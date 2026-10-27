"""Offline regression tests. Run: python -m pytest tests/test_phase10.py -q"""
from pathlib import Path
import importlib.util
from datetime import datetime,timezone
from sqlalchemy import create_engine,String,DateTime,Float,Integer,Text,select
from sqlalchemy.orm import DeclarativeBase,Mapped,mapped_column,sessionmaker
import pytest

ROOT=Path(__file__).resolve().parents[1]
mod_spec=importlib.util.spec_from_file_location('hardening',ROOT/'backend/app/hardening.py')
mod=importlib.util.module_from_spec(mod_spec);mod_spec.loader.exec_module(mod)
install_spec=importlib.util.spec_from_file_location('phase10install',ROOT/'scripts/install_phase10.py')
installer=importlib.util.module_from_spec(install_spec);install_spec.loader.exec_module(installer)

class Base(DeclarativeBase):pass
class Job(Base):
 __tablename__='jobs'
 id:Mapped[str]=mapped_column(String,primary_key=True)
 priority:Mapped[str]=mapped_column(String,default='normal')
 status:Mapped[str]=mapped_column(String)
 execution_mode:Mapped[str]=mapped_column(String)
 created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))
 gpu_id:Mapped[str|None]=mapped_column(String,nullable=True)
 started_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
 completed_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
 duration_seconds:Mapped[float|None]=mapped_column(Float,nullable=True)
 queue_wait_seconds:Mapped[float|None]=mapped_column(Float,nullable=True)
 error_message:Mapped[str|None]=mapped_column(Text,nullable=True)

class Redis:
 def __init__(self):self.data={};self.queues={}
 def pipeline(self,transaction=False):return Pipeline(self)
 def set(self,k,v):self.data[k]=v
 def get(self,k):return self.data.get(k)
class Pipeline:
 def __init__(self,redis):self.redis=redis;self.ops=[]
 def __enter__(self):return self
 def __exit__(self,*_):return False
 def delete(self,*keys):self.ops.append(('delete',keys))
 def lpush(self,key,*ids):self.ops.append(('lpush',key,ids))
 def execute(self):
  for op in self.ops:
   if op[0]=='delete':
    for k in op[1]:self.redis.queues.pop(k,None)
   else:
    _,key,ids=op
    for item in ids:self.redis.queues.setdefault(key,[]).insert(0,item)


def test_restart_idempotent_no_duplicate_or_real_retry():
 engine=create_engine('sqlite:///:memory:');Base.metadata.create_all(engine)
 factory=sessionmaker(bind=engine,expire_on_commit=False)
 ts=datetime.now(timezone.utc)
 with factory.begin() as db:
  for id_,s,m in [('a','queued','simulation'),('b','running','simulation'),('c','running','mi300x'),('d','completed','simulation')]:
   db.add(Job(id=id_,priority='normal',status=s,execution_mode=m,created_at=ts,gpu_id='test'))
 redis=Redis();names={'high':'q:h','normal':'q:n','low':'q:l'}
 redis.queues['q:n']=['garbage','a','a']
 r=mod.reconcile_pending_jobs(factory,Job,redis,names,lambda:datetime.now(timezone.utc))
 assert r['counts']['simulation_running_requeued']==1
 assert r['counts']['real_running_failed_unknown']==1
 assert set(redis.queues['q:n'])=={'a','b'} and len(redis.queues['q:n'])==2
 with factory() as db:
  assert db.get(Job,'b').status=='queued'
  assert db.get(Job,'c').status=='failed'
  assert 'Not automatically retried' in db.get(Job,'c').error_message
 mod.reconcile_pending_jobs(factory,Job,redis,names,lambda:datetime.now(timezone.utc))
 assert len(redis.queues['q:n'])==2
 assert mod.read_recovery_status(redis)['available']


def test_health_classification_and_security():
 r=mod.worker_health_summary('mi300x',[{'id':'a','health':'stale','ready':False,'active_jobs':2},
                                            {'id':'b','health':'healthy','ready':True,'active_jobs':0}])
 assert r['counts']['stale']==1 and r['counts']['healthy']==1
 assert not mod.authorized_write_request('POST','/api/jobs','', 'secret')
 assert mod.authorized_write_request('PUT','/api/jobs','secret', 'secret')
 assert mod.authorized_write_request('GET','/api/jobs','', 'secret')
 assert mod.authorized_write_request('POST','/api/jobs','', '')


def test_source_patches_idempotent(tmp_path):
 # Source from v0.3/v0.5 project; explicit base archive is required in the test runner.
 import zipfile
 zip_path=Path('/mnt/data/amd-ai-factory-dynamic-v0.3.zip')
 if not zip_path.exists():pytest.skip('Original v0.3 archive not present')
 with zipfile.ZipFile(zip_path) as z:
  main=next(i for i in z.namelist() if i.endswith('backend/app/main.py'))
  compose=next(i for i in z.namelist() if i.endswith('docker-compose.yml'))
  home=next(i for i in z.namelist() if i.endswith('frontend/src/app/page.tsx'))
  original=z.read(main).decode();cp=z.read(compose).decode();page=z.read(home).decode()
 patched=installer.patch_main(original)
 assert installer.patch_main(patched)==patched
 assert 'reconcile_pending_jobs' in patched and 'worker_loop()' in patched
 assert installer.patch_compose(installer.patch_compose(cp))==installer.patch_compose(cp)
 assert installer.patch_home(installer.patch_home(page))==installer.patch_home(page)


def test_security_audit_no_sensitive_values():
 spec=importlib.util.spec_from_file_location('audit',ROOT/'scripts/audit_phase10_security.py')
 audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)
 sample='''"127.0.0.1:3000:3000"\n"127.0.0.1:8000:8000"\n"127.0.0.1:3001:3000"\n"127.0.0.1:9090:9090"\nMISSION_CONTROL_WRITE_TOKEN\npgdata:/var/lib/postgresql/data\nredisdata:/data'''
 results=audit.audit(sample,'MISSION_AGENT_TOKEN=\n','.env\n')
 assert results['status']=='pass'
