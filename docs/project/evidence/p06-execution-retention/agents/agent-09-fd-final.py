"""Recheck the same early-output-fstat fault after root's narrow correction."""

import hashlib
import json
import os
from pathlib import Path
import sys
from unittest import mock

ROOT = Path('/tmp/ai-gpu-ae456f837c05/AI-GPU')
sys.path.insert(0, str(ROOT / 'ci/project'))
import p06_qualified_warm_pack as candidate
import test_p06_qualified_warm_pack as fixtures


def fds():
    result = {}
    for path in Path('/proc/self/fd').iterdir():
        try:
            result[int(path.name)] = os.readlink(path)
        except FileNotFoundError:
            pass
    return result


case = fixtures.PrivatePackagingTests()
case.setUp()
original = os.fstat
caught_fd = None


def interrupt(descriptor):
    global caught_fd
    if caught_fd is None and os.readlink('/proc/self/fd/' + str(descriptor)) == str(case.output):
        caught_fd = descriptor
        raise KeyboardInterrupt()
    return original(descriptor)


before = fds()
try:
    with mock.patch.object(candidate.os, 'fstat', side_effect=interrupt):
        try:
            candidate.package_partial(**case.arguments())
        except KeyboardInterrupt:
            pass
        else:
            raise AssertionError('the injected interruption was not propagated')
    assert caught_fd is not None
    assert fds() == before
    failure = json.loads((case.output / candidate.FAILURE_NAME).read_bytes())
    assert failure['error_type'] == 'KeyboardInterrupt'
    assert failure['stage'] == 'inventory'
    assert failure['packaging_passed'] is False
    assert failure['created_files'] == []
    result = {
        'candidate_sha256': hashlib.sha256((ROOT / 'ci/project/p06_qualified_warm_pack.py').read_bytes()).hexdigest(),
        'fault': 'KeyboardInterrupt at first fstat of the valid created output descriptor',
        'fault_propagated': True,
        'leaked_descriptor_count': 0,
        'failure_receipt_written': True,
        'failure_receipt_error_type': failure['error_type'],
        'failure_receipt_created_files': failure['created_files'],
    }
    (ROOT.parent / 'notes/agent-09-fd-final.json').write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')
    print('Same initial-output-fstat KeyboardInterrupt probe passed: zero leaked fds, failure receipt retained.')
finally:
    case.doCleanups()
