# SPDX-License-Identifier: Apache-2.0
"""Synthetic retained-record tests; no native processor or public runtime runs."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from p06_contract import _COUNTERS
import p06_counter_public_records as records


UINT64_MAX = (1 << 64) - 1
SENTINEL = 0xDECAFBAD12345678
INVENTORY = tuple((row[0], row[1], row[2],
                   2 if row[0].startswith("dcache_") or row[0] == "tcu_lmem_reads" else 1)
                  for row in _COUNTERS if row[1] not in (5, 6))
ASSERTIONS = {"normal": 1668, "coherent-terminal": 1814, "immediate-overflow": 1176,
              "delayed-overflow": 1176, "cache-overflow": 1173}


def model(generation):
    return {"live": True, "inventory_ready": True, "idle": True, "any_running": False,
            "generation": generation, "ticks": 180, "reset_generation": 2 * generation,
            "pending_reads": 0, "core_cycles": 60, "core_instructions": 3,
            "exitcode": 7, "components": [60, 3] + [0] * 38}


def read(state, selected, sequence, value, high=False, failed=False):
    return {"sequence": sequence, "generation": state["generation"], "addr": 1,
            "tag": (selected[1] << 22) | ((selected[2] - 0xB00 + (32 if high else 0)) << 16),
            "value": (value >> (32 if high else 0)) & 0xFFFFFFFF, "status": -1 if failed else 0,
            "completed": not failed, "overflow": failed,
            "ticks_before": state["ticks"], "ticks_after": state["ticks"],
            "reset_before": state["reset_generation"], "reset_after": state["reset_generation"],
            "class_before": 0, "class_after": selected[1] if failed else 0}


def cp(expected):
    return {"control": 1, "queue_control": 1, "status": 0, "error": 0,
            "retired": expected, "expected": expected, "head_writeback_raw": 0,
            "head_writeback_status": "not-published", "runtime_tail": expected * 64,
            "tail_register_pair_raw": expected * 64, "drain_basis": "enabled-idle-status-and-retired-sequence"}


def terminal(generation, sequence, seeded=False):
    witness = model(generation)
    before = deepcopy(witness)
    if seeded:
        before["components"] = [0x1234567800000000 + 2 * index + component
                                for index, item in enumerate(INVENTORY) for component in range(item[3])]
        before["core_cycles"], before["core_instructions"] = before["components"][:2]
    rows, offset = [], 0
    for index, selected in enumerate(INVENTORY):
        name, perf_class, csr, count = selected
        value = sum(before["components"][offset:offset + count])
        rows.append({"name": name, "class": perf_class, "csr": csr, "components": count, "value": value,
                     "low": read(before, selected, sequence + 2 * index, value),
                     "high": read(before, selected, sequence + 2 * index + 1, value, high=True)})
        offset += count
    return {"seeded": seeded, "selectors": 33, "components": 40, "unavailable_unqueried": 12,
            "device_refs": 1, "queues": 0, "buffers": 0, "extra_retain_rejected": True,
            "witness": witness, "before": before, "after": deepcopy(before),
            "cp_before": cp(26), "cp_after": cp(92), "rows": rows}


def query(selected=INVENTORY[0]):
    return {"class": selected[1], "csr": selected[2], "status": 3, "before": SENTINEL, "after": SENTINEL}


def fault(mode):
    asynchronous = mode != "cache-overflow"
    seed = UINT64_MAX - (2 if mode == "delayed-overflow" else 0)
    if asynchronous:
        before = {"live": True, "inventory_ready": True, "idle": True, "any_running": False,
                  "generation": 1, "ticks": 0, "reset_generation": 1, "pending_reads": 0,
                  "core_cycles": seed, "core_instructions": 0, "exitcode": 0,
                  "components": [seed] + [0] * 39}
        after = deepcopy(before)
        after.update(idle=False, any_running=True, ticks=3, reset_generation=2,
                     core_cycles=UINT64_MAX, components=[UINT64_MAX] + [0] * 39)
        trigger, reads = None, []
    else:
        before = model(1)
        before["components"][16:18] = [UINT64_MAX, 1]
        after = deepcopy(before)
        trigger = query(INVENTORY[16])
        reads = [read(before, INVENTORY[16], 1, 0, failed=True)]
    entries = {"run": 1, "read": 0 if asynchronous else 1, "write": 19, "overflows": 1}
    return {"asynchronous": asynchronous, "seed": seed, "before": before, "after": after,
            "trigger_query": trigger, "reads": reads,
            "suppression": {"before_entries": entries, "after_entries": deepcopy(entries),
                            "queries": [query(), query()],
                            "dma": {"address": 0x80000000, "status": 3,
                                    "before": [0x00700193, 0x0000700B, 0x0000000B],
                                    "attempted": [0xFF8FFE6C, 0xFFFF8FF4, 0xFFFFFFF4],
                                    "after": [0x00700193, 0x0000700B, 0x0000000B]}}}


def result(mode="normal"):
    negative = mode in ("immediate-overflow", "delayed-overflow", "cache-overflow")
    asynchronous = mode in ("immediate-overflow", "delayed-overflow")
    read_errors = int(mode == "cache-overflow")
    failure = fault(mode) if negative else None
    terminals = ([terminal(2, 1 + read_errors)] if negative else
                 [terminal(1, 1, mode == "coherent-terminal"), terminal(2, 67)])
    states = [failure["after"], terminals[0]["after"]] if negative else [item["after"] for item in terminals]
    return {"schema_version": 2, "mode": mode, "backend": "simx", "memory_route": "direct-ram",
            "xlen": 64, "checked": True, "native_model": True, "public_runtime": True,
            "checks": ASSERTIONS[mode], "failures": 0, "constructed": 2, "destroyed": 2,
            "run_entries": 2, "run_completed": 1 if asynchronous else 2, "run_errors": int(asynchronous),
            "dcr_read_entries": (66 if negative else 132) + read_errors,
            "dcr_read_completed": 66 if negative else 132, "dcr_read_errors": read_errors,
            "dcr_write_entries": 38, "dcr_write_completed": 38, "overflow_errors": int(negative),
            "unexpected_errors": 0, "violations": 0, "fresh_context_success": True,
            "program_words_verified": 6, "terminal_failure": negative, "suppressed_requests": 5 if negative else 0,
            "failure": failure, "terminal_snapshots": terminals,
            "destructions": [{"before": deepcopy(state), "completed": True, "ticks_after": 0,
                              "reset_after": state["reset_generation"], "idle_after": True} for state in states],
            "qualified": False, "ready_for_warm": False, "warm_execution": False, "acceptance_claimed": False}


def output(value):
    return "synthetic dependency statistics\nCOUNTER_PUBLIC_RESULT " + json.dumps(value, separators=(",", ":")) + "\n"


def at(value, path):
    for key in path:
        value = value[key]
    return value


def replace(value, path, replacement):
    at(value, path[:-1])[path[-1]] = replacement


class PublicRecordsTests(unittest.TestCase):
    def reject(self, value):
        with self.assertRaises(ValueError):
            records.verify_output(output(value), value["mode"])

    def changed(self, path, replacement, mode="normal"):
        value = result(mode)
        replace(value, path, replacement)
        self.reject(value)

    def test_five_complete_synthetic_records_remain_nonqualifying(self):
        for mode in records.MODES:
            with self.subTest(mode=mode):
                value = result(mode)
                self.assertEqual(records.verify_output(output(value), mode), value)
                for name in ("qualified", "ready_for_warm", "warm_execution", "acceptance_claimed"):
                    self.assertIs(value[name], False)

    def test_inventory_matches_independent_frozen_public_contract(self):
        self.assertEqual(records.SELECTORS, INVENTORY)
        self.assertEqual(len(INVENTORY), 33)
        self.assertEqual(sum(item[3] for item in INVENTORY), 40)
        self.assertEqual(len(_COUNTERS) - len(INVENTORY), 12)

    def test_no_producer_paths_or_commands_are_consulted(self):
        text = output(result("cache-overflow"))
        with patch("builtins.open", side_effect=AssertionError("opened a producer path")), \
             patch.object(Path, "resolve", side_effect=AssertionError("resolved a producer path")), \
             patch.object(subprocess, "run", side_effect=AssertionError("executed retained code")):
            self.assertEqual(records.verify_output(text, "cache-overflow")["mode"], "cache-overflow")

    def test_unknown_mode_and_wrong_report_mode(self):
        for mode in (None, True, 1, "", "public", "boundaries"):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                records.verify_output(output(result()), mode)
        with self.assertRaises(ValueError):
            records.verify_output(output(result()), "coherent-terminal")

    def test_top_level_claims_cannot_be_promoted_or_relabeled(self):
        for key, replacement in (("schema_version", 1), ("native_model", False), ("checked", False),
                                 ("public_runtime", False), ("xlen", 32), ("memory_route", "llc"),
                                 ("backend", "mock"), ("qualified", True), ("ready_for_warm", True),
                                 ("warm_execution", True), ("acceptance_claimed", True),
                                 ("checks", ASSERTIONS["normal"] - 1), ("program_words_verified", 7)):
            with self.subTest(key=key):
                self.changed((key,), replacement)

    def test_booleans_cannot_substitute_for_integers_at_any_layer(self):
        paths = [("schema_version",), ("constructed",), ("failures",),
                 ("terminal_snapshots", 0, "device_refs"), ("terminal_snapshots", 0, "before", "generation"),
                 ("terminal_snapshots", 0, "before", "components", 2),
                 ("terminal_snapshots", 0, "cp_before", "control"),
                 ("terminal_snapshots", 0, "rows", 0, "value"),
                 ("terminal_snapshots", 0, "rows", 0, "low", "status"),
                 ("destructions", 0, "ticks_after")]
        for path in paths:
            with self.subTest(path=path):
                self.changed(path, True)
        self.changed(("failure", "suppression", "before_entries", "run"), True, "cache-overflow")
        self.changed(("failure", "trigger_query", "status"), True, "cache-overflow")

    def test_integers_cannot_substitute_for_boolean_observations(self):
        for path in (("native_model",), ("qualified",), ("terminal_snapshots", 0, "seeded"),
                     ("terminal_snapshots", 0, "before", "idle"),
                     ("terminal_snapshots", 0, "rows", 0, "low", "completed"),
                     ("destructions", 0, "idle_after")):
            with self.subTest(path=path):
                self.changed(path, int(at(result(), path)))

    def test_unknown_and_missing_nested_fields_are_rejected(self):
        paths = [(), ("terminal_snapshots", 0), ("terminal_snapshots", 0, "before"),
                 ("terminal_snapshots", 0, "cp_before"), ("terminal_snapshots", 0, "rows", 0),
                 ("terminal_snapshots", 0, "rows", 0, "low"), ("destructions", 0)]
        for path in paths:
            for extra in (True, False):
                with self.subTest(path=path, extra=extra):
                    value = result()
                    selected = at(value, path)
                    if extra:
                        selected["unsupported"] = False
                    else:
                        del selected[next(key for key in selected if key != "mode")]
                    self.reject(value)
        for path in (("failure",), ("failure", "trigger_query"), ("failure", "suppression"),
                     ("failure", "suppression", "after_entries"), ("failure", "suppression", "queries", 0)):
            with self.subTest(path=path):
                value = result("cache-overflow")
                at(value, path)["unsupported"] = 0
                self.reject(value)

    def test_counter_inventory_cannot_be_shortened_duplicated_or_disabled(self):
        value = result()
        value["terminal_snapshots"][0]["rows"].pop()
        self.reject(value)
        value = result()
        value["terminal_snapshots"][0]["rows"][1] = deepcopy(value["terminal_snapshots"][0]["rows"][0])
        self.reject(value)
        for path, replacement in ((("selectors",), 32), (("unavailable_unqueried",), 13),
                                  (("rows", 16, "class"), 5), (("rows", 16, "name"), "l2cache_reads"),
                                  (("rows", 16, "components"), 1)):
            self.changed(("terminal_snapshots", 0) + path, replacement)

    def test_real_backing_banks_and_aggregate_bounds_are_checked(self):
        value = result("coherent-terminal")
        snapshot = value["terminal_snapshots"][0]
        for state in (snapshot["before"], snapshot["after"], value["destructions"][0]["before"]):
            state["components"][17] += 1
        row = snapshot["rows"][16]
        row["value"] += 1
        row["low"]["value"] += 1
        self.reject(value)
        value = result()
        snapshot = value["terminal_snapshots"][0]
        for state in (snapshot["witness"], snapshot["before"], snapshot["after"], value["destructions"][0]["before"]):
            state["components"][16:18] = [UINT64_MAX, 1]
        self.reject(value)

    def test_component_inventory_and_duplicate_core_observations_are_checked(self):
        value = result()
        value["terminal_snapshots"][0]["before"]["components"].pop()
        self.reject(value)
        self.changed(("terminal_snapshots", 0, "before", "core_cycles"), 61)
        self.changed(("terminal_snapshots", 0, "before", "components", 2), -1)
        self.changed(("terminal_snapshots", 0, "before", "components", 2), UINT64_MAX + 1)

    def test_coherent_seeds_cannot_be_replaced_by_zero_only_coverage(self):
        value = result("coherent-terminal")
        value["terminal_snapshots"][0] = terminal(1, 1)
        value["terminal_snapshots"][0]["seeded"] = True
        value["destructions"][0]["before"] = deepcopy(value["terminal_snapshots"][0]["after"])
        self.reject(value)
        self.changed(("terminal_snapshots", 1, "seeded"), True, "coherent-terminal")

    def test_both_half_words_tags_orders_and_classes_are_verified(self):
        for key, replacement in (("value", 0), ("tag", 0), ("addr", 2), ("status", 3),
                                 ("completed", False), ("overflow", True), ("sequence", 4),
                                 ("generation", 2), ("class_before", 4), ("class_after", 4),
                                 ("ticks_after", 181), ("reset_after", 3)):
            with self.subTest(key=key):
                self.changed(("terminal_snapshots", 0, "rows", 0, "high", key), replacement,
                             "coherent-terminal")
        self.changed(("terminal_snapshots", 0, "rows", 1, "low", "tag"), 1)
        value = result("coherent-terminal")
        row = value["terminal_snapshots"][0]["rows"][0]
        row["low"], row["high"] = row["high"], row["low"]
        self.reject(value)

    def test_public_result_must_reconstruct_actual_backing_values(self):
        self.changed(("terminal_snapshots", 0, "rows", 0, "value"), 0)
        value = result("coherent-terminal")
        row = value["terminal_snapshots"][0]["rows"][0]
        row["value"] = row["low"]["value"]
        row["high"]["value"] = 0
        self.reject(value)

    def test_model_cannot_advance_between_halves_or_at_resource_release(self):
        self.changed(("terminal_snapshots", 0, "rows", 0, "high", "ticks_before"), 181)
        self.changed(("terminal_snapshots", 0, "rows", 0, "high", "reset_before"), 3)
        self.changed(("terminal_snapshots", 0, "after", "ticks"), 181)
        self.changed(("terminal_snapshots", 0, "witness", "ticks"), 179)

    def test_terminal_ownership_and_completed_execution_are_required(self):
        for key, replacement in (("device_refs", 2), ("queues", 1), ("buffers", 1),
                                 ("extra_retain_rejected", False)):
            self.changed(("terminal_snapshots", 0, key), replacement)
        for key, replacement in (("idle", False), ("any_running", True), ("pending_reads", 1),
                                 ("exitcode", 0), ("ticks", 0)):
            self.changed(("terminal_snapshots", 0, "before", key), replacement)
        value = result()
        for state in (value["terminal_snapshots"][1][key] for key in ("before", "after", "witness")):
            state["core_instructions"] = state["components"][1] = 0
        self.reject(value)

    def test_cp_must_be_enabled_idle_and_retire_each_half(self):
        for key, replacement in (("control", 0), ("queue_control", 0), ("status", 1), ("error", 1),
                                 ("retired", 25), ("runtime_tail", 25 * 64),
                                 ("tail_register_pair_raw", 25 * 64), ("expected", 0)):
            self.changed(("terminal_snapshots", 0, "cp_before", key), replacement)
        self.changed(("terminal_snapshots", 0, "cp_after"), cp(91))
        value = result()
        value["terminal_snapshots"][0]["cp_before"].update(runtime_tail=64, tail_register_pair_raw=64)
        self.reject(value)

    def test_cp_raw_head_is_retained_without_claiming_published_head(self):
        value = result()
        observed = value["terminal_snapshots"][0]["cp_before"]
        self.assertEqual(observed["head_writeback_raw"], 0)
        self.assertNotEqual(observed["head_writeback_raw"], observed["tail_register_pair_raw"])
        self.assertEqual(records.verify_output(output(value), "normal"), value)
        for key, replacement in (("head_writeback_raw", observed["tail_register_pair_raw"]),
                                 ("head_writeback_raw", True),
                                 ("head_writeback_status", "published"),
                                 ("drain_basis", "observed-head-equals-tail")):
            self.changed(("terminal_snapshots", 0, "cp_before", key), replacement)
        value = result()
        for key in ("cp_before", "cp_after"):
            observed = value["terminal_snapshots"][0][key]
            observed["head"] = observed.pop("head_writeback_raw")
        self.reject(value)

    def test_cp_tail_observations_are_bounded_integers_and_account_for_every_cacheline(self):
        for key in ("runtime_tail", "tail_register_pair_raw"):
            for replacement in (True, -1, 0, UINT64_MAX + 1):
                with self.subTest(key=key, replacement=replacement):
                    self.changed(("terminal_snapshots", 0, "cp_before", key), replacement)
        for delta in (-64, 1, 64):
            value = result()
            observed = value["terminal_snapshots"][0]["cp_before"]
            observed["runtime_tail"] += delta
            observed["tail_register_pair_raw"] += delta
            self.reject(value)

    def test_actual_destruction_must_match_last_observation(self):
        for path, replacement in ((("completed",), False), (("ticks_after",), 1),
                                  (("reset_after",), 0), (("idle_after",), False),
                                  (("before", "ticks"), 181), (("before", "components", 2), 1)):
            self.changed(("destructions", 0) + path, replacement)
        self.changed(("destructions",), result()["destructions"][:1])
        self.changed(("terminal_snapshots", 1, "before", "generation"), 1)
        self.changed(("terminal_snapshots", 1, "before", "reset_generation"), 2)

    def test_native_failure_counts_and_global_entries_are_exact(self):
        for mode in records.MODES:
            for key in ("run_entries", "run_completed", "run_errors", "dcr_read_entries", "dcr_read_completed",
                        "dcr_read_errors", "dcr_write_entries", "dcr_write_completed", "overflow_errors"):
                with self.subTest(mode=mode, key=key):
                    value = result(mode)
                    value[key] += 1
                    self.reject(value)

    def test_async_failure_must_reach_actual_saturated_destination(self):
        for mode in ("immediate-overflow", "delayed-overflow"):
            value = result(mode)
            value["failure"]["after"]["components"][0] = 0
            value["failure"]["after"]["core_cycles"] = 0
            self.reject(value)
            self.changed(("failure", "after", "core_instructions"), 1, mode)
            self.changed(("failure", "before", "components", 2), 1, mode)
            self.changed(("failure", "before", "idle"), False, mode)
            self.changed(("failure", "before", "reset_generation"), 2, mode)
            self.changed(("failure", "trigger_query"), query(), mode)
            self.changed(("failure", "reads"), [result("cache-overflow")["failure"]["reads"][0]], mode)

    def test_delayed_failure_requires_two_real_increments_and_tick_progress(self):
        self.changed(("failure", "seed"), UINT64_MAX, "delayed-overflow")
        self.changed(("failure", "after", "ticks"), 0, "delayed-overflow")
        value = result("delayed-overflow")
        value["failure"]["before"]["core_cycles"] = UINT64_MAX - 1
        value["failure"]["before"]["components"][0] = UINT64_MAX - 1
        self.reject(value)

    def test_actual_two_bank_cache_fault_and_failed_half_are_required(self):
        self.changed(("failure", "before", "components", 17), 0, "cache-overflow")
        self.changed(("failure", "reads"), [], "cache-overflow")
        for key, replacement in (("completed", True), ("overflow", False), ("class_after", 0),
                                 ("class_before", 4), ("status", 0), ("value", 1),
                                 ("tag", (4 << 22) | (35 << 16))):
            self.changed(("failure", "reads", 0, key), replacement, "cache-overflow")
        self.changed(("failure", "after", "ticks"), 181, "cache-overflow")

    def test_public_failed_destinations_status_and_selector_are_raw_obligations(self):
        for path in (("failure", "trigger_query"), ("failure", "suppression", "queries", 0),
                     ("failure", "suppression", "queries", 1)):
            for key, replacement in (("status", 0), ("before", 0), ("after", 0), ("csr", 2818)):
                with self.subTest(path=path, key=key):
                    self.changed(path + (key,), replacement, "cache-overflow")

    def test_rejected_dma_requires_different_payload_and_unchanged_actual_ram(self):
        for mode in ("immediate-overflow", "delayed-overflow", "cache-overflow"):
            for field in ("before", "after"):
                with self.subTest(mode=mode, field=field):
                    value = result(mode)
                    dma = value["failure"]["suppression"]["dma"]
                    dma[field] = list(dma["attempted"])
                    self.reject(value)
            value = result(mode)
            dma = value["failure"]["suppression"]["dma"]
            dma["attempted"] = list(dma["before"])
            self.reject(value)
            for key, replacement in (("status", 0), ("address", UINT64_MAX), ("address", True),
                                     ("after", [True, 0x0000700B, 0x0000000B])):
                self.changed(("failure", "suppression", "dma", key), replacement, mode)

    def test_queue_error_consumption_cannot_revive_model_entries(self):
        for mode in ("immediate-overflow", "delayed-overflow", "cache-overflow"):
            for key in ("run", "read", "write", "overflows"):
                with self.subTest(mode=mode, key=key):
                    value = result(mode)
                    value["failure"]["suppression"]["after_entries"][key] += 1
                    self.reject(value)
            value = result(mode)
            for key in ("before_entries", "after_entries"):
                value["failure"]["suppression"][key]["write"] += 1
            self.reject(value)
            self.changed(("suppressed_requests",), 4, mode)

    def test_negative_context_destruction_and_fresh_success_are_both_bound(self):
        self.changed(("destructions", 0, "before", "ticks"), 4, "immediate-overflow")
        self.changed(("destructions", 1, "before", "components", 0), UINT64_MAX, "cache-overflow")
        self.changed(("terminal_snapshots", 0, "seeded"), True, "cache-overflow")
        self.changed(("fresh_context_success",), False, "delayed-overflow")

    def test_duplicate_json_keys_are_rejected_at_all_depths(self):
        text = output(result())
        for needle, replacement in (("\"schema_version\":2", "\"schema_version\":2,\"schema_version\":2"),
                                    ("\"generation\":1", "\"generation\":1,\"generation\":1"),
                                    ("\"status\":0", "\"status\":0,\"status\":0")):
            with self.subTest(needle=needle), self.assertRaises(ValueError):
                records.verify_output(text.replace(needle, replacement, 1), "normal")

    def test_result_requires_unique_complete_final_line_without_failure(self):
        text = output(result())
        corrupt = ("", text + text, text + "FAIL trailing failure\n", "FAILED native check\n" + text,
                   "ERROR crash\n" + text, "SIMX_CHECKED_COUNTER_FAILURE: overflow\n" + text,
                   "CHECKED_COUNTERS_RESULT {}\n" + text, text.rstrip() + " trailing bytes\n",
                   " " + text.split("\n", 1)[1], text + "unexpected later output\n")
        for index, value in enumerate(corrupt):
            with self.subTest(index=index), self.assertRaises(ValueError):
                records.verify_output(value, "normal")

    def test_reserved_result_markers_cannot_be_mixed_or_malformed_noise(self):
        text = output(result())
        markers = ("CHECKED_COUNTERS_RESULT", "CHECKED_COUNTERS_FAILURE_RESULT", "COUNTER_PUBLIC_RESULT")
        for marker in markers:
            for suffix in ("", " {}", "\t{}", ": malformed", "_EXTRA {}"):
                for leading in ("", " ", "dependency statistics: "):
                    with self.subTest(marker=marker, suffix=suffix, leading=leading), self.assertRaises(ValueError):
                        records.verify_output(leading + marker + suffix + "\n" + text, "normal")

    def test_malformed_nonfinite_float_and_oversized_integer_json_is_rejected(self):
        text = output(result())
        for replacement in ("NaN", "Infinity", "-Infinity", "1668.0", "1e3", "1" * 21, "null", '"1668"'):
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                records.verify_output(text.replace("\"checks\":1668", "\"checks\":" + replacement), "normal")
        for payload in ("{", "[]", "true", "[" * 17 + "0" + "]" * 17):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                records.verify_output(records.RESULT_PREFIX + payload + "\n", "normal")

    def test_log_controls_and_byte_bounds_are_enforced(self):
        text = output(result())
        for prefix in ("\r", "\x00", "\x1b", "\x85", "\u2028"):
            with self.subTest(prefix=repr(prefix)), self.assertRaises(ValueError):
                records.verify_output(prefix + text, "normal")
        with self.assertRaises(ValueError):
            records.verify_output("x" * (records.MAX_OUTPUT_BYTES + 1), "normal")
        with self.assertRaises(ValueError):
            records.verify_output(records.RESULT_PREFIX + " " * records.MAX_RESULT_BYTES + "{}\n", "normal")
        for value in (None, b"COUNTER_PUBLIC_RESULT {}", 1):
            with self.subTest(type=type(value)), self.assertRaises(ValueError):
                records.verify_output(value, "normal")


if __name__ == "__main__":
    unittest.main()
