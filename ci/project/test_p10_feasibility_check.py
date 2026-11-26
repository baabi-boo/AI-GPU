# SPDX-License-Identifier: Apache-2.0
"""Offline stdlib unit tests for ci/project/p10_feasibility_check.py."""

from __future__ import annotations

from contextlib import redirect_stdout
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

HERE = str(Path(__file__).resolve().parent)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import p10_feasibility_check as checker


def _make_fully_approved_package() -> dict:
    pkg = checker.build_template_package()
    pkg["phase_status"] = "complete"
    pkg["target_architecture"].update({
        "foundry_node": "Commercial 12nm FinFET",
        "memory_technology": "LPDDR5-6400 16 GiB",
        "host_interface": "PCIe Gen5 x8 Endpoint",
    })
    for idx, cat in enumerate(checker.REQUIRED_DEPENDENCY_CATEGORIES):
        pkg["dependencies"][cat] = {
            "status": "quoted",
            "owner": f"Lead Engineer {idx + 1}",
            "written_quote_ref": f"VENDOR-QUOTE-2026-{idx + 100}",
            "quoted_cost_usd": 250000.0 + idx * 10000.0,
        }
    for idx, plan_name in enumerate(checker.REQUIRED_SIGNOFF_PLANS):
        pkg["signoff_plans"][plan_name] = {
            "status": "approved",
            "uses_blackbox_sram": False,
            "uses_blackbox_phy": False,
            "uses_academic_pdk_as_signoff": False,
            "owner": f"Signoff Owner {idx + 1}",
            "criteria_summary": f"Foundry-qualified {plan_name} closure with compiled SRAM & PHY views.",
        }
    pkg["approval"] = {
        "go_approved": True,
        "human_approver": "Jane Doe",
        "approver_role": "VP Silicon Engineering",
        "approval_date": "2026-11-26",
        "funding_approved": True,
        "approved_budget_usd": 4500000.0,
        "foundry_partner": "Foundry Partner Corp",
        "osat_partner": "OSAT Assembly Inc",
        "procurement_authority": "CFO Signatory / PO-2026-001",
    }
    return pkg


class P10FeasibilityTemplateAndApprovalTests(unittest.TestCase):
    def test_unapproved_template_passes_as_preparatory_package(self):
        pkg = checker.build_template_package()
        result = checker.validate_feasibility_package(pkg)
        self.assertEqual(result["outcome"], "pass")
        self.assertFalse(result["go_approved"])
        self.assertEqual(result["errors"], [])
        self.assertTrue(result["warnings"])

    def test_fully_approved_package_with_quotes_and_non_blackbox_plans_passes(self):
        pkg = _make_fully_approved_package()
        result = checker.validate_feasibility_package(pkg)
        self.assertEqual(result["outcome"], "pass")
        self.assertTrue(result["go_approved"])
        self.assertEqual(result["errors"], [])

    def test_rejects_go_approved_without_human_approver_or_placeholder_approver(self):
        for bad_approver in (None, "", "   ", "TBD", "pending", "Unassigned", "replace_with_name"):
            with self.subTest(human_approver=bad_approver):
                pkg = _make_fully_approved_package()
                pkg["approval"]["human_approver"] = bad_approver
                result = checker.validate_feasibility_package(pkg)
                self.assertEqual(result["outcome"], "fail")
                self.assertTrue(any("human_approver" in e for e in result["errors"]))

    def test_rejects_agent_or_bot_approver_for_go_decision(self):
        for bot_name in ("Gemini Agent", "Claude Bot", "automated-ci", "LLM approver"):
            with self.subTest(human_approver=bot_name):
                pkg = _make_fully_approved_package()
                pkg["approval"]["human_approver"] = bot_name
                result = checker.validate_feasibility_package(pkg)
                self.assertEqual(result["outcome"], "fail")
                self.assertTrue(any("automated/agent" in e for e in result["errors"]))

    def test_rejects_go_approved_with_missing_or_invalid_approval_date(self):
        for bad_date in (None, "", "2026-13-45", "11/26/2026", "TBD"):
            with self.subTest(approval_date=bad_date):
                pkg = _make_fully_approved_package()
                pkg["approval"]["approval_date"] = bad_date
                result = checker.validate_feasibility_package(pkg)
                self.assertEqual(result["outcome"], "fail")
                self.assertTrue(any("approval_date" in e for e in result["errors"]))

    def test_rejects_go_approved_without_funding_budget_or_partners(self):
        cases = (
            ("funding_approved", False, "funding_approved"),
            ("approved_budget_usd", 0, "approved_budget_usd"),
            ("approved_budget_usd", -100.0, "approved_budget_usd"),
            ("approved_budget_usd", True, "approved_budget_usd"),
            ("foundry_partner", "TBD", "foundry_partner"),
            ("osat_partner", None, "osat_partner"),
            ("procurement_authority", "", "procurement_authority"),
        )
        for field, bad_val, expected_err in cases:
            with self.subTest(field=field, value=bad_val):
                pkg = _make_fully_approved_package()
                pkg["approval"][field] = bad_val
                result = checker.validate_feasibility_package(pkg)
                self.assertEqual(result["outcome"], "fail")
                self.assertTrue(any(expected_err in e for e in result["errors"]))

    def test_rejects_funding_approved_when_go_approved_is_false(self):
        pkg = checker.build_template_package()
        pkg["approval"]["funding_approved"] = True
        result = checker.validate_feasibility_package(pkg)
        self.assertEqual(result["outcome"], "fail")
        self.assertTrue(any("funding_approved cannot be true" in e for e in result["errors"]))

    def test_rejects_go_approved_when_phase_status_still_not_started(self):
        pkg = _make_fully_approved_package()
        pkg["phase_status"] = "not_started"
        result = checker.validate_feasibility_package(pkg)
        self.assertEqual(result["outcome"], "fail")
        self.assertTrue(any("not_started" in e for e in result["errors"]))

    def test_rejects_phase_status_complete_when_go_approved_is_false(self):
        pkg = checker.build_template_package()
        pkg["phase_status"] = "complete"
        pkg["approval"]["go_approved"] = False
        result = checker.validate_feasibility_package(pkg)
        self.assertEqual(result["outcome"], "fail")
        self.assertFalse(result["go_approved"])
        self.assertTrue(any("complete" in e and "go_approved=false" in e for e in result["errors"]))


class P10DependenciesAndSignoffTests(unittest.TestCase):
    def test_rejects_go_approved_if_any_dependency_lacks_written_quote_or_cost(self):
        for cat in checker.REQUIRED_DEPENDENCY_CATEGORIES:
            with self.subTest(category=cat, failure="unacquired"):
                pkg = _make_fully_approved_package()
                pkg["dependencies"][cat]["status"] = "UNACQUIRED / REQUIRES WRITTEN QUOTE"
                result = checker.validate_feasibility_package(pkg)
                self.assertEqual(result["outcome"], "fail")
                self.assertTrue(any(f"dependencies.{cat}.status" in e for e in result["errors"]))

            with self.subTest(category=cat, failure="missing_quote"):
                pkg = _make_fully_approved_package()
                pkg["dependencies"][cat]["written_quote_ref"] = None
                result = checker.validate_feasibility_package(pkg)
                self.assertEqual(result["outcome"], "fail")
                self.assertTrue(any(f"dependencies.{cat}.written_quote_ref" in e for e in result["errors"]))

            with self.subTest(category=cat, failure="zero_cost"):
                pkg = _make_fully_approved_package()
                pkg["dependencies"][cat]["quoted_cost_usd"] = 0.0
                result = checker.validate_feasibility_package(pkg)
                self.assertEqual(result["outcome"], "fail")
                self.assertTrue(any(f"dependencies.{cat}" in e for e in result["errors"]))

    def test_rejects_academic_pdk_quote_substitution_in_core_dependencies(self):
        for cat in ("foundry_pdk", "standard_cells_io", "sram_compiler"):
            with self.subTest(category=cat):
                pkg = _make_fully_approved_package()
                pkg["dependencies"][cat]["written_quote_ref"] = "free-asap7-sram_cost-stub"
                result = checker.validate_feasibility_package(pkg)
                self.assertEqual(result["outcome"], "fail")
                self.assertTrue(any("academic/black-box" in e for e in result["errors"]))

    def test_rejects_blackbox_sram_or_phy_or_academic_pdk_in_signoff_plans(self):
        for plan_name in checker.REQUIRED_SIGNOFF_PLANS:
            for flag in ("uses_blackbox_sram", "uses_blackbox_phy", "uses_academic_pdk_as_signoff"):
                with self.subTest(plan=plan_name, flag=flag):
                    pkg = _make_fully_approved_package()
                    pkg["signoff_plans"][plan_name][flag] = True
                    result = checker.validate_feasibility_package(pkg)
                    self.assertEqual(result["outcome"], "fail")
                    self.assertTrue(any(f"signoff_plans.{plan_name}.{flag}" in e for e in result["errors"]))

    def test_rejects_missing_signoff_plan_category(self):
        pkg = _make_fully_approved_package()
        del pkg["signoff_plans"]["dft_atpg_mbist_jtag"]
        result = checker.validate_feasibility_package(pkg)
        self.assertEqual(result["outcome"], "fail")
        self.assertTrue(any("dft_atpg_mbist_jtag" in e for e in result["errors"]))


class P10AcademicEstimateMasqueradeTests(unittest.TestCase):
    def test_rejects_asap7_or_yosys_estimate_masquerading_as_foundry_signoff(self):
        masquerade_cases = [
            {"pdk": "asap7", "flow": "yosys+opensta", "source_baseline": "ci/baselines/synthesis/yosys/tensor.json#tcu"},
            {"pdk": "nangate45", "flow": "yosys", "source_baseline": "custom"},
            {"pdk": "commercial", "flow": "opensta", "source_baseline": "asap7-run"},
            {"pdk": "predictive_7nm", "flow": "dc", "source_baseline": "sram_cost_stub"},
        ]
        for overrides in masquerade_cases:
            with self.subTest(overrides=overrides):
                pkg = checker.build_template_package()
                pkg["ppa_estimates"][0].update(overrides)
                pkg["ppa_estimates"][0]["is_estimate_only"] = False
                pkg["ppa_estimates"][0]["claimed_as_foundry_signoff"] = True
                pkg["ppa_estimates"][0]["uses_blackbox_sram"] = False
                pkg["ppa_estimates"][0]["includes_phy_io_pads"] = True
                result = checker.validate_feasibility_package(pkg)
                self.assertEqual(result["outcome"], "fail")
                self.assertTrue(any("cannot be claimed as foundry manufacturing sign-off" in e for e in result["errors"]))

    def test_rejects_blackbox_sram_or_missing_phy_pads_claimed_as_foundry_signoff(self):
        pkg = _make_fully_approved_package()
        pkg["ppa_estimates"] = [{
            "source_baseline": "commercial_12nm_dc_run",
            "pdk": "commercial_12nm",
            "flow": "synopsys_fc",
            "is_estimate_only": False,
            "claimed_as_foundry_signoff": True,
            "uses_blackbox_sram": True,
            "includes_phy_io_pads": False,
            "notes": "Commercial flow missing compiled SRAM and PHY pads.",
        }]
        result = checker.validate_feasibility_package(pkg)
        self.assertEqual(result["outcome"], "fail")
        self.assertTrue(any("black-box SRAM" in e for e in result["errors"]))
        self.assertTrue(any("omitting PHY/IO pads" in e for e in result["errors"]))

    def test_rejects_academic_estimate_missing_is_estimate_only_label(self):
        pkg = checker.build_template_package()
        pkg["ppa_estimates"][0]["is_estimate_only"] = False
        result = checker.validate_feasibility_package(pkg)
        self.assertEqual(result["outcome"], "fail")
        self.assertTrue(any("must explicitly set is_estimate_only=true" in e for e in result["errors"]))

    def test_rejects_non_rv64_or_non_tfr_architecture(self):
        for field, bad_val in (("xlen", 32), ("tcu_type", "DPI"), ("fpu_type", "DPI")):
            with self.subTest(field=field, value=bad_val):
                pkg = checker.build_template_package()
                pkg["target_architecture"][field] = bad_val
                result = checker.validate_feasibility_package(pkg)
                self.assertEqual(result["outcome"], "fail")
                self.assertTrue(any(f"target_architecture.{field}" in e for e in result["errors"]))


class P10CliTests(unittest.TestCase):
    def test_cli_emit_template_and_validate_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpl_path = Path(tmp) / "p10_template.json"
            out_buf = io.StringIO()
            with redirect_stdout(out_buf):
                rc_emit = checker.main(["emit-template", "--output", str(tmpl_path)])
            self.assertEqual(rc_emit, 0)
            self.assertTrue(tmpl_path.is_file())

            val_buf = io.StringIO()
            with redirect_stdout(val_buf):
                rc_val = checker.main(["validate", str(tmpl_path)])
            self.assertEqual(rc_val, 0)
            report = json.loads(val_buf.getvalue())
            self.assertEqual(report["outcome"], "pass")
            self.assertFalse(report["go_approved"])

    def test_cli_returns_nonzero_on_invalid_or_duplicate_key_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad_path = Path(tmp) / "dup.json"
            bad_path.write_text('{"schema_version": 1, "schema_version": 1}', encoding="utf-8")
            val_buf = io.StringIO()
            with redirect_stdout(val_buf):
                rc = checker.main(["validate", str(bad_path)])
            self.assertEqual(rc, 1)
            report = json.loads(val_buf.getvalue())
            self.assertEqual(report["outcome"], "fail")
            self.assertTrue(any("duplicate JSON key" in e for e in report["errors"]))


if __name__ == "__main__":
    unittest.main()
