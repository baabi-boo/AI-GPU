# SPDX-License-Identifier: Apache-2.0
"""Verify published P01 exports without reconstructing their original log bytes."""

import re

from baseline_packet_io import (
    MAX_FILES, MAX_PATH_BYTES, MAX_PATH_DEPTH, MAX_TOTAL_BYTES,
    PacketError, PacketReader,
)


EXPORT_MANIFEST = "export-manifest.json"
MAX_MANIFEST_BYTES = 1024 * 1024
COPY = "byte_preserving_copy"
REDACTION = "literal_path_redaction"
EXPORT_LIMITATIONS = [
    "The export manifest is unsigned provenance metadata; matching public hashes do not authenticate its source assertions.",
    "Original command-log bytes and the asserted redaction relationship are not verified or reconstructed from published bytes.",
    "Native matrix record consistency checks reported outcomes, configuration snapshots and published log markers; it is not raw execution verification or project-gate acceptance.",
    "Source paths and sanitization rules are inert metadata; original paths are never opened and retained code is never executed.",
]


def _require(condition, message):
    if not condition:
        raise PacketError(message)


def _fields(value, fields, label):
    _require(type(value) is dict and set(value) == set(fields),
             label + " has missing or unknown fields")


def _text(value, label, maximum=4096):
    _require(type(value) is str and 0 < len(value) <= maximum
             and bool(value.strip())
             and not any(ord(character) < 32 or 127 <= ord(character) <= 159
                         for character in value), label + " must be bounded text")
    return value


def _path(value, label):
    _text(value, label, MAX_PATH_BYTES)
    try:
        parts = value.split("/")
        valid = (len(value.encode("utf-8")) <= MAX_PATH_BYTES
                 and not value.startswith("/") and "\\" not in value
                 and not (len(value) >= 2 and value[0].isalpha() and value[1] == ":")
                 and len(parts) <= MAX_PATH_DEPTH
                 and all(part not in ("", ".", "..")
                         and len(part.encode("utf-8")) <= 255 for part in parts))
    except UnicodeError as error:
        raise PacketError(label + " is not valid UTF-8") from error
    _require(valid, label + " must be a canonical relative POSIX path")
    return value


def _hash(value, label):
    _require(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value),
             label + " must be a lowercase SHA-256 identity")


def _size(value, label):
    _require(type(value) is int and 0 <= value <= MAX_TOTAL_BYTES,
             label + " must be a bounded nonnegative integer")


def _sanitization(value):
    _fields(value, {"method", "nested_hash_policy", "rules"}, "export sanitization")
    for name in ("method", "nested_hash_policy"):
        _text(value[name], "export sanitization." + name)
    rules = value["rules"]
    _require(type(rules) is list and len(rules) <= 128,
             "export sanitization rules must be a bounded list")
    prefixes = set()
    for rule in rules:
        _fields(rule, {"source_prefix", "replacement"}, "export sanitization rule")
        prefix = _text(rule["source_prefix"], "export sanitization source prefix")
        token = "${RAW_WORKSPACE}"
        _require(prefix == token or prefix.startswith(token + "/"),
                 "export sanitization source prefix must use RAW_WORKSPACE")
        if prefix != token:
            _path(prefix[len(token) + 1:], "export sanitization source suffix")
        _require(prefix not in prefixes, "export sanitization has duplicate source prefixes")
        prefixes.add(prefix)
        replacement = rule["replacement"]
        _require(type(replacement) is str
                 and re.fullmatch(r"\$[A-Z][A-Z0-9_]{0,63}", replacement),
                 "export sanitization replacement must be a symbolic label")
    return bool(rules)


def _mapping(manifest):
    _fields(manifest, {"schema_version", "source_packet", "reported_outcome", "scope",
                       "limitations", "sanitization", "artifacts"}, "export manifest")
    _require(type(manifest["schema_version"]) is int and manifest["schema_version"] == 1,
             "unsupported export manifest schema")
    source_prefix = _path(manifest["source_packet"], "export source packet") + "/"
    _require(manifest["reported_outcome"] in ("pass", "fail", "blocked"),
             "export has an invalid reported outcome")
    _text(manifest["scope"], "export scope")
    limitations = manifest["limitations"]
    _require(type(limitations) is list and len(limitations) <= 256,
             "export limitations must be a bounded list")
    for limitation in limitations:
        _text(limitation, "export limitation")
    has_rules = _sanitization(manifest["sanitization"])
    rows = manifest["artifacts"]
    _require(type(rows) is list and 2 <= len(rows) < MAX_FILES,
             "export artifacts must be a bounded list containing report and matrix")
    by_source = {}
    public_paths = set()
    for row in rows:
        _fields(row, {"path", "sha256", "size_bytes", "source_path", "source_sha256",
                      "source_size_bytes", "transformation"}, "export artifact")
        public = _path(row["path"], "export artifact path")
        source = _path(row["source_path"], "export artifact source path")
        _require(source.startswith(source_prefix), "export artifact is outside its source packet")
        member = _path(source[len(source_prefix):], "export packet member")
        _require(member not in by_source and public not in public_paths,
                 "export artifacts have duplicate source or published paths")
        for name in ("sha256", "source_sha256"):
            _hash(row[name], "export artifact." + name)
        for name in ("size_bytes", "source_size_bytes"):
            _size(row[name], "export artifact." + name)
        transformation = row["transformation"]
        _require(transformation in (COPY, REDACTION), "unsupported export transformation")
        if transformation == COPY:
            _require((row["sha256"], row["size_bytes"])
                     == (row["source_sha256"], row["source_size_bytes"]),
                     "byte-preserving export has different source and published identities")
        else:
            _require(has_rules and member.startswith("logs/") and member.endswith(".log"),
                     "export redaction is only supported for command logs with declared rules")
        by_source[member] = row
        public_paths.add(public)
    _require({"report.json", "matrix.json"} <= set(by_source),
             "export lacks its report or retained matrix")
    report_path = by_source["report.json"]["path"]
    _require(report_path == "report.json" or report_path.endswith("/report.json"),
             "export report has the wrong published filename")
    public_prefix = report_path[:-len("report.json")]
    for member, row in by_source.items():
        _require(row["path"] == public_prefix + member,
                 "export source and published paths do not map to the same packet member")
    _require(sum(row["size_bytes"] for row in rows) <= MAX_TOTAL_BYTES,
             "export published byte inventory exceeds the packet budget")
    return by_source


def verify_export(root, require_native_records=False):
    """Check published bytes and recorded native outcomes, never raw-log provenance.

    Only fixed packet-relative members are opened. The command-log resolver is
    the sole substitution point; helpers and configuration snapshots still pass
    the raw contract's strict retained-identity checks.
    """
    from baseline_packet_contract import verify_contract

    _require(type(require_native_records) is bool, "native-record requirement must be boolean")
    with PacketReader(root) as reader:
        manifest = reader.read_json(EXPORT_MANIFEST, limit=MAX_MANIFEST_BYTES)
        mapping = _mapping(manifest)
        report = reader.read_json("report.json")
        matrix = reader.read_json("matrix.json", limit=256 * 1024)
        command_logs = set()

        def resolve_log(identity, limit):
            member = identity["path"]
            _require(member in mapping, "export lacks a referenced command log")
            row = mapping[member]
            _require((row["source_sha256"], row["source_size_bytes"])
                     == (identity["sha256"], identity["size_bytes"]),
                     "export source log identity differs from the unchanged command record")
            _require(row["source_size_bytes"] <= limit,
                     "export source log identity exceeds the command byte limit")
            contents = reader.read_bytes(member, limit=limit)
            observed = next(item for item in reader.inventory() if item["path"] == member)
            _require((observed["sha256"], observed["size_bytes"])
                     == (row["sha256"], row["size_bytes"]),
                     "published command log differs from its export identity")
            command_logs.add(member)
            return contents

        summary = verify_contract(reader, report, matrix, log_resolver=resolve_log)
        _require(manifest["reported_outcome"] == report["outcome"],
                 "export outcome differs from the unchanged report")
        inventory = reader.inventory()
        referenced = {item["path"] for item in inventory} - {EXPORT_MANIFEST}
        _require(set(mapping) == referenced,
                 "export mapping does not cover exactly the referenced packet artifacts")
        for observed in inventory:
            member = observed["path"]
            if member == EXPORT_MANIFEST:
                continue
            row = mapping[member]
            _require((observed["sha256"], observed["size_bytes"])
                     == (row["sha256"], row["size_bytes"]),
                     "published artifact differs from its export identity")
            _require(row["transformation"] == COPY or member in command_logs,
                     "only referenced command logs may use export redaction")
        reader.recheck()

    native_consistent = summary.pop("native_matrix_passed")
    satisfied = not require_native_records or native_consistent
    return {
        "schema_version": 1,
        **summary,
        "verification_mode": "published_export",
        "published_integrity": "verified",
        "native_matrix_records_consistent": native_consistent,
        "raw_log_bytes_verified": False,
        "redaction_relationship_verified": False,
        "outcome": "pass" if satisfied else "fail",
        "requirement_satisfied": satisfied,
        "published_files": inventory,
        "phase_complete": False,
        "limitations": [*summary["limitations"], *EXPORT_LIMITATIONS],
    }
