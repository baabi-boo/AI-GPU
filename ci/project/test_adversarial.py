# SPDX-License-Identifier: Apache-2.0
"""Adversarial metadata and Markdown tests using bounded local fixtures."""

import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import check_project
from test_check_project import IMAGE_PATH, ProjectFixture


class EvidenceAdversarialTests(ProjectFixture):
    def setUp(self):
        super().setUp()
        self.report, self.report_path = self.attach_report()
        self.data["phases"][0]["status"] = "complete"

    def reject_report(self, value):
        self.save_json(self.report_path, value)
        self.assert_invalid(self.roadmap_errors())

    def test_report_field_type_mutations_return_diagnostics(self):
        string_fields = ("record_id", "scope", "source_revision", "configuration", "reviewer")
        list_fields = ("acceptance_ids", "commands", "artifacts", "limitations")
        mutations = {key: (None, [], {}, 0, True) for key in string_fields}
        mutations.update({key: (None, {}, "not a list", True) for key in list_fields})
        mutations.update({key: (None, [], {}, False, "unknown")
                          for key in ("kind", "outcome", "evidence_level")})
        mutations["schema_version"] = (None, [], {}, "1", True, 1.0, 0)
        for key, values in mutations.items():
            for value in values:
                with self.subTest(field=key, value=value):
                    report = copy.deepcopy(self.report)
                    report[key] = value
                    self.reject_report(report)

    def test_report_list_members_are_validated(self):
        for field in ("commands", "artifacts", "acceptance_ids", "limitations"):
            for value in (None, [], {}, 1, True):
                with self.subTest(field=field, value=value):
                    report = copy.deepcopy(self.report)
                    report[field] = [value]
                    self.reject_report(report)

    def test_nested_objects_reject_missing_and_unknown_fields(self):
        for field in ("commands", "artifacts"):
            for key in self.report[field][0]:
                with self.subTest(field=field, missing=key):
                    report = copy.deepcopy(self.report)
                    del report[field][0][key]
                    self.reject_report(report)
            with self.subTest(field=field, unknown=True):
                report = copy.deepcopy(self.report)
                report[field][0]["unverified_override"] = True
                self.reject_report(report)

    def test_duplicate_keys_inside_reports_are_rejected(self):
        original = json.dumps(self.report, indent=2)
        for old, new in (
                ('"outcome": "pass"', '"outcome": "fail", "outcome": "pass"'),
                ('"exit_code": 0', '"exit_code": 1, "exit_code": 0')):
            with self.subTest(field=old):
                self.write(self.report_path, original.replace(old, new, 1))
                self.assert_invalid(self.roadmap_errors())

    def test_unreadable_or_nonobject_reports_fail_closed(self):
        payloads = (b"[]", b'"report"', b"null", b"\xff",
                    b'{"value": Infinity}',
                    ('{"value":' + "[" * 1100 + "0" + "]" * 1100 + "}").encode())
        for payload in payloads:
            with self.subTest(prefix=payload[:30]):
                self.write(self.report_path, payload)
                self.assert_invalid(self.roadmap_errors())

    def test_report_text_limit_is_checked_without_a_large_file(self):
        report = copy.deepcopy(self.report)
        report["scope"] = "x" * 4096
        self.save_json(self.report_path, report)
        with patch.object(check_project, "MAX_TEXT_BYTES", 2048):
            errors = self.roadmap_errors()
        self.assert_invalid(errors)
        self.assertTrue(any(self.report_path in error and "exceeds" in error for error in errors))

    def test_oversized_artifact_is_rejected_before_opening(self):
        target = self.root / self.report["artifacts"][0]["path"]
        original_stat, original_open = Path.stat, Path.open
        opened = []

        def enlarged_stat(path, *args, **kwargs):
            result = original_stat(path, *args, **kwargs)
            if path == target:
                fields = list(result)
                fields[6] = check_project.MAX_ARTIFACT_BYTES + 1
                return os.stat_result(fields)
            return result

        def record_open(path, *args, **kwargs):
            opened.append(path)
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "stat", enlarged_stat), patch.object(Path, "open", record_open):
            self.assert_invalid(self.roadmap_errors())
        self.assertNotIn(target, opened)

    def test_artifact_size_limit_is_inclusive(self):
        target = self.root / self.report["artifacts"][0]["path"]
        original_stat = Path.stat

        def boundary_stat(path, *args, **kwargs):
            result = original_stat(path, *args, **kwargs)
            if path == target:
                fields = list(result)
                fields[6] = check_project.MAX_ARTIFACT_BYTES
                return os.stat_result(fields)
            return result

        with patch.object(Path, "stat", boundary_stat):
            self.assertEqual([], self.roadmap_errors())

    def test_report_symlink_cannot_escape_even_with_valid_contents(self):
        with tempfile.TemporaryDirectory(prefix="ai-gpu-report-outside-") as outside:
            target = Path(outside) / "valid.json"
            target.write_text(json.dumps(self.report), encoding="utf-8")
            alias = "docs/project/evidence/outside.json"
            (self.root / alias).symlink_to(target)
            self.data["phases"][0]["evidence"][0]["record"] = alias
            self.assert_invalid(self.roadmap_errors())

    def test_symlink_alias_does_not_hide_duplicate_evidence(self):
        alias = "docs/project/evidence/alias.json"
        (self.root / alias).symlink_to(self.root / self.report_path)
        self.data["phases"][0]["evidence"].append({"acceptance_id": "P00-A01", "record": alias})
        self.assert_invalid(self.roadmap_errors())

    def test_shared_report_must_cover_each_referenced_criterion(self):
        phase = self.data["phases"][0]
        second = copy.deepcopy(phase["acceptance"][0])
        second["id"] = "P00-A02"
        phase["acceptance"].append(second)
        phase["evidence"].append({"acceptance_id": second["id"], "record": self.report_path})
        report = copy.deepcopy(self.report)
        report["acceptance_ids"].append(second["id"])
        self.save_json(self.report_path, report)
        self.assertEqual([], self.roadmap_errors())
        self.save_json(self.report_path, self.report)
        self.assert_invalid(self.roadmap_errors())

    def test_cached_report_is_rechecked_against_each_required_level(self):
        later = self.phase("P01", ["P00"])
        later["status"] = "complete"
        later["evidence"] = [{"acceptance_id": "P01-A01", "record": self.report_path}]
        self.data["phases"].append(later)
        report = copy.deepcopy(self.report)
        report["acceptance_ids"].append("P01-A01")
        self.save_json(self.report_path, report)
        self.assertEqual([], self.roadmap_errors())
        later["acceptance"][0]["evidence_level"] = "rtl_verified"
        self.assert_invalid(self.roadmap_errors())

    def test_retained_failure_does_not_replace_removed_passing_evidence(self):
        failed = copy.deepcopy(self.report)
        failed.update(record_id="failed-attempt", outcome="fail", reviewer="pending")
        failed["commands"][0].update(result="fail", exit_code=1)
        failed_path = "docs/project/evidence/failed.json"
        self.save_json(failed_path, failed)
        failed_ref = {"acceptance_id": "P00-A01", "record": failed_path}
        self.data["phases"][0]["evidence"].append(failed_ref)
        self.assertEqual([], self.roadmap_errors())
        self.data["phases"][0]["evidence"] = [failed_ref]
        self.assert_invalid(self.roadmap_errors())

    def test_secondary_malformed_report_cannot_hide_behind_a_pass(self):
        bad_path = "docs/project/evidence/broken.json"
        self.write(bad_path, "{broken")
        self.data["phases"][0]["status"] = "in_progress"
        self.data["phases"][0]["evidence"].append({"acceptance_id": "P00-A01", "record": bad_path})
        self.assert_invalid(self.roadmap_errors())

    def test_reopening_a_dependency_invalidates_completed_descendants(self):
        middle = self.phase("P01", ["P00"])
        final = self.phase("P02", ["P01"])
        for phase in (middle, final):
            phase["status"] = "complete"
            self.attach_report(phase)
        self.data["phases"].extend([final, middle])
        self.assertEqual([], self.roadmap_errors())
        self.data["phases"][0]["status"] = "blocked"
        self.assert_invalid(self.roadmap_errors())
        middle["status"] = final["status"] = "in_progress"
        self.assertEqual([], self.roadmap_errors())

    def test_malformed_reference_members_return_diagnostics(self):
        for value in (None, [], {}, 1, True, {"acceptance_id": []},
                      {"acceptance_id": "P00-A01", "record": []},
                      {"acceptance_id": "P01-A01", "record": self.report_path}):
            with self.subTest(reference=value):
                self.data["phases"][0]["evidence"] = [value]
                self.assert_invalid(self.roadmap_errors())


class MarkdownAdversarialTests(ProjectFixture):
    def test_reference_labels_are_case_and_whitespace_normalized(self):
        self.write("docs/project/index.md", """# Guide

[Purpose][  CONTRACT  ]
[contract][]

[Contract]:
  <charter.md#purpose> "Numerical contract"
""")
        self.assertEqual([], self.project_errors())

    def test_duplicate_setext_and_explicit_anchors_resolve(self):
        self.write("docs/project/charter.md", """# Contract

## Results
## Results

Numerical notes
--------------

<a id="native-proof"></a>
""")
        self.write("docs/project/index.md", """# Guide

[Second result](charter.md#results-1)
[Notes](charter.md#numerical-notes)
[Native](charter.md#native-proof)
""")
        self.assertEqual([], self.project_errors())

    def test_fenced_headings_cannot_supply_real_anchors(self):
        self.write("docs/project/charter.md", "# Contract\n\n~~~md\n## Fake result\n~~~\n")
        self.write("docs/project/index.md", "[Result](charter.md#fake-result)\n")
        self.assert_invalid(self.project_errors())

    def test_percent_encoded_paths_remain_inside_the_repository(self):
        self.write("docs/project/native notes.md", "# Notes\n")
        self.write("docs/project/index.md", "[Notes](native%20notes.md#notes)\n")
        self.assertEqual([], self.project_errors())
        self.write("docs/project/index.md", "[Outside](%2e%2e/%2e%2e/%2e%2e/outside.md)\n")
        self.assert_invalid(self.project_errors())

    def test_balanced_parentheses_in_local_link_are_supported(self):
        self.write("docs/project/native(TFR).md", "# Native\n")
        self.write("docs/project/index.md", "[Native](native(TFR).md#native)\n")
        self.assertEqual([], self.project_errors())

    def test_escaped_bracket_is_literal_text_not_a_link(self):
        self.write("docs/project/index.md", "# Guide\n\n\\[example](not-a-link.md)\n")
        self.assertEqual([], self.project_errors())

    def test_comment_hidden_image_cannot_satisfy_embed_requirement(self):
        self.write("README.md", '# Project\n\n<!-- <img src="' + IMAGE_PATH + '"> -->\n')
        self.assert_invalid(self.project_errors())

    def test_invalid_utf8_project_document_is_rejected(self):
        self.write("docs/project/index.md", b"# Guide\n\xff")
        self.assert_invalid(self.project_errors())


if __name__ == "__main__":
    unittest.main()
