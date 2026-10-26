#!/usr/bin/env bash
set -euo pipefail
printf '\n== Docker ==\n'
docker --version
docker compose version
printf '\n== Compose services ==\n'
docker compose ps
printf '\n== Health ==\n'
curl -fsS http://localhost:8000/health
printf '\n\n== GPU source mode ==\n'
curl -fsS http://localhost:8000/api/info
printf '\n\n== Done ==\n'
