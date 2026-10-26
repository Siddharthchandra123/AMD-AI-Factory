"""Synthetic MI300X nodes for running the control plane without AMD GPUs.

All telemetry here is simulation data. Never use it as MI300X benchmark evidence.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import time

from .scheduler import Candidate


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class RuntimeJob:
    job_id: str
    start_monotonic: float
    finish_monotonic: float
    memory_gb: float
    load_percent: float


@dataclass
class VirtualGPU:
    id: str
    model: str = "AMD Instinct MI300X (SIMULATED)"
    memory_total_gb: float = 192.0
    idle_memory_gb: float = 6.0
    idle_load_percent: float = 4.0
    active: dict[str, RuntimeJob] = field(default_factory=dict)
    cached_models: set[str] = field(default_factory=set)
    max_concurrent_jobs: int = 2
    draining: bool = False

    @property
    def memory_used_gb(self) -> float:
        return self.idle_memory_gb + sum(r.memory_gb for r in self.active.values())

    @property
    def utilization(self) -> float:
        return min(99.0, self.idle_load_percent + sum(r.load_percent for r in self.active.values()))

    def candidate(self) -> Candidate:
        return Candidate(
            id=self.id,
            total_memory_gb=self.memory_total_gb,
            used_memory_gb=self.memory_used_gb,
            gpu_utilization=self.utilization,
            active_jobs=len(self.active),
            max_concurrent_jobs=self.max_concurrent_jobs,
            temperature_c=38 + self.utilization * .39,
            power_watts=110 + self.utilization * 4.5,
            cached_models=tuple(sorted(self.cached_models)),
        )

    def as_dict(self) -> dict:
        utilization = self.utilization
        return {
            "id": self.id,
            "model": self.model,
            "source": "simulation",
            "memory_total_gb": self.memory_total_gb,
            "memory_used_gb": round(self.memory_used_gb, 1),
            "utilization_percent": round(utilization, 1),
            "temperature_c": round(38 + utilization * .39, 1),
            "power_watts": round(110 + utilization * 4.5, 1),
            "active_jobs": len(self.active),
            "health": "draining" if self.draining else ("healthy" if utilization < 90 else "high_load"),
            "draining": self.draining,
            "ready": True,
            "max_concurrent_jobs": self.max_concurrent_jobs,
            "gpu_ids": [self.id],
            "models": [],
            "last_seen_seconds": 0,
            "cached_models": sorted(self.cached_models),
        }


class VirtualCluster:
    def __init__(self, count: int = 4) -> None:
        self.nodes = [VirtualGPU(id=f"mi300x-sim-{i + 1}", idle_load_percent=3 + i) for i in range(count)]
        self.rr_cursor = 0

    def add(self, *, total_memory_gb: float = 192.0, max_concurrent_jobs: int = 2) -> VirtualGPU:
        identifiers = {n.id for n in self.nodes}
        i = 1
        while f"mi300x-sim-{i}" in identifiers:
            i += 1
        node = VirtualGPU(id=f"mi300x-sim-{i}", memory_total_gb=total_memory_gb, max_concurrent_jobs=max_concurrent_jobs)
        self.nodes.append(node)
        return node

    def remove(self, node_id: str) -> bool:
        node = next((n for n in self.nodes if n.id == node_id), None)
        if not node or node.active or len(self.nodes) <= 1:
            return False
        self.nodes.remove(node)
        self.rr_cursor %= len(self.nodes)
        return True

    def completed(self) -> list[tuple[str, str, float]]:
        finished = []
        t = time.monotonic()
        for node in self.nodes:
            for job_id, job in list(node.active.items()):
                if t >= job.finish_monotonic:
                    finished.append((job_id, node.id, round(t - job.start_monotonic, 3)))
                    del node.active[job_id]
        return finished

    def snapshot(self) -> list[dict]:
        return [node.as_dict() for node in self.nodes]
