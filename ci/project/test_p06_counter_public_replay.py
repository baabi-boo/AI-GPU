# SPDX-License-Identifier: Apache-2.0
"""Reject failed originals and rehashed corruptions without executing evidence."""

from contextlib import ExitStack, redirect_stdout
from copy import deepcopy
import builtins
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tempfile
import unittest
from unittest import mock
import warnings
import zipfile

import p06_counter_public_replay as replay


ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / "docs/project/evidence/p06-counter-diagnostics/native"
FAILED_ORIGINAL = NATIVE / "run-45029135146-attempt1.zip"
FAILED_SHA256 = "d628813ec8815140830825adef22cd2ea9191707686931e49145d5a4e4247db5"
FAILED_REVISION = "81ed6871634fefbf5c78fb27cf10dce913bd4d9c"
# This independent intake receipt is added only after a complete original passes.
SUCCESS_RECEIPT = NATIVE / "public-runtime-pass.json"
PREFIX = "public-counters/"
REPORT = PREFIX + "report.json"
FALSE_CLAIMS = ("qualified", "ready_for_warm", "warm_execution", "acceptance",
                "acceptance_claimed", "phase_acceptance", "performance_acceptance",
                "full_warm_coverage", "retained_code_executed")


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def read_members(path):
    with zipfile.ZipFile(path) as archive:
        return {row.filename: archive.read(row) for row in archive.infolist() if not row.is_dir()}


def successful_original():
    if not SUCCESS_RECEIPT.is_file():
        raise unittest.SkipTest("complete successful public original has not been retained")
    intake = json.loads(SUCCESS_RECEIPT.read_bytes())
    if type(intake) is not dict or set(intake) != {"archive", "sha256", "source_revision"}:
        raise AssertionError("successful-original intake receipt fields differ")
    if type(intake["archive"]) is not str or not re.fullmatch(r"run-[0-9]+-attempt[1-9][0-9]*\.zip", intake["archive"]):
        raise AssertionError("successful-original archive must be a sibling original ZIP filename")
    for name, width in (("sha256", 64), ("source_revision", 40)):
        if type(intake[name]) is not str or not re.fullmatch("[0-9a-f]{" + str(width) + "}", intake[name]):
            raise AssertionError("successful-original intake " + name + " is invalid")
    path = NATIVE / intake["archive"]
    if hashlib.sha256(path.read_bytes()).hexdigest() != intake["sha256"]:
        raise AssertionError("successful original differs from its external intake digest")
    return path, intake["sha256"], intake["source_revision"]


def edit_report(members, change):
    report = json.loads(members[REPORT])
    change(report)
    members[REPORT] = encoded(report)


def at(value, path):
    for key in path:
        value = value[key]
    return value


def replace(value, path, replacement):
    previous = at(value, path)
    if type(previous) is type(replacement) and previous == replacement:
        raise AssertionError("mutation did not change its selected value")
    at(value, path[:-1])[path[-1]] = replacement


def replace_log(members, command_id, transform):
    report = json.loads(members[REPORT])
    command = next(row for row in report["commands"] if row["id"] == command_id)
    name = PREFIX + command["log"]
    body = transform(members[name])
    members[name] = body
    command.update(log_sha256=hashlib.sha256(body).hexdigest(), log_size_bytes=len(body))
    members[REPORT] = encoded(report)


def edit_observation(members, mode, change):
    """Change both the raw result and summary, including the raw-log identity."""
    marker = replay.public_records.RESULT_PREFIX
    observed = None

    def transform(body):
        nonlocal observed
        lines = body.decode().splitlines()
        indexes = [index for index, line in enumerate(lines) if line.startswith(marker)]
        if len(indexes) != 1:
            raise AssertionError("original does not have exactly one public result")
        index = indexes[0]
        observed = json.loads(lines[index][len(marker):])
        change(observed)
        lines[index] = marker + encoded(observed).decode().strip()
        return ("\n".join(lines) + "\n").encode()

    replace_log(members, "public-" + mode, transform)
    edit_report(members, lambda report: next(cell for cell in report["cells"]
                if cell["mode"] == mode).__setitem__("observations", observed))


def replace_payload(members, relative, body, aliases=()):
    """Update every retained/original identity so semantic validation is reached."""
    if body == members[PREFIX + relative]:
        raise AssertionError("payload mutation did not change its selected bytes")
    members[PREFIX + relative] = body
    names = {relative, *aliases}
    digest = hashlib.sha256(body).hexdigest()

    def update(value):
        if type(value) is dict:
            if value.get("path") in names and {"sha256", "size_bytes"} <= set(value):
                value.update(sha256=digest, size_bytes=len(body))
            for child in value.values():
                update(child)
        elif type(value) is list:
            for child in value:
                update(child)

    edit_report(members, update)


def alter_build(members, command_id, predicate, transform):
    def changed(body):
        lines = body.decode().replace("\\\n", " ").splitlines()
        selected = [index for index, line in enumerate(lines) if predicate(line)]
        if len(selected) != 1:
            raise AssertionError("build mutation must select exactly one original command")
        index = selected[0]
        changed = transform(lines[index])
        if changed == lines[index]:
            raise AssertionError("build mutation did not change its selected command")
        lines[index] = changed
        return ("\n".join(lines) + "\n").encode()
    replace_log(members, command_id, changed)


class PublicReplayInputTests(unittest.TestCase):
    def test_invalid_external_revisions_fail_before_archive_access(self):
        for revision in (None, True, 1, "", "a" * 39, "A" * 40, "a" * 41):
            with self.subTest(revision=revision), mock.patch.object(
                    replay.diagnostics, "open_archive", side_effect=AssertionError("archive opened")):
                with self.assertRaisesRegex(ValueError, "revision"):
                    replay.replay_archive("/missing.zip", "0" * 64, expected_revision=revision)

    def test_unknown_contracts_fail_before_archive_access(self):
        for contract in (None, True, 1, "", "simx-checked-counters-native-v2"):
            with self.subTest(contract=contract), mock.patch.object(
                    replay.diagnostics, "open_archive", side_effect=AssertionError("archive opened")):
                with self.assertRaisesRegex(ValueError, "contract"):
                    replay.replay_archive("/missing.zip", "0" * 64,
                        expected_revision=FAILED_REVISION, expected_contract=contract)

    def test_nonacceptance_result_never_promotes_replay(self):
        result = replay.diagnostics.nonacceptance_result()
        for name in FALSE_CLAIMS:
            self.assertIs(result[name], False, name)
        self.assertEqual(result["native_execution"], "not_run")

    def test_cli_failure_remains_explicitly_nonqualifying(self):
        output = io.StringIO()
        with mock.patch.object(replay, "replay_archive", side_effect=ValueError("rejected fixture")), \
             redirect_stdout(output):
            code = replay.main(["--archive", "/missing.zip", "--sha256", "0" * 64,
                                "--source-revision", FAILED_REVISION])
        self.assertEqual(code, 1)
        value = json.loads(output.getvalue())
        self.assertEqual((value["outcome"], value["reason"]), ("fail", "rejected fixture"))
        for name in FALSE_CLAIMS:
            self.assertIs(value[name], False, name)
        self.assertEqual(value["native_execution"], "not_run")

    def test_only_absent_successful_original_receipt_allows_skipping(self):
        with mock.patch.object(Path, "is_file", return_value=False), \
             mock.patch.object(Path, "read_bytes", side_effect=AssertionError("opened absent receipt")):
            with self.assertRaises(unittest.SkipTest):
                successful_original()

    def test_existing_receipt_with_missing_archive_is_a_failure(self):
        intake = {"archive": "run-123-attempt1.zip", "sha256": "a" * 64,
                  "source_revision": FAILED_REVISION}
        with mock.patch.object(Path, "is_file", return_value=True), \
             mock.patch.object(Path, "read_bytes", side_effect=[encoded(intake), FileNotFoundError("missing ZIP")]):
            with self.assertRaises(FileNotFoundError):
                successful_original()

    def test_receipt_requires_external_digest_revision_and_safe_original_filename(self):
        for key, value in (("archive", "../run-123-attempt1.zip"), ("archive", "/foreign.zip"),
                           ("archive", "run-123-attempt1.zip/extra"), ("sha256", ""),
                           ("sha256", True), ("source_revision", "A" * 40), ("source_revision", None)):
            intake = {"archive": "run-123-attempt1.zip", "sha256": "a" * 64,
                      "source_revision": FAILED_REVISION}
            intake[key] = value
            with self.subTest(key=key, value=value), mock.patch.object(Path, "is_file", return_value=True), \
                 mock.patch.object(Path, "read_bytes", side_effect=[encoded(intake)]):
                with self.assertRaises(AssertionError):
                    successful_original()

    def test_existing_receipt_with_changed_archive_is_a_failure(self):
        intake = {"archive": "run-123-attempt1.zip", "sha256": "a" * 64,
                  "source_revision": FAILED_REVISION}
        with mock.patch.object(Path, "is_file", return_value=True), \
             mock.patch.object(Path, "read_bytes", side_effect=[encoded(intake), b"inert intake bytes"]):
            with self.assertRaisesRegex(AssertionError, "external intake digest"):
                successful_original()


class FailedOriginalPublicReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not FAILED_ORIGINAL.is_file():
            raise unittest.SkipTest("failed public original has not been retained in the repository")
        if hashlib.sha256(FAILED_ORIGINAL.read_bytes()).hexdigest() != FAILED_SHA256:
            raise AssertionError("failed original differs from its external intake digest")
        cls.members = read_members(FAILED_ORIGINAL)

    def test_failed_native_original_is_rejected_as_retained_data(self):
        with ExitStack() as stack:
            for owner, name in ((subprocess, "run"), (subprocess, "Popen"),
                                (zipfile.ZipFile, "extract"), (zipfile.ZipFile, "extractall")):
                stack.enter_context(mock.patch.object(owner, name, side_effect=AssertionError(name)))
            with self.assertRaisesRegex(ValueError, "producer outcome"):
                replay.replay_archive(FAILED_ORIGINAL, FAILED_SHA256, expected_revision=FAILED_REVISION)

    def test_failed_original_retains_failed_normal_and_four_blocked_modes(self):
        report = json.loads(self.members[REPORT])
        self.assertEqual(report["outcome"], "fail")
        self.assertEqual([cell["outcome"] for cell in report["cells"]], ["fail"] + ["blocked"] * 4)
        self.assertEqual(len(report["commands"]), 10)
        self.assertEqual(report["model"]["compiler_records"]["translation_units"], 45)
        self.assertEqual(report["public"]["compiler_records"]["translation_units"], 19)
        self.assertEqual(report["public"]["compiler_records"]["link_count"], 4)
        self.assertIn(b"terminal CP ring is not drained", self.members[PREFIX + "logs/public-normal.log"])
        self.assertNotIn(replay.public_records.RESULT_PREFIX.encode(),
                         self.members[PREFIX + "logs/public-normal.log"])

    def test_wrong_external_digest_precedes_failed_report_interpretation(self):
        with self.assertRaisesRegex(ValueError, "SHA-256|identity"):
            replay.replay_archive(FAILED_ORIGINAL, "0" * 64, expected_revision=FAILED_REVISION)


class OriginalPublicReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path, cls.sha256, cls.revision = successful_original()
        cls.original = read_members(cls.path)
        cls.result = replay.replay_archive(cls.path, cls.sha256, expected_revision=cls.revision)

    @classmethod
    def tearDownClass(cls):
        if hashlib.sha256(cls.path.read_bytes()).hexdigest() != cls.sha256:
            raise AssertionError("original public archive changed during replay tests")

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="p06-public-replay-test-")
        self.addCleanup(temporary.cleanup)
        self.changed_path = Path(temporary.name) / "changed.zip"

    def write_archive(self, members, extra=()):
        with zipfile.ZipFile(self.changed_path, "w", compression=zipfile.ZIP_STORED) as archive:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                for name, body in (*members.items(), *extra):
                    archive.writestr(name, body)
        return hashlib.sha256(self.changed_path.read_bytes()).hexdigest()

    def check(self, members, *, revision=None, sha256=None, prefix="public-counters"):
        digest = self.write_archive(members)
        return replay.replay_archive(self.changed_path, digest if sha256 is None else sha256,
            expected_revision=self.revision if revision is None else revision, prefix=prefix)

    def reject(self, members, pattern=".", **kwargs):
        with self.assertRaisesRegex(ValueError, pattern):
            self.check(members, **kwargs)

    def changed_report(self, change):
        members = dict(self.original)
        edit_report(members, change)
        return members

    def reject_observation(self, mode, path, replacement, pattern="."):
        members = dict(self.original)
        edit_observation(members, mode, lambda value: replace(value, path, replacement))
        self.reject(members, pattern)

    def test_original_completeness_and_nonacceptance_are_exact(self):
        result = self.result
        expected = {"outcome": "pass", "scope": "retained-data-consistency-only",
                    "retained_data_consistent": True, "retained_source_files": 676,
                    "commands_checked": 14, "cells_checked": 6, "public_cells_checked": 5,
                    "bindings_checked": 9, "stability_checks_checked": 28,
                    "transport_selectors": 33, "source_components": 40}
        for name, value in expected.items():
            self.assertEqual(result[name], value, name)
        self.assertEqual(result["source_revision"], self.revision)
        self.assertEqual(result["source_inventory_sha256"], replay.PUBLIC_V1_SOURCE_INVENTORY_SHA256)
        self.assertEqual((result["model"]["translation_units"], result["model"]["link_count"]), (45, 1))
        self.assertEqual((result["public"]["translation_units"], result["public"]["link_count"],
                          result["public"]["reused_model_objects"]), (19, 4, 44))
        self.assertEqual([cell["id"] for cell in result["public"]["cells"]],
                         ["public-" + mode for mode in replay.MODES])
        self.assertEqual([(cell["observations"]["schema_version"], cell["observations"]["checks"])
                          for cell in result["public"]["cells"]],
                         [(2, 1668), (2, 1176), (2, 1176), (2, 1173), (2, 1814)])
        for name in FALSE_CLAIMS:
            self.assertIs(result[name], False, name)
        self.assertEqual(result["native_execution"], "not_run")
        self.assertFalse(result["archive_read"]["retained_code_executed"])

    def test_replay_never_extracts_executes_or_opens_producer_paths(self):
        members = dict(self.original)
        source = "ci/project/p06_counter_public_execute.py"
        body = members[PREFIX + "artifacts/source/" + source] + b"\nraise AssertionError('archived code ran')\n"
        replace_payload(members, "artifacts/source/" + source, body, (source,))
        report = json.loads(members[REPORT])
        roots = tuple(PurePosixPath(value) for value in report["paths"].values())
        identities = set()

        def collect(value):
            if type(value) is dict:
                if {"path", "resolved_path", "sha256", "size_bytes"} <= set(value):
                    identities.update((value["path"], value["resolved_path"]))
                for child in value.values():
                    collect(child)
            elif type(value) is list:
                for child in value:
                    collect(child)
        collect(report)
        digest = self.write_archive(members)

        def guard(path):
            if isinstance(path, (str, bytes, os.PathLike)):
                candidate = PurePosixPath(os.fsdecode(path))
                self.assertFalse(str(candidate) in identities or any(candidate == root or root in candidate.parents
                                 for root in roots), "opened or resolved producer path: " + str(candidate))

        def guarded(function):
            def call(path, *args, **kwargs):
                guard(path)
                return function(path, *args, **kwargs)
            return call

        original_spec = importlib.util.spec_from_file_location
        archive_parser = ROOT / replay.diagnostics.trusted.ARCHIVE_READER_PATH

        def local_spec(name, location, *args, **kwargs):
            self.assertEqual(Path(location), archive_parser)
            return original_spec(name, location, *args, **kwargs)

        with ExitStack() as stack:
            for owner, name in ((builtins, "open"), (io, "open"), (os, "open"),
                                (Path, "resolve"), (Path, "stat")):
                stack.enter_context(mock.patch.object(owner, name, guarded(getattr(owner, name))))
            for owner, name in ((subprocess, "Popen"), (subprocess, "run"), (subprocess, "call"),
                                (subprocess, "check_call"), (subprocess, "check_output"),
                                (os, "system"), (os, "popen"), (os, "posix_spawn"),
                                (zipfile.ZipFile, "extract"), (zipfile.ZipFile, "extractall"),
                                (Path, "write_bytes"), (Path, "write_text"),
                                (replay.public_build, "validate_build"),
                                (replay.checked.native, "file_identity")):
                stack.enter_context(mock.patch.object(owner, name, side_effect=AssertionError(name)))
            stack.enter_context(mock.patch.object(importlib.util, "spec_from_file_location", local_spec))
            result = replay.replay_archive(self.changed_path, digest, expected_revision=self.revision)
        self.assertEqual(result["outcome"], "pass")
        self.assertFalse(result["retained_code_executed"])

    def test_consistency_does_not_authenticate_git_or_absent_binary_payloads(self):
        def change(report):
            for name in ("source_before", "source_after"):
                report[name]["checkout"]["tree"] = "f" * 40
            for name in ("before", "after"):
                report["bindings"]["public-artifacts"][name][0]["sha256"] = "e" * 64
        result = self.check(self.changed_report(change))
        self.assertEqual(result["scope"], "retained-data-consistency-only")
        self.assertEqual(result["public"]["recorded_artifact_identities"][0]["sha256"], "e" * 64)
        self.assertTrue(any("not a Git tree proof" in text for text in result["limitations"]))
        self.assertTrue(any("payloads are absent" in text for text in result["limitations"]))
        for name in FALSE_CLAIMS:
            self.assertIs(result[name], False, name)

    def test_external_digest_revision_and_prefix_are_mandatory(self):
        for digest in ("0" * 64, "", None, True, "A" * 64):
            with self.subTest(digest=digest):
                if digest is None:
                    with self.assertRaises(ValueError):
                        replay.replay_archive(self.path, None, expected_revision=self.revision)
                else:
                    self.reject(self.original, "SHA-256|identity", sha256=digest)
        self.reject(self.original, "revision", revision="f" * 40)
        for prefix in ("checked-counters", "../public-counters", "/public-counters", "public-counters/"):
            with self.subTest(prefix=prefix):
                self.reject(self.original, prefix=prefix)

    def test_all_producer_acceptance_flags_must_be_false(self):
        for name in FALSE_CLAIMS:
            if name in ("acceptance", "retained_code_executed"):
                continue
            for value in (True, 0):
                with self.subTest(name=name, value=value):
                    self.reject(self.changed_report(lambda report: report.__setitem__(name, value)), name)
        for mode in replay.MODES:
            for name in ("qualified", "ready_for_warm", "warm_execution", "acceptance_claimed"):
                with self.subTest(mode=mode, name=name):
                    self.reject_observation(mode, (name,), True, name)

    def test_report_keys_types_and_limits_are_strict(self):
        cases = [((), "unknown", 0), (("model",), "unknown", False),
                 (("public",), "unknown", False), (("bindings",), "unknown", {}),
                 (("cells", 0), "unknown", 0), (("commands", 0), "unknown", False)]
        for path, key, value in cases:
            with self.subTest(path=path):
                self.reject(self.changed_report(lambda report: at(report, path).__setitem__(key, value)), "fields")
        for path, replacement in ((("schema_version",), True), (("available_memory_bytes",), True),
                                  (("commands", 0, "exit_code"), False),
                                  (("commands", 0, "process_started"), 1),
                                  (("commands", 0, "log_size_bytes"), True),
                                  (("model_control", "run_process_started"), 1)):
            with self.subTest(path=path):
                self.reject(self.changed_report(lambda report: replace(report, path, replacement)))

    def test_duplicate_report_json_keys_and_nonfinite_numbers_are_rejected(self):
        for suffix in (b',"qualified":false}', b',"extra":NaN}', b',"extra":Infinity}'):
            with self.subTest(suffix=suffix):
                members = dict(self.original)
                members[REPORT] = members[REPORT].rstrip()[:-1] + suffix
                self.reject(members, "JSON|noninteger")

    def test_command_order_resources_cleanup_and_environment_are_bound(self):
        for path, replacement in ((("commands", 9, "timeout_seconds"), 181),
                                  (("commands", 9, "cleanup_complete"), False),
                                  (("commands", 9, "process_started"), False),
                                  (("commands", 9, "exit_code"), 1),
                                  (("commands", 9, "peak_rss_bytes"), 4 * 1024**3 + 1),
                                  (("commands", 9, "environment", "VORTEX_DRIVER"), "rtlsim"),
                                  (("commands", 9, "argv", -1), "warm")):
            with self.subTest(path=path):
                self.reject(self.changed_report(lambda report: replace(report, path, replacement)))
        for key in ("commands", "cells"):
            with self.subTest(key=key):
                self.reject(self.changed_report(lambda report: report[key].reverse()))
                self.reject(self.changed_report(lambda report: report[key].pop()))
                self.reject(self.changed_report(lambda report: report[key].append(deepcopy(report[key][-1]))))

    def test_all_nine_binding_groups_require_exact_before_after_identity(self):
        for group in replay.BINDINGS:
            with self.subTest(group=group):
                self.reject(self.changed_report(lambda report: report["bindings"][group]["after"][0].__setitem__(
                    "sha256", "0" * 64)), "before/after")
                self.reject(self.changed_report(lambda report: report["bindings"][group]["before"].pop()))
        for key, value in (("path", "/foreign/object.o"), ("resolved_path", "/foreign/object.o"),
                           ("sha256", "wrong"), ("size_bytes", True)):
            with self.subTest(key=key):
                self.reject(self.changed_report(lambda report: report["bindings"]["public-artifacts"]["before"][0]
                            .__setitem__(key, value)))

    def test_all_twenty_eight_stability_rows_are_required_in_order(self):
        for index in (0, 9, 10, 11, 12, 17, 18, 27):
            with self.subTest(index=index):
                self.reject(self.changed_report(lambda report: report["stability_checks"].pop(index)), "stability")
        self.reject(self.changed_report(lambda report: report["stability_checks"].reverse()), "stability")
        self.reject(self.changed_report(lambda report: report["stability_checks"][-1]["bindings"].pop()), "stability")

    def test_source_revision_cleanliness_and_before_after_must_agree(self):
        paths = (("source_after", "checkout", "revision"), ("source_before", "checkout", "tree"))
        for path in paths:
            with self.subTest(path=path):
                self.reject(self.changed_report(lambda report: replace(report, path, "f" * 40)), "source before/after")
        for field, value in (("dirty", True), ("changed_paths", ["sim/simx/core.cpp"]),
                             ("untracked_paths", ["injected.cpp"]), ("blockers", ["source differs"])):
            def change(report):
                for key in ("source_before", "source_after"):
                    report[key]["checkout"][field] = value
            with self.subTest(field=field):
                self.reject(self.changed_report(change), "checkout")

    def test_full_source_inventory_cannot_drop_an_uncompiled_header(self):
        report = json.loads(self.original[REPORT])
        name = next(row["path"] for row in report["source_before"]["files"]
                    if row["path"].endswith(".h") and row["path"] not in replay.SOURCE_REQUIRED)
        members = dict(self.original)
        del members[PREFIX + "artifacts/source/" + name]
        def change(value):
            for key in ("source_before", "source_after"):
                value[key]["files"] = [row for row in value[key]["files"] if row["path"] != name]
            value["retained_sources"] = [row for row in value["retained_sources"]
                                         if row["path"] != "artifacts/source/" + name]
        edit_report(members, change)
        self.reject(members, "versioned source inventory")

    def test_retained_source_bytes_and_frozen_profile_are_verified(self):
        members = dict(self.original)
        name = PREFIX + "artifacts/source/sw/runtime/common/device.cpp"
        members[name] += b"\n// damaged retained body\n"
        self.reject(members, "digest|size|identity")
        members = dict(self.original)
        name = "profiles/p02-tfr.json"
        body = members[PREFIX + "artifacts/source/" + name] + b"\n"
        replace_payload(members, "artifacts/source/" + name, body, (name,))
        self.reject(members, "frozen p02-tfr profile")

    def test_tools_interpreter_dependencies_and_paths_require_closure(self):
        for path, value in ((("tools_after", "tools", "g++", "sha256"), "0" * 64),
                            (("tools_stable",), False), (("source_stable",), 1),
                            (("interpreter", "version", 2), 13)):
            with self.subTest(path=path):
                self.reject(self.changed_report(lambda report: replace(report, path, value)))
        for selection in ("tools", "dependencies"):
            def change(report):
                for key in ("tools_before", "tools_after"):
                    selected = report[key][selection]
                    del selected[next(iter(selected))]
            with self.subTest(selection=selection):
                self.reject(self.changed_report(change))
        def mismatched_python(report):
            for key in ("tools_before", "tools_after"):
                report[key]["tools"]["executing_python"]["sha256"] = "0" * 64
        self.reject(self.changed_report(mismatched_python), "executing/PATH Python")

    def test_configuration_copies_template_expansion_and_header_probe_are_bound(self):
        report = json.loads(self.original[REPORT])
        build = report["build_dir"]
        cases = [("config.mk", lambda body: body.replace(b"p02-tfr", b"p02-other"), "config.mk"),
                 (".config.stamp", lambda body: body.replace(b"XLEN=64", b"XLEN=32"), "configure stamp"),
                 (replay.PUBLIC_MAKEFILE, lambda body: body + b"\n# changed copy\n", "copied source"),
                 (replay.diagnostics.HEADER_PROBE, lambda body: body + b"#define NDEBUG 0\n", "header probe")]
        for relative, transform, pattern in cases:
            with self.subTest(relative=relative):
                members = dict(self.original)
                name = "artifacts/checked/" + relative
                replace_payload(members, name, transform(members[PREFIX + name]), (build + "/" + relative,))
                self.reject(members, pattern)

    def test_generated_tcu_must_equal_original_plus_exact_footer(self):
        members = dict(self.original)
        relative = replay.checked.GENERATED_TCU
        name = "artifacts/checked/" + relative
        build = json.loads(members[REPORT])["build_dir"]
        replace_payload(members, name, members[PREFIX + name] + b"\n// generated source changed\n",
                        (build + "/" + relative,))
        self.reject(members, "generated|TCU|diagnostic")

    def test_prior_model_summary_is_recomputed_from_original_log(self):
        self.reject(self.changed_report(lambda report: report["model"]["compiler_records"].__setitem__(
            "translation_units", 44)), "recomputed compiler")
        members = dict(self.original)
        alter_build(members, "checked-build", lambda line: " -c " in line and line.endswith("/obj/core.o"),
                    lambda line: line.replace(" -c ", " -fno-access-control -c "))
        self.reject(members, "flags|access")
        self.reject(self.changed_report(lambda report: report["public"]["compiler_records"]
                    ["reused_model_object_identities"][0].__setitem__("sha256", "0" * 64)), "recomputed public")

    def test_public_summaries_cannot_replace_original_build_commands(self):
        for field, value in (("translation_units", 18), ("link_count", 3), ("wrapped_processor_symbols", [])):
            with self.subTest(field=field):
                self.reject(self.changed_report(lambda report: report["public"]["compiler_records"]
                            .__setitem__(field, value)), "recomputed public")
        members = dict(self.original)
        replace_log(members, "public-build", lambda body: b"build summary: 19 compiles, 4 links passed\n")
        self.reject(members, "19 new compiles")

    def test_public_dso_links_require_exact_object_roles_and_libraries(self):
        cases = [("libchecked-simx.so", lambda line: line.replace(" -lramulator", " -lother", 1)),
                 ("libvortex-simx.so", lambda line: line.replace("-lchecked-simx", "-lsimx")),
                 ("libvortex.so", lambda line: line.replace(" -pthread", " -lforeign")),
                 ("checked_public_test", lambda line: line.replace("-lvortex-simx", "-lsimx"))]
        for output, change in cases:
            with self.subTest(output=output):
                members = dict(self.original)
                alter_build(members, "public-build", lambda line: " -c " not in line
                            and line.endswith("/" + output), change)
                self.reject(members, "link")

    def test_all_five_processor_wraps_are_required_on_backend_dso(self):
        for symbol in replay.public_build.WRAPS:
            with self.subTest(symbol=symbol):
                members = dict(self.original)
                alter_build(members, "public-build", lambda line: line.endswith("/libvortex-simx.so"),
                            lambda line: line.replace(" -Wl,--wrap=" + symbol, ""))
                self.reject(members, "wraps")

    def test_public_compilation_roles_cannot_use_other_source_or_flags(self):
        cases = [("/obj/public_main.o", lambda line: line.replace("public_main.cpp", "public_hooks.cpp")),
                 ("/obj/backend/vortex.o", lambda line: line.replace("-DSIMX_CHECKED_COUNTERS=1",
                                                                               "-DSIMX_CHECKED_COUNTERS=0")),
                 ("/obj/runtime/common/device.o", lambda line: line.replace(" -O2 ", " -O0 "))]
        for suffix, transform in cases:
            with self.subTest(suffix=suffix):
                members = dict(self.original)
                alter_build(members, "public-build", lambda line: " -c " in line and line.endswith(suffix), transform)
                self.reject(members, "source|flags")

    def test_suppressed_dma_requires_original_ram_and_complemented_attempt(self):
        for mode in ("immediate-overflow", "delayed-overflow", "cache-overflow"):
            for name in ("before", "attempted", "after"):
                for index in range(3):
                    with self.subTest(mode=mode, name=name, index=index):
                        self.reject_observation(mode, ("failure", "suppression", "dma", name, index), 0,
                                                "failure.suppression.dma")
            self.reject_observation(mode, ("failure", "suppression", "dma", "status"), 0, "dma.status")

    def test_terminal_counters_components_halves_and_clock_are_verified(self):
        changes = [(("rows", 16, "value"), 0), (("rows", 0, "low", "value"), 1),
                   (("rows", 0, "high", "value"), 0), (("rows", 32, "components"), 1),
                   (("rows", 16, "low", "tag"), 0), (("rows", 0, "high", "sequence"), 1),
                   (("rows", 0, "low", "ticks_after"), 0), (("rows", 0, "high", "reset_after"), 0),
                   (("rows", 0, "low", "class_after"), 1), (("after", "ticks"), 0),
                   (("before", "components"), [0] * 39), (("components",), 39),
                   (("selectors",), 32), (("unavailable_unqueried",), 11)]
        for path, value in changes:
            with self.subTest(path=path):
                self.reject_observation("coherent-terminal", ("terminal_snapshots", 0) + path, value,
                                        "terminal_snapshots")

    def test_terminal_requires_exclusive_ownership_retired_cp_and_destruction(self):
        for path, value in ((("device_refs",), 2), (("queues",), 1), (("buffers",), 1),
                            (("extra_retain_rejected",), False), (("before", "idle"), False),
                            (("before", "any_running"), True), (("before", "pending_reads"), 1),
                            (("cp_after", "head_writeback_raw"), 1),
                            (("cp_after", "tail_register_pair_raw"), 64),
                            (("cp_after", "runtime_tail"), 64), (("cp_after", "retired"), 0)):
            with self.subTest(path=path):
                self.reject_observation("normal", ("terminal_snapshots", 0) + path, value, "terminal_snapshots")
        for index in range(2):
            for path, value in ((("completed",), False), (("ticks_after",), 1), (("reset_after",), 0),
                                (("idle_after",), False), (("before", "generation"), 9)):
                with self.subTest(index=index, path=path):
                    self.reject_observation("normal", ("destructions", index) + path, value, "destructions")

    def test_overflow_requires_original_callback_and_fresh_context_evidence(self):
        for mode in ("immediate-overflow", "delayed-overflow", "cache-overflow"):
            for key in ("overflow_errors", "run_entries", "dcr_write_completed", "suppressed_requests"):
                with self.subTest(mode=mode, key=key):
                    self.reject_observation(mode, (key,), 0, "result")
            self.reject_observation(mode, ("fresh_context_success",), False, "result")
            self.reject_observation(mode, ("terminal_failure",), False, "result")
            for field in ("run", "read", "write", "overflows"):
                with self.subTest(mode=mode, field=field):
                    self.reject_observation(mode, ("failure", "suppression", "after_entries", field), 99,
                                            "failure.suppression")
        self.reject_observation("delayed-overflow", ("failure", "after", "ticks"), 0, "delayed native updater")
        self.reject_observation("cache-overflow", ("failure", "reads", 0, "overflow"), False, "failure.reads")
        self.reject_observation("cache-overflow", ("failure", "trigger_query", "after"), 0, "trigger_query")
        self.reject_observation("immediate-overflow", ("failure", "suppression", "queries", 0, "after"), 0,
                                "suppression.queries")

    def test_observation_types_keys_and_integer_bounds_are_strict(self):
        for mode, path, value in (("normal", ("checked",), 1), ("normal", ("checks",), True),
                                  ("normal", ("terminal_snapshots", 0, "before", "ticks"), True),
                                  ("normal", ("terminal_snapshots", 0, "rows", 0, "value"), -1),
                                  ("normal", ("terminal_snapshots", 0, "rows", 0, "low", "value"), 1 << 32),
                                  ("cache-overflow", ("failure", "suppression", "dma", "before", 0), True)):
            with self.subTest(mode=mode, path=path):
                self.reject_observation(mode, path, value)
        for path in ((), ("terminal_snapshots", 0), ("terminal_snapshots", 0, "cp_after"),
                     ("terminal_snapshots", 0, "rows", 0, "high")):
            members = dict(self.original)
            edit_observation(members, "normal", lambda value: at(value, path).__setitem__("unknown", False))
            with self.subTest(path=path):
                self.reject(members, "fields")

    def test_public_result_duplicate_keys_numbers_and_record_boundaries_are_strict(self):
        marker = replay.public_records.RESULT_PREFIX.encode()

        def schema_number(body, replacement):
            token = b'"schema_version":2'
            self.assertEqual(body.count(token), 1, "original schema-2 token is not unique")
            return body.replace(token, b'"schema_version":' + replacement, 1)

        transformations = [lambda body: body.replace(marker + b"{", marker + b'{"checked":true,', 1),
                           lambda body: schema_number(body, b"2.0"),
                           lambda body: schema_number(body, b"NaN"),
                           lambda body: schema_number(body, b"Infinity"),
                           lambda body: body + b"extra trailing result\n",
                           lambda body: b"ERROR unrelated crash\n" + body,
                           lambda body: body + body]
        for index, transform in enumerate(transformations):
            with self.subTest(index=index):
                members = dict(self.original)
                # Canonicalize the native JSON first so token replacements are exact.
                edit_observation(members, "normal", lambda value: None)
                def changed(body):
                    mutated = transform(body)
                    self.assertNotEqual(mutated, body, "raw result mutation did not change its input")
                    return mutated
                replace_log(members, "public-normal", changed)
                self.reject(members, "public")

    def test_raw_observations_cannot_be_replaced_by_a_summary_only(self):
        members = dict(self.original)
        replace_log(members, "public-normal", lambda body: b"all public observations passed\n")
        self.reject(members, "unique final result")
        self.reject(self.changed_report(lambda report: report["cells"][0]["observations"]
                    .__setitem__("checks", 0)), "recomputed diagnostic observations")

    def test_extra_missing_duplicate_and_unsafe_members_are_rejected(self):
        members = dict(self.original)
        members[PREFIX + "extra.py"] = b"raise AssertionError('unconsumed payload')\n"
        self.reject(members, "member closure")
        members = dict(self.original)
        del members[PREFIX + "logs/public-coherent-terminal.log"]
        self.reject(members, "missing")
        for name in ("../escape", "/absolute", "a/../b", "a\\b", "C:drive", REPORT):
            with self.subTest(name=name):
                digest = self.write_archive(self.original, [(name, b"inert")])
                with self.assertRaisesRegex(ValueError, "member|duplicate"):
                    replay.replay_archive(self.changed_path, digest, expected_revision=self.revision)
        symlink = zipfile.ZipInfo(PREFIX + "link")
        symlink.create_system = 3
        symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
        digest = self.write_archive(self.original, [(symlink, b"/foreign/target")])
        with self.assertRaisesRegex(ValueError, "symlink|special"):
            replay.replay_archive(self.changed_path, digest, expected_revision=self.revision)


if __name__ == "__main__":
    unittest.main()
