import errno
import os
from pathlib import Path
import tempfile
import time
from unittest import mock
import p06_qualified_warm_encrypt as encrypt

for failure in (OSError(errno.EMFILE, 'synthetic fdopen failure'), KeyboardInterrupt('synthetic cancellation')):
    with tempfile.TemporaryDirectory(prefix='a034-reader-') as tmp:
        root = Path(tmp)
        path = root / 'synthetic.bin'
        path.write_bytes(b'synthetic fixture bytes')
        entry = encrypt._Entry(path.name, False, encrypt._stamp(path.stat()), path.stat().st_size)
        raw = []
        original_open = os.open
        def record_open(name, flags, *args, **kwargs):
            fd = original_open(name, flags, *args, **kwargs)
            if name == path.name:
                raw.append(fd)
            return fd
        with mock.patch.object(encrypt.os, 'open', side_effect=record_open), mock.patch.object(encrypt.os, 'fdopen', side_effect=failure):
            try:
                encrypt._VerifiedReader(root, entry, time.monotonic() + 1)
            except BaseException as actual:
                assert actual is failure
        fd = raw[-1]
        try:
            after = os.fstat(fd)
            leaked = (after.st_dev, after.st_ino) == entry.identity[:2]
        except OSError:
            leaked = False
        print(type(failure).__name__, 'raw_source_descriptor_leaked=', leaked)
        if leaked:
            os.close(fd)
