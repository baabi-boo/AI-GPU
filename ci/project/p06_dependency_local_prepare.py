#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Prepare fresh dependencies from explicit local Git objects and locked archives."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import tarfile

sys.dont_write_bytecode = True

from baseline_inventory import SOURCE_INPUTS, _git, collect_source
import p02_matrix as base
import p06_dependency_contract as contract
import p06_dependency_sources as sources
import p06_local_toolchain as toolchain
from preflight import PIN_NAMES, available_memory_bytes


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_ID = "p06-local-dependency-preparation-v1"
HOST_TOOLS = ("gcc", "g++", "ar", "ranlib", "cmake", "make", "python3")
LIMITATIONS = [
    "This is an explicitly local preparation, not a GitHub job or restored toolchain cache.",
    "Pinned local Git object bytes do not authenticate a remote repository or historical acquisition.",
    "Preparation observes archives and installed tools; inert receipt validation does not rehash their producer paths.",
    "Dependency compilation, native execution, loaded-library provenance and all qualification claims require their separate evidence.",
    "Before and after observations do not protect against malicious concurrent filesystem writers.",
]
LOCAL_FIELDS = {
    "schema_version", "contract_id", "execution_origin", "dependency_contract_sha256",
    "expected_revision", "outcome", "reason", "failures", "source_dir", "workspace_dir",
    "archive_root", "dependency_repositories_root", "tools_dir", "host_bin", "host_tools",
    "repositories", "source_manifest", "toolchain_receipt", "source_before", "source_after",
    "resources_before", "resources_after", "dependency_cache_used", "toolchain_cache_used",
    "network_acquisition", "native_execution", "budget", "limitations", *contract.FALSE_CLAIMS,
}
_CHECKOUT_FIELDS = {"revision", "tree", "dirty", "changed_paths", "untracked_paths", "submodules",
                    "pins", "blockers", "inputs", "outcome"}
_IDENTITY_FIELDS = {"path", "resolved_path", "sha256", "size_bytes"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def _literal_path(value):
    require(type(value) is str and 0 < len(value) <= 4096
            and re.fullmatch(r"/[A-Za-z0-9_./+\-]+", value)
            and str(PurePosixPath(value)) == value
            and all(part not in (".", "..") for part in value.split("/")),
            "local preparation path is not a canonical absolute literal")
    return PurePosixPath(value)


def _identity(value):
    require(type(value) is dict and set(value) == _IDENTITY_FIELDS,
            "local host tool identity fields differ")
    _literal_path(value["path"])
    _literal_path(value["resolved_path"])
    require(type(value["sha256"]) is str and re.fullmatch(r"[0-9a-f]{64}", value["sha256"])
            and type(value["size_bytes"]) is int and 0 < value["size_bytes"] <= contract.MAX_FILE_BYTES,
            "local host tool identity is malformed or oversized")


def _resource_record(value):
    require(type(value) is dict and set(value) == {"free_disk_bytes", "available_memory_bytes"}
            and type(value["free_disk_bytes"]) is dict
            and set(value["free_disk_bytes"]) == {"source", "workspace"},
            "local preparation resource fields differ")
    require(all(type(number) is int and contract.BUDGET["min_free_bytes"] <= number < 2**64
                for number in value["free_disk_bytes"].values()),
            "local preparation requires the 15 GiB disk reserve")
    require(type(value["available_memory_bytes"]) is int
            and contract.BUDGET["max_rss_bytes"] <= value["available_memory_bytes"] < 2**64,
            "local preparation requires 4 GiB available RAM")


def _checkout_record(value, revision):
    require(type(value) is dict and set(value) == _CHECKOUT_FIELDS,
            "local preparation checkout fields differ")
    require(value["revision"] == revision and type(value["tree"]) is str
            and re.fullmatch(r"[0-9a-f]{40}", value["tree"])
            and value["dirty"] is False and value["changed_paths"] == []
            and value["untracked_paths"] == [] and value["blockers"] == []
            and value["outcome"] == "pass", "local preparation source was not clean and exact")
    pins = value["pins"]
    require(type(pins) is dict and set(pins) == set(PIN_NAMES)
            and all(type(pin) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+\-]*", pin)
                    for pin in pins.values()), "local preparation source pins differ")
    submodules = value["submodules"]
    require(type(submodules) is dict and set(submodules) == {"entries", "declared_count", "errors"}
            and submodules["errors"] == [] and type(submodules["declared_count"]) is int
            and 0 < submodules["declared_count"] <= 128
            and type(submodules["entries"]) is list and 0 < len(submodules["entries"]) <= 128,
            "local preparation submodule inventory differs")
    observed = {}
    for row in submodules["entries"]:
        require(type(row) is dict and set(row) == {"path", "revision", "status"}
                and row["status"] == "initialized" and type(row["path"]) is str
                and re.fullmatch(r"[A-Za-z0-9_.+\-]+(?:/[A-Za-z0-9_.+\-]+)*", row["path"])
                and all(part not in (".", "..", ".git") for part in row["path"].split("/"))
                and row["path"] not in observed and type(row["revision"]) is str
                and re.fullmatch(r"[0-9a-f]{40}", row["revision"]),
                "local preparation has an absent, duplicate or uninitialized gitlink")
        observed[row["path"]] = row["revision"]
    require(len(observed) >= submodules["declared_count"], "local preparation omits declared gitlinks")
    for name in ("softfloat", "ramulator"):
        pin = contract.PINS[name]
        require(observed.get(pin["path"]) == pin["revision"],
                "local preparation dependency gitlink differs from its lock")
    inputs = value["inputs"]
    require(type(inputs) is list and [row.get("path") for row in inputs if type(row) is dict]
            == list(SOURCE_INPUTS), "local preparation checkout input inventory differs")
    for row in inputs:
        require(type(row) is dict and set(row) == {"path", "sha256", "size_bytes"}
                and type(row["sha256"]) is str and re.fullmatch(r"[0-9a-f]{64}", row["sha256"])
                and type(row["size_bytes"]) is int and 0 < row["size_bytes"] <= contract.MAX_FILE_BYTES,
                "local preparation checkout input identity differs")


def validate_local_preparation(document, expected_revision):
    """Check a successful local preparation as inert data without producer-path reads."""
    require(type(expected_revision) is str and re.fullmatch(r"[0-9a-f]{40}", expected_revision),
            "local preparation requires an exact source revision")
    require(type(document) is dict and set(document) == LOCAL_FIELDS,
            "local preparation fields differ")
    require(type(document["schema_version"]) is int and document["schema_version"] == 1
            and document["contract_id"] == CONTRACT_ID and document["execution_origin"] == "local"
            and document["dependency_contract_sha256"] == contract.contract_hash()
            and document["expected_revision"] == expected_revision
            and document["outcome"] == "pass" and document["reason"] is None
            and document["failures"] == [], "local preparation was not a matching complete success")
    require(document["dependency_cache_used"] is False and document["toolchain_cache_used"] is False
            and document["network_acquisition"] is False and document["native_execution"] == "not_run"
            and all(document[name] is False for name in contract.FALSE_CLAIMS),
            "local preparation changes its acquisition or execution scope")
    require(type(document["budget"]) is dict and document["budget"] == contract.BUDGET
            and all(type(number) is int for number in document["budget"].values())
            and document["limitations"] == LIMITATIONS, "local preparation budget or limitations differ")
    roots = {name: _literal_path(document[name]) for name in
             ("source_dir", "workspace_dir", "archive_root", "dependency_repositories_root", "tools_dir")}
    require(roots["tools_dir"] == roots["workspace_dir"] / "tools",
            "local preparation tools are outside the owned workspace")
    independent = [roots[name] for name in
                   ("source_dir", "workspace_dir", "archive_root", "dependency_repositories_root")]
    require(all(not base._overlap(left, right) for index, left in enumerate(independent)
                for right in independent[index + 1:]), "local preparation input and output roots overlap")
    host_bin = document["host_bin"]
    if host_bin is not None:
        _literal_path(host_bin)
    require(type(document["host_tools"]) is dict and set(document["host_tools"]) == set(HOST_TOOLS),
            "local preparation host tool inventory differs")
    for name, row in document["host_tools"].items():
        _identity(row)
        require(PurePosixPath(row["path"]).name == name, "local preparation host tool alias differs")
    python_parent = str(PurePosixPath(document["host_tools"]["python3"]["path"]).parent)
    selected_path = ([host_bin] if host_bin is not None else []) + [python_parent, "/usr/bin", "/bin"]
    require(all(str(PurePosixPath(row["path"]).parent) in selected_path
                for row in document["host_tools"].values()), "local preparation host tool is outside its selected PATH")
    repositories = document["repositories"]
    require(type(repositories) is dict and set(repositories) == set(contract.PINS),
            "local preparation dependency repository inventory differs")
    for name in contract.PINS:
        expected = (roots["source_dir"] / contract.PINS[name]["path"] if name in ("softfloat", "ramulator")
                    else roots["dependency_repositories_root"] / name)
        require(_literal_path(repositories[name]) == expected, "local preparation repository path differs")
    sources.validate_manifest(document["source_manifest"])
    _checkout_record(document["source_before"], expected_revision)
    _checkout_record(document["source_after"], expected_revision)
    require(document["source_before"] == document["source_after"],
            "source changed during local preparation")
    _resource_record(document["resources_before"])
    _resource_record(document["resources_after"])
    toolchain.validate_receipt(document["toolchain_receipt"])
    require(document["toolchain_receipt"]["tools_root"] == document["tools_dir"]
            and document["toolchain_receipt"]["archive_root"] == document["archive_root"]
            and document["toolchain_receipt"]["tag"] == document["source_before"]["pins"]["TOOLCHAIN_REV"],
            "local preparation toolchain paths or version differ")
    return document


def _source_inventory(repositories):
    budget = {"commands": 0, "bytes": 0}
    manifest = {"schema_version": 1, "contract_id": sources.CONTRACT_ID,
                "dependency_contract_sha256": contract.contract_hash(), "sources": [],
                "total_files": 0, "total_size_bytes": 0}
    for name in sorted(contract.PINS):
        pin = contract.PINS[name]
        reader = sources._DependencyGitObjects(Path(repositories[name]), pin["revision"], budget=budget)
        require(reader.tree_id == pin["tree"], "local dependency root tree differs: " + name)
        row = {"name": name, **{key: pin[key] for key in ("url", "revision", "tree")}, "files": []}
        for relative, entry in sorted(reader.entries.items()):
            body = reader.blob(relative)
            row["files"].append({"path": relative, "mode": entry["mode"], "oid": entry["oid"],
                                 "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)})
            manifest["total_files"] += 1
            manifest["total_size_bytes"] += len(body)
        manifest["sources"].append(row)
    return sources.validate_manifest(manifest)


def _host_tools(host_bin):
    entries = ([str(host_bin)] if host_bin is not None else []) + [str(Path(sys.executable).parent), "/usr/bin", "/bin"]
    environment_path = os.pathsep.join(dict.fromkeys(entries))
    result = {}
    for name in HOST_TOOLS:
        path = shutil.which(name, path=environment_path)
        require(path is not None and os.access(path, os.X_OK), "required local host tool is absent: " + name)
        result[name] = base._file_identity(path)
    require(result["python3"] == base._file_identity(sys.executable),
            "local preparation Python differs from the executing interpreter")
    return result


def _resources(source, workspace):
    return {"free_disk_bytes": {"source": shutil.disk_usage(source).free,
                               "workspace": shutil.disk_usage(workspace).free},
            "available_memory_bytes": available_memory_bytes()}


def prepare(args):
    source = base._path(args.source_dir, existing=True)
    workspace = base._path(args.workspace_dir, existing=True)
    require(source == ROOT and source.is_dir() and workspace.is_dir()
            and not base._overlap(source, workspace),
            "use this checkout and a distinct owned preparation workspace")
    evidence = workspace / "evidence"
    evidence.mkdir(mode=0o700, exist_ok=True)
    require(evidence.resolve(strict=True) == evidence and not evidence.is_symlink(),
            "local preparation evidence must be canonical")
    target = evidence / "dependency-preparation.json"
    require(not os.path.lexists(target), "local preparation receipt already exists")
    report = {"schema_version": 1, "contract_id": CONTRACT_ID, "execution_origin": "local",
              "dependency_contract_sha256": contract.contract_hash(), "expected_revision": args.expected_revision,
              "outcome": "blocked", "reason": None, "failures": [], "source_dir": str(source),
              "workspace_dir": str(workspace), "archive_root": None, "dependency_repositories_root": None,
              "tools_dir": str(workspace / "tools"), "host_bin": None, "host_tools": {}, "repositories": {},
              "source_manifest": None, "toolchain_receipt": None, "source_before": None, "source_after": None,
              "resources_before": None, "resources_after": None, "dependency_cache_used": False,
              "toolchain_cache_used": False, "network_acquisition": False, "native_execution": "not_run",
              "budget": dict(contract.BUDGET), "limitations": list(LIMITATIONS),
              **dict.fromkeys(contract.FALSE_CLAIMS, False)}
    provisioning_started = False

    def save():
        base._write_json(target, report)

    save()
    try:
        require(type(args.expected_revision) is str and re.fullmatch(r"[0-9a-f]{40}", args.expected_revision),
                "exact source revision required")
        archives = base._path(args.archive_root, existing=True)
        repositories_root = base._path(args.dependency_repositories, existing=True)
        require(archives.is_dir() and repositories_root.is_dir(), "local input roots must be directories")
        roots = (source, workspace, archives, repositories_root)
        require(all(not base._overlap(left, right) for index, left in enumerate(roots)
                    for right in roots[index + 1:]), "local preparation input and output roots overlap")
        report["archive_root"], report["dependency_repositories_root"] = str(archives), str(repositories_root)
        host_bin = base._path(args.host_bin, existing=True) if getattr(args, "host_bin", None) else None
        require(host_bin is None or host_bin.is_dir(), "local host-bin must be a directory")
        report["host_bin"] = str(host_bin) if host_bin is not None else None
        report["source_before"] = collect_source(source)
        base._source_ok({"checkout": report["source_before"]}, False)
        require(report["source_before"]["revision"] == args.expected_revision,
                "local preparation source differs from the expected revision")
        report["resources_before"] = _resources(source, workspace)
        _resource_record(report["resources_before"])
        require(not os.path.lexists(workspace / "tools"), "local toolchain destination must be fresh")
        for name in ("softfloat", "ramulator"):
            pin = contract.PINS[name]
            expected = ("160000 commit " + pin["revision"] + "\t" + pin["path"] + "\0").encode()
            require(_git(source, "ls-tree", "-z", "HEAD", "--", pin["path"]) == expected,
                    "superproject dependency gitlink differs from the source lock")
            directory = base._path(source / pin["path"], existing=True)
            require(_git(directory, "rev-parse", "HEAD").decode().strip() == pin["revision"],
                    "initialized local dependency differs from its gitlink")
            require(not _git(directory, "status", "--porcelain=v1", "--untracked-files=all", "--ignored"),
                    "initialized local dependency contains changed, untracked or ignored inputs: " + name)
        for relative in contract.PRODUCTS.values():
            require(not os.path.lexists(source / relative), "pre-existing dependency product is not fresh: " + relative)
        for name in ("yaml-cpp", "spdlog", "argparse"):
            require(not os.path.lexists(source / contract.PINS[name]["path"]),
                    "pre-existing fetched dependency input is not fresh: " + name)
        report["repositories"] = {
            name: str(source / pin["path"] if name in ("softfloat", "ramulator")
                      else base._path(repositories_root / name, existing=True))
            for name, pin in contract.PINS.items()}
        report["source_manifest"] = _source_inventory(report["repositories"])
        report["host_tools"] = _host_tools(host_bin)
        save()
        provisioning_started = True
        report["toolchain_receipt"] = toolchain.provision(archives, workspace / "tools")
        save()
        require(_host_tools(host_bin) == report["host_tools"], "selected host tools changed during local preparation")
        require(_source_inventory(report["repositories"]) == report["source_manifest"],
                "pinned dependency source objects changed during local preparation")
        report["source_after"] = collect_source(source)
        require(report["source_before"] == report["source_after"], "source changed during local preparation")
        report["resources_after"] = _resources(source, workspace)
        _resource_record(report["resources_after"])
        report["outcome"] = "pass"
        validate_local_preparation(report, args.expected_revision)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, EOFError, tarfile.TarError, KeyboardInterrupt) as error:
        report["reason"] = str(error) or "interrupted"
        report["failures"].append({"stage": "local-preparation", "reason": report["reason"]})
        report["outcome"] = "fail" if provisioning_started else "blocked"
    finally:
        save()
    return report


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=ROOT)
    parser.add_argument("--workspace-dir", type=Path, required=True)
    parser.add_argument("--expected-revision", required=True)
    parser.add_argument("--archive-root", type=Path, required=True)
    parser.add_argument("--dependency-repositories", type=Path, required=True)
    parser.add_argument("--host-bin", type=Path)
    return parser


def main(argv=None):
    args = argument_parser().parse_args(argv)
    try:
        report = prepare(args)
        print(json.dumps({name: report[name] for name in
                         ("contract_id", "execution_origin", "outcome", "reason", "native_execution")}, sort_keys=True))
        return 0 if report["outcome"] == "pass" else 1
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({"outcome": "blocked", "execution_origin": "local", "reason": str(error)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    sys.exit(main())
