"""Inert audit of a retained governance log; no captured program is executed."""
from __future__ import annotations

import ast
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import subprocess

WORK = Path('/tmp/ai-gpu-native-lifetime-dfd857-work')
ROOT = Path('/tmp/ai-gpu-native-lifetime-dfd857')
REVISION = 'b4127b19a004b5aebb8d52eab9ceda0da3ff4561'
LOG_SHA256 = '244af36ef253e5edb2c27aa79a4ac3f925f81a05203b83201bb444b49e9621f9'


def identity(path):
    data = path.read_bytes()
    return {'size_bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


original = WORK / 'full-governance-original.log'
retained = ROOT / 'docs/project/evidence/p06-native-lifetime/ci/b4127b19-full-governance-original.log'
assert original.read_bytes() == retained.read_bytes()
assert identity(original) == {'size_bytes': 801092, 'sha256': LOG_SHA256}
lines = [re.sub(r'^\d{4}-\d\d-\d\dT\S+Z ', '', line)
         for line in original.read_text().splitlines()]
records = []
current = None
for number, line in enumerate(lines, 1):
    match = re.match(r'^(test_\S+) \(([^)]+)\)(.*)$', line)
    if match:
        if current:
            records.append(current)
        current = {'id': match.group(2), 'line': number, 'lines': [line]}
    elif current:
        current['lines'].append(line)
        if line == '----------------------------------------------------------------------':
            records.append(current)
            current = None
if current:
    records.append(current)
for record in records:
    matches = [re.search(r'\.\.\. (ok|FAIL|ERROR|skipped.*|expected failure|unexpected success)$', line)
               for line in record['lines']]
    record['statuses'] = [match.group(1) for match in matches if match]
assert len(records) == 3813
assert len({record['id'] for record in records}) == 3813
assert all(record['statuses'] == ['ok'] for record in records)
assert [line for line in lines if re.fullmatch(r'Ran \d+ tests in [\d.]+s', line)] == ['Ran 3813 tests in 2498.078s']
assert [line for line in lines if re.fullmatch(r'OK(?: \(.*\))?', line)] == ['OK']
assert not any('##[error]' in line for line in lines)

collection = json.loads((WORK / 'w08_a02-collection.json').read_text())
assert collection['source_revision'] == REVISION
expected = {row['id'] for row in collection['tests']}
assert len(expected) == 80
observed = defaultdict(list)
for record in records:
    observed[record['id']].append(record)
assert all(len(observed[test_id]) == 1 and observed[test_id][0]['statuses'] == ['ok']
           for test_id in expected)
new_counts = Counter(test_id.split('.')[0] for test_id in expected)
focused_modules = sorted(new_counts) + ['test_p06_managed_preflight_runner', 'test_p06_managed_preflight_ci']
focused_records = [record for record in records if record['id'].split('.')[0] in focused_modules]
assert len(focused_records) == 120

paths = ['ci/project/' + name + '.py' for name in focused_modules] + [
    '.github/workflows/project-governance.yml', 'ci/project/preflight.py',
    'ci/project/check_project.py', 'ci/project/check_baseline_packets.py',
    'tests/regression/ai_counter_preflight/hooks.cpp',
    'tests/regression/ai_counter_preflight/hooks.h',
    'ci/project/fixtures/p06_native_lifetime_hooks/harness.cpp',
    'ci/project/fixtures/p06_native_lifetime_hooks/processor.h',
    'ci/project/fixtures/p06_native_lifetime_hooks/core.h',
]
sources = []
for path in paths:
    committed = subprocess.check_output(['git', 'show', REVISION + ':' + path], cwd=ROOT)
    assert committed == (ROOT / path).read_bytes(), path
    sources.append({'path': path, **identity(ROOT / path), 'matches_implementation': True})
hook_tree = ast.parse((ROOT / 'ci/project/test_p06_native_lifetime_hooks.py').read_text())
hook_class = next(node for node in hook_tree.body
                  if isinstance(node, ast.ClassDef) and node.name == 'NativeLifetimeHookTests')
methods = [node for node in hook_class.body
           if isinstance(node, ast.FunctionDef) and node.name.startswith('test_')]
scenarios = []
for method in methods:
    calls = [node for node in ast.walk(method) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute) and node.func.attr == 'cases']
    assert len(calls) == 1
    scenarios.extend(ast.literal_eval(calls[0].args[0]))
assert len(methods) == 11 and len(scenarios) == len(set(scenarios)) == 38

metadata = json.loads((WORK / 'full-governance-run-metadata.json').read_text())
jobs = json.loads((WORK / 'w10_a03-jobs.json').read_text())
assert metadata['id'] == 45130300117 and metadata['run_attempt'] == 1
assert metadata['head_sha'] == REVISION and metadata['head_branch'] == 'master'
assert metadata['event'] == 'push' and metadata['status'] == 'completed'
assert metadata['conclusion'] == 'success'
assert jobs['total_count'] == 1 and len(jobs['jobs']) == 1
job = jobs['jobs'][0]
assert job['id'] == 137544020980 and job['run_id'] == 45130300117
assert job['head_sha'] == REVISION and job['status'] == 'completed'
assert job['conclusion'] == 'success'
assert all(step['status'] == 'completed' and step['conclusion'] == 'success'
           for step in job['steps'])
assert REVISION in lines
assert 'Source: ' + REVISION + ' (tracked changes: False)' in lines
assert 'Preflight: pass (governance)' in lines
assert 'Project governance validation passed (structure and metadata only; no GPU execution certified).' in lines
baseline = [json.loads(line) for line in lines
            if line.startswith('{"outcome": "pass", "packets":')]
assert len(baseline) == 1 and baseline[0]['outcome'] == 'pass'
assert baseline[0]['phase_complete'] is False
assert baseline[0]['raw_log_bytes_verified'] is False
assert baseline[0]['redaction_relationship_verified'] is False

receipt = {
    'reviewer': 'w10_a03_completed_governance_review',
    'review_class': 'R3', 'verdict': 'LAND', 'open_f2_f3_findings': [],
    'scope': 'Inert completed-governance-original review; no suite, builds, native workload or retained program executed by reviewer.',
    'source_revision': REVISION, 'run_id': 45130300117, 'job_id': 137544020980,
    'run_attempt': 1, 'status': 'completed', 'conclusion': 'success',
    'original_log': identity(original), 'packet_log_matches_original': True,
    'source_checkout_sha_and_clean_preflight_match': True,
    'suite': {'tests': 3813, 'unique_ids': 3813, 'seconds': 2498.078,
              'explicit_ok_results': 3813, 'failures': 0, 'errors': 0, 'skips': 0,
              'expected_failures': 0, 'unexpected_successes': 0, 'summary': 'OK'},
    'new_method_counts': dict(sorted(new_counts.items())),
    'new_ids_executed_once_successfully': sorted(expected),
    'focused_method_counts': dict(sorted(Counter(row['id'].split('.')[0] for row in focused_records).items())),
    'focused_total_is_subset_of_full_suite': 120,
    'compiled_hook_source_inference': {
        'methods': 11, 'asserted_fresh_process_scenarios': 38,
        'no_missing_compiler_or_failed_compile_skip_path': True,
        'requires_cxx17_strict_warnings_ubsan': True,
        'separate_historical_parent_control_executed_by_this_job': False,
        'limitation': 'Successful unittest results plus unchanged setup/assertion source establish execution; successful child command stdout/compiler receipt is captured internally by tests, not separately printed into this original log.'},
    'completed_steps': [{key: step[key] for key in ('name', 'status', 'conclusion')} for step in job['steps']],
    'baseline_consistency_scope': baseline[0],
    'reviewed_sources': sources,
    'supporting_receipts': {name: identity(WORK / name) for name in
        ['w08_a02-collection.json', 'w08_a02-test-inventory.json',
         'full-governance-run-metadata.json', 'w10_a03-jobs.json']},
    'limits': ['Full-suite evidence belongs to b4127b19, not a later documentation/evidence commit.',
               'The 120 focused methods and 80 new methods overlap the 3813 full-suite methods.',
               'No native SimX, GPU, hardware, warm or phase qualification is established by governance.',
               'Generic CI run45130300144 is independent and is not reviewed as passed here.'],
}
(WORK / 'w10_a03-receipt.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
print(json.dumps({'verdict': receipt['verdict'], 'tests': 3813, 'new_methods': 80,
                  'focused_subset': 120, 'hook_scenarios': 38,
                  'source_files': len(sources), 'receipt': identity(WORK / 'w10_a03-receipt.json')}))
