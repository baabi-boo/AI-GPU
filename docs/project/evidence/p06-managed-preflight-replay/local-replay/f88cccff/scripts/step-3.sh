set -euo pipefail
python3 -I - <<'PY' 2>&1 | tee "$P06_MANAGED_REPLAY_ROOT/evidence/failed-control.log"
import json, os, subprocess, sys
from pathlib import Path
native = Path.cwd() / 'docs/project/evidence/p06-managed-preflight/native'
command = [sys.executable, 'ci/project/p06_managed_preflight_replay.py',
    '--archive', str(native / 'run-45084009157-attempt1.zip'),
    '--sha256', '4f1e177ba930c132f5e8cc7558b3087d39789c346763f00a9d1bdd2a6d17d00c',
    '--source-revision', '8756f40029e59c87546fa22f4da33acd4e5d8e02',
    '--source-inventory', str(native / 'source-inventory-8756f400-replay.json'),
    '--source-inventory-sha256', '57a1290e4cadb7e357d109b49ff7e2ee85459c42b9a54d9522e1e178f3323c30',
    '--source-derivation', str(native / 'source-derivation-8756f400-replay.json'),
    '--source-derivation-sha256', '492b142b047e71a84a62425aebf5d46bb35f2ec022a173d42d6463e04fe834b8']
result = subprocess.run(command, text=True, capture_output=True, timeout=120)
evidence = Path(os.environ['P06_MANAGED_REPLAY_ROOT']) / 'evidence'
(evidence / 'failed-original.stdout').write_text(result.stdout, encoding='utf-8')
(evidence / 'failed-original.stderr').write_text(result.stderr, encoding='utf-8')
def unique_pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Duplicate key in failed-original result: ' + key)
        value[key] = item
    return value
data = json.loads(result.stdout, object_pairs_hook=unique_pairs)
expected = {'contract_id': 'p06-managed-counter-preflight-replay-v1', 'outcome': 'fail',
    'reason': 'report.outcome: value differs', 'native_execution': 'not_run',
    'retained_code_executed': False, 'dependency_compilation_provenance_verified': False,
    'qualified': False, 'ready_for_warm': False, 'warm_execution': False,
    'full_warm_coverage': False, 'acceptance_claimed': False,
    'phase_acceptance': False, 'performance_acceptance': False}
if (result.returncode != 1 or result.stderr or type(data) is not dict
        or set(data) != set(expected)
        or any(type(data[key]) is not type(value) or data[key] != value
               for key, value in expected.items())):
    raise SystemExit('Failed original did not reach its required semantic rejection')
(evidence / 'failed-control.json').write_text(json.dumps({
    'outcome': 'pass', 'scope': 'original-failure-rejection-control',
    'replay_exit_code': result.returncode, 'replay': data,
    'native_execution': 'not_run', 'acceptance_claimed': False}, indent=2) + '\n', encoding='utf-8')
print('Original failed archive rejected at report.outcome; no acceptance or native execution')
PY
