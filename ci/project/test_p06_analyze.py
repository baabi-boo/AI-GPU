# SPDX-License-Identifier: Apache-2.0
"""End-to-end analyzer checks using synthetic packets, never native evidence."""

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import p06_analyze as analyze
from p06_test_packets import REVISION, synthetic_packet, write_archive
from test_p06_replay import edit_record, edit_report, edit_snapshot, replace_log


class AnalyzerIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix="p06-analyzer-inputs-")
        cls.addClassCleanup(temporary.cleanup)
        cls.input_root = Path(temporary.name)
        cls.members = {fmt: synthetic_packet(fmt) for fmt in ("fp16", "bf16")}
        cls.paths = {fmt: cls.input_root / (fmt + ".zip") for fmt in cls.members}
        cls.digests = {fmt: write_archive(cls.paths[fmt], members)
                       for fmt, members in cls.members.items()}

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="p06-analyzer-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def check(self, *, paths=None, digests=None, revision=REVISION):
        paths = self.paths if paths is None else paths
        digests = self.digests if digests is None else digests
        return analyze.analyze_archives(paths["fp16"], digests["fp16"],
                                        paths["bf16"], digests["bf16"],
                                        expected_revision=revision)

    def changed(self, fmt, change):
        members = dict(self.members[fmt])
        change(members)
        paths, digests = dict(self.paths), dict(self.digests)
        paths[fmt] = self.root / (fmt + "-changed.zip")
        digests[fmt] = write_archive(paths[fmt], members)
        return {"paths": paths, "digests": digests}

    def cli_args(self, destination):
        return ["--fp16-archive", str(self.paths["fp16"]),
                "--fp16-sha256", self.digests["fp16"],
                "--bf16-archive", str(self.paths["bf16"]),
                "--bf16-sha256", self.digests["bf16"],
                "--source-revision", REVISION, "--output", str(destination)]

    def test_complete_matrix_is_rebuilt_without_execution_or_acceptance_claims(self):
        result = self.check()
        self.assertEqual(result["outcome"], "pass")
        self.assertEqual(result["source_revision"], REVISION)
        self.assertEqual(result["native_execution"], "not_run")
        for claim in ("acceptance_claimed", "phase_complete", "optimization_claimed"):
            self.assertIs(result[claim], False)
        summary = result["summary"]
        self.assertIs(summary["full_matrix"], True)
        self.assertIs(summary["acceptance_claimed"], False)
        self.assertEqual(summary["formats"], ["fp16", "bf16"])
        self.assertEqual(summary["inventory"], {
            "workloads": 8, "warmup_processes": 8, "measured_processes": 40,
            "total_processes": 48, "warmup_launches": 12,
            "measured_launches": 60, "total_launches": 72,
        })
        self.assertEqual(len(summary["workloads"]), 8)
        for row in summary["workloads"]:
            self.assertEqual(len(row["warmup_sample_ids"]), 1)
            self.assertEqual(len(row["measured_sample_ids"]), 5)
        for fmt, path in self.paths.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), self.digests[fmt])

    def test_missing_format_archive_cannot_be_salvaged_as_a_partial_matrix(self):
        for fmt in self.paths:
            paths = dict(self.paths, **{fmt: self.root / (fmt + "-missing.zip")})
            with self.subTest(format=fmt), self.assertRaises((OSError, ValueError)):
                self.check(paths=paths)

    def test_supplied_digest_and_revision_are_required_for_each_original(self):
        for fmt in self.paths:
            for digest in ("0" * 64, "not-a-sha256"):
                digests = dict(self.digests, **{fmt: digest})
                with self.subTest(format=fmt, digest=digest), self.assertRaises(ValueError):
                    self.check(digests=digests)
        for revision in ("b" * 40, "short", True):
            with self.subTest(revision=revision), self.assertRaises(ValueError):
                self.check(revision=revision)

    def test_swapped_or_duplicated_formats_are_rejected_with_matching_digests(self):
        for mapping in ({"fp16": "bf16", "bf16": "fp16"},
                        {"fp16": "fp16", "bf16": "fp16"},
                        {"fp16": "bf16", "bf16": "bf16"}):
            paths = {fmt: self.paths[source] for fmt, source in mapping.items()}
            digests = {fmt: self.digests[source] for fmt, source in mapping.items()}
            with self.subTest(mapping=mapping), self.assertRaises(ValueError):
                self.check(paths=paths, digests=digests)

    def test_rehashed_agreeing_summary_copies_do_not_override_original_samples(self):
        def corrupt(members):
            edit_report(members, lambda report: report["summary"]["inventory"].update(
                measured_processes=19))
            edit_snapshot(members, "summary_snapshot", lambda summary:
                          summary["inventory"].update(measured_processes=19))

        for fmt in self.paths:
            arguments = self.changed(fmt, corrupt)
            with self.subTest(format=fmt), self.assertRaisesRegex(ValueError, "summary"):
                self.check(**arguments)

    def test_corrupt_raw_warmup_numerics_override_stored_success_in_either_format(self):
        for fmt in self.paths:
            def corrupt(members):
                command = "simx-" + fmt + "-single-dense_boundaries-warmup-0"
                replace_log(members, command, lambda body: edit_record(
                    body, "P03_RESULT", lambda row: row["actual_bits"].__setitem__(0, "deadbeef")))

            arguments = self.changed(fmt, corrupt)
            with self.subTest(format=fmt), self.assertRaisesRegex(
                    ValueError, "output|actual_bits|numerical|expected"):
                self.check(**arguments)

    def test_incomplete_measured_sample_inventory_cannot_use_a_retained_summary(self):
        for fmt in self.paths:
            arguments = self.changed(fmt, lambda members:
                                     edit_report(members, lambda report: report["samples"].pop()))
            with self.subTest(format=fmt), self.assertRaisesRegex(ValueError, "sample inventory"):
                self.check(**arguments)

    def test_cli_success_writes_exclusively_without_changing_existing_output(self):
        destination = self.root / "analysis.json"
        arguments = self.cli_args(destination)
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(analyze.main(arguments), 0)
        self.assertEqual(json.loads(output.getvalue())["outcome"], "pass")
        original = destination.read_bytes()
        report = json.loads(original)
        self.assertEqual(report["native_execution"], "not_run")
        self.assertIs(report["acceptance_claimed"], False)
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(analyze.main(arguments), 1)
        self.assertEqual(json.loads(output.getvalue())["outcome"], "fail")
        self.assertEqual(destination.read_bytes(), original)

    def test_cli_invalid_input_returns_failure_without_creating_a_report(self):
        destination = self.root / "must-not-exist.json"
        arguments = self.cli_args(destination)
        arguments[arguments.index("--bf16-sha256") + 1] = "0" * 64
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(analyze.main(arguments), 1)
        self.assertEqual(json.loads(output.getvalue())["outcome"], "fail")
        self.assertFalse(destination.exists())

    def test_cli_requires_both_format_identities(self):
        destination = self.root / "must-not-exist.json"
        arguments = self.cli_args(destination)
        index = arguments.index("--bf16-sha256")
        del arguments[index:index + 2]
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            analyze.main(arguments)
        self.assertEqual(error.exception.code, 2)
        self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
