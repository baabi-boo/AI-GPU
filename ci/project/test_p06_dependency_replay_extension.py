# SPDX-License-Identifier: Apache-2.0
"""Exercise explicit trusted replay routes with synthetic, non-native packets."""

from copy import deepcopy
import json
import unittest
from unittest import mock

import p06_dependency_native_replay as replay
import p06_native_lifetime_test_fixture as fixture
from test_p06_dependency_native_replay import MemoryView, SyntheticNativePacket, descriptor


PIN = "e" * 64


class SyntheticRoute:
    CONTRACT_ID = "synthetic-explicit-native-route-v1"
    SCOPE = "synthetic-explicit-native-route"
    SOURCE_FILES = replay.admission.SOURCE_FILES
    LIMITATIONS = ["Synthetic test grammar only; no execution or qualification."]

    @staticmethod
    def contract():
        return {"contract_id": SyntheticRoute.CONTRACT_ID,
                "parent": replay.admission.contract(), "extension_digest": PIN}

    @staticmethod
    def contract_hash():
        return replay.qualification_id(SyntheticRoute.contract())


class ExtendedReplay(replay._NativeReplay):
    route_module = SyntheticRoute
    report_fields = replay.REPORT_FIELDS | {"extension_snapshot", "extension_digest"}
    result_contract_id = "synthetic-explicit-native-replay-v1"
    result_scope = "synthetic-extended-retained-consistency"
    result_limitations = SyntheticRoute.LIMITATIONS

    def validate_route_provenance(self):
        replay._same(self.report["extension_digest"], PIN, "external extension digest")
        replay._same(self.document("extension_snapshot", "extension"),
                     {"digest": PIN}, "retained extension")

    def build_binding_extra(self):
        return {"extension_digest": PIN}

    def process_binding_extra(self, planned):
        return {"extension_digest": PIN, "extension_process": planned["id"]}

    def stability_extra(self):
        return {"extension_stability": {"digest": PIN}}

    def result_extra(self):
        return {"extension_verified": True}


def extend_packet(packet):
    packet.report.update(contract_id=SyntheticRoute.CONTRACT_ID,
        scope=SyntheticRoute.SCOPE, contract_sha256=SyntheticRoute.contract_hash(),
        limitations=[*SyntheticRoute.LIMITATIONS, *replay.producer.base.PROCESS_LIMITATIONS],
        extension_digest=PIN)
    packet.report["contract_snapshot"] = packet.put_json("snapshots/contract.json", SyntheticRoute.contract())
    packet.report["extension_snapshot"] = packet.put_json("snapshots/extension.json", {"digest": PIN})
    commands = {row["id"]: row for row in packet.report["commands"]}
    for variant in packet.report["variants"]:
        binding = json.loads(packet.files[variant["binding"]["path"]])
        binding.update(contract_id=SyntheticRoute.CONTRACT_ID,
            contract_sha256=SyntheticRoute.contract_hash(), extension_digest=PIN)
        build_id = replay.qualification_id(binding)
        variant["binding"] = packet.put_json(variant["binding"]["path"], binding)
        variant["build_binding_sha256"] = build_id
        for row in packet.report["processes"]:
            if row["format"] != variant["format"]:
                continue
            process = json.loads(packet.files[row["binding"]["path"]])
            process.update(contract_id=SyntheticRoute.CONTRACT_ID,
                contract_sha256=SyntheticRoute.contract_hash(), build_binding_sha256=build_id,
                build=binding, extension_digest=PIN, extension_process=row["id"])
            binding_id = replay.qualification_id(process)
            row.update(execution_binding_sha256=binding_id, build_binding_sha256=build_id,
                binding=packet.put_json(row["binding"]["path"], process))
            raw = fixture.raw_records(row["format"], row["policy"], binding_id=binding_id)
            raw[3]["loaded_libraries"] = [{"name": name, "path": path}
                for name, path in sorted(variant["expected_loaded_libraries"].items())]
            text = fixture.render_log(*raw[1:])
            observed = replay.records.verify_output(text, contract=packet.contract, case=raw[0],
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
    for row in packet.report["stability_checks"]:
        row["extension_stability"] = {"digest": PIN}
    packet.finish()
    return packet


def reader(packet, reader_type=ExtendedReplay):
    packet.finish()
    return reader_type(MemoryView(packet.files, packet.api), packet.api, packet.revision,
        dependency_document=deepcopy(packet.dependency_document),
        dependency_verification=deepcopy(packet.dependency_verification),
        dependency_body=packet.dependency_body, dependency_receipt_sha256=packet.receipt_pin,
        source_manifest_sha256=packet.source_pin)


class ExplicitRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = SyntheticNativePacket()
        cls.extended = extend_packet(deepcopy(cls.original))

    def setUp(self):
        self.packet = deepcopy(self.extended)

    def test_default_route_remains_complete_and_unqualified(self):
        result = reader(deepcopy(self.original), replay._NativeReplay).run()
        self.assertEqual(result["contract_id"], replay.CONTRACT_ID)
        self.assertEqual(result["counts"], replay.COUNTS)
        self.assertNotIn("extension_verified", result)
        for name in replay.manifest.FALSE_CLAIMS:
            self.assertIs(result[name], False)

    def test_explicit_route_reconstructs_new_bindings_without_execution(self):
        with mock.patch("subprocess.Popen", side_effect=AssertionError("retained process")), \
             mock.patch("os.system", side_effect=AssertionError("retained shell")):
            result = reader(self.packet).run()
        self.assertEqual(result["contract_id"], ExtendedReplay.result_contract_id)
        self.assertEqual(result["scope"], ExtendedReplay.result_scope)
        self.assertEqual(result["commands_checked"], 37)
        self.assertEqual(result["counts"], replay.COUNTS)
        self.assertTrue(result["extension_verified"])
        self.assertEqual(result["native_execution"], "not_run")
        self.assertIs(result["retained_code_executed"], False)
        for name in replay.manifest.FALSE_CLAIMS:
            self.assertIs(result[name], False)

    def test_default_reader_does_not_autodetect_extended_report(self):
        with self.assertRaisesRegex(ValueError, "missing or unknown fields"):
            reader(self.packet, replay._NativeReplay).run()

    def test_explicit_reader_does_not_upgrade_old_report(self):
        with self.assertRaisesRegex(ValueError, "missing or unknown fields"):
            reader(deepcopy(self.original)).run()

    def test_rehashed_unexpected_proof_and_binding_values_reject(self):
        for field in ("extension", "build", "process"):
            packet = deepcopy(self.extended)
            if field == "extension":
                packet.report["extension_snapshot"] = packet.put_json(
                    "snapshots/extension.json", {"digest": "d" * 64})
            else:
                owner = packet.report["variants"][0] if field == "build" else packet.report["processes"][0]
                value = json.loads(packet.files[owner["binding"]["path"]])
                value["extension_digest"] = "d" * 64
                owner["binding"] = packet.put_json(owner["binding"]["path"], value)
                owner["build_binding_sha256" if field == "build" else "execution_binding_sha256"] = replay.qualification_id(value)
            with self.subTest(field=field), self.assertRaises(ValueError):
                reader(packet).run()

    def test_late_missing_or_changed_extension_stability_rejects(self):
        for missing in (False, True):
            packet = deepcopy(self.extended)
            last = packet.report["stability_checks"][-1]
            if missing:
                del last["extension_stability"]
            else:
                last["extension_stability"] = {"digest": "d" * 64}
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                reader(packet).run()

    def test_result_extension_cannot_change_old_claims(self):
        class ReplacingResult(ExtendedReplay):
            def result_extra(self):
                return {"qualified": True}

        with self.assertRaisesRegex(ValueError, "replay result extension replaces"):
            reader(self.packet, ReplacingResult).run()

    def test_binding_extension_cannot_replace_core_provenance(self):
        class ReplacingBinding(ExtendedReplay):
            def build_binding_extra(self):
                return {"source": {}}

        with self.assertRaisesRegex(ValueError, "build binding extension replaces"):
            reader(self.packet, ReplacingBinding).run()

    def test_unaccounted_member_still_rejects_with_an_explicit_route(self):
        self.packet.put("snapshots/unreviewed.json", b"{}\n")
        with self.assertRaisesRegex(ValueError, "complete semantically bound retained inventory"):
            reader(self.packet).run()

    def test_new_report_cannot_select_a_subclass_through_shared_view_api(self):
        checked = {"retained_dependency_verification": self.packet.dependency_verification}
        with mock.patch.object(replay.dependency_replay, "verify_view", return_value=checked), \
             self.assertRaisesRegex(ValueError, "missing or unknown fields"):
            replay.verify_view(MemoryView(self.packet.files, self.packet.api),
                MemoryView({"report.json": self.packet.dependency_body}, self.packet.api), self.packet.api,
                expected_revision=self.packet.revision, expected_receipt_sha256=self.packet.receipt_pin,
                expected_native_report_sha256=self.packet.api.descriptor(
                    descriptor("report.json", self.packet.files["report.json"]))["sha256"],
                expected_source_manifest_sha256=self.packet.source_pin)


if __name__ == "__main__":
    unittest.main()
