# SPDX-License-Identifier: Apache-2.0
"""Host-only checks; mocked launches do not establish native regression evidence."""

from contextlib import redirect_stderr, redirect_stdout
import copy
import hashlib
import io
import json
from pathlib import Path
import shutil
import unittest
from unittest import mock

import p06_mpm_parent as parent
from test_p06_mpm_execute import NativeFixture


NATIVE_FAILURE = {"outcome": "fail", "exit_code": 1, "reason": "nonzero_exit",
                  "process_started": True, "cleanup_complete": True}
RTL_FAILURE = "FAIL RV64 tick=32 tag=00220001: expected=00000001 actual=00000000\n"
SIMX_HIGH = ("FAILED: host high reply core=0 class=0 index=0 seed=0x0000000100000000 "
             "actual=0x0000000000000000 expected=0x0000000000000001\n")
SIMX_RECONSTRUCTION = (
    "FAILED: low-first reconstruction core=0 class=0 index=0 seed=0x0000000100000000 "
    "actual=0x0000000000000000 expected=0x0000000100000000\n")
SIMX_FAILURE = ("MPM transport: XLEN=64 PERF=on\n" + SIMX_HIGH + SIMX_RECONSTRUCTION
                + "FAILED: 2 of 7 MPM transport checks\n")


class ParentFixture(NativeFixture):
    """Reuse real file/configuration identities; only processes and Git metadata are synthetic."""

    def __enter__(self):
        super().__enter__()
        source = self.paths["source"]
        (source / "third_party").mkdir(exist_ok=True)
        helper = source / parent.SELF
        helper.write_text("fixture parent helper\n", encoding="utf-8")
        self.dependency_trees = {"HEAD:third_party": "c" * 40,
                                 parent.PARENT + ":third_party": "c" * 40}
        self.reference_revision = parent.PARENT
        self.reference_files = {}
        self.stack.enter_context(mock.patch.object(parent, "LOADED", parent.hash_artifacts(
            source, (parent.SELF,) + parent.native.HELPERS)))
        self.stack.enter_context(mock.patch.object(parent, "_git", side_effect=self.git))
        self.stack.enter_context(mock.patch.object(parent, "available_memory_bytes",
                                                   return_value=8 * parent.GIB))
        self.parent_bounded = self.stack.enter_context(mock.patch.object(
            parent, "run_bounded", side_effect=self.command))
        return self

    def git(self, root, *arguments):
        if arguments[0] in {"ls-files", "cat-file", "status"}:
            return b""
        if arguments[0] == "rev-parse":
            value = arguments[1]
            if value in self.dependency_trees:
                return self.dependency_trees[value].encode()
            if value == "HEAD":
                return self.reference_revision.encode()
            if value == "HEAD^{tree}":
                return ("d" * 40).encode()
        if arguments[0] == "diff":
            changed = [name for name, content in self.reference_files.items()
                       if not (root / name).is_file() or (root / name).read_bytes() != content]
            return "\n".join(changed).encode()
        raise AssertionError("unexpected fixture Git read: " + repr(arguments))

    def run(self, *extra):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = parent.main(self.argv(*extra))
        path = self.paths["output"] / "report.json"
        return code, json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    def command(self, argv, cwd, environment, log_path, **budget):
        cwd, log_path = Path(cwd), Path(log_path)
        name = log_path.stem
        self.calls.append({"id": name, "argv": argv, "cwd": cwd,
                           "environment": dict(environment), **budget})
        result = {"outcome": "pass", "exit_code": 0, "reason": None, "process_started": True,
                  "cleanup_complete": True, "duration_seconds": 0.01, "peak_rss_bytes": 1024}
        if name.endswith("-run"):
            result.update(NATIVE_FAILURE)
        result.update(self.results.get(name, {}))
        output = "fixture command completed\n"
        if result["outcome"] == "pass":
            if name == "clone-reference":
                Path(argv[-1]).mkdir()
            elif name == "checkout-reference":
                for relative in parent.REFERENCE_INPUTS:
                    if relative in parent.OVERLAY:
                        continue
                    path = cwd / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    content = (self.paths["source"] / relative).read_bytes()
                    if relative in {"sim/simx/core.cpp", "hw/rtl/core/VX_csr_mpm.sv"}:
                        content += b"fixture original production implementation\n"
                    path.write_bytes(content)
                    self.reference_files[relative] = content
                (cwd / "third_party").mkdir()
            elif name == "configure-rv64-perf-on":
                reference = self.paths["work"] / "reference"
                for relative in parent.native.GENERATED:
                    path = cwd / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("fixture generated input\n", encoding="utf-8")
                config = {"XLEN": "64", "PROFILE": "", "VORTEX_HOME": str(reference),
                          "TOOLDIR": str(self.paths["tools"])}
                for argument in argv:
                    if argument.startswith("--osversion="):
                        config["OSVERSION"] = argument.split("=", 1)[1]
                (cwd / "config.mk").write_text(
                    "".join(key + " ?= " + value + "\n" for key, value in config.items()), encoding="utf-8")
                for relative in parent.native.COPIED:
                    destination = cwd / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(reference / relative, destination)
                for relative in parent.native.UNITS.values():
                    (cwd / relative).mkdir(parents=True, exist_ok=True)
            elif name.endswith("-build"):
                engine = name.split("-")[0]
                binary = cwd / parent.native.BINARIES[engine]
                binary.write_text("fixture native binary: " + engine + "\n", encoding="utf-8")
                binary.chmod(0o700)
                if engine == "simx":
                    (cwd / "simx_config.stamp").write_text("fixture compiler stamp\n", encoding="utf-8")
        if name.endswith("-run"):
            output = RTL_FAILURE if name == "rtl-run" else SIMX_FAILURE
        log_path.write_text(self.logs.get(name, output), encoding="utf-8")
        result.update(log_sha256=hashlib.sha256(log_path.read_bytes()).hexdigest(),
                      log_size_bytes=log_path.stat().st_size)
        self.after_command(name, cwd)
        return result


class ParentFailureParserTests(unittest.TestCase):
    def test_exact_native_failures_are_recognized_without_relabeling_native_exit(self):
        original = copy.deepcopy(NATIVE_FAILURE)
        for engine, output in (("rtl", RTL_FAILURE), ("simx", SIMX_FAILURE)):
            with self.subTest(engine=engine):
                record = parent.verify_expected_failure(output, engine, NATIVE_FAILURE)
                self.assertEqual((record["expected_high"], record["actual_high"]), ("00000001", "00000000"))
                self.assertEqual(NATIVE_FAILURE, original)

    def test_timeout_blocked_nonstarted_cleanup_or_nonassertion_exit_cannot_pass(self):
        changes = ({"outcome": "blocked"}, {"outcome": "pass"}, {"exit_code": 0}, {"exit_code": 2},
                   {"exit_code": -11}, {"process_started": False}, {"cleanup_complete": False},
                   {"reason": "timeout"}, {"reason": "disk_reserve"}, {"reason": "memory_limit"})
        for engine, output in (("rtl", RTL_FAILURE), ("simx", SIMX_FAILURE)):
            for change in changes:
                with self.subTest(engine=engine, change=change), self.assertRaises(ValueError):
                    parent.verify_expected_failure(output, engine, dict(NATIVE_FAILURE, **change))

    def test_rtl_rejects_wrong_width_tag_value_duplicate_or_unrelated_failure(self):
        outputs = ["", "compiler failed\n", RTL_FAILURE.replace("RV64", "RV32"),
                   RTL_FAILURE.replace("00220001", "00020001"),
                   RTL_FAILURE.replace("actual=00000000", "actual=00000002"),
                   RTL_FAILURE * 2, RTL_FAILURE + "FAIL unrelated assertion\n",
                   RTL_FAILURE + "PASSED mpm_transport\n"]
        for output in outputs:
            with self.subTest(output=output), self.assertRaises(ValueError):
                parent.verify_expected_failure(output, "rtl", NATIVE_FAILURE)

    def test_simx_rejects_missing_wrong_or_repeated_configuration_and_counts(self):
        outputs = [SIMX_FAILURE.replace("XLEN=64", "XLEN=32"),
                   SIMX_FAILURE.replace("PERF=on", "PERF=off"),
                   SIMX_FAILURE + "MPM transport: XLEN=64 PERF=on\n",
                   SIMX_FAILURE.replace("2 of 7", "1 of 7"),
                   SIMX_FAILURE.replace("2 of 7", "2 of 2"),
                   SIMX_FAILURE.replace("FAILED: 2 of 7 MPM transport checks\n", ""),
                   SIMX_FAILURE + "FAILED: 2 of 7 MPM transport checks\n",
                   SIMX_FAILURE + "PASSED: 7 MPM transport checks\n"]
        for output in outputs:
            with self.subTest(output=output), self.assertRaises(ValueError):
                parent.verify_expected_failure(output, "simx", NATIVE_FAILURE)

    def test_simx_rejects_numerically_wrong_or_unrelated_assertions(self):
        replacements = [("host high reply", "host low reply"),
                        ("host high reply", "host class restoration"),
                        ("actual=0x0000000000000000 expected=0x0000000000000001",
                         "actual=0x0000000000000002 expected=0x0000000000000001"),
                        ("expected=0x0000000000000001", "expected=0x0000000000000002"),
                        ("actual=0x0000000000000000 expected=0x0000000100000000",
                         "actual=0x0000000000000001 expected=0x0000000100000000"),
                        ("seed=0x0000000100000000", "seed=0x00000000ffffffff"),
                        ("core=0", "core=1"), ("class=0", "class=1"), ("index=0", "index=2")]
        for old, new in replacements:
            with self.subTest(old=old, new=new), self.assertRaises(ValueError):
                parent.verify_expected_failure(SIMX_FAILURE.replace(old, new), "simx", NATIVE_FAILURE)
        with self.assertRaises(ValueError):
            parent.verify_expected_failure(SIMX_FAILURE, "unknown", NATIVE_FAILURE)

    def test_simx_accepts_missing_high_bits_above_rtl_width_and_both_read_orders(self):
        extra = ("FAILED: high-first reconstruction core=0 class=1 index=30 seed=0xfedcba9889abcdef "
                 "actual=0x0000000089abcdef expected=0xfedcba9889abcdef\n")
        text = SIMX_FAILURE.replace("FAILED: 2 of 7", extra + "FAILED: 3 of 9")
        record = parent.verify_expected_failure(text, "simx", NATIVE_FAILURE)
        self.assertEqual(record["failed_checks"], 3)


class ParentExecutionBoundaryTests(unittest.TestCase):
    def test_success_requires_both_native_expected_failures_and_retains_raw_evidence(self):
        with ParentFixture() as fixture:
            code, report = fixture.run("--osversion", "ubuntu/focal")
            self.assertEqual((code, report["outcome"]), (0, "pass"), report.get("reason"))
            self.assertEqual({cell["engine"] for cell in report["cells"]}, {"rtl", "simx"})
            self.assertTrue(all(cell["outcome"] == "expected_failure" for cell in report["cells"]))
            self.assertTrue(all(cell["native_outcome"] == "fail" and cell["native_exit_code"] == 1
                                for cell in report["cells"]))
            self.assertFalse(report["qualified"])
            self.assertFalse(report["acceptance_claimed"])
            self.assertTrue(report["reference_is_test_overlay"])
            for cell in report["cells"]:
                self.assertEqual(cell["binary_before"], cell["binary_after"])
                binary_path = Path(cell["binary_before"]["path"])
                self.assertTrue(binary_path.is_relative_to(fixture.paths["work"]))
                run = next(call for call in fixture.calls if call["id"] == cell["run_command"])
                self.assertEqual(run["argv"], [str(binary_path)])
                self.assertEqual(run["environment"]["PERF"], "1")
            simx_build = next(call for call in fixture.calls if call["id"] == "simx-build")
            self.assertIn("mpm_transport.mk", simx_build["argv"])
            self.assertIn("-f", simx_build["argv"])
            self.assertTrue((fixture.paths["output"] / "configuration/sim/simx/mpm_transport.mk").is_file())
            self.assertTrue((fixture.paths["output"] / "configuration/sim/simx/simx_config.stamp").is_file())
            for command in report["commands"]:
                content = (fixture.paths["output"] / command["log"]).read_bytes()
                self.assertEqual(hashlib.sha256(content).hexdigest(), command["log_sha256"])
            for call in fixture.calls:
                self.assertEqual(call["max_rss_bytes"], 4 * parent.GIB)
                self.assertEqual(call["min_free_bytes"], 15 * parent.GIB)
                self.assertEqual(call["environment"]["THREADS"], "1")

    def test_test_overlay_preserves_production_and_shares_only_matching_dependencies(self):
        protected = {"sim/simx/Makefile", "sim/simx/core.cpp", "sim/simx/csr_unit.cpp",
                     "hw/rtl/core/VX_csr_mpm.sv", "hw/rtl/core/VX_csr_data.sv"}
        self.assertFalse(protected.intersection(parent.OVERLAY))
        self.assertIn("sim/simx/mpm_transport.mk", parent.OVERLAY)
        with ParentFixture() as fixture:
            source_before = parent.hash_artifacts(fixture.paths["source"], protected)
            code, report = fixture.run()
            self.assertEqual(code, 0, report.get("reason"))
            self.assertEqual(source_before, parent.hash_artifacts(fixture.paths["source"], protected))
            reference = fixture.paths["work"] / "reference"
            self.assertEqual(report["parent_production_before_overlay"], parent.hash_artifacts(reference,
                ("sim/simx/core.cpp", "sim/simx/csr_unit.cpp", "hw/rtl/core/VX_csr_mpm.sv", "hw/rtl/core/VX_csr_data.sv")))
            self.assertEqual((reference / "third_party").resolve(), fixture.paths["source"] / "third_party")
            self.assertEqual(report["source_before"], report["source_after"])
            self.assertEqual(report["reference_before"], report["reference_after"])

    def test_existing_output_and_unsafe_or_overlapping_paths_do_not_start_commands(self):
        with ParentFixture() as fixture:
            output = fixture.paths["output"]
            output.mkdir()
            (output / "report.json").write_text('{"retained": true}\n', encoding="utf-8")
            code, report = fixture.run()
            self.assertEqual((code, report), (2, {"retained": True}))
            self.assertFalse(fixture.paths["work"].exists())
            fixture.parent_bounded.assert_not_called()
        for name, value in (("--work-dir", "source"), ("--output", "source/new-output"),
                            ("--output", "work"), ("--tools-dir", "tools-link")):
            with self.subTest(name=name, value=value), ParentFixture() as fixture:
                root = fixture.paths["source"].parent
                (root / "tools-link").symlink_to(fixture.paths["tools"], target_is_directory=True)
                code, report = fixture.run(name, str(root / value))
                self.assertEqual((code, report), (2, None))
                fixture.parent_bounded.assert_not_called()
        with ParentFixture() as fixture:
            code, report = fixture.run("--osversion", "bundle;command")
            self.assertEqual((code, report), (2, None))
            fixture.parent_bounded.assert_not_called()

    def test_dirty_untracked_or_blocked_candidate_never_executes_reference(self):
        for condition in ("dirty", "untracked", "blocked", "dependency-mismatch"):
            with self.subTest(condition=condition), ParentFixture() as fixture:
                if condition == "dirty":
                    fixture.checkout["dirty"] = True
                elif condition == "untracked":
                    fixture.tracked.remove("sim/simx/core.cpp")
                elif condition == "blocked":
                    fixture.checkout["blockers"] = ["missing submodule"]
                else:
                    fixture.dependency_trees["HEAD:third_party"] = "e" * 40
                code, report = fixture.run()
                self.assertEqual((code, report["outcome"]), (1, "blocked"))
                self.assertEqual(report["state"], "finished")
                self.assertTrue(all(cell["outcome"] == "blocked" for cell in report["cells"]))
                fixture.parent_bounded.assert_not_called()

    def test_insufficient_resources_retain_blocked_receipt_without_starting_commands(self):
        for resource in ("disk", "memory", "unknown-memory"):
            with self.subTest(resource=resource), ParentFixture() as fixture:
                if resource == "disk":
                    usage = shutil.disk_usage(fixture.paths["source"])._replace(free=15 * parent.GIB - 1)
                    patch = mock.patch.object(parent.shutil, "disk_usage", return_value=usage)
                else:
                    patch = mock.patch.object(parent, "available_memory_bytes",
                                              return_value=None if resource == "unknown-memory" else 4 * parent.GIB - 1)
                with patch:
                    code, report = fixture.run()
                self.assertEqual((code, report["outcome"]), (1, "blocked"))
                self.assertEqual(report["state"], "finished")
                self.assertFalse(report["qualified"])
                fixture.parent_bounded.assert_not_called()

    def test_build_or_preflight_failure_never_supplies_native_failure_evidence(self):
        failures = ({"outcome": "fail", "exit_code": 2, "reason": "nonzero_exit"},
                    {"outcome": "blocked", "exit_code": None, "reason": "disk_reserve", "process_started": False})
        for result in failures:
            with self.subTest(result=result), ParentFixture() as fixture:
                fixture.results["rtl-build"] = result
                fixture.logs["rtl-build"] = RTL_FAILURE
                code, report = fixture.run()
                self.assertEqual((code, report["outcome"]), (1, "fail"))
                self.assertNotIn("rtl-run", {call["id"] for call in fixture.calls})
                self.assertTrue(all(cell["outcome"] == "blocked" for cell in report["cells"]))
                self.assertTrue((fixture.paths["output"] / "logs/rtl-build.log").is_file())

    def test_run_timeout_infrastructure_failure_or_wrong_assertion_is_retained_as_failure(self):
        conditions = ({"reason": "timeout", "exit_code": -15}, {"cleanup_complete": False},
                      {"process_started": False, "outcome": "blocked", "reason": "disk_reserve", "exit_code": None},
                      {"outcome": "pass", "exit_code": 0, "reason": None}, {})
        for condition in conditions:
            with self.subTest(condition=condition), ParentFixture() as fixture:
                fixture.results["rtl-run"] = condition
                if not condition:
                    fixture.logs["rtl-run"] = "FAIL unrelated assertion\n"
                code, report = fixture.run()
                self.assertEqual((code, report["outcome"]), (1, "fail"))
                self.assertNotIn("simx-run", {call["id"] for call in fixture.calls})
                self.assertEqual(report["state"], "finished")
                self.assertEqual(report["cells"][0]["outcome"], "blocked")
                self.assertTrue((fixture.paths["output"] / "logs/rtl-run.log").is_file())

    def test_second_backend_failure_preserves_first_expected_failure_and_both_logs(self):
        with ParentFixture() as fixture:
            fixture.logs["simx-run"] = SIMX_FAILURE.replace("host high reply", "host class restoration")
            code, report = fixture.run()
            self.assertEqual((code, report["outcome"]), (1, "fail"))
            self.assertEqual([cell["outcome"] for cell in report["cells"]], ["expected_failure", "blocked"])
            for engine in ("rtl", "simx"):
                self.assertTrue((fixture.paths["output"] / ("logs/" + engine + "-run.log")).is_file())

    def test_source_reference_generated_binary_and_tools_drift_invalidate_success(self):
        for what in ("source", "helper", "reference", "generated", "binary", "tool", "reference-revision"):
            with self.subTest(what=what), ParentFixture() as fixture:
                def mutate(command, cwd):
                    if command != "rtl-run":
                        return
                    if what == "reference-revision":
                        fixture.reference_revision = "f" * 40
                        return
                    paths = {"source": fixture.paths["source"] / "sim/simx/core.cpp",
                             "helper": fixture.paths["source"] / parent.SELF,
                             "reference": fixture.paths["work"] / "reference/sim/simx/core.cpp",
                             "generated": fixture.paths["work"] / "rv64-perf-on/hw/VX_config.vh",
                             "binary": cwd / "mpm_transport", "tool": fixture.tool_paths["make"]}
                    with paths[what].open("ab") as stream:
                        stream.write(b"changed fixture bytes\n")
                fixture.after_command = mutate
                code, report = fixture.run()
                self.assertEqual((code, report["outcome"]), (1, "fail"), what)
                self.assertFalse(report["qualified"])
                self.assertEqual(report["state"], "finished")
                self.assertIn("chang", report["reason"], report["reason"])


if __name__ == "__main__":
    unittest.main()
