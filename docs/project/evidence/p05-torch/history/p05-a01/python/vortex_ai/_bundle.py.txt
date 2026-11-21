# SPDX-License-Identifier: Apache-2.0
"""Integrity checks for a native bundle pinned into the installed extension."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat


CONTRACT_ID = "p05-python-bundle-v1"
PROFILE_SHA256 = "79a551bd7ba51b5aa4b221eeb9c8f68b0f3078e6282ce71a1f28e9bc4593a102"
FIXTURE_SHA256 = "d22a899827afb3e8c22a528fc6a27fd12ff114ef39caf9ffa0cccd77e849cd03"
SOURCE_PATHS = tuple(sorted((
    "pyproject.toml", "setup.py", "MANIFEST.in",
    "python/vortex_ai/__init__.py", "python/vortex_ai/_api.py",
    "python/vortex_ai/_bundle.py", "python/vortex_ai/launch.py", "python/native/module.cpp",
    "python/native/runtime_loader.cpp", "python/native/runtime_loader.h",
    "sw/runtime/ai/contract.cpp", "sw/runtime/ai/contract.h",
    "sw/runtime/ai/runtime.cpp", "sw/runtime/ai/runtime.h",
    "sw/runtime/ai/mlp_runtime.cpp", "sw/runtime/ai/mlp_runtime.h",
    "sw/runtime/ai/mlp_host.cpp", "sw/runtime/ai/mlp_host.h",
    "sw/runtime/include/vortex2.h", "sw/common/ai_matmul_args.h",
    "tests/regression/ai_mlp/p04_fixtures.h", "tests/regression/ai_mlp/records.h",
)))
MANIFEST_KEYS = {
    "schema_version", "contract_id", "backend", "format", "source_revision",
    "source_tree", "binding_sources", "binding_source_sha256", "profile_sha256",
    "fixture_sha256", "qualification_id", "native_binding", "artifacts",
}
ROLES = {
    "ramulator": "lib/libramulator.so",
    "ramulator_extension": "lib/libramulator-vortex.so",
    "runtime": "lib/libvortex.so",
    "simulator": "lib/libsimx.so",
    "backend": "lib/libvortex-simx.so",
    "module": "kernel.vxbin",
}
LIBRARY_ORDER = ("ramulator", "ramulator_extension", "runtime", "simulator", "backend")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_HEX40 = re.compile(r"[0-9a-f]{40}\Z")


class BundleError(ValueError):
    """The installed package and native artifacts do not form a matched bundle."""


def _require(condition, message):
    if not condition:
        raise BundleError(message)


def canonical_bytes(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       allow_nan=False) + "\n").encode("utf-8")


def _identity(value, pattern, label):
    _require(type(value) is str and pattern.fullmatch(value), "invalid " + label)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "duplicate manifest field: " + key)
        result[key] = value
    return result


def _nonfinite(value):
    raise BundleError("nonfinite manifest value: " + value)


def _path_parts(relative):
    _require(type(relative) is str and relative and "\\" not in relative
             and not any(ord(char) < 32 for char in relative), "unsafe bundle path")
    parts = PurePosixPath(relative)
    _require(parts.parts and not parts.is_absolute() and str(parts) == relative
             and all(part not in (".", "..") for part in parts.parts), "unsafe bundle path")
    return parts


def _relative(root, relative):
    parts = _path_parts(relative)
    path = root
    for part in parts.parts:
        path = path / part
        _require(not path.is_symlink(), "symlink is not allowed: " + relative)
    _require(path.resolve().is_relative_to(root), "bundle path escapes its root")
    return path


def _read_regular(root, relative, *, limit, retain):
    root = Path(root).resolve(strict=True)
    path = _relative(root, relative)
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            _require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= limit,
                     "invalid file type or size: " + relative)
            digest = hashlib.sha256()
            count = 0
            chunks = [] if retain else None
            while chunk := stream.read(1024 * 1024):
                count += len(chunk)
                _require(count <= limit, "file grew beyond limit: " + relative)
                digest.update(chunk)
                if retain:
                    chunks.append(chunk)
            after = os.fstat(stream.fileno())
        current = path.stat()
    except OSError as error:
        raise BundleError("cannot read required file: " + relative) from error
    stamp = lambda info: (info.st_dev, info.st_ino, info.st_size,
                          info.st_mtime_ns, info.st_ctime_ns)
    _require(stamp(before) == stamp(after) == stamp(current)
             and count == before.st_size and not path.is_symlink(),
             "file changed while being verified: " + relative)
    record = {"path": relative, "sha256": digest.hexdigest(), "size": count}
    return record, b"".join(chunks) if retain else None


def file_record(root, relative, *, limit=256 * 1024 * 1024):
    return _read_regular(root, relative, limit=limit, retain=False)[0]


def read_file(root, relative, *, limit=4 * 1024 * 1024):
    """Read bounded regular-file bytes and their identity from the same handle."""
    return _read_regular(root, relative, limit=limit, retain=True)


def source_inventory(root):
    return [file_record(root, path, limit=16 * 1024 * 1024) for path in SOURCE_PATHS]


def inventory_digest(records):
    return hashlib.sha256(canonical_bytes(records)).hexdigest()


def _records(rows, *, roles=False, native=False):
    _require(type(rows) is list and rows, "missing artifact inventory")
    seen = set()
    for row in rows:
        size_key = "size_bytes" if native else "size"
        keys = {"path", "sha256", size_key} | ({"role"} if roles else set())
        _require(type(row) is dict and set(row) == keys, "invalid artifact record")
        if roles:
            _require(type(row["role"]) is str, "invalid artifact role")
        _identity(row["sha256"], _HEX64, "artifact digest")
        _require(type(row[size_key]) is int and 0 < row[size_key] <= 256 * 1024 * 1024,
                 "invalid artifact size")
        path = row["path"]
        _require(type(path) is str and path not in seen, "duplicate artifact path")
        _path_parts(path)
        seen.add(path)
    return rows


def _validate_manifest(data):
    _require(type(data) is dict and set(data) == MANIFEST_KEYS, "invalid manifest fields")
    _require(type(data["schema_version"]) is int and data["schema_version"] == 1
             and data["contract_id"] == CONTRACT_ID, "unsupported bundle contract")
    _require(data["backend"] == "simx" and data["format"] in ("fp16", "bf16"),
             "this binding supports only declared SimX FP16/BF16 bundles")
    _identity(data["source_revision"], _HEX40, "source revision")
    _identity(data["source_tree"], _HEX40, "source tree")
    _identity(data["binding_source_sha256"], _HEX64, "binding source digest")
    _identity(data["qualification_id"], _HEX64, "native binding identity")
    _require(data["profile_sha256"] == PROFILE_SHA256, "unsupported native profile")
    _require(data["fixture_sha256"] == FIXTURE_SHA256, "frozen model fixture changed")
    sources = _records(data["binding_sources"])
    _require([row["path"] for row in sources] == list(SOURCE_PATHS),
             "binding source inventory is incomplete or reordered")
    _require(inventory_digest(sources) == data["binding_source_sha256"],
             "binding source inventory digest differs")
    artifacts = _records(data["artifacts"], roles=True)
    _require(len(artifacts) == len(ROLES)
             and {row["role"] for row in artifacts} == set(ROLES), "invalid artifact roles")
    _require(all(row["path"] == ROLES[row["role"]] for row in artifacts),
             "artifact role has the wrong path")
    binding = data["native_binding"]
    _require(type(binding) is dict and set(binding) == {
        "source", "backend", "format", "compiler_records", "artifacts",
        "dependencies", "profile_sha256", "fixture_sha256", "model_id",
    }, "invalid native binding fields")
    _require(hashlib.sha256(json.dumps(binding, sort_keys=True, separators=(",", ":"),
                                       allow_nan=False).encode()).hexdigest()
             == data["qualification_id"], "native qualification identity differs")
    _require(binding["backend"] == data["backend"] and binding["format"] == data["format"]
             and binding["profile_sha256"] == PROFILE_SHA256
             and binding["fixture_sha256"] == FIXTURE_SHA256
             and binding["model_id"] == "p04-tiny-mlp-v1", "native binding variant differs")
    source = binding["source"]
    _require(type(source) is dict and source.get("revision") == data["source_revision"]
             and source.get("tree") == data["source_tree"] and source.get("dirty") is False,
             "native binding does not identify the same clean source")
    _require(type(binding["compiler_records"]) is list and binding["compiler_records"],
             "native compiler records are missing")
    native = _records(binding["artifacts"], native=True)
    dependencies = _records(binding["dependencies"], native=True)
    original = {row["path"]: row for row in native + dependencies}
    _require(len(original) == len(native) + len(dependencies), "duplicate native artifact path")
    expected = {
        "runtime": "sw/runtime/libvortex.so",
        "backend": "sw/runtime/libvortex-simx.so",
        "simulator": "sw/runtime/libsimx.so",
        "ramulator": "third_party/ramulator/libramulator.so",
        "ramulator_extension": "third_party/ramulator_ext/libramulator-vortex.so",
        "module": "tests/regression/ai_mlp/kernel.vxbin",
    }
    for row in artifacts:
        matched = original.get(expected[row["role"]])
        _require(matched is not None and row["sha256"] == matched["sha256"]
                 and row["size"] == matched["size_bytes"],
                 "bundle artifact differs from native binding: " + row["role"])
    return data


def read_manifest(bundle_root):
    try:
        root = Path(bundle_root).resolve(strict=True)
        _require(root.is_dir(), "bundle root is not a directory")
        record, raw = read_file(root, "manifest.json")
    except (OSError, TypeError, ValueError) as error:
        if isinstance(error, BundleError):
            raise
        raise BundleError("native bundle is missing or unreadable") from error
    _require(hashlib.sha256(raw).hexdigest() == record["sha256"], "manifest changed while reading")
    try:
        data = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_nonfinite)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise BundleError("native manifest is not strict UTF-8 JSON") from error
    _require(canonical_bytes(data) == raw, "native manifest is not canonical JSON")
    return root, record["sha256"], _validate_manifest(data)


def validate_files(root, data):
    root = Path(root).resolve(strict=True)
    _require(not any(character in str(root) for character in ":;$")
             and all(ord(character) >= 32 and ord(character) != 127 for character in str(root)),
             "native bundle root contains loader separators or expansion tokens")
    library_dir = _relative(root, "lib")
    _require(library_dir.is_dir()
             and {path.name for path in library_dir.iterdir()}
             == {Path(ROLES[role]).name for role in LIBRARY_ORDER},
             "bundle library directory must contain exactly the five pinned libraries")
    for expected in data["artifacts"]:
        limit = 16 * 1024 * 1024 if expected["role"] == "module" else 256 * 1024 * 1024
        actual = file_record(root, expected["path"], limit=limit)
        _require(actual == {key: expected[key] for key in ("path", "sha256", "size")},
                 "native artifact changed: " + expected["path"])
        if expected["role"] == "module":
            _require(actual["size"] >= 16, "native module is truncated")


def build_binding(bundle_root, source_root):
    root, digest, data = read_manifest(bundle_root)
    _require(source_inventory(source_root) == data["binding_sources"],
             "package sources differ from the qualified bundle")
    validate_files(root, data)
    return digest, data["binding_source_sha256"]


