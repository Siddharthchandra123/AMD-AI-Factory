"use client";
import {useCallback, useEffect, useMemo, useState} from "react";
import {Activity, AlertCircle, AlertTriangle, ArrowRight, BarChart3, CheckCircle2, Cpu, Database, Gauge, Layers, Play, Plus, RefreshCw, Server, Settings2, ShieldAlert, Terminal, Trash2, Zap} from "lucide-react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
type NodeData = {id:string;model:string;source:string;memory_total_gb:number|null;memory_used_gb:number|null;utilization_percent:number|null;temperature_c:number|null;power_watts:number|null;active_jobs:number;max_concurrent_jobs?:number;health:string;ready?:boolean;draining?:boolean;gpu_ids?:string[];models?:string[];last_seen_seconds?:number;agent_id?:string};
type Cluster = {mode:string;source_notice:string;policy:string;queue_policy:string;nodes:NodeData[];summary:{node_count:number;avg_utilization_percent:number|null;running_jobs:number;queued_jobs:number;completed_jobs:number}};
type Job = {id:string;model:string;execution_mode:string;priority:string;status:string;gpu_id:string|null;created_at:string;queue_wait_seconds:number|null;duration_seconds:number|null;completion_tokens_actual:number|null;error_message:string|null;response_text:string|null};
type Catalog = {placement:{id:string;description:string}[];queue:{id:string;description:string}[]};
type Runtime = {mode:string;configured_agent_urls:string[];connected_workers:number;advertised_models:string[];agent_errors:Record<string,string>};
type Alert = {level:string;node:string;message:string};
type State = {cluster:Cluster;jobs:Job[];runtime:Runtime;alerts:{alerts:Alert[];total:number};models:{id:string;source:string;memory_gb:number|null}[];loadtest?:{active:boolean;simulation_only:boolean}};
const formatTime=(s:string)=>new Date(s).toLocaleTimeString();
const fmt=(n:number|null|undefined, digits=1, suffix="")=>n==null ? "n/a" : `${n.toFixed(digits)}${suffix}`;
function Stat({title,value,caption,icon:Icon}:{title:string;value:string|number;caption:string;icon:typeof Activity}){
  return <div className="metric"><div className="metric-heading"><span>{title}</span><Icon size={17}/></div><div className="metric-value">{value}</div><div className="metric-hint">{caption}</div></div>;
}
function MiniTrend({points}:{points:number[]}){
  if(points.length<2)return <span className="muted">Collecting live samples...</span>;
  const coords=points.map((n,i)=>`${(i/(Math.max(points.length-1,1))*600).toFixed(1)},${(100-Math.max(0,Math.min(100,n))).toFixed(1)}`).join(" ");
  return <svg viewBox="0 0 600 100" preserveAspectRatio="none" className="mini-trend" role="img" aria-label="Average GPU utilization over recent samples"><line x1="0" y1="50" x2="600" y2="50" stroke="currentColor" opacity=".1"/><polyline points={coords} fill="none" stroke="#e55d5d" strokeWidth="2.5" vectorEffect="non-scaling-stroke" strokeLinejoin="round"/></svg>;
}

export default function Home(){
  const [state,setState]=useState<State|null>(null);
  const [catalog,setCatalog]=useState<Catalog>({placement:[],queue:[]});
  const [error,setError]=useState("");
  const [busy,setBusy]=useState(false);
  const [connected,setConnected]=useState(false);
  const [lastUpdated,setLastUpdated]=useState("");
  const [history,setHistory]=useState<number[]>([]);
  const [model,setModel]=useState("model-7b");
  const [priority,setPriority]=useState("normal");
  const [batchSize,setBatchSize]=useState(8);
  const [prompt,setPrompt]=useState("Explain how GPU scheduling improves inference performance.");
  const [outputTokens,setOutputTokens]=useState(128);
  const [tenant,setTenant]=useState("default");
  const [deadline,setDeadline]=useState("");
  const [newSimMemory,setNewSimMemory]=useState(192);
  const [newSimConcurrency,setNewSimConcurrency]=useState(2);
  const [newSimModel,setNewSimModel]=useState("model-custom");
  const [newSimModelGb,setNewSimModelGb]=useState(24);
  const [loadRps,setLoadRps]=useState(1);
  const [loadDuration,setLoadDuration]=useState(30);
    const cluster=state?.cluster;
  const runtime=state?.runtime;
  const nodes=cluster?.nodes||[];
  const jobs=state?.jobs||[];
  const models=state?.models||[];

  const refresh=useCallback(async()=>{
    const [cr,jr,rr,ar,mr,lr]=await Promise.all([
      fetch(`${API}/api/cluster`,{cache:"no-store"}),fetch(`${API}/api/jobs?limit=30`,{cache:"no-store"}),
      fetch(`${API}/api/runtime`,{cache:"no-store"}),fetch(`${API}/api/alerts`,{cache:"no-store"}),
      fetch(`${API}/api/models`,{cache:"no-store"}),fetch(`${API}/api/loadtest`,{cache:"no-store"})]);
    if([cr,jr,rr,ar,mr,lr].some(r=>!r.ok))throw Error("Failed to fetch runtime state");
    const [c,j,r,a,m,l]=await Promise.all([cr.json(),jr.json(),rr.json(),ar.json(),mr.json(),lr.json()]);
    setState({cluster:c,jobs:j.jobs,runtime:r,alerts:a,models:m.models,loadtest:l});setConnected(true);setLastUpdated(new Date().toLocaleTimeString());
    if(c.summary.avg_utilization_percent!=null)setHistory(h=>[...h,c.summary.avg_utilization_percent].slice(-60));
  },[]);

  useEffect(()=>{
    fetch(`${API}/api/policies`).then(r=>r.json()).then(setCatalog).catch(()=>{});
    refresh().catch(e=>setError(String(e)));
    const stream=new EventSource(`${API}/api/events/stream`);
    stream.addEventListener("state",evt=>{
      const next=JSON.parse((evt as MessageEvent).data) as {cluster:Cluster;jobs:Job[];runtime:Runtime;alerts:{alerts:Alert[];total:number};models:State["models"];loadtest?:State["loadtest"]};
      setState(next);setConnected(true);setError("");setLastUpdated(new Date().toLocaleTimeString());
      if(next.cluster.summary.avg_utilization_percent!=null)setHistory(h=>[...h,next.cluster.summary.avg_utilization_percent!].slice(-60));
    });
    stream.onerror=()=>setConnected(false);
    // Fallback refresh if SSE stops; no WSL/host-specific dependencies.
    const poll=setInterval(()=>{if(stream.readyState!==EventSource.OPEN)refresh().catch(()=>{});},5000);
    return()=>{stream.close();clearInterval(poll);};
  },[refresh]);

  useEffect(()=>{if(models.length && !models.some(m=>m.id===model))setModel(models[0].id);},[models,model]);

  const send=async(path:string,method:"POST"|"PUT"|"DELETE",payload?:unknown)=>{
    setBusy(true);setError("");
    try{
      const response=await fetch(`${API}${path}`,{method,headers:payload?{"Content-Type":"application/json"}:{},body:payload?JSON.stringify(payload):undefined});
      if(!response.ok){const data=await response.json().catch(()=>null);throw Error(data?.detail||`${response.status} ${response.statusText}`);}
      await refresh();
    }catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setBusy(false);}
  };
  const submit=()=>send("/api/jobs/batch","POST",{model,prompt,priority,tenant,prompt_tokens:512,output_tokens:outputTokens,
    count:batchSize,deadline_seconds:deadline?Number(deadline):null});
  const real=cluster?.mode==="mi300x";
  const activeFailures=jobs.filter(j=>j.status==="failed").length;
  const completed=jobs.filter(j=>j.status==="completed");
  const throughput=useMemo(()=>{
    const samples=completed.filter(j=>j.execution_mode==="mi300x"&&j.completion_tokens_actual!=null&&j.duration_seconds);
    return samples.length ? (samples.reduce((s,j)=>s+(j.completion_tokens_actual||0),0)/samples.reduce((s,j)=>s+(j.duration_seconds||0),0)).toFixed(1) : "—";
  },[jobs]);
  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark"><Cpu size={22}/></div><div><strong>AMD AI FACTORY</strong><small>MISSION CONTROL</small></div></div>
      <div className="section-label">CONTROL PLANE / v0.3</div>
      <nav className="nav">
        <a href="#overview" className="active"><Gauge size={18}/> Overview</a>
        <a href="#gpu-nodes"><Server size={18}/> Live GPU fleet</a>
        <a href="#job-queue"><Layers size={18}/> Workload queue</a>
        <a href="#runtime"><Settings2 size={18}/> Runtime & topology</a>
        <a href="/benchmarks"><BarChart3 size={18}/> Benchmark Analytics <ArrowRight size={13}/></a>
        <a href="/scheduler-lab"><Layers size={18}/> Scheduler Lab <ArrowRight size={13}/></a>
        <a href="http://localhost:3001" target="_blank" rel="noreferrer"><BarChart3 size={18}/> Grafana <ArrowRight size={13}/></a>
        <a href="http://localhost:9090" target="_blank" rel="noreferrer"><Activity size={18}/> Prometheus <ArrowRight size={13}/></a>
      </nav>
      <div className="sidebar-bottom"><span className="status-pulse"/>{connected?" Live telemetry connected":" Reconnecting to backend"}<p>{real?"Remote MI300X / ROCm":"Local CPU / Virtual GPUs"}</p></div>
    </aside>
    <main className="main" id="overview">
      <header className="header"><div><div className="eyebrow">INFRASTRUCTURE / DYNAMIC CONTROL PLANE</div><h1>GPU Mission Control</h1><p>Dynamic discovery, inference routing, policy scheduling and live telemetry</p></div>
        <div className="header-meta"><span className={`sim-pill ${real?"real-pill":""}`}><span className="pulse-dot"/> {real?"REAL AMD SMI / vLLM":"SIMULATION MODE"}</span>
          <button className="icon-btn" title="Refresh now" onClick={()=>refresh().catch(e=>setError(String(e)))}><RefreshCw size={17}/></button></div>
      </header>
      {error&&<div className="error"><AlertCircle size={17}/><span>{error}</span></div>}
      <div className={`notice ${real?"live-notice":""}`}><ShieldAlert size={18}/><div><strong>{real?"Real AMD GPU mode is enabled.":"CPU-only simulation active."}</strong> {cluster?.source_notice||"Waiting for backend..."}</div></div>
      <section className="metric-grid">
        <Stat title="Discovered endpoints" value={nodes.length} caption={real?"Live serving pools, not GPU count":"Virtual scheduling nodes"} icon={Server}/>
        <Stat title="Average utilization" value={fmt(cluster?.summary.avg_utilization_percent,1,"%") } caption={real?"AMD SMI measurements":"Synthetic GPU activity"} icon={Gauge}/>
        <Stat title="Running / waiting" value={`${cluster?.summary.running_jobs??0} / ${cluster?.summary.queued_jobs??0}`} caption="Actual job queue state" icon={Layers}/>
        <Stat title="Jobs completed" value={cluster?.summary.completed_jobs??0} caption={real?`${throughput} completed tokens/s (aggregate)`:`${activeFailures} recent failed`} icon={Zap}/>
      </section>
      <section className="panel"><div className="panel-heading"><div><h2>Live fleet activity</h2><p>Last 60 samples · {real?"physical GPU telemetry":"synthetic workload simulator"}</p></div><span className="timestamp">{connected?"SSE live":"Polling fallback"} · {lastUpdated}</span></div><MiniTrend points={history}/></section>
      <section className="panel" id="gpu-nodes"><div className="panel-heading"><div><h2>Discovered inference endpoints</h2><p>Automatically follows topology changes; multi-GPU vLLM instances appear as one worker</p></div><span className="timestamp">{nodes.length} endpoints</span></div>
        <div className="node-grid">{nodes.map(node=><div className="node-card" key={node.id}>
          <div className="node-top"><div className="node-icon"><Cpu size={20}/></div><div className="node-title"><strong>{node.id}</strong><small>{node.model} · {node.source}</small></div><span className={`health ${node.health==="healthy"?"":"warning"}`}>{node.health}</span></div>
          {node.gpu_ids&&<div className="muted">GPU IDs: {node.gpu_ids.join(", ")} {node.agent_id?`· ${node.agent_id}`:""}</div>}
          <div className="bar-label"><span>Utilization</span><strong>{fmt(node.utilization_percent,1,"%")}</strong></div><div className="bar"><div className={node.utilization_percent!=null&&node.utilization_percent>90?"bar-fill hot":"bar-fill"} style={{width:`${node.utilization_percent||0}%`}}/></div>
          <div className="bar-label"><span>VRAM / HBM</span><strong>{fmt(node.memory_used_gb)} / {fmt(node.memory_total_gb)} GiB</strong></div><div className="bar memory"><div className="bar-fill memory-fill" style={{width:node.memory_used_gb!=null&&node.memory_total_gb?`${100*node.memory_used_gb/node.memory_total_gb}%`:"0%"}}/></div>
          <div className="node-footer"><span><Activity size={13}/>{fmt(node.temperature_c,0,"°C")}</span><span><Zap size={13}/>{fmt(node.power_watts,0,"W")}</span><span><Layers size={13}/>{node.active_jobs}/{node.max_concurrent_jobs||2} jobs</span></div>
          <div className="node-controls"><button disabled={busy} onClick={()=>send(`/api/nodes/${encodeURIComponent(node.id)}/drain`,"PUT",{draining:!node.draining})}>{node.draining?"Resume dispatch":"Drain endpoint"}</button>{!real&&<button disabled={busy||node.active_jobs>0||nodes.length===1} title="Remove idle simulated endpoint" onClick={()=>send(`/api/simulator/nodes/${encodeURIComponent(node.id)}`,"DELETE")}><Trash2 size={14}/> Remove</button>}</div>
        </div>)}{nodes.length===0&&<div className="empty">No endpoints detected. In real mode, check the remote agent configuration and diagnostics below.</div>}</div>
      </section>
      <section className="two-column">
        <div className="panel"><div className="panel-heading"><div><h2>Workload generator</h2><p>{real?"Dispatch real prompts to ROCm vLLM":"Simulate inference dispatch and model load"}</p></div><Play size={18}/></div>
          <div className="form-grid"><label>Served model<select value={model} onChange={e=>setModel(e.target.value)}>{models.map(m=><option key={m.id} value={m.id}>{m.id}{m.memory_gb?` · ${m.memory_gb} GiB profile`:""}</option>)}</select></label>
          <label>Priority<select value={priority} onChange={e=>setPriority(e.target.value)}><option value="high">High</option><option value="normal">Normal</option><option value="low">Low</option></select></label>
          <label>Job batch<select value={batchSize} onChange={e=>setBatchSize(Number(e.target.value))}>{[1,4,8,16,32].map(n=><option key={n} value={n}>{n} jobs</option>)}</select></label>
          <label>Output tokens<input type="number" min="1" max="8192" value={outputTokens} onChange={e=>setOutputTokens(Number(e.target.value))}/></label>
          <label>Tenant<input value={tenant} maxLength={64} onChange={e=>setTenant(e.target.value)}/></label>
          <label>Deadline (optional)<input type="number" min="1" placeholder="seconds" value={deadline} onChange={e=>setDeadline(e.target.value)}/></label>
          <label className="wide-field">Real inference prompt<textarea rows={3} maxLength={8192} value={prompt} onChange={e=>setPrompt(e.target.value)}/><small>Used only for actual vLLM inference; simulated jobs use token-count profiles.</small></label>
          <button className="primary wide-field" onClick={submit} disabled={busy||!models.length}><Play size={15}/>{busy?"Working...":real?"Run on AMD MI300X":"Submit simulated workload"}</button></div>
        </div>
        <div className="panel"><div className="panel-heading"><div><h2>Scheduling policies</h2><p>Change strategies live without restarting containers</p></div><Settings2 size={18}/></div>
          <div className="policy-select-grid"><label>Endpoint placement ({catalog.placement.length})<select value={cluster?.policy||"round_robin"} disabled={busy} onChange={e=>send("/api/policy","PUT",{policy:e.target.value})}>{catalog.placement.map(p=><option value={p.id} key={p.id}>{p.id.replaceAll("_"," ")}</option>)}</select><small>{catalog.placement.find(p=>p.id===cluster?.policy)?.description}</small></label>
          <label>Queue ordering ({catalog.queue.length})<select value={cluster?.queue_policy||"priority_fifo"} disabled={busy} onChange={e=>send("/api/queue-policy","PUT",{policy:e.target.value})}>{catalog.queue.map(p=><option value={p.id} key={p.id}>{p.id.replaceAll("_"," ")}</option>)}</select><small>{catalog.queue.find(p=>p.id===cluster?.queue_policy)?.description}</small></label></div>
          <p className="small-note">Auto mode dynamically selects placement from queue pressure and utilization spread. All policies are non-preemptive; topology and model availability constrain scheduling.</p>
          <h3 className="subsection-title"><AlertTriangle size={16}/> Live alerts ({state?.alerts.total||0})</h3>
          <div className="alert-feed">{state?.alerts.alerts.map((a,i)=><div className="alert-line" key={a.node+i}><AlertCircle size={15}/><strong>{a.node}</strong> {a.message}</div>)}{!state?.alerts.total&&<div className="muted"><CheckCircle2 size={15}/> No active alert thresholds exceeded</div>}</div>
        </div>
      </section>
      <section className="panel" id="runtime"><div className="panel-heading"><div><h2>Execution runtime & topology</h2><p>Change execution mode only when the queue is idle; real mode requires authenticated MI300X discovery</p></div><Server size={18}/></div>
        <div className="runtime-grid"><div><strong>Current runtime</strong><p>{real?"MI300X · AMD SMI · vLLM":"Local CPU · Synthetic MI300X"}</p><div className="node-controls"><button disabled={busy||!real} onClick={()=>send("/api/runtime","PUT",{mode:"simulation"})}>Use simulator</button><button disabled={busy||real||!runtime?.connected_workers} onClick={()=>send("/api/runtime","PUT",{mode:"mi300x"})}>Connect real MI300X</button></div></div>
        <div><strong>Remote agent connectivity</strong><p>{runtime?.connected_workers||0} ready serving endpoints · {runtime?.configured_agent_urls.length||0} agent URLs configured</p>{Object.entries(runtime?.agent_errors||{}).map(([url,message])=><div className="agent-error" key={url}>{url}: {message}</div>)}{!runtime?.configured_agent_urls.length&&<small className="muted">Set MI300X_AGENT_URLS and MISSION_AGENT_TOKEN in your local .env, then restart backend.</small>}</div></div>
        {!real&&<div className="sim-actions"><strong>Dynamic simulator topology</strong><label>GPU HBM GiB<input type="number" value={newSimMemory} min={8} max={512} onChange={e=>setNewSimMemory(Number(e.target.value))}/></label><label>Concurrent jobs / GPU<input type="number" min={1} max={32} value={newSimConcurrency} onChange={e=>setNewSimConcurrency(Number(e.target.value))}/></label><button disabled={busy} onClick={()=>send("/api/simulator/nodes","POST",{memory_total_gb:newSimMemory,max_concurrent_jobs:newSimConcurrency})}><Plus size={15}/> Add virtual GPU</button></div>}
      {!real&&<div className="sim-actions"><strong>Dynamic simulated models</strong><label>Model ID<input type="text" value={newSimModel} onChange={e=>setNewSimModel(e.target.value)}/></label><label>Estimated memory GiB<input type="number" value={newSimModelGb} min={0.1} max={400} onChange={e=>setNewSimModelGb(Number(e.target.value))}/></label><button disabled={busy} onClick={()=>send("/api/models/sim","POST",{id:newSimModel,memory_gb:newSimModelGb})}><Plus size={15}/> Register profile</button></div>}
      {!real&&<div className="sim-actions"><strong>Live synthetic load test</strong><label>Requests / second<input type="number" min={0.2} max={5} step={0.2} value={loadRps} onChange={e=>setLoadRps(Number(e.target.value))}/></label><label>Duration seconds<input type="number" min={1} max={120} value={loadDuration} onChange={e=>setLoadDuration(Number(e.target.value))}/></label>{state?.loadtest?.active?<button disabled={busy} onClick={()=>send("/api/loadtest/stop","POST")}><ShieldAlert size={15}/> Stop load generator</button>:<button disabled={busy||!models.length} onClick={()=>send("/api/loadtest/start","POST",{model,requests_per_second:loadRps,duration_seconds:loadDuration,batch_size:1})}><Play size={15}/> Start synthetic load</button>}<span className="muted">Never sends automatic loads to real MI300X</span></div>}
      </section>
      <section className="panel" id="job-queue"><div className="panel-heading"><div><h2>Job execution history</h2><p>Persisted in PostgreSQL · never mark real inference as simulated success</p></div><a className="export-btn" href={`${API}/api/jobs/export`}><Database size={15}/> Export CSV</a></div>
        <div className="table-wrap"><table><thead><tr><th>JOB</th><th>MODE</th><th>MODEL</th><th>WORKER</th><th>STATUS</th><th>RUNTIME</th><th>TOKENS</th><th>CREATED</th></tr></thead><tbody>{jobs.map(j=><tr key={j.id}><td className="mono" title={j.id}>{j.id.slice(0,8)}</td><td>{j.execution_mode}</td><td className="job-model" title={j.model}>{j.model}</td><td className="mono" title={j.gpu_id||""}>{j.gpu_id||"—"}</td><td title={j.error_message||j.response_text||""}><span className={`job-status ${j.status}`}>{j.status}</span></td><td>{fmt(j.duration_seconds,2,"s")}</td><td>{j.completion_tokens_actual??"—"}</td><td>{formatTime(j.created_at)}</td></tr>)}{!jobs.length&&<tr><td colSpan={8} className="empty">No jobs yet. Use the workload generator to submit your first request.</td></tr>}</tbody></table></div>
      </section>
      <footer><span><Terminal size={14}/> AMD AI Factory Mission Control v0.3</span><span>PowerShell + Docker Desktop · Agent connectivity via SSH tunnel · Data provenance enforced</span></footer>
    </main>
  </div>;
}
