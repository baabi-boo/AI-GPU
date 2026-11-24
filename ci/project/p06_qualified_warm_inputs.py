#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Acquire immutable qualified-warm inputs without provisioning or native execution."""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys

sys.dont_write_bytecode = True

import baseline_inventory as inventory
from baseline_process import run_bounded
import p02_matrix as base
import p06_counter_qualification_admission as original_inputs
import p06_dependency_contract as dependency
import p06_dependency_local_prepare as local_prepare
import p06_dependency_sources as sources
import p06_local_toolchain as toolchain
import p06_qualified_warm_contract as qualification
from preflight import available_memory_bytes


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_ID = "p06-qualified-warm-input-acquisition-v1"
RECEIPT_NAME = "input-acquisition.json"
FETCHED_NAMES = ("yaml-cpp", "spdlog", "argparse")
COMMAND_TIMEOUT_SECONDS = 120
CONNECT_TIMEOUT_SECONDS = 20
LIMITATIONS = [
    "This receipt records input acquisition only; existing preparation, admission and complete replay remain required.",
    "Original prerequisite archives are hashed in place and are never extracted, rewritten or executed here.",
    "Fixed public HTTPS locations and exact Git objects select bytes; no GitHub job or artifact origin is authenticated by this receipt.",
    "Disk and process-group RSS guards are polled; effective cgroup capacity and malicious concurrent writers are outside this observation.",
    "Partial downloads, repositories and command logs are retained on failure; this acquisition cannot be resumed or overwrite an earlier attempt.",
]
_FILE_LIMIT_EXEC = (
    "import os,resource,sys; "
    "limit=int(sys.argv[1]); "
    "resource.setrlimit(resource.RLIMIT_FSIZE,(limit,limit)); "
    "os.execv(sys.argv[2],sys.argv[2:])"
)
_SOURCE_IDENTITY_EXEC = (
    "import json,sys; "
    "sys.path.insert(0,sys.argv[1]); "
    "from baseline_inventory import collect_source; "
    "print(json.dumps(collect_source(sys.argv[2]),sort_keys=True,allow_nan=False))"
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def input_plan(source=ROOT):
    """Return the frozen byte expectations, without acquiring or extracting inputs."""
    source = Path(source)
    qualification.load_proof(source / qualification.SOURCE_PROOF_PATH,
                             qualification.SOURCE_PROOF_SHA256)
    original = qualification.base_proof(source)
    manifest = toolchain._locked_manifest()
    parts = toolchain._selected_parts(manifest)
    return {
        "qualified_warm_proof_sha256": qualification.SOURCE_PROOF_SHA256,
        "historical_proof_sha256": qualification.historical.SOURCE_PROOF_SHA256,
        "toolchain": {
            **{key: manifest[key] for key in ("repository", "revision", "tag", "os_bundle")},
            "manifest_sha256": manifest["sha256"],
            "manifest_size_bytes": manifest["size_bytes"],
            "selected_components": list(toolchain.COMPONENTS),
            "parts": parts, "part_count": len(parts),
            "compressed_bytes": sum(row["size_bytes"] for row in parts),
        },
        "dependency_pins": deepcopy(dependency.PINS),
        "originals": {name: {key: original[section]["archive"][key]
                             for key in ("sha256", "size_bytes")}
                      for name, section in (("diagnostic", "diagnostics"), ("control", "controls"))},
    }


def _root(value, *, existing):
    local_prepare._literal_path(str(value))
    path = base._path(value, existing=existing)
    require(all(not parent.is_symlink() for parent in (path, *path.parents)),
            "acquisition roots must not traverse symlinks")
    require(path.is_dir() if existing else path.parent.is_dir(),
            "acquisition root or its parent must be a directory")
    return path


def _roots(args):
    roots = {"source": _root(args.source_dir, existing=True)}
    for name, attribute in (("workspace", "workspace_dir"), ("archives", "archive_root"),
                            ("repositories", "dependency_repositories"), ("output", "output_dir")):
        roots[name] = _root(getattr(args, attribute), existing=False)
    require(roots["source"] == ROOT, "execute acquisition from the selected source checkout")
    values = list(roots.values())
    require(all(not base._overlap(left, right) for index, left in enumerate(values)
                for right in values[index + 1:]), "acquisition, source and workspace roots overlap")
    for name in ("workspace", "archives", "repositories", "output"):
        require(not os.path.lexists(roots[name]), "acquisition requires a fresh " + name + " root")
    return roots


def _environment():
    # Public acquisition needs no caller credentials, user configuration or proxy secrets.
    return {"PATH": os.defpath, "LANG": "C", "LC_ALL": "C", "TZ": "UTC",
            "PYTHONDONTWRITEBYTECODE": "1", "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_SYSTEM": "/dev/null",
            "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_NO_LAZY_FETCH": "1", "GIT_ATTR_NOSYSTEM": "1", "GIT_OPTIONAL_LOCKS": "0"}


def git_probe_isolated(source, *arguments):
    git = shutil.which("git", path=os.defpath)
    require(git is not None, "Git is unavailable on the system command path")
    code, output = inventory._probe(
        [git, "--no-optional-locks", "--no-replace-objects", "-c", "core.hooksPath=/dev/null",
         "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false", "-c",
         "protocol.allow=never", "-C", str(source), *arguments], environment=_environment())
    require(code == 0, "Git identity observation failed")
    return output


def collect_source_isolated(source):
    code, output = inventory._probe(
        [sys.executable, "-I", "-B", "-c", _SOURCE_IDENTITY_EXEC,
         str(Path(__file__).resolve().parent), str(source)],
        environment=_environment(), timeout=COMMAND_TIMEOUT_SECONDS)
    require(code == 0, "source identity observation failed")
    result = json.loads(output)
    require(type(result) is dict, "source identity observation is not an object")
    return result


def _resources(roots):
    return {"free_disk_bytes": {
        name: shutil.disk_usage(path if path.exists() else path.parent).free
        for name, path in roots.items()}, "available_memory_bytes": available_memory_bytes()}


def _check_resources(record):
    require(all(value >= dependency.BUDGET["min_free_bytes"]
                for value in record["free_disk_bytes"].values()),
            "input acquisition requires the unchanged 15 GiB disk reserve")
    require((record["available_memory_bytes"] or 0) >= dependency.BUDGET["max_rss_bytes"],
            "input acquisition requires 4 GiB available RAM")


def _originals(args, expected, roots):
    result = {}
    for name in ("diagnostic", "control"):
        path = Path(getattr(args, name + "_archive"))
        local_prepare._literal_path(str(path))
        require(all(not base._overlap(path, root) for root in roots.values()),
                "original prerequisite archives must be separate from acquisition and execution roots")
        identity = original_inputs._identity(path)
        require(all(identity[key] == value for key, value in expected[name].items()),
                name + " original differs from the frozen raw identity")
        result[name] = identity
    return result


def _source_dependencies(source):
    repositories = {}
    for name in ("softfloat", "ramulator"):
        pin = dependency.PINS[name]
        expected = ("160000 commit " + pin["revision"] + "\t" + pin["path"] + "\0").encode()
        require(git_probe_isolated(source, "ls-tree", "-z", "HEAD", "--", pin["path"]) == expected,
                "source dependency gitlink differs from the frozen pin: " + name)
        directory = _root(source / pin["path"], existing=True)
        require(git_probe_isolated(directory, "rev-parse", "HEAD").decode().strip() == pin["revision"],
                "source dependency HEAD differs from the frozen pin: " + name)
        require(not git_probe_isolated(directory, "status", "--porcelain=v1", "--untracked-files=all", "--ignored"),
                "source dependency has changed, untracked or ignored inputs: " + name)
        repositories[name] = str(directory)
    for relative in dependency.PRODUCTS.values():
        require(not os.path.lexists(source / relative), "source contains a pre-existing dependency product")
    for name in FETCHED_NAMES:
        require(not os.path.lexists(source / dependency.PINS[name]["path"]),
                "source contains pre-existing fetched dependency inputs")
    return repositories


def _dependency_inventory(repositories):
    manifest = local_prepare._source_inventory(repositories)
    budget = {"commands": 0, "bytes": 0}
    for name in sorted(dependency.PINS):
        pin = dependency.PINS[name]
        reader = sources._DependencyGitObjects(Path(repositories[name]), pin["revision"], budget=budget)
        body = reader.run(["cat-file", "commit", pin["revision"]], sources.git_objects.MAX_BLOB_BYTES)
        require(hashlib.sha1(b"commit " + str(len(body)).encode() + b"\0" + body).hexdigest()
                == pin["revision"], "dependency commit bytes differ from the frozen object: " + name)
    return manifest


def _verify_part(root, part, *, partial=False):
    relative = part["path"] + (".partial" if partial else "")
    identity = sources._read_identity(root, relative, part["size_bytes"])
    require(identity["size_bytes"] == part["size_bytes"]
            and identity["sha256"] == part["sha256"] and identity["oid"] == part["git_blob_sha"],
            "toolchain part differs from the immutable size, SHA-256 or Git blob identity")


def _git_command(git, directory, *arguments):
    settings = ("core.hooksPath=/dev/null", "core.fsmonitor=false", "credential.helper=",
                "credential.interactive=false", "http.followRedirects=false", "protocol.allow=never",
                "protocol.https.allow=always", "fetch.fsckObjects=true", "transfer.fsckObjects=true",
                "gc.auto=0", "maintenance.auto=false")
    return [git, *[item for setting in settings for item in ("-c", setting)],
            "-C", str(directory), *arguments]


def _download_command(curl, manifest, part, destination):
    url = "https://raw.githubusercontent.com/" + manifest["repository"] + "/" + manifest["revision"] + "/" + part["path"]
    # RLIMIT_FSIZE also bounds chunked responses on curl versions that only check Content-Length.
    return [sys.executable, "-I", "-B", "-c", _FILE_LIMIT_EXEC, str(part["size_bytes"]), curl,
            "--disable", "--fail", "--silent", "--show-error", "--proto", "=https",
            "--proto-redir", "=https", "--max-redirs", "0", "--retry", "0",
            "--connect-timeout", str(CONNECT_TIMEOUT_SECONDS), "--max-time", str(COMMAND_TIMEOUT_SECONDS),
            "--max-filesize", str(part["size_bytes"]), "--output", str(destination),
            "--write-out", "%{http_code}\n", "--url", url]


def acquire(args):
    """Populate fresh input roots; retain every attempt separately from native preparation."""
    roots = _roots(args)
    roots["output"].mkdir(mode=0o700)
    target = roots["output"] / RECEIPT_NAME
    revision_valid = type(args.expected_revision) is str and re.fullmatch(r"[0-9a-f]{40}", args.expected_revision)
    report = {"schema_version": 1, "contract_id": CONTRACT_ID, "state": "running",
              "outcome": "blocked", "reason": None, "failures": [],
              "expected_revision": args.expected_revision if revision_valid else None,
              "roots": {name: str(path) for name, path in roots.items()},
              "plan": None, "originals": {}, "repositories": {}, "parts": [], "commands": [],
              "source_before": None, "source_after": None, "source_manifest": None,
              "resources_before": None, "resources_after": None, "input_identity_sha256": None,
              "network_acquisition": False, "toolchain_cache_used": False, "dependency_cache_used": False,
              "native_execution": "not_run", "retained_code_executed": False,
              "counter_qualification_passed": False, "qualified_warm_passed": False,
              "budget": {**dependency.BUDGET, "acquisition_command_timeout_seconds": COMMAND_TIMEOUT_SECONDS,
                         "connect_timeout_seconds": CONNECT_TIMEOUT_SECONDS},
              "limitations": list(LIMITATIONS), **dict.fromkeys(dependency.FALSE_CLAIMS, False)}
    started = False

    def save():
        base._write_json(target, report)

    def run(identifier, argv, cwd):
        row = {"id": identifier, "argv": argv, "cwd": str(cwd), "log": "logs/" + identifier + ".log"}
        report["commands"].append(row)
        save()
        row.update(run_bounded(argv, cwd, _environment(), roots["output"] / row["log"],
            timeout_seconds=COMMAND_TIMEOUT_SECONDS, min_free_bytes=dependency.BUDGET["min_free_bytes"],
            max_rss_bytes=dependency.BUDGET["max_rss_bytes"], max_log_bytes=dependency.BUDGET["max_log_bytes"],
            resource_paths=tuple(path if path.exists() else path.parent for path in roots.values())))
        if row.get("process_started") is True and ("fetch" in argv or "--url" in argv):
            report["network_acquisition"] = True
        save()
        require(row.get("process_started") is True and row.get("outcome") == "pass"
                and type(row.get("exit_code")) is int and row["exit_code"] == 0
                and row.get("reason") is None and row.get("cleanup_complete") is True,
                "input acquisition command failed: " + identifier)
        return roots["output"] / row["log"]

    save()
    try:
        require(revision_valid, "an exact lowercase 40-character source revision is required")
        report["source_before"] = collect_source_isolated(roots["source"])
        base._source_ok({"checkout": report["source_before"]}, False)
        require(report["source_before"]["revision"] == args.expected_revision,
                "input source differs from the expected revision")
        report["plan"] = plan = input_plan(roots["source"])
        require(report["source_before"]["pins"]["TOOLCHAIN_REV"] == plan["toolchain"]["tag"],
                "source toolchain version differs from the immutable archive lock")
        report["originals"] = _originals(args, plan["originals"], roots)
        report["repositories"] = _source_dependencies(roots["source"])
        report["resources_before"] = _resources(roots)
        _check_resources(report["resources_before"])
        git, curl = (shutil.which(name, path=os.defpath) for name in ("git", "curl"))
        require(git is not None and curl is not None, "Git and curl are required on the system command path")
        started = True
        roots["archives"].mkdir(mode=0o700)
        roots["repositories"].mkdir(mode=0o700)
        (roots["output"] / "logs").mkdir(mode=0o700)
        save()
        for name in FETCHED_NAMES:
            directory, pin = roots["repositories"] / name, dependency.PINS[name]
            run(name + "-init", _git_command(git, roots["repositories"], "init", "--quiet",
                "--object-format=sha1", "--template=", str(directory)), roots["repositories"])
            run(name + "-fetch", _git_command(git, directory, "fetch", "--no-tags", "--depth=1",
                "--no-recurse-submodules", pin["url"], pin["revision"]), roots["repositories"])
            report["repositories"][name] = str(directory)
        report["source_manifest"] = _dependency_inventory(report["repositories"])
        save()
        for index, part in enumerate(plan["toolchain"]["parts"], 1):
            destination = roots["archives"] / part["path"]
            partial = destination.with_name(destination.name + ".partial")
            destination.parent.mkdir(parents=True, exist_ok=True)
            require(not os.path.lexists(destination) and not os.path.lexists(partial),
                    "toolchain part destination already exists")
            row = {**part, "state": "acquiring", "partial_path": part["path"] + ".partial"}
            report["parts"].append(row)
            save()
            log = run("toolchain-part-" + str(index).zfill(2),
                      _download_command(curl, plan["toolchain"], part, partial), roots["archives"])
            require(log.read_bytes() == b"200\n", "toolchain transfer did not return a direct HTTP 200 response")
            _verify_part(roots["archives"], part, partial=True)
            require(not os.path.lexists(destination), "toolchain part would overwrite an existing input")
            partial.rename(destination)
            row["state"] = "verified"
            save()
        for part in plan["toolchain"]["parts"]:
            _verify_part(roots["archives"], part)
        require(_dependency_inventory(report["repositories"]) == report["source_manifest"],
                "dependency Git objects changed during input acquisition")
        require(_originals(args, plan["originals"], roots) == report["originals"],
                "original prerequisite archives changed during input acquisition")
        report["source_after"] = collect_source_isolated(roots["source"])
        require(report["source_after"] == report["source_before"], "source changed during input acquisition")
        report["resources_after"] = _resources(roots)
        _check_resources(report["resources_after"])
        report["input_identity_sha256"] = dependency.digest({
            "expected_revision": args.expected_revision, "plan": plan,
            "source_manifest_sha256": dependency.digest(report["source_manifest"])})
        report["outcome"] = "pass"
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, KeyboardInterrupt) as error:
        report["reason"] = str(error) or "interrupted"
        report["failures"].append({"stage": "input-acquisition", "reason": report["reason"]})
        report["outcome"] = "fail" if started else "blocked"
    finally:
        report["state"] = "finished"
        save()
    return report


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=ROOT)
    parser.add_argument("--expected-revision", required=True)
    for name in ("workspace-dir", "archive-root", "dependency-repositories", "output-dir",
                 "diagnostic-archive", "control-archive"):
        parser.add_argument("--" + name, type=Path, required=True)
    return parser


def main(argv=None):
    args = argument_parser().parse_args(argv)
    try:
        report = acquire(args)
        print(json.dumps({name: report[name] for name in ("contract_id", "outcome", "reason", "native_execution")},
                         sort_keys=True))
        return 0 if report["outcome"] == "pass" else 1
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({"outcome": "blocked", "reason": str(error), "native_execution": "not_run"}, sort_keys=True))
        return 1


if __name__ == "__main__":
    sys.exit(main())
