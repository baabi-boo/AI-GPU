#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Preserve a qualified warm attempt as PRIVATE, bounded, inert local bytes.

``package_success`` creates the exact two-root replay ZIP, a separate envelope
of the other evidence, and a separate inventory receipt in a new output_dir.
``package_partial`` preserves only existing evidence, including unfinished or
malformed reports, under an explicitly partial prefix. Extra acquisition or
supervision inputs must be named explicitly in extra_roots (label -> path).

Both APIs require writers_finished=True: the caller must stop and wait for all
writers first. That assertion, finished/cleanup receipts, and repeated file
identities are observations, not hard exclusion of concurrent writers. No
retained code runs, no upload occurs, and no acceptance claim is established.
Raw originals can contain Micron confidential/proprietary source notices and
sensitive machine information. All outputs are PRIVATE; none is a public export.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import zipfile

sys.dont_write_bytecode = True

from baseline_packet_io import load_json_bytes
import p06_dependency_contract as dependency
import p06_qualified_warm_run as runner


CONTRACT_ID = "p06-qualified-warm-private-pack-v1"
ROOTS = ("dependency-build", "qualified-warm")
# Reuse the very same pinned reader and bounds as complete qualified replay.
ARCHIVE = runner.qualified_warm_replay.native.dependency_replay._archive_api()
MAX_ARCHIVE_BYTES = ARCHIVE.ARCHIVE_BYTES
MAX_MEMBER_BYTES = min(dependency.MAX_FILE_BYTES, ARCHIVE.MEMBER_BYTES)
MAX_EXPANDED_BYTES = min(dependency.MAX_PACKET_BYTES, ARCHIVE.EXPANDED_BYTES)
MAX_MEMBERS = ARCHIVE.MEMBER_COUNT
MAX_DIRECTORY_BYTES = ARCHIVE.DIRECTORY_BYTES
MAX_RECEIPT_BYTES = runner.qualified_warm_replay.MAX_REPORT_BYTES
CHUNK_BYTES = 1024 * 1024
ORIGINAL_NAME = "qualified-warm-original.PRIVATE.zip"
ENVELOPE_NAME = "qualified-warm-envelope.PRIVATE.zip"
PARTIAL_NAME = "partial-attempt.PRIVATE.zip"
RECEIPT_NAME = "qualified-warm-pack.PRIVATE.json"
FAILURE_NAME = "packaging-failure.PRIVATE.json"
LIMITATIONS = [
    "PRIVATE local retention only: raw originals may contain Micron confidential/proprietary source notices, raw logs, and sensitive machine information; no upload or public export is performed.",
    "writers_finished is the caller's assertion. Receipt cleanup and repeated source identities do not prove that processes are absent or exclude malicious concurrent writers.",
    "Packaging preserves bytes and checks bounded ZIP structure; it does not perform complete semantic replay, authenticate a producer, or establish native, performance, or phase acceptance.",
    "Partial retention preserves only existing selected evidence. Missing, malformed, unfinished, or failed-cleanup records remain unresolved, and no missing native subtree is fabricated.",
    "Interruption or packaging failure retains created partial bytes and a best-effort private failure receipt; abrupt process death or storage failure can prevent receipt finalization.",
]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _identity(stamp):
    return dict(zip(("device", "inode", "mode", "links", "size_bytes", "mtime_ns", "ctime_ns"), stamp))


def _canonical(value):
    raw = os.fspath(value)
    require(type(raw) is str and raw.startswith("/") and raw != "/",
            "paths must be explicit absolute literals")
    ARCHIVE.relative_name(raw[1:])
    return Path(raw)


def _directory(path):
    """Open every ancestor without following symlinks; the caller owns the fd."""
    path = _canonical(path)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptor = os.open("/", flags)
    try:
        for part in path.parts[1:]:
            child = os.open(part, flags, dir_fd=descriptor)
            parent, descriptor = descriptor, child
            os.close(parent)
        return descriptor
    except BaseException:
        try:
            os.close(descriptor)
        except BaseException:
            pass
        raise


def _overlap(left, right):
    return left == right or left in right.parents or right in left.parents


@dataclass(frozen=True)
class _File:
    source: Path
    name: str
    stamp: tuple
    sha256: str
    size_bytes: int

    def descriptor(self):
        return {"path": self.name, "sha256": self.sha256, "size_bytes": self.size_bytes}


def _close_owned(stream, descriptor, parent, *, suppress):
    failure = None
    for resource, close in ((stream, lambda value: value.close()),
                            (descriptor, os.close), (parent, os.close)):
        if resource is not None:
            try:
                close(resource)
            except BaseException as error:
                if failure is None:
                    failure = error
    if failure is not None and not suppress:
        raise failure


def _read_file(path, *, maximum=None, expected=None, destination=None, contents=False,
               directory_fd=None):
    """Hash/copy the same single-link regular descriptor through a bounded read."""
    maximum = MAX_MEMBER_BYTES if maximum is None else maximum
    parent = _directory(path.parent) if directory_fd is None else os.dup(directory_fd)
    descriptor = stream = None
    failed = False
    try:
        before = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                and 0 <= before.st_size <= maximum, "input is not a bounded single-link regular file")
        stamp = _stamp(before)
        if expected is not None:
            require(stamp == expected.stamp, "source identity changed before reading")
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                             dir_fd=parent)
        digest, count, chunks = hashlib.sha256(), 0, []
        # Raw descriptor ownership survives interrupted stream construction.
        stream = os.fdopen(descriptor, "rb", closefd=False)
        require(_stamp(os.fstat(stream.fileno())) == stamp, "input changed before opening")
        while chunk := stream.read(min(CHUNK_BYTES, maximum + 1 - count)):
            count += len(chunk)
            require(count <= maximum, "input grew beyond its byte bound")
            digest.update(chunk)
            if destination is not None:
                destination.write(chunk)
            if contents:
                chunks.append(chunk)
        require(_stamp(os.fstat(stream.fileno())) == stamp, "input changed during reading")
        require(count == before.st_size
                and _stamp(os.stat(path.name, dir_fd=parent, follow_symlinks=False)) == stamp,
                "source identity changed after reading")
        result = _File(path, "", stamp, digest.hexdigest(), count)
        if expected is not None:
            require((result.sha256, count) == (expected.sha256, expected.size_bytes),
                    "source bytes changed during packaging")
        return result, b"".join(chunks) if contents else None
    except BaseException:
        failed = True
        raise
    finally:
        _close_owned(stream, descriptor, parent, suppress=failed)


def _inventory(selections):
    """Retain every regular file, including hidden and uninterpreted outputs."""
    files, directories, missing = {}, {}, []
    visited = 0
    expanded = 0

    def consume(path, name, info):
        nonlocal visited, expanded
        ARCHIVE.relative_name(name)
        visited += 1
        # Include directories in a traversal budget; empty directory forests
        # cannot bypass the existing per-archive entry bound.
        require(visited <= 2 * MAX_MEMBERS, "selected trees exceed their traversal bound")
        if stat.S_ISDIR(info.st_mode):
            descriptor = _directory(path)
            try:
                before = _stamp(info)
                require(_stamp(os.fstat(descriptor)) == before, "directory changed before scanning")
                children = []
                with os.scandir(descriptor) as scan:
                    for child in scan:
                        require(len(children) + visited < 2 * MAX_MEMBERS,
                                "selected trees exceed their traversal bound")
                        children.append((child.name, child.stat(follow_symlinks=False)))
                for child, child_info in sorted(children):
                    consume(path / child, name + "/" + child, child_info)
                require(_stamp(os.fstat(descriptor)) == before
                        and _stamp(path.lstat()) == before, "directory changed while scanning")
                directories[str(path)] = before
            finally:
                os.close(descriptor)
        else:
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
                    "links and special files cannot be packaged")
            require(name not in files, "duplicate archive path")
            row, _ = _read_file(path)
            require(row.stamp == _stamp(info), "file changed during inventory")
            files[name] = _File(path, name, row.stamp, row.sha256, row.size_bytes)
            expanded += row.size_bytes
            require(expanded <= 2 * MAX_EXPANDED_BYTES, "selected evidence exceeds its total byte bound")

    for name, path in sorted(selections.items()):
        ARCHIVE.relative_name(name)
        # Validate ancestors even when the selected leaf is missing.
        try:
            parent = _directory(path.parent)
        except FileNotFoundError:
            missing.append(name)
            continue
        try:
            try:
                info = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                missing.append(name)
                continue
            consume(path, name, info)
        finally:
            os.close(parent)
    return files, directories, missing


def _read_document(row, *, warm=False):
    maximum = runner.qualified_warm_replay.MAX_REPORT_BYTES if warm else dependency.MAX_RECEIPT_BYTES
    _, raw = _read_file(row.source, maximum=maximum, expected=row, contents=True)
    value = (runner.qualified_warm_replay.decode_report(raw) if warm
             else load_json_bytes(raw, "private packaging input report"))
    require(type(value) is dict, "report must be an object")
    return value


def _writer_observations(files, *, success, source, workspace):
    documents, unresolved = {}, []
    for relative in (runner.RECEIPT_PATH, "dependency-preparation.json",
                     "dependency-build/report.json", "qualified-warm/report.json"):
        row = files.get("evidence/" + relative)
        if row is None:
            unresolved.append({"report": relative, "observation": "missing"})
            continue
        try:
            document = _read_document(row, warm=relative == "qualified-warm/report.json")
        except (ValueError, UnicodeError, KeyError, TypeError, RecursionError):
            unresolved.append({"report": relative, "observation": "malformed"})
            continue
        documents[relative] = document
        if relative != "dependency-preparation.json" and document.get("state") != "finished":
            unresolved.append({"report": relative, "observation": "unfinished"})
        key = "stages" if relative == runner.RECEIPT_PATH else "commands"
        commands = document.get(key, [])
        if type(commands) is not list or (success and relative != "dependency-preparation.json" and not commands):
            unresolved.append({"report": relative, "observation": "malformed-command-list"})
            continue
        for index, command in enumerate(commands):
            if type(command) is not dict or type(command.get("process_started")) is not bool \
                    or (command.get("process_started") is True and command.get("cleanup_complete") is not True):
                unresolved.append({"report": relative, "command_index": index,
                                   "observation": "cleanup-unresolved"})
    if not success:
        return {"caller_asserted_writers_finished": True, "finished_cleanup_records_verified": False,
                "unresolved": unresolved, "hard_writer_exclusion_established": False}
    require(not unresolved, "success packaging requires finished reports and complete cleanup")
    report = documents[runner.RECEIPT_PATH]
    require(report.get("contract_id") == runner.CONTRACT_ID and type(report.get("schema_version")) is int
            and report.get("schema_version") == 1
            and report.get("source_dir") == str(source) and report.get("workspace_dir") == str(workspace)
            and report.get("outcome") == "pass" and report.get("orchestration_passed") is True
            and report.get("reason") is None and report.get("failures") == [],
            "success packaging requires a matching finished orchestration receipt")
    require(all(report.get(name) is True for name in
                ("source_stable", "selected_sources_stable", "inputs_stable")),
            "orchestration source/input stability was not established")
    retained_sources = report.get("selected_sources_before")
    observed_sources = report.get("selected_sources_after")
    require(type(retained_sources) is list and 0 < len(retained_sources) <= runner.MAX_SOURCE_FILES
            and type(observed_sources) is list and retained_sources == observed_sources,
            "orchestration selected helper inventory is missing or changed")
    for descriptors in (retained_sources, observed_sources):
        require(all(type(descriptor) is dict and type(descriptor.get("size_bytes")) is int
                    for descriptor in descriptors)
                and tuple(descriptor.get("path") for descriptor in descriptors) == runner.SOURCE_FILES,
                "orchestration selected helper population or descriptors differ")
    for descriptor in retained_sources:
        relative = ARCHIVE.relative_name(descriptor.get("path"))
        row = files.get("evidence/" + runner.SOURCE_ROOT + "/" + relative)
        require(row is not None and descriptor == dict(row.descriptor(), path=relative),
                "retained orchestration helper differs from its original")
    stages = report.get("stages")
    require(type(stages) is list and [row.get("id") for row in stages] == list(runner.STAGE_NAMES),
            "orchestration stage population differs")
    for stage in stages:
        require(type(stage.get("finished_at")) is str and stage["finished_at"]
                and stage.get("process_started") is True
                and stage.get("cleanup_complete") is True and stage.get("outcome") == "pass"
                and type(stage.get("exit_code")) is int and stage["exit_code"] == 0,
                "orchestration stage is unfinished or unsuccessful")
        expected = runner.LOG_ROOT + "/" + stage["id"] + ".log"
        row = files.get("evidence/" + expected)
        require(row is not None and stage.get("log") == expected
                and stage.get("raw_log") == dict(row.descriptor(), path=expected),
                "orchestration raw log is absent or differs from its receipt")
    descriptors = report.get("reports")
    require(type(descriptors) is dict and 3 <= len(descriptors) <= dependency.MAX_RECORDS,
            "orchestration report descriptors are absent or unbounded")
    for descriptor in descriptors.values():
        require(type(descriptor) is dict, "invalid orchestration report descriptor")
        relative = ARCHIVE.relative_name(descriptor.get("path"))
        row = files.get("evidence/" + relative)
        require(row is not None and descriptor == dict(row.descriptor(), path=relative),
                "orchestration report bytes differ from their receipt")
    for stage, relative in (("preparation", "dependency-preparation.json"),
                            ("dependency-build", "dependency-build/report.json"),
                            ("qualified-warm", "qualified-warm/report.json")):
        require(descriptors.get(stage, {}).get("path") == relative,
                "orchestration report selection differs")
        document = documents[relative]
        require(document.get("outcome") == "pass" and document.get("reason") is None
                and document.get("failures") == [], "selected stage did not finish successfully")
    for field, relative in (("dependency_receipt_sha256", "dependency-build/report.json"),
                            ("qualified_warm_report_sha256", "qualified-warm/report.json")):
        require(report.get(field) == files["evidence/" + relative].sha256,
                "orchestration raw report pin differs")
    return {"caller_asserted_writers_finished": True, "finished_cleanup_records_verified": True,
            "unresolved": [], "hard_writer_exclusion_established": False}


class _BoundedOutput:
    def __init__(self, stream):
        self.stream = stream

    def write(self, body):
        require(self.stream.tell() + len(body) <= MAX_ARCHIVE_BYTES,
                "ZIP exceeds the existing compressed byte bound")
        return self.stream.write(body)

    def __getattr__(self, name):
        return getattr(self.stream, name)


@contextmanager
def _exclusive(path, *, directory_fd=None):
    parent = _directory(path.parent) if directory_fd is None else os.dup(directory_fd)
    descriptor = stream = None
    failed = False
    try:
        descriptor = os.open(path.name, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC,
                             0o600, dir_fd=parent)
        stream = os.fdopen(descriptor, "w+b", closefd=False)
        yield stream
    except BaseException:
        failed = True
        raise
    finally:
        _close_owned(stream, descriptor, parent, suppress=failed)


def _write_zip(path, members):
    require(0 < len(members) <= MAX_MEMBERS, "ZIP member population is empty or exceeds its bound")
    require(sum(row.size_bytes for row in members.values()) <= MAX_EXPANDED_BYTES,
            "ZIP exceeds the existing expanded byte bound")
    require(sum(46 + len(name.encode("utf-8")) for name in members) <= MAX_DIRECTORY_BYTES,
            "ZIP exceeds the existing central directory byte bound")
    with _exclusive(path) as stream:
        with zipfile.ZipFile(_BoundedOutput(stream), "w", compression=zipfile.ZIP_DEFLATED,
                             allowZip64=False) as archive:
            for name, row in sorted(members.items()):
                ARCHIVE.relative_name(name)
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o600) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                info.file_size = row.size_bytes
                with archive.open(info, "w", force_zip64=False) as member:
                    _read_file(row.source, expected=row, destination=member)
        stream.flush()
        os.fsync(stream.fileno())


def _verify_zip(path, members, final_name):
    row, _ = _read_file(path, maximum=MAX_ARCHIVE_BYTES)
    with ARCHIVE.ArchiveReader(path, row.sha256) as archive:
        require(tuple(archive.files()) == tuple(sorted(members)), "ZIP has missing, duplicate, or extra members")
        for name, expected in sorted(members.items()):
            observed = archive.identity(name, limit=MAX_MEMBER_BYTES)
            require(observed == dict(expected.descriptor(), path=name), "ZIP member differs from its original")
    return {"filename": final_name, "sha256": row.sha256, "size_bytes": row.size_bytes,
            "member_count": len(members), "expanded_bytes": sum(item.size_bytes for item in members.values()),
            "members": [dict(item.descriptor(), path=name, source_identity=_identity(item.stamp))
                        for name, item in sorted(members.items())],
            "all_members_rehashed_against_original": True, "zip_crc_verified": True}


def _write_receipt(path, document, *, directory_fd=None):
    raw = (json.dumps(document, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    require(len(raw) <= MAX_RECEIPT_BYTES, "packaging receipt exceeds its byte bound")
    with _exclusive(path, directory_fd=directory_fd) as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _publish(source, target):
    # link is an atomic no-clobber publication on this same new output directory.
    os.link(source, target, follow_symlinks=False)
    source.unlink()


def _package(*, source_dir, workspace_dir, output_dir, writers_finished=False,
             extra_roots=None, partial=False):
    require(writers_finished is True, "the caller must stop and wait for all writers before packaging")
    source, workspace, output = map(_canonical, (source_dir, workspace_dir, output_dir))
    require(not _overlap(source, workspace), "source and workspace overlap")
    source_fd = _directory(source)
    os.close(source_fd)
    selections = {"evidence": workspace / "evidence"}
    require(extra_roots is None or type(extra_roots) is dict, "extra roots must be an explicit label-to-path mapping")
    for label, path in (extra_roots or {}).items():
        ARCHIVE.relative_name(label)
        require("/" not in label, "extra evidence labels must be single path components")
        selections["additional-evidence/" + label] = _canonical(path)
    roots = list(selections.values())
    require(all(not _overlap(left, right) for index, left in enumerate(roots) for right in roots[index + 1:]),
            "selected evidence roots overlap")
    require(all(not _overlap(source, path) for path in roots), "selected evidence overlaps source")
    require(all(not _overlap(output, path) for path in (source, workspace, *roots)),
            "output overlaps source, workspace, or selected evidence")
    parent = _directory(output.parent)
    output_fd = None
    try:
        try:
            os.mkdir(output.name, mode=0o700, dir_fd=parent)
            output_fd = os.open(output.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                dir_fd=parent)
        finally:
            os.close(parent)
    except BaseException:
        if output_fd is not None:
            try:
                os.close(output_fd)
            except BaseException:
                pass
        raise
    created, published = [], []
    output_identity = None

    def check_output():
        descriptor = _directory(output)
        try:
            require(_stamp(os.fstat(descriptor))[:3] == output_identity,
                    "packaging output directory changed")
        finally:
            os.close(descriptor)

    def withdraw(target, temporary=None):
        # A renamed/replaced output pathname must not redirect recovery into
        # another directory. Keep the originally opened directory available
        # for best-effort reclassification and the private failure receipt.
        try:
            check_output()
        except (OSError, ValueError):
            if temporary is not None:
                os.link(target.name, temporary.name, src_dir_fd=output_fd, dst_dir_fd=output_fd,
                        follow_symlinks=False)
            os.unlink(target.name, dir_fd=output_fd)
        else:
            if temporary is None:
                target.unlink()
            else:
                _publish(target, temporary)

    def publish(temporary, target):
        check_output()
        info = temporary.lstat()
        # Record ownership before linking: interruption can leave both names,
        # or only the target, even when _publish has not returned.
        published.append((target, temporary, (info.st_dev, info.st_ino)))
        _publish(temporary, target)
        check_output()

    # Track this invocation even when its caller is handling another error.
    package_failed = False
    stage = "inventory"
    try:
        output_identity = _stamp(os.fstat(output_fd))[:3]
        before = _inventory(selections)
        check_output()
        files, _, missing = before
        require(files, "there is no existing selected evidence to preserve")
        if not partial:
            require(not missing, "success packaging is missing a selected evidence root")
            for name in ROOTS:
                require(str(workspace / "evidence" / name) in before[1], "success packet root is absent or not a directory")
        stage = "writer-observations"
        writers = _writer_observations(files, success=not partial, source=source, workspace=workspace)
        if partial:
            groups = {PARTIAL_NAME: {"partial-attempt/" + name: row for name, row in files.items()}}
        else:
            original, envelope = {}, {}
            for name, row in files.items():
                if any(name.startswith("evidence/" + root + "/") for root in ROOTS):
                    original[name.removeprefix("evidence/")] = row
                else:
                    envelope[name] = row
            require({name.split("/")[0] for name in original} == set(ROOTS), "success ZIP roots differ")
            groups = {ORIGINAL_NAME: original, ENVELOPE_NAME: envelope}
        archives = []
        for name, members in groups.items():
            check_output()
            temporary = output / ("incomplete-" + name)
            created.append(temporary)
            stage = "write-" + name
            _write_zip(temporary, members)
            check_output()
            stage = "verify-" + name
            archives.append(_verify_zip(temporary, members, name))
            check_output()
        stage = "final-source-inventory"
        require(_inventory(selections) == before, "selected source identities or bytes changed during packaging")
        check_output()
        receipt = {"schema_version": 1, "contract_id": CONTRACT_ID, "classification": "PRIVATE",
            "scope": "local-byte-preserving-retention-only", "outcome": "pass", "packaging_passed": True,
            "attempt_kind": "partial-attempt" if partial else "finished-success-original",
            "complete_replay_original_created": not partial, "partial_attempt": partial,
            "native_execution": "not_run", "retained_code_executed": False, "origin_authenticated": False,
            "writer_observations": writers, "missing_selected_roots": missing,
            "original_rehashed_after_packaging": True, "source_identities_stable": True,
            "archives": archives, "limits": {"archive_bytes": MAX_ARCHIVE_BYTES,
                "expanded_bytes_per_archive": MAX_EXPANDED_BYTES, "member_bytes": MAX_MEMBER_BYTES,
                "members_per_archive": MAX_MEMBERS, "directory_bytes": MAX_DIRECTORY_BYTES},
            **dict.fromkeys(runner.qualification.FALSE_CLAIMS, False), "limitations": list(LIMITATIONS)}
        stage = "write-inventory-receipt"
        receipt_temporary = output / ("incomplete-" + RECEIPT_NAME)
        _write_receipt(receipt_temporary, receipt)
        check_output()
        stage = "publish"
        for temporary, archive in zip(created, archives):
            target = output / archive["filename"]
            publish(temporary, target)
            # Publication changes filesystem metadata, never ZIP bytes. Rehash
            # the final single-link pathname before publishing its receipt.
            final, _ = _read_file(target, maximum=MAX_ARCHIVE_BYTES)
            require((final.sha256, final.size_bytes) == (archive["sha256"], archive["size_bytes"]),
                    "ZIP bytes changed after verification")
        publish(receipt_temporary, output / RECEIPT_NAME)
        return receipt
    except BaseException as error:
        package_failed = True
        # Never remove an original source or an incomplete ZIP. Reclassify any
        # just-published bytes as incomplete, without replacing another file.
        receipt_withdrawal_unresolved = False
        for target, temporary, identity in reversed(published):
            try:
                info = os.stat(target.name, dir_fd=output_fd, follow_symlinks=False)
                if (info.st_dev, info.st_ino) != identity:
                    continue
                try:
                    original = os.stat(temporary.name, dir_fd=output_fd, follow_symlinks=False)
                except FileNotFoundError:
                    withdraw(target, temporary)
                else:
                    if (original.st_dev, original.st_ino) == identity:
                        withdraw(target)
            except OSError:
                pass
            if target.name == RECEIPT_NAME:
                try:
                    info = os.stat(target.name, dir_fd=output_fd, follow_symlinks=False)
                    receipt_withdrawal_unresolved = (info.st_dev, info.st_ino) == identity
                except FileNotFoundError:
                    pass
                except OSError:
                    receipt_withdrawal_unresolved = True
                # A surviving owned receipt still names the verified final
                # archives. Keep those names unless its withdrawal is observed.
                if receipt_withdrawal_unresolved:
                    break
        retained = []
        retained_paths = [(path, None) for path in created]
        if receipt_withdrawal_unresolved:
            retained_paths.extend((target, identity) for target, _, identity in published
                                  if target.name != RECEIPT_NAME)
        for path, owned_identity in retained_paths:
            try:
                os.stat(path.name, dir_fd=output_fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            row = {"filename": path.name, "complete_replay_verified": False}
            try:
                identity, _ = _read_file(path, maximum=MAX_ARCHIVE_BYTES, directory_fd=output_fd)
                if owned_identity is not None and identity.stamp[:2] != owned_identity:
                    continue
                row.update(sha256=identity.sha256, size_bytes=identity.size_bytes)
            except (OSError, ValueError):
                row["identity_observation"] = "unresolved"
            retained.append(row)
        failure = {"schema_version": 1, "contract_id": CONTRACT_ID, "classification": "PRIVATE",
            "scope": "incomplete-local-packaging-only", "outcome": "fail", "packaging_passed": False,
            "partial_attempt": True, "complete_replay_original_created": False, "stage": stage,
            "error_type": type(error).__name__, "native_execution": "not_run", "retained_code_executed": False,
            "caller_asserted_writers_finished": True, "source_identities_stable": False,
            "published_receipt_withdrawal_unresolved": receipt_withdrawal_unresolved,
            "created_files": retained,
            **dict.fromkeys(runner.qualification.FALSE_CLAIMS, False), "limitations": list(LIMITATIONS)}
        try:
            _write_receipt(output / FAILURE_NAME, failure, directory_fd=output_fd)
        except (OSError, ValueError):
            pass
        raise
    finally:
        try:
            os.close(output_fd)
        except BaseException:
            # A failed close may have consumed the descriptor; never retry it.
            if not package_failed:
                raise


def package_success(*, source_dir, workspace_dir, output_dir, writers_finished=False, extra_roots=None):
    """Create a PRIVATE original, separate evidence envelope, and receipt, exclusively."""
    return _package(source_dir=source_dir, workspace_dir=workspace_dir, output_dir=output_dir,
                    writers_finished=writers_finished, extra_roots=extra_roots, partial=False)


def package_partial(*, source_dir, workspace_dir, output_dir, writers_finished=False, extra_roots=None):
    """Preserve existing evidence only; unfinished producer records remain unresolved."""
    return _package(source_dir=source_dir, workspace_dir=workspace_dir, output_dir=output_dir,
                    writers_finished=writers_finished, extra_roots=extra_roots, partial=True)


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("success", "partial"))
    for flag in ("source-dir", "workspace-dir", "output-dir"):
        parser.add_argument("--" + flag, required=True)
    parser.add_argument("--writers-finished", action="store_true", required=True,
                        help="Assert that the caller has stopped and waited for all evidence writers.")
    parser.add_argument("--extra-root", action="append", default=[], metavar="LABEL=ABSOLUTE_PATH",
                        help="Preserve this explicit acquisition/supervision evidence root; repeat as needed.")
    return parser


def main(argv=None):
    args = argument_parser().parse_args(argv)
    try:
        roots = {}
        for value in args.extra_root:
            label, separator, path = value.partition("=")
            require(separator and label not in roots, "extra root labels must be explicit and unique")
            roots[label] = path
        action = package_success if args.mode == "success" else package_partial
        receipt = action(source_dir=args.source_dir, workspace_dir=args.workspace_dir,
                         output_dir=args.output_dir, writers_finished=args.writers_finished, extra_roots=roots)
        print(json.dumps({"contract_id": CONTRACT_ID, "classification": "PRIVATE", "outcome": "pass",
                          "packaging_passed": True, "partial_attempt": receipt["partial_attempt"],
                          "artifact_count": len(receipt["archives"])}, sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError, KeyboardInterrupt):
        print(json.dumps({"contract_id": CONTRACT_ID, "classification": "PRIVATE", "outcome": "fail",
                          "packaging_passed": False, "reason": "Packaging failed; inspect private local evidence."},
                         sort_keys=True))
        return 1


if __name__ == "__main__":
    sys.exit(main())
