# SPDX-License-Identifier: Apache-2.0
"""Exercise hardware-header input selection and real configure failure exits."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
INPUTS = ("VX_config", "VX_types", "vortex_opae")


class ConfigureHeaderTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="configure-headers-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        for name in ("configure", "VERSION", "ci/gen_config.py", "pyproject.toml",
                     "profiles/p02-tfr.json", *(name + ".toml" for name in INPUTS)):
            target = self.source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, target)
        self.env = {"PATH": str(Path(sys.executable).parent) + os.pathsep + os.defpath,
                    "LC_ALL": "C", "PYTHONDONTWRITEBYTECODE": "1"}

    def configure(self, name, *, profile=""):
        build = self.root / name
        build.mkdir(exist_ok=True)
        result = subprocess.run(
            [str(self.source / "configure"), "--xlen=64", "--profile=" + profile,
             "--osversion=ubuntu/focal", "--tooldir=" + str(self.root / "unused-tools")],
            cwd=build, env=self.env, text=True, capture_output=True, timeout=20,
        )
        return build, result

    def inject_failure(self, format_name):
        generator = self.source / "ci/gen_config.py"
        generator.rename(generator.with_name("gen_config_original.py"))
        generator.write_text(
            "#!/usr/bin/env python3\n"
            "from pathlib import Path\nimport runpy\nimport sys\n"
            "if '--output' in sys.argv and sys.argv[sys.argv.index('--format') + 1] == "
            + repr(format_name) + ":\n"
            "    print('injected hardware header failure', file=sys.stderr)\n"
            "    raise SystemExit(42)\n"
            "runpy.run_path(str(Path(__file__).with_name('gen_config_original.py')), run_name='__main__')\n",
            encoding="utf-8",
        )
        generator.chmod(0o755)
        latest = max(path.stat().st_mtime_ns for path in self.root.rglob("*") if path.is_file())
        os.utime(generator, ns=(latest + 2_000_000_000, latest + 2_000_000_000))

    def test_only_hardware_inputs_generate_headers_with_packaging_metadata_present(self):
        (self.source / "unrelated.toml").write_text("deliberately invalid TOML\n")
        build, result = self.configure("native-profile", profile="p02-tfr")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual({path.name for path in (build / "hw").glob("*.vh")},
                         {name + ".vh" for name in INPUTS})
        self.assertEqual({path.name for path in (build / "sw").glob("*.h")},
                         {name + ".h" for name in INPUTS})
        for path in (*list((build / "hw").glob("*.vh")), *list((build / "sw").glob("*.h"))):
            self.assertGreater(path.stat().st_size, 0)

    def test_each_missing_hardware_input_fails_without_claiming_success(self):
        for name in INPUTS:
            with self.subTest(input=name):
                path = self.source / (name + ".toml")
                original = path.read_bytes()
                path.unlink()
                try:
                    _, result = self.configure("missing-" + name)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertIn("Missing hardware configuration: " + str(path), result.stderr)
                finally:
                    path.write_bytes(original)

    def test_verilog_generator_error_is_the_configure_exit_status(self):
        self.inject_failure("verilog")
        build, result = self.configure("failed-verilog")
        self.assertEqual(result.returncode, 42, result.stderr)
        self.assertIn("injected hardware header failure", result.stderr)
        self.assertFalse((build / "sw/VX_config.h").exists())

    def test_cpp_generator_error_stops_before_later_inputs(self):
        self.inject_failure("cpp")
        build, result = self.configure("failed-cpp")
        self.assertEqual(result.returncode, 42, result.stderr)
        self.assertTrue((build / "hw/VX_config.vh").is_file())
        self.assertFalse((build / "hw/VX_types.vh").exists())

    def test_failed_reconfiguration_cannot_succeed_with_old_headers_present(self):
        build, first = self.configure("reconfigure")
        self.assertEqual(first.returncode, 0, first.stderr)
        old = (build / "sw/VX_config.h").read_bytes()
        self.inject_failure("cpp")
        _, result = self.configure("reconfigure")
        self.assertEqual(result.returncode, 42, result.stderr)
        self.assertEqual((build / "sw/VX_config.h").read_bytes(), old)


if __name__ == "__main__":
    unittest.main()
