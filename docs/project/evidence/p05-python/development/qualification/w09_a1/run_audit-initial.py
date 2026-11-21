from pathlib import Path
import hashlib,json,subprocess,sys,time
ROOT=Path('/workspace/scratch/ba0248fde989/AI-GPU')
WORK=ROOT.parent/'p05-work/w09_a1'
PACKETS=ROOT.parent/'p05-work/ci-e1420fd'
OUT=ROOT/'docs/project/evidence/p05-python/reviews'
PINS={'numerics':'608b16c80a1a40816ef15f04b2670c736e2abca7768e7c6ad546c8a96f23e736','dispatch':'ab0a1d1d6d0268b0766e5d3bc211e2830efb5e9683a413854fc1a16a3d5de391','provenance':'4684a4e928ff672d371bdb78ab5f646b61ae59d1147c3c690e722a22a89186ac'}
def sha(raw):return hashlib.sha256(raw).hexdigest()
def file(path):
 raw=path.read_bytes();return {'sha256':sha(raw),'size_bytes':len(raw)}
def snapshot():
 manifest=json.loads((PACKETS/'simx-fp16/python/artifacts/bundle/manifest.json').read_text())
 rows=manifest['binding_sources']
 if isinstance(rows,dict):names=list(rows)
 else:names=[r['path'] for r in rows]
 return {'git':subprocess.check_output(['git','rev-parse','HEAD','HEAD^{tree}'],cwd=ROOT,text=True).splitlines(),
 'auditors':{name:file(OUT/('audit_'+name+'.py')) for name in PINS},
 'binding_sources':{name:file(ROOT/name) for name in names},
 'packets':{fmt:{p.relative_to(PACKETS/('simx-'+fmt)/'python').as_posix():file(p) for p in sorted((PACKETS/('simx-'+fmt)/'python').rglob('*')) if p.is_file()} for fmt in ('fp16','bf16')},
 'archives':{fmt:file(ROOT/'docs/project/evidence/p05-python/archives'/('simx-'+fmt+'.zip')) for fmt in ('fp16','bf16')}}
name=sys.argv[1];assert name in PINS
before=snapshot();assert before['auditors'][name]['sha256']==PINS[name]
output=OUT/('full-'+name+'.json');log=OUT/('full-'+name+'.log');assert not output.exists() and not log.exists()
command=[sys.executable,'-B',str(OUT/('audit_'+name+'.py')),'--source-dir',str(ROOT)]
for fmt in ('fp16','bf16'):command+=['--packet',str(PACKETS/('simx-'+fmt)/'python')]
command+=['--output',str(output)]
started=time.monotonic()
with log.open('xb') as stream:
 result=subprocess.run(command,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,timeout=180,check=False)
after=snapshot();audit=json.loads(output.read_bytes()) if output.is_file() else {}
record={'schema_version':1,'scope':'full retained-data audit; no native execution or phase acceptance','command':command,'cwd':str(ROOT),'exit_code':result.returncode,'elapsed_seconds':time.monotonic()-started,'before':before,'after':after,'stable':before==after,'output':file(output) if output.is_file() else None,'log':file(log),'outcome':audit.get('outcome'),'full_matrix':audit.get('full_matrix_verified',audit.get('full_matrix'))}
(WORK/(name+'-execution.json')).write_text(json.dumps(record,indent=2,sort_keys=True)+'\n')
print(json.dumps({k:record[k] for k in ('exit_code','elapsed_seconds','stable','outcome','full_matrix')},sort_keys=True))
assert result.returncode==0 and record['stable'] and record['outcome']=='pass' and record['full_matrix'] is True
