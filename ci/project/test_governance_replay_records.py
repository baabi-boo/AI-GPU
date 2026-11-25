# SPDX-License-Identifier: Apache-2.0
"""Mutation checks for the inert governance record reconciliation boundary."""

import ast
import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest import mock

import governance_replay_records as records


REVISION = "a" * 40


def _observed(identity):
    return {"requested_path": identity["path"], **{key: identity[key] for key in
            ("resolved_path", "sha256", "size_bytes")}}


def _receipt_bytes(environment):
    return (json.dumps(environment, sort_keys=True, indent=2) + "\n").encode()


def _bind_environment(started, summary, environment):
    raw = _receipt_bytes(environment)
    observed = {"receipt_path": environment["output_dir"] + "/environment.json",
                "receipt_sha256": hashlib.sha256(raw).hexdigest(), "receipt_size_bytes": len(raw),
                "tools": {name: _observed(value) for name, value in environment["tools"].items()},
                "cmake_selection": {key: _observed(environment["cmake_selection"][key])
                                    for key in ("requested", "native")}}
    started["environment_before"] = copy.deepcopy(observed)
    summary["environment_before"] = copy.deepcopy(observed)
    summary["environment_after"] = copy.deepcopy(observed)
    return raw


def records_fixture():
    """Build a self-contained recorded packet without invoking either producer."""
    root, output, run_output = "/recorded/source", "/recorded/evidence/environment", "/recorded/evidence/run"
    interpreter = output + "/venv/bin/python3"
    selected = {"PATH": output + "/venv/bin:/usr/bin:/bin", "HOME": output + "/home",
                "TMPDIR": output + "/tmp", "LANG": "C", "LC_ALL": "C", "TZ": "UTC",
                "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1", "CCACHE_DISABLE": "1",
                "OBJCACHE": "", "MAKEFLAGS": "-j2", "CMAKE_BUILD_PARALLEL_LEVEL": "2", "THREADS": "1"}
    tool_names = ("python", "python3", "cmake", "gcc", "g++", "ar", "ranlib", "make", "git", "tclsh", "readelf")
    tools = {}
    for name in tool_names:
        binary = "python3.12" if name in ("python", "python3") else name
        tools[name] = {"path": (output + "/venv/bin/" if name in ("python", "python3", "cmake") else "/usr/bin/") + name,
                       "resolved_path": "/native/" + binary, "sha256": hashlib.sha256(binary.encode()).hexdigest(),
                       "size_bytes": 100, "version": "Python 3.12.3" if name.startswith("python") else name + " version 1"}
    tools["cmake"]["version"] = "cmake version 3.22.6"
    bootstrap = {"path": "/bootstrap/bin/python3", **{key: tools["python3"][key] for key in
                 ("resolved_path", "sha256", "size_bytes")}}
    cmake = {"path": "/native/cmake", **{key: tools["cmake"][key] for key in
             ("resolved_path", "sha256", "size_bytes")}}
    python = {"executable": interpreter, "base_executable": "/native/python3.12",
              "prefix": output + "/venv", "base_prefix": "/base", "version": "3.12.3 (recorded)",
              "version_info": [3, 12, 3], "implementation": "cpython", "platform": "linux",
              "machine": "x86_64", "byteorder": "little", "libc": ["glibc", "2.39"],
              "gil_enabled": True, "user_site_enabled": False, "pip_present": False}
    producer = ast.parse(Path(__file__).with_name("governance_env.py").read_text())
    probe = next(ast.literal_eval(node.value) for node in producer.body if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id == "PYTHON_PROBE" for target in node.targets))
    source, build = output + "/probe-source", output + "/probe-build"
    commands = [
        ("create-venv", [bootstrap["path"], "-I", "-m", "venv", "--without-pip", output + "/venv"]),
        ("venv-python", [interpreter, "-c", probe]),
        *(("version-" + name, [tools[name]["path"]] + ([] if name == "tclsh" else ["--version"])) for name in tool_names),
        ("c-preprocessor", [tools["gcc"]["path"], "-E", "-dM", "-x", "c", "-DGOVERNANCE_ENV_PROBE=37", "-"]),
        ("elf32-link", [tools["gcc"]["path"], "-shared", "-fPIC", "-m32", "-nostdlib", source + "/value.c", "-o", output + "/probe32.so"]),
        ("elf32-readelf", [tools["readelf"]["path"], "-h", output + "/probe32.so"]),
        ("cmake-configure", [tools["cmake"]["path"], "-S", source, "-B", build, "-G", "Unix Makefiles",
                             "-DCMAKE_C_COMPILER=" + tools["gcc"]["path"], "-DCMAKE_CXX_COMPILER=" + tools["g++"]["path"],
                             "-DCMAKE_AR=" + tools["ar"]["path"], "-DCMAKE_RANLIB=" + tools["ranlib"]["path"],
                             "-DCMAKE_MAKE_PROGRAM=" + tools["make"]["path"]]),
        ("cmake-build", [tools["cmake"]["path"], "--build", build, "--parallel", "2"]),
        ("cxx17-ubsan-run", [build + "/probe"]), ("ubsan-rejection", [build + "/probe", "overflow"]),
    ]
    rows = []
    for name, argv in commands:
        environment = copy.deepcopy(selected)
        if name == "create-venv":
            environment["PATH"] = "/bootstrap/bin:/usr/bin:/bin"
        stdout, stderr, returncode = "", "", 0
        if name.startswith("version-"):
            stdout = tools[name.removeprefix("version-")]["version"] + "\n"
        elif name == "venv-python":
            stdout = json.dumps(python) + "\n"
        elif name == "c-preprocessor":
            stdout = "#define GOVERNANCE_ENV_PROBE 37\n"
        elif name == "elf32-readelf":
            stdout = "  Class: ELF32\n  Data: 2's complement, little endian\n"
        elif name == "cxx17-ubsan-run":
            stdout = "cxx17-ubsan-ok\n"
        elif name == "ubsan-rejection":
            stderr, returncode = "runtime error: signed integer overflow\n", 1
        rows.append({"name": name, "argv": argv, "cwd": output, "environment": environment,
                     "returncode": returncode, "timed_out": False, "stdout": stdout, "stderr": stderr})
    environment = {"schema_version": 1, "status": "ready", "source_root": root, "output_dir": output,
                   "interpreter": interpreter, "started_at": "2026-01-01T00:00:00+00:00",
                   "finished_at": "2026-01-01T00:00:01+00:00", "environment": selected, "tools": tools,
                   "probes": {name: True for name in ("c_preprocessor", "elf32_link", "cmake_build", "cxx17_threads",
                              "ubsan_runtime", "ubsan_rejects_overflow", "fifo", "nofollow")},
                   "commands": rows, "error": None, "bootstrap_python": bootstrap,
                   "cmake_selection": {"requested": copy.deepcopy(cmake), "native": cmake, "resolution": "native"},
                   "python": python}
    source = {"root": root, "head": REVISION, "tree": "b" * 40, "clean": True, "status_porcelain": "",
              "submodules": "-" + "d" * 40 + " third_party/example\n",
              "gitlinks": [{"path": "third_party/example", "oid": "d" * 40, "pinned_oid": "d" * 40, "status": "-"}],
              "tracked_count": 2, "tracked_sha256": "c" * 64, "index_sha256": "c" * 64,
              "worktree_sha256": "c" * 64, "tracked_bytes": 100, "mismatch_count": 0, "mismatches": [],
              "git": _observed(tools["git"])}
    interpreter_record = {"executable": _observed(tools["python3"]), "version": python["version"], "implementation": "CPython",
                          "platform": "linux", "prefix": python["prefix"], "base_prefix": python["base_prefix"],
                          "path": selected["PATH"]}
    started = {"schema_version": 1, "scope": "project-governance-unittest-only", "status": "started",
               "started_at": "2026-01-01T00:00:02+00:00", "governance_passed": False, "execution_completed": False,
               "source_root": root, "discovery": {"start_directory": "ci/project", "pattern": "test_*.py"},
               "command": [interpreter, root + "/ci/project/governance_run.py", "--output-dir", run_output,
                           "--environment-receipt", output + "/environment.json"],
               "source_before": source, "interpreter_before": interpreter_record}
    summary = {**copy.deepcopy(started), "status": "completed", "governance_passed": True, "execution_completed": True,
               "errors": [], "execution": {"strict_success": True, "execution_completed": True},
               "source_after": copy.deepcopy(source), "interpreter_after": copy.deepcopy(interpreter_record),
               "source_stable": True, "interpreter_stable": True, "environment_stable": True,
               "finished_at": "2026-01-01T00:00:03+00:00", "log": {"bytes": 12, "truncated": False}, "event_bytes": 64}
    _bind_environment(started, summary, environment)
    return started, summary, environment


class GovernanceReplayRecordsTests(unittest.TestCase):
    def setUp(self):
        self.started, self.summary, self.environment = records_fixture()

    def validate(self, raw=None):
        return records.validate_records(self.started, self.summary, self.environment, revision=REVISION,
                                        environment_bytes=_receipt_bytes(self.environment) if raw is None else raw)

    def rebind(self):
        return _bind_environment(self.started, self.summary, self.environment)

    def sources(self):
        return [self.started["source_before"], self.summary["source_before"], self.summary["source_after"]]

    def test_complete_record_packet_is_accepted(self):
        result = self.validate()
        self.assertEqual(result["revision"], REVISION)
        self.assertEqual(result["source_tracked_count"], 2)
        self.assertFalse(result["retained_code_executed"])
        self.assertEqual(result["environment_sha256"], hashlib.sha256(_receipt_bytes(self.environment)).hexdigest())

    def test_validation_performs_no_host_path_or_process_access(self):
        raw = _receipt_bytes(self.environment)
        with mock.patch("builtins.open", side_effect=AssertionError("unexpected host read")), \
                mock.patch("pathlib.Path.open", side_effect=AssertionError("unexpected host read")), \
                mock.patch("pathlib.Path.resolve", side_effect=AssertionError("unexpected host resolution")), \
                mock.patch("subprocess.Popen", side_effect=AssertionError("unexpected execution")):
            self.validate(raw)

    def test_input_records_are_not_mutated(self):
        before = copy.deepcopy((self.started, self.summary, self.environment))
        self.validate()
        self.assertEqual(before, (self.started, self.summary, self.environment))

    def test_missing_or_unknown_fields_are_rejected(self):
        for record_name in ("started", "summary", "environment"):
            for change in ("missing", "unknown"):
                with self.subTest(record=record_name, change=change):
                    self.setUp()
                    record = getattr(self, record_name)
                    if change == "missing":
                        del record["schema_version"]
                    else:
                        record["unexpected"] = True
                    self.rebind()
                    with self.assertRaises(ValueError):
                        self.validate()

    def test_start_and_finish_flags_are_exact(self):
        changes = (("started", "status", "completed"), ("started", "governance_passed", True),
                   ("started", "execution_completed", 0), ("summary", "status", "incomplete"),
                   ("summary", "governance_passed", 1), ("summary", "execution_completed", False),
                   ("summary", "source_stable", 1), ("summary", "environment_stable", False))
        for record, key, value in changes:
            with self.subTest(record=record, key=key):
                self.setUp()
                getattr(self, record)[key] = value
                with self.assertRaises(ValueError):
                    self.validate()

    def test_started_summary_and_finish_identities_must_agree(self):
        for key in ("source_before", "source_after", "interpreter_before", "interpreter_after", "environment_before", "environment_after"):
            with self.subTest(key=key):
                self.setUp()
                self.summary[key]["forged"] = "identity"
                with self.assertRaises(ValueError):
                    self.validate()

    def test_source_metadata_rejects_false_clean_claim(self):
        for key, value in (("head", "f" * 40), ("tree", "bad"), ("clean", 1), ("status_porcelain", " M file\0"),
                           ("index_sha256", "f" * 64), ("mismatch_count", 1), ("mismatches", ["file"]),
                           ("tracked_count", True), ("tracked_bytes", False), ("mismatch_count", False)):
            with self.subTest(key=key):
                self.setUp()
                for source in self.sources():
                    source[key] = value
                with self.assertRaises(ValueError):
                    self.validate()

    def test_uninitialized_and_initialized_submodules_are_supported(self):
        self.validate()
        for source in self.sources():
            source["gitlinks"][0]["status"] = " "
            source["submodules"] = " " + "d" * 40 + " third_party/example (heads/main)\n"
            source["submodules"] += "-" + "e" * 40 + " third_party/example/nested\n"
        self.validate()

    def test_gitlink_pin_status_and_path_must_agree(self):
        for change in ("pin", "status", "duplicate", "orphan", "traversal"):
            with self.subTest(change=change):
                self.setUp()
                for source in self.sources():
                    if change == "pin":
                        source["gitlinks"][0]["pinned_oid"] = "e" * 40
                    elif change == "status":
                        source["submodules"] = "+" + source["submodules"][1:]
                    elif change == "duplicate":
                        source["submodules"] += source["submodules"]
                    elif change == "orphan":
                        source["submodules"] += "-" + "e" * 40 + " unrelated/nested\n"
                    else:
                        source["gitlinks"][0]["path"] = "../example"
                with self.assertRaises(ValueError):
                    self.validate()

    def test_recorded_source_git_must_join_prepared_git(self):
        for source in self.sources():
            source["git"]["sha256"] = "e" * 64
        with self.assertRaisesRegex(ValueError, "Git identity"):
            self.validate()

    def test_runner_command_has_exact_source_interpreter_and_receipt_paths(self):
        for index, value in ((0, "/other/python3"), (1, "/other/governance_run.py"),
                             (2, "--output"), (3, "/recorded/source/inside"),
                             (4, "--other-receipt"), (5, "/other/environment.json")):
            with self.subTest(index=index):
                self.setUp()
                self.started["command"][index] = value
                self.summary["command"][index] = value
                with self.assertRaises(ValueError):
                    self.validate()

    def test_raw_environment_hash_and_size_are_bound(self):
        for key, value in (("receipt_sha256", "f" * 64), ("receipt_size_bytes", 1), ("receipt_size_bytes", True)):
            with self.subTest(key=key, value=value):
                self.setUp()
                for receipt in (self.started["environment_before"], self.summary["environment_before"], self.summary["environment_after"]):
                    receipt[key] = value
                with self.assertRaises(ValueError):
                    self.validate()
        self.setUp()
        with self.assertRaises(ValueError):
            self.validate(_receipt_bytes(self.environment) + b" ")

    def test_duplicate_and_nonfinite_raw_json_are_rejected(self):
        for raw in (b'{"schema_version":1,"schema_version":1}', b'{"x":NaN}', b'{"x":Infinity}', b"\xff"):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    self.validate(raw)

    def test_python_and_cmake_required_versions_are_checked(self):
        for kind in ("python", "cmake_old", "cmake_new", "python_bool"):
            with self.subTest(kind=kind):
                self.setUp()
                if kind == "python":
                    self.environment["python"]["version_info"] = [3, 13, 3]
                elif kind == "python_bool":
                    self.environment["python"]["version_info"] = [3, 12, True]
                else:
                    self.environment["tools"]["cmake"]["version"] = "cmake version " + ("3.20.6" if kind == "cmake_old" else "3.26.0")
                self.rebind()
                with self.assertRaises(ValueError):
                    self.validate()

    def test_probe_flags_are_required_true_booleans(self):
        for field in self.environment["probes"]:
            for value in (False, 1):
                with self.subTest(field=field, value=value):
                    self.setUp()
                    self.environment["probes"][field] = value
                    self.rebind()
                    with self.assertRaises(ValueError):
                        self.validate()

    def test_python_platform_and_isolation_are_checked(self):
        for key, value in (("implementation", "pypy"), ("platform", "win32"), ("machine", "aarch64"),
                           ("byteorder", "big"), ("libc", ["musl", "1"]), ("gil_enabled", 1),
                           ("user_site_enabled", True), ("pip_present", True)):
            with self.subTest(key=key):
                self.setUp()
                self.environment["python"][key] = value
                self.rebind()
                with self.assertRaises(ValueError):
                    self.validate()

    def test_prepared_environment_and_tool_paths_are_checked(self):
        for change in ("path", "override", "tool", "tool_size", "alias", "cmake"):
            with self.subTest(change=change):
                self.setUp()
                if change == "path":
                    self.environment["environment"]["PATH"] += ":/untrusted"
                elif change == "override":
                    self.environment["environment"]["PYTHONPATH"] = "/untrusted"
                elif change == "tool":
                    self.environment["tools"]["gcc"]["path"] = "/untrusted/gcc"
                elif change == "tool_size":
                    self.environment["tools"]["gcc"]["size_bytes"] = True
                elif change == "alias":
                    self.environment["tools"]["python"]["sha256"] = "e" * 64
                else:
                    self.environment["cmake_selection"]["native"]["sha256"] = "e" * 64
                self.rebind()
                with self.assertRaises(ValueError):
                    self.validate()

    def test_python_package_cmake_selection_is_supported(self):
        selection = self.environment["cmake_selection"]
        selection.update(resolution="python-package", package_version="3.22.6")
        selection["requested"] = {"path": "/bootstrap/bin/cmake", "resolved_path": "/bootstrap/bin/cmake",
                                  "sha256": "e" * 64, "size_bytes": 100}
        self.rebind()
        self.validate()

    def test_tool_version_must_match_observed_command_output(self):
        self.environment["tools"]["gcc"]["version"] = "invented compiler"
        self.rebind()
        with self.assertRaisesRegex(ValueError, "version disagrees"):
            self.validate()

    def test_shared_resolved_paths_cannot_claim_different_bytes(self):
        self.environment["bootstrap_python"]["sha256"] = "e" * 64
        self.rebind()
        with self.assertRaisesRegex(ValueError, "shared resolved"):
            self.validate()

    def test_shared_requested_paths_cannot_claim_different_files(self):
        self.environment["cmake_selection"]["requested"]["path"] = self.environment["tools"]["gcc"]["path"]
        self.rebind()
        with self.assertRaisesRegex(ValueError, "shared requested"):
            self.validate()

    def test_all_preparation_commands_are_required_and_ordered(self):
        for change in ("missing", "duplicate", "reordered"):
            with self.subTest(change=change):
                self.setUp()
                commands = self.environment["commands"]
                if change == "missing":
                    commands.pop()
                elif change == "duplicate":
                    commands[-1] = copy.deepcopy(commands[0])
                else:
                    commands[0], commands[1] = commands[1], commands[0]
                self.rebind()
                with self.assertRaises(ValueError):
                    self.validate()

    def test_preparation_argv_cwd_environment_and_result_are_bound(self):
        for change in ("argv", "cwd", "environment", "returncode", "bool_returncode", "timeout"):
            with self.subTest(change=change):
                self.setUp()
                row = self.environment["commands"][2]
                if change == "argv":
                    row["argv"].append("--extra")
                elif change == "cwd":
                    row["cwd"] = "/elsewhere"
                elif change == "environment":
                    row["environment"]["LD_PRELOAD"] = "/elsewhere.so"
                elif change == "returncode":
                    row["returncode"] = 1
                elif change == "bool_returncode":
                    row["returncode"] = False
                else:
                    row["timed_out"] = True
                self.rebind()
                with self.assertRaises(ValueError):
                    self.validate()

    def test_preparation_diagnostics_are_checked_beyond_ready_flag(self):
        for name in ("venv-python", "c-preprocessor", "elf32-readelf", "cxx17-ubsan-run", "ubsan-rejection"):
            with self.subTest(name=name):
                self.setUp()
                row = next(row for row in self.environment["commands"] if row["name"] == name)
                row["stdout"] = row["stderr"] = ""
                self.rebind()
                with self.assertRaises(ValueError):
                    self.validate()

    def test_ubsan_control_must_fail_without_timeout(self):
        self.environment["commands"][-1]["returncode"] = 0
        self.rebind()
        with self.assertRaises(ValueError):
            self.validate()

    def test_log_and_event_integer_bounds_and_truncation(self):
        for key, value in (("bytes", True), ("bytes", -1), ("bytes", records.MAX_LOG_BYTES + 1), ("truncated", True), ("truncated", 0)):
            with self.subTest(key=key, value=value):
                self.setUp()
                self.summary["log"][key] = value
                with self.assertRaises(ValueError):
                    self.validate()
        for value in (False, -1, 0, records.MAX_RECORD_BYTES + 1):
            with self.subTest(event_bytes=value):
                self.setUp()
                self.summary["event_bytes"] = value
                with self.assertRaises(ValueError):
                    self.validate()

    def test_timestamp_order_and_syntax(self):
        for value in ("2025-12-31T00:00:00+00:00", "2026-01-01", "2026-02-31T00:00:00+00:00"):
            with self.subTest(value=value):
                self.summary["finished_at"] = value
                with self.assertRaises(ValueError):
                    self.validate()


if __name__ == "__main__":
    unittest.main()
