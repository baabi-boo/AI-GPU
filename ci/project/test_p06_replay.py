# SPDX-License-Identifier: Apache-2.0
"""Author-disjoint retained-data replay tests; all packets are synthetic.

The positive producer simulates every external observation. These tests prove
reader behavior and corruption rejection, never native execution or acceptance.
"""

from contextlib import ExitStack, redirect_stdout
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest import mock
import warnings
import zipfile

import p06_replay as replay
from p06_test_packets import REVISION, descriptor, encoded, synthetic_packet, write_archive


REPORT = "baseline/report.json"


def edit_report(members, change):
    report = json.loads(members[REPORT])
    change(report)
    members[REPORT] = encoded(report)


def edit_snapshot(members, key, change):
    report = json.loads(members[REPORT])
    row = report[key]
    name = "baseline/" + row["path"]
    value = json.loads(members[name])
    change(value)
    members[name] = encoded(value)
    report[key] = descriptor(row["path"], members[name])
    members[REPORT] = encoded(report)


def replace_log(members, command_id, change):
    report = json.loads(members[REPORT])
    command = next(row for row in report["commands"] if row["id"] == command_id)
    name = "baseline/" + command["log"]
    members[name] = change(members[name])
    command.update(log_sha256=hashlib.sha256(members[name]).hexdigest(),
                   log_size_bytes=len(members[name]))
    members[REPORT] = encoded(report)


def edit_record(body, marker, change):
    lines = body.decode("utf-8").splitlines()
    index = next(i for i, line in enumerate(lines) if line.startswith(marker + " "))
    value = json.loads(lines[index][len(marker) + 1:])
    change(value)
    lines[index] = marker + " " + json.dumps(value, separators=(",", ":"))
    return ("\n".join(lines) + "\n").encode("utf-8")


def replace_source_body(members, relative, body):
    """Keep source descriptors internally consistent while breaking a frozen pin."""
    name = "artifacts/source/" + relative
    members["baseline/" + name] = body

    def source_change(source):
        for row in source["files"] + source["checkout"]["inputs"]:
            if row["path"] == relative:
                row.update(descriptor(relative, body))
    for key in ("source_before", "source_after"):
        edit_snapshot(members, key, source_change)

    def retained_change(report):
        for row in report["retained_sources"]:
            if row["path"] == name:
                row.update(descriptor(name, body))
    edit_report(members, retained_change)


def replace_build_body(members, relative, body):
    """Rehash every stage and report identity to reach semantic build checks."""
    report = json.loads(members[REPORT])
    variant = report["variants"][0]
    names = {relative}
    for stage in variant["retained_builds"]:
        name = "artifacts/" + variant["id"] + "/" + stage["stage"] + "/" + relative
        if "baseline/" + name in members:
            members["baseline/" + name] = body
            names.add(name)

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


def hosted(members):
    """Synthetic outer workflow observations; these do not authenticate GitHub."""
    members = dict(members)
    report = json.loads(members[REPORT])
    tools = json.loads(members["baseline/" + report["tools_before"]["path"]])
    workflow = members["baseline/artifacts/source/.github/workflows/p06-baseline.yml"]
    members["workflow.yml"] = workflow
    members["job.json"] = encoded({
        "GITHUB_SHA": REVISION, "GITHUB_EVENT_NAME": "push", "GITHUB_RUN_ID": "123456789",
        "GITHUB_RUN_ATTEMPT": "1", "GITHUB_JOB": "baseline", "GITHUB_REPOSITORY": "baabi-boo/AI-GPU",
        "GITHUB_REF": "refs/heads/master", "P06_BACKEND": "simx", "P06_FORMAT": report["formats"][0],
        "scope": "simx-native-baseline", "native_execution": "not_run", "acceptance_claimed": False,
        "workflow_sha256": hashlib.sha256(workflow).hexdigest(),
    })
    members["python-provision.json"] = encoded({
        "python_version": [3, 12, 14], "implementation": "CPython", "platform": "linux",
        "executable": tools["python3"]["resolved_path"], "python3_on_path": tools["python3"]["path"],
    })
    return members


class ReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packets = {fmt: synthetic_packet(fmt) for fmt in ("fp16", "bf16")}

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="p06-replay-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "original.zip"

    def check(self, members=None, *, fmt="fp16", revision=REVISION, sha256=None, prefix="baseline"):
        digest = write_archive(self.path, self.packets[fmt] if members is None else members)
        return replay.replay_archive(self.path, digest if sha256 is None else sha256,
                                     expected_revision=revision, expected_format=fmt, prefix=prefix)

    def reject(self, members, pattern=".", **kwargs):
        with self.assertRaisesRegex(ValueError, pattern):
            self.check(members, **kwargs)

    def changed_report(self, change):
        members = dict(self.packets["fp16"])
        edit_report(members, change)
        return members

    def test_both_formats_replay_after_source_build_and_tools_are_deleted(self):
        for fmt, members in self.packets.items():
            with self.subTest(fmt=fmt):
                report = json.loads(members[REPORT])
                for path in report["paths"].values():
                    if path is not None:
                        self.assertFalse(Path(path).exists())
                result = self.check(members, fmt=fmt)
                self.assertEqual((result["outcome"], result["native_execution"]), ("pass", "not_run"))
                self.assertFalse(result["acceptance_claimed"])
                self.assertFalse(result["phase_complete"])
                self.assertEqual(result["commands_checked"], 45)
                self.assertEqual(result["summary"]["inventory"], {
                    "workloads": 4, "warmup_processes": 4, "measured_processes": 20,
                    "total_processes": 24, "warmup_launches": 6, "measured_launches": 30,
                    "total_launches": 36,
                })
                self.assertFalse(result["summary"]["full_matrix"])
                self.assertFalse(result["archive_read"]["retained_code_executed"])
                self.assertIsNone(result["hosted_job_identity"])
                self.assertEqual(result["trusted_archive_reader"]["sha256"],
                                 "4144becd4fe3c829380f7e66cdb66f7cf073b5e189c2620cd60c62940b9317d3")
                self.assertEqual(len(result["trusted_replay_sources"]), 19)

    def test_replay_never_executes_extracts_or_opens_recorded_roots(self):
        members = dict(self.packets["fp16"])
        members["baseline/untrusted.py"] = b"raise AssertionError('archived code executed')\n"
        report = json.loads(members[REPORT])
        roots = tuple(Path(value) for value in report["paths"].values() if value is not None)
        original_open, original_os_open = Path.open, os.open

        def guard(path):
            if isinstance(path, (str, bytes, os.PathLike)):
                candidate = Path(os.fsdecode(path))
                self.assertFalse(any(candidate == root or root in candidate.parents for root in roots),
                                 "replay accessed a recorded runner root: " + str(candidate))

        def path_open(path, *args, **kwargs):
            guard(path)
            return original_open(path, *args, **kwargs)

        def os_open(path, *args, **kwargs):
            guard(path)
            return original_os_open(path, *args, **kwargs)

        with ExitStack() as patches:
            patches.enter_context(mock.patch.object(Path, "open", path_open))
            patches.enter_context(mock.patch.object(os, "open", os_open))
            for target, name in ((subprocess, "Popen"), (subprocess, "run"), (os, "system"),
                                 (zipfile.ZipFile, "extract"), (zipfile.ZipFile, "extractall")):
                patches.enter_context(mock.patch.object(target, name, side_effect=AssertionError(name)))
            self.assertEqual(self.check(members)["outcome"], "pass")

    def test_external_digest_revision_format_and_prefix_are_required(self):
        self.reject(self.packets["fp16"], "SHA-256|identity", sha256="0" * 64)
        self.reject(self.packets["fp16"], "revision", revision="b" * 40)
        self.reject(self.packets["fp16"], "formats", fmt="bf16")
        self.reject(self.packets["fp16"], "member name", prefix="../baseline")
        with self.assertRaisesRegex(ValueError, "external source revision"):
            replay.replay_archive(self.path, "0" * 64, expected_revision=True, expected_format="fp16")
        with self.assertRaisesRegex(ValueError, "external format"):
            replay.replay_archive(self.path, "0" * 64, expected_revision=REVISION, expected_format="tf32")

    def test_archive_names_duplicates_symlinks_and_trailing_bytes_are_rejected(self):
        for name in ("../escape", "/absolute", "a/../b", "a\\b", "C:drive"):
            with self.subTest(name=name):
                self.reject({name: b"not a packet"}, "member name")
        for kind in ("duplicate", "symlink", "trailing"):
            with self.subTest(kind=kind):
                with zipfile.ZipFile(self.path, "w") as archive, warnings.catch_warnings():
                    warnings.simplefilter("ignore", UserWarning)
                    archive.writestr("baseline/report.json", b"{}")
                    if kind == "duplicate":
                        archive.writestr("baseline/report.json", b"{}")
                    elif kind == "symlink":
                        link = zipfile.ZipInfo("link")
                        link.create_system = 3
                        link.external_attr = (stat.S_IFLNK | 0o777) << 16
                        archive.writestr(link, b"/etc/passwd")
                if kind == "trailing":
                    with self.path.open("ab") as stream:
                        stream.write(b"trailing bytes")
                digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
                with self.assertRaisesRegex(ValueError, "duplicate|symlink|special|ZIP|directory|comment"):
                    replay.replay_archive(self.path, digest, expected_revision=REVISION, expected_format="fp16")

    def test_archive_file_symlink_and_changed_bytes_do_not_match_intake(self):
        digest = write_archive(self.path, {"one": b"data"})
        alias = self.root / "alias.zip"
        alias.symlink_to(self.path)
        with self.assertRaisesRegex(ValueError, "canonical|symlink"):
            replay.replay_archive(alias, digest, expected_revision=REVISION, expected_format="fp16")
        self.path.write_bytes(self.path.read_bytes() + b"changed")
        with self.assertRaisesRegex(ValueError, "identity|SHA-256"):
            replay.replay_archive(self.path, digest, expected_revision=REVISION, expected_format="fp16")

    def test_pinned_archive_reader_charges_failed_crc_reads_and_detects_live_changes(self):
        api = replay._archive_api()
        with zipfile.ZipFile(self.path, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr("payload", b"uniquely marked body")
        raw = self.path.read_bytes()
        self.assertEqual(raw.count(b"uniquely marked body"), 1)
        self.path.write_bytes(raw.replace(b"uniquely marked body", b"Uniquely marked body"))
        digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
        with api.ArchiveReader(self.path, digest) as archive:
            with self.assertRaisesRegex(ValueError, "member payload"):
                archive.read("payload")
            receipt = archive.receipt()
            self.assertEqual(receipt["read_attempts"], 1)
            self.assertEqual(receipt["charged_read_bytes"], len(b"uniquely marked body"))
            with mock.patch.object(api, "READ_ATTEMPTS", 1), self.assertRaisesRegex(ValueError, "aggregate"):
                archive.read("payload")
        digest = write_archive(self.path, {"payload": b"original"})
        archive = api.ArchiveReader(self.path, digest)
        self.path.write_bytes(self.path.read_bytes() + b"changed during review")
        with self.assertRaisesRegex(ValueError, "changed during its audit"):
            archive.close()
        self.assertTrue(archive._closed)

    def test_report_json_rejects_duplicates_nonfinite_numbers_and_excessive_depth(self):
        for body in (b'{"schema_version":1,"schema_version":1}', b'{"duration":NaN}',
                     b"[" * 66 + b"0" + b"]" * 66):
            with self.subTest(body=body[:40]):
                self.reject({REPORT: body}, "JSON")

    def test_report_claims_and_complete_command_inventory_are_exact(self):
        for field, value in (("development", True), ("acceptance_claimed", True),
                             ("full_matrix_completed", True), ("schema_version", True)):
            with self.subTest(field=field):
                self.reject(self.changed_report(lambda report: report.update({field: value})), "report")
        self.reject(self.changed_report(lambda report: report["commands"].pop()), "45 original commands")

    def test_resource_and_process_receipts_preserve_exact_limits_and_cleanup(self):
        changes = (
            (lambda report: report["budget"].update(max_rss_bytes=8 * 1024**3), "budget.max_rss_bytes"),
            (lambda report: report["resources_before"]["free_disk_bytes"].update(work=0), "disk reserve"),
            (lambda report: report["commands"][0].update(cleanup_complete=False), "cleanup_complete"),
            (lambda report: report["commands"][0].update(process_started=False), "process_started"),
            (lambda report: report["commands"][0].update(exit_code=True), "exit_code"),
            (lambda report: report["commands"][0].update(peak_rss_bytes=4 * 1024**3 + 1), "peak RSS"),
            (lambda report: report["commands"][0].update(duration_seconds=41), "duration"),
        )
        for change, pattern in changes:
            with self.subTest(check=pattern):
                self.reject(self.changed_report(change), pattern)

    def test_exact_argv_environment_cwd_and_recorded_paths_are_checked(self):
        changes = (
            (lambda report: report["commands"][0]["argv"].append("--injected"), "argv"),
            (lambda report: report["commands"][0]["environment"].update(LD_PRELOAD="/untrusted.so"), "environment"),
            (lambda report: report["commands"][0].update(cwd=report["paths"]["tools"]), "cwd"),
            (lambda report: report["paths"].update(source="/tmp/../source"), "member name"),
            (lambda report: report["paths"].update(output=report["paths"]["work"] + "/packet"), "overlap"),
        )
        for change, pattern in changes:
            with self.subTest(check=pattern):
                self.reject(self.changed_report(change), pattern)

    def test_retained_source_helper_and_binding_conservation(self):
        members = dict(self.packets["fp16"])
        members["baseline/artifacts/source/ci/project/p06_execute.py"] += b"# altered\n"
        self.reject(members, "identity|descriptor")
        self.reject(self.changed_report(lambda report: report["loaded_helpers"].pop()), "loaded helpers")
        self.reject(self.changed_report(lambda report: report["variants"][0].update(qualification_id="0" * 64)),
                    "binding digest")
        members = dict(self.packets["fp16"])
        edit_snapshot(members, "source_after", lambda source: source["checkout"].update(tree="a" * 40))
        self.reject(members, "before/after")
        self.reject(self.changed_report(lambda report: report["source_before"].update(path="../source-before.json")),
                    "member name")
        members = dict(self.packets["fp16"])
        members["baseline/logs/version-gpp.log"] += b"unrecorded log bytes\n"
        self.reject(members, "original command log")

    def test_rehashed_source_pin_and_version_metadata_corruption_are_rejected(self):
        members = dict(self.packets["fp16"])
        source = "sim/simx/core.cpp"
        replace_source_body(members, source, members["baseline/artifacts/source/" + source] + b"// drift\n")
        self.reject(members, "frozen source pin differs")
        for change, pattern in ((lambda source: source["checkout"]["pins"].update(TOOLCHAIN_REV="forged"), "version pins"),
                                (lambda source: source["files"].append(dict(source["files"][0])), "duplicate path")):
            members = dict(self.packets["fp16"])
            for key in ("source_before", "source_after"):
                edit_snapshot(members, key, change)
            with self.subTest(check=pattern):
                self.reject(members, pattern)

    def test_build_stages_and_final_binary_identity_must_be_conserved(self):
        self.reject(self.changed_report(lambda report: report["variants"][0]["retained_builds"].pop(1)),
                    "build stage")
        self.reject(self.changed_report(lambda report: report["variants"][0]["artifacts_after"][0].update(sha256="0" * 64)),
                    "artifact stability")

    def test_rehashed_probe_copy_config_and_raw_stamp_semantics_are_checked(self):
        cases = (
            ("p06-header-check/include-probe.cpp", b'#include "/forced/header.h"\n', "ordinary header include probe"),
            ("sw/runtime/common.mk", b"CONFIGS += -DSIMX_FUNCTIONAL\n", "generated copied source"),
            ("config.mk", b"XLEN ?= 32\n", "generated config XLEN"),
            (".config.stamp", b"XLEN=64 XLEN=32\n", "repeats settings"),
            ("sw/runtime/simx_config.stamp", None, "changes timing mode"),
        )
        for relative, body, pattern in cases:
            with self.subTest(path=relative):
                members = dict(self.packets["fp16"])
                if body is None:
                    body = members["baseline/artifacts/simx-fp16/frozen/" + relative].rstrip() + b" -DSIMX_FUNCTIONAL\n"
                replace_build_body(members, relative, body)
                self.reject(members, pattern)

    def test_effective_header_original_log_and_compiler_records_are_recomputed(self):
        members = dict(self.packets["fp16"])
        replace_log(members, "simx-fp16-matmul-runtime-header",
                    lambda body: body + b"#define SIMX_FUNCTIONAL 1\n")
        self.reject(members, "changes timing mode")
        self.reject(self.changed_report(lambda report: report["variants"][0]["applications"]["matmul"]
                    ["compiler_records"][0]["include_paths"].reverse()), "compiler records")

    def test_raw_numerical_failures_and_unsigned_counters_override_stored_pass(self):
        command = "simx-fp16-single-dense_boundaries-warmup-0"
        changes = (
            (lambda body: body + b"ERROR: retained failure\n", "failure|ERROR"),
            (lambda body: edit_record(body, "P03_RESULT", lambda row: row["actual_bits"].__setitem__(0, "deadbeef")),
             "output|actual_bits|numerical|expected"),
            (lambda body: edit_record(body, "P06_END", lambda row: row["counters"][0].update(value=1 << 64)),
             "uint64"),
        )
        for change, pattern in changes:
            with self.subTest(check=pattern):
                members = dict(self.packets["fp16"])
                replace_log(members, command, change)
                self.reject(members, pattern)

    def test_derived_observation_and_entire_model_span_are_rechecked(self):
        self.reject(self.changed_report(lambda report: report["samples"][0]["observation"]
                    ["counter_deltas"][0].update(value=1001)), "original sample replay")

        def too_short(report):
            sample = next(row for row in report["samples"] if row["workload_id"].endswith("seeded_dense"))
            sample["process_duration_seconds"] = 0.000001
            command = next(row for row in report["commands"] if row["id"] == sample["command_id"])
            command["duration_seconds"] = sample["process_duration_seconds"]
        self.reject(self.changed_report(too_short), "process duration|process interval|host process")

    def test_complete_repeat_inventory_and_both_summary_copies_are_recomputed(self):
        self.reject(self.changed_report(lambda report: report["samples"].pop()), "sample inventory")
        members = self.changed_report(lambda report: report["summary"]["inventory"].update(measured_processes=19))
        edit_snapshot(members, "summary_snapshot", lambda summary: summary["inventory"].update(measured_processes=19))
        self.reject(members, "recomputed measured-only summary")
        self.reject(self.changed_report(lambda report: report["stability_checks"][1].update(source_sha256="0" * 64)),
                    "stability identity")

    def test_hosted_identity_matches_source_workflow_format_and_python(self):
        original = hosted(self.packets["fp16"])
        result = self.check(original)
        self.assertEqual(result["hosted_job_identity"]["GITHUB_RUN_ID"], "123456789")
        self.assertFalse(result["acceptance_claimed"])
        for name, change, pattern in (
            ("job.json", lambda value: value.update(GITHUB_SHA="b" * 40), "GITHUB_SHA"),
            ("job.json", lambda value: value.update(P06_FORMAT="bf16"), "P06_FORMAT"),
            ("python-provision.json", lambda value: value.update(python_version=[3, 12, 13]), "python_version"),
        ):
            members = dict(original)
            value = json.loads(members[name])
            change(value)
            members[name] = encoded(value)
            with self.subTest(check=pattern):
                self.reject(members, pattern)
        members = dict(original)
        members["workflow.yml"] += b"# drift\n"
        self.reject(members, "workflow source")
        members = dict(original)
        del members["python-provision.json"]
        self.reject(members, "hosted identity packet is incomplete")

    def test_trusted_reader_and_imported_validator_drift_fail_before_archive_reads(self):
        with mock.patch.object(replay, "ARCHIVE_READER_SHA256", "0" * 64):
            self.reject(self.packets["fp16"], "reviewed source pin")
        changed = copy.deepcopy(replay.TRUSTED_SOURCES)
        changed[0]["sha256"] = "0" * 64
        with mock.patch.object(replay, "_trusted_sources", return_value=changed):
            self.reject(self.packets["fp16"], "executing replay source stability")

    def test_cli_writes_review_result_exclusively_and_never_claims_execution(self):
        digest = write_archive(self.path, self.packets["fp16"])
        destination = self.root / "review.json"
        args = ["--archive", str(self.path), "--sha256", digest, "--source-revision", REVISION,
                "--format", "fp16", "--output", str(destination)]
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(replay.main(args), 0)
        self.assertEqual(json.loads(output.getvalue())["native_execution"], "not_run")
        body = destination.read_bytes()
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(replay.main(args), 1)
        self.assertEqual(json.loads(output.getvalue())["outcome"], "fail")
        self.assertEqual(destination.read_bytes(), body)


if __name__ == "__main__":
    unittest.main()
