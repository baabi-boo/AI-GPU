# SPDX-License-Identifier: Apache-2.0
"""Independently check the frozen benchmark inputs without native execution."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest import mock

import p02_fixture_oracle
import p02_wmma_fixtures
import p04_fixture_adapter
import p04_model_contract
import p06_contract as contract


ROOT = Path(__file__).resolve().parents[2]
RAW_MANIFEST = (ROOT / contract.MANIFEST_PATH).read_bytes()
MANIFEST = json.loads(RAW_MANIFEST)


class FrozenBenchmarkInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = contract.load_contract(ROOT)
        cls.operators = {row["id"]: row for row in p02_wmma_fixtures.load_cases(ROOT)}
        cls.models = {row["id"]: row for row in p04_fixture_adapter.load_cases(ROOT)}
        cls.graph = json.loads((ROOT / p04_model_contract.MANIFEST_PATH).read_bytes())["graph"]

    def test_declared_samples_and_launches_follow_the_frozen_workload_inventory(self):
        workloads = self.document["workloads"]
        suffixes = ("single-dense_boundaries", "numerical-cross_tile_rounding_positive",
                    "multi-dense_boundaries", "seeded_dense")
        self.assertEqual([row["id"] for row in workloads],
                         [fmt + "-" + suffix for fmt in ("fp16", "bf16") for suffix in suffixes])
        warmups, measured = (self.document["sampling"][key]
                             for key in ("warmup_runs", "measured_runs"))
        self.assertEqual((warmups, measured), (1, 5))
        launches = sum(len(row["native_shapes"]) for row in workloads)
        self.assertEqual(self.document["inventory"], {
            "workloads": len(workloads), "warmup_processes": len(workloads) * warmups,
            "measured_processes": len(workloads) * measured,
            "total_processes": len(workloads) * (warmups + measured),
            "warmup_launches": launches * warmups, "measured_launches": launches * measured,
            "total_launches": launches * (warmups + measured),
        })
        self.assertEqual((len(workloads) * (warmups + measured),
                          launches * (warmups + measured)), (48, 72))
        self.assertIs(self.document["acceptance_claimed"], False)
        self.assertIs(self.document["execution_claimed"], False)

    def test_operator_accounting_follows_independently_validated_packed_fixtures(self):
        for workload in self.document["workloads"]:
            if workload["kind"] != "matmul":
                continue
            with self.subTest(workload=workload["id"]):
                case = self.operators[workload["case_id"]]
                m, n, k = (case[key] for key in ("m", "n", "k"))
                self.assertEqual(workload["native_shapes"], [[m, n, k]])
                self.assertEqual(workload["expected_launches"], 1)
                self.assertEqual(workload["format"], case["format"])
                inputs = 4 * (len(case["a_words"]) + len(case["b_words"]))
                outputs = 4 * len(case["expected"])
                accounting = workload["accounting"]
                self.assertEqual(accounting["macs"], m * n * k)
                self.assertEqual(accounting["flops"], 2 * m * n * k)
                self.assertEqual(accounting["input_h2d_bytes"], inputs)
                self.assertEqual(accounting["poison_h2d_bytes"], outputs)
                self.assertEqual(accounting["tensor_h2d_bytes"], inputs + outputs)
                self.assertEqual(accounting["tensor_d2h_bytes"], outputs)
                self.assertTrue(all(value == 0 for key, value in accounting.items()
                                    if key.startswith("host_")))

    def test_model_accounting_follows_native_graph_and_actual_host_bridge(self):
        native = [stage for stage in self.graph if stage["placement"] == "native"]
        bridge, assembly = (next(stage for stage in self.graph if stage["id"] == name)
                            for name in ("hidden_relu_cast", "assemble_logits"))
        self.assertEqual(len(native), 3)
        for workload in self.document["workloads"]:
            if workload["kind"] != "mlp":
                continue
            with self.subTest(workload=workload["id"]):
                case = self.models[workload["case_id"]]
                accounting = workload["accounting"]
                self.assertEqual(workload["native_shapes"], [stage["mnk"] for stage in native])
                self.assertEqual(workload["expected_launches"], len(native))
                macs = sum(m * n * k for m, n, k in (stage["mnk"] for stage in native))
                inputs = sum(stage["a_bytes"] + stage["b_bytes"] for stage in native)
                outputs = sum(stage["output_bytes"] for stage in native)
                self.assertEqual(inputs, 4 * (len(case["input_words"]) + len(case["w1_words"])
                                              + len(case["bridge_words"]) + 2 * len(case["w2_words"])))
                self.assertEqual(outputs, 4 * (len(case["hidden_words"]) + len(case["output_words"])))
                self.assertEqual(accounting["macs"], macs)
                self.assertEqual(accounting["flops"], 2 * macs)
                self.assertEqual(accounting["input_h2d_bytes"], inputs)
                self.assertEqual(accounting["poison_h2d_bytes"], outputs)
                self.assertEqual(accounting["tensor_h2d_bytes"], inputs + outputs)
                self.assertEqual(accounting["tensor_d2h_bytes"], outputs)
                self.assertEqual(accounting["host_relu_elements"], bridge["elements"])
                self.assertEqual(accounting["host_cast_elements"], bridge["elements"])
                self.assertEqual(accounting["host_bridge_input_bytes"], bridge["input_bytes"])
                self.assertEqual(accounting["host_bridge_output_bytes"], bridge["output_bytes"])
                self.assertEqual(accounting["host_assembly_bytes"], sum(assembly["copy_bytes"]))

    def test_argument_payload_is_bound_to_the_existing_native_abi(self):
        header = (ROOT / "sw/common/ai_matmul_args.h").read_text()
        sizes = re.findall(r"constexpr uint32_t kArgumentBytes = ([0-9]+);", header)
        self.assertEqual(len(sizes), 1)
        for workload in self.document["workloads"]:
            self.assertEqual(workload["accounting"]["argument_payload_bytes"],
                             int(sizes[0]) * workload["expected_launches"])

    def test_source_and_fixture_pins_match_original_bytes(self):
        sources = self.document["source_inputs"]
        paths = [row["path"] for row in sources]
        self.assertEqual(paths, sorted(set(paths)))
        digests = {}
        for row in sources:
            with self.subTest(path=row["path"]):
                digests[row["path"]] = hashlib.sha256((ROOT / row["path"]).read_bytes()).hexdigest()
                self.assertEqual(row["sha256"], digests[row["path"]])
        self.assertEqual(self.document["profile"]["sha256"], digests["profiles/p02-tfr.json"])
        for workload in self.document["workloads"]:
            self.assertEqual(workload["fixture_sha256"], digests[workload["fixture"]])

    def test_counter_ids_match_canonical_toml_and_shared_scopes_use_one_query(self):
        types = tomllib.loads((ROOT / "VX_types.toml").read_text())
        symbols = {key: value for section in types.values() if type(section) is dict
                   for key, value in section.items()}
        rows = self.document["counters"]
        self.assertEqual(len(rows), 45)
        self.assertEqual(len({row["name"] for row in rows}), len(rows))
        self.assertEqual(len({(row["mpm_class"], row["csr"], row["core_id"]) for row in rows}), len(rows))
        scopes = {"BASE": "core", "CORE": "core", "ICACHE": "socket", "DCACHE": "socket",
                  "L2CACHE": "cluster", "L3CACHE": "global", "TCU": "core"}
        for row in rows:
            with self.subTest(counter=row["name"]):
                self.assertEqual(row["mpm_class"], symbols[row["class_macro"]])
                self.assertEqual(row["csr"], symbols[row["csr_macro"]])
                self.assertEqual(row["core_id"], 0)
                kind = row["class_macro"].removeprefix("VX_DCR_MPM_CLASS_")
                scope = scopes.get(kind, "global" if row["name"].startswith("memory_") else "core")
                self.assertEqual(row["scope"], scope)
        caps = self.document["capability_values"]
        self.assertEqual((caps["num_cores"], caps["num_clusters"], caps["socket_size"]), (1, 1, 1))

    def test_launch_reset_cache_arbitration_metrics_cannot_be_whole_context_totals(self):
        names = {row["name"] for row in self.document["counters"]}
        self.assertTrue({"dcache_bank_st", "l2cache_bank_st", "l3cache_bank_st"}.isdisjoint(names))
        self.assertTrue({"lmem_bank_st", "memory_bank_st", "dcache_mshr_st"} <= names)
        source = (ROOT / "sim/simx/mem/cache.cpp").read_text()
        arbiter = source[source.index("class CachePortArb"):]
        reset = arbiter[arbiter.index("void on_reset()"):arbiter.index("void on_tick()")]
        self.assertIn("collisions_ = 0;", reset)
        self.assertIn("perf_stats.bank_stalls = port_arb_->collisions();", source)
        self.assertTrue(any("reset on each launch" in line for line in self.document["limitations"]))

    def test_capabilities_and_availability_follow_public_api_symbols(self):
        header = (ROOT / "sw/runtime/include/vortex2.h").read_text()
        ids = {name: int(value, 16) for name, value in
               re.findall(r"^#define (VX_CAPS_[A-Z_]+)\s+(0x[0-9A-Fa-f]+)\b", header, re.MULTILINE)}
        symbols = {name: 1 << (32 + int(bit)) for name, bit in
                   re.findall(r"^#define (VX_ISA_EXT_[A-Z0-9_]+)\s+\(1ull << \(32 \+ ([0-9]+)\)\)",
                              header, re.MULTILINE)}
        names = {"cache_line_bytes": "CACHE_LINE_SIZE", "local_mem_bytes": "LOCAL_MEM_SIZE",
                 "global_mem_bytes": "GLOBAL_MEM_SIZE", "mem_bank_bytes": "MEM_BANK_SIZE"}
        self.assertEqual(len(self.document["capabilities"]), 13)
        for row in self.document["capabilities"]:
            api_name = "VX_CAPS_" + names.get(row["name"], row["name"].upper())
            self.assertEqual(row["id"], ids[api_name])
        unavailable = []
        for row in self.document["counters"]:
            group = row["name"].split("_", 1)[0].upper()
            expected = symbols.get("VX_ISA_EXT_" + group, 0)
            self.assertEqual(row["required_isa"], expected)
            if expected and self.document["capability_values"]["isa_flags"] & expected != expected:
                unavailable.append(row["name"])
        self.assertEqual(len(unavailable), 12)
        self.assertTrue(all(name.startswith(("l2cache_", "l3cache_")) for name in unavailable))
        self.assertNotIn(ids["VX_CAPS_CLOCK_RATE"], [row["id"] for row in self.document["capabilities"]])

    def test_loader_uses_original_fixture_validators_on_the_requested_source(self):
        with mock.patch.object(p02_wmma_fixtures, "load_cases", wraps=p02_wmma_fixtures.load_cases) as operators, \
                mock.patch.object(p04_fixture_adapter, "load_cases", wraps=p04_fixture_adapter.load_cases) as models:
            document = deepcopy(self.document)
            self.assertIs(contract.validate_contract(document, ROOT), document)
        operators.assert_called_once_with(ROOT)
        models.assert_called_once_with(ROOT)
        self.assertEqual(document, self.document)


class BenchmarkManifestRejectionTests(unittest.TestCase):
    def reject(self, mutate):
        document = deepcopy(MANIFEST)
        mutate(document)
        before = deepcopy(document)
        with self.assertRaises(contract.ContractError):
            contract.validate_contract(document, ROOT)
        self.assertEqual(document, before, "rejection must not repair a changed manifest")

    def test_scalar_types_cannot_substitute_booleans_floats_or_null(self):
        for path, replacement in ((["schema_version"], True), (["contract_version"], 1.0),
                                  (["acceptance_claimed"], 0), (["formats"], ("fp16", "bf16")),
                                  (["sampling", "warmup_runs"], True),
                                  (["capability_values", "vm_support"], False),
                                  (["geometry", "l2_enabled"], 0),
                                  (["budget", "max_rss_bytes"], None)):
            def mutate(doc, path=path, replacement=replacement):
                for key in path[:-1]:
                    doc = doc[key]
                doc[path[-1]] = replacement
            with self.subTest(path=path, replacement=replacement):
                self.reject(mutate)

    def test_missing_unknown_and_reordered_inventory_is_rejected(self):
        mutations = [lambda doc: doc.pop("boundaries"), lambda doc: doc.update(extra=True),
                     lambda doc: doc["workloads"].pop(), lambda doc: doc["workloads"].reverse(),
                     lambda doc: doc["workloads"].__setitem__(1, deepcopy(doc["workloads"][0])),
                     lambda doc: doc["counters"].pop(), lambda doc: doc["counters"].reverse(),
                     lambda doc: doc["capabilities"].append(deepcopy(doc["capabilities"][0])),
                     lambda doc: doc["source_inputs"].reverse(),
                     lambda doc: doc["workloads"][0]["accounting"].update(extra=0)]
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index):
                self.reject(mutate)

    def test_sample_policy_measurement_boundaries_and_gates_cannot_drift(self):
        mutations = [lambda doc: doc["sampling"].update(warmup_runs=0),
                     lambda doc: doc["sampling"].update(measured_runs=4),
                     lambda doc: doc["sampling"].update(iterations_per_process=2),
                     lambda doc: doc["sampling"].update(outlier_policy="discard_slowest"),
                     lambda doc: doc["sampling"].update(failed_sample_policy="retry"),
                     lambda doc: doc["sampling"].update(cache_policy="warm"),
                     lambda doc: doc["boundaries"].update(cycles="physical_device_latency"),
                     lambda doc: doc["budget"].update(min_free_bytes=1024),
                     lambda doc: doc["budget"].update(jobs_max=3),
                     lambda doc: doc.update(acceptance_claimed=True),
                     lambda doc: doc.update(execution_claimed=True),
                     lambda doc: doc["profile"].update(simulation_mode="functional"),
                     lambda doc: doc["profile"]["forbidden_macros"].remove("SIMX_FUNCTIONAL")]
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index):
                self.reject(mutate)

    def test_workload_shapes_counts_and_observer_metadata_are_frozen(self):
        mutations = [lambda doc: doc["workloads"][0].update(m=16),
                     lambda doc: doc["workloads"][0]["native_shapes"][0].__setitem__(2, 16),
                     lambda doc: doc["workloads"][0].update(kind="mlp"),
                     lambda doc: doc["workloads"][0].update(case_id="fp16-zero"),
                     lambda doc: doc["workloads"][0]["accounting"].update(flops=256),
                     lambda doc: doc["workloads"][3]["accounting"].update(poison_h2d_bytes=0),
                     lambda doc: doc["inventory"].update(total_launches=48),
                     lambda doc: doc["counters"][0].update(csr=2818),
                     lambda doc: doc["counters"][13].update(scope="core"),
                     lambda doc: doc["counters"][23].update(required_isa=0),
                     lambda doc: doc["capabilities"][0].update(id=1),
                     lambda doc: doc["observation"].update(disabled_counter_policy="zero"),
                     lambda doc: doc["observation"]["marker_order"]["mlp"].reverse()]
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index):
                self.reject(mutate)

    def test_selection_is_canonical_independent_and_does_not_mutate(self):
        before = deepcopy(MANIFEST)
        self.assertEqual(contract.select_workloads(MANIFEST), MANIFEST["workloads"])
        self.assertEqual(contract.select_workloads(MANIFEST, ["bf16", "fp16"]), MANIFEST["workloads"])
        for fmt in ("fp16", "bf16"):
            selected = contract.select_workloads(MANIFEST, (fmt,))
            self.assertEqual([row["id"] for row in selected],
                             [row["id"] for row in MANIFEST["workloads"] if row["format"] == fmt])
            selected[0]["native_shapes"][0][0] = 100
            selected[0]["accounting"]["macs"] = 0
        self.assertEqual(MANIFEST, before)

    def test_selection_rejects_ambiguous_or_unsupported_inputs(self):
        for selection in ([], (), "fp16", {"fp16"}, {"format": "fp16"}, ["fp16", "fp16"],
                          ["fp16", "fp32"], ["FP16"], [False], [1], [None]):
            with self.subTest(selection=selection), self.assertRaises(contract.ContractError):
                contract.select_workloads(MANIFEST, selection)
        changed = deepcopy(MANIFEST)
        changed["workloads"].pop()
        with self.assertRaises(contract.ContractError):
            contract.select_workloads(changed, ["fp16"])


class BenchmarkJsonBoundaryTests(unittest.TestCase):
    def test_exact_manifest_round_trip_and_uint64_boundary(self):
        self.assertEqual(contract.decode_contract(RAW_MANIFEST), MANIFEST)
        self.assertEqual(contract.decode_contract(b'{"value":18446744073709551615}'),
                         {"value": (1 << 64) - 1})

    def test_duplicate_keys_malformed_encodings_and_nonobjects_are_rejected(self):
        for raw in (b'{"schema_version":1,"schema_version":1}',
                    b'{"nested":{"value":1,"value":1}}', b'{"x":1,}', b'{}{}', b'{',
                    b'\xff', b'\xef\xbb\xbf{}', b'[]', b'null', b'true', b'"object"', b''):
            with self.subTest(raw=raw), self.assertRaises(contract.ContractError):
                contract.decode_contract(raw)

    def test_floating_nonfinite_negative_and_oversized_numbers_are_rejected(self):
        for number in ("1.0", "1e0", "NaN", "Infinity", "-Infinity", "-1",
                       "18446744073709551616", "1" * 21):
            with self.subTest(number=number), self.assertRaises(contract.ContractError):
                contract.decode_contract(('{"value":' + number + '}').encode())

    def test_byte_and_nesting_limits_apply_without_counting_quoted_braces(self):
        exact = b'{}' + b' ' * (contract.MAX_MANIFEST_BYTES - 2)
        self.assertEqual(contract.decode_contract(exact), {})
        with self.assertRaises(contract.ContractError):
            contract.decode_contract(exact + b' ')
        for raw in ("{}", bytearray(b'{}'), memoryview(b'{}'), None):
            with self.subTest(type=type(raw)), self.assertRaises(contract.ContractError):
                contract.decode_contract(raw)
        nested = b'{"x":' + b'[' * (contract.MAX_JSON_DEPTH - 1) + b'0' \
            + b']' * (contract.MAX_JSON_DEPTH - 1) + b'}'
        contract.decode_contract(nested)
        with self.assertRaises(contract.ContractError):
            contract.decode_contract(b'{"x":[' + nested + b']}')
        value = '{[\\"' * 100
        self.assertEqual(contract.decode_contract(json.dumps({"text": value}).encode()), {"text": value})


class BenchmarkSourceIntegrityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="p06-contract-")
        self.addCleanup(temporary.cleanup)
        self.temporary = Path(temporary.name)
        self.source = self.temporary / "source"
        paths = {row["path"] for row in MANIFEST["source_inputs"]}
        paths.update(p04_model_contract.ARTIFACT_PATHS)
        paths.add(p02_fixture_oracle.JSON_PATH.as_posix())
        paths.add(contract.MANIFEST_PATH)
        for name in sorted(paths):
            target = self.source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, target)

    def snapshot(self):
        return {path.relative_to(self.source).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
                for path in self.source.rglob("*") if path.is_file()}

    def test_copied_source_load_is_read_only_and_selection_is_detached(self):
        before = self.snapshot()
        document = contract.load_contract(self.source)
        self.assertEqual(document, MANIFEST)
        contract.select_workloads(document, ["bf16"])[0]["accounting"]["macs"] = 0
        self.assertEqual(document, MANIFEST)
        self.assertEqual(self.snapshot(), before)

    def test_each_frozen_input_rejects_changed_bytes(self):
        for row in MANIFEST["source_inputs"]:
            path = self.source / row["path"]
            original = path.read_bytes()
            with self.subTest(path=row["path"]):
                try:
                    path.write_bytes(original + b'\n')
                    with self.assertRaisesRegex(contract.ContractError, "frozen source input differs"):
                        contract.load_contract(self.source)
                    self.assertEqual(path.read_bytes(), original + b'\n')
                finally:
                    path.write_bytes(original)

    def test_rehashing_changed_fixture_or_profile_does_not_bless_a_new_baseline(self):
        for relative in ("ci/project/fixtures/p02_layout_v1.json",
                         "ci/project/fixtures/p02_wmma_numerical_v1.json",
                         "ci/project/fixtures/p04_tiny_mlp_v1.json", "profiles/p02-tfr.json"):
            document = deepcopy(MANIFEST)
            path = self.source / relative
            original = path.read_bytes()
            with self.subTest(path=relative):
                try:
                    path.write_bytes(original + b'\n')
                    changed = hashlib.sha256(path.read_bytes()).hexdigest()
                    for row in document["source_inputs"]:
                        if row["path"] == relative:
                            row["sha256"] = changed
                    for row in document["workloads"]:
                        if row["fixture"] == relative:
                            row["fixture_sha256"] = changed
                    if document["profile"]["path"] == relative:
                        document["profile"]["sha256"] = changed
                    with self.assertRaisesRegex(contract.ContractError, "frozen contract"):
                        contract.validate_contract(document, self.source)
                finally:
                    path.write_bytes(original)

    def test_transitive_leaf_fixture_still_requires_its_independent_producer(self):
        path = self.source / p02_fixture_oracle.JSON_PATH
        path.write_bytes(path.read_bytes() + b'\n')
        before = self.snapshot()
        with self.assertRaisesRegex(p02_wmma_fixtures.FixtureError, "frozen leaf fixture"):
            contract.load_contract(self.source)
        self.assertEqual(self.snapshot(), before)

    def test_missing_nonregular_and_oversized_inputs_fail_without_blocking(self):
        path = self.source / "VX_config.toml"
        original = path.read_bytes()
        for kind in ("missing", "directory", "fifo", "oversized"):
            with self.subTest(kind=kind):
                path.unlink()
                if kind == "directory":
                    path.mkdir()
                elif kind == "fifo":
                    os.mkfifo(path)
                elif kind == "oversized":
                    with path.open("wb") as stream:
                        stream.truncate(contract.MAX_SOURCE_BYTES + 1)
                if kind == "fifo":
                    result = subprocess.run(
                        [sys.executable, str(ROOT / "ci/project/p06_contract.py"),
                         "--source-dir", str(self.source)], cwd=ROOT,
                        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), text=True,
                        capture_output=True, timeout=15)
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertIn("bounded regular file", json.loads(result.stdout)["reason"])
                else:
                    with self.assertRaises(contract.ContractError):
                        contract.load_contract(self.source)
                if path.is_dir():
                    path.rmdir()
                elif path.exists():
                    path.unlink()
                path.write_bytes(original)

    def test_symlinked_file_parent_and_source_root_are_rejected(self):
        path = self.source / "VX_config.toml"
        original = path.read_bytes()
        path.unlink()
        path.symlink_to(ROOT / "VX_config.toml")
        with self.assertRaisesRegex(contract.ContractError, "symlink"):
            contract.load_contract(self.source)
        path.unlink()
        path.write_bytes(original)
        linked = self.temporary / "linked-source"
        linked.symlink_to(self.source, target_is_directory=True)
        with self.assertRaisesRegex(contract.ContractError, "symlink"):
            contract.load_contract(linked)
        real_profiles = self.temporary / "profiles"
        (self.source / "profiles").rename(real_profiles)
        (self.source / "profiles").symlink_to(real_profiles, target_is_directory=True)
        with self.assertRaisesRegex(contract.ContractError, "symlink"):
            contract.load_contract(self.source)

    def test_missing_root_and_oversized_manifest_are_rejected(self):
        with self.assertRaisesRegex(contract.ContractError, "existing directory"):
            contract.validate_contract(deepcopy(MANIFEST), self.temporary / "absent")
        path = self.source / contract.MANIFEST_PATH
        path.write_bytes(b' ' * (contract.MAX_MANIFEST_BYTES + 1))
        with self.assertRaisesRegex(contract.ContractError, "bounded regular file"):
            contract.load_contract(self.source)

    def test_original_fixture_inventory_or_geometry_cannot_be_substituted(self):
        operators = p02_wmma_fixtures.load_cases(self.source)
        selected = next(index for index, row in enumerate(operators)
                        if row["id"] == MANIFEST["workloads"][0]["case_id"])
        for mutation in (lambda rows: rows.pop(),
                         lambda rows: rows.__setitem__(1, deepcopy(rows[0])),
                         lambda rows: rows[selected].update(m=16),
                         lambda rows: rows[selected].update(format="bf16"),
                         lambda rows: rows[selected]["a_words"].pop()):
            changed = deepcopy(operators)
            mutation(changed)
            with self.subTest(case=changed[selected]["id"]), \
                    mock.patch.object(p02_wmma_fixtures, "load_cases", return_value=changed), \
                    self.assertRaises(contract.ContractError):
                contract.validate_contract(deepcopy(MANIFEST), self.source)
        models = p04_fixture_adapter.load_cases(self.source)
        selected = next(index for index, row in enumerate(models) if row["id"] == "fp16-seeded_dense")
        models[selected]["bridge_words"].pop()
        with mock.patch.object(p04_fixture_adapter, "load_cases", return_value=models), \
                self.assertRaisesRegex(contract.ContractError, "model fixture dimensions"):
            contract.validate_contract(deepcopy(MANIFEST), self.source)

    def test_cli_reports_source_only_success_and_retains_corrupt_input(self):
        command = [sys.executable, str(ROOT / "ci/project/p06_contract.py"),
                   "--source-dir", str(self.source)]
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        before = self.snapshot()
        result = subprocess.run(command, cwd=ROOT, env=environment, text=True,
                                capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout), {"outcome": "pass",
                         "contract_id": "p06-native-baseline-v1", "workloads": 8,
                         "counters": 45, "native_execution": "not_run"})
        self.assertEqual(self.snapshot(), before)
        path = self.source / "profiles/p02-tfr.json"
        path.write_bytes(path.read_bytes() + b'\n')
        before = self.snapshot()
        result = subprocess.run(command, cwd=ROOT, env=environment, text=True,
                                capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["native_execution"], "not_run")
        self.assertEqual(json.loads(result.stdout)["outcome"], "fail")
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
