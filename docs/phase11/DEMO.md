# Live demonstration walkthrough (GPU-free)

Use only the locally running simulation for live actions. Archived MI300X results should be identified clearly as **historical real-GPU experiments**.

## Sequence

1. Open `http://localhost:3000` and show the 4 simulated MI300X workers. Explain that their VRAM/utilization figures are synthetic.
2. Confirm with `GET http://localhost:8000/api/runtime` that the mode is `simulation`.
3. Open `http://localhost:3001` (Grafana) to show queue depth, active jobs, simulated HBM and dispatch metrics; explain that counters can reset with the backend.
4. Open `http://localhost:3000/benchmarks` to show the archived actual MI300X 8-job pre/post run. Highlight p95 end-to-end 12.7369 → 5.8264 s; explain limited trials.
5. Open `http://localhost:3000/scheduler-lab` to compare synthetic FIFO, SJF, priority and deadline-aware queueing using identical workloads. These charts are simulation, not GPU hardware results.
6. Open `http://localhost:3000/hardening` to show simulated drain/recovery reports and last controller startup reconciliation.
7. Show the local Phase 10 output: 6/6 drain test, 6/6 restart test, 9/9 security audit checks. Distinguish tested simulation from production failure tolerance.
8. Display the architecture diagram and the agent diagram. Walk through control plane → remote agent → vLLM → ROCm → MI300X. Explain that the real GPU was previously used and is no longer required for replaying evidence.
9. Conclude with limitations and roadmap: multi-agent/multi-GPU tests, production auth, vLLM high-resolution telemetry and statistically repeated real benchmarks.

## When a demo must remain read-only

Do **not** execute a worker-restart test during a live demo unless there is a dedicated test window and the queue is idle. Avoid changing runtime mode to `mi300x` without a connected and authenticated physical worker. Use existing results rather than consuming cloud GPU compute.

## Useful read-only checks (PowerShell)

```powershell
Invoke-RestMethod 'http://localhost:8000/health'
(Invoke-RestMethod 'http://localhost:8000/api/cluster').summary
Invoke-RestMethod 'http://localhost:8000/api/hardening/status' | ConvertTo-Json -Depth 5
python .\scripts\phase11_regression.py --compose
```
