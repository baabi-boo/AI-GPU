# SPDX-License-Identifier: Apache-2.0
"""Provision the locked SimX prebuilt archives with an explicitly local origin."""

from __future__ import annotations

from collections import deque
import hashlib
import io
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import shutil
import stat
import tarfile
import time

import baseline_inventory as inventory
import p06_dependency_contract as dependency
from preflight import available_memory_bytes


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_ID = "p06-local-toolchain-provision-v1"
COMPONENTS = ("riscv64-gnu-toolchain", "llvm-vortex", "libc64", "libcrt64")
NATIVE_TOOLS = {
    **{name: "llvm-vortex/bin/" + name for name in (
        "clang", "clang++", "llvm-objcopy", "llvm-objdump")},
    **{"riscv-" + name: "riscv64-gnu-toolchain/bin/riscv64-unknown-elf-" + name
       for name in ("gcc", "gcc-ar", "objdump", "objcopy")},
    **{name: name for name in ("libc64/lib/libc.a", "libc64/lib/libm.a",
                              "libcrt64/lib/baremetal/libclang_rt.builtins-riscv64.a")},
}
BUDGET = {"min_free_bytes": dependency.BUDGET["min_free_bytes"],
          "min_available_memory_bytes": dependency.BUDGET["max_rss_bytes"],
          "max_extracted_bytes": 4 * 1024**3, "max_member_bytes": 1024**3,
          "max_members": 50000, "timeout_seconds": 1800}
CHUNK = 1024**2
LIMITATIONS = [
    "This is local provisioning from an immutable historical archive lock, not a GitHub cache restoration or a current-tag resolution.",
    "Metadata replay checks retained consistency; it does not read the producer's paths, rehash archives, re-extract tools or authenticate the producer.",
    "The original provisioning operation hashes every selected archive and joins the selected installed tools to archive members; system libraries and host compiler inputs are outside this receipt.",
    "Before/after observations do not protect against malicious concurrent filesystem writers.",
]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def _absolute(value):
    require(type(value) is str and re.fullmatch(r"/[A-Za-z0-9_./+()\-]+", value)
            and str(PurePosixPath(value)) == value
            and ".." not in PurePosixPath(value).parts, "toolchain root is not a canonical absolute literal")
    return value


def _root(value, *, existing):
    path = Path(os.path.abspath(value))
    _absolute(str(path))
    require(path.resolve(strict=existing) == path
            and all(not parent.is_symlink() for parent in (path, *path.parents)),
            "toolchain roots must not traverse symlinks")
    require((path.is_dir() if existing else path.parent.is_dir()),
            "toolchain root or its parent is not a directory")
    return path


def _relative(value):
    require(type(value) is str and 0 < len(value) <= 1024
            and re.fullmatch(r"[A-Za-z0-9_./+\-]+", value)
            and not value.startswith("/") and str(PurePosixPath(value)) == value
            and not any(part in (".", "..") for part in value.split("/")),
            "archive member path is not a safe relative literal")
    return value


def _locked_manifest():
    return inventory._bundle_identity(ROOT / "ci/project/p01_toolchain.lock.json")


def _selected_parts(manifest):
    return sorted((dict(row) for row in manifest["parts"]
                   if row["path"].split("/", 1)[0] in COMPONENTS),
                  key=lambda row: row["path"])


def _digest(path):
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while block := stream.read(CHUNK):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def _part(path, expected):
    require(path.resolve(strict=True) == path
            and all(not parent.is_symlink() for parent in (path, *path.parents)),
            "toolchain archive traverses a symlink")
    information = path.stat()
    require(stat.S_ISREG(information.st_mode) and information.st_nlink == 1
            and information.st_size == expected["size_bytes"], "toolchain archive size or type differs")
    sha256 = hashlib.sha256()
    git_blob = hashlib.sha1(("blob " + str(information.st_size) + "\0").encode())
    with path.open("rb") as stream:
        while block := stream.read(CHUNK):
            sha256.update(block)
            git_blob.update(block)
    require(sha256.hexdigest() == expected["sha256"]
            and git_blob.hexdigest() == expected["git_blob_sha"], "toolchain archive bytes differ from the immutable lock")


class _Parts(io.RawIOBase):
    def __init__(self, root, parts):
        self.root, self.parts = root, iter(parts)
        self.current = None
        self.expected = None
        self.size = 0

    def readable(self):
        return True

    def read(self, size=-1):
        require(type(size) is int and 0 <= size <= CHUNK, "archive reads must be bounded")
        if not size:
            return b""
        result = bytearray()
        while len(result) < size:
            if self.current is None:
                self.expected = next(self.parts, None)
                if self.expected is None:
                    break
                self.current = (self.root / self.expected["path"]).open("rb")
                self.sha256 = hashlib.sha256()
                self.git_blob = hashlib.sha1(("blob " + str(self.expected["size_bytes"]) + "\0").encode())
                self.size = 0
            block = self.current.read(size - len(result))
            if block:
                self.size += len(block)
                require(self.size <= self.expected["size_bytes"], "archive grew during extraction")
                self.sha256.update(block)
                self.git_blob.update(block)
                result.extend(block)
            else:
                self.current.close()
                self.current = None
                require(self.size == self.expected["size_bytes"]
                        and self.sha256.hexdigest() == self.expected["sha256"]
                        and self.git_blob.hexdigest() == self.expected["git_blob_sha"],
                        "archive changed during extraction")
        return bytes(result)

    def close(self):
        if self.current is not None:
            self.current.close()
            self.current = None
        super().close()


def _link_target(record):
    target = record["target"]
    require(type(target) is str and 0 < len(target) <= 1024
            and re.fullmatch(r"[A-Za-z0-9_./+\-]+", target)
            and not target.startswith("/"), "archive link has an unsafe target")
    combined = (posixpath.join(posixpath.dirname(record["path"]), target)
                if record["kind"] == "symlink" else target)
    result = posixpath.normpath(combined)
    _relative(result)
    require(result.split("/", 1)[0] == record["path"].split("/", 1)[0],
            "archive link escapes its component")
    return result


def _member_directories(members):
    directories = set()
    for name in members:
        parts = name.split("/")
        directories.update("/".join(parts[:index]) for index in range(1, len(parts)))
    return directories


def _resolved_member(name, members, *, follow_hardlinks=True, directories=None):
    if directories is None:
        directories = _member_directories(members)
    pending, resolved = deque(name.split("/")), []
    component, expansions = name.split("/", 1)[0], 0
    while pending:
        part = pending.popleft()
        if part in ("", "."):
            continue
        if part == "..":
            require(len(resolved) > 1, "archive link escapes its component")
            resolved.pop()
            continue
        resolved.append(part)
        require(resolved[0] == component, "archive link escapes its component")
        row = members.get("/".join(resolved))
        if row is not None and (row["kind"] == "symlink"
                                or follow_hardlinks and row["kind"] == "hardlink"):
            _link_target(row)
            expansions += 1
            require(expansions <= 100, "archive links contain a cycle or exceed their depth bound")
            if row["kind"] == "symlink":
                resolved.pop()
            else:
                resolved.clear()
            # Parent segments apply after each symbolic prefix is expanded.
            pending.extendleft(reversed(row["target"].split("/")))
        elif pending:
            require((row is not None and row["kind"] == "directory")
                    or row is None and "/".join(resolved) in directories,
                    "archive link traverses a non-directory member")
    target = "/".join(resolved)
    if target not in members and target in directories:
        return {"path": target, "kind": "directory"}
    require(target in members, "archive link or selected tool has no member")
    return members[target]


def _check_resources(root, started):
    require(time.monotonic() - started <= BUDGET["timeout_seconds"], "toolchain extraction exceeded its time bound")
    require(shutil.disk_usage(root).free >= BUDGET["min_free_bytes"], "toolchain extraction threatens the 15 GiB disk reserve")


def _parents(target, root):
    for parent in target.parents:
        if parent == root:
            break
        require(not parent.is_symlink(), "archive output traverses a symlink")
    target.parent.mkdir(parents=True, exist_ok=True)


def _extract(archive_root, tools_root, parts, component, members, totals, started):
    with _Parts(archive_root, parts) as stream:
        with tarfile.open(fileobj=stream, mode="r|bz2") as archive:
            for item in archive:
                _check_resources(tools_root, started)
                name = _relative(item.name.rstrip("/"))
                require(name.split("/", 1)[0] == component, "archive member belongs to a different component")
                require(name not in members and len(members) < BUDGET["max_members"],
                        "archive has duplicate members or exceeds its member bound")
                require(not item.sparse and item.type in (tarfile.REGTYPE, tarfile.AREGTYPE,
                    tarfile.DIRTYPE, tarfile.SYMTYPE, tarfile.LNKTYPE), "archive member type is unsupported")
                filtered = tarfile.data_filter(item, str(tools_root))
                require(filtered is not None, "archive filter omitted a selected member")
                target = tools_root / name
                row = {"path": name}
                if item.isfile():
                    require(type(item.size) is int and 0 <= item.size <= BUDGET["max_member_bytes"]
                            and totals["bytes"] + item.size <= BUDGET["max_extracted_bytes"],
                            "archive exceeds its extracted-byte bound")
                    _parents(target, tools_root)
                    require(not os.path.lexists(target), "archive would replace an existing output")
                    digest = hashlib.sha256()
                    copied = 0
                    with archive.extractfile(item) as source, target.open("xb") as destination:
                        while block := source.read(CHUNK):
                            copied += len(block)
                            require(copied <= item.size, "archive member grew during extraction")
                            destination.write(block)
                            digest.update(block)
                            _check_resources(tools_root, started)
                    require(copied == item.size, "archive member was truncated")
                    mode = filtered.mode & 0o777
                    target.chmod(mode)
                    row.update(kind="file", size_bytes=copied, sha256=digest.hexdigest(), mode=mode)
                    totals["bytes"] += copied
                elif item.isdir():
                    _parents(target, tools_root)
                    require(not target.is_symlink() and (not target.exists() or target.is_dir()),
                            "archive directory conflicts with an existing output")
                    target.mkdir(mode=0o755, exist_ok=True)
                    row.update(kind="directory")
                else:
                    row.update(kind="symlink" if item.issym() else "hardlink", target=item.linkname)
                    _link_target(row)
                members[name] = row
        while stream.read(CHUNK):
            _check_resources(tools_root, started)


def provision(archive_root, tools_root):
    archive_root, tools_root = _root(archive_root, existing=True), _root(tools_root, existing=False)
    require(not os.path.lexists(tools_root), "toolchain extraction requires a fresh output root")
    require(not (archive_root == tools_root or archive_root in tools_root.parents or tools_root in archive_root.parents),
            "toolchain archive and output roots overlap")
    started = time.monotonic()
    _check_resources(tools_root.parent, started)
    require((available_memory_bytes() or 0) >= BUDGET["min_available_memory_bytes"],
            "toolchain extraction requires 4 GiB available memory")
    manifest = _locked_manifest()
    parts = _selected_parts(manifest)
    for part in parts:
        _part(archive_root / part["path"], part)
        _check_resources(tools_root.parent, started)
    tools_root.mkdir(mode=0o700)
    members, totals = {}, {"bytes": 0}
    for component in COMPONENTS:
        _extract(archive_root, tools_root,
                 [row for row in parts if row["path"].split("/", 1)[0] == component],
                 component, members, totals, started)
    directories = _member_directories(members)
    for row in members.values():
        if row["kind"] in ("symlink", "hardlink"):
            resolved = _resolved_member(row["path"], members, directories=directories)
            require(row["kind"] == "symlink" or resolved["kind"] == "file",
                    "archive hardlink target is not a regular file")
            target = tools_root / row["path"]
            _parents(target, tools_root)
            require(not os.path.lexists(target), "archive link would replace an existing output")
            if row["kind"] == "symlink":
                target.symlink_to(row["target"])
            else:
                os.link(tools_root / resolved["path"], target)
    for row in members.values():
        if row["kind"] in ("symlink", "hardlink"):
            path = tools_root / row["path"]
            resolved = path.resolve(strict=True)
            require(resolved.is_relative_to(tools_root / row["path"].split("/", 1)[0]),
                    "installed archive link escapes its component")
            expected = tools_root / _resolved_member(row["path"], members,
                follow_hardlinks=False, directories=directories)["path"]
            require(resolved == expected, "installed archive link differs from its retained resolution")
    tools = {}
    for name, relative in NATIVE_TOOLS.items():
        path = tools_root / relative
        resolved = path.resolve(strict=True)
        require(resolved.is_relative_to(tools_root) and resolved.is_file(), "installed tool escapes its root or is absent")
        member = _resolved_member(relative, members, directories=directories)
        digest, size = _digest(resolved)
        require(member["kind"] == "file" and (digest, size) == (member["sha256"], member["size_bytes"]),
                "installed tool bytes differ from their archive member")
        require(name.startswith(("libc64/", "libcrt64/")) or os.access(path, os.X_OK),
                "selected compiler tool is not executable")
        tools[name] = {"path": str(path), "resolved_path": str(resolved), "sha256": digest, "size_bytes": size}
    _check_resources(tools_root, started)
    receipt = {"schema_version": 1, "contract_id": CONTRACT_ID, "origin": "local-pinned-archives",
        "outcome": "pass", "native_execution": "not_run", "archive_root": str(archive_root),
        "tools_root": str(tools_root), "repository": manifest["repository"], "tag": manifest["tag"],
        "revision": manifest["revision"], "os_bundle": manifest["os_bundle"],
        "manifest_sha256": manifest["sha256"], "manifest_size_bytes": manifest["size_bytes"],
        "manifest_semantic_sha256": inventory.TOOLCHAIN_MANIFEST_SHA256,
        "selected_components": list(COMPONENTS), "parts": parts,
        "members": sorted(members.values(), key=lambda row: row["path"]), "tools": tools,
        "compressed_bytes": sum(row["size_bytes"] for row in parts),
        "extracted_regular_bytes": totals["bytes"], "member_count": len(members),
        "budget": dict(BUDGET), "limitations": list(LIMITATIONS),
        **dict.fromkeys(dependency.FALSE_CLAIMS, False)}
    validate_receipt(receipt)
    return receipt


def validate_receipt(document):
    manifest = _locked_manifest()
    fields = {"schema_version", "contract_id", "origin", "outcome", "native_execution", "archive_root",
              "tools_root", "repository", "tag", "revision", "os_bundle", "manifest_sha256",
              "manifest_size_bytes", "manifest_semantic_sha256", "selected_components", "parts",
              "members", "tools", "compressed_bytes", "extracted_regular_bytes", "member_count",
              "budget", "limitations", *dependency.FALSE_CLAIMS}
    require(type(document) is dict and set(document) == fields, "local toolchain receipt schema differs")
    require(type(document["schema_version"]) is int and document["schema_version"] == 1
            and document["contract_id"] == CONTRACT_ID and document["origin"] == "local-pinned-archives"
            and document["outcome"] == "pass" and document["native_execution"] == "not_run",
            "local toolchain receipt origin or state differs")
    require(all(document[name] is False for name in dependency.FALSE_CLAIMS), "toolchain receipt advances an unsupported claim")
    for name in ("repository", "tag", "revision", "os_bundle"):
        require(document[name] == manifest[name], "toolchain receipt changes an immutable source identity")
    require(document["manifest_sha256"] == manifest["sha256"]
            and type(document["manifest_size_bytes"]) is int
            and document["manifest_size_bytes"] == manifest["size_bytes"]
            and document["manifest_semantic_sha256"] == inventory.TOOLCHAIN_MANIFEST_SHA256,
            "toolchain receipt changes its reviewed manifest")
    parts = _selected_parts(manifest)
    require(document["parts"] == parts and document["selected_components"] == list(COMPONENTS),
            "toolchain receipt changes the selected archive inventory")
    require(type(document["compressed_bytes"]) is int
            and document["compressed_bytes"] == sum(row["size_bytes"] for row in parts),
            "toolchain compressed-byte count differs")
    require(document["budget"] == BUDGET and document["limitations"] == LIMITATIONS,
            "toolchain receipt changes its bounds or limitations")
    root, archive = _absolute(document["tools_root"]), _absolute(document["archive_root"])
    require(not (PurePosixPath(root).is_relative_to(archive) or PurePosixPath(archive).is_relative_to(root)),
            "toolchain archive and output roots overlap")
    rows = document["members"]
    require(type(rows) is list and 0 < len(rows) <= BUDGET["max_members"], "toolchain member inventory is absent or oversized")
    members, total = {}, 0
    for row in rows:
        require(type(row) is dict and row.get("kind") in ("file", "directory", "symlink", "hardlink"),
                "toolchain member kind differs")
        expected = {"path", "kind"}
        expected |= ({"size_bytes", "sha256", "mode"} if row["kind"] == "file"
                     else {"target"} if row["kind"] in ("symlink", "hardlink") else set())
        require(set(row) == expected, "toolchain member schema differs")
        name = _relative(row["path"])
        require(name.split("/", 1)[0] in COMPONENTS and name not in members, "toolchain member is duplicated or outside selection")
        if row["kind"] == "file":
            require(type(row["size_bytes"]) is int and 0 <= row["size_bytes"] <= BUDGET["max_member_bytes"]
                    and type(row["sha256"]) is str and re.fullmatch(r"[0-9a-f]{64}", row["sha256"])
                    and type(row["mode"]) is int and 0 <= row["mode"] <= 0o777
                    and row["mode"] & 0o022 == 0, "toolchain member file metadata differs")
            total += row["size_bytes"]
        elif row["kind"] in ("symlink", "hardlink"):
            _link_target(row)
        members[name] = row
    require(list(members) == sorted(members), "toolchain member inventory is unordered")
    require(type(document["member_count"]) is int and document["member_count"] == len(members)
            and type(document["extracted_regular_bytes"]) is int
            and document["extracted_regular_bytes"] == total <= BUDGET["max_extracted_bytes"],
            "toolchain extracted inventory totals differ")
    directories = _member_directories(members)
    for row in rows:
        for parent in PurePosixPath(row["path"]).parents:
            if str(parent) in members:
                require(members[str(parent)]["kind"] == "directory",
                        "toolchain member traverses a non-directory archive member")
        if row["kind"] in ("symlink", "hardlink"):
            target = _resolved_member(row["path"], members, directories=directories)
            require(row["kind"] == "symlink" or target["kind"] == "file", "hardlink target is not a file")
    require(type(document["tools"]) is dict and set(document["tools"]) == set(NATIVE_TOOLS),
            "selected native tool inventory differs")
    for name, relative in NATIVE_TOOLS.items():
        identity = document["tools"][name]
        require(type(identity) is dict and set(identity) == {"path", "resolved_path", "sha256", "size_bytes"},
                "native tool identity schema differs")
        require(identity["path"] == root + "/" + relative, "native tool invoked path differs")
        resolved = _absolute(identity["resolved_path"])
        require(PurePosixPath(resolved).is_relative_to(root), "native tool resolved path escapes its root")
        require(resolved == root + "/" + _resolved_member(relative, members,
                follow_hardlinks=False, directories=directories)["path"],
                "native tool resolved path differs from its symbolic archive resolution")
        actual = _resolved_member(str(PurePosixPath(resolved).relative_to(root)), members, directories=directories)
        expected = _resolved_member(relative, members, directories=directories)
        require(actual == expected and actual["kind"] == "file"
                and type(identity["size_bytes"]) is int
                and (identity["sha256"], identity["size_bytes"]) == (actual["sha256"], actual["size_bytes"]),
                "native tool identity differs from its archive member")
        require(name.startswith(("libc64/", "libcrt64/")) or actual["mode"] & 0o111,
                "native tool archive member is not executable")
    return {"contract_id": CONTRACT_ID, "origin": "local-pinned-archives", "outcome": "pass",
            "metadata_consistent": True, "archive_bytes_rehashed": False, "installed_bytes_rehashed": False,
            "native_execution": "not_run", "retained_code_executed": False,
            "tools_root": root, "tools": document["tools"],
            **dict.fromkeys(dependency.FALSE_CLAIMS, False)}
