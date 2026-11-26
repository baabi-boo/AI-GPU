# SPDX-License-Identifier: Apache-2.0
"""Isolated directory descriptor ownership and first-failure regressions."""

from collections import Counter
import errno
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


SOURCE = Path(__file__).with_name("governance_replay_archive.py")


def _failure(name, message):
    if name == "OSError":
        return OSError(errno.EIO, message)
    if name == "KeyboardInterrupt":
        return KeyboardInterrupt(message)
    raise ValueError(name)


def _probe(source, scenario, primary_name, cleanup_name):
    import resource

    spec = importlib.util.spec_from_file_location("directory_reader", source)
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    check = unittest.TestCase()
    real_open, real_close, real_fstat = os.open, os.close, os.fstat
    opened, closed, reused = [], [], {}
    stat_calls = 0
    primary = _failure(primary_name, "directory operation rejected")
    secondary = _failure(cleanup_name, "directory cleanup rejected")

    def identity(descriptor):
        info = real_fstat(descriptor)
        return info.st_dev, info.st_ino

    def open_directory(*args, **kwargs):
        if scenario == "child_open" and opened:
            raise primary
        descriptor = real_open(*args, **kwargs)
        opened.append((descriptor, identity(descriptor)))
        return descriptor

    def fstat(descriptor):
        nonlocal stat_calls
        stat_calls += 1
        if scenario in ("initial", "repeated", "cleanup") or (
                scenario == "descendant_stat" and stat_calls == 2):
            raise primary
        return real_fstat(descriptor)

    def close(descriptor):
        closed.append(descriptor)
        real_close(descriptor)
        if scenario in ("cleanup", "previous_close"):
            replacement = real_open("/dev/null", os.O_RDONLY | os.O_CLOEXEC)
            if replacement != descriptor:
                os.dup2(replacement, descriptor, inheritable=False)
                real_close(replacement)
            reused[descriptor] = identity(descriptor)
            raise primary if scenario == "previous_close" and len(closed) == 1 else secondary

    with tempfile.TemporaryDirectory(prefix="governance-directory-") as temporary:
        nested = Path(temporary).resolve() / "parent" / "leaf"
        nested.mkdir(parents=True)
        path = Path("/") if scenario in ("initial", "repeated", "cleanup", "root") else nested
        expected = []
        for ancestor in [*reversed(path.parents), path]:
            info = ancestor.stat()
            expected.append((info.st_dev, info.st_ino))
        attempts = 1
        if scenario == "repeated":
            # Descriptor limits belong only to this disposable probe process.
            soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
            budget = 64 if soft == resource.RLIM_INFINITY else min(soft, 64)
            resource.setrlimit(resource.RLIMIT_NOFILE, (budget, hard))
            attempts = 2 * budget
        success = scenario in ("root", "nested")
        returned = None
        try:
            with mock.patch.object(reader.os, "open", side_effect=open_directory), \
                    mock.patch.object(reader.os, "fstat", side_effect=fstat), \
                    mock.patch.object(reader.os, "close", side_effect=close):
                if success:
                    returned, identities = reader._directory(path)
                else:
                    for _ in range(attempts):
                        with check.assertRaises(BaseException) as caught:
                            reader._directory(path)
                        check.assertIs(caught.exception, primary)
            counts = Counter(descriptor for descriptor, _ in opened)
            check.assertEqual(counts, Counter(closed) + (Counter({returned: 1}) if success else Counter()))
            if success:
                check.assertEqual(identities, expected)
                check.assertEqual(identity(returned), expected[-1])
                check.assertFalse(os.get_inheritable(returned))
            elif scenario in ("initial", "repeated", "cleanup"):
                check.assertEqual(len(opened), attempts)
                check.assertEqual(stat_calls, attempts)
            elif scenario == "child_open":
                check.assertEqual(len(opened), 1)
            else:
                check.assertEqual(len(opened), 2)
            if scenario in ("cleanup", "previous_close"):
                check.assertEqual(len(reused), 1 if scenario == "cleanup" else 2)
            for descriptor in counts:
                if descriptor == returned:
                    continue
                if descriptor in reused:
                    check.assertEqual(identity(descriptor), reused[descriptor])
                else:
                    with check.assertRaises(OSError) as caught:
                        real_fstat(descriptor)
                    check.assertEqual(caught.exception.errno, errno.EBADF)
        finally:
            # Release only known identities, including those from a failing old-source control.
            for descriptor, expected_identity in set(opened) | set(reused.items()):
                try:
                    actual = identity(descriptor)
                except OSError:
                    continue
                if actual == expected_identity:
                    real_close(descriptor)
    print("directory ownership verified")


class GovernanceDirectoryOwnershipTests(unittest.TestCase):
    def probe(self, scenario, primary="OSError", cleanup="OSError"):
        completed = subprocess.run(
            [sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--probe",
             str(SOURCE.resolve()), scenario, primary, cleanup],
            capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(completed.stdout, "directory ownership verified\n")

    def test_initial_fstat_oserror_releases_root(self):
        self.probe("initial")

    def test_initial_fstat_interrupt_releases_root(self):
        self.probe("initial", "KeyboardInterrupt")

    def test_repeated_fstat_failures_do_not_exhaust_descriptors(self):
        for primary in ("OSError", "KeyboardInterrupt"):
            with self.subTest(primary=primary):
                self.probe("repeated", primary)

    def test_consuming_cleanup_preserves_primary_without_retry(self):
        for primary in ("OSError", "KeyboardInterrupt"):
            for cleanup in ("OSError", "KeyboardInterrupt"):
                with self.subTest(primary=primary, cleanup=cleanup):
                    self.probe("cleanup", primary, cleanup)

    def test_traversal_failures_release_owned_descriptors(self):
        for scenario in ("child_open", "descendant_stat"):
            for primary in ("OSError", "KeyboardInterrupt"):
                with self.subTest(scenario=scenario, primary=primary):
                    self.probe(scenario, primary)

    def test_consumed_predecessor_is_not_closed_again(self):
        for primary in ("OSError", "KeyboardInterrupt"):
            for cleanup in ("OSError", "KeyboardInterrupt"):
                with self.subTest(primary=primary, cleanup=cleanup):
                    self.probe("previous_close", primary, cleanup)

    def test_success_transfers_live_directory_and_ordered_identities(self):
        for scenario in ("root", "nested"):
            with self.subTest(scenario=scenario):
                self.probe(scenario)


if __name__ == "__main__":
    if len(sys.argv) == 6 and sys.argv[1] == "--probe":
        _probe(Path(sys.argv[2]), sys.argv[3], sys.argv[4], sys.argv[5])
    else:
        unittest.main()
