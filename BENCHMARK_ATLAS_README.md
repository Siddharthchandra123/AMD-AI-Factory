# AMD AI Factory Mission Control — Benchmark Atlas v1.1

**One offline analytics pack for all existing experiment evidence.**  No DigitalOcean Droplet, GPU, Docker restart, token or extra Python packages are needed to generate the local web report and CSV indexes.

## Installation on Windows (PowerShell)

1. Back up your `results/` directory. Download `AMD_AI_Factory_Benchmark_Atlas_Kit_v1.1.zip` and save it to Downloads.
2. Open PowerShell in your AMD AI Factory project:

```powershell
cd "C:\Users\Lenovo\Downloads\amd-ai-factory"
Expand-Archive `
  -Path "$env:USERPROFILE\Downloads\AMD_AI_Factory_Benchmark_Atlas_Kit_v1.1.zip" `
  -DestinationPath (Get-Location).Path -Force
```

3. Run the generator against **your real local files**, without `--sample`:

```powershell
python .\scripts\generate_benchmark_atlas.py --project .
```

4. Open the report:

```powershell
Start-Process ".\results\benchmark-atlas\index.html"
```

Output is saved to `results/benchmark-atlas/`.  Existing benchmark data is read-only; no benchmarks are re-executed and no running services are modified.  No server or GPU connection is required.

### What will appear

```text
results/benchmark-atlas/
├── index.html                  # Filterable, local interactive analytics index
├── atlas_manifest.json         # Discovered evidence counts and limitations
├── figures/                    # SVG charts (editable, scalable, ready for README)
│   ├── 01_queue_latency.svg
│   ├── 02_e2e_latency.svg
│   ├── 03_inference_latency.svg
│   ├── 04_client_throughput.svg
│   ├── ...
│   ├── 16_<scenario>_policy_p95_wait.svg
│   ├── 17_<scenario>_policy_deadlines.svg
│   └── 20_telemetry_hbm.svg
└── tables/
    ├── runs_index.csv              # Discover ALL v2_* and legacy MI300X runs
    ├── jobs_index.csv              # Redacted real job timing index
    ├── telemetry_index.csv         # Recorded hardware poll snapshots
    ├── profiler_index.csv          # Request-path latency trials
    ├── scheduler_policy_index.csv  # 9 policies × 4 scenario aggregates per lab run
    ├── scheduler_trials_index.csv  # ALL synthetic experiment trials
    ├── scheduler_jobs_index.csv    # ALL synthetic job records
    ├── worker_health_samples_index.csv
    ├── reliability_security_index.csv
    ├── evidence_files_index.csv    # Every indexed CSV/JSON source path and size
    ├── matched_run_comparisons.csv # Descriptive same-size, same-model comparisons
    ├── data_quality_index.csv
    └── metric_dictionary.csv
```

## Folder discovery

| Local source | Evidence and charts |
|---|---|
| `results/mi300x/v2_*/summary.json` | Real MI300X load, queue, inference, end-to-end, throughput |
| `results/mi300x/v2_*/jobs.csv` | Per-job waiting, execution, post-start extra, timelines |
| `results/mi300x/v2_*/telemetry_polls.csv` | Recorded AMD SMI HBM, utilization, queue and running snapshots |
| `results/mi300x/real-summary.json` | Original four-job benchmark (legacy denominator) |
| `results/mi300x/latency_diag_v06_*/` | Direct vLLM vs agent vs controller path profiler |
| `results/scheduler-lab/lab_*/` | Synthetic per-policy, per-scenario, per-trial, per-job evidence |
| `results/reliability/reliability_*/report.json` | Simulated drain / resume experiments |
| `results/hardening/restart_*/report.json` | Controller restart checks |
| `results/hardening/worker_watch_*.json` | Worker health and load snapshots |
| `results/hardening/security_audit.json` | Local hardening audit |
| `results/monitoring/*.json` | Prometheus test evidence files if present |

The generator skips invalid or missing records, notes incomplete data, and derives p99/sample statistics **only when individual job records are present**.  It does not invent missing data.

## Graph catalog

**Physical MI300X**: p50/p95 queue, p50/p95 end-to-end, p50/p95 inference HTTP duration, client throughput, controller span, completion/failure counts, throughput vs workload, queue vs workload, largest sampled HBM, per-job queue and E2E traces, post-start overhead, stored telemetry HBM/utilization/queue, and request-path profiling.

**Synthetic scheduling**: four separate plots for **every scenario** (p95 wait, deadline success, tenant wait disparity, throughput), trial variability, mean per-job wait by policy.

**Operations**: healthy workers over sampled time and active worker jobs. Where evidence is absent, corresponding charts are omitted instead of fabricated.

## Historical preview included

The bundled `benchmark-atlas-preview/` contains charts based on **four reported real MI300X runs**, the **16-job timeline**, and the **three-path latency profiler** shared earlier. It does **not** include the user's raw archived `v2_*` CSVs, other repeated trials, or complete Scheduler Lab job traces. Use the local generator for that information. The included PDF and Excel workbook are explicitly marked preview/partial.

## Methodological safeguards

- **Real vs simulated**: physical MI300X v2 runs and synthetic policy-lab records are labeled separately.
- **Legacy throughput**: original 4-job makespan throughput is not compared against v2 client-wall-clock throughput.
- **Small samples**: p95 and p99 from a small number of jobs describe the sample, not production SLAs or confidence intervals.
- **Memory**: sparse HBM polls cannot prove true peak utilization or hardware saturation.
- **Placement**: one real serving endpoint cannot validate cross-GPU scheduling benefits.
- **Privacy**: no prompt text, generated output, tokens, `.env`, keys or API response error bodies are placed into output indexes. Job identifiers are shortened to eight characters.
- **No telemetry sharing**: this tool has no network calls. Source evidence is never modified.

For external publishing, review the output index to ensure filenames themselves contain no sensitive details. Keep full raw source evidence private unless you've separately reviewed it.

## Test the parser

```powershell
python .\scripts\test_atlas_parser.py
```

This constructs a small fake archive, verifies v2/profiler/scheduler/reliability parsing, and asserts that prompts and generated text are not copied into the public job index.

## Release note

This atlas reports observed measurements and aggregates. It is not an independent performance benchmark and does not imply official AMD affiliation or endorsement. The offline preview was produced from data shared in the project's earlier technical discussions.
