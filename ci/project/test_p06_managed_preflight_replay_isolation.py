# SPDX-License-Identifier: Apache-2.0
"""Whole-reader isolation checks against the independently pinned original."""

import builtins
from contextlib import ExitStack
import ctypes
import encodings.cp437  # ZIP's standard codec must load before the import guard.
import importlib.util
import io
import _io
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import warnings
import zipfile

import p06_managed_preflight_replay as reader
from p06_managed_preflight_replay_test_support import (
    ORIGINAL, ORIGINAL_SHA256, PREFIX, REPORT, ROOT, SOURCE_INVENTORY,
    SOURCE_DERIVATION, Packet, digest_file, replay,
)
from test_p06_counter_diagnostics_replay import (
    ARCHIVE_READER_SOURCE, ArchiveReaderExecGuard,
)


CURRENT_MODULES = (
    "baseline_inventory", "baseline_matrix", "baseline_packet_contract", "baseline_packet_io",
    "baseline_process", "compiler_records", "p02_fixture_oracle", "p02_layout_fixture_oracle",
    "p02_matrix", "p02_matrix_records", "p02_wmma_fixtures", "p02_wmma_numerical_fixture_oracle",
    "p03_execute", "p03_execution_records", "p04_execution_records", "p04_fixture_adapter",
    "p04_model_contract", "p04_reference", "p06_compiler_records", "p06_contract",
    "p06_managed_preflight_application_build", "p06_managed_preflight_build",
    "p06_managed_preflight_backend_build",
    "p06_managed_preflight_contract", "p06_managed_preflight_derivation",
    "p06_managed_preflight_execute", "p06_managed_preflight_generated",
    "p06_managed_preflight_records", "p06_managed_preflight_replay",
    "p06_managed_preflight_replay_build", "p06_managed_preflight_replay_hosted",
    "p06_managed_preflight_sources", "p06_records", "p06_replay", "p06_warm_analyze",
    "p06_warm_compiler_records", "p06_warm_contract", "p06_warm_execute", "p06_warm_records",
    "p06_warm_replay", "p06_workspace_compiler_records", "p06_workspace_execute",
    "p06_workspace_records", "p06_workspace_replay", "preflight",
)
CURRENT_SOURCES = tuple("ci/project/" + name + ".py" for name in CURRENT_MODULES) + ("ci/gen_config.py",)
CURRENT_DATA = (
    "VX_config.toml", "VX_types.toml", "profiles/p02-tfr.json",
    "ci/project/p06_warm_contract.json",
    "ci/project/fixtures/p02_layout_v1.json", "ci/project/fixtures/p02_tfr_v1.json",
    "ci/project/fixtures/p02_wmma_numerical_v1.json",
    "sw/common/ai_matmul_args.h", "sw/common/ai_matmul_profile.h",
    "sw/kernel/ai/matmul.cpp", "tests/regression/ai_bench_common/counters.h",
    "tests/regression/sgemm_tcu/p02_fixtures.h",
)


class ExplicitReadGuard:
    def __init__(self, test, inputs):
        self.test = test
        self.cwd = PurePosixPath(os.getcwd())
        files = {ROOT / name for name in (*CURRENT_SOURCES, *CURRENT_DATA, ARCHIVE_READER_SOURCE)}
        files.update(Path(name) for name in inputs)
        # The actual code object is separately compared with the pinned source.
        files.add(Path(importlib.util.cache_from_source(str(ROOT / ARCHIVE_READER_SOURCE))))
        self.files = {PurePosixPath(name) for name in files}
        self.directories = {parent for name in self.files for parent in name.parents}
        self.descriptors = {}
        self.opened = set()

    def candidate(self, path, options):
        if type(path) is int:
            self.test.assertIn(path, self.descriptors, "unapproved replay file descriptor")
            return self.descriptors[path]
        value = PurePosixPath(os.fsdecode(path))
        self.test.assertNotIn("..", value.parts, "noncanonical replay file path")
        if not value.is_absolute():
            descriptor = options.get("dir_fd")
            if descriptor is None:
                value = self.cwd / value
            else:
                self.test.assertIn(descriptor, self.descriptors, "unapproved replay directory descriptor")
                value = self.descriptors[descriptor] / value
        return value

    def check(self, path, options, *, directory=False):
        value = self.candidate(path, options)
        approved = self.directories if directory else self.files | self.directories
        if value not in approved:
            raise AssertionError("unapproved replay path: " + str(value))
        return value

    def wrap(self, owner, name):
        original = getattr(owner, name)

        def checked(path, *args, **options):
            value = self.check(path, options)
            if name in ("open", "open_code"):
                if owner is os:
                    flags = options.get("flags", args[0] if args else os.O_RDONLY)
                    self.test.assertFalse(flags & (os.O_ACCMODE | os.O_CREAT | os.O_TRUNC | os.O_APPEND),
                                          "replay attempted a write-capable open")
                    directory = bool(flags & os.O_DIRECTORY)
                    self.test.assertIn(value, self.directories if directory else self.files)
                    descriptor = original(path, *args, **options)
                    self.descriptors[descriptor] = value
                    self.opened.add(value)
                    return descriptor
                mode = options.get("mode", args[0] if args else "r")
                if name == "open_code":
                    mode = "rb"
                self.test.assertIn(mode, ("r", "rb", "rt"), "replay attempted a write-capable open")
                self.test.assertIn(value, self.files)
                self.opened.add(value)
            return original(path, *args, **options)

        return checked

    def install(self, stack):
        capabilities = {name: set(getattr(os, name)) for name in
                        ("supports_dir_fd", "supports_follow_symlinks", "supports_fd")}
        for owner, names in (
            (builtins, ("open",)), (io, ("open", "open_code")), (_io, ("open_code",)),
            (os, ("open", "stat", "lstat", "readlink", "access")),
            (Path, ("open", "resolve", "stat", "lstat", "exists", "is_file", "is_dir")),
        ):
            for name in names:
                original = getattr(owner, name)
                wrapped = self.wrap(owner, name)
                stack.enter_context(mock.patch.object(owner, name, wrapped))
                if owner is os:
                    for functions in capabilities.values():
                        if original in functions:
                            functions.add(wrapped)
        # Preserve only actual platform capabilities of the wrapped functions.
        for name, functions in capabilities.items():
            stack.enter_context(mock.patch.object(os, name, functions))
        original_close = os.close

        def close(descriptor):
            try:
                return original_close(descriptor)
            finally:
                self.descriptors.pop(descriptor, None)

        stack.enter_context(mock.patch.object(os, "close", close))
        for owner, name in ((os, "listdir"), (os, "scandir"), (Path, "glob"), (Path, "rglob"),
                            (Path, "write_bytes"), (Path, "write_text")):
            stack.enter_context(mock.patch.object(owner, name, side_effect=AssertionError(
                "replay attempted filesystem enumeration or writing")))


class ManagedPreflightReplayIsolationTests(unittest.TestCase):
    def guarded_replay(self, path=ORIGINAL, digest=ORIGINAL_SHA256):
        guard = ExplicitReadGuard(self, (path, SOURCE_INVENTORY, SOURCE_DERIVATION))
        execute = ArchiveReaderExecGuard(self)
        original_spec = importlib.util.spec_from_file_location
        archive_source = ROOT / ARCHIVE_READER_SOURCE

        def current_spec(name, location, *args, **options):
            self.assertEqual(PurePosixPath(location), PurePosixPath(archive_source))
            return original_spec(name, location, *args, **options)

        calls = []
        with ExitStack() as stack:
            guard.install(stack)
            for owner, name in (
                (subprocess, "Popen"), (subprocess, "run"), (subprocess, "call"),
                (subprocess, "check_call"), (subprocess, "check_output"),
                (os, "system"), (os, "popen"), (os, "posix_spawn"), (os, "posix_spawnp"),
                (os, "execv"), (os, "execve"), (ctypes, "CDLL"), (ctypes, "PyDLL"),
                (zipfile.ZipFile, "extract"), (zipfile.ZipFile, "extractall"),
            ):
                calls.append(stack.enter_context(mock.patch.object(owner, name,
                    side_effect=AssertionError("replay executed or extracted: " + name))))
            stack.enter_context(mock.patch.object(importlib.util, "spec_from_file_location", current_spec))
            stack.enter_context(mock.patch.object(builtins, "exec", execute))
            result = replay(path, digest)
        for call in calls:
            call.assert_not_called()
        self.assertEqual(execute.executed, [str(archive_source)])
        self.assertTrue({PurePosixPath(ROOT / name) for name in CURRENT_SOURCES} <= guard.opened)
        return result

    def test_original_reads_only_explicit_current_inputs_and_executes_no_payloads(self):
        with Packet() as packet:
            report = packet.report
            tools = packet.json(report["tools_before"]["path"])
        collocated = {Path(row["path"]) for row in tools.values() if Path(row["path"]).is_file()}
        self.assertTrue(collocated, "a recorded producer tool must actually exist for this control")
        guard = ExplicitReadGuard(self, (ORIGINAL, SOURCE_INVENTORY, SOURCE_DERIVATION))
        with ExitStack() as stack:
            guard.install(stack)
            for path in collocated:
                with self.subTest(recorded_tool=path), self.assertRaisesRegex(
                        AssertionError, "unapproved replay path"):
                    path.read_bytes()
        result = self.guarded_replay()
        self.assertEqual(result["outcome"], "pass")
        self.assertEqual({row["path"] for row in result["trusted_replay_sources"]}, set(CURRENT_SOURCES))
        self.assertEqual(result["counts"]["launches"], 132)
        self.assertEqual(result["counts"]["checked_words"], 4224)
        self.assertIs(result["retained_code_executed"], False)
        self.assertEqual(result["native_execution"], "not_run")

    def test_guard_rejects_collocated_source_and_directory_relative_bypasses(self):
        existing = ROOT / "sim/simx/core.cpp"
        self.assertTrue(existing.is_file())
        guard = ExplicitReadGuard(self, (ORIGINAL, SOURCE_INVENTORY, SOURCE_DERIVATION))
        with ExitStack() as stack:
            guard.install(stack)
            for operation in (lambda: existing.read_bytes(), lambda: existing.resolve(),
                              lambda: os.stat(existing), lambda: io.open(existing, "rb")):
                with self.assertRaisesRegex(AssertionError, "unapproved replay path"):
                    operation()
            descriptor = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY)
            try:
                for operation in (
                    lambda: os.open("sim/simx/core.cpp", os.O_RDONLY, dir_fd=descriptor),
                    lambda: os.stat("sim/simx/core.cpp", dir_fd=descriptor),
                ):
                    with self.assertRaisesRegex(AssertionError, "unapproved replay path"):
                        operation()
            finally:
                os.close(descriptor)
            with self.assertRaisesRegex(AssertionError, "write-capable"):
                (ROOT / CURRENT_SOURCES[0]).open("w")

    def test_executable_retained_python_stays_inert_after_descriptor_rehash(self):
        with tempfile.TemporaryDirectory(prefix="p06-inert-source-") as directory, Packet() as packet:
            source = "ci/project/p06_managed_preflight_execute.py"
            relative = "artifacts/source/" + source
            body = packet[PREFIX + relative] + b"\nraise AssertionError('ARCHIVED_PYTHON_EXECUTED')\n"
            packet.replace_retained(relative, body, aliases=(source,))
            path = Path(directory) / "source.zip"
            digest = packet.write(path)
            with self.assertRaisesRegex(ValueError,
                    "retained source descriptors differ from the independently pinned inventory"):
                self.guarded_replay(path, digest)

    def test_wrong_external_archive_digest_rejects_before_zip_parsing(self):
        with mock.patch.object(zipfile.ZipFile, "__init__", side_effect=AssertionError("parsed unpinned ZIP")) as parse:
            with self.assertRaisesRegex(ValueError, "original ZIP SHA-256 differs"):
                replay(ORIGINAL, "0" * 64)
        parse.assert_not_called()

    def test_linked_archive_file_and_parent_reject_even_with_correct_digest(self):
        with tempfile.TemporaryDirectory(prefix="p06-inert-links-") as directory:
            root = Path(directory)
            file_alias = root / "archive.zip"
            file_alias.symlink_to(ORIGINAL)
            parent_alias = root / "native"
            parent_alias.symlink_to(ORIGINAL.parent, target_is_directory=True)
            for path in (file_alias, parent_alias / ORIGINAL.name):
                with self.subTest(path=path), self.assertRaisesRegex(ValueError, "canonical without symlinks"):
                    replay(path, ORIGINAL_SHA256)

    def changed_zip(self, entries):
        with tempfile.TemporaryDirectory(prefix="p06-inert-zip-") as directory, Packet() as packet:
            path = Path(directory) / "packet.zip"
            packet.write(path)
            with warnings.catch_warnings(), zipfile.ZipFile(path, "a") as archive:
                warnings.simplefilter("ignore", UserWarning)
                for name, body in entries:
                    archive.writestr(name, body)
            return replay(path, digest_file(path))

    def test_duplicate_and_file_parent_collisions_are_rejected(self):
        for name, reason in ((REPORT, "duplicate ZIP member"),
                             (REPORT + "/", "duplicate ZIP member"),
                             ("managed-preflight", "file shadows a parent directory")):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, reason):
                self.changed_zip(((name, b""),))

    def test_unsafe_member_names_are_rejected_after_archive_rehash(self):
        for name in ("../outside.py", "/absolute.py", "C:/outside.py", "managed-preflight\\outside.py"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "retained member name"):
                self.changed_zip(((name, b"raise AssertionError('not executed')"),))

    def test_symlink_and_special_members_are_rejected_without_extraction(self):
        for kind in (stat.S_IFLNK, stat.S_IFIFO):
            member = zipfile.ZipInfo("managed-preflight/untrusted")
            member.create_system = 3
            member.external_attr = (kind | 0o777) << 16
            with self.subTest(kind=kind), \
                 mock.patch.object(zipfile.ZipFile, "extract", side_effect=AssertionError("extracted")), \
                 mock.patch.object(zipfile.ZipFile, "extractall", side_effect=AssertionError("extracted")), \
                 self.assertRaisesRegex(ValueError, "symlink or special member"):
                self.changed_zip(((member, b"/unrelated/target"),))

    def test_current_helper_origin_substitution_rejects_before_archive_use(self):
        module = sys.modules["p06_managed_preflight_records"]
        with mock.patch.object(module, "__file__", "/unrelated/retained/p06_managed_preflight_records.py"), \
             mock.patch.object(reader, "_archive_api", side_effect=AssertionError("opened archive")) as api:
            with self.assertRaisesRegex(ValueError, "loaded outside the trusted repository"):
                replay()
        api.assert_not_called()

    def test_forged_current_archive_parser_cannot_execute_under_identity_guard(self):
        with mock.patch.object(importlib.machinery.SourceFileLoader, "get_code",
                               side_effect=AssertionError("unverified cached code requested")) as loader:
            result = self.guarded_replay()
        loader.assert_not_called()
        self.assertEqual(result["outcome"], "pass")

    def test_nested_hosted_wrapper_closes_whole_archive_inventory(self):
        def wrap(packet):
            for name in tuple(packet):
                packet["outer/inner/" + name] = packet[name]
                del packet[name]

        with tempfile.TemporaryDirectory(prefix="p06-inert-wrapper-") as directory, Packet() as packet:
            wrap(packet)
            good = Path(directory) / "complete.zip"
            digest = packet.write(good)
            result = replay(good, digest, prefix="outer/inner/managed-preflight")
            self.assertEqual(result["hosted_identity"]["validation"], "pass")
            packet["outer/unbound.py"] = b"raise AssertionError('not executed')\n"
            bad = Path(directory) / "unbound.zip"
            digest = packet.write(bad)
            with self.assertRaisesRegex(ValueError, "whole archive hosted inventory"):
                replay(bad, digest, prefix="outer/inner/managed-preflight")

    def test_dispatch_ref_accepts_valid_tag_and_rejects_lock_component(self):
        with tempfile.TemporaryDirectory(prefix="p06-inert-ref-") as directory, Packet() as packet:
            packet.edit_json("job.json", lambda row: row.update(
                GITHUB_EVENT_NAME="workflow_dispatch", GITHUB_REF="refs/tags/review/v1.0"))
            good = Path(directory) / "valid.zip"
            result = replay(good, packet.write(good))
            self.assertEqual(result["hosted_identity"]["job"]["GITHUB_REF"], "refs/tags/review/v1.0")
            self.assertIs(result["hosted_identity"]["origin_authenticated"], False)
            packet.edit_json("job.json", lambda row: row.update(GITHUB_REF="refs/tags/review.lock/v1"))
            bad = Path(directory) / "invalid.zip"
            with self.assertRaisesRegex(ValueError, "invalid hosted Git ref"):
                replay(bad, packet.write(bad))


if __name__ == "__main__":
    unittest.main()
