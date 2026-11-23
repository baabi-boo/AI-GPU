#!/usr/bin/env python3
"""Read-only independent review of the actual sealed third dependency original."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shlex
import stat
import subprocess
import sys
import time

sys.dont_write_bytecode = True
SOURCE = Path('/workspace/p06-local-run-source-03')
ROOT = Path('/workspace/p06-local-native-run-03/evidence/dependency-build')
OUT = Path('/workspace/scratch/279b6658611e/validation/w07_a06-dependency-review.json')
REVISION = '7251f078972c1d524de06d069e91b014b55896f5'
TREE = 'c44b5a93ab3aabaf2438e9e7d102339c9dc80542'
PIN = '202ee0fb2d79d4c47380e41dfb9356a2f353c36f977348442111461d2ffb4924'
sys.path.insert(0, str(SOURCE / 'ci/project'))
import p06_dependency_receipt as receipt
import p06_dependency_binary as binary
import p06_dependency_contract as contract
import p06_dependency_graph as graph


def identity(path):
    st = path.stat(follow_symlinks=False)
    assert stat.S_ISREG(st.st_mode) and st.st_nlink == 1, str(path)
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    after = path.stat(follow_symlinks=False)
    assert (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns) == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    return {'sha256': digest.hexdigest(), 'size_bytes': st.st_size}


def packet_snapshot(document):
    rows = document['retained_files']
    names = [row['path'] for row in rows]
    assert names == sorted(set(names))
    result = {}
    for row in rows:
        path = ROOT / row['path']
        assert path.resolve(strict=True) == path and path.is_relative_to(ROOT)
        value = identity(path)
        assert value == {key: row[key] for key in ('sha256', 'size_bytes')}, row['path']
        result[row['path']] = value
    actual = set()
    for directory, directories, files in os.walk(ROOT, followlinks=False):
        assert all(not (Path(directory) / name).is_symlink() for name in directories)
        for name in files:
            path = Path(directory) / name
            assert not path.is_symlink()
            actual.add(path.relative_to(ROOT).as_posix())
    assert actual == set(result) | {'report.json'}
    result['report.json'] = identity(ROOT / 'report.json')
    assert result['report.json']['sha256'] == PIN
    return result


def selected_snapshot(document):
    result = {}
    for row in document['staged_files']:
        path = Path(row['path'])
        assert path.resolve(strict=True) == path
        value = identity(path)
        assert value == {key: row[key] for key in ('sha256', 'size_bytes')}
        result[str(path)] = value
    for row in document['helper_sources']:
        path = SOURCE / row['path']
        value = identity(path)
        assert value == {key: row[key] for key in ('sha256', 'size_bytes')}
        result[str(path)] = value
    for row in document['tools'].values():
        path = Path(row['path'])
        resolved = Path(row['resolved_path'])
        assert path.resolve(strict=True) == resolved
        value = identity(resolved)
        assert value == {key: row[key] for key in ('sha256', 'size_bytes')}
        result[str(resolved)] = value
    for row in document['products'].values():
        path = Path(row['original_path'])
        value = identity(path)
        assert value == {key: row[key] for key in ('sha256', 'size_bytes')}
        result[str(path)] = value
    return result


def git_snapshot():
    environment = dict(os.environ, GIT_OPTIONAL_LOCKS='0')
    def run(*args):
        return subprocess.check_output(['git', *args], cwd=SOURCE, env=environment, text=True)
    head = run('rev-parse', 'HEAD', 'HEAD^{tree}').splitlines()
    status = run('status', '--porcelain=v1', '--untracked-files=normal')
    assert head == [REVISION, TREE] and status == ''
    return {'revision': head[0], 'tree': head[1], 'status_porcelain': status}


started = time.monotonic()
initial = identity(ROOT / 'report.json')
assert initial['sha256'] == PIN
document = receipt.decode((ROOT / 'report.json').read_bytes())
assert document['state'] == 'finished' and document['outcome'] == 'pass'
assert document['fresh_dependency_build_passed'] is True and document['reason'] is None
assert document['failures'] == [] and all(document[name] is False for name in contract.FALSE_CLAIMS)
assert document['expected_revision'] == REVISION and document['paths']['source'] == str(SOURCE)
git_before = git_snapshot()
before = packet_snapshot(document)
selected_before = selected_snapshot(document)

# An audit hook observes and rejects process/network execution during the original
# unmodified full reader. No reader function or verifier semantics are mocked.
guard = {'active': False, 'prohibited_events': []}
def deny_execution(event, args):
    prohibited = event.startswith('subprocess.') or event in {
        'os.system', 'os.exec', 'os.fork', 'os.forkpty', 'os.posix_spawn',
        'socket.connect', 'socket.connect_ex', 'socket.bind', 'socket.getaddrinfo'}
    if guard['active'] and prohibited:
        guard['prohibited_events'].append(event)
        raise AssertionError('Inert receipt reader attempted execution: ' + event)
sys.addaudithook(deny_execution)
guard['active'] = True
reader_started = time.monotonic()
checked_document, verification = receipt.load_receipt(ROOT / 'report.json', PIN, REVISION)
reader_seconds = time.monotonic() - reader_started
guard['active'] = False
assert checked_document == document and guard['prohibited_events'] == []
assert verification['fresh_dependency_build_passed'] is True
assert all(verification[name] is False for name in contract.FALSE_CLAIMS)

reader = receipt.PacketReader(ROOT)
records = [receipt.decode(receipt.descriptor(row, reader)) for row in document['records']]
roles = Counter(row['role'] for row in records)
assert roles == {'compile': 406, 'archive': 3, 'index': 2, 'link': 2}
children = [child for record in records for child in record['children']]
assert Counter(child['stage'] for child in children) == {'dependencies': 406, 'tool': 413}
for record in records:
    assert record['state'] == 'finished' and record['outcome'] == 'pass'
    assert record['process_started'] is True and record['exit_code'] == 0
    assert record['inputs_before'] == record['inputs_after']
    last = record['started_ns']
    for child in record['children']:
        assert child['process_started'] is True and child['exit_code'] == 0
        assert last <= child['started_ns'] <= child['finished_ns'] <= record['finished_ns']
        last = child['finished_ns']

manifest = document['source_manifest']
assert manifest['total_files'] == 1294 and manifest['total_size_bytes'] == 10938128
assert contract.digest(manifest) == 'c677abd7a1cbb78cab13c23b40a92a83be427e06c3dffa40419de92b8697cd2e'
sources = []
for source in manifest['sources']:
    for row in source['files']:
        data = receipt.descriptor(dict(path='sources/' + source['name'] + '/' + row['path'],
                                       sha256=row['sha256'], size_bytes=row['size_bytes']), reader)
        assert hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() == row['oid']
    sources.append({key: value for key, value in source.items() if key != 'files'} | {
        'files': len(source['files']), 'size_bytes': sum(row['size_bytes'] for row in source['files'])})
plan = graph.source_plan(manifest, lambda component, name: reader('sources/' + component + '/' + name))
assert plan == document['source_plan']
components = Counter(row['component'] for row in plan)
assert components == {'softfloat': 309, 'ramulator': 60, 'yaml-cpp': 29, 'spdlog': 7, 'extension': 1}
selected = {str(Path(document['paths']['sources']) / row['source']): row for row in plan}
compiles = {}
for record in records:
    if record['role'] == 'compile':
        source_args = [word for word in record['requested_arguments'] if not word.startswith('-') and word.endswith(('.c', '.cpp'))]
        assert len(source_args) == 1
        source = str((Path(record['cwd']) / source_args[0]).resolve())
        assert source in selected and source not in compiles
        compiles[source] = record
assert set(compiles) == set(selected)

edge_count = 0
archives = {}
for row in document['archives']:
    objects = [compiles[str(Path(document['paths']['sources']) / entry['source'])]
               for entry in plan if entry['component'] == row['name']]
    entries = [entry for entry in plan if entry['component'] == row['name']]
    expected_members = [{'name': entry['archive_member'], 'sha256': record['output']['sha256'],
                         'size_bytes': record['output']['size_bytes']} for entry, record in zip(entries, objects)]
    actual = binary.validate_archive(receipt.descriptor(row['descriptor'], reader), expected_members)
    assert actual['members'] == row['members']
    creates = [record for record in records if record['role'] == 'archive' and record['output_path'] == row['original_path']]
    assert len(creates) == 1
    create = creates[0]
    assert create['inputs_before'] == [record['output'] for record in objects]
    assert all(record['finished_ns'] <= create['started_ns'] for record in objects)
    edge_count += len(objects)
    indexes = [record for record in records if record['role'] == 'index' and record['output_path'] == row['original_path']]
    if row['name'] == 'softfloat':
        assert not indexes
        final = create
    else:
        assert len(indexes) == 1 and indexes[0]['output_before'] == create['output']
        assert create['finished_ns'] <= indexes[0]['started_ns']
        final = indexes[0]
        edge_count += 1
    assert all(row['descriptor'][key] == final['output'][key] for key in ('sha256', 'size_bytes'))
    archives[row['name']] = {'path': row['original_path'], 'members': len(actual['members']),
        'descriptor': row['descriptor'], 'creator_record': create['id'],
        'index_record': indexes[0]['id'] if indexes else None,
        'output': final['output'], 'finished_ns': final['finished_ns']}

maps = {}
links = {}
known_archives = {row['original_path'] for row in document['archives']} | {
    row['original_path'] for row in document['external_archives']}
for name in ('ramulator', 'extension'):
    product = document['products'][name]
    matches = [record for record in records if record['role'] == 'link' and record['output_path'] == product['original_path']]
    assert len(matches) == 1
    record = matches[0]
    if name == 'ramulator':
        prerequisites = [row for source, row in compiles.items() if selected[source]['component'] == 'ramulator']
        prerequisites += [archives[key] for key in ('yaml-cpp', 'spdlog')]
        required_loads = [archives[key]['path'] for key in ('yaml-cpp', 'spdlog')]
    else:
        prerequisites = [row for source, row in compiles.items() if selected[source]['component'] == 'extension']
        prerequisites.append(links['ramulator'])
        required_loads = [document['products']['ramulator']['original_path']]
    assert Counter(contract.digest(row['output']) for row in prerequisites) == Counter(contract.digest(row) for row in record['inputs_before'])
    assert all(row['finished_ns'] <= record['started_ns'] for row in prerequisites)
    edge_count += len(prerequisites)
    data = receipt.payload(record['link_map'], reader)
    parsed = binary.parse_link_map(data.decode('utf-8'), cwd=record['cwd'])
    counts = Counter(row['archive'] for row in parsed['selected_members'])
    loads = Counter(parsed['loads'])
    assert all(loads[path] == 1 for path in required_loads)
    assert set(counts) <= known_archives
    assert not any('libstdc++.a' in path or 'libc_nonshared.a' in path for path in counts)
    assert all(product[key] == record['output'][key] for key in ('sha256', 'size_bytes'))
    links[name] = record
    maps[name] = {'sha256': hashlib.sha256(data).hexdigest(), 'size_bytes': len(data),
        'record_id': record['id'], 'selected_archive_members': dict(sorted(counts.items())),
        'required_loads': {path: loads[path] for path in required_loads},
        'support_loads': [path for path in parsed['loads'] if any(word in path for word in ('stdc++', 'libc_nonshared', 'libgcc'))]}

database = receipt.decode(receipt.descriptor(document['compile_database'], reader))
assert len(database) == 97 and len({row['file'] for row in database}) == 97
cmake_sources = {source for source, row in selected.items() if row['component'] in ('ramulator', 'yaml-cpp', 'spdlog')}
main_source = str(Path(document['paths']['sources']) / 'ramulator/src/main.cpp')
assert {str((Path(row['directory']) / row['file']).resolve()) for row in database} == cmake_sources | {main_source}
assert all(shlex.split(row['command'])[0] == document['tools']['g++']['path'] for row in database)
assert len(document['generated_inputs']) == 144
generated = {}
root = Path(document['paths']['sources'])
for record in sorted(records, key=lambda row: row['finished_ns']):
    for key in ('output', 'dependency_file', 'dependency_prepass_file', 'link_map'):
        row = record[key]
        if row is not None and Path(row['path']).is_relative_to(root):
            name = Path(row['path']).relative_to(root).as_posix()
            generated[name] = dict(path=name, sha256=row['sha256'], size_bytes=row['size_bytes'])
assert document['generated_sources'] == [generated[name] for name in sorted(generated)]
labels = ['sources-frozen'] + [prefix + command['id'] for command in document['commands'] for prefix in ('before-', 'after-')] + ['staged-and-verified', 'final']
assert [row['label'] for row in document['stability_checks']] == labels and len(labels) == 13
assert len(document['products']) == 3 and len(document['staged_files']) == 628
preparation = receipt.decode(receipt.descriptor(document['preparation'], reader))
assert preparation['host_tools'] == document['tools'] and len(document['tools']) == 7
assert all(preparation[name] is False for name in contract.FALSE_CLAIMS)
checkout_before = receipt.decode(receipt.descriptor(document['source_checkout_before'], reader))
checkout_after = receipt.decode(receipt.descriptor(document['source_checkout_after'], reader))
assert checkout_before == checkout_after
assert (checkout_before['revision'], checkout_before['tree'], checkout_before['dirty'], checkout_before['blockers']) == (REVISION, TREE, False, [])

after = packet_snapshot(document)
selected_after = selected_snapshot(document)
git_after = git_snapshot()
assert before == after and selected_before == selected_after and git_before == git_after
assert identity(ROOT / 'report.json') == initial
result = {
    'schema_version': 1, 'review': 'wave-07-agent-06-actual-dependency-original-03',
    'observed_at': datetime.now(timezone.utc).isoformat(), 'review_outcome': 'pass',
    'original_outcome': document['outcome'], 'original_report': dict(path=str(ROOT / 'report.json'), **initial),
    'source_revision': REVISION, 'source_tree': TREE, 'source_git_unchanged_clean': True,
    'full_unmocked_receipt_reader': {'accepted': True, 'seconds': round(reader_seconds, 6),
        'execution_guard_enabled': True, 'prohibited_process_network_events': guard['prohibited_events']},
    'retained_files_excluding_report': len(before) - 1,
    'retained_bytes_excluding_report': sum(row['size_bytes'] for path, row in before.items() if path != 'report.json'),
    'whole_packet_files': len(before), 'whole_packet_bytes': sum(row['size_bytes'] for row in before.values()),
    'whole_packet_identity_sha256': contract.digest(before),
    'whole_packet_hashed_before_and_after_unchanged': True, 'exact_directory_membership': True,
    'lexical_posix_inventory_order_passed': True, 'packet_symlinks_or_hardlinks': 0,
    'current_selected_staged_helpers_tools_products_unchanged': True,
    'selected_external_files_hashed_before_and_after': len(selected_before),
    'helper_sources': len(document['helper_sources']), 'selected_host_tools': document['tools'],
    'actual_operation_counts': dict(sorted(roles.items())), 'child_observations': len(children),
    'child_stage_counts': dict(sorted(Counter(row['stage'] for row in children).items())),
    'record_children_ordered_and_successful': True, 'independent_dependency_chronology_edges': edge_count,
    'source_manifest_sha256': contract.digest(manifest), 'source_files': manifest['total_files'],
    'source_bytes': manifest['total_size_bytes'], 'source_git_blobs_rehashed': True, 'source_trees': sources,
    'independently_rederived_source_plan': dict(sorted(components.items())),
    'archive_joins': {name: {key: value for key, value in row.items() if key not in ('output', 'finished_ns')} for name, row in archives.items()},
    'maps': maps, 'external_archives': [row['name'] for row in document['external_archives']],
    'static_libstdcxx_or_libc_nonshared_members': 0,
    'compile_database': dict(document['compile_database'], rows=len(database), built_cmake_sources=len(cmake_sources),
        configured_but_unbuilt_main_source=main_source),
    'cmake_configuration': document['cmake_configuration'], 'generated_cmake_inputs': len(document['generated_inputs']),
    'generated_source_outputs': len(generated), 'generated_source_bytes': sum(row['size_bytes'] for row in generated.values()),
    'products': document['products'], 'staged_files': len(document['staged_files']),
    'staged_bytes': sum(row['size_bytes'] for row in document['staged_files']),
    'stability_boundaries': document['stability_checks'], 'preparation': document['preparation'],
    'source_checkout_before': document['source_checkout_before'], 'source_checkout_after': document['source_checkout_after'],
    'outer_commands': [{key: row[key] for key in ('id', 'outcome', 'exit_code', 'duration_seconds', 'peak_rss_bytes')} for row in document['commands']],
    'budget': document['budget'], 'fresh_dependency_build_passed': True,
    'reviewer_native_execution': 'not_run',
    'limitations': [
        'This reviews a sealed actual dependency original; it does not execute retained commands, rebuild products, or provide a new native outcome.',
        'An inert consistency and hash review does not independently attest every operating-system behavior or establish a cryptographically attested process history.',
        'Selected tools and project inputs are pinned; the host OS, dynamic runtime loader, and every system library are outside complete host provenance.',
        'Fresh dependency provenance is not counter qualification, admission, warm execution, phase acceptance, or performance acceptance.'
    ],
    **dict.fromkeys(contract.FALSE_CLAIMS, False), 'review_seconds': round(time.monotonic() - started, 6)
}
OUT.write_text(json.dumps(result, sort_keys=True, indent=2) + '\n', encoding='utf-8')
print(json.dumps({key: result[key] for key in ('review_outcome', 'original_report', 'whole_packet_files',
    'whole_packet_bytes', 'actual_operation_counts', 'child_observations', 'staged_files',
    'staged_bytes', 'independent_dependency_chronology_edges', 'review_seconds')}, sort_keys=True))
print(json.dumps({'compact_review': str(OUT), **identity(OUT)}, sort_keys=True))
