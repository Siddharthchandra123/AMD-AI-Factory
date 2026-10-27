# Release candidate acceptance checklist

## Already demonstrated in supplied outputs

- [x] Real ROCm/vLLM MI300X inference through the remote agent, single endpoint, 16/16 jobs completed.
- [x] Observed lower p95 end-to-end latency after v0.5 at matched 8-job load.
- [x] v0.6 profiler measured direct vLLM, agent and controller paths (three sequential trials each).
- [x] Local simulated worker drain/resume: 6/6 checks passed.
- [x] Local simulated controller restart/reconciliation: 6/6 checks passed.
- [x] Local configuration security audit: 9/9 checks passed.
- [x] Simulated Grafana dashboard displayed utilization, queue, and scheduler metrics.

## Must be done on the owner's actual Windows project before tagging

- [ ] Phase11 read-only regression returns no FAIL; investigate WARN.
- [ ] Docker Compose `config -q` passes; frontend and backend local URLs return HTTP 200.
- [ ] `/benchmarks`, `/scheduler-lab`, `/hardening` pages show data rather than placeholders.
- [ ] Relevant Python tests and the TypeScript Next.js production build pass.
- [ ] Verify all active and queued job counts are zero when taking a final snapshot.
- [ ] `phase11_release.py --dry-run` lists the correct local files.
- [ ] Build the v1.0.0-rc1 archive, verify its manifest, and manually inspect the archive for sensitive data.
- [ ] Test the ZIP from a clean extraction in a separate local directory (do not replace the running installation).
- [ ] Confirm optional `.env` example does not contain live secrets. Rotate old leaked credentials as needed.
- [ ] Choose/add an explicit project LICENSE before a public release.
- [ ] Capture screenshots of the dashboard and evidence pages.
- [ ] Push to GitHub/tag only after reviewing `git status`, `git diff`, GitHub secret scanning and the archive.

## Not yet achieved / out of scope

- [ ] Real multi-GPU/multi-worker placement superiority.
- [ ] ROCm vLLM high-resolution observability under controlled repeated hardware runs.
- [ ] Network fault injection on live remote agents, exactly-once semantics or multi-controller high availability.
- [ ] Penetration testing, production IAM, tenancy isolation and autoscaling.

A release candidate can be published with limitations documented, not silently marked production-ready.
