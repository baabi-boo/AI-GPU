#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run a host-only diagnostic of published dependency recipes, without staging."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True

REVISION = "5527cb062e10dfff3266022d138dd7cdf63f5e5c"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_project_loads(checked, expected_inputs, *, source, workspace, external_archives=()):
    loads = Counter(checked["loads"])
    require(all(loads[item["path"]] == 1 for item in expected_inputs),
            "map omits or repeats an actual direct input")
    external = set(external_archives)
    owned = [name for name in checked["loads"] if name not in external
             and any(Path(name).is_relative_to(root) for root in (source, workspace))]
    require(sorted(owned) == sorted(item["path"] for item in expected_inputs),
            "map contains an unplanned source/workspace input")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "run"))
    parser.add_argument("--helpers", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--repositories", type=Path)
    parser.add_argument("--cmake", type=Path)
    args = parser.parse_args()
    helpers = args.helpers.absolute()
    require(helpers.resolve(strict=True) == helpers, "helper checkout must be canonical")
    require(subprocess.check_output(["git", "-C", str(helpers), "rev-parse", "HEAD"]).decode().strip()
            == REVISION, "helper checkout is not the reviewed published revision")
    require(not subprocess.check_output(["git", "-C", str(helpers), "status", "--porcelain=v1"]),
            "helper checkout has changed or untracked inputs")
    sys.path.insert(0, str(helpers / "ci/project"))
    build = importlib.import_module("p06_dependency_build")
    receipt = importlib.import_module("p06_dependency_receipt")
    binary = importlib.import_module("p06_dependency_binary")
    sources = importlib.import_module("p06_dependency_sources")
    graph = importlib.import_module("p06_dependency_graph")
    contract = importlib.import_module("p06_dependency_contract")
    recorder = importlib.import_module("p06_dependency_record")
    process = importlib.import_module("baseline_process")
    preflight = importlib.import_module("preflight")
    for module in (build, receipt, binary, sources, graph, contract, recorder, process, preflight):
        require(Path(module.__file__).resolve().is_relative_to(helpers / "ci/project"),
                "diagnostic imported a helper outside the frozen checkout")
    workspace = build.canonical(args.workspace)
    require(not build.base._overlap(workspace, helpers), "workspace overlaps frozen helpers")
    output = workspace / "evidence"
    source_root = workspace / "dependency-sources"
    build_root = workspace / "dependency-build"
    prepared = workspace / "prepared.json"
    report_path = output / "host-diagnostic.json"

    def save(value):
        build.base._write_json(report_path, value)

    def retain(path, relative):
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        build.stage_file(path, destination)
        return build.identity(destination, relative_to=output)

    def resources():
        observed = {"free_disk_bytes": shutil.disk_usage(workspace).free,
                    "available_memory_bytes": preflight.available_memory_bytes()}
        require(observed["free_disk_bytes"] >= contract.BUDGET["min_free_bytes"],
                "diagnostic requires the unchanged15GiB disk reserve")
        require((observed["available_memory_bytes"] or 0) >= contract.BUDGET["max_rss_bytes"],
                "diagnostic requires the unchanged4GiB available-memory entry bound")
        return observed

    if args.phase == "prepare":
        require(args.repositories is not None and args.cmake is not None,
                "preparation requires explicit Git object repositories and CMake")
        require(not os.path.lexists(workspace), "diagnostic workspace must be fresh")
        workspace.mkdir(mode=0o700)
        initial_resources = resources()
        output.mkdir(mode=0o700)
        for name in ("logs", "records", "payloads", "launchers", "helpers", "sources", "build-inputs"):
            (output / name).mkdir(mode=0o700)
        build_root.mkdir(mode=0o700)
        for name in ("home", "tmp", "extension"):
            (build_root / name).mkdir(mode=0o700)
        environment = build.clean_environment(build_root)
        tools = {}
        for name in build.HOST_TOOLS:
            path = str(build.canonical(args.cmake, existing=True)) if name == "cmake" else shutil.which(name, path=environment["PATH"])
            require(path is not None and os.access(path, os.X_OK), "selected host tool absent: " + name)
            tools[name] = recorder.file_identity(path)
        require(tools["python3"] == recorder.file_identity(sys.executable), "launcher interpreter differs")
        repositories = {name: args.repositories / name for name in contract.PINS}
        manifest = sources.materialize_sources(repositories, source_root)
        plan = graph.source_plan(manifest, lambda component, path: (source_root / component / path).read_bytes())
        helper_sources = build.helper_inventory()
        for row in helper_sources:
            retain(helpers / row["path"], "helpers/" + row["path"])
        for component in manifest["sources"]:
            for row in component["files"]:
                name = component["name"] + "/" + row["path"]
                retain(source_root / name, "sources/" + name)
        config = {"schema_version": 1, "contract_id": recorder.CONTRACT_ID,
                  "contract_sha256": contract.contract_hash(), "roots": {
                      "sources": str(source_root), "build": str(build_root),
                      "receipts": str(output / "records"), "payloads": str(output / "payloads")},
                  "tools": {name: tools[name] for name in recorder.TOOLS}}
        config_identity = build.write_json(output / "tool-config.json", config)
        for name, role in (("ar", "archive"), ("ranlib", "index")):
            path = output / "launchers" / (name + ".sh")
            path.write_text("#!/bin/sh\nexec " + shlex.join(build.launcher(output / "tool-config.json",
                config_identity["sha256"], tools, name, role)) + ' "$@"\n')
            path.chmod(0o755)
        projection = {"paths": {"source": str(helpers), "workspace": str(workspace),
                "sources": str(source_root), "build": str(build_root), "output": str(output)},
            "source_manifest": manifest, "source_plan": plan, "tools": tools,
            "environment": environment, "tool_config": build.identity(output / "tool-config.json", relative_to=output),
            "helper_sources": helper_sources, "driver": build.identity(Path(__file__).resolve()),
            "helper_revision": REVISION, "resources_before_prepare": initial_resources,
            "budget": dict(contract.BUDGET), "commands": [], "stability_checks": [],
            "generated_inputs": [], "compile_database": None, "cmake_configuration": {}}
        build.write_json(prepared, projection)
        result = {"schema_version": 1, "scope": "host-dependency-diagnostic-only",
            "state": "prepared", "outcome": "not_run", "reason": None, "failures": [],
            "host_diagnostic_passed": False, "fresh_dependency_build_passed": False,
            "dependency_source_to_loaded_binary_verified": False, "native_execution": "not_run",
            "formal_preparation_executed": False, "measurement_staging_executed": False,
            "cache_restoration_claimed": False, **dict.fromkeys(contract.FALSE_CLAIMS, False),
            "prepared": build.identity(prepared), "observations": projection,
            "limitations": ["This is neither a formal dependency receipt nor the hosted native original.",
                "Compiler execution and inert graph checks have distinct recorded outcomes.",
                "No RISC-V toolchain, measurement staging, managed build or native lifetime process is selected.",
                "CMake is selected by its explicit local identity; its binary is not qualified.",
                *contract.LIMITATIONS]}
        save(result)
        print(json.dumps({"state": "prepared", "workspace": str(workspace),
            "source_files": manifest["total_files"], "planned_translation_units": len(plan),
            "native_execution": "not_run", "fresh_dependency_build_passed": False}, sort_keys=True))
        return 0

    require(prepared.is_file(), "prepared diagnostic inputs are absent")
    result = build.read_json(report_path)
    require(result["state"] == "prepared" and result["outcome"] == "not_run", "diagnostic already attempted")
    require(build.identity(prepared) == result["prepared"], "prepared inputs changed")
    observed = build.read_json(prepared)
    require(observed == result["observations"], "prepared projection changed")
    result["observations"] = observed
    require(build.identity(Path(__file__).resolve()) == observed["driver"], "diagnostic driver changed")
    with (workspace / "execution-started").open("x") as stream:
        stream.write("single diagnostic attempt\n")
    result.update(state="running", outcome="blocked")
    config_path = output / "tool-config.json"
    config, raw_reader = None, None
    environment, tools = {}, {}

    def records():
        paths = sorted((output / "records").glob("*.json"))
        require(len(paths) <= contract.MAX_RECORDS, "diagnostic record bound exceeded")
        return [build.read_json(path) for path in paths]

    def stable(label):
        require(build.helper_inventory() == observed["helper_sources"], "frozen diagnostic helpers changed")
        require(all(recorder.file_identity(row["path"]) == row for row in tools.values()), "selected host tool changed")
        generated = build.generated_sources(records(), source_root)
        check = sources.verify_sources(observed["source_manifest"], source_root, generated_files=generated)
        observed["stability_checks"].append({"label": label, "sources": check})

    def command(name, argv, cwd, timeout=1800):
        require(name not in {row["id"] for row in observed["commands"]}, "command repeated")
        stable("before-" + name)
        row = {"id": name, "argv": list(map(str, argv)), "cwd": str(cwd),
            "environment": environment, "timeout_seconds": timeout, "log": "logs/" + name + ".log",
            "process_started": None}
        observed["commands"].append(row)
        save(result)
        row.update(process.run_bounded(row["argv"], cwd, environment, output / row["log"],
            timeout_seconds=timeout, min_free_bytes=contract.BUDGET["min_free_bytes"],
            max_rss_bytes=contract.BUDGET["max_rss_bytes"], max_log_bytes=contract.BUDGET["max_log_bytes"],
            resource_paths=(workspace, output, helpers)))
        save(result)
        require(row.get("process_started") is True and row.get("outcome") == "pass"
                and type(row.get("exit_code")) is int and row["exit_code"] == 0
                and row.get("reason") is None and row.get("cleanup_complete") is True,
                "host diagnostic command failed: " + name)
        stable("after-" + name)
        save(result)
        return (output / row["log"]).read_text(encoding="utf-8")

    def retain_generated():
        selected = []
        for path in (build_root / "ramulator").rglob("*"):
            if path.is_file() and (path.suffix in (".cmake", ".make", ".txt", ".json", ".h", ".hpp",
                                                  *recorder.SOURCE_SUFFIXES) or path.name == "Makefile"):
                selected.append(path)
        for path in sorted(selected):
            name = "build-inputs/" + path.relative_to(build_root / "ramulator").as_posix()
            row = retain(path, name)
            observed["generated_inputs"].append(row)
            if name == "build-inputs/compile_commands.json":
                observed["compile_database"] = row

    def verify_graph(rows):
        recorder_identity = recorder.file_identity(build.RECORDER)
        for row in rows:
            receipt._validate_record(row, config, observed["tool_config"]["sha256"], raw_reader, recorder_identity)
        require(Counter(row["role"] for row in rows) == {"compile": 406, "archive": 3, "index": 2, "link": 2},
                "complete diagnostic operation population differs")
        plan, compiles, outputs = receipt._verify_compile_graph(observed, rows, config, raw_reader)
        receipt._verify_generated_build(observed, rows, raw_reader)
        observed["verified_compile_count"] = len(compiles)
        observed["verified_object_count"] = len(outputs)
        archive_by_path, archives = {}, {}
        for name in ("softfloat", "yaml-cpp", "spdlog"):
            selected = [compiles[str(source_root / row["source"])] for row in plan if row["component"] == name]
            planned = [row for row in plan if row["component"] == name]
            members = [{"name": item["archive_member"], "sha256": row["output"]["sha256"],
                        "size_bytes": row["output"]["size_bytes"]} for item, row in zip(planned, selected)]
            path = (source_root / "softfloat/build/Linux-x86_64-GCC/softfloat.a" if name == "softfloat"
                    else build_root / "ramulator/_deps" / (name + "-build") / ("lib" + name + ".a"))
            parsed = binary.validate_archive(path.read_bytes(), members)
            creates = [row for row in rows if row["role"] == "archive" and row["output_path"] == str(path)]
            require(len(creates) == 1, "archive lacks its unique actual creator")
            create = creates[0]
            expected = ["crs" if name == "softfloat" else "qc", str(path), *[row["output_path"] for row in selected]]
            actual = [create["requested_arguments"][0], *[receipt.absolute(word, create["cwd"])
                      for word in create["requested_arguments"][1:]]]
            require(actual == expected and create["inputs_before"] == [row["output"] for row in selected]
                    and all(row["finished_ns"] <= create["started_ns"] for row in selected),
                    "archive changes selected object order, bytes or prerequisites")
            binary.validate_archive(receipt.payload(create["output"], raw_reader), members)
            indexed = [row for row in rows if row["role"] == "index" and row["output_path"] == str(path)]
            final = create
            if name == "softfloat":
                require(not indexed, "SoftFloat unexpectedly indexed separately")
            else:
                require(len(indexed) == 1 and indexed[0]["output_before"] == create["output"]
                        and create["finished_ns"] <= indexed[0]["started_ns"], "index prerequisite differs")
                final = indexed[0]
            require((parsed["sha256"], parsed["size_bytes"])
                    == (final["output"]["sha256"], final["output"]["size_bytes"]), "final archive bytes differ")
            archive_by_path[str(path)] = members
            archives[name] = {"path": str(path), "members": members, "output": final["output"],
                              "finished_ns": final["finished_ns"]}
        observed["verified_archives"] = archives
        links = {}
        for name in ("ramulator", "extension"):
            path = (source_root / "ramulator/libramulator.so" if name == "ramulator"
                    else build_root / "extension/libramulator-vortex.so")
            matching = [row for row in rows if row["role"] == "link" and row["output_path"] == str(path)]
            require(len(matching) == 1, "shared product lacks a unique actual link")
            link = matching[0]
            require(recorder.file_identity(path) == {key: value for key, value in link["output"].items() if key != "payload"},
                    "actual shared output changed")
            selected = [compiles[str(source_root / row["source"])] for row in plan if row["component"] == name]
            expected_inputs = [row["output"] for row in selected]
            completed = [row["finished_ns"] for row in selected]
            if name == "ramulator":
                expected_inputs += [archives[key]["output"] for key in ("yaml-cpp", "spdlog")]
                completed += [archives[key]["finished_ns"] for key in ("yaml-cpp", "spdlog")]
                required = [archives[key]["path"] for key in ("yaml-cpp", "spdlog")]
                required_loads = []
            else:
                expected_inputs.append(links["ramulator"]["output"])
                completed.append(links["ramulator"]["finished_ns"])
                required = []
                required_loads = [str(source_root / "ramulator/libramulator.so")]
            require(Counter(contract.digest(row) for row in expected_inputs)
                    == Counter(contract.digest(row) for row in link["inputs_before"])
                    and all(value <= link["started_ns"] for value in completed),
                    "link changed observed inputs or prerequisite chronology")
            text = receipt.payload(link["link_map"], raw_reader).decode("utf-8")
            parsed = binary.parse_link_map(text, cwd=link["cwd"])
            for member in parsed["selected_members"]:
                if member["archive"] in archive_by_path:
                    continue
                external = Path(member["archive"])
                require(external.name in ("libgcc.a", "libgcc_eh.a"), "unreviewed compiler-support archive")
                identifier = "locate-" + external.name.replace(".", "-")
                resolved = command(identifier, [tools["g++"]["path"], "-print-file-name=" + external.name],
                                   build_root, timeout=30).strip()
                require(receipt.absolute(resolved) == str(external), "compiler selected a different support archive")
                descriptor = retain(external.resolve(), "external/" + external.name)
                external_parsed = binary.parse_archive(raw_reader(descriptor["path"]))
                archive_by_path[str(external)] = external_parsed["members"]
                observed.setdefault("external_archives", []).append({"path": str(external),
                    "descriptor": descriptor, "members": external_parsed["members"], "resolution_command": identifier})
            checked = binary.validate_link_map(text, cwd=link["cwd"], archives=archive_by_path,
                required_archives=required, required_loads=required_loads)
            validate_project_loads(checked, expected_inputs, source=helpers, workspace=workspace,
                external_archives=[row["path"] for row in observed.get("external_archives", [])])
            links[name] = {"output": link["output"], "finished_ns": link["finished_ns"], "map": checked,
                           "record_id": link["id"]}
        observed["verified_links"] = links
        receipt._verify_outer_commands(observed, config, raw_reader)

    def failure(error, stage):
        message = str(error) or "interrupted"
        result["failures"].append({"stage": stage, "reason": message})
        if result["reason"] is None:
            result["reason"] = message
        result["outcome"] = ("fail" if any(row.get("process_started") is True
                                          for row in observed["commands"]) else "blocked")
        result["host_diagnostic_passed"] = False

    try:
        save(result)
        environment, tools = observed["environment"], observed["tools"]
        config = build.read_json(config_path)
        require(build.identity(config_path, relative_to=output) == observed["tool_config"],
                "recorder configuration changed")
        raw_reader = receipt.PacketReader(output)
        observed["resources_before_execution"] = resources()
        stable("sources-frozen")
        arguments, cwd = build.softfloat_command(source_root, tools, config_path, observed["tool_config"]["sha256"])
        command("softfloat", arguments, cwd)
        arguments, settings = build.cmake_command(source_root, build_root, tools, config_path,
            observed["tool_config"]["sha256"], output / "launchers/ar.sh", output / "launchers/ranlib.sh")
        observed["cmake_configuration"] = settings
        command("ramulator-configure", arguments, build_root, timeout=120)
        command("ramulator-build", [tools["cmake"]["path"], "--build", str(build_root / "ramulator"),
                "--target", "ramulator", "--parallel", "2", "--verbose"], build_root)
        compile_args, link_args = build.extension_commands(source_root, build_root, tools, config_path,
                                                          observed["tool_config"]["sha256"])
        command("extension-compile", compile_args, build_root / "extension")
        command("extension-link", link_args, build_root / "extension")
        retain_generated()
        verify_graph(records())
        result.update(outcome="pass", host_diagnostic_passed=True)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, KeyboardInterrupt) as error:
        failure(error, "execution-or-inert-check")
    finally:
        for label, operation in (("final-stability", lambda: stable("final")),):
            try:
                operation()
            except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
                failure(error, label)
        try:
            rows = records()
            observed["record_identities"] = [build.identity(path, relative_to=output)
                for path in sorted((output / "records").glob("*.json"))]
            observed["actual_record_roles"] = dict(Counter(row["role"] for row in rows))
            observed["passing_record_roles"] = dict(Counter(row["role"] for row in rows if row["outcome"] == "pass"))
            observed["records_finished"] = all(row["state"] == "finished" for row in rows)
            observed["generated_sources"] = build.generated_sources(rows, source_root)
            retained = [build.identity(path, relative_to=output) for path in sorted(output.rglob("*"))
                        if path.is_file() and path != report_path]
            require(sum(row["size_bytes"] for row in retained) <= contract.MAX_PACKET_BYTES,
                    "diagnostic retention exceeds the unchanged1GiB packet bound")
            observed["retained_files"] = retained
            observed["retained_bytes"] = sum(row["size_bytes"] for row in retained)
        except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
            failure(error, "final-record-inventory")
        result["state"] = "finished"
        save(result)
    print(json.dumps({key: result[key] for key in ("state", "outcome", "reason", "host_diagnostic_passed",
        "fresh_dependency_build_passed", "native_execution")}, sort_keys=True))
    return 0 if result["host_diagnostic_passed"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        print(json.dumps({"outcome": "blocked", "reason": str(error), "scope": "host-dependency-diagnostic-only",
            "fresh_dependency_build_passed": False, "native_execution": "not_run"}, sort_keys=True))
        raise SystemExit(1)
