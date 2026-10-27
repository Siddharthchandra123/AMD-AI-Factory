# AMD AI Factory — Reliability Drill Diagnostic Fix v0.9.1

This is a **standalone replacement test runner**, not a backend patch. It does not edit any Docker service, Redis/SQL schema, GPU telemetry, saved MI300X benchmarks, or v0.9 script.

## Why v0.9 failed

v0.9 timed out looking for exactly one running and at least one queued job, but did not save the job/cluster state that would reveal why. The simulator sets a minimum of 3 seconds per synthetic job; possible explanations include scheduling failures, missed polling windows, and worker eligibility. The supplied error alone cannot determine which.

v0.9.1 submits longer synthetic requests (`output_tokens=256`, roughly 7–9 seconds each for the default model) and saves a **diagnostic snapshot** if a phase fails: current job IDs/status, temporary node state, queue totals, active policies, and failure phase. Sensitive API tokens, prompts, and agent configuration are not collected.

## Safely recover from the prior failed test (Windows PowerShell)

First verify no jobs are still running or queued:

```powershell
cd 'C:\Users\Lenovo\Downloads\amd-ai-factory'
(Invoke-RestMethod 'http://localhost:8000/api/cluster').summary
```

Re-run v0.9's idempotent restore from its printed recovery file, **after active jobs have finished**:

```powershell
python .\scripts\test_reliability_v0_9.py --restore --state '.\results\reliability\reliability_20261027T042055Z_8ef2a4\restore_state.json'
```

Inspect status and logs:

```powershell
(Invoke-RestMethod 'http://localhost:8000/api/cluster').nodes | Format-Table id,draining,active_jobs,max_concurrent_jobs
docker compose logs --tail 100 backend
```

## Install and run v0.9.1 (Windows PowerShell)

Extract the archive into the project root, then run **only while no other jobs are queued/running**:

```powershell
Expand-Archive -Path "$env:USERPROFILE\Downloads\amd-ai-factory-reliability-fix-v0.9.1.zip" -DestinationPath (Get-Location).Path -Force
python .\scripts\test_reliability_v0_9_1.py --run --jobs 3 --output-tokens 256 --timeout 90
```

If it fails, check the new report under `results/reliability/reliability_<timestamp>/report.json`, especially `failed_phase` and `diagnostic_snapshot`, and examine `docker compose logs --tail 100 backend`.

## Verification

```powershell
python -m unittest discover -s .\tests -p 'test_reliability_v0_9_1.py' -v
```

All experiments here use **synthetic nodes and synthetic inference durations**. They do not test a real MI300X or prove production-grade recovery.
