#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Qualify one installed CPU PyTorch route using a fresh, matching P05 packet.

This third, independent stage never builds or reruns native comparison workloads.
It revalidates the original live P04/P05 inputs, installs their bound wheel and a
closed hash-locked framework wheelhouse into a new venv, and records actual
framework calls. All external processes are bounded and failed evidence remains.
Passing execution does not accept a phase or establish hardware performance.
"""
from __future__ import annotations

import argparse
import configparser
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import sys
import tarfile
import zipfile

sys.dont_write_bytecode = True

from baseline_inventory import hash_artifacts
from baseline_process import run_bounded
import p05_execute as python_run
import p05_torch_records as torch_records
from p02_matrix_records import require, validate_header_macros

base = python_run.base
bundle_producer = python_run.bundle_producer
ROOT = python_run.ROOT
BUDGET = dict(python_run.BUDGET)
MIB = 1024 * 1024
MAX_FRAMEWORK_FILE = 2 * 1024 * MIB
MAX_FRAMEWORK_TOTAL = 3 * 1024 * MIB
MAX_FRAMEWORK_FILES = 50000
SITE = "lib/python3.12/site-packages/"
CONTRACT = "ci/project/p05_torch_contract.json"
LOCK = "ci/project/p05_torch_requirements.lock"
SOURCE_FILES = (
    "ci/project/p05_torch_execute.py", "ci/project/p05_torch_records.py",
    "ci/project/p05_torch_installed_check.py", CONTRACT, LOCK,
)
LOADED_HELPERS = hash_artifacts(ROOT, sorted({
    Path(module.__file__).resolve().relative_to(ROOT).as_posix()
    for module in tuple(sys.modules.values())
    if getattr(module, "__file__", None) and Path(module.__file__).suffix == ".py"
    and Path(module.__file__).resolve().is_relative_to(ROOT / "ci/project")
} | {"python/vortex_ai/_bundle.py"}))
LIMITATIONS = [
    "One SimX format is executed; both separate format packets are needed for the declared framework matrix.",
    "Only the frozen eager CPU tensor custom operators, Python patch, CPU framework version and wheel closure are qualified.",
    "The copied P04/P05 packets add no executions. This stage adds exactly 36 native launches through 16 framework operator calls.",
    "Framework payload files are independently matched to locked wheels and streamed before/after; large third-party binaries are identified, not replay-archived.",
    "Original P04/P05 paths and their installations must remain present for live revalidation; relocated offline review is a separate operation.",
    "SimX results are simulated evidence, not RTL, vendor hw_emu, physical FPGA, silicon or physical performance evidence.",
    "No phase acceptance, general framework backend, autograd, training, arbitrary models, CUDA inputs or zero-copy claim is made.",
    "Source and artifact identities retain the existing trusted-builder/non-adversarial-filesystem boundary.",
    *base.PROCESS_LIMITATIONS,
]

# The parent independently verifies installed bytes against the locked wheel
# payload before this process can import any third-party module. This probe only
# observes interpreter/module/distribution origins and actual framework metadata.
FRAMEWORK_PROBE = r'''
import importlib.metadata as metadata, json, pathlib, platform, sys, sysconfig
prefix = pathlib.Path(sys.argv[1])
expected = json.loads(sys.argv[2])
if pathlib.Path(sys.prefix) != prefix or sys.prefix == sys.base_prefix or not sys.flags.isolated or not sys.dont_write_bytecode:
    raise RuntimeError("framework probe did not use the fresh isolated venv")
if platform.python_implementation() != "CPython" or list(sys.version_info[:3]) != [3, 12, 14] or sys.platform != "linux" or platform.machine() != "x86_64" or sys.byteorder != "little" or sysconfig.get_config_var("Py_GIL_DISABLED"):
    raise RuntimeError("framework interpreter/platform differs from the frozen contract")
site = prefix / "lib/python3.12/site-packages"
if pathlib.Path(sysconfig.get_path("purelib")) != site or pathlib.Path(sysconfig.get_path("platlib")) != site:
    raise RuntimeError("framework installation paths differ")
def normalized(name):
    return name.lower().replace("-", "_").replace(".", "_")
distributions = {}
for distribution in metadata.distributions():
    name = normalized(distribution.metadata["Name"])
    if name in distributions or name not in expected or distribution.version != expected[name]:
        raise RuntimeError("unexpected or duplicate framework distribution: " + name)
    root = pathlib.Path(distribution.locate_file(""))
    if root != site or root.resolve(strict=True) != site:
        raise RuntimeError("framework distribution originated outside the fresh venv")
    files = sorted(str(item) for item in (distribution.files or ()))
    if not files:
        raise RuntimeError("framework distribution omitted its file inventory")
    distributions[name] = {"version": distribution.version, "root": str(root), "files": files}
if set(distributions) != set(expected):
    raise RuntimeError("framework distribution closure is incomplete")
import torch
if str(torch.__version__) != "2.15.0+cpu" or torch.version.cuda is not None or pathlib.Path(torch.__file__) != site / "torch/__init__.py":
    raise RuntimeError("actual framework module/version/CPU build differs")
torch.set_num_threads(1)
torch.set_num_interop_threads(1)
result = {"python_version": list(sys.version_info[:3]), "implementation": platform.python_implementation(),
          "platform": sys.platform, "machine": platform.machine(), "byteorder": sys.byteorder,
          "gil": not bool(sysconfig.get_config_var("Py_GIL_DISABLED")), "prefix": sys.prefix,
          "base_prefix": sys.base_prefix, "executable": sys.executable, "isolated": sys.flags.isolated,
          "torch_version": str(torch.__version__), "torch_file": torch.__file__, "cuda": torch.version.cuda,
          "torch_config": torch.__config__.show(), "distributions": distributions}
print("P05_TORCH_ENVIRONMENT " + json.dumps(result, sort_keys=True, separators=(",", ":")))
'''


def _same(actual, expected, message):
    bundle_producer._same(actual, expected, message)


def source_snapshot(source):
    snapshot = python_run.source_snapshot(source)
    names = {row["path"] for row in snapshot["files"]} | set(SOURCE_FILES)
    names.update(row["path"] for row in LOADED_HELPERS)
    snapshot["files"] = hash_artifacts(source, sorted(names))
    return snapshot


def _tree(root, *, limit=MAX_FRAMEWORK_FILE, total_limit=MAX_FRAMEWORK_TOTAL):
    """Hash only contained regular files; never load large binaries into memory."""
    rows, total = [], 0
    require(root.is_dir() and not root.is_symlink(), "inventory root must be a regular directory")
    for path in sorted(root.rglob("*")):
        require(not path.is_symlink(), "inventory contains a symlink: " + str(path))
        require(path.is_dir() or path.is_file(), "inventory contains a nonregular entry")
        if path.is_file():
            require(len(rows) < MAX_FRAMEWORK_FILES, "framework inventory has too many files")
            row, _, _ = bundle_producer._consume(root, path.relative_to(root).as_posix(), limit=limit)
            total += row["size_bytes"]
            require(total <= total_limit, "framework inventory exceeds its byte budget")
            rows.append(row)
    return rows


def _normal_name(value):
    return re.sub(r"[-_.]+", "_", value).lower()


def _contract(inputs, source, wheelhouse):
    value = bundle_producer._json(inputs.read(source, CONTRACT), CONTRACT)
    require(type(value) is dict and type(value.get("schema_version")) is int
            and value["schema_version"] == 1 and value.get("contract_id") == "p05-torch-custom-ops-v1"
            and value.get("acceptance_claimed") is False, "unsupported framework contract")
    _same(value["framework"], {"name": "torch", "version": "2.15.0+cpu", "distribution": "cpu",
        "python": "3.12.14", "implementation": "CPython", "gil": True,
        "platform": "linux", "machine": "x86_64", "byteorder": "little"}, "framework platform contract differs")
    lock_row = inputs.observe(source, LOCK)
    _same(value["requirements"], {"path": LOCK, "sha256": lock_row["sha256"]}, "framework lock identity differs")
    wheels = value.get("wheels")
    require(type(wheels) is list and len(wheels) == 11, "framework wheel closure must contain eleven wheels")
    names, files, expected_lines = set(), set(), []
    for row in wheels:
        require(type(row) is dict and set(row) == {"name", "version", "filename", "size", "sha256"},
                "invalid framework wheel descriptor")
        require(all(type(row[key]) is str and row[key] for key in ("name", "version", "filename", "sha256"))
                and re.fullmatch(r"[A-Za-z0-9_.+-]+\.whl", row["filename"])
                and re.fullmatch(r"[0-9a-f]{64}", row["sha256"])
                and type(row["size"]) is int and 0 < row["size"] <= 256 * MIB, "invalid framework wheel identity")
        name = _normal_name(row["name"])
        require(name not in names and row["filename"] not in files, "duplicate framework dependency")
        names.add(name)
        files.add(row["filename"])
        expected_lines.append(row["name"] + "==" + row["version"] + " --hash=sha256:" + row["sha256"])
    require(names == {"torch", "filelock", "fsspec", "jinja2", "markupsafe", "mpmath", "networkx",
                      "numpy", "setuptools", "sympy", "typing_extensions"}, "framework dependency membership differs")
    lock = inputs.read(source, LOCK).decode("utf-8")
    _same([line for line in lock.splitlines() if line and not line.startswith("#")], expected_lines,
          "requirements lock differs from the exact manifest wheel closure")
    entries = list(wheelhouse.iterdir())
    require({entry.name for entry in entries} == files and len(entries) == len(files),
            "framework wheelhouse has missing or extra entries")
    result = []
    for row in wheels:
        actual = inputs.observe(wheelhouse, row["filename"])
        _same(actual, {"path": row["filename"], "sha256": row["sha256"], "size_bytes": row["size"]},
              "framework wheel differs from the frozen lock")
        result.append(actual)
    return value, result


def _top_level_metadata(name, leaf):
    parts = name.split("/")
    return len(parts) == 2 and parts[0].endswith(".dist-info") and parts[1] == leaf


def _wheel_payload(wheel):
    """Derive installed paths/hashes directly from a bounded locked archive."""
    rows, names, scripts, total = [], set(), set(), 0
    with zipfile.ZipFile(wheel) as archive:
        entries = archive.infolist()
        require(0 < len(entries) <= MAX_FRAMEWORK_FILES, "framework wheel has excessive members")
        for item in entries:
            name = item.filename.rstrip("/") if item.is_dir() else item.filename
            path = python_run._archive_name(name)
            require(name not in names, "framework wheel repeats a member")
            names.add(name)
            mode = item.external_attr >> 16
            require(not stat.S_ISLNK(mode) and (not stat.S_IFMT(mode) or stat.S_ISREG(mode)
                    or (item.is_dir() and stat.S_ISDIR(mode))), "framework wheel contains a nonregular member")
            if item.is_dir():
                continue
            require(0 <= item.file_size <= MAX_FRAMEWORK_FILE, "framework wheel member exceeds its byte budget")
            total += item.file_size
            require(total <= MAX_FRAMEWORK_TOTAL, "framework wheel exceeds its expanded byte budget")
            digest, count = hashlib.sha256(), 0
            metadata = bytearray() if _top_level_metadata(name, "entry_points.txt") else None
            with archive.open(item) as stream:
                while raw := stream.read(MIB):
                    count += len(raw)
                    require(count <= item.file_size, "framework wheel member exceeds its declared size")
                    digest.update(raw)
                    if metadata is not None:
                        require(count <= MIB, "framework entry-point metadata is excessive")
                        metadata.extend(raw)
            require(count == item.file_size, "truncated framework wheel member")
            parts = path.parts
            if parts[0].endswith(".data"):
                require(len(parts) >= 3 and parts[1] == "data", "unsupported framework wheel installation scheme")
                installed = "/".join(parts[2:])
                require(installed.startswith("share/"), "framework data member escapes the reviewed share directory")
            else:
                installed = SITE + name
            rows.append({"path": installed, "sha256": digest.hexdigest(), "size_bytes": count})
            if metadata is not None:
                parser = configparser.ConfigParser(interpolation=None, strict=True)
                parser.optionxform = str
                parser.read_string(bytes(metadata).decode("utf-8"))
                for section in ("console_scripts", "gui_scripts"):
                    if parser.has_section(section):
                        for entry in parser[section]:
                            require(re.fullmatch(r"[A-Za-z0-9_.+-]+", entry), "unsafe framework executable entry point")
                            scripts.add("bin/" + entry)
    require(len({row["path"] for row in rows}) == len(rows), "framework wheel installed paths collide")
    return sorted(rows, key=lambda row: row["path"]), sorted(scripts)


def _installation_tree(venv):
    rows = []
    for name in ("lib/python3.12/site-packages", "bin", "share"):
        path = venv / name
        if path.exists():
            rows.extend({**row, "path": name + "/" + row["path"]} for row in _tree(path))
    require(sum(row["size_bytes"] for row in rows) <= MAX_FRAMEWORK_TOTAL, "installed framework exceeds its total budget")
    require(len(rows) <= MAX_FRAMEWORK_FILES, "installed framework has too many files")
    return sorted(rows, key=lambda row: row["path"])


def _installed_inventory(venv, payload, scripts, seed):
    """Match every immutable wheel member and reject unexplained installed files."""
    rows = _installation_tree(venv)
    actual = {row["path"]: row for row in rows}
    expected = {row["path"]: row for row in payload}
    require(len(expected) == len(payload), "wheel payloads overlap")
    rewritten_records = {name for name in expected if name.startswith(SITE)
                         and _top_level_metadata(name[len(SITE):], "RECORD")}
    for name, row in expected.items():
        if name in rewritten_records:
            require(name in actual, "installed distribution omitted RECORD")
        else:
            _same(actual.get(name), row, "installed file differs from locked wheel: " + name)
    allowed = set(expected) | set(scripts) | {row["path"] for row in seed}
    roots = {name.rsplit("/", 1)[0] for name in rewritten_records}
    allowed.update(root + "/" + leaf for root in roots for leaf in ("INSTALLER", "REQUESTED", "direct_url.json"))
    require(set(actual) <= allowed and set(scripts) <= set(actual), "installed framework has unexplained or missing files")
    for row in seed:
        _same(actual.get(row["path"]), row, "seed interpreter/pip bytes changed during framework installation")
    return rows


def _snapshot(inputs, root, report, key, relative=None):
    return bundle_producer._snapshot(inputs, root, report[key], relative or "snapshots/" + key.replace("_", "-") + ".json")


def _python_sources(inputs, source, output, report, current):
    before = _snapshot(inputs, output, report, "source_before")
    after = _snapshot(inputs, output, report, "source_after")
    _same(before, after, "original P05 source snapshots differ")
    _same(before["checkout"], current["checkout"], "original P05 did not execute the exact current clean checkout")
    require(report.get("source_stable") is True, "original P05 source was not stable")
    rows = bundle_producer._records(before["files"])
    _same(inputs.records(source, [row["path"] for row in rows]), rows, "original P05 source bytes changed")
    loaded = bundle_producer._records(report["loaded_helpers"])
    _same(inputs.records(source, [row["path"] for row in loaded]), loaded, "original P05 helper bytes changed")
    # P05 computes its helper list during import. Reusing its function from a
    # different entry point expands that list, so reconstruct its declared set.
    required = {row["path"] for row in python_run.model_run.source_snapshot(source)["files"]}
    required.update(python_run.SOURCE_FILES)
    required.update(bundle_producer._bundle.SOURCE_PATHS)
    required.update(row["path"] for row in loaded)
    require({row["path"] for row in rows} == required, "original P05 source inventory membership differs")
    retained = bundle_producer._records(report["retained_sources"])
    retained_names = set()
    for row in retained:
        prefix = "artifacts/source/"
        require(row["path"].startswith(prefix), "original P05 source receipt escapes its retained directory")
        name = row["path"][len(prefix):]
        expected = dict(inputs.observe(source, name), path=row["path"])
        _same(inputs.observe(output, row["path"]), expected, "original P05 retained source changed")
        _same(row, expected, "original P05 retained source descriptor differs")
        retained_names.add(name)
    require(retained_names == (set(python_run.SOURCE_FILES) | set(bundle_producer._bundle.SOURCE_PATHS)
          | {row["path"] for row in loaded}), "original P05 retained source membership differs")
    return before


def _verify_python_packet(*, inputs, source, python_work, python_output, work, output, fmt, current, report):
    """Revalidate original live P05/P04 evidence; never invoke an earlier runner."""
    packet = bundle_producer._json(inputs.read(python_output, "report.json"), "original P05 report")
    require(type(packet) is dict and type(packet.get("schema_version")) is int and packet["schema_version"] == 1
            and packet.get("contract_id") == "p05-installed-python-execution-v1", "unsupported original P05 packet")
    for key, expected in (("state", "finished"), ("outcome", "pass"), ("reason", None), ("development", False),
                          ("acceptance_claimed", False), ("phase_complete", False), ("backend", "simx"),
                          ("format", fmt), ("iterations", 2)):
        _same(packet.get(key), expected, "original P05 envelope differs: " + key)
    original_paths = packet["paths"]
    for key, path in (("source", source), ("work", python_work), ("output", python_output)):
        _same(original_paths.get(key), str(path), "original P05 path differs: " + key)
    paths = {key: base._path(value, existing=key != "verilator") if value is not None else None
             for key, value in original_paths.items()}
    require(set(paths) == {"source", "tools", "work", "output", "native_build", "native_output", "host_bin", "verilator"},
            "original P05 path membership differs")
    for key in ("native_build", "native_output", "tools"):
        require(paths[key].is_dir() and not any(base._overlap(paths[key], other) for other in (source, work, output)),
                "original P05 input overlaps the new stage or is missing")
    before = _python_sources(inputs, source, python_output, packet, current)
    matmul_cases = python_run.select_matmul_cases(python_run.load_matmul_cases(source), fmt)
    model_cases = python_run.select_model_cases(python_run.load_model_cases(source), fmt)
    _same(_snapshot(inputs, python_output, packet, "selection"), {"matmuls": matmul_cases, "models": model_cases},
          "original P05 case selection differs")
    _same(packet["matmul_case_ids"], [case["id"] for case in matmul_cases], "original P05 matmul IDs differ")
    _same(packet["model_case_ids"], [case["id"] for case in model_cases], "original P05 model IDs differ")
    jobs = packet["budget"].get("jobs")
    require(type(jobs) is int and jobs in (1, 2), "invalid original P05 build budget")
    _same(packet["budget"], dict(BUDGET, jobs=jobs, package_jobs=1), "original P05 resource budget differs")
    env = base.clean_environment(paths, jobs)
    env.pop("HOME", None)
    tools = _snapshot(inputs, python_output, packet, "tools_before")
    _same(_snapshot(inputs, python_output, packet, "tools_after"), tools, "original P05 tools changed")
    _same(base.tool_inventory(paths, env, ["simx"]), tools, "original P05 tools are no longer the same")
    dependencies = inputs.records(source, base.DEPENDENCIES)
    _same(packet["dependencies_before"], dependencies, "original P05 dependencies changed")
    commands = bundle_producer._commands(inputs, python_output, packet)
    _same(list(commands), ["package-tools-before", "native-matmul-build", "native-matmul-effective-header",
          *("native-" + case["id"] for case in matmul_cases), "package-bound-sdist", "package-offline-wheel",
          "package-create-venv", "package-install-wheel", "installed-matrix", "package-tools-after"],
          "original P05 command order/membership differs")

    native_output, build = paths["native_output"], paths["native_build"]
    native_files = python_run._tree_records(native_output)
    _same(packet["native_input"], {"kind": "completed_top_level_p04_packet", "directory": str(native_output),
          "build": str(build), "retained_prefix": "native", "files": native_files}, "original P05 native linkage differs")
    _same(python_run._tree_records(python_output / "native"), native_files, "original P05 copied native packet changed")
    for row in native_files:
        _same(inputs.observe(native_output, row["path"]), row, "original native packet changed")
    _same(inputs.observe(python_output, "native/report.json"), packet["native_report"], "original native report receipt differs")
    native = bundle_producer._json(inputs.read(native_output, "report.json"), "original P04 report")
    require(type(native.get("variants")) is list and len(native["variants"]) == 1, "original native variant differs")
    variant = native["variants"][0]
    require(variant["id"] == "simx-" + fmt, "original native format differs")
    native_models = {}
    require(len(variant["cases"]) == len(model_cases), "original native model count differs")
    for case, saved in zip(model_cases, variant["cases"]):
        require(saved["id"] == case["id"], "original native model order differs")
        raw = inputs.read(native_output, "logs/simx-" + fmt + "-" + case["id"] + ".log").decode("utf-8")
        native_models[case["id"]] = python_run.verify_model(raw, case, 2, variant["qualification_id"], backend="simx",
            source_revision=current["checkout"]["revision"], fixture_sha256=bundle_producer._bundle.FIXTURE_SHA256)
        _same(saved["observations"], native_models[case["id"]], "original native model differs from its raw log")
    native_artifacts = inputs.records(build, python_run.model_run.artifacts("simx"))
    _same(packet["native_artifacts"], native_artifacts, "original native model build changed")
    _same(packet["native_qualification_id"], variant["qualification_id"], "original model qualification ID differs")

    bundle = output / "artifacts/bundle"
    report["bundle_validation"] = {"kind": "in_process", "function": "p05_bundle.create_bundle",
        "source": str(source), "build": str(build), "native_output": str(native_output),
        "destination": str(bundle), "format": fmt, "state": "running"}
    base._write_json(output / "report.json", report)
    try:
        manifest = bundle_producer.create_bundle(source=source, build=build, native_output=native_output,
                                                 fmt=fmt, destination=bundle)
    except BaseException:
        report["bundle_validation"]["state"] = "failed"
        raise
    report["bundle_validation"]["state"] = "passed"
    original_manifest = inputs.read(python_output, "artifacts/bundle/manifest.json")
    require((bundle / "manifest.json").read_bytes() == original_manifest, "fresh bundle differs from original P05 bundle")
    _same(inputs.observe(python_output, "artifacts/bundle/manifest.json"), packet["bundle_manifest"], "original bundle receipt differs")
    bundle_rows = python_run._tree_records(bundle)
    _same(packet["bundle_artifacts"], bundle_rows, "original P05 bundle artifact inventory differs")
    _same(python_run._tree_records(python_output / "artifacts/bundle"), bundle_rows, "original P05 bundle bytes changed")
    bundle_producer._bundle.validate_files(bundle, manifest)
    report["bundle_manifest"] = hash_artifacts(output, ["artifacts/bundle/manifest.json"])[0]
    report["bundle_artifacts"] = bundle_rows

    app = build / python_run.matmul_run.APP
    compiler = python_run.validate_records(inputs.read(build, "sw/runtime/simx_rt_config.stamp").decode(),
        inputs.read(build, "sw/runtime/simx_config.stamp").decode(),
        inputs.read(build, python_run.matmul_run.APP + "/config.stamp").decode(),
        driver="simx", fmt=fmt, source=source, build=build, jobs=jobs)
    _same(compiler, packet["matmul_compiler_records"], "original native matmul compiler records changed")
    _same(compiler[:2], variant["compiler_records"][:2], "native model/matmul compiler identities differ")
    artifacts = inputs.records(build, python_run.matmul_run.artifacts("simx"))
    _same(packet["matmul_artifacts_before"], artifacts, "original matmul build changed")
    _same(packet["matmul_artifacts_after"], artifacts, "original matmul final build changed")
    binding = {"source": before["checkout"], "backend": "simx", "format": fmt, "compiler_records": compiler,
               "artifacts": artifacts, "dependencies": dependencies, "profile_sha256": bundle_producer._bundle.PROFILE_SHA256}
    _same(_snapshot(inputs, python_output, packet, "matmul_binding", "snapshots/native-matmul-binding.json"),
          binding, "original native matmul binding differs")
    matmul_id = python_run.qualification_id(binding)
    _same(packet["matmul_qualification_id"], matmul_id, "original native matmul qualification ID differs")
    effective = inputs.read(python_output, "logs/native-matmul-effective-header.log").decode("utf-8")
    _same(packet["matmul_backend_header_macros"], validate_header_macros(effective), "native effective-header receipt differs")
    native_matmuls = {}
    for case in matmul_cases:
        raw = inputs.read(python_output, "logs/native-" + case["id"] + ".log").decode("utf-8")
        native_matmuls[case["id"]] = python_run.verify_matmul(raw, case, 2, matmul_id)
    _same(packet["native_matmuls"], [{"id": case["id"], "observations": native_matmuls[case["id"]]}
          for case in matmul_cases], "original native matmul report differs from raw results")
    for key, root in (("retained_native_matmul", python_output / "artifacts/native-matmul"),
                      ("retained_native_model", python_output / "artifacts/native-model")):
        _same(packet[key], python_run._tree_records(root), "retained native executable inventory changed")
    retained_matmul_names = sorted(name for name in python_run.matmul_run.artifacts("simx")
        if name.endswith((".stamp", ".mk", ".h", ".vh", ".vlt")) or Path(name).name in ("Makefile", "ai_matmul", "kernel.elf", "kernel.vxbin"))
    _same([row["path"] for row in packet["retained_native_matmul"]], retained_matmul_names,
          "retained native matmul inventory is incomplete")
    _same([row["path"] for row in packet["retained_native_model"]], ["ai_mlp"], "retained native model inventory is incomplete")
    for row in packet["retained_native_matmul"]:
        _same(inputs.observe(build, row["path"]), row, "retained matmul bytes differ from the live build")
    _same({**inputs.observe(build, python_run.model_run.APP + "/ai_mlp"), "path": "ai_mlp"},
          {**inputs.observe(python_output, "artifacts/native-model/ai_mlp"), "path": "ai_mlp"}, "retained model executable changed")

    packages = bundle_producer._records(packet["packages"])
    _same(inputs.records(python_output, [row["path"] for row in packages]), packages, "original P05 packages changed")
    require(len(packages) == 2, "original P05 package inventory differs")
    sdists = [row for row in packages if row["path"].startswith("packages/sdist/") and row["path"].endswith(".tar.gz")]
    wheels = [row for row in packages if row["path"].startswith("packages/wheel/") and row["path"].endswith(".whl")]
    require(len(sdists) == len(wheels) == 1, "original P05 bound sdist/wheel inventory differs")
    _same(python_run._tree_records(python_output / "packages"),
          [{**row, "path": row["path"].removeprefix("packages/")} for row in packages], "original P05 packages contain extra files")
    wheel = python_output / wheels[0]["path"]
    digest = hashlib.sha256(original_manifest).hexdigest()
    require("-1" + digest + "-" in wheel.name, "original bound wheel lost its complete manifest pin")
    wheel_rows = python_run._wheel_inventory(wheel, manifest)
    _same(_snapshot(inputs, python_output, packet, "wheel_inventory"), wheel_rows, "original wheel member receipt differs")
    stage_names = sorted({row["path"] for row in manifest["binding_sources"]} | {"LICENSE", "python/README.md"})
    _same(_snapshot(inputs, python_output, packet, "package_source_stage"), inputs.records(source, stage_names),
          "original package source stage receipt differs")
    extracted = python_run._extract_sdist(python_output / sdists[0]["path"], work / "verified-sdist", manifest, original_manifest)
    _same(_snapshot(inputs, python_output, packet, "extracted_sdist_before_build"), python_run._tree_records(extracted),
          "original sdist extraction receipt differs")
    original_venv = python_work / "venv"
    original_site, installed = python_run._installed_inventory(original_venv, wheel_rows)
    _same(_snapshot(inputs, python_output, packet, "installed_before"), installed, "original P05 installed bytes changed")
    _same(_snapshot(inputs, python_output, packet, "installed_after"), installed, "original P05 final installed bytes differ")
    _same(python_run._tree_records(python_output / "artifacts/installed"), installed, "retained installed binding differs")
    for row in installed:
        _same(inputs.observe(original_site, row["path"]), row, "original installed binding changed")
    _same(base._file_identity(original_venv / "bin/python"), packet["venv_interpreter"], "original P05 interpreter changed")
    original_request = {"schema_version": 1, "contract_id": "p05-installed-request-v1",
        "binding": {"backend": "simx", "format": fmt, "bundle_root": str(python_output / "artifacts/bundle"),
                    "bundle_sha256": digest, "source_sha256": manifest["binding_source_sha256"],
                    "qualification_id": manifest["qualification_id"], "source_revision": manifest["source_revision"]},
        "matmul_cases": matmul_cases, "model_cases": [case["id"] for case in model_cases],
        "iterations": 2, "expected_prefix": str(original_venv)}
    _same(_snapshot(inputs, python_output, packet, "installed_request"), original_request, "original P05 request differs")
    original_check = python_work / "installed-check"
    _same(bundle_producer._json(inputs.read(original_check, "request.json"), "original request"), original_request,
          "original live request changed")
    script = inputs.observe(original_check, "p05_installed_check.py")
    _same(script, packet["installed_script"], "original checker receipt changed")
    _same({**inputs.observe(source, "ci/project/p05_installed_check.py"), "path": script["path"]}, script,
          "original checker differs from the exact current source")
    observations = _snapshot(inputs, python_output, packet, "observations", "artifacts/installed-observations.json")
    raw = inputs.read(python_output, "logs/installed-matrix.log").decode("utf-8")
    comparison = python_run.verify_observations(observations, original_request, native_matmuls=native_matmuls,
                                               native_models=native_models, model_cases=model_cases, raw_log=raw)
    _same(packet["comparison"], comparison, "original P05 comparison differs from its actual records")
    _same(packet["native_counts"], comparison["counts"], "original P05 native counts differ")
    _same(packet["completed_native_and_python_launches"], 72, "original native/Python execution count differs")
    _same(bundle_producer._json(inputs.read(original_check, "observations.json"), "original live observations"), observations,
          "original live observations changed")

    python = tools["python3"]["path"]
    package_env = dict(base.clean_environment(paths, 1), CC=tools["gcc"]["path"], CXX=tools["g++"]["path"],
                       AR=tools["ar"]["path"], MAX_JOBS="1")
    package_env.pop("HOME", None)
    native_env = dict(env, VORTEX_DRIVER="simx", LD_LIBRARY_PATH=str(build / "sw/runtime"))
    make = [tools["make"]["path"], "--no-print-directory", "-j" + str(jobs), "THREADS=" + str(jobs),
            "VERILATOR_PATH=" + str(paths["verilator"])]
    stage = python_work / "package-source"
    original_extract = python_work / "extracted-sdist" / extracted.name
    expected_commands = {
        "package-tools-before": ([python, "-I", "-B", "-c", python_run.PACKAGE_PROBE], python_work, package_env),
        "native-matmul-build": (make + ["all"], app, dict(env, CONFIGS=f"-DITYPE={fmt} -DOTYPE=fp32 -DKUNROLL=1")),
        "native-matmul-effective-header": ([tools["g++"]["path"], "-E", "-dM", "-x", "c++", *compiler[1]["macro_flags"],
                                            "-include", build / "sw/VX_config.h", "/dev/null"], build, env),
        "package-bound-sdist": ([python, "-I", "-B", stage / "setup.py", "egg_info", "sdist", "--dist-dir",
                                 python_output / "packages/sdist"], stage, dict(package_env, VORTEX_AI_BUNDLE=str(python_output / "artifacts/bundle"))),
        "package-offline-wheel": ([python, "-I", "-B", original_extract / "setup.py", "build", "--build-base",
            python_work / "package-build", "build_ext", "--parallel", "1", "bdist_wheel", "--dist-dir",
            python_output / "packages/wheel", "--bdist-dir", python_work / "wheel-stage"], original_extract, package_env),
        "package-create-venv": ([python, "-I", "-B", "-m", "venv", "--copies", original_venv], python_work, package_env),
        "package-install-wheel": ([original_venv / "bin/python", "-I", "-B", "-m", "pip", "--isolated", "install",
            "--no-index", "--no-deps", "--no-compile", "--disable-pip-version-check", wheel], python_work, package_env),
        "installed-matrix": ([original_venv / "bin/python", "-I", "-B", "-m", "vortex_ai.launch", "--bundle",
            python_output / "artifacts/bundle", "--", original_check / "p05_installed_check.py", "--request",
            original_check / "request.json", "--output", original_check / "observations.json"], original_check, package_env),
        "package-tools-after": ([python, "-I", "-B", "-c", python_run.PACKAGE_PROBE], python_work, package_env),
    }
    for case in matmul_cases:
        expected_commands["native-" + case["id"]] = ([app / "ai_matmul", "--case", case["id"], "--iterations", "2",
            "--module", app / "kernel.vxbin", "--qualification-id", matmul_id], app, native_env)
    for name, (argv, cwd, environment) in expected_commands.items():
        row = commands[name]
        _same(row["argv"], [str(item) for item in argv], "original P05 command arguments differ: " + name)
        _same(row["cwd"], str(cwd), "original P05 command directory differs: " + name)
        _same(row["environment"], environment, "original P05 command environment differs: " + name)
    packages_before = _snapshot(inputs, python_output, packet, "package_tools_before")
    _same(_snapshot(inputs, python_output, packet, "package_tools_after"), packages_before, "original package prerequisites changed")
    for name in ("package-tools-before", "package-tools-after"):
        raw = inputs.read(python_output, commands[name]["log"]).decode("utf-8")
        rows = [line.removeprefix("P05_PACKAGE_TOOLS ") for line in raw.splitlines() if line.startswith("P05_PACKAGE_TOOLS ")]
        require(len(rows) == 1, "original package prerequisite marker is missing or duplicated")
        _same(bundle_producer._json(rows[0].encode(), name), packages_before, "original package prerequisites differ from raw log")
    report["python_revalidation"] = {"outcome": "pass", "comparison": comparison,
        "source_revision": current["checkout"]["revision"], "native_qualification_id": variant["qualification_id"],
        "matmul_qualification_id": matmul_id, "wheel": wheels[0], "bundle_sha256": digest,
        "completed_native_and_python_launches": 72, "copied_packet_additional_launches": 0}
    return {"base_request": original_request, "native_matmuls": native_matmuls, "native_models": native_models,
            "model_cases": model_cases, "bundle": bundle, "manifest": manifest, "wheel": wheel,
            "wheel_rows": wheel_rows, "python": Path(python), "python_identity": tools["python3"]}


def execute(args, paths):
    source, work, output = (paths[name] for name in ("source", "work", "output"))
    output.mkdir(mode=0o700)
    for name in ("logs", "snapshots", "artifacts", "packages"):
        (output / name).mkdir()
    work.mkdir(mode=0o700)
    (work / "tmp").mkdir()
    env = dict(base.clean_environment({"work": work, "host_bin": None}, 1),
               OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MAX_JOBS="1")
    env.pop("HOME", None)
    report = {"schema_version": 1, "contract_id": "p05-installed-torch-execution-v1",
        "started_at": base._now(), "state": "running", "outcome": "blocked", "reason": None,
        "development": False, "acceptance_claimed": False, "phase_complete": False,
        "backend": "simx", "format": args.format, "iterations": 2, "commands": [],
        "budget": dict(BUDGET, framework_file_bytes=MAX_FRAMEWORK_FILE,
                       framework_total_bytes=MAX_FRAMEWORK_TOTAL, framework_files=MAX_FRAMEWORK_FILES),
        "paths": {name: str(value) for name, value in paths.items()}, "limitations": LIMITATIONS}
    inputs = bundle_producer._Inputs()
    initial = packet_rows = installed = context = venv_identity = None
    original_interpreter = framework_before = wheelhouse_rows = None
    payload = scripts = seed = None
    venv = work / "venv"
    venv_python = venv / "bin/python"
    installed_work = work / "installed-check"

    def checkpoint():
        base._write_json(output / "report.json", report)

    def snapshot(name, value):
        relative = "snapshots/" + name + ".json"
        base._write_json(output / relative, value)
        return hash_artifacts(output, [relative])[0]

    def command(name, argv, cwd, timeout):
        row = {"id": name, "argv": [str(item) for item in argv], "cwd": str(cwd),
               "environment": dict(env), "log": "logs/" + name + ".log",
               "timeout_seconds": timeout, "outcome": "running"}
        report["commands"].append(row)
        checkpoint()
        row.update(run_bounded(row["argv"], cwd, env, output / row["log"], timeout_seconds=timeout,
                               **BUDGET, resource_paths=(source, work, output, paths["wheelhouse"])))
        checkpoint()
        require(row["outcome"] == "pass" and row["exit_code"] == 0 and row["cleanup_complete"],
                "command failed: " + name + ": " + str(row.get("reason")))
        return (output / row["log"]).read_text(encoding="utf-8")

    def stable():
        if initial is not None:
            _same(source_snapshot(source), initial, "source changed during framework qualification")
        inputs.stable()
        if "retained_sources" in report:
            _same(hash_artifacts(output, [row["path"] for row in report["retained_sources"]]),
                  report["retained_sources"], "retained framework sources changed")
        if wheelhouse_rows is not None:
            _, current_wheels = _contract(inputs, source, paths["wheelhouse"])
            _same(current_wheels, wheelhouse_rows, "framework wheelhouse changed")
        if packet_rows is not None:
            _same(python_run._tree_records(paths["python_output"]), packet_rows, "original P05 packet changed")
            _same(python_run._tree_records(output / "python"), packet_rows, "retained original P05 packet changed")
        if context is not None:
            _same(python_run._tree_records(context["bundle"]), report["bundle_artifacts"], "verified framework bundle changed")
        if venv_identity is not None:
            _same(base._file_identity(venv_python), venv_identity, "fresh framework interpreter changed")
        if original_interpreter is not None:
            _same(base._file_identity(context["python"]), original_interpreter, "framework provisioning interpreter changed")
        if installed is not None:
            _same(_installed_inventory(venv, payload, scripts, seed), installed, "installed framework bytes changed")

    def probe(name, expected):
        raw = command(name, [venv_python, "-I", "-B", "-c", FRAMEWORK_PROBE, venv,
                             json.dumps(expected, sort_keys=True, separators=(",", ":"))], work, args.timeout_seconds)
        marker = "P05_TORCH_ENVIRONMENT "
        rows = [line[len(marker):] for line in raw.splitlines() if line.startswith(marker)]
        require(len(rows) == 1, "framework environment marker is missing or duplicated")
        result = bundle_producer._json(rows[0].encode("utf-8"), name)
        require(type(result) is dict and result.get("torch_version") == "2.15.0+cpu"
                and result.get("torch_file") == str(venv / SITE / "torch/__init__.py")
                and result.get("prefix") == str(venv) and result.get("cuda") is None,
                "observed framework origin/version differs")
        # Bind each distribution's actual RECORD file list to independently
        # streamed files, including rewritten RECORD and generated entry points.
        by_path = {row["path"]: row for row in installed}
        distributions = result.get("distributions")
        require(type(distributions) is dict and set(distributions) == set(expected), "observed distribution closure differs")
        for name, value in distributions.items():
            require(type(value) is dict and set(value) == {"version", "root", "files"}
                    and value["version"] == expected[name] and value["root"] == str(venv / SITE),
                    "observed distribution identity differs")
            require(type(value["files"]) is list and value["files"] and len(value["files"]) == len(set(value["files"])),
                    "invalid distribution file inventory")
            records = []
            for name in value["files"]:
                require(type(name) is str and name and "\\" not in name and not any(ord(char) < 32 for char in name),
                        "invalid distribution file reference")
                target = (venv / SITE / name).resolve(strict=True)
                require(target.is_relative_to(venv), "distribution file escaped the fresh venv")
                relative = target.relative_to(venv).as_posix()
                require(relative in by_path, "distribution file was not independently inventoried")
                records.append(by_path[relative])
            value["files"] = records
        return result

    try:
        report["resources_before"] = base._resources(paths)
        require(all(free >= BUDGET["min_free_bytes"] for free in report["resources_before"]["free_disk_bytes"].values()),
                "disk reserve below 15 GiB")
        memory = report["resources_before"]["available_memory_bytes"]
        require(memory is not None and memory >= BUDGET["max_rss_bytes"], "need 4 GiB available RAM")
        _same(hash_artifacts(source, [row["path"] for row in LOADED_HELPERS]), LOADED_HELPERS,
              "executing framework helper bytes changed after import")
        report["loaded_helpers"] = LOADED_HELPERS
        initial = source_snapshot(source)
        report["source_before"] = snapshot("source-before", initial)
        base._source_ok(initial, False)
        retained = sorted({row["path"] for row in LOADED_HELPERS} | set(SOURCE_FILES)
                          | set(python_run.SOURCE_FILES) | set(bundle_producer._bundle.SOURCE_PATHS))
        for name in retained:
            python_run._copy(source, name, output / "artifacts/source" / name)
        report["retained_sources"] = hash_artifacts(output, ["artifacts/source/" + name for name in retained])
        contract, wheelhouse_rows = _contract(inputs, source, paths["wheelhouse"])
        report["contract"] = hash_artifacts(output, ["artifacts/source/" + CONTRACT])[0]
        report["requirements"] = hash_artifacts(output, ["artifacts/source/" + LOCK])[0]
        report["wheelhouse"] = {"directory": str(paths["wheelhouse"]), "files": wheelhouse_rows}
        checkpoint()
        packet_rows = python_run._tree_records(paths["python_output"])
        require(packet_rows, "original P05 packet is empty")
        # Retain failures before any native/Python revalidation or framework
        # process. Copying these observations adds zero executed operations.
        for row in packet_rows:
            inputs.observe(paths["python_output"], row["path"])
            python_run._copy(paths["python_output"], row["path"], output / "python" / row["path"], expected=row)
        report["python_input"] = {"kind": "completed_top_level_p05_packet", "directory": str(paths["python_output"]),
                                  "work": str(paths["python_work"]), "retained_prefix": "python", "files": packet_rows}
        report["python_report"] = hash_artifacts(output, ["python/report.json"])[0]
        checkpoint()
        context = _verify_python_packet(inputs=inputs, source=source, python_work=paths["python_work"],
            python_output=paths["python_output"], work=work, output=output, fmt=args.format, current=initial, report=report)
        stable()
        original_interpreter = base._file_identity(context["python"])
        require((original_interpreter["sha256"], original_interpreter["size_bytes"])
                == (context["python_identity"]["sha256"], context["python_identity"]["size_bytes"]),
                "provisioning Python differs from the original P05 interpreter")
        report["provisioning_interpreter"] = original_interpreter
        command("framework-create-venv", [context["python"], "-I", "-B", "-m", "venv", "--copies", venv],
                work, args.timeout_seconds)
        venv_identity = base._file_identity(venv_python)
        require((venv_identity["sha256"], venv_identity["size_bytes"])
                == (original_interpreter["sha256"], original_interpreter["size_bytes"]), "copied framework interpreter bytes differ")
        report["venv_interpreter"] = venv_identity
        configuration, _, raw_config = bundle_producer._consume(venv, "pyvenv.cfg", limit=MIB, collect=True)
        require("include-system-site-packages = false" in raw_config.decode("utf-8").splitlines(),
                "framework venv permits system-site packages")
        report["venv_configuration"] = configuration
        inputs.observe(venv, "pyvenv.cfg", limit=MIB)
        seed = _installation_tree(venv)
        report["venv_seed"] = snapshot("venv-seed", seed)
        pip_metadata = [row for row in seed if re.fullmatch(SITE + r"pip-[^/]+\.dist-info/METADATA", row["path"])]
        require(len(pip_metadata) == 1, "fresh framework venv does not have exactly one seed pip")
        pip_name = pip_metadata[0]["path"].split("/")[-2]
        expected_versions = {_normal_name(row["name"]): row["version"] for row in contract["wheels"]}
        expected_versions.update(pip=pip_name.removeprefix("pip-").removesuffix(".dist-info"), vortex_ai="0.1.0")
        payload, scripts = [], []
        for row in contract["wheels"]:
            members, entries = _wheel_payload(paths["wheelhouse"] / row["filename"])
            payload.extend(members)
            scripts.extend(entries)
        payload.extend({**row, "path": SITE + row["path"]} for row in context["wheel_rows"])
        require(len({row["path"] for row in payload}) == len(payload) and len(set(scripts)) == len(scripts),
                "framework dependency wheels install colliding files or executables")
        report["framework_wheel_payload"] = snapshot("framework-wheel-payload", sorted(payload, key=lambda row: row["path"]))
        report["framework_entry_points"] = sorted(scripts)
        stable()
        lock_path = output / "artifacts/source" / LOCK
        command("framework-install-locked-wheels", [venv_python, "-I", "-B", "-m", "pip", "--isolated", "install",
            "--no-index", "--find-links", paths["wheelhouse"], "--only-binary=:all:", "--require-hashes", "--no-deps",
            "--no-compile", "--no-cache-dir", "--disable-pip-version-check", "-r", lock_path], work, args.timeout_seconds)
        wheel = output / "packages" / context["wheel"].name
        python_run._copy(context["wheel"].parent, context["wheel"].name, wheel)
        report["installed_wheel"] = hash_artifacts(output, [wheel.relative_to(output).as_posix()])[0]
        command("framework-install-bound-wheel", [venv_python, "-I", "-B", "-m", "pip", "--isolated", "install",
            "--no-index", "--no-deps", "--no-compile", "--no-cache-dir", "--disable-pip-version-check", wheel],
            work, args.timeout_seconds)
        installed = _installed_inventory(venv, payload, scripts, seed)
        report["installed_before"] = snapshot("installed-before", installed)
        framework_before = probe("framework-environment-before", expected_versions)
        report["framework_before"] = snapshot("framework-before", framework_before)
        stable()
        installed_work.mkdir(mode=0o700)
        helper_names = ("p05_torch_installed_check.py", "p05_torch_records.py", "p05_installed_check.py")
        for name in helper_names:
            python_run._copy(source, "ci/project/" + name, installed_work / name)
        python_run._copy(source, CONTRACT, installed_work / "p05_torch_contract.json")
        copied = (*helper_names, "p05_torch_contract.json")
        helper_rows = hash_artifacts(installed_work, copied)
        report["installed_helpers"] = snapshot("installed-helpers", helper_rows)
        for row in helper_rows:
            python_run._copy(installed_work, row["path"], output / "artifacts/checker" / row["path"], expected=row)
            inputs.observe(installed_work, row["path"])
        request = {"schema_version": 1, "contract_id": "p05-torch-request-v1",
            "base_request": copy.deepcopy(context["base_request"]), "framework": {"version": "2.15.0+cpu",
                "contract_sha256": inputs.observe(source, CONTRACT)["sha256"],
                "adapter_sha256": inputs.observe(source, "python/vortex_ai/torch_ops.py")["sha256"]}}
        request["base_request"]["expected_prefix"] = str(venv)
        request["base_request"]["binding"]["bundle_root"] = str(context["bundle"])
        torch_records.validate_request(request)
        request_path = installed_work / "request.json"
        base._write_json(request_path, request)
        report["installed_request"] = snapshot("installed-request", request)
        inputs.observe(installed_work, "request.json")
        observations_path = installed_work / "observations.json"
        stable()
        require(not any(name in env for name in ("PYTHONPATH", "PYTHONHOME", "LD_PRELOAD", "LD_AUDIT",
                                                "LD_LIBRARY_PATH", "VORTEX_AI_BUNDLE")), "framework environment has a source/loader override")
        raw = command("installed-framework-matrix", [venv_python, "-I", "-B", "-m", "vortex_ai.launch", "--bundle",
            context["bundle"], "--", installed_work / "p05_torch_installed_check.py", "--request", request_path,
            "--output", observations_path, "--contract", installed_work / "p05_torch_contract.json"],
            installed_work, 16 * args.run_timeout_seconds + 60)
        observations = python_run._read_json(installed_work, "observations.json")
        python_run._copy(installed_work, "observations.json", output / "artifacts/installed-observations.json")
        report["observations"] = hash_artifacts(output, ["artifacts/installed-observations.json"])[0]
        report["comparison"] = torch_records.verify_observations(observations, request,
            native_matmuls=context["native_matmuls"], native_models=context["native_models"],
            model_cases=context["model_cases"], raw_log=raw)
        _same(report["comparison"]["counts"], report["python_revalidation"]["comparison"]["counts"],
              "native/Python/framework dispatch counts differ")
        _same({**report["comparison"]["counts"], "event_profile_pairs": report["comparison"]["event_profile_pairs"]},
              contract["qualification_per_format"], "observed framework counts differ from the frozen contract")
        require(report["comparison"]["operator_calls"] == 16, "framework operator call count differs")
        framework_after = probe("framework-environment-after", expected_versions)
        _same(framework_after, framework_before, "actual framework environment changed")
        report["framework_after"] = snapshot("framework-after", framework_after)
        stable()
        report["installed_after"] = snapshot("installed-after", _installed_inventory(venv, payload, scripts, seed))
        bundle_producer._commands(inputs, output, report)
        report["execution_counts"] = {"native_comparison_launches": 36, "plain_python_launches": 36,
            "framework_launches": 36, "framework_operator_calls": 16, "copied_packet_additional_launches": 0,
            "distinct_total_launches": 108, "framework_event_profile_pairs": 180}
        report["outcome"] = "pass"
    except (OSError, ValueError, RuntimeError, KeyError, ImportError, TypeError, EOFError, OverflowError,
            tarfile.TarError, zipfile.BadZipFile, configparser.Error) as error:
        report.update(outcome="fail" if report["commands"] else "blocked", reason=str(error))
    except KeyboardInterrupt:
        report.update(outcome="fail", reason="interrupted")
    finally:
        # Even a nonzero checker exit can have useful partial structured output.
        # Preserve it while leaving the execution outcome failed.
        try:
            failed_observations = installed_work / "observations.json"
            if failed_observations.exists() and not (output / "artifacts/installed-observations.json").exists():
                python_run._copy(installed_work, "observations.json", output / "artifacts/installed-observations.json")
                report["observations"] = hash_artifacts(output, ["artifacts/installed-observations.json"])[0]
            if (venv / SITE).is_dir() and "installed_after" not in report:
                report["installed_after"] = snapshot("installed-after", _installation_tree(venv))
            if packet_rows is not None:
                report["python_input_after"] = snapshot("python-input-after", python_run._tree_records(paths["python_output"]))
            if wheelhouse_rows is not None:
                report["wheelhouse_after"] = snapshot("wheelhouse-after", _tree(paths["wheelhouse"], limit=256 * MIB))
            if initial is not None:
                final = source_snapshot(source)
                report["source_after"] = snapshot("source-after", final)
                report["source_stable"] = final == initial
                stable()
        except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
            report.setdefault("failure_reasons", []).append(str(error))
            report.update(outcome="fail", reason=report["reason"] or str(error))
        report.update(state="finished", finished_at=base._now())
        try:
            report["resources_after"] = base._resources(paths)
        except OSError as error:
            report["resource_snapshot_error"] = str(error)
            report.update(outcome="fail", reason=report["reason"] or str(error))
        checkpoint()
    return report


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=("run",))
    parser.add_argument("--source-dir", type=Path, default=ROOT)
    parser.add_argument("--python-work", type=Path, required=True, help="still-present fresh original P05 work directory")
    parser.add_argument("--python-output", type=Path, required=True, help="completed original P05 packet from the same clean revision")
    parser.add_argument("--wheelhouse", type=Path, required=True, help="closed preprovisioned hash-locked CPU framework wheelhouse")
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--format", choices=("fp16", "bf16"), required=True)
    parser.add_argument("--timeout-seconds", type=base._timeout, default=600)
    parser.add_argument("--run-timeout-seconds", type=base._timeout, default=300)
    return parser


def resolve_paths(args):
    paths = {"source": base._path(args.source_dir, existing=True),
        "python_work": base._path(args.python_work, existing=True),
        "python_output": base._path(args.python_output, existing=True),
        "wheelhouse": base._path(args.wheelhouse, existing=True),
        "work": base._path(args.work_dir), "output": base._path(args.output)}
    require(paths["source"] == ROOT, "execute the framework runner from the selected source checkout")
    for key in ("source", "python_work", "python_output", "wheelhouse"):
        require(paths[key].is_dir(), key + " must be an existing directory")
    for key in ("work", "output"):
        require(not os.path.lexists(paths[key]) and paths[key].parent.is_dir(),
                key + " must be fresh under an existing directory")
    roots = list(paths.values())
    require(not any(base._overlap(left, right) for index, left in enumerate(roots) for right in roots[index + 1:]),
            "framework source, input, work and output roots must be separate")
    return paths


def main(argv=None):
    args = argument_parser().parse_args(argv)
    try:
        report = execute(args, resolve_paths(args))
        print(json.dumps({"outcome": report["outcome"], "reason": report["reason"], "acceptance_claimed": False,
                          "report": str(args.output.absolute() / "report.json")}, sort_keys=True))
        return 0 if report["outcome"] == "pass" else 1
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({"outcome": "blocked", "reason": str(error), "acceptance_claimed": False}, sort_keys=True))
        return 1


if __name__ == "__main__":
    sys.exit(main())
