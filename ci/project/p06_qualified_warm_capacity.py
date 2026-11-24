# SPDX-License-Identifier: Apache-2.0
"""Observe bounded Linux memory snapshots; never authorize native execution."""

import argparse
from dataclasses import dataclass
import errno
import hashlib
import json
import os
import re
import stat
import sys
import time


CONTRACT_ID = "p06-qualified-warm-capacity-v1"
REQUIRED_BYTES = 4 * 1024**3
MAX_MEMINFO_BYTES = 64 * 1024
MAX_MEMBERSHIP_BYTES = 64 * 1024
MAX_MOUNTINFO_BYTES = 1024**2
MAX_SCALAR_BYTES = 4096
MAX_TOTAL_BYTES = 2 * 1024**2
MAX_FILE_READS = 512
MAX_READ_CALLS = 1024
MAX_PATH_BYTES = 4096
MAX_PATH_DEPTH = 64
MAX_ANCESTORS = 64
MAX_MOUNTS = 4096
MAX_SECONDS = 2.0
MAX_JSON_BYTES = 64 * 1024
MAX_INTEGER = 2**64 - 1
FALSE_CLAIMS = (
    "native_launch_authorized", "retained_code_executed", "qualified",
    "ready_for_warm", "warm_execution", "full_warm_coverage",
    "acceptance_claimed", "phase_acceptance", "performance_acceptance",
    "counter_qualification_passed", "qualified_warm_passed", "governance_passed",
)
SCALARS = ("cgroup.type", "memory.max", "memory.current")


class ObservationError(ValueError):
    """A fixed, path-free reason suitable for the public report."""


@dataclass(frozen=True)
class Mount:
    identifier: int
    device: tuple
    root: str
    point: str
    filesystem: str


@dataclass(frozen=True)
class ReadResult:
    body: bytes
    identity: tuple


def _text(body, maximum):
    if not isinstance(body, bytes) or len(body) > maximum:
        raise ObservationError("invalid_or_oversized_input")
    try:
        return body.decode("utf-8", errors="strict")
    except UnicodeError:
        raise ObservationError("invalid_encoding") from None


def _integer(token):
    if not re.fullmatch(r"[0-9]{1,20}", token):
        raise ObservationError("invalid_integer")
    value = int(token)
    if value > MAX_INTEGER:
        raise ObservationError("integer_out_of_range")
    return value


def parse_scalar(body, *, allow_max=False):
    token = _text(body, MAX_SCALAR_BYTES)
    if token.endswith("\n"):
        token = token[:-1]
    if allow_max and token == "max":
        return "max"
    return _integer(token)


def parse_memavailable(body):
    lines = _text(body, MAX_MEMINFO_BYTES).splitlines()
    matches = [line for line in lines if line.startswith("MemAvailable:")]
    if len(matches) != 1:
        raise ObservationError("missing_or_duplicate_memavailable")
    match = re.fullmatch(r"MemAvailable:[ \t]+([0-9]{1,20})[ \t]+kB[ \t]*", matches[0])
    if match is None:
        raise ObservationError("invalid_memavailable")
    value = _integer(match[1]) * 1024
    if value > MAX_INTEGER:
        raise ObservationError("integer_out_of_range")
    return value


def parse_controllers(body):
    token = _text(body, MAX_SCALAR_BYTES)
    if token.endswith("\n"):
        token = token[:-1]
    names = tuple(token.split(" ")) if token else ()
    if (len(names) != len(set(names))
            or any(re.fullmatch(r"[a-z][a-z_]*", name) is None for name in names)):
        raise ObservationError("invalid_controllers")
    return names


def _components(path):
    if (not path.startswith("/") or len(path.encode("utf-8")) > MAX_PATH_BYTES
            or "\x00" in path or any(ord(char) < 32 or ord(char) == 127 for char in path)):
        raise ObservationError("unsupported_path")
    parts = tuple(path[1:].split("/")) if path != "/" else ()
    if any(part in ("", ".", "..") for part in parts):
        raise ObservationError("noncanonical_path")
    if len(parts) > MAX_PATH_DEPTH:
        raise ObservationError("path_depth_limit")
    return parts


def _path(parts):
    return "/" + "/".join(parts)


def _within(path, root):
    parts, base = _components(path), _components(root)
    return parts[:len(base)] == base


def parse_membership(body):
    lines = _text(body, MAX_MEMBERSHIP_BYTES).splitlines()
    if len(lines) != 1 or not lines[0].startswith("0::"):
        raise ObservationError("unsupported_or_ambiguous_cgroup_membership")
    path = lines[0][3:]
    # proc membership escaping is not mountinfo escaping; do not guess a name.
    if "\\" in path or path.endswith(" (deleted)"):
        raise ObservationError("unsupported_membership_path")
    _components(path)
    return path


def _mount_path(token):
    escapes = {"040": " ", "011": "\t", "012": "\n", "134": "\\"}
    if re.search(r"\\(?!040|011|012|134)", token):
        raise ObservationError("invalid_mount_escape")
    path = re.sub(r"\\(040|011|012|134)", lambda match: escapes[match[1]], token)
    _components(path)
    return path


def parse_mountinfo(body):
    lines = _text(body, MAX_MOUNTINFO_BYTES).splitlines()
    if not lines or len(lines) > MAX_MOUNTS:
        raise ObservationError("missing_or_oversized_mount_table")
    mounts, identifiers = [], set()
    for line in lines:
        fields = line.split(" ")
        try:
            separator = fields.index("-", 6)
        except ValueError:
            raise ObservationError("invalid_mount_record") from None
        if any(not field for field in fields) or len(fields) != separator + 4:
            raise ObservationError("invalid_mount_record")
        identifier, parent = _integer(fields[0]), _integer(fields[1])
        device = fields[2].split(":")
        if not identifier or not parent or identifier in identifiers or len(device) != 2:
            raise ObservationError("invalid_or_duplicate_mount_identity")
        identifiers.add(identifier)
        mounts.append(Mount(identifier, tuple(_integer(value) for value in device),
                            _mount_path(fields[3]), _mount_path(fields[4]), fields[separator + 1]))
    return tuple(mounts)


def map_visible_ancestors(membership, mounts):
    """Return only the unique visible v2 mapping, without a completeness claim."""
    if any(mount.filesystem == "cgroup" for mount in mounts):
        raise ObservationError("unsupported_v1_or_hybrid_mounts")
    candidates = [mount for mount in mounts
                  if mount.filesystem == "cgroup2" and _within(membership, mount.root)]
    if len(candidates) != 1:
        raise ObservationError("missing_or_ambiguous_v2_mount")
    mount = candidates[0]
    relative = _components(membership)[len(_components(mount.root)):]
    if len(relative) + 1 > MAX_ANCESTORS:
        raise ObservationError("ancestor_depth_limit")
    base = _components(mount.point)
    ancestors = tuple(_path(base + relative[:depth])
                      for depth in range(len(relative), -1, -1))
    target_prefixes = set()
    for directory in ancestors:
        target_prefixes.add(_components(directory))
        for name in (*SCALARS, "memory.high", "cgroup.controllers"):
            target_prefixes.add(_components(directory.rstrip("/") + "/" + name))
    for other in mounts:
        if other.identifier != mount.identifier and _components(other.point) in target_prefixes:
            raise ObservationError("overlaid_or_crossed_mount")
    return mount, ancestors


class _Reader:
    def __init__(self, reader, clock):
        self.injected = reader
        self.clock = clock
        self.started = clock()
        self.file_reads = self.read_calls = self.total_bytes = 0
        self.exhausted = None

    def check(self):
        if self.exhausted:
            raise ObservationError(self.exhausted)
        if self.clock() - self.started >= MAX_SECONDS:
            self.exhausted = "time_budget_exhausted"
            raise ObservationError(self.exhausted)

    def read(self, path, maximum, mount=None):
        self.check()
        if self.file_reads >= MAX_FILE_READS:
            self.exhausted = "file_read_budget_exhausted"
            raise ObservationError(self.exhausted)
        remaining = MAX_TOTAL_BYTES - self.total_bytes
        if remaining <= 1:
            self.exhausted = "byte_budget_exhausted"
            raise ObservationError(self.exhausted)
        self.file_reads += 1
        # Reserve the overflow-detection byte inside the aggregate ceiling.
        maximum = min(maximum, remaining - 1)
        try:
            result = (self.injected(path, maximum, mount) if self.injected is not None
                      else self._regular(path, maximum, mount))
        except OSError as error:
            reason = "missing_file" if error.errno == errno.ENOENT else "unreadable_or_unsafe_file"
            raise ObservationError(reason) from None
        if (not isinstance(result, ReadResult) or not isinstance(result.body, bytes)
                or not isinstance(result.identity, tuple) or not result.identity
                or len(result.identity) > 2 * (MAX_PATH_DEPTH + 1)
                or any(type(value) is not int or value < 0 for value in result.identity)):
            raise ObservationError("invalid_reader_result")
        if self.injected is not None:
            self.total_bytes += min(len(result.body), maximum + 1)
        if len(result.body) > maximum:
            if maximum == remaining - 1:
                self.exhausted = "byte_budget_exhausted"
            raise ObservationError(self.exhausted or "oversized_file")
        self.check()
        return result

    def _regular(self, path, maximum, mount):
        parts = _components(path)
        if not parts:
            raise ObservationError("nonregular_file")
        flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
        directory = os.open("/", flags | os.O_DIRECTORY)
        descriptor = None
        identity = []
        mount_depth = len(_components(mount.point)) if mount else None
        try:
            for index, part in enumerate(parts[:-1], 1):
                self.check()
                next_directory = os.open(part, flags | os.O_DIRECTORY, dir_fd=directory)
                os.close(directory)
                directory = next_directory
                info = os.fstat(directory)
                if mount is not None and index >= mount_depth:
                    if (os.major(info.st_dev), os.minor(info.st_dev)) != mount.device:
                        raise ObservationError("crossed_mount_device")
                    identity.extend((info.st_dev, info.st_ino))
            self.check()
            descriptor = os.open(parts[-1], flags, dir_fd=directory)
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode):
                raise ObservationError("nonregular_file")
            if info.st_size > maximum:
                raise ObservationError("oversized_file")
            if mount is not None and (os.major(info.st_dev), os.minor(info.st_dev)) != mount.device:
                raise ObservationError("crossed_mount_device")
            identity.extend((info.st_dev, info.st_ino))
            body = bytearray()
            while len(body) <= maximum:
                self.check()
                if self.read_calls >= MAX_READ_CALLS:
                    self.exhausted = "read_call_budget_exhausted"
                    raise ObservationError(self.exhausted)
                self.read_calls += 1
                chunk = os.read(descriptor, min(65536, maximum + 1 - len(body)))
                if not chunk:
                    break
                self.total_bytes += len(chunk)
                body.extend(chunk)
            return ReadResult(bytes(body), tuple(identity))
        finally:
            if descriptor is not None:
                os.close(descriptor)
            os.close(directory)


def _read_value(reader, path, maximum, parser, mount=None):
    try:
        result = reader.read(path, maximum, mount)
        return parser(result.body), result, None
    except ObservationError as error:
        return None, None, str(error)


def _domain(body):
    if body not in (b"domain", b"domain\n"):
        raise ObservationError("unsupported_cgroup_type")
    return "domain"


def _sample(reader, directory, mount):
    values, identities, errors = {}, {}, {}
    for name in SCALARS:
        parser = _domain if name == "cgroup.type" else (
            (lambda body: parse_scalar(body, allow_max=True)) if name == "memory.max" else parse_scalar)
        value, result, error = _read_value(
            reader, directory.rstrip("/") + "/" + name, MAX_SCALAR_BYTES, parser, mount)
        values[name] = value
        if result is not None:
            identities[name] = result.identity
        if error is not None:
            errors[name] = error
    return values, identities, errors


def _base_report():
    return {
        "schema_version": 1, "contract_id": CONTRACT_ID,
        "scope": "advisory-read-only-visible-memory-snapshot",
        "status": "unknown", "exit_code": 1, "required_bytes": REQUIRED_BYTES,
        "known_memory_shortfall": False, "observation_complete": False,
        "host_available_bytes": None, "host_available_samples_bytes": [],
        "visible_limit_bytes": None, "visible_headroom_bytes": None,
        "visible_shortfall_observed": False, "visible_capacity_status": "unknown",
        "effective_capacity_status": "unknown", "effective_headroom_bytes": None,
        "full_ancestry_status": "unknown", "ancestry_complete": None,
        "topology_stable": None, "limits_stable": None,
        "membership": {"status": "unknown"}, "mount_mapping": {"status": "unknown"},
        "visible_root_observation": {"status": "unknown"},
        "ancestors": [], "errors": [], "native_execution": "not_run",
        **dict.fromkeys(FALSE_CLAIMS, False),
        "limitations": [
            "Full ancestry has no reviewed witness; namespace-relative root and all-max are not unlimited proof.",
            "Observation completeness covers visible reads only; hidden ancestors can impose tighter limits.",
            "A supported visible-root interface pattern is not a full-ancestry or unlimited-memory witness.",
            "Snapshots reserve nothing, are not atomic, and cannot prove allocation or native launch safety.",
            "Finite headroom uses ancestor usage including descendants; reclaim can change this margin.",
            "memory.high is a separate throttle observation; swap is never added to RAM.",
            "Topology equality at endpoints cannot exclude intervening migration or limit changes.",
            "The monotonic deadline is polled; it cannot interrupt a blocked kernel read or injected reader.",
            "Paths and ancestor names are omitted; relative level zero is the process's visible cgroup.",
        ],
    }


def observe_capacity(reader=None, *, clock=time.monotonic):
    """Injected reader(path, max_bytes, mount) returns bounded bytes and identity in ReadResult."""
    report, bounded = _base_report(), _Reader(reader, clock)
    proc = "/proc/" + str(os.getpid())
    host, _, error = _read_value(bounded, "/proc/meminfo", MAX_MEMINFO_BYTES, parse_memavailable)
    report["host_available_samples_bytes"].append(host)
    if error:
        report["errors"].append("host:first:" + error)
    membership, membership_read, error = _read_value(
        bounded, proc + "/cgroup", MAX_MEMBERSHIP_BYTES, parse_membership)
    if error:
        report["errors"].append("membership:first:" + error)
    else:
        report["membership"] = {"status": "observed", "depth": len(_components(membership)),
                                "namespace_relative_root": membership == "/",
                                "sha256": hashlib.sha256(membership_read.body).hexdigest()}
    mounts, mount_read, error = _read_value(
        bounded, proc + "/mountinfo", MAX_MOUNTINFO_BYTES, parse_mountinfo)
    if error:
        report["errors"].append("mounts:first:" + error)
    mount, ancestors, samples, highs, root_controllers = None, (), [], [], []
    root_high_last = None
    if membership is not None and mounts is not None:
        try:
            mount, ancestors = map_visible_ancestors(membership, mounts)
            report["mount_mapping"] = {
                "status": "observed", "filesystem": "cgroup2", "mount_id": mount.identifier,
                "mount_root_depth": len(_components(mount.root)),
                "mount_point_depth": len(_components(mount.point)),
                "process_depth_from_mount_root": len(ancestors) - 1,
                "mountinfo_sha256": hashlib.sha256(mount_read.body).hexdigest(),
            }
        except ObservationError as error:
            report["errors"].append("mapping:" + str(error))
    for directory in ancestors:
        samples.append([_sample(bounded, directory, mount)])
        high, _, error = _read_value(bounded, directory.rstrip("/") + "/memory.high",
                                    MAX_SCALAR_BYTES,
                                    lambda body: parse_scalar(body, allow_max=True), mount)
        highs.append((high, error))
        if (directory == ancestors[-1] and mount.root == "/" and error == "missing_file"
                and samples[-1][0][2] == dict.fromkeys(SCALARS, "missing_file")):
            # Linux omits these non-root interfaces at the real root. A namespace
            # root alone is insufficient: require its memory controller interface.
            root_controllers.append(_read_value(
                bounded, directory.rstrip("/") + "/cgroup.controllers",
                MAX_SCALAR_BYTES, parse_controllers, mount))
    for index, directory in enumerate(ancestors):
        samples[index].append(_sample(bounded, directory, mount))
        if root_controllers and directory == ancestors[-1]:
            root_high_last = _read_value(
                bounded, directory.rstrip("/") + "/memory.high", MAX_SCALAR_BYTES,
                lambda body: parse_scalar(body, allow_max=True), mount)
            root_controllers.append(_read_value(
                bounded, directory.rstrip("/") + "/cgroup.controllers",
                MAX_SCALAR_BYTES, parse_controllers, mount))
    host, _, error = _read_value(bounded, "/proc/meminfo", MAX_MEMINFO_BYTES, parse_memavailable)
    report["host_available_samples_bytes"].append(host)
    if error:
        report["errors"].append("host:last:" + error)
    topology_pairs = []
    for name, maximum, parser, first in (
        ("cgroup", MAX_MEMBERSHIP_BYTES, parse_membership, membership_read),
        ("mountinfo", MAX_MOUNTINFO_BYTES, parse_mountinfo, mount_read),
    ):
        _, last, error = _read_value(bounded, proc + "/" + name, maximum, parser)
        if error:
            report["errors"].append(name + ":last:" + error)
        topology_pairs.append(None if first is None or last is None else first == last)
    if False in topology_pairs:
        report["topology_stable"] = False
        report["errors"].append("topology_changed")
    elif all(value is True for value in topology_pairs) and mount is not None:
        report["topology_stable"] = True

    supported_root = False
    if root_controllers:
        first_controller, last_controller = root_controllers
        controllers_stable = (None if any(row[1] is None for row in root_controllers)
                              else first_controller[1] == last_controller[1])
        supported_root = (controllers_stable is True and "memory" in first_controller[0]
                          and samples[-1][1][2] == dict.fromkeys(SCALARS, "missing_file")
                          and root_high_last[2] == "missing_file")
        report["visible_root_observation"] = {
            "status": "supported_nonroot_interfaces_absent" if supported_root else "unknown",
            "memory_controller_samples": [None if row[0] is None else "memory" in row[0]
                                          for row in root_controllers],
            "controllers_stable": controllers_stable,
            "controller_errors": [row[2] for row in root_controllers],
            "last_memory_high_error": root_high_last[2],
        }
        if controllers_stable is False:
            report["topology_stable"] = False

    finite_limits, headrooms, stable_shortfalls, limit_stability = [], [], [], []
    for level, (first, last) in enumerate(samples):
        first_values, first_ids, first_errors = first
        last_values, last_ids, last_errors = last
        identity_changed = any(first_ids[name] != last_ids[name]
                               for name in first_ids.keys() & last_ids.keys())
        if identity_changed:
            report["topology_stable"] = False
        limits = [values["memory.max"] for values in (first_values, last_values)]
        limits_equal = None if None in limits else limits[0] == limits[1]
        limit_stability.append(limits_equal)
        root_absent = supported_root and level == len(samples) - 1
        stable = (root_absent or (not first_errors and not last_errors and not identity_changed
                                  and limits_equal is True))
        observed_limits = [value for value in limits if type(value) is int]
        pairs = [values for values in (first_values, last_values)
                 if values["cgroup.type"] == "domain" and type(values["memory.max"]) is int
                 and values["memory.current"] is not None]
        # Missing samples stay unknown; known values remain available as partial diagnostics.
        margin = (max(0, min(values["memory.max"] for values in pairs)
                      - max(values["memory.current"] for values in pairs)) if pairs else None)
        finite_limits.extend(observed_limits)
        if margin is not None:
            headrooms.append(margin)
            if stable and margin < REQUIRED_BYTES:
                stable_shortfalls.append(level)
        report["ancestors"].append({
            "level": level, "samples": [first_values, last_values], "stable": stable,
            "headroom_bytes": margin, "memory_high": highs[level][0],
            "memory_high_error": highs[level][1],
            "sample_errors": [first_errors, last_errors],
            "identity_changed": identity_changed,
            "supported_root_interfaces_absent": root_absent,
        })
    if limit_stability:
        report["limits_stable"] = (False if False in limit_stability else
                                    True if all(value is True for value in limit_stability) else None)
    host_samples = report["host_available_samples_bytes"]
    host_values = [value for value in host_samples if value is not None]
    report["host_available_bytes"] = min(host_values) if host_values else None
    report["visible_limit_bytes"] = min(finite_limits) if finite_limits else None
    report["visible_headroom_bytes"] = min(headrooms) if headrooms else None
    report["visible_shortfall_observed"] = any(value < REQUIRED_BYTES for value in headrooms)
    visible_complete = (bool(ancestors) and report["topology_stable"] is True
                        and all(row["stable"] for row in report["ancestors"]))
    report["observation_complete"] = (
        visible_complete and None not in host_samples and not bounded.exhausted
        and all(error is None or (supported_root and level == len(highs) - 1)
                for level, (_, error) in enumerate(highs)))
    cgroup_shortfall = bool(stable_shortfalls) and report["topology_stable"] is True
    report["known_memory_shortfall"] = cgroup_shortfall or any(value < REQUIRED_BYTES for value in host_values)
    if cgroup_shortfall:
        report["visible_capacity_status"] = "insufficient"
    elif visible_complete:
        report["visible_capacity_status"] = "no_shortfall_observed"
    if report["known_memory_shortfall"]:
        report["status"] = "blocked"
    report["observation_bounds"] = {
        "max_file_reads": MAX_FILE_READS, "file_reads": bounded.file_reads,
        "max_read_calls": MAX_READ_CALLS, "read_calls": bounded.read_calls,
        "max_total_bytes": MAX_TOTAL_BYTES, "bytes_read": bounded.total_bytes,
        "max_path_depth": MAX_PATH_DEPTH, "max_ancestors": MAX_ANCESTORS,
        "max_path_bytes": MAX_PATH_BYTES, "max_mounts": MAX_MOUNTS,
        "max_meminfo_bytes": MAX_MEMINFO_BYTES, "max_membership_bytes": MAX_MEMBERSHIP_BYTES,
        "max_mountinfo_bytes": MAX_MOUNTINFO_BYTES, "max_scalar_bytes": MAX_SCALAR_BYTES,
        "max_json_bytes": MAX_JSON_BYTES,
        "max_seconds": MAX_SECONDS, "exhausted": bounded.exhausted,
    }
    return report


def main(argv=None):
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    try:
        report = observe_capacity()
        body = json.dumps(report, sort_keys=True, allow_nan=False, separators=(",", ":"))
        if len(body.encode("utf-8")) + 1 > MAX_JSON_BYTES:
            raise ObservationError("report_size_limit")
    except Exception:
        report = _base_report()
        report.update(errors=["observation_failed"], exit_code=2)
        body = json.dumps(report, sort_keys=True, allow_nan=False, separators=(",", ":"))
    try:
        print(body)
    except OSError:
        return 2
    return report["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
