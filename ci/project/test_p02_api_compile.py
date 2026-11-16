# SPDX-License-Identifier: Apache-2.0
"""Host-only parser controls; these do not qualify the real compiler matrix."""

from pathlib import Path
import contextlib
import io
import tempfile
import unittest
from unittest import mock

import p02_api_compile as api


class CompilerDiagnosticControls(unittest.TestCase):
    def setUp(self):
        self.header = Path("/checked/source/sw/kernel/include/vx_tensor.h")
        self.case = api.Case("disabled", "fp16", diagnostic=api.INPUT_DIAGNOSTIC)
        self.rejected = {"process_started": True, "cleanup_complete": True,
                         "outcome": "fail", "exit_code": 1, "reason": "nonzero_exit"}

    def diagnostic(self, context, message=None, header=None):
        return (f"{header or self.header}:276:3: error: static assertion failed due to "
                f"requirement 'detail::tfr_input_enabled(fp16::id)': "
                f"{message or api.INPUT_DIAGNOSTIC}\n"
                f"/checked/output/probe.cpp:58:15: note: in instantiation of template class "
                f"'vortex::tensor::{context}<8, vortex::tensor::fp16, vortex::tensor::fp32>' "
                "requested here\n")

    def check(self, log, result=None, case=None):
        return api.judge_compile(case or self.case, result or self.rejected,
                                 log, self.header)[0]

    def test_exact_diagnostic_requires_both_contexts(self):
        wmma = self.diagnostic("wmma_context")
        wgmma = self.diagnostic("wgmma_context")
        self.assertTrue(self.check(wmma + wgmma))
        self.assertFalse(self.check(wmma))
        self.assertFalse(self.check(wgmma))

    def test_unrelated_errors_cannot_qualify_even_alongside_target_assertions(self):
        valid = "".join(self.diagnostic(context) for context in api.CONTEXTS)
        for additional in ("clang++: error: invalid argument '--bad'\n",
                           "/checked/output/probe.cpp:1:10: fatal error: header not found\n",
                           f"{self.header}:277:3: error: unexpected token\n"):
            with self.subTest(additional=additional):
                self.assertFalse(self.check(valid + additional))

    def test_wrong_assertion_and_wrong_file_cannot_qualify(self):
        for message, header in ((api.OUTPUT_DIAGNOSTIC, self.header),
                                (api.INPUT_DIAGNOSTIC, Path("/other/vx_tensor.h"))):
            log = "".join(self.diagnostic(c, message, header) for c in api.CONTEXTS)
            self.assertFalse(self.check(log))

    def test_quoted_source_text_is_not_a_compiler_rejection(self):
        log = f'  static_assert(false, "{api.INPUT_DIAGNOSTIC}");\n'
        self.assertFalse(self.check(log))
        self.assertFalse(self.check(""))

    def test_budget_signal_launch_and_cleanup_failures_never_qualify(self):
        log = "".join(self.diagnostic(context) for context in api.CONTEXTS)
        for alteration in ({"reason": "timeout"}, {"exit_code": -9},
                           {"exit_code": 2}, {"process_started": False},
                           {"cleanup_complete": False}, {"outcome": "blocked"}):
            with self.subTest(alteration=alteration):
                self.assertFalse(self.check(log, {**self.rejected, **alteration}))

    def test_blanket_rejection_cannot_satisfy_positive_control(self):
        positive = api.Case("enabled", "fp16", enabled=("FP16",))
        log = "".join(self.diagnostic(context) for context in api.CONTEXTS)
        self.assertFalse(self.check(log, case=positive))
        succeeded = {**self.rejected, "exit_code": 0, "outcome": "pass", "reason": None}
        self.assertTrue(self.check("", succeeded, positive))
        self.assertFalse(self.check("", succeeded))


class CompilerMatrixPlanning(unittest.TestCase):
    def test_false_configuration_uses_disable_not_zero_enable(self):
        case = api.Case("fp16_disabled", "fp16", diagnostic=api.INPUT_DIAGNOSTIC)
        flags = api.config_flags(case, 64)
        self.assertIn("-DVX_CFG_TCU_FP16_DISABLE", flags)
        self.assertNotIn("-DVX_CFG_TCU_FP16_ENABLE=0", flags)
        self.assertNotIn("-DVX_CFG_TCU_FP16_ENABLE", flags)
        source = api.case_source(case, 64)
        self.assertIn("#if defined(VX_CFG_TCU_FP16_ENABLE)", source)
        for context in api.CONTEXTS:
            self.assertIn(f"sizeof({context}_probe)", source)

    def test_empty_profile_does_not_consume_following_make_line(self):
        text = "PROFILE ?= \nifneq ($(strip $(PROFILE)),)\nXLEN ?= 64\n"
        self.assertEqual(api.make_setting(text, "PROFILE"), "")
        self.assertEqual(api.make_setting(text, "XLEN"), "64")
        with self.assertRaises(ValueError):
            api.make_setting("XLEN ?= $(OTHER)\n", "XLEN")

    def test_each_mx_prerequisite_has_an_isolated_negative_control(self):
        cases = api.matrix()
        self.assertEqual(len(cases), 47)
        for family in ("mxfp8", "mxbf8", "mxfp4", "nvfp4"):
            positive = next(c for c in cases if c.name == family + "_enabled")
            for guard in positive.enabled:
                negative = next(c for c in cases if c.name == family + "_without_" + guard.lower())
                self.assertEqual(set(positive.enabled) - set(negative.enabled), {guard})
                self.assertEqual(negative.diagnostic, api.INPUT_DIAGNOSTIC)


class CompilerDependencyControls(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.cpp = self.root / "probe.cpp"
        self.cpp.write_text("// probe\n")
        self.header = self.root / "header.h"
        self.header.write_text("// original header\n")

    def parse(self, body):
        return api.parse_dependencies(body, self.root, (self.cpp,))

    def test_make_escapes_and_continuations_preserve_exact_paths(self):
        unusual = self.root / "header #$ name.h"
        unusual.write_text("// another header\n")
        text = "p02_dependencies: probe.cpp \\\n header\\ \\#$$\\ name.h header.h\n"
        self.assertEqual(self.parse(text), (self.cpp, unusual, self.header))

    def test_malformed_missing_and_truncated_dependencies_fail_closed(self):
        for text in ("", "p02_dependencies: \n", "p02_dependencies: probe.cpp",
                     "p02_dependencies: probe.cpp\np02_other: header.h\n",
                     "p02_dependencies: probe.cpp\nclang++: warning: ignored option\n",
                     "p02_dependencies: header.h\n", "other: probe.cpp\n",
                     "p02_dependencies: probe.cpp missing.h\n",
                     "p02_dependencies: probe.cpp $(HEADER)\n",
                     "p02_dependencies: probe.cpp header\\x.h\n",
                     "p02_dependencies: probe.cpp # comment\n"):
            with self.subTest(text=text), self.assertRaises((OSError, ValueError)):
                self.parse(text)
        with mock.patch.object(api, "MAX_DEPENDENCIES", 1), self.assertRaises(ValueError):
            self.parse("p02_dependencies: probe.cpp header.h\n")

    def test_selected_header_content_removal_and_symlink_drift_are_detected(self):
        alias = self.root / "selected.h"
        alias.symlink_to(self.header)
        identities = api.snapshot({"selected": alias}, self.root / "packet")
        self.assertEqual(api.identity_drift(identities), [])
        other = self.root / "other.h"
        other.write_bytes(self.header.read_bytes())
        alias.unlink()
        alias.symlink_to(other)
        self.assertEqual(api.identity_drift(identities), ["selected"])
        alias.unlink()
        alias.symlink_to(self.header)
        self.header.write_text("// modified header\n")
        self.assertEqual(api.identity_drift(identities), ["selected"])
        self.header.unlink()
        self.assertEqual(api.identity_drift(identities), ["selected"])


class CompilerRunAccountingControls(unittest.TestCase):
    """Inject failures around actual launch accounting, without claiming compiler evidence."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.build = self.root / "build"
        self.tools = self.root / "tools"
        self.output = self.root / "packet"
        self.sysroot = self.tools / "riscv64-gnu-toolchain/riscv64-unknown-elf"
        self.resource = self.tools / "llvm-vortex/lib/clang/20"
        for path in (self.source / "VX_config.toml", self.source / "VX_types.toml",
                     self.source / "ci/gen_config.py", self.build / "ci/gen_config.py",
                     self.build / "sw/VX_config.h", self.build / "sw/VX_types.h",
                     self.source / "sw/kernel/include/vx_tensor.h",
                     self.tools / "llvm-vortex/bin/clang++",
                     self.sysroot / "include/stdint.h", self.resource / "include/stddef.h"):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture\n")
        (self.build / "config.mk").write_text(
            f"VORTEX_HOME ?= {self.source}\nXLEN ?= 64\nPROFILE ?= \n")
        self.launches = 0
        self.failure = None
        self.drift = False
        self.bad_probe_dependencies = False
        self.bad_compile_dependencies = False
        self.changed_compile_dependencies = False

    def dependency_text(self, cpp):
        paths = (Path(cpp), self.source / "sw/kernel/include/vx_tensor.h",
                 self.build / "sw/VX_config.h", self.build / "sw/VX_types.h",
                 self.sysroot / "include/stdint.h", self.resource / "include/stddef.h")
        return api.DEPENDENCY_TARGET + ": " + " ".join(map(str, paths)) + "\n"

    def execute(self, argv, cwd, env, directory, label):
        log = directory / (label + ".log")
        result = {"outcome": "pass", "process_started": True, "cleanup_complete": True,
                  "exit_code": 0, "reason": None, "log": str(log)}
        text = ""
        if label == "compiler-resource-dir":
            text = str(self.resource) + "\n"
        elif label.startswith("regenerate-"):
            Path(argv[argv.index("--output") + 1]).write_text("fixture\n")
        elif label == "resolve-config":
            text = "-DRESOLVED=1\n"
        elif label == "dependencies":
            self.assertNotIn("-MM", argv)
            self.assertIn("-M", argv)
            text = "broken\n" if self.bad_probe_dependencies else self.dependency_text(argv[-1])
        elif label == "compile":
            self.launches += 1
            self.assertIn("-MD", argv)
            depfile = Path(argv[argv.index("-MF") + 1])
            dependencies = self.dependency_text(argv[-1])
            if self.changed_compile_dependencies:
                unexpected = self.sysroot / "include/unexpected.h"
                unexpected.write_text("// newly selected header\n")
                dependencies = dependencies.rstrip("\n") + " " + str(unexpected) + "\n"
            depfile.write_text("broken\n" if self.bad_compile_dependencies else dependencies)
            if self.drift and self.launches == 47:
                (self.sysroot / "include/stdint.h").write_text("changed\n")
        if self.failure and label == self.failure[0]:
            result.update(self.failure[1])
        log.write_text(text)
        result["log_sha256"] = api.sha256(log)
        return result

    def run_packet(self):
        with (mock.patch.object(api.Path, "cwd", return_value=self.build),
              mock.patch.object(api, "execute", side_effect=self.execute),
              mock.patch.object(api, "judge_compile", return_value=(True, "test double")),
              contextlib.redirect_stdout(io.StringIO())):
            return api.run(self.build, self.tools, self.output)

    def test_first_configuration_failure_leaves_all_47_compiles_not_run(self):
        self.failure = ("resolve-config", {"outcome": "fail", "exit_code": 1, "reason": "nonzero_exit"})
        report = self.run_packet()
        self.assertEqual(report["outcome"], "fail")
        self.assertEqual(report["not_run_cases"], 47)
        self.assertEqual(report["launched_cases"], 0)
        self.assertEqual(report["failed_cases"], 0)
        self.assertEqual(len(report["cases"]), 1)
        self.assertEqual(self.launches, 0)

    def test_failed_launch_is_not_a_launched_case(self):
        self.failure = ("compile", {"outcome": "blocked", "process_started": False,
                                    "exit_code": None, "reason": "disk_reserve"})
        report = self.run_packet()
        self.assertEqual(len(report["cases"]), 47)
        self.assertEqual(report["not_run_cases"], 47)
        self.assertEqual(report["launched_cases"], 0)
        self.assertEqual(report["cases"][0]["outcome"], "not_run")

    def test_started_resource_failure_counts_one_compile(self):
        self.failure = ("compile", {"outcome": "fail", "exit_code": -9, "reason": "timeout"})
        report = self.run_packet()
        self.assertEqual(report["not_run_cases"], 46)
        self.assertEqual(report["launched_cases"], 1)
        self.assertEqual(report["failed_cases"], 1)

    def test_actual_compile_dependency_parse_failure_cannot_pass(self):
        self.bad_compile_dependencies = True
        report = self.run_packet()
        self.assertEqual(report["outcome"], "fail")
        self.assertEqual(report["passed_cases"], 0)
        self.assertEqual(report["not_run_cases"], 46)

    def test_dependency_probe_parse_failure_prevents_every_compile(self):
        self.bad_probe_dependencies = True
        report = self.run_packet()
        self.assertEqual(report["outcome"], "fail")
        self.assertEqual(report["not_run_cases"], 47)
        self.assertEqual(self.launches, 0)

    def test_changed_include_selection_fails_before_next_compile(self):
        self.changed_compile_dependencies = True
        report = self.run_packet()
        self.assertEqual(report["outcome"], "fail")
        self.assertIn("include selection changed", report["error"])
        self.assertEqual(report["not_run_cases"], 46)
        self.assertEqual(report["passed_cases"], 0)

    def test_system_header_drift_invalidates_completed_matrix(self):
        self.drift = True
        report = self.run_packet()
        self.assertEqual(report["outcome"], "fail")
        self.assertEqual(report["not_run_cases"], 0)
        self.assertEqual(report["launched_cases"], 47)
        self.assertTrue(report["identity_drift"])
        selected = {item["path"] for item in report["include_dependencies"].values()}
        self.assertIn(str(self.sysroot / "include/stdint.h"), selected)
        self.assertIn(str(self.resource / "include/stddef.h"), selected)


if __name__ == "__main__":
    unittest.main()
