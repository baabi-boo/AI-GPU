import datetime
import hashlib
import json
import os
from pathlib import Path
from collections import Counter
import shutil
import subprocess
import sys
import time
import unittest

ROOT = Path('/tmp/ai-gpu-b4f42b8a9d4b/repo')
OUT = Path('/tmp/ai-gpu-b4f42b8a9d4b/a039-validation')
OUT.mkdir(exist_ok=False)
MODULES = ['test_p06_qualified_warm_encrypt',
           'test_p06_encrypt_descriptor_closeout',
           'test_p06_encrypt_operational_failures',
           'test_p06_encrypt_publication_review',
           'test_p06_encrypt_final_directory',
           'test_p06_encrypt_sigterm_closeout',
           'test_p06_encrypt_reader_ownership']
FILES = ['ci/project/p06_qualified_warm_encrypt.py'] + [
    f'ci/project/{name}.py' for name in MODULES]
MINIMUM = 1024 ** 3
minimum_free = shutil.disk_usage('/tmp').free
resource_failure = False
active_result = None

class ReserveStop(BaseException):
    pass

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
        global active_result
        super().__init__(*args, **kwargs)
        active_result = self
        self.ids = []
        self.successes = 0
        self.subtests = 0
        self.successful_subtests = 0
        self.subtest_events = []

    def startTest(self, test):
        if disk() < MINIMUM:
            print('RESOURCE FAILURE: /tmp below 1 GiB', flush=True)
            self.stop()
            raise ReserveStop()
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
        self.subtest_events.append({'parent_id': test.id(), 'id': subtest.id(),
                                    'outcome': 'success' if err is None else 'failure_or_error'})
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
    raise SystemExit('A039 blocked: /tmp below 1 GiB before suite')
loader = unittest.TestLoader()
suite = loader.loadTestsFromNames(MODULES)
def flatten(node):
    if isinstance(node, unittest.TestSuite):
        for child in node:
            yield from flatten(child)
    else:
        yield node.id()
expected_ids = list(flatten(suite))
expected_tests = suite.countTestCases()
save('focused-discovered.json', {'count': expected_tests, 'ids': expected_ids,
     'unique_count': len(set(expected_ids)), 'loader_errors': list(loader.errors)})
start = time.monotonic()
print(f'A039 beginning combined focused suite ({expected_tests} tests)', flush=True)
with (OUT / 'focused-tests.log').open('w') as stream:
    try:
        result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=CountResult).run(suite)
    except ReserveStop:
        result = active_result
        stream.write('\nStopped before starting a test below the 1 GiB temporary reserve.\n')
elapsed = time.monotonic() - start
after_suite = snapshot()
save('source-after-suite.json', after_suite)
test_result = {
    'modules': MODULES, 'expected_tests': expected_tests, 'tests_run': result.testsRun,
    'unique_test_ids': len(set(result.ids)), 'successful_tests': result.successes,
    'duplicate_test_ids': {k: v for k, v in Counter(result.ids).items() if v != 1},
    'discovered_ids_match_execution_order': expected_ids == result.ids,
    'loader_errors': list(loader.errors),
    'tests_by_module': dict(sorted(Counter(i.split('.')[0] for i in result.ids).items())),
    'subtests_by_module': dict(sorted(Counter(e['parent_id'].split('.')[0] for e in result.subtest_events).items())),
    'subtests': result.subtests, 'successful_subtests': result.successful_subtests,
    'failures': len(result.failures), 'errors': len(result.errors),
    'skips': len(result.skipped), 'expected_failures': len(result.expectedFailures),
    'unexpected_successes': len(result.unexpectedSuccesses), 'elapsed_seconds': elapsed,
    'ids': result.ids,
    'failure_ids': [test.id() for test, _ in result.failures],
    'error_ids': [test.id() for test, _ in result.errors],
    'skip_events': [{'id': test.id(), 'reason': reason} for test, reason in result.skipped],
}
save('focused-result.json', test_result)
save('subtest-events.json', result.subtest_events)
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
    'schema_version': 1, 'assignment': 'a039',
    'scope': 'One source-scoped sequential focused host suite and metadata checks; no strict governance or native execution.',
    'head_before': head, 'head_after': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
    'started_utc': started, 'ended_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'python_version': sys.version, 'cwd': str(ROOT),
    'environment': {'sys_dont_write_bytecode': sys.dont_write_bytecode,
                    'PYTHONDONTWRITEBYTECODE': os.environ.get('PYTHONDONTWRITEBYTECODE'),
                    'PYTHONPATH': os.environ.get('PYTHONPATH')},
    'suite_command': 'PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=ci/project python3 -B /tmp/ai-gpu-b4f42b8a9d4b/a039-run.py',
    'test_result': 'focused-result.json', 'checks': checks,
    'source_snapshot_count': len(FILES), 'source_changes_during_checks': changed,
    'tmp_free_minimum_observed_bytes': minimum_free,
    'tmp_free_final_bytes': disk(), 'tmp_reserve_bytes': MINIMUM,
    'tmp_sampling': 'Before and after each test, each reported subtest, and each metadata command.',
    'resource_failure': resource_failure,
    'outcome': 'pass' if result.wasSuccessful() and result.testsRun == expected_tests == len(set(result.ids)) and expected_ids == result.ids and not loader.errors and not result.skipped and not result.expectedFailures and not result.unexpectedSuccesses and sys.dont_write_bytecode and os.environ.get('PYTHONDONTWRITEBYTECODE') == '1' and not changed and not resource_failure and len(checks) == 3 and all(x['exit_code'] == 0 for x in checks) else 'fail',
}
save('receipt.json', receipt)
print(json.dumps(receipt, sort_keys=True), flush=True)
raise SystemExit(0 if receipt['outcome'] == 'pass' else 1)
