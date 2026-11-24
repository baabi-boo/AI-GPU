#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Read-only advisory observations for the explicitly selected qualified warm route."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import sys

sys.dont_write_bytecode = True

import baseline_inventory as inventory
import hwemu_source
import p02_matrix as base
import p06_counter_qualification_admission as historical
import p06_dependency_contract as dependency
import p06_dependency_local_prepare as preparation
import p06_dependency_sources as sources
import p06_local_toolchain as toolchain
import p06_managed_preflight_execute as managed
import p06_qualified_warm_admission as admission
import p06_qualified_warm_contract as qualification
import preflight


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_ID = "p06-qualified-warm-readiness-v1"
PATH_ARGUMENTS = ("source_dir", "workspace_dir", "archive_root", "dependency_repositories",
                  "host_bin", "diagnostic_archive", "control_archive")
STAGE_DESTINATIONS = ("tools", "dependency-sources", "dependency-build", "work",
                      "evidence/dependency-preparation.json", "evidence/dependency-build",
                      "evidence/qualified-warm")
NATIVE_HOST_ALIASES = ("as", "ld", "bash", "perl")
PYTHON_RUNTIME = {"version": [3, 12, 14], "implementation": "CPython", "platform": "linux"}
OUTSIDE_SCREEN = (
    "full_historical_replay", "tool_extraction", "dependency_compilation",
    "native_build_and_process_admission", "installed_native_tool_verification",
    "runtime_host_support", "governance_completion", "provider_transport",
)
LIMITATIONS = (
    "This advisory JSON is not a preparation receipt or an admission input and does not authorize execution.",
    "Existing validators are fail-fast within a check; independent checks continue, but every internal defect is not enumerated.",
    "The recursive source observer retains its original byte, entry, module and time bounds; an incomplete observation is not clean closure.",
    "Effective cgroup allocation and hidden ancestor constraints are unknown; host MemAvailable cannot establish effective memory capacity.",
    "Disk and memory snapshots reserve nothing; the disk reserve is not an upper bound on extraction, build, log or warm-run growth.",
    "The screen is not atomic and cannot defend against malicious concurrent writers; execution stages must revalidate their own inputs.",
    "Host executable identities and versions do not verify compiler support files, C++ headers, shared runtimes or a successful build.",
    "Archive raw identities do not establish member safety, historical replay, acquisition authentication or installed-tool identities.",
)


def _reason(value):
    return " ".join(str(value).split())[:512]


class _Checks:
    def __init__(self):
        self.rows = []

    def add(self, identifier, status, observed=None, expected=None, reason=""):
        self.rows.append({"id": identifier, "status": status, "observed": deepcopy(observed),
                          "expected": deepcopy(expected), "reason": _reason(reason)})

    def skip(self, identifier, reason, expected=None):
        self.add(identifier, "not_checked", expected=expected, reason=reason)

    def ok(self, identifier):
        return any(row["id"] == identifier and row["status"] == "observed" for row in self.rows)

    def run(self, identifier, operation, *, expected=None, accept=None,
            reason="observation matches the selected requirement", summary=None,
            failure_status="blocked"):
        try:
            value = operation()
            passed = accept is None or accept(value)
            self.add(identifier, "observed" if passed else "blocked",
                     summary(value) if summary else value, expected, reason)
            return value
        except Exception as error:
            self.add(identifier, failure_status, expected=expected,
                     reason=type(error).__name__ + ": " + str(error))
            return None


def _root(value, *, planned=False):
    literal = os.fspath(value)
    qualification.require(Path(literal).is_absolute() and str(Path(literal)) == literal
                          and ".." not in Path(literal).parts,
                          "input must be a canonical absolute path")
    path = base._path(literal, existing=not planned)
    qualification.require(all(not part.is_symlink() for part in (path, *path.parents)),
                          "input must not traverse a symlink")
    qualification.require(path.is_dir() if os.path.lexists(path) else planned and path.parent.is_dir(),
                          "input directory or planned workspace parent is absent")
    return path


def _inspect_paths(inputs, checks):
    roots = {}
    for name in PATH_ARGUMENTS[:-2]:
        identifier = "paths." + name
        value = checks.run(identifier, lambda name=name: _root(inputs[name], planned=name == "workspace_dir"),
            expected=str(ROOT) if name == "source_dir" else "canonical directory",
            accept=lambda value, name=name: name != "source_dir" or value == ROOT,
            reason="source must be this trusted checkout; other roots must be canonical directories",
            summary=str)
        if checks.ok(identifier):
            roots[name] = value
    names = ("source_dir", "workspace_dir", "archive_root", "dependency_repositories")
    for index, left in enumerate(names):
        for right in names[index + 1:]:
            identifier = "paths.disjoint:" + left + ":" + right
            if left not in roots or right not in roots:
                checks.skip(identifier, "a selected root could not be validated")
            else:
                checks.run(identifier, lambda: not base._overlap(roots[left], roots[right]),
                           expected=True, accept=lambda value: value, reason="selected roots must be disjoint")
    workspace = roots.get("workspace_dir")
    if workspace is None:
        checks.skip("workspace.state", "workspace path could not be validated")
    else:
        checks.add("workspace.state", "observed", {
            "path": str(workspace), "state": "existing" if workspace.is_dir() else "planned",
            "observed_at": str(workspace if workspace.is_dir() else workspace.parent)},
            "existing directory or absent destination under an existing parent",
            "workspace creation is a separate runbook action")
    for relative in STAGE_DESTINATIONS:
        _absent(checks, "workspace.absent:" + relative, workspace, relative)
    for name, relative in dependency.PRODUCTS.items():
        _absent(checks, "source.product_absent:" + name, roots.get("source_dir"), relative)
    for name in ("yaml-cpp", "spdlog", "argparse"):
        _absent(checks, "source.fetched_absent:" + name, roots.get("source_dir"), dependency.PINS[name]["path"])
    return roots


def _absent(checks, identifier, root, relative):
    if root is None:
        checks.skip(identifier, "selected root could not be validated", expected="absent")
        return
    def observe():
        path = root / relative
        qualification.require(all(not parent.is_symlink() for parent in path.parents),
                              "destination ancestor is a symlink")
        qualification.require(all(not os.path.lexists(parent) or parent.is_dir() for parent in path.parents),
                              "destination ancestor is not a directory")
        return {"path": str(path), "exists": os.path.lexists(path)}
    checks.run(identifier, observe, expected="absent", accept=lambda value: not value["exists"],
               reason="stage destinations must be absent, including dangling aliases")


def _local_inputs(directory):
    directory = _root(directory)
    qualification.require(os.path.lexists(directory / ".git") and not (directory / ".git").is_symlink(),
                          "initialized dependency worktree is absent")
    git = shutil.which("git", path=os.defpath)
    qualification.require(git is not None, "system Git is unavailable")
    environment = {"PATH": os.defpath, "LANG": "C", "LC_ALL": "C", "GIT_OPTIONAL_LOCKS": "0",
        "GIT_NO_LAZY_FETCH": "1", "GIT_NO_REPLACE_OBJECTS": "1", "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
    command = [git, "--no-optional-locks", "-c", "core.fsmonitor=false", "-c",
               "core.untrackedCache=false", "-c", "protocol.allow=never", "-C", str(directory)]
    code, output = inventory._probe([*command, "rev-parse", "--show-toplevel"], environment=environment)
    qualification.require(code == 0 and output == (str(directory) + "\n").encode(),
                          "dependency Git worktree root differs from its selected path")
    counts = {}
    for name, extra in (("untracked", []), ("ignored", ["--ignored"])):
        code, output = inventory._probe([*command, "ls-files", "--others", "--exclude-standard", "-z", *extra],
                                       environment=environment)
        qualification.require(code == 0 and (not output or output.endswith(b"\0")),
                              "dependency worktree input observation failed")
        counts[name] = output.count(b"\0")
    return counts


def _inspect_source(inputs, roots, checks):
    source = roots.get("source_dir")
    snapshot = None
    if source is None:
        checks.skip("source.raw_recursive", "selected source is not the trusted checkout")
    else:
        snapshot = checks.run("source.raw_recursive", lambda: hwemu_source.collect_source(source),
            expected={"revision": inputs["expected_revision"], "dirty": False, "complete_recursive_closure": True},
            accept=lambda value: value["outcome"] == "pass" and value["dirty"] is False,
            reason="raw HEAD/index/worktree and recursive closure must be completely observed",
            summary=lambda value: {key: value[key] for key in ("revision", "tree", "dirty", "submodules", "blockers", "outcome")})
    if snapshot is None or snapshot.get("revision") is None:
        checks.skip("source.revision", "source revision could not be observed", inputs["expected_revision"])
    else:
        checks.run("source.revision", lambda: snapshot["revision"], expected=inputs["expected_revision"],
                   accept=lambda value: value == inputs["expected_revision"], reason="source revision must match the explicit selection")
    entries = {row["path"]: row for row in snapshot["submodules"]["entries"]} if snapshot else {}
    for name in ("softfloat", "ramulator"):
        pin = dependency.PINS[name]
        row = entries.get(pin["path"])
        identifier = "source.dependency_gitlink:" + name
        if not checks.ok("source.raw_recursive"):
            checks.skip(identifier, "complete raw recursive source observation is unavailable", pin["revision"])
        elif row is None:
            checks.skip(identifier, "gitlink observation is unavailable", pin["revision"])
        else:
            checks.run(identifier, lambda: row, expected={"revision": pin["revision"], "status": "initialized"},
                accept=lambda value: value["revision"] == pin["revision"] and value["status"] == "initialized",
                reason="initialized dependency gitlink must match the unchanged lock")
        identifier = "source.local_inputs:" + name
        if source is None:
            checks.skip(identifier, "trusted source is unavailable")
        else:
            checks.run(identifier, lambda: _local_inputs(source / pin["path"]),
                expected={"untracked": 0, "ignored": 0}, accept=lambda value: not any(value.values()),
                reason="dependency worktrees must contain no untracked or ignored inputs")


def _pinned_json(relative, digest, maximum):
    body = qualification.warm._read_file(ROOT / relative, maximum)
    qualification.require(hashlib.sha256(body).hexdigest() == digest, "frozen raw JSON identity differs")
    return qualification.historical._decode(body)


def _inspect_contracts(roots, checks):
    old = qualification.historical
    for identifier, relative, digest, size in (
        ("qualified_warm", qualification.SOURCE_PROOF_PATH, qualification.SOURCE_PROOF_SHA256, qualification.SOURCE_PROOF_BYTES),
        ("historical", old.SOURCE_PROOF_PATH, old.SOURCE_PROOF_SHA256, old.SOURCE_PROOF_BYTES),
        ("warm_manifest", qualification.warm.MANIFEST_PATH, qualification.WARM_CONTRACT_SHA256, None),
    ):
        expected = {"path": relative, "sha256": digest}
        if size is not None:
            expected["size_bytes"] = size
        checks.run("proof." + identifier + ".raw", lambda relative=relative: historical._relative_identity(ROOT, relative),
            expected=expected, accept=lambda value, expected=expected: all(value[key] == item for key, item in expected.items()),
            reason="raw input must match its unchanged frozen identity")
    checks.run("proof.qualified_warm.validation", lambda: qualification.load_proof(
        ROOT / qualification.SOURCE_PROOF_PATH, qualification.SOURCE_PROOF_SHA256), summary=lambda _: "validated")
    checks.run("proof.historical.validation", qualification.base_proof, summary=lambda _: "validated")
    checks.run("proof.warm_manifest.validation", lambda: qualification.warm.load_contract(ROOT), summary=lambda _: "validated")
    checks.run("proof.sampling", lambda: qualification.sampling_binding(ROOT), summary=lambda value: {
        "contract_sha256": value["contract_sha256"], "sampling": value["sampling"], "process_count": len(value["processes"])})
    proof = checks.run("proof.measurement_expectations", lambda: _pinned_json(
        qualification.SOURCE_PROOF_PATH, qualification.SOURCE_PROOF_SHA256, qualification.MAX_PROOF_BYTES),
        summary=lambda value: {"measurement_sources": len(value["measurement_sources"])})
    original = checks.run("proof.original_expectations", lambda: _pinned_json(
        old.SOURCE_PROOF_PATH, old.SOURCE_PROOF_SHA256, old.MAX_PROOF_BYTES), summary=lambda _: "frozen raw proof decoded")
    source = roots.get("source_dir")
    rows = []
    if proof is None:
        checks.skip("source.measurements", "frozen measurement expectations are unavailable")
    else:
        for expected in proof["measurement_sources"]:
            identifier = "source.measurement:" + expected["path"]
            if source is None:
                checks.skip(identifier, "trusted source selection is unavailable", expected)
            else:
                row = checks.run(identifier, lambda expected=expected: historical._relative_identity(source, expected["path"]),
                    expected=expected, accept=lambda value, expected=expected: value == expected,
                    reason="measurement bytes must match the frozen source extension")
                if row is not None:
                    rows.append(row)
    if proof is None or len(rows) != len(proof["measurement_sources"]):
        checks.skip("source.measurement_projection", "one or more measurement inputs could not be read")
    else:
        checks.run("source.measurement_projection", lambda: qualification.verify_source_projection(proof, rows))
    helpers = checks.run("source.helper_inventory", admission.reader_sources,
                         summary=lambda value: {"source_count": len(value)})
    prerequisites = None
    if proof is None:
        checks.skip("source.prerequisite_inventory", "validated raw proof is unavailable")
    else:
        prerequisites = checks.run("source.prerequisite_inventory", lambda: admission.prerequisite_input_rows(proof),
                                   summary=lambda value: {"source_count": len(value)})
    for kind, inputs in (("helper", helpers), ("prerequisite", prerequisites)):
        if inputs is None:
            checks.skip("source." + kind + "_inputs", "trusted expected input rows are unavailable")
            continue
        for expected in inputs:
            identifier = "source." + kind + ":" + expected["path"]
            if source is None:
                checks.skip(identifier, "trusted source selection is unavailable", expected)
            else:
                checks.run(identifier, lambda expected=expected: historical._relative_identity(source, expected["path"]),
                    expected=expected, accept=lambda value, expected=expected: value == expected,
                    reason="source/helper prerequisite identity must match its trusted observation")
    return original


def _inspect_originals(inputs, original_proof, checks):
    for name, section in (("diagnostic", "diagnostics"), ("control", "controls")):
        identifier = "originals." + name
        if original_proof is None:
            checks.skip(identifier, "frozen original archive expectations are unavailable")
            continue
        expected = {key: original_proof[section]["archive"][key] for key in ("sha256", "size_bytes")}
        checks.run(identifier, lambda name=name: historical._identity(inputs[name + "_archive"]),
            expected=expected, accept=lambda value: all(value[key] == item for key, item in expected.items()),
            reason="canonical single-link original archive must retain its raw identity; replay is not performed")


def _inspect_parts(roots, checks):
    manifest = checks.run("toolchain.lock", toolchain._locked_manifest,
                         summary=lambda value: {key: value[key] for key in ("sha256", "size_bytes", "revision", "tag")})
    if manifest is None:
        checks.skip("toolchain.selection", "trusted toolchain lock is unavailable")
        checks.skip("toolchain.parts", "trusted archive-part expectations are unavailable")
        return
    parts = checks.run("toolchain.selection", lambda: toolchain._selected_parts(manifest),
        summary=lambda value: {"parts": len(value), "size_bytes": sum(row["size_bytes"] for row in value),
                               "components": list(toolchain.COMPONENTS)})
    if parts is None:
        checks.skip("toolchain.parts", "trusted archive-part selection is unavailable")
        return
    for expected in parts:
        identifier = "toolchain.part:" + expected["path"]
        if "archive_root" not in roots:
            checks.skip(identifier, "archive root could not be validated", expected)
        else:
            def observe(expected=expected):
                toolchain._part(roots["archive_root"] / expected["path"], expected)
                return dict(expected)
            checks.run(identifier, observe, expected=expected,
                       reason="raw size, SHA-256 and Git blob identity match the immutable lock")


def _dependency_row(repository, name, budget):
    pin = dependency.PINS[name]
    reader = sources._DependencyGitObjects(repository, pin["revision"], budget=budget)
    qualification.require(reader.tree_id == pin["tree"], "dependency root tree differs: " + name)
    row = {"name": name, **{key: pin[key] for key in ("url", "revision", "tree")}, "files": []}
    for relative, entry in sorted(reader.entries.items()):
        body = reader.blob(relative)
        row["files"].append({"path": relative, "mode": entry["mode"], "oid": entry["oid"],
                             "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)})
    return row


def _inspect_dependencies(roots, checks):
    budget = {"commands": 0, "bytes": 0}
    manifest = {"schema_version": 1, "contract_id": sources.CONTRACT_ID,
        "dependency_contract_sha256": dependency.contract_hash(), "sources": [],
        "total_files": 0, "total_size_bytes": 0}
    for name, pin in sorted(dependency.PINS.items()):
        identifier = "dependency.repository:" + name
        root_name = "source_dir" if name in ("softfloat", "ramulator") else "dependency_repositories"
        root = roots.get(root_name)
        if root is None:
            checks.skip(identifier, "selected repository root could not be validated", pin)
            continue
        repository = root / (pin["path"] if root_name == "source_dir" else name)
        row = checks.run(identifier, lambda: _dependency_row(repository, name, budget), expected=pin,
            summary=lambda value: {"revision": value["revision"], "tree": value["tree"],
                "files": len(value["files"]), "size_bytes": sum(item["size_bytes"] for item in value["files"])})
        if row is not None:
            manifest["sources"].append(row)
            manifest["total_files"] += len(row["files"])
            manifest["total_size_bytes"] += sum(item["size_bytes"] for item in row["files"])
    if len(manifest["sources"]) != len(dependency.PINS):
        checks.skip("dependency.manifest", "complete objects from every pinned repository are required")
    else:
        checks.run("dependency.manifest", lambda: sources.validate_manifest(manifest),
            summary=lambda value: {key: value[key] for key in ("total_files", "total_size_bytes")})


def _tool_identity(path):
    status = Path(path).resolve(strict=True).stat()
    qualification.require(stat.S_ISREG(status.st_mode) and 0 < status.st_size <= dependency.MAX_FILE_BYTES
                          and os.access(path, os.X_OK), "host executable is absent, nonregular or oversized")
    return base._file_identity(path)


def _version_probe(identity, environment):
    code, body = inventory._probe([identity["path"], "--version"], environment=environment)
    qualification.require(code == 0, "selected executable --version failed in the sanitized environment")
    first = body.decode("utf-8").splitlines()[0] if body else ""
    prefix = {"python3": "Python", "cmake": "cmake version"}[Path(identity["path"]).name]
    match = re.fullmatch(prefix + r" ([0-9]+)\.([0-9]+)\.([0-9]+)", first)
    qualification.require(match is not None, "selected executable returned an unrecognized version")
    qualification.require(_tool_identity(identity["path"]) == identity, "selected executable changed during version observation")
    return {"version": [int(part) for part in match.groups()], "first_line": first}


def _inspect_host(roots, checks):
    runtime = {"version": list(sys.version_info[:3]), "implementation": platform.python_implementation(), "platform": sys.platform}
    checks.run("host.python_runtime", lambda: runtime, expected=PYTHON_RUNTIME,
               accept=lambda value: value == PYTHON_RUNTIME, reason="executing interpreter must be Linux CPython 3.12.14")
    executing = checks.run("host.executing_python", lambda: _tool_identity(sys.executable))
    host_bin = roots.get("host_bin")
    selected = {}
    environment = None
    if host_bin is not None:
        entries = [str(host_bin), str(Path(sys.executable).parent), "/usr/bin", "/bin"]
        environment = {"PATH": os.pathsep.join(dict.fromkeys(entries)), "LANG": "C", "LC_ALL": "C", "TZ": "UTC",
            "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1", "CCACHE_DISABLE": "1", "OBJCACHE": "",
            "MAKEFLAGS": "-j" + str(dependency.BUDGET["jobs"]),
            "CMAKE_BUILD_PARALLEL_LEVEL": str(dependency.BUDGET["jobs"]), "THREADS": "1"}
        if "workspace_dir" in roots:
            environment.update(HOME=str(roots["workspace_dir"] / "local-home"),
                               TMPDIR=str(roots["workspace_dir"] / "local-tmp"))
    for name in (*preparation.HOST_TOOLS, *NATIVE_HOST_ALIASES):
        identifier = "host.alias:" + name
        if environment is None:
            checks.skip(identifier, "host alias directory could not be validated")
            continue
        def observe(name=name):
            path = shutil.which(name, path=environment["PATH"])
            qualification.require(path is not None, "required host alias is absent: " + name)
            return _tool_identity(path)
        row = checks.run(identifier, observe)
        if row is not None:
            selected[name] = row
    if environment is None:
        checks.skip("host.preparation_selection", "host alias directory could not be validated")
    elif executing is None or any(name not in selected for name in preparation.HOST_TOOLS):
        checks.skip("host.preparation_selection", "bounded host executable identities are incomplete")
    else:
        checks.run("host.preparation_selection", lambda: preparation._host_tools(host_bin),
            accept=lambda value: value == {name: selected[name] for name in preparation.HOST_TOOLS},
            reason="preparation aliases must match the observations and exact executing-Python selection")
    if "python3" not in selected or executing is None:
        checks.skip("host.interpreter_binding", "observed Python aliases are incomplete")
    else:
        checks.run("host.interpreter_binding", lambda: managed.interpreter_identity(
            {"python3": selected["python3"], "executing_python": executing}), expected=PYTHON_RUNTIME)
    for name in ("python3", "cmake"):
        identifier = "host.version:" + name
        expected = [3, 12, 14] if name == "python3" else {"minimum": [3, 21, 0], "exclusive_maximum": [3, 26, 0]}
        if name not in selected or "workspace_dir" not in roots:
            checks.skip(identifier, "selected executable or workspace environment is unavailable", expected)
        else:
            checks.run(identifier, lambda: _version_probe(selected[name], environment), expected=expected,
                accept=lambda value: value["version"] == [3, 12, 14] if name == "python3"
                    else (3, 21, 0) <= tuple(value["version"]) < (3, 26, 0),
                reason="selected version must satisfy the fixed interpreter or CMake compatibility requirement")


def _inspect_resources(roots, checks):
    filesystems = {}
    for name in ("source", "workspace"):
        path = roots.get(name + "_dir")
        identifier = "resources.disk." + name
        if path is None:
            checks.skip(identifier, "selected filesystem path could not be validated", dependency.BUDGET["min_free_bytes"])
            continue
        def observe():
            qualification.require(name == "workspace" or path.is_dir(), "source directory is unavailable")
            observed_at = path if path.is_dir() else path.parent
            filesystem = observed_at.stat().st_dev
            free = shutil.disk_usage(observed_at).free
            qualification.require(type(free) is int and 0 <= free < 2**64, "free disk bytes are unavailable")
            shared = filesystems.setdefault(filesystem, name)
            return {"path": str(path), "observed_at": str(observed_at), "filesystem": filesystem,
                    "free_bytes": free, "reserve_margin_bytes": free - dependency.BUDGET["min_free_bytes"],
                    "shares_filesystem_with": shared if shared != name else None}
        checks.run(identifier, observe, expected=dependency.BUDGET["min_free_bytes"],
            accept=lambda value: value["reserve_margin_bytes"] >= 0, failure_status="unknown",
            reason="free bytes must retain the disk reserve; shared filesystems are not independent capacity")
    def memory():
        value = preflight.available_memory_bytes()
        qualification.require(type(value) is int and 0 <= value < 2**64, "host MemAvailable is unknown")
        return value
    checks.run("resources.host_memory", memory, expected=dependency.BUDGET["max_rss_bytes"],
        accept=lambda value: value >= dependency.BUDGET["max_rss_bytes"], failure_status="unknown",
        reason="host MemAvailable must meet the unchanged memory requirement")
    checks.add("resources.cgroup_capacity", "unknown", expected=dependency.BUDGET["max_rss_bytes"],
        reason="effective process cgroup allocation and visible/hidden ancestor margins are not established by an existing bounded observer")


def inspect_readiness(inputs):
    values = dict(inputs) if isinstance(inputs, Mapping) else vars(inputs)
    for name in PATH_ARGUMENTS:
        if name not in values or not isinstance(values[name], (str, os.PathLike)) or not os.fspath(values[name]):
            raise ValueError("required path argument is missing or invalid: " + name)
    revision = values.get("expected_revision")
    if type(revision) is not str or re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        raise ValueError("expected_revision must be an explicit 40-character lowercase Git commit")
    checks, roots, original = _Checks(), {}, None
    def category(name, operation):
        try:
            return operation()
        except Exception as error:
            checks.add("category." + name, "blocked", reason=type(error).__name__ + ": " + str(error))
            return None
    roots = category("paths", lambda: _inspect_paths(values, checks)) or {}
    category("source", lambda: _inspect_source(values, roots, checks))
    original = category("contracts", lambda: _inspect_contracts(roots, checks))
    category("originals", lambda: _inspect_originals(values, original, checks))
    category("parts", lambda: _inspect_parts(roots, checks))
    category("dependencies", lambda: _inspect_dependencies(roots, checks))
    category("host", lambda: _inspect_host(roots, checks))
    category("resources", lambda: _inspect_resources(roots, checks))
    blockers = [row["id"] for row in checks.rows if row["status"] == "blocked"]
    incomplete = [row["id"] for row in checks.rows if row["status"] in ("unknown", "not_checked")]
    outcome = "blocked" if blockers else "incomplete" if incomplete else "no_blockers_observed"
    return {"schema_version": 1, "contract_id": CONTRACT_ID, "scope": "advisory-read-only-input-screen",
        "expected_revision": revision, "outcome": outcome, "exit_code": int(bool(blockers or incomplete)),
        "checks": checks.rows, "blockers": blockers, "incomplete_checks": incomplete,
        "native_execution": "not_run", "counter_qualification_passed": False, "qualified_warm_passed": False,
        **dict.fromkeys(qualification.FALSE_CLAIMS, False), "budget": dict(dependency.BUDGET),
        "source_observer_limits": {"max_tracked_bytes": hwemu_source.MAX_WORKTREE_BYTES,
            "max_entries": hwemu_source.MAX_INDEX_ENTRIES, "max_modules": hwemu_source.MAX_MODULES,
            "timeout_seconds": hwemu_source.MAX_OBSERVATION_SECONDS},
        "outside_screen": list(OUTSIDE_SCREEN), "limitations": list(LIMITATIONS)}


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in PATH_ARGUMENTS:
        parser.add_argument("--" + name.replace("_", "-"), required=True)
    parser.add_argument("--expected-revision", required=True)
    return parser


def main(argv=None):
    args = argument_parser().parse_args(argv)
    try:
        report = inspect_readiness(args)
        body = json.dumps(report, sort_keys=True, allow_nan=False)
    except Exception as error:
        report = {"schema_version": 1, "contract_id": CONTRACT_ID, "outcome": "error", "exit_code": 2,
            "reason": _reason(type(error).__name__ + ": " + str(error)), "native_execution": "not_run",
            "counter_qualification_passed": False, "qualified_warm_passed": False,
            **dict.fromkeys(qualification.FALSE_CLAIMS, False), "budget": dict(dependency.BUDGET),
            "outside_screen": list(OUTSIDE_SCREEN), "limitations": list(LIMITATIONS)}
        body = json.dumps(report, sort_keys=True, allow_nan=False)
    try:
        print(body)
    except OSError:
        return 2
    return report["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
