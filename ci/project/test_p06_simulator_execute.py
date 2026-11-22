# SPDX-License-Identifier: Apache-2.0
"""Host-only native-runner boundaries; these tests do not execute the model."""

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import p06_simulator_execute as runner
from test_p02_matrix import sample


UNIT_OUTPUT = "\n".join((
    "native_x3 gp=7 checked_launches=3 legacy_launches=1",
    "native_x3 gp=-1 checked_launches=3 legacy_launches=1",
    "native_legacy_exception result=-1",
    "native_exception type=OutOfRange consumed=1",
    "native_x3 gp=7 checked_launches=3 legacy_launches=1",
    "PASSED simx_completion native_unit contexts=5 checked_success=9 legacy_success=3 checked_exceptions=1 legacy_errors=1",
)) + "\n"


def public_output(gp=0x180001800):
    rows = []
    for context in range(2):
        for launch in range(3):
            value = 0x13579bdf ^ (0x2468ace0 + 17 * launch + context)
            rows.append(f"native_success context={context} launch={launch} gp={gp:016x} value={value:08x}")
    return "\n".join(rows + ["PASSED simx_completion native_success contexts=2 launches=6 gp_nonzero=6"]) + "\n"


class OutputTests(unittest.TestCase):
    def test_unit_complete_with_model_diagnostics(self):
        result = runner.verify_output("model diagnostic\n" + UNIT_OUTPUT + "model totals\n", "unit")
        self.assertEqual(result["checked_exceptions"], 1)
        self.assertEqual(result["legacy_success"], 3)

    def test_unit_requires_each_ordered_observation(self):
        rows = UNIT_OUTPUT.splitlines()
        for altered in (rows[1:], rows + rows[:1], rows[:2] + rows[3:4] + rows[2:3] + rows[4:],
                        rows + ["FAILED simx_completion native_unit: error"]):
            with self.subTest(altered=altered), self.assertRaises(ValueError):
                runner.verify_output("\n".join(altered), "unit")

    def test_public_requires_six_correct_nonzero_gp_launches(self):
        result = runner.verify_output(public_output(), "public")
        self.assertEqual((result["contexts"], result["launches"], result["gp_nonzero"]), (2, 6, 6))
        self.assertEqual(len(result["witnesses"]), 6)

    def test_public_rejects_zero_low_word_even_when_high_word_nonzero(self):
        for gp in (0, 1 << 32):
            with self.subTest(gp=gp), self.assertRaises(ValueError):
                runner.verify_output(public_output(gp), "public")

    def test_public_rejects_missing_repeated_mismatched_or_failed_launches(self):
        rows = public_output().splitlines()
        alternatives = (rows[1:], rows[:-1] + rows[:1] + rows[-1:],
                        [rows[1], rows[0], *rows[2:]],
                        [rows[0].split("value=")[0] + "value=00000000", *rows[1:]],
                        rows + ["FAILED simx_completion: error"])
        for altered in alternatives:
            with self.subTest(altered=altered), self.assertRaises(ValueError):
                runner.verify_output("\n".join(altered), "public")


class CompilerRecordTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="completion-records-")
        self.addCleanup(self.directory.cleanup)
        self.build = Path(self.directory.name)
        self.configs = ["-DVX_CFG_XLEN=64", "-DVX_CFG_FPU_TYPE=STD", "-DVX_CFG_TCU_TYPE=TFR"]
        # Adapt independent retained Makefile samples to this caller. There
        # are no tensor-format/unroll selectors or extra host helper include.
        def completion_sample(name):
            text = sample(name, source=runner.ROOT, build=self.build)
            for flag in ("-DITYPE=bf16", "-DOTYPE=fp32", "-DKUNROLL=1",
                         "-I" + str(runner.ROOT / "third_party/softfloat/source/include"),
                         str(runner.ROOT / "third_party/softfloat/build/Linux-x86_64-GCC/softfloat.a")):
                if (flag.startswith("-I") or flag.startswith("/")) and name != "application":
                    continue
                text = text.replace(flag, "")
            return text

        model = completion_sample("simx_backend").rstrip("\n") + " -DPERF_ENABLE\n"
        unit_model = model.replace(str(self.build / "sw/runtime/simx_config.stamp"),
                                   str(self.build / "sim/simx/simx_config.stamp"))
        self.contents = [unit_model, model, completion_sample("simx_rt"),
                         completion_sample("application")]
        for name, text in zip(runner.STAMPS, self.contents):
            path = self.build / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

    def test_each_original_record_is_validated_and_retains_identity(self):
        before = [path.read_bytes() for path in map(self.build.__truediv__, runner.STAMPS)]
        rows = runner.validate_compiler_records(self.build, self.configs)
        self.assertEqual([row["role"] for row in rows], ["unit_model", "runtime_model", "runtime", "kernel", "host"])
        originals = [*self.contents[:3], *self.contents[3].splitlines()[:2]]
        tools = {name: {"path": "/completion-tools/" + name} for name in ("g++", "clang++")}
        for row, original in zip(rows, originals):
            with self.subTest(role=row["role"]):
                text = original.rstrip("\n")
                self.assertEqual(row["sha256"], hashlib.sha256(text.encode()).hexdigest())
                self.assertEqual(row["compiler_flags"], runner._stamp_words(text, row["role"]))
                self.assertNotIn("-MF", row["probe_flags"])
                self.assertNotIn("-MMD", row["probe_flags"])
                self.assertNotIn("-MP", row["probe_flags"])
                argv, cwd = runner.effective_header_command(tools, self.build, Path("/completion-tools"), row)
                expected_compiler = "clang++" if row["role"] == "kernel" else "g++"
                self.assertEqual(argv[0], tools[expected_compiler]["path"])
                self.assertEqual(argv[-len(row["probe_flags"]) - 5:-5], row["probe_flags"])
                self.assertEqual(argv[-5:], ["-E", "-dM", "-x", "c++", self.build / "completion-header.cpp"])
                expected_directory = "sim/simx" if row["role"].endswith("_model") else (
                    "sw/runtime/simx" if row["role"] == "runtime" else runner.APP)
                self.assertEqual(cwd, self.build / expected_directory)
        self.assertEqual([path.read_bytes() for path in map(self.build.__truediv__, runner.STAMPS)], before)

    def test_performance_selection_is_checked_for_each_model(self):
        for name, text in zip(runner.STAMPS[:2], self.contents[:2]):
            path = self.build / name
            path.write_text(text.replace(" -DPERF_ENABLE", ""), encoding="utf-8")
            with self.subTest(name=name), self.assertRaises(ValueError):
                runner.validate_compiler_records(self.build, self.configs)
            path.write_text(text, encoding="utf-8")

    def test_one_record_cannot_borrow_another_records_configuration(self):
        for name, text in zip(runner.STAMPS, self.contents):
            path = self.build / name
            path.write_text(text.replace("-DVX_CFG_XLEN=64", "-DVX_CFG_XLEN=32", 1), encoding="utf-8")
            with self.subTest(name=name), self.assertRaises(ValueError):
                runner.validate_compiler_records(self.build, self.configs)
            path.write_text(text, encoding="utf-8")


class PreflightTests(unittest.TestCase):
    def run_blocked(self, free, memory):
        with tempfile.TemporaryDirectory(prefix="completion-blocked-") as directory:
            root = Path(directory)
            paths = {name: root / name for name in ("source", "tools", "work", "output")}
            for name in ("source", "tools"):
                paths[name].mkdir()
            paths.update(host_bin=None, verilator=paths["tools"] / "verilator")
            resources = {"free_disk_bytes": {name: free for name in ("source", "tools", "work", "output")},
                         "available_memory_bytes": memory}
            with mock.patch.object(runner.base, "_resources", return_value=resources), \
                    mock.patch.object(runner, "run_bounded") as bounded:
                report = runner.execute(None, paths)
            bounded.assert_not_called()
            self.assertEqual(report, json.loads((paths["output"] / "report.json").read_text()))
            return report

    def test_low_disk_preserves_blocked_report_without_starting_processes(self):
        report = self.run_blocked(runner.BUDGET["min_free_bytes"] - 1, 8 * 1024**3)
        self.assertEqual(report["outcome"], "blocked")
        self.assertIn("15 GiB", report["reason"])
        self.assertFalse(report["full_matrix_completed"])
        self.assertTrue(all(cell["outcome"] == "blocked" for cell in report["cells"]))

    def test_missing_or_insufficient_memory_does_not_start_processes(self):
        for memory in (None, 4 * 1024**3 - 1):
            with self.subTest(memory=memory):
                report = self.run_blocked(30 * 1024**3, memory)
                self.assertEqual(report["outcome"], "blocked")
                self.assertIn("4 GiB", report["reason"])

    def test_executing_interpreter_is_distinct_from_path_python(self):
        with mock.patch.object(runner.base, "tool_inventory", return_value={"python3": {"path": "/other/python3"}}), \
                mock.patch.object(runner.base, "_file_identity", side_effect=lambda path: {"path": str(path)}) as identity:
            result = runner.tool_snapshot({}, {})
        identity.assert_called_once_with(sys.executable)
        self.assertEqual(result["python3"]["path"], "/other/python3")
        self.assertEqual(result["executing_python"]["path"], sys.executable)


if __name__ == "__main__":
    unittest.main()
