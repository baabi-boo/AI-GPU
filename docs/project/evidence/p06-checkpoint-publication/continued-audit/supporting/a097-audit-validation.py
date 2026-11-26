import concurrent.futures
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path('/tmp/ai-gpu-2bfab0261c05')
REPO = ROOT / 'audit'
PACKET = REPO / 'docs/project/evidence/p06-checkpoint-publication/continued-audit'
BASE = '30b2e8ca69fba47646392c0cf6650cbb75155843'
def digest(data):
    return hashlib.sha256(data).hexdigest()
def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()
def git(*args):
    return subprocess.check_output(['/usr/bin/git', *args], cwd=REPO)
def snapshot():
    files = [REPO / 'docs/project/p06-qualified-warm-handoff.md'] + sorted(p for p in PACKET.rglob('*') if p.is_file())
    records = []
    for p in files:
        assert not p.is_symlink(), p
        data = p.read_bytes()
        records.append({'path': str(p.relative_to(REPO)), 'size_bytes': len(data), 'sha256': digest(data), 'mode': oct(p.stat().st_mode & 0o777)})
    payload = json.dumps(records,sort_keys=True,separators=(',', ':')).encode() + b'\n'
    return {'at_utc': now(), 'head': git('rev-parse', 'HEAD').decode().strip(),
        'tree': git('rev-parse', 'HEAD^{tree}').decode().strip(),
        'status': git('status','--porcelain=v1','--untracked-files=all').decode(),
        'index_sha256': digest(Path(git('rev-parse','--path-format=absolute','--git-path','index').decode().strip()).read_bytes()),
        'audit_file_count': len(records), 'audit_file_bytes': sum(r['size_bytes'] for r in records),
        'audit_inventory_sha256': digest(payload), 'audit_inventory': records,
        'ledger_completed_reports': json.loads((PACKET/'agent-ledger.json').read_text())['completed_reports']}
python = str(Path(shutil.which('python3')).absolute())
environment = {'PATH': str(Path(python).parent)+':/usr/bin:/bin', 'LANG':'C', 'LC_ALL':'C', 'TZ':'UTC', 'PYTHONUTF8':'1', 'PYTHONDONTWRITEBYTECODE':'1'}
before = snapshot()
assert before['head'] == BASE
identities = []
for path in ['ci/project/check_project.py', 'ci/project/check_baseline_packets.py', '.github/workflows/project-governance.yml', 'ci/change_impact.py', 'docs/review/change-impact.yaml', 'docs/review/code-review-policy.md']:
    body = (REPO/path).read_bytes()
    baseline = git('show', f'{BASE}:{path}')
    assert body == baseline, path
    identities.append({'path':path,'bytes':len(body),'sha256':digest(body),'equals_immutable_base':True})
runtime = {'python':python,'python_resolved':str(Path(python).resolve()),'python_sha256':digest(Path(python).resolve().read_bytes()),'python_version':subprocess.check_output([python,'--version'],env=environment).decode().strip(),'git_resolved':'/usr/bin/git','git_sha256':digest(Path('/usr/bin/git').read_bytes())}
def execute(name, script):
    command = [python, '-B', script]
    start = now(); timer = time.monotonic()
    result = subprocess.run(command,cwd=REPO,env=environment,capture_output=True,check=False,timeout=120)
    elapsed = time.monotonic() - timer
    stdout = ROOT/f'a097-{name}.stdout.log'
    stderr = ROOT/f'a097-{name}.stderr.log'
    stdout.write_bytes(result.stdout); stderr.write_bytes(result.stderr)
    return {'command':command,'cwd':str(REPO),'start_utc':start,'end_utc':now(),'elapsed_seconds':elapsed,'exit_code':result.returncode,
        'stdout':{'filename':stdout.name,'bytes':len(result.stdout),'sha256':digest(result.stdout),'text':result.stdout.decode()},
        'stderr':{'filename':stderr.name,'bytes':len(result.stderr),'sha256':digest(result.stderr),'text':result.stderr.decode()}}
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
    commands=list(pool.map(lambda pair: execute(*pair), [('project','ci/project/check_project.py'),('baseline-packets','ci/project/check_baseline_packets.py')]))
after = snapshot()
stable_keys = ['head','tree','status','index_sha256','audit_file_count','audit_file_bytes','audit_inventory_sha256','ledger_completed_reports']
stable = {key:before[key] == after[key] for key in stable_keys}
result = {'schema_version':1,'scope':'audit-documentation-metadata-validators-only','base_revision':BASE,'runtime':runtime,'environment':environment,'commands':commands,'validator_policy_identities':identities,'before':before,'after':after,'stability':stable,'all_stable':all(stable.values()),'all_commands_succeeded':all(x['exit_code']==0 for x in commands),
    'suite_tests_executed':False,'native_execution':False,'full_governance_qualification':False,
    'classification':{'whole_uncommitted_diff_supported':False,'reason':'classify requires --base and --head resolving to Git commit objects; Repo.changes reads their immutable object diff. New packet remains untracked. No commit or index mutation performed.','path_rule_advisory':'All changed paths under docs/project/** match prose R0, excluding docs/designs/** and docs/review/**; exact committed detector/evidence classification remains required.','required_after_commit_command':'python3 -B <immutable-base-ci/change_impact.py> --repo <audit-repository> --policy <immutable-base-change-impact.yaml> classify --base '+BASE+' --head <audit-commit> --event push --format json'}}
(ROOT/'a097-audit-validation.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'validators':[{ 'exit_code': x['exit_code'], 'command':x['command'], 'stdout':x['stdout']['text'], 'stderr':x['stderr']['text']} for x in commands], 'stable':stable,'snapshot_files':before['audit_file_count'],'snapshot_bytes':before['audit_file_bytes'],'completed_reports':before['ledger_completed_reports']}))
