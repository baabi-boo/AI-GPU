#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Verify a caller-pinned dependency original inside an inert, bounded ZIP.

The archive and dependency report digests must be obtained independently of
the packet. A pass establishes retained-data consistency for the selected
dependency build; it does not execute a compiler, native application or any
retained source, command or binary, and does not authenticate its producer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True

import p06_dependency_contract as contract
import p06_dependency_receipt as receipt
import p06_managed_preflight_replay as managed_archive


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_ID = "p06-dependency-provenance-replay-v1"
DEFAULT_PREFIX = "dependency-build"
MAX_PACKET_FILES = 20000
MAX_CACHE_BYTES = contract.MAX_PACKET_BYTES
DEPENDENCY_MODULES = (
    "p06_dependency_binary", "p06_dependency_contract", "p06_dependency_graph",
    "p06_dependency_receipt", "p06_dependency_record", "p06_dependency_sources",
    "p06_dependency_local_prepare", "p06_local_toolchain",
    "p06_managed_preflight_source_export",
)
LIMITATIONS = [
    "This result verifies retained dependency-build consistency; no compiler or native process is executed by replay.",
    "The caller supplies the archive, dependency receipt and source revision independently; matching data does not authenticate GitHub origin or an untrusted producer.",
    "Retained commands, code, binaries and producer paths are inert. Only the explicit local archive and trusted current reader sources are opened.",
    "The selected dependency packet is checked completely; other hosted packet prefixes and the managed native population require their separate review.",
    "A consistently synthetic or forged execution history remains synthetic or forged after consistency review.",
    "The original dependency reader's compiler/system-input and concurrent-writer limits remain applicable.",
    "Qualification, warm execution, full warm coverage and phase/performance acceptance remain false.",
]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def _reader_sources():
    """Freeze current trusted readers, never an inventory supplied by the ZIP."""
    rows = managed_archive._reader_sources()
    modules = [(name, sys.modules.get(name)) for name in DEPENDENCY_MODULES]
    modules.append(("p06_dependency_replay", sys.modules[__name__]))
    for name, module in modules:
        require(module is not None and type(getattr(module, "__file__", None)) is str,
                "trusted dependency replay module is missing: " + name)
        path = ROOT / "ci/project" / (name + ".py")
        require(Path(module.__file__).resolve(strict=True) == path,
                "dependency replay module loaded outside the trusted checkout: " + name)
        body = path.read_bytes()
        rows.append({"path": "ci/project/" + name + ".py",
                     "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)})
    require(len({row["path"] for row in rows}) == len(rows),
            "trusted replay source inventory repeats a file")
    return sorted(rows, key=lambda row: row["path"])


TRUSTED_READER_SOURCES = _reader_sources()


def _archive_api():
    # The managed reader compiles the already hash-verified helper bytes rather
    # than consulting SourceFileLoader's timestamp/size bytecode cache.
    return managed_archive._archive_api()


class CachedPacket:
    """Read each selected member at most once within the existing packet bound."""

    def __init__(self, view):
        self.view = view
        self.allowed = {"report.json"}
        self.cache = {}
        self.bytes_read = 0

    def __call__(self, name):
        receipt.relative(name)
        require(name in self.allowed, "retained path is outside the selected packet inventory")
        if name not in self.cache:
            require(len(self.cache) < MAX_PACKET_FILES + 1,
                    "dependency replay cache exceeds its file bound")
            limit = contract.MAX_RECEIPT_BYTES if name == "report.json" else contract.MAX_FILE_BYTES
            body = self.view.read(name, limit=min(limit, MAX_CACHE_BYTES - self.bytes_read))
            require(type(body) is bytes and self.bytes_read + len(body) <= MAX_CACHE_BYTES,
                    "dependency replay cache exceeds its byte bound")
            self.cache[name] = body
            self.bytes_read += len(body)
        return self.cache[name]

    def select(self, document):
        require(type(document) is dict and type(document.get("retained_files")) is list
                and 0 < len(document["retained_files"]) <= MAX_PACKET_FILES,
                "dependency retained inventory is absent or outside its bound")
        names = []
        total = 0
        for row in document["retained_files"]:
            receipt.fields(row, receipt.DESCRIPTOR_FIELDS, "retained descriptor")
            name = receipt.relative(row["path"])
            require(name != "report.json", "dependency report cannot inventory itself")
            require(type(row["sha256"]) is str and receipt.SHA256.fullmatch(row["sha256"])
                    and type(row["size_bytes"]) is int
                    and 0 <= row["size_bytes"] <= contract.MAX_FILE_BYTES,
                    "retained descriptor has invalid digest or byte count")
            total += row["size_bytes"]
            require(total <= contract.MAX_PACKET_BYTES,
                    "dependency packet exceeds its total byte bound")
            names.append(name)
        require(len(names) == len(set(names)), "dependency retained inventory repeats a path")
        self.allowed = set(names) | {"report.json"}
        require(set(self.view.files()) == self.allowed,
                "dependency ZIP prefix contains omitted or unlisted files")
        # Check all retained bytes even if a future semantic reader consumes
        # only a subset. The cache keeps subsequent semantic reads inexpensive.
        for row in document["retained_files"]:
            receipt.descriptor(row, self)


def verify_view(view, *, expected_revision, expected_receipt_sha256):
    """Check one explicit dependency view; no producer path becomes a host path."""
    require(type(expected_revision) is str and receipt.REVISION.fullmatch(expected_revision),
            "exact external source revision is required")
    require(type(expected_receipt_sha256) is str and receipt.SHA256.fullmatch(expected_receipt_sha256),
            "external dependency receipt SHA-256 is required")
    read = CachedPacket(view)
    body = read("report.json")
    require(hashlib.sha256(body).hexdigest() == expected_receipt_sha256,
            "dependency receipt SHA-256 differs from the external intake identity")
    document = receipt.decode(body)
    read.select(document)
    verified = receipt.verify_document(document, read, expected_revision=expected_revision)
    require(set(read.cache) == read.allowed and set(view.files()) == read.allowed,
            "dependency packet inventory changed or was incompletely read")
    return {
        "dependency_report": {"path": "report.json", "sha256": expected_receipt_sha256,
                              "size_bytes": len(body)},
        "retained_dependency_verification": verified,
        "packet_files_checked": len(read.cache), "packet_bytes_checked": read.bytes_read,
    }


def replay_archive(path, sha256, *, expected_revision, expected_receipt_sha256,
                   prefix=DEFAULT_PREFIX):
    """Review the dependency subset of one externally pinned hosted original."""
    require(type(sha256) is str and receipt.SHA256.fullmatch(sha256),
            "external original ZIP SHA-256 is required")
    require(type(expected_revision) is str and receipt.REVISION.fullmatch(expected_revision),
            "exact external source revision is required")
    require(type(expected_receipt_sha256) is str and receipt.SHA256.fullmatch(expected_receipt_sha256),
            "external dependency receipt SHA-256 is required")
    require(type(prefix) is str, "dependency packet prefix must be literal text")
    require(_reader_sources() == TRUSTED_READER_SOURCES,
            "trusted dependency replay source changed after import")
    api = _archive_api()
    if prefix:
        api.relative_name(prefix)
    try:
        with api.ArchiveReader(path, sha256) as archive:
            checked = verify_view(archive.view(prefix), expected_revision=expected_revision,
                                  expected_receipt_sha256=expected_receipt_sha256)
            result = {
                "schema_version": 1, "contract_id": CONTRACT_ID,
                "scope": "selected-dependency-retained-consistency", "outcome": "pass",
                "retained_consistency": True, "native_execution": "not_run",
                "retained_code_executed": False, "source_revision": expected_revision,
                "dependency_receipt_sha256": expected_receipt_sha256, "prefix": prefix,
                **checked, "archive_read": archive.receipt(),
                "trusted_archive_reader": {"path": managed_archive.archive_helpers.ARCHIVE_READER_PATH,
                    "sha256": managed_archive.archive_helpers.ARCHIVE_READER_SHA256},
                "trusted_reader_sources": TRUSTED_READER_SOURCES,
                "limitations": list(LIMITATIONS), **dict.fromkeys(contract.FALSE_CLAIMS, False),
            }
        # ArchiveReader.close() rechecks the whole ZIP digest before a result is
        # returned. A changed archive can never leave through this success path.
        require(_reader_sources() == TRUSTED_READER_SOURCES,
                "trusted dependency replay source changed during review")
        return result
    except (KeyError, TypeError, IndexError, UnicodeError, OverflowError, RecursionError) as error:
        raise ValueError("malformed retained dependency packet: " + str(error)) from error


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--dependency-receipt-sha256", required=True)
    parser.add_argument("--prefix", default=DEFAULT_PREFIX)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv=None):
    args = argument_parser().parse_args(argv)
    try:
        result = replay_archive(args.archive, args.sha256, expected_revision=args.source_revision,
            expected_receipt_sha256=args.dependency_receipt_sha256, prefix=args.prefix)
        body = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
        if args.output is None:
            print(body, end="")
        else:
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(body)
            print(json.dumps({"outcome": "pass", "scope": result["scope"],
                "report": str(args.output), "retained_consistency": True,
                "native_execution": "not_run", "retained_code_executed": False,
                **dict.fromkeys(contract.FALSE_CLAIMS, False)}, sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({"outcome": "fail", "reason": str(error),
            "retained_consistency": False, "native_execution": "not_run",
            "retained_code_executed": False, **dict.fromkeys(contract.FALSE_CLAIMS, False)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    sys.exit(main())
