# Licensed under the Apache License, Version 2.0.
"""Independent provenance checks using local repositories and inert tool fixtures."""

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import baseline_inventory as inventory


PINS = {
    "VORTEX_VERSION": "3.0",
    "TOOLCHAIN_REV": "v3.0.2",
    "GEM5_REV": "v25.0.0.1",
    "FIRESIM_REV": "57bb93f1e23daf46198659ddd93608f70121fee0",
}
SOURCE_FILES = (
    "VERSION", ".gitmodules", "configure", "config.mk.in", "VX_config.toml",
    "VX_types.toml", "ci/gen_config.py", "ci/blackbox.sh",
)
BINARIES = (
    "riscv64-gnu-toolchain/bin/riscv64-unknown-elf-gcc",
    "llvm-vortex/bin/clang", "verilator/bin/verilator",
    "verilator/bin/verilator_bin",
)
LIBRARIES = (
    "libc64/lib/libc.a", "libc64/lib/libm.a",
    "libcrt64/lib/baremetal/libclang_rt.builtins-riscv64.a",
)


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def git(root, *arguments):
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith("GIT_")}
    environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    return subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=Inventory Fixture",
         "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false",
         *arguments], check=True, capture_output=True, text=True, timeout=10,
        env=environment,
    ).stdout.strip()


def populate_source(root):
    root.mkdir(parents=True)
    for name in SOURCE_FILES:
        write(root / name, "fixture\n")
    write(root / "VERSION", "".join(f"{key}={value}\n" for key, value in PINS.items()))
    write(root / ".gitmodules", "")
    write(root / ".gitignore", "/build*/\n")


class TemporaryFixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)

    def assert_blocked(self, result, fragment=None):
        self.assertEqual(result["outcome"], "blocked", result)
        self.assertTrue(result["blockers"])
        if fragment is not None:
            self.assertTrue(any(fragment in item for item in result["blockers"]), result)


class ArtifactTests(TemporaryFixture):
    def setUp(self):
        super().setUp()
        self.root = self.base / "artifacts"
        self.root.mkdir()
        (self.root / "result.log").write_bytes(b"observed result\n")

    def test_hash_matches_exact_bytes_and_preserves_requested_path(self):
        self.assertEqual(inventory.hash_artifacts(self.root, ["result.log"]), [{
            "path": "result.log", "size_bytes": 16,
            "sha256": hashlib.sha256(b"observed result\n").hexdigest(),
        }])

    def test_contained_symlink_is_hashed_but_external_symlink_is_rejected(self):
        (self.root / "alias.log").symlink_to("result.log")
        result = inventory.hash_artifacts(self.root, ["alias.log"])[0]
        self.assertEqual(result["path"], "alias.log")
        self.assertEqual(result["sha256"], hashlib.sha256(b"observed result\n").hexdigest())
        write(self.base / "external.log", "private fixture")
        (self.root / "escape.log").symlink_to(self.base / "external.log")
        with self.assertRaises(ValueError):
            inventory.hash_artifacts(self.root, ["escape.log"])

    def test_missing_directory_fifo_and_invalid_paths_are_rejected(self):
        (self.root / "directory").mkdir()
        os.mkfifo(self.root / "pipe")
        for names in (["missing"], ["directory"], ["pipe"], ["../external"],
                      [str(self.root / "result.log")], ["result.log", "result.log"],
                      ["bad\nname"], ["bad\\name"], [""]):
            with self.subTest(names=names), self.assertRaises(ValueError):
                inventory.hash_artifacts(self.root, names)


class SourceTests(TemporaryFixture):
    def setUp(self):
        super().setUp()
        self.root = self.base / "source"
        populate_source(self.root)
        git(self.root, "init", "-q")
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", "fixture source")

    def test_clean_source_reports_actual_git_commit_and_tree(self):
        report = inventory.collect_source(self.root)
        self.assertEqual(report["outcome"], "pass", report)
        self.assertEqual(report["revision"], git(self.root, "rev-parse", "HEAD"))
        self.assertEqual(report["tree"], git(self.root, "rev-parse", "HEAD^{tree}"))
        self.assertIs(report["dirty"], False)
        self.assertEqual(report["pins"], PINS)
        self.assertNotIn(str(self.base), json.dumps(report))

    def test_tracked_edits_block_the_commit_only_identity(self):
        write(self.root / "configure", "changed input\n")
        report = inventory.collect_source(self.root)
        self.assert_blocked(report, "tracked changes")
        self.assertIn("configure", report["changed_paths"])

    def test_nonignored_untracked_inputs_block_but_build_outputs_do_not(self):
        write(self.root / "build64" / "result.o", "generated object")
        self.assertEqual(inventory.collect_source(self.root)["outcome"], "pass")
        write(self.root / "new_kernel.cpp", "new source")
        report = inventory.collect_source(self.root)
        self.assert_blocked(report)
        self.assertEqual(report["untracked_paths"], ["new_kernel.cpp"])

    def test_staged_rename_keeps_the_new_path_and_blocks(self):
        git(self.root, "mv", "configure", "configure-renamed")
        report = inventory.collect_source(self.root)
        self.assert_blocked(report)
        self.assertIn("configure-renamed", report["changed_paths"])

    def test_subdirectory_and_nonrepository_cannot_be_source_root(self):
        self.assert_blocked(inventory.collect_source(self.root / "ci"))
        self.assert_blocked(inventory.collect_source(self.base))

    def test_missing_submodule_checkout_is_a_blocker_without_network_access(self):
        revision = git(self.root, "rev-parse", "HEAD")
        write(self.root / ".gitmodules", '[submodule "math"]\n'
              'path = third_party/math\nurl = https://example.invalid/math.git\n')
        git(self.root, "add", ".gitmodules")
        git(self.root, "update-index", "--add", "--cacheinfo",
            "160000," + revision + ",third_party/math")
        git(self.root, "commit", "-qm", "declare submodule")
        report = inventory.collect_source(self.root)
        self.assert_blocked(report, "submodule is not at its recorded revision")
        self.assertEqual(report["submodules"]["entries"][0]["status"], "not_initialized")

    def test_mismatched_submodule_revision_is_not_reported_clean(self):
        upstream = self.base / "upstream"
        upstream.mkdir()
        git(upstream, "init", "-q")
        write(upstream / "math.c", "first\n")
        git(upstream, "add", ".")
        git(upstream, "commit", "-qm", "first")
        first = git(upstream, "rev-parse", "HEAD")
        write(upstream / "math.c", "second\n")
        git(upstream, "commit", "-qam", "second")
        second = git(upstream, "rev-parse", "HEAD")
        git(self.root, "-c", "protocol.file.allow=always", "submodule", "add", "-q",
            str(upstream), "third_party/math")
        checkout = self.root / "third_party/math"
        git(checkout, "checkout", "-q", first)
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", "pin first submodule")
        self.assertEqual(inventory.collect_source(self.root)["outcome"], "pass")
        git(checkout, "checkout", "-q", second)
        report = inventory.collect_source(self.root)
        self.assert_blocked(report, "submodule is not at its recorded revision")
        self.assertEqual(report["submodules"]["entries"][0]["status"], "revision_mismatch")


class ToolTests(TemporaryFixture):
    def setUp(self):
        super().setUp()
        self.root = self.base / "tools"
        self.root.mkdir()
        for relative in BINARIES:
            self.script(relative, 'print("Fixture compiler 1.0 /private/location")\n')
        for relative in LIBRARIES:
            write(self.root / relative, "archive fixture\n")
        paths = []
        for component, suffixes in (("riscv64-gnu-toolchain", "abcdefghij"),
                                    ("llvm-vortex", "abc"), ("verilator", "abc")):
            paths.extend(f"{component}/ubuntu/focal/{component}.tar.bz2.parta{x}"
                         for x in suffixes)
        paths.extend(("libc64/libc64.tar.bz2", "libcrt64/libcrt64.tar.bz2"))
        self.manifest_data = {
            "repository": "vortexgpgpu/vortex-toolchain-prebuilt", "tag": "v3.0.2",
            "revision": "e3db4bcdf819a17f618ad9fc2472f8f7dea3192b",
            "os_bundle": "ubuntu/focal",
            "parts": [{"path": path, "size_bytes": 10,
                       "git_blob_sha": "a" * 40, "sha256": "b" * 64} for path in paths],
        }
        self.manifest = self.base / "bundles.json"
        self.save_manifest()
        self.production_anchor = inventory.TOOLCHAIN_MANIFEST_SHA256
        self.enterContext(mock.patch.object(inventory, "TOOLCHAIN_MANIFEST_SHA256",
                                           inventory.manifest_digest(self.manifest_data)))

    def script(self, relative, body):
        path = self.root / relative
        write(path, "#!" + sys.executable + "\n" + body)
        path.chmod(0o755)

    def save_manifest(self, data=None):
        write(self.manifest, json.dumps(self.manifest_data if data is None else data))

    def collect(self):
        return inventory.collect_tools(self.root, self.manifest)

    def test_complete_fixture_records_hashes_and_redacts_version_paths(self):
        report = self.collect()
        self.assertEqual(report["outcome"], "pass", report)
        self.assertEqual(len(report["tools"]), 4)
        self.assertEqual(len(report["libraries"]), 3)
        self.assertEqual(len(report["bundle_manifest"]["parts"]), 18)
        serialized = json.dumps(report)
        self.assertNotIn(str(self.base), serialized)
        self.assertNotIn("/private/location", serialized)
        self.assertIn("<path>", serialized)

    def test_absent_manifest_is_not_a_pinned_environment(self):
        self.assert_blocked(inventory.collect_tools(self.root), "manifest")

    def test_production_anchor_rejects_synthetic_archive_identities(self):
        with mock.patch.object(inventory, "TOOLCHAIN_MANIFEST_SHA256", self.production_anchor):
            self.assert_blocked(self.collect(), "manifest")

    def test_production_manifest_rejects_duplicate_top_level_fields(self):
        data = json.loads(Path(__file__).with_name("p01_toolchain.lock.json").read_text())
        serialized = json.dumps(data, separators=(",", ":"))
        with mock.patch.object(inventory, "TOOLCHAIN_MANIFEST_SHA256", self.production_anchor):
            self.save_manifest(data)
            self.assertEqual(self.collect()["outcome"], "pass")
            for value in ("0" * 40, data["revision"]):
                with self.subTest(duplicate_value=value):
                    contents = '{"revision":' + json.dumps(value) + ',' + serialized[1:]
                    self.assertEqual(json.loads(contents), data)
                    write(self.manifest, contents)
                    with self.assertRaisesRegex(ValueError, "duplicate JSON field"):
                        inventory._bundle_identity(self.manifest)
                    self.assert_blocked(self.collect(), "manifest")

    def test_production_manifest_rejects_duplicate_nested_fields(self):
        data = json.loads(Path(__file__).with_name("p01_toolchain.lock.json").read_text())
        serialized = json.dumps(data, separators=(",", ":"))
        with mock.patch.object(inventory, "TOOLCHAIN_MANIFEST_SHA256", self.production_anchor):
            self.save_manifest(data)
            self.assertEqual(self.collect()["outcome"], "pass")
            for value in ("0" * 64, data["parts"][0]["sha256"]):
                with self.subTest(duplicate_value=value):
                    contents = serialized.replace(
                        '"sha256":', '"sha256":' + json.dumps(value) + ',"sha256":', 1)
                    self.assertEqual(json.loads(contents), data)
                    write(self.manifest, contents)
                    with self.assertRaisesRegex(ValueError, "duplicate JSON field"):
                        inventory._bundle_identity(self.manifest)
                    self.assert_blocked(self.collect(), "manifest")

    def test_incomplete_duplicate_or_wrong_pin_manifests_are_rejected(self):
        wrong_pin = copy.deepcopy(self.manifest_data)
        wrong_pin["revision"] = "c" * 40
        missing = copy.deepcopy(self.manifest_data)
        missing["parts"].pop()
        duplicate = copy.deepcopy(self.manifest_data)
        duplicate["parts"][-1] = copy.deepcopy(duplicate["parts"][0])
        for data in (wrong_pin, missing, duplicate):
            with self.subTest(data=data):
                self.save_manifest(data)
                self.assert_blocked(self.collect(), "manifest")

    def test_malformed_and_oversized_manifests_fail_closed(self):
        for contents in ("{", "[]", " " * (1024 * 1024 + 1)):
            with self.subTest(length=len(contents)):
                write(self.manifest, contents)
                self.assert_blocked(self.collect(), "manifest")

    def test_missing_nonexecutable_and_failed_version_tools_are_blocked(self):
        relative = BINARIES[0]
        path = self.root / relative
        path.unlink()
        self.assert_blocked(self.collect(), "riscv_gcc")
        self.script(relative, 'print("fixture")\n')
        path.chmod(0o644)
        self.assert_blocked(self.collect(), "riscv_gcc")
        self.script(relative, "raise SystemExit(7)\n")
        self.assert_blocked(self.collect(), "riscv_gcc")

    def test_empty_and_unbounded_version_output_are_not_accepted(self):
        for body in ("pass\n", 'print("x" * 70000)\n'):
            with self.subTest(body=body):
                self.script(BINARIES[1], body)
                self.assert_blocked(self.collect(), "llvm_clang")

    def test_missing_required_library_blocks_an_otherwise_complete_inventory(self):
        (self.root / LIBRARIES[-1]).unlink()
        self.assert_blocked(self.collect(), "required library")

    def test_version_probe_has_a_bounded_timeout(self):
        start = time.monotonic()
        with self.assertRaises(ValueError):
            inventory._probe([sys.executable, "-c", "import time; time.sleep(10)"],
                             timeout=0.1)
        self.assertLess(time.monotonic() - start, 3)


class BuildTests(TemporaryFixture):
    def setUp(self):
        super().setUp()
        self.source = self.base / "source"
        populate_source(self.source)
        self.build = self.source / "build64"
        self.build.mkdir()
        self.stamp = {
            "XLEN": "64", "TOOLDIR": str(self.base / "tools"),
            "OSVERSION": "ubuntu/focal", "PREFIX": str(self.build / "install"),
            "PROFILE": "", "SOURCE_DIR": str(self.source), "BUILDDIR": str(self.build),
            **PINS,
        }
        self.config = {"XLEN": "64", "TOOLDIR": self.stamp["TOOLDIR"],
                       "OSVERSION": "ubuntu/focal", "PROFILE": "",
                       "VORTEX_HOME": str(self.source)}
        write(self.source / "config.mk.in", "".join(
            f"{key} ?= @{key}@\n" for key in self.config))
        self.write_config()
        repository = Path(__file__).resolve().parents[2]
        for relative in ("VX_config.toml", "VX_types.toml", "ci/gen_config.py"):
            write(self.source / relative, (repository / relative).read_text())
        substitutions = dict(self.stamp, VORTEX_HOME=str(self.source),
                             INSTALLDIR=self.stamp["PREFIX"])
        for destination, origin in inventory.COPIED_BUILD_INPUTS.items():
            contents = (repository / origin).read_text()
            write(self.source / origin, contents)
            if origin.endswith(".in"):
                for key, value in substitutions.items():
                    contents = contents.replace("@" + key + "@", value)
            write(self.build / destination, contents)
        for relative in ("sw/VX_config.h", "hw/VX_config.vh", "sw/VX_types.h", "hw/VX_types.vh"):
            target = self.build / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            args = [sys.executable, "-I", "-S", "-B", str(self.source / "ci/gen_config.py"),
                    "--config", str(self.source / (target.stem + ".toml")),
                    "--output", str(target), "--format",
                    "cpp" if relative.startswith("sw/") else "verilog"]
            if target.stem == "VX_types":
                args.append("--resolved")
            subprocess.run(args, env=dict(os.environ, XLEN="64"), check=True,
                           capture_output=True, timeout=10)
            os.utime(self.build / relative, (time.time() + 10, time.time() + 10))
        write(self.build / "ci/blackbox.sh", (self.source / "ci/blackbox.sh").read_text())

    def write_config(self):
        write(self.build / ".config.stamp", " ".join(f"{k}={v}" for k, v in self.stamp.items()))
        write(self.build / "config.mk", "".join(f"{k} ?= {v}\n" for k, v in self.config.items()))

    def collect(self):
        return inventory.collect_build(self.build, self.source)

    def test_matching_build_records_fresh_generated_hashes(self):
        report = self.collect()
        self.assertEqual(report["outcome"], "pass", report)
        self.assertIs(report["identity_matches"], True)
        self.assertEqual(report["xlen"], 64)
        self.assertEqual(len(report["generated"]), 7)
        self.assertNotIn(str(self.base), json.dumps(report))

    def test_build_cannot_be_the_source_or_contain_the_source(self):
        self.assert_blocked(inventory.collect_build(self.source, self.source))
        self.assert_blocked(inventory.collect_build(self.base, self.source))

    def test_different_source_identity_or_tool_directory_is_rejected(self):
        self.config["VORTEX_HOME"] = str(self.base / "other-source")
        self.write_config()
        self.assert_blocked(self.collect())
        self.config["VORTEX_HOME"] = str(self.source)
        self.config["TOOLDIR"] = str(self.base / "other-tools")
        self.write_config()
        self.assert_blocked(self.collect())

    def test_wrong_xlen_and_profile_are_rejected_even_when_stamp_matches(self):
        for key, value in (("XLEN", "32"), ("PROFILE", "ai-dev")):
            with self.subTest(key=key):
                self.config[key] = value
                self.stamp[key] = value
                self.write_config()
                self.assert_blocked(self.collect())
                self.config[key] = self.stamp[key] = "64" if key == "XLEN" else ""

    def test_stale_generated_header_or_runner_cannot_pass(self):
        target = self.build / "sw/VX_config.h"
        os.utime(target, (1, 1))
        self.assert_blocked(self.collect())
        os.utime(target, (time.time() + 10, time.time() + 10))
        write(self.build / "ci/blackbox.sh", "stale command body")
        self.assert_blocked(self.collect())

    def test_missing_or_oversized_generated_identity_blocks(self):
        target = self.build / "config.mk"
        target.unlink()
        self.assert_blocked(self.collect())
        write(target, " " * (1024 * 1024 + 1))
        self.assert_blocked(self.collect())

    def test_effective_make_override_cannot_hide_behind_expected_defaults(self):
        for directive in ("override XLEN := 32", "override TOOLDIR := /other-tools",
                          "include /other/config.mk"):
            with self.subTest(directive=directive):
                self.write_config()
                with (self.build / "config.mk").open("a", encoding="utf-8") as stream:
                    stream.write(directive + "\n")
                self.assert_blocked(self.collect())

    def test_nonregular_or_escaped_configuration_is_rejected_before_reading(self):
        for relative in (".config.stamp", "config.mk"):
            target = self.build / relative
            with self.subTest(relative=relative, kind="fifo"):
                self.write_config()
                target.unlink()
                os.mkfifo(target)
                self.assert_blocked(self.collect())
                target.unlink()
            with self.subTest(relative=relative, kind="external-symlink"):
                self.write_config()
                external = self.base / "external-config"
                write(external, target.read_text())
                target.unlink()
                target.symlink_to(external)
                self.assert_blocked(self.collect())
                target.unlink()


if __name__ == "__main__":
    unittest.main()
