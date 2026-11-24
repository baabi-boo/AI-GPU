# SPDX-License-Identifier: Apache-2.0
"""Join retained P05 package bytes and installation receipts without execution.

The archive driver validates source/command provenance and numerical records.
This module supplies its immutable installation facts. Recorded absolute paths
are POSIX names only: no producer path is opened, resolved, or imported. Missing
third-party bytes remain observations, even when all their receipts agree.
"""

from __future__ import annotations

import base64
import copy
import csv
from email import policy
from email.parser import BytesParser
import gzip
import hashlib
import io
import json
from pathlib import PurePosixPath
import re
import stat
import struct
import tarfile
import zipfile
import zlib

from p05_execution_records import RetainedIdentity
from p06_replay import _archive_api


MIB = 1024 * 1024
# These describe absent external files, NOT retained archive members. In
# particular libtorch_cpu.so legitimately exceeds the reader's 256 MiB bound.
EXTERNAL_FILE_BYTES = 2 * 1024 * MIB
EXTERNAL_TOTAL_BYTES = 3 * 1024 * MIB
EXTERNAL_FILES = 50000
SITE = "lib/python3.12/site-packages/"
DIST = "vortex_ai-0.1.0.dist-info/"
EXTENSION = "vortex_ai/_native.cpython-312-x86_64-linux-gnu.so"
CONTRACT = "ci/project/p05_torch_contract.json"
LOCK = "ci/project/p05_torch_requirements.lock"
CONTRACT_SHA256 = "295d4cffec7391c25ad1c97f7f808945e9a9df88f10410600d2b17a054623a11"
PROFILE_SHA256 = "79a551bd7ba51b5aa4b221eeb9c8f68b0f3078e6282ce71a1f28e9bc4593a102"
FIXTURE_SHA256 = "d22a899827afb3e8c22a528fc6a27fd12ff114ef39caf9ffa0cccd77e849cd03"
SOURCE_PATHS = tuple(sorted((
    "pyproject.toml", "setup.py", "MANIFEST.in", "python/vortex_ai/__init__.py",
    "python/vortex_ai/_api.py", "python/vortex_ai/_bundle.py", "python/vortex_ai/launch.py",
    "python/vortex_ai/torch_ops.py", "python/native/module.cpp", "python/native/runtime_loader.cpp",
    "python/native/runtime_loader.h", "sw/runtime/ai/contract.cpp", "sw/runtime/ai/contract.h",
    "sw/runtime/ai/runtime.cpp", "sw/runtime/ai/runtime.h", "sw/runtime/ai/mlp_runtime.cpp",
    "sw/runtime/ai/mlp_runtime.h", "sw/runtime/ai/mlp_host.cpp", "sw/runtime/ai/mlp_host.h",
    "sw/runtime/include/vortex2.h", "sw/common/ai_matmul_args.h",
    "tests/regression/ai_mlp/p04_fixtures.h", "tests/regression/ai_mlp/records.h",
)))
ROLES = {
    "ramulator": ("lib/libramulator.so", "third_party/ramulator/libramulator.so"),
    "ramulator_extension": ("lib/libramulator-vortex.so", "third_party/ramulator_ext/libramulator-vortex.so"),
    "runtime": ("lib/libvortex.so", "sw/runtime/libvortex.so"),
    "simulator": ("lib/libsimx.so", "sw/runtime/libsimx.so"),
    "backend": ("lib/libvortex-simx.so", "sw/runtime/libvortex-simx.so"),
    "module": ("kernel.vxbin", "tests/regression/ai_mlp/kernel.vxbin"),
}
LIBRARY_ORDER = ("ramulator", "ramulator_extension", "runtime", "simulator", "backend")
ENTRY_POINTS = ("bin/f2py", "bin/isympy", "bin/numpy-config", "bin/torchfrtrace", "bin/torchrun")
HELPERS = ("p05_torch_installed_check.py", "p05_torch_records.py",
           "p05_installed_check.py", "p05_torch_contract.json")
WHEEL_METADATA = ("METADATA", "WHEEL", "RECORD", "licenses/LICENSE", "top_level.txt")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
REVISION = re.compile(r"[0-9a-f]{40}\Z")
LIMITATIONS = (
    "Third-party wheel archives and installed framework payload bytes, including Torch binaries, are absent; their locked identities, inventory joins and stability are recorded observations only.",
    "The combined framework payload inventory has no per-wheel ownership: absent wheel bytes prevent independent derivation of third-party payloads or entry-point metadata from the wheel lock.",
    "Generated third-party entry points, seed pip, interpreter, packaging-tool and shared interpreter/OS library bytes are absent and cannot be freshly hashed.",
    "Framework pyvenv.cfg is retained only as a descriptor; its include-system-site-packages content check cannot be repeated.",
    "The framework installation's rewritten Vortex RECORD and direct_url.json bytes are absent; the retained plain-Python metadata does not establish those bytes.",
    "The framework observations do not separately retain the loaded Torch _C object; no fresh loader or third-party binary qualification is established.",
    "Retained extension bytes and build/source pins establish consistency, not reproducible compilation or machine-code behavior; trusted-builder/non-adversarial-filesystem scope remains.",
)


class InstallationError(ValueError):
    """Retained installation bytes or receipts fail a required join."""


def _require(condition, message):
    if not condition:
        raise InstallationError(message)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _same(actual, expected, label):
    _require(_canonical(actual) == _canonical(expected), label + " differs")


def _fields(value, names, label):
    _require(type(value) is dict and set(value) == set(names), "invalid " + label + " fields")


def _row(name, raw):
    return {"path": name, "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}


def _inventory(rows, api, label, *, ordered=True, per_file=EXTERNAL_FILE_BYTES,
               total_limit=EXTERNAL_TOTAL_BYTES, absolute=False):
    """Validate absent-file receipts separately from the archive byte bounds."""
    _require(type(rows) is list and 0 < len(rows) <= EXTERNAL_FILES, "invalid " + label + " inventory")
    names, total = [], 0
    for row in rows:
        _fields(row, ("path", "sha256", "size_bytes"), label + " descriptor")
        (api.recorded_absolute if absolute else api.relative_name)(row["path"])
        _require(type(row["sha256"]) is str and SHA256.fullmatch(row["sha256"]),
                 "invalid " + label + " digest")
        size = row["size_bytes"]
        _require(type(size) is int and 0 <= size <= per_file, "invalid " + label + " file size")
        total += size
        _require(total <= total_limit, label + " exceeds its total byte bound")
        names.append(row["path"])
    name_set = set(names)
    _require(len(name_set) == len(names), label + " repeats a path")
    _require(not any(str(parent) in name_set for name in names for parent in PurePosixPath(name).parents),
             label + " has a file/directory collision")
    _require(not ordered or names == sorted(names), label + " inventory is reordered")
    return {row["path"]: row for row in rows}


def _snapshot(view, report, key):
    return view.document(report[key], "snapshots/" + key.replace("_", "-") + ".json", integers_only=True)


def _retained_tree(view, prefix, rows, api, label):
    _inventory(rows, api, label, per_file=api.MEMBER_BYTES, total_limit=api.EXPANDED_BYTES)
    tree = view.subview(prefix)
    _same(tree.inventory(), rows, label + " retained bytes")
    return tree


def _manifest(python, torch, python_report, torch_report, native, api, revision, fmt):
    raw = python.verified(python_report["bundle_manifest"], "artifacts/bundle/manifest.json")
    _require(torch.verified(torch_report["bundle_manifest"], "artifacts/bundle/manifest.json") == raw,
             "Python/framework bundle manifests differ")
    value = api.strict_json(raw, integers_only=True)
    _fields(value, ("schema_version", "contract_id", "backend", "format", "source_revision", "source_tree",
                   "binding_sources", "binding_source_sha256", "profile_sha256", "fixture_sha256",
                   "qualification_id", "native_binding", "artifacts"), "bundle manifest")
    _require(raw == _canonical(value) + b"\n", "bundle manifest is not canonical")
    _same({key: value[key] for key in ("schema_version", "contract_id", "backend", "format", "source_revision",
                                      "profile_sha256", "fixture_sha256")},
          {"schema_version": 1, "contract_id": "p05-python-bundle-v1", "backend": "simx", "format": fmt,
           "source_revision": revision, "profile_sha256": PROFILE_SHA256, "fixture_sha256": FIXTURE_SHA256},
          "bundle contract")
    source = _snapshot(python, python_report, "source_before")
    _same(source, native["python_source"], "independently verified Python source")
    _require(source["checkout"]["revision"] == revision and source["checkout"]["dirty"] is False,
             "bundle source is not the expected clean revision")
    _same(value["source_tree"], source["checkout"]["tree"], "bundle source tree")
    _require(type(value["source_tree"]) is str and REVISION.fullmatch(value["source_tree"]), "invalid bundle source tree")
    _same(value["native_binding"], native["model_binding"], "bundle/native model binding")
    _same(value["qualification_id"], hashlib.sha256(_canonical(value["native_binding"])).hexdigest(),
          "bundle qualification identity")
    _same(value["qualification_id"], python_report["native_qualification_id"], "Python native qualification identity")
    sources = value["binding_sources"]
    _require(type(sources) is list and len(sources) == len(SOURCE_PATHS), "incomplete bundle source inventory")
    source_rows = []
    for row in sources:
        _fields(row, ("path", "sha256", "size"), "bundle source")
        _require(type(row["size"]) is int and row["size"] > 0, "empty bundle source")
        source_rows.append({"path": row["path"], "sha256": row["sha256"], "size_bytes": row["size"]})
    _inventory(source_rows, api, "bundle sources", per_file=16 * MIB)
    _same([row["path"] for row in source_rows], list(SOURCE_PATHS), "bundle source membership")
    _same(value["binding_source_sha256"], hashlib.sha256(_canonical(sources) + b"\n").hexdigest(),
          "bundle source inventory pin")
    source_index = _inventory(source["files"], api, "Python source", per_file=api.MEMBER_BYTES)
    for row in source_rows:
        _same(source_index.get(row["path"]), row, "bound source snapshot " + row["path"])
        for view in (python, torch):
            _same(view.identity("artifacts/source/" + row["path"]),
                  {**row, "path": "artifacts/source/" + row["path"]}, "retained bound source " + row["path"])
    artifacts = value["artifacts"]
    _require(type(artifacts) is list and len(artifacts) == len(ROLES), "incomplete bundle artifacts")
    binding = value["native_binding"]
    _same(binding["source"], source["checkout"], "bundle native/Python source")
    original = _inventory(binding["artifacts"] + binding["dependencies"], api, "native binding artifacts", ordered=False,
                          per_file=api.MEMBER_BYTES)
    roles, artifact_rows = set(), []
    for row in artifacts:
        _fields(row, ("role", "path", "sha256", "size"), "bundle artifact")
        role = row["role"]
        _require(type(role) is str and role in ROLES and role not in roles, "duplicate or unknown bundle role")
        roles.add(role)
        _require(type(row["size"]) is int and row["size"] > 0, "empty bundle artifact")
        relative, native_name = ROLES[role]
        expected = {"path": relative, "sha256": row["sha256"], "size_bytes": row["size"]}
        _same(row["path"], relative, "bundle artifact role path")
        _same(original.get(native_name), {**expected, "path": native_name}, "bundle/native artifact " + role)
        if role == "module":
            _require(16 <= row["size"] <= 16 * MIB, "invalid retained native module size")
        artifact_rows.append(expected)
    artifact_rows.append(_row("manifest.json", raw))
    artifact_rows.sort(key=lambda row: row["path"])
    for view, report in ((python, python_report), (torch, torch_report)):
        _same(report["bundle_artifacts"], artifact_rows, "bundle artifact receipt")
        _retained_tree(view, "artifacts/bundle", artifact_rows, api, "bundle")
    return value, raw


def _pin_header(manifest, bundle_sha256):
    """Reconstruct inert generated text; never load the retained setup.py."""
    values = {"bundle_sha256": bundle_sha256, "source_sha256": manifest["binding_source_sha256"],
              **{key: manifest[key] for key in ("backend", "format", "qualification_id", "source_revision")}}
    lines = ["// SPDX-License-Identifier: Apache-2.0", "// Generated from validated build inputs. Do not edit.",
             "#ifndef VORTEX_AI_P05_BUILD_CONFIG_H", "#define VORTEX_AI_P05_BUILD_CONFIG_H", "#include <array>",
             "#include <cstdint>", "namespace vortex_ai_python::build {", "struct Artifact {", "  const char* role;",
             "  const char* path;", "  const char* sha256;", "  std::uint64_t size;", "};"]
    lines.extend("inline constexpr char " + key + "[] = " + json.dumps(value) + ";" for key, value in values.items())
    lines.append("inline constexpr std::array<Artifact, 6> artifacts{{")
    for row in sorted(manifest["artifacts"], key=lambda row: row["role"]):
        fields = [json.dumps(row[key]) for key in ("role", "path", "sha256")] + [str(row["size"]) + "ULL"]
        lines.append("  {" + ", ".join(fields) + "},")
    return "\n".join(lines + ["}};", "}  // namespace vortex_ai_python::build", "#endif", ""]).encode("utf-8")


def _wheel_members(raw, manifest, api):
    # Bound the nested central directory BEFORE ZipFile allocates its entries.
    end = struct.Struct("<4s4H2IH")
    offset = raw.rfind(b"PK\x05\x06", max(0, len(raw) - end.size - 65535))
    _require(offset >= 0 and offset + end.size <= len(raw), "wheel end record is missing")
    _, disk, start_disk, disk_count, count, size, start, comment = end.unpack_from(raw, offset)
    _require(disk == start_disk == 0 and disk_count == count and 0 < count <= 1024
             and size <= MIB and start + size == offset and comment == 0 and offset + end.size == len(raw),
             "unsupported or excessive wheel directory")
    sources = {row["path"].removeprefix("python/"): row for row in manifest["binding_sources"]
               if row["path"].startswith("python/vortex_ai/")}
    expected_names = set(sources) | {EXTENSION} | {DIST + name for name in WHEEL_METADATA}
    _require(count == len(expected_names), "wheel closed member count differs")
    members, total = {}, 0
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        _require(len(entries) == count and min(item.header_offset for item in entries) == 0,
                 "wheel directory/header layout differs")
        for item in entries:
            name = api.relative_name(item.filename)
            _require(item.orig_filename == name and name not in members and not item.is_dir(),
                     "wheel has a duplicate, hidden or directory member")
            _require(name in expected_names, "wheel contains an unexpected member")
            _require(stat.S_IFMT(item.external_attr >> 16) in (0, stat.S_IFREG)
                     and not item.flag_bits & 1 and item.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED),
                     "wheel has an unsupported member type")
            member_limit = api.MEMBER_BYTES if name == EXTENSION else 16 * MIB
            _require(0 <= item.file_size <= member_limit and 0 <= item.header_offset < start,
                     "wheel member exceeds its byte bound")
            total += item.file_size
            _require(total <= 512 * MIB, "wheel exceeds its expanded byte bound")
            with archive.open(item) as stream:
                data = stream.read(item.file_size + 1)
            _require(len(data) == item.file_size, "wheel member length differs")
            members[name] = data
    _same(sorted(members), sorted(expected_names),
          "wheel closed package membership")
    for name, row in sources.items():
        _same(_row(name, members[name]), {"path": name, "sha256": row["sha256"], "size_bytes": row["size"]},
              "wheel bound Python source " + name)
    rows = [_row(name, members[name]) for name in sorted(members)]
    _record_csv(members[DIST + "RECORD"], {row["path"]: row for row in rows}, DIST + "RECORD")
    for leaf, expected in (("METADATA", {"Name": "vortex-ai", "Version": "0.1.0"}),
                           ("WHEEL", {"Wheel-Version": "1.0", "Root-Is-Purelib": "false",
                                      "Build": "1" + hashlib.sha256(_canonical(manifest) + b"\n").hexdigest(),
                                      "Tag": "cp312-cp312-linux_x86_64"})):
        metadata = BytesParser(policy=policy.default).parsebytes(members[DIST + leaf])
        _require(not metadata.defects, "malformed wheel metadata")
        for key, value in expected.items():
            _same(metadata.get_all(key), [value], "wheel metadata " + leaf + "/" + key)
    _require(members[DIST + "top_level.txt"] == b"vortex_ai\n", "wheel top-level package metadata differs")
    return members, rows


def _record_csv(raw, inventory, own_path):
    parsed = list(csv.reader(io.StringIO(raw.decode("utf-8"), newline="")))
    _require(len(parsed) == len(inventory) and all(len(row) == 3 for row in parsed), "invalid package RECORD inventory")
    _require(len({row[0] for row in parsed}) == len(parsed) and {row[0] for row in parsed} == set(inventory),
             "package RECORD membership differs")
    for name, digest, size in parsed:
        if name == own_path:
            _require(digest == size == "", "package RECORD hashes itself")
        else:
            row = inventory[name]
            encoded = base64.urlsafe_b64encode(bytes.fromhex(row["sha256"])).rstrip(b"=").decode("ascii")
            _require(digest == "sha256=" + encoded and size == str(row["size_bytes"]),
                     "package RECORD file identity differs: " + name)


def _sdist_members(raw, api):
    # Parse a bounded decompressed byte string. No tar extraction API is used.
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as compressed:
        unpacked = compressed.read(80 * MIB + 1)
    _require(len(unpacked) <= 80 * MIB, "source archive exceeds its decompression bound")
    files, names, total = {}, set(), 0
    with tarfile.open(fileobj=io.BytesIO(unpacked), mode="r:") as archive:
        for index, item in enumerate(archive):
            _require(index < 1024, "source archive has excessive members")
            name = api.relative_name(item.name.rstrip("/") if item.isdir() else item.name)
            _require(name not in names and (item.isdir() or item.type in (tarfile.REGTYPE, tarfile.AREGTYPE))
                     and item.sparse is None, "source archive repeats a path or has a link/sparse member")
            names.add(name)
            parts = PurePosixPath(name).parts
            _require(parts[0] == "vortex_ai-0.1.0", "source archive root differs")
            if item.isdir():
                _require(item.size == 0, "source archive directory has bytes")
                continue
            _require(len(parts) > 1 and 0 <= item.size <= 16 * MIB, "source archive member is oversized")
            total += item.size
            _require(total <= 64 * MIB, "source archive exceeds its payload bound")
            data = unpacked[item.offset_data:item.offset_data + item.size]
            _require(len(data) == item.size, "truncated source archive member")
            files["/".join(parts[1:])] = data
    for name in names:
        _require(not any(str(parent).removeprefix("vortex_ai-0.1.0/") in files
                         for parent in PurePosixPath(name).parents), "source archive file shadows a directory")
    return files


def _packages(python, torch, pr, tr, manifest, manifest_raw, api):
    packages = _inventory(pr["packages"], api, "Python packages", per_file=api.MEMBER_BYTES)
    digest = hashlib.sha256(manifest_raw).hexdigest()
    wheel_name = "vortex_ai-0.1.0-1" + digest + "-cp312-cp312-linux_x86_64.whl"
    wheel_path, sdist_path = "packages/wheel/" + wheel_name, "packages/sdist/vortex_ai-0.1.0.tar.gz"
    _same(sorted(packages), sorted((wheel_path, sdist_path)), "Python package inventory")
    _same([name for name in python.files() if name.startswith("packages/")], sorted(packages), "retained Python packages")
    wheel_raw = python.verified(packages[wheel_path], wheel_path, limit=api.MEMBER_BYTES)
    _same(tr["python_revalidation"]["wheel"], packages[wheel_path], "revalidated wheel receipt")
    _same(tr["installed_wheel"], {**packages[wheel_path], "path": "packages/" + wheel_name}, "framework wheel receipt")
    _same([name for name in torch.files() if name.startswith("packages/")], ["packages/" + wheel_name],
          "retained framework packages")
    _require(torch.verified(tr["installed_wheel"], "packages/" + wheel_name, limit=api.MEMBER_BYTES) == wheel_raw,
             "retained framework wheel differs from Python wheel")
    members, wheel_rows = _wheel_members(wheel_raw, manifest, api)
    _same(_snapshot(python, pr, "wheel_inventory"), wheel_rows, "wheel inventory snapshot")
    pins = {"manifest.json": manifest_raw, "source_inventory.json": _canonical(manifest["binding_sources"]) + b"\n",
            "p05_build_config.h": _pin_header(manifest, digest)}
    _retained_tree(python, "artifacts/sdist-pin", [_row(name, pins[name]) for name in sorted(pins)], api, "sdist pins")
    files = _sdist_members(python.verified(packages[sdist_path], sdist_path, limit=api.MEMBER_BYTES), api)
    names = set(SOURCE_PATHS) | {"LICENSE", "python/README.md", "PKG-INFO"}
    names.update("python/p05_build/" + name for name in pins)
    names.update("python/vortex_ai.egg-info/" + name for name in ("PKG-INFO", "SOURCES.txt", "dependency_links.txt", "top_level.txt"))
    _same(sorted(files), sorted(names), "sdist closed file membership")
    # The producer's tree walk sorts Path components, not full path strings;
    # vortex_ai/ and vortex_ai.egg-info/ consequently have a different order.
    _same(_snapshot(python, pr, "extracted_sdist_before_build"),
          [_row(name, files[name]) for name in sorted(files, key=lambda name: PurePosixPath(name).parts)],
          "sdist pre-build inventory")
    for name, raw in pins.items():
        _require(files["python/p05_build/" + name] == raw, "sdist pin differs: " + name)
    stage = _snapshot(python, pr, "package_source_stage")
    _inventory(stage, api, "package source stage", per_file=16 * MIB)
    expected_stage = [_row(name, files[name]) for name in sorted(set(SOURCE_PATHS) | {"LICENSE", "python/README.md"})]
    _same(stage, expected_stage, "package source stage inventory")
    for row in expected_stage:
        _same(python.identity("artifacts/source/" + row["path"]), {**row, "path": "artifacts/source/" + row["path"]},
              "sdist retained source " + row["path"])
    _require(members[DIST + "licenses/LICENSE"] == files["LICENSE"], "wheel license differs from source archive")
    return wheel_rows, members, wheel_path


def _plain_installation(python, pr, wheel_rows, wheel_path, api):
    rows = _snapshot(python, pr, "installed_before")
    installed = _inventory(rows, api, "plain installed package", per_file=api.MEMBER_BYTES)
    _same(_snapshot(python, pr, "installed_after"), rows, "plain installation stability")
    tree = _retained_tree(python, "artifacts/installed", rows, api, "plain installation")
    _same(sorted(installed), sorted([row["path"] for row in wheel_rows] +
                                  [DIST + name for name in ("INSTALLER", "REQUESTED", "direct_url.json")]),
          "plain installed package membership")
    for row in wheel_rows:
        if row["path"] != DIST + "RECORD":
            _same(installed.get(row["path"]), row, "plain installed wheel member " + row["path"])
    _require(tree.read(DIST + "INSTALLER") == b"pip\n" and tree.read(DIST + "REQUESTED") == b"",
             "plain installation pip metadata differs")
    _record_csv(tree.read(DIST + "RECORD"), installed, DIST + "RECORD")
    wheel = next(row for row in pr["packages"] if row["path"] == wheel_path)
    _same(tree.json(DIST + "direct_url.json"), {
        "archive_info": {"hash": "sha256=" + wheel["sha256"], "hashes": {"sha256": wheel["sha256"]}},
        "url": (api.recorded_absolute(pr["paths"]["output"]) / wheel_path).as_uri()}, "plain installed wheel URL")
    return installed


def _locked_framework(torch, tr, api):
    raw = torch.verified(tr["contract"], "artifacts/source/" + CONTRACT)
    _require(hashlib.sha256(raw).hexdigest() == CONTRACT_SHA256, "unsupported frozen framework contract")
    contract = api.strict_json(raw, integers_only=True)
    lock = torch.verified(tr["requirements"], "artifacts/source/" + LOCK)
    _same(contract["requirements"], {"path": LOCK, "sha256": hashlib.sha256(lock).hexdigest()}, "framework lock pin")
    _same([line for line in lock.decode("utf-8").splitlines() if line and not line.startswith("#")],
          [row["name"] + "==" + row["version"] + " --hash=sha256:" + row["sha256"] for row in contract["wheels"]],
          "framework locked requirements")
    expected = [{"path": row["filename"], "sha256": row["sha256"], "size_bytes": row["size"]}
                for row in contract["wheels"]]
    _fields(tr["wheelhouse"], ("directory", "files"), "wheelhouse")
    _same(tr["wheelhouse"]["directory"], tr["paths"]["wheelhouse"], "framework wheelhouse directory")
    api.recorded_absolute(tr["wheelhouse"]["directory"])
    _same(tr["wheelhouse"]["files"], expected, "recorded wheelhouse lock")
    _same(_snapshot(torch, tr, "wheelhouse_after"), expected, "recorded wheelhouse stability")
    return contract


def _framework_inventory(torch, tr, wheel_rows, plain, contract, api):
    rows = _snapshot(torch, tr, "installed_before")
    installed = _inventory(rows, api, "framework installation")
    _same(_snapshot(torch, tr, "installed_after"), rows, "framework installation stability")
    payload = _inventory(_snapshot(torch, tr, "framework_wheel_payload"), api, "framework wheel payload")
    seed = _inventory(_snapshot(torch, tr, "venv_seed"), api, "framework seed")
    for name in set(installed) | set(payload) | set(seed):
        _require(name.startswith((SITE, "bin/", "share/")), "framework file is outside the inventoried installation roots")
    _same(tr["framework_entry_points"], list(ENTRY_POINTS), "framework recorded entry points")
    records = {name for name in payload if name.startswith(SITE) and len(name[len(SITE):].split("/")) == 2
               and name.endswith(".dist-info/RECORD")}
    roots = {name.removesuffix("/RECORD") for name in records}
    expected_roots = {SITE + "-".join(row["filename"].split("-")[:2]) + ".dist-info" for row in contract["wheels"]}
    expected_roots.add(SITE + DIST.rstrip("/"))
    _same(sorted(roots), sorted(expected_roots), "framework payload distribution roots")
    for root in roots:
        _require(all(root + "/" + leaf in payload for leaf in ("METADATA", "WHEEL", "RECORD")),
                 "framework payload lacks distribution metadata")
    for name, row in payload.items():
        if name in records:
            _require(name in installed, "framework installation lacks rewritten RECORD")
        else:
            _same(installed.get(name), row, "framework payload/installation " + name)
    allowed = set(payload) | set(ENTRY_POINTS) | set(seed)
    allowed.update(root + "/" + leaf for root in roots for leaf in ("INSTALLER", "REQUESTED", "direct_url.json"))
    _require(set(installed) <= allowed and set(ENTRY_POINTS) <= set(installed),
             "framework installation has unexplained or missing files")
    _require(not set(seed) & (set(payload) | set(ENTRY_POINTS)), "framework seed overlaps installed wheel payloads")
    for name, row in seed.items():
        _same(installed.get(name), row, "framework seed stability " + name)
    first_party = {SITE + row["path"]: {**row, "path": SITE + row["path"]} for row in wheel_rows}
    actual_first = {name: row for name, row in payload.items() if name.startswith((SITE + "vortex_ai/", SITE + DIST))}
    _same(actual_first, first_party, "framework first-party wheel payload")
    for name, row in plain.items():
        if name not in (DIST + "RECORD", DIST + "direct_url.json"):
            _same(installed.get(SITE + name), {**row, "path": SITE + name}, "plain/framework immutable installation " + name)
    _same(sorted(name[len(SITE):] for name in installed if name.startswith((SITE + "vortex_ai/", SITE + DIST))),
          sorted(plain), "framework first-party installed membership")
    pip = [name for name in seed if re.fullmatch(re.escape(SITE) + r"pip-[^/]+\.dist-info/METADATA", name)]
    _require(len(pip) == 1 and "bin/python" in seed, "framework seed lacks its pip/interpreter inventory")
    pip_version = pip[0].split("/")[-2].removeprefix("pip-").removesuffix(".dist-info")
    versions = {re.sub(r"[-_.]+", "_", row["name"]).lower(): row["version"] for row in contract["wheels"]}
    versions.update(pip=pip_version, vortex_ai="0.1.0")
    return installed, payload, seed, versions


def _marker(view, name, marker, api):
    raw = view.read("logs/" + name + ".log")
    text = raw.decode("utf-8")
    _require(not any((ord(char) < 32 and char not in "\t\n\r") or 127 <= ord(char) <= 159 for char in text),
             "environment log contains unsupported control characters")
    lines = [line[len(marker):] for line in text.splitlines() if line.startswith(marker)]
    _require(len(lines) == 1, "environment log marker is missing or duplicated: " + name)
    return api.strict_json(lines[0].encode("utf-8"), integers_only=True)


def _distribution_path(name, api):
    _require(type(name) is str and 0 < len(name.encode("utf-8")) <= 4096 and "\\" not in name
             and not name.startswith("/") and not re.match(r"[A-Za-z]:", name)
             and not any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in name), "invalid distribution file reference")
    parts = name.split("/")
    _require(len(parts) <= 64 and all(part not in ("", ".") for part in parts), "noncanonical distribution file reference")
    stack = SITE.rstrip("/").split("/")
    for part in parts:
        if part == "..":
            _require(stack, "distribution file escapes the recorded venv")
            stack.pop()
        else:
            stack.append(part)
    return api.relative_name("/".join(stack))


def _environments(torch, tr, installed, seed, versions, prefix, base_prefix, api):
    before = _snapshot(torch, tr, "framework_before")
    _same(_snapshot(torch, tr, "framework_after"), before, "framework environment stability")
    _fields(before, ("python_version", "implementation", "platform", "machine", "byteorder", "gil", "prefix",
                     "base_prefix", "executable", "isolated", "torch_version", "torch_file", "cuda", "torch_config",
                     "distributions"), "framework environment")
    _same({key: before[key] for key in set(before) - {"torch_config", "distributions"}}, {
        "python_version": [3, 12, 14], "implementation": "CPython", "platform": "linux", "machine": "x86_64",
        "byteorder": "little", "gil": True, "prefix": str(prefix), "base_prefix": base_prefix,
        "executable": str(prefix / "bin/python"), "isolated": 1, "torch_version": "2.15.0+cpu",
        "torch_file": str(prefix / SITE / "torch/__init__.py"), "cuda": None}, "framework environment identity")
    _require(type(before["torch_config"]) is str and 0 < len(before["torch_config"].encode("utf-8")) <= MIB,
             "framework configuration text is missing or oversized")
    _fields(before["distributions"], versions, "framework distribution closure")
    distributed = set()
    for name, distribution in before["distributions"].items():
        _fields(distribution, ("version", "root", "files"), "framework distribution")
        _same(distribution["version"], versions[name], "framework distribution version " + name)
        _same(distribution["root"], str(prefix / SITE), "framework distribution root " + name)
        rows = _inventory(distribution["files"], api, "distribution " + name, ordered=False)
        if name == "vortex_ai":
            _same(sorted(rows), sorted(path for path in installed
                                      if path.startswith((SITE + "vortex_ai/", SITE + DIST))),
                  "framework first-party distribution membership")
        _require(not distributed & set(rows), "framework distributions claim overlapping files")
        distributed.update(rows)
        for path, row in rows.items():
            _same(installed.get(path), row, "distribution/installed file " + path)
    _require(set(installed) - set(seed) <= distributed,
             "framework distribution lists omit installed wheel or generated files")
    _require(SITE + "torch/__init__.py" in {row["path"] for row in before["distributions"]["torch"]["files"]},
             "framework module is absent from its distribution inventory")
    for command in ("framework-environment-before", "framework-environment-after"):
        observed = _marker(torch, command, "P05_TORCH_ENVIRONMENT ", api)
        _fields(observed, before, "raw framework environment")
        _fields(observed["distributions"], versions, "raw framework distribution closure")
        for name, distribution in observed["distributions"].items():
            _fields(distribution, ("version", "root", "files"), "raw framework distribution")
            files = distribution["files"]
            _require(type(files) is list and 0 < len(files) <= EXTERNAL_FILES and all(type(item) is str for item in files)
                     and files == sorted(set(files)), "raw distribution file list is invalid")
            paths = [_distribution_path(item, api) for item in files]
            _require(len(set(paths)) == len(paths) and all(path in installed for path in paths),
                     "raw distribution has aliases or uninventoried files")
            distribution["files"] = [installed[path] for path in paths]
        _same(observed, before, "raw framework environment " + command)
    return before


def _interpreter(row, api, label):
    _fields(row, ("path", "resolved_path", "sha256", "size_bytes"), label)
    api.recorded_absolute(row["path"])
    api.recorded_absolute(row["resolved_path"])
    _inventory([{key: row[key] for key in ("path", "sha256", "size_bytes")}], api, label, absolute=True,
               per_file=api.MEMBER_BYTES)
    _require(row["size_bytes"] > 0, "empty recorded interpreter")
    return row["sha256"], row["size_bytes"]


def _join_identity(identities, path, row):
    identity = row["sha256"], row["size_bytes"]
    _same(identities.setdefault(path, identity), identity, "recorded file identity " + path)


def _package_tools(python, pr, provisioning, executables, api):
    before = _snapshot(python, pr, "package_tools_before")
    _same(_snapshot(python, pr, "package_tools_after"), before, "package prerequisite stability")
    _fields(before, ("distributions", "executable", "implementation", "python_version"), "package prerequisites")
    _same({key: before[key] for key in ("executable", "implementation", "python_version")}, {
        "executable": provisioning["path"], "implementation": "CPython", "python_version": [3, 12, 14]},
        "package prerequisite interpreter")
    expected = {"setuptools": "84.2.1", "wheel": "0.48.0", "packaging": "26.3"}
    _fields(before["distributions"], expected, "package prerequisite distributions")
    identities = {}
    for row in executables:
        for key in ("path", "resolved_path"):
            _join_identity(identities, str(api.recorded_absolute(row[key])), row)
    for name, value in before["distributions"].items():
        _fields(value, ("version", "files"), "package prerequisite distribution")
        _same(value["version"], expected[name], "package prerequisite version")
        rows = _inventory(value["files"], api, "package prerequisite " + name, absolute=True, ordered=False, per_file=16 * MIB)
        for path, row in rows.items():
            _join_identity(identities, path, row)
    for command in ("package-tools-before", "package-tools-after"):
        _same(_marker(python, command, "P05_PACKAGE_TOOLS ", api), before, "raw package prerequisite " + command)


def _observed_installation(observation, request, manifest, extension, base_prefix, api):
    value = observation["installation"]
    _fields(value, ("python_version", "python_implementation", "executable", "prefix", "base_prefix", "package_file",
                    "extension_file", "distribution_version", "build_info", "runtime_libraries"), "observed installation")
    prefix = api.recorded_absolute(request["expected_prefix"])
    bundle = api.recorded_absolute(request["binding"]["bundle_root"])
    _same(value, {
        "python_version": [3, 12, 14], "python_implementation": "CPython", "executable": str(prefix / "bin/python"),
        "prefix": str(prefix), "base_prefix": base_prefix, "package_file": str(prefix / SITE / "vortex_ai/__init__.py"),
        "extension_file": str(prefix / SITE / extension), "distribution_version": "0.1.0",
        "build_info": {"binding_api": 1, "bundle_sha256": request["binding"]["bundle_sha256"],
                       "source_sha256": manifest["binding_source_sha256"]},
        "runtime_libraries": [str(bundle / ROLES[role][0]) for role in LIBRARY_ORDER]}, "observed installation identity")
    _same(observation["binding"], request["binding"], "observed native binding")


def verify_installations(outer_view, torch_report, native_result, *, expected_revision, expected_format):
    """Return identities only after joining retained bytes and external receipts.

    ``outer_view`` is the root original-archive PacketView. The native verifier
    must already have checked nested packet equality and reconstructed its
    ``model_binding`` and ``python_source`` as well as the documented Python
    report/request/observation results. The public driver performs final archive
    close/rehash and does not treat this helper alone as an execution verdict.
    """
    api = _archive_api()
    try:
        _require(type(expected_revision) is str and REVISION.fullmatch(expected_revision), "invalid expected source revision")
        _require(expected_format in ("fp16", "bf16"), "invalid expected format")
        torch, python = outer_view.subview("torch"), outer_view.subview("python")
        pr, tr = native_result["python_report"], torch_report
        _same(python.json("report.json"), pr, "verified Python report")
        _same(torch.json("report.json"), tr, "verified framework report")
        _same(torch.document(tr["python_report"], "python/report.json"), pr, "copied Python report")
        for key in ("source", "work", "output"):
            api.recorded_absolute(pr["paths"][key])
            api.recorded_absolute(tr["paths"][key])
        _same(tr["paths"]["python_output"], pr["paths"]["output"], "recorded Python output root")
        _same(tr["paths"]["python_work"], pr["paths"]["work"], "recorded Python work root")
        _same(tr["paths"]["source"], pr["paths"]["source"], "recorded source root")
        manifest, manifest_raw = _manifest(python, torch, pr, tr, native_result, api, expected_revision, expected_format)
        digest = hashlib.sha256(manifest_raw).hexdigest()
        _same(tr["python_revalidation"]["bundle_sha256"], digest, "revalidated bundle digest")
        wheel_rows, members, wheel_path = _packages(python, torch, pr, tr, manifest, manifest_raw, api)
        plain = _plain_installation(python, pr, wheel_rows, wheel_path, api)
        contract = _locked_framework(torch, tr, api)
        installed, payload, seed, versions = _framework_inventory(torch, tr, wheel_rows, plain, contract, api)
        python_request = _snapshot(python, pr, "installed_request")
        _same(python_request, native_result["python_request"], "verified Python request")
        python_observations = python.document(pr["observations"], "artifacts/installed-observations.json", integers_only=True)
        _same(python_observations, native_result["python_observations"], "verified Python observations")
        prefix = api.recorded_absolute(tr["paths"]["work"]) / "venv"
        python_prefix = api.recorded_absolute(pr["paths"]["work"]) / "venv"
        _same(python_request["expected_prefix"], str(python_prefix), "Python venv prefix")
        _same(python_request["binding"], {"backend": "simx", "format": expected_format,
            "bundle_root": str(api.recorded_absolute(pr["paths"]["output"]) / "artifacts/bundle"),
            "bundle_sha256": digest, "source_sha256": manifest["binding_source_sha256"],
            "qualification_id": manifest["qualification_id"], "source_revision": expected_revision}, "Python request binding")
        adapter = members["vortex_ai/torch_ops.py"]
        expected_base = copy.deepcopy(python_request)
        expected_base["expected_prefix"] = str(prefix)
        expected_base["binding"]["bundle_root"] = str(api.recorded_absolute(tr["paths"]["output"]) / "artifacts/bundle")
        request = _snapshot(torch, tr, "installed_request")
        _same(request, {"schema_version": 1, "contract_id": "p05-torch-request-v1", "base_request": expected_base,
                       "framework": {"version": "2.15.0+cpu", "contract_sha256": CONTRACT_SHA256,
                                     "adapter_sha256": hashlib.sha256(adapter).hexdigest()}}, "framework installed request")
        observations = torch.document(tr["observations"], "artifacts/installed-observations.json", integers_only=True)
        framework = observations["framework"]
        _same(framework["adapter_file"], str(prefix / SITE / "vortex_ai/torch_ops.py"), "observed adapter path")
        _same({key: framework[key] for key in ("version", "contract_sha256", "adapter_sha256")}, request["framework"],
              "observed framework identity")
        _same(framework["distribution_version"], "2.15.0+cpu", "observed framework distribution version")
        provisioning = tr["provisioning_interpreter"]
        identity = _interpreter(provisioning, api, "provisioning interpreter")
        tools = _snapshot(python, pr, "tools_before")
        _same(_snapshot(python, pr, "tools_after"), tools, "Python tool stability")
        _same(provisioning, tools["python3"], "original provisioning interpreter")
        for report, root in ((pr, python_prefix), (tr, prefix)):
            interpreter = report["venv_interpreter"]
            _same(_interpreter(interpreter, api, "copied venv interpreter"), identity, "copied interpreter bytes")
            _same(interpreter["path"], str(root / "bin/python"), "copied interpreter path")
            _same(interpreter["resolved_path"], interpreter["path"], "copied interpreter canonical path")
        _same(seed["bin/python"], {"path": "bin/python", "sha256": identity[0], "size_bytes": identity[1]},
              "seed/interpreter identity")
        api.descriptor(tr["venv_configuration"])
        _require(tr["venv_configuration"]["path"] == "pyvenv.cfg"
                 and 0 < tr["venv_configuration"]["size_bytes"] <= MIB, "invalid venv configuration receipt")
        base_prefix = python_observations["installation"]["base_prefix"]
        api.recorded_absolute(base_prefix)
        _require(base_prefix not in (str(prefix), str(python_prefix)), "recorded installation did not use separate venvs")
        for observation, base in ((python_observations, python_request), (observations["base_observations"], expected_base)):
            _observed_installation(observation, base, manifest, EXTENSION, base_prefix, api)
        environment = _environments(torch, tr, installed, seed, versions, prefix, base_prefix, api)
        _package_tools(python, pr, provisioning,
                       (*tools.values(), pr["venv_interpreter"], tr["venv_interpreter"]), api)
        helpers = _snapshot(torch, tr, "installed_helpers")
        _inventory(helpers, api, "installed helpers", ordered=False, per_file=api.MEMBER_BYTES)
        _same([row["path"] for row in helpers], list(HELPERS), "installed helper membership/order")
        _same(torch.subview("artifacts/checker").inventory(), sorted(helpers, key=lambda row: row["path"]), "retained checker bytes")
        for row in helpers:
            _same(torch.identity("artifacts/source/ci/project/" + row["path"]),
                  {**row, "path": "artifacts/source/ci/project/" + row["path"]}, "checker/source identity")
        _same(pr["installed_script"], next(row for row in helpers if row["path"] == "p05_installed_check.py"),
              "Python/framework checker identity")
        python_files = [(str(python_prefix / SITE / name), row["sha256"], row["size_bytes"]) for name, row in plain.items()]
        python_files.append((str(python_prefix / "bin/python"), *identity))
        torch_files = [(str(prefix / name), row["sha256"], row["size_bytes"]) for name, row in installed.items()]
        return {
            "python_identity": RetainedIdentity(hashlib.sha256(_canonical(python_request)).hexdigest(), tuple(sorted(python_files))),
            "torch_identity": RetainedIdentity(hashlib.sha256(_canonical(expected_base)).hexdigest(), tuple(sorted(torch_files))),
            "adapter_bytes": adapter,
            "summary": {"scope": "retained-installation-consistency", "bundle_sha256": digest,
                "binding_source_sha256": manifest["binding_source_sha256"], "bound_wheel_members": len(wheel_rows),
                "retained_plain_installed_files": len(plain), "framework_payload_receipts": len(payload),
                "framework_installed_receipts": len(installed), "framework_seed_receipts": len(seed),
                "framework_distribution_receipts": len(environment["distributions"]),
                "third_party_wheel_receipts": len(contract["wheels"]), "third_party_bytes_rehashed": False,
                "interpreter_bytes_rehashed": False, "venv_configuration_bytes_retained": False,
                "native_execution": "not_run", "retained_code_executed": False, "acceptance_claimed": False,
                "phase_acceptance": False, "limitations": list(LIMITATIONS)},
        }
    except (KeyError, TypeError, UnicodeError, OverflowError, OSError, RuntimeError, zipfile.BadZipFile,
            tarfile.TarError, EOFError, csv.Error, struct.error, zlib.error) as error:
        raise InstallationError("malformed retained installation data: " + str(error)) from error
