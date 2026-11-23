"""Read completed test evidence without executing tests or changing source."""
import ast
import collections
import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path('/workspace/scratch/279b6658611e')
VALIDATION = ROOT / 'validation'
BASE = '849469e1111870fbcfe0346afd33b284a5a1edd8'
INITIAL = 'ac2f2ae761c3644103278f7a41cc6ae7db734a86'
CORRECTED = '7251f078972c1d524de06d069e91b014b55896f5'
FULL_SOURCE = Path('/workspace/p06-governance-source')
CORRECTED_SOURCE = Path('/workspace/p06-reader-regression-source')


def identity(path):
    data = Path(path).read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(data).hexdigest(), 'size_bytes': len(data)}


def git(source, *args):
    return subprocess.check_output(['git', '-C', str(source), *args], text=True).strip()


def source_state(source):
    return {'revision': git(source, 'rev-parse', 'HEAD'),
            'tree': git(source, 'rev-parse', 'HEAD^{tree}'),
            'status': git(source, 'status', '--short'),
            'submodules': git(source, 'submodule', 'status', '--recursive')}


def parse_log(path):
    text = path.read_text()
    starts = list(re.finditer(r'^test\S+ \(([^\n)]+)\)', text, re.M))
    ids = [match.group(1) for match in starts]
    statuses = collections.Counter()
    unresolved = []
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        block = text[match.start():end]
        endings = re.findall(r'(?:^| \.\.\. )(ok|FAIL|ERROR|skipped[^\n]*|expected failure|unexpected success)$', block, re.M)
        if len(endings) != 1:
            unresolved.append({'id': match.group(1), 'endings': endings})
        else:
            statuses[endings[0]] += 1
    summaries = re.findall(r'^Ran (\d+) tests? in ([\d.]+)s$', text, re.M)
    assert len(summaries) == 1
    count, duration = summaries[0]
    assert len(ids) == int(count) == len(set(ids))
    assert not unresolved
    assert dict(statuses) == {'ok': int(count)}
    assert text.rstrip().endswith('\nOK')
    return {'identity': identity(path), 'tests_run': int(count),
            'unique_test_ids': len(set(ids)), 'duplicate_test_ids': 0,
            'unittest_duration_seconds': float(duration),
            'status_counts': dict(statuses), 'terminal_status': 'OK',
            'failures': 0, 'errors': 0, 'skipped': 0,
            'expected_failures': 0, 'unexpected_successes': 0,
            'module_counts': dict(sorted(collections.Counter(x.split('.')[0] for x in ids).items()))}, set(ids)


def declared_tests(revision, path):
    result = subprocess.run(['git', '-C', str(CORRECTED_SOURCE), 'show', revision + ':' + path],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    if result.returncode:
        assert result.returncode == 128
        return set()
    module = Path(path).stem
    tests = set()
    for node in ast.parse(result.stdout).body:
        if isinstance(node, ast.ClassDef):
            for method in node.body:
                if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)) and method.name.startswith('test'):
                    tests.add(f'{module}.{node.name}.{method.name}')
    return tests


def test_delta(before, after):
    paths = git(CORRECTED_SOURCE, 'diff', '--name-only', before, after, '--', 'ci/project/test_*.py').splitlines()
    added = set()
    removed = set()
    counts = []
    for path in paths:
        old, new = declared_tests(before, path), declared_tests(after, path)
        added |= new - old
        removed |= old - new
        counts.append({'path': path, 'added': len(new - old), 'removed': len(old - new)})
    return {'before': before, 'after': after, 'added_test_methods': len(added),
            'removed_test_methods': len(removed), 'files': counts}, added, removed


full_receipt_path = VALIDATION / 'full-governance-ac2f2ae7.process.json'
corrected_receipt_path = VALIDATION / 'w07_a02-affected-reader-regression.json'
identity_path = VALIDATION / 'w07_a02-source-identities.json'
full_receipt = json.loads(full_receipt_path.read_text())
corrected_receipt = json.loads(corrected_receipt_path.read_text())
recorded_source = json.loads(identity_path.read_text())
full, old_ids = parse_log(VALIDATION / 'full-governance-ac2f2ae7.log')
affected, affected_ids = parse_log(VALIDATION / 'w07_a02-affected-reader-regression.log')

assert full_receipt['exit_code'] == corrected_receipt['exit_code'] == 0
assert full['identity']['sha256'] == full_receipt['log_sha256']
assert full['identity']['size_bytes'] == full_receipt['log_bytes']
assert affected['identity'] == corrected_receipt['log_identity']
assert identity(identity_path) == corrected_receipt['source_identity']
assert recorded_source['before'] == recorded_source['after']
assert full_receipt['status_before'] == full_receipt['status_after'] == ''
assert corrected_receipt['status_before'] == corrected_receipt['status_after'] == ''

current_full = source_state(FULL_SOURCE)
current_corrected = source_state(CORRECTED_SOURCE)
assert current_full['revision'] == full_receipt['source_revision'] == INITIAL
assert current_full['tree'] == full_receipt['source_tree']
assert current_full['status'] == ''
assert current_corrected['revision'] == corrected_receipt['expected_revision'] == CORRECTED
assert current_corrected['tree'] == corrected_receipt['expected_tree']
for field in current_corrected:
    assert current_corrected[field] == recorded_source['after'][field], field
assert current_corrected['status'] == ''
tracked_manifest = recorded_source['after']['files']
expected_paths = [p for p in git(CORRECTED_SOURCE, 'ls-files', 'ci/project').splitlines()
                  if p.endswith(('.py', '.json'))]
assert sorted(row['path'] for row in tracked_manifest) == sorted(expected_paths)
for row in tracked_manifest:
    actual = identity(CORRECTED_SOURCE / row['path'])
    assert actual['sha256'] == row['sha256'] and actual['size_bytes'] == row['size_bytes'], row['path']
for field in ('python', 'cmake'):
    assert identity(corrected_receipt[field]['path']) == corrected_receipt[field]

initial_delta, initial_additions, initial_removals = test_delta(BASE, INITIAL)
correction_delta, correction_additions, correction_removals = test_delta(INITIAL, CORRECTED)
assert initial_delta['added_test_methods'] == 115 and not initial_removals
assert correction_delta['added_test_methods'] == 12 and not correction_removals
assert initial_additions <= old_ids
assert correction_additions <= affected_ids
assert not correction_additions & old_ids
assert affected_ids - old_ids == correction_additions
assert len(affected_ids & old_ids) == 124
assert len(affected_ids & initial_additions) == 14

full.update({'receipt': identity(full_receipt_path), 'argv': full_receipt['argv'],
             'cwd': full_receipt['cwd'], 'source_revision': INITIAL,
             'source_tree': current_full['tree'], 'exit_code': full_receipt['exit_code'],
             'outer_duration_seconds': full_receipt['duration_seconds'],
             'started_at': full_receipt['started_at'], 'finished_at': full_receipt['finished_at'],
             'recorded_before_after_status_clean': True, 'current_source_clean': True,
             'current_revision_and_tree_match_receipt': True,
             'source_evidence_limit': 'Receipt records initial revision/tree and before/after clean git status; it does not contain a before/after byte manifest or explicit after-run revision/tree.',
             'cmake_path': full_receipt['cmake_path']})
affected.update({'receipt': identity(corrected_receipt_path), 'argv': corrected_receipt['argv'],
                 'cwd': corrected_receipt['cwd'], 'source_revision': CORRECTED,
                 'source_tree': current_corrected['tree'], 'exit_code': corrected_receipt['exit_code'],
                 'outer_duration_seconds': corrected_receipt['duration_seconds'],
                 'started_at': corrected_receipt['started_at'], 'finished_at': corrected_receipt['finished_at'],
                 'environment_overrides': corrected_receipt['environment_overrides'],
                 'path_prefix': corrected_receipt['path_prefix'],
                 'python': corrected_receipt['python'], 'python_version': corrected_receipt['python_version'],
                 'cmake': corrected_receipt['cmake'],
                 'source_identity_record': identity(identity_path),
                 'before_after_source_states_equal': True,
                 'tracked_python_json_files_independently_rehashed': len(tracked_manifest),
                 'recursive_submodule_entries': len(current_corrected['submodules'].splitlines()),
                 'current_source_matches_after_manifest': True,
                 'recorded_before_after_status_clean': True, 'current_source_clean': True})

output = {
    'schema_version': 1,
    'audit_agent': '/root/w07_a05',
    'recorded_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'audit_mode': 'Read-only verification of completed logs, process receipts, source identities and Git/AST deltas; no tests rerun.',
    'outcome': 'pass_with_explicit_revision_scopes',
    'full_governance': full,
    'corrected_affected_regression': affected,
    'initial_test_delta': initial_delta,
    'correction_test_delta': correction_delta,
    'coverage_relationship': {
        'initial_additions_present_in_full_log': len(initial_additions),
        'correction_additions_present_in_affected_log': len(correction_additions),
        'affected_ids_already_in_initial_full_run': len(affected_ids & old_ids),
        'affected_ids_absent_from_initial_full_run': len(affected_ids - old_ids),
        'initial_full_ids_not_rerun_in_affected_suite': len(old_ids - affected_ids),
        'initial_new_tests_repeated_in_affected_suite': len(initial_additions & affected_ids),
        'correction_added_test_ids': sorted(correction_additions),
        'no_aggregate_same_revision_pass_count_claimed': True
    },
    'correction_changed_files': git(CORRECTED_SOURCE, 'diff', '--name-status', INITIAL, CORRECTED).splitlines(),
    'correction_diff_stat': git(CORRECTED_SOURCE, 'diff', '--shortstat', INITIAL, CORRECTED),
    'what_passed': [
        '4,256 unique unittest cases in complete ci/project test_*.py discovery at ac2f2ae761c3644103278f7a41cc6ae7db734a86; exit 0, terminal OK, zero skips/failures/errors.',
        '136 unique unittest cases across ten affected modules at 7251f078972c1d524de06d069e91b014b55896f5; exit 0, terminal OK, zero skips/failures/errors.',
        'All 115 initially added test methods occur in the old full run; all 12 correction test methods occur in the corrected affected run.',
        'Recorded corrected source states match before/after and current bytes; full receipt and current checkout agree on initial revision/tree and clean status.'
    ],
    'what_is_not_established': [
        'The full governance suite was not run at 7251f078 in these artifacts.',
        'The 136 corrected tests are not 136 new tests; 124 IDs overlap the initial full run.',
        'Unit/governance results do not establish native GPU execution, broad backend qualification, warm-run acceptance, or phase acceptance.',
        'No results for later source revisions are established by these two test runs.'
    ],
    'native_gpu_execution_established': False,
    'qualification_or_acceptance_claimed': False
}
outpath = VALIDATION / 'w07_a05-test-evidence-review.json'
outpath.write_text(json.dumps(output, indent=2) + '\n')
print(json.dumps({'output': str(outpath), 'full_tests': full['tests_run'],
                  'corrected_tests': affected['tests_run'], 'overlap': len(old_ids & affected_ids),
                  'initial_new_tests': len(initial_additions), 'correction_new_tests': len(correction_additions),
                  'current_files_rehashed': len(tracked_manifest), 'outcome': output['outcome']}))
