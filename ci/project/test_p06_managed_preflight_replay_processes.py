# SPDX-License-Identifier: Apache-2.0
"""Rehashed archive controls for managed process, counter, and loader semantics."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import tempfile
import unittest

import p06_managed_preflight_contract as contract
import p06_managed_preflight_replay_test_support as fixture


OPERATION = b"P06_WARM_OPERATION "
SUMMARY = b"P06_WARM_SUMMARY "
WITNESS = contract.WITNESS_PREFIX.encode("utf-8")


class ManagedPreflightReplayProcessTests(unittest.TestCase):
    def _replace_process_log(self, packet, index, body, observation):
        process = packet.report["processes"][index]
        warm, separator, last = body[:-1].rpartition(b"\n")
        self.assertTrue(body.endswith(b"\n") and separator and last.startswith(WITNESS))
        self.assertTrue((warm + separator).endswith(b"PASSED!\n"))
        observation["warm"]["raw_log_sha256"] = hashlib.sha256(warm + separator).hexdigest()
        packet.replace_log(process["command_id"], lambda old: body)
        packet.edit_report(lambda report: report["processes"][index].update(observation=deepcopy(observation)))
        packet.replace_retained(process["retained_observation"]["path"], fixture.encoded(observation))

        current = packet.report["processes"][index]
        self.assertEqual(packet.json(current["retained_observation"]["path"]), current["observation"])
        command = next(row for row in packet.report["commands"] if row["id"] == process["command_id"])
        self.assertEqual(command["log_sha256"], hashlib.sha256(body).hexdigest())
        self.assertEqual(command["log_size_bytes"], len(body))
        self.assertEqual(current["observation"]["warm"]["raw_log_sha256"],
                         hashlib.sha256(warm + separator).hexdigest())

    def _witness(self, packet, change, *, index=0):
        process = packet.report["processes"][index]
        original = packet[fixture.PREFIX + process["log"]]
        warm, separator, last = original[:-1].rpartition(b"\n")
        self.assertTrue(last.startswith(WITNESS))
        value = json.loads(last[len(WITNESS):])
        change(value)
        observation = deepcopy(process["observation"])
        observation["witness"] = value
        body = warm + separator + WITNESS + (json.dumps(value, sort_keys=True) + "\n").encode()
        self._replace_process_log(packet, index, body, observation)

    def _operation(self, packet, change, *, index=0, operation=0):
        process = packet.report["processes"][index]
        lines = packet[fixture.PREFIX + process["log"]].splitlines(keepends=True)
        locations = [number for number, line in enumerate(lines) if line.startswith(OPERATION)]
        self.assertEqual(len(locations), 33)
        location = locations[operation]
        value = json.loads(lines[location][len(OPERATION):])
        change(value)
        lines[location] = OPERATION + fixture.encoded(value)
        observation = deepcopy(process["observation"])
        observation["warm"]["operations"][operation] = value
        self._replace_process_log(packet, index, b"".join(lines), observation)

    def _summary(self, packet, change, *, index=0):
        process = packet.report["processes"][index]
        lines = packet[fixture.PREFIX + process["log"]].splitlines(keepends=True)
        locations = [number for number, line in enumerate(lines) if line.startswith(SUMMARY)]
        self.assertEqual(len(locations), 1)
        location = locations[0]
        value = json.loads(lines[location][len(SUMMARY):])
        change(value)
        lines[location] = SUMMARY + fixture.encoded(value)
        observation = deepcopy(process["observation"])
        observation["warm"]["summary"] = value
        self._replace_process_log(packet, index, b"".join(lines), observation)

    def _rejected(self, change, reason):
        with tempfile.TemporaryDirectory(prefix="p06-process-replay-") as directory, fixture.Packet() as packet:
            change(packet)
            path = Path(directory) / "mutated.zip"
            digest = packet.write(path)
            self.assertNotEqual(digest, fixture.ORIGINAL_SHA256)
            with self.assertRaisesRegex(ValueError, re.escape(reason)):
                fixture.replay(path, digest)

    def test_equivalent_witness_serialization_with_repaired_copies_passes(self):
        with tempfile.TemporaryDirectory(prefix="p06-process-positive-") as directory, fixture.Packet() as packet:
            self._witness(packet, lambda value: None, index=3)
            path = Path(directory) / "reserialized.zip"
            digest = packet.write(path)
            self.assertNotEqual(digest, fixture.ORIGINAL_SHA256)
            result = fixture.replay(path, digest)
        self.assertEqual(result["outcome"], "pass")
        self.assertEqual(result["counts"], dict(contract.COMPLETE_COUNTS))
        self.assertEqual(result["native_execution"], "not_run")
        for name in contract.FALSE_CLAIMS:
            self.assertIs(result[name], False)

    def test_forged_fp32_word_rejects_despite_matching_observation_copies(self):
        self._rejected(lambda packet: self._operation(packet,
            lambda row: row["actual_bits"].__setitem__(0, "40400001")),
            "warm operation 0.actual_bits")

    def test_launch_and_operation_population_cannot_change(self):
        with self.subTest("second launch"):
            self._rejected(lambda packet: self._operation(packet,
                lambda row: row["dispatch"].update(launches=2), index=1),
                "warm operation 0.dispatch.launches")

        def omit_last(packet):
            process = packet.report["processes"][2]
            lines = packet[fixture.PREFIX + process["log"]].splitlines(keepends=True)
            location = [number for number, line in enumerate(lines) if line.startswith(OPERATION)][-1]
            del lines[location]
            observation = deepcopy(process["observation"])
            observation["warm"]["operations"].pop()
            self._replace_process_log(packet, 2, b"".join(lines), observation)
        with self.subTest("missing operation"):
            self._rejected(omit_last, "warm summary is repeated or precedes the complete sequence")

    def test_low_high_reply_pairing_remains_exact(self):
        controls = (
            ("high value", lambda value: value["reads"][1].update(value=1), "managed read[1].value"),
            ("duplicate sequence", lambda value: value["reads"][1].update(sequence=1),
             "managed read[1].sequence"),
        )
        for label, change, reason in controls:
            with self.subTest(label):
                self._rejected(lambda packet: self._witness(packet, change), reason)

    def test_selector_tag_cannot_be_reassigned(self):
        self._rejected(lambda packet: self._witness(packet,
            lambda value: value["reads"][2].update(tag=value["reads"][2]["tag"] ^ (1 << 16)), index=2),
            "managed read[2].tag")

    def test_counter_reads_preserve_reset_and_saved_class(self):
        controls = (
            ("reset", lambda value: value["reads"][66].update(reset_after=3),
             "managed read[66].reset_after"),
            ("saved class", lambda value: value["reads"][66].update(class_after=1),
             "managed read[66].class_after"),
        )
        for label, change, reason in controls:
            with self.subTest(label):
                self._rejected(lambda packet: self._witness(packet, change, index=1), reason)

    def test_snapshot_queries_cannot_change_or_run_the_model(self):
        controls = (
            ("changed model", lambda value: value["snapshots"][1]["after"].update(
                ticks=value["snapshots"][1]["after"]["ticks"] + 1),
             "managed snapshot after_prime.unchanged model"),
            ("running model", lambda value: value["snapshots"][1]["before"].update(any_running=True),
             "managed snapshot after_prime.before.any_running"),
        )
        for label, change, reason in controls:
            with self.subTest(label):
                self._rejected(lambda packet: self._witness(packet, change), reason)

    def test_terminal_runtime_ownership_is_closed(self):
        for field, number in (("device_refs", 2), ("buffers", 1), ("queues", 1)):
            with self.subTest(field=field):
                self._rejected(lambda packet: self._witness(packet,
                    lambda value: value["snapshots"][-1].update({field: number}), index=3),
                    "managed snapshot before_release." + field)

    def test_lifecycle_counts_cannot_hide_incomplete_runs_or_disposal(self):
        for field, number in (("run_completed", 32), ("destroyed", 0), ("violations", 1)):
            with self.subTest(field=field):
                self._rejected(lambda packet: self._witness(packet,
                    lambda value: value["observation"].update({field: number})),
                    "managed observation." + field)

    def test_destruction_reset_and_terminal_boundary_are_bound(self):
        controls = (
            ("reset", lambda value: value["observation"]["destruction"].update(reset_after=35),
             "managed observation.destruction.reset_after"),
            ("boundary", lambda value: value["observation"]["destruction"]["before"].update(
                ticks=value["observation"]["destruction"]["before"]["ticks"] + 1),
             "managed snapshot before_release.destruction boundary"),
        )
        for label, change, reason in controls:
            with self.subTest(label):
                self._rejected(lambda packet: self._witness(packet, change, index=2), reason)

    def test_reset_generations_cannot_move_backwards(self):
        def rewind(value):
            for side in ("before", "after"):
                value["snapshots"][2][side]["reset_generation"] = 1
            for row in value["reads"][132:198]:
                row.update(reset_before=1, reset_after=1)
        self._rejected(lambda packet: self._witness(packet, rewind, index=3),
                       "managed snapshot after_batch: reset generation moved backwards")

    def test_cache_flush_reads_are_complete_and_ordered(self):
        controls = (
            ("missing", lambda value: value["cache_flush_reads"].pop(),
             "managed cache-flush read inventory differs"),
            ("completion", lambda value: value["cache_flush_reads"][0].update(completed=False),
             "managed cache-flush read[0].completed"),
            ("sequence", lambda value: value["cache_flush_reads"][1].update(sequence=135),
             "managed cache-flush read[1].sequence"),
        )
        for label, change, reason in controls:
            with self.subTest(label):
                self._rejected(lambda packet: self._witness(packet, change), reason)

    def test_unavailable_counter_cannot_gain_a_status_or_value(self):
        def enable_value(summary):
            row = next(row for row in summary["snapshots"]["after_open"]["counters"]
                       if row["enabled"] is False)
            row.update(status=0, value=0)
        self._rejected(lambda packet: self._summary(packet, enable_value, index=2),
                       "disabled counter must have unavailable status and value")

    def test_loaded_library_inventory_and_bound_paths_are_exact(self):
        controls = (
            ("path", lambda value: value["loaded_libraries"][2].update(path="/tmp/forged/libsimx.so"),
             "loaded library libsimx.so"),
            ("name", lambda value: value["loaded_libraries"][2].update(name="libvortex.so"),
             "loaded library name"),
            ("extra", lambda value: value["loaded_libraries"].append(
                {"name": "libunexpected.so", "path": "/tmp/libunexpected.so"}),
             "loaded libraries: inventory length differs"),
        )
        for label, change, reason in controls:
            with self.subTest(label):
                self._rejected(lambda packet: self._witness(packet, change, index=3), reason)

    def test_process_bindings_cannot_be_reassigned_or_crossed(self):
        def binding_policy(packet):
            process = packet.report["processes"][3]
            value = packet.json(process["binding"]["path"])
            value["process"]["policy"] = "per_operation"
            packet.replace_retained(process["binding"]["path"], fixture.encoded(value))
            packet.rehash_bindings()
        with self.subTest("rehashed binding"):
            self._rejected(binding_policy, "reconstructed process binding.process.policy")

        def foreign_process(packet):
            other = packet.report["processes"][1]
            self._replace_process_log(packet, 0, packet[fixture.PREFIX + other["log"]],
                                      deepcopy(other["observation"]))
        with self.subTest("coherent other process"):
            self._rejected(foreign_process, "managed witness.process_id")


if __name__ == "__main__":
    unittest.main()
