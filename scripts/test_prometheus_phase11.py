#!/usr/bin/env python3
"""Read-only Prometheus acceptance checks for AMD AI Factory Mission Control.
Uses only Python standard library. Never submits inference or changes services.
"""
import argparse
import datetime as dt
import json
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

METRICS = (
    "mission_pending_jobs",
    "mission_running_jobs",
    "mission_gpu_utilization_percent",
    "mission_gpu_hbm_used_gb",
    "mission_endpoint_available",
)
RULES = {"VirtualGPUHighUtilization", "SimulatedQueueBacklog"}

def request_json(url, timeout=12):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"Accept": "application/json"}), timeout=timeout) as res:
        return json.load(res)

def request_text(url, timeout=12):
    with urllib.request.urlopen(url, timeout=timeout) as res:
        return res.read().decode("utf-8", "replace")

def api(base, path, **params):
    suffix = "?" + urllib.parse.urlencode(params) if params else ""
    value = request_json(base + path + suffix)
    if value.get("status") != "success":
        raise ValueError(f"Prometheus API reported {value.get('status')}: {value.get('error', '')}")
    return value["data"]

def check(results, name, func):
    try:
        ok, details = func()
        results.append({"check": name, "passed": bool(ok), "details": details})
    except Exception as exc:
        results.append({"check": name, "passed": False, "details": f"{type(exc).__name__}: {exc}"})

def readable_scrape_age(value):
    if not value or value.startswith("0001-"):
        return None
    date = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return round((dt.datetime.now(dt.timezone.utc) - date).total_seconds(), 1)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prometheus", default="http://127.0.0.1:9090")
    parser.add_argument("--backend", default="http://127.0.0.1:8000")
    parser.add_argument("--evidence-dir", default="results/monitoring")
    args = parser.parse_args()
    prom = args.prometheus.rstrip("/")
    backend = args.backend.rstrip("/")
    results = []
    context = {"timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
               "prometheus": prom, "backend": backend, "checks": results}

    def health():
        body = request_text(prom + "/-/healthy").strip()
        ready = request_text(prom + "/-/ready").strip()
        return bool(body and ready), {"healthy_response": body[:120], "ready_response": ready[:120]}
    check(results, "prometheus_healthy_and_ready", health)

    def build():
        data = api(prom, "/api/v1/status/buildinfo")
        return bool(data.get("version")), {"version": data.get("version", "unknown"), "revision": data.get("revision", "")[:16]}
    check(results, "prometheus_api_and_version", build)

    def exporter():
        body = request_text(backend + "/metrics/")
        present = {m: bool(m in body) for m in METRICS}
        return all(present.values()), {"metric_families_present": present, "bytes": len(body.encode())}
    check(results, "backend_metrics_exporter", exporter)

    def targets():
        data = api(prom, "/api/v1/targets", state="active")
        targets_by_job = {}
        for target in data.get("activeTargets", []):
            job = target.get("labels", {}).get("job", "unknown")
            targets_by_job.setdefault(job, []).append({
                "health": target.get("health"),
                "last_error": target.get("lastError", ""),
                "scrape_age_seconds": readable_scrape_age(target.get("lastScrape")),
                "scrape_url": target.get("scrapeUrl")
            })
        required = ("mission-control", "prometheus")
        ok = all(job in targets_by_job and any(
            t["health"] == "up" and not t["last_error"] and
            t["scrape_age_seconds"] is not None and 0 <= t["scrape_age_seconds"] < 90
            for t in targets_by_job[job]) for job in required)
        return ok, {"required_targets": list(required), "targets": targets_by_job}
    check(results, "both_scrape_targets_up_and_fresh", targets)

    def up_query():
        info = {}
        for job in ("mission-control", "prometheus"):
            result = api(prom, "/api/v1/query", query=f'up{{job="{job}"}}')["result"]
            values = [float(series.get("value", [0, "0"])[1]) for series in result]
            info[job] = values
        return all(any(v == 1.0 for v in info[job]) for job in info), info
    check(results, "promql_up_both_targets", up_query)

    def gauge_query():
        info = {}
        for name in METRICS:
            data = api(prom, "/api/v1/query", query=name)
            values = data.get("result", [])
            info[name] = {"series": len(values), "samples": [
                {"labels": {key: val for key, val in row.get("metric", {}).items() if key in ("gpu_id", "source")},
                 "value": row.get("value", [None, None])[1]} for row in values[:4]]}
        return all(info[name]["series"] > 0 for name in METRICS), info
    check(results, "promql_mission_metrics_present", gauge_query)

    def recent_samples():
        end = time.time()
        data = api(prom, "/api/v1/query_range", query="mission_running_jobs", start=round(end-60, 3), end=round(end, 3), step="5s")
        lengths = [len(series.get("values", [])) for series in data.get("result", [])]
        return bool(lengths and max(lengths) >= 3), {"range_seconds": 60, "samples_per_series": lengths}
    check(results, "recent_timeseries_samples", recent_samples)

    def alerts():
        data = api(prom, "/api/v1/rules", type="alert")
        seen = {}
        for group in data.get("groups", []):
            for rule in group.get("rules", []):
                if rule.get("type") == "alerting":
                    seen[rule.get("name", "")] = {"state": rule.get("state", "unknown"), "group": group.get("name")}
        return RULES.issubset(seen), {"required_rules": sorted(RULES), "loaded_rules": seen,
                                       "note": "Rules loaded does not verify a firing notification."}
    check(results, "alert_rules_loaded", alerts)

    context["status"] = "pass" if all(item["passed"] for item in results) else "fail"
    context["passed"] = sum(bool(item["passed"]) for item in results)
    context["total"] = len(results)
    dest = pathlib.Path(args.evidence_dir)
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / ("prometheus_validation_" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json")
    target.write_text(json.dumps(context, indent=2), encoding="utf-8")
    for item in results:
        print(("PASS" if item["passed"] else "FAIL") + "  " + item["check"])
        if not item["passed"]:
            print("      " + json.dumps(item["details"], ensure_ascii=False)[:500])
    print(f"\nRESULT: {context['status'].upper()} ({context['passed']}/{context['total']})")
    print("Evidence:", target)
    return 0 if context["status"] == "pass" else 1

if __name__ == "__main__":
    sys.exit(main())
