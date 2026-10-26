# Legacy validation notes (v0.1/v0.2)

**Superseded for v0.3:** use [MI300X-DYNAMIC-DEPLOYMENT.md](MI300X-DYNAMIC-DEPLOYMENT.md) for live agent setup and valid AMD telemetry.

# Phase 2 — Real AMD Instinct MI300X validation plan

**Do not use any of the synthetic charts from Phase 1 as measured AMD performance.**

## Before deploying

1. Confirm remote host OS, GPU visibility, AMD drivers, ROCm compatibility, and whether containers and system-level telemetry are permitted.
2. Establish SSH access and verify `rocminfo` and `amd-smi list` where available.
3. Record MI300X GPU count, HBM, ROCm version, vLLM version, and model weights/revision.
4. Use official upstream ROCm-enabled vLLM images (`vllm/vllm-openai-rocm`) with a tested pinned tag. Avoid deprecated `rocm/vllm` images.
5. Run a small model baseline with fixed prompt/output token distributions and measured concurrency.
6. Collect GPU monitoring via AMD SMI / AMD Device Metrics Exporter where permitted.
7. Save raw timestamps, TTFT, time-per-token or ITL, generated tokens/sec, p50/p95/p99 latency, requests/sec, HBM use, GPU utilization, errors, model identifier and software version.
8. Compare least-loaded and round-robin using the same workload replay. A single physical GPU cannot validate multi-node routing; run an explicit single-node benchmark and label the distinction.
9. Export results and prepare repeatable scripts with no tokens, API keys or passwords committed.

## Official upstream docs

- ROCm vLLM: https://rocm.docs.amd.com/projects/ai-ecosystem/en/latest/inference/vllm.html
- AMD Instinct docs: https://instinct.docs.amd.com/
- AMD GPU Operator: https://instinct.docs.amd.com/projects/gpu-operator/en/latest/
- AMD SMI: https://rocm.docs.amd.com/projects/amdsmi/en/latest/

No GPU-side deployment commands are included yet because they must match actual MI300X host permissions, driver/ROCm compatibility and selected model.
