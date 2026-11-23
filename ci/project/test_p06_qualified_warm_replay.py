# SPDX-License-Identifier: Apache-2.0
"""Explicit reader boundaries; full native packets have separate integration tests."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import unittest
from unittest import mock

import p06_qualified_warm_replay as replay


class WarmReportDecoderTests(unittest.TestCase):
    def test_complete_population_can_exceed_historical_structure_bound(self):
        body = json.dumps({"values": [0] * 300000}).encode()
        self.assertEqual(len(replay.decode_report(body)["values"]), 300000)
        with self.assertRaisesRegex(ValueError, "structure bound"):
            replay.native.dependency_replay._archive_api().strict_json(body)

    def test_exact_new_node_boundary_and_one_over(self):
        count = replay.MAX_REPORT_NODES - 2
        body = b'{"values":[' + b'0,' * (count - 1) + b'0]}'
        self.assertEqual(len(replay.decode_report(body)["values"]), count)
        with self.assertRaisesRegex(ValueError, "structure bound"):
            replay.decode_report(body[:-2] + b',0]}')

    def test_report_byte_bound_is_independent_of_structure(self):
        body = b'{"value":"' + b'a' * 28 + b'"}'
        self.assertEqual(len(body), 40)
        with mock.patch.object(replay, "MAX_REPORT_BYTES", 40):
            self.assertEqual(replay.decode_report(body)["value"], "a" * 28)
            with self.assertRaisesRegex(ValueError, "byte bound"):
                replay.decode_report(body + b' ')

    def test_depth_boundary_and_one_over(self):
        self.assertIsInstance(replay.decode_report(b'{"a":' * 64 + b'0' + b'}' * 64), dict)
        with self.assertRaisesRegex(ValueError, "structure bound"):
            replay.decode_report(b'{"a":' * 65 + b'0' + b'}' * 65)

    def test_malformed_duplicate_and_nonfinite_numbers_reject(self):
        examples = [b'', b' ', b'[]', b'null', b'1', b'\xff', b'{"x":0}\x00',
            b'{"x":1,"x":2}', b'{"x":{"a":1,"a":2}}', b'{"x":NaN}',
            b'{"x":Infinity}', b'{"x":-Infinity}', b'{"x":1e999}',
            b'{"x":' + b'9' * 65 + b'}', b'{"x":0.' + b'9' * 65 + b'}']
        for body in examples:
            with self.subTest(body=body[:80]), self.assertRaises(ValueError):
                replay.decode_report(body)

    def test_only_report_json_uses_new_decoder(self):
        original = mock.Mock()
        original.read.return_value = b'{"duration":0.125}'
        original.json.return_value = {"old": True}
        selected = replay._WarmReportView(original)
        self.assertEqual(selected.json("report.json"), {"duration": 0.125})
        original.read.assert_called_once_with("report.json", limit=replay.MAX_REPORT_BYTES)
        original.json.assert_not_called()
        self.assertEqual(selected.json("other.json", integers_only=True), {"old": True})
        original.json.assert_called_once_with("other.json", integers_only=True)
        with self.assertRaisesRegex(ValueError, "supervised durations"):
            selected.json("report.json", integers_only=True)


class WarmReplayRouteTests(unittest.TestCase):
    def test_historical_defaults_and_new_complete_population_are_separate(self):
        self.assertEqual(replay.native._NativeReplay.complete_counts["processes"], 4)
        self.assertEqual(replay.native._NativeReplay.command_count, 37)
        self.assertEqual(replay.historical_replay._QualifiedReplay.complete_counts["processes"], 4)
        self.assertEqual(replay._QualifiedWarmReplay.complete_counts, replay.contract.COMPLETE_COUNTS)
        self.assertEqual(replay._QualifiedWarmReplay.command_count, 57)
        self.assertEqual(replay.REPORT_FIELDS - replay.historical_replay.REPORT_FIELDS,
                         {"qualified_warm_passed"})

    def test_native_argv_binds_every_actual_pair_and_explicit_mode(self):
        reader = object.__new__(replay._QualifiedWarmReplay)
        reader.build = Path("/selected-build")
        digest = "a" * 64
        for planned in replay.contract.process_plan():
            arguments = reader.process_arguments(planned, digest)
            self.assertEqual(arguments[1:3], ["--lifetime", "--qualified-warm"])
            for flag, value in (("--policy", planned["policy"]),
                    ("--qualification-id", digest), ("--sample-id", planned["sample_id"]),
                    ("--pair-index", str(planned["pair_index"])), ("--phase", planned["phase"])):
                self.assertEqual(arguments[arguments.index(flag) + 1], value)

    def test_historical_argv_remains_pair_zero_without_warm_opt_in(self):
        reader = object.__new__(replay.native._NativeReplay)
        reader.build = Path("/selected-build")
        planned = replay.native.manifest.process_plan()[0]
        arguments = reader.process_arguments(planned, "a" * 64)
        self.assertNotIn("--qualified-warm", arguments)
        self.assertEqual(arguments[-4:], ["--pair-index", "0", "--phase", "warmup"])

    def test_both_bindings_include_exact_frozen_population(self):
        reader = object.__new__(replay._QualifiedWarmReplay)
        reader.qualification_pin = replay.contract.SOURCE_PROOF_SHA256
        reader.counter_admission = {"verified": "test-boundary-only"}
        build = reader.build_binding_extra()
        process = reader.process_binding_extra(replay.contract.process_plan()[0])
        self.assertEqual(build["warm_sampling"], replay.contract.sampling_binding())
        self.assertEqual(process["warm_sampling"], build["warm_sampling"])
        self.assertEqual(process["counter_qualification_sha256"], reader.qualification_pin)
        build["warm_sampling"]["processes"].clear()
        self.assertEqual(len(reader.build_binding_extra()["warm_sampling"]["processes"]), 24)

    def test_new_output_route_receives_actual_identity_without_normalization(self):
        reader = object.__new__(replay._QualifiedWarmReplay)
        reader.contract, reader.case, reader.fmt, reader.libraries = {}, {}, "bf16", {}
        planned = replay.contract.process_plan()[-1]
        with mock.patch.object(replay.records, "verify_output", return_value={"raw": True}) as verify:
            self.assertEqual(reader.verify_process_output("original bytes", planned, "a" * 64), {"raw": True})
        self.assertEqual(verify.call_args.args, ("original bytes",))
        self.assertEqual(verify.call_args.kwargs["pair_index"], 5)
        self.assertEqual(verify.call_args.kwargs["phase"], "measured")
        self.assertEqual(verify.call_args.kwargs["process_id"], planned["id"])

    def test_trusted_inventory_includes_all_fixed_proof_and_reference_inputs(self):
        self.assertEqual(tuple(row["path"] for row in replay.admission.reader_sources()), replay.ADMISSION_HELPERS)
        self.assertEqual(len(replay.RUNNER_HELPERS), 81)
        names = {row["path"] for row in replay.TRUSTED_READER_SOURCES}
        expected = {row["path"] for row in replay.historical_replay._reader_sources()}
        expected.update(replay.ADMISSION_HELPERS)
        expected.update({"ci/project/p06_qualified_warm_replay.py",
                         "ci/project/p06_qualified_warm_records.py",
                         "ci/project/p06_qualified_warm_analyze.py", replay.contract.SOURCE_PROOF_PATH})
        self.assertEqual(names, expected)
        self.assertEqual(replay._reader_sources(), replay.TRUSTED_READER_SOURCES)

    def test_external_pin_and_revision_validation_precedes_archive_reads(self):
        arguments = dict(expected_revision="a" * 40, expected_receipt_sha256="a" * 64,
            expected_native_report_sha256="a" * 64, expected_source_manifest_sha256="a" * 64,
            expected_qualification_sha256=replay.contract.SOURCE_PROOF_SHA256,
            diagnostic_archive=Path("/selected-diagnostic.zip"), diagnostic_sha256="a" * 64,
            control_archive=Path("/selected-control.zip"), control_sha256="a" * 64)
        for key in ("expected_revision", "expected_receipt_sha256", "expected_native_report_sha256",
                    "expected_source_manifest_sha256", "expected_qualification_sha256",
                    "diagnostic_sha256", "control_sha256"):
            view = mock.Mock()
            with self.subTest(key=key), self.assertRaises(ValueError):
                replay.verify_view(view, mock.Mock(), mock.Mock(), **dict(arguments, **{key: "invalid"}))
            view.read.assert_not_called()

    def test_cli_failure_never_claims_warm_or_performance_success(self):
        argv = ["--archive", "/missing.zip", "--sha256", "invalid", "--source-revision", "a" * 40,
            "--dependency-receipt-sha256", "a" * 64, "--native-report-sha256", "a" * 64,
            "--source-manifest-sha256", "a" * 64,
            "--counter-qualification-sha256", replay.contract.SOURCE_PROOF_SHA256,
            "--diagnostic-archive", "/diagnostic.zip", "--diagnostic-archive-sha256", "a" * 64,
            "--control-archive", "/control.zip", "--control-archive-sha256", "a" * 64]
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(replay.main(argv), 1)
        result = json.loads(output.getvalue())
        self.assertIs(result["qualified_warm_passed"], False)
        self.assertEqual(result["native_execution"], "not_run")
        for name in replay.contract.FALSE_CLAIMS:
            self.assertIs(result[name], False)


if __name__ == "__main__":
    unittest.main()
