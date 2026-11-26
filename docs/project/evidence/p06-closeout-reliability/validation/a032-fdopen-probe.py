"""Temporary, host-only control for _exclusive's fdopen failure branch."""
import errno
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from unittest import mock

REPO = Path('/home/agent/ai-gpu-work-4c990083f078/AI-GPU')
SOURCE = REPO / 'ci/project/p06_qualified_warm_encrypt.py'
SOURCE_SHA256 = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
spec = importlib.util.spec_from_file_location('a032_probe_encrypt', SOURCE)
encrypt = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = encrypt
spec.loader.exec_module(encrypt)
assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == SOURCE_SHA256
real_open, real_close, real_fchmod = os.open, os.close, os.fchmod


def identity(fd):
    info = os.fstat(fd)
    return info.st_dev, info.st_ino


def is_open(fd):
    try:
        os.fstat(fd)
        return True
    except OSError as error:
        assert error.errno == errno.EBADF
        return False


def run_case(primary_type, secondary_type=None):
    primary = (OSError(errno.EIO, 'injected fdopen failure')
               if primary_type is OSError else KeyboardInterrupt('injected fdopen interrupt'))
    secondary = (OSError(errno.ENOSPC, 'injected consuming close failure')
                 if secondary_type is OSError else KeyboardInterrupt('injected consuming close interrupt'))
    state = {'raw': None, 'raw_identity': None, 'sentinel': None,
             'sentinel_identity': None, 'fdopen_calls': 0, 'close_calls': [],
             'profile_returns': []}
    with tempfile.TemporaryDirectory(prefix='a032-fdopen-') as directory:
        directory_fd = real_open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        directory_identity = identity(directory_fd)

        def fail_fdopen(descriptor, mode, *, buffering):
            state['fdopen_calls'] += 1
            state['raw'] = descriptor
            state['raw_identity'] = identity(descriptor)
            assert descriptor != directory_fd
            assert mode == 'w+b' and buffering == 0
            assert stat.S_IMODE(os.fstat(descriptor).st_mode) == 0o600
            assert os.open is real_open and os.fchmod is real_fchmod
            # Ownership has not moved to a stream: the raw fd is still open.
            raise primary

        def profile(frame, event, arg):
            if arg is real_close and frame.f_code is encrypt._exclusive.__code__:
                if event == 'c_call':
                    state['close_calls'].append(frame.f_locals['fd'])
                elif event == 'c_return':
                    state['profile_returns'].append(frame.f_locals['fd'])

        def consuming_close_failure(descriptor):
            state['close_calls'].append(descriptor)
            assert descriptor == state['raw']
            real_close(descriptor)
            state['sentinel'] = real_open('sentinel', os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_CLOEXEC,
                                          0o600, dir_fd=directory_fd)
            assert state['sentinel'] == descriptor
            state['sentinel_identity'] = identity(state['sentinel'])
            assert state['sentinel_identity'] != state['raw_identity']
            raise secondary

        caught = None
        previous_profile = sys.getprofile()
        try:
            with mock.patch.object(encrypt.os, 'fdopen', side_effect=fail_fdopen):
                if secondary_type is None:
                    assert os.close is real_close
                    sys.setprofile(profile)
                    try:
                        encrypt._exclusive(directory_fd, 'allocated')
                    except BaseException as error:
                        caught = error
                    finally:
                        sys.setprofile(previous_profile)
                else:
                    with mock.patch.object(encrypt.os, 'close', side_effect=consuming_close_failure):
                        try:
                            encrypt._exclusive(directory_fd, 'allocated')
                        except BaseException as error:
                            caught = error
            assert caught is primary, (type(caught).__name__, type(primary).__name__)
            assert state['fdopen_calls'] == 1
            assert state['close_calls'] == [state['raw']], state['close_calls']
            assert identity(directory_fd) == directory_identity
            assert stat.S_ISDIR(os.fstat(directory_fd).st_mode)
            if secondary_type is None:
                assert state['profile_returns'] == [state['raw']]
                assert not is_open(state['raw'])
            else:
                assert state['sentinel'] == state['raw']
                assert identity(state['sentinel']) == state['sentinel_identity']
                assert os.write(state['sentinel'], b'preserved') == 9
            result = {'case': primary_type.__name__,
                      'secondary_close': secondary_type.__name__ if secondary_type else None,
                      'primary_exception_identity': True, 'fdopen_calls': state['fdopen_calls'],
                      'raw_close_calls': len(state['close_calls']), 'directory_fd_preserved': True,
                      'raw_fd_closed': secondary_type is None,
                      'reused_fd_preserved': True if secondary_type else None, 'result': 'PASS'}
            print(json.dumps(result, sort_keys=True))
            return result
        finally:
            sys.setprofile(previous_profile)
            # Clean up only descriptors whose current inode still belongs to this probe.
            sentinel = state['sentinel']
            if sentinel is not None and is_open(sentinel):
                assert identity(sentinel) == state['sentinel_identity']
                real_close(sentinel)
            raw = state['raw']
            if raw is not None and is_open(raw) and identity(raw) == state['raw_identity']:
                real_close(raw)
            real_close(directory_fd)


print(json.dumps({'source': str(SOURCE), 'source_sha256': SOURCE_SHA256,
                  'python': sys.version, 'tmpdir': tempfile.gettempdir()}, sort_keys=True))
results = []
for primary_type in (OSError, KeyboardInterrupt):
    results.append(run_case(primary_type))
for primary_type in (OSError, KeyboardInterrupt):
    for secondary_type in (OSError, KeyboardInterrupt):
        results.append(run_case(primary_type, secondary_type))
assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == SOURCE_SHA256
print(json.dumps({'result': 'PASS', 'cases': len(results), 'source_unchanged': True}, sort_keys=True))
