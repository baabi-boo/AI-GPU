# SPDX-License-Identifier: Apache-2.0
"""Author-disjoint tests of the inert all-33 diagnostic archive reader.

The positive control is the retained original ZIP. Mutations are synthetic and
rehash the ZIP, command logs and relevant descriptors before semantic checks.
Passing replay establishes internal consistency, never Git origin, a new native
execution, object/binary authentication, warm qualification or acceptance.
"""

import builtins
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

import p06_counter_diagnostics_replay as replay


ROOT = Path(__file__).resolve().parents[2]
ORIGINAL = ROOT / "docs/project/evidence/p06-counter-diagnostics/native/run-45026112992-attempt1.zip"
ORIGINAL_SHA256 = "c4a7ae49259bbb72066d55f7c3e733ce5696f215175ce308f654e1cec9e9c13f"
REVISION = "407ab9fea5e4f793a2a5088f566a87f3e631aa84"
PREFIX = "checked-counters/"
REPORT = PREFIX + "report.json"
BOUNDARY_PREFIX = "CHECKED_COUNTERS_RESULT "
FAILURE_PREFIX = "CHECKED_COUNTERS_FAILURE_RESULT "
STAMP = "sim/simx/simx_config.stamp"
GENERATED_TCU = "sim/simx/obj/tests/checked_counters/access_tcu.generated.cpp"
NONACCEPTANCE = (
    "qualified", "ready_for_warm", "warm_execution", "acceptance", "acceptance_claimed",
    "phase_acceptance", "performance_acceptance", "full_warm_coverage", "retained_code_executed",
)
OLD_SELECTORS = (
    "cycles", "instructions", "core_sched_idle", "core_active_warps", "core_stalled_warps",
    "core_issued_warps", "core_issued_threads", "core_stall_scrb", "core_stall_lsu",
    "core_stall_tcu", "core_instr_tcu", "core_loads", "core_stores", "lmem_reads", "lmem_writes",
    "lmem_bank_st", "coalescer_miss", "tcu_tbuf_stalls", "tcu_tbuf_cache_hits",
)


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def descriptor(path, body):
    return {"path": path, "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)}


def edit_report(members, change):
    report = json.loads(members[REPORT])
    change(report)
    members[REPORT] = encoded(report)


def replace_log(members, command_id, change):
    report = json.loads(members[REPORT])
    command = next(row for row in report["commands"] if row["id"] == command_id)
    name = PREFIX + command["log"]
    members[name] = change(members[name])
    command.update(log_sha256=hashlib.sha256(members[name]).hexdigest(), log_size_bytes=len(members[name]))
    members[REPORT] = encoded(report)


def replace_result(members, command_id, change, *, mirror=False):
    """Mutate raw result JSON, optionally updating the reported observation too."""
    prefix = BOUNDARY_PREFIX if command_id.endswith("-boundaries") else FAILURE_PREFIX
    result = None

    def update(body):
        nonlocal result
        lines = body.decode("utf-8").splitlines()
        index = next(i for i, line in enumerate(lines) if line.startswith(prefix))
        result = json.loads(lines[index][len(prefix):])
        change(result)
        lines[index] = prefix + json.dumps(result, separators=(",", ":"), allow_nan=False)
        return ("\n".join(lines) + "\n").encode("utf-8")

    replace_log(members, command_id, update)
    if mirror:
        def update_report(report):
            next(row for row in report["cells"] if row["id"] == command_id)["observations"] = result
        edit_report(members, update_report)


def replace_source(members, name, body):
    """Rehash both source snapshots and their retained body, without Git claims."""
    retained = "artifacts/source/" + name
    members[PREFIX + retained] = body

    def change(report):
        for key in ("source_before", "source_after"):
            for row in report[key]["files"] + report[key]["checkout"]["inputs"]:
                if row["path"] == name:
                    row.update(descriptor(name, body))
        for row in report["retained_sources"]:
            if row["path"] == retained:
                row.update(descriptor(retained, body))
    edit_report(members, change)


def replace_build(members, variant_id, name, body):
    """Rehash only this variant's original and retained build descriptors."""
    retained = "artifacts/" + variant_id + "/" + name
    members[PREFIX + retained] = body

    def change(report):
        variant = next(row for row in report["variants"] if row["id"] == variant_id)

        def update(value):
            if type(value) is dict:
                if set(value) == {"path", "sha256", "size_bytes"} and value["path"] in (name, retained):
                    value.update(descriptor(value["path"], body))
                for child in value.values():
                    update(child)
            elif type(value) is list:
                for child in value:
                    update(child)
        update(variant)
    edit_report(members, change)


def write_archive(path, members):
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, body in sorted(members.items()):
            archive.writestr(name, body)
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CounterDiagnosticsReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Fail when the required original evidence is absent or substituted.
        if hashlib.sha256(ORIGINAL.read_bytes()).hexdigest() != ORIGINAL_SHA256:
            raise AssertionError("original all-33 diagnostic ZIP identity differs")
        with zipfile.ZipFile(ORIGINAL) as archive:
            cls.original = {name: archive.read(name) for name in archive.namelist()}
        cls.original_report = json.loads(cls.original[REPORT])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="p06-counter-replay-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "mutation.zip"

    def changed_report(self, change):
        members = dict(self.original)
        edit_report(members, change)
        return members

    def check(self, members, *, digest=None, revision=REVISION, prefix="checked-counters", **kwargs):
        actual = write_archive(self.path, members)
        return replay.replay_archive(self.path, actual if digest is None else digest,
                                     expected_revision=revision, prefix=prefix, **kwargs)

    def reject(self, members, pattern, **kwargs):
        with self.assertRaisesRegex(ValueError, pattern):
            self.check(members, **kwargs)

    def assert_nonacceptance(self, result):
        self.assertEqual(result["native_execution"], "not_run")
        for name in NONACCEPTANCE:
            self.assertIs(result[name], False, name)

    def test_original_all33_zip_replays_without_execution_or_qualification(self):
        result = replay.replay_archive(ORIGINAL, ORIGINAL_SHA256, expected_revision=REVISION)
        self.assertEqual(result["outcome"], "pass")
        self.assertEqual(result["scope"], "retained-data-consistency-only")
        self.assertIs(result["retained_data_consistent"], True)
        self.assert_nonacceptance(result)
        self.assertEqual(result["source_revision"], REVISION)
        self.assertEqual((result["cells_checked"], result["commands_checked"], result["retained_source_files"]),
                         (7, 17, 270))
        self.assertEqual(result["archive_read"]["data_files"], 327)
        self.assertEqual(result["archive_read"]["archive"]["sha256"], ORIGINAL_SHA256)
        self.assertIs(result["archive_read"]["retained_code_executed"], False)
        self.assertIs(result["archive_read"]["acceptance_claimed"], False)
        self.assertEqual(result["transport_selectors_per_variant"], 33)
        self.assertEqual(result["source_components_per_variant"], 40)
        self.assertEqual(result["checks_per_variant"], 6389)
        self.assertEqual(result["half_reads_per_variant"], 1788)
        self.assertEqual([row["translation_units"] for row in result["variants"]], [45, 45])
        self.assertEqual([row["link_count"] for row in result["variants"]], [1, 1])

    def test_semantic_mutation_helpers_rehash_all_modified_descriptors(self):
        members = dict(self.original)
        source = "sim/simx/core.cpp"
        body = members[PREFIX + "artifacts/source/" + source] + b"\n// inert retained-data mutation\n"
        replace_source(members, source, body)
        config = "config.mk"
        config_body = members[PREFIX + "artifacts/ordinary/" + config] + b"# semantic mutation\n"
        replace_build(members, "ordinary", config, config_body)
        replace_log(members, "version-make", lambda raw: raw + b"synthetic retained text\n")
        digest = write_archive(self.path, members)
        self.assertNotEqual(digest, ORIGINAL_SHA256)
        self.assertEqual(digest, hashlib.sha256(self.path.read_bytes()).hexdigest())
        report = json.loads(members[REPORT])
        for key in ("source_before", "source_after"):
            self.assertEqual(next(row for row in report[key]["files"] if row["path"] == source),
                             descriptor(source, body))
        variant = report["variants"][0]
        for key in ("generated_before", "generated_after"):
            self.assertEqual(next(row for row in variant[key] if row["path"] == config),
                             descriptor(config, config_body))
        self.assertEqual(next(row for row in variant["retained_configuration"]
                              if row["path"] == "artifacts/ordinary/config.mk"),
                         descriptor("artifacts/ordinary/config.mk", config_body))
        log = report["commands"][0]
        self.assertEqual(log["log_sha256"], hashlib.sha256(members[PREFIX + log["log"]]).hexdigest())
        self.assertEqual(log["log_size_bytes"], len(members[PREFIX + log["log"]]))

    def test_replay_never_opens_producer_paths_extracts_or_executes_retained_code(self):
        members = dict(self.original)
        # This retained producer module would fail immediately if imported.
        replace_source(members, "ci/project/p06_checked_execute.py",
                       b"raise AssertionError('retained producer code was executed')\n")
        digest = write_archive(self.path, members)
        report = json.loads(members[REPORT])
        roots = tuple(Path(value) for value in report["paths"].values())
        tool_paths = {Path(row[key]) for row in report["tools_before"]["tools"].values()
                      for key in ("path", "resolved_path")}
        trusted_reader = str(ROOT / replay.trusted.ARCHIVE_READER_PATH)
        executed = []
        original_exec = builtins.exec

        def guard(path):
            if isinstance(path, (str, bytes, os.PathLike)):
                candidate = Path(os.fsdecode(path))
                self.assertNotIn(candidate, tool_paths, "reader opened a recorded tool identity")
                self.assertFalse(any(candidate == root or root in candidate.parents for root in roots),
                                 "reader accessed recorded producer path: " + str(candidate))

        def guarded(method):
            def call(path, *args, **kwargs):
                guard(path)
                return method(path, *args, **kwargs)
            return call

        def trusted_exec(code, globals=None, locals=None, **kwargs):
            # The current, digest-pinned archive-reader module is imported once.
            # Executing that trusted helper is distinct from archive-code replay.
            filename = getattr(code, "co_filename", None)
            self.assertEqual(filename, trusted_reader, "executed code outside the pinned current archive reader")
            executed.append(filename)
            return original_exec(code, globals, locals, **kwargs)

        with ExitStack() as patches:
            for owner, name in ((builtins, "open"), (io, "open"), (os, "open"),
                                (os, "stat"), (os, "lstat"), (os, "readlink"),
                                (os, "listdir"), (os, "scandir"), (os, "access"),
                                (Path, "open"), (Path, "resolve"), (Path, "stat"),
                                (Path, "lstat"), (Path, "exists"), (Path, "is_file"),
                                (Path, "is_dir"), (Path, "glob"), (Path, "rglob")):
                patches.enter_context(mock.patch.object(owner, name, guarded(getattr(owner, name))))
            for owner, name in ((subprocess, "Popen"), (subprocess, "run"), (subprocess, "call"),
                                (subprocess, "check_call"), (subprocess, "check_output"),
                                (os, "system"), (os, "popen"), (os, "fork"),
                                (os, "execv"), (os, "execve"), (os, "execvp"), (os, "execvpe"),
                                (os, "posix_spawn"), (os, "posix_spawnp"),
                                (zipfile.ZipFile, "extract"), (zipfile.ZipFile, "extractall"),
                                (replay.checked, "validate_build"), (replay.checked, "source_snapshot")):
                if hasattr(owner, name):
                    patches.enter_context(mock.patch.object(owner, name, side_effect=AssertionError(name)))
            patches.enter_context(mock.patch.object(builtins, "exec", trusted_exec))
            result = replay.replay_archive(self.path, digest, expected_revision=REVISION)
        self.assertEqual(executed, [trusted_reader])
        self.assertEqual(result["outcome"], "pass")
        self.assert_nonacceptance(result)

    def test_equal_recorded_git_tree_is_consistency_without_origin_authentication(self):
        def change(report):
            for key in ("source_before", "source_after"):
                report[key]["checkout"]["tree"] = "a" * 40
        result = self.check(self.changed_report(change))
        self.assertEqual(result["outcome"], "pass")
        self.assert_nonacceptance(result)
        self.assertTrue(any("not a Git tree proof" in line for line in result["limitations"]))
        self.assertTrue(any("not independently rehashed" in line for line in result["limitations"]))

    def test_external_digest_revision_contract_and_prefix_are_enforced(self):
        for digest in ("0" * 64, True, "A" * 64, "", "0" * 63):
            with self.subTest(digest=digest):
                self.reject(self.original, "SHA-256|identity", digest=digest)
        for revision in ("b" * 40, True, "407ab9f", "A" * 40):
            with self.subTest(revision=revision):
                self.reject(self.original, "revision", revision=revision)
        self.reject(self.original, "external diagnostic contract", expected_contract="simx-checked-counters-native-v1")
        self.reject(self.original, "member name", prefix="../checked-counters")
        self.reject(self.original, "prefix", prefix="missing")

    def test_archive_duplicate_unsafe_symlink_and_trailing_members_are_rejected(self):
        for name in ("../escape", "/absolute", "a/../b", "a\\b", "C:drive", "a//b", "a/./b"):
            with self.subTest(name=name):
                self.reject({name: b"invalid"}, "member name")
        for kind in ("duplicate", "symlink", "trailing"):
            with self.subTest(kind=kind):
                with zipfile.ZipFile(self.path, "w") as archive, warnings.catch_warnings():
                    warnings.simplefilter("ignore", UserWarning)
                    archive.writestr(REPORT, b"{}")
                    if kind == "duplicate":
                        archive.writestr(REPORT, b"{}")
                    elif kind == "symlink":
                        member = zipfile.ZipInfo(PREFIX + "link")
                        member.create_system = 3
                        member.external_attr = (stat.S_IFLNK | 0o777) << 16
                        archive.writestr(member, b"/etc/passwd")
                if kind == "trailing":
                    with self.path.open("ab") as stream:
                        stream.write(b"unconsumed ZIP trailer")
                digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
                with self.assertRaisesRegex(ValueError, "duplicate|symlink|special|ZIP|trailing"):
                    replay.replay_archive(self.path, digest, expected_revision=REVISION)

    def test_original_archive_symlink_and_change_during_read_are_rejected(self):
        digest = write_archive(self.path, self.original)
        link = self.root / "alias.zip"
        link.symlink_to(self.path)
        with self.assertRaisesRegex(ValueError, "canonical|symlink"):
            replay.replay_archive(link, digest, expected_revision=REVISION)
        with self.assertRaisesRegex(ValueError, "changed during its audit"):
            with replay.open_archive(self.path, digest, prefix="checked-counters"):
                with self.path.open("ab") as stream:
                    stream.write(b"changed during review")

    def test_duplicate_json_keys_nonfinite_values_and_depth_are_rejected(self):
        for body in (b'{"schema_version":2,"schema_version":2}', b'{"nested":{"x":1,"x":1}}',
                     b'{"duration":NaN}', b'{"duration":Infinity}', b"[" * 66 + b"0" + b"]" * 66):
            with self.subTest(body=body[:60]):
                self.reject({REPORT: body}, "JSON")

    def test_report_claims_require_exact_types_and_known_fields(self):
        for field, value in (("schema_version", True), ("schema_version", 2.0), ("qualified", 0),
                             ("native_prerequisites_passed", 1), ("qualified", True),
                             ("ready_for_warm", True), ("acceptance_claimed", True),
                             ("full_warm_coverage", True), ("warm_execution", True),
                             ("all_available_selector_transport", False), ("unknown", False)):
            with self.subTest(field=field, value=value):
                self.reject(self.changed_report(lambda row: row.update({field: value})), "report|producer")

    def test_nested_extra_fields_are_rejected(self):
        selectors = (
            (lambda report: report["commands"][0], "command"),
            (lambda report: report["cells"][0], "cell"),
            (lambda report: report["variants"][0], "variant"),
            (lambda report: report["source_before"], "source before/after"),
            (lambda report: report["retained_sources"][0], "retained source inventory"),
            (lambda report: report["variants"][0]["compiler_records"], "compiler/link/source/object"),
        )
        for select, pattern in selectors:
            with self.subTest(pattern=pattern):
                self.reject(self.changed_report(lambda report: select(report).update(unexpected="field")), pattern)

    def test_missing_required_source_body_is_rejected_even_with_rewritten_inventories(self):
        for name in ("sim/simx/core.cpp", "sim/simx/tcu/tcu_tbuf.cpp", "sim/common/perf_counter.h"):
            with self.subTest(name=name):
                members = dict(self.original)
                del members[PREFIX + "artifacts/source/" + name]

                def change(report):
                    for key in ("source_before", "source_after"):
                        report[key]["files"] = [row for row in report[key]["files"] if row["path"] != name]
                    report["retained_sources"] = [row for row in report["retained_sources"]
                                                  if row["path"] != "artifacts/source/" + name]
                edit_report(members, change)
                self.reject(members, "source inventory omits a required body")

    def test_missing_noncritical_source_is_rejected_by_versioned_inventory(self):
        name = next(row["path"] for row in self.original_report["source_before"]["files"]
                    if row["path"] not in replay.SOURCE_REQUIRED)
        members = dict(self.original)
        del members[PREFIX + "artifacts/source/" + name]

        def change(report):
            for key in ("source_before", "source_after"):
                report[key]["files"] = [row for row in report[key]["files"] if row["path"] != name]
            report["retained_sources"] = [row for row in report["retained_sources"]
                                          if row["path"] != "artifacts/source/" + name]
        edit_report(members, change)
        self.reject(members, "versioned source inventory")

    def test_absent_retained_source_and_generated_payloads_are_rejected(self):
        for name in ("artifacts/source/sim/simx/core.cpp", "artifacts/ordinary/" + GENERATED_TCU,
                     "artifacts/checked/" + GENERATED_TCU, "artifacts/checked/sw/VX_config.h"):
            with self.subTest(name=name):
                members = dict(self.original)
                del members[PREFIX + name]
                self.reject(members, "missing retained member")

    def test_source_tool_config_object_and_binary_drift_are_rejected(self):
        changes = (
            (lambda report: report["source_after"]["files"][0].update(sha256="0" * 64), "source before/after"),
            (lambda report: report["source_after"]["checkout"].update(tree="a" * 40), "source before/after"),
            (lambda report: report["tools_after"]["tools"]["g++"].update(sha256="0" * 64), "tools before/after"),
            (lambda report: report["tools_after"]["dependencies"][replay.DEPENDENCIES[0]].update(sha256="0" * 64),
             "tools before/after"),
            (lambda report: report["variants"][0]["generated_after"][0].update(sha256="0" * 64), "before/after generated"),
            (lambda report: report["variants"][0]["compiler_stamp_after"][0].update(sha256="0" * 64),
             "before/after compiler_stamp"),
            (lambda report: report["variants"][0]["diagnostic_sources_after"][0].update(sha256="0" * 64),
             "before/after diagnostic_sources"),
            (lambda report: report["variants"][0]["objects_after"][0].update(sha256="0" * 64),
             "object before/after"),
            (lambda report: report["variants"][0]["binary_after"].update(sha256="0" * 64), "before/after binary"),
        )
        for change, pattern in changes:
            with self.subTest(pattern=pattern):
                self.reject(self.changed_report(change), pattern)

    def test_source_cleanliness_submodules_and_profile_pin_are_enforced(self):
        for mutation, pattern in (
            (lambda source: source["checkout"].update(dirty=True), "checkout dirty"),
            (lambda source: source.update(untracked_critical=["sim/simx/core.cpp"]), "untracked critical"),
            (lambda source: source["checkout"]["submodules"]["entries"].pop(), "missing or repeated pinned submodule"),
            (lambda source: source["checkout"]["submodules"]["entries"][0].update(status="uninitialized"), "submodule status"),
            (lambda source: source["checkout"]["pins"].update(TOOLCHAIN_REV="forged"), "version pins"),
        ):
            def change(report):
                for key in ("source_before", "source_after"):
                    mutation(report[key])
            with self.subTest(pattern=pattern):
                self.reject(self.changed_report(change), pattern)
        members = dict(self.original)
        name = "profiles/p02-tfr.json"
        replace_source(members, name, members[PREFIX + "artifacts/source/" + name] + b"\n")
        self.reject(members, "frozen p02-tfr profile")

    def test_tool_identity_types_fields_dependency_inventory_and_python_are_checked(self):
        for mutation, pattern in (
            (lambda tools: tools["tools"]["g++"].update(size_bytes=True), "recorded file size"),
            (lambda tools: tools["tools"]["g++"].update(extra=1), "recorded file identity"),
            (lambda tools: tools["tools"]["executing_python"].update(sha256="0" * 64), "executing/PATH Python"),
            (lambda tools: tools["dependencies"].pop(replay.DEPENDENCIES[0]), "linked dependencies"),
            (lambda tools: tools["dependencies"][replay.DEPENDENCIES[0]].update(resolved_path="/unrelated/library"),
             "recorded path resolution"),
        ):
            def change(report):
                for key in ("tools_before", "tools_after"):
                    mutation(report[key])
            with self.subTest(pattern=pattern):
                self.reject(self.changed_report(change), pattern)

    def test_rehashed_generated_tcu_must_equal_production_source_plus_footer(self):
        for variant in ("ordinary", "checked"):
            with self.subTest(variant=variant):
                members = dict(self.original)
                name = PREFIX + "artifacts/" + variant + "/" + GENERATED_TCU
                replace_build(members, variant, GENERATED_TCU, members[name] + b"\n// generated drift\n")
                self.reject(members, "generated TCU|concatenation|production body")

    def test_rehashed_access_wrapper_cannot_omit_its_production_include(self):
        members = dict(self.original)
        name = "tests/unittest/checked_counters/access_socket.cpp"
        body = members[PREFIX + "artifacts/source/" + name]
        self.assertIn(b'#include "../../../sim/simx/socket.cpp"', body)
        replace_source(members, name, body.replace(b'#include "../../../sim/simx/socket.cpp"', b"// omitted include"))
        self.reject(members, "access wrapper|production include|included production")

    def test_missing_fresh_translation_unit_is_rejected_after_rehash(self):
        members = dict(self.original)
        replace_log(members, "ordinary-build", lambda body: b"\n".join(body.splitlines()[1:]) + b"\n")
        self.reject(members, "exact fresh compile/link source inventory")

    def test_duplicate_translation_unit_and_missing_link_are_rejected_after_rehash(self):
        for change, pattern in (
            (lambda body: body.splitlines()[0] + b"\n" + body, "compiled object is repeated"),
            (lambda body: b"\n".join(body.splitlines()[:-1]) + b"\n", "exact fresh compile/link source inventory"),
        ):
            with self.subTest(pattern=pattern):
                members = dict(self.original)
                replace_log(members, "ordinary-build", change)
                self.reject(members, pattern)

    def test_link_requires_every_fresh_object_and_identified_library(self):
        for token in (b"-lramulator ", b"-lramulator-vortex ", b"-Wl,--push-state,--no-as-needed "):
            with self.subTest(token=token):
                members = dict(self.original)
                self.assertIn(token, members[PREFIX + "logs/ordinary-build.log"])
                replace_log(members, "ordinary-build", lambda body: body.replace(token, b"", 1))
                self.reject(members, "fresh objects and identified dependencies")
        members = dict(self.original)
        object_path = self.original_report["variants"][0]["objects_after"][0]["path"].encode() + b" "
        replace_log(members, "ordinary-build", lambda body: body.replace(object_path, b"", 1))
        self.reject(members, "fresh objects and identified dependencies")

    def test_compiler_log_cannot_use_a_different_translation_unit_guard_or_flags(self):
        cases = (
            ("ordinary-build", lambda body: body.replace(b" -O2 ", b" -O3 ", 1)),
            ("ordinary-build", lambda body: body.replace(b" -O2 ", b" -O2 -DSIMX_CHECKED_COUNTERS=1 ", 1)),
            ("checked-build", lambda body: body.replace(b" -DSIMX_CHECKED_COUNTERS=1 ", b" ", 1)),
        )
        for command, change in cases:
            with self.subTest(command=command):
                members = dict(self.original)
                replace_log(members, command, change)
                self.reject(members, "translation-unit flags differ")

    def test_rehashed_compiler_stamps_cannot_change_guard_release_or_topology(self):
        for variant, before, after, pattern in (
            ("checked", b" -DSIMX_CHECKED_COUNTERS=1 ", b" ", "checked-counter selection"),
            ("checked", b" -DSIMX_CHECKED_COUNTERS=1 ", b" -DSIMX_CHECKED_COUNTERS=0 ", "checked-counter selection"),
            ("ordinary", b" -O2 ", b" -O2 -DSIMX_CHECKED_COUNTERS=1 ", "checked-counter selection"),
            ("ordinary", b" -O2 ", b" -O0 ", "release, optimization"),
            ("ordinary", b" -DVX_CFG_NUM_THREADS=4 ", b" -DVX_CFG_NUM_THREADS=8 ", "configuration|NUM_THREADS"),
        ):
            with self.subTest(variant=variant, pattern=pattern):
                members = dict(self.original)
                body = members[PREFIX + "artifacts/" + variant + "/" + STAMP]
                self.assertIn(before, body)
                replace_build(members, variant, STAMP, body.replace(before, after, 1))
                self.reject(members, pattern)

    def test_rehashed_configuration_copy_probe_and_template_are_checked(self):
        for name, body, pattern in (
            ("config.mk", b"XLEN ?= 32\nOSVERSION ?= ubuntu2404\n", "config.mk template expansion"),
            (".config.stamp", b"XLEN=32\n", "generated configure stamp"),
            ("sim/common.mk", b"CONFIGS += -DSIMX_FUNCTIONAL\n", "copied source"),
            ("checked-header-probe.cpp", b"#include </unrelated/header.h>\n", "header probe source"),
        ):
            with self.subTest(name=name):
                members = dict(self.original)
                replace_build(members, "ordinary", name, body)
                self.reject(members, pattern)

    def test_raw_effective_header_and_stored_configuration_must_agree(self):
        for command, change in (
            ("ordinary-header", lambda body: body + b"#define SIMX_CHECKED_COUNTERS 1\n"),
            ("checked-header", lambda body: body.replace(b"#define SIMX_CHECKED_COUNTERS 1\n", b"")),
            ("ordinary-header", lambda body: body + b"#define SIMX_FUNCTIONAL 1\n"),
        ):
            with self.subTest(command=command):
                members = dict(self.original)
                replace_log(members, command, change)
                self.reject(members, "effective checked-counter macro|timing mode")
        self.reject(self.changed_report(lambda report: report["variants"][0]["effective_configuration"].update(unexpected=True)),
                    "recomputed effective configuration")

    def test_compiler_summary_and_object_identities_are_recomputed_and_typed(self):
        for change, pattern in (
            (lambda report: report["variants"][0]["compiler_records"].update(translation_units=44), "compiler/link/source/object"),
            (lambda report: report["variants"][0]["compiler_records"].update(link_count=True), "compiler/link/source/object"),
            (lambda report: report["variants"][0]["compiler_records"]["compiled_sources"].pop(), "compiler/link/source/object"),
            (lambda report: report["variants"][0]["compiler_records"]["object_identities"][0].update(size_bytes=True),
             "recorded file size"),
            (lambda report: report["variants"][0]["compiler_records"]["object_identities"][0].update(path="/different/object.o"),
             "recorded file path"),
        ):
            with self.subTest(pattern=pattern):
                self.reject(self.changed_report(change), pattern)

    def test_binary_identity_fields_and_resolved_path_are_checked_without_payloads(self):
        for change, pattern in (
            (lambda row: row.update(size_bytes=True), "recorded file size"),
            (lambda row: row.update(sha256="not-a-digest"), "recorded file digest"),
            (lambda row: row.update(resolved_path="/different/binary"), "recorded path resolution"),
            (lambda row: row.update(extra="unrecognized"), "recorded file identity"),
        ):
            def mutate(report):
                for key in ("binary_before", "binary_after"):
                    change(report["variants"][0][key])
            with self.subTest(pattern=pattern):
                self.reject(self.changed_report(mutate), pattern)

    def test_missing_reordered_or_duplicate_selectors_are_rejected_after_rehash(self):
        for change in (lambda row: row["transport_selectors"].pop(),
                       lambda row: row["transport_selectors"].reverse(),
                       lambda row: row["transport_selectors"].__setitem__(-1, "cycles")):
            members = dict(self.original)
            replace_result(members, "ordinary-boundaries", change, mirror=True)
            self.reject(members, "boundary result differs")

    def test_old_19_selector_result_cannot_be_relabelled_as_schema_two(self):
        members = dict(self.original)

        def old_result(row):
            # Keep the new version label and new all-33 claims, but substitute
            # the real old contract's seeded/unseeded selector split and counts.
            unseeded = [name for name in row["transport_selectors"] if name not in OLD_SELECTORS]
            row.update(schema_version=2, transport_selectors=list(OLD_SELECTORS), transport_reads=760,
                       checks=2749, unseeded_available_selectors=unseeded)
        for command in ("ordinary-boundaries", "checked-boundaries"):
            replace_result(members, command, old_result, mirror=True)
        self.reject(members, "boundary result differs")

    def test_raw_results_and_report_observations_cannot_disagree(self):
        for index, field, value in ((0, "checks", 6388), (1, "checked", False),
                                    (2, "suppressed_tasks", 3), (6, "actual_dcr_query", False)):
            with self.subTest(index=index, field=field):
                self.reject(self.changed_report(lambda report: report["cells"][index]["observations"].update({field: value})),
                            "recomputed diagnostic observations")
        for command, change in (("ordinary-boundaries", lambda row: row.update(failures=1)),
                                ("checked-core-overflow", lambda row: row.update(terminal_failure=False)),
                                ("checked-tcu-backing-overflow", lambda row: row.update(source_unchanged=False))):
            with self.subTest(command=command):
                members = dict(self.original)
                replace_result(members, command, change)
                self.reject(members, "result differs")

    def test_raw_result_integer_boolean_types_and_extra_fields_are_rejected(self):
        for command, key, value in (("ordinary-boundaries", "failures", False),
                                    ("ordinary-boundaries", "perf", 1),
                                    ("ordinary-boundaries", "schema_version", 2.0),
                                    ("ordinary-boundaries", "extra", False),
                                    ("checked-core-overflow", "schema_version", True),
                                    ("checked-core-overflow", "joined", 1),
                                    ("checked-core-overflow", "extra", False)):
            with self.subTest(command=command, key=key):
                members = dict(self.original)
                replace_result(members, command, lambda row: row.update({key: value}), mirror=True)
                self.reject(members, "result differs")

    def test_raw_results_reject_duplicate_json_keys_and_repeated_records(self):
        for command in ("ordinary-boundaries", "checked-core-overflow"):
            for mutation, pattern in (
                (lambda body: body.replace(b'{"schema_version":', b'{"schema_version":2,"schema_version":', 1),
                 "repeats a key"),
                (lambda body: body + body, "missing, repeated|unique failure result"),
            ):
                with self.subTest(command=command, pattern=pattern):
                    members = dict(self.original)
                    replace_log(members, command, mutation)
                    self.reject(members, pattern)

    def test_boundary_log_cannot_also_claim_a_negative_failure_result(self):
        members = dict(self.original)
        negative = members[PREFIX + "logs/checked-core-overflow.log"]
        replace_log(members, "ordinary-boundaries", lambda body: body + negative)
        self.reject(members, "failure|negative|unexpected|boundary")

    def test_negative_logs_reject_failure_text_and_boundary_records(self):
        for suffix in (b"FAILED: unexpected work\n", b"SIMX_CHECKED_COUNTER_FAILURE overflow\n",
                       self.original[PREFIX + "logs/ordinary-boundaries.log"]):
            with self.subTest(suffix=suffix[:50]):
                members = dict(self.original)
                replace_log(members, "checked-core-overflow", lambda body: body + suffix)
                self.reject(members, "unique failure result")

    def test_process_status_types_cleanup_and_failure_are_rejected(self):
        for key, value in (("exit_code", True), ("exit_code", 0.0), ("exit_code", 1),
                           ("process_started", 1), ("process_started", False),
                           ("cleanup_complete", 1), ("cleanup_complete", False),
                           ("outcome", "timeout"), ("reason", "terminated")):
            with self.subTest(key=key, value=value):
                self.reject(self.changed_report(lambda report: report["commands"][-1].update({key: value})),
                            "command .*" + key)

    def test_command_resource_budgets_and_timeouts_are_exact(self):
        for key, value, pattern in (("timeout_seconds", 31, "timeout"),
                                    ("timeout_seconds", True, "timeout"),
                                    ("duration_seconds", True, "duration"),
                                    ("duration_seconds", -1, "duration"),
                                    ("duration_seconds", 36, "duration"),
                                    ("peak_rss_bytes", True, "peak RSS"),
                                    ("peak_rss_bytes", 4 * 1024**3 + 1, "peak RSS"),
                                    ("log_size_bytes", True, "log bytes"),
                                    ("log_size_bytes", 16 * 1024**2 + 1, "log bytes")):
            with self.subTest(key=key, value=value):
                self.reject(self.changed_report(lambda report: report["commands"][0].update({key: value})), pattern)
        for command, timeout in (("ordinary-configure", 121), ("ordinary-build", 1801), ("ordinary-boundaries", 181)):
            def change(report):
                next(row for row in report["commands"] if row["id"] == command)["timeout_seconds"] = timeout
            with self.subTest(command=command):
                self.reject(self.changed_report(change), "timeout")

    def test_initial_budget_memory_disk_and_environment_are_bounded(self):
        for change, pattern in (
            (lambda report: report["budget"].update(max_rss_bytes=8 * 1024**3), "fixed diagnostic budget"),
            (lambda report: report["budget"].update(threads=True), "fixed diagnostic budget"),
            (lambda report: report["budget"]["timeouts_seconds"].update(run=181), "fixed diagnostic budget"),
            (lambda report: report.update(available_memory_bytes=True), "available memory"),
            (lambda report: report.update(available_memory_bytes=4 * 1024**3 - 1), "available memory"),
            (lambda report: report["free_disk_bytes"].update(work=15 * 1024**3 - 1), "initial disk reserve"),
            (lambda report: report["free_disk_bytes"].update(output=True), "initial disk reserve"),
            (lambda report: report["environment"].update(LD_PRELOAD="/untrusted.so"), "sanitized environment"),
        ):
            with self.subTest(pattern=pattern):
                self.reject(self.changed_report(change), pattern)

    def test_command_identity_argv_environment_and_working_directory_are_exact(self):
        for change, pattern in (
            (lambda report: report["commands"][0].update(id="different"), "command order"),
            (lambda report: report["commands"][0]["argv"].append("--injected"), "command argv"),
            (lambda report: report["commands"][0].update(cwd=report["paths"]["source"]), "command cwd"),
            (lambda report: report["commands"][0]["environment"].update(LD_PRELOAD="/untrusted.so"), "command environment"),
            (lambda report: report["commands"][0].update(log="logs/different.log"), "command log path"),
            (lambda report: report["commands"][0].update(limitations=[]), "process limitations"),
        ):
            with self.subTest(pattern=pattern):
                self.reject(self.changed_report(change), pattern)

    def test_recorded_roots_are_syntactic_canonical_and_nonoverlapping(self):
        for change, pattern in (
            (lambda report: report["paths"].update(source="/tmp/../source"), "member name"),
            (lambda report: report["paths"].update(source="/tmp/source;command"), "unsafe producer root"),
            (lambda report: report["paths"].update(output=report["paths"]["work"] + "/evidence"), "overlap"),
        ):
            with self.subTest(pattern=pattern):
                self.reject(self.changed_report(change), pattern)

    def test_interpreter_version_is_read_from_original_log(self):
        for command in ("version-python3", "version-executing_python"):
            with self.subTest(command=command):
                members = dict(self.original)
                replace_log(members, command, lambda _: b"Python 3.12.13\n")
                self.reject(members, "pinned interpreter version")

    def test_cell_inventory_outcomes_and_types_are_exact(self):
        for change, pattern in (
            (lambda report: report["cells"].pop(), "native cell inventory"),
            (lambda report: report["cells"].reverse(), "native cell order"),
            (lambda report: report["cells"][0].update(exit_code=False), "cell exit_code"),
            (lambda report: report["cells"][0].update(run_process_started=1), "cell run_process_started"),
            (lambda report: report["cells"][0].update(run_outcome="timeout"), "cell run_outcome"),
        ):
            with self.subTest(pattern=pattern):
                self.reject(self.changed_report(change), pattern)

    def test_unconsumed_diagnostic_members_and_trailing_commands_are_rejected(self):
        for name in ("unconsumed.json", "logs/extra.log", "artifacts/source/untrusted.py"):
            with self.subTest(name=name):
                members = dict(self.original)
                members[PREFIX + name] = b"unconsumed retained data\n"
                self.reject(members, "diagnostic archive member closure")
        self.reject(self.changed_report(lambda report: report["commands"].append(copy.deepcopy(report["commands"][-1]))),
                    "exact native command count|trailing command")
        self.reject(self.changed_report(lambda report: report["commands"].pop()), "required command is missing")

    def test_cli_failure_retains_all_nonacceptance_flags(self):
        output = io.StringIO()
        with redirect_stdout(output):
            status = replay.main(["--archive", str(ORIGINAL), "--sha256", "0" * 64,
                                  "--source-revision", REVISION])
        self.assertEqual(status, 1)
        result = json.loads(output.getvalue())
        self.assertEqual(result["outcome"], "fail")
        self.assert_nonacceptance(result)


if __name__ == "__main__":
    unittest.main()
