# SPDX-License-Identifier: Apache-2.0
"""Strict qualified-reader controls using synthetic complete native grammar."""

from contextlib import ExitStack
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

import p06_counter_qualification_replay as replay
from p06_counter_qualification_test_fixture import (
    CONTROL_PATH, DIAGNOSTIC_PATH, SyntheticQualificationPacket,
)
from test_p06_dependency_native_replay import (
    MemoryView, SyntheticNativePacket, descriptor, digest, inert_path_guards,
)


class QualifiedReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = SyntheticNativePacket()
        cls.qualified = SyntheticQualificationPacket()

    def setUp(self):
        self.packet = deepcopy(self.qualified)
        self.patches = ExitStack()
        self.addCleanup(self.patches.close)
        self.diagnostic_reader = self.patches.enter_context(mock.patch.object(
            replay.prerequisites, "verify_prerequisites", return_value=self.packet.diagnostics))
        self.control_reader = self.patches.enter_context(mock.patch.object(
            replay.prerequisites, "verify_control_prerequisite", return_value=self.packet.controls))

    def view_replay(self, packet=None, **overrides):
        packet = packet or self.packet
        packet.finish()
        args = dict(packet.arguments(), **overrides)
        checked = {"retained_dependency_verification": packet.dependency_verification}
        with mock.patch.object(replay.native.dependency_replay, "verify_view", return_value=checked) as dependency:
            result = replay.verify_view(MemoryView(packet.files, packet.api),
                MemoryView({"report.json": packet.dependency_body}, packet.api), packet.api, **args)
        dependency.assert_called_once()
        return result

    def zip_replay(self, *, prefix="", extra=None, selected_prefix=None, wrong_pin=False):
        self.packet.finish()
        files = self.packet.local_files(prefix)
        files.update(extra or {})
        with tempfile.TemporaryDirectory(prefix="p06-qualified-replay-") as directory:
            path = Path(directory) / "original.zip"
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
                for name, body in files.items():
                    archive.writestr(name, body)
            pin = "0" * 64 if wrong_pin else digest(path.read_bytes())
            checked = {"retained_dependency_verification": self.packet.dependency_verification}
            with mock.patch.object(replay.native.dependency_replay, "verify_view", return_value=checked):
                return replay.replay_archive(path, pin, **self.packet.arguments(),
                    prefix=prefix if selected_prefix is None else selected_prefix)

    def test_complete_positive_reconstructs_raw_records_without_execution(self):
        inert_open, inert_resolve = inert_path_guards(replay.ROOT, replay.TRUSTED_READER_SOURCES)
        with mock.patch("subprocess.Popen", side_effect=AssertionError("retained process")), \
             mock.patch("os.system", side_effect=AssertionError("retained shell")), \
             mock.patch("runpy.run_path", side_effect=AssertionError("retained Python")), \
             mock.patch.object(zipfile.ZipFile, "extract", side_effect=AssertionError("extraction")), \
             mock.patch.object(zipfile.ZipFile, "extractall", side_effect=AssertionError("extraction")), \
             mock.patch.object(Path, "open", inert_open), mock.patch.object(Path, "resolve", inert_resolve):
            result, context = self.view_replay()
        self.assertEqual(result["contract_id"], replay.CONTRACT_ID)
        self.assertEqual(result["scope"], replay.SCOPE)
        self.assertEqual(result["counts"], replay.native.COUNTS)
        self.assertEqual(result["commands_checked"], 37)
        self.assertEqual(len(context.process_results), 4)
        self.assertEqual(result["counts"]["launches"], 132)
        self.assertEqual(result["counts"]["checked_words"], 4224)
        self.assertIs(result["counter_qualification_passed"], True)
        self.assertEqual(result["counter_qualification_scope"], "recorded-four-process-preflight-only")
        self.assertEqual(result["native_execution"], "not_run")
        self.assertIs(result["retained_code_executed"], False)
        self.assertIs(result["counter_qualification_admission"]["counter_qualification_passed"], False)
        self.assertEqual(result["counter_population"], {"selectors": 33, "components": 40, "unavailable_selectors": 12})
        self.assertEqual(result["lifetime_premises"], list(replay.contract.PREMISE_IDS))
        for name in replay.contract.FALSE_CLAIMS:
            self.assertIs(result[name], False)
        self.diagnostic_reader.assert_called_once_with(self.packet.proof,
            diagnostic_archive=DIAGNOSTIC_PATH,
            diagnostic_sha256=self.packet.proof["diagnostics"]["archive"]["sha256"])
        self.control_reader.assert_called_once_with(self.packet.proof, archive=CONTROL_PATH,
            sha256=self.packet.proof["controls"]["archive"]["sha256"])

    def test_fixed_helper_inventory_covers_executing_entry_and_all_prerequisites(self):
        self.assertEqual(len(replay.RUNNER_HELPERS), 77)
        self.assertEqual(len(replay.ADMISSION_HELPERS), 79)
        self.assertEqual(tuple(row["path"] for row in replay.admission.reader_sources()), replay.ADMISSION_HELPERS)
        self.assertIn("ci/project/p06_counter_qualification_execute.py", replay.RUNNER_HELPERS)
        self.assertIn("tests/unittest/pending_reads/main.cpp", replay.ADMISSION_HELPERS)
        self.assertIn(replay.native.archive_helpers.ARCHIVE_READER_PATH, replay.ADMISSION_HELPERS)
        trusted = {row["path"] for row in replay.TRUSTED_READER_SOURCES}
        self.assertTrue({replay.PUBLIC_INVENTORY, replay.contract.SOURCE_PROOF_PATH,
            "ci/project/p06_counter_qualification_replay.py"} <= trusted)

    def test_external_proof_report_and_source_pins_are_independent(self):
        for name in ("expected_qualification_sha256", "expected_native_report_sha256",
                     "expected_source_manifest_sha256", "expected_receipt_sha256"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.view_replay(**{name: "0" * 64})
        self.diagnostic_reader.assert_not_called()
        self.control_reader.assert_not_called()

    def test_independent_prerequisite_archive_pins_are_required(self):
        for name in ("diagnostic_sha256", "control_sha256"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.view_replay(**{name: "0" * 64})
        self.diagnostic_reader.assert_not_called()
        self.control_reader.assert_not_called()

    def test_rehashed_proof_and_alternate_retained_path_reject(self):
        for mutation in ("bytes", "path"):
            packet = deepcopy(self.qualified)
            path = replay.PROOF_MEMBER if mutation == "bytes" else "snapshots/qualification.json"
            body = packet.proof_body + b" " if mutation == "bytes" else packet.proof_body
            packet.report["retained_counter_qualification"] = packet.put(path, body)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                packet.reader().run()

    def test_original_false_or_omitted_pass_flag_cannot_qualify(self):
        for missing in (False, True):
            packet = deepcopy(self.qualified)
            if missing:
                del packet.report["counter_qualification_passed"]
            else:
                packet.report["counter_qualification_passed"] = False
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                packet.reader().run()

    def test_rehashed_build_or_process_proof_binding_rejects(self):
        for kind in ("build", "process"):
            packet = deepcopy(self.qualified)
            row = packet.report["variants"][0] if kind == "build" else packet.report["processes"][0]
            binding = json.loads(packet.files[row["binding"]["path"]])
            binding["counter_qualification_sha256"] = "0" * 64
            row["binding"] = packet.put_json(row["binding"]["path"], binding)
            row["build_binding_sha256" if kind == "build" else "execution_binding_sha256"] = replay.native.qualification_id(binding)
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "reconstructed .*binding"):
                packet.reader().run()

    def test_rehashed_report_admission_summary_is_reconstructed(self):
        self.packet.report["counter_qualification_admission"] = deepcopy(self.packet.counter_admission)
        self.packet.report["counter_qualification_admission"]["source_projection"]["source_files"] = 68
        with self.assertRaisesRegex(ValueError, "reconstructed counter qualification admission"):
            self.packet.reader().run()

    def test_actual_retained_measurement_sources_are_checked(self):
        name = "sim/simx/core.cpp"
        body = self.packet.files["artifacts/source/" + name] + b"\n// altered synthetic source\n"
        self.packet.put("artifacts/source/" + name, body)
        self.packet.source["files"] = [descriptor(name, body) if row["path"] == name else row
                                       for row in self.packet.source["files"]]
        self.packet.report["retained_sources"] = [dict(row, path="artifacts/source/" + row["path"])
                                                   for row in self.packet.source["files"]]
        for which in ("before", "after"):
            self.packet.report["source_" + which] = self.packet.put_json(
                "snapshots/source-" + which + ".json", self.packet.source)
        self.packet.source_pin = self.packet.report["source_before"]["sha256"]
        with self.assertRaisesRegex(ValueError, "qualification source projection"):
            self.packet.reader().run()

    def test_fresh_dependency_projection_checks_git_blob_identity(self):
        reader = self.packet.reader()
        component = next(row for row in reader.dependency_document["source_manifest"]["sources"]
                         if row["name"] == "ramulator")
        selected = self.packet.proof["dependency_sources"][0]["path"]
        next(row for row in component["files"] if row["path"] == selected)["oid"] = "0" * 40
        with self.assertRaisesRegex(ValueError, "qualified dependency Git blob"):
            reader.run()

    def test_missing_admission_helper_is_not_hidden_by_loaded_helper_inventory(self):
        name = "tests/unittest/pending_reads/main.cpp"
        self.packet.source["files"] = [row for row in self.packet.source["files"] if row["path"] != name]
        self.packet.report["retained_sources"] = [dict(row, path="artifacts/source/" + row["path"])
                                                   for row in self.packet.source["files"]]
        for which in ("before", "after"):
            self.packet.report["source_" + which] = self.packet.put_json(
                "snapshots/source-" + which + ".json", self.packet.source)
        self.packet.source_pin = self.packet.report["source_before"]["sha256"]
        with self.assertRaisesRegex(ValueError, "qualification admission helper"):
            self.packet.reader().run()

    def test_summary_is_not_accepted_when_either_independent_replay_fails(self):
        for boundary in (self.diagnostic_reader, self.control_reader):
            boundary.side_effect = ValueError("independent original rejected")
            with self.subTest(boundary=boundary), self.assertRaisesRegex(ValueError, "independent original rejected"):
                self.packet.reader().run()
            boundary.side_effect = None

    def test_all_six_final_stability_digests_are_required(self):
        for name in self.packet.counter_stability:
            packet = deepcopy(self.qualified)
            packet.report["counter_qualification_admission_after"] = dict(packet.counter_stability, **{name: "0" * 64})
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "final stability"):
                packet.reader().run()

    def test_last_stability_row_fails_after_all_four_transcripts(self):
        for missing in (False, True):
            packet = deepcopy(self.qualified)
            row = packet.report["stability_checks"][-1]
            if missing:
                del row["counter_qualification_admission"]
            else:
                row["counter_qualification_admission"] = dict(packet.counter_stability, proof_sha256="0" * 64)
            reader = packet.reader()
            with self.subTest(missing=missing), self.assertRaisesRegex(ValueError, "stability"):
                reader.run()
            self.assertEqual(len(reader.process_results), 4)

    def test_trusted_reader_change_at_end_rejects_public_result(self):
        changed = deepcopy(replay.TRUSTED_READER_SOURCES)
        changed[-1]["sha256"] = "0" * 64
        with mock.patch.object(replay, "_reader_sources", side_effect=[replay.TRUSTED_READER_SOURCES, changed]), \
             self.assertRaisesRegex(ValueError, "trusted qualification reader changed during review"):
            self.view_replay()

    def test_old_reader_cannot_autodetect_or_upgrade_the_new_route(self):
        with self.assertRaisesRegex(ValueError, "missing or unknown fields"):
            SyntheticNativePacket.reader(self.packet).run()
        original = deepcopy(self.original)
        qualified = self.packet.reader()
        qualified.report = original.report
        with self.assertRaisesRegex(ValueError, "missing or unknown fields"):
            qualified.run()
        checked = {"retained_dependency_verification": self.packet.dependency_verification}
        with mock.patch.object(replay.native.dependency_replay, "verify_view", return_value=checked), \
             self.assertRaisesRegex(ValueError, "missing or unknown fields"):
            replay.native.verify_view(MemoryView(self.packet.files, self.packet.api),
                MemoryView({"report.json": self.packet.dependency_body}, self.packet.api), self.packet.api,
                **{key: value for key, value in self.packet.arguments().items() if key in (
                    "expected_revision", "expected_receipt_sha256", "expected_native_report_sha256",
                    "expected_source_manifest_sha256")})

    def test_unaccounted_retained_member_rejects_after_transcripts(self):
        self.packet.put("snapshots/unreviewed.json", b"{}\n")
        reader = self.packet.reader()
        with self.assertRaisesRegex(ValueError, "complete semantically bound retained inventory"):
            reader.run()
        self.assertEqual(len(reader.process_results), 4)

    def test_local_archive_has_exact_two_roots_and_no_hosted_envelope(self):
        for prefix in ("", "selected-local"):
            with self.subTest(prefix=prefix):
                result = self.zip_replay(prefix=prefix)
                self.assertIs(result["counter_qualification_passed"], True)
                self.assertEqual(result["execution_origin"], "local")
                self.assertIs(result["origin_authenticated"], False)
                self.assertEqual(result["prefix"], prefix)

    def test_foreign_members_outside_and_inside_prefix_reject(self):
        for prefix, extra in (("", "job.json"), ("selected-local", "unselected/report.json"),
                              ("selected-local", "selected-local/workflow.yml")):
            with self.subTest(extra=extra), self.assertRaisesRegex(ValueError, "complete local qualification archive roots"):
                self.zip_replay(prefix=prefix, extra={extra: b"{}\n"})
        self.diagnostic_reader.assert_not_called()

    def test_wrong_local_archive_pin_and_wrong_prefix_reject(self):
        with self.assertRaises(ValueError):
            self.zip_replay(wrong_pin=True)
        with self.assertRaises(ValueError):
            self.zip_replay(prefix="selected-local", selected_prefix="other")
        self.diagnostic_reader.assert_not_called()

    def test_invalid_prefix_and_missing_external_selection_fail_closed(self):
        for prefix in ("../outside", "/absolute", "selected-local/", "a//b"):
            with self.subTest(prefix=prefix), self.assertRaises(ValueError):
                replay.replay_archive(Path("/unopened/original.zip"), "1" * 64,
                    **self.packet.arguments(), prefix=prefix)
        with self.assertRaises(TypeError):
            replay.verify_view(MemoryView(self.packet.files, self.packet.api),
                MemoryView({"report.json": self.packet.dependency_body}, self.packet.api), self.packet.api,
                expected_revision=self.packet.revision)


if __name__ == "__main__":
    unittest.main()
