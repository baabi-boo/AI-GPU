#!/usr/bin/env python3
"""Agent 21: coordinated host-only retained lifecycle mutations, no GPU work."""

import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1] / "AI-GPU"
sys.path.insert(0, str(ROOT / "ci/project"))

import p05_execution_records as base_records
import p05_torch_records as torch_records
from p05_qualification_test_fixture import raw_log as base_raw_log
from p05_torch_qualification_test_fixture import raw_log, synthetic
from test_p05_retained_observation_records import denied_live_access, retained_identity


SOURCES = (
    "ci/project/p03_execution_records.py",
    "ci/project/p04_execution_records.py",
    "ci/project/p05_execution_records.py",
    "ci/project/p05_installed_check.py",
    "ci/project/p05_torch_records.py",
    "ci/project/p05_qualification_test_fixture.py",
    "ci/project/p05_torch_qualification_test_fixture.py",
    "ci/project/test_p05_retained_observation_records.py",
    "docs/designs/torch_archive_replay_v1.md",
    "docs/project/evidence/p05-torch/reviews/archive_reader.py",
)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def source_hashes():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCES}


def numerical_projection(value):
    base = value["base_observations"]
    return {
        "matmul": [row["actual_bits"] for row in base["matmuls"]],
        "models": [
            {**{key: row["record"]["trace"][key] for key in
                ("hidden_words", "bridge_words", "bridge_bytes", "output_words")},
             "stages": [{key: stage[key] for key in ("a_bytes", "b_bytes", "output_words")}
                        for stage in row["record"]["trace"]["native"]]}
            for row in base["models"]
        ],
        "framework_matmuls": value["framework_matmuls"],
        "framework_models": value["framework_models"],
    }


def launch_dispatches(value):
    base = value["base_observations"]
    return ([row["trace"] for row in base["matmuls"]] +
            [stage["dispatch"] for row in base["models"]
             for stage in row["record"]["trace"]["native"]])


def mutations():
    # Missing each of the five event slots in a different late launch covers
    # the final direct matmul and all three model stage positions.
    for slot, launch in enumerate((5, 31, 32, 33, 35)):
        def remove_slot(value, slot=slot, launch=launch):
            dispatch = launch_dispatches(value)[launch]
            for key in ("event_results", "event_profile_results", "event_profile_queried", "event_profiles"):
                dispatch[key].pop(slot)
        yield f"missing_event_{slot}_launch_{launch}", remove_slot, "five-event"

    for launch in (5, 35):
        def reorder(value, launch=launch):
            dispatch = launch_dispatches(value)[launch]
            for key in ("event_results", "event_profile_results", "event_profile_queried", "event_profiles"):
                dispatch[key][3], dispatch[key][4] = dispatch[key][4], dispatch[key][3]
        yield f"reordered_pair_launch_{launch}", reorder, ("ordering", "predecessor")

        def duplicate(value, launch=launch):
            dispatch = launch_dispatches(value)[launch]
            for key in ("event_results", "event_profile_results", "event_profile_queried", "event_profiles"):
                dispatch[key][4] = copy.deepcopy(dispatch[key][3])
        yield f"duplicated_pair_launch_{launch}", duplicate, ("ordering", "predecessor")

    yield "completed_matmul_close_but_incomplete_wait", (
        lambda value: value["base_observations"]["matmuls"][-1]["status"].update(complete=False)
    ), "matmul completion"
    yield "completed_matmul_wait_but_incomplete_close", (
        lambda value: value["base_observations"]["matmuls"][-1]["close_status"].update(complete=False)
    ), "matmul close"
    yield "successful_matmul_close_but_resource_leak", (
        lambda value: value["base_observations"]["matmuls"][-1]["resources"].update(used_after=0x20004)
    ), "resources did not return"
    yield "successful_model_cleanup_but_owner_open", (
        lambda value: value["base_observations"]["models"][-1]["record"]["trace"].update(owner_closed=False)
    ), "owner_closed"
    yield "successful_stage_cleanup_but_stage_open", (
        lambda value: value["base_observations"]["models"][-1]["record"]["trace"]["native"][-1].update(closed=False)
    ), "stage.closed"
    yield "closed_stage_but_incomplete_completion", (
        lambda value: value["base_observations"]["models"][-1]["record"]["trace"]["native"][-1]["completion"].update(complete=False)
    ), "native completion.complete"
    yield "closed_stage_but_failed_cleanup", (
        lambda value: value["base_observations"]["models"][-1]["record"]["trace"]["native"][-1]["cleanup"].update(cleanup=6)
    ), "native cleanup.cleanup"
    yield "successful_model_close_but_resource_leak", (
        lambda value: value["base_observations"]["models"][-1]["record"]["trace"]["resources"].update(free_after=0x100004)
    ), "model resources were not restored"


def main():
    started = time.monotonic()
    before = source_hashes()
    results = []
    for fmt in ("fp16", "bf16"):
        with tempfile.TemporaryDirectory(prefix="a21-inert-lifecycle-") as temporary:
            producer = Path(temporary) / "producer"
            value, request, native = synthetic(producer, fmt)
            identity = retained_identity(value, request)
            adapter = Path(value["framework"]["adapter_file"]).read_bytes()
            numerical_digest = digest(numerical_projection(value))
            request_digest, native_digest = digest(request), digest(native)
            shutil.rmtree(producer)

            def verify(candidate, endpoint):
                if endpoint == "python":
                    base = candidate["base_observations"]
                    return base_records.verify_retained_observations(
                        base, request["base_request"], retained_identity=identity,
                        **native, raw_log=base_raw_log(base))
                return torch_records.verify_retained_observations(
                    candidate, request, retained_identity=identity, adapter_bytes=adapter,
                    **native, raw_log=raw_log(candidate))

            with denied_live_access():
                for endpoint in ("python", "torch"):
                    positive = verify(value, endpoint)
                    assert positive["counts"]["total_launches"] == 36, positive
                    assert positive["event_profile_pairs"] == 180, positive
                    if endpoint == "torch":
                        assert positive["operator_calls"] == 16, positive
                        assert positive["framework_result_bytes"] == 4096, positive
                    results.append({"format": fmt, "endpoint": endpoint,
                                    "case": "positive_control", "outcome": "pass",
                                    "counts": positive["counts"], "event_profile_pairs": 180})

                for label, mutate, expected in mutations():
                    candidate = copy.deepcopy(value)
                    mutate(candidate)
                    assert digest(numerical_projection(candidate)) == numerical_digest, label
                    assert digest(request) == request_digest and digest(native) == native_digest, label
                    # Each endpoint regenerates its own raw rows from the mutated
                    # parsed records, keeping both views exactly coordinated.
                    for endpoint in ("python", "torch"):
                        try:
                            verify(candidate, endpoint)
                        except ValueError as error:
                            error_text = str(error)
                            needles = (expected,) if isinstance(expected, str) else expected
                            assert any(needle in error_text for needle in needles), (label, error_text)
                            results.append({"format": fmt, "endpoint": endpoint,
                                            "case": label, "outcome": "rejected",
                                            "error": error_text})
                        else:
                            raise AssertionError("accepted inconsistent lifecycle: " + label + "/" + endpoint)

    after = source_hashes()
    assert before == after, "source changed during probe"
    output = {
        "evidence": "host-only synthetic retained-record consistency",
        "native_execution": "not_run", "retained_code_executed": False,
        "original_archive_opened": False, "acceptance_claimed": False,
        "positive_controls": sum(row["outcome"] == "pass" for row in results),
        "rejected_calls": sum(row["outcome"] == "rejected" for row in results),
        "distinct_mutations_per_format": len(list(mutations())),
        "numerical_results_unchanged": True, "sources_stable": True,
        "source_manifest_sha256": digest(before), "source_sha256": before,
        "probe_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "elapsed_seconds": round(time.monotonic() - started, 3), "results": results,
    }
    print(json.dumps(output, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
