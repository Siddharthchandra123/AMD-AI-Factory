# Benchmark evidence and interpretation

All numeric results below are transcribed from user-reported command outputs, not re-extracted from the complete source `results/mi300x/` archive. Preserve the real raw archive independently.

## MI300X results

| Run | Jobs | Completed | p95 queue (s) | p95 inference HTTP (s) | p95 E2E (s) | Client throughput (tokens/s) |
|---|---:|---:|---:|---:|---:|---:|
| Original 4 jobs (v0.3 script) | 4 | 4 | — | 0.2326 (job duration) | — | 31.131 (different makespan denominator) |
| 8 jobs before v0.5 | 8 | 8 | 11.2829 | 0.2073 | 12.7369 | 49.607 |
| 8 jobs after v0.5 | 8 | 8 | 4.6745 | 0.2110 | 5.8264 | 69.661 |
| 16 jobs after v0.5 | 16 | 16 | 13.7397 | 0.2132 | 15.3572 | 75.680 |

The original 4-job throughput came from a different benchmark formula; **do not compare it directly** with v2 client-throughput figures. All tests used Qwen/Qwen3-0.6B on a **single MI300X serving endpoint**.

### Observed eight-job before/after differences

- p95 queue waiting time: 11.2829 to 4.6745 s (**58.6% decrease**).
- p95 end-to-end duration: 12.7369 to 5.8264 s (**54.3% decrease**).
- Client throughput: 49.607 to 69.661 output tokens/s (**40.4% increase**).
- The per-call p95 inference duration stayed near 0.21 s; it is a partial timing boundary and **not** user-perceived end-to-end latency.
- Improvements describe one observed before/after comparison; there is not yet a replicated controlled experiment with confidence intervals.

### Sixteen-job scaling and lifecycle diagnosis

At 16 jobs with 2 configured concurrent slots, all completed; client wall time **20.296 s**, p95 queue **13.7397 s**, and peak *polled* HBM memory **46.885 GiB**. Jobs appeared in near-simultaneous pairs spaced roughly 1.4–2.2 seconds apart. The average post-start time outside the measured inference HTTP call was approximately **1.59 s** in the shared 16-job timeline. It cannot be attributed to a single component without finer instrumentation.

Sparse HBM snapshots (4 rows in the 16-job test) cannot establish peak device utilization, server throughput or memory saturation.

## v0.6 direct/agent/control plane path profiling

| Path | Median client duration (s) | p95 (s) | Trials |
|---|---:|---:|---:|
| Direct vLLM through SSH | 1.5487 | 1.5703 | 3 |
| Agent-mediated inference | 1.1988 | 1.6402 | 3 |
| Full Mission Control | 1.8450 | 1.9246 | 3 |

These were three sequential, nonconcurrent requests per path. Agent-reported vLLM HTTP duration was ~0.18 s and excludes other calls. They measure network/client + service operations, not isolated MI300X silicon performance.

## Simulated tests (not MI300X benchmarks)

- v0.8 Scheduler Lab: 9 implemented queue-ordering policies, 4 synthetic workload scenarios, 3 trials, 32 jobs per run, with deterministic inputs. Compared queue times, turnaround, fairness proxy and deadlines. Source code `rank_queue` was reused, but not the full backend/agent serving stack.
- v0.9.1 drain/resume: 6/6 reported checks passed on simulated workers.
- v1.0.1 controller restart: 6/6 reported checks passed on simulated jobs.
- Phase 10 local security audit: 9/9 checks passed after clearing token placeholder. Not a penetration test.

## Reproduce from the user's local archive

Use `scripts/benchmark_mi300x_v2.py` only if a live real MI300X has been provisioned. **Do not attempt the real benchmark on simulation and label its output 'real'.** With no GPU, inspect read-only `/benchmarks`, run `scripts/evaluate_queue_policies_v0_8.py`, and use the local Phase 9/10 reliability tools. Do not rerun disruptive restart drills while users/jobs are active.
