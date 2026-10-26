"""Portable simulation-first job scheduling and GPU placement policies.

This module is intentionally pure Python: no ROCm, CUDA or accelerator hardware
required. Node policies decide *where* to run a job. Queue policies decide *which*
waiting job to dispatch. These are non-preemptive inference-job policies.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import random

MODEL_MEMORY_GB = {"model-7b": 18.0, "model-8b": 22.0, "model-32b": 76.0}

PLACEMENT_POLICIES: dict[str, str] = {
    "round_robin": "Rotate across eligible GPU nodes",
    "weighted_round_robin": "Rotate with slots proportional to GPU performance",
    "first_fit": "Select first GPU with sufficient HBM and concurrency",
    "least_loaded": "Choose lowest simulated GPU utilization",
    "least_connections": "Choose fewest currently running jobs",
    "least_memory_used": "Choose smallest absolute HBM allocation",
    "most_free_memory": "Choose maximum remaining HBM",
    "best_fit_memory": "Pack job onto smallest sufficient HBM remainder",
    "worst_fit_memory": "Spread jobs to node with largest remaining HBM",
    "capacity_weighted": "Prefer highest free-HBM percentage",
    "power_aware": "Prefer lowest current node power",
    "thermal_aware": "Prefer coolest eligible GPU",
    "balanced_score": "Balance utilization, memory pressure and concurrency",
    "latency_aware": "Prefer smallest load-adjusted estimated processing delay",
    "energy_efficiency": "Prefer performance-per-watt proxy",
    "locality_aware": "Prefer node with the requested model in simulated cache",
    "rendezvous_hash": "Stable model/job routing using rendezvous hashing",
    "power_of_two_choices": "Sample two eligible nodes and pick lower load",
    "random": "Uniform random eligible GPU",
    "weighted_random": "Random selection weighted by headroom and performance",
    "adaptive": "Multi-factor headroom, latency, temperature, cache and power score",
    "auto": "Dynamically choose a placement strategy from live queue and GPU pressure",
}
QUEUE_POLICIES: dict[str, str] = {
    "priority_fifo": "High > normal > low priority, FIFO within each tier (original behavior)",
    "fcfs": "First Come First Served across all priorities",
    "shortest_job_first": "Shortest estimated non-preemptive job first",
    "longest_job_first": "Longest estimated non-preemptive job first",
    "highest_response_ratio_next": "Highest (waiting + service) / service first",
    "priority_aging": "Priorities gradually rise with wait time to limit starvation",
    "earliest_deadline_first": "Earliest explicit deadline first, FIFO for no deadline",
    "fair_share": "Prefer tenants with the fewest currently running jobs",
    "random_queue": "Randomly choose a waiting job (experimental baseline)",
}
VALID_POLICIES = set(PLACEMENT_POLICIES)  # v0.1 compatibility
VALID_QUEUE_POLICIES = set(QUEUE_POLICIES)
PRIORITY_WEIGHTS = {"high": 2, "normal": 1, "low": 0}


@dataclass(frozen=True)
class Candidate:
    id: str
    total_memory_gb: float
    used_memory_gb: float
    gpu_utilization: float
    active_jobs: int
    max_concurrent_jobs: int = 2
    temperature_c: float = 45.0
    power_watts: float = 120.0
    performance_weight: float = 1.0
    cached_models: tuple[str, ...] = ()

    @property
    def free_gb(self) -> float:
        return self.total_memory_gb - self.used_memory_gb

    def can_accept(self, memory_required_gb: float) -> bool:
        return self.active_jobs < self.max_concurrent_jobs and self.free_gb >= memory_required_gb


@dataclass(frozen=True)
class QueueCandidate:
    id: str
    priority: str
    created_timestamp: float
    estimated_seconds: float
    tenant: str = "default"
    deadline_timestamp: float | None = None


def _stable_unit(key: str) -> float:
    value = int.from_bytes(hashlib.blake2b(key.encode(), digest_size=8).digest(), "big")
    return (value + 1) / (2**64 + 1)


def select_node(
    candidates: list[Candidate],
    memory_required_gb: float,
    policy: str,
    cursor: int = 0,
    *,
    model: str | None = None,
    job_key: str | None = None,
    rng: random.Random | None = None,
) -> tuple[Candidate | None, int]:
    """Select eligible GPU. Return (selected node, next round-robin cursor)."""
    if policy == "auto":
        policy = "adaptive"  # Control plane selects the effective policy at dispatch time.
    if policy not in PLACEMENT_POLICIES:
        raise ValueError(f"Unknown placement policy: {policy}")
    eligible = [n for n in candidates if n.can_accept(memory_required_gb)]
    if not eligible:
        return None, cursor
    ordered = sorted(eligible, key=lambda n: n.id)
    randomizer = rng if rng is not None else random.Random()
    if policy == "first_fit":
        return next(n for n in candidates if n.can_accept(memory_required_gb)), cursor
    if policy == "round_robin":
        for offset in range(len(candidates)):
            idx = (cursor + offset) % len(candidates)
            if candidates[idx].can_accept(memory_required_gb):
                return candidates[idx], (idx + 1) % len(candidates)
    if policy == "weighted_round_robin":
        # Stable weighted ring; slots reflect relative compute performance.
        ring = [n for n in candidates for _ in range(max(1, min(8, round(n.performance_weight * 2))))]
        for offset in range(len(ring)):
            idx = (cursor + offset) % len(ring)
            if ring[idx].can_accept(memory_required_gb):
                return ring[idx], (idx + 1) % len(ring)
    if policy == "least_loaded":
        return min(eligible, key=lambda n: (n.gpu_utilization, n.active_jobs, n.id)), cursor
    if policy == "least_connections":
        return min(eligible, key=lambda n: (n.active_jobs, n.gpu_utilization, n.id)), cursor
    if policy == "least_memory_used":
        return min(eligible, key=lambda n: (n.used_memory_gb, n.id)), cursor
    if policy == "most_free_memory":
        return min(eligible, key=lambda n: (-n.free_gb, n.id)), cursor
    if policy == "best_fit_memory":
        return min(eligible, key=lambda n: (n.free_gb - memory_required_gb, n.id)), cursor
    if policy == "worst_fit_memory":
        return min(eligible, key=lambda n: (-n.free_gb, n.id)), cursor
    if policy == "capacity_weighted":
        return min(eligible, key=lambda n: (-n.free_gb / max(n.total_memory_gb, 1), n.id)), cursor
    if policy == "power_aware":
        return min(eligible, key=lambda n: (n.power_watts, n.id)), cursor
    if policy == "thermal_aware":
        return min(eligible, key=lambda n: (n.temperature_c, n.id)), cursor
    if policy == "balanced_score":
        return min(eligible, key=lambda n: (
            .45 * n.gpu_utilization / 100
            + .30 * n.used_memory_gb / max(n.total_memory_gb, 1)
            + .25 * n.active_jobs / max(n.max_concurrent_jobs, 1), n.id
        )), cursor
    if policy == "latency_aware":
        return min(eligible, key=lambda n: (
            (n.active_jobs + 1) * (1 + n.gpu_utilization / 100) / max(n.performance_weight, .01), n.id
        )), cursor
    if policy == "energy_efficiency":
        return min(eligible, key=lambda n: (
            n.power_watts * (n.active_jobs + 1) / max(n.performance_weight, .01), n.id
        )), cursor
    if policy == "locality_aware":
        return min(eligible, key=lambda n: (
            0 if model is not None and model in n.cached_models else 1,
            n.gpu_utilization, n.id
        )), cursor
    if policy == "rendezvous_hash":
        # Using the model produces model locality; per-job key allows distribution.
        key = job_key or model or "default"
        return max(eligible, key=lambda n: (_stable_unit(key + ":" + n.id), n.id)), cursor
    if policy == "power_of_two_choices":
        sampled = randomizer.sample(ordered, min(2, len(ordered)))
        return min(sampled, key=lambda n: (n.gpu_utilization, n.active_jobs, n.id)), cursor
    if policy == "random":
        return randomizer.choice(ordered), cursor
    if policy == "weighted_random":
        weights = [(n.free_gb / max(n.total_memory_gb, 1)) * max(n.performance_weight, .01) for n in ordered]
        return randomizer.choices(ordered, weights=weights, k=1)[0], cursor
    if policy == "adaptive":
        return min(eligible, key=lambda n: (
            .28 * n.gpu_utilization / 100
            + .18 * n.used_memory_gb / max(n.total_memory_gb, 1)
            + .21 * n.active_jobs / max(n.max_concurrent_jobs, 1)
            + .11 * min(n.temperature_c / 95, 1)
            + .10 * min(n.power_watts / 750, 1)
            + .12 * (0 if model is not None and model in n.cached_models else 1), n.id
        )), cursor
    raise AssertionError(f"Unimplemented placement policy: {policy}")


def rank_queue(
    queued: list[QueueCandidate],
    policy: str,
    *,
    now_timestamp: float,
    active_by_tenant: dict[str, int] | None = None,
    rng: random.Random | None = None,
) -> list[QueueCandidate]:
    """Order pending non-preemptive jobs (does not dispatch them)."""
    if policy not in QUEUE_POLICIES:
        raise ValueError(f"Unknown queue policy: {policy}")
    active_by_tenant = active_by_tenant or {}
    randomizer = rng if rng is not None else random.Random()
    fifo = lambda j: (j.created_timestamp, j.id)
    if policy == "priority_fifo":
        return sorted(queued, key=lambda j: (-PRIORITY_WEIGHTS[j.priority], *fifo(j)))
    if policy == "fcfs":
        return sorted(queued, key=fifo)
    if policy == "shortest_job_first":
        return sorted(queued, key=lambda j: (j.estimated_seconds, *fifo(j)))
    if policy == "longest_job_first":
        return sorted(queued, key=lambda j: (-j.estimated_seconds, *fifo(j)))
    if policy == "highest_response_ratio_next":
        return sorted(queued, key=lambda j: (
            -(1 + max(0, now_timestamp - j.created_timestamp) / max(j.estimated_seconds, .001)),
            *fifo(j)
        ))
    if policy == "priority_aging":
        return sorted(queued, key=lambda j: (
            -(PRIORITY_WEIGHTS[j.priority] * 10 + max(0, now_timestamp - j.created_timestamp) / 5),
            *fifo(j)
        ))
    if policy == "earliest_deadline_first":
        return sorted(queued, key=lambda j: (
            j.deadline_timestamp if j.deadline_timestamp is not None else math.inf,
            *fifo(j)
        ))
    if policy == "fair_share":
        return sorted(queued, key=lambda j: (active_by_tenant.get(j.tenant, 0), *fifo(j)))
    if policy == "random_queue":
        result = list(queued)
        randomizer.shuffle(result)
        return result
    raise AssertionError(f"Unimplemented queue policy: {policy}")


def estimated_simulation_seconds(prompt_tokens: int, output_tokens: int, memory_gb: float) -> float:
    """Synthetic duration only: NOT an AMD throughput prediction."""
    return round(min(40.0, max(3.0, (prompt_tokens + output_tokens * 3) / 110 + memory_gb / 16)), 2)
