# SPDX-License-Identifier: Apache-2.0
"""Check preparation origin, shared host selection and real alias stability."""

from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import p06_dependency_build as build
import p06_dependency_contract as contract
import p06_dependency_receipt as receipt
import p06_dependency_record as recorder
from test_p06_dependency_local_prepare import synthetic_preparation


class DependencyLocalAdmissionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="p06-local-admission-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.host_bin = self.root / "host-bin"
        self.host_bin.mkdir()
        self.revision = "1" * 40
        self.hosted = {"contract_id": "p06-dependency-preparation-v1",
            "outcome": "pass", "reason": None, "expected_revision": self.revision,
            "dependency_contract_sha256": contract.contract_hash(), "dependency_cache_used": False}

    def rejected_build(self, preparation, *, host_bin=None):
        original = self.root / "preparation.json"
        original.write_bytes(contract.json_bytes(preparation) + b"\n")
        args = SimpleNamespace(source_dir=build.ROOT, workspace_dir=self.workspace,
            preparation=original, output_dir=self.workspace / "evidence",
            expected_revision=self.revision, host_bin=host_bin)
        with mock.patch.object(build, "collect_source", return_value={"revision": self.revision}), \
                mock.patch.object(build.base, "_source_ok"), \
                mock.patch.object(build, "run_bounded", side_effect=AssertionError("build must not launch")):
            report = build.build(args)
        self.assertEqual(report["outcome"], "blocked")
        self.assertFalse(report["fresh_dependency_build_passed"])
        self.assertEqual(report["commands"], [])
        self.assertFalse((self.workspace / "dependency-build").exists())
        self.assertFalse((self.workspace / "dependency-sources").exists())
        self.assertEqual(json.loads((args.output_dir / "report.json").read_bytes()), report)
        self.assertTrue(all(report[name] is False for name in contract.FALSE_CLAIMS))
        return report

    def test_unknown_success_shaped_preparation_is_rejected_before_execution(self):
        preparation = dict(self.hosted, contract_id="p06-unreviewed-preparation-v1")
        report = self.rejected_build(preparation)
        self.assertIn("matching fresh dependency preparation", report["reason"])

    def test_missing_preparation_contract_cannot_bypass_origin_admission(self):
        preparation = dict(self.hosted)
        del preparation["contract_id"]
        self.assertIn("matching fresh dependency preparation", self.rejected_build(preparation)["reason"])

    def test_hosted_preparation_cannot_enable_a_local_host_override(self):
        report = self.rejected_build(self.hosted, host_bin=self.host_bin)
        self.assertIn("host-bin differs", report["reason"])

    def test_hosted_preparation_cannot_smuggle_custom_host_bin_metadata(self):
        preparation = dict(self.hosted, host_bin=str(self.host_bin))
        self.assertIn("hosted preparation cannot", self.rejected_build(preparation)["reason"])

    def test_local_contract_name_alone_is_not_a_successful_preparation(self):
        preparation = dict(self.hosted, contract_id="p06-local-dependency-preparation-v1")
        self.rejected_build(preparation)

    def test_hosted_preparation_remains_inert_and_uses_default_tools(self):
        with mock.patch("subprocess.Popen", side_effect=AssertionError("replay must remain inert")), \
                mock.patch.object(Path, "open", side_effect=AssertionError("producer file access forbidden")), \
                mock.patch.object(Path, "resolve", side_effect=AssertionError("producer resolution forbidden")):
            self.assertIsNone(receipt.validate_preparation(self.hosted, self.revision))
        for key, value in (("expected_revision", "2" * 40), ("dependency_cache_used", True),
                           ("outcome", "fail"), ("reason", "previous failure")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                receipt.validate_preparation(dict(self.hosted, **{key: value}), self.revision)

    def test_complete_local_preparation_joins_without_opening_producer_paths(self):
        document = synthetic_preparation(self.root, self.revision, host_bin=self.host_bin)
        paths = {"source": document["source_dir"], "workspace": document["workspace_dir"]}
        trusted_lock = receipt.local_prepare.toolchain.ROOT / "ci/project/p01_toolchain.lock.json"
        original_open = Path.open

        def trusted_open(path, *args, **kwargs):
            self.assertEqual(path, trusted_lock, "producer file access forbidden")
            return original_open(path, *args, **kwargs)

        with mock.patch("subprocess.Popen", side_effect=AssertionError("replay must remain inert")), \
                mock.patch.object(Path, "resolve", side_effect=AssertionError("producer resolution forbidden")), \
                mock.patch.object(Path, "open", trusted_open):
            self.assertEqual(receipt.validate_preparation(document, self.revision, paths=paths,
                tools=document["host_tools"], manifest=document["source_manifest"],
                checkout=document["source_before"]), str(self.host_bin))

    def test_local_preparation_rejects_different_build_source_tools_and_checkout(self):
        document = synthetic_preparation(self.root, self.revision, host_bin=self.host_bin)
        paths = {"source": document["source_dir"], "workspace": document["workspace_dir"]}
        tools = deepcopy(document["host_tools"])
        tools["g++"]["resolved_path"] += "-other"
        manifest = deepcopy(document["source_manifest"])
        manifest["sources"][0]["files"][0]["sha256"] = "0" * 64
        checkout = dict(document["source_before"], tree="c" * 40)
        cases = (({"paths": dict(paths, source="/different-source")}, "roots"),
                 ({"paths": dict(paths, workspace="/different-workspace")}, "roots"),
                 ({"tools": tools}, "host tools"), ({"manifest": manifest}, "materialized sources"),
                 ({"checkout": checkout}, "measurement checkout"))
        for values, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                receipt.validate_preparation(document, self.revision, **values)

    def test_default_environment_is_unchanged_and_host_prefix_does_not_leak_inputs(self):
        with mock.patch.dict(os.environ, {"CXX": "caller", "PATH": "/caller", "LD_PRELOAD": "/caller.so",
                                         "CPATH": "/caller", "MAKEFLAGS": "-j64"}):
            ordinary = build.clean_environment(self.root / "build")
            selected = build.clean_environment(self.root / "build", self.host_bin)
        expected = os.pathsep.join(dict.fromkeys((str(Path(sys.executable).parent), "/usr/bin", "/bin")))
        self.assertEqual(ordinary["PATH"], expected)
        self.assertEqual(selected.pop("PATH"), str(self.host_bin) + os.pathsep + expected)
        ordinary.pop("PATH")
        self.assertEqual(selected, ordinary)
        self.assertFalse(set(recorder.INJECTION_ENVIRONMENT) & set(selected))
        self.assertNotIn("CXX", selected)
        self.assertNotIn("LD_PRELOAD", selected)
        self.assertEqual(selected["MAKEFLAGS"], "-j2")
        self.assertEqual(selected["CMAKE_BUILD_PARALLEL_LEVEL"], "2")
        self.assertEqual(selected["THREADS"], "1")

    def test_real_host_alias_retarget_is_rejected_at_the_next_stability_boundary(self):
        for name in build.HOST_TOOLS:
            if name != "python3":
                executable = self.host_bin / name
                executable.write_bytes(("#!/bin/sh\nprintf '%s\\n' '" + name + "'\n").encode())
                executable.chmod(0o700)
        environment = build.clean_environment(self.root / "build", self.host_bin)
        original = build.tool_inventory(environment)
        producer = object.__new__(build.Builder)
        producer.helpers = None
        producer.environment = environment
        producer.report = {"tools": original, "source_manifest": None,
                           "staged_files": [], "stability_checks": []}
        producer.stable("before-compile")
        alias = self.host_bin / "g++"
        original_target = self.host_bin / "g++-original"
        alias.rename(original_target)
        alias.symlink_to(original_target)
        self.assertEqual(build.tool_inventory(environment)["g++"]["sha256"], original["g++"]["sha256"])
        with self.assertRaisesRegex(ValueError, "dependency build tool changed"):
            producer.stable("after-alias-retarget")

    def test_host_bin_directory_cannot_be_a_symlink(self):
        alias = self.root / "alias"
        alias.symlink_to(self.host_bin, target_is_directory=True)
        args = SimpleNamespace(source_dir=build.ROOT, workspace_dir=self.workspace,
            output_dir=self.workspace / "evidence", expected_revision=self.revision, host_bin=alias)
        with self.assertRaises(ValueError):
            build.Builder(args)
        self.assertFalse(args.output_dir.exists())


if __name__ == "__main__":
    unittest.main()
