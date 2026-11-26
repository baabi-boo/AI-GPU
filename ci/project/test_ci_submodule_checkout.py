# SPDX-License-Identifier: Apache-2.0
"""Dependency-cache gitfiles require initialized checkout metadata before restore."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from test_p05_ci_workflow import children, scalars, steps, workflow


WORKFLOWS = Path(__file__).resolve().parents[2] / ".github/workflows"


class SubmoduleCheckoutTests(unittest.TestCase):
    def test_all_setup_vortex_consumers_checkout_recursively_before_cache_restore(self):
        consumers = []
        for path in sorted(WORKFLOWS.iterdir()):
            if path.suffix not in {".yml", ".yaml"}:
                continue
            jobs = children(workflow(path), "jobs", 2)
            for name in jobs:
                job = children(jobs, name, 4)
                if "steps" not in job:
                    continue
                checkout = None
                for step in steps(job):
                    action = step.get("uses", ("", []))[0]
                    if action.startswith("actions/checkout@"):
                        checkout = step
                    if action != "./.github/actions/setup-vortex":
                        continue
                    consumers.append((path.name, name))
                    with self.subTest(workflow=path.name, job=name):
                        obligation = "recursive checkout must precede Setup Vortex cache restore"
                        self.assertIsNotNone(checkout, obligation)
                        inputs = scalars(children(checkout, "with", 10)) if "with" in checkout else {}
                        self.assertEqual(inputs.get("submodules"), "recursive", obligation)
                        self.assertNotIn("if", checkout,
                                         "checkout must initialize submodules for every cache consumer")
        self.assertTrue(consumers, "expected Setup Vortex cache consumers")

    def git(self, root, *arguments, check=True):
        result = subprocess.run([
            "git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false",
            "-c", "protocol.allow=never", "-c", "protocol.file.allow=always",
            "-c", "user.name=Checkout Fixture", "-c", "user.email=fixture@example.invalid",
            "-C", str(root), *arguments], capture_output=True, text=True, timeout=15,
            env={**os.environ, "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1",
                 "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0"})
        if check:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def test_cached_submodule_gitfiles_need_metadata_before_restore(self):
        with tempfile.TemporaryDirectory(prefix="ci-submodule-cache-") as temporary:
            root = Path(temporary)
            dependency, producer = root / "dependency", root / "producer"
            dependency.mkdir()
            producer.mkdir()
            self.git(dependency, "init", "-q")
            (dependency / "source.txt").write_text("local cache fixture\n")
            self.git(dependency, "add", "source.txt")
            self.git(dependency, "commit", "-qm", "dependency")
            self.git(producer, "init", "-q")
            self.git(producer, "submodule", "add", "-q", str(dependency), "third_party/cocogfx")
            self.git(producer, "commit", "-qam", "superproject")
            cache = root / "cache"
            shutil.copytree(producer / "third_party", cache)
            gitfile = Path("third_party/cocogfx/.git")
            cached_pointer = (cache / "cocogfx/.git").read_text()
            self.assertEqual(cached_pointer, "gitdir: ../../.git/modules/third_party/cocogfx\n")

            for recursive in (False, True):
                with self.subTest(recursive_checkout=recursive):
                    checkout = root / ("recursive" if recursive else "plain")
                    options = ["--recurse-submodules"] if recursive else []
                    self.git(root, "clone", "-q", *options, str(producer), str(checkout))
                    shutil.copytree(cache, checkout / "third_party", dirs_exist_ok=True)
                    self.assertEqual((checkout / gitfile).read_text(), cached_pointer)
                    metadata = checkout / ".git/modules/third_party/cocogfx"
                    self.assertEqual(metadata.is_dir(), recursive)
                    traversal = self.git(checkout, "submodule", "foreach", "--recursive", "true", check=False)
                    self.assertEqual(traversal.returncode, 0 if recursive else 128, traversal.stderr)
                    if not recursive:
                        self.assertIn("gitfile does not point to a valid repository", traversal.stderr)
                        late_init = self.git(checkout, "submodule", "update", "--init", "--recursive", check=False)
                        self.assertEqual(late_init.returncode, 128, late_init.stderr)
                        self.assertFalse(metadata.exists())


if __name__ == "__main__":
    unittest.main()
