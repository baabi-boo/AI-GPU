# SPDX-License-Identifier: Apache-2.0
"""Independent backend closure and coherently rehashed build mutations."""

from copy import deepcopy
from pathlib import Path
import re
import tempfile
import unittest

from p06_managed_preflight_backend_build import RECIPE_SHA256, validate_backend_build
from p06_managed_preflight_replay_test_support import (
    Packet, PREFIX, REPORT, descriptor, encoded, replay,
)
from p06_replay import ReplayError


BUILD_IDS = {
    "simx-fp16": "132ed4807c345b17e3f8db1236f1c9566193bd0c76491999f70a318398d81782",
    "simx-bf16": "a245d97ae7455eaf7568bbbab1b510211ddcbd523eb2470f4c4178a5fa978d57",
}


class BackendEnvelopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.variants = {}
        with Packet() as packet:
            report = packet.report
            tools = packet.json(report["tools_before"]["path"])
            source_files = [row["path"] for row in packet.json(report["source_before"]["path"])["files"]]
            cls.recipes = {name: packet[PREFIX + "artifacts/source/" + name] for name in RECIPE_SHA256}
            for variant in report["variants"]:
                command = next(row for row in report["commands"]
                               if row["id"] == variant["backend_build_command"])
                prefix = PREFIX + "artifacts/" + variant["id"] + "/frozen/sw/runtime/"
                cls.variants[variant["format"]] = {
                    "text": packet[PREFIX + command["log"]].decode("utf-8"),
                    "original": variant["model_build_records"],
                    "arguments": {
                        "runtime": packet[prefix + "simx_rt_config.stamp"].decode("utf-8"),
                        "backend": packet[prefix + "simx_config.stamp"].decode("utf-8"),
                        "backend_linker": packet[prefix + "preflight_backend_link.stamp"].decode("utf-8"),
                        "source": report["paths"]["source"], "build": variant["build_dir"],
                        "compiler": tools["g++"]["path"], "make": tools["make"]["path"],
                        "fmt": variant["format"], "source_files": source_files,
                    },
                }

    def validate(self, text, fmt="fp16", recipes=None):
        return validate_backend_build(text, source_body=(self.recipes if recipes is None else recipes).__getitem__,
                                      **self.variants[fmt]["arguments"])

    def test_original_formats_keep_historical_model_records_and_complete_counts(self):
        before = deepcopy(self.variants)
        for fmt, variant in self.variants.items():
            with self.subTest(fmt=fmt):
                receipt = self.validate(variant["text"], fmt)
                self.assertEqual(receipt["model_build_records"], variant["original"])
                self.assertEqual(receipt["command_count"], 46)
                self.assertEqual(receipt["command_counts"], {
                    "model_compile": 43, "model_link": 1, "backend_link": 1, "recursive_make": 1})
                self.assertEqual(receipt["command_order"][0], "nested-make")
                self.assertEqual(receipt["command_order"][-2:], ["model-link", "backend-link"])
                self.assertEqual(receipt["recipe_sha256"], RECIPE_SHA256)
        self.assertEqual(self.variants, before)

    def test_parallel_model_compiles_can_have_a_different_valid_order(self):
        for fmt, variant in self.variants.items():
            with self.subTest(fmt=fmt):
                lines = variant["text"].splitlines()
                changed = [lines[0], *reversed(lines[1:-2]), *lines[-2:]]
                receipt = self.validate("\n".join(changed) + "\n", fmt)
                self.assertEqual(receipt["model_build_records"], variant["original"])
                self.assertNotEqual(receipt["normalized_commands_sha256"],
                                    self.validate(variant["text"], fmt)["normalized_commands_sha256"])

    def test_nested_make_shell_assignment_must_remain_an_assignment(self):
        lines = self.variants["fp16"]["text"].splitlines()
        assignment, tail = lines[0].split(" ", 1)
        for replacement in ("'" + assignment + "' " + tail,
                            assignment.replace("=", "\\=", 1) + " " + tail,
                            "# " + lines[0], "/usr/bin/true"):
            with self.subTest(replacement=replacement):
                with self.assertRaisesRegex(ValueError, "unsupported command at record 1"):
                    self.validate("\n".join([replacement, *lines[1:]]) + "\n")

    def test_each_selected_backend_recipe_is_bound_before_log_acceptance(self):
        for name in RECIPE_SHA256:
            with self.subTest(recipe=name):
                recipes = dict(self.recipes)
                recipes[name] += b"\n# changed recipe\n"
                with self.assertRaisesRegex(ValueError, re.escape("reviewed source: " + name)):
                    self.validate(self.variants["fp16"]["text"], recipes=recipes)


class ManagedBuildReplayTests(unittest.TestCase):
    def replay_packet(self, packet):
        with tempfile.TemporaryDirectory(prefix="p06-build-review-") as directory:
            path = Path(directory) / "mutation.zip"
            return replay(path, packet.write(path))

    def rejected_log(self, change, reason):
        with Packet() as packet:
            packet.replace_log("simx-fp16-backend",
                lambda body: ("\n".join(change(body.decode("utf-8").splitlines())) + "\n").encode("utf-8"))
            with self.assertRaisesRegex(ValueError, re.escape(reason)):
                self.replay_packet(packet)

    def replace_build_copies(self, packet, relative, change):
        variant = packet.report["variants"][0]
        prefix = "artifacts/" + variant["id"] + "/"
        body = change(packet[PREFIX + prefix + "frozen/" + relative])
        for stage in variant["retained_builds"]:
            name = prefix + stage["stage"] + "/" + relative
            if PREFIX + name in packet:
                packet.replace_retained(name, body)
        identity = descriptor(relative, body)
        report = packet.report
        variant = report["variants"][0]
        for key in ("artifacts_before", "artifacts_after", "generated_identity"):
            for row in variant[key]:
                if row["path"] == relative:
                    row.update(identity)
        packet[REPORT] = encoded(report)
        binding = packet.json(variant["binding"]["path"])
        for key in ("artifacts", "generated_identity"):
            for row in binding[key]:
                if row["path"] == relative:
                    row.update(identity)
        packet.replace_retained(variant["binding"]["path"], encoded(binding))
        packet.rehash_bindings()

    def test_extra_command_and_same_count_unknown_command_reject(self):
        for change, reason in (
            (lambda lines: [*lines, "touch /tmp/unrelated-side-effect"], "exactly 46 commands"),
            (lambda lines: ["touch /tmp/unrelated-side-effect", *lines[1:]], "unsupported command at record 1"),
        ):
            with self.subTest(reason=reason):
                self.rejected_log(change, reason)

    def test_missing_and_duplicate_recursive_make_reject(self):
        for change in (lambda lines: lines[1:], lambda lines: [lines[0], *lines]):
            with self.subTest(change=change):
                self.rejected_log(change, "exactly 46 commands")

    def test_compile_cannot_precede_recursive_make(self):
        self.rejected_log(lambda lines: [lines[1], lines[0], *lines[2:]],
                          "backend build command precedes its prerequisites: model:")

    def test_model_link_cannot_precede_its_object_compiles(self):
        self.rejected_log(lambda lines: [lines[0], lines[-2], *lines[1:-2], lines[-1]],
                          "backend build command precedes its prerequisites: model-link")

    def test_backend_link_cannot_precede_its_model_library(self):
        self.rejected_log(lambda lines: [*lines[:-2], lines[-1], lines[-2]],
                          "backend build command precedes its prerequisites: backend-link")

    def test_valid_parallel_compile_permutations_keep_both_build_bindings(self):
        with Packet() as packet:
            for variant in packet.report["variants"]:
                def permute(body):
                    lines = body.decode("utf-8").splitlines()
                    return ("\n".join([lines[0], *reversed(lines[1:-2]), *lines[-2:]]) + "\n").encode("utf-8")
                packet.replace_log(variant["backend_build_command"], permute)
            report = packet.report
            self.assertEqual({row["id"]: row["build_binding_sha256"] for row in report["variants"]}, BUILD_IDS)
            result = self.replay_packet(packet)
            self.assertEqual(result["outcome"], "pass")
            self.assertEqual(result["counts"]["launches"], 132)
            self.assertEqual(result["counts"]["checked_words"], 4224)
            self.assertEqual(result["retained_payload_files_checked"], 17)
            self.assertEqual(set(result["backend_builds"]), set(BUILD_IDS))
            for variant in report["variants"]:
                receipt = result["backend_builds"][variant["id"]]
                self.assertEqual(receipt["command_count"], 46)
                self.assertEqual(receipt["model_build_records"], variant["model_build_records"])

    def test_original_stage_and_artifact_populations_are_closed(self):
        with Packet() as packet:
            for variant in packet.report["variants"]:
                self.assertEqual(len(variant["artifacts_before"]), 75)
                self.assertEqual([(stage["stage"], len(stage["files"])) for stage in variant["retained_builds"]],
                                 [("configured", 20), ("backend", 24), ("frozen", 25)])
                self.assertEqual(len(variant["retained_binary_payloads"]), 7)
            retained = next(row for row in packet.report["variants"][0]["retained_builds"][0]["files"]
                            if row["path"].endswith("/config.mk"))
            packet.replace_retained(retained["path"], packet[PREFIX + retained["path"]] + b"\n# divergence\n")
            with self.assertRaisesRegex(ReplayError, "retained build identity"):
                self.replay_packet(packet)

    def test_coherently_rehashed_generated_configuration_cannot_drift(self):
        for relative, change, reason in (
            (".config.stamp", lambda body: body.replace(b"OSVERSION=ubuntu/focal", b"OSVERSION=ubuntu/jammy"),
             "complete configure stamp"),
            ("config.mk", lambda body: body + b"\nCXX := /tmp/foreign-compiler\n",
             "complete generated configuration"),
            ("sim/rtlsim/verilator.vlt", lambda body: body + b"\n// additional configuration\n",
             "generated Verilator configuration"),
        ):
            with self.subTest(relative=relative), Packet() as packet:
                self.replace_build_copies(packet, relative, change)
                with self.assertRaisesRegex(ReplayError, reason):
                    self.replay_packet(packet)

    def test_coherently_rehashed_copied_backend_recipe_cannot_drift(self):
        with Packet() as packet:
            relative = "tests/regression/ai_counter_preflight/backend.mk"
            self.replace_build_copies(packet, relative, lambda body: body + b"\n.PHONY: unreviewed\n")
            with self.assertRaisesRegex(ReplayError, "copied source " + re.escape(relative)):
                self.replay_packet(packet)

    def test_rehashed_binary_payload_must_match_its_frozen_artifact(self):
        with Packet() as packet:
            payload = next(row for row in packet.report["variants"][0]["retained_binary_payloads"]
                           if row["path"].endswith("/kernel.vxbin"))
            body = packet[PREFIX + payload["path"]]
            packet.replace_retained(payload["path"], bytes([body[0] ^ 1]) + body[1:])
            with self.assertRaisesRegex(ReplayError, "retained binary identity"):
                self.replay_packet(packet)

    def test_rehashed_common_build_binding_cannot_change_worker_contract(self):
        with Packet() as packet:
            binding = packet.report["variants"][0]["binding"]["path"]
            packet.edit_json(binding, lambda row: row.update(simulation_workers=2))
            packet.rehash_bindings()
            with self.assertRaisesRegex(ReplayError, "reconstructed common build binding.simulation_workers"):
                self.replay_packet(packet)


if __name__ == "__main__":
    unittest.main()
