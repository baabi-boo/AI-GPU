#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Verify complete managed-preflight archives as inert, externally pinned data.

The original archive and source-manifest digests must come from outside the
packet being checked. Retained commands, modules, binaries and producer paths
are never executed, imported or consulted as local files. A pass establishes
consistency of the retained preflight evidence, not new native execution,
dependency compilation provenance, counter qualification or acceptance.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
import sys

sys.dont_write_bytecode = True

from baseline_process import LIMITATIONS as PROCESS_LIMITATIONS
from p02_matrix_records import PROFILE_SHA256
from p02_wmma_fixtures import load_cases, render_header
from p03_execution_records import qualification_id
import p06_replay as archive_helpers
from p06_replay import ReplayError, require, _fields, _integer, _number, _same, _timestamp
import p06_workspace_replay as common
import p06_managed_preflight_contract as contract_module
import p06_managed_preflight_execute as producer
import p06_managed_preflight_records as records
import p06_managed_preflight_sources as source_inventory
import p06_managed_preflight_derivation as source_derivation
import p06_managed_preflight_generated as generated_inputs
from p06_managed_preflight_replay_build import BuildReplayMixin
from p06_managed_preflight_replay_hosted import HostedReplayMixin
import p06_warm_contract as warm_contract
from p06_warm_execute import validate_process_duration


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_ID = contract_module.CONTRACT_ID
REPLAY_CONTRACT_ID = "p06-managed-counter-preflight-replay-v1"
APP = contract_module.APP
COUNTS = dict(contract_module.COMPLETE_COUNTS)
MAX_PAYLOAD_FILE_BYTES = 64 * 1024**2
MAX_PAYLOAD_BYTES = 256 * 1024**2
REPORT_FIELDS = {
    "acceptance_claimed", "budget", "commands", "completed_counts", "contract_id", "contract_sha256",
    "contract_snapshot", "corpus", "dependencies_after", "dependencies_before", "dependencies_stable",
    "environment", "expected_counts", "expected_processes", "expected_revision", "failures", "finished_at",
    "fixture_snapshot", "full_warm_coverage", "interpreter", "kernel_source_sha256", "limitations",
    "loaded_helpers", "native_execution", "native_preflight_passed", "outcome", "paths", "payload_limits",
    "performance_acceptance", "phase_acceptance", "processes", "profile_sha256", "qualified", "raw_logs",
    "ready_for_warm", "reason", "resources_after", "resources_before", "retained_dependency_payloads",
    "retained_files", "retained_files_stable", "retained_payload_bytes", "retained_sources", "schema_version",
    "scope", "source_after", "source_before", "source_stable", "stability_checks", "started_at", "state",
    "tools_after", "tools_before", "tools_stable", "unresolved_obligations", "variants",
    "warm_contract_sha256", "warm_execution",
}
VARIANT_FIELDS = {
    "application_build_command", "artifacts_after", "artifacts_before", "backend", "backend_build_command",
    "binding", "build_binding_sha256", "build_dir", "compiler_records", "effective_headers",
    "expected_backend_header_macros", "expected_expanded_header_macros", "expected_loaded_libraries",
    "format", "generated_identity", "header_macros", "host_build_records", "id", "model_build_records",
    "outcome", "process_ids", "retained_binary_payloads", "retained_builds",
}
RUNNER_HELPERS = tuple("ci/project/" + name + ".py" for name in (
    "baseline_inventory", "baseline_matrix", "baseline_packet_contract", "baseline_packet_io",
    "baseline_process", "compiler_records", "p02_fixture_oracle", "p02_layout_fixture_oracle",
    "p02_matrix", "p02_matrix_records", "p02_wmma_fixtures", "p02_wmma_numerical_fixture_oracle",
    "p03_execute", "p03_execution_records", "p04_execution_records", "p04_fixture_adapter",
    "p04_model_contract", "p04_reference", "p06_compiler_records", "p06_contract",
    "p06_managed_preflight_build", "p06_managed_preflight_contract", "p06_managed_preflight_execute",
    "p06_managed_preflight_records", "p06_records", "p06_warm_compiler_records", "p06_warm_contract",
    "p06_warm_execute", "p06_warm_records", "p06_workspace_compiler_records", "p06_workspace_records",
    "preflight",
))
READER_MODULES = tuple(sorted(set(archive_helpers.REPLAY_MODULES) | {
    "baseline_inventory", "p02_matrix", "p03_execute", "preflight", "p06_replay",
    "p06_workspace_replay", "p06_workspace_compiler_records", "p06_workspace_execute",
    "p06_workspace_records", "p06_managed_preflight_build", "p06_managed_preflight_contract",
    "p06_managed_preflight_execute", "p06_managed_preflight_records", "p06_managed_preflight_sources",
    "p06_managed_preflight_replay_build", "p06_managed_preflight_replay_hosted",
    "p06_managed_preflight_application_build", "p06_managed_preflight_derivation",
    "p06_managed_preflight_backend_build",
    "p06_managed_preflight_generated",
    "p06_warm_compiler_records", "p06_warm_contract", "p06_warm_execute", "p06_warm_records",
    "p06_warm_analyze", "p06_warm_replay",
}))
LIMITATIONS = [
    "This is retained-data consistency verification, not a new native execution or producer authentication.",
    "Archive, source revision and manifest digests must be obtained independently; matching records do not authenticate GitHub origin.",
    "Every retained source body is checked against the externally supplied inventory; the reader does not independently establish Git object membership.",
    "Retained payload bytes are rehashed and connected to original links and loader observations; cached dependency compilation provenance remains unresolved.",
    "No archive member, producer command or recorded producer path is executed, imported, opened or resolved on this host.",
    "The original checked preflight covers four processes only; complete lifetime qualification and the full warm performance population remain unavailable.",
    "A matching synthetic or consistently forged packet remains synthetic or forged; consistency does not establish actual execution.",
    "Tool identities do not retain every tool payload, system header, compiler support file or loaded system library.",
    "Before/after identity observations do not defend against malicious concurrent producer filesystem writers.",
    "Qualification, warm readiness, warm execution, full warm coverage, performance and phase acceptance remain false.",
    *PROCESS_LIMITATIONS,
]


def _reader_sources():
    rows = []
    modules = [(name, sys.modules.get(name)) for name in READER_MODULES]
    modules.append(("p06_managed_preflight_replay", sys.modules[__name__]))
    for name, module in modules:
        require(module is not None and type(getattr(module, "__file__", None)) is str,
                "required trusted replay module is missing: " + name)
        expected = ROOT / "ci/project" / (name + ".py")
        actual = Path(module.__file__).resolve()
        require(actual == expected, "replay helper loaded outside the trusted repository: " + name)
        body = expected.read_bytes()
        rows.append({"path": "ci/project/" + name + ".py", "sha256": hashlib.sha256(body).hexdigest(),
                     "size_bytes": len(body)})
    rows.append(generated_inputs.trusted_generator_identity())
    return sorted(rows, key=lambda row: row["path"])


TRUSTED_READER_SOURCES = _reader_sources()


def _archive_api():
    """Execute only the verified current helper bytes, never cached bytecode."""
    path = ROOT / archive_helpers.ARCHIVE_READER_PATH
    body = path.read_bytes()
    require(hashlib.sha256(body).hexdigest() == archive_helpers.ARCHIVE_READER_SHA256,
            "trusted archive reader differs from its reviewed source pin")
    spec = importlib.util.spec_from_file_location("p06_managed_trusted_archive_reader", path)
    require(spec is not None, "trusted archive reader is unavailable")
    module = importlib.util.module_from_spec(spec)
    exec(compile(body, str(path), "exec", flags=0, dont_inherit=True,
                 optimize=sys.flags.optimize), module.__dict__)
    return module


class _Replay(BuildReplayMixin, HostedReplayMixin, common._Replay):
    def __init__(self, view, api, revision, expected_sources, expected_derivation):
        self.view, self.api, self.revision = view, api, revision
        self.report = view.json("report.json")
        self.contract = contract_module.load_contract(ROOT)
        self.cases = contract_module.select_cases(self.contract, ROOT)
        self.plan = contract_module.process_plan(self.contract, ROOT)
        self.expected_sources = expected_sources
        self.expected_derivation = expected_derivation
        self.command_index = 0
        self.used_members = {"report.json"}
        self.descriptors, self.bindings = {}, {}
        self.application_builds, self.generated_builds = {}, {}
        self.backend_builds = {}
        self.log_rows, self.process_results, self.recomputed_processes = [], [], []
        self.stability_labels = []
        self.payload_bytes = 0
        self.payload_members = set()

    def verified(self, row, expected=None):
        body = self.view.verified(row, expected)
        self._remember(row)
        return body

    def _remember(self, row):
        if row["path"] in self.descriptors:
            _same(row, self.descriptors[row["path"]], "repeated retained descriptor")
        self.descriptors[row["path"]] = row
        self.used_members.add(row["path"])

    def payload(self, row, expected=None):
        self.api.descriptor(row)
        require(expected is None or row["path"] == expected, "binary payload path differs")
        _integer(row["size_bytes"], 1, MAX_PAYLOAD_FILE_BYTES, "retained binary payload size")
        _same(self.view.identity(row["path"], limit=MAX_PAYLOAD_FILE_BYTES), row, "retained binary payload")
        self._remember(row)
        if row["path"] not in self.payload_members:
            self.payload_members.add(row["path"])
            self.payload_bytes += row["size_bytes"]
            require(self.payload_bytes <= MAX_PAYLOAD_BYTES, "retained binary payload total exceeds its bound")
        return row

    def budget(self):
        value = self.report["budget"]
        _fields(value, contract_module.BUDGET, "budget")
        for name in ("max_rss_bytes", "min_free_bytes", "max_log_bytes", "threads", "hosted_job_minutes"):
            _same(value[name], contract_module.BUDGET[name], "budget." + name)
        _integer(value["jobs"], 1, 2, "build jobs")
        times = value["timeouts_seconds"]
        _fields(times, ("configure", "build", "run"), "command timeouts")
        _integer(times["build"], 1, 1800, "build timeout")
        _integer(times["run"], 1, 180, "run timeout")
        _same(times["configure"], min(120, times["build"]), "configure timeout")
        self.limits = {key: value[key] for key in ("jobs", "max_rss_bytes", "max_log_bytes", "min_free_bytes")}
        self.limits.update({key + "_timeout_seconds": item for key, item in times.items()})
        for name in ("resources_before", "resources_after"):
            resource = self.report[name]
            _fields(resource, ("available_memory_bytes", "free_disk_bytes"), name)
            _fields(resource["free_disk_bytes"], ("source", "tools", "work", "output"), name + " roots")
            for free in resource["free_disk_bytes"].values():
                _integer(free, value["min_free_bytes"], (1 << 64) - 1, name + " disk reserve")
            if resource["available_memory_bytes"] is not None:
                _integer(resource["available_memory_bytes"], 0, (1 << 64) - 1, name + " available memory")
        memory = self.report["resources_before"]["available_memory_bytes"]
        _integer(memory, value["max_rss_bytes"], (1 << 64) - 1, "initial memory reserve")
        _same(self.report["payload_limits"], {"per_file_bytes": MAX_PAYLOAD_FILE_BYTES,
                                             "total_bytes": MAX_PAYLOAD_BYTES}, "payload limits")

    def provenance(self):
        self.source = self.document("source_before", "source-before")
        self.tools = self.document("tools_before", "tools-before")
        self.dependencies = self.document("dependencies_before", "dependencies-before")
        for name, original in (("source", self.source), ("tools", self.tools), ("dependencies", self.dependencies)):
            _same(self.report[name + "_stable"], True, name + " stability")
            _same(self.document(name + "_after", name + "-after"), original, name + " original/final")
        _fields(self.source, ("checkout", "files"), "source snapshot")
        checkout = self.source["checkout"]
        _fields(checkout, ("revision", "tree", "dirty", "changed_paths", "untracked_paths", "submodules",
                           "pins", "blockers", "inputs", "outcome"), "source checkout")
        for name, expected in (("revision", self.revision), ("dirty", False), ("changed_paths", []),
                               ("untracked_paths", []), ("blockers", []), ("outcome", "pass")):
            _same(checkout[name], expected, "checkout." + name)
        require(type(checkout["tree"]) is str and archive_helpers.REVISION.fullmatch(checkout["tree"]),
                "invalid recorded source tree")
        submodules = checkout["submodules"]
        _fields(submodules, ("declared_count", "entries", "errors"), "submodule inventory")
        _same(submodules["errors"], [], "submodule errors")
        _integer(submodules["declared_count"], 1, 1000, "declared submodules")
        require(type(submodules["entries"]) is list
                and submodules["declared_count"] <= len(submodules["entries"]) <= 1000,
                "submodule inventory is incomplete or excessive")
        names = []
        for row in submodules["entries"]:
            _fields(row, ("path", "revision", "status"), "submodule")
            self.api.relative_name(row["path"])
            require(row["path"] not in names and type(row["revision"]) is str
                    and archive_helpers.REVISION.fullmatch(row["revision"]), "invalid submodule identity")
            names.append(row["path"])
            _same(row["status"], "initialized", "submodule state")
        _same(names, sorted(names), "submodule order")
        source_inventory.validate_retained_sources(self.source["files"], self.expected_sources,
                                                   expected_revision=self.revision)
        self.sources = self.inventory(self.source["files"], "source files", sorted_paths=True)
        retained = [dict(row, path="artifacts/source/" + row["path"]) for row in self.source["files"]]
        _same(self.report["retained_sources"], retained, "retained source descriptors")
        for row in retained:
            self.verified(row)
        self.derivation = source_derivation.validate_retained_derivation(self.expected_derivation,
            checkout=checkout, source_body=self.source_body)
        common._check_declared_submodules(self.source_body(".gitmodules"), submodules, self.api)
        for row in self.inventory(checkout["inputs"], "checkout inputs", expected=archive_helpers.SOURCE_INPUTS).values():
            _same(row, self.sources[row["path"]], "checkout input identity")
        helpers = self.inventory(self.report["loaded_helpers"], "executing helpers", expected=RUNNER_HELPERS)
        for row in helpers.values():
            _same(row, self.sources[row["path"]], "executing helper identity")
        version = {}
        for line in self.source_body("VERSION").decode("utf-8").splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            match = re.fullmatch(r"(VORTEX_VERSION|TOOLCHAIN_REV|GEM5_REV|FIRESIM_REV)=([A-Za-z0-9][A-Za-z0-9._+-]*)", line)
            require(match is not None and match[1] not in version, "invalid retained version pin")
            version[match[1]] = match[2]
        _fields(version, ("VORTEX_VERSION", "TOOLCHAIN_REV", "GEM5_REV", "FIRESIM_REV"), "version pins")
        _same(checkout["pins"], version, "checkout pins")
        _same(self.report["contract_sha256"], qualification_id(self.contract), "contract identity")
        _same(self.document("contract_snapshot", "contract"), self.contract, "contract snapshot")
        _same(self.document("fixture_snapshot", "selected-fixtures"), self.cases, "selected independent fixtures")
        corpus = self.inventory(self.report["corpus"], "fixture corpus", expected=common.CORPUS)
        for name, row in corpus.items():
            _same(row, self.sources[name], "fixture descriptor")
            _same(self.source_body(name), (ROOT / name).read_bytes(), "trusted independent fixture bytes")
        _same(self.source_body(common.CORPUS[-1]), render_header(load_cases(ROOT)), "independent fixture header")
        old_bytes = self.source_body("ci/project/p06_warm_contract.json")
        _same(hashlib.sha256(old_bytes).hexdigest(), contract_module.WARM_CONTRACT_SHA256,
              "unchanged historical warm contract")
        for path, digest, field in (("profiles/p02-tfr.json", PROFILE_SHA256, "profile_sha256"),
            ("sw/kernel/ai/matmul.cpp", producer.KERNEL_SHA256, "kernel_source_sha256"),
            ("ci/project/p06_warm_contract.json", contract_module.WARM_CONTRACT_SHA256, "warm_contract_sha256")):
            _same(self.sources[path]["sha256"], digest, "frozen " + path)
            _same(self.report[field], digest, "reported " + path)
        self.inventory(self.dependencies, "dependencies", expected=archive_helpers.DEPENDENCIES)
        payloads = [dict(row, path="artifacts/dependencies/" + row["path"]) for row in self.dependencies]
        _same(self.report["retained_dependency_payloads"], payloads, "retained dependency payloads")
        for row in payloads:
            self.payload(row)

    def paths_and_tools(self):
        _fields(self.report["paths"], ("source", "tools", "work", "output", "host_bin", "verilator"), "paths")
        self.paths = {key: self.api.recorded_absolute(value) if value is not None else None
                      for key, value in self.report["paths"].items()}
        require(all(self.paths[key] is not None for key in ("source", "tools", "work", "output", "verilator")),
                "missing execution root")
        for key in ("work", "output"):
            path = self.paths[key]
            require(not any(path == other or path in other.parents or other in path.parents
                            for name, other in self.paths.items()
                            if name in ("source", "tools", "work", "output") and name != key), "execution roots overlap")
        _same(self.paths["verilator"], self.paths["tools"] / "verilator", "unused Verilator default")
        _fields(self.tools, set(archive_helpers.HOST_TOOLS) | set(archive_helpers.TOOL_SUFFIXES)
                | {"executing_python"}, "tools")
        for key, row in self.tools.items():
            _fields(row, ("path", "resolved_path", "sha256", "size_bytes"), "tool " + key)
            self.api.recorded_absolute(row["path"])
            self.api.recorded_absolute(row["resolved_path"])
            require(type(row["sha256"]) is str and archive_helpers.SHA256.fullmatch(row["sha256"]), "invalid tool digest")
            _integer(row["size_bytes"], 1, (1 << 64) - 1, "tool bytes")
            if key in archive_helpers.TOOL_SUFFIXES:
                _same(row["path"], str(self.paths["tools"] / archive_helpers.TOOL_SUFFIXES[key]), "selected tool " + key)
        _same(self.report["interpreter"], {"version": [3, 12, 14], "implementation": "CPython",
                                           "platform": "linux"}, "executing interpreter")
        for key in ("resolved_path", "sha256", "size_bytes"):
            _same(self.tools["python3"][key], self.tools["executing_python"][key], "executing Python " + key)
        env = self.report["environment"]
        require(type(env) is dict, "sanitized environment is not an object")
        expected = {"PATH": env.get("PATH"), "TMPDIR": str(self.paths["work"] / "tmp"),
            "HOME": str(self.paths["work"] / "home"), "LANG": "C", "LC_ALL": "C", "TZ": "UTC",
            "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1", "CCACHE_DISABLE": "1", "OBJCACHE": "",
            "MAKEFLAGS": "-j" + str(self.limits["jobs"]), "THREADS": "1",
            "CMAKE_BUILD_PARALLEL_LEVEL": str(self.limits["jobs"])}
        _same(env, expected, "sanitized environment")
        require(type(env["PATH"]) is str and 0 < len(env["PATH"]) <= 16384, "invalid PATH")
        paths = env["PATH"].split(":")
        for path in paths:
            self.api.recorded_absolute(path)
        host = [str(self.paths["host_bin"])] if self.paths["host_bin"] else []
        interpreter = str(PurePosixPath(self.tools["python3"]["path"]).parent)
        _same(paths, list(dict.fromkeys([*host, interpreter, "/usr/bin", "/bin"])), "bounded PATH")
        for key in archive_helpers.HOST_TOOLS:
            path = PurePosixPath(self.tools[key]["path"])
            require(path.name == key and str(path.parent) in paths, "host tool escaped bounded PATH")
        self.env = env

    def command(self, command_id, argv, cwd, environment, timeout, *, read=False, native_process=False):
        require(self.command_index < len(self.report["commands"]), "missing planned command")
        row = self.report["commands"][self.command_index]
        self.command_index += 1
        _fields(row, archive_helpers.COMMAND_FIELDS | {"native_process"}, "command " + command_id)
        for key, expected in (("id", command_id), ("argv", [str(arg) for arg in argv]), ("cwd", str(cwd)),
            ("environment", environment), ("timeout_seconds", timeout), ("outcome", "pass"), ("exit_code", 0),
            ("reason", None), ("process_started", True), ("cleanup_complete", True),
            ("native_process", native_process), ("limitations", list(PROCESS_LIMITATIONS)),
            ("log", "logs/" + command_id + ".log")):
            _same(row[key], expected, "command " + command_id + "." + key)
        _number(row["duration_seconds"], 0, timeout + 10, "command duration")
        _integer(row["peak_rss_bytes"], 0, self.limits["max_rss_bytes"], "command peak RSS")
        _integer(row["log_size_bytes"], 0, self.limits["max_log_bytes"], "command log size")
        descriptor = {"path": row["log"], "sha256": row["log_sha256"], "size_bytes": row["log_size_bytes"]}
        body = self.verified(descriptor)
        self.log_rows.append(descriptor)
        self.stability_labels.extend(("before-command-" + command_id, "after-command-" + command_id))
        return (body.decode("utf-8") if read else None), row

    def processes(self):
        for planned in (row for row in self.plan if row["format"] == self.fmt):
            row = self.report["processes"][len(self.process_results)]
            _fields(row, set(planned) | {"binding", "command_id", "log", "observation", "outcome",
                "execution_binding_sha256", "build_binding_sha256", "process_duration_seconds",
                "retained_observation"}, "process")
            for key, expected in planned.items():
                _same(row[key], expected, "process." + key)
            _same(row["outcome"], "pass", "process outcome")
            process_id = planned["id"]
            binding = {"contract_id": CONTRACT_ID, "contract_sha256": self.report["contract_sha256"],
                "build_binding_sha256": self.build_id, "build": self.bindings[self.variant_id], "process": planned}
            actual = self.api.strict_json(self.verified(row["binding"], "snapshots/" + process_id + "-binding.json"))
            _same(actual, binding, "reconstructed process binding")
            binding_id = qualification_id(binding)
            for key, expected in (("execution_binding_sha256", binding_id), ("build_binding_sha256", self.build_id),
                ("command_id", process_id), ("log", "logs/" + process_id + ".log")):
                _same(row[key], expected, "process " + key)
            app = self.build / APP
            text, receipt = self.command(process_id, [app / "ai_counter_preflight", "--policy", planned["policy"],
                "--module", app / "kernel.vxbin", "--qualification-id", binding_id,
                "--sample-id", planned["sample_id"], "--pair-index", "0", "--phase", "warmup"], app,
                dict(self.env, VORTEX_DRIVER="simx", LD_LIBRARY_PATH=str(self.build / "sw/runtime")),
                self.limits["run_timeout_seconds"], read=True, native_process=True)
            _same(row["process_duration_seconds"], receipt["duration_seconds"], "supervisor duration")
            observed = records.verify_output(text, contract=self.contract, case=self.case, fmt=self.fmt,
                policy=planned["policy"], binding_id=binding_id, sample_id=planned["sample_id"],
                process_id=process_id, expected_libraries=self.libraries)
            _same(row["observation"], observed, "recomputed original output")
            retained = self.api.strict_json(self.verified(row["retained_observation"],
                "snapshots/" + process_id + "-observation.json"))
            _same(retained, observed, "separate retained original observation")
            validate_process_duration(observed["warm"], receipt["duration_seconds"], warm_contract.load_contract(ROOT))
            self.recomputed_processes.append({"outcome": "pass", "observation": observed})
            witness = observed["witness"]
            self.process_results.append({"id": process_id, "format": self.fmt, "policy": planned["policy"],
                "execution_binding_sha256": binding_id, "build_binding_sha256": self.build_id,
                "launches": sum(item["dispatch"]["launches"] for item in observed["warm"]["operations"]),
                "checked_words": sum(item["checked"] for item in observed["warm"]["operations"]),
                "snapshots": len(witness["snapshots"]), "half_replies": len(witness["reads"]),
                "cache_flush_reads": len(witness["cache_flush_reads"]),
                "dcr_reads": witness["observation"]["dcr_read_completed"],
                "loaded_libraries": witness["loaded_libraries"]})
            self.stability_labels.append("after-process-" + process_id)

    def stability(self):
        checks = self.report["stability_checks"]
        require(type(checks) is list and len(checks) == len(self.stability_labels), "missing stability observations")
        previous = self.started
        for check, label in zip(checks, self.stability_labels):
            _fields(check, ("at", "label", "source_sha256", "tools_sha256", "dependencies_sha256"), "stability observation")
            _same(check["label"], label, "stability order")
            at = _timestamp(check["at"])
            require(previous <= at <= self.finished, "stability timestamps are outside chronology")
            previous = at
            for name, value in (("source", self.source), ("tools", self.tools), ("dependencies", self.dependencies)):
                _same(check[name + "_sha256"], qualification_id(value), "stability identity " + name)

    def run(self):
        _fields(self.report, REPORT_FIELDS, "managed preflight report")
        for key, expected in (("schema_version", 1), ("contract_id", CONTRACT_ID),
            ("scope", "seed-free-managed-counter-preflight"), ("state", "finished"), ("outcome", "pass"),
            ("reason", None), ("failures", []), ("native_execution", "run"), ("native_preflight_passed", True),
            ("expected_revision", self.revision), ("expected_counts", COUNTS), ("completed_counts", COUNTS),
            ("expected_processes", self.plan), ("unresolved_obligations", list(contract_module.UNRESOLVED_OBLIGATIONS)),
            ("retained_files_stable", True), ("limitations", producer.LIMITATIONS)):
            _same(self.report[key], expected, "report." + key)
        for name in contract_module.FALSE_CLAIMS:
            _same(self.report[name], False, "report." + name)
        self.started, self.finished = (_timestamp(self.report[key]) for key in ("started_at", "finished_at"))
        require(self.started <= self.finished, "execution timestamps are reversed")
        require(type(self.report["commands"]) is list and len(self.report["commands"]) == 35,
                "unexpected command inventory")
        require(type(self.report["variants"]) is list and len(self.report["variants"]) == 2, "expected two format builds")
        require(type(self.report["processes"]) is list and len(self.report["processes"]) == 4,
                "expected exactly four managed processes")
        self.budget()
        self.provenance()
        self.paths_and_tools()
        for name in ("g++", "gcc", "make", "python3", "executing_python", "clang", "riscv-gcc"):
            text, _ = self.command("version-" + name.replace("+", "p"), [self.tools[name]["path"], "--version"],
                self.paths["work"], self.env, 30, read=True)
            require(text.strip(), "empty version observation")
            if name in ("python3", "executing_python"):
                _same(text, "Python 3.12.14\n", "executing interpreter version output")
        for self.variant, self.fmt in zip(self.report["variants"], contract_module.FORMATS):
            self.variant_id = "simx-" + self.fmt
            self.build = self.paths["work"] / self.variant_id
            self.case = next(case for case in self.cases if case["format"] == self.fmt)
            _fields(self.variant, VARIANT_FIELDS, "variant")
            for key, expected in (("id", self.variant_id), ("backend", "simx"), ("format", self.fmt),
                ("outcome", "pass"), ("build_dir", str(self.build)),
                ("process_ids", [row["id"] for row in self.plan if row["format"] == self.fmt])):
                _same(self.variant[key], expected, "variant." + key)
            self.generated()
            self.compiler_commands()
            self.application_builds[self.variant_id] = self.application_build
            self.backend_builds[self.variant_id] = self.backend_build
            self.generated_builds[self.variant_id] = {"headers": self.generated_headers, "flags": self.generated_flags}
            self.build_binding()
            self.processes()
            self.stability_labels.append("after-variant-" + self.variant_id)
        _same(self.command_index, len(self.report["commands"]), "unexpected trailing command")
        _same(self.report["raw_logs"], self.log_rows, "original raw-log inventory")
        counts = producer.completion_counts(self.recomputed_processes)
        _same(counts, COUNTS, "recomputed complete counts")
        _same(self.report["retained_payload_bytes"], self.payload_bytes, "total retained payload bytes")
        self.stability()
        retained = self.inventory(self.report["retained_files"], "complete retained inventory")
        logs = {row["path"] for row in self.log_rows}
        expected_retained = {name: row for name, row in self.descriptors.items() if name not in logs}
        _same(retained, expected_retained, "complete semantically bound retained inventory")
        _same(set(self.view.files()), self.used_members, "complete managed packet member inventory")
        hosted = self.hosted_identity()
        return {"schema_version": 1, "contract_id": REPLAY_CONTRACT_ID,
            "scope": "complete-seed-free-managed-preflight-retained-data-replay", "outcome": "pass",
            "native_execution": "not_run", "retained_code_executed": False,
            "dependency_compilation_provenance_verified": False,
            **dict.fromkeys(contract_module.FALSE_CLAIMS, False),
            "unresolved_obligations": list(contract_module.UNRESOLVED_OBLIGATIONS),
            "source_revision": self.revision, "source_tree": self.source["checkout"]["tree"],
            "source_snapshot_sha256": qualification_id(self.source), "report_identity": self.view.identity("report.json"),
            "source_derivation": self.derivation,
            "commands_checked": self.command_index, "retained_source_files_checked": len(self.sources),
            "retained_payload_files_checked": len(self.payload_members), "retained_payload_bytes_checked": self.payload_bytes,
            "retained_files_checked": len(retained), "counts": counts, "processes": self.process_results,
            "build_binding_ids": {name: qualification_id(value) for name, value in self.bindings.items()},
            "application_builds": self.application_builds, "generated_builds": self.generated_builds,
            "backend_builds": self.backend_builds,
            "hosted_identity": hosted, "limitations": list(LIMITATIONS)}


def replay_archive(path, sha256, *, expected_revision, source_inventory_path,
                   source_inventory_sha256, source_derivation_path, source_derivation_sha256,
                   prefix="managed-preflight"):
    """Check a complete original against independently supplied expectations."""
    require(type(expected_revision) is str and archive_helpers.REVISION.fullmatch(expected_revision),
            "invalid external source revision")
    _same(_reader_sources(), TRUSTED_READER_SOURCES, "trusted replay source stability since import")
    expected = source_inventory.load_source_inventory(source_inventory_path,
        expected_sha256=source_inventory_sha256, expected_revision=expected_revision)
    derivation = source_derivation.load_source_derivation(source_derivation_path,
        expected_sha256=source_derivation_sha256, expected_revision=expected_revision,
        source_inventory=expected, source_inventory_sha256=source_inventory_sha256)
    api = _archive_api()
    try:
        with api.ArchiveReader(path, sha256) as archive:
            result = _Replay(archive.view(prefix), api, expected_revision, expected, derivation).run()
            result["archive_read"] = archive.receipt()
            result["source_inventory_sha256"] = source_inventory_sha256
            result["source_derivation_sha256"] = source_derivation_sha256
            result["trusted_archive_reader"] = {"path": archive_helpers.ARCHIVE_READER_PATH,
                                                "sha256": archive_helpers.ARCHIVE_READER_SHA256}
            _same(_reader_sources(), TRUSTED_READER_SOURCES, "trusted replay source stability")
            result["trusted_replay_sources"] = [dict(row) for row in TRUSTED_READER_SOURCES]
            return result
    except (KeyError, TypeError, IndexError, UnicodeError, OverflowError, RecursionError) as error:
        raise ReplayError("malformed retained managed preflight packet: " + str(error)) from error


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--source-inventory", type=Path, required=True)
    parser.add_argument("--source-inventory-sha256", required=True)
    parser.add_argument("--source-derivation", type=Path, required=True)
    parser.add_argument("--source-derivation-sha256", required=True)
    parser.add_argument("--prefix", default="managed-preflight")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = replay_archive(args.archive, args.sha256, expected_revision=args.source_revision,
            source_inventory_path=args.source_inventory, source_inventory_sha256=args.source_inventory_sha256,
            source_derivation_path=args.source_derivation, source_derivation_sha256=args.source_derivation_sha256,
            prefix=args.prefix)
        body = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
        if args.output:
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(body)
            print(json.dumps({"contract_id": REPLAY_CONTRACT_ID, "outcome": "pass", "counts": result["counts"],
                "report": str(args.output), "native_execution": "not_run", "retained_code_executed": False,
                **dict.fromkeys(contract_module.FALSE_CLAIMS, False)}, sort_keys=True))
        else:
            print(body, end="")
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({"contract_id": REPLAY_CONTRACT_ID, "outcome": "fail", "reason": str(error),
            "native_execution": "not_run", "retained_code_executed": False,
            "dependency_compilation_provenance_verified": False,
            **dict.fromkeys(contract_module.FALSE_CLAIMS, False)}, sort_keys=True))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
