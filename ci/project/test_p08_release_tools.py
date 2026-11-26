# SPDX-License-Identifier: Apache-2.0
"""Unit tests for ci/project/p08_release_tools.py (offline, stdlib only)."""

from __future__ import annotations

import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

_THIS_DIR = str(Path(__file__).resolve().parent)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

import p08_release_tools as tools


ROOT = Path(__file__).resolve().parents[2]


def _valid_soak_record() -> dict:
    return {
        "schema_version": 1,
        "driver": "xrt",
        "target": "hw",
        "physical_hardware": True,
        "board": "xilinx_u55c_gen3x16_xdma_3_202210_1",
        "bitstream_sha256": "a" * 64,
        "source_revision": "b" * 40,
        "achieved_clock_mhz": 250.0,
        "duration_seconds": 86400,
        "iterations_completed": 1440,
        "unexplained_errors": 0,
        "numerical_mismatches": 0,
        "hangs": 0,
        "error_events": [],
        "telemetry": {
            "temperature_c": {"min": 42.0, "max": 68.5},
            "power_w": {"min": 38.0, "max": 74.2},
            "memory_leak_bytes": 0,
        },
        "issue_dispositions": [],
    }


def _valid_fault_matrix() -> dict:
    return {
        "schema_version": 1,
        "driver": "xrt",
        "target": "hw",
        "require_physical": True,
        "cases": [
            {
                "case_id": "p08-malformed-unaligned-01",
                "fault_class": "malformed_args",
                "outcome": "pass",
                "expected_behavior": "Reject unaligned offset before DMA/launch with VX_ERR_INVALID_VALUE",
                "observed_behavior": "Rejected synchronously with VX_ERR_INVALID_VALUE; poison retained",
                "critical_finding_open": False,
            },
            {
                "case_id": "p08-exhaustion-oom-01",
                "fault_class": "resource_exhaustion",
                "outcome": "pass",
                "expected_behavior": "Return VX_ERR_OUT_OF_DEVICE_MEMORY and preserve baseline free bytes",
                "observed_behavior": "Returned VX_ERR_OUT_OF_DEVICE_MEMORY; free memory restored after cleanup",
                "critical_finding_open": False,
            },
            {
                "case_id": "p08-propagation-timeout-01",
                "fault_class": "error_propagation",
                "outcome": "pass",
                "expected_behavior": "Propagate asynchronous device fault/timeout without retiring success",
                "observed_behavior": "Event and queue_finish reported failure; repeated waits retained status",
                "critical_finding_open": False,
            },
            {
                "case_id": "p08-recovery-reset-01",
                "fault_class": "reset_recovery",
                "outcome": "pass",
                "expected_behavior": "Drain/reset failed context and run fresh workload to bit-exact match",
                "observed_behavior": "Device reset completed and subsequent matmul matched frozen P02 reference",
                "critical_finding_open": False,
            },
            {
                "case_id": "p08-isolation-canary-01",
                "fault_class": "memory_isolation",
                "outcome": "pass",
                "expected_behavior": "Reject OOB transfer and keep adjacent canary buffers untouched",
                "observed_behavior": "OOB copy rejected; adjacent host/device canary bytes unchanged",
                "critical_finding_open": False,
            },
        ],
    }


def _init_mini_repo(repo: Path, *, svg_bytes: bytes | None = None,
                    license_text: str | None = None,
                    include_micron_file: bool = True) -> None:
    (repo / "docs/assets/img").mkdir(parents=True)
    (repo / "third_party/ramulator/verilog_verification/sources").mkdir(parents=True)
    (repo / "hw/syn/libs/cln28hpm/rf2_32x19_wm0").mkdir(parents=True)

    if license_text is None:
        license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    (repo / "LICENSE").write_text(license_text, encoding="utf-8")
    (repo / "pyproject.toml").write_text((ROOT / "pyproject.toml").read_text(encoding="utf-8"), encoding="utf-8")

    if svg_bytes is None:
        svg_bytes = (ROOT / tools.PROTECTED_SVG_PATH).read_bytes()
    (repo / tools.PROTECTED_SVG_PATH).write_bytes(svg_bytes)

    (repo / "third_party/ramulator/LICENSE").write_text("MIT License\n", encoding="utf-8")
    if include_micron_file:
        (repo / "third_party/ramulator/verilog_verification/sources/ddr4_model.svp").write_text(
            "// MICRON TECHNOLOGY, INC. - CONFIDENTIAL AND PROPRIETARY INFORMATION\n",
            encoding="utf-8",
        )
    (repo / "hw/syn/libs/cln28hpm/rf2_32x19_wm0/rf2_32x19_wm0_rtl.v").write_text(
        "// CONFIDENTIAL AND PROPRIETARY SOFTWARE OF ARM PHYSICAL IP, INC.\n",
        encoding="utf-8",
    )

    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)


class SbomTests(unittest.TestCase):
    def test_repository_sbom_passes_and_flags_micron_and_proprietary_files(self):
        report = tools.generate_sbom(ROOT)
        self.assertEqual(report["outcome"], "pass", report["errors"])
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["root_license"]["kind"], "Apache-2.0")
        self.assertEqual(report["packaging"]["name"], "vortex-ai")
        self.assertEqual(report["packaging"]["license"], "Apache-2.0")
        self.assertTrue(report["protected_assets"][0]["verified"])
        self.assertEqual(report["protected_assets"][0]["actual_sha256"], tools.PROTECTED_SVG_SHA256)

        flagged = {item["path"]: item for item in report["proprietary_exclusions"]}
        # Check proprietary/non-redistributable Micron collateral in Ramulator (if checked out)
        # or foundry IP tracked in hw/syn/libs.
        self.assertIn("hw/syn/libs/NangateOpenCellLibrary_typical.lib", flagged)
        self.assertIn("hw/syn/libs/cln28hpm/rf2_32x19_wm0/rf2_32x19_wm0_rtl.v", flagged)
        ramulator_dir = ROOT / "third_party/ramulator/verilog_verification/sources"
        if ramulator_dir.is_dir():
            self.assertIn("third_party/ramulator/verilog_verification/sources/ddr4_model.svp", flagged)
            self.assertFalse(flagged["third_party/ramulator/verilog_verification/sources/ddr4_model.svp"]["redistributable"])
            self.assertTrue(flagged["third_party/ramulator/verilog_verification/sources/ddr4_model.svp"]["exclude_from_release_bundles"])

    def test_sbom_rejects_proprietary_files_in_bundle_manifest(self):
        with tempfile.TemporaryDirectory(prefix="p08-sbom-bundle-") as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_mini_repo(repo)
            clean = tools.generate_sbom(repo, check_bundle_paths=["LICENSE", "pyproject.toml"])
            self.assertEqual(clean["outcome"], "pass")
            self.assertEqual(clean["bundle_violations"], [])

            dirty = tools.generate_sbom(
                repo,
                check_bundle_paths=[
                    "LICENSE",
                    "third_party/ramulator/verilog_verification/sources/ddr4_model.svp",
                ],
            )
            self.assertEqual(dirty["outcome"], "fail")
            self.assertEqual(
                dirty["bundle_violations"],
                ["third_party/ramulator/verilog_verification/sources/ddr4_model.svp"],
            )

    def test_sbom_rejects_modified_protected_svg_and_non_apache_license(self):
        with tempfile.TemporaryDirectory(prefix="p08-sbom-neg-") as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_mini_repo(repo, svg_bytes=b"<svg>tampered</svg>", license_text="MIT License\n")
            report = tools.generate_sbom(repo)
            self.assertEqual(report["outcome"], "fail")
            self.assertFalse(report["protected_assets"][0]["verified"])
            self.assertTrue(any("Protected asset SHA-256 mismatch" in err for err in report["errors"]))
            self.assertTrue(any("Apache-2.0" in err for err in report["errors"]))

    def test_sbom_reproducible_output_and_cli_roundtrip(self):
        with tempfile.TemporaryDirectory(prefix="p08-sbom-cli-") as tmp:
            tmp_path = Path(tmp)
            manifest = tmp_path / "bundle.json"
            manifest.write_text(json.dumps({"files": ["LICENSE", "pyproject.toml"]}), encoding="utf-8")
            out_a = tmp_path / "sbom_a.json"
            out_b = tmp_path / "sbom_b.json"

            with redirect_stdout(io.StringIO()):
                rc_a = tools.main(["sbom", "--root", str(ROOT), "--bundle-manifest", str(manifest), "--output", str(out_a)])
                rc_b = tools.main(["sbom", "--root", str(ROOT), "--bundle-manifest", str(manifest), "--output", str(out_b)])
            self.assertEqual(rc_a, 0)
            self.assertEqual(rc_b, 0)
            self.assertEqual(out_a.read_text(encoding="utf-8"), out_b.read_text(encoding="utf-8"))


class Soak24AnalyzeTests(unittest.TestCase):
    def test_valid_24h_physical_soak_passes(self):
        record = _valid_soak_record()
        result = tools.analyze_soak24(record)
        self.assertEqual(result["outcome"], "pass", result["errors"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["duration_seconds"], 86400.0)

    def test_valid_soak_with_explicit_unavailable_telemetry_passes_with_warning(self):
        record = _valid_soak_record()
        record["duration_seconds"] = 90000
        record["telemetry"]["power_w"] = "unavailable"
        result = tools.analyze_soak24(record)
        self.assertEqual(result["outcome"], "pass", result["errors"])
        self.assertTrue(any("power_w" in w for w in result["warnings"]))

    def test_soak_rejects_duration_below_86400_seconds(self):
        for duration in (0, 3600, 86399, 86399.9):
            with self.subTest(duration=duration):
                record = _valid_soak_record()
                record["duration_seconds"] = duration
                result = tools.analyze_soak24(record)
                self.assertEqual(result["outcome"], "fail")
                self.assertTrue(any("86400" in err for err in result["errors"]))

    def test_soak_rejects_non_physical_drivers_and_targets(self):
        for driver, target in (
            ("simx", "simx"),
            ("rtlsim", "rtlsim"),
            ("xrtsim", "xrtsim"),
            ("xrt", "hw_emu"),
            ("xrt", "sw_emu"),
        ):
            with self.subTest(driver=driver, target=target):
                record = _valid_soak_record()
                record["driver"] = driver
                record["target"] = target
                result = tools.analyze_soak24(record)
                self.assertEqual(result["outcome"], "fail")
                self.assertTrue(result["errors"])

    def test_soak_rejects_unexplained_errors_mismatches_hangs_and_unexplained_events(self):
        bad_unexplained = _valid_soak_record()
        bad_unexplained["unexplained_errors"] = 1
        self.assertEqual(tools.analyze_soak24(bad_unexplained)["outcome"], "fail")

        bad_mismatch = _valid_soak_record()
        bad_mismatch["numerical_mismatches"] = 1
        self.assertEqual(tools.analyze_soak24(bad_mismatch)["outcome"], "fail")

        bad_hang = _valid_soak_record()
        bad_hang["hangs"] = 1
        self.assertEqual(tools.analyze_soak24(bad_hang)["outcome"], "fail")

        bad_event = _valid_soak_record()
        bad_event["error_events"] = [{"timestamp": "2026-11-26T00:00:00Z", "explained": False}]
        self.assertEqual(tools.analyze_soak24(bad_event)["outcome"], "fail")

    def test_soak_cli_exit_codes(self):
        with tempfile.TemporaryDirectory(prefix="p08-soak-cli-") as tmp:
            good_path = Path(tmp) / "good.json"
            bad_path = Path(tmp) / "bad.json"
            good_path.write_text(json.dumps(_valid_soak_record()), encoding="utf-8")
            bad = _valid_soak_record()
            bad["target"] = "hw_emu"
            bad_path.write_text(json.dumps(bad), encoding="utf-8")

            with redirect_stdout(io.StringIO()):
                self.assertEqual(tools.main(["soak24-analyze", str(good_path)]), 0)
                self.assertEqual(tools.main(["soak24-analyze", str(bad_path)]), 1)


class FaultMatrixCheckTests(unittest.TestCase):
    def test_complete_passing_fault_matrix_passes(self):
        matrix = _valid_fault_matrix()
        result = tools.check_fault_matrix(matrix)
        self.assertEqual(result["outcome"], "pass", result["errors"])
        self.assertEqual(result["evidence_level"], "fpga_measured")
        self.assertTrue(result["require_physical"])
        self.assertEqual(result["missing_classes"], [])
        self.assertEqual(result["failed_cases"], [])
        self.assertEqual(result["total_cases"], 5)

    def test_require_physical_defaults_to_true_and_simulated_opt_out_emits_simulated_level(self):
        default_simx = _valid_fault_matrix()
        del default_simx["require_physical"]
        default_simx["driver"] = "simx"
        default_simx["target"] = "simx"
        res_default = tools.check_fault_matrix(default_simx)
        self.assertEqual(res_default["outcome"], "fail")
        self.assertEqual(res_default["evidence_level"], "unqualified")
        self.assertTrue(res_default["require_physical"])

        sim_opt_out = _valid_fault_matrix()
        sim_opt_out["require_physical"] = False
        sim_opt_out["driver"] = "simx"
        sim_opt_out["target"] = "simx"
        res_sim = tools.check_fault_matrix(sim_opt_out)
        self.assertEqual(res_sim["outcome"], "pass", res_sim["errors"])
        self.assertEqual(res_sim["evidence_level"], "simulated")
        self.assertFalse(res_sim["require_physical"])

    def test_missing_any_required_fault_class_fails(self):
        base = _valid_fault_matrix()
        for cls in tools.REQUIRED_FAULT_CLASSES:
            with self.subTest(omitted_class=cls):
                mutated = copy.deepcopy(base)
                mutated["cases"] = [c for c in mutated["cases"] if c["fault_class"] != cls]
                result = tools.check_fault_matrix(mutated)
                self.assertEqual(result["outcome"], "fail")
                self.assertEqual(result["evidence_level"], "unqualified")
                self.assertIn(cls, result["missing_classes"])

    def test_failed_or_blocked_or_not_run_fault_case_fails(self):
        for outcome in ("fail", "blocked", "not_run"):
            with self.subTest(case_outcome=outcome):
                matrix = _valid_fault_matrix()
                matrix["cases"][0]["outcome"] = outcome
                result = tools.check_fault_matrix(matrix)
                self.assertEqual(result["outcome"], "fail")
                self.assertEqual(result["failed_cases"], [matrix["cases"][0]["case_id"]])

    def test_open_critical_finding_or_non_physical_allowlist_or_physical_false_fails(self):
        with_critical = _valid_fault_matrix()
        with_critical["cases"][2]["critical_finding_open"] = True
        self.assertEqual(tools.check_fault_matrix(with_critical)["outcome"], "fail")

        for driver, target, phys in (
            ("simx", "simx", True),
            ("xrt", "hw_emu_v2", True),
            ("custom_sim", "hw", True),
            ("xrt", "hw", False),
        ):
            with self.subTest(driver=driver, target=target, physical_hardware=phys):
                mutated = _valid_fault_matrix()
                mutated["driver"] = driver
                mutated["target"] = target
                mutated["physical_hardware"] = phys
                res = tools.check_fault_matrix(mutated)
                self.assertEqual(res["outcome"], "fail")
                self.assertEqual(res["evidence_level"], "unqualified")

    def test_fault_matrix_cli_exit_codes(self):
        with tempfile.TemporaryDirectory(prefix="p08-fault-cli-") as tmp:
            good_path = Path(tmp) / "good.json"
            bad_path = Path(tmp) / "bad.json"
            good_path.write_text(json.dumps(_valid_fault_matrix()), encoding="utf-8")
            bad = _valid_fault_matrix()
            bad["cases"].pop()
            bad_path.write_text(json.dumps(bad), encoding="utf-8")

            with redirect_stdout(io.StringIO()):
                self.assertEqual(tools.main(["fault-matrix-check", str(good_path)]), 0)
                self.assertEqual(tools.main(["fault-matrix-check", str(bad_path)]), 1)


if __name__ == "__main__":
    unittest.main()
