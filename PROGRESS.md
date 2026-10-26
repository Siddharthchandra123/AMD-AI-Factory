# AMD AI Factory Mission Control — progress

## v0.3 prepared

- Added live AMD MI300X agent and AMD SMI Python telemetry probe.
- Added ROCm vLLM inference adapter with real token counts and response durations.
- Added runtime discovery + readiness TTL; worker grouping respects tensor parallelism.
- Added `simulation` / `mi300x` mode switch with safety guard.
- Added dynamic simulation nodes, model profiles, drain/resume, workload generation.
- Added rule-based auto placement, learned job duration EWMA from real model requests.
- Added SSE dashboard, live alerts, live-vs-simulation labels and Grafana enhancements.
- Added real benchmark script and PowerShell preflight verification.

### Verification performed during artifact authoring
- 75 Python tests passed (including a mock-based AMD SMI probe test).
- Next.js TSX parsed with TypeScript's syntax parser (0 parse errors).
- Python code compiled (`compileall`).

### NOT yet verified
- Docker Compose rebuild and fully integrated API / Redis / PostgreSQL operation on user Windows laptop.
- Next.js production build (dependency install unavailable in authoring environment).
- Actual physical AMD MI300X ROCm inference, telemetry, multi-worker policy comparison.

### Immediate next action
Run `docker compose up -d --build` in **Windows PowerShell** and `.\scripts\verify-dynamic.ps1`. Do not switch to real mode until remote agent checks succeed.
