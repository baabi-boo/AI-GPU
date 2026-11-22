# SPDX-License-Identifier: Apache-2.0
"""Host-only command-boundary tests; fake processes establish no native coverage."""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import tempfile
import unittest
from unittest import mock

import p06_checked_execute as runner
from test_p02_matrix import STAMP_SAMPLES, sample


TRANSPORT_SELECTORS = [
    "cycles", "instructions", "core_sched_idle", "core_active_warps", "core_stalled_warps",
    "core_issued_warps", "core_issued_threads", "core_stall_scrb", "core_stall_lsu",
    "core_stall_tcu", "core_instr_tcu", "core_loads", "core_stores",
    "icache_reads", "icache_miss_r", "icache_mshr_st", "dcache_reads", "dcache_writes",
    "dcache_miss_r", "dcache_miss_w", "dcache_evicts", "dcache_mshr_st",
    "lmem_reads", "lmem_writes", "lmem_bank_st", "coalescer_miss", "memory_reads",
    "memory_writes", "memory_lt", "memory_bank_st", "tcu_tbuf_stalls", "tcu_tbuf_cache_hits",
    "tcu_lmem_reads",
]
UNSEEDED_SELECTORS = []
WRAPPER_SOURCES = {
    "tests/unittest/checked_counters/access_socket.cpp": "sim/simx/socket.cpp",
    "tests/unittest/checked_counters/access_cache.cpp": "sim/simx/mem/cache.cpp",
    "tests/unittest/checked_counters/access_memory.cpp": "sim/simx/mem/memory.cpp",
    "tests/unittest/checked_counters/access_tcu.cpp": "sim/simx/tcu/tcu_tbuf.cpp",
}
TCU_FOOTER = "tests/unittest/checked_counters/access_tcu.cpp"
TCU_ORIGINAL = "sim/simx/tcu/tcu_tbuf.cpp"
GENERATED_TCU = "sim/simx/obj/tests/checked_counters/access_tcu.generated.cpp"
INCLUDED_SOURCES = {wrapper: original for wrapper, original in WRAPPER_SOURCES.items() if wrapper != TCU_FOOTER}
ACCESS_SOURCES = (*WRAPPER_SOURCES, "tests/unittest/checked_counters/counter_access.cpp")
MODEL_SOURCES = (
    "sw/common/util.cpp", "sim/common/mem.cpp", "sw/common/softfloat_ext.cpp",
    "sw/common/rvfloats.cpp", "sim/common/dram_sim.cpp", "sim/common/cmd_processor.cpp",
    "sim/common/elf_loader.cpp", "sim/common/host_monitor.cpp", "sim/common/cout_drainer.cpp",
    *("sim/simx/" + name + ".cpp" for name in (
        "processor", "cluster", "core", "scheduler", "cta_dispatcher", "barrier_unit",
        "gbar_unit", "kmu/kmu", "decode", "decompressor", "scoreboard", "sequencer", "opc_unit",
        "dispatcher", "alu_unit", "fpu_unit", "lsu_unit", "sfu_unit", "wctl_unit", "csr_unit",
        "mem/cache_cluster", "mem/local_mem", "mem/mem_coalescer",
        "mem/local_mem_switch", "mem/lsu_mem_adapter", "dtm/debug_module", "dtm/jtag_dtm",
        "dtm/remote_bitbang", "operands", "tcu/tcu_unit")),
    *ACCESS_SOURCES, "tests/unittest/checked_counters/main.cpp",
)
NEGATIVE_MODES = {
    "core-overflow": "overflow", "cache-aggregate-overflow": "overflow",
    "pending-underflow": "underflow", "cache-backing-overflow": "overflow",
    "tcu-backing-overflow": "overflow",
}


def fixture_object(build, relative):
    if relative == "tests/unittest/checked_counters/main.cpp":
        suffix = "tests/checked_counters_test.o"
    elif relative.startswith("tests/unittest/checked_counters/"):
        suffix = "tests/checked_counters/" + Path(relative).with_suffix(".o").name
    elif relative.startswith("sw/common/"):
        suffix = "common/" + relative[len("sw/common/"):].replace(".cpp", ".o")
    elif relative.startswith("sim/common/"):
        suffix = "sim_common/" + relative[len("sim/common/"):].replace(".cpp", ".o")
    else:
        suffix = relative[len("sim/simx/"):].replace(".cpp", ".o")
    return build / "sim/simx/obj" / suffix


def fixture_input(source, build, relative):
    return build / GENERATED_TCU if relative == TCU_FOOTER else source / relative


def boundary_record(checked):
    return {"schema_version": 2, "mode": "boundaries", "xlen": 64, "perf": True,
            "tcu": True, "checked": checked, "transport_selectors": list(TRANSPORT_SELECTORS),
            "vectors_per_selector": 10, "transport_reads": 1788, "checks": 6389, "failures": 0,
            "source_components": 40, "component_vectors": 400, "split_vectors": 14, "reset_selectors": 33,
            "all_available_selector_transport": True,
            "unseeded_available_selectors": list(UNSEEDED_SELECTORS), "unavailable_selectors": 12,
            "full_warm_coverage": False, "warm_execution": False}


def boundary_output(checked_mode, **changes):
    value = boundary_record(checked_mode)
    value.update(changes)
    return "CHECKED_COUNTERS_RESULT " + json.dumps(value, separators=(",", ":")) + "\n"


def failure_record(mode):
    backing = mode in ("cache-backing-overflow", "tcu-backing-overflow")
    value = {"schema_version": 2 if backing else 1, "mode": mode, "reason": NEGATIVE_MODES[mode], "checked": True,
             "exception_type": "PerfCounterError", "protected_value_unchanged": True,
             "public_runtime": False, "warm_execution": False}
    if backing:
        value.update(source_unchanged=True, actual_backing_sources=True, actual_dcr_query=True,
                     terminal_failure=True, sticky_failure_checks=8, later_work_suppressed=True,
                     suppressed_tasks=2, joined=True, fresh_context_success=True)
    elif mode == "core-overflow":
        value.update(actual_model_updater=True, terminal_failure=True, sticky_failure_checks=8,
                     later_work_suppressed=True, suppressed_tasks=2, joined=True, fresh_context_success=True)
    elif mode == "cache-aggregate-overflow":
        value.update(source_unchanged=True, scope="production-cache-aggregate")
    else:
        value.update(scope="pending-counter-primitive")
    return value


def failure_output(scenario, **changes):
    value = failure_record(scenario)
    value.update(changes)
    return "CHECKED_COUNTERS_FAILURE_RESULT " + json.dumps(value, separators=(",", ":")) + "\n"


def compiler_stamp(source, build, checked):
    """Adapt retained compiler records, without deriving flags from the validator."""
    words = shlex.split(sample("simx_backend", source=source, build=build))
    words = [word for word in words if word not in ("-DITYPE=bf16", "-DOTYPE=fp32", "-DKUNROLL=1")]
    words[words.index("-MF") + 1] = str(build / "sim/simx/simx_config.stamp")
    words.append("-DPERF_ENABLE")
    if checked:
        words.append("-DSIMX_CHECKED_COUNTERS=1")
    return shlex.join(words) + "\n"


def header_output(checked):
    return (STAMP_SAMPLES["header"] + "\n#define PERF_ENABLE 1\n"
            + ("#define SIMX_CHECKED_COUNTERS 1\n" if checked else ""))


class NativeFixture:
    """Use real file hashes and checkpoints around a simulated process boundary."""

    def __enter__(self):
        self.stack = ExitStack()
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix="p06-checked-runner-"))).resolve()
        self.paths = {name: root / name for name in ("source", "tools", "work", "output")}
        for name in ("source", "tools"):
            self.paths[name].mkdir()
        self.tracked = set(runner.CRITICAL) | set(runner.COPIED) | set(MODEL_SOURCES)
        for name in self.tracked:
            path = self.paths["source"] / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture source: " + name + "\n", encoding="utf-8")
        for wrapper, original in INCLUDED_SOURCES.items():
            (self.paths["source"] / wrapper).write_text(
                '// SPDX-License-Identifier: Apache-2.0\n#include "counter_access.h"\n'
                + '#include "../../../' + original + '"\n\n#include <stdexcept>\n', encoding="utf-8")
        (self.paths["source"] / TCU_FOOTER).write_text(
            '// SPDX-License-Identifier: Apache-2.0\n'
            '#include "../../tests/unittest/checked_counters/counter_access.h"\n\n'
            '#include <stdexcept>\n', encoding="utf-8")
        self.tool_paths = {}
        for name in ("make", "g++", "gcc", "ar", "as", "ld", "bash", "python3", "executing_python"):
            path = self.paths["tools"] / name
            path.write_text("fixture tool: " + name + "\n", encoding="utf-8")
            path.chmod(0o700)
            self.tool_paths[name] = path
        self.dependencies = {}
        for name in runner.native.DEPENDENCIES:
            path = self.paths["source"] / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture dependency: " + name + "\n", encoding="utf-8")
            self.dependencies[name] = path
        self.checkout = {"revision": "a" * 40, "tree": "b" * 40, "dirty": False, "blockers": []}
        self.results, self.logs, self.stamps, self.calls, self.missing = {}, {}, {}, [], []
        self.after_command = lambda name, cwd: None
        for module in (runner, runner.native):
            self.stack.enter_context(mock.patch.object(module, "ROOT", self.paths["source"]))
        self.stack.enter_context(mock.patch.object(
            runner, "LOADED_HELPERS", runner.hash_artifacts(self.paths["source"], runner.HELPERS)))
        self.stack.enter_context(mock.patch.object(
            runner, "collect_source", side_effect=lambda source: copy.deepcopy(self.checkout)))
        self.stack.enter_context(mock.patch.object(
            runner, "_git", side_effect=lambda *args: "\0".join(sorted(self.tracked)).encode()))
        self.stack.enter_context(mock.patch.object(runner.native, "tools_snapshot", side_effect=self.tools_snapshot))
        self.memory = self.stack.enter_context(
            mock.patch.object(runner, "available_memory_bytes", return_value=8 * runner.GIB))
        usage = shutil.disk_usage(root)._replace(free=64 * runner.GIB)
        self.disk = self.stack.enter_context(mock.patch.object(runner.shutil, "disk_usage", return_value=usage))
        self.stack.enter_context(mock.patch.object(runner, "run_bounded", side_effect=self.command))
        return self

    def __exit__(self, *error):
        return self.stack.__exit__(*error)

    def tools_snapshot(self, paths, environment, engines):
        return {"tools": {name: runner.native.file_identity(path) for name, path in self.tool_paths.items()
                          if name not in self.missing},
                "dependencies": {name: runner.native.file_identity(path) for name, path in self.dependencies.items()
                                 if name not in self.missing}, "missing": list(self.missing)}

    def argv(self, *extra):
        return ["--source-dir", str(self.paths["source"]), "--tools-dir", str(self.paths["tools"]),
                "--work-dir", str(self.paths["work"]), "--output", str(self.paths["output"]), *extra]

    def run(self, *extra):
        self.stdout, self.stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(self.stdout), redirect_stderr(self.stderr):
            code = runner.main(self.argv(*extra))
        path = self.paths["output"] / "report.json"
        return code, json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    def configure(self, argv, build):
        for name in runner.GENERATED:
            path = build / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("generated fixture: " + name + "\n", encoding="utf-8")
        config = {"XLEN": "64", "PROFILE": "p02-tfr", "VORTEX_HOME": str(self.paths["source"]),
                  "TOOLDIR": str(self.paths["tools"])}
        for argument in argv:
            if argument.startswith("--osversion="):
                config["OSVERSION"] = argument.split("=", 1)[1]
        (build / "config.mk").write_text(
            "".join(key + " ?= " + value + "\n" for key, value in config.items()), encoding="utf-8")
        for name in runner.COPIED:
            destination = build / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.paths["source"] / name, destination)

    def build(self, name, cwd):
        source, build = self.paths["source"], cwd.parents[1]
        checked = name.startswith("checked-")
        stamp = compiler_stamp(source, build, checked)
        stamp = self.stamps.get(name, lambda text: text)(stamp)
        (cwd / "simx_config.stamp").write_text(stamp, encoding="utf-8")
        flags = shlex.split(stamp)
        compiler = str(self.tool_paths["g++"])
        commands, objects = [], []
        generated = build / GENERATED_TCU
        generated.parent.mkdir(parents=True, exist_ok=True)
        generated.write_bytes((source / TCU_ORIGINAL).read_bytes() + b"\n" + (source / TCU_FOOTER).read_bytes())
        for relative in MODEL_SOURCES:
            obj = fixture_object(build, relative)
            obj.parent.mkdir(parents=True, exist_ok=True)
            obj.write_text("fixture object: " + relative + "\n", encoding="utf-8")
            objects.append(str(obj))
            per_object = list(flags)
            per_object[per_object.index("-MF") + 1] = str(obj.with_suffix(".d"))
            commands.append(shlex.join([compiler, *per_object, "-c", str(fixture_input(source, build, relative)), "-o", str(obj)]))
        binary = cwd / "checked_counters_test"
        binary.write_text("fixture executable: " + name + "\n", encoding="utf-8")
        binary.chmod(0o700)
        libraries = [str(source / "third_party/softfloat/build/Linux-x86_64-GCC/softfloat.a"),
                     "-Wl,-rpath," + str(source / "third_party/ramulator"),
                     "-L" + str(source / "third_party/ramulator"), "-lramulator",
                     "-Wl,-rpath," + str(source / "third_party/ramulator_ext"),
                     "-L" + str(source / "third_party/ramulator_ext"),
                     "-Wl,--push-state,--no-as-needed", "-lramulator-vortex", "-Wl,--pop-state"]
        link_flags = list(flags)
        link_flags[link_flags.index("-MF") + 1] = str(binary)
        commands.append(shlex.join([compiler, *link_flags, *objects, *libraries, "-o", str(binary)]))
        return "\n".join(commands) + "\n"

    def command(self, argv, cwd, environment, log_path, **budget):
        cwd, log_path = Path(cwd), Path(log_path)
        name = log_path.stem
        self.calls.append({"id": name, "argv": list(argv), "cwd": cwd, "environment": dict(environment), **budget})
        result = {"outcome": "pass", "exit_code": 0, "reason": None, "process_started": True,
                  "cleanup_complete": True, "duration_seconds": 0.01, "peak_rss_bytes": 1024}
        mode = name.removeprefix("checked-")
        result.update(self.results.get(name, {}))
        output = "fixture command completed\n"
        if name.endswith("-configure") and result["outcome"] == "pass":
            self.configure(argv, cwd)
        elif name.endswith("-build") and result["outcome"] == "pass":
            output = self.build(name, cwd)
        elif name.endswith("-header"):
            output = header_output(name.startswith("checked-"))
        elif name.endswith("-boundaries"):
            output = boundary_output(name.startswith("checked-"))
        elif mode in NEGATIVE_MODES:
            output = failure_output(mode)
        replacement = self.logs.get(name, output)
        output = replacement(output) if callable(replacement) else replacement
        log_path.write_text(output, encoding="utf-8")
        result.update(log_sha256=hashlib.sha256(log_path.read_bytes()).hexdigest(),
                      log_size_bytes=log_path.stat().st_size)
        self.after_command(name, cwd)
        return result


class CheckedExecuteBoundaryTests(unittest.TestCase):
    def assert_nonqualifying(self, report):
        self.assertEqual(report["state"], "finished")
        for key in ("qualified", "ready_for_warm", "acceptance_claimed", "full_warm_coverage", "warm_execution"):
            self.assertIs(report[key], False, key)

    def assert_failed(self, code, report, reason=None):
        self.assertEqual(code, 1)
        self.assertIn(report["outcome"], ("fail", "blocked"))
        self.assertFalse(report["native_prerequisites_passed"])
        self.assert_nonqualifying(report)
        self.assertTrue(report["errors"])
        if reason:
            self.assertIn(reason, "\n".join(error["reason"] for error in report["errors"]))

    def test_complete_fresh_pair_retains_evidence_without_warm_qualification(self):
        with NativeFixture() as fixture:
            code, report = fixture.run("--expected-revision", "a" * 40, "--osversion", "ubuntu/jammy")
            self.assertEqual(code, 0, report["errors"])
            self.assertEqual(report["outcome"], "pass")
            self.assertTrue(report["native_prerequisites_passed"])
            self.assertTrue(report["all_available_selector_transport"])
            self.assertEqual(report["schema_version"], 2)
            self.assertEqual(report["contract_id"], "simx-checked-counters-native-v2")
            self.assert_nonqualifying(report)
            self.assertEqual(len(fixture.calls), 17)
            self.assertEqual(len(report["variants"]), 2)
            self.assertEqual(len(report["cells"]), 7)
            self.assertTrue(all(cell["outcome"] == "pass" for cell in report["cells"]))
            self.assertTrue(report["source_stable"] and report["tools_stable"])
            self.assertTrue(report["ordinary_checked_observations_equal"])
            self.assertEqual(report["expected_revision"], "a" * 40)
            for variant in report["variants"]:
                self.assertEqual(variant["compiler_records"]["translation_units"], len(MODEL_SOURCES))
                self.assertEqual(variant["compiler_records"]["link_count"], 1)
                self.assertEqual(variant["compiler_records"]["included_production_sources"], INCLUDED_SOURCES)
                generated_path = str(Path(variant["build_dir"]) / GENERATED_TCU)
                self.assertEqual(variant["compiler_records"]["generated_production_sources"], {
                    generated_path: {"production_source": TCU_ORIGINAL, "access_footer": TCU_FOOTER,
                                     "separator_hex": "0a"}})
                self.assertIn(generated_path, variant["compiler_records"]["compiled_sources"])
                self.assertNotIn(str(fixture.paths["source"] / TCU_FOOTER),
                                 variant["compiler_records"]["compiled_sources"])
                self.assertTrue({str(fixture.paths["source"] / name) for name in WRAPPER_SOURCES.values()}.isdisjoint(
                    variant["compiler_records"]["compiled_sources"]))
                for key in ("generated", "compiler_stamp", "diagnostic_sources", "binary"):
                    self.assertEqual(variant[key + "_before"], variant[key + "_after"])
                self.assertEqual(variant["compiler_records"]["object_identities"], variant["objects_after"])
                for item in (variant["retained_configuration"] + variant["retained_compiler_stamp"]
                             + variant["retained_diagnostic_sources"]):
                    path = fixture.paths["output"] / item["path"]
                    self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), item["sha256"])
            observed = [cell["observations"] for cell in report["cells"] if cell["mode"] == "boundaries"]
            for value in observed:
                self.assertEqual(len(value["transport_selectors"]), 33)
                self.assertEqual(len(value["unseeded_available_selectors"]), 0)
                self.assertEqual(value["unavailable_selectors"], 12)
            for cell in report["cells"]:
                if cell["mode"] in NEGATIVE_MODES:
                    self.assertEqual(cell["observations"], failure_record(cell["mode"]))
                    self.assertEqual(cell["exit_code"], 0)
                    self.assertEqual(cell["run_outcome"], "pass")
            retained_source_paths = {item["path"] for item in report["retained_sources"]}
            self.assertIn("artifacts/source/sw/runtime/common/async_run.h", retained_source_paths)
            self.assertIn("primitive", " ".join(report["limitations"]))
            self.assertIn("native public-runtime", " ".join(report["limitations"]))
            self.assertNotEqual(report["tools_before"]["tools"]["python3"],
                                report["tools_before"]["tools"]["executing_python"])
            self.assertEqual(json.loads(fixture.stdout.getvalue())["ready_for_warm"], False)

    def test_every_command_has_fixed_limits_and_scrubbed_environment(self):
        with NativeFixture() as fixture, mock.patch.dict(os.environ, {
                "CONFIGS": "-DSIMX_FUNCTIONAL=1", "CXXFLAGS": "-Ofast", "MAKEFLAGS": "-j99",
                "THREADS": "99", "LD_PRELOAD": "/unexpected.so", "PYTHONPATH": "/unexpected"}):
            code, report = fixture.run()
            self.assertEqual(code, 0, report["errors"])
            for call in fixture.calls:
                self.assertEqual(call["min_free_bytes"], 15 * runner.GIB)
                self.assertEqual(call["max_rss_bytes"], 4 * runner.GIB)
                self.assertEqual(call["max_log_bytes"], 16 * 1024 * 1024)
                self.assertEqual(call["environment"]["MAKEFLAGS"], "-j2")
                self.assertEqual(call["environment"]["THREADS"], "1")
                self.assertTrue(set(("CONFIGS", "CXXFLAGS", "LD_PRELOAD", "PYTHONPATH")).isdisjoint(call["environment"]))
                self.assertEqual(set(call["resource_paths"]), set(fixture.paths.values()))
                if call["id"].endswith("-build"):
                    self.assertEqual(call["timeout_seconds"], 1800)
                    for value in ("-j2", "THREADS=1", "PROFILE=p02-tfr", "PERF=1"):
                        self.assertIn(value, call["argv"])
                    expected = "CONFIGS=-DSIMX_CHECKED_COUNTERS=1" if call["id"].startswith("checked-") else "CONFIGS="
                    self.assertIn(expected, call["argv"])
                if call["id"].endswith("boundaries") or call["id"].removeprefix("checked-") in NEGATIVE_MODES:
                    self.assertEqual(call["timeout_seconds"], 180)
                    self.assertEqual(call["argv"][:3], [str(fixture.tool_paths["executing_python"]), "-I", "-c"])
                    self.assertIn("resource.setrlimit(resource.RLIMIT_CORE,(0,0))", call["argv"][3])

    def test_existing_output_is_preserved(self):
        with NativeFixture() as fixture:
            fixture.paths["output"].mkdir()
            marker = fixture.paths["output"] / "keep.txt"
            marker.write_text("preserve", encoding="utf-8")
            code, report = fixture.run()
            self.assertEqual((code, report), (2, None))
            self.assertEqual(marker.read_text(encoding="utf-8"), "preserve")
            self.assertEqual(fixture.calls, [])

    def test_work_overlap_symlink_and_unsafe_paths_are_rejected(self):
        for kind in ("existing", "overlap", "symlink", "unsafe"):
            with self.subTest(kind=kind), NativeFixture() as fixture:
                work = fixture.paths["work"]
                if kind == "existing":
                    work.mkdir()
                elif kind == "overlap":
                    fixture.paths["work"] = fixture.paths["source"] / "work"
                elif kind == "symlink":
                    work.symlink_to(fixture.paths["tools"], target_is_directory=True)
                else:
                    fixture.paths["work"] = work.with_name("unsafe work")
                code, report = fixture.run()
                self.assertEqual((code, report), (2, None))
                self.assertEqual(fixture.calls, [])

    def test_expected_revision_is_validated_and_matched_before_commands(self):
        for revision in ("short", "A" * 40, "f" * 40):
            with self.subTest(revision=revision), NativeFixture() as fixture:
                code, report = fixture.run("--expected-revision", revision)
                if revision == "f" * 40:
                    self.assert_failed(code, report, "requested revision")
                else:
                    self.assertEqual((code, report), (2, None))
                self.assertEqual(fixture.calls, [])

    def test_dirty_untracked_blocked_and_unidentified_source_never_runs(self):
        for kind in ("dirty", "untracked", "untracked-completion", "blocker", "revision", "tree", "helper"):
            with self.subTest(kind=kind), NativeFixture() as fixture:
                if kind == "dirty":
                    fixture.checkout["dirty"] = True
                elif kind == "untracked":
                    fixture.tracked.remove("sim/common/perf_counter.h")
                elif kind == "untracked-completion":
                    fixture.tracked.remove("sw/runtime/common/async_run.h")
                elif kind == "blocker":
                    fixture.checkout["blockers"] = ["submodule state unavailable"]
                elif kind == "helper":
                    (fixture.paths["source"] / runner.HELPERS[0]).write_text("changed", encoding="utf-8")
                else:
                    fixture.checkout[kind] = None
                code, report = fixture.run()
                self.assert_failed(code, report)
                self.assertEqual(fixture.calls, [])

    def test_missing_tools_and_dependencies_block_before_commands(self):
        for missing in ("g++", "python3", "executing_python", runner.native.DEPENDENCIES[0]):
            with self.subTest(missing=missing), NativeFixture() as fixture:
                fixture.missing.append(missing)
                code, report = fixture.run()
                self.assert_failed(code, report, "missing installed prerequisites")
                self.assertEqual(fixture.calls, [])

    def test_insufficient_disk_or_memory_blocks_before_commands(self):
        for kind in ("disk", "memory", "unknown-memory"):
            with self.subTest(kind=kind), NativeFixture() as fixture:
                if kind == "disk":
                    fixture.disk.return_value = fixture.disk.return_value._replace(free=15 * runner.GIB - 1)
                else:
                    fixture.memory.return_value = None if kind == "unknown-memory" else 4 * runner.GIB - 1
                code, report = fixture.run()
                self.assert_failed(code, report)
                self.assertEqual(fixture.calls, [])

    def test_nonzero_build_or_boundary_exit_cannot_be_rescued_by_output(self):
        for name in ("ordinary-build", "checked-build", "ordinary-boundaries", "checked-boundaries"):
            with self.subTest(name=name), NativeFixture() as fixture:
                fixture.results[name] = {"outcome": "fail", "exit_code": 2, "reason": "nonzero_exit"}
                fixture.logs[name] = boundary_output(name.startswith("checked-")) + "PASSED!\n"
                code, report = fixture.run()
                self.assert_failed(code, report, name + " failed")
                command = next(item for item in report["commands"] if item["id"] == name)
                self.assertEqual(command["exit_code"], 2)
                self.assertEqual(fixture.calls[-1]["id"], name)

    def test_resource_stops_and_incomplete_cleanup_remain_failures(self):
        failures = [{"outcome": "blocked", "exit_code": None, "reason": "disk_reserve", "process_started": False},
                    {"outcome": "fail", "exit_code": -9, "reason": "timeout"},
                    {"outcome": "fail", "exit_code": -9, "reason": "rss_limit"},
                    {"outcome": "fail", "exit_code": -9, "reason": "log_limit"},
                    {"cleanup_complete": False}]
        for failure in failures:
            with self.subTest(failure=failure), NativeFixture() as fixture:
                fixture.results["checked-core-overflow"] = failure
                code, report = fixture.run()
                self.assert_failed(code, report)
                self.assertEqual(fixture.calls[-1]["id"], "checked-core-overflow")
                self.assertEqual(report["cells"][0]["outcome"], "pass")

    def test_stale_generated_binary_is_rejected_before_build(self):
        with NativeFixture() as fixture:
            def stale(name, cwd):
                if name == "ordinary-configure":
                    (cwd / "sim/simx/checked_counters_test").write_text("stale", encoding="utf-8")
            fixture.after_command = stale
            code, report = fixture.run()
            self.assert_failed(code, report, "not fresh")
            self.assertFalse(any(item["id"].endswith("-build") for item in fixture.calls))

    def test_missing_or_unexecutable_binary_cannot_run(self):
        for kind in ("missing", "unexecutable"):
            with self.subTest(kind=kind), NativeFixture() as fixture:
                def remove(name, cwd):
                    if name == "ordinary-build":
                        path = cwd / "checked_counters_test"
                        path.unlink() if kind == "missing" else path.chmod(0o600)
                fixture.after_command = remove
                code, report = fixture.run()
                self.assert_failed(code, report, "missing or not executable")
                self.assertFalse(any(item["id"] == "ordinary-boundaries" for item in fixture.calls))

    def test_guard_stamp_and_effective_header_mismatches_fail(self):
        for kind in ("missing-stamp", "wrong-stamp", "ordinary-stamp", "missing-header", "wrong-header"):
            with self.subTest(kind=kind), NativeFixture() as fixture:
                if kind == "missing-stamp":
                    fixture.stamps["checked-build"] = lambda text: text.replace(" -DSIMX_CHECKED_COUNTERS=1", "")
                elif kind == "wrong-stamp":
                    fixture.stamps["checked-build"] = lambda text: text.replace("SIMX_CHECKED_COUNTERS=1", "SIMX_CHECKED_COUNTERS=0")
                elif kind == "ordinary-stamp":
                    fixture.stamps["ordinary-build"] = lambda text: text.rstrip() + " -DSIMX_CHECKED_COUNTERS=1\n"
                else:
                    fixture.logs["checked-header"] = header_output(False) + (
                        "#define SIMX_CHECKED_COUNTERS 0\n" if kind == "wrong-header" else "")
                code, report = fixture.run()
                self.assert_failed(code, report, "checked-counter")

    def test_one_translation_unit_cannot_omit_the_guard(self):
        with NativeFixture() as fixture:
            fixture.logs["checked-build"] = lambda text: text.replace(" -DSIMX_CHECKED_COUNTERS=1", "", 1)
            code, report = fixture.run()
            self.assert_failed(code, report, "translation-unit flags differ")
            self.assertFalse(any(item["id"] == "checked-boundaries" for item in fixture.calls))

    def test_missing_compile_duplicate_link_or_unbound_object_is_rejected(self):
        mutations = {
            "missing-compile": lambda text: "\n".join(text.splitlines()[1:]) + "\n",
            "duplicate-link": lambda text: text + text.splitlines()[-1] + "\n",
            "unbound-object": lambda text: text.replace(" -lramulator ", " /outside/foreign.o -lramulator "),
            "missing-tcu": lambda text: "\n".join(line for line in text.splitlines()
                                                        if " -c " not in line or "/tcu/tcu_unit.cpp" not in line) + "\n",
        }
        for name, mutation in mutations.items():
            with self.subTest(name=name), NativeFixture() as fixture:
                fixture.logs["checked-build"] = mutation
                code, report = fixture.run()
                self.assert_failed(code, report)
                self.assertEqual(fixture.calls[-1]["id"], "checked-build")

    def test_access_control_cannot_be_disabled_for_any_translation_unit(self):
        for relative in ("sim/simx/core.cpp", *ACCESS_SOURCES,
                         "tests/unittest/checked_counters/main.cpp"):
            with self.subTest(source=relative), NativeFixture() as fixture:
                def weaken(text):
                    path = fixture_input(fixture.paths["source"], fixture.paths["work"] / "checked", relative)
                    return text.replace(" -c " + str(path), " -fno-access-control -c " + str(path))
                fixture.logs["checked-build"] = weaken
                code, report = fixture.run()
                self.assert_failed(code, report, "translation-unit flags differ")
                self.assertFalse(any(item["id"] == "checked-boundaries" for item in fixture.calls))

    def test_original_and_wrapper_translation_units_cannot_be_substituted_or_combined(self):
        for wrapper, original in WRAPPER_SOURCES.items():
            for kind in ("substitute", "duplicate", "omit"):
                with self.subTest(wrapper=wrapper, kind=kind), NativeFixture() as fixture:
                    def replace(text):
                        lines = text.splitlines()
                        path = fixture_input(fixture.paths["source"], fixture.paths["work"] / "checked", wrapper)
                        selected = next(line for line in lines
                                        if " -c " + str(path) + " " in line)
                        if kind == "substitute":
                            return text.replace(str(path),
                                                str(fixture.paths["source"] / original))
                        if kind == "duplicate":
                            extra = selected.replace(str(path),
                                                     str(fixture.paths["source"] / original))
                            return text + extra + "\n"
                        return "\n".join(line for line in lines if line != selected) + "\n"
                    fixture.logs["checked-build"] = replace
                    code, report = fixture.run()
                    self.assert_failed(code, report)
                    self.assertEqual(fixture.calls[-1]["id"], "checked-build")

    def test_exact_inventory_rejects_missing_non_counter_model_source(self):
        with NativeFixture() as fixture:
            fixture.logs["checked-build"] = lambda text: "\n".join(
                line for line in text.splitlines()
                if " -c " + str(fixture.paths["source"] / "sim/simx/decode.cpp") + " " not in line) + "\n"
            code, report = fixture.run()
            self.assert_failed(code, report, "exact fresh compile/link source inventory")

    def test_source_tools_dependencies_and_generated_evidence_drift_fail_closed(self):
        for kind in ("source", "guard", "completion", "wrapper", "included-source", "access-header", "tool", "executing-python", "dependency", "generated", "generated-tcu", "stamp", "object", "retained", "retained-tcu", "log"):
            with self.subTest(kind=kind), NativeFixture() as fixture:
                def mutate(name, cwd):
                    if name != "ordinary-boundaries":
                        return
                    targets = {
                        "source": fixture.paths["source"] / "sim/simx/core.cpp",
                        "guard": fixture.paths["source"] / "sim/common/perf_counter.h",
                        "completion": fixture.paths["source"] / "sw/runtime/common/async_run.h",
                        "wrapper": fixture.paths["source"] / "tests/unittest/checked_counters/access_cache.cpp",
                        "included-source": fixture.paths["source"] / "sim/simx/mem/cache.cpp",
                        "access-header": fixture.paths["source"] / "tests/unittest/checked_counters/counter_access.h",
                        "tool": fixture.tool_paths["g++"],
                        "executing-python": fixture.tool_paths["executing_python"],
                        "dependency": next(iter(fixture.dependencies.values())),
                        "generated": cwd.parents[1] / "sw/VX_config.h",
                        "generated-tcu": cwd.parents[1] / GENERATED_TCU,
                        "stamp": cwd / "simx_config.stamp",
                        "object": fixture_object(cwd.parents[1], MODEL_SOURCES[0]),
                        "retained": fixture.paths["output"] / "artifacts/source/sim/common/perf_counter.h",
                        "retained-tcu": fixture.paths["output"] / "artifacts/ordinary" / GENERATED_TCU,
                        "log": fixture.paths["output"] / "logs/ordinary-build.log",
                    }
                    with targets[kind].open("a", encoding="utf-8") as stream:
                        stream.write("changed after observation\n")
                fixture.after_command = mutate
                code, report = fixture.run()
                self.assert_failed(code, report, "changed")

    def test_binary_drift_between_build_and_run_and_after_run_is_rejected(self):
        for when in ("ordinary-header", "ordinary-boundaries", "checked-pending-underflow"):
            with self.subTest(when=when), NativeFixture() as fixture:
                def mutate(name, cwd):
                    if name == when:
                        with (cwd / "checked_counters_test").open("a", encoding="utf-8") as stream:
                            stream.write("replacement binary\n")
                fixture.after_command = mutate
                code, report = fixture.run()
                self.assert_failed(code, report, "binary changed")
                if when == "ordinary-header":
                    self.assertFalse(any(item["id"] == "ordinary-boundaries" for item in fixture.calls))

    def test_configuration_or_stamp_drift_after_header_blocks_native_launch(self):
        for relative in ("sw/VX_config.h", "sim/simx/simx_config.stamp", GENERATED_TCU):
            with self.subTest(relative=relative), NativeFixture() as fixture:
                def mutate(name, cwd):
                    if name == "ordinary-header":
                        with (cwd.parents[1] / relative).open("a", encoding="utf-8") as stream:
                            stream.write("changed before native launch\n")
                fixture.after_command = mutate
                code, report = fixture.run()
                self.assert_failed(code, report, "changed")
                self.assertFalse(any(item["id"] == "ordinary-boundaries" for item in fixture.calls))

    def test_invalid_boundary_claim_or_partial_selector_scope_cannot_pass(self):
        changes = ({"checked": False}, {"xlen": 32}, {"perf": False}, {"tcu": False},
                   {"checks": 0}, {"failures": 1}, {"full_warm_coverage": True}, {"warm_execution": True},
                   {"transport_selectors": TRANSPORT_SELECTORS[:-1]}, {"unseeded_available_selectors": ["memory_lt"]},
                   {"all_available_selector_transport": False}, {"source_components": 39},
                   {"component_vectors": 399}, {"split_vectors": 13}, {"reset_selectors": 32},
                   {"schema_version": 1})
        for change in changes:
            with self.subTest(change=change), NativeFixture() as fixture:
                fixture.logs["checked-boundaries"] = boundary_output(True, **change)
                code, report = fixture.run()
                self.assert_failed(code, report, "boundary result")

    def test_native_exception_diagnostic_cannot_hide_a_crash_or_failed_process(self):
        changes = ({"outcome": "fail", "exit_code": -signal.SIGABRT, "reason": "nonzero_exit"},
                   {"outcome": "fail", "exit_code": -signal.SIGSEGV, "reason": "nonzero_exit"},
                   {"outcome": "fail", "exit_code": 1, "reason": "nonzero_exit"},
                   {"exit_code": -signal.SIGABRT}, {"exit_code": 1},
                   {"exit_code": False}, {"process_started": False})
        for mode in NEGATIVE_MODES:
            for change in changes:
                with self.subTest(mode=mode, change=change), NativeFixture() as fixture:
                    name = "checked-" + mode
                    fixture.results[name] = change
                    code, report = fixture.run()
                    self.assert_failed(code, report)
                    self.assertEqual(fixture.calls[-1]["id"], name)
                    cell = next(item for item in report["cells"] if item["id"] == name)
                    self.assertIn(cell["outcome"], ("fail", "blocked"))

    def test_false_containment_or_overstated_scope_blocks_the_attempt(self):
        failures = (
            ("core-overflow", {"terminal_failure": False}),
            ("core-overflow", {"actual_model_updater": False}),
            ("core-overflow", {"sticky_failure_checks": 7}),
            ("core-overflow", {"later_work_suppressed": False}),
            ("core-overflow", {"fresh_context_success": False}),
            ("core-overflow", {"joined": False}),
            ("cache-aggregate-overflow", {"source_unchanged": False}),
            ("pending-underflow", {"scope": "native-pending-count"}),
            ("pending-underflow", {"public_runtime": True}),
        )
        for mode, change in failures:
            with self.subTest(mode=mode, change=change), NativeFixture() as fixture:
                fixture.logs["checked-" + mode] = failure_output(mode, **change)
                code, report = fixture.run()
                self.assert_failed(code, report, "failure result")
                self.assertEqual(fixture.calls[-1]["id"], "checked-" + mode)


class CheckedOutputParserTests(unittest.TestCase):
    def test_boundary_json_rejects_duplicates_types_extra_results_and_diagnostics(self):
        original = boundary_output(True)
        bad = (original + original, original + "FAILED\n", original + "SIMX_CHECKED_COUNTER_FAILURE: overflow\n",
               original.replace('"checked":true', '"checked":1'),
               original.replace('"failures":0', '"failures":false'),
               original.replace('"checks":6389', '"checks":6389.0'),
               original.replace('"checks":6389', '"checks":NaN'),
               original.replace('"checks":6389', '"checks":6389,"checks":6389'), "PASSED!\n")
        self.assertEqual(runner.verify_output(original, True), boundary_record(True))
        for text in bad:
            with self.subTest(text=text[-120:]), self.assertRaises(ValueError):
                runner.verify_output(text, True)

    def test_all_negative_scenarios_require_completed_successful_diagnostics(self):
        result = {"outcome": "pass", "exit_code": 0, "reason": None,
                  "process_started": True, "cleanup_complete": True}
        changes = ({"outcome": "fail", "exit_code": -signal.SIGABRT, "reason": "nonzero_exit"},
                   {"exit_code": 1}, {"exit_code": -signal.SIGABRT},
                   {"exit_code": 128 + signal.SIGABRT}, {"exit_code": -signal.SIGSEGV},
                   {"exit_code": False}, {"exit_code": 0.0}, {"exit_code": None},
                   {"process_started": False}, {"process_started": 1},
                   {"cleanup_complete": False}, {"cleanup_complete": 1}, {"reason": "timeout"},
                   {"reason": "rss_limit"}, {"reason": "nonzero_exit"}, {"outcome": "blocked"})
        for mode in NEGATIVE_MODES:
            text = failure_output(mode)
            self.assertEqual(runner.verify_negative(text, result, mode), failure_record(mode))
            for change in changes:
                with self.subTest(mode=mode, change=change), self.assertRaises(ValueError):
                    runner.verify_negative(text, dict(result, **change), mode)

    def test_failure_json_rejects_duplicate_truncated_or_competing_records(self):
        result = {"outcome": "pass", "exit_code": 0, "reason": None,
                  "process_started": True, "cleanup_complete": True}
        for mode in NEGATIVE_MODES:
            text = failure_output(mode)
            bad_outputs = (
                "", "PASSED!\n", text + text, "prefix " + text, text + "prefix " + text,
                text + boundary_output(True), text + "FAILED\n",
                text + "SIMX_CHECKED_COUNTER_FAILURE: " + NEGATIVE_MODES[mode] + "\n",
                "SIMX_CHECKED_COUNTER_FAILURE: " + NEGATIVE_MODES[mode] + "\n",
                text[:-3] + "\n", text.replace('"checked":true', '"checked":true,"checked":true'),
                text.replace('"schema_version":' + str(failure_record(mode)["schema_version"]), '"schema_version":NaN'),
                text.replace('"schema_version":' + str(failure_record(mode)["schema_version"]), '"schema_version":Infinity'),
                text.replace('"schema_version":' + str(failure_record(mode)["schema_version"]), '"schema_version":-Infinity'),
                "CHECKED_COUNTERS_FAILURE_RESULT []\n",
            )
            for bad in bad_outputs:
                with self.subTest(mode=mode, text=bad), self.assertRaises(ValueError):
                    runner.verify_negative(bad, result, mode)

    def test_failure_records_require_exact_typed_reason_and_protected_value(self):
        result = {"outcome": "pass", "exit_code": 0, "reason": None,
                  "process_started": True, "cleanup_complete": True}
        changes = ({"schema_version": 3}, {"schema_version": True}, {"mode": "boundaries"},
                   {"reason": "negative operand"}, {"checked": False}, {"checked": 1},
                   {"exception_type": "std::runtime_error"}, {"protected_value_unchanged": False},
                   {"public_runtime": True}, {"public_runtime": 0}, {"warm_execution": True},
                   {"qualified": True}, {"ready_for_warm": True})
        for mode in NEGATIVE_MODES:
            for change in changes:
                with self.subTest(mode=mode, change=change), self.assertRaises(ValueError):
                    runner.verify_negative(failure_output(mode, **change), result, mode)
            for omitted in failure_record(mode):
                value = failure_record(mode)
                del value[omitted]
                text = "CHECKED_COUNTERS_FAILURE_RESULT " + json.dumps(value) + "\n"
                with self.subTest(mode=mode, omitted=omitted), self.assertRaises(ValueError):
                    runner.verify_negative(text, result, mode)

    def test_native_updater_containment_and_each_non_native_scope_are_exact(self):
        result = {"outcome": "pass", "exit_code": 0, "reason": None,
                  "process_started": True, "cleanup_complete": True}
        core_changes = ({"actual_model_updater": False}, {"terminal_failure": False},
                        {"sticky_failure_checks": 0}, {"sticky_failure_checks": 8.0},
                        {"later_work_suppressed": False}, {"suppressed_tasks": 1},
                        {"joined": False}, {"fresh_context_success": False})
        for change in core_changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                runner.verify_negative(failure_output("core-overflow", **change), result, "core-overflow")
        for mode, changes in (
                ("cache-aggregate-overflow", ({"source_unchanged": False}, {"source_unchanged": 1},
                                            {"scope": "copied-cache-arithmetic"})),
                ("pending-underflow", ({"scope": "native-pending-count"},
                                      {"actual_model_updater": True}, {"fresh_context_success": True}))):
            for change in changes:
                with self.subTest(mode=mode, change=change), self.assertRaises(ValueError):
                    runner.verify_negative(failure_output(mode, **change), result, mode)

    def test_backing_failures_require_real_sources_queries_and_terminal_containment(self):
        result = {"outcome": "pass", "exit_code": 0, "reason": None,
                  "process_started": True, "cleanup_complete": True}
        for mode in ("cache-backing-overflow", "tcu-backing-overflow"):
            for change in ({"schema_version": 1}, {"source_unchanged": False},
                           {"actual_backing_sources": False}, {"actual_dcr_query": False},
                           {"terminal_failure": False}, {"sticky_failure_checks": 8.0},
                           {"later_work_suppressed": False}, {"suppressed_tasks": 1},
                           {"joined": False}, {"fresh_context_success": False}):
                with self.subTest(mode=mode, change=change), self.assertRaises(ValueError):
                    runner.verify_negative(failure_output(mode, **change), result, mode)

    def test_all_source_and_coverage_counts_require_exact_types(self):
        for key in ("schema_version", "source_components", "component_vectors", "split_vectors",
                    "reset_selectors", "vectors_per_selector", "transport_reads", "checks"):
            value = boundary_record(True)[key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                runner.verify_output(boundary_output(True, **{key: float(value)}), True)
        for change in ({"all_available_selector_transport": 1},
                       {"transport_selectors": TRANSPORT_SELECTORS + ["memory_reads"]},
                       {"transport_selectors": list(reversed(TRANSPORT_SELECTORS))},
                       {"unavailable_selectors": 0}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                runner.verify_output(boundary_output(True, **change), True)

    def test_pure_build_parser_does_not_open_original_paths(self):
        with NativeFixture() as fixture:
            source = fixture.paths["source"]
            build = fixture.paths["work"] / "checked"
            unit = build / "sim/simx"
            unit.mkdir(parents=True)
            text = fixture.build("checked-build", unit)
            words = shlex.split(compiler_stamp(source, build, True))
            contents = {name: (source / name).read_bytes() for name in (*WRAPPER_SOURCES, TCU_ORIGINAL)}
            generated = {GENERATED_TCU: (build / GENERATED_TCU).read_bytes()}
            shutil.rmtree(source)
            shutil.rmtree(fixture.paths["work"])
            with mock.patch.object(Path, "resolve", side_effect=AssertionError("resolved producer path")), \
                    mock.patch.object(runner.native, "file_identity", side_effect=AssertionError("read producer file")):
                parsed = runner.parse_build_records(text, words, source=source, build=build,
                    binary=unit / "checked_counters_test", compiler=str(fixture.tool_paths["g++"]),
                    source_files=fixture.tracked, source_contents=contents, generated_contents=generated)
            self.assertEqual(parsed["translation_units"], len(MODEL_SOURCES))
            self.assertEqual(parsed["included_production_sources"], INCLUDED_SOURCES)
            self.assertEqual(parsed["generated_production_sources"], {
                str(build / GENERATED_TCU): {"production_source": TCU_ORIGINAL,
                    "access_footer": TCU_FOOTER, "separator_hex": "0a"}})
            self.assertEqual(len(parsed["object_paths"]), len(MODEL_SOURCES))
            self.assertNotIn("object_identities", parsed)

    def test_pure_build_parser_requires_original_bodies_and_normalized_record_paths(self):
        with NativeFixture() as fixture:
            source = fixture.paths["source"]
            build = fixture.paths["work"] / "checked"
            unit = build / "sim/simx"
            unit.mkdir(parents=True)
            text = fixture.build("checked-build", unit)
            words = shlex.split(compiler_stamp(source, build, True))
            arguments = dict(source=source, build=build, binary=unit / "checked_counters_test",
                             compiler=str(fixture.tool_paths["g++"]), source_files=fixture.tracked,
                             source_contents={name: (source / name).read_bytes() for name in (*WRAPPER_SOURCES, TCU_ORIGINAL)},
                             generated_contents={GENERATED_TCU: (build / GENERATED_TCU).read_bytes()})
            for original in WRAPPER_SOURCES.values():
                with self.subTest(original=original), self.assertRaises(ValueError):
                    runner.parse_build_records(text, words, **dict(arguments,
                        source_files=fixture.tracked - {original}))
            malformed = text.replace(" -o " + str(unit / "obj"), " -o " + str(unit / "obj") + "/../obj", 1)
            with self.assertRaisesRegex(ValueError, "normalized path"):
                runner.parse_build_records(malformed, words, **arguments)

    def test_source_bindings_reject_includes_generated_tampering_and_footer_substitution(self):
        with NativeFixture() as fixture:
            source, build = fixture.paths["source"], fixture.paths["work"] / "checked"
            unit = build / "sim/simx"
            unit.mkdir(parents=True)
            text = fixture.build("checked-build", unit)
            words = shlex.split(compiler_stamp(source, build, True))
            contents = {name: (source / name).read_bytes() for name in (*WRAPPER_SOURCES, TCU_ORIGINAL)}
            generated = {GENERATED_TCU: (build / GENERATED_TCU).read_bytes()}
            arguments = dict(source=source, build=build, binary=unit / "checked_counters_test",
                             compiler=str(fixture.tool_paths["g++"]), source_files=fixture.tracked,
                             source_contents=contents, generated_contents=generated)
            for wrapper, original in INCLUDED_SOURCES.items():
                for body in (contents[wrapper].replace(original.encode(), b"sim/simx/core.cpp"),
                             b"#if 0\n" + contents[wrapper] + b"#endif\n",
                             contents[wrapper] + b'#include "../../../sim/simx/core.cpp"\n',
                             contents[wrapper].replace(b"../../../", b"../../../sim/../")):
                    with self.subTest(wrapper=wrapper, body=body), self.assertRaisesRegex(ValueError, "production include"):
                        runner.parse_build_records(text, words, **dict(arguments,
                            source_contents=dict(contents, **{wrapper: body})))
            for replacement in (generated[GENERATED_TCU] + b"// changed\n", contents[TCU_FOOTER],
                                contents[TCU_ORIGINAL] + contents[TCU_FOOTER],
                                contents[TCU_ORIGINAL] + b"\n" + contents[TCU_FOOTER] + b"// other footer\n"):
                with self.subTest(generated=replacement), self.assertRaisesRegex(ValueError, "exact production body"):
                    runner.parse_build_records(text, words, **dict(arguments,
                        generated_contents={GENERATED_TCU: replacement}))
            for replacement in (b"#define private public\n" + contents[TCU_FOOTER],
                                contents[TCU_FOOTER] + b'#include "../../../sim/simx/tcu/tcu_tbuf.cpp"\n'):
                with self.subTest(footer=replacement), self.assertRaisesRegex(ValueError, "TCU access footer"):
                    runner.parse_build_records(text, words, **dict(arguments,
                        source_contents=dict(contents, **{TCU_FOOTER: replacement}),
                        generated_contents={GENERATED_TCU: contents[TCU_ORIGINAL] + b"\n" + replacement}))
            for alternate in (source / TCU_FOOTER, build / "other.generated.cpp", source / TCU_ORIGINAL):
                with self.subTest(path=alternate), self.assertRaisesRegex(ValueError, "source inventory"):
                    runner.parse_build_records(text.replace(str(build / GENERATED_TCU), str(alternate)), words, **arguments)
            with self.assertRaisesRegex(ValueError, "exact source mapping"):
                original = str(fixture_object(build, "sim/simx/core.cpp"))
                runner.parse_build_records(text.replace(original, str(unit / "obj/foreign.o"))
                    .replace(original[:-2] + ".d", str(unit / "obj/foreign.d")), words, **arguments)

    def test_release_profile_rejects_concurrency_unsafe_optimization_and_guard_redefinition(self):
        with tempfile.TemporaryDirectory(prefix="p06-checked-stamp-") as directory:
            source, build = Path(directory) / "source", Path(directory) / "build"
            valid = compiler_stamp(source, build, True)
            runner.compile_flags(valid, checked=True, source=source, build=build)
            for extra in ("-DSIMX_CHECKED_COUNTERS=1", "-USIMX_CHECKED_COUNTERS", "-DSIMX_MT=0",
                          "-DSIMX_FUNCTIONAL=0", "-ffast-math", "-fno-access-control", "-I/foreign", "-DVX_CFG_NUM_CORES=2"):
                with self.subTest(extra=extra), self.assertRaises(ValueError):
                    runner.compile_flags(valid.rstrip() + " " + extra + "\n", checked=True, source=source, build=build)


if __name__ == "__main__":
    unittest.main()
