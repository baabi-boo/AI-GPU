# Licensed under the Apache License, Version 2.0.
"""Independent host-tool identity checks using small executable fixtures."""

import hashlib
import json
import os
from pathlib import Path
import shlex
import tempfile
import unittest
from unittest import mock

import baseline_host as host


VERSIONS = {
    "gcc": "gcc (fixture) 11.3.0",
    "g++": "g++ (fixture) 11.3.0",
    "make": "GNU Make 4.4.1",
    "ld": "GNU ld (fixture) 2.44",
    "as": "GNU assembler (fixture) 2.44",
    "python3": "Python 3.12.14",
    "cmake": "cmake version 3.31.6",
}
PLATFORM = {
    "system": "Linux", "machine": "x86_64",
    "libc": {"name": "glibc", "version": "2.41"},
}


class HostFixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.marker = self.base / "frontend-was-run"
        self.frontend = self.bin / "cc1plus"
        self.frontend.write_text(
            "#!/bin/sh\nprintf unexpected > " + shlex.quote(str(self.marker)) + "\nexit 99\n",
            encoding="utf-8",
        )
        self.frontend.chmod(0o755)
        for name, version in VERSIONS.items():
            self.write_tool(name, version)
        self.environment = {"PATH": str(self.bin), "FIXTURE_SECRET": "private-test-value"}
        self.platform_patch = mock.patch.object(host, "_platform", return_value=PLATFORM.copy())
        self.platform_patch.start()
        self.addCleanup(self.platform_patch.stop)

    def write_tool(self, name, version=None, *, frontend=None, exit_code=0):
        version = VERSIONS[name] if version is None else version
        frontend = str(self.frontend) if frontend is None else frontend
        script = "#!/bin/sh\n"
        if name == "g++":
            script += (
                'if [ "$1" = "-print-prog-name=cc1plus" ]; then\n'
                "  printf '%s\\n' " + shlex.quote(frontend) + "\n  exit 0\nfi\n"
            )
        script += "printf '%s\\n' " + shlex.quote(version) + "\nexit " + str(exit_code) + "\n"
        path = self.bin / name
        path.write_text(script, encoding="utf-8")
        path.chmod(0o755)
        return path

    def collect(self, environment=None):
        return host.collect_host(self.environment if environment is None else environment)

    def assert_blocked(self, report, tool=None):
        self.assertEqual(report["outcome"], "blocked", report)
        self.assertTrue(report["blockers"])
        if tool:
            self.assertTrue(any(tool in message for message in report["blockers"]), report)

    def test_records_exact_executable_hashes_without_running_the_frontend(self):
        report = self.collect()
        self.assertEqual(report["outcome"], "pass", report)
        self.assertEqual(report["host"], PLATFORM)
        self.assertEqual(set(report["tools"]), set(VERSIONS) | {"cc1plus"})
        for name, identity in report["tools"].items():
            content = (self.bin / name).read_bytes()
            self.assertEqual(identity["sha256"], hashlib.sha256(content).hexdigest())
            self.assertEqual(identity["size_bytes"], len(content))
        self.assertFalse(self.marker.exists())
        self.assertNotIn("version", report["tools"]["cc1plus"])
        self.assertEqual(report["tools"]["cc1plus"]["reported_by"],
                         "g++ -print-prog-name=cc1plus")

    def test_supplied_path_wins_over_the_calling_process_path(self):
        with mock.patch.dict(os.environ, {"PATH": "/nonexistent/fixture-path"}, clear=True):
            report = self.collect()
        self.assertEqual(report["outcome"], "pass", report)
        self.assertEqual(report["tools"]["gcc"]["version"], VERSIONS["gcc"])

    def test_default_environment_observes_a_copy_of_process_environment(self):
        with mock.patch.dict(os.environ, self.environment, clear=True):
            before = dict(os.environ)
            report = host.collect_host()
            self.assertEqual(dict(os.environ), before)
        self.assertEqual(report["outcome"], "pass", report)

    def test_environment_and_private_machine_details_are_not_serialized(self):
        before = self.environment.copy()
        report = self.collect()
        self.assertEqual(self.environment, before)
        text = json.dumps(report)
        for private in (str(self.base), "private-test-value", "FIXTURE_SECRET", "PATH"):
            if private == "PATH":
                self.assertNotIn('"PATH":', text)
            else:
                self.assertNotIn(private, text)
        self.assertEqual(set(report["host"]), {"system", "machine", "libc"})
        self.assertTrue(any("not a compiler compatibility" in item for item in report["limitations"]))
        self.assertNotIn("compatible", report)

    def test_missing_required_tools_block_without_using_a_parent_path(self):
        for name in host.REQUIRED_TOOLS:
            path = self.bin / name
            hidden = self.bin / (name + ".disabled")
            path.rename(hidden)
            try:
                with self.subTest(tool=name):
                    self.assert_blocked(self.collect(), name)
            finally:
                hidden.rename(path)
        self.assert_blocked(self.collect({"PATH": str(self.base / "missing")}))

    def test_absent_optional_cmake_is_a_limitation_not_a_blocker(self):
        (self.bin / "cmake").unlink()
        report = self.collect()
        self.assertEqual(report["outcome"], "pass", report)
        self.assertNotIn("cmake", report["tools"])
        self.assertTrue(any("cmake" in item for item in report["limitations"]))

    def test_present_but_invalid_optional_cmake_blocks(self):
        self.write_tool("cmake", "unidentified tool 1.0")
        self.assert_blocked(self.collect(), "cmake")

    def test_empty_malformed_nonzero_and_non_utf8_versions_block(self):
        for version, status in (("", 0), ("gcc without a version", 0),
                                ("some other program 11.3.0", 0),
                                (VERSIONS["gcc"], 7), ("gcc 11.3.0\tbad", 0)):
            with self.subTest(version=version, status=status):
                self.write_tool("gcc", version, exit_code=status)
                self.assert_blocked(self.collect(), "gcc")
        original = host._probe

        def invalid_utf8(argv, **kwargs):
            return (0, b"gcc 11.3.0 \xff") if Path(argv[0]).name == "gcc" else original(argv, **kwargs)

        with mock.patch.object(host, "_probe", side_effect=invalid_utf8):
            self.assert_blocked(self.collect(), "gcc")

    def test_nonexecutable_directory_and_broken_symlink_cannot_be_tools(self):
        path = self.bin / "gcc"
        path.chmod(0o644)
        self.assert_blocked(self.collect(), "gcc")
        path.unlink()
        path.mkdir()
        self.assert_blocked(self.collect(), "gcc")
        path.rmdir()
        path.symlink_to("missing-compiler")
        self.assert_blocked(self.collect(), "gcc")

    def test_executable_symlink_uses_target_hash_and_selected_invocation_name(self):
        selected = self.bin / "g++"
        target = self.bin / "compiler-driver-11"
        selected.rename(target)
        selected.symlink_to(target.name)
        with mock.patch.object(host, "_probe", wraps=host._probe) as probes:
            report = self.collect()
        self.assertEqual(report["outcome"], "pass", report)
        identity = report["tools"]["g++"]
        self.assertEqual(identity["resolved_name"], target.name)
        self.assertEqual(identity["sha256"], hashlib.sha256(target.read_bytes()).hexdigest())
        self.assertTrue(any(call.args[0] == [str(selected), "--version"]
                            for call in probes.call_args_list))

    def test_binary_content_changes_are_visible_even_with_identical_version(self):
        first = self.collect()["tools"]["gcc"]
        path = self.bin / "gcc"
        path.write_text(path.read_text(encoding="utf-8") + "# different tool bytes\n", encoding="utf-8")
        second = self.collect()["tools"]["gcc"]
        self.assertEqual(first["version"], second["version"])
        self.assertNotEqual(first["sha256"], second["sha256"])

    def test_binary_mutation_during_a_version_probe_is_rejected(self):
        original = host._probe

        def mutate(argv, **kwargs):
            result = original(argv, **kwargs)
            if Path(argv[0]).name == "gcc":
                path = Path(argv[0])
                path.write_text(path.read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")
            return result

        with mock.patch.object(host, "_probe", side_effect=mutate):
            self.assert_blocked(self.collect(), "gcc")

    def test_bare_frontend_name_is_resolved_through_the_supplied_path(self):
        self.write_tool("g++", frontend="cc1plus")
        report = self.collect()
        self.assertEqual(report["outcome"], "pass", report)
        self.assertEqual(report["tools"]["cc1plus"]["sha256"],
                         hashlib.sha256(self.frontend.read_bytes()).hexdigest())
        self.assertFalse(self.marker.exists())

    def test_missing_nonexecutable_and_malformed_frontends_block_the_driver(self):
        for frontend in (str(self.base / "missing"), str(self.base), "", "cc1plus\nother"):
            with self.subTest(frontend=frontend):
                self.write_tool("g++", frontend=frontend)
                self.assert_blocked(self.collect(), "g++")
        self.write_tool("g++")
        self.frontend.chmod(0o644)
        self.assert_blocked(self.collect(), "g++")

    def test_driver_mutation_while_resolving_frontend_is_rejected(self):
        original = host._probe

        def mutate(argv, **kwargs):
            result = original(argv, **kwargs)
            if argv[1] == "-print-prog-name=cc1plus":
                path = Path(argv[0])
                path.write_text(path.read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")
            return result

        with mock.patch.object(host, "_probe", side_effect=mutate):
            self.assert_blocked(self.collect(), "g++")

    def test_private_version_paths_and_extra_output_lines_are_omitted(self):
        self.write_tool("gcc", "gcc 11.3.0 /workspace/private/install\nprivate-extra-line")
        report = self.collect()
        self.assertEqual(report["outcome"], "pass", report)
        self.assertEqual(report["tools"]["gcc"]["version"], "gcc 11.3.0 <path>")
        self.assertNotIn("/workspace/private", json.dumps(report))
        self.assertNotIn("private-extra-line", json.dumps(report))

    def test_probes_are_bounded_and_receive_the_selected_environment(self):
        with mock.patch.object(host, "_probe", wraps=host._probe) as probes:
            report = self.collect()
        self.assertEqual(report["outcome"], "pass", report)
        for call in probes.call_args_list:
            self.assertEqual(call.kwargs["timeout"], 5)
            self.assertEqual(call.kwargs["environment"], self.environment)
        with mock.patch.object(host, "_probe", side_effect=ValueError("bounded probe failure")):
            self.assert_blocked(self.collect())

    def test_malformed_environments_are_blocked_before_any_probe(self):
        for environment in ([], "PATH", {"PATH": None}, {1: "text"},
                            {"BAD=KEY": "text"}, {"PATH": "bad\0path"}, {"": "text"}):
            with self.subTest(environment=environment), mock.patch.object(host, "_probe") as probe:
                self.assert_blocked(host.collect_host(environment))
                probe.assert_not_called()

    def test_missing_or_malformed_platform_identity_blocks(self):
        self.platform_patch.stop()
        with mock.patch.object(host.platform, "system", return_value=""):
            self.assert_blocked(self.collect())
        with mock.patch.object(host.platform, "system", return_value="/private/host"):
            report = self.collect()
            self.assert_blocked(report)
            self.assertNotIn("/private/host", json.dumps(report))
        with mock.patch.object(host.os, "confstr", return_value=None), \
                mock.patch.object(host.platform, "libc_ver", return_value=("", "")):
            self.assert_blocked(self.collect())


if __name__ == "__main__":
    unittest.main()
