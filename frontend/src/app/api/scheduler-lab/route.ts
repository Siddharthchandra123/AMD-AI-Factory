import { NextResponse } from "next/server";
import { readFile } from "node:fs/promises";
import path from "node:path";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET() {
  const root = process.env.SCHEDULER_LAB_RESULTS_DIR || "/app/scheduler-lab-evidence";
  try {
    const meta = JSON.parse(await readFile(path.join(root, "latest.json"), "utf8")) as {folder?: unknown};
    // Never let a file-controlled name traverse outside the evidence mount.
    if (typeof meta.folder !== "string" || !/^lab_\d{8}T\d{12}Z$/.test(meta.folder)) {
      throw new Error("Invalid latest.json run identifier");
    }
    const raw = await readFile(path.join(root, meta.folder, "summary.json"), "utf8");
    if (raw.length > 5_000_000) throw new Error("Summary exceeds 5 MB safety limit");
    const parsed = JSON.parse(raw);
    if (!parsed || parsed.manifest?.kind !== "CPU-only discrete-event simulation (NOT MI300X benchmark)"
        || !Array.isArray(parsed.aggregates)) {
      throw new Error("Unrecognized Scheduler Lab result schema");
    }
    return NextResponse.json({available: true, folder: meta.folder, ...parsed},
      {headers: {"Cache-Control": "no-store"}});
  } catch (err) {
    return NextResponse.json({available: false,
      message: err instanceof Error ? err.message : "Scheduler Lab evidence unavailable",
      setup: "Run python .\\scripts\\evaluate_queue_policies_v0_8.py from the project root."},
      {headers: {"Cache-Control": "no-store"}});
  }
}
