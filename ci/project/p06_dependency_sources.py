# SPDX-License-Identifier: Apache-2.0
"""Materialize and verify the complete locked dependency source trees."""

from copy import deepcopy
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import stat

import p06_dependency_contract as contract
from p06_managed_preflight_source_export import GitObjects, _tree_identity
import p06_managed_preflight_source_export as git_objects


CONTRACT_ID = "p06-dependency-source-inventory-v1"
MAX_PATH_BYTES = 4096
MAX_PATH_DEPTH = 64
MAX_GENERATED_FILES = 4096
_SHA1 = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
# The pinned yaml-cpp tree includes How-To-Parse-A-Document-(Old-API).md.
# These are inert file names; command roots retain their narrower grammar.
_RELATIVE = re.compile(r"[A-Za-z0-9_.+()-]+(?:/[A-Za-z0-9_.+()-]+)*")
_ABSOLUTE = re.compile(r"/[A-Za-z0-9_.+-]+(?:/[A-Za-z0-9_.+-]+)*")
_MANIFEST_FIELDS = {"schema_version", "contract_id", "dependency_contract_sha256",
                    "sources", "total_files", "total_size_bytes"}
_SOURCE_FIELDS = {"name", "url", "revision", "tree", "files"}
_FILE_FIELDS = {"path", "mode", "oid", "sha256", "size_bytes"}
_GENERATED_FIELDS = {"path", "sha256", "size_bytes"}
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


class SourceError(ValueError):
    pass


def _require(condition, message):
    if not condition:
        raise SourceError(message)


def _relative(value):
    _require(type(value) is str and 0 < len(value) <= MAX_PATH_BYTES
             and _RELATIVE.fullmatch(value), "source path is not bounded canonical relative text")
    parts = value.split("/")
    _require(len(parts) <= MAX_PATH_DEPTH and all(
        part not in (".", "..", ".git") and len(part) <= 255 for part in parts),
        "source path contains an unsafe component")
    return value


class _DependencyGitObjects(GitObjects):
    """Keep the original exporter grammar unchanged while reading full pinned trees."""

    def blob(self, name):
        _relative(name)
        entry = self.entries.get(name)
        _require(entry is not None and entry["kind"] == "blob"
                 and entry["mode"] in ("100644", "100755"),
                 "selected dependency is not a regular Git blob: " + name)
        if name not in self.cache:
            raw_size = self.run(["cat-file", "-s", entry["oid"]], 32)
            _require(re.fullmatch(rb"(?:0|[1-9][0-9]*)\n", raw_size), "Git object size is invalid")
            size = int(raw_size)
            _require(size <= git_objects.MAX_BLOB_BYTES
                     and self.budget["bytes"] + size <= git_objects.MAX_TOTAL_BYTES,
                     "dependency source exceeds its Git byte budget")
            body = self.run(["cat-file", "blob", entry["oid"]], max(size, 1))
            _require(len(body) == size, "Git dependency blob size changed")
            _require(hashlib.sha1(b"blob " + str(size).encode() + b"\0" + body).hexdigest()
                     == entry["oid"], "Git dependency blob bytes differ from their object identity")
            self.bytes_read += size
            self.budget["bytes"] += size
            self.cache[name] = body
        return self.cache[name]


def _absolute(value):
    _require(isinstance(value, (str, Path)), "source root must be an absolute path")
    text = str(value)
    _require(len(text) <= MAX_PATH_BYTES and _ABSOLUTE.fullmatch(text),
             "source root is not bounded canonical absolute text")
    path = Path(text)
    _require(str(path) == text and all(part not in (".", "..") for part in path.parts),
             "source root is not lexically canonical")
    return path


def _directory(value):
    path = _absolute(value)
    for current in reversed((path, *path.parents)):
        info = current.lstat()
        _require(stat.S_ISDIR(info.st_mode), "source root traverses a non-directory or symlink")
    return path


def _open_directory(root, relative="", *, create=False):
    descriptor = os.open(root, _DIRECTORY_FLAGS)
    try:
        for part in relative.split("/") if relative else ():
            if create:
                try:
                    os.mkdir(part, 0o755, dir_fd=descriptor)
                except FileExistsError:
                    pass
            child = os.open(part, _DIRECTORY_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _write_blob(root, relative, body, mode):
    parent, _, name = relative.rpartition("/")
    directory = _open_directory(root, parent, create=True)
    descriptor = None
    try:
        descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                             | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=directory)
        with os.fdopen(descriptor, "wb") as output:
            descriptor = None
            output.write(body)
            os.fchmod(output.fileno(), 0o755 if mode == "100755" else 0o644)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(directory)


def _read_identity(root, relative, maximum):
    parent, _, name = relative.rpartition("/")
    directory = _open_directory(root, parent)
    descriptor = None
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                             | os.O_CLOEXEC, dir_fd=directory)
        with os.fdopen(descriptor, "rb") as source:
            descriptor = None
            before = os.fstat(source.fileno())
            _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1,
                     "source input must be a regular file without hard links: " + relative)
            _require(0 <= before.st_size <= maximum, "source file exceeds its byte bound: " + relative)
            sha256 = hashlib.sha256()
            oid = hashlib.sha1(b"blob " + str(before.st_size).encode("ascii") + b"\0")
            size = 0
            while chunk := source.read(min(1024 * 1024, maximum - size + 1)):
                size += len(chunk)
                _require(size <= maximum, "source file exceeds its byte bound: " + relative)
                sha256.update(chunk)
                oid.update(chunk)
            after = os.fstat(source.fileno())
            _require(size == before.st_size and
                     (before.st_dev, before.st_ino, before.st_mode, before.st_nlink,
                      before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                     (after.st_dev, after.st_ino, after.st_mode, after.st_nlink,
                      after.st_size, after.st_mtime_ns, after.st_ctime_ns),
                     "source file changed while reading: " + relative)
            return {"sha256": sha256.hexdigest(), "oid": oid.hexdigest(),
                    "size_bytes": size, "permissions": stat.S_IMODE(before.st_mode)}
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(directory)


def validate_manifest(manifest):
    """Validate parsed inventory data against the fixed lock without filesystem access."""
    _require(type(manifest) is dict and set(manifest) == _MANIFEST_FIELDS,
             "dependency source manifest fields differ")
    _require(type(manifest["schema_version"]) is int and manifest["schema_version"] == 1
             and type(manifest["contract_id"]) is str and manifest["contract_id"] == CONTRACT_ID,
             "dependency source manifest version differs")
    _require(type(manifest["dependency_contract_sha256"]) is str
             and manifest["dependency_contract_sha256"] == contract.contract_hash(),
             "dependency source manifest contract digest differs")
    sources = manifest["sources"]
    _require(type(sources) is list and len(sources) == len(contract.PINS),
             "dependency source repository inventory differs")
    total_files = total_bytes = 0
    for source, name in zip(sources, sorted(contract.PINS)):
        pin = contract.PINS[name]
        _require(type(source) is dict and set(source) == _SOURCE_FIELDS
                 and source["name"] == name, "dependency source repository order or fields differ")
        for key in ("url", "revision", "tree"):
            _require(type(source[key]) is str and source[key] == pin[key],
                     "dependency source locked " + key + " differs: " + name)
        rows = source["files"]
        _require(type(rows) is list and 0 < len(rows) <= git_objects.MAX_TREE_ENTRIES,
                 "dependency source file inventory is empty or excessive")
        entries, previous = {}, None
        for row in rows:
            _require(type(row) is dict and set(row) == _FILE_FIELDS,
                     "dependency source file descriptor fields differ")
            path = _relative(row["path"])
            _relative(name + "/" + path)
            _require(previous is None or previous < path, "dependency source paths must be unique and sorted")
            _require(type(row["mode"]) is str and row["mode"] in ("100644", "100755"),
                     "dependency source requires regular Git blobs")
            _require(type(row["oid"]) is str and _SHA1.fullmatch(row["oid"]),
                     "dependency source Git object identity is invalid")
            _require(type(row["sha256"]) is str and _SHA256.fullmatch(row["sha256"]),
                     "dependency source SHA-256 is invalid")
            _require(type(row["size_bytes"]) is int and 0 <= row["size_bytes"] <= git_objects.MAX_BLOB_BYTES,
                     "dependency source file size is invalid")
            total_files += 1
            total_bytes += row["size_bytes"]
            _require(total_files <= git_objects.MAX_TREE_ENTRIES and total_bytes <= contract.MAX_SOURCE_BYTES,
                     "dependency source inventory exceeds its total bound")
            entries[path] = {"mode": row["mode"], "oid": row["oid"]}
            previous = path
        _require(_tree_identity(entries) == pin["tree"],
                 "dependency source inventory does not reconstruct the locked tree: " + name)
    _require(type(manifest["total_files"]) is int and manifest["total_files"] == total_files
             and type(manifest["total_size_bytes"]) is int and manifest["total_size_bytes"] == total_bytes,
             "dependency source inventory totals differ")
    return deepcopy(manifest)


def materialize_sources(repositories, destination):
    """Copy only fixed Git object bytes into a fresh owned dependency source root."""
    _require(type(repositories) is dict and set(repositories) == set(contract.PINS),
             "all and only five locked dependency repositories are required")
    destination = _absolute(destination)
    _directory(destination.parent)
    _require(not os.path.lexists(destination), "dependency source destination must be fresh")
    readers, budget = {}, {"commands": 0, "bytes": 0}
    for name in sorted(contract.PINS):
        repository = _directory(repositories[name])
        _require(not destination.is_relative_to(repository) and not repository.is_relative_to(destination),
                 "dependency source destination overlaps an acquisition repository")
        pin = contract.PINS[name]
        reader = _DependencyGitObjects(repository, pin["revision"], budget=budget)
        _require(reader.tree_id == pin["tree"], "dependency repository differs from the locked root tree: " + name)
        _require(all(row["kind"] == "blob" and row["mode"] in ("100644", "100755")
                     for row in reader.entries.values()), "dependency source tree contains a symlink or gitlink")
        readers[name] = reader
    manifest = {"schema_version": 1, "contract_id": CONTRACT_ID,
                "dependency_contract_sha256": contract.contract_hash(), "sources": [],
                "total_files": 0, "total_size_bytes": 0}
    for name, reader in readers.items():
        pin = contract.PINS[name]
        source = {"name": name, **{key: pin[key] for key in ("url", "revision", "tree")}, "files": []}
        for relative, entry in sorted(reader.entries.items()):
            _relative(relative)
            body = reader.blob(relative)
            source["files"].append({"path": relative, "mode": entry["mode"], "oid": entry["oid"],
                                    "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)})
            manifest["total_files"] += 1
            manifest["total_size_bytes"] += len(body)
        manifest["sources"].append(source)
    validate_manifest(manifest)
    destination.mkdir(mode=0o700)
    for source in manifest["sources"]:
        name = source["name"]
        for row in source["files"]:
            _write_blob(destination, name + "/" + row["path"], readers[name].blob(row["path"]), row["mode"])
    verify_sources(manifest, destination)
    return manifest


def _generated(rows, source_names):
    _require(type(rows) in (list, tuple) and len(rows) <= MAX_GENERATED_FILES,
             "generated source-root files must be a bounded explicit sequence")
    generated, total = {}, 0
    for row in rows:
        _require(type(row) is dict and set(row) == _GENERATED_FIELDS,
                 "generated source-root descriptor fields differ")
        name = _relative(row["path"])
        softfloat = re.fullmatch(r"softfloat/build/Linux-x86_64-GCC/(?:[A-Za-z0-9_.+-]+\.(?:o|d)|softfloat\.a)", name)
        _require(softfloat is not None or name == "ramulator/libramulator.so",
                 "generated file is outside the exact source-root output grammar: " + name)
        _require(name not in source_names and name not in generated,
                 "generated file duplicates or replaces an immutable source: " + name)
        _require(type(row["sha256"]) is str and _SHA256.fullmatch(row["sha256"])
                 and type(row["size_bytes"]) is int and 0 <= row["size_bytes"] <= contract.MAX_FILE_BYTES,
                 "generated source-root file identity is invalid")
        total += row["size_bytes"]
        _require(total <= contract.MAX_PACKET_BYTES, "generated source-root files exceed their byte bound")
        generated[name] = row
    return generated


def _filesystem_inventory(root, expected_files, expected_directories):
    seen_files, seen_directories = set(), set()
    pending = [(root, "")]
    while pending:
        directory, prefix = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                name = _relative(prefix + entry.name)
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    _require(name in expected_directories, "unexpected source directory: " + name)
                    seen_directories.add(name)
                    pending.append((Path(entry.path), name + "/"))
                else:
                    _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
                             "source tree contains a symlink, special file or hard link: " + name)
                    _require(name in expected_files, "unexpected source-root file: " + name)
                    seen_files.add(name)
    _require(seen_files == expected_files and seen_directories == expected_directories,
             "dependency source filesystem inventory is incomplete")


def verify_sources(manifest, root, *, generated_files=()):
    """Rehash immutable sources and an exact, caller-bound set of generated products."""
    manifest = validate_manifest(manifest)
    root = _directory(root)
    originals = {source["name"] + "/" + row["path"]: row
                 for source in manifest["sources"] for row in source["files"]}
    generated = _generated(generated_files, originals)
    names = set(originals) | set(generated)
    directories = set()
    for name in names:
        directories.update(str(path) for path in PurePosixPath(name).parents if str(path) != ".")
    _filesystem_inventory(root, names, directories)
    for name, row in originals.items():
        observed = _read_identity(root, name, git_objects.MAX_BLOB_BYTES)
        _require(all(observed[key] == row[key] for key in ("sha256", "size_bytes", "oid")),
                 "immutable dependency source changed: " + name)
        _require(observed["permissions"] == (0o755 if row["mode"] == "100755" else 0o644),
                 "immutable dependency source mode changed: " + name)
    for name, row in generated.items():
        observed = _read_identity(root, name, contract.MAX_FILE_BYTES)
        _require(all(observed[key] == row[key] for key in ("sha256", "size_bytes")),
                 "generated dependency product changed: " + name)
    return {"contract_id": CONTRACT_ID, "manifest_sha256": contract.digest(manifest),
            "source_files": manifest["total_files"], "source_bytes": manifest["total_size_bytes"],
            "generated_files": len(generated),
            "generated_bytes": sum(row["size_bytes"] for row in generated.values()),
            "generated_sha256": contract.digest([generated[name] for name in sorted(generated)])}
