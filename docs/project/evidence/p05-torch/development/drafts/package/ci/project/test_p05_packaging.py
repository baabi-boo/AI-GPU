# SPDX-License-Identifier: Apache-2.0
"""Fast packaging contract tests; no compiler, setuptools or native loader runs.

Only setuptools' command boundary is replaced when loading the real setup.py.
The production inventory, receipt, header and payload validators run unchanged
against independent source snapshots and labeled nonexecutable bundle bytes.
Real sdist/wheel/install checks require the pinned build tools and are a
separate packaging qualification, not a prerequisite of governance discovery.
"""

import copy
import hashlib
import importlib.machinery
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import tomllib
import types
import unittest
from unittest import mock

from test_p05_bundle import BUNDLE, BundleFixture, ROOT, canonical


def load_setup(source, *, bundle=None):
    """Capture setup's declarations without importing third-party build tools."""
    captured = mock.Mock()
    modules = {name: types.ModuleType(name) for name in (
        "setuptools", "setuptools.command", "setuptools.command.bdist_wheel",
        "setuptools.command.build_ext", "setuptools.command.build_py",
        "setuptools.command.sdist",
    )}
    modules["setuptools"].__path__ = []
    modules["setuptools.command"].__path__ = []
    modules["setuptools"].setup = captured
    modules["setuptools"].Extension = lambda name, **kwargs: types.SimpleNamespace(
        name=name, **kwargs)
    bases = {}
    for name in ("bdist_wheel", "build_ext", "build_py", "sdist"):
        # These mocks only observe forwarding. They never simulate compilation,
        # source copying or archive creation, which belong to the real build.
        base = type(name, (), {method: mock.Mock() for method in (
            "run", "finalize_options", "write_wheelfile", "make_release_tree")})
        bases[name] = base
        setattr(modules["setuptools.command." + name], name, base)
    environment = dict(os.environ)
    environment.pop("VORTEX_AI_BUNDLE", None)
    if bundle is not None:
        environment["VORTEX_AI_BUNDLE"] = str(bundle)
    with mock.patch.dict(sys.modules, modules), \
            mock.patch.dict(os.environ, environment, clear=True):
        namespace = runpy.run_path(str(source / "setup.py"))
    captured.assert_called_once()
    return types.SimpleNamespace(namespace=namespace, declarations=captured.call_args.kwargs,
                                 bases=bases, identity=namespace["IDENTITY"])


class PackagingTestCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="p05-packaging-host-only-")
        self.addCleanup(temporary.cleanup)
        self.fixture = BundleFixture(temporary.name)
        self.area, self.source = self.fixture.area, self.fixture.source
        for relative in ("LICENSE", "python/README.md"):
            target = self.source / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / relative).read_bytes())
        self.loaded = load_setup(self.source)

    def prepare(self, *, bound=True):
        loaded = load_setup(self.source, bundle=self.fixture.root if bound else None)
        loaded.identity.stage(self.source / "python/p05_build")
        (self.source / "PKG-INFO").write_text("Metadata-Version: 2.4\nName: vortex-ai\n")
        return loaded


class PackagingIdentityTests(PackagingTestCase):
    def test_unbound_identity_matches_independently_hashed_sources(self):
        identity = self.loaded.identity
        expected = self.fixture.manifest["binding_sources"]
        self.assertEqual(identity.sources, expected)
        self.assertEqual(identity.source_bytes, canonical(expected))
        self.assertEqual(identity.source_sha256, hashlib.sha256(canonical(expected)).hexdigest())
        self.assertEqual(identity.bundle_sha256, "")
        self.assertIsNone(identity.manifest)
        self.assertIsNone(identity.manifest_bytes)
        self.assertIn(identity.source_sha256.encode(), identity.header_bytes)
        self.assertIn(b'inline constexpr char bundle_sha256[] = "";', identity.header_bytes)
        self.assertEqual(identity.header_bytes.count(b'{"", "", "", 0ULL}'), 6)
        self.assertFalse((self.source / "python/p05_build").exists())

    def test_binding_inventory_covers_launcher_and_optional_framework_adapter(self):
        expected = {row["path"] for row in self.loaded.identity.sources
                    if row["path"].startswith("python/vortex_ai/")}
        self.assertTrue({"python/vortex_ai/launch.py",
                         "python/vortex_ai/torch_ops.py"}.issubset(expected))
        includes = {line.removeprefix("include ")
                    for line in (self.source / "MANIFEST.in").read_text().splitlines()
                    if line.startswith("include ")}
        self.assertTrue(expected.issubset(includes))
        self.assertEqual(expected, {path.relative_to(ROOT).as_posix()
                                    for path in (ROOT / "python/vortex_ai").glob("*.py")})
        self.assertEqual(self.loaded.declarations["ext_modules"][0].name, "vortex_ai._native")

    def test_base_import_does_not_load_framework_or_native_dependencies(self):
        metadata = tomllib.loads((self.source / "pyproject.toml").read_text())
        self.assertEqual(metadata["project"]["dependencies"], [])
        code = """
import importlib.abc
import sys

class RejectOptional(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if (fullname in ('vortex_ai._native', 'vortex_ai._bundle', 'vortex_ai.torch_ops')
                or fullname == 'torch' or fullname.startswith('torch.')):
            raise AssertionError('base import requested optional dependency: ' + fullname)

sys.path.insert(0, sys.argv[1])
sys.meta_path.insert(0, RejectOptional())
import vortex_ai
assert vortex_ai.BINDING_API == 1
assert 'torch' not in sys.modules
assert 'vortex_ai.torch_ops' not in sys.modules
print('dependency-free base import')
"""
        result = subprocess.run(
            [sys.executable, "-I", "-S", "-B", "-c", code, str(self.source / "python")],
            cwd=self.area, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "dependency-free base import\n")

    def test_optional_framework_import_reports_missing_torch_without_loading_native(self):
        code = """
import importlib.abc
import sys

class MissingTorch(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'torch':
            raise ModuleNotFoundError('No module named torch', name='torch')
        if fullname in ('vortex_ai._native', 'vortex_ai._bundle'):
            raise AssertionError('missing-framework import requested native code: ' + fullname)

sys.path.insert(0, sys.argv[1])
sys.meta_path.insert(0, MissingTorch())
import vortex_ai
try:
    import vortex_ai.torch_ops
except ImportError as error:
    message = str(error).lower()
    assert 'torch' in message and 'install' in message, message
else:
    raise AssertionError('optional framework import succeeded without torch')
assert 'vortex_ai._native' not in sys.modules
assert 'vortex_ai._bundle' not in sys.modules
print('actionable missing-framework error')
"""
        result = subprocess.run(
            [sys.executable, "-I", "-S", "-B", "-c", code, str(self.source / "python")],
            cwd=self.area, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "actionable missing-framework error\n")

    def test_loading_setup_leaves_no_imported_package_or_source_bytecode(self):
        prior = {key: value for key, value in sys.modules.items() if key.startswith("vortex_ai")}
        old_flag = sys.dont_write_bytecode
        load_setup(self.source)
        self.assertIs(sys.dont_write_bytecode, old_flag)
        self.assertEqual(prior, {key: value for key, value in sys.modules.items()
                                 if key.startswith("vortex_ai")})
        self.assertEqual(list(self.source.rglob("*.pyc")), [])

    def test_bound_identity_embeds_receipt_and_all_six_artifact_pins(self):
        loaded = load_setup(self.source, bundle=self.fixture.root)
        identity = loaded.identity
        self.assertEqual(identity.bundle_sha256, self.fixture.identity["bundle_sha256"])
        self.assertEqual(identity.manifest_bytes, (self.fixture.root / "manifest.json").read_bytes())
        self.assertEqual(identity.manifest, self.fixture.manifest)
        for row in self.fixture.manifest["artifacts"]:
            self.assertIn(('"' + row["sha256"] + '"').encode(), identity.header_bytes)
            self.assertIn(('"' + row["path"] + '"').encode(), identity.header_bytes)
        self.assertIn(identity.bundle_sha256.encode(), identity.header_bytes)

    def test_prepared_bound_source_reloads_without_original_native_bundle(self):
        identity = self.prepare().identity
        self.fixture.root.rename(self.area / "original-bundle-unavailable")
        offline = load_setup(self.source).identity
        for name in ("bundle_sha256", "source_sha256", "source_bytes",
                     "manifest_bytes", "header_bytes"):
            self.assertEqual(getattr(offline, name), getattr(identity, name), name)
        repacked = self.area / "repacked-config"
        offline.stage(repacked)
        original = self.source / "python/p05_build"
        self.assertEqual({p.name for p in repacked.iterdir()}, {p.name for p in original.iterdir()})
        for path in original.iterdir():
            self.assertEqual(path.read_bytes(), (repacked / path.name).read_bytes())

    def test_prepared_unbound_source_preserves_its_source_pin(self):
        original = self.prepare(bound=False).identity
        offline = load_setup(self.source).identity
        self.assertEqual(offline.source_sha256, original.source_sha256)
        self.assertEqual(offline.header_bytes, original.header_bytes)
        self.assertEqual(offline.bundle_sha256, "")
        self.assertEqual({p.name for p in (self.source / "python/p05_build").iterdir()},
                         {"p05_build_config.h", "source_inventory.json"})

    def test_empty_bundle_environment_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "must name a qualified bundle"):
            load_setup(self.source, bundle="")

    def test_changes_to_any_inventory_input_fail_before_build(self):
        self.prepare()
        for relative in BUNDLE.SOURCE_PATHS:
            with self.subTest(path=relative):
                target = self.source / relative
                raw = target.read_bytes()
                target.write_bytes(raw + b"\n# mutated packaging input\n")
                try:
                    with self.assertRaisesRegex(RuntimeError, "immutable source inventory"):
                        load_setup(self.source)
                finally:
                    target.write_bytes(raw)

    def test_prepared_header_inventory_and_manifest_mutations_are_rejected(self):
        self.prepare()
        directory = self.source / "python/p05_build"
        cases = (
            ("p05_build_config.h", lambda raw: raw + b"\n", "build header differs"),
            ("source_inventory.json", lambda raw: b"[]\n", "immutable source inventory"),
            ("manifest.json", lambda raw: raw + b"\n", "canonical JSON"),
        )
        for name, mutation, error in cases:
            with self.subTest(name=name):
                path = directory / name
                raw = path.read_bytes()
                path.write_bytes(mutation(raw))
                try:
                    with self.assertRaisesRegex((RuntimeError, ValueError), error):
                        load_setup(self.source)
                finally:
                    path.write_bytes(raw)

    def test_missing_config_inputs_and_additional_config_file_are_rejected(self):
        self.prepare()
        directory = self.source / "python/p05_build"
        for name in ("p05_build_config.h", "source_inventory.json", "manifest.json"):
            with self.subTest(name=name):
                path = directory / name
                raw = path.read_bytes()
                path.unlink()
                try:
                    with self.assertRaisesRegex(RuntimeError, "incomplete|build header differs"):
                        load_setup(self.source)
                finally:
                    path.write_bytes(raw)
        (directory / "unexpected").write_text("not an input\n")
        with self.assertRaisesRegex(RuntimeError, "incomplete"):
            load_setup(self.source)
        shutil.rmtree(directory)
        with self.assertRaisesRegex(RuntimeError, "missing its immutable build configuration"):
            load_setup(self.source)

    def test_extra_and_missing_package_or_native_sources_are_rejected(self):
        for relative in ("python/vortex_ai/extra.py", "python/vortex_ai/nested/extra.py",
                         "python/native/extra.cpp", "python/native/extra.h"):
            with self.subTest(extra=relative):
                path = self.source / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("// host-only extra source\n")
                try:
                    with self.assertRaisesRegex(RuntimeError, "sources differ from the binding inventory"):
                        load_setup(self.source)
                finally:
                    path.unlink()
        for relative in ("python/vortex_ai/launch.py", "python/vortex_ai/torch_ops.py"):
            path = self.source / relative
            raw = path.read_bytes()
            path.unlink()
            try:
                with self.subTest(missing=relative), self.assertRaisesRegex(
                        RuntimeError, "sources differ from the binding inventory"):
                    load_setup(self.source)
            finally:
                path.write_bytes(raw)

    def test_prepared_source_rejects_replacement_bundle_and_unbound_rebinding(self):
        self.prepare()
        data = copy.deepcopy(self.fixture.manifest)
        data["format"] = data["native_binding"]["format"] = "bf16"
        self.fixture.write(data, rebind=True)
        with self.assertRaisesRegex(RuntimeError, "cannot replace an immutable sdist pin"):
            load_setup(self.source, bundle=self.fixture.root)
        shutil.rmtree(self.source / "python/p05_build")
        (self.source / "PKG-INFO").unlink()
        self.prepare(bound=False)
        with self.assertRaisesRegex(RuntimeError, "cannot replace an immutable sdist pin"):
            load_setup(self.source, bundle=self.fixture.root)

    def test_bound_build_checks_all_native_artifacts_without_loading_them(self):
        for relative in BUNDLE.ROLES.values():
            with self.subTest(path=relative):
                path = self.fixture.root / relative
                raw = path.read_bytes()
                path.unlink()
                try:
                    with self.assertRaisesRegex(ValueError, "required file|exactly the five pinned"):
                        load_setup(self.source, bundle=self.fixture.root)
                finally:
                    path.write_bytes(raw)
        (self.fixture.root / "lib/extra.so").write_text("INERT EXTRA LIBRARY\n")
        with self.assertRaisesRegex(ValueError, "exactly the five pinned"):
            load_setup(self.source, bundle=self.fixture.root)

    def test_source_change_after_identity_is_detected(self):
        path = self.source / "python/vortex_ai/launch.py"
        path.write_bytes(path.read_bytes() + b"\n# changed after identity\n")
        with self.assertRaisesRegex(RuntimeError, "changed during the package build"):
            self.loaded.identity.assert_unchanged()


class PackagingReadTests(PackagingTestCase):
    def test_checked_bytes_uses_one_bounded_regular_file_handle(self):
        checked = self.loaded.namespace["_checked_bytes"]
        bundle = self.loaded.namespace["BUNDLE"]
        expected = (self.source / "python/vortex_ai/launch.py").read_bytes()
        with mock.patch.object(bundle.os, "open", wraps=bundle.os.open) as opened, \
                mock.patch.object(Path, "read_bytes", side_effect=AssertionError("unbounded reopen")):
            actual = checked(self.source, "python/vortex_ai/launch.py", limit=len(expected))
        self.assertEqual(actual, expected)
        opened.assert_called_once()
        flags = opened.call_args.args[1]
        for required in (os.O_NOFOLLOW, os.O_NONBLOCK, os.O_CLOEXEC):
            self.assertEqual(flags & required, required)

    def test_checked_bytes_detects_record_and_retained_bytes_disagreement(self):
        checked = self.loaded.namespace["_checked_bytes"]
        bundle = self.loaded.namespace["BUNDLE"]
        original = bundle.read_file
        for mode in ("size", "digest"):
            with self.subTest(mode=mode):
                def mismatch(root, relative, **kwargs):
                    record, raw = original(root, relative, **kwargs)
                    return record, raw + b"!" if mode == "size" else raw[:-1] + b"!"
                with mock.patch.object(bundle, "read_file", side_effect=mismatch), \
                        self.assertRaisesRegex(RuntimeError, "Build input changed while reading"):
                    checked(self.source, "python/vortex_ai/launch.py")

    def test_prepared_config_symlink_and_nonregular_inputs_are_rejected(self):
        self.prepare()
        directory = self.source / "python/p05_build"
        for name in ("p05_build_config.h", "source_inventory.json", "manifest.json"):
            path = directory / name
            raw = path.read_bytes()
            target = self.area / (name + ".external")
            target.write_bytes(raw)
            path.unlink()
            path.symlink_to(target)
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "symlink"):
                load_setup(self.source)
            path.unlink()
            path.write_bytes(raw)
        moved = self.area / "moved-config"
        directory.rename(moved)
        directory.symlink_to(moved, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, "must be a directory"):
            load_setup(self.source)

    def test_checked_bytes_rejects_empty_oversize_directory_and_fifo_without_blocking(self):
        (self.area / "empty").touch()
        (self.area / "large").write_bytes(b"12345")
        (self.area / "directory").mkdir()
        os.mkfifo(self.area / "fifo")
        code = """
import pathlib, sys
sys.path.insert(0, sys.argv[1])
from test_p05_packaging import load_setup
checked = load_setup(pathlib.Path(sys.argv[2])).namespace['_checked_bytes']
for name in ('empty', 'large', 'directory', 'fifo'):
    try:
        checked(pathlib.Path(sys.argv[3]), name, limit=4)
    except ValueError:
        continue
    raise AssertionError('accepted invalid build input: ' + name)
print('four invalid build inputs rejected without blocking')
"""
        result = subprocess.run(
            [sys.executable, "-I", "-S", "-B", "-c", code, str(ROOT / "ci/project"),
             str(self.source), str(self.area)], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "four invalid build inputs rejected without blocking\n")


class PackagingCommandTests(PackagingTestCase):
    def test_staged_compile_paths_do_not_leak_into_later_metadata(self):
        for failure in (None, RuntimeError("injected compiler failure")):
            with self.subTest(failure=failure):
                command = self.loaded.namespace["PinnedBuildExt"]()
                command.build_temp = str(self.area / "build-temp")
                command.extensions = self.loaded.declarations["ext_modules"]
                command.parallel = None
                before = [(extension.sources, extension.include_dirs, extension.depends)
                          for extension in command.extensions]
                self.loaded.bases["build_ext"].run.side_effect = failure
                if failure is None:
                    command.run()
                else:
                    with self.assertRaisesRegex(RuntimeError, "injected compiler failure"):
                        command.run()
                for extension, (sources, includes, depends) in zip(command.extensions, before):
                    self.assertIs(extension.sources, sources)
                    self.assertIs(extension.include_dirs, includes)
                    self.assertIs(extension.depends, depends)
                    self.assertTrue(all(not Path(path).is_absolute() for path in extension.sources))

    def test_generated_receipt_precedes_stale_source_headers(self):
        name = "p05_build_config.h"
        shadow = self.source / "sw/runtime/ai" / name
        shadow.write_text("#error stale receipt must not be selected\n")
        (shadow.parent / "vortex2.h").write_text("#error stale ABI must not be selected\n")
        (shadow.parent / "array").write_text("#error stale system header must not be selected\n")
        command = self.loaded.namespace["PinnedBuildExt"]()
        command.build_temp = str(self.area / "build-temp")
        command.extensions = self.loaded.declarations["ext_modules"]
        command.parallel = None
        selected = []

        def observe_compiler_search():
            for extension in command.extensions:
                candidates = [Path(extension.sources[1]).parent / name]
                candidates.extend(Path(path) / name for path in extension.include_dirs)
                header = next(path for path in candidates if path.is_file())
                selected.append(header.read_bytes())
                self.assertIn(str(header), extension.depends)
                for source in extension.sources:
                    self.assertTrue(Path(source).is_relative_to(self.area / "build-temp"))
                    self.assertFalse(Path(source).is_relative_to(self.source))
                abi = [Path(path) / "vortex2.h" for path in extension.include_dirs]
                selected_abi = next(path for path in abi if path.is_file())
                self.assertEqual(selected_abi.read_bytes(),
                                 (self.source / "sw/runtime/include/vortex2.h").read_bytes())
                self.assertFalse(any((Path(path) / "array").exists()
                                     for path in extension.include_dirs))

        self.loaded.bases["build_ext"].run.side_effect = observe_compiler_search
        command.run()
        self.assertEqual(selected, [self.loaded.identity.header_bytes])
        self.assertTrue(command.force)
        self.assertEqual(command.parallel, 1)

    def test_python_copy_is_forced_and_checks_source_before_and_after(self):
        command = self.loaded.namespace["PinnedBuildPy"]()
        observed = []
        self.loaded.bases["build_py"].run.side_effect = lambda: observed.append(command.force)
        command.run()
        self.assertEqual(observed, [True])
        self.loaded.bases["build_py"].run.side_effect = lambda: (
            self.source / "python/vortex_ai/launch.py").write_text("# changed during copy\n")
        with self.assertRaisesRegex(RuntimeError, "changed during the package build"):
            command.run()

    def test_bound_wheel_tag_uses_complete_pin_and_rejects_an_override(self):
        loaded = load_setup(self.source, bundle=self.fixture.root)
        expected = "1" + self.fixture.identity["bundle_sha256"]
        for requested in (None, "", expected):
            command = loaded.namespace["PinnedWheel"]()
            command.build_number = requested
            command.finalize_options()
            self.assertEqual(command.build_number, expected)
        command.build_number = expected[:-1]
        with self.assertRaisesRegex(RuntimeError, "complete bundle pin"):
            command.finalize_options()

    def test_wheel_skip_build_cannot_reuse_an_earlier_extension_pin(self):
        command = self.loaded.namespace["PinnedWheel"]()
        command.skip_build = True
        with self.assertRaisesRegex(RuntimeError, "fresh extension build"):
            command.run()
        self.loaded.bases["bdist_wheel"].run.assert_not_called()

    def payload(self):
        root = self.area / "wheel-payload"
        root.mkdir()
        for row in self.loaded.identity.sources:
            if row["path"].startswith("python/vortex_ai/"):
                target = root / row["path"].removeprefix("python/")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((self.source / row["path"]).read_bytes())
        native = "vortex_ai/_native" + importlib.machinery.EXTENSION_SUFFIXES[0]
        (root / native).write_bytes(b"INERT HOST-ONLY PAYLOAD; NOT AN EXTENSION\n")
        metadata = root / "vortex_ai-0.1.0.dist-info"
        metadata.mkdir()
        (metadata / "METADATA").write_text("Name: vortex-ai\n")
        command = self.loaded.namespace["PinnedWheel"]()
        command.bdist_dir = str(root)
        command.get_finalized_command = mock.Mock(return_value=types.SimpleNamespace(
            get_ext_filename=mock.Mock(return_value=native)))
        return command, root, metadata, native

    def test_exact_wheel_payload_accepts_only_current_python_bytes_and_one_extension(self):
        command, root, metadata, native = self.payload()
        command.write_wheelfile(str(metadata), generator="host-only-test")
        self.loaded.bases["bdist_wheel"].write_wheelfile.assert_called_once_with(
            str(metadata), generator="host-only-test")
        self.assertFalse((root / native).read_bytes().startswith(b"\x7fELF"))

    def test_wheel_rejects_extra_payload_and_missing_launcher_or_adapter(self):
        command, root, metadata, _ = self.payload()
        for relative in ("unexpected.py", "vortex_ai/extra.so", "vortex_ai/extra.py"):
            path = root / relative
            path.write_text("INERT EXTRA PAYLOAD\n")
            with self.subTest(extra=relative), self.assertRaisesRegex(RuntimeError, "wheel payload differs"):
                command.write_wheelfile(str(metadata))
            path.unlink()
        for relative in ("vortex_ai/launch.py", "vortex_ai/torch_ops.py"):
            path = root / relative
            raw = path.read_bytes()
            path.unlink()
            try:
                with self.subTest(missing=relative), self.assertRaisesRegex(RuntimeError, "wheel payload differs"):
                    command.write_wheelfile(str(metadata))
            finally:
                path.write_bytes(raw)
        self.loaded.bases["bdist_wheel"].write_wheelfile.assert_not_called()

    def test_wheel_rejects_stale_python_bytes_and_symlinked_extension(self):
        command, root, metadata, native = self.payload()
        for relative in ("vortex_ai/launch.py", "vortex_ai/torch_ops.py"):
            path = root / relative
            raw = path.read_bytes()
            path.write_bytes(raw + b"\n# stale payload\n")
            try:
                with self.subTest(stale=relative), self.assertRaisesRegex(RuntimeError, "Python source differs"):
                    command.write_wheelfile(str(metadata))
            finally:
                path.write_bytes(raw)
        extension = root / native
        moved = self.area / "external-inert-extension"
        extension.rename(moved)
        extension.symlink_to(moved)
        with self.assertRaisesRegex(ValueError, "symlink"):
            command.write_wheelfile(str(metadata))

    def test_sdist_rejects_existing_staging_directory_and_missing_inventory_member(self):
        command = self.loaded.namespace["PinnedSDist"]()
        existing = self.area / "existing-release"
        existing.mkdir()
        with self.assertRaisesRegex(RuntimeError, "Refusing to reuse"):
            command.make_release_tree(str(existing), list(BUNDLE.SOURCE_PATHS))
        command.get_finalized_command = mock.Mock(return_value=types.SimpleNamespace(
            egg_info="python/vortex_ai.egg-info"))
        for missing in ("python/vortex_ai/launch.py", "python/vortex_ai/torch_ops.py"):
            files = [path for path in BUNDLE.SOURCE_PATHS if path != missing]
            with self.subTest(missing=missing), self.assertRaisesRegex(RuntimeError, "omits a binding build input"):
                command.make_release_tree(str(self.area / "new-release"), files)
        self.loaded.bases["sdist"].make_release_tree.assert_not_called()


if __name__ == "__main__":
    unittest.main()
