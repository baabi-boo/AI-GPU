# SPDX-License-Identifier: Apache-2.0
"""Offline acquisition controls with tiny locked bytes and real inert Git objects."""

from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import zlib

import p06_qualified_warm_inputs as inputs


def git(root, *arguments):
    environment = {"PATH": os.defpath, "LANG": "C", "LC_ALL": "C",
        "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "Acquisition fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "Acquisition fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+0000", "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+0000"}
    return subprocess.run(["git", "-C", str(root), *arguments], env=environment,
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10).stdout.decode("ascii").strip()


def pinned_bytes(body):
    return {"sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)}


class FrozenAcquisitionPlanTests(unittest.TestCase):
    def test_production_selection_retains_exact_published_pins(self):
        plan = inputs.input_plan()
        toolchain = plan["toolchain"]
        self.assertEqual((toolchain["part_count"], toolchain["compressed_bytes"]), (15, 606992434))
        self.assertEqual(toolchain["revision"], "e3db4bcdf819a17f618ad9fc2472f8f7dea3192b")
        self.assertEqual(toolchain["repository"], "vortexgpgpu/vortex-toolchain-prebuilt")
        self.assertNotIn("verilator", toolchain["selected_components"])
        self.assertEqual(toolchain["parts"], sorted(toolchain["parts"], key=lambda row: row["path"]))
        self.assertEqual(plan["dependency_pins"], inputs.dependency.PINS)
        self.assertEqual(plan["originals"], {
            "diagnostic": {"size_bytes": 4290949,
                "sha256": "6d7673032857904468dc2e212d2583da0d2b72bf14885c335d77c159eb717efb"},
            "control": {"size_bytes": 47632218,
                "sha256": "d3a16e1e6e92a68414f5fdcce564b963dde2e9e801601191d52ceeb974faea6f"}})

    def test_file_limit_wrapper_enforces_exact_bytes_without_network_or_native_tools(self):
        with tempfile.TemporaryDirectory(prefix="p06-acquisition-fsize-") as directory:
            target = Path(directory) / "oversized.partial"
            command = [sys.executable, "-I", "-B", "-c", inputs._FILE_LIMIT_EXEC, "7",
                sys.executable, "-I", "-B", "-c",
                "import pathlib,sys; pathlib.Path(sys.argv[1]).write_bytes(b'x'*8)", str(target)]
            result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertLessEqual(target.stat().st_size, 7)

    def test_source_probes_ignore_caller_git_python_and_home_injection(self):
        with tempfile.TemporaryDirectory(prefix="p06-acquisition-probes-") as directory:
            root = Path(directory)
            source, child = root / "source", root / "child"
            for repository in (source, child):
                repository.mkdir()
                git(repository, "init", "--quiet", "--object-format=sha1", "--template=")
            (child / "input.h").write_text("inert submodule input\n")
            git(child, "add", "--all")
            git(child, "commit", "--quiet", "-m", "inert child")
            child_revision = git(child, "rev-parse", "HEAD")
            for name in inputs.inventory.SOURCE_INPUTS:
                target = source / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((inputs.ROOT / name).read_bytes())
            (source / ".gitmodules").write_text(
                '[submodule "fixture"]\n\tpath = third_party/fixture\n\turl = ../child\n')
            shutil.copytree(child, source / "third_party/fixture")
            git(source, "add", "--all")
            git(source, "commit", "--quiet", "-m", "inert source")
            git(source, "submodule", "init", "--", "third_party/fixture")
            revision = git(source, "rev-parse", "HEAD")
            (source / "visible-untracked").write_text("must remain visible\n")
            with mock.patch.dict(os.environ, inputs._environment(), clear=True):
                expected = inputs.inventory.collect_source(source)
            self.assertEqual(expected["untracked_paths"], ["visible-untracked"])
            self.assertEqual(expected["submodules"]["entries"], [{
                "path": "third_party/fixture", "revision": child_revision, "status": "initialized"}])
            marker = root / "caller-code-executed"
            injected = root / "injected"
            injected.mkdir()
            executable = injected / "git"
            executable.write_text("#!/bin/sh\nprintf invoked > '" + str(marker) + "'\nexit 97\n")
            executable.chmod(0o700)
            (injected / "sitecustomize.py").write_text(
                "from pathlib import Path\nPath(" + repr(str(marker)) + ").write_text('python startup')\n")
            (injected / "ignored").write_text("visible-untracked\n")
            (injected / ".gitconfig").write_text("[core]\n\texcludesFile = " + str(injected / "ignored") + "\n")
            hostile = {"PATH": str(injected), "HOME": str(injected), "PYTHONPATH": str(injected),
                       "GIT_DIR": str(child / ".git"), "GIT_WORK_TREE": str(child),
                       "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.bare",
                       "GIT_CONFIG_VALUE_0": "true", "LD_PRELOAD": str(injected / "absent.so")}
            with mock.patch.dict(os.environ, hostile):
                self.assertEqual(inputs.collect_source_isolated(source), expected)
                self.assertEqual(inputs.git_probe_isolated(source, "rev-parse", "HEAD"),
                                 (revision + "\n").encode())
                self.assertEqual({key: os.environ[key] for key in hostile}, hostile)
            self.assertFalse(marker.exists())


class QualifiedWarmInputAcquisitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture_directory = tempfile.TemporaryDirectory(prefix="p06-acquisition-git-fixtures-")
        cls.addClassCleanup(cls.fixture_directory.cleanup)
        cls.fixtures = Path(cls.fixture_directory.name).resolve()
        cls.frozen = inputs.input_plan()
        cls.pins = deepcopy(inputs.dependency.PINS)
        for name, pin in cls.pins.items():
            repository = cls.fixtures / name
            repository.mkdir()
            git(repository, "init", "--quiet", "--object-format=sha1", "--template=")
            (repository / "input.h").write_text("inert source for " + name + "\n")
            executable = repository / "never-run.sh"
            executable.write_text("#!/bin/sh\nexit 97\n")
            executable.chmod(0o755)
            git(repository, "add", "--all")
            git(repository, "commit", "--quiet", "-m", "inert source fixture")
            pin["revision"] = git(repository, "rev-parse", "HEAD")
            pin["tree"] = git(repository, "rev-parse", "HEAD^{tree}")

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="p06-qualified-inputs-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source = self.root / "source"
        self.source.mkdir()
        self.args = SimpleNamespace(source_dir=self.source, expected_revision="a" * 40,
            workspace_dir=self.root / "workspace", archive_root=self.root / "archives",
            dependency_repositories=self.root / "repositories", output_dir=self.root / "evidence",
            diagnostic_archive=self.root / "diagnostic.zip", control_archive=self.root / "control.zip")
        self.plan = deepcopy(self.frozen)
        self.plan["dependency_pins"] = deepcopy(self.pins)
        self.part_bodies = {}
        for index, row in enumerate(self.plan["toolchain"]["parts"]):
            body = ("inert locked archive part " + str(index) + "\n").encode()
            self.part_bodies[row["path"]] = body
            row.update(pinned_bytes(body), git_blob_sha=hashlib.sha1(
                b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest())
        self.plan["toolchain"]["compressed_bytes"] = sum(map(len, self.part_bodies.values()))
        for name in ("diagnostic", "control"):
            body = ("unchanged original " + name + "\n").encode()
            getattr(self.args, name + "_archive").write_bytes(body)
            self.plan["originals"][name] = pinned_bytes(body)
        for name in ("softfloat", "ramulator"):
            shutil.copytree(self.fixtures / name, self.source / self.pins[name]["path"])
        self.checkout = {"revision": self.args.expected_revision, "tree": "b" * 40,
                         "dirty": False, "blockers": [], "pins": {"TOOLCHAIN_REV": "v3.0.2"}}
        self.observed = []
        self.status = b""
        self.enterContext(mock.patch.object(inputs, "ROOT", self.source))
        self.enterContext(mock.patch.object(inputs.dependency, "PINS", deepcopy(self.pins)))
        self.plan_mock = self.enterContext(mock.patch.object(inputs, "input_plan", side_effect=lambda _: deepcopy(self.plan)))
        self.source_mock = self.enterContext(mock.patch.object(inputs, "collect_source_isolated", side_effect=lambda _: deepcopy(self.checkout)))
        self.enterContext(mock.patch.object(inputs, "git_probe_isolated", side_effect=self.source_git))
        self.disk_mock = self.enterContext(mock.patch.object(inputs.shutil, "disk_usage",
            return_value=SimpleNamespace(free=inputs.dependency.BUDGET["min_free_bytes"] + 1024**3)))
        self.memory_mock = self.enterContext(mock.patch.object(inputs, "available_memory_bytes",
            return_value=inputs.dependency.BUDGET["max_rss_bytes"]))
        self.run_mock = self.enterContext(mock.patch.object(inputs, "run_bounded", side_effect=self.command))
        self.provision_mock = self.enterContext(mock.patch.object(inputs.toolchain, "provision",
            side_effect=AssertionError("acquisition must not provision tools")))

    def source_git(self, root, *arguments):
        if arguments[:3] == ("ls-tree", "-z", "HEAD"):
            pin = next(row for row in inputs.dependency.PINS.values() if row["path"] == arguments[-1])
            return ("160000 commit " + pin["revision"] + "\t" + pin["path"] + "\0").encode()
        if arguments == ("rev-parse", "HEAD"):
            name = next(name for name in ("softfloat", "ramulator")
                        if root == self.source / inputs.dependency.PINS[name]["path"])
            return (inputs.dependency.PINS[name]["revision"] + "\n").encode()
        if arguments == ("status", "--porcelain=v1", "--untracked-files=all", "--ignored"):
            return self.status
        raise AssertionError("unexpected source Git observation")

    def command(self, argv, cwd, environment, log, **limits):
        self.observed.append((argv, cwd, dict(environment), limits))
        if "init" in argv:
            Path(argv[-1]).mkdir()
        elif "fetch" in argv:
            directory = Path(argv[argv.index("-C") + 1])
            shutil.copytree(self.fixtures / directory.name / ".git", directory / ".git")
        elif "--url" in argv:
            destination = Path(argv[argv.index("--output") + 1])
            relative = destination.relative_to(self.args.archive_root).as_posix().removesuffix(".partial")
            destination.write_bytes(self.part_bodies[relative])
        else:
            raise AssertionError("unexpected acquisition command")
        log.write_bytes(b"200\n" if "--url" in argv else b"inert fixture acquisition\n")
        return {"process_started": True, "outcome": "pass", "exit_code": 0,
                "reason": None, "cleanup_complete": True, "duration_seconds": 0.0,
                "log_size_bytes": log.stat().st_size, "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest()}

    def acquire(self):
        result = inputs.acquire(self.args)
        receipt = self.args.output_dir / inputs.RECEIPT_NAME
        self.assertEqual(receipt.read_bytes(), inputs.base._json_bytes(result))
        self.assertEqual(json.loads(receipt.read_bytes()), result)
        self.assertEqual(result["state"], "finished")
        self.assertFalse(self.args.workspace_dir.exists())
        self.assertEqual(result["native_execution"], "not_run")
        self.assertIs(result["retained_code_executed"], False)
        for name in (*inputs.dependency.FALSE_CLAIMS, "counter_qualification_passed", "qualified_warm_passed",
                     "toolchain_cache_used", "dependency_cache_used"):
            self.assertIs(result[name], False)
        self.provision_mock.assert_not_called()
        return result

    def test_acquires_exact_objects_and_parts_without_changing_originals_or_source(self):
        original_bytes = {name: getattr(self.args, name + "_archive").read_bytes()
                          for name in ("diagnostic", "control")}
        result = self.acquire()
        self.assertEqual(result["outcome"], "pass")
        self.assertEqual(len(result["commands"]), 21)
        self.assertEqual(set(result["repositories"]), set(self.pins))
        self.assertEqual(result["source_manifest"]["total_files"], 10)
        self.assertEqual(result["source_before"], result["source_after"])
        self.assertIs(result["network_acquisition"], True)
        self.assertEqual(len(result["parts"]), 15)
        self.assertTrue(all(row["state"] == "verified" for row in result["parts"]))
        for relative, body in self.part_bodies.items():
            self.assertEqual((self.args.archive_root / relative).read_bytes(), body)
            self.assertFalse((self.args.archive_root / (relative + ".partial")).exists())
        for name, body in original_bytes.items():
            self.assertEqual(getattr(self.args, name + "_archive").read_bytes(), body)
        for name in inputs.FETCHED_NAMES:
            self.assertFalse((self.source / self.pins[name]["path"]).exists())
            self.assertFalse((self.args.dependency_repositories / name / "never-run.sh").exists())
        expected = inputs.dependency.digest({"expected_revision": self.args.expected_revision,
            "plan": self.plan, "source_manifest_sha256": inputs.dependency.digest(result["source_manifest"])})
        self.assertEqual(result["input_identity_sha256"], expected)

    def test_commands_use_public_immutable_urls_no_user_configuration_and_fixed_budgets(self):
        secret = "https://user:private-token@proxy.invalid/"
        with mock.patch.dict(os.environ, {"HTTPS_PROXY": secret, "GITHUB_TOKEN": "private-token",
                                         "GIT_CONFIG_COUNT": "1", "CURL_HOME": "/untrusted"}):
            result = self.acquire()
        self.assertEqual(result["outcome"], "pass")
        self.assertNotIn("private-token", json.dumps(result))
        fetches, transfers = [], []
        for argv, cwd, environment, limits in self.observed:
            self.assertEqual(environment, inputs._environment())
            self.assertNotIn("HTTPS_PROXY", environment)
            self.assertNotIn("GITHUB_TOKEN", environment)
            self.assertEqual(limits["timeout_seconds"], 120)
            self.assertEqual(limits["min_free_bytes"], 15 * 1024**3)
            self.assertEqual(limits["max_rss_bytes"], 4 * 1024**3)
            self.assertEqual(limits["max_log_bytes"], 16 * 1024**2)
            if "fetch" in argv:
                fetches.append(argv[-2:])
                self.assertIn("http.followRedirects=false", argv)
                self.assertIn("fetch.fsckObjects=true", argv)
                self.assertIn("credential.helper=", argv)
                self.assertIn("--depth=1", argv)
                self.assertIn("--no-recurse-submodules", argv)
            if "--url" in argv:
                transfers.append(argv)
                self.assertEqual(argv[1:5], ["-I", "-B", "-c", inputs._FILE_LIMIT_EXEC])
                self.assertEqual(argv[7], "--disable")
                self.assertIn("--fail", argv)
                self.assertNotIn("--location", argv)
                self.assertNotIn("--insecure", argv)
                self.assertEqual(argv[5], argv[argv.index("--max-filesize") + 1])
                self.assertEqual(argv[-1].split("/")[2], "raw.githubusercontent.com")
                self.assertIn("/" + self.plan["toolchain"]["revision"] + "/", argv[-1])
        self.assertEqual(fetches, [[self.pins[name]["url"], self.pins[name]["revision"]]
                                   for name in inputs.FETCHED_NAMES])
        self.assertEqual(len(transfers), 15)

    def test_archive_mismatch_preserves_partial_and_does_not_install_or_continue(self):
        first = self.plan["toolchain"]["parts"][0]
        self.part_bodies[first["path"]] = b"X" * first["size_bytes"]
        result = self.acquire()
        self.assertEqual(result["outcome"], "fail")
        self.assertIn("immutable", result["reason"])
        self.assertEqual(len(self.observed), 7)
        self.assertEqual(result["parts"][0]["state"], "acquiring")
        self.assertFalse((self.args.archive_root / first["path"]).exists())
        self.assertEqual((self.args.archive_root / (first["path"] + ".partial")).read_bytes(),
                         self.part_bodies[first["path"]])

    def test_git_blob_hash_is_checked_independently_of_raw_sha256(self):
        self.plan["toolchain"]["parts"][0]["git_blob_sha"] = "0" * 40
        result = self.acquire()
        self.assertEqual(result["outcome"], "fail")
        self.assertIn("Git blob", result["reason"])

    def test_oversized_partial_is_rejected_and_retained(self):
        first = self.plan["toolchain"]["parts"][0]
        self.part_bodies[first["path"]] += b"excess"
        result = self.acquire()
        self.assertEqual(result["outcome"], "fail")
        self.assertIn("bound", result["reason"])
        self.assertTrue((self.args.archive_root / (first["path"] + ".partial")).is_file())

    def test_redirect_or_non_200_response_never_becomes_a_locked_part(self):
        def redirect(*arguments, **kwargs):
            result = self.command(*arguments, **kwargs)
            if "--url" in arguments[0]:
                arguments[3].write_bytes(b"302\n")
            return result
        self.run_mock.side_effect = redirect
        result = self.acquire()
        self.assertEqual(result["outcome"], "fail")
        self.assertIn("direct HTTP 200", result["reason"])
        self.assertEqual(len(result["parts"]), 1)

    def test_failed_fetch_retains_repository_and_log_and_stops_before_downloads(self):
        def fail_fetch(*arguments, **kwargs):
            result = self.command(*arguments, **kwargs)
            return dict(result, outcome="fail", exit_code=128, reason="nonzero_exit") if "fetch" in arguments[0] else result
        self.run_mock.side_effect = fail_fetch
        result = self.acquire()
        self.assertEqual(result["outcome"], "fail")
        self.assertEqual(len(self.observed), 2)
        self.assertEqual(result["parts"], [])
        self.assertTrue((self.args.dependency_repositories / "yaml-cpp/.git").is_dir())
        self.assertTrue((self.args.output_dir / "logs/yaml-cpp-fetch.log").is_file())

    def test_failed_second_transfer_preserves_first_verified_part(self):
        def fail_transfer(*arguments, **kwargs):
            result = self.command(*arguments, **kwargs)
            if arguments[3].name == "toolchain-part-02.log":
                result.update(outcome="fail", exit_code=28, reason="timeout")
            return result
        self.run_mock.side_effect = fail_transfer
        result = self.acquire()
        self.assertEqual(result["outcome"], "fail")
        self.assertEqual([row["state"] for row in result["parts"]], ["verified", "acquiring"])
        self.assertEqual(len(self.observed), 8)
        self.assertTrue((self.args.archive_root / result["parts"][0]["path"]).is_file())
        self.assertTrue((self.args.archive_root / result["parts"][1]["partial_path"]).is_file())

    def test_zero_exit_with_incomplete_cleanup_is_not_success(self):
        self.run_mock.side_effect = lambda *a, **k: dict(self.command(*a, **k), cleanup_complete=False)
        result = self.acquire()
        self.assertEqual(result["outcome"], "fail")
        self.assertEqual(len(result["commands"]), 1)

    def test_interruption_retains_pending_command_and_a_nonempty_failure(self):
        self.run_mock.side_effect = KeyboardInterrupt
        result = self.acquire()
        self.assertEqual((result["outcome"], result["reason"]), ("fail", "interrupted"))
        self.assertEqual(len(result["commands"]), 1)
        self.assertEqual(result["input_identity_sha256"], None)

    def test_reused_attempt_never_overwrites_receipt_or_retries(self):
        self.acquire()
        receipt = self.args.output_dir / inputs.RECEIPT_NAME
        original = receipt.read_bytes()
        observed = len(self.observed)
        with self.assertRaisesRegex(ValueError, "fresh"):
            inputs.acquire(self.args)
        self.assertEqual(receipt.read_bytes(), original)
        self.assertEqual(len(self.observed), observed)

    def test_overlapping_or_existing_roots_reject_before_mutation(self):
        for attribute, value in (("archive_root", self.args.workspace_dir),
                                 ("output_dir", self.source / "evidence"),
                                 ("dependency_repositories", self.source)):
            with self.subTest(attribute=attribute), mock.patch.object(self.args, attribute, value):
                with self.assertRaisesRegex(ValueError, "overlap"):
                    inputs.acquire(self.args)
        self.args.workspace_dir.mkdir()
        with self.assertRaisesRegex(ValueError, "fresh workspace"):
            inputs.acquire(self.args)
        self.assertFalse(self.args.output_dir.exists())
        self.assertEqual(self.observed, [])

    def test_symlink_parent_is_rejected_before_mutation(self):
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        self.args.archive_root = alias / "archives"
        with self.assertRaisesRegex(ValueError, "symlink"):
            inputs.acquire(self.args)
        self.assertFalse(self.args.output_dir.exists())

    def test_relative_root_is_rejected_instead_of_being_absolutized(self):
        self.args.archive_root = Path("relative-archives")
        with self.assertRaisesRegex(ValueError, "canonical absolute"):
            inputs.acquire(self.args)
        self.assertEqual(self.observed, [])

    def test_wrong_original_raw_bytes_block_before_network_and_preserve_input(self):
        changed = b"unreviewed replacement original\n"
        self.args.control_archive.write_bytes(changed)
        result = self.acquire()
        self.assertEqual(result["outcome"], "blocked")
        self.assertIn("control original", result["reason"])
        self.assertEqual(self.args.control_archive.read_bytes(), changed)
        self.assertFalse(self.args.archive_root.exists())
        self.assertFalse(self.args.dependency_repositories.exists())
        self.assertEqual(self.observed, [])

    def test_original_hardlink_is_not_accepted(self):
        os.link(self.args.control_archive, self.root / "control-copy.zip")
        result = self.acquire()
        self.assertEqual(result["outcome"], "blocked")
        self.assertIn("unlinked regular file", result["reason"])
        self.assertEqual(self.observed, [])

    def test_original_symlink_is_not_accepted(self):
        alias = self.root / "control-alias.zip"
        alias.symlink_to(self.args.control_archive)
        self.args.control_archive = alias
        result = self.acquire()
        self.assertEqual(result["outcome"], "blocked")
        self.assertIn("without symlinks", result["reason"])
        self.assertEqual(self.observed, [])

    def test_original_inside_source_is_rejected_without_reading_its_code(self):
        original = self.source / "original.zip"
        original.write_bytes(self.args.control_archive.read_bytes())
        self.args.control_archive = original
        result = self.acquire()
        self.assertEqual(result["outcome"], "blocked")
        self.assertIn("must be separate", result["reason"])

    def test_changed_original_after_download_rejects_complete_acquisition(self):
        def mutate_original(*arguments, **kwargs):
            result = self.command(*arguments, **kwargs)
            if arguments[3].name == "toolchain-part-15.log":
                self.args.control_archive.write_bytes(b"changed original\n")
            return result
        self.run_mock.side_effect = mutate_original
        result = self.acquire()
        self.assertEqual(result["outcome"], "fail")
        self.assertIsNone(result["input_identity_sha256"])
        self.assertEqual(len(result["parts"]), 15)

    def test_disk_reserve_is_not_lowered_for_input_acquisition(self):
        self.disk_mock.return_value = SimpleNamespace(free=15 * 1024**3 - 1)
        result = self.acquire()
        self.assertEqual(result["outcome"], "blocked")
        self.assertIn("15 GiB", result["reason"])
        self.assertEqual(result["resources_before"]["free_disk_bytes"]["archives"], 15 * 1024**3 - 1)
        self.assertEqual(self.observed, [])
        self.assertFalse(self.args.archive_root.exists())

    def test_missing_available_memory_blocks_before_network(self):
        self.memory_mock.return_value = None
        result = self.acquire()
        self.assertEqual(result["outcome"], "blocked")
        self.assertIn("4 GiB", result["reason"])
        self.assertEqual(self.observed, [])

    def test_final_resource_failure_does_not_return_success(self):
        high = SimpleNamespace(free=16 * 1024**3)
        low = SimpleNamespace(free=15 * 1024**3 - 1)
        self.disk_mock.side_effect = [high] * 5 + [low] * 5
        result = self.acquire()
        self.assertEqual(result["outcome"], "fail")
        self.assertEqual(len(result["parts"]), 15)
        self.assertIsNone(result["input_identity_sha256"])

    def test_invalid_revision_is_not_copied_into_public_receipt(self):
        self.args.expected_revision = "https://user:secret@example.invalid/"
        result = self.acquire()
        self.assertEqual(result["outcome"], "blocked")
        self.assertIsNone(result["expected_revision"])
        self.assertNotIn("secret", json.dumps(result))
        self.plan_mock.assert_not_called()
        self.source_mock.assert_not_called()

    def test_wrong_source_revision_blocks_before_fetch(self):
        self.checkout["revision"] = "c" * 40
        result = self.acquire()
        self.assertEqual(result["outcome"], "blocked")
        self.assertIn("expected revision", result["reason"])
        self.assertEqual(self.observed, [])

    def test_dirty_source_blocks_before_fetch(self):
        self.checkout["dirty"] = True
        result = self.acquire()
        self.assertEqual(result["outcome"], "blocked")
        self.assertIn("clean source", result["reason"])
        self.assertEqual(self.observed, [])

    def test_moving_toolchain_version_cannot_replace_the_immutable_lock(self):
        self.checkout["pins"]["TOOLCHAIN_REV"] = "v3.0.3"
        result = self.acquire()
        self.assertEqual(result["outcome"], "blocked")
        self.assertIn("immutable archive lock", result["reason"])
        self.assertEqual(self.observed, [])

    def test_ignored_source_dependency_residue_blocks_before_fetch(self):
        self.status = b"!! build/CMakeCache.txt\n"
        result = self.acquire()
        self.assertEqual(result["outcome"], "blocked")
        self.assertIn("ignored inputs", result["reason"])
        self.assertEqual(self.observed, [])

    def test_wrong_dependency_tree_rejects_before_archive_transfer(self):
        inputs.dependency.PINS["yaml-cpp"]["tree"] = "0" * 40
        result = self.acquire()
        self.assertEqual(result["outcome"], "fail")
        self.assertIn("root tree differs", result["reason"])
        self.assertEqual(result["parts"], [])

    def test_commit_bytes_are_hashed_even_when_tree_and_blob_objects_match(self):
        pin = self.pins["ramulator"]
        object_path = self.source / pin["path"] / ".git/objects" / pin["revision"][:2] / pin["revision"][2:]
        raw = zlib.decompress(object_path.read_bytes()).split(b"\0", 1)[1] + b"altered commit message\n"
        object_path.chmod(0o600)
        object_path.write_bytes(zlib.compress(b"commit " + str(len(raw)).encode() + b"\0" + raw))
        result = self.acquire()
        self.assertEqual(result["outcome"], "fail")
        self.assertRegex(result["reason"], "commit bytes differ|hash mismatch")
        self.assertEqual(result["parts"], [])

    def test_source_mutation_after_acquisition_is_retained_as_failure(self):
        self.source_mock.side_effect = [deepcopy(self.checkout), dict(self.checkout, dirty=True)]
        result = self.acquire()
        self.assertEqual(result["outcome"], "fail")
        self.assertIn("source changed", result["reason"])
        self.assertIsNone(result["input_identity_sha256"])

    def test_cli_requires_explicit_separate_originals_and_reports_scope(self):
        values = []
        for name in ("source_dir", "expected_revision", "workspace_dir", "archive_root",
                     "dependency_repositories", "output_dir", "diagnostic_archive", "control_archive"):
            values.extend(("--" + name.replace("_", "-"), str(getattr(self.args, name))))
        with mock.patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(inputs.main(values), 0)
        summary = json.loads(output.getvalue())
        self.assertEqual(summary["outcome"], "pass")
        self.assertEqual(summary["native_execution"], "not_run")
        self.assertEqual(summary["contract_id"], inputs.CONTRACT_ID)


if __name__ == "__main__":
    unittest.main()
