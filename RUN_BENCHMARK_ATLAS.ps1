# Run in Windows PowerShell after extracting this kit into the amd-ai-factory root.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
python .\scripts\generate_benchmark_atlas.py --project .
if ($LASTEXITCODE -ne 0) { throw "Benchmark Atlas generation failed: exit $LASTEXITCODE" }
Start-Process (Join-Path $PSScriptRoot 'results\benchmark-atlas\index.html')
