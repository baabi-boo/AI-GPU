#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Comprehensive unit tests for ci/project/b2_wave_gates.py."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = str(Path(__file__).resolve().parent)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import b2_program_tracker as tracker  # noqa: E402
import b2_wave_gates as gates  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[2]


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def _init_temp_git_repo(root: Path, ledger_base: dict | None = None) -> tuple[str, dict]:
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test User")

    (root / "docs/project").mkdir(parents=True, exist_ok=True)
    (root / "hw/rtl").mkdir(parents=True, exist_ok=True)
    (root / "profiles").mkdir(parents=True, exist_ok=True)
    (root / "ci/project").mkdir(parents=True, exist_ok=True)

    (root / "README.md").write_text("# Test Repo\n", encoding="utf-8")
    (root / "hw/rtl/base.sv").write_text(
        "// SPDX-License-Identifier: Apache-2.0\nmodule base; endmodule\n",
        encoding="utf-8",
    )
    _git(root, "add", ".")
    _git(root, "commit", "-m", "base")
    base_sha = _git(root, "rev-parse", "HEAD")

    ledger = ledger_base or {
        "schema_version": 1,
        "adr": "ADR-007",
        "base_commit": base_sha,
        "target_min_production_loc": 500000,
        "evidence_boundary": {
            "foundry_signoff": False,
            "physical_gates_unwaived": True,
            "allowed_levels": ["source_present", "simulated", "rtl_verified", "open_source_synth_pnr_gds"],
            "forbidden_levels": ["fpga_measured", "silicon_measured"],
        },
        "waves": [
            {
                "id": "W13",
                "title": "Bootstrap",
                "pillar": "bootstrap",
                "status": "in_progress",
                "target_prod_loc": 500000,
                "target_test_loc": 2500,
                "owned_paths": ["profiles/", "ci/project/", "hw/rtl/b2/"],
                "required_gates": ["check_project_pass", "pro_independent_review"],
            }
        ],
    }
    (root / "docs/project/b2_program_ledger.json").write_text(
        json.dumps(ledger, indent=2), encoding="utf-8"
    )
    _git(root, "add", "docs/project/b2_program_ledger.json")
    _git(root, "commit", "-m", "add ledger")
    return base_sha, ledger


def _populate_pinned_files(root: Path) -> Path:
    for rel in gates.CORE_PINNED_SHA256:
        src = REPO_ROOT / rel
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
    presilicon_src = REPO_ROOT / "docs/project/presilicon_readiness.json"
    presilicon_data = json.loads(presilicon_src.read_text(encoding="utf-8"))
    for track in presilicon_data["tracks"]:
        for ev in track["evidence"]:
            rel = ev["path"]
            src = REPO_ROOT / rel
            dst = root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(src.read_bytes())
    presilicon_dst = root / "docs/project/presilicon_readiness.json"
    presilicon_dst.parent.mkdir(parents=True, exist_ok=True)
    presilicon_dst.write_bytes(presilicon_src.read_bytes())
    return presilicon_dst


class TestPrecommitLocAndAntiBloat(unittest.TestCase):
    def test_precommit_loc_counts_committed_staged_unstaged_and_untracked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, ledger = _init_temp_git_repo(root)

            # Committed production file
            (root / "profiles/aigpu-b2.json").write_text('{\n  "cores": 128\n}\n', encoding="utf-8")
            _git(root, "add", "profiles/aigpu-b2.json")
            _git(root, "commit", "-m", "commit profile")

            # Staged production file
            (root / "hw/rtl/tcu_v2.sv").write_text(
                "// SPDX-License-Identifier: Apache-2.0\n"
                "module tcu_v2;\n"
                "  logic a;\n"
                "  assign a = 1'b0;\n"
                "endmodule\n",
                encoding="utf-8",
            )
            _git(root, "add", "hw/rtl/tcu_v2.sv")

            # Unstaged modification to committed file
            (root / "profiles/aigpu-b2.json").write_text(
                '{\n  "cores": 128,\n  "tmem_kib": 256\n}\n', encoding="utf-8"
            )

            # Untracked test file and untracked production file
            (root / "ci/project/test_sample.py").write_text(
                "# SPDX-License-Identifier: Apache-2.0\n"
                "def test_ok():\n"
                "    assert 1 == 1\n",
                encoding="utf-8",
            )
            (root / "ci/project/helper_tool.py").write_text(
                "# SPDX-License-Identifier: Apache-2.0\n"
                "def run_check(x):\n"
                "    return x + 1\n",
                encoding="utf-8",
            )

            preview = gates.compute_precommit_loc_preview(root, ledger)
            self.assertEqual(preview["committed_production_loc"], 3)
            self.assertEqual(preview["working_tree_production_delta"], 7)
            self.assertEqual(preview["net_production_loc"], 10)
            self.assertEqual(preview["production_loc_by_bucket"]["rtl_silicon"], 4)
            self.assertEqual(preview["production_loc_by_bucket"]["bootstrap"], 6)
            self.assertEqual(preview["net_verification_test_loc"], 2)
            self.assertEqual(preview["anti_bloat_warnings"], [])
            self.assertEqual(preview["accidental_exclusions"], [])

    def test_precommit_flags_anti_bloat_and_accidental_exclusion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, ledger = _init_temp_git_repo(root)

            # Bloated file (>=200 lines repetitive)
            (root / "sw/libs/aigpu_blas").mkdir(parents=True, exist_ok=True)
            (root / "sw/libs/aigpu_blas/padded.cpp").write_text(
                "int acc = acc + 1;\n" * 240, encoding="utf-8"
            )
            # Accidental exclusion: .sh script inside sw/libs/
            (root / "sw/libs/aigpu_blas/build_helper.sh").write_text(
                "#!/bin/bash\necho hi\n", encoding="utf-8"
            )
            # Accidental exclusion: .json file outside profiles/
            (root / "ci/project/misplaced_data.json").write_text('{"a": 1}\n', encoding="utf-8")

            preview = gates.compute_precommit_loc_preview(root, ledger)
            self.assertTrue(preview["anti_bloat_warnings"])
            excluded_paths = {item["path"] for item in preview["accidental_exclusions"]}
            self.assertIn("sw/libs/aigpu_blas/build_helper.sh", excluded_paths)
            self.assertIn("ci/project/misplaced_data.json", excluded_paths)

    def test_precommit_detects_frozen_path_edit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, ledger = _init_temp_git_repo(root)
            (root / "python/vortex_ai").mkdir(parents=True, exist_ok=True)
            (root / "python/vortex_ai/__init__.py").write_text("# modified\n", encoding="utf-8")

            preview = gates.compute_precommit_loc_preview(root, ledger)
            self.assertIn("python/vortex_ai/__init__.py", preview["frozen_path_violations"])


class TestFrozenAndSha256DriftGuard(unittest.TestCase):
    def test_live_repo_frozen_guard_passes_cleanly(self):
        report = gates.check_frozen_and_sha256_drift(REPO_ROOT)
        self.assertTrue(report["ok"], report["violations"])
        self.assertEqual(report["presilicon_artifact_count"], 17)
        self.assertGreaterEqual(report["verified_count"], 30)
        self.assertEqual(report["violation_count"], 0)

    def test_drift_detected_on_pinned_file_and_unexpected_vortex_ai_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            presilicon_dst = _populate_pinned_files(root)
            ok_report = gates.check_frozen_and_sha256_drift(root, presilicon_dst)
            self.assertTrue(ok_report["ok"], ok_report["violations"])

            # Mutate VX_config.toml
            cfg = root / "VX_config.toml"
            cfg.write_bytes(cfg.read_bytes() + b"\n# drift\n")
            # Mutate a presilicon artifact
            b1 = root / "profiles/aigpu-b1.json"
            b1.write_bytes(b1.read_bytes() + b" ")
            # Drop an unexpected file into python/vortex_ai/
            (root / "python/vortex_ai/rogue.py").write_text("x = 1\n", encoding="utf-8")

            bad_report = gates.check_frozen_and_sha256_drift(root, presilicon_dst)
            self.assertFalse(bad_report["ok"])
            reasons = {v["path"]: v["reason"] for v in bad_report["violations"]}
            self.assertEqual(reasons.get("VX_config.toml"), "sha256_drift")
            self.assertEqual(reasons.get("profiles/aigpu-b1.json"), "sha256_drift")
            self.assertEqual(reasons.get("python/vortex_ai/rogue.py"), "unexpected_file_in_frozen_dir")


class TestCleanIpScanner(unittest.TestCase):
    def test_live_repo_clean_ip_baseline_passes(self):
        report = gates.scan_clean_ip_files(REPO_ROOT, allow_legacy_apache=True)
        self.assertTrue(report["ok"], report["violations"][:5])
        self.assertGreater(report["scanned_files"], 400)

    def test_clean_ip_flags_missing_spdx_and_forbidden_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "hw/rtl/b2").mkdir(parents=True, exist_ok=True)
            (root / "hw/asic/b2").mkdir(parents=True, exist_ok=True)
            (root / "hw/dv/b2").mkdir(parents=True, exist_ok=True)

            good = root / "hw/rtl/b2/good.sv"
            good.write_text(
                "// SPDX-License-Identifier: Apache-2.0\nmodule good; endmodule\n",
                encoding="utf-8",
            )
            no_spdx = root / "hw/rtl/b2/missing_header.sv"
            no_spdx.write_text("module missing_header; endmodule\n", encoding="utf-8")

            tainted = root / "hw/asic/b2/bad_ip.sv"
            tainted.write_text(
                "// SPDX-License-Identifier: Apache-2.0\n"
                "// Micron proprietary and confidential under NDA\n"
                "// GPLv3 pragma protect\n"
                "module bad_ip; endmodule\n",
                encoding="utf-8",
            )
            xci = root / "hw/dv/b2/ip_core.xci"
            xci.write_text("<xml/>", encoding="utf-8")

            res_good = gates.scan_clean_ip_files(root, paths=["hw/rtl/b2/good.sv"])
            self.assertTrue(res_good["ok"], res_good["violations"])

            res_all = gates.scan_clean_ip_files(root)
            self.assertFalse(res_all["ok"])
            rules = {(v["path"], v["rule"]) for v in res_all["violations"]}
            self.assertIn(("hw/rtl/b2/missing_header.sv", "missing_spdx_apache2"), rules)
            self.assertIn(("hw/asic/b2/bad_ip.sv", "forbidden_content:micron_vendor"), rules)
            self.assertIn(("hw/asic/b2/bad_ip.sv", "forbidden_content:nda_restricted"), rules)
            self.assertIn(("hw/asic/b2/bad_ip.sv", "forbidden_content:gpl_license"), rules)
            self.assertIn(("hw/asic/b2/bad_ip.sv", "forbidden_content:ieee_1735_protect"), rules)
            self.assertIn(("hw/dv/b2/ip_core.xci", "forbidden_extension"), rules)


class TestParityAndWaveEvidence(unittest.TestCase):
    def test_simx_rtl_parity_enforces_exact_instrs_and_5pct_cycles(self):
        ok = gates.evaluate_simx_rtl_parity([
            {"workload": "gemm_fp16", "simx_instrs": 10000, "rtl_instrs": 10000, "simx_cycles": 4080, "rtl_cycles": 4000},
            {"workload": "dxa_copy", "simx_instrs": 2500, "rtl_instrs": 2500, "simx_cycles": 1000, "rtl_cycles": 1000},
        ])
        self.assertTrue(ok["ok"])
        self.assertEqual(ok["passed_cases"], 2)

        bad_instr = gates.evaluate_simx_rtl_parity([
            {"workload": "gemm_fp16", "simx_instrs": 9999, "rtl_instrs": 10000, "simx_cycles": 4000, "rtl_cycles": 4000},
        ])
        self.assertFalse(bad_instr["ok"])
        self.assertTrue(any("instruction mismatch" in f for f in bad_instr["failures"]))

        bad_cycles = gates.evaluate_simx_rtl_parity([
            {"workload": "gemm_fp16", "simx_instrs": 10000, "rtl_instrs": 10000, "simx_cycles": 4300, "rtl_cycles": 4000},
        ])
        self.assertFalse(bad_cycles["ok"])
        self.assertTrue(any("exceeds 5.00%" in f for f in bad_cycles["failures"]))

    def test_wave_evidence_builder_and_honesty_rejections(self):
        ledger = json.loads((REPO_ROOT / "docs/project/b2_program_ledger.json").read_text(encoding="utf-8"))
        req_gates = {g: {"outcome": "pass"} for g in ledger["waves"][0]["required_gates"]}
        ev = gates.build_wave_evidence(
            "W13",
            status="complete",
            evidence_level="simulated",
            gates=req_gates,
            loc_metrics={"net_production_loc": 5100},
            reviewer="pro-reviewer",
            source_commit="abc1234",
            ledger=ledger,
        )
        self.assertEqual(gates.validate_wave_evidence(ev, ledger=ledger), [])
        self.assertIs(ev["foundry_signoff"], False)
        self.assertIs(ev["fpga_measured"], False)
        self.assertIs(ev["silicon_measured"], False)
        self.assertIs(ev["physical_gates_unwaived"], True)

        # Reject fpga_measured / silicon_measured / foundry_signoff=True / unwaived=False
        for field, bad_val in (
            ("foundry_signoff", True),
            ("fpga_measured", True),
            ("silicon_measured", True),
            ("physical_gates_unwaived", False),
            ("evidence_level", "fpga_measured"),
            ("evidence_level", "silicon_measured"),
        ):
            mutated = json.loads(json.dumps(ev))
            mutated[field] = bad_val
            errs = gates.validate_wave_evidence(mutated, ledger=ledger)
            self.assertTrue(errs, f"Expected rejection for {field}={bad_val!r}")


class TestPrTableAndCli(unittest.TestCase):
    def test_pr_table_rendering_and_cli_json_modes(self):
        ledger = json.loads((REPO_ROOT / "docs/project/b2_program_ledger.json").read_text(encoding="utf-8"))
        metrics = tracker.compute_program_metrics(REPO_ROOT, ledger)
        md = gates.render_pr_progress_table(ledger, metrics)
        self.assertIn("| `W13` | `bootstrap` |", md)
        self.assertIn("| `W32` | `qualification_dataroom` |", md)
        self.assertIn("foundry_signoff=false", md)

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = gates.main(["--check-frozen", "--json"])
        self.assertEqual(rc, 0)
        parsed = json.loads(buf.getvalue())
        self.assertTrue(parsed["ok"])

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ev_path = tmp_path / "ev.json"
            req_gates = {g: {"outcome": "pass"} for g in ledger["waves"][0]["required_gates"]}
            ev = gates.build_wave_evidence(
                "W13",
                status="complete",
                evidence_level="simulated",
                gates=req_gates,
                ledger=ledger,
            )
            ev_path.write_text(json.dumps(ev), encoding="utf-8")

            parity_path = tmp_path / "parity.json"
            parity_path.write_text(json.dumps([
                {"workload": "demo", "simx_instrs": 500, "rtl_instrs": 500, "simx_cycles": 1020, "rtl_cycles": 1000}
            ]), encoding="utf-8")

            buf_ev = io.StringIO()
            with redirect_stdout(buf_ev):
                self.assertEqual(gates.main(["--validate-evidence", str(ev_path), "--json"]), 0)
            self.assertTrue(json.loads(buf_ev.getvalue())["ok"])

            buf_par = io.StringIO()
            with redirect_stdout(buf_par):
                self.assertEqual(gates.main(["--check-parity", str(parity_path), "--json"]), 0)
            self.assertTrue(json.loads(buf_par.getvalue())["ok"])

            # Verify invalid parity JSON fails with rc=1
            bad_parity_path = tmp_path / "bad_parity.json"
            bad_parity_path.write_text(json.dumps([
                {"workload": "demo", "simx_instrs": 500, "rtl_instrs": 501, "simx_cycles": 1000, "rtl_cycles": 1000}
            ]), encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(gates.main(["--check-parity", str(bad_parity_path)]), 1)

    def test_cli_conflicting_modes_exit_2(self):
        for argv in (
            ["--precommit-audit", "--check-frozen"],
            ["--check-frozen", "--render-pr-table"],
            ["--check-clean-ip", "--precommit-audit"],
        ):
            with redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as ctx:
                    gates.main(argv)
            self.assertEqual(ctx.exception.code, 2, f"Expected exit 2 for {argv}")


class TestWaveOwnershipAndEdgeCases(unittest.TestCase):
    def test_strict_wave_ownership_flags_paths_outside_declared_prefixes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, ledger = _init_temp_git_repo(root)
            presilicon_dst = _populate_pinned_files(root)
            _git(root, "add", ".")
            _git(root, "commit", "-m", "pinned baseline")
            ledger["base_commit"] = _git(root, "rev-parse", "HEAD")
            (root / "docs/project/b2_program_ledger.json").write_text(
                json.dumps(ledger, indent=2), encoding="utf-8"
            )
            _git(root, "add", "docs/project/b2_program_ledger.json")
            _git(root, "commit", "-m", "update base")
            ledger["base_commit"] = _git(root, "rev-parse", "HEAD")
            (root / "docs/project/b2_program_ledger.json").write_text(
                json.dumps(ledger, indent=2), encoding="utf-8"
            )
            _git(root, "add", "docs/project/b2_program_ledger.json")
            _git(root, "commit", "-m", "pin base to itself")

            # File outside the fixture wave's declared owned_paths
            (root / "sw/libs/aigpu_blas").mkdir(parents=True, exist_ok=True)
            (root / "sw/libs/aigpu_blas/gemm.cpp").write_text(
                "// SPDX-License-Identifier: Apache-2.0\nint gemm_entry() { return 0; }\n",
                encoding="utf-8",
            )
            audit_warn = gates.run_precommit_audit(
                root,
                root / "docs/project/b2_program_ledger.json",
                presilicon_dst,
                wave_id="W13",
                strict_wave_ownership=False,
            )
            self.assertIn("sw/libs/aigpu_blas/gemm.cpp", audit_warn["ownership_warnings"])
            self.assertTrue(audit_warn["ok"], audit_warn["errors"])

            audit_strict = gates.run_precommit_audit(
                root,
                root / "docs/project/b2_program_ledger.json",
                presilicon_dst,
                wave_id="W13",
                strict_wave_ownership=True,
            )
            self.assertFalse(audit_strict["ok"])
            self.assertTrue(any("outside declared owned_paths" in e for e in audit_strict["errors"]))

    def test_strict_wave_ownership_exempts_ledger_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, ledger = _init_temp_git_repo(root)
            presilicon_dst = _populate_pinned_files(root)
            _git(root, "add", ".")
            _git(root, "commit", "-m", "pinned baseline")
            ledger["base_commit"] = _git(root, "rev-parse", "HEAD")
            (root / "docs/project/b2_program_ledger.json").write_text(
                json.dumps(ledger, indent=2), encoding="utf-8"
            )
            _git(root, "add", "docs/project/b2_program_ledger.json")
            _git(root, "commit", "-m", "pin base")

            # Uncommitted edit to b2_program_ledger.json plus an owned file must pass strict ownership
            ledger["waves"][0]["title"] = "Updated Bootstrap"
            (root / "docs/project/b2_program_ledger.json").write_text(
                json.dumps(ledger, indent=2), encoding="utf-8"
            )
            (root / "ci/project/owned_helper.py").write_text(
                "# SPDX-License-Identifier: Apache-2.0\ndef helper():\n    return 1\n",
                encoding="utf-8",
            )
            audit_strict = gates.run_precommit_audit(
                root,
                root / "docs/project/b2_program_ledger.json",
                presilicon_dst,
                wave_id="W13",
                strict_wave_ownership=True,
            )
            self.assertTrue(audit_strict["ok"], audit_strict["errors"])
            self.assertEqual(audit_strict["ownership_warnings"], [])

    def test_wave_evidence_rejects_nested_forbidden_level_and_incomplete_gates(self):
        ledger = json.loads((REPO_ROOT / "docs/project/b2_program_ledger.json").read_text(encoding="utf-8"))
        req_gates = {g: {"outcome": "pass"} for g in ledger["waves"][0]["required_gates"]}
        ev = gates.build_wave_evidence(
            "W13",
            status="complete",
            evidence_level="rtl_verified",
            gates=req_gates,
            parity_summary={"ok": True, "passed_cases": 2, "total_cases": 2},
            ledger=ledger,
        )
        # Nested forbidden string inside gates detail must be rejected
        ev_nested = json.loads(json.dumps(ev))
        ev_nested["gates"]["check_project_pass"]["claim"] = "silicon_measured"
        errs_nested = gates.validate_wave_evidence(ev_nested, ledger=ledger)
        self.assertTrue(any("silicon_measured" in e for e in errs_nested))

        # Complete wave missing a required gate or having a failing gate must be rejected
        ev_missing_gate = json.loads(json.dumps(ev))
        del ev_missing_gate["gates"]["pro_independent_review"]
        errs_missing = gates.validate_wave_evidence(ev_missing_gate, ledger=ledger)
        self.assertTrue(any("pro_independent_review" in e for e in errs_missing))

        ev_fail_gate = json.loads(json.dumps(ev))
        ev_fail_gate["gates"]["check_project_pass"]["outcome"] = "fail"
        errs_fail = gates.validate_wave_evidence(ev_fail_gate, ledger=ledger)
        self.assertTrue(any("outcome='pass'" in e for e in errs_fail))

    def test_parity_validator_rejects_invalid_inputs_and_zero_cycles(self):
        with self.assertRaises(ValueError):
            gates.evaluate_simx_rtl_parity([])
        with self.assertRaises(ValueError):
            gates.evaluate_simx_rtl_parity(
                [{"workload": "x", "simx_instrs": 1, "rtl_instrs": 1, "simx_cycles": 1, "rtl_cycles": 1}],
                max_cycle_delta_pct=-0.1,
            )
        zero_rtl = gates.evaluate_simx_rtl_parity([
            {"workload": "zero", "simx_instrs": 10, "rtl_instrs": 10, "simx_cycles": 0, "rtl_cycles": 0}
        ])
        self.assertFalse(zero_rtl["ok"])
        self.assertTrue(any("rtl_cycles must be > 0" in f for f in zero_rtl["failures"]))

        bool_count = gates.evaluate_simx_rtl_parity([
            {"workload": "bool", "simx_instrs": True, "rtl_instrs": 1, "simx_cycles": 10, "rtl_cycles": 10}
        ])
        self.assertFalse(bool_count["ok"])

    def test_clean_ip_detects_all_rights_reserved_and_third_party_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad_dir = root / "hw/rtl/third_party_ip"
            bad_dir.mkdir(parents=True, exist_ok=True)
            f_path = bad_dir / "vendor_block.sv"
            f_path.write_text(
                "// SPDX-License-Identifier: Apache-2.0\n"
                "module vendor_block; endmodule\n",
                encoding="utf-8",
            )

            clean_dir = root / "hw/rtl/b2"
            clean_dir.mkdir(parents=True, exist_ok=True)
            f_arr = clean_dir / "unclassified_arr.sv"
            f_arr.write_text(
                "// Copyright 2026 Vendor Corp. All rights reserved.\n"
                "module unclassified_arr; endmodule\n",
                encoding="utf-8",
            )

            res = gates.scan_clean_ip_files(root)
            self.assertFalse(res["ok"])
            by_path = {(v["path"], v["rule"]) for v in res["violations"]}
            self.assertIn(("hw/rtl/third_party_ip/vendor_block.sv", "forbidden_path_token"), by_path)
            self.assertIn(
                ("hw/rtl/b2/unclassified_arr.sv", "forbidden_content:unclassified_all_rights_reserved"),
                by_path,
            )
            self.assertIn(("hw/rtl/b2/unclassified_arr.sv", "missing_spdx_apache2"), by_path)


if __name__ == "__main__":
    unittest.main()
