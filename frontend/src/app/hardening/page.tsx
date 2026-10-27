"use client";
import { useEffect, useState } from "react";
import { Activity, ArrowLeft, CheckCircle2, RefreshCw, ShieldCheck, ShieldAlert, Server, Database } from "lucide-react";
import "./hardening.css";

type Report = {folder:string;status:string;kind:string;start_utc?:string|null;
  requested_jobs?:number|null;peak_observed_concurrency?:number|null;checks:Record<string,boolean>};
type Reports = {available:boolean;reports:Report[];message?:string;evidence_type:string};
type Health = {mode:string;counts:Record<string,number>;nodes:{id:string;health:string;draining:boolean;active_jobs:number}[]};
type Runtime = {recovery?:{available:boolean;at_utc?:string;counts?:Record<string,number>};
  workers?:Health;security?:{write_token_enabled:boolean;note:string}};
const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
export default function Hardening() {
  const [reports,setReports]=useState<Reports|null>(null);
  const [runtime,setRuntime]=useState<Runtime|null>(null);
  const [error,setError]=useState("");
  const [busy,setBusy]=useState(false);
  const refresh=async()=>{
    setBusy(true);setError("");
    try {
      const result=await fetch("/api/hardening",{cache:"no-store"});
      if(!result.ok) throw new Error(`Evidence HTTP ${result.status}`);
      setReports(await result.json() as Reports);
      try {
        const live=await fetch(`${API}/api/hardening/status`,{cache:"no-store"});
        if(live.ok) setRuntime(await live.json() as Runtime);
        else setRuntime(null);
      } catch {setRuntime(null);}
    } catch(err) {setError(err instanceof Error?err.message:String(err));}
    finally {setBusy(false);}
  };
  useEffect(()=>{void refresh();},[]);
  const latest=reports?.reports[0];
  const checks=latest?Object.entries(latest.checks):[];
  const passed=checks.filter(([,p])=>p).length;
  return <div className="hc-root"><main className="hc-main">
    <a href="/" className="hc-back"><ArrowLeft size={15}/> Mission Control</a>
    <header className="hc-top"><div><div className="hc-kicker">PHASE 10 / OPERATIONS</div>
      <h1>Reliability &amp; Hardening</h1>
      <p>Local reliability evidence, restart reconciliation and worker health. Simulation results are not GPU fault-tolerance proof.</p></div>
      <button onClick={()=>void refresh()} disabled={busy}><RefreshCw size={16}/> Refresh</button></header>
    {error&&<div className="hc-error"><ShieldAlert size={18}/>{error}</div>}
    <div className="hc-banner"><ShieldCheck size={17}/><strong>Offline evidence</strong> — No MI300X required; tests below use simulated workers.</div>
    <div className="hc-cards">
      <div className="hc-card"><Activity size={17}/><small>Recorded reliability runs</small><strong>{reports?.reports.length??"—"}</strong></div>
      <div className="hc-card"><CheckCircle2 size={17}/><small>Latest checks passed</small><strong>{latest?`${passed}/${checks.length}`:"—"}</strong></div>
      <div className="hc-card"><Database size={17}/><small>Latest startup reconciliation</small><strong>{runtime?.recovery?.available?"Recorded":"Unavailable"}</strong></div>
      <div className="hc-card"><Server size={17}/><small>Current controller mode</small><strong>{runtime?.workers?.mode??"Offline"}</strong></div>
    </div>
    <section className="hc-panel"><h2>Reliability drill history</h2>
      {!reports?.available?<p>{reports?.message||"No reports found. Run v0.9.1 and refresh."}</p>:
      <div className="hc-scroll"><table><thead><tr><th>Evidence directory</th><th>Status</th><th>Checks</th><th>Source</th></tr></thead><tbody>
      {reports.reports.map(r=><tr key={r.folder}><td><code>{r.folder}</code></td><td>{r.status}</td>
      <td>{Object.values(r.checks).filter(Boolean).length}/{Object.keys(r.checks).length}</td><td>CPU simulation</td></tr>)}
      </tbody></table></div>}
      {latest&&<div className="hc-checks">{checks.map(([name,success])=><div key={name} className="hc-check"><span>{success?<CheckCircle2 size={15}/>:<ShieldAlert size={15}/>} {name.replaceAll("_"," ")}</span><b>{success?"PASS":"FAIL"}</b></div>)}</div>}
    </section>
    <section className="hc-panel"><h2>Controller restart reconciliation</h2>
      {runtime?.recovery?.available?<><p>Last startup: {runtime.recovery.at_utc}</p><div className="hc-scroll"><table><tbody>
      {Object.entries(runtime.recovery.counts||{}).map(([name,n])=><tr key={name}><td>{name.replaceAll("_"," ")}</td><td>{n}</td></tr>)}
      </tbody></table></div></>:<p>No startup reconciliation record available from the running backend. Rebuild it with Phase 10 installed and refresh.</p>}
      <p className="hc-note">Interrupted real inference is marked failed with outcome unknown and never automatically reissued. Only simulated in-flight jobs are requeued.</p>
    </section>
    <section className="hc-panel"><h2>Worker health &amp; readiness</h2>
      {runtime?.workers?<div className="hc-scroll"><table><thead><tr><th>Endpoint</th><th>Health</th><th>Drain</th><th>Active</th></tr></thead><tbody>
      {runtime.workers.nodes.map(n=><tr key={n.id}><td>{n.id}</td><td>{n.health}</td><td>{n.draining?"Yes":"No"}</td><td>{n.active_jobs}</td></tr>)}
      </tbody></table></div>:<p>Backend unavailable or Phase 10 status API is not installed.</p>}
      <p className="hc-note">Stale workers are excluded from new real placements. This dashboard does not trigger retries or job cancellation.</p>
    </section>
    <section className="hc-panel"><h2>Security posture</h2>
      <p>Optional write-token gate: <b>{runtime?.security?.write_token_enabled?"Enabled":"Not enabled / not reported"}</b></p>
      <p className="hc-note">Keep backend, Grafana, Redis, PostgreSQL and this dashboard private. Optional API token mode requires authenticated clients and can break existing frontend write controls until integrated.</p>
    </section>
    <footer>AMD AI Factory Mission Control · Phase 10 unified hardening · Read-only monitoring interface</footer>
  </main></div>;
}
