#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Reconstruct a complete fresh-dependency native original as inert retained data.

All digests are caller supplied. The source-manifest pin identifies the exact
native source-before snapshot bytes, not a new Git membership attestation.
Only the named ZIP and trusted current reader files are opened. No retained
code, compiler, executable, command or producer path is executed or opened.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys

sys.dont_write_bytecode = True

from baseline_packet_contract import _stamp_flags, _stamp_words
from p02_matrix_records import DISABLED, PROFILE_SHA256
from p02_wmma_fixtures import load_cases, render_header
from p03_execution_records import qualification_id
from p06_compiler_records import validate_header_macros
import p06_dependency_admission as admission
import p06_dependency_binary as binary
import p06_dependency_contract as dependency_contract
import p06_dependency_receipt as dependency_receipt
import p06_dependency_replay as dependency_replay
import p06_managed_preflight_application_build as application
import p06_managed_preflight_backend_build as backend_recipes
import p06_managed_preflight_build as build_records
import p06_managed_preflight_contract as manifest
import p06_managed_preflight_execute as producer
from p06_managed_preflight_generated import validate_generated_flags
import p06_managed_preflight_replay as managed
import p06_managed_preflight_replay_build as replay_build
from p06_managed_preflight_replay_hosted import _valid_hosted_ref
import p06_managed_preflight_sources as source_inventory
import p06_native_lifetime_contract as lifetime
import p06_native_lifetime_records as records
import p06_replay as archive_helpers
from p06_replay import _fields, _integer, _same, _timestamp, require
import p06_workspace_replay as common
import p06_warm_contract as warm_contract
from p06_warm_execute import validate_process_duration

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_ID = "p06-managed-dependency-lifetime-replay-v1"
APP, HEADER_PROBE = manifest.APP, producer.HEADER_PROBE
BINARY_FILES = producer.BINARY_FILES
BACKEND_STAMPS = replay_build.BACKEND_STAMPS
GENERATED, COPIED = archive_helpers.GENERATED, archive_helpers.COPIED
COUNTS = dict(lifetime.COMPLETE_COUNTS)
REPORT_FIELDS = managed.REPORT_FIELDS | {
    "native_lifetime_passed", "preflight_contract_snapshot", "preflight_contract_sha256",
    "dependency_receipt_sha256", "dependency_admission", "dependency_admission_before",
    "dependency_admission_after", "dependency_source_to_loaded_binary_verified",
    "retained_dependency_receipt",
}
VARIANT_FIELDS = managed.VARIANT_FIELDS | {
    "dependency_model_build_command", "dependency_receipt_sha256", "dependency_model_link",
    "application_build_records", "retained_dependency_model_payloads",
}
RUNNER_HELPERS = tuple(sorted(set(managed.RUNNER_HELPERS) | {
    "ci/project/" + name + ".py" for name in (
        "p06_dependency_admission", "p06_dependency_binary", "p06_dependency_contract",
        "p06_dependency_graph", "p06_dependency_lifetime_execute", "p06_dependency_receipt",
        "p06_dependency_record", "p06_dependency_sources", "p06_managed_preflight_application_build",
        "p06_managed_preflight_source_export", "p06_managed_preflight_sources",
        "p06_native_lifetime_contract", "p06_native_lifetime_records")
}))
MODEL_RECIPE = b"# SPDX-License-Identifier: Apache-2.0\ninclude Makefile\n\nLDFLAGS += -Wl,-Map,$(DESTDIR)/dependency-model.map\n"
LIMITATIONS = [
    "This verifies retained consistency of the selected dependency build and complete four-process native original; replay executes no native process.",
    "The archive, source revision, dependency receipt, native report and source-before snapshot digests are external intake expectations, not producer authentication.",
    "The native source-manifest pin binds every retained source descriptor and byte; this reader does not independently establish superproject Git object membership.",
    "The dependency reader independently reconstructs its five locked Git source trees; system/compiler and concurrent-writer limitations remain applicable.",
    "Retained command strings, source, binaries and producer paths are inert; the named hosted original supplies execution evidence separately.",
    "The pending-accessor probe and alternate-dependency control are separate populations and need their own original review.",
    "A consistently synthetic or forged original remains synthetic or forged after consistency verification.",
    "Complete 40-component qualification, no-wrap bounds, warm performance and phase acceptance remain unavailable; all seven claims remain false.",
]


def _reader_sources():
    rows = dependency_replay._reader_sources()
    names = {row["path"] for row in rows}
    for name in ("p06_dependency_native_replay", "p06_dependency_admission",
                 "p06_native_lifetime_contract", "p06_native_lifetime_records"):
        path = ROOT / "ci/project" / (name + ".py")
        module = sys.modules[__name__] if name == "p06_dependency_native_replay" else sys.modules[name]
        require(Path(module.__file__).resolve(strict=True) == path,
                "native replay helper loaded outside the trusted checkout")
        relative = path.relative_to(ROOT).as_posix()
        if relative not in names:
            body = path.read_bytes()
            rows.append({"path": relative, "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)})
            names.add(relative)
    return sorted(rows, key=lambda row: row["path"])


def _pin(value, label):
    require(type(value) is str and dependency_receipt.SHA256.fullmatch(value),
            "exact external " + label + " SHA-256 is required")
    return value


def _admission_values(document, verification, receipt_sha256):
    verified = dict(verification, receipt_sha256=receipt_sha256)
    summary = {"receipt_sha256": receipt_sha256,
        "dependency_contract_sha256": dependency_contract.contract_hash(),
        "source_manifest_sha256": qualification_id(document["source_manifest"]),
        "staged_files_sha256": qualification_id(document["staged_files"]), "verification": verified}
    source_inputs = []
    for component in document["source_manifest"]["sources"]:
        prefix = PurePosixPath(document["paths"]["source"]) / dependency_contract.PINS[component["name"]]["path"]
        source_inputs.extend({"path": str(prefix / item["path"]), "sha256": item["sha256"],
                              "size_bytes": item["size_bytes"]} for item in component["files"])
    source_inputs.sort(key=lambda row: row["path"])
    stability = {"receipt_sha256": receipt_sha256,
        "source_inputs_sha256": qualification_id(source_inputs),
        "staged_files_sha256": summary["staged_files_sha256"],
        "tools_sha256": qualification_id(document["tools"]),
        "helper_sources_sha256": qualification_id(document["helper_sources"])}
    return summary, stability


def _backend_graph(model_text, backend_text, *, compiler, make, source, build, source_body):
    """Review the split graph without changing the historical recursive graph."""
    for name, digest in backend_recipes.RECIPE_SHA256.items():
        require(hashlib.sha256(source_body(name)).hexdigest() == digest,
                "dependency backend source recipe differs: " + name)
    _same(source_body(admission.MODEL_MAKEFILE), MODEL_RECIPE, "dependency model companion recipe")
    model_lines = build_records._lines(model_text, "dependency model log")
    backend_lines = build_records._lines(backend_text, "dependency backend log")
    require(len(model_lines) == 44 and len(backend_lines) == 2,
            "split model/backend command population differs")
    objects = {str(build_records.expected_object(name, str(build))) for name in build_records.MODEL_SOURCES}
    seen, order = set(), []
    target = str(build / "sw/runtime/libsimx.so")
    for line in model_lines:
        words = _stamp_words(line, "dependency model command")
        require(words[0] == compiler and words[-2] == "-o", "dependency model command is not a selected compiler")
        output = words[-1]
        if output in objects:
            require(output not in seen and target not in seen, "model compile is repeated or after its link")
        else:
            require(output == target and seen == objects, "model link precedes its complete object graph")
        seen.add(output)
        order.append(output)
    require(seen == objects | {target}, "model command graph is incomplete")
    expected_nested = ["DESTDIR=" + str(build / "sw/runtime"), make, "-C", str(build / "sim/simx"), target]
    _same(_stamp_words(backend_lines[0], "backend recursive make"), expected_nested, "backend recursive check")
    backend_words = _stamp_words(backend_lines[1], "backend compile/link")
    require(backend_words[0] == compiler and backend_words[-2:] == ["-o", str(build / "sw/runtime/libvortex-simx.so")],
            "backend compile/link differs from the selected output")
    return {"contract_id": "p06-dependency-managed-build-graph-v1", "command_count": 46,
        "model_command_count": 44, "backend_command_count": 2,
        "recipe_sha256": dict(backend_recipes.RECIPE_SHA256,
                              **{admission.MODEL_MAKEFILE: hashlib.sha256(MODEL_RECIPE).hexdigest()}),
        "model_order": order,
        "normalized_commands_sha256": hashlib.sha256(("\n".join(model_lines + backend_lines) + "\n").encode()).hexdigest()}


class _NativeReplay(managed._Replay):
    def __init__(self, view, api, revision, *, dependency_document, dependency_verification,
                 dependency_body, dependency_receipt_sha256, source_manifest_sha256):
        super().__init__(view, api, revision, None, None)
        self.dependency_document = dependency_document
        self.dependency_verification = dependency_verification
        self.dependency_body = dependency_body
        self.dependency_receipt_sha256 = dependency_receipt_sha256
        self.source_manifest_sha256 = source_manifest_sha256
        self.admission_summary, self.admission_stability = _admission_values(
            dependency_document, dependency_verification, dependency_receipt_sha256)
        self.model_links = {}

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
        _same(self.report["source_before"]["sha256"], self.source_manifest_sha256,
              "externally pinned native source manifest")
        self.sources = self.inventory(self.source["files"], "source files", sorted_paths=True)
        retained = [dict(row, path="artifacts/source/" + row["path"]) for row in self.source["files"]]
        _same(self.report["retained_sources"], retained, "retained source descriptors")
        for row in retained:
            self.verified(row)
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
        _same(self.report["preflight_contract_sha256"], qualification_id(self.contract), "parent contract identity")
        _same(self.document("preflight_contract_snapshot", "preflight-contract"), self.contract, "parent contract snapshot")
        _same(self.report["contract_sha256"], admission.contract_hash(), "dependency lifetime contract identity")
        _same(self.document("contract_snapshot", "contract"), admission.contract(), "dependency lifetime contract snapshot")
        _same(self.document("fixture_snapshot", "selected-fixtures"), self.cases, "selected independent fixtures")
        corpus = self.inventory(self.report["corpus"], "fixture corpus", expected=common.CORPUS)
        for name, row in corpus.items():
            _same(row, self.sources[name], "fixture descriptor")
            _same(self.source_body(name), (ROOT / name).read_bytes(), "trusted independent fixture bytes")
        _same(self.source_body(common.CORPUS[-1]), render_header(load_cases(ROOT)), "independent fixture header")
        old_bytes = self.source_body("ci/project/p06_warm_contract.json")
        _same(hashlib.sha256(old_bytes).hexdigest(), manifest.WARM_CONTRACT_SHA256,
              "unchanged historical warm contract")
        for path, digest, field in (("profiles/p02-tfr.json", PROFILE_SHA256, "profile_sha256"),
            ("sw/kernel/ai/matmul.cpp", producer.KERNEL_SHA256, "kernel_source_sha256"),
            ("ci/project/p06_warm_contract.json", manifest.WARM_CONTRACT_SHA256, "warm_contract_sha256")):
            _same(self.sources[path]["sha256"], digest, "frozen " + path)
            _same(self.report[field], digest, "reported " + path)
        self.inventory(self.dependencies, "dependencies", expected=archive_helpers.DEPENDENCIES)
        payloads = [dict(row, path="artifacts/dependencies/" + row["path"]) for row in self.dependencies]
        _same(self.report["retained_dependency_payloads"], payloads, "retained dependency payloads")
        for row in payloads:
            self.payload(row)
        required = set(source_inventory.REQUIRED_SOURCE_NAMES) | set(producer.SOURCE_FILES) | set(lifetime.SOURCE_FILES) | set(admission.SOURCE_FILES) | set(RUNNER_HELPERS)
        require(required <= set(self.sources), "native source inventory omits required production inputs")
        input_hashes = {}
        for component in self.dependency_document["source_manifest"]["sources"]:
            prefix = dependency_contract.PINS[component["name"]]["path"] + "/"
            input_hashes.update({prefix + item["path"]: item for item in component["files"]})
        for name, row in self.sources.items():
            if name.startswith("third_party/") and name in input_hashes:
                expected = input_hashes[name]
                _same({key: row[key] for key in ("sha256", "size_bytes")},
                      {key: expected[key] for key in ("sha256", "size_bytes")}, "native dependency source bytes")
        submodules_by_name = {row["path"]: row for row in submodules["entries"]}
        for name in ("softfloat", "ramulator"):
            pin = dependency_contract.PINS[name]
            require(pin["path"] in submodules_by_name, "required dependency submodule is absent")
            _same(submodules_by_name[pin["path"]]["revision"], pin["revision"], "native submodule source pin")
        for row in self.dependency_document["helper_sources"]:
            require(row["path"] in self.sources, "dependency build helper was not retained by native admission")
            _same(self.sources[row["path"]], row, "shared dependency/native helper source")
        for name, identity in self.dependency_document["tools"].items():
            if name in self.tools:
                _same(self.tools[name], identity, "shared dependency/native tool")
        products = self.dependency_document["products"]
        expected_dependencies = [{"path": relative, "sha256": products[name]["sha256"],
                                  "size_bytes": products[name]["size_bytes"]}
                                 for name, relative in dependency_contract.PRODUCTS.items()]
        _same(self.dependencies, expected_dependencies, "fresh dependency products consumed by native builds")
        _same(self.report["dependency_admission"], self.admission_summary, "recomputed dependency admission")
        for key in ("dependency_admission_before", "dependency_admission_after"):
            _same(self.report[key], self.admission_stability, "dependency admission stability")
        retained_receipt = self.report["retained_dependency_receipt"]
        _same(self.verified(retained_receipt, "artifacts/dependency-receipt/report.json"),
              self.dependency_body, "native retained dependency original")

    def model_link(self):
        """Join retained model objects, archive members, map and staged products."""
        products = self.dependency_document["products"]
        softfloat = products["softfloat"]
        members = self.dependency_verification["archives"]["softfloat"]["members"]
        softfloat_name = "artifacts/dependencies/" + dependency_contract.PRODUCTS["softfloat"]
        archive = binary.validate_archive(self.verified(self.descriptors[softfloat_name]), members)
        _same((archive["sha256"], archive["size_bytes"]),
              (softfloat["sha256"], softfloat["size_bytes"]), "model selected SoftFloat archive")
        archives = {softfloat["staged_path"]: members}
        for row in self.dependency_document["external_archives"]:
            # verify_view already rehashed and parsed these exact retained bytes.
            # Their producer absolute names are lookup keys, never local paths.
            archives[row["original_path"]] = row["members"]
        map_row = self.model_payloads["artifacts/" + self.variant_id + "/dependency-model/" + admission.MODEL_MAP]
        map_body = self.verified(map_row)
        checked = binary.validate_link_map(map_body.decode("utf-8"),
            cwd=str(self.build / "sim/simx"), archives=archives,
            required_archives=[softfloat["staged_path"]],
            required_loads=[products[name]["staged_path"] for name in ("ramulator", "extension")])
        objects = sorted(str(build_records.expected_object(name, str(self.build)))
                         for name in build_records.MODEL_SOURCES)
        _same(self.model_build["object_paths"], objects, "model compiler object population")
        _same(self.model_build["dependency_link_map"], str(self.build / admission.MODEL_MAP),
              "model compiler map selection")
        loads = Counter(checked["loads"])
        require(all(loads[name] == 1 for name in objects),
                "model link map lacks an exact production object load")
        local_objects = [name for name in checked["loads"]
                         if PurePosixPath(name).is_relative_to(self.build)
                         and name.endswith(".o")]
        _same(sorted(local_objects), objects, "model map contains an unplanned build object")

        def identity(name):
            return dict(self.frozen[name], path=str(self.build / name))

        result = {"dependency_receipt_sha256": self.dependency_receipt_sha256,
            "map": identity(admission.MODEL_MAP), "verification": checked,
            "model": identity("sw/runtime/libsimx.so"),
            "objects": [identity(PurePosixPath(name).relative_to(self.build).as_posix()) for name in objects],
            "products": products, "source_to_model_link_verified": True,
            **dict.fromkeys(manifest.FALSE_CLAIMS, False)}
        _same(self.variant["dependency_receipt_sha256"], self.dependency_receipt_sha256,
              "variant selected dependency receipt")
        _same(self.variant["dependency_model_link"], result, "recomputed source to model link")
        self.model_links[self.variant_id] = result

    def generated(self):
        row = self.variant
        self.artifacts = row["artifacts_before"]
        self.frozen = self.inventory(self.artifacts, "frozen artifacts", expected=tuple(sorted(set(replay_build.artifact_names(self.build)) | {admission.MODEL_MAKEFILE, admission.MODEL_MAP})))
        for value in self.frozen.values():
            _integer(value["size_bytes"], 1, self.api.MEMBER_BYTES, "frozen artifact bytes")
        _same(row["artifacts_after"], self.artifacts, "artifact stability")
        generated = self.inventory(row["generated_identity"], "generated identity", expected=GENERATED + COPIED)
        for name, value in generated.items():
            _same(value, self.frozen[name], "generated file identity")
        configured = sorted((*GENERATED, *COPIED, APP + "/Makefile", APP + "/backend.mk", admission.MODEL_MAKEFILE))
        backend = sorted((*configured, HEADER_PROBE, *BACKEND_STAMPS))
        frozen = sorted((*backend, APP + "/config.stamp"))
        stages = row["retained_builds"]
        require(type(stages) is list and len(stages) == 3, "missing retained build stages")
        self.stages = {}
        for stage, (label, names) in zip(stages, (("configured", configured), ("backend", backend), ("frozen", frozen))):
            _fields(stage, ("stage", "files"), "retained stage")
            _same(stage["stage"], label, "build stage order")
            prefix = "artifacts/" + self.variant_id + "/" + label + "/"
            values = self.inventory(stage["files"], "build " + label,
                                    expected=[prefix + name for name in names])
            self.stages[label] = {}
            for name in names:
                value = values[prefix + name]
                _same(value, dict(self.frozen[name], path=prefix + name), "retained build identity")
                self.verified(value, prefix + name)
                self.stages[label][name] = value
        _same(self.build_body(HEADER_PROBE), producer.HEADER_PROBE_CONTENT, "include probe")
        for name in (*COPIED, APP + "/Makefile", APP + "/backend.mk", admission.MODEL_MAKEFILE):
            _same(self.build_body(name), self.source_body(name), "copied source " + name)
        self._configuration_text()
        prefix = "artifacts/" + self.variant_id + "/binaries/"
        self.binary_payloads = self.inventory(row["retained_binary_payloads"], "binary payloads",
                                             expected=[prefix + name for name in BINARY_FILES])
        for name in BINARY_FILES:
            value = self.binary_payloads[prefix + name]
            _same(value, dict(self.frozen[name], path=prefix + name), "retained binary identity")
            self.payload(value, prefix + name)
        self.libraries = {name: str(self.build / "sw/runtime" / name)
                          for name in ("libvortex.so", "libvortex-simx.so", "libsimx.so")}
        self.libraries.update({
            "libramulator.so": str(self.paths["source"] / "third_party/ramulator/libramulator.so"),
            "libramulator-vortex.so": str(self.paths["source"] / "third_party/ramulator_ext/libramulator-vortex.so")})
        _same(row["expected_loaded_libraries"], self.libraries, "selected loaded-library paths")
        names = [build_records.expected_object(name, str(self.build)).relative_to(self.build).as_posix()
                 for name in build_records.MODEL_SOURCES] + [admission.MODEL_MAP]
        prefix = "artifacts/" + self.variant_id + "/dependency-model/"
        self.model_payloads = self.inventory(row["retained_dependency_model_payloads"],
            "retained dependency model payloads", expected=[prefix + name for name in names])
        for name in names:
            value = self.model_payloads[prefix + name]
            _same(value, dict(self.frozen[name], path=prefix + name), "retained model object/map identity")
            self.payload(value, prefix + name)

    def compiler_commands(self):
        source, build, env = self.paths["source"], self.build, self.env
        self.command(self.variant_id + "-configure", [source / "configure", "--xlen=64", "--profile=p02-tfr",
                     "--osversion=ubuntu/focal", "--tooldir=" + str(self.paths["tools"])], build, env,
                     self.limits["configure_timeout_seconds"])
        preprocessor = [self.tools["g++"]["path"], "-E", "-dM", "-x", "c++"]
        tail = ["-include", build / "sw/VX_config.h", "/dev/null"]
        text, _ = self.command(self.variant_id + "-header", [*preprocessor, "-DVX_CFG_XLEN=64",
                               "-DVX_CFG_XLEN_64", *tail], build, env, 30, read=True)
        initial = validate_header_macros(text)
        _same(self.variant["header_macros"], initial, "initial header macros")
        for language, relative in (("cpp", "sw/VX_config.h"), ("verilog", "hw/VX_config.vh")):
            self.command(self.variant_id + "-" + language + "-header-reproduce", [self.tools["python3"]["path"],
                         source / "ci/gen_config.py", "--config=" + str(source / "VX_config.toml"), "--profile=p02-tfr",
                         "--format=" + language, "--output=" + str(build / PurePosixPath(HEADER_PROBE).parent / PurePosixPath(relative).name)],
                         build, dict(env, XLEN="64"), 30)
        raw_flags = "-DITYPE=" + self.fmt + " -DOTYPE=fp32 -DKUNROLL=1"
        text, _ = self.command(self.variant_id + "-expected-flags", [self.tools["python3"]["path"],
                               source / "ci/gen_config.py", "--config=" + str(source / "VX_config.toml"),
                               "--profile=p02-tfr", "--xlen=64", "--format=cflags",
                               "--cflags=" + raw_flags + " -DVX_CFG_XLEN=64"], build, env, 30, read=True)
        self.generated_flags = validate_generated_flags(text, source_body=self.source_body, fmt=self.fmt)
        flags = _stamp_flags(text, "independently generated preflight flags")
        require(flags and all(flag.startswith("-D") for flag in flags), "generated flags contain non-definitions")
        text, _ = self.command(self.variant_id + "-expected-expanded-header", [*preprocessor, *flags,
                               *("-D" + name + "_DISABLE" for name in DISABLED), *tail],
                               build, env, 30, read=True)
        expanded = dict(validate_header_macros(text), **{build_records.GUARD: "1"})
        backend = dict(initial, PERF_ENABLE="1", **{name + "_DISABLE": "1" for name in DISABLED},
                       **{build_records.GUARD: "1"})
        _same(self.variant["expected_expanded_header_macros"], expanded, "expanded configuration")
        _same(self.variant["expected_backend_header_macros"], backend, "backend configuration")
        make = [self.tools["make"]["path"], "--no-print-directory", "-j" + str(self.limits["jobs"]),
                "THREADS=1", "CXX=" + self.tools["g++"]["path"]]
        current = dict(env, CONFIGS=raw_flags + " " + build_records.GUARD_FLAG, PERF="1")
        runtime, app = build / "sw/runtime", build / APP
        model_text, model_command = self.command(self.variant_id + "-dependency-model",
            [*make, "CC=" + self.tools["gcc"]["path"], "DESTDIR=" + str(runtime),
             "-f", build / admission.MODEL_MAKEFILE, runtime / "libsimx.so"],
            build / "sim/simx", current, self.limits["build_timeout_seconds"], read=True)
        _same(self.variant["dependency_model_build_command"], model_command["id"], "model command binding")
        backend_text, backend_command = self.command(self.variant_id + "-backend",
            [*make, "CC=" + self.tools["gcc"]["path"], "DESTDIR=" + str(runtime),
             "-f", app / "backend.mk", runtime / "libvortex-simx.so"],
            runtime / "simx", current, self.limits["build_timeout_seconds"], read=True)
        runtime_stamp = self.build_body(BACKEND_STAMPS[0]).decode("utf-8")
        model_stamp = self.build_body(BACKEND_STAMPS[1]).decode("utf-8")
        link_stamp = self.build_body(BACKEND_STAMPS[2]).decode("utf-8")
        self.backend_build = _backend_graph(model_text, backend_text,
            compiler=self.tools["g++"]["path"], make=self.tools["make"]["path"],
            source=source, build=build, source_body=self.source_body)
        self.model_build = build_records.validate_build_commands(model_text + "\n" + backend_text,
            runtime_stamp, model_stamp, link_stamp, source=str(source), build=str(build),
            compiler=self.tools["g++"]["path"], make=self.tools["make"]["path"], fmt=self.fmt,
            source_files=list(self.sources), dependency_map=str(build / admission.MODEL_MAP))
        _same(self.variant["model_build_records"], self.model_build, "original model build records")
        _same(self.variant["backend_build_command"], backend_command["id"], "backend command binding")
        application_text, application_command = self.command(self.variant_id + "-application",
            [*make, "--output-sync=target", "all"], app, current, self.limits["build_timeout_seconds"], read=True)
        app_stamp = self.build_body(APP + "/config.stamp").decode("utf-8")
        self.host_build = producer.validate_host_build(application_text, app_stamp,
            source=source, build=build, compiler=self.tools["g++"]["path"])
        _same(self.variant["host_build_records"], self.host_build, "original host build records")
        _same(self.variant["application_build_command"], application_command["id"], "application command binding")
        self.compiler = build_records.validate_records(runtime_stamp, model_stamp, app_stamp,
            fmt=self.fmt, source=str(source), build=str(build), jobs=self.limits["jobs"])
        _same(self.variant["compiler_records"], self.compiler, "independent original compiler records")
        self.application_build = application.validate_application_build(application_text, app_stamp,
            source=source, build=build, tools_root=self.paths["tools"], tools=self.tools, fmt=self.fmt,
            compiler_records=self.compiler, source_body=self.source_body)
        _same(self.variant["application_build_records"], self.application_build, "complete application build binding")
        self.model_link()
        self.effective = {}
        directories = {"runtime": runtime / "simx", "backend_cpp": build / "sim/simx", "kernel": app, "host": app}
        for record in self.compiler:
            role = record["role"]
            command_id = self.variant_id + "-" + role + "-header"
            text, _ = self.command(command_id, [*preprocessor, *record["macro_flags"],
                                   *("-I" + name for name in record["include_paths"]), build / HEADER_PROBE],
                                   directories[role], env, 30, read=True)
            expected = backend if role == "backend_cpp" else expanded
            self.effective[role] = {"command_id": command_id,
                "macros": build_records.validate_effective_header(text, expected, role=role)}
        _same(self.variant["effective_headers"], self.effective, "effective compiler configuration")

    def build_binding(self):
        binding = {"contract_id": admission.CONTRACT_ID, "contract_sha256": self.report["contract_sha256"],
            "source": self.source, "loaded_helpers": self.report["loaded_helpers"],
            "format": self.fmt, "backend": "simx", "case": self.case, "corpus": self.report["corpus"],
            "profile_sha256": PROFILE_SHA256, "kernel_source_sha256": producer.KERNEL_SHA256,
            "warm_contract_sha256": manifest.WARM_CONTRACT_SHA256, "compiler_records": self.compiler,
            "model_build_records": self.model_build, "host_build_records": self.host_build,
            "effective_headers": self.effective, "generated_identity": self.variant["generated_identity"],
            "artifacts": self.artifacts, "tools": self.tools, "dependencies": self.dependencies,
            "expected_loaded_libraries": self.libraries, "simulation_workers": 1,
            "performance_environment": {"PERF": "1"},
            "unresolved_obligations": list(manifest.UNRESOLVED_OBLIGATIONS),
            **dict.fromkeys(manifest.FALSE_CLAIMS, False)}
        binding.update(lifetime_contract=lifetime.contract(),
            preflight_contract_sha256=qualification_id(self.contract),
            dependency_receipt_sha256=self.dependency_receipt_sha256,
            dependency_admission=self.admission_summary,
            application_build_records=self.application_build,
            dependency_model_link=self.model_links[self.variant_id])
        original = self.api.strict_json(self.verified(self.variant["binding"],
            "snapshots/" + self.variant_id + "-build-binding.json"))
        _same(original, binding, "reconstructed common build binding")
        self.build_id = qualification_id(binding)
        _same(self.variant["build_binding_sha256"], self.build_id, "common build identity")
        self.bindings[self.variant_id] = binding

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
            binding = {"contract_id": admission.CONTRACT_ID, "contract_sha256": self.report["contract_sha256"],
                "build_binding_sha256": self.build_id, "build": self.bindings[self.variant_id], "process": planned}
            binding.update(lifetime_contract=lifetime.contract(),
                preflight_contract_sha256=qualification_id(self.contract),
                dependency_receipt_sha256=self.dependency_receipt_sha256)
            actual = self.api.strict_json(self.verified(row["binding"], "snapshots/" + process_id + "-binding.json"))
            _same(actual, binding, "reconstructed process binding")
            binding_id = qualification_id(binding)
            for key, expected in (("execution_binding_sha256", binding_id), ("build_binding_sha256", self.build_id),
                ("command_id", process_id), ("log", "logs/" + process_id + ".log")):
                _same(row[key], expected, "process " + key)
            app = self.build / APP
            text, receipt = self.command(process_id, [app / "ai_counter_preflight", lifetime.APP_FLAG, "--policy", planned["policy"],
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
                "loaded_libraries": witness["loaded_libraries"],
                "lifetime_runs": len(observed["lifetime"]["runs"]),
                "terminal_pending_reads": observed["lifetime"]["destruction"]["before"]["pending_reads"]})
            self.stability_labels.append("after-process-" + process_id)

    def stability(self):
        checks = self.report["stability_checks"]
        require(type(checks) is list and len(checks) == len(self.stability_labels), "missing stability observations")
        previous = self.started
        for check, label in zip(checks, self.stability_labels):
            _fields(check, ("at", "label", "source_sha256", "tools_sha256", "dependencies_sha256", "dependency_admission"), "stability observation")
            _same(check["label"], label, "stability order")
            at = _timestamp(check["at"])
            require(previous <= at <= self.finished, "stability timestamps are outside chronology")
            previous = at
            for name, value in (("source", self.source), ("tools", self.tools), ("dependencies", self.dependencies)):
                _same(check[name + "_sha256"], qualification_id(value), "stability identity " + name)
            _same(check["dependency_admission"], self.admission_stability, "dependency stability observation")

    def run(self):
        _fields(self.report, REPORT_FIELDS, "managed preflight report")
        for key, expected in (("schema_version", 1), ("contract_id", admission.CONTRACT_ID),
            ("scope", admission.SCOPE), ("state", "finished"), ("outcome", "pass"),
            ("reason", None), ("failures", []), ("native_execution", "run"), ("native_preflight_passed", True),
            ("native_lifetime_passed", True), ("dependency_source_to_loaded_binary_verified", True),
            ("dependency_receipt_sha256", self.dependency_receipt_sha256),
            ("expected_revision", self.revision), ("expected_counts", COUNTS), ("completed_counts", COUNTS),
            ("expected_processes", self.plan), ("unresolved_obligations", list(manifest.UNRESOLVED_OBLIGATIONS)),
            ("retained_files_stable", True), ("limitations", [*admission.LIMITATIONS, *producer.base.PROCESS_LIMITATIONS])):
            _same(self.report[key], expected, "report." + key)
        for name in manifest.FALSE_CLAIMS:
            _same(self.report[name], False, "report." + name)
        self.started, self.finished = (_timestamp(self.report[key]) for key in ("started_at", "finished_at"))
        require(self.started <= self.finished, "execution timestamps are reversed")
        require(type(self.report["commands"]) is list and len(self.report["commands"]) == 37,
                "unexpected command inventory")
        require(type(self.report["variants"]) is list and len(self.report["variants"]) == 2, "expected two format builds")
        require(type(self.report["processes"]) is list and len(self.report["processes"]) == 4,
                "expected exactly four managed processes")
        self.budget()
        self.provenance()
        self.paths_and_tools()
        _same(str(self.paths["source"]), self.dependency_document["paths"]["source"],
              "dependency/native measurement source")
        for name in ("g++", "gcc", "make", "python3", "executing_python", "clang", "riscv-gcc"):
            text, _ = self.command("version-" + name.replace("+", "p"), [self.tools[name]["path"], "--version"],
                self.paths["work"], self.env, 30, read=True)
            require(text.strip(), "empty version observation")
            if name in ("python3", "executing_python"):
                _same(text, "Python 3.12.14\n", "executing interpreter version output")
        for self.variant, self.fmt in zip(self.report["variants"], manifest.FORMATS):
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
        return {"schema_version": 1, "contract_id": CONTRACT_ID,
            "scope": "complete-dependency-lifetime-retained-consistency", "outcome": "pass",
            "native_execution": "not_run", "retained_code_executed": False,
            "retained_consistency": True, "dependency_source_to_loaded_binary_consistent": True,
            **dict.fromkeys(manifest.FALSE_CLAIMS, False),
            "unresolved_obligations": list(manifest.UNRESOLVED_OBLIGATIONS),
            "source_revision": self.revision, "source_tree": self.source["checkout"]["tree"],
            "source_snapshot_sha256": qualification_id(self.source), "report_identity": self.view.identity("report.json"),
            "source_manifest_sha256": self.source_manifest_sha256,
            "dependency_receipt_sha256": self.dependency_receipt_sha256,
            "commands_checked": self.command_index, "retained_source_files_checked": len(self.sources),
            "retained_payload_files_checked": len(self.payload_members), "retained_payload_bytes_checked": self.payload_bytes,
            "retained_files_checked": len(retained), "counts": counts, "processes": self.process_results,
            "build_binding_ids": {name: qualification_id(value) for name, value in self.bindings.items()},
            "application_builds": self.application_builds, "generated_builds": self.generated_builds,
            "backend_builds": self.backend_builds, "dependency_model_links": self.model_links,
            "limitations": list(LIMITATIONS)}


def _hosted_identity(replay, outer, dependency_view):
    """Bind the original's job envelope; separate probes remain outside scope."""
    job = outer.json("job.json")
    expected = {
        "GITHUB_SHA": replay.revision, "GITHUB_REPOSITORY": "baabi-boo/AI-GPU",
        "GITHUB_JOB": "dependency-provenance", "schema_version": 1,
        "contract_id": admission.CONTRACT_ID, "scope": "fresh-selected-dependency-lifetime",
        "record_stage": "job-initialization", "requested_xlen": 64,
        "requested_profile": "p02-tfr", "requested_perf": "on",
        "requested_formats": list(manifest.FORMATS), "requested_policies": list(manifest.POLICIES),
        "requested_processes": 4, "requested_launches": 132, "requested_checked_words": 4224,
        "requested_build_jobs": 2, "requested_simulation_workers": 1,
        "native_execution": "not_run", "native_preflight_passed": False,
        "native_lifetime_passed": False, "fresh_dependency_build_passed": False,
        "dependency_source_to_loaded_binary_verified": False,
        **dict.fromkeys(manifest.FALSE_CLAIMS, False),
    }
    _fields(job, set(expected) | {"GITHUB_EVENT_NAME", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_REF",
        "workflow_sha256", "free_disk_bytes_before_cache", "available_memory_bytes_before_cache"}, "hosted job")
    for name, value in expected.items():
        _same(job[name], value, "hosted job " + name)
    _same(job["requested_build_jobs"], replay.limits["jobs"], "hosted build parallelism")
    require(job["GITHUB_EVENT_NAME"] in ("push", "pull_request", "workflow_dispatch"), "unsupported hosted event")
    for name in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"):
        require(type(job[name]) is str and re.fullmatch(r"[1-9][0-9]{0,20}", job[name]), "invalid hosted run identity")
    require(_valid_hosted_ref(job["GITHUB_REF"]), "invalid hosted Git ref")
    if job["GITHUB_EVENT_NAME"] == "push":
        _same(job["GITHUB_REF"], "refs/heads/master", "hosted push ref")
    elif job["GITHUB_EVENT_NAME"] == "pull_request":
        require(re.fullmatch(r"refs/pull/[1-9][0-9]*/merge", job["GITHUB_REF"]), "hosted pull request ref differs")
    else:
        require(job["GITHUB_REF"].startswith(("refs/heads/", "refs/tags/")), "hosted dispatch ref differs")
    _integer(job["free_disk_bytes_before_cache"], 15 * 1024**3, 2**64 - 1, "hosted initial disk")
    _integer(job["available_memory_bytes_before_cache"], 4 * 1024**3, 2**64 - 1, "hosted initial memory")
    workflow = outer.read("workflow.yml", limit=256 * 1024)
    _same(workflow, replay.source_body(".github/workflows/p06-dependency-provenance.yml"), "hosted workflow source")
    _same(job["workflow_sha256"], hashlib.sha256(workflow).hexdigest(), "hosted workflow digest")
    provision = outer.json("python-provision.json")
    _fields(provision, ("python_version", "implementation", "platform", "executable", "python3_on_path"),
            "hosted Python provision")
    for name, value in (("python_version", [3, 12, 14]), ("implementation", "CPython"),
                        ("platform", "linux"), ("python3_on_path", replay.tools["python3"]["path"])):
        _same(provision[name], value, "hosted Python " + name)
    replay.api.recorded_absolute(provision["executable"])
    require(provision["executable"] in (replay.tools["executing_python"]["path"],
            replay.tools["executing_python"]["resolved_path"]), "hosted executing interpreter differs")
    _same(outer.json("dependency-receipt.json"), {
        "path": "dependency-build/report.json", "sha256": replay.dependency_receipt_sha256,
        "size_bytes": len(replay.dependency_body), "expected_revision": replay.revision}, "hosted dependency intake")
    preparation_body = dependency_view.verified(replay.dependency_document["preparation"])
    _same(outer.read("dependency-preparation.json", limit=dependency_contract.MAX_RECEIPT_BYTES),
          preparation_body, "hosted dependency preparation copy")
    _same(outer.json("execution.log"), {
        "outcome": "pass", "reason": None, "report": str(replay.paths["output"] / "report.json"),
        "completed_counts": COUNTS, "native_preflight_passed": True, "native_lifetime_passed": True,
        "dependency_source_to_loaded_binary_verified": True,
        **dict.fromkeys(manifest.FALSE_CLAIMS, False)}, "hosted execution terminal output")
    names = ("job.json", "workflow.yml", "python-provision.json", "dependency-receipt.json",
             "dependency-preparation.json", "execution.log")
    return {"validation": "pass", "job": job, "origin_authenticated": False,
        "outer_files": [outer.identity(name, limit=dependency_contract.MAX_RECEIPT_BYTES) for name in names],
        "other_outer_members_semantically_verified": False,
        "other_outer_members": [name for name in outer.files() if name not in names
            and not name.startswith(("dependency-build/", "native-lifetime/"))]}


def replay_archive(path, sha256, *, expected_revision, expected_receipt_sha256,
                   expected_native_report_sha256, expected_source_manifest_sha256, prefix=""):
    """Verify the exact native original and dependency packet in a hosted ZIP."""
    for value, label in ((sha256, "original ZIP"), (expected_receipt_sha256, "dependency receipt"),
            (expected_native_report_sha256, "native report"), (expected_source_manifest_sha256, "native source manifest")):
        _pin(value, label)
    require(type(expected_revision) is str and dependency_receipt.REVISION.fullmatch(expected_revision),
            "exact external source revision is required")
    require(type(prefix) is str, "hosted prefix must be literal text")
    require(_reader_sources() == TRUSTED_READER_SOURCES, "trusted native replay source changed after import")
    api = dependency_replay._archive_api()
    if prefix:
        api.relative_name(prefix)
    try:
        with api.ArchiveReader(path, sha256) as archive:
            outer = archive.view(prefix)
            stem = prefix + "/" if prefix else ""
            dependency_view = archive.view(stem + "dependency-build")
            native_view = archive.view(stem + "native-lifetime")
            native_body = native_view.read("report.json", limit=dependency_contract.MAX_RECEIPT_BYTES)
            _same(hashlib.sha256(native_body).hexdigest(), expected_native_report_sha256,
                  "externally pinned native report")
            checked = dependency_replay.verify_view(dependency_view, expected_revision=expected_revision,
                expected_receipt_sha256=expected_receipt_sha256)
            dependency_body = dependency_view.read("report.json", limit=dependency_contract.MAX_RECEIPT_BYTES)
            _same(hashlib.sha256(dependency_body).hexdigest(), expected_receipt_sha256, "dependency report after replay")
            dependency_document = dependency_receipt.decode(dependency_body)
            replay = _NativeReplay(native_view, api, expected_revision,
                dependency_document=dependency_document,
                dependency_verification=checked["retained_dependency_verification"],
                dependency_body=dependency_body, dependency_receipt_sha256=expected_receipt_sha256,
                source_manifest_sha256=expected_source_manifest_sha256)
            result = replay.run()
            result["hosted_identity"] = _hosted_identity(replay, outer, dependency_view)
            result.update(dependency_verification=checked,
                native_report_sha256=expected_native_report_sha256, prefix=prefix,
                archive_read=archive.receipt(), trusted_reader_sources=TRUSTED_READER_SOURCES,
                trusted_archive_reader={"path": archive_helpers.ARCHIVE_READER_PATH,
                                        "sha256": archive_helpers.ARCHIVE_READER_SHA256})
        require(_reader_sources() == TRUSTED_READER_SOURCES, "trusted native replay source changed during review")
        return result
    except (KeyError, TypeError, IndexError, UnicodeError, OverflowError, RecursionError) as error:
        raise ValueError("malformed retained dependency/native packet: " + str(error)) from error


TRUSTED_READER_SOURCES = _reader_sources()


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--dependency-receipt-sha256", required=True)
    parser.add_argument("--native-report-sha256", required=True)
    parser.add_argument("--source-manifest-sha256", required=True,
                        help="external SHA-256 of native-lifetime/snapshots/source-before.json")
    parser.add_argument("--prefix", default="", help="literal optional hosted root directory inside the ZIP")
    parser.add_argument("--output", type=Path)
    return parser


def main(argv=None):
    args = argument_parser().parse_args(argv)
    try:
        result = replay_archive(args.archive, args.sha256, expected_revision=args.source_revision,
            expected_receipt_sha256=args.dependency_receipt_sha256,
            expected_native_report_sha256=args.native_report_sha256,
            expected_source_manifest_sha256=args.source_manifest_sha256, prefix=args.prefix)
        body = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
        if args.output is None:
            print(body, end="")
        else:
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(body)
            print(json.dumps({"outcome": "pass", "scope": result["scope"], "report": str(args.output),
                "retained_consistency": True, "native_execution": "not_run", "retained_code_executed": False,
                **dict.fromkeys(manifest.FALSE_CLAIMS, False)}, sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({"outcome": "fail", "reason": str(error), "retained_consistency": False,
            "native_execution": "not_run", "retained_code_executed": False,
            **dict.fromkeys(manifest.FALSE_CLAIMS, False)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    sys.exit(main())
