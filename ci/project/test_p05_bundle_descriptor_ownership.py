# SPDX-License-Identifier: Apache-2.0
"""Host-only descriptor ownership checks using real CPython audit failures."""

import errno
import hashlib
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


def _probe(root, reader, scenario):
    import resource

    check = unittest.TestCase()
    if reader == "installed":
        spec = importlib.util.spec_from_file_location(
            "descriptor_bundle", root / "python/vortex_ai/_bundle.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    else:
        sys.path.insert(0, str(root / "ci/project"))
        import p05_bundle as module

    with tempfile.TemporaryDirectory(prefix="p05-descriptor-host-only-") as temporary:
        directory = Path(temporary)
        raw = b"host-only bounded bundle bytes\n" * 257
        path = directory / "input"
        path.write_bytes(raw)
        target = path.stat()
        descriptors = []
        failure = None

        def audit(event, args):
            if event == "open" and type(args[0]) is int:
                info = os.fstat(args[0])
                if (info.st_dev, info.st_ino) == (target.st_dev, target.st_ino):
                    descriptors.append(args[0])
                    if failure is not None:
                        raise failure

        def read(limit):
            if reader == "installed":
                return module._read_regular(directory, "input", limit=limit, retain=True)
            return module._consume(directory, "input", limit=limit, collect=True)

        def closed_since(start):
            check.assertGreater(len(descriptors), start, "fdopen audit event was not reached")
            for descriptor in set(descriptors[start:]):
                with check.assertRaises(OSError) as caught:
                    os.fstat(descriptor)
                check.assertEqual(caught.exception.errno, errno.EBADF)

        # Audit hooks cannot be removed; this entire probe runs in a child.
        sys.addaudithook(audit)
        try:
            attempts = 1
            error_type = {"RuntimeError": RuntimeError, "MemoryError": MemoryError,
                          "KeyboardInterrupt": KeyboardInterrupt, "OSError": OSError}
            if scenario == "repeated":
                soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
                budget = 64 if soft == resource.RLIM_INFINITY else min(soft, 64)
                resource.setrlimit(resource.RLIMIT_NOFILE, (budget, hard))
                attempts = 2 * budget
                scenario = "RuntimeError"
            for _ in range(attempts):
                failure = error_type[scenario]("fdopen construction rejected")
                with check.assertRaises(BaseException) as caught:
                    read(len(raw))
                if reader == "installed" and isinstance(failure, OSError):
                    check.assertIs(type(caught.exception), module.BundleError)
                    check.assertIs(caught.exception.__cause__, failure)
                else:
                    check.assertIs(caught.exception, failure)
            check.assertEqual(len(descriptors), attempts)
            closed_since(0)

            failure = None
            start = len(descriptors)
            result = read(len(raw))
            size_key = "size" if reader == "installed" else "size_bytes"
            check.assertEqual(result[0], {"path": "input", size_key: len(raw),
                                         "sha256": hashlib.sha256(raw).hexdigest()})
            check.assertEqual(result[-1], raw)
            closed_since(start)

            start = len(descriptors)
            with check.assertRaises(ValueError):
                read(len(raw) - 1)
            closed_since(start)
        finally:
            failure = None
            # Retain the assertion even when testing a leaking source revision.
            for descriptor in set(descriptors):
                try:
                    info = os.fstat(descriptor)
                except OSError:
                    continue
                if (info.st_dev, info.st_ino) == (target.st_dev, target.st_ino):
                    os.close(descriptor)
    print("descriptor ownership verified")


class BundleDescriptorOwnershipTests(unittest.TestCase):
    def probe(self, reader, scenario):
        completed = subprocess.run(
            [sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--probe",
             str(ROOT), reader, scenario],
            capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(completed.stdout, "descriptor ownership verified\n")

    def test_installed_fdopen_failure_closes_descriptor_and_preserves_error(self):
        for error in ("RuntimeError", "MemoryError", "KeyboardInterrupt", "OSError"):
            with self.subTest(error=error):
                self.probe("installed", error)

    def test_producer_fdopen_failure_closes_descriptor_and_preserves_error(self):
        for error in ("RuntimeError", "MemoryError", "KeyboardInterrupt", "OSError"):
            with self.subTest(error=error):
                self.probe("producer", error)

    def test_repeated_installed_fdopen_failures_do_not_exhaust_descriptors(self):
        self.probe("installed", "repeated")

    def test_repeated_producer_fdopen_failures_do_not_exhaust_descriptors(self):
        self.probe("producer", "repeated")


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "--probe":
        _probe(Path(sys.argv[2]), sys.argv[3], sys.argv[4])
    else:
        unittest.main()
