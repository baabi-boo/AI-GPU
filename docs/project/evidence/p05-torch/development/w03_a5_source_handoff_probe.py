from pathlib import Path
import hashlib,json,subprocess,sys,tempfile
root=Path('/workspace/scratch/55f1fb23ad42/AI-GPU')
work=root.parent/'p05-torch-work'
sys.dont_write_bytecode=True
sys.path.insert(0,str(root/'ci/project'))
import p05_torch_execute as runner
program='''import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import p05_execute as p
print(json.dumps({"source":p.source_snapshot(p.ROOT),"loaded":p.LOADED_HELPERS}))
'''
proc=subprocess.run([sys.executable,'-I','-B','-c',program,str(root/'ci/project')],cwd=work,
 check=True,text=True,capture_output=True,timeout=30)
original=json.loads(proc.stdout)
assert 'ci/project/p05_torch_execute.py' not in {r['path'] for r in original['loaded']}
with tempfile.TemporaryDirectory(prefix='p05-real-source-handoff-') as temp:
 output=Path(temp)
 report={'source_stable':True,'loaded_helpers':original['loaded'],'retained_sources':[]}
 def write(name,data):
  target=output/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
  return {'path':name,'sha256':hashlib.sha256(data).hexdigest(),'size_bytes':len(data)}
 for name in ('source-before','source-after'):
  report[name.replace('-','_')]=write('snapshots/'+name+'.json',json.dumps(original['source']).encode())
 retained=sorted(set(runner.python_run.SOURCE_FILES)|set(runner.bundle_producer._bundle.SOURCE_PATHS)|{r['path'] for r in original['loaded']})
 for name in retained:report['retained_sources'].append(write('artifacts/source/'+name,(root/name).read_bytes()))
 result=runner._python_sources(runner.bundle_producer._Inputs(),root,output,report,{'checkout':original['source']['checkout']})
 assert result==original['source']
receipt={'scope':'host-only-source-inventory-handoff','outcome':'pass','native_execution':False,
 'original_helpers':len(original['loaded']),'source_files':len(original['source']['files']),
 'retained_sources':len(retained),'new_entry_point_excluded_from_original_helpers':True,
 'runner_sha256':hashlib.sha256(Path(runner.__file__).read_bytes()).hexdigest()}
(work/'w03_a5-source-handoff.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt,sort_keys=True))
