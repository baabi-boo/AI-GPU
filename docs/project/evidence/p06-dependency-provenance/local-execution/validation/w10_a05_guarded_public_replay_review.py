"""Independent actual-original public CLI and external-pin review; no retained execution."""

import contextlib
import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import zipfile

sys.dont_write_bytecode = True
SOURCE = Path('/workspace/p06-local-replay-source')
VALIDATION = Path('/workspace/scratch/279b6658611e/validation')
ARCHIVE = Path('/workspace/scratch/279b6658611e/AI-GPU_P06_local_attempt_04_passed_2026-11-23.zip')
EXPECTED_READER = 'ba2d649d4150e046c2ba610de02725d9d062b1be'
EXPECTED_TREE = 'a9db358818a66f2a241ed2d8a7453edf938ccb2c'
EXPECTED_EXECUTION = '0f9aaa36d46364c297254164f5dab0d4f0e88349'
EXPECTED_ZIP = 'd3a16e1e6e92a68414f5fdcce564b963dde2e9e801601191d52ceeb974faea6f'


def git(*args):
    return subprocess.check_output(['git', '-C', str(SOURCE), *args]).decode().strip()


def identity(path):
    before = path.stat()
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    after = path.stat()
    assert (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) == (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    return {'sha256': digest.hexdigest(), 'size_bytes': before.st_size}


source_before = {'revision': git('rev-parse', 'HEAD'), 'tree': git('rev-parse', 'HEAD^{tree}'),
                 'status': git('status', '--porcelain=v1', '--untracked-files=all')}
assert source_before == {'revision': EXPECTED_READER, 'tree': EXPECTED_TREE, 'status': ''}
archive_before = identity(ARCHIVE)
assert archive_before == {'sha256': EXPECTED_ZIP, 'size_bytes': 47632218}
with zipfile.ZipFile(ARCHIVE) as archive:
    envelope_bytes = archive.read('local-execution.json')
    envelope = json.loads(envelope_bytes)
    archive_inventory = {'members': len(archive.infolist()),
                         'expanded_bytes': sum(item.file_size for item in archive.infolist())}
assert archive_inventory == {'members': 5597, 'expanded_bytes': 227787986}
assert envelope['expected_revision'] == EXPECTED_EXECUTION and envelope['outcome'] == 'pass'
pins = envelope['reports']
arguments = {
    'sha256': EXPECTED_ZIP,
    'expected-revision': EXPECTED_EXECUTION,
    'dependency-receipt-sha256': pins['dependency-build']['sha256'],
    'native-report-sha256': pins['native-lifetime']['sha256'],
    'source-manifest-sha256': pins['native-source']['sha256'],
    'probe-report-sha256': pins['pending-probe']['sha256'],
    'substitution-report-sha256': pins['dependency-substitution']['sha256'],
    'local-execution-sha256': hashlib.sha256(envelope_bytes).hexdigest(),
}
denied_roots = sorted({envelope['source_dir'], envelope['workspace_dir'],
                       envelope['archive_root'], envelope['dependency_repositories_root'],
                       str(Path(envelope['host_bin']).parent)})
assert not any(str(SOURCE) == root or str(SOURCE).startswith(root + '/') for root in denied_roots)
sys.path.insert(0, str(SOURCE / 'ci/project'))
import p06_dependency_local_replay as replay

reader_before = replay._reader_sources()
assert reader_before == replay.TRUSTED_READER_SOURCES
started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
started = time.monotonic()
active = False
allowed_output = None
events = []
cases = []
original_resolve, original_realpath = Path.resolve, os.path.realpath


def producer_path(path):
    if isinstance(path, int) or path is None:
        return False
    try:
        text = os.fsdecode(os.fspath(path))
    except TypeError:
        return False
    normalized = os.path.abspath(os.path.normpath(text))
    return any(normalized == root or normalized.startswith(root + '/') for root in denied_roots)


def deny(event, path=None):
    value = {'event': event}
    if path is not None:
        value['path'] = str(path)
    events.append(value)
    raise RuntimeError('review guard denied ' + event + (': ' + str(path) if path is not None else ''))


def guarded_resolve(path, *args, **kwargs):
    if active and producer_path(path):
        deny('producer Path.resolve', path)
    return original_resolve(path, *args, **kwargs)


def guarded_realpath(path, *args, **kwargs):
    if active and producer_path(path):
        deny('producer os.path.realpath', path)
    return original_realpath(path, *args, **kwargs)


def audit(event, args):
    if not active:
        return
    if event in ('subprocess.Popen', 'os.system', 'os.exec', 'os.posix_spawn', 'os.fork', 'os.forkpty',
                 'socket.__new__', 'socket.connect', 'socket.bind', 'socket.sendto', 'socket.getaddrinfo',
                 'ctypes.dlopen', 'os.remove', 'os.rmdir', 'os.mkdir', 'os.rename', 'os.link',
                 'os.symlink', 'os.chmod', 'os.chown', 'os.truncate', 'os.utime', 'os.chdir'):
        deny(event)
    if event == 'open':
        path, mode, flags = args
        if producer_path(path):
            deny('producer open', path)
        writing = isinstance(flags, int) and flags & (
            os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_TRUNC | os.O_CREAT)
        if writing and str(path) != str(allowed_output):
            deny('unexpected write', path)
    if event in ('os.listdir', 'os.scandir', 'os.chdir', 'os.remove', 'os.mkdir', 'os.rename'):
        for path in args[:2]:
            if producer_path(path):
                deny(event, path)


sys.addaudithook(audit)
Path.resolve = guarded_resolve
os.path.realpath = guarded_realpath
false_claims = ('qualified', 'ready_for_warm', 'warm_execution', 'full_warm_coverage',
                'acceptance_claimed', 'phase_acceptance', 'performance_acceptance')
positive = None

try:
    selections = [('exact-all-pins', None)] + [('wrong-' + name, name) for name in arguments]
    for label, wrong in selections:
        output = VALIDATION / ('w10_a05-guarded-' + label + '.json')
        assert not output.exists()
        selected = dict(arguments)
        if wrong:
            value = selected[wrong]
            selected[wrong] = ('0' if value[0] != '0' else '1') + value[1:]
        argv = [str(ARCHIVE)]
        for key, value in selected.items():
            argv.extend(['--' + key, value])
        argv.extend(['--output', str(output)])
        allowed_output = output
        stream = io.StringIO()
        begin = time.monotonic()
        active = True
        try:
            with contextlib.redirect_stdout(stream):
                exit_code = replay.main(argv)
        finally:
            active = False
        terminal = json.loads(stream.getvalue())
        row = {'case': label, 'changed_external_argument': wrong, 'argv': argv,
               'exit_code': exit_code, 'duration_seconds': time.monotonic() - begin,
               'terminal': terminal, 'prohibited_events': list(events)}
        assert not events
        assert terminal['native_execution'] == 'not_run' and terminal['retained_code_executed'] is False
        assert all(terminal[name] is False for name in false_claims)
        if wrong is None:
            assert exit_code == 0 and terminal['outcome'] == 'pass' and output.is_file()
            positive = json.loads(output.read_bytes())
            assert positive['outcome'] == 'pass' and positive['retained_consistency'] is True
            assert positive['native_execution'] == 'not_run' and positive['retained_code_executed'] is False
            assert all(positive[name] is False for name in false_claims)
            assert positive['local_identity']['origin_authenticated'] is False
            assert positive['local_identity']['stages_checked'] == 5
            assert positive['local_identity']['retained_members_checked'] == 5597
            assert positive['managed_counts'] == replay.native_replay.COUNTS
            assert positive['pending_probe']['processes'] == 2 and positive['pending_probe']['contexts'] == 2
            assert positive['dependency_substitution']['control_counts']['launches'] == 33
            assert positive['dependency_substitution']['control_counts']['checked_words'] == 1056
            assert positive['trusted_reader_sources'] == reader_before
            row['result_identity'] = identity(output)
            row['closing_archive_context_returned'] = True
        else:
            assert exit_code == 1 and terminal['outcome'] == 'fail' and not output.exists()
            assert terminal['retained_consistency'] is False
        cases.append(row)
        print(json.dumps({'case': label, 'exit_code': exit_code, 'outcome': terminal['outcome'],
                          'reason': terminal.get('reason'), 'duration_seconds': row['duration_seconds']}), flush=True)
finally:
    active = False
    Path.resolve = original_resolve
    os.path.realpath = original_realpath

reader_after = replay._reader_sources()
assert reader_after == reader_before
archive_after = identity(ARCHIVE)
assert archive_before == archive_after
source_after = {'revision': git('rev-parse', 'HEAD'), 'tree': git('rev-parse', 'HEAD^{tree}'),
                'status': git('status', '--porcelain=v1', '--untracked-files=all')}
assert source_after == source_before
archive_receipt = {key: value for key, value in positive['archive_read'].items() if key != 'read_files'}
result = {
    'schema_version': 1,
    'scope': 'Independent unmodified public local CLI plus every external identity argument; actual original data remains inert',
    'outcome': 'pass', 'started_at': started_at,
    'finished_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'duration_seconds': time.monotonic() - started,
    'original_execution_revision': EXPECTED_EXECUTION,
    'reader_source_before': source_before, 'reader_source_after': source_after,
    'archive_before': archive_before, 'archive_after': archive_after,
    'archive_inventory': archive_inventory, 'archive_unchanged': True,
    'trusted_reader_source_count': len(reader_before),
    'trusted_reader_inventory_sha256': hashlib.sha256(replay.contract.json_bytes(reader_before)).hexdigest(),
    'trusted_reader_sources_unchanged': True,
    'denied_producer_roots': denied_roots,
    'prohibited_events': events, 'retained_code_executed': False,
    'guard_scope': 'Deny producer-root opens/resolves/traversal; all process/network/dlopen; all filesystem mutation audit events and every write-open except selected CLI output',
    'positive_public_cli_passes': 1, 'negative_external_pin_rejections': 8,
    'cases': cases, 'managed_counts': positive['managed_counts'],
    'local_identity': positive['local_identity'], 'pending_probe': positive['pending_probe'],
    'dependency_substitution': positive['dependency_substitution'],
    'archive_read': archive_receipt,
    'reader_correction_scope': 'Exact required Ramulator diagnostics are inert, bounded and excluded from all numerical/performance/qualification evidence',
    **dict.fromkeys(false_claims, False),
}
target = VALIDATION / 'w10_a05-guarded-public-replay-review.json'
assert not target.exists()
target.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
print(json.dumps({'outcome': 'pass', 'review': str(target), **identity(target),
                  'duration_seconds': result['duration_seconds']}, indent=2), flush=True)
