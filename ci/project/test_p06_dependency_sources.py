# SPDX-License-Identifier: Apache-2.0
"""Locked materialization and filesystem-substitution controls with tiny Git trees."""

import copy
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import p06_dependency_contract as contract
import p06_dependency_sources as sources


def git(root, *arguments):
    environment = {"PATH": os.defpath, "LANG": "C", "LC_ALL": "C",
        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "Fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid"}
    return subprocess.run(["git", "-C", str(root), *arguments], env=environment,
                          check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=10).stdout.decode("ascii").strip()


class DependencySourcesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="p06-dependency-sources-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.repositories, pins = {}, copy.deepcopy(contract.PINS)
        for name in sorted(pins):
            repository = self.root / ("git-" + name)
            repository.mkdir()
            git(repository, "init", "--quiet")
            (repository / "input.h").write_text("input for " + name + "\n")
            (repository / "run.sh").write_text("#!/bin/sh\nexit 97\n")
            (repository / "run.sh").chmod(0o755)
            if name == "softfloat":
                platform = repository / "build/Linux-x86_64-GCC/platform.h"
                platform.parent.mkdir(parents=True)
                platform.write_text("platform\n")
            if name == "yaml-cpp":
                document = repository / "docs/How-To-Parse-A-Document-(Old-API).md"
                document.parent.mkdir()
                document.write_text("Pinned literal parentheses are inert file names.\n")
            git(repository, "add", "--all")
            git(repository, "commit", "--quiet", "-m", "source fixture")
            pins[name]["revision"] = git(repository, "rev-parse", "HEAD")
            pins[name]["tree"] = git(repository, "rev-parse", "HEAD^{tree}")
            self.repositories[name] = repository
        self.lock = pins
        patcher = mock.patch.object(contract, "PINS", pins)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.destination = self.root / "sources"

    def materialize(self):
        return sources.materialize_sources(self.repositories, self.destination)

    def generated(self, name, body=b"new object\n"):
        target = self.destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        return {"path": name, "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)}

    def test_complete_regular_trees_are_relocated_with_original_modes_and_bytes(self):
        manifest = self.materialize()
        self.assertEqual([row["name"] for row in manifest["sources"]], sorted(self.lock))
        self.assertEqual(manifest["total_files"], 12)
        self.assertEqual(manifest, sources.validate_manifest(manifest))
        for component in manifest["sources"]:
            for row in component["files"]:
                path = self.destination / component["name"] / row["path"]
                self.assertEqual(path.read_bytes(),
                                 (self.repositories[component["name"]] / row["path"]).read_bytes())
                self.assertEqual(path.stat().st_mode & 0o777,
                                 0o755 if row["mode"] == "100755" else 0o644)
        other = self.root / "relocated"
        self.destination.rename(other)
        result = sources.verify_sources(manifest, other)
        self.assertEqual(result["manifest_sha256"], contract.digest(manifest))
        self.assertEqual(result["generated_files"], 0)

    def test_literal_parentheses_do_not_admit_traversal_or_shell_expansion(self):
        literal = "yaml-cpp/docs/How-To-Parse-A-Document-(Old-API).md"
        self.assertEqual(sources._relative(literal), literal)
        for name in ("../escape", "yaml-cpp/../escape", "yaml-cpp//file", "/absolute",
                     "yaml-cpp/$(touch-marker)", "yaml-cpp/`touch-marker`",
                     "yaml-cpp/document;touch-marker", "yaml-cpp/file\nname", "yaml-cpp/.git/config"):
            with self.subTest(name=name), self.assertRaises(sources.SourceError):
                sources._relative(name)

    def test_historical_exporter_keeps_its_original_selected_path_grammar(self):
        reader = sources.GitObjects(self.repositories["yaml-cpp"], self.lock["yaml-cpp"]["revision"])
        with self.assertRaises(ValueError):
            reader.blob("docs/How-To-Parse-A-Document-(Old-API).md")
        manifest = self.materialize()
        self.assertIn("docs/How-To-Parse-A-Document-(Old-API).md",
                      [row["path"] for source in manifest["sources"] if source["name"] == "yaml-cpp"
                       for row in source["files"]])

    def test_checkout_mutations_and_ignored_old_products_never_enter_materialization(self):
        repository = self.repositories["softfloat"]
        (repository / "input.h").write_text("uncommitted replacement\n")
        (repository / "build/Linux-x86_64-GCC/stale.o").write_bytes(b"stale object")
        (repository / "ignored.h").write_text("untracked replacement\n")
        self.materialize()
        self.assertEqual((self.destination / "softfloat/input.h").read_text(), "input for softfloat\n")
        self.assertFalse((self.destination / "softfloat/ignored.h").exists())
        self.assertFalse((self.destination / "softfloat/build/Linux-x86_64-GCC/stale.o").exists())

    def test_existing_destination_is_rejected_without_overwriting_inputs(self):
        self.destination.mkdir()
        sentinel = self.destination / "keep"
        sentinel.write_bytes(b"original")
        with self.assertRaisesRegex(sources.SourceError, "must be fresh"):
            self.materialize()
        self.assertEqual(sentinel.read_bytes(), b"original")

    def test_repository_inventory_must_be_exact(self):
        for missing in (True, False):
            repositories = dict(self.repositories)
            if missing:
                del repositories["argparse"]
            else:
                repositories["extra"] = repositories["argparse"]
            with self.subTest(missing=missing), self.assertRaisesRegex(sources.SourceError, "only five"):
                sources.materialize_sources(repositories, self.destination)
        self.assertFalse(self.destination.exists())

    def test_wrong_selected_tree_rejects_before_creating_destination(self):
        self.lock["softfloat"]["tree"] = "0" * 40
        with self.assertRaisesRegex(sources.SourceError, "locked root tree"):
            self.materialize()
        self.assertFalse(self.destination.exists())

    def test_wrong_commit_rejects_without_falling_back_to_checkout_head(self):
        self.lock["softfloat"]["revision"] = "1" * 40
        with self.assertRaises(ValueError):
            self.materialize()
        self.assertFalse(self.destination.exists())

    def test_committed_symlink_and_gitlink_are_not_materialized(self):
        repository = self.repositories["argparse"]
        (repository / "link.h").symlink_to("input.h")
        git(repository, "add", "link.h")
        git(repository, "commit", "--quiet", "-m", "symlink fixture")
        self.lock["argparse"].update(revision=git(repository, "rev-parse", "HEAD"),
                                     tree=git(repository, "rev-parse", "HEAD^{tree}"))
        with self.assertRaisesRegex(sources.SourceError, "symlink or gitlink"):
            self.materialize()
        git(repository, "rm", "link.h")
        git(repository, "update-index", "--add", "--cacheinfo",
            "160000," + self.lock["argparse"]["revision"] + ",nested")
        git(repository, "commit", "--quiet", "-m", "gitlink fixture")
        self.lock["argparse"].update(revision=git(repository, "rev-parse", "HEAD"),
                                     tree=git(repository, "rev-parse", "HEAD^{tree}"))
        with self.assertRaisesRegex(sources.SourceError, "symlink or gitlink"):
            self.materialize()
        self.assertFalse(self.destination.exists())

    def test_symlinked_destination_parent_is_rejected_without_external_writes(self):
        external = self.root / "external"
        external.mkdir()
        alias = self.root / "alias"
        alias.symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(sources.SourceError, "symlink"):
            sources.materialize_sources(self.repositories, alias / "sources")
        self.assertEqual(list(external.iterdir()), [])

    def test_symlinked_repository_is_rejected(self):
        alias = self.root / "alias"
        alias.symlink_to(self.repositories["argparse"], target_is_directory=True)
        self.repositories["argparse"] = alias
        with self.assertRaisesRegex(sources.SourceError, "symlink"):
            self.materialize()

    def test_destination_cannot_overlap_acquisition_repository(self):
        with self.assertRaisesRegex(sources.SourceError, "overlaps"):
            sources.materialize_sources(self.repositories, self.repositories["argparse"] / "output")

    def test_explicit_object_depfile_and_ramulator_product_are_supported(self):
        manifest = self.materialize()
        rows = [self.generated(name) for name in (
            "softfloat/build/Linux-x86_64-GCC/add.o",
            "softfloat/build/Linux-x86_64-GCC/add.o.d",
            "softfloat/build/Linux-x86_64-GCC/add.o.p06-before.d",
            "softfloat/build/Linux-x86_64-GCC/softfloat.a",
            "ramulator/libramulator.so")]
        result = sources.verify_sources(manifest, self.destination, generated_files=rows)
        self.assertEqual(result["generated_files"], 5)
        self.assertEqual(result["generated_bytes"], sum(row["size_bytes"] for row in rows))
        self.assertEqual(result, sources.verify_sources(manifest, self.destination, generated_files=rows[::-1]))

    def test_unlisted_stale_object_and_unexpected_empty_directory_are_rejected(self):
        manifest = self.materialize()
        row = self.generated("softfloat/build/Linux-x86_64-GCC/stale.o")
        with self.assertRaisesRegex(sources.SourceError, "unexpected source-root file"):
            sources.verify_sources(manifest, self.destination)
        (self.destination / row["path"]).unlink()
        (self.destination / "ramulator/build").mkdir()
        with self.assertRaisesRegex(sources.SourceError, "unexpected source directory"):
            sources.verify_sources(manifest, self.destination)

    def test_explicit_generated_list_cannot_authorize_injected_source(self):
        manifest = self.materialize()
        for name in ("ramulator/new.cpp", "softfloat/build/Linux-x86_64-GCC/replace.h",
                     "yaml-cpp/new.o", "ramulator/CMakeCache.txt"):
            row = self.generated(name)
            with self.subTest(name=name), self.assertRaisesRegex(sources.SourceError, "output grammar"):
                sources.verify_sources(manifest, self.destination, generated_files=[row])
            (self.destination / name).unlink()

    def test_generated_duplicates_and_product_substitution_are_rejected(self):
        manifest = self.materialize()
        row = self.generated("ramulator/libramulator.so")
        with self.assertRaisesRegex(sources.SourceError, "duplicates"):
            sources.verify_sources(manifest, self.destination, generated_files=[row, row])
        (self.destination / row["path"]).write_bytes(b"other product\n")
        with self.assertRaisesRegex(sources.SourceError, "product changed"):
            sources.verify_sources(manifest, self.destination, generated_files=[row])

    def test_changed_source_bytes_mode_or_missing_source_reject(self):
        manifest = self.materialize()
        target = self.destination / "ramulator/input.h"
        original = target.read_bytes()
        target.write_bytes(b"replacement\n")
        with self.assertRaisesRegex(sources.SourceError, "source changed"):
            sources.verify_sources(manifest, self.destination)
        target.write_bytes(original)
        target.chmod(0o755)
        with self.assertRaisesRegex(sources.SourceError, "mode changed"):
            sources.verify_sources(manifest, self.destination)
        target.unlink()
        with self.assertRaisesRegex(sources.SourceError, "incomplete"):
            sources.verify_sources(manifest, self.destination)

    def test_regular_source_replacement_by_symlink_hardlink_or_fifo_rejects(self):
        manifest = self.materialize()
        target = self.destination / "ramulator/input.h"
        original = target.read_bytes()
        outside = self.root / "other.h"
        outside.write_bytes(original)
        for kind in ("symlink", "hardlink", "fifo"):
            target.unlink()
            if kind == "symlink":
                target.symlink_to(outside)
            elif kind == "hardlink":
                os.link(outside, target)
            else:
                os.mkfifo(target)
            with self.subTest(kind=kind), self.assertRaisesRegex(sources.SourceError, "symlink, special file or hard link"):
                sources.verify_sources(manifest, self.destination)
            target.unlink()
            target.write_bytes(original)

    def test_verification_rejects_symlinked_source_root(self):
        manifest = self.materialize()
        alias = self.root / "source-alias"
        alias.symlink_to(self.destination, target_is_directory=True)
        with self.assertRaisesRegex(sources.SourceError, "symlink"):
            sources.verify_sources(manifest, alias)

    def test_manifest_omission_reordering_duplicate_and_mode_change_reject(self):
        manifest = self.materialize()
        for mutation in ("omit", "reorder", "duplicate", "mode"):
            changed = copy.deepcopy(manifest)
            rows = changed["sources"][0]["files"]
            if mutation == "omit":
                rows.pop()
            elif mutation == "reorder":
                rows.reverse()
            elif mutation == "duplicate":
                rows.append(copy.deepcopy(rows[-1]))
            else:
                rows[0]["mode"] = "100755"
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                sources.validate_manifest(changed)

    def test_coherently_rehashed_substitution_still_must_match_git_blob_and_tree(self):
        manifest = self.materialize()
        changed = copy.deepcopy(manifest)
        source = changed["sources"][0]
        row = source["files"][0]
        body = b"coherently substituted source\n"
        (self.destination / source["name"] / row["path"]).write_bytes(body)
        changed["total_size_bytes"] += len(body) - row["size_bytes"]
        row.update(sha256=hashlib.sha256(body).hexdigest(), size_bytes=len(body))
        with self.assertRaisesRegex(sources.SourceError, "source changed"):
            sources.verify_sources(changed, self.destination)
        row["oid"] = hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()
        with self.assertRaisesRegex(sources.SourceError, "locked tree"):
            sources.validate_manifest(changed)

    def test_manifest_unknown_fields_boolean_sizes_and_changed_lock_reject(self):
        manifest = self.materialize()
        variants = []
        changed = copy.deepcopy(manifest)
        changed["unreviewed"] = True
        variants.append(changed)
        changed = copy.deepcopy(manifest)
        changed["sources"][0]["files"][0]["size_bytes"] = True
        variants.append(changed)
        changed = copy.deepcopy(manifest)
        changed["sources"][0]["revision"] = "0" * 40
        variants.append(changed)
        changed = copy.deepcopy(manifest)
        changed["dependency_contract_sha256"] = "0" * 64
        variants.append(changed)
        changed = copy.deepcopy(manifest)
        changed["schema_version"] = True
        variants.append(changed)
        for changed in variants:
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                sources.validate_manifest(changed)

    def test_unsafe_paths_and_prefix_collisions_reject_before_filesystem_reads(self):
        manifest = self.materialize()
        for name in ("../escape", "/absolute", "bad//path", ".git/config", "x\\y", "x\nname"):
            changed = copy.deepcopy(manifest)
            changed["sources"][0]["files"][0]["path"] = name
            with self.subTest(name=name), self.assertRaises(ValueError):
                sources.validate_manifest(changed)
        changed = copy.deepcopy(manifest)
        rows = changed["sources"][0]["files"]
        rows[0]["path"] = "a"
        rows[1]["path"] = "a/child"
        with self.assertRaisesRegex(ValueError, "prefix collision"):
            sources.validate_manifest(changed)

    def test_source_and_generated_byte_bounds_are_enforced(self):
        manifest = self.materialize()
        with mock.patch.object(contract, "MAX_SOURCE_BYTES", 1):
            changed = copy.deepcopy(manifest)
            changed["dependency_contract_sha256"] = contract.contract_hash()
            with self.assertRaisesRegex(sources.SourceError, "total bound"):
                sources.validate_manifest(changed)
        row = {"path": "ramulator/libramulator.so", "sha256": "0" * 64,
               "size_bytes": contract.MAX_FILE_BYTES + 1}
        with self.assertRaisesRegex(sources.SourceError, "identity is invalid"):
            sources.verify_sources(manifest, self.destination, generated_files=[row])

    def test_manifest_validator_is_inert_and_does_not_alias_input(self):
        manifest = self.materialize()
        with mock.patch.object(os, "open", side_effect=AssertionError("filesystem access")), \
                mock.patch.object(subprocess, "Popen", side_effect=AssertionError("execution")):
            validated = sources.validate_manifest(manifest)
        validated["sources"][0]["files"][0]["sha256"] = "0" * 64
        self.assertNotEqual(validated, manifest)


if __name__ == "__main__":
    unittest.main()
