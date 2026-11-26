import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import unittest

ROOT = Path('/tmp/ai-gpu-b4f42b8a9d4b/repo')
OUT = Path('/tmp/ai-gpu-b4f42b8a9d4b/a013-validation')
OUT.mkdir(exist_ok=True)
MODULES = ['test_ci_required_results', 'test_ci_submodule_checkout',
           'test_p05_bundle_descriptor_ownership', 'test_p05_bundle',
           'test_p05_bundle_producer', 'test_p05_launcher',
           'test_p05_launcher_signals', 'test_p05_ci_workflow']
FILES = [f'ci/project/{name}.py' for name in MODULES] + [
    '.github/workflows/apptainer-ci.yml', '.github/workflows/ci.yml',
    'ci/project/p05_bundle.py', 'python/vortex_ai/_bundle.py']
MINIMUM = 1024 ** 3
minimum_free = shutil.disk_usage('/tmp').free
resource_failure = False

def save(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')

def disk():
    global minimum_free, resource_failure
    free = shutil.disk_usage('/tmp').free
    minimum_free = min(minimum_free, free)
    if free < MINIMUM:
        resource_failure = True
    return free

def snapshot():
    return {name: {'sha256': hashlib.sha256((ROOT / name).read_bytes()).hexdigest(),
                   'size_bytes': (ROOT / name).stat().st_size} for name in FILES}

class CountResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ids = []
        self.successes = 0
        self.subtests = 0
        self.successful_subtests = 0

    def startTest(self, test):
        if disk() < MINIMUM:
            print('RESOURCE FAILURE: /tmp below 1 GiB', flush=True)
            self.stop()
        self.ids.append(test.id())
        super().startTest(test)

    def stopTest(self, test):
        disk()
        if resource_failure:
            self.stop()
        super().stopTest(test)

    def addSuccess(self, test):
        self.successes += 1
        super().addSuccess(test)

    def addSubTest(self, test, subtest, err):
        self.subtests += 1
        self.successful_subtests += int(err is None)
        if err is not None:
            print('SUBTEST FAILURE: ' + subtest.id(), flush=True)
        if disk() < MINIMUM:
            self.stop()
        super().addSubTest(test, subtest, err)

    def addFailure(self, test, err):
        print('TEST FAILURE: ' + test.id(), flush=True)
        super().addFailure(test, err)

    def addError(self, test, err):
        print('TEST ERROR: ' + test.id(), flush=True)
        super().addError(test, err)

os.chdir(ROOT)
started = datetime.datetime.now(datetime.timezone.utc).isoformat()
head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
before = snapshot()
save('source-before.json', before)
if disk() < MINIMUM:
    raise SystemExit('A013 blocked: /tmp below 1 GiB before suite')
suite = unittest.defaultTestLoader.loadTestsFromNames(MODULES)
expected_tests = suite.countTestCases()
start = time.monotonic()
print(f'A013 beginning combined focused suite ({expected_tests} tests)', flush=True)
with (OUT / 'focused-tests.log').open('w') as stream:
    result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=CountResult).run(suite)
elapsed = time.monotonic() - start
after_suite = snapshot()
save('source-after-suite.json', after_suite)
test_result = {
    'modules': MODULES, 'expected_tests': expected_tests, 'tests_run': result.testsRun,
    'unique_test_ids': len(set(result.ids)), 'successful_tests': result.successes,
    'subtests': result.subtests, 'successful_subtests': result.successful_subtests,
    'failures': len(result.failures), 'errors': len(result.errors),
    'skips': len(result.skipped), 'expected_failures': len(result.expectedFailures),
    'unexpected_successes': len(result.unexpectedSuccesses), 'elapsed_seconds': elapsed,
    'ids': result.ids,
    'failure_ids': [test.id() for test, _ in result.failures],
    'error_ids': [test.id() for test, _ in result.errors],
}
save('focused-result.json', test_result)
print(json.dumps({k: v for k, v in test_result.items() if k not in ('ids', 'modules')}, sort_keys=True), flush=True)
checks = []
for command, label in [
        ([sys.executable, '-B', 'ci/project/check_project.py'], 'check-project'),
        ([sys.executable, '-B', 'ci/project/check_baseline_packets.py'], 'check-baseline-packets'),
        (['git', 'diff', '--check'], 'git-diff-check')]:
    if disk() < MINIMUM:
        print('RESOURCE FAILURE: remaining checks stopped', flush=True)
        break
    start = time.monotonic()
    with (OUT / f'{label}.log').open('w') as stream:
        completed = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=False)
    checks.append({'command': command, 'exit_code': completed.returncode,
                   'elapsed_seconds': time.monotonic() - start, 'log': f'{label}.log'})
    print(f'{label}: exit {completed.returncode}', flush=True)
    disk()
after = snapshot()
save('source-after.json', after)
changed = [name for name in FILES if before[name] != after_suite[name] or before[name] != after[name]]
receipt = {
    'schema_version': 1, 'assignment': 'a013',
    'scope': 'One source-scoped sequential focused host suite and metadata checks; no strict governance or native execution.',
    'head_before': head, 'head_after': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
    'started_utc': started, 'ended_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'python_version': sys.version, 'cwd': str(ROOT),
    'environment': {'PYTHONDONTWRITEBYTECODE': os.environ.get('PYTHONDONTWRITEBYTECODE'),
                    'PYTHONPATH': os.environ.get('PYTHONPATH')},
    'suite_command': 'PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=ci/project python -B /tmp/ai-gpu-b4f42b8a9d4b/a013-run.py',
    'test_result': 'focused-result.json', 'checks': checks,
    'source_snapshot_count': len(FILES), 'source_changes_during_checks': changed,
    'tmp_free_minimum_observed_bytes': minimum_free,
    'tmp_free_final_bytes': disk(), 'tmp_reserve_bytes': MINIMUM,
    'tmp_sampling': 'Before and after each test, each reported subtest, and each metadata command.',
    'resource_failure': resource_failure,
    'outcome': 'pass' if result.wasSuccessful() and result.testsRun == expected_tests and not changed and not resource_failure and len(checks) == 3 and all(x['exit_code'] == 0 for x in checks) else 'fail',
}
save('receipt.json', receipt)
print(json.dumps(receipt, sort_keys=True), flush=True)
raise SystemExit(0 if receipt['outcome'] == 'pass' else 1)
