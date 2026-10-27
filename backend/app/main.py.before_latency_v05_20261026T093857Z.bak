"""AMD AI Factory Mission Control v0.3 — dynamically scheduled simulation and MI300X modes.

CPU-only Windows runs simulation. Real inference is explicitly enabled only after
an authenticated MI300X agent reports actual SMI telemetry AND ready vLLM workers.
"""
import asyncio
import csv
from contextlib import asynccontextmanager
from datetime import timedelta
from io import StringIO
import json
import os
import statistics
import time
import uuid

import redis
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse
from prometheus_client import Counter, Gauge, Histogram, make_asgi_app
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select, text

from .database import Base, InferenceJob, SessionLocal, engine
from .live_runtime import LiveRegistry
from .scheduler import (MODEL_MEMORY_GB, VALID_POLICIES, VALID_QUEUE_POLICIES,
    PLACEMENT_POLICIES, QUEUE_POLICIES, QueueCandidate,
    estimated_simulation_seconds, rank_queue, select_node)
from .simulator import RuntimeJob, VirtualCluster, VirtualGPU, now_utc

REDIS_URL = os.getenv('REDIS_URL', 'redis://redis:6379/0')
cache = redis.Redis.from_url(REDIS_URL, decode_responses=True)
queue_names = {p: f'mission:queue:{p}' for p in ('high', 'normal', 'low')}
cluster = VirtualCluster(count=max(1, min(16, int(os.getenv('SIM_GPU_COUNT', '4')))))
live = LiveRegistry()
active_tasks: set[asyncio.Task] = set()
_last_metric_labels: set[tuple[str, str]] = set()
loadtest_task: asyncio.Task | None = None

GPU_UTILIZATION = Gauge('mission_gpu_utilization_percent', 'GPU utilization; see source label', ['gpu_id', 'source'])
GPU_MEMORY = Gauge('mission_gpu_hbm_used_gb', 'GPU VRAM usage; see source label', ['gpu_id', 'source'])
GPU_TEMP = Gauge('mission_gpu_temperature_c', 'GPU sensor temperature; see source label', ['gpu_id', 'source'])
GPU_HEALTH = Gauge('mission_endpoint_available', 'Whether a worker is eligible for routing', ['gpu_id', 'source'])
QUEUED = Gauge('mission_pending_jobs', 'Queued inference jobs')
RUNNING = Gauge('mission_running_jobs', 'Running inference jobs')
COMPLETED = Counter('mission_completed_jobs_total', 'Completed jobs', ['mode'])
FAILED = Counter('mission_failed_jobs_total', 'Failed jobs', ['mode'])
SUBMITTED = Counter('mission_submitted_jobs_total', 'Submitted jobs', ['mode'])
DURATIONS = Histogram('mission_job_duration_seconds', 'Observed job duration', ['mode'])
TOKENS = Counter('mission_completion_tokens_total', 'Actual completion tokens from vLLM (real only)')
DISPATCHES = Counter('mission_scheduler_dispatches_total', 'Jobs dispatched', ['placement_policy', 'queue_policy', 'mode'])


class JobRequest(BaseModel):
    model: str = Field(default='model-7b', min_length=1, max_length=300)
    prompt: str = Field(default='Explain what GPU scheduling is.', min_length=1, max_length=8192)
    prompt_tokens: int = Field(default=512, ge=1, le=32000)
    output_tokens: int = Field(default=256, ge=1, le=8192)
    priority: str = Field(default='normal')
    tenant: str = Field(default='default', min_length=1, max_length=64, pattern=r'^[A-Za-z0-9_-]+$')
    deadline_seconds: int | None = Field(default=None, ge=1, le=86400)


class BatchRequest(JobRequest):
    count: int = Field(default=8, ge=1, le=50)


class PolicyRequest(BaseModel):
    policy: str


class RuntimeRequest(BaseModel):
    mode: str


class SimNodeRequest(BaseModel):
    memory_total_gb: float = Field(default=192.0, ge=8, le=512)
    max_concurrent_jobs: int = Field(default=2, ge=1, le=32)


class DrainRequest(BaseModel):
    draining: bool


class SimModelRequest(BaseModel):
    id: str = Field(min_length=1, max_length=80, pattern=r'^[A-Za-z0-9_.-]+$')
    memory_gb: float = Field(ge=0.1, le=400)


class LoadTestRequest(BaseModel):
    requests_per_second: float = Field(default=1.0, ge=0.2, le=5.0)
    duration_seconds: int = Field(default=30, ge=1, le=120)
    batch_size: int = Field(default=1, ge=1, le=10)
    model: str = Field(default='model-7b')


class ThresholdRequest(BaseModel):
    utilization_warning_percent: float = Field(95, ge=1, le=100)
    temperature_warning_c: float = Field(85, ge=0, le=120)
    pending_jobs_warning: int = Field(16, ge=1, le=100000)


def get_mode():
    value = cache.get('mission:runtime_mode') or 'simulation'
    return value if value in ('simulation', 'mi300x') else 'simulation'


def get_policy():
    value = cache.get('mission:policy') or 'round_robin'
    return value if value in VALID_POLICIES else 'round_robin'


def get_queue_policy():
    value = cache.get('mission:queue_policy') or 'priority_fifo'
    return value if value in VALID_QUEUE_POLICIES else 'priority_fifo'


def get_drained():
    return cache.smembers('mission:drained_nodes')


def persist_simulator():
    cache.set('mission:sim_nodes', json.dumps([{
        'id': n.id, 'memory_total_gb': n.memory_total_gb,
        'max_concurrent_jobs': n.max_concurrent_jobs, 'draining': n.draining,
    } for n in cluster.nodes]))


def restore_simulator():
    saved = cache.get('mission:sim_nodes')
    if not saved:
        return
    try:
        records = json.loads(saved)
        if not records or len(records) > 32:
            return
        cluster.nodes = [VirtualGPU(
            id=str(n['id']), memory_total_gb=float(n['memory_total_gb']),
            max_concurrent_jobs=int(n['max_concurrent_jobs']), draining=bool(n.get('draining', False)),
        ) for n in records]
        cluster.rr_cursor = 0
    except (ValueError, TypeError, KeyError):
        print('Ignoring damaged simulator config in Redis', flush=True)


def get_profiles():
    saved = cache.get('mission:sim_profiles')
    return json.loads(saved) if saved else dict(MODEL_MEMORY_GB)


def get_thresholds():
    saved = cache.get('mission:thresholds')
    return json.loads(saved) if saved else ThresholdRequest().model_dump()


def pending_count():
    return sum(cache.llen(key) for key in queue_names.values())


def model_catalog():
    if get_mode() == 'mi300x':
        return [{'id': name, 'source': 'real_vllm', 'memory_gb': None} for name in live.models()]
    return [{'id': name, 'source': 'simulation', 'memory_gb': value} for name, value in get_profiles().items()]


def add_job(request: JobRequest):
    mode = get_mode()
    available = {m['id'] for m in model_catalog()}
    if request.model not in available:
        raise HTTPException(422, f'Model {request.model!r} is not available in {mode} mode; check /api/models')
    if request.priority not in queue_names:
        raise HTTPException(422, 'Priority must be high, normal or low')
    job = InferenceJob(id=str(uuid.uuid4()), model=request.model,
        prompt=request.prompt, prompt_tokens=request.prompt_tokens, output_tokens=request.output_tokens,
        priority=request.priority, tenant=request.tenant, execution_mode=mode,
        deadline_at=now_utc() + timedelta(seconds=request.deadline_seconds) if request.deadline_seconds else None,
        status='queued')
    with SessionLocal.begin() as db:
        db.add(job)
    cache.lpush(queue_names[job.priority], job.id)
    SUBMITTED.labels(mode).inc()
    return job.to_dict()


def queue_snapshot():
    queue_ids = {}
    for priority, key in queue_names.items():
        for job_id in cache.lrange(key, 0, -1):
            queue_ids.setdefault(job_id, priority)
    return queue_ids


def choose_effective_policy(policy: str, candidates: list, queued_count: int):
    if policy != 'auto':
        return policy
    if not candidates:
        return 'adaptive'
    if queued_count > len(candidates) * 3:
        return 'least_connections'
    utilizations = [n.gpu_utilization for n in candidates]
    if len(utilizations) >= 2 and max(utilizations) - min(utilizations) > 18:
        return 'least_loaded'
    return 'adaptive'


def real_estimated_seconds(model: str, output_tokens: int) -> float:
    """EWMA trained on completed jobs; until then, a heuristic (not a measured prediction)."""
    estimate = cache.get('mission:latency_ewma:' + model)
    if estimate is not None:
        return max(.1, float(estimate) * max(1, output_tokens) / 128)
    return max(.5, output_tokens / 100)


def queue_ranked(waiting: list[InferenceJob], mode: str, active_by_tenant: dict[str, int]):
    profiles = get_profiles()
    candidates = [QueueCandidate(
        id=job.id, priority=job.priority, created_timestamp=job.created_at.timestamp(),
        estimated_seconds=estimated_simulation_seconds(job.prompt_tokens, job.output_tokens, profiles.get(job.model, 0))
            if mode == 'simulation' else real_estimated_seconds(job.model, job.output_tokens),
        tenant=job.tenant,
        deadline_timestamp=job.deadline_at.timestamp() if job.deadline_at else None,
    ) for job in waiting]
    return rank_queue(candidates, get_queue_policy(), now_timestamp=now_utc().timestamp(),
                      active_by_tenant=active_by_tenant)


def _get_workload(db):
    queue_ids = queue_snapshot()
    if not queue_ids:
        return {}, [], {}
    waiting = db.scalars(select(InferenceJob).where(InferenceJob.id.in_(queue_ids))).all()
    by_id = {j.id: j for j in waiting if j.status == 'queued'}
    for job_id, priority in queue_ids.items():
        if job_id not in by_id:
            cache.lrem(queue_names[priority], 0, job_id)
    active_by_tenant = dict(db.execute(select(InferenceJob.tenant, func.count())
        .where(InferenceJob.status == 'running').group_by(InferenceJob.tenant)).all())
    return by_id, queue_ranked(list(by_id.values()), get_mode(), active_by_tenant), active_by_tenant


def sim_tick():
    for job_id, _, duration in cluster.completed():
        with SessionLocal.begin() as db:
            job = db.get(InferenceJob, job_id)
            if job and job.status == 'running':
                job.status = 'completed'
                job.completed_at = now_utc()
                job.duration_seconds = duration
                COMPLETED.labels('simulation').inc()
                DURATIONS.labels('simulation').observe(duration)
    for _ in range(16):
        with SessionLocal.begin() as db:
            by_id, ranked, _ = _get_workload(db)
            if not by_id:
                break
            chosen_record = None
            for next_job in ranked:
                job = by_id[next_job.id]
                if job.execution_mode != 'simulation':
                    continue
                required = get_profiles().get(job.model)
                if required is None:
                    continue
                candidates = [n.candidate() for n in cluster.nodes if not n.draining]
                policy = get_policy()
                effective = choose_effective_policy(policy, candidates, len(ranked))
                candidate, cursor = select_node(candidates, required, effective, cluster.rr_cursor,
                    model=job.model, job_key=job.model if effective == 'rendezvous_hash' else job.id)
                if candidate is not None:
                    chosen_record = (job, candidate, cursor, required, effective)
                    break
            if chosen_record is None:
                break
            job, candidate, cursor, required, effective = chosen_record
            if cache.lrem(queue_names[job.priority], 1, job.id) != 1:
                continue
            cluster.rr_cursor = cursor
            node = next(n for n in cluster.nodes if n.id == candidate.id)
            runtime = estimated_simulation_seconds(job.prompt_tokens, job.output_tokens, required)
            start = time.monotonic()
            node.active[job.id] = RuntimeJob(job.id, start, start + runtime, required,
                35.0 + min(10, required / 12))
            node.cached_models.add(job.model)
            job.status, job.gpu_id, job.started_at = 'running', node.id, now_utc()
            job.queue_wait_seconds = round((job.started_at - job.created_at).total_seconds(), 3)
            DISPATCHES.labels(effective, get_queue_policy(), 'simulation').inc()


async def perform_real(job_id: str, node_id: str, model: str, prompt: str, max_tokens: int):
    node = live.nodes[node_id]
    try:
        response = await live.infer(node, model, prompt, max_tokens)
        with SessionLocal.begin() as db:
            job = db.get(InferenceJob, job_id)
            if job and job.status == 'running':
                job.status = 'completed'
                job.completed_at = now_utc()
                job.duration_seconds = response['duration_seconds']
                job.response_text = response.get('text', '')[:8192]
                job.completion_tokens_actual = response.get('completion_tokens')
                COMPLETED.labels('mi300x').inc()
                DURATIONS.labels('mi300x').observe(job.duration_seconds)
                if isinstance(job.completion_tokens_actual, int):
                    TOKENS.inc(max(0, job.completion_tokens_actual))
                # Runtime-normalized, model-specific EWMA for future SJF/HRRN decisions.
                actual = max(.01, job.duration_seconds) * 128 / max(1, job.output_tokens)
                key = 'mission:latency_ewma:' + job.model
                old = cache.get(key)
                cache.set(key, str(.3 * actual + .7 * float(old) if old is not None else actual))
    except Exception as exc:
        with SessionLocal.begin() as db:
            job = db.get(InferenceJob, job_id)
            if job and job.status == 'running':
                job.status = 'failed'
                job.completed_at = now_utc()
                job.error_message = str(exc)[:400]
                FAILED.labels('mi300x').inc()
    finally:
        node.active.discard(job_id)


def real_tick():
    for _ in range(16):
        with SessionLocal.begin() as db:
            by_id, ranked, _ = _get_workload(db)
            if not by_id:
                break
            chosen_record = None
            for ranked_job in ranked:
                job = by_id[ranked_job.id]
                if job.execution_mode != 'mi300x':
                    continue
                candidates = live.candidates(job.model, get_drained(), get_policy())
                effective = choose_effective_policy(get_policy(), candidates, len(ranked))
                # Model already lives in vLLM: no fictional extra model-weight allocation.
                # Optional reserve_gb_per_job is configured by the GPU operator.
                selected, cursor = select_node(candidates, 0.0, effective, cluster.rr_cursor,
                    model=job.model, job_key=job.model if effective == 'rendezvous_hash' else job.id)
                if selected is not None:
                    chosen_record = (job, selected, cursor, effective)
                    break
            if chosen_record is None:
                break
            job, selected, cursor, effective = chosen_record
            if cache.lrem(queue_names[job.priority], 1, job.id) != 1:
                continue
            cluster.rr_cursor = cursor
            node = live.nodes[selected.id]
            node.active.add(job.id)
            job.status, job.gpu_id, job.started_at = 'running', node.id, now_utc()
            job.queue_wait_seconds = round((job.started_at - job.created_at).total_seconds(), 3)
            task = asyncio.create_task(perform_real(job.id, node.id, job.model,
                job.prompt or 'Explain GPU scheduling.', job.output_tokens))
            active_tasks.add(task)
            task.add_done_callback(active_tasks.discard)
            DISPATCHES.labels(effective, get_queue_policy(), 'mi300x').inc()


def get_snapshots():
    return cluster.snapshot() if get_mode() == 'simulation' else live.snapshots(get_drained())


def update_metrics():
    global _last_metric_labels
    nodes = get_snapshots()
    current = {(n['id'], n['source']) for n in nodes}
    for labels in _last_metric_labels - current:
        for metric in (GPU_UTILIZATION, GPU_MEMORY, GPU_TEMP, GPU_HEALTH):
            try:
                metric.remove(*labels)
            except KeyError:
                pass
    _last_metric_labels = current
    for node in nodes:
        labels = (node['id'], node['source'])
        for metric, key in ((GPU_UTILIZATION, 'utilization_percent'),
                            (GPU_MEMORY, 'memory_used_gb'), (GPU_TEMP, 'temperature_c')):
            if node.get(key) is not None and node.get('health') != 'stale':
                metric.labels(*labels).set(node[key])
            else:
                try:
                    metric.remove(*labels)
                except KeyError:
                    pass
        GPU_HEALTH.labels(*labels).set(1 if node.get('ready') and not node.get('draining') else 0)
    QUEUED.set(pending_count())
    RUNNING.set(sum(n['active_jobs'] for n in nodes))


async def worker_loop():
    while True:
        try:
            await live.refresh()
            if get_mode() == 'simulation':
                sim_tick()
            else:
                real_tick()
            update_metrics()
        except Exception as exc:
            print(f'worker loop error: {exc}', flush=True)
        await asyncio.sleep(1.5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        for sql in [
            "ALTER TABLE inference_jobs ADD COLUMN IF NOT EXISTS tenant VARCHAR(64) NOT NULL DEFAULT 'default'",
            'ALTER TABLE inference_jobs ADD COLUMN IF NOT EXISTS deadline_at TIMESTAMPTZ',
            "ALTER TABLE inference_jobs ADD COLUMN IF NOT EXISTS execution_mode VARCHAR(16) NOT NULL DEFAULT 'simulation'",
            'ALTER TABLE inference_jobs ADD COLUMN IF NOT EXISTS prompt TEXT',
            'ALTER TABLE inference_jobs ADD COLUMN IF NOT EXISTS response_text TEXT',
            'ALTER TABLE inference_jobs ADD COLUMN IF NOT EXISTS completion_tokens_actual INTEGER',
            'ALTER TABLE inference_jobs ADD COLUMN IF NOT EXISTS error_message TEXT',
        ]:
            connection.execute(text(sql))
    cache.ping()
    restore_simulator()
    # Simulation can be retried, but an interrupted real vLLM request must NEVER
    # be silently resubmitted (could generate duplicate processing/billing).
    with SessionLocal.begin() as db:
        records = db.scalars(select(InferenceJob).where(InferenceJob.status.in_(['queued', 'running']))).all()
        for job in records:
            if job.execution_mode == 'mi300x' and job.status == 'running':
                job.status = 'failed'
                job.error_message = 'Controller restarted while real inference was in flight; outcome unknown, not retried.'
                job.completed_at = now_utc()
                cache.lrem(queue_names[job.priority], 0, job.id)
                continue
            job.status = 'queued'
            job.gpu_id = None
            job.started_at = None
            cache.lrem(queue_names[job.priority], 0, job.id)
            cache.lpush(queue_names[job.priority], job.id)
    await live.refresh()
    task = asyncio.create_task(worker_loop())
    try:
        yield
    finally:
        task.cancel()
        if loadtest_task:
            loadtest_task.cancel()
        for real in list(active_tasks):
            real.cancel()
        await asyncio.gather(task, *list(active_tasks), *([loadtest_task] if loadtest_task else []), return_exceptions=True)


app = FastAPI(title='AMD AI Factory Mission Control', version='0.3.0', lifespan=lifespan)
app.add_middleware(CORSMiddleware,
    allow_origins=['http://localhost:3000', 'http://127.0.0.1:3000'],
    allow_methods=['GET', 'POST', 'PUT', 'DELETE'], allow_headers=['Content-Type'])
app.mount('/metrics', make_asgi_app())


@app.get('/health')
def health():
    with engine.connect() as db:
        db.execute(text('SELECT 1'))
    cache.ping()
    return {'status': 'ok', 'version': '0.3.0', 'mode': get_mode(),
            'live_agents_configured': len(live.urls)}


@app.get('/api/cluster')
def get_cluster():
    nodes = get_snapshots()
    available_util = [n['utilization_percent'] for n in nodes if n.get('utilization_percent') is not None]
    with SessionLocal() as db:
        completed = db.scalar(select(func.count()).select_from(InferenceJob).where(InferenceJob.status == 'completed')) or 0
    mode = get_mode()
    return {'mode': mode,
        'source_notice': 'Synthetic simulated GPU data. Not real AMD hardware measurements.' if mode == 'simulation'
            else 'AMD SMI data from remote agent; metrics are unavailable if sensors/agent are not healthy.',
        'policy': get_policy(), 'queue_policy': get_queue_policy(), 'nodes': nodes,
        'summary': {'node_count': len(nodes), 'avg_utilization_percent': round(statistics.mean(available_util), 1)
            if available_util else None, 'running_jobs': sum(n['active_jobs'] for n in nodes),
            'queued_jobs': pending_count(), 'completed_jobs': completed}}


@app.get('/api/runtime')
def runtime_status():
    return {'mode': get_mode(), 'configured_agent_urls': live.urls,
            'connected_workers': len([n for n in live.snapshots() if n['ready']]),
            'advertised_models': live.models(), 'agent_errors': live.agent_errors,
            'reconfigure_agents_by_env': True,
            'notice': 'Switching to real mode requires a ready agent and an idle queue.'}


@app.put('/api/runtime')
def runtime_change(request: RuntimeRequest):
    if request.mode not in ('simulation', 'mi300x'):
        raise HTTPException(422, 'mode must be simulation or mi300x')
    if request.mode == get_mode():
        return runtime_status()
    if pending_count() or any(n.active for n in cluster.nodes) or any(n.active for n in live.nodes.values()):
        raise HTTPException(409, 'Wait for queued/running jobs to finish before switching modes')
    if request.mode == 'mi300x' and not any(live.candidates(m, get_drained()) for m in live.models()):
        raise HTTPException(409, 'No ready MI300X inference endpoint with valid AMD SMI telemetry')
    cache.set('mission:runtime_mode', request.mode)
    return runtime_status()


@app.get('/api/models')
def models():
    return {'mode': get_mode(), 'models': model_catalog()}


@app.get('/api/jobs')
def jobs(limit: int = Query(default=50, ge=1, le=500)):
    with SessionLocal() as db:
        records = db.scalars(select(InferenceJob).order_by(desc(InferenceJob.created_at)).limit(limit)).all()
        return {'jobs': [x.to_dict() for x in records]}


@app.get('/api/jobs/export', response_class=PlainTextResponse)
def jobs_export():
    cols = ['id', 'model', 'priority', 'tenant', 'execution_mode', 'status', 'gpu_id',
            'prompt_tokens', 'output_tokens', 'completion_tokens_actual', 'created_at',
            'started_at', 'completed_at', 'queue_wait_seconds', 'duration_seconds', 'error_message']
    out = StringIO()
    writer = csv.DictWriter(out, fieldnames=cols)
    writer.writeheader()
    with SessionLocal() as db:
        for job in db.scalars(select(InferenceJob).order_by(InferenceJob.created_at)):
            payload = job.to_dict()
            writer.writerow({k: payload[k] for k in cols})
    return PlainTextResponse(out.getvalue(), media_type='text/csv',
        headers={'Content-Disposition': 'attachment; filename=mission-jobs.csv'})


@app.post('/api/jobs', status_code=201)
def create_job(request: JobRequest):
    return add_job(request)


@app.post('/api/jobs/batch', status_code=201)
def create_batch(request: BatchRequest):
    return {'jobs': [add_job(request) for _ in range(request.count)]}


@app.put('/api/policy')
def policy_update(request: PolicyRequest):
    if request.policy not in VALID_POLICIES:
        raise HTTPException(422, f'Choose one of {sorted(VALID_POLICIES)}')
    cache.set('mission:policy', request.policy)
    return {'policy': request.policy}


@app.put('/api/queue-policy')
def queue_policy_update(request: PolicyRequest):
    if request.policy not in VALID_QUEUE_POLICIES:
        raise HTTPException(422, f'Choose one of {sorted(VALID_QUEUE_POLICIES)}')
    cache.set('mission:queue_policy', request.policy)
    return {'queue_policy': request.policy}


@app.get('/api/policies')
def policies():
    return {'placement': [{'id': k, 'description': v} for k, v in PLACEMENT_POLICIES.items()],
            'queue': [{'id': k, 'description': v} for k, v in QUEUE_POLICIES.items()],
            'active_placement': get_policy(), 'active_queue': get_queue_policy(),
            'mode': get_mode(), 'preemption_supported': False}


@app.post('/api/simulator/nodes', status_code=201)
def simulator_add(request: SimNodeRequest):
    if get_mode() != 'simulation':
        raise HTTPException(409, 'Simulator can only be modified in simulation mode')
    if len(cluster.nodes) >= 32:
        raise HTTPException(409, 'Simulator is limited to 32 nodes')
    node = cluster.add(total_memory_gb=request.memory_total_gb, max_concurrent_jobs=request.max_concurrent_jobs)
    persist_simulator()
    return node.as_dict()


@app.delete('/api/simulator/nodes/{node_id}')
def simulator_remove(node_id: str):
    if get_mode() != 'simulation':
        raise HTTPException(409, 'Simulator can only be modified in simulation mode')
    if not cluster.remove(node_id):
        raise HTTPException(409, 'Node absent, active, or last remaining node')
    persist_simulator()
    return {'removed': node_id}


@app.put('/api/nodes/{node_id:path}/drain')
def drain_node(node_id: str, request: DrainRequest):
    if get_mode() == 'simulation':
        node = next((n for n in cluster.nodes if n.id == node_id), None)
        if node is None:
            raise HTTPException(404, 'Unknown node')
        node.draining = request.draining
        persist_simulator()
    else:
        if node_id not in live.nodes:
            raise HTTPException(404, 'Unknown worker')
        if request.draining:
            cache.sadd('mission:drained_nodes', node_id)
        else:
            cache.srem('mission:drained_nodes', node_id)
    return {'id': node_id, 'draining': request.draining}


@app.get('/api/settings')
def settings_get():
    return get_thresholds()


@app.put('/api/settings')
def settings_update(request: ThresholdRequest):
    cache.set('mission:thresholds', request.model_dump_json())
    return request


@app.get('/api/alerts')
def alerts():
    conf = get_thresholds()
    result = []
    for node in get_snapshots():
        if node['health'] in ('stale', 'unavailable'):
            result.append({'level': 'critical', 'node': node['id'], 'message': f"Worker {node['health']}"})
        if node.get('utilization_percent') is not None and node['utilization_percent'] >= conf['utilization_warning_percent']:
            result.append({'level': 'warning', 'node': node['id'], 'message': 'GPU utilization threshold exceeded'})
        if node.get('temperature_c') is not None and node['temperature_c'] >= conf['temperature_warning_c']:
            result.append({'level': 'warning', 'node': node['id'], 'message': 'GPU temperature threshold exceeded'})
    if pending_count() >= conf['pending_jobs_warning']:
        result.append({'level': 'warning', 'node': 'scheduler', 'message': 'Backlog threshold exceeded'})
    return {'mode': get_mode(), 'alerts': result, 'total': len(result)}


@app.get('/api/info')
def info():
    return {'project': 'AMD AI Factory Mission Control', 'mode': get_mode(),
            'gpu_count': len(get_snapshots()), 'models': [m['id'] for m in model_catalog()],
            'policies': sorted(VALID_POLICIES), 'queue_policies': sorted(VALID_QUEUE_POLICIES),
            'gpu_data_is_real': get_mode() == 'mi300x' and any(n.get('ready') for n in get_snapshots()), 'version': '0.3.0'}


@app.get('/api/events/stream')
async def events():
    async def push():
        while True:
            try:
                payload = {'cluster': get_cluster(), 'jobs': jobs(limit=30)['jobs'],
                           'alerts': alerts(), 'runtime': runtime_status(), 'models': model_catalog(), 'loadtest': loadtest_status()}
                yield 'event: state\ndata: ' + json.dumps(payload, default=str) + '\n\n'
            except Exception as exc:
                yield 'event: error\ndata: ' + json.dumps({'error': str(exc)[:200]}) + '\n\n'
            await asyncio.sleep(2)
    return StreamingResponse(push(), media_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@app.post('/api/models/sim', status_code=201)
def sim_model_add(request: SimModelRequest):
    if get_mode() != 'simulation':
        raise HTTPException(409, 'Only simulation profiles can be modified')
    profiles = get_profiles()
    profiles[request.id] = request.memory_gb
    cache.set('mission:sim_profiles', json.dumps(profiles))
    return {'id': request.id, 'memory_gb': request.memory_gb}


@app.delete('/api/models/sim/{model_id}')
def sim_model_delete(model_id: str):
    if get_mode() != 'simulation':
        raise HTTPException(409, 'Only simulation profiles can be modified')
    with SessionLocal() as db:
        outstanding = db.scalar(select(func.count()).select_from(InferenceJob).where(
            InferenceJob.model == model_id, InferenceJob.status.in_(['queued', 'running'])))
    if outstanding:
        raise HTTPException(409, 'Model has queued/running jobs')
    profiles = get_profiles()
    if model_id not in profiles or len(profiles) <= 1:
        raise HTTPException(409, 'Model not found or last remaining profile')
    del profiles[model_id]
    cache.set('mission:sim_profiles', json.dumps(profiles))
    return {'removed': model_id}


async def synthetic_load_loop(req: LoadTestRequest):
    deadline = time.monotonic() + req.duration_seconds
    try:
        while time.monotonic() < deadline and get_mode() == 'simulation':
            for _ in range(req.batch_size):
                try:
                    add_job(JobRequest(model=req.model, output_tokens=128))
                except Exception as exc:
                    print(f'Load generator stopped: {exc}', flush=True)
                    return
            await asyncio.sleep(max(0.05, req.batch_size / req.requests_per_second))
    finally:
        cache.set('mission:loadtest_active', '0')


@app.post('/api/loadtest/start')
async def loadtest_start(request: LoadTestRequest):
    global loadtest_task
    if get_mode() != 'simulation':
        raise HTTPException(409, 'Automatic load generation only permitted in simulation mode')
    if request.model not in get_profiles():
        raise HTTPException(422, 'Unknown simulated model')
    if loadtest_task is not None and not loadtest_task.done():
        raise HTTPException(409, 'Load test already running')
    cache.set('mission:loadtest_active', '1')
    loadtest_task = asyncio.create_task(synthetic_load_loop(request))
    return {'status': 'started', 'simulation_only': True, **request.model_dump()}


@app.post('/api/loadtest/stop')
async def loadtest_stop():
    global loadtest_task
    if loadtest_task and not loadtest_task.done():
        loadtest_task.cancel()
        await asyncio.gather(loadtest_task, return_exceptions=True)
    cache.set('mission:loadtest_active', '0')
    return {'status': 'stopped'}


@app.get('/api/loadtest')
def loadtest_status():
    return {'active': bool(loadtest_task and not loadtest_task.done()), 'simulation_only': True}
