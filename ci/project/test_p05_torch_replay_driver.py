# SPDX-License-Identifier: Apache-2.0
"""Synthetic host-only checks of the public retained-data driver's boundaries."""

import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import zipfile

import p05_torch_replay as replay


REVISION = "1" * 40
API = replay._archive_api()
SCOPE = "SYNTHETIC HOST-ONLY DATA; NO ACCELERATOR EXECUTION"


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def descriptor(name, body):
    return {"path": name, "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)}


class MemoryView:
    """Strict in-memory packets never map producer paths onto the filesystem."""

    def __init__(self, payloads=None, prefix=""):
        self.payloads = {} if payloads is None else payloads
        self.prefix = prefix

    def name(self, relative):
        API.relative_name(relative)
        return self.prefix + "/" + relative if self.prefix else relative

    def files(self):
        prefix = self.prefix + "/" if self.prefix else ""
        return tuple(name[len(prefix):] for name in sorted(self.payloads) if name.startswith(prefix))

    def subview(self, relative):
        return MemoryView(self.payloads, self.name(relative))

    def add(self, name, body):
        self.payloads[self.name(name)] = body
        return descriptor(name, body)

    def document_row(self, name, value):
        return self.add(name, encoded(value))

    def read(self, name, *, limit=16 * replay.MIB):
        body = self.payloads.get(self.name(name))
        if body is None or len(body) > limit:
            raise ValueError("synthetic member missing or exceeds bound")
        return body

    def identity(self, name, *, limit=API.MEMBER_BYTES):
        return descriptor(name, self.read(name, limit=limit))

    def verified(self, row, expected_path=None, *, limit=16 * replay.MIB):
        API.descriptor(row)
        body = self.read(row["path"], limit=limit)
        if descriptor(row["path"], body) != row or (expected_path is not None and row["path"] != expected_path):
            raise ValueError("synthetic descriptor differs")
        return body

    def json(self, name, *, integers_only=False):
        return API.strict_json(self.read(name), integers_only=integers_only)

    def document(self, row, expected_path=None, *, integers_only=False):
        return API.strict_json(self.verified(row, expected_path), integers_only=integers_only)

    def inventory(self):
        return [self.identity(name) for name in self.files()]


def source_fixture():
    view = MemoryView()
    rows = {name: descriptor(name, (SCOPE + "\n" + name).encode())
            for name in set(replay.RETAINED_SOURCES + replay.CHECKOUT_INPUTS)}
    source = {"checkout": {
        "revision": REVISION, "tree": "2" * 40, "dirty": False, "changed_paths": [],
        "untracked_paths": [], "blockers": [], "outcome": "pass",
        "pins": {"FIRESIM_REV": "3" * 40, "GEM5_REV": "v1", "TOOLCHAIN_REV": "v1", "VORTEX_VERSION": "1"},
        "inputs": [rows[name] for name in replay.CHECKOUT_INPUTS],
        "submodules": {"declared_count": 5, "errors": [], "entries": [
            {"path": name, "revision": "4" * 40, "status": "initialized"} for name in replay.SUBMODULE_PATHS]},
    }, "files": [rows[name] for name in sorted(rows) if name != "ci/blackbox.sh"]}
    report = {"retained_sources": [view.add("artifacts/source/" + name, (SCOPE + "\n" + name).encode())
                                    for name in replay.RETAINED_SOURCES],
              "loaded_helpers": [rows[name] for name in replay.TORCH_HELPERS]}
    update_source(view, report, source)
    return view, report, source


def update_source(view, report, source):
    for key in ("source_before", "source_after"):
        report[key] = view.document_row("snapshots/" + key.replace("_", "-") + ".json", source)


def command_fixture():
    view = MemoryView()
    # Spaces and shell metacharacters stay inert lexical strings.
    base = PurePosixPath("/missing producer;$(never-run)")
    paths = {key: str(base / key) for key in ("source", "output", "python_output", "python_work", "wheelhouse", "work")}
    work, output = PurePosixPath(paths["work"]), PurePosixPath(paths["output"])
    check, interpreter = work / "installed-check", str(work / "venv/bin/python")
    provisioning = "/missing interpreter/bin/python3"
    names = ("filelock", "fsspec", "jinja2", "markupsafe", "mpmath", "networkx", "numpy", "setuptools",
             "sympy", "typing_extensions", "pip", "torch", "vortex_ai")
    versions = {name: "1" for name in names}
    versions.update(torch="2.15.0+cpu", vortex_ai="0.1.0")
    framework = {"distributions": {name: {"version": version} for name, version in versions.items()}}
    report = {"paths": paths, "provisioning_interpreter": {"path": provisioning},
              "requirements": {"path": "artifacts/source/ci/project/p05_torch_requirements.lock"},
              "installed_wheel": {"path": "packages/synthetic.whl"},
              "framework_before": view.document_row("snapshots/framework-before.json", framework), "commands": []}
    environment = {
        "CCACHE_DISABLE": "1", "CMAKE_BUILD_PARALLEL_LEVEL": "1", "LANG": "C", "LC_ALL": "C",
        "MAKEFLAGS": "-j1", "MAX_JOBS": "1", "MKL_NUM_THREADS": "1", "OBJCACHE": "",
        "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "PATH": "/missing interpreter/bin:/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1", "THREADS": "1", "TMPDIR": str(work / "tmp"), "TZ": "UTC",
    }
    probe = [interpreter, "-I", "-B", "-c", replay._probe_source(), str(work / "venv"), encoded(versions).decode()]
    arguments = [
        [provisioning, "-I", "-B", "-m", "venv", "--copies", str(work / "venv")],
        [interpreter, "-I", "-B", "-m", "pip", "--isolated", "install", "--no-index", "--find-links",
         paths["wheelhouse"], "--only-binary=:all:", "--require-hashes", "--no-deps", "--no-compile",
         "--no-cache-dir", "--disable-pip-version-check", "-r", str(output / report["requirements"]["path"])],
        [interpreter, "-I", "-B", "-m", "pip", "--isolated", "install", "--no-index", "--no-deps",
         "--no-compile", "--no-cache-dir", "--disable-pip-version-check", str(output / report["installed_wheel"]["path"])],
        probe,
        [interpreter, "-I", "-B", "-m", "vortex_ai.launch", "--bundle", str(output / "artifacts/bundle"), "--",
         str(check / "p05_torch_installed_check.py"), "--request", str(check / "request.json"), "--output",
         str(check / "observations.json"), "--contract", str(check / "p05_torch_contract.json")],
        list(probe),
    ]
    for name, argv in zip(replay.COMMAND_IDS, arguments):
        log = view.add("logs/" + name + ".log", b"")
        report["commands"].append({
            "id": name, "argv": argv, "cwd": str(check if name == "installed-framework-matrix" else work),
            "environment": dict(environment), "log": log["path"], "log_sha256": log["sha256"], "log_size_bytes": 0,
            "timeout_seconds": 4860 if name == "installed-framework-matrix" else 600, "outcome": "pass",
            "exit_code": 0, "reason": None, "process_started": True, "cleanup_complete": True,
            "duration_seconds": 0.5, "peak_rss_bytes": 4096, "limitations": list(replay.PROCESS_LIMITATIONS),
        })
    request = {"base_request": {"expected_prefix": str(work / "venv"),
                                 "binding": {"bundle_root": str(output / "artifacts/bundle")}}}
    return view, report, request


def provider_fixture():
    view = MemoryView()
    workflow = view.add("workflow.yml", (SCOPE + "\n").encode())
    job = {"GITHUB_EVENT_NAME": "push", "GITHUB_RUN_ID": "12345", "GITHUB_RUN_ATTEMPT": "1",
           "GITHUB_SHA": REVISION, "P05_BACKEND": "simx", "P05_FORMAT": "fp16", "acceptance_claimed": False,
           "native_execution": "not_run", "python_execution": "not_run", "torch_execution": "not_run",
           "scope": "simx-installed-pytorch", "workflow_sha256": workflow["sha256"]}
    provision = {"python_version": [3, 12, 14], "implementation": "CPython", "platform": "linux",
                 "executable": "/missing/bin/python3",
                 "build_requirements": {"packaging": "26.3", "setuptools": "84.2.1", "wheel": "0.48.0"}}
    view.document_row("job.json", job)
    view.document_row("python-provision.json", provision)
    return view, job, provision, {"provisioning_interpreter": {"path": provision["executable"]}}


def packet_fixture():
    """Inventories alone are synthetic; semantic verifiers have separate tests."""
    outer = MemoryView()
    py = outer.subview("python")
    pr = {"commands": [{"log": "logs/synthetic.log"}], "packages": [], "retained_sources": [],
          "native_input": {"files": [{"path": "report.json"}]}, "retained_native_matmul": [{"path": "kernel.bin"}],
          "retained_native_model": [{"path": "model.bin"}], "bundle_artifacts": [{"path": "manifest.json"}]}
    for key in ("bundle_manifest", "observations", "source_before", "source_after", "tools_before", "tools_after",
                "selection", "matmul_binding", "wheel_inventory", "package_source_stage", "extracted_sdist_before_build",
                "installed_before", "installed_after", "installed_request", "package_tools_before", "package_tools_after",
                "native_report"):
        name = {"bundle_manifest": "artifacts/bundle/manifest.json", "observations": "artifacts/installed-observations.json",
                "native_report": "native/report.json"}.get(key, "snapshots/" + key.replace("_", "-") + ".json")
        value = [{"path": "vortex_ai/example.py"}] if key == "installed_before" else {}
        pr[key] = py.document_row(name, value)
    pr["packages"].append(py.add("packages/synthetic.whl", b"inert package"))
    pr["retained_sources"].append(py.add("artifacts/source/example.py", b"inert source"))
    for name in ("report.json", "logs/synthetic.log", "artifacts/native-matmul/kernel.bin", "artifacts/native-model/model.bin",
                 "artifacts/installed/vortex_ai/example.py", "artifacts/sdist-pin/manifest.json",
                 "artifacts/sdist-pin/source_inventory.json", "artifacts/sdist-pin/p05_build_config.h"):
        py.add(name, b"synthetic")
    torch = outer.subview("torch")
    tr = {"commands": [{"log": "logs/synthetic.log"}], "retained_sources": [],
          "bundle_artifacts": [{"path": "manifest.json"}], "installed_wheel": {"path": "packages/synthetic.whl"}}
    for key in ("framework_after", "framework_before", "framework_wheel_payload", "installed_after", "installed_before",
                "installed_helpers", "installed_request", "python_input_after", "source_after", "source_before",
                "venv_seed", "wheelhouse_after"):
        tr[key] = torch.document_row("snapshots/" + key.replace("_", "-") + ".json", {})
    for name in ("report.json", "logs/synthetic.log", "packages/synthetic.whl", "artifacts/installed-observations.json",
                 "artifacts/bundle/manifest.json"):
        torch.add(name, b"synthetic")
    for name in replay.installation_replay.HELPERS:
        torch.add("artifacts/checker/" + name, b"inert helper")
    for name in py.files():
        torch.add("python/" + name, py.read(name))
    outer.add("native-model/report.json", b"synthetic")
    for name in replay.SUPPLEMENTARY_FILES:
        outer.add(name, b"inert supplementary data")
    return outer, tr, {"python_report": pr}


class SourceTests(unittest.TestCase):
    def test_complete_synthetic_source(self):
        view, report, source = source_fixture()
        self.assertEqual(replay._source(view, report, API, REVISION), source)

    def test_removing_helper_from_every_receipt_cannot_hide_it(self):
        view, report, source = source_fixture()
        name = replay.TORCH_HELPERS[0]
        source["files"] = [row for row in source["files"] if row["path"] != name]
        report["loaded_helpers"] = [row for row in report["loaded_helpers"] if row["path"] != name]
        report["retained_sources"] = [row for row in report["retained_sources"] if row["path"] != "artifacts/source/" + name]
        del view.payloads["artifacts/source/" + name]
        update_source(view, report, source)
        with self.assertRaisesRegex(ValueError, "membership"):
            replay._source(view, report, API, REVISION)

    def test_source_requires_clean_strict_checkout_and_submodules(self):
        mutations = [
            lambda s: s["checkout"].update(untracked_paths=["unreviewed.py"]),
            lambda s: s["checkout"].update(unknown=True),
            lambda s: s["checkout"].update(tree="not-a-tree"),
            lambda s: s["checkout"]["submodules"].update(errors=["uninitialized"]),
            lambda s: s["checkout"]["submodules"]["entries"].pop(),
            lambda s: s["checkout"]["inputs"].pop(),
            lambda s: s["files"].reverse(),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                view, report, source = source_fixture()
                mutate(source)
                update_source(view, report, source)
                with self.assertRaises(ValueError):
                    replay._source(view, report, API, REVISION)

    def test_retained_source_byte_change_is_rejected(self):
        view, report, _ = source_fixture()
        view.payloads[report["retained_sources"][0]["path"]] += b"changed"
        with self.assertRaisesRegex(ValueError, "descriptor"):
            replay._source(view, report, API, REVISION)

    def test_extra_retained_source_is_rejected(self):
        view, report, _ = source_fixture()
        view.add("artifacts/source/unaccounted.py", b"never executed")
        with self.assertRaisesRegex(ValueError, "closure"):
            replay._source(view, report, API, REVISION)


class CommandTests(unittest.TestCase):
    def test_commands_accept_inert_paths_and_checker_working_directory(self):
        view, report, request = command_fixture()
        with patch.object(Path, "open", side_effect=AssertionError("producer path was opened")):
            self.assertEqual(set(replay._commands(view, report, request, API)), set(replay.COMMAND_IDS))

    def test_command_inventory_is_complete_ordered_and_typed(self):
        for mutate in (lambda rows: rows.pop(), lambda rows: rows.reverse(),
                       lambda rows: rows.__setitem__(0, None), lambda rows: rows[0].update(extra=True)):
            with self.subTest(mutate=mutate):
                view, report, request = command_fixture()
                mutate(report["commands"])
                with self.assertRaises(ValueError):
                    replay._commands(view, report, request, API)

    def test_checker_cwd_cannot_be_source_or_framework_root(self):
        view, report, request = command_fixture()
        report["commands"][4]["cwd"] = report["paths"]["work"]
        with self.assertRaisesRegex(ValueError, "cwd"):
            replay._commands(view, report, request, API)

    def test_environment_is_exact_without_loader_or_python_overrides(self):
        for key, value in (("LD_PRELOAD", "/missing/evil.so"), ("PYTHONPATH", "/missing/source"),
                           ("PATH", "/different/bin"), ("MAX_JOBS", "2")):
            with self.subTest(key=key):
                view, report, request = command_fixture()
                report["commands"][0]["environment"][key] = value
                with self.assertRaisesRegex(ValueError, "environment"):
                    replay._commands(view, report, request, API)

    def test_failed_cleanup_boolean_exit_or_oversized_resources_are_rejected(self):
        for key, value in (("cleanup_complete", False), ("exit_code", False), ("process_started", False),
                           ("peak_rss_bytes", replay.BUDGET["max_rss_bytes"] + 1),
                           ("log_size_bytes", 16 * replay.MIB + 1), ("duration_seconds", 611),
                           ("duration_seconds", True), ("timeout_seconds", 601), ("limitations", [])):
            with self.subTest(key=key, value=value):
                view, report, request = command_fixture()
                report["commands"][0][key] = value
                with self.assertRaises(ValueError):
                    replay._commands(view, report, request, API)

    def test_changed_probe_and_distribution_closure_are_rejected(self):
        for index, value in ((4, "raise RuntimeError('never execute')"), (6, '{"torch":"2.15.0+cpu","vortex_ai":"0.1.0"}')):
            with self.subTest(index=index):
                view, report, request = command_fixture()
                report["commands"][3]["argv"][index] = value
                with self.assertRaisesRegex(ValueError, "arguments"):
                    replay._commands(view, report, request, API)

    def test_changed_or_unaccounted_command_log_is_rejected(self):
        for extra in (False, True):
            with self.subTest(extra=extra):
                view, report, request = command_fixture()
                view.add("logs/unaccounted.log" if extra else "logs/framework-create-venv.log", b"changed")
                with self.assertRaises(ValueError):
                    replay._commands(view, report, request, API)

    def test_overlapping_recorded_roots_are_rejected_without_resolving_them(self):
        view, report, request = command_fixture()
        report["paths"]["source"] = report["paths"]["work"] + "/source"
        with self.assertRaisesRegex(ValueError, "overlap"):
            replay._commands(view, report, request, API)


class ProviderTests(unittest.TestCase):
    def test_provider_identity_is_explicitly_unauthenticated_and_pre_execution(self):
        view, _, _, report = provider_fixture()
        result = replay._hosted(view, REVISION, "fp16", API, report)
        self.assertFalse(result["origin_authenticated_by_replay"])
        self.assertEqual(result["job_record_stage"], "initial_pre_execution_identity")

    def test_provider_extra_fields_run_ids_and_execution_claims_are_rejected(self):
        for key, value in (("GITHUB_RUN_ID", 12345), ("GITHUB_RUN_ATTEMPT", "01"), ("GITHUB_EVENT_NAME", "unknown"),
                           ("native_execution", "pass"), ("extra", "ignored"), ("GITHUB_SHA", "2" * 40)):
            with self.subTest(key=key):
                view, job, _, report = provider_fixture()
                job[key] = value
                view.document_row("job.json", job)
                with self.assertRaises(ValueError):
                    replay._hosted(view, REVISION, "fp16", API, report)

    def test_provisioning_version_and_executable_join_are_required(self):
        for key, value in (("python_version", [3, 12, 15]), ("executable", "/another/bin/python3"),
                           ("build_requirements", {"setuptools": "84.2.1"})):
            with self.subTest(key=key):
                view, _, provision, report = provider_fixture()
                provision[key] = value
                view.document_row("python-provision.json", provision)
                with self.assertRaises(ValueError):
                    replay._hosted(view, REVISION, "fp16", API, report)

    def test_workflow_bytes_are_bound_to_the_provider_envelope(self):
        view, _, _, report = provider_fixture()
        view.payloads["workflow.yml"] += b"changed"
        with self.assertRaisesRegex(ValueError, "workflow identity"):
            replay._hosted(view, REVISION, "fp16", API, report)


class InventoryAndReaderTests(unittest.TestCase):
    def test_complete_synthetic_packet_members(self):
        outer, report, native = packet_fixture()
        replay._packet_members(outer, report, native, API)

    def test_extra_members_at_each_owned_level_are_rejected(self):
        for name in ("extra.log", "python/extra.py", "torch/extra.py", "torch-native-host/extra.bin"):
            with self.subTest(name=name):
                outer, report, native = packet_fixture()
                outer.add(name, b"not executed")
                with self.assertRaisesRegex(ValueError, "inventory"):
                    replay._packet_members(outer, report, native, API)

    def test_missing_supplementary_member_is_not_silently_ignored(self):
        outer, report, native = packet_fixture()
        del outer.payloads["torch-native-host/children/cleanup_failure/stderr.log"]
        with self.assertRaisesRegex(ValueError, "outer archive member inventory"):
            replay._packet_members(outer, report, native, API)

    def test_recorded_paths_are_bounded_lexical_posix_data(self):
        self.assertEqual(str(replay._absolute("/producer path/$(never);literal")), "/producer path/$(never);literal")
        for value in ("relative", "/", "//server/file", "/a/../b", "/a//b", "/a/./b", "/a\\b",
                      "/a\x80b", "/" + "x" * 4097, "/" + "/".join(["a"] * 65)):
            with self.subTest(value=value[:60]):
                with self.assertRaises(ValueError):
                    replay._absolute(value)

    def test_reader_identity_includes_unimported_probes_and_model_inputs(self):
        names = {row["path"] for row in replay._reader_sources()}
        self.assertTrue(set(replay.READER_DATA) <= names)
        self.assertIn("ci/project/p05_execute.py", names)
        self.assertIn("ci/project/p05_torch_execute.py", names)
        self.assertIn("ci/project/p04_model_manifest.json", names)

    def test_unrelated_imports_do_not_change_reader_identity(self):
        before = replay._reader_sources()
        with patch.dict(sys.modules, unrelated=types.SimpleNamespace(__file__=str(replay.ROOT / "ci/project/test_unused.py"))):
            self.assertEqual(replay._reader_sources(), before)

    def test_missing_or_redirected_trusted_helper_is_rejected(self):
        for module in (None, types.SimpleNamespace(__file__="/producer/untrusted.py")):
            with self.subTest(module=module):
                with patch.dict(sys.modules, p05_execution_records=module):
                    with self.assertRaisesRegex(ValueError, "helper"):
                        replay._reader_sources()

    def test_changed_input_since_import_fails_before_archive_open(self):
        changed = copy.deepcopy(replay.READER_SOURCES)
        changed[0]["sha256"] = "0" * 64
        with patch.object(replay, "_reader_sources", return_value=changed), patch.object(replay, "_archive_api") as api:
            with self.assertRaisesRegex(ValueError, "since import"):
                replay.replay_archive("/not-opened.zip", "0" * 64, expected_revision=REVISION, expected_format="fp16")
            api.return_value.ArchiveReader.assert_not_called()


class ReportTests(unittest.TestCase):
    def report(self):
        value = {name: None for name in replay.REPORT_FIELDS}
        value.update(schema_version=1, contract_id="p05-installed-torch-execution-v1", backend="simx", format="fp16",
                     state="finished", outcome="pass", reason=None, development=False, source_stable=True,
                     acceptance_claimed=False, phase_complete=False, iterations=2, budget=dict(replay.BUDGET),
                     limitations=list(replay.REPORT_LIMITATIONS), started_at="2026-11-24T00:00:00+00:00",
                     finished_at="2026-11-24T00:00:10+00:00", commands=[])
        for key in ("resources_before", "resources_after"):
            value[key] = {"available_memory_bytes": 4 * 1024**3,
                          "free_disk_bytes": {name: 15 * 1024**3 for name in ("source", "output", "work")}}
        return value

    def validate(self, report):
        view = MemoryView()
        report["installed_request"] = view.document_row("snapshots/installed-request.json", {})
        report["observations"] = view.document_row("artifacts/installed-observations.json", {})
        view.document_row("report.json", report)
        # Isolate report-envelope checks; complete request/source/command
        # semantics are exercised by their own focused verifier tests.
        with patch.object(replay, "_source", return_value={}), patch.object(replay, "_commands", return_value={}), \
                patch.object(replay.torch_records, "validate_request_data"):
            return replay._report(view, API, REVISION, "fp16")

    def test_report_budget_is_exact_and_initial_reserves_are_required(self):
        self.validate(self.report())
        for mutate in (lambda r: r["budget"].update(max_rss_bytes=5 * 1024**3),
                       lambda r: r["budget"].update(extra=1),
                       lambda r: r["resources_before"].update(available_memory_bytes=None),
                       lambda r: r["resources_before"]["free_disk_bytes"].update(work=1),
                       lambda r: r["resources_after"].update(available_memory_bytes=True)):
            with self.subTest(mutate=mutate):
                report = self.report()
                mutate(report)
                with self.assertRaises(ValueError):
                    self.validate(report)

    def test_report_times_outcomes_limits_and_unknown_fields_are_strict(self):
        for key, value in (("started_at", "2026-11-24T00:00:11+00:00"), ("finished_at", "yesterday"),
                           ("schema_version", True), ("acceptance_claimed", True), ("outcome", "fail"),
                           ("limitations", []), ("extra", None), ("commands", [{"duration_seconds": 13}])):
            with self.subTest(key=key):
                report = self.report()
                report[key] = value
                with self.assertRaises(ValueError):
                    self.validate(report)


class OrchestrationTests(unittest.TestCase):
    """Only orchestration is stubbed; these archives do not model GPU evidence."""

    @contextlib.contextmanager
    def driver(self, path, *, native_launches=36):
        counts = {"total_launches": 36}
        python = {"counts": counts}
        framework = {"counts": counts, "operator_calls": 16, "event_profile_pairs": 180}
        totals = {"copied_packet_additional_launches": 0, "distinct_total_launches": 108,
                  "framework_event_profile_pairs": 180, "framework_launches": 36,
                  "framework_operator_calls": 16, "native_comparison_launches": 36, "plain_python_launches": 36}
        report = {"comparison": framework, "execution_counts": totals}
        native = {"python_report": {"comparison": python}, "python_observations": {}, "python_request": {},
                  "native_matmuls": [], "native_models": [], "model_cases": [], "python_raw_log": "",
                  "counts": {"total_launches": native_launches}}
        identities = {"python_identity": None, "torch_identity": None, "adapter_bytes": b"inert", "summary": {}}
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(replay, "_archive_api", return_value=API))
            stack.enter_context(patch.object(replay, "_report", return_value=(report, {}, {}, {"installed-framework-matrix": ""}, {})))
            stack.enter_context(patch.object(replay, "_hosted", return_value={"origin_authenticated_by_replay": False}))
            stack.enter_context(patch.object(replay, "verify_native", return_value=native))
            stack.enter_context(patch.object(replay, "verify_installations", return_value=identities))
            stack.enter_context(patch.object(replay.python_records, "verify_retained_observations", return_value=python))
            stack.enter_context(patch.object(replay.torch_records, "verify_retained_observations", return_value=framework))
            for name in ("_source_and_python", "_packet_members"):
                stack.enter_context(patch.object(replay, name))
            stack.enter_context(patch.object(replay, "_supplementary", return_value={"host_fault_semantics_revalidated": False}))
            yield lambda: replay.replay_archive(path, hashlib.sha256(path.read_bytes()).hexdigest(),
                                               expected_revision=REVISION, expected_format="fp16")

    def archive(self, root):
        path = Path(root) / "original with spaces;$(inert).data"
        with zipfile.ZipFile(path, "w") as output:
            output.writestr("torch/report.json", encoded({"synthetic_scope": SCOPE}))
        return path

    def test_arbitrary_archive_filename_retains_scope_flags_and_all_byte_coverage(self):
        with tempfile.TemporaryDirectory() as root:
            path = self.archive(root)
            with self.driver(path) as run:
                result = run()
            self.assertEqual(result["native_execution"], "not_run")
            for field in ("acceptance_claimed", "phase_acceptance", "retained_code_executed", "host_fault_semantics_revalidated"):
                self.assertIs(result[field], False)
            self.assertEqual(result["counts"]["distinct_total_launches"], 108)
            self.assertEqual([row["path"] for row in result["archive_read"]["read_files"]], ["torch/report.json"])

    def test_symlink_archive_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            path = self.archive(root)
            linked = Path(root) / "linked.zip"
            linked.symlink_to(path)
            with self.driver(linked) as run:
                with self.assertRaisesRegex(ValueError, "canonical"):
                    run()

    def test_counts_are_derived_and_checked_against_frozen_population(self):
        with tempfile.TemporaryDirectory() as root:
            with self.driver(self.archive(root), native_launches=35) as run:
                with self.assertRaisesRegex(ValueError, "population"):
                    run()

    def test_success_is_not_returned_when_archive_close_rehash_fails(self):
        original_close = API.ArchiveReader.close

        def reject_close(reader):
            original_close(reader)
            raise ValueError("synthetic final archive identity failure")

        with tempfile.TemporaryDirectory() as root:
            with self.driver(self.archive(root)) as run, patch.object(API.ArchiveReader, "close", reject_close):
                with self.assertRaisesRegex(ValueError, "final archive identity"):
                    run()

    def test_final_reader_source_change_blocks_success(self):
        changed = copy.deepcopy(replay.READER_SOURCES)
        changed[-1]["sha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as root:
            with self.driver(self.archive(root)) as run, patch.object(replay, "_reader_sources",
                                                                     side_effect=[replay.READER_SOURCES, changed]):
                with self.assertRaisesRegex(ValueError, "during replay"):
                    run()

    def test_cli_failure_never_emits_execution_or_acceptance(self):
        output = io.StringIO()
        with patch.object(replay, "replay_archive", side_effect=ValueError("synthetic invalid archive")), \
                contextlib.redirect_stdout(output):
            status = replay.main(["--archive", "/missing.zip", "--sha256", "0" * 64,
                                  "--expected-revision", REVISION, "--format", "fp16"])
        value = json.loads(output.getvalue())
        self.assertEqual(status, 1)
        self.assertEqual(value["outcome"], "fail")
        self.assertEqual(value["native_execution"], "not_run")
        self.assertIs(value["acceptance_claimed"], False)
        self.assertIs(value["retained_code_executed"], False)
        self.assertIs(value["phase_acceptance"], False)


if __name__ == "__main__":
    unittest.main()
