"""W08 A6 data-only execution receipt and immutable-input inventory."""
import datetime
import hashlib
import json
from pathlib import Path
import stat
import subprocess
import sys
import time

REPO = Path('/workspace/scratch/ba0248fde989/AI-GPU')
WORK = REPO.parent / 'p05-work/w08_a6'
PACKET = REPO.parent / 'p05-work/ci-e1420fd/simx-bf16/python'
AUDITOR = REPO / 'docs/project/evidence/p05-python/reviews/audit_provenance.py'
OUTPUT = AUDITOR.parent / 'bf16-provenance.json'
LOG = AUDITOR.parent / 'bf16-provenance.log'
REVISION = 'e1420fd550f716df33a2556057b7086a03032cbe'
AUDITOR_HASH = '4684a4e928ff672d371bdb78ab5f646b61ae59d1147c3c690e722a22a89186ac'
ZIP_HASH = 'e951f943ece1878f3767180c4ce2b859939722d2d639c1afb37b8a72c76006d8'

def sha(body):
    return hashlib.sha256(body).hexdigest()

def identity(path):
    assert stat.S_ISREG(path.lstat().st_mode) and not path.is_symlink()
    body = path.read_bytes()
    return {'size_bytes': len(body), 'sha256': sha(body)}

def git(*args):
    return subprocess.check_output(['git', '-C', str(REPO), *args])

manifest = json.loads((PACKET / 'artifacts/bundle/manifest.json').read_bytes())
sources = [entry['path'] for entry in manifest['binding_sources']]
assert len(sources) == 22

def capture():
    inventory = {p.relative_to(PACKET).as_posix(): identity(p)
                 for p in sorted(PACKET.rglob('*')) if p.is_file()}
    return {'packet': inventory, 'packet_inventory_sha256': sha(json.dumps(inventory, sort_keys=True, separators=(',', ':')).encode()),
            'original_zip': identity(PACKET.parent.parent / 'simx-bf16.zip'),
            'retained_zip': identity(REPO / 'docs/project/evidence/p05-python/archives/simx-bf16.zip'),
            'auditor': identity(AUDITOR), 'live_binding_sources': {name: identity(REPO / name) for name in sources},
            'recorded_git_source_hashes': {name: sha(git('show', REVISION + ':' + name)) for name in sources},
            'head': git('rev-parse', 'HEAD').decode().strip(),
            'head_tree': git('rev-parse', 'HEAD^{tree}').decode().strip(),
            'recorded_tree': git('rev-parse', REVISION + '^{tree}').decode().strip()}

before = capture()
assert before['auditor']['sha256'] == AUDITOR_HASH and before['original_zip']['sha256'] == ZIP_HASH
assert before['original_zip'] == before['retained_zip'] and len(before['packet']) == 206
for row in manifest['binding_sources']:
    assert before['live_binding_sources'][row['path']] == {'sha256': row['sha256'], 'size_bytes': row['size']}
    assert before['recorded_git_source_hashes'][row['path']] == row['sha256']
command = [sys.executable, '-B', str(AUDITOR), '--source-dir', str(REPO), '--packet', str(PACKET),
           '--selected-scope', '--output', str(OUTPUT)]
started = datetime.datetime.now(datetime.timezone.utc).isoformat()
start = time.monotonic()
with LOG.open('xb') as stream:
    completed = subprocess.run(command, cwd=REPO, stdin=subprocess.DEVNULL, stdout=stream,
                               stderr=subprocess.STDOUT, timeout=180, check=False)
duration = time.monotonic() - start
after = capture()
result = json.loads(OUTPUT.read_bytes())
receipt = {'scope': 'W08 A6 selected BF16 retained-data audit; no native execution or acceptance',
           'command': command, 'cwd': str(REPO), 'started_at': started, 'elapsed_seconds': duration,
           'exit_code': completed.returncode, 'before': before, 'after': after, 'unchanged': before == after,
           'output': {'path': str(OUTPUT), **identity(OUTPUT)}, 'log': {'path': str(LOG), **identity(LOG)},
           'audit_outcome': result['outcome'], 'scope_reported': result['scope'], 'full_matrix': result['full_matrix']}
(WORK / 'execution.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
assert completed.returncode == 0 and result['outcome'] == 'pass' and before == after
assert result['full_matrix'] is False and result['scope'] == 'incomplete_selected_format_matrix'
print(json.dumps({key: receipt[key] for key in ('exit_code', 'elapsed_seconds', 'unchanged', 'audit_outcome', 'scope_reported', 'full_matrix')}))
