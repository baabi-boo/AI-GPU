# SPDX-License-Identifier: Apache-2.0
"""Readiness input observations with tiny files and explicitly substituted test pins."""

from contextlib import ExitStack
from copy import deepcopy
import hashlib
import inspect
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

import p06_qualified_warm_readiness as readiness
import test_p06_dependency_sources as dependency_fixtures


ROOT = Path(__file__).resolve().parents[2]


def indexed(checks):
    return {row["id"]: row for row in checks.rows}


def snapshot(root):
    return {path.relative_to(root).as_posix(): (
        path.stat().st_mode, path.stat().st_size, path.stat().st_mtime_ns,
        hashlib.sha256(path.read_bytes()).hexdigest())
        for path in root.rglob("*") if path.is_file() and not path.is_symlink()}


class ContractInputTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="p06-readiness-contract-inputs-")
        self.addCleanup(directory.cleanup)
        self.source = Path(directory.name).resolve() / "source"
        qualification = readiness.qualification
        self.proof = qualification.load_proof(ROOT / qualification.SOURCE_PROOF_PATH,
                                               qualification.SOURCE_PROOF_SHA256)
        self.helpers = readiness.admission.reader_sources()
        self.prerequisites = readiness.admission.prerequisite_input_rows(self.proof)
        paths = {row["path"] for row in
                 self.proof["measurement_sources"] + self.helpers + self.prerequisites}
        paths.add(qualification.warm.MANIFEST_PATH)
        self.assertLess(sum((ROOT / name).stat().st_size for name in paths), 5 * 1024**2)
        for name in paths:
            target = self.source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)

    def observe(self):
        checks = readiness._Checks()
        original = readiness._inspect_contracts({"source_dir": self.source}, checks)
        return indexed(checks), original

    def test_frozen_proofs_sampling_and_all_69_measurements_are_bound_without_admission(self):
        before = snapshot(self.source)
        with mock.patch.object(readiness.admission, "Admission") as admission, \
                mock.patch.object(readiness.historical, "Admission") as historical_admission, \
                mock.patch("subprocess.Popen") as process:
            rows, original = self.observe()
        admission.assert_not_called()
        historical_admission.assert_not_called()
        process.assert_not_called()
        self.assertTrue(all(row["status"] == "observed" for row in rows.values()), rows)
        measured = {row["path"]: row for row in self.proof["measurement_sources"]}
        self.assertEqual(len(measured), 69)
        self.assertEqual({name.removeprefix("source.measurement:") for name in rows
                          if name.startswith("source.measurement:")}, set(measured))
        for name, expected in measured.items():
            row = rows["source.measurement:" + name]
            self.assertEqual(row["observed"], expected)
            self.assertEqual(row["expected"], expected)
        sampling = rows["proof.sampling"]["observed"]
        self.assertEqual(sampling["process_count"], 24)
        self.assertEqual(sampling["sampling"], self.proof["sampling"])
        self.assertEqual(sampling["contract_sha256"], readiness.qualification.WARM_CONTRACT_SHA256)
        self.assertEqual(original, readiness.qualification.base_proof())
        self.assertEqual(snapshot(self.source), before)

    def test_changed_caller_and_missing_measurement_do_not_hide_other_rows(self):
        caller = readiness.qualification.CHANGED_SOURCE
        missing = "sim/common/perf_counter.h"
        (self.source / caller).write_bytes(
            (ROOT / "ci/project/fixtures/p06_counter_preflight_main_v1.cpp").read_bytes())
        (self.source / missing).unlink()
        before = snapshot(self.source)
        rows, _ = self.observe()
        measured = [row for name, row in rows.items() if name.startswith("source.measurement:")]
        self.assertEqual(len(measured), 69)
        self.assertEqual(sum(row["status"] == "observed" for row in measured), 67)
        self.assertEqual(rows["source.measurement:" + caller]["status"], "blocked")
        self.assertEqual(rows["source.measurement:" + missing]["status"], "blocked")
        self.assertEqual(rows["source.measurement_projection"]["status"], "not_checked")
        self.assertEqual(snapshot(self.source), before)
        self.assertFalse((self.source / missing).exists())

    def test_readable_wrong_measurement_bytes_reach_the_projection_validator(self):
        target = self.source / readiness.qualification.CHANGED_SOURCE
        body = target.read_bytes()
        target.write_bytes(bytes([body[0] ^ 1]) + body[1:])
        with mock.patch.object(readiness.qualification, "verify_source_projection",
                               wraps=readiness.qualification.verify_source_projection) as projection:
            rows, _ = self.observe()
        projection.assert_called_once()
        self.assertEqual(len(projection.call_args.args[1]), 69)
        self.assertEqual(rows["source.measurement_projection"]["status"], "blocked")
        self.assertEqual(rows["source.measurement:" + readiness.qualification.CHANGED_SOURCE]
                         ["observed"]["size_bytes"], len(body))

    def test_each_raw_proof_or_sampling_substitution_is_reported(self):
        qualification = readiness.qualification
        original_loader = qualification.base_proof
        inputs = (("qualified_warm", qualification.SOURCE_PROOF_PATH),
                  ("historical", qualification.historical.SOURCE_PROOF_PATH),
                  ("warm_manifest", qualification.warm.MANIFEST_PATH))
        for name, relative in inputs:
            with self.subTest(input=name):
                target = self.source / relative
                body = target.read_bytes()
                target.write_bytes(body[:-1] + bytes([body[-1] ^ 1]))
                try:
                    with mock.patch.object(readiness, "ROOT", self.source), \
                            mock.patch.object(qualification, "base_proof",
                                              side_effect=lambda: original_loader(self.source)):
                        rows, _ = self.observe()
                    self.assertEqual(rows["proof." + name + ".raw"]["status"], "blocked")
                    self.assertEqual(rows["proof." + name + ".validation"]["status"], "blocked")
                    if name == "qualified_warm":
                        self.assertEqual(rows["source.measurements"]["status"], "not_checked")
                    else:
                        self.assertEqual(sum(key.startswith("source.measurement:") for key in rows), 69)
                    self.assertEqual(target.read_bytes(), body[:-1] + bytes([body[-1] ^ 1]))
                finally:
                    target.write_bytes(body)

    def test_raising_semantic_proof_helper_preserves_frozen_measurement_checks(self):
        with mock.patch.object(readiness.qualification, "load_proof",
                               side_effect=ValueError("semantic proof helper failed")):
            rows, original = self.observe()
        self.assertEqual(rows["proof.qualified_warm.validation"]["status"], "blocked")
        measured = [row for name, row in rows.items() if name.startswith("source.measurement:")]
        self.assertEqual(len(measured), 69)
        self.assertTrue(all(row["status"] == "observed" for row in measured))
        self.assertIsNotNone(original)

    def test_helper_and_prerequisite_mismatches_remain_separate_from_measurements(self):
        helper = "ci/project/p06_qualified_warm_admission.py"
        prerequisite = readiness.qualification.base_proof()["diagnostics"]["public_source_inventory"]["path"]
        for name in (helper, prerequisite):
            target = self.source / name
            target.write_bytes(target.read_bytes() + b"\n")
        rows, _ = self.observe()
        self.assertEqual(rows["source.helper:" + helper]["status"], "blocked")
        self.assertEqual(rows["source.prerequisite:" + prerequisite]["status"], "blocked")
        self.assertEqual(rows["source.measurement_projection"]["status"], "observed")


class OriginalInputTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="p06-readiness-original-inputs-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.proof = deepcopy(readiness.qualification.base_proof())
        self.inputs = {}
        for name, section in (("diagnostic", "diagnostics"), ("control", "controls")):
            path = self.root / (name + ".zip")
            body = ("synthetic " + name + " bytes, intentionally not a ZIP\n").encode()
            path.write_bytes(body)
            self.inputs[name + "_archive"] = path
            self.proof[section]["archive"].update(
                sha256=hashlib.sha256(body).hexdigest(), size_bytes=len(body))

    def observe(self, **overrides):
        checks = readiness._Checks()
        with mock.patch("zipfile.ZipFile") as archive, \
                mock.patch.object(readiness.admission.prerequisites, "verify_prerequisites") as diagnostics, \
                mock.patch.object(readiness.admission.prerequisites, "verify_control_prerequisite") as controls:
            readiness._inspect_originals(dict(self.inputs, **overrides), self.proof, checks)
        archive.assert_not_called()
        diagnostics.assert_not_called()
        controls.assert_not_called()
        return indexed(checks)

    def test_explicitly_substituted_tiny_pins_observe_bytes_without_opening_zip_members(self):
        before = snapshot(self.root)
        rows = self.observe()
        for name in ("diagnostic", "control"):
            row = rows["originals." + name]
            self.assertEqual(row["status"], "observed")
            self.assertEqual(row["observed"], readiness.historical._identity(self.inputs[name + "_archive"]))
        self.assertEqual(snapshot(self.root), before)

    def test_both_originals_reject_wrong_raw_size_or_digest_and_continue(self):
        for name in ("diagnostic", "control"):
            path = self.inputs[name + "_archive"]
            body = path.read_bytes()
            peer = "control" if name == "diagnostic" else "diagnostic"
            for changed in (body + b"extra", bytes([body[0] ^ 1]) + body[1:]):
                with self.subTest(original=name, size=len(changed)):
                    path.write_bytes(changed)
                    try:
                        rows = self.observe()
                        self.assertEqual(rows["originals." + name]["status"], "blocked")
                        self.assertEqual(rows["originals." + peer]["status"], "observed")
                        self.assertEqual(path.read_bytes(), changed)
                    finally:
                        path.write_bytes(body)

    def test_both_originals_reject_path_aliases_symlinks_and_multiple_links(self):
        for name in ("diagnostic", "control"):
            path = self.inputs[name + "_archive"]
            peer = "control" if name == "diagnostic" else "diagnostic"
            for kind in ("relative", "parent_segment", "symlink", "parent_symlink", "hardlink"):
                with self.subTest(original=name, kind=kind):
                    alias = self.root / "alias"
                    if kind == "relative":
                        selected = path.name
                    elif kind == "parent_segment":
                        selected = path.parent / ".." / path.parent.name / path.name
                    elif kind == "symlink":
                        alias.symlink_to(path)
                        selected = alias
                    elif kind == "parent_symlink":
                        alias.symlink_to(path.parent, target_is_directory=True)
                        selected = alias / path.name
                    else:
                        os.link(path, alias)
                        selected = path
                    try:
                        rows = self.observe(**{name + "_archive": selected})
                        self.assertEqual(rows["originals." + name]["status"], "blocked")
                        self.assertEqual(rows["originals." + peer]["status"], "observed")
                    finally:
                        if os.path.lexists(alias):
                            alias.unlink()


class ArchivePartInputTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="p06-readiness-part-inputs-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.manifest = readiness.toolchain._locked_manifest()
        self.parts = readiness.toolchain._selected_parts(self.manifest)

    def observe(self):
        checks = readiness._Checks()
        with mock.patch.object(readiness.toolchain, "provision") as provision, \
                mock.patch.object(readiness.toolchain, "_extract") as extract:
            readiness._inspect_parts({"archive_root": self.root}, checks)
        provision.assert_not_called()
        extract.assert_not_called()
        return indexed(checks)

    def test_all_fifteen_missing_locked_parts_are_reported_without_extraction(self):
        rows = self.observe()
        self.assertEqual(len(self.parts), 15)
        self.assertEqual(rows["toolchain.selection"]["observed"]["parts"], 15)
        self.assertEqual({name for name in rows if name.startswith("toolchain.part:")},
                         {"toolchain.part:" + row["path"] for row in self.parts})
        self.assertTrue(all(rows["toolchain.part:" + row["path"]]["status"] == "blocked"
                            for row in self.parts))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_missing_and_corrupt_tiny_parts_do_not_hide_later_validated_parts(self):
        synthetic = deepcopy(self.manifest)
        selected_paths = {row["path"] for row in self.parts}
        for row in synthetic["parts"]:
            if row["path"] not in selected_paths:
                continue
            body = ("tiny substituted part " + row["path"] + "\n").encode()
            path = self.root / row["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
            row.update(size_bytes=len(body), sha256=hashlib.sha256(body).hexdigest(),
                       git_blob_sha=hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest())
        (self.root / self.parts[0]["path"]).unlink()
        corrupt = self.root / self.parts[1]["path"]
        body = corrupt.read_bytes()
        corrupt.write_bytes(bytes([body[0] ^ 1]) + body[1:])
        before = snapshot(self.root)
        with mock.patch.object(readiness.toolchain, "_locked_manifest", return_value=synthetic):
            rows = self.observe()
        for index, part in enumerate(self.parts):
            self.assertEqual(rows["toolchain.part:" + part["path"]]["status"],
                             "blocked" if index < 2 else "observed")
        self.assertEqual(snapshot(self.root), before)


class DependencyInputTests(unittest.TestCase):
    def setUp(self):
        self.fixture = dependency_fixtures.DependencySourcesTests(
            methodName="test_complete_regular_trees_are_relocated_with_original_modes_and_bytes")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.source = self.fixture.root / "source"
        self.repositories = self.fixture.root / "repositories"
        self.source.mkdir()
        self.repositories.mkdir()
        for name, old in self.fixture.repositories.items():
            path = (self.source / self.fixture.lock[name]["path"]
                    if name in ("softfloat", "ramulator") else self.repositories / name)
            path.parent.mkdir(parents=True, exist_ok=True)
            old.rename(path)
            self.fixture.repositories[name] = path

    def observe(self, **roots):
        checks = readiness._Checks()
        selected = {"source_dir": self.source, "dependency_repositories": self.repositories}
        selected.update(roots)
        with mock.patch.object(readiness.sources, "materialize_sources") as materialize:
            readiness._inspect_dependencies(selected, checks)
        materialize.assert_not_called()
        return indexed(checks)

    def test_all_five_object_trees_read_every_blob_with_one_shared_budget(self):
        before = snapshot(self.fixture.root)
        original = readiness.sources._DependencyGitObjects
        readers = []

        def open_reader(*args, **kwargs):
            reader = original(*args, **kwargs)
            reader.blob = mock.Mock(wraps=reader.blob)
            readers.append(reader)
            return reader

        with mock.patch.object(readiness.sources, "_DependencyGitObjects", side_effect=open_reader), \
                mock.patch.object(readiness.sources, "validate_manifest",
                                  wraps=readiness.sources.validate_manifest) as validate:
            rows = self.observe()
        self.assertEqual(len(readers), 5)
        self.assertEqual(len({id(reader.budget) for reader in readers}), 1)
        for reader in readers:
            self.assertEqual([call.args[0] for call in reader.blob.call_args_list], sorted(reader.entries))
        validate.assert_called_once()
        self.assertEqual(len(validate.call_args.args[0]["sources"]), 5)
        self.assertEqual(rows["dependency.manifest"]["observed"]["total_files"], 12)
        self.assertTrue(all(row["status"] == "observed" for row in rows.values()))
        self.assertEqual(snapshot(self.fixture.root), before)
        self.assertFalse(self.fixture.destination.exists())

    def test_missing_blob_and_missing_repository_are_both_reported_without_partial_manifest(self):
        repository = self.fixture.repositories["argparse"]
        oid = dependency_fixtures.git(repository, "rev-parse", "HEAD:input.h")
        (repository / ".git/objects" / oid[:2] / oid[2:]).unlink()
        self.fixture.repositories["spdlog"].rename(self.fixture.root / "unselected-spdlog")
        before = snapshot(self.fixture.root)
        with mock.patch.object(readiness.sources, "validate_manifest") as validate:
            rows = self.observe()
        validate.assert_not_called()
        for name in self.fixture.lock:
            self.assertEqual(rows["dependency.repository:" + name]["status"],
                             "blocked" if name in ("argparse", "spdlog") else "observed")
        self.assertEqual(rows["dependency.manifest"]["status"], "not_checked")
        self.assertEqual(snapshot(self.fixture.root), before)


class HostInputTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="p06-readiness-host-inputs-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.host = self.root / "host-bin"
        self.python = self.root / "python-bin/python3"
        self.workspace = self.root / "planned-workspace"
        self.host.mkdir()
        self.python.parent.mkdir()
        for name in (*readiness.preparation.HOST_TOOLS, *readiness.NATIVE_HOST_ALIASES):
            target = self.python if name == "python3" else self.host / name
            target.write_bytes(("synthetic host alias " + name + "\n").encode())
            target.chmod(0o755)
        self.context = ExitStack()
        self.addCleanup(self.context.close)
        self.context.enter_context(mock.patch.object(readiness.sys, "executable", str(self.python)))
        self.context.enter_context(mock.patch.object(readiness.sys, "version_info", (3, 12, 14, "final", 0)))
        self.context.enter_context(mock.patch.object(readiness.sys, "platform", "linux"))
        self.context.enter_context(mock.patch.object(readiness.platform, "python_implementation", return_value="CPython"))

    def probe_output(self, argv, **kwargs):
        return 0, b"Python 3.12.14\n" if Path(argv[0]).name == "python3" else b"cmake version 3.22.6\n"

    def observe(self, probe=None, *, workspace=True):
        checks = readiness._Checks()
        roots = {"host_bin": self.host}
        if workspace:
            roots["workspace_dir"] = self.workspace
        with mock.patch.object(readiness.inventory, "_probe", side_effect=probe or self.probe_output) as bounded:
            readiness._inspect_host(roots, checks)
        return indexed(checks), bounded

    def test_actual_alias_paths_and_hashes_feed_bounded_sanitized_version_probes(self):
        executable = self.host / "gcc-real"
        (self.host / "gcc").rename(executable)
        (self.host / "gcc").symlink_to(executable.name)
        before = snapshot(self.root)
        with mock.patch.dict(os.environ, {"PATH": "/unselected", "PYTHONPATH": "/unselected",
                                          "LD_PRELOAD": "/unselected", "MAKEFLAGS": "-j99"}):
            rows, probe = self.observe()
        self.assertTrue(all(row["status"] == "observed" for row in rows.values()), rows)
        for name in (*readiness.preparation.HOST_TOOLS, *readiness.NATIVE_HOST_ALIASES):
            path = self.python if name == "python3" else self.host / name
            self.assertEqual(rows["host.alias:" + name]["observed"], readiness.base._file_identity(path))
        self.assertEqual(rows["host.alias:gcc"]["observed"]["resolved_path"], str(executable))
        self.assertEqual([call.args[0] for call in probe.call_args_list],
                         [[str(self.python), "--version"], [str(self.host / "cmake"), "--version"]])
        environments = [call.kwargs["environment"] for call in probe.call_args_list]
        self.assertEqual(environments[0], environments[1])
        environment = environments[0]
        self.assertEqual(environment["PATH"], os.pathsep.join(
            (str(self.host), str(self.python.parent), "/usr/bin", "/bin")))
        self.assertEqual(environment["HOME"], str(self.workspace / "local-home"))
        self.assertEqual(environment["TMPDIR"], str(self.workspace / "local-tmp"))
        self.assertEqual(environment["MAKEFLAGS"], "-j2")
        self.assertNotIn("PYTHONPATH", environment)
        self.assertNotIn("LD_PRELOAD", environment)
        self.assertEqual(inspect.signature(readiness.inventory._probe).parameters["timeout"].default, 10)
        self.assertEqual(readiness.inventory.MAX_PROBE_BYTES, 65536)
        self.assertEqual(snapshot(self.root), before)
        self.assertFalse(self.workspace.exists())

    def test_several_absent_aliases_are_enumerated_while_other_versions_continue(self):
        original = shutil.which
        missing = {"g++", "as", "perl"}
        with mock.patch.object(readiness.shutil, "which",
                               side_effect=lambda name, **kwargs: None if name in missing else original(name, **kwargs)):
            rows, probe = self.observe()
        for name in (*readiness.preparation.HOST_TOOLS, *readiness.NATIVE_HOST_ALIASES):
            self.assertEqual(rows["host.alias:" + name]["status"],
                             "blocked" if name in missing else "observed")
        self.assertEqual(rows["host.preparation_selection"]["status"], "not_checked")
        self.assertEqual(rows["host.version:python3"]["status"], "observed")
        self.assertEqual(rows["host.version:cmake"]["status"], "observed")
        self.assertEqual(probe.call_count, 2)

    def test_same_version_from_a_shadowing_python_does_not_satisfy_interpreter_binding(self):
        shadow = self.host / "python3"
        shadow.write_bytes(b"different selected interpreter\n")
        shadow.chmod(0o755)
        rows, probe = self.observe()
        self.assertEqual(rows["host.alias:python3"]["observed"]["path"], str(shadow))
        self.assertEqual(rows["host.executing_python"]["observed"]["path"], str(self.python))
        self.assertEqual(rows["host.preparation_selection"]["status"], "blocked")
        self.assertEqual(rows["host.interpreter_binding"]["status"], "blocked")
        self.assertEqual(rows["host.version:python3"]["status"], "observed")
        self.assertEqual(probe.call_args_list[0].args[0], [str(shadow), "--version"])

    def test_missing_python_alias_leaves_explicit_dependent_checks_unperformed(self):
        original = shutil.which
        with mock.patch.object(readiness.shutil, "which",
                               side_effect=lambda name, **kwargs: None if name == "python3" else original(name, **kwargs)):
            rows, probe = self.observe()
        self.assertEqual(rows["host.alias:python3"]["status"], "blocked")
        self.assertEqual(rows["host.preparation_selection"]["status"], "not_checked")
        self.assertEqual(rows["host.interpreter_binding"]["status"], "not_checked")
        self.assertEqual(rows["host.version:python3"]["status"], "not_checked")
        self.assertEqual(rows["host.version:cmake"]["status"], "observed")
        self.assertEqual([call.args[0] for call in probe.call_args_list],
                         [[str(self.host / "cmake"), "--version"]])

    def test_wrong_runtime_does_not_suppress_alias_or_cmake_observations(self):
        with mock.patch.object(readiness.sys, "version_info", (3, 12, 13, "final", 0)):
            rows, _ = self.observe()
        self.assertEqual(rows["host.python_runtime"]["status"], "blocked")
        self.assertEqual(rows["host.interpreter_binding"]["status"], "blocked")
        self.assertEqual(rows["host.preparation_selection"]["status"], "observed")
        self.assertEqual(rows["host.version:cmake"]["status"], "observed")

    def test_cmake_compatibility_bounds_apply_to_the_selected_executable(self):
        for version, status in (("3.20.9", "blocked"), ("3.21.0", "observed"),
                                ("3.25.99", "observed"), ("3.26.0", "blocked")):
            with self.subTest(version=version):
                def probe(argv, **kwargs):
                    return ((0, ("cmake version " + version + "\n").encode())
                            if Path(argv[0]).name == "cmake" else self.probe_output(argv, **kwargs))
                rows, observed = self.observe(probe)
                self.assertEqual(rows["host.version:cmake"]["status"], status)
                self.assertEqual(rows["host.version:cmake"]["observed"]["version"],
                                 [int(part) for part in version.split(".")])
                self.assertEqual(observed.call_args_list[-1].args[0], [str(self.host / "cmake"), "--version"])

    def test_probe_failures_and_output_bounds_do_not_trigger_tool_substitution(self):
        failures = (ValueError("identity probe timed out"),
                    ValueError("identity probe output exceeded its limit"),
                    (1, b"cmake version 3.22.6\n"), (0, b"Python 3.22.6\n"))
        for failure in failures:
            with self.subTest(failure=str(failure)):
                def probe(argv, **kwargs):
                    if Path(argv[0]).name != "cmake":
                        return self.probe_output(argv, **kwargs)
                    if isinstance(failure, Exception):
                        raise failure
                    return failure
                rows, observed = self.observe(probe)
                self.assertEqual(rows["host.version:cmake"]["status"], "blocked")
                self.assertEqual(rows["host.version:python3"]["status"], "observed")
                self.assertEqual(observed.call_count, 2)
                self.assertEqual(observed.call_args_list[-1].args[0], [str(self.host / "cmake"), "--version"])

    def test_version_probe_rechecks_selected_tool_bytes_after_observation(self):
        path = self.host / "cmake"
        identity = readiness._tool_identity(path)

        def changed(argv, **kwargs):
            path.write_bytes(b"changed while the version was observed\n")
            return 0, b"cmake version 3.22.6\n"

        with mock.patch.object(readiness.inventory, "_probe", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "changed during version observation"):
                readiness._version_probe(identity, {"PATH": str(self.host)})

    def test_missing_workspace_keeps_alias_checks_but_skips_version_execution(self):
        rows, probe = self.observe(workspace=False)
        self.assertEqual(rows["host.alias:cmake"]["status"], "observed")
        self.assertEqual(rows["host.interpreter_binding"]["status"], "observed")
        self.assertEqual(rows["host.version:python3"]["status"], "not_checked")
        self.assertEqual(rows["host.version:cmake"]["status"], "not_checked")
        probe.assert_not_called()


if __name__ == "__main__":
    unittest.main()
