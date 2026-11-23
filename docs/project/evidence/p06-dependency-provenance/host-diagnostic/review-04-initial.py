#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Independently review retained diagnostic data with published trusted helpers."""

import argparse
from collections import Counter
import hashlib
import importlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import time
from unittest import mock


REVISION = "146253db8407e21aaef70e05f3f0dd3c7f5f6d33"
TREE = "0407e9c5250b410d399af8cb3ea32f06dc3dea17"
PREPARED_SHA256 = "8a5d86be8362bcd1cdb3083f403d0ffb9600d1b2d34410aefb1894b434646a82"
CONFIG_SHA256 = "9e2b57d643128c9a91f16e3afd5edb926b3220bcf1796ffbd0b004f03500b9d0"
DRIVER_SHA256 = "c2aeaf524fd134b4c7eca6544b9d03c51bbe374dabde5239fa0c4c4372c3ddd0"
MANIFEST_SHA256 = "c677abd7a1cbb78cab13c23b40a92a83be427e06c3dffa40419de92b8697cd2e"
PLAN_SHA256 = "f479cc6ed3ee4d4dd7fd305bc45943af33a3a2ba9069da48eebe627c5f817570"


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def sha256(body):
    return hashlib.sha256(body).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--helpers", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--expected-report-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started = time.monotonic()
    helpers, workspace = args.helpers.resolve(strict=True), args.workspace.resolve(strict=True)
    output = workspace / "evidence"

    def git(*words):
        return subprocess.check_output(["git", "-C", str(helpers), *words])

    require(git("rev-parse", "HEAD").decode().strip() == REVISION, "trusted helper revision differs")
    require(git("rev-parse", "HEAD^{tree}").decode().strip() == TREE, "trusted helper tree differs")
    require(not git("status", "--porcelain=v1"), "trusted helper checkout is dirty")
    require(not list((helpers / "ci/project").rglob("*.pyc")), "trusted helper checkout contains bytecode")
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(helpers / "ci/project"))
    receipt = importlib.import_module("p06_dependency_receipt")
    binary = importlib.import_module("p06_dependency_binary")
    contract = importlib.import_module("p06_dependency_contract")
    recorder = importlib.import_module("p06_dependency_record")
    graph = importlib.import_module("p06_dependency_graph")
    sources = importlib.import_module("p06_dependency_sources")
    for module in (receipt, binary, contract, recorder, graph, sources):
        path = Path(module.__file__).resolve(strict=True)
        require(path.is_relative_to(helpers / "ci/project"), "trusted module origin differs")
        require(path.read_bytes() == git("show", REVISION + ":" + path.relative_to(helpers).as_posix()),
                "trusted module bytes differ from published Git blob")
    reader = receipt.PacketReader(output)
    report_bytes = reader("host-diagnostic.json")
    require(sha256(report_bytes) == args.expected_report_sha256, "caller-pinned original report differs")
    report = receipt.decode(report_bytes)
    require(report["state"] == "finished", "original diagnostic is still running")
    require(report["scope"] == "host-dependency-diagnostic-only", "original diagnostic scope differs")
    require(report["native_execution"] == "not_run", "diagnostic invents native execution")
    for name in (*contract.FALSE_CLAIMS, "fresh_dependency_build_passed",
                 "dependency_source_to_loaded_binary_verified", "formal_preparation_executed",
                 "measurement_staging_executed", "cache_restoration_claimed"):
        require(report[name] is False, "diagnostic promotes a false claim: " + name)
    document = report["observations"]
    require(document["helper_revision"] == REVISION, "original helper revision differs")
    require(document["paths"] == {"source": str(helpers), "workspace": str(workspace),
            "sources": str(workspace / "dependency-sources"), "build": str(workspace / "dependency-build"),
            "output": str(output)}, "diagnostic roots differ from selected original")
    require(document["budget"] == contract.BUDGET
            and all(type(value) is int for value in document["budget"].values()), "original budgets differ")
    prepared_bytes = (workspace / "prepared.json").read_bytes()
    require(sha256(prepared_bytes) == PREPARED_SHA256 == report["prepared"]["sha256"],
            "sealed preparation differs")
    prepared = receipt.decode(prepared_bytes)
    require(prepared["driver"]["sha256"] == DRIVER_SHA256, "sealed driver differs")
    for key in ("paths", "source_manifest", "source_plan", "tools", "environment", "tool_config",
                "helper_sources", "driver", "helper_revision", "budget", "resources_before_prepare"):
        require(document[key] == prepared[key], "sealed input changed: " + key)
    require(contract.digest(document["source_manifest"]) == MANIFEST_SHA256, "source manifest pin differs")
    require(contract.digest(document["source_plan"]) == PLAN_SHA256, "source plan pin differs")
    require(len(document["helper_sources"]) == 18 and len(document["tools"]) == 7,
            "selected helper/tool population differs")
    helper_identities = {}
    for row in document["helper_sources"]:
        name = receipt.relative(row["path"])
        require(name.startswith("ci/project/") and name.endswith(".py"), "helper path differs")
        body = git("show", REVISION + ":" + name)
        require(body == (helpers / name).read_bytes(), "current helper bytes differ")
        require(sha256(body) == row["sha256"] and len(body) == row["size_bytes"], "frozen helper differs")
        helper_identities[name] = row["sha256"]

    result = {"schema_version": 1, "scope": "independent-inert-host-diagnostic-review",
        "trusted_revision": REVISION, "trusted_tree": TREE,
        "original_report": {"sha256": sha256(report_bytes), "size_bytes": len(report_bytes)},
        "prepared_sha256": PREPARED_SHA256, "config_sha256": CONFIG_SHA256,
        "driver_sha256": DRIVER_SHA256, "source_manifest_sha256": MANIFEST_SHA256,
        "source_plan_sha256": PLAN_SHA256, "trusted_helper_sha256": helper_identities,
        "original_outcome": report["outcome"], "original_reason": report["reason"],
        "review_outcome": "blocked", "full_selected_graph_verified": False,
        "retained_code_executed": False, "native_execution": "not_run",
        **dict.fromkeys(contract.FALSE_CLAIMS, False),
        "limitations": [
            "This reviews retained diagnostic consistency, not formal preparation, staging, managed builds or native loader joins.",
            "Caller-pinned report and retained data do not authenticate a producer or rebuild the compiler and system inputs.",
            "Current trusted published helpers execute; retained helpers, commands, source and binary payloads remain data.",
            "Before/after hashing does not provide protection against malicious concurrent filesystem writers.",
        ]}
    try:
        with mock.patch.object(subprocess, "Popen", side_effect=AssertionError("inert review cannot launch a process")):
            inventory_rows = document["retained_files"]
            names = [row["path"] for row in inventory_rows]
            require(names == sorted(set(names)) and len(names) <= 20000, "retained inventory differs")
            require(sum(row["size_bytes"] for row in inventory_rows) <= contract.MAX_PACKET_BYTES,
                    "retained packet exceeds its bound")
            actual_names = []
            for directory, directories, files in os.walk(output, followlinks=False):
                for name in directories:
                    require(stat.S_ISDIR((Path(directory) / name).lstat().st_mode), "retained directory is not ordinary")
                for name in files:
                    path = Path(directory) / name
                    status = path.lstat()
                    require(stat.S_ISREG(status.st_mode) and status.st_nlink == 1, "retained file is not ordinary")
                    if path.name != "host-diagnostic.json" or path.parent != output:
                        actual_names.append(path.relative_to(output).as_posix())
            require(sorted(actual_names) == names, "retained original has missing or unlisted files")
            inventory = {row["path"]: row for row in inventory_rows}

            def read(name):
                require(name in inventory, "reference is outside retained original inventory")
                return receipt.descriptor(inventory[name], reader)

            for row in inventory_rows:
                receipt.descriptor(row, reader)
            for row in document["helper_sources"]:
                receipt.descriptor(dict(row, path="helpers/" + row["path"]), read)
            config_bytes = receipt.descriptor(document["tool_config"], read)
            require(sha256(config_bytes) == CONFIG_SHA256, "configuration pin differs")
            config = receipt.decode(config_bytes)
            require(config["contract_sha256"] == contract.contract_hash()
                    and config["contract_id"] == recorder.CONTRACT_ID, "configuration contract differs")
            require(config["tools"] == {name: document["tools"][name] for name in recorder.TOOLS},
                    "recorder selected different tools")
            require(config["roots"] == {"sources": document["paths"]["sources"],
                    "build": document["paths"]["build"], "receipts": str(output / "records"),
                    "payloads": str(output / "payloads")}, "recorder roots differ")
            recorder_row = next(row for row in document["helper_sources"]
                                if row["path"] == "ci/project/p06_dependency_record.py")
            recorder_path = str(helpers / recorder_row["path"])
            expected_recorder = {"path": recorder_path, "resolved_path": recorder_path,
                                 "sha256": recorder_row["sha256"], "size_bytes": recorder_row["size_bytes"]}
            descriptors = document["record_identities"]
            records = [receipt.decode(receipt.descriptor(row, read)) for row in descriptors]
            require(len(records) <= contract.MAX_RECORDS and len({row["id"] for row in records}) == len(records),
                    "record count or unique identities differ")
            require([row["path"] for row in descriptors] == sorted(row["path"] for row in descriptors)
                    and all(item["path"] == "records/" + row["id"] + ".json"
                            for item, row in zip(descriptors, records)), "record filenames differ")
            require(all(row["state"] == "finished" for row in records), "unfinished selected tool record")
            passing = [row for row in records if row["outcome"] == "pass"]
            for row in passing:
                receipt._validate_record(row, config, CONFIG_SHA256, read, expected_recorder)
                require(row["environment"]["PATH"] == document["environment"]["PATH"], "tool PATH changed")
            roles = dict(Counter(row["role"] for row in records))
            passed_roles = dict(Counter(row["role"] for row in passing))
            require(roles == document["actual_record_roles"]
                    and passed_roles == document["passing_record_roles"], "declared role population differs")
            result.update(retained_files=len(names), retained_bytes=sum(row["size_bytes"] for row in inventory_rows),
                record_roles=roles, passing_record_roles=passed_roles,
                child_stages=dict(Counter(child["stage"] for row in records for child in row["children"])))
            expected_roles = {"compile": 406, "archive": 3, "index": 2, "link": 2}
            if roles != expected_roles or len(passing) != len(records):
                require(report["outcome"] in ("fail", "blocked") and report["host_diagnostic_passed"] is False
                        and report["reason"] and report["failures"], "incomplete original claims success")
                result.update(review_outcome="pass", partial_original_only=True)
            else:
                plan, compiles, outputs = receipt._verify_compile_graph(document, records, config, read)
                receipt._verify_generated_build(document, records, read)
                commands = receipt._verify_outer_commands(document, config, read)
                require(Counter(row["component"] for row in plan) == contract.TRANSLATION_UNITS
                        and len(compiles) == len(outputs) == 406, "full compile population differs")
                archives, archive_members = {}, {}
                source_root, build_root = document["paths"]["sources"], document["paths"]["build"]
                for name in ("softfloat", "yaml-cpp", "spdlog"):
                    units = [row for row in plan if row["component"] == name]
                    objects = [compiles[source_root + "/" + row["source"]] for row in units]
                    members = [{"name": unit["archive_member"], "sha256": row["output"]["sha256"],
                                "size_bytes": row["output"]["size_bytes"]} for unit, row in zip(units, objects)]
                    path = (source_root + "/softfloat/build/Linux-x86_64-GCC/softfloat.a" if name == "softfloat"
                            else build_root + "/ramulator/_deps/" + name + "-build/lib" + name + ".a")
                    creators = [row for row in records if row["role"] == "archive" and row["output_path"] == path]
                    require(len(creators) == 1, "archive does not have a unique creator")
                    creator = creators[0]
                    arguments = creator["requested_arguments"]
                    require(arguments[0] == ("crs" if name == "softfloat" else "qc")
                            and [receipt.absolute(word, creator["cwd"]) for word in arguments[1:]]
                                == [path, *[row["output_path"] for row in objects]], "archive recipe or order differs")
                    require(creator["inputs_before"] == [row["output"] for row in objects]
                            and all(row["finished_ns"] <= creator["started_ns"] for row in objects),
                            "archive object bytes or chronology differ")
                    binary.validate_archive(receipt.payload(creator["output"], read), members)
                    indexes = [row for row in records if row["role"] == "index" and row["output_path"] == path]
                    final = creator
                    if name == "softfloat":
                        require(not indexes, "SoftFloat has an extra index operation")
                    else:
                        require(len(indexes) == 1 and indexes[0]["output_before"] == creator["output"]
                                and creator["finished_ns"] <= indexes[0]["started_ns"], "index chronology differs")
                        final = indexes[0]
                    parsed = binary.validate_archive(receipt.payload(final["output"], read), members)
                    archives[name] = {"path": path, "members": members, "output": final["output"],
                                      "finished_ns": final["finished_ns"]}
                    require(document["verified_archives"][name] == archives[name], "declared archive result differs")
                    archive_members[path] = parsed["members"]
                external_rows = document.get("external_archives", [])
                require(len(external_rows) <= 2 and len({row["path"] for row in external_rows}) == len(external_rows),
                        "compiler support archive population differs")
                for row in external_rows:
                    path = receipt.absolute(row["path"])
                    name = PurePosixPath(path).name
                    require(name in ("libgcc.a", "libgcc_eh.a") and path not in archive_members,
                            "compiler support archive selection differs")
                    command = commands[row["resolution_command"]]
                    require(command["argv"] == [document["tools"]["g++"]["path"], "-print-file-name=" + name]
                            and receipt.absolute(read(command["log"]).decode().strip()) == path,
                            "compiler support resolution differs")
                    parsed = binary.parse_archive(receipt.descriptor(row["descriptor"], read))
                    require(parsed["members"] == row["members"], "compiler support members differ")
                    archive_members[path] = parsed["members"]
                require(set(commands) - {"softfloat", "ramulator-configure", "ramulator-build",
                        "extension-compile", "extension-link"} == {row["resolution_command"] for row in external_rows},
                        "unexpected compiler support resolution command")
                map_document = dict(document, external_archives=[{"original_path": row["path"]} for row in external_rows])
                links = {}
                for name in ("ramulator", "extension"):
                    path = (source_root + "/ramulator/libramulator.so" if name == "ramulator"
                            else build_root + "/extension/libramulator-vortex.so")
                    selected = [row for row in records if row["role"] == "link" and row["output_path"] == path]
                    require(len(selected) == 1, "shared product lacks a unique link")
                    link = selected[0]
                    objects = [compiles[source_root + "/" + row["source"]] for row in plan if row["component"] == name]
                    expected_inputs, finished = [row["output"] for row in objects], [row["finished_ns"] for row in objects]
                    if name == "ramulator":
                        expected_inputs += [archives[key]["output"] for key in ("yaml-cpp", "spdlog")]
                        finished += [archives[key]["finished_ns"] for key in ("yaml-cpp", "spdlog")]
                        required, loads = [archives[key]["path"] for key in ("yaml-cpp", "spdlog")], []
                    else:
                        expected_inputs.append(links["ramulator"]["output"])
                        finished.append(links["ramulator"]["finished_ns"])
                        required, loads = [], [source_root + "/ramulator/libramulator.so"]
                    require(Counter(contract.digest(row) for row in link["inputs_before"])
                            == Counter(contract.digest(row) for row in expected_inputs)
                            and all(value <= link["started_ns"] for value in finished), "link inputs or chronology differ")
                    require(link["link_map"]["path"] == build_root + "/" + name + ".map", "link map path differs")
                    checked = receipt._verify_link_map(map_document, link, expected_inputs, archive_members, required, loads, read)
                    links[name] = {"output": link["output"], "finished_ns": link["finished_ns"],
                                   "map": checked, "record_id": link["id"]}
                    require(links[name] == document["verified_links"][name], "declared link result differs")

                generated = {}
                for row in sorted(records, key=lambda item: item["finished_ns"]):
                    for field in ("output", "dependency_file", "dependency_prepass_file", "link_map"):
                        item = row[field]
                        if item is not None and PurePosixPath(item["path"]).is_relative_to(PurePosixPath(source_root)):
                            name = str(PurePosixPath(item["path"]).relative_to(PurePosixPath(source_root)))
                            generated[name] = {"path": name, "sha256": item["sha256"], "size_bytes": item["size_bytes"]}
                generated_rows = [generated[name] for name in sorted(generated)]
                require(document["generated_sources"] == generated_rows, "generated source-root inventory differs")
                labels = ["sources-frozen", *(prefix + name for name in commands for prefix in ("before-", "after-")), "final"]
                require([row["label"] for row in document["stability_checks"]] == labels, "diagnostic stability boundaries differ")
                current = []
                for row in document["stability_checks"]:
                    require(set(row) == {"label", "sources"}, "diagnostic stability fields differ")
                    if row["label"] == "after-softfloat":
                        current = [item for item in generated_rows if item["path"].startswith("softfloat/")]
                    elif row["label"] == "after-ramulator-build":
                        current = generated_rows
                    expected = {"contract_id": sources.CONTRACT_ID, "manifest_sha256": MANIFEST_SHA256,
                        "source_files": document["source_manifest"]["total_files"],
                        "source_bytes": document["source_manifest"]["total_size_bytes"],
                        "generated_files": len(current), "generated_bytes": sum(item["size_bytes"] for item in current),
                        "generated_sha256": contract.digest(current)}
                    require(row["sources"] == expected, "source stability summary differs from actual outputs")
                require(report["outcome"] == "pass" and report["host_diagnostic_passed"] is True
                        and report["reason"] is None and report["failures"] == [], "complete original terminal state differs")
                result.update(review_outcome="pass", full_selected_graph_verified=True,
                    translation_units=dict(Counter(row["component"] for row in plan)), selected_tool_operations=len(records),
                    generated_cmake_rows=len(receipt.decode(receipt.descriptor(document["compile_database"], read))),
                    archive_members={name: len(row["members"]) for name, row in archives.items()},
                    products={"softfloat": archives["softfloat"]["output"],
                              **{name: row["output"] for name, row in links.items()}},
                    external_archives=[row["path"] for row in external_rows],
                    outer_commands=[{"id": row["id"], "duration_seconds": row["duration_seconds"],
                        "peak_rss_bytes": row["peak_rss_bytes"], "exit_code": row["exit_code"]} for row in commands.values()],
                    stability_boundaries=len(labels), generated_source_root_files=len(generated_rows))
            for row in inventory_rows:
                receipt.descriptor(row, reader)
            require(reader("host-diagnostic.json") == report_bytes, "original report changed during review")
            require((workspace / "prepared.json").read_bytes() == prepared_bytes, "prepared record changed during review")
            result["original_bytes_stable_during_review"] = True
    except (OSError, ValueError, RuntimeError, AssertionError, KeyError, TypeError) as error:
        result.update(review_outcome="fail", reason=str(error), error_type=type(error).__name__)
    result["duration_seconds"] = round(time.monotonic() - started, 6)
    result["reviewer_sha256"] = sha256(Path(__file__).read_bytes())
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({key: result[key] for key in ("review_outcome", "original_outcome", "full_selected_graph_verified",
        "retained_code_executed", "native_execution", "duration_seconds")}, sort_keys=True))
    if result.get("reason"):
        print(result["reason"])
    return 0 if result["review_outcome"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
