# SPDX-License-Identifier: Apache-2.0
"""Offline unit tests for the P07 physical FPGA preflight, planner, and soak analyzer."""

from __future__ import annotations

from contextlib import ExitStack, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

HERE = str(Path(__file__).resolve().parent)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import p07_fpga_harness as harness


U55C_PLATFORM = "xilinx_u55c_gen3x16_xdma_3_202210_1"
VALID_BDF = "0000:3d:00.1"


def _make_xbutil_payload(
    *,
    bdf: str = VALID_BDF,
    vbnv: str = U55C_PLATFORM,
    is_ready: bool = True,
) -> dict:
    return {
        "system": {
            "host": {
                "devices": [
                    {
                        "bdf": bdf,
                        "vbnv": vbnv,
                        "is_ready": is_ready,
                    }
                ]
            }
        }
    }


def _make_clean_soak_lines(
    *,
    bdf: str = VALID_BDF,
    target: str = "hw",
    driver: str | None = "xrt",
    telemetry_driver: str | None = "xrt",
    telemetry_target: str | None = "hw",
    start_ts: float = 1700000000.0,
    duration_s: float = 3600.0,
    steps: int = 12,
    include_sensors: bool = True,
) -> list[str]:
    lines: list[str] = []
    dt = duration_s / steps
    for idx in range(steps + 1):
        ts = start_ts + idx * dt
        iter_rec: dict = {
            "timestamp": ts,
            "kind": "iteration",
            "bdf": bdf,
            "target": target,
            "app": "sgemm_tcu" if idx % 2 == 0 else "ai_mlp_fused",
            "status": "pass",
            "numerical_mismatches": 0,
            "dma_errors": 0,
            "reset_errors": 0,
            "throughput_gflops": 120.5 + (idx % 3),
        }
        if driver is not None:
            iter_rec["driver"] = driver
        lines.append(json.dumps(iter_rec))
        telem_rec: dict = {
            "timestamp": ts,
            "kind": "telemetry",
            "bdf": bdf,
            "temp_c": 58.0 + (idx % 4) if include_sensors else None,
            "power_w": 64.5 + (idx % 2) if include_sensors else None,
            "ecc_errors": 0,
        }
        if telemetry_target is not None:
            telem_rec["target"] = telemetry_target
        if telemetry_driver is not None:
            telem_rec["driver"] = telemetry_driver
        lines.append(json.dumps(telem_rec))
    return lines


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.tmpdir = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.xrt_dir = self.tmpdir / "xrt"
        self.xrt_dir.mkdir()
        self.xclbin = self.tmpdir / "vortex_afu.xclbin"
        self.xclbin.write_bytes(b"SYNTHETIC_XCLBIN_IMAGE_FOR_OFFLINE_HASH_ONLY")
        self.xclbin_sha = hashlib.sha256(self.xclbin.read_bytes()).hexdigest()
        self.vbin = self.tmpdir / "vortex_afu.vbin"
        self.vbin.write_bytes(b"SYNTHETIC_VBIN_IMAGE_FOR_OFFLINE_HASH_ONLY")
        self.vbin_sha = hashlib.sha256(self.vbin.read_bytes()).hexdigest()
        self.env = {
            "PATH": "/usr/bin:/bin",
            "XILINX_XRT": str(self.xrt_dir),
        }

    def _mock_xbutil(self, payload: dict | None = None, returncode: int = 0):
        raw = json.dumps(_make_xbutil_payload() if payload is None else payload)
        proc = SimpleNamespace(returncode=returncode, stdout=raw, stderr="")
        self.stack.enter_context(mock.patch.object(harness.shutil, "which", return_value="/opt/xilinx/xrt/bin/xbutil"))
        self.stack.enter_context(mock.patch.object(harness.subprocess, "run", return_value=proc))

    def _mock_v80_smi(self, stdout: str, returncode: int = 0):
        proc = SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")
        self.stack.enter_context(mock.patch.object(harness.shutil, "which", return_value="/opt/xilinx/slash/bin/v80-smi"))
        self.stack.enter_context(mock.patch.object(harness.subprocess, "run", return_value=proc))

    def test_physical_hw_preflight_passes_with_verified_identity_and_sha256(self):
        self._mock_xbutil()
        report = harness.run_preflight(
            target="hw",
            requested_evidence="fpga_measured",
            bdf="3d:00.1",
            platform=U55C_PLATFORM,
            xclbin=self.xclbin,
            expected_sha256=self.xclbin_sha,
            environ=self.env,
        )
        self.assertEqual(report["outcome"], "pass")
        self.assertTrue(report["eligible_for_fpga_measured"])
        self.assertEqual(report["board"], "u55c")
        self.assertEqual(report["driver"], "xrt")
        self.assertEqual(report["bdf"], VALID_BDF)
        self.assertEqual(report["xclbin"]["sha256"], self.xclbin_sha)
        self.assertEqual(report["device_identity"]["vbnv"], U55C_PLATFORM)
        self.assertEqual(report["blockers"], [])

    def test_v80_preflight_uses_v80_smi_and_vrt_device_bdf_without_xbutil_or_xilinx_xrt(self):
        self._mock_v80_smi("Board 0000:01:00 OK (PF0: OK) (PF1: OK) (PF2: OK) (VRTD: OK)\n")
        report = harness.run_preflight(
            board="v80",
            target="hw",
            requested_evidence="fpga_measured",
            bdf="01:00.0",
            platform="xcv80-lsva4737-2MHP-e-S",
            xclbin=self.vbin,
            expected_sha256=self.vbin_sha,
            environ={"PATH": "/usr/bin:/bin", "VRT_DEVICE_BDF": "0000:01:00.0"},
        )
        self.assertEqual(report["outcome"], "pass", report["blockers"])
        self.assertTrue(report["eligible_for_fpga_measured"])
        self.assertEqual(report["board"], "v80")
        self.assertEqual(report["driver"], "aved")
        self.assertIsNone(report["xilinx_xrt"])
        self.assertIsNone(report["xbutil_path"])
        self.assertEqual(report["vrt_device_bdf"], "0000:01:00.0")
        self.assertTrue(str(report["v80_preflight_script"]).endswith("ci/v80_preflight.sh"))

    def test_rejects_is_ready_false_boolean_and_string_case_insensitive(self):
        for ready_val in (False, "false", "FALSE", " False "):
            with self.subTest(is_ready=ready_val):
                self._mock_xbutil(payload=_make_xbutil_payload(is_ready=ready_val))
                report = harness.run_preflight(
                    target="hw",
                    requested_evidence="fpga_measured",
                    bdf=VALID_BDF,
                    platform=U55C_PLATFORM,
                    xclbin=self.xclbin,
                    environ=self.env,
                )
                self.assertEqual(report["outcome"], "blocked")
                self.assertFalse(report["eligible_for_fpga_measured"])
                self.assertTrue(any("is_ready=false" in b for b in report["blockers"]))

    def test_rejects_hw_emu_and_xrtsim_masquerading_as_fpga_measured(self):
        self._mock_xbutil()
        for bad_target in ("hw_emu", "xrtsim", "avedsim", "simx", "rtlsim", "sw_emu"):
            with self.subTest(target=bad_target):
                report = harness.run_preflight(
                    target=bad_target,
                    requested_evidence="fpga_measured",
                    bdf=VALID_BDF,
                    platform=U55C_PLATFORM,
                    xclbin=self.xclbin,
                    expected_sha256=self.xclbin_sha,
                    environ=self.env,
                )
                self.assertEqual(report["outcome"], "blocked")
                self.assertFalse(report["eligible_for_fpga_measured"])
                self.assertTrue(any("non-physical" in b for b in report["blockers"]))

    def test_rejects_when_xcl_emulation_mode_env_is_set(self):
        self._mock_xbutil()
        env = {**self.env, "XCL_EMULATION_MODE": "hw_emu"}
        report = harness.run_preflight(
            target="hw",
            requested_evidence="fpga_measured",
            bdf=VALID_BDF,
            platform=U55C_PLATFORM,
            xclbin=self.xclbin,
            environ=env,
        )
        self.assertEqual(report["outcome"], "blocked")
        self.assertFalse(report["eligible_for_fpga_measured"])
        self.assertTrue(any("XCL_EMULATION_MODE" in b for b in report["blockers"]))

    def test_rejects_emulated_device_identity_from_xbutil(self):
        self._mock_xbutil(payload=_make_xbutil_payload(vbnv="xilinx_u55c_hw_emu_shell"))
        report = harness.run_preflight(
            target="hw",
            requested_evidence="fpga_measured",
            bdf=VALID_BDF,
            platform=U55C_PLATFORM,
            xclbin=self.xclbin,
            environ=self.env,
        )
        self.assertEqual(report["outcome"], "blocked")
        self.assertFalse(report["eligible_for_fpga_measured"])
        self.assertTrue(any("non-physical" in b for b in report["blockers"]))

    def test_rejects_missing_xbutil_or_xilinx_xrt(self):
        self.stack.enter_context(mock.patch.object(harness.shutil, "which", return_value=None))
        report = harness.run_preflight(
            target="hw",
            requested_evidence="fpga_measured",
            bdf=VALID_BDF,
            platform=U55C_PLATFORM,
            xclbin=self.xclbin,
            environ={"PATH": "/usr/bin"},
        )
        self.assertEqual(report["outcome"], "blocked")
        self.assertFalse(report["eligible_for_fpga_measured"])
        self.assertTrue(any("XILINX_XRT" in b for b in report["blockers"]))
        self.assertTrue(any("xbutil" in b for b in report["blockers"]))

    def test_rejects_xclbin_sha256_mismatch_and_no_probe_fpga_measured(self):
        self._mock_xbutil()
        bad_digest = "0" * 64
        report = harness.run_preflight(
            target="hw",
            requested_evidence="fpga_measured",
            bdf=VALID_BDF,
            platform=U55C_PLATFORM,
            xclbin=self.xclbin,
            expected_sha256=bad_digest,
            environ=self.env,
        )
        self.assertEqual(report["outcome"], "blocked")
        self.assertTrue(any("SHA-256 mismatch" in b for b in report["blockers"]))

        no_probe_report = harness.run_preflight(
            target="hw",
            requested_evidence="fpga_measured",
            bdf=VALID_BDF,
            platform=U55C_PLATFORM,
            xclbin=self.xclbin,
            probe_device=False,
            environ=self.env,
        )
        self.assertEqual(no_probe_report["outcome"], "blocked")
        self.assertFalse(no_probe_report["eligible_for_fpga_measured"])


class PlanTests(unittest.TestCase):
    def test_emits_deterministic_u55c_execution_plan(self):
        plan_a = harness.build_execution_plan(
            board="u55c",
            bdf="3d:00.1",
            platform=None,
            build_dir="/work/build64-u55c",
            fpga_bin_dir="/work/xclbin/bin",
        )
        plan_b = harness.build_execution_plan(
            board="u55c",
            bdf=VALID_BDF,
            platform=U55C_PLATFORM,
            build_dir="/work/build64-u55c",
            fpga_bin_dir="/work/xclbin/bin",
        )
        self.assertEqual(plan_a, plan_b)
        self.assertEqual(plan_a["outcome"], "planned")
        self.assertFalse(plan_a["execution_performed"])
        self.assertEqual(plan_a["evidence_level"], "source_present")
        self.assertEqual(plan_a["target"], "hw")
        self.assertEqual(plan_a["driver"], "xrt")
        self.assertEqual(plan_a["board"]["capacity"]["lut"], 1_303_680)
        self.assertIn("XILINX_XRT", plan_a["environment_contract"])
        self.assertIn("FPGA_BIN_DIR", plan_a["environment_contract"])

        steps_by_id = {step["id"]: step for step in plan_a["steps"]}
        self.assertEqual(set(s["category"] for s in plan_a["steps"]), {
            "enumeration",
            "dma",
            "hbm_bank_boundary",
            "gemm_fp16",
            "gemm_bf16",
            "attention",
            "tiny_mlp",
            "soak",
        })

        attn = steps_by_id["attention-native"]
        self.assertIn("-DITYPE=fp16", attn["env"]["CONFIGS"])
        self.assertIn("-DOTYPE=fp32", attn["env"]["CONFIGS"])

        for step_id, expected_itype in (
            ("tiny-mlp-p04-fp16", "fp16"),
            ("tiny-mlp-p04-bf16", "bf16"),
        ):
            mlp = steps_by_id[step_id]
            self.assertIn("--app=ai_mlp_fused", mlp["argv"])
            self.assertIn("--profile=p02-tfr", mlp["argv"])
            self.assertIn(f"-DITYPE={expected_itype}", mlp["env"]["CONFIGS"])
            self.assertIn("-DOTYPE=fp32", mlp["env"]["CONFIGS"])
            self.assertIn("-DKUNROLL=1", mlp["env"]["CONFIGS"])
            self.assertIn("ai_mlp v1", mlp["notes"])

        soak_step = steps_by_id["physical-soak-3600s"]
        self.assertEqual(soak_step["duration_seconds"], 3600)
        self.assertIn("--driver=xrt", soak_step["argv"])
        self.assertIn("--target=hw", soak_step["argv"])

    def test_rejects_short_soak_or_non_physical_platform_in_plan(self):
        with self.assertRaises(ValueError):
            harness.build_execution_plan(
                board="u55c",
                bdf=VALID_BDF,
                platform=U55C_PLATFORM,
                build_dir="/work/build64",
                fpga_bin_dir="/work/bin",
                soak_seconds=3599,
            )
        with self.assertRaises(ValueError):
            harness.build_execution_plan(
                board="u55c",
                bdf=VALID_BDF,
                platform="xilinx_u55c_hw_emu",
                build_dir="/work/build64",
                fpga_bin_dir="/work/bin",
            )

    def test_v80_secondary_plan_uses_aved_and_v80_smi_without_xbutil_or_xilinx_xrt(self):
        plan = harness.build_execution_plan(
            board="v80",
            bdf="01:00.0",
            platform=None,
            build_dir="/work/build64-v80",
            fpga_bin_dir="/work/vbin",
        )
        self.assertEqual(plan["driver"], "aved")
        self.assertEqual(plan["target"], "hw")
        self.assertEqual(plan["board"]["part"], "xcv80-lsva4737-2MHP-e-S")
        self.assertEqual(plan["board"]["memory_type"], "HBM2e")
        self.assertIn("VRT_DEVICE_BDF", plan["environment_contract"])
        self.assertNotIn("XILINX_XRT", plan["environment_contract"])

        steps_by_id = {step["id"]: step for step in plan["steps"]}
        examine = steps_by_id["host-device-examine"]
        self.assertIn("v80-smi", " ".join(examine["argv"]))
        self.assertIn("ci/v80_preflight.sh", " ".join(examine["argv"]))
        self.assertNotIn("xbutil", " ".join(examine["argv"]))
        soak = steps_by_id["physical-soak-3600s"]
        self.assertEqual(soak["telemetry_cmd"], ["v80-smi", "list"])
        self.assertIn("--driver=aved", soak["argv"])


class SoakAnalyzerTests(unittest.TestCase):
    def test_clean_3600s_u55c_soak_passes(self):
        lines = _make_clean_soak_lines(duration_s=3605.0, include_sensors=True)
        result = harness.analyze_soak_jsonl(lines, expected_bdf=VALID_BDF)
        self.assertEqual(result["verdict"], "pass")
        self.assertEqual(result["evidence_level"], "fpga_measured")
        self.assertEqual(result["observed_drivers"], ["xrt"])
        self.assertGreaterEqual(result["duration_seconds"], 3600.0)
        self.assertEqual(result["counts"]["iterations_failed"], 0)
        self.assertEqual(result["counts"]["numerical_mismatches"], 0)
        self.assertEqual(result["counts"]["dma_errors"], 0)
        self.assertEqual(result["counts"]["reset_errors"], 0)
        self.assertEqual(result["telemetry"]["temp_c_status"], "measured")
        self.assertEqual(result["telemetry"]["power_w_status"], "measured")
        self.assertEqual(result["failures"], [])

    def test_clean_iso8601_timestamps_pass(self):
        lines = _make_clean_soak_lines(start_ts=1700000000.0, duration_s=3600.0, steps=2)
        iso_lines = []
        base_iso = ["2026-11-26T10:00:00Z", "2026-11-26T10:30:00Z", "2026-11-26T11:00:00Z"]
        for idx, raw in enumerate(lines):
            rec = json.loads(raw)
            rec["timestamp"] = base_iso[idx // 2]
            iso_lines.append(json.dumps(rec))
        result = harness.analyze_soak_jsonl(iso_lines, expected_bdf=VALID_BDF)
        self.assertEqual(result["verdict"], "pass")
        self.assertEqual(result["duration_seconds"], 3600.0)

    def test_unavailable_sensors_reported_explicitly_without_fabricating_watts(self):
        lines = _make_clean_soak_lines(duration_s=3600.0, include_sensors=False)
        result = harness.analyze_soak_jsonl(lines, expected_bdf=VALID_BDF)
        self.assertEqual(result["verdict"], "pass")
        self.assertIsNone(result["telemetry"]["temp_c_max"])
        self.assertEqual(result["telemetry"]["temp_c_status"], "unavailable")
        self.assertIsNone(result["telemetry"]["power_w_avg"])
        self.assertEqual(result["telemetry"]["power_w_status"], "unavailable")
        self.assertTrue(result["warnings"])

    def test_rejects_non_physical_or_missing_driver_in_iterations_and_telemetry(self):
        for bad_driver in ("simx", "rtlsim", "xrtsim", "foldsim"):
            with self.subTest(driver=bad_driver):
                lines = _make_clean_soak_lines(duration_s=3600.0, driver=bad_driver, telemetry_driver=bad_driver)
                result = harness.analyze_soak_jsonl(lines, expected_bdf=VALID_BDF)
                self.assertEqual(result["verdict"], "fail")
                self.assertEqual(result["evidence_level"], "unqualified")
                self.assertTrue(any("non-physical driver" in f for f in result["failures"]))

        missing_drv = _make_clean_soak_lines(duration_s=3600.0, driver=None, telemetry_driver=None)
        missing_res = harness.analyze_soak_jsonl(missing_drv, expected_bdf=VALID_BDF)
        self.assertEqual(missing_res["verdict"], "fail")
        self.assertTrue(any("missing `driver` field" in f for f in missing_res["failures"]))

        bad_telem_drv = _make_clean_soak_lines(duration_s=3600.0, driver="xrt", telemetry_driver="xrtsim")
        bad_telem_res = harness.analyze_soak_jsonl(bad_telem_drv, expected_bdf=VALID_BDF)
        self.assertEqual(bad_telem_res["verdict"], "fail")
        self.assertTrue(any("non-physical driver" in f for f in bad_telem_res["failures"]))

        bad_telem_tgt = _make_clean_soak_lines(duration_s=3600.0, driver="xrt", telemetry_target="hw_emu")
        bad_tgt_res = harness.analyze_soak_jsonl(bad_telem_tgt, expected_bdf=VALID_BDF)
        self.assertEqual(bad_tgt_res["verdict"], "fail")
        self.assertTrue(any("non-physical target" in f for f in bad_tgt_res["failures"]))

    def test_rejects_soak_under_3600_seconds(self):
        lines = _make_clean_soak_lines(duration_s=3599.0)
        result = harness.analyze_soak_jsonl(lines, expected_bdf=VALID_BDF)
        self.assertEqual(result["verdict"], "fail")
        self.assertEqual(result["evidence_level"], "unqualified")
        self.assertTrue(any("below required minimum" in f for f in result["failures"]))

    def test_rejects_non_zero_numerical_dma_reset_and_ecc_errors(self):
        for field in ("numerical_mismatches", "dma_errors", "reset_errors", "ecc_errors"):
            with self.subTest(field=field):
                lines = _make_clean_soak_lines(duration_s=3600.0)
                idx = 1 if field == "ecc_errors" else 0
                rec = json.loads(lines[idx])
                rec[field] = 1
                lines[idx] = json.dumps(rec)
                result = harness.analyze_soak_jsonl(lines, expected_bdf=VALID_BDF)
                self.assertEqual(result["verdict"], "fail")
                self.assertEqual(result["evidence_level"], "unqualified")
                self.assertTrue(result["failures"])

    def test_rejects_failed_iteration_and_bdf_mismatch(self):
        lines = _make_clean_soak_lines(duration_s=3600.0)
        rec = json.loads(lines[0])
        rec["status"] = "fail"
        rec["error"] = "kernel timeout"
        lines[0] = json.dumps(rec)
        result = harness.analyze_soak_jsonl(lines, expected_bdf=VALID_BDF)
        self.assertEqual(result["verdict"], "fail")
        self.assertEqual(result["counts"]["iterations_failed"], 1)

        mismatch_lines = _make_clean_soak_lines(duration_s=3600.0, bdf="0000:aa:00.0")
        mismatch_res = harness.analyze_soak_jsonl(mismatch_lines, expected_bdf=VALID_BDF)
        self.assertEqual(mismatch_res["verdict"], "fail")
        self.assertTrue(any("BDF mismatch" in f for f in mismatch_res["failures"]))

    def test_rejects_hw_emu_target_or_thermal_excursion_in_soak(self):
        emu_lines = _make_clean_soak_lines(duration_s=3600.0, target="hw_emu")
        emu_result = harness.analyze_soak_jsonl(emu_lines, expected_bdf=VALID_BDF)
        self.assertEqual(emu_result["verdict"], "fail")
        self.assertTrue(any("non-physical target" in f for f in emu_result["failures"]))

        hot_lines = _make_clean_soak_lines(duration_s=3600.0)
        rec = json.loads(hot_lines[1])
        rec["temp_c"] = 101.5
        hot_lines[1] = json.dumps(rec)
        hot_result = harness.analyze_soak_jsonl(hot_lines, expected_bdf=VALID_BDF)
        self.assertEqual(hot_result["verdict"], "fail")
        self.assertTrue(any("temperature" in f for f in hot_result["failures"]))

    def test_rejects_malformed_jsonl_and_timestamp_regression(self):
        lines = _make_clean_soak_lines(duration_s=3600.0)
        rec = json.loads(lines[-1])
        rec["timestamp"] = 1600000000.0
        lines[-1] = json.dumps(rec)
        lines.append("{not-json")
        result = harness.analyze_soak_jsonl(lines, expected_bdf=VALID_BDF)
        self.assertEqual(result["verdict"], "fail")
        self.assertTrue(any("timestamp regressed" in f for f in result["failures"]))
        self.assertTrue(any("malformed JSON" in f for f in result["failures"]))


class CliTests(unittest.TestCase):
    def test_cli_plan_and_soak_analyze_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            soak_file = Path(tmp) / "soak.jsonl"
            soak_file.write_text("\n".join(_make_clean_soak_lines(duration_s=3600.0)) + "\n", encoding="utf-8")

            out_plan = io.StringIO()
            with redirect_stdout(out_plan):
                code = harness.main([
                    "plan", "--board", "u55c", "--bdf", VALID_BDF,
                    "--build-dir", "/work/build64", "--fpga-bin-dir", "/work/bin",
                ])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out_plan.getvalue())["outcome"], "planned")

            out_soak = io.StringIO()
            with redirect_stdout(out_soak):
                code = harness.main(["soak-analyze", "--input", str(soak_file), "--bdf", VALID_BDF])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out_soak.getvalue())["verdict"], "pass")

    def test_cli_preflight_blocks_hw_emu_with_nonzero_exit(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = harness.main([
                "preflight", "--target", "hw_emu", "--bdf", VALID_BDF, "--platform", U55C_PLATFORM,
            ])
        self.assertEqual(code, 1)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["outcome"], "blocked")
        self.assertFalse(payload["eligible_for_fpga_measured"])

    def test_cli_soak_analyze_fails_on_missing_file_or_short_soak(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "absent.jsonl"
            out_missing = io.StringIO()
            with redirect_stdout(out_missing):
                code = harness.main(["soak-analyze", "--input", str(missing)])
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(out_missing.getvalue())["verdict"], "fail")

            short_file = Path(tmp) / "short.jsonl"
            short_file.write_text("\n".join(_make_clean_soak_lines(duration_s=60.0)) + "\n", encoding="utf-8")
            out_short = io.StringIO()
            with redirect_stdout(out_short):
                code = harness.main(["soak-analyze", "--input", str(short_file), "--bdf", VALID_BDF])
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(out_short.getvalue())["verdict"], "fail")


if __name__ == "__main__":
    unittest.main()
