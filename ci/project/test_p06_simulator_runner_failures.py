# SPDX-License-Identifier: Apache-2.0
"""Host-only adversarial receipts; no native compiler or simulator is executed."""

from contextlib import ExitStack
import copy
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import p06_simulator_execute as runner
from test_p02_matrix import STAMP_SAMPLES, sample
from test_p06_simulator_execute import UNIT_OUTPUT, public_output


ROLES = ((0, 0, "unit_model"), (1, 0, "runtime_model"), (2, 0, "runtime"),
         (3, 0, "kernel"), (3, 1, "host"))


class HostFixture:
    """Use real files, identities and validation around a simulated command seam."""

    def __enter__(self):
        self.stack = ExitStack()
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix="simulator-failures-")))
        self.paths = {name: root / name for name in ("source", "tools", "work", "output")}
        self.paths.update(host_bin=None, verilator=root / "tools/verilator")
        for name in ("source", "tools"):
            self.paths[name].mkdir()
        self.build = self.paths["work"] / "rv64-p02-tfr"
        names = set(runner.SOURCE_FILES + runner.base.COPIED)
        names.update(row["path"] for row in runner.LOADED_HELPERS)
        names.update(("configure", "config.mk.in", "VERSION", "VX_config.toml",
                      "profiles/p02-tfr.json", "sim/rtlsim/verilator.vlt.in"))
        self.source_names = sorted(names)
        for name in self.source_names:
            destination = self.paths["source"] / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((runner.ROOT / name).read_bytes())
        for name in runner.base.DEPENDENCIES:
            destination = self.paths["source"] / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text("synthetic dependency: " + name + "\n", encoding="utf-8")
        self.tool_paths = {}
        for name in ("make", "g++", "clang", "clang++", "python3", "executing_python"):
            path = self.paths["tools"] / name
            path.write_text("synthetic tool: " + name + "\n", encoding="utf-8")
            path.chmod(0o700)
            self.tool_paths[name] = path
        self.checkout = {"revision": "a" * 40, "tree": "b" * 40, "dirty": False, "blockers": []}
        self.resources = {"free_disk_bytes": {name: 32 * 1024**3 for name in ("source", "tools", "work", "output")},
                          "available_memory_bytes": 8 * 1024**3}
        profile = subprocess.run(
            [sys.executable, str(self.paths["source"] / "ci/gen_config.py"),
             "--config=" + str(self.paths["source"] / "VX_config.toml"),
             "--profile=p02-tfr", "--xlen=64", "--merge-configs", "--cflags=-DVX_CFG_XLEN=64"],
            capture_output=True, text=True, check=True, timeout=30)
        self.configs = shlex.split(profile.stdout)

        def completion_stamp(name):
            text = sample(name, source=self.paths["source"], build=self.build, tools=self.paths["tools"])
            for flag in ("-DITYPE=bf16", "-DOTYPE=fp32", "-DKUNROLL=1"):
                text = text.replace(" " + flag, "")
            return text

        # Retained Makefile samples supply actual options; completion has no GEMM selectors.
        model = completion_stamp("simx_backend").rstrip("\n") + " -DPERF_ENABLE\n"
        unit = model.replace(str(self.build / "sw/runtime/simx_config.stamp"),
                             str(self.build / "sim/simx/simx_config.stamp"))
        application = completion_stamp("application").splitlines()
        application[1] = application[1].replace(
            "-I" + str(self.paths["source"] / "third_party/softfloat/source/include") + " ", "")
        application[2] = application[2].replace(
            str(self.paths["source"] / "third_party/softfloat/build/Linux-x86_64-GCC/softfloat.a") + " ", "")
        self.stamps = [unit, model, completion_stamp("simx_rt"), "\n".join(application) + "\n"]
        self.results = {}
        self.outputs = {}
        self.calls = []
        self.after_command = lambda name: None
        self.stack.enter_context(mock.patch.object(runner, "source_snapshot", side_effect=self.source_snapshot))
        self.stack.enter_context(mock.patch.object(runner.base, "_resources", side_effect=lambda paths: copy.deepcopy(self.resources)))
        self.stack.enter_context(mock.patch.object(runner.base, "tool_inventory", side_effect=self.tool_inventory))
        self.stack.enter_context(mock.patch.object(runner.sys, "executable", str(self.tool_paths["executing_python"])))
        self.bounded = self.stack.enter_context(mock.patch.object(runner, "run_bounded", side_effect=self.command))
        return self

    def __exit__(self, *error):
        return self.stack.__exit__(*error)

    def source_snapshot(self, source):
        return {"checkout": copy.deepcopy(self.checkout),
                "files": runner.hash_artifacts(source, self.source_names)}

    def tool_inventory(self, paths, environment, backends):
        return {name: runner.base._file_identity(path) for name, path in self.tool_paths.items()
                if name != "executing_python"}

    def configure(self):
        for name in runner.GENERATED:
            destination = self.build / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text("synthetic configured input: " + name + "\n", encoding="utf-8")
        for name in runner.base.COPIED + ("sim/simx/completion.mk", runner.APP + "/Makefile"):
            (self.build / name).write_bytes((self.paths["source"] / name).read_bytes())
        config = {"XLEN": "64", "PROFILE": "p02-tfr", "VORTEX_HOME": str(self.paths["source"]),
                  "TOOLDIR": str(self.paths["tools"]), "OSVERSION": "ubuntu/focal",
                  "INSTALLDIR": str(self.build / "install")}
        config.update(line.split("=", 1) for line in
                      (self.paths["source"] / "VERSION").read_text(encoding="utf-8").splitlines())
        template = (self.paths["source"] / "config.mk.in").read_text(encoding="utf-8")
        for name, value in config.items():
            template = template.replace("@" + name + "@", value)
        (self.build / "config.mk").write_text(template, encoding="utf-8")
        (self.build / ".config.stamp").write_text(
            "XLEN=64 PROFILE=p02-tfr SOURCE_DIR=" + str(self.paths["source"])
            + " BUILDDIR=" + str(self.build) + " TOOLDIR=" + str(self.paths["tools"]) + "\n", encoding="utf-8")
        (self.build / "sim/rtlsim/verilator.vlt").write_text(
            (self.paths["source"] / "sim/rtlsim/verilator.vlt.in").read_text().replace(
                "@VORTEX_HOME@", str(self.paths["source"])), encoding="utf-8")

    def compile(self):
        for name in runner.BINARIES:
            destination = self.build / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text("synthetic binary: " + name + "\n", encoding="utf-8")
            destination.chmod(0o700)
        for name, text in zip(runner.STAMPS, self.stamps):
            (self.build / name).write_text(text, encoding="utf-8")

    def alter_role(self, outer, inner, transform):
        lines = self.stamps[outer].splitlines()
        lines[inner] = transform(lines[inner])
        self.stamps[outer] = "\n".join(lines) + "\n"

    def command(self, argv, cwd, environment, logfile, **budget):
        name = logfile.stem
        self.calls.append({"id": name, "argv": list(argv), "cwd": Path(cwd),
                           "environment": dict(environment), **budget})
        result = {"outcome": "pass", "exit_code": 0, "reason": None, "process_started": True,
                  "cleanup_complete": True, "duration_seconds": 0.01, "peak_rss_bytes": 1024}
        text = "synthetic host-only command; no native execution\n"
        if name == "configure":
            self.configure()
        elif name == "application-build":
            self.compile()
        elif name == "profile-flags":
            text = " ".join(self.configs) + "\n"
        elif name.startswith("header-"):
            text = STAMP_SAMPLES["header"]
            if name.endswith("_model"):
                text += "#define PERF_ENABLE 1\n"
        elif name == "unit-run":
            text = UNIT_OUTPUT
        elif name == "public-run":
            text = public_output()
        logfile.write_text(self.outputs.get(name, text), encoding="utf-8")
        digest, size = runner._digest(logfile)
        result.update(log_sha256=digest, log_size_bytes=size)
        result.update(self.results.get(name, {}))
        self.after_command(name)
        return result

    def run(self):
        report = runner.execute(None, self.paths)
        self.persisted = json.loads((self.paths["output"] / "report.json").read_text(encoding="utf-8"))
        return report


class SimulatorRunnerFailureTests(unittest.TestCase):
    def assert_rejected(self, fixture, report, outcome="fail"):
        self.assertEqual(report, fixture.persisted)
        self.assertEqual((report["state"], report["outcome"]), ("finished", outcome))
        self.assertFalse(report["full_matrix_completed"])
        self.assertFalse(report["qualified"])
        self.assertFalse(report["acceptance_claimed"])

    def test_control_reaches_both_cells_with_every_command_bounded(self):
        with HostFixture() as fixture:
            report = fixture.run()
            self.assertEqual(report, fixture.persisted)
            self.assertEqual(report["outcome"], "pass")
            self.assertTrue(report["full_matrix_completed"])
            self.assertFalse(report["qualified"])
            self.assertFalse(report["acceptance_claimed"])
            self.assertEqual([row["id"] for row in fixture.calls if row["id"].endswith("-run")],
                             ["unit-run", "public-run"])
            self.assertEqual(set(report["effective_headers"]), {role for _, _, role in ROLES})
            for call in fixture.calls:
                self.assertEqual({key: call[key] for key in runner.BUDGET}, runner.BUDGET)
                self.assertEqual(call["resource_paths"], tuple(fixture.paths[name] for name in ("source", "tools", "work", "output")))
                stage = call["id"].rsplit("-", 1)[-1]
                self.assertEqual(call["timeout_seconds"], runner.TIMEOUTS.get(stage, runner.TIMEOUTS["probe"]))
                self.assertEqual(call["environment"]["THREADS"], "1")
                self.assertEqual(call["environment"]["MAKEFLAGS"], "-j2")

    def test_late_resource_failure_cannot_be_rescued_by_complete_success_output(self):
        for reason in ("timeout", "memory_limit", "disk_reserve", "log_limit"):
            with self.subTest(reason=reason), HostFixture() as fixture:
                fixture.results["public-run"] = {"outcome": "fail", "exit_code": -15, "reason": reason}
                report = fixture.run()
                self.assert_rejected(fixture, report)
                self.assertIn(reason, report["reason"])
                self.assertEqual([cell["outcome"] for cell in report["cells"]], ["pass", "fail"])
                self.assertNotIn("observations", report["cells"][1])
                self.assertEqual((fixture.paths["output"] / "logs/public-run.log").read_text(), public_output())
                self.assertEqual(report["commands"][-1]["reason"], reason)

    def test_pass_receipt_still_requires_started_zero_exit_and_complete_cleanup(self):
        for change in ({"process_started": False}, {"exit_code": 7}, {"cleanup_complete": False}):
            with self.subTest(change=change), HostFixture() as fixture:
                fixture.results["public-run"] = change
                report = fixture.run()
                self.assert_rejected(fixture, report)
                self.assertEqual([cell["outcome"] for cell in report["cells"]], ["pass", "fail"])
                self.assertNotIn("observations", report["cells"][1])

    def test_resource_block_before_any_process_keeps_every_cell_blocked(self):
        with HostFixture() as fixture:
            fixture.results["version-make"] = {"outcome": "blocked", "exit_code": None,
                                                 "process_started": False, "reason": "disk_reserve"}
            report = fixture.run()
            self.assert_rejected(fixture, report, "blocked")
            self.assertEqual([row["id"] for row in fixture.calls], ["version-make"])
            self.assertTrue(all(cell["outcome"] == "blocked" for cell in report["cells"]))

    def test_source_tools_and_executing_interpreter_drift_stop_the_second_cell(self):
        for kind in ("source", "tool", "interpreter", "dependency"):
            with self.subTest(kind=kind), HostFixture() as fixture:
                target = {"source": fixture.paths["source"] / "tests/unittest/simx_completion/main.cpp",
                          "tool": fixture.tool_paths["g++"], "interpreter": fixture.tool_paths["executing_python"],
                          "dependency": fixture.paths["source"] / runner.base.DEPENDENCIES[0]}[kind]
                fixture.after_command = lambda name: target.write_bytes(target.read_bytes() + b"drift\n") if name == "unit-run" else None
                report = fixture.run()
                self.assert_rejected(fixture, report)
                self.assertNotIn("public-run", [call["id"] for call in fixture.calls])
                self.assertIn("changed", report["reason"])

    def test_configure_settings_and_copied_completion_inputs_must_match(self):
        changes = (("config.mk", lambda text: text.replace("PROFILE ?= p02-tfr", "PROFILE ?= other")),
                   ("config.mk", lambda text: text.replace("LLVM_PATH ?= $(TOOLDIR)/llvm-vortex",
                                                          "LLVM_PATH ?= /unretained-compiler-input")),
                   ("config.mk", lambda text: text.replace(
                       "RISCV_SYSROOT ?= $(RISCV_TOOLCHAIN_PATH)/$(RISCV_PREFIX)",
                       "RISCV_SYSROOT ?= /unretained-compiler-input")),
                   (".config.stamp", lambda text: text.replace("XLEN=64", "XLEN=32")),
                   ("sim/simx/completion.mk", lambda text: text + "# changed\n"),
                   (runner.APP + "/Makefile", lambda text: text + "# changed\n"))
        for name, change in changes:
            with self.subTest(name=name), HostFixture() as fixture:
                def alter(command):
                    if command == "configure":
                        path = fixture.build / name
                        path.write_text(change(path.read_text()), encoding="utf-8")
                fixture.after_command = alter
                report = fixture.run()
                self.assert_rejected(fixture, report)
                self.assertEqual(fixture.calls[-1]["id"], "configure")
                self.assertTrue(all(cell["outcome"] == "blocked" for cell in report["cells"]))

    def test_each_effective_header_rejects_its_own_geometry_mismatch(self):
        for _, _, role in ROLES:
            with self.subTest(role=role), HostFixture() as fixture:
                text = STAMP_SAMPLES["header"].replace("#define VX_CFG_NUM_THREADS 4", "#define VX_CFG_NUM_THREADS 8")
                self.assertNotEqual(text, STAMP_SAMPLES["header"])
                if role.endswith("_model"):
                    text += "#define PERF_ENABLE 1\n"
                fixture.outputs["header-" + role] = text
                report = fixture.run()
                self.assert_rejected(fixture, report)
                self.assertIn("VX_CFG_NUM_THREADS", report["reason"])
                self.assertFalse(any(call["id"].endswith("-run") for call in fixture.calls))

    def test_host_record_cannot_borrow_the_kernel_configuration(self):
        with HostFixture() as fixture:
            fixture.alter_role(3, 1, lambda text: text.replace("-DVX_CFG_XLEN=64", ""))
            report = fixture.run()
            self.assert_rejected(fixture, report)
            self.assertIn("host", report["reason"])
            self.assertFalse(any(call["id"].endswith("-run") for call in fixture.calls))

    def test_fast_math_in_each_original_compiler_role_is_rejected(self):
        for outer, inner, role in ROLES:
            with self.subTest(role=role), HostFixture() as fixture:
                before = fixture.stamps[outer]
                fixture.alter_role(outer, inner, lambda text: " ".join(
                    "-Ofast" if word in ("-O2", "-O3") else word for word in shlex.split(text)))
                self.assertNotEqual(fixture.stamps[outer], before)
                self.assertIn("-Ofast", shlex.split(fixture.stamps[outer].splitlines()[inner]))
                report = fixture.run()
                self.assert_rejected(fixture, report)
                self.assertFalse(any(call["id"].endswith("-run") for call in fixture.calls))

    def test_unretained_header_search_cannot_be_hidden_by_the_macro_only_probe(self):
        for outer, inner, role in ROLES:
            with self.subTest(role=role), HostFixture() as fixture:
                shadow = fixture.paths["source"].parent / "unretained-headers"
                shadow.mkdir()
                (shadow / "VX_config.h").write_text(
                    "#undef VX_CFG_NUM_THREADS\n#define VX_CFG_NUM_THREADS 8\n", encoding="utf-8")
                fixture.alter_role(outer, inner, lambda text: "-I" + str(shadow) + " " + text)
                report = fixture.run()
                self.assert_rejected(fixture, report)
                self.assertFalse(any(call["id"].endswith("-run") for call in fixture.calls))

    def test_binary_or_compiler_record_drift_blocks_the_remaining_cell(self):
        for name in (runner.UNIT, runner.APP + "/kernel.vxbin", "sw/runtime/libvortex-simx.so", runner.STAMPS[-1]):
            with self.subTest(name=name), HostFixture() as fixture:
                def alter(command):
                    if command == "unit-run":
                        path = fixture.build / name
                        path.write_bytes(path.read_bytes() + b"drift\n")
                fixture.after_command = alter
                report = fixture.run()
                self.assert_rejected(fixture, report)
                self.assertNotIn("public-run", [call["id"] for call in fixture.calls])
                self.assertNotEqual(report["artifacts_before"], report["artifacts_after"])

    def test_log_receipt_mismatch_rejects_success_before_output_validation(self):
        for field, value in (("log_sha256", "0" * 64), ("log_size_bytes", 0)):
            with self.subTest(field=field), HostFixture() as fixture:
                fixture.results["unit-run"] = {field: value}
                report = fixture.run()
                self.assert_rejected(fixture, report)
                self.assertNotIn("observations", report["cells"][0])
                self.assertNotIn("public-run", [call["id"] for call in fixture.calls])

    def test_later_log_replacement_or_deletion_invalidates_a_completed_matrix(self):
        for remove in (False, True):
            with self.subTest(remove=remove), HostFixture() as fixture:
                def alter(command):
                    if command == "public-run":
                        path = fixture.paths["output"] / "logs/unit-run.log"
                        path.unlink() if remove else path.write_text(UNIT_OUTPUT + "changed\n", encoding="utf-8")
                fixture.after_command = alter
                report = fixture.run()
                self.assert_rejected(fixture, report)
                self.assertEqual([cell["outcome"] for cell in report["cells"]], ["pass", "pass"])

    def test_retained_inputs_cannot_change_after_the_native_cells(self):
        names = ("source/tests/unittest/simx_completion/main.cpp", "build/sw/VX_config.h",
                 "compiler/" + runner.STAMPS[0], "probe/completion-header.cpp")
        for name in names:
            with self.subTest(name=name), HostFixture() as fixture:
                def alter(command):
                    if command == "public-run":
                        path = fixture.paths["output"] / "artifacts" / name
                        path.write_bytes(path.read_bytes() + b"drift\n")
                fixture.after_command = alter
                report = fixture.run()
                self.assert_rejected(fixture, report)
                self.assertIn("retained evidence changed", report["reason"])

    def test_final_disk_reserve_failure_cannot_leave_full_matrix_pass(self):
        with HostFixture() as fixture:
            def alter(command):
                if command == "public-run":
                    fixture.resources["free_disk_bytes"]["output"] = runner.BUDGET["min_free_bytes"] - 1
            fixture.after_command = alter
            report = fixture.run()
            self.assert_rejected(fixture, report)
            self.assertIn("final disk reserve", report["reason"])
            self.assertEqual([cell["outcome"] for cell in report["cells"]], ["pass", "pass"])


if __name__ == "__main__":
    unittest.main()
