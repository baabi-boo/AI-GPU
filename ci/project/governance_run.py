#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run the complete governance unittest population with strict identity accounting."""

from __future__ import annotations

import argparse
from collections import Counter
import contextlib
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import time
import traceback
import unittest


ROOT = Path(__file__).resolve().parents[2]
DISCOVERY = {"start_directory": "ci/project", "pattern": "test_*.py"}
SCOPE = "project-governance-unittest-only"
MAX_TESTS = 100_000
MAX_ID_BYTES = 4096
MAX_RECORD_BYTES = 32 * 1024**2
MAX_LOG_BYTES = 128 * 1024**2
MAX_EVENTS = 1_000_000
MAX_GIT_BYTES = 4 * 1024**2
MAX_TOOL_BYTES = 512 * 1024**2
MAX_SOURCE_FILES = 32_768
MAX_SOURCE_FILE_BYTES = 128 * 1024**2
MAX_SOURCE_BYTES = 1024**3
MAX_SOURCE_SECONDS = 30
MAX_GITLINKS = 32
UNSAFE_SOURCE_CONFIG = (r"^(filter\..*\.(clean|smudge|process)|extensions\.partialclone|"
                        r"remote\..*\.promisor|diff\.external|diff\..*\.(command|textconv))$")
REQUIRED_ENVIRONMENT_TOOLS = {"python", "python3", "cmake", "gcc", "g++", "ar", "ranlib",
                              "make", "git", "tclsh", "readelf"}


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _identity(test):
    value = test.id()
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > MAX_ID_BYTES:
        raise ValueError("invalid or oversized unittest identity")
    return value


def _subtest_identity(test):
    """Preserve short labels; bind oversized dynamic labels without truncation."""
    value = test.id()
    if not isinstance(value, str) or not value:
        raise ValueError("invalid unittest subtest identity")
    encoded = value.encode("utf-8")
    if len(encoded) <= MAX_ID_BYTES:
        return {"subtest_id": value}
    return {"subtest_id": "sha256:" + hashlib.sha256(encoded).hexdigest(),
            "subtest_id_encoding": "sha256", "subtest_id_original_encoding": "utf-8",
            "subtest_id_original_bytes": len(encoded)}


def collect_test_ids(suite):
    """Collect ordered strings without retaining additional test-case objects."""
    identities = []

    def visit(node):
        if isinstance(node, unittest.TestSuite):
            for child in node:
                visit(child)
        else:
            identities.append(_identity(node))
            if len(identities) > MAX_TESTS:
                raise ValueError("governance discovery exceeds the identity limit")

    visit(suite)
    return identities


def _ids_digest(identities):
    return hashlib.sha256("".join(item + "\n" for item in identities).encode("utf-8")).hexdigest()


class StrictResult(unittest.TextTestResult):
    def __init__(self, *args, test_ids, event_sink=None, loader_errors=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.test_ids = tuple(test_ids)
        self.event_sink = event_sink
        self.loader_errors = list(loader_errors)
        self.starts = Counter()
        self.stops = Counter()
        self.outcomes = Counter()
        self.start_order = []
        self.fixture_counts = Counter()
        self.subtest_counts = Counter()
        self.event_count = 0
        self.execution_completed = False
        self.abort = None
        self.summary = {}
        self.strict_success = False
        self._started = time.monotonic()

    def getDescription(self, test):
        if isinstance(test, str):
            return test
        if isinstance(test, unittest.case._SubTest):
            record = _subtest_identity(test)
            if "subtest_id_encoding" in record:
                return record["subtest_id"]
        return super().getDescription(test)

    def _emit(self, event, **fields):
        self.event_count += 1
        if self.event_count > MAX_EVENTS:
            raise ValueError("governance event limit exceeded")
        if self.event_sink is not None:
            self.event_sink({"sequence": self.event_count, "event": event,
                             "elapsed_seconds": round(time.monotonic() - self._started, 6), **fields})

    def _outcome(self, test, outcome, **fields):
        if isinstance(test, unittest.case._SubTest):
            parent_id = _identity(test.test_case)
            record = _subtest_identity(test)
            self.subtest_counts[outcome] += 1
            self._emit("subtest_outcome", test_id=parent_id,
                       outcome=outcome, **record, **fields)
            return record["subtest_id"]
        identity = _identity(test)
        if isinstance(test, unittest.TestCase):
            self.outcomes[(identity, outcome)] += 1
            self._emit("test_outcome", test_id=identity, outcome=outcome, **fields)
        else:
            self.fixture_counts[outcome] += 1
            self._emit("fixture_outcome", fixture_id=identity, outcome=outcome, **fields)
        return identity

    def startTest(self, test):
        identity = _identity(test)
        self.starts[identity] += 1
        self.start_order.append(identity)
        self._emit("test_start", test_id=identity)
        super().startTest(test)

    def stopTest(self, test):
        identity = _identity(test)
        self.stops[identity] += 1
        self._emit("test_stop", test_id=identity)
        super().stopTest(test)

    def addSuccess(self, test):
        self._outcome(test, "success")
        super().addSuccess(test)

    def addFailure(self, test, err):
        self._outcome(test, "failure")
        super().addFailure(test, err)
        self.failures[-1] = (self.getDescription(test), self.failures[-1][1])

    def addError(self, test, err):
        self._outcome(test, "error")
        super().addError(test, err)
        self.errors[-1] = (self.getDescription(test), self.errors[-1][1])

    def addSkip(self, test, reason):
        identity = self._outcome(test, "skip", reason=str(reason)[:8192])
        super().addSkip(test, reason)
        self.skipped[-1] = (identity, str(reason))

    def addExpectedFailure(self, test, err):
        self._outcome(test, "expected_failure")
        super().addExpectedFailure(test, err)
        self.expectedFailures[-1] = (self.getDescription(test), self.expectedFailures[-1][1])

    def addUnexpectedSuccess(self, test):
        self._outcome(test, "unexpected_success")
        super().addUnexpectedSuccess(test)
        self.unexpectedSuccesses[-1] = self.getDescription(test)

    def addSubTest(self, test, subtest, err):
        outcome = "success" if err is None else (
            "failure" if issubclass(err[0], test.failureException) else "error")
        self._outcome(subtest, outcome)
        super().addSubTest(test, subtest, err)
        if err is not None:
            records = self.failures if outcome == "failure" else self.errors
            records[-1] = (self.getDescription(subtest), records[-1][1])

    def finalize(self):
        expected = Counter(self.test_ids)
        terminal = Counter()
        for (identity, _), count in self.outcomes.items():
            terminal[identity] += count
        discrepancies = {"duplicate_discovered_ids": sorted(i for i, n in expected.items() if n != 1)}
        for name, observed in (("started", self.starts), ("stopped", self.stops), ("outcome", terminal)):
            discrepancies["missing_" + name + "_ids"] = sorted(set(expected) - set(observed))
            discrepancies["unexpected_" + name + "_ids"] = sorted(set(observed) - set(expected))
            discrepancies["duplicate_" + name + "_ids"] = sorted(i for i, n in observed.items() if n != 1)
        non_successful = sorted(i for i in expected if self.outcomes[(i, "success")] != 1
                                or terminal[i] != 1)
        outcome_counts = Counter()
        for (_, outcome), count in self.outcomes.items():
            outcome_counts[outcome] += count
        coverage_complete = bool(expected) and not any(discrepancies.values())
        order_matches = self.start_order == list(self.test_ids)
        counts_match = self.testsRun == len(self.test_ids)
        self.strict_success = bool(self.execution_completed and not self.abort and coverage_complete
                                   and order_matches and counts_match and not self.loader_errors and not non_successful
                                   and not self.fixture_counts
                                   and not any(v for k, v in self.subtest_counts.items() if k != "success")
                                   and super().wasSuccessful() and not self.skipped
                                   and not self.expectedFailures)
        self.summary = {
            "schema_version": 1, "scope": SCOPE, "strict_success": self.strict_success,
            "execution_completed": self.execution_completed, "coverage_complete": coverage_complete,
            "order_matches": order_matches, "counts_match": counts_match, "discovered_count": len(self.test_ids),
            "discovered_sha256": _ids_digest(self.test_ids), "tests_run": self.testsRun,
            "started_count": sum(self.starts.values()), "stopped_count": sum(self.stops.values()),
            "outcome_counts": dict(outcome_counts), "fixture_counts": dict(self.fixture_counts),
            "subtest_counts": dict(self.subtest_counts), "non_successful_ids": non_successful,
            "loader_errors": self.loader_errors, "abort": self.abort,
            "event_count": self.event_count, "duration_seconds": round(time.monotonic() - self._started, 6),
            **discrepancies,
        }
        return self.summary


def run_suite(suite, *, stream=None, event_sink=None, loader_errors=()):
    """Execute a supplied suite once; this helper alone does not qualify source."""
    identities = collect_test_ids(suite)
    errors = list(loader_errors)
    errors.extend("unittest loader failure: " + item for item in identities
                  if item.startswith("unittest.loader._FailedTest."))
    result = None

    def result_factory(*args, **kwargs):
        nonlocal result
        result = StrictResult(*args, test_ids=identities, event_sink=event_sink,
                              loader_errors=errors, **kwargs)
        return result

    runner = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=result_factory)
    if not identities or len(set(identities)) != len(identities) or errors:
        result = runner._makeResult()
        for error in errors:
            runner.stream.writeln(error)
        runner.stream.writeln("Strict governance rejected empty, duplicate, or failed discovery.")
    else:
        try:
            runner.run(suite)
            result.execution_completed = True
        except BaseException as exc:
            if result is None:
                raise
            result.abort = {"type": type(exc).__name__, "message": str(exc)[:8192]}
            traceback.print_exc(file=runner.stream)
    result.finalize()
    return result


def _file_identity(path):
    requested = Path(path).absolute()
    resolved = requested.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > MAX_TOOL_BYTES:
        raise ValueError("tool identity requires a bounded regular file")
    digest = hashlib.sha256()
    with resolved.open("rb") as source:
        size = 0
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            size += len(chunk)
            if size > MAX_TOOL_BYTES:
                raise ValueError("tool exceeds identity size limit")
            digest.update(chunk)
    return {"requested_path": str(requested), "resolved_path": str(resolved),
            "size_bytes": size, "sha256": digest.hexdigest()}


def _git(args, *, deadline=None, root=None, raw=False, returncodes=(0,)):
    executable = shutil.which("git")
    if executable is None:
        raise ValueError("Git is required for governance source identity")
    deadline = min(deadline if deadline is not None else float("inf"), time.monotonic() + 10)
    environment = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    environment.update(GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0",
                       GIT_NO_LAZY_FETCH="1", GIT_NO_REPLACE_OBJECTS="1",
                       GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                       GIT_ALLOW_PROTOCOL="", GIT_ATTR_NOSYSTEM="1")
    process = None
    try:
        _source_time(deadline)
        process = subprocess.Popen(
            [executable, "--no-pager", "--no-optional-locks", "-c", "core.fsmonitor=false",
             "-c", "core.hooksPath=" + os.devnull, "-c", "core.untrackedCache=false", *args],
            cwd=ROOT if root is None else root, env=environment, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
        output = bytearray()
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                _source_time(deadline)
                for key, _ in selector.select(min(0.1, max(0, deadline - time.monotonic()))):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    output.extend(chunk)
                    if len(output) > MAX_GIT_BYTES:
                        raise ValueError("Git identity output exceeds limit")
        process.wait(timeout=max(0.001, deadline - time.monotonic()))
        if process.returncode not in returncodes:
            raise ValueError("Git source identity failed: " + output[:8192].decode("utf-8", "replace"))
        return bytes(output) if raw else output.decode("utf-8", "strict")
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("Git source identity is unavailable or timed out") from exc
    finally:
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            process.stdout.close()


def _source_time(deadline):
    if time.monotonic() >= deadline:
        raise ValueError("source observation timed out")


def _source_relative(value):
    parts = value.split("/")
    if (not value or value.startswith("/") or "\\" in value or ":" in value
            or len(value.encode("utf-8")) > 4096 or len(parts) > 128
            or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value)
            or any(part.lower() in ("", ".", "..", ".git")
                   or len(part.encode("utf-8")) > 255 for part in parts)):
        raise ValueError("unsafe Git source filename")
    return value


def _source_config(root, deadline):
    if _git(["config", "--includes", "--null", "--name-only", "--get-regexp", UNSAFE_SOURCE_CONFIG],
            root=root, deadline=deadline, returncodes=(0, 1)):
        raise ValueError("source uses executable filters or deferred object retrieval")
    sparse = _git(["config", "--includes", "--bool", "--get", "core.sparsecheckout"],
                  root=root, deadline=deadline, returncodes=(0, 1)).strip()
    if sparse not in ("", "false"):
        raise ValueError("sparse source checkout is not a complete governance population")


def _source_entries(output, *, index, oid_length):
    records = output.split(b"\0")
    if records[-1] or len(records) - 1 > MAX_SOURCE_FILES:
        raise ValueError("source inventory is malformed or exceeds its entry limit")
    entries = {}
    for record in records[:-1]:
        metadata, separator, name = record.partition(b"\t")
        if not separator:
            raise ValueError("source inventory is malformed")
        name = _source_relative(name.decode("utf-8", "strict"))
        fields = metadata.decode("ascii").split(" ")
        if index:
            if len(fields) != 4 or fields[0] != "H" or fields[3] != "0":
                raise ValueError("source index has hidden, sparse, or unresolved entries")
            _, mode, oid, _ = fields
        else:
            if len(fields) != 3:
                raise ValueError("source tree is malformed")
            mode, kind, oid = fields
            if kind != ("commit" if mode == "160000" else "blob"):
                raise ValueError("source tree has an unsupported member type")
        if (mode not in ("100644", "100755", "120000", "160000")
                or not re.fullmatch(r"[0-9a-f]{" + str(oid_length) + r"}", oid)
                or name in entries):
            raise ValueError("source inventory has malformed or duplicate entries")
        entries[name] = (mode, oid)
    return entries


def _source_state(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


class _SourceChain:
    """Keep source traversal anchored to checked, non-symlink directories."""

    def __init__(self, root):
        if (os.name != "posix" or not hasattr(os, "O_NOFOLLOW")
                or not hasattr(os, "O_DIRECTORY") or os.open not in os.supports_dir_fd
                or os.stat not in os.supports_follow_symlinks):
            raise ValueError("source observation requires no-follow filesystem access")
        self.descriptors, self.links = [], []
        self.flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK
        try:
            self.descriptors.append(os.open("/", self.flags))
            for part in Path(root).parts[1:]:
                descriptor, link = self._open(self.descriptors[-1], part)
                self.descriptors.append(descriptor)
                self.links.append(link)
        except BaseException:
            self.close()
            raise

    def _open(self, parent, name):
        before = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISDIR(before.st_mode):
            raise ValueError("source parent is not a real directory")
        descriptor = os.open(name, self.flags, dir_fd=parent)
        expected = before.st_dev, before.st_ino
        current = os.fstat(descriptor)
        if (current.st_dev, current.st_ino) != expected:
            os.close(descriptor)
            raise ValueError("source parent changed during traversal")
        return descriptor, (parent, name, descriptor, expected)

    @staticmethod
    def _check(links):
        for parent, name, descriptor, expected in links:
            for info in (os.stat(name, dir_fd=parent, follow_symlinks=False), os.fstat(descriptor)):
                if not stat.S_ISDIR(info.st_mode) or (info.st_dev, info.st_ino) != expected:
                    raise ValueError("source parent changed during observation")

    @contextlib.contextmanager
    def parent(self, relative):
        links, descriptors = [], []
        try:
            self._check(self.links)
            parent = self.descriptors[-1]
            parts = relative.split("/")
            for part in parts[:-1]:
                parent, link = self._open(parent, part)
                descriptors.append(parent)
                links.append(link)
            yield parent, parts[-1]
            self._check(links)
            self._check(self.links)
        finally:
            for descriptor in reversed(descriptors):
                os.close(descriptor)

    def close(self):
        for descriptor in reversed(self.descriptors):
            os.close(descriptor)
        self.descriptors.clear()


def _read_source_member(chain, relative, algorithm, budget):
    _source_time(budget["deadline"])
    try:
        with chain.parent(relative) as (parent, name):
            before = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISREG(before.st_mode) and not stat.S_ISLNK(before.st_mode):
                raise ValueError("tracked source is not a regular file or symlink")
            budget["bytes"] += before.st_size
            if not 0 <= before.st_size <= MAX_SOURCE_FILE_BYTES or budget["bytes"] > MAX_SOURCE_BYTES:
                raise ValueError("tracked source exceeds its byte limit")
            digest = hashlib.new(algorithm, b"blob " + str(before.st_size).encode("ascii") + b"\0")
            if stat.S_ISLNK(before.st_mode):
                contents = os.readlink(os.fsencode(name), dir_fd=parent)
                if len(contents) != before.st_size:
                    raise ValueError("source symlink changed during observation")
                digest.update(contents)
                mode = "120000"
            else:
                descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                try:
                    if _source_state(os.fstat(descriptor)) != _source_state(before):
                        raise ValueError("source file changed while opening")
                    size = 0
                    while True:
                        _source_time(budget["deadline"])
                        chunk = os.read(descriptor, min(65536, before.st_size - size + 1))
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > before.st_size:
                            raise ValueError("source file grew during observation")
                        digest.update(chunk)
                    if size != before.st_size or _source_state(os.fstat(descriptor)) != _source_state(before):
                        raise ValueError("source file changed during observation")
                finally:
                    os.close(descriptor)
                mode = "100755" if before.st_mode & stat.S_IXUSR else "100644"
            if _source_state(os.stat(name, dir_fd=parent, follow_symlinks=False)) != _source_state(before):
                raise ValueError("source member changed during observation")
            budget["states"].append((relative, _source_state(before)))
            return mode, digest.hexdigest()
    except FileNotFoundError:
        budget["states"].append((relative, None))
        return None


def _source_digest(entries):
    digest = hashlib.sha256()
    for name, identity in sorted(entries.items()):
        mode, oid = identity if identity is not None else ("missing", "")
        digest.update((mode + " " + oid + "\t" + name + "\0").encode("utf-8"))
    return digest.hexdigest()


def _source_python_inventory(entries, deadline):
    ignored = _git(["ls-files", "--others", "--ignored", "--exclude-standard", "-z"],
                   deadline=deadline, raw=True).split(b"\0")
    if ignored[-1] or len(ignored) - 1 > MAX_SOURCE_FILES:
        raise ValueError("ignored source inventory is malformed or exceeds its entry limit")
    for raw in ignored[:-1]:
        _source_time(deadline)
        name = _source_relative(raw.decode("utf-8", "strict"))
        if Path(name).suffix.lower() in (".py", ".pyc", ".pyo"):
            raise ValueError("ignored Python source or cached bytecode is not bound to HEAD: " + name)
    for name in entries:
        _source_time(deadline)
        if Path(name).suffix.lower() in (".pyc", ".pyo"):
            raise ValueError("tracked Python bytecode cannot establish source execution: " + name)
        # Git does not descend into an ignored __pycache__ symlink. Check the
        # active cache path even without a redirected cache prefix, before any
        # local module can load and remove an unbound cache during import.
        if name.endswith(".py"):
            cached = importlib.util.cache_from_source(str(ROOT / name))
            if os.path.lexists(cached):
                raise ValueError("local Python source has unbound cached bytecode: " + name)


def _source_submodules(entries, deadline):
    value = _git(["submodule", "status", "--recursive"], deadline=deadline)
    observations = {}
    for line in value.splitlines():
        match = re.fullmatch(r"([-+ U])([0-9a-f]{40}|[0-9a-f]{64}) ([^\s()]+)(?: \([^\r\n]*\))?", line)
        if not match or len(observations) >= MAX_GITLINKS:
            raise ValueError("submodule identity is malformed or exceeds its limit")
        status, oid, name = match.groups()
        name = _source_relative(name)
        if name in observations or status == "U":
            raise ValueError("submodule identity is duplicate or unresolved")
        observations[name] = {"path": name, "oid": oid, "status": status}
        if status != "-":
            chain = _SourceChain(ROOT / name)
            try:
                _source_config(ROOT / name, deadline)
                chain._check(chain.links)
            finally:
                chain.close()
    links = []
    for name, (mode, oid) in sorted(entries.items()):
        if mode == "160000":
            if name not in observations:
                raise ValueError("tracked gitlink is missing its submodule state")
            links.append({**observations[name], "pinned_oid": oid})
    return value, links


def _source_metadata(deadline):
    _source_config(ROOT, deadline)
    top = Path(_git(["rev-parse", "--show-toplevel"], deadline=deadline).strip())
    if top != ROOT:
        raise ValueError("runner is not in its source checkout root")
    head = _git(["rev-parse", "--verify", "HEAD"], deadline=deadline).strip()
    tree = _git(["rev-parse", "--verify", "HEAD^{tree}"], deadline=deadline).strip()
    if not all(re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value) for value in (head, tree)):
        raise ValueError("invalid Git source identity")
    index = _source_entries(_git(["ls-files", "-v", "--stage", "-z"], deadline=deadline, raw=True),
                            index=True, oid_length=len(head))
    entries = _source_entries(_git(["ls-tree", "-r", "-z", "HEAD"], deadline=deadline, raw=True),
                              index=False, oid_length=len(head))
    _source_python_inventory(entries, deadline)
    submodules, gitlinks = _source_submodules(entries, deadline)
    # Config safety precedes status because even a read-only status can run filters.
    status = _git(["status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignore-submodules=none"],
                  deadline=deadline)
    return head, tree, index, entries, status, submodules, gitlinks


def _bound_python_sources(entries):
    for module in tuple(sys.modules.values()):
        filename = getattr(module, "__file__", None)
        if not isinstance(filename, str):
            continue
        path = Path(filename).absolute()
        if not path.is_relative_to(ROOT):
            continue
        relative = _source_relative(path.relative_to(ROOT).as_posix())
        if entries.get(relative, (None,))[0] not in ("100644", "100755"):
            raise ValueError("local Python input is not bound to HEAD: " + relative)
        if path.resolve(strict=True) != path:
            raise ValueError("local Python input traverses an unbound symlink: " + relative)
        cached = getattr(module, "__cached__", None)
        if isinstance(cached, str) and os.path.lexists(cached):
            raise ValueError("local Python input has unbound cached bytecode: " + relative)


def source_snapshot():
    """Bind materialized raw source to HEAD without a native submodule closure."""
    deadline = time.monotonic() + MAX_SOURCE_SECONDS
    chain = _SourceChain(ROOT)
    try:
        metadata = _source_metadata(deadline)
        head, tree, index, entries, status, submodules, gitlinks = metadata
        names = entries.keys() | index.keys()
        if len(names) > MAX_SOURCE_FILES:
            raise ValueError("source inventory exceeds its entry limit")
        changed = {name for name in names if entries.get(name) != index.get(name)}
        budget = {"deadline": deadline, "bytes": 0, "states": []}
        observed = {}
        for name in sorted(names):
            expected = entries.get(name)
            mode, oid = expected if expected is not None else index[name]
            observed[name] = ((mode, oid) if mode == "160000" else
                              _read_source_member(chain, name, "sha1" if len(head) == 40 else "sha256", budget))
            if observed[name] != expected:
                changed.add(name)
        if not status and not changed:
            _bound_python_sources(entries)
        if _source_metadata(deadline) != metadata:
            raise ValueError("source metadata changed during observation")
        for name, expected in budget["states"]:
            _source_time(deadline)
            try:
                with chain.parent(name) as (parent, member):
                    current = _source_state(os.stat(member, dir_fd=parent, follow_symlinks=False))
            except FileNotFoundError:
                current = None
            if current != expected:
                raise ValueError("source member changed during observation")
        chain._check(chain.links)
        return {"root": str(ROOT), "head": head, "tree": tree, "clean": not status and not changed,
                "status_porcelain": status, "submodules": submodules, "gitlinks": gitlinks,
                "tracked_count": len(entries), "tracked_sha256": _source_digest(entries),
                "index_sha256": _source_digest(index), "worktree_sha256": _source_digest(observed),
                "tracked_bytes": budget["bytes"], "mismatch_count": len(changed),
                "mismatches": sorted(changed)[:32], "git": _file_identity(shutil.which("git"))}
    except (OSError, UnicodeError) as exc:
        raise ValueError("source observation is unsafe, incomplete, or unstable") from exc
    finally:
        chain.close()


def interpreter_snapshot():
    return {"executable": _file_identity(sys.executable), "version": sys.version,
            "implementation": platform.python_implementation(), "platform": sys.platform,
            "prefix": sys.prefix, "base_prefix": sys.base_prefix, "path": os.environ.get("PATH", "")}


def environment_snapshot(path):
    """Bind the fixed preparation receipt by inert rehashing, never command execution."""
    path = Path(path)
    if not path.is_absolute() or not path.is_file() or path.stat().st_size > 1024**2:
        raise ValueError("environment receipt must be a bounded absolute regular file")
    raw = path.read_bytes()
    if len(raw) > 1024**2:
        raise ValueError("environment receipt exceeds limit")

    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate environment receipt key")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError("nonfinite environment receipt number: " + value)

    receipt = json.loads(raw, object_pairs_hook=object_pairs, parse_constant=invalid_constant)
    if not isinstance(receipt, dict) or type(receipt.get("schema_version")) is not int \
            or receipt["schema_version"] != 1 or receipt.get("status") != "ready":
        raise ValueError("environment preparation receipt is not ready schema 1")
    interpreter = str(Path(sys.executable).absolute())
    restricted_path = os.pathsep.join((str(Path(interpreter).parent), "/usr/bin", "/bin"))
    if receipt.get("interpreter") != interpreter or receipt.get("environment", {}).get("PATH") != restricted_path:
        raise ValueError("environment receipt does not select this interpreter and restricted PATH")
    if os.environ.get("PATH") != restricted_path:
        raise ValueError("active PATH differs from the prepared restricted PATH")
    tools = receipt.get("tools")
    if not isinstance(tools, dict) or not REQUIRED_ENVIRONMENT_TOOLS <= tools.keys() or len(tools) > 64:
        raise ValueError("environment receipt tool inventory is incomplete or oversized")

    def check(identity):
        if not isinstance(identity, dict) or not isinstance(identity.get("path"), str) \
                or not Path(identity["path"]).is_absolute():
            raise ValueError("invalid environment tool path")
        observed = _file_identity(identity["path"])
        if not os.access(identity["path"], os.X_OK) or any(
                identity.get(key) != observed[key] for key in ("resolved_path", "sha256", "size_bytes")):
            raise ValueError("environment tool identity changed: " + identity["path"])
        if type(identity.get("size_bytes")) is not int:
            raise ValueError("invalid environment tool size")
        return observed

    observed_tools = {}
    for name, identity in sorted(tools.items()):
        if not isinstance(name, str) or "/" in name or "\\" in name or not name:
            raise ValueError("invalid environment tool alias")
        observed_tools[name] = check(identity)
        if shutil.which(name, path=restricted_path) != identity["path"]:
            raise ValueError("restricted tool alias differs from preparation: " + name)
    selection = receipt.get("cmake_selection", {})
    if selection.get("resolution") not in ("native", "python-package"):
        raise ValueError("invalid selected CMake resolution")
    return {"receipt_path": str(path), "receipt_sha256": hashlib.sha256(raw).hexdigest(),
            "receipt_size_bytes": len(raw), "tools": observed_tools,
            "cmake_selection": {key: check(selection.get(key)) for key in ("requested", "native")}}


def _write_json(path, value):
    encoded = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if len(encoded) > MAX_RECORD_BYTES:
        raise ValueError("governance JSON record exceeds limit")
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("xb") as target:
        target.write(encoded)
        target.flush()
        os.fsync(target.fileno())
    os.replace(temporary, path)


class _BoundedLog:
    """Bound Python stdout/stderr text streams; the workflow tee retains OS/child output."""

    def __init__(self, target, original, state):
        self.target, self.original, self.state = target, original, state

    def write(self, value):
        self.original.write(value)
        self.original.flush()
        size = len(value.encode("utf-8", errors="replace"))
        if self.state["bytes"] + size <= MAX_LOG_BYTES and not self.state["truncated"]:
            self.target.write(value)
            self.target.flush()
            self.state["bytes"] += size
        else:
            self.state["truncated"] = True
        return len(value)

    def flush(self):
        self.original.flush()
        self.target.flush()

    def __getattr__(self, name):
        return getattr(self.original, name)


def _fresh_output(value):
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or path.resolve() != path:
        raise ValueError("output directory must be an exact absolute path without symlink components")
    if path.is_relative_to(ROOT) or ROOT.is_relative_to(path):
        raise ValueError("output directory must be outside the source checkout")
    path.mkdir(mode=0o700, exist_ok=False)
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True,
                        help="fresh absolute directory outside the source checkout")
    parser.add_argument("--environment-receipt", required=True,
                        help="inert governance_env.py preparation receipt")
    args = parser.parse_args(argv)
    try:
        output = _fresh_output(args.output_dir)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    started = _utc_now()
    receipt = {"schema_version": 1, "scope": SCOPE, "status": "started", "started_at": started,
               "governance_passed": False, "execution_completed": False,
               "source_root": str(ROOT), "discovery": DISCOVERY,
               "command": [sys.executable, str(Path(__file__).resolve()), "--output-dir", str(output)]}
    receipt["command"].extend(("--environment-receipt", args.environment_receipt))
    _write_json(output / "started.json", receipt)
    summary = {**receipt, "status": "incomplete", "errors": []}
    log_state = {"bytes": 0, "truncated": False}
    event_bytes = 0
    previous_cwd = Path.cwd()
    try:
        os.chdir(ROOT)
        with (output / "unittest.log").open("x", encoding="utf-8") as log, \
                (output / "events.jsonl").open("x", encoding="utf-8") as events:
            def emit(event):
                nonlocal event_bytes
                line = json.dumps(event, sort_keys=True) + "\n"
                event_bytes += len(line.encode("utf-8"))
                if event_bytes > MAX_RECORD_BYTES:
                    raise ValueError("governance event evidence exceeds limit")
                events.write(line)
                events.flush()

            with contextlib.redirect_stdout(_BoundedLog(log, sys.stdout, log_state)), \
                    contextlib.redirect_stderr(_BoundedLog(log, sys.stderr, log_state)):
                summary["source_before"] = source_snapshot()
                summary["interpreter_before"] = interpreter_snapshot()
                summary["environment_before"] = environment_snapshot(args.environment_receipt)
                receipt.update({key: summary[key] for key in (
                    "source_before", "interpreter_before", "environment_before")})
                _write_json(output / "started.json", receipt)
                if not summary["source_before"]["clean"]:
                    raise ValueError("governance qualification requires a clean source checkout")
                loader = unittest.TestLoader()
                suite = loader.discover(DISCOVERY["start_directory"], pattern=DISCOVERY["pattern"])
                identities = collect_test_ids(suite)
                _write_json(output / "discovered.json", {
                    "schema_version": 1, "scope": SCOPE, "discovery": DISCOVERY,
                    "test_ids": identities, "count": len(identities), "sha256": _ids_digest(identities)})
                result = run_suite(suite, stream=sys.stderr, event_sink=emit, loader_errors=loader.errors)
                summary["execution"] = result.summary
                summary["execution_completed"] = result.execution_completed
                summary["source_after"] = source_snapshot()
                summary["interpreter_after"] = interpreter_snapshot()
                summary["environment_after"] = environment_snapshot(args.environment_receipt)
                summary["source_stable"] = summary["source_before"] == summary["source_after"]
                summary["interpreter_stable"] = summary["interpreter_before"] == summary["interpreter_after"]
                summary["environment_stable"] = summary["environment_before"] == summary["environment_after"]
                summary["governance_passed"] = bool(
                    result.strict_success and tuple(identities) == result.test_ids
                    and summary["source_after"]["clean"] and summary["source_stable"]
                    and summary["interpreter_stable"] and summary["environment_stable"]
                    and not log_state["truncated"])
                summary["status"] = "completed" if result.execution_completed else "incomplete"
    except BaseException as exc:
        summary["governance_passed"] = False
        summary["errors"].append({"type": type(exc).__name__, "message": str(exc)[:8192]})
        traceback.print_exc()
    finally:
        os.chdir(previous_cwd)
    summary.update(finished_at=_utc_now(), log=log_state, event_bytes=event_bytes)
    _write_json(output / "summary.json", summary)
    print("Strict governance " + ("PASSED" if summary["governance_passed"] else "FAILED")
          + ": " + str(output / "summary.json"))
    return 0 if summary["governance_passed"] else 1


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    raise SystemExit(main())
