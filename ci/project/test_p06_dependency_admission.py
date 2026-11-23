# SPDX-License-Identifier: Apache-2.0
"""Host controls for opt-in dependency admission; no native GPU execution."""

import copy
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import p06_dependency_admission as admission
import p06_dependency_contract as dependency_contract
import p06_dependency_lifetime_execute as runner
import p06_managed_preflight_build as build_records
import p06_managed_preflight_execute as preflight
import p06_native_lifetime_contract as lifetime
from p06_managed_preflight_build_fixture import generate
from test_p06_dependency_binary import archive, descriptor, map_text, member
from test_p06_managed_preflight_runner import FIRST, HASH, REVISION
from test_p06_native_lifetime_runner import LifetimeHarness


ROOT = preflight.ROOT


class LiveInputs:
    """Synthetic inert-reader output; the live boundary uses actual file hashes."""

    def __init__(self, source, tools):
        self.source = source
        self.path = source.parent / "dependency-original/report.json"
        self.path.parent.mkdir()
        manifest = {"sources": []}
        staged = []
        for name, pin in dependency_contract.PINS.items():
            path = source / pin["path"] / "p06-host-fixture.h"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"synthetic pinned input: " + name.encode())
            row = admission._live_identity(path)
            manifest["sources"].append({"name": name, "files": [dict(row, path=path.name)]})
            if name in ("yaml-cpp", "spdlog", "argparse"):
                staged.append(row)
        self.members = [descriptor("first.o", b"first-object"), descriptor("second.o", b"second-object")]
        products = {}
        for name, relative in dependency_contract.PRODUCTS.items():
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            body = (archive(member("first.o/", b"first-object"), member("second.o/", b"second-object"))
                    if name == "softfloat" else b"synthetic linked product: " + name.encode())
            path.write_bytes(body)
            row = admission._live_identity(path)
            staged.append(row)
            products[name] = {"original_path": str(source.parent / "dependency-build" / path.name),
                "staged_path": str(path), "sha256": row["sha256"], "size_bytes": row["size_bytes"],
                "payload": "payloads/" + row["sha256"] + ".bin"}
        helper = "ci/project/p06_dependency_admission.py"
        helper_path = source / helper
        helper_path.parent.mkdir(parents=True, exist_ok=True)
        helper_path.write_bytes((ROOT / helper).read_bytes())
        self.document = {"paths": {"source": str(source),
                                  "workspace": str(source.parent / "dependency-build")}, "products": products,
            "source_manifest": manifest, "staged_files": sorted(staged, key=lambda row: row["path"]),
            "helper_sources": HASH(source, [helper]), "tools": tools,
            "external_archives": [], "fresh_dependency_build_passed": True,
            **dict.fromkeys(dependency_contract.FALSE_CLAIMS, False)}
        self.verification = {"fresh_dependency_build_passed": True,
            "archives": {"softfloat": {"members": self.members}},
            **dict.fromkeys(dependency_contract.FALSE_CLAIMS, False)}
        self.write()

    def write(self):
        self.path.write_bytes(preflight.base._json_bytes(self.document))
        self.sha256 = hashlib.sha256(self.path.read_bytes()).hexdigest()

    def load(self, path, expected_sha256, expected_revision):
        if Path(path) != self.path or expected_sha256 != hashlib.sha256(self.path.read_bytes()).hexdigest():
            raise ValueError("dependency receipt digest differs from the caller pin")
        if expected_revision != REVISION:
            raise ValueError("dependency expected revision differs")
        return copy.deepcopy(self.document), copy.deepcopy(self.verification)

    def admit(self):
        with mock.patch.object(admission.receipt, "load_receipt", side_effect=self.load):
            return admission.Admission(self.path, self.sha256, source=self.source, expected_revision=REVISION)

    def model(self, build):
        objects = sorted(str(build_records.expected_object(name, build)) for name in build_records.MODEL_SOURCES)
        for path in objects:
            output = Path(path)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"synthetic model object: " + output.name.encode())
        runtime = build / "sw/runtime"
        (runtime / "libsimx.so").write_bytes(b"synthetic model linked output")
        softfloat = self.document["products"]["softfloat"]["staged_path"]
        text = map_text([softfloat + "(first.o) " + objects[0] + " (fixture_symbol)"],
            [*objects, softfloat, *(self.document["products"][name]["staged_path"]
                                   for name in ("ramulator", "extension"))])
        (build / admission.MODEL_MAP).write_text(text)
        return {"object_paths": objects, "dependency_link_map": str(build / admission.MODEL_MAP),
                "dependency_compilation_provenance_verified": False}


class DependencyHarness(LifetimeHarness):
    def __enter__(self):
        super().__enter__()
        for relative in admission.SOURCE_FILES:
            path = self.paths["source"] / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((ROOT / relative).read_bytes())
        self.source_names = sorted(set(self.source_names) | set(admission.SOURCE_FILES))
        self.helper_names += [name for name in admission.SOURCE_FILES if name.endswith(".py")]
        self.helpers = HASH(self.paths["source"], self.helper_names)
        preflight.loaded_helpers.return_value = self.helpers
        self.inputs = LiveInputs(self.paths["source"], self.tool_inventory())
        self.args.dependency_receipt = self.inputs.path
        self.args.dependency_receipt_sha256 = self.inputs.sha256
        self.stack.enter_context(mock.patch.object(admission.receipt, "load_receipt", side_effect=self.inputs.load))
        preflight.build_records.validate_build_commands.side_effect = self.model_records
        self.application = self.stack.enter_context(mock.patch.object(
            admission.application, "validate_application_build", side_effect=self.application_records))
        return self

    def configure(self, build):
        super().configure(build)
        path = build / admission.MODEL_MAKEFILE
        path.write_bytes((self.paths["source"] / admission.MODEL_MAKEFILE).read_bytes())

    def model_records(self, *args, **kwargs):
        return {"object_paths": sorted(str(build_records.expected_object(name, kwargs["build"]))
                                       for name in build_records.MODEL_SOURCES),
                "dependency_link_map": kwargs["dependency_map"],
                "dependency_compilation_provenance_verified": False}

    def application_records(self, text, stamp, **kwargs):
        return {"contract_id": admission.application.CONTRACT_ID, "format": kwargs["fmt"],
                "command_count": 30, "normalized_commands_sha256": "a" * 64}

    def command(self, argv, cwd, environment, logfile, **budget):
        name = logfile.stem
        build = self.paths["work"] / ("simx-bf16" if "bf16" in name else "simx-fp16")
        if name.endswith("-dependency-model"):
            self.inputs.model(build)
        preserved = []
        if name.endswith(("-backend", "-application")):
            for path in [build / "sw/runtime/libsimx.so", *(build_records.expected_object(relative, build)
                                                            for relative in build_records.MODEL_SOURCES)]:
                preserved.append((path, path.read_bytes()))
        after = self.after_command

        def restore(identifier, directory):
            for path, body in preserved:
                path.write_bytes(body)
            after(identifier, directory)

        self.after_command = restore
        try:
            return super().command(argv, cwd, environment, logfile, **budget)
        finally:
            self.after_command = after

    def run(self):
        result = runner.execute(self.args, self.paths)
        self.saved = json.loads((self.paths["output"] / "report.json").read_text())
        return result


class AdmissionLiveChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="p06-dependency-live-inputs-")
        self.addCleanup(self.temporary.cleanup)
        self.source = Path(self.temporary.name) / "source"
        self.source.mkdir()
        self.tool = self.source.parent / "host-cxx"
        self.tool.write_bytes(b"synthetic host compiler identity")
        self.tools = {"g++": preflight.base._file_identity(self.tool)}
        self.inputs = LiveInputs(self.source, self.tools)

    def test_valid_live_inputs_and_exact_staged_population(self):
        checked = self.inputs.admit()
        self.assertEqual(checked.verify_stable(self.tools)["receipt_sha256"], self.inputs.sha256)
        self.assertEqual(len(checked.source_inputs), len(dependency_contract.PINS))
        self.assertEqual(checked.summary["verification"], self.inputs.verification)
        self.inputs.document["staged_files"].pop()
        self.inputs.write()
        with self.assertRaisesRegex(ValueError, "staged dependency inventory"):
            self.inputs.admit()

    def test_staged_product_and_nonstaged_pinned_source_drift(self):
        checked = self.inputs.admit()
        for path in (self.source / dependency_contract.PINS["softfloat"]["path"] / "p06-host-fixture.h",
                     self.source / dependency_contract.PRODUCTS["ramulator"]):
            before = path.read_bytes()
            path.write_bytes(before + b"changed")
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "pinned dependency source or staged bytes"):
                checked.verify_stable(self.tools)
            path.write_bytes(before)

    def test_receipt_and_selected_tool_drift_fail(self):
        checked = self.inputs.admit()
        self.inputs.path.write_bytes(self.inputs.path.read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "receipt changed"):
            checked.verify_stable(self.tools)
        self.inputs.write()
        self.tool.write_bytes(b"different executable")
        with self.assertRaisesRegex(ValueError, "tool identity changed"):
            checked.verify_stable(self.tools)

    def test_dependency_and_managed_tools_must_match(self):
        checked = self.inputs.admit()
        with self.assertRaisesRegex(ValueError, "managed and dependency selected tools differ"):
            checked.verify_stable({"g++": dict(self.tools["g++"], sha256="0" * 64)})

    def test_symlink_and_hardlink_staged_inputs_reject(self):
        target = self.source / dependency_contract.PRODUCTS["ramulator"]
        backup = self.source.parent / "different-directory-library"
        target.rename(backup)
        target.symlink_to(backup)
        with self.assertRaisesRegex(ValueError, "symlink traversal"):
            self.inputs.admit()
        target.unlink()
        target.hardlink_to(backup)
        with self.assertRaisesRegex(ValueError, "unlinked regular file"):
            self.inputs.admit()

    def test_literal_documentation_parentheses_are_data_but_substitution_rejects(self):
        path = self.source / "yaml-cpp-emitter(advanced).md"
        body = b"literal pinned documentation bytes"
        path.write_bytes(body)
        self.assertEqual(admission._live_identity(path), {
            "path": str(path), "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)})
        unsafe = self.source / "$(command).md"
        unsafe.write_bytes(body)
        with self.assertRaisesRegex(ValueError, "safe absolute literals"):
            admission._live_identity(unsafe)
        with self.assertRaisesRegex(ValueError, "root paths"):
            preflight.base._path(path, existing=True)

    def test_exact_model_member_object_and_product_join(self):
        checked = self.inputs.admit()
        build = self.source.parent / "model-build"
        build.mkdir()
        records = self.inputs.model(build)
        result = checked.validate_model(build, records)
        self.assertIs(result["source_to_model_link_verified"], True)
        self.assertEqual(len(result["objects"]), 43)
        self.assertEqual(result["verification"]["selected_members"][0]["sha256"], self.inputs.members[0]["sha256"])
        checked.verify_model_stable(result)
        Path(result["objects"][0]["path"]).write_bytes(b"changed compiled object")
        with self.assertRaisesRegex(ValueError, "admitted model object"):
            checked.verify_model_stable(result)

    def test_model_map_requires_selected_member_and_every_object(self):
        checked = self.inputs.admit()
        build = self.source.parent / "model-build"
        build.mkdir()
        records = self.inputs.model(build)
        path = build / admission.MODEL_MAP
        original = path.read_text()
        for changed in (original.replace("LOAD " + records["object_paths"][0] + "\n", ""),
                        original[original.index(admission.binary.MAP_HEADING):]):
            path.write_text(changed)
            with self.subTest(changed=changed[:30]), self.assertRaises(ValueError):
                checked.validate_model(build, records)

    def test_application_source_reader_requires_frozen_recipe_bytes(self):
        checked = self.inputs.admit()
        name = "config.mk.in"
        path = self.source / name
        path.write_bytes((ROOT / name).read_bytes())
        identities = HASH(self.source, [name])

        def inspect(*args, **kwargs):
            return kwargs["source_body"](name)

        options = dict(build=self.source.parent / "build", tools_root=self.source.parent,
                       tools={}, fmt="fp16", compiler_records=[], source_files=identities)
        with mock.patch.object(admission.application, "validate_application_build", side_effect=inspect):
            self.assertEqual(checked.validate_application("", "", **options), path.read_bytes())
            path.write_bytes(path.read_bytes() + b"\n")
            with self.assertRaisesRegex(ValueError, "recipe changed after the source freeze"):
                checked.validate_application("", "", **options)

    def test_model_map_rejects_extra_source_or_work_loads(self):
        checked = self.inputs.admit()
        work = self.source.parent / "work"
        build = work / "simx-fp16"
        build.mkdir(parents=True)
        records = self.inputs.model(build)
        checked.validate_model(build, records)
        path = build / admission.MODEL_MAP
        original = path.read_text()
        for extra in (build / "sw/runtime/unplanned.so", build / "sw/runtime/unplanned.a",
                      work / "simx-bf16/unplanned.o", self.source / "unplanned.so"):
            path.write_text(original + "\nLOAD " + str(extra) + "\n")
            with self.subTest(extra=extra), self.assertRaisesRegex(
                    ValueError, "unplanned source/work input"):
                checked.validate_model(build, records)


class DependencyManagedRunnerTests(unittest.TestCase):
    def assert_finished(self, fixture, result, *, passed):
        self.assertEqual(result, fixture.saved)
        self.assertEqual(result["state"], "finished")
        self.assertEqual(result["contract_id"], dependency_contract.MANAGED_CONTRACT_ID)
        self.assertIs(result["native_lifetime_passed"], passed)
        self.assertIs(result["dependency_source_to_loaded_binary_verified"], passed)
        self.assertTrue(all(result[name] is False for name in dependency_contract.FALSE_CLAIMS))

    def test_complete_route_binds_receipt_application_and_unchanged_lifetime(self):
        events = []
        real_import = importlib.import_module

        def imported(name):
            events.append("import:" + name)
            return real_import(name)

        with DependencyHarness() as fixture:
            def helpers():
                events.append("helpers")
                return fixture.helpers

            with mock.patch.object(preflight.importlib, "import_module", side_effect=imported), \
                    mock.patch.object(preflight, "loaded_helpers", side_effect=helpers):
                result = fixture.run()
            self.assert_finished(fixture, result, passed=True)
            self.assertEqual(result["completed_counts"], preflight.COMPLETE_COUNTS)
            self.assertEqual(fixture.application.call_count, 2)
            self.assertEqual(fixture.lifetime_verify.call_count, 4)
            self.assertLess(events.index("import:p06_dependency_admission"), events.index("helpers"))
            self.assertLess(events.index("import:p06_native_lifetime_records"), events.index("helpers"))
            self.assertEqual(fixture.retained(result["contract_snapshot"]), admission.contract())
            self.assertEqual(result["contract_sha256"], admission.contract_hash())
            self.assertEqual(result["dependency_receipt_sha256"], fixture.inputs.sha256)
            for variant in result["variants"]:
                self.assertEqual(len(variant["retained_dependency_model_payloads"]), 44)
                self.assertIs(variant["model_build_records"]["dependency_compilation_provenance_verified"], False)
                binding = fixture.retained(variant["binding"])
                self.assertEqual(binding["application_build_records"], variant["application_build_records"])
                self.assertEqual(binding["dependency_model_link"], variant["dependency_model_link"])
                self.assertEqual(binding["dependency_receipt_sha256"], fixture.inputs.sha256)
                self.assertEqual(preflight.qualification_id(binding), variant["build_binding_sha256"])
                self.assertEqual(binding["lifetime_contract"], lifetime.contract())
            for process in result["processes"]:
                binding = fixture.retained(process["binding"])
                self.assertEqual(binding["lifetime_contract"], lifetime.contract())
                self.assertEqual(binding["build"]["lifetime_contract"], lifetime.contract())
                self.assertEqual(binding["dependency_receipt_sha256"], fixture.inputs.sha256)
                self.assertEqual(preflight.qualification_id(binding), process["execution_binding_sha256"])
                altered = copy.deepcopy(binding)
                altered["build"]["application_build_records"]["normalized_commands_sha256"] = "0" * 64
                self.assertNotEqual(preflight.qualification_id(altered), process["execution_binding_sha256"])
                altered = copy.deepcopy(binding)
                altered["build"]["dependency_receipt_sha256"] = "0" * 64
                self.assertNotEqual(preflight.qualification_id(altered), process["execution_binding_sha256"])

    def test_bad_receipt_prevents_any_commands_and_native_execution(self):
        with DependencyHarness() as fixture:
            fixture.args.dependency_receipt_sha256 = "0" * 64
            result = fixture.run()
            self.assert_finished(fixture, result, passed=False)
            self.assertIn("caller pin", result["reason"])
            self.assertEqual(result["commands"], [])
            self.assertEqual(result["native_execution"], "not_run")

    def test_complete_application_failure_prevents_native_launch(self):
        with DependencyHarness() as fixture:
            fixture.application.side_effect = ValueError("complete application graph lacks stub compile")
            result = fixture.run()
            self.assert_finished(fixture, result, passed=False)
            self.assertIn("lacks stub compile", result["reason"])
            self.assertEqual(fixture.launches(), [])
            self.assertEqual(fixture.application.call_count, 1)

    def test_staged_header_drift_stops_remaining_processes(self):
        with DependencyHarness() as fixture:
            path = fixture.paths["source"] / dependency_contract.PINS["argparse"]["path"] / "p06-host-fixture.h"

            def mutate(name, build):
                if name == FIRST:
                    path.write_bytes(b"changed staged source")

            fixture.after_command = mutate
            result = fixture.run()
            self.assert_finished(fixture, result, passed=False)
            self.assertIn("pinned dependency source or staged bytes changed", result["reason"])
            self.assertEqual(fixture.launches(), [FIRST])

    def test_full_matrix_final_receipt_failure_cannot_pass(self):
        with DependencyHarness() as fixture:
            original = admission.Admission.verify_stable

            def observed(instance, tools=None):
                report = fixture.paths["output"] / "report.json"
                state = json.loads(report.read_text()) if report.exists() else {}
                variants = state.get("variants", [])
                if len(variants) == 2 and all(row["outcome"] == "pass" for row in variants):
                    fixture.inputs.path.write_bytes(fixture.inputs.path.read_bytes() + b"\n")
                return original(instance, tools)

            with mock.patch.object(admission.Admission, "verify_stable", new=observed):
                result = fixture.run()
            self.assert_finished(fixture, result, passed=False)
            self.assertIn("receipt changed", result["reason"])
            self.assertEqual(len(fixture.launches()), 4)
            self.assertEqual(result["completed_counts"], preflight.COMPLETE_COUNTS)
            self.assertEqual(result["failures"][0]["stage"], "final-dependency-admission")

    def test_earlier_failure_remains_primary_when_final_receipt_also_changes(self):
        with DependencyHarness() as fixture:
            fixture.results[FIRST] = {"outcome": "fail", "reason": "compiler-or-process-original-exit37", "exit_code": 37}

            def mutate(name, build):
                if name == FIRST:
                    fixture.inputs.path.write_bytes(fixture.inputs.path.read_bytes() + b"\n")

            fixture.after_command = mutate
            result = fixture.run()
            self.assert_finished(fixture, result, passed=False)
            self.assertIn("original-exit37", result["reason"])
            self.assertTrue(any(row["stage"] == "final-dependency-admission" for row in result["failures"]))
            self.assertEqual(fixture.launches(), [FIRST])

    def test_companion_map_and_object_drift_fail_before_native(self):
        for relative in (admission.MODEL_MAP, "sw/runtime/libsimx.so"):
            with self.subTest(relative=relative), DependencyHarness() as fixture:
                def mutate(name, build):
                    if name == "simx-fp16-application":
                        (build / relative).write_bytes(b"changed application-side model bytes")

                fixture.after_command = mutate
                result = fixture.run()
                self.assert_finished(fixture, result, passed=False)
                self.assertIn("admitted model object, binary or link map changed", result["reason"])
                self.assertEqual(fixture.launches(), [])

    def test_mode_selector_is_exact_boolean_and_requires_lifetime(self):
        for options in ({"dependency": True}, {"lifetime": True, "dependency": 1},
                        {"lifetime": True, "dependency": "yes"}):
            with self.subTest(options=options), self.assertRaisesRegex(ValueError, "dependency admission requires"):
                preflight.execute(None, None, **options)

    def test_old_entry_point_imports_exclude_new_dependency_helpers(self):
        for module in ("p06_managed_preflight_execute", "p06_native_lifetime_execute"):
            code = "\n".join(("import sys", "sys.path.insert(0, " + repr(str(ROOT / "ci/project")) + ")",
                "import " + module, "assert not any(name.startswith('p06_dependency') for name in sys.modules)",
                "import p06_managed_preflight_execute as runner",
                "assert not any('p06_dependency' in row['path'] for row in runner.LOADED_HELPERS)"))
            with self.subTest(module=module):
                result = subprocess.run([sys.executable, "-I", "-B", "-c", code],
                    capture_output=True, text=True, timeout=30, check=False)
                self.assertEqual(result.returncode, 0, result.stderr)


class DependencyModelGrammarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        parent = "/home/agent" if Path("/home/agent").is_dir() else None
        cls.temporary = tempfile.TemporaryDirectory(prefix="p06-dependency-map-grammar-", dir=parent)
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.generated = generate(Path(cls.temporary.name))

    def validate(self, data, *, text=None, **options):
        return build_records.validate_build_commands(text or data["text"], *data["stamps"][:2],
            data["backend_linker"], **{key: data[key] for key in (
                "source", "build", "compiler", "make", "fmt", "source_files")}, **options)

    def mapped(self, data):
        path = str(data["build"] / admission.MODEL_MAP)
        suffix = " -o " + str(data["build"] / "sw/runtime/libsimx.so")
        return data["text"].replace(suffix, " -Wl,-Map," + path + suffix), path

    def test_exact_opt_in_flag_and_historical_false_claim(self):
        for data in self.generated["formats"].values():
            text, path = self.mapped(data)
            result = self.validate(data, text=text, dependency_map=path)
            self.assertEqual(result["dependency_link_map"], path)
            self.assertEqual(result["model_translation_units"], 43)
            self.assertIs(result["dependency_compilation_provenance_verified"], False)
            self.assertNotIn("dependency_link_map", self.validate(data))
            with self.assertRaisesRegex(ValueError, "exact dependencies"):
                self.validate(data, text=text)

    def test_missing_duplicate_unselected_and_relocated_map_reject(self):
        data = self.generated["formats"]["fp16"]
        text, path = self.mapped(data)
        flag = "-Wl,-Map," + path
        for changed in (data["text"], text.replace(flag, flag + " " + flag),
                        text.replace(flag, flag + " -Wl,--as-needed"), text.replace(flag, "-Wl,-Map,/tmp/other.map")):
            with self.subTest(text=changed[-100:]), self.assertRaises(ValueError):
                self.validate(data, text=changed, dependency_map=path)
        for value in (True, Path(path), "/tmp/other.map"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "exact reviewed build path"):
                self.validate(data, text=text, dependency_map=value)


if __name__ == "__main__":
    unittest.main()
