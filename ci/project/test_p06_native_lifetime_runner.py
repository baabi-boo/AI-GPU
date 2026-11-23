# SPDX-License-Identifier: Apache-2.0
"""Lifetime orchestration with simulated commands and real transcript checks."""

import copy
import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import p06_managed_preflight_execute as preflight
import p06_native_lifetime_contract as contract
import p06_native_lifetime_execute as runner
import p06_native_lifetime_records as records
import p06_native_lifetime_test_fixture as samples
from test_p06_managed_preflight_runner import FIRST, HASH, ManagedHarness


ROOT = preflight.ROOT


class LifetimeHarness(ManagedHarness):
    def __enter__(self):
        temporary_directory = tempfile.TemporaryDirectory

        def temporary(*args, **kwargs):
            kwargs.pop("dir", None)
            return temporary_directory(*args, **kwargs)

        with mock.patch.object(tempfile, "TemporaryDirectory", side_effect=temporary):
            super().__enter__()
        self.source_requests = []
        self.transform_output = lambda name, text: text
        for relative in contract.SOURCE_FILES:
            target = self.paths["source"] / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / relative).read_bytes())
        self.source_names = sorted(set(self.source_names) | set(contract.SOURCE_FILES))
        self.helper_names += [name for name in contract.SOURCE_FILES if name.endswith(".py")]
        self.helpers = HASH(self.paths["source"], self.helper_names)
        preflight.loaded_helpers.return_value = self.helpers
        self.mutate_output = self.lifetime_output
        self.lifetime_verify = self.stack.enter_context(
            mock.patch.object(records, "verify_output", wraps=records.verify_output))
        return self

    def source_snapshot(self, source, helpers=None, *, extra_source_files=()):
        self.source_requests.append(tuple(extra_source_files))
        return {"checkout": copy.deepcopy(self.checkout),
                "files": HASH(source, sorted(set(self.source_names) | set(extra_source_files)))}

    def lifetime_output(self, name, text):
        if name.startswith("preflight-"):
            _, original = records.parent_records._split_output(text)
            _, operations, summary, witness, lifetime = samples.raw_records(
                original["format"], original["policy"],
                binding_id=original["execution_binding_sha256"])
            witness["loaded_libraries"] = original["loaded_libraries"]
            text = samples.render_log(operations, summary, witness, lifetime)
        return self.transform_output(name, text)

    def command(self, argv, *args, **kwargs):
        original = list(argv)
        translated = original
        if len(original) > 1 and original[1] == contract.APP_FLAG:
            translated = [original[0], *original[2:]]
        try:
            return super().command(translated, *args, **kwargs)
        finally:
            self.calls[-1]["argv"] = original

    def run(self):
        result = runner.execute(self.args, self.paths)
        self.saved = json.loads((self.paths["output"] / "report.json").read_text())
        return result

    def retained(self, descriptor):
        return json.loads((self.paths["output"] / descriptor["path"]).read_text())


class NativeLifetimeRunnerTests(unittest.TestCase):
    def assert_finished(self, fixture, result, *, passed):
        self.assertEqual(result, fixture.saved)
        self.assertEqual(result["state"], "finished")
        self.assertEqual(result["contract_id"], contract.CONTRACT_ID)
        self.assertEqual(result["scope"], contract.SCOPE)
        self.assertIs(result["native_preflight_passed"], passed)
        self.assertIs(result["native_lifetime_passed"], passed)
        self.assertEqual(result["unresolved_obligations"], list(contract.UNRESOLVED_OBLIGATIONS))
        self.assertEqual(len(result["unresolved_obligations"]), 3)
        self.assertEqual(len(contract.FALSE_CLAIMS), 7)
        for name in contract.FALSE_CLAIMS:
            self.assertIs(result[name], False)
        if not passed:
            self.assertIn(result["outcome"], ("blocked", "fail"))
            self.assertTrue(result["failures"])

    def test_four_processes_bind_descriptor_helpers_sources_and_explicit_mode(self):
        events = []
        real_import = importlib.import_module

        def imported(name):
            events.append("import:" + name)
            return real_import(name)

        with LifetimeHarness() as fixture:
            def helpers():
                events.append("helpers")
                return fixture.helpers

            with mock.patch.object(preflight.importlib, "import_module", side_effect=imported), \
                    mock.patch.object(preflight, "loaded_helpers", side_effect=helpers):
                result = fixture.run()
            self.assert_finished(fixture, result, passed=True)
            self.assertEqual(result["completed_counts"], contract.COMPLETE_COUNTS)
            self.assertEqual((result["completed_counts"]["processes"],
                              result["completed_counts"]["launches"],
                              result["completed_counts"]["checked_words"]), (4, 132, 4224))
            self.assertEqual(fixture.launches(), [row["id"] for row in preflight.manifest.process_plan()])
            self.assertEqual(fixture.lifetime_verify.call_count, 4)
            self.assertEqual(fixture.verify.call_count, 4)
            self.assertLess(events.index("import:p06_native_lifetime_records"), events.index("helpers"))
            self.assertTrue(fixture.source_requests)
            self.assertTrue(all(value == contract.SOURCE_FILES for value in fixture.source_requests))
            self.assertEqual(fixture.retained(result["contract_snapshot"]), contract.contract())
            self.assertEqual(result["contract_sha256"], contract.contract_hash())
            parent = fixture.retained(result["preflight_contract_snapshot"])
            self.assertEqual(parent["contract_id"], preflight.CONTRACT_ID)
            self.assertEqual(result["preflight_contract_sha256"], preflight.qualification_id(parent))
            source = fixture.retained(result["source_before"])
            self.assertTrue(set(contract.SOURCE_FILES) <= {row["path"] for row in source["files"]})
            self.assertTrue({name for name in contract.SOURCE_FILES if name.endswith(".py")}
                            <= {row["path"] for row in result["loaded_helpers"]})
            for process in result["processes"]:
                binding = fixture.retained(process["binding"])
                self.assertEqual(binding["contract_id"], contract.CONTRACT_ID)
                self.assertEqual(binding["contract_sha256"], contract.contract_hash())
                self.assertEqual(binding["lifetime_contract"], contract.contract())
                self.assertEqual(binding["preflight_contract_sha256"], result["preflight_contract_sha256"])
                self.assertEqual(preflight.qualification_id(binding), process["execution_binding_sha256"])
                self.assertEqual(preflight.qualification_id(binding["build"]), process["build_binding_sha256"])
                self.assertEqual(binding["build"]["contract_id"], contract.CONTRACT_ID)
                self.assertEqual(binding["build"]["lifetime_contract"], contract.contract())
                for witness in (process["observation"]["witness"], process["observation"]["lifetime"]):
                    for name in contract.FALSE_CLAIMS:
                        self.assertIs(witness[name], False)
            for call in fixture.calls:
                if call["id"].startswith("preflight-"):
                    self.assertEqual(call["argv"][1:3], ["--lifetime", "--policy"])
                    self.assertEqual(call["argv"].count("--lifetime"), 1)
            self.assertEqual(result["retained_files"], HASH(fixture.paths["output"],
                [row["path"] for row in result["retained_files"]]))
            self.assertEqual(preflight.CONTRACT_ID, contract.PARENT_CONTRACT_ID)

    def test_missing_or_invalid_sidecar_stops_after_original_first_process(self):
        for kind in ("missing", "pending", "version"):
            with self.subTest(kind=kind), LifetimeHarness() as fixture:
                def corrupt(name, text):
                    if name != FIRST:
                        return text
                    prefix, lifetime = records._split_output(text)
                    if kind == "missing":
                        return prefix
                    if kind == "pending":
                        lifetime["runs"][0]["before"]["pending_reads"] = 1
                    else:
                        lifetime["contract_id"] = contract.PARENT_CONTRACT_ID
                    return prefix + contract.WITNESS_PREFIX + json.dumps(lifetime) + "\n"

                fixture.transform_output = corrupt
                result = fixture.run()
                self.assert_finished(fixture, result, passed=False)
                self.assertEqual(fixture.launches(), [FIRST])
                self.assertEqual(result["native_execution"], "run")
                self.assertEqual(result["completed_counts"]["processes"], 0)
                self.assertEqual(result["processes"][0]["outcome"], "fail")
                self.assertTrue(result["processes"][0]["log"])
                self.assertIn({"missing": "exactly one lifetime witness", "pending": "pending_reads",
                               "version": "contract_id"}[kind], result["reason"])

    def test_source_or_product_change_after_native_command_invalidates_attempt(self):
        for kind in ("source", "product"):
            with self.subTest(kind=kind), LifetimeHarness() as fixture:
                def mutate(name, build):
                    if name == FIRST:
                        target = (fixture.paths["source"] / "ci/project/p06_native_lifetime_contract.py"
                                  if kind == "source" else build / "sw/runtime/libsimx.so")
                        target.write_bytes(target.read_bytes() + b"changed during native process\n")

                fixture.after_command = mutate
                result = fixture.run()
                self.assert_finished(fixture, result, passed=False)
                self.assertEqual(fixture.launches(), [FIRST])
                self.assertEqual(result["native_execution"], "run")
                self.assertEqual(result["completed_counts"]["processes"], 0)
                self.assertIn("changed", result["reason"])

    def test_later_stability_failure_preserves_original_native_exit(self):
        for kind in ("source", "product"):
            with self.subTest(kind=kind), LifetimeHarness() as fixture:
                fixture.results[FIRST] = {"outcome": "fail", "exit_code": 37, "reason": "nonzero_exit"}

                def mutate(name, build):
                    if name == FIRST:
                        target = (fixture.paths["source"] / "ci/project/p06_native_lifetime_records.py"
                                  if kind == "source" else build / "sw/runtime/libsimx.so")
                        target.write_bytes(target.read_bytes() + b"changed after native failure\n")

                fixture.after_command = mutate
                result = fixture.run()
                self.assert_finished(fixture, result, passed=False)
                self.assertEqual(fixture.launches(), [FIRST])
                self.assertEqual(result["native_execution"], "run")
                self.assertIn("nonzero_exit", result["reason"])
                command = next(row for row in result["commands"] if row["id"] == FIRST)
                self.assertEqual((command["exit_code"], command["reason"]), (37, "nonzero_exit"))
                stage = "final-source" if kind == "source" else "final-artifacts-simx-fp16"
                self.assertTrue(any(row["stage"] == stage for row in result["failures"]))
                self.assertEqual(fixture.lifetime_verify.call_count, 0)

    def test_explicit_source_extras_are_hashed_by_real_snapshot_function(self):
        with tempfile.TemporaryDirectory(prefix="lifetime-source-extras-") as directory:
            source = Path(directory)
            for name in ("base.txt", "extra.txt"):
                (source / name).write_text(name)
            baseline = {"checkout": {}, "files": HASH(source, ["base.txt"])}
            with mock.patch.object(preflight.operator_run, "source_snapshot", return_value=baseline), \
                    mock.patch.object(preflight, "SOURCE_FILES", ()):
                result = preflight.source_snapshot(source, [], extra_source_files=("extra.txt",))
            self.assertEqual(result["files"], HASH(source, ["base.txt", "extra.txt"]))

    def test_actual_helper_inventory_contains_loaded_lifetime_modules(self):
        identities = preflight.loaded_helpers()
        expected = {name for name in contract.SOURCE_FILES if name.endswith(".py")}
        self.assertTrue(expected <= {row["path"] for row in identities})
        self.assertEqual(identities, HASH(ROOT, [row["path"] for row in identities]))

    def test_default_runner_fresh_import_has_no_lifetime_helpers(self):
        code = ("import sys\n"
                f"sys.path.insert(0, {str(ROOT / 'ci/project')!r})\n"
                "import p06_managed_preflight_execute as runner\n"
                "assert not any(name.startswith('p06_native_lifetime') for name in sys.modules)\n"
                "assert runner.CONTRACT_ID == 'p06-managed-counter-preflight-v1'\n"
                "print('default import remains isolated')\n")
        result = subprocess.run([sys.executable, "-I", "-B", "-c", code], cwd=ROOT,
            capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "default import remains isolated\n")

    def test_default_execution_has_no_lifetime_fields_or_mode_selector(self):
        with ManagedHarness() as fixture:
            fixture.results[FIRST] = {"outcome": "fail", "exit_code": 37, "reason": "nonzero_exit"}
            result = fixture.run()
            self.assertEqual(result["contract_id"], contract.PARENT_CONTRACT_ID)
            self.assertNotIn("native_lifetime_passed", result)
            self.assertNotIn("preflight_contract_snapshot", result)
            self.assertTrue(fixture.launches())
            for call in fixture.calls:
                self.assertNotIn(contract.APP_FLAG, call["argv"])


if __name__ == "__main__":
    unittest.main()
