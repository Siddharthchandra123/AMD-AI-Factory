"""Phase 10 operational safeguards for AMD AI Factory Mission Control.

Recovery semantics: queued jobs are reconstructed from PostgreSQL; interrupted
simulation jobs may be requeued; interrupted REAL vLLM jobs are failed closed,
never automatically retried because remote execution may have occurred.
One controller process / scheduler is assumed; not a distributed lease manager.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from sqlalchemy import select

RECOVERY_KEY = 'mission:hardening:last_recovery'


def reconcile_pending_jobs(session_factory, job_cls, cache, queue_names, now_utc):
    """Idempotently reconcile database queue state on controller startup.

    Commit durable DB status changes *before* rebuilding Redis queues. If a
    crash occurs between steps, the next restart reconstructs the queues.
    """
    counts = {'queued_restored': 0, 'simulation_running_requeued': 0,
              'real_running_failed_unknown': 0, 'other_running_failed': 0,
              'queue_ids_written': 0}
    with session_factory.begin() as db:
        pending = db.scalars(select(job_cls).where(job_cls.status.in_(['queued', 'running']))).all()
        for job in pending:
            if job.status != 'running':
                counts['queued_restored'] += 1
                continue
            if job.execution_mode == 'simulation':
                job.status = 'queued'
                job.gpu_id = None
                job.started_at = None
                job.completed_at = None
                job.duration_seconds = None
                job.queue_wait_seconds = None
                counts['simulation_running_requeued'] += 1
            else:
                # If the agent completed while the controller was down, status
                # cannot be established safely. Never retry automatically.
                job.status = 'failed'
                job.completed_at = now_utc()
                job.error_message = (
                    'Controller restarted with remote execution in flight; '
                    'outcome unknown. Not automatically retried.'
                )
                counts['real_running_failed_unknown' if job.execution_mode == 'mi300x'
                       else 'other_running_failed'] += 1

    with session_factory() as db:
        queued = db.scalars(select(job_cls).where(job_cls.status == 'queued')
                            .order_by(job_cls.created_at, job_cls.id)).all()
        entries = {priority: [] for priority in queue_names}
        for job in queued:
            # Malformed priority cannot be safely dispatched; flag in counts.
            if job.priority in entries:
                entries[job.priority].append(job.id)
            else:
                counts['unrecognized_priority'] = counts.get('unrecognized_priority', 0) + 1
    # One atomic Redis transaction replaces all stale/duplicated queue IDs.
    with cache.pipeline(transaction=True) as pipe:
        pipe.delete(*queue_names.values())
        for priority, ids in entries.items():
            if ids:
                pipe.lpush(queue_names[priority], *ids)
                counts['queue_ids_written'] += len(ids)
        pipe.execute()
    summary = {'at_utc': datetime.now(timezone.utc).isoformat(),
               'semantics': 'postgres-rebuild; real-inflight-unknown-not-retried',
               'counts': counts}
    cache.set(RECOVERY_KEY, json.dumps(summary))
    return summary


def read_recovery_status(cache):
    raw = cache.get(RECOVERY_KEY)
    if not raw:
        return {'available': False, 'message': 'No recovery record in Redis'}
    try:
        return {'available': True, **json.loads(raw)}
    except (ValueError, TypeError):
        return {'available': False, 'message': 'Recovery record unreadable'}


def worker_health_summary(mode: str, nodes: list[dict]):
    """Report known worker states. Does not infer remote side effects."""
    counts = {'healthy': 0, 'draining': 0, 'stale': 0, 'unavailable': 0,
              'high_load': 0, 'other': 0}
    result = []
    for node in nodes:
        health = str(node.get('health', 'unknown'))
        counts[health if health in counts else 'other'] += 1
        ready = bool(node.get('ready', health == 'healthy'))
        result.append({'id': node.get('id'), 'health': health, 'ready': ready,
                       'draining': bool(node.get('draining', False)),
                       'active_jobs': int(node.get('active_jobs') or 0),
                       'last_seen_seconds': node.get('last_seen_seconds')})
    return {'mode': mode, 'counts': counts, 'nodes': result,
            'real_inflight_note': 'A stale real worker is excluded from new placement; in-flight outcome is unknown until response/timeout. No automatic retry.'}


def authorized_write_request(method: str, path: str, supplied: str, configured: str) -> bool:
    """Optional dev-local write gate. Never replaces perimeter authentication."""
    import hmac
    if not configured or not path.startswith('/api/') or method.upper() in ('GET', 'HEAD', 'OPTIONS'):
        return True
    return hmac.compare_digest(supplied or '', configured)
