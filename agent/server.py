"""MI300X host-side agent. Never run on the local CPU-only Windows machine.

Run on the Linux MI300X server, bound to loopback; access from Windows through
SSH -L 9877:127.0.0.1:9877 and Docker Desktop host.docker.internal.

Workers are vLLM instances. Multiple GPUs used by a TP worker constitute ONE
schedulable inference endpoint, not independent model-serving nodes.
"""
import asyncio
import hmac
import json
import os
import time
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from amdsmi_probe import probe_gpus

TOKEN = os.environ.get('MISSION_AGENT_TOKEN', '')
AGENT_ID = os.environ.get('MISSION_AGENT_ID', 'mi300x-host-1')
try:
    WORKERS = json.loads(os.environ.get('MI300X_WORKERS_JSON', '[]'))
except json.JSONDecodeError as exc:
    raise RuntimeError('MI300X_WORKERS_JSON must be valid JSON') from exc
if not TOKEN or len(TOKEN) < 16:
    raise RuntimeError('MISSION_AGENT_TOKEN required (minimum 16 characters)')
if not isinstance(WORKERS, list):
    raise RuntimeError('MI300X_WORKERS_JSON must contain a list')
for w in WORKERS:
    if not all(k in w for k in ('id', 'base_url', 'gpu_ids')) or not isinstance(w['gpu_ids'], list) or not w['gpu_ids']:
        raise RuntimeError('Each worker needs id, base_url, and nonempty gpu_ids')

app = FastAPI(title='AMD MI300X Runtime Agent', version='0.3.0')


def auth(token: str | None):
    if not token or not hmac.compare_digest(token, TOKEN):
        raise HTTPException(401, detail='Unauthorized')


def by_id(worker_id: str):
    result = next((w for w in WORKERS if w['id'] == worker_id), None)
    if result is None:
        raise HTTPException(404, detail='Unknown serving worker')
    return result


def headers():
    key = os.environ.get('VLLM_API_KEY', '')
    return {'Authorization': 'Bearer ' + key} if key else {}


async def describe_worker(w):
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(w['base_url'].rstrip('/') + '/v1/models', headers=headers())
            response.raise_for_status()
            models = [m['id'] for m in response.json().get('data', []) if 'id' in m]
            return {'id': w['id'], 'gpu_ids': [str(x) for x in w['gpu_ids']], 'models': models,
                    'ready': bool(models), 'max_concurrent_jobs': max(1, int(w.get('max_concurrent_jobs', 2))),
                    'reserve_gb_per_job': max(0, float(w.get('reserve_gb_per_job', 0)))}
    except (httpx.HTTPError, ValueError, KeyError):
        return {'id': w['id'], 'gpu_ids': [str(x) for x in w['gpu_ids']], 'models': [],
                'ready': False, 'max_concurrent_jobs': int(w.get('max_concurrent_jobs', 2)),
                'reserve_gb_per_job': max(0, float(w.get('reserve_gb_per_job', 0)))}


@app.get('/health')
def health():
    return {'status': 'running', 'agent': AGENT_ID}


@app.get('/v1/state')
async def state(x_mission_token: str | None = Header(None)):
    auth(x_mission_token)
    try:
        gpus = await asyncio.to_thread(probe_gpus)
    except Exception as e:
        # Real mode must fail closed when the GPU/ROCm sensor is absent.
        raise HTTPException(503, detail=f'AMD SMI unavailable: {type(e).__name__}: {e}')
    workers = await asyncio.gather(*(describe_worker(w) for w in WORKERS))
    return {'agent_id': AGENT_ID, 'sample_time': time.time(), 'source': 'amd_smi',
            'gpus': gpus, 'workers': workers}


class InferenceRequest(BaseModel):
    worker_id: str
    model: str = Field(min_length=1, max_length=300)
    prompt: str = Field(min_length=1, max_length=8192)
    max_tokens: int = Field(default=128, ge=1, le=8192)


@app.post('/v1/infer')
async def infer(request: InferenceRequest, x_mission_token: str | None = Header(None)):
    auth(x_mission_token)
    worker = by_id(request.worker_id)
    advertised = await describe_worker(worker)
    if not advertised['ready'] or request.model not in advertised['models']:
        raise HTTPException(503, detail='Model is not served by the selected ready vLLM endpoint')
    begin = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=5.0)) as client:
            response = await client.post(
                worker['base_url'].rstrip('/') + '/v1/completions', headers=headers(),
                json={'model': request.model, 'prompt': request.prompt,
                      'max_tokens': request.max_tokens, 'temperature': 0.0},
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, detail=f'vLLM execution failed: {str(exc)[:200]}')
    usage = payload.get('usage') or {}
    choices = payload.get('choices') or []
    return {'worker_id': request.worker_id, 'model': request.model,
            'duration_seconds': round(time.perf_counter() - begin, 4),
            'completion_tokens': usage.get('completion_tokens'),
            'prompt_tokens': usage.get('prompt_tokens'),
            'text': str(choices[0].get('text') or '')[:8192] if choices else '',
            'source': 'real_vllm'}
