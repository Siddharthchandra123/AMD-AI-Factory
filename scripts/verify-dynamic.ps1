# PowerShell 5.1+/7, Windows CPU-only smoke tests. Does not enable MI300X mode.
$ErrorActionPreference = "Stop"
$base = "http://localhost:8000"
Write-Host "=== AMD AI Factory v0.3 dynamic smoke test ===" -ForegroundColor Cyan
$health = Invoke-RestMethod -Uri "$base/health"
if ($health.status -ne "ok") { throw "Backend unhealthy" }
if ($health.mode -ne "simulation") { throw "Expected simulation mode. Switch back only when idle." }
Write-Host "Backend: $($health.version), $($health.mode)" -ForegroundColor Green
$before = Invoke-RestMethod -Uri "$base/api/cluster"
Write-Host "Before: $($before.summary.node_count) virtual nodes"
$added = Invoke-RestMethod -Uri "$base/api/simulator/nodes" -Method POST -ContentType "application/json" -Body (@{memory_total_gb=64;max_concurrent_jobs=3} | ConvertTo-Json)
try {
  $after = Invoke-RestMethod -Uri "$base/api/cluster"
  if ($after.summary.node_count -ne ($before.summary.node_count + 1)) {throw "Add node did not increase count"}
  Write-Host "Dynamic discovery: added $($added.id)" -ForegroundColor Green
  Invoke-RestMethod -Uri "$base/api/nodes/$($added.id)/drain" -Method PUT -ContentType "application/json" -Body '{"draining":true}' | Out-Null
  $drained = (Invoke-RestMethod -Uri "$base/api/cluster").nodes | Where-Object id -eq $added.id
  if (-not $drained.draining) {throw "Drain did not take effect"}
  Write-Host "Dynamic draining works" -ForegroundColor Green
} finally {
  Invoke-RestMethod -Uri "$base/api/simulator/nodes/$($added.id)" -Method DELETE | Out-Null
}
$policy = Invoke-RestMethod -Uri "$base/api/policies"
Write-Host "Placement policies: $($policy.placement.Count) | Queue policies: $($policy.queue.Count)" -ForegroundColor Green
$models = Invoke-RestMethod -Uri "$base/api/models"
Write-Host "Models currently discovered: $($models.models.Count)"
$runtime = Invoke-RestMethod -Uri "$base/api/runtime"
Write-Host "Remote MI300X agent connections: $($runtime.connected_workers)"
Write-Host "PASS: dynamic local smoke checks complete" -ForegroundColor Green
