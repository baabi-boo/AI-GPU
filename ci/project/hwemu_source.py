# SPDX-License-Identifier: Apache-2.0
"""Bounded source provenance without vendor, submodule, or conversion execution."""

import configparser
from contextlib import contextmanager, ExitStack
import hashlib
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import time

from baseline_inventory import SOURCE_INPUTS
from baseline_packet_io import _DirectoryChain, _check_links, _file_state, _open_directory
from hwemu_build import COPIED_INPUTS
from hwemu_io import Inputs
from preflight import PIN_NAMES


# These are the inspector's source inputs, not a full build dependency closure.
REQUIRED_SOURCE_INPUTS = tuple(dict.fromkeys((
    *SOURCE_INPUTS, *COPIED_INPUTS.values(), "sw/runtime/xrt/xsim.tcl",
)))
MAX_SOURCE_FILE_BYTES = 1024 * 1024
MAX_SOURCE_BYTES = 8 * MAX_SOURCE_FILE_BYTES
MAX_PROBE_BYTES = 1024 * 1024
MAX_MODULES = 32
MAX_INDEX_ENTRIES = 32768
MAX_WORKTREE_BYTES = 512 * 1024 * 1024
MAX_OBSERVATION_SECONDS = 30
UNSAFE_CONFIG = r"^(filter\..*\.(clean|process)|extensions\.partialclone|remote\..*\.promisor)$"
GIT_COMMANDS = (
    ("config", "--includes", "--null", "--name-only", "--get-regexp", UNSAFE_CONFIG),
    ("rev-parse", "--show-toplevel"),
    ("rev-parse", "--verify", "HEAD"),
    ("rev-parse", "--verify", "HEAD^{tree}"),
    ("ls-files", "-v", "--stage", "-z"),
    ("ls-tree", "-r", "-z", "HEAD"),
    ("ls-files", "--others", "--exclude-standard", "-z"),
)


def _probe(argv, environment, deadline):
    process = None
    try:
        deadline = min(deadline, time.monotonic() + 10)
        if time.monotonic() >= deadline:
            raise ValueError("source observation timed out")
        process = subprocess.Popen(
            argv, env=environment, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, start_new_session=True,
        )
        output = bytearray()
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ValueError("source observation timed out")
                for key, _ in selector.select(min(0.1, remaining)):
                    chunk = os.read(key.fileobj.fileno(), 8192)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    output.extend(chunk)
                    if len(output) > MAX_PROBE_BYTES:
                        raise ValueError("source observation exceeded its byte limit")
            process.wait(timeout=max(0.001, deadline - time.monotonic()))
        return process.returncode, bytes(output)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError("source observation unavailable") from error
    finally:
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            if process.stdout is not None:
                process.stdout.close()


def _git(root, command, deadline):
    if command not in GIT_COMMANDS:
        raise ValueError("unsupported source observation")
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith("GIT_")}
    environment.update(GIT_OPTIONAL_LOCKS="0", GIT_NO_LAZY_FETCH="1",
                       GIT_NO_REPLACE_OBJECTS="1", GIT_TERMINAL_PROMPT="0")
    code, output = _probe(
        ["git", "--no-pager", "--no-optional-locks", "-c", "core.fsmonitor=false",
         "-c", "core.untrackedCache=false", "-C", str(root), *command],
        environment, deadline,
    )
    if command == GIT_COMMANDS[0] and code == 1 and not output:
        return b""
    if code != 0:
        raise ValueError("Git source observation failed")
    return output


def _relative(value):
    if (not value or value.startswith("/") or "\\" in value
            or len(value.encode("utf-8")) > 4096
            or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value)
            or any(part in ("", ".", "..", ".git") for part in value.split("/"))):
        raise ValueError("unsafe source member")
    return value


def _revision(value):
    value = value.decode("ascii").strip()
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("source identity is malformed")
    return value


def _pins(contents):
    pins = {}
    for line in contents.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if (not separator or key not in PIN_NAMES or key in pins
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", value)):
            raise ValueError("source pins are malformed")
        pins[key] = value
    if set(pins) != set(PIN_NAMES):
        raise ValueError("source pins are incomplete")
    return pins


def _declared_modules(contents):
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(contents)
    if parser.defaults():
        raise ValueError("submodule declarations contain defaults")
    result = set()
    for section in parser.sections():
        path = parser.get(section, "path", fallback="")
        if (not re.fullmatch(r'submodule "[^"\r\n]+"', section)
                or not re.fullmatch(r"[A-Za-z0-9_./+-]+", path)
                or _relative(path) in result):
            raise ValueError("submodule declarations are malformed")
        result.add(path)
    if len(result) > MAX_MODULES:
        raise ValueError("submodule declarations exceed their limit")
    return result


def _entries(output, *, index):
    entries = output.split(b"\0")
    if entries[-1] or len(entries) - 1 > MAX_INDEX_ENTRIES:
        raise ValueError("source index is malformed or oversized")
    result = {}
    for raw in entries[:-1]:
        metadata, separator, path = raw.partition(b"\t")
        if not separator:
            raise ValueError("source index is malformed")
        path = _relative(path.decode("utf-8"))
        fields = metadata.decode("ascii").split(" ")
        if index:
            if len(fields) != 4 or fields[0] != "H" or fields[3] != "0":
                raise ValueError("source index has hidden or unresolved entries")
            _, mode, revision, _ = fields
        else:
            if len(fields) != 3:
                raise ValueError("source tree is malformed")
            mode, kind, revision = fields
            if kind != ("commit" if mode == "160000" else "blob"):
                raise ValueError("source tree is malformed")
        if (mode not in ("100644", "100755", "120000", "160000")
                or not re.fullmatch(r"[0-9a-f]{40}", revision) or path in result):
            raise ValueError("source entries are malformed")
        result[path] = (mode, revision)
    return result


def _snapshot(root, chain, deadline):
    chain.check()
    if _git(root, GIT_COMMANDS[0], deadline):
        raise ValueError("source uses executable filters or deferred object retrieval")
    top = _git(root, GIT_COMMANDS[1], deadline).decode("utf-8").strip()
    if top != str(root):
        raise ValueError("source root is not the checkout root")
    revision = _revision(_git(root, GIT_COMMANDS[2], deadline))
    tree = _revision(_git(root, GIT_COMMANDS[3], deadline))
    index = _entries(_git(root, GIT_COMMANDS[4], deadline), index=True)
    entries = _entries(_git(root, GIT_COMMANDS[5], deadline), index=False)
    links = {path: oid for path, (mode, oid) in entries.items() if mode == "160000"}
    chain.check()
    return {"revision": revision, "tree": tree, "index": index,
            "entries": entries, "links": links}


def _required_members(snapshot):
    for members in (snapshot["entries"], snapshot["index"]):
        for name in REQUIRED_SOURCE_INPUTS:
            if members.get(name, (None,))[0] not in ("100644", "100755"):
                raise ValueError("required source input is not a recorded regular blob")


def _untracked(root, prefix, deadline, report):
    output = _git(root, GIT_COMMANDS[6], deadline)
    entries = output.split(b"\0")
    if entries[-1]:
        raise ValueError("source status is malformed")
    for entry in entries[:-1]:
        report["untracked_paths"].append(prefix + _relative(entry.decode("utf-8")))


@contextmanager
def _parent(chain, relative):
    directories = []
    links = []
    try:
        chain.check()
        parent = chain.fd
        parts = relative.split("/")
        for part in parts[:-1]:
            child, expected = _open_directory(parent, part)
            directories.append(child)
            links.append((parent, part, child, expected))
            parent = child
        yield parent, parts[-1]
        _check_links(links)
        chain.check()
    finally:
        for descriptor in reversed(directories):
            os.close(descriptor)


class _Worktree:
    def __init__(self, deadline):
        self.deadline = deadline
        self.size = 0
        self.count = 0
        self.states = []

    def _budget(self, size):
        self.count += 1
        self.size += size
        if (self.count > MAX_INDEX_ENTRIES or size < 0
                or self.size > MAX_WORKTREE_BYTES or time.monotonic() >= self.deadline):
            raise ValueError("source worktree exceeds its observation budget")

    def matches(self, chain, relative, mode, expected):
        try:
            with _parent(chain, relative) as (parent, name):
                before = os.stat(name, dir_fd=parent, follow_symlinks=False)
                self._budget(before.st_size)
                if stat.S_ISLNK(before.st_mode):
                    contents = os.readlink(os.fsencode(name), dir_fd=parent)
                    if len(contents) != before.st_size:
                        raise ValueError("source link changed during observation")
                    digest = hashlib.sha1(b"blob " + str(len(contents)).encode() + b"\0" + contents)
                    actual_mode = "120000"
                elif stat.S_ISREG(before.st_mode):
                    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
                    descriptor = os.open(name, flags, dir_fd=parent)
                    try:
                        if _file_state(os.fstat(descriptor)) != _file_state(before):
                            raise ValueError("source file changed while opening")
                        digest = hashlib.sha1(b"blob " + str(before.st_size).encode() + b"\0")
                        size = 0
                        while True:
                            if time.monotonic() >= self.deadline:
                                raise ValueError("source observation timed out")
                            chunk = os.read(descriptor, min(65536, before.st_size - size + 1))
                            if not chunk:
                                break
                            size += len(chunk)
                            if size > before.st_size:
                                raise ValueError("source file grew during observation")
                            digest.update(chunk)
                        if (size != before.st_size
                                or _file_state(os.fstat(descriptor)) != _file_state(before)):
                            raise ValueError("source file changed during observation")
                    finally:
                        os.close(descriptor)
                    actual_mode = "100755" if before.st_mode & stat.S_IXUSR else "100644"
                else:
                    raise ValueError("source file is not regular or a tracked link")
                after = os.stat(name, dir_fd=parent, follow_symlinks=False)
                if _file_state(after) != _file_state(before):
                    raise ValueError("source member changed during observation")
                self.states.append((chain, relative, _file_state(before)))
                return mode == actual_mode and expected == digest.hexdigest()
        except (FileNotFoundError, NotADirectoryError):
            return False

    def recheck(self):
        for chain, relative, expected in self.states:
            if time.monotonic() >= self.deadline:
                raise ValueError("source observation timed out")
            with _parent(chain, relative) as (parent, name):
                current = os.stat(name, dir_fd=parent, follow_symlinks=False)
                if _file_state(current) != expected:
                    raise ValueError("source member changed during observation")


def collect_source(root):
    report = {"revision": None, "tree": None, "dirty": None,
              "changed_paths": [], "untracked_paths": [], "pins": {},
              "submodules": {"entries": [], "declared_count": None, "errors": []},
              "blockers": [], "inputs": []}
    modules = report["submodules"]
    deadline = time.monotonic() + MAX_OBSERVATION_SECONDS
    try:
        root = Path(root).absolute()
        with ExitStack() as stack:
            inputs = stack.enter_context(Inputs(max_total_bytes=MAX_SOURCE_BYTES))
            repositories = []
            absent_manifests = []
            worktree = _Worktree(deadline)

            def prepare(path, prefix="", expected=None):
                chain = _DirectoryChain(str(path))
                stack.callback(chain.close)
                gitfile = path / ".git"
                metadata = gitfile.lstat()
                if stat.S_ISREG(metadata.st_mode):
                    inputs.read_text(str(gitfile), limit=MAX_SOURCE_FILE_BYTES)
                elif not stat.S_ISDIR(metadata.st_mode):
                    raise ValueError("source Git metadata is unsafe")
                snapshot = _snapshot(path, chain, deadline)
                manifest = path / ".gitmodules"
                if path == root:
                    _required_members(snapshot)
                    texts = {name: inputs.read_text(str(root / name), limit=MAX_SOURCE_FILE_BYTES)
                             for name in SOURCE_INPUTS}
                    report["pins"] = _pins(texts["VERSION"])
                    contents = texts[".gitmodules"]
                else:
                    try:
                        manifest.lstat()
                    except FileNotFoundError:
                        absent_manifests.append(manifest)
                        contents = ""
                    else:
                        contents = inputs.read_text(str(manifest), limit=MAX_SOURCE_FILE_BYTES)
                declared = _declared_modules(contents)
                if path == root:
                    report.update(revision=snapshot["revision"], tree=snapshot["tree"])
                    modules["declared_count"] = len(declared)
                if declared != set(snapshot["links"]):
                    raise ValueError("submodule declarations differ from recorded gitlinks")
                if expected is not None and snapshot["revision"] != expected:
                    modules["entries"][-1]["status"] = "revision_mismatch"
                    raise ValueError("submodule is not at its recorded revision")
                repositories.append((path, prefix, chain, snapshot))
                for relative in sorted(declared):
                    if len(modules["entries"]) >= MAX_MODULES:
                        raise ValueError("recursive submodule count exceeds its limit")
                    entry = {"path": prefix + relative, "revision": snapshot["links"][relative],
                             "status": "not_initialized"}
                    modules["entries"].append(entry)
                    child = path / relative
                    try:
                        (child / ".git").lstat()
                    except FileNotFoundError:
                        modules["errors"].append("a recorded submodule is not initialized")
                        continue
                    entry["status"] = "initialized"
                    prepare(child, prefix + relative + "/", entry["revision"])

            prepare(root)
            for path, prefix, chain, snapshot in repositories:
                chain.check()
                staged = {name for name in snapshot["index"].keys() | snapshot["entries"].keys()
                          if snapshot["index"].get(name) != snapshot["entries"].get(name)}
                changed = set(staged)
                for name, (mode, revision) in snapshot["index"].items():
                    if mode != "160000" and not worktree.matches(chain, name, mode, revision):
                        changed.add(name)
                report["changed_paths"].extend(prefix + name for name in sorted(changed))
                _untracked(path, prefix, deadline, report)
                if _snapshot(path, chain, deadline) != snapshot:
                    raise ValueError("source metadata changed during observation")
            inputs.recheck()
            worktree.recheck()
            for manifest in absent_manifests:
                try:
                    manifest.lstat()
                except FileNotFoundError:
                    continue
                raise ValueError("submodule declarations appeared during observation")
            for _, _, chain, _ in repositories:
                chain.check()
            report["inputs"] = [dict(item, path=str(Path(item["path"]).relative_to(root)))
                                for item in inputs.inventory()]
            report["dirty"] = bool(report["changed_paths"] or report["untracked_paths"])
            if report["dirty"]:
                report["blockers"].append("source contains tracked changes or nonignored untracked inputs")
            report["blockers"].extend(modules["errors"])
    except (ValueError, OSError, RuntimeError, TypeError, UnicodeError, configparser.Error):
        report["dirty"] = None
        modules["errors"].append("source or recursive submodule observation is incomplete")
        report["blockers"].append("source identity could not be completely verified")
    report["outcome"] = "blocked" if report["blockers"] else "pass"
    return report
