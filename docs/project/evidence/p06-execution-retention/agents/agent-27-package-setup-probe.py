# SPDX-License-Identifier: Apache-2.0
"""Independent real-fd regression for _package output setup ownership."""
import errno
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import p06_qualified_warm_pack as pack


class PackagingSetupOwnershipProbe(unittest.TestCase):
    def test_consumed_parent_close_releases_opened_output(self):
        real_open, real_close = os.open, os.close
        failure = OSError(errno.EIO, "consumed output-parent close")

        class OSProxy:
            parent = output = unrelated = None

            def __getattr__(self, key):
                return getattr(os, key)

            def open(self, path, flags, *args, **kwargs):
                descriptor = real_open(path, flags, *args, **kwargs)
                if path == "result":
                    self.parent = kwargs["dir_fd"]
                    self.output = descriptor
                return descriptor

            def close(self, descriptor):
                real_close(descriptor)
                if self.output is not None and descriptor == self.parent and self.unrelated is None:
                    self.unrelated = real_open("/dev/null", os.O_RDONLY | os.O_CLOEXEC)
                    if self.unrelated != descriptor:
                        raise AssertionError("real descriptor reuse did not occur")
                    raise failure

        def is_open(descriptor):
            try:
                os.fstat(descriptor)
                return True
            except OSError as error:
                self.assertEqual(error.errno, errno.EBADF)
                return False

        with tempfile.TemporaryDirectory(prefix="agent27-package-") as temporary:
            root = Path(temporary)
            source, workspace = root / "source", root / "workspace"
            source.mkdir()
            workspace.mkdir()
            probe = OSProxy()
            try:
                with mock.patch.object(pack, "os", probe):
                    with self.assertRaises(OSError) as caught:
                        pack.package_partial(source_dir=source, workspace_dir=workspace,
                            output_dir=root / "result", writers_finished=True)
                result = {
                    "original_exception_preserved": caught.exception is failure,
                    "closed_parent_fd": probe.parent,
                    "reused_unrelated_fd": probe.unrelated,
                    "unrelated_fd_survives": is_open(probe.unrelated),
                    "output_fd": probe.output,
                    "output_fd_leaked": is_open(probe.output),
                }
                if result["output_fd_leaked"]:
                    result["output_fd_target"] = os.readlink("/proc/self/fd/" + str(probe.output))
                print(json.dumps(result, sort_keys=True), flush=True)
                self.assertTrue(result["original_exception_preserved"])
                self.assertTrue(result["unrelated_fd_survives"])
                self.assertFalse(result["output_fd_leaked"], "opened output fd escaped _package setup cleanup")
            finally:
                for descriptor in (probe.output, probe.unrelated):
                    if descriptor is not None and is_open(descriptor):
                        real_close(descriptor)


if __name__ == "__main__":
    unittest.main(verbosity=2)
