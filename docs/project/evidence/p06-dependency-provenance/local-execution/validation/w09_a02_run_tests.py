import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path('/workspace/ai-gpu-next')
OUT = Path('/workspace/scratch/279b6658611e/validation')
selection = sys.argv[1]
groups = {
    'preparation': (
        ['test_p06_dependency_prepare', 'test_p06_dependency_prepare_cache_review'],
        ['ci/project/p06_dependency_prepare.py', 'ci/project/test_p06_dependency_prepare.py',
         'ci/project/test_p06_dependency_prepare_cache_review.py', 'ci/project/baseline_inventory.py',
         'ci/project/p02_matrix.py', 'ci/project/preflight.py']),
    'guards': (
        ['test_p06_dependency_native_replay.InertSourceGuardTests',
         'test_p06_dependency_native_replay.CompleteSyntheticNativeTests.test_hosted_zip_bridge_replays_native_semantics_with_synthetic_dependency_boundary',
         'test_p06_dependency_control_replay.SeparateControlReplayTests.test_zip_bridge_runs_all_native_and_control_semantics_without_execution',
         'test_p06_dependency_local_replay.LocalDependencyReplayTests.test_complete_local_archive_reuses_native_and_both_control_semantics_inertly'],
        ['ci/project/test_p06_dependency_native_replay.py', 'ci/project/test_p06_dependency_control_replay.py',
         'ci/project/test_p06_dependency_local_replay.py', 'ci/project/p06_dependency_prepare.py',
         'ci/project/p06_dependency_native_replay.py', 'ci/project/p06_dependency_control_replay.py',
         'ci/project/p06_dependency_local_replay.py']),
}
modules, names = groups[selection]
def identity(path):
    body = path.read_bytes()
    return {'sha256': hashlib.sha256(body).hexdigest(), 'size_bytes': len(body)}
def sources():
    return {name: identity(ROOT / name) for name in names}
before = sources()
argv = [sys.executable, '-B', '-m', 'unittest', '-v', *modules]
env = dict(os.environ, PYTHONPATH=str(ROOT / 'ci/project'), PYTHONDONTWRITEBYTECODE='1')
log = OUT / ('w09_a02-' + selection + '-tests.log')
receipt = {'schema_version': 1, 'scope': 'Independent focused hosted-boundary regression; no native execution',
    'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'argv': argv,
    'cwd': str(ROOT), 'base_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip(),
    'source_before': before, 'source_modifications_by_reviewer': False}
started = time.monotonic()
with log.open('xb') as stream:
    result = subprocess.run(argv, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT)
receipt.update(finished_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    exit_code=result.returncode, duration_seconds=time.monotonic() - started, source_after=sources(),
    log=dict(path=log.name, **identity(log)))
receipt['sources_unchanged'] = receipt['source_before'] == receipt['source_after']
target = OUT / ('w09_a02-' + selection + '-tests.json')
target.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
print(json.dumps({name: receipt[name] for name in ('exit_code', 'duration_seconds', 'sources_unchanged', 'log')}))
raise SystemExit(result.returncode)
