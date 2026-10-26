# AMD AI Factory Mission Control — Dynamic Runtime v0.3

**Windows PowerShell + Docker Desktop, CPU-only development → optional remote AMD Instinct MI300X validation.**

This is a functioning codebase with **two deliberately separate execution modes**, not a cloud subscription or an AMD-certified production GPU operator.

- **simulation** (default): a CPU-driven, configurable synthetic GPU fleet; synthetic HBM, temperature, utilization, and job duration.
- **mi300x** (opt-in): authenticated remote agent discovers actual AMD GPU metrics via AMD SMI, and routes inference to already-running ROCm-compatible vLLM endpoints. Failed real inference is recorded as failed; never replaced with a simulated success.

## What's dynamic

- Discover inference endpoints and GPUs from the MI300X agent every ~1.5 seconds; stale endpoints become ineligible after 12 seconds.
- Dynamic simulation topology: add/remove simulated nodes and configure memory/concurrency; drain/resume live or virtual serving endpoints; Redis persists simulator topology and user-selected policies.
- Dynamic model registry: simulated profiles are editable; the real model catalog comes from the currently running vLLM `/v1/models` endpoints.
- 22 placement policies (including adaptive `auto`) × 9 queue policies. The `auto` policy changes effective placement based on live load spread and queue pressure. No GPU preemption is implemented.
- SSE updates dashboard every 2 seconds, with polling fallback; live Prometheus metrics, Grafana panels, alerts and CSV export.
- Synthetic load generator **only in simulation mode**. Real workloads require explicit job submission.
- Real job completion writes response text, actual vLLM token usage, duration and an EWMA model-latency estimate. Simulator results are always labeled synthetic.
- In a tensor-parallel MI300X vLLM server, GPUs `[0,1,...]` make up **one schedulable endpoint**. Never pretend these are multiple independent replica endpoints.

## Install / upgrade on Windows PowerShell

1. Save the ZIP in your Windows Downloads folder and extract its `amd-ai-factory` folder over the existing folder (or into a separate development copy). **Back up your existing `.env` first.** Do not delete Docker volumes.
2. Run these commands from Windows PowerShell (not WSL):

```powershell
cd "$env:USERPROFILE\Downloads\amd-ai-factory"
docker compose config --quiet
docker compose up -d --build
Invoke-RestMethod http://localhost:8000/health | ConvertTo-Json
.\scripts\verify-dynamic.ps1
```

The first Docker build may download dependencies. If PowerShell execution policy blocks the script, invoke `powershell -ExecutionPolicy Bypass -File .\scripts\verify-dynamic.ps1` for this invocation only after inspecting it.

URLs: UI `http://localhost:3000` · API `http://localhost:8000/docs` · Grafana `http://localhost:3001` · Prometheus `http://localhost:9090`.

`docker compose up -d --build` **does not remove persistent PostgreSQL, Redis, or Grafana volumes.** Never run `docker compose down -v` for an upgrade.

## Local dynamic smoke tests (PowerShell)

```powershell
# Inspect live state and all supported policies
Invoke-RestMethod http://localhost:8000/api/runtime | ConvertTo-Json -Depth 8
Invoke-RestMethod http://localhost:8000/api/policies | ConvertTo-Json -Depth 8
Invoke-RestMethod http://localhost:8000/api/models | ConvertTo-Json -Depth 8

# Dynamically add a synthetic node
$node = Invoke-RestMethod http://localhost:8000/api/simulator/nodes -Method POST -ContentType application/json -Body '{"memory_total_gb":64,"max_concurrent_jobs":3}'

# Enable dynamic automatic placement while staying on CPU simulator
Invoke-RestMethod http://localhost:8000/api/policy -Method PUT -ContentType application/json -Body '{"policy":"auto"}'

# Submit four synthetic jobs
Invoke-RestMethod http://localhost:8000/api/jobs/batch -Method POST -ContentType application/json -Body '{"model":"model-7b","priority":"normal","prompt_tokens":512,"output_tokens":128,"count":4}'

# Inspect, then remove newly created node after it becomes idle
Invoke-RestMethod http://localhost:8000/api/cluster | ConvertTo-Json -Depth 9
# When idle:
Invoke-RestMethod "http://localhost:8000/api/simulator/nodes/$($node.id)" -Method DELETE
```

Or use buttons in the UI at `http://localhost:3000` for topology management and simulation load generation.

## MI300X deployment and readiness

See **[docs/MI300X-DYNAMIC-DEPLOYMENT.md](docs/MI300X-DYNAMIC-DEPLOYMENT.md)**. The MI300X requires a *separate Linux GPU server* for ROCm, the AMD SMI agent, and vLLM. Your Windows laptop runs only the Docker-based control plane. The agent is accessible via an SSH tunnel or trusted private network; no public GPU agent endpoint is needed.

## Architecture

```text
Windows + Docker Desktop (CPU only)
  Next.js --SSE/REST--> FastAPI Mission Control
                           |---- Redis queues + policies + simulator config
                           |---- PostgreSQL job history / real inference evidence
                           |---- Simulation engine (fully local, no GPU)
                           |---- AMD LiveRegistry (authenticated agent polling)
                           |         |--> MI300X agent /v1/state (AMD SMI)
                           |         |--> MI300X agent /v1/infer (ROCm vLLM)
                           +---- Prometheus ---- Grafana / alert rules

Linux MI300X GPU server (later)
  AMD SMI -> physical GPU telemetry (0..N)
  Configured vLLM serving endpoints (0..M); each may use one OR many GPUs
  MI300X agent (loopback, shared token) polls endpoint model registry
```

## Limitations (before real hardware testing)

- AMD MI300X integration **has code and mock-based tests**, but no GPU hardware validation has been performed in this environment.
- Docker/Next.js build was **not** executable in the authoring environment; verify using the commands above on Windows before MI300X tests.
- The controller is single-instance; it does not have a distributed leadership/lease system. This is **not yet a Kubernetes GPU Operator**, and the scheduler routes to pre-deployed vLLM instances; it does not create/destroy GPU containers itself.
- Model memory pressure must be understood per served vLLM instance. vLLM can preallocate large fractions of HBM, so the controller does not double-count model weights per inference request. Instead it uses configured concurrency limits, measured availability and optional admission reservations.
- Most placement policies are educational/baseline heuristics. The adaptive policy is rule-based, not a trained RL/ML model. Some temperature/power fields may be absent if AMD SMI sensors are unavailable.
- The local REST API is intentionally bound to loopback, **without user authentication**. Do not publish the controller or MI300X agent on an untrusted network. Use an SSH tunnel and keep tokens out of Git.

## Repository structure

- `backend/app/main.py` — API, policy loop, dynamic modes, jobs, alerts, CSV, SSE
- `backend/app/scheduler.py` — 22 endpoint placement + 9 queue strategies
- `backend/app/simulator.py` — CPU-based synthetic GPU nodes
- `backend/app/live_runtime.py` — AMD agent discovery, TTL health, real serving adapters
- `agent/amdsmi_probe.py` — AMD SMI hardware sensor adapter (MI300X Linux only)
- `agent/server.py` — authenticated host agent + vLLM proxy
- `frontend/src/app` — reactive Next.js dashboard
- `monitoring/` — Prometheus and Grafana resources
- `scripts/verify-dynamic.ps1` — Windows PowerShell local validation
- `docs/MI300X-DYNAMIC-DEPLOYMENT.md` — agent, vLLM and connection steps

## Developer tests

Python scheduling, runtime and mocked agent tests:

```powershell
docker compose exec backend pytest -q
```

From a normal Python environment with pytest installed, `PYTHONPATH=backend` is needed for tests; **Windows PowerShell users should prefer the Docker test command above**.

Software source references: [AMD SMI Python API](https://rocmdocs.amd.com/projects/amdsmi/en/latest/reference/amdsmi-py-api.html), [ROCm vLLM guidance](https://rocm.docs.amd.com/en/docs-7.2.4/how-to/rocm-for-ai/inference/benchmark-docker/vllm.html), [vLLM ROCm installation](https://docs.vllm.ai/en/latest/getting_started/installation/gpu/).
#   A M D - A I - F a c t o r y  
 