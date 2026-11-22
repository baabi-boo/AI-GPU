#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Recheck public native counter diagnostics as inert retained data.

An externally supplied original ZIP digest and source revision are mandatory.
Later source inventories require an explicit external manifest and its digest.
Archive members and producer paths are data: no member is extracted, imported
or executed, and no recorded producer file is opened. Successful consistency
checking never establishes a new native execution, authentication or acceptance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True

import p06_checked_execute as checked
import p06_counter_diagnostics_replay as diagnostics
import p06_counter_public_build as public_build
import p06_counter_public_records as public_records


CONTRACT_ID = "simx-counter-public-native-v1"
REPLAY_CONTRACT_ID = "simx-counter-public-replay-v1"
PUBLIC_MAKEFILE = "tests/unittest/checked_counters/public.mk"
PUBLIC_DIR = "sim/simx/checked-public"
PUBLIC_BINARY = PUBLIC_DIR + "/checked_public_test"
COPIED = (*checked.COPIED, PUBLIC_MAKEFILE)
MODES = ("normal", "immediate-overflow", "delayed-overflow", "cache-overflow", "coherent-terminal")
REPORT_FIELDS = {
    "schema_version", "contract_id", "started_at", "finished_at", "state", "outcome",
    "qualified", "ready_for_warm", "acceptance_claimed", "phase_acceptance",
    "performance_acceptance", "full_warm_coverage", "warm_execution",
    "native_public_diagnostics_passed", "all_available_selector_transport", "expected_revision",
    "paths", "commands", "cells", "model_control", "model", "public", "bindings",
    "stability_checks", "errors", "limitations", "budget", "environment",
    "available_memory_bytes", "free_disk_bytes", "source_before", "source_after", "source_stable",
    "tools_before", "tools_after", "tools_stable", "interpreter", "retained_sources",
    "build_dir", "configure_command", "retained_configuration",
}
MODEL_FIELDS = {"build_command", "retained_compiler_stamp", "retained_diagnostic_source",
                "compiler_records", "retained_probe", "effective_configuration"}
PUBLIC_FIELDS = {"build_command", "retained_compiler_stamps", "compiler_records"}
CONTROL_FIELDS = {"id", "outcome", "run_command", "run_outcome", "exit_code",
                  "run_process_started", "observations"}
CELL_FIELDS = CONTROL_FIELDS | {"mode"}
BINDINGS = ("configuration", "model-stamp", "generated-diagnostic-source", "model-objects",
            "model-binary", "header-probe", "public-stamps", "public-objects", "public-artifacts")
COMMANDS = ("version-make", "version-gpp", "version-python3", "version-executing_python",
            "checked-configure", "checked-build", "checked-header", "checked-boundaries",
            "public-build", *("public-" + mode for mode in MODES))
SOURCE_REQUIRED = tuple(dict.fromkeys((
    *checked.CRITICAL, *checked.MODEL_SOURCES, *checked.WRAPPER_SOURCES.values(),
    *public_build.RUNTIME_SOURCES, *public_build.BACKEND_SOURCES, *public_build.HEADERS,
    public_build.HOOKS, public_build.MAIN, ".github/workflows/p06-checked-counters.yml",
    "ci/project/p06_counter_public_execute.py", "ci/project/p06_counter_public_build.py",
    "ci/project/p06_counter_public_records.py",
)))
# The native-v1 producer retains 676 complete source bodies. This is SHA-256 of
# their sorted source-relative names, each followed by LF, independently derived
# from its source tree. It covers runtime/model headers and the original helper
# closure without depending on a later checkout's dynamically discovered files.
PUBLIC_V1_SOURCE_INVENTORY_SHA256 = "f38b606f70604edc6ff27400126e94d3fdcc5983950658dcf35588fb655d09da"
PRODUCER_LIMITATIONS = [
    "Success covers only these directed real-model public-runtime diagnostics, not warm readiness or phase acceptance.",
    "The scalar control and seeded counter reads do not execute GEMM, workspace reuse, the full warm caller or a performance experiment.",
    "Test-only linker wrappers observe the actual Processor; the diagnostic libraries are not seed-free measurement binaries.",
    "Coherence and terminal observations apply only to an exclusive serial submitter with the exact VM-off, direct-RAM CP route.",
    "Native observations do not replace independent source/dependency review of the complete counter-lifetime theorem.",
    "SimX evidence is software simulation, not processor RTL, vendor full-AFU emulation or physical hardware evidence.",
    "Tools and dependency identities do not inventory every host header, compiler support file or loaded system library.",
    "Binary and object bytes remain in the work tree; retained identities do not independently authenticate arbitrary producer claims.",
    "Before/after hashes do not defend against malicious concurrent filesystem writers.",
    *diagnostics.PROCESS_LIMITATIONS,
]
LIMITATIONS = [
    "This is retained-data consistency checking, not a new native execution or producer authentication.",
    "The externally supplied ZIP digest and source revision do not independently authenticate GitHub origin.",
    "Consistent synthetic or forged records remain synthetic or forged; replay cannot establish actual execution.",
    "Retained source bodies and reported clean revision/tree/submodule identities are internally bound, not a Git tree proof.",
    "Without an external source manifest, the complete original 676-name source inventory remains pinned.",
    "An external manifest's caller-supplied digest defines expected source descriptors; it does not independently prove Git provenance or execution.",
    "Object, executable, library, tool and dependency payloads are absent; their recorded identities are not independently rehashed.",
    "Recorded producer paths are interpreted syntactically and are never opened, resolved or executed on this host.",
    "The original 45-TU model and 19-TU public logs are reparsed; compiler processes and retained commands are never rerun.",
    "Five directed public scenarios and one boundary control do not prove complete lifetime bounds, a warm GEMM experiment or workspace performance.",
    "The retained test-only wrappers and seeded diagnostic binaries are not seed-free measurement binaries.",
    "No terminal source proof, hardware result, readiness, qualification or phase/performance acceptance is established.",
    "Before/after identities do not defend against malicious concurrent producer filesystem writers.",
    *diagnostics.PROCESS_LIMITATIONS,
]
require = diagnostics.require
_same = diagnostics._same
_fields = diagnostics._fields


def _reader_sources():
    """Identify only the current trusted reader closure, never archived code."""
    rows = diagnostics._reader_sources()
    modules = {"p06_counter_public_build": public_build, "p06_counter_public_records": public_records,
               "p06_counter_public_replay": sys.modules[__name__]}
    for name, module in sorted(modules.items()):
        path = Path(module.__file__).resolve()
        filename = name + ".py"
        require(path == diagnostics.trusted.ROOT / "ci/project" / filename,
                "public reader helper is outside the trusted repository")
        body = path.read_bytes()
        rows.append({"path": "ci/project/" + filename, "sha256": hashlib.sha256(body).hexdigest(),
                     "size_bytes": len(body)})
    return sorted(rows, key=lambda row: row["path"])


def _binding(packet, name, paths, *, expected=None):
    """Check before/after file identities without consulting their paths."""
    group = packet.report["bindings"][name]
    _fields(group, ("before", "after"), "execution binding " + name)
    before = group["before"]
    require(type(before) is list and len(before) == len(paths), "execution binding inventory differs: " + name)
    for row, path in zip(before, paths):
        packet.identity(row, expected_path=path, resolved_equal=True)
    _same(group["after"], before, "execution binding before/after " + name)
    if expected is not None:
        _same(before, expected, "execution binding validated identities " + name)
    return before


def _retained_binding(packet, name, rows, build, relatives):
    """Bind original retained bytes to their exact execution-input identities."""
    prefix = "artifacts/" + build.name + "/"
    bodies = packet.retained(rows, expected=[prefix + name for name in relatives])
    identities = _binding(packet, name, [build / name for name in relatives])
    expected = [{"path": prefix + relative, "sha256": row["sha256"], "size_bytes": row["size_bytes"]}
                for relative, row in zip(relatives, identities)]
    _same(rows, expected, "retained execution binding " + name)
    return {relative: bodies[prefix + relative] for relative in relatives}


def _configure(packet, build):
    _same(packet.report["configure_command"], "checked-configure", "configure command binding")
    require(packet.command_index < len(packet.commands), "configure command is missing")
    actual = packet.commands[packet.command_index]
    require(type(actual) is dict and type(actual.get("argv")) is list, "invalid configure command")
    argv = [packet.paths["source"] / "configure", "--xlen=64", "--profile=p02-tfr",
            "--tooldir=" + str(packet.paths["tools"])]
    if len(actual["argv"]) == 5:
        argv.append("--osversion=" + packet.osversions[str(build)])
    packet.command("checked-configure", argv, build, diagnostics.TIMEOUTS["configure"])


def _cell(packet, cell, *, mode, binary, cwd, public):
    _fields(cell, CELL_FIELDS if public else CONTROL_FIELDS, "public diagnostic cell")
    name = "public-" + mode if public else "checked-boundaries"
    for key, expected in (("id", name), ("outcome", "pass"), ("run_command", name),
                           ("run_outcome", "pass"), ("exit_code", 0), ("run_process_started", True)):
        _same(cell[key], expected, "diagnostic cell " + key)
    if public:
        _same(cell["mode"], mode, "public diagnostic mode")
    environment = dict(packet.environment, VORTEX_DRIVER="simx") if public else packet.environment
    _, text = packet.command(name, [packet.tools["executing_python"]["path"], "-I", "-c",
        checked.NO_CORE_WRAPPER, binary, mode], cwd, diagnostics.TIMEOUTS["run"], environment=environment)
    observed = public_records.verify_output(text, mode) if public else checked.verify_output(text, True)
    _same(cell["observations"], observed, "recomputed diagnostic observations " + name)
    return {"id": name, "observations": observed}


def _public_build(packet, build, words, model_records, text):
    public = packet.report["public"]
    bodies = _retained_binding(packet, "public-stamps", public["retained_compiler_stamps"], build,
                               public_build.STAMPS)
    stamps = {kind: bodies[name].decode("utf-8") for kind, name in zip(public_build.KINDS, public_build.STAMPS)}
    # model_records is recomputed from the original model log and retained
    # original/generated source bytes before this public parser is called.
    recomputed = public_build.parse_build_records(text, words, stamps, source=packet.paths["source"],
        build=build, compiler=packet.tools["g++"]["path"], source_files=set(packet.sources),
        model_records=model_records)
    paths = recomputed.pop("object_paths")
    archived = public["compiler_records"]
    require(type(archived) is dict, "public compiler summary is not an object")
    identities = archived.get("object_identities")
    require(type(identities) is list and len(identities) == len(paths), "public object identity inventory differs")
    for row, path in zip(identities, paths):
        packet.identity(row, expected_path=path, resolved_equal=True)
    recomputed["object_identities"] = identities
    _same(archived, recomputed, "recomputed public compiler/link/source/object summary")
    _binding(packet, "public-objects", paths, expected=identities)
    return recomputed


def _execution(packet):
    report = packet.report
    _fields(report["model"], MODEL_FIELDS, "model build records")
    _fields(report["public"], PUBLIC_FIELDS, "public build records")
    _fields(report["bindings"], BINDINGS, "execution bindings")
    model, public = report["model"], report["public"]
    build = packet.paths["work"] / "checked"
    unit, binary = build / "sim/simx", build / "sim/simx/checked_counters_test"
    _same(report["build_dir"], str(build), "public build root")
    packet.configuration(report["retained_configuration"], build=build, copied=COPIED)
    _retained_binding(packet, "configuration", report["retained_configuration"], build,
                      (*checked.GENERATED, *COPIED))
    _configure(packet, build)
    make = [packet.tools["make"]["path"], "--no-print-directory", "-j2", "THREADS=1",
            "PROFILE=p02-tfr", "CONFIGS=-D" + checked.GUARD + "=1", "PERF=1",
            "CXX=" + packet.tools["g++"]["path"]]
    _same(model["build_command"], "checked-build", "model build command binding")
    _, model_text = packet.command("checked-build", [*make, "-f", "checked_counters.mk", binary], unit,
                                   diagnostics.TIMEOUTS["build"])
    words, model_records = packet.model_build(build=build, binary=binary,
        stamp_rows=model["retained_compiler_stamp"], generated_rows=model["retained_diagnostic_source"],
        compiler_records=model["compiler_records"], build_text=model_text, is_checked=True)
    _retained_binding(packet, "model-stamp", model["retained_compiler_stamp"], build, [checked.STAMP])
    _retained_binding(packet, "generated-diagnostic-source", model["retained_diagnostic_source"], build,
                      [checked.GENERATED_TCU])
    _binding(packet, "model-objects", [row["path"] for row in model_records["object_identities"]],
             expected=model_records["object_identities"])
    binary_identity = _binding(packet, "model-binary", [binary])[0]
    probe = _retained_binding(packet, "header-probe", model["retained_probe"], build,
                              [diagnostics.HEADER_PROBE])
    _same(probe[diagnostics.HEADER_PROBE], diagnostics.HEADER_PROBE_CONTENT, "header probe source")
    flags = [word for word in checked.dependency_flags(words, build / checked.STAMP) if word not in ("-MMD", "-MP")]
    _, header = packet.command("checked-header", [packet.tools["g++"]["path"], *flags,
        "-E", "-dM", "-x", "c++", build / diagnostics.HEADER_PROBE], unit, diagnostics.TIMEOUTS["configure"])
    _same(model["effective_configuration"], checked.verify_header(header, True), "recomputed effective configuration")
    control = _cell(packet, report["model_control"], mode="boundaries", binary=binary, cwd=unit, public=False)
    _same(public["build_command"], "public-build", "public build command binding")
    _, public_text = packet.command("public-build", [*make, "-f", "../../" + PUBLIC_MAKEFILE, "checked-public"],
                                    unit, diagnostics.TIMEOUTS["build"])
    public_summary = _public_build(packet, build, words, model_records, public_text)
    artifact_identities = _binding(packet, "public-artifacts", [build / name for name in public_build.ARTIFACTS])
    require(type(report["cells"]) is list and len(report["cells"]) == len(MODES), "public cell inventory differs")
    cells = [_cell(packet, cell, mode=mode, binary=build / PUBLIC_BINARY, cwd=build / PUBLIC_DIR, public=True)
             for mode, cell in zip(MODES, report["cells"])]
    return ({"translation_units": model_records["translation_units"], "link_count": model_records["link_count"],
             "recorded_binary_identity": binary_identity, "control": control},
            {"translation_units": public_summary["translation_units"], "link_count": public_summary["link_count"],
             "reused_model_objects": len(public_summary["reused_model_object_identities"]),
             "recorded_artifact_identities": artifact_identities, "cells": cells})


def _stability(packet):
    expected = []
    for index, command in enumerate(COMMANDS):
        active = BINDINGS if index >= 9 else BINDINGS[:6] if index >= 6 else BINDINGS[:1] if index == 5 else ()
        for edge in ("before-", "after-"):
            expected.append({"stage": edge + command, "bindings": list(active)})
    _same(packet.report["stability_checks"], expected, "exact per-command stability sequence")


def replay_archive(path, sha256, *, expected_revision, prefix="public-counters", expected_contract=CONTRACT_ID,
                   source_inventory=None, source_inventory_sha256=None):
    """Validate one complete native-v1 packet without execution or acceptance."""
    _same(expected_contract, CONTRACT_ID, "supported external public diagnostic contract")
    require(type(expected_revision) is str and diagnostics.trusted.REVISION.fullmatch(expected_revision),
            "an external 40-character source revision is required")
    diagnostics.source_inventory_pair(source_inventory, source_inventory_sha256)
    readers = _reader_sources()
    with diagnostics.open_archive(path, sha256, prefix=prefix) as (packet, archive):
        expected_inventory = diagnostics.load_expected_inventory(source_inventory, source_inventory_sha256,
            expected_revision=expected_revision, producer_contract_id=CONTRACT_ID)
        report = packet.report
        _fields(report, REPORT_FIELDS, "public native report")
        for key, expected in (("schema_version", 1), ("contract_id", CONTRACT_ID), ("state", "finished"),
            ("outcome", "pass"), ("qualified", False), ("ready_for_warm", False), ("acceptance_claimed", False),
            ("phase_acceptance", False), ("performance_acceptance", False), ("full_warm_coverage", False),
            ("warm_execution", False), ("native_public_diagnostics_passed", True),
            ("all_available_selector_transport", True), ("errors", [])):
            _same(report[key], expected, "producer " + key)
        require(diagnostics.trusted._timestamp(report["finished_at"]) >=
                diagnostics.trusted._timestamp(report["started_at"]), "producer timestamps are reversed")
        _same(report["limitations"], PRODUCER_LIMITATIONS, "producer limitations")
        _same(list(public_records.MODES), list(MODES), "trusted public scenario inventory")
        packet.setup()
        packet.source(expected_revision, required=SOURCE_REQUIRED, inventory_sha256=PUBLIC_V1_SOURCE_INVENTORY_SHA256,
                      expected_inventory=expected_inventory, producer_contract_id=CONTRACT_ID)
        packet.toolchain()
        _same(report["interpreter"], {"version": [3, 12, 14], "implementation": "CPython", "platform": "linux"},
              "executing interpreter observation")
        packet.version_commands()
        model, public = _execution(packet)
        _same(len(packet.commands), len(COMMANDS), "exact public command count")
        _stability(packet)
        packet.finish()
        _same(_reader_sources(), readers, "trusted public reader source stability")
        result = {"schema_version": 1, "contract_id": REPLAY_CONTRACT_ID, "producer_contract_id": CONTRACT_ID,
            "outcome": "pass", "scope": "retained-data-consistency-only", "retained_data_consistent": True,
            **diagnostics.nonacceptance_result(), "source_revision": expected_revision,
            "source_inventory_sha256": packet.source_inventory_sha256, "retained_source_files": len(packet.sources),
            "source_inventory_expectation": diagnostics.inventory_expectation(
                packet, source_inventory, source_inventory_sha256),
            "commands_checked": packet.command_index, "cells_checked": 6, "public_cells_checked": len(MODES),
            "bindings_checked": len(BINDINGS), "stability_checks_checked": 2 * len(COMMANDS),
            "transport_selectors": 33, "source_components": 40, "model": model, "public": public,
            "limitations": LIMITATIONS, "archive_read": archive.receipt(),
            "trusted_archive_reader": {"path": diagnostics.trusted.ARCHIVE_READER_PATH,
                                       "sha256": diagnostics.trusted.ARCHIVE_READER_SHA256},
            "trusted_replay_sources": readers}
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--source-inventory", type=Path,
                        help="external complete source manifest; requires --source-inventory-sha256")
    parser.add_argument("--source-inventory-sha256", help="independently supplied external manifest SHA-256")
    parser.add_argument("--prefix", default="public-counters")
    parser.add_argument("--expected-contract", default=CONTRACT_ID)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = replay_archive(args.archive, args.sha256, expected_revision=args.source_revision,
                                prefix=args.prefix, expected_contract=args.expected_contract,
                                source_inventory=args.source_inventory,
                                source_inventory_sha256=args.source_inventory_sha256)
        if args.output is None:
            print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
        else:
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
            print(json.dumps({"outcome": "pass", "scope": result["scope"], "report": str(args.output),
                              "cells_checked": result["cells_checked"], **diagnostics.nonacceptance_result()}))
        return 0
    except (OSError, ValueError) as error:
        print(json.dumps({"outcome": "fail", "reason": str(error), **diagnostics.nonacceptance_result()}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
