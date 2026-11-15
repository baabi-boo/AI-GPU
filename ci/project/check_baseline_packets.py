#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check published baseline evidence consistency without accepting project gates."""

import argparse
import json
from pathlib import Path
import sys

from baseline_packet_export import verify_export
from baseline_packet_io import PacketError


PACKETS = (
    ("native", "docs/project/evidence/p01/native", True),
    ("clean-build", "docs/project/evidence/p01/clean-build", False),
)


def check_baseline_packets(root):
    packets = {}
    for name, relative, require_native_records in PACKETS:
        packet = {"path": relative, "require_native_records": require_native_records}
        try:
            verified = verify_export(Path(root) / relative,
                                     require_native_records=require_native_records)
            errors = []
            if verified["outcome"] != "pass" or verified["requirement_satisfied"] is not True:
                errors.append("published evidence requirement is not satisfied")
            if verified["run_outcome"] != "pass":
                errors.append("retained run outcome must be pass")
            packet.update(
                outcome="fail" if errors else "pass",
                published_integrity=verified["published_integrity"],
                run_outcome=verified["run_outcome"],
                native_matrix_records_consistent=verified["native_matrix_records_consistent"],
            )
            if errors:
                packet["errors"] = errors
        except (PacketError, OSError, ValueError, UnicodeError, RecursionError) as error:
            reason = (str(error) if isinstance(error, PacketError)
                      else "published packet is unavailable or malformed")
            packet.update(outcome="fail", published_integrity="invalid", errors=[reason])
        packets[name] = packet
    return {
        "schema_version": 1,
        "outcome": "pass" if all(packet["outcome"] == "pass" for packet in packets.values()) else "fail",
        "phase_complete": False,
        "scope": "Published evidence consistency only; no project-gate acceptance.",
        "raw_log_bytes_verified": False,
        "redaction_relationship_verified": False,
        "packets": packets,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2],
                        help="repository root (defaults to the checkout containing this script)")
    args = parser.parse_args(argv)
    result = check_baseline_packets(args.root)
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0 if result["outcome"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
