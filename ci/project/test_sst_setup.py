"""Source-level safeguards for the hosted SST integration setup."""

import ast
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class SstSetupTests(unittest.TestCase):
    def test_shell_scripts_are_syntactically_valid(self):
        for path in ("ci/sst_install.sh.in", "ci/regression.sh.in"):
            with self.subTest(path=path):
                subprocess.run(["bash", "-n", str(ROOT / path)], check=True)

    def test_installer_builds_sst_core_without_unused_elements(self):
        script = (ROOT / "ci/sst_install.sh.in").read_text(encoding="utf-8")
        self.assertIn("SST_CORE_1510=", script)
        self.assertIn("make -j$(nproc) all", script)
        self.assertNotIn("SST_ELEMENTS_1510=", script)
        self.assertNotIn("sstelements-15.1.0.tar.gz", script)
        self.assertNotIn("--with-sst-core", script)
        self.assertIn('mkdir -p "$SST_ELEMENTS_HOME/lib/sst-elements-library"', script)

    def test_hostless_runner_uses_only_vortex_component(self):
        path = ROOT / "ci/sst_run_hostless_app.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        component_names = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute):
                continue
            if not isinstance(node.func.value, ast.Name):
                continue
            if node.func.value.id == "sst" and node.func.attr == "Component":
                self.assertGreaterEqual(len(node.args), 2)
                component_names.append(ast.literal_eval(node.args[1]))
        self.assertEqual(["vortex.VortexGPGPU"], component_names)

    def test_regression_registers_locally_built_element(self):
        script = (ROOT / "ci/regression.sh.in").read_text(encoding="utf-8")
        self.assertIn('SST_LIBDIR="$SST_ELEMENTS_HOME/lib/sst-elements-library"', script)
        self.assertIn('cp sim/simx/libvortex.so "$SST_LIBDIR/"', script)
        self.assertIn(
            'command sst --add-lib-path "$SST_LIBDIR" ci/sst_run_hostless_app.py',
            script,
        )

    def test_hostless_dispatch_passes_plugin_path_to_both_kernels(self):
        template = (ROOT / "ci/regression.sh.in").read_text(encoding="utf-8")
        body = template.split("\nsst()\n{\n", 1)[1].split("\n}\n", 1)[0]
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            executable = directory / "bin" / "sst"
            executable.parent.mkdir()
            executable.write_text(
                '#!/bin/sh\n'
                '[ "$1" = "--add-lib-path" ] || exit 21\n'
                '[ "$3" = "ci/sst_run_hostless_app.py" ] || exit 22\n'
                '[ -f "$2/libvortex.so" ] || exit 23\n'
                'printf "%s|%s|%s\\n" "$2" "$VORTEX_TEST_DIR" '
                '"$VORTEX_TEST_KERNEL" >> "$SST_PROBE_LOG"\n',
                encoding="utf-8",
            )
            executable.chmod(0o755)
            home = directory / "tools" / "sst-install" / "sst-elements"
            probe = directory / "sst-invocations.log"
            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{executable.parent}:{env['PATH']}",
                    "SST_ELEMENTS_HOME": str(home),
                    "SST_PROBE_LOG": str(probe),
                }
            )
            run = (
                'set -e\n'
                'make() {\n'
                '  if [ "$*" = "-C sim/simx USE_SST=1" ]; then\n'
                '    mkdir -p sim/simx\n'
                '    printf plugin > sim/simx/libvortex.so\n'
                '  fi\n'
                '}\n'
                f'sst()\n{{\n{body}\n}}\n'
                'sst\n'
            )
            subprocess.run(["bash", "-c", run], cwd=directory, env=env, check=True)
            libdir = home / "lib" / "sst-elements-library"
            self.assertEqual("plugin", (libdir / "libvortex.so").read_text())
            self.assertEqual(
                [
                    f"{libdir}|{directory}/tests/kernel/hello|hello.vxbin",
                    f"{libdir}|{directory}/tests/kernel/fibonacci|fibonacci.vxbin",
                ],
                probe.read_text(encoding="utf-8").splitlines(),
            )


if __name__ == "__main__":
    unittest.main()
