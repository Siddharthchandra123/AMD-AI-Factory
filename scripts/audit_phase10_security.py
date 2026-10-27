#!/usr/bin/env python3
"""Local, read-only security configuration check. Never prints secret values."""
from __future__ import annotations
import json
from pathlib import Path
import re
import sys

ROOT = Path.cwd()
COMPOSE = ROOT / 'docker-compose.yml'


def audit(source: str, env_example: str = '', gitignore: str = '') -> dict:
    rows=[]
    def put(check,passed,detail): rows.append({'check':check,'passed':passed,'detail':detail})
    for port, target in (('3000','3000'),('8000','8000'),('3001','3000'),('9090','9090')):
        item = bool(re.search(r'["\']127\.0\.0\.1:' + port + r':' + target + r'["\']', source))
        put(f'loopback_{port}',item,'Service port must bind 127.0.0.1 for local demo')
    put('backend_token_configuration','MISSION_CONTROL_WRITE_TOKEN' in source,
        'Opt-in mutation guard can be supplied through environment; read APIs are not protected')
    put('postgres_data_volume','pgdata:/var/lib/postgresql/data' in source,'Persistent database storage')
    put('redis_data_volume','redisdata:/data' in source,'Persistent Redis volume (durability depends on Redis persistence settings)')
    put('dotenv_gitignored',bool(re.search(r'^\.env\s*$',gitignore,re.M)),'.env must not be committed')
    put('no_obvious_secret_in_example',not bool(re.search(r'^MISSION_AGENT_TOKEN=[^\s#]+',env_example,re.M)),
        '.env.example must not contain an actual agent token')
    return {'status':'pass' if all(x['passed'] for x in rows) else 'review_needed',
            'checks':rows,'limitations':['Not a penetration test','Opt-in write token does not protect API GET/SSE endpoints',
            'Current local UI does not supply write-token headers','Cannot establish real-GPU failover without hardware']}


def main():
    if not COMPOSE.is_file():
        print('Run from AMD AI Factory project root.'); return 2
    result = audit(COMPOSE.read_text(encoding='utf-8'),
                   (ROOT/'.env.example').read_text(encoding='utf-8') if (ROOT/'.env.example').exists() else '',
                   (ROOT/'.gitignore').read_text(encoding='utf-8') if (ROOT/'.gitignore').exists() else '')
    folder = ROOT/'results'/'hardening'
    folder.mkdir(parents=True,exist_ok=True)
    path = folder/'security_audit.json'
    path.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))
    print('Saved non-secret audit:',path)
    return 0 if result['status']=='pass' else 1

if __name__ == '__main__': sys.exit(main())
