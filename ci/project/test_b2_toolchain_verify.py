#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for ci/project/b2_toolchain_verify.py."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

HERE = str(Path(__file__).resolve().parent)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import b2_toolchain_verify as verify  # noqa: E402


class TestParsers(unittest.TestCase):
    def test_parse_ldd_output_detects_missing_libtinfo(self):
        sample_bad = (
            "\tlinux-vdso.so.1 (0x00007ffd)\n"
            "\tlibtinfo.so.5 => not found\n"
            "\tlibstdc++.so.6 => /lib/x86_64-linux-gnu/libstdc++.so.6 (0x00007f00)\n"
            "\tlibc.so.6 => /lib/x86_64-linux-gnu/libc.so.6 (0x00007f00)\n"
        )
        parsed = verify.parse_ldd_output(sample_bad)
        self.assertFalse(parsed["ok"])
        self.assertEqual(parsed["missing_libs"], ["libtinfo.so.5"])
        self.assertEqual(parsed["resolved_count"], 2)

        sample_ok = (
            "\tlinux-vdso.so.1 (0x00007ffd)\n"
            "\tlibc.so.6 => /lib/x86_64-linux-gnu/libc.so.6 (0x00007f00)\n"
        )
        parsed_ok = verify.parse_ldd_output(sample_ok)
        self.assertTrue(parsed_ok["ok"])
        self.assertEqual(parsed_ok["missing_libs"], [])
        self.assertEqual(parsed_ok["resolved_count"], 1)

        static_res = verify.parse_ldd_output("\tnot a dynamic executable\n")
        self.assertTrue(static_res["ok"])
        self.assertTrue(static_res["not_dynamic"])

    def test_parse_tool_versions_and_ccache_and_docker_digest(self):
        self.assertEqual(verify.parse_tool_version("verilator", "Verilator 5.050 2026-01-01"), "Verilator 5.050")
        self.assertEqual(verify.parse_tool_version("yosys", "Yosys 0.69 (git sha1 abc123)"), "Yosys 0.69")
        self.assertEqual(verify.parse_tool_version("z3", "Z3 version 4.8.12 - 64 bit"), "Z3 4.8.12")
        self.assertEqual(verify.parse_tool_version("sta", "3.1.0\n"), "3.1.0")
        self.assertIn("24.0.0", verify.parse_tool_version("circt-verilog", "LLVM version 24.0.0git"))

        ccache_out = (
            "Cacheable calls:   12 /  15 (80.00%)\n"
            "  Hits:            12 /  15 (80.00%)\n"
            "  Misses:           3 /  15 (20.00%)\n"
            "Cache size (GiB):  0.42 / 2.00 (21.00%)\n"
            "max_size = 2.0G\n"
        )
        stats = verify.parse_ccache_stats(ccache_out)
        self.assertIn("0.42", stats["cache_size"])
        self.assertEqual(stats["max_size"], "2.0G")

        inspect_json = json.dumps([
            {"Id": "sha256:abc", "RepoDigests": ["openroad/orfs@sha256:deadbeef"]}
        ])
        self.assertEqual(verify.parse_docker_image_digest(inspect_json), "openroad/orfs@sha256:deadbeef")


class TestToolAndPythonProbes(unittest.TestCase):
    def test_probe_binary_tool_catches_missing_shared_library(self):
        with tempfile.TemporaryDirectory() as tmp:
            tooldir = Path(tmp)
            yosys_bin = tooldir / "yosys/bin/yosys"
            yosys_bin.parent.mkdir(parents=True, exist_ok=True)
            yosys_bin.write_bytes(b"\x7fELFdummy")
            os.chmod(yosys_bin, 0o755)

            def fake_runner(argv, **kwargs):
                if argv[0] == "ldd":
                    return verify.CommandResult(0, "\tlibtinfo.so.5 => not found\n", "")
                return verify.CommandResult(127, "", "error while loading shared libraries: libtinfo.so.5")

            with mock.patch("shutil.which", side_effect=lambda x: "/usr/bin/ldd" if x == "ldd" else None):
                res = verify.probe_binary_tool("yosys", tooldir, runner=fake_runner)

            self.assertTrue(res["found"])
            self.assertFalse(res["ok"])
            self.assertEqual(res["ldd"]["missing_libs"], ["libtinfo.so.5"])
            self.assertIn("libtinfo.so.5", res["error"])

    def test_probe_python_environment_catches_pipx_trap(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_pipx = Path(tmp) / "pipx/venvs/pytest/bin"
            fake_pipx.mkdir(parents=True, exist_ok=True)
            pytest_bin = fake_pipx / "pytest"
            pytest_bin.write_text("#!/opt/pipx/venvs/pytest/bin/python\n", encoding="utf-8")
            os.chmod(pytest_bin, 0o755)

            pkg_payload = json.dumps({
                pkg: {"installed": True, "version": "1.0.0", "file": f"/pyenv/{pkg}.py"}
                for pkg, _ in verify.REQUIRED_PYTHON_PACKAGES
            })

            def fake_runner(argv, **kwargs):
                if argv[0] == sys.executable:
                    return verify.CommandResult(0, pkg_payload + "\n", "")
                if argv[0] == str(pytest_bin):
                    return verify.CommandResult(0, "pytest 8.3.0\n", "")
                if argv[0] == "/opt/pipx/venvs/pytest/bin/python":
                    return verify.CommandResult(1, "", "ModuleNotFoundError: No module named 'torch'")
                return verify.CommandResult(0, "", "")

            with mock.patch("shutil.which", return_value=str(pytest_bin)):
                py_res = verify.probe_python_environment(runner=fake_runner)

            self.assertTrue(py_res["pytest_in_pipx"])
            self.assertTrue(py_res["pytest_isolated_missing_torch_numpy"])
            self.assertTrue(py_res["pipx_trap_detected"])
            self.assertFalse(py_res["ok"])
            self.assertIn("-m pytest", py_res["recommendation"])

    def test_probe_docker_orfs_mocked_pass_and_skip(self):
        skipped = verify.probe_docker_orfs(skip_docker=True)
        self.assertTrue(skipped["skipped"])
        self.assertTrue(skipped["ok"])

        seen_cmds: list[list[str]] = []

        def fake_docker(argv, **kwargs):
            seen_cmds.append(list(argv))
            if "info" in argv:
                return verify.CommandResult(0, "29.10.0\n", "")
            if "inspect" in argv:
                return verify.CommandResult(
                    0,
                    json.dumps([{"Id": "sha256:123", "RepoDigests": ["openroad/orfs@sha256:cafebabe"]}]),
                    "",
                )
            if "run" in argv:
                return verify.CommandResult(0, "24Q3-1234-gabcdef\nKLayout 0.29.8\n", "")
            return verify.CommandResult(1, "", "unexpected")

        with mock.patch("shutil.which", return_value="/usr/bin/docker"):
            ok_res = verify.probe_docker_orfs("openroad/orfs:latest", runner=fake_docker)

        self.assertTrue(ok_res["ok"])
        self.assertEqual(ok_res["image_digest"], "openroad/orfs@sha256:cafebabe")
        self.assertIn("24Q3", ok_res["openroad_version"])
        self.assertIn("0.29.8", ok_res["klayout_version"])
        run_cmd = [c for c in seen_cmds if "run" in c][0]
        self.assertIn("source /OpenROAD-flow-scripts/env.sh", run_cmd[-1])
        self.assertIn("klayout.db", run_cmd[-1])

        def fake_orfs_env_klayout_db(argv, **kwargs):
            if "info" in argv:
                return verify.CommandResult(0, "29.10.0\n", "")
            if "inspect" in argv:
                return verify.CommandResult(
                    0,
                    json.dumps([{"Id": "sha256:456", "RepoDigests": ["openroad/orfs@sha256:b7be8a1b"]}]),
                    "",
                )
            if "run" in argv:
                return verify.CommandResult(0, "unknown \nklayout 0.30.13\n", "")
            return verify.CommandResult(1, "", "unexpected")

        with mock.patch("shutil.which", return_value="/usr/bin/docker"):
            orfs_res = verify.probe_docker_orfs("openroad/orfs:latest", runner=fake_orfs_env_klayout_db)

        self.assertTrue(orfs_res["ok"], orfs_res)
        self.assertEqual(orfs_res["openroad_version"], "unknown")
        self.assertEqual(orfs_res["klayout_version"], "klayout 0.30.13")

    def test_probe_build_dir_sw_runtime_and_legacy_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            # Standard Vortex out-of-tree layout: <build_dir>/sw/runtime/
            b_sw = root / "build64_b2"
            (b_sw / "sw/runtime").mkdir(parents=True, exist_ok=True)
            (b_sw / "sw/VX_config.h").write_text("// ok\n", encoding="utf-8")
            (b_sw / "sw/runtime/libvortex-simx.so").write_bytes(b"")
            (b_sw / "sw/runtime/libvortex-rtlsim.so").write_bytes(b"")
            res_sw = verify.probe_build_dir(b_sw)
            self.assertTrue(res_sw["exists"])
            self.assertTrue(res_sw["configured"])
            self.assertTrue(res_sw["simx_built"])
            self.assertTrue(res_sw["rtlsim_built"])

            # Alternate library names under sw/runtime/ (libsimx.so / librtlsim.so)
            b_alt = root / "build_alt"
            (b_alt / "sw/runtime").mkdir(parents=True, exist_ok=True)
            (b_alt / "hw").mkdir(parents=True, exist_ok=True)
            (b_alt / "hw/VX_config.vh").write_text("// ok\n", encoding="utf-8")
            (b_alt / "sw/runtime/libsimx.so").write_bytes(b"")
            (b_alt / "sw/runtime/librtlsim.so").write_bytes(b"")
            res_alt = verify.probe_build_dir(b_alt)
            self.assertTrue(res_alt["configured"])
            self.assertTrue(res_alt["simx_built"])
            self.assertTrue(res_alt["rtlsim_built"])

            # Legacy <build_dir>/runtime/ fallback
            b_legacy = root / "build_legacy"
            (b_legacy / "runtime").mkdir(parents=True, exist_ok=True)
            (b_legacy / "sw").mkdir(parents=True, exist_ok=True)
            (b_legacy / "sw/VX_config.h").write_text("// ok\n", encoding="utf-8")
            (b_legacy / "runtime/libvortex-simx.so").write_bytes(b"")
            (b_legacy / "runtime/libvortex-rtlsim.so").write_bytes(b"")
            res_legacy = verify.probe_build_dir(b_legacy)
            self.assertTrue(res_legacy["configured"])
            self.assertTrue(res_legacy["simx_built"])
            self.assertTrue(res_legacy["rtlsim_built"])


class TestDiskRamThresholdsAndCli(unittest.TestCase):
    def test_disk_and_ram_thresholds(self):
        with tempfile.TemporaryDirectory() as tmp:
            meminfo = Path(tmp) / "meminfo"
            meminfo.write_text(
                "MemTotal:        8150016 kB\n"
                "MemAvailable:    7488332 kB\n"
                "SwapTotal:       8388608 kB\n"
                "SwapFree:        8388608 kB\n",
                encoding="utf-8",
            )
            gib = 1024 ** 3
            # 15 GiB free -> warning (<20), not error (>=10)
            warn_res = verify.probe_disk_and_ram(
                Path(tmp),
                warn_disk_gib=20.0,
                min_disk_gib=10.0,
                min_ram_gib=4.0,
                meminfo_path=meminfo,
                disk_usage_fn=lambda _: (100 * gib, 85 * gib, 15 * gib),
            )
            self.assertTrue(warn_res["ok"])
            self.assertEqual(len(warn_res["warnings"]), 1)
            self.assertEqual(warn_res["errors"], [])

            # 8 GiB free -> hard fail (<10)
            fail_res = verify.probe_disk_and_ram(
                Path(tmp),
                warn_disk_gib=20.0,
                min_disk_gib=10.0,
                min_ram_gib=4.0,
                meminfo_path=meminfo,
                disk_usage_fn=lambda _: (100 * gib, 92 * gib, 8 * gib),
            )
            self.assertFalse(fail_res["ok"])
            self.assertTrue(any("hard minimum" in e for e in fail_res["errors"]))

    def test_full_run_verification_and_cli_json_markdown_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            tooldir = tmp_path / "tools"
            build_dir = tmp_path / "build64_b2"
            (build_dir / "sw").mkdir(parents=True, exist_ok=True)
            (build_dir / "sw/VX_config.h").write_text("// ok\n", encoding="utf-8")

            for rel in verify.VORTEX_TOOL_CANDIDATES.values():
                p = tooldir / rel[0]
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
                os.chmod(p, 0o755)

            pkg_payload = json.dumps({
                pkg: {"installed": True, "version": "2.0.0", "file": f"/pyenv/{pkg}.py"}
                for pkg, _ in verify.REQUIRED_PYTHON_PACKAGES
            })

            def fake_runner(argv, **kwargs):
                cmd = argv[0]
                if "verilator" in cmd:
                    return verify.CommandResult(0, "Verilator 5.050\n", "")
                if "yosys-smtbmc" in cmd:
                    return verify.CommandResult(0, "usage: yosys-smtbmc\n", "")
                if "yosys" in cmd:
                    return verify.CommandResult(0, "Yosys 0.69\n", "")
                if cmd.endswith("/sta"):
                    return verify.CommandResult(0, "3.1.0\n", "")
                if "circt-verilog" in cmd:
                    return verify.CommandResult(0, "LLVM version 24.0.0git\n", "")
                if "riscv64-unknown-elf-gcc" in cmd:
                    return verify.CommandResult(0, "riscv64-unknown-elf-gcc 12.2.0\n", "")
                if "clang" in cmd:
                    return verify.CommandResult(0, "clang version 20.1.8\n", "")
                if "z3" in cmd:
                    return verify.CommandResult(0, "Z3 version 4.8.12 - 64 bit\n", "")
                if "ccache" in cmd:
                    return verify.CommandResult(0, "Cache size: 0.1 / 2.0 GiB\nmax_size = 2.0G\n", "")
                if cmd == "git":
                    return verify.CommandResult(0, " b1befdb36df8 third_party/cocogfx (heads/master)\n", "")
                if cmd == sys.executable:
                    return verify.CommandResult(0, pkg_payload + "\n", "")
                return verify.CommandResult(0, "", "")

            out_json = tmp_path / "report.json"
            with mock.patch("shutil.which", side_effect=lambda x: f"/usr/bin/{x}" if x in ("z3", "ccache", "ldd") else None):
                with mock.patch.object(verify, "_run_cmd", side_effect=fake_runner):
                    buf = io.StringIO()
                    with redirect_stdout(buf):
                        rc = verify.main([
                            "--tooldir", str(tooldir),
                            "--build-dir", str(build_dir),
                            "--skip-docker",
                            "--json",
                            "--output", str(out_json),
                        ])
            self.assertEqual(rc, 0, buf.getvalue())
            data = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertTrue(data["ok"])
            self.assertIs(data["foundry_signoff"], False)
            self.assertIs(data["fpga_measured"], False)
            self.assertIs(data["silicon_measured"], False)
            self.assertTrue(data["build_dir"]["configured"])

            md = verify.render_markdown_report(data)
            self.assertIn("Verilator 5.050", md)
            self.assertIn("foundry_signoff=false", md)

            # Verify --markdown CLI mode writes file cleanly
            out_md = tmp_path / "report.md"
            with mock.patch("shutil.which", side_effect=lambda x: f"/usr/bin/{x}" if x in ("z3", "ccache", "ldd") else None):
                with mock.patch.object(verify, "_run_cmd", side_effect=fake_runner):
                    with redirect_stdout(io.StringIO()):
                        rc_md = verify.main([
                            "--tooldir", str(tooldir),
                            "--build-dir", str(build_dir),
                            "--skip-docker",
                            "--markdown",
                            "--output", str(out_md),
                        ])
            self.assertEqual(rc_md, 0)
            self.assertTrue(out_md.is_file())
            self.assertIn("## ADR-007 VM Toolchain", out_md.read_text(encoding="utf-8"))

    def test_cli_mutually_exclusive_flags_exit_2(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                verify.main(["--check-all", "--skip-docker"])
        self.assertEqual(ctx.exception.code, 2)

        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx_out:
                verify.main(["--json", "--markdown"])
        self.assertEqual(ctx_out.exception.code, 2)


class TestSubmodulesZ3AndFailurePaths(unittest.TestCase):
    def test_probe_git_submodules_states(self):
        def fake_git(argv, **kwargs):
            return verify.CommandResult(
                0,
                " b1befdb36df8 third_party/cocogfx (heads/master)\n"
                "-79e453139072 third_party/cvfpu\n"
                "+aaf5736dffa5 third_party/hardfloat (remotes/origin/HEAD)\n"
                "U1234567890ab third_party/conflict\n",
                "",
            )

        res = verify.probe_git_submodules(Path("."), runner=fake_git)
        self.assertFalse(res["ok"])
        self.assertEqual(res["total"], 4)
        self.assertEqual(res["uninitialized"], ["third_party/cvfpu"])
        self.assertEqual(res["modified"], ["third_party/hardfloat"])
        self.assertEqual(res["conflicts"], ["third_party/conflict"])

    def test_probe_z3_missing_and_present(self):
        with mock.patch("shutil.which", return_value=None):
            with mock.patch("importlib.util.find_spec", return_value=None):
                missing = verify.probe_z3()
        self.assertFalse(missing["found"])
        self.assertFalse(missing["ok"])

        with mock.patch("shutil.which", return_value="/usr/bin/z3"):
            with mock.patch("importlib.util.find_spec", return_value=object()):
                ok = verify.probe_z3(
                    runner=lambda argv, **kw: verify.CommandResult(0, "Z3 version 4.8.12 - 64 bit\n", "")
                )
        self.assertTrue(ok["ok"])
        self.assertTrue(ok["python_z3_available"])
        self.assertEqual(ok["version"], "Z3 4.8.12")

    def test_docker_failure_modes(self):
        with mock.patch("shutil.which", return_value=None):
            no_cli = verify.probe_docker_orfs()
        self.assertFalse(no_cli["ok"])
        self.assertIn("not found", no_cli["error"])

        with mock.patch("shutil.which", return_value="/usr/bin/docker"):
            no_daemon = verify.probe_docker_orfs(
                runner=lambda argv, **kw: verify.CommandResult(1, "", "Cannot connect to the Docker daemon")
            )
        self.assertFalse(no_daemon["ok"])
        self.assertFalse(no_daemon["daemon_ok"])

        def no_img_runner(argv, **kw):
            if "info" in argv:
                return verify.CommandResult(0, "29.10.0\n", "")
            return verify.CommandResult(1, "", "Error: No such image: openroad/orfs:latest")

        with mock.patch("shutil.which", return_value="/usr/bin/docker"):
            no_img = verify.probe_docker_orfs(runner=no_img_runner)
        self.assertFalse(no_img["ok"])
        self.assertTrue(no_img["daemon_ok"])
        self.assertFalse(no_img["image_present"])

    def test_ram_threshold_failure_and_missing_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            meminfo = Path(tmp) / "meminfo"
            meminfo.write_text("MemTotal: 2097152 kB\nMemAvailable: 1048576 kB\n", encoding="utf-8")
            gib = 1024 ** 3
            low_ram = verify.probe_disk_and_ram(
                Path(tmp),
                min_ram_gib=4.0,
                meminfo_path=meminfo,
                disk_usage_fn=lambda _: (100 * gib, 50 * gib, 50 * gib),
            )
            self.assertFalse(low_ram["ok"])
            self.assertTrue(any("Effective RAM" in e for e in low_ram["errors"]))

            with mock.patch("shutil.which", return_value=None):
                missing_tool = verify.probe_binary_tool("verilator", Path(tmp))
            self.assertFalse(missing_tool["found"])
            self.assertFalse(missing_tool["ok"])


if __name__ == "__main__":
    unittest.main()
