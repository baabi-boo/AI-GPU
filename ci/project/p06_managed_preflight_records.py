# SPDX-License-Identifier: Apache-2.0
"""Validate bounded managed-preflight records as inert, untrusted data.

The unchanged warm verifier owns the original operation and snapshot records.
This module verifies the separately emitted native witness and cross-checks its
raw observations against those records. It neither opens recorded paths nor
executes retained code, and does not confer counter or performance qualification.
"""

from __future__ import annotations

import p06_managed_preflight_contract as manifest
import p06_warm_records as warm_records


require = manifest.require
fixed = manifest.fixed
fields = manifest.fields
uint = manifest.uint

_MPM_BASE = 0xB00
_MPM_VALUE_DCR = 0x001
_PACKET_BYTES = 64


def _split_output(text):
    """Keep every original warm byte; remove only the final witness line."""
    require(type(text) is str, "managed preflight output must be text")
    try:
        encoded = text.encode("utf-8", "strict")
    except UnicodeError as error:
        raise manifest.ContractError("managed preflight output is not valid UTF-8") from error
    require(0 < len(encoded) <= manifest.MAX_OUTPUT_BYTES,
            "managed preflight output exceeds its byte bound")
    require("\r" not in text and "\x00" not in text,
            "managed preflight output contains noncanonical line data")
    require(text.endswith("\n"), "managed preflight witness must end with a newline")
    require(text.count(manifest.WITNESS_MARKER) == 1,
            "managed preflight requires exactly one witness marker")
    # rpartition avoids rebuilding or normalizing the warm part of the log.
    warm_text, separator, last = text[:-1].rpartition("\n")
    require(separator == "\n" and last.startswith(manifest.WITNESS_PREFIX),
            "managed preflight requires a final witness line")
    warm_text += separator
    require(warm_text.endswith("PASSED!\n"),
            "managed preflight witness must immediately follow warm success")
    witness = manifest.decode_record(last[len(manifest.WITNESS_PREFIX):].encode("utf-8"))
    return warm_text, witness


def _model(value, label):
    fields(value, manifest.MODEL_FIELDS, label)
    for name in ("generation", "ticks", "reset_generation", "core_cycles", "core_instructions"):
        uint(value[name], label + "." + name)
    for name, expected in (("live", True), ("idle", True), ("any_running", False),
                           ("generation", 1)):
        fixed(value[name], expected, label + "." + name)
    require(type(value["exitcode"]) is int and -(1 << 31) <= value["exitcode"] < (1 << 31),
            label + ".exitcode: expected a native signed 32-bit integer")


def _observation(value):
    label = "managed observation"
    fields(value, manifest.OBSERVATION_FIELDS, label)
    for name in manifest.OBSERVATION_COUNTER_FIELDS:
        uint(value[name], label + "." + name)
    for name in ("constructed", "destroyed", "constructor_entries", "destructor_entries", "generation"):
        fixed(value[name], 1, label + "." + name)
    for name in ("run_entries", "run_completed"):
        fixed(value[name], manifest.OPERATIONS, label + "." + name)
    fixed(value["read_count"], manifest.PER_PROCESS["half_replies"], label + ".read_count")
    fixed(value["cache_flush_count"], manifest.OPERATIONS, label + ".cache_flush_count")
    for name in ("dcr_read_entries", "dcr_read_completed"):
        fixed(value[name], manifest.PER_PROCESS["dcr_reads"], label + "." + name)
    for name in ("run_errors", "dcr_read_errors", "dcr_write_errors", "overflow_errors",
                 "underflow_errors", "negative_operand_errors", "unexpected_errors", "violations"):
        fixed(value[name], 0, label + "." + name)
    fixed(value["dcr_write_completed"], value["dcr_write_entries"],
          label + ".completed DCR writes")
    fixed(value["live"], False, label + ".live")
    _model(value["constructed_state"], label + ".constructed_state")

    destruction = value["destruction"]
    fields(destruction, manifest.DESTRUCTION_FIELDS, label + ".destruction")
    _model(destruction["before"], label + ".destruction.before")
    fixed(destruction["completed"], True, label + ".destruction.completed")
    fixed(destruction["idle_after"], True, label + ".destruction.idle_after")
    uint(destruction["ticks_after"], label + ".destruction.ticks_after")
    uint(destruction["reset_after"], label + ".destruction.reset_after")
    # SimPlatform::finalize clears cycles but does not increment reset_gen.
    # Requiring clock monotonicity over disposal would reject the real source.
    fixed(destruction["ticks_after"], 0, label + ".destruction.ticks_after")
    fixed(destruction["reset_after"], destruction["before"]["reset_generation"],
          label + ".destruction.reset_after")


def _cp(value, label):
    fields(value, manifest.CP_FIELDS, label)
    for name in ("control", "queue_control", "status", "error", "retired"):
        uint(value[name], label + "." + name, bits=32)
    uint(value["expected"], label + ".expected", bits=32, minimum=1)
    for name in ("head_writeback_raw", "runtime_tail", "tail_register_pair_raw"):
        uint(value[name], label + "." + name)
    for name, expected in (("control", 1), ("queue_control", 1), ("status", 0), ("error", 0),
                           ("head_writeback_raw", 0), ("head_writeback_status", "not-published"),
                           ("drain_basis", "enabled-idle-status-and-retired-sequence")):
        fixed(value[name], expected, label + "." + name)
    fixed(value["retired"], value["expected"], label + ".retirement")
    fixed(value["runtime_tail"], value["expected"] * _PACKET_BYTES, label + ".runtime_tail")
    fixed(value["tail_register_pair_raw"], value["runtime_tail"], label + ".tail_register_pair_raw")


def _read(value, *, index, descriptor, high, expected_value, model, saved_class, completed_runs):
    label = "managed read[" + str(index) + "]"
    fields(value, manifest.READ_FIELDS, label)
    for name in ("sequence", "generation", "completed_runs", "ticks_before", "ticks_after", "reset_before", "reset_after"):
        uint(value[name], label + "." + name)
    for name in ("addr", "tag", "value", "class_before", "class_after"):
        uint(value[name], label + "." + name, bits=32)
    offset = descriptor["csr"] - _MPM_BASE + (32 if high else 0)
    tag = (descriptor["mpm_class"] << 22) | (offset << 16) | descriptor["core_id"]
    expected_half = (expected_value >> (32 if high else 0)) & manifest.MAX_UINT32
    expected = {
        "sequence": index + 1 + completed_runs, "generation": 1, "addr": _MPM_VALUE_DCR,
        "completed_runs": completed_runs,
        "tag": tag, "value": expected_half, "status": 0,
        "completed": True, "overflow": False,
        "ticks_before": model["ticks"], "ticks_after": model["ticks"],
        "reset_before": model["reset_generation"], "reset_after": model["reset_generation"],
        "class_before": saved_class, "class_after": saved_class,
        "idle_before": True, "idle_after": True,
        "any_running_before": False, "any_running_after": False,
    }
    for name, expected_item in expected.items():
        fixed(value[name], expected_item, label + "." + name)


def _snapshots(witness, warm, inventory):
    snapshots = witness["snapshots"]
    reads = witness["reads"]
    require(type(snapshots) is list and len(snapshots) == len(manifest.SNAPSHOT_NAMES),
            "managed snapshot inventory differs")
    require(type(reads) is list and len(reads) == manifest.PER_PROCESS["half_replies"],
            "managed raw reply inventory differs")
    observation = witness["observation"]
    enabled_names = [descriptor["name"] for descriptor in inventory["enabled"]]
    unavailable_names = [descriptor["name"] for descriptor in inventory["unavailable"]]
    previous_reset = None
    for ordinal, (name, snapshot) in enumerate(zip(manifest.SNAPSHOT_NAMES, snapshots)):
        label = "managed snapshot " + name
        fields(snapshot, manifest.SNAPSHOT_FIELDS, label)
        fixed(snapshot["name"], name, label + ".name")
        for side in ("before", "after"):
            _model(snapshot[side], label + "." + side)
        fixed(snapshot["after"], snapshot["before"], label + ".unchanged model")
        model = snapshot["before"]
        if previous_reset is not None:
            require(model["reset_generation"] >= previous_reset,
                    label + ": reset generation moved backwards")
        previous_reset = model["reset_generation"]
        for key in ("read_begin", "read_end", "device_refs", "queues", "buffers", "cache_flush_count"):
            uint(snapshot[key], label + "." + key)
        require(snapshot["device_refs"] > 0, label + ": no runtime owner")
        fixed(snapshot["queues"], 0, label + ".queues")
        begin = ordinal * manifest.HALVES_PER_SNAPSHOT
        end = begin + manifest.HALVES_PER_SNAPSHOT
        fixed(snapshot["read_begin"], begin, label + ".read_begin")
        fixed(snapshot["read_end"], end, label + ".read_end")
        completed_runs = (0, 1, manifest.OPERATIONS, manifest.OPERATIONS)[ordinal]
        fixed(snapshot["cache_flush_count"], completed_runs, label + ".cache_flush_count")

        # The original verifier validates all 45 descriptors, capability gates,
        # and unavailable null rows. Preserve that result and bind raw reads only
        # to its 33 enabled rows in the exact original order.
        rows = warm["summary"]["snapshots"][name]["counters"]
        enabled = [row for row in rows if row["enabled"] is True]
        unavailable = [row for row in rows if row["enabled"] is False]
        fixed([row["name"] for row in enabled], enabled_names, label + ".enabled inventory")
        fixed([row["name"] for row in unavailable], unavailable_names, label + ".unavailable inventory")
        values = {row["name"]: row["value"] for row in enabled}
        fixed(model["core_cycles"], values["cycles"], label + ".actual core cycles")
        fixed(model["core_instructions"], values["instructions"], label + ".actual core instructions")
        # Validate the first row before reading its saved class. Every tagged
        # query must restore this class throughout the quiescent snapshot.
        fields(reads[begin], manifest.READ_FIELDS, "managed first snapshot read")
        saved_class = reads[begin]["class_before"]
        uint(saved_class, label + ".saved class", bits=32)
        for selected, (descriptor, public) in enumerate(zip(inventory["enabled"], enabled)):
            index = begin + 2 * selected
            for half in (0, 1):
                _read(reads[index + half], index=index + half, descriptor=descriptor,
                      high=bool(half), expected_value=public["value"], model=model,
                      saved_class=saved_class, completed_runs=completed_runs)
            reconstructed = reads[index]["value"] | (reads[index + 1]["value"] << 32)
            fixed(reconstructed, public["value"], label + ".reconstructed " + descriptor["name"])
            if ordinal == 0:
                fixed(reconstructed, 0, label + ".zero opening aggregate " + descriptor["name"])

        if ordinal == len(manifest.SNAPSHOT_NAMES) - 1:
            fixed(snapshot["device_refs"], 1, label + ".device_refs")
            fixed(snapshot["buffers"], 0, label + ".buffers")
            _cp(snapshot["cp_before"], label + ".cp_before")
            _cp(snapshot["cp_after"], label + ".cp_after")
            fixed(snapshot["cp_after"]["expected"],
                  snapshot["cp_before"]["expected"] + manifest.HALVES_PER_SNAPSHOT,
                  label + ".terminal query retirement")
            fixed(observation["destruction"]["before"], snapshot["after"],
                  label + ".destruction boundary")
        else:
            fixed(snapshot["cp_before"], None, label + ".cp_before")
            fixed(snapshot["cp_after"], None, label + ".cp_after")
        if ordinal == 0:
            fixed(observation["constructed_state"], model, label + ".construction boundary")


def _cache_flushes(witness):
    """Account for the unchanged caller's one full output-DMA flush per launch."""
    reads = witness["cache_flush_reads"]
    require(type(reads) is list and len(reads) == manifest.OPERATIONS,
            "managed cache-flush read inventory differs")
    first_reset = witness["snapshots"][0]["after"]["reset_generation"]
    last_reset = witness["snapshots"][2]["before"]["reset_generation"]
    previous_reset = first_reset
    for index, value in enumerate(reads):
        label = "managed cache-flush read[" + str(index) + "]"
        fields(value, manifest.READ_FIELDS, label)
        for name in ("sequence", "generation", "completed_runs", "ticks_before", "ticks_after", "reset_before", "reset_after"):
            uint(value[name], label + "." + name)
        for name in ("addr", "tag", "value", "class_before", "class_after"):
            uint(value[name], label + "." + name, bits=32)
        expected = {
            "sequence": 67 if index == 0 else 133 + index,
            "generation": 1, "completed_runs": index + 1,
            "addr": 0, "tag": 0, "value": 0, "status": 0,
            "completed": True, "overflow": False,
            "reset_after": value["reset_before"], "class_after": value["class_before"],
            "idle_before": True, "idle_after": True,
            "any_running_before": False, "any_running_after": False,
        }
        for name, item in expected.items():
            fixed(value[name], item, label + "." + name)
        require(value["ticks_after"] >= value["ticks_before"], label + ": flush clock moved backwards")
        require(previous_reset <= value["reset_before"] <= last_reset,
                label + ": flush reset generation is outside the observed lifetime")
        previous_reset = value["reset_before"]
    fixed(reads[0]["reset_after"], witness["snapshots"][1]["before"]["reset_generation"],
          "prime cache-flush reset generation")
    fixed(reads[-1]["reset_after"], last_reset, "last cache-flush reset generation")
    fixed(sorted(row["sequence"] for row in witness["reads"] + reads),
          list(range(1, manifest.PER_PROCESS["dcr_reads"] + 1)), "complete DCR read sequence")


def verify_output(text, *, contract, case, fmt, policy, binding_id, sample_id,
                  process_id, expected_libraries):
    """Verify one of the four fixed processes without granting qualification.

    ``expected_libraries`` is an independently supplied mapping of the five
    names to the runner's bound absolute paths. Recorded paths are compared
    lexically; they are never opened. The returned ``warm`` object is exactly
    the unchanged warm verifier's result for the original warm prefix.
    """
    manifest.validate_contract(contract)
    identity = manifest.process_identity(fmt, policy, binding_id)
    fixed(sample_id, identity["sample_id"], "managed sample identity")
    fixed(process_id, identity["process_id"], "managed process identity")
    fields(expected_libraries, manifest.LOADED_LIBRARY_NAMES, "expected loaded library paths")
    warm_text, witness = _split_output(text)
    fields(witness, manifest.WITNESS_FIELDS, "managed witness")
    for name, value in identity.items():
        fixed(witness[name], value, "managed witness." + name)
    for name, value in (("backend", "simx"), ("xlen", 64), ("checked_counter_bits", 64),
                        ("simulation_workers", 1), ("seeded", False)):
        fixed(witness[name], value, "managed witness." + name)
    manifest.false_claims(witness, "managed witness")
    fixed(witness["unresolved_obligations"], list(manifest.UNRESOLVED_OBLIGATIONS),
          "managed unresolved obligations")
    manifest.validate_loaded_libraries(witness["loaded_libraries"], expected_libraries)
    warm = warm_records.verify_output(
        warm_text, case=case, fmt=fmt, policy=policy, binding_id=binding_id,
        sample_id=sample_id, pair_index=0, phase="warmup",
        contract=manifest.warm.load_contract(manifest.ROOT))
    _observation(witness["observation"])
    _snapshots(witness, warm, manifest.counter_inventory(contract))
    _cache_flushes(witness)
    return {"warm": warm, "witness": witness}
