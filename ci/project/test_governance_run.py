# SPDX-License-Identifier: Apache-2.0
"""Synthetic unittest executions exercise strict governance outcome accounting."""

import gc
import io
import sys
import types
import unittest
from unittest import mock
import weakref

import governance_run


def _case(identity, body=None):
    class Case(unittest.TestCase):
        def id(self):
            return identity

        def runTest(self):
            if body is not None:
                body(self)

    return Case()


class GovernanceRunTests(unittest.TestCase):
    def run_synthetic(self, suite, **options):
        stream = io.StringIO()
        events = []
        result = governance_run.run_suite(
            suite, stream=stream, event_sink=events.append, **options)
        self.assertIs(result.summary["strict_success"], result.strict_success)
        self.assertEqual(result.summary["event_count"], len(events))
        self.assertEqual([event["sequence"] for event in events],
                         list(range(1, len(events) + 1)))
        return result, events, stream.getvalue()

    def assert_incomplete(self, result):
        self.assertFalse(result.strict_success)
        self.assertFalse(result.summary["execution_completed"])
        self.assertFalse(result.summary["coverage_complete"])

    def test_collection_preserves_nested_order_without_consuming_the_suite(self):
        executed = []
        suite = unittest.TestSuite([
            unittest.TestSuite([
                _case("fixture.Order.test_zulu", lambda _: executed.append("zulu")),
                unittest.TestSuite([
                    _case("fixture.Order.test_alpha", lambda _: executed.append("alpha")),
                ]),
            ]),
            _case("fixture.Order.test_middle", lambda _: executed.append("middle")),
        ])
        expected = ["fixture.Order.test_zulu", "fixture.Order.test_alpha",
                    "fixture.Order.test_middle"]

        self.assertEqual(governance_run.collect_test_ids(suite), expected)
        self.assertEqual(governance_run.collect_test_ids(suite), expected)
        self.assertEqual(suite.countTestCases(), 3)
        self.assertEqual(executed, [])
        result, events, _ = self.run_synthetic(suite)

        self.assertTrue(result.strict_success)
        self.assertEqual(executed, ["zulu", "alpha", "middle"])
        self.assertEqual([event["test_id"] for event in events
                          if event["event"] == "test_start"], expected)

    def test_all_success_has_complete_ordered_start_outcome_stop_events(self):
        result, events, output = self.run_synthetic(unittest.TestSuite([
            _case("fixture.Success.test_first"),
            _case("fixture.Success.test_second"),
        ]))

        self.assertTrue(result.strict_success)
        self.assertTrue(result.summary["execution_completed"])
        self.assertTrue(result.summary["coverage_complete"])
        self.assertTrue(result.summary["order_matches"])
        self.assertTrue(result.summary["counts_match"])
        self.assertEqual(result.summary["discovered_count"], 2)
        self.assertEqual(result.summary["tests_run"], 2)
        self.assertEqual(result.summary["started_count"], 2)
        self.assertEqual(result.summary["stopped_count"], 2)
        self.assertEqual(result.summary["outcome_counts"], {"success": 2})
        self.assertEqual(result.summary["non_successful_ids"], [])
        self.assertEqual(result.summary["fixture_counts"], {})
        self.assertEqual(result.summary["subtest_counts"], {})
        self.assertEqual(result.summary["loader_errors"], [])
        self.assertIsNone(result.summary["abort"])
        self.assertEqual([(event["event"], event["test_id"]) for event in events], [
            ("test_start", "fixture.Success.test_first"),
            ("test_outcome", "fixture.Success.test_first"),
            ("test_stop", "fixture.Success.test_first"),
            ("test_start", "fixture.Success.test_second"),
            ("test_outcome", "fixture.Success.test_second"),
            ("test_stop", "fixture.Success.test_second"),
        ])
        self.assertIn("Ran 2 tests", output)

    def test_successful_subtests_preserve_one_successful_parent_outcome(self):
        def body(case):
            for value in (1, 2):
                with case.subTest(value=value):
                    case.assertGreater(value, 0)

        result, events, _ = self.run_synthetic(unittest.TestSuite([
            _case("fixture.Subtests.test_success", body),
        ]))

        self.assertTrue(result.strict_success)
        self.assertEqual(result.summary["tests_run"], 1)
        self.assertEqual(result.summary["outcome_counts"], {"success": 1})
        self.assertEqual(result.summary["subtest_counts"], {"success": 2})
        self.assertEqual([event["test_id"] for event in events
                          if event["event"] == "subtest_outcome"],
                         ["fixture.Subtests.test_success"] * 2)

    def test_changed_execution_order_rejects_otherwise_complete_success(self):
        executed = []

        class ReversedSuite(unittest.TestSuite):
            def run(self, result, debug=False):
                return unittest.TestSuite(reversed(list(self))).run(result, debug)

        suite = ReversedSuite([
            _case("fixture.Order.test_first", lambda _: executed.append("first")),
            _case("fixture.Order.test_second", lambda _: executed.append("second")),
        ])
        result, _, _ = self.run_synthetic(suite)

        self.assertEqual(executed, ["second", "first"])
        self.assertTrue(result.summary["execution_completed"])
        self.assertTrue(result.summary["coverage_complete"])
        self.assertTrue(result.summary["counts_match"])
        self.assertEqual(result.summary["outcome_counts"], {"success": 2})
        self.assertFalse(result.summary["order_matches"])
        self.assertFalse(result.strict_success)

    def test_failures_and_errors_are_distinct_and_do_not_hide_later_tests(self):
        executed = []

        def failure(case):
            executed.append("failure")
            case.fail("synthetic assertion failure")

        def error(_):
            executed.append("error")
            raise RuntimeError("synthetic runtime error")

        result, events, output = self.run_synthetic(unittest.TestSuite([
            _case("fixture.Outcomes.test_failure", failure),
            _case("fixture.Outcomes.test_error", error),
            _case("fixture.Outcomes.test_after", lambda _: executed.append("after")),
        ]))

        self.assertEqual(executed, ["failure", "error", "after"])
        self.assertFalse(result.strict_success)
        self.assertTrue(result.summary["execution_completed"])
        self.assertTrue(result.summary["coverage_complete"])
        self.assertEqual(result.summary["tests_run"], 3)
        self.assertEqual(result.summary["outcome_counts"],
                         {"failure": 1, "error": 1, "success": 1})
        self.assertEqual(result.summary["non_successful_ids"],
                         ["fixture.Outcomes.test_error", "fixture.Outcomes.test_failure"])
        self.assertEqual([event["outcome"] for event in events
                          if event["event"] == "test_outcome"],
                         ["failure", "error", "success"])
        self.assertIn("synthetic assertion failure", output)
        self.assertIn("synthetic runtime error", output)

    def test_skipped_method_cannot_pass_even_when_unittest_reports_success(self):
        executed = []

        class Case(unittest.TestCase):
            @unittest.skip("synthetic method skip")
            def test_body(self):
                executed.append("body")

        case = Case("test_body")
        identity = case.id()
        result, events, _ = self.run_synthetic(unittest.TestSuite([case]))

        self.assertEqual(executed, [])
        self.assertTrue(result.wasSuccessful())
        self.assertFalse(result.strict_success)
        self.assertTrue(result.summary["coverage_complete"])
        self.assertEqual(result.summary["tests_run"], 1)
        self.assertEqual(result.summary["outcome_counts"], {"skip": 1})
        self.assertEqual(result.summary["non_successful_ids"], [identity])
        outcome = next(event for event in events if event["event"] == "test_outcome")
        self.assertEqual(outcome["reason"], "synthetic method skip")

    def test_runtime_skip_records_entered_body_without_claiming_success(self):
        executed = []

        def body(case):
            executed.append("entered")
            case.skipTest("missing synthetic prerequisite")
            executed.append("finished")

        result, _, _ = self.run_synthetic(unittest.TestSuite([
            _case("fixture.Skip.test_runtime", body),
        ]))

        self.assertEqual(executed, ["entered"])
        self.assertFalse(result.strict_success)
        self.assertEqual(result.summary["outcome_counts"], {"skip": 1})
        self.assertEqual(result.summary["non_successful_ids"], ["fixture.Skip.test_runtime"])

    def test_class_setup_skip_leaves_bodies_missing_and_runs_other_classes(self):
        executed = []

        class Case(unittest.TestCase):
            @classmethod
            def setUpClass(cls):
                raise unittest.SkipTest("synthetic class prerequisite")

            def test_first(self):
                executed.append("first")

            def test_second(self):
                executed.append("second")

        hidden = [Case("test_first"), Case("test_second")]
        hidden_ids = sorted(case.id() for case in hidden)
        suite = unittest.TestSuite(hidden + [
            _case("fixture.Control.test_after", lambda _: executed.append("control")),
        ])
        result, events, _ = self.run_synthetic(suite)

        self.assertEqual(executed, ["control"])
        self.assertFalse(result.strict_success)
        self.assertTrue(result.summary["execution_completed"])
        self.assertFalse(result.summary["coverage_complete"])
        self.assertEqual(result.summary["discovered_count"], 3)
        self.assertEqual(result.summary["tests_run"], 1)
        self.assertEqual(result.summary["fixture_counts"], {"skip": 1})
        self.assertEqual(result.summary["outcome_counts"], {"success": 1})
        self.assertEqual(result.summary["missing_started_ids"], hidden_ids)
        self.assertEqual(result.summary["missing_stopped_ids"], hidden_ids)
        self.assertEqual(result.summary["missing_outcome_ids"], hidden_ids)
        self.assertEqual([event["outcome"] for event in events
                          if event["event"] == "fixture_outcome"], ["skip"])

    def test_module_setup_skip_leaves_all_its_bodies_missing(self):
        executed = []
        module = types.ModuleType("_governance_synthetic_setup_skip")

        def set_up_module():
            raise unittest.SkipTest("synthetic module prerequisite")

        module.setUpModule = set_up_module

        class Case(unittest.TestCase):
            def test_first(self):
                executed.append("first")

            def test_second(self):
                executed.append("second")

        Case.__module__ = module.__name__
        hidden = [Case("test_first"), Case("test_second")]
        hidden_ids = sorted(case.id() for case in hidden)
        suite = unittest.TestSuite(hidden + [
            _case("fixture.Control.test_after", lambda _: executed.append("control")),
        ])
        with mock.patch.dict(sys.modules, {module.__name__: module}):
            result, events, _ = self.run_synthetic(suite)

        self.assertEqual(executed, ["control"])
        self.assertFalse(result.strict_success)
        self.assertFalse(result.summary["coverage_complete"])
        self.assertEqual(result.summary["discovered_count"], 3)
        self.assertEqual(result.summary["tests_run"], 1)
        self.assertEqual(result.summary["fixture_counts"], {"skip": 1})
        self.assertEqual(result.summary["outcome_counts"], {"success": 1})
        self.assertEqual(result.summary["missing_started_ids"], hidden_ids)
        self.assertEqual(result.summary["missing_stopped_ids"], hidden_ids)
        self.assertEqual(result.summary["missing_outcome_ids"], hidden_ids)
        fixture_event = next(event for event in events if event["event"] == "fixture_outcome")
        self.assertIn("setUpModule", fixture_event["fixture_id"])
        self.assertEqual(fixture_event["reason"], "synthetic module prerequisite")

    def test_class_teardown_error_rejects_complete_successful_bodies(self):
        class Case(unittest.TestCase):
            @classmethod
            def tearDownClass(cls):
                raise RuntimeError("synthetic teardown error")

            def test_body(self):
                pass

        result, _, output = self.run_synthetic(unittest.TestSuite([Case("test_body")]))

        self.assertTrue(result.summary["execution_completed"])
        self.assertTrue(result.summary["coverage_complete"])
        self.assertEqual(result.summary["outcome_counts"], {"success": 1})
        self.assertEqual(result.summary["fixture_counts"], {"error": 1})
        self.assertFalse(result.strict_success)
        self.assertIn("synthetic teardown error", output)

    def test_expected_failure_is_not_a_passing_governance_body(self):
        class Case(unittest.TestCase):
            @unittest.expectedFailure
            def test_body(self):
                self.fail("synthetic expected failure")

        case = Case("test_body")
        identity = case.id()
        result, _, _ = self.run_synthetic(unittest.TestSuite([case]))

        self.assertTrue(result.wasSuccessful())
        self.assertFalse(result.strict_success)
        self.assertTrue(result.summary["coverage_complete"])
        self.assertEqual(result.summary["outcome_counts"], {"expected_failure": 1})
        self.assertEqual(result.summary["non_successful_ids"], [identity])

    def test_unexpected_success_is_not_a_passing_governance_body(self):
        class Case(unittest.TestCase):
            @unittest.expectedFailure
            def test_body(self):
                pass

        case = Case("test_body")
        identity = case.id()
        result, _, _ = self.run_synthetic(unittest.TestSuite([case]))

        self.assertFalse(result.strict_success)
        self.assertTrue(result.summary["coverage_complete"])
        self.assertEqual(result.summary["outcome_counts"], {"unexpected_success": 1})
        self.assertEqual(result.summary["non_successful_ids"], [identity])

    def test_failing_or_erroring_subtest_cannot_be_hidden_by_later_success(self):
        for exception, outcome in ((AssertionError, "failure"), (RuntimeError, "error")):
            with self.subTest(outcome=outcome):
                executed = []

                def body(case):
                    with case.subTest(part="bad"):
                        raise exception("synthetic subtest problem")
                    with case.subTest(part="good"):
                        executed.append("continued")

                result, events, _ = self.run_synthetic(unittest.TestSuite([
                    _case("fixture.Subtests.test_problem", body),
                ]))

                self.assertEqual(executed, ["continued"])
                self.assertFalse(result.strict_success)
                self.assertTrue(result.summary["execution_completed"])
                self.assertEqual(result.summary["tests_run"], 1)
                self.assertEqual(result.summary["subtest_counts"], {outcome: 1, "success": 1})
                self.assertEqual(result.summary["outcome_counts"].get("success", 0), 0)
                self.assertEqual(result.summary["non_successful_ids"],
                                 ["fixture.Subtests.test_problem"])
                self.assertEqual([event["outcome"] for event in events
                                  if event["event"] == "subtest_outcome"],
                                 [outcome, "success"])

    def test_skipped_subtest_cannot_be_hidden_by_later_success(self):
        executed = []

        def body(case):
            with case.subTest(part="skipped"):
                case.skipTest("synthetic subtest skip")
            with case.subTest(part="good"):
                executed.append("continued")

        result, events, _ = self.run_synthetic(unittest.TestSuite([
            _case("fixture.Subtests.test_skip", body),
        ]))

        self.assertEqual(executed, ["continued"])
        self.assertTrue(result.wasSuccessful())
        self.assertFalse(result.strict_success)
        self.assertEqual(result.summary["subtest_counts"], {"skip": 1, "success": 1})
        self.assertEqual(result.summary["outcome_counts"].get("success", 0), 0)
        self.assertEqual(result.summary["non_successful_ids"], ["fixture.Subtests.test_skip"])
        skipped = next(event for event in events if event.get("outcome") == "skip")
        self.assertEqual(skipped["event"], "subtest_outcome")
        self.assertEqual(skipped["test_id"], "fixture.Subtests.test_skip")
        self.assertEqual(skipped["reason"], "synthetic subtest skip")

    def test_duplicate_discovery_is_rejected_before_any_body_executes(self):
        executed = []
        suite = unittest.TestSuite([
            _case("fixture.Duplicate.test_body", lambda _: executed.append("first")),
            _case("fixture.Duplicate.test_body", lambda _: executed.append("second")),
        ])
        result, events, _ = self.run_synthetic(suite)

        self.assertEqual(executed, [])
        self.assertEqual(events, [])
        self.assert_incomplete(result)
        self.assertEqual(result.summary["discovered_count"], 2)
        self.assertEqual(result.summary["tests_run"], 0)
        self.assertEqual(result.summary["duplicate_discovered_ids"],
                         ["fixture.Duplicate.test_body"])

    def test_loader_errors_reject_an_otherwise_valid_suite_before_execution(self):
        executed = []
        result, events, output = self.run_synthetic(unittest.TestSuite([
            _case("fixture.Loader.test_body", lambda _: executed.append("body")),
        ]), loader_errors=("synthetic discovery import failure",))

        self.assertEqual(executed, [])
        self.assertEqual(events, [])
        self.assert_incomplete(result)
        self.assertEqual(result.summary["tests_run"], 0)
        self.assertEqual(result.summary["loader_errors"], ["synthetic discovery import failure"])
        self.assertIn("synthetic discovery import failure", output)

    def test_unittest_failed_import_is_detected_without_explicit_loader_errors(self):
        executed = []
        loader = unittest.TestLoader()
        failed = loader.loadTestsFromName("_governance_synthetic_nonexistent_test_module")
        self.assertEqual(len(loader.errors), 1)
        suite = unittest.TestSuite([
            _case("fixture.Loader.test_before", lambda _: executed.append("before")),
            failed,
        ])
        result, events, _ = self.run_synthetic(suite)

        self.assertEqual(executed, [])
        self.assertEqual(events, [])
        self.assert_incomplete(result)
        self.assertEqual(result.summary["discovered_count"], 2)
        self.assertEqual(result.summary["tests_run"], 0)
        self.assertEqual(len(result.summary["loader_errors"]), 1)
        self.assertIn("_governance_synthetic_nonexistent_test_module",
                      result.summary["loader_errors"][0])

    def test_empty_discovery_is_rejected_without_starting_execution(self):
        result, events, output = self.run_synthetic(unittest.TestSuite())

        self.assertEqual(events, [])
        self.assert_incomplete(result)
        self.assertEqual(result.summary["discovered_count"], 0)
        self.assertEqual(result.summary["tests_run"], 0)
        self.assertEqual(result.summary["outcome_counts"], {})
        self.assertIn("rejected", output)

    def test_keyboard_interrupt_from_a_body_preserves_incomplete_accounting(self):
        executed = []

        def interrupt(_):
            executed.append("interrupted")
            raise KeyboardInterrupt("synthetic interruption")

        result, _, output = self.run_synthetic(unittest.TestSuite([
            _case("fixture.Interrupt.test_before", lambda _: executed.append("before")),
            _case("fixture.Interrupt.test_during", interrupt),
            _case("fixture.Interrupt.test_after", lambda _: executed.append("after")),
        ]))

        self.assertEqual(executed, ["before", "interrupted"])
        self.assert_incomplete(result)
        self.assertEqual(result.summary["tests_run"], 2)
        self.assertEqual(result.summary["outcome_counts"], {"success": 1})
        self.assertEqual(result.summary["abort"],
                         {"type": "KeyboardInterrupt", "message": "synthetic interruption"})
        self.assertEqual(result.summary["missing_started_ids"], ["fixture.Interrupt.test_after"])
        self.assertEqual(result.summary["missing_outcome_ids"],
                         ["fixture.Interrupt.test_after", "fixture.Interrupt.test_during"])
        self.assertIn("KeyboardInterrupt", output)

    def test_escaping_system_exit_cannot_finalize_a_partial_suite_as_passed(self):
        executed = []

        class AbortingSuite(unittest.TestSuite):
            def run(self, result, debug=False):
                raise SystemExit(23)

        suite = unittest.TestSuite([
            _case("fixture.Exit.test_before", lambda _: executed.append("before")),
            AbortingSuite([
                _case("fixture.Exit.test_unreached", lambda _: executed.append("unreached")),
            ]),
        ])
        result, _, output = self.run_synthetic(suite)

        self.assertEqual(executed, ["before"])
        self.assert_incomplete(result)
        self.assertEqual(result.summary["tests_run"], 1)
        self.assertEqual(result.summary["outcome_counts"], {"success": 1})
        self.assertEqual(result.summary["abort"], {"type": "SystemExit", "message": "23"})
        self.assertEqual(result.summary["missing_started_ids"], ["fixture.Exit.test_unreached"])
        self.assertEqual(result.summary["missing_outcome_ids"], ["fixture.Exit.test_unreached"])
        self.assertIn("SystemExit: 23", output)

    def test_system_exit_caught_by_unittest_is_an_error_and_never_a_pass(self):
        executed = []

        def exit_body(_):
            raise SystemExit(23)

        result, _, _ = self.run_synthetic(unittest.TestSuite([
            _case("fixture.Exit.test_body", exit_body),
            _case("fixture.Exit.test_after", lambda _: executed.append("after")),
        ]))

        self.assertEqual(executed, ["after"])
        self.assertFalse(result.strict_success)
        self.assertTrue(result.summary["execution_completed"])
        self.assertTrue(result.summary["coverage_complete"])
        self.assertEqual(result.summary["outcome_counts"], {"error": 1, "success": 1})
        self.assertEqual(result.summary["non_successful_ids"], ["fixture.Exit.test_body"])
        self.assertIsNone(result.summary["abort"])

    def test_completed_test_instances_are_released_while_result_and_events_remain(self):
        class Case(unittest.TestCase):
            def test_error(self):
                raise RuntimeError("synthetic error")

            @unittest.expectedFailure
            def test_expected_failure(self):
                self.fail("synthetic expected failure")

            def test_failure(self):
                self.fail("synthetic failure")

            @unittest.skip("synthetic decorated skip")
            def test_method_skip(self):
                pass

            def test_runtime_skip(self):
                self.skipTest("synthetic runtime skip")

            def test_subtest_error(self):
                with self.subTest(part="error"):
                    raise RuntimeError("synthetic subtest error")

            def test_subtest_failure(self):
                with self.subTest(part="failure"):
                    self.fail("synthetic subtest failure")

            def test_subtest_skip(self):
                with self.subTest(part="skip"):
                    self.skipTest("synthetic subtest skip")

            def test_success(self):
                pass

            @unittest.expectedFailure
            def test_unexpected_success(self):
                pass

        suite = unittest.defaultTestLoader.loadTestsFromTestCase(Case)
        references = [weakref.ref(case) for case in suite]
        identities = governance_run.collect_test_ids(suite)
        released_during_execution = []

        def observe_release(_):
            gc.collect()
            released_during_execution.append(all(reference() is None for reference in references))

        suite.addTest(_case("fixture.Lifetime.test_observer", observe_release))
        result, events, output = self.run_synthetic(suite)
        gc.collect()

        self.assertEqual(len(identities), 10)
        self.assertEqual(released_during_execution, [True])
        self.assertTrue(all(reference() is None for reference in references))
        self.assertEqual(result.summary["tests_run"], 11)
        self.assertFalse(result.strict_success)
        self.assertGreater(len(events), 30)
        self.assertIn("synthetic subtest error", output)


if __name__ == "__main__":
    unittest.main()
