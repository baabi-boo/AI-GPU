# SPDX-License-Identifier: Apache-2.0
"""Real-filesystem seal containment regressions using synthetic packet data."""

import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest

import baseline_packet as packet
from baseline_packet_fixture import make_packet
from baseline_packet_io import PacketError


CLI = Path(__file__).resolve().with_name("baseline_packet.py")
CONTAINMENT_ERROR = "manifest output must be outside the retained packet"


@unittest.skipUnless(os.name == "posix" and hasattr(os, "O_NOFOLLOW"),
                     "packet filesystem safety requires POSIX no-follow support")
class PacketContainmentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.root = self.base / "packet"
        make_packet(self.root)

    @staticmethod
    def spelling(path, separators):
        return "/" * separators + str(path).lstrip("/")

    @staticmethod
    def snapshot(root):
        """Record contents and stable metadata; reads may update access times."""
        result = {}
        for path in [root, *root.rglob("*")]:
            info = path.lstat()
            if stat.S_ISREG(info.st_mode):
                contents = path.read_bytes()
            elif stat.S_ISLNK(info.st_mode):
                contents = os.readlink(path)
            else:
                contents = None
            result[path.relative_to(root).as_posix()] = (
                info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
                info.st_mtime_ns, info.st_ctime_ns, contents,
            )
        return result

    def seal(self, root, output):
        before = self.snapshot(self.root)
        completed = subprocess.run(
            [sys.executable, "-B", str(CLI), "seal", str(root),
             "--output", str(output)],
            cwd=self.base, capture_output=True, text=True, check=False, timeout=30,
        )
        self.assertEqual(completed.stderr, "")
        self.assertEqual(self.snapshot(self.root), before,
                         "seal changed retained packet contents or metadata")
        return completed.returncode, json.loads(completed.stdout)

    def assert_refused(self, root, output, *, containment=True):
        status, result = self.seal(root, output)
        self.assertEqual(status, 1)
        self.assertEqual(result["outcome"], "fail")
        self.assertEqual(result["integrity"], "invalid")
        self.assertIs(result["phase_complete"], False)
        self.assertNotIn("manifest_written", result)
        if containment:
            self.assertEqual(result["errors"], [CONTAINMENT_ERROR])
        else:
            self.assertTrue(result["errors"])

    def test_cli_refuses_inside_output_with_mixed_leading_separators(self):
        for root_slashes, output_slashes in ((1, 2), (2, 1), (2, 2), (3, 2), (2, 3)):
            with self.subTest(root=root_slashes, output=output_slashes):
                destination = self.root / f"inside-{root_slashes}-{output_slashes}.json"
                self.assert_refused(self.spelling(self.root, root_slashes),
                                    self.spelling(destination, output_slashes))
                self.assertFalse(destination.exists())

    def test_cli_refuses_packet_directory_and_nested_output_aliases(self):
        destinations = (self.root, self.root / "report.json",
                        self.root / "logs" / "inside.json")
        for root_slashes, output_slashes in ((1, 2), (2, 1)):
            for destination in destinations:
                with self.subTest(root=root_slashes, output=str(destination)):
                    self.assert_refused(self.spelling(self.root, root_slashes),
                                        self.spelling(destination, output_slashes))

    def test_cli_writes_external_output_for_absolute_spellings(self):
        outside = self.base / "packet-neighbor"
        outside.mkdir()
        expected = None
        for root_slashes in (1, 2, 3):
            for output_slashes in (1, 2, 3):
                with self.subTest(root=root_slashes, output=output_slashes):
                    destination = outside / f"manifest-{root_slashes}-{output_slashes}.json"
                    status, result = self.seal(
                        self.spelling(self.root, root_slashes),
                        self.spelling(destination, output_slashes),
                    )
                    self.assertEqual(status, 0)
                    self.assertIs(result["manifest_written"], True)
                    self.assertEqual(json.loads(destination.read_bytes()), result["manifest"])
                    self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)
                    if expected is None:
                        expected = destination.read_bytes()
                    self.assertEqual(destination.read_bytes(), expected)

    def test_cli_writes_external_output_for_relative_spellings(self):
        for index, root in enumerate(("packet", "./packet", "packet/../packet")):
            with self.subTest(root=root):
                output = f"packet/../manifest-relative-{index}.json"
                status, result = self.seal(root, output)
                self.assertEqual(status, 0)
                self.assertIs(result["manifest_written"], True)
                self.assertEqual(json.loads((self.base / output).read_bytes()),
                                 result["manifest"])

    def test_cli_preserves_existing_external_output_under_aliases(self):
        destination = self.base / "existing.json"
        destination.write_bytes(b"prior independent output\n")
        before = self.snapshot(self.base)
        for root_slashes, output_slashes in ((1, 2), (2, 1), (2, 2)):
            with self.subTest(root=root_slashes, output=output_slashes):
                self.assert_refused(self.spelling(self.root, root_slashes),
                                    self.spelling(destination, output_slashes),
                                    containment=False)
                self.assertEqual(self.snapshot(self.base), before)

    def test_cli_refuses_symlink_output_and_parent_under_aliases(self):
        destination = self.base / "existing.json"
        destination.write_bytes(b"preserve symlink target\n")
        linked_output = self.base / "linked.json"
        linked_output.symlink_to(destination)
        linked_parent = self.base / "packet-alias"
        linked_parent.symlink_to(self.root, target_is_directory=True)
        before = self.snapshot(self.base)
        for root_slashes, output_slashes in ((1, 2), (2, 1)):
            for output in (linked_output, linked_parent / "inside.json"):
                with self.subTest(root=root_slashes, output=str(output)):
                    self.assert_refused(self.spelling(self.root, root_slashes),
                                        self.spelling(output, output_slashes),
                                        containment=False)
                    self.assertEqual(self.snapshot(self.base), before)

    def test_writer_root_directory_contains_every_output_spelling(self):
        destination = self.base / "inside-root.json"
        before = self.snapshot(self.base)
        outputs = ["/", "//", "///"]
        outputs.extend(self.spelling(destination, count) for count in (1, 2, 3))
        for root in ("/", "//", "///"):
            for output in outputs:
                with self.subTest(root=root, output=output):
                    with self.assertRaisesRegex(PacketError, CONTAINMENT_ERROR):
                        packet.write_manifest(output, root, {})
                    self.assertEqual(self.snapshot(self.base), before)
                    self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
