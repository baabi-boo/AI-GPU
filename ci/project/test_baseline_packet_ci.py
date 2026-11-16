# SPDX-License-Identifier: Apache-2.0
"""Independent CI checks over synthetic exports; no GPU execution is performed."""

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

import check_baseline_packets as checker
from baseline_packet_export import verify_export
from baseline_packet_export_fixture import make_export, save_export_manifest
from baseline_packet_fixture import CASE_IDS, save_report


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PACKET_PATHS = {
    "native": "docs/project/evidence/p01/native",
    "clean-build": "docs/project/evidence/p01/clean-build",
}


@unittest.skipUnless(os.name == "posix" and hasattr(os, "O_NOFOLLOW"),
                     "packet filesystem safety requires POSIX no-follow support")
class BaselinePacketCITests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="baseline-packet-ci-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.root = self.base / "synthetic checkout"
        self.outside = self.base / "unrelated working directory"
        self.outside.mkdir()
        self.manifests = self.make_repository(self.root)

    @staticmethod
    def make_repository(root, *, native=None, clean=None):
        return {
            "native": make_export(root / PACKET_PATHS["native"], **(native or {})),
            "clean-build": make_export(root / PACKET_PATHS["clean-build"], **(
                {"selected_ids": [CASE_IDS[0]]} if clean is None else clean)),
        }

    @staticmethod
    def snapshot(root):
        if not root.exists():
            return None
        result = {}
        for path in [root, *root.rglob("*")]:
            info = path.lstat()
            contents = path.read_bytes() if stat.S_ISREG(info.st_mode) else None
            result[path.relative_to(root).as_posix()] = (
                info.st_ino, info.st_mode, info.st_mtime_ns, contents,
            )
        return result

    def assert_boundaries(self, result):
        self.assertEqual(set(result), {
            "schema_version", "outcome", "phase_complete", "scope",
            "raw_log_bytes_verified", "redaction_relationship_verified", "packets",
        })
        self.assertEqual(result["schema_version"], 1)
        self.assertIs(result["phase_complete"], False)
        self.assertIs(result["raw_log_bytes_verified"], False)
        self.assertIs(result["redaction_relationship_verified"], False)
        self.assertEqual(result["scope"],
                         "Published evidence consistency only; no project-gate acceptance.")
        self.assertEqual(set(result["packets"]), set(PACKET_PATHS))
        for name, relative in PACKET_PATHS.items():
            packet = result["packets"][name]
            self.assertEqual(packet["path"], relative)
            self.assertIs(packet["require_native_records"], name == "native")
            self.assertLessEqual(set(packet), {
                "path", "require_native_records", "outcome", "published_integrity",
                "run_outcome", "native_matrix_records_consistent", "errors",
            })
            self.assertIn(packet["outcome"], ("pass", "fail"))
            if packet["outcome"] == "fail":
                self.assertTrue(packet["errors"])
            else:
                self.assertNotIn("errors", packet)

    def check(self, root=None):
        root = self.root if root is None else root
        before = self.snapshot(root)
        result = checker.check_baseline_packets(root)
        self.assertEqual(self.snapshot(root), before, "CI checking changed its inputs")
        self.assert_boundaries(result)
        return result

    def assert_outcomes(self, result, *, native="pass", clean="pass"):
        self.assertEqual(result["packets"]["native"]["outcome"], native)
        self.assertEqual(result["packets"]["clean-build"]["outcome"], clean)
        self.assertEqual(result["outcome"],
                         "pass" if native == clean == "pass" else "fail")

    def assert_invalid(self, result, name):
        self.assert_outcomes(result, **({"native": "fail"} if name == "native"
                                        else {"clean": "fail"}))
        self.assertEqual(result["packets"][name]["published_integrity"], "invalid")

    def clone(self, label):
        root = self.base / label
        shutil.copytree(self.root, root)
        return root

    def invoke_main(self, root):
        before = self.snapshot(root)
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = checker.main(["--root", str(root)])
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(len(stdout.getvalue().splitlines()), 1)
        result = json.loads(stdout.getvalue())
        self.assert_boundaries(result)
        self.assertEqual(self.snapshot(root), before, "CI main changed its inputs")
        return status, result

    def invoke_process(self, *arguments, script=None, root=None):
        root = self.root if root is None else root
        before = self.snapshot(root)
        completed = subprocess.run(
            [sys.executable, "-B", str(script or HERE / "check_baseline_packets.py"),
             *map(str, arguments)], cwd=self.outside, capture_output=True,
            text=True, timeout=15, check=False,
        )
        self.assertEqual(completed.stderr, "")
        self.assertEqual(len(completed.stdout.splitlines()), 1)
        result = json.loads(completed.stdout)
        self.assert_boundaries(result)
        self.assertEqual(self.snapshot(root), before, "CI process changed its inputs")
        return completed.returncode, result

    def test_full_native_and_selected_clean_build_pass_the_fixed_requirements(self):
        result = self.check()
        self.assert_outcomes(result)
        for name, packet in result["packets"].items():
            self.assertEqual(packet["published_integrity"], "verified")
            self.assertEqual(packet["run_outcome"], "pass")
            self.assertIs(packet["native_matrix_records_consistent"], name == "native")

    def test_clean_build_can_also_contain_a_complete_native_matrix(self):
        root = self.base / "complete-clean-build"
        self.make_repository(root, clean={})
        result = self.check(root)
        self.assert_outcomes(result)
        self.assertIs(result["packets"]["clean-build"]["native_matrix_records_consistent"],
                      True)

    def test_passing_native_subset_does_not_satisfy_the_native_requirement(self):
        root = self.base / "native-subset"
        self.make_repository(root, native={"selected_ids": [CASE_IDS[0]]})
        published = verify_export(root / PACKET_PATHS["native"],
                                  require_native_records=False)
        self.assertEqual(published["outcome"], "pass")
        self.assertEqual(published["run_outcome"], "pass")
        self.assertIs(published["native_matrix_records_consistent"], False)
        result = self.check(root)
        self.assert_outcomes(result, native="fail")
        native = result["packets"]["native"]
        self.assertEqual(native["published_integrity"], "verified")
        self.assertEqual(native["run_outcome"], "pass")
        self.assertIs(native["native_matrix_records_consistent"], False)
        self.assertEqual(native["errors"],
                         ["published evidence requirement is not satisfied"])

    def test_failed_clean_run_fails_even_when_export_verification_passes(self):
        root = self.base / "failed-clean-build"
        self.make_repository(root, clean={
            "selected_ids": [CASE_IDS[0]], "failed_case": CASE_IDS[0],
        })
        published = verify_export(root / PACKET_PATHS["clean-build"],
                                  require_native_records=False)
        self.assertEqual(published["outcome"], "pass")
        self.assertEqual(published["published_integrity"], "verified")
        self.assertIs(published["requirement_satisfied"], True)
        self.assertEqual(published["run_outcome"], "fail")
        result = self.check(root)
        self.assert_outcomes(result, clean="fail")
        clean = result["packets"]["clean-build"]
        self.assertEqual(clean["published_integrity"], "verified")
        self.assertEqual(clean["run_outcome"], "fail")
        self.assertEqual(clean["errors"], ["retained run outcome must be pass"])

    def test_failed_native_run_retains_both_failure_reasons_and_checks_clean_build(self):
        root = self.base / "failed-native"
        self.make_repository(root, native={"failed_case": CASE_IDS[1]})
        result = self.check(root)
        self.assert_outcomes(result, native="fail")
        native = result["packets"]["native"]
        self.assertEqual(native["published_integrity"], "verified")
        self.assertEqual(native["run_outcome"], "fail")
        self.assertEqual(set(native["errors"]), {
            "published evidence requirement is not satisfied",
            "retained run outcome must be pass",
        })

    def test_missing_packet_uses_only_its_fixed_path_and_checks_the_other_packet(self):
        for name, relative in PACKET_PATHS.items():
            with self.subTest(packet=name):
                root = self.clone("missing-" + name)
                (root / relative).rename(root / name)
                result = self.check(root)
                self.assert_invalid(result, name)
                self.assertFalse((root / relative).exists())

    def test_missing_export_manifest_does_not_skip_the_other_packet(self):
        for name, relative in PACKET_PATHS.items():
            with self.subTest(packet=name):
                root = self.clone("missing-manifest-" + name)
                (root / relative / "export-manifest.json").unlink()
                self.assert_invalid(self.check(root), name)

    def test_missing_repository_reports_both_packets_without_creating_files(self):
        root = self.base / "absent"
        result = self.check(root)
        self.assert_outcomes(result, native="fail", clean="fail")
        for packet in result["packets"].values():
            self.assertEqual(packet["published_integrity"], "invalid")
        self.assertFalse(root.exists())

    def test_tampered_logs_reports_and_matrix_fail_for_either_packet(self):
        members = ("logs/" + CASE_IDS[0] + ".log", "report.json", "matrix.json")
        for name, relative in PACKET_PATHS.items():
            for index, member in enumerate(members):
                with self.subTest(packet=name, member=member):
                    root = self.clone("tampered-" + name + "-" + str(index))
                    with (root / relative / member).open("ab") as destination:
                        destination.write(b"\n ")
                    self.assert_invalid(self.check(root), name)

    def test_missing_unknown_and_invalid_export_fields_fail_closed(self):
        mutations = (
            ("missing-scope", lambda manifest: manifest.pop("scope")),
            ("unknown-field", lambda manifest: manifest.update(accepted=True)),
            ("boolean-schema", lambda manifest: manifest.update(schema_version=True)),
            ("invalid-outcome", lambda manifest: manifest.update(reported_outcome="not_run")),
            ("invalid-artifact", lambda manifest: manifest["artifacts"].__setitem__(0, [])),
        )
        for name, relative in PACKET_PATHS.items():
            for label, mutate in mutations:
                with self.subTest(packet=name, mutation=label):
                    root = self.clone(name + "-" + label)
                    manifest = deepcopy(self.manifests[name])
                    mutate(manifest)
                    save_export_manifest(root / relative, manifest)
                    self.assert_invalid(self.check(root), name)

    def test_invalid_retained_fields_fail_even_with_updated_export_identities(self):
        mutations = (
            ("missing-coverage", lambda report: report.pop("coverage")),
            ("unknown-field", lambda report: report.update(accepted=True)),
            ("invalid-schema", lambda report: report.update(schema_version=False)),
            ("false-completion", lambda report: report.update(phase_complete=True)),
        )
        for name, relative in PACKET_PATHS.items():
            for label, mutate in mutations:
                with self.subTest(packet=name, mutation=label):
                    root = self.clone("retained-" + name + "-" + label)
                    packet = root / relative
                    report = json.loads((packet / "report.json").read_bytes())
                    mutate(report)
                    save_report(packet, report)
                    contents = (packet / "report.json").read_bytes()
                    digest = hashlib.sha256(contents).hexdigest()
                    manifest = deepcopy(self.manifests[name])
                    source = manifest["source_packet"] + "/report.json"
                    row = next(row for row in manifest["artifacts"]
                               if row["source_path"] == source)
                    row.update(sha256=digest, source_sha256=digest,
                               size_bytes=len(contents), source_size_bytes=len(contents))
                    save_export_manifest(packet, manifest)
                    self.assert_invalid(self.check(root), name)

    def test_malformed_manifest_bytes_produce_json_failure_without_a_traceback(self):
        for index, contents in enumerate((b"{", b"\xff", b"[]\n")):
            with self.subTest(contents=contents):
                root = self.clone("malformed-" + str(index))
                (root / PACKET_PATHS["native"] / "export-manifest.json").write_bytes(contents)
                status, result = self.invoke_main(root)
                self.assertEqual(status, 1)
                self.assert_invalid(result, "native")

    def test_main_root_option_emits_one_json_result_and_matching_exit_status(self):
        status, result = self.invoke_main(self.root)
        self.assertEqual(status, 0)
        self.assertEqual(result, self.check())
        (self.root / PACKET_PATHS["clean-build"] / "export-manifest.json").unlink()
        status, result = self.invoke_main(self.root)
        self.assertEqual(status, 1)
        self.assert_invalid(result, "clean-build")

    def test_cli_absolute_and_relative_root_are_independent_of_working_directory(self):
        expected = self.check()
        for root_argument in (self.root, os.path.relpath(self.root, self.outside)):
            with self.subTest(root_argument=str(root_argument)):
                status, result = self.invoke_process("--root", root_argument)
                self.assertEqual(status, 0)
                self.assertEqual(result, expected)

    def test_cli_failure_returns_nonzero_and_still_reports_both_packets(self):
        (self.root / PACKET_PATHS["native"] / "export-manifest.json").unlink()
        status, result = self.invoke_process("--root", self.root)
        self.assertEqual(status, 1)
        self.assert_invalid(result, "native")

    def test_cli_default_root_is_the_checkout_containing_the_script(self):
        destination = self.root / "ci/project"
        destination.mkdir(parents=True)
        for filename in ("check_baseline_packets.py", "baseline_packet_export.py",
                         "baseline_packet_contract.py", "baseline_packet_io.py",
                         "baseline_matrix.py"):
            shutil.copyfile(HERE / filename, destination / filename)
        status, result = self.invoke_process(script=destination / "check_baseline_packets.py")
        self.assertEqual(status, 0)
        self.assertEqual(result, self.check())
        self.assertEqual(list(self.outside.iterdir()), [])


class BaselinePacketCIWorkflowTests(unittest.TestCase):
    def test_governance_runs_the_same_checker_as_an_unconditional_failing_step(self):
        workflow = (ROOT / ".github/workflows/project-governance.yml").read_text(encoding="utf-8")
        steps = re.split(r"(?m)^      - ", workflow)[1:]
        matching = [step for step in steps if "check_baseline_packets.py" in step]
        self.assertEqual(matching, [
            "name: Check published baseline packet consistency\n"
            "        run: python3 ci/project/check_baseline_packets.py\n",
        ])
        self.assertLess(workflow.index("run: python3 ci/project/check_project.py"),
                        workflow.index("run: python3 ci/project/check_baseline_packets.py"))
        self.assertLess(workflow.index("run: python3 ci/project/check_baseline_packets.py"),
                        workflow.index("run: python3 -m unittest discover"))

    def test_governance_keeps_the_existing_read_only_runtime_contract(self):
        workflow = (ROOT / ".github/workflows/project-governance.yml").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r"(?m)^([ \t]*)permissions:", workflow), [""])
        self.assertRegex(workflow, r"(?m)^permissions:\n  contents: read$")
        self.assertEqual(re.findall(r"(?m)^    runs-on: (.+)$", workflow), ["ubuntu-24.04"])
        self.assertEqual(re.findall(r"(?m)^    timeout-minutes: (.+)$", workflow), ["10"])
        self.assertIn("assert sys.version_info[:2] == (3, 12)", workflow)
        for option in ("submodules", "lfs", "persist-credentials"):
            self.assertRegex(workflow, r"(?m)^          " + option + ": false$")
        self.assertNotRegex(workflow, r"\bpull_request_target\b|\bself-hosted\b")


if __name__ == "__main__":
    unittest.main()
