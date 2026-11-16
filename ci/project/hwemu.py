#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Inspect vendor-emulation prerequisites and candidate plans without execution."""

import sys

if __name__ == "__main__":
    sys.dont_write_bytecode = True

import argparse
import json
from pathlib import Path

from hwemu_inventory import inventory
from hwemu_io import read_manifest


BOUNDARIES = {
    "execution_performed": False,
    "phase_complete": False,
    "launch_ready": False,
    "vendor_qualification_verified": False,
    "vendor_qualification": "unverified",
    "acceptance_id": "P01-A03",
    "acceptance_outcome": "blocked",
}


class _Parser(argparse.ArgumentParser):
    def error(self, _message):
        self.print_usage(sys.stderr)
        self.exit(2, self.prog + ": invalid arguments; use --help\n")


def plan_manifest(manifest):
    from hwemu_plan import create_plan

    return create_plan(manifest)


def _blocked(message):
    return {
        "schema_version": 1,
        "target": "hw_emu",
        "outcome": "blocked",
        **BOUNDARIES,
        "candidate": None,
        "blockers": [message],
        "limitations": ["No vendor tool, setup script, build, or workload was executed."],
    }


def _checked_report(report, mode):
    if type(report) is not dict:
        raise ValueError("invalid observation report")
    for key, expected in BOUNDARIES.items():
        if key in report and (type(report[key]) is not type(expected)
                              or report[key] != expected):
            raise ValueError("observation crossed its qualification boundary")
    result = {**report, **BOUNDARIES}
    if result.get("target") != "hw_emu" or result.get("outcome") not in ("blocked", "planned"):
        raise ValueError("invalid observation outcome")
    for key in ("blockers", "limitations"):
        if type(result.get(key)) is not list or any(type(item) is not str for item in result[key]):
            raise ValueError("invalid observation diagnostics")
    if mode == "inventory" and result["outcome"] != "blocked":
        raise ValueError("inventory cannot qualify a candidate")
    if result["outcome"] == "planned":
        if (result["blockers"] or type(result.get("candidate")) is not dict
                or result.get("input_consistency_verified") is not True):
            raise ValueError("candidate plan is incomplete")
    elif result.get("candidate") is not None:
        raise ValueError("blocked observation cannot expose a candidate")
    json.dumps(result, allow_nan=False)
    return result


def _emit(report, mode, json_output):
    if json_output:
        print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
        return
    print("hw_emu " + mode + ": " + report["outcome"])
    print("No GPU execution performed; P01-A03 remains blocked.")
    for title, key in (("Blockers", "blockers"), ("Limitations", "limitations")):
        if report[key]:
            print(title + ":")
            for item in report[key]:
                print("- " + item)
    if report.get("candidate") is not None:
        print("Candidate only; vendor qualification and bounded supervision remain required:")
        print(json.dumps(report["candidate"], indent=2, sort_keys=True, allow_nan=False))


def main(argv=None):
    parser = _Parser(
        prog="hwemu.py",
        description="Read-only hw_emu inventory and input-consistency planning; never executes a GPU.",
        allow_abbrev=False,
    )
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inventory", help="report missing local prerequisites",
                                  allow_abbrev=False)
    inspect.add_argument("--root", default=str(Path(__file__).resolve().parents[2]),
                         help="source checkout to inspect (defaults to this repository)")
    inspect.add_argument("--json", action="store_true", help="print the structured observation")
    plan = commands.add_parser("plan", help="check an inert manifest and describe a candidate",
                               allow_abbrev=False)
    plan.add_argument("manifest", metavar="MANIFEST", help="canonical absolute manifest path")
    plan.add_argument("--json", action="store_true", help="print the structured candidate report")
    args = parser.parse_args(argv)
    try:
        if args.command == "inventory":
            report = inventory(args.root)
        else:
            report = plan_manifest(read_manifest(args.manifest))
        report = _checked_report(report, args.command)
    except (OSError, ValueError, TypeError, RuntimeError):
        report = _blocked("Requested inputs are unavailable, unsafe, malformed, or inconsistent.")
    _emit(report, args.command, args.json)
    return 0 if report["outcome"] == "planned" else 1


if __name__ == "__main__":
    raise SystemExit(main())
