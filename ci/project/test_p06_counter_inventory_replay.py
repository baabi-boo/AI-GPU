# SPDX-License-Identifier: Apache-2.0
"""Focused external-inventory integration checks for inert counter replay.

The checked positive is an original retained native ZIP. Added helper bodies,
changed revision labels and log mutations are synthetic consistency fixtures,
never new native execution evidence. The failed public original stays failed;
its source-only checks do not fabricate a successful public packet.
"""

import builtins
from contextlib import ExitStack, redirect_stdout
import copy
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import tempfile
import unittest
from unittest import mock
import zipfile

import p06_counter_diagnostics_replay as checked
import p06_counter_public_replay as public
import p06_counter_source_inventory as inventory


ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / "docs/project/evidence/p06-counter-diagnostics/native"
CHECKED_ARCHIVE = NATIVE / "run-45026112992-attempt1.zip"
CHECKED_SHA256 = "c4a7ae49259bbb72066d55f7c3e733ce5696f215175ce308f654e1cec9e9c13f"
CHECKED_REVISION = "407ab9fea5e4f793a2a5088f566a87f3e631aa84"
PUBLIC_ARCHIVE = NATIVE / "run-45029135146-attempt1.zip"
PUBLIC_SHA256 = "d628813ec8815140830825adef22cd2ea9191707686931e49145d5a4e4247db5"
PUBLIC_REVISION = "81ed6871634fefbf5c78fb27cf10dce913bd4d9c"
ADDED_HELPER = "ci/project/p06_future_diagnostic_helper.py"
ADDED_BODY = b"raise AssertionError('synthetic retained helper must remain inert')\n"
HEADER = "sim/common/axi_latency_pipe.h"
SYNTHETIC_REVISION = "a" * 40
FALSE_CLAIMS = (
    "qualified", "ready_for_warm", "warm_execution", "acceptance", "acceptance_claimed",
    "phase_acceptance", "performance_acceptance", "full_warm_coverage", "retained_code_executed",
)


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def descriptor(name, body):
    return {"path": name, "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)}


def source_manifest(report, contract):
    return {"schema_version": 1, "contract_id": inventory.CONTRACT_ID,
            "producer_contract_id": contract, "source_revision": report["expected_revision"],
            "sources": copy.deepcopy(report["source_before"]["files"])}


def edit_report(members, prefix, transform):
    name = prefix + "/report.json"
    report = json.loads(members[name])
    transform(report)
    members[name] = encoded(report)


def add_helper(members, prefix):
    """Make only a synthetic retained-body/log/revision consistency mutation."""
    result = dict(members)
    retained = "artifacts/source/" + ADDED_HELPER
    result[prefix + "/" + retained] = ADDED_BODY

    def change(report):
        report["expected_revision"] = SYNTHETIC_REVISION
        for key in ("source_before", "source_after"):
            report[key]["checkout"]["revision"] = SYNTHETIC_REVISION
            report[key]["files"].append(descriptor(ADDED_HELPER, ADDED_BODY))
            report[key]["files"].sort(key=lambda row: row["path"])
        report["retained_sources"].append(descriptor(retained, ADDED_BODY))
        report["retained_sources"].sort(key=lambda row: row["path"])
        command = next(row for row in report["commands"] if row["id"] == "version-make")
        log = prefix + "/" + command["log"]
        result[log] += b"synthetic consistency fixture: added retained helper\n"
        command.update(log_sha256=hashlib.sha256(result[log]).hexdigest(), log_size_bytes=len(result[log]))

    edit_report(result, prefix, change)
    return result


class CounterInventoryReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixtures = []
        for reader, path, sha256, revision, prefix in (
            (checked, CHECKED_ARCHIVE, CHECKED_SHA256, CHECKED_REVISION, "checked-counters"),
            (public, PUBLIC_ARCHIVE, PUBLIC_SHA256, PUBLIC_REVISION, "public-counters"),
        ):
            if hashlib.sha256(path.read_bytes()).hexdigest() != sha256:
                raise AssertionError("original diagnostic archive identity differs")
            with zipfile.ZipFile(path) as archive:
                members = {row.filename: archive.read(row) for row in archive.infolist() if not row.is_dir()}
            report = json.loads(members[prefix + "/report.json"])
            cls.fixtures.append({"reader": reader, "path": path, "sha256": sha256,
                "revision": revision, "prefix": prefix, "members": members, "report": report})

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="p06-inventory-replay-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.manifest_path = self.root / "expected-sources.json"
        self.archive_path = self.root / "synthetic-consistency.zip"

    def manifest(self, fixture, *, members=None, transform=None):
        report = fixture["report"] if members is None else json.loads(members[fixture["prefix"] + "/report.json"])
        result = source_manifest(report, fixture["reader"].CONTRACT_ID)
        if transform is not None:
            transform(result)
        body = encoded(result)
        self.manifest_path.write_bytes(body)
        return {"source_inventory": self.manifest_path, "source_inventory_sha256": hashlib.sha256(body).hexdigest()}

    def archive(self, members):
        with zipfile.ZipFile(self.archive_path, "w", compression=zipfile.ZIP_STORED) as archive:
            for name, body in sorted(members.items()):
                archive.writestr(name, body)
        return self.archive_path, hashlib.sha256(self.archive_path.read_bytes()).hexdigest()

    def replay(self, fixture, *, members=None, revision=None, **kwargs):
        path, sha256 = (fixture["path"], fixture["sha256"]) if members is None else self.archive(members)
        return fixture["reader"].replay_archive(path, sha256,
            expected_revision=fixture["revision"] if revision is None else revision, **kwargs)

    def assert_nonacceptance(self, result):
        self.assertEqual(result["native_execution"], "not_run")
        for name in FALSE_CLAIMS:
            self.assertIs(result[name], False, name)

    def test_original_checked_inventory_remains_pinned_without_manifest(self):
        result = self.replay(self.fixtures[0])
        self.assertEqual((result["outcome"], result["retained_source_files"], result["cells_checked"]),
                         ("pass", 270, 7))
        self.assertEqual(result["source_inventory_sha256"], checked.NATIVE_V2_SOURCE_INVENTORY_SHA256)
        expected = result["source_inventory_expectation"]
        self.assertEqual(expected["source"], "original-inventory")
        self.assertIsNone(expected["manifest_path"])
        self.assertIsNone(expected["manifest_sha256"])
        self.assertEqual(expected["source_files"], 270)
        self.assertEqual(expected["source_names_sha256"], checked.NATIVE_V2_SOURCE_INVENTORY_SHA256)
        self.assertIn("complete original source-name inventory", expected["trust_boundary"])
        self.assert_nonacceptance(result)

    def test_exact_external_manifest_replays_original_checked_with_explicit_trust_receipt(self):
        fixture = self.fixtures[0]
        options = self.manifest(fixture)
        with mock.patch.object(inventory, "load_source_inventory", wraps=inventory.load_source_inventory) as load, \
             mock.patch.object(inventory, "validate_archive_sources", wraps=inventory.validate_archive_sources) as compare:
            result = self.replay(fixture, **options)
        load.assert_called_once_with(self.manifest_path, expected_sha256=options["source_inventory_sha256"],
            expected_revision=CHECKED_REVISION, producer_contract_id=checked.CONTRACT_ID)
        self.assertEqual(compare.call_count, 1)
        self.assertEqual(compare.call_args.args[0], fixture["report"]["source_before"]["files"])
        self.assertEqual(compare.call_args.kwargs,
            {"expected_revision": CHECKED_REVISION, "producer_contract_id": checked.CONTRACT_ID})
        expected = result["source_inventory_expectation"]
        self.assertEqual(expected["source"], "external-manifest")
        self.assertEqual(expected["manifest_path"], str(self.manifest_path))
        self.assertEqual(expected["manifest_sha256"], options["source_inventory_sha256"])
        self.assertEqual(expected["source_files"], 270)
        self.assertIn("caller-supplied manifest digest", expected["trust_boundary"])
        self.assertIn("do not independently prove Git/GitHub provenance", expected["trust_boundary"])
        self.assertEqual(result["commands_checked"], 17)
        self.assertEqual([row["translation_units"] for row in result["variants"]], [45, 45])
        self.assert_nonacceptance(result)

    def test_added_helper_and_updated_log_pass_only_matching_external_manifest_as_synthetic_consistency(self):
        fixture = self.fixtures[0]
        members = add_helper(fixture["members"], fixture["prefix"])
        with self.assertRaisesRegex(ValueError, "versioned source inventory"):
            self.replay(fixture, members=members, revision=SYNTHETIC_REVISION)
        old = self.manifest(fixture, transform=lambda manifest: manifest.update(source_revision=SYNTHETIC_REVISION))
        with self.assertRaisesRegex(ValueError, "archive source descriptors differ"):
            self.replay(fixture, members=members, revision=SYNTHETIC_REVISION, **old)
        options = self.manifest(fixture, members=members)
        result = self.replay(fixture, members=members, revision=SYNTHETIC_REVISION, **options)
        self.assertEqual((result["outcome"], result["retained_source_files"]), ("pass", 271))
        self.assertEqual(result["source_inventory_expectation"]["source_files"], 271)
        self.assertNotEqual(result["source_inventory_sha256"], checked.NATIVE_V2_SOURCE_INVENTORY_SHA256)
        self.assertEqual(result["source_revision"], SYNTHETIC_REVISION)
        self.assert_nonacceptance(result)

    def test_public_original_source_check_accepts_exact_manifest_without_changing_failed_outcome(self):
        fixture = self.fixtures[1]
        options = self.manifest(fixture)
        with checked.open_archive(fixture["path"], fixture["sha256"], prefix=fixture["prefix"]) as (packet, _archive):
            expected = checked.load_expected_inventory(options["source_inventory"], options["source_inventory_sha256"],
                expected_revision=PUBLIC_REVISION, producer_contract_id=public.CONTRACT_ID)
            packet.source(PUBLIC_REVISION, required=public.SOURCE_REQUIRED,
                inventory_sha256=public.PUBLIC_V1_SOURCE_INVENTORY_SHA256,
                expected_inventory=expected, producer_contract_id=public.CONTRACT_ID)
            self.assertEqual(len(packet.sources), 676)
            self.assertEqual(packet.report["outcome"], "fail")
        for selected in ({}, options):
            with self.subTest(external=bool(selected)), self.assertRaisesRegex(ValueError, "producer outcome"):
                self.replay(fixture, **selected)

    def test_public_source_check_requires_matching_manifest_for_added_helper(self):
        fixture = self.fixtures[1]
        members = add_helper(fixture["members"], fixture["prefix"])
        path, sha256 = self.archive(members)
        options = self.manifest(fixture, members=members)
        with checked.open_archive(path, sha256, prefix=fixture["prefix"]) as (packet, _archive):
            with self.assertRaisesRegex(ValueError, "versioned source inventory"):
                packet.source(SYNTHETIC_REVISION, required=public.SOURCE_REQUIRED,
                    inventory_sha256=public.PUBLIC_V1_SOURCE_INVENTORY_SHA256)
            expected = checked.load_expected_inventory(options["source_inventory"], options["source_inventory_sha256"],
                expected_revision=SYNTHETIC_REVISION, producer_contract_id=public.CONTRACT_ID)
            packet.source(SYNTHETIC_REVISION, required=public.SOURCE_REQUIRED,
                inventory_sha256=public.PUBLIC_V1_SOURCE_INVENTORY_SHA256,
                expected_inventory=expected, producer_contract_id=public.CONTRACT_ID)
            self.assertEqual(len(packet.sources), 677)
            self.assertEqual(packet.report["outcome"], "fail")
        with self.assertRaisesRegex(ValueError, "producer outcome"):
            public.replay_archive(path, sha256, expected_revision=SYNTHETIC_REVISION, **options)

    def test_missing_manifest_option_pairs_reject_before_archive_access_in_both_apis(self):
        for fixture in self.fixtures:
            for options in ({"source_inventory": self.manifest_path},
                            {"source_inventory_sha256": "0" * 64},
                            {"source_inventory": ""}, {"source_inventory_sha256": ""}):
                with self.subTest(reader=fixture["reader"].CONTRACT_ID, options=options), \
                     mock.patch.object(checked, "open_archive", side_effect=AssertionError("archive opened")), \
                     self.assertRaisesRegex(ValueError, "must be supplied together"):
                    self.replay(fixture, **options)

    def test_wrong_external_digest_rejects_in_both_readers_without_fallback(self):
        for fixture in self.fixtures:
            options = self.manifest(fixture)
            options["source_inventory_sha256"] = "0" * 64
            with self.subTest(reader=fixture["reader"].CONTRACT_ID), \
                 self.assertRaisesRegex(ValueError, "manifest SHA-256 differs"):
                self.replay(fixture, **options)

    def test_wrong_manifest_revision_rejects_in_both_readers(self):
        for fixture in self.fixtures:
            options = self.manifest(fixture, transform=lambda manifest: manifest.update(source_revision="b" * 40))
            with self.subTest(reader=fixture["reader"].CONTRACT_ID), \
                 self.assertRaisesRegex(ValueError, "revision differs"):
                self.replay(fixture, **options)

    def test_wrong_manifest_producer_contract_rejects_in_both_readers(self):
        for fixture in self.fixtures:
            other = public.CONTRACT_ID if fixture["reader"] is checked else checked.CONTRACT_ID
            options = self.manifest(fixture, transform=lambda manifest: manifest.update(producer_contract_id=other))
            with self.subTest(reader=fixture["reader"].CONTRACT_ID), \
                 self.assertRaisesRegex(ValueError, "producer contract differs"):
                self.replay(fixture, **options)

    def test_external_manifests_cannot_omit_original_uncompiled_header_or_helper(self):
        self.assertNotIn(HEADER, checked.SOURCE_REQUIRED)
        for fixture in self.fixtures:
            for omitted in (HEADER, "ci/project/baseline_packet_io.py"):
                options = self.manifest(fixture, transform=lambda manifest: manifest.update(
                    sources=[row for row in manifest["sources"] if row["path"] != omitted]))
                with self.subTest(reader=fixture["reader"].CONTRACT_ID, omitted=omitted), \
                     self.assertRaisesRegex(ValueError, "omits an original required body"):
                    self.replay(fixture, **options)

    def test_removing_header_from_both_packet_and_manifest_still_rejects(self):
        fixture = self.fixtures[0]
        members = dict(fixture["members"])
        retained = "artifacts/source/" + HEADER
        del members[fixture["prefix"] + "/" + retained]

        def change(report):
            for key in ("source_before", "source_after"):
                report[key]["files"] = [row for row in report[key]["files"] if row["path"] != HEADER]
            report["retained_sources"] = [row for row in report["retained_sources"] if row["path"] != retained]

        edit_report(members, fixture["prefix"], change)
        options = self.manifest(fixture, members=members)
        with self.assertRaisesRegex(ValueError, "omits an original required body"):
            self.replay(fixture, members=members, **options)

    def test_external_hash_and_size_descriptors_must_match_full_report_exactly(self):
        fixture = self.fixtures[0]
        for field, value in (("sha256", "0" * 64), ("size_bytes", 1)):
            def change(manifest):
                next(row for row in manifest["sources"] if row["path"] == HEADER)[field] = value
            options = self.manifest(fixture, transform=change)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "archive source descriptors differ"):
                self.replay(fixture, **options)

    def test_explicit_missing_malformed_or_symlink_manifest_never_falls_back(self):
        fixture = self.fixtures[0]
        options = self.manifest(fixture)
        good = self.manifest_path.read_bytes()
        for body in (b"", b"{", b"{\"schema_version\":1,\"schema_version\":1}"):
            self.manifest_path.write_bytes(body)
            options["source_inventory_sha256"] = hashlib.sha256(body).hexdigest()
            with self.subTest(body=body), self.assertRaises(ValueError):
                self.replay(fixture, **options)
        self.manifest_path.unlink()
        options["source_inventory_sha256"] = hashlib.sha256(good).hexdigest()
        with self.assertRaisesRegex(ValueError, "cannot be read safely"):
            self.replay(fixture, **options)
        target = self.root / "manifest-target.json"
        target.write_bytes(good)
        self.manifest_path.symlink_to(target)
        with self.assertRaisesRegex(ValueError, "cannot be read safely"):
            self.replay(fixture, **options)

    def test_empty_or_mistyped_digest_is_explicit_invalid_input(self):
        for fixture in self.fixtures:
            options = self.manifest(fixture)
            for sha256 in ("", True, 1, "A" * 64, "a" * 63):
                options["source_inventory_sha256"] = sha256
                with self.subTest(reader=fixture["reader"].CONTRACT_ID, sha256=sha256), \
                     self.assertRaisesRegex(ValueError, "external source inventory SHA-256"):
                    self.replay(fixture, **options)

    def test_external_manifest_does_not_replace_raw_retained_source_hashing(self):
        fixture = self.fixtures[0]
        members = dict(fixture["members"])
        members[fixture["prefix"] + "/artifacts/source/" + HEADER] += b"// unbound raw bytes\n"
        options = self.manifest(fixture)
        with self.assertRaisesRegex(ValueError, "retained descriptor hash or size differs"):
            self.replay(fixture, members=members, **options)

    def test_external_manifest_does_not_replace_original_compiler_log_checks(self):
        fixture = self.fixtures[0]
        members = dict(fixture["members"])

        def change(report):
            command = next(row for row in report["commands"] if row["id"] == "ordinary-build")
            path = fixture["prefix"] + "/" + command["log"]
            members[path] = b"\n".join(members[path].splitlines()[1:]) + b"\n"
            command.update(log_sha256=hashlib.sha256(members[path]).hexdigest(), log_size_bytes=len(members[path]))

        edit_report(members, fixture["prefix"], change)
        options = self.manifest(fixture, members=members)
        with self.assertRaisesRegex(ValueError, "exact fresh compile/link source inventory"):
            self.replay(fixture, members=members, **options)

    def test_external_manifest_does_not_relax_source_before_after_metadata(self):
        fixture = self.fixtures[0]
        members = dict(fixture["members"])
        edit_report(members, fixture["prefix"], lambda report: report["source_after"]["checkout"].update(tree="b" * 40))
        options = self.manifest(fixture, members=members)
        with self.assertRaisesRegex(ValueError, "source before/after"):
            self.replay(fixture, members=members, **options)

    def test_source_inventory_helper_and_packet_io_are_in_both_trusted_reader_closures(self):
        for reader in (checked, public):
            rows = reader._reader_sources()
            for name in ("p06_counter_source_inventory.py", "baseline_packet_io.py"):
                with self.subTest(reader=reader.CONTRACT_ID, helper=name):
                    matching = [row for row in rows if row["path"] == "ci/project/" + name]
                    self.assertEqual(len(matching), 1)
                    self.assertEqual(matching[0], descriptor("ci/project/" + name, (ROOT / "ci/project" / name).read_bytes()))

    def test_reader_helper_or_packet_io_drift_during_manifest_load_rejects(self):
        fixture = self.fixtures[0]
        options = self.manifest(fixture)
        read_bytes = Path.read_bytes
        load = inventory.load_source_inventory
        for name in ("p06_counter_source_inventory.py", "baseline_packet_io.py"):
            changed = False

            def change_after_load(*args, **kwargs):
                nonlocal changed
                result = load(*args, **kwargs)
                changed = True
                return result

            def observed(path):
                body = read_bytes(path)
                return body + b"\n# simulated trusted-source drift\n" if changed and path.name == name else body

            with self.subTest(helper=name), mock.patch.object(Path, "read_bytes", observed), \
                 mock.patch.object(inventory, "load_source_inventory", change_after_load), \
                 self.assertRaisesRegex(ValueError, "trusted reader source stability"):
                self.replay(fixture, **options)

    def test_both_cli_argument_paths_load_manifest_and_preserve_nonacceptance(self):
        for fixture in self.fixtures:
            options = self.manifest(fixture)
            arguments = ["--archive", str(fixture["path"]), "--sha256", fixture["sha256"],
                "--source-revision", fixture["revision"], "--source-inventory", str(self.manifest_path),
                "--source-inventory-sha256", options["source_inventory_sha256"]]
            output = io.StringIO()
            with self.subTest(reader=fixture["reader"].CONTRACT_ID), redirect_stdout(output), \
                 mock.patch.object(inventory, "load_source_inventory", wraps=inventory.load_source_inventory) as load:
                code = fixture["reader"].main(arguments)
            self.assertEqual(load.call_count, 1)
            result = json.loads(output.getvalue())
            self.assert_nonacceptance(result)
            if fixture["reader"] is checked:
                self.assertEqual((code, result["outcome"]), (0, "pass"))
                self.assertEqual(result["source_inventory_expectation"]["manifest_sha256"], options["source_inventory_sha256"])
            else:
                self.assertEqual((code, result["outcome"]), (1, "fail"))
                self.assertIn("producer outcome", result["reason"])

    def test_both_clis_reject_partial_manifest_options_without_archive_access(self):
        for fixture in self.fixtures:
            for partial in (("--source-inventory", str(self.manifest_path)), ("--source-inventory-sha256", "0" * 64)):
                output = io.StringIO()
                with self.subTest(reader=fixture["reader"].CONTRACT_ID, partial=partial), redirect_stdout(output), \
                     mock.patch.object(checked, "open_archive", side_effect=AssertionError("archive opened")):
                    code = fixture["reader"].main(["--archive", str(fixture["path"]), "--sha256", fixture["sha256"],
                        "--source-revision", fixture["revision"], *partial])
                result = json.loads(output.getvalue())
                self.assertEqual(code, 1)
                self.assertIn("must be supplied together", result["reason"])
                self.assert_nonacceptance(result)

    def test_cli_output_retains_manifest_receipt_and_all_false_claims(self):
        fixture = self.fixtures[0]
        options = self.manifest(fixture)
        destination = self.root / "replay-result.json"
        output = io.StringIO()
        with redirect_stdout(output):
            code = checked.main(["--archive", str(fixture["path"]), "--sha256", fixture["sha256"],
                "--source-revision", fixture["revision"], "--source-inventory", str(self.manifest_path),
                "--source-inventory-sha256", options["source_inventory_sha256"], "--output", str(destination)])
        self.assertEqual(code, 0)
        result = json.loads(destination.read_bytes())
        self.assertEqual(result["source_inventory_expectation"]["manifest_sha256"], options["source_inventory_sha256"])
        self.assert_nonacceptance(result)
        self.assert_nonacceptance(json.loads(output.getvalue()))

    def test_external_manifest_and_retained_helper_remain_inert_with_bounded_filesystem_inputs(self):
        fixture = self.fixtures[0]
        members = add_helper(fixture["members"], fixture["prefix"])
        archive, sha256 = self.archive(members)
        options = self.manifest(fixture, members=members)
        parser = ROOT / checked.trusted.ARCHIVE_READER_PATH
        allowed_files = {archive, self.manifest_path, parser,
                         *(ROOT / row["path"] for row in checked._reader_sources())}
        allowed_directories = {parent for path in allowed_files for parent in path.parents}
        cwd = Path.cwd()
        descriptors = {}
        opened = set()
        original_open, original_exec = os.open, builtins.exec

        def selected(path, *, dir_fd=None, directories=False):
            if isinstance(path, int):
                self.assertIn(path, descriptors, "accessed an unselected descriptor")
                return descriptors[path]
            candidate = PurePosixPath(os.fsdecode(path))
            if not candidate.is_absolute():
                candidate = (PurePosixPath(descriptors[dir_fd]) if dir_fd is not None else cwd) / candidate
            candidate = Path(candidate)
            self.assertIn(candidate, allowed_files | allowed_directories if directories else allowed_files,
                          "accessed a path outside explicit files and trusted reader closure: " + str(candidate))
            return candidate

        def guarded(function, *, directories=False):
            def call(path, *args, **kwargs):
                selected(path, dir_fd=kwargs.get("dir_fd"), directories=directories)
                return function(path, *args, **kwargs)
            return call

        def open_fd(path, flags, *args, **kwargs):
            candidate = selected(path, dir_fd=kwargs.get("dir_fd"), directories=bool(flags & os.O_DIRECTORY))
            self.assertFalse(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
            descriptor_number = original_open(path, flags, *args, **kwargs)
            descriptors[descriptor_number] = candidate
            opened.add(candidate)
            return descriptor_number

        def trusted_exec(code, globals=None, locals=None, **kwargs):
            self.assertEqual(getattr(code, "co_filename", None), str(parser), "executed untrusted retained code")
            return original_exec(code, globals, locals, **kwargs)

        with ExitStack() as patches:
            for owner, name in ((builtins, "open"), (io, "open"), (Path, "open")):
                patches.enter_context(mock.patch.object(owner, name, guarded(getattr(owner, name))))
            for owner, name in ((os, "stat"), (os, "lstat"), (os, "readlink"), (Path, "resolve"),
                                (Path, "stat"), (Path, "lstat"), (Path, "exists"), (Path, "is_file"), (Path, "is_dir")):
                patches.enter_context(mock.patch.object(owner, name, guarded(getattr(owner, name), directories=True)))
            patches.enter_context(mock.patch.object(os, "open", open_fd))
            # Preserve the real platform's no-follow capability declarations for these audit wrappers.
            patches.enter_context(mock.patch.object(os, "supports_dir_fd", os.supports_dir_fd | {os.open, os.stat}))
            patches.enter_context(mock.patch.object(os, "supports_follow_symlinks", os.supports_follow_symlinks | {os.stat}))
            for owner, name in ((subprocess, "Popen"), (subprocess, "run"), (subprocess, "call"),
                                (subprocess, "check_call"), (subprocess, "check_output"), (os, "system"), (os, "popen"),
                                (os, "fork"), (os, "execv"), (os, "execve"), (os, "execvp"), (os, "execvpe"),
                                (os, "posix_spawn"), (os, "posix_spawnp"), (os, "listdir"), (os, "scandir"),
                                (Path, "glob"), (Path, "rglob"), (Path, "write_bytes"), (Path, "write_text"),
                                (zipfile.ZipFile, "extract"), (zipfile.ZipFile, "extractall"),
                                (checked.checked, "validate_build"), (checked.checked, "source_snapshot")):
                if hasattr(owner, name):
                    patches.enter_context(mock.patch.object(owner, name, side_effect=AssertionError(name)))
            patches.enter_context(mock.patch.object(builtins, "exec", trusted_exec))
            result = checked.replay_archive(archive, sha256, expected_revision=SYNTHETIC_REVISION, **options)
        self.assertIn(archive, opened)
        self.assertIn(self.manifest_path, opened)
        self.assert_nonacceptance(result)


if __name__ == "__main__":
    unittest.main()
