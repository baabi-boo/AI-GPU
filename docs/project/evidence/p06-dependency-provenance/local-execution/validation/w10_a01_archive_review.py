#!/usr/bin/env python3
"""Independent complete native/dependency replay plus exact selector scope review."""
import collections,datetime,hashlib,json,pathlib,subprocess,sys,time
sys.dont_write_bytecode=True
S=pathlib.Path('/workspace/p06-local-run-source-04')
P=pathlib.Path('/workspace/p06-local-native-run-04/evidence/native-lifetime')
Z=pathlib.Path('/workspace/scratch/279b6658611e/AI-GPU_P06_local_attempt_04_passed_2026-11-23.zip')
OUT=pathlib.Path('/workspace/scratch/279b6658611e/validation/w10_a01-archive-review.json')
revision='0f9aaa36d46364c297254164f5dab0d4f0e88349'
zip_pin='d3a16e1e6e92a68414f5fdcce564b963dde2e9e801601191d52ceeb974faea6f'
source_pin='04207022c43cc2e5a715e1eca626adb165711c975f2d1757e5ec3baddfbd5bf1'
report_pin='83040361c8b934dcab290bb8ba00d74e0b2b05f4db25f3455518c34945b997a6'
dep_pin='f22f564ddd8d8a3d20636410f6d2f04b328018676803fdc5ea483c28ded10e8a'
def git(*args):return subprocess.check_output(['git','-C',str(S),*args]).decode().strip()
checkout={'revision':git('rev-parse','HEAD'),'tree':git('rev-parse','HEAD^{tree}'),'status':git('status','--porcelain=v1','--untracked-files=all'),'submodules':git('submodule','status','--recursive')}
assert checkout['revision']==revision and checkout['tree']=='fb8e90f38498ca138acf978d4a11d6a087e5a778' and checkout['status']==''
assert len(checkout['submodules'].splitlines())==8
sys.path.insert(0,str(S/'ci/project'))
import p06_dependency_native_replay as native
api=native.dependency_replay._archive_api()
prohibited=[]
def guard(event,args):
 if event in ('subprocess.Popen','os.system','os.exec','os.posix_spawn','os.fork','pty.spawn') or event.startswith('socket.'):
  prohibited.append(event);raise RuntimeError('inert review prohibits '+event)
sys.addaudithook(guard)
def ident(path):
 body=path.read_bytes();return {'sha256':hashlib.sha256(body).hexdigest(),'size_bytes':len(body)}
zip_before=ident(Z);assert zip_before['sha256']==zip_pin
start=time.monotonic(); started_at=datetime.datetime.now(datetime.timezone.utc).isoformat()
with api.ArchiveReader(Z,zip_pin) as archive:
 outer=archive.view('')
 result,context=native.verify_view(outer.subview('native-lifetime'),outer.subview('dependency-build'),api,expected_revision=revision,expected_receipt_sha256=dep_pin,expected_native_report_sha256=report_pin,expected_source_manifest_sha256=source_pin)
 archive_receipt=archive.receipt()
assert ident(Z)==zip_before and not prohibited
report=json.loads((P/'report.json').read_bytes())
manifest_path=S/'docs/project/evidence/p06-counter-diagnostics/lifetime-source-manifest.json'
manifest=json.loads(manifest_path.read_bytes())
selector=lambda row:tuple(row[k] for k in ('name','mpm_class','csr','core_id'))
expected={selector(row) for row in manifest['selectors']}
unavailable={selector(row) for row in manifest['unavailable_selectors']}
assert len(expected)==33 and len(unavailable)==12
per_process=[]
for process in report['processes']:
 observation=process['observation']; summaries=observation['warm']['summary']['snapshots']
 for snap in summaries.values():
  enabled=[row for row in snap['counters'] if row['enabled']]
  disabled=[row for row in snap['counters'] if not row['enabled']]
  assert {selector(row) for row in enabled}==expected and len(enabled)==33
  assert {selector(row) for row in disabled}==unavailable and len(disabled)==12
  assert all(row['status']==0 and type(row['value']) is int for row in enabled)
  assert all(row['status'] is None and row['value'] is None for row in disabled)
 lt=observation['lifetime']; assert [row['before']['reset_generation'] for row in lt['snapshots']]==[1,2,34,34]
 assert len(lt['runs'])==33 and all(row['real_call_entered'] and row['completed'] and not row['exception'] for row in lt['runs'])
 assert lt['destruction']['completed'] and lt['destruction']['before']['pending_reads']==0 and lt['destruction']['idle_after']
 per_process.append({'id':process['id'],'snapshots':len(summaries),'exact_available_selectors':33,'exact_unavailable_selectors':12,'run_reset_pairs':33,'snapshot_reset_generations':[1,2,34,34],'terminal_pending_reads':0,'destruction_completed':True})
summary={'schema_version':1,'reviewer':'w10_a01','scope':'Actual04 complete native/dependency retained semantics and selector interpretation; controls excluded','outcome':'pass','source_checkout':checkout,'source_manifest_sha256':source_pin,'native_report_sha256':report_pin,'dependency_report_sha256':dep_pin,'archive':zip_before,'archive_member_count':archive_receipt['data_files'],'archive_expanded_bytes':archive_receipt['expanded_bytes'],'archive_read_count':archive_receipt['read_count'],'archive_read_bytes':archive_receipt['read_bytes'],'archive_closing_check_completed':True,'archive_unchanged':True,'native_result':{k:v for k,v in result.items() if k not in ('dependency_verification',)},'exact_selector_process_checks':per_process,'component_manifest':{'path':str(manifest_path),'identity':ident(manifest_path),'qualified':manifest['qualified'],'ready_for_warm':manifest['ready_for_warm'],'premise_count':len(manifest['premises'])},'native_execution_during_review':'not_run','retained_code_executed':False,'prohibited_events':prohibited,'started_at':started_at,'finished_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'duration_seconds':round(time.monotonic()-start,6),'limitations':['Complete raw native population and retained graph were reviewed; separate pending and alternate-dependency controls are not part of this review.','The33selectors represent40cumulativebackingcomponents under the historical conditional source proof. This review does not newly qualify all component lifetimes or discharge ten premises.','Pending reads are a transient balance, not a41stmonotonecomponent.','No current full hosted run, producer authentication, physical hardware, warm performance or acceptance is claimed.']}
OUT.write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n')
print(json.dumps({'outcome':'pass','output':str(OUT),'identity':ident(OUT),'duration_seconds':summary['duration_seconds'],'counts':result['counts'],'selector_processes':len(per_process)}))
