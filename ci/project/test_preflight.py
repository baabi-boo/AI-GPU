# Licensed under the Apache License, Version 2.0.
"""Offline prerequisite-screen tests; no toolchain or device is exercised."""

import argparse
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import preflight


REVISION = "a" * 40
PINS = (
    "VORTEX_VERSION=3.0\nTOOLCHAIN_REV=v3.0.2\n"
    "GEM5_REV=v25.0.0.1\nFIRESIM_REV=" + REVISION + "\n"
)
MODULE = "third_party/math"


class PreflightFixture(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.base = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.root = self.base / "repo"
        self.root.mkdir()
        (self.root / "VERSION").write_text(PINS, encoding="utf-8")
        self.write_modules(MODULE)
        self.asset = self.root / preflight.ASSET_PATH
        self.asset.parent.mkdir(parents=True)
        self.asset.write_bytes(b"isolated illustration fixture")
        digest = hashlib.sha256(self.asset.read_bytes()).hexdigest()
        self.stack.enter_context(mock.patch.object(preflight, "ASSET_SHA256", digest))
        self.git_outputs = {
            ("rev-parse", "--show-toplevel"): (0, str(self.root) + "\n"),
            ("rev-parse", "--verify", "HEAD"): (0, REVISION + "\n"),
            ("status", "--porcelain", "--untracked-files=no"): (0, ""),
            ("submodule", "status", "--recursive"): (0, " " + REVISION + " " + MODULE + "\n"),
        }
        self.git = self.stack.enter_context(mock.patch.object(
            preflight, "run_git", side_effect=lambda root, args: self.git_outputs[tuple(args)]))
        self.which = self.stack.enter_context(mock.patch.object(
            preflight.shutil, "which", return_value="/synthetic/private/tool"))
        self.disk = self.stack.enter_context(mock.patch.object(
            preflight.shutil, "disk_usage", return_value=SimpleNamespace(free=8 * preflight.GIB)))
        self.ram = self.stack.enter_context(mock.patch.object(
            preflight, "available_memory_bytes", return_value=4 * preflight.GIB))
        self.process = self.stack.enter_context(mock.patch.object(
            preflight.subprocess, "run", side_effect=AssertionError("unexpected process execution")))

    def write_modules(self, path):
        (self.root / ".gitmodules").write_text(
            '[submodule "math"]\npath = ' + path +
            "\nurl = https://synthetic-secret@example.invalid/math.git\n", encoding="utf-8")

    def collect(self, tier="governance", minimum=None):
        return preflight.collect_preflight(self.root, tier, minimum)

    def assert_blocked(self, report, fragment=None):
        self.assertEqual(report["outcome"], "blocked")
        self.assertTrue(report["blockers"])
        if fragment:
            self.assertTrue(any(fragment in item for item in report["blockers"]), report["blockers"])


class CollectionTests(PreflightFixture):
    def test_governance_pass_has_exact_identity_and_no_mutation(self):
        before = {path.relative_to(self.root): path.read_bytes()
                  for path in self.root.rglob("*") if path.is_file()}
        report = self.collect()
        after = {path.relative_to(self.root): path.read_bytes()
                 for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(report["outcome"], "pass")
        self.assertEqual(report["source"]["revision"], REVISION)
        self.assertFalse(report["source"]["tracked_changes"])
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["resources"]["free_disk_bytes"], 8 * preflight.GIB)
        self.assertTrue(report["asset"]["matches"])
        self.assertEqual(before, after)
        self.process.assert_not_called()
        observed = [tuple(call.args[1]) for call in self.git.call_args_list]
        self.assertCountEqual(observed, preflight.GIT_COMMANDS)

    def test_missing_gpu_tools_and_uninitialized_submodule_are_optional_for_governance(self):
        self.which.side_effect = lambda name: "/synthetic/git" if name == "git" else None
        self.git_outputs[("submodule", "status", "--recursive")] = (
            0, "-" + REVISION + " " + MODULE + "\n")
        report = self.collect()
        self.assertEqual(report["outcome"], "pass")
        self.assertTrue(report["warnings"])
        self.assertFalse(report["tools"]["verilator"]["available"])
        self.assertFalse(report["tools"]["verilator"]["required"])
        self.assertEqual(report["submodules"]["entries"][0]["status"], "not_initialized")

    def test_missing_git_blocks_governance(self):
        self.which.return_value = None
        self.assert_blocked(self.collect(), "git")

    def test_execution_tiers_block_missing_tools(self):
        self.which.side_effect = lambda name: "/synthetic/git" if name == "git" else None
        for tier in ("simulation", "fpga", "asic"):
            with self.subTest(tier=tier):
                self.assert_blocked(self.collect(tier), "tool missing")

    def test_execution_tiers_block_unresolved_submodules(self):
        for marker in ("-", "+", "U"):
            self.git_outputs[("submodule", "status", "--recursive")] = (
                0, marker + REVISION + " " + MODULE + "\n")
            with self.subTest(marker=marker):
                self.assert_blocked(self.collect("simulation"), "submodule")

    def test_execution_inventory_pass_explicitly_limits_claims(self):
        for tier, term in (("simulation", "SimX"), ("fpga", "Xilinx/XRT"), ("asic", "sign-off")):
            with self.subTest(tier=tier):
                report = self.collect(tier)
                self.assertEqual(report["outcome"], "pass")
                limitations = " ".join(report["limitations"])
                self.assertIn(term, limitations)
                self.assertIn("cgroup", limitations)
                self.assertIn("PATH", limitations)
                self.assertIn("approval", limitations)

    def test_unknown_tier_is_rejected(self):
        with self.assertRaises(ValueError):
            self.collect("imaginary")

    def test_disk_threshold_is_enforced_including_boundary(self):
        self.assertEqual(self.collect(minimum=8)["outcome"], "pass")
        self.assert_blocked(self.collect(minimum=8.01), "minimum")

    def test_invalid_programmatic_thresholds_fail_closed(self):
        for value in (-1, float("nan"), float("inf"), -float("inf"), True, "1", 10 ** 10000):
            with self.subTest(value_type=type(value).__name__):
                report = self.collect(minimum=value)
                self.assert_blocked(report, "finite")
                self.assertIsNone(report["resources"]["minimum_free_gib"])
                json.dumps(report, allow_nan=False)

    def test_unknown_disk_is_optional_only_without_governance_reserve(self):
        self.disk.side_effect = OSError("synthetic-sensitive-path")
        report = self.collect()
        self.assertEqual(report["outcome"], "pass")
        self.assertIsNone(report["resources"]["free_disk_bytes"])
        self.assert_blocked(self.collect(minimum=0), "minimum")
        self.assert_blocked(self.collect("simulation"), "resource")
        self.assertNotIn("synthetic-sensitive-path", json.dumps(report))

    def test_unknown_ram_does_not_become_zero_or_execution_pass(self):
        self.ram.return_value = None
        report = self.collect()
        self.assertEqual(report["outcome"], "pass")
        self.assertIsNone(report["resources"]["available_ram_bytes"])
        self.assertTrue(any("RAM" in item for item in report["warnings"]))
        self.assert_blocked(self.collect("simulation"), "resource")

    def test_wrong_git_top_level_blocks_inventory(self):
        self.git_outputs[("rev-parse", "--show-toplevel")] = (0, str(self.base))
        self.assert_blocked(self.collect(), "top level")

    def test_unavailable_git_root_blocks_inventory(self):
        self.git_outputs[("rev-parse", "--show-toplevel")] = (None, "")
        self.assert_blocked(self.collect(), "top level")

    def test_invalid_source_revision_is_not_reported_as_exact(self):
        for value in ("abc", "g" * 40, "", "a" * 41):
            self.git_outputs[("rev-parse", "--verify", "HEAD")] = (0, value)
            with self.subTest(value=value):
                report = self.collect()
                self.assert_blocked(report, "revision")
                self.assertIsNone(report["source"]["revision"])

    def test_dirty_and_unknown_tracked_status_are_explicit(self):
        key = ("status", "--porcelain", "--untracked-files=no")
        self.git_outputs[key] = (0, " M synthetic-sensitive-filename\n")
        report = self.collect()
        self.assertTrue(report["source"]["tracked_changes"])
        self.assertTrue(report["warnings"])
        self.assertNotIn("synthetic-sensitive-filename", json.dumps(report))
        self.git_outputs[key] = (None, "")
        report = self.collect()
        self.assertIsNone(report["source"]["tracked_changes"])
        self.assertTrue(report["warnings"])

    def test_changed_image_blocks_every_tier(self):
        self.asset.write_bytes(b"changed illustration")
        for tier in preflight.TIERS:
            with self.subTest(tier=tier):
                self.assert_blocked(self.collect(tier), "illustration")

    def test_no_urls_environment_values_or_tool_paths_are_reported(self):
        with mock.patch.dict(preflight.os.environ, {"SYNTHETIC_TOKEN": "never-emit-this-value"}):
            output = json.dumps(self.collect())
        for secret in ("synthetic-secret", "never-emit-this-value", "/synthetic/private/tool"):
            self.assertNotIn(secret, output)


class PinAndAssetTests(PreflightFixture):
    def test_expected_pins_parse_without_errors(self):
        pins, errors = preflight.read_pins(self.root)
        self.assertEqual(set(pins), set(preflight.PIN_NAMES))
        self.assertEqual(pins["TOOLCHAIN_REV"], "v3.0.2")
        self.assertEqual(errors, [])

    def test_missing_and_malformed_pins_are_rejected(self):
        for text in ("", PINS.replace("TOOLCHAIN_REV=v3.0.2\n", ""),
                     PINS + "TOOLCHAIN_REV=v4\n", PINS + "UNKNOWN=value\n",
                     PINS.replace("v3.0.2", "https://synthetic-secret.invalid"),
                     "not-an-assignment\n"):
            with self.subTest(text_length=len(text)):
                (self.root / "VERSION").write_text(text, encoding="utf-8")
                pins, errors = preflight.read_pins(self.root)
                self.assertTrue(errors)
                self.assertNotIn("synthetic-secret", json.dumps([pins, errors]))
                self.assert_blocked(self.collect(), "VERSION")

    def test_missing_pin_file_is_rejected(self):
        (self.root / "VERSION").unlink()
        self.assertTrue(preflight.read_pins(self.root)[1])

    def test_pin_symlink_cannot_escape_root(self):
        target = self.base / "outside-version"
        target.write_text(PINS, encoding="utf-8")
        path = self.root / "VERSION"
        path.unlink()
        path.symlink_to(target)
        self.assertTrue(preflight.read_pins(self.root)[1])

    def test_asset_hash_changes_and_missing_file_are_visible(self):
        self.assertTrue(preflight.asset_integrity(self.root)["matches"])
        self.asset.write_bytes(b"different")
        self.assertFalse(preflight.asset_integrity(self.root)["matches"])
        self.asset.unlink()
        report = preflight.asset_integrity(self.root)
        self.assertFalse(report["matches"])
        self.assertIsNone(report["actual_sha256"])

    def test_asset_symlink_cannot_escape_root(self):
        target = self.base / "outside.svg"
        target.write_bytes(self.asset.read_bytes())
        self.asset.unlink()
        self.asset.symlink_to(target)
        report = preflight.asset_integrity(self.root)
        self.assertFalse(report["matches"])
        self.assertIsNone(report["actual_sha256"])


class SubmoduleTests(PreflightFixture):
    def test_initialized_and_unresolved_statuses_are_distinct(self):
        for marker, status in ((" ", "initialized"), ("-", "not_initialized"),
                               ("+", "revision_mismatch"), ("U", "conflict")):
            self.git_outputs[("submodule", "status", "--recursive")] = (
                0, marker + REVISION.upper() + " " + MODULE + " (synthetic-secret-ref)\n")
            with self.subTest(status=status):
                result = preflight.submodule_inventory(self.root)
                self.assertFalse(result["errors"])
                self.assertEqual(result["entries"][0]["status"], status)
                self.assertEqual(result["entries"][0]["revision"], REVISION)
                self.assertNotIn("synthetic-secret-ref", json.dumps(result))

    def test_omitted_declared_module_is_rejected(self):
        self.git_outputs[("submodule", "status", "--recursive")] = (0, "")
        self.assertTrue(preflight.submodule_inventory(self.root)["errors"])
        self.assert_blocked(self.collect("simulation"), "submodule")

    def test_failed_status_is_not_silently_initialized(self):
        self.git_outputs[("submodule", "status", "--recursive")] = (1, "")
        self.assertTrue(preflight.submodule_inventory(self.root)["errors"])
        self.assertEqual(self.collect()["outcome"], "pass")
        self.assert_blocked(self.collect("simulation"), "submodule")

    def test_malformed_and_escaping_status_paths_are_rejected(self):
        for line in ("unrecognized output", " " + REVISION + " ../escape",
                     " " + REVISION + " /absolute/escape"):
            self.git_outputs[("submodule", "status", "--recursive")] = (0, line)
            with self.subTest(line=line):
                self.assertTrue(preflight.submodule_inventory(self.root)["errors"])

    def test_manifest_rejects_unsafe_missing_and_duplicate_paths(self):
        for path in ("../escape", "/absolute/escape", "", "bad path"):
            self.write_modules(path)
            with self.subTest(path=path):
                self.assertTrue(preflight.submodule_inventory(self.root)["errors"])
        self.write_modules(MODULE)
        manifest = self.root / ".gitmodules"
        manifest.write_text(manifest.read_text(encoding="utf-8") +
                            '[submodule "duplicate"]\npath = ' + MODULE + "\n", encoding="utf-8")
        self.assertTrue(preflight.submodule_inventory(self.root)["errors"])

    def test_manifest_path_symlink_cannot_escape_root(self):
        (self.root / "third_party").mkdir()
        (self.root / MODULE).symlink_to(self.base, target_is_directory=True)
        self.assertTrue(preflight.submodule_inventory(self.root)["errors"])

    def test_missing_and_invalid_manifest_are_visible(self):
        manifest = self.root / ".gitmodules"
        manifest.write_text("not an ini document", encoding="utf-8")
        self.assertTrue(preflight.submodule_inventory(self.root)["errors"])
        manifest.unlink()
        self.assertTrue(preflight.submodule_inventory(self.root)["errors"])


class CommandAndMemoryTests(unittest.TestCase):
    def test_git_allowlist_excludes_mutations_network_and_config_dumps(self):
        with mock.patch.object(preflight.subprocess, "run") as runner:
            for args in (("fetch",), ("push",), ("checkout", "master"), ("clean", "-fd"),
                         ("submodule", "update", "--init"), ("config", "--list"), ("remote", "-v")):
                with self.subTest(args=args), self.assertRaises(ValueError):
                    preflight.run_git(Path("/synthetic/repo"), args)
            runner.assert_not_called()

    def test_git_observations_have_timeout_and_read_only_controls(self):
        result = SimpleNamespace(returncode=0, stdout=REVISION + "\n", stderr="")
        with mock.patch.object(preflight.subprocess, "run", return_value=result) as runner:
            for args in preflight.GIT_COMMANDS:
                self.assertEqual(preflight.run_git(Path("/synthetic/repo"), args), (0, result.stdout))
            for call in runner.call_args_list:
                argv = call.args[0]
                self.assertEqual(argv[0], "git")
                self.assertIn("--no-optional-locks", argv)
                self.assertIn("core.fsmonitor=false", argv)
                self.assertIn("core.untrackedCache=false", argv)
                self.assertEqual(call.kwargs["timeout"], 10)
                self.assertEqual(call.kwargs["env"]["GIT_OPTIONAL_LOCKS"], "0")
                self.assertFalse(call.kwargs.get("shell", False))
                self.assertFalse(call.kwargs["check"])

    def test_git_failures_do_not_leak_stdout_or_stderr(self):
        result = SimpleNamespace(returncode=1, stdout="synthetic-secret", stderr="synthetic-secret")
        with mock.patch.object(preflight.subprocess, "run", return_value=result):
            self.assertEqual(preflight.run_git(Path("/synthetic/repo"), ("rev-parse", "--verify", "HEAD")), (1, ""))

    def test_git_timeout_oserror_and_decode_error_are_sanitized(self):
        failures = (OSError("synthetic-secret"),
                    subprocess.TimeoutExpired("synthetic-secret", 10, output="synthetic-secret"),
                    UnicodeError("synthetic-secret"))
        for error in failures:
            with self.subTest(error=type(error).__name__), mock.patch.object(
                    preflight.subprocess, "run", side_effect=error):
                self.assertEqual(preflight.run_git(Path("/synthetic/repo"), ("rev-parse", "--verify", "HEAD")), (None, ""))

    def test_memory_reports_available_not_total(self):
        with mock.patch.object(Path, "read_text", return_value="MemTotal: 99999 kB\nMemAvailable: 1234 kB\n"):
            self.assertEqual(preflight.available_memory_bytes(), 1234 * 1024)

    def test_memory_is_unknown_without_valid_available_value(self):
        for contents in ("MemTotal: 99999 kB\n", "MemAvailable: unknown kB\n", "MemAvailable: -1 kB\n"):
            with self.subTest(contents=contents), mock.patch.object(Path, "read_text", return_value=contents):
                self.assertIsNone(preflight.available_memory_bytes())
        with mock.patch.object(Path, "read_text", side_effect=OSError):
            self.assertIsNone(preflight.available_memory_bytes())

    def test_disk_parser_rejects_nonfinite_negative_and_nonnumeric_values(self):
        for value in ("nan", "NaN", "inf", "-inf", "-1", "not-a-number"):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                preflight.disk_threshold(value)
        self.assertEqual(preflight.disk_threshold("0"), 0)
        self.assertEqual(preflight.disk_threshold("1.5"), 1.5)


class CommandLineTests(PreflightFixture):
    def invoke(self, *args):
        output = io.StringIO()
        with redirect_stdout(output):
            code = preflight.main(["--root", str(self.root), *args])
        return code, output.getvalue()

    def test_json_success_and_blocked_exit_codes(self):
        code, output = self.invoke("--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["outcome"], "pass")
        code, output = self.invoke("--json", "--min-free-gib", "9")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output)["outcome"], "blocked")

    def test_text_output_names_scope_without_private_inventory(self):
        code, output = self.invoke()
        self.assertEqual(code, 0)
        self.assertIn("governance", output)
        self.assertIn("unchanged", output)
        self.assertNotIn("synthetic-secret", output)
        self.assertNotIn("/synthetic/private", output)

    def test_invalid_cli_thresholds_are_usage_errors(self):
        for value in ("nan", "inf", "-1", "text"):
            with self.subTest(value=value), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                self.invoke("--min-free-gib", value)
            self.assertEqual(error.exception.code, 2)

    def test_invalid_cli_tier_is_usage_error(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            self.invoke("--tier", "imaginary")
        self.assertEqual(error.exception.code, 2)

    def test_unreadable_root_is_sanitized_json_failure(self):
        with mock.patch.object(preflight, "collect_preflight", side_effect=OSError("synthetic-secret")):
            code, output = self.invoke("--json")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output)["outcome"], "blocked")
        self.assertNotIn("synthetic-secret", output)


if __name__ == "__main__":
    unittest.main()
