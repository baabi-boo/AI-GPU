# SPDX-License-Identifier: Apache-2.0
"""Bounded, no-follow access to inert retained baseline evidence."""

import hashlib
import json
import math
import os
import stat


MAX_TOTAL_BYTES = 512 * 1024 * 1024
MAX_FILES = 128
READ_CHUNK_BYTES = 64 * 1024
MAX_JSON_DEPTH = 64
MAX_JSON_TOKENS = 250000
MAX_NUMBER_CHARS = 1024
MAX_PATH_BYTES = 4096
MAX_PATH_DEPTH = 128


class PacketError(ValueError):
    """A retained packet is unsafe, malformed, inconsistent, or unstable."""


def _integer(value, label, maximum):
    if type(value) is not int or not 0 <= value <= maximum:
        raise PacketError(label + " must be a bounded nonnegative integer")
    return value


def _json_bounds(text):
    depth = tokens = 0
    quoted = escaped = False
    for character in text:
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
        elif character == '"':
            quoted = True
            tokens += 1
        elif character in "[{":
            depth += 1
            tokens += 1
            if depth > MAX_JSON_DEPTH:
                raise PacketError("JSON nesting exceeds the limit")
        elif character in "]}":
            depth -= 1
        elif character in ",:":
            tokens += 1
        if tokens > MAX_JSON_TOKENS:
            raise PacketError("JSON structure exceeds the limit")


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PacketError("duplicate JSON field")
        result[key] = value
    return result


def _json_integer(token):
    if len(token) > MAX_NUMBER_CHARS:
        raise PacketError("JSON integer exceeds the limit")
    return int(token)


def _json_float(token):
    if len(token) > MAX_NUMBER_CHARS:
        raise PacketError("JSON number exceeds the limit")
    value = float(token)
    if not math.isfinite(value):
        raise PacketError("nonfinite JSON number")
    return value


def _reject_constant(_value):
    raise PacketError("nonfinite JSON constant")


def load_json_bytes(contents, label="JSON"):
    """Parse a bounded-depth UTF-8 object without ambiguous fields or numbers."""
    if not isinstance(contents, (bytes, bytearray)):
        raise PacketError(str(label) + ": expected UTF-8 bytes")
    try:
        text = contents.decode("utf-8", errors="strict")
        _json_bounds(text)
        value = json.loads(text, object_pairs_hook=_unique_keys,
                           parse_int=_json_integer, parse_float=_json_float,
                           parse_constant=_reject_constant)
        if type(value) is not dict:
            raise PacketError("top-level JSON value must be an object")
        return value
    except (ValueError, UnicodeError, RecursionError, OverflowError) as error:
        raise PacketError(str(label) + ": " + str(error)) from error


def _path_text(value, label):
    try:
        value = os.fspath(value)
        if type(value) is not str or not value:
            raise ValueError
        if any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value):
            raise ValueError
        if len(value.encode("utf-8")) > MAX_PATH_BYTES:
            raise ValueError
    except (TypeError, ValueError, UnicodeError) as error:
        raise PacketError(label + " must be a bounded nonempty path") from error
    return value


def _relative_path(relative):
    if type(relative) is not str:
        raise PacketError("packet member must be a canonical POSIX relative path")
    relative = _path_text(relative, "packet member")
    parts = relative.split("/")
    if (relative.startswith("/") or "\\" in relative
            or (len(relative) >= 2 and relative[0].isalpha() and relative[1] == ":")
            or len(parts) > MAX_PATH_DEPTH
            or any(part in ("", ".", "..") or len(part.encode("utf-8")) > 255
                   for part in parts)):
        raise PacketError("packet member must be a canonical POSIX relative path")
    return relative, parts


def _require_nofollow():
    if (os.name != "posix" or not hasattr(os, "O_NOFOLLOW")
            or not hasattr(os, "O_DIRECTORY") or not hasattr(os, "O_NONBLOCK")
            or os.open not in os.supports_dir_fd
            or os.stat not in os.supports_dir_fd
            or os.stat not in os.supports_follow_symlinks):
        raise PacketError("this platform cannot enforce no-follow packet access")


def _directory_flags():
    return (os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK
            | getattr(os, "O_CLOEXEC", 0))


def _inode(info):
    return info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode)


def _file_state(info):
    return (_inode(info), info.st_mode, info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _open_directory(parent, name):
    before = os.stat(name, dir_fd=parent, follow_symlinks=False)
    if not stat.S_ISDIR(before.st_mode):
        raise PacketError("packet directory component is not a real directory")
    descriptor = os.open(name, _directory_flags(), dir_fd=parent)
    try:
        after = os.fstat(descriptor)
        if not stat.S_ISDIR(after.st_mode) or _inode(before) != _inode(after):
            raise PacketError("packet directory changed during traversal")
        return descriptor, _inode(after)
    except BaseException:
        os.close(descriptor)
        raise


def _check_links(links):
    for parent, name, descriptor, expected in links:
        current = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if _inode(current) != expected or _inode(os.fstat(descriptor)) != expected:
            raise PacketError("packet directory changed during verification")


class _DirectoryChain:
    def __init__(self, root):
        _require_nofollow()
        self.descriptors = []
        self.links = []
        root = _path_text(root, "packet root")
        try:
            if not root.startswith("/"):
                root = os.getcwd() + "/" + root
            parts = [part for part in root.split("/") if part and part != "."]
            if (len(root.encode("utf-8")) > MAX_PATH_BYTES
                    or len(parts) > MAX_PATH_DEPTH
                    or any(len(part.encode("utf-8")) > 255 for part in parts)):
                raise PacketError("packet root exceeds the path limit")
            self.descriptors.append(os.open("/", _directory_flags()))
            for name in parts:
                parent = self.descriptors[-1]
                descriptor, expected = _open_directory(parent, name)
                self.descriptors.append(descriptor)
                self.links.append((parent, name, descriptor, expected))
            self.check()
        except (OSError, ValueError) as error:
            self.close()
            raise PacketError("packet root is missing, unsafe, or unreadable") from error

    @property
    def fd(self):
        if not self.descriptors:
            raise PacketError("packet reader is closed")
        return self.descriptors[-1]

    def check(self):
        self.fd
        _check_links(self.links)

    def close(self):
        while self.descriptors:
            os.close(self.descriptors.pop())


class PacketReader:
    """Read and inventory a fixed, bounded set of retained regular files."""

    def __init__(self, root, max_total_bytes=MAX_TOTAL_BYTES, max_files=MAX_FILES):
        self._max_total_bytes = _integer(max_total_bytes, "total byte budget", MAX_TOTAL_BYTES)
        self._max_files = _integer(max_files, "file budget", MAX_FILES)
        self._records = {}
        self._states = {}
        self._total_bytes = 0
        self._root = _DirectoryChain(root)

    def __enter__(self):
        self._root.fd
        return self

    def __exit__(self, _kind, _value, _traceback):
        self.close()

    def close(self):
        self._root.close()

    def _read(self, relative, limit, retain):
        relative, parts = _relative_path(relative)
        limit = _integer(limit, "file byte limit", MAX_TOTAL_BYTES)
        previous = self._records.get(relative)
        if previous is None:
            if len(self._records) >= self._max_files:
                raise PacketError("packet exceeds the file-count limit")
            limit = min(limit, self._max_total_bytes - self._total_bytes)
        directories = []
        links = []
        descriptor = None
        try:
            self._root.check()
            parent = self._root.fd
            for name in parts[:-1]:
                child, expected = _open_directory(parent, name)
                directories.append(child)
                links.append((parent, name, child, expected))
                parent = child
            before = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISREG(before.st_mode):
                raise PacketError("packet member is not a regular file")
            if before.st_size < 0 or before.st_size > limit:
                raise PacketError("packet member exceeds its byte limit")
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
            descriptor = os.open(parts[-1], flags, dir_fd=parent)
            initial = os.fstat(descriptor)
            if not stat.S_ISREG(initial.st_mode) or _file_state(initial) != _file_state(before):
                raise PacketError("packet member changed while opening")
            if previous is not None and _file_state(initial) != self._states[relative]:
                raise PacketError("previously read packet member changed")
            digest = hashlib.sha256()
            chunks = [] if retain else None
            size = 0
            while True:
                chunk = os.read(descriptor, min(READ_CHUNK_BYTES, initial.st_size - size + 1))
                if not chunk:
                    break
                size += len(chunk)
                if size > initial.st_size or size > limit:
                    raise PacketError("packet member grew during reading")
                digest.update(chunk)
                if retain:
                    chunks.append(chunk)
            final = os.fstat(descriptor)
            named = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
            if (size != initial.st_size or _file_state(final) != _file_state(initial)
                    or _file_state(named) != _file_state(initial)):
                raise PacketError("packet member changed during reading")
            _check_links(links)
            self._root.check()
            record = {"path": relative, "sha256": digest.hexdigest(), "size_bytes": size}
            if previous is not None and record != previous:
                raise PacketError("previously read packet contents changed")
            if previous is None:
                self._records[relative] = record
                self._states[relative] = _file_state(initial)
                self._total_bytes += size
            return b"".join(chunks) if retain else dict(record)
        except (OSError, ValueError) as error:
            if isinstance(error, PacketError):
                raise PacketError(relative + ": " + str(error)) from error
            raise PacketError(relative + ": packet member is missing, unsafe, or unreadable") from error
        finally:
            if descriptor is not None:
                os.close(descriptor)
            for directory in reversed(directories):
                os.close(directory)

    def read_bytes(self, relative, limit=16 * 1024 * 1024):
        return self._read(relative, limit, retain=True)

    def read_json(self, relative, limit=8 * 1024 * 1024):
        return load_json_bytes(self.read_bytes(relative, limit), relative)

    def identity(self, relative, limit=16 * 1024 * 1024):
        return self._read(relative, limit, retain=False)

    def inventory(self):
        return [dict(self._records[path]) for path in sorted(self._records)]

    def recheck(self):
        try:
            self._root.check()
            for path in sorted(self._records):
                self.identity(path, limit=self._records[path]["size_bytes"])
            self._root.check()
        except OSError as error:
            raise PacketError("packet changed during recheck") from error


def write_bytes_exclusive(path, contents):
    """Create a separate output safely; preserve a partial file after write failure."""
    if not isinstance(contents, bytes):
        raise PacketError("exclusive output must be bytes")
    path = _path_text(path, "output")
    parent, separator, name = path.rpartition("/")
    if not separator:
        parent = "."
    elif not parent:
        parent = "/"
    _relative_path(name)
    chain = _DirectoryChain(parent)
    descriptor = None
    created = False
    try:
        chain.check()
        flags = (os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                 | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0))
        descriptor = os.open(name, flags, 0o600, dir_fd=chain.fd)
        created = True
        initial = os.fstat(descriptor)
        if not stat.S_ISREG(initial.st_mode):
            raise PacketError("exclusive output is not a regular file")
        offset = 0
        view = memoryview(contents)
        while offset < len(view):
            count = os.write(descriptor, view[offset:offset + READ_CHUNK_BYTES])
            if count <= 0:
                raise PacketError("exclusive output write made no progress")
            offset += count
        os.fsync(descriptor)
        final = os.fstat(descriptor)
        named = os.stat(name, dir_fd=chain.fd, follow_symlinks=False)
        if (_inode(final) != _inode(initial) or final.st_size != len(contents)
                or _file_state(final) != _file_state(named)):
            raise PacketError("exclusive output changed during writing")
        chain.check()
        os.fsync(chain.fd)
    except (OSError, ValueError) as error:
        if created:
            raise PacketError("exclusive output failed; a possibly partial output was preserved") from error
        raise PacketError("output already exists, is unsafe, or cannot be created") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
        chain.close()
