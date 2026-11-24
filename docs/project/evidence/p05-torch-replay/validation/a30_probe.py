#!/usr/bin/env python3
"""Complete P05 replay under a deny-by-default Python boundary observation.

Only this external probe is modified. Semantic replay functions are not patched.
The trusted local archive reader import is allowed by exact source/code identity.
This is host observation, not an OS sandbox or native GPU execution evidence.
"""
from __future__ import annotations

import argparse
import ast
import builtins
from collections import Counter
import ctypes
import _ctypes
import _imp
import email.feedparser
import email.headerregistry
import email.message
import email.parser
import email.policy
import encodings.ascii
import encodings.cp437
import encodings.latin_1
import encodings.utf_8
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import marshal
import os
from pathlib import Path
import shutil
import socket
import _socket
import stat
import subprocess
import sys
import tarfile
import time
import traceback
import types
import zipfile

sys.dont_write_bytecode = True

DEFAULT_SHA = "8c42f7e9f310972e2c0c67c56a03ce8f5460d706cb8dc3a5397435445ea6737c"
DEFAULT_REV = "c0b44ce64665fe11895f869eea8c38c9b820d6f7"
BASE = "f01c9d03147343d274ee0a45b71b34f004709c0e"


def digest_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        while raw := stream.read(1024 * 1024):
            digest.update(raw)
    return digest.hexdigest()


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args])


def static_inventory(repo, paths):
    """Scan full local Python inputs for actual AST calls, not string snippets."""
    names = {
        "open", "read_bytes", "read_text", "resolve", "realpath", "stat", "lstat", "readlink",
        "extract", "extractall", "extractfile", "_extract_member", "unpack_archive", "exec", "eval",
        "compile", "exec_module", "load_module", "import_module", "spec_from_file_location",
        "Popen", "run", "call", "check_call", "check_output", "system", "popen", "fork",
        "posix_spawn", "socket", "connect", "getaddrinfo", "CDLL", "PyDLL", "dlopen", "LoadLibrary",
    }
    rows = []
    for path in sorted(paths):
        if path.suffix != ".py":
            continue
        raw = path.read_bytes()
        tree = ast.parse(raw, filename=str(path))
        parents = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            leaf = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", None)
            if leaf not in names:
                continue
            owner, current = [], node
            while current in parents:
                current = parents[current]
                if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    owner.append(current.name)
            rows.append({"path": str(path.relative_to(repo)), "line": node.lineno,
                         "owner": ".".join(reversed(owner)) or "<module>",
                         "call": ast.unparse(node.func)})
    return rows


class BoundaryDenied(PermissionError):
    pass


class Guard:
    def __init__(self, repo, archive, sources, reader_path, reader_raw, reader_code):
        self.repo = str(repo)
        self.archive = str(archive)
        self.reader_path = str(reader_path)
        self.reader_raw_sha = hashlib.sha256(reader_raw).hexdigest()
        self.reader_code_sha = hashlib.sha256(marshal.dumps(reader_code)).hexdigest()
        self.cache_path = importlib.util.cache_from_source(self.reader_path)
        self.allowed = {self.archive, *(str(repo / row["path"]) for row in sources)}
        self.metadata = set(self.allowed)
        for path in self.allowed:
            self.metadata.update(str(parent) for parent in Path(path).parents)
        self.identities = {(os.stat(path).st_dev, os.stat(path).st_ino): path for path in self.allowed}
        self.original_fstat = os.fstat
        self.cwd = os.getcwd()
        self.active = False
        self.phase = "setup"
        self.ast_compile = 0
        self.events = Counter()
        self.functions = Counter()
        self.hash_checks = []
        self.closes = []
        self.patches = []
        self.local_python = {path for path in self.allowed if path.endswith(".py")}
        self.preloaded_names = frozenset(sys.modules)

    def record(self, category, target, decision="allow"):
        self.events[(self.phase, decision, category, str(target))] += 1

    def deny(self, category, target):
        self.record(category, target, "deny")
        raise BoundaryDenied(category + ": " + str(target))

    def path(self, value):
        if isinstance(value, int):
            info = self.original_fstat(value)
            name = self.identities.get((info.st_dev, info.st_ino))
            if name is None:
                self.deny("unlisted_descriptor", value)
            return name
        try:
            value = os.fsdecode(value)
        except TypeError:
            self.deny("invalid_path", type(value).__name__)
        if not os.path.isabs(value):
            value = os.path.join(self.cwd, value)
        return os.path.normpath(value)

    def permit_path(self, operation, value, *, metadata=False):
        name = self.path(value)
        if name == self.cache_path:
            # CPython catches the denied cache read and compiles the pinned source.
            self.deny("trusted_reader_cache_fallback", name)
        if name not in (self.metadata if metadata else self.allowed):
            self.deny(operation + "_unlisted_path", name)
        self.record(operation, name)
        return name

    def patch(self, owner, name, replacement):
        if hasattr(owner, name):
            self.patches.append((owner, name, getattr(owner, name)))
            setattr(owner, name, replacement)

    def blocker(self, category, name):
        def blocked(*args, **kwargs):
            if self.active:
                self.deny(category, name)
            raise AssertionError("inactive blocker called: " + name)
        return blocked

    def audit(self, event, args):
        if not self.active:
            return
        if event == "open":
            target, mode, flags = args
            name = self.path(target)
            if (isinstance(mode, str) and any(char in mode for char in "wax+")) or (
                    flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)):
                self.deny("filesystem_write", name)
            self.permit_path("open", target)
        elif event == "exec":
            code = args[0]
            digest = hashlib.sha256(marshal.dumps(code)).hexdigest()
            if code.co_filename != self.reader_path or digest != self.reader_code_sha:
                self.deny("untrusted_code_execution", code.co_filename)
            self.record("trusted_local_reader_exec", code.co_filename)
        elif event == "compile":
            source, filename = args
            if self.ast_compile:
                self.record("ast_only_parse", filename)
                return
            raw = source.encode("utf-8") if isinstance(source, str) else source
            if (filename != self.reader_path or type(raw) is not bytes
                    or hashlib.sha256(raw).hexdigest() != self.reader_raw_sha):
                self.deny("executable_compile", filename)
            self.record("trusted_local_reader_compile", filename)
        elif event == "import":
            self.deny("new_import", args[0])
        elif event.startswith(("socket.", "ctypes.", "subprocess.")):
            self.deny("network_dynamic_load_or_process", event)
        elif event in {
            "os.system", "os.fork", "os.forkpty", "os.exec", "os.posix_spawn", "os.spawn",
            "os.chdir", "os.fchdir", "os.chroot", "os.remove", "os.rmdir", "os.rename",
            "os.mkdir", "os.link", "os.symlink", "os.truncate", "os.chmod", "os.chown",
            "os.utime", "os.listdir", "os.scandir", "shutil.copyfile", "shutil.rmtree",
            "shutil.unpack_archive", "mmap.__new__",
        }:
            self.deny("filesystem_mutation_enumeration_or_process", event)

    def install(self):
        sys.addaudithook(self.audit)
        original_compile = builtins.compile
        def compiled(source, filename, mode, flags=0, dont_inherit=False, optimize=-1, **kwargs):
            if not self.active:
                return original_compile(source, filename, mode, flags, dont_inherit, optimize, **kwargs)
            ast_only = bool(flags & ast.PyCF_ONLY_AST)
            if ast_only:
                self.ast_compile += 1
            try:
                return original_compile(source, filename, mode, flags, dont_inherit, optimize, **kwargs)
            finally:
                if ast_only:
                    self.ast_compile -= 1
        self.patch(builtins, "compile", compiled)
        original_import = builtins.__import__
        def imported(name, globals=None, locals=None, fromlist=(), level=0):
            if self.active and (level or name not in self.preloaded_names):
                self.deny("unlisted_module_import", name)
            return original_import(name, globals, locals, fromlist, level)
        self.patch(builtins, "__import__", imported)
        for name in ("stat", "lstat", "readlink", "access"):
            original = getattr(os, name)
            def metadata(path, *args, _name=name, _original=original, **kwargs):
                if self.active:
                    if kwargs.get("dir_fd") is not None:
                        self.deny("relative_descriptor_resolution", _name)
                    self.permit_path(_name, path, metadata=True)
                return _original(path, *args, **kwargs)
            self.patch(os, name, metadata)
        original_resolve = Path.resolve
        def resolved(path, *args, **kwargs):
            if self.active:
                self.permit_path("Path.resolve", path, metadata=True)
            return original_resolve(path, *args, **kwargs)
        self.patch(Path, "resolve", resolved)
        original_realpath = os.path.realpath
        def realpath(path, *args, **kwargs):
            if self.active:
                self.permit_path("realpath", path, metadata=True)
            return original_realpath(path, *args, **kwargs)
        self.patch(os.path, "realpath", realpath)
        for owner, names, category in (
            (subprocess, ("Popen", "run", "call", "check_call", "check_output"), "process_launch"),
            (os, tuple(name for name in dir(os) if name.startswith(("exec", "spawn", "posix_spawn")))
                 + ("system", "popen", "fork", "forkpty"), "process_launch"),
            (socket, ("socket", "create_connection", "create_server", "socketpair", "fromfd",
                      "getaddrinfo", "gethostbyname", "gethostbyname_ex", "gethostbyaddr", "getnameinfo"), "network"),
            (_socket, ("socket", "getaddrinfo", "gethostbyname", "gethostbyname_ex", "gethostbyaddr", "getnameinfo"), "network"),
            (ctypes, ("CDLL", "PyDLL", "WinDLL", "OleDLL"), "dynamic_library_load"),
            (_ctypes, ("dlopen",), "dynamic_library_load"),
            (_imp, ("create_dynamic", "exec_dynamic"), "extension_import"),
            (importlib.machinery.ExtensionFileLoader, ("create_module", "exec_module"), "extension_import"),
            (zipfile.ZipFile, ("extract", "extractall", "_extract_member"), "archive_extraction"),
            (tarfile.TarFile, ("extract", "extractall", "_extract_member", "makefile", "makelink"), "archive_extraction"),
            (shutil, ("unpack_archive",), "archive_extraction"),
        ):
            for name in names:
                self.patch(owner, name, self.blocker(category, owner.__name__ + "." + name))

    def restore(self):
        self.active = False
        for owner, name, original in reversed(self.patches):
            setattr(owner, name, original)
        self.patches.clear()

    def profile(self, frame, event, arg):
        if not self.active or self.phase != "replay":
            return
        filename = frame.f_code.co_filename
        if filename not in self.local_python:
            return
        name = frame.f_code.co_qualname
        if event == "call":
            self.functions[(filename[len(self.repo) + 1:], name)] += 1
        elif event == "return" and filename == self.reader_path:
            if name == "ArchiveReader._verify_original":
                owner = frame.f_locals["self"]
                digest = frame.f_locals.get("digest")
                count = frame.f_locals.get("count")
                self.hash_checks.append({"caller": frame.f_back.f_code.co_name,
                    "bytes": count, "sha256": digest.hexdigest() if digest else None,
                    "matches_external": digest is not None and digest.hexdigest() == owner._expected_sha256
                                        and count == owner._size})
            elif name == "ArchiveReader.close":
                owner = frame.f_locals["self"]
                self.closes.append({"closed": owner._closed, "stream_closed": owner._stream.closed,
                                    "archive": str(owner.path)})

    def export(self):
        return [{"phase": phase, "decision": decision, "operation": category, "target": target, "count": count}
                for (phase, decision, category, target), count in sorted(self.events.items())]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    base = Path(__file__).resolve().parents[1]
    parser.add_argument("--repo", type=Path, default=base / "AI-GPU")
    parser.add_argument("--archive", type=Path, default=base / "originals/p05-torch-fp16-c0b44ce6-original.zip")
    parser.add_argument("--sha256", default=DEFAULT_SHA)
    parser.add_argument("--expected-revision", default=DEFAULT_REV)
    parser.add_argument("--format", choices=("fp16", "bf16"), default="fp16")
    parser.add_argument("--output", type=Path, default=base / "validation/a30-result.json")
    args = parser.parse_args()
    repo, archive = args.repo.resolve(strict=True), args.archive.resolve(strict=True)
    sys.path.insert(0, str(repo / "ci/project"))
    import p05_torch_replay as replay
    sources = replay.READER_SOURCES
    allowed_paths = {repo / row["path"] for row in sources}
    reader_path = repo / replay.p06_replay.ARCHIVE_READER_PATH
    reader_raw = reader_path.read_bytes()
    assert hashlib.sha256(reader_raw).hexdigest() == replay.p06_replay.ARCHIVE_READER_SHA256
    reader_code = compile(reader_raw, str(reader_path), "exec", dont_inherit=True)
    synthetic_code = compile("pass", "<a30-retained-execution-control>", "exec", dont_inherit=True)
    archive_before = digest_file(archive)
    assert archive_before == args.sha256
    diff = git(repo, "diff", BASE, "--")
    changed = git(repo, "diff", "--name-only", BASE, "--").decode().splitlines()
    untracked = git(repo, "ls-files", "--others", "--exclude-standard").decode().splitlines()
    review_paths = {repo / name for name in changed + untracked if (repo / name).is_file()}
    source_before = {str(path.relative_to(repo)): digest_file(path) for path in sorted(allowed_paths | review_paths)}
    static_calls = static_inventory(repo, allowed_paths | review_paths)
    recorded_roots = set()
    # Reading these three reports as data identifies actual producer paths for negative controls.
    with zipfile.ZipFile(archive) as opened:
        for name in ("native-model/report.json", "python/report.json", "torch/report.json"):
            report = json.loads(opened.read(name))
            recorded_roots.update(value for value in report["paths"].values() if isinstance(value, str))
    assert not any(str(archive) == root or str(archive).startswith(root + "/") for root in recorded_roots)
    assert not any(str(path) == root or str(path).startswith(root + "/")
                   for root in recorded_roots for path in allowed_paths)
    producer = sorted(root for root in recorded_roots if root.startswith("/"))[0]
    guard = Guard(repo, archive, sources, reader_path, reader_raw, reader_code)
    controls = [
        ("producer_builtin_open", lambda: builtins.open(producer + "/a30-control", "rb")),
        ("producer_io_open", lambda: io.open(producer + "/a30-control", "rb")),
        ("producer_os_open", lambda: os.open(producer + "/a30-control", os.O_RDONLY)),
        ("producer_resolve", lambda: Path(producer).resolve()),
        ("producer_stat", lambda: os.stat(producer)),
        ("producer_lstat", lambda: os.lstat(producer)),
        ("producer_readlink", lambda: os.readlink(producer)),
        ("archive_write", lambda: os.open(str(archive), os.O_WRONLY)),
        ("unlisted_open", lambda: builtins.open("/a30-not-allowed", "rb")),
        ("enumerate", lambda: os.listdir(repo)),
        ("subprocess", lambda: subprocess.run(["false"])),
        ("system", lambda: os.system(":")),
        ("fork", lambda: os.fork()),
        ("socket", lambda: socket.socket()),
        ("dns", lambda: socket.getaddrinfo("localhost", 0)),
        ("dynamic_library", lambda: ctypes.CDLL("/a30-not-allowed.so")),
        ("extension_import", lambda: _imp.create_dynamic(None)),
        ("zip_extract", lambda: zipfile.ZipFile.extract(None, "a30-control")),
        ("tar_extract", lambda: tarfile.TarFile.extract(None, "a30-control")),
        ("retained_exec", lambda: exec(synthetic_code)),
        ("retained_eval", lambda: eval("1 + 1")),
        ("executable_compile", lambda: compile("pass", "<a30-control>", "exec")),
        ("new_import", lambda: __import__("a30_retained_control_module")),
    ]
    guard.install()
    control_results, error, outcome = [], None, None
    start = time.monotonic()
    try:
        guard.active = True
        guard.phase = "controls"
        for name, action in controls:
            try:
                action()
            except BoundaryDenied as failure:
                control_results.append({"name": name, "blocked": True, "reason": str(failure)})
            else:
                raise AssertionError("guard control unexpectedly permitted: " + name)
        guard.phase = "replay"
        sys.setprofile(guard.profile)
        outcome = replay.replay_archive(archive, args.sha256,
            expected_revision=args.expected_revision, expected_format=args.format)
    except BaseException:
        error = sys.exc_info()
    finally:
        sys.setprofile(None)
        guard.restore()
    elapsed = time.monotonic() - start
    source_after = {name: digest_file(repo / name) for name in source_before}
    source_changes = [name for name in source_before if source_before[name] != source_after[name]]
    archive_after = digest_file(archive)
    events = guard.export()
    unexpected = [row for row in events if row["phase"] == "replay" and row["decision"] == "deny"
                  and row["operation"] != "trusted_reader_cache_fallback"]
    live_names = {
        ("ci/project/p05_execution_records.py", "verify_observations"),
        ("ci/project/p05_execution_records.py", "_installation"),
        ("ci/project/p05_torch_records.py", "verify_observations"),
        ("ci/project/p05_torch_records.py", "_framework"),
        ("ci/project/p05_installed_check.py", "validate_request"),
    }
    live_calls = [{"path": path, "function": name, "count": guard.functions[(path, name)]}
                  for path, name in sorted(live_names) if guard.functions[(path, name)]]
    success = (error is None and outcome is not None and outcome["outcome"] == "pass"
               and not source_changes and archive_before == archive_after == args.sha256
               and not unexpected and not live_calls and len(control_results) == len(controls)
               and len(guard.hash_checks) == 2 and all(row["matches_external"] for row in guard.hash_checks)
               and guard.hash_checks[-1]["caller"] == "close"
               and guard.closes == [{"closed": True, "stream_closed": True, "archive": str(archive)}])
    result = {
        "schema_version": 1, "agent": "a30", "success": success,
        "scope": "one-complete-public-c0-fp16-original-replay-under-denial-guards",
        "command": "PYTHONDONTWRITEBYTECODE=1 python3 ../validation/a30_probe.py",
        "reader_head": git(repo, "rev-parse", "HEAD").decode().strip(),
        "base": BASE, "task_diff_sha256": hashlib.sha256(diff).hexdigest(),
        "reviewed_changed_paths": changed, "reviewed_untracked_paths": untracked,
        "python": sys.version, "elapsed_seconds": round(elapsed, 6),
        "archive": {"path": str(archive), "expected_sha256": args.sha256,
                    "external_before_sha256": archive_before, "external_after_sha256": archive_after,
                    "execution_revision": args.expected_revision, "format": args.format},
        "source_sha256": source_before, "source_changes": source_changes,
        "reader_input_manifest": sources,
        "allowed_read_files": sorted(guard.allowed),
        "allowed_metadata_only_ancestors": sorted(guard.metadata - guard.allowed),
        "recorded_producer_roots_denied": sorted(recorded_roots),
        "trusted_local_reader_code_sha256": guard.reader_code_sha,
        "guards": {
            "semantic_replay_functions_patched": False,
            "open": "CPython audit open event: exact files, read only, verified descriptor identities",
            "resolution": "Path.resolve/os.path.realpath/os.stat/os.lstat/os.readlink/os.access wrappers",
            "process": "subprocess, os.system/popen/exec/spawn/fork and audit events denied",
            "network": "socket construction/name resolution and socket audit events denied",
            "loading": "new imports, extension loading and ctypes shared library loading denied",
            "execution": "all exec/eval denied except byte-identical compiled hash-pinned local archive_reader.py",
            "compilation": "AST-only compile allowed; executable compile only exact local archive reader bytes",
            "extraction": "ZIP/TAR filesystem extraction and shutil.unpack_archive denied",
            "writes": "write-mode opens, mutation, enumeration, mmap and process audit events denied",
        },
        "guard_controls": control_results, "events": events,
        "unexpected_replay_denials": unexpected, "live_validation_calls": live_calls,
        "archive_internal_hash_checks": guard.hash_checks, "archive_closes": guard.closes,
        "static_call_inventory": static_calls,
        "local_functions_called": [{"path": path, "function": name, "count": count}
                                   for (path, name), count in sorted(guard.functions.items())],
        "replay": None if outcome is None else {
            key: outcome[key] for key in ("outcome", "scope", "counts", "native_execution", "retained_code_executed",
                "acceptance_claimed", "phase_acceptance", "host_fault_semantics_revalidated", "limitations")
        },
        "archive_receipt": None if outcome is None else {key: value for key, value in outcome["archive_read"].items()
                                                       if key != "read_files"},
        "error": None if error is None else "".join(traceback.format_exception(*error)),
        "limits": [
            "One pinned FP16 original only; no BF16 or fresh c6 guarded run is claimed.",
            "Python runtime audit/hooks plus static source inventory are not an OS sandbox or proof against a hostile interpreter.",
            "Trusted standard-library and local reader modules are imported before guards; their startup imports are outside this dynamic boundary.",
            "The public loader's exact trusted local archive_reader.py is repeatedly source-verified and allowed to execute; this is not retained payload execution.",
            "Denied local bytecode-cache reads force the unmodified loader to fall back to pinned source; those denials are separately classified.",
            "Native execution, acceptance, arbitrary-origin authentication, missing third-party bytes and full supplementary host-fault semantics remain unclaimed.",
        ],
    }
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"success": success, "output": str(args.output), "elapsed_seconds": result["elapsed_seconds"],
        "guard_controls_blocked": len(control_results), "source_changes": source_changes,
        "unexpected_replay_denials": unexpected, "archive_internal_hash_checks": guard.hash_checks,
        "replay": result["replay"], "error": result["error"]}, indent=2, sort_keys=True))
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
