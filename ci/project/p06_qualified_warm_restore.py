#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Inspect or restore an already-decrypted qualified-warm retention archive.

The complete archive is verified before creating a fresh private destination.
Restored files remain inert, and every report concerns retention consistency
only. Stop writers first: repeated descriptor identities and hashes detect
observed changes, but do not exclude malicious concurrent same-user writers.
A failed restore retains its owned incomplete output; existence or absence of
the incomplete marker is not a success receipt or an atomic crash transaction.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import unicodedata

sys.dont_write_bytecode = True

import p06_qualified_warm_retention as retention

CONTRACT_ID = "p06-qualified-warm-retention-review-v1"
MANIFEST_NAME = "manifest.json"
PRIVATE_NAME = "private"
INCOMPLETE_NAME = ".restore-incomplete.PRIVATE.json"
CHUNK_BYTES = 64 * 1024
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
_CREATE_FLAGS = os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
_ERROR_CODES = frozenset({"invalid-arguments", "invalid-output-path", "input-output-overlap",
    "output-exists", "output-changed", "output-verification-failed", "short-output-write",
    "retention-rejected", "filesystem-failed", "interrupted", "restore-failed"})


class RestoreError(ValueError):
    """A fixed public diagnostic that never includes retained names or bytes."""

    def __init__(self, code):
        self.code = code if type(code) is str and code in _ERROR_CODES else "restore-failed"
        super().__init__(self.code)


def _require(condition, code):
    if not condition:
        raise RestoreError(code)


def _close_fds(*fds, suppress=False):
    try:
        retention._close_all(fds, os.close, suppress=suppress)
    except KeyboardInterrupt:
        raise RestoreError("interrupted") from None
    except OSError:
        raise RestoreError("filesystem-failed") from None
    except Exception:
        raise RestoreError("restore-failed") from None


def _json_bytes(document):
    return (json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)
            + "\n").encode("utf-8")


def _failure_report(code):
    return {"schema_version": 1, "contract_id": CONTRACT_ID, "outcome": "fail",
        "error_code": code, "retention_verified": False, "restoration_completed": False,
        "native_execution": "not_run", "retained_code_executed": False,
        "origin_authenticated": False, "native_acceptance": False,
        "performance_acceptance": False, "phase_acceptance": False}


_INCOMPLETE_BYTES = _json_bytes({"schema_version": 1, "contract_id": CONTRACT_ID,
    "outcome": "incomplete", "restoration_completed": False,
    "native_execution": "not_run", "retained_code_executed": False,
    "origin_authenticated": False, "native_acceptance": False,
    "performance_acceptance": False, "phase_acceptance": False})


def _absolute(value):
    raw = os.fspath(value)
    _require(type(raw) is str and raw.startswith("/") and raw != "/",
             "invalid-output-path")
    parts = raw[1:].split("/")
    _require(len(raw[1:].encode("utf-8")) <= 4096 and len(parts) <= 128
             and unicodedata.normalize("NFC", raw) == raw
             and not any(ord(char) < 32 or ord(char) == 127 for char in raw)
             and "\\" not in raw and ":" not in raw
             and all(part not in ("", ".", "..") and len(part.encode("utf-8")) <= 255
                     for part in parts), "invalid-output-path")
    return Path(raw)


def _identity(info):
    return info.st_dev, info.st_ino


def _stamp(info):
    return (_identity(info), info.st_mode, info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _open_directory(path):
    fd = os.open("/", _DIRECTORY_FLAGS)
    try:
        identities = [_identity(os.fstat(fd))]
        for part in path.parts[1:]:
            child = os.open(part, _DIRECTORY_FLAGS, dir_fd=fd)
            previous, fd = fd, child
            _close_fds(previous)
            identities.append(_identity(os.fstat(fd)))
        _require(len(set(identities)) == len(identities), "output-changed")
        return fd, tuple(identities)
    except BaseException:
        _close_fds(fd, suppress=True)
        raise


def _overlap(left, right):
    return left == right or left in right.parents or right in left.parents


def _absent(parent_fd, name):
    try:
        os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    raise RestoreError("output-exists")


def _directory_identity(fd, expected):
    info = os.fstat(fd)
    _require(stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700
             and _identity(info) == expected, "output-changed")
    return info


def _mkdir(parent_fd, name):
    os.mkdir(name, mode=0o700, dir_fd=parent_fd)
    before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    fd = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent_fd)
    try:
        _require(stat.S_ISDIR(before.st_mode) and _identity(before) == _identity(os.fstat(fd)),
                 "output-changed")
        os.fchmod(fd, 0o700)
        identity = _identity(os.fstat(fd))
        _directory_identity(fd, identity)
        _require(_identity(os.stat(name, dir_fd=parent_fd, follow_symlinks=False)) == identity,
                 "output-changed")
        return fd, identity
    except BaseException:
        _close_fds(fd, suppress=True)
        raise


def _open_owned_directory(root_fd, directories, relative):
    fd = os.dup(root_fd)
    prefix = ""
    try:
        _directory_identity(fd, directories[""])
        for part in relative.split("/") if relative else ():
            prefix = prefix + "/" + part if prefix else part
            child = os.open(part, _DIRECTORY_FLAGS, dir_fd=fd)
            previous, fd = fd, child
            _close_fds(previous)
            _directory_identity(fd, directories[prefix])
        return fd
    except BaseException:
        _close_fds(fd, suppress=True)
        raise


def _write_all(fd, body):
    remaining = memoryview(body)
    while remaining:
        count = os.write(fd, remaining)
        _require(type(count) is int and 0 < count <= len(remaining), "short-output-write")
        remaining = remaining[count:]


@dataclass(frozen=True)
class _File:
    identity: tuple
    size: int
    sha256: str
    stamp: tuple | None = None


def _verify_file(fd, expected):
    before = os.fstat(fd)
    _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
             and stat.S_IMODE(before.st_mode) == 0o600
             and _identity(before) == expected.identity and before.st_size == expected.size,
             "output-verification-failed")
    _require(expected.stamp is None or _stamp(before) == expected.stamp,
             "output-verification-failed")
    digest = hashlib.sha256()
    offset = 0
    while offset < expected.size:
        chunk = os.pread(fd, min(CHUNK_BYTES, expected.size - offset), offset)
        _require(bool(chunk), "output-verification-failed")
        digest.update(chunk)
        offset += len(chunk)
    _require(not os.pread(fd, 1, offset) and digest.hexdigest() == expected.sha256
             and _stamp(os.fstat(fd)) == _stamp(before), "output-verification-failed")
    return _stamp(before)


def _new_file(root_fd, directories, relative, size, sha256, writer):
    parent, _, name = relative.rpartition("/")
    parent_fd = _open_owned_directory(root_fd, directories, parent)
    fd = None
    completed = False
    try:
        fd = os.open(name, _CREATE_FLAGS, 0o600, dir_fd=parent_fd)
        os.fchmod(fd, 0o600)
        expected = _File(_identity(os.fstat(fd)), size, sha256)
        writer(fd)
        os.fsync(fd)
        expected = replace(expected, stamp=_verify_file(fd, expected))
        _require(_stamp(os.stat(name, dir_fd=parent_fd, follow_symlinks=False)) == expected.stamp,
                 "output-changed")
        completed = True
        return expected
    finally:
        _close_fds(fd, parent_fd, suppress=not completed)


def _bytes_file(root_fd, directories, relative, body):
    return _new_file(root_fd, directories, relative, len(body), hashlib.sha256(body).hexdigest(),
                     lambda fd: _write_all(fd, body))


def _verify_tree(root_fd, directories, files):
    children = {name: set() for name in directories}
    for relative in set(directories).union(files) - {""}:
        parent, _, name = relative.rpartition("/")
        children[parent].add(name)

    def visit(fd, relative):
        before = _directory_identity(fd, directories[relative])
        found = set()
        with os.scandir(fd) as iterator:
            for child in iterator:
                _require(child.name in children[relative] and child.name not in found,
                         "output-verification-failed")
                found.add(child.name)
        _require(found == children[relative], "output-verification-failed")
        for name in sorted(found):
            path = relative + "/" + name if relative else name
            directory = path in directories
            child_fd = os.open(name, _DIRECTORY_FLAGS if directory else _READ_FLAGS, dir_fd=fd)
            completed = False
            try:
                if directory:
                    visit(child_fd, path)
                    _require(_identity(os.stat(name, dir_fd=fd, follow_symlinks=False))
                             == directories[path], "output-changed")
                else:
                    _verify_file(child_fd, files[path])
                    _require(_stamp(os.stat(name, dir_fd=fd, follow_symlinks=False))
                             == files[path].stamp, "output-changed")
                completed = True
            finally:
                _close_fds(child_fd, suppress=not completed)
        _require(_stamp(os.fstat(fd)) == _stamp(before), "output-changed")
        os.fsync(fd)

    visit(root_fd, "")


def _verify_root(output, parent_fd, parent_identities, root_fd, root_identity):
    reopened, identities = _open_directory(output.parent)
    completed = False
    try:
        _require(identities == parent_identities
                 and _identity(os.fstat(reopened)) == _identity(os.fstat(parent_fd)),
                 "output-changed")
        named = os.stat(output.name, dir_fd=reopened, follow_symlinks=False)
        _require(stat.S_ISDIR(named.st_mode) and _identity(named) == root_identity,
                 "output-changed")
        _directory_identity(root_fd, root_identity)
        completed = True
    finally:
        _close_fds(reopened, suppress=not completed)


def _retain_incomplete(root_fd, root_identity):
    fd = None
    try:
        _directory_identity(root_fd, root_identity)
        fd = os.open(INCOMPLETE_NAME, _CREATE_FLAGS, 0o600, dir_fd=root_fd)
        os.fchmod(fd, 0o600)
        _write_all(fd, _INCOMPLETE_BYTES)
        os.fsync(fd)
        os.fsync(root_fd)
    except BaseException:
        # A replacement is never removed, and secondary failures cannot undo
        # the private bytes already retained through the owned descriptor.
        pass
    finally:
        _close_fds(fd, suppress=True)


def restore_archive(archive, expected_sha256, *, expected_revision, output_dir, summary=None):
    """Restore validated bytes into one absent private directory, or fail closed."""
    parent_fd = root_fd = None
    root_identity = None
    completed = False
    try:
        output = _absolute(output_dir)
        with retention.RetentionArchive(archive, expected_sha256,
                expected_revision=expected_revision, summary=summary) as retained:
            inputs = [Path(archive)] + ([Path(summary)] if summary is not None else [])
            _require(all(not _overlap(path, output) for path in inputs), "input-output-overlap")
            input_ancestors = set()
            for path in inputs:
                input_fd, identities = _open_directory(path.parent)
                _close_fds(input_fd)
                input_ancestors.update(identities)
            parent_fd, parent_identities = _open_directory(output.parent)
            input_ancestors.update(parent_identities)
            _absent(parent_fd, output.name)
            retained.assert_unchanged()
            root_fd, root_identity = _mkdir(parent_fd, output.name)
            _require(root_identity not in input_ancestors, "input-output-overlap")
            directories = {"": root_identity}
            directory_identities = {root_identity}
            marker = _bytes_file(root_fd, directories, INCOMPLETE_NAME, _INCOMPLETE_BYTES)
            os.fsync(root_fd)
            os.fsync(parent_fd)
            files = {INCOMPLETE_NAME: marker,
                MANIFEST_NAME: _bytes_file(root_fd, directories, MANIFEST_NAME, retained.manifest_bytes)}
            names = [name for name, entry in retained.entries.items() if entry["directory"]]
            for name in sorted(names, key=lambda value: (value.count("/"), value)):
                relative = PRIVATE_NAME + ("/" + name if name else "")
                parent, _, base = relative.rpartition("/")
                directory_fd = _open_owned_directory(root_fd, directories, parent)
                directory_completed = False
                try:
                    child_fd, identity = _mkdir(directory_fd, base)
                    _close_fds(child_fd)
                    _require(identity not in directory_identities and identity not in input_ancestors,
                             "output-changed")
                    directory_identities.add(identity)
                    directories[relative] = identity
                    directory_completed = True
                finally:
                    _close_fds(directory_fd, suppress=not directory_completed)
            for name, entry in sorted(retained.entries.items()):
                if not entry["directory"]:
                    relative = PRIVATE_NAME + "/" + name
                    files[relative] = _new_file(root_fd, directories, relative,
                        entry["size_bytes"], entry["sha256"],
                        lambda fd, name=name: retained.copy_file(name, fd))
            _verify_tree(root_fd, directories, files)
            retained.assert_unchanged()
            _verify_root(output, parent_fd, parent_identities, root_fd, root_identity)
            _require(_stamp(os.stat(INCOMPLETE_NAME, dir_fd=root_fd, follow_symlinks=False))
                     == marker.stamp, "output-changed")
            os.unlink(INCOMPLETE_NAME, dir_fd=root_fd)
            del files[INCOMPLETE_NAME]
            _verify_tree(root_fd, directories, files)
            retained.assert_unchanged()
            _verify_root(output, parent_fd, parent_identities, root_fd, root_identity)
            os.fsync(parent_fd)
            report = dict(retained.report(), restoration_completed=True)
        completed = True
        return report
    except BaseException as error:
        if root_fd is not None and root_identity is not None:
            _retain_incomplete(root_fd, root_identity)
        if isinstance(error, RestoreError):
            raise
        if isinstance(error, retention.RetentionError):
            raise RestoreError("retention-rejected") from None
        if isinstance(error, KeyboardInterrupt):
            raise RestoreError("interrupted") from None
        if isinstance(error, OSError):
            raise RestoreError("filesystem-failed") from None
        if isinstance(error, Exception):
            raise RestoreError("restore-failed") from None
        raise
    finally:
        _close_fds(root_fd, parent_fd, suppress=not completed)


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise RestoreError("invalid-arguments")


def argument_parser():
    parser = _Parser(prog="p06-qualified-warm-restore", description=__doc__, allow_abbrev=False)
    operations = parser.add_subparsers(dest="operation", required=True, parser_class=_Parser)
    for operation in ("inspect", "restore"):
        child = operations.add_parser(operation, allow_abbrev=False)
        for name in ("archive", "sha256", "expected-revision"):
            child.add_argument("--" + name, required=True)
        child.add_argument("--summary", help="Input public encryption summary; consistency only")
        if operation == "restore":
            child.add_argument("--output-dir", required=True, help="Absent absolute private output directory")
    return parser


def main(argv=None):
    status = 0
    try:
        args = argument_parser().parse_args(argv)
        options = {"expected_revision": args.expected_revision, "summary": args.summary}
        if args.operation == "restore":
            report = restore_archive(args.archive, args.sha256, output_dir=args.output_dir, **options)
        else:
            report = retention.inspect_archive(args.archive, args.sha256, **options)
    except (Exception, KeyboardInterrupt) as error:
        if isinstance(error, RestoreError):
            code = error.code
        elif isinstance(error, retention.RetentionError):
            code = "retention-rejected"
        elif isinstance(error, KeyboardInterrupt):
            code = "interrupted"
        else:
            code = "restore-failed"
        report, status = _failure_report(code), 1
    try:
        sys.stdout.write(_json_bytes(report).decode("utf-8"))
        sys.stdout.flush()
    except (Exception, KeyboardInterrupt):
        return 1
    return status


if __name__ == "__main__":
    sys.exit(main())
