# Run from the AMD AI Factory project folder in Windows PowerShell.
$ErrorActionPreference = 'Stop'
Write-Host 'Checking AMD AI Factory local services...' -ForegroundColor Cyan
docker compose ps
$health = Invoke-RestMethod -Uri 'http://localhost:8000/health' -Method Get
$catalog = Invoke-RestMethod -Uri 'http://localhost:8000/api/policies' -Method Get
$cluster = Invoke-RestMethod -Uri 'http://localhost:8000/api/cluster' -Method Get
Write-Host ("Backend: {0}; Mode: {1}" -f $health.status, $health.mode)
Write-Host ("Algorithms: {0} placement + {1} queue" -f $catalog.placement.Count, $catalog.queue.Count)
Write-Host ("Simulated GPUs: {0}; Placement: {1}; Queue: {2}" -f $cluster.summary.node_count, $cluster.policy, $cluster.queue_policy)
if ($health.status -ne 'ok' -or $catalog.placement.Count -lt 20 -or $catalog.queue.Count -lt 8) {
    throw 'Health or scheduler catalog validation failed.'
}
Write-Host 'Scheduler catalog validation passed.' -ForegroundColor Green
