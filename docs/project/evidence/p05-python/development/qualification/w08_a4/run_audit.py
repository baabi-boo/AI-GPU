import hashlib, json, subprocess, sys, time
from pathlib import Path
repo=Path('/workspace/scratch/ba0248fde989/AI-GPU')
packet=repo.parent/'p05-work/ci-e1420fd/simx-bf16/python'
work=repo.parent/'p05-work/w08_a4'
auditor=repo/'docs/project/evidence/p05-python/reviews/audit_numerics.py'
output=auditor.parent/'bf16-numerics.json';log=auditor.parent/'bf16-numerics.log'
expected='608b16c80a1a40816ef15f04b2670c736e2abca7768e7c6ad546c8a96f23e736'
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def snapshot():
 manifest=json.loads((packet/'artifacts/bundle/manifest.json').read_text())
 names=[r['path'] for r in manifest['binding_sources']]+['ci/project/fixtures/p02_layout_v1.json','ci/project/fixtures/p02_wmma_numerical_v1.json','ci/project/fixtures/p04_tiny_mlp_v1.json','docs/project/evidence/p04-executor/reviews/audit_numerics.py']
 return {'auditor_sha256':sha(auditor),'packet':{str(p.relative_to(packet)):sha(p) for p in sorted(packet.rglob('*')) if p.is_file()},'source':{name:sha(repo/name) for name in names},'archive_sha256':sha(packet.parent.parent/'simx-bf16.zip'),'git':subprocess.check_output(['git','rev-parse','HEAD','HEAD^{tree}'],cwd=repo,text=True).splitlines()}
before=snapshot();assert before['auditor_sha256']==expected
argv=[sys.executable,'-B',str(auditor),'--source-dir',str(repo),'--packet',str(packet),'--selected-scope','--output',str(output)]
start=time.monotonic()
with log.open('x') as stream:child=subprocess.run(argv,cwd=repo,stdout=stream,stderr=subprocess.STDOUT,timeout=180,check=False)
after=snapshot();record={'scope':'independent retained-data BF16 numerical audit; no native execution','argv':argv,'cwd':str(repo),'exit_code':child.returncode,'elapsed_seconds':time.monotonic()-start,'before':before,'after':after,'unchanged':before==after,'output_sha256':sha(output),'log_sha256':sha(log)}
(work/'execution.json').write_text(json.dumps(record,indent=2)+'\n')
assert child.returncode==0 and before==after
result=json.loads(output.read_text());assert result['outcome']=='pass' and result['full_matrix_verified'] is False and result['matrix_scope']=='incomplete_selected_format'
print(json.dumps({k:result[k] for k in ['outcome','matrix_scope','total_launches','event_profile_pairs','counts']},indent=2));print('packet_files',len(before['packet']),'source_files',len(before['source']))
