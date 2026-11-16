# SPDX-License-Identifier: Apache-2.0
"""Exercise the real CLI with synthetic resources, never GPU/vendor evidence."""

import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import unittest

from hwemu_fixture import HwemuFixture


PROJECT = Path(__file__).resolve().parent
GIB = 1024 ** 3
SYNTHETIC_RESOURCE_BOOTSTRAP = r"""
import sys
from unittest.mock import patch

sys.path.insert(0, sys.argv[1])
import hwemu
import hwemu_plan

def synthetic_adequate_resources(directories):
    return {
        "test_only": "synthetic resources; not a host measurement",
        "free_disk_bytes": {label: 32 * 1024 ** 3 for label in directories},
        "available_memory_bytes": 8 * 1024 ** 3,
        "cgroup_limit_bytes": None,
    }

sys.argv = ["hwemu.py", "plan", sys.argv[2], "--json"]
with patch.object(hwemu_plan, "_sample_resources",
                  side_effect=synthetic_adequate_resources):
    raise SystemExit(hwemu.main())
"""


class HwemuCliIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = HwemuFixture()
        self.addCleanup(self.fixture.close)
        self.markers = [self.fixture.base / "vendor-was-executed",
                        self.fixture.base / "setup-was-executed"]
        paths = (
            [Path(self.fixture.manifest["files"][role]["path"])
             for role in ("vpp", "vivado", "emconfigutil", "platforminfo")],
            [self.fixture.vendor / "vitis/settings64.sh",
             self.fixture.vendor / "vivado/settings64.sh",
             self.fixture.vendor / "xrt/setup.sh"],
        )
        for marker, group in zip(self.markers, paths):
            for path in group:
                path.write_text("#!/bin/sh\nprintf 'unexpected execution' > "
                                + shlex.quote(str(marker)) + "\nexit 97\n",
                                encoding="utf-8")
                path.chmod(0o755)
        self.fixture.refresh()
        self.bytecode = self.fixture.base / "python-bytecode"
        self.bytecode.mkdir()
        (self.bytecode / "retained.pyc").write_bytes(b"synthetic retained bytecode\n")

    def snapshot(self):
        result = {}
        for path in self.fixture.base.rglob("*"):
            metadata = path.lstat()
            if path.is_file():
                result[str(path.relative_to(self.fixture.base))] = (
                    metadata.st_mode, metadata.st_size, metadata.st_mtime_ns,
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                )
            elif path.is_dir():
                result[str(path.relative_to(self.fixture.base))] = (metadata.st_mode,)
            else:
                self.fail("unexpected special file in synthetic CLI fixture")
        return result

    def run_cli(self):
        before = self.snapshot()
        environment = {
            "PATH": os.pathsep.join((str(self.fixture.vendor / "vitis/bin"),
                                     str(self.fixture.vendor / "vivado/bin"), os.defpath)),
            "LANG": "C", "LC_ALL": "C", "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPYCACHEPREFIX": str(self.bytecode),
            "XILINX_VITIS": str(self.fixture.vendor / "vitis"),
            "XILINX_VIVADO": str(self.fixture.vendor / "vivado"),
            "XILINX_XRT": str(self.fixture.vendor / "xrt"),
        }
        result = subprocess.run(
            [sys.executable, "-c", SYNTHETIC_RESOURCE_BOOTSTRAP,
             str(PROJECT), str(self.fixture.manifest_path)],
            cwd=self.fixture.base, env=environment, capture_output=True,
            text=True, check=False, timeout=20,
        )
        self.assertEqual(self.snapshot(), before, "CLI changed inputs or bytecode")
        for marker in self.markers:
            self.assertFalse(marker.exists(), "CLI executed a vendor/setup script")
        self.assertEqual(result.stderr, "")
        observed = json.loads(result.stdout)
        for key in ("execution_performed", "phase_complete", "launch_ready",
                    "vendor_qualification_verified"):
            self.assertIs(observed[key], False)
        self.assertEqual(observed["vendor_qualification"], "unverified")
        self.assertEqual(observed["acceptance_id"], "P01-A03")
        self.assertEqual(observed["acceptance_outcome"], "blocked")
        return result.returncode, observed

    def test_real_cli_plans_complete_fixture_with_only_synthetic_resources(self):
        code, observed = self.run_cli()
        self.assertEqual(code, 0, observed)
        self.assertEqual(observed["outcome"], "planned")
        self.assertIs(observed["input_consistency_verified"], True)
        self.assertEqual(observed["blockers"], [])
        self.assertEqual(observed["source"], self.fixture.source_observation)
        self.assertGreater(observed["checked_input_count"],
                           len(self.fixture.manifest["files"])
                           + len(self.fixture.manifest["generated"]))
        self.assertEqual(set(observed["resources"]), {"initial", "final"})
        for sample in observed["resources"].values():
            self.assertEqual(sample["test_only"], "synthetic resources; not a host measurement")
            self.assertTrue(sample["free_disk_bytes"])
            self.assertEqual(set(sample["free_disk_bytes"].values()), {32 * GIB})
            self.assertEqual(sample["available_memory_bytes"], 8 * GIB)
            self.assertIsNone(sample["cgroup_limit_bytes"])
        candidate = observed["candidate"]
        self.assertEqual(candidate["cwd"], str(self.fixture.build))
        self.assertEqual(candidate["argv"], ["./ci/blackbox.sh", "--driver=xrt",
                                            "--target=hw_emu", "--app=demo", "--args=-n1"])
        self.assertIs(candidate["inherit_environment"], False)
        self.assertIs(candidate["supervision_required"], True)
        self.assertEqual(candidate["budget"], self.fixture.manifest["budget"])
        self.assertEqual(candidate["budget"]["min_free_bytes"], 15 * GIB)

    def test_real_cli_blocks_same_size_artifact_corruption(self):
        path = Path(self.fixture.manifest["files"]["xclbin"]["path"])
        original = path.read_bytes()
        path.write_bytes(bytes((original[0] ^ 1,)) + original[1:])
        code, observed = self.run_cli()
        self.assertEqual(code, 1, observed)
        self.assertEqual(observed["outcome"], "blocked")
        self.assertIs(observed["input_consistency_verified"], False)
        self.assertIsNone(observed["candidate"])
        self.assertEqual(observed["blockers"], [
            "declared xclbin input is missing, unsafe, changed, or mismatched",
        ])

    def test_real_cli_blocks_missing_required_generated_input(self):
        (self.fixture.build / "sw/runtime/xrt/xrt.ini").unlink()
        code, observed = self.run_cli()
        self.assertEqual(code, 1, observed)
        self.assertEqual(observed["outcome"], "blocked")
        self.assertIs(observed["input_consistency_verified"], False)
        self.assertIsNone(observed["candidate"])
        self.assertEqual(observed["blockers"], [
            "generated sw/runtime/xrt/xrt.ini identity is missing, unsafe, changed, or mismatched",
        ])


if __name__ == "__main__":
    unittest.main()
