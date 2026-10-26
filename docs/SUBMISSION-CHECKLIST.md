# Submission checklist (use after MI300X validation)

## Deliverables

- [ ] Public or private Git repository with documented version/tag.
- [ ] One-paragraph project summary, problem statement, differentiator and expected impact.
- [ ] Architecture diagram differentiating simulated and real execution.
- [ ] Reproducible local launch (`docker compose up --build -d`) and pass/fail screenshots.
- [ ] Evidence of real AMD Instinct MI300X, ROCm release, vLLM release and model revision.
- [ ] Raw benchmark artifacts with UTC timestamps, GPU IDs and measurement source labels.
- [ ] Baseline comparisons using the same model, prompts, concurrency and output length.
- [ ] Explain trade-offs and failure modes (GPU saturation, queue backlog, retries, routing).
- [ ] Demonstration video: queue jobs, watch nodes, show Grafana and performance report.
- [ ] License review for model weights and all third-party dependencies.
- [ ] Do not include secrets, tokens, identifiable customer data or private cloud credentials.

## Claims to avoid

- Do not describe synthetic telemetry as real MI300X utilization.
- Do not claim multi-node load balancing was physically validated if access is only a single GPU.
- Do not claim improved throughput or p95 latency until workloads are measured in a controlled A/B test.

Submission destination and application deadline are intentionally unspecified until confirmed by the project owner.
