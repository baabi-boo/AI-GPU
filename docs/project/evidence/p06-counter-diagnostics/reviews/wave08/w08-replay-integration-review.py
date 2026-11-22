#!/usr/bin/env python3
"""Independent, read-only R3 review of caller-pinned replay integration."""
import ast
import builtins
from contextlib import ExitStack, redirect_stdout
import copy
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
import zipfile

sys.dont_write_bytecode = True
ROOT = Path('/workspace/scratch/98908dfa3444/AI-GPU')
OUT = ROOT.parent
sys.path.insert(0, str(ROOT / 'ci/project'))
import baseline_packet_io
import p06_counter_diagnostics_replay as checked
import p06_counter_public_replay as public
import p06_counter_source_inventory as inventory
import test_p06_counter_inventory_replay as authored_tests

PINS = {
    'ci/project/p06_counter_diagnostics_replay.py': '4d959363229859bd1ac5f4ede4f09937b8418e50f85a1c2eab3f131956532f0b',
    'ci/project/p06_counter_public_replay.py': '6489dff8b39bda3d18df97fb72092fd2014d86d8c0129bcd56a13f08acd942a0',
    'ci/project/test_p06_counter_inventory_replay.py': 'c710288b344930cb3f0a9ca6b8092c87f4ae71fbc0952cdf712d4627892290c9',
    'ci/project/p06_counter_source_inventory.py': '8961331993ceb112f80a83314ee7a6a3020163a89ca1b8781139c103e98f6862',
}
NATIVE = ROOT / 'docs/project/evidence/p06-counter-diagnostics/native'
FALSE = ('qualified', 'ready_for_warm', 'warm_execution', 'acceptance', 'acceptance_claimed',
         'phase_acceptance', 'performance_acceptance', 'full_warm_coverage', 'retained_code_executed')
HEADER = 'sim/common/axi_latency_pipe.h'
PUBLIC_REV = 'e5f152464dda5e488d6d1a030c1fcdc49b5a9701'
PUBLIC_SHA = '05f79eef4c9e30b97302e02fec9e2cca47e08fc10c4d5f8235b21f40f41d7276'
CHECKED_REV = '407ab9fea5e4f793a2a5088f566a87f3e631aa84'
CHECKED_SHA = 'c4a7ae49259bbb72066d55f7c3e733ce5696f215175ce308f654e1cec9e9c13f'
FAILED_REV = '81ed6871634fefbf5c78fb27cf10dce913bd4d9c'
FAILED_SHA = 'd628813ec8815140830825adef22cd2ea9191707686931e49145d5a4e4247db5'

def digest(body):
    return hashlib.sha256(body).hexdigest()

def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()

def pin_files():
    for name, expected in PINS.items():
        assert digest((ROOT / name).read_bytes()) == expected, name

def fixture(reader, filename, sha256, revision, prefix):
    path = NATIVE / filename
    assert digest(path.read_bytes()) == sha256
    with zipfile.ZipFile(path) as archive:
        members = {row.filename: archive.read(row) for row in archive.infolist() if not row.is_dir()}
    report = json.loads(members[prefix + '/report.json'])
    return dict(reader=reader, path=path, sha256=sha256, revision=revision,
                prefix=prefix, members=members, report=report)

def manifest(fix):
    return dict(schema_version=1, contract_id=inventory.CONTRACT_ID,
                producer_contract_id=fix['reader'].CONTRACT_ID,
                source_revision=fix['revision'], sources=copy.deepcopy(fix['report']['source_before']['files']))

pin_files()
FIXTURES = [
    fixture(checked, 'run-45026112992-attempt1.zip', CHECKED_SHA, CHECKED_REV, 'checked-counters'),
    fixture(public, 'run-45031746149-attempt1.zip', PUBLIC_SHA, PUBLIC_REV, 'public-counters'),
]
FAILED = fixture(public, 'run-45029135146-attempt1.zip', FAILED_SHA, FAILED_REV, 'public-counters')
intake = json.loads((NATIVE / 'public-runtime-pass.json').read_bytes())
assert intake == dict(archive=FIXTURES[1]['path'].name, sha256=PUBLIC_SHA, source_revision=PUBLIC_REV)
RECEIPT = {'scope': 'independent R3 retained-data replay integration review', 'agent': 44,
           'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
           'reviewed_sha256': PINS, 'findings': [], 'checks': [],
           'native_execution': 'not_run', 'qualification': False,
           'limits': ['No native builds or execution, full discovery, archived-code execution, repository edits, commits or push.',
                      'Manifest generated from archive descriptors is initially only a synthetic wiring expectation.',
                      'Separate Git blob comparisons bind source bodies to the named local immutable Git commit; no new remote-origin authentication.',
                      'Source consistency does not authenticate absent objects, binaries, native execution, or qualification.']}

def verify_git_sources(fix):
    """Independent immutable-Git comparison, outside the replay implementation."""
    rows = fix['report']['source_before']['files']
    requests = ''.join(fix['revision'] + ':' + row['path'] + '\n' for row in rows).encode()
    command = ['git', 'cat-file', '--batch']
    completed = subprocess.run(command, cwd=ROOT, input=requests, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, check=True)
    stream = io.BytesIO(completed.stdout)
    compared = []
    for row in rows:
        header = stream.readline().decode().rstrip('\n').split(' ')
        assert len(header) == 3 and header[1] == 'blob', (row['path'], header)
        body = stream.read(int(header[2]))
        assert stream.read(1) == b'\n'
        assert (digest(body), len(body)) == (row['sha256'], row['size_bytes']), row['path']
        assert body == fix['members'][fix['prefix'] + '/artifacts/source/' + row['path']], row['path']
        compared.append(dict(path=row['path'], git_blob=header[0], sha256=digest(body), size_bytes=len(body)))
    assert stream.read() == b''
    return dict(command=command, revision=fix['revision'], compared=len(compared), mismatches=0,
                source_names_sha256=digest(''.join(row['path'] + '\n' for row in rows).encode()),
                git_tree=subprocess.check_output(['git', 'rev-parse', fix['revision'] + '^{tree}'], cwd=ROOT, text=True).strip(),
                files=compared)

git_check = verify_git_sources(FIXTURES[1])
(OUT / 'w08-replay-integration-public-git.json').write_bytes(encoded(git_check))
RECEIPT['immutable_git_check'] = {key: value for key, value in git_check.items() if key != 'files'}
print('Immutable Git: all', git_check['compared'], 'public source descriptors and retained bodies matched', PUBLIC_REV, flush=True)

PUBLIC_MANIFEST = OUT / 'w08-replay-integration-public-inventory.json'
PUBLIC_MANIFEST.write_bytes(encoded(manifest(FIXTURES[1])))
RECEIPT['public_manifest'] = dict(path=str(PUBLIC_MANIFEST), sha256=digest(PUBLIC_MANIFEST.read_bytes()),
    origin='Copied from genuine report for wiring; all 676 descriptors separately compared to immutable Git blobs')

def import_closure(start):
    queue, found = [start], set()
    while queue:
        name = queue.pop()
        if name in found:
            continue
        found.add(name)
        path = ROOT / 'ci/project' / (name + '.py')
        for node in ast.walk(ast.parse(path.read_bytes(), filename=str(path))):
            names = [alias.name.split('.')[0] for alias in node.names] if isinstance(node, ast.Import) else \
                    [node.module.split('.')[0]] if isinstance(node, ast.ImportFrom) and node.module else []
            for child in names:
                if (ROOT / 'ci/project' / (child + '.py')).is_file():
                    queue.append(child)
    return {'ci/project/' + name + '.py' for name in found}

RECEIPT['closures'] = []
for reader in (checked, public):
    expected = import_closure(reader.__name__)
    rows = reader._reader_sources()
    actual = {row['path'] for row in rows}
    assert expected <= actual, sorted(expected - actual)
    assert len(actual) == len(rows)
    RECEIPT['closures'].append(dict(reader=reader.__name__, transitive_local_imports=len(expected),
        reported_sources=len(rows), missing=sorted(expected - actual), extra=sorted(actual - expected), sources=rows))
print('Import closure: checked and public cover all transitive repository Python imports', flush=True)

class CountResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.subtests = 0
    def addSubTest(self, test, subtest, err):
        self.subtests += 1
        super().addSubTest(test, subtest, err)

class IndependentPublicInventoryReview(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='w08-replay-review-')
        self.addCleanup(temporary.cleanup)
        self.temporary = Path(temporary.name)
        self.inventory_path = self.temporary / 'source-inventory.json'
        self.synthetic_path = self.temporary / 'synthetic.zip'

    def options(self, fix, transform=None):
        value = manifest(fix)
        if transform:
            transform(value)
        body = encoded(value)
        self.inventory_path.write_bytes(body)
        return dict(source_inventory=self.inventory_path, source_inventory_sha256=digest(body))

    def replay(self, fix, members=None, **options):
        path, sha256 = fix['path'], fix['sha256']
        if members is not None:
            with zipfile.ZipFile(self.synthetic_path, 'w', compression=zipfile.ZIP_STORED) as archive:
                for name, body in sorted(members.items()):
                    archive.writestr(name, body)
            path, sha256 = self.synthetic_path, digest(self.synthetic_path.read_bytes())
        return fix['reader'].replay_archive(path, sha256, expected_revision=fix['revision'], **options)

    def claims(self, result):
        self.assertEqual(result['native_execution'], 'not_run')
        for name in FALSE:
            self.assertIs(result[name], False, name)

    def edit_report(self, members, fix, transform):
        key = fix['prefix'] + '/report.json'
        value = json.loads(members[key])
        transform(value)
        members[key] = encoded(value)

    def test_genuine_complete_public_both_routes_and_uint64_preservation(self):
        fix = FIXTURES[1]
        legacy = self.replay(fix)
        options = self.options(fix)
        external = self.replay(fix, **options)
        for value, source in ((legacy, 'original-inventory'), (external, 'external-manifest')):
            self.assertEqual((value['outcome'], value['retained_source_files'], value['commands_checked'],
                              value['cells_checked'], value['public_cells_checked']), ('pass', 676, 14, 6, 5))
            self.assertEqual(value['source_inventory_sha256'], public.PUBLIC_V1_SOURCE_INVENTORY_SHA256)
            self.assertEqual(value['source_inventory_expectation']['source'], source)
            self.assertEqual(value['source_inventory_expectation']['source_files'], 676)
            self.assertEqual(value['source_inventory_expectation']['source_names_sha256'], value['source_inventory_sha256'])
            self.assertEqual((value['model']['translation_units'], value['public']['translation_units'],
                              value['public']['reused_model_objects']), (45, 19, 44))
            self.claims(value)
            self.assertEqual(json.loads(encoded(value)), value)
            for cell, original in zip(value['public']['cells'], fix['report']['cells']):
                checked._same(cell['observations'], original['observations'], 'exact integer observations')
            seeds = [cell['observations']['failure']['seed'] for cell in value['public']['cells']
                     if cell['id'] in ('public-immediate-overflow', 'public-delayed-overflow', 'public-cache-overflow')]
            self.assertEqual(seeds, [(1 << 64) - 1, (1 << 64) - 3, (1 << 64) - 1])
            self.assertTrue(all(type(seed) is int for seed in seeds))
        self.assertIsNone(legacy['source_inventory_expectation']['manifest_path'])
        self.assertIsNone(legacy['source_inventory_expectation']['manifest_sha256'])
        receipt = external['source_inventory_expectation']
        self.assertEqual(receipt['manifest_path'], str(self.inventory_path))
        self.assertEqual(receipt['manifest_sha256'], options['source_inventory_sha256'])
        self.assertIn('do not independently prove Git/GitHub provenance, binary contents or execution', receipt['trust_boundary'])
        left, right = dict(legacy), dict(external)
        del left['source_inventory_expectation'], right['source_inventory_expectation']
        self.assertEqual(left, right)
        for label, result in (('legacy', legacy), ('external', external)):
            (OUT / ('w08-replay-integration-public-' + label + '-result.json')).write_bytes(encoded(result))

    def test_failed_public_original_remains_failed_both_routes(self):
        for options in ({}, self.options(FAILED)):
            with self.subTest(external=bool(options)), self.assertRaisesRegex(ValueError, 'producer outcome'):
                self.replay(FAILED, **options)

    def test_both_apis_missing_pair_before_archive_open(self):
        for fix in FIXTURES:
            for options in ({'source_inventory': self.inventory_path}, {'source_inventory_sha256': '0' * 64},
                            {'source_inventory': ''}, {'source_inventory_sha256': ''}):
                with self.subTest(reader=fix['reader'].__name__, options=str(options)), \
                     mock.patch.object(checked, 'open_archive', side_effect=AssertionError('archive opened')), \
                     self.assertRaisesRegex(ValueError, 'supplied together'):
                    self.replay(fix, **options)

    def test_wrong_digest_and_mistyped_digest_never_fall_back(self):
        for fix in FIXTURES:
            options = self.options(fix)
            for bad in ('0' * 64, '', True, 1, 'A' * 64, 'f' * 63):
                with self.subTest(reader=fix['reader'].__name__, bad=bad), self.assertRaises(ValueError):
                    self.replay(fix, **dict(options, source_inventory_sha256=bad))

    def test_wrong_revision_or_producer_reject_on_genuine_public(self):
        fix = FIXTURES[1]
        for key, value, match in (('source_revision', FAILED_REV, 'revision differs'),
                                  ('producer_contract_id', checked.CONTRACT_ID, 'producer contract differs')):
            options = self.options(fix, lambda manifest: manifest.__setitem__(key, value))
            with self.subTest(field=key), self.assertRaisesRegex(ValueError, match):
                self.replay(fix, **options)

    def test_public_header_and_helper_omission_still_reject(self):
        fix = FIXTURES[1]
        for omitted in (HEADER, 'ci/project/baseline_packet_io.py'):
            for both in (False, True):
                options = self.options(fix, lambda value: value.update(sources=[row for row in value['sources'] if row['path'] != omitted]))
                members = None
                if both:
                    members = dict(fix['members'])
                    del members[fix['prefix'] + '/artifacts/source/' + omitted]
                    def remove(report):
                        for key in ('source_before', 'source_after'):
                            report[key]['files'] = [row for row in report[key]['files'] if row['path'] != omitted]
                        report['retained_sources'] = [row for row in report['retained_sources'] if row['path'] != 'artifacts/source/' + omitted]
                    self.edit_report(members, fix, remove)
                with self.subTest(omitted=omitted, packet_and_manifest=both), self.assertRaisesRegex(ValueError, 'omits an original required body'):
                    self.replay(fix, members=members, **options)

    def test_public_hash_size_and_full_manifest_swap_reject(self):
        fix = FIXTURES[1]
        for field, value in (('sha256', '0' * 64), ('size_bytes', 1)):
            def change(manifest):
                next(row for row in manifest['sources'] if row['path'] == HEADER)[field] = value
            options = self.options(fix, change)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'archive source descriptors differ'):
                self.replay(fix, **options)
        options = self.options(FAILED, lambda value: value.update(source_revision=PUBLIC_REV))
        with self.assertRaisesRegex(ValueError, 'archive source descriptors differ'):
            self.replay(fix, **options)

    def test_explicit_invalid_manifest_never_falls_back(self):
        fix = FIXTURES[1]
        for body in (b'', b'{', b'{"schema_version":1,"schema_version":1}'):
            self.inventory_path.write_bytes(body)
            with self.subTest(body=body), self.assertRaises(ValueError):
                self.replay(fix, source_inventory=self.inventory_path, source_inventory_sha256=digest(body))
        options = self.options(fix)
        self.inventory_path.unlink()
        with self.assertRaisesRegex(ValueError, 'cannot be read safely'):
            self.replay(fix, **options)
        target = self.temporary / 'target.json'
        target.write_bytes(encoded(manifest(fix)))
        self.inventory_path.symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'cannot be read safely'):
            self.replay(fix, **options)

    def test_manifest_replaced_during_read_is_rejected(self):
        fix = FIXTURES[1]
        options = self.options(fix)
        replacement = self.temporary / 'replacement.json'
        replacement.write_bytes(self.inventory_path.read_bytes())
        original_read = os.read
        swapped = False
        def read_and_swap(fd, length):
            nonlocal swapped
            body = original_read(fd, length)
            if not swapped:
                os.replace(replacement, self.inventory_path)
                swapped = True
            return body
        with mock.patch.object(baseline_packet_io.os, 'read', read_and_swap), \
             self.assertRaisesRegex(ValueError, 'changed during reading'):
            self.replay(fix, **options)
        self.assertTrue(swapped)

    def test_public_retained_raw_bytes_still_hash_checked(self):
        fix = FIXTURES[1]
        options = self.options(fix)
        members = dict(fix['members'])
        members[fix['prefix'] + '/artifacts/source/' + HEADER] += b'changed without descriptor update\n'
        with self.assertRaisesRegex(ValueError, 'retained descriptor hash or size differs'):
            self.replay(fix, members=members, **options)

    def test_public_current_helper_drift_rejects_every_reported_closure_file(self):
        fix = FIXTURES[1]
        options = self.options(fix)
        original_read, original_load = Path.read_bytes, inventory.load_source_inventory
        for row in public._reader_sources():
            changed = False
            target = ROOT / row['path']
            def drift_load(*args, **kwargs):
                nonlocal changed
                result = original_load(*args, **kwargs)
                changed = True
                return result
            def observed(path):
                body = original_read(path)
                return body + b'\n# mocked independent drift observation\n' if changed and path == target else body
            with self.subTest(path=row['path']), mock.patch.object(Path, 'read_bytes', observed), \
                 mock.patch.object(inventory, 'load_source_inventory', drift_load), \
                 self.assertRaisesRegex(ValueError, 'trusted (public )?reader source stability'):
                self.replay(fix, **options)

    def test_public_successful_external_replay_filesystem_and_execution_guard(self):
        fix = FIXTURES[1]
        options = self.options(fix)
        parser = ROOT / checked.trusted.ARCHIVE_READER_PATH
        allowed = {fix['path'], self.inventory_path, parser, *(ROOT / row['path'] for row in public._reader_sources())}
        directories = {parent for path in allowed for parent in path.parents}
        descriptors, opened = {}, set()
        original_open, original_exec = os.open, builtins.exec
        cwd = Path.cwd()
        def selected(path, *, dir_fd=None, directory=False):
            if isinstance(path, int):
                self.assertIn(path, descriptors)
                return descriptors[path]
            candidate = PurePosixPath(os.fsdecode(path))
            if not candidate.is_absolute():
                candidate = (PurePosixPath(descriptors[dir_fd]) if dir_fd is not None else cwd) / candidate
            candidate = Path(candidate)
            self.assertIn(candidate, allowed | directories if directory else allowed, str(candidate))
            return candidate
        def wrap(function, directory=False):
            def guarded(path, *args, **kwargs):
                selected(path, dir_fd=kwargs.get('dir_fd'), directory=directory)
                return function(path, *args, **kwargs)
            return guarded
        def open_fd(path, flags, *args, **kwargs):
            candidate = selected(path, dir_fd=kwargs.get('dir_fd'), directory=bool(flags & os.O_DIRECTORY))
            self.assertFalse(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
            fd = original_open(path, flags, *args, **kwargs)
            descriptors[fd] = candidate
            opened.add(candidate)
            return fd
        def execute(code, globals=None, locals=None, **kwargs):
            self.assertEqual(getattr(code, 'co_filename', None), str(parser))
            return original_exec(code, globals, locals, **kwargs)
        with ExitStack() as stack:
            for owner, name in ((builtins, 'open'), (io, 'open'), (Path, 'open')):
                stack.enter_context(mock.patch.object(owner, name, wrap(getattr(owner, name))))
            for owner, name in ((os, 'stat'), (os, 'lstat'), (os, 'readlink'), (Path, 'resolve'),
                                (Path, 'stat'), (Path, 'lstat'), (Path, 'exists'), (Path, 'is_file'), (Path, 'is_dir')):
                stack.enter_context(mock.patch.object(owner, name, wrap(getattr(owner, name), directory=True)))
            stack.enter_context(mock.patch.object(os, 'open', open_fd))
            stack.enter_context(mock.patch.object(os, 'supports_dir_fd', os.supports_dir_fd | {os.open, os.stat}))
            stack.enter_context(mock.patch.object(os, 'supports_follow_symlinks', os.supports_follow_symlinks | {os.stat}))
            for owner, name in ((subprocess, 'Popen'), (subprocess, 'run'), (subprocess, 'call'),
                                (subprocess, 'check_call'), (subprocess, 'check_output'), (os, 'system'), (os, 'popen'),
                                (os, 'fork'), (os, 'execv'), (os, 'execve'), (os, 'execvp'), (os, 'execvpe'),
                                (os, 'posix_spawn'), (os, 'posix_spawnp'), (os, 'listdir'), (os, 'scandir'),
                                (Path, 'glob'), (Path, 'rglob'), (Path, 'write_bytes'), (Path, 'write_text'),
                                (zipfile.ZipFile, 'extract'), (zipfile.ZipFile, 'extractall'),
                                (checked.checked, 'validate_build'), (checked.checked, 'source_snapshot')):
                if hasattr(owner, name):
                    stack.enter_context(mock.patch.object(owner, name, side_effect=AssertionError(name)))
            stack.enter_context(mock.patch.object(builtins, 'exec', execute))
            result = self.replay(fix, **options)
        self.assertEqual(result['outcome'], 'pass')
        self.assertIn(fix['path'], opened)
        self.assertIn(self.inventory_path, opened)
        self.claims(result)

    def test_public_cli_output_and_failure_claims(self):
        fix = FIXTURES[1]
        options = self.options(fix)
        output = self.temporary / 'result.json'
        base = ['--archive', str(fix['path']), '--sha256', fix['sha256'], '--source-revision', fix['revision']]
        common = ['--source-inventory', str(self.inventory_path), '--source-inventory-sha256', options['source_inventory_sha256']]
        for partial in (['--source-inventory', str(self.inventory_path)], ['--source-inventory-sha256', '0' * 64]):
            capture = io.StringIO()
            with self.subTest(partial=partial), redirect_stdout(capture), \
                 mock.patch.object(checked, 'open_archive', side_effect=AssertionError('archive opened')):
                code = public.main(base + partial)
            self.assertEqual(code, 1)
            result = json.loads(capture.getvalue())
            self.assertIn('supplied together', result['reason'])
            self.claims(result)
        capture = io.StringIO()
        with redirect_stdout(capture):
            code = public.main(base + common + ['--output', str(output)])
        self.assertEqual(code, 0)
        result = json.loads(output.read_bytes())
        self.assertEqual(result['source_inventory_expectation']['manifest_sha256'], options['source_inventory_sha256'])
        self.claims(result)
        self.claims(json.loads(capture.getvalue()))
        body = output.read_bytes()
        capture = io.StringIO()
        with redirect_stdout(capture):
            code = public.main(base + common + ['--output', str(output)])
        self.assertEqual(code, 1)
        self.assertEqual(output.read_bytes(), body)
        self.claims(json.loads(capture.getvalue()))

    def test_current_cli_process_loads_external_manifest(self):
        fix = FIXTURES[1]
        options = self.options(fix)
        command = [sys.executable, '-B', str(ROOT / 'ci/project/p06_counter_public_replay.py'),
                   '--archive', str(fix['path']), '--sha256', fix['sha256'], '--source-revision', fix['revision'],
                   '--source-inventory', str(self.inventory_path), '--source-inventory-sha256', options['source_inventory_sha256']]
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        value = json.loads(result.stdout)
        self.assertEqual(value['outcome'], 'pass')
        self.assertEqual(value['source_inventory_expectation']['manifest_sha256'], options['source_inventory_sha256'])
        self.claims(value)
        RECEIPT['cli_process'] = dict(command=command, exit_code=result.returncode, stderr=result.stderr,
                                       stdout_sha256=digest(result.stdout.encode()))

all_pass = True
for name, suite in (
    ('authored integration regressions', unittest.defaultTestLoader.loadTestsFromModule(authored_tests)),
    ('independent genuine public integration review', unittest.defaultTestLoader.loadTestsFromTestCase(IndependentPublicInventoryReview)),
):
    start = time.monotonic()
    print('\nSUITE:', name, flush=True)
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2, resultclass=CountResult).run(suite)
    RECEIPT['checks'].append(dict(name=name, methods=result.testsRun, subtests=result.subtests,
        failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped),
        duration_seconds=round(time.monotonic() - start, 3), passed=result.wasSuccessful()))
    all_pass &= result.wasSuccessful() and not result.skipped
pin_files()
RECEIPT['outcome'] = 'pass' if all_pass else 'fail'
RECEIPT['review_inputs_stable'] = True
(OUT / 'w08-replay-integration-review.json').write_bytes(encoded(RECEIPT))
print('\nRECEIPT:', OUT / 'w08-replay-integration-review.json', flush=True)
raise SystemExit(0 if all_pass else 1)
