#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Verify the producer's bounded plaintext retention tar without extracting it.

The selected digest and revision bind this inspection to caller-selected bytes;
they do not authenticate a producer or qualify retained native results. Stop
writers first. Repeated descriptor, path and digest observations detect changes
but cannot exclude every malicious concurrent writer.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tarfile
import unicodedata

from p06_qualified_warm_encrypt import (
    CHUNK_BYTES, CONTRACT_ID as RETENTION_CONTRACT_ID, MAX_DEPTH, MAX_ENTRIES,
    MAX_FILE_BYTES, MAX_INPUT_BYTES, MAX_MANIFEST_BYTES, MAX_PATH_BYTES,
)


CONTRACT_ID = "p06-qualified-warm-retention-review-v1"
MAX_ARCHIVE_BYTES = (MAX_INPUT_BYTES + MAX_MANIFEST_BYTES
                     + MAX_ENTRIES * 6144 + 2 * tarfile.RECORDSIZE)
MAX_SUMMARY_BYTES = 64 * 1024
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_REVISION = re.compile(r"[0-9a-f]{40}\Z")
ERROR_CODES = frozenset({
    "invalid-argument", "noncanonical-path", "archive-unavailable", "archive-type",
    "archive-byte-limit", "archive-changed", "archive-read", "archive-sha256",
    "archive-format", "manifest-format", "manifest-schema", "manifest-byte-limit",
    "entry-limit", "path-alias", "parent-missing", "file-limit", "input-byte-limit",
    "revision-mismatch", "file-sha256", "summary-unavailable", "summary-type",
    "summary-byte-limit", "summary-read", "summary-format", "summary-mismatch",
    "summary-changed", "reader-state", "unknown-file", "copy-output", "copy-failed",
    "retention-invalid",
})


class RetentionError(ValueError):
    """A fixed public diagnostic that never contains retained bytes or paths."""

    def __init__(self, code):
        self.code = code if type(code) is str and code in ERROR_CODES else "retention-invalid"
        super().__init__(self.code)


def _require(condition, code):
    if not condition:
        raise RetentionError(code)


def _relative(name):
    _require(type(name) is str and name, "noncanonical-path")
    try:
        encoded = name.encode("utf-8", "strict")
    except UnicodeError:
        raise RetentionError("noncanonical-path") from None
    parts = name.split("/")
    _require(len(encoded) <= MAX_PATH_BYTES and len(parts) <= MAX_DEPTH
             and unicodedata.normalize("NFC", name) == name
             and not any(ord(char) < 32 or ord(char) == 127 for char in name)
             and "\\" not in name and ":" not in name
             and all(part not in ("", ".", "..") and len(part.encode("utf-8")) <= 255
                     for part in parts), "noncanonical-path")


def _canonical(value):
    try:
        raw = os.fspath(value)
    except TypeError:
        raise RetentionError("noncanonical-path") from None
    _require(type(raw) is str and raw.startswith("/") and raw != "/", "noncanonical-path")
    _relative(raw[1:])
    return Path(raw)


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _directory(path):
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open("/", flags)
    identities = []
    try:
        identities.append(_stamp(os.fstat(fd))[:2])
        for part in path.parts[1:]:
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
            identities.append(_stamp(os.fstat(fd))[:2])
        return fd, identities
    except BaseException:
        os.close(fd)
        raise


class _Input:
    def __init__(self, path, kind, maximum):
        self.path, self.kind = path, kind
        self.fd = self.parent = None
        try:
            self.parent, self.ancestors = _directory(path.parent)
            before = os.stat(path.name, dir_fd=self.parent, follow_symlinks=False)
            _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1, kind + "-type")
            _require(0 < before.st_size <= maximum, kind + "-byte-limit")
            self.identity = _stamp(before)
            self.size = before.st_size
            self.fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                              | os.O_CLOEXEC, dir_fd=self.parent)
            self.assert_identity()
        except BaseException as error:
            self.close()
            if isinstance(error, OSError):
                raise RetentionError(kind + "-unavailable") from None
            raise

    def assert_identity(self):
        parent = None
        try:
            parent, ancestors = _directory(self.path.parent)
            _require(ancestors == self.ancestors
                     and _stamp(os.fstat(self.fd)) == self.identity
                     and _stamp(os.stat(self.path.name, dir_fd=parent,
                                        follow_symlinks=False)) == self.identity,
                     self.kind + "-changed")
        except OSError:
            raise RetentionError(self.kind + "-changed") from None
        finally:
            if parent is not None:
                os.close(parent)

    def blocks(self, offset, length):
        _require(0 <= offset <= self.size and 0 <= length <= self.size - offset,
                 self.kind + "-read")
        try:
            while length:
                body = os.pread(self.fd, min(length, CHUNK_BYTES), offset)
                _require(body, self.kind + "-read")
                yield body
                length -= len(body)
                offset += len(body)
        except OSError:
            raise RetentionError(self.kind + "-read") from None

    def verify_digest(self, expected):
        self.assert_identity()
        digest = hashlib.sha256()
        for body in self.blocks(0, self.size):
            digest.update(body)
        self.assert_eof()
        _require(digest.hexdigest() == expected, self.kind + "-changed")
        self.assert_identity()

    def assert_eof(self):
        try:
            _require(os.pread(self.fd, 1, self.size) == b"", self.kind + "-changed")
        except OSError:
            raise RetentionError(self.kind + "-changed") from None

    def close(self):
        for attribute in ("fd", "parent"):
            fd = getattr(self, attribute)
            if fd is not None:
                setattr(self, attribute, None)
                os.close(fd)


def _json_bytes(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True, allow_nan=False) + "\n").encode("utf-8")


def _json(body, code):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, code)
            result[key] = value
        return result

    def reject_number(value):
        raise RetentionError(code)

    try:
        return json.loads(body.decode("utf-8", "strict"), object_pairs_hook=unique,
                          parse_float=reject_number, parse_constant=reject_number)
    except (UnicodeError, ValueError, RecursionError):
        raise RetentionError(code) from None


@dataclass(frozen=True)
class _Entry:
    directory: bool
    size_bytes: int = 0
    sha256: str | None = None
    offset: int | None = None


def _manifest(body, expected_revision):
    value = _json(body, "manifest-format")
    _require(type(value) is dict and set(value) == {
        "schema_version", "contract_id", "expected_revision", "directories", "files",
    }, "manifest-schema")
    _require(type(value["schema_version"]) is int and value["schema_version"] == 1
             and value["contract_id"] == RETENTION_CONTRACT_ID, "manifest-schema")
    revision = value["expected_revision"]
    _require(revision is None or type(revision) is str and _REVISION.fullmatch(revision),
             "manifest-schema")
    _require(revision == expected_revision, "revision-mismatch")
    directories, files = value["directories"], value["files"]
    _require(type(directories) is list and type(files) is list, "manifest-schema")
    _require(1 <= len(directories) + len(files) <= MAX_ENTRIES, "entry-limit")
    _require(directories and directories[0] == "" and all(type(name) is str for name in directories),
             "manifest-schema")
    _require(directories == sorted(directories), "manifest-schema")
    entries, folded = {}, set()

    def add(name, entry):
        if name:
            _relative(name)
        _require(name not in entries and name.casefold() not in folded, "path-alias")
        entries[name] = entry
        folded.add(name.casefold())

    for name in directories:
        add(name, _Entry(True))
    total, previous = 0, None
    for item in files:
        _require(type(item) is dict and set(item) == {"path", "size_bytes", "sha256"},
                 "manifest-schema")
        name, size, digest = item["path"], item["size_bytes"], item["sha256"]
        _relative(name)
        _require(type(size) is int and 0 <= size <= MAX_FILE_BYTES, "file-limit")
        _require(type(digest) is str and _DIGEST.fullmatch(digest), "manifest-schema")
        _require(previous is None or previous < name, "manifest-schema")
        total += size
        _require(total <= MAX_INPUT_BYTES, "input-byte-limit")
        add(name, _Entry(False, size, digest))
        previous = name
    for name in entries:
        _require(not name or name.rpartition("/")[0] in entries
                 and entries[name.rpartition("/")[0]].directory, "parent-missing")
    _require(_json_bytes(value) == body, "manifest-format")
    return value, entries, total


def _header(name, size=0, directory=False):
    info = tarfile.TarInfo(name)
    info.type = tarfile.DIRTYPE if directory else tarfile.REGTYPE
    info.mode = 0o700 if directory else 0o600
    info.size, info.mtime = size, 0
    return info.tobuf(format=tarfile.PAX_FORMAT, encoding="utf-8", errors="strict")


def _member_header(name, entry):
    return _header("private" + ("/" + name if name else ""), entry.size_bytes, entry.directory)


class RetentionArchive:
    """Keep one fully validated, no-follow regular archive open for bounded copies."""

    def __init__(self, archive, expected_sha256, *, expected_revision, summary=None):
        _require(type(expected_sha256) is str and _DIGEST.fullmatch(expected_sha256),
                 "invalid-argument")
        _require(type(expected_revision) is str and _REVISION.fullmatch(expected_revision),
                 "invalid-argument")
        self.archive_path = _canonical(archive)
        self.summary_path = _canonical(summary) if summary is not None else None
        self.expected_sha256, self.expected_revision = expected_sha256, expected_revision
        self._archive = self._summary = None
        self._validated = False

    def __enter__(self):
        _require(self._archive is None and not self._validated, "reader-state")
        try:
            self._archive = _Input(self.archive_path, "archive", MAX_ARCHIVE_BYTES)
            self._validate_archive()
            if self.summary_path is not None:
                self._validate_summary()
            self._archive.assert_identity()
            self._validated = True
            return self
        except BaseException:
            self.close()
            raise

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            if exc_type is None:
                self.assert_unchanged()
        finally:
            self.close()

    def close(self):
        self._validated = False
        for attribute in ("_summary", "_archive"):
            source = getattr(self, attribute)
            if source is not None:
                setattr(self, attribute, None)
                source.close()

    def _ready(self):
        _require(self._validated and self._archive is not None, "reader-state")

    def _consume(self, length):
        for body in self._archive.blocks(self._offset, length):
            self._offset += len(body)
            self._digest.update(body)
            yield body

    def _take(self, length):
        return b"".join(self._consume(length))

    def _zeros(self, length):
        for body in self._consume(length):
            _require(body == bytes(len(body)), "archive-format")

    def _validate_archive(self):
        self._offset, self._digest = 0, hashlib.sha256()
        first = self._take(tarfile.BLOCKSIZE)
        size_field = first[124:136]
        _require(re.fullmatch(rb"[0-7]{11}\x00", size_field), "archive-format")
        manifest_size = int(size_field[:-1], 8)
        _require(0 < manifest_size <= MAX_MANIFEST_BYTES, "manifest-byte-limit")
        _require(first == _header("manifest.json", manifest_size), "archive-format")
        self._manifest_bytes = self._take(manifest_size)
        self._zeros(-manifest_size % tarfile.BLOCKSIZE)
        self._manifest, self._entries, self._input_bytes = _manifest(
            self._manifest_bytes, self.expected_revision)
        size = tarfile.BLOCKSIZE + manifest_size + (-manifest_size % tarfile.BLOCKSIZE) + 1024
        for name, entry in self._entries.items():
            size += len(_member_header(name, entry)) + entry.size_bytes
            size += -entry.size_bytes % tarfile.BLOCKSIZE
        size += -size % tarfile.RECORDSIZE
        _require(self._archive.size == size, "archive-format")
        for name, entry in sorted(self._entries.items()):
            expected = _member_header(name, entry)
            _require(self._take(len(expected)) == expected, "archive-format")
            if not entry.directory:
                offset, digest = self._offset, hashlib.sha256()
                for body in self._consume(entry.size_bytes):
                    digest.update(body)
                _require(digest.hexdigest() == entry.sha256, "file-sha256")
                self._entries[name] = _Entry(False, entry.size_bytes, entry.sha256, offset)
                self._zeros(-entry.size_bytes % tarfile.BLOCKSIZE)
        _require(size - self._offset >= 1024, "archive-format")
        self._zeros(size - self._offset)
        _require(self._digest.hexdigest() == self.expected_sha256, "archive-sha256")
        self._archive.assert_eof()

    def _validate_summary(self):
        self._summary = _Input(self.summary_path, "summary", MAX_SUMMARY_BYTES)
        body = b"".join(self._summary.blocks(0, self._summary.size))
        value = _json(body, "summary-format")
        _require(type(value) is dict and set(value) == {
            "schema_version", "contract_id", "expected_revision", "outcome", "encryption_passed",
            "file_count", "directory_count", "input_bytes", "ciphertext_bytes", "ciphertext_sha256",
        }, "summary-format")
        _require(type(value["schema_version"]) is int and value["schema_version"] == 1
                 and value["contract_id"] == RETENTION_CONTRACT_ID
                 and value["outcome"] == "pass" and value["encryption_passed"] is True
                 and all(type(value[key]) is int for key in (
                     "file_count", "directory_count", "input_bytes", "ciphertext_bytes"))
                 and 0 < value["ciphertext_bytes"] <= MAX_ARCHIVE_BYTES
                     + ((MAX_ARCHIVE_BYTES + 65535) // 65536) * 16 + 4096
                 and type(value["ciphertext_sha256"]) is str
                 and _DIGEST.fullmatch(value["ciphertext_sha256"]), "summary-format")
        _require(value["expected_revision"] == self.expected_revision
                 and value["file_count"] == len(self._manifest["files"])
                 and value["directory_count"] == len(self._manifest["directories"])
                 and value["input_bytes"] == self._input_bytes, "summary-mismatch")
        self._summary_digest = hashlib.sha256(body).hexdigest()
        self._summary.assert_eof()
        self._summary.assert_identity()

    @property
    def manifest(self):
        self._ready()
        return copy.deepcopy(self._manifest)

    @property
    def manifest_bytes(self):
        self._ready()
        return self._manifest_bytes

    @property
    def entries(self):
        self._ready()
        return {name: {"directory": entry.directory, "size_bytes": entry.size_bytes,
                       **({} if entry.directory else {"sha256": entry.sha256, "offset": entry.offset})}
                for name, entry in self._entries.items()}

    def report(self):
        self._ready()
        return {
            "schema_version": 1, "contract_id": CONTRACT_ID, "outcome": "pass",
            "retention_verified": True, "expected_revision": self.expected_revision,
            "archive_bytes": self._archive.size, "archive_sha256": self.expected_sha256,
            "file_count": len(self._manifest["files"]),
            "directory_count": len(self._manifest["directories"]), "input_bytes": self._input_bytes,
            "summary_checked": self._summary is not None, "native_execution": "not_run",
            "retained_code_executed": False, "origin_authenticated": False,
            "native_acceptance": False, "performance_acceptance": False, "phase_acceptance": False,
            "limitations": ["caller-selected-digest-is-not-origin-authentication",
                            "public-summary-ciphertext-is-not-verified",
                            "retention-consistency-is-not-native-or-performance-acceptance",
                            "observed-stability-does-not-exclude-malicious-concurrent-writers"],
        }

    def assert_unchanged(self):
        self._ready()
        self._archive.verify_digest(self.expected_sha256)
        if self._summary is not None:
            self._summary.verify_digest(self._summary_digest)

    def copy_file(self, name, output_fd):
        self._ready()
        _require(type(name) is str and name in self._entries
                 and not self._entries[name].directory, "unknown-file")
        _require(type(output_fd) is int and output_fd >= 0, "copy-output")
        entry = self._entries[name]
        self._archive.assert_identity()
        try:
            before = os.fstat(output_fd)
            _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                     and before.st_size == 0 and os.lseek(output_fd, 0, os.SEEK_CUR) == 0,
                     "copy-output")
            digest = hashlib.sha256()
            for body in self._archive.blocks(entry.offset, entry.size_bytes):
                digest.update(body)
                remaining = memoryview(body)
                while remaining:
                    count = os.write(output_fd, remaining)
                    _require(type(count) is int and 0 < count <= len(remaining), "copy-failed")
                    remaining = remaining[count:]
            _require(digest.hexdigest() == entry.sha256, "file-sha256")
            after = os.fstat(output_fd)
            _require(_stamp(before)[:2] == _stamp(after)[:2]
                     and after.st_size == entry.size_bytes and after.st_nlink == 1, "copy-failed")
        except (OSError, OverflowError):
            raise RetentionError("copy-failed") from None
        self._archive.assert_identity()


def inspect_archive(archive, expected_sha256, *, expected_revision, summary=None):
    """Return retention consistency only after complete offline verification."""
    with RetentionArchive(archive, expected_sha256,
                          expected_revision=expected_revision, summary=summary) as retained:
        return retained.report()
