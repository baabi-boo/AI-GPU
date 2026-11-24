# SPDX-License-Identifier: Apache-2.0
"""Advisory aggregation and resource controls with tiny synthetic observations."""

import argparse
from contextlib import contextmanager, ExitStack, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import p06_dependency_contract as dependency
import p06_qualified_warm_readiness as readiness


REVISION = "a" * 40
CATEGORIES = ("paths", "source", "contracts", "originals", "parts",
              "dependencies", "host", "resources")


class ReadinessFixture:
    def __enter__(self):
        self.stack = ExitStack()
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(
            prefix="p06-readiness-synthetic-")))
        self.inputs = {name: self.root / directory for name, directory in (
            ("source_dir", "source"), ("workspace_dir", "workspace"),
            ("archive_root", "archives"), ("dependency_repositories", "repositories"),
            ("host_bin", "host-bin"))}
        for name, path in self.inputs.items():
            if name != "workspace_dir":
                path.mkdir()
        self.inputs.update(expected_revision=REVISION,
                           diagnostic_archive=self.root / "diagnostic.zip",
                           control_archive=self.root / "control.zip")
        self.roots = {name: value for name, value in self.inputs.items()
                      if name not in ("expected_revision", "diagnostic_archive", "control_archive")}
        return self

    def __exit__(self, *args):
        return self.stack.__exit__(*args)

    def argv(self):
        return [item for name, value in self.inputs.items()
                for item in ("--" + name.replace("_", "-"), str(value))]

    def observation(self, category):
        def inspect(*args):
            args[-1].add("synthetic." + category, "observed",
                         observed={"scope": "synthetic-aggregation-only"},
                         reason="synthetic category observation")
            if category == "paths":
                return self.roots
            if category == "contracts":
                return {"scope": "synthetic-aggregation-only"}
        return inspect

    @contextmanager
    def screen(self, *, real=(), overrides=None):
        with ExitStack() as stack:
            mocked = {}
            for category in CATEGORIES:
                if category not in real:
                    operation = (overrides or {}).get(category, self.observation(category))
                    mocked[category] = stack.enter_context(mock.patch.object(
                        readiness, "_inspect_" + category, side_effect=operation))
            yield mocked


class AdvisoryAssertions:
    def assert_scope(self, report):
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["contract_id"], "p06-qualified-warm-readiness-v1")
        self.assertEqual(report["native_execution"], "not_run")
        for name in (*dependency.FALSE_CLAIMS, "counter_qualification_passed",
                     "qualified_warm_passed"):
            self.assertIs(report[name], False, name)
        self.assertEqual(report["budget"], dependency.BUDGET)
        self.assertTrue(report["limitations"])
        self.assertEqual(set(report["outside_screen"]), {
            "full_historical_replay", "tool_extraction", "dependency_compilation",
            "native_build_and_process_admission", "installed_native_tool_verification",
            "runtime_host_support", "governance_completion", "provider_transport"})

    def assert_advisory(self, report):
        self.assert_scope(report)
        rows = report["checks"]
        self.assertEqual(len(rows), len({row["id"] for row in rows}))
        for row in rows:
            self.assertEqual(set(row), {"id", "status", "observed", "expected", "reason"})
            self.assertIn(row["status"], ("observed", "blocked", "unknown", "not_checked"))
            self.assertIsInstance(row["reason"], str)
            self.assertLessEqual(len(row["reason"]), 512)
        self.assertEqual(report["blockers"], [row["id"] for row in rows
                                              if row["status"] == "blocked"])
        self.assertEqual(report["incomplete_checks"], [row["id"] for row in rows
                           if row["status"] in ("unknown", "not_checked")])
        json.dumps(report, allow_nan=False)


class ReadinessAggregationTests(AdvisoryAssertions, unittest.TestCase):
    def test_independent_failures_and_a_raising_observation_are_aggregated(self):
        def unavailable_source(*args):
            def fail():
                raise RuntimeError("synthetic unavailable source observer\n" + "detail " * 100)
            args[-1].run("synthetic.source.failure", fail)

        def blocked_parts(*args):
            args[-1].add("synthetic.parts.failure", "blocked",
                         reason="synthetic archive observation failed")

        def incomplete_resources(*args):
            args[-1].add("synthetic.resources.unknown", "unknown",
                         reason="synthetic capacity observation unavailable")

        with ReadinessFixture() as fixture, fixture.screen(overrides={
                "source": unavailable_source, "parts": blocked_parts,
                "resources": incomplete_resources}) as categories:
            report = readiness.inspect_readiness(fixture.inputs)
            for operation in categories.values():
                operation.assert_called_once()
        self.assert_advisory(report)
        self.assertEqual(report["outcome"], "blocked")
        self.assertEqual(report["exit_code"], 1)
        self.assertEqual(report["blockers"], ["synthetic.source.failure", "synthetic.parts.failure"])
        self.assertEqual(report["incomplete_checks"], ["synthetic.resources.unknown"])
        failure = next(row for row in report["checks"] if row["id"] == "synthetic.source.failure")
        self.assertNotIn("\n", failure["reason"])
        self.assertEqual({row["id"] for row in report["checks"]}, {
            "synthetic.paths", "synthetic.source.failure", "synthetic.contracts",
            "synthetic.originals", "synthetic.parts.failure", "synthetic.dependencies",
            "synthetic.host", "synthetic.resources.unknown"})

    def test_category_exception_keeps_dependent_skips_and_independent_observations(self):
        def broken_paths(*_):
            raise RuntimeError("synthetic path observer failure")

        with ReadinessFixture() as fixture, fixture.screen(
                real=("resources",), overrides={"paths": broken_paths}) as categories, \
                mock.patch.object(readiness.preflight, "available_memory_bytes",
                                  return_value=dependency.BUDGET["max_rss_bytes"]), \
                mock.patch.object(readiness.shutil, "disk_usage") as disk:
            report = readiness.inspect_readiness(fixture.inputs)
            for operation in categories.values():
                operation.assert_called_once()
            disk.assert_not_called()
        self.assert_advisory(report)
        rows = {row["id"]: row for row in report["checks"]}
        self.assertEqual(report["blockers"], ["category.paths"])
        for name in ("source", "workspace"):
            row = rows["resources.disk." + name]
            self.assertEqual(row["status"], "not_checked")
            self.assertIsNone(row["observed"])
        self.assertEqual(rows["resources.host_memory"]["status"], "observed")
        self.assertEqual(rows["resources.cgroup_capacity"]["status"], "unknown")
        self.assertEqual(report["outcome"], "blocked")
        self.assertEqual(report["exit_code"], 1)

    def test_synthetic_outcomes_preserve_all_false_claims_and_separate_incompleteness(self):
        for status, outcome, code in (("observed", "no_blockers_observed", 0),
                ("blocked", "blocked", 1), ("unknown", "incomplete", 1),
                ("not_checked", "incomplete", 1)):
            with self.subTest(status=status), ReadinessFixture() as fixture:
                def resource_status(*args):
                    args[-1].add("synthetic.resources", status,
                                 reason="synthetic outcome branch only")
                with fixture.screen(overrides={"resources": resource_status}):
                    report = readiness.inspect_readiness(fixture.inputs)
                self.assert_advisory(report)
                self.assertEqual((report["outcome"], report["exit_code"]), (outcome, code))

    def test_namespace_and_mapping_use_the_same_required_inputs(self):
        with ReadinessFixture() as fixture, fixture.screen():
            mapping = readiness.inspect_readiness(fixture.inputs)
            namespace = readiness.inspect_readiness(argparse.Namespace(**fixture.inputs))
        self.assertEqual(mapping, namespace)
        self.assert_advisory(mapping)

    def test_each_missing_input_is_an_invalid_invocation(self):
        with ReadinessFixture() as fixture, fixture.screen() as categories:
            for name in fixture.inputs:
                inputs = dict(fixture.inputs)
                del inputs[name]
                with self.subTest(name=name), self.assertRaises(ValueError):
                    readiness.inspect_readiness(inputs)
            for operation in categories.values():
                operation.assert_not_called()

    def test_invalid_revision_or_path_types_cannot_start_observation(self):
        with ReadinessFixture() as fixture, fixture.screen() as categories:
            for name, values in (("expected_revision", ("", "a" * 39, "g" * 40,
                                                        "A" * 40, 123, None)),
                                 ("workspace_dir", (None, False, 123, [], {}))):
                for value in values:
                    inputs = dict(fixture.inputs, **{name: value})
                    with self.subTest(name=name, value=repr(value)), self.assertRaises(ValueError):
                        readiness.inspect_readiness(inputs)
            for operation in categories.values():
                operation.assert_not_called()


class ReadinessResourceTests(AdvisoryAssertions, unittest.TestCase):
    def inspect(self, fixture, *, disk_samples=None, memory=None):
        if disk_samples is None:
            disk_samples = [SimpleNamespace(free=dependency.BUDGET["min_free_bytes"])] * 2
        memory_arguments = ({"side_effect": memory} if isinstance(memory, Exception)
                            else {"return_value": memory})
        with fixture.screen(real=("paths", "resources")), \
                mock.patch.object(readiness, "ROOT", fixture.inputs["source_dir"]), \
                mock.patch.object(readiness.shutil, "disk_usage", side_effect=disk_samples) as disk, \
                mock.patch.object(readiness.preflight, "available_memory_bytes", **memory_arguments):
            report = readiness.inspect_readiness(fixture.inputs)
        self.assert_advisory(report)
        return report, disk.call_args_list

    def test_planned_workspace_samples_its_existing_parent_without_double_counting(self):
        with ReadinessFixture() as fixture:
            report, calls = self.inspect(fixture, memory=dependency.BUDGET["max_rss_bytes"])
            rows = {row["id"]: row for row in report["checks"]}
            self.assertEqual(calls, [mock.call(fixture.inputs["source_dir"]), mock.call(fixture.root)])
            workspace = rows["workspace.state"]["observed"]
            self.assertEqual(workspace["state"], "planned")
            self.assertEqual(workspace["observed_at"], str(fixture.root))
            self.assertFalse(fixture.inputs["workspace_dir"].exists())
            source = rows["resources.disk.source"]
            target = rows["resources.disk.workspace"]
            for row in (source, target):
                self.assertEqual(row["status"], "observed")
                self.assertEqual(row["observed"]["free_bytes"], dependency.BUDGET["min_free_bytes"])
                self.assertEqual(row["observed"]["reserve_margin_bytes"], 0)
            self.assertEqual(target["observed"]["path"], str(fixture.inputs["workspace_dir"]))
            self.assertEqual(target["observed"]["observed_at"], str(fixture.root))
            self.assertEqual(source["observed"]["filesystem"], target["observed"]["filesystem"])
            self.assertIsNone(source["observed"]["shares_filesystem_with"])
            self.assertEqual(target["observed"]["shares_filesystem_with"], "source")
        self.assertEqual(report["blockers"], [])
        self.assertEqual(report["incomplete_checks"], ["resources.cgroup_capacity"])
        self.assertEqual((report["outcome"], report["exit_code"]), ("incomplete", 1))

    def test_existing_workspace_is_sampled_directly_and_keeps_existing_contents(self):
        with ReadinessFixture() as fixture:
            workspace = fixture.inputs["workspace_dir"]
            workspace.mkdir()
            note = workspace / "retained-note.txt"
            note.write_bytes(b"unrelated existing user content")
            report, calls = self.inspect(fixture, memory=dependency.BUDGET["max_rss_bytes"])
            rows = {row["id"]: row for row in report["checks"]}
            self.assertEqual(calls, [mock.call(fixture.inputs["source_dir"]), mock.call(workspace)])
            self.assertEqual(rows["workspace.state"]["observed"]["state"], "existing")
            self.assertEqual(rows["resources.disk.workspace"]["observed"]["observed_at"], str(workspace))
            self.assertEqual(note.read_bytes(), b"unrelated existing user content")
            self.assertEqual(list(workspace.iterdir()), [note])
        self.assertEqual(report["blockers"], [])

    def test_absent_workspace_parent_leaves_dependent_disk_unchecked(self):
        with ReadinessFixture() as fixture:
            fixture.inputs["workspace_dir"] = fixture.root / "absent-parent" / "workspace"
            report, calls = self.inspect(fixture, memory=dependency.BUDGET["max_rss_bytes"])
            rows = {row["id"]: row for row in report["checks"]}
            self.assertEqual(calls, [mock.call(fixture.inputs["source_dir"])])
            self.assertFalse((fixture.root / "absent-parent").exists())
        self.assertEqual(rows["paths.workspace_dir"]["status"], "blocked")
        self.assertEqual(rows["workspace.state"]["status"], "not_checked")
        self.assertEqual(rows["resources.disk.workspace"]["status"], "not_checked")
        self.assertEqual(rows["resources.disk.source"]["status"], "observed")
        self.assertEqual(rows["resources.host_memory"]["status"], "observed")

    def test_unknown_or_invalid_host_memory_is_not_reported_as_zero_capacity(self):
        for value in (None, -1, True, False, 1.5, "4294967296", OSError("synthetic unavailable memory")):
            with self.subTest(value=repr(value)), ReadinessFixture() as fixture:
                report, _ = self.inspect(fixture, memory=value)
            rows = {row["id"]: row for row in report["checks"]}
            memory = rows["resources.host_memory"]
            self.assertEqual(memory["status"], "unknown")
            self.assertIsNone(memory["observed"])
            self.assertEqual(memory["expected"], dependency.BUDGET["max_rss_bytes"])
            self.assertEqual(report["blockers"], [])
            self.assertEqual(report["incomplete_checks"], ["resources.host_memory", "resources.cgroup_capacity"])
            self.assertEqual(report["outcome"], "incomplete")

    def test_known_host_memory_is_compared_against_the_unchanged_boundary(self):
        minimum = dependency.BUDGET["max_rss_bytes"]
        for value, status in ((0, "blocked"), (minimum - 1, "blocked"),
                              (minimum, "observed"), (minimum + 1, "observed")):
            with self.subTest(value=value), ReadinessFixture() as fixture:
                report, _ = self.inspect(fixture, memory=value)
            row = next(row for row in report["checks"] if row["id"] == "resources.host_memory")
            self.assertEqual((row["status"], row["observed"], row["expected"]), (status, value, minimum))
            self.assertEqual(report["blockers"], ["resources.host_memory"] if status == "blocked" else [])
            self.assertEqual(report["incomplete_checks"], ["resources.cgroup_capacity"])
            self.assertEqual(report["exit_code"], 1)

    def test_unknown_disk_observation_does_not_hide_the_other_filesystem_or_memory(self):
        for name, index in (("source", 0), ("workspace", 1)):
            for value in (None, -1, True, "16106127360", OSError("synthetic unavailable filesystem")):
                with self.subTest(name=name, value=repr(value)), ReadinessFixture() as fixture:
                    samples = [SimpleNamespace(free=dependency.BUDGET["min_free_bytes"])] * 2
                    samples[index] = value if isinstance(value, Exception) else SimpleNamespace(free=value)
                    report, calls = self.inspect(fixture, disk_samples=samples,
                                                memory=dependency.BUDGET["max_rss_bytes"])
                rows = {row["id"]: row for row in report["checks"]}
                self.assertEqual(len(calls), 2)
                unknown = "resources.disk." + name
                other = "resources.disk." + ("workspace" if name == "source" else "source")
                self.assertEqual(rows[unknown]["status"], "unknown")
                self.assertIsNone(rows[unknown]["observed"])
                self.assertEqual(rows[other]["status"], "observed")
                self.assertEqual(rows["resources.host_memory"]["status"], "observed")
                self.assertEqual(report["blockers"], [])
                self.assertEqual(report["incomplete_checks"], [unknown, "resources.cgroup_capacity"])

    def test_known_disk_capacity_keeps_the_exact_signed_reserve_margin(self):
        minimum = dependency.BUDGET["min_free_bytes"]
        for difference in (-1, 0, 1):
            with self.subTest(difference=difference), ReadinessFixture() as fixture:
                report, _ = self.inspect(fixture,
                    disk_samples=[SimpleNamespace(free=minimum + difference)] * 2,
                    memory=dependency.BUDGET["max_rss_bytes"])
            rows = {row["id"]: row for row in report["checks"]}
            for name in ("source", "workspace"):
                row = rows["resources.disk." + name]
                self.assertEqual(row["status"], "blocked" if difference < 0 else "observed")
                self.assertEqual(row["observed"]["reserve_margin_bytes"], difference)
                self.assertEqual(row["expected"], minimum)
            self.assertEqual(report["blockers"],
                ["resources.disk.source", "resources.disk.workspace"] if difference < 0 else [])
            self.assertEqual(report["incomplete_checks"], ["resources.cgroup_capacity"])


class ReadinessCliTests(AdvisoryAssertions, unittest.TestCase):
    def invoke(self, argv):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            code = readiness.main(argv)
        return code, output.getvalue(), errors.getvalue()

    def test_parser_selects_all_explicit_inputs(self):
        with ReadinessFixture() as fixture:
            args = readiness.argument_parser().parse_args(fixture.argv())
            for name, expected in fixture.inputs.items():
                self.assertEqual(str(getattr(args, name)), str(expected), name)

    def test_missing_inputs_and_unavailable_bypass_flags_exit_two(self):
        with ReadinessFixture() as fixture:
            invocations = [[], *[fixture.argv() + [flag, value] for flag, value in (
                ("--output-dir", str(fixture.root / "output")),
                ("--min-free-bytes", "0"), ("--jobs", "99"),
                ("--counter-qualification-sha256", "0" * 64), ("--skip", "resources"))]]
            for argv in invocations:
                with self.subTest(extra=argv[-2:]), redirect_stderr(io.StringIO()), \
                        self.assertRaises(SystemExit) as failure:
                    readiness.argument_parser().parse_args(argv)
                self.assertEqual(failure.exception.code, 2)
            self.assertFalse((fixture.root / "output").exists())

    def test_main_serializes_synthetic_outcomes_and_uses_their_exit_codes(self):
        for status, outcome, code in (("observed", "no_blockers_observed", 0),
                ("blocked", "blocked", 1), ("unknown", "incomplete", 1)):
            with self.subTest(status=status), ReadinessFixture() as fixture:
                def observation(*args):
                    args[-1].add("synthetic.resources", status,
                                 reason="synthetic CLI outcome only")
                with fixture.screen(overrides={"resources": observation}):
                    result, output, errors = self.invoke(fixture.argv())
                self.assertEqual(result, code)
                report = json.loads(output)
                self.assert_advisory(report)
                self.assertEqual((report["outcome"], report["exit_code"]), (outcome, code))
                self.assertEqual(report["native_execution"], "not_run")
                self.assertTrue(all(report[name] is False for name in dependency.FALSE_CLAIMS))
                self.assertEqual(errors, "")

    def test_invalid_revision_returns_one_json_error_without_observation(self):
        with ReadinessFixture() as fixture, fixture.screen() as categories:
            fixture.inputs["expected_revision"] = "not-a-reviewed-commit"
            code, output, errors = self.invoke(fixture.argv())
            for operation in categories.values():
                operation.assert_not_called()
        report = json.loads(output)
        self.assertEqual((code, report["exit_code"], report["outcome"]), (2, 2, "error"))
        self.assert_scope(report)
        self.assertIn("expected_revision", report["reason"])
        self.assertEqual(errors, "")

    def test_observation_and_serialization_failures_return_one_json_error(self):
        for arguments in ({"side_effect": RuntimeError("synthetic report failure")},
                          {"return_value": {"unserializable": object()}},
                          {"return_value": {"nonfinite": float("nan")}}):
            with self.subTest(arguments=arguments), ReadinessFixture() as fixture, \
                    mock.patch.object(readiness, "inspect_readiness", **arguments):
                code, output, errors = self.invoke(fixture.argv())
            report = json.loads(output)
            self.assertEqual((code, report["exit_code"], report["outcome"]), (2, 2, "error"))
            self.assert_scope(report)
            self.assertEqual(errors, "")

    def test_unwritable_stdout_returns_exit_two_without_a_report_retry(self):
        with ReadinessFixture() as fixture, fixture.screen(), \
                mock.patch("builtins.print", side_effect=OSError("synthetic closed stdout")) as output:
            code = readiness.main(fixture.argv())
            output.assert_called_once()
        self.assertEqual(code, 2)
        self.assert_advisory(json.loads(output.call_args.args[0]))


class ReadinessSideEffectTests(AdvisoryAssertions, unittest.TestCase):
    @staticmethod
    def snapshot(root):
        return {str(path.relative_to(root)): (path.stat().st_mode,
                    path.read_bytes() if path.is_file() else None)
                for path in root.rglob("*")}

    def test_actual_inspection_cannot_prepare_build_download_or_mutate_inputs(self):
        with ReadinessFixture() as fixture:
            source = fixture.inputs["source_dir"]
            (source / ".git").mkdir()
            (source / ".git" / "index").write_bytes(b"synthetic index sentinel")
            (source / "tracked.txt").write_bytes(b"synthetic tracked input")
            fixture.inputs["diagnostic_archive"].write_bytes(b"synthetic diagnostic original")
            fixture.inputs["control_archive"].write_bytes(b"synthetic control original")
            before = self.snapshot(fixture.root)
            with ExitStack() as stack:
                stack.enter_context(mock.patch.object(readiness, "ROOT", source))
                stack.enter_context(mock.patch.object(readiness.hwemu_source, "collect_source",
                    side_effect=ValueError("synthetic unavailable Git observation")))
                stack.enter_context(mock.patch.object(readiness.sources, "_DependencyGitObjects",
                    side_effect=ValueError("synthetic unavailable dependency object")))
                stack.enter_context(mock.patch.object(readiness, "_tool_identity",
                    side_effect=ValueError("synthetic unavailable executable identity")))
                stack.enter_context(mock.patch.object(readiness.shutil, "which", return_value=None))
                stack.enter_context(mock.patch.object(readiness.admission, "reader_sources", return_value=[]))
                stack.enter_context(mock.patch.object(readiness.preflight, "available_memory_bytes",
                    return_value=dependency.BUDGET["max_rss_bytes"]))
                stack.enter_context(mock.patch.object(readiness.shutil, "disk_usage",
                    return_value=SimpleNamespace(free=dependency.BUDGET["min_free_bytes"])))
                guards = {name: stack.enter_context(mock.patch(target,
                    side_effect=AssertionError("unexpected " + name))) for name, target in (
                    ("process", "subprocess.Popen"), ("network", "socket.socket.connect"),
                    ("download", "urllib.request.urlopen"),
                    ("preparation", "p06_dependency_local_prepare.prepare"),
                    ("provision", "p06_local_toolchain.provision"),
                    ("extraction", "p06_local_toolchain._extract"),
                    ("dependency build", "p06_dependency_build.build"),
                    ("native execution", "p06_managed_preflight_execute.execute"),
                    ("directory creation", "os.mkdir"), ("file write", "pathlib.Path.write_bytes"),
                    ("text write", "pathlib.Path.write_text"), ("file removal", "pathlib.Path.unlink"))}
                report = readiness.inspect_readiness(fixture.inputs)
                for guard in guards.values():
                    guard.assert_not_called()
            self.assertEqual(self.snapshot(fixture.root), before)
            self.assertFalse(os.path.lexists(fixture.inputs["workspace_dir"]))
        self.assert_advisory(report)
        self.assertEqual(report["outcome"], "blocked")
        self.assertEqual(report["exit_code"], 1)


if __name__ == "__main__":
    unittest.main()
