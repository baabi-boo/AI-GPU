#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run a separate, numerically favorable wrong-dependency provenance control.

The admitted measurement products stay unchanged. A fresh extension has one
explicit emitted marker added, then the existing FP16 application observes that
alternate extension through the native loader. This extra process is outside
the four-process managed population and cannot establish qualification.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys

sys.dont_write_bytecode = True

from baseline_inventory import collect_source, hash_artifacts
from baseline_process import run_bounded
import p02_matrix as base
import p06_dependency_admission as admission_module
import p06_dependency_binary as binary
import p06_dependency_build as builder
import p06_dependency_contract as dependency
import p06_dependency_receipt as receipts
import p06_dependency_record as recorder
import p06_managed_preflight_contract as manifest
import p06_managed_preflight_execute as preflight
import p06_native_lifetime_contract as lifetime
import p06_native_lifetime_records as lifetime_records
import p06_pending_probe as probe
from preflight import available_memory_bytes


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_ID = "p06-dependency-substitution-control-v1"
SOURCE_FILES = ("ci/project/p06_dependency_substitution.py",)
FORMAT = "fp16"
POLICY = "reusable_single_tile"
LIBRARY = "libramulator-vortex.so"
MARKER = b"p06-known-different-dependency-v1"
MARKER_DECLARATION = (b'extern "C" {\n'
    b'__attribute__((used, visibility("default")))\n'
    b'extern const char p06_dependency_substitution_marker[] = "' + MARKER + b'";\n}\n')
ORIGINAL_SOURCE = "third_party/ramulator/src/dram/impl/GDDR6.cpp"
CONTROL_SOURCE = "gddr6-control.cpp"
REJECTION = "loaded library libramulator-vortex.so: differs from the fixed contract"
BUDGET = dict(preflight.BUDGET)
LIMITATIONS = [
    "One extra FP16 reusable-policy process belongs only to this negative control, outside the four managed processes and their 132 launches.",
    "The alternate extension compiles an isolated copy of the admitted GDDR6 source with a fixed emitted declaration appended; no admitted source or measurement product is modified.",
    "Numerical success and complete lifetime observations can coexist with rejection of the actual alternate dependency path and bytes.",
    "This executing control does not authenticate an untrusted producer or defeat malicious concurrent filesystem writers.",
    "All qualification, warm-readiness, warm-execution, performance and phase acceptance claims remain false.",
]


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def recipes(source, work):
    """Construct reviewed commands; retained producer argv is never executed."""
    source, work = Path(source), Path(work)
    ramulator = source / "third_party/ramulator"
    compile_args = ["-std=c++20", "-O3", "-DNDEBUG", "-fPIC"]
    for directory in (ramulator / "src", ramulator / "ext/spdlog/include",
                      ramulator / "ext/yaml-cpp/include"):
        compile_args.extend(("-isystem", str(directory)))
    compile_args.extend(("-c", str(work / CONTROL_SOURCE), "-o", str(work / "gddr6-control.o")))
    link_args = ["-shared", str(work / "gddr6-control.o"), "-L" + str(ramulator),
        "-lramulator", "-Wl,-Map," + str(work / "control.map"), "-o", str(work / LIBRARY)]
    return {"compile": compile_args, "link": link_args}


def derived_source(original):
    require(type(original) is bytes and 0 < len(original)
            <= dependency.MAX_FILE_BYTES - len(MARKER_DECLARATION) - 1,
            "control original source is empty or exceeds its bound")
    return original + b"\n" + MARKER_DECLARATION


def prepare_source(source, output, work, admission):
    """Copy the exact admitted source and append one fixed, reviewed declaration."""
    original_path = source / ORIGINAL_SOURCE
    known = {row["path"]: row for row in admission.source_inputs}
    require(str(original_path) in known
            and builder.identity(original_path) == known[str(original_path)],
            "control original source differs from the pinned dependency input")
    retained = output / "inputs/gddr6-original.cpp"
    builder.stage_file(original_path, retained)
    body = receipts.PacketReader(output)("inputs/gddr6-original.cpp")
    generated = work / CONTROL_SOURCE
    with generated.open("xb") as stream:
        stream.write(derived_source(body))
    require(builder.identity(original_path) == known[str(original_path)],
            "control original source changed during derivation")
    return {"original_source": known[str(original_path)],
            "retained_original": builder.identity(retained, relative_to=output),
            "derived_source": builder.identity(generated, relative_to=output),
            "appended_declaration_sha256": hashlib.sha256(MARKER_DECLARATION).hexdigest()}


def verify_observation(text, *, contract, case, binding_id, original_libraries, alternate_path):
    """Use the same exact transcript twice, with separate loader expectations."""
    require(set(original_libraries) == set(manifest.LOADED_LIBRARY_NAMES),
            "control original library inventory differs")
    require(alternate_path != original_libraries[LIBRARY], "control did not select an alternate path")
    selected = dict(original_libraries, **{LIBRARY: alternate_path})
    identity = manifest.process_identity(FORMAT, POLICY, binding_id)
    parameters = dict(contract=contract, case=case, fmt=FORMAT, policy=POLICY,
        binding_id=binding_id, sample_id=identity["sample_id"], process_id=identity["process_id"])
    observed = lifetime_records.verify_output(text, expected_libraries=selected, **parameters)
    counts = preflight.completion_counts([{"outcome": "pass", "observation": observed}])
    require(counts["processes"] == 1 and counts["launches"] == 33
            and counts["checked_words"] == 1056, "control numerical population is incomplete")
    try:
        lifetime_records.verify_output(text, expected_libraries=original_libraries, **parameters)
    except ValueError as error:
        require(str(error) == REJECTION, "control rejected for a different provenance reason: " + str(error))
        rejection = str(error)
    else:
        raise ValueError("alternate dependency was admitted as the original product")
    return {"observation": observed, "control_counts": counts,
            "expected_libraries": selected, "rejection": rejection}


def verify_records(output, config, config_sha256, *, source, work, managed_work, admission, tools):
    """Reconcile the two actual recorder operations with this reviewed control."""
    reader = receipts.PacketReader(output)
    require(config["tools"] == {name: tools[name] for name in recorder.TOOLS},
            "control selected tools differ from admitted dependency tools")
    paths = sorted((output / "records").glob("*.json"))
    require(len(paths) == 2, "control requires exactly one fresh compile and one fresh link")
    expected_recorder = base._file_identity(source / "ci/project/p06_dependency_record.py")
    rows = [receipts._validate_record(receipts.decode(reader(path.relative_to(output).as_posix())),
        config, config_sha256, reader, expected_recorder) for path in paths]
    require({row["role"] for row in rows} == {"compile", "link"}, "control recorder roles differ")
    selected = {row["role"]: row for row in rows}
    expected = recipes(source, work)
    for role, row in selected.items():
        require(row["tool_name"] == "g++" and row["requested_arguments"] == expected[role]
                and row["cwd"] == str(work), "control tool recipe differs")
    compiled, linked = selected["compile"], selected["link"]
    require(compiled["finished_ns"] <= linked["started_ns"], "control link preceded completed compilation")
    known = {row["path"]: row for row in admission.source_inputs}
    original_path = str(source / ORIGINAL_SOURCE)
    require(original_path in known, "control original source is not a pinned dependency input")
    original = reader("inputs/gddr6-original.cpp")
    require(hashlib.sha256(original).hexdigest() == known[original_path]["sha256"]
            and len(original) == known[original_path]["size_bytes"],
            "control retained original differs from the pinned dependency input")
    derived_path = str(work / CONTROL_SOURCE)
    derived_seen = False
    project_roots = (source, work, managed_work, Path(admission.document["paths"]["workspace"]))
    for row in compiled["inputs_before"]:
        if row["path"] == derived_path:
            require(row["resolved_path"] == derived_path
                    and receipts.payload(row, reader) == derived_source(original),
                    "control source is not the exact pinned source plus emitted declaration")
            derived_seen = True
        elif Path(row["path"]).is_relative_to(source / "third_party"):
            require(row["path"] in known and row["resolved_path"] == row["path"]
                    and all(row[key] == known[row["path"]][key] for key in ("sha256", "size_bytes")),
                    "control source/header differs from the pinned dependency input")
        else:
            require(not any(Path(row[key]).is_relative_to(root)
                            for root in project_roots for key in ("path", "resolved_path")),
                    "control compiler input has an unreviewed project file")
    require(derived_seen, "actual compiler closure omits the derived control source")
    product = admission.products["ramulator"]
    require(len(linked["inputs_before"]) == 2, "control link input population differs")
    by_path = {row["path"]: row for row in linked["inputs_before"]}
    require(by_path.get(compiled["output_path"]) == compiled["output"],
            "control link did not consume its fresh object")
    ramulator = by_path.get(product["staged_path"])
    require(ramulator is not None and all(ramulator[key] == product[key] for key in ("sha256", "size_bytes")),
            "control link did not consume the admitted Ramulator product")
    alternate = linked["output"]
    body = receipts.payload(alternate, reader)
    require(MARKER in body and alternate["sha256"] != admission.products["extension"]["sha256"],
            "control extension is not the known different emitted-marker product")
    archives = {row["original_path"]: row["members"] for row in admission.document["external_archives"]}
    mapping = binary.validate_link_map(receipts.payload(linked["link_map"], reader).decode("utf-8"),
        cwd=str(work), archives=archives, required_loads=[product["staged_path"], compiled["output_path"]])
    owned_loads = [name for name in mapping["loads"] if name not in archives
                   and any(Path(name).is_relative_to(root) for root in project_roots)]
    require(sorted(owned_loads) == sorted((product["staged_path"], compiled["output_path"])),
            "control map contains an unplanned source/work input")
    require(base._file_identity(alternate["path"]) == {key: alternate[key] for key in receipts.IDENTITY_FIELDS},
            "control extension changed after its successful link")
    return {"records": [hash_artifacts(output, [path.relative_to(output).as_posix()])[0] for path in paths],
            "compile": compiled, "link": linked, "map_verification": mapping,
            "alternate_product": {key: alternate[key] for key in receipts.IDENTITY_FIELDS},
            "source_derivation": {
                "original_source": known[original_path],
                "retained_original": builder.identity(output / "inputs/gddr6-original.cpp", relative_to=output),
                "derived_source": builder.identity(work / CONTROL_SOURCE, relative_to=output),
                "appended_declaration_sha256": hashlib.sha256(MARKER_DECLARATION).hexdigest()},
            "original_product": admission.products["extension"]}


class Control:
    def __init__(self, args):
        self.args = args
        self.source = base._path(args.source_dir, existing=True)
        self.build = base._path(args.build_dir, existing=True)
        self.managed_path = base._path(args.managed_report, existing=True)
        self.dependency_path = base._path(args.dependency_receipt, existing=True)
        self.output = base._path(args.output_dir)
        require(self.source == ROOT and self.source.is_dir() and self.build.is_dir(),
                "control requires this source checkout and an existing admitted build")
        require(not self.output.exists() and self.output.parent.is_dir()
                and not any(base._overlap(self.output, path) for path in (
                    self.source, self.build, self.managed_path, self.dependency_path)),
                "control output must be fresh and separate from admitted inputs")
        require(type(args.expected_revision) is str and re.fullmatch(r"[0-9a-f]{40}", args.expected_revision),
                "control expected revision is not an exact Git identity")
        require(type(args.dependency_receipt_sha256) is str
                and re.fullmatch(r"[0-9a-f]{64}", args.dependency_receipt_sha256),
                "control dependency receipt pin is not an exact SHA256")
        self.output.mkdir(mode=0o700)
        for name in ("work", "records", "payloads", "inputs", "logs"):
            (self.output / name).mkdir(mode=0o700)
        self.work = self.output / "work"
        for name in ("home", "tmp"):
            (self.work / name).mkdir(mode=0o700)
        self.environment = builder.clean_environment(self.work)
        self.report = {"schema_version": 1, "contract_id": CONTRACT_ID,
            "expected_revision": args.expected_revision,
            "dependency_receipt_sha256": args.dependency_receipt_sha256,
            "state": "running", "outcome": "blocked", "reason": None, "failures": [],
            "native_execution": "not_run", "control_passed": False,
            "alternate_dependency_built": False, "numerical_control_passed": False,
            "original_provenance_rejected": False, "commands": [], "control_counts": None,
            "budget": dict(dependency.BUDGET), "environment": self.environment,
            "managed_population_included": False, "limitations": LIMITATIONS,
            "started_at": base._now(), **dict.fromkeys(dependency.FALSE_CLAIMS, False)}
        self.initial = None
        self.admission = None
        self.frozen_control = None
        self.save()

    def save(self):
        base._write_json(self.output / "report.json", self.report)

    def fail(self, error, stage):
        reason = str(error) or "interrupted"
        failure = {"stage": stage, "reason": reason}
        if not self.report["failures"] or self.report["failures"][-1] != failure:
            self.report["failures"].append(failure)
        if self.report["reason"] is None:
            self.report["reason"] = reason
        self.report["outcome"] = "fail" if any(row.get("process_started") for row in self.report["commands"]) else "blocked"
        self.report["control_passed"] = False

    def snapshot(self):
        require(self.admission is not None, "control dependency admission is absent")
        return {"checkout": collect_source(self.source),
            "source_files": hash_artifacts(self.source, self.source_names),
            "build": hash_artifacts(self.build, self.build_names),
            "managed_report": base._file_identity(self.managed_path),
            "managed_snapshots": hash_artifacts(self.managed_path.parent, self.managed_snapshots),
            "dependency_admission": self.admission.verify_stable(self.tools)}

    def stable(self):
        require(self.snapshot() == self.initial, "control admitted inputs changed")
        if self.frozen_control is not None:
            require(hash_artifacts(self.output, [row["path"] for row in self.frozen_control]) == self.frozen_control,
                    "control compiled products or receipts changed")

    def command(self, name, argv, *, native=False):
        self.stable()
        environment = dict(self.environment)
        if native:
            environment.update(VORTEX_DRIVER="simx", PERF="1", LD_LIBRARY_PATH=os.pathsep.join((
                str(self.work), str(self.build / "sw/runtime"))))
        row = {"id": name, "argv": list(map(str, argv)), "cwd": str(self.work),
            "environment": environment, "native_process": native,
            "timeout_seconds": 180 if native else 1800, "log": "logs/" + name + ".log",
            "process_started": None}
        self.report["commands"].append(row)
        previous_native_execution = self.report["native_execution"]
        if native:
            self.report["native_execution"] = preflight.native_execution_state(previous_native_execution, None)
        self.save()
        try:
            row.update(run_bounded(row["argv"], self.work, environment, self.output / row["log"],
                timeout_seconds=row["timeout_seconds"], resource_paths=(self.source, self.build, self.output,
                    self.managed_path.parent, self.dependency_path.parent), **BUDGET))
        except (OSError, ValueError, RuntimeError, TypeError, KeyboardInterrupt) as error:
            row.update(outcome="fail", reason=str(error) or "interrupted")
            self.fail(error, "execution")
            try:
                if (self.output / row["log"]).is_file():
                    identity = builder.identity(self.output / row["log"])
                    row.update(log_sha256=identity["sha256"], log_size_bytes=identity["size_bytes"])
            except (OSError, ValueError, RuntimeError) as log_error:
                row["log_identity_error"] = str(log_error)
            self.save()
            raise
        if native:
            self.report["native_execution"] = preflight.native_execution_state(
                previous_native_execution, row.get("process_started"))
        self.save()
        require(row.get("process_started") is True and row.get("cleanup_complete") is True
                and row.get("outcome") == "pass" and type(row.get("exit_code")) is int
                and row["exit_code"] == 0 and row.get("reason") is None,
                name + ": command failed: " + str(row.get("reason")))
        descriptor = {"path": row["log"], "sha256": row["log_sha256"], "size_bytes": row["log_size_bytes"]}
        text = receipts.descriptor(descriptor, receipts.PacketReader(self.output)).decode("utf-8")
        self.stable()
        return text

    def admit(self):
        require(all(shutil.disk_usage(path).free >= BUDGET["min_free_bytes"] for path in (
            self.source, self.build, self.output, self.managed_path.parent, self.dependency_path.parent)),
            "dependency substitution control requires 15 GiB disk reserve")
        require((available_memory_bytes() or 0) >= BUDGET["max_rss_bytes"],
                "dependency substitution control requires 4 GiB available memory")
        managed = probe.managed_json(self.managed_path,
                                    dependency_receipt_sha256=self.args.dependency_receipt_sha256)
        probe.managed_mode(managed, expected_revision=self.args.expected_revision,
                           dependency_receipt_sha256=self.args.dependency_receipt_sha256)
        variants = [row for row in managed["variants"] if row.get("build_dir") == str(self.build)]
        require(len(variants) == 1 and variants[0].get("format") == FORMAT
                and variants[0].get("backend") == "simx" and variants[0].get("outcome") == "pass",
                "control requires the complete admitted FP16 model")
        variant = variants[0]
        prefix = "snapshots/simx-fp16-build-binding.json"
        binding = probe.retained_json(self.managed_path.parent, variant["binding"], prefix)
        require(preflight.qualification_id(binding) == variant["build_binding_sha256"]
                and binding.get("contract_id") == dependency.MANAGED_CONTRACT_ID
                and binding.get("dependency_receipt_sha256") == self.args.dependency_receipt_sha256
                and variant.get("dependency_receipt_sha256") == self.args.dependency_receipt_sha256,
                "control managed build binding differs")
        manifest.false_claims(binding)
        require(binding.get("format") == FORMAT and binding.get("backend") == "simx"
                and all(binding.get(name) == variant.get(name) and name in binding for name in (
                    "application_build_records", "dependency_model_link")),
                "control application/model admission differs")
        self.tools = probe.retained_json(self.managed_path.parent, managed["tools_before"], "snapshots/tools-before.json")
        selected_source = probe.retained_json(self.managed_path.parent, managed["source_before"], "snapshots/source-before.json")
        require(collect_source(self.source) == selected_source["checkout"]
                and selected_source["checkout"]["revision"] == self.args.expected_revision,
                "control source differs from the managed checkout")
        base._source_ok(selected_source, False)
        require(hash_artifacts(self.source, [row["path"] for row in selected_source["files"]]) == selected_source["files"],
                "control source bytes differ from the admitted build")
        self.build_names = preflight.artifacts(self.build, dependency=True)
        require(hash_artifacts(self.build, self.build_names) == variant["artifacts_before"] == variant["artifacts_after"]
                and binding.get("artifacts") == variant["artifacts_before"],
                "control build artifacts differ from the admitted products")
        self.admission = admission_module.Admission(self.dependency_path, self.args.dependency_receipt_sha256,
            source=self.source, expected_revision=self.args.expected_revision)
        self.admission.verify_stable(self.tools)
        self.original_libraries = preflight.expected_libraries(self.source, self.build)
        require(self.original_libraries == variant["expected_loaded_libraries"],
                "control original loader paths differ from the admitted build")
        self.helpers = preflight.loaded_helpers()
        self.source_names = sorted({row["path"] for row in selected_source["files"]}
            | {row["path"] for row in self.helpers} | set(SOURCE_FILES))
        self.managed_snapshots = ["snapshots/source-before.json", "snapshots/tools-before.json", prefix]
        self.initial = self.snapshot()
        self.report.update(inputs_before=self.initial, original_libraries=self.original_libraries,
            managed_build_binding_sha256=variant["build_binding_sha256"], helper_sources=self.helpers)
        for row in self.helpers:
            destination = self.output / "inputs" / row["path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            builder.stage_file(self.source / row["path"], destination)
        for label, path in (("managed-report.json", self.managed_path), ("dependency-report.json", self.dependency_path)):
            builder.stage_file(path, self.output / "inputs" / label)
        return managed

    def execute(self):
        try:
            self.admit()
            source_derivation = prepare_source(self.source, self.output, self.work, self.admission)
            self.report["source_derivation"] = source_derivation
            tools = self.admission.document["tools"]
            config = {"schema_version": 1, "contract_id": recorder.CONTRACT_ID,
                "contract_sha256": dependency.contract_hash(), "roots": {
                    "sources": str(self.source / "third_party"), "build": str(self.work),
                    "receipts": str(self.output / "records"), "payloads": str(self.output / "payloads")},
                "tools": {name: tools[name] for name in recorder.TOOLS}}
            config_path = self.output / "tool-config.json"
            config_descriptor = builder.write_json(config_path, config)
            self.report["tool_config"] = dict(config_descriptor, path="tool-config.json")
            commands = recipes(self.source, self.work)
            for role in ("compile", "link"):
                self.command(role + "-alternate-extension", [*builder.launcher(config_path,
                    config_descriptor["sha256"], tools, "g++", role), *commands[role]])
            verified = verify_records(self.output, config, config_descriptor["sha256"], source=self.source,
                work=self.work, managed_work=self.build.parent, admission=self.admission, tools=tools)
            require(verified["source_derivation"] == source_derivation,
                    "control source derivation changed during compilation")
            self.report.update(alternate_dependency_built=True, dependency_control=verified)
            frozen_names = ["tool-config.json", "work/" + CONTROL_SOURCE, "work/gddr6-control.o",
                "work/gddr6-control.o.d", "work/gddr6-control.o.p06-before.d", "work/" + LIBRARY,
                "work/control.map"]
            frozen_names.extend(path.relative_to(self.output).as_posix()
                for name in ("records", "payloads", "inputs")
                for path in (self.output / name).rglob("*") if path.is_file())
            # The recorder uses <object>.d when the invocation has no -MF.
            self.frozen_control = hash_artifacts(self.output, sorted(frozen_names))
            self.report["control_products_before"] = self.frozen_control
            control_binding = {"contract_id": CONTRACT_ID, "expected_revision": self.args.expected_revision,
                "dependency_receipt_sha256": self.args.dependency_receipt_sha256,
                "managed_build_binding_sha256": self.report["managed_build_binding_sha256"],
                "inputs_sha256": dependency.digest(self.initial),
                "source_derivation_sha256": dependency.digest(source_derivation),
                "alternate_product": verified["alternate_product"], "original_product": verified["original_product"],
                "format": FORMAT, "policy": POLICY, "managed_population_included": False,
                **dict.fromkeys(dependency.FALSE_CLAIMS, False)}
            binding_id = dependency.digest(control_binding)
            self.report.update(control_binding=control_binding, control_binding_sha256=binding_id)
            identity = manifest.process_identity(FORMAT, POLICY, binding_id)
            app = self.build / manifest.APP
            text = self.command("run-alternate-extension", [app / "ai_counter_preflight", lifetime.APP_FLAG,
                "--policy", POLICY, "--module", app / "kernel.vxbin", "--qualification-id", binding_id,
                "--sample-id", identity["sample_id"], "--pair-index", "0", "--phase", "warmup"], native=True)
            contract = manifest.load_contract(self.source)
            case = next(row for row in manifest.select_cases(contract, self.source) if row["format"] == FORMAT)
            checked = verify_observation(text, contract=contract, case=case, binding_id=binding_id,
                original_libraries=self.original_libraries, alternate_path=str(self.work / LIBRARY))
            self.report.update(checked, numerical_control_passed=True, original_provenance_rejected=True,
                               outcome="pass")
        except (OSError, ValueError, RuntimeError, KeyError, TypeError, KeyboardInterrupt) as error:
            self.fail(error, "execution")
        finally:
            if self.initial is not None:
                try:
                    self.stable()
                    self.report["inputs_after"] = self.snapshot()
                    if self.frozen_control is not None:
                        self.report["control_products_after"] = hash_artifacts(self.output,
                            [row["path"] for row in self.frozen_control])
                except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
                    self.fail(error, "final-stability")
            try:
                retained = []
                for path in sorted(self.output.rglob("*")):
                    require(not path.is_symlink(), "control retained data contains a symlink")
                    if path.is_dir() or path == self.output / "report.json":
                        continue
                    retained.append(builder.identity(path, relative_to=self.output))
                    require(len(retained) <= 20000, "control retained file inventory exceeds its bound")
                self.report["retained_files"] = retained
                require(sum(row["size_bytes"] for row in self.report["retained_files"]) <= dependency.MAX_PACKET_BYTES,
                        "control retained data exceeds the packet byte bound")
            except (OSError, ValueError, RuntimeError) as error:
                self.fail(error, "final-retention")
            self.report["control_passed"] = self.report["outcome"] == "pass" and all(self.report[name] is True
                for name in ("alternate_dependency_built", "numerical_control_passed", "original_provenance_rejected"))
            self.report.update(state="finished", finished_at=base._now())
            self.save()
        return self.report


def execute(args):
    return Control(args).execute()


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=ROOT)
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("--managed-report", type=Path, required=True)
    parser.add_argument("--dependency-receipt", type=Path, required=True)
    parser.add_argument("--dependency-receipt-sha256", required=True)
    parser.add_argument("--expected-revision", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv=None):
    try:
        result = execute(argument_parser().parse_args(argv))
        print(json.dumps({name: result[name] for name in ("outcome", "reason", "native_execution",
            "control_passed", "alternate_dependency_built", "numerical_control_passed",
            "original_provenance_rejected", "control_counts")}, sort_keys=True))
        return 0 if result["control_passed"] else 1
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        print(json.dumps({"outcome": "blocked", "reason": str(error), "control_passed": False,
                         **dict.fromkeys(dependency.FALSE_CLAIMS, False)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    sys.exit(main())
