# SPDX-License-Identifier: Apache-2.0
"""Host-only checks of circuit evidence, with native subprocesses replaced."""

import argparse
import ast
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

import p06_mpm_synthesis as runner


SOURCE = Path(__file__).resolve().parents[2]


def report_entry(result):
    """Use the real gate's report schema without importing its optional packages."""
    tree = ast.parse((SOURCE / "ci/synth_gate.py").read_text())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "report_entry")
    namespace = {"config_hash": lambda *_: "fixture-config-hash"}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "ci/synth_gate.py", "exec"), namespace)
    return namespace["report_entry"](result, {}, None)


class CircuitFixture:
    """Keep the runner's real parsing, file identities and retained reports."""

    def __enter__(self):
        self.stack = ExitStack()
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix="mpm-circuit-test-"))).resolve()
        self.paths = {name: root / name for name in ("source", "tools", "work", "output")}
        for name in ("source", "tools"):
            self.paths[name].mkdir()
        for name in runner.INPUTS + ("hw/rtl/core/VX_csr_mpm.sv", "hw/rtl/other.sv"):
            self.write(self.paths["source"] / name, "fixture source: " + name + "\n")
        self.old_decoder = b"pinned original decoder\n"
        self.tool_paths = {}
        for name in ("make", "git", "python3", "bash"):
            self.tool_paths[name] = self.paths["tools"] / name
        for component, name in (("circt", "circt-opt"), ("circt", "circt-verilog"),
                                ("foldsim", "foldsim-opt"), ("yosys", "yosys"), ("yosys", "yosys-abc")):
            self.tool_paths[name] = self.paths["tools"] / component / "bin" / name
        for name, path in self.tool_paths.items():
            self.write(path, "fixture tool: " + name + "\n")
            path.chmod(0o700)
        self.source_status = ""
        self.results, self.diff_exits, self.calls = {}, {}, []
        self.after_command = lambda *_: None
        self.stack.enter_context(mock.patch.object(runner, "ROOT", self.paths["source"]))
        self.stack.enter_context(mock.patch.object(runner, "_git", side_effect=self.git))
        self.stack.enter_context(mock.patch.object(runner.shutil, "which", side_effect=lambda name, **_: str(self.tool_paths[name])))
        self.stack.enter_context(mock.patch.object(runner, "available_memory_bytes", return_value=8 * runner.GIB))
        usage = shutil.disk_usage(root)._replace(free=64 * runner.GIB)
        self.stack.enter_context(mock.patch.object(runner.shutil, "disk_usage", return_value=usage))
        self.bounded = self.stack.enter_context(mock.patch.object(runner, "run_bounded", side_effect=self.command))
        return self

    def __exit__(self, *error):
        return self.stack.__exit__(*error)

    @staticmethod
    def write(path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def git(self, source, *args):
        parent = Path(source) == self.paths["work"] / "reference"
        if args == ("rev-parse", "HEAD"):
            return (runner.REFERENCE if parent else "c" * 40).encode()
        if args == ("rev-parse", "HEAD^{tree}"):
            return ("a" if parent else "b").encode() * 40
        if args and args[0] == "status":
            return (" M ci/testcases/logic_gate.yaml\n" if parent else self.source_status).encode()
        if args == ("cat-file", "-t", runner.REFERENCE):
            return b"commit\n"
        if args == ("show", runner.REFERENCE + ":hw/rtl/core/VX_csr_mpm.sv"):
            return self.old_decoder
        raise AssertionError("unexpected Git request: " + repr(args))

    def argv(self, *extra):
        return ["--source-dir", str(self.paths["source"]), "--tools-dir", str(self.paths["tools"]),
                "--work-dir", str(self.paths["work"]), "--output", str(self.paths["output"]), *extra]

    def run(self, *extra):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = runner.main(self.argv(*extra))
        path = self.paths["output"] / "report.json"
        return code, json.loads(path.read_text()) if path.is_file() else None

    @staticmethod
    def leaf(build, width, perf):
        return build / "hw/syn/xilinx/dut" / f"logic_gate_mpm_transport_rv{width}_{perf}_mpm_transport"

    def beacon(self, name, argv):
        build = Path(argv[argv.index("--build-dir") + 1])
        build_id = argv[argv.index("-b") + 1]
        width, perf = int(build_id.split("_")[-2][2:]), build_id.rsplit("_", 1)[1]
        metrics = dict(zip(runner.METRICS, (4, 20, 100, 0, 0, 0, 0)))
        metrics.update(units={}, endpoints=132, watch_levels=8, fix_levels=12)
        if name.startswith("candidate-rv64"):
            metrics["ff"] += 24 if perf == "off" else 72
        row = report_entry({
            "build": {"id": build_id, "xlen": width, "group": "mpm_transport", "dut": "mpm_transport",
                      "clock_mhz": 200, "configs": "-DPERF_ENABLE" if perf == "on" else ""},
            "metrics": metrics, "error": None, "verdict": "NO-BASELINE", "reasons": ["no golden baseline"],
        })
        Path(argv[argv.index("--report") + 1]).write_text(json.dumps({"builds": [row]}))
        leaf = self.leaf(build, width, perf)
        for path in ("beacon/endpoints.csv", "beacon/report.txt", "beacon/area.csv", "beacon_summary.csv",
                     "beacon_units.json", "beacon_area.txt"):
            self.write(leaf / path, "fixture retained " + path + "\n")

    def command(self, argv, cwd, environment, log_path, **budget):
        cwd, log_path = Path(cwd), Path(log_path)
        name = log_path.stem
        self.calls.append(dict(id=name, argv=list(argv), cwd=cwd, environment=dict(environment), **budget))
        result = dict(outcome="pass", exit_code=0, reason=None, cleanup_complete=True, process_started=True)
        if name.endswith("-beacon"):
            result.update(outcome="fail", exit_code=1, reason="nonzero_exit")
        elif name.endswith("-beacon-diff"):
            result["exit_code"] = self.diff_exits.get(name.removesuffix("-beacon-diff"), 0)
            if result["exit_code"]:
                result.update(outcome="fail", reason="nonzero_exit")
        result.update(self.results.get(name, {}))
        text = "fixture process output\n"
        if result["process_started"] and result["reason"] in (None, "nonzero_exit"):
            if name == "reference-clone":
                reference = self.paths["work"] / "reference"
                shutil.copytree(self.paths["source"], reference)
                (reference / "hw/rtl/core/VX_csr_mpm.sv").write_bytes(self.old_decoder)
            elif name.endswith("-configure"):
                checkout = Path(argv[0]).parent
                width = next(arg.split("=", 1)[1] for arg in argv if arg.startswith("--xlen="))
                for path in runner.GENERATED:
                    self.write(cwd / path, "fixture generated " + path + "\n")
                config = f"XLEN ?= {width}\nPROFILE ?=\nVORTEX_HOME ?= {checkout}\nTOOLDIR ?= {self.paths['tools']}\n"
                if any(arg.startswith("--osversion=") for arg in argv):
                    config += "OSVERSION ?= " + next(arg.split("=", 1)[1] for arg in argv if arg.startswith("--osversion=")) + "\n"
                (cwd / "config.mk").write_text(config)
            elif name.endswith("-beacon"):
                self.beacon(name, argv)
            elif name.endswith("-yosys-sources"):
                circuit = cwd / "hw/syn/yosys" / ("mpm_measure_" + runner.TOP)
                self.write(circuit / "src/design.sv", "module " + runner.TOP + "; endmodule\n")
                self.write(circuit / "sources.txt", "+incdir+" + str(circuit / "src") + "\n+define+SYNTHESIS\n"
                           + str(circuit / "src/design.sv") + "\n")
            elif name.endswith("-yosys") and name.startswith(("parent-", "candidate-")):
                cells = {"$_AND_": 4, "$_DFF_P_": 8}
                (cwd / "generic-stat.json").write_text(json.dumps({"modules": {
                    "\\" + runner.TOP: {"num_cells": sum(cells.values()), "num_cells_by_type": cells}}}))
                (cwd / "generic-netlist.json").write_text('{"fixture_netlist": true}\n')
                text = "Longest topological path in " + runner.TOP + " (length=4):\n"
        self.after_command(name, cwd, argv)
        log_path.write_text(text)
        data = log_path.read_bytes()
        result.update(log_sha256=hashlib.sha256(data).hexdigest(), log_size_bytes=len(data))
        return result


class CircuitMeasurementTests(unittest.TestCase):
    def assert_nonaccepting(self, report):
        self.assertFalse(report["qualified"])
        self.assertFalse(report["acceptance_claimed"])
        self.assertNotEqual(report["gate_outcome"], "pass")
        self.assertTrue(any("no Liberty/STA" in item.get("yosys", {}).get("technology", "")
                            for item in report["measurements"]) or not report["measurements_complete"])

    def test_complete_low_depth_matrix_retains_real_gate_schema_and_no_baseline(self):
        with CircuitFixture() as fixture:
            code, report = fixture.run("--osversion", "ubuntu/focal")
            self.assertEqual((code, report["outcome"], report["gate_outcome"]),
                             (0, "measurements_complete", "not_passed"))
            expected = {(side, width, perf) for side in ("parent", "candidate")
                        for width in (32, 64) for perf in ("off", "on")}
            self.assertEqual({(item["side"], item["xlen"], item["perf"]) for item in report["measurements"]}, expected)
            self.assertEqual(len(report["measurements"]), 8)
            self.assertEqual(len(report["comparisons"]), 4)
            for item in report["measurements"]:
                self.assertEqual(item["beacon"]["metrics"]["units"], {})
                self.assertEqual((item["beacon"]["verdict"], item["beacon"]["exit_code"]), ("NO-BASELINE", 1))
                self.assertEqual(item["generated_before"], item["generated_after"])
                for key in ("configuration", "beacon_artifacts", "yosys_artifacts"):
                    self.assertTrue(item[key])
                    for artifact in item[key]:
                        data = (fixture.paths["output"] / artifact["path"]).read_bytes()
                        self.assertEqual(hashlib.sha256(data).hexdigest(), artifact["sha256"])
            self.assert_nonaccepting(report)
            ids = [call["id"] for call in fixture.calls]
            self.assertLess(max(i for i, name in enumerate(ids) if name.endswith("-beacon")),
                            min(i for i, name in enumerate(ids) if name.endswith("-yosys") and name.startswith(("parent-", "candidate-"))))
            for call in fixture.calls:
                self.assertEqual((call["max_rss_bytes"], call["min_free_bytes"], call["max_log_bytes"]),
                                 (4 * runner.GIB, 15 * runner.GIB, 16 * runner.MIB))
            self.assertFalse((fixture.paths["output"] / "report.json.tmp").exists())

    def test_area_and_depth_regressions_stay_red_after_complete_measurements(self):
        with CircuitFixture() as fixture:
            fixture.diff_exits.update({"rv64-off": 3, "rv64-on": 1})
            code, report = fixture.run()
            self.assertEqual((code, report["measurements_complete"], report["gate_outcome"]), (0, True, "fail"))
            self.assertEqual(report["regressions"], ["rv64-off: area", "rv64-on: depth"])
            comparisons = {item["id"]: item for item in report["comparisons"]}
            self.assertEqual(comparisons["rv64-off"]["beacon_deltas"]["ff"], 24)
            self.assertEqual(comparisons["rv64-on"]["beacon_deltas"]["ff"], 72)
            self.assertEqual(comparisons["rv64-off"]["diff_exit_code"], 3)
            self.assert_nonaccepting(report)

    def test_existing_output_is_not_overwritten(self):
        with CircuitFixture() as fixture:
            fixture.paths["output"].mkdir()
            marker = fixture.paths["output"] / "report.json"
            marker.write_text('{"previous": true}\n')
            code, report = fixture.run()
            self.assertEqual((code, report), (2, {"previous": True}))
            fixture.bounded.assert_not_called()
            self.assertFalse(fixture.paths["work"].exists())

    def test_unsafe_overlapping_and_symlink_paths_fail_before_commands(self):
        with CircuitFixture() as fixture:
            args = argparse.Namespace(source_dir=fixture.paths["source"], tools_dir=fixture.paths["tools"],
                                      work_dir=fixture.paths["work"], output=fixture.paths["output"])
            link = fixture.paths["tools"].parent / "linked-tools"
            link.symlink_to(fixture.paths["tools"], target_is_directory=True)
            for key, path in (("work_dir", fixture.paths["source"] / "build"),
                              ("output", fixture.paths["work"]), ("tools_dir", link),
                              ("output", fixture.paths["output"].parent / "unsafe path")):
                with self.subTest(key=key, path=path), self.assertRaises(ValueError):
                    changed = copy.copy(args)
                    setattr(changed, key, path)
                    runner.paths_for(changed)
            fixture.bounded.assert_not_called()

    def test_dirty_source_or_resource_shortage_blocks_before_commands(self):
        for condition in ("dirty", "disk", "memory"):
            with self.subTest(condition=condition), CircuitFixture() as fixture:
                if condition == "dirty":
                    fixture.source_status = " M hw/rtl/core/VX_csr_mpm.sv\n"
                elif condition == "disk":
                    runner.shutil.disk_usage.return_value = runner.shutil.disk_usage.return_value._replace(free=14 * runner.GIB)
                else:
                    runner.available_memory_bytes.return_value = 3 * runner.GIB
                code, report = fixture.run()
                self.assertEqual((code, report["outcome"], report["measurements_complete"]), (1, "blocked", False))
                fixture.bounded.assert_not_called()

    def test_native_stops_and_unexpected_gate_exit_never_complete(self):
        for change in ({"reason": "timeout", "exit_code": -15},
                       {"reason": "disk_reserve", "exit_code": None, "process_started": False},
                       {"reason": "nonzero_exit", "exit_code": 2}, {"cleanup_complete": False}):
            with self.subTest(change=change), CircuitFixture() as fixture:
                fixture.results["candidate-rv32-off-beacon"] = dict(outcome="fail", **change)
                code, report = fixture.run()
                self.assertEqual((code, report["outcome"], report["measurements_complete"]), (1, "fail", False))
                self.assertEqual(report["measurements"][0]["beacon"]["verdict"], "NO-BASELINE")
                self.assertFalse(any(call["id"].endswith("-yosys") and call["id"].startswith(("parent-", "candidate-")) for call in fixture.calls))
                self.assertTrue((fixture.paths["output"] / "logs/candidate-rv32-off-beacon.log").is_file())

    def test_incomplete_malformed_and_wrong_config_beacon_results_fail(self):
        for condition in ("missing", "nan", "negative", "bool", "no_endpoints", "no_units", "width", "perf", "error", "missing_raw"):
            with self.subTest(condition=condition), CircuitFixture() as fixture:
                def alter(name, cwd, argv):
                    if name != "parent-rv32-off-beacon":
                        return
                    path = Path(argv[argv.index("--report") + 1])
                    data = json.loads(path.read_text())
                    row = data["builds"][0]
                    if condition in ("nan", "negative", "bool"):
                        row["metrics"]["lut"] = {"nan": float("nan"), "negative": -1, "bool": True}[condition]
                    elif condition == "missing":
                        row["metrics"].pop("ff")
                    elif condition == "no_endpoints":
                        row["metrics"]["endpoints"] = 0
                    elif condition == "no_units":
                        row["metrics"].pop("units")
                    elif condition == "width":
                        row["xlen"] = 64
                    elif condition == "perf":
                        row["configs"] = "-DPERF_ENABLE"
                    elif condition == "error":
                        row["error"] = "build failed"
                    else:
                        build = Path(argv[argv.index("--build-dir") + 1])
                        (fixture.leaf(build, 32, "off") / "beacon/endpoints.csv").unlink()
                    path.write_text(json.dumps(data))
                fixture.after_command = alter
                code, report = fixture.run()
                self.assertEqual((code, report["measurements_complete"]), (1, False))
                self.assertIn("Beacon", report["reason"])
                self.assertFalse(any(call["id"].endswith("-yosys") and call["id"].startswith(("parent-", "candidate-")) for call in fixture.calls))

    def test_source_reference_tool_and_configuration_drift_veto_completion(self):
        for condition in ("source", "reference", "tool", "configuration"):
            with self.subTest(condition=condition), CircuitFixture() as fixture:
                def alter(name, cwd, argv):
                    if name != "parent-rv32-off-yosys":
                        return
                    target = {"source": fixture.paths["source"] / "hw/rtl/other.sv",
                              "reference": fixture.paths["work"] / "reference/hw/rtl/core/VX_csr_mpm.sv",
                              "tool": fixture.tool_paths["yosys"],
                              "configuration": fixture.paths["work"] / "parent-rv32-off/hw/VX_config.vh"}[condition]
                    target.write_bytes(target.read_bytes() + b"changed\n")
                fixture.after_command = alter
                code, report = fixture.run()
                self.assertEqual((code, report["outcome"], report["measurements_complete"]), (1, "fail", False))
                self.assertIn("changed", report["reason"])
                self.assertEqual(len(report["measurements"]), 8)
                self.assertTrue(all("beacon" in item for item in report["measurements"]))

    def test_production_source_is_excluded_from_reference_test_overlay(self):
        self.assertNotIn("hw/rtl/core/VX_csr_mpm.sv", runner.OVERLAY)
        self.assertFalse(any(name.startswith("hw/rtl/") or name.startswith("sim/") for name in runner.OVERLAY))
        with CircuitFixture() as fixture:
            code, report = fixture.run()
            self.assertEqual(code, 0)
            parent = fixture.paths["work"] / "reference"
            self.assertEqual((parent / "hw/rtl/core/VX_csr_mpm.sv").read_bytes(), fixture.old_decoder)
            self.assertNotEqual((fixture.paths["source"] / "hw/rtl/core/VX_csr_mpm.sv").read_bytes(), fixture.old_decoder)
            for path in runner.OVERLAY:
                self.assertEqual((fixture.paths["source"] / path).read_bytes(), (parent / path).read_bytes())
            self.assertEqual(report["reference_before"], report["reference_after"])

    def test_environment_and_commands_keep_perf_variants_explicit(self):
        poison = dict(PERF="0", CONFIGS="bad", PROFILE="bad", CXXFLAGS="bad", LD_PRELOAD="bad", MAKEFLAGS="-j99")
        with mock.patch.dict(os.environ, poison), CircuitFixture() as fixture:
            code, report = fixture.run()
            self.assertEqual(code, 0)
            for call in fixture.calls:
                self.assertFalse({"PERF", "CONFIGS", "PROFILE", "CXXFLAGS", "LD_PRELOAD"}.intersection(call["environment"]))
                self.assertEqual(call["environment"]["MAKEFLAGS"], "-j2")
                self.assertNotIn("--update-baseline", call["argv"])
                if call["id"].endswith("-yosys-sources"):
                    self.assertIn("PERF=", call["argv"])
                    self.assertNotIn("PERF=0", call["argv"])
                    self.assertIn("CONFIGS=" + ("-DPERF_ENABLE" if "-on-" in call["id"] else ""), call["argv"])
                if call["id"].startswith("candidate") and call["id"].endswith("-beacon"):
                    self.assertIn("--against", call["argv"])
            self.assert_nonaccepting(report)


class YosysParserTests(unittest.TestCase):
    def test_filelist_preserves_actual_sources_defines_and_include_paths(self):
        with tempfile.TemporaryDirectory(prefix="mpm-filelist-") as tmp:
            root = Path(tmp)
            source = root / "design.sv"
            source.write_text("module top; endmodule\n")
            filelist, script = root / "sources.txt", root / "generic.ys"
            filelist.write_text("# generated\n\n+incdir+" + str(root) + "\n+define+PERF_ENABLE\n" + str(source) + "\n")
            record = runner.yosys_script(filelist, script)
            self.assertEqual(record["sources"], [runner.identity(source)])
            self.assertEqual(record["script"], runner.identity(script))
            self.assertIn("-DPERF_ENABLE", script.read_text())
            self.assertIn("synth -top " + runner.TOP + " -flatten", script.read_text())
            self.assertIn("ltp -noff", script.read_text())
            self.assertNotIn("read_json", script.read_text())

    def test_filelist_rejects_empty_missing_relative_and_command_tokens(self):
        with tempfile.TemporaryDirectory(prefix="mpm-filelist-") as tmp:
            root = Path(tmp)
            filelist = root / "sources.txt"
            for data in ("", "relative.sv\n", str(root / "missing.sv") + "\n", "+define+SYNTHESIS;quit\n", "+incdir+has space\n"):
                with self.subTest(data=data), self.assertRaises(ValueError):
                    filelist.write_text(data)
                    runner.yosys_script(filelist, root / "generic.ys")

    def test_cell_counts_and_path_are_reported_without_physical_timing_claim(self):
        with tempfile.TemporaryDirectory(prefix="mpm-yosys-") as tmp:
            root = Path(tmp)
            (root / "generic-stat.json").write_text(json.dumps({"modules": {"\\" + runner.TOP: {
                "num_cells": 5, "num_cells_by_type": {"$_AND_": 2, "$_DFF_P_": 3}}}}))
            for form in ("length=7", "length = 7"):
                record = runner.read_yosys(root, "Longest topological path in top (" + form + "):\n")
                self.assertEqual((record["cells"], record["flip_flop_cells"], record["longest_topological_path"]), (5, 3, 7))
                self.assertEqual(record["technology"], "generic gates; no Liberty/STA")

    def test_malformed_counts_modules_or_depth_fail(self):
        valid = {"modules": {"\\" + runner.TOP: {"num_cells": 5, "num_cells_by_type": {"$_AND_": 2, "$_DFF_P_": 3}}}}
        with tempfile.TemporaryDirectory(prefix="mpm-yosys-") as tmp:
            root = Path(tmp)
            for condition in ("none", "two", "empty", "negative", "float", "boolean", "total", "missing_depth", "duplicate_depth", "mixed_depth", "negative_depth"):
                with self.subTest(condition=condition), self.assertRaises(ValueError):
                    data = copy.deepcopy(valid)
                    module = data["modules"]["\\" + runner.TOP]
                    log = "Longest topological path in top (length=7):\n"
                    if condition == "none":
                        data["modules"] = {}
                    elif condition == "two":
                        data["modules"]["other"] = copy.deepcopy(module)
                    elif condition == "empty":
                        module["num_cells_by_type"] = {}
                    elif condition in ("negative", "float", "boolean"):
                        module["num_cells_by_type"]["$_AND_"] = {"negative": -2, "float": 2.0, "boolean": True}[condition]
                    elif condition == "total":
                        module["num_cells"] = 6
                    elif condition == "missing_depth":
                        log = ""
                    elif condition == "duplicate_depth":
                        log *= 2
                    elif condition == "mixed_depth":
                        log += log.replace("length=7", "length = 7")
                    else:
                        log = log.replace("length=7", "length=-1")
                    (root / "generic-stat.json").write_text(json.dumps(data))
                    runner.read_yosys(root, log)


if __name__ == "__main__":
    unittest.main()
