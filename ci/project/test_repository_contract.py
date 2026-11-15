# SPDX-License-Identifier: Apache-2.0
"""Cross-document contracts and narrow textual CI guardrails, not attestations."""

from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "docs/project"
IMAGE_PATH = "docs/assets/img/vortex_framework_stack.svg"
IMAGE_SHA256 = "db123c71024f85f379c2504c7465c03ee9df8959a5d17fc3d3e94a94a1cd3aa4"
IMAGE_EMBED = '<img src="' + IMAGE_PATH + '" alt="Vortex framework stack" width="100%">'
GATE_PATTERN = re.compile(r"\bP[0-9]{2}-A[0-9]{2}\b")


def _read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _ledger_errors(data, foundation_complete=False):
    """Check the recorded prefix; metadata cannot prove an agent actually ran."""
    if not isinstance(data, dict):
        return ["ledger must be an object"]
    errors = []
    if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        errors.append("ledger schema version must be integer 1")
    requested = data.get("requested")
    if (not isinstance(requested, dict) or requested != {"agents": 60, "waves": 10}
            or type(requested.get("agents")) is not int or type(requested.get("waves")) is not int):
        errors.append("setup request is 60 distinct agents in 10 waves")
    concurrency = data.get("max_concurrent_subagents")
    if type(concurrency) is not int or not 1 <= concurrency <= 3:
        errors.append("recorded subagent concurrency must be between 1 and 3")
    entries = data.get("completed")
    if not isinstance(entries, list):
        return errors + ["completed assignments must be a list"]
    if len(entries) > 60:
        errors.append("setup ledger exceeds its requested assignment count")
    names, waves = set(), []
    for entry in entries:
        if not isinstance(entry, dict):
            errors.append("assignment must be an object")
            continue
        wave = entry.get("wave")
        if type(wave) is not int or not 1 <= wave <= 10:
            errors.append("assignment wave must be an integer from 1 through 10")
            continue
        waves.append(wave)
        name = entry.get("agent")
        match = re.fullmatch(r"/root/w([0-9]{2})_a([0-9]{2})", name) if isinstance(name, str) else None
        if match is None or int(match[1]) != wave or not 1 <= int(match[2]) <= 6:
            errors.append("agent identity must name its wave and one of six assignments")
        if isinstance(name, str):
            if name in names:
                errors.append("agent identities must be distinct")
            names.add(name)
        if entry.get("status") != "complete":
            errors.append("completed assignments cannot contain pending work")
        task = entry.get("task")
        if not isinstance(task, str) or not task.strip():
            errors.append("each assignment needs its actual task")
    counts = Counter(waves)
    if waves != sorted(waves):
        errors.append("recorded waves must be ordered")
    if any(count > 6 for count in counts.values()):
        errors.append("a wave may contain at most six distinct assignments")
    if waves and any(counts[number] != 6 for number in range(1, max(waves))):
        errors.append("a later wave requires six completed assignments in every earlier wave")
    if foundation_complete and (len(entries) != 60 or len(names) != 60
                                or any(counts[number] != 6 for number in range(1, 11))):
        errors.append("accepted foundation requires all 60 assignments across 10 complete waves")
    return errors


def _ledger_fixture(count):
    return {
        "schema_version": 1,
        "requested": {"agents": 60, "waves": 10},
        "max_concurrent_subagents": 3,
        "completed": [
            {"wave": index // 6 + 1,
             "agent": f"/root/w{index // 6 + 1:02d}_a{index % 6 + 1:02d}",
             "status": "complete", "task": "Synthetic ledger fixture; not execution evidence"}
            for index in range(count)
        ],
    }


class RepositoryContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.roadmap = _read_json(PROJECT / "roadmap.json")
        cls.phases = cls.roadmap["phases"]
        cls.gates = {gate["id"] for phase in cls.phases for gate in phase["acceptance"]}

    def test_requirement_rows_have_unique_ids_and_cover_all_gates(self):
        text = (PROJECT / "requirements.md").read_text(encoding="utf-8")
        rows = [line for line in text.splitlines() if re.match(r"\| RQ-[0-9]{3} \|", line)]
        self.assertTrue(rows, "Requirements must contain traceability rows")
        requirement_ids = [re.search(r"RQ-[0-9]{3}", line)[0] for line in rows]
        self.assertEqual(len(requirement_ids), len(set(requirement_ids)))
        mapped = set()
        for row in rows:
            gate_ids = set(GATE_PATTERN.findall(row))
            self.assertTrue(gate_ids, "Each requirement row must name an acceptance gate")
            mapped.update(gate_ids)
        self.assertEqual(mapped, self.gates, "Requirement mapping has missing or unknown gates")

    def test_each_phase_guide_names_its_gates_without_unknown_ids(self):
        for phase in self.phases:
            with self.subTest(phase=phase["id"]):
                text = (ROOT / phase["document"]).read_text(encoding="utf-8")
                mentioned = set(GATE_PATTERN.findall(text))
                expected = {gate["id"] for gate in phase["acceptance"]}
                self.assertLessEqual(expected, mentioned)
                self.assertLessEqual(mentioned, self.gates)

    def test_roadmap_and_project_index_link_every_phase(self):
        roadmap_text = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
        index_text = (PROJECT / "index.md").read_text(encoding="utf-8")
        for phase in self.phases:
            with self.subTest(phase=phase["id"]):
                path = Path(phase["document"])
                self.assertTrue((ROOT / path).is_file())
                self.assertIn("](" + path.as_posix() + ")", roadmap_text)
                relative = path.relative_to("docs/project").as_posix()
                self.assertIn("](" + relative + ")", index_text)

    def test_required_project_documents_remain_indexed(self):
        index = PROJECT / "index.md"
        text = index.read_text(encoding="utf-8")
        for name in self.roadmap["required_documents"]:
            with self.subTest(document=name):
                path = ROOT / name
                self.assertTrue(path.is_file())
                if path != index and path.is_relative_to(PROJECT):
                    self.assertIn("](" + path.relative_to(PROJECT).as_posix() + ")", text)

    def test_entrypoints_link_the_canonical_navigation(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for link in ("ROADMAP.md", "docs/project/index.md", "docs/project/status.md",
                     "docs/project/roadmap.json", "CONTRIBUTING.md", "AGENTS.md"):
            with self.subTest(link=link):
                self.assertIn("](" + link + ")", readme)
        technical_index = (ROOT / "docs/index.md").read_text(encoding="utf-8")
        self.assertIn("](project/index.md)", technical_index)

    def test_announced_phase_and_gate_totals_match_the_manifest(self):
        for filename in ("README.md", "ROADMAP.md"):
            with self.subTest(document=filename):
                text = (ROOT / filename).read_text(encoding="utf-8")
                phase_counts = re.findall(r"\b([0-9]+) phases\b", text)
                gate_counts = re.findall(r"\b([0-9]+) acceptance (?:gates|criteria)\b", text)
                self.assertTrue(phase_counts)
                self.assertTrue(gate_counts)
                self.assertEqual({int(value) for value in phase_counts}, {len(self.phases)})
                self.assertEqual({int(value) for value in gate_counts}, {len(self.gates)})

    def test_report_template_is_explicitly_unexecuted_and_unreviewed(self):
        report = _read_json(PROJECT / "evidence/report.example.json")
        self.assertEqual(report["outcome"], "not_run")
        self.assertEqual(report["reviewer"], "pending")
        self.assertTrue(report["commands"])
        for command in report["commands"]:
            self.assertEqual(command["result"], "not_run")
            self.assertIsNone(command["exit_code"])

    def test_benchmark_template_contains_no_achieved_measurements(self):
        benchmark = _read_json(PROJECT / "evidence/benchmark.example.json")
        self.assertEqual(benchmark["outcome"], "not_run")
        self.assertIs(benchmark["is_phase_evidence"], False)
        self.assertTrue(benchmark["measured_metrics"])
        self.assertTrue(all(value is None for value in benchmark["measured_metrics"].values()))

    def test_no_unexecuted_example_is_attached_to_a_phase(self):
        for phase in self.phases:
            for reference in phase["evidence"]:
                with self.subTest(phase=phase["id"], reference=reference):
                    self.assertFalse(reference["record"].endswith(".example.json"))

    def test_original_image_and_readme_embed_are_preserved(self):
        self.assertEqual(hashlib.sha256((ROOT / IMAGE_PATH).read_bytes()).hexdigest(), IMAGE_SHA256)
        self.assertIn({"path": IMAGE_PATH, "sha256": IMAGE_SHA256}, self.roadmap["protected_assets"])
        self.assertIn(IMAGE_EMBED, (ROOT / "README.md").read_text(encoding="utf-8"))

    def test_recorded_execution_ledger_is_a_valid_completed_prefix(self):
        ledger = _read_json(PROJECT / "agent-execution.json")
        foundation = next(phase for phase in self.phases if phase["id"] == "P00")
        self.assertEqual(_ledger_errors(ledger, foundation["status"] == "complete"), [])

    def test_workflow_retains_declared_low_privilege_guardrails(self):
        # Literal guardrails complement, but do not replace, YAML and trust-boundary review.
        text = (ROOT / ".github/workflows/project-governance.yml").read_text(encoding="utf-8")
        self.assertNotRegex(text, r"\bpull_request_target\b|\bself-hosted\b|\bsecrets\s*[.\[]")
        self.assertEqual(re.findall(r"(?m)^([ \t]*)permissions:", text), [""])
        self.assertRegex(text, r"(?m)^permissions:\s*\n  contents: read\s*$")
        self.assertNotRegex(text, r"(?m)^\s*[\w-]+:\s*(?:write|write-all)\s*$")
        self.assertRegex(text, r"(?m)^    runs-on: ubuntu-[0-9]{2}\.[0-9]{2}\s*$")
        timeout = re.findall(r"(?m)^    timeout-minutes: ([0-9]+)\s*$", text)
        self.assertEqual(len(timeout), 1)
        self.assertTrue(1 <= int(timeout[0]) <= 10)
        for setting in ("persist-credentials", "submodules", "lfs"):
            self.assertRegex(text, rf"(?m)^          {setting}: false\s*$")
        for command in ("python3 ci/project/preflight.py --tier governance",
                        "python3 ci/project/check_project.py",
                        "python3 -m unittest discover -s ci/project -p 'test_*.py'"):
            self.assertIn("run: " + command, text)


class ExecutionLedgerContractTests(unittest.TestCase):
    def test_in_progress_accepts_empty_or_partial_final_wave(self):
        for count in (0, 1, 6, 7, 30, 59, 60):
            with self.subTest(count=count):
                self.assertEqual(_ledger_errors(_ledger_fixture(count)), [])

    def test_complete_foundation_requires_exact_requested_count(self):
        for count in (0, 6, 30, 59):
            with self.subTest(count=count):
                self.assertTrue(_ledger_errors(_ledger_fixture(count), True))
        self.assertEqual(_ledger_errors(_ledger_fixture(60), True), [])

    def test_duplicate_agent_and_extra_assignment_are_rejected(self):
        duplicate = _ledger_fixture(6)
        duplicate["completed"][1]["agent"] = duplicate["completed"][0]["agent"]
        self.assertTrue(_ledger_errors(duplicate))
        extra = _ledger_fixture(60)
        extra["completed"].append(copy.deepcopy(extra["completed"][-1]))
        self.assertTrue(_ledger_errors(extra))

    def test_missing_previous_wave_and_reordered_waves_are_rejected(self):
        missing = _ledger_fixture(7)
        del missing["completed"][0]
        self.assertTrue(_ledger_errors(missing))
        reordered = _ledger_fixture(7)
        reordered["completed"].reverse()
        self.assertTrue(_ledger_errors(reordered))

    def test_wrong_wave_identity_and_pending_assignment_are_rejected(self):
        for key, value in (("agent", "/root/w02_a01"), ("agent", "/root/w01_a07"),
                           ("wave", True), ("wave", 11), ("status", "running"), ("task", " ")):
            with self.subTest(field=key, value=value):
                ledger = _ledger_fixture(1)
                ledger["completed"][0][key] = value
                self.assertTrue(_ledger_errors(ledger))

    def test_invalid_ledger_metadata_is_rejected(self):
        for key, value in (("schema_version", True), ("requested", {"agents": 6, "waves": 1}),
                           ("requested", {"agents": 60.0, "waves": 10}),
                           ("max_concurrent_subagents", 4), ("max_concurrent_subagents", True),
                           ("completed", {}), ("completed", [None])):
            with self.subTest(field=key, value=value):
                ledger = _ledger_fixture(1)
                ledger[key] = value
                self.assertTrue(_ledger_errors(ledger))
        self.assertTrue(_ledger_errors(None))


if __name__ == "__main__":
    unittest.main()
