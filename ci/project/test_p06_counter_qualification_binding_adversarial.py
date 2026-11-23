# SPDX-License-Identifier: Apache-2.0
"""Rehashed binding attacks against the public qualified retained reader.

Complete native grammar is synthetic. Only the dependency and historical
prerequisite verifier boundaries are mocked; binding, transcript, source,
inventory, stability, and externally selected report checks remain real.
"""

from contextlib import ExitStack
from copy import deepcopy
import json
import unittest
from unittest import mock

import p06_counter_qualification_replay as replay
import p06_native_lifetime_test_fixture as lifetime_fixture
from p06_counter_qualification_test_fixture import SyntheticQualificationPacket
from test_p06_dependency_native_replay import MemoryView, descriptor, digest


class QualificationBindingAdversarialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = SyntheticQualificationPacket()

    def setUp(self):
        self.packet = deepcopy(self.original)
        self.patches = ExitStack()
        self.addCleanup(self.patches.close)
        self.diagnostics = self.patches.enter_context(mock.patch.object(
            replay.prerequisites, "verify_prerequisites", return_value=self.packet.diagnostics))
        self.controls = self.patches.enter_context(mock.patch.object(
            replay.prerequisites, "verify_control_prerequisite", return_value=self.packet.controls))

    def rewrite_bindings(self, *, change_build=None, change_process=None):
        """Repair every downstream binding and raw echo, including observations."""
        packet = self.packet
        commands = {row["id"]: row for row in packet.report["commands"]}
        for variant in packet.report["variants"]:
            binding = json.loads(packet.files[variant["binding"]["path"]])
            if change_build is not None:
                change_build(binding)
            build_id = replay.native.qualification_id(binding)
            variant["binding"] = packet.put_json(variant["binding"]["path"], binding)
            variant["build_binding_sha256"] = build_id
            for row in packet.report["processes"]:
                if row["format"] != variant["format"]:
                    continue
                process = json.loads(packet.files[row["binding"]["path"]])
                process.update(build=binding, build_binding_sha256=build_id)
                if change_process is not None:
                    change_process(row, process)
                binding_id = replay.native.qualification_id(process)
                row.update(execution_binding_sha256=binding_id, build_binding_sha256=build_id,
                    binding=packet.put_json(row["binding"]["path"], process))
                raw = lifetime_fixture.raw_records(row["format"], row["policy"], binding_id=binding_id)
                raw[3]["loaded_libraries"] = [{"name": name, "path": path}
                    for name, path in sorted(variant["expected_loaded_libraries"].items())]
                text = lifetime_fixture.render_log(*raw[1:])
                observed = replay.native.records.verify_output(text, contract=packet.contract, case=raw[0],
                    fmt=row["format"], policy=row["policy"], binding_id=binding_id,
                    sample_id=row["sample_id"], process_id=row["id"],
                    expected_libraries=variant["expected_loaded_libraries"])
                row["observation"] = observed
                row["retained_observation"] = packet.put_json(row["retained_observation"]["path"], observed)
                command = commands[row["id"]]
                command["argv"][command["argv"].index("--qualification-id") + 1] = binding_id
                packet.log(command, text)
        packet.report["raw_logs"] = [descriptor(row["log"], packet.files[row["log"]])
                                      for row in packet.report["commands"]]
        packet.finish()

    def public_replay(self):
        self.packet.finish()
        args = self.packet.arguments()
        self.assertNotEqual(args["expected_native_report_sha256"],
                            digest(self.original.files["report.json"]))
        self.assertEqual(args["expected_native_report_sha256"], digest(self.packet.files["report.json"]))
        checked = {"retained_dependency_verification": self.packet.dependency_verification}
        with mock.patch.object(replay.native.dependency_replay, "verify_view", return_value=checked) as dependency:
            try:
                return replay.verify_view(MemoryView(self.packet.files, self.packet.api),
                    MemoryView({"report.json": self.packet.dependency_body}, self.packet.api),
                    self.packet.api, **args)
            finally:
                dependency.assert_called_once()

    def test_cross_policy_process_binding_transplant_rejects_after_all_echoes_repaired(self):
        target, donor = self.packet.report["processes"][:2]
        self.assertEqual(target["format"], donor["format"])
        self.assertNotEqual(target["policy"], donor["policy"])
        donor_binding = json.loads(self.packet.files[donor["binding"]["path"]])
        original_binding = target["execution_binding_sha256"]

        def transplant(row, binding):
            if row["id"] == target["id"]:
                binding["process"] = deepcopy(donor_binding["process"])

        self.rewrite_bindings(change_process=transplant)
        self.assertNotEqual(target["execution_binding_sha256"], original_binding)
        self.assertEqual(target["execution_binding_sha256"], donor["execution_binding_sha256"])
        with self.assertRaisesRegex(ValueError, "reconstructed process binding"):
            self.public_replay()

    def test_control_summary_transplant_rejects_after_all_build_and_process_rebindings(self):
        original_ids = [row["execution_binding_sha256"] for row in self.packet.report["processes"]]
        replaced = deepcopy(self.packet.report["counter_qualification_admission"])
        replaced["controls"]["positive_pending_contexts"][0]["gp"] = 17
        self.packet.report["counter_qualification_admission"] = replaced

        def transplant(binding):
            binding["counter_qualification_admission"] = deepcopy(replaced)

        self.rewrite_bindings(change_build=transplant)
        self.assertTrue(all(before != row["execution_binding_sha256"]
            for before, row in zip(original_ids, self.packet.report["processes"])))
        with self.assertRaisesRegex(ValueError, "reconstructed counter qualification admission"):
            self.public_replay()
        self.diagnostics.assert_called_once()
        self.controls.assert_called_once()

    def test_interior_stability_drift_rejects_even_when_endpoints_and_final_row_match(self):
        checks = self.packet.report["stability_checks"]
        selected = checks[len(checks) // 2]
        selected["counter_qualification_admission"] = dict(self.packet.counter_stability,
            control_archive_sha256="0" * 64)
        self.assertEqual(self.packet.report["counter_qualification_admission_before"],
                         self.packet.report["counter_qualification_admission_after"])
        self.assertEqual(checks[-1]["counter_qualification_admission"], self.packet.counter_stability)
        with mock.patch.object(replay.native.records, "verify_output",
                wraps=replay.native.records.verify_output) as transcripts:
            with self.assertRaisesRegex(ValueError, "route stability observation counter_qualification_admission"):
                self.public_replay()
        self.assertEqual(transcripts.call_count, 4)

    def test_equal_count_loaded_helper_substitution_rejects_after_transitive_rebinding(self):
        removed = "ci/project/p06_counter_qualification_execute.py"
        replacement = "ci/gen_config.py"
        helpers = self.packet.report["loaded_helpers"]
        self.assertIn(removed, {row["path"] for row in helpers})
        self.assertNotIn(replacement, {row["path"] for row in helpers})
        altered = [row for row in helpers if row["path"] != removed]
        altered.append(deepcopy(self.packet.sources[replacement]))
        self.packet.report["loaded_helpers"] = sorted(altered, key=lambda row: row["path"])
        self.assertEqual(len(helpers), len(self.packet.report["loaded_helpers"]))

        def substitute(binding):
            binding["loaded_helpers"] = deepcopy(self.packet.report["loaded_helpers"])

        self.rewrite_bindings(change_build=substitute)
        with self.assertRaisesRegex(ValueError, "executing helpers paths"):
            self.public_replay()
        self.diagnostics.assert_not_called()
        self.controls.assert_not_called()


if __name__ == "__main__":
    unittest.main()
