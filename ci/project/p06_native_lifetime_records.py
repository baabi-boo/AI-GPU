# SPDX-License-Identifier: Apache-2.0
"""Validate the additional lifetime transcript without executing retained data."""

from __future__ import annotations

import p06_managed_preflight_contract as preflight
import p06_managed_preflight_records as parent_records
import p06_native_lifetime_contract as manifest


require = preflight.require
fixed = preflight.fixed
fields = preflight.fields
uint = preflight.uint


def _split_output(text):
    require(type(text) is str, "native lifetime output must be text")
    try:
        encoded = text.encode("utf-8", "strict")
    except UnicodeError as error:
        raise preflight.ContractError("native lifetime output is not valid UTF-8") from error
    require(0 < len(encoded) <= manifest.MAX_OUTPUT_BYTES,
            "native lifetime output exceeds its byte bound")
    require("\r" not in text and "\x00" not in text,
            "native lifetime output contains noncanonical line data")
    require(text.endswith("\n"), "native lifetime witness must end with a newline")
    require(text.count(manifest.WITNESS_MARKER) == 1,
            "native lifetime requires exactly one lifetime witness")
    parent, separator, last = text[:-1].rpartition("\n")
    require(separator == "\n" and last.startswith(manifest.WITNESS_PREFIX),
            "native lifetime requires a final lifetime witness line")
    witness = preflight.decode_record(last[len(manifest.WITNESS_PREFIX):].encode("utf-8"))
    return parent + separator, witness


def _model(value, label, expected=None):
    fields(value, manifest.MODEL_FIELDS, label)
    projection = {name: value[name] for name in preflight.MODEL_FIELDS}
    parent_records._model(projection, label)
    uint(value["pending_reads"], label + ".pending_reads")
    fixed(value["pending_reads"], 0, label + ".pending_reads")
    if expected is not None:
        fixed(projection, expected, label + ".parent model")
    return projection


def _pending_reads(values, originals, label):
    require(type(values) is list and len(values) == len(originals),
            label + ": inventory length differs")
    for index, (value, original) in enumerate(zip(values, originals)):
        item = label + "[" + str(index) + "]"
        fields(value, manifest.PENDING_READ_FIELDS, item)
        for name in manifest.PENDING_READ_FIELDS:
            uint(value[name], item + "." + name)
        fixed(value["sequence"], original["sequence"], item + ".sequence")
        fixed(value["pending_before"], 0, item + ".pending_before")
        fixed(value["pending_after"], 0, item + ".pending_after")


def _snapshots(lifetime, witness, baseline):
    snapshots = lifetime["snapshots"]
    require(type(snapshots) is list and len(snapshots) == len(manifest.SNAPSHOT_NAMES),
            "native lifetime snapshot inventory differs")
    for index, (name, offset, snapshot, original) in enumerate(zip(
            manifest.SNAPSHOT_NAMES, manifest.SNAPSHOT_RESET_OFFSETS,
            snapshots, witness["snapshots"])):
        label = "native lifetime snapshot[" + str(index) + "]"
        fields(snapshot, manifest.SNAPSHOT_FIELDS, label)
        fixed(snapshot["name"], name, label + ".name")
        for side in ("before", "after"):
            _model(snapshot[side], label + "." + side, original[side])
            fixed(snapshot[side]["reset_generation"], baseline + offset,
                  label + "." + side + ".reset_generation")
        fixed(snapshot["after"], snapshot["before"], label + ".unchanged model")
    fixed(snapshots[0]["before"], lifetime["constructed_state"],
          "native lifetime construction/opening boundary")
    fixed(snapshots[3]["before"], snapshots[2]["after"],
          "native lifetime final cleanup boundary")


def _runs(lifetime, witness, baseline):
    runs = lifetime["runs"]
    require(type(runs) is list and len(runs) == manifest.OPERATIONS,
            "native lifetime run inventory differs")
    previous = lifetime["constructed_state"]
    for index, (run, flush) in enumerate(zip(runs, witness["cache_flush_reads"])):
        ordinal = index + 1
        label = "native lifetime run[" + str(index) + "]"
        fields(run, manifest.RUN_FIELDS, label)
        uint(run["ordinal"], label + ".ordinal", minimum=1)
        fixed(run["ordinal"], ordinal, label + ".ordinal")
        for side in ("before", "after"):
            _model(run[side], label + "." + side)
        for name, expected in manifest.SUCCESSFUL_RUN.items():
            fixed(run[name], expected, label + "." + name)
        reads = 66 if ordinal == 1 else 131 + ordinal
        for name in ("dcr_reads_before", "dcr_reads_after"):
            uint(run[name], label + "." + name)
            fixed(run[name], reads, label + "." + name)
        for name in ("cache_flushes_before", "cache_flushes_after"):
            uint(run[name], label + "." + name)
            fixed(run[name], index, label + "." + name)
        before, after = run["before"], run["after"]
        fixed(before["reset_generation"], baseline + index,
              label + ".before.reset_generation")
        fixed(after["reset_generation"], baseline + ordinal,
              label + ".after.reset_generation")
        fixed(before, previous, label + ".preceding boundary")
        for name in ("core_cycles", "core_instructions"):
            require(after[name] >= before[name], label + "." + name + " decreased")
        for side in ("before", "after"):
            fixed(flush["reset_" + side], baseline + ordinal,
                  label + ".flush reset " + side)
        # On the bound direct-RAM route, only the run and output flush tick.
        fixed(flush["ticks_before"], after["ticks"], label + ".flush entry clock")
        require(flush["ticks_after"] >= after["ticks"], label + ".flush clock decreased")
        previous = dict(after, ticks=flush["ticks_after"])
        if ordinal == 1:
            fixed(lifetime["snapshots"][1]["before"], previous,
                  "native lifetime prime snapshot boundary")
    fixed(lifetime["snapshots"][2]["before"], previous,
          "native lifetime final snapshot boundary")


def _destruction(lifetime, witness):
    value = lifetime["destruction"]
    original = witness["observation"]["destruction"]
    label = "native lifetime destruction"
    fields(value, manifest.DESTRUCTION_FIELDS, label)
    projected_before = _model(value["before"], label + ".before", original["before"])
    projection = dict(value, before=projected_before)
    fixed(projection, original, label + ".parent disposal")
    fixed(value["before"], lifetime["snapshots"][-1]["after"],
          label + ".terminal boundary")


def verify_output(text, *, contract, case, fmt, policy, binding_id, sample_id,
                  process_id, expected_libraries):
    """Recheck the original transcript and its required lifetime supplement."""
    parent_text, lifetime = _split_output(text)
    verified = parent_records.verify_output(parent_text, contract=contract, case=case,
        fmt=fmt, policy=policy, binding_id=binding_id, sample_id=sample_id,
        process_id=process_id, expected_libraries=expected_libraries)
    fields(lifetime, manifest.WITNESS_FIELDS, "native lifetime witness")
    for name, expected in manifest.process_identity(fmt, policy, binding_id).items():
        fixed(lifetime[name], expected, "native lifetime witness." + name)
    for name, expected in manifest.ROUTE.items():
        fixed(lifetime[name], expected, "native lifetime witness." + name)
    preflight.false_claims(lifetime, "native lifetime witness")
    fixed(lifetime["unresolved_obligations"], list(manifest.UNRESOLVED_OBLIGATIONS),
          "native lifetime unresolved obligations")
    fixed(lifetime["trace_overflow"], False, "native lifetime trace_overflow")
    witness = verified["witness"]
    _model(lifetime["constructed_state"], "native lifetime constructed state",
           witness["observation"]["constructed_state"])
    baseline = lifetime["constructed_state"]["reset_generation"]
    require(baseline <= manifest.MAX_UINT64 - manifest.OPERATIONS,
            "native lifetime reset generation would overflow")
    _snapshots(lifetime, witness, baseline)
    _pending_reads(lifetime["reads"], witness["reads"], "native lifetime MPM reads")
    _pending_reads(lifetime["cache_flush_reads"], witness["cache_flush_reads"],
                   "native lifetime cache-flush reads")
    _runs(lifetime, witness, baseline)
    _destruction(lifetime, witness)
    return dict(verified, lifetime=lifetime)
