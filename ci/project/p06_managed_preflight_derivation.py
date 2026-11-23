# SPDX-License-Identifier: Apache-2.0
"""Bind retained source bodies to a separately pinned Git-export receipt."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath

from baseline_packet_io import PacketReader, load_json_bytes
import p06_managed_preflight_sources as inventory


CONTRACT_ID = "p06-managed-counter-preflight-source-export-v1"
REPLAY_CONTRACT_ID = "p06-managed-counter-preflight-source-derivation-replay-v1"
MAX_RECEIPT_BYTES = 16 * 1024**2
MAX_GIT_BYTES = 64 * 1024**2
MAX_BLOB_BYTES = 16 * 1024**2
MAX_GIT_COMMANDS = 25000
FALSE_CLAIMS = ("qualified", "ready_for_warm", "warm_execution", "full_warm_coverage",
                "acceptance_claimed", "phase_acceptance", "performance_acceptance")
RECEIPT_FIELDS = {
    "schema_version", "contract_id", "source_revision", "source_files", "source_names_sha256",
    "manifest_sha256", "discovery_helper_sha256", "repositories", "sources", "git_commands",
    "git_bytes_read", "native_execution", "retained_code_executed",
    "dependency_compilation_provenance_verified", "limitations", *FALSE_CLAIMS,
}
SOURCE_FIELDS = inventory.DESCRIPTOR_FIELDS | {"repository", "repository_path", "git_blob", "git_mode"}
DEPENDENCIES = {
    "ramulator": ("third_party/ramulator", "https://github.com/CMU-SAFARI/ramulator2.git"),
    "softfloat": ("third_party/softfloat", "https://github.com/ucb-bar/berkeley-softfloat-3.git"),
}
FETCH_INPUTS = {
    "spdlog": ("https://github.com/gabime/spdlog.git", "v1.11.0"),
    "yaml-cpp": ("https://github.com/jbeder/yaml-cpp.git", "yaml-cpp-0.7.0"),
}
SOURCE_PREFIXES = (
    ("spdlog", "third_party/ramulator/ext/spdlog/", ("include",)),
    ("yaml-cpp", "third_party/ramulator/ext/yaml-cpp/", ("include",)),
    ("ramulator", "third_party/ramulator/", ("src",)),
    ("softfloat", "third_party/softfloat/", ("source/include", "source/RISCV")),
)
DISCOVERY_HELPER_SHA256 = frozenset((
    "24f1eb40dac4469c64379d6afcd0a8271518218e3ca10f445c4335ebc5f0502c",
    "3d58674992289643ac35aee2ec0c4ecd69969a24a8d3ab36029807703aa064c2",
))
EXPORT_LIMITATIONS = [
    "The explicitly supplied full commits select expected Git content; remote origin is not authenticated.",
    "The reviewed discovery recipe is fixed; changed producer/helper bytes require an independently reviewed update.",
    "CMake tag text is checked, but caller-supplied full commits select FetchContent bytes; remote tag resolution is not authenticated.",
    "Only selected source/header inputs are inventoried; this is not a complete dependency compilation closure.",
    "Git object membership and source hashes do not prove source-to-binary compilation, loaded bytes or native execution.",
    "Local repositories are caller-selected inputs; hashes do not defend against malicious concurrent object-store mutation.",
]


class SourceDerivationError(ValueError):
    pass


def _require(condition, message):
    if not condition:
        raise SourceDerivationError(message)


def _same(actual, expected, label):
    _require(type(actual) is type(expected), label + ": value type differs")
    if type(expected) is dict:
        _fields(actual, expected, label)
        for name, value in expected.items():
            _same(actual[name], value, label + "." + name)
    elif type(expected) is list:
        _require(len(actual) == len(expected), label + ": inventory length differs")
        for index, value in enumerate(expected):
            _same(actual[index], value, label + "[" + str(index) + "]")
    else:
        _require(actual == expected, label + ": value differs")


def _fields(value, expected, label):
    _require(type(value) is dict and set(value) == set(expected), label + ": fields differ")


def _integer(value, low, high, label):
    _require(type(value) is int and low <= value <= high, label + ": integer is outside its bound")


def _digest(value, pattern, label):
    _require(type(value) is str and pattern.fullmatch(value), label + ": invalid digest")


def _expectations(expected_sha256, expected_revision, source_inventory_sha256):
    _digest(expected_sha256, inventory.SHA256, "external source derivation")
    _digest(expected_revision, inventory.REVISION, "external source revision")
    _digest(source_inventory_sha256, inventory.SHA256, "external source inventory")


def _path(value):
    try:
        return inventory._source_path(value)
    except ValueError as error:
        raise SourceDerivationError(str(error)) from error


def _json_bytes(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def _source_mapping(name):
    for repository, prefix, roots in SOURCE_PREFIXES:
        if name.startswith(prefix):
            relative = _path(name[len(prefix):])
            _require(any(relative.startswith(root + "/") for root in roots)
                     and PurePosixPath(relative).suffix in (".h", ".hpp", ".inc", ".tpp"),
                     "derivation source is outside the reviewed dependency header roots")
            return repository, relative
    return "source", name


def validate_source_derivation(document, *, expected_revision, source_inventory, source_inventory_sha256):
    """Validate a trusted receipt; the caller must establish its external digest."""
    _digest(expected_revision, inventory.REVISION, "external source revision")
    _digest(source_inventory_sha256, inventory.SHA256, "external source inventory")
    try:
        manifest = inventory.validate_source_inventory(source_inventory, expected_revision=expected_revision)
    except ValueError as error:
        raise SourceDerivationError(str(error)) from error
    _fields(document, RECEIPT_FIELDS, "source derivation")
    for name, expected in (
        ("schema_version", 1), ("contract_id", CONTRACT_ID), ("source_revision", expected_revision),
        ("manifest_sha256", source_inventory_sha256), ("source_files", len(manifest["sources"])),
        ("native_execution", "not_run"), ("retained_code_executed", False),
        ("dependency_compilation_provenance_verified", False), ("limitations", EXPORT_LIMITATIONS),
        *((name, False) for name in FALSE_CLAIMS),
    ):
        _same(document[name], expected, "source derivation " + name)
    names = "".join(row["path"] + "\n" for row in manifest["sources"]).encode("ascii")
    _same(document["source_names_sha256"], hashlib.sha256(names).hexdigest(), "derived source names")
    selected = {row["path"]: row for row in manifest["sources"]}
    helpers = [selected[name] for name in inventory.required_source_names()
               if name.startswith("ci/project/") and name.endswith(".py")]
    helper_sha = hashlib.sha256(_json_bytes(helpers)).hexdigest()
    _require(helper_sha in DISCOVERY_HELPER_SHA256, "derivation discovery helpers are not reviewed")
    _same(document["discovery_helper_sha256"], helper_sha, "derived discovery helpers")

    repositories = document["repositories"]
    _fields(repositories, ("source", *DEPENDENCIES, *FETCH_INPUTS), "derivation repositories")
    for name, row in repositories.items():
        expected = {"commit": row.get("commit"), "tree": row.get("tree")} if type(row) is dict else {}
        if name == "source":
            expected.update(commit=expected_revision, selection="caller-supplied-full-producer-commit")
        elif name in DEPENDENCIES:
            path, url = DEPENDENCIES[name]
            expected.update(selection="producer-gitlink", producer_path=path, url=url)
        else:
            url, tag = FETCH_INPUTS[name]
            expected.update(selection="caller-supplied-full-FetchContent-commit", url=url, declared_tag=tag)
        _same(row, expected, "derivation repository " + name)
        for field in ("commit", "tree"):
            _digest(row[field], inventory.REVISION, "derivation repository " + name + " " + field)

    rows = document["sources"]
    _require(type(rows) is list and len(rows) == len(manifest["sources"]), "derivation source count differs")
    counts = dict.fromkeys(repositories, 0)
    for row, descriptor in zip(rows, manifest["sources"]):
        _fields(row, SOURCE_FIELDS, "derived source")
        _same({key: row[key] for key in inventory.DESCRIPTOR_FIELDS}, descriptor, "derived source descriptor")
        repository, relative = _source_mapping(descriptor["path"])
        _same(row["repository"], repository, "derived source repository")
        _same(row["repository_path"], relative, "derived source repository path")
        _require(type(row["git_mode"]) is str and row["git_mode"] in ("100644", "100755"),
                 "derived source Git mode is not a regular blob")
        _digest(row["git_blob"], inventory.REVISION, "derived source Git blob")
        _integer(row["size_bytes"], 0, MAX_BLOB_BYTES, "derived source bytes")
        counts[repository] += 1
    _require(all(counts.values()), "derivation omits a selected repository")
    _integer(document["git_commands"], 4 * len(repositories) + 2 * len(rows), MAX_GIT_COMMANDS,
             "derivation Git commands")
    _integer(document["git_bytes_read"], sum(row["size_bytes"] for row in rows), MAX_GIT_BYTES,
             "derivation Git bytes")
    return json.loads(_json_bytes(document))


def decode_source_derivation(contents, *, expected_sha256, expected_revision,
                             source_inventory, source_inventory_sha256):
    """Verify the caller's exact-byte digest before parsing bounded inert JSON."""
    _expectations(expected_sha256, expected_revision, source_inventory_sha256)
    _require(type(contents) is bytes and 0 < len(contents) <= MAX_RECEIPT_BYTES,
             "source derivation bytes are absent or exceed the limit")
    _same(hashlib.sha256(contents).hexdigest(), expected_sha256, "source derivation external digest")
    try:
        document = load_json_bytes(contents, "managed preflight source derivation")
    except ValueError as error:
        raise SourceDerivationError(str(error)) from error
    return validate_source_derivation(document, expected_revision=expected_revision,
        source_inventory=source_inventory, source_inventory_sha256=source_inventory_sha256)


def load_source_derivation(path, *, expected_sha256, expected_revision,
                           source_inventory, source_inventory_sha256):
    """Open only the explicit receipt, refusing links, nonregular files and races."""
    _expectations(expected_sha256, expected_revision, source_inventory_sha256)
    try:
        selected = Path(path)
        _require(".." not in selected.parts, "source derivation path contains parent traversal")
        with PacketReader(selected.parent, max_total_bytes=MAX_RECEIPT_BYTES, max_files=1) as reader:
            contents = reader.read_bytes(selected.name, limit=MAX_RECEIPT_BYTES)
            reader.recheck()
    except (OSError, TypeError, ValueError) as error:
        raise SourceDerivationError("source derivation cannot be read safely: " + str(error)) from error
    return decode_source_derivation(contents, expected_sha256=expected_sha256,
        expected_revision=expected_revision, source_inventory=source_inventory,
        source_inventory_sha256=source_inventory_sha256)


def validate_retained_derivation(receipt, *, checkout, source_body):
    """Bind a validated external receipt to checkout metadata and inert source bytes."""
    _require(type(checkout) is dict, "retained checkout is not an object")
    _same(checkout.get("revision"), receipt["source_revision"], "derived checkout revision")
    _same(checkout.get("tree"), receipt["repositories"]["source"]["tree"], "derived checkout tree")
    submodules = checkout.get("submodules")
    _fields(submodules, ("declared_count", "entries", "errors"), "derived checkout submodules")
    rows = submodules["entries"]
    _require(type(rows) is list and 0 < len(rows) <= 1000, "derived submodule inventory is invalid")
    _integer(submodules["declared_count"], 1, len(rows), "derived declared submodule count")
    _same(submodules["errors"], [], "derived submodule errors")
    entries = {}
    for row in rows:
        _fields(row, ("path", "revision", "status"), "derived submodule")
        name = _path(row["path"])
        _require(name not in entries, "derived submodule path is repeated")
        _digest(row["revision"], inventory.REVISION, "derived submodule revision")
        _same(row["status"], "initialized", "derived submodule state")
        entries[name] = row
    _same(list(entries), sorted(entries), "derived submodule order")
    for name, (path, _) in DEPENDENCIES.items():
        _require(path in entries, "derived dependency Gitlink is absent: " + name)
        _same(entries[path]["revision"], receipt["repositories"][name]["commit"],
              "derived dependency Gitlink " + name)
    counts = dict.fromkeys(receipt["repositories"], 0)
    for row in receipt["sources"]:
        body = source_body(_path(row["path"]))
        _require(type(body) is bytes and len(body) == row["size_bytes"], "derived retained source size differs")
        _same(hashlib.sha256(body).hexdigest(), row["sha256"], "derived retained source SHA-256")
        blob = b"blob " + str(len(body)).encode("ascii") + b"\0" + body
        _same(hashlib.sha1(blob).hexdigest(), row["git_blob"], "derived retained Git blob")
        counts[row["repository"]] += 1
    return {
        "contract_id": REPLAY_CONTRACT_ID, "validation": "pass",
        "source_revision": receipt["source_revision"], "source_tree": receipt["repositories"]["source"]["tree"],
        "manifest_sha256": receipt["manifest_sha256"], "source_files_checked": sum(counts.values()),
        "repository_source_counts": counts,
        "dependency_commits": {name: receipt["repositories"][name]["commit"] for name in DEPENDENCIES},
        "remote_origin_authenticated": False, "git_object_membership_revalidated": False,
        "dependency_compilation_provenance_verified": False,
        "retained_code_executed": False, "native_execution": "not_run",
        **dict.fromkeys(FALSE_CLAIMS, False),
    }
