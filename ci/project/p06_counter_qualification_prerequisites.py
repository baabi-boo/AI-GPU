# SPDX-License-Identifier: Apache-2.0
"""Join pinned diagnostic originals to the reviewed counter source proof."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import p06_counter_diagnostics_replay as model_reader
import p06_counter_public_replay as public_reader
import p06_counter_qualification_contract as contract
import p06_dependency_contract as dependencies
import p06_dependency_local_replay as control_reader


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_ID = "p06-counter-qualification-prerequisites-v1"
MODEL_MODES = (
    "ordinary-boundaries", "checked-boundaries", "checked-core-overflow",
    "checked-cache-aggregate-overflow", "checked-pending-underflow",
    "checked-cache-backing-overflow", "checked-tcu-backing-overflow",
)
PUBLIC_MODES = (
    "normal", "immediate-overflow", "delayed-overflow", "cache-overflow", "coherent-terminal",
)
GETTER_PATHS = (
    "sim/simx/processor.cpp", "sim/simx/processor.h", "sim/simx/processor_impl.h",
)
require, same = model_reader.require, model_reader._same


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def reader_sources():
    rows = {row["path"]: row for row in public_reader._reader_sources()}
    rows.update({row["path"]: row for row in control_reader._reader_sources()})
    for module in (contract, dependencies, sys.modules[__name__]):
        path = ROOT / "ci/project" / (module.__name__ + ".py")
        require(Path(module.__file__).resolve(strict=True) == path,
                "qualification prerequisite helper is outside the trusted checkout")
        body = path.read_bytes()
        relative = path.relative_to(ROOT).as_posix()
        rows[relative] = {"path": relative, "sha256": hashlib.sha256(body).hexdigest(),
                          "size_bytes": len(body)}
    archive_name = model_reader.trusted.ARCHIVE_READER_PATH
    archive_body = (ROOT / archive_name).read_bytes()
    archive_digest = hashlib.sha256(archive_body).hexdigest()
    same(archive_digest, model_reader.trusted.ARCHIVE_READER_SHA256,
         "qualification prerequisite trusted archive helper")
    rows[archive_name] = {"path": archive_name, "sha256": archive_digest,
                          "size_bytes": len(archive_body)}
    return [rows[name] for name in sorted(rows)]


def _sources(result, prefix, expected_count):
    rows = result["archive_read"]["read_files"]
    require(type(rows) is list, "diagnostic reader did not retain its checked source inventory")
    start = prefix + "/artifacts/source/"
    selected = {}
    for row in rows:
        model_reader._fields(row, ("path", "sha256", "size_bytes"), "checked source descriptor")
        if row["path"].startswith(start):
            name = row["path"][len(start):]
            require(name not in selected, "diagnostic source appears more than once")
            selected[name] = dict(row, path=name)
    same(len(selected), expected_count, "diagnostic checked source count")
    return selected


def _original(result, expected, contract_id, producer_id, *, cells, commands, sources):
    for key, value in (("schema_version", 1), ("contract_id", contract_id),
            ("producer_contract_id", producer_id), ("outcome", "pass"),
            ("scope", "retained-data-consistency-only"), ("retained_data_consistent", True),
            ("source_revision", expected["source_revision"]), ("cells_checked", cells),
            ("commands_checked", commands), ("retained_source_files", sources),
            *model_reader.nonacceptance_result().items()):
        same(result[key], value, "diagnostic result." + key)
    identity = result["archive_read"]["archive"]
    same(identity["sha256"], expected["archive"]["sha256"], "diagnostic original digest")
    same(identity["size_bytes"], expected["archive"]["size_bytes"], "diagnostic original size")
    same(result["archive_read"]["data_files"], expected["archive"]["members"],
         "diagnostic original member count")


def _projection(proof, model, public):
    historical = _sources(public, "public-counters", 683)
    model_sources = _sources(model, "checked-counters", 270)
    for name in set(historical) & set(model_sources):
        same(model_sources[name], historical[name], "model/public common source " + name)
    projected = [historical[name] for name in sorted(historical)
                 if name.startswith(("sim/", "sw/"))]
    same(projected, proof["diagnostic_projection"], "complete diagnostic production projection")
    for row in proof["diagnostic_sources"]:
        same(historical.get(row["path"]), row, "seeded diagnostic source " + row["path"])
        same(model_sources.get(row["path"]), row, "seeded model source " + row["path"])
    changes = {row["path"]: row for row in proof["source_projection_changes"]}
    same(sorted(changes), list(GETTER_PATHS), "reviewed getter change inventory")
    require(len(changes) == len(proof["source_projection_changes"]), "repeated source projection change")
    measured = {row["path"]: row for row in proof["measurement_sources"]}
    for name, change in changes.items():
        same(historical[name]["sha256"], change["previous_sha256"], "reviewed previous getter " + name)
        same(measured[name], {key: change[key] for key in ("path", "sha256", "size_bytes")},
             "reviewed current getter " + name)
        require(change["sha256"] != change["previous_sha256"], "getter projection did not identify a change")
    for name in (set(measured) & set(historical)) - set(changes):
        same(measured[name], historical[name], "unchanged diagnostic/measurement source " + name)
    return {"historical_source_files": len(projected),
            "diagnostic_sources": len(proof["diagnostic_sources"]),
            "reviewed_changed_paths": list(GETTER_PATHS),
            "diagnostic_projection_sha256": _digest(projected),
            "measurement_projection_sha256": _digest(proof["measurement_sources"])}


def _coverage(proof, model, public):
    names = [row["name"] for row in proof["selectors"]]
    cells = [cell for variant in model["variants"] for cell in variant["cells"]]
    same([cell["id"] for cell in cells], list(MODEL_MODES), "complete model control inventory")
    for cell in cells[:2]:
        observed = cell["observations"]
        for key, value in (("transport_selectors", names), ("source_components", 40),
                ("unavailable_selectors", 12), ("checks", 6389), ("transport_reads", 1788),
                ("failures", 0), ("xlen", 64), ("perf", True), ("tcu", True)):
            same(observed[key], value, "model boundary." + key)
    same(public["model"]["control"], cells[1], "public checked boundary control")
    same([cell["id"] for cell in public["public"]["cells"]],
         ["public-" + name for name in PUBLIC_MODES], "complete public control inventory")
    public_cells = [cell["observations"] for cell in public["public"]["cells"]]
    for mode, observed in zip(PUBLIC_MODES, public_cells):
        fault = mode.endswith("overflow")
        for key, value in (("mode", mode), ("constructed", 2), ("destroyed", 2),
                ("fresh_context_success", True), ("terminal_failure", fault),
                ("suppressed_requests", 5 if fault else 0), ("failures", 0),
                ("unexpected_errors", 0), ("violations", 0),
                ("run_errors", 1 if mode in ("immediate-overflow", "delayed-overflow") else 0),
                ("dcr_read_errors", 1 if mode == "cache-overflow" else 0)):
            same(observed[key], value, "public control." + key)
    snapshots = [snapshot for cell in public_cells for snapshot in cell["terminal_snapshots"]]
    same(len(snapshots), 7, "public terminal vector count")
    for snapshot in snapshots:
        same(snapshot["selectors"], 33, "public terminal selector count")
        same(snapshot["components"], 40, "public terminal component count")
        same(len(snapshot["rows"]), 33, "public terminal row count")
    return {"model_cells": len(cells), "public_cells": 6, "public_processes": len(public_cells),
            "transport_selectors": len(names), "source_components": 40, "unavailable_selectors": 12,
            "boundary_checks_per_variant": 6389, "boundary_half_reads_per_variant": 1788,
            "model_control_ids": [cell["id"] for cell in cells],
            "public_control_modes": list(PUBLIC_MODES),
            "public_constructions": sum(cell["constructed"] for cell in public_cells),
            "public_destructions": sum(cell["destroyed"] for cell in public_cells),
            "public_terminal_vectors": len(snapshots),
            "public_terminal_queries": sum(len(snapshot["rows"]) for snapshot in snapshots)}


def verify_prerequisites(proof, *, diagnostic_archive, diagnostic_sha256):
    """Recheck both original diagnostic packets before deriving their projection."""
    proof = contract.validate_proof(proof)
    expected = proof["diagnostics"]
    same(diagnostic_sha256, expected["archive"]["sha256"], "externally selected diagnostic digest")
    before = reader_sources()
    inventory = expected["public_source_inventory"]
    inventory_path = ROOT / inventory["path"]
    try:
        model = model_reader.replay_archive(diagnostic_archive, diagnostic_sha256,
            expected_revision=expected["source_revision"])
        public = public_reader.replay_archive(diagnostic_archive, diagnostic_sha256,
            expected_revision=expected["source_revision"], source_inventory=inventory_path,
            source_inventory_sha256=inventory["sha256"])
        _original(model, expected, model_reader.REPLAY_CONTRACT_ID, model_reader.CONTRACT_ID,
                  cells=7, commands=17, sources=270)
        _original(public, expected, public_reader.REPLAY_CONTRACT_ID, public_reader.CONTRACT_ID,
                  cells=6, commands=14, sources=683)
        for key, value in (("source", "external-manifest"), ("manifest_sha256", inventory["sha256"]),
                           ("source_files", 683)):
            same(public["source_inventory_expectation"][key], value, "explicit public source inventory." + key)
        projection = _projection(proof, model, public)
        coverage = _coverage(proof, model, public)
        same(reader_sources(), before, "qualification prerequisite reader stability")
        return {"schema_version": 1, "contract_id": CONTRACT_ID,
                "scope": "pinned-diagnostic-prerequisites-only", "outcome": "pass",
                "diagnostic_prerequisites_consistent": True,
                "archive": dict(expected["archive"]), "source_revision": expected["source_revision"],
                "public_source_inventory_sha256": inventory["sha256"],
                "model_source_inventory_sha256": model["source_inventory_sha256"],
                "public_source_names_sha256": public["source_inventory_sha256"],
                "projection": projection, "coverage": coverage,
                **model_reader.nonacceptance_result()}
    except (KeyError, TypeError, IndexError, UnicodeError, OverflowError, RecursionError) as error:
        raise ValueError("malformed qualification prerequisite: " + str(error)) from error


def verify_dependency_projection(proof, verified_dependency_document):
    """Join source proof to an already fully verified fresh dependency receipt."""
    proof = contract.validate_proof(proof)
    try:
        same(verified_dependency_document["contract_id"], dependencies.CONTRACT_ID,
             "dependency projection contract")
        sources = verified_dependency_document["source_manifest"]["sources"]
        require(type(sources) is list, "dependency sources must be a list")
        selected = [row for row in sources if row["name"] == "ramulator"]
        same(len(selected), 1, "selected Ramulator source inventory")
        selected = selected[0]
        same(selected["revision"], proof["dependency_revision"], "qualified Ramulator revision")
        same(selected["tree"], dependencies.PINS["ramulator"]["tree"], "qualified Ramulator tree")
        require(type(selected["files"]) is list and len(selected["files"]) <= 20000,
                "dependency projection source inventory is not bounded")
        files = {row["path"]: row for row in selected["files"]}
        same(len(files), len(selected["files"]), "unique dependency projection source paths")
        for row in proof["dependency_sources"]:
            observed = files[row["path"]]
            same({key: observed[key] for key in ("path", "sha256", "size_bytes")},
                 {key: row[key] for key in ("path", "sha256", "size_bytes")},
                 "qualified dependency source " + row["path"])
            same(observed["oid"], row["git_blob"], "qualified dependency Git blob " + row["path"])
        return {"source_files": len(proof["dependency_sources"]),
                "revision": selected["revision"], "tree": selected["tree"],
                "projection_sha256": _digest(proof["dependency_sources"])}
    except (KeyError, TypeError, IndexError, UnicodeError, OverflowError, RecursionError) as error:
        raise ValueError("malformed qualified dependency projection: " + str(error)) from error


def verify_control_prerequisite(proof, *, archive, sha256):
    """Recheck the complete earlier original and project its separate controls."""
    proof = contract.validate_proof(proof)
    expected = proof["controls"]
    same(sha256, expected["archive"]["sha256"], "externally selected control original digest")
    before = reader_sources()
    try:
        result = control_reader.replay_archive(archive, sha256,
            expected_revision=expected["source_revision"],
            expected_receipt_sha256=expected["receipt_sha256"],
            expected_native_report_sha256=expected["native_report_sha256"],
            expected_source_manifest_sha256=expected["source_manifest_sha256"],
            expected_probe_report_sha256=expected["probe_report_sha256"],
            expected_substitution_report_sha256=expected["substitution_report_sha256"],
            expected_local_execution_sha256=expected["local_execution_sha256"])
        for key, value in (("schema_version", 1), ("contract_id", control_reader.CONTRACT_ID),
                ("outcome", "pass"), ("retained_consistency", True),
                ("source_revision", expected["source_revision"]), ("native_execution", "not_run"),
                ("retained_code_executed", False), *dict.fromkeys(dependencies.FALSE_CLAIMS, False).items()):
            same(result[key], value, "control original." + key)
        for key in ("sha256", "size_bytes"):
            same(result["archive_read"]["archive"][key], expected["archive"][key], "control archive." + key)
        same(result["archive_read"]["data_files"], expected["archive"]["members"], "control member count")
        same(result["managed_counts"], control_reader.producer.COMPLETE_COUNTS, "historical managed population")
        historical = _sources(result, "native-lifetime", result["native_review"]["retained_source_files_checked"])
        for row in proof["measurement_sources"]:
            same(historical.get(row["path"]), row, "control/measurement source projection " + row["path"])
        probe_source = dict(proof["controls"]["probe_source"],
            path="pending-probe/inputs/" + proof["controls"]["probe_source"]["path"])
        matches = [row for row in result["archive_read"]["read_files"] if row["path"] == probe_source["path"]]
        same(matches, [probe_source], "actual accessor probe source")
        pending, alternate = result["pending_probe"], result["dependency_substitution"]
        for value, pin in ((pending, expected["probe_report_sha256"]),
                           (alternate, expected["substitution_report_sha256"])):
            for key, wanted in (("outcome", "pass"), ("report_sha256", pin),
                    ("managed_population_included", False), ("native_execution", "not_run"),
                    ("retained_code_executed", False), *dict.fromkeys(dependencies.FALSE_CLAIMS, False).items()):
                same(value[key], wanted, "separate control." + key)
        for key, value in (("processes", 2), ("contexts", 2), ("commands_checked", 5),
                ("always_zero_rejection", "FAILED pending_reads native_probe: pending getter did not observe an outstanding read")):
            same(pending[key], value, "pending-read prerequisite." + key)
        contexts = pending["positive_pending_contexts"]
        same(contexts, [{"gp": gp, "checked_gp": gp, "max_pending": 1,
            "pending_final": 0, "positive_samples": 23, "readonly_checks": 137,
            "checked_reset_delta": 1, "stepped_reset_delta": 1, "steps": 135} for gp in (7, -1)],
            "actual positive-pending accessor contexts")
        same(alternate["rejection"], "loaded library libramulator-vortex.so: differs from the fixed contract",
             "alternate-library exact provenance rejection")
        same(alternate["control_counts"], {"processes": 1, "launches": 33, "checked_words": 1056,
            "snapshots": 4, "available_queries": 132, "half_replies": 264, "cache_flush_reads": 33,
            "dcr_reads": 297, "unavailable_rows": 48}, "separate substitution population")
        same(reader_sources(), before, "control prerequisite reader stability")
        return {"schema_version": 1, "contract_id": CONTRACT_ID,
                "scope": "pinned-separate-control-prerequisites-only", "outcome": "pass",
                "control_prerequisites_consistent": True, "archive": dict(expected["archive"]),
                "source_revision": expected["source_revision"],
                "receipt_sha256": expected["receipt_sha256"],
                "native_report_sha256": expected["native_report_sha256"],
                "source_manifest_sha256": expected["source_manifest_sha256"],
                "probe_report_sha256": expected["probe_report_sha256"],
                "substitution_report_sha256": expected["substitution_report_sha256"],
                "local_execution_sha256": expected["local_execution_sha256"],
                "projected_measurement_sources": len(proof["measurement_sources"]),
                "measurement_projection_sha256": _digest(proof["measurement_sources"]),
                "probe_source": dict(expected["probe_source"]),
                "positive_pending_contexts": [dict(row) for row in contexts],
                "always_zero_rejection": pending["always_zero_rejection"],
                "alternate_library_rejection": alternate["rejection"],
                "managed_population_included": False, **model_reader.nonacceptance_result()}
    except (KeyError, TypeError, IndexError, UnicodeError, OverflowError, RecursionError) as error:
        raise ValueError("malformed counter control prerequisite: " + str(error)) from error
