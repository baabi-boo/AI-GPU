#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Verify retained P01 execution evidence without running or accepting it."""

import argparse
import json
import os
from pathlib import Path
import sys

from baseline_packet_contract import verify_contract
from baseline_packet_io import PacketError, PacketReader, write_bytes_exclusive


MANIFEST_KIND = "p01-baseline-packet"
MAX_MANIFEST_BYTES = 1024 * 1024


def _encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def _read_manifest(path):
    supplied = Path(os.path.abspath(path))
    with PacketReader(supplied.parent) as reader:
        result = reader.read_json(supplied.name, limit=MAX_MANIFEST_BYTES)
        reader.recheck()
        return result


def verify_packet(root, manifest_path=None, require_native_pass=False):
    with PacketReader(root) as reader:
        report = reader.read_json("report.json")
        matrix = reader.read_json("matrix.json", limit=256 * 1024)
        summary = verify_contract(reader, report, matrix)
        reader.recheck()
        manifest = {
            "schema_version": 1,
            "kind": MANIFEST_KIND,
            "files": reader.inventory(),
            "native_matrix_passed": summary["native_matrix_passed"],
            "phase_complete": False,
        }
        if manifest_path is not None:
            supplied = _read_manifest(manifest_path)
            if _encoded(supplied) != _encoded(manifest):
                raise PacketError("supplied manifest differs from the verified packet")
        reader.recheck()
    satisfied = not require_native_pass or summary["native_matrix_passed"]
    return {
        "schema_version": 1,
        **summary,
        "outcome": "pass" if satisfied else "fail",
        "integrity": "verified",
        "requirement_satisfied": satisfied,
        "manifest": manifest,
        "manifest_matched": manifest_path is not None,
        "phase_complete": False,
    }


def write_manifest(path, root, manifest):
    # Descriptor traversal anchors all leading-slash spellings at the POSIX root.
    supplied = Path("/" + os.path.abspath(path).lstrip("/"))
    packet = Path("/" + os.path.abspath(root).lstrip("/"))
    if supplied == packet or supplied.is_relative_to(packet):
        raise PacketError("manifest output must be outside the retained packet")
    data = _encoded(manifest)
    if len(data) > MAX_MANIFEST_BYTES:
        raise PacketError("manifest exceeds its size limit")
    write_bytes_exclusive(supplied, data)


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="mode", required=True)
    for name in ("verify", "seal"):
        command = commands.add_parser(name)
        command.add_argument("packet", type=Path)
        command.add_argument("--require-native-pass", action="store_true",
                             help="require all six frozen native cases and final provenance to pass")
        if name == "verify":
            command.add_argument("--manifest", type=Path)
        else:
            command.add_argument("--output", type=Path, required=True,
                                 help="new unsigned hash inventory outside the retained packet")
    published = commands.add_parser("verify-export", help="verify an explicitly published, path-redacted packet")
    published.add_argument("packet", type=Path)
    published.add_argument("--require-native-records", action="store_true",
                           help="require complete consistent native records without claiming original log bytes")
    return parser


def main(argv=None):
    args = argument_parser().parse_args(argv)
    try:
        if args.mode == "verify-export":
            from baseline_packet_export import verify_export
            result = verify_export(args.packet, args.require_native_records)
        else:
            result = verify_packet(args.packet, getattr(args, "manifest", None),
                                   args.require_native_pass)
        if args.mode == "seal" and result["requirement_satisfied"]:
            write_manifest(args.output, args.packet, result["manifest"])
            result["manifest_written"] = True
        print(_encoded(result).decode("utf-8"), end="")
        return 0 if result["requirement_satisfied"] else 1
    except (PacketError, OSError, ValueError, UnicodeError, RecursionError) as error:
        reason = str(error) if isinstance(error, PacketError) else "packet or manifest is unavailable or malformed"
        result = {"schema_version": 1, "outcome": "fail", "phase_complete": False,
                  "errors": [reason]}
        if args.mode == "verify-export":
            result.update(verification_mode="published_export", published_integrity="invalid",
                          native_matrix_records_consistent=False, raw_log_bytes_verified=False,
                          redaction_relationship_verified=False)
        else:
            result.update(integrity="invalid", native_matrix_passed=False)
        print(json.dumps(result, sort_keys=True))
        return 1


if __name__ == "__main__":
    sys.exit(main())
