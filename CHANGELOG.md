# Changes

## 0.3.0 — Dynamic GPU Runtime
- Fully reactive dashboard via SSE with automatic polling fallback.
- Add/remove virtual GPUs dynamically (topology persisted in Redis).
- Per-node drain/resume for simulated or remote inference endpoints.
- Live AMD SMI + vLLM multi-worker endpoint discovery; topology-aware scheduling.
- Strict opt-in runtime change and separate synthetic / real job source tracking.
- Automatic learned model service-time EWMA after genuine vLLM completions.
- Extended placement catalog with rule-based `auto` strategy (22 endpoint policies × 9 queue policies).
- Redis-based model profiles, thresholds, telemetry and dynamic bounded simulator load generator.
- Real inference completion and error persistence; stale-agent failure closure.
- Prometheus and Grafana accept both synthetic and actual AMD telemetry, retaining a source label.
- Added `agent/`, MI300X runbook and real-only benchmark script.

## 0.2.0 — Advanced Scheduler
- Added GPU placement and non-preemptive queue selection policies.

## 0.1.0 — Local CPU MVP
- Original Docker Compose, Next.js, FastAPI, simulator, Redis, PostgreSQL, Prometheus and Grafana.
