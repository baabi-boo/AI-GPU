# SPDX-License-Identifier: Apache-2.0
"""Bounded environment tests, with explicitly injected package/probe fixtures.

The compiled version printer is an ELF selection fixture, not CMake. These
tests exercise real venv creation and child processes; mocked native probes
establish preparation control flow, not successful CMake build qualification.
"""

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import governance_env as environment


class GovernanceEnvironmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix="governance-env-tools-")
        cls.addClassCleanup(temporary.cleanup)
        cls.tools = Path(temporary.name).resolve()
        for name in ("home", "tmp"):
            (cls.tools / name).mkdir()
        compiler = shutil.which("gcc", path="/usr/bin:/bin")
        if compiler is None:
            raise AssertionError("environment tests require the governance host C compiler")
        cls.native_fixture = cls.tools / "version-printer"
        cls.preload_fixture = cls.tools / "preload-marker.so"
        sources = (
            (cls.native_fixture, [], '#include <stdio.h>\n'
             'int main(void) { puts("cmake version 3.22.6"); return 0; }\n'),
            (cls.preload_fixture, ["-shared", "-fPIC"], '#include <stdio.h>\n'
             '__attribute__((constructor)) static void marker(void) {\n'
             '    fputs("ambient-native-injected\\n", stderr);\n}\n'),
        )
        for output, options, source in sources:
            result = subprocess.run(
                [compiler, *options, "-x", "c", "-", "-o", str(output)],
                input=source, text=True, capture_output=True, timeout=30,
                cwd=cls.tools, env=environment.clean_environment(sys.executable, cls.tools))
            if result.returncode:
                raise AssertionError("native test fixture compilation failed: " + result.stderr)
        if cls.native_fixture.read_bytes()[:4] != b"\x7fELF":
            raise AssertionError("governance environment tests require native ELF fixtures")

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="governance-env-test-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.output = self.base / "output"

    def executable(self, name, content=b"#!/bin/sh\nexit 86\n"):
        path = self.base / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        path.chmod(0o700)
        return path

    def cmake_fixture(self, name="native-cmake", version="3.22.6"):
        data = self.native_fixture.read_bytes()
        self.assertEqual(len(version), len("3.22.6"))
        self.assertEqual(data.count(b"3.22.6"), 1)
        return self.executable(name, data.replace(b"3.22.6", version.encode("ascii")))

    def package_fixture(self, launcher, native, *, files=None, entry_points=None):
        locations = {"../../../bin/cmake": launcher, "cmake/data/bin/cmake": native}
        return SimpleNamespace(
            version="3.22.6", files=list(locations) if files is None else files,
            locate_file=lambda item: locations[str(item)],
            entry_points=[SimpleNamespace(group="console_scripts", name="cmake",
                                          value="cmake:cmake")]
            if entry_points is None else entry_points)

    def failed_receipt(self, output=None, reason=None):
        output = output or self.output
        report = json.loads((output / "environment.json").read_text())
        self.assertEqual(report["status"], "failed")
        self.assertIsNotNone(report["finished_at"])
        self.assertTrue(report["error"])
        self.assertFalse((output / "environment.json.tmp").exists())
        if reason:
            self.assertIn(reason, report["error"])
        return report

    def test_fresh_output_creates_private_empty_sibling_directory(self):
        source = self.base / "source"
        source.mkdir()
        output = self.base / "source-evidence"
        with mock.patch.object(environment, "ROOT", source):
            self.assertEqual(environment.fresh_output(str(output)), output)
        self.assertEqual(list(output.iterdir()), [])
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o700)

    def test_fresh_output_rejects_relative_unsafe_and_dot_traversal_paths(self):
        for raw in ("relative", str(self.base) + "/./output",
                    str(self.base) + "/child/../output",
                    str(self.base / "unsafe name"), str(self.base / "unsafe;name"),
                    str(self.base / "unsafe\nname"), str(self.base / "$HOME")):
            with self.subTest(path=raw), self.assertRaises(ValueError):
                environment.fresh_output(raw)
        self.assertEqual(list(self.base.iterdir()), [])

    def test_fresh_output_rejects_missing_parent_without_creating_it(self):
        with self.assertRaisesRegex(ValueError, "parent directory must already exist"):
            environment.fresh_output(str(self.base / "missing/output"))
        self.assertEqual(list(self.base.iterdir()), [])

    def test_fresh_output_rejects_source_descendant_and_ancestor(self):
        source = self.base / "source"
        source.mkdir()
        with mock.patch.object(environment, "ROOT", source):
            for output in (source, source / "evidence", self.base):
                with self.subTest(path=output), self.assertRaisesRegex(
                        ValueError, "outside the source checkout"):
                    environment.fresh_output(str(output))
        self.assertEqual(list(source.iterdir()), [])

    def test_reused_output_preserves_existing_receipt_and_files(self):
        self.output.mkdir()
        receipt = self.output / "environment.json"
        receipt.write_bytes(b"previous receipt must remain unchanged\n")
        with self.assertRaisesRegex(ValueError, "must be fresh"):
            environment.prepare_environment(str(self.output), str(self.base / "missing-cmake"))
        self.assertEqual(receipt.read_bytes(), b"previous receipt must remain unchanged\n")
        self.assertEqual(list(self.output.iterdir()), [receipt])
        existing_file = self.base / "existing-file"
        existing_file.write_bytes(b"preserved")
        with self.assertRaisesRegex(ValueError, "must be fresh"):
            environment.fresh_output(str(existing_file))
        self.assertEqual(existing_file.read_bytes(), b"preserved")

    def test_fresh_output_rejects_symlink_parent_output_and_dangling_link(self):
        target = self.base / "target"
        target.mkdir()
        link = self.base / "alias"
        link.symlink_to(target, target_is_directory=True)
        dangling = self.base / "dangling"
        dangling.symlink_to(self.base / "absent")
        for output in (link, link / "output", dangling):
            with self.subTest(path=output), self.assertRaisesRegex(ValueError, "symlink"):
                environment.fresh_output(str(output))
        self.assertEqual(list(target.iterdir()), [])
        self.assertTrue(link.is_symlink())
        self.assertTrue(dangling.is_symlink())

    def test_identity_binds_alias_to_actual_bytes_and_detects_same_size_edit(self):
        target = self.executable("target", b"first bytes")
        alias = self.base / "alias"
        alias.symlink_to(target)
        before = environment.identity(alias)
        self.assertEqual(before, {"path": str(alias), "resolved_path": str(target),
                                 "sha256": hashlib.sha256(b"first bytes").hexdigest(),
                                 "size_bytes": 11})
        target.write_bytes(b"other bytes")
        after = environment.identity(alias)
        self.assertEqual(after["size_bytes"], before["size_bytes"])
        self.assertNotEqual(after["sha256"], before["sha256"])

    def test_native_cmake_selects_real_elf_without_package_metadata(self):
        native = self.cmake_fixture()
        alias = self.base / "cmake-alias"
        alias.symlink_to(native)
        with mock.patch.object(environment.importlib.metadata, "distribution") as metadata:
            selected, receipt = environment.native_cmake(alias)
        metadata.assert_not_called()
        self.assertEqual(selected, native)
        self.assertEqual(receipt, {"resolution": "native",
                                  "requested": environment.identity(alias),
                                  "native": environment.identity(native)})

    def test_native_cmake_rejects_missing_nonexecutable_and_directory_inputs(self):
        with self.assertRaises(FileNotFoundError):
            environment.native_cmake(self.base / "missing")
        native = self.cmake_fixture()
        native.chmod(0o600)
        for path in (native, self.base):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "regular executable"):
                environment.native_cmake(path)

    def test_mocked_distribution_resolves_bound_launcher_without_executing_it(self):
        launcher = self.executable("bin/cmake")
        native = self.cmake_fixture("package/cmake/data/bin/cmake")
        package = self.package_fixture(launcher, native)
        with mock.patch.object(environment.importlib.metadata, "distribution", return_value=package), \
                mock.patch.object(environment.subprocess, "Popen") as execute:
            selected, receipt = environment.native_cmake(launcher)
        execute.assert_not_called()
        self.assertEqual(selected, native)
        self.assertEqual(receipt["resolution"], "python-package")
        self.assertEqual(receipt["package_version"], "3.22.6")
        self.assertEqual(receipt["requested"], environment.identity(launcher))
        self.assertEqual(receipt["native"], environment.identity(native))

    def test_mocked_distribution_absence_and_unrelated_launcher_are_rejected(self):
        launcher = self.executable("selected-launcher")
        with mock.patch.object(environment.importlib.metadata, "distribution",
                               side_effect=importlib.metadata.PackageNotFoundError("cmake")), \
                self.assertRaisesRegex(ValueError, "pass --cmake the native executable"):
            environment.native_cmake(launcher)
        package = self.package_fixture(self.executable("other-launcher"), self.cmake_fixture())
        with mock.patch.object(environment.importlib.metadata, "distribution", return_value=package), \
                self.assertRaisesRegex(ValueError, "not bound"):
            environment.native_cmake(launcher)

    def test_mocked_distribution_requires_exact_entry_point_and_unique_native(self):
        launcher, native = self.executable("launcher"), self.cmake_fixture()
        entry_points = [[], [SimpleNamespace(group="console_scripts", name="cmake",
                                             value="different:cmake")]]
        for entries in entry_points:
            package = self.package_fixture(launcher, native, entry_points=entries)
            with self.subTest(entries=entries), mock.patch.object(
                    environment.importlib.metadata, "distribution", return_value=package), \
                    self.assertRaisesRegex(ValueError, "not bound"):
                environment.native_cmake(launcher)
        for files in (["../../../bin/cmake"],
                      ["../../../bin/cmake", "cmake/data/bin/cmake", "cmake/data/bin/cmake"]):
            package = self.package_fixture(launcher, native, files=files)
            with self.subTest(files=files), mock.patch.object(
                    environment.importlib.metadata, "distribution", return_value=package), \
                    self.assertRaisesRegex(ValueError, "identify one native executable"):
                environment.native_cmake(launcher)

    def test_mocked_distribution_cannot_substitute_another_script_for_native_elf(self):
        launcher, script = self.executable("launcher"), self.executable("native-script")
        package = self.package_fixture(launcher, script)
        with mock.patch.object(environment.importlib.metadata, "distribution", return_value=package), \
                self.assertRaisesRegex(ValueError, "not an ELF executable"):
            environment.native_cmake(launcher)

    def test_clean_environment_prevents_actual_ambient_loader_and_python_injection(self):
        for name in ("home", "tmp", "injection"):
            (self.base / name).mkdir()
        injection = self.base / "injection"
        customization = injection / "sitecustomize.py"
        customization.write_text(
            'import sys\nsys._governance_ambient_injected = True\n'
            'sys.stderr.write("ambient-python-injected\\n")\n')
        probe = (
            "import json, os, sys; print(json.dumps({'environment': dict(os.environ), "
            "'path': sys.path, "
            "'customization': getattr(sys.modules.get('sitecustomize'), '__file__', None), "
            "'injected': getattr(sys, '_governance_ambient_injected', False)}))")
        cleaned = environment.clean_environment(sys.executable, self.base)
        injected = {"LD_PRELOAD": str(self.preload_fixture),
                    "LD_LIBRARY_PATH": str(injection), "PYTHONPATH": str(injection)}
        control = subprocess.run([sys.executable, "-c", probe], cwd=self.base,
                                 env=cleaned | injected, text=True, capture_output=True, timeout=10)
        self.assertEqual(control.returncode, 0, control.stderr)
        self.assertIn("ambient-native-injected", control.stderr)
        self.assertIn("ambient-python-injected", control.stderr)
        poisoned = json.loads(control.stdout)
        self.assertTrue(poisoned["injected"])
        self.assertEqual(poisoned["customization"], str(customization))
        ambient = injected | {"PYTHONHOME": str(injection), "PYTHONUSERBASE": str(injection),
                              "PYTHONSTARTUP": str(customization),
                              "PYTHONINSPECT": "1", "CC": "untrusted-compiler",
                              "CMAKE_TOOLCHAIN_FILE": str(injection / "toolchain.cmake")}
        report = {"commands": []}
        with mock.patch.dict(os.environ, ambient):
            cleaned = environment.clean_environment(sys.executable, self.base)
            result = environment.command(report, "isolated-python", [sys.executable, "-c", probe],
                                         cleaned, self.base)
        observed = json.loads(result["stdout"])
        self.assertEqual(observed["environment"], cleaned)
        self.assertFalse(set(ambient) & set(observed["environment"]))
        self.assertNotIn(str(injection), observed["path"])
        self.assertFalse(observed["injected"])
        self.assertNotEqual(observed["customization"], str(customization))
        self.assertEqual(result["stderr"], "")
        self.assertEqual(cleaned["PATH"].split(os.pathsep),
                         list(dict.fromkeys((str(Path(sys.executable).parent), "/usr/bin", "/bin"))))

    def test_mocked_native_probes_reach_ready_after_real_isolated_venv_creation(self):
        native = self.cmake_fixture()

        def inspect_preparing(report, output, cleaned):
            retained = json.loads((output / "environment.json").read_text())
            self.assertEqual(retained["status"], "preparing")
            self.assertIsNone(retained["finished_at"])
            self.assertEqual(cleaned, report["environment"])

        with mock.patch.object(environment, "native_probes", side_effect=inspect_preparing):
            report = environment.prepare_environment(str(self.output), str(native))
        self.assertEqual(report["status"], "ready")
        self.assertIsNone(report["error"])
        self.assertFalse(report["python"]["pip_present"])
        self.assertFalse(report["python"]["user_site_enabled"])
        self.assertEqual(report["python"]["prefix"], str(self.output / "venv"))
        self.assertEqual(report["interpreter"], str(self.output / "venv/bin/python3"))
        self.assertEqual(report["python"]["executable"], report["interpreter"])
        self.assertEqual(report["tools"]["python3"]["path"], report["interpreter"])
        self.assertEqual(report["tools"]["python"]["path"], str(self.output / "venv/bin/python"))
        self.assertEqual(report["tools"]["python3"]["resolved_path"],
                         report["tools"]["python"]["resolved_path"])
        self.assertEqual(report["tools"]["cmake"]["resolved_path"], str(native))
        self.assertEqual(json.loads((self.output / "environment.json").read_text()), report)

    def test_python_alias_selection_requires_exact_venv_paths(self):
        native, original_which = self.cmake_fixture(), shutil.which
        for selected, substitute in (("python3", "python"), ("python", "python3")):
            with self.subTest(alias=selected):
                output = self.base / ("output-" + selected)

                def wrong_alias(name, **kwargs):
                    if name == selected:
                        return str(output / "venv/bin" / substitute)
                    return original_which(name, **kwargs)

                with mock.patch.object(environment.shutil, "which", side_effect=wrong_alias), \
                        mock.patch.object(environment, "native_probes") as probes, \
                        self.assertRaisesRegex(ValueError, "does not select the venv Python aliases"):
                    environment.prepare_environment(str(output), str(native))
                probes.assert_not_called()
                report = self.failed_receipt(output, reason="does not select the venv Python aliases")
                self.assertEqual(report["tools"]["python3"]["resolved_path"],
                                 report["tools"]["python"]["resolved_path"])
                self.assertEqual(report["tools"][selected]["path"],
                                 str(output / "venv/bin" / substitute))

    def test_missing_cmake_retains_failed_receipt_before_venv_creation(self):
        with self.assertRaises(FileNotFoundError):
            environment.prepare_environment(str(self.output), str(self.base / "missing-cmake"))
        report = self.failed_receipt(reason="FileNotFoundError")
        self.assertEqual(report["commands"], [])
        self.assertEqual(report["probes"], {})
        self.assertFalse((self.output / "venv").exists())

    def test_mocked_missing_required_tool_fails_before_native_probes(self):
        native, original_which = self.cmake_fixture(), shutil.which

        def missing_compiler(name, **kwargs):
            return None if name == "g++" else original_which(name, **kwargs)

        with mock.patch.object(environment.shutil, "which", side_effect=missing_compiler), \
                mock.patch.object(environment, "native_probes") as probes, \
                self.assertRaisesRegex(ValueError, "absent from clean PATH: g\\+\\+"):
            environment.prepare_environment(str(self.output), str(native))
        probes.assert_not_called()
        report = self.failed_receipt(reason="absent from clean PATH: g++")
        self.assertIn("gcc", report["tools"])
        self.assertNotIn("g++", report["tools"])
        self.assertEqual(report["probes"], {})

    def test_incompatible_and_unrecognized_cmake_versions_retain_failed_receipts(self):
        for version, reason in (("3.13.9", "requires CMake 3.21 through 3.25"),
                                ("3.20.9", "requires CMake 3.21 through 3.25"),
                                ("3.26.0", "requires CMake 3.21 through 3.25"),
                                ("4.00.0", "requires CMake 3.21 through 3.25"),
                                ("banana", "unrecognized version")):
            native = self.cmake_fixture("cmake-" + version, version=version)
            output = self.base / ("output-" + version)
            with self.subTest(version=version), mock.patch.object(
                    environment, "native_probes") as probes, self.assertRaisesRegex(ValueError, reason):
                environment.prepare_environment(str(output), str(native))
            probes.assert_not_called()
            report = self.failed_receipt(output, reason)
            self.assertEqual(report["tools"]["cmake"]["version"], "cmake version " + version)
            self.assertEqual(report["probes"], {})

    def test_mocked_native_probes_accept_supported_cmake_version_boundaries(self):
        for version in ("3.21.0", "3.25.9"):
            native = self.cmake_fixture("cmake-" + version, version=version)
            output = self.base / ("output-" + version)
            with self.subTest(version=version), mock.patch.object(
                    environment, "native_probes") as probes:
                report = environment.prepare_environment(str(output), str(native))
                probes.assert_called_once()
                self.assertEqual(report["status"], "ready")
                self.assertEqual(report["tools"]["cmake"]["version"], "cmake version " + version)
                self.assertEqual(json.loads((output / "environment.json").read_text()), report)

    def test_mocked_probe_tool_content_and_alias_tampering_are_rejected(self):
        for tamper in ("bytes", "alias"):
            native = self.cmake_fixture("cmake-" + tamper)
            replacement = self.cmake_fixture("replacement-" + tamper)
            output = self.base / ("output-" + tamper)

            def change_tool(report, workspace, cleaned):
                if tamper == "bytes":
                    native.write_bytes(native.read_bytes() + b"changed")
                else:
                    alias = workspace / "venv/bin/cmake"
                    alias.unlink()
                    alias.symlink_to(replacement)

            with self.subTest(tamper=tamper), mock.patch.object(
                    environment, "native_probes", side_effect=change_tool), \
                    self.assertRaisesRegex(ValueError, "selected tool changed during preparation"):
                environment.prepare_environment(str(output), str(native))
            self.failed_receipt(output, "selected tool changed during preparation")

    def test_injected_probe_command_failure_retains_failed_receipt_and_cli_has_no_success_json(self):
        native = self.cmake_fixture()

        def failing_probe(report, output, cleaned):
            environment.command(report, "injected-probe-failure", [sys.executable, "-c",
                "import sys; print('partial probe output'); "
                "print('probe diagnostic', file=sys.stderr); sys.exit(9)"], cleaned, output)

        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(environment, "native_probes", side_effect=failing_probe), \
                redirect_stdout(stdout), redirect_stderr(stderr):
            result = environment.main(["--output-dir", str(self.output), "--cmake", str(native)])
        self.assertEqual(result, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("governance environment failed:", stderr.getvalue())
        report = self.failed_receipt(reason="injected-probe-failure failed with exit 9")
        self.assertEqual(report["probes"], {})
        self.assertEqual(report["commands"][-1]["returncode"], 9)
        self.assertEqual(report["commands"][-1]["stdout"], "partial probe output\n")
        self.assertEqual(report["commands"][-1]["stderr"], "probe diagnostic\n")

    def test_injected_probe_timeout_retains_failed_receipt_even_with_check_false(self):
        native = self.cmake_fixture()

        def timed_probe(report, output, cleaned):
            environment.command(report, "injected-probe-timeout", [sys.executable, "-c",
                "import time; time.sleep(10)"], cleaned, output, check=False, timeout=0.2)

        with mock.patch.object(environment, "native_probes", side_effect=timed_probe), \
                self.assertRaisesRegex(ValueError, "exceeded its time bound"):
            environment.prepare_environment(str(self.output), str(native))
        report = self.failed_receipt(reason="injected-probe-timeout")
        self.assertEqual(report["probes"], {})
        self.assertTrue(report["commands"][-1]["timed_out"])
        self.assertEqual(report["commands"][-1]["returncode"], -signal.SIGKILL)

    def test_command_records_stdin_stdout_stderr_and_exact_environment(self):
        report = {"commands": []}
        cleaned = environment.clean_environment(sys.executable, self.base)
        argv = [sys.executable, "-c", "import sys; sys.stdout.write(sys.stdin.read()); "
                "sys.stderr.write('diagnostic\\n')"]
        result = environment.command(report, "roundtrip", argv, cleaned, self.base,
                                     input_text="input-\u03bb\n")
        self.assertEqual(report["commands"], [result])
        self.assertEqual(result["argv"], argv)
        self.assertEqual(result["cwd"], str(self.base))
        self.assertEqual(result["environment"], cleaned)
        self.assertEqual(result["stdout"], "input-\u03bb\n")
        self.assertEqual(result["stderr"], "diagnostic\n")
        self.assertEqual(result["returncode"], 0)
        self.assertFalse(result["timed_out"])

    def test_command_checked_and_permitted_nonzero_exit_preserve_failure_details(self):
        for check in (True, False):
            report = {"commands": []}
            arguments = (report, "exit-seven", [sys.executable, "-c",
                "import sys; print('diagnostic', file=sys.stderr); sys.exit(7)"],
                environment.clean_environment(sys.executable, self.base), self.base)
            with self.subTest(check=check):
                if check:
                    with self.assertRaisesRegex(ValueError, "failed with exit 7: diagnostic"):
                        environment.command(*arguments)
                else:
                    self.assertIs(environment.command(*arguments, check=False), report["commands"][0])
                self.assertEqual(report["commands"][0]["returncode"], 7)
                self.assertEqual(report["commands"][0]["stderr"], "diagnostic\n")
                self.assertFalse(report["commands"][0]["timed_out"])

    def test_command_timeout_kills_its_process_group_and_retains_output(self):
        report = {"commands": []}
        program = ("import subprocess, sys, time; "
                   "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(10)']); "
                   "print(child.pid, flush=True); time.sleep(10)")
        with self.assertRaisesRegex(ValueError, "exceeded its time bound"):
            environment.command(report, "process-group-timeout", [sys.executable, "-c", program],
                                environment.clean_environment(sys.executable, self.base),
                                self.base, timeout=1)
        result = report["commands"][0]
        self.assertTrue(result["timed_out"])
        self.assertEqual(result["returncode"], -signal.SIGKILL)
        child_pid = int(result["stdout"].strip())
        process_state = Path("/proc") / str(child_pid) / "stat"
        try:
            state = process_state.read_text().rsplit(")", 1)[1].split()[0]
        except FileNotFoundError:
            pass
        else:
            self.assertIn(state, ("Z", "X"), "timed-out descendant remained alive")

    def test_command_output_bound_rejects_zero_exit_even_with_check_false(self):
        for stream in ("stdout", "stderr"):
            report = {"commands": []}
            with self.subTest(stream=stream), mock.patch.object(environment, "MAX_OUTPUT_BYTES", 32), \
                    self.assertRaisesRegex(ValueError, "exceeded its output bound"):
                environment.command(report, "large-output", [sys.executable, "-c",
                    "import sys; sys." + stream + ".write('x' * 33)"],
                    environment.clean_environment(sys.executable, self.base), self.base, check=False)
            self.assertEqual(report["commands"][0]["returncode"], 0)
            self.assertEqual(report["commands"][0][stream], "x" * 32)


if __name__ == "__main__":
    unittest.main()
