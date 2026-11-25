"""Scratch-only independent probe for private control recovery close ownership."""

from contextlib import contextmanager
import errno
import hashlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest import mock

import p06_qualified_warm_control as control
from test_p06_qualified_warm_control import AZURE, BODY, Response


@contextmanager
def opener(_value, *, timeout):
    yield Response()


with tempfile.TemporaryDirectory(prefix="p06-a21-recovery-") as root:
    output = Path(root).resolve() / "intake"
    real_open, real_close = os.open, os.close
    real_output_close = control._PrivateOutput.close
    recovering = False
    recovery_opens, recovery_closes = [], []
    sentinel_fd = None
    injected = False

    def close_output(value):
        global recovering
        real_output_close(value)
        recovering = True
        raise OSError(errno.EIO, "synthetic-private-detail " + AZURE)

    def record_open(path, flags, *args, **kwargs):
        descriptor = real_open(path, flags, *args, **kwargs)
        if recovering:
            recovery_opens.append((str(path), descriptor))
        return descriptor

    def fail_first_recovery_close(descriptor):
        global injected, sentinel_fd
        if recovering:
            recovery_closes.append(descriptor)
        real_close(descriptor)
        if recovering and not injected:
            injected = True
            # Models another thread reusing the consumed descriptor before
            # the close error is processed by directory traversal.
            sentinel_fd = real_open("/dev/null", os.O_RDONLY)
            assert sentinel_fd == descriptor
            raise OSError(errno.EIO, "synthetic-private-detail " + AZURE)

    with mock.patch.object(control, "_reviewed_identity", return_value={
            "sha256": hashlib.sha256(BODY).hexdigest(), "size_bytes": len(BODY)}), \
            mock.patch.object(control.os, "fstatvfs", return_value=SimpleNamespace(
                f_bavail=100 * 1024**3, f_frsize=1)), \
            mock.patch.dict(os.environ, {control.URL_ENVIRONMENT_VARIABLE: AZURE}), \
            mock.patch.object(control._PrivateOutput, "close", new=close_output), \
            mock.patch.object(control.os, "open", side_effect=record_open), \
            mock.patch.object(control.os, "close", side_effect=fail_first_recovery_close):
        try:
            control.acquire_control(output, opener=opener)
        except control.IntakeError as error:
            code = error.code
            assert str(error) == control._REASONS["storage_failed"]
        else:
            raise AssertionError("expected storage failure")

    def live(descriptor):
        try:
            os.fstat(descriptor)
            return True
        except OSError as error:
            assert error.errno == errno.EBADF
            return False

    leaked = [descriptor for _, descriptor in recovery_opens if live(descriptor)]
    observations = {
        "error_code": code,
        "recovery_opens": recovery_opens,
        "recovery_close_attempts": recovery_closes,
        "unowned_reused_descriptor_still_open": live(sentinel_fd),
        "leaked_recovery_descriptors": leaked,
        "archive_unchanged": (output / control.ARCHIVE_NAME).read_bytes() == BODY,
        "receipt_outcome": json.loads((output / control.RECEIPT_NAME).read_bytes())["outcome"],
    }
    for descriptor in set(leaked + [sentinel_fd]):
        if live(descriptor):
            real_close(descriptor)
    print(json.dumps(observations, indent=2, sort_keys=True))
