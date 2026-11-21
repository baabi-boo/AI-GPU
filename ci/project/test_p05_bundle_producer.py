# SPDX-License-Identifier: Apache-2.0
"""Synthetic host-only producer provenance tests; no accelerator acceptance.

The fixture imports unchanged P04 in isolation and injects labeled process
results. Real hashing, source/fixture/header generation, separate compiler-record
validation and strict P04 raw-record validation remain active throughout.
"""

import copy
import hashlib
import json
import tempfile
import unittest
from unittest import mock

from p05_bundle_test_fixture import SCOPE, SyntheticP04Packet, producer, save


class ProducerProvenanceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="p05-producer-synthetic-host-only-")
        self.addCleanup(temporary.cleanup)
        self.fixture = SyntheticP04Packet(temporary.name)

    def reject(self, message=None, **overrides):
        destination = overrides.get("destination", self.fixture.destination)
        manager = (self.assertRaisesRegex((ValueError, OSError), message) if message
                   else self.assertRaises((ValueError, OSError)))
        with manager:
            self.fixture.create(**overrides)
        self.assertFalse((destination / "manifest.json").exists())

    def test_direct_p04_callback_packet_produces_canonical_bundle(self):
        fixture = self.fixture
        self.assertEqual(fixture.report["state"], "finished")
        self.assertFalse(fixture.report["development"])
        self.assertFalse(fixture.report["acceptance_claimed"])
        self.assertEqual(fixture.report["completed_case_executions"], 5)
        self.assertEqual(fixture.report["completed_model_runs"], 10)
        self.assertEqual(fixture.report["completed_launches"], 30)
        self.assertEqual(len(fixture.process_ids), 15)
        self.assertTrue(all(row["synthetic_host_only_scope"] == SCOPE
                            for row in fixture.report["commands"]))
        retained = {row["path"] for row in fixture.report["retained_sources"]}
        self.assertTrue({"artifacts/source/" + row["path"]
                         for row in fixture.report["loaded_helpers"]} <= retained)
        before = json.loads((fixture.packet / fixture.report["source_before"]["path"]).read_text())
        source_files = {row["path"]: row for row in before["files"]}
        for helper in fixture.report["loaded_helpers"]:
            self.assertEqual(helper, source_files[helper["path"]])
        self.assertNotIn("ci/project/p05_bundle_test_fixture.py",
                         {row["path"] for row in fixture.report["loaded_helpers"]})
        self.assertTrue((fixture.packet / "artifacts/simx-fp16/.config.stamp").is_file())
        manifest = fixture.create()
        self.assertEqual(manifest["native_binding"], fixture.binding)
        self.assertEqual({row["role"] for row in manifest["artifacts"]}, set(producer._bundle.ROLES))
        raw = (fixture.destination / "manifest.json").read_bytes()
        self.assertEqual(raw, (json.dumps(manifest, sort_keys=True, separators=(",", ":"),
                                         allow_nan=False) + "\n").encode())
        self.assertTrue(all("size_bytes" in row and "size" not in row
                            for row in manifest["native_binding"]["artifacts"]))
        self.assertTrue(all("size" in row and "size_bytes" not in row for row in manifest["artifacts"]))
        for row in manifest["artifacts"]:
            original_root, original = producer._NATIVE_PATHS[row["role"]]
            root = fixture.source if original_root == "source" else fixture.build
            self.assertEqual((fixture.destination / row["path"]).read_bytes(), (root / original).read_bytes())
        binding = producer._bundle.build_binding(fixture.destination, fixture.source)
        self.assertEqual(binding, (hashlib.sha256(raw).hexdigest(), manifest["binding_source_sha256"]))

    def test_bf16_direct_packet_uses_real_format_specific_validators(self):
        with tempfile.TemporaryDirectory(prefix="p05-producer-synthetic-bf16-") as temporary:
            fixture = SyntheticP04Packet(temporary, fmt="bf16")
            manifest = fixture.create()
            self.assertEqual(manifest["format"], "bf16")
            self.assertEqual([row["role"] for row in manifest["native_binding"]["compiler_records"]],
                             ["runtime", "backend_cpp", "kernel", "host"])
            producer._bundle.build_binding(fixture.destination, fixture.source)

    def test_foreign_source_checkout_and_original_build_path_are_rejected(self):
        other = self.fixture.area / "other-source"
        other.mkdir()
        self.reject("selected source checkout", source=other)
        self.fixture.report["paths"]["work"] = str(self.fixture.area / "different-work")
        self.fixture.save_report()
        self.reject("original variant build")

    def test_dirty_or_changed_source_identity_is_rejected(self):
        self.fixture.checkout["dirty"] = True
        self.reject("clean source")
        self.fixture.checkout["dirty"] = False
        self.fixture.checkout["revision"] = "3" * 40
        self.reject("current clean source")

    def test_current_source_or_retained_helper_body_mutation_is_rejected(self):
        source = self.fixture.source / "ci/project/p04_execution_records.py"
        original = source.read_bytes()
        source.write_bytes(original + b"\n# synthetic source mutation\n")
        self.reject("producer/helper bytes changed")
        source.write_bytes(original)
        retained = self.fixture.packet / "artifacts/source/ci/project/p04_execution_records.py"
        retained.write_bytes(retained.read_bytes() + b"\n# synthetic retained mutation\n")
        self.reject("retained native source differs")

    def test_loaded_helper_and_required_source_retention_cannot_be_omitted(self):
        path = "artifacts/source/ci/project/p04_execution_records.py"
        self.fixture.report["retained_sources"] = [row for row in self.fixture.report["retained_sources"]
                                                   if row["path"] != path]
        self.fixture.save_report()
        self.reject("omits required runner or source bodies")

    def test_retained_loaded_helper_must_be_present_in_source_snapshot(self):
        name = "ci/project/p05_bundle_test_fixture.py"
        raw = (self.fixture.source / name).read_bytes()
        self.fixture.report["loaded_helpers"].append({
            "path": name, "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)})
        self.fixture.save_report()
        self.reject("helper.*snapshot|snapshot.*helper")

    def test_report_requires_completed_clean_two_poison_native_execution(self):
        mutations = (("schema_version", True), ("contract_id", "p05-model-execution-v1"),
                     ("state", "running"), ("outcome", "blocked"), ("development", True),
                     ("reason", "synthetic failure"), ("acceptance_claimed", True),
                     ("phase_complete", True), ("source_stable", False), ("iterations", 1),
                     ("iterations", True))
        for key, value in mutations:
            with self.subTest(key=key, value=value):
                original = self.fixture.report[key]
                self.fixture.report[key] = value
                self.fixture.save_report()
                self.reject()
                self.fixture.report[key] = original

    def test_all_four_compiler_roles_reject_rehashed_wrong_format_stamps(self):
        for role, name, line in (("runtime", "sw/runtime/simx_rt_config.stamp", 0),
                                 ("backend", "sw/runtime/simx_config.stamp", 0),
                                 ("kernel", producer.native_run.APP + "/config.stamp", 0),
                                 ("host", producer.native_run.APP + "/config.stamp", 1)):
            with self.subTest(role=role):
                path = self.fixture.build / name
                original = path.read_bytes()
                lines = original.decode().splitlines()
                self.assertIn("-DITYPE=fp16", lines[line])
                lines[line] = lines[line].replace("-DITYPE=fp16", "-DITYPE=bf16")
                path.write_text("\n".join(lines) + "\n")
                self.fixture.rehash_build()
                self.reject("ITYPE")
                path.write_bytes(original)
                self.fixture.rehash_build()

    def test_unhashed_raw_log_mutation_is_rejected(self):
        command = self.fixture.command("fp16-zero")
        path = self.fixture.packet / command["log"]
        path.write_bytes(path.read_bytes() + b"synthetic unrecorded trailing data\n")
        self.reject("native command log changed")

    def test_rehashed_second_poison_corruption_reaches_real_model_validator(self):
        command = self.fixture.command("fp16-split_boundary")
        raw = (self.fixture.packet / command["log"]).read_text()
        modified = raw.replace('"poison":3735928559', '"poison":2143346349')
        self.assertNotEqual(modified, raw)
        self.fixture.save_log(command, modified)
        self.reject("poison")

    def test_rehashed_wrong_output_words_cannot_be_hidden_by_saved_pass(self):
        command = self.fixture.command("fp16-zero")
        lines = (self.fixture.packet / command["log"]).read_text().splitlines()
        index = next(index for index, line in enumerate(lines) if line.startswith("P04_RESULT "))
        row = json.loads(lines[index][len("P04_RESULT "):])
        row["trace"]["output_words"][0] = "3f800000"
        lines[index] = "P04_RESULT " + json.dumps(row, separators=(",", ":"))
        self.fixture.save_log(command, "\n".join(lines) + "\n")
        self.reject("output|logits")

    def test_saved_observations_must_equal_raw_validated_model_records(self):
        self.fixture.variant["cases"][0]["observations"][0]["trace"]["create_end_ns"] += 1
        self.fixture.save_report()
        self.reject("observations differ from raw")

    def test_missing_duplicate_and_reordered_model_families_are_rejected(self):
        cases = copy.deepcopy(self.fixture.variant["cases"])
        for changed in (cases[:-1], [*cases[:-1], cases[0]], list(reversed(cases))):
            with self.subTest(ids=[row["id"] for row in changed]):
                self.fixture.variant["cases"] = changed
                self.fixture.save_report()
                self.reject("all five cases exactly once in fixture order")

    def test_rehashed_fixture_selection_cannot_omit_fifth_family(self):
        self.fixture.report["case_ids"].pop()
        self.fixture.report["fixture_snapshot"] = save(
            self.fixture.packet, "snapshots/fixtures.json", self.fixture.cases[:-1])
        self.fixture.save_report()
        self.reject("native case selection differs")

    def test_passing_command_requires_zero_integer_exit_and_complete_cleanup(self):
        command = self.fixture.command("fp16-zero")
        for key, value in (("cleanup_complete", False), ("cleanup_complete", 1),
                           ("exit_code", False), ("exit_code", 1), ("outcome", "blocked"),
                           ("reason", "synthetic child still alive")):
            with self.subTest(key=key, value=value):
                original = command[key]
                command[key] = value
                self.fixture.save_report()
                self.reject("did not complete successfully")
                command[key] = original

    def test_missing_and_duplicate_required_commands_are_rejected(self):
        original = self.fixture.report["commands"]
        self.fixture.report["commands"] = [row for row in original
                                          if row["id"] != "simx-fp16-effective-header"]
        self.fixture.save_report()
        self.reject("lacks required commands")
        self.fixture.report["commands"] = [*original, copy.deepcopy(original[-1])]
        self.fixture.save_report()
        self.reject("duplicate native command")

    def test_changed_configure_build_and_model_invocations_are_rejected(self):
        for suffix in ("configure", "runtime", "application", "fp16-zero"):
            with self.subTest(suffix=suffix):
                command = self.fixture.command(suffix)
                original = command["argv"]
                command["argv"] = [*original, "--synthetic-unrecorded-option"]
                self.fixture.save_report()
                self.reject("invocation differs")
                command["argv"] = original

    def test_changed_model_runtime_environment_is_rejected(self):
        self.fixture.command("fp16-zero")["environment"]["VORTEX_DRIVER"] = "rtlsim"
        self.fixture.save_report()
        self.reject("native model launch environment differs")

    def test_rehashed_generated_header_must_reproduce_from_frozen_profile(self):
        path = self.fixture.build / "sw/VX_config.h"
        path.write_bytes(path.read_bytes() + b"\n#define SYNTHETIC_STALE_HEADER 1\n")
        self.fixture.rehash_build()
        self.reject("generated native header differs")

    def test_copied_build_recipe_and_live_hidden_config_are_required(self):
        name = producer.native_run.base.COPIED[0]
        path = self.fixture.build / name
        original = path.read_bytes()
        path.write_bytes(original + b"\n# synthetic stale generated helper\n")
        self.reject("generated Makefile/helper differs")
        path.write_bytes(original)
        (self.fixture.build / ".config.stamp").unlink()
        self.reject()

    def test_dependency_and_native_binary_bytes_must_match_original_binding(self):
        for root, name, error in ((self.fixture.source, producer.native_run.base.DEPENDENCIES[1],
                                    "native dependencies changed"),
                                   (self.fixture.build, "sw/runtime/libvortex.so", "artifact inventory differs")):
            with self.subTest(name=name):
                path = root / name
                original = path.read_bytes()
                path.write_bytes(original + b"synthetic mutation\n")
                self.reject(error)
                path.write_bytes(original)

    def test_missing_retained_hidden_config_is_rejected(self):
        (self.fixture.packet / "artifacts/simx-fp16/.config.stamp").unlink()
        self.reject()

    def test_tampered_retained_generated_header_is_rejected(self):
        path = self.fixture.packet / "artifacts/simx-fp16/sw/VX_config.h"
        path.write_bytes(path.read_bytes() + b"\n/* synthetic retained-body corruption */\n")
        self.reject()

    def test_missing_or_tampered_retained_compiler_stamps_are_rejected(self):
        for name in ("sw/runtime/simx_rt_config.stamp", "sw/runtime/simx_config.stamp",
                     producer.native_run.APP + "/config.stamp"):
            with self.subTest(name=name):
                path = self.fixture.packet / "artifacts/simx-fp16" / name
                original = path.read_bytes()
                path.write_bytes(original + b"-DSYNTHETIC_UNRETAINED=1\n")
                self.reject()
                path.write_bytes(original)

    def test_existing_destination_is_preserved_without_overwrite(self):
        self.fixture.destination.mkdir()
        marker = self.fixture.destination / "keep.txt"
        marker.write_bytes(b"existing user-owned contents\n")
        with self.assertRaisesRegex(ValueError, "must be new"):
            self.fixture.create()
        self.assertEqual(marker.read_bytes(), b"existing user-owned contents\n")
        self.assertEqual(list(self.fixture.destination.iterdir()), [marker])

    def test_destination_symlink_and_symlinked_parent_are_rejected(self):
        target = self.fixture.area / "owned-existing-directory"
        target.mkdir()
        marker = target / "keep.txt"
        marker.write_bytes(b"preserve existing directory\n")
        link = self.fixture.area / "destination-link"
        link.symlink_to(target, target_is_directory=True)
        for destination in (link, link / "new-bundle"):
            with self.subTest(destination=destination):
                self.reject("symlink", destination=destination)
        self.assertEqual(list(target.iterdir()), [marker])
        self.assertEqual(marker.read_bytes(), b"preserve existing directory\n")

    def test_symlinked_input_roots_are_rejected(self):
        for key, target in (("source", self.fixture.source), ("build", self.fixture.build),
                            ("native_output", self.fixture.packet)):
            with self.subTest(key=key):
                link = self.fixture.area / (key + "-link")
                link.symlink_to(target, target_is_directory=True)
                self.reject("symlink", **{key: link})

    def test_symlinked_source_log_generated_and_native_files_are_rejected(self):
        paths = ((self.fixture.source, "ci/project/p04_execution_records.py"),
                 (self.fixture.packet, self.fixture.command("fp16-zero")["log"]),
                 (self.fixture.build, ".config.stamp"),
                 (self.fixture.build, "sw/runtime/libvortex.so"),
                 (self.fixture.packet, "artifacts/simx-fp16/.config.stamp"))
        for index, (root, name) in enumerate(paths):
            with self.subTest(name=name):
                path = root / name
                original = path.read_bytes()
                target = self.fixture.area / ("symlink-target-" + str(index))
                target.write_bytes(original)
                path.unlink()
                path.symlink_to(target)
                try:
                    self.reject("symlink")
                finally:
                    path.unlink()
                    path.write_bytes(original)

    def test_source_build_or_packet_mutation_during_copy_leaves_no_manifest(self):
        paths = ((self.fixture.source, "sw/runtime/ai/mlp_runtime.cpp"),
                 (self.fixture.build, "sw/runtime/libvortex.so"),
                 (self.fixture.packet, self.fixture.command("fp16-zero")["log"]))
        observe = producer._Inputs.observe
        for index, (root, name) in enumerate(paths):
            with self.subTest(name=name):
                path = root / name
                original = path.read_bytes()
                changed = []

                def change_after_copy(inputs, source, relative, **kwargs):
                    value = observe(inputs, source, relative, **kwargs)
                    if kwargs.get("sink") is not None and not changed:
                        path.write_bytes(original + b"\nSYNTHETIC MUTATION DURING COPY\n")
                        changed.append(relative)
                    return value

                destination = self.fixture.area / ("copy-mutation-" + str(index))
                try:
                    with mock.patch.object(producer._Inputs, "observe", change_after_copy):
                        self.reject("changed|differ", destination=destination)
                    self.assertEqual(len(changed), 1)
                    self.assertTrue(destination.is_dir())
                finally:
                    path.write_bytes(original)

    def test_changed_tools_during_copy_prevent_manifest_publication(self):
        original = copy.deepcopy(self.fixture.tool_inventory)
        observe = producer._Inputs.observe
        changed = []

        def change_after_copy(inputs, root, relative, **kwargs):
            value = observe(inputs, root, relative, **kwargs)
            if kwargs.get("sink") is not None and not changed:
                self.fixture.tool_inventory["make"]["path"] += "-changed"
                changed.append(relative)
            return value

        with mock.patch.object(producer._Inputs, "observe", change_after_copy):
            self.reject("tools changed during bundle copying")
        self.assertEqual(len(changed), 1)
        self.fixture.tool_inventory = original

    def test_postpublication_failure_removes_qualified_manifest(self):
        with mock.patch.object(producer._bundle, "read_manifest",
                               side_effect=ValueError("synthetic final readback failure")):
            self.reject("synthetic final readback failure")
        self.assertTrue(self.fixture.destination.is_dir())
        self.assertTrue((self.fixture.destination / "lib/libvortex.so").is_file())

    def test_duplicate_json_keys_and_unsafe_retained_paths_are_rejected(self):
        path = self.fixture.packet / "report.json"
        raw = path.read_bytes()
        path.write_bytes(b'{"schema_version":1,' + raw[1:])
        self.reject("invalid strict JSON")
        path.write_bytes(raw)
        original = self.fixture.report["loaded_helpers"][0]["path"]
        for unsafe in ("../outside", "/absolute", "ci//project/p04_execute.py",
                       "ci/project/./p04_execute.py", "ci/project/p04_execute.py/"):
            with self.subTest(path=unsafe):
                self.fixture.report["loaded_helpers"][0]["path"] = unsafe
                self.fixture.save_report()
                self.reject("unsafe bundle path")
        self.fixture.report["loaded_helpers"][0]["path"] = original


if __name__ == "__main__":
    unittest.main()
