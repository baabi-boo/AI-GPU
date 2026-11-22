# SPDX-License-Identifier: Apache-2.0
"""Replay retained original workspace packets and reject rehashed corruptions."""

from contextlib import ExitStack
import copy
import hashlib
import json
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest import mock
import warnings
import zipfile

import p06_workspace_replay as replay


ROOT = Path(__file__).resolve().parents[2]
ORIGINALS = ROOT / "docs/project/evidence/p06-warm-workspace/originals"
REVISION = "13dc0d1fdb6d5322104e381aa342dc139c7bb80c"
TREE = "b10ca275377103ad94941847ee4efb1b3f296efd"
DIGESTS = {
    ("simx", "fp16"): "dec4bd9f2a57b808cbce046a63ed68849fcc6fe4271eeaea819c8b637189ac05",
    ("simx", "bf16"): "7775d29d06db73b2bc75341fc0bf0acce6415326bd6f4e976598a36778f5bd42",
    ("rtlsim", "fp16"): "3a8bc281ac24b32bd613fdf1096cea61b209f2b54a542b42fad3c39a2f1b6a7b",
    ("rtlsim", "bf16"): "64ff960a65582f76df9f1699fc70edacce075c6ed3764dbb2cb050611fabf760",
}
REPORT = "workspace/report.json"
PROCESS = "simx-fp16-per_operation"


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def descriptor(path, body):
    return {"path": path, "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)}


def edit_report(members, change):
    report = json.loads(members[REPORT])
    change(report)
    members[REPORT] = encoded(report)


def edit_snapshot(members, key, change):
    report = json.loads(members[REPORT])
    path = report[key]["path"]
    value = json.loads(members["workspace/" + path])
    change(value)
    body = encoded(value)
    members["workspace/" + path] = body
    report[key] = descriptor(path, body)
    members[REPORT] = encoded(report)


def replace_log(members, command_id, change):
    report = json.loads(members[REPORT])
    command = next(row for row in report["commands"] if row["id"] == command_id)
    path = command["log"]
    body = change(members["workspace/" + path])
    members["workspace/" + path] = body
    row = descriptor(path, body)
    command.update(log_sha256=row["sha256"], log_size_bytes=row["size_bytes"])
    for original in report["raw_logs"]:
        if original["path"] == path:
            original.update(row)
    members[REPORT] = encoded(report)


def edit_record(body, marker, change):
    lines = body.decode().splitlines()
    index = next(i for i, line in enumerate(lines) if line.startswith(marker + " "))
    row = json.loads(lines[index][len(marker) + 1:])
    change(row)
    lines[index] = marker + " " + encoded(row).decode().strip()
    return ("\n".join(lines) + "\n").encode()


def replace_build_body(members, relative, body):
    """Rehash every retained stage so original compiler validation sees the change."""
    report = json.loads(members[REPORT])
    variant = report["variants"][0]
    names = {relative}
    for stage in variant["retained_builds"]:
        path = "artifacts/" + variant["id"] + "/" + stage["stage"] + "/" + relative
        if "workspace/" + path in members:
            members["workspace/" + path] = body
            names.add(path)

    def update(value):
        if isinstance(value, dict):
            if set(value) == {"path", "sha256", "size_bytes"} and value["path"] in names:
                value.update(descriptor(value["path"], body))
            for child in value.values():
                update(child)
        elif isinstance(value, list):
            for child in value:
                update(child)

    update(report)
    members[REPORT] = encoded(report)


class WorkspaceReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.selections = [
            {"path": ORIGINALS / ("workspace-" + backend + "-" + fmt + ".zip"),
             "sha256": digest, "backend": backend, "format": fmt}
            for (backend, fmt), digest in DIGESTS.items()
        ]
        cls.execution_guards = []
        with ExitStack() as stack:
            for owner, name in ((subprocess, "run"), (subprocess, "Popen"),
                                (zipfile.ZipFile, "extract"), (zipfile.ZipFile, "extractall")):
                cls.execution_guards.append(stack.enter_context(mock.patch.object(
                    owner, name, side_effect=AssertionError("retained-data replay executed or extracted a payload"))))
            cls.matrix = replay.replay_matrix(cls.selections, expected_revision=REVISION)
        with zipfile.ZipFile(cls.selections[0]["path"]) as archive:
            cls.original = {row.filename: archive.read(row) for row in archive.infolist() if not row.is_dir()}

    @classmethod
    def tearDownClass(cls):
        for row in cls.selections:
            actual = hashlib.sha256(row["path"].read_bytes()).hexdigest()
            if actual != row["sha256"]:
                raise AssertionError("retained original archive changed: " + str(row["path"]))

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="p06-workspace-replay-test-")
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "mutated.zip"

    def write_archive(self, members, extra=()):
        with zipfile.ZipFile(self.path, "w", compression=zipfile.ZIP_STORED) as archive:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                for path, body in (*members.items(), *extra):
                    archive.writestr(path, body)
        return hashlib.sha256(self.path.read_bytes()).hexdigest()

    def check(self, members, *, extra=(), revision=REVISION, backend="simx", fmt="fp16", digest=None):
        actual = self.write_archive(members, extra)
        return replay.replay_archive(self.path, actual if digest is None else digest,
                                     expected_revision=revision, expected_backend=backend, expected_format=fmt)

    def reject(self, members, pattern, **kwargs):
        with self.assertRaisesRegex(ValueError, pattern):
            self.check(members, **kwargs)

    def changed_report(self, change):
        members = dict(self.original)
        edit_report(members, change)
        return members

    def cached_matrix_reject(self, results, pattern):
        with mock.patch.object(replay, "replay_archive", side_effect=results) as reader:
            with self.assertRaisesRegex(ValueError, pattern):
                replay.replay_matrix(self.selections, expected_revision=REVISION)
            self.assertEqual(reader.call_count, 4)

    def test_original_complete_matrix_has_exact_scope(self):
        result = self.matrix
        self.assertEqual(result["outcome"], "pass")
        self.assertEqual(result["source_revision"], REVISION)
        self.assertEqual(result["source_tree"], TREE)
        self.assertEqual(result["counts"], {"processes": 8, "launches": 32, "checked_words": 1024})
        self.assertTrue(result["full_matrix_completed"])
        self.assertEqual({(row["backend"], row["format"]) for row in result["variants"]}, set(DIGESTS))

    def test_original_variants_preserve_commands_sources_and_hosted_identity(self):
        for row in self.matrix["variants"]:
            with self.subTest(backend=row["backend"], fmt=row["format"]):
                self.assertEqual(row["commands_checked"], 21 if row["backend"] == "rtlsim" else 19)
                self.assertEqual(row["retained_source_files_checked"], 971)
                self.assertEqual(row["selected_counts"], {"processes": 2, "launches": 8, "checked_words": 256})
                self.assertEqual(row["hosted_job_identity"]["GITHUB_RUN_ID"], "44925627664")
                self.assertEqual(row["hosted_job_identity"]["GITHUB_RUN_ATTEMPT"], "1")
                self.assertEqual([(p["buffer_creates"], p["buffer_releases"]) for p in row["processes"]],
                                 [(12, 12), (3, 3)])
                self.assertFalse(row["full_matrix_completed"])

    def test_original_replay_executes_no_native_code_or_archive_extraction(self):
        for guard in self.execution_guards:
            guard.assert_not_called()
        for row in [self.matrix, *self.matrix["variants"]]:
            self.assertEqual(row["native_execution"], "not_run")
            for key in ("acceptance_claimed", "performance_acceptance", "phase_acceptance", "phase_complete"):
                self.assertIs(row[key], False)
        for row in self.matrix["variants"]:
            self.assertFalse(row["archive_read"]["retained_code_executed"])

    def test_rehashed_submodule_claims_match_retained_declarations_and_inventory_bound(self):
        for excessive in (False, True):
            members = dict(self.original)

            def change(source):
                inventory = source["checkout"]["submodules"]
                if excessive:
                    first = inventory["entries"][0]
                    inventory["entries"].extend(dict(first, path=first["path"] + "/nested" + str(index))
                                                for index in range(1001 - len(inventory["entries"])))
                else:
                    inventory["declared_count"] = 1

            for key in ("source_before", "source_after"):
                edit_snapshot(members, key, change)
            with self.subTest(excessive=excessive):
                self.reject(members, "submodule inventory|declared root submodule count")

    def test_external_digest_revision_backend_and_format_are_bound(self):
        for kwargs, pattern in (({"digest": "0" * 64}, "SHA-256|identity"),
                                ({"revision": "0" * 40}, "checkout.revision"),
                                ({"backend": "rtlsim"}, "command inventory|variant"),
                                ({"fmt": "bf16"}, "variant")):
            with self.subTest(kwargs=kwargs):
                self.reject(self.original, pattern, **kwargs)

    def test_invalid_external_selection_is_rejected_before_archive_access(self):
        for key, value in (("expected_revision", True), ("expected_backend", "xrt"), ("expected_format", "tf32")):
            args = {"expected_revision": REVISION, "expected_backend": "simx", "expected_format": "fp16", key: value}
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "external"):
                replay.replay_archive(self.path, "0" * 64, **args)

    def test_false_completeness_and_acceptance_claims_are_rejected(self):
        for key in ("acceptance_claimed", "performance_acceptance", "phase_acceptance", "phase_complete",
                    "full_matrix_requested", "full_matrix_completed"):
            with self.subTest(key=key):
                self.reject(self.changed_report(lambda r: r.update({key: True})), "report." + key)
        self.reject(self.changed_report(lambda r: r.update(selected_scope_completed=False)), "selected_scope_completed")
        self.reject(self.changed_report(lambda r: r["complete_matrix"].update(checked_words=1)), "complete_matrix")

    def test_wrong_counts_and_stored_observations_do_not_override_raw_output(self):
        self.reject(self.changed_report(lambda r: r["selected_counts"].update(checked_words=255)), "selected counts")
        self.reject(self.changed_report(lambda r: r["processes"][0]["observation"]["operations"][0]
                                      ["actual_bits"].__setitem__(0, "deadbeef")), "recomputed original output")

    def test_command_inventory_and_order_are_exact(self):
        self.reject(self.changed_report(lambda r: r["commands"].pop()), "command inventory")
        self.reject(self.changed_report(lambda r: r["commands"].insert(0, r["commands"].pop(1))), "command.*id")

    def test_command_argv_environment_timeout_and_cleanup_are_checked(self):
        changes = (("argv", ["/bin/true"]), ("timeout_seconds", 31), ("cleanup_complete", False),
                   ("exit_code", 1), ("process_started", False))
        for key, value in changes:
            with self.subTest(key=key):
                self.reject(self.changed_report(lambda r: r["commands"][0].update({key: value})), "command.*" + key)
        self.reject(self.changed_report(lambda r: r["commands"][0]["environment"].update(LD_PRELOAD="/tmp/inject.so")),
                    "sanitized environment")
        self.reject(self.changed_report(lambda r: r["commands"][1]["environment"].update(LANG="other")),
                    "command.*environment")

    def test_budget_and_resource_boundaries_are_enforced(self):
        for key, value in (("jobs", 3), ("max_rss_bytes", 8 * 1024**3), ("max_log_bytes", 1),
                           ("min_free_bytes", 0), ("build_timeout_seconds", 1801), ("run_timeout_seconds", 181)):
            with self.subTest(key=key):
                self.reject(self.changed_report(lambda r: r["budget"].update({key: value})), "budget|jobs|timeout")
        self.reject(self.changed_report(lambda r: r["resources_before"]["free_disk_bytes"].update(work=0)), "disk reserve")
        self.reject(self.changed_report(lambda r: r["resources_before"].update(available_memory_bytes=1)), "initial memory")
        self.reject(self.changed_report(lambda r: r["commands"][0].update(peak_rss_bytes=4 * 1024**3 + 1)), "peak RSS")

    def test_source_tree_revision_and_clean_checkout_are_checked(self):
        for field, value, pattern in (("tree", "invalid", "source tree"), ("revision", "0" * 40, "checkout.revision"),
                                       ("dirty", True, "checkout.dirty"), ("changed_paths", ["sw/runtime/ai/runtime.cpp"],
                                        "checkout.changed_paths")):
            with self.subTest(field=field):
                members = dict(self.original)
                for key in ("source_before", "source_after"):
                    edit_snapshot(members, key, lambda source: source["checkout"].update({field: value}))
                self.reject(members, pattern)

    def test_final_source_tools_and_dependencies_must_match_initial_snapshots(self):
        changes = (("source_after", lambda s: s["checkout"].update(tree="0" * 40), "source original/final"),
                   ("tools_after", lambda s: s["g++"].update(sha256="0" * 64), "tools original/final"),
                   ("dependencies_after", lambda s: s[0].update(sha256="0" * 64), "dependencies original/final"))
        for key, change, pattern in changes:
            with self.subTest(key=key):
                members = dict(self.original)
                edit_snapshot(members, key, change)
                self.reject(members, pattern)

    def test_stability_flags_hashes_and_chronology_are_rechecked(self):
        for key in ("source_stable", "tools_stable", "dependencies_stable", "retained_files_stable"):
            with self.subTest(key=key):
                self.reject(self.changed_report(lambda r: r.update({key: False})), "stable")
        self.reject(self.changed_report(lambda r: r["stability_checks"][0].update(source_sha256="0" * 64)),
                    "stability identity source")
        self.reject(self.changed_report(lambda r: r["stability_checks"][0].update(at="2000-01-01T00:00:00+00:00")),
                    "stability timestamps")

    def test_retained_source_bytes_and_required_member_are_verified(self):
        path = "workspace/artifacts/source/sw/runtime/ai/runtime.cpp"
        members = dict(self.original)
        members[path] += b"\n"
        self.reject(members, "identity|size|digest|SHA-256")
        members = dict(self.original)
        del members[path]
        self.reject(members, "missing")

    def test_rehashed_compiler_stamp_changes_are_rejected(self):
        relative = "sw/runtime/simx_rt_config.stamp"
        members = dict(self.original)
        original = members["workspace/artifacts/simx-fp16/frozen/" + relative]
        self.assertIn(b"-DITYPE=fp16", original)
        replace_build_body(members, relative, original.replace(b"-DITYPE=fp16", b"-DITYPE=bf16"))
        self.reject(members, "ITYPE|runtime.*format|compiler|configuration")

    def test_embedded_compiler_records_cannot_replace_original_stamps(self):
        self.reject(self.changed_report(lambda r: r["variants"][0]["compiler_records"][0]
                                      ["include_paths"].reverse()), "independent original compiler records")

    def test_rehashed_effective_header_log_is_revalidated(self):
        members = dict(self.original)
        replace_log(members, "simx-fp16-runtime-header", lambda body: body + b"#define SIMX_FUNCTIONAL 1\n")
        self.reject(members, "execution mode or instrumentation")

    def test_embedded_effective_header_macros_are_recomputed(self):
        self.reject(self.changed_report(lambda r: r["variants"][0]["effective_headers"]["runtime"]["macros"]
                                      .update(VX_CFG_NUM_THREADS="8")), "effective compiler configuration")

    def test_rehashed_binding_and_qualification_id_are_reconstructed(self):
        members = dict(self.original)
        report = json.loads(members[REPORT])
        path = report["processes"][0]["binding"]["path"]
        value = json.loads(members["workspace/" + path])
        value["policy"] = "reusable_single_tile"
        members["workspace/" + path] = encoded(value)
        report["processes"][0]["binding"] = descriptor(path, members["workspace/" + path])
        members[REPORT] = encoded(report)
        self.reject(members, "reconstructed execution binding")
        self.reject(self.changed_report(lambda r: r["processes"][0].update(qualification_id="0" * 64)),
                    "qualification identity")

    def test_rehashed_raw_numerical_output_is_independently_checked(self):
        members = dict(self.original)
        replace_log(members, PROCESS, lambda body: edit_record(body, "P06_WORKSPACE_RESULT",
                    lambda row: row["actual_bits"].__setitem__(0, "deadbeef")))
        self.reject(members, "actual_bits|numerical|output|expected|mismatch")

    def test_missing_raw_log_and_record_are_rejected(self):
        members = dict(self.original)
        del members["workspace/logs/" + PROCESS + ".log"]
        self.reject(members, "missing")
        members = dict(self.original)
        replace_log(members, PROCESS, lambda body: b"\n".join(body.splitlines()[1:]) + b"\n")
        self.reject(members, "record|operation|sequence|four")

    def test_raw_log_failure_and_wrong_qualification_are_rejected(self):
        for change, pattern in ((lambda body: body + b"ERROR: failed retained command\n", "failure|ERROR|failed"),
                                (lambda body: edit_record(body, "P06_WORKSPACE_RESULT",
                                 lambda row: row.update(qualification_id="0" * 64)), "qualification")):
            with self.subTest(pattern=pattern):
                members = dict(self.original)
                replace_log(members, PROCESS, change)
                self.reject(members, pattern)

    def test_raw_log_inventory_and_packet_member_set_are_exact(self):
        self.reject(self.changed_report(lambda r: r["raw_logs"].pop()), "raw-log inventory")
        members = dict(self.original, **{"workspace/unclaimed.json": b"{}"})
        self.reject(members, "member inventory")

    def test_hosted_revision_workflow_and_provisioning_are_bound(self):
        for field, value in (("GITHUB_SHA", "0" * 40), ("P06_WORKSPACE_FORMAT", "bf16"),
                             ("GITHUB_RUN_ID", "0"), ("GITHUB_REF", "refs/heads/other")):
            with self.subTest(field=field):
                members = dict(self.original)
                job = json.loads(members["job.json"])
                job[field] = value
                members["job.json"] = encoded(job)
                self.reject(members, "hosted")
        members = dict(self.original)
        members["workflow.yml"] += b"\n"
        self.reject(members, "workflow source")
        members = dict(self.original)
        provision = json.loads(members["python-provision.json"])
        provision["python3_on_path"] = "/tmp/python3"
        members["python-provision.json"] = encoded(provision)
        self.reject(members, "provisioned interpreter")

    def test_duplicate_or_incomplete_matrix_is_rejected_before_replay(self):
        for selections, pattern in ((self.selections[:3], "exactly four"),
                                    ([self.selections[0]] * 4, "duplicate workspace variant")):
            with self.subTest(pattern=pattern), mock.patch.object(replay, "replay_archive") as reader:
                with self.assertRaisesRegex(ValueError, pattern):
                    replay.replay_matrix(selections, expected_revision=REVISION)
                reader.assert_not_called()

    def test_individually_valid_rehashed_packet_cannot_join_another_hosted_run(self):
        members = dict(self.original)
        job = json.loads(members["job.json"])
        job["GITHUB_RUN_ID"] = "44925627665"
        members["job.json"] = encoded(job)
        changed = self.check(members)
        self.assertEqual(changed["outcome"], "pass")
        results = copy.deepcopy(self.matrix["variants"])
        results[0] = changed
        self.cached_matrix_reject(results, "matrix hosted GITHUB_RUN_ID")

    def test_matrix_requires_same_source_tree_dependencies_tools_and_attempt(self):
        for key, change, pattern in (
            ("tree", lambda r: r.update(source_tree="0" * 40), "matrix source_tree"),
            ("dependencies", lambda r: r["dependencies"][0].update(sha256="0" * 64), "matrix dependencies"),
            ("tools", lambda r: r["tools"]["g++"].update(sha256="0" * 64), "matrix tool g"),
            ("attempt", lambda r: r["hosted_job_identity"].update(GITHUB_RUN_ATTEMPT="2"), "matrix hosted GITHUB_RUN_ATTEMPT"),
            ("hosted", lambda r: r.update(hosted_job_identity=None), "mixed hosted/non-hosted"),
        ):
            with self.subTest(key=key):
                results = copy.deepcopy(self.matrix["variants"])
                change(results[1])
                self.cached_matrix_reject(results, pattern)

    def test_traversal_and_absolute_zip_members_are_rejected(self):
        for name in ("../escape", "/absolute", "workspace/../escape", "workspace\\escape", "C:drive"):
            with self.subTest(name=name):
                self.reject(self.original, "member name", extra=((name, b"not a retained member"),))

    def test_symlink_and_duplicate_zip_entries_are_rejected(self):
        link = zipfile.ZipInfo("workspace/link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        self.reject(self.original, "symlink|special", extra=((link, b"/tmp/unused-target"),))
        self.reject(self.original, "duplicate", extra=((REPORT, self.original[REPORT]),))

    def test_missing_report_and_duplicate_json_keys_are_rejected(self):
        members = dict(self.original)
        del members[REPORT]
        self.reject(members, "missing")
        members = dict(self.original)
        members[REPORT] = b'{"schema_version":1,"schema_version":1}'
        self.reject(members, "duplicate JSON field")


if __name__ == "__main__":
    unittest.main()
