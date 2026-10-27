# AMD AI Factory Mission Control — Scheduler Latency Patch v0.5

**What this changes:** Decouples the MI300X agent's telemetry/model-discovery poll from the real-inference job-dispatch loop. The current v0.3 backend awaits a remote `/v1/state` response before deciding which queued jobs to dispatch, then sleeps 1.5 seconds. Remote telemetry checks and repeated discovery can therefore delay dispatch, especially when the worker has two active slots.

**What this doesn't do:** Doesn't change scheduler policy selection, concurrency limits, ROCm, AMD SMI, vLLM, the token, Docker volumes or PostgreSQL. This is a measured *hypothesis*: run the same 8-job benchmark before and after; do not claim an improvement until the data shows one.

## Apply in Windows PowerShell

1. Wait until the MI300X queue is **idle** (`running_jobs=0`, `queued_jobs=0`) and your previous benchmark results are saved.
2. Extract this archive **inside the existing project folder** `C:\Users\Lenovo\Downloads\amd-ai-factory` so `scripts\patch_scheduler_v0_5.py` is present. Do not replace other project files.
3. Check compatibility:
   ```powershell
   python .\scripts\patch_scheduler_v0_5.py
   ```
4. Apply (the script creates a timestamped backup):
   ```powershell
   python .\scripts\patch_scheduler_v0_5.py --apply
   ```
5. Rebuild only the Windows backend:
   ```powershell
   docker compose up -d --build backend
   docker compose logs --tail=40 backend
   ```
6. Validate active MI300X worker and valid HBM:
   ```powershell
   Invoke-RestMethod 'http://localhost:8000/api/runtime' | ConvertTo-Json -Depth 5
   (Invoke-RestMethod 'http://localhost:8000/api/cluster').nodes | Format-Table id, health, memory_total_gb, memory_used_gb, active_jobs
   ```
7. Run the same 8-job workload without concurrent background jobs:
   ```powershell
   python .\scripts\benchmark_mi300x_v2.py --jobs 8 --output-tokens 96
   ```
8. Compare p50/p95 queue wait, p95 E2E, and client-observed throughput with prior results. The script preserves evidence in a unique directory.

## Restore

To roll back, locate `backend\app\main.py.before_latency_v05_<timestamp>.bak` and copy it back over `backend\app\main.py` using PowerShell (when idle), then `docker compose up -d --build backend`.

## Safety limits

- Windows commands belong in PowerShell; the AMD telemetry agent and vLLM continue running on the remote MI300X, unchanged.
- Be sure the original queue is idle before restarting the backend: a real in-flight job is marked failed with an unknown remote outcome rather than automatically retried.
- With a **single** serving endpoint, this change tests **queue dispatch**, not GPU-placement policy comparisons.
- Longer GPU benchmarks consume paid or credited Droplet time; stop billing when finished.
