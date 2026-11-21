from pathlib import Path
import hashlib,json,runpy,shutil,sys,time
root=Path('/workspace/scratch/55f1fb23ad42/AI-GPU')
work=root.parent/'p05-torch-work'
sys.path.insert(0,str(root/'ci/project'))
from p05_test_runtime import TestRuntime
initial=work/'w04_a3-native-initial'
build=initial/'runtime'
current=root/'ci/project/p05_torch_native_host_tests.py'
namespace=runpy.run_path(str(current))
commands=json.loads((build/'build_commands.json').read_text())['commands']
runtime=TestRuntime(build,build/'bundle',build/'python',next((build/'python/vortex_ai').glob('_native*.so')),build/'generated/p05_build_config.h','fp16',tuple(tuple(x) for x in commands))
manifest=json.loads((runtime.bundle/'manifest.json').read_text())
for row in manifest['binding_sources']:
 assert hashlib.sha256((root/row['path']).read_bytes()).hexdigest()==row['sha256'], row['path']
for path in (runtime.package_root/'vortex_ai').glob('*.py'):
 assert path.read_bytes()==(root/'python/vortex_ai'/path.name).read_bytes(),path
out=work/'w04_a3-native-recheck'
out.mkdir()
snapshot=out/'test.snapshot.py'
shutil.copyfile(current,snapshot)
report={'schema_version':1,'scope':namespace['SCOPE'],'acceptance_claimed':False,'native_accelerator_execution':'not_run','backend_execution':'not_run','format':'fp16','python_version':sys.version,'reuse':'same single compiled immutable host-only runtime from initial run','extension_sha256':namespace['digest'](runtime.extension),'manifest_sha256':namespace['digest'](runtime.bundle/'manifest.json'),'test_sha256':namespace['digest'](snapshot),'results':[]}
for scenario in namespace['SCENARIOS']:
 target=out/scenario;target.mkdir()
 source='import runpy, sys\n'+f'sys.argv = [{str(snapshot)!r}, "--child", {scenario!r}]\n'+f'runpy.run_path({str(snapshot)!r}, run_name="__main__")\n'
 (target/'launcher.py').write_text(source)
 namespace['write_json'](target/'command.json',{'argv':[sys.executable,'-c',source],'cwd':str(runtime.root),'pythonpath':runtime.environment()['PYTHONPATH'],'timeout_seconds':30,'scope':namespace['SCOPE']})
 began=time.monotonic();result=runtime.run_python(source,timeout=30,check=False)
 (target/'stdout.log').write_text(result.stdout);(target/'stderr.log').write_text(result.stderr)
 row={'scenario':scenario,'exit_code':result.returncode,'outcome':'pass' if result.returncode==0 and not result.stderr else 'fail','seconds':round(time.monotonic()-began,3),'stdout_sha256':namespace['digest'](target/'stdout.log'),'stderr_sha256':namespace['digest'](target/'stderr.log')}
 if row['outcome']=='pass':row['observations']=json.loads(result.stdout)
 report['results'].append(row)
 print(scenario+': '+row['outcome'],flush=True)
 namespace['write_json'](out/'report.json',report)
report['outcome']='pass' if all(row['outcome']=='pass' for row in report['results']) else 'fail'
namespace['write_json'](out/'report.json',report)
raise SystemExit(0 if report['outcome']=='pass' else 1)
