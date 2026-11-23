# SPDX-License-Identifier: Apache-2.0
"""Bind the hosted preflight envelope without executing its retained contents."""

from __future__ import annotations

import hashlib
from pathlib import PurePosixPath
import re

import p06_managed_preflight_contract as contract
from p06_replay import _fields, _integer, _same, require
import p06_warm_replay as warm_replay


OUTER_FILES = (
    "execution.log", "host-dependencies.log", "job.json", "preparation.json",
    "preparation.log", "python-provision.json", "workflow.yml",
)
PREPARATION_SOURCES = (
    "ci/project/p04_ci_prepare.py", ".github/workflows/p04-model.yml",
    "ci/toolchain_rev.sh", "ci/install_dependencies.sh",
)
PREPARATION_LIMITATIONS = [
    "Cache keys identify restored inputs; actual tool/library hashes are retained separately.",
    "Prepared prerequisites are not numerical execution or phase acceptance.",
    "Native processor RTL remains separate from full-AFU and vendor/physical hardware evidence.",
]
JOB_FIELDS = {
    "GITHUB_SHA", "GITHUB_EVENT_NAME", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT",
    "GITHUB_JOB", "GITHUB_REPOSITORY", "GITHUB_REF", "schema_version", "contract_id",
    "scope", "record_stage", "requested_xlen", "requested_profile", "requested_perf",
    "requested_formats", "requested_policies", "requested_processes", "requested_launches",
    "requested_checked_words", "requested_build_jobs", "requested_simulation_workers",
    "native_execution", "native_preflight_passed", "dependency_compilation_provenance_verified",
    "workflow_sha256", "free_disk_bytes_before_cache", "available_memory_bytes_before_cache",
    *contract.FALSE_CLAIMS,
}


def _valid_hosted_ref(value):
    if type(value) is not str or not 0 < len(value) <= 1024:
        return False
    if re.fullmatch(r"refs/((heads|tags)/[^\s]+|pull/[1-9][0-9]*/merge)", value) is None:
        return False
    if re.search(r"[\x00-\x20\x7f~^:?*\[\\]", value) or ".." in value or "@{" in value:
        return False
    return not value.endswith(".") and all(
        part and not part.startswith(".") and not part.endswith(".lock") for part in value.split("/"))


class HostedReplayMixin:
    quarantine = warm_replay._Replay.quarantine

    def _hosted_preparation(self, outer):
        row = outer.json("preparation.json")
        _fields(row, (
            "schema_version", "contract_id", "outcome", "reason", "native_execution",
            "acceptance_claimed", "expected_revision", "backend", "formats", "toolchain_id",
            "toolchain_cache_key", "third_party_cache_key", "budget", "tools_relocated",
            "limitations", "resources", "tools_dir", "cache_quarantine", "source",
            "tool_identities", "dependency_identities", "preparation_sources",
        ), "hosted preparation")
        expected_tools = {name: item for name, item in self.tools.items() if name != "executing_python"}
        expected = {
            "schema_version": 1, "contract_id": "p04-hosted-preparation-v1",
            "outcome": "pass", "reason": None, "native_execution": "not_run",
            "acceptance_claimed": False, "expected_revision": self.revision,
            "backend": "simx", "formats": list(contract.FORMATS), "tools_relocated": True,
            "tools_dir": str(self.paths["tools"]), "source": self.source["checkout"],
            "tool_identities": expected_tools, "dependency_identities": self.dependencies,
            "budget": {"min_free_bytes": 15 * 1024**3, "max_rss_bytes": 4 * 1024**3,
                       "max_log_bytes": 16 * 1024**2, "jobs": 2},
            "limitations": PREPARATION_LIMITATIONS,
        }
        for name, value in expected.items():
            _same(row[name], value, "hosted preparation " + name)
        require(type(row["toolchain_id"]) is str and re.fullmatch(
            re.escape(self.source["checkout"]["pins"]["TOOLCHAIN_REV"]) + r"-[0-9a-f]{40}",
            row["toolchain_id"]), "preparation toolchain resolution differs from VERSION")
        prefix = "Linux-toolchain-" + row["toolchain_id"] + "-"
        require(row["toolchain_cache_key"] in (prefix + "lite", prefix + "full"),
                "preparation toolchain cache identity differs")
        cache_digest = hashlib.sha256(b"".join(hashlib.sha256(self.source_body(name)).digest()
            for name in ("third_party/Makefile", ".gitmodules"))).hexdigest()
        _same(row["third_party_cache_key"], "Linux-thirdparty-" + cache_digest,
              "preparation dependency cache source identity")
        _fields(row["resources"], ("free_disk_bytes", "available_memory_bytes"), "preparation resources")
        _fields(row["resources"]["free_disk_bytes"], ("source", "workspace"), "preparation disk roots")
        for value in row["resources"]["free_disk_bytes"].values():
            _integer(value, 15 * 1024**3, 2**64 - 1, "preparation disk reserve")
        _integer(row["resources"]["available_memory_bytes"], 4 * 1024**3, 2**64 - 1,
                 "preparation available memory")
        for item in self.inventory(row["preparation_sources"], "preparation sources",
                                   expected=PREPARATION_SOURCES).values():
            _same(item, self.sources[item["path"]], "preparation source descriptor")
        require(type(row["cache_quarantine"]) is dict, "invalid preparation quarantine")
        self.quarantine(row["cache_quarantine"])
        _same(outer.json("preparation.log"), {
            "outcome": "pass", "reason": None, "native_execution": "not_run",
        }, "preparation terminal output")
        return {
            "identity": outer.identity("preparation.json"),
            "toolchain_id": row["toolchain_id"], "toolchain_cache_key": row["toolchain_cache_key"],
            "third_party_cache_key": row["third_party_cache_key"],
            "cache_quarantine_state": row["cache_quarantine"]["state"],
            "dependency_compilation_provenance_verified": False,
        }

    def hosted_identity(self):
        parent = str(PurePosixPath(self.view.prefix.rstrip("/")).parent)
        outer = self.view.archive.view("" if parent == "." else parent)
        nested = PurePosixPath(self.view.prefix.rstrip("/")).name + "/"
        _same(set(outer.files()), set(OUTER_FILES) | {nested + name for name in self.view.files()},
              "complete hosted archive inventory")
        expected_archive_names = {str(PurePosixPath(outer.prefix) / name) for name in outer.files()}
        _same(set(self.view.archive.files()), expected_archive_names, "whole archive hosted inventory")
        job = outer.json("job.json")
        _fields(job, JOB_FIELDS, "hosted job")
        expected = {
            "GITHUB_SHA": self.revision, "GITHUB_REPOSITORY": "baabi-boo/AI-GPU",
            "GITHUB_JOB": "managed-preflight", "schema_version": 1,
            "contract_id": contract.CONTRACT_ID, "scope": "seed-free-managed-counter-preflight",
            "record_stage": "job-initialization", "requested_xlen": 64,
            "requested_profile": "p02-tfr", "requested_perf": "on",
            "requested_formats": list(contract.FORMATS), "requested_policies": list(contract.POLICIES),
            "requested_processes": 4, "requested_launches": 132, "requested_checked_words": 4224,
            "requested_build_jobs": 2, "requested_simulation_workers": 1,
            "native_execution": "not_run", "native_preflight_passed": False,
            "dependency_compilation_provenance_verified": False,
            **dict.fromkeys(contract.FALSE_CLAIMS, False),
        }
        for name, value in expected.items():
            _same(job[name], value, "hosted job " + name)
        _same(job["requested_build_jobs"], self.limits["jobs"], "hosted build parallelism")
        require(job["GITHUB_EVENT_NAME"] in ("push", "pull_request", "workflow_dispatch"),
                "unsupported hosted event")
        for name in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"):
            require(type(job[name]) is str and re.fullmatch(r"[1-9][0-9]{0,20}", job[name]),
                    "invalid hosted run identity")
        require(_valid_hosted_ref(job["GITHUB_REF"]), "invalid hosted Git ref")
        if job["GITHUB_EVENT_NAME"] == "push":
            _same(job["GITHUB_REF"], "refs/heads/master", "hosted push ref")
        elif job["GITHUB_EVENT_NAME"] == "pull_request":
            require(re.fullmatch(r"refs/pull/[1-9][0-9]*/merge", job["GITHUB_REF"]),
                    "hosted pull request ref differs")
        else:
            require(job["GITHUB_REF"].startswith(("refs/heads/", "refs/tags/")),
                    "hosted dispatch ref differs")
        _integer(job["free_disk_bytes_before_cache"], 15 * 1024**3, 2**64 - 1, "hosted initial disk")
        _integer(job["available_memory_bytes_before_cache"], 4 * 1024**3, 2**64 - 1, "hosted initial memory")
        workflow = outer.read("workflow.yml", limit=256 * 1024)
        _same(workflow, self.source_body(".github/workflows/p06-managed-preflight.yml"),
              "hosted workflow source bytes")
        _same(job["workflow_sha256"], hashlib.sha256(workflow).hexdigest(), "hosted workflow identity")
        provision = outer.json("python-provision.json")
        _fields(provision, ("python_version", "implementation", "platform", "executable", "python3_on_path"),
                "hosted Python provision")
        for name, value in (("python_version", [3, 12, 14]), ("implementation", "CPython"),
                            ("platform", "linux"), ("python3_on_path", self.tools["python3"]["path"])):
            _same(provision[name], value, "hosted Python " + name)
        self.api.recorded_absolute(provision["executable"])
        require(provision["executable"] in (
            self.tools["executing_python"]["path"], self.tools["executing_python"]["resolved_path"]),
            "provisioned executable differs from the executing interpreter")
        preparation = self._hosted_preparation(outer)
        _same(outer.json("execution.log"), {
            "outcome": "pass", "reason": None, "report": str(self.paths["output"] / "report.json"),
            "completed_counts": dict(contract.COMPLETE_COUNTS), "native_preflight_passed": True,
            **dict.fromkeys(contract.FALSE_CLAIMS, False),
        }, "hosted execution terminal output")
        outer_files = [outer.identity(name, limit=16 * 1024**2) for name in OUTER_FILES]
        return {
            "validation": "pass", "job": job, "preparation": preparation,
            "outer_files": outer_files, "origin_authenticated": False,
            "host_installation_log_semantics_verified": False,
        }
