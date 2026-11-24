# SPDX-License-Identifier: Apache-2.0
"""Shared structural checks for the strict, complete governance invocation."""

import ast
from pathlib import Path
import shlex

from test_p05_ci_workflow import script


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "ci/project/governance_run.py"


def _expression(source):
    return ast.dump(ast.parse(source, mode="eval").body, include_attributes=False)


def _same_expression(case, node, source):
    case.assertEqual(ast.dump(node, include_attributes=False), _expression(source))


def _calls(tree, name):
    expected = _expression(name)
    return [node for node in ast.walk(tree) if isinstance(node, ast.Call)
            and ast.dump(node.func, include_attributes=False) == expected]


def _one_function(case, tree, name):
    found = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name]
    case.assertEqual(len(found), 1, "expected one runner function: " + name)
    return found[0]


def _one_assignment(case, tree, name):
    writes = [node for node in ast.walk(tree) if isinstance(node, ast.Name)
              and node.id == name and isinstance(node.ctx, ast.Store)]
    found = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)
             and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
             and node.targets[0].id == name]
    case.assertEqual(len(writes), 1, "runner must not replace or filter " + name)
    case.assertEqual(len(found), 1, "expected one plain assignment: " + name)
    return found[0]


def _assert_name_uses(case, tree, name, expected):
    uses = [node for node in ast.walk(tree) if isinstance(node, ast.Name)
            and node.id == name and isinstance(node.ctx, ast.Load)]
    case.assertEqual(len(uses), expected, "unexpected alias, mutation, or filtering of " + name)


def _assert_not_repeated(case, tree, call, *, unconditional=False):
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    forbidden = (ast.For, ast.AsyncFor, ast.While, ast.comprehension)
    if unconditional:
        forbidden += (ast.If, ast.IfExp)
    node = call
    while node in parents:
        node = parents[node]
        case.assertNotIsInstance(node, forbidden, "canonical discovery and execution cannot be selected or retried")


def assert_strict_discovery(case):
    """Inspect the executed runner, not a comment or an unused command literal.

    Behavioral outcome accounting is exercised by the runner's focused tests.
    This contract checks the workflow-to-runner boundary: fixed source-root
    discovery, no CLI selection, no suite filtering, one execution and a strict
    result-dependent process status.
    """
    tree = ast.parse(RUNNER.read_text(encoding="utf-8"), filename=str(RUNNER))
    _same_expression(case, _one_assignment(case, tree, "ROOT").value,
                     "Path(__file__).resolve().parents[2]")
    discovery = _one_assignment(case, tree, "DISCOVERY")
    case.assertEqual(ast.literal_eval(discovery.value), {
        "start_directory": "ci/project", "pattern": "test_*.py",
    })
    # Only subscript reads and inert receipt fields may consume this mapping.
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "DISCOVERY" and isinstance(node.ctx, ast.Load):
            parent = parents[node]
            case.assertIsInstance(parent, (ast.Subscript, ast.Dict))
            if isinstance(parent, ast.Subscript):
                case.assertIs(parent.value, node)
                case.assertIsInstance(parent.ctx, ast.Load)
                case.assertIn(ast.literal_eval(parent.slice), ("start_directory", "pattern"))
            else:
                case.assertIn(node, parent.values)

    main = _one_function(case, tree, "main")
    options = _calls(main, "parser.add_argument")
    case.assertEqual([tuple(ast.literal_eval(arg) for arg in call.args) for call in options], [
        ("--output-dir",), ("--environment-receipt",),
    ], "governance must not expose a test, pattern, shard, or exclusion selector")
    parse = _calls(main, "parser.parse_args")
    case.assertEqual(len(parse), 1)
    _same_expression(case, parse[0], "parser.parse_args(argv)")
    case.assertFalse(_calls(tree, "parser.parse_known_args"), "unknown selectors must fail closed")

    loader = _one_assignment(case, main, "loader")
    _same_expression(case, loader.value, "unittest.TestLoader()")
    _assert_name_uses(case, main, "loader", 2)
    suite = _one_assignment(case, main, "suite")
    _same_expression(case, suite.value,
                     'loader.discover(DISCOVERY["start_directory"], pattern=DISCOVERY["pattern"])')
    discovers = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute) and node.func.attr == "discover"]
    case.assertEqual(discovers, [suite.value], "exactly one canonical discovery is required")
    _assert_not_repeated(case, main, suite.value, unconditional=True)
    _assert_name_uses(case, main, "suite", 2)
    identities = _one_assignment(case, main, "identities")
    _same_expression(case, identities.value, "collect_test_ids(suite)")

    chdir = [call for call in _calls(main, "os.chdir") if len(call.args) == 1
             and ast.dump(call.args[0], include_attributes=False) == _expression("ROOT")]
    case.assertEqual(len(chdir), 1, "discovery must run from the source root")
    case.assertLess(chdir[0].lineno, suite.lineno)
    _assert_not_repeated(case, main, chdir[0], unconditional=True)
    execute = _calls(tree, "run_suite")
    case.assertEqual(len(execute), 1, "the complete discovered suite must run exactly once")
    _same_expression(case, execute[0],
                     "run_suite(suite, stream=sys.stderr, event_sink=emit, loader_errors=loader.errors)")
    case.assertIn(execute[0], list(ast.walk(main)))
    case.assertLess(suite.lineno, identities.lineno)
    case.assertLess(identities.lineno, execute[0].lineno)
    _assert_not_repeated(case, main, execute[0], unconditional=True)

    run_suite = _one_function(case, tree, "run_suite")
    case.assertFalse([node for node in ast.walk(run_suite) if isinstance(node, ast.Name)
                      and node.id == "suite" and isinstance(node.ctx, ast.Store)],
                     "the execution helper cannot replace the discovered suite")
    _assert_name_uses(case, run_suite, "suite", 2)
    _same_expression(case, _one_assignment(case, run_suite, "identities").value,
                     "collect_test_ids(suite)")
    _same_expression(case, _one_assignment(case, run_suite, "runner").value,
                     "unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=result_factory)")
    strict_result = _calls(run_suite, "StrictResult")
    case.assertEqual(len(strict_result), 1)
    _same_expression(case, strict_result[0],
                     "StrictResult(*args, test_ids=identities, event_sink=event_sink, "
                     "loader_errors=errors, **kwargs)")
    run = _calls(run_suite, "runner.run")
    case.assertEqual(len(run), 1)
    _same_expression(case, run[0], "runner.run(suite)")
    _assert_not_repeated(case, run_suite, run[0])
    finalize = _calls(run_suite, "result.finalize")
    case.assertEqual(len(finalize), 1)
    case.assertLess(run[0].lineno, finalize[0].lineno)
    _assert_not_repeated(case, run_suite, finalize[0], unconditional=True)
    case.assertIsInstance(run_suite.body[-1], ast.Return)
    _same_expression(case, run_suite.body[-1].value, "result")

    pass_assignments = [node for node in ast.walk(main) if isinstance(node, ast.Assign)
                        and any(isinstance(target, ast.Subscript)
                                and isinstance(target.value, ast.Name) and target.value.id == "summary"
                                and isinstance(target.slice, ast.Constant)
                                and target.slice.value == "governance_passed" for target in node.targets)]
    gates = [node.value for node in pass_assignments if not (
        isinstance(node.value, ast.Constant) and node.value.value is False)]
    case.assertEqual(len(gates), 1, "success cannot be overwritten or forced after execution")
    gate = gates[0]
    case.assertIsInstance(gate, ast.Call)
    _same_expression(case, gate.func, "bool")
    case.assertEqual(len(gate.args), 1)
    case.assertFalse(gate.keywords)
    case.assertIsInstance(gate.args[0], ast.BoolOp)
    case.assertIsInstance(gate.args[0].op, ast.And)
    clauses = {ast.dump(node, include_attributes=False) for node in gate.args[0].values}
    for required in ("result.strict_success", "tuple(identities) == result.test_ids",
                     'summary["source_after"]["clean"]', 'summary["source_stable"]',
                     'summary["interpreter_stable"]', 'summary["environment_stable"]',
                     'not log_state["truncated"]'):
        case.assertIn(_expression(required), clauses)
    returns = [node for node in ast.walk(main) if isinstance(node, ast.Return)]
    case.assertEqual(returns, [main.body[-1]])
    _same_expression(case, returns[0].value, '0 if summary["governance_passed"] else 1')
    expected_entry = ast.parse('if __name__ == "__main__":\n'
                               '    sys.dont_write_bytecode = True\n'
                               '    raise SystemExit(main())\n').body[0]
    case.assertEqual(ast.dump(tree.body[-1], include_attributes=False),
                     ast.dump(expected_entry, include_attributes=False))


def assert_strict_governance_step(case, step):
    """Require one unconditional fail-closed invocation and its retained log."""
    case.assertEqual(set(step), {"name", "run"},
                     "the source suite cannot gain skip, suppression, shell, or environment overrides")
    case.assertEqual(step["name"], ("Test governance tooling", []))
    lines = script(step).replace("\\\n", " ").splitlines()
    case.assertEqual(len(lines), 2, "the shell must only enable strict mode and invoke the suite once")
    case.assertEqual(shlex.split(lines[0]), ["set", "-euo", "pipefail"])
    # Preserve double quoting as well as argument boundaries: private paths must
    # expand as one argument, and tee must not mask the runner's failure.
    case.assertEqual(shlex.split(lines[1], posix=False), [
        "/usr/bin/env", "-i", 'PATH="$GOVERNANCE_ROOT/environment/venv/bin:/usr/bin:/bin"',
        'HOME="$GOVERNANCE_ROOT/environment/home"', 'TMPDIR="$GOVERNANCE_ROOT/environment/tmp"',
        "LANG=C", "LC_ALL=C", "TZ=UTC", "PYTHONUTF8=1", "PYTHONDONTWRITEBYTECODE=1",
        "CCACHE_DISABLE=1", "OBJCACHE=", "MAKEFLAGS=-j2", "CMAKE_BUILD_PARALLEL_LEVEL=2", "THREADS=1",
        '"$GOVERNANCE_ROOT/environment/venv/bin/python"', "ci/project/governance_run.py",
        "--output-dir", '"$GOVERNANCE_ROOT/run"',
        "--environment-receipt", '"$GOVERNANCE_ROOT/environment/environment.json"',
        "2>&1", "|", "tee", '"$GOVERNANCE_ROOT/logs/governance.log"',
    ])
    assert_strict_discovery(case)
