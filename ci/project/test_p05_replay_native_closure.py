# SPDX-License-Identifier: Apache-2.0
"""Host-only source/chronology boundary composition; no original ZIP needed."""

from contextlib import ExitStack
import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import p05_replay_native as replay
import p05_torch_replay as driver
from test_p05_torch_replay_driver import MemoryView, descriptor, encoded


REVISION = "1" * 40
CONTRACTS = ("p04-managed-model-execution-v1", "p05-installed-python-execution-v1")
CHECKOUT_INPUTS = ("VERSION", ".gitmodules", "configure", "config.mk.in", "VX_config.toml",
                   "VX_types.toml", "ci/gen_config.py", "ci/blackbox.sh")
ABSENT_SOURCE = "third_party/unretained/header.h"
SCOPE = "SYNTHETIC HOST-ONLY DATA; NO ACCELERATOR EXECUTION"


def report_envelope(native, fmt="fp16"):
    base = "/missing producer;$(never-run)"
    paths = {key: base + "/" + key for key in ("source", "tools", "verilator")}
    paths.update(host_bin=None, work=base + ("/native-work" if native else "/python-work"),
                 output=base + ("/native-output" if native else "/python-output"))
    if not native:
        paths.update(native_build=base + "/native-work/simx-" + fmt, native_output=base + "/native-output")
    budget = {"min_free_bytes": 15 * 1024**3, "max_rss_bytes": 4 * 1024**3,
              "max_log_bytes": replay.MAX_LOG_BYTES, "jobs": 1}
    if not native:
        budget["package_jobs"] = 1
    resources = {"available_memory_bytes": 8 * 1024**3,
                 "free_disk_bytes": {key: 32 * 1024**3 for key in ("source", "tools", "work", "output")}}
    return {"schema_version": 1, "contract_id": CONTRACTS[not native], "state": "finished", "outcome": "pass",
            "reason": None, "development": False, "acceptance_claimed": False, "phase_complete": False,
            "iterations": 2, "started_at": "2026-01-01T00:00:00+00:00",
            "finished_at": "2026-01-01T00:00:10+00:00", "limitations": [SCOPE],
            "paths": paths, "budget": budget, "resources_before": resources, "resources_after": resources,
            "backend": "simx", "format": fmt, "full_matrix_requested": False, "source_stable": True}


def source_fixture(native, fmt="fp16"):
    view, report = MemoryView(), report_envelope(native, fmt)
    retained = replay.NATIVE_RETAINED_SOURCES if native else replay.PYTHON_RETAINED_SOURCES
    names = set(replay.NATIVE_RETAINED_SOURCES + replay.PYTHON_RETAINED_SOURCES + CHECKOUT_INPUTS + (ABSENT_SOURCE,))
    # Deliberately invalid Python is inert source data, never a test dependency.
    bodies = {name: (SCOPE + "\nraise AssertionError('retained code must stay inert')\n" + name).encode()
              for name in names}
    rows = {name: descriptor(name, body) for name, body in bodies.items()}
    source = {"checkout": {"revision": REVISION, "tree": "2" * 40, "dirty": False, "changed_paths": [],
              "untracked_paths": [], "blockers": [], "outcome": "pass", "pins": {"TOOLCHAIN_REV": "synthetic"},
              "inputs": [rows[name] for name in CHECKOUT_INPUTS], "submodules": {"declared_count": 1,
              "errors": [], "entries": [{"path": "third_party/synthetic", "revision": "3" * 40,
                                          "status": "initialized"}]}},
              "files": [rows[name] for name in sorted(rows) if name != "ci/blackbox.sh"]}
    report["retained_sources"] = [view.add("artifacts/source/" + name, bodies[name]) for name in retained]
    helpers = replay.NATIVE_HELPERS if native else replay.PYTHON_HELPERS
    report["loaded_helpers"] = [rows[name] for name in helpers]
    update_source(view, report, source)
    return view, report, source


def update_source(view, report, source):
    for key in ("source_before", "source_after"):
        report[key] = view.document_row("snapshots/" + key.replace("_", "-") + ".json", source)


def drop_source(view, report, source, name, *, drop_receipt=False):
    member = "artifacts/source/" + name
    del view.payloads[view.name(member)]
    report["retained_sources"] = [row for row in report["retained_sources"] if row["path"] != member]
    report["loaded_helpers"] = [row for row in report["loaded_helpers"] if row["path"] != name]
    if drop_receipt:
        source["files"] = [row for row in source["files"] if row["path"] != name]
        update_source(view, report, source)


def outer_fixture(fmt, *, remove=None):
    outer = MemoryView()
    for native, prefix in ((True, "native-model"), (False, "python")):
        view, report, source = source_fixture(native, fmt)
        if remove is native:
            drop_source(view, report, source,
                        "tests/regression/ai_mlp/main.cpp" if native else "python/README.md")
        view.document_row("report.json", report)
        for name in view.files():
            outer.add(prefix + "/" + name, view.read(name))
    # Repair every copy coherently, so missing-source failures cannot be
    # attributed to an asymmetric copy or a stale copied descriptor.
    native = outer.subview("native-model")
    for name in native.files():
        outer.add("python/native/" + name, native.read(name))
    python = outer.subview("python")
    for name in python.files():
        outer.add("torch/python/" + name, python.read(name))
    return outer


def command_fixture(native, total):
    report, view = report_envelope(native), MemoryView()
    if native:
        ids = ["version-gpp", "version-clang", "version-make"]
        ids += ["simx-fp16-" + suffix for suffix in ("configure", "header", "cpp-header-reproduce",
                "verilog-header-reproduce", "runtime", "application", "effective-header")]
    else:
        ids = ["package-tools-before", "native-matmul-build", "native-matmul-effective-header",
               "package-bound-sdist", "package-offline-wheel", "package-create-venv",
               "package-install-wheel", "installed-matrix", "package-tools-after"]
        report["packages"] = [descriptor("packages/wheel/synthetic.whl", b"inert wheel")]
    report["commands"] = []
    for index, name in enumerate(ids):
        log = view.add("logs/" + name + ".log", b"")
        report["commands"].append({"id": name, "argv": ["/missing/tool"], "cwd": "/missing/work",
            "environment": {}, "log": log["path"], "log_sha256": log["sha256"], "log_size_bytes": 0,
            "timeout_seconds": 30, "outcome": "pass", "exit_code": 0, "reason": None,
            "process_started": True, "duration_seconds": total - len(ids) + 1 if index == 0 else 1,
            "peak_rss_bytes": 1024, "cleanup_complete": True, "limitations": list(replay.PROCESS_LIMITATIONS)})
    return view, report


def check_commands(native, total, *, zero_elapsed=False):
    view, report = command_fixture(native, total)
    if zero_elapsed:
        report["finished_at"] = report["started_at"]
    replay._finished(report, CONTRACTS[not native])
    tools = {name: {"path": "/missing/" + name} for name in ("g++", "clang", "make", "python3", "gcc", "ar")}
    compiler = [{}, {"macro_flags": []}]
    # Only argv construction is isolated. Real receipt/log validation, both
    # command entry points and the elapsed-time join remain enabled.
    with patch.object(replay, "_command"), patch.object(replay, "_package_probe", return_value=SCOPE), \
            patch.object(Path, "open", side_effect=AssertionError("producer read")), \
            patch("subprocess.Popen", side_effect=AssertionError("process launch")):
        if native:
            return replay._native_commands(view, report, tools, compiler, "4" * 64, [], REVISION, "fp16")
        request = {"expected_prefix": report["paths"]["work"] + "/venv",
                   "binding": {"bundle_root": report["paths"]["output"] + "/artifacts/bundle"}}
        return replay._python_commands(view, report, tools, compiler, "4" * 64, [], request)


class NativeSourceClosureTests(unittest.TestCase):
    def test_complete_retained_subset_keeps_absent_source_receipts_inert(self):
        for native in (True, False):
            view, report, source = source_fixture(native)
            self.assertIn(ABSENT_SOURCE, {row["path"] for row in source["files"]})
            self.assertNotIn("artifacts/source/" + ABSENT_SOURCE, view.files())
            with patch.object(Path, "open", side_effect=AssertionError("producer read")), \
                    patch("subprocess.Popen", side_effect=AssertionError("process launch")):
                self.assertEqual(replay._source(view, report, REVISION), source)

    def test_every_mandatory_source_survives_coherent_deletion_attempts(self):
        for native in (True, False):
            original = source_fixture(native)
            required = replay.NATIVE_RETAINED_SOURCES if native else replay.PYTHON_RETAINED_SOURCES
            for name in required:
                for drop_receipt in (False, True):
                    with self.subTest(native=native, name=name, drop_receipt=drop_receipt):
                        view, report, source = copy.deepcopy(original)
                        drop_source(view, report, source, name, drop_receipt=drop_receipt)
                        with self.assertRaisesRegex(ValueError, "retained sources paths"):
                            replay._source(view, report, REVISION)

    def test_unexpected_source_cannot_be_added_by_rewriting_all_receipts(self):
        for native in (True, False):
            view, report, source = source_fixture(native)
            name, body = "unexpected.cpp", b"inert"
            source["files"].append(descriptor(name, body))
            source["files"].sort(key=lambda row: row["path"])
            report["retained_sources"].append(view.add("artifacts/source/" + name, body))
            report["retained_sources"].sort(key=lambda row: row["path"])
            update_source(view, report, source)
            with self.assertRaisesRegex(ValueError, "retained sources paths"):
                replay._source(view, report, REVISION)

    def test_public_archive_reaches_real_native_source_closure_in_both_formats(self):
        # This composes the real ArchiveReader, public driver, copy checks and
        # native source validation. It stops before unrelated build/numerical
        # stages; these synthetic source packets do not claim native execution.
        class SourceBoundaryReached(Exception):
            pass

        for fmt in ("fp16", "bf16"):
            for remove in (None, True, False):
                with self.subTest(fmt=fmt, remove=remove), tempfile.TemporaryDirectory() as root:
                    path = Path(root) / "synthetic.zip"
                    outer = outer_fixture(fmt, remove=remove)
                    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                        for name in outer.files():
                            archive.writestr(name, outer.read(name))
                    digest = hashlib.sha256(path.read_bytes()).hexdigest()
                    with ExitStack() as stack:
                        stack.enter_context(patch.object(driver, "_report", return_value=({}, {}, {}, {}, {})))
                        stack.enter_context(patch.object(driver, "_hosted", return_value={}))
                        stack.enter_context(patch.object(replay, "_tools", side_effect=SourceBoundaryReached))
                        stack.enter_context(patch("subprocess.Popen", side_effect=AssertionError("process launch")))
                        expected = self.assertRaises(SourceBoundaryReached) if remove is None else \
                            self.assertRaisesRegex(ValueError, "retained sources paths")
                        with expected:
                            driver.replay_archive(path, digest, expected_revision=REVISION, expected_format=fmt)


class NativeChronologyTests(unittest.TestCase):
    def test_both_routes_accept_only_the_fixed_two_second_endpoint_allowance(self):
        for native in (True, False):
            with self.subTest(native=native):
                self.assertTrue(check_commands(native, 12))
                with self.assertRaisesRegex(ValueError, "commands exceed the recorded execution interval"):
                    check_commands(native, 12.000001)

    def test_sequential_sum_cannot_fit_inside_zero_elapsed_report(self):
        for native in (True, False):
            with self.subTest(native=native), self.assertRaisesRegex(ValueError, "recorded execution interval"):
                check_commands(native, 12, zero_elapsed=True)


if __name__ == "__main__":
    unittest.main()
