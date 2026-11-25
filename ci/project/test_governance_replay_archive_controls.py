# SPDX-License-Identifier: Apache-2.0
"""Independent control for local metadata on descriptor-bearing members."""

import io
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile

import governance_replay_archive as reader


class _Nonseekable(io.BytesIO):
    def seek(self, *arguments):
        raise io.UnsupportedOperation("seek")


class GovernanceReplayArchiveControlsTests(unittest.TestCase):
    def test_descriptor_cannot_override_contradictory_local_metadata(self):
        name, contents = "run/summary.json", b'{"status":"completed"}\n'
        output = _Nonseekable()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr(zipfile.ZipInfo(name), contents)
        original = output.getvalue()
        central = struct.unpack_from("<I", original, len(original) - 6)[0]
        expected = struct.unpack_from("<3I", original, central + 16)
        self.assertEqual(struct.unpack_from("<H", original, 6)[0] & 8, 8)
        self.assertTrue(all(expected))

        with tempfile.TemporaryDirectory(prefix="governance-descriptor-") as temporary:
            path = Path(temporary).resolve() / "governance.zip"
            populated = bytearray(original)
            struct.pack_into("<3I", populated, 14, *expected)
            path.write_bytes(populated)
            self.assertEqual(reader.read_archive(path)["members"], {name: contents})

            for index, field in enumerate(("crc", "compressed_size", "expanded_size")):
                with self.subTest(field=field):
                    conflicting = bytearray(populated)
                    struct.pack_into("<I", conflicting, 14 + index * 4, 0)
                    path.write_bytes(conflicting)
                    with self.assertRaisesRegex(reader.ArchiveError, "local descriptor placeholders"):
                        reader.read_archive(path, retain=())


if __name__ == "__main__":
    unittest.main()
