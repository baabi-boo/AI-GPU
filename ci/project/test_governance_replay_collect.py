# SPDX-License-Identifier: Apache-2.0
"""Tiny committed checkouts exercise isolated canonical collect-only discovery."""

import importlib.util
import json
import os
from pathlib import Path
import py_compile
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from unittest import mock

import governance_replay_collect as collector


_CASE = """\
import unittest

class Example(unittest.TestCase):
    def test_zulu(self):
        raise AssertionError("test body was executed")

    def test_alpha(self):
        raise AssertionError("test body was executed")
"""


class GovernanceReplayCollectTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="governance-collect-test-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.root = self.base / "source"
        self.root.mkdir()
        self.environment = {
            "PATH": "/usr/bin:/bin", "HOME": str(self.base), "LANG": "C", "LC_ALL": "C",
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_NAME": "Fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
            "GIT_TERMINAL_PROMPT": "0", "PYTHONDONTWRITEBYTECODE": "1",
        }
        self.git("init", "-q")
        self.git("config", "core.autocrlf", "false")
        self.git("config", "core.filemode", "true")
        self.write("ci/project/test_fixture.py", _CASE)
        self.commit()

    def git(self, *arguments, root=None):
        return subprocess.run(
            ["/usr/bin/git", "-c", "core.hooksPath=" + os.devnull,
             "-c", "commit.gpgsign=false", *arguments],
            cwd=self.root if root is None else root, env=self.environment,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=10,
        ).stdout

    def write(self, name, contents):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(contents), encoding="utf-8")
        return path

    def commit(self):
        self.git("add", "--all", ".")
        self.git("commit", "-qm", "collector fixture")
        self.revision = self.git("rev-parse", "HEAD").decode().strip()

    def collect(self):
        return collector.collect(self.root, self.revision)

    def replace_test(self, content):
        self.write("ci/project/test_fixture.py", content)
        self.commit()

    def reject(self):
        with self.assertRaises(collector.ReplayCollectError):
            self.collect()

    def test_canonical_order_is_collected_without_fixtures_or_test_bodies(self):
        marker = self.base / "body"
        self.replace_test(f"""
            import unittest
            from pathlib import Path

            class Example(unittest.TestCase):
                @classmethod
                def setUpClass(cls):
                    Path({str(marker)!r}).touch()

                def setUp(self):
                    Path({str(marker)!r}).touch()

                def test_zulu(self):
                    Path({str(marker)!r}).touch()

                def test_alpha(self):
                    Path({str(marker)!r}).touch()
        """)
        self.assertEqual(self.collect(), ["test_fixture.Example.test_alpha",
                                         "test_fixture.Example.test_zulu"])
        self.assertFalse(marker.exists())
        self.assertFalse(list(self.root.rglob("*.pyc")))

    def test_nested_load_tests_order_is_preserved_independently(self):
        self.write("ci/project/governance_run.py", "raise RuntimeError('producer imported')\n")
        self.replace_test(_CASE + """
def load_tests(loader, tests, pattern):
    return unittest.TestSuite([
        unittest.TestSuite([Example('test_zulu')]),
        unittest.TestSuite([unittest.TestSuite([Example('test_alpha')])]),
    ])
""")
        self.assertEqual(self.collect(), ["test_fixture.Example.test_zulu",
                                         "test_fixture.Example.test_alpha"])

    def test_only_the_selected_checkout_is_imported_in_the_child(self):
        marker = self.base / "imported"
        self.write("ci/project/collector_fixture_helper.py", "VALUE = 19\n")
        self.replace_test(f"""
            import unittest
            from pathlib import Path
            import collector_fixture_helper
            assert collector_fixture_helper.VALUE == 19
            Path({str(marker)!r}).write_text('import only')

            class Example(unittest.TestCase):
                def test_example(self):
                    raise AssertionError('body ran')
        """)
        with mock.patch.dict(sys.modules, {"collector_fixture_helper": object(),
                                           "test_fixture": object()}):
            self.assertEqual(self.collect(), ["test_fixture.Example.test_example"])
            self.assertIs(type(sys.modules["collector_fixture_helper"]), object)
        self.assertEqual(marker.read_text(), "import only")
        self.assertNotIn("collector_fixture_helper", sys.modules)

    def test_environment_is_explicit_and_excludes_tokens_and_loader_overrides(self):
        poisoned = {
            "GH_TOKEN": "fixture-secret", "GITHUB_TOKEN": "fixture-secret",
            "PRIVATE_URL": "https://private.invalid/?fixture=secret",
            "PYTHONPATH": str(self.base), "PYTHONHOME": str(self.base),
            "PYTHONSTARTUP": str(self.base / "startup.py"),
            "GIT_DIR": str(self.base), "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "core.hooksPath", "GIT_CONFIG_VALUE_0": str(self.base),
            "LD_PRELOAD": str(self.base / "poison.so"), "LD_LIBRARY_PATH": str(self.base),
            "SSLKEYLOGFILE": str(self.base / "keys"), "HOME": str(self.base),
            "PATH": str(self.base), "TMPDIR": str(self.base),
        }
        self.replace_test(textwrap.dedent(f"""
            import os
            import sys
            from pathlib import Path
            assert set(os.environ) <= {{'PATH', 'HOME', 'TMPDIR', 'LANG', 'LC_ALL', 'TZ'}}
            assert os.environ['PATH'] == '/usr/bin:/bin'
            assert os.environ['HOME'] != {str(self.base)!r}
            assert os.environ['TMPDIR'] != {str(self.base)!r}
            assert Path(os.environ['HOME']).is_dir()
            assert Path(os.environ['TMPDIR']).is_dir()
            assert Path.cwd() == Path(__file__).resolve().parents[2]
            assert sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode
        """) + _CASE)
        with mock.patch.dict(os.environ, poisoned):
            self.assertEqual(len(self.collect()), 2)

    def test_tracked_python_outside_discovery_directory_can_be_imported(self):
        self.write("python/fixture_package/__init__.py", "VALUE = 23\n")
        self.write("python/fixture_namespace/module.py", "VALUE = 31\n")
        self.write("tools/fixture_direct.py", "VALUE = 29\n")
        self.replace_test("""
import importlib.util
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'python'))
import fixture_package
from fixture_namespace import module as namespace_module
assert fixture_package.VALUE == 23
assert namespace_module.VALUE == 31
spec = importlib.util.spec_from_file_location('direct_fixture', ROOT / 'tools/fixture_direct.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert module.VALUE == 29
""" + _CASE)
        self.assertEqual(len(self.collect()), 2)

    def test_stdlib_lazy_imports_and_dynamic_namedtuples_remain_supported(self):
        self.replace_test("""
from collections import namedtuple
import ctypes
import decimal
import email.message
import typing
import xml.etree.ElementTree
assert namedtuple('ExampleTuple', 'number')(3).number == 3
assert decimal.Decimal('2.5') * 2 == 5
""" + _CASE)
        self.assertEqual(len(self.collect()), 2)

    def test_wrong_revision_and_dirty_source_fail_before_import(self):
        marker = self.base / "imported"
        self.replace_test(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n" + _CASE)
        with self.assertRaises(collector.ReplayCollectError):
            collector.collect(self.root, "0" * 40)
        self.assertFalse(marker.exists())
        self.write("tracked.txt", "untracked\n")
        self.reject()
        self.assertFalse(marker.exists())

    def test_source_changes_during_import_are_rejected(self):
        self.write("tracked.txt", "before\n")
        self.replace_test("""
from pathlib import Path
(Path(__file__).resolve().parents[2] / 'tracked.txt').write_text('after')
""" + _CASE)
        self.reject()
        self.assertEqual((self.root / "tracked.txt").read_text(), "after")

    def test_source_before_and_after_bindings_must_be_equal(self):
        real_binding = collector.source_binding
        observations = []

        def binding(*arguments):
            result = real_binding(*arguments)
            observations.append(result)
            if len(observations) == 2:
                return {**result, "tracked_bytes": result["tracked_bytes"] + 1}
            return result

        with mock.patch.object(collector, "source_binding", side_effect=binding), \
                self.assertRaisesRegex(collector.ReplayCollectError, "source changed"):
            self.collect()
        self.assertEqual(len(observations), 2)

    def test_imported_source_is_rehashed_before_its_code_executes(self):
        marker = self.base / "substituted-code"
        helper = self.write("ci/project/helper.py", "VALUE = 19\n")
        self.replace_test("import helper\nassert helper.VALUE == 19\n" + _CASE)
        run_child = collector._run_child

        def changed(root, request):
            helper.write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\nVALUE = 19\n")
            return run_child(root, request)

        with mock.patch.object(collector, "_run_child", side_effect=changed):
            self.reject()
        self.assertFalse(marker.exists())

    def test_unbound_synthetic_module_is_rejected(self):
        self.replace_test("import sys, types\n"
                          "sys.modules['unbound_fixture'] = types.ModuleType('unbound_fixture')\n" + _CASE)
        self.reject()

    def test_loader_failure_and_empty_discovery_are_rejected(self):
        for content in ("raise RuntimeError('import failure')\n", "import unittest\n"):
            with self.subTest(content=content):
                self.replace_test(content)
                self.reject()

    def test_duplicate_identities_and_cyclic_suites_are_rejected(self):
        for extra in ("""
def load_tests(loader, tests, pattern):
    return unittest.TestSuite([Example('test_alpha'), Example('test_alpha')])
""", """
def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    suite.addTest(suite)
    return suite
"""):
            with self.subTest(extra=extra):
                self.replace_test(_CASE + extra)
                self.reject()

    def test_invalid_identity_types_encodings_and_lengths_are_rejected(self):
        for value in ("''", "True", "'x' * 4097", "'é' * 2049", "'\\ud800'",
                      "'unittest.loader._FailedTest.forged'"):
            with self.subTest(value=value):
                self.replace_test("import unittest\nclass Example(unittest.TestCase):\n"
                                  "    def id(self): return " + value + "\n"
                                  "    def test_example(self): raise AssertionError('body ran')\n")
                self.reject()

    def test_test_count_and_result_json_limits_are_enforced(self):
        for setting, value in (("MAX_TESTS", 1), ("MAX_OUTPUT_BYTES", 8),
                               ("MAX_INPUT_BYTES", 8)):
            with self.subTest(setting=setting), mock.patch.object(collector, setting, value):
                self.reject()

    def test_existing_ignored_bytecode_is_rejected_before_import(self):
        marker = self.base / "imported"
        self.write(".gitignore", "__pycache__/\n")
        source = self.write("ci/project/helper.py",
                            f"from pathlib import Path\nPath({str(marker)!r}).touch()\n")
        self.replace_test("import helper\n" + _CASE)
        py_compile.compile(str(source), doraise=True)
        self.assertTrue(Path(importlib.util.cache_from_source(str(source))).exists())
        self.reject()
        self.assertFalse(marker.exists())

    def test_external_imports_are_rejected_before_their_code_executes(self):
        outside = self.base / "outside"
        outside.mkdir()
        marker = self.base / "outside-executed"
        module = outside / "outside_helper.py"
        module.write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n")
        forms = (
            f"import sys\nsys.path.insert(0, {str(outside)!r})\nimport outside_helper\n",
            "import importlib.util\n"
            f"spec = importlib.util.spec_from_file_location('outside_helper', {str(module)!r})\n"
            "module = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(module)\n",
        )
        for code in forms:
            with self.subTest(code=code):
                self.replace_test(code + _CASE)
                self.reject()
                self.assertFalse(marker.exists())

    def test_external_sourceless_bytecode_is_rejected_before_execution(self):
        marker = self.base / "outside-executed"
        source = self.base / "outside.py"
        source.write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n")
        bytecode = self.base / "outside.pyc"
        py_compile.compile(str(source), cfile=str(bytecode), doraise=True)
        source.unlink()
        self.replace_test("import importlib.util\n"
                          f"spec = importlib.util.spec_from_file_location('outside', {str(bytecode)!r})\n"
                          "module = importlib.util.module_from_spec(spec)\n"
                          "spec.loader.exec_module(module)\n" + _CASE)
        self.reject()
        self.assertFalse(marker.exists())

    def test_initialized_gitlink_is_allowed_but_its_python_cannot_be_imported(self):
        vendor = self.root / "vendor"
        vendor.mkdir()
        self.git("init", "-q", root=vendor)
        marker = self.base / "vendor-imported"
        (vendor / "vendor_helper.py").write_text(
            f"from pathlib import Path\nPath({str(marker)!r}).touch()\n")
        self.git("add", ".", root=vendor)
        self.git("commit", "-qm", "native fixture", root=vendor)
        pin = self.git("rev-parse", "HEAD", root=vendor).decode().strip()
        self.git("update-index", "--add", "--cacheinfo", "160000", pin, "vendor")
        self.commit()
        self.assertEqual(len(self.collect()), 2)
        self.replace_test("import sys\nfrom pathlib import Path\n"
                          "sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'vendor'))\n"
                          "import vendor_helper\n" + _CASE)
        self.reject()
        self.assertFalse(marker.exists())

    def test_non_json_descriptor_output_is_rejected(self):
        self.replace_test("import os\nos.write(1, b'not-json')\n" + _CASE)
        self.reject()

    def test_diagnostic_output_limit_is_enforced(self):
        self.replace_test("import os\nos.write(2, b'x' * 100000)\n" + _CASE)
        with mock.patch.object(collector, "MAX_DIAGNOSTIC_BYTES", 1024), \
                self.assertRaisesRegex(collector.ReplayCollectError, "diagnostics"):
            self.collect()

    def test_descriptor_output_cannot_bypass_the_json_byte_limit(self):
        self.replace_test("import os\nos.write(1, b'x' * 100000)\n" + _CASE)
        with mock.patch.object(collector, "MAX_OUTPUT_BYTES", 1024), \
                self.assertRaisesRegex(collector.ReplayCollectError, "output byte limit"):
            self.collect()

    def test_timeout_kills_and_reaps_the_collection_process(self):
        self.replace_test("import time\ntime.sleep(30)\n" + _CASE)
        processes = []
        real_popen = subprocess.Popen

        def launch(command, *arguments, **keywords):
            process = real_popen(command, *arguments, **keywords)
            if "-I" in command:
                processes.append(process)
            return process

        start = time.monotonic()
        with mock.patch.object(collector, "MAX_CHILD_SECONDS", 0.2), \
                mock.patch.object(collector.subprocess, "Popen", side_effect=launch), \
                self.assertRaisesRegex(collector.ReplayCollectError, "timed out"):
            self.collect()
        self.assertLess(time.monotonic() - start, 5)
        self.assertEqual(len(processes), 1)
        self.assertIsNotNone(processes[0].returncode)
        self.assertTrue(processes[0].stdout.closed)
        self.assertTrue(processes[0].stderr.closed)

    def test_timeout_also_terminates_inherited_descendants(self):
        pid_path = self.base / "descendant.pid"
        self.replace_test("import subprocess, sys, time\nfrom pathlib import Path\n"
                          "child = subprocess.Popen([sys.executable, '-I', '-B', '-S', '-c', "
                          "'import time; time.sleep(30)'])\n"
                          f"Path({str(pid_path)!r}).write_text(str(child.pid))\n"
                          "time.sleep(30)\n" + _CASE)
        with mock.patch.object(collector, "MAX_CHILD_SECONDS", 0.4), \
                self.assertRaisesRegex(collector.ReplayCollectError, "timed out"):
            self.collect()
        pid = int(pid_path.read_text())
        state_path = Path("/proc") / str(pid) / "stat"
        deadline = time.monotonic() + 1
        while state_path.exists() and time.monotonic() < deadline:
            try:
                state = state_path.read_text().partition(")")[2].split()[0]
            except FileNotFoundError:
                break
            if state == "Z":
                break
            time.sleep(0.01)
        else:
            if state_path.exists():
                os.kill(pid, signal.SIGKILL)
                self.fail("collection descendant remained running after cleanup")

    def test_parent_revalidates_the_complete_child_json(self):
        malformed = (b"", b"{}", b"[]", b"[true]", b'["same","same"]',
                     b'["valid"] trailing', b'["\\ud800"]', b"[NaN]", b"\xff")
        for payload in malformed:
            with self.subTest(payload=payload), mock.patch.object(collector, "_run_child", return_value=payload):
                self.reject()
        with mock.patch.object(collector, "MAX_OUTPUT_BYTES", 2):
            with self.assertRaises(collector.ReplayCollectError):
                collector._decode(json.dumps(["example"]).encode())


if __name__ == "__main__":
    unittest.main()
