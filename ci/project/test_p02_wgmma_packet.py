# SPDX-License-Identifier: Apache-2.0
"""Synthetic transport/adversarial controls; these are not GPU execution evidence."""

import copy
from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

import p02_wgmma_packet as packet
import p02_wgmma_matrix as matrix
import p02_wgmma_records as records
import test_p02_wgmma_matrix as support
import test_p02_wgmma_witness as witness_support


def row(path, contents):
    return {"path": path, "sha256": hashlib.sha256(contents).hexdigest(), "size_bytes": len(contents)}


class PacketFixture:
    def __init__(self, root, *, full=False, witness=False, parity_failure=False, witness_failure=False):
        self.root = root
        self.report = r = {"schema_version": 1, "contract_id": matrix.CONTRACT_ID, "state": "finished",
            "iterations": 2, "acceptance_claimed": False, "qualifies_P02_A03": False, "phase_complete": False,
            "source_frozen_before_execution": True, "source_stable": True, "development": not full,
            "full_matrix_requested": full, "witness_requested": witness, "source_dirty": False,
            "source_revision": "1" * 40, "budget": dict(matrix.BUDGET, jobs=2), "commands": [], "variants": [],
            "paths": {"source": "/synthetic/source", "work": "/synthetic/work", "tools": "/synthetic/tools",
                      "verilator": "/synthetic/tools/verilator", "output": str(root)}}
        manifest, fixtures = matrix.load_inputs(packet.ROOT)
        specs = manifest["variants"] if full else [manifest["variants"][-1 if witness else 0]]
        backends = list(matrix.BACKENDS) if full else ["rtlsim" if witness else "simx"]
        source_names = set(packet.HELPERS + (matrix.MANIFEST, packet.WITNESS_PARSER) + matrix.CORPUS + matrix.COPIED + matrix.CONFIG_INPUTS)
        for directory in (matrix.APP, "tests/regression/sgemm_tcu_wg", "tests/regression/sgemm_tcu_wg_sp"):
            source_names |= {str(path.relative_to(packet.ROOT)) for path in (packet.ROOT / directory).iterdir()
                             if path.is_file() and (path.suffix in matrix.SOURCE_SUFFIXES or path.name == "Makefile")}
        if witness:
            source_names.add(manifest["witness"]["source"])
        source_files = {}
        source_rows = []
        for name in sorted(source_names):
            data = (packet.ROOT / name).read_bytes()
            source_files[name] = data
            source_rows.append(self.put("artifacts/source/" + name, data))
        r["source_snapshots"] = source_rows
        originals = {name: row(name, data) for name, data in source_files.items()}
        r["loaded_helpers"] = [originals[name] for name in packet.HELPERS]
        r["manifest"] = originals[matrix.MANIFEST]
        r["corpus"] = manifest["fixture_inputs"]
        if witness:
            r["witness_parser"] = originals[packet.WITNESS_PARSER]
        self.source = {"checkout": {"revision": r["source_revision"], "tree": "2" * 40, "dirty": False,
            "changed_paths": [], "untracked_paths": [], "blockers": [], "inputs": [originals["configure"]]},
            "files": [originals[name] for name in sorted(originals)]}
        for name in ("before", "after"):
            r["source_" + name] = self.snapshot("source-" + name, self.source)
        tool_names = {"make", "g++", "gcc", "ar", "as", "ld", "python3", "bash", "perl", "clang", "clang++",
            "llvm-objcopy", "llvm-objdump", "riscv-gcc", "riscv-gcc-ar", "riscv-objdump", "riscv-objcopy",
            "libc64/lib/libc.a", "libc64/lib/libm.a", "libcrt64/lib/baremetal/libclang_rt.builtins-riscv64.a"}
        if "rtlsim" in backends:
            tool_names |= {"verilator", "verilator_bin"}
        self.tools = {name: dict(row("/synthetic/tools/" + name, b"synthetic tool"), resolved_path="/synthetic/tools/" + name)
                      for name in sorted(tool_names)}
        self.environment = matrix.clean_environment({"work": Path(r["paths"]["work"]), "host_bin": None}, 2)
        for suffix in ("before", "after"):
            r["tools_" + suffix] = self.snapshot("tools-" + suffix, self.tools)
            r["dependencies_" + suffix] = [row(name, b"synthetic dependency") for name in matrix.DEPENDENCIES]
            r["dependency_headers_" + suffix] = [row(prefix + "synthetic.h", b"synthetic header") for prefix in packet.HEADER_ROOTS]
        for name in ["g++", "make", "clang", "riscv-gcc"] + (["verilator"] if "rtlsim" in backends else []):
            self.command("version-" + name.replace("+", "p"), "synthetic version\n", [self.tools[name]["path"], "--version"])
        for driver in backends:
            for spec in specs:
                vid = driver + "-" + spec["id"]
                build = Path(r["paths"]["work"]) / vid
                selected_witness = witness and driver == "rtlsim" and spec["sparse"]
                flags = manifest["configs"] + spec["configs"] + ([manifest["witness"]["flag"]] if selected_witness else [])
                item = {"id": vid, "backend": driver, "configuration_id": spec["id"], "configuration": spec,
                        "profile": "", "witness": selected_witness, "configs": flags, "build_dir": str(build), "cases": []}
                r["variants"].append(item)
                for suffix in ("before", "built", "after"):
                    r["source_" + vid + "-" + suffix] = self.snapshot("source-" + vid + "-" + suffix, self.source)
                stamps = support.compiler_fixture(driver, spec, source=Path(r["paths"]["source"]), build=build, witness=selected_witness)
                item["compiler_records"] = records.validate_records(*stamps, driver=driver, variant=spec,
                    source=Path(r["paths"]["source"]), build=build, jobs=2, witness=selected_witness)
                generated = {name: b"synthetic generated header\n" for name in matrix.GENERATED}
                generated.update({name: source_files[name] for name in matrix.COPIED})
                generated["config.mk"] = ("XLEN ?= 64\nPROFILE ?=\nVORTEX_HOME ?= /synthetic/source\n"
                    "TOOLDIR ?= /synthetic/tools\nOSVERSION ?= ubuntu/focal\n").encode()
                generated[".config.stamp"] = ("XLEN=64 PROFILE= SOURCE_DIR=/synthetic/source BUILDDIR=" + str(build) + " TOOLDIR=/synthetic/tools\n").encode()
                generated["sim/rtlsim/verilator.vlt"] = source_files["sim/rtlsim/verilator.vlt.in"].replace(b"@VORTEX_HOME@", b"/synthetic/source")
                binaries = {name: b"synthetic binary" for name in (
                    matrix.APP + "/p02_wgmma", matrix.APP + "/kernel.elf", matrix.APP + "/kernel.vxbin",
                    "sw/kernel/libvortex2.a", "sw/runtime/libvortex.so", "sw/runtime/libvortex-" + driver + ".so", "sw/runtime/lib" + driver + ".so")}
                artifacts = dict(generated, **binaries)
                artifacts.update({name: text.encode() for name, text in zip(("sw/runtime/" + driver + "_rt_config.stamp",
                    "sw/runtime/" + driver + "_config.stamp", matrix.APP + "/config.stamp"), stamps)})
                if driver == "rtlsim":
                    artifacts.update({"sw/runtime/librtlsim.so.obj_dir/Vrtlsim_shim" + suffix: b"synthetic native metadata\n"
                                      for suffix in ("__verFiles.dat", "_classes.mk", "__Syms.h")})
                item["generated_before"] = [row(name, generated[name]) for name in matrix.GENERATED + matrix.COPIED]
                item["artifacts_before"] = [row(name, data) for name, data in sorted(artifacts.items())]
                item["artifacts_after"] = copy.deepcopy(item["artifacts_before"])
                item["retained_artifacts"] = [self.put("artifacts/" + vid + "/" + name, data)
                    for name, data in sorted(artifacts.items()) if packet.retained_name(name)]
                source = Path(r["paths"]["source"])
                app = build / matrix.APP
                make = [self.tools["make"]["path"], "--no-print-directory", "-j2", "THREADS=2", "VERILATOR_PATH=/synthetic/tools/verilator"]
                current = dict(self.environment, CONFIGS=" ".join(flags), VORTEX_PROFILING="11")
                self.command(vid + "-configure", "synthetic configure\n", [str(source / "configure"), "--xlen=64",
                    "--profile=", "--osversion=ubuntu/focal", "--tooldir=/synthetic/tools"], cwd=build)
                for language, name in (("cpp", "VX_config.h"), ("verilog", "VX_config.vh")):
                    self.command(vid + "-" + language + "-header-reproduce", "synthetic header generation\n",
                        [self.tools["python3"]["path"], str(source / "ci/gen_config.py"), "--config=" + str(source / "VX_config.toml"),
                         "--profile=", "--format=" + language, "--output=" + str(build / "p02-header-check" / name)],
                        dict(self.environment, XLEN="64"), cwd=build)
                self.command(vid + "-runtime", "synthetic runtime build\n", make + ["runtime-" + driver], current, cwd=app)
                self.command(vid + "-application-build", "synthetic application build\n", make + ["all"], current, cwd=app)
                effective = support.header_for(spec, witness=selected_witness)
                self.command(vid + "-effective-header", effective, [self.tools["g++"]["path"], "-E", "-dM", "-x", "c++",
                    *item["compiler_records"][1]["macro_flags"], "-include", str(build / "sw/VX_config.h"), "/dev/null"], cwd=build)
                item["effective_backend_configuration"] = records.validate_header_macros(effective, spec)
                disassembly = self.command(vid + "-kernel-disassembly", "synthetic disassembly\n",
                    [self.tools["llvm-objdump"]["path"], "-D", str(app / "kernel.elf")], cwd=app)
                item["kernel_disassembly"] = packet.log_identity(disassembly)
                for name in spec["cases"]:
                    case = fixtures[name]
                    if selected_witness:
                        rows = witness_support.trace(wait_launches=(not witness_failure, not witness_failure))
                        for label, value in rows:
                            if label in ("BEGIN", "RESULT", "PASS"):
                                value["case_id"] = name
                            if label == "RESULT":
                                value["actual_bits"] = value["expected_bits"] = case["expected"]
                        text = witness_support.render(rows)
                    else:
                        cycles = 1051 if parity_failure and driver == "simx" else 1000
                        text = support.render(support.output_rows(case, spec, cycles=(cycles, 2 * cycles), instructions=(100, 200)))
                    cmd = self.command(vid + "-" + name, text,
                        make + ["--silent", "run-" + driver, "OPTS=--case=" + name + " --iterations=2"], current, cwd=app)
                    observed = {"id": name, "command_id": cmd["id"], "arithmetic_outcome": "pass", "witness_outcome": "not_run",
                        "outcome": "pass", "observations": records.verify_output(text, case, spec, witness=selected_witness)}
                    if selected_witness:
                        try:
                            observed["witness"] = packet.verify_witness(text, require_wait=True)
                            observed["witness_outcome"] = "pass"
                        except ValueError as error:
                            observed.update(witness_outcome="fail", outcome="fail", witness_reason=str(error))
                    item["cases"].append(observed)
                item["outcome"] = "pass" if all(case["outcome"] == "pass" for case in item["cases"]) else "fail"
        case_ids = sorted({case["id"] for item in r["variants"] for case in item["cases"]})
        r["case_ids"] = case_ids
        r["fixture_snapshot"] = self.snapshot("selected-fixtures", [fixtures[name] for name in case_ids])
        count = sum(len(item["cases"]) for item in r["variants"])
        r.update(full_matrix_counts=manifest["expected_counts"], expected_case_executions=count,
            completed_case_executions=count, verified_case_executions=count, expected_launches=count * 2,
            verified_launches=count * 2, expected_checked_output_words=count * 1024, checked_output_words=count * 1024,
            expected_witness_case_executions=sum(len(item["cases"]) for item in r["variants"] if item["witness"]))
        r["paired_performance"] = matrix.paired_comparisons(r["variants"])
        r["arithmetic_outcome"] = "pass"
        r["witness_outcome"] = ("fail" if witness_failure else "pass") if witness else "not_run"
        r["parity_outcome"] = r["paired_performance"]["outcome"]
        failures = []
        if r["parity_outcome"] == "fail":
            failures.append("paired retired-instruction or cycle parity differs")
        if r["witness_outcome"] == "fail":
            failures.append("metadata witness ordering or observed wait coverage failed")
        r["outcome"] = "fail" if failures else "pass"
        r["reason"] = "; ".join(failures) + "; arithmetic outcome retained separately" if failures else None
        self.save()

    def put(self, name, contents):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
        return row(name, contents)

    def snapshot(self, name, value):
        return self.put("snapshots/" + name + ".json", (json.dumps(value, indent=2) + "\n").encode())

    def command(self, name, text, argv=None, environment=None, *, cwd=None):
        identity = self.put("logs/" + name + ".log", text.encode())
        cmd = {"id": name, "argv": argv or ["/synthetic/command"], "environment": environment or self.environment,
            "cwd": str(cwd or "/synthetic/work"), "log": identity["path"], "log_sha256": identity["sha256"],
            "log_size_bytes": identity["size_bytes"], "timeout_seconds": 120, "process_started": True,
            "cleanup_complete": True, "exit_code": 0, "outcome": "pass"}
        self.report["commands"].append(cmd)
        return cmd

    def save(self):
        data = (json.dumps(self.report, indent=2) + "\n").encode()
        self.put("report.json", data)
        return hashlib.sha256(data).hexdigest()

    def alter_build(self, path, text):
        item = self.report["variants"][0]
        changed = row(path, text.encode())
        for field in ("artifacts_before", "artifacts_after", "generated_before"):
            item[field] = [changed if old["path"] == path else old for old in item[field]]
        saved = self.put("artifacts/" + item["id"] + "/" + path, text.encode())
        item["retained_artifacts"] = [saved if old["path"] == saved["path"] else old for old in item["retained_artifacts"]]

    def omit_source_chain(self, names):
        """Remove original identities, retained copies and every stable snapshot."""
        names = set(names)
        self.source["files"] = [item for item in self.source["files"] if item["path"] not in names]
        self.source["checkout"]["inputs"] = [item for item in self.source["checkout"]["inputs"]
                                             if item["path"] not in names]
        self.report["loaded_helpers"] = [item for item in self.report["loaded_helpers"]
                                         if item["path"] not in names]
        retained = {"artifacts/source/" + name for name in names}
        self.report["source_snapshots"] = [item for item in self.report["source_snapshots"]
                                            if item["path"] not in retained]
        for name in retained:
            (self.root / name).unlink()
        contents = (json.dumps(self.source, indent=2) + "\n").encode()
        for key, value in self.report.items():
            if key.startswith("source_") and type(value) is dict:
                self.report[key] = self.put(value["path"], contents)


class PacketTests(unittest.TestCase):
    def fixture(self, **kwargs):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        return PacketFixture(Path(temp.name), **kwargs)

    def rejects(self, fixture, message=None):
        fixture.save()
        with self.assertRaisesRegex((ValueError, KeyError, TypeError), message or ".*"):
            packet.verify_packet(fixture.root)

    def test_full_original_packet_replays_exact_inventory_and_keeps_acceptance_false(self):
        fixture = self.fixture(full=True, witness=True)
        result = packet.verify_packet(fixture.root, report_sha256=fixture.save(), require_witness=True)
        self.assertTrue(result["packet_valid"])
        self.assertEqual(result["counts"], {"backend_variants": 12, "case_executions": 24, "launches": 48,
            "checked_output_words": 24576, "commands": 113, "performance_pairs": 12, "witness_case_executions": 2})
        self.assertEqual(result["qualification_status"], "independent_review_required")
        self.assertEqual(result["trust_anchor"], "external_report_sha256")
        self.assertIn("ci/project/p02_wgmma_packet.py", {item["path"] for item in result["verifier_sources"]})
        self.assertTrue(all(result["unavailable_binary_bodies"].values()))
        for key in ("acceptance_claimed", "qualifies_P02_A03", "phase_complete"):
            self.assertIs(result[key], False)

    def test_complete_parity_failure_is_valid_evidence_without_qualification(self):
        fixture = self.fixture(full=True, witness=True, parity_failure=True)
        result = packet.verify_packet(fixture.root)
        self.assertTrue(result["packet_valid"])
        self.assertEqual((result["arithmetic_outcome"], result["witness_outcome"], result["parity_outcome"]), ("pass", "pass", "fail"))
        self.assertEqual(result["qualification_status"], "not_established")
        fixture.report["paired_performance"]["pairs"][0]["launches"][0]["cycle_within_tolerance"] = True
        self.rejects(fixture, "paired performance")

    def test_retained_witness_failure_replays_but_forged_pass_is_rejected(self):
        fixture = self.fixture(witness=True, witness_failure=True)
        result = packet.verify_packet(fixture.root, require_witness=True)
        self.assertEqual((result["arithmetic_outcome"], result["witness_outcome"]), ("pass", "fail"))
        fixture.report["variants"][0]["cases"][0]["witness_outcome"] = "pass"
        self.rejects(fixture, "witness outcome")

    def test_partial_development_is_preserved_and_cannot_become_formal(self):
        fixture = self.fixture()
        result = packet.verify_packet(fixture.root)
        self.assertFalse(result["full_matrix"])
        self.assertEqual(result["qualification_status"], "not_established")
        self.assertEqual(result["parity_outcome"], "not_run")
        with self.assertRaisesRegex(ValueError, "witness"):
            packet.verify_packet(fixture.root, require_witness=True)
        fixture.report["development"] = False
        self.rejects(fixture, "incomplete matrix")

    def test_duplicate_missing_or_unstarted_commands_reject(self):
        fixture = self.fixture()
        original = copy.deepcopy(fixture.report)
        for change in (lambda r: r["commands"].pop(), lambda r: r["commands"].append(r["commands"][0]),
                       lambda r: r["commands"][0].update(process_started=False),
                       lambda r: r["commands"][0].update(exit_code=False),
                       lambda r: r["commands"][0].update(cleanup_complete=False),
                       lambda r: r["commands"][-1]["argv"].insert(1, "CONFIGS=-Ofast")):
            fixture.report = copy.deepcopy(original)
            change(fixture.report)
            self.rejects(fixture, "command")

    def test_duplicate_missing_variant_or_case_inventory_rejects(self):
        fixture = self.fixture()
        original = copy.deepcopy(fixture.report)
        for change in (lambda r: r["variants"].append(r["variants"][0]),
                       lambda r: r["variants"][0]["cases"].append(r["variants"][0]["cases"][0]),
                       lambda r: r["variants"][0]["cases"].pop(),
                       lambda r: r.update(full_matrix_requested=True)):
            fixture.report = copy.deepcopy(original)
            change(fixture.report)
            self.rejects(fixture)

    def test_corrupt_log_and_self_consistent_wrong_arithmetic_reject(self):
        fixture = self.fixture()
        cmd = fixture.report["commands"][-1]
        path = fixture.root / cmd["log"]
        original = path.read_text()
        path.write_text(original + "corruption\n")
        self.rejects(fixture, "retained file")
        changed = original.replace('"actual_bits": ["', '"actual_bits": ["00000000", "', 1)
        identity = fixture.put(cmd["log"], changed.encode())
        cmd.update(log_sha256=identity["sha256"], log_size_bytes=identity["size_bytes"])
        self.rejects(fixture, "raw output bits")

    def test_traversal_symlink_and_hard_link_aliases_reject(self):
        fixture = self.fixture()
        command = fixture.report["commands"][0]
        original = command["log"]
        command["log"] = "logs/../" + Path(original).name
        self.rejects(fixture, "command log path")
        command["log"] = original
        path = fixture.root / original
        outside = fixture.root / "outside"
        outside.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(outside)
        self.rejects(fixture, "regular file")
        path.unlink()
        os.link(outside, path)
        self.rejects(fixture, "hard-link aliases")

    def test_bounded_json_rejects_duplicates_nonfinite_and_deep_input(self):
        for text in ('{"a": 1, "a": 2}', '{"a": NaN}', '{"a": Infinity}', '{"a": 1e999}',
                     '{"a": ' + '[' * 65 + '0' + ']' * 65 + '}'):
            with self.subTest(text=text[:40]), self.assertRaises(ValueError):
                packet.parse_json(text.encode(), "mutation")
        fixture = self.fixture()
        path = fixture.root / fixture.report["commands"][0]["log"]
        with path.open("wb") as stream:
            stream.truncate(matrix.BUDGET["max_log_bytes"] + 1)
        self.rejects(fixture, "byte limit")

    def test_forged_observations_counts_and_acceptance_flags_reject(self):
        fixture = self.fixture()
        original = copy.deepcopy(fixture.report)
        for change in (lambda r: r.update(verified_launches=5), lambda r: r.update(checked_output_words=2048.0),
                       lambda r: r.update(phase_complete=True), lambda r: r.update(schema_version=True),
                       lambda r: r.update(arithmetic_outcome="fail"),
                       lambda r: r["variants"][0]["cases"][0]["observations"]["launches"][1]["performance"].update(cycles=999)):
            fixture.report = copy.deepcopy(original)
            change(fixture.report)
            self.rejects(fixture)

    def test_source_tool_and_dependency_header_drift_reject(self):
        fixture = self.fixture()
        original = copy.deepcopy(fixture.report)
        changed_source = copy.deepcopy(fixture.source)
        changed_source["checkout"]["revision"] = "3" * 40
        fixture.report["source_after"] = fixture.snapshot("source-after", changed_source)
        self.rejects(fixture, "source stability")
        fixture.report = copy.deepcopy(original)
        fixture.report["source_after"] = fixture.snapshot("source-after", fixture.source)
        changed_tools = copy.deepcopy(fixture.tools)
        changed_tools["g++"]["sha256"] = "3" * 64
        fixture.report["tools_after"] = fixture.snapshot("tools-after", changed_tools)
        self.rejects(fixture, "tool stability")
        fixture.report["tools_after"] = fixture.snapshot("tools-after", fixture.tools)
        fixture.report["dependency_headers_after"][0]["sha256"] = "3" * 64
        self.rejects(fixture, "dependency header stability")

    def test_missing_helper_fixture_and_retained_source_evidence_reject(self):
        fixture = self.fixture()
        original = copy.deepcopy(fixture.report)
        for change in (lambda r: r["loaded_helpers"].pop(), lambda r: r["source_snapshots"].pop(),
                       lambda r: r["corpus"].pop(), lambda r: r.update(case_ids=[])):
            fixture.report = copy.deepcopy(original)
            change(fixture.report)
            self.rejects(fixture)

    def test_full_packet_cannot_omit_host_and_both_kernel_source_chains(self):
        fixture = self.fixture(full=True, witness=True)
        fixture.omit_source_chain(("tests/regression/p02_wgmma/main.cpp",
                                   "tests/regression/sgemm_tcu_wg/kernel.cpp",
                                   "tests/regression/sgemm_tcu_wg_sp/kernel.cpp"))
        self.rejects(fixture, "source/ inventory differs")

    def test_required_consumer_and_helper_source_chains_cannot_be_omitted(self):
        required = ("tests/regression/p02_wgmma/main.cpp", "tests/regression/p02_wgmma/Makefile",
                    "tests/regression/sgemm_tcu_wg/main.cpp", "tests/regression/sgemm_tcu_wg/common.h",
                    "tests/regression/sgemm_tcu_wg/kernel.cpp", "tests/regression/sgemm_tcu_wg/Makefile",
                    "tests/regression/sgemm_tcu_wg_sp/main.cpp", "tests/regression/sgemm_tcu_wg_sp/common.h",
                    "tests/regression/sgemm_tcu_wg_sp/kernel.cpp", "tests/regression/sgemm_tcu_wg_sp/Makefile",
                    "ci/project/p02_wgmma_records.py")
        for name in required:
            with self.subTest(source=name):
                fixture = self.fixture()
                fixture.omit_source_chain((name,))
                self.rejects(fixture, "source/ inventory differs|loaded helper closure")

    def test_each_compiler_stamp_is_revalidated_even_after_rehash(self):
        fixture = self.fixture()
        name = "sw/runtime/simx_rt_config.stamp"
        path = fixture.root / "artifacts" / fixture.report["variants"][0]["id"] / name
        fixture.alter_build(name, path.read_text().replace("-DVX_CFG_NUM_THREADS=8", "-DVX_CFG_NUM_THREADS=4"))
        self.rejects(fixture, "VX_CFG_NUM_THREADS")

    def test_generated_copy_binding_and_native_metadata_are_required(self):
        fixture = self.fixture(witness=True)
        name = "sw/kernel/Makefile"
        fixture.alter_build(name, "changed copied build input\n")
        self.rejects(fixture, "copied build input")
        fixture = self.fixture(witness=True)
        item = fixture.report["variants"][0]
        name = "sw/runtime/librtlsim.so.obj_dir/Vrtlsim_shim__Syms.h"
        for field in ("artifacts_before", "artifacts_after", "retained_artifacts"):
            item[field] = [value for value in item[field] if not value["path"].endswith(name)]
        self.rejects(fixture, "native hierarchy")

    def test_external_digest_original_location_and_cli_failure_semantics(self):
        fixture = self.fixture()
        with self.assertRaisesRegex(ValueError, "external report digest"):
            packet.verify_packet(fixture.root, report_sha256="0" * 64)
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(packet.main([str(fixture.root)]), 0)
        self.assertTrue(json.loads(output.getvalue())["packet_valid"])
        fixture.report["paths"]["output"] = "/different/original/path"
        fixture.save()
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(packet.main([str(fixture.root)]), 1)
        self.assertFalse(json.loads(output.getvalue())["packet_valid"])


if __name__ == "__main__":
    unittest.main()
