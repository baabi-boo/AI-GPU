#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""One-shot independent provenance audit of the retained workspace originals."""

import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "ci/project"))
from p02_matrix_records import DISABLED, validate_header_macros
from p03_execution_records import qualification_id
from p06_workspace_compiler_records import validate_records
from p06_workspace_execute import validate_effective_header

REVISION = "13dc0d1fdb6d5322104e381aa342dc139c7bb80c"
TREE = "b10ca275377103ad94941847ee4efb1b3f296efd"
PACKET = ROOT / "docs/project/evidence/p06-warm-workspace"
BUDGET = {
    "build_timeout_seconds": 1800, "configure_timeout_seconds": 120,
    "jobs": 2, "max_log_bytes": 16777216, "max_rss_bytes": 4294967296,
    "min_free_bytes": 16106127360, "run_timeout_seconds": 180,
}


def require(ok, label):
    if not ok:
        raise ValueError(label)


def digest(body):
    return hashlib.sha256(body).hexdigest()


def unique(pairs):
    row = {}
    for key, value in pairs:
        require(key not in row, "duplicate JSON field: " + key)
        row[key] = value
    return row


def read_json(body):
    return json.loads(body, object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def git_inventory():
    raw = subprocess.check_output(["git", "ls-tree", "-r", "-z", REVISION], cwd=ROOT)
    rows = {}
    for record in raw.split(b"\0"):
        if record:
            info, name = record.split(b"\t", 1)
            mode, kind, oid = info.decode().split()
            rows[name.decode()] = (mode, kind, oid)
    require(subprocess.check_output(["git", "rev-parse", REVISION + "^{tree}"],
                                   cwd=ROOT).decode().strip() == TREE, "source tree identity")
    return rows


def audit(artifact, git_files):
    archive = ROOT / artifact["path"]
    body = archive.read_bytes()
    require(len(body) == artifact["size_in_bytes"], "archive size")
    require(digest(body) == artifact["sha256"] == artifact["digest"].removeprefix("sha256:"),
            "archive digest")
    with zipfile.ZipFile(archive) as z:
        infos = z.infolist()
        names = [item.filename for item in infos]
        require(len(names) == len(set(names)), "duplicate ZIP member")
        require(sum(item.file_size for item in infos) < 64 * 1024**2, "archive size bound")
        for info in infos:
            p = PurePosixPath(info.filename)
            require(not p.is_absolute() and ".." not in p.parts
                    and not stat.S_ISLNK(info.external_attr >> 16), "unsafe ZIP member")

        def data(name):
            return z.read(name)

        def doc(name):
            return read_json(data(name))

        checked = set()

        def descriptor(row, prefix="workspace/"):
            raw = data(prefix + row["path"])
            require(len(raw) == row["size_bytes"] and digest(raw) == row["sha256"],
                    "descriptor mismatch: " + row["path"])
            checked.add(prefix + row["path"])
            return raw

        r = doc("workspace/report.json")
        require(r["state"] == "finished" and r["outcome"] == "pass"
                and r["failures"] == [] and r["reason"] is None, "final outcome")
        for key in ("acceptance_claimed", "performance_acceptance", "phase_acceptance", "phase_complete"):
            require(r[key] is False, "unexpected acceptance claim")
        require(r["budget"] == BUDGET, "native budget changed")
        snapshots = {}
        for label in ("source", "tools", "dependencies"):
            first = read_json(descriptor(r[label + "_before"]))
            last = read_json(descriptor(r[label + "_after"]))
            require(r[label + "_stable"] is True and first == last, label + " stability")
            snapshots[label] = first
        source, tools, dependencies = (snapshots[k] for k in ("source", "tools", "dependencies"))
        checkout = source["checkout"]
        require(checkout["revision"] == REVISION and checkout["tree"] == TREE
                and checkout["dirty"] is False and checkout["changed_paths"] == []
                and checkout["untracked_paths"] == [] and checkout["blockers"] == []
                and checkout["outcome"] == "pass", "clean source checkout")
        require(checkout["submodules"]["errors"] == [], "submodule errors")
        top_submodules = 0
        for entry in checkout["submodules"]["entries"]:
            require(entry["status"] == "initialized", "uninitialized submodule")
            if entry["path"] in git_files:
                require(git_files[entry["path"]] == ("160000", "commit", entry["revision"]),
                        "top-level submodule revision")
                top_submodules += 1
        require(top_submodules == 5, "missing top-level submodule pins")
        require(r["retained_sources"] == [dict(row, path="artifacts/source/" + row["path"])
                                         for row in source["files"]], "source inventory mapping")
        verified_git = 0
        submodule_source_bodies = 0
        submodule_roots = [name for name, (mode, _, _) in git_files.items() if mode == "160000"]
        for row in source["files"]:
            raw = descriptor(dict(row, path="artifacts/source/" + row["path"]))
            if row["path"] not in git_files:
                require(any(row["path"].startswith(name + "/") for name in submodule_roots),
                        "retained source outside committed tree or pinned submodules: " + row["path"])
                submodule_source_bodies += 1
                continue
            mode, kind, oid = git_files[row["path"]]
            require(kind == "blob" and hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() == oid,
                    "retained source differs from Git blob: " + row["path"])
            verified_git += 1
        for row in r["loaded_helpers"] + checkout["inputs"] + r["corpus"]:
            require(row in source["files"], "unbound source/helper input")
        for entry in r["stability_checks"]:
            for label, snapshot in snapshots.items():
                require(entry[label + "_sha256"] == qualification_id(snapshot), "intermediate stability digest")
        for resources in (r["resources_before"], r["resources_after"]):
            require(all(n >= BUDGET["min_free_bytes"] for n in resources["free_disk_bytes"].values()),
                    "disk reserve violation")
            require(resources["available_memory_bytes"] >= BUDGET["max_rss_bytes"], "available memory prerequisite")
        for row in r["raw_logs"]:
            descriptor(row)
        commands = {}
        for command in r["commands"]:
            require(command["id"] not in commands, "duplicate command")
            commands[command["id"]] = command
            raw = data("workspace/" + command["log"])
            require(command["outcome"] == "pass" and command["exit_code"] == 0
                    and command["cleanup_complete"] is True and command["process_started"] is True
                    and command["reason"] is None, "failed command")
            require(digest(raw) == command["log_sha256"]
                    and len(raw) == command["log_size_bytes"] <= BUDGET["max_log_bytes"], "command log identity/bound")
            require(command["peak_rss_bytes"] <= BUDGET["max_rss_bytes"], "RSS budget")
            require(command["duration_seconds"] <= command["timeout_seconds"] + 1, "command deadline")
            env = command["environment"]
            require(env["MAKEFLAGS"] == "-j2" and env["THREADS"] == "2"
                    and env["CMAKE_BUILD_PARALLEL_LEVEL"] == "2" and env["CCACHE_DISABLE"] == "1",
                    "job budget/environment")
        require(len(r["variants"]) == 1, "selected variant count")
        variant = r["variants"][0]
        driver, fmt, vid = (variant[k] for k in ("backend", "format", "id"))
        require(vid == driver + "-" + fmt and variant["outcome"] == "pass", "variant identity")
        require(variant["artifacts_before"] == variant["artifacts_after"], "binary/config identities changed")
        all_builds = {}
        for stage in variant["retained_builds"]:
            for row in stage["files"]:
                descriptor(row)
                all_builds[row["path"]] = row
        prefix = "artifacts/" + vid + "/frozen/"

        def frozen(name):
            return data("workspace/" + prefix + name).decode()

        for row in variant["artifacts_before"]:
            key = prefix + row["path"]
            if key in all_builds:
                require(all_builds[key] == dict(row, path=key), "frozen artifact identity")
        for row in variant["generated_identity"]:
            key = "artifacts/" + vid + "/configured/" + row["path"]
            if key in all_builds:
                require(all_builds[key] == dict(row, path=key), "generated artifact identity")
        records = validate_records(frozen("sw/runtime/" + driver + "_rt_config.stamp"),
                                   frozen("sw/runtime/" + driver + "_config.stamp"),
                                   frozen("tests/regression/ai_workspace/config.stamp"),
                                   driver=driver, fmt=fmt, source=Path(r["paths"]["source"]),
                                   build=Path(variant["build_dir"]), jobs=2)
        require(records == variant["compiler_records"], "independent compiler validation result")
        header = validate_header_macros(data("workspace/logs/" + vid + "-header.log").decode())
        require(header == variant["header_macros"], "raw generated header")
        expanded = validate_header_macros(data("workspace/logs/" + vid + "-expected-expanded-header.log").decode())
        require(expanded == variant["expected_expanded_header_macros"], "expanded header")
        backend_header = dict(header, **{name + "_DISABLE": "1" for name in DISABLED})
        require(backend_header == variant["expected_backend_header_macros"], "backend generated profile")
        for record in records:
            role = record["role"]
            expected = dict(backend_header if role in ("backend_cpp", "verilator") else expanded)
            if driver == "rtlsim" and role == "backend_cpp":
                expected.pop("VX_CFG_TCU_TYPE_TFR", None)
                expected.pop("VX_CFG_FPU_TYPE_STD", None)
            row = variant["effective_headers"][role]
            require(row["command_id"] == vid + "-" + role + "-header", "effective header command")
            actual = validate_effective_header(data("workspace/" + commands[row["command_id"]]["log"]).decode(),
                                               expected, driver=driver, role=role)
            require(actual == row["macros"], "effective header result")
        contract = read_json(descriptor(r["contract_snapshot"]))
        fixtures = read_json(descriptor(r["fixture_snapshot"]))
        for process in r["processes"]:
            binding = read_json(descriptor(process["binding"]))
            require(qualification_id(binding) == process["qualification_id"], "qualification digest")
            for key, expected in (("source", source), ("tools", tools), ("dependencies", dependencies),
                                  ("compiler_records", records), ("artifacts", variant["artifacts_before"]),
                                  ("generated_identity", variant["generated_identity"]),
                                  ("effective_headers", variant["effective_headers"]),
                                  ("policy", process["policy"]), ("backend", driver), ("format", fmt),
                                  ("sequence", contract["sequence"]), ("cases", fixtures)):
                require(binding[key] == expected, "binding " + key)
        job = doc("job.json")
        for key, expected in (("GITHUB_SHA", REVISION), ("GITHUB_RUN_ID", "44925627664"),
                              ("GITHUB_RUN_ATTEMPT", "1"), ("GITHUB_REPOSITORY", "baabi-boo/AI-GPU"),
                              ("GITHUB_REF", "refs/heads/master"), ("P06_WORKSPACE_BACKEND", driver),
                              ("P06_WORKSPACE_FORMAT", fmt)):
            require(job[key] == expected, "hosted job identity")
        workflow = data("workflow.yml")
        require(digest(workflow) == job["workflow_sha256"]
                and workflow == data("workspace/artifacts/source/.github/workflows/p06-workspace.yml"),
                "hosted workflow identity")
        require(b"timeout-minutes: 90" in workflow and b"max-parallel: 2" in workflow, "hosted limits")
        preparation = doc("preparation.json")
        require(preparation["outcome"] == "pass" and preparation["expected_revision"] == REVISION
                and preparation["backend"] == driver and preparation["formats"] == [fmt]
                and preparation["source"] == checkout, "preparation identity")
        provision = doc("python-provision.json")
        require(provision["python_version"] == [3, 12, 14] and provision["implementation"] == "CPython"
                and provision["python3_on_path"] == tools["python3"]["path"], "interpreter identity")
        require(r["retained_files_stable"] is True, "retained file stability claim")
        return {"variant": vid, "outcome": "pass", "artifact_id": artifact["id"],
                "archive_sha256": digest(body), "report_sha256": digest(data("workspace/report.json")),
                "source_revision": REVISION, "source_tree": TREE,
                "retained_source_blobs_matched_to_git": verified_git,
                "submodule_source_bodies_hash_checked": submodule_source_bodies,
                "descriptor_files_checked": len(checked), "commands_checked": len(commands),
                "compiler_roles": [row["role"] for row in records], "linker_record_checked": True,
                "effective_headers_checked": len(records), "bindings_checked": len(r["processes"]),
                "peak_sampled_rss_bytes": max(c["peak_rss_bytes"] for c in commands.values()),
                "minimum_observed_free_disk_bytes": min(n for resources in
                    (r["resources_before"], r["resources_after"]) for n in resources["free_disk_bytes"].values()),
                "binary_identities_without_binary_bodies": [row["path"] for row in variant["artifacts_before"]
                    if prefix + row["path"] not in all_builds]}


def main():
    git_files = git_inventory()
    artifacts = read_json((PACKET / "originals/artifacts.json").read_bytes())
    rows = [audit(artifact, git_files) for artifact in artifacts]
    require({r["variant"] for r in rows} == {"simx-fp16", "simx-bf16", "rtlsim-fp16", "rtlsim-bf16"}
            and len(rows) == 4, "four distinct variants")
    result = {"schema_version": 1, "reviewer": "/root/w01_a06_native_provenance",
              "scope": "independent original workspace provenance/compiler/budget audit",
              "outcome": "pass", "native_execution": "not_run", "acceptance_claimed": False,
              "source_revision": REVISION, "source_tree": TREE,
              "workflow_run_id": 44925627664, "workflow_attempt": 1,
              "variants": sorted(rows, key=lambda r: r["variant"]), "findings": [],
              "limitations": [
                  "This review parses retained data and trusted current local validators; it executes no archived source or binary.",
                  "Numerical results and allocator-lifetime semantics are independently reviewed by other assignments.",
                  "The original binary/tool/dependency payloads are not retained; their reported before/after hashes are checked for consistency, not rehashed from unavailable bodies.",
                  "The five top-level submodule commits match Git; nested submodule identities are recorded clean-source observations, not independently fetched here.",
                  "Retained submodule source bodies are hash-checked against the source inventory; this checkout lacks those submodule Git object databases, so their commit membership is not independently replayed here.",
                  "RSS and disk limits are polled observations, not hard quotas; between-poll peaks are outside this evidence.",
                  "Job and preparation native_execution=not_run are initialization/preparation fields; the final execution report is the source for completed native commands.",
                  "Processor rtlsim bypasses the AFU. No vendor, physical hardware, speedup or phase acceptance follows from this review.",
              ]}
    (PACKET / "reviews/workspace-provenance.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"outcome": result["outcome"], "variants": rows}, indent=2))


if __name__ == "__main__":
    main()
