#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Compose a trusted manual hosted attempt with private, encrypted closeout."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sys
import tarfile
import tempfile
import time
from urllib.parse import urlencode

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from p06_qualified_warm_inputs import (
    collect_source_isolated as collect_source, git_probe_isolated as _git,
)
from baseline_packet_contract import RECURSIVE_SUBMODULES
from baseline_packet_io import load_json_bytes
from baseline_process import run_bounded
import governance_replay
import p02_matrix as base
import p06_dependency_contract as dependency
import p06_dependency_local_prepare as preparation
import p06_governance_api as governance_api
import p06_governance_artifact as governance_artifact
import p06_qualified_warm_capacity as capacity
import p06_qualified_warm_encrypt as encryption
import p06_qualified_warm_run as runner
from xrt_signals import terminate_as_interrupt


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_ID = "p06-qualified-warm-hosted-v1"
REPOSITORY = "baabi-boo/AI-GPU"
WORKFLOW = ".github/workflows/p06-qualified-warm.yml"
GOVERNANCE_WORKFLOW = ".github/workflows/project-governance.yml"
GOVERNANCE_STEPS = (
    "Verify system Python 3.12", "Inspect governance prerequisites",
    "Validate project structure and evidence", "Check published baseline packet consistency",
    "Install pinned governance CMake", "Prepare checked governance invocation environment",
    "Test governance tooling", "Retain complete governance packet",
)
URL_VARIABLE = "P06_CONTROL_ARCHIVE_URL"
RECIPIENT_VARIABLE = "P06_EVIDENCE_AGE_RECIPIENT"
DIAGNOSTIC = "docs/project/evidence/p06-counter-diagnostics/native/run-45034575685-attempt1.zip"
AGE_URL = "https://github.com/FiloSottile/age/releases/download/v1.3.2/age-v1.3.2-linux-amd64.tar.gz"
AGE_SHA256 = "cbe24006683f8eb669266162894b9a522a1af52f2665fbc63a4bb032ed26ac10"
AGE_BYTES = 19405817
CMAKE_REQUIREMENT = "cmake==3.22.6 --hash=sha256:a2357c510e37db7df156c31ab43857b4583e3a2ece8220747e8a007aea50aa45\n"
HOST_PACKAGES = (
    "gcc-12", "g++-12", "binutils", "make", "perl", "libstdc++6", "libc6-dev",
    "uuid-dev", "libffi8", "libpng-dev", "libboost-serialization-dev", "libtinfo6",
    "zlib1g-dev", "libgmp-dev", "libmpfr-dev", "libmpc-dev",
)
_FILE_LIMIT_EXEC = (
    "import os,resource,sys; limit=int(sys.argv[1]); "
    "resource.setrlimit(resource.RLIMIT_FSIZE,(limit,limit)); os.execv(sys.argv[2],sys.argv[2:])"
)
MAX_API_BYTES = 4 * 1024**2
MAX_PUBLIC_SUMMARY_BYTES = 4096
# Covers the encryption helper's 1 GiB input plus bounded tar/manifest overhead.
MAX_PUBLIC_CIPHERTEXT_BYTES = 2 * 1024**3
SOURCE_FILES = tuple(sorted(set(runner.SOURCE_FILES) | {
    "ci/project/p06_qualified_warm_hosted.py", "ci/project/p06_qualified_warm_control.py",
    "ci/project/p06_qualified_warm_capacity.py", "ci/project/p06_qualified_warm_pack.py",
    "ci/project/p06_qualified_warm_encrypt.py", WORKFLOW, GOVERNANCE_WORKFLOW,
    "ci/project/governance_replay.py", "ci/project/governance_replay_archive.py",
    "ci/project/governance_replay_events.py", "ci/project/governance_replay_records.py",
    "ci/project/governance_replay_source.py", "ci/project/governance_replay_collect.py",
    "ci/project/p06_governance_api.py", "ci/project/p06_governance_artifact.py",
}))
LIMITATIONS = [
    "Governance admission independently replays the exact provider-bound original and collects tests from the trusted checkout; it does not reproduce test execution or establish native acceptance.",
    "Visible capacity observations never establish complete cgroup hierarchy visibility or reserve host resources.",
    "Ubuntu GCC 12 package and executable identities are retained for this attempt; equivalence to a historical compiler is not claimed.",
    "The native supervisor retains its 90-minute budget and existing 120/1800/180-second child limits; outer monitors do not contain child-created process groups.",
    "Packaging follows completed writer and cleanup records, not an operating-system proof that every possible writer is absent.",
    "Downloaded toolchain parts, fetched Git repositories and installed host tools remain local inputs; their receipts, logs and selected native evidence are retained.",
    "Selected operational helper and workflow bytes are retained with repeated identities; this does not establish complete operating-system input closure.",
    "If packaging fails before copying selected evidence, encrypted closeout preserves only bytes already created in the retention directory; other private originals remain local.",
    "Abrupt provider termination, unresolved writer cleanup or unavailable encryption can prevent encrypted delivery; such an attempt cannot pass.",
    "Hosted composition and encrypted delivery do not establish independent native replay, performance acceptance, phase acceptance or hardware qualification.",
]


class HostedError(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise HostedError(code)


def _revision(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{40}", value) is not None


def _write(path, value):
    body = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    require(len(body) <= dependency.MAX_RECEIPT_BYTES, "receipt_bound")
    with Path(path).open("xb") as stream:
        stream.write(body)


def _read(path, maximum=dependency.MAX_RECEIPT_BYTES, *, warm=False):
    _, body = runner._file(path, maximum, contents=True)
    result = (runner.qualified_warm_replay.decode_report(body) if warm
              else load_json_bytes(body, "private hosted receipt"))
    require(type(result) is dict, "receipt_shape")
    return result


def _public(revision, stage, outcome):
    return {"contract_id": CONTRACT_ID, "expected_revision": revision if _revision(revision) else None,
            "stage": stage, "outcome": outcome}


def _emit(revision, stage, outcome):
    print(json.dumps(_public(revision, stage, outcome), sort_keys=True), flush=True)


def trusted_context(environment, revision):
    require(_revision(revision), "revision")
    expected = {"GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF": "refs/heads/master",
                "GITHUB_REPOSITORY": REPOSITORY, "GITHUB_SHA": revision,
                "GITHUB_WORKFLOW_SHA": revision,
                "GITHUB_WORKFLOW_REF": REPOSITORY + "/" + WORKFLOW + "@refs/heads/master"}
    require(all(environment.get(key) == value for key, value in expected.items()), "untrusted_context")
    for key in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"):
        require(re.fullmatch(r"[1-9][0-9]{0,19}", environment.get(key, "")) is not None, "provider_identity")
    return {**expected, **{key: environment[key] for key in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT")}}


def _api(path, token):
    return governance_api.request(path, token)


def _governance_run(row, revision, workflow_id):
    return (type(row) is dict and type(row.get("id")) is int and row["id"] > 0
            and type(row.get("run_attempt")) is int and row["run_attempt"] > 0
            and row.get("workflow_id") == workflow_id and row.get("path") == GOVERNANCE_WORKFLOW
            and row.get("head_sha") == revision and row.get("head_branch") == "master"
            and row.get("event") in ("push", "workflow_dispatch")
            and row.get("status") == "completed" and row.get("conclusion") == "success"
            and all(type(row.get(key)) is dict and row[key].get("full_name") == REPOSITORY
                    for key in ("repository", "head_repository")))


def _governance_job(jobs, revision, run_id, run_attempt):
    require(type(jobs) is dict and type(jobs.get("total_count")) is int
            and jobs["total_count"] == 1 and type(jobs.get("jobs")) is list
            and len(jobs["jobs"]) == 1, "governance_jobs")
    job = jobs["jobs"][0]
    require(type(job) is dict and type(job.get("id")) is int and job["id"] > 0
            and type(job.get("run_id")) is int and job["run_id"] == run_id
            and job.get("name") == "governance" and job.get("head_sha") == revision
            and type(job.get("run_attempt")) is int and job["run_attempt"] == run_attempt
            and job.get("status") == "completed" and job.get("conclusion") == "success", "governance_job")
    steps = job.get("steps")
    require(type(steps) is list and all(type(step) is dict and step.get("status") == "completed"
            and step.get("conclusion") == "success" for step in steps), "governance_steps")
    names = [step.get("name") for step in steps]
    require(all(names.count(name) == 1 for name in GOVERNANCE_STEPS), "governance_full_run")
    return job


def _provider_digest(document):
    require(type(document) is dict, "governance_observation")
    body = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    require(0 < len(body) <= MAX_API_BYTES, "governance_observation")
    return hashlib.sha256(body).hexdigest()


def _provider_observations(workflow, run, jobs):
    return {key: _provider_digest(value) for key, value in (
        ("workflow_sha256", workflow), ("run_sha256", run), ("jobs_sha256", jobs))}


def verify_governance(revision, token, api=None):
    require(_revision(revision), "revision")
    require(type(token) is str and re.fullmatch(r"[A-Za-z0-9_.-]{1,256}", token), "api_token")
    get = (lambda path: _api(path, token)) if api is None else api
    prefix = "/repos/" + REPOSITORY + "/actions/"
    workflow = get(prefix + "workflows/project-governance.yml")
    require(workflow.get("path") == GOVERNANCE_WORKFLOW and workflow.get("state") == "active"
            and type(workflow.get("id")) is int and workflow["id"] > 0, "governance_workflow")
    runs = get(prefix + "workflows/project-governance.yml/runs?" + urlencode(
        {"head_sha": revision, "status": "completed", "per_page": 100}))
    rows = runs.get("workflow_runs")
    require(type(rows) is list and len(rows) <= 100, "governance_runs")
    selected = [row for row in rows if _governance_run(row, revision, workflow["id"])]
    require(selected, "governance_missing")
    row = max(selected, key=lambda value: (value["id"], value["run_attempt"]))
    run_path = prefix + "runs/" + str(row["id"])
    jobs = get(run_path + "/attempts/" + str(row["run_attempt"]) + "/jobs?per_page=100")
    job = _governance_job(jobs, revision, row["id"], row["run_attempt"])
    latest = get(run_path)
    require(_governance_run(latest, revision, workflow["id"])
            and latest["id"] == row["id"] and latest["run_attempt"] == row["run_attempt"]
            and latest["event"] == row["event"], "governance_changed")
    return {"workflow_id": workflow["id"], "run_id": row["id"], "run_attempt": row["run_attempt"],
            "job_id": job["id"], "head_sha": revision, "event": row["event"],
            "required_steps": list(GOVERNANCE_STEPS),
            "provider_observations": _provider_observations(workflow, latest, jobs),
            "provider_observed_success": True, "independent_packet_replay": False}


def _reobserve_governance(revision, token, governance):
    prefix = "/repos/" + REPOSITORY + "/actions/"
    run_path = prefix + "runs/" + str(governance["run_id"])
    workflow = _api(prefix + "workflows/project-governance.yml", token)
    run = _api(run_path, token)
    jobs = _api(run_path + "/attempts/" + str(governance["run_attempt"]) + "/jobs?per_page=100", token)
    require(_governance_run(run, revision, governance["workflow_id"]), "governance_changed")
    _governance_job(jobs, revision, governance["run_id"], governance["run_attempt"])
    require(_provider_observations(workflow, run, jobs) == governance["provider_observations"],
            "governance_changed")
    require(_provider_digest(_api(run_path, token)) == governance["provider_observations"]["run_sha256"],
            "governance_changed")


def verify_source(source, revision):
    source = runner._canonical(source, existing=True)
    require(source == ROOT, "source_location")
    snapshot = collect_source(source)
    base._source_ok({"checkout": snapshot}, False)
    rows = snapshot["submodules"]["entries"]
    require(snapshot["revision"] == revision and len(rows) == 8
            and {row["path"] for row in rows} == RECURSIVE_SUBMODULES
            and all(row["status"] == "initialized" for row in rows), "source_gitlinks")
    for path in (source, *(source / row["path"] for row in rows)):
        require(not _git(path, "status", "--porcelain=v1", "--untracked-files=all", "--ignored",
                         "--ignore-submodules=none"), "source_unclean")
    return snapshot


def _governance_admission(source, revision, token, parent, snapshot, governance):
    parent = runner._canonical(parent, existing=True)
    require(parent.is_dir() and not base._overlap(source, parent), "governance_output")
    directory = parent / "governance"
    artifact = governance_artifact.download_artifact(
        revision, governance["run_id"], governance["run_attempt"], token, directory, api=_api)
    require(type(artifact) is dict and artifact.get("provider_observed_stable") is True
            and type(artifact.get("artifact_id")) is int and artifact["artifact_id"] > 0
            and artifact.get("artifact_name") == (f"project-governance-{revision}-run"
                f"{governance['run_id']}-attempt{governance['run_attempt']}")
            and artifact.get("repository") == REPOSITORY and artifact.get("head_sha") == revision
            and type(artifact.get("run_id")) is int and artifact["run_id"] == governance["run_id"]
            and type(artifact.get("run_attempt")) is int
            and artifact["run_attempt"] == governance["run_attempt"]
            and type(artifact.get("bytes")) is int
            and 0 < artifact["bytes"] <= governance_artifact.MAX_ARCHIVE_BYTES
            and type(artifact.get("sha256")) is str
            and re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"]), "governance_artifact")
    archive = runner._canonical(artifact.get("archive_path"), existing=True)
    require(archive == directory / "governance.zip", "governance_artifact")
    identity, _ = runner._file(archive, governance_artifact.MAX_ARCHIVE_BYTES)
    require(identity["sha256"] == artifact["sha256"] and identity["size_bytes"] == artifact["bytes"],
            "governance_artifact")
    replay = governance_replay.verify_archive(
        archive, revision=revision, source_dir=source, expected_sha256=artifact["sha256"])
    require(type(replay) is dict and type(replay.get("schema_version")) is int
            and replay["schema_version"] == 1 and replay.get("revision") == revision
            and replay.get("scope") == "project-governance-artifact-replay-only"
            and replay.get("independent_packet_replay") is True
            and replay.get("trusted_source_imported") is True
            and all(replay.get(field) is False for field in (
                "provider_authenticated", "retained_code_executed", "tests_executed_by_replay",
                "native_acceptance", "phase_acceptance", "performance_acceptance"))
            and runner._same_json(replay.get("archive"), {
                "bytes": artifact["bytes"], "sha256": artifact["sha256"]}), "governance_replay")
    require(runner._same_json(verify_source(source, revision), snapshot), "source_changed")
    _reobserve_governance(revision, token, governance)
    require(runner._same_json(verify_source(source, revision), snapshot)
            and runner._file(archive, governance_artifact.MAX_ARCHIVE_BYTES)[0] == identity,
            "governance_changed")
    provider = {key: artifact[key] for key in (
        "artifact_id", "artifact_name", "sha256", "bytes", "repository", "head_sha", "run_id", "run_attempt")}
    governance = dict(governance, artifact=provider, independent_packet_replay=True,
                      provider_observed_stable=True, source_observed_stable=True, replay=replay)
    _write(directory / "provider.json", {key: value for key, value in governance.items() if key != "replay"})
    _write(directory / "replay.json", replay)
    return governance


def preflight(source, revision, environment=None, *, output_parent=None):
    try:
        environment = os.environ if environment is None else environment
        context = trusted_context(environment, revision)
        source = runner._canonical(source, existing=True)
        snapshot = verify_source(source, revision)
        token = environment.get("GITHUB_TOKEN")
        governance = verify_governance(revision, token)
        if output_parent is None:
            with tempfile.TemporaryDirectory(prefix="p06-governance-", dir="/tmp") as directory:
                governance = _governance_admission(source, revision, token, Path(directory), snapshot, governance)
        else:
            governance = _governance_admission(source, revision, token, output_parent, snapshot, governance)
        return {"context": context, "source": snapshot, "governance": governance}
    except Exception:
        raise HostedError("governance_admission") from None


def capacity_gate(source, attempt):
    observed = capacity.observe_capacity()
    disk = {name: shutil.disk_usage(path).free for name, path in (("source", source), ("attempt", attempt))}
    good = (observed.get("known_memory_shortfall") is False
            and observed.get("observation_complete") is True
            and observed.get("effective_capacity_status") == "unknown"
            and type(observed.get("host_available_bytes")) is int
            and observed["host_available_bytes"] >= dependency.BUDGET["max_rss_bytes"]
            and all(value >= dependency.BUDGET["min_free_bytes"] for value in disk.values()))
    return {"observation": observed, "free_disk_bytes": disk, "gate_satisfied": good,
            "effective_capacity_established": False}


def _environment(attempt):
    return {"PATH": str(Path(sys.executable).parent) + ":/usr/bin:/bin",
            "HOME": str(attempt / "home"), "TMPDIR": str(attempt / "tmp"),
            "LANG": "C", "LC_ALL": "C", "TZ": "UTC", "PYTHONUTF8": "1",
            "PYTHONDONTWRITEBYTECODE": "1", "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_SYSTEM": "/dev/null", "GIT_CONFIG_GLOBAL": "/dev/null",
            "CCACHE_DISABLE": "1", "OBJCACHE": "", "MAKEFLAGS": "-j2",
            "CMAKE_BUILD_PARALLEL_LEVEL": "2", "THREADS": "1", "DEBIAN_FRONTEND": "noninteractive"}


def provision_age(attempt, stage):
    archive = attempt / "bootstrap/age.tar.gz"
    require(shutil.disk_usage(attempt).free >= AGE_BYTES + 128 * 1024**2, "retention_tool_disk")
    stage("retention-tool-download", [sys.executable, "-I", "-B", "-c", _FILE_LIMIT_EXEC, str(AGE_BYTES),
          "/usr/bin/curl", "--disable", "--fail", "--silent", "--show-error",
          "--location", "--proto", "=https", "--proto-redir", "=https", "--max-redirs", "3",
          "--retry", "0", "--connect-timeout", "20", "--max-time", "120", "--max-filesize", str(AGE_BYTES),
          "--output", str(archive), "--url", AGE_URL], 130, retention=True)
    identity, _ = runner._file(archive, AGE_BYTES)
    require(identity["size_bytes"] == AGE_BYTES and identity["sha256"] == AGE_SHA256, "age_identity")
    target = attempt / "bootstrap/age"
    with tarfile.open(archive, "r:gz") as bundle:
        selected = []
        for index, member in enumerate(bundle):
            require(index < 16, "age_archive_bound")
            if member.name == "age/age":
                require(member.isfile() and 0 < member.size <= 64 * 1024**2, "age_archive_member")
                selected.append(member)
        require(len(selected) == 1, "age_archive_member")
        with bundle.extractfile(selected[0]) as original, target.open("xb") as output:
            shutil.copyfileobj(original, output, 1024 * 1024)
    target.chmod(0o700)
    stage("retention-tool-version", [str(target), "--version"], 30, retention=True)
    require((attempt / "hosted/logs/retention-tool-version.log").read_bytes() == b"v1.3.2\n", "age_version")
    return target


def provision_host(attempt, stage):
    apt = ["/usr/bin/sudo", "-n", "/usr/bin/env", "DEBIAN_FRONTEND=noninteractive", "/usr/bin/apt-get"]
    stage("host-package-index", [*apt, "-q", "update"], 180)
    stage("host-packages", [*apt, "-q", "-y",
                           "--no-install-recommends", "install", *HOST_PACKAGES], 600)
    stage("host-package-versions", ["/usr/bin/dpkg-query", "-W", "-f=${Package}\t${Version}\t${Architecture}\n",
                                   *HOST_PACKAGES], 30)
    requirement = attempt / "bootstrap/cmake-requirements.txt"
    requirement.write_text(CMAKE_REQUIREMENT, encoding="ascii")
    stage("host-cmake", [sys.executable, "-I", "-B", "-m", "pip", "--isolated", "--disable-pip-version-check",
          "install", "--index-url", "https://pypi.org/simple", "--no-cache-dir", "--no-deps", "--no-compile",
          "--only-binary=:all:", "--require-hashes", "--target", str(attempt / "bootstrap/cmake-package"),
          "--requirement", str(requirement)], 180)
    host = attempt / "host-bin"
    host.mkdir(mode=0o700)
    targets = {name: Path("/usr/bin") / (name + "-12" if name in ("gcc", "g++") else name)
               for name in ("gcc", "g++", "ar", "ranlib", "make", "as", "ld", "bash", "perl")}
    targets["cmake"] = attempt / "bootstrap/cmake-package/cmake/data/bin/cmake"
    for name, target in targets.items():
        require(target.is_file() and os.access(target, os.X_OK), "host_tool_missing")
        (host / name).symlink_to(target)
    for name in ("gcc", "g++", "cmake"):
        stage("host-version-" + name.replace("+", "p"), [str(host / name), "--version"], 30)
    require((attempt / "hosted/logs/host-version-cmake.log").read_bytes().splitlines()[0]
            == b"cmake version 3.22.6", "cmake_version")
    tools = preparation._host_tools(host)
    _write(attempt / "hosted/host-tools.json", {"tools": tools, "interpreter": runner.interpreter_identity(),
           "packages": list(HOST_PACKAGES), "same_as_historical_compiler_claimed": False})
    return host


def copy_diagnostic(source, destination):
    expected = runner.ORIGINAL_ARCHIVES["diagnostic_archive"]
    identity, body = runner._file(source / DIAGNOSTIC, expected["size_bytes"], contents=True)
    require(all(identity[key] == value for key, value in expected.items()), "diagnostic_identity")
    with destination.open("xb") as stream:
        stream.write(body)
    copied, _ = runner._file(destination, expected["size_bytes"])
    require(all(copied[key] == value for key, value in expected.items()), "diagnostic_copy")
    copied_stat, source_stat = destination.stat(), (source / DIAGNOSTIC).stat()
    require(copied_stat.st_nlink == 1
            and (copied_stat.st_dev, copied_stat.st_ino) != (source_stat.st_dev, source_stat.st_ino),
            "diagnostic_alias")
    return copied


def selected_sources(source, destination=None):
    require(0 < len(SOURCE_FILES) <= runner.MAX_SOURCE_FILES, "source_inventory_bound")
    rows, total = [], 0
    for name in SOURCE_FILES:
        row, body = runner._descriptor(source, name, runner.MAX_SOURCE_FILE_BYTES,
                                       contents=destination is not None)
        total += row["size_bytes"]
        require(total <= runner.MAX_SOURCE_TOTAL_BYTES, "source_inventory_bound")
        if destination is not None:
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(body)
            require(runner._descriptor(destination, name, runner.MAX_SOURCE_FILE_BYTES)[0] == row,
                    "source_copy_changed")
        rows.append(row)
    return rows


def verify_encryption_output(attempt, revision):
    public = runner._canonical(attempt / "public", existing=True)
    require({path.name for path in public.iterdir()} == {
        encryption.CIPHERTEXT_NAME, encryption.SUMMARY_NAME}, "public_files")
    summary = _read(public / encryption.SUMMARY_NAME, MAX_PUBLIC_SUMMARY_BYTES)
    count, digest = summary.get("ciphertext_bytes"), summary.get("ciphertext_sha256")
    require(type(count) is int and 0 < count <= MAX_PUBLIC_CIPHERTEXT_BYTES
            and type(digest) is str and re.fullmatch(r"[0-9a-f]{64}", digest), "ciphertext_identity")
    entries = encryption._inventory(attempt / "retention", time.monotonic() + encryption.MAX_RUNTIME_SECONDS)
    expected = encryption._summary(revision, passed=True, entries=entries,
                                   cipher_bytes=count, cipher_digest=digest)
    require(runner._same_json(summary, expected) and count > expected["input_bytes"], "encryption_summary")
    actual, _ = runner._file(public / encryption.CIPHERTEXT_NAME, count)
    require(actual["size_bytes"] == count and actual["sha256"] == digest, "ciphertext_identity")
    terminal = _read(attempt / "encryption-invocation.PRIVATE.log", MAX_PUBLIC_SUMMARY_BYTES)
    require(runner._same_json(summary, terminal), "encryption_terminal")
    return summary


def writers_finished(attempt, stages):
    if any(type(row) is not dict or type(row.get("process_started")) is not bool
           or row.get("cleanup_complete") is not True for row in stages):
        return False
    for stage_name, path in (("input-acquisition", attempt / "acquisition/input-acquisition.json"),
                             ("native-supervisor", attempt / "workspace/evidence/qualified-warm-run.json")):
        active = next((row for row in stages if row["id"] == stage_name), None)
        if active is None or active.get("process_started") is False:
            continue
        try:
            report = _read(path)
            commands = report.get("stages" if stage_name == "native-supervisor" else "commands")
            if report.get("state") != "finished" or type(commands) is not list:
                return False
            if any(type(row) is not dict or type(row.get("process_started")) is not bool
                   or (row["process_started"] and row.get("cleanup_complete") is not True) for row in commands):
                return False
            if stage_name == "native-supervisor":
                for row in commands:
                    child_path = attempt / "workspace/evidence" / runner._relative(row["report_path"])
                    if row["process_started"]:
                        child = _read(child_path, runner.qualified_warm_replay.MAX_REPORT_BYTES,
                                      warm=row["id"] == "qualified-warm")
                        if row["id"] != "preparation" and child.get("state") != "finished":
                            return False
                        child_commands = child.get("commands", [] if row["id"] == "preparation" else None)
                        if type(child_commands) is not list or any(type(command) is not dict
                               or type(command.get("process_started")) is not bool
                               or (command["process_started"] and command.get("cleanup_complete") is not True)
                               for command in child_commands):
                            return False
        except (OSError, ValueError, KeyError, TypeError):
            return False
    return True


def observed_native_execution(attempt, revision):
    try:
        report = _read(attempt / "workspace/evidence/qualified-warm-run.json")
    except (OSError, ValueError):
        return "unknown"
    observed = report.get("native_execution")
    if (report.get("contract_id") == runner.CONTRACT_ID
            and report.get("expected_revision") == revision and report.get("state") == "finished"
            and observed in ("not_run", "unknown", "run")):
        return observed
    return "unknown"


def execute(source, revision, attempt_root):
    previous_umask = os.umask(0o077)
    try:
        return _execute(source, revision, attempt_root)
    finally:
        os.umask(previous_umask)


def _execute(source, revision, attempt_root):
    source = runner._canonical(source, existing=True)
    attempt = runner._canonical(attempt_root)
    require(attempt.parent.is_dir() and not os.path.lexists(attempt)
            and not base._overlap(source, attempt), "attempt_root")
    attempt.mkdir(mode=0o700)
    for name in ("hosted", "hosted/logs", "bootstrap", "home", "tmp", "originals", "retention"):
        (attempt / name).mkdir(mode=0o700)
    environment = dict(os.environ)
    secret = os.environ.pop(URL_VARIABLE, None)
    os.environ.pop("GITHUB_TOKEN", None)
    recipient = environment.get(RECIPIENT_VARIABLE)
    native_success, retained, encrypted = False, False, False
    age = attempt / "bootstrap/age"
    record = {"schema_version": 1, "contract_id": CONTRACT_ID, "expected_revision": revision,
              "state": "running", "outcome": "fail", "stages": [], "failures": [],
              "expected_counts": dict(runner.COMPLETE_COUNTS), "budget": dict(runner.BUDGET),
              "native_execution": "not_run", "orchestration_passed": False,
              "counter_qualification_passed": False, "qualified_warm_passed": False,
              "writers_finished_observed": False, "packaging_passed": False, "encryption_passed": False,
              "selected_sources_before": None, "selected_sources_after": None, "selected_sources_stable": False,
              "retained_sources_root": "hosted/sources", "selected_source_limits": {
                  "files": runner.MAX_SOURCE_FILES, "per_file_bytes": runner.MAX_SOURCE_FILE_BYTES,
                  "total_bytes": runner.MAX_SOURCE_TOTAL_BYTES},
              **dict.fromkeys(dependency.FALSE_CLAIMS, False), "limitations": list(LIMITATIONS)}

    def check_sources():
        if record["selected_sources_before"] is not None:
            record["selected_sources_stable"] = False
            record["selected_sources_after"] = selected_sources(source)
            require(record["selected_sources_after"] == record["selected_sources_before"]
                    and selected_sources(attempt / "hosted/sources") == record["selected_sources_before"],
                    "source_changed")
            record["selected_sources_stable"] = True

    def stage(name, argv, timeout, *, retention=False, extra_environment=None, log=None):
        check_sources()
        child_environment = _environment(attempt)
        child_environment.update(extra_environment or {})
        row = {"id": name, "argv": argv, "process_started": None, "cleanup_complete": False}
        record["stages"].append(row)
        _emit(revision, name, "running")
        try:
            row.update(run_bounded(argv, source, child_environment,
                       log or attempt / "hosted/logs" / (name + ".log"), timeout_seconds=timeout,
                       min_free_bytes=1 if retention else dependency.BUDGET["min_free_bytes"],
                       max_rss_bytes=dependency.BUDGET["max_rss_bytes"],
                       max_log_bytes=dependency.BUDGET["max_log_bytes"], resource_paths=(source, attempt)))
        except BaseException:
            row.update(outcome="fail", cleanup_complete=False)
            raise
        good = (row.get("process_started") is True and row.get("outcome") == "pass"
                and type(row.get("exit_code")) is int and row["exit_code"] == 0
                and row.get("cleanup_complete") is True and row.get("reason") is None)
        check_sources()
        _emit(revision, name, "pass" if good else "fail")
        require(good, "stage_failed")
        return row

    def cli(module, *arguments):
        return [sys.executable, "-B", str(source / "ci/project" / (module + ".py")), *map(str, arguments)]

    try:
        record["selected_sources_before"] = selected_sources(source, attempt / "hosted/sources")
        check_sources()
        require(secret is not None and bool(secret), "control_configuration")
        encryption.validate_recipient(recipient)
        require(environment.get("P06_HOST_SETUP_READY") == "true", "host_setup")
        record["preflight"] = preflight(source, revision, environment, output_parent=attempt / "hosted")
        require(sys.version_info[:3] == (3, 12, 14) and platform.python_implementation() == "CPython"
                and sys.platform == "linux" and platform.machine() == "x86_64"
                and Path(sys.executable).name == "python3", "interpreter")
        age = provision_age(attempt, stage)
        empty = attempt / "bootstrap/recipient-probe-input"
        with empty.open("xb"):
            pass
        stage("recipient-probe", [str(age), "--encrypt", "--recipient", recipient,
              "--output", str(attempt / "bootstrap/recipient-probe.age"), str(empty)], 30, retention=True)
        observed = capacity_gate(source, attempt)
        _write(attempt / "hosted/capacity.json", observed)
        require(observed["gate_satisfied"], "capacity")
        host = provision_host(attempt, stage)
        stage("control-intake", cli("p06_qualified_warm_control", "--output-dir", attempt / "control"), 330,
              extra_environment={URL_VARIABLE: secret})
        secret = None
        control = _read(attempt / "control/control-intake.json")
        require(control.get("original_verified") is True and control.get("outcome") == "pass", "control_receipt")
        record["diagnostic_copy"] = copy_diagnostic(source, attempt / "originals/diagnostic-original.zip")
        paths = ["--source-dir", source, "--expected-revision", revision,
                 "--workspace-dir", attempt / "workspace", "--archive-root", attempt / "archives",
                 "--dependency-repositories", attempt / "repositories",
                 "--diagnostic-archive", attempt / "originals/diagnostic-original.zip",
                 "--control-archive", attempt / "control/control-original.zip"]
        stage("input-acquisition", cli("p06_qualified_warm_inputs", *paths,
              "--output-dir", attempt / "acquisition"), 1200)
        acquired = _read(attempt / "acquisition/input-acquisition.json")
        require(acquired.get("state") == "finished" and acquired.get("outcome") == "pass"
                and acquired.get("expected_revision") == revision, "acquisition_receipt")
        stage("native-supervisor", cli("p06_qualified_warm_run", *paths, "--host-bin", host),
              runner.BUDGET["execution_timeout_seconds"] + 120)
        native = _read(attempt / "workspace/evidence/qualified-warm-run.json")
        record["native_execution"] = native.get("native_execution", "unknown")
        require(native.get("state") == "finished" and native.get("expected_revision") == revision
                and native.get("orchestration_passed") is True
                and native.get("native_execution") == "run"
                and native.get("completed_counts") == runner.COMPLETE_COUNTS, "native_receipt")
        native_success = True
        record["orchestration_passed"] = True
    except (Exception, KeyboardInterrupt) as error:
        record["failures"].append({"stage": "execution", "error_type": type(error).__name__})
    finally:
        secret, environment = None, None
        try:
            check_sources()
        except (Exception, KeyboardInterrupt) as error:
            native_success = False
            record["orchestration_passed"] = False
            record["failures"].append({"stage": "source-closeout", "error_type": type(error).__name__})
        record["state"] = "finished"
        record["writers_finished_observed"] = writers_finished(attempt, record["stages"])
        if not native_success and any(row["id"] == "native-supervisor" and row.get("process_started") is not False
                                      for row in record["stages"]):
            record["native_execution"] = "unknown"
            if record["selected_sources_stable"] and record["writers_finished_observed"]:
                record["native_execution"] = observed_native_execution(attempt, revision)
        try:
            _write(attempt / "hosted/attempt-before-closeout.json", record)
            require(record["writers_finished_observed"], "writers_unresolved")
            extras = []
            for label in ("hosted", "control", "originals", "acquisition"):
                path = attempt / label
                if path.exists():
                    extras.extend(("--extra-root", label + "=" + str(path)))
            stage("packaging", cli("p06_qualified_warm_pack", "success" if native_success else "partial",
                  "--source-dir", source, "--workspace-dir", attempt / "workspace",
                  "--output-dir", attempt / "retention/packet", "--writers-finished", *extras), 600,
                  retention=True, log=attempt / "retention/packaging.log")
            retained = True
        except (Exception, KeyboardInterrupt) as error:
            record["failures"].append({"stage": "packaging", "error_type": type(error).__name__})
        try:
            record["packaging_passed"] = retained
            _write(attempt / "retention/hosted-closeout.json", record)
            # Failed packaging leaves incomplete private bytes in this same selected directory.
            require(record["writers_finished_observed"], "writers_unresolved")
            require(all(row.get("cleanup_complete") is True for row in record["stages"]), "cleanup_unresolved")
            stage("encryption", cli("p06_qualified_warm_encrypt", "--input-dir", attempt / "retention",
                  "--output-dir", attempt / "public", "--recipient", recipient or "",
                  "--age-binary", age, "--expected-revision", revision), 600,
                  retention=True, log=attempt / "encryption-invocation.PRIVATE.log")
            record["encryption_summary"] = verify_encryption_output(attempt, revision)
            encrypted = True
        except (Exception, KeyboardInterrupt) as error:
            record["failures"].append({"stage": "encryption", "error_type": type(error).__name__})
        record.update(outcome="pass" if native_success and retained and encrypted else "fail",
                      packaging_passed=retained, encryption_passed=encrypted)
        _write(attempt / "attempt-final.PRIVATE.json", record)
    return record


class _Parser(argparse.ArgumentParser):
    def error(self, _message):
        raise HostedError("invalid_arguments")


def argument_parser():
    parser = _Parser(description=__doc__, allow_abbrev=False)
    commands = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)
    for command in ("preflight", "run"):
        child = commands.add_parser(command, allow_abbrev=False)
        child.add_argument("--source-dir", required=True, type=Path)
        child.add_argument("--expected-revision", required=True)
        if command == "run":
            child.add_argument("--attempt-root", required=True, type=Path)
    return parser


@terminate_as_interrupt()
def main(argv=None):
    revision, command = None, "invocation"
    try:
        args = argument_parser().parse_args(argv)
        revision, command = args.expected_revision, args.command
        if command == "preflight":
            preflight(args.source_dir, revision)
            passed = True
        else:
            result = execute(args.source_dir, revision, args.attempt_root)
            passed = result["outcome"] == "pass"
            if result["encryption_passed"] is True and os.environ.get("GITHUB_OUTPUT"):
                with open(os.environ["GITHUB_OUTPUT"], "a", encoding="ascii") as output:
                    output.write("encrypted_retention_ready=true\n")
        _emit(revision, command, "pass" if passed else "fail")
        return 0 if passed else 1
    except (Exception, KeyboardInterrupt):
        _emit(revision, command, "fail")
        return 1


if __name__ == "__main__":
    sys.exit(main())
