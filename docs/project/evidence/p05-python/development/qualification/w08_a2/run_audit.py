from pathlib import Path
import ast
import hashlib
import json
import subprocess
import sys
import time

REPO = Path('/workspace/scratch/ba0248fde989/AI-GPU')
WORK = REPO.parent / 'p05-work'
SCRATCH = WORK / 'w08_a2'
PACKET = WORK / 'ci-e1420fd/simx-fp16/python'
ARCHIVE = WORK / 'ci-e1420fd/simx-fp16.zip'
SCRIPT = REPO / 'docs/project/evidence/p05-python/reviews/audit_dispatch.py'
RESULT = SCRIPT.parent / 'fp16-dispatch.json'
LOG = SCRIPT.parent / 'fp16-dispatch.log'
EXPECTED = 'ab0a1d1d6d0268b0766e5d3bc211e2830efb5e9683a413854fc1a16a3d5de391'

def sha(body):
    return hashlib.sha256(body).hexdigest()

def inventory(root):
    return {str(p.relative_to(root)): sha(p.read_bytes()) for p in sorted(root.rglob('*')) if p.is_file()}

def canonical(value):
    return (json.dumps(value,sort_keys=True,separators=(',',':'))+'\n').encode()

def source_inventory():
    names = {'docs/project/evidence/p04-executor/reviews/audit_dispatch.py', 'profiles/p02-tfr.json'}
    for node in ast.parse(SCRIPT.read_text()).body:
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id in ('FIXTURES','NATIVE_PINS','ALLOCATOR_PINS') for t in node.targets):
            names.update(ast.literal_eval(key) for key in node.value.keys)
    return {name:sha((REPO/name).read_bytes()) for name in sorted(names)}

SCRATCH.mkdir()
before = {'packet_files':inventory(PACKET), 'archive_sha256':sha(ARCHIVE.read_bytes()),
          'auditor_sha256':sha(SCRIPT.read_bytes()), 'sources':source_inventory(),
          'git_head_tree':subprocess.check_output(['git','rev-parse','HEAD','HEAD^{tree}'],cwd=REPO,text=True).splitlines()}
assert before['auditor_sha256']==EXPECTED
assert before['archive_sha256']=='467122e41bee4e67f9eef285e015b2dee3a52522f0bcb3f497e3cec87e6c7380'
assert len(before['packet_files'])==206
argv=[sys.executable,'-B',str(SCRIPT),'--source-dir',str(REPO),'--packet',str(PACKET),'--selected-scope','--output',str(RESULT)]
started=time.monotonic()
with LOG.open('xb') as stream:
    child=subprocess.run(argv,cwd=REPO,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,timeout=120,check=False)
after = {'packet_files':inventory(PACKET), 'archive_sha256':sha(ARCHIVE.read_bytes()),
         'auditor_sha256':sha(SCRIPT.read_bytes()), 'sources':source_inventory(),
         'git_head_tree':subprocess.check_output(['git','rev-parse','HEAD','HEAD^{tree}'],cwd=REPO,text=True).splitlines()}
assert before==after
result=json.loads(RESULT.read_text())
receipt={'schema_version':1,'command':argv,'cwd':str(REPO),'exit_code':child.returncode,'elapsed_seconds':time.monotonic()-started,
         'source_scope':'retained actual FP16 SimX execution at e1420fd550f716df33a2556057b7086a03032cbe; no new native execution',
         'outcome':result.get('outcome'),'selected_scope':result.get('selected_scope'),'full_matrix_checked':result.get('full_matrix_checked'),
         'input_inventory_sha256':sha(canonical(before['packet_files'])),'auditor_sha256_before':before['auditor_sha256'],
         'auditor_sha256_after':after['auditor_sha256'],'before':before,'after':after,
         'result_sha256':sha(RESULT.read_bytes()),'log_sha256':sha(LOG.read_bytes()),'counts':result.get('counts'),
         'execution_performed':False,'acceptance_claimed':False}
(SCRATCH/'execution.json').write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n')
assert child.returncode==0 and result['outcome']=='pass' and result['selected_scope'] is True and result['full_matrix_checked'] is False
print(json.dumps({k:receipt[k] for k in ('exit_code','outcome','elapsed_seconds','input_inventory_sha256','auditor_sha256_before','result_sha256','log_sha256','counts')},indent=2))
