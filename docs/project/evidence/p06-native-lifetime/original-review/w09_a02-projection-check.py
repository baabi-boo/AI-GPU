#!/usr/bin/env python3
"""Inert comparison of retained native source inputs with a committed checkout."""

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import time
import zipfile


REPO = Path('/tmp/ai-gpu-native-lifetime-dfd857')
WORK = Path('/tmp/ai-gpu-native-lifetime-dfd857-work')
ORIGINAL = WORK / 'native-original'
REVISION = 'b4127b19a004b5aebb8d52eab9ceda0da3ff4561'
TREE = 'bd37fb53ab1c34dfebc2ac8805abff5877735fc4'
PACKET = 'docs/project/evidence/p06-native-lifetime/'
ARCHIVE = REPO / PACKET / 'native/b4127b19-run45130300651-attempt1/original.zip'
ARCHIVE_SHA256 = '3d4879f73c197352689d65feb56e73f537701fc1411e55bf53c92b1b41e13db3'
ARCHIVE_BLOB = '5a9dae6b08ca7b3ee789363666be4827eb553ab8'
MUTABLE_DOCS = {
    'README.md', 'docs/index.md', 'docs/project/index.md',
    'docs/project/status.md', 'docs/project/backlog.md',
    'docs/project/p06-managed-preflight-handoff.md',
    'docs/project/p06-mpm-qualification-plan.md',
    'docs/project/phases/p06-performance.md',
    'docs/project/p06-workspace-handoff.md',
}
checks = 0
start = time.monotonic()


def require(condition, message):
    global checks
    checks += 1
    if not condition:
        raise ValueError(message)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def git_blob(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def canonical(data):
    return json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def pairs(values):
    result = {}
    for key, value in values:
        require(key not in result, 'duplicate JSON field: ' + key)
        result[key] = value
    return result


def decode(data):
    return json.loads(data.decode('utf-8'), object_pairs_hook=pairs)


def git(*args):
    return subprocess.check_output(['git', *args], cwd=REPO)


def safe_path(root, name):
    relative = PurePosixPath(name)
    require(not relative.is_absolute() and '..' not in relative.parts
            and str(relative) == name and '\\' not in name, 'unsafe path: ' + name)
    result = root / name
    require(result.resolve().is_relative_to(root.resolve()), 'path escaped root: ' + name)
    require(stat.S_ISREG(result.lstat().st_mode), 'input is not regular: ' + name)
    return result


def descriptor(name, data):
    return {'path': name, 'sha256': sha256(data), 'size_bytes': len(data)}


def descriptor_map(rows):
    result = {}
    for row in rows:
        require(type(row) is dict and set(row) == {'path', 'sha256', 'size_bytes'}, 'descriptor fields differ')
        name = row['path']
        require(type(name) is str and name not in result, 'duplicate descriptor path')
        require(type(row['size_bytes']) is int and row['size_bytes'] >= 0, 'invalid byte size')
        require(type(row['sha256']) is str and re.fullmatch('[0-9a-f]{64}', row['sha256']), 'invalid digest')
        result[name] = row
    return result


def inventory_digest(rows):
    return sha256(canonical(sorted(rows, key=lambda row: row['path'])))


def dependency_group(name):
    prefixes = {
        'third_party/ramulator/ext/spdlog/include/': 'spdlog_including_bundled_fmt',
        'third_party/ramulator/ext/yaml-cpp/include/': 'yaml_cpp',
        'third_party/ramulator/src/': 'ramulator_source',
        'third_party/softfloat/source/': 'softfloat_source',
    }
    matches = [group for prefix, group in prefixes.items() if name.startswith(prefix)]
    require(len(matches) == 1, 'unexpected dependency header family: ' + name)
    return matches[0]


def diff_snapshot():
    raw = git('status', '--porcelain=v1', '-z', '--untracked-files=all')
    rows = []
    for record in raw.split(b'\0'):
        if not record:
            continue
        record = record.decode('utf-8')
        status, name = record[:2], record[3:]
        require('R' not in status and 'C' not in status, 'unexpected rename/copy status')
        if name.startswith(PACKET):
            category = 'lifetime_evidence_and_reviews'
        elif name in MUTABLE_DOCS:
            category = 'current_state_documentation'
        elif name == 'docs/project/p06-dependency-provenance-handoff.md':
            category = 'new_dependency_handoff'
        else:
            category = 'unexpected'
        require(category != 'unexpected', 'unexpected changed path: ' + name)
        rows.append({'path': name, 'status': status, 'category': category})
    return {'paths': rows, 'counts': dict(Counter(row['category'] for row in rows))}


def local_inventory(names):
    result = []
    for name in sorted(names):
        result.append(descriptor(name, safe_path(REPO, name).read_bytes()))
    return result


observed_at = datetime.now(timezone.utc).isoformat()
require(git('rev-parse', 'HEAD').decode().strip() == REVISION, 'HEAD differs from reviewed revision')
require(git('rev-parse', 'HEAD^{tree}').decode().strip() == TREE, 'HEAD tree differs')
diff_before = diff_snapshot()
archive_bytes = ARCHIVE.read_bytes()
require(len(archive_bytes) == 9086055 and sha256(archive_bytes) == ARCHIVE_SHA256, 'repository archive differs')
require(git_blob(archive_bytes) == ARCHIVE_BLOB, 'repository archive Git blob differs')
require((WORK / 'native-original.zip').read_bytes() == archive_bytes, 'repository and downloaded archives differ')
metadata = decode((ARCHIVE.parent / 'artifact-metadata.json').read_bytes())
require(len(metadata['artifacts']) == 1, 'artifact metadata count differs')
require(metadata['artifacts'][0]['digest'] == 'sha256:' + ARCHIVE_SHA256, 'artifact API digest differs')
require(metadata['artifacts'][0]['workflow_run']['head_sha'] == REVISION, 'artifact source revision differs')

with zipfile.ZipFile(ARCHIVE) as archive:
    names = archive.namelist()
    require(len(names) == len(set(names)), 'duplicate ZIP member')

    def member(name):
        data = archive.read(name)
        require(data == safe_path(ORIGINAL, name).read_bytes(), 'extracted original differs: ' + name)
        return data

    managed = decode(member('native-lifetime/report.json'))
    probe = decode(member('pending-probe/report.json'))
    require(managed['expected_revision'] == probe['expected_revision'] == REVISION, 'report revision differs')

    snapshots = []
    for field in ('source_before', 'source_after'):
        row = managed[field]
        data = member('native-lifetime/' + row['path'])
        require(descriptor(row['path'], data) == row, 'source snapshot descriptor differs')
        snapshots.append(decode(data))
    require(snapshots[0] == snapshots[1], 'managed source snapshots differ')
    require(snapshots[0]['checkout']['revision'] == REVISION
            and snapshots[0]['checkout']['tree'] == TREE
            and snapshots[0]['checkout']['dirty'] is False, 'original checkout identity differs')
    require(probe['inputs_before'] == probe['inputs_after'], 'probe source/input stability differs')
    require(probe['inputs_before']['checkout'] == snapshots[0]['checkout'], 'probe checkout differs')
    managed_map = descriptor_map(snapshots[0]['files'])
    probe_map = descriptor_map(probe['inputs_before']['sources'])
    require(len(managed_map) == 1004 and len(probe_map) == 1006, 'source population differs')
    require(all(probe_map[name] == row for name, row in managed_map.items()), 'shared managed/probe source identity differs')
    require(set(probe_map) - set(managed_map) == {
        'ci/project/p06_pending_probe.py', 'tests/unittest/pending_reads/main.cpp'}, 'probe-only source set differs')

    source_copies = {name: [] for name in probe_map}
    retained_map = descriptor_map(managed['retained_sources'])
    require(set(retained_map) == {'artifacts/source/' + name for name in managed_map}, 'retained managed inventory differs')
    for name, row in managed_map.items():
        member_name = 'native-lifetime/artifacts/source/' + name
        data = member(member_name)
        require(descriptor(name, data) == row, 'retained source differs: ' + name)
        require(descriptor('artifacts/source/' + name, data) == retained_map['artifacts/source/' + name], 'retained descriptor differs')
        source_copies[name].append(member_name)
    probe_members = [name for name in names if name.startswith('pending-probe/inputs/') and not name.endswith('/')]
    require(len(probe_members) == 33, 'probe retained input population differs')
    for member_name in probe_members:
        name = member_name.removeprefix('pending-probe/inputs/')
        require(name in probe_map, 'unknown probe retained source')
        require(descriptor(name, member(member_name)) == probe_map[name], 'probe retained source differs')
        source_copies[name].append(member_name)
    require(all(source_copies.values()), 'source descriptor lacks retained bytes')

    tree_map = {}
    for line in git('ls-tree', '-r', '-z', REVISION).split(b'\0'):
        if not line:
            continue
        meta, name = line.split(b'\t', 1)
        mode, kind, oid = meta.decode().split()
        tree_map[name.decode()] = {'mode': mode, 'kind': kind, 'oid': oid}
    root_names = sorted(name for name in probe_map if name in tree_map and tree_map[name]['kind'] == 'blob')
    dependency_names = sorted(set(probe_map) - set(root_names))
    require(len(root_names) == 813 and len(dependency_names) == 193, 'root/dependency partition differs')
    dependency_groups = dict(Counter(dependency_group(name) for name in dependency_names))
    require(dependency_groups == {'spdlog_including_bundled_fmt': 99, 'yaml_cpp': 37,
        'ramulator_source': 50, 'softfloat_source': 7}, 'dependency header family population differs')

    local_before = local_inventory(root_names)
    require(local_before == [probe_map[name] for name in root_names], 'current root source bytes differ')
    object_ids = [tree_map[name]['oid'] for name in root_names]
    objects = subprocess.run(['git', 'cat-file', '--batch'], cwd=REPO,
        input=('\n'.join(object_ids) + '\n').encode(), stdout=subprocess.PIPE, check=True).stdout
    cursor = 0
    root_rows = []
    for name, oid in zip(root_names, object_ids):
        end = objects.index(b'\n', cursor)
        found_oid, kind, size = objects[cursor:end].decode().split()
        size = int(size)
        require(found_oid == oid and kind == 'blob', 'Git object header differs')
        body = objects[end + 1:end + 1 + size]
        require(objects[end + 1 + size:end + 2 + size] == b'\n', 'Git object terminator differs')
        cursor = end + size + 2
        require(descriptor(name, body) == probe_map[name], 'committed blob differs: ' + name)
        local = safe_path(REPO, name)
        require(local.read_bytes() == body, 'current and committed bytes differ: ' + name)
        mode = '100755' if local.stat().st_mode & 0o111 else '100644'
        require(mode == tree_map[name]['mode'], 'current executable mode differs: ' + name)
        for copy in source_copies[name]:
            require(archive.read(copy) == body, 'retained and committed bytes differ: ' + name)
        root_rows.append(dict(probe_map[name], git_blob_sha=oid, git_mode=mode, retained_copies=source_copies[name]))
    require(cursor == len(objects), 'unused Git object output')
    dependency_rows = [dict(probe_map[name], retained_copies=source_copies[name],
        qualification='captured_bytes_only; no root-Git or fresh dependency-build provenance claim')
        for name in dependency_names]

    frozen_names = [name for name in root_names if name.startswith('docs/designs/')]
    require(len(frozen_names) == 7, 'frozen contract population differs')
    frozen_rows = [row for row in root_rows if row['path'] in frozen_names]
    local_after = local_inventory(root_names)
    require(local_after == local_before, 'native source changed during review')

diff_after = diff_snapshot()
require(not set(root_names).intersection(row['path'] for row in diff_after['paths']), 'native source appears in current diff')
require(git('rev-parse', 'HEAD').decode().strip() == REVISION, 'HEAD changed during review')
require(sha256(ARCHIVE.read_bytes()) == ARCHIVE_SHA256, 'archive changed during review')

packaging_inputs = []
for name in ('pyproject.toml', 'MANIFEST.in', 'setup.py', 'python/README.md'):
    committed = git('show', REVISION + ':' + name)
    require(safe_path(REPO, name).read_bytes() == committed, 'packaging context changed: ' + name)
    packaging_inputs.append(descriptor(name, committed))
require('readme = "python/README.md"' in (REPO / 'pyproject.toml').read_text(), 'packaging readme selection differs')
require('exclude README.md' in (REPO / 'MANIFEST.in').read_text(), 'root readme exclusion differs')

root_inventory = [probe_map[name] for name in root_names]
full_inventory = [probe_map[name] for name in sorted(probe_map)]
dependency_inventory = [probe_map[name] for name in dependency_names]
receipt = {
    'scope': 'inert source projection from an executed native original to the currently edited documentation/evidence workspace',
    'observed_at_utc': observed_at, 'outcome': 'pass', 'reviewed_revision': REVISION,
    'reviewed_tree': TREE, 'native_execution': 'not_run', 'retained_code_executed': False,
    'repository_edited_by_this_check': False, 'qualifies_native_counter_lifetime': False,
    'counts': {'managed_sources': 1004, 'probe_union_sources': 1006, 'root_git_sources': 813,
        'captured_dependency_headers': 193, 'source_copy_members_verified': 1004 + len(probe_members),
        'frozen_design_contracts': len(frozen_rows)},
    'inventory_encoding': 'UTF-8 JSON, sort_keys=True, separators=(comma,colon), ensure_ascii=True; rows sorted by path; no trailing newline',
    'inventory_descriptor_fields': ['path', 'sha256', 'size_bytes'],
    'root_source_inventory_sha256': inventory_digest(root_inventory),
    'full_captured_inventory_sha256': inventory_digest(full_inventory),
    'dependency_header_inventory_sha256': inventory_digest(dependency_inventory),
    'frozen_contract_inventory_sha256': inventory_digest([probe_map[name] for name in frozen_names]),
    'current_root_inventory_before_sha256': inventory_digest(local_before),
    'current_root_inventory_after_sha256': inventory_digest(local_after),
    'archive': {'path': str(ARCHIVE.relative_to(REPO)), 'sha256': ARCHIVE_SHA256,
        'size_bytes': len(archive_bytes), 'git_blob_sha': ARCHIVE_BLOB,
        'working_copy_matches_download': True, 'current_api_metadata_matches': True},
    'root_source_join': root_rows, 'captured_dependency_headers': dependency_rows,
    'dependency_header_groups': dependency_groups,
    'frozen_design_contracts': frozen_rows, 'diff_before': diff_before, 'diff_after': diff_after,
    'packaging_context': {'inputs': packaging_inputs, 'selected_readme': 'python/README.md',
        'root_readme_excluded_from_sdist': True,
        'claim': 'No wheel/sdist build, byte identity, or metadata-equivalence result is asserted by this source projection.'},
    'limitations': [
        'The current full working tree differs in documentation/evidence; this does not execute or qualify that later full tree.',
        'Captured dependency-header bytes match retained hashes; immutable transitive origins and fresh dependency builds remain unresolved.',
        'No model object, compiler executable, or final binary is rebuilt or executed by this check.',
        'Concurrent authorized documentation edits are recorded as point-in-time diff snapshots; native inputs are checked before and after.',
        'The pending final commit/ref publication must separately preserve these bytes and the exact ZIP Git blob.'
    ],
    'reviewer_correction': {
        'initial_assumption': 'All 193 non-root-Git source headers were under the fetched spdlog/yaml include roots.',
        'correction': 'The exact population also contains 50 Ramulator source headers and 7 SoftFloat source headers under the pinned submodule paths.',
        'production_or_artifact_changed': False,
    },
    'inert_assertions': checks, 'seconds': time.monotonic() - start,
}
target = WORK / 'w09_a02-projection.json'
target.write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps({key: receipt[key] for key in ('outcome', 'counts', 'root_source_inventory_sha256',
    'full_captured_inventory_sha256', 'dependency_header_inventory_sha256',
    'frozen_contract_inventory_sha256', 'inert_assertions', 'seconds')}, sort_keys=True))
