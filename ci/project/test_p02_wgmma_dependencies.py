# SPDX-License-Identifier: Apache-2.0
"""Real filesystem mutations for bounded external-header provenance."""

import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import p02_wgmma_dependencies as dependencies
import test_p02_wgmma_matrix as support


class DependencyHeadersTests(unittest.TestCase):
    def tree(self):
        temporary = tempfile.TemporaryDirectory(prefix="wgmma-headers-")
        self.addCleanup(temporary.cleanup)
        source = Path(temporary.name).resolve() / "source"
        for name in dependencies.HEADER_ROOTS:
            directory = source / name / "nested"
            directory.mkdir(parents=True)
            (directory / "fixture.h").write_bytes(b"header A\n")
        return source

    def test_complete_sorted_inventory_includes_nonstandard_header_suffixes(self):
        source = self.tree()
        extra = source / dependencies.HEADER_ROOTS[0] / "detail.inc"
        extra.write_bytes(b"included fragments\n")
        observed = dependencies.dependency_headers(source)
        paths = sorted(path for root in dependencies.HEADER_ROOTS for path in (source / root).rglob("*")
                       if path.is_file())
        self.assertEqual(observed, [{"path": path.relative_to(source).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size_bytes": path.stat().st_size}
            for path in paths])

    def test_same_size_edit_addition_and_removal_change_real_inventory(self):
        for mutation in ("edit", "add", "remove"):
            with self.subTest(mutation=mutation):
                source = self.tree()
                baseline = dependencies.dependency_headers(source)
                directory = source / dependencies.HEADER_ROOTS[0]
                if mutation == "edit":
                    (directory / "nested/fixture.h").write_bytes(b"header B\n")
                else:
                    added = directory / "added.h"
                    added.write_bytes(b"new header\n")
                    if mutation == "remove":
                        baseline = dependencies.dependency_headers(source)
                        added.unlink()
                self.assertNotEqual(dependencies.dependency_headers(source), baseline)

    def test_missing_or_empty_include_trees_reject(self):
        for relative in dependencies.HEADER_ROOTS:
            for remove in (False, True):
                with self.subTest(relative=relative, missing=remove):
                    source = self.tree()
                    directory = source / relative
                    (directory / "nested/fixture.h").unlink()
                    (directory / "nested").rmdir()
                    if remove:
                        directory.rmdir()
                    with self.assertRaisesRegex(ValueError, "empty|missing"):
                        dependencies.dependency_headers(source)

    def test_symlinked_roots_ancestors_files_and_directories_reject(self):
        for relative in ("third_party/ramulator/ext", *dependencies.HEADER_ROOTS,
                         dependencies.HEADER_ROOTS[0] + "/nested",
                         dependencies.HEADER_ROOTS[0] + "/nested/fixture.h"):
            with self.subTest(relative=relative):
                source = self.tree()
                target = source / relative
                saved = target.with_name(target.name + "-original")
                target.rename(saved)
                target.symlink_to(saved.name, target_is_directory=saved.is_dir())
                with self.assertRaisesRegex(ValueError, "symlink"):
                    dependencies.dependency_headers(source)

    def test_symlinked_source_broken_link_and_special_file_reject(self):
        source = self.tree()
        linked_source = source.parent / "linked-source"
        linked_source.symlink_to(source, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            dependencies.dependency_headers(linked_source)
        path = source / dependencies.HEADER_ROOTS[0] / "unexpected"
        path.symlink_to("missing")
        with self.assertRaisesRegex(ValueError, "symlink"):
            dependencies.dependency_headers(source)
        path.unlink()
        os.mkfifo(path)
        with self.assertRaisesRegex(ValueError, "regular file"):
            dependencies.dependency_headers(source)

    def test_entry_depth_file_size_and_total_size_limits_reject(self):
        for constant, value, message in (("MAX_HEADER_ENTRIES", 1, "entry limit"),
                                         ("MAX_HEADER_DEPTH", 0, "depth limit"),
                                         ("MAX_HEADER_FILE_BYTES", 1, "file byte limit"),
                                         ("MAX_HEADER_BYTES", 10, "total byte limit")):
            with self.subTest(limit=constant), mock.patch.object(dependencies, constant, value):
                with self.assertRaisesRegex(ValueError, message):
                    dependencies.dependency_headers(self.tree())

    def test_reads_are_bounded_and_file_mutation_during_hashing_rejects(self):
        source = self.tree()
        path = source / dependencies.HEADER_ROOTS[0] / "nested/fixture.h"
        real_read, changed = os.read, []

        def read(descriptor, size):
            self.assertGreater(size, 0)
            self.assertLessEqual(size, dependencies.READ_BYTES)
            value = real_read(descriptor, size)
            if value and not changed:
                path.write_bytes(b"header B\n")
                changed.append(True)
            return value

        with mock.patch.object(dependencies.os, "read", side_effect=read):
            with self.assertRaisesRegex(ValueError, "changed while reading"):
                dependencies.dependency_headers(source)
        self.assertTrue(changed)

    def test_runner_rejects_real_header_drift_before_launch_and_at_finalization(self):
        for when in (2, 5):
            with self.subTest(observation=when):
                source, observations = self.tree(), []

                def inventory(_):
                    observations.append(True)
                    if len(observations) == when:
                        (source / dependencies.HEADER_ROOTS[0] / "nested/fixture.h").write_bytes(b"header B\n")
                    return dependencies.dependency_headers(source)

                harness = support.WorkflowTests()
                self.addCleanup(harness.doCleanups)
                report, calls, _ = harness.scenario(dependency_header_inventory=inventory)
                self.assertEqual(report["outcome"], "fail", report["reason"])
                self.assertIn("dependency headers changed", report["reason"])
                self.assertEqual(calls["case"], 0 if when == 2 else 2)
                self.assertEqual(report["dependencies_before"], report["dependencies_after"])
                self.assertNotEqual(report["dependency_headers_before"], report["dependency_headers_after"])
                self.assertTrue(report["source_stable"])
                self.assertFalse(report["acceptance_claimed"])


if __name__ == "__main__":
    unittest.main()
