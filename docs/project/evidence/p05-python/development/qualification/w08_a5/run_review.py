"""Execute the exact retained-data auditor and preserve source/input identities."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

REPO = Path('/workspace/scratch/ba0248fde989/AI-GPU')
WORK = REPO.parent / 'p05-work/w08_a5'
PACKET = REPO.parent / 'p05-work/ci-e1420fd/simx-bf16/python'
ZIP = PACKET.parent.parent / 'simx-bf16.zip'
AUDITOR = REPO / 'docs/project/evidence/p05-python/reviews/audit_dispatch.py'
OUTPUT = AUDITOR.parent / 'bf16-dispatch.json'
LOG = AUDITOR.parent / 'bf16-dispatch.log'
EXPECTED = 'ab0a1d1d6d0268b0766e5d3bc211e2830efb5e9683a413854fc1a16a3d5de391'

def digest(body): return hashlib.sha256(body).hexdigest()
def file(path):
    body = path.read_bytes()
    return {'sha256': digest(body), 'size_bytes': len(body)}
def canonical(value): return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()

tree = ast.parse(AUDITOR.read_text())
constants = {}
for node in tree.body:
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in ('NATIVE_PINS', 'ALLOCATOR_PINS', 'FIXTURES', 'HELPER'):
                constants[target.id] = (ast.literal_eval(node.value) if target.id == 'HELPER'
                                        else [ast.literal_eval(key) for key in node.value.keys])
paths = sorted(set(constants['NATIVE_PINS']) | set(constants['ALLOCATOR_PINS']) |
               set(constants['FIXTURES']) | {constants['HELPER'], 'profiles/p02-tfr.json'})

def capture():
    entries = {str(p.relative_to(PACKET)): file(p) for p in sorted(PACKET.rglob('*')) if p.is_file()}
    source = {name: file(REPO / name) for name in paths}
    pins = {}
    for name in paths:
        body = subprocess.check_output(['git', 'show', 'e1420fd550f716df33a2556057b7086a03032cbe:' + name], cwd=REPO)
        pins[name] = {'sha256': digest(body), 'size_bytes': len(body)}
    assert source == pins
    return {'auditor': file(AUDITOR), 'zip': file(ZIP), 'packet_members': entries,
            'packet_inventory_sha256': digest(canonical(entries)), 'supporting_sources': source,
            'git': subprocess.check_output(['git', 'rev-parse', 'HEAD', 'HEAD^{tree}'], cwd=REPO, text=True).splitlines()}

before = capture()
assert before['auditor']['sha256'] == EXPECTED and len(before['packet_members']) == 206
command = [sys.executable, '-B', str(AUDITOR), '--source-dir', str(REPO),
           '--packet', str(PACKET), '--selected-scope', '--output', str(OUTPUT)]
start = time.monotonic()
with LOG.open('xb') as stream:
    run = subprocess.run(command, cwd=REPO, stdin=subprocess.DEVNULL, stdout=stream,
                         stderr=subprocess.STDOUT, timeout=60, check=False)
elapsed = time.monotonic() - start
after = capture()
receipt = {'scope': 'W08 A5 independent BF16 retained-data dispatch review; no native execution',
           'command': command, 'cwd': str(REPO), 'exit_code': run.returncode,
           'elapsed_seconds': elapsed, 'before': before, 'after': after,
           'inputs_stable': before == after, 'output': file(OUTPUT), 'log': file(LOG),
           'acceptance_claimed': False}
(WORK / 'execution.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
assert before == after and run.returncode == 0
result = json.loads(OUTPUT.read_text())
assert result['outcome'] == 'pass' and result['phase_acceptance'] is False
print(json.dumps({'exit_code': run.returncode, 'elapsed_seconds': elapsed,
                  'outcome': result['outcome'], 'counts': result['counts'],
                  'input_files': len(before['packet_members']), 'supporting_sources': len(paths)}, indent=2))
