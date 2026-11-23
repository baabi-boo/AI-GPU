#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Execute the fixed managed preflight with its required lifetime witness."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True

import p06_managed_preflight_execute as preflight


def argument_parser():
    parser = preflight.argument_parser()
    parser.description = __doc__
    return parser


def execute(args, paths):
    return preflight.execute(args, paths, lifetime=True)


def main(argv=None):
    args = argument_parser().parse_args(argv)
    try:
        result = execute(args, preflight.base.resolve_paths(args))
        print(json.dumps({"outcome": result["outcome"], "reason": result["reason"],
            "report": str(Path(args.output).absolute() / "report.json"),
            "completed_counts": result["completed_counts"],
            "native_preflight_passed": result["native_preflight_passed"],
            "native_lifetime_passed": result["native_lifetime_passed"],
            **dict.fromkeys(preflight.manifest.FALSE_CLAIMS, False)}, sort_keys=True))
        return 0 if result["native_lifetime_passed"] else 1
    except (OSError, ValueError, RuntimeError, ImportError, TypeError) as error:
        print(json.dumps({"outcome": "blocked", "reason": str(error),
            "native_preflight_passed": False, "native_lifetime_passed": False,
            **dict.fromkeys(preflight.manifest.FALSE_CLAIMS, False)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    sys.exit(main())
