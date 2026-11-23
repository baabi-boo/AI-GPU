# SPDX-License-Identifier: Apache-2.0
"""Synthetic control originals and one tiny real-host recorder join.

The complete ZIP fixture invents dependency metadata and native observations.
Only its independent dependency semantic boundary is stubbed; all native and
control replay semantics run. The tiny host test compiles two small libraries,
not Ramulator or the simulator, and establishes no native GPU execution.
"""

from copy import deepcopy
import json
from pathlib import Path, PurePosixPath
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import zipfile

import p06_dependency_control_replay as replay
from test_p06_dependency_binary import map_text
from test_p06_dependency_native_replay import (SyntheticNativePacket, MemoryView, descriptor, digest,
                                              inert_path_guards, json_bytes)
import test_p06_dependency_substitution as substitution_tests
from test_p06_pending_probe import output_lines, render
import p06_native_lifetime_test_fixture as lifetime_fixture


class SyntheticNativeWithControlTools(SyntheticNativePacket):
    def make_dependencies(self):
        super().make_dependencies()
        # This source is deliberately invented, just like the enclosing
        # dependency metadata; it is not an execution of pinned GDDR6.
        self.control_original = b"// synthetic GDDR6 source for inert reader tests\nint synthetic_gddr6;\n"
        ramulator = next(row for row in self.dependency_document["source_manifest"]["sources"]
                         if row["name"] == "ramulator")
        ramulator["files"].append(descriptor("src/dram/impl/GDDR6.cpp", self.control_original))
        ramulator["files"].sort(key=lambda row: row["path"])
        self.dependency_document["tools"] = deepcopy(self.tools)
        # The historical native grammar fixture has no ranlib selection. This
        # invented tool belongs solely to the explicitly synthetic dependency.
        self.dependency_document["tools"]["ranlib"] = {
            "path": "/synthetic-tools/ranlib", "resolved_path": "/synthetic-tools/ranlib",
            "sha256": "a" * 64, "size_bytes": 1}
        self.dependency_body = json_bytes(self.dependency_document)
        self.receipt_pin = digest(self.dependency_body)
        self.admission, self.stability = replay.native_replay._admission_values(
            self.dependency_document, self.dependency_verification, self.receipt_pin)


class SyntheticControls:
    def __init__(self, original, native):
        self.original, self.native = original, native
        self.probe_files, self.substitution_files = {}, {}
        self.variant = native.report["variants"][0]
        self.source = native.paths["source"]
        self.build = PurePosixPath(self.variant["build_dir"])
        self.probe_output = native.paths["output"].parent / "pending-probe"
        self.substitution_output = native.paths["output"].parent / "dependency-substitution"
        self.work = self.substitution_output / "work"
        self.native_pin = digest(original.files["report.json"])
        self.make_probe()
        self.make_substitution()

    def put(self, files, name, body):
        files[name] = body
        return descriptor(name, body)

    def put_json(self, files, name, value):
        return self.put(files, name, json_bytes(value))

    def sources(self, files, names):
        rows = {}
        for name in sorted(names):
            body = self.original.files.get("artifacts/source/" + name)
            if body is None:
                body = (replay.ROOT / name).read_bytes()
            self.put(files, "inputs/" + name, body)
            rows[name] = descriptor(name, body)
        return rows

    def base(self, contract_id):
        return {"schema_version": 1, "contract_id": contract_id, "state": "finished", "outcome": "pass",
            "reason": None, "failures": [], "native_execution": "run",
            "expected_revision": self.native.revision, "dependency_receipt_sha256": self.native.dependency_receipt_sha256,
            "started_at": self.native.report["finished_at"], "finished_at": self.native.report["finished_at"],
            **dict.fromkeys(replay.contract.FALSE_CLAIMS, False)}

    def command(self, files, name, argv, cwd, text, *, timeout=None, environment=None, native=False, negative=False):
        raw = text.encode()
        self.put(files, "logs/" + name + ".log", raw)
        row = {"id": name, "argv": list(map(str, argv)), "cwd": str(cwd), "log": "logs/" + name + ".log",
            "process_started": True, "outcome": "fail" if negative else "pass", "exit_code": 1 if negative else 0,
            "reason": "nonzero_exit" if negative else None, "duration_seconds": 1.0, "peak_rss_bytes": 4096,
            "cleanup_complete": True, "limitations": list(replay.PROCESS_LIMITATIONS),
            "log_sha256": digest(raw), "log_size_bytes": len(raw)}
        if environment is not None:
            row.update(environment=environment, timeout_seconds=timeout, native_process=native)
        return row

    def native_report_identity(self):
        path = str(self.native.paths["output"] / "report.json")
        return dict(descriptor(path, self.original.files["report.json"]), resolved_path=path)

    def make_probe(self):
        n, v, files = self.native, self.variant, self.probe_files
        compiler, runtime = n.tools["g++"]["path"], self.build / "sw/runtime"
        helpers = self.sources(files, set(replay.PROBE_HELPERS) | set(replay.probe.SOURCE_FILES))
        sources = dict(n.sources, **helpers)
        initial = {"checkout": n.source["checkout"], "sources": [sources[name] for name in sorted(sources)],
            "build": v["artifacts_before"], "dependencies": n.dependencies, "compiler": n.tools["g++"],
            "managed_report": self.native_report_identity(), "managed_snapshots": [n.report["source_before"],
                n.report["tools_before"], n.report["dependencies_before"], v["binding"]]}
        stage = next(row for row in v["retained_builds"] if row["stage"] == "frozen")
        prefix = "artifacts/" + v["id"] + "/frozen/"
        stamps = {row["path"][len(prefix):]: self.original.files[row["path"]].decode() for row in stage["files"]}
        flags, records = replay.probe.probe_flags(stamps["sw/runtime/simx_rt_config.stamp"],
            stamps["sw/runtime/simx_config.stamp"], stamps[replay.native_replay.APP + "/config.stamp"],
            source=Path(self.source), build=Path(self.build), fmt="fp16")
        libraries = {name: v["expected_loaded_libraries"][name] for name in replay.probe.LIBRARIES}
        paths = [str(PurePosixPath(n.tools["executing_python"]["path"]).parent), "/usr/bin", "/bin"]
        environment = {"PATH": ":".join(dict.fromkeys(paths)), "LANG": "C", "LC_ALL": "C", "TZ": "UTC",
            "TMPDIR": str(self.probe_output / "tmp"), "THREADS": "1", "CCACHE_DISABLE": "1", "OBJCACHE": "",
            "PYTHONDONTWRITEBYTECODE": "1", "PERF": "1", "LD_LIBRARY_PATH": ":".join((str(runtime),
                str(self.source / "third_party/ramulator"), str(self.source / "third_party/ramulator_ext")))}
        limitations = list(replay.probe.LIMITATIONS)
        limitations[2] = ("The selected model and dependencies match the completed managed build "
            "and its caller-pinned fresh dependency receipt; this probe does not replay compilation.")
        self.probe_report = {**self.base(replay.probe.CONTRACT_ID), "native_probe_passed": True,
            "zero_mutation_rejected": True, "budget": dict(replay.probe.BUDGET), "limitations": limitations,
            "managed_contract_id": replay.contract.MANAGED_CONTRACT_ID, "inputs_before": initial, "inputs_after": deepcopy(initial),
            "format": "fp16", "compiler_records": records, "probe_flags": flags, "expected_libraries": libraries,
            "environment": environment, "managed_build_binding_sha256": v["build_binding_sha256"], "products": [],
            "commands": [self.command(files, "compiler-version", [compiler, "--version"], self.probe_output,
                                      "synthetic compiler version observation\n")]}
        for mode, defines in (("native", []), ("always-zero", ["-DP06_PENDING_FORCE_ZERO=1"])):
            relative = "products/pending-reads-" + mode
            path = str(self.probe_output / relative)
            row = self.put(files, relative, b"synthetic non-executable probe " + mode.encode())
            self.probe_report["commands"].append(self.command(files, "compile-" + mode,
                [compiler, *flags, *defines, self.source / replay.probe.PROBE_SOURCE, "-L" + str(runtime),
                 "-Wl,-rpath," + str(runtime), "-lsimx", "-pthread", "-ldl", "-o", path],
                self.probe_output, "synthetic compiler observation\n"))
            zero = mode == "always-zero"
            raw = render(output_lines(libraries, zero=zero))
            self.probe_report["commands"].append(self.command(files, "run-" + mode, [path], self.probe_output,
                                                              raw, negative=zero))
            observed = replay.probe.verify_output(raw, libraries, zero_control=zero)
            self.probe_report["products"].append(dict(row, path=path, resolved_path=path, mode=mode, observation=observed))
        self.put(files, replay.RUNTIME_DIAGNOSTIC_NAME,
                 b"synthetic opaque Ramulator destructor diagnostic\nidle_latency: .nan\n")
        self.finish_probe()

    def finish_probe(self):
        self.probe_pin = self.put_json(self.probe_files, "report.json", self.probe_report)["sha256"]

    def payload(self, path, body):
        pin = digest(body)
        self.put(self.substitution_files, "payloads/" + pin + ".bin", body)
        return {"path": str(path), "resolved_path": str(path), "sha256": pin,
                "size_bytes": len(body), "payload": pin + ".bin"}

    def tool_record(self, role, config, arguments, inputs, output, *, dep=None, prepass=None, mapping=None):
        start = 10 if role == "compile" else 100
        actual = ([*arguments, "-MD", "-MF", dep["path"], "-MT", output["path"]]
                  if role == "compile" else arguments)
        tool = config["tools"]["g++"]
        children = []
        if role == "compile":
            children.append({"stage": "dependencies", "argv": [tool["path"],
                *replay.recorder._prepass(arguments, prepass["path"], output["path"])],
                "started_ns": start + 1, "finished_ns": start + 2, "pid": 101,
                "process_group": 100, "process_started": True, "exit_code": 0})
        children.append({"stage": "tool", "argv": [tool["path"], *actual],
            "started_ns": start + 3, "finished_ns": start + 4, "pid": 102,
            "process_group": 100, "process_started": True, "exit_code": 0})
        path = str(self.source / "ci/project/p06_dependency_record.py")
        return {"schema_version": 1, "contract_id": replay.recorder.CONTRACT_ID,
            "id": replay.contract.digest({"role": role, "output": output["path"]}),
            "config_sha256": self.substitution_report["tool_config"]["sha256"],
            "recorder": dict(self.native.sources["ci/project/p06_dependency_record.py"], path=path, resolved_path=path),
            "tool_name": "g++", "tool": tool, "role": role, "cwd": str(self.work),
            "requested_arguments": arguments, "arguments": actual, "output_path": output["path"],
            "output_before": None, "output_absent_before": True, "output": output,
            "inputs_before": inputs, "inputs_after": deepcopy(inputs), "dependency_file": dep,
            "dependency_prepass_file": prepass, "link_map": mapping, "children": children,
            "started_ns": start, "finished_ns": start + 5, "state": "finished", "outcome": "pass",
            "reason": None, "failures": [], "process_started": True, "exit_code": 0,
            "environment": {"PATH": self.environment["PATH"], "CCACHE_DISABLE": "1", "OBJCACHE": "",
                            **dict.fromkeys(replay.recorder.INJECTION_ENVIRONMENT)}}

    def make_substitution(self):
        n, v, files = self.native, self.variant, self.substitution_files
        helpers = self.sources(files, set(replay.SUBSTITUTION_HELPERS))
        sources = dict(n.sources, **helpers)
        initial = {"checkout": n.source["checkout"], "source_files": [sources[name] for name in sorted(sources)],
            "build": v["artifacts_before"], "managed_report": self.native_report_identity(),
            "managed_snapshots": [n.report["source_before"], n.report["tools_before"], v["binding"]],
            "dependency_admission": n.admission_stability}
        self.put(files, "inputs/managed-report.json", self.original.files["report.json"])
        self.put(files, "inputs/dependency-report.json", n.dependency_body)
        paths = [str(PurePosixPath(n.tools["executing_python"]["path"]).parent), "/usr/bin", "/bin"]
        self.environment = {"PATH": ":".join(dict.fromkeys(paths)), "HOME": str(self.work / "home"),
            "TMPDIR": str(self.work / "tmp"), "LANG": "C", "LC_ALL": "C", "TZ": "UTC", "PYTHONUTF8": "1",
            "PYTHONDONTWRITEBYTECODE": "1", "CCACHE_DISABLE": "1", "OBJCACHE": "", "MAKEFLAGS": "-j2",
            "CMAKE_BUILD_PARALLEL_LEVEL": "2", "THREADS": "1"}
        tools = n.dependency_document["tools"]
        config = {"schema_version": 1, "contract_id": replay.recorder.CONTRACT_ID,
            "contract_sha256": replay.contract.contract_hash(), "roots": {"sources": str(self.source / "third_party"),
                "build": str(self.work), "receipts": str(self.substitution_output / "records"),
                "payloads": str(self.substitution_output / "payloads")},
            "tools": {name: tools[name] for name in replay.recorder.TOOLS}}
        self.substitution_report = {**self.base(replay.substitution.CONTRACT_ID), "control_passed": True,
            "alternate_dependency_built": True, "numerical_control_passed": True, "original_provenance_rejected": True,
            "budget": dict(replay.contract.BUDGET), "environment": self.environment, "managed_population_included": False,
            "limitations": list(replay.substitution.LIMITATIONS), "inputs_before": initial, "inputs_after": deepcopy(initial),
            "original_libraries": v["expected_loaded_libraries"], "managed_build_binding_sha256": v["build_binding_sha256"],
            "helper_sources": [helpers[name] for name in replay.SUBSTITUTION_HELPERS],
            "tool_config": self.put_json(files, "tool-config.json", config)}
        original_name = replay.substitution.ORIGINAL_SOURCE
        original = self.original.control_original
        original_path = str(self.source / original_name)
        derived = replay.substitution.derived_source(original)
        self.put(files, "inputs/gddr6-original.cpp", original)
        self.put(files, "work/" + replay.substitution.CONTROL_SOURCE, derived)
        derived_input = self.payload(self.work / replay.substitution.CONTROL_SOURCE, derived)
        header_name = next(name for name in n.sources if name.startswith("third_party/ramulator/src/") and name.endswith(".h"))
        header = self.payload(self.source / header_name, self.original.files["artifacts/source/" + header_name])
        object_row = self.payload(self.work / "gddr6-control.o", b"synthetic non-executable object")
        dep_body = (object_row["path"] + ": " + derived_input["path"] + " " + header["path"] + "\n").encode()
        dep = self.payload(self.work / "gddr6-control.o.d", dep_body)
        before = self.payload(self.work / "gddr6-control.o.p06-before.d", dep_body)
        arguments = replay.substitution.recipes(self.source, self.work)
        compiled = self.tool_record("compile", config, arguments["compile"], [derived_input, header], object_row,
                                    dep=dep, prepass=before)
        products = n.dependency_document["products"]
        ramulator = self.payload(products["ramulator"]["staged_path"],
            self.original.files["artifacts/dependencies/" + replay.contract.PRODUCTS["ramulator"]])
        map_body = map_text([], [products["ramulator"]["staged_path"], object_row["path"]]).encode()
        mapping = self.payload(self.work / "control.map", map_body)
        alternate = self.payload(self.work / replay.substitution.LIBRARY,
                                  b"synthetic non-executable extension " + replay.substitution.MARKER)
        linked = self.tool_record("link", config, arguments["link"], [object_row, ramulator], alternate, mapping=mapping)
        for row in (object_row, dep, before, mapping, alternate):
            name = PurePosixPath(row["path"]).relative_to(self.work).as_posix()
            self.put(files, "work/" + name, files["payloads/" + row["payload"]])
        records = [self.put_json(files, "records/" + row["id"] + ".json", row) for row in (compiled, linked)]
        self.put(files, "records/.records.lock", b"")
        self.put(files, "payloads/.retention.lock", b"")
        derivation = {"original_source": descriptor(original_path, original),
            "retained_original": descriptor("inputs/gddr6-original.cpp", original),
            "derived_source": descriptor("work/" + replay.substitution.CONTROL_SOURCE, derived),
            "appended_declaration_sha256": digest(replay.substitution.MARKER_DECLARATION)}
        checked = {"records": sorted(records, key=lambda row: row["path"]), "compile": compiled, "link": linked,
            "map_verification": replay.substitution.binary.validate_link_map(map_body.decode(), cwd=str(self.work),
                archives={}, required_loads=[products["ramulator"]["staged_path"], object_row["path"]]),
            "alternate_product": {key: alternate[key] for key in replay.receipts.IDENTITY_FIELDS},
            "source_derivation": derivation, "original_product": products["extension"]}
        frozen = [descriptor(name, body) for name, body in sorted(files.items())]
        binding = {"contract_id": replay.substitution.CONTRACT_ID, "expected_revision": n.revision,
            "dependency_receipt_sha256": n.dependency_receipt_sha256,
            "managed_build_binding_sha256": v["build_binding_sha256"], "inputs_sha256": replay.contract.digest(initial),
            "source_derivation_sha256": replay.contract.digest(derivation), "alternate_product": checked["alternate_product"],
            "original_product": checked["original_product"], "format": "fp16", "policy": replay.substitution.POLICY,
            "managed_population_included": False, **dict.fromkeys(replay.contract.FALSE_CLAIMS, False)}
        binding_id = replay.contract.digest(binding)
        self.substitution_report.update(source_derivation=derivation, dependency_control=checked,
            control_products_before=frozen, control_products_after=deepcopy(frozen),
            control_binding=binding, control_binding_sha256=binding_id, commands=[])
        for role in ("compile", "link"):
            argv = [tools["python3"]["path"], str(self.source / "ci/project/p06_dependency_record.py"),
                "--config", str(self.substitution_output / "tool-config.json"), "--config-sha256",
                self.substitution_report["tool_config"]["sha256"], "--tool", "g++", "--role", role, "--", *arguments[role]]
            self.substitution_report["commands"].append(self.command(files, role + "-alternate-extension", argv,
                self.work, "synthetic tool receipt observation\n", timeout=1800, environment=self.environment))
        self.make_substitution_log()
        # Native finalization emits this after the compilation products freeze.
        self.put(files, "work/" + replay.RUNTIME_DIAGNOSTIC_NAME,
                 b"synthetic opaque Ramulator destructor diagnostic\nidle_latency: .nan\n")
        self.finish_substitution()

    def make_substitution_log(self, change=None):
        report = self.substitution_report
        binding_id = report["control_binding_sha256"]
        raw = lifetime_fixture.raw_records("fp16", replay.substitution.POLICY, binding_id=binding_id)
        libraries = dict(self.variant["expected_loaded_libraries"],
                         **{replay.substitution.LIBRARY: str(self.work / replay.substitution.LIBRARY)})
        raw[3]["loaded_libraries"] = [{"name": name, "path": path} for name, path in sorted(libraries.items())]
        if change:
            change(raw)
        text = lifetime_fixture.render_log(*raw[1:])
        identity = replay.substitution.manifest.process_identity("fp16", replay.substitution.POLICY, binding_id)
        app = self.build / replay.native_replay.APP
        argv = [app / "ai_counter_preflight", replay.substitution.lifetime.APP_FLAG, "--policy", replay.substitution.POLICY,
            "--module", app / "kernel.vxbin", "--qualification-id", binding_id, "--sample-id", identity["sample_id"],
            "--pair-index", "0", "--phase", "warmup"]
        row = self.command(self.substitution_files, "run-alternate-extension", argv, self.work, text,
            timeout=180, native=True, environment=dict(self.environment, VORTEX_DRIVER="simx", PERF="1",
                LD_LIBRARY_PATH=str(self.work) + ":" + str(self.build / "sw/runtime")))
        report["commands"] = report["commands"][:2] + [row]
        if change is None:
            report.update(replay.substitution.verify_observation(text, contract=self.native.contract, case=raw[0],
                binding_id=binding_id, original_libraries=self.variant["expected_loaded_libraries"],
                alternate_path=str(self.work / replay.substitution.LIBRARY)))

    def finish_substitution(self):
        self.substitution_report["retained_files"] = [descriptor(name, body)
            for name, body in sorted(self.substitution_files.items()) if name != "report.json"]
        self.substitution_pin = self.put_json(self.substitution_files, "report.json", self.substitution_report)["sha256"]

    def replace_substitution_record(self, role, record):
        files, report = self.substitution_files, self.substitution_report
        self.put_json(files, "records/" + record["id"] + ".json", record)
        report["dependency_control"][role] = record
        report["dependency_control"]["records"] = [descriptor(row["path"], files[row["path"]])
            for row in report["dependency_control"]["records"]]
        frozen = [descriptor(name, body) for name, body in sorted(files.items())
                  if name not in ("report.json", "work/" + replay.RUNTIME_DIAGNOSTIC_NAME)
                  and not name.startswith("logs/")]
        report["control_products_before"] = frozen
        report["control_products_after"] = deepcopy(frozen)

    def probe_check(self):
        self.finish_probe()
        return replay.verify_probe_view(MemoryView(self.probe_files, self.native.api), native=self.native,
            expected_report_sha256=self.probe_pin, expected_native_report_sha256=self.native_pin)

    def substitution_check(self):
        self.finish_substitution()
        return replay.verify_substitution_view(MemoryView(self.substitution_files, self.native.api), native=self.native,
            expected_report_sha256=self.substitution_pin, expected_native_report_sha256=self.native_pin)


class SeparateControlReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = SyntheticNativeWithControlTools()
        cls.native = cls.original.reader()
        cls.native_result = cls.native.run()

    def setUp(self):
        self.packet = SyntheticControls(self.original, self.native)

    def test_complete_synthetic_controls_keep_all_three_populations_separate(self):
        pending = self.packet.probe_check()
        alternate = self.packet.substitution_check()
        self.assertEqual((pending["processes"], pending["contexts"], pending["commands_checked"]), (2, 2, 5))
        self.assertEqual(pending["always_zero_rejection"], replay.probe.ZERO_FAILURE)
        self.assertTrue(all(row["positive_samples"] > 0 for row in pending["positive_pending_contexts"]))
        self.assertEqual((alternate["control_counts"]["processes"], alternate["control_counts"]["launches"],
                          alternate["control_counts"]["checked_words"]), (1, 33, 1056))
        self.assertEqual(alternate["rejection"], replay.substitution.REJECTION)
        self.assertEqual(self.native_result["counts"]["launches"], 132)
        for result in (pending, alternate):
            self.assertIs(result["managed_population_included"], False)
            self.assertEqual(result["native_execution"], "not_run")
            self.assertIs(result["retained_code_executed"], False)
            self.assertTrue(all(result[name] is False for name in replay.contract.FALSE_CLAIMS))

    def test_report_failure_claim_and_final_stability_mutations_fail(self):
        for which in ("probe", "substitution"):
            for change in (lambda row: row.update(outcome="fail"), lambda row: row.update(reason="earlier failure"),
                           lambda row: row.update(qualified=True), lambda row: row.update(native_execution="unknown"),
                           lambda row: row.update(failures=["first failure"]),
                           lambda row: row["inputs_after"]["checkout"].update(revision="b" * 40)):
                with self.subTest(which=which, change=change):
                    self.packet = SyntheticControls(self.original, self.native)
                    change(getattr(self.packet, which + "_report"))
                    with self.assertRaises(ValueError):
                        getattr(self.packet, which + "_check")()

    def test_pending_actual_raw_context_and_exact_zero_assertion_are_required(self):
        for mode, old, new in (("native", '"positive_samples": 5', '"positive_samples": 0'),
                              ("always-zero", replay.probe.ZERO_FAILURE, "FAILED pending_reads native_probe: timeout")):
            with self.subTest(mode=mode):
                self.packet = SyntheticControls(self.original, self.native)
                name = "logs/run-" + mode + ".log"
                body = self.packet.probe_files[name].replace(old.encode(), new.encode())
                self.assertNotEqual(body, self.packet.probe_files[name])
                self.packet.probe_files[name] = body
                row = next(row for row in self.packet.probe_report["commands"] if row["log"] == name)
                row.update(log_sha256=digest(body), log_size_bytes=len(body))
                with self.assertRaises(ValueError):
                    self.packet.probe_check()

    def test_pending_compiler_recipe_tool_model_binary_and_command_inventory_mutations_fail(self):
        changes = (lambda p: p.probe_report["commands"][3]["argv"].remove("-DP06_PENDING_FORCE_ZERO=1"),
                   lambda p: p.probe_report["commands"][1]["argv"].__setitem__(0, "/foreign/g++"),
                   lambda p: p.probe_report["commands"][4].update(exit_code=0),
                   lambda p: p.probe_report["commands"][2].update(peak_rss_bytes=5 * 1024**3),
                   lambda p: p.probe_report["commands"].pop(),
                   lambda p: p.probe_report["inputs_before"]["build"][0].update(sha256="0" * 64),
                   lambda p: p.probe_files.__setitem__("products/pending-reads-native", b"replaced"))
        for change in changes:
            with self.subTest(change=change):
                self.packet = SyntheticControls(self.original, self.native)
                # Input rows in the fixture are copied before adversarial editing.
                self.packet.probe_report = deepcopy(self.packet.probe_report)
                change(self.packet)
                with self.assertRaises(ValueError):
                    self.packet.probe_check()

    def test_substitution_raw_numeric_lifetime_and_actual_loader_mutations_fail(self):
        for change in (lambda raw: raw[4]["runs"].pop(),
                       lambda raw: raw[4]["runs"][1]["after"].update(pending_reads=1),
                       lambda raw: raw[3]["loaded_libraries"][0].update(path="/foreign/library.so"),
                       lambda raw: raw[1][0].update(checked=31)):
            with self.subTest(change=change):
                self.packet = SyntheticControls(self.original, self.native)
                self.packet.make_substitution_log(change)
                with self.assertRaises(ValueError):
                    self.packet.substitution_check()

    def test_substitution_control_cannot_relabel_binding_population_or_rejection(self):
        for change in (lambda row: row.update(managed_population_included=True),
                       lambda row: row["control_counts"].update(launches=132),
                       lambda row: row.update(rejection="some unrelated failure"),
                       lambda row: row["control_binding"].update(format="bf16"),
                       lambda row: row["commands"][-1]["environment"].update(LD_LIBRARY_PATH="/foreign"),
                       lambda row: row["commands"][0].update(timeout_seconds=1801)):
            with self.subTest(change=change):
                self.packet = SyntheticControls(self.original, self.native)
                self.packet.substitution_report = deepcopy(self.packet.substitution_report)
                change(self.packet.substitution_report)
                with self.assertRaises(ValueError):
                    self.packet.substitution_check()

    def test_substitution_exact_source_derivation_and_admitted_header_are_rechecked(self):
        for field in ("derived", "header", "object", "children", "order"):
            with self.subTest(field=field):
                self.packet = SyntheticControls(self.original, self.native)
                files = self.packet.substitution_files
                name = self.packet.substitution_report["dependency_control"]["compile"]["id"]
                path = "records/" + name + ".json"
                record = json.loads(files[path])
                if field in ("derived", "header"):
                    index = 0 if field == "derived" else 1
                    row = record["inputs_before"][index]
                    replacement = self.packet.payload(row["path"], b"unexpected input bytes\n")
                    record["inputs_before"][index] = replacement
                    record["inputs_after"][index] = deepcopy(replacement)
                    if field == "derived":
                        files["work/" + replay.substitution.CONTROL_SOURCE] = b"unexpected input bytes\n"
                elif field == "object":
                    record["output"] = self.packet.payload(record["output_path"], b"different fresh object")
                    files["work/gddr6-control.o"] = b"different fresh object"
                elif field == "children":
                    record["children"][0]["process_started"] = False
                else:
                    record["finished_ns"] = 1000
                self.packet.put_json(files, path, record)
                with self.assertRaises(ValueError):
                    self.packet.substitution_check()

    def test_substitution_map_rejects_rehashed_unplanned_source_or_work_libraries(self):
        for root in (self.packet.source, self.packet.work):
            with self.subTest(root=root):
                self.packet = SyntheticControls(self.original, self.native)
                report, files = self.packet.substitution_report, self.packet.substitution_files
                linked = deepcopy(report["dependency_control"]["link"])
                body = files["work/control.map"] + ("LOAD " + str(root / "extra.so") + "\n").encode()
                linked["link_map"] = self.packet.payload(linked["link_map"]["path"], body)
                files["work/control.map"] = body
                self.packet.put_json(files, "records/" + linked["id"] + ".json", linked)
                with self.assertRaisesRegex(ValueError, "unplanned source/work input"):
                    self.packet.substitution_check()

    def test_substitution_map_rejects_rebound_inputs_from_admitted_native_builds(self):
        self.assertEqual(self.packet.substitution_check()["outcome"], "pass")
        for relative in ("simx-fp16/unplanned.o", "simx-bf16/unplanned.so"):
            with self.subTest(relative=relative):
                self.packet = SyntheticControls(self.original, self.native)
                report, files = self.packet.substitution_report, self.packet.substitution_files
                linked = deepcopy(report["dependency_control"]["link"])
                previous = "payloads/" + linked["link_map"]["payload"]
                extra = self.native.paths["work"] / relative
                body = files["work/control.map"] + ("LOAD " + str(extra) + "\n").encode()
                linked["link_map"] = self.packet.payload(linked["link_map"]["path"], body)
                files["work/control.map"] = body
                del files[previous]
                report["dependency_control"]["map_verification"] = replay.substitution.binary.validate_link_map(
                    body.decode(), cwd=str(self.packet.work), archives={}, required_loads=[
                        self.native.dependency_document["products"]["ramulator"]["staged_path"],
                        report["dependency_control"]["compile"]["output_path"]])
                self.packet.replace_substitution_record("link", linked)
                with self.assertRaisesRegex(ValueError, "unplanned source/work input"):
                    self.packet.substitution_check()

    def test_substitution_header_closure_cannot_add_unreviewed_project_inputs(self):
        self.assertEqual(self.packet.substitution_check()["outcome"], "pass")
        for label, path, resolved in (
                ("source", self.packet.source / "unplanned.h", None),
                ("native-build", self.native.paths["work"] / "simx-bf16/unplanned.h", None),
                ("resolved-source", PurePosixPath("/synthetic-system/project-alias.h"),
                 self.packet.source / "unplanned.h"),
                ("resolved-native-build", PurePosixPath("/synthetic-system/project-alias.h"),
                 self.native.paths["work"] / "simx-bf16/unplanned.h")):
            with self.subTest(label=label):
                self.packet = SyntheticControls(self.original, self.native)
                files = self.packet.substitution_files
                compiled = deepcopy(self.packet.substitution_report["dependency_control"]["compile"])
                extra = self.packet.payload(path, b"/* unreviewed project header */\n")
                if resolved is not None:
                    extra["resolved_path"] = str(resolved)
                compiled["inputs_before"].append(extra)
                compiled["inputs_after"] = deepcopy(compiled["inputs_before"])
                body = (compiled["output_path"] + ": " + " ".join(
                    row["path"] for row in compiled["inputs_before"]) + "\n").encode()
                old_payloads = {"payloads/" + compiled[key]["payload"]
                                for key in ("dependency_file", "dependency_prepass_file")}
                for key, relative in (("dependency_file", "work/gddr6-control.o.d"),
                        ("dependency_prepass_file", "work/gddr6-control.o.p06-before.d")):
                    compiled[key] = self.packet.payload(compiled[key]["path"], body)
                    files[relative] = body
                for name in old_payloads:
                    del files[name]
                self.packet.replace_substitution_record("compile", compiled)
                with self.assertRaisesRegex(ValueError, "unreviewed source/work file"):
                    self.packet.substitution_check()

    def test_control_originals_are_pinned_before_semantics_and_inventory_is_exact(self):
        for which, function in (("probe", replay.verify_probe_view), ("substitution", replay.verify_substitution_view)):
            files = getattr(self.packet, which + "_files")
            with self.subTest(which=which), self.assertRaisesRegex(ValueError, "externally pinned control report"):
                function(MemoryView(files, self.native.api), native=self.native,
                         expected_report_sha256="0" * 64, expected_native_report_sha256=self.packet.native_pin)
            files["unbound.py"] = b"raise AssertionError('retained code must remain inert')\n"
            with self.subTest(which=which), self.assertRaises(ValueError):
                getattr(self.packet, which + "_check")()

    def test_zip_bridge_runs_all_native_and_control_semantics_without_execution(self):
        files = self.original.hosted_files()
        files.update({"pending-probe/" + name: body for name, body in self.packet.probe_files.items()})
        files.update({"dependency-substitution/" + name: body for name, body in self.packet.substitution_files.items()})
        files["pending-probe.log"] = json_bytes({name: self.packet.probe_report[name] for name in (
            "outcome", "reason", "native_execution", "native_probe_passed", "zero_mutation_rejected")})
        files["dependency-substitution.log"] = json_bytes({name: self.packet.substitution_report[name] for name in (
            "outcome", "reason", "native_execution", "control_passed", "alternate_dependency_built",
            "numerical_control_passed", "original_provenance_rejected", "control_counts")})
        arguments = {"expected_revision": self.original.revision, "expected_receipt_sha256": self.original.receipt_pin,
            "expected_native_report_sha256": self.packet.native_pin, "expected_source_manifest_sha256": self.original.source_pin,
            "expected_probe_report_sha256": self.packet.probe_pin,
            "expected_substitution_report_sha256": self.packet.substitution_pin}

        def dependency_boundary(view, *, expected_revision, expected_receipt_sha256):
            self.assertEqual(expected_revision, self.original.revision)
            self.assertEqual(expected_receipt_sha256, digest(view.read("report.json")))
            return {"retained_dependency_verification": self.original.dependency_verification,
                    "synthetic_dependency_boundary": True}

        with tempfile.TemporaryDirectory(prefix="p06-control-synthetic-zip-") as directory:
            path = Path(directory) / "synthetic.zip"
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for name, body in files.items():
                    archive.writestr(name, body)
            pin = digest(path.read_bytes())
            inert_open, inert_resolve = inert_path_guards(replay.ROOT, replay.TRUSTED_READER_SOURCES,
                (*replay.native_replay.common.CORPUS, replay.native_replay.archive_helpers.ARCHIVE_READER_PATH),
                input_archive=path)
            with mock.patch.object(replay.native_replay.dependency_replay, "verify_view", side_effect=dependency_boundary) as boundary, \
                 mock.patch("subprocess.Popen", side_effect=AssertionError("retained process started")), \
                 mock.patch.object(replay.substitution, "verify_records", side_effect=AssertionError("live record verifier used")), \
                 mock.patch.object(replay.receipts, "PacketReader", side_effect=AssertionError("live producer path reader used")), \
                 mock.patch.object(zipfile.ZipFile, "extract", side_effect=AssertionError("archive extracted")), \
                 mock.patch.object(zipfile.ZipFile, "extractall", side_effect=AssertionError("archive extracted")), \
                 mock.patch.object(Path, "open", new=inert_open), mock.patch.object(Path, "resolve", new=inert_resolve):
                result = replay.replay_archive(path, pin, **arguments)
            boundary.assert_called_once()
            self.assertEqual(result["managed_counts"]["launches"], 132)
            self.assertEqual(result["dependency_substitution"]["control_counts"]["launches"], 33)
            self.assertEqual(result["native_review"]["commands_checked"], 37)
            self.assertEqual(result["native_execution"], "not_run")
            self.assertTrue(all(result[name] is False for name in replay.contract.FALSE_CLAIMS))
            self.assertIs(result["hosted_identity"]["separate_control_packets_semantically_verified"], True)
            for terminal, field in (("pending-probe.log", "zero_mutation_rejected"),
                                    ("dependency-substitution.log", "control_passed")):
                with self.subTest(terminal=terminal):
                    original_terminal = files[terminal]
                    damaged = json.loads(original_terminal)
                    damaged[field] = False
                    files[terminal] = json_bytes(damaged)
                    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                        for name, body in files.items():
                            archive.writestr(name, body)
                    with mock.patch.object(replay.native_replay.dependency_replay, "verify_view", side_effect=dependency_boundary), \
                         self.assertRaisesRegex(ValueError, "hosted .* terminal output"):
                        replay.replay_archive(path, digest(path.read_bytes()), **arguments)
                    files[terminal] = original_terminal
            # The synthetic dependency boundary cannot pass the actual pinned
            # full dependency reader when the explicit test stub is removed.
            with self.assertRaises(ValueError):
                replay.replay_archive(path, digest(path.read_bytes()), **arguments)

    def test_every_external_intake_pin_is_mandatory_before_archive_open(self):
        arguments = {"expected_revision": "a" * 40, "expected_receipt_sha256": "a" * 64,
            "expected_native_report_sha256": "a" * 64, "expected_source_manifest_sha256": "a" * 64,
            "expected_probe_report_sha256": "a" * 64, "expected_substitution_report_sha256": "a" * 64}
        for name in arguments:
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "external"):
                replay.replay_archive(Path("/must-not-open.zip"), "a" * 64, **dict(arguments, **{name: ""}))
        with self.assertRaisesRegex(ValueError, "external"):
            replay.replay_archive(Path("/must-not-open.zip"), "", **arguments)


class TinyActualRecorderReplayTests(unittest.TestCase):
    def test_two_real_tiny_host_tool_records_survive_source_removal_and_inert_replay(self):
        fixture = substitution_tests.ActualSubstitutionBuildTests(
            methodName="test_actual_fresh_marker_library_preserves_tiny_numerics_and_is_byte_different")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        # Copy only trusted fixture tools before generating the packet. No
        # retained file is executed or imported during the subsequent review.
        helper_dir = fixture.source / "ci/project"
        helper_dir.mkdir(parents=True)
        for name in ("p06_dependency_record.py", "p06_dependency_contract.py", "baseline_packet_io.py"):
            shutil.copyfile(replay.ROOT / "ci/project" / name, helper_dir / name)
        for role, arguments in replay.substitution.recipes(fixture.source, fixture.work).items():
            fixture.call([fixture.tools["python3"]["path"], str(helper_dir / "p06_dependency_record.py"),
                "--config", str(fixture.config_path), "--config-sha256", fixture.pin,
                "--tool", "g++", "--role", role, "--", *arguments])
        for library in (fixture.original, fixture.work / replay.substitution.LIBRARY):
            script = "import ctypes,sys; print(ctypes.CDLL(sys.argv[1]).control_value())"
            self.assertEqual(fixture.call([fixture.tools["python3"]["path"], "-c", script, str(library)],
                environment=dict(fixture.environment, LD_LIBRARY_PATH=str(fixture.ramulator))).strip(), "42")
        source_row = descriptor("ci/project/p06_dependency_record.py", (helper_dir / "p06_dependency_record.py").read_bytes())
        original = fixture.gddr6.read_bytes()
        native = SimpleNamespace(sources={source_row["path"]: source_row},
            paths={"work": PurePosixPath(fixture.source.parent / "managed-work")}, dependency_document={
            "paths": {"workspace": fixture.admission.document["paths"]["workspace"]},
            "source_manifest": {"sources": [{"name": "ramulator", "files": [descriptor("src/dram/impl/GDDR6.cpp", original)]}]},
            "products": fixture.admission.products, "external_archives": []})
        files = {path.relative_to(fixture.output).as_posix(): path.read_bytes()
                 for path in fixture.output.rglob("*") if path.is_file()}
        report = {"tool_config": descriptor("tool-config.json", files["tool-config.json"]), "environment": fixture.environment}
        files["report.json"] = json_bytes(report)
        api = replay.native_replay.dependency_replay._archive_api()
        packet = replay._Packet(MemoryView(files, api), api, digest(files["report.json"]))
        source, work = PurePosixPath(fixture.source), PurePosixPath(fixture.work)
        shutil.rmtree(fixture.source)
        shutil.rmtree(fixture.output)
        with mock.patch("subprocess.Popen", side_effect=AssertionError("tool restarted by replay")), \
             mock.patch.object(replay.receipts, "PacketReader", side_effect=AssertionError("live packet reader used")), \
             mock.patch.object(Path, "open", side_effect=AssertionError("producer file opened")), \
             mock.patch.object(Path, "resolve", side_effect=AssertionError("producer path resolved")):
            checked = replay._substitution_records(packet, native, fixture.config, source, work)
        self.assertEqual([row["stage"] for row in checked["compile"]["children"]], ["dependencies", "tool"])
        self.assertEqual(len(checked["records"]), 2)
        self.assertNotEqual(checked["alternate_product"]["sha256"], checked["original_product"]["sha256"])
        self.assertEqual(checked["source_derivation"]["retained_original"]["sha256"], digest(original))


if __name__ == "__main__":
    unittest.main()
