#!/usr/bin/env python3
"""Read-only worker health observation; GPU-free and non-disruptive."""
import argparse,json,time,urllib.request
from pathlib import Path
from datetime import datetime,timezone

def main():
 p=argparse.ArgumentParser();p.add_argument('--seconds',type=int,default=30);p.add_argument('--interval',type=float,default=2.0);args=p.parse_args()
 if not 1<=args.seconds<=1800 or args.interval<.25: raise SystemExit('Invalid watch duration/interval')
 history=[];end=time.monotonic()+args.seconds
 while time.monotonic()<end:
  try:
   with urllib.request.urlopen('http://127.0.0.1:8000/api/hardening/status',timeout=5) as res:data=json.load(res)
   history.append({'at':datetime.now(timezone.utc).isoformat(),'mode':data['workers']['mode'],
                   'nodes':data['workers']['nodes']})
  except Exception as e:history.append({'at':datetime.now(timezone.utc).isoformat(),'error':str(e)[:200]})
  time.sleep(min(args.interval,max(0,end-time.monotonic())))
 path=Path('results/hardening')/('worker_watch_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.json')
 path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps({'source':'local_status_api','samples':history},indent=2)+'\n')
 print('Saved',path,'samples:',len(history))
if __name__=='__main__':main()
