#!/usr/bin/env python3
"""Read-only source-scope review; no project code or native binary is imported."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import time
import zipfile

BASE = '6aac9c421180805a5621156e3d914c685fc6f4a5'
IMPLEMENTATION = 'e1420fd550f716df33a2556057b7086a03032cbe'
TREE = '3a168adfd345ecb3c15dc02b2583dc832bef6049'
EVIDENCE = 'docs/project/evidence/p05-python/'
INITIAL_MODIFIED = {
    '.github/workflows/project-governance.yml', 'AGENTS.md', 'README.md', 'ROADMAP.md',
    'docs/project/backlog.md', 'docs/project/p05-entry-handoff.md',
    'docs/project/roadmap.json', 'docs/project/status.md',
}
LATER_DOCS = {
    'README.md', 'ROADMAP.md', 'docs/project/backlog.md', 'docs/project/p05-binding-audit.md',
    'docs/project/p05-entry-handoff.md', 'docs/project/roadmap.json', 'docs/project/status.md',
    'docs/project/p05-python-compatibility.md', 'python/README.md',
}
ARCHIVES = {
    'fp16': (6417582, '467122e41bee4e67f9eef285e015b2dee3a52522f0bcb3f497e3cec87e6c7380'),
    'bf16': (6417108, 'e951f943ece1878f3767180c4ce2b859939722d2d639c1afb37b8a72c76006d8'),
}


def encode(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def sha(body):
    return hashlib.sha256(body).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    root, out = args.source_dir, args.output_dir
    require(root.is_absolute() and root.resolve(strict=True) == root, 'noncanonical repository')
    require(out.is_absolute() and out.parent.resolve(strict=True) == out.parent and not out.exists(), 'output must be fresh')
    started = time.monotonic()
    observed_at = datetime.now(timezone.utc).isoformat()

    def git(*argv):
        return subprocess.check_output(['git', '-C', str(root), *argv], stderr=subprocess.PIPE, timeout=60)

    def entries(revision):
        result = {}
        for raw in git('ls-tree', '-r', '-z', revision).split(b'\0'):
            if raw:
                meta, path = raw.split(b'\t', 1)
                mode, kind, object_id = meta.decode().split()
                result[path.decode()] = {'mode': mode, 'type': kind, 'git_object': object_id}
        return result

    def blob(revision, path):
        return git('show', revision + ':' + path)

    cache = {}
    def current(path, expected):
        if expected['type'] == 'commit':
            return {'path': path, **expected, 'scope': 'Gitlink only; submodule worktree contents not reconstructed'}
        file = root / path
        status = file.lstat()
        if expected['mode'] == '120000':
            require(stat.S_ISLNK(status.st_mode), 'symlink type changed: ' + path)
            body = os.fsencode(os.readlink(file))
            size = len(body)
            digest = hashlib.sha1(b'blob ' + str(size).encode() + b'\0' + body).hexdigest()
            digest256 = sha(body)
        else:
            require(stat.S_ISREG(status.st_mode), 'nonregular tracked file: ' + path)
            require(bool(status.st_mode & stat.S_IXUSR) == (expected['mode'] == '100755'), 'executable mode changed: ' + path)
            size = status.st_size
            first = hashlib.sha1(b'blob ' + str(size).encode() + b'\0')
            second = hashlib.sha256()
            with file.open('rb') as stream:
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    first.update(chunk)
                    second.update(chunk)
            after = file.lstat()
            require((status.st_ino, status.st_size, status.st_mtime_ns) ==
                    (after.st_ino, after.st_size, after.st_mtime_ns), 'tracked file changed during read: ' + path)
            digest, digest256 = first.hexdigest(), second.hexdigest()
        require(digest == expected['git_object'], 'worktree differs from recorded Git blob: ' + path)
        value = {'path': path, **expected, 'size_bytes': size, 'sha256': digest256}
        cache[path] = value
        return value

    base, implementation = entries(BASE), entries(IMPLEMENTATION)
    require(git('rev-parse', 'HEAD').decode().strip() == IMPLEMENTATION, 'unexpected current HEAD')
    require(git('rev-parse', IMPLEMENTATION + '^{tree}').decode().strip() == TREE, 'implementation tree differs')
    require(git('rev-parse', IMPLEMENTATION + '^').decode().strip() == BASE, 'implementation parent differs')
    modified = {name for name in base if base[name] != implementation.get(name)}
    added = set(implementation) - set(base)
    require(modified == INITIAL_MODIFIED and len(added) == 66, 'initial 74-file implementation scope differs')
    protected = sorted(set(base) - INITIAL_MODIFIED)
    protected_rows = []
    for name in protected:
        require(base[name] == implementation[name], 'protected Git source changed: ' + name)
        protected_rows.append(current(name, base[name]))

    production = sorted(name for name in implementation if (
        name.startswith(('python/native/', 'python/vortex_ai/', 'ci/project/p05_', 'ci/project/test_p05_', 'ci/project/fixtures/p05_'))
        or name in {'.github/workflows/p05-python.yml', '.github/workflows/project-governance.yml',
                    'AGENTS.md', 'MANIFEST.in', 'pyproject.toml', 'setup.py', 'docs/designs/python_binding_v1.md'}))
    production_rows = [current(name, implementation[name]) for name in production]
    baseline_receipts = sorted(name for name in implementation if name.startswith(EVIDENCE + 'development/')
                               and name != EVIDENCE + 'development/README.md')
    require(len(baseline_receipts) == 31, 'initial receipt/manifest inventory differs')
    initial_receipt_rows = [current(name, implementation[name]) for name in baseline_receipts]

    host_path = EVIDENCE + 'development/host/w06_a1_run.json'
    host_raw = (root / host_path).read_bytes()
    host = json.loads(host_raw)
    host_rows = []
    require(len(host['source_sha256']) == 64 and host['returncode'] == 0 and host['sources_unchanged'] is True, 'host run scope differs')
    for name, expected in sorted(host['source_sha256'].items()):
        row = current(name, implementation[name])
        require(row['sha256'] == sha(blob(IMPLEMENTATION, name)) == expected, 'host-tested source differs: ' + name)
        host_rows.append(row)
    native_path = EVIDENCE + 'development/host/w06_a1-native/results.json'
    native = json.loads((root / native_path).read_bytes())
    host_builds = {}
    for fmt, build in native['builds'].items():
        require(len(build['binding_sources']) == 62, 'host build source count differs')
        require(sha(canonical(build['binding_sources']) + b'\n') == build['source_sha256'], 'host source inventory digest differs')
        for item in build['binding_sources']:
            row = current(item['path'], implementation[item['path']])
            require((row['sha256'], row['size_bytes']) == (item['sha256'], item['size']), 'host build input differs')
        host_builds[fmt] = {'inputs': 62, 'source_sha256': build['source_sha256'], 'scope': 'host-only fake runtime; preserved original digest'}

    archives, binding_rows, manifests = {}, None, {}
    for fmt, (size, digest) in ARCHIVES.items():
        archive_path = EVIDENCE + 'archives/simx-' + fmt + '.zip'
        archive = root / archive_path
        require(archive.stat().st_size == size and sha(archive.read_bytes()) == digest, 'archive changed: ' + fmt)
        with zipfile.ZipFile(archive) as stream:
            manifest = json.loads(stream.read('python/artifacts/bundle/manifest.json'))
            snapshot = json.loads(stream.read('python/snapshots/source-before.json'))
        require(manifest['source_revision'] == IMPLEMENTATION and manifest['source_tree'] == TREE, 'bundle source differs')
        require(snapshot['checkout']['revision'] == IMPLEMENTATION and snapshot['checkout']['tree'] == TREE
                and snapshot['checkout']['dirty'] is False, 'hosted checkout identity differs')
        rows = manifest['binding_sources']
        require(len(rows) == 22 and sha(canonical(rows) + b'\n') == manifest['binding_source_sha256'], 'binding source inventory differs')
        require(binding_rows is None or rows == binding_rows, 'format binding sources differ')
        binding_rows = rows
        for item in rows:
            row = current(item['path'], implementation[item['path']])
            require((row['sha256'], row['size_bytes']) == (item['sha256'], item['size']), 'bound source differs: ' + item['path'])
        archives[fmt] = {'path': archive_path, 'size_bytes': size, 'sha256': digest}
        manifests[fmt] = {'source_revision': manifest['source_revision'], 'source_tree': manifest['source_tree'],
                          'binding_source_sha256': manifest['binding_source_sha256'],
                          'native_qualification_id': manifest['qualification_id']}

    svg = 'docs/assets/img/vortex_framework_stack.svg'
    image_line = lambda raw: [line for line in raw.splitlines() if b'vortex_framework_stack.svg' in line]
    base_embed = image_line(blob(BASE, 'README.md'))
    require(base_embed and base_embed == image_line(blob(IMPLEMENTATION, 'README.md'))
            == image_line((root / 'README.md').read_bytes()), 'protected README embedding changed')
    changed = sorted(x.decode() for x in git('diff', '--name-only', '-z', IMPLEMENTATION).split(b'\0') if x)
    untracked = sorted(x.decode() for x in git('ls-files', '--others', '--exclude-standard', '-z').split(b'\0') if x)
    require(all(path in LATER_DOCS or path.startswith(EVIDENCE) for path in changed + untracked), 'unexpected post-implementation change')

    p05 = next(row for row in json.loads((root / 'docs/project/roadmap.json').read_bytes())['phases'] if row['id'] == 'P05')
    require(p05['status'] == 'in_progress' and p05['evidence'] == [{
        'acceptance_id': 'P05-A01', 'record': EVIDENCE + 'acceptance-binding.json'}], 'phase scope differs')
    acceptance_raw = (root / (EVIDENCE + 'acceptance-binding.json')).read_bytes()
    acceptance = json.loads(acceptance_raw)
    require(acceptance['source_revision'] == IMPLEMENTATION and acceptance['acceptance_ids'] == ['P05-A01']
            and acceptance['outcome'] == 'pass' and acceptance['evidence_level'] == 'simulated', 'acceptance source scope differs')

    groups = {
        'native_runtime_kernel': ('sw/',), 'hardware_rtl': ('hw/',), 'simulators': ('sim/',),
        'native_tests_and_references': ('tests/',), 'profiles': ('profiles/',),
        'inherited_ci_helpers_fixtures_and_goldens': ('ci/',),
        'prior_evidence': ('docs/project/evidence/',), 'prior_designs': ('docs/designs/',),
        'review_policy': ('docs/review/',), 'third_party_source_and_gitlinks': ('third_party/',),
    }
    summaries = {}
    for label, prefixes in groups.items():
        rows = [row for row in protected_rows if row['path'].startswith(prefixes)]
        summaries[label] = {'entries': len(rows), 'blobs': sum(row['type'] == 'blob' for row in rows),
                            'gitlinks': sum(row['type'] == 'commit' for row in rows),
                            'bytes': sum(row.get('size_bytes', 0) for row in rows),
                            'inventory_sha256': sha(canonical(rows)), 'unchanged': True}
    auditors = []
    for name in ('audit_numerics.py', 'audit_dispatch.py', 'audit_provenance.py', 'extract_retained.py'):
        path = EVIDENCE + 'reviews/' + name
        raw = (root / path).read_bytes()
        auditors.append({'path': path, 'size_bytes': len(raw), 'sha256': sha(raw),
                         'scope': 'later independent retained-data tooling; absent from tested implementation commit'})
    source_map = {
        'schema_version': 1, 'map': 'p05-qualified-implementation-source-v1',
        'audited_base': BASE, 'qualified_revision': IMPLEMENTATION, 'qualified_tree': TREE,
        'implementation_delta': {'files': 74, 'added': 66, 'modified': sorted(INITIAL_MODIFIED)},
        'binding_source_sha256': manifests['fp16']['binding_source_sha256'], 'binding_sources': binding_rows,
        'production_test_and_workflow_files': production_rows,
        'host_test_source_receipt': {'path': host_path, 'sha256': sha(host_raw), 'files': 64,
                                    'recorded_base': host['head'], 'clean_qualification': False,
                                    'mapping': 'all 64 source hashes equal the later qualified commit and current files'},
        'host_test_sources': host_rows, 'host_fake_runtime_builds': host_builds,
        'hosted_archives': archives, 'hosted_bundle_sources': manifests,
        'later_review_tools': auditors,
        'later_change_boundary': {'allowed_document_paths': sorted(LATER_DOCS), 'allowed_evidence_prefix': EVIDENCE,
                                  'observed_tracked_paths': changed,
                                  'scope': 'Evidence/audit tooling and handoff docs may change; compiled production and existing tests/workflows remain pinned.'},
        'evidence_mapping': [
            {'kind': 'installed_simx', 'revision': IMPLEMENTATION, 'run': 44866368565,
             'jobs': [136730846147, 136730846328], 'scope': 'Python and native comparison routes; 144 launches and 660 event/profile pairs'},
            {'kind': 'hosted_source_suite', 'revision': IMPLEMENTATION, 'run': 44866368570,
             'job': 136730846161, 'tests': 2174, 'scope': 'clean integrated host/project validation'},
            {'kind': 'supplemental_native_regression', 'revision': IMPLEMENTATION, 'run': 44866368512,
             'scope': 'four separate P04 jobs; executions are not added to P05 counts'},
            {'kind': 'host_fake_runtime', 'original_base': BASE, 'source_hash_mapping': IMPLEMENTATION,
             'scope': '107 maintained scenarios and 11 probes; no accelerator arithmetic or actual device-fault proof'},
        ],
        'not_a_final_tree_attestation': True,
    }
    source_bytes = encode(source_map)
    review = {
        'schema_version': 1, 'audit': 'independent-p05-source-boundary-v1', 'outcome': 'pass',
        'reviewer': '/root/w09_a5_source_boundary_review', 'observed_at_utc': observed_at,
        'source_revision': IMPLEMENTATION, 'source_tree': TREE, 'audited_base': BASE,
        'execution_performed': False, 'acceptance_claimed': False, 'phase_complete': False,
        'source_map': {'path': EVIDENCE + 'source-map.json', 'sha256': sha(source_bytes)},
        'protected_base': {'entries': len(protected_rows), 'blobs': sum(row['type'] == 'blob' for row in protected_rows),
                           'gitlinks': sum(row['type'] == 'commit' for row in protected_rows),
                           'bytes': sum(row.get('size_bytes', 0) for row in protected_rows),
                           'inventory_sha256': sha(canonical(protected_rows)), 'all_unchanged': True},
        'groups': summaries,
        'preserved_assets': [cache['LICENSE'], cache[svg]],
        'readme_embed': {'lines': [line.decode() for line in base_embed], 'unchanged_from_base_and_implementation': True},
        'initial_receipts': {'files': len(initial_receipt_rows), 'inventory_sha256': sha(canonical(initial_receipt_rows)), 'all_unchanged': True},
        'qualified_production_files': len(production_rows), 'host_source_files': len(host_rows), 'binding_source_files': len(binding_rows),
        'acceptance_record_sha256': sha(acceptance_raw), 'post_implementation_tracked_paths': changed,
        'unexpected_changed_or_untracked_paths': [],
        'limitations': [
            'This review verifies byte and Git identities; it executes no compiled binding, native runtime, kernel, simulator, compiler or test suite.',
            'The qualified implementation is e1420fd, not the later documentation/evidence publication commit. New retained-data auditors have separately reviewed source hashes.',
            'All original tracked files except the eight explicitly reviewed first-implementation modifications were checked. Ignored scratch/build outputs are not authoritative source or archived execution proof.',
            'Five third-party Gitlinks are unchanged; uninitialized local submodule contents are not fetched or reconstructed. Recorded external dependency identities are not full transitive reproducibility.',
            'The seven observed tracked documentation changes are a review-time inventory. The explicit nine-path documentation allowance and P05 evidence prefix accommodate planned finalization; no unknown final Git tree is asserted.',
            'P05-A01 is simulated, A02/A03 remain unearned, P05 stays in_progress. P01-A03 and the inherited DSP area finding remain unresolved.',
        ],
    }
    # Recheck all live code/support hashes after the evidence reads, without
    # freezing the unrelated finalization documents other workers still own.
    for name in sorted(set(production) | set(host['source_sha256']) | {row['path'] for row in binding_rows}):
        current(name, implementation[name])
    require(git('rev-parse', 'HEAD').decode().strip() == IMPLEMENTATION, 'HEAD changed during review')
    out.mkdir()
    (out / 'source-map.json').write_bytes(source_bytes)
    (out / 'source-integrity-review.json').write_bytes(encode(review))
    (out / 'protected-inventory.json').write_bytes(encode(protected_rows))
    execution = {'command': ['python3', '-B', str(Path(__file__).resolve()), '--source-dir', str(root), '--output-dir', str(out)],
                 'observed_exit': 0, 'scope': 'read-only source and evidence identities; no native/test execution',
                 'elapsed_seconds': time.monotonic() - started, 'script_sha256': sha(Path(__file__).read_bytes()),
                 'source_map_sha256': sha(source_bytes), 'review_sha256': sha(encode(review)),
                 'protected_entries': len(protected_rows), 'production_files': len(production_rows)}
    (out / 'execution.json').write_bytes(encode(execution))
    print(json.dumps(execution, sort_keys=True))


if __name__ == '__main__':
    main()
