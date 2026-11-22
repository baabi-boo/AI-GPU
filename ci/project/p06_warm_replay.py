#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Recheck a digest-pinned warm study without executing retained code."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import sys

from baseline_packet_contract import _stamp_flags
from p02_matrix_records import DISABLED, PROFILE_SHA256
from p02_wmma_fixtures import load_cases, render_header
from p03_execution_records import qualification_id
import p06_replay as archive_helpers
from p06_replay import ReplayError, require, _fields, _integer, _same, _timestamp
from p06_compiler_records import validate_header_macros
from p06_warm_analyze import analyze_processes
from p06_warm_compiler_records import validate_records, validate_effective_header
from p06_warm_contract import CONTRACT_ID, MANIFEST_PATH, load_contract, select_cases, process_plan
from p06_warm_records import verify_output
import p06_workspace_replay as common


ROOT = Path(__file__).resolve().parents[2]
APP = "tests/regression/ai_warm_workspace"
HEADER_PROBE = "p06-warm-header-check/include-probe.cpp"
KERNEL_SHA256 = "ad3b6107f0eef91ec676412bc795ab70cd1c9f31647b2cea854de6234fe71d3e"
GENERATED, COPIED = archive_helpers.GENERATED, archive_helpers.COPIED
SOURCE_INPUTS, CORPUS = archive_helpers.SOURCE_INPUTS, common.CORPUS
COUNTS = {"processes": 24, "launches": 792, "checked_words": 25344}
REPORT_FIELDS = common.REPORT_FIELDS | {"hypothesis_evaluation", "measured_processes", "measured_operations"}
RUNNER_HELPERS = tuple("ci/project/" + name + ".py" for name in (
    "baseline_inventory", "baseline_matrix", "baseline_packet_contract", "baseline_packet_io",
    "baseline_process", "compiler_records", "p02_fixture_oracle", "p02_layout_fixture_oracle",
    "p02_matrix", "p02_matrix_records", "p02_wmma_fixtures", "p02_wmma_numerical_fixture_oracle",
    "p03_execute", "p03_execution_records", "p04_execution_records", "p04_fixture_adapter",
    "p04_model_contract", "p04_reference", "p06_compiler_records", "p06_contract", "p06_records",
    "p06_warm_compiler_records", "p06_warm_contract", "p06_warm_execute", "p06_warm_records",
    "p06_workspace_compiler_records", "p06_workspace_records", "preflight",
))
PREPARATION_SOURCES = ("ci/project/p04_ci_prepare.py", ".github/workflows/p04-model.yml",
                       "ci/toolchain_rev.sh", "ci/install_dependencies.sh")
LIMITATIONS = [
    "This is retained-data verification; native_execution is not_run and no performance or phase is accepted.",
    "The externally supplied ZIP digest and source revision do not authenticate producer honesty or prove GPU execution.",
    "Retained source bodies, hashes and clean checkout observations are checked for consistency; Git object membership is not independently authenticated here.",
    "No archive member, retained helper, binary, command or recorded absolute path is executed or opened as local source.",
    "Binaries, toolchains, dependencies and quarantined cache products are identities, not executable replay payloads.",
    "Host time includes fixed allocation-observer bookkeeping and numerical validation, not physical-device latency.",
    "RV64 host MPM counter differences are unqualified low-32-bit observations; positive monotonic values do not prove no wrap or true paired modeled-cycle comparisons.",
    "Requested tensor bytes and simulator allocator observations do not establish physical memory reclamation.",
    "Replay pass and exit zero establish retained-data consistency only; full hypothesis qualification remains blocked regardless of conditional host-time and reported-counter predicates.",
]


def _artifacts():
    return tuple(sorted(set((*GENERATED, *COPIED, HEADER_PROBE, "sw/kernel/libvortex2.a",
        *(APP + "/" + name for name in ("Makefile", "config.stamp", "ai_warm_workspace", "kernel.elf", "kernel.vxbin")),
        "sw/runtime/libvortex.so", "sw/runtime/libvortex-simx.so", "sw/runtime/libsimx.so",
        "sw/runtime/simx_rt_config.stamp", "sw/runtime/simx_config.stamp"))))


class _Replay(common._Replay):
    def __init__(self, view, api, revision):
        self.view, self.api, self.revision = view, api, revision
        self.driver, self.variant_id = "simx", "simx-fp16"
        self.report = view.json("report.json")
        self.contract = load_contract(ROOT)
        self.cases = select_cases(self.contract, ROOT)
        self.plan = process_plan(self.contract)
        self.command_index = 0
        self.used_members = {"report.json"}
        self.log_rows, self.process_results = [], []
        self.raw_logs, self.bindings = {}, {}

    def provenance(self):
        self.source = self.document("source_before", "source-before")
        self.tools = self.document("tools_before", "tools-before")
        self.dependencies = self.document("dependencies_before", "dependencies-before")
        for name, original in (("source", self.source), ("tools", self.tools), ("dependencies", self.dependencies)):
            _same(self.report[name + "_stable"], True, name + " stable")
            _same(self.document(name + "_after", name + "-after"), original, name + " original/final")
        _fields(self.source, ("checkout", "files"), "source snapshot")
        checkout = self.source["checkout"]
        _fields(checkout, ("revision", "tree", "dirty", "changed_paths", "untracked_paths", "submodules",
                           "pins", "blockers", "inputs", "outcome"), "source checkout")
        for name, expected in (("revision", self.revision), ("dirty", False), ("changed_paths", []),
                               ("untracked_paths", []), ("blockers", []), ("outcome", "pass")):
            _same(checkout[name], expected, "checkout." + name)
        require(type(checkout["tree"]) is str and archive_helpers.REVISION.fullmatch(checkout["tree"]),
                "invalid source tree")
        submodules = checkout["submodules"]
        _fields(submodules, ("declared_count", "entries", "errors"), "submodule inventory")
        _same(submodules["errors"], [], "submodule errors")
        _integer(submodules["declared_count"], 1, 1000, "declared submodules")
        require(type(submodules["entries"]) is list
                and submodules["declared_count"] <= len(submodules["entries"]) <= 1000,
                "submodule inventory is incomplete or excessive")
        seen = set()
        for row in submodules["entries"]:
            _fields(row, ("path", "revision", "status"), "submodule")
            self.api.relative_name(row["path"])
            require(row["path"] not in seen and type(row["revision"]) is str
                    and archive_helpers.REVISION.fullmatch(row["revision"]), "invalid submodule identity")
            seen.add(row["path"])
            _same(row["status"], "initialized", "submodule state")
        self.sources = self.inventory(self.source["files"], "source files", sorted_paths=True)
        retained = [dict(row, path="artifacts/source/" + row["path"]) for row in self.source["files"]]
        _same(self.report["retained_sources"], retained, "retained source descriptors")
        for row in retained:
            self.verified(row)
        required = set(RUNNER_HELPERS) | set(SOURCE_INPUTS) | set(COPIED) | set(CORPUS) | {
            MANIFEST_PATH, ".github/workflows/p06-warm-workspace.yml", *PREPARATION_SOURCES, "third_party/Makefile",
            "profiles/p02-tfr.json", "sw/kernel/ai/matmul.cpp", "sw/runtime/ai/runtime.cpp",
            "sw/runtime/ai/runtime.h", "sw/runtime/ai/contract.cpp", "sw/runtime/ai/contract.h",
            "sw/common/ai_matmul_args.h", "sw/common/ai_matmul_profile.h", "sw/runtime/include/vortex2.h",
            "sim/rtlsim/verilator.vlt.in", "tests/regression/ai_bench_common/counters.h",
            "docs/designs/warm_workspace_benchmark_v1.md", "docs/designs/serial_matmul_workspace_v1.md",
            "docs/designs/ai_operator_contract_v1.md", "docs/designs/tensor_numerics_v1.md",
            *(APP + "/" + name for name in ("main.cpp", "observer.cpp", "observer.h", "Makefile")),
        }
        require(required <= set(self.sources), "missing required source inventory")
        common._check_declared_submodules(self.source_body(".gitmodules"), submodules, self.api)
        for row in self.inventory(checkout["inputs"], "checkout inputs", expected=SOURCE_INPUTS).values():
            _same(row, self.sources[row["path"]], "checkout input identity")
        for row in self.inventory(self.report["loaded_helpers"], "executing helpers", expected=RUNNER_HELPERS).values():
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
        manifest = self.source_body(MANIFEST_PATH)
        _same(self.api.strict_json(manifest, integers_only=True), self.contract, "retained contract")
        _same(self.report["contract_sha256"], hashlib.sha256(manifest).hexdigest(), "manifest identity")
        _same(self.document("contract_snapshot", "contract"), self.contract, "contract snapshot")
        _same(self.document("fixture_snapshot", "selected-fixtures"), self.cases, "selected independent fixtures")
        corpus = self.inventory(self.report["corpus"], "fixture corpus", expected=CORPUS)
        for name, row in corpus.items():
            _same(row, self.sources[name], "fixture descriptor")
            _same(self.source_body(name), (ROOT / name).read_bytes(), "trusted independent fixture bytes")
        _same(self.source_body(CORPUS[-1]), render_header(load_cases(ROOT)), "independent fixture header")
        for row in self.contract["source_inputs"]:
            require(row["path"] in self.sources, "missing frozen source input")
            _same(self.sources[row["path"]]["sha256"], row["sha256"], "frozen " + row["path"])
        for key, expected in (("profile_sha256", PROFILE_SHA256), ("kernel_source_sha256", KERNEL_SHA256)):
            _same(self.report[key], expected, key)
        self.inventory(self.dependencies, "dependencies", expected=archive_helpers.DEPENDENCIES)

    def generated(self):
        row = self.variant
        self.frozen = self.inventory(row["artifacts_before"], "frozen artifacts", expected=_artifacts())
        for value in self.frozen.values():
            _integer(value["size_bytes"], 1, self.api.MEMBER_BYTES, "frozen artifact bytes")
        _same(row["artifacts_after"], row["artifacts_before"], "artifact stability")
        for value in self.inventory(row["generated_identity"], "generated identity", expected=GENERATED + COPIED).values():
            _same(value, self.frozen[value["path"]], "generated file identity")
        stages = row["retained_builds"]
        require(type(stages) is list and len(stages) == 4, "missing retained build stages")
        names = [name for name in self.frozen if name.endswith((".stamp", ".mk", ".h", ".vh", ".vlt", ".py"))
                 or PurePosixPath(name).name == "Makefile" or name == HEADER_PROBE]
        self.stages = {}
        for stage, expected in zip(stages, ("configured", "runtime", "built", "frozen")):
            _fields(stage, ("stage", "files"), "retained stage")
            _same(stage["stage"], expected, "build stage order")
            prefix = "artifacts/" + self.variant_id + "/" + expected + "/"
            rows = self.inventory(stage["files"], "build " + expected, sorted_paths=True)
            values = {}
            for name, value in rows.items():
                require(name.startswith(prefix) and name[len(prefix):] in names, "unexpected retained build input")
                relative = name[len(prefix):]
                _same(dict(value, path=relative), self.frozen[relative], "retained build identity")
                self.verified(value)
                values[relative] = value
            require(set(GENERATED + COPIED) <= set(values), "build stage omits generated inputs")
            self.stages[expected] = values
        _same(list(self.stages["frozen"]), names, "final retained build inventory")
        _same(self.build_body(HEADER_PROBE), b"#include <VX_config.h>\n", "include probe")
        for name in (*COPIED, APP + "/Makefile"):
            _same(self.build_body(name), self.source_body(name), "copied source " + name)
        config = self.build_body("config.mk").decode("utf-8")
        for key, expected in (("XLEN", "64"), ("PROFILE", "p02-tfr"), ("VORTEX_HOME", str(self.paths["source"])),
                              ("TOOLDIR", str(self.paths["tools"])), ("OSVERSION", "ubuntu/focal")):
            values = re.findall(r"^" + key + r"[ \t]*\?=[ \t]*(.*?)[ \t]*$", config, re.MULTILINE)
            _same(values, [expected], "generated config " + key)
        tokens = self.build_body(".config.stamp").decode("utf-8").strip().split()
        require(all("=" in token for token in tokens), "invalid configure stamp")
        stamp = dict(token.split("=", 1) for token in tokens)
        require(len(stamp) == len(tokens), "duplicate configure settings")
        for key, expected in (("XLEN", "64"), ("PROFILE", "p02-tfr"), ("SOURCE_DIR", str(self.paths["source"])),
                              ("BUILDDIR", str(self.build)), ("TOOLDIR", str(self.paths["tools"]))):
            _same(stamp.get(key), expected, "configure stamp " + key)
        _same(self.build_body("sim/rtlsim/verilator.vlt").decode("utf-8"),
              self.source_body("sim/rtlsim/verilator.vlt.in").decode("utf-8").replace("@VORTEX_HOME@", str(self.paths["source"])),
              "generated Verilator configuration")

    def compiler_commands(self):
        source, build, env = self.paths["source"], self.build, self.env
        self.command(self.variant_id + "-configure", [source / "configure", "--xlen=64", "--profile=p02-tfr",
                     "--osversion=ubuntu/focal", "--tooldir=" + str(self.paths["tools"])], build, env,
                     self.limits["configure_timeout_seconds"])
        preprocessor = [self.tools["g++"]["path"], "-E", "-dM", "-x", "c++"]
        tail = ["-include", build / "sw/VX_config.h", "/dev/null"]
        text, _ = self.command(self.variant_id + "-header", [*preprocessor, "-DVX_CFG_XLEN=64", "-DVX_CFG_XLEN_64", *tail],
                               build, env, 30, read=True)
        initial = validate_header_macros(text)
        _same(self.variant["header_macros"], initial, "initial header macros")
        for language, relative in (("cpp", "sw/VX_config.h"), ("verilog", "hw/VX_config.vh")):
            self.command(self.variant_id + "-" + language + "-header-reproduce", [self.tools["python3"]["path"],
                         source / "ci/gen_config.py", "--config=" + str(source / "VX_config.toml"), "--profile=p02-tfr",
                         "--format=" + language, "--output=" + str(build / PurePosixPath(HEADER_PROBE).parent / PurePosixPath(relative).name)],
                         build, dict(env, XLEN="64"), 30)
        config = "-DITYPE=" + self.fmt + " -DOTYPE=fp32 -DKUNROLL=1"
        text, _ = self.command(self.variant_id + "-expected-flags", [self.tools["python3"]["path"], source / "ci/gen_config.py",
                               "--config=" + str(source / "VX_config.toml"), "--profile=p02-tfr", "--xlen=64", "--format=cflags",
                               "--cflags=" + config + " -DVX_CFG_XLEN=64"], build, env, 30, read=True)
        flags = _stamp_flags(text, "retained generated flags")
        require(flags and all(flag.startswith("-D") for flag in flags), "invalid generated flags")
        text, _ = self.command(self.variant_id + "-expected-expanded-header", [*preprocessor, *flags,
                               *("-D" + name + "_DISABLE" for name in DISABLED), *tail], build, env, 30, read=True)
        expanded = validate_header_macros(text)
        backend = dict(initial, PERF_ENABLE="1", **{name + "_DISABLE": "1" for name in DISABLED})
        _same(self.variant["expected_expanded_header_macros"], expanded, "expanded configuration")
        _same(self.variant["expected_backend_header_macros"], backend, "backend configuration")
        make = [self.tools["make"]["path"], "--no-print-directory", "-j" + str(self.limits["jobs"]),
                "THREADS=" + str(self.limits["jobs"])]
        app = build / APP
        current = dict(env, CONFIGS=config, PERF="1")
        self.command(self.variant_id + "-runtime", [*make, "runtime-simx"], app, current, self.limits["build_timeout_seconds"])
        self.command(self.variant_id + "-application", [*make, "all"], app, current, self.limits["build_timeout_seconds"])
        self.compiler = validate_records(self.build_body("sw/runtime/simx_rt_config.stamp").decode("utf-8"),
            self.build_body("sw/runtime/simx_config.stamp").decode("utf-8"),
            self.build_body(APP + "/config.stamp").decode("utf-8"), driver="simx", fmt=self.fmt,
            source=Path(str(source)), build=Path(str(build)), jobs=self.limits["jobs"])
        _same(self.variant["compiler_records"], self.compiler, "independent original compiler records")
        self.effective = {}
        directories = {"runtime": build / "sw/runtime/simx", "backend_cpp": build / "sim/simx", "kernel": app, "host": app}
        for record in self.compiler:
            role = record["role"]
            command_id = self.variant_id + "-" + role + "-header"
            text, _ = self.command(command_id, [*preprocessor, *record["macro_flags"],
                                   *("-I" + name for name in record["include_paths"]), build / HEADER_PROBE],
                                   directories[role], env, 30, read=True)
            expected = dict(backend if role == "backend_cpp" else expanded)
            self.effective[role] = {"command_id": command_id, "macros":
                validate_effective_header(text, expected, driver="simx", role=role)}
        _same(self.variant["effective_headers"], self.effective, "effective compiler configuration")

    def build_binding(self):
        binding = {
            "contract_id": CONTRACT_ID, "contract_sha256": self.report["contract_sha256"],
            "source": self.source, "backend": "simx", "format": self.fmt, "case": self.case,
            "corpus": self.report["corpus"], "profile_sha256": PROFILE_SHA256,
            "kernel_source_sha256": KERNEL_SHA256, "compiler_records": self.compiler,
            "effective_headers": self.effective, "generated_identity": self.variant["generated_identity"],
            "generated_header_macros": self.variant["header_macros"],
            "expected_expanded_header_macros": self.variant["expected_expanded_header_macros"],
            "expected_backend_header_macros": self.variant["expected_backend_header_macros"],
            "artifacts": self.variant["artifacts_before"], "tools": self.tools, "dependencies": self.dependencies,
            "sampling": self.contract["sampling"], "performance_environment": {"PERF": "1"},
        }
        original = self.api.strict_json(self.verified(self.variant["binding"],
            "snapshots/" + self.variant_id + "-build-binding.json"))
        _same(original, binding, "reconstructed common build binding")
        self.build_id = qualification_id(binding)
        _same(self.variant["qualification_id"], self.build_id, "common build identity")
        self.bindings[self.variant_id] = binding

    def processes(self):
        for planned in (row for row in self.plan if row["format"] == self.fmt):
            row = self.report["processes"][len(self.process_results)]
            _fields(row, set(planned) | {"sample_id", "binding", "command_id", "log", "observation", "outcome",
                "qualification_id", "build_qualification_id", "process_duration_seconds"}, "process")
            for key, expected in planned.items():
                _same(row[key], expected, "process." + key)
            _same(row["outcome"], "pass", "process outcome")
            process_id = planned["id"]
            binding = {"contract_id": CONTRACT_ID, "contract_sha256": self.report["contract_sha256"],
                "build_qualification_id": self.build_id, "build": self.bindings[self.variant_id], "process": planned}
            actual = self.api.strict_json(self.verified(row["binding"], "snapshots/" + process_id + "-binding.json"))
            _same(actual, binding, "reconstructed process binding")
            binding_id = qualification_id(binding)
            for key, expected in (("qualification_id", binding_id), ("build_qualification_id", self.build_id),
                                  ("command_id", process_id), ("sample_id", process_id), ("log", "logs/" + process_id + ".log")):
                _same(row[key], expected, "process " + key)
            app = self.build / APP
            text, receipt = self.command(process_id, [app / "ai_warm_workspace", "--policy", planned["policy"],
                "--module", app / "kernel.vxbin", "--qualification-id", binding_id, "--sample-id", process_id,
                "--pair-index", str(planned["pair_index"]), "--phase", planned["phase"]], app,
                dict(self.env, VORTEX_DRIVER="simx", LD_LIBRARY_PATH=str(self.build / "sw/runtime")),
                self.limits["run_timeout_seconds"], read=True)
            _same(row["process_duration_seconds"], receipt["duration_seconds"], "supervisor duration")
            observed = verify_output(text, case=self.case, fmt=self.fmt, policy=planned["policy"],
                binding_id=binding_id, sample_id=process_id, pair_index=planned["pair_index"],
                phase=planned["phase"], contract=self.contract)
            _same(row["observation"], observed, "recomputed original output")
            intervals = observed["summary"]["host_intervals_ns"]
            span = intervals["close"]["end_ns"] - intervals["create"]["begin_ns"]
            allowance = self.contract["timing"]["supervisor_containment_allowance_ns"]
            require(0 <= span <= math.ceil(receipt["duration_seconds"] * 1_000_000_000) + allowance,
                    "owner lifetime exceeds the supervised process duration")
            self.raw_logs[process_id] = text
            self.process_results.append({**planned, "qualification_id": binding_id, "build_qualification_id": self.build_id,
                "launches": sum(op["dispatch"]["launches"] for op in observed["operations"]),
                "checked_words": sum(op["checked"] for op in observed["operations"]),
                "buffer_creates": observed["summary"]["counts"]["buffer_create_calls"],
                "buffer_releases": observed["summary"]["counts"]["buffer_release_calls"],
                "raw_log_sha256": observed["raw_log_sha256"]})

    def stability(self):
        labels = []
        for fmt in ("fp16", "bf16"):
            labels.append("before-simx-" + fmt)
            for row in self.plan:
                if row["format"] == fmt:
                    labels.extend(("before-" + row["id"], "after-" + row["id"]))
            labels.append("after-simx-" + fmt)
        checks = self.report["stability_checks"]
        require(type(checks) is list and len(checks) == len(labels), "missing stability observations")
        previous = self.started
        for check, label in zip(checks, labels):
            _fields(check, ("at", "label", "source_sha256", "tools_sha256", "dependencies_sha256"), "stability observation")
            _same(check["label"], label, "stability order")
            at = _timestamp(check["at"])
            require(previous <= at <= self.finished, "stability timestamps are outside chronology")
            previous = at
            for name, value in (("source", self.source), ("tools", self.tools), ("dependencies", self.dependencies)):
                _same(check[name + "_sha256"], qualification_id(value), "stability identity " + name)

    def quarantine(self, row):
        _same(row.get("submodule"), "third_party/cocogfx", "cache quarantine submodule")
        modules = {item["path"]: item["revision"] for item in self.source["checkout"]["submodules"]["entries"]}
        if row.get("state") == "not_present":
            _fields(row, ("submodule", "state", "files"), "absent cache quarantine")
            _same(row["files"], [], "absent cache products")
            require("third_party/cocogfx" not in modules, "quarantine omits a declared submodule")
            return
        require(row.get("state") in ("not_needed", "relocated"), "unfinished cache quarantine")
        fields = {"submodule", "state", "files", "expected_revision", "revision_before", "revision_after",
                  "status_before", "status_after"}
        if row["state"] == "relocated":
            fields.add("destination")
        _fields(row, fields, "cache quarantine")
        revision = modules.get("third_party/cocogfx")
        require(revision is not None, "quarantined module is absent from checkout")
        for key in ("expected_revision", "revision_before", "revision_after"):
            _same(row[key], revision, "quarantine " + key)
        _same(row["status_after"], [], "quarantine final source state")
        if row["state"] == "not_needed":
            _same(row["status_before"], [], "clean cache source")
            _same(row["files"], [], "unused quarantine inventory")
            return
        destination = self.paths["tools"].parent / "cache-quarantine/cocogfx"
        _same(row["destination"], str(destination), "quarantine destination")
        require(type(row["files"]) is list and 0 < len(row["files"]) <= 1000, "invalid quarantine inventory")
        products = []
        for item in row["files"]:
            _fields(item, ("path", "sha256", "size_bytes", "moved", "destination", "after_sha256", "after_size_bytes"),
                    "quarantined product")
            self.api.descriptor({key: item[key] for key in ("path", "sha256", "size_bytes")})
            require(item["path"].startswith("third_party/cocogfx/"), "quarantine path escaped its module")
            product = item["path"][len("third_party/cocogfx/"):]
            require(product in (".depend", "libcocogfx.a") or re.fullmatch(r"src/[A-Za-z0-9_.-]+\.o", product),
                    "quarantine has an unexpected product class")
            products.append(product)
            for key, expected in (("moved", True), ("after_sha256", item["sha256"]),
                                  ("after_size_bytes", item["size_bytes"]), ("destination", str(destination / product))):
                _same(item[key], expected, "quarantine product " + key)
        _same(products, sorted(set(products)), "unique ordered quarantine products")
        _same(row["status_before"], ["?? " + product for product in products], "quarantine original source state")

    def preparation(self, outer):
        row = outer.json("preparation.json")
        _fields(row, ("schema_version", "contract_id", "outcome", "reason", "native_execution", "acceptance_claimed",
            "expected_revision", "backend", "formats", "toolchain_id", "toolchain_cache_key", "third_party_cache_key",
            "budget", "tools_relocated", "limitations", "resources", "tools_dir", "cache_quarantine", "source",
            "tool_identities", "dependency_identities", "preparation_sources"), "hosted preparation")
        for key, expected in (("schema_version", 1), ("contract_id", "p04-hosted-preparation-v1"),
            ("outcome", "pass"), ("reason", None), ("native_execution", "not_run"), ("acceptance_claimed", False),
            ("expected_revision", self.revision), ("backend", "simx"), ("formats", ["fp16", "bf16"]),
            ("tools_relocated", True), ("tools_dir", str(self.paths["tools"])), ("source", self.source["checkout"]),
            ("tool_identities", self.tools), ("dependency_identities", self.dependencies),
            ("budget", {"min_free_bytes": 15 * 1024**3, "max_rss_bytes": 4 * 1024**3,
                        "max_log_bytes": 16 * 1024**2, "jobs": 2})):
            _same(row[key], expected, "preparation " + key)
        require(type(row["toolchain_id"]) is str and re.fullmatch(
            re.escape(self.source["checkout"]["pins"]["TOOLCHAIN_REV"]) + r"-[0-9a-f]{40}", row["toolchain_id"]),
            "preparation toolchain resolution differs from VERSION")
        require(row["toolchain_cache_key"] in ("Linux-toolchain-" + row["toolchain_id"] + "-lite",
                                               "Linux-toolchain-" + row["toolchain_id"] + "-full"),
                "unmatched toolchain cache")
        cache_digest = hashlib.sha256(b"".join(hashlib.sha256(self.source_body(name)).digest()
            for name in ("third_party/Makefile", ".gitmodules"))).hexdigest()
        _same(row["third_party_cache_key"], "Linux-thirdparty-" + cache_digest, "dependency cache source identity")
        require(type(row["limitations"]) is list and row["limitations"]
                and all(type(value) is str and value for value in row["limitations"]), "missing preparation limitations")
        resource = row["resources"]
        _fields(resource, ("free_disk_bytes", "available_memory_bytes"), "preparation resources")
        _fields(resource["free_disk_bytes"], ("source", "workspace"), "preparation resource roots")
        for value in resource["free_disk_bytes"].values():
            _integer(value, 15 * 1024**3, (1 << 64) - 1, "preparation disk reserve")
        _integer(resource["available_memory_bytes"], 4 * 1024**3, (1 << 64) - 1, "preparation available memory")
        for item in self.inventory(row["preparation_sources"], "preparation sources", expected=PREPARATION_SOURCES).values():
            _same(item, self.sources[item["path"]], "preparation source identity")
        require(type(row["cache_quarantine"]) is dict, "invalid quarantine record")
        self.quarantine(row["cache_quarantine"])
        _same(outer.json("preparation.log"), {"outcome": "pass", "reason": None, "native_execution": "not_run"},
              "preparation final output")
        return {"identity": outer.identity("preparation.json"), "toolchain_id": row["toolchain_id"],
                "toolchain_cache_key": row["toolchain_cache_key"], "third_party_cache_key": row["third_party_cache_key"],
                "cache_quarantine_state": row["cache_quarantine"]["state"]}

    def hosted_identity(self):
        parent = str(PurePosixPath(self.view.prefix).parent) if self.view.prefix else ""
        outer = self.view.archive.view("" if parent == "." else parent)
        names = {"job.json", "workflow.yml", "python-provision.json", "preparation.json", "preparation.log", "execution.log"}
        present = names.intersection(outer.files())
        if not present:
            return None, None
        _same(present, names, "complete hosted identity")
        job = outer.json("job.json")
        _fields(job, ("GITHUB_SHA", "GITHUB_EVENT_NAME", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_JOB",
            "GITHUB_REPOSITORY", "GITHUB_REF", "P06_WARM_BACKEND", "P06_WARM_FORMAT", "scope", "record_stage",
            "native_execution", "acceptance_claimed", "workflow_sha256"), "hosted job")
        for key, expected in (("GITHUB_SHA", self.revision), ("GITHUB_REPOSITORY", "baabi-boo/AI-GPU"),
            ("GITHUB_JOB", "experiment"), ("P06_WARM_BACKEND", "simx"), ("P06_WARM_FORMAT", "both"),
            ("scope", "matched-warm-context-workspace-experiment"), ("record_stage", "job-initialization"),
            ("native_execution", "not_run"), ("acceptance_claimed", False)):
            _same(job[key], expected, "hosted " + key)
        require(job["GITHUB_EVENT_NAME"] in ("push", "pull_request", "workflow_dispatch"), "invalid hosted event")
        for key in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"):
            require(type(job[key]) is str and re.fullmatch(r"[1-9][0-9]{0,20}", job[key]), "invalid hosted run identity")
        require(type(job["GITHUB_REF"]) is str
                and re.fullmatch(r"refs/((heads|tags)/[^\s]+|pull/[1-9][0-9]*/merge)", job["GITHUB_REF"]),
                "invalid hosted ref")
        if job["GITHUB_EVENT_NAME"] == "push":
            _same(job["GITHUB_REF"], "refs/heads/master", "hosted push branch")
        elif job["GITHUB_EVENT_NAME"] == "pull_request":
            require(re.fullmatch(r"refs/pull/[1-9][0-9]*/merge", job["GITHUB_REF"]), "hosted PR ref differs")
        workflow = outer.read("workflow.yml", limit=256 * 1024)
        _same(workflow, self.source_body(".github/workflows/p06-warm-workspace.yml"), "hosted workflow source")
        _same(job["workflow_sha256"], hashlib.sha256(workflow).hexdigest(), "hosted workflow hash")
        provision = outer.json("python-provision.json")
        _fields(provision, ("python_version", "implementation", "platform", "executable", "python3_on_path"), "Python provision")
        for key, expected in (("python_version", [3, 12, 14]), ("implementation", "CPython"), ("platform", "linux")):
            _same(provision[key], expected, "provisioned " + key)
        self.api.recorded_absolute(provision["executable"])
        _same(provision["python3_on_path"], self.tools["python3"]["path"], "provisioned interpreter")
        require(provision["executable"] in (self.tools["python3"]["path"], self.tools["python3"]["resolved_path"]),
                "Python provisioning differs from executed tool")
        prepared = self.preparation(outer)
        _same(outer.json("execution.log"), {"outcome": "pass", "reason": None,
            "report": str(self.paths["output"] / "report.json"), "completed_processes": 24,
            "completed_launches": 792, "checked_words": 25344, "full_matrix_completed": True,
            "acceptance_claimed": False, "performance_acceptance": False, "hypothesis_evaluation": "not_evaluated"},
            "hosted final execution output")
        if "host-dependencies.log" in outer.files():
            outer.read("host-dependencies.log", limit=16 * 1024**2)
        nested = PurePosixPath(self.view.prefix).name + "/"
        extras = set(outer.files()) - names - {"host-dependencies.log"}
        _same(extras, {nested + name for name in self.view.files()}, "hosted member inventory")
        return job, prepared

    def run(self):
        _fields(self.report, REPORT_FIELDS, "warm report")
        for key, expected in (("schema_version", 1), ("contract_id", CONTRACT_ID),
            ("scope", "matched-warm-context-workspace-experiment"), ("state", "finished"), ("outcome", "pass"),
            ("reason", None), ("failures", []), ("acceptance_claimed", False), ("performance_acceptance", False),
            ("phase_acceptance", False), ("phase_complete", False), ("hypothesis_evaluation", "not_evaluated"),
            ("full_matrix_requested", True), ("full_matrix_completed", True), ("selected_scope_completed", True),
            ("retained_files_stable", True), ("complete_matrix", self.contract["complete_matrix"]),
            ("selected_counts", COUNTS), ("completed_processes", 24), ("completed_launches", 792),
            ("checked_words", 25344), ("measured_processes", 20), ("measured_operations", 640),
            ("expected_processes", self.plan)):
            _same(self.report[key], expected, "report." + key)
        require(type(self.report["limitations"]) is list and self.report["limitations"]
                and all(type(value) is str and value for value in self.report["limitations"]), "missing execution limitations")
        self.started, self.finished = (_timestamp(self.report[key]) for key in ("started_at", "finished_at"))
        require(self.started <= self.finished, "execution timestamps are reversed")
        require(type(self.report["commands"]) is list and len(self.report["commands"]) == 53,
                "unexpected command inventory")
        require(type(self.report["variants"]) is list and len(self.report["variants"]) == 2, "expected two format builds")
        require(type(self.report["processes"]) is list and len(self.report["processes"]) == 24,
                "missing or duplicate process")
        self.budget()
        self.provenance()
        self.paths_and_tools()
        _same(str(self.paths["verilator"]), str(self.paths["tools"] / "verilator"), "unused Verilator default")
        for name in ("g++", "clang", "make", "python3", "riscv-gcc"):
            self.command("version-" + name.replace("+", "p"), [self.tools[name]["path"], "--version"],
                         self.paths["work"], self.env, 30)
        for self.variant, self.fmt in zip(self.report["variants"], ("fp16", "bf16")):
            self.variant_id = "simx-" + self.fmt
            self.build = self.paths["work"] / self.variant_id
            self.case = next(case for case in self.cases if case["format"] == self.fmt)
            _fields(self.variant, ("artifacts_after", "artifacts_before", "backend", "build_dir", "compiler_records",
                "effective_headers", "expected_backend_header_macros", "expected_expanded_header_macros", "format",
                "generated_identity", "header_macros", "id", "outcome", "process_ids", "retained_builds",
                "qualification_id", "binding"), "variant")
            for key, expected in (("id", self.variant_id), ("backend", "simx"), ("format", self.fmt),
                ("outcome", "pass"), ("build_dir", str(self.build)),
                ("process_ids", [row["id"] for row in self.plan if row["format"] == self.fmt])):
                _same(self.variant[key], expected, "variant." + key)
            self.generated()
            self.compiler_commands()
            self.build_binding()
            self.processes()
        _same(self.command_index, len(self.report["commands"]), "unexpected trailing command")
        _same(self.report["raw_logs"], self.log_rows, "original raw-log inventory")
        counts = {"processes": len(self.process_results), "launches": sum(row["launches"] for row in self.process_results),
                  "checked_words": sum(row["checked_words"] for row in self.process_results)}
        _same(counts, COUNTS, "recomputed complete counts")
        self.stability()
        hosted, preparation = self.hosted_identity()
        _same(set(self.view.files()), self.used_members, "complete warm packet member inventory")
        analysis = analyze_processes(self.report["processes"], self.raw_logs, build_bindings=self.bindings,
                                     contract=self.contract, expected_revision=self.revision)
        return {"schema_version": 2, "scope": "p06-warm-workspace-complete-retained-data-replay", "outcome": "pass",
            "native_execution": "not_run", "acceptance_claimed": False, "performance_acceptance": False,
            "phase_acceptance": False, "phase_complete": False, "full_matrix_completed": True,
            "hypothesis_evaluation": analysis["hypothesis_evaluation"],
            "full_hypothesis_qualification": analysis["full_hypothesis_qualification"],
            "conditional_evaluation": analysis["conditional_evaluation"],
            "source_revision": self.revision, "source_tree": self.source["checkout"]["tree"],
            "source_snapshot_sha256": qualification_id(self.source), "report_identity": self.view.identity("report.json"),
            "commands_checked": self.command_index, "retained_source_files_checked": len(self.sources), "counts": counts,
            "processes": self.process_results, "build_qualification_ids": {name: qualification_id(value) for name, value in self.bindings.items()},
            "hosted_job_identity": hosted, "preparation": preparation, "analysis": analysis,
            "archive_provenance_validation": "pass", "limitations": LIMITATIONS}


def replay_archive(path, sha256, *, expected_revision, prefix="warm-workspace"):
    """Verify one complete paired archive against external digest/source identities."""
    require(type(expected_revision) is str and archive_helpers.REVISION.fullmatch(expected_revision),
            "invalid external source revision")
    trusted = common._trusted_sources()
    api = archive_helpers._archive_api()
    try:
        with api.ArchiveReader(path, sha256) as archive:
            result = _Replay(archive.view(prefix), api, expected_revision).run()
            result["archive_read"] = archive.receipt()
            result["trusted_archive_reader"] = {"path": archive_helpers.ARCHIVE_READER_PATH,
                                                "sha256": archive_helpers.ARCHIVE_READER_SHA256}
            _same(common._trusted_sources(), trusted, "executing replay source stability")
            result["trusted_replay_sources"] = trusted
            return result
    except (KeyError, TypeError, IndexError, UnicodeError, OverflowError) as error:
        raise ReplayError("malformed retained warm packet: " + str(error)) from error


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--prefix", default="warm-workspace")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = replay_archive(args.archive, args.sha256, expected_revision=args.source_revision, prefix=args.prefix)
        body = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
        if args.output:
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(body)
            print(json.dumps({"schema_version": result["schema_version"],
                "outcome": "pass", "counts": result["counts"], "native_execution": "not_run",
                "hypothesis_evaluation": result["hypothesis_evaluation"],
                "full_hypothesis_qualification": result["full_hypothesis_qualification"],
                "conditional_evaluation": result["conditional_evaluation"],
                "acceptance_claimed": False, "report": str(args.output)}))
        else:
            print(body, end="")
        return 0
    except (OSError, ValueError) as error:
        print(json.dumps({"outcome": "fail", "reason": str(error), "native_execution": "not_run", "acceptance_claimed": False}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
