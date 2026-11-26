# SPDX-License-Identifier: Apache-2.0
"""Host-only launcher checks; a scoped metadata mock never executes native code."""

import copy
import importlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

if __package__:
    from .test_p05_bundle import BundleFixture, PACKAGE, ROOT, isolated_package
else:
    from test_p05_bundle import BundleFixture, PACKAGE, ROOT, isolated_package


class LauncherImportTests(unittest.TestCase):
    def test_importing_launcher_and_package_never_requests_native_extension(self):
        code = """
import importlib.abc, sys
class RejectNative(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'vortex_ai._native':
            raise AssertionError('eager native import')
sys.path.insert(0, sys.argv[1])
sys.meta_path.insert(0, RejectNative())
import vortex_ai
import vortex_ai.launch
assert 'vortex_ai._native' not in sys.modules
print('no eager native import')
"""
        result = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(PACKAGE.parent)],
                                cwd=ROOT.parent, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "no eager native import\n")

    def test_module_sandbox_restores_existing_package_and_native_objects(self):
        original = {name: value for name, value in tuple(sys.modules.items())
                    if name == "vortex_ai" or name.startswith("vortex_ai.")}
        with isolated_package():
            sentinel = types.ModuleType("vortex_ai._native")
            sys.modules["vortex_ai._native"] = sentinel
            with isolated_package():
                self.assertNotIn("vortex_ai._native", sys.modules)
                sys.modules["vortex_ai._native"] = types.ModuleType("vortex_ai._native")
            self.assertIs(sys.modules["vortex_ai._native"], sentinel)
        restored = {name: value for name, value in tuple(sys.modules.items())
                    if name == "vortex_ai" or name.startswith("vortex_ai.")}
        self.assertEqual(restored, original)


class LauncherTestCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="p05-launcher-host-only-")
        self.addCleanup(temporary.cleanup)
        self.fixture = BundleFixture(temporary.name)
        self.package = self.enterContext(isolated_package())
        self.launch = importlib.import_module("vortex_ai.launch")
        self.native = types.ModuleType("vortex_ai._native")
        self.native.build_info = mock.Mock(return_value=self.fixture.identity)
        self.native.__getattr__ = lambda name: self.fail("native execution requested: " + name)
        self.package._native = self.native
        sys.modules["vortex_ai._native"] = self.native
        self.script = self.fixture.area / "installed check.py"
        self.script.write_text("raise SystemExit(0)\n", encoding="utf-8")
        self.command = ["--bundle", str(self.fixture.root), "--", str(self.script)]
        self.environment = self.enterContext(mock.patch.dict(os.environ, {"PATH": os.defpath}, clear=True))
        self.stderr = io.StringIO()
        self.enterContext(mock.patch.object(sys, "stderr", self.stderr))

    def run_main(self, *, command=None, returncode=0):
        with mock.patch.object(self.launch, "_run_child", return_value=returncode) as start:
            code = self.launch.main(self.command if command is None else command)
        return code, start


class LauncherEnvironmentTests(LauncherTestCase):
    def test_bundle_path_cannot_change_dynamic_loader_search_semantics(self):
        for suffix in ("left:right", "left;right", "$ORIGIN", "${LIB}", "$PLATFORM", "line\nbreak"):
            moved = self.fixture.area / suffix
            self.fixture.root.rename(moved)
            try:
                with self.subTest(suffix=suffix):
                    code, start = self.run_main(command=["--bundle", str(moved), "--", str(self.script)])
                    self.assertEqual(code, 2)
                    start.assert_not_called()
                    self.assertIn("loader separators or expansion tokens", self.stderr.getvalue())
            finally:
                moved.rename(self.fixture.root)

    def test_clean_environment_uses_exact_canonical_bundle_directory(self):
        original = {"PATH": "/kept/bin", "HOME": "/kept/home", "USER_SETTING": "unchanged"}
        saved = original.copy()
        returned = self.launch.verified_environment(self.fixture.root, environment=original)
        self.assertEqual(original, saved)
        self.assertIsNot(returned, original)
        self.assertEqual(returned, dict(original, VORTEX_DRIVER="simx",
                                       LD_LIBRARY_PATH=str(self.fixture.root.resolve() / "lib")))
        self.native.build_info.assert_called_once_with()

    def test_parent_loader_overrides_are_rejected_before_native_import_or_file_reads(self):
        for key in ("LD_PRELOAD", "LD_AUDIT", "LD_LIBRARY_PATH"):
            for value in ("/untrusted", ":", " "):
                with self.subTest(key=key, value=value):
                    self.native.build_info.reset_mock()
                    with mock.patch.object(self.launch._bundle, "read_manifest") as read:
                        with self.assertRaisesRegex(self.launch._bundle.BundleError, key):
                            self.launch.verified_environment(self.fixture.root, environment={key: value})
                    read.assert_not_called()
                    self.native.build_info.assert_not_called()

    def test_conflicting_driver_is_rejected_before_loading_metadata(self):
        for value in ("rtlsim", "xrt", "SIMX", "simx:other", " "):
            with self.subTest(value=value):
                self.native.build_info.reset_mock()
                with self.assertRaisesRegex(self.launch._bundle.BundleError, "conflicts"):
                    self.launch.verified_environment(self.fixture.root,
                                                     environment={"VORTEX_DRIVER": value})
                self.native.build_info.assert_not_called()

    def test_absent_empty_and_matching_driver_values_are_allowed(self):
        for value in (None, "", "simx"):
            with self.subTest(value=value):
                env = {} if value is None else {"VORTEX_DRIVER": value}
                result = self.launch.verified_environment(self.fixture.root, environment=env)
                self.assertEqual(result["VORTEX_DRIVER"], "simx")

    def test_empty_loader_overrides_and_python_build_selectors_are_scrubbed(self):
        original = {"LD_PRELOAD": "", "LD_AUDIT": "", "LD_LIBRARY_PATH": "",
                    "PYTHONPATH": "/untrusted/python", "PYTHONHOME": "/untrusted/home",
                    "VORTEX_AI_BUNDLE": "/untrusted/rebind", "KEEP": "yes"}
        saved = original.copy()
        result = self.launch.verified_environment(self.fixture.root, environment=original)
        self.assertEqual(original, saved)
        for key in ("LD_PRELOAD", "LD_AUDIT", "PYTHONPATH", "PYTHONHOME", "VORTEX_AI_BUNDLE"):
            self.assertNotIn(key, result)
        self.assertEqual(result["LD_LIBRARY_PATH"], str(self.fixture.root / "lib"))
        self.assertEqual(result["KEEP"], "yes")

    def test_default_environment_is_copied_without_mutating_parent(self):
        os.environ.update(PYTHONPATH="/parent/python", VORTEX_AI_BUNDLE="/parent/build", KEEP="value")
        before = dict(os.environ)
        result = self.launch.verified_environment(self.fixture.root)
        self.assertEqual(dict(os.environ), before)
        self.assertNotIn("PYTHONPATH", result)
        self.assertNotIn("VORTEX_AI_BUNDLE", result)
        self.assertEqual(result["KEEP"], "value")

    def test_compiled_identity_requires_exact_api_one_shape(self):
        valid = self.fixture.identity
        candidates = [None, [], "identity", True, {}, dict(valid, extra="value")]
        candidates += [{key: value for key, value in valid.items() if key != missing}
                       for missing in valid]
        candidates += [dict(valid, binding_api=value) for value in (True, False, 0, 2, 1.0, "1", None)]
        candidates += [dict(valid, bundle_sha256=value) for value in ("", None, False)]
        for identity in candidates:
            with self.subTest(identity=identity):
                self.native.build_info.return_value = identity
                with mock.patch.object(self.launch._bundle, "read_manifest") as read:
                    with self.assertRaises(self.launch._bundle.BundleError):
                        self.launch.verified_environment(self.fixture.root, environment={})
                read.assert_not_called()

    def test_compiled_manifest_and_source_pins_must_both_match(self):
        for key in ("bundle_sha256", "source_sha256"):
            for value in ("0" * 64, "A" * 64, 1, [], {}, None):
                with self.subTest(key=key, value=value):
                    self.native.build_info.return_value = dict(self.fixture.identity, **{key: value})
                    with mock.patch.object(self.launch._bundle, "validate_files") as checked:
                        with self.assertRaises(self.launch._bundle.BundleError):
                            self.launch.verified_environment(self.fixture.root, environment={})
                    checked.assert_not_called()

    def test_rehashed_changed_manifest_cannot_replace_compiled_pin(self):
        data = copy.deepcopy(self.fixture.manifest)
        data["format"] = data["native_binding"]["format"] = "bf16"
        self.fixture.write(data, rebind=True)
        with self.assertRaisesRegex(self.launch._bundle.BundleError, "immutable pin"):
            self.launch.verified_environment(self.fixture.root, environment={})

    def test_read_or_native_metadata_failures_never_create_child_environment(self):
        for error in (ImportError("missing extension"), RuntimeError("metadata failed")):
            with self.subTest(error=error):
                self.native.build_info.side_effect = error
                code, start = self.run_main()
                self.assertEqual(code, 2)
                start.assert_not_called()


class LauncherStartupTests(LauncherTestCase):
    def test_compiled_pin_and_every_file_are_checked_before_child_start(self):
        events = []
        bundle = self.launch._bundle
        read, verify, record = bundle.read_manifest, bundle.validate_files, bundle.file_record

        def identity():
            events.append("compiled-pin")
            return self.fixture.identity

        def read_manifest(root):
            events.append("manifest")
            return read(root)

        def file_record(root, relative, **kwargs):
            value = record(root, relative, **kwargs)
            events.append(relative)
            return value

        def validate_files(root, data):
            verify(root, data)
            events.append("all-files-verified")

        def start_child(*args, **kwargs):
            self.assertEqual(events[-1], "all-files-verified")
            for relative in bundle.ROLES.values():
                self.assertIn(relative, events)
            events.append("child")
            return 0

        self.native.build_info.side_effect = identity
        with mock.patch.object(bundle, "read_manifest", side_effect=read_manifest), \
                mock.patch.object(bundle, "file_record", side_effect=file_record), \
                mock.patch.object(bundle, "validate_files", side_effect=validate_files), \
                mock.patch.object(self.launch, "_run_child", side_effect=start_child) as start:
            self.assertEqual(self.launch.main(self.command), 0)
        start.assert_called_once()
        self.assertEqual(events[:2], ["compiled-pin", "manifest"])
        self.assertEqual(events[-2:], ["all-files-verified", "child"])

    def test_each_mutated_artifact_blocks_subprocess_startup(self):
        for relative in self.launch._bundle.ROLES.values():
            with self.subTest(relative=relative):
                path = self.fixture.root / relative
                original = path.read_bytes()
                path.write_bytes(original + b"mutation")
                try:
                    code, start = self.run_main()
                    self.assertEqual(code, 2)
                    start.assert_not_called()
                finally:
                    path.write_bytes(original)

    def test_extra_library_and_symlink_fail_before_subprocess_startup(self):
        extra = self.fixture.root / "lib/extra.so"
        extra.write_bytes(b"inert")
        code, start = self.run_main()
        self.assertEqual(code, 2)
        start.assert_not_called()
        extra.unlink()
        module = self.fixture.root / "kernel.vxbin"
        target = self.fixture.area / "external-module"
        module.rename(target)
        module.symlink_to(target)
        code, start = self.run_main()
        self.assertEqual(code, 2)
        start.assert_not_called()

    def test_invalid_manifest_and_mismatched_pin_block_subprocess_startup(self):
        manifest = self.fixture.root / "manifest.json"
        raw = manifest.read_bytes()
        for replacement in (b"{}\n", raw + b" "):
            with self.subTest(replacement=replacement[:10]):
                manifest.write_bytes(replacement)
                code, start = self.run_main()
                self.assertEqual(code, 2)
                start.assert_not_called()
        manifest.write_bytes(raw)
        self.native.build_info.return_value = dict(self.fixture.identity, bundle_sha256="0" * 64)
        code, start = self.run_main()
        self.assertEqual(code, 2)
        start.assert_not_called()

    def test_loader_environment_failure_blocks_subprocess_startup(self):
        for key in ("LD_PRELOAD", "LD_AUDIT", "LD_LIBRARY_PATH", "VORTEX_DRIVER"):
            with self.subTest(key=key), mock.patch.dict(os.environ, {key: "conflict"}):
                code, start = self.run_main()
                self.assertEqual(code, 2)
                start.assert_not_called()

    def test_shared_qualification_syntax_forwards_arguments_as_one_script(self):
        args = ["--request", str(self.fixture.area / "request file.json"),
                "--output", str(self.fixture.area / "observations.json"), "-c", "literal argument"]
        code, start = self.run_main(command=self.command + args, returncode=7)
        self.assertEqual(code, 7)
        call = start.call_args
        self.assertEqual(call.args[0], [sys.executable, "-I", "-B", str(self.script.resolve()), *args])
        self.assertEqual(set(call.kwargs), {"env"})
        self.assertEqual(call.kwargs["env"]["LD_LIBRARY_PATH"], str(self.fixture.root / "lib"))

    def test_missing_script_and_interpreter_modes_are_parser_errors(self):
        prefix = ["--bundle", str(self.fixture.root), "--"]
        for args in ([], ["-c", "print('not allowed')"], ["-m", "module"], ["-"], ["--version"]):
            with self.subTest(args=args):
                with mock.patch.object(self.launch, "_run_child") as start:
                    with self.assertRaises(SystemExit) as error:
                        self.launch.main(prefix + args)
                self.assertEqual(error.exception.code, 2)
                start.assert_not_called()
        self.native.build_info.assert_not_called()

    def test_missing_directory_and_fifo_scripts_fail_without_verification_or_child(self):
        fifo = self.fixture.area / "script-fifo"
        os.mkfifo(fifo)
        for path in (self.fixture.area / "does-not-exist.py", self.fixture.area, fifo):
            with self.subTest(path=path):
                code, start = self.run_main(command=["--bundle", str(self.fixture.root), "--", str(path)])
                self.assertEqual(code, 2)
                start.assert_not_called()
        self.native.build_info.assert_not_called()

    def test_script_symlink_is_resolved_to_the_selected_regular_script(self):
        link = self.fixture.area / "selected-script.py"
        link.symlink_to(self.script)
        code, start = self.run_main(command=["--bundle", str(self.fixture.root), "--", str(link)])
        self.assertEqual(code, 0)
        self.assertEqual(start.call_args.args[0][3], str(self.script.resolve()))

    def test_child_status_is_preserved_and_signal_status_uses_shell_convention(self):
        for native_status, expected in ((0, 0), (1, 1), (23, 23), (127, 127), (-15, 143), (-9, 137)):
            with self.subTest(native_status=native_status):
                code, start = self.run_main(returncode=native_status)
                self.assertEqual(code, expected)
                start.assert_called_once()

    def test_subprocess_start_error_returns_actionable_launcher_failure(self):
        with mock.patch.object(self.launch.subprocess, "Popen", side_effect=OSError("cannot start Python")):
            self.assertEqual(self.launch.main(self.command), 2)
        self.assertIn("vortex_ai.launch: cannot start Python", self.stderr.getvalue())

    def test_real_child_gets_isolated_flags_scrubbed_environment_and_exact_exit_code(self):
        self.script.write_text(
            "import json, os, signal, sys\n"
            "signal.alarm(5)\n"
            "print(json.dumps({'argv': sys.argv[1:], 'isolated': sys.flags.isolated,\n"
            " 'ignore_environment': sys.flags.ignore_environment,\n"
            " 'no_bytecode': sys.flags.dont_write_bytecode,\n"
            " 'env': {key: os.environ.get(key) for key in ('LD_LIBRARY_PATH', 'VORTEX_DRIVER',\n"
            " 'PYTHONPATH', 'PYTHONHOME', 'VORTEX_AI_BUNDLE', 'KEEP')},\n"
            " 'native_imported': 'vortex_ai._native' in sys.modules}))\n"
            "raise SystemExit(37)\n", encoding="utf-8")
        os.environ.update(PYTHONPATH="/untrusted/python", PYTHONHOME="/untrusted/home",
                          VORTEX_AI_BUNDLE="/untrusted/build", KEEP="preserved")
        real_popen = subprocess.Popen
        stdout = self.enterContext(tempfile.TemporaryFile(mode="w+"))
        stderr = self.enterContext(tempfile.TemporaryFile(mode="w+"))

        def start_child(argv, **kwargs):
            return real_popen(argv, **kwargs, stdout=stdout, stderr=stderr)

        arguments = ["--request", "literal request", "--output", "literal output"]
        with mock.patch.object(self.launch.subprocess, "Popen", side_effect=start_child) as start:
            code = self.launch.main(self.command + arguments)
        self.assertEqual(code, 37)
        start.assert_called_once()
        stderr.seek(0)
        self.assertEqual(stderr.read(), "")
        stdout.seek(0)
        value = json.loads(stdout.read())
        self.assertEqual(value["argv"], arguments)
        self.assertEqual((value["isolated"], value["ignore_environment"], value["no_bytecode"]), (1, 1, 1))
        self.assertFalse(value["native_imported"])
        self.assertEqual(value["env"], {
            "LD_LIBRARY_PATH": str(self.fixture.root / "lib"), "VORTEX_DRIVER": "simx",
            "PYTHONPATH": None, "PYTHONHOME": None, "VORTEX_AI_BUNDLE": None, "KEEP": "preserved",
        })


if __name__ == "__main__":
    unittest.main()
