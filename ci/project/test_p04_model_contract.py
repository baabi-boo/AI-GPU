# SPDX-License-Identifier: Apache-2.0
"""Corruption and read-only checks for the fixed tiny-model source contract."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import p04_model_contract as contract


ROOT = Path(__file__).resolve().parents[2]


class TinyMlpContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="p04-contract-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "source"
        self.root.mkdir()
        for name in (*contract.ARTIFACT_PATHS, contract.MANIFEST_PATH):
            destination = self.root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, destination)
        self.manifest_path = self.root / contract.MANIFEST_PATH
        self.fixture_path = self.root / contract.FIXTURE_PATH
        self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.fixture = json.loads(self.fixture_path.read_text(encoding="utf-8"))

    def snapshot(self):
        return {str(path.relative_to(self.root)): (path.read_bytes(), path.stat().st_mtime_ns)
                for path in self.root.rglob("*") if path.is_file()}

    def write_json(self, path, document):
        path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

    def reject_manifest(self, mutate):
        document = deepcopy(self.manifest)
        mutate(document)
        self.write_json(self.manifest_path, document)
        before = self.snapshot()
        with self.assertRaises(contract.ContractError):
            contract.validate(self.root)
        self.assertEqual(self.snapshot(), before)

    def rehash_fixture(self, document):
        self.write_json(self.fixture_path, document)
        manifest = deepcopy(self.manifest)
        for artifact in manifest["artifacts"]:
            if artifact["path"] == contract.FIXTURE_PATH:
                artifact["sha256"] = hashlib.sha256(self.fixture_path.read_bytes()).hexdigest()
        self.write_json(self.manifest_path, manifest)

    def reject_profile(self, mutate):
        name = "profiles/p02-tfr.json"
        path = self.root / name
        profile = json.loads((ROOT / name).read_text(encoding="utf-8"))
        mutate(profile)
        self.write_json(path, profile)
        # Match the changed source identity so rejection proves profile compatibility,
        # not just a stale digest. Each mutation starts from the accepted profile.
        manifest = deepcopy(self.manifest)
        for artifact in manifest["artifacts"]:
            if artifact["path"] == name:
                artifact["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.write_json(self.manifest_path, manifest)
        for arguments in (["--check"], ["--write-manifest"]):
            with self.subTest(arguments=arguments):
                # cli snapshots every file's bytes and mtime, including the manifest.
                result = self.cli(arguments, 1)
                self.assertIn("P02.profile", result.stderr)

    def cli(self, arguments, expected_code, *, readonly=True, checker=None):
        before = self.snapshot()
        result = subprocess.run(
            [sys.executable, str(checker or ROOT / "ci/project/p04_model_contract.py"),
             "--root", str(self.root), *arguments],
            cwd=self.root, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
            text=True, capture_output=True, timeout=20,
        )
        self.assertEqual(result.returncode, expected_code, result.stdout + result.stderr)
        if readonly:
            self.assertEqual(self.snapshot(), before, "verification must not repair or rewrite inputs")
        return result

    def test_frozen_inventory_validates_without_execution_claims(self):
        before = self.snapshot()
        result = contract.validate(self.root)
        self.assertEqual(result["result"], "pass")
        self.assertEqual(result["scope"], "source_present")
        self.assertEqual(result["case_count"], 10)
        self.assertEqual(result["planned_native_launches"], 30)
        self.assertIs(result["gpu_execution_claimed"], False)
        self.assertIs(result["execution_available"], False)
        self.assertEqual(self.snapshot(), before)

    def test_manifest_rejects_boolean_integer_and_float_substitutions(self):
        mutations = [
            lambda doc: doc.update(schema_version=True),
            lambda doc: doc.update(case_count=10.0),
            lambda doc: doc.update(execution_available=0),
            lambda doc: doc["numerics"].update(absolute_tolerance=False),
            lambda doc: doc["graph"][0]["mnk"].__setitem__(0, 16.0),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutations.index(mutate)):
                self.reject_manifest(mutate)

    def test_manifest_rejects_unknown_and_missing_fields(self):
        for mutate in (lambda doc: doc.update(unrecognized=True),
                       lambda doc: doc.pop("execution_available"),
                       lambda doc: doc["graph"][1].update(fallback="cpu")):
            self.reject_manifest(mutate)

    def test_placement_fallback_and_acceptance_cannot_be_relabelled(self):
        mutations = [
            lambda doc: doc.update(cpu_matmul_fallback=True),
            lambda doc: doc.update(gpu_execution_claimed=True),
            lambda doc: doc["execution_acceptances"].update({"P04-A02": "pass"}),
            lambda doc: doc["graph"][1].update(placement="native"),
            lambda doc: doc["graph"][0].update(placement="host"),
            lambda doc: doc["host_work_allowlist"].append("matmul"),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index):
                self.reject_manifest(mutate)

    def test_shapes_rows_and_actual_output_dependencies_are_fixed(self):
        mutations = [
            lambda doc: doc["graph"][0].update(mnk=[16, 4, 8]),
            lambda doc: doc["graph"][2].update(a="expected_bridge"),
            lambda doc: doc["graph"][1].update(input="expected_hidden"),
            lambda doc: doc["graph"][3].update(rows=[0, 8], a_offset_bytes=0),
            lambda doc: doc["graph"][4]["inputs"].reverse(),
            lambda doc: doc["graph"].pop(),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index):
                self.reject_manifest(mutate)

    def test_manifest_inventory_cannot_drop_duplicate_or_reorder_cases(self):
        for mutate in (lambda doc: (doc["case_ids"].pop(), doc.update(case_count=9)),
                       lambda doc: doc["case_ids"].__setitem__(1, doc["case_ids"][0]),
                       lambda doc: doc["case_ids"].reverse()):
            self.reject_manifest(mutate)

    def test_recomputed_tensor_and_fixture_hashes_do_not_bless_changed_reference(self):
        for stage in ("input", "hidden", "bridge", "output"):
            with self.subTest(stage=stage):
                document = deepcopy(self.fixture)
                case = document["cases"][0]
                words = case[stage + "_words"]
                words[0] = f"{int(words[0], 16) ^ 1:08x}"
                raw = b"".join(int(word, 16).to_bytes(4, "little") for word in words)
                case["sha256"][stage] = hashlib.sha256(raw).hexdigest()
                self.rehash_fixture(document)
                with self.assertRaisesRegex(contract.ContractError, "fixture"):
                    contract.validate(self.root)

    def test_fixture_cannot_change_inventory_metadata_or_word_representation(self):
        mutations = [
            lambda doc: doc["cases"].pop(),
            lambda doc: doc["cases"].reverse(),
            lambda doc: doc["cases"][0].update(format="fp32"),
            lambda doc: doc["cases"][0]["input_words"].__setitem__(0, "0000000A"),
            lambda doc: doc["model"].update(batch_size=True),
            lambda doc: doc["model"].update(weight_layout="row_major"),
            lambda doc: doc["weights"]["logical"]["w1"][0].__setitem__(0, 2),
            lambda doc: doc.update(extra_field=0),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index):
                document = deepcopy(self.fixture)
                mutate(document)
                self.rehash_fixture(document)
                with self.assertRaisesRegex(contract.ContractError, "fixture"):
                    contract.validate(self.root)

    def test_fixture_must_preserve_canonical_file_bytes(self):
        self.fixture_path.write_text(json.dumps(self.fixture) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(contract.ContractError, "canonical"):
            contract.validate(self.root)

    def test_source_identity_change_is_detected_without_refresh(self):
        source = self.root / "sw/runtime/ai/mlp_host.cpp"
        source.write_bytes(source.read_bytes() + b"\n// harmless identity probe\n")
        with self.assertRaisesRegex(contract.ContractError, "sha256"):
            contract.validate(self.root)
        self.cli(["--check"], 1)

    def test_changed_copied_producer_cannot_be_checked_with_another_oracle(self):
        name = "ci/project/p04_reference.py"
        producer = self.root / name
        original = producer.read_text(encoding="utf-8")
        changed = original.replace("0x50403401", "0x50403403", 1)
        self.assertNotEqual(changed, original)
        producer.write_text(changed, encoding="utf-8")
        manifest = deepcopy(self.manifest)
        for artifact in manifest["artifacts"]:
            if artifact["path"] == name:
                artifact["sha256"] = hashlib.sha256(producer.read_bytes()).hexdigest()
        self.write_json(self.manifest_path, manifest)
        for arguments in (["--check"], ["--write-manifest"]):
            with self.subTest(arguments=arguments):
                result = self.cli(arguments, 1)
                self.assertIn(name, result.stderr)
                self.assertIn("target source differs from the invoking implementation", result.stderr)
                self.assertIn("reviewed target's own checker", result.stderr)

    def test_copied_verifier_and_encoding_helper_must_match_invoking_sources(self):
        for name in ("ci/project/p04_model_contract.py",
                     "ci/project/p02_layout_fixture_oracle.py"):
            with self.subTest(source=name):
                source = self.root / name
                original = source.read_bytes()
                source.write_bytes(original + b"\n# copied implementation identity probe\n")
                manifest = deepcopy(self.manifest)
                for artifact in manifest["artifacts"]:
                    if artifact["path"] == name:
                        artifact["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
                self.write_json(self.manifest_path, manifest)
                for arguments in (["--check"], ["--write-manifest"]):
                    result = self.cli(arguments, 1)
                    self.assertIn(name, result.stderr)
                    self.assertIn("target source differs from the invoking implementation", result.stderr)
                before = self.snapshot()
                with self.assertRaisesRegex(contract.ContractError, "invoking implementation"):
                    contract.expected_manifest(self.root)
                self.assertEqual(self.snapshot(), before)
                source.write_bytes(original)
                self.write_json(self.manifest_path, self.manifest)

    def test_reviewed_target_uses_its_own_checker_for_producer_identity_changes(self):
        producer = self.root / "ci/project/p04_reference.py"
        producer.write_bytes(producer.read_bytes() + b"\n# reviewed identity-only change\n")
        self.assertIn("invoking implementation", self.cli(["--check"], 1).stderr)
        checker = self.root / "ci/project/p04_model_contract.py"
        fixture_before = self.fixture_path.read_bytes()
        self.cli(["--write-manifest"], 0, readonly=False, checker=checker)
        summary = json.loads(self.cli(["--check", "--json"], 0, checker=checker).stdout)
        self.assertEqual(summary["result"], "pass")
        self.assertIs(summary["gpu_execution_claimed"], False)
        self.assertEqual(self.fixture_path.read_bytes(), fixture_before)
        refreshed = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        changed = [entry for entry in refreshed["artifacts"] if entry not in self.manifest["artifacts"]]
        self.assertEqual([entry["path"] for entry in changed], ["ci/project/p04_reference.py"])
        self.assertIn("invoking implementation", self.cli(["--check"], 1).stderr)

    def test_missing_nonregular_and_oversized_artifacts_fail(self):
        path = self.root / "sw/runtime/ai/mlp_host.h"
        data = path.read_bytes()
        path.unlink()
        with self.assertRaises(contract.ContractError):
            contract.validate(self.root)
        path.mkdir()
        with self.assertRaises(contract.ContractError):
            contract.validate(self.root)
        path.rmdir()
        path.write_bytes(b" " * (contract.MAX_ARTIFACT_BYTES + 1))
        with self.assertRaises(contract.ContractError):
            contract.validate(self.root)
        path.write_bytes(data)
        self.fixture_path.write_bytes(b" " * (contract.MAX_DOCUMENT_BYTES + 1))
        with self.assertRaises(contract.ContractError):
            contract.validate(self.root)

    def test_manifest_paths_cannot_select_external_or_substituted_files(self):
        for mutate in (lambda doc: doc.update(fixture="../outside.json"),
                       lambda doc: doc["artifacts"][0].update(path="/tmp/arbitrary.json"),
                       lambda doc: doc["artifacts"][1].update(path="../../outside.py"),
                       lambda doc: doc["artifacts"].pop()):
            self.reject_manifest(mutate)

    def test_symlink_artifact_and_parent_directory_are_rejected(self):
        outside = Path(self.temporary.name) / "outside.json"
        outside.write_bytes(self.fixture_path.read_bytes())
        self.fixture_path.unlink()
        self.fixture_path.symlink_to(outside)
        with self.assertRaisesRegex(contract.ContractError, "symlink"):
            contract.validate(self.root)
        self.fixture_path.unlink()
        self.fixture_path.write_bytes(outside.read_bytes())
        original = self.fixture_path.parent
        moved = Path(self.temporary.name) / "external-fixtures"
        original.rename(moved)
        original.symlink_to(moved, target_is_directory=True)
        with self.assertRaisesRegex(contract.ContractError, "symlink"):
            contract.validate(self.root)

    def test_symlink_root_and_manifest_are_rejected(self):
        alias = Path(self.temporary.name) / "source-alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(contract.ContractError, "symlink"):
            contract.validate(alias)
        outside = Path(self.temporary.name) / "outside-manifest.json"
        outside.write_bytes(self.manifest_path.read_bytes())
        before = outside.read_bytes()
        self.manifest_path.unlink()
        self.manifest_path.symlink_to(outside)
        with self.assertRaisesRegex(contract.ContractError, "symlink"):
            contract.validate(self.root)
        self.cli(["--write-manifest"], 1)
        self.assertEqual(outside.read_bytes(), before)

    def test_json_loader_rejects_duplicate_keys_nonfinite_and_malformed_documents(self):
        path = self.root / "parser-input.json"
        invalid = [b'{"value":1,"value":2}', b'{"nested":{"x":1,"x":1}}',
                   b'{"value":NaN}', b'{"value":Infinity}', b'{"value":-Infinity}',
                   b'{"value":1e10000}', b'{"value":"\xff"}', b'{', b'[]', b'null',
                   b'{} {}']
        for data in invalid:
            with self.subTest(data=data):
                path.write_bytes(data)
                with self.assertRaises(contract.ContractError):
                    contract.load_document(path)
        path.write_bytes(b'{"finite":1.5}')
        self.assertEqual(contract.load_document(path), {"finite": 1.5})

    def test_json_size_bound_is_enforced_and_must_be_a_positive_integer(self):
        path = self.root / "parser-input.json"
        path.write_bytes(b'{}')
        self.assertEqual(contract.load_document(path, max_bytes=2), {})
        for maximum in (1, 0, -1, True, 2.0):
            with self.subTest(maximum=maximum), self.assertRaises(contract.ContractError):
                contract.load_document(path, max_bytes=maximum)

    def test_default_check_and_json_cli_are_read_only(self):
        for arguments in ([], ["--check"], ["--check", "--json"]):
            with self.subTest(arguments=arguments):
                result = self.cli(arguments, 0)
                if "--json" in arguments:
                    summary = json.loads(result.stdout)
                    self.assertEqual(summary["scope"], "source_present")
                    self.assertIs(summary["execution_available"], False)
                    self.assertIs(summary["gpu_execution_claimed"], False)
                else:
                    self.assertIn("no GPU execution", result.stdout)

    def test_failed_cli_check_does_not_repair_missing_or_corrupt_manifest(self):
        self.manifest_path.unlink()
        self.cli(["--check", "--json"], 1)
        self.assertFalse(self.manifest_path.exists())
        self.manifest_path.write_bytes(b'{"schema_version":1,"schema_version":1}')
        self.assertIn("duplicate JSON key", self.cli([], 1).stderr)
        self.write_json(self.manifest_path, self.manifest)
        document = deepcopy(self.manifest)
        document["graph"][0]["placement"] = "host"
        self.write_json(self.manifest_path, document)
        self.cli(["--check"], 1)

    def test_manifest_write_is_explicit_and_refreshes_only_the_fixed_contract(self):
        source = self.root / "sw/runtime/ai/mlp_host.cpp"
        source.write_bytes(source.read_bytes() + b"\n// reviewed identity-only change\n")
        self.cli([], 1)
        result = self.cli(["--write-manifest"], 0, readonly=False)
        self.assertIn("no execution acceptance", result.stdout)
        refreshed = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        changed = [entry for entry in refreshed["artifacts"] if entry not in self.manifest["artifacts"]]
        self.assertEqual([entry["path"] for entry in changed], ["sw/runtime/ai/mlp_host.cpp"])
        self.assertEqual(refreshed["graph"], self.manifest["graph"])
        self.assertEqual(refreshed["execution_acceptances"], {"P04-A02": "not_run", "P04-A03": "not_run"})
        self.cli(["--check"], 0)

    def test_manifest_write_cannot_bless_altered_reference(self):
        document = deepcopy(self.fixture)
        document["cases"][0]["output_words"][0] = "00000000"
        self.assertNotEqual(document, self.fixture)
        self.rehash_fixture(document)
        self.cli(["--write-manifest"], 1)

    def test_manifest_write_cannot_bless_unsupported_operator_or_profile(self):
        path = self.root / "ci/project/p03_operator_manifest.json"
        operators = json.loads(path.read_text(encoding="utf-8"))
        operators["operators"][0]["signature"]["shape_tuples"].append([16, 4, 8])
        self.write_json(path, operators)
        self.cli(["--write-manifest"], 1)
        shutil.copy2(ROOT / "ci/project/p03_operator_manifest.json", path)
        profile_path = self.root / "profiles/p02-tfr.json"
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        profile["core"]["VX_CFG_TCU_TYPE"] = "DPI"
        self.write_json(profile_path, profile)
        self.cli(["--write-manifest"], 1)

    def test_profile_requires_native_fp16_bank(self):
        self.reject_profile(lambda doc: doc["core"].update(VX_CFG_TCU_FP16_ENABLE=False))

    def test_profile_requires_local_memory(self):
        self.reject_profile(lambda doc: doc["core"].update(VX_CFG_LMEM_ENABLE=False))

    def test_profile_requires_accepted_pe_ratio(self):
        self.reject_profile(lambda doc: doc["core"].update(VX_CFG_TCU_PE_RATIO=2))

    def test_profile_cannot_add_local_memory_size_override(self):
        self.reject_profile(lambda doc: doc["core"].update(VX_CFG_LMEM_SIZE=8192))

    def test_profile_rejects_forbidden_native_format_bank(self):
        self.reject_profile(lambda doc: doc["core"].update(VX_CFG_TCU_TF32_ENABLE=True))

    def test_profile_rejects_unknown_or_additional_override_scopes(self):
        mutations = (
            ("core", lambda doc: doc["core"].update(VX_CFG_UNREVIEWED_OVERRIDE=1)),
            ("chip", lambda doc: doc["chip"].update(VX_CFG_UNREVIEWED_OVERRIDE=1)),
            ("top_level", lambda doc: doc.update(VX_CFG_LMEM_SIZE=8192)),
            ("platform", lambda doc: doc.update(platform={"VX_CFG_LMEM_ENABLE": False})),
            ("extends", lambda doc: doc.update(extends="unreviewed-profile")),
        )
        for scope, mutate in mutations:
            with self.subTest(scope=scope):
                self.reject_profile(mutate)

    def test_profile_rejects_boolean_integer_substitutions(self):
        mutations = (
            ("fp16_integer", lambda doc: doc["core"].update(VX_CFG_TCU_FP16_ENABLE=1)),
            ("tf32_integer", lambda doc: doc["core"].update(VX_CFG_TCU_TF32_ENABLE=0)),
            ("pe_ratio_boolean", lambda doc: doc["core"].update(VX_CFG_TCU_PE_RATIO=True)),
            ("dsp_boolean", lambda doc: doc["core"].update(VX_CFG_TCU_USE_DSP=False)),
            ("core_count_boolean", lambda doc: doc["chip"].update(VX_CFG_NUM_CORES=True)),
        )
        for field, mutate in mutations:
            with self.subTest(field=field):
                self.reject_profile(mutate)

    def test_conflicting_cli_modes_never_write(self):
        self.cli(["--check", "--write-manifest"], 2)


if __name__ == "__main__":
    unittest.main()
