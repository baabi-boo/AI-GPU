"""Exercise replay mutation code on explicit synthetic raw parser fixtures only."""

import ast
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import unittest

import test_p06_counter_public_records as fixtures
import test_p06_counter_public_replay as tests


ROOT = Path.cwd()
OUT = ROOT.parent
LOG = OUT / "w07-public-replay-integration-tests.log"
parser = tests.replay.public_records
positive = {mode: fixtures.result(mode) for mode in parser.MODES}
original = {}
report = {"commands": [], "cells": []}
for mode, value in positive.items():
    name = "logs/public-" + mode + ".log"
    original[tests.PREFIX + name] = (parser.RESULT_PREFIX + tests.encoded(value).decode()).encode()
    report["commands"].append({"id": "public-" + mode, "log": name})
    report["cells"].append({"mode": mode, "observations": deepcopy(value)})
original[tests.REPORT] = tests.encoded(report)

source = (OUT / "w07-public-replay-integration-tests-before.py").read_text()
tree = ast.parse(source)
cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "OriginalPublicReplayTests")
method = next(node for node in cls.body if isinstance(node, ast.FunctionDef)
              and node.name == "test_public_result_duplicate_keys_numbers_and_record_boundaries_are_strict")
assignment = next(node for node in method.body if isinstance(node, ast.Assign)
                  and node.targets[0].id == "transformations")
before_cases = []
body = original[tests.PREFIX + "logs/public-normal.log"]
for expression in assignment.value.elts[1:3]:
    transform = eval(compile(ast.Expression(expression), "retained-before-test-source", "eval"))
    changed = transform(body)
    accepted = parser.verify_output(changed.decode(), "normal")
    assert changed == body and accepted["schema_version"] == 2
    before_cases.append({"transformation": ast.unparse(expression), "bytes_changed": False,
                         "parser_accepted_schema": accepted["schema_version"]})
with LOG.open("a") as stream:
    stream.write("\nBASELINE F2 REPRODUCTION (synthetic raw parser fixture; no archive/native execution)\n")
    stream.write(json.dumps(before_cases, indent=2) + "\n")
print("Baseline stale mutations:", json.dumps(before_cases))


class SyntheticRawReplayMutationProbes(unittest.TestCase):
    original = original
    reject_observation = tests.OriginalPublicReplayTests.reject_observation
    rejected = []

    def reject(self, members, pattern=".", **kwargs):
        errors = []
        for mode in parser.MODES:
            try:
                parser.verify_output(members[tests.PREFIX + "logs/public-" + mode + ".log"].decode(), mode)
            except ValueError as error:
                errors.append((mode, str(error)))
        self.assertEqual(len(errors), 1, "exactly the mutated raw observation must fail")
        self.assertRegex(errors[0][1], pattern)
        self.rejected.append({"method": self.id(), "mode": errors[0][0], "reason": errors[0][1]})

    def test_five_schema2_counts_are_parser_controls_only(self):
        expected = {"normal": 1668, "coherent-terminal": 1814, "immediate-overflow": 1176,
                    "delayed-overflow": 1176, "cache-overflow": 1173}
        for mode, checks in expected.items():
            with self.subTest(mode=mode):
                value = parser.verify_output(original[tests.PREFIX + "logs/public-" + mode + ".log"].decode(), mode)
                self.assertEqual((value["schema_version"], value["checks"]), (2, checks))
                self.assertFalse(value["qualified"])

    def test_noop_and_missing_selected_paths_fail_before_rejection(self):
        value = deepcopy(positive["normal"])
        with self.assertRaisesRegex(AssertionError, "did not change"):
            tests.replace(value, ("checks",), 1668)
        with self.assertRaises(KeyError):
            tests.replace(value, ("terminal_snapshots", 0, "cp_after", "head"), 1)
        with self.assertRaisesRegex(AssertionError, "did not change"):
            tests.replace_payload({"public-counters/inert": b"same"}, "inert", b"same")
        members = {tests.REPORT: tests.encoded({"commands": [{"id": "build", "log": "build.log"}]}),
                   tests.PREFIX + "build.log": b"inert build command\n"}
        with self.assertRaisesRegex(AssertionError, "did not change"):
            tests.alter_build(members, "build", lambda line: True, lambda line: line)


copied = (
    "test_suppressed_dma_requires_original_ram_and_complemented_attempt",
    "test_terminal_counters_components_halves_and_clock_are_verified",
    "test_terminal_requires_exclusive_ownership_retired_cp_and_destruction",
    "test_overflow_requires_original_callback_and_fresh_context_evidence",
    "test_observation_types_keys_and_integer_bounds_are_strict",
    "test_public_result_duplicate_keys_numbers_and_record_boundaries_are_strict",
)
for name in copied:
    setattr(SyntheticRawReplayMutationProbes, name, getattr(tests.OriginalPublicReplayTests, name))
spec = importlib.util.spec_from_file_location("w07_accounted_runner", OUT / "w07-public-replay-integration-runner.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
suite = unittest.defaultTestLoader.loadTestsFromTestCase(SyntheticRawReplayMutationProbes)
passed = runner.run_accounted(suite, "direct-synthetic-raw-parser-mutation-probes", log_path=LOG,
    result_path=OUT / "w07-public-replay-raw-mutation-probes-result.json",
    source_paths=[ROOT / "ci/project/test_p06_counter_public_replay.py",
                  ROOT / "ci/project/p06_counter_public_records.py",
                  ROOT / "ci/project/test_p06_counter_public_records.py"])
with LOG.open("a") as stream:
    stream.write("RAW PARSER REJECTION COUNT " + str(len(SyntheticRawReplayMutationProbes.rejected)) + "\n")
    for row in SyntheticRawReplayMutationProbes.rejected:
        stream.write("RAW REJECTION " + json.dumps(row, sort_keys=True) + "\n")
(OUT / "w07-public-replay-raw-mutation-rejections.json").write_text(json.dumps(
    {"scope": "synthetic raw parser mutation probes only; no archive or native execution",
     "baseline_noops": before_cases, "rejections": SyntheticRawReplayMutationProbes.rejected}, indent=2) + "\n")
sys.exit(0 if passed else 1)
