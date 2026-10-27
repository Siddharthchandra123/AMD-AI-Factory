# MI300X latency diagnostic — v0.6

This is an additive, read-only (configuration-wise) benchmark script for **AMD AI Factory Mission Control v0.3/v0.5**. It submits real inference requests to three paths: **direct vLLM over the existing SSH tunnel**, **AMD agent over the tunnel**, and **the Windows Mission Control controller**. No existing source files are replaced.

## Run from Windows PowerShell

1. Extract this ZIP *into the existing* `C:\Users\Lenovo\Downloads\amd-ai-factory` directory.
2. Keep local backend, SSH tunnel (`8002`, `9877`), remote agent, and vLLM running.
3. Ensure the backend is in `mi300x` mode and the queue is idle.
4. Execute:

```powershell
python .\scripts\diagnose_latency_v0_6.py --trials 3 --output-tokens 96
```

The script securely prompts for your current agent token (typing is not echoed). **Do not post the token.** It submits 9 real GPU-backed requests in total; this may consume cloud credits. It uses only Python's standard library. Results are written into a new timestamped `results\mi300x\latency_diag_v06_...` directory, with `summary.json` and `requests.csv`.

## How to read the output

- **direct_vllm**: Windows → SSH → vLLM. Includes SSH/network overhead and direct serving.
- **agent_vllm**: Windows → SSH → agent → readiness check → vLLM. Reports client duration minus agent-measured vLLM duration, which includes readiness check, network, parsing, and other overhead; not purely network overhead.
- **mission_control**: Windows → FastAPI → scheduler → SSH → agent → vLLM → DB, including queue wait, post-start overhead, and client polling.

Only three trials per path are recorded by default. These are diagnostic comparisons, **not statistically robust model benchmarks**. Calls run sequentially, so this does not test concurrency.

## Deployment boundaries

Do **not** restart the MI300X agent, vLLM, or ROCm just to use this script. No changes to the `.env`, Docker services, queue policies or database schema are needed.
