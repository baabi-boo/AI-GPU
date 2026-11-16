# SPDX-License-Identifier: Apache-2.0
"""Compare compiler-record decisions with a real host preprocessor's macros."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from compiler_records import validate_records


BUILD = "/review/oracle/build64"
CONFIGS = (
    "-DVX_CFG_NUM_CLUSTERS=1",
    "-DVX_CFG_NUM_CORES=1",
    "-DVX_CFG_NUM_WARPS=4",
    "-DVX_CFG_NUM_THREADS=4",
    "-DVX_CFG_ISSUE_WIDTH=1",
    "-DVX_CFG_FPU_TYPE_STD",
)
FLAGS = (*CONFIGS, "-DVX_CFG_XLEN=64", "-DVX_CFG_XLEN_64")
EXPECTED = {
    "VX_CFG_NUM_CLUSTERS": "1", "VX_CFG_NUM_CORES": "1",
    "VX_CFG_NUM_WARPS": "4", "VX_CFG_NUM_THREADS": "4",
    "VX_CFG_ISSUE_WIDTH": "1", "VX_CFG_FPU_TYPE_STD": "1",
    "VX_CFG_XLEN": "64", "VX_CFG_XLEN_64": "1",
}
GLOB_SCRIPT = 'set -- -I* -DVX_CFG_NUM_CLUSTERS=1\nprintf \'%s\\n\' "$@"\n'


def macro_values(output):
    values = {}
    for line in output.splitlines():
        if line.startswith("#define "):
            parts = line.split(None, 2)
            if len(parts) == 3:
                values[parts[1]] = parts[2]
    return values


def records(*, runtime=FLAGS, kernel=FLAGS, host=FLAGS):
    return (
        " ".join(runtime) + "\n",
        "-march=rv64imafd -mabi=lp64d " + " ".join(kernel) + "\n"
        + " ".join(host) + "\n-L" + BUILD + "/sw/runtime -lvortex\n",
    )


class CompilerPreprocessorOracleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.environment = {"PATH": os.environ.get("PATH", os.defpath), "LC_ALL": "C"}
        attempted, seen = [], set()
        for name in ("cc", "gcc", "clang"):
            executable = shutil.which(name)
            if executable is None or Path(executable).resolve() in seen:
                continue
            seen.add(Path(executable).resolve())
            attempted.append(name)
            try:
                probe = subprocess.run(
                    [executable, "-E", "-dM", "-x", "c", "-DAI_GPU_ORACLE_PROBE=37", "-"],
                    input="", capture_output=True, text=True, timeout=5,
                    env=cls.environment, check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                continue
            if (probe.returncode == 0 and len(probe.stdout) <= 256 * 1024
                    and macro_values(probe.stdout).get("AI_GPU_ORACLE_PROBE") == "37"):
                cls.compiler = executable
                return
        raise unittest.SkipTest(
            "No compatible cc/gcc/clang preprocessor for the independent macro oracle; "
            "attempted: " + (", ".join(attempted) or "none available"))

    def preprocess(self, flags, *, cwd=None):
        result = subprocess.run(
            [self.compiler, "-E", "-dM", "-x", "c", *flags, "-"],
            input="", capture_output=True, text=True, timeout=5,
            env=self.environment, cwd=cwd, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLessEqual(len(result.stdout), 256 * 1024)
        return macro_values(result.stdout)

    def validate(self, **compiler_records):
        runtime, demo = records(**compiler_records)
        return validate_records(runtime, demo, BUILD, CONFIGS)

    def assert_missing_cluster(self, observed):
        self.assertNotIn("VX_CFG_NUM_CLUSTERS", observed)
        for name, value in EXPECTED.items():
            if name != "VX_CFG_NUM_CLUSTERS":
                self.assertEqual(observed.get(name), value)

    def test_direct_definitions_match_real_preprocessor_and_validate(self):
        observed = self.preprocess(FLAGS)
        self.assertEqual({name: observed.get(name) for name in EXPECTED}, EXPECTED)
        self.assertIsNone(self.validate())

    def test_include_operand_consumes_a_required_define_in_every_role(self):
        flags = ("-I", *FLAGS)
        self.assert_missing_cluster(self.preprocess(flags))
        for role in ("runtime", "kernel", "host"):
            with self.subTest(role=role), self.assertRaises(ValueError):
                self.validate(**{role: flags})

    def test_real_pathname_expansion_changes_include_argument_boundaries(self):
        shell = shutil.which("sh")
        self.assertIsNotNone(shell, "The Linux compiler oracle requires a POSIX shell")
        with tempfile.TemporaryDirectory(prefix="ai-gpu-compiler-oracle-") as temporary:
            (Path(temporary) / "-I").touch()
            result = subprocess.run(
                [shell, "-c", GLOB_SCRIPT], cwd=temporary, env=self.environment,
                capture_output=True, text=True, timeout=5, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            expanded = result.stdout.splitlines()
            self.assertEqual(expanded, ["-I", "-DVX_CFG_NUM_CLUSTERS=1"])
            self.assert_missing_cluster(self.preprocess((*expanded, *FLAGS[1:]), cwd=temporary))
        for role in ("runtime", "kernel", "host"):
            with self.subTest(role=role), self.assertRaises(ValueError):
                self.validate(**{role: ("-I*", *FLAGS)})

    def test_combining_incomplete_records_does_not_prove_either_invocation(self):
        kernel = tuple(flag for flag in FLAGS if flag != "-DVX_CFG_NUM_CLUSTERS=1")
        host = tuple(flag for flag in FLAGS if flag != "-DVX_CFG_NUM_CORES=1")
        self.assertNotIn("VX_CFG_NUM_CLUSTERS", self.preprocess(kernel))
        self.assertNotIn("VX_CFG_NUM_CORES", self.preprocess(host))
        combined = self.preprocess((*kernel, *host))
        self.assertEqual({name: combined.get(name) for name in EXPECTED}, EXPECTED)
        with self.assertRaises(ValueError):
            self.validate(kernel=kernel, host=host)
        with self.assertRaises(ValueError):
            self.validate(kernel=kernel)
        with self.assertRaises(ValueError):
            self.validate(host=host)


if __name__ == "__main__":
    unittest.main()
