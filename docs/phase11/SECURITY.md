# Security and release boundary

**Audience:** local technical demonstration, not an internet-facing production service.

## Key findings

- Phase 10 audit reported 9/9 local configuration checks passed. These covered loopback port exposure, `.env` Git ignore rule, persistent volumes and the absence of a populated agent token from `.env.example`.
- The mutation API key is **optional and disabled** in the observed local run (`write_token_enabled: false`). The existing UI does not automatically attach mutation credentials.
- Some GET/SSE APIs can expose job prompts or outputs. They are not secured by the optional mutation-only token.
- The remote GPU agent used its own `X-Mission-Token`; do not commit this token, the historical contents of `.env`, or the private key used to SSH to the cloud VM.
- The GPU cloud VM can be destroyed; archived real benchmark data and local simulation remain operational.

## Minimum controls before sharing

1. Inspect with `git status --ignored`, `git diff --cached` and a secret scanner of your choice.
2. Use this Phase 11 packager rather than zipping your entire live project, because the live project includes files unsuitable for publication.
3. Rotate any credential ever pasted into a shared log, committed to Git or exposed in screenshots; removing it from the latest file does not remove historical exposure.
4. Publish only architecture and curated aggregate data. Raw benchmark directories can include job identifiers and output content.
5. Keep FastAPI, Redis/Postgres and dashboards bound to loopback for local demos; use auth-capable gateway and TLS before any internet exposure.
6. Test with a nonprivileged user, apply dependency and image updates, and set non-default database/Grafana passwords for shared deployments.
7. Audit authorization on all endpoints; read APIs and SSE must not leak prompts or outputs to unauthorized viewers.
8. Do not claim a passing automated checklist substitutes for a penetration test or production review.

## Safe archive policy

The release script excludes `.env`, SSH keys, private certificates, `.git`, caches, Docker volumes, local databases, raw `results/` and backup folders. It scans included text for obvious tokens/private keys; if it detects a possible secret, the release **stops** and prints only file names and finding types. Patterns are incomplete; manually inspect the resulting archive. Running it does not upload anything.

## Failure semantics

The startup reconciling code may requeue simulated running jobs, but must **not automatically retry** real in-flight MI300X jobs because they could have completed on the remote GPU before the disconnect. Marking their outcomes unknown is safer than assuming exactly-once inference.
