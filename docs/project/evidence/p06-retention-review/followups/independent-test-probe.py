#!/usr/bin/env python3
"""One A35 probe invocation: exact corrected method and one setup-fault control."""
from contextlib import ExitStack
import errno
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
import unittest
from unittest import mock

ROOT = Path('/home/agent/ai-gpu-d37f66a85d88/AI-GPU')
BASE = Path('/home/agent/ai-gpu-d37f66a85d88')
OUT = BASE / 'tmp/a35-post-publication'
REPORT = BASE / 'notes/a35-post-publication-test-review.json'
if REPORT.exists():
    raise SystemExit('One-shot report already exists; refusing to rerun.')
sys.path.insert(0, str(ROOT / 'ci/project'))
import test_p06_qualified_warm_restore as tests

restore = tests.restore
original_open, original_close, original_fstat = os.open, os.close, os.fstat
original_listdir, original_verify = os.listdir, restore._verify_tree
METHOD = 'test_changed_restored_bytes_and_unexpected_entries_are_detected'
FILES = ('ci/project/test_p06_qualified_warm_restore.py',
         'ci/project/p06_qualified_warm_restore.py',
         'ci/project/p06_qualified_warm_retention.py',
         'ci/project/p06_qualified_warm_encrypt.py')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identities():
    result = {}
    for name in original_listdir('/proc/self/fd'):
        try:
            value = original_fstat(int(name))
        except OSError:
            continue
        result[name] = [value.st_dev, value.st_ino, value.st_mode, value.st_rdev]
    return result


def run_control(fail_setup):
    state = {'held_fd': None, 'held_open': False, 'held_close_count': 0,
             'setup_fault_injected': False, 'restores': [], 'subtests': [],
             'verification_observations': []}
    case = tests.QualifiedWarmRestoreTests(METHOD)
    original_run = case.run_restore

    def opening(path, flags, *args, **kwargs):
        fd = original_open(path, flags, *args, **kwargs)
        if isinstance(path, Path) and path.is_absolute() and path.parts[-2:] == ('private', 'empty'):
            info = original_fstat(fd)
            state.update(held_fd=fd, held_open=True, held_path=str(path),
                         held_initial_identity=[info.st_dev, info.st_ino])
        return fd

    def stating(fd):
        if fail_setup and state['held_open'] and fd == state['held_fd'] and not state['setup_fault_injected']:
            state['setup_fault_injected'] = True
            raise OSError(errno.EIO, 'A35 synthetic held-fd fixture setup failure')
        return original_fstat(fd)

    def closing(fd):
        is_held = state['held_open'] and fd == state['held_fd']
        result = original_close(fd)
        if is_held:
            state['held_open'] = False
            state['held_close_count'] += 1
        return result

    def verifying(*args, **kwargs):
        if state['held_open']:
            old = original_fstat(state['held_fd'])
            new = Path(state['held_path']).stat()
            state['verification_observations'].append({
                'held_identity': [old.st_dev, old.st_ino],
                'replacement_identity': [new.st_dev, new.st_ino],
                'identities_differ': (old.st_dev, old.st_ino) != (new.st_dev, new.st_ino),
                'old_link_count': old.st_nlink,
            })
        return original_verify(*args, **kwargs)

    def observing_restore(**updates):
        row = {'output_name': Path(updates['output_dir']).name}
        state['restores'].append(row)
        try:
            value = original_run(**updates)
            row['returned'] = True
            return value
        except BaseException as error:
            row.update(returned=False, exception_type=type(error).__name__,
                       error_code=getattr(error, 'code', None))
            raise

    class Result(unittest.TextTestResult):
        def addSubTest(self, test, subtest, err):
            row = {'params': dict(subtest.params), 'passed': err is None}
            if err is not None:
                frames = traceback.extract_tb(err[2])
                row.update(exception_type=err[0].__name__, message=str(err[1]),
                           frames=[{'file': item.filename, 'line': item.lineno,
                                    'function': item.name, 'source': item.line} for item in frames],
                           outside_restore_mapper=not any(item.name == 'restore_archive' for item in frames))
            state['subtests'].append(row)
            super().addSubTest(test, subtest, err)

    before = identities()
    stream = io.StringIO()
    with ExitStack() as patches:
        patches.enter_context(mock.patch.object(os, 'open', side_effect=opening))
        patches.enter_context(mock.patch.object(os, 'fstat', side_effect=stating))
        patches.enter_context(mock.patch.object(os, 'close', side_effect=closing))
        patches.enter_context(mock.patch.object(restore, '_verify_tree', side_effect=verifying))
        patches.enter_context(mock.patch.object(case, 'run_restore', side_effect=observing_restore))
        result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=Result).run(
            unittest.TestSuite([case]))
    after = identities()
    name = 'setup_fault' if fail_setup else 'actual_replacement'
    log = OUT / (name + '.log')
    log.write_text(stream.getvalue())
    state.update(control=name, tests_run=result.testsRun, test_success=result.wasSuccessful(),
                 failures=len(result.failures), errors=len(result.errors), skips=len(result.skipped),
                 fd_identities_before=before, fd_identities_after=after,
                 no_descriptor_change=before == after,
                 hooks_restored=os.open is original_open and os.close is original_close
                     and os.fstat is original_fstat and restore._verify_tree is original_verify,
                 log=str(log), log_sha256=sha(log))
    return state


before = {name: sha(ROOT / name) for name in FILES}
head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
started = time.monotonic()
actual = run_control(False)
fault = run_control(True)
after = {name: sha(ROOT / name) for name in FILES}
actual_directory = next(row for row in actual['restores'] if row['output_name'] == 'changed-3')
fault_directory = next(row for row in fault['restores'] if row['output_name'] == 'changed-3')
failed_subtests = [row for row in fault['subtests'] if not row['passed']]
passed = (before == after
    and actual['test_success'] and actual['tests_run'] == 1
    and actual_directory['error_code'] == 'output-changed'
    and actual['held_close_count'] == 1 and not actual['held_open']
    and len(actual['verification_observations']) == 1
    and actual['verification_observations'][0]['identities_differ']
    and actual['verification_observations'][0]['old_link_count'] == 0
    and actual['no_descriptor_change'] and actual['hooks_restored']
    and not fault['test_success'] and fault['tests_run'] == 1
    and fault['setup_fault_injected']
    and fault_directory['error_code'] == 'filesystem-failed'
    and fault['held_close_count'] == 1 and not fault['held_open']
    and fault['no_descriptor_change'] and fault['hooks_restored']
    and len(failed_subtests) == 1
    and failed_subtests[0]['params'] == {'change': 'directory'}
    and failed_subtests[0]['exception_type'] == 'AssertionError'
    and failed_subtests[0]['message'] == '0 != 2'
    and failed_subtests[0]['outside_restore_mapper']
    and actual['errors'] == fault['errors'] == actual['skips'] == fault['skips'] == 0)
report = {
    'reviewer': 'A35', 'same_assignment_followup': True,
    'date_utc': '2026-11-25', 'head': head, 'python': sys.version,
    'scope': 'One probe invocation, two distinct controls of the exact changed test method; no full module or suite run.',
    'command': [sys.executable, '-B', str(Path(__file__).resolve())],
    'environment': {'PYTHONDONTWRITEBYTECODE': '1', 'TMPDIR': str(OUT)},
    'source_before': before, 'source_after': after, 'sources_stable': before == after,
    'script_sha256': sha(Path(__file__)),
    'actual_replacement': actual, 'setup_fault': fault,
    'elapsed_seconds': time.monotonic() - started,
    'probe_passed': passed,
    'limits': [
        'Hosted failure inode values were not observed here; inode reuse remains inferred for that historical failure.',
        'Only one actual replacement and one injected setup-fault control were performed; this is focused synthetic host evidence.',
        'The expected failing setup-fault control is not represented as a passing test.',
    ],
}
with REPORT.open('x') as stream:
    json.dump(report, stream, indent=2, sort_keys=True)
    stream.write('\n')
print(json.dumps({'probe_passed': passed, 'sources_stable': before == after,
                  'actual_replacement': {key: actual[key] for key in
                      ('test_success', 'subtests', 'verification_observations', 'held_close_count', 'no_descriptor_change', 'hooks_restored')},
                  'setup_fault': {key: fault[key] for key in
                      ('test_success', 'subtests', 'setup_fault_injected', 'held_close_count', 'no_descriptor_change', 'hooks_restored')},
                  'report': str(REPORT)}, sort_keys=True))
raise SystemExit(0 if passed else 1)
