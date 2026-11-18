# SPDX-License-Identifier: Apache-2.0
"""Bounded identities for Ramulator headers omitted from Git source inventories."""

from contextlib import ExitStack, contextmanager
import hashlib
import os
from pathlib import Path
import stat


HEADER_ROOTS = ("third_party/ramulator/ext/spdlog/include",
                "third_party/ramulator/ext/yaml-cpp/include")
MAX_HEADER_ENTRIES = 4096
MAX_HEADER_DEPTH = 16
MAX_HEADER_FILE_BYTES = 4 * 1024 * 1024
MAX_HEADER_BYTES = 32 * 1024 * 1024
READ_BYTES = 1024 * 1024


@contextmanager
def _opened(name, flags, parent=None):
    descriptor = os.open(name, flags | os.O_NOFOLLOW, dir_fd=parent)
    try:
        yield descriptor
    finally:
        os.close(descriptor)


def _identity(status):
    return (status.st_dev, status.st_ino, status.st_mode, status.st_size,
            status.st_mtime_ns, status.st_ctime_ns)


def _header(parent, name, relative, observed, available):
    with _opened(name, os.O_RDONLY | os.O_NONBLOCK, parent) as descriptor:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or _identity(before) != _identity(observed):
            raise ValueError("dependency header changed before reading: " + relative)
        if before.st_size > MAX_HEADER_FILE_BYTES:
            raise ValueError("dependency header exceeds the file byte limit: " + relative)
        if before.st_size > available:
            raise ValueError("dependency headers exceed the total byte limit")
        limit = min(MAX_HEADER_FILE_BYTES, available)
        digest, size = hashlib.sha256(), 0
        while chunk := os.read(descriptor, min(READ_BYTES, limit - size + 1)):
            size += len(chunk)
            if size > limit:
                raise ValueError("dependency header exceeds its byte limit while reading: " + relative)
            digest.update(chunk)
        after = os.fstat(descriptor)
        current = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if (_identity(before) != _identity(after) or _identity(before) != _identity(current)
                or size != after.st_size):
            raise ValueError("dependency header changed while reading: " + relative)
    return {"path": relative, "sha256": digest.hexdigest(), "size_bytes": size}


def dependency_headers(source):
    """Hash both complete include trees without following links or unbounded input."""
    source = Path(source).absolute()
    records, entries_seen, bytes_seen = [], 0, 0

    def walk(directory, relative, depth):
        nonlocal entries_seen, bytes_seen
        before = os.fstat(directory)
        with os.scandir(directory) as entries:
            for entry in entries:
                entries_seen += 1
                if entries_seen > MAX_HEADER_ENTRIES:
                    raise ValueError("dependency headers exceed the entry limit")
                name = relative + "/" + entry.name
                if "\\" in name or any(ord(character) < 32 for character in name):
                    raise ValueError("invalid dependency header path")
                observed = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(observed.st_mode):
                    if depth >= MAX_HEADER_DEPTH:
                        raise ValueError("dependency headers exceed the directory depth limit")
                    with _opened(entry.name, os.O_RDONLY | os.O_DIRECTORY, directory) as child:
                        if _identity(os.fstat(child)) != _identity(observed):
                            raise ValueError("dependency header directory changed: " + name)
                        walk(child, name, depth + 1)
                    if _identity(os.stat(entry.name, dir_fd=directory, follow_symlinks=False)) != _identity(observed):
                        raise ValueError("dependency header directory changed: " + name)
                elif stat.S_ISREG(observed.st_mode):
                    record = _header(directory, entry.name, name, observed, MAX_HEADER_BYTES - bytes_seen)
                    records.append(record)
                    bytes_seen += record["size_bytes"]
                else:
                    raise ValueError("dependency header is symlinked or not a regular file: " + name)
        if _identity(os.fstat(directory)) != _identity(before):
            raise ValueError("dependency header directory changed during inventory: " + relative)

    try:
        if source.resolve(strict=True) != source:
            raise ValueError("dependency header source is symlinked")
        with _opened(source, os.O_RDONLY | os.O_DIRECTORY) as source_fd:
            for relative in HEADER_ROOTS:
                with ExitStack() as stack:
                    directory, parents = source_fd, []
                    for part in Path(relative).parts:
                        child = stack.enter_context(_opened(part, os.O_RDONLY | os.O_DIRECTORY, directory))
                        parents.append((directory, part, os.fstat(child)))
                        directory = child
                    first = len(records)
                    walk(directory, relative, 0)
                    if len(records) == first:
                        raise ValueError("dependency header directory is empty: " + relative)
                    for parent, part, before in parents:
                        if _identity(os.stat(part, dir_fd=parent, follow_symlinks=False)) != _identity(before):
                            raise ValueError("dependency header directory changed during inventory: " + relative)
    except OSError as error:
        raise ValueError("dependency header inventory is missing, symlinked or unreadable") from error
    return sorted(records, key=lambda record: record["path"])
