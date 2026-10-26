"""Dynamic MI300X agent polling and endpoint-level scheduling state.

The controller schedules vLLM *endpoints*, not raw GPU devices. A worker with
GPU IDs [0,1,...,7] is one pool if the server uses tensor parallelism.
"""
from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
import os
import time
from typing import Any
import httpx

from .scheduler import Candidate


@dataclass
class LiveNode:
    id: str
    agent_url: str
    agent_id: str
    worker_id: str
    gpu_ids: list[str]
    models: list[str]
    ready: bool
    max_concurrent_jobs: int
    reserve_gb_per_job: float
    gpu_samples: list[dict[str, Any]]
    sampled_at: float
    active: set[str] = field(default_factory=set)
    cached_models: set[str] = field(default_factory=set)

    @staticmethod
    def numeric_stats(values, fn):
        available = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
        return fn(available) if available else None

    def snapshot(self, now: float, timeout: float = 12.0, drained: bool = False) -> dict:
        gpus = self.gpu_samples
        min_stat = lambda key: self.numeric_stats((x.get(key) for x in gpus), min)
        max_stat = lambda key: self.numeric_stats((x.get(key) for x in gpus), max)
        sum_stat = lambda key: self.numeric_stats((x.get(key) for x in gpus), sum)
        total = min_stat('memory_total_gb')
        used = max_stat('memory_used_gb')
        fresh = now - self.sampled_at < timeout
        ready = self.ready and fresh and bool(gpus)
        health = 'stale' if not fresh else ('draining' if drained else ('healthy' if ready else 'unavailable'))
        util = max_stat('utilization_percent')
        if health == 'healthy' and util is not None and util >= 95:
            health = 'high_load'
        return {'id': self.id, 'model': ' + '.join(sorted(set(x.get('model', 'AMD GPU') for x in gpus))),
                'source': 'amd_smi', 'memory_total_gb': total, 'memory_used_gb': used,
                'utilization_percent': util, 'temperature_c': max_stat('temperature_c'),
                'power_watts': sum_stat('power_watts'), 'active_jobs': len(self.active),
                'health': health, 'gpu_ids': self.gpu_ids, 'models': self.models,
                'ready': ready, 'draining': drained, 'agent_id': self.agent_id,
                'last_seen_seconds': round(max(0, now - self.sampled_at), 1),
                'max_concurrent_jobs': self.max_concurrent_jobs}

    def candidate(self, now: float, drained: bool = False, *, require_temperature=False, require_power=False) -> Candidate | None:
        s = self.snapshot(now, drained=drained)
        if not s['ready'] or drained:
            return None
        # Fail closed when AMD SMI could not report VRAM/utilization.
        if s['memory_total_gb'] is None or s['memory_used_gb'] is None or s['utilization_percent'] is None:
            return None
        if require_temperature and s['temperature_c'] is None:
            return None
        if require_power and s['power_watts'] is None:
            return None
        return Candidate(
            id=self.id, total_memory_gb=s['memory_total_gb'], used_memory_gb=s['memory_used_gb']
            + len(self.active) * self.reserve_gb_per_job,
            gpu_utilization=s['utilization_percent'], active_jobs=len(self.active),
            max_concurrent_jobs=self.max_concurrent_jobs,
            temperature_c=s['temperature_c'] if s['temperature_c'] is not None else 95.0,
            power_watts=s['power_watts'] if s['power_watts'] is not None else 750.0,
            cached_models=tuple(self.models),
        )


class LiveRegistry:
    def __init__(self):
        self.urls = [x.strip().rstrip('/') for x in os.getenv('MI300X_AGENT_URLS', '').split(',') if x.strip()]
        self.token = os.getenv('MISSION_AGENT_TOKEN', '')
        self.nodes: dict[str, LiveNode] = {}
        self.agent_errors: dict[str, str] = {}
        self._last_agent_nodes: dict[str, set[str]] = {}

    async def refresh(self):
        if not self.urls or not self.token:
            return
        async with httpx.AsyncClient(timeout=5.0) as client:
            await asyncio.gather(*(self._refresh_one(client, url) for url in self.urls))

    async def _refresh_one(self, client: httpx.AsyncClient, url: str):
        try:
            response = await client.get(url + '/v1/state', headers={'X-Mission-Token': self.token})
            response.raise_for_status()
            result = response.json()
            if result.get('source') != 'amd_smi':
                raise ValueError('Rejected non-AMD telemetry')
            agent_id = str(result['agent_id'])
            gpus = {str(g['id']): g for g in result['gpus']}
            now = time.monotonic()
            active_ids: set[str] = set()
            claimed: set[str] = set()
            for worker in result['workers']:
                worker_id = str(worker['id'])
                resource_id = agent_id + '/' + worker_id
                indices = [str(x) for x in worker['gpu_ids']]
                has_overlap = bool(claimed.intersection(indices))
                claimed.update(indices)
                samples = [gpus[i] for i in indices if i in gpus]
                ready = bool(worker.get('ready')) and len(samples) == len(indices) and not has_overlap
                existing = self.nodes.get(resource_id)
                self.nodes[resource_id] = LiveNode(
                    id=resource_id, agent_url=url, agent_id=agent_id, worker_id=worker_id,
                    gpu_ids=indices, models=[str(m) for m in worker.get('models', [])],
                    ready=ready, max_concurrent_jobs=max(1, int(worker.get('max_concurrent_jobs', 2))),
                    reserve_gb_per_job=max(0, float(worker.get('reserve_gb_per_job', 0))),
                    gpu_samples=samples, sampled_at=now,
                    active=existing.active if existing else set(),
                    cached_models=set(worker.get('models', [])),
                )
                active_ids.add(resource_id)
            previous = self._last_agent_nodes.get(url, set())
            for removed in previous - active_ids:
                if removed in self.nodes:
                    self.nodes[removed].ready = False
            self._last_agent_nodes[url] = active_ids
            self.agent_errors.pop(url, None)
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            self.agent_errors[url] = str(exc)[:250]
            # Last successful observation remains, but times out after 12s.

    def snapshots(self, drained: set[str] | None = None) -> list[dict]:
        drained = drained or set()
        now = time.monotonic()
        return [n.snapshot(now, drained=n.id in drained) for n in sorted(self.nodes.values(), key=lambda n: n.id)]

    def models(self) -> list[str]:
        now = time.monotonic()
        return sorted({m for n in self.nodes.values() if n.snapshot(now)['ready'] for m in n.models})

    def candidates(self, model: str, drained: set[str], policy: str | None = None) -> list[Candidate]:
        now = time.monotonic()
        result = []
        for node in self.nodes.values():
            if model in node.models:
                c = node.candidate(now, drained=node.id in drained,
                    require_temperature=policy == 'thermal_aware',
                    require_power=policy in ('power_aware', 'energy_efficiency'))
                if c is not None:
                    result.append(c)
        return result

    async def infer(self, node: LiveNode, model: str, prompt: str, max_tokens: int):
        async with httpx.AsyncClient(timeout=httpx.Timeout(615.0, connect=5.0)) as client:
            resp = await client.post(node.agent_url + '/v1/infer',
                headers={'X-Mission-Token': self.token},
                json={'worker_id': node.worker_id, 'model': model, 'prompt': prompt, 'max_tokens': max_tokens})
            resp.raise_for_status()
            result = resp.json()
            if result.get('source') != 'real_vllm':
                raise ValueError('Rejected response without a real_vllm marker')
            return result
