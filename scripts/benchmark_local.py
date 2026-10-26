#!/usr/bin/env python3
"""Compare scheduling policies on SIMULATED GPU traces (not MI300X measurements).

Usage (PowerShell): python .\\scripts\\benchmark_local.py --jobs 12
Requires the local docker-compose services already running.
"""
import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import time
from urllib.request import Request, urlopen


def call(base: str, path: str, method: str = "GET", payload: dict | None = None):
    body = json.dumps(payload).encode() if payload is not None else None
    req = Request(
        base.rstrip("/") + path,
        data=body, method=method,
        headers={"Content-Type": "application/json"} if body else {},
    )
    with urlopen(req, timeout=10) as response:
        return json.load(response)


def percentile(values: list[float], q: float) -> float:
    arr = sorted(values)
    if not arr:
        return 0.0
    pos = (len(arr) - 1) * q
    left = int(pos)
    right = min(left + 1, len(arr) - 1)
    return arr[left] + (arr[right] - arr[left]) * (pos - left)


def wait_for_idle(base: str, timeout: int = 240) -> None:
    started = time.monotonic()
    while True:
        summary = call(base, "/api/cluster")["summary"]
        if summary["queued_jobs"] == 0 and summary["running_jobs"] == 0:
            return
        if time.monotonic() - started > timeout:
            raise TimeoutError("Cluster did not become idle in time")
        time.sleep(1)


def run_policy(base: str, policy: str, queue_policy: str, count: int) -> tuple[list[dict], dict]:
    wait_for_idle(base)
    call(base, "/api/policy", "PUT", {"policy": policy})
    call(base, "/api/queue-policy", "PUT", {"policy": queue_policy})
    begin = time.monotonic()
    created = call(base, "/api/jobs/batch", "POST", {
        "count": count, "model": "model-7b", "priority": "normal",
        "prompt_tokens": 512, "output_tokens": 256,
    })["jobs"]
    identifiers = {j["id"] for j in created}
    while True:
        jobs = call(base, "/api/jobs?limit=500")["jobs"]
        records = [j for j in jobs if j["id"] in identifiers]
        if len(records) == count and all(j["status"] == "completed" for j in records):
            break
        if time.monotonic() - begin > 240:
            raise TimeoutError(f"Timed out waiting for policy {policy}")
        time.sleep(1)
    makespan = time.monotonic() - begin
    waits = [float(j["queue_wait_seconds"] or 0) for j in records]
    runtimes = [float(j["duration_seconds"] or 0) for j in records]
    summary = {
        "policy": policy,
        "queue_policy": queue_policy,
        "jobs": count,
        "makespan_seconds": round(makespan, 3),
        "jobs_per_second": round(count / makespan, 4),
        "average_queue_wait_seconds": round(statistics.mean(waits), 3),
        "p95_queue_wait_seconds": round(percentile(waits, .95), 3),
        "average_simulated_duration_seconds": round(statistics.mean(runtimes), 3),
        "p95_simulated_duration_seconds": round(percentile(runtimes, .95), 3),
        "source": "simulation (NOT real AMD GPU)",
    }
    for rec in records:
        rec["test_policy"] = policy
        rec["test_queue_policy"] = queue_policy
        rec["source"] = "simulation"
    return records, summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--jobs", type=int, default=12)
    parser.add_argument("--output", default="results/local")
    parser.add_argument("--placement", default="round_robin,least_loaded,adaptive", help="Comma-separated placement policies")
    parser.add_argument("--queue", default="priority_fifo", help="Comma-separated queue policies")
    parser.add_argument("--all-placement", action="store_true", help="Test all placement policies (can take substantial time)")
    parser.add_argument("--all-queue", action="store_true", help="Test all queue policies (can take substantial time)")
    args = parser.parse_args()
    if args.jobs < 1 or args.jobs > 50:
        parser.error("--jobs must be between 1 and 50")
    info = call(args.api, "/api/info")
    if info["mode"] != "simulation":
        raise RuntimeError("This is a simulation-only benchmark script")
    catalog = call(args.api, "/api/policies")
    available_placements = [p["id"] for p in catalog["placement"]]
    available_queues = [p["id"] for p in catalog["queue"]]
    placements = available_placements if args.all_placement else [p.strip() for p in args.placement.split(",") if p.strip()]
    queue_policies = available_queues if args.all_queue else [p.strip() for p in args.queue.split(",") if p.strip()]
    for policy in placements:
        if policy not in available_placements:
            parser.error(f"Unknown placement policy {policy!r}")
    for policy in queue_policies:
        if policy not in available_queues:
            parser.error(f"Unknown queue policy {policy!r}")
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    records = []
    results = []
    for queue_policy in queue_policies:
        for policy in placements:
            print(f"Running placement={policy}, queue={queue_policy} (SIMULATED) with {args.jobs} jobs...", flush=True)
            r, summary = run_policy(args.api, policy, queue_policy, args.jobs)
            records.extend(r)
            results.append(summary)
            print(json.dumps(summary, indent=2))
    with (out / "simulation-summary.json").open("w") as f:
        json.dump({"generated_at_utc": datetime.now(timezone.utc).isoformat(), "mode": "simulation", "results": results}, f, indent=2)
    with (out / "simulation-jobs.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=records[0].keys())
        writer.writeheader()
        writer.writerows(records)
    print(f"Synthetic benchmark results saved under: {out}")


if __name__ == "__main__":
    main()
