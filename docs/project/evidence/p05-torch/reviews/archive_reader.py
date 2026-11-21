#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Read original qualification ZIPs as bounded data; never extract or execute.

The caller supplies the original ZIP identity from its independently retained
intake record. This helper does not authenticate GitHub origin, interpret an
execution outcome, map recorded absolute paths onto the local filesystem, or
qualify a phase. Import this trusted source file, never a copy from an archive.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import struct
import zipfile
import zlib


MIB = 1024 * 1024
ARCHIVE_BYTES = 256 * MIB
DIRECTORY_BYTES = 32 * MIB
MEMBER_BYTES = 256 * MIB
EXPANDED_BYTES = 1024 * MIB
READ_BYTES = 2 * 1024 * MIB
READ_ATTEMPTS = 100000
JSON_BYTES = 16 * MIB
MEMBER_COUNT = 20000
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
EOCD = struct.Struct("<4s4H2IH")


class ArchiveError(ValueError):
    """An archive or data descriptor violates the bounded read contract."""


def require(condition, message):
    if not condition:
        raise ArchiveError(message)


def relative_name(value):
    require(type(value) is str and value and len(value.encode("utf-8")) <= 4096
            and "\\" not in value
            and not any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in value),
            "invalid retained member name")
    path = PurePosixPath(value)
    require(not path.is_absolute() and str(path) == value and len(path.parts) <= 64
            and not re.match(r"[A-Za-z]:", value)
            and all(part not in ("", ".", "..") for part in value.split("/")),
            "unsafe or noncanonical retained member name")
    return value


def recorded_absolute(value):
    """Validate a recorded POSIX path syntactically, without filesystem access."""
    require(type(value) is str and value.startswith("/") and value != "/",
            "invalid recorded absolute path")
    relative_name(value[1:])
    return PurePosixPath(value)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON field: " + key)
        result[key] = value
    return result


def _integer(token):
    require(len(token) <= 64, "oversized JSON integer")
    return int(token)


def _finite(token):
    require(len(token) <= 64, "oversized JSON number")
    value = float(token)
    require(math.isfinite(value), "nonfinite JSON number")
    return value


def _noninteger(token):
    raise ArchiveError("noninteger JSON observation number: " + token[:32])


def strict_json(raw, *, integers_only=False):
    require(type(raw) is bytes and 0 < len(raw) <= JSON_BYTES,
            "JSON is missing or exceeds its byte bound")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                           parse_int=_integer,
                           parse_float=_noninteger if integers_only else _finite,
                           parse_constant=_noninteger)
    except (UnicodeError, RecursionError, OverflowError, json.JSONDecodeError) as error:
        raise ArchiveError("invalid bounded JSON") from error
    pending, count = [(value, 0)], 0
    while pending:
        item, depth = pending.pop()
        count += 1
        require(depth <= 64 and count <= 300000, "JSON exceeds its structure bound")
        if type(item) is dict:
            pending.extend((child, depth + 1) for child in item.values())
        elif type(item) is list:
            pending.extend((child, depth + 1) for child in item)
    return value


def descriptor(value):
    require(type(value) is dict and set(value) == {"path", "sha256", "size_bytes"},
            "invalid retained descriptor fields")
    relative_name(value["path"])
    require(type(value["sha256"]) is str and SHA256.fullmatch(value["sha256"]),
            "invalid retained descriptor digest")
    require(type(value["size_bytes"]) is int and 0 <= value["size_bytes"] <= MEMBER_BYTES,
            "invalid retained descriptor byte count")
    return value


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


class ArchiveReader:
    """Read-only ZIP owner with identity checks before parsing and at close.

    Uncommented single-disk, non-ZIP64 ZIPs using stored/deflated members are the
    reviewed format. This matches the retained GitHub artifact format;
    another ZIP format requires a separately reviewed contract change.
    """

    def __init__(self, path, expected_sha256):
        require(type(expected_sha256) is str and SHA256.fullmatch(expected_sha256),
                "an external original ZIP SHA-256 is required")
        self.path = Path(path)
        require(self.path.is_absolute() and self.path.resolve(strict=True) == self.path
                and not any(part.is_symlink() for part in (self.path, *self.path.parents)),
                "archive path must be absolute and canonical without symlinks")
        self._stream = None
        self._zip = None
        self._closed = False
        self._expected_sha256 = expected_sha256
        self._reads = {}
        self._read_count = 0
        self._read_bytes = 0
        self._read_attempts = 0
        self._charged_read_bytes = 0
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
        try:
            self._stream = os.fdopen(os.open(self.path, flags), "rb")
            info = os.fstat(self._stream.fileno())
            require(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= ARCHIVE_BYTES,
                    "archive is not a bounded regular file")
            self._stamp = _stamp(info)
            self._size = info.st_size
            self._verify_original()
            self._directory_check()
            self._zip = zipfile.ZipFile(self._stream, "r")
            entries = self._zip.infolist()
            require(len(entries) == self._entry_count, "ZIP central-directory count differs")
            self._files, names, expanded = {}, set(), 0
            for item in entries:
                require(item.orig_filename == item.filename, "ZIP member has a hidden NUL suffix")
                name = item.filename[:-1] if item.is_dir() else item.filename
                relative_name(name)
                require(name not in names, "duplicate ZIP member or file/directory collision")
                names.add(name)
                kind = stat.S_IFMT(item.external_attr >> 16)
                require(kind in ((0, stat.S_IFDIR) if item.is_dir() else (0, stat.S_IFREG)),
                        "ZIP contains a symlink or special member")
                require(not item.flag_bits & 1, "encrypted ZIP members are unsupported")
                require(item.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED),
                        "unsupported ZIP compression method")
                require(0 <= item.header_offset < self._directory_offset,
                        "ZIP member header is outside its data region")
                require(0 <= item.file_size <= MEMBER_BYTES
                        and 0 <= item.compress_size <= self._size,
                        "ZIP member exceeds its byte bound")
                expanded += item.file_size
                require(expanded <= EXPANDED_BYTES, "ZIP exceeds its expanded byte bound")
                if item.is_dir():
                    require(item.file_size == 0, "ZIP directory contains a payload")
                else:
                    self._files[name] = item
            require(self._files, "ZIP contains no data files")
            require(min(item.header_offset for item in entries) == 0,
                    "ZIP has an unsupported leading payload")
            for name in names:
                require(not any(str(parent) in self._files for parent in PurePosixPath(name).parents
                                if str(parent) != "."), "ZIP file shadows a parent directory")
            self._expanded = expanded
            self._stable()
        except (zipfile.BadZipFile, RuntimeError, EOFError, UnicodeError, struct.error) as error:
            self._release()
            raise ArchiveError("invalid original ZIP structure") from error
        except BaseException:
            self._release()
            raise

    def _stable(self):
        require(not self._closed and self._stream is not None, "archive reader is closed")
        require(self.path.resolve(strict=True) == self.path
                and not any(part.is_symlink() for part in (self.path, *self.path.parents))
                and _stamp(os.fstat(self._stream.fileno())) == self._stamp
                and _stamp(self.path.stat(follow_symlinks=False)) == self._stamp,
                "original ZIP changed during its audit")

    def _verify_original(self):
        self._stable()
        self._stream.seek(0)
        digest, count = hashlib.sha256(), 0
        while raw := self._stream.read(MIB):
            count += len(raw)
            require(count <= self._size, "original ZIP grew while hashing")
            digest.update(raw)
        self._stable()
        require(count == self._size and digest.hexdigest() == self._expected_sha256,
                "original ZIP SHA-256 differs from the external intake identity")

    def _directory_check(self):
        # Bound the central directory before ZipFile allocates its member list.
        extent = min(self._size, EOCD.size + 65535)
        self._stream.seek(self._size - extent)
        tail = self._stream.read(extent)
        offset = tail.rfind(b"PK\x05\x06")
        require(offset >= 0 and offset + EOCD.size <= len(tail), "missing ZIP end record")
        _, disk, start_disk, disk_count, count, size, start, comment = EOCD.unpack_from(tail, offset)
        require(offset + EOCD.size + comment == len(tail), "ZIP end record or trailing bytes differ")
        require(comment == 0, "ZIP comments are outside the reviewed artifact format")
        require(disk == start_disk == 0 and disk_count == count
                and 0 < count <= MEMBER_COUNT and count != 0xFFFF,
                "multidisk, ZIP64 or excessive-member archives are unsupported")
        require(size <= DIRECTORY_BYTES and size != 0xFFFFFFFF and start != 0xFFFFFFFF
                and start + size == self._size - extent + offset,
                "ZIP central directory is oversized or outside its expected extent")
        self._entry_count, self._directory_offset = count, start

    def files(self):
        self._stable()
        return tuple(sorted(self._files))

    def _consume(self, name, limit, collect):
        relative_name(name)
        require(type(limit) is int and 0 <= limit <= MEMBER_BYTES, "invalid member read limit")
        self._stable()
        require(name in self._files, "missing retained member: " + name)
        item = self._files[name]
        require(item.file_size <= limit, "retained member exceeds the requested read bound")
        require(self._read_attempts < READ_ATTEMPTS
                and self._charged_read_bytes + item.file_size <= READ_BYTES,
                "aggregate archive read bound exceeded")
        # Charge before opening: a CRC/decompression failure must not allow
        # repeated expensive reads to bypass the aggregate resource bound.
        self._read_attempts += 1
        self._charged_read_bytes += item.file_size
        digest, count, chunks = hashlib.sha256(), 0, [] if collect else None
        try:
            with self._zip.open(item, "r") as stream:
                while raw := stream.read(MIB):
                    count += len(raw)
                    self._read_bytes += len(raw)
                    require(count <= item.file_size and count <= limit and self._read_bytes <= READ_BYTES,
                            "expanded member exceeds its declared or aggregate bound")
                    digest.update(raw)
                    if collect:
                        chunks.append(raw)
        except (zipfile.BadZipFile, RuntimeError, EOFError, zlib.error) as error:
            raise ArchiveError("invalid retained member payload: " + name) from error
        self._stable()
        require(count == item.file_size, "retained member is truncated")
        row = {"path": name, "sha256": digest.hexdigest(), "size_bytes": count}
        require(name not in self._reads or self._reads[name] == row, "retained member changed between reads")
        self._reads[name] = row
        self._read_count += 1
        return (b"".join(chunks) if collect else None), row

    def read(self, name, *, limit=JSON_BYTES):
        return self._consume(name, limit, True)[0]

    def identity(self, name, *, limit=MEMBER_BYTES):
        return dict(self._consume(name, limit, False)[1])

    def view(self, prefix=""):
        return PacketView(self, prefix)

    def receipt(self):
        self._stable()
        return {"scope": "data-only-original-archive-read", "acceptance_claimed": False,
                "retained_code_executed": False,
                "archive": {"path": str(self.path), "sha256": self._expected_sha256,
                            "size_bytes": self._size},
                "data_files": len(self._files), "expanded_bytes": self._expanded,
                "read_count": self._read_count, "read_bytes": self._read_bytes,
                "read_attempts": self._read_attempts,
                "charged_read_bytes": self._charged_read_bytes,
                "read_files": [dict(self._reads[name]) for name in sorted(self._reads)]}

    def _release(self):
        try:
            if self._zip is not None:
                self._zip.close()
        finally:
            if self._stream is not None:
                self._stream.close()
            self._closed = True

    def close(self):
        if not self._closed:
            try:
                self._verify_original()
            finally:
                self._release()

    def __enter__(self):
        self._stable()
        return self

    def __exit__(self, _kind, _value, _traceback):
        self.close()


class PacketView:
    """An explicit ZIP prefix; it never represents a live installed directory."""

    def __init__(self, archive, prefix=""):
        require(type(archive) is ArchiveReader, "packet view requires its original archive owner")
        if prefix:
            relative_name(prefix)
        else:
            require(prefix == "", "invalid packet prefix")
        self.archive, self.prefix = archive, prefix
        require(self.files(), "packet prefix has no retained files")

    def _name(self, relative):
        relative_name(relative)
        return self.prefix + "/" + relative if self.prefix else relative

    def files(self):
        prefix = self.prefix + "/" if self.prefix else ""
        return tuple(name[len(prefix):] for name in self.archive.files() if name.startswith(prefix))

    def subview(self, relative):
        return PacketView(self.archive, self._name(relative))

    def read(self, relative, *, limit=JSON_BYTES):
        return self.archive.read(self._name(relative), limit=limit)

    def identity(self, relative, *, limit=MEMBER_BYTES):
        return {**self.archive.identity(self._name(relative), limit=limit), "path": relative}

    def verified(self, row, expected_path=None, *, limit=JSON_BYTES):
        descriptor(row)
        require(expected_path is None or row["path"] == expected_path, "retained descriptor path differs")
        raw = self.read(row["path"], limit=limit)
        require(row["sha256"] == hashlib.sha256(raw).hexdigest() and row["size_bytes"] == len(raw),
                "retained descriptor hash or size differs")
        return raw

    def json(self, relative, *, integers_only=False):
        return strict_json(self.read(relative), integers_only=integers_only)

    def document(self, row, expected_path=None, *, integers_only=False):
        return strict_json(self.verified(row, expected_path), integers_only=integers_only)

    def inventory(self):
        return [self.identity(name) for name in self.files()]
