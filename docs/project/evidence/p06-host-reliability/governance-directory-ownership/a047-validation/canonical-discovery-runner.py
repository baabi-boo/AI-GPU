"""Inventory the canonical suite in a fresh process without executing tests."""
import ast
from collections import Counter
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import unittest
from unittest import mock

ROOT = Path('/tmp/ai-gpu-b4f42b8a9d4b/repo')
OUT = ROOT.parent / 'a047-validation'
PRIOR = ROOT.parent / 'a039-validation/canonical-discovery.json'
NEW_MODULE = 'test_governance_directory_ownership'
MINIMUM = 1024 ** 3


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def ids_digest(identities):
    return digest(''.join(identity + '\n' for identity in identities).encode())


def sources():
    return {str(path.relative_to(ROOT)): {'sha256': digest(path.read_bytes()),
                                        'size_bytes': path.stat().st_size}
            for path in sorted((ROOT / 'ci/project').glob('*.py'))}


def flatten(suite):
    if isinstance(suite, unittest.TestSuite):
        for item in suite:
            yield from flatten(item)
    else:
        yield suite.id()


def block_execution(*args, **kwargs):
    execution_attempts.append('unittest execution attempted during discovery')
    raise RuntimeError(execution_attempts[-1])


os.chdir(ROOT)
started = datetime.now(timezone.utc).isoformat()
head_before = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
disk_before = shutil.disk_usage('/tmp').free
if disk_before < MINIMUM:
    raise SystemExit('A047 canonical discovery blocked: /tmp below 1 GiB')
before = sources()
prior_raw = PRIOR.read_bytes()
prior = json.loads(prior_raw)
base_ids = prior['test_ids']
base_set = set(base_ids)
new_ast = ast.parse((ROOT / 'ci/project' / (NEW_MODULE + '.py')).read_bytes())
expected_new_ids = sorted(
    f'{NEW_MODULE}.{node.name}.{method.name}'
    for node in new_ast.body if isinstance(node, ast.ClassDef)
    for method in node.body
    if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
    and method.name.startswith('test_'))
execution_attempts = []
loader = unittest.TestLoader()
start = time.monotonic()
with ExitStack() as stack:
    for owner, method in ((unittest.TestCase, 'run'),
                          (unittest.TestCase, 'debug'),
                          (unittest.TestCase, '_callTestMethod'),
                          (unittest.TestSuite, 'run'),
                          (unittest.TestSuite, 'debug'),
                          (unittest.BaseTestSuite, 'run'),
                          (unittest.TextTestRunner, 'run'),
                          (unittest.TestProgram, 'runTests')):
        stack.enter_context(mock.patch.object(owner, method, block_execution))
    test_prefix = str(ROOT / 'ci/project/test_')
    new_file = str(ROOT / 'ci/project' / (NEW_MODULE + '.py'))
    def no_test_bodies(frame, event, arg):
        if event != 'call':
            return
        filename, name = frame.f_code.co_filename, frame.f_code.co_name
        if ((filename.startswith(test_prefix) and name.startswith('test_'))
                or (filename == new_file and name == '_probe')):
            execution_attempts.append(filename + ':' + name)
            raise RuntimeError('test body or new probe attempted during discovery')
    previous_profile = sys.getprofile()
    sys.setprofile(no_test_bodies)
    try:
        suite = loader.discover('ci/project', pattern='test_*.py')
        identities = list(flatten(suite))
    finally:
        sys.setprofile(previous_profile)
elapsed = time.monotonic() - start
after = sources()
disk_after = shutil.disk_usage('/tmp').free
head_after = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
current_set = set(identities)
added = [identity for identity in identities if identity not in base_set]
removed = [identity for identity in base_ids if identity not in current_set]
duplicates = {identity: count for identity, count in Counter(identities).items() if count != 1}
failed = [identity for identity in identities if identity.startswith('unittest.loader._FailedTest.')]
changed = [name for name in sorted(set(before) | set(after))
           if before.get(name) != after.get(name)]
checks = {
    'prior_count_5568': len(base_ids) == len(base_set) == prior['count'] == 5568,
    'prior_digest_matches': ids_digest(base_ids) == prior['ids_sha256'],
    'exact_new_ids_only': sorted(added) == expected_new_ids,
    'exact_current_count_5575': len(identities) == len(current_set) == 5575,
    'new_method_count_seven': len(expected_new_ids) == 7,
    'no_removals': not removed,
    'base_relative_order_preserved': [identity for identity in identities if identity in base_set] == base_ids,
    'no_duplicates': not duplicates,
    'no_loader_errors': not loader.errors,
    'no_failed_placeholders': not failed,
    'no_test_execution_attempts': not execution_attempts,
    'source_bytes_stable': not changed,
    'head_stable': head_before == head_after,
    'bytecode_disabled': sys.dont_write_bytecode and os.environ.get('PYTHONDONTWRITEBYTECODE') == '1',
    'tmp_reserve_preserved': min(disk_before, disk_after) >= MINIMUM,
}
receipt = {
    'schema_version': 1, 'assignment': 'a047',
    'scope': 'canonical-discovery-only in isolated child process; no test bodies executed',
    'command': 'PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=ci/project python3 -B /tmp/ai-gpu-b4f42b8a9d4b/a047-validation/canonical-discovery-runner.py',
    'started_utc': started, 'ended_utc': datetime.now(timezone.utc).isoformat(),
    'elapsed_seconds': elapsed, 'head_before': head_before, 'head_after': head_after,
    'python_version': sys.version,
    'discovery': {'start_dir': 'ci/project', 'pattern': 'test_*.py',
                  'top_level_dir': 'default (same as start_dir)', 'filter': None},
    'count': len(identities), 'unique_count': len(current_set),
    'ids_sha256': ids_digest(identities), 'test_ids': identities,
    'baseline': {'path': str(PRIOR), 'sha256': digest(prior_raw),
                 'count': len(base_ids), 'ids_sha256': ids_digest(base_ids)},
    'added_ids': added, 'removed_ids': removed,
    'expected_ast_new_ids': expected_new_ids,
    'duplicate_ids': duplicates, 'loader_errors': list(loader.errors),
    'failed_placeholders': failed, 'execution_attempts': execution_attempts,
    'source_snapshot_count': len(before), 'source_before_file': 'source-before.json',
    'source_after_file': 'source-after-discovery.json',
    'source_before_sha256': digest(json.dumps(before, sort_keys=True).encode()),
    'source_after_sha256': digest(json.dumps(after, sort_keys=True).encode()),
    'changed_source_files': changed,
    'tmp_free_before_bytes': disk_before, 'tmp_free_after_bytes': disk_after,
    'tmp_reserve_bytes': MINIMUM, 'checks': checks,
    'outcome': 'pass' if all(checks.values()) else 'fail',
    'limitations': 'Discovery imports trusted source. It is not suite execution, strict governance, native admission or phase acceptance.',
}
(OUT / 'source-before.json').write_text(json.dumps(before, indent=2, sort_keys=True) + '\n')
(OUT / 'source-after-discovery.json').write_text(json.dumps(after, indent=2, sort_keys=True) + '\n')
(OUT / 'canonical-discovery.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
summary = {key: receipt[key] for key in ('count', 'unique_count', 'ids_sha256', 'elapsed_seconds', 'outcome')}
summary.update({'additions': len(added), 'removals': len(removed),
                'python_sources_observed': len(before),
                'failed_checks': [key for key, value in checks.items() if not value]})
print(json.dumps(summary, sort_keys=True), flush=True)
raise SystemExit(0 if receipt['outcome'] == 'pass' else 1)
