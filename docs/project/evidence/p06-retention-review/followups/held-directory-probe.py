#!/usr/bin/env python3
"""One synthetic held-directory replacement check; no native execution."""

import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import time
from unittest import mock

SOURCE = Path('/home/agent/ai-gpu-d37f66a85d88/AI-GPU')
sys.path.insert(0, str(SOURCE / 'ci/project'))
import p06_qualified_warm_restore as restore


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity(info):
    return [info.st_dev, info.st_ino]


source_files = ['ci/project/p06_qualified_warm_restore.py',
                'ci/project/p06_qualified_warm_retention.py',
                'ci/project/test_p06_qualified_warm_restore.py']
before = {name: digest(SOURCE / name) for name in source_files}
started = time.monotonic()
observations = {}
held = []
with tempfile.TemporaryDirectory(prefix='held-directory-',
        dir='/home/agent/ai-gpu-d37f66a85d88/tmp/a57_inode_review') as temporary:
    root = Path(temporary)
    archive, output = root / 'input.PRIVATE.tar', root / 'restored.PRIVATE'
    payload = b'inert synthetic payload\x00\xff'
    revision = 'a9' * 20
    manifest = {'schema_version': 1,
                'contract_id': 'p06-qualified-warm-encrypted-retention-v1',
                'expected_revision': revision,
                'directories': ['', 'empty'],
                'files': [{'path': 'payload', 'size_bytes': len(payload),
                           'sha256': hashlib.sha256(payload).hexdigest()}]}
    raw = (json.dumps(manifest, sort_keys=True, separators=(',', ':')) + '\n').encode()
    members = [('manifest.json', raw), ('private', None),
               ('private/empty', None), ('private/payload', payload)]
    with tarfile.open(archive, 'w', format=tarfile.PAX_FORMAT,
                      encoding='utf-8', errors='strict') as stream:
        for name, body in members:
            info = tarfile.TarInfo(name)
            info.type = tarfile.DIRTYPE if body is None else tarfile.REGTYPE
            info.mode = 0o700 if body is None else 0o600
            info.size, info.mtime = (0 if body is None else len(body)), 0
            stream.addfile(info, None if body is None else io.BytesIO(body))
    archive.chmod(0o600)
    archive_before = digest(archive)
    original_verify = restore._verify_tree
    changed = False

    def replace_directory(root_fd, directories, files):
        global changed
        if not changed:
            changed = True
            path = output / 'private/empty'
            fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            held.append(fd)
            observations['expected_identity'] = list(directories['private/empty'])
            observations['original_identity'] = identity(os.fstat(fd))
            path.rmdir()
            path.mkdir(mode=0o700)
            observations['removed_identity'] = identity(os.fstat(fd))
            observations['removed_link_count'] = os.fstat(fd).st_nlink
            observations['replacement_identity'] = identity(path.stat())
        return original_verify(root_fd, directories, files)

    error = None
    report = None
    try:
        with mock.patch.object(restore, '_verify_tree', side_effect=replace_directory):
            try:
                report = restore.restore_archive(archive, archive_before,
                    expected_revision=revision, output_dir=output)
            except restore.RestoreError as failure:
                error = failure.code
        observations['error_code'] = error
        observations['returned_success'] = report is not None
        marker = json.loads((output / restore.INCOMPLETE_NAME).read_bytes())
        observations['marker'] = marker
        observations['archive_unchanged'] = digest(archive) == archive_before
        observations['payload_retained'] = (output / 'private/payload').read_bytes() == payload
        observations['removed_fd_still_open_after_rejection'] = identity(os.fstat(held[0]))
        # Assertions are deliberately outside the operation's exception mapper.
        assert observations['original_identity'] == observations['expected_identity']
        assert observations['removed_identity'] == observations['original_identity']
        assert observations['replacement_identity'] != observations['original_identity']
        assert error == 'output-changed' and report is None
        assert marker['outcome'] == 'incomplete' and marker['restoration_completed'] is False
        assert marker['native_execution'] == 'not_run'
        assert all(marker[key] is False for key in ('retained_code_executed',
            'origin_authenticated', 'native_acceptance', 'performance_acceptance', 'phase_acceptance'))
        assert observations['archive_unchanged'] and observations['payload_retained']
    finally:
        for fd in held:
            os.close(fd)

after = {name: digest(SOURCE / name) for name in source_files}
assert before == after
result = {'outcome': 'pass', 'scope': 'one-independent-synthetic-host-probe',
          'tests_run': 1, 'native_execution': 'not_run',
          'interpreter': sys.version, 'executable': sys.executable,
          'duration_seconds': time.monotonic() - started,
          'source_sha256_before': before, 'source_sha256_after': after,
          'observations': observations}
print(json.dumps(result, indent=2, sort_keys=True))
