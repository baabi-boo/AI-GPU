# SPDX-License-Identifier: Apache-2.0
"""Lightweight post-replay compatibility tests; all observations are synthetic."""

from copy import deepcopy
import hashlib
import json
import unittest

import p06_analyze as analyze


def packet_pair():
    source = {
        "checkout": {
            "revision": "1" * 40, "tree": "2" * 40,
            "pins": {"TOOLCHAIN_REV": "v3.0.2"},
            "submodules": {"entries": [{"path": "third_party/ramulator",
                                        "revision": "3" * 40, "status": "initialized"}]},
        },
        "files": [{"path": "sw/kernel/ai/matmul.cpp", "sha256": "4" * 64, "size_bytes": 17}],
    }
    packets = []
    for fmt, digit in (("fp16", "a"), ("bf16", "b")):
        packets.append({
            "documents": {
                "source": deepcopy(source),
                "tools": {
                    name: {"path": "/tools/bin/" + name, "resolved_path": "/tools/bin/" + name,
                           "sha256": value * 64, "size_bytes": size}
                    for name, value, size in (("clang", "5", 100), ("gcc", "6", 200))
                },
                "dependencies": [{"path": "third_party/ramulator/libramulator.so",
                                  "sha256": "7" * 64, "size_bytes": 300}],
                "contract": {"contract_id": "p06-native-baseline-v1", "formats": ["fp16", "bf16"],
                             "counters": [{"name": "cycles", "unit": "active_core_cycles"}]},
                "manifest": b'{"contract_id": "p06-native-baseline-v1"}\n',
            },
            "report": {
                "contract_id": "p06-native-baseline-v1", "contract_sha256": "8" * 64,
                "sampling": {"warmup_runs": 1, "measured_runs": 5,
                             "cache_policy": "fresh_device_context_not_warm_device_cache"},
                "boundaries": {"cycles": "modeled_active_core_cycles_not_model_wall_time"},
                "budget": {"jobs": 2, "run_timeout_seconds": 180, "max_rss_bytes": 4 << 30},
                "loaded_helpers": [{"path": "ci/project/p06_records.py",
                                    "sha256": "9" * 64, "size_bytes": 400}],
                "contract_limitations": ["Simulated counts are not physical throughput."],
                "variants": [{
                    "id": "simx-" + fmt, "format": fmt, "backend": "simx",
                    "qualification_id": digit * 64,
                    "artifacts_before": [{"path": "kernel.vxbin", "sha256": digit * 64,
                                          "size_bytes": 500 if fmt == "fp16" else 600}],
                    "header_macros": {"VX_CFG_NUM_THREADS": "4"},
                    "expected_expanded_header_macros": {"VX_CFG_NUM_THREADS": "4"},
                    "expected_backend_header_macros": {"VX_CFG_NUM_THREADS": "4", "PERF_ENABLE": "1"},
                }],
            },
            "replay": {
                "binding_id": digit * 64,
                "hosted_job_identity": {
                    "GITHUB_SHA": "1" * 40, "GITHUB_RUN_ID": "42", "GITHUB_RUN_ATTEMPT": "1",
                    "GITHUB_EVENT_NAME": "push", "GITHUB_REPOSITORY": "baabi-boo/AI-GPU",
                    "GITHUB_REF": "refs/heads/master", "GITHUB_JOB": "baseline",
                    "P06_BACKEND": "simx", "P06_FORMAT": fmt, "workflow_sha256": "c" * 64,
                },
            },
        })
    return packets


def replace(packet, path, value):
    for key in path[:-1]:
        packet = packet[key]
    packet[path[-1]] = value


class MatrixCompatibilityTests(unittest.TestCase):
    def reject_changes(self, changes):
        for path, value in changes:
            packets = packet_pair()
            replace(packets[1], path, value)
            with self.subTest(path=path), self.assertRaises(analyze.AnalysisError):
                analyze._compatible(packets)

    def test_distinct_format_bindings_and_binaries_remain_separate(self):
        packets = packet_pair()
        original = deepcopy(packets)
        result = analyze._compatible(packets)
        self.assertEqual(result["outcome"], "pass")
        self.assertFalse(result["format_bindings_compared_as_equal"])
        self.assertNotEqual(packets[0]["replay"]["binding_id"], packets[1]["replay"]["binding_id"])
        self.assertNotEqual(packets[0]["report"]["variants"][0]["artifacts_before"],
                            packets[1]["report"]["variants"][0]["artifacts_before"])
        self.assertEqual(packets, original)

    def test_revision_tree_pins_submodules_and_source_bodies_must_agree(self):
        root = ("documents", "source")
        self.reject_changes([
            (root + ("checkout", "revision"), "d" * 40),
            (root + ("checkout", "tree"), "d" * 40),
            (root + ("checkout", "pins", "TOOLCHAIN_REV"), "v3.0.3"),
            (root + ("checkout", "submodules", "entries", 0, "revision"), "d" * 40),
            (root + ("files", 0, "sha256"), "d" * 64),
            (root + ("files", 0, "size_bytes"), 18),
            (root + ("files", 0, "path"), "sw/kernel/ai/other.cpp"),
        ])

    def test_relocated_identical_tools_keep_the_same_compatibility_identity(self):
        packets = packet_pair()
        expected = analyze._compatible(packets)
        for name, tool in packets[1]["documents"]["tools"].items():
            tool.update(path="/relocated/tools/bin/" + name,
                        resolved_path="/relocated/actual/bin/" + name)
        before = deepcopy(packets)
        self.assertEqual(analyze._compatible(packets), expected)
        self.assertEqual(packets, before)

    def test_tool_names_hashes_and_sizes_cannot_be_normalized_away(self):
        self.reject_changes([
            (("documents", "tools", "clang", "sha256"), "d" * 64),
            (("documents", "tools", "clang", "size_bytes"), 101),
        ])
        packets = packet_pair()
        tools = packets[1]["documents"]["tools"]
        tools["clang++"] = tools.pop("clang")
        with self.assertRaises(analyze.AnalysisError):
            analyze._compatible(packets)

    def test_dependency_identity_and_counter_contract_must_match(self):
        self.reject_changes([
            (("documents", "dependencies", 0, "sha256"), "d" * 64),
            (("documents", "dependencies", 0, "size_bytes"), 301),
            (("documents", "dependencies", 0, "path"), "third_party/other/libramulator.so"),
            (("documents", "contract", "counters", 0, "unit"), "nanoseconds"),
        ])

    def test_exact_manifest_bytes_are_distinct_from_parsed_contract_identity(self):
        packets = packet_pair()
        manifest = packets[0]["documents"]["manifest"]
        result = analyze._compatible(packets)
        self.assertEqual(result["identity_sha256"]["manifest"], hashlib.sha256(manifest).hexdigest())
        reformatted = json.dumps(json.loads(manifest), separators=(",", ":")).encode()
        self.assertEqual(json.loads(reformatted), json.loads(manifest))
        packets[1]["documents"]["manifest"] = reformatted
        with self.assertRaises(analyze.AnalysisError):
            analyze._compatible(packets)

    def test_experiment_boundaries_sampling_budget_and_helpers_must_match(self):
        root = ("report",)
        self.reject_changes([
            (root + ("contract_id",), "other-contract"),
            (root + ("contract_sha256",), "d" * 64),
            (root + ("sampling", "warmup_runs"), 0),
            (root + ("sampling", "measured_runs"), 4),
            (root + ("sampling", "cache_policy"), "reused_device_context"),
            (root + ("boundaries", "cycles"), "one_kernel_only"),
            (root + ("budget", "jobs"), 1),
            (root + ("budget", "max_rss_bytes"), 2 << 30),
            (root + ("loaded_helpers", 0, "sha256"), "d" * 64),
            (root + ("contract_limitations",), []),
        ])

    def test_hardware_macro_maps_are_not_format_specific_exemptions(self):
        self.reject_changes([
            (("report", "variants", 0, name, "VX_CFG_NUM_THREADS"), "8")
            for name in ("header_macros", "expected_expanded_header_macros", "expected_backend_header_macros")
        ])

    def test_hosted_run_attempt_source_and_workflow_identity_must_agree(self):
        root = ("replay", "hosted_job_identity")
        self.reject_changes([
            (root + ("GITHUB_RUN_ID",), "43"),
            (root + ("GITHUB_RUN_ATTEMPT",), "2"),
            (root + ("GITHUB_SHA",), "d" * 40),
            (root + ("GITHUB_REPOSITORY",), "another/project"),
            (root + ("GITHUB_REF",), "refs/heads/another"),
            (root + ("GITHUB_EVENT_NAME",), "workflow_dispatch"),
            (root + ("GITHUB_JOB",), "another-job"),
            (root + ("P06_BACKEND",), "rtlsim"),
            (root + ("workflow_sha256",), "d" * 64),
        ])

    def test_hosted_provenance_cannot_be_dropped_from_only_one_format(self):
        for index in (0, 1):
            packets = packet_pair()
            packets[index]["replay"]["hosted_job_identity"] = None
            with self.subTest(format=index), self.assertRaises(analyze.AnalysisError):
                analyze._compatible(packets)
        packets = packet_pair()
        for packet in packets:
            packet["replay"]["hosted_job_identity"] = None
        self.assertEqual(analyze._compatible(packets)["outcome"], "pass")


if __name__ == "__main__":
    unittest.main()
