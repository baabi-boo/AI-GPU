# SPDX-License-Identifier: Apache-2.0
"""Offline tests for project structure and evidence validation."""

import copy
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import check_project


SOURCE_ROOT = Path(__file__).resolve().parents[2]
IMAGE_PATH = "docs/assets/img/vortex_framework_stack.svg"
IMAGE_SHA256 = "db123c71024f85f379c2504c7465c03ee9df8959a5d17fc3d3e94a94a1cd3aa4"
LEVELS = ["source_present", "simulated", "rtl_verified", "fpga_measured", "silicon_measured"]
STATUSES = ["not_started", "in_progress", "blocked", "complete"]


class ProjectFixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="ai-gpu-governance-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.write(IMAGE_PATH, (SOURCE_ROOT / IMAGE_PATH).read_bytes())
        self.write("README.md", '# Project\n\n<img src="' + IMAGE_PATH + '">\n')
        for name in ("ROADMAP.md", "CONTRIBUTING.md", "AGENTS.md", "SECURITY.md"):
            self.write(name, "# Fixture\n")
        self.write("docs/index.md", "# Documentation\n")
        self.write("docs/project/index.md", "# Project guide\n")
        self.write("docs/project/charter.md", "# Charter\n\n## Purpose\n\nFixture only.\n")
        self.data = {
            "schema_version": 1,
            "project": "AI-GPU",
            "repository": "baabi-boo/AI-GPU",
            "default_branch": "master",
            "baseline_commit": "1" * 40,
            "evidence_levels": list(LEVELS),
            "status_values": list(STATUSES),
            "protected_assets": [{"path": IMAGE_PATH, "sha256": IMAGE_SHA256}],
            "required_documents": ["docs/project/index.md", "docs/project/charter.md"],
            "phases": [self.phase("P00")],
        }

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
        return path

    def save_json(self, name, data):
        return self.write(name, json.dumps(data, indent=2) + "\n")

    def phase(self, phase_id, dependencies=None):
        document = f"docs/project/phases/{phase_id.lower()}.md"
        self.write(document, f"# {phase_id}\n")
        return {
            "id": phase_id,
            "title": "Fixture phase",
            "status": "in_progress",
            "depends_on": list(dependencies or []),
            "accountable_role": "Verification lead",
            "goal": "Validate isolated governance fixtures.",
            "document": document,
            "acceptance": [{
                "id": phase_id + "-A01",
                "criterion": "The fixture has a reviewed check.",
                "verification": "Run the fixture check.",
                "evidence_level": "source_present",
            }],
            "evidence": [],
        }

    def attach_report(self, phase=None):
        phase = phase if phase is not None else self.data["phases"][0]
        phase_id = phase["id"]
        artifact = f"docs/project/evidence/{phase_id.lower()}.txt"
        payload = b"Isolated unit-test fixture, not project acceptance evidence.\n"
        self.write(artifact, payload)
        report = {
            "schema_version": 1,
            "record_id": "test-" + phase_id,
            "kind": "governance",
            "outcome": "pass",
            "evidence_level": "source_present",
            "scope": "Governance fixture only; no GPU execution.",
            "source_revision": "2" * 40,
            "configuration": "Isolated temporary test project.",
            "acceptance_ids": [phase_id + "-A01"],
            "commands": [{"command": "fixture-check", "result": "pass", "exit_code": 0}],
            "artifacts": [{"path": artifact, "sha256": hashlib.sha256(payload).hexdigest()}],
            "limitations": ["Synthetic metadata for a unit test, not hardware evidence."],
            "reviewer": "Unit-test reviewer",
        }
        report_path = f"docs/project/evidence/{phase_id.lower()}.json"
        self.save_json(report_path, report)
        phase["evidence"] = [{"acceptance_id": phase_id + "-A01", "record": report_path}]
        return report, report_path

    def roadmap_errors(self, data=None):
        return check_project.validate_roadmap(self.data if data is None else data, self.root)

    def project_errors(self):
        self.save_json("docs/project/roadmap.json", self.data)
        return check_project.validate_project(self.root)

    def assert_invalid(self, errors):
        self.assertIsInstance(errors, list)
        self.assertTrue(errors, "Invalid fixture was accepted")
        self.assertTrue(all(isinstance(error, str) for error in errors))


class RoadmapTests(ProjectFixture):
    def test_minimal_in_progress_roadmap_is_valid(self):
        self.assertEqual([], self.roadmap_errors())

    def test_validator_does_not_mutate_manifest(self):
        original = copy.deepcopy(self.data)
        self.assertEqual([], self.roadmap_errors())
        self.assertEqual(original, self.data)

    def test_rejects_nonobject_roadmaps(self):
        for value in (None, [], "roadmap", 1, True):
            with self.subTest(value=value):
                self.assert_invalid(check_project.validate_roadmap(value, self.root))

    def test_rejects_invalid_schema_versions(self):
        for value in (True, "1", 1.0, 2, None):
            with self.subTest(value=value):
                data = copy.deepcopy(self.data)
                data["schema_version"] = value
                self.assert_invalid(self.roadmap_errors(data))

    def test_rejects_missing_and_unknown_fields(self):
        data = copy.deepcopy(self.data)
        del data["repository"]
        self.assert_invalid(self.roadmap_errors(data))
        data = copy.deepcopy(self.data)
        data["pretend_complete"] = True
        self.assert_invalid(self.roadmap_errors(data))

    def test_rejects_empty_or_invalid_phase_lists(self):
        for value in ([], None, {}, "P00", [None]):
            with self.subTest(value=value):
                data = copy.deepcopy(self.data)
                data["phases"] = value
                self.assert_invalid(self.roadmap_errors(data))

    def test_rejects_invalid_phase_fields(self):
        for key, value in (("id", "P0"), ("id", []), ("title", ""),
                           ("accountable_role", " "), ("goal", None),
                           ("status", "done"), ("depends_on", "P01"),
                           ("evidence", {}), ("acceptance", [])):
            with self.subTest(key=key, value=value):
                data = copy.deepcopy(self.data)
                data["phases"][0][key] = value
                self.assert_invalid(self.roadmap_errors(data))

    def test_rejects_redefined_status_and_evidence_vocabularies(self):
        for key, value in (("status_values", STATUSES + ["approved"]),
                           ("evidence_levels", list(reversed(LEVELS))),
                           ("evidence_levels", LEVELS + ["promised"])):
            with self.subTest(key=key, value=value):
                data = copy.deepcopy(self.data)
                data[key] = value
                self.assert_invalid(self.roadmap_errors(data))

    def test_rejects_duplicate_phase_ids(self):
        self.data["phases"].append(copy.deepcopy(self.data["phases"][0]))
        self.assert_invalid(self.roadmap_errors())

    def test_rejects_duplicate_and_wrong_phase_acceptance_ids(self):
        phase = self.data["phases"][0]
        phase["acceptance"].append(copy.deepcopy(phase["acceptance"][0]))
        self.assert_invalid(self.roadmap_errors())
        phase["acceptance"].pop()
        phase["acceptance"][0]["id"] = "P01-A01"
        self.assert_invalid(self.roadmap_errors())

    def test_rejects_invalid_acceptance_fields(self):
        for key, value in (("id", "P00-A1"), ("criterion", ""),
                           ("verification", None), ("evidence_level", "promised")):
            with self.subTest(key=key, value=value):
                data = copy.deepcopy(self.data)
                data["phases"][0]["acceptance"][0][key] = value
                self.assert_invalid(self.roadmap_errors(data))

    def test_rejects_unknown_self_and_duplicate_dependencies(self):
        for dependencies in (["P99"], ["P00"], ["P01", "P01"], [None]):
            with self.subTest(dependencies=dependencies):
                data = copy.deepcopy(self.data)
                data["phases"][0]["depends_on"] = dependencies
                self.assert_invalid(self.roadmap_errors(data))

    def test_rejects_dependency_cycle(self):
        self.data["phases"][0]["depends_on"] = ["P01"]
        self.data["phases"].append(self.phase("P01", ["P00"]))
        self.assert_invalid(self.roadmap_errors())

    def test_accepts_acyclic_dependency_chain(self):
        self.data["phases"].extend([self.phase("P01", ["P00"]), self.phase("P02", ["P01"])])
        self.assertEqual([], self.roadmap_errors())

    def test_rejects_missing_documents(self):
        self.data["required_documents"].append("docs/project/missing.md")
        self.assert_invalid(self.roadmap_errors())
        self.data["required_documents"].pop()
        self.data["phases"][0]["document"] = "docs/project/missing.md"
        self.assert_invalid(self.roadmap_errors())

    def test_rejects_unsafe_repository_paths(self):
        for path in ("../outside.md", "/etc/passwd", "C:\\outside.md",
                     "docs/../../outside.md", "docs//project/index.md", "docs/project/index.md#x"):
            with self.subTest(path=path):
                data = copy.deepcopy(self.data)
                data["phases"][0]["document"] = path
                self.assert_invalid(self.roadmap_errors(data))

    def test_rejects_document_symlink_escape(self):
        with tempfile.TemporaryDirectory(prefix="ai-gpu-external-fixture-") as outside:
            target = Path(outside) / "outside.md"
            target.write_text("# Outside\n", encoding="utf-8")
            link = self.root / "docs/project/escape.md"
            link.symlink_to(target)
            self.data["phases"][0]["document"] = "docs/project/escape.md"
            self.assert_invalid(self.roadmap_errors())

    def test_rejects_changed_protected_image(self):
        self.write(IMAGE_PATH, b"changed image")
        self.assert_invalid(self.roadmap_errors())

    def test_rejects_missing_or_code_fenced_image_embed(self):
        for text in ("# No image\n", '```html\n<img src="' + IMAGE_PATH + '">\n```\n'):
            with self.subTest(text=text):
                self.write("README.md", text)
                self.assert_invalid(self.roadmap_errors())

    def test_image_shown_only_as_inline_code_is_not_embedded(self):
        self.write("README.md", '`<img src="' + IMAGE_PATH + '">`\n')
        self.assert_invalid(self.roadmap_errors())

    def test_accepts_markdown_image_embed(self):
        self.write("README.md", "# Project\n\n![GPU](" + IMAGE_PATH + ")\n")
        self.assertEqual([], self.roadmap_errors())

    def test_complete_phase_requires_every_gate(self):
        self.data["phases"][0]["status"] = "complete"
        self.assert_invalid(self.roadmap_errors())
        self.attach_report()
        self.assertEqual([], self.roadmap_errors())
        second = copy.deepcopy(self.data["phases"][0]["acceptance"][0])
        second["id"] = "P00-A02"
        self.data["phases"][0]["acceptance"].append(second)
        self.assert_invalid(self.roadmap_errors())

    def test_complete_phase_requires_complete_dependencies(self):
        next_phase = self.phase("P01", ["P00"])
        next_phase["status"] = "complete"
        self.data["phases"].append(next_phase)
        self.attach_report(next_phase)
        self.assert_invalid(self.roadmap_errors())
        self.attach_report()
        self.data["phases"][0]["status"] = "complete"
        self.assertEqual([], self.roadmap_errors())

    def test_rejects_invalid_report_fields_even_when_phase_incomplete(self):
        report, path = self.attach_report()
        mutations = (("schema_version", True), ("record_id", ""), ("kind", "promise"),
                     ("outcome", "success"), ("scope", ""), ("configuration", None),
                     ("source_revision", "main"), ("source_revision", "0" * 40),
                     ("reviewer", "pending"), ("reviewer", "TBD"),
                     ("commands", []), ("artifacts", []), ("limitations", "none"))
        for key, value in mutations:
            with self.subTest(key=key, value=value):
                invalid = copy.deepcopy(report)
                invalid[key] = value
                self.save_json(path, invalid)
                self.assert_invalid(self.roadmap_errors())

    def test_rejects_malformed_missing_and_template_reports(self):
        _, path = self.attach_report()
        self.write(path, "{broken json")
        self.assert_invalid(self.roadmap_errors())
        self.data["phases"][0]["evidence"][0]["record"] = "docs/project/evidence/missing.json"
        self.assert_invalid(self.roadmap_errors())
        template = "docs/project/evidence/report.example.json"
        self.save_json(template, {"outcome": "not_run"})
        self.data["phases"][0]["evidence"][0]["record"] = template
        self.assert_invalid(self.roadmap_errors())

    def test_rejects_missing_or_wrong_report_acceptance_ids(self):
        report, path = self.attach_report()
        for ids in ([], ["P99-A01"], ["P00-A01", "P00-A01"], "P00-A01"):
            with self.subTest(ids=ids):
                report["acceptance_ids"] = ids
                self.save_json(path, report)
                self.assert_invalid(self.roadmap_errors())

    def test_rejects_duplicate_evidence_references(self):
        self.attach_report()
        evidence = self.data["phases"][0]["evidence"]
        evidence.append(copy.deepcopy(evidence[0]))
        self.assert_invalid(self.roadmap_errors())

    def test_rejects_duplicate_record_ids_across_files(self):
        report, _ = self.attach_report()
        second = self.phase("P01", ["P00"])
        self.data["phases"].append(second)
        other, path = self.attach_report(second)
        other["record_id"] = report["record_id"]
        self.save_json(path, other)
        self.assert_invalid(self.roadmap_errors())

    def test_rejects_report_kind_level_mismatch(self):
        report, path = self.attach_report()
        report["evidence_level"] = "fpga_measured"
        self.save_json(path, report)
        self.assert_invalid(self.roadmap_errors())

    def test_governance_cannot_satisfy_rtl_gate(self):
        self.attach_report()
        phase = self.data["phases"][0]
        phase["status"] = "complete"
        phase["acceptance"][0]["evidence_level"] = "rtl_verified"
        self.assert_invalid(self.roadmap_errors())

    def test_accepts_compatible_rtl_report_metadata(self):
        report, path = self.attach_report()
        report.update(kind="rtl", evidence_level="rtl_verified", scope="Native TFR processor RTL fixture.")
        self.save_json(path, report)
        self.data["phases"][0]["status"] = "complete"
        self.data["phases"][0]["acceptance"][0]["evidence_level"] = "rtl_verified"
        self.assertEqual([], self.roadmap_errors())

    def test_passing_command_requires_real_integer_zero(self):
        report, path = self.attach_report()
        for code in (None, False, True, 0.0, "0", 1):
            with self.subTest(code=code):
                report["commands"][0]["exit_code"] = code
                self.save_json(path, report)
                self.assert_invalid(self.roadmap_errors())

    def test_passing_report_rejects_nonpassing_commands(self):
        report, path = self.attach_report()
        for result, code in (("fail", 1), ("not_run", None), ("blocked", None)):
            with self.subTest(result=result):
                invalid = copy.deepcopy(report)
                invalid["commands"].append({"command": "other-check", "result": result, "exit_code": code})
                self.save_json(path, invalid)
                self.assert_invalid(self.roadmap_errors())

    def test_failed_report_is_retained_but_cannot_close_phase(self):
        report, path = self.attach_report()
        report["outcome"] = "fail"
        report["commands"][0].update(result="fail", exit_code=1)
        report["reviewer"] = "pending"
        self.save_json(path, report)
        self.assertEqual([], self.roadmap_errors())
        self.data["phases"][0]["status"] = "complete"
        self.assert_invalid(self.roadmap_errors())

    def test_not_run_report_cannot_claim_zero_exit(self):
        report, path = self.attach_report()
        report["outcome"] = "not_run"
        report["commands"][0].update(result="not_run", exit_code=0)
        self.save_json(path, report)
        self.assert_invalid(self.roadmap_errors())
        report["commands"][0]["exit_code"] = None
        self.save_json(path, report)
        self.assertEqual([], self.roadmap_errors())

    def test_rejects_missing_tampered_and_invalid_artifact_hashes(self):
        report, path = self.attach_report()
        original = copy.deepcopy(report)
        for digest in ("0" * 64, "bad", None):
            with self.subTest(digest=digest):
                report["artifacts"][0]["sha256"] = digest
                self.save_json(path, report)
                self.assert_invalid(self.roadmap_errors())
        original["artifacts"][0]["path"] = "docs/project/evidence/absent.txt"
        self.save_json(path, original)
        self.assert_invalid(self.roadmap_errors())

    def test_rejects_artifact_and_report_path_escape(self):
        report, path = self.attach_report()
        report["artifacts"][0]["path"] = "../outside.txt"
        self.save_json(path, report)
        self.assert_invalid(self.roadmap_errors())
        self.data["phases"][0]["evidence"][0]["record"] = "../outside.json"
        self.assert_invalid(self.roadmap_errors())

    def test_rejects_artifact_symlink_escape_despite_matching_hash(self):
        report, path = self.attach_report()
        artifact = report["artifacts"][0]
        payload = (self.root / artifact["path"]).read_bytes()
        with tempfile.TemporaryDirectory(prefix="ai-gpu-external-artifact-") as outside:
            target = Path(outside) / "log.txt"
            target.write_bytes(payload)
            link = self.root / "docs/project/evidence/escape.txt"
            link.symlink_to(target)
            artifact["path"] = "docs/project/evidence/escape.txt"
            self.save_json(path, report)
            self.assert_invalid(self.roadmap_errors())


class ProjectTests(ProjectFixture):
    def test_complete_project_fixture_passes(self):
        self.assertEqual([], self.project_errors())

    def test_rejects_nonexistent_root(self):
        self.assert_invalid(check_project.validate_project(self.root / "missing"))

    def test_original_image_protection_cannot_be_removed_or_redefined(self):
        self.data["protected_assets"] = []
        self.assert_invalid(self.project_errors())
        payload = b"substitute"
        self.write(IMAGE_PATH, payload)
        self.data["protected_assets"] = [{"path": IMAGE_PATH, "sha256": hashlib.sha256(payload).hexdigest()}]
        self.assert_invalid(self.project_errors())

    def test_rejects_missing_root_document(self):
        (self.root / "ROADMAP.md").unlink()
        self.assert_invalid(self.project_errors())

    def test_rejects_duplicate_json_keys_and_nonfinite_numbers(self):
        self.save_json("docs/project/roadmap.json", self.data)
        raw = (self.root / "docs/project/roadmap.json").read_text(encoding="utf-8")
        duplicate = raw.replace('"schema_version": 1,', '"schema_version": 1, "schema_version": 1,', 1)
        self.write("docs/project/roadmap.json", duplicate)
        self.assert_invalid(check_project.validate_project(self.root))
        self.write("docs/project/roadmap.json", raw.replace('"schema_version": 1', '"schema_version": NaN', 1))
        self.assert_invalid(check_project.validate_project(self.root))

    def test_rejects_broken_project_link(self):
        self.write("docs/project/index.md", "# Guide\n\n[Missing](missing.md)\n")
        self.assert_invalid(self.project_errors())

    def test_accepts_valid_project_link_and_anchor(self):
        self.write("docs/project/index.md", "# Guide\n\n[Purpose](charter.md#purpose)\n")
        self.assertEqual([], self.project_errors())

    def test_rejects_broken_project_anchor(self):
        self.write("docs/project/index.md", "# Guide\n\n[Missing](charter.md#missing)\n")
        self.assert_invalid(self.project_errors())

    def test_ignores_code_fences_inline_code_and_external_links(self):
        self.write("docs/project/index.md", """# Guide

```md
[Example](missing.md)
```

~~~md
[Another example](also-missing.md)
~~~

`[Inline example](not-a-link.md)`
[Website](https://example.invalid/missing#anchor)
[Email](mailto:example@example.invalid)
""")
        self.assertEqual([], self.project_errors())

    def test_ignores_unrelated_historical_docs_index_link(self):
        self.write("docs/index.md", "# Existing documentation\n\n[Legacy](legacy-missing.md)\n")
        self.assertEqual([], self.project_errors())
        self.write("docs/index.md", "# Documentation\n\n[Project](project/missing.md)\n")
        self.assert_invalid(self.project_errors())

    def test_rejects_markdown_link_escape(self):
        self.write("docs/project/index.md", "# Guide\n\n[Outside](../../../outside.md)\n")
        self.assert_invalid(self.project_errors())

    def test_unreferenced_evidence_template_does_not_claim_acceptance(self):
        self.save_json("docs/project/evidence/report.example.json", {"outcome": "not_run", "reviewer": "pending"})
        self.assertEqual([], self.project_errors())

    def test_cli_success_and_failure_are_explicit(self):
        self.save_json("docs/project/roadmap.json", self.data)
        before = {path.relative_to(self.root): path.read_bytes()
                  for path in self.root.rglob("*") if path.is_file()}
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(0, check_project.main(["--root", str(self.root)]))
        after = {path.relative_to(self.root): path.read_bytes()
                 for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(before, after)
        self.data["phases"][0]["status"] = "complete"
        self.save_json("docs/project/roadmap.json", self.data)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertNotEqual(0, check_project.main(["--root", str(self.root)]))


if __name__ == "__main__":
    unittest.main()
