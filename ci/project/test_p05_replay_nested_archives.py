# SPDX-License-Identifier: Apache-2.0
"""Synthetic host-only malformed nested-tar checks; no retained execution."""

import contextlib
import gzip
import io
import json
import tarfile
import unittest
from unittest.mock import patch

import p05_replay_installation as installation
import p05_torch_replay as driver
from p06_replay import _archive_api
from test_p05_replay_installation import SyntheticInstallation, record, source_archive, wheel_bytes


def truncated_sparse_archive(*, later=False):
    item = tarfile.TarInfo("vortex_ai-0.1.0/setup.py")
    item.type = tarfile.GNUTYPE_SPARSE
    header = bytearray(item.tobuf(format=tarfile.GNU_FORMAT))
    header[482] = 1  # Promises a GNU sparse extension block that is absent.
    header[148:156] = b"        "
    header[148:156] = ("%06o\0 " % sum(header)).encode("ascii")
    prefix = b""
    if later:
        earlier = tarfile.TarInfo("vortex_ai-0.1.0/earlier.txt")
        earlier.size = 1
        prefix = earlier.tobuf(format=tarfile.GNU_FORMAT) + b"x" + b"\0" * 511
    return gzip.compress(prefix + bytes(header), mtime=0)


def installation_with_sdist(raw):
    fixture = SyntheticInstallation()
    for index, row in enumerate(fixture.pr["packages"]):
        if row["path"].endswith(".tar.gz"):
            fixture.files["python/" + row["path"]] = raw
            fixture.pr["packages"][index] = record(row["path"], raw)
            return fixture
    raise AssertionError("synthetic source archive is missing")


class NestedArchiveBoundaryTests(unittest.TestCase):
    def test_valid_nested_archives_and_installation(self):
        fixture, api = SyntheticInstallation(), _archive_api()
        members, rows = installation._wheel_members(wheel_bytes(fixture.wheel_members), fixture.manifest, api)
        self.assertEqual(members, fixture.wheel_members)
        self.assertEqual(len(rows), 11)
        self.assertEqual(installation._sdist_members(source_archive({"setup.py": b"inert"}), api),
                         {"setup.py": b"inert"})
        self.assertEqual(fixture.run()["summary"]["scope"], "retained-installation-consistency")

    def test_sparse_parser_failure_at_initial_and_later_headers(self):
        for later in (False, True):
            with self.subTest(later=later), self.assertRaisesRegex(installation.InstallationError,
                                                                 "malformed source archive header"):
                installation._sdist_members(truncated_sparse_archive(later=later), _archive_api())

    def test_installation_verifier_normalizes_sparse_parser_failure(self):
        for later in (False, True):
            fixture = installation_with_sdist(truncated_sparse_archive(later=later))
            with self.subTest(later=later), self.assertRaisesRegex(installation.InstallationError,
                                                                 "malformed source archive header"):
                fixture.run()

    def test_cli_returns_structured_failure_from_real_installation_verifier(self):
        # Stub only the top-level replay seam: all installation joins and nested
        # parsing are real. This does not claim complete public archive replay.
        for later in (False, True):
            fixture = installation_with_sdist(truncated_sparse_archive(later=later))
            output = io.StringIO()
            with self.subTest(later=later), \
                    patch.object(driver, "replay_archive", side_effect=lambda *args, **kwargs: fixture.run()), \
                    contextlib.redirect_stdout(output):
                status = driver.main(["--archive", "/unused-synthetic.zip", "--sha256", "0" * 64,
                                      "--expected-revision", "a" * 40, "--format", "fp16"])
            result = json.loads(output.getvalue())
            self.assertEqual(status, 1)
            self.assertEqual(result["outcome"], "fail")
            self.assertIn("malformed source archive header", result["reason"])
            self.assertEqual(result["native_execution"], "not_run")
            for field in ("retained_code_executed", "acceptance_claimed", "phase_acceptance"):
                self.assertIs(result[field], False)

    def test_validation_index_error_is_not_hidden_by_parser_normalization(self):
        api = _archive_api()
        with patch.object(api, "relative_name", side_effect=IndexError("validation bug")), \
                self.assertRaisesRegex(IndexError, "validation bug"):
            installation._sdist_members(source_archive({"setup.py": b"inert"}), api)


if __name__ == "__main__":
    unittest.main()
