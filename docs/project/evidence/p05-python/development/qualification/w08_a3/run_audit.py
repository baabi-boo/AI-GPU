import datetime
import hashlib
import json
from pathlib import Path
import stat
import subprocess
import sys
import time

REPO = Path('/workspace/scratch/ba0248fde989/AI-GPU')
WORK = REPO.parent / 'p05-work/w08_a3'
PACKET = REPO.parent / 'p05-work/ci-e1420fd/simx-fp16/python'
ARCHIVE = PACKET.parent.parent / 'simx-fp16.zip'
AUDITOR = REPO / 'docs/project/evidence/p05-python/reviews/audit_provenance.py'
RESULT = AUDITOR.parent / 'fp16-provenance.json'
LOG = AUDITOR.parent / 'fp16-provenance.log'
REVISION = 'e1420fd550f716df33a2556057b7086a03032cbe'
EXPECTED_AUDITOR = '4684a4e928ff672d371bdb78ab5f646b61ae59d1147c3c690e722a22a89186ac'
EXPECTED_ARCHIVE = '467122e41bee4e67f9eef285e015b2dee3a52522f0bcb3f497e3cec87e6c7380'

def digest(data):
    return hashlib.sha256(data).hexdigest()

def file_identity(path):
    assert stat.S_ISREG(path.lstat().st_mode) and not path.is_symlink()
    data = path.read_bytes()
    return {'size_bytes': len(data), 'sha256': digest(data)}

def git(*args):
    return subprocess.check_output(['git', '-C', str(REPO), *args])

manifest = json.loads((PACKET / 'artifacts/bundle/manifest.json').read_text())
source_names = [row['path'] for row in manifest['binding_sources']]
assert len(source_names) == 22

def capture():
    files = {str(path.relative_to(PACKET)): file_identity(path) for path in sorted(PACKET.rglob('*')) if path.is_file()}
    return {
        'packet_files': files,
        'packet_inventory_sha256': digest(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()),
        'archive': file_identity(ARCHIVE),
        'repository_archive': file_identity(REPO / 'docs/project/evidence/p05-python/archives/simx-fp16.zip'),
        'auditor': file_identity(AUDITOR),
        'binding_sources_live': {name: file_identity(REPO / name) for name in source_names},
        'recorded_source_git_blobs': {name: digest(git('show', REVISION + ':' + name)) for name in source_names},
        'head': git('rev-parse', 'HEAD').decode().strip(),
        'head_tree': git('rev-parse', 'HEAD^{tree}').decode().strip(),
        'recorded_revision_tree': git('rev-parse', REVISION + '^{tree}').decode().strip(),
    }

before = capture()
assert before['auditor']['sha256'] == EXPECTED_AUDITOR
assert before['archive']['sha256'] == EXPECTED_ARCHIVE
assert before['repository_archive'] == before['archive']
assert len(before['packet_files']) == 206
for row in manifest['binding_sources']:
    assert before['recorded_source_git_blobs'][row['path']] == row['sha256']
    assert before['binding_sources_live'][row['path']] == {'sha256': row['sha256'], 'size_bytes': row['size']}
command = [sys.executable, '-B', str(AUDITOR), '--source-dir', str(REPO), '--packet', str(PACKET), '--selected-scope', '--output', str(RESULT)]
start = time.monotonic()
started = datetime.datetime.now(datetime.timezone.utc).isoformat()
with LOG.open('xb') as stream:
    child = subprocess.run(command, cwd=REPO, stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT, timeout=180, check=False)
elapsed = time.monotonic() - start
after = capture()
result = json.loads(RESULT.read_text())
receipt = {
    'scope': 'W08 A3 selected FP16 retained-data provenance audit; no native/package code execution or gate acceptance',
    'command': command, 'cwd': str(REPO), 'started_at': started, 'elapsed_seconds': elapsed,
    'exit_code': child.returncode, 'before': before, 'after': after, 'identities_stable': before == after,
    'result': {'path': str(RESULT.relative_to(REPO)), **file_identity(RESULT)},
    'log': {'path': str(LOG.relative_to(REPO)), **file_identity(LOG)},
    'audit_outcome': result['outcome'], 'audit_scope': result.get('scope'), 'full_matrix': result['full_matrix'],
}
(WORK / 'execution.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
assert child.returncode == 0 and result['outcome'] == 'pass'
assert result['full_matrix'] is False and result['scope'] == 'incomplete_selected_format_matrix'
assert before == after
print(json.dumps({key: receipt[key] for key in ('exit_code', 'elapsed_seconds', 'identities_stable', 'audit_outcome', 'audit_scope', 'full_matrix')}))
