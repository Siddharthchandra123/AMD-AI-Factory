"use client";

import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, ArrowRight, BarChart3, CheckCircle2, Cpu, Database, FileJson2, RefreshCw, ShieldAlert, SlidersHorizontal } from "lucide-react";
import "./scheduler-lab.css";

type Metric = "p95_wait_s"|"mean_wait_s"|"p95_turnaround_s"|"deadline_met_pct"|"tenant_mean_wait_gap_s"|"throughput_jobs_per_s";
type Summary = {scenario:string; policy:string; trials:number; completed:number; deadline_jobs:number;
  p95_wait_s:number; p95_wait_s_sd:number; mean_wait_s:number; p95_turnaround_s:number;
  p95_turnaround_s_sd:number; deadline_met_pct:number|null; deadline_met_pct_sd:number|null;
  tenant_mean_wait_gap_s:number; throughput_jobs_per_s:number; starvation_proxy_count:number;
  high_priority_p95_wait_s:number|null};
type Job = {job_id:string; priority:string;tenant:string;arrival_s:number;started_s:number;completed_s:number;queue_wait_s:number;service_s:number;deadline_met:boolean|null};
type Result = {available:boolean;folder?:string; message?:string; setup?:string;
  manifest?: {kind:string;timestamp_utc:string;seed:number;synthetic_slots:number;trials_per_scenario_policy:number;jobs_per_scenario_trial:number;
    scheduler_sha256:string;starvation_proxy_threshold_s:number;scenarios:Record<string,string>;notes:string[]};
  policies?:Record<string,string>; aggregates?:Summary[]; sample_jobs?:Record<string,Job[]>};

const metricOptions:{id:Metric;name:string;unit:string;lowerBetter:boolean}[] = [
  {id:"p95_wait_s",name:"p95 queue wait",unit:"s",lowerBetter:true},
  {id:"mean_wait_s",name:"Mean queue wait",unit:"s",lowerBetter:true},
  {id:"p95_turnaround_s",name:"p95 end-to-end",unit:"s",lowerBetter:true},
  {id:"deadline_met_pct",name:"Deadline success",unit:"%",lowerBetter:false},
  {id:"tenant_mean_wait_gap_s",name:"Tenant mean-wait gap",unit:"s",lowerBetter:true},
  {id:"throughput_jobs_per_s",name:"Job throughput",unit:" jobs/s",lowerBetter:false},
];
function fmt(v:number|null|undefined, n=2, suffix="") {return v==null || !Number.isFinite(v) ? "â€”" : v.toFixed(n)+suffix;}
function readable(id:string) {return id.replaceAll("_"," ");}
function MetricCard({label,value,subtitle}:{label:string;value:string;subtitle:string}) {
  return <div className="sl-card"><small>{label}</small><strong>{value}</strong><span>{subtitle}</span></div>;
}

export default function SchedulerLabPage() {
  const [data,setData] = useState<Result|null>(null);
  const [busy,setBusy] = useState(false);
  const [scenario,setScenario] = useState("mixed_burst");
  const [metric,setMetric] = useState<Metric>("p95_wait_s");
  const [selected,setSelected] = useState("fcfs");
  const [issue,setIssue] = useState("");
  const reload = async() => {
    setBusy(true);setIssue("");
    try {
      const response = await fetch("/api/scheduler-lab",{cache:"no-store"});
      if(!response.ok)throw Error(`HTTP ${response.status}`);
      const next = await response.json() as Result;
      setData(next);
      if(next.manifest && !next.manifest.scenarios[scenario])setScenario(Object.keys(next.manifest.scenarios)[0]||"mixed_burst");
    } catch(e) {setIssue(e instanceof Error?e.message:String(e));}
    finally {setBusy(false);}
  };
  useEffect(()=>{void reload();},[]); // only on mount
  const metricInfo=metricOptions.find(m=>m.id===metric)!;
  const selectedRows=useMemo(()=>{
    const rows = (data?.aggregates||[]).filter(row=>row.scenario===scenario && row[metric]!=null);
    return [...rows].sort((a,b)=>metricInfo.lowerBetter ? (a[metric]??0)-(b[metric]??0) : (b[metric]??0)-(a[metric]??0));
  },[data,scenario,metric,metricInfo.lowerBetter]);
  const baseline = (data?.aggregates||[]).find(r=>r.scenario===scenario&&r.policy==="fcfs");
  const reference = (data?.aggregates||[]).find(r=>r.scenario===scenario&&r.policy===selected);
  const sample = data?.sample_jobs?.[`${scenario}:${selected}`]||[];
  const maxMetric=Math.max(1, ...selectedRows.map(r=>r[metric]??0));
  const start=Math.min(...sample.map(j=>j.arrival_s),0);
  const end=Math.max(1,...sample.map(j=>j.completed_s));
  const safeSpan=Math.max(1e-4,end-start);

  return <div className="sl-root"><main className="sl-layout">
    <a className="sl-back" href="/"><ArrowLeft size={15}/> Back to Mission Control</a>
    <div className="sl-heading"><div><div className="sl-kicker">OFFLINE EXPERIMENTS / PHASE 8</div>
      <h1>Scheduling Policy Lab</h1>
      <p>Compare the actual Mission Control queue-ranking policies using reproducible, synthetic, CPU-only workloads.</p></div>
      <button className="sl-reload" onClick={()=>void reload()} disabled={busy}><RefreshCw size={15} className={busy?"sl-spin":""}/> Refresh evidence</button>
    </div>
    <div className="sl-banner"><Cpu size={17}/><strong>Simulation evidence only</strong><span>No MI300X hardware, GPU telemetry or real inference timing is used in this lab.</span></div>
    {issue && <div className="sl-alert"><ShieldAlert size={17}/>{issue}</div>}
    {!data?.available ? <section className="sl-panel"><h2>No scheduling experiments found</h2><p>Run the Python evaluator from your project root and refresh this page. The evaluator imports your existing <code>backend/app/scheduler.py</code> directly.</p><pre>python .\scripts\evaluate_queue_policies_v0_8.py --trials 3 --jobs 32 --slots 2</pre><p className="sl-muted">{data?.message||"No results loaded yet."}</p></section> : <>
      <section className="sl-cards">
        <MetricCard label="Policies evaluated" value={String(Object.keys(data.policies||{}).length)} subtitle="Actual rank_queue() implementation"/>
        <MetricCard label="Scenario families" value={String(Object.keys(data.manifest?.scenarios||{}).length)} subtitle="Matched workload traces"/>
        <MetricCard label="Repetitions per policy" value={String(data.manifest!.trials_per_scenario_policy)} subtitle="Common seeds across policies"/>
        <MetricCard label="Synthetic worker slots" value={String(data.manifest!.synthetic_slots)} subtitle="Not physical GPU workers"/>
      </section>
      <section className="sl-panel"><div className="sl-panel-head"><div><h2>Policy performance</h2><p>Select a workload and metric. Bar lengths are proportional to the selected value, not scores.</p></div><SlidersHorizontal size={20}/></div>
        <div className="sl-controls"><label>Workload scenario<select value={scenario} onChange={e=>{setScenario(e.target.value);if(e.target.value!=="deadline_pressure" && metric==="deadline_met_pct")setMetric("p95_wait_s");}}>{Object.entries(data.manifest!.scenarios).map(([key])=><option key={key} value={key}>{readable(key)}</option>)}</select></label>
        <label>Evaluation metric<select value={metric} onChange={e=>setMetric(e.target.value as Metric)}>{metricOptions.filter(m=>m.id!=="deadline_met_pct"||scenario==="deadline_pressure").map(m=><option key={m.id} value={m.id}>{m.name}</option>)}</select></label></div>
        <p className="sl-description">{data.manifest!.scenarios[scenario]} {metricInfo.lowerBetter?"Lower values indicate better performance for this metric.":"Higher values indicate better performance for this metric."}</p>
        <div className="sl-bars">{selectedRows.map((row,i)=><button key={row.policy} className={`sl-bar-row ${selected===row.policy?"sl-active":""}`} onClick={()=>setSelected(row.policy)} aria-label={`Inspect ${row.policy}`}>
          <span className="sl-bar-name">{i===0&&<CheckCircle2 size={13}/>} {readable(row.policy)}</span><div className="sl-track"><div className="sl-fill" style={{width:`${Math.max(0,(row[metric]??0)/maxMetric*100)}%`}}/></div><strong>{fmt(row[metric],metric==="deadline_met_pct"?1:2,metricInfo.unit)}</strong></button>)}</div>
        <p className="sl-muted">Top-ranked means best on <em>this scenario and metric only</em>. Changes in workload, service-time estimates, or capacity can change the ranking.</p>
      </section>
      <section className="sl-panel"><div className="sl-panel-head"><div><h2>Compare with FCFS</h2><p>Same arrivals, service times and deadlines for each policy within a trial.</p></div><BarChart3 size={19}/></div>
        <div className="sl-controls"><label>Selected policy<select value={selected} onChange={e=>setSelected(e.target.value)}>{Object.keys(data.policies||{}).map(p=><option key={p} value={p}>{readable(p)}</option>)}</select></label></div>
        <div className="sl-table-wrap"><table><thead><tr><th>Metric</th><th>FCFS baseline</th><th>{readable(selected)}</th><th>Difference</th></tr></thead><tbody>{metricOptions.filter(m=>m.id!=="deadline_met_pct"||scenario==="deadline_pressure").map(m=>{
          const a=baseline?.[m.id]??null,b=reference?.[m.id]??null;
          const delta=a!==null&&b!==null&&a!==0?(b-a)/Math.abs(a)*100:null;
          return <tr key={m.id}><td>{m.name}</td><td>{fmt(a,2,m.unit)}</td><td>{fmt(b,2,m.unit)}</td><td className={delta!==null&&(m.lowerBetter?delta<0:delta>0)?"sl-good":""}>{delta===null?"â€”":`${delta>0?"+":""}${delta.toFixed(1)}%`}</td></tr>;
        })}</tbody></table></div>
        <p className="sl-muted">The tenant mean-wait gap is a limited fairness indicator, not a guarantee of equitable scheduling. Throughput is synthetic completed jobs / simulation makespan.</p>
      </section>
      <section className="sl-panel"><div className="sl-panel-head"><div><h2>Per-job synthetic timeline</h2><p>First trial, selected policy. Colored segments show queue waiting and service time.</p></div><Database size={18}/></div>
      <div className="sl-timeline">{[...sample].sort((a,b)=>a.started_s-b.started_s).map(j=><div className="sl-timeline-row" key={j.job_id}><span className="sl-job-label">{j.job_id}</span><div className="sl-timebar">
        <span className="sl-offset" style={{width:`${Math.max(0,(j.arrival_s-start)/safeSpan*100)}%`}}/>
        <span className="sl-queued" style={{width:`${Math.max(0,j.queue_wait_s/safeSpan*100)}%`}}/>
        <span className="sl-served" style={{width:`${Math.max(.18,j.service_s/safeSpan*100)}%`}}/>
      </div><span className="sl-timevalue">{fmt(j.queue_wait_s,2,"s")}</span></div>)}</div>
      <div className="sl-legend"><span><i className="sl-queued"/> Queue wait</span><span><i className="sl-served"/> Synthetic service</span></div>
      </section>
      <section className="sl-panel"><h2>Reproducibility and evidence</h2>
        <div className="sl-evidence"><FileJson2 size={22}/><div><strong>{data.folder}</strong><p>Source SHA-256: <code>{data.manifest!.scheduler_sha256}</code></p><p>Seed: {data.manifest!.seed} Â· {data.manifest!.jobs_per_scenario_trial} jobs/scenario/trial Â· {data.manifest!.trials_per_scenario_policy} trials Â· {data.manifest!.synthetic_slots} slots</p></div></div>
        <div className="sl-table-wrap"><table><thead><tr><th>Important assumptions</th></tr></thead><tbody>{data.manifest!.notes.map((n,i)=><tr key={i}><td>{n}</td></tr>)}</tbody></table></div>
        <p className="sl-muted">CSV files in <code>results/scheduler-lab/{data.folder}</code>: <code>jobs.csv</code>, <code>runs.csv</code>, <code>summary.csv</code>. The benchmark archive under <code>results/mi300x</code> is not modified.</p>
      </section>
    </>}
    <footer className="sl-footer">AMD AI Factory Mission Control / Scheduler Lab v0.8 <span><ArrowRight size={13}/> CPU-only evidence</span></footer>
  </main></div>;
}

