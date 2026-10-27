import { NextResponse } from "next/server";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Report = {status?: string; checks?: Record<string, boolean>; peak_observed_concurrency?: number;
  events?: unknown[]; output?: string; requested_jobs?: number; kind?: string; start_utc?: string; };
const BASE = process.env.RELIABILITY_RESULTS_DIR || "/app/reliability-evidence";

export async function GET() {
  try {
    const dirs = (await readdir(BASE, {withFileTypes:true}))
      .filter(d => d.isDirectory() && /^reliability_[A-Za-z0-9_-]{8,100}$/.test(d.name))
      .map(d => d.name).sort().reverse().slice(0, 30);
    const reports = [];
    for (const folder of dirs) {
      try {
        const raw = await readFile(path.join(BASE, folder, "report.json"), "utf8");
        if (raw.length > 2000000) continue;
        const r = JSON.parse(raw) as Report;
        const checks:Record<string,boolean> = {};
        for (const [key,value] of Object.entries(r.checks || {})) {
          if (/^[a-z_]{1,80}$/.test(key) && typeof value === "boolean") checks[key] = value;
        }
        reports.push({folder, status: r.status || "unknown", kind: r.kind || "simulation",
          start_utc: r.start_utc ?? null,
          requested_jobs: typeof r.requested_jobs === "number" ? r.requested_jobs : null,
          peak_observed_concurrency: typeof r.peak_observed_concurrency === "number" ? r.peak_observed_concurrency : null,
          checks});
      } catch { /* Ignore folders without readable summary. */ }
    }
    return NextResponse.json({available: reports.length > 0, reports, evidence_type:"simulation_only"},
      {headers:{"Cache-Control":"no-store", "X-Content-Type-Options":"nosniff"}});
  } catch {
    return NextResponse.json({available:false, reports:[], evidence_type:"simulation_only",
      message:"No mounted reliability reports. Run v0.9.1 and refresh."},
      {headers:{"Cache-Control":"no-store"}});
  }
}
