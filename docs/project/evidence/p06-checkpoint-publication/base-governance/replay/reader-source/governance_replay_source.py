# SPDX-License-Identifier: Apache-2.0
"""Independently bind a trusted checkout without executing its retained code."""

from contextlib import closing, contextmanager
import hashlib
import importlib.util
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import time

from baseline_packet_io import _DirectoryChain, _check_links, _file_state, _open_directory


GIT_EXECUTABLE = "/usr/bin/git"
MAX_GIT_BYTES = 4 * 1024**2
MAX_SOURCE_FILES = 32_768
MAX_SOURCE_FILE_BYTES = 128 * 1024**2
MAX_SOURCE_BYTES = 1024**3
MAX_SOURCE_SECONDS = 30
MAX_GITLINKS = 32
UNSAFE_CONFIG = (r"^(filter\..*\.(clean|smudge|process)|extensions\.partialclone|"
                 r"remote\..*\.(promisor|partialclonefilter)|diff\.external|"
                 r"diff\..*\.(command|textconv)|core\.alternaterefscommand)$")
PYTHON_SUFFIXES = {".py", ".pyw", ".pyc", ".pyo", ".so", ".pyd"}


class SourceBindingError(ValueError):
    """The selected checkout is unsafe, incomplete, changed, or not exact."""


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise SourceBindingError("source observation timed out")
    return remaining


def _git(root, arguments, deadline, *, returncodes=(0,)):
    environment = {
        "PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "LANG": "C", "LC_ALL": "C",
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_OPTIONAL_LOCKS": "0", "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_NO_LAZY_FETCH": "1", "GIT_TERMINAL_PROMPT": "0",
        "GIT_ALLOW_PROTOCOL": "", "GIT_ATTR_NOSYSTEM": "1",
    }
    deadline = min(deadline, time.monotonic() + 10)
    process = None
    try:
        _remaining(deadline)
        process = subprocess.Popen(
            [GIT_EXECUTABLE, "--no-pager", "--no-optional-locks", "-c",
             "core.fsmonitor=false", "-c", "core.hooksPath=" + os.devnull,
             "-c", "core.untrackedCache=false", *arguments],
            cwd=root, env=environment, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
        output = bytearray()
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                for key, _ in selector.select(min(0.1, _remaining(deadline))):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                    else:
                        output.extend(chunk)
                        if len(output) > MAX_GIT_BYTES:
                            raise SourceBindingError("Git source output exceeds its byte limit")
        process.wait(timeout=_remaining(deadline))
        if process.returncode not in returncodes:
            raise SourceBindingError("trusted Git source inventory failed")
        return bytes(output)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SourceBindingError("trusted Git source inventory is unavailable or timed out") from error
    finally:
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            process.stdout.close()


def _relative(value):
    parts = value.split("/")
    if (not value or value.startswith("/") or "\\" in value or ":" in value
            or len(value.encode("utf-8")) > 4096 or len(parts) > 128
            or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value)
            or any(part.lower() in ("", ".", "..", ".git")
                   or len(part.encode("utf-8")) > 255 for part in parts)):
        raise SourceBindingError("unsafe Git source filename")
    return value


def _records(output):
    records = output.split(b"\0")
    if records[-1] or len(records) - 1 > MAX_SOURCE_FILES:
        raise SourceBindingError("source inventory is malformed or exceeds its entry limit")
    return records[:-1]


def _entries(output, oid_length, *, index=False):
    entries = {}
    for record in _records(output):
        metadata, separator, raw_name = record.partition(b"\t")
        if not separator:
            raise SourceBindingError("source inventory is malformed")
        name = _relative(raw_name.decode("utf-8", "strict"))
        fields = metadata.decode("ascii").split(" ")
        if index:
            if len(fields) != 4 or fields[0] != "H" or fields[3] != "0":
                raise SourceBindingError("source index has hidden, sparse, or unresolved entries")
            _, mode, oid, _ = fields
        else:
            if len(fields) != 3:
                raise SourceBindingError("source tree inventory is malformed")
            mode, kind, oid = fields
            if kind != ("commit" if mode == "160000" else "blob"):
                raise SourceBindingError("source tree has an unsupported member type")
        if (mode not in ("100644", "100755", "120000", "160000")
                or not re.fullmatch(r"[0-9a-f]{" + str(oid_length) + "}", oid)
                or name in entries):
            raise SourceBindingError("source inventory has malformed or duplicate entries")
        entries[name] = (mode, oid)
    return entries


@contextmanager
def _parent(chain, relative):
    descriptors, links = [], []
    try:
        chain.check()
        parent = chain.fd
        parts = relative.split("/")
        for name in parts[:-1]:
            child, expected = _open_directory(parent, name)
            descriptors.append(child)
            links.append((parent, name, child, expected))
            parent = child
        yield parent, parts[-1]
        _check_links(links)
        chain.check()
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _reject_grafts(directory):
    with closing(_DirectoryChain(directory)) as chain:
        try:
            with _parent(chain, "info/grafts") as (parent, name):
                os.stat(name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            return
        raise SourceBindingError("source Git grafts are not allowed")


def _metadata(root, revision, deadline):
    if _git(root, ["config", "--includes", "--null", "--name-only", "--get-regexp",
                   UNSAFE_CONFIG], deadline, returncodes=(0, 1)):
        raise SourceBindingError("source uses executable filters or deferred object retrieval")
    sparse = _git(root, ["config", "--includes", "--bool", "--get", "core.sparsecheckout"],
                  deadline, returncodes=(0, 1))
    if sparse not in (b"", b"false\n"):
        raise SourceBindingError("sparse source checkout is not a complete population")
    layout = _git(root, ["rev-parse", "--path-format=absolute", "--show-toplevel", "--git-dir",
                        "--git-common-dir"], deadline).decode("utf-8", "strict").splitlines()
    if len(layout) != 3 or layout[0] != str(root):
        raise SourceBindingError("source must name the exact checkout root")
    for directory in set(layout[1:]):
        _reject_grafts(directory)
    if _git(root, ["for-each-ref", "--format=%(refname)", "refs/replace/"], deadline):
        raise SourceBindingError("source Git replacement refs are not allowed")
    identities = _git(root, ["rev-parse", "HEAD", "HEAD^{commit}", "HEAD^{tree}"],
                      deadline).decode("ascii").splitlines()
    if (len(identities) != 3 or identities[0] != revision or identities[1] != revision
            or not re.fullmatch(r"[0-9a-f]{" + str(len(revision)) + "}", identities[2])):
        raise SourceBindingError("source HEAD does not match the exact requested revision")
    index = _entries(_git(root, ["ls-files", "-v", "--stage", "-z"], deadline),
                     len(revision), index=True)
    entries = _entries(_git(root, ["ls-tree", "-r", "-z", "HEAD"], deadline), len(revision))
    if index != entries:
        raise SourceBindingError("source index differs from HEAD")
    if _git(root, ["ls-files", "--others", "--exclude-standard", "-z"], deadline):
        raise SourceBindingError("source checkout has untracked files")
    ignored = tuple(_relative(raw.decode("utf-8", "strict")) for raw in _records(
        _git(root, ["ls-files", "--others", "--ignored", "--exclude-standard", "-z"], deadline)))
    return tuple(layout), identities[2], entries, ignored


def _python_inventory(root, chain, entries, ignored, deadline):
    for name in ignored:
        _remaining(deadline)
        with _parent(chain, name) as (parent, member):
            info = os.stat(member, dir_fd=parent, follow_symlinks=False)
        if Path(name).suffix.lower() in PYTHON_SUFFIXES or not stat.S_ISREG(info.st_mode):
            raise SourceBindingError("ignored Python source, bytecode, or link is not bound to HEAD")
    for name, (mode, _oid) in entries.items():
        _remaining(deadline)
        suffix = Path(name).suffix.lower()
        if suffix in (".pyc", ".pyo") or (suffix in PYTHON_SUFFIXES and mode == "120000"):
            raise SourceBindingError("Python bytecode or symlink cannot establish bound source")
        if suffix == ".py":
            cached = importlib.util.cache_from_source(str(root / name))
            if os.path.lexists(cached):
                raise SourceBindingError("local Python source has unbound cached bytecode")


def _read_member(chain, relative, algorithm, deadline, byte_budget):
    with _parent(chain, relative) as (parent, name):
        before = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode) and not stat.S_ISLNK(before.st_mode):
            raise SourceBindingError("tracked source is not a regular file or symlink")
        if not 0 <= before.st_size <= min(MAX_SOURCE_FILE_BYTES, byte_budget):
            raise SourceBindingError("tracked source exceeds its byte limit")
        digest = hashlib.new(algorithm, b"blob " + str(before.st_size).encode("ascii") + b"\0")
        if stat.S_ISLNK(before.st_mode):
            contents = os.readlink(os.fsencode(name), dir_fd=parent)
            if len(contents) != before.st_size:
                raise SourceBindingError("source symlink changed during observation")
            digest.update(contents)
            mode = "120000"
        else:
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            try:
                if _file_state(os.fstat(descriptor)) != _file_state(before):
                    raise SourceBindingError("source file changed while opening")
                size = 0
                while True:
                    _remaining(deadline)
                    chunk = os.read(descriptor, min(65536, before.st_size - size + 1))
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > before.st_size:
                        raise SourceBindingError("source file grew during observation")
                    digest.update(chunk)
                if size != before.st_size or _file_state(os.fstat(descriptor)) != _file_state(before):
                    raise SourceBindingError("source file changed during observation")
            finally:
                os.close(descriptor)
            mode = "100755" if before.st_mode & stat.S_IXUSR else "100644"
        if _file_state(os.stat(name, dir_fd=parent, follow_symlinks=False)) != _file_state(before):
            raise SourceBindingError("source member changed during observation")
        return (mode, digest.hexdigest()), before.st_size, _file_state(before)


def source_binding(source_dir, revision):
    """Return exact top-level source identity; gitlinks bind pins, not native closure."""
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", revision):
        raise SourceBindingError("source revision must be a full lowercase Git object ID")
    try:
        raw_root = os.fspath(source_dir)
        if not isinstance(raw_root, str) or not os.path.isabs(raw_root):
            raise SourceBindingError("source directory must be an absolute checkout root")
        if raw_root != os.path.normpath(raw_root):
            raise SourceBindingError("source directory must have a canonical path")
        root = Path(raw_root)
        deadline = time.monotonic() + MAX_SOURCE_SECONDS
        with closing(_DirectoryChain(root)) as chain:
            locator = os.stat(".git", dir_fd=chain.fd, follow_symlinks=False)
            if not stat.S_ISDIR(locator.st_mode) and not (
                    stat.S_ISREG(locator.st_mode) and 0 < locator.st_size <= 4096):
                raise SourceBindingError("source Git locator is not a real directory or bounded file")
            metadata = _metadata(root, revision, deadline)
            _layout, tree, entries, ignored = metadata
            _python_inventory(root, chain, entries, ignored, deadline)
            algorithm = "sha1" if len(revision) == 40 else "sha256"
            digest = hashlib.sha256()
            total_bytes, states, gitlinks = 0, {}, []
            for name, identity in sorted(entries.items()):
                _remaining(deadline)
                mode, oid = identity
                digest.update((mode + " " + oid + "\t" + name + "\0").encode("utf-8"))
                if mode == "160000":
                    gitlinks.append({"path": name, "oid": oid})
                    if len(gitlinks) > MAX_GITLINKS:
                        raise SourceBindingError("source gitlinks exceed their entry limit")
                    try:
                        with _parent(chain, name) as (parent, member):
                            info = os.stat(member, dir_fd=parent, follow_symlinks=False)
                        if not stat.S_ISDIR(info.st_mode):
                            raise SourceBindingError("source gitlink is not a real directory")
                    except FileNotFoundError:
                        pass
                    continue
                observed, size, state = _read_member(chain, name, algorithm, deadline,
                                                      MAX_SOURCE_BYTES - total_bytes)
                if observed != identity:
                    raise SourceBindingError("materialized source differs from HEAD: " + name)
                total_bytes += size
                states[name] = state
            if _metadata(root, revision, deadline) != metadata:
                raise SourceBindingError("source metadata changed during observation")
            _python_inventory(root, chain, entries, ignored, deadline)
            for name, state in states.items():
                _remaining(deadline)
                with _parent(chain, name) as (parent, member):
                    if _file_state(os.stat(member, dir_fd=parent, follow_symlinks=False)) != state:
                        raise SourceBindingError("source member changed during observation")
            chain.check()
        return {"head": revision, "tree": tree, "object_format": algorithm,
                "tracked_sha256": digest.hexdigest(), "tracked_count": len(entries),
                "tracked_bytes": total_bytes, "gitlinks": gitlinks}
    except SourceBindingError:
        raise
    except (OSError, ValueError, TypeError, UnicodeError) as error:
        raise SourceBindingError("source checkout is unsafe, incomplete, or unstable") from error
