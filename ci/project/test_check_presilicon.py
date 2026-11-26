# SPDX-License-Identifier: Apache-2.0
"""Offline stdlib unit tests for ci/project/check_presilicon.py."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

HERE = str(Path(__file__).resolve().parent)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import check_presilicon as checker


SOURCE_ROOT = Path(__file__).resolve().parents[2]


class RealCheckoutPresiliconTests(unittest.TestCase):
    def test_real_presilicon_ledger_and_roadmap_pass(self):
        errors = checker.validate_presilicon(root=SOURCE_ROOT)
        self.assertEqual(errors, [])

    def test_real_ledger_metadata_and_tracks_match_adr006_contract(self):
        ledger = json.loads(
            (SOURCE_ROOT / "docs/project/presilicon_readiness.json").read_text(encoding="utf-8")
        )
        self.assertEqual(ledger["schema_version"], 1)
        self.assertEqual(ledger["adr"], "ADR-006")
        self.assertEqual(ledger["target_architecture"], "aigpu-b1")
        self.assertEqual(ledger["rtl_slice_profile"], "aigpu-b1-tile")
        self.assertEqual(
            ledger["allowed_evidence_levels"],
            ["source_present", "simulated", "rtl_verified"],
        )
        self.assertTrue(ledger["physical_gates_unwaived"])
        track_statuses = {track["id"]: track["status"] for track in ledger["tracks"]}
        self.assertEqual(
            track_statuses,
            {
                "TRACK-A": "not_started",
                "TRACK-B": "in_progress",
                "TRACK-C": "not_started",
                "TRACK-D": "not_started",
                "TRACK-E": "not_started",
                "TRACK-F": "not_started",
            },
        )
        for track in ledger["tracks"]:
            self.assertEqual(track["evidence"], [])

    def test_cli_main_passes_on_real_checkout(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            rc = checker.main(["--root", str(SOURCE_ROOT)])
        self.assertEqual(rc, 0)
        self.assertIn("passed", stdout.getvalue())
        self.assertEqual(stderr.getvalue(), "")


class PresiliconValidatorTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ai-gpu-presilicon-test-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.ledger = json.loads(
            (SOURCE_ROOT / "docs/project/presilicon_readiness.json").read_text(encoding="utf-8")
        )
        self.roadmap = json.loads(
            (SOURCE_ROOT / "docs/project/roadmap.json").read_text(encoding="utf-8")
        )
        self._write_json("docs/project/roadmap.json", self.roadmap)
        self._write_json("docs/project/presilicon_readiness.json", self.ledger)

    def _write_bytes(self, rel_path: str, payload: bytes) -> Path:
        target = self.root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        return target

    def _write_json(self, rel_path: str, data: dict) -> Path:
        return self._write_bytes(
            rel_path, (json.dumps(data, indent=2) + "\n").encode("utf-8")
        )

    def _add_valid_evidence(
        self,
        track_id: str,
        *,
        rel_path: str = "docs/project/evidence/synthetic_presilicon.json",
        payload: bytes = b'{"synthetic": true}\n',
        evidence_level: str = "rtl_verified",
        commit: str = "3f12943ef10dae4953a97e3c9081e94aabd8ed98",
        summary: str = "Synthetic unit-test evidence artifact.",
        mark_complete: bool = False,
    ) -> str:
        self._write_bytes(rel_path, payload)
        digest = hashlib.sha256(payload).hexdigest()
        for track in self.ledger["tracks"]:
            if track["id"] == track_id:
                track["evidence"].append(
                    {
                        "path": rel_path,
                        "sha256": digest,
                        "evidence_level": evidence_level,
                        "commit": commit,
                        "summary": summary,
                    }
                )
                if mark_complete:
                    track["status"] = "complete"
                break
        return digest

    def _validate(self) -> list[str]:
        return checker.validate_presilicon_data(
            self.ledger, self.root, roadmap=self.roadmap
        )

    def test_valid_complete_track_with_matching_evidence_and_sha256_passes(self):
        self._add_valid_evidence(
            "TRACK-B",
            evidence_level="rtl_verified",
            mark_complete=True,
        )
        self._add_valid_evidence(
            "TRACK-A",
            rel_path="docs/project/evidence/track_a.json",
            payload=b'{"profile": "aigpu-b1-tile"}\n',
            evidence_level="simulated",
            mark_complete=True,
        )
        self.assertEqual(self._validate(), [])

    def test_rejects_fpga_measured_and_silicon_measured_claims(self):
        for bad_level in ("fpga_measured", "silicon_measured"):
            with self.subTest(bad_level=bad_level, location="track_evidence"):
                ledger = copy.deepcopy(self.ledger)
                self._write_bytes("docs/project/evidence/ev.json", b"{}\n")
                digest = hashlib.sha256(b"{}\n").hexdigest()
                ledger["tracks"][1]["evidence"].append(
                    {
                        "path": "docs/project/evidence/ev.json",
                        "sha256": digest,
                        "evidence_level": bad_level,
                        "commit": "3f12943",
                        "summary": "Forbidden physical level claim.",
                    }
                )
                errors = checker.validate_presilicon_data(
                    ledger, self.root, roadmap=self.roadmap
                )
                self.assertTrue(errors)
                self.assertTrue(any(bad_level in err for err in errors))

            with self.subTest(bad_level=bad_level, location="allowed_evidence_levels"):
                ledger = copy.deepcopy(self.ledger)
                ledger["allowed_evidence_levels"].append(bad_level)
                errors = checker.validate_presilicon_data(
                    ledger, self.root, roadmap=self.roadmap
                )
                self.assertTrue(errors)
                self.assertTrue(any("allowed_evidence_levels" in err or bad_level in err for err in errors))

            with self.subTest(bad_level=bad_level, location="required_evidence_level"):
                ledger = copy.deepcopy(self.ledger)
                ledger["tracks"][0]["required_evidence_level"] = bad_level
                errors = checker.validate_presilicon_data(
                    ledger, self.root, roadmap=self.roadmap
                )
                self.assertTrue(errors)
                self.assertTrue(any(bad_level in err for err in errors))

    def test_rejects_complete_track_with_empty_evidence(self):
        for track in self.ledger["tracks"]:
            with self.subTest(track_id=track["id"]):
                ledger = copy.deepcopy(self.ledger)
                for item in ledger["tracks"]:
                    if item["id"] == track["id"]:
                        item["status"] = "complete"
                        item["evidence"] = []
                errors = checker.validate_presilicon_data(
                    ledger, self.root, roadmap=self.roadmap
                )
                self.assertTrue(errors)
                self.assertTrue(any("empty evidence" in err for err in errors))

    def test_rejects_mismatched_sha256_and_missing_evidence_file(self):
        self._add_valid_evidence("TRACK-B", evidence_level="rtl_verified", mark_complete=True)
        # Tamper with file bytes after computing SHA-256
        self._write_bytes("docs/project/evidence/synthetic_presilicon.json", b'{"tampered": true}\n')
        errors = self._validate()
        self.assertTrue(errors)
        self.assertTrue(any("SHA-256 mismatch" in err for err in errors))
        self.assertTrue(any("lacks an evidence entry" in err for err in errors))

        # Missing file on disk
        (self.root / "docs/project/evidence/synthetic_presilicon.json").unlink()
        errors_missing = self._validate()
        self.assertTrue(errors_missing)
        self.assertTrue(any("missing file on disk" in err for err in errors_missing))

    def test_rejects_evidence_level_below_required_level(self):
        # TRACK-B requires rtl_verified; simulated and source_present must fail
        for weak_level in ("source_present", "simulated"):
            with self.subTest(weak_level=weak_level):
                self.ledger = json.loads(
                    (SOURCE_ROOT / "docs/project/presilicon_readiness.json").read_text(encoding="utf-8")
                )
                self._add_valid_evidence(
                    "TRACK-B",
                    evidence_level=weak_level,
                    mark_complete=True,
                )
                errors = self._validate()
                self.assertTrue(errors)
                self.assertTrue(any("below track required_evidence_level" in err for err in errors))

        # TRACK-E requires simulated; source_present must fail
        self.ledger = json.loads(
            (SOURCE_ROOT / "docs/project/presilicon_readiness.json").read_text(encoding="utf-8")
        )
        self._add_valid_evidence(
            "TRACK-E",
            evidence_level="source_present",
            mark_complete=False,
        )
        errors_e = self._validate()
        self.assertTrue(errors_e)
        self.assertTrue(any("below track required_evidence_level" in err for err in errors_e))

    def test_rejects_invalid_commit_hash_and_invalid_status(self):
        for bad_commit in ("", "not-a-hex-hash", "0" * 40, "abc12", "g" * 40):
            with self.subTest(bad_commit=bad_commit):
                self.ledger = json.loads(
                    (SOURCE_ROOT / "docs/project/presilicon_readiness.json").read_text(encoding="utf-8")
                )
                self._add_valid_evidence("TRACK-A", evidence_level="source_present", commit=bad_commit)
                errors = self._validate()
                self.assertTrue(errors)
                self.assertTrue(any("commit" in err for err in errors))

        for bad_status in ("blocked", "passed", "pending", ""):
            with self.subTest(bad_status=bad_status):
                ledger = copy.deepcopy(self.ledger)
                ledger["tracks"][0]["status"] = bad_status
                errors = checker.validate_presilicon_data(
                    ledger, self.root, roadmap=self.roadmap
                )
                self.assertTrue(errors)
                self.assertTrue(any("status" in err for err in errors))

    def test_rejects_waived_physical_gates_or_unblocked_p01_without_hardware_pass(self):
        # physical_gates_unwaived = False
        ledger = copy.deepcopy(self.ledger)
        ledger["physical_gates_unwaived"] = False
        errors = checker.validate_presilicon_data(ledger, self.root, roadmap=self.roadmap)
        self.assertTrue(any("physical_gates_unwaived" in err for err in errors))

        # Roadmap P01 silently marked in_progress or complete without passing P01-A03
        for bad_p01_status in ("in_progress", "not_started", "complete"):
            with self.subTest(p01_status=bad_p01_status):
                roadmap = copy.deepcopy(self.roadmap)
                for phase in roadmap["phases"]:
                    if phase["id"] == "P01":
                        phase["status"] = bad_p01_status
                errors = checker.validate_presilicon_data(
                    self.ledger, self.root, roadmap=roadmap
                )
                self.assertTrue(errors)
                self.assertTrue(any("roadmap.P01" in err for err in errors))

        # Roadmap P11 silently removed
        roadmap_no_p11 = copy.deepcopy(self.roadmap)
        roadmap_no_p11["phases"] = [
            phase for phase in roadmap_no_p11["phases"] if phase["id"] != "P11"
        ]
        errors_p11 = checker.validate_presilicon_data(
            self.ledger, self.root, roadmap=roadmap_no_p11
        )
        self.assertTrue(any("P11" in err for err in errors_p11))

        # Roadmap P07 silently drops P01 dependency
        roadmap_no_dep = copy.deepcopy(self.roadmap)
        for phase in roadmap_no_dep["phases"]:
            if phase["id"] == "P07":
                phase["depends_on"] = ["P04", "P06"]
        errors_dep = checker.validate_presilicon_data(
            self.ledger, self.root, roadmap=roadmap_no_dep
        )
        self.assertTrue(any("P07.depends_on" in err for err in errors_dep))

    def test_cli_main_exits_nonzero_on_invalid_ledger(self):
        bad_ledger = copy.deepcopy(self.ledger)
        bad_ledger["tracks"][0]["status"] = "complete"
        bad_ledger_path = self._write_json("docs/project/presilicon_readiness.json", bad_ledger)
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            rc = checker.main(
                [
                    "--root",
                    str(self.root),
                    "--ledger",
                    str(bad_ledger_path),
                    "--roadmap",
                    str(self.root / "docs/project/roadmap.json"),
                ]
            )
        self.assertEqual(rc, 1)
        self.assertIn("ERROR:", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
