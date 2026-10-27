import assert from "node:assert/strict";
import {mkdtemp,mkdir,writeFile,rm} from "node:fs/promises";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {loadEvidence,parseCsv,parseTimings,finite} from "../frontend/src/lib/benchmark-loader.ts";

assert.equal(finite(""), null);
assert.equal(finite("15.22"),15.22);
assert.deepEqual(parseCsv('id,note\n123,"a,b"\n456,"line\ncontinued"\n'),[{id:'123',note:'a,b'},{id:'456',note:'line\ncontinued'}]);
const jobs=parseTimings('id,created_at,started_at,completed_at,queue_wait_seconds,execution_seconds,end_to_end_seconds\nx,2026-10-26T10:00:00Z,2026-10-26T10:00:02Z,2026-10-26T10:00:03Z,2,0.2,3\n');
assert.equal(jobs[0].other,0.8);
assert.equal(jobs[0].queue,2);
const dir=await mkdtemp(join(tmpdir(),"amd-analytics-"));
try {
  const old={source:'real_vllm',model:'Qwen/Qwen3-0.6B',submitted:4,completed:4,failed:0,p95_job_seconds:0.2326,completion_tokens_per_second:31.131};
  await writeFile(join(dir,"real-summary.json"), JSON.stringify(old));
  const v2=join(dir,"v2_20261026_101148_738883");await mkdir(v2);
  await writeFile(join(v2,"summary.json"),JSON.stringify({source:'real_vllm',mode:'mi300x',model:'Qwen/Qwen3-0.6B',requested_jobs:16,completed:16,failed:0,p95_queue_wait_seconds:13.7397,p95_end_to_end_seconds:15.3572,observed_client_tokens_per_second:75.68,peak_polled_hbm_gib:46.885,gpu_poll_rows:4,unique_serving_endpoints:['worker-1'],configured_max_concurrent_jobs:{'worker-1':2}}));
  await writeFile(join(v2,"jobs.csv"),'id,created_at,started_at,completed_at,queue_wait_seconds,execution_seconds,end_to_end_seconds\n123,2026-10-26T10:00:00Z,2026-10-26T10:00:02Z,2026-10-26T10:00:03Z,2,0.2,3\n');
  const diag=join(dir,"latency_diag_v06_20261026_102910_100211");await mkdir(diag);
  await writeFile(join(diag,"summary.json"), JSON.stringify({source:'latency_diagnostic',model:'Qwen/Qwen3-0.6B',timestamp_utc:'2026-10-26T10:29:10Z',results:{direct_vllm:{n:3,median_client_seconds:1.5487,p95_client_seconds:1.5703}}}));
  const res=await loadEvidence(dir);
  assert.equal(res.rootStatus,'ok');assert.equal(res.runs.length,3);
  const heavy=res.runs.find(r=>r.requested===16);
  assert.equal(heavy.queueP95,13.7397);assert.equal(heavy.jobs.length,1);assert.equal(heavy.concurrency,2);
  const legacy=res.runs.find(r=>r.id==='legacy');assert.equal(legacy.completed,4);assert.equal(legacy.e2eP95,null);
  const profile=res.runs.find(r=>r.type==='diagnostic');assert.equal(profile.diagnostics[0].median,1.5487);
  assert.equal(res.errors.length,0);
  console.log('PASS: unit parsing, real v2, legacy, diagnostic, and missing metrics.');
} finally {await rm(dir,{recursive:true,force:true});}
const miss=await loadEvidence(join(tmpdir(),'path-that-is-unlikely-to-exist-123456789'));
assert.equal(miss.rootStatus,'missing');
console.log('PASS: missing folder handled safely.');
