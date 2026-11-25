#!/usr/bin/env python3
"""Inert reconciliation of observed governance-v1 ZIP evidence against external pins."""

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import zipfile


MIB = 1024**2
MAX_ZIP = 64 * MIB
SCOPE = "project-governance-unittest-only"
DISCOVERY = {"pattern": "test_*.py", "start_directory": "ci/project"}
LIMITS = {
    "environment/environment.json": MIB,
    "run/started.json": 32 * MIB,
    "run/discovered.json": 32 * MIB,
    "run/events.jsonl": 32 * MIB,
    "run/summary.json": 32 * MIB,
    "run/unittest.log": 128 * MIB,
    "logs/governance.log": 128 * MIB,
    "logs/source-revision.txt": 128,
}
TOOLS = {"python", "python3", "cmake", "gcc", "g++", "ar", "ranlib",
         "make", "git", "tclsh", "readelf"}
PROBES = {"c_preprocessor", "cmake_build", "cxx17_threads", "elf32_link",
          "fifo", "nofollow", "ubsan_rejects_overflow", "ubsan_runtime"}


def require(condition, label):
    if not condition:
        raise ValueError(label)


def same(actual, expected, label):
    require(json.dumps(actual, sort_keys=True, allow_nan=False)
            == json.dumps(expected, sort_keys=True, allow_nan=False), label)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def number(value, label):
    require(type(value) in (int, float) and math.isfinite(value) and value >= 0, label)
    return value


def integer(value, label, minimum=0):
    require(type(value) is int and value >= minimum, label)
    return value


def load_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON key: " + key)
            result[key] = value
        return result

    def floating(value):
        parsed = float(value)
        require(math.isfinite(parsed), "nonfinite JSON number")
        return parsed

    def constant(value):
        raise ValueError("nonfinite JSON constant: " + value)

    return json.loads(raw, object_pairs_hook=pairs, parse_float=floating,
                      parse_constant=constant)


def absolute(value):
    require(isinstance(value, str) and value.startswith("/")
            and str(PurePosixPath(value)) == value
            and ".." not in PurePosixPath(value).parts, "invalid retained absolute path")
    return value


def identity(row):
    require(isinstance(row, dict), "invalid tool identity")
    require(re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) is not None, "invalid tool hash")
    return {"requested_path": absolute(row["path"]),
            "resolved_path": absolute(row["resolved_path"]),
            "sha256": row["sha256"],
            "size_bytes": integer(row["size_bytes"], "invalid tool size", 1)}


def read_members(raw):
    require(len(raw) <= MAX_ZIP, "ZIP exceeds 64 MiB reviewer limit")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        require(len(entries) <= 128, "ZIP exceeds 128-member reviewer limit")
        names = [entry.filename for entry in entries]
        require(len(set(names)) == len(names), "duplicate ZIP member")
        require(set(LIMITS) <= set(names), "missing required ZIP members: "
                + ", ".join(sorted(set(LIMITS) - set(names))))
        require(sum(entry.file_size for entry in entries) <= 384 * MIB,
                "ZIP exceeds 384 MiB expanded reviewer limit")
        data = {}
        for entry in entries:
            require(entry.filename == entry.orig_filename and "\\" not in entry.filename
                    and not entry.filename.startswith("/")
                    and ".." not in PurePosixPath(entry.filename).parts,
                    "ambiguous ZIP member name")
            if entry.filename not in LIMITS:
                continue
            mode = stat.S_IFMT(entry.external_attr >> 16)
            require(mode in (0, stat.S_IFREG) and not entry.is_dir(), "nonregular evidence member")
            require(not entry.flag_bits & 1, "encrypted evidence member")
            limit = LIMITS[entry.filename]
            require(entry.file_size <= limit, "oversized evidence member: " + entry.filename)
            with archive.open(entry) as source:
                member = source.read(limit + 1)
            require(len(member) == entry.file_size and len(member) <= limit,
                    "evidence member size mismatch")
            data[entry.filename] = member
        return data, len(entries), sum(entry.file_size for entry in entries)


def review_bytes(raw, revision, expected_hash):
    require(re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", revision) is not None,
            "expected revision must be a full lowercase Git object ID")
    require(re.fullmatch(r"[0-9a-f]{64}", expected_hash) is not None,
            "expected SHA-256 must be a full lowercase digest")
    require(len(raw) <= MAX_ZIP, "ZIP exceeds 64 MiB reviewer limit")
    same(sha(raw), expected_hash, "ZIP hash differs from external expected hash")
    data, members, expanded = read_members(raw)
    manifest = load_json(data["run/discovered.json"])
    started = load_json(data["run/started.json"])
    summary = load_json(data["run/summary.json"])
    environment = load_json(data["environment/environment.json"])
    execution = summary["execution"]
    for row in (manifest, started, summary, execution):
        require(isinstance(row, dict), "expected governance JSON object")
        same(row["schema_version"], 1, "unsupported governance schema")
        same(row["scope"], SCOPE, "unexpected governance scope")
    for row in (manifest, started, summary):
        same(row["discovery"], DISCOVERY, "noncanonical discovery")
    require(set(manifest) == {"schema_version", "scope", "discovery", "test_ids", "count", "sha256"},
            "unsupported manifest fields")
    ids = manifest["test_ids"]
    require(isinstance(ids, list) and 0 < len(ids) <= 100000, "invalid manifest population")
    require(all(isinstance(item, str) and item and len(item.encode("utf-8")) <= 4096
                and "\n" not in item and "\r" not in item for item in ids), "invalid canonical ID")
    require(len(set(ids)) == len(ids), "duplicate canonical ID")
    same(manifest["count"], len(ids), "manifest count mismatch")
    digest = sha("".join(item + "\n" for item in ids).encode("utf-8"))
    same(manifest["sha256"], digest, "ordered manifest digest mismatch")

    same(started["status"], "started", "invalid started status")
    same(started["execution_completed"], False, "started receipt claims completion")
    same(started["governance_passed"], False, "started receipt claims pass")
    same(summary["status"], "completed", "governance receipt is incomplete")
    same(summary["errors"], [], "governance receipt reports errors")
    for flag in ("execution_completed", "governance_passed", "source_stable",
                 "interpreter_stable", "environment_stable"):
        same(summary[flag], True, "false or invalid completion/stability flag: " + flag)
    for key in ("command", "source_root", "started_at", "source_before",
                "interpreter_before", "environment_before"):
        same(started[key], summary[key], "started/summary mismatch: " + key)
    for key in ("source", "interpreter", "environment"):
        same(summary[key + "_before"], summary[key + "_after"], key + " identities changed")
    source = summary["source_before"]
    same(source["head"], revision, "source revision differs from external expected revision")
    require(data["logs/source-revision.txt"] == (revision + "\n").encode(), "revision log mismatch")
    same(source["clean"], True, "source was not clean")
    same(source["status_porcelain"], "", "source status was not empty")
    same(source["mismatch_count"], 0, "source mismatch count")
    same(source["mismatches"], [], "source mismatches")
    require(re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", source["tree"]) is not None,
            "invalid source tree ID")
    require(re.fullmatch(r"[0-9a-f]{64}", source["tracked_sha256"]) is not None,
            "invalid source inventory hash")
    same(source["index_sha256"], source["tracked_sha256"], "HEAD/index inventory mismatch")
    same(source["worktree_sha256"], source["tracked_sha256"], "HEAD/worktree inventory mismatch")
    integer(source["tracked_count"], "invalid tracked count", 1)
    integer(source["tracked_bytes"], "invalid tracked bytes")
    root = absolute(summary["source_root"])
    same(source["root"], root, "source root mismatch")

    same(environment["schema_version"], 1, "unsupported environment schema")
    same(environment["status"], "ready", "environment was not ready")
    same(environment["error"], None, "environment error")
    same(environment["source_root"], root, "environment source root mismatch")
    same(environment["probes"], {key: True for key in PROBES}, "environment probe mismatch")
    env_root = absolute(environment["output_dir"])
    interpreter = env_root + "/venv/bin/python3"
    receipt_path = env_root + "/environment.json"
    same(environment["interpreter"], interpreter, "prepared interpreter alias mismatch")
    expected_environment = {
        "CCACHE_DISABLE": "1", "CMAKE_BUILD_PARALLEL_LEVEL": "2", "HOME": env_root + "/home",
        "LANG": "C", "LC_ALL": "C", "MAKEFLAGS": "-j2", "OBJCACHE": "",
        "PATH": env_root + "/venv/bin:/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUTF8": "1", "THREADS": "1", "TMPDIR": env_root + "/tmp", "TZ": "UTC",
    }
    same(environment["environment"], expected_environment, "prepared environment mismatch")
    tools = environment["tools"]
    require(isinstance(tools, dict) and TOOLS <= set(tools) and len(tools) <= 64,
            "incomplete or oversized tool inventory")
    require(all(name and "/" not in name and "\\" not in name for name in tools), "invalid tool alias")
    tool_identities = {name: identity(row) for name, row in tools.items()}
    selection = environment["cmake_selection"]
    require(selection["resolution"] in ("native", "python-package"), "unsupported CMake selection")
    expected_snapshot = {
        "receipt_path": receipt_path, "receipt_sha256": sha(data["environment/environment.json"]),
        "receipt_size_bytes": len(data["environment/environment.json"]), "tools": tool_identities,
        "cmake_selection": {key: identity(selection[key]) for key in ("native", "requested")},
    }
    same(summary["environment_before"], expected_snapshot, "environment receipt/tool binding mismatch")
    same(source["git"], tool_identities["git"], "source Git identity mismatch")
    for field in ("resolved_path", "sha256", "size_bytes"):
        same(tools["python"][field], tools["python3"][field], "Python alias identity mismatch")
        same(tools["cmake"][field], selection["native"][field], "native CMake identity mismatch")
    same(tools["python"]["path"], env_root + "/venv/bin/python", "Python alias path mismatch")
    same(tools["python3"]["path"], interpreter, "Python3 alias path mismatch")
    cmake = re.match(r"cmake version (\d+)\.(\d+)\.(\d+)\b", tools["cmake"]["version"])
    require(cmake is not None and int(cmake[1]) == 3 and 21 <= int(cmake[2]) <= 25,
            "CMake version outside runbook range")
    python = environment["python"]
    for key, value in {"platform": "linux", "implementation": "cpython", "machine": "x86_64",
                       "byteorder": "little", "gil_enabled": True,
                       "user_site_enabled": False, "pip_present": False}.items():
        same(python[key], value, "Python prerequisite mismatch: " + key)
    same(python["version_info"][:2], [3, 12], "unsupported Python version")
    same(python["libc"][0], "glibc", "unsupported libc")
    same(python["executable"], interpreter, "Python probe interpreter mismatch")
    same(summary["interpreter_before"], {
        "base_prefix": python["base_prefix"], "executable": tool_identities["python3"],
        "implementation": "CPython", "path": expected_environment["PATH"],
        "platform": "linux", "prefix": python["prefix"], "version": python["version"],
    }, "interpreter receipt mismatch")
    command = summary["command"]
    require(isinstance(command, list) and len(command) == 6, "unsupported governance command")
    output = absolute(command[3])
    same(command, [interpreter, root + "/ci/project/governance_run.py", "--output-dir", output,
                   "--environment-receipt", receipt_path], "governance launch mismatch")
    require(not PurePosixPath(output).is_relative_to(root)
            and not PurePosixPath(root).is_relative_to(output), "output overlaps source root")
    times = [datetime.fromisoformat(value) for value in
             (environment["started_at"], environment["finished_at"],
              summary["started_at"], summary["finished_at"])]
    require(all(item.utcoffset() is not None for item in times) and times == sorted(times),
            "receipt timestamp order mismatch")

    duration = number(execution["duration_seconds"], "invalid execution duration")
    require(duration <= (times[-1] - times[-2]).total_seconds(), "duration exceeds receipt interval")
    counts = Counter()
    active, completed, outcome, previous_elapsed, encoded_subtests = None, 0, False, 0, 0
    event_bytes = data["run/events.jsonl"]
    events = io.BytesIO(event_bytes)
    sequence = 0
    while line := events.readline(65537):
        require(len(line) <= 65536 and line.endswith(b"\n"), "oversized or unfinished event line")
        event = load_json(line)
        require(isinstance(event, dict), "event is not an object")
        sequence += 1
        require(sequence <= 1000000, "event count exceeds runner limit")
        same(event["sequence"], sequence, "noncontiguous event sequence")
        elapsed = number(event["elapsed_seconds"], "invalid event time")
        require(previous_elapsed <= elapsed <= duration, "event time order/range mismatch")
        previous_elapsed = elapsed
        kind = event["event"]
        keys = {"sequence", "event", "elapsed_seconds", "test_id"}
        require(kind in {"test_start", "test_outcome", "test_stop", "subtest_outcome"},
                "fixture or unsupported event in pass packet")
        if kind in {"test_outcome", "subtest_outcome"}:
            keys.add("outcome")
            same(event["outcome"], "success", "non-successful outcome")
        if kind == "test_start":
            require(active is None and completed < len(ids), "overlapping or excess test start")
            same(event["test_id"], ids[completed], "test start differs from ordered manifest")
            active, outcome = event["test_id"], False
        else:
            require(active is not None, "event outside active test")
            same(event["test_id"], active, "event parent differs from active test")
            if kind == "test_outcome":
                require(not outcome, "duplicate terminal outcome")
                outcome = True
            elif kind == "test_stop":
                require(outcome, "test stopped without successful outcome")
                active, completed = None, completed + 1
            else:
                require(not outcome, "subtest after terminal outcome")
                keys.add("subtest_id")
                label = event["subtest_id"]
                require(isinstance(label, str) and label and len(label.encode("utf-8")) <= 4096,
                        "invalid subtest label")
                if "subtest_id_encoding" in event:
                    keys |= {"subtest_id_encoding", "subtest_id_original_encoding", "subtest_id_original_bytes"}
                    same(event["subtest_id_encoding"], "sha256", "unsupported subtest encoding")
                    same(event["subtest_id_original_encoding"], "utf-8", "unsupported original encoding")
                    require(re.fullmatch(r"sha256:[0-9a-f]{64}", label) is not None, "invalid encoded subtest ID")
                    integer(event["subtest_id_original_bytes"], "invalid encoded subtest length", 4097)
                    encoded_subtests += 1
                else:
                    require(label.startswith(active + " "), "short subtest label has wrong parent")
        require(set(event) == keys, "unsupported event fields")
        counts[kind] += 1
    require(active is None and completed == len(ids), "incomplete event population")
    expected_execution = {
        "schema_version": 1, "scope": SCOPE, "abort": None, "counts_match": True,
        "coverage_complete": True, "discovered_count": len(ids), "discovered_sha256": digest,
        "duration_seconds": duration, "event_count": sequence, "execution_completed": True,
        "fixture_counts": {}, "loader_errors": [], "non_successful_ids": [], "order_matches": True,
        "outcome_counts": {"success": len(ids)}, "started_count": len(ids), "stopped_count": len(ids),
        "strict_success": True, "subtest_counts": ({"success": counts["subtest_outcome"]}
                                                   if counts["subtest_outcome"] else {}),
        "tests_run": len(ids), "duplicate_discovered_ids": [],
    }
    expected_execution.update({prefix + "_" + role + "_ids": []
                               for prefix in ("duplicate", "missing", "unexpected")
                               for role in ("started", "stopped", "outcome")})
    same(execution, expected_execution, "summary execution differs from independently reconciled events")
    same(summary["event_bytes"], len(event_bytes), "event byte count mismatch")
    same(summary["log"], {"bytes": len(data["run/unittest.log"]), "truncated": False}, "internal log accounting mismatch")
    log_seconds = {}
    for name in ("run/unittest.log", "logs/governance.log"):
        log = data[name].decode("utf-8")
        observed_ids = re.findall(r"^\S+ \(([^()\r\n]+)\)(?: \.\.\. |$)", log, re.MULTILINE)
        same(observed_ids, ids, "ordered test IDs differ in " + name)
        if name.startswith("logs/"):
            marker = "Strict governance PASSED: " + output + "/summary.json\n"
            require(log.endswith(marker), "outer strict-pass marker missing or mismatched")
            log = log[:-len(marker)]
        terminal = re.search(r"\n-+\nRan (\d+) tests? in ([0-9]+(?:\.[0-9]+)?)s\n\nOK\n\Z", log)
        require(terminal is not None and int(terminal[1]) == len(ids), "unittest completion mismatch in " + name)
        seconds = number(float(terminal[2]), "invalid log duration")
        require(seconds <= duration + 0.001, "log duration exceeds execution duration")
        log_seconds[name] = seconds
    same(log_seconds["run/unittest.log"], log_seconds["logs/governance.log"], "log duration disagreement")
    return {
        "status": "verified-consistent-pass", "scope": "inert-governance-v1-reconciliation",
        "expected_revision": revision, "archive_sha256": sha(raw), "archive_bytes": len(raw),
        "archive_members": members, "archive_expanded_bytes": expanded,
        "source_tree": source["tree"], "source_inventory_sha256": source["tracked_sha256"],
        "canonical_tests": len(ids), "ordered_manifest_sha256": digest,
        "event_counts": dict(counts), "events": sequence, "event_bytes": len(event_bytes),
        "encoded_subtest_labels": encoded_subtests, "duration_seconds": duration,
        "log_duration_seconds": log_seconds["run/unittest.log"],
        "source_stable": True, "interpreter_stable": True, "environment_stable": True,
        "checked_tool_count": len(tool_identities), "python_version": python["version"],
        "cmake_version": cmake[0], "fixture_events": 0, "non_success_outcomes": 0,
        "members_checked": {name: {"bytes": len(value), "sha256": sha(value)} for name, value in data.items()},
        "limitations": [
            "Verifies internal consistency of the externally hash-pinned archive; no provider provenance authentication.",
            "Source/tool snapshots are cross-checked as retained records; their original executable/file bytes are not re-observed.",
            "No retained commands or code are executed and no archive members are extracted.",
            "The outer terminal marker is checked; the provider process exit code is not independently observed.",
            "Only the pinned revision is covered; no native execution, performance acceptance, or phase acceptance is established.",
            "Observed successful schema-v1 packets only; incompatible schemas, non-success packets, or reviewer-limit excesses are rejected.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--expected-revision", required=True)
    parser.add_argument("--expected-sha256", required=True)
    args = parser.parse_args()
    try:
        with os.fdopen(os.open(args.archive, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW), "rb") as source:
            require(stat.S_ISREG(os.fstat(source.fileno()).st_mode), "archive must be a regular file")
            raw = source.read(MAX_ZIP + 1)
        result = review_bytes(raw, args.expected_revision, args.expected_sha256)
    except (OSError, ValueError, KeyError, TypeError, IndexError, OverflowError,
            RecursionError, RuntimeError, zipfile.BadZipFile, NotImplementedError) as error:
        result = {"status": "rejected", "scope": "inert-governance-v1-reconciliation",
                  "error": str(error), "error_type": type(error).__name__}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "verified-consistent-pass" else 1


if __name__ == "__main__":
    sys.exit(main())
