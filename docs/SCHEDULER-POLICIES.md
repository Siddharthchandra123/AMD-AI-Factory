# Advanced scheduler: policy catalog (v0.2)

**Development environment: Windows PowerShell + Docker Desktop, CPU-only.**
All MI300X telemetry, cache state, completion times, utilization and power are **simulated**. No NVIDIA/AMD GPU is required for local mode. The policy engine is pure Python and portable to a future adapter.

## Two independent decisions

1. **Queue policy** selects the next waiting job (non-preemptive). Includes admission and queue prioritization.
2. **Placement policy** selects an eligible GPU node. Every policy respects available HBM and per-node concurrency.

Combining the two gives **21 × 9 = 189** selectable policy pairs; this is not a claim that all 189 are distinct scheduling algorithms.

### GPU placement (21)

| Policy | Goal |
|---|---|
| `round_robin` | Rotate through eligible nodes |
| `weighted_round_robin` | Rotate more often through faster nodes (simulated weights) |
| `first_fit` | First eligible node |
| `least_loaded` | Minimize current simulated utilization |
| `least_connections` | Minimize active jobs |
| `least_memory_used` | Minimize absolute occupied HBM |
| `most_free_memory` | Maximize free HBM |
| `best_fit_memory` | Pack jobs into smallest sufficient free HBM |
| `worst_fit_memory` | Spread to largest sufficient free HBM |
| `capacity_weighted` | Maximize free HBM ratio |
| `power_aware` | Prefer lower instantaneous simulated watts |
| `thermal_aware` | Prefer cooler nodes |
| `balanced_score` | Weighted utilization/HBM/concurrency |
| `latency_aware` | Estimate node load-adjusted delay using performance weight |
| `energy_efficiency` | Power/performance proxy |
| `locality_aware` | Prefer nodes with matching model in synthetic cache |
| `rendezvous_hash` | Stable model-affinity hash |
| `power_of_two_choices` | Randomly sample two, select less loaded |
| `random` | Uniform random baseline |
| `weighted_random` | Weighted lottery by headroom and relative performance |
| `adaptive` | Multi-factor heuristic scoring |

### Queue dispatch (9)

| Policy | Goal |
|---|---|
| `priority_fifo` | High/normal/low tiers with FIFO within tier (original v0.1 behavior) |
| `fcfs` | Global arrival order |
| `shortest_job_first` | Shortest estimated job first |
| `longest_job_first` | Longest estimated job first |
| `highest_response_ratio_next` | Maximize (wait + service) / service |
| `priority_aging` | Permit sufficiently old lower-priority jobs to overtake newer higher-priority jobs |
| `earliest_deadline_first` | Earliest supplied `deadline_seconds` first; FIFO for jobs without deadlines |
| `fair_share` | Fewer currently running jobs for a tenant (simplified concurrency-based fairness) |
| `random_queue` | Random dispatch baseline |

**Non-preemptive only:** SRTF, time-quantum CPU round-robin, real GPU context preemption, gang scheduling and Kubernetes-level placement are **not** implemented. GPU-operator support and ROCm telemetry are future work. `round_robin` here refers to GPU **node placement**, not CPU time slicing.

## API usage (Windows PowerShell)

List policies:

```powershell
Invoke-RestMethod 'http://localhost:8000/api/policies' | ConvertTo-Json -Depth 8
```

Choose queue + placement:

```powershell
Invoke-RestMethod -Method Put -Uri 'http://localhost:8000/api/policy' -ContentType 'application/json' -Body '{"policy":"adaptive"}'
Invoke-RestMethod -Method Put -Uri 'http://localhost:8000/api/queue-policy' -ContentType 'application/json' -Body '{"policy":"shortest_job_first"}'
```

Submit with tenant and deadline (in seconds from submission):

```powershell
$body = @{model='model-7b'; priority='normal'; prompt_tokens=512; output_tokens=256; count=8; tenant='team_a'; deadline_seconds=90} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri 'http://localhost:8000/api/jobs/batch' -ContentType 'application/json' -Body $body
```

## Benchmarking

Run a quick 3-placement comparison:

```powershell
python .\scripts\benchmark_local.py --jobs 8 --placement round_robin,least_loaded,adaptive
```

Compare queue policies under one placement:

```powershell
python .\scripts\benchmark_local.py --jobs 8 --placement least_loaded --queue priority_fifo,shortest_job_first,highest_response_ratio_next
```

Enumerating **all** policies with `--all-placement` and `--all-queue` runs 189 sequential combinations and can be slow. Run a subset first. The simulation has four homogeneous virtual GPUs, a fixed synthetic service-time model and no realistic network effects. Many policies therefore produce similar results. Avoid claims of real GPU speedups or scheduling superiority before controlled benchmarking on physical hardware.

## Compatibility / limitations

- Existing endpoints `/api/policy`, `/api/jobs/batch`, `/api/cluster`, and `/api/info` remain operational.
- `PUT /api/queue-policy`, `GET /api/policies`, and optional `tenant` and `deadline_seconds` are new.
- An additive PostgreSQL migration adds `tenant` and `deadline_at` to existing v0.1 tables automatically on backend startup; **do not delete volumes** to upgrade.
- Single scheduler worker only. Multi-process coordination, cancellation, preemption, admission quotas, dynamic model loading costs, multi-instance scheduling and production auth are future work.
- Random policies are not seeded from the API, so live runs are not exactly reproducible; deterministic unit tests use injected RNG. Benchmark comparisons should use repeated runs with identical workload traces before drawing conclusions.
