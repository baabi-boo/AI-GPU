# SPDX-License-Identifier: Apache-2.0
"""Offline negative controls; synthetic records never certify native execution."""

from contextlib import ExitStack, redirect_stderr
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import p02_wgmma_unit as unit


EXPECTED_GROUPS = (
    ("dense_ss_initial", 64, 512), ("dense_ss_descriptor_reuse", 64, 512),
    ("dense_ss_row_major", 64, 512), ("dense_rs_bf16", 64, 512),
    ("cta_exclusion", 32, 256), ("sparse_metadata_initial", 36, 256),
    ("sparse_metadata_reload", 36, 256), ("dense_rs_commit_pressure", 32, 256),
)


def arguments(*extra):
    return unit.argument_parser().parse_args([
        "run", "--tools-dir", "/unit/tools", "--work-dir", "/unit/work", "--output", "/unit/output", *extra])


def output():
    rows = [f"WGMMA_GROUP name={name} accepted={count} commits={count} words={words} cycles={100 + index}"
            for index, (name, count, words) in enumerate(EXPECTED_GROUPS)]
    coverage = dict(accepted=392, commits=392, words=3072, dispatch_stalls=30, commit_holds=27,
                    lmem_holds=32, lmem_requests=200, lmem_responses=200, delayed_lmem=80,
                    metadata_requests=8, metadata_writes=16, metadata_lanes=64, delayed_metadata=8,
                    cta_conflicts=4, cta_entries=1, overlapping=12, pressure_holds=19,
                    pressure_qualified=9, pressure_tail=8, descriptor_a_poisoned=238,
                    descriptor_b_poisoned=357, cycles=sum(100 + i for i in range(8)),
                    watchdog=100000, pressure_limit=256)
    rows.append("WGMMA_COVERAGE " + " ".join(f"{key}={value}" for key, value in coverage.items()))
    return "\n".join(rows + ["WGMMA_DIRECTED_PASS"]) + "\n"


def stamp(source=Path("/unit/source"), build=Path("/unit/build"), jobs=2):
    flags = " ".join(unit.CONFIGS) + " -DVX_CFG_XLEN=64 -DVX_CFG_XLEN_64"
    cpp = " ".join("-I" + str(path) for path in (source / unit.UNIT, build / "sw", build / "hw"))
    cpp += " -std=c++17 -Wall -Wextra -Wfatal-errors -Werror -fPIC -O2 " + flags + " -DNDEBUG -UNDEBUG"
    rtl = "--exe --language 1800-2012 --assert -Wall -Wpedantic -Wno-DECLFILENAME -Wno-REDEFMACRO "
    rtl += "-Wno-GENUNNAMED --x-initial unique --x-assign unique ../verilator.vlt -DSIMULATION " + flags
    rtl += " " + " ".join("-I" + str(path) for path in (build / "sw", build / "hw"))
    rtl += " " + " ".join("-I" + str(source / "hw/rtl" / path) for path in
                          ("", "libs", "tcu", "tcu/tfr", "interfaces", "core", "mem"))
    rtl += " -I" + str(source / unit.UNIT)
    rtl += " " + str(source / "hw/rtl/VX_gpu_pkg.sv") + " " + str(source / "hw/rtl/tcu/VX_tcu_pkg.sv")
    rtl += f" --cc {unit.TOP} --top-module {unit.TOP} -j {jobs} -DNDEBUG -UNDEBUG"
    return cpp + "\n" + rtl + "\n\n"


def effective_header():
    defines = unit._stamp_defines(" ".join(unit.CONFIGS), "test fixture")
    defines.update(VX_CFG_XLEN="64", VX_CFG_XLEN_64="1", VX_CFG_NUM_LSU_LANES="8")
    return "\n".join(f"#define {key} {value}" for key, value in defines.items()) + "\n"


class OutputTests(unittest.TestCase):
    def test_complete_schedule_reconciles_exact_inventory_and_coverage(self):
        observed = unit.verify_output(output())
        self.assertEqual((observed["group_count"], observed["accepted_transactions"],
                          observed["committed_transactions"], observed["checked_output_words"]), (8, 392, 392, 3072))
        self.assertEqual(observed["cycle_watchdog_per_group"], 100000)
        self.assertEqual([row["name"] for row in observed["groups"]], [row[0] for row in EXPECTED_GROUPS])

    def test_missing_duplicate_reordered_scenario_and_pass_reject(self):
        rows = output().splitlines()
        for index in range(len(rows)):
            for mutant in (rows[:index] + rows[index + 1:], rows[:index] + [rows[index]] + rows[index:]):
                with self.subTest(index=index), self.assertRaises(ValueError):
                    unit.verify_output("\n".join(mutant))
        for index in range(7):
            mutant = rows.copy()
            mutant[index], mutant[index + 1] = mutant[index + 1], mutant[index]
            with self.subTest(reorder=index), self.assertRaises(ValueError):
                unit.verify_output("\n".join(mutant))

    def test_aggregate_stalls_cannot_replace_causal_pressure_or_descriptor_poison(self):
        for old, new in (("pressure_qualified=9", "pressure_qualified=0"),
                         ("pressure_tail=8", "pressure_tail=7"), ("pressure_holds=19", "pressure_holds=8"),
                         ("pressure_holds=19", "pressure_holds=257"), ("pressure_qualified=9", "pressure_qualified=20"),
                         ("descriptor_a_poisoned=238", "descriptor_a_poisoned=237"),
                         ("descriptor_b_poisoned=357", "descriptor_b_poisoned=0")):
            with self.subTest(old=old, new=new), self.assertRaises(ValueError):
                unit.verify_output(output().replace(old, new))

    def test_counter_identity_zero_coverage_and_watchdog_mutations_reject(self):
        replacements = (("accepted=392", "accepted=391"), ("commits=392", "commits=393"),
                        ("words=3072", "words=3071"), ("lmem_responses=200", "lmem_responses=199"),
                        ("metadata_requests=8", "metadata_requests=7"), ("metadata_writes=16", "metadata_writes=8"),
                        ("metadata_lanes=64", "metadata_lanes=63"), ("delayed_metadata=8", "delayed_metadata=0"),
                        ("cycles=100", "cycles=100000"), ("watchdog=100000", "watchdog=100001"),
                        ("pressure_limit=256", "pressure_limit=512"), ("cycles=828", "cycles=829"))
        for old, new in replacements:
            with self.subTest(old=old, new=new), self.assertRaises(ValueError):
                unit.verify_output(output().replace(old, new))
        for key in ("dispatch_stalls", "commit_holds", "lmem_holds", "delayed_lmem", "cta_conflicts",
                    "cta_entries", "overlapping"):
            rows = output().splitlines()
            words = rows[-2].split()
            rows[-2] = " ".join(key + "=0" if word.startswith(key + "=") else word for word in words)
            with self.subTest(zero=key), self.assertRaises(ValueError):
                unit.verify_output("\n".join(rows))

    def test_malformed_extra_negative_and_failure_output_reject(self):
        text = output()
        for mutant in (text + "WGMMA_DIRECTED_FAIL hidden\n", text + "error: failed\n", text + "\x00",
                       text.replace("accepted=392", "accepted=-392"), text.replace("commits=392", "commits=392.0"),
                       text.replace("accepted=392", "accepted=392 accepted=392"),
                       text.replace("WGMMA_COVERAGE ", "prefix WGMMA_COVERAGE "),
                       text.replace("WGMMA_COVERAGE ", "WGMMA_COVERAGE extra=1 "),
                       "x" * (unit.BUDGET["max_log_bytes"] + 1)):
            with self.subTest(length=len(mutant)), self.assertRaises(ValueError):
                unit.verify_output(mutant)


class ConfigurationTests(unittest.TestCase):
    def test_separate_cpp_and_rtl_stamps_and_effective_header_accept(self):
        self.assertEqual([row["role"] for row in unit.validate_stamp(stamp(), Path("/unit/source"), Path("/unit/build"), 2)],
                         ["host_cpp", "verilator"])
        self.assertEqual(unit.validate_header(effective_header())["VX_CFG_NUM_LSU_LANES"], "8")

    def test_each_stamp_record_rejects_controls_and_unicode_separators(self):
        controls = ("\x00", "\x01", "\x1b", "\x7f", "\x80", "\x85", "\r", "\v", "\f",
                    "\u00a0", "\u2003", "\u2028", "\u2029")
        for index in (0, 1):
            for control in controls:
                lines = stamp().split("\n")
                lines[index] += " -DIGNORED=" + control + "value"
                with self.subTest(record=index, control=repr(control)), self.assertRaisesRegex(
                        ValueError, "unsupported control characters or record separators"):
                    unit.validate_stamp("\n".join(lines), Path("/unit/source"), Path("/unit/build"), 2)

    def test_stamp_keeps_empty_linker_and_supported_argument_whitespace(self):
        for text in (stamp(), stamp().replace(" -std=c++17", "\t-std=c++17", 1)
                     .replace("--exe --language", "--exe\t--language", 1)):
            with self.subTest(tabs="\t" in text):
                self.assertEqual(text.splitlines()[2], "")
                self.assertEqual([row["role"] for row in unit.validate_stamp(
                    text, Path("/unit/source"), Path("/unit/build"), 2)], ["host_cpp", "verilator"])

    def test_each_record_requires_fixed_geometry_native_flags_and_assertions(self):
        for index in (0, 1):
            for flag in ("-DVX_CFG_NUM_THREADS=8", "-DVX_CFG_TCU_TYPE_TFR", "-DVX_CFG_TCU_SPARSE_ENABLE", "-UNDEBUG"):
                lines = stamp().splitlines()
                lines[index] = lines[index].replace(flag, "")
                with self.subTest(record=index, flag=flag), self.assertRaises(ValueError):
                    unit.validate_stamp("\n".join(lines) + "\n", Path("/unit/source"), Path("/unit/build"), 2)

    def test_trace_dpi_other_formats_hidden_options_and_pooling_reject(self):
        for extra in ("-DSV_DPI", "-DVX_CFG_TCU_TYPE_DPI=0", "-DVX_CFG_TCU_FP8_ENABLE=0", "-DVCD_OUTPUT=0",
                      "-DDEBUG=0", "-DVX_CFG_TCU_FEDP2K=0", "-Ofast", "-ffast-math", "-Wp,-DNDEBUG",
                      "-Xpreprocessor -DNDEBUG", "-DNDEBUG", "-UVX_CFG_NUM_THREADS", "@opaque.rsp", "; true"):
            for index in (0, 1):
                lines = stamp().splitlines()
                lines[index] += " " + extra
                with self.subTest(extra=extra, record=index), self.assertRaises(ValueError):
                    unit.validate_stamp("\n".join(lines) + "\n", Path("/unit/source"), Path("/unit/build"), 2)
        for text in (stamp() + "-O2\n", stamp().replace("--assert", "--no-assert"),
                     stamp().replace("-j 2", "-j 32"), stamp().replace("--top-module " + unit.TOP, "--top-module other"),
                     stamp().replace("../verilator.vlt", "/different.vlt")):
            with self.assertRaises(ValueError):
                unit.validate_stamp(text, Path("/unit/source"), Path("/unit/build"), 2)

    def test_header_assertion_restore_lane_change_or_duplicate_macro_reject(self):
        for text in (effective_header() + "#define NDEBUG 1\n", effective_header().replace("NUM_LSU_LANES 8", "NUM_LSU_LANES 4"),
                     effective_header() + "#define VX_CFG_NUM_THREADS 8\n"):
            with self.assertRaises(ValueError):
                unit.validate_header(text)

    def test_cli_caps_environment_and_canonical_boolean_source_selection(self):
        for options in (("--jobs", "3"), ("--timeout-seconds", "1801"), ("--run-timeout-seconds", "0"), ("--waive",)):
            with redirect_stderr(io.StringIO()), self.subTest(options=options), self.assertRaises(SystemExit):
                arguments(*options)
        self.assertEqual(arguments().jobs, 2)
        self.assertEqual(unit.BUDGET, {"min_free_bytes": 15 * 1024 ** 3, "max_rss_bytes": 6 * 1024 ** 3,
                                       "max_log_bytes": 16 * 1024 ** 2})
        with mock.patch.dict(os.environ, {"CXXFLAGS": "-Ofast", "LD_PRELOAD": "x", "MAKEFLAGS": "-j99"}):
            env = unit.clean_environment({"work": Path("/unit/work"), "host_bin": None}, 2)
        self.assertNotIn("CXXFLAGS", env)
        self.assertNotIn("LD_PRELOAD", env)
        self.assertEqual(env["MAKEFLAGS"], "-j2")
        resolved = subprocess.check_output([sys.executable, str(unit.ROOT / "ci/gen_config.py"),
            "--config=" + str(unit.ROOT / "VX_config.toml"),
            "--cflags=" + " ".join(unit.CONFIGS + ("-DVX_CFG_XLEN=64",))], text=True).split()
        self.assertIn("-DVX_CFG_EXT_TCU_ENABLE", resolved)
        self.assertIn("-DVX_CFG_TCU_SPARSE_ENABLE", resolved)
        self.assertIn("-DVX_CFG_TCU_TYPE_TFR", resolved)
        for flag in ("-DVX_CFG_NUM_THREADS=8", "-DVX_CFG_NUM_WARPS=8", "-DVX_CFG_ISSUE_WIDTH=4",
                     "-DVX_CFG_NUM_TCU_BLOCKS=4", "-DVX_CFG_LMEM_NUM_BANKS=8", "-DVX_CFG_TCU_LATENCY=4",
                     "-DVX_CFG_TCU_USE_DSP=0", "-DVX_CFG_NUM_LSU_LANES=8", "-DVX_CFG_FPU_TYPE_STD"):
            self.assertIn(flag, resolved)

    def test_unit_tool_inventory_does_not_require_kernel_toolchain_or_libraries(self):
        with tempfile.TemporaryDirectory(prefix="unit-tools-") as temporary:
            root = Path(temporary).resolve()
            host = root / "host"
            host.mkdir()
            verilator = root / "verilator"
            (verilator / "bin").mkdir(parents=True)
            names = ("make", "g++", "gcc", "ar", "as", "ld", "python3", "bash", "perl")
            for path in [host / name for name in names] + [verilator / "bin" / name for name in ("verilator", "verilator_bin")]:
                path.write_text("synthetic tool identity\n")
                path.chmod(0o700)
            found = unit.tool_inventory({"verilator": verilator}, {"PATH": str(host)})
            self.assertEqual(set(found), set(names) | {"verilator", "verilator_bin"})
            self.assertTrue(all(len(row["sha256"]) == 64 for row in found.values()))

    def test_work_and_output_roots_must_be_fresh_separate_literals(self):
        with tempfile.TemporaryDirectory(prefix="unit-paths-") as temporary:
            root = Path(temporary).resolve()
            tools = root / "tools"
            tools.mkdir()
            args = arguments()
            args.tools_dir, args.work_dir, args.output = tools, root / "work", root / "output"
            unit.resolve_paths(args)
            for bad in (tools / "work", args.output):
                args.work_dir = bad
                with self.subTest(path=bad), self.assertRaises(ValueError):
                    unit.resolve_paths(args)
            args.work_dir = root / "work"
            args.work_dir.mkdir()
            with self.assertRaises(ValueError):
                unit.resolve_paths(args)


class WorkflowTests(unittest.TestCase):
    def scenario(self, *, dirty=False, development=False, failure=None, source_drift=False,
                 tool_drift=False, artifact_drift=False, malformed=False, resources=None, copy_reserve=False):
        temporary = tempfile.TemporaryDirectory(prefix="wgmma-unit-test-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        paths = {"source": root / "source", "tools": root / "tools", "work": root / "work",
                 "output": root / "output", "host_bin": None, "verilator": root / "tools/verilator"}
        paths["source"].mkdir()
        paths["tools"].mkdir()
        source = paths["source"]
        for name in set(unit.INPUTS + unit.COPIED):
            path = source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("synthetic source " + name + "\n")
        identity = {"checkout": {"revision": "a" * 40, "dirty": dirty,
            "blockers": ["source contains tracked changes or nonignored untracked inputs"] if dirty else []},
            "files": unit.hash_artifacts(source, sorted(set(unit.INPUTS + unit.COPIED)))}
        inventory = {name: {"path": "/fake-tools/" + name, "sha256": "b" * 64}
                     for name in ("g++", "make", "verilator", "python3")}
        budget = {"available_memory_bytes": 8 * unit.GIB, "free_disk_bytes": {"source": 20 * unit.GIB}}
        if resources:
            resources(budget)
        calls = {"source": 0, "tools": 0, "commands": []}

        def observe_source(_):
            calls["source"] += 1
            result = copy.deepcopy(identity)
            if source_drift and calls["source"] >= 2:
                result["checkout"]["revision"] = "c" * 40
            return result

        def observe_tools(*_):
            calls["tools"] += 1
            result = copy.deepcopy(inventory)
            if tool_drift and calls["tools"] >= 2:
                result["make"]["sha256"] = "d" * 64
            return result

        def execute(argv, cwd, env, log, **limits):
            calls["commands"].append((log.stem, list(argv), dict(env), limits))
            cwd = Path(cwd)
            log.write_text("synthetic process boundary\n")
            result = {"outcome": "pass", "exit_code": 0, "reason": None, "process_started": True, "cleanup_complete": True}
            if log.stem == failure:
                return dict(result, outcome="fail", exit_code=1, reason="nonzero_exit")
            if log.stem == "configure":
                for name in unit.GENERATED + unit.COPIED:
                    path = cwd / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text((source / name).read_text() if name in unit.COPIED else "header\n")
                (cwd / "config.mk").write_text("\n".join(f"{key} ?= {value}" for key, value in {
                    "XLEN": "64", "PROFILE": "", "VORTEX_HOME": source, "TOOLDIR": paths["tools"], "OSVERSION": "ubuntu/focal"}.items()) + "\n")
                (cwd / ".config.stamp").write_text(f"XLEN=64 PROFILE= SOURCE_DIR={source} BUILDDIR={cwd} TOOLDIR={paths['tools']}\n")
                (cwd / "hw/unittest/verilator.vlt").write_text((source / "hw/unittest/verilator.vlt.in").read_text())
            elif log.stem.endswith("-header-reproduce"):
                destination = Path(next(word.split("=", 1)[1] for word in argv if word.startswith("--output=")))
                destination.write_text("header\n")
                self.assertEqual(env["XLEN"], "64")
            elif log.stem == "native-build":
                build = paths["work"] / "native-unit"
                (cwd / "config.stamp").write_text(stamp(source, build))
                (cwd / "tcu_wgmma").write_text("synthetic executable identity\n")
                obj = cwd / "obj_dir"
                obj.mkdir()
                (obj / (unit.PREFIX + "__verFiles.dat")).write_text("VX_tcu_unit.sv VX_tcu_shared.sv VX_tcu_fedp_tfr.sv\n")
                (obj / (unit.PREFIX + "_classes.mk")).write_text("synthetic generated classes\n")
                (obj / (unit.PREFIX + "__Syms.h")).write_text("VX_tcu_fedp_tfr " + " ".join(f"g_blocks__BRA__{i}__KET__" for i in range(4)))
            elif log.stem == "effective-header":
                log.write_text(effective_header())
            elif log.stem == "native-run":
                log.write_text(output().replace("pressure_qualified=9", "pressure_qualified=0") if malformed else output())
                if artifact_drift:
                    (cwd / "tcu_wgmma").write_text("changed executable\n")
            return result

        with ExitStack() as stack:
            for name, value in (("source_snapshot", observe_source), ("tool_inventory", observe_tools),
                                ("_resources", lambda _: copy.deepcopy(budget)), ("run_bounded", execute)):
                stack.enter_context(mock.patch.object(unit, name, side_effect=value))
            stack.enter_context(mock.patch.object(unit, "LOADED_HELPERS", []))
            stack.enter_context(mock.patch.object(unit, "TOOLING", ()))
            stack.enter_context(mock.patch.object(unit.shutil, "disk_usage",
                return_value=SimpleNamespace(free=(15 if copy_reserve else 20) * unit.GIB)))
            report = unit.execute_run(arguments(*(["--development"] if development else [])), paths)
        return report, calls, paths

    def test_complete_workflow_retains_builds_immutable_environments_and_no_acceptance(self):
        report, calls, paths = self.scenario()
        self.assertEqual(report["outcome"], "pass", report["reason"])
        self.assertEqual(report["observations"]["checked_output_words"], 3072)
        self.assertFalse(report["acceptance_claimed"])
        self.assertFalse(report["qualifies_P02_A03"])
        self.assertTrue((paths["work"] / "native-unit" / unit.UNIT / "tcu_wgmma").is_file())
        for entry in report["commands"]:
            self.assertEqual("XLEN" in entry["environment"], entry["id"].endswith("-header-reproduce"))
        for _, _, _, limits in calls["commands"]:
            self.assertEqual({key: limits[key] for key in unit.BUDGET}, unit.BUDGET)
            self.assertLessEqual(limits["timeout_seconds"], 1800)

    def test_dirty_formal_source_rejects_before_commands_but_development_is_labelled(self):
        report, calls, _ = self.scenario(dirty=True)
        self.assertEqual(report["outcome"], "blocked")
        self.assertEqual(calls["commands"], [])
        report, _, _ = self.scenario(dirty=True, development=True)
        self.assertEqual(report["outcome"], "pass", report["reason"])
        self.assertTrue(report["development"])
        self.assertTrue(report["source_dirty"])

    def test_source_tools_artifacts_and_runtime_coverage_drift_fail(self):
        for option in ("source_drift", "tool_drift", "artifact_drift", "malformed"):
            report, _, _ = self.scenario(**{option: True})
            with self.subTest(option=option):
                self.assertEqual(report["outcome"], "fail")
                self.assertFalse(report["acceptance_claimed"])

    def test_resource_breaches_block_before_build_and_command_failure_is_retained(self):
        for change in (lambda row: row.update(available_memory_bytes=unit.GIB),
                       lambda row: row["free_disk_bytes"].update(source=14 * unit.GIB)):
            report, calls, _ = self.scenario(resources=change)
            self.assertEqual(report["outcome"], "blocked")
            self.assertEqual(calls["commands"], [])
        report, _, paths = self.scenario(failure="native-build")
        self.assertEqual(report["outcome"], "fail")
        self.assertEqual(report["commands"][-1]["id"], "native-build")
        self.assertTrue((paths["output"] / "logs/native-build.log").is_file())

    def test_retaining_artifacts_cannot_consume_the_disk_reserve(self):
        report, calls, _ = self.scenario(copy_reserve=True)
        self.assertEqual(report["outcome"], "blocked")
        self.assertIn("retained artifact would breach", report["reason"])
        self.assertEqual(calls["commands"], [])


if __name__ == "__main__":
    unittest.main()
