#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Review the two separate dependency controls as inert, caller-pinned bytes.

The native/dependency original is validated first. Producer paths are names for
joins only: this module never opens them, imports retained Python, or invokes a
compiler, loader, application or retained command. A consistent synthetic
packet remains synthetic. Execution evidence belongs to its original producer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys

sys.dont_write_bytecode = True

from baseline_process import LIMITATIONS as PROCESS_LIMITATIONS
import p06_dependency_contract as contract
import p06_dependency_native_replay as native_replay
import p06_dependency_receipt as receipts
import p06_dependency_record as recorder
import p06_dependency_substitution as substitution
import p06_pending_probe as probe
from p06_replay import _fields, _integer, _number, _same, _timestamp, require


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_ID = "p06-dependency-controls-replay-v1"
RUNTIME_DIAGNOSTIC_SOURCE = "sim/common/dram_sim.cpp"
RUNTIME_DIAGNOSTIC_NAME = "ramulator.stats.log"
PROBE_HELPERS = tuple("ci/project/" + name + ".py" for name in """
baseline_inventory baseline_matrix baseline_packet_contract baseline_packet_io
baseline_process compiler_records p02_fixture_oracle p02_layout_fixture_oracle
p02_matrix p02_matrix_records p02_wmma_fixtures p02_wmma_numerical_fixture_oracle
p03_execute p03_execution_records p04_execution_records p04_fixture_adapter
p04_model_contract p04_reference p06_compiler_records p06_contract
p06_dependency_contract p06_managed_preflight_build p06_managed_preflight_contract
p06_managed_preflight_execute p06_pending_probe p06_records
p06_warm_compiler_records p06_warm_contract p06_warm_execute p06_warm_records
p06_workspace_compiler_records p06_workspace_records preflight
""".split())
SUBSTITUTION_HELPERS = tuple(sorted(set(PROBE_HELPERS) | {
    "ci/project/" + name + ".py" for name in """
p06_dependency_admission p06_dependency_binary p06_dependency_build
p06_dependency_graph p06_dependency_receipt p06_dependency_record
p06_dependency_sources p06_dependency_substitution
p06_dependency_local_prepare p06_local_toolchain
p06_managed_preflight_application_build p06_managed_preflight_records
p06_managed_preflight_source_export p06_managed_preflight_sources
p06_native_lifetime_contract p06_native_lifetime_records
""".split()}))
PROBE_FIELDS = {
    "schema_version", "contract_id", "started_at", "finished_at", "state", "outcome",
    "reason", "expected_revision", "native_execution", "native_probe_passed",
    "zero_mutation_rejected", "commands", "failures", "budget", "limitations",
    "dependency_receipt_sha256", "managed_contract_id", "inputs_before", "inputs_after",
    "format", "compiler_records", "probe_flags", "expected_libraries", "environment",
    "managed_build_binding_sha256", "products", *contract.FALSE_CLAIMS,
}
SUBSTITUTION_FIELDS = {
    "schema_version", "contract_id", "expected_revision", "dependency_receipt_sha256",
    "state", "outcome", "reason", "failures", "native_execution", "control_passed",
    "alternate_dependency_built", "numerical_control_passed", "original_provenance_rejected",
    "commands", "control_counts", "budget", "environment", "managed_population_included",
    "limitations", "started_at", "finished_at", "inputs_before", "inputs_after",
    "original_libraries", "managed_build_binding_sha256", "helper_sources", "source_derivation",
    "tool_config", "dependency_control", "control_products_before", "control_products_after",
    "control_binding", "control_binding_sha256", "observation", "expected_libraries",
    "rejection", "retained_files", *contract.FALSE_CLAIMS,
}
LIMITATIONS = [
    "This is retained consistency review; no native process, compiler, retained code or producer path is executed or opened by replay.",
    "The four managed processes (132 launches, 4,224 words), the pending accessor probe and its zero control, and the one substitution process (33 launches, 1,056 words) remain separate populations.",
    "External ZIP, revision, dependency receipt, native report, native source snapshot and both control report pins identify the requested originals; they do not authenticate a producer.",
    "Shared control inputs are joined to the verified native/dependency original. Additional control sources are bound by each external report pin and the trusted current control source bytes.",
    "Original tool identities, system-header/support-file coverage and before/after stability have the same limitations as the selected dependency and native readers.",
    "A consistently synthetic or forged packet is not promoted into actual execution evidence.",
    "The exact Ramulator destructor side output is byte-accounted as an opaque runtime diagnostic; its contents do not contribute numerical, performance or qualification evidence.",
    "Complete 40-component qualification, absolute no-wrap bounds, warm performance and phase acceptance remain separate; all seven claims remain false.",
]


def _digest(body):
    return hashlib.sha256(body).hexdigest()


def _descriptor(name, body):
    return {"path": name, "sha256": _digest(body), "size_bytes": len(body)}


def _reader_sources():
    rows = {row["path"]: row for row in native_replay._reader_sources()}
    for name in ("p06_dependency_control_replay", "p06_pending_probe", "p06_dependency_substitution",
                 "p06_dependency_build"):
        path = ROOT / "ci/project" / (name + ".py")
        module = sys.modules[__name__] if name == "p06_dependency_control_replay" else sys.modules[name]
        require(Path(module.__file__).resolve(strict=True) == path,
                "control replay helper loaded outside the trusted checkout")
        rows[path.relative_to(ROOT).as_posix()] = _descriptor(path.relative_to(ROOT).as_posix(), path.read_bytes())
    rows[probe.PROBE_SOURCE] = _descriptor(probe.PROBE_SOURCE, (ROOT / probe.PROBE_SOURCE).read_bytes())
    return [rows[name] for name in sorted(rows)]


TRUSTED_READER_SOURCES = _reader_sources()
TRUSTED_CONTROL_SOURCES = {row["path"]: row for row in TRUSTED_READER_SOURCES}


class _Packet:
    """One-read byte cache; exact semantic membership is checked at completion."""

    def __init__(self, view, api, expected_report_sha256):
        self.view, self.api, self.cache = view, api, {}
        self.total = 0
        native_replay._pin(expected_report_sha256, "control report")
        body = self.read("report.json", limit=contract.MAX_RECEIPT_BYTES)
        _same(_digest(body), expected_report_sha256, "externally pinned control report")
        self.report = receipts.decode(body)

    def read(self, name, *, limit=contract.MAX_FILE_BYTES):
        self.api.relative_name(name)
        if name not in self.cache:
            body = self.view.read(name, limit=limit)
            require(type(body) is bytes and len(body) <= limit, "control member exceeds its byte bound")
            self.total += len(body)
            require(self.total <= contract.MAX_PACKET_BYTES, "control packet exceeds its byte bound")
            self.cache[name] = body
        require(len(self.cache[name]) <= limit, "control member exceeds its byte bound")
        return self.cache[name]

    def row(self, name):
        return _descriptor(name, self.read(name))

    def verified(self, row, expected=None):
        self.api.descriptor(row)
        require(expected is None or row["path"] == expected, "control retained path differs")
        _same(self.row(row["path"]), row, "control retained identity")
        return self.read(row["path"])

    def finish(self):
        _same(set(self.view.files()), set(self.cache), "complete control packet member inventory")
        return {"retained_files_checked": len(self.cache), "retained_bytes_checked": self.total}


def _report(packet, native, fields, identifier):
    value = packet.report
    _fields(value, fields, "control report")
    for key, expected in (("schema_version", 1), ("contract_id", identifier), ("state", "finished"),
            ("outcome", "pass"), ("reason", None), ("failures", []), ("native_execution", "run"),
            ("expected_revision", native.revision), ("dependency_receipt_sha256", native.dependency_receipt_sha256)):
        _same(value[key], expected, "control report." + key)
    for name in contract.FALSE_CLAIMS:
        _same(value[name], False, "control report." + name)
    start, finish = (_timestamp(value[key]) for key in ("started_at", "finished_at"))
    require(native.finished <= start <= finish, "control timestamps precede completed native admission")


def _sources(packet, native, helpers, extra):
    retained = {}
    for name in sorted(set(helpers) | set(extra)):
        row = dict(packet.row("inputs/" + name), path=name)
        expected = native.sources.get(name, TRUSTED_CONTROL_SOURCES.get(name))
        require(expected is not None, "control source is outside the reviewed helper inventory")
        _same(row, expected, "control source identity " + name)
        retained[name] = row
    selected = dict(native.sources, **retained)
    return [selected[name] for name in sorted(selected)], retained


def _original_report(native, expected_sha256):
    row = native.view.identity("report.json", limit=contract.MAX_RECEIPT_BYTES)
    _same(row["sha256"], expected_sha256, "control admission native report pin")
    path = str(native.paths["output"] / "report.json")
    return dict(row, path=path, resolved_path=path)


def _variant(native):
    variant = native.report["variants"][0]
    _same((variant["format"], variant["backend"]), ("fp16", "simx"), "control selected native format")
    return variant


def _command(packet, row, identifier, argv, cwd, timeout, *, environment=None, native=False, negative=False):
    fields = receipts.COMMAND_FIELDS | {"native_process"} if environment is not None else (
        receipts.COMMAND_FIELDS - {"environment", "timeout_seconds"})
    _fields(row, fields, "control command " + identifier)
    expected = {"id": identifier, "argv": list(map(str, argv)), "cwd": str(cwd),
        "outcome": "fail" if negative else "pass", "exit_code": 1 if negative else 0,
        "reason": "nonzero_exit" if negative else None, "process_started": True,
        "cleanup_complete": True, "limitations": list(PROCESS_LIMITATIONS), "log": "logs/" + identifier + ".log"}
    if environment is not None:
        expected.update(environment=environment, timeout_seconds=timeout, native_process=native)
    for key, value in expected.items():
        _same(row[key], value, "control command " + identifier + "." + key)
    _number(row["duration_seconds"], 0, timeout + 10, "control command duration")
    _integer(row["peak_rss_bytes"], 0, contract.BUDGET["max_rss_bytes"], "control command peak RSS")
    _integer(row["log_size_bytes"], 0, contract.BUDGET["max_log_bytes"], "control command log size")
    return packet.verified({"path": row["log"], "sha256": row["log_sha256"],
                            "size_bytes": row["log_size_bytes"]}).decode("utf-8")


def _runtime_diagnostic(packet, native, name):
    require(name in (RUNTIME_DIAGNOSTIC_NAME, "work/" + RUNTIME_DIAGNOSTIC_NAME),
            "unexpected runtime diagnostic path")
    source = native.source_body(RUNTIME_DIAGNOSTIC_SOURCE)
    declaration = (b'  ~RamulatorDram() override {\n'
                   b'    std::ofstream nullstream("ramulator.stats.log");\n')
    require(source.count(declaration) == 1,
            "native Ramulator destructor side-output source differs")
    require(name in packet.view.files(), "required Ramulator runtime diagnostic is absent")
    body = packet.read(name, limit=contract.BUDGET["max_log_bytes"])
    require(body, "Ramulator runtime diagnostic is empty")
    # Finalization can emit .nan for an idle channel. These are inert diagnostic
    # bytes, not a parser input, a per-process transcript or measurement data.
    return dict(_descriptor(name, body), interpreted=False,
                numerical_evidence=False, performance_evidence=False,
                qualification_evidence=False)


def verify_probe_view(view, *, native, expected_report_sha256, expected_native_report_sha256):
    """Join a pending-probe view to an already fully verified native context."""
    packet = _Packet(view, native.api, expected_report_sha256)
    _report(packet, native, PROBE_FIELDS, probe.CONTRACT_ID)
    report, variant = packet.report, _variant(native)
    source, build = native.paths["source"], PurePosixPath(variant["build_dir"])
    output = native.paths["output"].parent / "pending-probe"
    runtime = build / "sw/runtime"
    for key, expected in (("native_probe_passed", True), ("zero_mutation_rejected", True),
            ("managed_contract_id", contract.MANAGED_CONTRACT_ID), ("format", "fp16"),
            ("budget", probe.BUDGET), ("managed_build_binding_sha256", variant["build_binding_sha256"])):
        _same(report[key], expected, "pending report." + key)
    limitations = list(probe.LIMITATIONS)
    limitations[2] = ("The selected model and dependencies match the completed managed build "
        "and its caller-pinned fresh dependency receipt; this probe does not replay compilation.")
    _same(report["limitations"], limitations, "pending limitations")
    sources, _ = _sources(packet, native, PROBE_HELPERS, probe.SOURCE_FILES)
    snapshots = [native.report[key] for key in ("source_before", "tools_before", "dependencies_before")]
    snapshots.append(variant["binding"])
    initial = {"checkout": native.source["checkout"], "sources": sources,
        "build": variant["artifacts_before"], "dependencies": native.dependencies,
        "compiler": native.tools["g++"], "managed_report": _original_report(native, expected_native_report_sha256),
        "managed_snapshots": snapshots}
    for key in ("inputs_before", "inputs_after"):
        _same(report[key], initial, "pending " + key)
    frozen = next(row for row in variant["retained_builds"] if row["stage"] == "frozen")
    prefix = "artifacts/" + variant["id"] + "/frozen/"
    descriptors = {row["path"][len(prefix):]: row for row in frozen["files"]}
    texts = [native.view.verified(descriptors[name]).decode("utf-8") for name in (
        "sw/runtime/simx_rt_config.stamp", "sw/runtime/simx_config.stamp", native_replay.APP + "/config.stamp")]
    flags, records = probe.probe_flags(*texts, source=Path(source), build=Path(build), fmt="fp16")
    _same(report["probe_flags"], flags, "pending revalidated compiler flags")
    _same(report["compiler_records"], records, "pending revalidated compiler records")
    _same(records, variant["compiler_records"], "pending admitted compiler records")
    libraries = {name: variant["expected_loaded_libraries"][name] for name in probe.LIBRARIES}
    _same(report["expected_libraries"], libraries, "pending loaded libraries")
    paths = ([str(native.paths["host_bin"])] if native.paths["host_bin"] is not None else [])
    paths += [str(PurePosixPath(native.tools["executing_python"]["path"]).parent), "/usr/bin", "/bin"]
    environment = {"PATH": ":".join(dict.fromkeys(paths)), "LANG": "C", "LC_ALL": "C", "TZ": "UTC",
        "TMPDIR": str(output / "tmp"), "THREADS": "1", "CCACHE_DISABLE": "1", "OBJCACHE": "",
        "PYTHONDONTWRITEBYTECODE": "1", "PERF": "1", "LD_LIBRARY_PATH": ":".join((str(runtime),
            str(source / "third_party/ramulator"), str(source / "third_party/ramulator_ext")))}
    _same(report["environment"], environment, "pending environment")
    commands, products = report["commands"], report["products"]
    require(type(commands) is list and len(commands) == 5 and type(products) is list and len(products) == 2,
            "pending command or product population differs")
    compiler = native.tools["g++"]["path"]
    require(_command(packet, commands[0], "compiler-version", [compiler, "--version"], output, 120).strip(),
            "pending compiler version observation is empty")
    observations = []
    for index, (mode, defines) in enumerate((("native", []), ("always-zero", ["-DP06_PENDING_FORCE_ZERO=1"]))):
        relative = "products/pending-reads-" + mode
        binary_path = str(output / relative)
        _command(packet, commands[1 + 2 * index], "compile-" + mode,
            [compiler, *flags, *defines, source / probe.PROBE_SOURCE, "-L" + str(runtime),
             "-Wl,-rpath," + str(runtime), "-lsimx", "-pthread", "-ldl", "-o", binary_path], output, 120)
        text = _command(packet, commands[2 + 2 * index], "run-" + mode, [binary_path], output, 180,
                        negative=bool(index))
        observed = probe.verify_output(text, libraries, zero_control=bool(index))
        identity = packet.row(relative)
        require(identity["size_bytes"] > 0, "pending executable is empty")
        _same(products[index], dict(identity, path=binary_path, resolved_path=binary_path,
                                    mode=mode, observation=observed), "pending product/raw observation")
        observations.append(observed)
    require(products[0]["sha256"] != products[1]["sha256"], "always-zero control did not change the executable bytes")
    diagnostic = _runtime_diagnostic(packet, native, RUNTIME_DIAGNOSTIC_NAME)
    return {"outcome": "pass", "report_sha256": expected_report_sha256,
        "managed_population_included": False, "processes": 2, "contexts": 2,
        "positive_pending_contexts": observations[0]["contexts"],
        "always_zero_rejection": observations[1]["expected_failure"], "commands_checked": 5,
        "runtime_diagnostic": diagnostic,
        "native_execution": "not_run", "retained_code_executed": False,
        **dict.fromkeys(contract.FALSE_CLAIMS, False), **packet.finish()}


def _substitution_records(packet, native, config, source, work):
    """Pure counterpart to the live producer's filesystem-dependent record join."""
    project_roots = (source, work, native.paths["work"],
                     PurePosixPath(native.dependency_document["paths"]["workspace"]))
    record_names = sorted(name for name in packet.view.files() if name.startswith("records/") and name.endswith(".json"))
    require(len(record_names) == 2, "substitution requires exactly two tool execution receipts")
    recorder_source = native.sources["ci/project/p06_dependency_record.py"]
    recorder_path = str(source / recorder_source["path"])
    expected_recorder = dict(recorder_source, path=recorder_path, resolved_path=recorder_path)
    rows = [receipts._validate_record(receipts.decode(packet.read(name, limit=contract.MAX_RECEIPT_BYTES)),
        config, packet.report["tool_config"]["sha256"], packet.read, expected_recorder) for name in record_names]
    require({row["role"] for row in rows} == {"compile", "link"}, "substitution recorder roles differ")
    selected = {row["role"]: row for row in rows}
    expected = substitution.recipes(source, work)
    for role, row in selected.items():
        require("records/" + row["id"] + ".json" in record_names, "substitution receipt filename differs")
        _same(row["tool_name"], "g++", "substitution selected compiler")
        _same(row["requested_arguments"], expected[role], "substitution tool recipe")
        _same(row["cwd"], str(work), "substitution tool working directory")
        _same(row["environment"]["PATH"], packet.report["environment"]["PATH"], "substitution recorder PATH")
    compiled, linked = selected["compile"], selected["link"]
    require(compiled["finished_ns"] <= linked["started_ns"], "substitution link preceded completed compilation")
    known = {}
    for component in native.dependency_document["source_manifest"]["sources"]:
        root = source / contract.PINS[component["name"]]["path"]
        for row in component["files"]:
            path = str(root / row["path"])
            known[path] = {"path": path, "sha256": row["sha256"], "size_bytes": row["size_bytes"]}
    original_path = str(source / substitution.ORIGINAL_SOURCE)
    require(original_path in known, "substitution original source is not a pinned dependency input")
    original = packet.read("inputs/gddr6-original.cpp")
    _same(_descriptor(original_path, original), known[original_path], "substitution pinned original source")
    derived = substitution.derived_source(original)
    _same(packet.read("work/" + substitution.CONTROL_SOURCE), derived, "substitution exact emitted source derivation")
    derived_path, derived_seen = str(work / substitution.CONTROL_SOURCE), False
    for row in compiled["inputs_before"]:
        if row["path"] == derived_path:
            _same(receipts.payload(row, packet.read), derived, "substitution compiled source derivation")
            _same(row["resolved_path"], derived_path, "substitution compiled source path")
            derived_seen = True
        elif PurePosixPath(row["path"]).is_relative_to(source / "third_party"):
            require(row["path"] in known and row["resolved_path"] == row["path"],
                    "substitution source/header is not a canonical pinned input")
            _same({key: row[key] for key in receipts.DESCRIPTOR_FIELDS}, known[row["path"]],
                  "substitution pinned source/header bytes")
        else:
            require(not any(PurePosixPath(row[key]).is_relative_to(root)
                            for root in project_roots for key in ("path", "resolved_path")),
                    "substitution compiler input has an unreviewed source/work file")
    require(derived_seen, "substitution compiler closure omits the derived source")
    products = native.dependency_document["products"]
    product = products["ramulator"]
    require(len(linked["inputs_before"]) == 2, "substitution link input population differs")
    by_path = {row["path"]: row for row in linked["inputs_before"]}
    _same(by_path.get(compiled["output_path"]), compiled["output"], "substitution fresh object consumption")
    ramulator = by_path.get(product["staged_path"])
    require(ramulator is not None, "substitution link omits the admitted Ramulator product")
    _same({key: ramulator[key] for key in receipts.IDENTITY_FIELDS}, {
        "path": product["staged_path"], "resolved_path": product["staged_path"],
        "sha256": product["sha256"], "size_bytes": product["size_bytes"]}, "substitution admitted Ramulator bytes")
    alternate = linked["output"]
    body = receipts.payload(alternate, packet.read)
    require(substitution.MARKER in body and alternate["sha256"] != products["extension"]["sha256"],
            "substitution extension is not the known different emitted-marker product")
    archives = {row["original_path"]: row["members"] for row in native.dependency_document["external_archives"]}
    mapping = substitution.binary.validate_link_map(receipts.payload(linked["link_map"], packet.read).decode("utf-8"),
        cwd=str(work), archives=archives, required_loads=[product["staged_path"], compiled["output_path"]])
    owned_loads = [name for name in mapping["loads"] if name not in archives
                   and any(PurePosixPath(name).is_relative_to(root) for root in project_roots)]
    _same(sorted(owned_loads), sorted((product["staged_path"], compiled["output_path"])),
          "substitution map contains an unplanned source/work input")
    for row in (compiled["output"], compiled["dependency_file"], compiled["dependency_prepass_file"],
                linked["output"], linked["link_map"]):
        relative = PurePosixPath(row["path"]).relative_to(work)
        _same(packet.read("work/" + relative.as_posix()), receipts.payload(row, packet.read),
              "substitution retained work output/payload join")
    _same(packet.read("records/.records.lock"), b"", "substitution recorder lock")
    _same(packet.read("payloads/.retention.lock"), b"", "substitution retention lock")
    derivation = {"original_source": known[original_path],
        "retained_original": packet.row("inputs/gddr6-original.cpp"),
        "derived_source": packet.row("work/" + substitution.CONTROL_SOURCE),
        "appended_declaration_sha256": _digest(substitution.MARKER_DECLARATION)}
    return {"records": [packet.row(name) for name in record_names], "compile": compiled, "link": linked,
        "map_verification": mapping,
        "alternate_product": {key: alternate[key] for key in receipts.IDENTITY_FIELDS},
        "source_derivation": derivation, "original_product": products["extension"]}


def verify_substitution_view(view, *, native, expected_report_sha256, expected_native_report_sha256):
    """Review the isolated alternate extension without calling live verify_records."""
    packet = _Packet(view, native.api, expected_report_sha256)
    _report(packet, native, SUBSTITUTION_FIELDS, substitution.CONTRACT_ID)
    report, variant = packet.report, _variant(native)
    source, build = native.paths["source"], PurePosixPath(variant["build_dir"])
    output = native.paths["output"].parent / "dependency-substitution"
    work = output / "work"
    for key, expected in (("control_passed", True), ("alternate_dependency_built", True),
            ("numerical_control_passed", True), ("original_provenance_rejected", True),
            ("managed_population_included", False), ("budget", contract.BUDGET),
            ("limitations", substitution.LIMITATIONS),
            ("managed_build_binding_sha256", variant["build_binding_sha256"]),
            ("original_libraries", variant["expected_loaded_libraries"])):
        _same(report[key], expected, "substitution report." + key)
    sources, helpers = _sources(packet, native, SUBSTITUTION_HELPERS, substitution.SOURCE_FILES)
    _same(report["helper_sources"], [helpers[name] for name in SUBSTITUTION_HELPERS], "substitution helper inventory")
    initial = {"checkout": native.source["checkout"], "source_files": sources,
        "build": variant["artifacts_before"], "managed_report": _original_report(native, expected_native_report_sha256),
        "managed_snapshots": [native.report["source_before"], native.report["tools_before"], variant["binding"]],
        "dependency_admission": native.admission_stability}
    for key in ("inputs_before", "inputs_after"):
        _same(report[key], initial, "substitution " + key)
    _same(packet.read("inputs/managed-report.json", limit=contract.MAX_RECEIPT_BYTES),
          native.view.read("report.json", limit=contract.MAX_RECEIPT_BYTES), "substitution retained native original")
    _same(packet.read("inputs/dependency-report.json", limit=contract.MAX_RECEIPT_BYTES),
          native.dependency_body, "substitution retained dependency original")
    paths = [str(PurePosixPath(native.tools["executing_python"]["path"]).parent), "/usr/bin", "/bin"]
    environment = {"PATH": ":".join(dict.fromkeys(paths)), "HOME": str(work / "home"), "TMPDIR": str(work / "tmp"),
        "LANG": "C", "LC_ALL": "C", "TZ": "UTC", "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1",
        "CCACHE_DISABLE": "1", "OBJCACHE": "", "MAKEFLAGS": "-j2", "CMAKE_BUILD_PARALLEL_LEVEL": "2", "THREADS": "1"}
    _same(report["environment"], environment, "substitution environment")
    tools = native.dependency_document["tools"]
    config = receipts.decode(packet.verified(report["tool_config"], "tool-config.json"))
    _same(config, {"schema_version": 1, "contract_id": recorder.CONTRACT_ID,
        "contract_sha256": contract.contract_hash(), "roots": {"sources": str(source / "third_party"),
            "build": str(work), "receipts": str(output / "records"), "payloads": str(output / "payloads")},
        "tools": {name: tools[name] for name in recorder.TOOLS}}, "substitution tool configuration")
    checked = _substitution_records(packet, native, config, source, work)
    _same(report["dependency_control"], checked, "substitution reconstructed tool evidence")
    _same(report["source_derivation"], checked["source_derivation"], "substitution reported source derivation")
    frozen = [packet.row(name) for name in sorted(packet.cache) if name != "report.json"]
    for key in ("control_products_before", "control_products_after"):
        _same(report[key], frozen, "substitution " + key)
    binding = {"contract_id": substitution.CONTRACT_ID, "expected_revision": native.revision,
        "dependency_receipt_sha256": native.dependency_receipt_sha256,
        "managed_build_binding_sha256": variant["build_binding_sha256"],
        "inputs_sha256": contract.digest(initial), "source_derivation_sha256": contract.digest(checked["source_derivation"]),
        "alternate_product": checked["alternate_product"], "original_product": checked["original_product"],
        "format": substitution.FORMAT, "policy": substitution.POLICY, "managed_population_included": False,
        **dict.fromkeys(contract.FALSE_CLAIMS, False)}
    _same(report["control_binding"], binding, "substitution reconstructed binding")
    binding_id = contract.digest(binding)
    _same(report["control_binding_sha256"], binding_id, "substitution binding digest")
    require(binding_id not in {row["execution_binding_sha256"] for row in native.report["processes"]},
            "substitution process reuses a managed population binding")
    commands = report["commands"]
    require(type(commands) is list and len(commands) == 3, "substitution command population differs")
    for index, (role, arguments) in enumerate(substitution.recipes(source, work).items()):
        argv = [tools["python3"]["path"], str(source / "ci/project/p06_dependency_record.py"),
            "--config", str(output / "tool-config.json"), "--config-sha256", report["tool_config"]["sha256"],
            "--tool", "g++", "--role", role, "--", *arguments]
        _command(packet, commands[index], role + "-alternate-extension", argv, work, 1800, environment=environment)
    identity = substitution.manifest.process_identity(substitution.FORMAT, substitution.POLICY, binding_id)
    app = build / native_replay.APP
    argv = [app / "ai_counter_preflight", substitution.lifetime.APP_FLAG, "--policy", substitution.POLICY,
        "--module", app / "kernel.vxbin", "--qualification-id", binding_id, "--sample-id", identity["sample_id"],
        "--pair-index", "0", "--phase", "warmup"]
    text = _command(packet, commands[2], "run-alternate-extension", argv, work, 180,
        environment=dict(environment, VORTEX_DRIVER="simx", PERF="1", LD_LIBRARY_PATH=str(work) + ":" + str(build / "sw/runtime")),
        native=True)
    case = next(row for row in native.cases if row["format"] == substitution.FORMAT)
    observation = substitution.verify_observation(text, contract=native.contract, case=case, binding_id=binding_id,
        original_libraries=variant["expected_loaded_libraries"], alternate_path=str(work / substitution.LIBRARY))
    for name, value in observation.items():
        _same(report[name], value, "substitution recomputed " + name)
    native_replay.validate_process_duration(observation["observation"]["warm"], commands[2]["duration_seconds"],
                                          native_replay.warm_contract.load_contract(ROOT))
    # The native process creates this after the frozen compilation products.
    # Account it only in the final inventory, never either frozen snapshot.
    diagnostic = _runtime_diagnostic(packet, native, "work/" + RUNTIME_DIAGNOSTIC_NAME)
    _same(report["retained_files"], [packet.row(name) for name in sorted(packet.cache) if name != "report.json"],
          "substitution complete retained inventory")
    return {"outcome": "pass", "report_sha256": expected_report_sha256, "managed_population_included": False,
        "control_counts": observation["control_counts"], "rejection": observation["rejection"],
        "control_binding_sha256": binding_id, "tool_records_checked": 2, "commands_checked": 3,
        "source_derivation": checked["source_derivation"], "map_verification": checked["map_verification"],
        "runtime_diagnostic": diagnostic,
        "native_execution": "not_run", "retained_code_executed": False,
        **dict.fromkeys(contract.FALSE_CLAIMS, False), **packet.finish()}


def replay_archive(path, sha256, *, expected_revision, expected_receipt_sha256,
                   expected_native_report_sha256, expected_source_manifest_sha256,
                   expected_probe_report_sha256, expected_substitution_report_sha256, prefix=""):
    """Verify both controls, the complete native original and dependency receipt."""
    for value, label in ((sha256, "original ZIP"), (expected_receipt_sha256, "dependency receipt"),
            (expected_native_report_sha256, "native report"), (expected_source_manifest_sha256, "native source manifest"),
            (expected_probe_report_sha256, "pending probe report"),
            (expected_substitution_report_sha256, "substitution report")):
        native_replay._pin(value, label)
    require(type(expected_revision) is str and receipts.REVISION.fullmatch(expected_revision),
            "exact external source revision is required")
    require(type(prefix) is str, "hosted prefix must be literal text")
    require(_reader_sources() == TRUSTED_READER_SOURCES, "trusted control replay source changed after import")
    api = native_replay.dependency_replay._archive_api()
    if prefix:
        api.relative_name(prefix)
    try:
        with api.ArchiveReader(path, sha256) as archive:
            outer = archive.view(prefix)
            dependency_view = outer.subview("dependency-build")
            probe_view, substitution_view = outer.subview("pending-probe"), outer.subview("dependency-substitution")
            # Reject externally wrong control originals before expensive graph replay.
            for view, pin in ((probe_view, expected_probe_report_sha256), (substitution_view, expected_substitution_report_sha256)):
                _same(_digest(view.read("report.json", limit=contract.MAX_RECEIPT_BYTES)), pin,
                      "externally pinned control report")
            native_result, native = native_replay.verify_view(outer.subview("native-lifetime"), dependency_view, api,
                expected_revision=expected_revision, expected_receipt_sha256=expected_receipt_sha256,
                expected_native_report_sha256=expected_native_report_sha256,
                expected_source_manifest_sha256=expected_source_manifest_sha256)
            hosted = native_replay._hosted_identity(native, outer, dependency_view)
            pending = verify_probe_view(probe_view, native=native, expected_report_sha256=expected_probe_report_sha256,
                                        expected_native_report_sha256=expected_native_report_sha256)
            alternate = verify_substitution_view(substitution_view, native=native,
                expected_report_sha256=expected_substitution_report_sha256,
                expected_native_report_sha256=expected_native_report_sha256)
            require(_timestamp(probe_view.json("report.json")["finished_at"])
                    <= _timestamp(substitution_view.json("report.json")["started_at"]),
                    "substitution precedes completed pending-probe control")
            _same(outer.json("pending-probe.log"), {"outcome": "pass", "reason": None, "native_execution": "run",
                "native_probe_passed": True, "zero_mutation_rejected": True}, "hosted pending terminal output")
            _same(outer.json("dependency-substitution.log"), {"outcome": "pass", "reason": None,
                "native_execution": "run", "control_passed": True, "alternate_dependency_built": True,
                "numerical_control_passed": True, "original_provenance_rejected": True,
                "control_counts": alternate["control_counts"]}, "hosted substitution terminal output")
            terminals = ("pending-probe.log", "dependency-substitution.log")
            hosted.update(separate_control_packets_semantically_verified=True,
                control_terminal_files=[outer.identity(name) for name in terminals],
                other_outer_members=[name for name in hosted["other_outer_members"]
                    if name not in terminals and not name.startswith(("pending-probe/", "dependency-substitution/"))])
            result = {"schema_version": 1, "contract_id": CONTRACT_ID,
                "scope": "dependency-native-and-separate-controls-retained-consistency", "outcome": "pass",
                "retained_consistency": True, "native_execution": "not_run", "retained_code_executed": False,
                **dict.fromkeys(contract.FALSE_CLAIMS, False), "source_revision": expected_revision,
                "managed_counts": native_result["counts"], "pending_probe": pending, "dependency_substitution": alternate,
                "native_review": native_result, "hosted_identity": hosted, "prefix": prefix,
                "archive_read": archive.receipt(), "trusted_reader_sources": TRUSTED_READER_SOURCES,
                "trusted_archive_reader": {"path": native_replay.archive_helpers.ARCHIVE_READER_PATH,
                                           "sha256": native_replay.archive_helpers.ARCHIVE_READER_SHA256},
                "limitations": list(LIMITATIONS)}
        require(_reader_sources() == TRUSTED_READER_SOURCES, "trusted control replay source changed during review")
        return result
    except (KeyError, TypeError, IndexError, UnicodeError, OverflowError, RecursionError, StopIteration) as error:
        raise ValueError("malformed dependency control original: " + str(error)) from error


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    for name in ("sha256", "expected-revision", "dependency-receipt-sha256", "native-report-sha256",
                 "source-manifest-sha256", "probe-report-sha256", "substitution-report-sha256"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--prefix", default="")
    parser.add_argument("--output", type=Path)
    return parser


def main(argv=None):
    args = argument_parser().parse_args(argv)
    try:
        result = replay_archive(args.archive, args.sha256, expected_revision=args.expected_revision,
            expected_receipt_sha256=args.dependency_receipt_sha256,
            expected_native_report_sha256=args.native_report_sha256,
            expected_source_manifest_sha256=args.source_manifest_sha256,
            expected_probe_report_sha256=args.probe_report_sha256,
            expected_substitution_report_sha256=args.substitution_report_sha256, prefix=args.prefix)
        body = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
        if args.output is None:
            print(body, end="")
        else:
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(body)
            print(json.dumps({"outcome": "pass", "report": str(args.output), "native_execution": "not_run",
                "retained_consistency": True, "retained_code_executed": False,
                **dict.fromkeys(contract.FALSE_CLAIMS, False)}, sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({"outcome": "fail", "reason": str(error), "retained_consistency": False,
            "native_execution": "not_run", "retained_code_executed": False,
            **dict.fromkeys(contract.FALSE_CLAIMS, False)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    sys.exit(main())
