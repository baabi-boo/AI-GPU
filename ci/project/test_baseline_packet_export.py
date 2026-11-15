# SPDX-License-Identifier: Apache-2.0
"""Independent published-export checks; synthetic records are never GPU evidence."""

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import baseline_packet as packet
import baseline_packet_export as export
from baseline_packet_export_fixture import make_export, save_export_manifest
from baseline_packet_fixture import CASE_IDS, make_packet, save_report
from baseline_packet_io import PacketError, PacketReader


@unittest.skipUnless(os.name == "posix" and hasattr(os, "O_NOFOLLOW"),
                     "packet filesystem safety requires POSIX no-follow support")
class PublishedExportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.root = self.base / "published"
        self.manifest = make_export(self.root)
        self.report = json.loads((self.root / "report.json").read_bytes())

    @staticmethod
    def snapshot(root):
        result = {}
        for path in [root, *root.rglob("*")]:
            info = path.lstat()
            if stat.S_ISREG(info.st_mode):
                contents = path.read_bytes()
            elif stat.S_ISLNK(info.st_mode):
                contents = os.readlink(path)
            else:
                contents = None
            result[path.relative_to(root).as_posix()] = (
                info.st_ino, info.st_mode, info.st_mtime_ns, contents,
            )
        return result

    @staticmethod
    def row(manifest, member):
        source = manifest["source_packet"] + "/" + member
        return next(row for row in manifest["artifacts"] if row["source_path"] == source)

    def refresh_public(self, manifest, member, *, copied=False, root=None):
        contents = ((root or self.root) / member).read_bytes()
        row = self.row(manifest, member)
        row.update(sha256=hashlib.sha256(contents).hexdigest(), size_bytes=len(contents))
        if copied:
            row.update(source_sha256=row["sha256"], source_size_bytes=row["size_bytes"])
        save_export_manifest(root or self.root, manifest)

    def assertBoundary(self, value, *, native):
        self.assertEqual(value["verification_mode"], "published_export")
        self.assertEqual(value["published_integrity"], "verified")
        self.assertIs(value["native_matrix_records_consistent"], native)
        self.assertIs(value["raw_log_bytes_verified"], False)
        self.assertIs(value["redaction_relationship_verified"], False)
        self.assertIs(value["phase_complete"], False)
        self.assertEqual(value["integration_outcome"], "blocked")
        for raw_claim in ("integrity", "native_matrix_passed", "manifest", "manifest_written"):
            self.assertNotIn(raw_claim, value)
        limitations = " ".join(value["limitations"]).lower()
        for boundary in ("unsigned", "original command-log bytes", "redaction relationship",
                         "independent review", "vendor xrt", "never imported or executed"):
            self.assertIn(boundary, limitations)

    def verify(self, root=None, *, required=False):
        root = root or self.root
        before = self.snapshot(root)
        value = export.verify_export(root, require_native_records=required)
        self.assertEqual(self.snapshot(root), before, "verification changed published inputs")
        return value

    def assertInvalid(self, manifest=None, *, pattern=None, root=None):
        root = root or self.root
        if manifest is not None:
            save_export_manifest(root, manifest)
        before = self.snapshot(root)
        expectation = (self.assertRaisesRegex(PacketError, pattern)
                       if pattern else self.assertRaises(PacketError))
        with expectation:
            export.verify_export(root)
        self.assertEqual(self.snapshot(root), before, "rejection changed published inputs")

    def invoke(self, *arguments):
        root = Path(arguments[1])
        before = self.snapshot(root) if root.is_dir() else None
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = packet.main([str(argument) for argument in arguments])
        self.assertEqual(stderr.getvalue(), "")
        value = json.loads(stdout.getvalue())
        if before is not None:
            self.assertEqual(self.snapshot(root), before, "CLI changed published inputs")
        return status, value

    def test_complete_export_checks_public_inventory_without_raw_or_acceptance_claims(self):
        value = self.verify(required=True)
        self.assertBoundary(value, native=True)
        self.assertEqual(value["outcome"], "pass")
        self.assertEqual(value["run_outcome"], "pass")
        self.assertIs(value["requirement_satisfied"], True)
        self.assertEqual(value["selected_ids"], list(CASE_IDS))
        self.assertEqual(value["passed_ids"], list(CASE_IDS))
        self.assertEqual(value["failed_ids"], [])
        self.assertEqual(value["not_run_ids"], [])
        expected = []
        members = {row["source_path"][len(self.manifest["source_packet"]) + 1:]
                   for row in self.manifest["artifacts"]}
        for member in sorted(members | {"export-manifest.json"}):
            contents = (self.root / member).read_bytes()
            expected.append({"path": member, "size_bytes": len(contents),
                             "sha256": hashlib.sha256(contents).hexdigest()})
        self.assertEqual(value["published_files"], expected)
        status, actual = self.invoke("verify-export", self.root, "--require-native-records")
        self.assertEqual(status, 0)
        self.assertEqual(actual, value)

    def test_selection_and_failure_preserve_outcome_and_native_requirement_boundaries(self):
        cases = (
            ("selected", {"selected_ids": [CASE_IDS[0], CASE_IDS[2]]},
             "pass", [CASE_IDS[0], CASE_IDS[2]], [], []),
            ("failed", {"failed_case": CASE_IDS[1]},
             "fail", [CASE_IDS[0]], [CASE_IDS[1]], list(CASE_IDS[2:])),
        )
        for label, options, outcome, passed, failed, not_run in cases:
            root = self.base / label
            make_export(root, **options)
            for required in (False, True):
                with self.subTest(packet=label, required=required):
                    value = self.verify(root, required=required)
                    self.assertBoundary(value, native=False)
                    self.assertEqual(value["outcome"], "fail" if required else "pass")
                    self.assertEqual(value["run_outcome"], outcome)
                    self.assertIs(value["requirement_satisfied"], not required)
                    self.assertEqual(value["passed_ids"], passed)
                    self.assertEqual(value["failed_ids"], failed)
                    self.assertEqual(value["not_run_ids"], not_run)
                    flags = ["--require-native-records"] if required else []
                    status, actual = self.invoke("verify-export", root, *flags)
                    self.assertEqual(status, int(required))
                    self.assertEqual(actual, value)

    def test_copy_only_export_still_reports_only_published_verification(self):
        manifest = deepcopy(self.manifest)
        report = deepcopy(self.report)
        for command in report["commands"]:
            row = self.row(manifest, command["log"])
            command.update(log_sha256=row["sha256"], log_size_bytes=row["size_bytes"])
            row.update(transformation="byte_preserving_copy", source_sha256=row["sha256"],
                       source_size_bytes=row["size_bytes"])
        manifest["sanitization"]["rules"] = []
        save_report(self.root, report)
        self.refresh_public(manifest, "report.json", copied=True)
        self.assertIs(packet.verify_packet(self.root)["native_matrix_passed"], True)
        self.assertBoundary(self.verify(required=True), native=True)

    def test_strict_raw_api_cli_and_seal_reject_redacted_logs(self):
        before = self.snapshot(self.root)
        with self.assertRaises(PacketError):
            packet.verify_packet(self.root)
        for flags in ([], ["--manifest", self.root / "export-manifest.json"]):
            with self.subTest(flags=flags):
                status, value = self.invoke("verify", self.root, *flags)
                self.assertEqual(status, 1)
                self.assertEqual(value["integrity"], "invalid")
                self.assertIs(value["native_matrix_passed"], False)
                self.assertNotIn("published_integrity", value)
        output = self.base / "raw-seal.json"
        status, value = self.invoke("seal", self.root, "--output", output)
        self.assertEqual(status, 1)
        self.assertNotIn("manifest_written", value)
        self.assertFalse(output.exists())
        self.assertEqual(self.snapshot(self.root), before)

    def test_relocation_and_nonexistent_source_metadata_do_not_require_original_paths(self):
        original = self.verify()
        root = self.base / "relocated"
        shutil.copytree(self.root, root)
        self.assertEqual(self.verify(root), original)
        manifest = deepcopy(self.manifest)
        old_prefix = manifest["source_packet"] + "/"
        manifest["source_packet"] = "unavailable-original/workspace/packet"
        for row in manifest["artifacts"]:
            row["source_path"] = manifest["source_packet"] + "/" + row["source_path"][len(old_prefix):]
        self.assertFalse((root / "unavailable-original").exists())
        save_export_manifest(root, manifest)
        self.assertBoundary(self.verify(root, required=True), native=True)

    def test_public_prefix_is_metadata_but_each_member_mapping_must_agree(self):
        manifest = deepcopy(self.manifest)
        for row in manifest["artifacts"]:
            row["path"] = row["source_path"][len(manifest["source_packet"]) + 1:]
        save_export_manifest(self.root, manifest)
        self.assertBoundary(self.verify(required=True), native=True)
        self.row(manifest, "logs/" + CASE_IDS[0] + ".log")["path"] = "logs/substituted.log"
        self.assertInvalid(manifest)

    def test_unreferenced_files_are_preserved_outside_the_published_inventory(self):
        original = self.verify()
        (self.root / "unused.py").write_text("raise RuntimeError('must not execute')\n",
                                               encoding="utf-8")
        self.assertEqual(self.verify(), original)

    def test_public_byte_mutation_is_rejected_for_logs_and_copied_records(self):
        members = ["report.json", "matrix.json", "logs/" + CASE_IDS[0] + ".log",
                   self.report["tooling_snapshots"][0]["path"],
                   self.report["cases"][0]["configuration_artifacts"][0]["path"]]
        for index, member in enumerate(members):
            with self.subTest(member=member):
                root = self.base / ("mutation-" + str(index))
                shutil.copytree(self.root, root)
                with (root / member).open("ab") as destination:
                    destination.write(b"\n ")
                self.assertInvalid(root=root)

    def test_redacted_source_hash_and_size_must_bind_the_unchanged_command(self):
        member = "logs/" + CASE_IDS[0] + ".log"
        for field, value in (("source_sha256", "0" * 64), ("source_size_bytes", 1)):
            with self.subTest(field=field):
                manifest = deepcopy(self.manifest)
                self.row(manifest, member)[field] = value
                self.assertInvalid(manifest, pattern="source log identity")

    def test_copied_source_and_published_identities_cannot_differ(self):
        for field, value in (("source_sha256", "0" * 64), ("source_size_bytes", 1)):
            with self.subTest(field=field):
                manifest = deepcopy(self.manifest)
                self.row(manifest, "report.json")[field] = value
                self.assertInvalid(manifest, pattern="byte-preserving")

    def test_refreshing_public_log_identity_cannot_hide_reference_marker_corruption(self):
        member = "logs/" + CASE_IDS[0] + ".log"
        original = (self.root / member).read_bytes()
        self.assertIn(b"PASSED!\n", original)
        mutations = (
            original.replace(b"PASSED!\n", b"\n"),
            original.replace(b"PASSED!\n", b"FAILED!\n"),
            original + b"PASSED!\n",
            original + b"Found 1 errors!\n",
        )
        for index, contents in enumerate(mutations):
            with self.subTest(mutation=index):
                manifest = deepcopy(self.manifest)
                (self.root / member).write_bytes(contents)
                self.refresh_public(manifest, member)
                self.assertInvalid(pattern="CPU-reference")

    def test_refreshed_copy_mapping_cannot_override_report_retained_identities(self):
        members = [self.report["tooling_snapshots"][0]["path"],
                   self.report["cases"][0]["configuration_artifacts"][0]["path"]]
        for index, member in enumerate(members):
            with self.subTest(member=member):
                root = self.base / ("retained-" + str(index))
                shutil.copytree(self.root, root)
                with (root / member).open("ab") as destination:
                    destination.write(b"\n# harmless-looking changed bytes\n")
                self.refresh_public(deepcopy(self.manifest), member, copied=True, root=root)
                self.assertInvalid(root=root)

    def test_refreshed_report_identity_does_not_bypass_semantic_consistency(self):
        report = deepcopy(self.report)
        report["coverage"]["full_native_matrix_passed"] = False
        save_report(self.root, report)
        self.refresh_public(deepcopy(self.manifest), "report.json", copied=True)
        self.assertInvalid(pattern="native-matrix coverage")

    def test_reported_outcome_must_match_copied_report(self):
        manifest = deepcopy(self.manifest)
        manifest["reported_outcome"] = "fail"
        self.assertInvalid(manifest, pattern="outcome differs")

    def test_missing_rows_are_rejected_in_each_artifact_category(self):
        members = ["report.json", "matrix.json", "logs/" + CASE_IDS[0] + ".log",
                   self.report["tooling_snapshots"][0]["path"],
                   self.report["cases"][0]["configuration_artifacts"][0]["path"]]
        for member in members:
            with self.subTest(member=member):
                manifest = deepcopy(self.manifest)
                manifest["artifacts"].remove(self.row(manifest, member))
                self.assertInvalid(manifest)

    def test_duplicate_source_or_public_paths_are_rejected(self):
        for duplicate in ("both", "source", "public"):
            with self.subTest(duplicate=duplicate):
                manifest = deepcopy(self.manifest)
                row = deepcopy(self.row(manifest, "report.json"))
                if duplicate == "source":
                    row["path"] += ".other"
                if duplicate == "public":
                    row["source_path"] += ".other"
                manifest["artifacts"].append(row)
                self.assertInvalid(manifest, pattern="duplicate")

    def test_extra_copy_and_unreferenced_redacted_log_rows_are_rejected(self):
        for member, transformation in (("unreferenced.txt", "byte_preserving_copy"),
                                        ("logs/unreferenced.log", "literal_path_redaction")):
            with self.subTest(member=member):
                contents = b"unreferenced fixture bytes\n"
                (self.root / member).write_bytes(contents)
                manifest = deepcopy(self.manifest)
                row = deepcopy(self.row(manifest, "report.json"))
                row["path"] = row["path"][:-len("report.json")] + member
                row.update(source_path=manifest["source_packet"] + "/" + member,
                           sha256=hashlib.sha256(contents).hexdigest(), size_bytes=len(contents),
                           source_sha256=hashlib.sha256(contents).hexdigest(),
                           source_size_bytes=len(contents), transformation=transformation)
                manifest["artifacts"].append(row)
                self.assertInvalid(manifest, pattern="exactly")

    def test_noncanonical_paths_and_source_escape_are_rejected(self):
        bad_paths = ("/absolute", "../outside", "a/../../outside", "a/./b", "a//b",
                     "a/", "a\\b", "C:/outside", "a\x00b", "a\nb", "a/" + "x" * 256)
        for field in ("path", "source_path", "source_packet"):
            for value in bad_paths:
                with self.subTest(field=field, value=value):
                    manifest = deepcopy(self.manifest)
                    target = manifest if field == "source_packet" else self.row(manifest, "report.json")
                    target[field] = value
                    self.assertInvalid(manifest)
        manifest = deepcopy(self.manifest)
        self.row(manifest, "report.json")["source_path"] = "different-packet/report.json"
        self.assertInvalid(manifest, pattern="outside")

    def test_redaction_is_for_referenced_command_logs_only(self):
        members = ["report.json", "matrix.json", self.report["tooling_snapshots"][0]["path"],
                   self.report["cases"][0]["configuration_artifacts"][0]["path"]]
        for member in members:
            with self.subTest(member=member):
                manifest = deepcopy(self.manifest)
                self.row(manifest, member)["transformation"] = "literal_path_redaction"
                self.assertInvalid(manifest, pattern="only supported for command logs")

    def test_unknown_transformations_and_redaction_without_rules_are_rejected(self):
        for value in ("copy", "decode_utf8", "execute", "", None, True, [], {}):
            with self.subTest(transformation=value):
                manifest = deepcopy(self.manifest)
                self.row(manifest, "logs/" + CASE_IDS[0] + ".log")["transformation"] = value
                self.assertInvalid(manifest)
        manifest = deepcopy(self.manifest)
        manifest["sanitization"]["rules"] = []
        self.assertInvalid(manifest)

    def test_malformed_json_duplicate_keys_and_nonobject_manifests_are_rejected(self):
        contents = (b"{", b"[]", b"null", b"true", b"\xff",
                    b'{"schema_version":1,"schema_version":1}',
                    b'{"schema_version":NaN}')
        for raw in contents:
            with self.subTest(contents=raw):
                (self.root / "export-manifest.json").write_bytes(raw)
                self.assertInvalid()

    def test_manifest_field_types_and_unknown_fields_are_rejected(self):
        mutations = {
            "schema_version": (True, "1", 0, 2, None),
            "source_packet": (None, 1, []),
            "reported_outcome": (True, None, "finished", [], {}),
            "scope": (None, 1, "", "\n", "x" * 4097),
            "limitations": (None, {}, "text", [None], ["x"] * 257),
            "sanitization": (None, [], "text"),
            "artifacts": (None, {}, "text", []),
        }
        for field, values in mutations.items():
            for value in values:
                with self.subTest(field=field, value=repr(value)[:80]):
                    manifest = deepcopy(self.manifest)
                    manifest[field] = value
                    self.assertInvalid(manifest)
        for field in ("scope", "unexpected"):
            with self.subTest(field=field):
                manifest = deepcopy(self.manifest)
                if field == "scope":
                    del manifest[field]
                else:
                    manifest[field] = True
                self.assertInvalid(manifest)

    def test_artifact_row_types_and_identity_fields_are_rejected(self):
        for value in (None, [], "text", True):
            with self.subTest(row=value):
                manifest = deepcopy(self.manifest)
                manifest["artifacts"][0] = value
                self.assertInvalid(manifest)
        for field in ("sha256", "source_sha256"):
            for value in (None, True, [], "0" * 63, "g" * 64, "A" * 64):
                with self.subTest(field=field, value=value):
                    manifest = deepcopy(self.manifest)
                    self.row(manifest, "report.json")[field] = value
                    self.assertInvalid(manifest)
        for field in ("size_bytes", "source_size_bytes"):
            for value in (None, True, -1, 1.5, "1", 512 * 1024 * 1024 + 1):
                with self.subTest(field=field, value=value):
                    manifest = deepcopy(self.manifest)
                    self.row(manifest, "report.json")[field] = value
                    self.assertInvalid(manifest)
        for missing in (True, False):
            manifest = deepcopy(self.manifest)
            row = self.row(manifest, "report.json")
            if missing:
                del row["sha256"]
            else:
                row["unknown"] = True
            self.assertInvalid(manifest)

    def test_sanitization_metadata_is_bounded_and_cannot_encode_source_traversal(self):
        mutations = (("method", None), ("nested_hash_policy", ""), ("rules", {}),
                     ("rules", [None]), ("rules", [{}]), ("rules", [
                         {"source_prefix": "${RAW_WORKSPACE}/../outside", "replacement": "$ROOT"}]),
                     ("rules", [{"source_prefix": "/actual/source", "replacement": "$ROOT"}]),
                     ("rules", [{"source_prefix": "${RAW_WORKSPACE}", "replacement": "/outside"}]))
        for field, value in mutations:
            with self.subTest(field=field, value=value):
                manifest = deepcopy(self.manifest)
                manifest["sanitization"][field] = value
                self.assertInvalid(manifest)
        manifest = deepcopy(self.manifest)
        manifest["sanitization"]["rules"].append(deepcopy(manifest["sanitization"]["rules"][0]))
        self.assertInvalid(manifest)

    def test_native_requirement_accepts_only_boolean_values(self):
        before = self.snapshot(self.root)
        for required in (None, 0, 1, "true", [], {}):
            with self.subTest(required=required), self.assertRaises(PacketError):
                export.verify_export(self.root, require_native_records=required)
        self.assertEqual(self.snapshot(self.root), before)

    def test_missing_manifest_never_autodetects_a_raw_packet(self):
        root = self.base / "raw"
        make_packet(root)
        self.assertInvalid(root=root)
        self.assertIs(packet.verify_packet(root)["native_matrix_passed"], True)

    def test_symlink_members_and_root_are_rejected_without_changing_targets(self):
        members = ["export-manifest.json", "report.json", "matrix.json",
                   "logs/" + CASE_IDS[0] + ".log", self.report["tooling_snapshots"][0]["path"]]
        for index, member in enumerate(members):
            with self.subTest(member=member):
                root = self.base / ("symlink-" + str(index))
                shutil.copytree(self.root, root)
                target = self.base / ("target-" + str(index))
                (root / member).rename(target)
                before = target.read_bytes(), target.stat().st_mtime_ns
                (root / member).symlink_to(target)
                self.assertInvalid(root=root)
                self.assertEqual((target.read_bytes(), target.stat().st_mtime_ns), before)
        alias = self.base / "root-alias"
        alias.symlink_to(self.root, target_is_directory=True)
        self.assertInvalid(root=alias)

    def test_symlink_ancestor_and_nonregular_manifest_are_rejected(self):
        root = self.base / "ancestor"
        shutil.copytree(self.root, root)
        (root / "logs").rename(self.base / "outside-logs")
        (root / "logs").symlink_to(self.base / "outside-logs", target_is_directory=True)
        self.assertInvalid(root=root)
        (self.root / "export-manifest.json").unlink()
        (self.root / "export-manifest.json").mkdir()
        self.assertInvalid()

    def test_manifest_and_log_are_rechecked_after_semantic_verification(self):
        real_recheck = PacketReader.recheck
        for index, member in enumerate(("export-manifest.json", "logs/" + CASE_IDS[0] + ".log")):
            root = self.base / ("race-" + str(index))
            shutil.copytree(self.root, root)
            changed = []

            def mutate_then_recheck(reader):
                changed.append(member)
                with (root / member).open("ab") as destination:
                    destination.write(b"\n")
                return real_recheck(reader)

            with self.subTest(member=member), mock.patch.object(
                    PacketReader, "recheck", mutate_then_recheck):
                with self.assertRaises(PacketError):
                    export.verify_export(root)
            self.assertEqual(changed, [member])

    def test_manifest_size_row_count_and_declared_byte_budget_are_enforced(self):
        path = self.root / "export-manifest.json"
        with path.open("r+b") as destination:
            destination.truncate(1024 * 1024 + 1)
        self.assertInvalid(pattern="byte limit")
        manifest = deepcopy(self.manifest)
        manifest["artifacts"] = [deepcopy(manifest["artifacts"][0]) for _ in range(128)]
        self.assertInvalid(manifest, pattern="bounded list")
        manifest = deepcopy(self.manifest)
        self.row(manifest, "logs/" + CASE_IDS[0] + ".log")["size_bytes"] = 512 * 1024 * 1024
        self.assertInvalid(manifest, pattern="byte inventory")

    def test_published_log_size_is_limited_before_reading_oversized_contents(self):
        member = "logs/" + CASE_IDS[0] + ".log"
        with (self.root / member).open("r+b") as destination:
            destination.truncate(16 * 1024 * 1024 + 1)
        manifest = deepcopy(self.manifest)
        self.row(manifest, member)["size_bytes"] = 16 * 1024 * 1024 + 1
        self.assertInvalid(manifest, pattern="byte limit")

    def test_cli_errors_remain_json_with_published_failure_boundaries(self):
        for root in (self.root, self.base / "missing"):
            with self.subTest(root=root.name):
                if root == self.root:
                    (root / "export-manifest.json").write_text("{}\n", encoding="utf-8")
                status, value = self.invoke("verify-export", root, "--require-native-records")
                self.assertEqual(status, 1)
                self.assertEqual(value["outcome"], "fail")
                self.assertEqual(value["verification_mode"], "published_export")
                self.assertEqual(value["published_integrity"], "invalid")
                for field in ("native_matrix_records_consistent", "raw_log_bytes_verified",
                              "redaction_relationship_verified", "phase_complete"):
                    self.assertIs(value[field], False)
                self.assertTrue(value["errors"])
                self.assertTrue(all(type(error) is str for error in value["errors"]))
                self.assertNotIn("integrity", value)
                self.assertNotIn("native_matrix_passed", value)
                self.assertNotIn(str(self.base), json.dumps(value))

    def test_cli_flags_are_explicit_and_do_not_relax_raw_mode(self):
        commands = (("verify-export", self.root, "--require-native-pass"),
                    ("verify", self.root, "--require-native-records"),
                    ("verify-export", self.root, "--manifest", self.root / "export-manifest.json"))
        before = self.snapshot(self.root)
        for arguments in commands:
            with self.subTest(arguments=arguments):
                stdout, stderr = io.StringIO(), io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
                    packet.main([str(argument) for argument in arguments])
                self.assertEqual(raised.exception.code, 2)
                self.assertEqual(stdout.getvalue(), "")
                self.assertIn("unrecognized arguments", stderr.getvalue())
        self.assertEqual(self.snapshot(self.root), before)

    def test_real_cli_process_reports_complete_published_records(self):
        before = self.snapshot(self.root)
        command = [sys.executable, str(Path(packet.__file__).resolve()), "verify-export",
                   str(self.root), "--require-native-records"]
        result = subprocess.run(command, capture_output=True, text=True, timeout=15,
                                cwd=Path(packet.__file__).resolve().parents[2], check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        value = json.loads(result.stdout)
        self.assertBoundary(value, native=True)
        self.assertIs(value["requirement_satisfied"], True)
        self.assertEqual(self.snapshot(self.root), before)


if __name__ == "__main__":
    unittest.main()
