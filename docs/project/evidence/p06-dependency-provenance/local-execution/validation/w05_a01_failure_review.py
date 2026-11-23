#!/usr/bin/env python3
"""Read-only review of the sealed first local dependency failure."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import time

sys.dont_write_bytecode = True
SOURCE = Path('/workspace/p06-local-run-source')
ROOT = Path('/workspace/p06-local-native-run-01/evidence/dependency-build')
PIN = '97fe819aacd6d308e0c799701344efe5bd7229ac4d737f0c04ff1e69956151b1'
REVISION = 'ac2f2ae761c3644103278f7a41cc6ae7db734a86'
sys.path.insert(0, str(SOURCE / 'ci/project'))
import p06_dependency_receipt as receipt
import p06_dependency_binary as binary
import p06_dependency_contract as contract
import p06_dependency_graph as graph


def identity(path):
    st = path.stat(follow_symlinks=False)
    assert stat.S_ISREG(st.st_mode) and st.st_nlink == 1
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    after = path.stat(follow_symlinks=False)
    assert (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns) == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    return {'sha256': digest.hexdigest(), 'size_bytes': st.st_size}


def snapshot(document):
    identities = {}
    for row in document['retained_files']:
        path = ROOT / row['path']
        assert path.resolve(strict=True) == path and path.is_relative_to(ROOT)
        observed = identity(path)
        assert observed == {key: row[key] for key in ('sha256', 'size_bytes')}
        identities[row['path']] = observed
    actual = set()
    for directory, directories, files in os.walk(ROOT, followlinks=False):
        assert all(not (Path(directory) / name).is_symlink() for name in directories)
        for name in files:
            p = Path(directory) / name
            assert not p.is_symlink()
            actual.add(p.relative_to(ROOT).as_posix())
    assert actual == set(identities) | {'report.json'}
    return identities


started = time.monotonic()
original = identity(ROOT / 'report.json')
assert original['sha256'] == PIN
document = json.loads((ROOT / 'report.json').read_bytes())
assert document['state'] == 'finished' and document['outcome'] == 'fail'
assert document['reason'] == 'link selected an unreviewed external archive'
assert document['fresh_dependency_build_passed'] is False
assert all(document[name] is False for name in contract.FALSE_CLAIMS)
before = snapshot(document)
reader = receipt.PacketReader(ROOT)
config_data = receipt.descriptor(document['tool_config'], reader)
config = receipt.decode(config_data)
config_sha256 = hashlib.sha256(config_data).hexdigest()
helper = next(row for row in document['helper_sources'] if row['path'] == 'ci/project/p06_dependency_record.py')
recorder_path = str(SOURCE / helper['path'])
recorder = {'path': recorder_path, 'resolved_path': recorder_path,
            'sha256': helper['sha256'], 'size_bytes': helper['size_bytes']}
records = [receipt._validate_record(receipt.decode(receipt.descriptor(row, reader)), config,
                                   config_sha256, reader, recorder) for row in document['records']]
roles = Counter(row['role'] for row in records)
assert roles == {'compile': 406, 'archive': 3, 'index': 2, 'link': 2}
children = [child for row in records for child in row['children']]
assert len(children) == 819
plan = graph.source_plan(document['source_manifest'], lambda component, name: reader('sources/' + component + '/' + name))
assert plan == document['source_plan']
components = Counter(row['component'] for row in plan)
assert components == contract.TRANSLATION_UNITS
selected = {str(Path(document['paths']['sources']) / row['source']): row for row in plan}
compiles = {}
for record in records:
    if record['role'] != 'compile':
        continue
    sources = [word for word in record['requested_arguments'] if word.endswith(('.c', '.cpp'))]
    assert len(sources) == 1
    path = str((Path(record['cwd']) / sources[0]).resolve())
    assert path in selected and path not in compiles
    compiles[path] = record
assert set(compiles) == set(selected)
archives = {}
for row in document['archives']:
    expected = []
    for entry in plan:
        if entry['component'] == row['name']:
            output = compiles[str(Path(document['paths']['sources']) / entry['source'])]['output']
            expected.append({'name': entry['archive_member'], 'sha256': output['sha256'], 'size_bytes': output['size_bytes']})
    result = binary.validate_archive(receipt.descriptor(row['descriptor'], reader), expected)
    assert result['members'] == row['members']
    archives[row['name']] = {'path': row['original_path'], 'members': len(result['members']), 'descriptor': row['descriptor']}

maps = {}
known = {row['original_path'] for row in document['archives']}
for record in records:
    if record['role'] != 'link':
        continue
    row = record['link_map']
    data = receipt.payload(row, reader)
    parsed = binary.parse_link_map(data.decode('utf-8'), cwd=record['cwd'])
    selected_counts = Counter(item['archive'] for item in parsed['selected_members'])
    name = 'extension' if '/extension/' in record['output_path'] else 'ramulator'
    maps[name] = {'sha256': hashlib.sha256(data).hexdigest(), 'size_bytes': len(data),
                  'record_id': record['id'], 'recorded_path': row['path'],
                  'retained_payload': 'payloads/' + row['payload'],
                  'selected_archive_member_counts': dict(sorted(selected_counts.items())),
                  'unadmitted_selected_archives': sorted(set(selected_counts) - known),
                  'support_loads': [path for path in parsed['loads'] if 'stdc++' in path or 'libc_nonshared' in path or 'libgcc' in path]}
assert maps['ramulator']['selected_archive_member_counts']['/workspace/p06-local-host/extracted/usr/lib/gcc/x86_64-linux-gnu/12/libstdc++.a'] == 108
assert maps['ramulator']['selected_archive_member_counts']['/usr/lib/x86_64-linux-gnu/libc_nonshared.a'] == 1
runtime_link = Path('/workspace/p06-local-host/extracted/usr/lib/gcc/x86_64-linux-gnu/12/libstdc++.so')
assert runtime_link.is_symlink() and not runtime_link.exists()
try:
    receipt.load_receipt(ROOT / 'report.json', PIN, REVISION)
except ValueError as error:
    full_reader_rejection = str(error)
else:
    raise AssertionError('The failed original was accepted')
assert full_reader_rejection == 'dependency receipt is not a complete successful build'
after = snapshot(document)
assert after == before and identity(ROOT / 'report.json') == original

result = {
    'schema_version': 1, 'review': 'wave-05-agent-01-failed-dependency-original',
    'observed_at': datetime.now(timezone.utc).isoformat(), 'review_outcome': 'pass',
    'original_outcome': 'fail', 'original_reason': document['reason'],
    'source_revision': REVISION, 'original_report': dict(path=str(ROOT / 'report.json'), **original),
    'retained_files': len(before), 'retained_bytes_excluding_report': sum(row['size_bytes'] for row in before.values()),
    'retained_files_rehashed_before_and_after': True, 'report_unchanged_after_review': True,
    'passing_actual_operation_counts': dict(sorted(roles.items())),
    'passing_actual_child_observations': len(children), 'child_stage_counts': dict(sorted(Counter(row['stage'] for row in children).items())),
    'independently_rederived_source_plan': dict(sorted(components.items())),
    'source_manifest_sha256': contract.digest(document['source_manifest']),
    'archive_members_joined_to_compile_outputs': archives, 'maps': maps,
    'missing_runtime': {'path': str(runtime_link), 'symlink_target': str(runtime_link.readlink()),
                        'resolved_path': str(runtime_link.resolve()), 'target_exists': False},
    'outer_commands': [{key: row[key] for key in ('id', 'outcome', 'exit_code', 'duration_seconds')} for row in document['commands']],
    'full_receipt_reader_result': {'accepted': False, 'reason': full_reader_rejection},
    'omitted_after_failure': {'generated_inputs': len(document['generated_inputs']), 'compile_database': document['compile_database'],
                              'products': len(document['products']), 'staged_files': len(document['staged_files']),
                              'admitted_maps': len(document['maps']), 'external_archives': len(document['external_archives'])},
    'fresh_dependency_build_passed': False, 'native_execution': 'not_run',
    'retained_code_executed_by_reviewer': False, 'qualification_or_acceptance_claimed': False,
    'duration_seconds': round(time.monotonic() - started, 6),
    'findings': [{'severity': 'F2', 'scope': 'execution environment', 'confidence': 'high',
                  'evidence_type': 'static-proof', 'finding': 'The extracted host C++ development runtime link is dangling, so GNU ld falls back to unadmitted static libstdc++ members.',
                  'repository_validator_status': 'Correctly rejects the incomplete original; no validator relaxation is warranted.',
                  'next_action': 'Preserve this host and failed original. Provision the pinned shared C++ runtime in a new host root, prove shared selection, then execute a fresh attempt.'}],
    'limitations': ['This review establishes the failure cause and the completed observed operation population, not a complete fresh dependency receipt.',
                    'Generated CMake retention, final product staging, complete source/stability checks and native loaded-library joins remain unestablished by this attempt.',
                    'No retained commands or binaries were executed and no original evidence was changed.']
}
destination = Path('/workspace/scratch/279b6658611e/validation/w05_a01-failure-review.json')
destination.write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')
print(json.dumps({key: result[key] for key in ('review_outcome', 'original_outcome', 'original_report', 'retained_files',
                                              'retained_bytes_excluding_report', 'passing_actual_operation_counts',
                                              'passing_actual_child_observations', 'duration_seconds')}, sort_keys=True))
