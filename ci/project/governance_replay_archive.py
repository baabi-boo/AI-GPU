# SPDX-License-Identifier: Apache-2.0
"""Read bounded governance ZIP bytes without extracting or executing members."""

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import re
import stat
import struct
import zipfile
import zlib


MIB = 1024 * 1024
MAX_ARCHIVE_BYTES = 256 * MIB
MAX_MEMBER_BYTES = 256 * MIB
MAX_TOTAL_BYTES = 512 * MIB
MAX_MEMBERS = 64
MAX_DIRECTORY_BYTES = 64 * 1024
MAX_NAME_BYTES = 512
CHUNK_BYTES = 64 * 1024
_NAME = re.compile(r"[A-Za-z0-9_.+-]+(?:/[A-Za-z0-9_.+-]+)*\Z")
_END = struct.Struct("<4s4H2IH")
_LOCAL = struct.Struct("<4s5H3I2H")
_DESCRIPTOR = struct.Struct("<3I")
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


class ArchiveError(ValueError):
    """The selected local ZIP cannot be safely and completely inspected."""


def _require(condition, message):
    if not condition:
        raise ArchiveError(message)


def _name(value):
    _require(type(value) is str and 0 < len(value) <= MAX_NAME_BYTES
             and _NAME.fullmatch(value), "unsafe ZIP member name")
    parts = value.split("/")
    _require(len(parts) <= 16 and all(part not in (".", "..")
             and len(part) <= 255 for part in parts), "unsafe ZIP member component")
    return value


def _path(value):
    try:
        text = os.fspath(value)
    except TypeError:
        raise ArchiveError("archive path must be canonical absolute text") from None
    _require(type(text) is str and text.startswith("/") and len(text) <= 4096
             and "\\" not in text and ":" not in text
             and not any(ord(char) < 32 or ord(char) == 127 for char in text),
             "archive path must be canonical absolute text")
    parts = text.split("/")[1:]
    _require(0 < len(parts) <= 64 and all(part not in ("", ".", "..")
             and len(part.encode("utf-8")) <= 255 for part in parts),
             "archive path contains an unsafe component")
    return Path(text)


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _directory(path):
    descriptor = os.open("/", _DIRECTORY_FLAGS)
    try:
        identities = [_stamp(os.fstat(descriptor))[:2]]
        for part in path.parts[1:]:
            child = os.open(part, _DIRECTORY_FLAGS, dir_fd=descriptor)
            previous, descriptor = descriptor, child
            os.close(previous)
            identities.append(_stamp(os.fstat(descriptor))[:2])
        return descriptor, identities
    except BaseException:
        try:
            os.close(descriptor)
        except BaseException:
            pass
        raise


@contextmanager
def _input(path):
    parent, identities = _directory(path.parent)
    descriptor = stream = fresh_parent = None
    failed = False
    try:
        before = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1,
                 "archive must be a regular file without links")
        _require(_END.size <= before.st_size <= MAX_ARCHIVE_BYTES,
                 "archive exceeds its byte bound or is truncated")
        descriptor = os.open(path.name, _READ_FLAGS, dir_fd=parent)
        _require(_stamp(os.fstat(descriptor)) == _stamp(before),
                 "archive changed while opening")
        stream = os.fdopen(descriptor, "rb", closefd=False)
        yield stream, before.st_size
        fresh_parent, fresh_identities = _directory(path.parent)
        _require(fresh_identities == identities
                 and _stamp(os.fstat(stream.fileno())) == _stamp(before)
                 and _stamp(os.stat(path.name, dir_fd=fresh_parent,
                                    follow_symlinks=False)) == _stamp(before),
                 "archive changed while reading")
    except BaseException:
        failed = True
        raise
    finally:
        failure = None
        # A consuming close failure must not strand other owners or be retried.
        for resource, close in ((stream, lambda value: value.close()),
                                (descriptor, os.close), (fresh_parent, os.close),
                                (parent, os.close)):
            if resource is not None:
                try:
                    close(resource)
                except BaseException as error:
                    if failure is None:
                        failure = error
        if failure is not None and not failed:
            raise failure


def _read(stream, offset, size):
    stream.seek(offset)
    body = stream.read(size)
    _require(len(body) == size, "ZIP data is truncated")
    return body


def _blocks(stream, offset, size):
    while size:
        body = _read(stream, offset, min(size, CHUNK_BYTES))
        yield body
        offset += len(body)
        size -= len(body)


def _digest(stream, size):
    digest = hashlib.sha256()
    for body in _blocks(stream, 0, size):
        digest.update(body)
    return digest.hexdigest()


def _directory_bounds(stream, size):
    if size >= _END.size + 20:
        _require(_read(stream, size - _END.size - 20, 4) != b"PK\x06\x07",
                 "ZIP64 end records are unsupported")
    fields = _END.unpack(_read(stream, size - _END.size, _END.size))
    signature, disk, start_disk, disk_count, count, length, start, comment = fields
    _require(signature == b"PK\x05\x06" and disk == start_disk == 0
             and disk_count == count and 0 < count <= MAX_MEMBERS
             and 0 < length <= MAX_DIRECTORY_BYTES and start + length == size - _END.size
             and comment == 0, "unsupported, malformed or excessive ZIP directory")
    return start, count


def _entries(archive, start, count):
    entries = archive.infolist()
    _require(len(entries) == count and archive.start_dir == start,
             "ZIP directory count or offset differs")
    names, folded, total, compressed = set(), set(), 0, 0
    for item in entries:
        name = _name(item.filename)
        _require(item.orig_filename == name and name not in names
                 and name.casefold() not in folded, "duplicate or aliased ZIP member")
        names.add(name)
        folded.add(name.casefold())
        mode = item.external_attr >> 16
        _require(not item.is_dir() and stat.S_IFMT(mode) in (0, stat.S_IFREG)
                 and not mode & 0o7000 and not item.external_attr & 0xFFD8
                 and item.create_system in (0, 3), "ZIP member is not an ordinary regular file")
        _require(item.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                 and not item.flag_bits & ~0x080E
                 and (item.compress_type != zipfile.ZIP_STORED or not item.flag_bits & 6)
                 and item.extract_version <= 20,
                 "encrypted or unsupported ZIP member encoding")
        _require(not item.extra and not item.comment and item.volume == 0,
                 "unsupported ZIP member extensions")
        _require(0 <= item.file_size <= MAX_MEMBER_BYTES
                 and 0 <= item.compress_size <= MAX_ARCHIVE_BYTES
                 and 0 <= item.header_offset < start,
                 "ZIP member exceeds its byte bound")
        total += item.file_size
        compressed += item.compress_size
        _require(total <= MAX_TOTAL_BYTES and compressed <= MAX_ARCHIVE_BYTES,
                 "ZIP aggregate exceeds its byte bound")
    for name in names:
        parts = name.split("/")
        _require(not any("/".join(parts[:length]).casefold() in folded
                         for length in range(1, len(parts))), "ZIP file and parent names collide")
    return sorted(entries, key=lambda item: item.header_offset), names, total, compressed


def _member_layout(stream, item, next_offset):
    fields = _LOCAL.unpack(_read(stream, item.header_offset, _LOCAL.size))
    signature, version, flags, method, _, _, crc, compressed, size, namesize, extrasize = fields
    _require(signature == b"PK\x03\x04" and version == item.extract_version
             and flags == item.flag_bits and method == item.compress_type
             and 0 < namesize <= MAX_NAME_BYTES and extrasize == 0,
             "ZIP local header differs or has unsupported extensions")
    name = _read(stream, item.header_offset + _LOCAL.size, namesize)
    _require(name.decode("utf-8" if flags & 0x800 else "cp437") == item.filename,
             "ZIP local and directory names differ")
    expected = (item.CRC, item.compress_size, item.file_size)
    data = item.header_offset + _LOCAL.size + namesize
    end = data + item.compress_size
    _require(data <= end <= next_offset, "ZIP member overlaps another record")
    if flags & 8:
        _require((crc, compressed, size) in ((0, 0, 0), expected),
                 "ZIP local descriptor placeholders differ")
        length = next_offset - end
        _require(length in (12, 16), "ZIP data descriptor length differs")
        descriptor = _read(stream, end, length)
        if length == 16:
            _require(descriptor[:4] == b"PK\x07\x08", "ZIP descriptor signature differs")
            descriptor = descriptor[4:]
        _require(_DESCRIPTOR.unpack(descriptor) == expected, "ZIP data descriptor differs")
    else:
        _require((crc, compressed, size) == expected and end == next_offset,
                 "ZIP local sizes, CRC or record extent differ")
    return data


def _member_bytes(stream, item, offset, retain):
    digest, crc, size, chunks = hashlib.sha256(), 0, 0, []
    decoder = zlib.decompressobj(-15) if item.compress_type == zipfile.ZIP_DEFLATED else None

    def consume(body):
        nonlocal crc, size
        size += len(body)
        _require(size <= item.file_size and size <= MAX_MEMBER_BYTES,
                 "ZIP expanded member exceeds its declared size")
        digest.update(body)
        crc = zlib.crc32(body, crc)
        if retain:
            chunks.append(body)

    for compressed in _blocks(stream, offset, item.compress_size):
        if decoder is None:
            consume(compressed)
            continue
        pending = compressed
        while pending:
            body = decoder.decompress(pending, min(CHUNK_BYTES, item.file_size - size + 1))
            _require(not decoder.unused_data, "ZIP deflate stream has trailing data")
            consume(body)
            tail = decoder.unconsumed_tail
            _require(body or len(tail) < len(pending), "ZIP deflate stream made no progress")
            pending = tail
    if decoder is not None:
        _require(decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail,
                 "ZIP deflate stream is incomplete")
    _require(size == item.file_size and crc == item.CRC, "ZIP member size or CRC differs")
    return b"".join(chunks) if retain else None, {
        "bytes": size, "sha256": digest.hexdigest(), "compressed_bytes": item.compress_size}


def _retained_names(retain):
    if retain is None:
        return None
    _require(not isinstance(retain, (str, bytes)), "retained names must be a bounded collection")
    try:
        iterator = iter(retain)
    except TypeError:
        raise ArchiveError("retained names must be a bounded collection") from None
    names = set()
    for count, name in enumerate(iterator, 1):
        _require(count <= MAX_MEMBERS, "retained names exceed the member bound")
        names.add(_name(name))
    return names


def read_archive(path, *, retain=None):
    """Hash every member; retain all bytes or only the caller's exact selected names."""
    try:
        path, retain = _path(path), _retained_names(retain)
        with _input(path) as (stream, size):
            digest = _digest(stream, size)
            start, count = _directory_bounds(stream, size)
            with zipfile.ZipFile(stream) as archive:
                entries, names, total, compressed = _entries(archive, start, count)
                _require(retain is None or retain <= names, "retained member is absent from ZIP")
                _require(entries[0].header_offset == 0, "ZIP has an unsupported preamble")
                members, identities = {}, {}
                for index, item in enumerate(entries):
                    next_offset = entries[index + 1].header_offset if index + 1 < count else start
                    data = _member_layout(stream, item, next_offset)
                    keep = retain is None or item.filename in retain
                    body, identity = _member_bytes(stream, item, data, keep)
                    identities[item.filename] = identity
                    if keep:
                        members[item.filename] = body
            _require(_digest(stream, size) == digest, "archive bytes changed while reading")
            return {"members": members, "archive": {"bytes": size, "sha256": digest},
                    "member_identities": identities, "member_count": count,
                    "total_uncompressed_bytes": total, "total_compressed_bytes": compressed}
    except ArchiveError:
        raise
    except (OSError, EOFError, ValueError, RuntimeError, NotImplementedError,
            zipfile.BadZipFile, zipfile.LargeZipFile, struct.error, zlib.error):
        raise ArchiveError("archive is unreadable, malformed or unsupported") from None
