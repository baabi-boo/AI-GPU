# SPDX-License-Identifier: Apache-2.0
"""Host orchestration faults with retained bytes; no native compiler or GPU runs."""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import shlex
import tempfile
import unittest
from unittest import mock

import p06_managed_preflight_execute as runner
import p06_managed_preflight_records as records
import p06_managed_preflight_test_fixture as samples
from test_p02_matrix import STAMP_SAMPLES


ROOT = runner.ROOT
REVISION = "a" * 40
FIRST = "preflight-simx-fp16-per_operation"
SECOND = "preflight-simx-fp16-reusable_single_tile"
LAST = "preflight-simx-bf16-reusable_single_tile"
HASH = runner.hash_artifacts
HEADER = STAMP_SAMPLES["header"]
EXPANDED = HEADER.rstrip() + "\n" + "".join(
    "#define " + name + "_DISABLE 1\n" for name in runner.DISABLED)


class ModuleView:
    def __init__(self, original, **values):
        self.original = original
        self.__dict__.update(values)

    def __getattr__(self, name):
        return getattr(self.original, name)


def arguments(*extra):
    return runner.argument_parser().parse_args([
        "run", "--tools-dir", "/managed-host-fixture/tools",
        "--work-dir", "/managed-host-fixture/work", "--output", "/managed-host-fixture/output",
        "--expected-revision", REVISION, *extra])


class ManagedHarness:
    """Simulate external producers around real lifecycle, hashing and output checks."""

    def __enter__(self):
        self.stack = ExitStack()
        parent = "/home/agent" if Path("/home/agent").is_dir() else None
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(
            prefix="managed-runner-host-", dir=parent))).resolve()
        self.paths = {name: root / name for name in ("source", "tools", "work", "output")}
        self.paths.update(host_bin=None, verilator=root / "tools/verilator")
        self.paths["source"].mkdir()
        self.paths["tools"].mkdir()
        self.args = arguments()
        for field, name in (("source_dir", "source"), ("tools_dir", "tools"),
                            ("work_dir", "work"), ("output", "output")):
            setattr(self.args, field, self.paths[name])
        names = set(runner.warm_contract._SOURCE_HASHES) | set(runner.base.COPIED) | {
            runner.warm_contract.MANIFEST_PATH, "sim/rtlsim/verilator.vlt.in",
            runner.APP + "/Makefile", runner.APP + "/backend.mk",
            "ci/project/p06_managed_preflight_execute.py", "ci/project/p06_managed_preflight_records.py"}
        for relative in sorted(names):
            path = self.paths["source"] / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((ROOT / relative).read_bytes())
        self.source_names = sorted(names)
        self.helper_names = ["ci/project/p06_managed_preflight_execute.py",
                             "ci/project/p06_managed_preflight_records.py"]
        self.helpers = HASH(self.paths["source"], self.helper_names)
        for relative in runner.base.DEPENDENCIES:
            path = self.paths["source"] / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"synthetic dependency payload: " + relative.encode())
        self.tool_paths = {}
        for name in ("g++", "gcc", "make", "python3", "clang", "riscv-gcc"):
            path = self.paths["tools"] / name
            path.write_bytes(b"synthetic tool bytes: " + name.encode())
            self.tool_paths[name] = path
        self.tool_paths["executing_python"] = self.tool_paths["python3"]
        self.checkout = {"revision": REVISION, "tree": "b" * 40, "dirty": False,
                         "changed_paths": [], "untracked_paths": [], "blockers": []}
        self.resources = {"available_memory_bytes": 4 * 1024**3, "free_disk_bytes": {
            name: 15 * 1024**3 for name in ("source", "tools", "work", "output")}}
        self.calls = []
        self.results, self.remove, self.exceptions = {}, {}, {}
        self.after_command = lambda name, build: None
        self.mutate_output = lambda name, text: text
        self.mutate_resources = lambda count, result: result
        self.resource_count = 0
        self.native_checkpoints = []
        self.stack.enter_context(mock.patch.object(runner, "LOADED_HELPERS", self.helpers))
        self.stack.enter_context(mock.patch.object(runner, "loaded_helpers", return_value=self.helpers))
        self.stack.enter_context(mock.patch.object(runner, "source_snapshot", side_effect=self.source_snapshot))
        self.stack.enter_context(mock.patch.object(runner, "tool_inventory", side_effect=self.tool_inventory))
        self.stack.enter_context(mock.patch.object(runner.base, "_resources", side_effect=self.resource_snapshot))
        self.stack.enter_context(mock.patch.object(runner, "sys", ModuleView(
            runner.sys, version_info=(3, 12, 14), platform="linux")))
        self.stack.enter_context(mock.patch.object(runner, "platform", ModuleView(
            runner.platform, python_implementation=lambda: "CPython")))
        self.stack.enter_context(mock.patch.object(runner, "run_bounded", side_effect=self.command))
        self.stack.enter_context(mock.patch.object(runner.build_records, "validate_build_commands",
            return_value={"synthetic_build_observation": True}))
        self.stack.enter_context(mock.patch.object(runner.build_records, "validate_records",
            side_effect=self.compiler_records))
        self.stack.enter_context(mock.patch.object(runner.build_records, "validate_effective_header",
            side_effect=lambda text, expected, **_: copy.deepcopy(expected)))
        self.verify = self.stack.enter_context(mock.patch.object(records, "verify_output", wraps=records.verify_output))
        return self

    def __exit__(self, *args):
        return self.stack.__exit__(*args)

    def source_snapshot(self, source, helpers=None):
        return {"checkout": copy.deepcopy(self.checkout), "files": HASH(source, self.source_names)}

    def tool_inventory(self, *_):
        return {name: runner.base._file_identity(path) for name, path in self.tool_paths.items()}

    def resource_snapshot(self, _):
        self.resource_count += 1
        return self.mutate_resources(self.resource_count, copy.deepcopy(self.resources))

    def compiler_records(self, *args, **kwargs):
        return [{"role": role, "macro_flags": ["-DSIMX_CHECKED_COUNTERS=1"],
                 "include_paths": [], "configuration": {"SIMX_CHECKED_COUNTERS": "1"}}
                for role in ("runtime", "backend_cpp", "kernel", "host")]

    def write_build(self, build, names):
        for relative in names:
            path = build / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("synthetic build payload: " + relative + "\n")

    def configure(self, build):
        self.write_build(build, runner.base.GENERATED + runner.base.COPIED + (
            runner.APP + "/Makefile", runner.APP + "/backend.mk"))
        for name in runner.base.COPIED + (runner.APP + "/Makefile", runner.APP + "/backend.mk"):
            (build / name).write_bytes((self.paths["source"] / name).read_bytes())
        (build / "sim/rtlsim/verilator.vlt").write_text(
            (self.paths["source"] / "sim/rtlsim/verilator.vlt.in").read_text().replace(
                "@VORTEX_HOME@", str(self.paths["source"])))
        settings = {"XLEN": "64", "PROFILE": "p02-tfr", "VORTEX_HOME": str(self.paths["source"]),
                    "TOOLDIR": str(self.paths["tools"]), "OSVERSION": "ubuntu/focal"}
        (build / "config.mk").write_text("".join(key + " ?= " + value + "\n" for key, value in settings.items()))
        (build / ".config.stamp").write_text("XLEN=64 PROFILE=p02-tfr SOURCE_DIR="
            + str(self.paths["source"]) + " BUILDDIR=" + str(build)
            + " TOOLDIR=" + str(self.paths["tools"]) + "\n")

    def command(self, argv, cwd, environment, logfile, **budget):
        name, cwd = logfile.stem, Path(cwd)
        self.calls.append({"id": name, "argv": list(argv), "cwd": cwd,
                           "environment": dict(environment), **budget})
        if name.startswith("preflight-"):
            self.native_checkpoints.append(json.loads((self.paths["output"] / "report.json").read_text()))
        build = self.paths["work"] / ("simx-bf16" if "bf16" in name else "simx-fp16")
        text = "synthetic supervised process; no native execution\n"
        if name.endswith("-configure"):
            self.configure(build)
        elif name.endswith("-header-reproduce"):
            destination = Path(next(arg.split("=", 1)[1] for arg in argv if arg.startswith("--output=")))
            relative = "sw/VX_config.h" if "-cpp-" in name else "hw/VX_config.vh"
            destination.write_bytes((build / relative).read_bytes())
        elif name.endswith("-expected-flags"):
            text = "-DVX_CFG_XLEN=64\n"
        elif name.endswith("-header"):
            text = HEADER if name in ("simx-fp16-header", "simx-bf16-header") else EXPANDED
        elif name.endswith("-backend"):
            self.write_build(build, [path for path in runner.artifacts(build)
                if path.startswith("sw/runtime/") and path not in runner.base.COPIED])
        elif name.endswith("-application"):
            self.write_build(build, [path for path in runner.artifacts(build)
                if path not in runner.base.GENERATED + runner.base.COPIED
                and path not in (runner.HEADER_PROBE, runner.APP + "/Makefile", runner.APP + "/backend.mk")])
            app = build / runner.APP
            (app / "ai_counter_preflight").chmod(0o700)
            flags = "-DSIMX_CHECKED_COUNTERS=1"
            link = shlex.join(runner.build_records.host_link_flags(build))
            (app / "config.stamp").write_text(flags + "\n" + flags + "\n" + link + "\n")
            text = shlex.join([str(self.tool_paths["g++"]), flags,
                *(str(self.paths["source"] / relative) for relative in runner.build_records.APP_SOURCES),
                str(build / "sw/runtime/libvortex.so"), *shlex.split(link), "-o", "ai_counter_preflight"]) + "\n"
        elif "--policy" in argv:
            values = dict(zip(argv[1::2], argv[2::2]))
            _, operations, summary, witness = samples.raw_records(
                "bf16" if "bf16" in name else "fp16", values["--policy"], binding_id=values["--qualification-id"])
            libraries = runner.expected_libraries(self.paths["source"], build)
            witness["loaded_libraries"] = [{"name": key, "path": value} for key, value in sorted(libraries.items())]
            text = samples.render_log(operations, summary, witness)
        text = self.mutate_output(name, text)
        logfile.write_bytes(text if type(text) is bytes else text.encode("utf-8"))
        self.after_command(name, build)
        if name in self.exceptions:
            raise self.exceptions[name]
        response = {"outcome": "pass", "exit_code": 0, "reason": None, "process_started": True,
                    "cleanup_complete": True, "duration_seconds": 0.01, "peak_rss_bytes": 1024,
                    "log_sha256": hashlib.sha256(logfile.read_bytes()).hexdigest(),
                    "log_size_bytes": logfile.stat().st_size}
        response.update(self.results.get(name, {}))
        for key in self.remove.get(name, ()):
            response.pop(key, None)
        return response

    def run(self):
        result = runner.execute(self.args, self.paths)
        self.saved = json.loads((self.paths["output"] / "report.json").read_text())
        return result

    def launches(self):
        return [call["id"] for call in self.calls if call["id"].startswith("preflight-")]


class ManagedRunnerTests(unittest.TestCase):
    def assert_finished(self, fixture, result, *, passed=False):
        self.assertEqual(result, fixture.saved)
        self.assertEqual(result["state"], "finished")
        self.assertIs(result["native_preflight_passed"], passed)
        for name in runner.manifest.FALSE_CLAIMS:
            self.assertIs(result[name], False, name)
        self.assertEqual(result["unresolved_obligations"], list(runner.manifest.UNRESOLVED_OBLIGATIONS))
        if not passed:
            self.assertIn(result["outcome"], ("blocked", "fail"))
            self.assertTrue(result["failures"])

    def test_complete_four_cells_retain_real_bytes_and_distinct_bindings(self):
        with ManagedHarness() as fixture:
            result = fixture.run()
            self.assert_finished(fixture, result, passed=True)
            self.assertEqual(result["outcome"], "pass")
            self.assertEqual(result["completed_counts"], runner.COMPLETE_COUNTS)
            self.assertEqual(fixture.launches(), [row["id"] for row in runner.manifest.process_plan()])
            self.assertEqual(fixture.verify.call_count, 4)
            self.assertEqual(result["native_execution"], "run")
            self.assertEqual(len({row["execution_binding_sha256"] for row in result["processes"]}), 4)
            self.assertEqual(len({row["build_binding_sha256"] for row in result["processes"]}), 2)
            self.assertEqual(result["retained_files"], HASH(fixture.paths["output"], [row["path"] for row in result["retained_files"]]))
            self.assertGreater(result["retained_payload_bytes"], 0)
            self.assertEqual(fixture.native_checkpoints[0]["native_execution"], "unknown")
            self.assertTrue(all(row["native_execution"] == "run" for row in fixture.native_checkpoints[1:]))

    def test_every_command_is_bounded_and_scrubbed_with_one_model_worker(self):
        with ManagedHarness() as fixture, mock.patch.dict(os.environ, {
                "THREADS": "99", "MAKEFLAGS": "-j99", "CONFIGS": "-DSIMX_FUNCTIONAL=1",
                "LD_PRELOAD": "/foreign.so", "PYTHONPATH": "/foreign"}):
            result = fixture.run()
            self.assert_finished(fixture, result, passed=True)
            for call in fixture.calls:
                self.assertEqual({key: call[key] for key in runner.BUDGET}, runner.BUDGET)
                self.assertEqual(call["resource_paths"], tuple(fixture.paths[key] for key in ("source", "tools", "work", "output")))
                self.assertEqual(call["environment"]["THREADS"], "1")
                self.assertEqual(call["environment"]["MAKEFLAGS"], "-j2")
                self.assertNotIn("LD_PRELOAD", call["environment"])
                self.assertNotIn("PYTHONPATH", call["environment"])
                if call["id"].endswith(("-backend", "-application")):
                    self.assertIn("THREADS=1", call["argv"])
                    self.assertIn("-j2", call["argv"])
                    self.assertIn("-DSIMX_CHECKED_COUNTERS=1", call["environment"]["CONFIGS"])
                if call["id"].startswith("preflight-"):
                    self.assertEqual(call["timeout_seconds"], 180)
                    self.assertEqual(call["environment"]["VORTEX_DRIVER"], "simx")

    def test_resource_blockers_retain_zero_start_disposition(self):
        for kind in ("disk", "memory", "unknown-memory"):
            with self.subTest(kind=kind), ManagedHarness() as fixture:
                if kind == "disk":
                    fixture.resources["free_disk_bytes"]["source"] -= 1
                else:
                    fixture.resources["available_memory_bytes"] = None if kind == "unknown-memory" else 4 * 1024**3 - 1
                result = fixture.run()
                self.assert_finished(fixture, result)
                self.assertEqual(fixture.calls, [])
                self.assertEqual(result["native_execution"], "not_run")
                self.assertFalse(any(result["completed_counts"].values()))

    def test_dirty_wrong_revision_and_provenance_blockers_prevent_commands(self):
        for kind in ("dirty", "revision", "blocker", "helper"):
            with self.subTest(kind=kind), ManagedHarness() as fixture:
                if kind == "dirty":
                    fixture.checkout["dirty"] = True
                elif kind == "revision":
                    fixture.checkout["revision"] = "b" * 40
                elif kind == "blocker":
                    fixture.checkout["blockers"] = ["source contains untracked inputs"]
                else:
                    (fixture.paths["source"] / fixture.helper_names[0]).write_bytes(b"changed imported helper")
                result = fixture.run()
                self.assert_finished(fixture, result)
                self.assertEqual(fixture.calls, [])

    def test_interpreter_pin_and_path_identity_are_enforced_before_commands(self):
        for kind in ("version", "platform", "implementation", "identity"):
            with self.subTest(kind=kind), ManagedHarness() as fixture:
                if kind == "version":
                    fixture.stack.enter_context(mock.patch.object(runner.sys, "version_info", (3, 12, 13)))
                elif kind == "platform":
                    fixture.stack.enter_context(mock.patch.object(runner.sys, "platform", "darwin"))
                elif kind == "implementation":
                    fixture.stack.enter_context(mock.patch.object(runner.platform, "python_implementation", return_value="Other"))
                else:
                    fixture.tool_paths["executing_python"] = fixture.tool_paths["make"]
                result = fixture.run()
                self.assert_finished(fixture, result)
                self.assertEqual(fixture.calls, [])

    def test_source_dependency_and_interpreter_drift_stop_before_second_policy(self):
        for kind in ("source", "dependency", "tool", "helper", "interpreter"):
            with self.subTest(kind=kind), ManagedHarness() as fixture:
                target = {"source": fixture.paths["source"] / "sw/kernel/ai/matmul.cpp",
                    "dependency": fixture.paths["source"] / runner.base.DEPENDENCIES[0],
                    "tool": fixture.tool_paths["g++"], "helper": fixture.paths["source"] / fixture.helper_names[0],
                    "interpreter": fixture.tool_paths["python3"]}[kind]
                fixture.after_command = lambda name, build: target.write_bytes(target.read_bytes() + b"drift") if name == FIRST else None
                result = fixture.run()
                self.assert_finished(fixture, result)
                self.assertEqual(fixture.launches(), [FIRST])
                self.assertIn("changed", result["reason"])
                self.assertEqual(result["native_execution"], "run")

    def test_binary_drift_after_first_process_invalidates_it_without_retry(self):
        with ManagedHarness() as fixture:
            fixture.after_command = lambda name, build: (build / runner.BINARY_FILES[0]).write_bytes(b"substituted") if name == FIRST else None
            result = fixture.run()
            self.assert_finished(fixture, result)
            self.assertEqual(fixture.launches(), [FIRST])
            self.assertEqual(result["completed_counts"]["processes"], 0)
            self.assertIn("artifacts changed", result["reason"])

    def test_started_failed_process_retains_log_and_partial_counts(self):
        with ManagedHarness() as fixture:
            fixture.results[SECOND] = {"outcome": "fail", "exit_code": -15, "reason": "timeout"}
            result = fixture.run()
            self.assert_finished(fixture, result)
            self.assertEqual(fixture.launches(), [FIRST, SECOND])
            self.assertEqual(result["completed_counts"]["processes"], 1)
            self.assertEqual(result["completed_counts"]["launches"], 33)
            self.assertIn("timeout", result["reason"])
            self.assertIn("logs/" + SECOND + ".log", {row["path"] for row in result["raw_logs"]})

    def test_success_text_cannot_rescue_failed_supervision(self):
        changes = ({"exit_code": 1}, {"exit_code": False}, {"cleanup_complete": False},
                   {"process_started": False}, {"process_started": None},
                   {"reason": "log_limit"}, {"outcome": "blocked"})
        for change in changes:
            with self.subTest(change=change), ManagedHarness() as fixture:
                fixture.results[FIRST] = change
                result = fixture.run()
                self.assert_finished(fixture, result)
                self.assertEqual(fixture.launches(), [FIRST])
                self.assertEqual(fixture.verify.call_count, 0)
                self.assertEqual(result["completed_counts"]["processes"], 0)

    def test_missing_or_changed_original_log_identity_rejects(self):
        for kind in ("missing", "digest", "size"):
            with self.subTest(kind=kind), ManagedHarness() as fixture:
                if kind == "missing":
                    fixture.remove[FIRST] = ["log_sha256"]
                else:
                    fixture.results[FIRST] = {"log_sha256": "0" * 64} if kind == "digest" else {"log_size_bytes": 0}
                result = fixture.run()
                self.assert_finished(fixture, result)
                self.assertEqual(fixture.verify.call_count, 0)
                self.assertEqual(result["completed_counts"]["processes"], 0)

    def test_supervisor_exception_before_first_receipt_is_unknown_and_retains_partial_log(self):
        for error in (OSError("lost receipt"), RuntimeError("supervisor stopped"), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__), ManagedHarness() as fixture:
                fixture.exceptions[FIRST] = error
                result = fixture.run()
                self.assert_finished(fixture, result)
                self.assertEqual(result["native_execution"], "unknown")
                self.assertEqual(result["completed_counts"]["processes"], 0)
                self.assertIn("logs/" + FIRST + ".log", {row["path"] for row in result["raw_logs"]})

    def test_supervisor_exception_after_a_confirmed_process_keeps_run(self):
        with ManagedHarness() as fixture:
            fixture.exceptions[SECOND] = OSError("receipt lost")
            result = fixture.run()
            self.assert_finished(fixture, result)
            self.assertEqual(result["native_execution"], "run")
            self.assertEqual(result["completed_counts"]["processes"], 1)

    def test_explicit_nonstart_receipt_restores_not_run(self):
        with ManagedHarness() as fixture:
            fixture.results[FIRST] = {"process_started": False, "outcome": "blocked", "reason": "disk_reserve"}
            result = fixture.run()
            self.assert_finished(fixture, result)
            self.assertEqual(result["native_execution"], "not_run")

    def test_record_validation_failure_stops_following_cells(self):
        with ManagedHarness() as fixture:
            fixture.mutate_output = lambda name, text: text.replace('"qualified":false', '"qualified":true') if name == FIRST else text
            result = fixture.run()
            self.assert_finished(fixture, result)
            self.assertEqual(fixture.launches(), [FIRST])
            self.assertEqual(fixture.verify.call_count, 1)
            self.assertEqual(result["completed_counts"]["processes"], 0)

    def test_final_resource_failure_invalidates_all_four_completed_cells(self):
        with ManagedHarness() as fixture:
            def resources(count, value):
                if count > 1:
                    value["free_disk_bytes"]["output"] = 15 * 1024**3 - 1
                return value
            fixture.mutate_resources = resources
            result = fixture.run()
            self.assert_finished(fixture, result)
            self.assertEqual(result["completed_counts"], runner.COMPLETE_COUNTS)
            self.assertIn("final disk reserve", result["reason"])

    def test_retained_binary_payload_tamper_is_detected_at_finalization(self):
        with ManagedHarness() as fixture:
            def tamper(name, build):
                if name == LAST:
                    target = fixture.paths["output"] / "artifacts/simx-fp16/binaries" / runner.BINARY_FILES[0]
                    target.write_bytes(b"retained binary changed")
            fixture.after_command = tamper
            result = fixture.run()
            self.assert_finished(fixture, result)
            self.assertEqual(result["completed_counts"], runner.COMPLETE_COUNTS)
            self.assertFalse(result["retained_files_stable"])

    def test_old_success_log_changed_later_invalidates_packet(self):
        with ManagedHarness() as fixture:
            def tamper(name, build):
                if name == LAST:
                    target = fixture.paths["output"] / ("logs/" + FIRST + ".log")
                    target.write_bytes(target.read_bytes() + b"changed\n")
            fixture.after_command = tamper
            result = fixture.run()
            self.assert_finished(fixture, result)
            self.assertIn("original command log changed", result["reason"])

    def test_payload_limits_block_before_native_execution(self):
        for name, value in (("MAX_PAYLOAD_FILE_BYTES", 1), ("MAX_PAYLOAD_BYTES", 1)):
            with self.subTest(name=name), ManagedHarness() as fixture, mock.patch.object(runner, name, value):
                result = fixture.run()
                self.assert_finished(fixture, result)
                self.assertEqual(fixture.launches(), [])
                self.assertEqual(result["native_execution"], "not_run")

    def test_repeat_attempt_cannot_replace_existing_output(self):
        with ManagedHarness() as fixture:
            fixture.resources["available_memory_bytes"] = 0
            fixture.run()
            original = (fixture.paths["output"] / "report.json").read_bytes()
            with self.assertRaises(FileExistsError):
                fixture.run()
            self.assertEqual((fixture.paths["output"] / "report.json").read_bytes(), original)


class ManagedBoundaryTests(unittest.TestCase):
    def test_native_execution_states_preserve_unknown_and_observed_starts(self):
        expected = {
            "not_run": {False: "not_run", True: "run", None: "unknown"},
            "unknown": {False: "unknown", True: "run", None: "unknown"},
            "run": {False: "run", True: "run", None: "run"},
        }
        for previous, states in expected.items():
            for started, state in states.items():
                self.assertEqual(runner.native_execution_state(previous, started), state)
        for previous, started in (("pass", True), ("not_run", 0), ("not_run", 1), ("not_run", "true")):
            with self.assertRaises(ValueError):
                runner.native_execution_state(previous, started)

    def test_cli_cannot_shrink_matrix_or_increase_budgets(self):
        invalid = (("--format", "fp16"), ("--policy", "per_operation"), ("--allow-dirty",),
                   ("--iterations", "1"), ("--jobs", "3"), ("--jobs", "0"),
                   ("--timeout-seconds", "1801"), ("--run-timeout-seconds", "181"),
                   ("--run-timeout-seconds", "0"), ("--min-free-bytes", "0"))
        for options in invalid:
            with self.subTest(options=options), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                arguments(*options)

    def test_paths_are_fresh_disjoint_and_have_no_symlink_aliases(self):
        parent = "/home/agent" if Path("/home/agent").is_dir() else None
        with tempfile.TemporaryDirectory(prefix="managed-paths-", dir=parent) as temporary:
            root = Path(temporary)
            tools = root / "tools"
            tools.mkdir()
            args = arguments("--source-dir", str(ROOT), "--tools-dir", str(tools),
                             "--work-dir", str(root / "work"), "--output", str(root / "output"))
            runner.base.resolve_paths(args)
            alias = root / "alias"
            alias.symlink_to(tools, target_is_directory=True)
            for field, value in (("work_dir", tools), ("output", tools), ("output", args.work_dir),
                ("work_dir", ROOT / "managed-test-work"), ("output", ROOT / "managed-test-output"),
                ("tools_dir", alias), ("work_dir", root / "absent/work"), ("output", root / "unsafe path")):
                changed = copy.copy(args)
                setattr(changed, field, value)
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    runner.base.resolve_paths(changed)

    def test_main_reports_blocked_without_claims_when_path_resolution_fails(self):
        output = io.StringIO()
        with mock.patch.object(runner.base, "resolve_paths", side_effect=ValueError("fresh path required")), redirect_stdout(output):
            code = runner.main(["run", "--tools-dir", "/tools", "--work-dir", "/work",
                                "--output", "/output", "--expected-revision", REVISION])
        result = json.loads(output.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(result["outcome"], "blocked")
        for name in ("native_preflight_passed", *runner.manifest.FALSE_CLAIMS):
            self.assertIs(result[name], False)


if __name__ == "__main__":
    unittest.main()
