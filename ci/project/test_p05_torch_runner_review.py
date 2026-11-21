# SPDX-License-Identifier: Apache-2.0
"""Independent host-only regressions for framework package and provenance seams.

Synthetic inert files exercise validation only. No native workload or framework
is installed, imported, or executed by this module.
"""
from contextlib import ExitStack
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

import p05_torch_execute as runner


def write(root, name, data):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {"path": name, "sha256": hashlib.sha256(data).hexdigest(),
            "size_bytes": len(data)}


class VendorMetadataContracts(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="p05-torch-vendor-review-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_only_root_distribution_entry_points_create_commands(self):
        wheel = self.root / "synthetic.whl"
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr("tiny-1.dist-info/entry_points.txt",
                             "[console_scripts]\ntiny = tiny:main\n")
            archive.writestr("tiny/_vendor/other-2.dist-info/entry_points.txt",
                             "[console_scripts]\nvendor-only = other:main\n")
        payload, scripts = runner._wheel_payload(wheel)
        self.assertEqual(scripts, ["bin/tiny"])
        self.assertIn(runner.SITE + "tiny/_vendor/other-2.dist-info/entry_points.txt",
                      {row["path"] for row in payload})

    def test_vendored_record_is_immutable_payload(self):
        venv = self.root / "venv"
        name = runner.SITE + "tiny/_vendor/other-2.dist-info/RECORD"
        original = write(venv, name, b"original vendor record\n")
        write(venv, name, b"changed vendor record\n")
        with self.assertRaisesRegex(ValueError, "differs from locked wheel"):
            runner._installed_inventory(venv, [original], [], [])

    def test_vendored_metadata_cannot_authorize_unexplained_files(self):
        venv = self.root / "venv"
        prefix = runner.SITE + "tiny/_vendor/other-2.dist-info/"
        original = write(venv, prefix + "RECORD", b"vendor record\n")
        write(venv, prefix + "direct_url.json", b"{}\n")
        with self.assertRaisesRegex(ValueError, "unexplained"):
            runner._installed_inventory(venv, [original], [], [])

    def test_top_level_installer_metadata_remains_supported(self):
        venv = self.root / "venv"
        prefix = runner.SITE + "tiny-1.dist-info/"
        original = write(venv, prefix + "RECORD", b"original wheel record\n")
        write(venv, prefix + "RECORD", b"installer rewrote record\n")
        write(venv, prefix + "INSTALLER", b"pip\n")
        write(venv, prefix + "REQUESTED", b"")
        write(venv, prefix + "direct_url.json", b"{}\n")
        self.assertEqual(len(runner._installed_inventory(venv, [original], [], [])), 4)


class SourceHandoffContracts(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="p05-torch-source-review-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source, self.output = self.root / "source", self.root / "output"
        self.main = "ci/project/p05_execute.py"
        self.binding = "python/vortex_ai/_bundle.py"
        self.helper = "ci/project/raw_validator.py"
        self.native = "native/model.cpp"
        names = (self.main, self.binding, self.helper, self.native)
        self.rows = [write(self.source, name, ("inert source " + name).encode())
                     for name in sorted(names)]
        self.before = {"checkout": {"revision": "1" * 40, "tree": "2" * 40,
                                      "dirty": False}, "files": self.rows}
        self.current = copy.deepcopy(self.before)
        # The new entry point legitimately observes its own extra source.
        self.current["files"].append(write(self.source, "ci/project/p05_torch_execute.py",
                                            b"inert new entry point"))
        self.report = {"source_stable": True,
                       "loaded_helpers": [row for row in self.rows
                                          if row["path"] == self.helper],
                       "retained_sources": []}
        for name in sorted((self.main, self.binding, self.helper)):
            self.report["retained_sources"].append(write(
                self.output, "artifacts/source/" + name, (self.source / name).read_bytes()))
        self.save_snapshots()
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch.object(runner.python_run, "SOURCE_FILES", (self.main,)))
        stack.enter_context(mock.patch.object(runner.bundle_producer._bundle,
                                               "SOURCE_PATHS", (self.binding,)))
        stack.enter_context(mock.patch.object(runner.python_run.model_run, "source_snapshot",
                                               return_value={"files": [{"path": self.native}]}))

    def save_snapshots(self):
        for key, name in (("source_before", "source-before"), ("source_after", "source-after")):
            self.report[key] = write(self.output, "snapshots/" + name + ".json",
                                     json.dumps(self.before, sort_keys=True).encode())

    def verify(self):
        return runner._python_sources(runner.bundle_producer._Inputs(), self.source,
                                       self.output, self.report, self.current)

    def test_original_helpers_need_not_include_new_entry_point(self):
        self.assertEqual(self.verify(), self.before)

    def test_rehashed_stale_checkout_is_rejected(self):
        self.before["checkout"]["revision"] = "3" * 40
        self.save_snapshots()
        with self.assertRaisesRegex(ValueError, "exact current clean checkout"):
            self.verify()

    def test_omitted_native_source_inventory_member_is_rejected(self):
        self.before["files"] = [row for row in self.rows if row["path"] != self.native]
        self.save_snapshots()
        with self.assertRaisesRegex(ValueError, "inventory membership"):
            self.verify()

    def test_omitted_retained_helper_is_rejected(self):
        self.report["retained_sources"] = [row for row in self.report["retained_sources"]
                                            if row["path"] != "artifacts/source/" + self.helper]
        with self.assertRaisesRegex(ValueError, "retained source membership"):
            self.verify()

    def test_rehashed_retained_helper_cannot_substitute_for_actual_source(self):
        name = "artifacts/source/" + self.helper
        changed = write(self.output, name, b"substituted helper")
        self.report["retained_sources"] = [changed if row["path"] == name else row
                                            for row in self.report["retained_sources"]]
        with self.assertRaisesRegex(ValueError, "retained source changed"):
            self.verify()

    def test_changed_live_helper_is_rejected(self):
        write(self.source, self.helper, b"different live helper")
        with self.assertRaisesRegex(ValueError, "source bytes changed"):
            self.verify()

    def test_integer_stability_claim_is_not_a_boolean(self):
        self.report["source_stable"] = 1
        with self.assertRaisesRegex(ValueError, "not stable"):
            self.verify()


if __name__ == "__main__":
    unittest.main()
