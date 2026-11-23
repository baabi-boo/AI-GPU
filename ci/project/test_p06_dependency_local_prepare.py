# SPDX-License-Identifier: Apache-2.0
"""Local preparation controls use synthetic observations, never execution evidence."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path, PurePosixPath
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import p06_dependency_contract as contract
import p06_dependency_local_prepare as prepare
import p06_local_toolchain as toolchain


def synthetic_toolchain(archive_root, tools_root):
    """Real reviewed lock metadata with invented installed-member observations."""
    manifest = toolchain._locked_manifest()
    parts = toolchain._selected_parts(manifest)
    members, tools = {}, {}
    for name, relative in toolchain.NATIVE_TOOLS.items():
        for parent in PurePosixPath(relative).parents:
            if str(parent) != ".":
                members[str(parent)] = {"path": str(parent), "kind": "directory"}
        digest = hashlib.sha256(relative.encode()).hexdigest()
        mode = 0o644 if name.startswith(("libc64/", "libcrt64/")) else 0o755
        members[relative] = {"path": relative, "kind": "file", "sha256": digest,
                             "size_bytes": len(relative), "mode": mode}
        path = str(PurePosixPath(tools_root) / relative)
        tools[name] = {"path": path, "resolved_path": path, "sha256": digest, "size_bytes": len(relative)}
    return {"schema_version": 1, "contract_id": toolchain.CONTRACT_ID, "origin": "local-pinned-archives",
        "outcome": "pass", "native_execution": "not_run", "archive_root": str(archive_root),
        "tools_root": str(tools_root), **{name: manifest[name] for name in ("repository", "tag", "revision", "os_bundle")},
        "manifest_sha256": manifest["sha256"], "manifest_size_bytes": manifest["size_bytes"],
        "manifest_semantic_sha256": toolchain.inventory.TOOLCHAIN_MANIFEST_SHA256,
        "selected_components": list(toolchain.COMPONENTS), "parts": parts,
        "members": [members[name] for name in sorted(members)], "tools": tools,
        "compressed_bytes": sum(row["size_bytes"] for row in parts),
        "extracted_regular_bytes": sum(row.get("size_bytes", 0) for row in members.values()),
        "member_count": len(members), "budget": dict(toolchain.BUDGET), "limitations": list(toolchain.LIMITATIONS),
        **dict.fromkeys(contract.FALSE_CLAIMS, False)}


def synthetic_preparation(root=Path("/synthetic-local"), revision="a" * 40, *, host_bin=None):
    """A complete inert schema fixture; it does not assert that any command ran."""
    source, workspace, archives, repositories_root = (root / name for name in ("source", "workspace", "archives", "repositories"))
    tool_root = workspace / "tools"
    repository_paths = {name: str(source / row["path"] if name in ("softfloat", "ramulator")
                                  else repositories_root / name) for name, row in contract.PINS.items()}
    source_manifest = json.loads((prepare.ROOT / "docs/project/evidence/p06-dependency-provenance/source-inputs/manifest.json").read_text())
    source_manifest["dependency_contract_sha256"] = contract.contract_hash()
    submodules = [
        {"path": name, "revision": "b" * 40, "status": "initialized"}
        for name in ("third_party/cocogfx", "third_party/cvfpu", "third_party/hardfloat")]
    submodules += [{"path": contract.PINS[name]["path"], "revision": contract.PINS[name]["revision"], "status": "initialized"}
                  for name in ("ramulator", "softfloat")]
    source_identity = {"revision": revision, "tree": "b" * 40, "dirty": False,
        "changed_paths": [], "untracked_paths": [], "submodules": {"entries": submodules, "declared_count": 5, "errors": []},
        "pins": {"VORTEX_VERSION": "3.0", "TOOLCHAIN_REV": "v3.0.2", "GEM5_REV": "v25.0.0.1",
                 "FIRESIM_REV": "57bb93f1e23daf46198659ddd93608f70121fee0"}, "blockers": [], "outcome": "pass",
        "inputs": [{"path": name, "sha256": hashlib.sha256(name.encode()).hexdigest(), "size_bytes": 1}
                   for name in prepare.SOURCE_INPUTS]}
    host_tools = {}
    for name in prepare.HOST_TOOLS:
        parent = "/synthetic-python/bin" if name == "python3" else (str(host_bin) if host_bin else "/usr/bin")
        path = parent + "/" + name
        host_tools[name] = {"path": path, "resolved_path": path,
                            "sha256": hashlib.sha256(name.encode()).hexdigest(), "size_bytes": 13}
    resources = {"free_disk_bytes": {"source": 30 * 2**30, "workspace": 30 * 2**30},
                 "available_memory_bytes": 8 * 2**30}
    return {"schema_version": 1, "contract_id": prepare.CONTRACT_ID, "execution_origin": "local",
        "dependency_contract_sha256": contract.contract_hash(), "expected_revision": revision,
        "outcome": "pass", "reason": None, "failures": [], "source_dir": str(source),
        "workspace_dir": str(workspace), "archive_root": str(archives), "dependency_repositories_root": str(repositories_root),
        "tools_dir": str(tool_root), "host_bin": str(host_bin) if host_bin else None, "host_tools": host_tools,
        "repositories": repository_paths, "source_manifest": source_manifest,
        "toolchain_receipt": synthetic_toolchain(archives, tool_root),
        "source_before": source_identity, "source_after": deepcopy(source_identity),
        "resources_before": resources, "resources_after": deepcopy(resources),
        "dependency_cache_used": False, "toolchain_cache_used": False, "network_acquisition": False,
        "native_execution": "not_run", "budget": dict(contract.BUDGET), "limitations": list(prepare.LIMITATIONS),
        **dict.fromkeys(contract.FALSE_CLAIMS, False)}


class LocalPreparationSchemaTests(unittest.TestCase):
    def setUp(self):
        self.document = synthetic_preparation()

    def validate(self, document=None):
        return prepare.validate_local_preparation(document or self.document, "a" * 40)

    def test_complete_synthetic_local_schema_passes_real_inert_validators(self):
        before = deepcopy(self.document)
        self.assertEqual(self.validate(), self.document)
        self.assertEqual(self.document, before)
        self.assertEqual(self.document["source_manifest"]["total_files"], 1294)
        self.assertEqual(self.document["native_execution"], "not_run")

    def test_explicit_host_bin_is_bound_in_the_schema(self):
        document = synthetic_preparation(host_bin=Path("/synthetic-host/bin"))
        self.assertEqual(self.validate(document)["host_bin"], "/synthetic-host/bin")
        document["host_bin"] = "/different-host/bin"
        with self.assertRaisesRegex(ValueError, "selected PATH"):
            self.validate(document)

    def test_unknown_fields_hosted_fields_and_missing_fields_are_rejected(self):
        for name, value in (("GITHUB_RUN_ID", "19"), ("toolchain_cache_key", "favorable-cache"), ("extra", 1)):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "fields differ"):
                self.validate(dict(self.document, **{name: value}))
        document = deepcopy(self.document)
        del document["source_manifest"]
        with self.assertRaisesRegex(ValueError, "fields differ"):
            self.validate(document)

    def test_origin_success_and_false_claims_cannot_be_forged(self):
        changes = {"schema_version": True, "execution_origin": "github", "contract_id": "other",
                   "outcome": "blocked", "expected_revision": "b" * 40, "dependency_contract_sha256": "0" * 64,
                   "reason": "earlier failure", "failures": [{"stage": "earlier", "reason": "failed"}],
                   "dependency_cache_used": True, "toolchain_cache_used": True, "network_acquisition": True,
                   "native_execution": "pass", **dict.fromkeys(contract.FALSE_CLAIMS, True)}
        for name, value in changes.items():
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.validate(dict(self.document, **{name: value}))

    def test_path_alias_traversal_and_overlapping_inputs_are_rejected(self):
        for name, value in (("source_dir", "/synthetic-local/source/../source"), ("archive_root", "/synthetic-local//archives"),
                            ("dependency_repositories_root", self.document["source_dir"]),
                            ("tools_dir", "/outside/tools"), ("host_bin", "/bin/$(id)")):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.validate(dict(self.document, **{name: value}))

    def test_pinned_source_and_archive_metadata_are_not_success_only_assertions(self):
        for mutate in (
            lambda data: data["source_manifest"]["sources"][0].__setitem__("tree", "0" * 40),
            lambda data: data["source_manifest"]["sources"].pop(),
            lambda data: data["toolchain_receipt"]["parts"][0].__setitem__("sha256", "0" * 64),
            lambda data: data["toolchain_receipt"].__setitem__("tools_root", "/another/tools"),
            lambda data: data["repositories"].__setitem__("spdlog", "/another/repository"),
        ):
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                document = deepcopy(self.document)
                mutate(document)
                self.validate(document)

    def test_missing_or_uninitialized_gitlinks_and_changed_checkout_are_rejected(self):
        for mutate in (
            lambda data: data["source_before"]["submodules"]["entries"][0].__setitem__("status", "not_initialized"),
            lambda data: data["source_before"]["submodules"]["entries"].pop(),
            lambda data: data["source_before"].__setitem__("dirty", True),
            lambda data: data["source_after"].__setitem__("tree", "c" * 40),
            lambda data: data["source_before"]["inputs"].pop(),
        ):
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                document = deepcopy(self.document)
                mutate(document)
                self.validate(document)

    def test_resource_and_budget_bounds_cannot_be_waived(self):
        for mutate in (
            lambda data: data["resources_before"]["free_disk_bytes"].__setitem__("source", 15 * 2**30 - 1),
            lambda data: data["resources_after"].__setitem__("available_memory_bytes", 4 * 2**30 - 1),
            lambda data: data["budget"].__setitem__("min_free_bytes", 1),
            lambda data: data["budget"].__setitem__("simulation_workers", True),
        ):
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                document = deepcopy(self.document)
                mutate(document)
                self.validate(document)

    def test_validation_never_opens_resolves_or_executes_producer_paths(self):
        locked = toolchain._locked_manifest()
        with mock.patch.object(toolchain, "_locked_manifest", return_value=locked), \
                mock.patch.object(Path, "open", side_effect=AssertionError("producer file opened")), \
                mock.patch.object(Path, "resolve", side_effect=AssertionError("producer path resolved")), \
                mock.patch.object(prepare, "_git", side_effect=AssertionError("Git executed")), \
                mock.patch.object(toolchain, "provision", side_effect=AssertionError("archive extracted")):
            self.validate()


class LocalPreparationExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="p06-local-prepare-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.fixture = synthetic_preparation(self.root)
        self.source, self.workspace, self.archives, self.repositories = (
            Path(self.fixture[name]) for name in ("source_dir", "workspace_dir", "archive_root", "dependency_repositories_root"))
        for directory in (self.source, self.workspace, self.archives, self.repositories):
            directory.mkdir()
        for path in self.fixture["repositories"].values():
            Path(path).mkdir(parents=True, exist_ok=True)
        self.args = SimpleNamespace(source_dir=self.source, workspace_dir=self.workspace,
            expected_revision="a" * 40, archive_root=self.archives,
            dependency_repositories=self.repositories, host_bin=None)
        self.status = b""
        self.calls = []
        patches = {
            "root": mock.patch.object(prepare, "ROOT", self.source),
            "source": mock.patch.object(prepare, "collect_source", side_effect=lambda _: deepcopy(self.fixture["source_before"])),
            "resources": mock.patch.object(prepare, "_resources", side_effect=lambda *_: deepcopy(self.fixture["resources_before"])),
            "objects": mock.patch.object(prepare, "_source_inventory", side_effect=lambda _: deepcopy(self.fixture["source_manifest"])),
            "tools": mock.patch.object(prepare, "_host_tools", side_effect=lambda _: deepcopy(self.fixture["host_tools"])),
            "git": mock.patch.object(prepare, "_git", side_effect=self.git),
            "provision": mock.patch.object(toolchain, "provision", side_effect=self.provision),
        }
        self.mocks = {}
        for name, patch in patches.items():
            self.mocks[name] = patch.start()
            self.addCleanup(patch.stop)

    def git(self, root, *args):
        if args[:3] == ("ls-tree", "-z", "HEAD"):
            pin = next(row for row in contract.PINS.values() if row["path"] == args[-1])
            return ("160000 commit " + pin["revision"] + "\t" + pin["path"] + "\0").encode()
        if args == ("rev-parse", "HEAD"):
            name = next(name for name in ("softfloat", "ramulator") if root == self.source / contract.PINS[name]["path"])
            return (contract.PINS[name]["revision"] + "\n").encode()
        if args == ("status", "--porcelain=v1", "--untracked-files=all", "--ignored"):
            return self.status
        raise AssertionError("Unexpected Git observation: " + repr(args))

    def provision(self, archive_root, tools_root):
        self.calls.append((archive_root, tools_root))
        tools_root.mkdir()
        return deepcopy(self.fixture["toolchain_receipt"])

    def run_prepare(self):
        result = prepare.prepare(self.args)
        retained = json.loads((self.workspace / "evidence/dependency-preparation.json").read_text())
        self.assertEqual(result, retained)
        self.assertEqual(result["native_execution"], "not_run")
        self.assertTrue(all(result[name] is False for name in contract.FALSE_CLAIMS))
        return result

    def test_complete_local_preparation_retains_exact_source_tool_and_origin_joins(self):
        result = self.run_prepare()
        self.assertEqual(result["outcome"], "pass", result["reason"])
        self.assertEqual(self.calls, [(self.archives, self.workspace / "tools")])
        self.assertEqual(result["source_before"], result["source_after"])
        self.assertEqual(result["source_manifest"], self.fixture["source_manifest"])
        self.assertEqual(result["host_tools"], self.fixture["host_tools"])
        self.assertEqual(self.mocks["objects"].call_count, 2)
        self.assertEqual(self.mocks["tools"].call_count, 2)

    def test_wrong_source_and_dirty_source_are_retained_before_provision(self):
        self.args.expected_revision = "c" * 40
        result = self.run_prepare()
        self.assertEqual(result["outcome"], "blocked")
        self.assertIn("expected revision", result["reason"])
        self.mocks["provision"].assert_not_called()

    def test_dirty_source_rejects_before_provision(self):
        self.fixture["source_before"]["dirty"] = True
        self.assertIn("clean source", self.run_prepare()["reason"])
        self.mocks["provision"].assert_not_called()

    def test_existing_tool_destination_is_preserved_and_rejected(self):
        (self.workspace / "tools").mkdir()
        marker = self.workspace / "tools/existing"
        marker.write_bytes(b"do not delete")
        self.assertIn("must be fresh", self.run_prepare()["reason"])
        self.assertEqual(marker.read_bytes(), b"do not delete")
        self.mocks["provision"].assert_not_called()

    def test_existing_dependency_product_is_preserved_and_rejected(self):
        product = self.source / contract.PRODUCTS["ramulator"]
        product.write_bytes(b"cached dependency")
        self.assertIn("pre-existing dependency product", self.run_prepare()["reason"])
        self.assertEqual(product.read_bytes(), b"cached dependency")
        self.mocks["provision"].assert_not_called()

    def test_existing_fetched_headers_and_ignored_submodule_cache_reject(self):
        (self.source / contract.PINS["spdlog"]["path"]).mkdir(parents=True)
        self.assertIn("pre-existing fetched", self.run_prepare()["reason"])
        self.mocks["provision"].assert_not_called()

    def test_ignored_source_products_reject_before_tool_provision(self):
        self.status = b"!! build/CMakeCache.txt\n"
        self.assertIn("changed, untracked or ignored", self.run_prepare()["reason"])
        self.mocks["provision"].assert_not_called()

    def test_insufficient_resources_retain_blocked_attempt(self):
        self.fixture["resources_before"]["available_memory_bytes"] = 4 * 2**30 - 1
        self.assertIn("4 GiB available RAM", self.run_prepare()["reason"])
        self.mocks["provision"].assert_not_called()

    def test_changed_tools_after_extraction_cannot_become_pass(self):
        changed = deepcopy(self.fixture["host_tools"])
        changed["g++"]["sha256"] = "0" * 64
        self.mocks["tools"].side_effect = [deepcopy(self.fixture["host_tools"]), changed]
        result = self.run_prepare()
        self.assertEqual(result["outcome"], "fail")
        self.assertIn("host tools changed", result["reason"])
        self.assertIsNotNone(result["toolchain_receipt"])

    def test_changed_source_objects_after_extraction_cannot_become_pass(self):
        changed = deepcopy(self.fixture["source_manifest"])
        changed["total_size_bytes"] += 1
        self.mocks["objects"].side_effect = [deepcopy(self.fixture["source_manifest"]), changed]
        result = self.run_prepare()
        self.assertEqual(result["outcome"], "fail")
        self.assertIn("source objects changed", result["reason"])

    def test_extraction_failure_is_retained_without_inventing_native_execution(self):
        self.mocks["provision"].side_effect = ValueError("archive bytes differ from the immutable lock")
        result = self.run_prepare()
        self.assertEqual(result["outcome"], "fail")
        self.assertEqual(result["failures"], [{"stage": "local-preparation", "reason": result["reason"]}])
        self.assertIsNone(result["toolchain_receipt"])

    def test_existing_receipt_is_not_overwritten(self):
        self.run_prepare()
        target = self.workspace / "evidence/dependency-preparation.json"
        original = target.read_bytes()
        with self.assertRaisesRegex(ValueError, "receipt already exists"):
            prepare.prepare(self.args)
        self.assertEqual(target.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
