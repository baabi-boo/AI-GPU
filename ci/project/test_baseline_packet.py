# SPDX-License-Identifier: Apache-2.0
"""Independent CLI checks using synthetic stopped packets, never GPU evidence."""

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
from baseline_packet_fixture import (
    CASE_IDS, make_packet, refresh_log, refresh_stamp, save_report,
)


@unittest.skipUnless(os.name == "posix" and hasattr(os, "O_NOFOLLOW"),
                     "packet filesystem safety requires POSIX no-follow support")
class PacketCLITests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.root = self.base / "packet"
        self.report = make_packet(self.root)

    @staticmethod
    def snapshot(root):
        """Observe bytes, names, modes and modification times, excluding atime."""
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
                info.st_mode, info.st_mtime_ns, contents,
            )
        return result

    def invoke(self, *arguments, check_unchanged=True):
        root = Path(arguments[1])
        before = self.snapshot(root) if check_unchanged and root.is_dir() else None
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = packet.main([str(argument) for argument in arguments])
        self.assertEqual(stderr.getvalue(), "")
        value = json.loads(stdout.getvalue())
        self.assertIs(type(value), dict)
        if before is not None:
            self.assertEqual(self.snapshot(root), before, "CLI changed retained inputs")
        return status, value

    def assert_invalid(self, *arguments):
        status, value = self.invoke(*arguments)
        self.assertEqual(status, 1)
        self.assertEqual(value["outcome"], "fail")
        self.assertEqual(value["integrity"], "invalid")
        self.assertIs(value["native_matrix_passed"], False)
        self.assertIs(value["phase_complete"], False)
        self.assertTrue(value["errors"])
        self.assertTrue(all(type(error) is str for error in value["errors"]))
        self.assertNotIn("manifest_written", value)
        return value

    def save_manifest(self, value=None, name="manifest.json"):
        if value is None:
            value = packet.verify_packet(self.root)["manifest"]
        path = self.base / name
        path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
        return path

    def test_full_cli_reports_integrity_without_phase_or_integration_acceptance(self):
        status, value = self.invoke("verify", self.root)
        self.assertEqual(status, 0)
        self.assertEqual(value["outcome"], "pass")
        self.assertEqual(value["run_outcome"], "pass")
        self.assertEqual(value["integrity"], "verified")
        self.assertIs(value["requirement_satisfied"], True)
        self.assertIs(value["native_matrix_passed"], True)
        self.assertEqual(value["selected_ids"], list(CASE_IDS))
        self.assertEqual(value["passed_ids"], list(CASE_IDS))
        self.assertEqual(value["failed_ids"], [])
        self.assertEqual(value["not_run_ids"], [])
        self.assertIs(value["phase_complete"], False)
        self.assertEqual(value["integration_outcome"], "blocked")
        self.assertIs(value["manifest_matched"], False)
        limitations = " ".join(value["limitations"]).lower()
        for boundary in ("unsigned", "unrelated directory", "independent review",
                         "never imported or executed", "vendor xrt"):
            self.assertIn(boundary, limitations)

    def test_full_native_requirement_succeeds_in_api_and_cli(self):
        before = self.snapshot(self.root)
        result = packet.verify_packet(self.root, require_native_pass=True)
        self.assertEqual(self.snapshot(self.root), before)
        status, cli_result = self.invoke("verify", self.root, "--require-native-pass")
        self.assertEqual(status, 0)
        self.assertEqual(cli_result, result)
        self.assertIs(result["requirement_satisfied"], True)
        self.assertIs(result["phase_complete"], False)

    def test_selected_success_and_failed_execution_keep_integrity_separate(self):
        scenarios = (
            ("selected", {"selected_ids": [CASE_IDS[0], CASE_IDS[2]]},
             "pass", [CASE_IDS[0], CASE_IDS[2]], [], []),
            ("failed", {"failed_case": CASE_IDS[1]},
             "fail", [CASE_IDS[0]], [CASE_IDS[1]], list(CASE_IDS[2:])),
        )
        for label, options, outcome, passed, failed, not_run in scenarios:
            root = self.base / label
            make_packet(root, **options)
            for require_native in (False, True):
                with self.subTest(packet=label, require_native=require_native):
                    flags = ["--require-native-pass"] if require_native else []
                    status, value = self.invoke("verify", root, *flags)
                    self.assertEqual(status, int(require_native))
                    self.assertEqual(value["outcome"], "fail" if require_native else "pass")
                    self.assertEqual(value["run_outcome"], outcome)
                    self.assertEqual(value["integrity"], "verified")
                    self.assertIs(value["native_matrix_passed"], False)
                    self.assertIs(value["requirement_satisfied"], not require_native)
                    self.assertEqual(value["passed_ids"], passed)
                    self.assertEqual(value["failed_ids"], failed)
                    self.assertEqual(value["not_run_ids"], not_run)
                    self.assertIs(value["phase_complete"], False)
                    self.assertEqual(value["integration_outcome"], "blocked")

    def test_seal_is_deterministic_unsigned_and_covers_exact_referenced_bytes(self):
        first, second = self.base / "first.json", self.base / "second.json"
        for output in (first, second):
            status, value = self.invoke("seal", self.root, "--output", output,
                                        "--require-native-pass")
            self.assertEqual(status, 0)
            self.assertIs(value["manifest_written"], True)
            self.assertEqual(json.loads(output.read_bytes()), value["manifest"])
        self.assertEqual(first.read_bytes(), second.read_bytes())
        manifest = json.loads(first.read_bytes())
        self.assertEqual(set(manifest), {
            "schema_version", "kind", "files", "native_matrix_passed", "phase_complete",
        })
        self.assertIs(type(manifest["schema_version"]), int)
        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(manifest["kind"], "p01-baseline-packet")
        self.assertIs(manifest["native_matrix_passed"], True)
        self.assertIs(manifest["phase_complete"], False)
        expected_paths = {"report.json", "matrix.json"}
        expected_paths.update(command["log"] for command in self.report["commands"])
        expected_paths.update(item["path"] for item in self.report["tooling_snapshots"])
        for case in self.report["cases"]:
            expected_paths.update(item["path"] for item in case["configuration_artifacts"])
        expected = []
        for relative in sorted(expected_paths):
            contents = (self.root / relative).read_bytes()
            expected.append({"path": relative, "size_bytes": len(contents),
                             "sha256": hashlib.sha256(contents).hexdigest()})
        self.assertEqual(manifest["files"], expected)
        self.assertNotIn(str(self.base), first.read_text(encoding="utf-8"))

    def test_relocated_packet_produces_the_same_manifest(self):
        original = packet.verify_packet(self.root)["manifest"]
        relocated = self.base / "relocated"
        shutil.copytree(self.root, relocated)
        status, result = self.invoke("verify", relocated)
        self.assertEqual(status, 0)
        self.assertEqual(result["manifest"], original)

    def test_unreferenced_files_are_preserved_and_outside_manifest_scope(self):
        original = packet.verify_packet(self.root)["manifest"]
        unused = self.root / "unreferenced.py"
        unused.write_text("raise RuntimeError('unreferenced source must never run')\n",
                          encoding="utf-8")
        status, result = self.invoke("verify", self.root)
        self.assertEqual(status, 0)
        self.assertEqual(result["manifest"], original)

    def test_selected_and_failed_packets_can_be_sealed_without_native_requirement(self):
        for label, options in (("selected", {"selected_ids": [CASE_IDS[0]]}),
                               ("failed", {"failed_case": CASE_IDS[0]})):
            with self.subTest(packet=label):
                root = self.base / label
                make_packet(root, **options)
                output = self.base / (label + ".json")
                status, value = self.invoke("seal", root, "--output", output)
                self.assertEqual(status, 0)
                self.assertIs(value["manifest_written"], True)
                self.assertIs(json.loads(output.read_bytes())["native_matrix_passed"], False)
                refused = self.base / (label + "-required.json")
                status, value = self.invoke("seal", root, "--output", refused,
                                            "--require-native-pass")
                self.assertEqual(status, 1)
                self.assertEqual(value["integrity"], "verified")
                self.assertIs(value["requirement_satisfied"], False)
                self.assertNotIn("manifest_written", value)
                self.assertFalse(refused.exists())

    def test_seal_refuses_existing_file_and_directory_without_overwriting(self):
        existing = self.base / "existing.json"
        original = b"independent prior result\n"
        existing.write_bytes(original)
        before = existing.stat()
        directory = self.base / "existing-directory"
        directory.mkdir()
        for output in (existing, directory):
            with self.subTest(output=output.name):
                self.assert_invalid("seal", self.root, "--output", output)
        self.assertEqual(existing.read_bytes(), original)
        self.assertEqual(existing.stat().st_mtime_ns, before.st_mtime_ns)
        self.assertEqual(list(directory.iterdir()), [])

    def test_seal_refuses_every_output_inside_packet(self):
        outputs = (self.root, self.root / "manifest.json",
                   self.root / "logs" / "manifest.json",
                   self.root / "logs" / ".." / "manifest.json",
                   self.root / "report.json")
        for output in outputs:
            with self.subTest(output=str(output.relative_to(self.root))):
                self.assert_invalid("seal", self.root, "--output", output)

    def test_seal_refuses_symlink_output_and_symlink_parent(self):
        target = self.base / "original.json"
        target.write_bytes(b"preserve external contents\n")
        linked_output = self.base / "linked.json"
        linked_output.symlink_to(target)
        packet_alias = self.base / "packet-alias"
        packet_alias.symlink_to(self.root, target_is_directory=True)
        for output in (linked_output, packet_alias / "manifest.json"):
            with self.subTest(output=str(output)):
                self.assert_invalid("seal", self.root, "--output", output)
        self.assertEqual(target.read_bytes(), b"preserve external contents\n")
        self.assertTrue(linked_output.is_symlink())
        self.assertFalse((self.root / "manifest.json").exists())

    def test_invalid_or_active_packet_is_never_sealed(self):
        for state in ("running", "planned"):
            with self.subTest(state=state):
                report = deepcopy(self.report)
                report["state"] = state
                save_report(self.root, report)
                output = self.base / (state + ".json")
                self.assert_invalid("verify", self.root)
                self.assert_invalid("seal", self.root, "--output", output)
                self.assertFalse(output.exists())

    def test_matching_supplied_manifest_is_read_only_and_format_independent(self):
        manifest = packet.verify_packet(self.root)["manifest"]
        supplied = self.save_manifest(dict(reversed(list(manifest.items()))))
        before = supplied.read_bytes(), supplied.stat().st_mtime_ns
        status, value = self.invoke("verify", self.root, "--manifest", supplied,
                                    "--require-native-pass")
        self.assertEqual(status, 0)
        self.assertIs(value["manifest_matched"], True)
        self.assertEqual(value["manifest"], manifest)
        self.assertEqual((supplied.read_bytes(), supplied.stat().st_mtime_ns), before)

    def test_supplied_manifest_rejects_changed_fields_or_inventory(self):
        original = packet.verify_packet(self.root)["manifest"]
        mutations = {
            "wrong-kind": lambda value: value.update(kind="accepted-baseline"),
            "wrong-version": lambda value: value.update(schema_version=2),
            "extra-field": lambda value: value.update(signature="not-authenticated"),
            "missing-field": lambda value: value.pop("phase_complete"),
            "wrong-hash": lambda value: value["files"][0].update(sha256="0" * 64),
            "wrong-size": lambda value: value["files"][0].update(size_bytes=0),
            "wrong-path": lambda value: value["files"][0].update(path="different.txt"),
            "missing-file": lambda value: value["files"].pop(),
            "duplicate-file": lambda value: value["files"].append(value["files"][0]),
            "reordered-files": lambda value: value["files"].reverse(),
        }
        for label, mutate in mutations.items():
            with self.subTest(mutation=label):
                manifest = deepcopy(original)
                mutate(manifest)
                supplied = self.save_manifest(manifest)
                before = supplied.read_bytes()
                self.assert_invalid("verify", self.root, "--manifest", supplied)
                self.assertEqual(supplied.read_bytes(), before)

    def test_supplied_manifest_rejects_boolean_and_numeric_type_coercion(self):
        original = packet.verify_packet(self.root)["manifest"]
        mutations = (
            ("schema_version", True), ("schema_version", 1.0),
            ("native_matrix_passed", 1), ("native_matrix_passed", "true"),
            ("phase_complete", 0), ("phase_complete", "false"),
        )
        for field, replacement in mutations:
            with self.subTest(field=field, replacement=replacement):
                manifest = deepcopy(original)
                manifest[field] = replacement
                supplied = self.save_manifest(manifest)
                self.assert_invalid("verify", self.root, "--manifest", supplied)
        for replacement in (True, float(original["files"][0]["size_bytes"])):
            with self.subTest(size_bytes=replacement):
                manifest = deepcopy(original)
                manifest["files"][0]["size_bytes"] = replacement
                supplied = self.save_manifest(manifest)
                self.assert_invalid("verify", self.root, "--manifest", supplied)

    def test_supplied_manifest_rejects_duplicate_keys_even_with_identical_values(self):
        manifest = packet.verify_packet(self.root)["manifest"]
        source = json.dumps(manifest)
        path_field = '"path": ' + json.dumps(manifest["files"][0]["path"])
        documents = (
            source.replace('"schema_version": 1',
                           '"schema_version": 1, "schema_version": 1', 1),
            source.replace(path_field, path_field + ", " + path_field, 1),
            source.replace(path_field, path_field + ", " +
                           path_field.replace('"path"', '"\\u0070ath"'), 1),
        )
        supplied = self.base / "manifest.json"
        for index, document in enumerate(documents):
            with self.subTest(duplicate=index):
                self.assertNotEqual(document, source)
                supplied.write_text(document, encoding="utf-8")
                self.assert_invalid("verify", self.root, "--manifest", supplied)
                self.assertEqual(supplied.read_text(encoding="utf-8"), document)

    def test_missing_or_malformed_supplied_manifest_is_invalid(self):
        supplied = self.base / "manifest.json"
        self.assert_invalid("verify", self.root, "--manifest", supplied)
        for contents in (b"[]", b"null", b"{} trailing", b'{"x": NaN}',
                         b'{"x": 1e400}', b'{"x":"\xff"}'):
            with self.subTest(contents=contents):
                supplied.write_bytes(contents)
                self.assert_invalid("verify", self.root, "--manifest", supplied)
                self.assertEqual(supplied.read_bytes(), contents)

    def test_changed_referenced_log_stamp_or_helper_invalidates_integrity(self):
        relatives = (
            self.report["commands"][0]["log"],
            self.report["cases"][0]["configuration_artifacts"][0]["path"],
            self.report["tooling_snapshots"][0]["path"],
        )
        supplied = self.save_manifest()
        for relative in relatives:
            with self.subTest(member=relative):
                member = self.root / relative
                original = member.read_bytes()
                member.write_bytes(original + b"changed retained evidence\n")
                self.assert_invalid("verify", self.root)
                self.assert_invalid("verify", self.root, "--manifest", supplied)
                member.write_bytes(original)

    def test_valid_changed_evidence_cannot_match_an_older_manifest(self):
        for label in ("report", "matrix", "log", "stamp"):
            with self.subTest(member=label):
                root = self.base / label
                report = make_packet(root)
                supplied = self.save_manifest(packet.verify_packet(root)["manifest"],
                                              label + "-manifest.json")
                if label in ("report", "matrix"):
                    member = root / (label + ".json")
                    member.write_bytes(member.read_bytes() + b"\n")
                elif label == "log":
                    command = report["commands"][0]
                    contents = (root / command["log"]).read_bytes()
                    refresh_log(root, command, contents + b"additional retained note\n")
                    save_report(root, report)
                else:
                    artifact = report["cases"][0]["configuration_artifacts"][0]
                    contents = (root / artifact["path"]).read_bytes()
                    refresh_stamp(root, artifact, contents + b"# retained formatting note\n")
                    save_report(root, report)
                status, value = self.invoke("verify", root)
                self.assertEqual(status, 0)
                self.assertEqual(value["integrity"], "verified")
                self.assert_invalid("verify", root, "--manifest", supplied)

    def test_change_after_contract_check_blocks_verification_and_sealing(self):
        real_verify = packet.verify_contract
        member = self.root / self.report["commands"][0]["log"]
        original = member.read_bytes()

        def change_after_check(reader, report, matrix):
            result = real_verify(reader, report, matrix)
            member.write_bytes(original + b"changed after contract verification\n")
            return result

        for mode in ("verify", "seal"):
            with self.subTest(mode=mode):
                member.write_bytes(original)
                output = self.base / "raced.json"
                flags = ["--output", output] if mode == "seal" else []
                with mock.patch.object(packet, "verify_contract", new=change_after_check):
                    status, value = self.invoke(mode, self.root, *flags,
                                                check_unchanged=False)
                self.assertEqual(status, 1)
                self.assertEqual(value["integrity"], "invalid")
                self.assertFalse(output.exists())

    def test_change_during_supplied_manifest_read_is_rechecked(self):
        supplied = self.save_manifest()
        member = self.root / self.report["commands"][0]["log"]
        original = member.read_bytes()
        real_read = packet.PacketReader.read_json
        changed = []

        def read_and_change(reader, relative, *args, **kwargs):
            value = real_read(reader, relative, *args, **kwargs)
            if relative == supplied.name:
                member.write_bytes(original + b"changed while manifest was read\n")
                changed.append(True)
            return value

        with mock.patch.object(packet.PacketReader, "read_json", new=read_and_change):
            status, value = self.invoke("verify", self.root, "--manifest", supplied,
                                        check_unchanged=False)
        self.assertEqual(changed, [True])
        self.assertEqual(status, 1)
        self.assertEqual(value["integrity"], "invalid")

    def test_invalid_input_errors_do_not_echo_private_paths_or_report_contents(self):
        secret = "PRIVATE_FIXTURE_TOKEN_NEVER_ECHO"
        missing = self.base / secret / "missing-packet"
        result = self.assert_invalid("verify", missing)
        self.assertNotIn(secret, json.dumps(result))
        self.assertNotIn(str(self.base), json.dumps(result))
        (self.root / "report.json").write_text(
            '{"private": "' + secret + '", "broken": }', encoding="utf-8")
        result = self.assert_invalid("verify", self.root)
        rendered = json.dumps(result)
        self.assertNotIn(secret, rendered)
        self.assertNotIn(str(self.base), rendered)
        self.assertNotIn("Traceback", rendered)

    def test_unexpected_operational_errors_are_safe_json_failures(self):
        secret = "PRIVATE_ERROR_DETAIL_NEVER_ECHO"
        for kind in (OSError, ValueError, UnicodeError, RecursionError):
            with self.subTest(exception=kind.__name__):
                with mock.patch.object(packet, "verify_packet", side_effect=kind(secret)):
                    result = self.assert_invalid("verify", self.root)
                self.assertNotIn(secret, json.dumps(result))
                self.assertNotIn("Traceback", json.dumps(result))

    def test_current_cli_entrypoint_runs_from_an_unrelated_working_directory(self):
        before = self.snapshot(self.root)
        result = subprocess.run(
            [sys.executable, "-B", str(Path(packet.__file__).resolve()), "verify",
             str(self.root), "--require-native-pass"],
            cwd=self.base, capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(result.stderr, "")
        value = json.loads(result.stdout)
        self.assertEqual(value["integrity"], "verified")
        self.assertIs(value["native_matrix_passed"], True)
        self.assertIs(value["phase_complete"], False)
        self.assertEqual(self.snapshot(self.root), before)


if __name__ == "__main__":
    unittest.main()
