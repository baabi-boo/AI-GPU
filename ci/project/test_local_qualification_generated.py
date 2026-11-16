# Licensed under the Apache License, Version 2.0.
"""Real configure and intercepted application recipes, without GPU tools or builds."""

import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import local_qualification as runner
import local_qualification_inventory as inventory
from local_qualification_cases import CORE_IDS, TENSOR_IDS, select_cases
import test_local_qualification_runner as runner_fixtures


REPOSITORY = Path(__file__).resolve().parents[2]
EXPECTED_RECIPES = {
    "sim/xrtsim/Makefile": "sim/xrtsim/Makefile",
    "sim/xrtsim/verilator.vlt": "sim/xrtsim/verilator.vlt.in",
    "sw/runtime/xrt/Makefile": "sw/runtime/xrt/Makefile",
    "sw/runtime/xrt/xrt.ini": "sw/runtime/xrt/xrt.ini.in",
    "hw/unittest/common.mk": "hw/unittest/common.mk",
    "hw/unittest/verilator.vlt": "hw/unittest/verilator.vlt.in",
}
SOURCE_HOOK = "sw/runtime/xrt/xsim.tcl"
CAPTURE_SUBMAKE = """import json
import os
from pathlib import Path
import sys
Path(os.environ["QUALIFICATION_CAPTURE"]).write_text(json.dumps({
    "argv": sys.argv[1:], "cwd": os.getcwd(),
    "configs": os.environ.get("CONFIGS"), "target": os.environ.get("TARGET"),
}))
"""


def identity(root, relative):
    contents = (root / relative).read_bytes()
    return {"path": relative, "size_bytes": len(contents),
            "sha256": hashlib.sha256(contents).hexdigest()}


class RealConfigureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix="local-qualification-generated-")
        cls.addClassCleanup(temporary.cleanup)
        cls.base = Path(temporary.name).resolve()
        cls.build = cls.base / "build64"
        cls.tools = cls.base / "empty-tools"
        cls.build.mkdir()
        cls.tools.mkdir()
        cls.environment = {
            "PATH": str(Path(sys.executable).parent) + os.pathsep + os.defpath,
            "HOME": str(cls.base), "LANG": "C", "LC_ALL": "C",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        subprocess.run(
            [str(REPOSITORY / "configure"), "--xlen=64", "--osversion=ubuntu/focal",
             "--tooldir=" + str(cls.tools)], cwd=cls.build, env=cls.environment,
            check=True, capture_output=True, text=True, timeout=15,
        )

    def test_actual_generated_core_and_tensor_inventories_retain_the_source_hook(self):
        self.assertFalse(self.build.is_relative_to(REPOSITORY))
        self.assertEqual(list(self.tools.iterdir()), [])
        self.assertFalse((self.build / SOURCE_HOOK).exists())
        self.assertIn("user_pre_sim_script=" + str(REPOSITORY / SOURCE_HOOK),
                      (self.build / "sw/runtime/xrt/xrt.ini").read_text())
        for selected in (CORE_IDS, (TENSOR_IDS[0],), (TENSOR_IDS[1],)):
            with self.subTest(selected=selected):
                cases = select_cases(selected)
                report = inventory.collect_generated(self.build, REPOSITORY, cases)
                self.assertEqual(report["outcome"], "pass", report["blockers"])
                self.assertTrue(report["baseline"]["identity_matches"])
                generated = {item["path"]: item for item in report["files"]}
                sources = {item["path"]: item for item in report["source_files"]}
                expected = dict(EXPECTED_RECIPES)
                for case in cases:
                    prefix = "tests/regression/" if case["kind"] == "app" else "hw/unittest/"
                    relative = prefix + case["app"] + "/Makefile"
                    expected[relative] = relative
                for destination, origin in expected.items():
                    contents = (REPOSITORY / origin).read_bytes()
                    if origin.endswith(".in"):
                        contents = contents.replace(b"@VORTEX_HOME@", str(REPOSITORY).encode())
                    self.assertEqual((self.build / destination).read_bytes(), contents, destination)
                    self.assertEqual(generated[destination], identity(self.build, destination))
                    self.assertEqual(sources[origin], identity(REPOSITORY, origin))
                self.assertNotIn(SOURCE_HOOK, generated)
                self.assertEqual(sources[SOURCE_HOOK], identity(REPOSITORY, SOURCE_HOOK))

    def test_application_runtime_target_passes_canonical_destination_and_fixed_configs(self):
        capture_script = self.base / "capture_submake.py"
        capture_script.write_text(CAPTURE_SUBMAKE)
        capture = self.base / "submake.json"
        intercepted_make = shlex.join([sys.executable, "-I", "-S", "-B", str(capture_script)])
        for case in select_cases(["demo", *TENSOR_IDS]):
            with self.subTest(case=case["id"]):
                if capture.exists():
                    capture.unlink()
                # Only the app Makefile is parsed; the recursive runtime make is intercepted.
                subprocess.run(
                    ["make", "--no-print-directory", "-j1", "-C", "tests/regression/" + case["app"],
                     "runtime-xrt", "TARGET=xrtsim", "MAKE=" + intercepted_make],
                    cwd=self.build, env={**self.environment, "CONFIGS": case["configs"],
                                         "QUALIFICATION_CAPTURE": str(capture)},
                    check=True, capture_output=True, text=True, timeout=5,
                )
                observed = json.loads(capture.read_text())
                self.assertEqual(observed, {
                    "argv": ["-C", str(self.build / "sw/runtime/xrt"),
                             "DESTDIR=" + str(self.build / "sw/runtime")],
                    "cwd": str(self.build / "tests/regression" / case["app"]),
                    "configs": case["configs"], "target": "xrtsim",
                })
                self.assertFalse((self.build / "tests/regression" / case["app"] / "config.stamp").exists())
        self.assertEqual(list(self.tools.iterdir()), [])
        self.assertFalse((self.build / "sw/runtime/xrtsim_config.stamp").exists())
        self.assertFalse((self.build / "sim/xrtsim/obj_dir").exists())


class RuntimePreparationTests(unittest.TestCase):
    def test_runner_prepares_through_the_same_application_target_before_build_and_launch(self):
        with tempfile.TemporaryDirectory(prefix="local-qualification-runtime-selection-") as temporary:
            fixture = runner_fixtures.RunnerFixture(Path(temporary).resolve())
            fixture.args.case = ["demo"]
            capacity = type(shutil.disk_usage(fixture.base))(64 * runner.GIB,
                                                          runner.GIB, 63 * runner.GIB)
            with mock.patch.dict(os.environ, fixture.environment, clear=True), \
                    mock.patch.object(runner, "HERE", fixture.helpers), \
                    mock.patch.object(inventory, "HERE", fixture.helpers), \
                    mock.patch.object(runner.shutil, "disk_usage", return_value=capacity), \
                    mock.patch.object(runner, "run_bounded", side_effect=fixture.command):
                plan = runner.plan_run(fixture.args, fixture.paths)
                self.assertEqual(plan["outcome"], "pass", plan["blockers"])
                report = runner.execute_run(fixture.args, plan, fixture.paths)
            self.assertEqual(report["outcome"], "pass", report.get("reason"))
            self.assertEqual([call["id"] for call in fixture.calls], [
                "scalar-configure", "scalar-kernel", "scalar-stub", "demo-runtime",
                "demo-build", "demo-run",
            ])
            calls = {call["id"]: call for call in fixture.calls}
            self.assertEqual(calls["demo-runtime"]["argv"], [
                "make", "-j1", "-C", "tests/regression/demo", "runtime-xrt", "TARGET=xrtsim",
            ])
            self.assertEqual(calls["demo-build"]["argv"], [
                "make", "-j1", "-C", "tests/regression/demo", "TARGET=xrtsim",
            ])
            self.assertEqual(calls["demo-run"]["argv"], [
                "./ci/blackbox.sh", "--driver=xrt", "--target=xrtsim", "--app=demo", "--args=-n1",
            ])
            for name in ("demo-runtime", "demo-build", "demo-run"):
                self.assertEqual(calls[name]["cwd"], fixture.paths["build"] / "scalar")
                self.assertEqual(calls[name]["environment"]["CONFIGS"], select_cases(["demo"])[0]["configs"])
            self.assertTrue(any(item["source"]["path"] == SOURCE_HOOK
                                for item in report["snapshots"]))


if __name__ == "__main__":
    unittest.main()
