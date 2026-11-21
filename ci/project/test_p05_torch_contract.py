# SPDX-License-Identifier: Apache-2.0
"""Dependency-free checks for the optional framework import and package boundary."""

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[2]
MODULE = "python/vortex_ai/torch_ops.py"


class TorchOptionalContractTests(unittest.TestCase):
    def probe(self, body):
        prefix = "import sys\nsys.path.insert(0, sys.argv[1])\n"
        result = subprocess.run([sys.executable, "-I", "-B", "-c", prefix + body,
                                 str(ROOT / "python")], cwd=ROOT,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_base_import_never_requests_torch_or_native_runtime(self):
        self.probe("""
import importlib.abc
class BlockOptional(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'torch' or fullname.startswith('torch.') or fullname in (
                'vortex_ai._native', 'vortex_ai._bundle', 'vortex_ai.torch_ops'):
            raise AssertionError('base import requested optional code: ' + fullname)
sys.meta_path.insert(0, BlockOptional())
import vortex_ai
assert vortex_ai.BINDING_API == 1
assert 'torch' not in sys.modules
assert 'vortex_ai.torch_ops' not in sys.modules
assert 'vortex_ai._native' not in sys.modules
""")

    def test_missing_torch_has_actionable_error_without_native_loading(self):
        self.probe("""
import importlib.abc
class MissingTorch(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'torch':
            raise ModuleNotFoundError('torch deliberately absent', name='torch')
        if fullname == 'vortex_ai._native':
            raise AssertionError('optional import loaded a native runtime')
sys.meta_path.insert(0, MissingTorch())
import vortex_ai
try:
    import vortex_ai.torch_ops
except ImportError as error:
    message = str(error).lower()
    assert 'torch' in message and ('install' in message or 'require' in message), message
else:
    raise AssertionError('missing framework dependency was accepted')
assert 'vortex_ai._native' not in sys.modules
assert vortex_ai.BINDING_API == 1
""")

    def test_wrong_torch_version_rejected_before_registration(self):
        self.probe("""
import importlib.abc, types
fake = types.ModuleType('torch')
fake.__version__ = '0.0.0+cpu'
fake.version = types.SimpleNamespace(cuda=None, hip=None)
sys.modules['torch'] = fake
class NoNative(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'vortex_ai._native':
            raise AssertionError('version check loaded native code')
sys.meta_path.insert(0, NoNative())
try:
    import vortex_ai.torch_ops
except (ImportError, RuntimeError) as error:
    assert '2.15.0+cpu' in str(error), str(error)
else:
    raise AssertionError('unqualified torch version was accepted')
assert 'vortex_ai._native' not in sys.modules
""")

    def test_framework_does_not_become_a_base_package_dependency(self):
        project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
        self.assertEqual(project["dependencies"], [])
        self.assertNotIn("optional-dependencies", project)

    def test_adapter_is_included_and_changes_the_bound_source_identity(self):
        spec = importlib.util.spec_from_file_location("p05_torch_bundle_probe",
                                                      ROOT / "python/vortex_ai/_bundle.py")
        bundle = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bundle)
        self.assertIn(MODULE, bundle.SOURCE_PATHS)
        includes = {line.split(maxsplit=1)[1] for line in (ROOT / "MANIFEST.in").read_text().splitlines()
                    if line.startswith("include ")}
        self.assertIn(MODULE, includes)
        before = bundle.source_inventory(ROOT)
        with tempfile.TemporaryDirectory(prefix="p05-torch-source-pin-") as temporary:
            staged = Path(temporary)
            for name in bundle.SOURCE_PATHS:
                target = staged / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / name, target)
            self.assertEqual(bundle.source_inventory(staged), before)
            with (staged / MODULE).open("ab") as stream:
                stream.write(b"\n# tampered optional adapter\n")
            after = bundle.source_inventory(staged)
        self.assertNotEqual(bundle.inventory_digest(before), bundle.inventory_digest(after))
        changed = [old["path"] for old, new in zip(before, after) if old != new]
        self.assertEqual(changed, [MODULE])


if __name__ == "__main__":
    unittest.main()
