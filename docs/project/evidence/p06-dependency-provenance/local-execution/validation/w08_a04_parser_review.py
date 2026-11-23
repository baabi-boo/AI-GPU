import ast
from copy import deepcopy
import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path('/workspace/ai-gpu-next')
OUT = Path('/workspace/scratch/279b6658611e/validation')
ORIGINAL = Path('/workspace/p06-local-native-run-03/evidence/native-lifetime/report.json')
PIN = 'bba2af32da50326b43c0225f63478a3003865a6fc34eaef2e79b9228697a56d0'
DEP = '202ee0fb2d79d4c47380e41dfb9356a2f353c36f977348442111461d2ffb4924'
REV = '7251f078972c1d524de06d069e91b014b55896f5'
FILES = ['baseline_packet_io.py', 'p06_dependency_contract.py', 'p06_dependency_local_execute.py', 'p06_pending_probe.py', 'p06_dependency_substitution.py', 'test_p06_managed_report_json_review.py']
sys.path.insert(0, str(ROOT / 'ci/project'))

def identity(path):
    body = path.read_bytes()
    return {'sha256': hashlib.sha256(body).hexdigest(), 'size_bytes': len(body)}

if len(sys.argv) == 3 and sys.argv[1] == '--helpers':
    import p06_pending_probe as probe
    if sys.argv[2] == 'substitution':
        import p06_dependency_substitution
    events = []
    def hook(event, args):
        if event in ('subprocess.Popen', 'os.system', 'os.exec', 'os.posix_spawn', 'socket.connect'):
            events.append(event)
            raise RuntimeError('prohibited event: ' + event)
    sys.addaudithook(hook)
    document = probe.managed_json(ORIGINAL, dependency_receipt_sha256=DEP)
    assert probe.managed_mode(document, expected_revision=REV, dependency_receipt_sha256=DEP) is True
    print(json.dumps({'helper_paths': [r['path'] for r in probe.preflight.loaded_helpers()], 'prohibited_events': events}))
    sys.exit(0)

started = time.monotonic()
source_before = {name: identity(ROOT / 'ci/project' / name) for name in FILES}
original_before = identity(ORIGINAL)
assert original_before['sha256'] == PIN
revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
assert revision == REV
helper_runs = {}
for mode in ('pending', 'substitution'):
    child = subprocess.run([sys.executable, '-B', __file__, '--helpers', mode], cwd=ROOT, capture_output=True, text=True, check=True)
    helper_runs[mode] = json.loads(child.stdout)

import baseline_packet_io as packet
import p06_dependency_contract as contract
import p06_dependency_control_replay as control_replay
import p06_dependency_local_execute as execute
import p06_pending_probe as probe
assert helper_runs['pending']['helper_paths'] == sorted(control_replay.PROBE_HELPERS)
assert helper_runs['substitution']['helper_paths'] == sorted(control_replay.SUBSTITUTION_HELPERS)

body = ORIGINAL.read_bytes()
quoted = escaped = False
tokens = depth = max_depth = 0
for character in body.decode('utf-8'):
    if quoted:
        if escaped:
            escaped = False
        elif character == '\\':
            escaped = True
        elif character == '"':
            quoted = False
    elif character == '"':
        quoted = True
        tokens += 1
    elif character in '[{':
        tokens += 1
        depth += 1
        max_depth = max(max_depth, depth)
    elif character in ']}':
        depth -= 1
    elif character in ',:':
        tokens += 1
assert tokens == 265793 and max_depth == 10

checks = []
def rejected(name, function):
    try:
        function()
    except ValueError as error:
        checks.append({'name': name, 'outcome': 'rejected', 'reason': str(error)})
    else:
        raise AssertionError(name + ' unexpectedly accepted')

events = []
def hook(event, args):
    if event in ('subprocess.Popen', 'os.system', 'os.exec', 'os.posix_spawn', 'socket.connect'):
        events.append(event)
        raise RuntimeError('prohibited event: ' + event)
sys.addaudithook(hook)
rejected('generic_actual_report', lambda: packet.load_json_bytes(body))
rejected('historical_control_actual_report', lambda: probe.managed_json(ORIGINAL))
document = packet.load_json_bytes(body, max_tokens=contract.MANAGED_REPORT_MAX_JSON_TOKENS)
execute.validate_stage_report('native-lifetime', document, REV, DEP)
assert probe.managed_json(ORIGINAL, dependency_receipt_sha256=DEP) == document
assert probe.managed_mode(document, expected_revision=REV, dependency_receipt_sha256=DEP) is True
checks.append({'name': 'explicit_actual_native_and_control_intake', 'outcome': 'pass'})
rejected('wrong_revision', lambda: probe.managed_mode(document, expected_revision='0' * 40, dependency_receipt_sha256=DEP))
rejected('wrong_receipt', lambda: probe.managed_mode(document, expected_revision=REV, dependency_receipt_sha256='0' * 64))
mutations = [
    ('wrong_contract', lambda d: d.update(contract_id='p06-managed-counter-lifetime-v1')),
    ('missing_process', lambda d: d['processes'].pop()),
    ('reordered_processes', lambda d: d['processes'].reverse()),
    ('wrong_count', lambda d: d['completed_counts'].update(launches=131)),
    ('bool_count', lambda d: d['completed_counts'].update(processes=True)),
]
mutations += [(name, lambda d, key=name: d.update({key: True})) for name in contract.FALSE_CLAIMS]
for name, mutate in mutations:
    changed = deepcopy(document)
    mutate(changed)
    rejected(name, lambda d=changed: probe.managed_mode(d, expected_revision=REV, dependency_receipt_sha256=DEP))
assert identity(ORIGINAL) == original_before
assert {name: identity(ROOT / 'ci/project' / name) for name in FILES} == source_before
assert events == [] and all(value['prohibited_events'] == [] for value in helper_runs.values())
log = OUT / 'w08_a04-parser-tests.log'
log_text = log.read_text()
assert 'Ran 52 tests' in log_text and '\nOK\n' in log_text
result = {
    'schema_version': 1,
    'reviewer': 'w08_a04',
    'outcome': 'pass',
    'finding_count_f2_f3': 0,
    'source_base_revision': revision,
    'source_scope': 'Exact six file identities in an uncommitted correction over source_base_revision',
    'source_files_before_and_after': source_before,
    'source_files_unchanged': True,
    'original': {'path': str(ORIGINAL), **original_before, 'unchanged': True},
    'actual_structural_tokens': tokens,
    'actual_maximum_depth': max_depth,
    'generic_token_budget': packet.MAX_JSON_TOKENS,
    'explicit_managed_token_budget': contract.MANAGED_REPORT_MAX_JSON_TOKENS,
    'byte_limit_unchanged': contract.MAX_RECEIPT_BYTES,
    'depth_limit_unchanged': packet.MAX_JSON_DEPTH,
    'number_char_limit_unchanged': packet.MAX_NUMBER_CHARS,
    'checks': checks,
    'helper_closures': {name: {'count': len(value['helper_paths']), 'matches_reader_inventory': True, 'prohibited_events': value['prohibited_events']} for name, value in helper_runs.items()},
    'test_run': {'command': 'PYTHONPATH=ci/project python3 -B -m unittest test_baseline_packet_io test_p06_managed_report_json_review -v', 'tests': 52, 'existing_baseline_tests': 42, 'new_regressions': 10, 'duration_seconds': 0.746, 'exit_code': 0, 'log': log.name, **identity(log)},
    'native_execution': 'not_run',
    'retained_code_executed': False,
    'prohibited_events': events,
    'qualification_claims': dict.fromkeys(contract.FALSE_CLAIMS, False),
    'completed_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'duration_seconds': round(time.monotonic() - started, 6),
}
(OUT / 'w08_a04-parser-review.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
print(json.dumps({'outcome': result['outcome'], 'checks': len(checks), 'helper_closures': result['helper_closures'], 'duration_seconds': result['duration_seconds']}))
