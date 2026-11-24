# SPDX-License-Identifier: Apache-2.0
"""Keep every frozen model input inside the governance workflow's coverage."""

from pathlib import Path
import re
import unittest

from governance_workflow_test_support import assert_strict_governance_step
from p04_model_contract import ARTIFACT_PATHS
from test_p05_ci_workflow import fields


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/project-governance.yml"


def section(lines, name, indent):
    header = " " * indent + name + ":"
    matches = [index for index, line in enumerate(lines) if line == header]
    if len(matches) != 1:
        raise AssertionError(f"expected one plain {name} mapping at indentation {indent}")
    selected = []
    for line in lines[matches[0] + 1:]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if len(line) - len(line.lstrip(" ")) <= indent:
            break
        selected.append(line)
    return selected


def positive_path_patterns(lines, event):
    body = section(section(lines, "on", 0), event, 2)
    if not body or body[0] != "    paths:":
        raise AssertionError(f"{event}: expected a plain positive paths filter")
    patterns = []
    for line in body[1:]:
        entry = re.fullmatch(r"      - (['\"])([A-Za-z0-9_./*\-]+)\1", line)
        if entry is None:
            raise AssertionError(f"{event}: unsupported path filter or event structure: {line}")
        pattern = entry[2]
        if "**" in pattern:
            if not pattern.endswith("/**") or "*" in pattern[:-3]:
                raise AssertionError(f"{event}: unsupported recursive glob: {pattern}")
            expression = re.escape(pattern[:-2]) + ".*"
        else:
            expression = "[^/]*".join(re.escape(part) for part in pattern.split("*"))
        patterns.append(re.compile(expression))
    if not patterns:
        raise AssertionError(f"{event}: empty paths filter")
    return patterns


class TinyMlpCiCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data = WORKFLOW.read_bytes()
        if len(data) > 64 * 1024 or b"\t" in data:
            raise AssertionError("workflow exceeds the bounded plain-indentation contract")
        cls.lines = data.decode("utf-8").splitlines()

    def test_all_pinned_artifacts_trigger_both_governance_events(self):
        for event in ("push", "pull_request"):
            patterns = positive_path_patterns(self.lines, event)
            for path in (*ARTIFACT_PATHS, WORKFLOW.relative_to(ROOT).as_posix(),
                         Path(__file__).relative_to(ROOT).as_posix()):
                with self.subTest(event=event, path=path):
                    self.assertTrue(any(pattern.fullmatch(path) for pattern in patterns),
                                    f"{event} does not cover frozen input {path}")

    def test_source_suite_remains_an_unconditional_failing_step(self):
        job = section(section(self.lines, "jobs", 0), "governance", 2)
        job_keys = []
        for line in job:
            if line.startswith("     "):
                continue
            key = re.match(r"    ([a-z][a-z0-9-]*):(?: |$)", line)
            self.assertIsNotNone(key, "governance job keys must use plain mapping syntax")
            job_keys.append(key[1])
        self.assertEqual(len(job_keys), len(set(job_keys)), "duplicate governance job key")
        self.assertTrue({"if", "continue-on-error"}.isdisjoint(job_keys),
                         "governance must not skip or suppress its source checks")
        steps = section(job, "steps", 4)
        header = "      - name: Test governance tooling"
        matches = [index for index, line in enumerate(steps) if line == header]
        self.assertEqual(len(matches), 1, "the source suite must have one explicit step")
        body = []
        for line in steps[matches[0] + 1:]:
            if len(line) - len(line.lstrip(" ")) <= 6:
                break
            body.append(line)
        step = fields(["        name: Test governance tooling", *body], 8)
        assert_strict_governance_step(self, step)
