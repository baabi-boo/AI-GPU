# SPDX-License-Identifier: Apache-2.0
"""Complete invented warm packets exercise real replay, not execution evidence.

Only the separately tested dependency and original prerequisite archive readers
are replaced by explicit synthetic seams. Native source, build, raw record,
lifetime, chronology, member inventory, and arithmetic checks remain real.
"""

from contextlib import ExitStack
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

import p06_qualified_warm_replay as replay
from p06_counter_qualification_test_fixture import CONTROL_PATH, DIAGNOSTIC_PATH
from p06_qualified_warm_test_fixture import SyntheticQualifiedWarmPacket
from test_p06_dependency_native_replay import MemoryView, descriptor, digest, inert_path_guards
from test_p06_qualified_warm_records import render_log


class CompleteQualifiedWarmReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.example = SyntheticQualifiedWarmPacket()

    def setUp(self):
        self.packet = deepcopy(self.example)
        self.patches = ExitStack()
        self.addCleanup(self.patches.close)
        self.diagnostics = self.patches.enter_context(mock.patch.object(
            replay.prerequisites, "verify_prerequisites", return_value=self.packet.diagnostics))
        self.controls = self.patches.enter_context(mock.patch.object(
            replay.prerequisites, "verify_control_prerequisite", return_value=self.packet.controls))

    def view_replay(self):
        self.packet.finish()
        checked = {"retained_dependency_verification": self.packet.dependency_verification}
        with mock.patch.object(replay.native.dependency_replay, "verify_view", return_value=checked) as dependency:
            result = replay.verify_view(MemoryView(self.packet.files, self.packet.api),
                MemoryView({"report.json": self.packet.dependency_body}, self.packet.api),
                self.packet.api, **self.packet.arguments())
        dependency.assert_called_once()
        return result

    def rewrite_source(self, name, body):
        self.packet.put("artifacts/source/" + name, body)
        self.packet.source["files"] = [descriptor(name, body) if row["path"] == name else row
                                        for row in self.packet.source["files"]]
        self.packet.report["retained_sources"] = [dict(row, path="artifacts/source/" + row["path"])
                                                   for row in self.packet.source["files"]]
        for which in ("before", "after"):
            self.packet.report["source_" + which] = self.packet.put_json(
                "snapshots/source-" + which + ".json", self.packet.source)
        self.packet.source_pin = self.packet.report["source_before"]["sha256"]
        self.packet.finish()

    def raw_log(self, index):
        observed = self.packet.report["processes"][index]["observation"]
        return [deepcopy(observed["warm"]["operations"]), deepcopy(observed["warm"]["summary"]),
                deepcopy(observed["witness"]), deepcopy(observed["lifetime"])]

    def test_complete_public_replay_and_analysis_without_execution(self):
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
        self.assertEqual(result["commands_checked"], 57)
        self.assertEqual(result["counts"], replay.contract.COMPLETE_COUNTS)
        self.assertEqual(result["counts"]["processes"], 24)
        self.assertEqual(result["counts"]["launches"], 792)
        self.assertEqual(result["counts"]["checked_words"], 25344)
        self.assertEqual(len(context.process_results), 24)
        self.assertEqual([row["id"] for row in context.process_results],
                         [row["id"] for row in self.packet.plan])
        for fmt in replay.native.manifest.FORMATS:
            ids = {row["build_binding_sha256"] for row in context.process_results if row["format"] == fmt}
            self.assertEqual(len(ids), 1)
        self.assertIs(result["qualified_warm_passed"], True)
        self.assertEqual(result["native_execution"], "not_run")
        self.assertIs(result["retained_code_executed"], False)
        self.assertIs(result["counter_qualification_admission"]["qualified_warm_passed"], False)
        for name in replay.contract.FALSE_CLAIMS:
            self.assertIs(result[name], False)
        analysis = result["analysis"]
        self.assertEqual(len(analysis["batches"]), 24)
        self.assertEqual(analysis["excluded_prime_operations"], 24)
        self.assertEqual(len(analysis["excluded_warmup_processes"]), 4)
        self.assertEqual(sum(row["included_in_conditional_criteria"] for row in analysis["batches"]), 20)
        self.assertIs(analysis["performance_acceptance"], False)
        self.assertIs(analysis["phase_acceptance"], False)
        self.assertIs(analysis["acceptance_claimed"], False)
        self.diagnostics.assert_called_once_with(self.packet.original_proof,
            diagnostic_archive=DIAGNOSTIC_PATH,
            diagnostic_sha256=self.packet.original_proof["diagnostics"]["archive"]["sha256"])
        self.controls.assert_called_once_with(self.packet.original_proof, archive=CONTROL_PATH,
            sha256=self.packet.original_proof["controls"]["archive"]["sha256"])

    def test_complete_zip_envelope_has_only_two_exact_roots(self):
        self.packet.finish()
        prefix = "retained-attempt"
        files = self.packet.local_files(prefix)
        checked = {"retained_dependency_verification": self.packet.dependency_verification}
        with tempfile.TemporaryDirectory(prefix="p06-qualified-warm-replay-") as directory:
            path = Path(directory) / "synthetic.zip"
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
                for name, body in files.items():
                    archive.writestr(name, body)
            with mock.patch.object(replay.native.dependency_replay, "verify_view", return_value=checked):
                result = replay.replay_archive(path, digest(path.read_bytes()),
                    prefix=prefix, **self.packet.arguments())
            self.assertIs(result["qualified_warm_passed"], True)
            self.assertEqual(result["counts"], replay.contract.COMPLETE_COUNTS)
            self.assertEqual(result["execution_origin"], "local")
            self.assertIs(result["origin_authenticated"], False)
            with zipfile.ZipFile(path, "a") as archive:
                archive.writestr(prefix + "/unbound.json", "{}\n")
            with self.assertRaisesRegex(ValueError, "complete local qualification archive roots"):
                replay.replay_archive(path, digest(path.read_bytes()),
                    prefix=prefix, **self.packet.arguments())

    def test_missing_reordered_and_duplicate_processes_reject_with_rehashed_report(self):
        for change in ("missing", "reordered", "duplicate"):
            self.packet = deepcopy(self.example)
            processes = self.packet.report["processes"]
            if change == "missing":
                processes.pop()
            elif change == "reordered":
                processes[0], processes[1] = processes[1], processes[0]
            else:
                processes[1] = deepcopy(processes[0])
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "24 qualified warm|process\\."):
                self.packet.reader().run()

    def test_missing_and_reordered_raw_operations_reject_with_repaired_log_hashes(self):
        for change in ("missing", "reordered"):
            self.packet = deepcopy(self.example)
            raw = self.raw_log(0)
            if change == "missing":
                raw[0].pop(16)
            else:
                raw[0][16], raw[0][17] = raw[0][17], raw[0][16]
            self.packet.replace_log(0, render_log(*raw))
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.packet.reader().run()

    def test_cross_pair_transcript_substitution_rejects_with_repaired_outer_hashes(self):
        processes = self.packet.report["processes"]
        source = next(row for row in processes if row["format"] == "fp16"
                      and row["pair_index"] == 1 and row["policy"] == "per_operation")
        index = next(i for i, row in enumerate(processes) if row["format"] == "fp16"
                     and row["pair_index"] == 2 and row["policy"] == "per_operation")
        self.packet.replace_log(index, self.packet.files[source["log"]].decode("utf-8"))
        reader = self.packet.reader()
        with self.assertRaisesRegex(ValueError, "process_id|sample_id|pair_index|execution_binding"):
            reader.run()
        self.assertEqual(len(reader.process_results), index)

    def test_source_extension_cannot_be_rebound_to_the_historical_caller(self):
        name = "tests/regression/ai_counter_preflight/main.cpp"
        historical = (replay.ROOT / "ci/project/fixtures/p06_counter_preflight_main_v1.cpp").read_bytes()
        self.assertNotEqual(digest(historical), self.packet.sources[name]["sha256"])
        self.rewrite_source(name, historical)
        with self.assertRaisesRegex(ValueError, "qualified warm source projection"):
            self.packet.reader().run()

    def test_interior_lifetime_failure_rejects_despite_repaired_log_inventory(self):
        raw = self.raw_log(0)
        raw[3]["runs"][16]["after"]["pending_reads"] = 1
        self.packet.replace_log(0, render_log(*raw))
        reader = self.packet.reader()
        with self.assertRaisesRegex(ValueError, "pending"):
            reader.run()
        self.assertEqual(reader.process_results, [])

    def test_rehashed_process_cannot_select_a_different_common_binary(self):
        row = self.packet.report["processes"][1]
        binding = json.loads(self.packet.files[row["binding"]["path"]])
        binary = next(artifact for artifact in binding["build"]["artifacts"]
                      if artifact["path"].endswith("/ai_counter_preflight"))
        binary["sha256"] = "0" * 64
        alternative = replay.native.qualification_id(binding["build"])
        binding["build_binding_sha256"] = alternative
        row["build_binding_sha256"] = alternative
        row["execution_binding_sha256"] = replay.native.qualification_id(binding)
        row["binding"] = self.packet.put_json(row["binding"]["path"], binding)
        reader = self.packet.reader()
        with self.assertRaisesRegex(ValueError, "reconstructed process binding"):
            reader.run()
        self.assertEqual(len(reader.process_results), 1)

    def test_final_input_stability_drift_rejects_after_all_24_transcripts(self):
        row = self.packet.report["stability_checks"][-1]
        row["counter_qualification_admission"] = dict(self.packet.counter_stability,
            prerequisite_inputs_sha256="0" * 64)
        reader = self.packet.reader()
        with self.assertRaisesRegex(ValueError, "route stability observation"):
            reader.run()
        self.assertEqual(len(reader.process_results), 24)

    def test_rehashed_unbound_native_member_is_rejected(self):
        self.packet.put("artifacts/unbound.bin", b"unbound synthetic payload\n")
        reader = self.packet.reader()
        with self.assertRaisesRegex(ValueError, "complete semantically bound retained inventory"):
            reader.run()
        self.assertEqual(len(reader.process_results), 24)

    def test_analysis_cannot_run_before_the_native_packet_is_complete(self):
        self.packet.report["processes"].pop()
        with mock.patch.object(replay.analysis, "analyze_population",
                               wraps=replay.analysis.analyze_population) as arithmetic:
            with self.assertRaisesRegex(ValueError, "24 qualified warm"):
                self.view_replay()
        arithmetic.assert_not_called()


if __name__ == "__main__":
    unittest.main()
