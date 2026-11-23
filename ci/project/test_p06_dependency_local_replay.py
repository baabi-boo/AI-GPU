# SPDX-License-Identifier: Apache-2.0
"""Local envelope controls around synthetic native and control originals.

Dependency semantics are stubbed at their existing independent boundary. All
native/control and local-envelope readers run; this fixture is not execution.
"""

from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path, PurePosixPath
import tempfile
import unittest
from unittest import mock
import zipfile

import p06_dependency_local_replay as replay
from test_p06_dependency_control_replay import SyntheticNativeWithControlTools, SyntheticControls
from test_p06_dependency_native_replay import descriptor, digest, inert_path_guards, json_bytes


class SyntheticLocalNative(SyntheticNativeWithControlTools):
    def __init__(self, toolchain_sha256=None):
        self.toolchain_sha256 = toolchain_sha256
        super().__init__()

    def make_dependencies(self):
        super().make_dependencies()
        self.workspace = str(PurePosixPath(self.report["paths"]["work"]).parent)
        source, tools = self.report["paths"]["source"], self.report["paths"]["tools"]
        self.preparation = {
            "contract_id": replay.receipts.local_prepare.CONTRACT_ID, "execution_origin": "local",
            "source_dir": source, "workspace_dir": self.workspace, "archive_root": "/synthetic-local-archives",
            "dependency_repositories_root": "/synthetic-local-repositories", "host_bin": self.report["paths"]["host_bin"],
            "source_before": deepcopy(self.source["checkout"]), "tools_dir": tools,
            "toolchain_receipt": {"tools": {name: deepcopy(self.tools[name]) for name in replay.toolchain.NATIVE_TOOLS}},
            "host_tools": {name: deepcopy(self.tools[name]) for name in ("gcc", "g++", "ar", "make", "python3")},
            "outcome": "pass", "reason": None, "native_execution": "not_run",
        }
        if self.toolchain_sha256 is not None:
            self.preparation["toolchain_receipt"]["tools"]["clang"]["sha256"] = self.toolchain_sha256
        self.preparation_body = json_bytes(self.preparation)
        self.dependency_document["preparation"] = descriptor("snapshots/preparation.json", self.preparation_body)
        self.dependency_document["paths"]["workspace"] = self.workspace
        self.dependency_document.update(outcome="pass", reason=None, fresh_dependency_build_passed=True)
        self.dependency_body = json_bytes(self.dependency_document)
        self.receipt_pin = digest(self.dependency_body)
        self.admission, self.stability = replay.native_replay._admission_values(
            self.dependency_document, self.dependency_verification, self.receipt_pin)


def synthetic_local_packet(original, native, controls):
    files = {"native-lifetime/" + name: body for name, body in original.files.items()}
    files.update({"dependency-build/report.json": original.dependency_body,
                  "dependency-build/snapshots/preparation.json": original.preparation_body,
                  "dependency-preparation.json": original.preparation_body})
    files.update({"pending-probe/" + name: body for name, body in controls.probe_files.items()})
    files.update({"dependency-substitution/" + name: body for name, body in controls.substitution_files.items()})
    files[replay.RETAINED_PRODUCER] = (replay.ROOT / replay.PRODUCER_SOURCE).read_bytes()
    paths = {"source": str(native.paths["source"]), "workspace": original.workspace,
             "archive": original.preparation["archive_root"],
             "repositories": original.preparation["dependency_repositories_root"],
             "host_bin": original.preparation["host_bin"]}
    interpreter = dict(native.tools["executing_python"], python_version=[3, 12, 14],
                       implementation="CPython", platform="linux")
    environment = replay.producer.clean_environment(paths, interpreter["path"])
    begun, ended = replay._timestamp(native.report["started_at"]), replay._timestamp(native.report["finished_at"])
    start, finish = begun - timedelta(seconds=10), ended + timedelta(seconds=10)
    times = ((start, start + timedelta(seconds=1)), (start + timedelta(seconds=1), begun),
             (begun, ended), (ended, ended), (ended, ended))
    envelope = {"schema_version": 1, "contract_id": replay.producer.CONTRACT_ID,
        "execution_origin": "local", "expected_revision": native.revision, "state": "finished",
        "outcome": "pass", "reason": None, "failures": [], "started_at": start.isoformat(),
        "finished_at": finish.isoformat(), "duration_seconds": (finish - start).total_seconds(),
        "source_dir": paths["source"], "workspace_dir": paths["workspace"], "archive_root": paths["archive"],
        "dependency_repositories_root": paths["repositories"], "host_bin": paths["host_bin"],
        "interpreter": interpreter, "environment": environment, "budget": dict(replay.producer.BUDGET),
        "source_before": deepcopy(native.source["checkout"]), "source_after": deepcopy(native.source["checkout"]),
        "orchestrator_source": descriptor(replay.RETAINED_PRODUCER, files[replay.RETAINED_PRODUCER]),
        "stages": [], "reports": {}, "native_execution": "run", "fresh_dependency_build_passed": True,
        "dependency_source_to_loaded_binary_verified": True, "separate_controls_passed": True,
        **dict.fromkeys(replay.contract.FALSE_CLAIMS, False), "limitations": list(replay.producer.LIMITATIONS)}
    reports = dict(replay.REPORTS, **{"native-source": "native-lifetime/" + native.report["source_before"]["path"]})
    envelope["reports"] = {name: descriptor(path, files[path]) for name, path in reports.items()}
    specifications = replay.producer.stage_specs(paths, native.revision, interpreter["path"], original.receipt_pin)
    elapsed = 0.0
    for spec, (begin, end) in zip(specifications, times):
        report = json.loads(files[spec["report_path"]])
        body = (json.dumps(replay.producer.report_terminal(spec["id"], report, paths),
                           sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
        log = "local-logs/" + spec["id"] + ".log"
        files[log] = body
        envelope["stages"].append({"id": spec["id"], "argv": spec["argv"], "cwd": spec["cwd"],
            "environment": deepcopy(environment), "timeout_seconds": min(spec["timeout_seconds_max"],
                replay.producer.BUDGET["execution_timeout_seconds"] - elapsed),
            "log": log, "started_at": begin.isoformat(), "finished_at": end.isoformat(),
            "outcome": "pass", "exit_code": 0, "reason": None, "process_started": True,
            "duration_seconds": (end - begin).total_seconds(), "log_sha256": digest(body),
            "log_size_bytes": len(body), "peak_rss_bytes": 4096, "cleanup_complete": True,
            "limitations": list(replay.PROCESS_LIMITATIONS)})
        elapsed += (end - begin).total_seconds()
    files[replay.ENVELOPE] = json_bytes(envelope)
    return files, envelope


class LocalDependencyReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = SyntheticLocalNative()
        cls.native = cls.original.reader()
        cls.native_result = cls.native.run()
        cls.controls = SyntheticControls(cls.original, cls.native)
        cls.files, cls.envelope = synthetic_local_packet(cls.original, cls.native, cls.controls)

    def setUp(self):
        self.files = dict(type(self).files)
        self.envelope = deepcopy(type(self).envelope)
        self.temporary = tempfile.TemporaryDirectory(prefix="p06-local-replay-")
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "synthetic.zip"

    def arguments(self):
        return {"expected_revision": self.original.revision, "expected_receipt_sha256": self.original.receipt_pin,
            "expected_native_report_sha256": self.controls.native_pin,
            "expected_source_manifest_sha256": self.original.source_pin,
            "expected_probe_report_sha256": self.controls.probe_pin,
            "expected_substitution_report_sha256": self.controls.substitution_pin,
            "expected_local_execution_sha256": digest(self.files[replay.ENVELOPE])}

    def archive(self, prefix=""):
        stem = prefix + "/" if prefix else ""
        with zipfile.ZipFile(self.path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, body in sorted(self.files.items()):
                archive.writestr(stem + name, body)
        return digest(self.path.read_bytes())

    def dependency_boundary(self, view, *, expected_revision, expected_receipt_sha256):
        self.assertEqual(expected_revision, self.original.revision)
        replay.require(expected_receipt_sha256 == digest(view.read("report.json")),
                       "synthetic dependency boundary: externally pinned receipt differs")
        return {"retained_dependency_verification": self.original.dependency_verification,
                "synthetic_dependency_boundary": True}

    def check(self, *, prefix="", **arguments):
        self.files[replay.ENVELOPE] = json_bytes(self.envelope)
        kwargs = dict(self.arguments(), **arguments)
        pin = self.archive(prefix)
        with mock.patch.object(replay.native_replay.dependency_replay, "verify_view",
                               side_effect=self.dependency_boundary):
            return replay.replay_archive(self.path, pin, prefix=prefix, **kwargs)

    def test_complete_local_archive_reuses_native_and_both_control_semantics_inertly(self):
        inert_open, inert_resolve = inert_path_guards(replay.ROOT, replay.TRUSTED_READER_SOURCES,
            (*replay.native_replay.common.CORPUS, replay.native_replay.archive_helpers.ARCHIVE_READER_PATH),
            input_archive=self.path)

        with mock.patch("subprocess.Popen", side_effect=AssertionError("retained process executed")), \
             mock.patch.object(replay.receipts, "PacketReader", side_effect=AssertionError("live receipt reader used")), \
             mock.patch.object(replay.controls.substitution, "verify_records", side_effect=AssertionError("live tool records used")), \
             mock.patch.object(zipfile.ZipFile, "extractall", side_effect=AssertionError("archive extracted")), \
             mock.patch.object(Path, "open", new=inert_open), mock.patch.object(Path, "resolve", new=inert_resolve):
            result = self.check()
        self.assertEqual(result["managed_counts"]["launches"], 132)
        self.assertEqual(result["dependency_substitution"]["control_counts"]["launches"], 33)
        self.assertEqual(result["local_identity"]["toolchain_identities_joined"], 11)
        self.assertEqual(result["local_identity"]["stages_checked"], 5)
        self.assertEqual(result["native_review"]["commands_checked"], 37)
        self.assertEqual(result["native_execution"], "not_run")
        self.assertIs(result["retained_code_executed"], False)
        self.assertIs(result["local_identity"]["origin_authenticated"], False)
        self.assertTrue(all(result[name] is False for name in replay.contract.FALSE_CLAIMS))
        self.assertNotIn("hosted_identity", result)

    def test_literal_packet_prefix_is_supported(self):
        self.assertEqual(self.check(prefix="retained/original")["prefix"], "retained/original")

    def test_each_external_pin_is_required_and_must_match(self):
        for name in self.arguments():
            with self.subTest(name=name):
                value = "0" * (40 if name == "expected_revision" else 64)
                with self.assertRaises(ValueError):
                    self.check(**{name: value})

    def test_local_envelope_is_pinned_before_native_graph_work(self):
        with mock.patch.object(replay.native_replay, "verify_view", side_effect=AssertionError("graph was reached")), \
             self.assertRaisesRegex(ValueError, "externally pinned local envelope"):
            self.check(expected_local_execution_sha256="0" * 64)

    def test_absent_external_pins_fail_before_archive_intake(self):
        for name in ("sha256", *self.arguments()):
            with self.subTest(name=name):
                arguments = dict(self.arguments(), sha256="a" * 64)
                arguments[name] = None
                with mock.patch.object(replay.native_replay.dependency_replay, "_archive_api",
                                       side_effect=AssertionError("archive intake reached")), \
                     self.assertRaises(ValueError):
                    replay.replay_archive(self.path, **arguments)

    def test_origin_fields_flags_and_schema_cannot_masquerade_as_hosted(self):
        changes = (lambda row: row.update(execution_origin="github"),
                   lambda row: row.update(GITHUB_RUN_ID="1"),
                   lambda row: row.update(contract_id="p06-dependency-controls-replay-v1"),
                   lambda row: row.update(schema_version=True),
                   lambda row: row.update(native_execution="not_run"),
                   lambda row: row.update(qualified=True),
                   lambda row: row.update(separate_controls_passed=False),
                   lambda row: row.update(failures=[{"reason": "earlier failure"}]))
        for change in changes:
            with self.subTest(change=change):
                self.envelope = deepcopy(type(self).envelope)
                change(self.envelope)
                with self.assertRaises(ValueError):
                    self.check()

    def test_stage_order_success_and_bounds_cannot_be_relabelled(self):
        changes = (lambda rows: rows.reverse(), lambda rows: rows.pop(),
                   lambda rows: rows.append(deepcopy(rows[-1])),
                   lambda rows: rows[2].update(process_started=False),
                   lambda rows: rows[2].update(exit_code=1),
                   lambda rows: rows[2].update(exit_code=False),
                   lambda rows: rows[2].update(cleanup_complete=False),
                   lambda rows: rows[2].update(timeout_seconds=5401),
                   lambda rows: rows[2].update(timeout_seconds=5400),
                   lambda rows: rows[2].update(duration_seconds=5401),
                   lambda rows: rows[2].update(peak_rss_bytes=4 * 1024**3 + 1),
                   lambda rows: rows[1]["argv"].append("--unreviewed"),
                   lambda rows: rows[1]["environment"].update(LD_PRELOAD="/foreign.so"))
        for change in changes:
            with self.subTest(change=change):
                self.envelope = deepcopy(type(self).envelope)
                change(self.envelope["stages"])
                with self.assertRaises(ValueError):
                    self.check()

    def test_source_toolchain_interpreter_and_time_joins_are_required(self):
        changes = (lambda row: row.update(source_dir="/other/source"),
                   lambda row: row.update(workspace_dir="/other/work"),
                   lambda row: row.update(host_bin="/other/host-bin"),
                   lambda row: row["source_after"].update(tree="0" * 40),
                   lambda row: row["interpreter"].update(sha256="0" * 64),
                   lambda row: row["interpreter"].update(python_version=[3, 12, 15]),
                   lambda row: row.update(duration_seconds=5401),
                   lambda row: row["stages"][0].update(started_at=row["finished_at"]),
                   lambda row: row["reports"]["native-source"].update(sha256="0" * 64))
        for change in changes:
            with self.subTest(change=change):
                self.envelope = deepcopy(type(self).envelope)
                change(self.envelope)
                with self.assertRaises(ValueError):
                    self.check()

    def test_terminal_stdout_and_extra_outer_members_are_bound(self):
        self.files["job.json"] = b'{"GITHUB_RUN_ID":"1"}'
        with self.assertRaisesRegex(ValueError, "complete local packet member inventory"):
            self.check()
        del self.files["job.json"]
        row = self.envelope["stages"][3]
        body = self.files[row["log"]].replace(b'"native_probe_passed": true', b'"native_probe_passed": false')
        self.assertNotEqual(body, self.files[row["log"]])
        self.files[row["log"]] = body
        row.update(log_sha256=digest(body), log_size_bytes=len(body))
        with self.assertRaisesRegex(ValueError, "terminal output"):
            self.check()

    def test_retained_orchestrator_cannot_replace_current_trusted_code(self):
        body = b"raise AssertionError('retained code must not execute')\n"
        self.files[replay.RETAINED_PRODUCER] = body
        self.envelope["orchestrator_source"] = descriptor(replay.RETAINED_PRODUCER, body)
        with self.assertRaisesRegex(ValueError, "local orchestrator source"):
            self.check()

    def test_preparation_native_tool_identity_join_rejects_rebound_packet(self):
        self.original = SyntheticLocalNative(toolchain_sha256="0" * 64)
        self.native = self.original.reader()
        self.native.run()
        self.controls = SyntheticControls(self.original, self.native)
        self.files, self.envelope = synthetic_local_packet(self.original, self.native, self.controls)
        with self.assertRaisesRegex(ValueError, "prepared native tool clang"):
            self.check()

    def test_one_archive_closing_stability_is_required(self):
        api = replay.native_replay.dependency_replay._archive_api()
        original_init, original_receipt = api.ArchiveReader.__init__, api.ArchiveReader.receipt
        opened = []

        def counted_init(reader, *args, **kwargs):
            opened.append(reader)
            original_init(reader, *args, **kwargs)

        def changed_after_receipt(reader):
            result = original_receipt(reader)
            with self.path.open("ab") as stream:
                stream.write(b"changed-after-final-read")
            return result

        with mock.patch.object(replay.native_replay.dependency_replay, "_archive_api", return_value=api), \
             mock.patch.object(api.ArchiveReader, "__init__", new=counted_init), \
             mock.patch.object(api.ArchiveReader, "receipt", new=changed_after_receipt), \
             self.assertRaisesRegex(ValueError, "original ZIP changed"):
            self.check()
        self.assertEqual(len(opened), 1)

    def test_synthetic_dependency_boundary_cannot_pass_unmocked_reader(self):
        self.files[replay.ENVELOPE] = json_bytes(self.envelope)
        pin = self.archive()
        with self.assertRaises(ValueError):
            replay.replay_archive(self.path, pin, **self.arguments())

    def test_hosted_entry_point_rejects_local_packet(self):
        self.files[replay.ENVELOPE] = json_bytes(self.envelope)
        pin = self.archive()
        arguments = self.arguments()
        del arguments["expected_local_execution_sha256"]
        with mock.patch.object(replay.native_replay.dependency_replay, "verify_view", side_effect=self.dependency_boundary), \
             self.assertRaises((ValueError, KeyError)):
            replay.controls.replay_archive(self.path, pin, **arguments)


if __name__ == "__main__":
    unittest.main()
