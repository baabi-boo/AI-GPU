# SPDX-License-Identifier: Apache-2.0
"""Compiled observation-wrapper controls; controlled processor, not native SimX."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "ci/project/fixtures/p06_native_lifetime_hooks"
HOOKS = ROOT / "tests/regression/ai_counter_preflight"
PARENT_REJECTION = "FAILED pending-before-reset: reset-bearing real run was entered\n"


def compile_control(source, build, *, parent_control=False):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if compiler is None:
        raise RuntimeError("compiled lifetime controls require a C++17 compiler with UBSan")
    binary = build / "hooks-control"
    command = [compiler, "-std=c++17", "-O1", "-Wall", "-Wextra", "-Werror",
               "-fsanitize=undefined", "-fno-sanitize-recover=undefined", "-pthread",
               "-DSIMX_CHECKED_COUNTERS=1", "-DVX_CFG_XLEN=64",
               "-I" + str(source), "-I" + str(FIXTURE), "-I" + str(ROOT / "sim/common")]
    if parent_control:
        command.append("-DP06_PARENT_CONTROL=1")
    command.extend([str(source / "hooks.cpp"), str(FIXTURE / "harness.cpp"), "-o", str(binary)])
    result = subprocess.run(command, cwd=build, text=True, capture_output=True, timeout=120)
    if result.returncode != 0:
        raise AssertionError("lifetime control compilation failed:\n" + result.stdout + result.stderr)
    return binary, {"argv": command, "returncode": result.returncode,
                    "stdout": result.stdout, "stderr": result.stderr}


def run_control(binary, *arguments):
    environment = dict(os.environ, UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=0")
    return subprocess.run([str(binary), *arguments], cwd=binary.parent, env=environment,
                          text=True, capture_output=True, timeout=15)


class NativeLifetimeHookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="p06-lifetime-hooks-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.binary, cls.build = compile_control(HOOKS, Path(cls.temporary.name))

    def cases(self, names):
        for name in names:
            with self.subTest(case=name):
                result = run_control(self.binary, name)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(result.stdout, "PASS " + name + "\n")
                self.assertEqual(result.stderr, "")

    def test_full_33_run_trace_preserves_successful_nonzero_legacy_gp(self):
        self.cases(("success-seven", "success-minus-one"))

    def test_default_v1_does_not_query_or_enforce_lifetime_observations(self):
        self.cases(("default-v1",))

    def test_pre_run_failures_reject_before_real_reset_or_balance_erasure(self):
        self.cases(("before-pending", "before-idle", "before-running", "reset-exhausted"))

    def test_post_run_failures_keep_real_return_but_invalidate_the_lifetime(self):
        self.cases(("after-pending", "after-idle", "after-running", "reset-skip", "reset-extra"))

    def test_real_execution_exceptions_survive_secondary_observation_faults(self):
        self.cases(("run-exception-standard", "run-exception-nonstandard", "run-exception-secondary",
                    "run-exception-overflow", "run-exception-underflow", "run-exception-negative"))

    def test_read_exceptions_survive_secondary_observation_faults(self):
        self.cases(("read-exception-standard", "read-exception-nonstandard",
                    "read-exception-secondary", "read-exception-overflow"))

    def test_raw_and_flush_reads_require_zero_pending_on_both_sides(self):
        self.cases(("read-before", "read-after", "flush-before", "flush-after"))

    def test_failed_dcr_status_and_absent_reply_remain_failures(self):
        self.cases(("read-status", "flush-status", "read-null"))

    def test_bounded_traces_reject_before_another_real_operation(self):
        self.cases(("run-capacity", "read-capacity", "flush-capacity"))

    def test_late_duplicate_and_changed_ownership_cannot_rehabilitate_a_lifetime(self):
        self.cases(("late-enable", "duplicate-enable", "wrong-owner", "reconstruct"))

    def test_invalid_destructor_observation_still_disposes_without_dead_reads(self):
        self.cases(("destructor-pending", "destructor-secondary"))


def parent_sensitivity(revision, output):
    """Run an explicit Git-parent comparison outside shallow-checkout unit discovery."""
    if re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        raise ValueError("parent control requires a full lowercase Git revision")
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {"scope": "compiled-controlled-hooks-parent-sensitivity", "parent_revision": revision,
              "native_execution": "not_run", "qualification_claimed": False, "variants": []}
    for variant in ("parent", "candidate"):
        build = output / variant
        build.mkdir()
        source = HOOKS
        if variant == "parent":
            source = build / "source"
            source.mkdir()
            for name in ("hooks.h", "hooks.cpp"):
                relative = HOOKS.relative_to(ROOT).as_posix() + "/" + name
                original = subprocess.run(["git", "show", revision + ":" + relative], cwd=ROOT,
                                          capture_output=True, check=True, timeout=30)
                (source / name).write_bytes(original.stdout)
        binary, compiled = compile_control(source, build, parent_control=True)
        result = run_control(binary)
        bodies = [source / "hooks.h", source / "hooks.cpp", FIXTURE / "core.h",
                  FIXTURE / "processor.h", FIXTURE / "harness.cpp", ROOT / "sim/common/perf_counter.h"]
        row = {"variant": variant, "compile": compiled, "run": {
                   "argv": [str(binary)], "returncode": result.returncode,
                   "stdout": result.stdout, "stderr": result.stderr},
               "source_files": [{"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                                 "size_bytes": path.stat().st_size} for path in bodies]}
        report["variants"].append(row)
        (output / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    parent, candidate = report["variants"]
    report["passed"] = (parent["run"]["returncode"] == 1
        and parent["run"]["stdout"] == "" and parent["run"]["stderr"] == PARENT_REJECTION
        and candidate["run"]["returncode"] == 0
        and candidate["run"]["stdout"] == "PASS pending-before-reset\n"
        and candidate["run"]["stderr"] == "")
    (output / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"passed": report["passed"], "report": str(output / "report.json")}, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--parent-control":
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--parent-control", required=True)
        parser.add_argument("--output", required=True, type=Path)
        arguments = parser.parse_args()
        sys.exit(parent_sensitivity(arguments.parent_control, arguments.output))
    unittest.main()
