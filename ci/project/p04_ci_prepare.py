#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Verify and relocate restored CI inputs before clean-source model execution."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from baseline_inventory import collect_source, hash_artifacts
import p02_matrix as base
from p02_matrix_records import require
from preflight import available_memory_bytes, read_pins


ROOT = Path(__file__).resolve().parents[2]
GIB = 1024**3
MIN_FREE_BYTES = 15 * GIB
MAX_RSS_BYTES = 4 * GIB
CACHE_REMEDY = (
    "Warm the existing CI setup job for the same VERSION/.gitmodules/third_party "
    "inputs, then rerun this workflow. This qualification job does not install "
    "a whole toolchain, rebuild cached dependencies or write shared caches."
)


def prepare(args):
    source = base._path(args.source_dir, existing=True)
    workspace = base._path(args.workspace_dir, existing=True)
    require(source == ROOT and source.is_dir(), "use this checkout's preparation helper")
    require(workspace.is_dir() and not base._overlap(source, workspace),
            "preparation workspace must be an existing directory outside the source")
    evidence = workspace / "evidence"
    evidence.mkdir(mode=0o700, exist_ok=True)
    require(not evidence.is_symlink() and evidence.resolve() == evidence,
            "evidence directory must not traverse a symlink")
    report_path = evidence / "preparation.json"
    require(not os.path.lexists(report_path), "preparation receipt already exists")
    report = {
        "schema_version": 1,
        "contract_id": "p04-hosted-preparation-v1",
        "outcome": "blocked",
        "reason": None,
        "native_execution": "not_run",
        "acceptance_claimed": False,
        "expected_revision": args.expected_revision,
        "backend": args.backend,
        "formats": ["fp16", "bf16"] if args.format == "both" else [args.format],
        "toolchain_id": args.toolchain_id,
        "toolchain_cache_key": args.toolchain_cache_key,
        "third_party_cache_key": args.third_party_cache_key,
        "budget": {"min_free_bytes": MIN_FREE_BYTES, "max_rss_bytes": MAX_RSS_BYTES,
                   "max_log_bytes": 16 * 1024**2, "jobs": 2},
        "tools_relocated": False,
        "limitations": [
            "Cache keys identify restored inputs; actual tool/library hashes are retained separately.",
            "Prepared prerequisites are not numerical execution or phase acceptance.",
            "Native processor RTL remains separate from full-AFU and vendor/physical hardware evidence.",
        ],
    }
    try:
        require(re.fullmatch(r"[0-9a-f]{40}", args.expected_revision), "invalid source revision")
        pins, errors = read_pins(source)
        require(not errors, "invalid VERSION pins: " + "; ".join(errors))
        require(re.fullmatch(re.escape(pins["TOOLCHAIN_REV"]) + r"-[0-9a-f]{40}",
                             args.toolchain_id), "toolchain cache identity differs from VERSION")
        prefix = "Linux-toolchain-" + args.toolchain_id + "-"
        require(args.toolchain_cache_key in (prefix + "lite", prefix + "full"),
                "matching pinned toolchain cache is unavailable. " + CACHE_REMEDY)
        require(re.fullmatch(r"Linux-thirdparty-[0-9a-f]{64}", args.expected_third_party_key)
                and args.third_party_cache_key == args.expected_third_party_key,
                "matching dependency cache is unavailable. " + CACHE_REMEDY)
        report["resources"] = {
            "free_disk_bytes": {"source": shutil.disk_usage(source).free,
                                "workspace": shutil.disk_usage(workspace).free},
            "available_memory_bytes": available_memory_bytes(),
        }
        require(all(value >= MIN_FREE_BYTES for value in report["resources"]["free_disk_bytes"].values()),
                "disk reserve below 15 GiB after cache restoration")
        memory = report["resources"]["available_memory_bytes"]
        require(memory is not None and memory >= MAX_RSS_BYTES, "need 4 GiB available RAM")
        cache_tools = base._path(source / "tools", existing=True)
        destination = workspace / "tools"
        require(cache_tools.is_dir() and not os.path.lexists(destination),
                "restored tools must exist and their destination must be fresh")
        tracked = subprocess.run(["git", "ls-files", "-z", "--", "tools"], cwd=source,
                                 check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        require(not tracked.stdout, "refusing to relocate tracked source files")
        revision = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=source,
                                  check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        require(revision.stdout.decode("ascii").strip() == args.expected_revision,
                "checkout differs from the workflow SHA before relocation")
        require(cache_tools.stat().st_dev == workspace.stat().st_dev,
                "atomic tool relocation requires a workspace on the source filesystem; "
                "choose a fresh outside-checkout sibling directory")
        cache_tools.rename(destination)
        report["tools_relocated"] = True
        report["tools_dir"] = str(destination)
        checkout = collect_source(source)
        report["source"] = checkout
        require(checkout["revision"] == args.expected_revision, "checkout differs from the workflow SHA")
        require(checkout["dirty"] is False and not checkout["blockers"],
                "restored source or recursive submodule provenance is invalid: "
                + "; ".join(checkout["blockers"]))
        paths = {"source": source, "tools": destination, "work": workspace / "work",
                 "output": evidence / "model", "host_bin": None,
                 "verilator": destination / "verilator"}
        environment = base.clean_environment(paths, 2)
        environment.pop("HOME", None)
        report["tool_identities"] = base.tool_inventory(paths, environment, [args.backend])
        report["dependency_identities"] = hash_artifacts(source, base.DEPENDENCIES)
        report["preparation_sources"] = hash_artifacts(source, [
            "ci/project/p04_ci_prepare.py", ".github/workflows/p04-model.yml",
            "ci/toolchain_rev.sh", "ci/install_dependencies.sh",
        ])
        report["outcome"] = "pass"
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
        report["reason"] = str(error)
    base._write_json(report_path, report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=ROOT)
    parser.add_argument("--workspace-dir", type=Path, required=True)
    parser.add_argument("--expected-revision", required=True)
    parser.add_argument("--toolchain-id", required=True)
    parser.add_argument("--toolchain-cache-key", required=True)
    parser.add_argument("--third-party-cache-key", required=True)
    parser.add_argument("--expected-third-party-key", required=True)
    parser.add_argument("--backend", choices=("simx", "rtlsim"), required=True)
    parser.add_argument("--format", choices=("fp16", "bf16", "both"), required=True)
    args = parser.parse_args(argv)
    try:
        report = prepare(args)
        print(json.dumps({"outcome": report["outcome"], "reason": report["reason"],
                          "native_execution": "not_run"}))
        return 0 if report["outcome"] == "pass" else 1
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({"outcome": "blocked", "reason": str(error), "native_execution": "not_run"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
