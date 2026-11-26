#!/usr/bin/env python3
"""Record one source-bound development invocation; no qualification claims."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest

ROOT = Path('/home/agent/ai-gpu-d7ec98164a68/repo')
OUTPUT = Path('/home/agent/ai-gpu-d7ec98164a68/validation')
BASE = '81d7a35c641f3a969c23c8e604f7468a4d88644a'
MODULES = [
    'test_p06_pack_descriptor_ownership', 'test_p06_qualified_warm_pack',
    'test_p06_pack_setup_cleanup', 'test_p06_pack_operational_failures',
    'test_p06_pack_final_cleanup', 'test_p06_qualified_warm_retention',
    'test_p06_qualified_warm_retention_integration',
    'test_governance_archive_input_ownership', 'test_governance_replay_archive',
    'test_governance_replay_archive_controls', 'test_p06_workspace_runtime',
]
os.chdir(ROOT)
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'ci/project'))
OUTPUT.mkdir()

def save(name, value):
    (OUTPUT / name).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')

proof = json.loads((ROOT / 'ci/project/p06_qualified_warm_proof.json').read_text())
source_paths = set(row['path'] for row in proof['measurement_sources'])
source_paths.update(str(path.relative_to(ROOT)) for path in (ROOT / 'ci/project').rglob('*')
                    if path.is_file() and '__pycache__' not in path.parts)
source_paths.update(str(path.relative_to(ROOT)) for path in (ROOT / 'python').rglob('*')
                    if path.is_file() and '__pycache__' not in path.parts)

def inventory():
    result = {}
    for name in sorted(source_paths):
        body = (ROOT / name).read_bytes()
        result[name] = {'sha256': hashlib.sha256(body).hexdigest(), 'bytes': len(body)}
    return result

before = inventory()
save('source-before.json', before)
frozen = []
for row in proof['measurement_sources']:
    actual = before[row['path']]
    frozen.append({'path': row['path'], 'sha256': actual['sha256'],
                   'matches_proof': actual['sha256'] == row['sha256']
                    and actual['bytes'] == row['size_bytes']})
assert len(frozen) == 69 and all(row['matches_proof'] for row in frozen)
historical_name = 'ci/project/p06_counter_qualification_proof.json'
historical_before = json.loads(subprocess.check_output(
    ['git', 'show', BASE + ':' + historical_name], cwd=ROOT))
historical_after = json.loads((ROOT / historical_name).read_text())
assert len(historical_after['dependency_sources']) == 21
assert historical_before['dependency_sources'] == historical_after['dependency_sources']
save('preserved-inputs.json', {'measurement_sources': frozen,
    'dependency_descriptors': 21, 'dependency_descriptors_unchanged': True,
    'external_dependency_bytes_rechecked': False,
    'qualified_population': proof['complete_counts'],
    'native_experiment_executed': False})

class Result(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ids = []
        self.successful_subtests = 0
        self.failed_subtests = 0
    def startTest(self, test):
        self.ids.append(test.id())
        super().startTest(test)
    def addSubTest(self, test, subtest, error):
        if error is None:
            self.successful_subtests += 1
        else:
            self.failed_subtests += 1
        super().addSubTest(test, subtest, error)

suite = unittest.defaultTestLoader.loadTestsFromNames(MODULES)
started = time.monotonic()
with (OUTPUT / 'focused-tests.log').open('w') as log:
    result = unittest.TextTestRunner(stream=log, verbosity=2, resultclass=Result).run(suite)
after = inventory()
save('source-after.json', after)
summary = {
    'scope': 'focused-host-development-only', 'base_revision': BASE,
    'source_state': 'base-plus-recorded-working-changes', 'modules': MODULES,
    'python': sys.version, 'tests_run': result.testsRun,
    'unique_test_ids': len(set(result.ids)), 'successful_subtests': result.successful_subtests,
    'failed_subtests': result.failed_subtests,
    'failures': len(result.failures), 'errors': len(result.errors),
    'skips': len(result.skipped), 'expected_failures': len(result.expectedFailures),
    'unexpected_successes': len(result.unexpectedSuccesses),
    'duration_seconds': time.monotonic() - started,
    'source_files_observed': len(before), 'source_stable': before == after,
    'passed': result.wasSuccessful() and not result.skipped and before == after,
    'strict_governance_qualification': False, 'native_execution': False,
    'performance_acceptance': False, 'phase_acceptance': False,
}
save('focused-result.json', summary)
save('executed-ids.json', result.ids)
print(json.dumps(summary, indent=2))
raise SystemExit(0 if summary['passed'] else 1)
