import errno
import hashlib
import json
import os
from pathlib import Path
import sys
from unittest import mock

REPO = Path('/home/agent/ai-gpu-work-4c990083f078/AI-GPU')
sys.path.insert(0, str(REPO / 'ci/project'))
import p06_qualified_warm_encrypt as encrypt
from test_p06_encrypt_operational_failures import encryption_fixture


def closed(fd):
    try:
        os.fstat(fd)
    except OSError as error:
        assert error.errno == errno.EBADF, error
        return True
    return False


def check(mode):
    real_open, real_close, real_read = os.open, os.close, os.read
    real_verify = encrypt._verify_public_file
    real_popen = encrypt.subprocess.Popen
    real_unlink = encrypt._unlink_owned
    real_pump_close = encrypt._Pump.close
    failure = OSError(errno.EIO, 'injected final public read failure')
    state = {'entered': False, 'in_helper': False, 'reads': 0}
    fds, retained, public_checks, closes, unlink_calls, processes, pumps = {}, {}, [], [], [], [], []
    with encryption_fixture() as fixture:
        before = fixture.source_bytes()

        def record_open(name, flags, *args, **kwargs):
            fd = real_open(name, flags, *args, **kwargs)
            if name == fixture.private.name and 'private' not in fds:
                fds['private'] = fd
                fds['parent'] = kwargs['dir_fd']
            if name == fixture.output.name and 'output' not in fds:
                fds['output'] = fd
            if state['in_helper'] and name == encrypt.CIPHERTEXT_NAME:
                assert kwargs['dir_fd'] == fds['output']
                fds['helper'] = fd
            return fd

        def record_close(fd):
            if state['entered']:
                closes.append(fd)
            return real_close(fd)

        def read_fault(fd, amount):
            if state['in_helper'] and fd == fds.get('helper'):
                state['reads'] += 1
                if mode == 'read-oserror' and state['reads'] == 2:
                    raise failure
            return real_read(fd, amount)

        def verify(directory_fd, name, identity, count, expected_digest, deadline):
            assert not state['entered'], 'unexpected repeated verification'
            state['entered'] = True
            public_checks.append(name)
            assert name == encrypt.CIPHERTEXT_NAME
            assert directory_fd == fds['output']
            assert not (fixture.private / encrypt.INCOMPLETE_NAME).exists()
            assert not (fixture.private / encrypt.PRIVATE_SUMMARY_NAME).exists()
            assert {path.name for path in fixture.private.iterdir()} == {encrypt.STDERR_NAME}
            retained.update({path.name: path.read_bytes() for path in fixture.output.iterdir()})
            assert set(retained) == {encrypt.CIPHERTEXT_NAME, encrypt.SUMMARY_NAME}
            state['in_helper'] = True
            try:
                if mode == 'deadline':
                    with mock.patch.object(encrypt.time, 'monotonic', return_value=deadline):
                        return real_verify(directory_fd, name, identity, count, expected_digest, deadline)
                return real_verify(directory_fd, name, identity, count, expected_digest, deadline)
            finally:
                state['in_helper'] = False
                assert closed(fds['helper']), 'helper finally leaked fd'
                assert closes == [fds['helper']], closes

        def record_unlink(directory_fd, name, identity):
            unlink_calls.append((directory_fd, name, state['entered']))
            return real_unlink(directory_fd, name, identity)

        def launch(*args, **kwargs):
            assert not state['entered'], 'relaunch after public check'
            process = real_popen(*args, **kwargs)
            processes.append(process)
            return process

        def close_pump(pump):
            pumps.append(pump)
            return real_pump_close(pump)

        with mock.patch.object(encrypt.os, 'open', side_effect=record_open), \
             mock.patch.object(encrypt.os, 'close', side_effect=record_close), \
             mock.patch.object(encrypt.os, 'read', side_effect=read_fault), \
             mock.patch.object(encrypt, '_verify_public_file', side_effect=verify), \
             mock.patch.object(encrypt, '_unlink_owned', side_effect=record_unlink), \
             mock.patch.object(encrypt.subprocess, 'Popen', side_effect=launch), \
             mock.patch.object(encrypt._Pump, 'close', new=close_pump):
            try:
                fixture.run_encrypt()
            except BaseException as error:
                if mode == 'read-oserror':
                    assert error is failure, repr(error)
                else:
                    assert isinstance(error, encrypt.EncryptionError), repr(error)
                    assert str(error) == 'runtime-limit', repr(error)
                error_name = type(error).__name__
            else:
                raise AssertionError('failure returned success')

        assert state['entered']
        assert state['reads'] == (2 if mode == 'read-oserror' else 0), state
        assert len(processes) == 1
        assert processes[0].returncode == 0
        assert len(pumps) == 1
        assert all(stream.closed for stream in (processes[0].stdin, processes[0].stdout, processes[0].stderr))
        assert pumps[0].selector.get_map() is None
        assert closes == [fds['helper'], fds['output'], fds['private'], fds['parent']], closes
        assert all(closed(fd) for fd in fds.values()), fds
        assert unlink_calls == [(fds['private'], encrypt.INCOMPLETE_NAME, False),
                                (fds['private'], encrypt.PRIVATE_SUMMARY_NAME, False)], unlink_calls
        assert public_checks == [encrypt.CIPHERTEXT_NAME]
        assert fixture.source_bytes() == before
        after = {path.name: path.read_bytes() for path in fixture.output.iterdir()}
        assert after == retained
        assert all(fixture.secret not in body and b'ustar' not in body for body in after.values())
        assert {path.name for path in fixture.private.iterdir()} == {encrypt.STDERR_NAME, encrypt.DIAGNOSTIC_NAME}
        diagnostic = json.loads((fixture.private / encrypt.DIAGNOSTIC_NAME).read_bytes())
        for key, expected in {'stage': 'private-cleanup', 'error_type': error_name,
                              'publication_committed': True, 'encryption_passed': False,
                              'plaintext_publication_authorized': False, 'cleanup_complete': True}.items():
            assert diagnostic[key] == expected, (key, diagnostic)
        public_summary = json.loads(after[encrypt.SUMMARY_NAME])
        assert public_summary['encryption_passed'] is True
        assert public_summary['ciphertext_sha256'] == hashlib.sha256(after[encrypt.CIPHERTEXT_NAME]).hexdigest()
        fixture.verify_captured_tar(before)
        print(json.dumps({'mode': mode, 'result': 'PASS', 'error_type': error_name,
                          'ciphertext_bytes': len(after[encrypt.CIPHERTEXT_NAME]),
                          'ciphertext_sha256': hashlib.sha256(after[encrypt.CIPHERTEXT_NAME]).hexdigest(),
                          'public_pair_unchanged': True, 'private_links_absent_at_injection': True,
                          'launches': len(processes), 'public_reads': state['reads'],
                          'helper_and_caller_fd_close_order': ['helper', 'output', 'private', 'parent'],
                          'public_pass_summary_retained': True, 'private_failure_diagnostic': diagnostic}, sort_keys=True))


for mode in ('read-oserror', 'deadline'):
    check(mode)
print('PASS: 2 full-caller synthetic fault probes; no native, network, real cryptography, or full-suite qualification.')
