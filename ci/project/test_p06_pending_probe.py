# SPDX-License-Identifier: Apache-2.0
"""Host-only probe checks with real Make stamps and simulated process receipts."""

from contextlib import ExitStack
import copy
import json
from pathlib import Path
import re
import shlex
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import p06_pending_probe as probe
from p06_managed_preflight_build_fixture import generate, ROLES


ROOT = probe.ROOT
REVISION = "a" * 40


def context(gp):
    return {"gp": gp, "steps": 21, "positive_samples": 5, "max_pending": 2,
            "readonly_checks": 23, "stepped_reset_delta": 1, "checked_reset_delta": 1,
            "pending_final": 0, "checked_gp": gp}


def output_lines(libraries, *, zero=False):
    lines = ["P06_PENDING_LIBRARY " + json.dumps({"name": name, "path": libraries[name]})
             for name in probe.LIBRARIES]
    if zero:
        return lines + [probe.ZERO_FAILURE]
    return lines + ["P06_PENDING_CONTEXT " + json.dumps(context(gp)) for gp in (7, -1)] + [probe.PASS_LINE]


def render(lines):
    return "\n".join(lines) + "\n"


def change_role(stamps, outer, inner, change):
    updated = list(stamps)
    lines = updated[outer].splitlines()
    lines[inner] = change(lines[inner])
    updated[outer] = render(lines)
    return tuple(updated)


class PendingOutputTests(unittest.TestCase):
    def setUp(self):
        self.libraries = {name: "/completed-build/" + name for name in probe.LIBRARIES}
        self.lines = output_lines(self.libraries)

    def test_positive_control_requires_both_legacy_gp_values(self):
        result = probe.verify_output(render(self.lines), self.libraries)
        self.assertEqual(result["contexts"], [context(7), context(-1)])
        self.assertEqual([row["name"] for row in result["loaded_libraries"]], list(probe.LIBRARIES))

    def test_only_exact_always_zero_behavior_is_an_expected_failure(self):
        lines = output_lines(self.libraries, zero=True)
        result = probe.verify_output(render(lines), self.libraries, zero_control=True)
        self.assertEqual(result["expected_failure"], probe.ZERO_FAILURE)
        for failure in ("FAILED pending_reads native_probe: stepped launch exceeded its cycle bound",
                        "FAILED pending_reads native_probe: pending getter changed model state",
                        "FAILED pending_reads native_probe: checked launch retains pending reads",
                        probe.ZERO_FAILURE + " extra", "Segmentation fault", ""):
            with self.subTest(failure=failure), self.assertRaises(ValueError):
                probe.verify_output(render(lines[:3] + [failure]), self.libraries, zero_control=True)

    def test_zero_control_rejects_contexts_passes_duplicates_and_wrong_order(self):
        zero = output_lines(self.libraries, zero=True)
        for lines in (zero + [self.lines[3]], zero + [probe.PASS_LINE], zero + [probe.ZERO_FAILURE],
                      [zero[-1], *zero[:-1]], [*zero[:2], zero[-1], zero[2]], self.lines):
            with self.subTest(lines=lines), self.assertRaises(ValueError):
                probe.verify_output(render(lines), self.libraries, zero_control=True)

    def test_positive_rejects_missing_duplicate_reordered_and_failed_records(self):
        changes = [self.lines[:index] + self.lines[index + 1:] for index in range(len(self.lines))]
        changes += [self.lines + [line] for line in self.lines]
        changes += [[self.lines[-1], *self.lines[:-1]],
                    [*self.lines[:3], self.lines[4], self.lines[3], self.lines[5]],
                    [self.lines[3], *self.lines[:3], *self.lines[4:]],
                    self.lines + [probe.ZERO_FAILURE],
                    self.lines + ["P06_PENDING_EXTRA {}"]]
        for lines in changes:
            with self.subTest(lines=lines), self.assertRaises(ValueError):
                probe.verify_output(render(lines), self.libraries)

    def test_library_identity_and_inventory_are_exact(self):
        for replacement in ({"name": "libsimx.so", "path": "/foreign/libsimx.so"},
                            {"name": "libsimx.so", "path": self.libraries["libsimx.so"], "extra": 0},
                            {"name": "libsimx.so"}, {"name": True, "path": True}):
            lines = self.lines.copy()
            lines[0] = "P06_PENDING_LIBRARY " + json.dumps(replacement)
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                probe.verify_output(render(lines), self.libraries)

    def test_context_schema_requires_each_field_and_exact_integer_types(self):
        baseline = context(7)
        for name in baseline:
            for value in (None, True, 1.0, "1"):
                row = dict(baseline, **{name: value})
                lines = self.lines.copy()
                lines[3] = "P06_PENDING_CONTEXT " + json.dumps(row)
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    probe.verify_output(render(lines), self.libraries)
            row = dict(baseline)
            del row[name]
            lines = self.lines.copy()
            lines[3] = "P06_PENDING_CONTEXT " + json.dumps(row)
            with self.subTest(missing=name), self.assertRaises(ValueError):
                probe.verify_output(render(lines), self.libraries)
        lines = self.lines.copy()
        lines[3] = "P06_PENDING_CONTEXT " + json.dumps(dict(baseline, extra=1))
        with self.assertRaises(ValueError):
            probe.verify_output(render(lines), self.libraries)

    def test_context_observation_invariants(self):
        for change in ({"gp": 0}, {"checked_gp": -1}, {"steps": 0},
                       {"steps": probe.MAX_STEPS + 1}, {"positive_samples": 0},
                       {"positive_samples": 22}, {"max_pending": 0}, {"max_pending": -1},
                       {"max_pending": 1 << 64}, {"readonly_checks": 22},
                       {"stepped_reset_delta": 0}, {"checked_reset_delta": 2},
                       {"pending_final": 1}, {"pending_final": -1}):
            lines = self.lines.copy()
            lines[3] = "P06_PENDING_CONTEXT " + json.dumps(dict(context(7), **change))
            with self.subTest(change=change), self.assertRaises(ValueError):
                probe.verify_output(render(lines), self.libraries)

    def test_duplicate_json_keys_nonfinite_values_and_container_changes_reject(self):
        for body in ('{"gp":7,"gp":7}', '{"gp":NaN}', '[]', 'null'):
            lines = self.lines.copy()
            lines[3] = "P06_PENDING_CONTEXT " + body
            with self.subTest(body=body), self.assertRaises(ValueError):
                probe.verify_output(render(lines), self.libraries)

    def test_log_is_bounded_canonical_text(self):
        valid = render(self.lines)
        for text in (valid[:-1], valid + "\r\n", valid + "\x00\n", "", valid.encode()):
            with self.subTest(text=repr(text[-20:])), self.assertRaises(ValueError):
                probe.verify_output(text, self.libraries)
        with mock.patch.dict(probe.BUDGET, max_log_bytes=len(valid.encode()) - 1):
            with self.assertRaises(ValueError):
                probe.verify_output(valid, self.libraries)


class PendingJsonTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="pending-json-", dir="/tmp")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.path = self.directory / "snapshot.json"

    def test_object_and_list_containers_are_independently_selected(self):
        for value in ({"native_execution": "not_run"}, [{"path": "model"}]):
            self.path.write_text(json.dumps(value))
            self.assertEqual(probe.bounded_json(self.path, expected=type(value)), value)
            with self.assertRaises(ValueError):
                probe.bounded_json(self.path, expected=list if type(value) is dict else dict)

    def test_json_requires_one_complete_value(self):
        for body in ('{"outcome":"pass"},"outcome":"fail"', '[],"extra":1',
                     '{"x":1,"x":2}', '{"x":NaN}', '{} {}', '{', ''):
            self.path.write_text(body)
            with self.subTest(body=body), self.assertRaises(ValueError):
                probe.bounded_json(self.path, expected=list if body.startswith('[') else dict)

    def test_json_size_bound_and_retained_descriptor_identity(self):
        self.path.write_text('{"x":1}')
        descriptor = probe.hash_artifacts(self.directory, [self.path.name])[0]
        self.assertEqual(probe.retained_json(self.directory, descriptor, self.path.name), {"x": 1})
        for changed in (dict(descriptor, path="other.json"), dict(descriptor, sha256="0" * 64),
                        dict(descriptor, size_bytes=0), dict(descriptor, extra=True)):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                probe.retained_json(self.directory, changed, self.path.name)
        with mock.patch.object(probe, "MAX_JSON_BYTES", self.path.stat().st_size - 1):
            with self.assertRaises(ValueError):
                probe.bounded_json(self.path)
        self.path.write_text('{"x":2}')
        with self.assertRaises(ValueError):
            probe.retained_json(self.directory, descriptor, self.path.name)


class ProbeHarness:
    """Retain actual byte identities while substituting only external execution."""

    def __init__(self, data):
        self.data = data

    def __enter__(self):
        self.stack = ExitStack()
        directory = self.stack.enter_context(tempfile.TemporaryDirectory(prefix="pending-host-", dir="/tmp"))
        self.directory = Path(directory)
        self.source, self.build, self.managed, self.host_bin = [
            self.directory / name for name in ("source", "build", "managed", "bin")]
        for path in (self.source, self.build, self.managed, self.host_bin):
            path.mkdir()
        (self.managed / "snapshots").mkdir()
        self.args = SimpleNamespace(source_dir=self.source, build_dir=self.build,
            managed_report=self.managed / "report.json", output_dir=self.directory / "output",
            expected_revision=REVISION, host_bin=self.host_bin)
        self.compiler = self.host_bin / "g++"
        self.compiler.write_text("#!/bin/sh\nexit 97\n")
        self.compiler.chmod(0o700)
        for name in probe.SOURCE_FILES:
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((ROOT / name).read_bytes())
        for name in probe.base.DEPENDENCIES:
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"synthetic dependency: " + name.encode())
        self.build_names = probe.preflight.artifacts(self.build)
        for name in self.build_names:
            path = self.build / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"synthetic build artifact: " + name.encode())
        stamps = [text.replace(str(self.data["source"]), str(self.source)).replace(
            str(self.data["build"]), str(self.build)) for text in self.data["stamps"]]
        self.stamp_paths = [self.build / "sw/runtime/simx_rt_config.stamp",
                            self.build / "sw/runtime/simx_config.stamp",
                            self.build / probe.preflight_contract.APP / "config.stamp"]
        for path, text in zip(self.stamp_paths, stamps):
            path.write_text(text)
        _, records = probe.probe_flags(*stamps, source=self.source, build=self.build, fmt=self.data["fmt"])
        self.checkout = {"revision": REVISION, "tree": "b" * 40, "dirty": False,
                         "changed_paths": [], "untracked_paths": [], "blockers": []}
        self.libraries = {"libsimx.so": str(self.build / "sw/runtime/libsimx.so"),
            "libramulator.so": str(self.source / "third_party/ramulator/libramulator.so"),
            "libramulator-vortex.so": str(self.source / "third_party/ramulator_ext/libramulator-vortex.so")}
        self.variant = {"build_dir": str(self.build), "outcome": "pass", "format": self.data["fmt"],
            "backend": "simx", "compiler_records": records, "expected_loaded_libraries": self.libraries,
            "build_binding_sha256": "c" * 64}
        self.report = {"contract_id": probe.MANAGED_CONTRACT_ID, "state": "finished", "outcome": "pass",
            "native_lifetime_passed": True, "native_preflight_passed": True, "expected_revision": REVISION,
            **dict.fromkeys(probe.preflight_contract.FALSE_CLAIMS, False), "variants": [self.variant]}
        self.write_snapshot("tools_before", "tools-before.json", {"g++": probe.base._file_identity(self.compiler)})
        self.write_snapshot("source_before", "source-before.json", {"checkout": self.checkout,
            "files": probe.hash_artifacts(self.source, probe.SOURCE_FILES)})
        self.write_snapshot("dependencies_before", "dependencies-before.json",
            probe.hash_artifacts(self.source, probe.base.DEPENDENCIES))
        self.bind_artifacts()
        self.calls, self.results = [], {}
        self.after_command = lambda name: None
        self.change_text = lambda name, text: text
        self.stack.enter_context(mock.patch.object(probe, "ROOT", self.source))
        self.stack.enter_context(mock.patch.object(probe, "collect_source", return_value=self.checkout))
        self.stack.enter_context(mock.patch.object(probe.preflight, "loaded_helpers", return_value=[]))
        self.disk = self.stack.enter_context(mock.patch.object(probe.shutil, "disk_usage",
            return_value=SimpleNamespace(free=probe.BUDGET["min_free_bytes"])))
        self.memory = self.stack.enter_context(mock.patch.object(probe, "available_memory_bytes",
            return_value=probe.BUDGET["max_rss_bytes"]))
        self.executor = self.stack.enter_context(mock.patch.object(probe, "run_bounded", side_effect=self.command))
        return self

    def __exit__(self, *args):
        return self.stack.__exit__(*args)

    def write_snapshot(self, key, name, value):
        path = self.managed / "snapshots" / name
        path.write_text(json.dumps(value))
        self.report[key] = probe.hash_artifacts(self.managed, ["snapshots/" + name])[0]

    def bind_artifacts(self):
        self.variant["artifacts_before"] = probe.hash_artifacts(self.build, self.build_names)
        self.variant["artifacts_after"] = copy.deepcopy(self.variant["artifacts_before"])

    def command(self, argv, cwd, environment, logfile, **budget):
        name = logfile.stem
        self.calls.append({"id": name, "argv": argv, "cwd": cwd, "environment": environment, **budget})
        text = "simulated process receipt; no native execution\n"
        if name.startswith("compile-"):
            Path(argv[-1]).write_bytes(b"synthetic executable: " + name.encode())
        elif name.startswith("run-"):
            text = render(output_lines(self.libraries, zero=name == "run-always-zero"))
        logfile.write_text(self.change_text(name, text))
        digest, size = probe._digest(logfile)
        negative = name == "run-always-zero"
        receipt = {"process_started": True, "cleanup_complete": True,
            "outcome": "fail" if negative else "pass", "exit_code": 1 if negative else 0,
            "reason": "nonzero_exit" if negative else None, "log_sha256": digest,
            "log_size_bytes": size, "peak_rss_bytes": 1024, "duration_seconds": 0.001}
        receipt.update(self.results.get(name, {}))
        self.after_command(name)
        return receipt

    def run(self):
        self.args.managed_report.write_text(json.dumps(self.report))
        result = probe.execute(self.args)
        self.saved = json.loads((self.args.output_dir / "report.json").read_text())
        return result


class PendingBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="pending-stamps-", dir="/tmp")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.generated = generate(Path(cls.temporary.name))

    def setUp(self):
        self.data = self.generated["formats"]["fp16"]

    def flags(self, stamps=None, data=None):
        data = data or self.data
        return probe.probe_flags(*(stamps or data["stamps"]),
            source=data["source"], build=data["build"], fmt=data["fmt"])

    def assert_blocked(self, fixture, result, reason):
        self.assertEqual(result["state"], "finished")
        self.assertEqual(result["outcome"], "blocked")
        self.assertFalse(result["native_probe_passed"])
        self.assertEqual(result["native_execution"], "not_run")
        self.assertIn(reason, result["reason"])
        self.assertEqual(result, fixture.saved)
        fixture.executor.assert_not_called()
        for name in probe.preflight_contract.FALSE_CLAIMS:
            self.assertIs(result[name], False)

    def test_generated_flags_preserve_the_model_configuration_in_both_formats(self):
        for fmt, data in self.generated["formats"].items():
            with self.subTest(fmt=fmt):
                flags, records = self.flags(data=data)
                original = shlex.split(data["stamps"][1])
                index = original.index("-MF")
                self.assertEqual(original[index + 1], str(data["build"] / "sw/runtime/simx_config.stamp"))
                original[index:index + 2] = []
                original.remove("-MMD")
                original.remove("-MP")
                self.assertEqual(flags, original)
                self.assertIn("-DSIMX_CHECKED_COUNTERS=1", flags)
                self.assertIn("-DVX_CFG_XLEN=64", flags)
                self.assertEqual([row["role"] for row in records], [role for _, _, role in ROLES])
        self.assertFalse(self.generated["guard_marker"].exists())

    def test_each_original_role_requires_checked_timing_single_worker_configuration(self):
        for outer, inner, role in ROLES:
            for replacement in ("", "-DSIMX_CHECKED_COUNTERS=0", "-DSIMX_CHECKED_COUNTERS=2",
                                "-DSIMX_CHECKED_COUNTERS=1 -DSIMX_MT=2",
                                "-DSIMX_CHECKED_COUNTERS=1 -DSIMX_FUNCTIONAL=1",
                                "-DSIMX_CHECKED_COUNTERS=1 -DP06_PENDING_FORCE_ZERO=1"):
                stamps = change_role(self.data["stamps"], outer, inner,
                    lambda text: text.replace("-DSIMX_CHECKED_COUNTERS=1", replacement))
                with self.subTest(role=role, replacement=replacement), self.assertRaises(ValueError):
                    self.flags(stamps)

    def test_dependency_options_are_not_ambiguous_or_retargeted(self):
        changes = (lambda text: re.sub(r"-MF \S+", "-MF /tmp/foreign.d", text),
                   lambda text: re.sub(r"-MF \S+", "", text),
                   lambda text: text + " -MF /tmp/foreign.d",
                   lambda text: text.replace("-MMD", ""),
                   lambda text: text.replace("-MP", ""),
                   lambda text: text + " -MMD", lambda text: text + " -MP")
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.flags(change_role(self.data["stamps"], 1, 0, change))

    def test_format_source_build_and_link_routes_cannot_be_substituted(self):
        for outer, inner, change in (
                (0, 0, lambda text: text.replace("-DITYPE=fp16", "-DITYPE=bf16")),
                (1, 0, lambda text: text.replace("-DVX_CFG_XLEN=64", "-DVX_CFG_XLEN=32")),
                (1, 0, lambda text: text.replace(str(ROOT / "sim/simx"), "/foreign/simx")),
                (2, 2, lambda text: text + " -lforeign")):
            with self.subTest(outer=outer, inner=inner), self.assertRaises(ValueError):
                self.flags(change_role(self.data["stamps"], outer, inner, change))

    def test_simulated_complete_route_retains_controls_and_frozen_budgets(self):
        with ProbeHarness(self.data) as fixture:
            result = fixture.run()
            self.assertEqual(result["outcome"], "pass", result["reason"])
            self.assertTrue(result["native_probe_passed"])
            self.assertTrue(result["zero_mutation_rejected"])
            self.assertEqual(result["inputs_before"], result["inputs_after"])
            self.assertEqual(result, fixture.saved)
            self.assertEqual([call["id"] for call in fixture.calls],
                ["compiler-version", "compile-native", "run-native", "compile-always-zero", "run-always-zero"])
            for call in fixture.calls:
                for name, value in probe.BUDGET.items():
                    self.assertEqual(call[name], value)
                self.assertEqual(call["timeout_seconds"], 180 if call["id"].startswith("run-") else 120)
                self.assertEqual(call["environment"]["CCACHE_DISABLE"], "1")
                self.assertEqual(call["environment"]["THREADS"], "1")
            positive, negative = fixture.calls[1]["argv"], fixture.calls[3]["argv"]
            self.assertNotIn("-DP06_PENDING_FORCE_ZERO=1", positive)
            self.assertEqual(negative.count("-DP06_PENDING_FORCE_ZERO=1"), 1)
            self.assertEqual(positive[0], str(fixture.compiler))
            self.assertNotIn("-MF", positive)
            self.assertIn(str(fixture.source / probe.PROBE_SOURCE), positive)
            for name in probe.preflight_contract.FALSE_CLAIMS:
                self.assertIs(result[name], False)

    def test_disk_and_memory_shortfalls_block_before_commands(self):
        for resource in ("disk", "memory"):
            with self.subTest(resource=resource), ProbeHarness(self.data) as fixture:
                if resource == "disk":
                    fixture.disk.return_value = SimpleNamespace(free=probe.BUDGET["min_free_bytes"] - 1)
                else:
                    fixture.memory.return_value = probe.BUDGET["max_rss_bytes"] - 1
                self.assert_blocked(fixture, fixture.run(), "probe needs")

    def test_independently_selected_compiler_cannot_follow_a_recorded_foreign_path(self):
        with ProbeHarness(self.data) as fixture:
            foreign = fixture.directory / "recorded-compiler"
            foreign.write_bytes(fixture.compiler.read_bytes())
            foreign.chmod(0o700)
            fixture.write_snapshot("tools_before", "tools-before.json",
                {"g++": probe.base._file_identity(foreign)})
            self.assert_blocked(fixture, fixture.run(), "independently selected compiler differs")

    def test_changed_compiler_bytes_are_rejected_even_at_the_recorded_path(self):
        with ProbeHarness(self.data) as fixture:
            fixture.compiler.write_text("#!/bin/sh\nexit 98\n")
            self.assert_blocked(fixture, fixture.run(), "independently selected compiler differs")

    def test_selected_managed_route_and_false_claims_are_enforced(self):
        mutations = [lambda fixture: fixture.report.update(native_lifetime_passed=False),
                     lambda fixture: fixture.report.update(expected_revision="d" * 40),
                     lambda fixture: fixture.variant.update(backend="rtlsim"),
                     lambda fixture: fixture.variant.update(format="fp32"),
                     lambda fixture: fixture.report["variants"].append(copy.deepcopy(fixture.variant))]
        mutations += [lambda fixture, name=name: fixture.report.update({name: True})
                      for name in probe.preflight_contract.FALSE_CLAIMS]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index), ProbeHarness(self.data) as fixture:
                mutate(fixture)
                self.assert_blocked(fixture, fixture.run(), "")

    def test_changed_model_source_and_dependency_bytes_reject_before_execution(self):
        for target, reason in (("build", "model products or generated inputs"),
                               ("source", "current source bytes"), ("dependency", "model dependencies")):
            with self.subTest(target=target), ProbeHarness(self.data) as fixture:
                path = {"build": fixture.build / "sw/runtime/libsimx.so",
                        "source": fixture.source / probe.PROBE_SOURCE,
                        "dependency": fixture.source / probe.base.DEPENDENCIES[0]}[target]
                path.write_bytes(path.read_bytes() + b"changed")
                self.assert_blocked(fixture, fixture.run(), reason)

    def test_model_stamp_guard_is_rechecked_after_artifact_rehash(self):
        with ProbeHarness(self.data) as fixture:
            path = fixture.stamp_paths[1]
            path.write_text(path.read_text().replace("-DSIMX_CHECKED_COUNTERS=1", "-DSIMX_CHECKED_COUNTERS=0"))
            fixture.bind_artifacts()
            self.assert_blocked(fixture, fixture.run(), "checked-counter")

    def test_recorded_model_configuration_must_match_the_live_stamp(self):
        with ProbeHarness(self.data) as fixture:
            fixture.variant["compiler_records"][1]["configuration"]["SIMX_CHECKED_COUNTERS"] = "0"
            self.assert_blocked(fixture, fixture.run(), "revalidated compiler records differ")

    def test_expected_libraries_must_use_the_fixed_live_build_paths(self):
        with ProbeHarness(self.data) as fixture:
            fixture.variant["expected_loaded_libraries"] = dict(fixture.libraries, **{"libsimx.so": "/foreign/libsimx.so"})
            self.assert_blocked(fixture, fixture.run(), "fixed build route")

    def test_zero_control_receipt_does_not_accept_arbitrary_process_failure(self):
        for changed in ({"exit_code": -9}, {"reason": "timeout"}, {"outcome": "pass", "exit_code": 0},
                        {"cleanup_complete": False}, {"process_started": False}):
            with self.subTest(changed=changed), ProbeHarness(self.data) as fixture:
                fixture.results["run-always-zero"] = changed
                result = fixture.run()
                self.assertEqual(result["outcome"], "fail")
                self.assertFalse(result["native_probe_passed"])
                self.assertFalse(result["zero_mutation_rejected"])
                self.assertEqual(result, fixture.saved)

    def test_zero_control_receipt_and_exact_output_must_both_match(self):
        with ProbeHarness(self.data) as fixture:
            fixture.change_text = lambda name, text: text.replace(probe.ZERO_FAILURE,
                "FAILED pending_reads native_probe: unexpected nonstandard exception")
            result = fixture.run()
            self.assertEqual(result["outcome"], "fail")
            self.assertIn("required behavioral assertion", result["reason"])
            self.assertFalse(result["native_probe_passed"])
            self.assertFalse(result["zero_mutation_rejected"])

    def test_failed_command_preserves_input_stability_failure(self):
        with ProbeHarness(self.data) as fixture:
            fixture.results["run-native"] = {"outcome": "fail", "exit_code": 1, "reason": "nonzero_exit"}
            def change(name):
                if name == "run-native":
                    path = fixture.build / "sw/runtime/libsimx.so"
                    path.write_bytes(path.read_bytes() + b"changed")
            fixture.after_command = change
            result = fixture.run()
            self.assertEqual(result["outcome"], "fail")
            self.assertIn("run-native: command failed", result["reason"])
            self.assertIn("probe input stability failed", result["failures"])
            self.assertNotEqual(result["inputs_before"], result["inputs_after"])
            self.assertFalse(result["native_probe_passed"])
            self.assertEqual(result, fixture.saved)

    def test_changed_probe_executable_during_run_cannot_pass(self):
        with ProbeHarness(self.data) as fixture:
            def change(name):
                if name == "run-native":
                    (fixture.args.output_dir / "products/pending-reads-native").write_bytes(b"changed")
            fixture.after_command = change
            result = fixture.run()
            self.assertEqual(result["outcome"], "fail")
            self.assertIn("probe executable changed", result["reason"])
            self.assertFalse(result["native_probe_passed"])

    def test_log_digest_mismatch_fails_before_observations_are_accepted(self):
        with ProbeHarness(self.data) as fixture:
            fixture.results["run-native"] = {"log_sha256": "f" * 64}
            result = fixture.run()
            self.assertEqual(result["outcome"], "fail")
            self.assertIn("retained log changed", result["reason"])
            self.assertFalse(result["native_probe_passed"])


if __name__ == "__main__":
    unittest.main()
