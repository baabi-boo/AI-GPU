# SPDX-License-Identifier: Apache-2.0
"""Independent complete warm archive tests; every producer observation is synthetic."""

from contextlib import ExitStack, redirect_stdout
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import warnings
import zipfile

import p06_warm_replay as replay
from p06_warm_test_fixture import raw_records, render_log
from p06_warm_test_packets import (NATIVE_HELPERS, PREFIX, REPORT, REVISION, ROOT,
                                   descriptor, encoded, hosted, synthetic_packet, write_archive)


FIRST_PROCESS = "warm-simx-fp16-pair0-per_operation"


def edit_report(members, change):
    value = json.loads(members[REPORT])
    change(value)
    members[REPORT] = encoded(value)


def edit_snapshot(members, key, change):
    report = json.loads(members[REPORT])
    row = report[key]
    name = PREFIX + row["path"]
    value = json.loads(members[name])
    change(value)
    members[name] = encoded(value)
    report[key] = descriptor(row["path"], members[name])
    members[REPORT] = encoded(report)


def replace_log(members, command_id, change):
    report = json.loads(members[REPORT])
    command = next(row for row in report["commands"] if row["id"] == command_id)
    name = PREFIX + command["log"]
    members[name] = change(members[name])
    row = descriptor(command["log"], members[name])
    command.update(log_sha256=row["sha256"], log_size_bytes=row["size_bytes"])
    for original in report["raw_logs"]:
        if original["path"] == row["path"]:
            original.update(row)
    members[REPORT] = encoded(report)


def edit_record(body, marker, change):
    lines = body.decode("utf-8").splitlines()
    index = next(i for i, line in enumerate(lines) if line.startswith(marker + " "))
    value = json.loads(lines[index][len(marker) + 1:])
    change(value)
    lines[index] = marker + " " + json.dumps(value, separators=(",", ":"))
    return ("\n".join(lines) + "\n").encode("utf-8")


def replace_source_body(members, relative, body):
    name = "artifacts/source/" + relative
    members[PREFIX + name] = body

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
    report = json.loads(members[REPORT])
    variant = report["variants"][0]
    names = {relative}
    for stage in variant["retained_builds"]:
        name = "artifacts/" + variant["id"] + "/" + stage["stage"] + "/" + relative
        if PREFIX + name in members:
            members[PREFIX + name] = body
            names.add(name)

    def update(value):
        if type(value) is dict:
            if set(value) == {"path", "sha256", "size_bytes"} and value["path"] in names:
                value.update(descriptor(value["path"], body))
            for child in value.values():
                update(child)
        elif type(value) is list:
            for child in value:
                update(child)
    update(report)
    members[REPORT] = encoded(report)


def edit_binding(members, *, process, change):
    report = json.loads(members[REPORT])
    row = report["processes" if process else "variants"][0]
    name = PREFIX + row["binding"]["path"]
    value = json.loads(members[name])
    change(value)
    members[name] = encoded(value)
    row["binding"] = descriptor(row["binding"]["path"], members[name])
    members[REPORT] = encoded(report)


def favorable_reported_packet(original):
    """Invent a faster candidate while retaining full raw-record reconciliation."""
    members = dict(original)
    report = json.loads(members[REPORT])
    contract = replay.load_contract()
    for process in report["processes"]:
        if process["policy"] != "reusable_single_tile":
            continue
        case, operations, summary = raw_records(process["format"], process["policy"],
            pair_index=process["pair_index"], binding_id=process["qualification_id"],
            durations_ns=95, contract=contract)
        raw = render_log(operations, summary)
        body = raw.encode("utf-8")
        members[PREFIX + process["log"]] = body
        process["observation"] = replay.verify_output(raw, case=case, fmt=process["format"],
            policy=process["policy"], binding_id=process["qualification_id"],
            sample_id=process["id"], pair_index=process["pair_index"], phase=process["phase"],
            contract=contract)
        identity = descriptor(process["log"], body)
        command = next(row for row in report["commands"] if row["id"] == process["id"])
        command.update(log_sha256=identity["sha256"], log_size_bytes=identity["size_bytes"])
        retained = next(row for row in report["raw_logs"] if row["path"] == process["log"])
        retained.update(identity)
    members[REPORT] = encoded(report)
    return members


class WarmReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.members = synthetic_packet()
        cls.hosted_members = hosted(cls.members)
        cls.hosted_relocated = hosted(cls.members, relocated=True)
        cls.favorable_members = favorable_reported_packet(cls.members)
        cls.original_hashes = {name: hashlib.sha256(body).hexdigest() for name, body in cls.members.items()}

    @classmethod
    def tearDownClass(cls):
        observed = {name: hashlib.sha256(body).hexdigest() for name, body in cls.members.items()}
        if observed != cls.original_hashes:
            raise AssertionError("shared synthetic archive was mutated")

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="warm-replay-test-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.path = self.directory / "packet.zip"

    def assert_blocked(self, result, conditional):
        self.assertEqual(result["schema_version"], 2)
        self.assertEqual(result["hypothesis_evaluation"], "blocked")
        self.assertEqual(result["conditional_evaluation"], conditional)
        qualification = result["full_hypothesis_qualification"]
        self.assertEqual(qualification["status"], "blocked")
        self.assertIs(qualification["qualified"], False)
        self.assertEqual(qualification["finding_id"], "P06-WARM-RV64-MPM-HIGH-HALF")
        self.assertEqual(qualification["counter_transport"], "unqualified_low_32_bits")
        self.assertEqual(qualification["absolute_no_wrap_bound"], "not_established")
        self.assertEqual(result["analysis"]["schema_version"], 2)
        self.assertEqual(result["analysis"]["hypothesis_evaluation"], "blocked")
        self.assertEqual(result["analysis"]["conditional_evaluation"], conditional)
        self.assertEqual(result["analysis"]["full_hypothesis_qualification"], qualification)
        for row in result["analysis"]["formats"]:
            self.assertNotIn("hypothesis_supported", row)

    def check(self, members=None, *, revision=REVISION, sha256=None, prefix="warm-workspace"):
        digest = write_archive(self.path, self.members if members is None else members)
        return replay.replay_archive(self.path, digest if sha256 is None else sha256,
                                     expected_revision=revision, prefix=prefix)

    def reject(self, members, pattern=".", **kwargs):
        with self.assertRaisesRegex(ValueError, pattern):
            self.check(members, **kwargs)

    def changed_report(self, change):
        members = dict(self.members)
        edit_report(members, change)
        return members

    def check_hosted_component(self, members):
        """Exercise hosted mutations after the complete packet's positive replay."""
        digest = write_archive(self.path, members)
        api = replay.archive_helpers._archive_api()
        with api.ArchiveReader(self.path, digest) as archive:
            reader = replay._Replay(archive.view("warm-workspace"), api, REVISION)
            reader.budget()
            reader.provenance()
            reader.paths_and_tools()
            return reader.hosted_identity()

    def check_provenance_component(self, members):
        digest = write_archive(self.path, members)
        api = replay.archive_helpers._archive_api()
        with api.ArchiveReader(self.path, digest) as archive:
            reader = replay._Replay(archive.view("warm-workspace"), api, REVISION)
            reader.provenance()
            return reader.source

    def test_complete_packet_replays_after_all_recorded_roots_are_deleted(self):
        report = json.loads(self.members[REPORT])
        for path in report["paths"].values():
            if path is not None:
                self.assertFalse(Path(path).exists(), path)
        result = self.check()
        self.assertEqual((result["outcome"], result["native_execution"]), ("pass", "not_run"))
        self.assertEqual(result["counts"], {"processes": 24, "launches": 792, "checked_words": 25344})
        self.assertEqual(result["commands_checked"], 53)
        self.assertEqual(len(result["processes"]), 24)
        self.assertEqual(len(result["build_qualification_ids"]), 2)
        self.assertEqual(len(report["stability_checks"]), 52)
        for key in ("acceptance_claimed", "performance_acceptance", "phase_acceptance", "phase_complete"):
            self.assertIs(result[key], False)
        self.assertFalse(result["archive_read"]["retained_code_executed"])
        self.assertIsNone(result["hosted_job_identity"])
        self.assertIsNone(result["preparation"])
        self.assert_blocked(result, "not_satisfied")
        self.assertEqual(result["analysis"]["raw_record_validation"], "pass")
        for row in result["analysis"]["formats"]:
            self.assertEqual(row["failed_conditional_criteria"], ["host_median_at_most_95_percent_of_reference"])

    def test_fresh_entry_point_helper_inventory_is_independent_of_test_imports(self):
        code = ("import json,sys;assert sys.flags.isolated and sys.dont_write_bytecode;"
                "sys.path.insert(0,sys.argv[1]);import p06_warm_execute as r;"
                "print(json.dumps([v['path'] for v in r.LOADED_HELPERS]))")
        run = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(ROOT / "ci/project")],
                             check=True, text=True, capture_output=True, timeout=20)
        self.assertEqual(json.loads(run.stdout), list(NATIVE_HELPERS))
        self.assertEqual(len(NATIVE_HELPERS), 28)

    def test_favorable_host_and_reported_cycles_never_qualify_complete_replay(self):
        result = self.check(self.favorable_members)
        self.assertEqual(result["outcome"], "pass")
        self.assertEqual(result["archive_provenance_validation"], "pass")
        self.assertEqual(result["analysis"]["raw_record_validation"], "pass")
        self.assert_blocked(result, "satisfied")
        for row in result["analysis"]["formats"]:
            self.assertTrue(row["conditional_criteria_satisfied"])
            self.assertEqual(row["failed_conditional_criteria"], [])
            self.assertEqual(row["candidate_reference_median_ratio"]["numerator"], 19)
            self.assertEqual(row["candidate_reference_median_ratio"]["denominator"], 20)

    def test_fresh_cli_exposes_block_for_both_conditional_outcomes(self):
        for members, conditional in ((self.members, "not_satisfied"), (self.favorable_members, "satisfied")):
            digest = write_archive(self.path, members)
            for write_output in (False, True):
                output = self.directory / (conditional + "-fresh-result.json")
                command = [sys.executable, "-B", str(ROOT / "ci/project/p06_warm_replay.py"),
                           "--archive", str(self.path), "--sha256", digest, "--source-revision", REVISION]
                if write_output:
                    command.extend(("--output", str(output)))
                with self.subTest(conditional=conditional, write_output=write_output):
                    run = subprocess.run(command, cwd=ROOT, text=True, capture_output=True,
                                         check=False, timeout=60)
                    self.assertEqual((run.returncode, run.stderr), (0, ""))
                    emitted = json.loads(run.stdout)
                    self.assertEqual(emitted["hypothesis_evaluation"], "blocked")
                    self.assertEqual(emitted["conditional_evaluation"], conditional)
                    result = json.loads(output.read_bytes()) if write_output else emitted
                    self.assertEqual(emitted["full_hypothesis_qualification"],
                                     result["full_hypothesis_qualification"])
                    self.assertEqual(result["outcome"], "pass")
                    self.assert_blocked(result, conditional)

    def test_packet_cannot_assert_transport_qualification(self):
        for key, value in (("full_hypothesis_qualification", {"status": "pass", "qualified": True}),
                           ("counter_transport_qualified", True), ("conditional_evaluation", "satisfied")):
            with self.subTest(field=key):
                self.reject(self.changed_report(lambda row, k=key, v=value: row.update({k: v})), "fields")
        with self.assertRaises(TypeError):
            replay.replay_archive(self.path, "0" * 64, expected_revision=REVISION,
                                  counter_transport_qualified=True)

    def test_hosted_clean_and_relocated_preparation_replay_end_to_end(self):
        for members, expected in ((self.hosted_members, "not_needed"), (self.hosted_relocated, "relocated")):
            with self.subTest(quarantine=expected):
                result = self.check(members)
                self.assertEqual(result["preparation"]["cache_quarantine_state"], expected)
                self.assertEqual(result["hosted_job_identity"]["GITHUB_SHA"], REVISION)
                self.assertEqual(result["hosted_job_identity"]["record_stage"], "job-initialization")
                self.assert_blocked(result, "not_satisfied")

    def test_replay_executes_no_archive_content_and_opens_no_recorded_root(self):
        roots = tuple(Path(value) for value in json.loads(self.members[REPORT])["paths"].values()
                      if value is not None)
        original_open, original_os_open = Path.open, os.open

        def guard(path):
            if isinstance(path, (str, bytes, os.PathLike)):
                candidate = Path(os.fsdecode(path))
                self.assertFalse(any(candidate == root or root in candidate.parents for root in roots),
                                 "replay accessed a recorded execution root")

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
            self.assertEqual(self.check()["outcome"], "pass")

    def test_digest_revision_prefix_and_file_type_are_external_requirements(self):
        self.reject(self.members, "SHA-256|identity", sha256="0" * 64)
        self.reject(self.members, "revision", revision="2" * 40)
        self.reject(self.members, "member name", prefix="../warm-workspace")
        self.reject(self.members, "no retained files", prefix="absent")
        for revision in (True, "A" * 40, "1" * 39):
            with self.subTest(revision=revision), self.assertRaises(ValueError):
                replay.replay_archive(self.path, "0" * 64, expected_revision=revision)
        digest = write_archive(self.path, self.members)
        alias = self.directory / "alias.zip"
        alias.symlink_to(self.path)
        with self.assertRaisesRegex(ValueError, "canonical|symlink"):
            replay.replay_archive(alias, digest, expected_revision=REVISION)
        self.path.write_bytes(self.path.read_bytes() + b"changed")
        with self.assertRaisesRegex(ValueError, "identity|SHA-256"):
            replay.replay_archive(self.path, digest, expected_revision=REVISION)

    def test_archive_name_duplicate_special_and_trailing_data_are_rejected(self):
        for name in ("../escape", "/absolute", "a/../b", "a\\b", "C:drive"):
            with self.subTest(name=name):
                self.reject({name: b"not a packet"}, "member name")
        for kind in ("duplicate", "symlink", "trailing"):
            with self.subTest(kind=kind):
                with zipfile.ZipFile(self.path, "w") as archive, warnings.catch_warnings():
                    warnings.simplefilter("ignore", UserWarning)
                    archive.writestr(REPORT, b"{}")
                    if kind == "duplicate":
                        archive.writestr(REPORT, b"{}")
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
                    replay.replay_archive(self.path, digest, expected_revision=REVISION)

    def test_report_json_duplicate_nonfinite_boolean_and_unknown_fields_fail(self):
        for body in (b'{"schema_version":1,"schema_version":1}', b'{"schema_version":NaN}',
                     b'{"schema_version":1e400}', b'\xff'):
            with self.subTest(body=body):
                changed = dict(self.members, **{REPORT: body})
                self.reject(changed)
        for key, value in (("schema_version", True), ("checked_words", True), ("unexpected", 1)):
            with self.subTest(key=key):
                self.reject(self.changed_report(lambda row, k=key, v=value: row.update({k: v})))

    def test_completeness_claims_cannot_replace_required_processes(self):
        for key, value in (("completed_launches", 791), ("completed_processes", 23),
                           ("measured_operations", 639), ("measured_processes", 19),
                           ("full_matrix_completed", False), ("phase_complete", True),
                           ("acceptance_claimed", True), ("performance_acceptance", True),
                           ("phase_acceptance", True), ("hypothesis_evaluation", "supported"),
                           ("state", "running"), ("outcome", "fail")):
            with self.subTest(key=key):
                self.reject(self.changed_report(lambda row, k=key, v=value: row.update({k: v})), "report")
        self.reject(self.changed_report(lambda row: row["processes"].pop()), "missing|duplicate")
        self.reject(self.changed_report(lambda row: row["variants"].pop()), "two format")

    def test_budgets_cannot_be_weakened_or_satisfied_with_wrong_types(self):
        for key, value in (("jobs", 3), ("jobs", True), ("min_free_bytes", 0),
                           ("max_rss_bytes", 8 * 1024**3), ("max_log_bytes", 32 * 1024**2),
                           ("build_timeout_seconds", 1801), ("run_timeout_seconds", 181),
                           ("configure_timeout_seconds", 121)):
            with self.subTest(key=key, value=value):
                self.reject(self.changed_report(lambda row, k=key, v=value: row["budget"].update({k: v})))
        self.reject(self.changed_report(lambda row: row["resources_before"].update(available_memory_bytes=None)))
        self.reject(self.changed_report(lambda row: row["resources_after"]["free_disk_bytes"].update(output=0)))

    def test_command_status_cleanup_rss_timeout_and_log_limits_are_checked(self):
        for key, value in (("outcome", "fail"), ("exit_code", 1), ("process_started", False),
                           ("cleanup_complete", False), ("duration_seconds", float("inf")),
                           ("duration_seconds", 41), ("peak_rss_bytes", 4 * 1024**3 + 1),
                           ("log_size_bytes", 16 * 1024**2 + 1), ("timeout_seconds", 31),
                           ("limitations", [])):
            with self.subTest(key=key):
                if key == "duration_seconds" and value == float("inf"):
                    changed = dict(self.members)
                    report = json.loads(changed[REPORT])
                    report["commands"][0][key] = value
                    changed[REPORT] = json.dumps(report).encode()
                else:
                    changed = self.changed_report(lambda row, k=key, v=value: row["commands"][0].update({k: v}))
                self.reject(changed)

    def test_command_order_arguments_environment_and_paths_are_bound(self):
        changes = (
            lambda row: row["commands"].reverse(),
            lambda row: row["commands"][0]["argv"].append("--injected"),
            lambda row: row["commands"][0]["environment"].update(HOME="/untrusted"),
            lambda row: row["commands"][0]["environment"].update(PATH="/untrusted:/usr/bin:/bin"),
            lambda row: row["commands"][0].update(cwd="/untrusted"),
            lambda row: row["paths"].update(work=row["paths"]["source"]),
            lambda row: row["paths"].update(tools="relative"),
        )
        for change in changes:
            with self.subTest(change=change):
                self.reject(self.changed_report(change))

    def test_perf_environment_is_required_only_for_build_commands(self):
        for name in ("simx-fp16-runtime", "simx-fp16-application"):
            changed = self.changed_report(lambda report, n=name: next(
                row for row in report["commands"] if row["id"] == n)["environment"].pop("PERF"))
            with self.subTest(name=name):
                self.reject(changed, "environment")
        changed = self.changed_report(lambda report: next(row for row in report["commands"]
            if row["id"] == FIRST_PROCESS)["environment"].update(PERF="1"))
        self.reject(changed, "environment")

    def test_source_rehash_does_not_override_frozen_kernel_or_fixture(self):
        for name in ("sw/kernel/ai/matmul.cpp", "ci/project/fixtures/p02_layout_v1.json"):
            changed = dict(self.members)
            replace_source_body(changed, name, changed[PREFIX + "artifacts/source/" + name] + b"\n")
            with self.subTest(name=name):
                self.reject(changed, "frozen|fixture")

    def test_dirty_source_tree_inputs_and_loaded_helpers_are_rejected(self):
        for key, value in (("dirty", True), ("revision", "2" * 40), ("tree", "invalid"),
                           ("changed_paths", ["file"]), ("untracked_paths", ["file"]),
                           ("outcome", "blocked")):
            changed = dict(self.members)
            for snapshot in ("source_before", "source_after"):
                edit_snapshot(changed, snapshot, lambda row, k=key, v=value: row["checkout"].update({k: v}))
            with self.subTest(key=key):
                self.reject(changed)
        self.reject(self.changed_report(lambda row: row["loaded_helpers"].pop()), "helper")
        self.reject(self.changed_report(lambda row: row["retained_sources"].pop()), "retained source")

    def test_declared_submodule_roots_and_nested_entries_are_checked_from_retained_body(self):
        body = self.members[PREFIX + "artifacts/source/.gitmodules"]
        report = json.loads(self.members[REPORT])
        source = json.loads(self.members[PREFIX + report["source_before"]["path"]])
        inventory = source["checkout"]["submodules"]
        api = replay.archive_helpers._archive_api()
        replay.common._check_declared_submodules(body, inventory, api)
        nested = copy.deepcopy(inventory)
        nested["entries"].append(dict(nested["entries"][0], path=nested["entries"][0]["path"] + "/nested"))
        replay.common._check_declared_submodules(body, nested, api)
        bad_bodies = (
            body + body,
            body + b'\n[submodule "second-name"]\npath = third_party/softfloat\n',
            body + b'\n[DEFAULT]\npath = inherited\n',
            b'[unknown "section"]\npath = third_party/softfloat\n',
            b'[submodule "unsafe"]\npath = ../escape\n',
            b'[submodule "missing-path"]\nurl = https://example.invalid/repo\n',
            b'\xff', b'x' * (256 * 1024 + 1),
        )
        for changed in bad_bodies:
            with self.subTest(body=changed[:60]), self.assertRaises(ValueError):
                replay.common._check_declared_submodules(changed, inventory, api)

    def test_inconsistent_submodule_claims_fail_before_build_binding_checks(self):
        def missing_root(inventory):
            inventory["entries"][0]["path"] = inventory["entries"][1]["path"] + "/nested"

        def unrelated_entry(inventory):
            inventory["entries"].append(dict(inventory["entries"][0], path="unrelated/module"))

        def excessive(inventory):
            first = inventory["entries"][0]
            inventory["entries"].extend(dict(first, path=first["path"] + "/nested" + str(index))
                                        for index in range(1001 - len(inventory["entries"])))

        for change, pattern in (
            (lambda row: row.update(declared_count=1), "declared root submodule count"),
            (missing_root, "declared root submodule is missing"),
            (unrelated_entry, "outside the declared roots"),
            (excessive, "incomplete or excessive"),
        ):
            changed = dict(self.members)
            for key in ("source_before", "source_after"):
                edit_snapshot(changed, key, lambda row, modify=change: modify(row["checkout"]["submodules"]))
            with self.subTest(pattern=pattern), self.assertRaisesRegex(ValueError, pattern):
                self.check_provenance_component(changed)

    def test_selected_fixture_and_manifest_snapshots_are_recomputed(self):
        changed = dict(self.members)
        edit_snapshot(changed, "fixture_snapshot", lambda row: row[0]["expected"].__setitem__(
            0, f"{int(row[0]['expected'][0], 16) ^ 1:08x}"))
        self.reject(changed, "fixture")
        changed = dict(self.members)
        edit_snapshot(changed, "contract_snapshot", lambda row: row["sampling"].update(measured_pairs=4))
        self.reject(changed, "contract")

    def test_original_compiler_and_linker_stamps_are_semantically_checked_after_rehash(self):
        for relative, before, after in (
            ("sw/runtime/simx_config.stamp", b" -DPERF_ENABLE", b""),
            ("sw/runtime/simx_rt_config.stamp", b"-DOTYPE=fp32", b"-DOTYPE=bf16"),
            ("tests/regression/ai_warm_workspace/config.stamp", b"-Wl,--wrap=vx_buffer_create ", b""),
        ):
            name = PREFIX + "artifacts/simx-fp16/frozen/" + relative
            self.assertIn(before, self.members[name])
            changed = dict(self.members)
            replace_build_body(changed, relative, self.members[name].replace(before, after))
            with self.subTest(relative=relative):
                self.reject(changed, "performance|selectors|linker")

    def test_header_log_is_reparsed_after_all_log_hashes_are_repaired(self):
        changed = dict(self.members)
        replace_log(changed, "simx-fp16-backend_cpp-header", lambda body: body.replace(
            b"#define PERF_ENABLE 1", b"#define PERF_ENABLE 0"))
        self.reject(changed, "PERF|configuration|performance")

    def test_common_build_binding_and_per_process_binding_are_reconstructed(self):
        changed = dict(self.members)
        edit_binding(changed, process=False, change=lambda row: row.update(performance_environment={}))
        self.reject(changed, "common build binding")
        changed = dict(self.members)
        edit_binding(changed, process=True, change=lambda row: row["process"].update(policy="reusable_single_tile"))
        self.reject(changed, "process binding")
        self.reject(self.changed_report(lambda row: row["processes"][0].update(build_qualification_id="0" * 64)),
                    "build_qualification_id")

    def test_replaced_reordered_and_cross_format_processes_are_rejected(self):
        for field, value in (("id", "replacement"), ("pair_index", 1), ("format", "bf16"),
                             ("sample_id", "replacement"), ("policy", "reusable_single_tile")):
            with self.subTest(field=field):
                self.reject(self.changed_report(lambda row, k=field, v=value: row["processes"][0].update({k: v})))
        self.reject(self.changed_report(lambda row: row["processes"].reverse()), "process")

    def test_raw_output_words_arguments_cleanup_and_counter_values_are_reparsed(self):
        changes = (
            ("P06_WARM_OPERATION", lambda row: row["actual_bits"].__setitem__(
                0, f"{int(row['actual_bits'][0], 16) ^ 1:08x}")),
            ("P06_WARM_OPERATION", lambda row: row["dispatch"].update(argument_bytes="00" * 56)),
            ("P06_WARM_OPERATION", lambda row: row["results"]["close"].update(cleanup=1)),
            ("P06_WARM_SUMMARY", lambda row: row["snapshots"]["after_batch"]["counters"][0].update(value=0)),
        )
        for marker, change in changes:
            with self.subTest(marker=marker):
                changed = dict(self.members)
                replace_log(changed, FIRST_PROCESS, lambda body, m=marker, c=change: edit_record(body, m, c))
                self.reject(changed)

    def test_raw_process_log_cannot_be_missing_or_claim_success_without_sequence(self):
        for body in (b"PASSED!\n", b"P06_WARM_FAILURE {}\nPASSED!\n", b"P06_WARM_SUMMARY {}\nPASSED!\n"):
            with self.subTest(body=body):
                changed = dict(self.members)
                replace_log(changed, FIRST_PROCESS, lambda _, b=body: b)
                self.reject(changed)
        changed = dict(self.members)
        del changed[PREFIX + "logs/" + FIRST_PROCESS + ".log"]
        self.reject(changed, "missing|does not exist")

    def test_retained_observation_and_supervisor_duration_cannot_be_invented(self):
        self.reject(self.changed_report(lambda row: row["processes"][0]["observation"]["timed_operation_durations_ns"].__setitem__(0, 1)),
                    "recomputed original output")
        self.reject(self.changed_report(lambda row: row["processes"][0].update(process_duration_seconds=0)),
                    "supervisor duration")
        changed = self.changed_report(lambda row: (
            row["processes"][0].update(process_duration_seconds=0),
            next(command for command in row["commands"] if command["id"] == FIRST_PROCESS).update(duration_seconds=0)))
        self.reject(changed, "owner lifetime")

    def test_final_source_tool_dependency_and_build_identities_are_required(self):
        for snapshot, change in (
            ("source_after", lambda row: row["checkout"].update(tree="a" * 40)),
            ("tools_after", lambda row: row["g++"].update(sha256="b" * 64)),
            ("dependencies_after", lambda row: row[0].update(sha256="b" * 64)),
        ):
            with self.subTest(snapshot=snapshot):
                changed = dict(self.members)
                edit_snapshot(changed, snapshot, change)
                self.reject(changed, "original/final")
        self.reject(self.changed_report(lambda row: row["variants"][0]["artifacts_after"][0].update(sha256="b" * 64)),
                    "artifact stability")

    def test_stability_and_raw_log_inventory_are_complete_and_ordered(self):
        for change in (lambda row: row["stability_checks"].pop(),
                       lambda row: row["stability_checks"].reverse(),
                       lambda row: row["stability_checks"][0].update(source_sha256="0" * 64),
                       lambda row: row["stability_checks"][0].update(at="2000-01-01T00:00:00+00:00"),
                       lambda row: row["raw_logs"].pop()):
            with self.subTest(change=change):
                self.reject(self.changed_report(change), "stability|chronology|raw-log")

    def test_unexpected_retained_member_and_missing_compiler_body_are_rejected(self):
        changed = dict(self.members)
        changed[PREFIX + "untrusted.py"] = b"raise AssertionError('must never execute')\n"
        self.reject(changed, "member inventory")
        changed = dict(self.members)
        del changed[PREFIX + "artifacts/simx-fp16/frozen/sw/runtime/simx_config.stamp"]
        self.reject(changed, "missing|does not exist")

    def test_hosted_identity_and_initialization_fields_are_not_execution_proof(self):
        for key, value in (("GITHUB_SHA", "2" * 40), ("GITHUB_JOB", "baseline"),
                           ("GITHUB_REF", "refs/heads/other"), ("GITHUB_RUN_ID", "0"),
                           ("record_stage", "finished"), ("native_execution", "pass"),
                           ("acceptance_claimed", True), ("workflow_sha256", "0" * 64)):
            changed = dict(self.hosted_members)
            job = json.loads(changed["job.json"])
            job[key] = value
            changed["job.json"] = encoded(job)
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.check_hosted_component(changed)

    def test_hosted_preparation_cache_provenance_and_quarantine_are_checked(self):
        for change in (lambda row: row.update(formats=["fp16"]),
                       lambda row: row.update(third_party_cache_key="Linux-thirdparty-" + "0" * 64),
                       lambda row: row.update(toolchain_cache_key="Linux-toolchain-unpinned-lite"),
                       lambda row: row["cache_quarantine"].update(revision_after="a" * 40),
                       lambda row: row["cache_quarantine"]["files"][0].update(after_sha256="0" * 64),
                       lambda row: row["cache_quarantine"]["files"][0].update(moved=False),
                       lambda row: row["preparation_sources"].pop(),
                       lambda row: row["resources"]["free_disk_bytes"].update(workspace=0)):
            changed = dict(self.hosted_relocated)
            preparation = json.loads(changed["preparation.json"])
            change(preparation)
            changed["preparation.json"] = encoded(preparation)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.check_hosted_component(changed)

    def test_hosted_packet_requires_complete_provision_workflow_and_final_output(self):
        for name in ("job.json", "workflow.yml", "python-provision.json", "preparation.json", "execution.log"):
            changed = dict(self.hosted_members)
            del changed[name]
            with self.subTest(missing=name), self.assertRaises(ValueError):
                self.check_hosted_component(changed)
        for name, change in (("python-provision.json", lambda row: row.update(python_version=[3, 11, 0])),
                             ("execution.log", lambda row: row.update(completed_processes=23)),
                             ("preparation.log", lambda row: row.update(outcome="fail"))):
            changed = dict(self.hosted_members)
            value = json.loads(changed[name])
            change(value)
            changed[name] = encoded(value)
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.check_hosted_component(changed)
        changed = dict(self.hosted_members)
        changed["unexpected.txt"] = b"unaccounted outer evidence"
        with self.assertRaisesRegex(ValueError, "hosted member inventory"):
            self.check_hosted_component(changed)

    def test_cli_writes_new_result_without_overwriting_existing_output(self):
        digest = write_archive(self.path, self.members)
        output = self.directory / "result.json"
        args = ["--archive", str(self.path), "--sha256", digest, "--source-revision", REVISION,
                "--output", str(output)]
        with redirect_stdout(io.StringIO()) as captured:
            status = replay.main(args)
        self.assertEqual(status, 0)
        summary = json.loads(captured.getvalue())
        self.assertEqual(summary["hypothesis_evaluation"], "blocked")
        self.assertEqual(summary["conditional_evaluation"], "not_satisfied")
        self.assertEqual(summary["full_hypothesis_qualification"]["status"], "blocked")
        self.assertIs(summary["full_hypothesis_qualification"]["qualified"], False)
        self.assertEqual(summary["native_execution"], "not_run")
        original = output.read_bytes()
        with mock.patch.object(replay, "replay_archive", return_value=json.loads(original)), redirect_stdout(io.StringIO()):
            self.assertEqual(replay.main(args), 1)
        self.assertEqual(output.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
