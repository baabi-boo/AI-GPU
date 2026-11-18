import hashlib,json,os,subprocess,sys,time
from pathlib import Path
root=Path('${SOURCE}')
out=Path('${CONTINUATION}/work/formal-tests')
out.mkdir();(out/'tmp').mkdir()
sys.path.insert(0,str(root/'ci/project'))
from baseline_process import run_bounded

def git(*args):return subprocess.check_output(['git',*args],cwd=root,text=True).strip()
def snapshot():
 paths=git('diff','--name-only','359a8c007f450a8146540f795cb576b29818fa03','HEAD').splitlines()+['ci/project/baseline_process.py']
 return [{'path':p,'sha256':hashlib.sha256((root/p).read_bytes()).hexdigest(),'size_bytes':(root/p).stat().st_size}for p in sorted(set(paths))]
assert not git('status','--porcelain')
overrides={'PYTHONDONTWRITEBYTECODE':'1','CCACHE_DISABLE':'1','OBJCACHE':'','MAKEFLAGS':'-j2','CMAKE_BUILD_PARALLEL_LEVEL':'2','THREADS':'2','TMPDIR':str(out/'tmp'),'LC_ALL':'C'}
env=os.environ.copy();env.update(overrides);env.pop('PYTHONPATH',None)
record={'schema_version':1,'source_revision':git('rev-parse','HEAD'),'source_tree':git('rev-parse','HEAD^{tree}'),'source_dirty':False,'environment_overrides':overrides,'python':sys.version,'budget':{'timeout_seconds':900,'min_free_bytes':15*1024**3,'max_log_bytes':16*1024**2,'max_rss_bytes':6*1024**3},'source_before':snapshot(),'commands':[]}
for label,argv in [('governance',['python3','ci/project/check_project.py']),('full-suite',['python3','-m','unittest','discover','-s','ci/project','-p','test_*.py','-v'])]:
 print('Starting '+label,flush=True)
 result=run_bounded(argv,root,env,out/(label+'.log'),timeout_seconds=900,resource_paths=(out,root))
 record['commands'].append(dict(result,label=label,argv=argv,cwd=str(root),log=label+'.log'))
 (out/'verification.json').write_text(json.dumps(record,indent=2,sort_keys=True)+'\n')
 print(json.dumps({'label':label,**result}),flush=True)
 if result['outcome']!='pass':break
record['source_after']=snapshot();record['working_tree_after']=git('status','--porcelain');record['source_stable']=record['source_before']==record['source_after'] and not record['working_tree_after'];record['outcome']='pass' if record['source_stable'] and len(record['commands'])==2 and all(c['outcome']=='pass' for c in record['commands'])else'fail'
(out/'verification.json').write_text(json.dumps(record,indent=2,sort_keys=True)+'\n')
print('Formal result: '+record['outcome'],flush=True)
sys.exit(0 if record['outcome']=='pass' else 1)
