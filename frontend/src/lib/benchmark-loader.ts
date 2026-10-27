/** Read-only MI300X benchmark evidence loader. Never initiates inference or network calls. */
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";

export type JobTiming = {
  id: string;
  startUtc: string | null;
  queue: number | null;
  inference: number | null;
  other: number | null;
  endToEnd: number | null;
};
export type Diagnostic = { path: string; n: number | null; median: number | null; p95: number | null };
export type EvidenceRun = {
  id: string; type: "legacy" | "v2" | "diagnostic"; label: string; timestamp: string | null;
  source: string; model: string | null; requested: number | null; completed: number | null; failed: number | null;
  queueP50: number | null; queueP95: number | null;
  inferenceP50: number | null; inferenceP95: number | null;
  e2eP50: number | null; e2eP95: number | null;
  clientWall: number | null; controllerSpan: number | null;
  throughput: number | null; controllerThroughput: number | null;
  hbmPeak: number | null; gpuPollRows: number | null;
  endpointCount: number | null; concurrency: number | null;
  jobs: JobTiming[]; diagnostics: Diagnostic[];
  notes: string[];
};
export type EvidenceSet = { rootStatus: "ok" | "missing" | "error"; root: string; runs: EvidenceRun[]; errors: string[] };

export function finite(value: unknown): number | null {
  if (value === null || value === undefined || value === "" || typeof value === "boolean") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}
function str(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}
function object(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}
function textIn(obj: Record<string, unknown>, key: string): string | null { return str(obj[key]); }
function numberIn(obj: Record<string, unknown>, key: string): number | null { return finite(obj[key]); }
function isoFromRun(name: string): string | null {
  const m = name.match(/(?:v2_|latency_diag_v0?6_)(\d{8})_(\d{6})/);
  if (!m) return null;
  return `${m[1].slice(0,4)}-${m[1].slice(4,6)}-${m[1].slice(6,8)}T${m[2].slice(0,2)}:${m[2].slice(2,4)}:${m[2].slice(4,6)}Z`;
}
function makeLabel(run: EvidenceRun): string {
  if (run.type === "diagnostic") return `Latency profiler · ${run.timestamp?.slice(0,16).replace("T", " ") ?? run.id}`;
  if (run.type === "legacy") return `${run.requested ?? "Original"}-job baseline · v0.3`;
  return `${run.requested ?? "?"} jobs · ${run.timestamp?.slice(0,16).replace("T", " ") ?? run.id}`;
}

/** RFC-4180-style CSV reader; caps handled by caller. No external dependencies. */
export function parseCsv(csv: string): Record<string, string>[] {
  const matrix: string[][] = [];
  let row: string[] = [], value = "", quoted = false;
  const pushField = () => { row.push(value); value = ""; };
  const pushRow = () => { pushField(); if (row.some(v => v.length)) matrix.push(row); row = []; };
  for (let i = 0; i < csv.length; i++) {
    const c = csv[i];
    if (c === '"') {
      if (quoted && csv[i + 1] === '"') { value += '"'; i++; }
      else quoted = !quoted;
    } else if (c === "," && !quoted) pushField();
    else if ((c === "\n" || c === "\r") && !quoted) {
      if (c === "\r" && csv[i + 1] === "\n") i++;
      pushRow();
    } else value += c;
  }
  if (value.length || row.length) pushRow();
  if (!matrix.length) return [];
  const [head, ...rows] = matrix;
  const columns = head.map(h => h.trim().replace(/^\uFEFF/, ""));
  return rows.slice(0, 2000).map(cells => Object.fromEntries(columns.map((col, i) => [col, cells[i] ?? ""])));
}
function timeDelta(a: string | null, b: string | null): number | null {
  if (!a || !b) return null;
  const start = Date.parse(a), finish = Date.parse(b);
  return Number.isFinite(start) && Number.isFinite(finish) ? Math.max(0, (finish - start) / 1000) : null;
}
export function parseTimings(csv: string): JobTiming[] {
  return parseCsv(csv).map(row => {
    const inference = finite(row.execution_seconds) ?? finite(row.duration_seconds);
    const life = timeDelta(row.started_at ?? null, row.completed_at ?? null);
    const other = life !== null && inference !== null ? Math.max(0, life - inference) : null;
    return {
      id: (row.id || "unknown").slice(0, 8), startUtc: row.started_at || null,
      queue: finite(row.queue_wait_seconds), inference, other,
      endToEnd: finite(row.end_to_end_seconds) ?? timeDelta(row.created_at ?? null, row.completed_at ?? null),
    };
  }).sort((a, b) => (a.startUtc || "").localeCompare(b.startUtc || ""));
}
function buildRun(id: string, summaryRaw: unknown, jobs: JobTiming[]): EvidenceRun {
  const doc = object(summaryRaw);
  const isLegacy = id === "legacy";
  const isDiagnostic = id.startsWith("latency_diag_");
  const records = object(doc.results);
  const diagnostics = isDiagnostic ? Object.entries(records).map(([key, raw]) => {
    const rec = object(raw);
    return { path: key, n: numberIn(rec, "n"), median: numberIn(rec, "median_client_seconds"), p95: numberIn(rec, "p95_client_seconds") };
  }) : [];
  const endpoints = Array.isArray(doc.unique_serving_endpoints) ? doc.unique_serving_endpoints :
    Array.isArray(doc.observed_serving_endpoints) ? doc.observed_serving_endpoints : [];
  const concurrencySettings = object(doc.configured_max_concurrent_jobs);
  const concurrency = Object.values(concurrencySettings).length === 1 ? finite(Object.values(concurrencySettings)[0]) : null;
  const run: EvidenceRun = {
    id, type: isDiagnostic ? "diagnostic" : isLegacy ? "legacy" : "v2", label: "", timestamp: textIn(doc, "timestamp_utc") ?? isoFromRun(id),
    source: textIn(doc, "source") ?? (isDiagnostic ? "latency_diagnostic" : "unknown"), model: textIn(doc, "model"),
    requested: numberIn(doc, "requested_jobs") ?? numberIn(doc, "submitted"),
    completed: numberIn(doc, "completed"), failed: numberIn(doc, "failed"),
    queueP50: numberIn(doc, "p50_queue_wait_seconds"), queueP95: numberIn(doc, "p95_queue_wait_seconds"),
    inferenceP50: numberIn(doc, "p50_inference_seconds") ?? numberIn(doc, "p50_job_seconds"),
    inferenceP95: numberIn(doc, "p95_inference_seconds") ?? numberIn(doc, "p95_job_seconds"),
    e2eP50: numberIn(doc, "p50_end_to_end_seconds"), e2eP95: numberIn(doc, "p95_end_to_end_seconds"),
    clientWall: numberIn(doc, "client_observed_wall_seconds") ?? numberIn(doc, "makespan_seconds"),
    controllerSpan: numberIn(doc, "controller_lifecycle_span_seconds"),
    throughput: numberIn(doc, "observed_client_tokens_per_second") ?? numberIn(doc, "completion_tokens_per_second"),
    controllerThroughput: numberIn(doc, "controller_lifecycle_tokens_per_second"),
    hbmPeak: numberIn(doc, "peak_polled_hbm_gib"), gpuPollRows: numberIn(doc, "gpu_poll_rows") ?? numberIn(doc, "gpu_samples"),
    endpointCount: isDiagnostic ? 1 : endpoints.length || null, concurrency,
    jobs: isDiagnostic ? [] : jobs, diagnostics,
    notes: [
      ...(str(doc.warning) ? [String(doc.warning)] : []),
      ...(isLegacy ? ["Legacy throughput uses original benchmark makespan; do not treat it as directly equivalent to v2 throughput."] : []),
      ...(isDiagnostic ? ["Sequential, small-sample path diagnostics; not a GPU saturation or concurrency benchmark."] : []),
      "Stored local evidence; not live GPU telemetry or a fresh hardware measurement.",
    ],
  };
  run.label = makeLabel(run);
  return run;
}
async function readLimited(filename: string, max = 3_000_000): Promise<string> {
  // Evidence files are local and mounted read-only; limit individual parsed files to 3 MB.
  const data = await readFile(filename, { encoding: "utf8" });
  if (data.length > max) throw new Error("File is larger than the evidence-viewer limit");
  return data;
}
export async function loadEvidence(rootDir: string): Promise<EvidenceSet> {
  const root = path.resolve(rootDir);
  let entries;
  try { entries = await readdir(root, { withFileTypes: true }); }
  catch (err) {
    const code = (err as NodeJS.ErrnoException).code;
    return { rootStatus: code === "ENOENT" ? "missing" : "error", root, runs: [], errors: [`Unable to read results directory (${code || "unknown error"})`] };
  }
  const errors: string[] = [], runs: EvidenceRun[] = [];
  const legacyName = entries.some(e => e.isFile() && e.name === "real-summary.json");
  if (legacyName) {
    try {
      const summary = JSON.parse(await readLimited(path.join(root, "real-summary.json")));
      const jobs = entries.some(e => e.isFile() && e.name === "real-jobs.csv") ?
        parseTimings(await readLimited(path.join(root, "real-jobs.csv"))) : [];
      runs.push(buildRun("legacy", summary, jobs));
    } catch (err) { errors.push(`Legacy run: ${String(err).slice(0,160)}`); }
  }
  const folders = entries.filter(e => e.isDirectory() && (e.name.startsWith("v2_") || e.name.startsWith("latency_diag_v06_"))).sort((a,b) => b.name.localeCompare(a.name)).slice(0, 100);
  for (const folder of folders) {
    const id = folder.name;
    try {
      const location = path.join(root, id);
      const summary = JSON.parse(await readLimited(path.join(location, "summary.json")));
      let jobs: JobTiming[] = [];
      if (id.startsWith("v2_")) {
        try { jobs = parseTimings(await readLimited(path.join(location, "jobs.csv"))); }
        catch { /* Some runs may have only a summary; keep them viewable. */ }
      }
      runs.push(buildRun(id, summary, jobs));
    } catch (err) { errors.push(`${id}: ${String(err).slice(0,160)}`); }
  }
  runs.sort((a,b) => (b.timestamp || "").localeCompare(a.timestamp || ""));
  return { rootStatus: "ok", root, runs, errors };
}
