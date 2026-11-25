#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Execute managed lifetime observations with a pinned fresh dependency original."""

from __future__ import annotations

import json
from pathlib import Path
import signal
import sys

sys.dont_write_bytecode = True

import p06_managed_preflight_execute as preflight


def argument_parser():
    parser = preflight.argument_parser()
    parser.description = __doc__
    parser.add_argument("--dependency-receipt", type=Path, required=True)
    parser.add_argument("--dependency-receipt-sha256", required=True)
    return parser


def execute(args, paths):
    return preflight.execute(args, paths, lifetime=True, dependency=True)


def _main(argv=None):
    args = argument_parser().parse_args(argv)
    try:
        result = execute(args, preflight.base.resolve_paths(args))
        print(json.dumps({"outcome": result["outcome"], "reason": result["reason"],
            "report": str(Path(args.output).absolute() / "report.json"),
            "completed_counts": result["completed_counts"],
            "native_preflight_passed": result["native_preflight_passed"],
            "native_lifetime_passed": result["native_lifetime_passed"],
            "dependency_source_to_loaded_binary_verified": result["dependency_source_to_loaded_binary_verified"],
            **dict.fromkeys(preflight.manifest.FALSE_CLAIMS, False)}, sort_keys=True))
        return 0 if result["dependency_source_to_loaded_binary_verified"] else 1
    except (OSError, ValueError, RuntimeError, ImportError, TypeError) as error:
        print(json.dumps({"outcome": "blocked", "reason": str(error),
            "native_preflight_passed": False, "native_lifetime_passed": False,
            "dependency_source_to_loaded_binary_verified": False,
            **dict.fromkeys(preflight.manifest.FALSE_CLAIMS, False)}, sort_keys=True))
        return 1


def main(argv=None):
    def interrupt(number, frame):
        raise KeyboardInterrupt

    previous = signal.getsignal(signal.SIGTERM)
    try:
        signal.signal(signal.SIGTERM, interrupt)
        return _main(argv)
    finally:
        signal.signal(signal.SIGTERM, previous)


if __name__ == "__main__":
    sys.exit(main())
