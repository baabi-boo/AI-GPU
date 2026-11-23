#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Execute the explicit fresh four-process counter qualification preflight."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True

import p06_dependency_lifetime_execute as dependency_runner


preflight = dependency_runner.preflight


def argument_parser():
    parser = dependency_runner.argument_parser()
    parser.description = __doc__
    parser.add_argument("--counter-qualification", type=Path, required=True)
    parser.add_argument("--counter-qualification-sha256", required=True)
    parser.add_argument("--diagnostic-archive", type=Path, required=True)
    parser.add_argument("--diagnostic-archive-sha256", required=True)
    parser.add_argument("--control-archive", type=Path, required=True)
    parser.add_argument("--control-archive-sha256", required=True)
    return parser


def execute(args, paths):
    return preflight.execute(args, paths, lifetime=True, dependency=True,
                             counter_qualification=True)


def main(argv=None):
    args = argument_parser().parse_args(argv)
    try:
        result = execute(args, preflight.base.resolve_paths(args))
        print(json.dumps({"outcome": result["outcome"], "reason": result["reason"],
            "report": str(Path(args.output).absolute() / "report.json"),
            "completed_counts": result["completed_counts"],
            "native_preflight_passed": result["native_preflight_passed"],
            "native_lifetime_passed": result["native_lifetime_passed"],
            "dependency_source_to_loaded_binary_verified": result["dependency_source_to_loaded_binary_verified"],
            "counter_qualification_passed": result["counter_qualification_passed"],
            **dict.fromkeys(preflight.manifest.FALSE_CLAIMS, False)}, sort_keys=True))
        return 0 if result["counter_qualification_passed"] else 1
    except (OSError, ValueError, RuntimeError, ImportError, TypeError) as error:
        print(json.dumps({"outcome": "blocked", "reason": str(error),
            "native_preflight_passed": False, "native_lifetime_passed": False,
            "dependency_source_to_loaded_binary_verified": False,
            "counter_qualification_passed": False,
            **dict.fromkeys(preflight.manifest.FALSE_CLAIMS, False)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    sys.exit(main())
