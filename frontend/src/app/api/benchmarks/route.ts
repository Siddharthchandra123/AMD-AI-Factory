import { NextResponse } from "next/server";
import { loadEvidence } from "../../../lib/benchmark-loader";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET() {
  try {
    const directory = process.env.BENCHMARK_RESULTS_DIR || "/app/benchmark-evidence";
    const results = await loadEvidence(directory);
    return NextResponse.json(results, {headers: {"Cache-Control": "no-store, max-age=0"}});
  } catch (e) {
    return NextResponse.json({rootStatus:"error",runs:[],errors:[String(e).slice(0,160)]}, {status:500,headers:{"Cache-Control":"no-store"}});
  }
}
