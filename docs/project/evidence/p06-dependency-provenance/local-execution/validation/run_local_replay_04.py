import datetime,hashlib,json,os,pathlib,runpy,sys,time
sys.dont_write_bytecode=True
source=pathlib.Path('/workspace/p06-local-replay-source')
root=pathlib.Path('/workspace/p06-local-native-run-04/evidence')
validation=pathlib.Path('/workspace/scratch/279b6658611e/validation')
archive=pathlib.Path('/workspace/scratch/279b6658611e/AI-GPU_P06_local_attempt_04_passed_2026-11-23.zip')
output=validation/'local-attempt-04-replay.json'
identity=json.loads(archive.with_suffix('.identity.json').read_text())
envelope=json.loads((root/'local-execution.json').read_text());pins=envelope['reports']
argv=[str(source/'ci/project/p06_dependency_local_replay.py'),str(archive),'--sha256',identity['sha256'],'--expected-revision',envelope['expected_revision'],'--dependency-receipt-sha256',pins['dependency-build']['sha256'],'--native-report-sha256',pins['native-lifetime']['sha256'],'--source-manifest-sha256',pins['native-source']['sha256'],'--probe-report-sha256',pins['pending-probe']['sha256'],'--substitution-report-sha256',pins['dependency-substitution']['sha256'],'--local-execution-sha256',hashlib.sha256((root/'local-execution.json').read_bytes()).hexdigest(),'--output',str(output)]
assert not output.exists()
before=hashlib.sha256(archive.read_bytes()).hexdigest();assert before==identity['sha256']
events=[];active=True
def hook(event,args):
 if not active:return
 if event in ('subprocess.Popen','os.system','os.exec','os.posix_spawn','socket.connect','ctypes.dlopen'):
  events.append({'event':event});raise RuntimeError('execution/network denied: '+event)
 if event=='open':
  path,mode,flags=args
  writing=isinstance(flags,int) and flags & (os.O_WRONLY|os.O_RDWR|os.O_APPEND|os.O_TRUNC|os.O_CREAT)
  if writing and str(path)!=str(output):
   events.append({'event':event,'path':str(path)});raise RuntimeError('unexpected replay write: '+str(path))
sys.path.insert(0,str(source/'ci/project'));sys.argv=argv
started=time.monotonic();timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat();sys.addaudithook(hook)
code=0;error=None
try:runpy.run_path(argv[0],run_name='__main__')
except SystemExit as outcome:code=outcome.code if isinstance(outcome.code,int) else 1
except BaseException as outcome:code=1;error=repr(outcome)
finally:active=False
after=hashlib.sha256(archive.read_bytes()).hexdigest()
receipt={'schema_version':1,'scope':'Unmodified public local replay CLI with all real semantic readers and exact external pins','argv':argv,'source_revision':envelope['expected_revision'],'reader_revision':'ba2d649d4150e046c2ba610de02725d9d062b1be','reader_tree':'a9db358818a66f2a241ed2d8a7453edf938ccb2c','started_at':timestamp,'finished_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'duration_seconds':time.monotonic()-started,'exit_code':code,'error':error,'prohibited_events':events,'archive_before_sha256':before,'archive_after_sha256':after,'archive_unchanged':before==after,'retained_code_executed':False}
if output.exists():
 body=output.read_bytes();result=json.loads(body);receipt['result']={'path':output.name,'sha256':hashlib.sha256(body).hexdigest(),'size_bytes':len(body),'outcome':result['outcome']}
 summary={'schema_version':1,'scope':receipt['scope'],'source_revision':receipt['source_revision'],'reader_revision':receipt['reader_revision'],'reader_tree':receipt['reader_tree'],'outcome':result['outcome'],'receipt':receipt,'managed_counts':result.get('managed_counts'),'local_identity':result.get('local_identity'),'pending_probe':result.get('pending_probe'),'dependency_substitution':result.get('dependency_substitution'),'archive_read':{k:v for k,v in result['archive_read'].items() if k!='read_files'},'native_execution':result['native_execution'],'retained_code_executed':result['retained_code_executed'],'all_seven_claims_false':all(result[k] is False for k in ('qualified','ready_for_warm','warm_execution','full_warm_coverage','acceptance_claimed','phase_acceptance','performance_acceptance'))}
 (validation/'local-attempt-04-replay-summary.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n')
(validation/'local-attempt-04-replay-process.json').write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n')
print(json.dumps(receipt,indent=2))
raise SystemExit(code)
