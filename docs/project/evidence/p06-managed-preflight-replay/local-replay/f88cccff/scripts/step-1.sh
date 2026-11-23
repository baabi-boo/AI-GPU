set -euo pipefail
python3 -I - <<'PY'
import hashlib, json, os, shutil, sys
from pathlib import Path
root = Path(os.environ['RUNNER_TEMP']) / 'p06-managed-preflight-replay'
evidence = root / 'evidence'
evidence.mkdir(parents=True, exist_ok=False)
with Path(os.environ['GITHUB_ENV']).open('a', encoding='utf-8') as stream:
    stream.write('P06_MANAGED_REPLAY_ROOT=' + str(root) + '\n')
native = Path('docs/project/evidence/p06-managed-preflight/native')
pins = {
    'run-45085300171-attempt1.zip': 'cee5be4dba875494f6eafb83484933ab7693428e4773b932a26d5b91bd17969d',
    'source-inventory-57248e73.json': '72ca7e9237060ca2831a275811d27ec6fdb3507dfd9a00b693aa177aa68382e8',
    'source-derivation-57248e73.json': '3b25d30eceeee2dc5cebd1cce8ed7ab90da0fec64857e82fc7cc7fc3ca38e171',
    'run-45084009157-attempt1.zip': '4f1e177ba930c132f5e8cc7558b3087d39789c346763f00a9d1bdd2a6d17d00c',
    'source-inventory-8756f400-replay.json': '57a1290e4cadb7e357d109b49ff7e2ee85459c42b9a54d9522e1e178f3323c30',
    'source-derivation-8756f400-replay.json': '492b142b047e71a84a62425aebf5d46bb35f2ec022a173d42d6463e04fe834b8',
}
inputs = []
for name, expected in pins.items():
    path = native / name
    digest = hashlib.sha256()
    row = {'path': path.as_posix(), 'expected_sha256': expected,
           'sha256': None, 'size_bytes': None, 'error': None}
    try:
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        row.update(sha256=digest.hexdigest(), size_bytes=path.stat().st_size)
    except OSError as error:
        row['error'] = str(error)
    inputs.append(row)
workflow = Path('.github/workflows/p06-managed-preflight-replay.yml').read_bytes()
(evidence / 'workflow.yml').write_bytes(workflow)
data = {name: os.environ[name] for name in (
    'GITHUB_SHA', 'GITHUB_EVENT_NAME', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT',
    'GITHUB_JOB', 'GITHUB_REPOSITORY', 'GITHUB_REF')}
data.update(schema_version=1, scope='managed-preflight-retained-data-replay',
    original_source_revision='57248e73dfce4ae2d21d2cbdb82c3953eef2e3db',
    failed_source_revision='8756f40029e59c87546fa22f4da33acd4e5d8e02',
    native_execution='not_run', retained_code_executed=False,
    dependency_compilation_provenance_verified=False,
    qualified=False, ready_for_warm=False, warm_execution=False,
    full_warm_coverage=False, acceptance_claimed=False,
    phase_acceptance=False, performance_acceptance=False,
    workflow_sha256=hashlib.sha256(workflow).hexdigest(), inputs=inputs,
    python_version=list(sys.version_info[:3]), implementation=sys.implementation.name,
    platform=sys.platform, executable=sys.executable, python3_on_path=shutil.which('python3'))
(evidence / 'job.json').write_text(json.dumps(data, indent=2, sort_keys=True) + '\n', encoding='utf-8')
if any(row['sha256'] != row['expected_sha256'] for row in inputs):
    raise SystemExit('Historical replay inputs differ from their independent pins')
if (data['python_version'][:2] != [3, 12] or data['implementation'] != 'cpython'
        or data['platform'] != 'linux' or data['python3_on_path'] is None
        or Path(data['python3_on_path']).resolve() != Path(sys.executable).resolve()):
    raise SystemExit('Replay requires the selected system CPython 3.12 on Linux')
PY
