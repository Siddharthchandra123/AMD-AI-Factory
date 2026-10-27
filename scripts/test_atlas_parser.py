import csv,json,subprocess,tempfile,sys
from pathlib import Path
SCRIPT=Path(__file__).with_name('generate_benchmark_atlas.py')
def emit(path,data):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(data),encoding='utf-8')
def csvout(path,rows):
 path.parent.mkdir(parents=True,exist_ok=True)
 with path.open('w',newline='',encoding='utf-8') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
with tempfile.TemporaryDirectory() as td:
 root=Path(td);mi=root/'results'/'mi300x';v2=mi/'v2_20261026_110101_000000'
 emit(v2/'summary.json',{'source':'real_vllm','mode':'mi300x','model':'Qwen/Qwen3-0.6B','requested_jobs':2,'completed':2,'failed':0,'p50_queue_wait_seconds':0.2,'p95_queue_wait_seconds':0.5,'p95_inference_seconds':0.2,'p95_end_to_end_seconds':1.2,'client_observed_wall_seconds':3,'observed_client_tokens_per_second':64,'gpu_poll_rows':2,'peak_polled_hbm_gib':44,'unique_serving_endpoints':['mi300x-host-1/vllm-1']})
 csvout(v2/'jobs.csv',[{'id':'abcdef00-1234-0000','model':'Qwen/Qwen3-0.6B','status':'completed','gpu_id':'mi300x-host-1/vllm-1','created_at':'2026-10-26T11:00:00+00:00','started_at':'2026-10-26T11:00:01+00:00','completed_at':'2026-10-26T11:00:02+00:00','queue_wait_seconds':1,'execution_seconds':0.2,'end_to_end_seconds':2,'completion_tokens':96,'prompt':'SECRET PROMPT','output':'PRIVATE OUTPUT'}, {'id':'abcdef11-1234-0000','model':'Qwen/Qwen3-0.6B','status':'completed','gpu_id':'mi300x-host-1/vllm-1','created_at':'2026-10-26T11:00:00+00:00','started_at':'2026-10-26T11:00:02+00:00','completed_at':'2026-10-26T11:00:03+00:00','queue_wait_seconds':2,'execution_seconds':0.2,'end_to_end_seconds':3,'completion_tokens':96,'prompt':'SECRET PROMPT','output':'PRIVATE OUTPUT'}])
 csvout(v2/'telemetry_polls.csv',[{'polled_utc':'2026-10-26T11:00:01+00:00','endpoint':'mi300x-host-1/vllm-1','hbm_used_gib':'46','hbm_total_gib':'191.7','gpu_util_percent':'75','cluster_queued_jobs':'1','cluster_running_jobs':'1'}])
 prof=mi/'latency_diag_v06_20261026_122233_003311';emit(prof/'summary.json',{'model':'Qwen/Qwen3-0.6B','timestamp_utc':'2026-10-26','results':{'direct_vllm':{'median_client_seconds':1,'p95_client_seconds':1.5},'mission_control':{'median_client_seconds':2,'p95_client_seconds':3}}})
 csvout(prof/'requests.csv',[{'trial':1,'path':'direct_vllm','client_seconds':1,'vllm_reported_seconds':0.2,'agent_overhead_seconds':'','controller_queue_seconds':'','controller_poststart_extra_seconds':'','completion_tokens':96}])
 lab=root/'results'/'scheduler-lab'/'lab_20261027T000000';emit(lab/'summary.json',{'aggregates':[{'scenario':'mixed_burst','policy':'priority_fifo','trials':3,'completed':32,'p95_wait_s':3.1,'deadline_met_pct':80,'tenant_mean_wait_gap_s':1.8,'throughput_jobs_per_s':4.5}]})
 reli=root/'results'/'reliability'/'reliability_20261027_0';emit(reli/'report.json',{'status':'passed','checks':{'queue_backpressure_observed':True,'completed_after_resume':True}})
 restart=root/'results'/'hardening'/'restart_20261027_1';emit(restart/'report.json',{'status':'passed','checks':{'recovery_record_created':True}})
 emit(root/'results'/'hardening'/'security_audit.json',{'status':'pass','checks':[{'check':'token_example','passed':True}]})
 out=root/'results'/'benchmark-atlas';subprocess.run([sys.executable,str(SCRIPT),'--project',str(root)],check=True,capture_output=True,text=True)
 m=json.loads((out/'atlas_manifest.json').read_text());assert m['real_runs']==1,m
 assert m['sanitized_real_jobs']==2,m
 assert m['telemetry_poll_rows']==1,m
 assert m['profiler_trials']==1,m
 assert m['policy_aggregate_rows']==1,m
 assert m['operational_evidence_records']==3,m
 assert m['graph_count']>=16,m
 jobidx=(out/'tables'/'jobs_index.csv').read_text();assert 'SECRET PROMPT' not in jobidx and 'PRIVATE OUTPUT' not in jobidx
 assert 'abcdef00-1234' not in jobidx
 assert (out/'index.html').exists()
 assert (out/'figures'/'10_per_job_queue.svg').exists()
 assert (out/'figures'/'20_telemetry_hbm.svg').exists()
print('PASS archive indexing: v2 jobs, HBM telemetry, profiler, scheduler lab, reliability, security, charts, secret redaction')
