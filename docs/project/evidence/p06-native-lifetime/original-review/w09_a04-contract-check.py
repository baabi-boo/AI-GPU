"""Narrow inert identity/framing review; never run a retained program."""
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import zipfile

ROOT = Path('/tmp/ai-gpu-native-lifetime-dfd857')
WORK = Path('/tmp/ai-gpu-native-lifetime-dfd857-work')
CURRENT = 'b4127b19a004b5aebb8d52eab9ceda0da3ff4561'
BASE = '6130a2f7424932a6f3b7377ef8ae4816da2b304f'
PACKET = WORK / 'native-original/native-lifetime'
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'ci/project'))
import p06_managed_preflight_contract as parent
import p06_native_lifetime_contract as lifetime


def sha(body):
    return hashlib.sha256(body).hexdigest()


def canonical(value):
    return sha(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode())


def ident(path):
    body = path.read_bytes()
    return {'sha256': sha(body), 'size_bytes': len(body)}


def git_body(revision, name):
    return subprocess.run(['git', 'cat-file', 'blob', revision + ':' + name], cwd=ROOT,
                          check=True, capture_output=True).stdout


unchanged = [
    '.github/workflows/p06-managed-preflight.yml',
    '.github/workflows/p06-managed-preflight-replay.yml',
    'ci/project/p06_managed_preflight_contract.py',
    'ci/project/p06_managed_preflight_records.py',
    'ci/project/p06_managed_preflight_replay.py',
    'ci/project/p06_managed_preflight_replay_build.py',
    'ci/project/p06_managed_preflight_replay_hosted.py',
    'ci/project/p06_managed_preflight_source_export.py',
    'ci/project/p06_managed_preflight_sources.py',
    'ci/project/p06_managed_preflight_derivation.py',
    'ci/project/p06_managed_preflight_application_build.py',
    'ci/project/p06_warm_contract.json',
    'ci/project/p06_warm_records.py',
    'docs/designs/managed_counter_preflight_v1.md',
    'docs/designs/managed_counter_preflight_replay_v1.md',
    'docs/designs/warm_workspace_benchmark_v1.md',
    'docs/designs/simx_counter_lifetime_v1.md',
    'tests/regression/ai_warm_workspace/main.cpp',
]
selected = unchanged + [
    '.github/workflows/p06-native-lifetime.yml',
    'ci/project/p06_managed_preflight_execute.py',
    'ci/project/p06_native_lifetime_contract.py',
    'ci/project/p06_native_lifetime_execute.py',
    'ci/project/p06_native_lifetime_records.py',
    'ci/project/p06_pending_probe.py',
    'ci/project/test_p06_native_lifetime_records.py',
    'ci/project/test_p06_native_lifetime_runner.py',
    'docs/designs/managed_counter_lifetime_v1.md',
    'tests/regression/ai_counter_preflight/main.cpp',
    'tests/regression/ai_counter_preflight/hooks.cpp',
]
sources = []
for name in selected:
    body = (ROOT / name).read_bytes()
    assert body == git_body(CURRENT, name), name
    if name in unchanged:
        assert body == git_body(BASE, name), name
    sources.append({'path': name, **ident(ROOT / name), 'matches_current_commit': True,
                    'unchanged_from_audit_base': name in unchanged})

report = json.loads((PACKET / 'report.json').read_bytes())
assert report['expected_revision'] == CURRENT
assert report['contract_id'] == lifetime.CONTRACT_ID
parent_descriptor = parent.load_contract(ROOT)
lifetime_descriptor = lifetime.contract()
descriptors = {}
for label, key, expected in [('parent', 'preflight_contract', parent_descriptor),
                             ('lifetime', 'contract', lifetime_descriptor)]:
    descriptor = report[key + '_snapshot']
    path = PACKET / descriptor['path']
    assert ident(path) == {k: descriptor[k] for k in ('sha256', 'size_bytes')}
    value = json.loads(path.read_bytes())
    assert value == expected
    assert canonical(value) == report[key + '_sha256']
    descriptors[label] = {'contract_id': value['contract_id'], 'canonical_sha256': canonical(value),
                          'snapshot': descriptor}
assert lifetime.contract_hash() == descriptors['lifetime']['canonical_sha256']

tree = ast.parse((ROOT / 'ci/project/p06_managed_preflight_replay.py').read_text())
old_report_fields = next(ast.literal_eval(n.value) for n in tree.body
                        if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
                        and n.targets[0].id == 'REPORT_FIELDS')
new_extra = sorted(set(report) - old_report_fields)
assert new_extra == ['native_lifetime_passed', 'preflight_contract_sha256', 'preflight_contract_snapshot']
assert not old_report_fields - set(report)
assert report['contract_id'] != parent.CONTRACT_ID


def false_claims(value):
    assert all(value[name] is False for name in parent.FALSE_CLAIMS)


false_claims(report)
assert report['unresolved_obligations'] == list(parent.UNRESOLVED_OBLIGATIONS)
builds = {}
for variant in report['variants']:
    descriptor = variant['binding']
    body = (PACKET / descriptor['path']).read_bytes()
    assert sha(body) == descriptor['sha256'] and len(body) == descriptor['size_bytes']
    binding = json.loads(body)
    assert canonical(binding) == variant['build_binding_sha256']
    assert binding['contract_id'] == lifetime.CONTRACT_ID
    assert binding['lifetime_contract'] == lifetime_descriptor
    assert binding['contract_sha256'] == descriptors['lifetime']['canonical_sha256']
    assert binding['preflight_contract_sha256'] == descriptors['parent']['canonical_sha256']
    false_claims(binding)
    builds[variant['build_binding_sha256']] = binding

processes = []
for process in report['processes']:
    descriptor = process['binding']
    body = (PACKET / descriptor['path']).read_bytes()
    assert sha(body) == descriptor['sha256'] and len(body) == descriptor['size_bytes']
    binding = json.loads(body)
    assert canonical(binding) == process['execution_binding_sha256']
    assert binding['build'] == builds[process['build_binding_sha256']]
    assert binding['lifetime_contract'] == lifetime_descriptor
    assert binding['contract_id'] == lifetime.CONTRACT_ID
    assert binding['contract_sha256'] == descriptors['lifetime']['canonical_sha256']
    assert binding['preflight_contract_sha256'] == descriptors['parent']['canonical_sha256']
    raw = (PACKET / process['log']).read_bytes()
    assert raw.endswith(b'\n') and b'\r' not in raw and b'\x00' not in raw
    assert raw.count(lifetime.WITNESS_MARKER.encode()) == 1
    prefix, separator, last = raw[:-1].rpartition(b'\n')
    prefix += separator
    assert prefix == raw[:len(prefix)] and last.startswith(lifetime.WITNESS_PREFIX.encode())
    sidecar = json.loads(last[len(lifetime.WITNESS_PREFIX):])
    assert prefix.count(parent.WITNESS_MARKER.encode()) == 1
    warm, separator, old_last = prefix[:-1].rpartition(b'\n')
    assert old_last.startswith(parent.WITNESS_PREFIX.encode())
    assert (warm + separator).endswith(b'PASSED!\n')
    witness = json.loads(old_last[len(parent.WITNESS_PREFIX):])
    assert set(witness) == set(parent.WITNESS_FIELDS)
    assert set(sidecar) == set(lifetime.WITNESS_FIELDS)
    for observed, identity in [(witness, parent.process_identity(process['format'], process['policy'],
                                    process['execution_binding_sha256'])),
                               (sidecar, lifetime.process_identity(process['format'], process['policy'],
                                    process['execution_binding_sha256']))]:
        assert all(observed[name] == value for name, value in identity.items())
        assert observed['sample_id'] == process['sample_id'] and observed['process_id'] == process['id']
        false_claims(observed)
        assert observed['unresolved_obligations'] == list(parent.UNRESOLVED_OBLIGATIONS)
    assert witness == process['observation']['witness']
    assert sidecar == process['observation']['lifetime']
    command = next(c for c in report['commands'] if c['id'] == process['command_id'])
    assert command['argv'][1:4] == ['--lifetime', '--policy', process['policy']]
    assert command['argv'].count('--lifetime') == 1
    assert command['argv'][command['argv'].index('--qualification-id') + 1] == process['execution_binding_sha256']
    processes.append({'id': process['id'], 'log_sha256': sha(raw), 'prefix_sha256': sha(prefix),
                      'prefix_bytes': len(prefix), 'sidecar_bytes': len(raw) - len(prefix),
                      'execution_binding_sha256': process['execution_binding_sha256'],
                      'build_binding_sha256': process['build_binding_sha256'],
                      'original_witness_contract_id': witness['contract_id'],
                      'sidecar_contract_id': sidecar['contract_id']})
assert len(processes) == 4

historical_root = ROOT / 'docs/project/evidence/p06-managed-preflight/native'
historical_files = []
for path in sorted(historical_root.iterdir()):
    if path.is_file():
        name = path.relative_to(ROOT).as_posix()
        body = path.read_bytes()
        assert body == git_body(BASE, name) == git_body(CURRENT, name)
        historical_files.append({'path': name, **ident(path), 'unchanged_from_base_and_current': True})
historical = []
for name, digest, expected_outcome in [
    ('run-45085300171-attempt1.zip', 'cee5be4dba875494f6eafb83484933ab7693428e4773b932a26d5b91bd17969d', 'pass'),
    ('run-45084009157-attempt1.zip', '4f1e177ba930c132f5e8cc7558b3087d39789c346763f00a9d1bdd2a6d17d00c', 'fail'),
]:
    assert ident(historical_root / name)['sha256'] == digest
    with zipfile.ZipFile(historical_root / name) as archive:
        original = json.loads(archive.read('managed-preflight/report.json'))
        descriptor_bytes = archive.read('managed-preflight/' + original['contract_snapshot']['path'])
        assert descriptor_bytes == (PACKET / report['preflight_contract_snapshot']['path']).read_bytes()
        assert original['contract_id'] == parent.CONTRACT_ID
        assert original['contract_sha256'] == descriptors['parent']['canonical_sha256']
        assert original['outcome'] == expected_outcome
        false_claims(original)
        native_logs = [n for n in archive.namelist() if n.startswith('managed-preflight/logs/preflight-')]
        for member in native_logs:
            body = archive.read(member)
            assert lifetime.WITNESS_MARKER.encode() not in body
            assert body.endswith(b'\n') and body[:-1].rpartition(b'\n')[2].startswith(parent.WITNESS_PREFIX.encode())
        historical.append({'archive': name, 'sha256': digest, 'source_revision': original['expected_revision'],
                           'outcome': original['outcome'], 'reason': original['reason'],
                           'contract_id': original['contract_id'], 'native_logs': len(native_logs),
                           'lifetime_witnesses': 0, 'parent_descriptor_bytes_identical': True})

status = json.loads((WORK / 'w06_a04-status.json').read_bytes())
log_summaries = []
for row in status['original_job_logs']:
    path = WORK / row['path']
    assert ident(path) == {k: row[k] for k in ('sha256', 'size_bytes')}
    content = path.read_text()
    objects = []
    for line in content.splitlines():
        match = re.match(r'^\S+Z (\{.*\})$', line)
        if match:
            objects.append(json.loads(match[1]))
    if row['job_id'] == 137544020957:
        selected_summary = next(x for x in objects if x.get('native_preflight_passed') is True)
        assert selected_summary['completed_counts'] == parent.COMPLETE_COUNTS
        run_id = 45130300249
    else:
        selected_summary = next(x for x in objects if x.get('contract_id') == 'p06-managed-counter-preflight-replay-v1')
        assert selected_summary['counts'] == parent.COMPLETE_COUNTS
        assert selected_summary['native_execution'] == 'not_run'
        assert selected_summary['retained_code_executed'] is False
        assert 'Ran 203 tests in 273.807s' in content and re.search(r'^\S+Z OK$', content, re.M)
        assert re.search(r'^\S+Z Original failed archive rejected at report.outcome;', content, re.M)
        run_id = 45130300109
    false_claims(selected_summary)
    assert selected_summary['outcome'] == 'pass'
    run = next(x for x in status['runs'] if x['id'] == run_id)
    assert run['head_sha'] == CURRENT and run['conclusion'] == 'success' and run['run_attempt'] == 1
    log_summaries.append({'run_id': run_id, 'job_id': row['job_id'], 'log': row['path'],
                          **ident(path), 'summary': selected_summary, 'run': run})

for row in sources:
    assert ident(ROOT / row['path']) == {k: row[k] for k in ('sha256', 'size_bytes')}
handoff = ROOT / 'docs/project/p06-dependency-provenance-handoff.md'
review_notes = ['w03_a05.md', 'w04_a05.md', 'w06_a04.md', 'w07_a06.md', 'w08_a01.md', 'w08_a05.md']
receipt = {'scope': 'narrow inert external-contract compatibility and identity review',
           'reviewed_revision': CURRENT, 'base_revision': BASE, 'outcome': 'pass',
           'retained_code_executed': False, 'native_execution_by_reviewer': 'not_run',
           'full_replay_by_reviewer': 'not_run', 'tests_or_builds_by_reviewer': 'not_run',
           'sources': sources, 'unchanged_source_count': len(unchanged), 'descriptors': descriptors,
           'new_report_extra_fields_rejected_by_old_exact_shape': new_extra,
           'new_processes': processes, 'historical_files': historical_files,
           'historical_originals': historical, 'original_ci_logs': log_summaries,
           'handoff': {'path': handoff.relative_to(ROOT).as_posix(), **ident(handoff)},
           'supporting_review_notes': [{'path': name, **ident(WORK / name)} for name in review_notes]}
output = WORK / 'w09_a04-contract-receipt.json'
output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
print(json.dumps({'outcome': 'pass', 'source_count': len(sources), 'unchanged_source_count': len(unchanged),
                  'unchanged_historical_files': len(historical_files), 'process_count': len(processes),
                  'receipt': str(output), **ident(output)}, sort_keys=True))
