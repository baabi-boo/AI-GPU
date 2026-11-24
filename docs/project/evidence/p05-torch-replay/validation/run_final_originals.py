"""Source-bound public replay of four immutable originals; no native execution."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

root = Path.cwd().resolve()
out = Path('/workspace/scratch/101d52695253/validation')
originals = out.parent / 'originals'
cases = [
    ('c6', 'c6fb039e706e812b6b3f4d2a5db1828076fe50df', 'fp16', 'd9e9a713ef716882086b6c8176d1d27c4c98acae77110c58f84bdb69a00c4aaa'),
    ('c6', 'c6fb039e706e812b6b3f4d2a5db1828076fe50df', 'bf16', '85498037f9a8b06bbb44357208f236ad325dc686934059bc472348c4524a74b3'),
    ('c0', 'c0b44ce64665fe11895f869eea8c38c9b820d6f7', 'fp16', '8c42f7e9f310972e2c0c67c56a03ce8f5460d706cb8dc3a5397435445ea6737c'),
    ('c0', 'c0b44ce64665fe11895f869eea8c38c9b820d6f7', 'bf16', '787fd1b41a27da8c100277613c581ba734920fd45b13e0707ba0f9ea2e866330'),
]

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def git(*args):
    return subprocess.check_output(['git', *args], text=True).strip()

assert not git('status', '--porcelain'), 'replay checkout must be clean'
record = {'reader_revision': git('rev-parse', 'HEAD'), 'reader_tree': git('rev-parse', 'HEAD^{tree}'),
          'source_clean_before': True, 'cwd': str(root), 'python': sys.version,
          'native_execution': 'not_run', 'phase_acceptance': False, 'replays': []}
manifests = []
for label, revision, fmt, digest in cases:
    archive = originals / ('p05-torch-' + fmt + '-' + revision[:8] + '-original.zip')
    assert sha(archive) == digest
    output = out / ('final-' + label + '-' + fmt + '-replay.json')
    stderr = out / ('final-' + label + '-' + fmt + '-replay.stderr')
    command = ['python3', '-B', 'ci/project/p05_torch_replay.py', '--archive', str(archive),
               '--sha256', digest, '--expected-revision', revision, '--format', fmt]
    start = time.monotonic()
    with output.open('w') as stdout, stderr.open('w') as errors:
        result = subprocess.run(command, stdout=stdout, stderr=errors,
                                env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}, timeout=180)
    duration = round(time.monotonic() - start, 6)
    body = json.loads(output.read_text())
    assert result.returncode == 0 and body['outcome'] == 'pass', (label, fmt, body)
    assert body['native_execution'] == 'not_run'
    for key in ('retained_code_executed', 'acceptance_claimed', 'phase_acceptance', 'host_fault_semantics_revalidated'):
        assert body[key] is False, key
    assert body['counts']['distinct_total_launches'] == 108
    assert body['archive_read']['data_files'] == 663 and len(body['archive_read']['read_files']) == 663
    assert sha(archive) == digest
    manifests.append(body['reader_sources'])
    row = {'population': label, 'execution_revision': revision, 'format': fmt,
           'command': command, 'exit_code': result.returncode, 'outcome': body['outcome'],
           'duration_seconds': duration, 'original_filename': archive.name,
           'original_sha256': digest, 'original_size_bytes': archive.stat().st_size,
           'original_digest_unchanged': True, 'output': output.name, 'output_sha256': sha(output),
           'stderr': stderr.name, 'stderr_bytes': stderr.stat().st_size,
           'counts': body['counts'], 'reader_sources': body['reader_sources']}
    record['replays'].append(row)
    print(json.dumps({k: row[k] for k in ('population', 'format', 'exit_code', 'duration_seconds')}), flush=True)
assert all(m == manifests[0] for m in manifests)
record['reader_manifests_identical'] = True
record['source_clean_after'] = not git('status', '--porcelain')
assert record['source_clean_after']
record['outcome'] = 'pass'
record['source_of_native_evidence'] = 'Original hosted execution at the selected revision; the reader performed no native work.'
(out / 'final-original-replays.json').write_text(json.dumps(record, indent=2) + '\n')
