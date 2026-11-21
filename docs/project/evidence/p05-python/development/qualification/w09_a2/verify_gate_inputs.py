#!/usr/bin/env python3
"""Read-only P05-A01 evidence reconciliation; executes no native or package code."""
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import zipfile

ROOT = Path('/workspace/scratch/ba0248fde989/AI-GPU')
BASE = ROOT / 'docs/project/evidence/p05-python'
OUT = ROOT.parent / 'p05-work/w09_a2/input-verification.json'
REVISION = 'e1420fd550f716df33a2556057b7086a03032cbe'
TREE = '3a168adfd345ecb3c15dc02b2583dc832bef6049'
AUDITORS = {
    'numerics': '608b16c80a1a40816ef15f04b2670c736e2abca7768e7c6ad546c8a96f23e736',
    'dispatch': 'ab0a1d1d6d0268b0766e5d3bc211e2830efb5e9683a413854fc1a16a3d5de391',
    'provenance': '4684a4e928ff672d371bdb78ab5f646b61ae59d1147c3c690e722a22a89186ac',
}

def sha(data):
    return hashlib.sha256(data).hexdigest()

def load(relative):
    return json.loads((BASE / relative).read_bytes())

def git_bytes(name):
    return subprocess.check_output(['git', 'show', REVISION + ':' + name], cwd=ROOT)

def identity(path):
    raw = path.read_bytes()
    return {'path': str(path.relative_to(ROOT)), 'sha256': sha(raw), 'size_bytes': len(raw)}

assert subprocess.check_output(['git', 'rev-parse', REVISION + '^{tree}'], cwd=ROOT).decode().strip() == TREE
verification = {'scope': 'Independent read-only A01 evidence reconciliation; no runtime execution or full suite',
                'source_revision': REVISION, 'source_tree': TREE, 'outcome': 'pass'}
host = load('development/host/w06_a1_run.json')
assert host['returncode'] == 0 and host['sources_unchanged'] is True
for name, digest in host['source_sha256'].items():
    assert sha(git_bytes(name)) == digest, name
assert len(host['source_sha256']) == 64
scenarios = load('development/host/w06_a1-native/results.json')
assert scenarios['scope'] == 'host-only-fault-injection'
assert scenarios['completed'] == scenarios['passed'] == scenarios['scenario_count'] == len(scenarios['results']) == 107
assert all(row['passed'] is True and row['returncode'] == 0 for row in scenarios['results'])
assert len({row['name'] for row in scenarios['results']}) == 107
probes = load('development/host/w06_a1-probes/results.json')
assert probes['completed'] == probes['passed'] == len(probes['results']) == 11
assert probes['source_unchanged'] is True and probes['original_artifacts_unchanged'] is True
assert all(row['passed'] is True and row['returncode'] == 0 for row in probes['results'])
assert sha((BASE / 'development/host/w06_a1_native_suite.log').read_bytes()) == host['suite_log_sha256']
verification['host_lifecycle'] = {'matching_recorded_source_hashes': 64, 'scenarios': 107, 'separate_probes': 11,
                                'scope': 'host-only-fault-injection', 'historical_head': host['head']}
inventory = load('development/host/w06_a2-checks/source-inventory.json')
assert len(inventory) == 22
for row in inventory:
    body = git_bytes(row['path'])
    assert sha(body) == row['sha256'] and len(body) == row['size'], row['path']
commands = load('development/host/w06_a2-checks/commands.json')
assert len(commands) == 8 and all(row['exit_code'] == 0 and row['timed_out'] is False for row in commands)
for row in commands:
    body = (BASE / 'development/host/w06_a2-checks/logs' / Path(row['log']['path']).name).read_bytes()
    assert sha(body) == row['log']['sha256'] and len(body) == row['log']['size']
assert load('development/host/w06_a2-checks/result.json')['outcome'] == 'pass'
verification['host_packaging'] = {'matching_binding_source_hashes': 22, 'successful_real_commands': 8,
                                'scope': 'unbound host packaging and isolated import'}
governance_run = load('hosted/governance-run.json')
governance_jobs = load('hosted/governance-jobs.json')['jobs']
assert governance_run['head_sha'] == REVISION and governance_run['conclusion'] == 'success'
assert len(governance_jobs) == 1 and governance_jobs[0]['head_sha'] == REVISION
assert governance_jobs[0]['conclusion'] == 'success'
governance_log = (BASE / 'hosted/governance-job.log').read_text()
assert 'Ran 2174 tests in 421.584s' in governance_log and re.search(r'\bOK\s*$', governance_log, re.M)
assert not re.search(r'FAILED \(failures=|FAILED \(errors=|OK \(skipped=', governance_log)
verification['clean_hosted_governance'] = {'run_id': governance_run['id'], 'job_id': governance_jobs[0]['id'],
                                         'tests': 2174, 'seconds': 421.584, 'conclusion': 'success'}
full = {}
for name, digest in AUDITORS.items():
    assert sha((BASE / 'reviews' / ('audit_' + name + '.py')).read_bytes()) == digest
    full[name] = load('reviews/full-' + name + '.json')
    assert full[name]['outcome'] == 'pass' and full[name]['auditor_sha256'] == digest
assert full['numerics']['full_matrix_verified'] is True
assert full['dispatch']['full_matrix_checked'] is True
assert full['provenance']['full_matrix'] is True
selected_matches = []
for name in AUDITORS:
    by_format = {row['format']: row for row in full[name]['packets']}
    assert set(by_format) == {'fp16', 'bf16'}
    for fmt in ('fp16', 'bf16'):
        selected = load('reviews/' + fmt + '-' + name + '.json')
        assert selected['outcome'] == 'pass' and selected['packets'] == [by_format[fmt]]
        selected_matches.append(fmt + '-' + name)
combined = full['dispatch']['counts']['combined']
assert combined['total_launches'] == 144 and combined['event_profile_pairs'] == 660
assert combined['profiled_launches'] == 132 and combined['unprofiled_launches'] == 12
assert combined['tensor_h2d_bytes'] == 93696 and combined['tensor_d2h_bytes'] == 36864
assert full['numerics']['total_launches'] == 144 and full['numerics']['event_profile_pairs'] == 660
review = load('qualification-review.json')
assert review['outcome'] == 'pass' and review['source_revision'] == REVISION
for row in review['commands']:
    assert row['exit_code'] == 0 and row['outcome'] == 'pass' and row['input_source_auditor_stable'] is True
    for field in ('log', 'result'):
        artifact = row[field]
        body = (ROOT / artifact['path']).read_bytes()
        assert sha(body) == artifact['sha256'] and len(body) == artifact['size_bytes']
verification['independent_audits'] = {'auditor_hashes': AUDITORS, 'six_selected_objects_match_full_matrix': selected_matches,
                                    'counts': combined}
metadata = {row['name']: row for row in load('hosted/p05-artifacts.json')['artifacts']}
archive_rows = []
installed_commands = []
for entry in load('archive-index.json')['archives']:
    variant = entry['variant']
    raw = (BASE / 'archives' / (variant + '.zip')).read_bytes()
    assert sha(raw) == entry['archive']['sha256'] and len(raw) == entry['archive']['size_bytes']
    provider = metadata['p05-' + variant + '-' + REVISION + '-attempt1']
    assert provider['digest'] == 'sha256:' + sha(raw) and provider['size_in_bytes'] == len(raw)
    expected = {row['path']: row for row in entry['members']}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert len(archive.infolist()) == len(expected) == 304
        assert set(archive.namelist()) == set(expected)
        for name, row in expected.items():
            body = archive.read(name)
            assert sha(body) == row['sha256'] and len(body) == row['size_bytes']
        report = json.loads(archive.read('python/report.json'))
        native = json.loads(archive.read('python/native/report.json'))
        checkout = json.loads(archive.read('python/snapshots/source-before.json'))['checkout']
        assert checkout['revision'] == REVISION and checkout['tree'] == TREE and checkout['dirty'] is False
        assert len(report['commands']) == 12 and len(native['commands']) == 15
        for packet in (report, native):
            assert packet['outcome'] == 'pass' and packet['source_stable'] is True
            assert all(row['exit_code'] == 0 and row['outcome'] == 'pass' and row['process_started'] is True
                       and row['cleanup_complete'] is True for row in packet['commands'])
        installed_commands += [{'variant': variant, 'archive_member': 'python/report.json', **row}
                               for row in report['commands'] if row['id'] in (
                                   'package-bound-sdist', 'package-offline-wheel', 'package-create-venv',
                                   'package-install-wheel', 'installed-matrix')]
    archive_rows.append({'variant': variant, 'sha256': sha(raw), 'size_bytes': len(raw),
                         'member_hashes_verified': 304, 'p05_commands': 12, 'native_commands': 15})
verification['original_archives'] = archive_rows
verification['installed_command_receipts'] = installed_commands
verification['qualification_review'] = identity(BASE / 'qualification-review.json')
OUT.write_text(json.dumps(verification, indent=2, sort_keys=True) + '\n')
print(json.dumps({'outcome': 'pass', 'output': str(OUT), 'sha256': sha(OUT.read_bytes()),
                  'host_source_hashes': 64, 'package_source_hashes': 22, 'archive_members': 608,
                  'selected_reports': 6, 'full_audits': 3}, sort_keys=True))
