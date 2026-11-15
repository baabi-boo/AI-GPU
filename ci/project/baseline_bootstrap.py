#!/usr/bin/env python3
# Licensed under the Apache License, Version 2.0.
"""Install or verify the pinned native tool subset; never qualify GPU behavior."""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import shutil
import stat
import sys
import tarfile
import tempfile
import time
import urllib.request

import baseline_inventory as inventory


GIB = 1024 ** 3
CHUNK = 1024 ** 2
MAX_EXPANDED_BYTES = 10 * GIB
MAX_MEMBERS = 100000
DEFAULT_MANIFEST = Path(__file__).with_name("p01_toolchain.lock.json")
RECEIPT = "baseline-toolchain-receipt.json"
CACHE_MARKER = "baseline-download-cache.json"
COMPONENTS = ("riscv64-gnu-toolchain", "llvm-vortex", "verilator", "libc64", "libcrt64")
PART_FIELDS = {"path", "size_bytes", "git_blob_sha", "sha256"}
LIMITATIONS = [
    "Installation and receipt verification are not GPU execution or phase acceptance.",
    "Disk reserves are checked during streaming; they are not filesystem quotas.",
    "Receipt verification checks the recorded executable/library identities, not every installed file.",
]


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _read_json(path, maximum=1024 * 1024):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
        raise ValueError("JSON input must be a bounded regular file without a symlink")
    with path.open("rb") as source:
        data = source.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError("JSON input exceeds its size limit")
    def reject(value):
        raise ValueError("nonfinite JSON constant")
    return json.loads(data.decode("utf-8"), object_pairs_hook=_unique, parse_constant=reject)


def load_manifest(path=DEFAULT_MANIFEST):
    manifest = _read_json(path)
    fields = {"repository", "tag", "revision", "os_bundle", "parts"}
    if type(manifest) is not dict or set(manifest) != fields:
        raise ValueError("unexpected toolchain manifest fields")
    expected = (inventory.TOOLCHAIN_REPOSITORY, inventory.TOOLCHAIN_TAG,
                inventory.TOOLCHAIN_COMMIT, inventory.OS_BUNDLE)
    if tuple(manifest[key] for key in ("repository", "tag", "revision", "os_bundle")) != expected:
        raise ValueError("toolchain manifest does not name the immutable baseline pin")
    if type(manifest["parts"]) is not list or len(manifest["parts"]) != 18:
        raise ValueError("toolchain manifest must contain all eighteen archive parts")
    paths = set()
    for part in manifest["parts"]:
        if (type(part) is not dict or set(part) != PART_FIELDS
                or type(part["path"]) is not str
                or part["path"] not in inventory._expected_bundle_paths()
                or part["path"] in paths
                or type(part["size_bytes"]) is not int
                or not 0 < part["size_bytes"] <= 64 * CHUNK
                or type(part["git_blob_sha"]) is not str
                or not re.fullmatch(r"[0-9a-f]{40}", part["git_blob_sha"])
                or type(part["sha256"]) is not str
                or not re.fullmatch(r"[0-9a-f]{64}", part["sha256"])):
            raise ValueError("invalid, duplicate or unexpected tool archive part")
        paths.add(part["path"])
    if paths != inventory._expected_bundle_paths() or sum(p["size_bytes"] for p in manifest["parts"]) > GIB:
        raise ValueError("incomplete toolchain or compressed-size budget exceeded")
    if manifest_digest(manifest) != inventory.TOOLCHAIN_MANIFEST_SHA256:
        raise ValueError("toolchain manifest differs from the reviewed immutable lock")
    return manifest


def manifest_digest(manifest):
    return inventory.manifest_digest(manifest)


def _safe_path(path):
    path = Path(path)
    if (not path.is_absolute() or ".." in path.parts
            or not re.fullmatch(r"/[A-Za-z0-9_./+-]+", str(path))
            or path != path.resolve(strict=False)):
        raise ValueError("use an absolute directory without symlinks or unsafe path characters")
    return path


def _directory(path, create=False):
    path = _safe_path(path)
    if create:
        path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir():
        raise ValueError("required directory does not exist")
    return path


def _reserve(path, minimum, additional=0):
    if type(minimum) is not int or minimum <= 0:
        raise ValueError("free-space reserve must be a positive integer")
    if shutil.disk_usage(path).free < minimum + additional:
        raise ValueError("free-space reserve would be exceeded")


def _write_new_json(path, value):
    with path.open("x", encoding="utf-8") as output:
        json.dump(value, output, indent=2, sort_keys=True, allow_nan=False)
        output.write("\n")


def verify_part(path, part):
    if path.is_symlink() or not path.is_file() or path.stat().st_size != part["size_bytes"]:
        raise ValueError("cached archive part is not a regular file of the pinned size")
    git_hash = hashlib.sha1(f'blob {part["size_bytes"]}\0'.encode())
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as source:
        while chunk := source.read(CHUNK):
            total += len(chunk)
            if total > part["size_bytes"]:
                raise ValueError("archive part changed during verification")
            git_hash.update(chunk)
            digest.update(chunk)
    if total != part["size_bytes"] or git_hash.hexdigest() != part["git_blob_sha"] or digest.hexdigest() != part["sha256"]:
        raise ValueError("archive part does not match its Git blob and SHA-256 identities")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        raise ValueError("tool archive redirects are not permitted")


def _open_url(url, timeout):
    return urllib.request.build_opener(_NoRedirect()).open(url, timeout=timeout)


def download_part(part, cache, minimum):
    destination = cache / PurePosixPath(part["path"]).name
    if os.path.lexists(destination):
        verify_part(destination, part)
        return destination
    _reserve(cache, minimum, part["size_bytes"])
    url = ("https://raw.githubusercontent.com/" + inventory.TOOLCHAIN_REPOSITORY
           + "/" + inventory.TOOLCHAIN_COMMIT + "/" + part["path"])
    temporary = None
    with tempfile.NamedTemporaryFile(prefix=destination.name + ".partial.", dir=cache, delete=False) as output:
        temporary = Path(output.name)
        deadline, total = time.monotonic() + 300, 0
        with _open_url(url, timeout=30) as response:
            if response.geturl() != url:
                raise ValueError("tool archive response changed its pinned URL")
            while chunk := response.read(CHUNK):
                total += len(chunk)
                if total > part["size_bytes"] or time.monotonic() > deadline:
                    raise ValueError("tool download exceeded its size or time limit")
                _reserve(cache, minimum, len(chunk))
                output.write(chunk)
    verify_part(temporary, part)
    os.link(temporary, destination)
    temporary.unlink()
    return destination


def _member_path(member, component):
    name = member.name.rstrip("/")
    path = PurePosixPath(name)
    if (not name or path.is_absolute() or ".." in path.parts or "\\" in name
            or any(ord(character) < 32 for character in name)
            or not path.parts or path.parts[0] != component
            or not (member.isdir() or member.isfile() or member.issym() or member.islnk())):
        raise ValueError("archive contains an unsafe path, special file or unexpected root")
    if str(path) == component and not member.isdir():
        raise ValueError("archive component root must be a directory")
    if member.issym() or member.islnk():
        link = member.linkname
        if not link or link.startswith("/") or "\\" in link or any(ord(c) < 32 for c in link):
            raise ValueError("archive contains an unsafe link")
        target = posixpath.normpath(posixpath.join(str(path.parent), link) if member.issym() else link)
        if not PurePosixPath(target).parts or PurePosixPath(target).parts[0] != component:
            raise ValueError("archive link escapes its component")
    return path


def extract_component(archive, root, component, minimum):
    if os.path.lexists(root / component):
        raise ValueError("installed component already exists; refusing to overwrite it")
    with tarfile.open(archive, "r:bz2") as bundle:
        members, seen, total = [], set(), 0
        for member in bundle:
            path = _member_path(member, component)
            if str(path) in seen or len(members) >= MAX_MEMBERS or member.size < 0:
                raise ValueError("duplicate archive path or member-count limit exceeded")
            seen.add(str(path))
            total += member.size
            if total > MAX_EXPANDED_BYTES:
                raise ValueError("component expansion exceeds its size limit")
            members.append((member, path))
        if not members:
            raise ValueError("component archive is empty")
        _reserve(root, minimum, total)
        for member, relative in members:
            _reserve(root, minimum, member.size)
            destination = root / str(relative)
            for parent in destination.parents:
                if parent == root:
                    break
                if parent.is_symlink():
                    raise ValueError("archive member traverses an installed symlink")
            destination.parent.mkdir(parents=True, exist_ok=True)
            safe = tarfile.data_filter(member, str(root))
            if member.isdir():
                if os.path.lexists(destination) and (destination.is_symlink() or not destination.is_dir()):
                    raise ValueError("archive directory would replace another file")
                destination.mkdir(exist_ok=True)
            elif os.path.lexists(destination):
                raise ValueError("archive member would overwrite an existing file")
            elif member.isfile():
                remaining = member.size
                with bundle.extractfile(member) as source, destination.open("xb") as output:
                    while remaining:
                        chunk = source.read(min(CHUNK, remaining))
                        if not chunk:
                            raise ValueError("truncated archive member")
                        _reserve(root, minimum, len(chunk))
                        output.write(chunk)
                        remaining -= len(chunk)
                os.chmod(destination, (safe.mode if safe.mode is not None else 0o600) & 0o777)
            elif member.issym():
                os.symlink(member.linkname, destination)
            else:
                target = root / member.linkname
                if target.is_symlink() or not target.is_file() or not target.resolve().is_relative_to(root / component):
                    raise ValueError("archive hardlink does not name an extracted component file")
                os.link(target, destination)


def _receipt_files(tool_dir, manifest_path):
    observed = inventory.collect_tools(tool_dir, manifest_path)
    if observed["outcome"] != "pass":
        raise ValueError("installed tools failed their version or library identity probes")
    files = [{key: entry[key] for key in ("path", "sha256", "size_bytes")}
             for entry in list(observed["tools"].values()) + observed["libraries"]]
    return files, {name: entry["version"] for name, entry in observed["tools"].items()}


def verify(tool_dir, manifest_path=DEFAULT_MANIFEST):
    manifest = load_manifest(manifest_path)
    root = _directory(tool_dir)
    receipt = _read_json(root / RECEIPT, 65536)
    if (type(receipt) is not dict
            or set(receipt) != {"schema_version", "manifest_sha256", "toolchain_commit", "files", "tool_versions"}
            or type(receipt["schema_version"]) is not int or receipt["schema_version"] != 1
            or receipt["manifest_sha256"] != manifest_digest(manifest)
            or receipt["toolchain_commit"] != inventory.TOOLCHAIN_COMMIT
            or type(receipt["files"]) is not list):
        raise ValueError("installation receipt does not match the pinned manifest")
    expected = set(inventory.TOOL_BINARIES.values()) | set(inventory.LIBRARIES)
    entries = receipt["files"]
    if (any(type(item) is not dict or set(item) != {"path", "sha256", "size_bytes"}
            or type(item["path"]) is not str or type(item["size_bytes"]) is not int
            or item["size_bytes"] < 0 or type(item["sha256"]) is not str
            or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) for item in entries)
            or len(entries) != len(expected) or {item["path"] for item in entries} != expected):
        raise ValueError("installation receipt omits or changes required file identities")
    if (type(receipt["tool_versions"]) is not dict
            or set(receipt["tool_versions"]) != set(inventory.TOOL_BINARIES)
            or any(type(value) is not str or not value or len(value) > 512
                   for value in receipt["tool_versions"].values())):
        raise ValueError("installation receipt has malformed tool versions")
    if any((root / component).is_symlink() or not (root / component).is_dir() for component in COMPONENTS):
        raise ValueError("installed components are missing or symlinked")
    if inventory.hash_artifacts(root, [item["path"] for item in entries]) != entries:
        raise ValueError("installed files differ from the recorded receipt")
    if any(not os.access(root / path, os.X_OK) for path in inventory.TOOL_BINARIES.values()):
        raise ValueError("recorded tool is no longer executable")
    return {"outcome": "pass", "operation": "verify", "manifest_sha256": receipt["manifest_sha256"],
            "receipt": receipt, "limitations": LIMITATIONS}


def install(tool_dir, cache_dir, manifest_path=DEFAULT_MANIFEST, min_free_bytes=15 * GIB):
    manifest = load_manifest(manifest_path)
    if type(min_free_bytes) is not int or min_free_bytes <= 0:
        raise ValueError("free-space reserve must be a positive integer")
    root, cache = _safe_path(tool_dir), _safe_path(cache_dir)
    if root == cache or root.is_relative_to(cache) or cache.is_relative_to(root):
        raise ValueError("tool and cache directories must be separate and disjoint")
    root, cache = _directory(root, True), _directory(cache, True)
    _reserve(root, min_free_bytes)
    _reserve(cache, min_free_bytes)
    if any(root.iterdir()):
        result = verify(root, manifest_path)
        result.update(operation="install", action="verified_existing_installation")
        return result
    marker = {"manifest_sha256": manifest_digest(manifest)}
    if os.path.lexists(cache / CACHE_MARKER):
        if _read_json(cache / CACHE_MARKER) != marker:
            raise ValueError("download cache belongs to another manifest")
    elif any(cache.iterdir()):
        raise ValueError("use an empty cache or its existing baseline cache marker")
    else:
        _write_new_json(cache / CACHE_MARKER, marker)
    for component in COMPONENTS:
        parts = sorted((part for part in manifest["parts"] if part["path"].startswith(component + "/")), key=lambda part: part["path"])
        paths = [download_part(part, cache, min_free_bytes) for part in parts]
        _reserve(cache, min_free_bytes, sum(part["size_bytes"] for part in parts))
        with tempfile.NamedTemporaryFile(prefix=component + ".assembled.", suffix=".tar.bz2", dir=cache, delete=False) as output:
            archive = Path(output.name)
            for path in paths:
                with path.open("rb") as source:
                    while chunk := source.read(CHUNK):
                        _reserve(cache, min_free_bytes, len(chunk))
                        output.write(chunk)
        extract_component(archive, root, component, min_free_bytes)
        archive.unlink()
    files, versions = _receipt_files(root, manifest_path)
    receipt = {"schema_version": 1, "manifest_sha256": manifest_digest(manifest),
               "toolchain_commit": inventory.TOOLCHAIN_COMMIT, "files": files, "tool_versions": versions}
    _write_new_json(root / RECEIPT, receipt)
    result = verify(root, manifest_path)
    result.update(operation="install", action="installed_pinned_components")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("install", "verify"))
    parser.add_argument("--tool-dir", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--min-free-gib", type=float, default=15)
    args = parser.parse_args(argv)
    try:
        if not math.isfinite(args.min_free_gib * GIB) or args.min_free_gib <= 0:
            raise ValueError("minimum free GiB must be finite and positive")
        if args.operation == "install":
            if args.cache_dir is None:
                raise ValueError("install requires an explicit dedicated cache directory")
            report = install(args.tool_dir, args.cache_dir, args.manifest, int(args.min_free_gib * GIB))
        else:
            report = verify(args.tool_dir, args.manifest)
    except (OSError, ValueError, RuntimeError, UnicodeError, tarfile.TarError) as error:
        reason = str(error) if isinstance(error, ValueError) else "filesystem, network or archive operation failed"
        report = {"outcome": "fail", "operation": args.operation, "reason": reason,
                  "limitations": LIMITATIONS + ["Partial outputs are preserved; no existing installation is replaced."]}
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["outcome"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
