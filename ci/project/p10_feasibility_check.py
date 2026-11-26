#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Machine-checkable validator for P10 ASIC feasibility packages.

This tool enforces strict P10 governance and sign-off boundaries:
  1. Academic ASAP7 / Yosys / OpenSTA / NanGate45 / black-box SRAM estimates
     may NEVER masquerade as foundry manufacturing sign-off.
  2. NO feasibility package may set `go_approved=true` without:
     - a non-empty, non-placeholder human approver + valid ISO date + explicit
       funding/procurement authorization;
     - written foundry/PDK, SRAM macro compiler, PCIe, memory controller/PHY,
       package/OSAT, and commercial EDA tool-license quotes;
     - non-black-box compiled-SRAM and PHY physical-design, DFT/MBIST, MCMM STA,
       power-integrity (IR drop/EM), and formal/functional sign-off plans.
  3. Unapproved preparatory packages (`go_approved=false`) are valid ONLY when
     estimates are explicitly labeled as non-sign-off academic/pre-layout
     estimates and phase readiness stays unapproved.

Offline validation of a feasibility JSON package establishes structural
compliance only; it never authorizes spending, IP licensing, or tapeout.
"""

from __future__ import annotations

import argparse
from datetime import date
import json
import math
from pathlib import Path
import re
import sys
from typing import Any


SCHEMA_VERSION = 1

REQUIRED_DEPENDENCY_CATEGORIES = (
    "foundry_pdk",
    "standard_cells_io",
    "sram_compiler",
    "clock_reset_ip",
    "pcie_controller_phy",
    "memory_controller_phy",
    "package_osat",
    "eda_licenses",
)

REQUIRED_SIGNOFF_PLANS = (
    "functional_formal_cdc",
    "dft_atpg_mbist_jtag",
    "physical_drc_lvs",
    "mcmm_sta",
    "power_integrity_em",
)

PLACEHOLDER_STRINGS = frozenset({
    "",
    "tbd",
    "todo",
    "pending",
    "none",
    "n/a",
    "na",
    "unknown",
    "unassigned",
    "unselected",
    "unapproved",
    "undecided",
    "placeholder",
})

AGENT_APPROVER_MARKERS = (
    "agent",
    "bot",
    "llm",
    "claude",
    "gemini",
    "gpt",
    "copilot",
    "automated",
    "auto-approved",
)

ACADEMIC_NON_SIGNOFF_TOKENS = (
    "asap7",
    "nangate45",
    "nangate15",
    "yosys",
    "opensta",
    "openroad",
    "predictive",
    "academic",
    "sram_cost",
    "vx_sp_ram_asic",
    "vx_dp_ram_asic",
    "black-box",
    "blackbox",
)

ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: {message}\n")


def _nonempty_real_text(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    if not stripped:
        return False
    lowered = stripped.lower()
    if lowered in PLACEHOLDER_STRINGS:
        return False
    if "replace_with" in lowered or "example.invalid" in lowered:
        return False
    return True


def _is_positive_finite(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0.0
    )


def _valid_iso_date(value: Any) -> bool:
    if not isinstance(value, str) or not ISO_DATE_RE.fullmatch(value.strip()):
        return False
    try:
        date.fromisoformat(value.strip())
    except ValueError:
        return False
    return True


def _looks_academic_or_blackbox(text: str) -> list[str]:
    lowered = text.lower()
    return [tok for tok in ACADEMIC_NON_SIGNOFF_TOKENS if tok in lowered]


def _read_json_strict(path: Path) -> dict[str, Any]:
    def _reject_dup(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, v in pairs:
            if k in out:
                raise ValueError(f"duplicate JSON key {k!r}")
            out[k] = v
        return out

    def _reject_const(val: str) -> None:
        raise ValueError(f"non-finite JSON constant {val!r}")

    raw = path.read_text(encoding="utf-8")
    parsed = json.loads(raw, object_pairs_hook=_reject_dup, parse_constant=_reject_const)
    if not isinstance(parsed, dict):
        raise ValueError("feasibility package root must be a JSON object")
    return parsed


def build_template_package() -> dict[str, Any]:
    """Return a canonical unapproved P10 preparatory package template."""
    return {
        "schema_version": SCHEMA_VERSION,
        "package_id": "p10-bounded-inference-asic-template",
        "phase_status": "not_started",
        "evidence_level": "source_present",
        "target_architecture": {
            "base_profile": "p02-tfr",
            "xlen": 64,
            "core_count_range": "2-4",
            "l2_cache_enabled": True,
            "tcu_type": "TFR",
            "fpu_type": "STD",
            "foundry_node": "UNDECIDED",
            "memory_technology": "UNDECIDED",
            "host_interface": "UNDECIDED",
        },
        "ppa_estimates": [
            {
                "source_baseline": "ci/baselines/synthesis/yosys/tensor.json#tcu",
                "pdk": "asap7",
                "flow": "yosys+opensta",
                "is_estimate_only": True,
                "claimed_as_foundry_signoff": False,
                "uses_blackbox_sram": True,
                "includes_phy_io_pads": False,
                "notes": "Academic ASAP7 pre-layout estimate without SRAM macros, PHY/IO pads, or foundry sign-off.",
            },
            {
                "source_baseline": "ci/baselines/synthesis/yosys/tensor.json#tensor",
                "pdk": "asap7",
                "flow": "yosys+opensta",
                "is_estimate_only": True,
                "claimed_as_foundry_signoff": False,
                "uses_blackbox_sram": True,
                "includes_phy_io_pads": False,
                "notes": "Academic ASAP7 pre-layout estimate with sram_cost.py black-box SRAM heuristic.",
            },
            {
                "source_baseline": "ci/baselines/synthesis/yosys/core.json#core",
                "pdk": "asap7",
                "flow": "yosys+opensta",
                "is_estimate_only": True,
                "claimed_as_foundry_signoff": False,
                "uses_blackbox_sram": True,
                "includes_phy_io_pads": False,
                "notes": "Academic ASAP7 pre-layout estimate with sram_cost.py black-box SRAM heuristic.",
            },
        ],
        "dependencies": {
            cat: {
                "status": "UNACQUIRED / REQUIRES WRITTEN QUOTE",
                "owner": "UNASSIGNED",
                "written_quote_ref": None,
                "quoted_cost_usd": None,
            }
            for cat in REQUIRED_DEPENDENCY_CATEGORIES
        },
        "signoff_plans": {
            plan: {
                "status": "planned",
                "uses_blackbox_sram": False,
                "uses_blackbox_phy": False,
                "uses_academic_pdk_as_signoff": False,
                "owner": "UNASSIGNED",
                "criteria_summary": f"Full foundry-qualified {plan} sign-off required before tapeout.",
            }
            for plan in REQUIRED_SIGNOFF_PLANS
        },
        "approval": {
            "go_approved": False,
            "human_approver": None,
            "approver_role": None,
            "approval_date": None,
            "funding_approved": False,
            "approved_budget_usd": None,
            "foundry_partner": None,
            "osat_partner": None,
            "procurement_authority": None,
        },
    }


def validate_feasibility_package(package: dict[str, Any]) -> dict[str, Any]:
    """Validate a P10 ASIC feasibility package and enforce Go/No-Go invariants."""
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(package, dict):
        return {
            "schema_version": SCHEMA_VERSION,
            "tool": "p10_feasibility_check.validate",
            "outcome": "fail",
            "go_approved": False,
            "errors": ["package must be a JSON object"],
            "warnings": [],
        }

    if type(package.get("schema_version")) is not int or package["schema_version"] != SCHEMA_VERSION:
        errors.append(f"schema_version must be integer {SCHEMA_VERSION}")

    if not _nonempty_real_text(package.get("package_id")):
        errors.append("package_id must be a non-empty non-placeholder string")

    phase_status = package.get("phase_status")
    if phase_status not in ("not_started", "in_progress", "blocked", "complete"):
        errors.append(f"unsupported phase_status {phase_status!r}")

    evidence_level = package.get("evidence_level")
    if evidence_level != "source_present":
        errors.append(
            f"P10 feasibility packages must have evidence_level='source_present', got {evidence_level!r}"
        )

    # Target architecture check
    arch = package.get("target_architecture")
    if not isinstance(arch, dict):
        errors.append("target_architecture must be an object")
    else:
        if arch.get("xlen") != 64:
            errors.append(f"target_architecture.xlen must be 64 (RV64 p02-tfr baseline), got {arch.get('xlen')!r}")
        if arch.get("tcu_type") != "TFR":
            errors.append(f"target_architecture.tcu_type must be 'TFR', got {arch.get('tcu_type')!r}")
        if arch.get("fpu_type") != "STD":
            errors.append(f"target_architecture.fpu_type must be 'STD', got {arch.get('fpu_type')!r}")

    # 1. PPA Estimates: unconditionally reject academic ASAP7 / black-box SRAM masquerading as foundry sign-off
    ppa = package.get("ppa_estimates")
    if not isinstance(ppa, list) or not ppa:
        errors.append("ppa_estimates must be a non-empty list")
        ppa = []
    for idx, entry in enumerate(ppa):
        ctx = f"ppa_estimates[{idx}]"
        if not isinstance(entry, dict):
            errors.append(f"{ctx} must be an object")
            continue
        pdk = str(entry.get("pdk", ""))
        flow = str(entry.get("flow", ""))
        notes = str(entry.get("notes", ""))
        baseline = str(entry.get("source_baseline", ""))
        combined_text = " ".join((pdk, flow, notes, baseline))
        academic_hits = _looks_academic_or_blackbox(combined_text)

        claimed_signoff = entry.get("claimed_as_foundry_signoff")
        is_estimate_only = entry.get("is_estimate_only")
        uses_blackbox_sram = entry.get("uses_blackbox_sram")
        includes_phy_io_pads = entry.get("includes_phy_io_pads")

        if type(claimed_signoff) is not bool:
            errors.append(f"{ctx}.claimed_as_foundry_signoff must be a boolean")
        if type(is_estimate_only) is not bool:
            errors.append(f"{ctx}.is_estimate_only must be a boolean")
        if type(uses_blackbox_sram) is not bool:
            errors.append(f"{ctx}.uses_blackbox_sram must be a boolean")
        if type(includes_phy_io_pads) is not bool:
            errors.append(f"{ctx}.includes_phy_io_pads must be a boolean")

        if claimed_signoff is True:
            if academic_hits:
                errors.append(
                    f"{ctx}: academic/pre-layout estimate ({', '.join(sorted(set(academic_hits)))}) "
                    "cannot be claimed as foundry manufacturing sign-off"
                )
            if uses_blackbox_sram is True:
                errors.append(
                    f"{ctx}: estimate using black-box SRAM cannot be claimed as foundry sign-off"
                )
            if includes_phy_io_pads is False:
                errors.append(
                    f"{ctx}: report omitting PHY/IO pads cannot be claimed as foundry sign-off"
                )
            if is_estimate_only is True:
                errors.append(
                    f"{ctx}: contradictory flags: is_estimate_only=true and claimed_as_foundry_signoff=true"
                )
        elif academic_hits and is_estimate_only is not True:
            errors.append(
                f"{ctx}: academic/pre-layout PPA entry ({', '.join(sorted(set(academic_hits)))}) "
                "must explicitly set is_estimate_only=true"
            )

    # 2. Approval object validation
    approval = package.get("approval")
    if not isinstance(approval, dict):
        errors.append("approval must be an object")
        approval = {}

    go_approved = approval.get("go_approved")
    if type(go_approved) is not bool:
        errors.append("approval.go_approved must be a boolean")
        go_approved = False

    if go_approved and phase_status == "not_started":
        errors.append("phase_status cannot be 'not_started' when approval.go_approved=true")
    if phase_status == "complete" and not go_approved:
        errors.append("phase_status cannot be 'complete' when approval.go_approved=false")

    # 3. Dependencies validation
    deps = package.get("dependencies")
    if not isinstance(deps, dict):
        errors.append("dependencies must be an object")
        deps = {}
    else:
        for cat in REQUIRED_DEPENDENCY_CATEGORIES:
            if cat not in deps or not isinstance(deps[cat], dict):
                errors.append(f"dependencies.{cat} is missing or not an object")
                continue
            dep = deps[cat]
            status = dep.get("status")
            if not isinstance(status, str) or not status.strip():
                errors.append(f"dependencies.{cat}.status must be a non-empty string")
            if go_approved:
                if status not in ("quoted", "acquired", "licensed"):
                    errors.append(
                        f"go_approved=true requires dependencies.{cat}.status in "
                        f"('quoted', 'acquired', 'licensed'), got {status!r}"
                    )
                if not _nonempty_real_text(dep.get("owner")):
                    errors.append(f"go_approved=true requires non-placeholder dependencies.{cat}.owner")
                if not _nonempty_real_text(dep.get("written_quote_ref")):
                    errors.append(
                        f"go_approved=true requires written quote reference dependencies.{cat}.written_quote_ref"
                    )
                if not _is_positive_finite(dep.get("quoted_cost_usd")):
                    errors.append(
                        f"go_approved=true requires positive quoted_cost_usd for dependencies.{cat}"
                    )
                quote_ref_text = str(dep.get("written_quote_ref", ""))
                if _looks_academic_or_blackbox(quote_ref_text) and cat in (
                    "foundry_pdk",
                    "standard_cells_io",
                    "sram_compiler",
                ):
                    errors.append(
                        f"go_approved=true rejects academic/black-box reference in dependencies.{cat}.written_quote_ref"
                    )

    # 4. Sign-off plans validation
    plans = package.get("signoff_plans")
    if not isinstance(plans, dict):
        errors.append("signoff_plans must be an object")
        plans = {}
    else:
        for plan_name in REQUIRED_SIGNOFF_PLANS:
            if plan_name not in plans or not isinstance(plans[plan_name], dict):
                errors.append(f"signoff_plans.{plan_name} is missing or not an object")
                continue
            plan = plans[plan_name]
            if plan.get("uses_blackbox_sram") is not False:
                errors.append(
                    f"signoff_plans.{plan_name}.uses_blackbox_sram must be false "
                    "(black-box memory assumptions cannot be sign-off)"
                )
            if plan.get("uses_blackbox_phy") is not False:
                errors.append(
                    f"signoff_plans.{plan_name}.uses_blackbox_phy must be false"
                )
            if plan.get("uses_academic_pdk_as_signoff") is not False:
                errors.append(
                    f"signoff_plans.{plan_name}.uses_academic_pdk_as_signoff must be false"
                )
            if not _nonempty_real_text(plan.get("criteria_summary")):
                errors.append(f"signoff_plans.{plan_name}.criteria_summary must be non-empty")
            if _looks_academic_or_blackbox(str(plan.get("criteria_summary", ""))):
                errors.append(
                    f"signoff_plans.{plan_name}.criteria_summary references academic/black-box assumption as sign-off"
                )
            if go_approved:
                if plan.get("status") not in ("reviewed", "approved", "complete"):
                    errors.append(
                        f"go_approved=true requires signoff_plans.{plan_name}.status in "
                        f"('reviewed', 'approved', 'complete'), got {plan.get('status')!r}"
                    )
                if not _nonempty_real_text(plan.get("owner")):
                    errors.append(
                        f"go_approved=true requires non-placeholder signoff_plans.{plan_name}.owner"
                    )

    # 5. Strict Go/No-Go human & funding gate enforcement
    if go_approved:
        approver = approval.get("human_approver")
        if not _nonempty_real_text(approver):
            errors.append("go_approved=true requires a non-empty human_approver")
        else:
            lowered_approver = str(approver).strip().lower()
            for marker in AGENT_APPROVER_MARKERS:
                if re.search(rf"\b{re.escape(marker)}\b", lowered_approver):
                    errors.append(
                        f"go_approved=true cannot be authorized by an automated/agent identity ({approver!r})"
                    )
                    break

        if not _nonempty_real_text(approval.get("approver_role")):
            errors.append("go_approved=true requires a non-empty approval.approver_role")
        if not _valid_iso_date(approval.get("approval_date")):
            errors.append("go_approved=true requires a valid ISO date YYYY-MM-DD in approval.approval_date")
        if approval.get("funding_approved") is not True:
            errors.append("go_approved=true requires approval.funding_approved=true")
        if not _is_positive_finite(approval.get("approved_budget_usd")):
            errors.append("go_approved=true requires positive approval.approved_budget_usd")
        if not _nonempty_real_text(approval.get("foundry_partner")):
            errors.append("go_approved=true requires non-placeholder approval.foundry_partner")
        if not _nonempty_real_text(approval.get("osat_partner")):
            errors.append("go_approved=true requires non-placeholder approval.osat_partner")
        if not _nonempty_real_text(approval.get("procurement_authority")):
            errors.append("go_approved=true requires non-placeholder approval.procurement_authority")
    else:
        if approval.get("funding_approved") is True:
            errors.append("approval.funding_approved cannot be true when approval.go_approved=false")
        if not errors:
            warnings.append(
                "Feasibility package is unapproved preparatory planning (go_approved=false); "
                "no foundry sign-off, spending, or tapeout is authorized."
            )

    return {
        "schema_version": SCHEMA_VERSION,
        "tool": "p10_feasibility_check.validate",
        "package_id": package.get("package_id"),
        "go_approved": go_approved,
        "outcome": "pass" if not errors else "fail",
        "errors": errors,
        "warnings": warnings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(
        prog="p10_feasibility_check.py",
        description="Validate P10 ASIC feasibility packages and enforce human Go/No-Go gates.",
        allow_abbrev=False,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    val_cmd = sub.add_parser("validate", help="Validate a P10 feasibility JSON package.")
    val_cmd.add_argument("input", type=Path, help="Path to P10 feasibility JSON package.")
    val_cmd.add_argument("--output", type=Path, default=None, help="Optional output JSON report path.")

    tmpl_cmd = sub.add_parser("emit-template", help="Emit the canonical unapproved P10 template JSON.")
    tmpl_cmd.add_argument("--output", type=Path, default=None, help="Optional output JSON path.")

    args = parser.parse_args(argv)

    if args.command == "emit-template":
        payload = build_template_package()
        encoded = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False)
        if args.output is not None:
            args.output.write_text(encoded + "\n", encoding="utf-8")
        print(encoded)
        return 0

    try:
        package = _read_json_strict(args.input)
        report = validate_feasibility_package(package)
    except (OSError, ValueError, UnicodeError) as exc:
        report = {
            "schema_version": SCHEMA_VERSION,
            "tool": "p10_feasibility_check.validate",
            "go_approved": False,
            "outcome": "fail",
            "errors": [str(exc)],
            "warnings": [],
        }

    encoded = json.dumps(report, indent=2, sort_keys=True, allow_nan=False)
    if args.output is not None:
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0 if report["outcome"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
