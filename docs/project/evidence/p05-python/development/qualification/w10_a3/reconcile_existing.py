#!/usr/bin/env python3
"""Read-only reconciliation of existing W07-W09 evidence, not an auditor rerun."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path('/workspace/scratch/ba0248fde989/AI-GPU')
EVIDENCE = ROOT / 'docs/project/evidence/p05-python'
REVIEWS = EVIDENCE / 'reviews'
REVISION = 'e1420fd550f716df33a2556057b7086a03032cbe'
TREE = '3a168adfd345ecb3c15dc02b2583dc832bef6049'
PINS = {
    'audit_numerics.py': '608b16c80a1a40816ef15f04b2670c736e2abca7768e7c6ad546c8a96f23e736',
    'audit_dispatch.py': 'ab0a1d1d6d0268b0766e5d3bc211e2830efb5e9683a413854fc1a16a3d5de391',
    'audit_provenance.py': '4684a4e928ff672d371bdb78ab5f646b61ae59d1147c3c690e722a22a89186ac',
    'extract_retained.py': '3abfe1aac9bbeef648389bcfc45c569b58a52db849b0575f23bac6c80f6507be',
}
ORIGINAL_PINS = {
    'numerics': 'd7a04f989b031e69d230c74e00d97b004bcf1b21625c3eeef7d7aaf5b4a165e0',
    'dispatch': '61d53c9bb72a6e2dee72d2baf6a7e86b2270ae6e35bfe62d0d24374dc425fc43',
    'provenance': 'cc0e18b5e241ad6301f949f393cfa3f0918829106cc8a3af1b8ff83a81bb7e62',
}
SEEN = {}

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def read(path):
    raw = path.read_bytes()
    name = str(path.relative_to(ROOT))
    row = {'path': name, 'sha256': digest(raw), 'size_bytes': len(raw)}
    assert SEEN.get(name, row) == row, 'input changed during review: ' + name
    SEEN[name] = row
    return raw

def document(path):
    return json.loads(read(path))

def descriptor(row, path=None):
    path = path or ROOT / row['path']
    raw = read(path)
    assert digest(raw) == row['sha256'] and len(raw) == row['size_bytes'], row['path']

def normalized(value):
    if isinstance(value, dict):
        return {key: normalized(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalized(item) for item in value]
    if isinstance(value, str):
        for directory in ('ci-e1420fd', 'w09_a4/relocated'):
            for fmt in ('fp16', 'bf16'):
                prefix = f'/workspace/scratch/ba0248fde989/p05-work/{directory}/simx-{fmt}/python'
                if value == prefix or value.startswith(prefix + '/'):
                    return f'<packet-{fmt}>' + value[len(prefix):]
    return value

def git(*args):
    return subprocess.check_output(['/usr/bin/git', '--no-optional-locks', '-C', str(ROOT), *args], timeout=30)

assert git('rev-parse', REVISION + '^{tree}').decode().strip() == TREE
readme = read(REVIEWS / 'README.md').decode()
for name, pin in PINS.items():
    assert digest(read(REVIEWS / name)) == pin
    if name.startswith('audit_'):
        assert pin in readme
for name, pin in ORIGINAL_PINS.items():
    assert digest(read(REVIEWS / 'history' / f'audit_{name}-initial.py')) == pin

full = {}
scope_keys = {'numerics': 'full_matrix_verified', 'dispatch': 'full_matrix_checked', 'provenance': 'full_matrix'}
helper_keys = {'numerics': 'reused_helper', 'dispatch': 'independent_helper', 'provenance': 'p04_helper'}
helpers = []
for name in scope_keys:
    value = document(REVIEWS / f'full-{name}.json')
    full[name] = value
    assert value['outcome'] == 'pass' and value[scope_keys[name]] is True
    assert value['auditor_sha256'] == PINS[f'audit_{name}.py']
    assert value.get('phase_acceptance', value.get('acceptance_claimed')) is False
    assert len(value['packets']) == 2
    helper = value[helper_keys[name]]
    raw = read(ROOT / helper['path'])
    assert digest(raw) == helper['sha256']
    assert git('cat-file', 'blob', REVISION + ':' + helper['path']) == raw
    helpers.append({'path': helper['path'], 'sha256': helper['sha256']})
    replay = document(REVIEWS / f'replay-{name}.json')
    assert normalized(value) == normalized(replay), name + ' replay difference beyond packet roots'
    for packet in value['packets']:
        assert packet.get('source_revision', packet.get('revision')) == REVISION
        assert packet.get('source_tree', packet.get('tree')) == TREE

q = document(EVIDENCE / 'qualification-review.json')
assert q['outcome'] == 'pass' and q['acceptance_claimed'] is False and q['phase_complete'] is False
assert q['source_revision'] == REVISION and q['source_tree'] == TREE
for command in q['commands']:
    assert command['exit_code'] == 0 and command['full_matrix'] is True
    descriptor(command['result']); descriptor(command['log'])
assert len(q['selected_reviews']) == 6
for row in q['selected_reviews']:
    descriptor(row)
    selected = document(ROOT / row['path'])
    assert selected['outcome'] == 'pass' and selected[scope_keys[row['audit']]] is False
    assert selected['auditor_sha256'] == PINS[f"audit_{row['audit']}.py"]
    assert selected.get('selected_scope', selected.get('selected_scope_requested')) is True
    assert len(selected['packets']) == 1
    expected = next(p for p in full[row['audit']]['packets'] if p['format'] == row['format'])
    assert selected['packets'][0] == expected
assert q['counts']['dispatch'] == full['dispatch']['counts']
assert q['counts']['numerics'] == full['numerics']['counts']
combined = full['dispatch']['counts']['combined']
assert (combined['total_launches'], combined['event_profile_pairs']) == (144, 660)
assert (combined['tensor_h2d_bytes'], combined['tensor_d2h_bytes']) == (93696, 36864)
assert (combined['profiled_launches'], combined['unprofiled_launches']) == (132, 12)
assert (full['numerics']['total_launches'], full['numerics']['event_profile_pairs']) == (144, 660)
assert q['wrapper_correction']['auditor_exit'] == 0 and q['wrapper_correction']['initial_wrapper_exit'] == 1
assert q['wrapper_correction']['source_and_auditors_modified'] is False

historical = {}
for name, count in [('numerics', 24), ('dispatch', 42), ('provenance', 26)]:
    before = document(REVIEWS / 'history' / f'{name}-before.json')
    after = document(REVIEWS / 'history' / f'{name}-after.json')
    rows_key, id_key = ('checks', 'name') if name == 'dispatch' else ('cases', 'case')
    assert len(before[rows_key]) == len(after[rows_key]) == count
    assert [r[id_key] for r in before[rows_key]] == [r[id_key] for r in after[rows_key]]
    if name == 'dispatch':
        failures = [r['name'] for r in before['checks'] if r['outcome'] == 'ACCEPTED_CONTRADICTION']
        assert len(failures) == 11 and after['accepted_contradictions'] == []
        assert all(r['outcome'] == {'pass': 'passed', 'reject': 'rejected'}[r['expected']] for r in after['checks'])
        assert after['auditor_sha256_before'] == after['auditor_sha256_after'] == PINS['audit_dispatch.py']
        assert before['packet_inventory_sha256_before'] == before['packet_inventory_sha256_after']
        assert after['packet_inventory_sha256_before'] == after['packet_inventory_sha256_after']
        assert read(REVIEWS / 'history/dispatch-after.json') == read(REVIEWS / 'history/dispatch-repair-check.json')
    else:
        expectation = 'expectation_met' if name == 'numerics' else 'expected_met'
        failures = [r['case'] for r in before['cases'] if r[expectation] is False]
        assert len(failures) == (2 if name == 'numerics' else 6)
        assert all(r[expectation] is True for r in after['cases'])
        assert after['auditor_initial_sha256'] == after['auditor_final_sha256'] == PINS[f'audit_{name}.py']
    lookup = {r[id_key]: r for r in after[rows_key]}
    historical[name] = {'unchanged_case_count': count, 'former_false_accepts': failures,
        'resolved': [{'case': case, 'outcome': lookup[case]['outcome'], 'reason': lookup[case].get('reason')} for case in failures],
        'before_receipt': SEEN[str((REVIEWS / 'history' / f'{name}-before.json').relative_to(ROOT))],
        'after_receipt': SEEN[str((REVIEWS / 'history' / f'{name}-after.json').relative_to(ROOT))]}
cli = document(REVIEWS / 'history/provenance-cli-recheck.json')
assert cli['checks'] == cli['expected_met'] == 4 and cli['existing_output_bytes_preserved'] is True
assert [r['returncode'] for r in cli['results']] == [0, 0, 1, 1]
assert document(REVIEWS / 'history/dispatch-initial-positive-rejection.json')['reason'] == 'command argument is invalid'
assert document(REVIEWS / 'history/provenance-initial-control-full.json')['reason'] == 'unrecognized VERSION syntax'

replay = document(EVIDENCE / 'relocated-replay.json')
assert replay['outcome'] == 'pass' and replay['execution_performed'] is False
assert replay['before'] == replay['after'] and replay['original_inputs_and_reviewed_scripts_unchanged'] is True
for row in replay['before']:
    descriptor(row, Path(row['path']))
assert len(replay['commands']) == 7
assert [row['exit_code'] for row in replay['commands']] == [0, 0, 0, 0, 2, 2, 2]
for row in replay['commands']:
    descriptor(row['log'], ROOT / row['retained_log'])
descriptor(replay['extraction'], ROOT / replay['extraction']['retained_copy'])
assert len(replay['negative_checks']) == 3
assert replay['negative_checks'][0]['retained_destination_unchanged'] is True
assert all(row['no_output_directory_created'] for row in replay['negative_checks'][1:])
assert all(row['exact_match_after_only_packet_path_normalization'] for row in replay['comparisons'].values())
index = document(EVIDENCE / 'archive-index.json')
assert digest(read(EVIDENCE / 'archive-index.json')) == '4295bc5eb96f34e0bf9dfbcea9752b6db493e0eb89669cc097ec0105e33646bd'
assert index['source_revision'] == REVISION and len(index['archives']) == 2
archive_summary = []
for entry in index['archives']:
    descriptor(entry['archive'], EVIDENCE / 'archives' / entry['archive']['path'])
    assert len(entry['members']) == 304
    hidden = sorted(row['path'] for row in entry['members'] if row['path'].endswith('/.config.stamp'))
    assert len(hidden) == 3
    proof = next(row for row in replay['archive_checks'] if row['variant'] == entry['variant'])
    assert proof['member_count'] == 304 and proof['matches_index_and_original_extraction'] is True
    assert hidden == sorted(proof['hidden_configuration_stamps'])
    archive_summary.append({'variant': entry['variant'], 'archive': entry['archive'], 'members': 304, 'hidden_stamps': hidden})

for name in ('w06_a4.md', 'w06_a5.md', 'w06_a6.md', 'w07_a1.md', 'w07_a2.md', 'w07_a3.md', 'w07_a4.md'):
    read(EVIDENCE / 'development' / name)
# Only parse reviewed source; never import or execute an auditor or its helper.
imports = {}
for name in PINS:
    body = read(REVIEWS / name)
    imports[name] = sorted({alias.name for node in ast.walk(ast.parse(body)) if isinstance(node, ast.Import) for alias in node.names}
                          | {node.module for node in ast.walk(ast.parse(body)) if isinstance(node, ast.ImportFrom) and node.module})
    assert not any(module.startswith(('vortex_ai', 'p05_')) for module in imports[name])
for name, row in list(SEEN.items()):
    assert digest((ROOT / name).read_bytes()) == row['sha256'], 'reviewed input changed: ' + name
result = {
    'schema_version': 1, 'outcome': 'pass', 'reviewer': '/root/w10_a3_final_auditor_review',
    'scope': 'Read-only source and existing W07-W09 evidence reconciliation; no auditor, probe, package or native execution',
    'source_revision': REVISION, 'source_tree': TREE, 'auditors_executed': False, 'native_executed': False,
    'fresh_counterexamples_run': 0, 'current_source_pins': PINS, 'initial_source_pins': ORIGINAL_PINS,
    'p04_helper_pins_checked_against_git': helpers, 'static_imports': imports,
    'historical_repairs': historical, 'provenance_cli_controls_passed': 4,
    'selected_packet_results_equal_complete_packet_results': 6,
    'full_and_replay_results_equal_after_only_packet_root_normalization': list(scope_keys),
    'combined_dispatch_counts': combined, 'combined_comparisons': q['combined_comparisons'],
    'archive_summary': archive_summary, 'relocated_positive_commands': 4, 'relocated_negative_commands': 3,
    'reviewed_inputs_unchanged': True, 'reviewed_files': sorted(SEEN.values(), key=lambda row: row['path']),
}
encoded = json.dumps(result, indent=2, sort_keys=True) + '\n'
with Path(sys.argv[1]).open('x') as output:
    output.write(encoded)
print(json.dumps({'outcome': 'pass', 'reviewed_files': len(SEEN), 'historical_semantic_outcomes': 92,
                  'prior_cli_controls': 4, 'selected_results': 6, 'full_replay_equalities': 3,
                  'new_auditor_or_native_executions': 0, 'result_sha256': digest(encoded.encode())}, sort_keys=True))
