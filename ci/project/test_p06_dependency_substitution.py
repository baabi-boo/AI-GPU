# SPDX-License-Identifier: Apache-2.0
"""Actual tiny-library and synthetic native controls for dependency substitution."""

import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import p06_dependency_build as builder
import p06_dependency_contract as dependency
import p06_dependency_record as recorder
import p06_dependency_substitution as control
import p06_managed_preflight_contract as manifest
import p06_native_lifetime_test_fixture as fixture


ROOT = Path(__file__).resolve().parents[2]
REVISION = "a" * 40
PIN = "b" * 64


class SubstitutionObservationTests(unittest.TestCase):
    def data(self):
        case, operations, summary, witness, lifetime = fixture.raw_records("fp16", control.POLICY)
        alternate = "/separate-control/work/" + control.LIBRARY
        for row in witness["loaded_libraries"]:
            if row["name"] == control.LIBRARY:
                row["path"] = alternate
        return case, operations, summary, witness, lifetime, alternate

    def verify(self, values):
        case, operations, summary, witness, lifetime, alternate = values
        return control.verify_observation(fixture.render_log(operations, summary, witness, lifetime),
            contract=manifest.load_contract(), case=case, binding_id=fixture.BINDING,
            original_libraries=fixture.EXPECTED_LIBRARIES, alternate_path=alternate)

    def test_same_favorable_transcript_passes_numeric_and_rejects_original_dependency(self):
        result = self.verify(self.data())
        self.assertEqual(result["rejection"], control.REJECTION)
        self.assertEqual((result["control_counts"]["processes"], result["control_counts"]["launches"],
                          result["control_counts"]["checked_words"]), (1, 33, 1056))
        self.assertEqual(result["expected_libraries"][control.LIBRARY], "/separate-control/work/" + control.LIBRARY)
        for flag in dependency.FALSE_CLAIMS:
            self.assertIs(result["observation"]["witness"][flag], False)
            self.assertIs(result["observation"]["lifetime"][flag], False)

    def test_wrong_numerics_cannot_establish_provenance_sensitivity(self):
        data = self.data()
        data[1][0]["actual_bits"][0] = "00000000"
        with self.assertRaises(ValueError):
            self.verify(data)

    def test_alternate_model_or_missing_lifetime_cannot_replace_dependency_control(self):
        data = self.data()
        for row in data[3]["loaded_libraries"]:
            if row["name"] == "libsimx.so":
                row["path"] = "/other/libsimx.so"
        with self.assertRaisesRegex(ValueError, "libsimx"):
            self.verify(data)
        data = self.data()
        text = fixture.render_log(*data[1:5]).rsplit("\n", 2)[0] + "\n"
        with self.assertRaisesRegex(ValueError, "lifetime"):
            control.verify_observation(text, contract=manifest.load_contract(), case=data[0],
                binding_id=fixture.BINDING, original_libraries=fixture.EXPECTED_LIBRARIES,
                alternate_path=data[5])

    def test_unmodified_loader_path_and_wrong_rejection_reason_fail(self):
        data = self.data()
        with self.assertRaisesRegex(ValueError, "alternate path"):
            control.verify_observation(fixture.render_log(*data[1:5]), contract=manifest.load_contract(),
                case=data[0], binding_id=fixture.BINDING, original_libraries=fixture.EXPECTED_LIBRARIES,
                alternate_path=fixture.EXPECTED_LIBRARIES[control.LIBRARY])
        actual = control.lifetime_records.verify_output
        count = 0

        def wrong_reason(*args, **kwargs):
            nonlocal count
            count += 1
            if count == 2:
                raise ValueError("unrelated malformed observation")
            return actual(*args, **kwargs)

        with mock.patch.object(control.lifetime_records, "verify_output", side_effect=wrong_reason):
            with self.assertRaisesRegex(ValueError, "different provenance reason"):
                self.verify(self.data())


class ActualSubstitutionBuildTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="p06-substitution-tiny-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.output = self.root / "control"
        self.work = self.output / "work"
        self.managed_work = self.root / "managed-work"
        self.managed_work.mkdir()
        self.ramulator = self.source / "third_party/ramulator"
        for path in (self.ramulator / "src/dram/impl", self.ramulator / "ext/spdlog/include",
                     self.ramulator / "ext/yaml-cpp/include", self.work / "home", self.work / "tmp",
                     self.output / "records", self.output / "payloads", self.output / "inputs"):
            path.mkdir(parents=True)
        self.tools = {name: recorder.file_identity(shutil.which(name))
                      for name in (*recorder.TOOLS, "python3")}
        self.environment = builder.clean_environment(self.work)
        ramulator_source = self.ramulator / "tiny.cpp"
        ramulator_source.write_text('extern "C" int ramulator_value() { return 41; }\n')
        self.call([self.tools["g++"]["path"], "-shared", "-fPIC", str(ramulator_source),
                   "-o", str(self.ramulator / "libramulator.so")])
        self.gddr6 = self.ramulator / "src/dram/impl/GDDR6.cpp"
        self.gddr6.write_text('extern "C" int ramulator_value();\n'
            'extern "C" int control_value() { return ramulator_value() + 1; }\n')
        self.original = self.root / "original" / control.LIBRARY
        self.original.parent.mkdir()
        self.call([self.tools["g++"]["path"], "-shared", "-fPIC", "-std=c++20", "-O3", "-DNDEBUG",
                   str(self.gddr6), "-L" + str(self.ramulator), "-lramulator", "-o", str(self.original)])
        self.config = {"schema_version": 1, "contract_id": recorder.CONTRACT_ID,
            "contract_sha256": dependency.contract_hash(), "roots": {
                "sources": str(self.source / "third_party"), "build": str(self.work),
                "receipts": str(self.output / "records"), "payloads": str(self.output / "payloads")},
            "tools": {name: self.tools[name] for name in recorder.TOOLS}}
        self.config_path = self.output / "tool-config.json"
        self.pin = builder.write_json(self.config_path, self.config)["sha256"]
        products = {}
        for name, path in (("ramulator", self.ramulator / "libramulator.so"), ("extension", self.original)):
            identity = builder.identity(path)
            products[name] = dict(identity, staged_path=identity["path"])
        self.admission = SimpleNamespace(source_inputs=[builder.identity(self.gddr6)],
            products=products, document={"external_archives": [],
                                        "paths": {"workspace": str(self.root / "dependency-workspace")}})
        self.derivation = control.prepare_source(self.source, self.output, self.work, self.admission)

    def call(self, words, *, environment=None):
        result = subprocess.run(words, cwd=self.work, env=environment or self.environment,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60, text=True)
        self.assertEqual(result.returncode, 0, result.stdout)
        return result.stdout

    def build_control(self):
        for role, arguments in control.recipes(self.source, self.work).items():
            self.call([*builder.launcher(self.config_path, self.pin, self.tools, "g++", role), *arguments])

    def verify(self):
        actual = control.base._file_identity

        def identity(path):
            if Path(path) == self.source / "ci/project/p06_dependency_record.py":
                return actual(ROOT / "ci/project/p06_dependency_record.py")
            return actual(path)

        with mock.patch.object(control.base, "_file_identity", side_effect=identity):
            return control.verify_records(self.output, self.config, self.pin, source=self.source,
                work=self.work, managed_work=self.managed_work, admission=self.admission, tools=self.tools)

    def test_rehashed_extra_project_loads_cannot_pass_the_control(self):
        self.build_control()
        verified = self.verify()
        linked = copy.deepcopy(verified["link"])
        path = self.output / "records" / (linked["id"] + ".json")
        mapping = linked["link_map"]
        original = (self.output / "payloads" / mapping["payload"]).read_bytes()
        for extra in (self.source / "extra.so", self.work / "extra.a",
                      self.managed_work / "simx-fp16/extra.o",
                      self.managed_work / "simx-bf16/extra.so"):
            body = original + ("\nLOAD " + str(extra) + "\n").encode()
            digest = hashlib.sha256(body).hexdigest()
            (self.output / "payloads" / (digest + ".bin")).write_bytes(body)
            linked["link_map"] = dict(mapping, sha256=digest, size_bytes=len(body), payload=digest + ".bin")
            path.write_text(json.dumps(linked, sort_keys=True) + "\n")
            with self.subTest(extra=extra), self.assertRaisesRegex(ValueError, "unplanned source/work input"):
                self.verify()

    def test_rehashed_unreviewed_project_headers_cannot_pass_the_control(self):
        self.build_control()
        verified = self.verify()
        original = verified["compile"]
        record_path = self.output / "records" / (original["id"] + ".json")
        for name, resolved in ((self.source / "extra.h", self.source / "extra.h"),
                (self.managed_work / "simx-bf16/extra.h", self.managed_work / "simx-bf16/extra.h"),
                (Path("/usr/include/p06-review-extra.h"), self.source / "extra.h"),
                (Path("/usr/include/p06-review-extra.h"), self.work / "extra.h")):
            compiled = copy.deepcopy(original)
            body = b"unreviewed project header\n"
            digest = hashlib.sha256(body).hexdigest()
            (self.output / "payloads" / (digest + ".bin")).write_bytes(body)
            inputs = sorted([*compiled["inputs_before"], {
                "path": str(name), "resolved_path": str(resolved), "sha256": digest,
                "size_bytes": len(body), "payload": digest + ".bin"}], key=lambda row: row["path"])
            compiled["inputs_before"] = inputs
            compiled["inputs_after"] = copy.deepcopy(inputs)
            body = (compiled["output_path"] + ": " + " ".join(row["path"] for row in inputs) + "\n").encode()
            digest = hashlib.sha256(body).hexdigest()
            (self.output / "payloads" / (digest + ".bin")).write_bytes(body)
            for key in ("dependency_file", "dependency_prepass_file"):
                compiled[key] = dict(compiled[key], sha256=digest, size_bytes=len(body), payload=digest + ".bin")
            record_path.write_text(json.dumps(compiled, sort_keys=True) + "\n")
            with self.subTest(name=name, resolved=resolved), self.assertRaisesRegex(
                    ValueError, "unreviewed project file"):
                self.verify()

    def test_actual_fresh_marker_library_preserves_tiny_numerics_and_is_byte_different(self):
        before = builder.identity(self.original)
        self.build_control()
        result = self.verify()
        self.assertNotEqual(result["alternate_product"]["sha256"], before["sha256"])
        self.assertEqual(builder.identity(self.original), before)
        self.assertIn(control.MARKER, (self.work / control.LIBRARY).read_bytes())
        for path in (self.original, self.work / control.LIBRARY):
            script = "import ctypes,sys; print(ctypes.CDLL(sys.argv[1]).control_value())"
            self.assertEqual(self.call([sys.executable, "-c", script, str(path)],
                environment=dict(self.environment, LD_LIBRARY_PATH=str(self.ramulator))).strip(), "42")
        self.assertEqual([row["stage"] for row in result["compile"]["children"]], ["dependencies", "tool"])
        self.assertEqual(len(result["records"]), 2)
        self.assertEqual(result["source_derivation"], self.derivation)

    def test_fresh_compilation_of_an_unreviewed_derived_source_is_rejected(self):
        path = self.work / control.CONTROL_SOURCE
        path.write_bytes(b"// unexpected extra source bytes\n" + path.read_bytes())
        self.build_control()
        with self.assertRaisesRegex(ValueError, "exact pinned source plus emitted declaration"):
            self.verify()

    def test_changed_source_marker_or_original_product_cannot_pass_the_join(self):
        self.build_control()
        original_source = copy.deepcopy(self.admission.source_inputs)
        self.admission.source_inputs[0]["sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "pinned dependency input"):
            self.verify()
        self.admission.source_inputs = original_source
        original_product = self.admission.products["extension"]["sha256"]
        self.admission.products["extension"]["sha256"] = builder.identity(self.work / control.LIBRARY)["sha256"]
        with self.assertRaisesRegex(ValueError, "known different"):
            self.verify()
        self.admission.products["extension"]["sha256"] = original_product
        (self.work / control.LIBRARY).write_bytes(b"substituted after successful link")
        with self.assertRaisesRegex(ValueError, "changed after"):
            self.verify()


class SyntheticControlHarness:
    """Fake commands, real files and exact synthetic lifetime transcript checks."""

    def __enter__(self):
        import contextlib
        self.context = contextlib.ExitStack()
        temporary = self.context.enter_context(tempfile.TemporaryDirectory(prefix="p06-substitution-runner-"))
        self.root = Path(temporary)
        self.source, self.build = self.root / "source", self.root / "build"
        self.source.mkdir()
        self.build.mkdir()
        self.managed = self.root / "managed.json"
        self.receipt = self.root / "dependency.json"
        self.managed.write_text("{}")
        self.receipt.write_text("{}")
        self.args = SimpleNamespace(source_dir=self.source, build_dir=self.build,
            managed_report=self.managed, dependency_receipt=self.receipt, output_dir=self.root / "control",
            expected_revision=REVISION, dependency_receipt_sha256=PIN)
        self.context.enter_context(mock.patch.object(control, "ROOT", self.source))
        self.control = control.Control(self.args)
        self.state = {"source_identity": 1}
        self.calls = []
        self.failure = None
        self.drift = False
        self.tools = {name: {"path": "/tools/" + name} for name in (*recorder.TOOLS, "python3")}
        original = self.source / control.ORIGINAL_SOURCE
        original.parent.mkdir(parents=True)
        original.write_bytes(b"// synthetic admitted GDDR6 source\n")
        self.control.admission = SimpleNamespace(document={"tools": self.tools},
            source_inputs=[builder.identity(original)])
        self.control.original_libraries = dict(fixture.EXPECTED_LIBRARIES)
        self.control.initial = dict(self.state)
        self.control.report["managed_build_binding_sha256"] = "c" * 64
        self.context.enter_context(mock.patch.object(self.control, "admit", return_value={}))
        self.context.enter_context(mock.patch.object(self.control, "snapshot", side_effect=lambda: dict(self.state)))
        self.context.enter_context(mock.patch.object(control, "verify_records", side_effect=self.verified))
        self.executor = self.context.enter_context(mock.patch.object(control, "run_bounded", side_effect=self.command))
        actual_contract = manifest.load_contract()
        case = manifest.select_cases(actual_contract)[0]
        self.context.enter_context(mock.patch.object(control.manifest, "load_contract", return_value=actual_contract))
        self.context.enter_context(mock.patch.object(control.manifest, "select_cases", return_value=[case]))
        return self

    def __exit__(self, *arguments):
        return self.context.__exit__(*arguments)

    def verified(self, *args, **kwargs):
        return {"records": [{"path": "records/compile.json"}, {"path": "records/link.json"}],
            "alternate_product": builder.identity(self.control.work / control.LIBRARY),
            "source_derivation": copy.deepcopy(self.control.report["source_derivation"]),
            "original_product": {"path": "/original/" + control.LIBRARY, "sha256": "0" * 64}}

    def command(self, argv, cwd, environment, log_path, **limits):
        name = Path(log_path).stem
        self.calls.append({"name": name, "argv": argv, "environment": environment, **limits})
        body = "synthetic command output\n"
        if name == "compile-alternate-extension":
            for filename in ("gddr6-control.o", "gddr6-control.o.d", "gddr6-control.o.p06-before.d"):
                (self.control.work / filename).write_bytes(b"synthetic control output")
            (self.control.output / "records/compile.json").write_text("{}")
        elif name == "link-alternate-extension":
            (self.control.work / control.LIBRARY).write_bytes(control.MARKER)
            (self.control.work / "control.map").write_text("synthetic map")
            (self.control.output / "records/link.json").write_text("{}")
        else:
            binding_id = argv[argv.index("--qualification-id") + 1]
            _, operations, summary, witness, lifetime = fixture.raw_records("fp16", control.POLICY,
                                                                           binding_id=binding_id)
            for row in witness["loaded_libraries"]:
                if row["name"] == control.LIBRARY:
                    row["path"] = str(self.control.work / control.LIBRARY)
            body = fixture.render_log(operations, summary, witness, lifetime)
        raw = body.encode()
        Path(log_path).write_bytes(raw)
        failed = self.failure == name
        if failed and self.drift:
            self.state["source_identity"] = 2
        return {"outcome": "fail" if failed else "pass", "reason": "synthetic_failure" if failed else None,
            "exit_code": 17 if failed else 0, "cleanup_complete": True, "process_started": True,
            "log_sha256": hashlib.sha256(raw).hexdigest(), "log_size_bytes": len(raw), "duration_seconds": 1.0}

    def run(self):
        result = self.control.execute()
        self.saved = json.loads((self.control.output / "report.json").read_text())
        return result


class SubstitutionRunnerTests(unittest.TestCase):
    def test_control_population_is_separate_and_bounded_with_exact_loader_environment(self):
        with SyntheticControlHarness() as harness:
            result = harness.run()
            self.assertEqual(result, harness.saved)
            self.assertEqual(result["outcome"], "pass", result["reason"])
            self.assertIs(result["control_passed"], True)
            self.assertIs(result["managed_population_included"], False)
            self.assertEqual(result["control_counts"]["launches"], 33)
            self.assertNotIn("completed_counts", result)
            self.assertEqual(result["rejection"], control.REJECTION)
            self.assertEqual(result["control_products_before"], result["control_products_after"])
            self.assertEqual([row["name"] for row in harness.calls], ["compile-alternate-extension",
                "link-alternate-extension", "run-alternate-extension"])
            native = harness.calls[-1]
            self.assertEqual(native["environment"]["LD_LIBRARY_PATH"],
                str(harness.control.work) + ":" + str(harness.build / "sw/runtime"))
            self.assertEqual(native["timeout_seconds"], 180)
            self.assertEqual([row["timeout_seconds"] for row in harness.calls[:2]], [1800, 1800])
            for row in harness.calls:
                self.assertEqual(row["environment"]["THREADS"], "1")
                self.assertEqual(row["environment"]["MAKEFLAGS"], "-j2")
                for name, value in control.BUDGET.items():
                    self.assertEqual(row[name], value)
            for flag in dependency.FALSE_CLAIMS:
                self.assertIs(result[flag], False)

    def test_failed_build_stops_native_execution_and_retains_first_failure_over_drift(self):
        with SyntheticControlHarness() as harness:
            harness.failure = "compile-alternate-extension"
            harness.drift = True
            result = harness.run()
            self.assertEqual(result["outcome"], "fail")
            self.assertIn("synthetic_failure", result["reason"])
            self.assertEqual(result["native_execution"], "not_run")
            self.assertIs(result["control_passed"], False)
            self.assertEqual(len(harness.calls), 1)
            self.assertEqual([row["stage"] for row in result["failures"]], ["execution", "final-stability"])

    def test_native_failure_cannot_become_a_successful_negative_control(self):
        with SyntheticControlHarness() as harness:
            harness.failure = "run-alternate-extension"
            result = harness.run()
            self.assertEqual(result["native_execution"], "run")
            self.assertEqual(result["outcome"], "fail")
            self.assertIs(result["control_passed"], False)
            self.assertIs(result["original_provenance_rejected"], False)

    def test_unreturned_native_start_receipt_remains_unknown_and_retains_partial_log(self):
        with SyntheticControlHarness() as harness:
            def interrupted(argv, cwd, environment, log_path, **limits):
                result = harness.command(argv, cwd, environment, log_path, **limits)
                if Path(log_path).stem == "run-alternate-extension":
                    raise RuntimeError("synthetic native monitor interruption")
                return result

            harness.executor.side_effect = interrupted
            result = harness.run()
            self.assertEqual(result["outcome"], "fail")
            self.assertEqual(result["native_execution"], "unknown")
            self.assertIs(result["control_passed"], False)
            self.assertEqual(result["reason"], "synthetic native monitor interruption")
            native = result["commands"][-1]
            self.assertIsNone(native["process_started"])
            self.assertEqual(native["outcome"], "fail")
            body = (harness.control.output / native["log"]).read_bytes()
            self.assertEqual(native["log_sha256"], hashlib.sha256(body).hexdigest())
            self.assertEqual(native["log_size_bytes"], len(body))
            self.assertIn(native["log"], [row["path"] for row in result["retained_files"]])

    def test_resource_block_precedes_admission_and_any_execution(self):
        with SyntheticControlHarness() as harness:
            with mock.patch.object(control.shutil, "disk_usage", return_value=SimpleNamespace(free=1)), \
                    mock.patch.object(harness.control, "admit", side_effect=lambda: control.Control.admit(harness.control)):
                harness.control.initial = None
                result = harness.run()
            self.assertEqual(result["outcome"], "blocked")
            self.assertIn("15 GiB", result["reason"])
            self.assertEqual(result["native_execution"], "not_run")
            harness.executor.assert_not_called()

    def test_cli_requires_the_explicit_dependency_receipt_and_pin(self):
        args = control.argument_parser().parse_args(["--build-dir", "/build", "--managed-report", "/managed.json",
            "--dependency-receipt", "/receipt.json", "--dependency-receipt-sha256", PIN,
            "--expected-revision", REVISION, "--output-dir", "/control"])
        self.assertEqual(args.dependency_receipt, Path("/receipt.json"))
        self.assertEqual(args.dependency_receipt_sha256, PIN)


if __name__ == "__main__":
    unittest.main()
