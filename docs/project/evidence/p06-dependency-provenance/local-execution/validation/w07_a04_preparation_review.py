"""Read-only original preparation review; never runs retained commands or tools."""

import ast
import datetime
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time

SOURCE = Path('/workspace/p06-local-run-source-03')
WORKSPACE = Path('/workspace/p06-local-native-run-03')
HOST = Path('/workspace/p06-local-host-02')
OUT = Path('/workspace/scratch/279b6658611e/validation/w07_a04-preparation-review.json')
REVISION = '7251f078972c1d524de06d069e91b014b55896f5'
TREE = 'c44b5a93ab3aabaf2438e9e7d102339c9dc80542'
HOST_PIN = '1a205a1d080753490669664c61236a2102176aff1457529415809740ad70f4ce'
SOURCE_MANIFEST_PIN = 'c677abd7a1cbb78cab13c23b40a92a83be427e06c3dffa40419de92b8697cd2e'
FALSE_CLAIMS = ('qualified', 'ready_for_warm', 'warm_execution', 'full_warm_coverage',
                'acceptance_claimed', 'phase_acceptance', 'performance_acceptance')
NATIVE_TOOLS = {
    **{name: 'llvm-vortex/bin/' + name for name in ('clang', 'clang++', 'llvm-objcopy', 'llvm-objdump')},
    **{'riscv-' + name: 'riscv64-gnu-toolchain/bin/riscv64-unknown-elf-' + name
       for name in ('gcc', 'gcc-ar', 'objdump', 'objcopy')},
    **{name: name for name in ('libc64/lib/libc.a', 'libc64/lib/libm.a',
                              'libcrt64/lib/baremetal/libclang_rt.builtins-riscv64.a')},
}
EXPECTED_GITLINKS = {
    'third_party/cocogfx': 'b1befdb36df8af7ac9e2c96acaf81957aab5d107',
    'third_party/cvfpu': '79e453139072df42c9ec8f697132ba485d74e23d',
    'third_party/cvfpu/src/common_cells': '6aeee85d0a34fedc06c14f04fd6363c9f7b4eeea',
    'third_party/cvfpu/src/fpu_div_sqrt_mvp': '86e1f558b3c95e91577c41b2fc452c86b04e85ac',
    'third_party/cvfpu/tb/flexfloat': '28be2d4fbf41b38fc37763bb6e90a1c88f6aaa61',
    'third_party/hardfloat': 'aaf5736dffa521603b681fd5853760c671446c85',
    'third_party/ramulator': 'e62c84a6f0e06566ba6e182d308434b4532068a5',
    'third_party/softfloat': 'b51ef8f3201669b2288104c28546fc72532a1ea4',
}

def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()

def digest(path):
    before = path.stat()
    value = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 ** 2):
            value.update(chunk)
    after = path.stat()
    assert (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) == (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    assert stat.S_ISREG(after.st_mode)
    return {'sha256': value.hexdigest(), 'size_bytes': after.st_size}

def canonical_digest(document):
    body = json.dumps(document, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                      allow_nan=False).encode()
    return hashlib.sha256(body).hexdigest()

def identity(path):
    return {'path': str(path), 'resolved_path': str(path.resolve(strict=True)), **digest(path)}

started = time.monotonic()
report_path = WORKSPACE / 'evidence/dependency-preparation.json'
original = report_path.read_bytes()
document = json.loads(original)
prior = json.loads(Path('/workspace/p06-local-native-run-02/evidence/dependency-preparation.json').read_text())
host_original = (HOST / 'receipt.json').read_bytes()
assert hashlib.sha256(host_original).hexdigest() == HOST_PIN
host_receipt = json.loads(host_original)
assert host_receipt['outcome'] == 'pass' and len(host_receipt['packages']) == 7
assert git(SOURCE, 'rev-parse', 'HEAD') == REVISION
assert git(SOURCE, 'rev-parse', 'HEAD^{tree}') == TREE
assert git(SOURCE, 'status', '--porcelain=v1', '--untracked-files=all') == ''
gitlinks = {}
for line in subprocess.check_output(['git', '-C', str(SOURCE), 'submodule', 'status', '--recursive'], text=True).splitlines():
    assert line[0] == ' '
    sha, name, *_ = line[1:].split()
    gitlinks[name] = sha
assert gitlinks == EXPECTED_GITLINKS
assert document['contract_id'] == 'p06-local-dependency-preparation-v1'
assert document['execution_origin'] == 'local'
assert document['expected_revision'] == REVISION
assert document['outcome'] == 'pass' and document['reason'] is None and document['failures'] == []
assert document['source_before'] == document['source_after']
assert document['source_before']['revision'] == REVISION and document['source_before']['tree'] == TREE
assert document['source_before']['dirty'] is False and document['source_before']['outcome'] == 'pass'
assert document['source_before']['changed_paths'] == document['source_before']['untracked_paths'] == []
assert document['native_execution'] == 'not_run'
assert all(document[name] is False for name in (*FALSE_CLAIMS, 'dependency_cache_used', 'toolchain_cache_used', 'network_acquisition'))
assert document['source_manifest'] == prior['source_manifest']
assert canonical_digest(document['source_manifest']) == SOURCE_MANIFEST_PIN
assert document['host_tools'] == prior['host_tools']
assert document['budget'] == prior['budget']
assert document['source_dir'] == str(SOURCE) and document['workspace_dir'] == str(WORKSPACE)
assert document['tools_dir'] == str(WORKSPACE / 'tools')
assert document['host_bin'] == str(HOST / 'bin')
assert document['archive_root'] == prior['archive_root']
assert document['dependency_repositories_root'] == prior['dependency_repositories_root']

module = ast.parse((SOURCE / 'ci/project/p06_dependency_contract.py').read_text())
pins = next(ast.literal_eval(node.value) for node in module.body if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == 'PINS' for target in node.targets))
dependency_trees = {}
for name, pin in pins.items():
    path = SOURCE / pin['path'] if name in ('softfloat', 'ramulator') else Path('/workspace/p06-pinned-inputs') / name
    assert document['repositories'][name] == str(path)
    observed = git(path, 'rev-parse', pin['revision'] + '^{tree}')
    assert observed == pin['tree']
    dependency_trees[name] = {'revision': pin['revision'], 'tree': observed, 'repository': str(path)}

toolchain = document['toolchain_receipt']
prior_toolchain = prior['toolchain_receipt']
for field in ('parts', 'members', 'member_count', 'compressed_bytes', 'extracted_regular_bytes',
              'manifest_sha256', 'manifest_size_bytes', 'manifest_semantic_sha256', 'repository',
              'revision', 'tag', 'selected_components', 'budget', 'origin', 'native_execution', 'outcome'):
    assert toolchain[field] == prior_toolchain[field], field
assert toolchain['outcome'] == 'pass' and toolchain['native_execution'] == 'not_run'
assert all(toolchain[name] is False for name in FALSE_CLAIMS)
assert toolchain['tools_root'] == str(WORKSPACE / 'tools')
assert set(toolchain['tools']) == set(NATIVE_TOOLS)
archive_observations = []
for part in toolchain['parts']:
    path = Path(document['archive_root']) / part['path']
    observed = digest(path)
    assert observed == {key: part[key] for key in ('sha256', 'size_bytes')}
    archive_observations.append({'path': part['path'], **observed})
native_tools = {}
for name, relative in NATIVE_TOOLS.items():
    path = WORKSPACE / 'tools' / relative
    observed = identity(path)
    assert path.resolve(strict=True).is_relative_to(WORKSPACE / 'tools')
    assert observed == toolchain['tools'][name]
    assert all(observed[key] == prior_toolchain['tools'][name][key] for key in ('sha256', 'size_bytes'))
    assert name.startswith(('libc64/', 'libcrt64/')) or os.access(path, os.X_OK)
    native_tools[name] = observed
host_tools = {}
for name, expected in document['host_tools'].items():
    observed = identity(Path(expected['path']))
    assert observed == expected and os.access(observed['path'], os.X_OK)
    host_tools[name] = observed
runtime = host_receipt['selected_shared_runtime']
assert identity(Path(runtime['path'])) == runtime

sealed_copy = WORKSPACE / 'evidence/dependency-build/preparation.json'
assert sealed_copy.read_bytes() == original
assert report_path.read_bytes() == original and (HOST / 'receipt.json').read_bytes() == host_original
envelope = json.loads((WORKSPACE / 'evidence/local-execution.json').read_text())
stage = next(row for row in envelope['stages'] if row['id'] == 'preparation')
assert stage['outcome'] == 'pass' and stage['exit_code'] == 0 and stage['cleanup_complete'] is True
assert stage['peak_rss_bytes'] <= document['budget']['max_rss_bytes']
assert stage['log_size_bytes'] <= document['budget']['max_log_bytes']
assert stage['duration_seconds'] <= 1800
for point in ('resources_before', 'resources_after'):
    resources = document[point]
    assert min(resources['free_disk_bytes'].values()) >= document['budget']['min_free_bytes']
    assert resources['available_memory_bytes'] >= document['budget']['max_rss_bytes']

unchanged = []
for attempt, expected in [('01', ('97fe819aacd6d308e0c799701344efe5bd7229ac4d737f0c04ff1e69956151b1',
                                 '1e1c336d2d1c078aa041ccbe698d917370190f4f420f9d4481552514095d9f2a')),
                          ('02', ('344c43fe145a76f11938c45abcdb940ddda5a47da52c9ced6249713b9d62123b',
                                  '567f5e34826ddc9d510cf242361f3afb112a7e8fbcdccfc556cbe2df236285ed'))]:
    root = Path('/workspace/p06-local-native-run-' + attempt + '/evidence')
    actual = (digest(root / 'dependency-build/report.json'), digest(root / 'local-execution.json'))
    assert tuple(row['sha256'] for row in actual) == expected
    unchanged.append({'attempt': attempt, 'dependency_report': actual[0], 'local_envelope': actual[1]})
assert git(SOURCE, 'status', '--porcelain=v1', '--untracked-files=all') == ''
reviewed_names = ['ci/project/p06_dependency_build.py', 'ci/project/p06_dependency_control_replay.py',
                  'ci/project/p06_local_toolchain.py', 'ci/project/p06_dependency_local_prepare.py',
                  'ci/project/p06_dependency_contract.py', 'ci/project/p01_toolchain.lock.json']
source_ids = {name: digest(SOURCE / name) for name in reviewed_names}
for name in reviewed_names:
    assert (SOURCE / name).read_bytes() == subprocess.check_output(['git', '-C', str(SOURCE), 'show', REVISION + ':' + name])

result = {
    'schema_version': 1, 'scope': 'Independent fresh attempt03 source/preparation/tool identity review only',
    'outcome': 'pass', 'established_findings': [], 'source_revision': REVISION, 'source_tree': TREE,
    'initial_observation': {'observed_at': '2026-11-23T12:56:53.970060+00:00',
                            'source_status': 'clean', 'workspace_entries': ['evidence', 'local-home', 'local-tmp'],
                            'tools_directory_existed': False},
    'completed_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'duration_seconds': round(time.monotonic() - started, 6),
    'preparation': {'path': str(report_path), 'sha256': hashlib.sha256(original).hexdigest(), 'size_bytes': len(original),
                    'retained_copy_identical': True, 'original_unchanged': True,
                    'stage_duration_seconds': stage['duration_seconds'], 'peak_rss_bytes': stage['peak_rss_bytes']},
    'recursive_gitlinks': gitlinks, 'dependency_trees': dependency_trees,
    'source_manifest_sha256': SOURCE_MANIFEST_PIN,
    'source_manifest_files': document['source_manifest']['total_files'],
    'source_manifest_bytes': document['source_manifest']['total_size_bytes'],
    'source_manifest_equals_failed02': True, 'toolchain_member_metadata_equals_failed02': True,
    'archive_parts': archive_observations, 'member_count': toolchain['member_count'],
    'extracted_regular_bytes': toolchain['extracted_regular_bytes'],
    'native_tools': native_tools, 'host_tools': host_tools,
    'host_receipt_sha256': HOST_PIN, 'selected_shared_runtime': runtime,
    'failed_original_pins_unchanged': unchanged, 'source_files': source_ids,
    'resource_observations': {name: document[name] for name in ('resources_before', 'resources_after')},
    'native_execution_by_reviewer': 'not_run', 'retained_code_executed': False,
    'qualification_or_acceptance_claimed': False,
    'limits': ['Actual dependency compilation, managed native execution and both separate controls are outside this preparation review.',
               'The 6,122-member metadata is compared with the independently reviewed prior installation; this review rehashes all 15 archive parts and 11 selected native identities, not all installed members.',
               'Before/after observations do not protect against malicious concurrent writers; system runtime and complete host-toolchain provenance remain outside scope.'],
}
OUT.write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({'outcome': 'pass', 'report': str(OUT), 'preparation': result['preparation'],
                  'source_manifest_sha256': SOURCE_MANIFEST_PIN, 'archive_parts': len(archive_observations),
                  'native_tools': len(native_tools), 'host_tools': len(host_tools),
                  'duration_seconds': result['duration_seconds']}, indent=2))
