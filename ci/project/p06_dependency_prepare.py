#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Acquire fixed dependency objects and relocate the selected prebuilt toolchain."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys

sys.dont_write_bytecode = True

from baseline_inventory import _git, collect_source
from baseline_process import run_bounded
import p02_matrix as base
import p06_dependency_contract as contract
from preflight import available_memory_bytes, read_pins


ROOT = Path(__file__).resolve().parents[2]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def prepare(args):
    source = base._path(args.source_dir, existing=True)
    workspace = base._path(args.workspace_dir, existing=True)
    require(source == ROOT and not base._overlap(source, workspace),
            "use this checkout and a distinct owned preparation workspace")
    evidence = workspace / "evidence"
    evidence.mkdir(mode=0o700, exist_ok=True)
    require(evidence.resolve() == evidence and not evidence.is_symlink(),
            "preparation evidence must be canonical")
    target = evidence / "dependency-preparation.json"
    require(not os.path.lexists(target), "dependency preparation receipt already exists")
    report = {"schema_version": 1, "contract_id": "p06-dependency-preparation-v1",
              "dependency_contract_sha256": contract.contract_hash(),
              "expected_revision": args.expected_revision, "outcome": "blocked", "reason": None,
              "failures": [], "commands": [], "repositories": {}, "toolchain_id": args.toolchain_id,
              "toolchain_cache_key": args.toolchain_cache_key, "dependency_cache_used": False,
              "native_execution": "not_run", **dict.fromkeys(contract.FALSE_CLAIMS, False)}

    def save():
        base._write_json(target, report)

    save()
    try:
        require(type(args.expected_revision) is str
                and re.fullmatch(r"[0-9a-f]{40}", args.expected_revision), "exact source revision required")
        pins, errors = read_pins(source)
        require(not errors, "invalid toolchain version inputs")
        require(re.fullmatch(re.escape(pins["TOOLCHAIN_REV"]) + r"-[0-9a-f]{40}", args.toolchain_id),
                "toolchain cache identity differs from VERSION")
        prefix = "Linux-toolchain-" + args.toolchain_id + "-"
        require(args.toolchain_cache_key in (prefix + "lite", prefix + "full"),
                "the matching pinned prebuilt toolchain cache is required")
        report["resources_before"] = {"free_disk_bytes": {
            "source": shutil.disk_usage(source).free, "workspace": shutil.disk_usage(workspace).free},
            "available_memory_bytes": available_memory_bytes()}
        require(all(value >= contract.BUDGET["min_free_bytes"]
                    for value in report["resources_before"]["free_disk_bytes"].values()),
                "fresh dependency preparation requires the 15 GiB disk reserve")
        require((report["resources_before"]["available_memory_bytes"] or 0)
                >= contract.BUDGET["max_rss_bytes"], "fresh dependency preparation requires 4 GiB available RAM")
        for name in ("softfloat", "ramulator"):
            pin = contract.PINS[name]
            expected = ("160000 commit " + pin["revision"] + "\t" + pin["path"] + "\0").encode()
            require(_git(source, "ls-tree", "-z", "HEAD", "--", pin["path"]) == expected,
                    "superproject dependency gitlink differs from the source lock")
            directory = base._path(source / pin["path"], existing=True)
            require(_git(directory, "rev-parse", "HEAD").decode().strip() == pin["revision"],
                    "initialized dependency differs from the selected gitlink")
            require(not _git(directory, "status", "--porcelain=v1", "--untracked-files=all", "--ignored"),
                    "initialized dependency contains changed, untracked or ignored inputs: " + name)
            report["repositories"][name] = str(directory)
        for relative in contract.PRODUCTS.values():
            require(not os.path.lexists(source / relative), "pre-existing dependency product is not fresh: " + relative)
        for name in ("yaml-cpp", "spdlog", "argparse"):
            require(not os.path.lexists(source / contract.PINS[name]["path"]),
                    "pre-existing fetched dependency input is not fresh: " + name)
        cached_tools = base._path(source / "tools", existing=True)
        relocated = workspace / "tools"
        acquisition = workspace / "dependency-acquisition"
        logs = evidence / "dependency-acquisition-logs"
        require(cached_tools.is_dir() and not os.path.lexists(relocated), "toolchain relocation must be fresh")
        require(not os.path.lexists(acquisition), "dependency acquisition workspace must be fresh")
        require(not os.path.lexists(logs), "dependency acquisition logs must be fresh")
        require(not _git(source, "ls-files", "-z", "--", "tools"), "toolchain directory contains tracked source")
        require(cached_tools.stat().st_dev == workspace.stat().st_dev, "toolchain relocation requires one filesystem")
        cached_tools.rename(relocated)
        report["tools_dir"] = str(relocated)
        save()
        # The restored, untracked toolchain is a preparation input, not source.
        # Relocate it before the unchanged strict checkout inventory: a real
        # cache otherwise dirties the checkout or exceeds its bounded status
        # observation. A later source rejection preserves this owned cache at
        # its recorded workspace location and starts no acquisition command.
        report["source_before"] = collect_source(source)
        base._source_ok({"checkout": report["source_before"]}, False)
        require(report["source_before"]["revision"] == args.expected_revision,
                "preparation source differs from the expected revision")
        acquisition.mkdir(mode=0o700)
        logs.mkdir(mode=0o700)
        git = shutil.which("git", path=os.defpath)
        require(git is not None, "Git is unavailable")
        environment = {"PATH": os.defpath, "LANG": "C", "LC_ALL": "C", "TZ": "UTC",
                       "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1",
                       "GIT_CONFIG_SYSTEM": "/dev/null", "GIT_CONFIG_GLOBAL": "/dev/null",
                       "GIT_NO_REPLACE_OBJECTS": "1"}
        # Acquisition may use the runner's network route; it is not retained as a credential-bearing environment.
        for key in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "NO_PROXY",
                    "https_proxy", "http_proxy", "all_proxy", "no_proxy"):
            if key in os.environ:
                environment[key] = os.environ[key]
        for name in ("yaml-cpp", "spdlog", "argparse"):
            directory = acquisition / name
            pin = contract.PINS[name]
            for operation, argv in (("init", [git, "-c", "core.hooksPath=/dev/null", "init", str(directory)]),
                                    ("fetch", [git, "-c", "core.hooksPath=/dev/null", "-C", str(directory),
                                               "fetch", "--no-tags", "--depth=1", pin["url"], pin["revision"]])):
                identifier = name + "-" + operation
                row = {"id": identifier, "argv": argv, "cwd": str(acquisition),
                       "log": "dependency-acquisition-logs/" + identifier + ".log"}
                report["commands"].append(row)
                save()
                row.update(run_bounded(argv, acquisition, environment, evidence / row["log"],
                    timeout_seconds=120, min_free_bytes=contract.BUDGET["min_free_bytes"],
                    max_rss_bytes=contract.BUDGET["max_rss_bytes"], max_log_bytes=contract.BUDGET["max_log_bytes"],
                    resource_paths=(source, workspace)))
                save()
                require(row.get("process_started") is True and row.get("outcome") == "pass"
                        and type(row.get("exit_code")) is int and row["exit_code"] == 0
                        and row.get("reason") is None and row.get("cleanup_complete") is True,
                        "dependency acquisition failed: " + identifier)
            report["repositories"][name] = str(directory)
        report["source_after"] = collect_source(source)
        require(report["source_before"] == report["source_after"], "source changed during dependency preparation")
        report["outcome"] = "pass"
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, KeyboardInterrupt) as error:
        report["reason"] = str(error) or "interrupted"
        report["failures"].append({"stage": "preparation", "reason": report["reason"]})
        if any(row.get("process_started") for row in report["commands"]):
            report["outcome"] = "fail"
    finally:
        save()
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=ROOT)
    parser.add_argument("--workspace-dir", type=Path, required=True)
    parser.add_argument("--expected-revision", required=True)
    parser.add_argument("--toolchain-id", required=True)
    parser.add_argument("--toolchain-cache-key", required=True)
    args = parser.parse_args(argv)
    try:
        report = prepare(args)
        print(json.dumps({key: report[key] for key in ("outcome", "reason", "dependency_cache_used")}, sort_keys=True))
        return 0 if report["outcome"] == "pass" else 1
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({"outcome": "blocked", "reason": str(error)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    sys.exit(main())
