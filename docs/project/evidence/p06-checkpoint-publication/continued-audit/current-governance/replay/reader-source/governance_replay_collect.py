# SPDX-License-Identifier: Apache-2.0
"""Collect canonical IDs by importing an explicit trusted checkout in a child.

The selected source is executable trusted input; this is not a Python sandbox.
No retained artifact code is imported, and no unittest runner or body is called.
"""

import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import tempfile
import time

from governance_replay_source import SourceBindingError, _entries, _git, source_binding


MAX_TESTS = 100_000
MAX_ID_BYTES = 4096
MAX_INPUT_BYTES = 8 * 1024**2
MAX_OUTPUT_BYTES = 32 * 1024**2
MAX_DIAGNOSTIC_BYTES = 1024**2
MAX_CHILD_SECONDS = 60
MAX_CHILD_MEMORY_BYTES = 1024**3


class ReplayCollectError(ValueError):
    """Trusted canonical collection was incomplete, unsafe, or unstable."""


_CHILD = r'''
import contextlib
import hashlib
import importlib.machinery
import json
import math
import os
from pathlib import Path
import resource
import stat
import sys
import typing
import unittest


def main():
    request = json.loads(sys.stdin.buffer.read(8 * 1024**2 + 1).decode("utf-8"))
    root = request["root"]
    bound = request["python"]
    limits = request["limits"]
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    memory = limits["memory"]
    resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    cpu = max(1, math.ceil(limits["seconds"]))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
    resource.setrlimit(resource.RLIMIT_FSIZE, (8 * 1024**2, 8 * 1024**2))
    if os.getcwd() != root or not (sys.flags.isolated and sys.flags.no_site
                                  and sys.dont_write_bytecode):
        raise ValueError("collector isolation is unavailable")

    original_paths = tuple(sys.path)
    interpreter_aliases = {name: module for name, module in sys.modules.items()
                          if getattr(module, "__spec__", None) is None}
    standard_dirs = tuple(os.path.realpath(path) for path in original_paths
                          if os.path.isdir(path))
    standard_archives = tuple(os.path.realpath(path) for path in original_paths
                              if path.endswith(".zip"))
    loaded_source = set()

    def below(path, directory):
        return path == directory or path.startswith(directory + os.sep)

    def path_kind(filename, *, directory=False):
        path = os.path.abspath(os.fspath(filename))
        real = os.path.realpath(path)
        if below(path, root) or below(real, root):
            if path != real or not below(path, root):
                raise ValueError("linked source import")
            relative = os.path.relpath(path, root).replace(os.sep, "/")
            if directory:
                prefix = "" if relative == "." else relative + "/"
                if not any(name.startswith(prefix) for name in bound):
                    raise ValueError("unbound source namespace")
            elif relative not in bound:
                raise ValueError("unbound source import")
            return "source", path, relative
        if any(part in ("site-packages", "dist-packages") for part in Path(real).parts):
            raise ValueError("third-party interpreter import")
        if (any(below(real, directory) for directory in standard_dirs)
                or any(real.startswith(archive + os.sep) for archive in standard_archives)):
            return "standard", path, None
        raise ValueError("external Python import")

    def state(info):
        return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
                info.st_mtime_ns, info.st_ctime_ns)

    def source_bytes(path, relative):
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode) or not 0 <= before.st_size <= 128 * 1024**2:
                raise ValueError("nonregular or oversized Python source")
            expected_mode, expected_oid = bound[relative]
            mode = "100755" if before.st_mode & stat.S_IXUSR else "100644"
            if mode != expected_mode:
                raise ValueError("Python source mode changed")
            data = bytearray()
            while True:
                chunk = os.read(descriptor, min(65536, before.st_size - len(data) + 1))
                if not chunk:
                    break
                data.extend(chunk)
                if len(data) > before.st_size:
                    raise ValueError("Python source grew")
            if (len(data) != before.st_size or state(os.fstat(descriptor)) != state(before)
                    or state(os.stat(path, follow_symlinks=False)) != state(before)):
                raise ValueError("Python source changed")
            digest = hashlib.new(request["algorithm"],
                                 b"blob " + str(len(data)).encode("ascii") + b"\0")
            digest.update(data)
            if digest.hexdigest() != expected_oid:
                raise ValueError("Python source differs from the selected revision")
            loaded_source.add((path, relative))
            return bytes(data)
        finally:
            os.close(descriptor)

    machinery = importlib.machinery
    original_source_code = machinery.SourceFileLoader.get_code
    original_bytecode = machinery.SourcelessFileLoader.get_code
    original_extension_create = machinery.ExtensionFileLoader.create_module
    original_extension_exec = machinery.ExtensionFileLoader.exec_module

    def source_code(loader, fullname):
        kind, path, relative = path_kind(loader.path)
        if kind == "source":
            return compile(source_bytes(path, relative), path, "exec", dont_inherit=True)
        return original_source_code(loader, fullname)

    def bytecode(loader, fullname):
        if path_kind(loader.path)[0] != "standard":
            raise ValueError("unbound Python bytecode")
        return original_bytecode(loader, fullname)

    def extension_create(loader, spec):
        if path_kind(loader.path)[0] != "standard":
            raise ValueError("unbound native Python module")
        return original_extension_create(loader, spec)

    def extension_exec(loader, module):
        if path_kind(loader.path)[0] != "standard":
            raise ValueError("unbound native Python module")
        return original_extension_exec(loader, module)

    machinery.SourceFileLoader.get_code = source_code
    machinery.SourcelessFileLoader.get_code = bytecode
    machinery.ExtensionFileLoader.create_module = extension_create
    machinery.ExtensionFileLoader.exec_module = extension_exec

    def check_spec(spec):
        if spec.origin in ("built-in", "frozen"):
            expected = machinery.BuiltinImporter if spec.origin == "built-in" else machinery.FrozenImporter
            if spec.loader is not expected:
                raise ValueError("unbound interpreter loader")
        elif spec.origin is None:
            if spec.submodule_search_locations is None:
                raise ValueError("unbound Python module")
            for path in spec.submodule_search_locations:
                path_kind(path, directory=True)
        else:
            kind, _path, _relative = path_kind(spec.origin)
            if kind == "source" and not isinstance(spec.loader, machinery.SourceFileLoader):
                raise ValueError("unbound source loader")

    original_finders = tuple(sys.meta_path)

    class BoundFinder:
        @staticmethod
        def find_spec(fullname, path=None, target=None):
            for finder in original_finders:
                spec = finder.find_spec(fullname, path, target)
                if spec is not None:
                    check_spec(spec)
                    return spec
            return None

    sys.meta_path[:] = [BoundFinder]
    sys.path[:] = [os.path.join(root, "ci", "project"), *original_paths]
    suite_type, case_type = unittest.TestSuite, unittest.TestCase
    loader = unittest.TestLoader()
    with contextlib.redirect_stdout(sys.stderr):
        suite = loader.discover("ci/project", pattern="test_*.py")
        if loader.errors:
            raise ValueError("unittest loader errors")
        identities, unique = [], set()
        stack, active, nodes, output_bytes = [(iter((suite,)), None)], set(), 0, 2
        while stack:
            iterator, parent = stack[-1]
            try:
                node = next(iterator)
            except StopIteration:
                stack.pop()
                if parent is not None:
                    active.remove(parent)
                continue
            nodes += 1
            if nodes > 4 * limits["tests"] or len(stack) > 256:
                raise ValueError("oversized or cyclic unittest suite")
            if isinstance(node, suite_type):
                if id(node) in active:
                    raise ValueError("cyclic unittest suite")
                active.add(id(node))
                stack.append((iter(node), id(node)))
                continue
            if not isinstance(node, case_type):
                raise ValueError("non-test unittest leaf")
            identity = node.id()
            if (type(identity) is not str or not identity
                    or len(identity.encode("utf-8")) > limits["id_bytes"]
                    or identity.startswith("unittest.loader._FailedTest.")
                    or identity in unique):
                raise ValueError("invalid or duplicate unittest identity")
            identities.append(identity)
            unique.add(identity)
            output_bytes += len(json.dumps(identity, ensure_ascii=False).encode("utf-8")) + 1
            if len(identities) > limits["tests"] or output_bytes > limits["output"]:
                raise ValueError("unittest identity output exceeds its limit")
        if not identities:
            raise ValueError("empty unittest discovery")
        for name, module in tuple(sys.modules.items()):
            if module is None or name == "__main__":
                continue
            spec = getattr(module, "__spec__", None)
            if spec is None:
                if interpreter_aliases.get(name) is module:
                    continue
                # Native stdlib modules also expose auxiliary namespace objects.
                parent, separator, attribute = name.rpartition(".")
                owner = sys.modules.get(parent)
                owner_spec = getattr(owner, "__spec__", None)
                if (separator and owner_spec is not None
                        and getattr(module, "__file__", None) is None
                        and getattr(owner, attribute, None) is module):
                    check_spec(owner_spec)
                    if (owner_spec.origin in ("built-in", "frozen")
                            or owner_spec.origin is not None
                            and path_kind(owner_spec.origin)[0] == "standard"):
                        continue
                raise ValueError("unbound imported module")
            check_spec(spec)
            filename = getattr(module, "__file__", None)
            if filename is not None:
                path_kind(filename)
        for path, relative in tuple(loaded_source):
            source_bytes(path, relative)
    result = json.dumps(identities, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(result) > limits["output"]:
        raise ValueError("unittest identity output exceeds its limit")
    sys.stdout.buffer.write(result)
    sys.stdout.buffer.flush()


try:
    main()
except BaseException:
    os.write(2, b"trusted canonical collection rejected\n")
    os._exit(1)
os._exit(0)
'''


def _kill(process):
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _run_child(root, request):
    payload = json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_INPUT_BYTES:
        raise ReplayCollectError("trusted Python inventory exceeds its input byte limit")
    process = None
    with tempfile.TemporaryDirectory(prefix="governance-replay-collect-", dir="/tmp") as temporary:
        private = Path(temporary)
        (private / "home").mkdir()
        (private / "tmp").mkdir()
        environment = {"PATH": "/usr/bin:/bin", "HOME": str(private / "home"),
                       "TMPDIR": str(private / "tmp"), "LANG": "C", "LC_ALL": "C", "TZ": "UTC"}
        with tempfile.TemporaryFile(dir=private) as input_file:
            input_file.write(payload)
            input_file.seek(0)
            try:
                deadline = time.monotonic() + MAX_CHILD_SECONDS
                process = subprocess.Popen(
                    [sys.executable, "-I", "-B", "-S", "-c", _CHILD],
                    cwd=root, env=environment, stdin=input_file,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
                output, diagnostics = bytearray(), 0
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ, "output")
                    selector.register(process.stderr, selectors.EVENT_READ, "diagnostics")
                    while selector.get_map():
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise ReplayCollectError("trusted canonical collection timed out")
                        for key, _ in selector.select(min(0.1, remaining)):
                            chunk = os.read(key.fileobj.fileno(), 65536)
                            if not chunk:
                                selector.unregister(key.fileobj)
                            elif key.data == "output":
                                output.extend(chunk)
                                if len(output) > MAX_OUTPUT_BYTES:
                                    raise ReplayCollectError("collection JSON exceeds its output byte limit")
                            else:
                                diagnostics += len(chunk)
                                if diagnostics > MAX_DIAGNOSTIC_BYTES:
                                    raise ReplayCollectError("collection diagnostics exceed their byte limit")
                        if process.poll() is not None:
                            _kill(process)
                process.wait(timeout=max(0.001, deadline - time.monotonic()))
                if process.returncode != 0:
                    raise ReplayCollectError("trusted canonical collection failed")
                return bytes(output)
            except (OSError, subprocess.TimeoutExpired) as error:
                raise ReplayCollectError("trusted canonical collection is unavailable or timed out") from error
            finally:
                if process is not None:
                    _kill(process)
                    try:
                        process.wait(timeout=5)
                    finally:
                        process.stdout.close()
                        process.stderr.close()


def _decode(raw):
    if not raw or len(raw) > MAX_OUTPUT_BYTES:
        raise ReplayCollectError("collection JSON is empty or exceeds its byte limit")
    try:
        identities = json.loads(raw.decode("utf-8"))
        if type(identities) is not list or not 0 < len(identities) <= MAX_TESTS:
            raise ValueError("invalid identity population")
        unique = set()
        for identity in identities:
            if (type(identity) is not str or not identity or identity in unique
                    or len(identity.encode("utf-8")) > MAX_ID_BYTES
                    or identity.startswith("unittest.loader._FailedTest.")):
                raise ValueError("invalid identity")
            unique.add(identity)
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise ReplayCollectError("collection JSON contains invalid or duplicate unittest identities") from error
    return identities


def collect(source_dir, revision):
    """Return ordered canonical IDs; importing this trusted source executes its code."""
    try:
        before = source_binding(source_dir, revision)
        root = Path(source_dir)
        entries = _entries(_git(root, ["ls-tree", "-r", "-z", revision],
                                time.monotonic() + 30), len(revision))
        digest = hashlib.sha256()
        for name, (mode, oid) in sorted(entries.items()):
            digest.update((mode + " " + oid + "\t" + name + "\0").encode("utf-8"))
        if digest.hexdigest() != before["tracked_sha256"] or len(entries) != before["tracked_count"]:
            raise ReplayCollectError("trusted Python inventory differs from the source binding")
        python = {name: [mode, oid] for name, (mode, oid) in entries.items()
                  if name.endswith(".py") and mode in ("100644", "100755")}
        request = {"root": str(root), "algorithm": before["object_format"], "python": python,
                   "limits": {"tests": MAX_TESTS, "id_bytes": MAX_ID_BYTES,
                              "output": MAX_OUTPUT_BYTES, "seconds": MAX_CHILD_SECONDS,
                              "memory": MAX_CHILD_MEMORY_BYTES}}
        identities = _decode(_run_child(root, request))
        if source_binding(source_dir, revision) != before:
            raise ReplayCollectError("trusted source changed during canonical collection")
        return identities
    except SourceBindingError as error:
        raise ReplayCollectError("trusted source binding rejected canonical collection") from error
