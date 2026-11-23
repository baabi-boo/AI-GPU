import datetime, hashlib, json, pathlib, sys, time
sys.dont_write_bytecode=True
sys.path.insert(0, '/workspace/p06-local-run-source-03/ci/project')
import p06_dependency_native_replay as native
archive_path=pathlib.Path('/workspace/scratch/279b6658611e/AI-GPU_P06_local_attempt_03_failed_2026-11-23.zip')
source=pathlib.Path('/workspace/p06-local-native-run-03/evidence/native-lifetime/report.json')
doc=json.loads(source.read_bytes())
pins={'expected_revision':'7251f078972c1d524de06d069e91b014b55896f5','expected_receipt_sha256':'202ee0fb2d79d4c47380e41dfb9356a2f353c36f977348442111461d2ffb4924','expected_native_report_sha256':'bba2af32da50326b43c0225f63478a3003865a6fc34eaef2e79b9228697a56d0','expected_source_manifest_sha256':doc['source_before']['sha256']}
api=native.dependency_replay._archive_api()
events=[]
def hook(event,args):
 if event in ('subprocess.Popen','os.system','os.exec','os.posix_spawn','socket.connect'):
  events.append(event);raise RuntimeError('retained execution prohibited: '+event)
sys.addaudithook(hook)
started=time.monotonic()
result={'scope':'actual03-unmocked-native-and-dependency-semantic-diagnostic','original_outer_outcome':'fail','controls_run':False,'pins':pins,'prohibited_events':events}
try:
 with api.ArchiveReader(archive_path,'d4136feb365a809ad975bde4e5c553fecbfc3143a5fff8da25a6de191a6cb5cc') as archive:
  outer=archive.view('')
  checked,_=native.verify_view(outer.subview('native-lifetime'),outer.subview('dependency-build'),api,**pins)
  result.update(outcome='pass',native_result=checked,archive_read=archive.receipt())
except Exception as error:
 result.update(outcome='fail',reason=str(error),error_type=type(error).__name__)
result['duration_seconds']=time.monotonic()-started
pathlib.Path('/workspace/scratch/279b6658611e/validation/native03_unmocked_diagnostic.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
print(json.dumps({k:v for k,v in result.items() if k!='native_result'},indent=2))
sys.exit(0 if result['outcome']=='pass' else 1)
