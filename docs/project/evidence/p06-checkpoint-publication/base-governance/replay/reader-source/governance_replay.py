#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Reconcile one inert governance ZIP against an explicitly trusted source revision.

Discovery imports the selected trusted checkout in an isolated child; retained ZIP
members are only data. This reader never executes the recorded tests or tools.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys

from governance_replay_archive import read_archive
from governance_replay_events import reconcile
from governance_replay_records import validate_records


MIB = 1024 * 1024
MEMBER_LIMITS = {
    "logs/cmake-install.log": MIB,
    "logs/cmake-requirements.txt": 256,
    "logs/cmake-version.log": 64 * 1024,
    "logs/environment.log": 16 * 1024,
    "logs/governance.log": 256 * MIB,
    "logs/source-revision.txt": 65,
    "environment/environment.json": MIB,
    "run/discovered.json": 32 * MIB,
    "run/events.jsonl": 32 * MIB,
    "run/started.json": 32 * MIB,
    "run/summary.json": 32 * MIB,
    "run/unittest.log": 128 * MIB,
}
CMAKE_REQUIREMENT = (b"cmake==3.22.6 --hash=sha256:"
                     b"a2357c510e37db7df156c31ab43857b4583e3a2ece8220747e8a007aea50aa45\n")
_TRAILER = re.compile(rb"\n-{70}\nRan ([1-9][0-9]{0,5}) (test|tests) in ([0-9]{1,12}\.[0-9]{3})s\n\nOK\n\Z")
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_SINGLE_BYTES = tuple(bytes((value,)) for value in range(256))


class ReplayError(ValueError):
    """The selected artifact does not establish the bounded replay claim."""


def _require(condition, message):
    if not condition:
        raise ReplayError(message)


def _source_binding(source_dir, revision):
    from governance_replay_source import source_binding
    return source_binding(source_dir, revision)


def _collect(source_dir, revision):
    from governance_replay_collect import collect
    return collect(source_dir, revision)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "JSON contains a duplicate object key")
        result[key] = value
    return result


def _nonfinite(_value):
    raise ReplayError("JSON contains a nonfinite number")


def _finite_float(value):
    number = float(value)
    _require(math.isfinite(number), "JSON contains a nonfinite number")
    return number


def _json(raw):
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                           parse_constant=_nonfinite, parse_float=_finite_float)
    except (UnicodeError, ValueError, RecursionError):
        raise ReplayError("retained JSON is malformed or ambiguous") from None
    _require(type(value) is dict, "retained JSON must be an object")
    return value


def _same(actual, expected, message):
    # JSON encodings preserve boolean/integer distinctions which Python == loses.
    try:
        equal = (json.dumps(actual, sort_keys=True, allow_nan=False, separators=(",", ":"))
                 == json.dumps(expected, sort_keys=True, allow_nan=False, separators=(",", ":")))
    except (ValueError, TypeError, RecursionError):
        equal = False
    _require(equal, message)


def _source_projection(source, revision):
    return {"head": source["head"], "tree": source["tree"],
            "object_format": "sha1" if len(revision) == 40 else "sha256",
            "tracked_sha256": source["tracked_sha256"],
            "tracked_count": source["tracked_count"], "tracked_bytes": source["tracked_bytes"],
            "gitlinks": [{"path": link["path"], "oid": link["pinned_oid"]}
                         for link in source["gitlinks"]]}


def _subsequence(inner, outer):
    """Linear scan: OS/child diagnostics can interrupt Python log writes."""
    position = 0
    for offset in range(0, len(inner), 4096):
        chunk = inner[offset:offset + 4096]
        if outer.startswith(chunk, position):
            position += len(chunk)
            continue
        for value in chunk:
            position = outer.find(_SINGLE_BYTES[value], position)
            if position < 0:
                return False
            position += 1
    return True


def _logs(members, summary, environment, execution):
    inner, outer = members["run/unittest.log"], members["logs/governance.log"]
    _require(len(inner) == summary["log"]["bytes"], "internal log byte count differs")
    _require(len(members["run/events.jsonl"]) == summary["event_bytes"], "event byte count differs")
    trailer = _TRAILER.search(inner)
    _require(trailer is not None, "internal log has no complete successful unittest trailer")
    count = execution["tests_run"]
    _require(int(trailer[1]) == count and trailer[2] == (b"test" if count == 1 else b"tests"),
             "unittest trailer count differs from reconciled execution")
    _require(float(trailer[3]) <= execution["duration_seconds"] + 0.001,
             "unittest trailer duration exceeds execution duration")
    ending = ("Strict governance PASSED: " + summary["command"][3] + "/summary.json\n").encode("utf-8")
    _require(outer.endswith(ending) and len(outer) >= len(inner) + len(ending),
             "outer log has no complete strict-runner success line")
    outer_body = outer[:-len(ending)]
    _require(outer_body.endswith(trailer[0]), "inner and outer unittest trailers differ")
    _require(_subsequence(inner, outer_body), "outer log omits or reorders internal log bytes")
    _require(members["logs/cmake-requirements.txt"] == CMAKE_REQUIREMENT,
             "retained CMake requirement differs from the workflow pin")
    version = members["logs/cmake-version.log"]
    _require(version.startswith(b"cmake version 3.22.6\n") and version.endswith(b"\n")
             and version.decode("utf-8").strip() == environment["tools"]["cmake"]["version"],
             "CMake version log disagrees with the prepared tool")
    _require(members["logs/cmake-install.log"].endswith(b"Successfully installed cmake-3.22.6\n"),
             "CMake install log has no complete successful termination")
    environment_log = members["logs/environment.log"]
    _require(environment_log.endswith(b"\n"), "environment log is incomplete")
    _same(_json(environment_log), {"interpreter": environment["interpreter"],
          "environment_receipt": environment["output_dir"] + "/environment.json"},
          "environment log disagrees with the preparation receipt")


def verify_archive(path, *, revision, source_dir, expected_sha256):
    """Return a source-bound replay receipt, without authenticating its provider."""
    _require(type(revision) is str and re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", revision),
             "expected revision must be a full lowercase Git object ID")
    _require(type(expected_sha256) is str and re.fullmatch(r"[0-9a-f]{64}", expected_sha256),
             "expected archive digest must be a lowercase SHA-256")
    packet = read_archive(path)
    _require(packet["archive"]["sha256"] == expected_sha256, "archive digest differs from the expected digest")
    members = packet["members"]
    _require(set(members) == set(MEMBER_LIMITS) and packet["member_count"] == len(MEMBER_LIMITS),
             "archive does not contain the exact governance workflow member set")
    for name, limit in MEMBER_LIMITS.items():
        _require(type(members[name]) is bytes and 0 < len(members[name]) <= limit,
                 "retained member is empty or exceeds its specific byte limit")
    _require(members["logs/source-revision.txt"] == (revision + "\n").encode("ascii"),
             "retained source revision differs from the selected revision")
    source_before = _source_binding(source_dir, revision)
    started, summary, environment, discovered = (_json(members[name]) for name in
        ("run/started.json", "run/summary.json", "environment/environment.json", "run/discovered.json"))
    records = validate_records(started, summary, environment, revision=revision,
                               environment_bytes=members["environment/environment.json"])
    expected_source = _source_projection(summary["source_before"], revision)
    _same(source_before, expected_source, "trusted source inventory differs from retained source")
    execution = reconcile(discovered, members["run/events.jsonl"], summary["execution"])
    _logs(members, summary, environment, execution)
    canonical = _collect(source_dir, revision)
    _require(type(canonical) is list and canonical == discovered["test_ids"],
             "retained test identities differ from trusted canonical discovery")
    _same(_source_binding(source_dir, revision), source_before, "trusted source changed during collection")
    receipt = {
        "schema_version": 1, "scope": "project-governance-artifact-replay-only",
        "independent_packet_replay": True, "revision": revision,
        "source_tree": source_before["tree"], "source_tracked_sha256": source_before["tracked_sha256"],
        "source_tracked_count": source_before["tracked_count"], "source_tracked_bytes": source_before["tracked_bytes"],
        "canonical_tests": execution["tests_run"], "canonical_ids_sha256": execution["discovered_sha256"],
        "successful_subtests": execution["subtest_counts"].get("success", 0), "events": execution["event_count"],
        "duration_seconds": execution["duration_seconds"], "archive": dict(packet["archive"]),
        "environment_sha256": records["environment_sha256"], "event_bytes": len(members["run/events.jsonl"]),
        "log_bytes": {"inner": len(members["run/unittest.log"]), "outer": len(members["logs/governance.log"])},
        "provider_authenticated": False, "retained_code_executed": False,
        "trusted_source_imported": True, "tests_executed_by_replay": False,
        "native_acceptance": False, "phase_acceptance": False, "performance_acceptance": False,
        "limitations": ["Retained records are reconciled; their execution is not reproduced.",
                        "Canonical discovery imports the explicitly trusted checkout without running test bodies.",
                        "Artifact authenticity requires separate provider evidence.",
                        "No native, performance, or phase acceptance is established."],
    }
    _same(_source_binding(source_dir, revision), source_before, "trusted source changed during replay")
    return receipt


def _output_path(value):
    text = os.fspath(value)
    _require(type(text) is str and 0 < len(text) <= 4096 and text.startswith("/")
             and "\\" not in text and ":" not in text
             and not any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in text),
             "output must be a canonical absolute path")
    path = PurePosixPath(text)
    _require(str(path) == text and not text.startswith("//") and ".." not in path.parts
             and 1 < len(path.parts) <= 64
             and all(len(part.encode("utf-8")) <= 255 for part in path.parts),
             "output path contains a noncanonical component")
    return Path(text)


def _directory(path):
    descriptor = os.open("/", _DIRECTORY_FLAGS)
    identities = [(os.fstat(descriptor).st_dev, os.fstat(descriptor).st_ino)]
    try:
        for part in path.parts[1:]:
            child = os.open(part, _DIRECTORY_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
            info = os.fstat(descriptor)
            identities.append((info.st_dev, info.st_ino))
        return descriptor, identities
    except BaseException:
        os.close(descriptor)
        raise


def _write_output(value, raw, source_dir):
    path = _output_path(value)
    source = _output_path(source_dir)
    _require(not path.is_relative_to(source), "output must be outside the trusted checkout")
    parent, identities = _directory(path.parent)
    descriptor = None
    try:
        # Unnamed staging needs no pathname deletion when a write fails.
        descriptor = os.open(".", os.O_RDWR | os.O_TMPFILE | os.O_NOFOLLOW | os.O_CLOEXEC,
                             0o600, dir_fd=parent)
        created = os.fstat(descriptor)
        _require(stat.S_ISREG(created.st_mode) and created.st_nlink == 0 and created.st_size == 0,
                 "receipt staging is not an empty anonymous file")
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            _require(written > 0, "receipt write was incomplete")
            view = view[written:]
        os.fsync(descriptor)
        fresh, fresh_identities = _directory(path.parent)
        try:
            staged = os.fstat(descriptor)
            _require(identities == fresh_identities and staged.st_nlink == 0
                     and staged.st_size == len(raw)
                     and (staged.st_dev, staged.st_ino) == (created.st_dev, created.st_ino),
                     "output changed while writing the receipt")
            os.link("/proc/self/fd/" + str(descriptor), path.name,
                    dst_dir_fd=fresh, follow_symlinks=True)
        finally:
            os.close(fresh)
        fresh, fresh_identities = _directory(path.parent)
        try:
            observed = os.stat(path.name, dir_fd=fresh, follow_symlinks=False)
            published = os.fstat(descriptor)
            _require(identities == fresh_identities and stat.S_ISREG(observed.st_mode)
                     and observed.st_nlink == published.st_nlink == 1
                     and observed.st_size == published.st_size == len(raw)
                     and (observed.st_dev, observed.st_ino) == (created.st_dev, created.st_ino),
                     "output changed while writing the receipt")
            os.fsync(fresh)
        finally:
            os.close(fresh)
    finally:
        # A published name may belong to another writer by now; preserve it on failure.
        if descriptor is not None:
            os.close(descriptor)
        os.close(parent)


class _Parser(argparse.ArgumentParser):
    def error(self, _message):
        raise ReplayError("invalid replay arguments")


def _emit(stream, text):
    try:
        _require(stream.write(text) == len(text), "receipt output was incomplete")
        stream.flush()
    except Exception:
        # A failed buffered write must not be retried during interpreter shutdown.
        try:
            stream.close()
        except Exception:
            pass
        raise


def main(argv=None):
    parser = _Parser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--archive", required=True, help="canonical absolute path to the original ZIP")
    parser.add_argument("--expected-revision", required=True, help="full trusted Git commit ID")
    parser.add_argument("--source-dir", required=True, help="exact clean trusted checkout; discovery imports this source")
    parser.add_argument("--expected-sha256", required=True, help="independently selected original ZIP digest")
    parser.add_argument("--output", help="fresh canonical absolute receipt path outside the trusted checkout")
    try:
        args = parser.parse_args(argv)
        receipt = verify_archive(args.archive, revision=args.expected_revision, source_dir=args.source_dir,
                                 expected_sha256=args.expected_sha256)
        text = json.dumps(receipt, sort_keys=True, indent=2, allow_nan=False) + "\n"
        if args.output is not None:
            _write_output(args.output, text.encode("utf-8"), args.source_dir)
        _emit(sys.stdout, text)
        return 0
    except Exception:
        # Never echo retained fields, credential-bearing paths or raw tool errors.
        try:
            _emit(sys.stderr, "governance replay failed\n")
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    raise SystemExit(main())
