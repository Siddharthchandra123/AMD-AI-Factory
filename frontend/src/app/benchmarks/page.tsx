"use client";
import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, ArrowRight, BarChart3, CheckCircle2, Clock3, Database, Download, FileArchive, Layers, RefreshCw, ShieldCheck, TriangleAlert } from "lucide-react";
import type { EvidenceRun, EvidenceSet, Diagnostic, JobTiming } from "../../lib/benchmark-loader";
import "./benchmarks.css";

const fmt = (n: number | null | undefined, digits = 2, unit = "") => n == null ? "—" : `${n.toFixed(digits)}${unit}`;
const full = (s: string | null) => s ? s.replace("T", " ").replace("Z", " UTC") : "unknown timestamp";
const safe = (n: number | null | undefined) => n == null || !Number.isFinite(n) ? 0 : n;
const compareDelta = (a: number | null, b: number | null, lowerBetter: boolean) => {
  if (a === null || b === null || a === 0) return null;
  const delta = (b - a) / Math.abs(a) * 100;
  return {delta, good: lowerBetter ? delta < 0 : delta > 0};
};

function Stat({label,value,note}:{label:string;value:string;note:string}) {
  return <div className="bench-stat"><span>{label}</span><strong>{value}</strong><small>{note}</small></div>;
}
function CompareBars({name, a, b, unit, lowerBetter=false}:{name:string;a:number|null;b:number|null;unit:string;lowerBetter?:boolean}) {
  const max = Math.max(safe(a),safe(b),0.001);
  const change = compareDelta(a,b,lowerBetter);
  return <div className="bench-compare-item">
    <div className="bench-comparison-title"><strong>{name}</strong><span className={change?.good?"bench-positive":"bench-neutral"}>{change ? `${change.delta>0?"+":""}${change.delta.toFixed(1)}%` : "not comparable"}</span></div>
    <div className="bench-bar-row"><span>A</span><div className="bench-track"><div className="bench-fill bench-fill-a" style={{width:`${(safe(a)/max)*100}%`}}/></div><b>{fmt(a,2,unit)}</b></div>
    <div className="bench-bar-row"><span>B</span><div className="bench-track"><div className="bench-fill bench-fill-b" style={{width:`${(safe(b)/max)*100}%`}}/></div><b>{fmt(b,2,unit)}</b></div>
  </div>;
}
function Trends({runs}:{runs:EvidenceRun[]}) {
  const data = runs.filter(r=>r.type!=="diagnostic" && r.queueP95 !== null).slice().reverse();
  if (data.length<2) return <p className="bench-placeholder">At least two runs with p95 queue timing are needed to plot the latency trend.</p>;
  const width=760,height=225,padX=48,padY=26;
  const yTop=Math.max(1,...data.map(r=>r.queueP95||0),...data.map(r=>r.e2eP95||0))*1.14;
  const x=(i:number)=>padX+i*(width-2*padX)/Math.max(1,data.length-1);
  const y=(v:number)=>height-padY-(v/yTop)*(height-2*padY);
  const points=(key:"queueP95"|"e2eP95")=>data.map((r,i)=>`${x(i)},${y(safe(r[key]))}`).join(" ");
  return <div className="bench-chart" role="img" aria-label="Chronological p95 queue and end-to-end latency of the recorded MI300X runs">
    <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="xMidYMid meet">
      {[0,1,2,3,4].map(i=>{const value=yTop*i/4; return <g key={i}><line x1={padX} y1={y(value)} x2={width-padX} y2={y(value)} stroke="#2a3549"/><text x={4} y={y(value)+4} fill="#8797b0" fontSize={12}>{value.toFixed(1)}s</text></g>;})}
      <polyline fill="none" stroke="#f08b78" strokeWidth={3} strokeLinejoin="round" points={points("queueP95")}/>
      <polyline fill="none" stroke="#6cc8df" strokeWidth={3} strokeLinejoin="round" points={points("e2eP95")}/>
      {data.map((r,i)=><g key={r.id}><circle cx={x(i)} cy={y(safe(r.queueP95))} r={4} fill="#f08b78"><title>{r.label} · queue p95 {fmt(r.queueP95,2,"s")}</title></circle><circle cx={x(i)} cy={y(safe(r.e2eP95))} r={4} fill="#6cc8df"><title>{r.label} · E2E p95 {fmt(r.e2eP95,2,"s")}</title></circle><text x={x(i)} y={height-4} fill="#8797b0" textAnchor="middle" fontSize={11}>{r.requested || "?"} jobs</text></g>)}
    </svg>
    <div className="bench-legend"><span><i className="bench-dot bench-coral"/> p95 queue wait</span><span><i className="bench-dot bench-teal"/> p95 end-to-end</span><span>Chronological runs (not matched trials)</span></div>
  </div>;
}
function Timeline({rows}:{rows:JobTiming[]}) {
  const eligible=rows.filter(r=>r.queue !== null && r.inference !== null);
  if(!eligible.length) return <p className="bench-placeholder">Individual job timing rows are unavailable for this run.</p>;
  const max=Math.max(1,...eligible.map(r=>safe(r.queue)+safe(r.inference)+safe(r.other)));
  return <div className="bench-timeline">
    {eligible.map((j,i)=><div className="bench-timing" key={`${j.id}-${i}`} title={`Job ${j.id} · queue ${fmt(j.queue,3," s")} · vLLM HTTP duration ${fmt(j.inference,3," s")} · other post-start ${fmt(j.other,3," s")}`}>
      <span className="bench-jobid">{j.id}</span><div className="bench-timing-track">
        <div className="bench-queue" style={{width:`${safe(j.queue)/max*100}%`}}/>
        <div className="bench-inference" style={{width:`${safe(j.inference)/max*100}%`}}/>
        <div className="bench-other" style={{width:`${safe(j.other)/max*100}%`}}/>
      </div><span className="bench-time-value">{fmt(j.endToEnd,2,"s")}</span>
    </div>)}
    <div className="bench-legend"><span><i className="bench-dot bench-coral"/> Queue</span><span><i className="bench-dot bench-teal"/> Agent-recorded vLLM request</span><span><i className="bench-dot bench-gold"/> Other post-start</span></div>
    <p className="bench-muted">The component bars are approximate recorded intervals. End-to-end timestamps can include additional overhead. They are not GPU kernel timings.</p>
  </div>;
}
function Profile({rows}:{rows:Diagnostic[]}) {
  const max=Math.max(0.001,...rows.map(r=>safe(r.median)));
  return <div className="bench-profiler">{rows.map(r=><div className="bench-profiler-row" key={r.path}>
    <div className="bench-comparison-title"><strong>{r.path.replaceAll("_"," ")}</strong><span>{fmt(r.median,3," s")} median · {fmt(r.p95,3," s")} p95 · {r.n ?? "?"} trials</span></div>
    <div className="bench-track"><div className="bench-fill bench-fill-b" style={{width:`${safe(r.median)/max*100}%`}}/></div>
  </div>)}</div>;
}

export default function BenchmarkAnalytics() {
  const [data,setData]=useState<EvidenceSet|null>(null);
  const [error,setError]=useState("");
  const [loading,setLoading]=useState(false);
  const [filter,setFilter]=useState("all");
  const [runA,setRunA]=useState("");
  const [runB,setRunB]=useState("");
  const [selected,setSelected]=useState("");
  const load=async()=>{
    setLoading(true);setError("");
    try {const response=await fetch("/api/benchmarks",{cache:"no-store"});if(!response.ok)throw new Error(`HTTP ${response.status}`);setData(await response.json());}
    catch(e){setError(String(e));}finally{setLoading(false);}
  };
  useEffect(()=>{void load();},[]);
  const runs=useMemo(()=>data?.runs||[],[data]);
  const v2=useMemo(()=>runs.filter(r=>r.type==="v2"),[runs]);
  const comparable=useMemo(()=>runs.filter(r=>r.type==="v2" && r.queueP95!==null),[runs]);
  useEffect(()=>{
    if (!comparable.length) return;
    const oldestEight=comparable.filter(r=>r.requested===8).slice().reverse();
    if(!runA || !comparable.some(r=>r.id===runA))setRunA((oldestEight[0]||comparable[comparable.length-1]).id);
    if(!runB || !comparable.some(r=>r.id===runB))setRunB((oldestEight[oldestEight.length-1]||comparable[0]).id);
  },[comparable,runA,runB]);
  useEffect(()=>{if(runs.length && (!selected || !runs.some(r=>r.id===selected)))setSelected((v2[0]||runs[0]).id);},[runs,v2,selected]);
  const a=runs.find(r=>r.id===runA), b=runs.find(r=>r.id===runB), choice=runs.find(r=>r.id===selected);
  const validMatch=Boolean(a && b && a.requested === b.requested && a.model===b.model && a.id!==b.id);
  const activeRuns=runs.filter(r=>filter==="all" || (filter==="profiling" ? r.type==="diagnostic" : r.requested===Number(filter)));
  const completionCount=v2.reduce((sum,r)=>sum+(r.completed||0),0);
  const peakThroughput=v2.reduce((peak,r)=>Math.max(peak,r.throughput||0),0);
  const profilerCount=runs.filter(r=>r.type==="diagnostic").length;
  const downloadIndex=()=>{
    const blob=new Blob([JSON.stringify(data,null,2)],{type:"application/json"});const url=URL.createObjectURL(blob);const a=document.createElement("a");a.href=url;a.download="mi300x-benchmark-index.json";a.click();URL.revokeObjectURL(url);
  };
  return <div className="bench-root"><div className="bench-container">
    <header className="bench-header"><div><a href="/" className="bench-back"><ArrowLeft size={15}/> Mission Control</a><div className="bench-eyebrow">AMD AI FACTORY / PERFORMANCE EVIDENCE</div><h1>Benchmark Analytics</h1><p>Read-only analysis of archived MI300X inference experiments. No remote GPU connection required.</p></div><div className="bench-actions"><span className="bench-offline"><ShieldCheck size={14}/> ARCHIVED EVIDENCE</span><button onClick={()=>void load()} disabled={loading}><RefreshCw size={15} className={loading?"bench-spin":""}/> Refresh</button><button onClick={downloadIndex} disabled={!data || !data.runs.length}><Download size={15}/> Export JSON</button></div></header>
    {error&&<div className="bench-error">{error}</div>}
    {data?.rootStatus!=="ok"&&<div className="bench-warning"><TriangleAlert size={18}/> <span>Benchmark results directory is {data?.rootStatus ?? "loading"}. Ensure <code>results/mi300x</code> exists locally and the frontend Docker read-only volume is installed. No GPU is needed.</span></div>}
    {!!data?.errors.length&&<div className="bench-warning"><TriangleAlert size={16}/> {data.errors.length} evidence file(s) were skipped: {data.errors.slice(0,3).join("; ")}</div>}
    <section className="bench-stats">
      <Stat label="Archived experiments" value={String(runs.length)} note={`${v2.length} enhanced benchmarks · ${profilerCount} path diagnostics`}/>
      <Stat label="Completed jobs (v2)" value={String(completionCount)} note="Sum across v2 files; may include repeated trials"/>
      <Stat label="Peak recorded throughput" value={peakThroughput?`${peakThroughput.toFixed(2)} tok/s`:"—"} note="Client-observed, not GPU-only"/>
      <Stat label="Endpoint scope" value="1 worker" note="Reported real MI300X deployment · concurrency 2"/>
    </section>
    <section className="bench-panel"><div className="bench-panel-heading"><div><h2>Recorded latency trend</h2><p>Recorded p95 values; each run may differ in workload and environmental conditions.</p></div><BarChart3 size={20}/></div><Trends runs={runs}/></section>
    <section className="bench-panel"><div className="bench-panel-heading"><div><h2>Compare matched experiments</h2><p>Select two identical job-count and model configurations for a meaningful descriptive comparison.</p></div><Layers size={20}/></div>
      <div className="bench-selects"><label>Baseline (A)<select value={runA} onChange={e=>setRunA(e.target.value)}>{comparable.map(r=><option key={r.id} value={r.id}>{r.label}</option>)}</select></label><label>Comparison (B)<select value={runB} onChange={e=>setRunB(e.target.value)}>{comparable.map(r=><option key={r.id} value={r.id}>{r.label}</option>)}</select></label></div>
      {!validMatch&&<div className="bench-note"><TriangleAlert size={17}/> Choose distinct runs with the same job count and model. Cross-workload comparisons can be misleading.</div>}
      {validMatch&&a&&b&&<><div className="bench-compare-grid"><CompareBars name="p95 queue wait" a={a.queueP95} b={b.queueP95} unit="s" lowerBetter/><CompareBars name="p95 end-to-end latency" a={a.e2eP95} b={b.e2eP95} unit="s" lowerBetter/><CompareBars name="Client output throughput" a={a.throughput} b={b.throughput} unit=" tok/s"/><CompareBars name="Client wall time" a={a.clientWall} b={b.clientWall} unit="s" lowerBetter/></div><p className="bench-muted"><CheckCircle2 size={13}/> Same workload size and model verified. Results are descriptive single-run measurements; validate performance claims across repeated controlled trials.</p></>}
    </section>
    <section className="bench-panel"><div className="bench-panel-heading"><div><h2>Experiment archive</h2><p>Discovered automatically from timestamped <code>v2_*</code> and <code>latency_diag_v06_*</code> folders.</p></div><FileArchive size={20}/></div><div className="bench-filter"><label>Filter by workload <select value={filter} onChange={e=>setFilter(e.target.value)}><option value="all">All experiments</option><option value="4">4 jobs</option><option value="8">8 jobs</option><option value="16">16 jobs</option><option value="profiling">Latency diagnostics</option></select></label></div>
      <div className="bench-table-scroll"><table><thead><tr><th>Recorded run</th><th>Completed</th><th>p95 queue</th><th>p95 E2E</th><th>Client throughput</th><th>Source</th></tr></thead><tbody>{activeRuns.map(r=><tr key={r.id} className={selected===r.id?"bench-selected-row":""} onClick={()=>setSelected(r.id)} title="Click to inspect this run"><td><strong>{r.label}</strong><small>{r.id}</small></td><td>{r.completed===null?"—":`${r.completed}/${r.requested??"?"}`}</td><td>{fmt(r.queueP95,2,"s")}</td><td>{fmt(r.e2eP95,2,"s")}</td><td>{fmt(r.throughput,2," tok/s")}</td><td>{r.type==="diagnostic"?"Path diagnostic":r.source}</td></tr>)}{!activeRuns.length&&<tr><td colSpan={6} className="bench-placeholder">No matching files found in the mounted evidence directory.</td></tr>}</tbody></table></div>
    </section>
    <section className="bench-panel"><div className="bench-panel-heading"><div><h2>Run inspection</h2><p>{choice?.label??"Select a recorded run"} · {full(choice?.timestamp||null)}</p></div><Clock3 size={20}/></div>
      {choice?.type==="diagnostic" ? <Profile rows={choice.diagnostics}/> : choice ? <><div className="bench-inspection-kpis"><Stat label="Queue p50" value={fmt(choice.queueP50,3,"s")} note="Created → dispatched"/><Stat label="Inference p50" value={fmt(choice.inferenceP50,3,"s")} note="Agent-recorded vLLM HTTP time"/><Stat label="End-to-end p95" value={fmt(choice.e2eP95,3,"s")} note="Controller lifecycle"/><Stat label="Peak sampled HBM" value={fmt(choice.hbmPeak,2," GiB")} note={`${choice.gpuPollRows??0} polling rows; snapshots only`}/></div><h3>Individual job timeline</h3><Timeline rows={choice.jobs}/></> : <p className="bench-placeholder">Select a run above to inspect individual job timings.</p>}
      {choice&&<div className="bench-provenance"><Database size={15}/><div><strong>Data provenance</strong><p>Loaded from local archived <code>summary.json</code> and, when present, <code>jobs.csv</code>. {choice.notes.join(" ")}</p></div></div>}
    </section>
    <footer className="bench-footer"><span>AMD AI Factory Mission Control · Offline Benchmark Analytics v0.7</span><span><ArrowRight size={14}/> Local evidence only · No GPU charges</span></footer>
  </div></div>;
}
