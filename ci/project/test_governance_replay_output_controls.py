# SPDX-License-Identifier: Apache-2.0
"""Receipt publication preserves names owned by concurrent writers."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import governance_replay as replay


class GovernanceReplayOutputControlsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="governance-output-controls-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source = self.root / "source"
        self.source.mkdir()
        self.output = self.root / "receipt.json"
        self.replacement = self.root / "replacement"
        self.replacement.write_bytes(b"unrelated replacement")

    def test_failed_sync_cannot_delete_a_replacement_after_ownership_stat(self):
        original_stat = os.stat

        def replace_after_stat(path, *args, **options):
            info = original_stat(path, *args, **options)
            if path == self.output.name and options.get("dir_fd") is not None:
                os.replace(self.replacement, path, dst_dir_fd=options["dir_fd"])
            return info

        with mock.patch.object(replay.os, "fsync", side_effect=OSError("injected write failure")), \
                mock.patch.object(replay.os, "stat", side_effect=replace_after_stat):
            with self.assertRaises(OSError):
                replay._write_output(self.output, b"{}\n", self.source)
        remaining = [path.read_bytes() for path in (self.replacement, self.output) if path.exists()]
        self.assertIn(b"unrelated replacement", remaining)

    def test_postpublication_replacement_is_preserved_and_rejected(self):
        original_link = os.link

        def replace_after_link(source, destination, **options):
            original_link(source, destination, **options)
            os.replace(self.replacement, destination, dst_dir_fd=options["dst_dir_fd"])

        with mock.patch.object(replay.os, "link", side_effect=replace_after_link):
            with self.assertRaisesRegex(replay.ReplayError, "output changed"):
                replay._write_output(self.output, b"{}\n", self.source)
        self.assertEqual(self.output.read_bytes(), b"unrelated replacement")


if __name__ == "__main__":
    unittest.main()
