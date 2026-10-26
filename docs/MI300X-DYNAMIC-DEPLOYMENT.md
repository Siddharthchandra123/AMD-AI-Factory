# AMD MI300X Deployment — Dynamic Agent + Actual vLLM Evidence

This document is for the **final validation phase**. The controller stays on Windows PowerShell, running CPU-only Docker Desktop containers. ROCm runs only on the separate AMD Instinct GPU server (typically Linux).

## 0. Preconditions

- A Linux MI300X node that you are authorized to use, accessible over SSH or private network.
- ROCm driver and AMD SMI installed on that node, with AMD SMI Python bindings importable by the Python used for the agent.
- Docker (or a supported container runtime) on the MI300X host, with GPU device access and permissions.
- GPU server outbound connectivity or previously downloaded model weights.
- Model-specific hardware requirements. Use a small model for the first smoke test; **MI300X throughput claims require actual measurement**.
- Only one Mission Control backend replica. If scaling the controller to multiple replicas, add durable job leases, reservations and leader election first.

## 1. From your Windows PowerShell terminal

Back up `amd-ai-factory/.env`. Send *only the agent source folder* to the authorized MI300X Linux host:

```powershell
cd "$env:USERPROFILE\Downloads\amd-ai-factory"
scp -r .\agent USER@GPU_HOST:~/amd-mi300x-agent
# Do not upload your local .env, secrets, or database.
```

Generate an authentication token in PowerShell and privately transfer its value to the MI300X host:

```powershell
$token = ([guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N'))
$token
```

Use this **same token** for `MISSION_AGENT_TOKEN` on both systems. Never share it in screenshots, logs, a public repo or chat.

## 2. GPU host only: confirm ROCm and AMD SMI (Linux shell)

The following commands run **on the remote MI300X Linux server, not on your Windows laptop or WSL**. Any ROCm host-specific prerequisite must be handled by the GPU administrator.

```bash
amd-smi list
amd-smi monitor --json
python3 -c 'import amdsmi; print("AMD SMI bindings available")'
```

The Python environment running the agent must have `amdsmi` available from the installed ROCm stack. An isolated venv can obscure ROCm's system-provided Python module; if needed use a venv with `--system-site-packages` or a validated ROCm Python environment.

## 3. GPU host: start vLLM (Linux shell)

Choose a **ROCm image tag compatible with the GPU host and supported ROCm software stack**. Official current tags change; consult the upstream vLLM ROCm installation guide. Example for one GPU / one small model:

```bash
# Example tag: verify against your host's ROCm driver and docs before using.
docker pull vllm/vllm-openai-rocm:latest-rocm72

docker run --rm --name mi300x-vllm \
  --device /dev/kfd --device /dev/dri \
  --group-add video --ipc=host \
  -p 127.0.0.1:8002:8000 \
  -v "$HOME/.cache/huggingface:/root/.cache/huggingface" \
  vllm/vllm-openai-rocm:latest-rocm72 \
  --model Qwen/Qwen3-0.6B \
  --tensor-parallel-size 1
```

Some environments require additional container/security permissions, model tokens, or different ROCm image versions. Consult upstream ROCm/vLLM documentation, not fixed assumptions from the simulator.

Check model discovery on GPU host:

```bash
curl --fail http://127.0.0.1:8002/v1/models
```

For tensor parallel inference across eight GPUs, create **one vLLM endpoint** with tensor parallel size 8 and map its `gpu_ids` to all eight hardware devices. Do not register eight independent endpoints for a single tensor-parallel server.

## 4. GPU host: run the authenticated MI300X agent (Linux shell)

```bash
cd ~/amd-mi300x-agent
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install -r requirements.txt
python -c 'import amdsmi; print("AMD SMI ready")'

# Use your actual shared secret here; example placeholder must be replaced.
export MISSION_AGENT_TOKEN='PASTE_YOUR_PRIVATE_TOKEN'
export MISSION_AGENT_ID='mi300x-host-1'
export MI300X_WORKERS_JSON='[{"id":"vllm-small","base_url":"http://127.0.0.1:8002","gpu_ids":[0],"max_concurrent_jobs":2,"reserve_gb_per_job":0}]'
uvicorn server:app --host 127.0.0.1 --port 9877
```

Important: `gpu_ids` must match GPU indices from **agent-side AMD SMI enumeration** and the devices actually exposed to each vLLM worker. For tensor-parallel vLLM, a list of several GPU IDs forms one serving endpoint.

The `/v1/state` and `/v1/infer` routes require the `X-Mission-Token` header. The agent performs real AMD SMI reads and will respond with HTTP 503 if AMD telemetry cannot be obtained; it **does not generate simulator values**.

## 5. Windows PowerShell: make an SSH tunnel

With vLLM and the agent running remotely, open a *separate* Windows PowerShell window:

```powershell
ssh -N -L 9877:127.0.0.1:9877 USER@GPU_HOST
```

Keep that PowerShell window open. In a second PowerShell window:

```powershell
$headers = @{"X-Mission-Token"=$token}
Invoke-RestMethod -Uri "http://127.0.0.1:9877/v1/state" -Headers $headers | ConvertTo-Json -Depth 10
```

If telemetry and models are visible, configure your local `amd-ai-factory/.env`:

```env
MI300X_AGENT_URLS=http://host.docker.internal:9877
MISSION_AGENT_TOKEN=PASTE_THE_SAME_PRIVATE_TOKEN
```

Then from **Windows PowerShell**:

```powershell
docker compose up -d --force-recreate backend
Invoke-RestMethod http://localhost:8000/api/runtime | ConvertTo-Json -Depth 10
```

Docker Desktop provides `host.docker.internal` to reach host services, but your SSH tunnel and Windows firewall configuration may limit visibility to loopback. If the local `127.0.0.1:9877` probe succeeds but the backend reports a connection error, diagnose container-to-host connectivity. Do **not** expose the agent publicly as a workaround; use a properly secured private network or a deliberate, access-restricted forwarding arrangement.

## 6. Windows PowerShell: explicitly switch modes

**Wait for the simulation queue to empty first.** The app refuses runtime switches while any jobs are running or queued.

```powershell
# Inspect readiness before switching
Invoke-RestMethod http://localhost:8000/api/cluster | ConvertTo-Json -Depth 10
Invoke-RestMethod http://localhost:8000/api/runtime | ConvertTo-Json -Depth 10

# Switch mode using the correct single-line PowerShell command below.
# Use the model ID actually reported by the MI300X server, not "model-7b".
Invoke-RestMethod http://localhost:8000/api/models | ConvertTo-Json -Depth 8
```

Use this PowerShell command to switch:

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/runtime" -Method PUT -ContentType "application/json" -Body '{"mode":"mi300x"}'
```

Submit **one** real inference job to begin:

```powershell
$models = (Invoke-RestMethod http://localhost:8000/api/models).models
$realModel = $models[0].id
$payload = @{model=$realModel;prompt='Explain the advantage of adaptive GPU routing in two sentences.';output_tokens=96;priority='normal'} | ConvertTo-Json
Invoke-RestMethod -Uri "http://localhost:8000/api/jobs" -Method POST -ContentType "application/json" -Body $payload
Start-Sleep -Seconds 10
Invoke-RestMethod http://localhost:8000/api/jobs | ConvertTo-Json -Depth 10
```

A successful real job will contain `execution_mode: mi300x`, `status: completed`, actual `completion_tokens_actual`, real `duration_seconds`, and `response_text`. The same job can fail with an explicit `error_message`; failure is not silently retried or converted to simulated success.

## 7. Performance evidence and criteria

1. Verify `mode=mi300x` and actual `source=amd_smi` on all registered endpoints; no simulated readings in GPU evidence.
2. Submit one real model request; inspect response and actual duration/token count.
3. Increase concurrency carefully. Record p50/p95 latency, completed tokens/s, throughput, queue wait, memory, GPU utilization, sensor errors and rejected/failed requests.
4. Compare scheduling policies under identical actual prompts and traffic; do not treat policy rankings from synthetic tests as MI300X measurements.
5. Test draining a real worker while idle/running, agent shutdown, stale telemetry, unreachable vLLM, and recovery. A single inference endpoint cannot demonstrate meaningful **cross-node** load balancing; multiple independent vLLM workers are needed.
6. Capture reproducible system versions, GPU topology, vLLM command, model ID, quantization/dtype, concurrency, model lengths, benchmark scripts, and CSV/JSON outputs.

## 8. Architecture limitations to state in submission

- The controller routes to **existing** vLLM inference endpoints; it does not autoscale or provision vLLM processes or K8s nodes yet.
- No distributed consensus or global resource lease across multiple Mission Control replicas; run one control-plane instance.
- This version uses live utilization/concurrency and operator-specified memory reservations. It does not have an accurate predictive KV-cache model or preempt running requests.
- Multi-GPU tensor parallel endpoints are scheduled as a group, not separate physical accelerators.
- Model latency EWMA is learned online after genuine completions; it is not a forecast trained offline.
- SSH is the recommended way to avoid exposing the agent, and shared tokens are not a substitute for TLS/RBAC in a public cloud deployment.

### References

- AMD SMI Python API: https://rocmdocs.amd.com/projects/amdsmi/en/latest/reference/amdsmi-py-api.html
- AMD SMI CLI: https://rocmdocs.amd.com/projects/amdsmi/en/latest/how-to/amdsmi-cli-tool.html
- Official ROCm vLLM: https://rocm.docs.amd.com/en/docs-7.2.4/how-to/rocm-for-ai/inference/benchmark-docker/vllm.html
- vLLM OpenAI-compatible API: https://docs.vllm.ai/en/latest/serving/openai_compatible_server.html

## 9. Real benchmark script (Windows PowerShell)

After the single real inference smoke test has completed, run a controlled multi-policy benchmark **only when your GPU allocation allows it**:

```powershell
cd "$env:USERPROFILE\Downloads\amd-ai-factory"
python .\scripts\benchmark_mi300x.py --jobs 4 --placement round_robin,least_loaded,auto --output-tokens 96
Get-Content .\results\mi300x\real-summary.json
```

The script refuses to run unless `mode=mi300x`, discovers the actual served model, collects AMD SMI readings, and writes the following **real-only** evidence: `real-summary.json`, `real-jobs.csv`, and `real-telemetry.csv`. It does not retry failed jobs and cannot produce real benchmark evidence in simulation mode. Compare policies on two or more independent vLLM endpoints for meaningful placement comparisons; a single TP8 worker cannot be load-balanced to another worker by itself.
