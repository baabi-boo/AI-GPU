#!/usr/bin/env python3
"""Read-only Git/source projection for local original04 and hosted-only fixes."""
import ast, hashlib, json, os, pathlib, subprocess, sys
from datetime import datetime, timezone
sys.dont_write_bytecode=True
SOURCE=pathlib.Path('/workspace/p06-local-run-source-04')
CURRENT=pathlib.Path('/workspace/ai-gpu-next')
EVIDENCE=pathlib.Path('/workspace/p06-local-native-run-04/evidence')
REVISION='0f9aaa36d46364c297254164f5dab0d4f0e88349'
FINAL='8d735eba0016cdc64592d9c40a98e6b52574e64b'
HOSTED='ci/project/p06_dependency_prepare.py'
OUT=pathlib.Path('/workspace/scratch/279b6658611e/validation/w09_a06-source-projection.json')
def git(*args):
 return subprocess.check_output(['git','-C',str(CURRENT),*args],env=dict(os.environ,GIT_OPTIONAL_LOCKS='0'))
def ident(body): return {'sha256':hashlib.sha256(body).hexdigest(),'size_bytes':len(body)}
def tree(revision):
 result={}
 for line in git('ls-tree','-rz','-r',revision).split(b'\0'):
  if not line:continue
  meta,name=line.split(b'\t',1); mode,kind,oid=meta.decode().split()
  result[name.decode()]={'mode':mode,'type':kind,'oid':oid}
 return result
assert git('rev-parse','HEAD').decode().strip()==FINAL
before,after=tree(REVISION),tree(FINAL)
changed=sorted(p for p in set(before)|set(after) if before.get(p)!=after.get(p))
expected=[HOSTED,'ci/project/test_p06_dependency_control_replay.py','ci/project/test_p06_dependency_local_replay.py','ci/project/test_p06_dependency_native_replay.py','ci/project/test_p06_dependency_prepare.py','ci/project/test_p06_dependency_prepare_cache_review.py']
assert changed==sorted(expected)
rows=[]
for name in changed:
 row={'path':name,'scope':'hosted preparation only; no local execution entry point' if name==HOSTED else 'test only'}
 for label,revision,entries in [('before',REVISION,before),('after',FINAL,after)]:
  row[label]=None if name not in entries else dict(entries[name],**ident(git('show',revision+':'+name)))
 if row['after']:
  assert ident((CURRENT/name).read_bytes())=={k:row['after'][k] for k in ('sha256','size_bytes')}
 rows.append(row)
assert all(name==HOSTED or name.startswith('ci/project/test_') for name in changed)
sys.path.insert(0,str(SOURCE/'ci/project'))
import p06_dependency_local_replay as replay
import p06_dependency_local_execute as execute
import p06_dependency_build as build
import p06_dependency_local_prepare as prepare
import p06_dependency_lifetime_execute as lifetime
import p06_pending_probe as probe
import p06_dependency_substitution as substitution
assert 'p06_dependency_prepare' not in sys.modules
trusted=replay._reader_sources()
assert HOSTED not in {r['path'] for r in trusted}
for row in trusted:
 assert ident((SOURCE/row['path']).read_bytes())=={k:row[k] for k in ('sha256','size_bytes')}
 assert (SOURCE/row['path']).read_bytes()==(CURRENT/row['path']).read_bytes()
 assert before[row['path']]==after[row['path']]
operational=['ci/project/'+name+'.py' for name in ['p06_dependency_local_execute','p06_dependency_local_prepare','p06_dependency_build','p06_dependency_lifetime_execute','p06_pending_probe','p06_dependency_substitution']]
for name in operational:
 assert before[name]==after[name] and (SOURCE/name).read_bytes()==(CURRENT/name).read_bytes()
# Examine every local Python module loaded by all seven current entry points.
modules=[]
for name,module in sorted(sys.modules.items()):
 path=getattr(module,'__file__',None)
 if not path: continue
 path=pathlib.Path(path).resolve()
 if path.parent!=SOURCE/'ci/project':continue
 relative=path.relative_to(SOURCE).as_posix(); body=path.read_bytes()
 assert relative!=HOSTED and before[relative]==after[relative]
 assert body==(CURRENT/relative).read_bytes()
 imports=[]
 for node in ast.walk(ast.parse(body)):
  if isinstance(node,ast.Import): imports.extend(x.name for x in node.names)
  elif isinstance(node,ast.ImportFrom) and node.module: imports.append(node.module)
  elif isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='import_module' and node.args and isinstance(node.args[0],ast.Constant): imports.append(node.args[0].value)
 assert 'p06_dependency_prepare' not in imports
 modules.append({'module':name,'path':relative,**ident(body),'imports':sorted(set(imports))})
envelope=json.loads((EVIDENCE/'local-execution.json').read_bytes())
paths={k:envelope[field] for k,field in [('source','source_dir'),('workspace','workspace_dir'),('archive','archive_root'),('repositories','dependency_repositories_root'),('host_bin','host_bin')]}
expected_stages=execute.stage_specs(paths,REVISION,envelope['interpreter']['path'],dependency_pin='f22f564ddd8d8a3d20636410f6d2f04b328018676803fdc5ea483c28ded10e8a')
assert len(expected_stages)==5
for observed,expected in zip(envelope['stages'],expected_stages):
 assert observed['id']==expected['id'] and observed['argv']==expected['argv']
assert all(not any(HOSTED in a for a in stage['argv']) for stage in expected_stages)
native=json.loads((EVIDENCE/'native-lifetime/report.json').read_bytes())
snapshot=EVIDENCE/'native-lifetime'/native['source_before']['path'];snapshot_body=snapshot.read_bytes()
assert ident(snapshot_body)=={k:native['source_before'][k] for k in ('sha256','size_bytes')}
sources=json.loads(snapshot_body)
source_rows={r['path']:r for r in sources['files']}
assert HOSTED in source_rows
assert ident((SOURCE/HOSTED).read_bytes())=={k:source_rows[HOSTED][k] for k in ('sha256','size_bytes')}
native_helpers={r['path'] for r in native['loaded_helpers']}
assert HOSTED not in native_helpers
assert all(before[name]==after[name] for name in native_helpers)
current_source_deltas=[]
projected_main_source_count=0
for name,row in source_rows.items():
 path=CURRENT/name
 if name in before and name in after and before[name]['type']=='blob':
  assert path.is_file()
  projected_main_source_count+=1
  if ident(path.read_bytes())!={k:row[k] for k in ('sha256','size_bytes')}:current_source_deltas.append(name)
assert current_source_deltas==[HOSTED]
result={'schema_version':1,'scope':'Exact Git/source projection, not a new execution or source-checkout identity upgrade','observed_at':datetime.now(timezone.utc).isoformat(),'outcome':'pass','execution_revision':REVISION,'execution_tree':git('rev-parse',REVISION+'^{tree}').decode().strip(),'later_revision':FINAL,'later_tree':git('rev-parse',FINAL+'^{tree}').decode().strip(),'changed_files':rows,'only_production_delta':HOSTED,'local_operational_entry_points_unchanged':operational,'trusted_reader_source_count':len(trusted),'trusted_reader_sources':trusted,'local_module_closure_count':len(modules),'local_module_closure':modules,'hosted_preparer_imported':False,'five_defined_stage_entry_points':[r['argv'][2] for r in expected_stages],'observed_stage_ids':[r['id'] for r in envelope['stages']],'hosted_preparer_executed_by_defined_local_stages':False,'native_source_snapshot':dict(path=str(snapshot),**ident(snapshot_body)),'hosted_preparer_retained_in_native_snapshot':source_rows[HOSTED],'hosted_preparer_in_native_loaded_helpers':False,'native_loaded_helper_count':len(native_helpers),'current_native_source_deltas':current_source_deltas,'projected_main_source_count':projected_main_source_count,'recorded_native_source_file_count':len(source_rows),'all_gitlink_objects_unchanged':all(after[name]==row for name,row in before.items() if row['type']=='commit'),'revision_projection_does_not_change_original_revision':True,'limitations':['Native04 is executed at0f9aaa36, not8d735eba; this projection never changes the original revision or packet.','The hosted-only preparation correction has separate tests/review, not a new hosted success.','This projection reads trusted local source and Git objects; it does not execute retained packet content or qualify the native result.']}
OUT.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
print(json.dumps({k:result[k] for k in ['outcome','execution_revision','later_revision','only_production_delta','trusted_reader_source_count','local_module_closure_count','native_loaded_helper_count','current_native_source_deltas']},indent=2))
print(json.dumps({'path':str(OUT),**ident(OUT.read_bytes())}))
