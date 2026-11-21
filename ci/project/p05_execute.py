#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Qualify one installed copying-Python variant against unchanged native paths.

The unchanged top-level P04 runner supplies a clean native packet. Three additional
frozen matmuls run in that same build without weakening P03's selection gates.
A bound sdist is rebuilt offline without VORTEX_AI_BUNDLE, installed into a
fresh venv, and exercised outside the checkout through the trusted launcher.
Every external command is bounded and raw evidence survives failures. A passing
selected SimX format is execution evidence, never automatic P05 acceptance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys
import tarfile
import zipfile

sys.dont_write_bytecode = True

from baseline_inventory import hash_artifacts
from baseline_process import run_bounded
import p02_matrix as base
from p02_matrix_records import require, validate_header_macros
from p02_wmma_fixtures import load_cases as load_matmul_cases
import p03_execute as matmul_run
from p03_execution_records import qualification_id, validate_records, verify_output as verify_matmul
import p04_execute as model_run
from p04_fixture_adapter import load_cases as load_model_cases
from p04_execution_records import verify_output as verify_model
import p05_bundle as bundle_producer
from p05_execution_records import select_matmul_cases, select_model_cases, verify_observations


ROOT = Path(__file__).resolve().parents[2]
BUDGET = dict(model_run.BUDGET)
SOURCE_FILES = (
    "ci/project/p05_execute.py", "ci/project/p05_execution_records.py",
    "ci/project/p05_installed_check.py", "ci/project/p05_bundle.py", "python/README.md", "LICENSE",
)
LIMITATIONS = [
    "This invocation qualifies one SimX FP16 or BF16 installed variant; both separate packets are needed for the six-signature/twenty-model-run Python matrix.",
    "The comparison selects three frozen P02 cases covering the three supported shapes; it does not rerun or relax the P03 full-matrix gate.",
    "The unchanged P04 native executable and unchanged P03 native matmul executable are independent comparison routes.",
    "Only Linux CPython 3.12 copying APIs and the fixed synthetic model are exercised; no PyTorch/custom-op, arbitrary model, autograd, training or CUDA compatibility is established.",
    "SimX results are simulator evidence, not processor RTL, vendor hw_emu, physical FPGA, silicon or physical performance evidence.",
    "Source, tools and artifact identities are checked within the existing trusted-builder/non-adversarial-filesystem boundary.",
    "Package sources, sdist, wheel, installed package bytes, raw commands/logs and native bundle bytes are retained; system Python/ELF dependencies are identified but not replay-archived.",
    "No dependency download, local toolchain installation or golden-data modification occurs.",
    "A passing packet does not accept a phase or resolve the preserved vendor hw_emu and DSP area-gate blockers.",
    *base.PROCESS_LIMITATIONS,
]
LOADED_HELPERS = hash_artifacts(ROOT, sorted({
    Path(module.__file__).resolve().relative_to(ROOT).as_posix()
    for module in tuple(sys.modules.values())
    if getattr(module, "__file__", None) and Path(module.__file__).suffix == ".py"
    and Path(module.__file__).resolve().is_relative_to(ROOT / "ci/project")
} | {"ci/project/p05_execute.py", "python/vortex_ai/_bundle.py"}))

PACKAGE_PROBE = r'''
import hashlib, importlib.metadata, json, pathlib, platform, sys, sysconfig
if platform.python_implementation() != "CPython" or sys.version_info[:2] != (3, 12) or not sys.platform.startswith("linux") or sysconfig.get_config_var("Py_GIL_DISABLED"):
    raise RuntimeError("P05 package qualification requires Linux CPython 3.12 with the GIL")
result = {"python_version": list(sys.version_info[:3]), "implementation": platform.python_implementation(), "executable": sys.executable, "distributions": {}}
for name, expected in (("setuptools", "84.2.1"), ("wheel", "0.48.0"), ("packaging", "26.3")):
    distribution = importlib.metadata.distribution(name)
    if distribution.version != expected:
        raise RuntimeError("offline package prerequisite version differs: " + name)
    rows = []
    for item in sorted(distribution.files or (), key=str):
        path = pathlib.Path(distribution.locate_file(item)).resolve(strict=True)
        if not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
            raise RuntimeError("invalid package prerequisite file: " + str(path))
        raw = path.read_bytes()
        rows.append({"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)})
    if not rows:
        raise RuntimeError("missing package prerequisite inventory: " + name)
    result["distributions"][name] = {"version": distribution.version, "files": rows}
print("P05_PACKAGE_TOOLS " + json.dumps(result, sort_keys=True, separators=(",", ":")))
'''


def source_snapshot(source):
    snapshot = model_run.source_snapshot(source)
    names = {row["path"] for row in snapshot["files"]}
    names.update(SOURCE_FILES)
    names.update(bundle_producer._bundle.SOURCE_PATHS)
    names.update(row["path"] for row in LOADED_HELPERS)
    snapshot["files"] = hash_artifacts(source, sorted(names))
    return snapshot


def _same(actual, expected, message):
    bundle_producer._same(actual, expected, message)


def _read_json(root, relative):
    _, _, raw = bundle_producer._consume(root, relative, limit=16 * 1024 * 1024, collect=True)
    return bundle_producer._json(raw, relative)


def _copy(root, relative, destination, *, expected=None):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as stream:
        row, _, _ = bundle_producer._consume(root, relative, limit=256 * 1024 * 1024, sink=stream)
        stream.flush()
        os.fsync(stream.fileno())
    actual = hash_artifacts(destination.parent, [destination.name])[0]
    require((actual["sha256"], actual["size_bytes"]) == (row["sha256"], row["size_bytes"]),
            "copied file identity differs: " + relative)
    if expected is not None:
        require((row["sha256"], row["size_bytes"]) == (expected["sha256"], expected.get("size", expected.get("size_bytes"))),
                "copy differs from frozen identity: " + relative)
    return row


def _tree_records(root):
    names = []
    for path in sorted(root.rglob("*")):
        require(not path.is_symlink(), "owned artifact tree contains a symlink")
        require(path.is_dir() or path.is_file(), "owned artifact tree contains a nonregular entry")
        if path.is_file():
            names.append(path.relative_to(root).as_posix())
    return hash_artifacts(root, names)


def _package_stage(source, destination, manifest):
    destination.mkdir(mode=0o700)
    expected = {row["path"]: row for row in manifest["binding_sources"]}
    for name in sorted(set(expected) | {"LICENSE", "python/README.md"}):
        _copy(source, name, destination / name, expected=expected.get(name))
    _same(bundle_producer._bundle.source_inventory(destination), manifest["binding_sources"],
          "packaging source stage differs from the bound inventory")
    require(not (destination / "python/p05_build").exists(), "initial packaging stage has a preexisting pin")
    return _tree_records(destination)


def _archive_name(name):
    require(type(name) is str and name and "\\" not in name
            and not any(ord(char) < 32 for char in name), "unsafe package archive member")
    path = PurePosixPath(name)
    require(not path.is_absolute() and str(path) == name
            and all(part not in (".", "..") for part in path.parts), "package archive path escapes")
    return path


def _extract_sdist(archive, destination, manifest, manifest_bytes):
    """Extract only regular bounded members; never honor archive links or modes."""
    destination.mkdir(mode=0o700)
    names, total, top = set(), 0, None
    with tarfile.open(archive, "r:gz") as stream:
        for index, member in enumerate(stream):
            require(index < 1024, "source archive member inventory is excessive")
            name = member.name.rstrip("/") if member.isdir() else member.name
            path = _archive_name(name)
            require(name not in names and (member.isdir() or member.isfile()),
                    "duplicate or nonregular source archive member")
            names.add(name)
            if top is None:
                top = path.parts[0]
            require(path.parts[0] == top, "source archive has multiple roots")
            target = destination.joinpath(*path.parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            require(len(path.parts) > 1 and 0 <= member.size <= 16 * 1024 * 1024,
                    "source archive file is oversized or lacks a package root")
            total += member.size
            require(total <= 64 * 1024 * 1024, "source archive expands beyond its budget")
            target.parent.mkdir(parents=True, exist_ok=True)
            source = stream.extractfile(member)
            require(source is not None, "source archive member cannot be read")
            with source, target.open("xb") as output:
                remaining = member.size
                while remaining:
                    raw = source.read(min(remaining, 1024 * 1024))
                    require(raw, "truncated source archive member")
                    output.write(raw)
                    remaining -= len(raw)
                require(not source.read(1), "source archive member exceeded declared size")
    require(top is not None, "empty source archive")
    root = destination / top
    expected_files = {row["path"] for row in manifest["binding_sources"]} | {
        "LICENSE", "python/README.md", "PKG-INFO", "python/p05_build/manifest.json",
        "python/p05_build/source_inventory.json", "python/p05_build/p05_build_config.h",
        *("python/vortex_ai.egg-info/" + name for name in
          ("PKG-INFO", "SOURCES.txt", "dependency_links.txt", "top_level.txt")),
    }
    require({row["path"] for row in _tree_records(root)} == expected_files,
            "source archive file inventory differs from the reviewed package producer")
    _same(bundle_producer._bundle.source_inventory(root), manifest["binding_sources"],
          "sdist source inventory differs from its bound inputs")
    require((root / "python/p05_build/manifest.json").read_bytes() == manifest_bytes,
            "sdist did not preserve the exact bundle pin")
    require((root / "python/p05_build/source_inventory.json").read_bytes()
            == bundle_producer._bundle.canonical_bytes(manifest["binding_sources"]),
            "sdist did not preserve its source receipt")
    require((root / "python/p05_build/p05_build_config.h").is_file(), "sdist omitted its generated pin header")
    return root


def _wheel_inventory(wheel, manifest):
    rows, names, total = [], set(), 0
    with zipfile.ZipFile(wheel) as archive:
        entries = archive.infolist()
        require(0 < len(entries) <= 1024, "wheel member inventory is excessive")
        for item in entries:
            require(not item.is_dir(), "wheel has an unexpected directory entry")
            path = _archive_name(item.filename)
            require(item.filename not in names, "wheel repeats a member")
            names.add(item.filename)
            mode = item.external_attr >> 16
            require(not stat.S_ISLNK(mode) and (not stat.S_IFMT(mode) or stat.S_ISREG(mode)),
                    "wheel contains a nonregular member")
            require(0 <= item.file_size <= 256 * 1024 * 1024, "wheel member is oversized")
            total += item.file_size
            require(total <= 512 * 1024 * 1024, "wheel expands beyond its budget")
            raw = archive.read(item)
            require(len(raw) == item.file_size, "wheel member length differs")
            rows.append({"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)})
    sources = {row["path"].removeprefix("python/"): row for row in manifest["binding_sources"]
               if row["path"].startswith("python/vortex_ai/")}
    payload = {row["path"]: row for row in rows if row["path"].startswith("vortex_ai/")}
    extensions = [name for name in payload if name.startswith("vortex_ai/_native.") and name.endswith(".so")]
    require(len(extensions) == 1 and set(payload) == set(sources) | set(extensions),
            "wheel package payload differs from the exact binding source inventory")
    for name, expected in sources.items():
        require((payload[name]["sha256"], payload[name]["size_bytes"]) == (expected["sha256"], expected["size"]),
                "wheel Python source differs from the bound source: " + name)
    metadata = {name.split("/", 1)[0] for name in names - set(payload)}
    require(metadata == {"vortex_ai-0.1.0.dist-info"}
            and {"vortex_ai-0.1.0.dist-info/" + name for name in ("METADATA", "WHEEL", "RECORD")} <= names,
            "wheel contains an unexpected payload root")
    return sorted(rows, key=lambda row: row["path"])


def _installed_inventory(venv, wheel_rows):
    site = venv / "lib/python3.12/site-packages"
    require(site.is_dir() and not site.is_symlink(), "clean venv site-packages is unavailable")
    payload = [row for row in wheel_rows if row["path"].startswith("vortex_ai/")]
    actual = _tree_records(site / "vortex_ai")
    _same(actual, [{**row, "path": row["path"].removeprefix("vortex_ai/")} for row in payload],
          "installed package bytes differ from the retained wheel")
    for row in wheel_rows:
        # pip rewrites RECORD and adds INSTALLER/direct_url/REQUESTED; all other
        # wheel bytes must remain exact, including the distribution metadata.
        if row["path"].endswith(".dist-info/RECORD"):
            continue
        _same(hash_artifacts(site, [row["path"]])[0], row, "installed wheel member changed")
    metadata_roots = {row["path"].split("/", 1)[0] for row in wheel_rows if ".dist-info/" in row["path"]}
    names = [row["path"] for row in payload]
    for name in metadata_roots:
        names.extend(name + "/" + row["path"] for row in _tree_records(site / name))
    return site, hash_artifacts(site, sorted(names))


def execute(args, paths):
    source, work, output = (paths[key] for key in ("source", "work", "output"))
    output.mkdir(mode=0o700)
    for name in ("logs", "snapshots", "artifacts", "packages"):
        (output / name).mkdir()
    work.mkdir(mode=0o700)
    (work / "tmp").mkdir()
    env = base.clean_environment(paths, args.jobs)
    env.pop("HOME", None)
    report = {"schema_version": 1, "contract_id": "p05-installed-python-execution-v1",
        "started_at": base._now(), "state": "running", "outcome": "blocked", "reason": None,
        "development": False, "acceptance_claimed": False, "phase_complete": False,
        "backend": "simx", "format": args.format, "iterations": 2,
        "commands": [], "limitations": LIMITATIONS, "budget": dict(BUDGET, jobs=args.jobs, package_jobs=1),
        "paths": {key: str(value) if value else None for key, value in paths.items()}}
    initial = tools = dependencies = package_tools = None
    native_frozen = native_packet_frozen = matmul_frozen = bundle_frozen = installed_frozen = package_frozen = None
    build = bundle = site = venv_python = venv_identity = None

    def checkpoint():
        base._write_json(output / "report.json", report)

    def snapshot(name, value):
        relative = "snapshots/" + name + ".json"
        base._write_json(output / relative, value)
        return hash_artifacts(output, [relative])[0]

    def command(name, argv, cwd, environment, timeout):
        row = {"id": name, "argv": [str(item) for item in argv], "cwd": str(cwd),
            "environment": environment, "log": "logs/" + name + ".log",
            "timeout_seconds": timeout, "outcome": "running"}
        report["commands"].append(row)
        checkpoint()
        row.update(run_bounded(row["argv"], cwd, environment, output / row["log"],
            timeout_seconds=timeout, **BUDGET, resource_paths=(source, work, output)))
        checkpoint()
        require(row["outcome"] == "pass" and row["exit_code"] == 0 and row["cleanup_complete"],
                "command failed: " + name + ": " + str(row.get("reason")))
        return (output / row["log"]).read_text(encoding="utf-8")

    def stable():
        require(source_snapshot(source) == initial, "source changed during P05 execution")
        if tools is not None:
            require(base.tool_inventory(paths, env, ["simx"]) == tools, "tools changed during P05 execution")
        if dependencies is not None:
            require(hash_artifacts(source, base.DEPENDENCIES) == dependencies, "native dependencies changed")
        if native_packet_frozen is not None:
            require(_tree_records(paths["native_output"]) == native_packet_frozen,
                    "original native P04 packet changed during P05 execution")
            require(_tree_records(output / "native") == native_packet_frozen,
                    "retained native P04 packet changed during P05 execution")
        if native_frozen is not None:
            require(hash_artifacts(build, model_run.artifacts("simx")) == native_frozen,
                    "qualified P04 build changed during P05 execution")
        if matmul_frozen is not None:
            require(hash_artifacts(build, matmul_run.artifacts("simx")) == matmul_frozen,
                    "qualified native matmul build changed")
        if bundle_frozen is not None:
            require(_tree_records(bundle) == bundle_frozen, "relocated native bundle changed")
        if installed_frozen is not None:
            require(hash_artifacts(site, [row["path"] for row in installed_frozen]) == installed_frozen,
                    "installed package bytes changed during execution")
        if package_frozen is not None:
            require(hash_artifacts(output, [row["path"] for row in package_frozen]) == package_frozen,
                    "retained source/wheel package bytes changed")
        if venv_identity is not None:
            require(base._file_identity(venv_python) == venv_identity, "copied venv interpreter changed")

    def probe_packages(label, python, package_env):
        text = command(label, [python, "-I", "-B", "-c", PACKAGE_PROBE], work, package_env, 60)
        rows = [line[len("P05_PACKAGE_TOOLS "):] for line in text.splitlines() if line.startswith("P05_PACKAGE_TOOLS ")]
        require(len(rows) == 1, "missing or duplicate offline package prerequisite inventory")
        return bundle_producer._json(rows[0].encode("utf-8"), "package prerequisites")

    try:
        report["resources_before"] = base._resources(paths)
        require(all(value >= BUDGET["min_free_bytes"] for value in
                    report["resources_before"]["free_disk_bytes"].values()), "disk reserve below 15 GiB")
        memory = report["resources_before"]["available_memory_bytes"]
        require(memory is not None and memory >= BUDGET["max_rss_bytes"], "need 4 GiB available RAM")
        require(hash_artifacts(source, [row["path"] for row in LOADED_HELPERS]) == LOADED_HELPERS,
                "executing P05 runner/helper bytes changed after import")
        report["loaded_helpers"] = LOADED_HELPERS
        initial = source_snapshot(source)
        report["source_before"] = snapshot("source-before", initial)
        base._source_ok(initial, False)
        matmul_cases = select_matmul_cases(load_matmul_cases(source), args.format)
        model_cases = select_model_cases(load_model_cases(source), args.format)
        report["selection"] = snapshot("selection", {"matmuls": matmul_cases, "models": model_cases})
        report["matmul_case_ids"] = [case["id"] for case in matmul_cases]
        report["model_case_ids"] = [case["id"] for case in model_cases]
        tools = base.tool_inventory(paths, env, ["simx"])
        report["tools_before"] = snapshot("tools-before", tools)
        dependencies = hash_artifacts(source, base.DEPENDENCIES)
        report["dependencies_before"] = dependencies
        retained = sorted({row["path"] for row in LOADED_HELPERS} | set(SOURCE_FILES)
                          | set(bundle_producer._bundle.SOURCE_PATHS))
        for name in retained:
            _copy(source, name, output / "artifacts/source" / name)
        report["retained_sources"] = hash_artifacts(output, ["artifacts/source/" + name for name in retained])
        python = tools["python3"]["path"]
        package_env = dict(base.clean_environment(paths, 1), CC=tools["gcc"]["path"],
                           CXX=tools["g++"]["path"], AR=tools["ar"]["path"], MAX_JOBS="1")
        package_env.pop("HOME", None)
        package_tools = probe_packages("package-tools-before", python, package_env)
        report["package_tools_before"] = snapshot("package-tools-before", package_tools)
        stable()

        native_output = paths["native_output"]
        native_packet_frozen = _tree_records(native_output)
        require(native_packet_frozen, "native P04 packet is empty")
        for row in native_packet_frozen:
            _copy(native_output, row["path"], output / "native" / row["path"], expected=row)
        _same(_tree_records(output / "native"), native_packet_frozen,
              "retained native P04 packet differs from its original bytes")
        native = _read_json(native_output, "report.json")
        report["native_input"] = {"kind": "completed_top_level_p04_packet",
            "directory": str(native_output), "build": str(paths["native_build"]),
            "retained_prefix": "native", "files": native_packet_frozen}
        checkpoint()
        require(type(native) is dict, "native P04 report must be a JSON object")
        require(native.get("outcome") == "pass" and native.get("development") is False
                and native.get("acceptance_claimed") is False and native.get("state") == "finished",
                "unchanged P04 runner did not produce a passing clean packet")
        require(type(native.get("paths")) is dict, "native P04 report lacks its input paths")
        for name in ("source", "tools", "host_bin", "verilator"):
            expected = str(paths[name]) if paths[name] is not None else None
            _same(native["paths"].get(name), expected,
                  "native P04 and P05 input path differs: " + name)
        require(type(native.get("variants")) is list and len(native["variants"]) == 1
                and type(native["variants"][0]) is dict
                and native["variants"][0].get("id") == "simx-" + args.format,
                "native P04 selected variant differs")
        variant = native["variants"][0]
        build = paths["native_build"]
        native_frozen = hash_artifacts(build, model_run.artifacts("simx"))
        _same(variant["artifacts_before"], native_frozen, "P04 build changed after native execution")
        _same(variant["artifacts_after"], native_frozen, "P04 final build inventory differs")
        report["native_report"] = hash_artifacts(output, ["native/report.json"])[0]
        report["native_qualification_id"] = variant["qualification_id"]
        report["native_artifacts"] = native_frozen
        native_models = {}
        for case, saved in zip(model_cases, variant["cases"]):
            require(saved["id"] == case["id"], "native model case membership differs")
            name = "simx-" + args.format + "-" + case["id"]
            raw = (native_output / "logs" / (name + ".log")).read_text(encoding="utf-8")
            native_models[case["id"]] = verify_model(raw, case, 2, variant["qualification_id"], backend="simx",
                source_revision=initial["checkout"]["revision"], fixture_sha256=native["fixture_sha256"])
            _same(saved["observations"], native_models[case["id"]], "native model report differs from raw log")
        stable()

        # Producer rechecks the complete original P04 packet and exact source,
        # stamps, dependency closure and still-present native build itself.
        bundle = output / "artifacts/bundle"
        report["bundle_validation"] = {"kind": "in_process", "function": "p05_bundle.create_bundle",
            "producer_source": hash_artifacts(source, ["ci/project/p05_bundle.py"])[0],
            "source": str(source), "build": str(build), "native_output": str(native_output),
            "format": args.format, "destination": str(bundle), "state": "running"}
        checkpoint()
        # Metadata probes have their own bounded child groups. Keeping the
        # producer here avoids an outer group monitor misreporting their cleanup.
        try:
            manifest = bundle_producer.create_bundle(source=source, build=build,
                native_output=native_output, fmt=args.format, destination=bundle)
        except BaseException:
            report["bundle_validation"]["state"] = "failed"
            checkpoint()
            raise
        _, _, observed_manifest = bundle_producer._bundle.read_manifest(bundle)
        _same(observed_manifest, manifest, "produced manifest differs from its retained bytes")
        report["bundle_validation"]["state"] = "passed"
        bundle_producer._bundle.validate_files(bundle, manifest)
        manifest_bytes = (bundle / "manifest.json").read_bytes()
        bundle_frozen = _tree_records(bundle)
        report["bundle_manifest"] = hash_artifacts(output, ["artifacts/bundle/manifest.json"])[0]
        report["bundle_artifacts"] = bundle_frozen
        stable()

        # This additional host/kernel app shares the already qualified runtime
        # and CONFIGS, while retaining independent application compiler records.
        app = build / matmul_run.APP
        require((app / "Makefile").read_bytes() == (source / matmul_run.APP / "Makefile").read_bytes(),
                "generated matmul Makefile differs from unchanged source")
        make = [tools["make"]["path"], "--no-print-directory", "-j" + str(args.jobs),
                "THREADS=" + str(args.jobs), "VERILATOR_PATH=" + str(paths["verilator"])]
        build_env = dict(env, CONFIGS=f"-DITYPE={args.format} -DOTYPE=fp32 -DKUNROLL=1")
        command("native-matmul-build", make + ["all"], app, build_env, args.timeout_seconds)
        stable()
        compiler = validate_records((build / "sw/runtime/simx_rt_config.stamp").read_text(),
            (build / "sw/runtime/simx_config.stamp").read_text(), (app / "config.stamp").read_text(),
            driver="simx", fmt=args.format, source=source, build=build, jobs=args.jobs)
        _same(compiler[:2], variant["compiler_records"][:2], "matmul and model runtime/backend records differ")
        effective = command("native-matmul-effective-header", [tools["g++"]["path"], "-E", "-dM", "-x", "c++",
            *compiler[1]["macro_flags"], "-include", build / "sw/VX_config.h", "/dev/null"], build, env, 30)
        report["matmul_backend_header_macros"] = validate_header_macros(effective)
        matmul_frozen = hash_artifacts(build, matmul_run.artifacts("simx"))
        matmul_binding = {"source": initial["checkout"], "backend": "simx", "format": args.format,
            "compiler_records": compiler, "artifacts": matmul_frozen, "dependencies": dependencies,
            "profile_sha256": bundle_producer._bundle.PROFILE_SHA256}
        matmul_id = qualification_id(matmul_binding)
        report["matmul_binding"] = snapshot("native-matmul-binding", matmul_binding)
        report["matmul_qualification_id"] = matmul_id
        report["matmul_compiler_records"] = compiler
        report["matmul_artifacts_before"] = matmul_frozen
        for name in matmul_run.artifacts("simx"):
            if name.endswith((".stamp", ".mk", ".h", ".vh", ".vlt")) or Path(name).name in (
                    "Makefile", "ai_matmul", "kernel.elf", "kernel.vxbin"):
                _copy(build, name, output / "artifacts/native-matmul" / name)
        _copy(build, model_run.APP + "/ai_mlp", output / "artifacts/native-model/ai_mlp")
        report["retained_native_matmul"] = _tree_records(output / "artifacts/native-matmul")
        report["retained_native_model"] = _tree_records(output / "artifacts/native-model")
        native_matmuls = {}
        report["native_matmuls"] = []
        native_env = dict(env, VORTEX_DRIVER="simx", LD_LIBRARY_PATH=str(build / "sw/runtime"))
        for case in matmul_cases:
            stable()
            raw = command("native-" + case["id"], [app / "ai_matmul", "--case", case["id"],
                "--iterations", "2", "--module", app / "kernel.vxbin", "--qualification-id", matmul_id],
                app, native_env, args.run_timeout_seconds)
            native_matmuls[case["id"]] = verify_matmul(raw, case, 2, matmul_id)
            report["native_matmuls"].append({"id": case["id"], "observations": native_matmuls[case["id"]]})
            stable()
            checkpoint()

        # The reviewed setup supports ordinary egg_info inside this exact source
        # stage. All metadata/staging writes remain outside the clean checkout.
        stage = work / "package-source"
        report["package_source_stage"] = snapshot("package-source-stage", _package_stage(source, stage, manifest))
        sdist_dir, wheel_dir = output / "packages/sdist", output / "packages/wheel"
        sdist_dir.mkdir()
        wheel_dir.mkdir()
        command("package-bound-sdist", [python, "-I", "-B", stage / "setup.py", "egg_info", "sdist",
            "--dist-dir", sdist_dir], stage, dict(package_env, VORTEX_AI_BUNDLE=str(bundle)), args.timeout_seconds)
        archives = sorted(sdist_dir.glob("*.tar.gz"))
        require(len(archives) == 1 and len(list(sdist_dir.iterdir())) == 1, "expected one bound source archive")
        sdist = archives[0]
        extracted = _extract_sdist(sdist, work / "extracted-sdist", manifest, manifest_bytes)
        report["extracted_sdist_before_build"] = snapshot("extracted-sdist-before-build", _tree_records(extracted))
        pins = ["python/p05_build/" + name for name in ("manifest.json", "source_inventory.json", "p05_build_config.h")]
        for name in pins:
            _copy(extracted, name, output / "artifacts/sdist-pin" / Path(name).name)
        stable()
        require("VORTEX_AI_BUNDLE" not in package_env, "wheel rebuild unexpectedly has the original bundle environment")
        command("package-offline-wheel", [python, "-I", "-B", extracted / "setup.py", "build",
            "--build-base", work / "package-build", "build_ext", "--parallel", "1", "bdist_wheel",
            "--dist-dir", wheel_dir, "--bdist-dir", work / "wheel-stage"],
            extracted, package_env, args.timeout_seconds)
        _same(bundle_producer._bundle.source_inventory(extracted), manifest["binding_sources"],
              "source distribution inputs changed during wheel rebuild")
        wheels = sorted(wheel_dir.glob("*.whl"))
        require(len(wheels) == 1 and len(list(wheel_dir.iterdir())) == 1, "expected one rebuilt bound wheel")
        wheel = wheels[0]
        digest = hashlib.sha256(manifest_bytes).hexdigest()
        require(("-1" + digest + "-") in wheel.name, "wheel build tag does not retain the complete bundle pin")
        wheel_rows = _wheel_inventory(wheel, manifest)
        report["wheel_inventory"] = snapshot("wheel-inventory", wheel_rows)
        package_frozen = hash_artifacts(output, [sdist.relative_to(output).as_posix(), wheel.relative_to(output).as_posix()])
        report["packages"] = package_frozen
        stable()

        venv = work / "venv"
        command("package-create-venv", [python, "-I", "-B", "-m", "venv", "--copies", venv],
                work, package_env, 120)
        venv_python = venv / "bin/python"
        venv_identity = base._file_identity(venv_python)
        require((venv_identity["sha256"], venv_identity["size_bytes"])
                == (tools["python3"]["sha256"], tools["python3"]["size_bytes"]),
                "venv interpreter bytes differ from the inventoried Python executable")
        report["venv_interpreter"] = venv_identity
        command("package-install-wheel", [venv_python, "-I", "-B", "-m", "pip", "--isolated", "install",
            "--no-index", "--no-deps", "--no-compile", "--disable-pip-version-check", wheel],
            work, package_env, 120)
        site, installed_frozen = _installed_inventory(venv, wheel_rows)
        report["installed_before"] = snapshot("installed-before", installed_frozen)
        for row in installed_frozen:
            _copy(site, row["path"], output / "artifacts/installed" / row["path"], expected=row)
        # Only this outside-checkout directory is the installed workload's cwd.
        installed_work = work / "installed-check"
        installed_work.mkdir(mode=0o700)
        script = installed_work / "p05_installed_check.py"
        _copy(source, "ci/project/p05_installed_check.py", script)
        request = {"schema_version": 1, "contract_id": "p05-installed-request-v1",
            "binding": {"backend": "simx", "format": args.format, "bundle_root": str(bundle),
                "bundle_sha256": digest, "source_sha256": manifest["binding_source_sha256"],
                "qualification_id": manifest["qualification_id"], "source_revision": manifest["source_revision"]},
            "matmul_cases": matmul_cases, "model_cases": [case["id"] for case in model_cases],
            "iterations": 2, "expected_prefix": str(venv)}
        request_path = installed_work / "request.json"
        base._write_json(request_path, request)
        report["installed_request"] = snapshot("installed-request", request)
        report["installed_script"] = hash_artifacts(installed_work, [script.name])[0]
        observations_path = installed_work / "observations.json"
        stable()
        require(not any(name in package_env for name in ("LD_PRELOAD", "LD_AUDIT", "LD_LIBRARY_PATH", "PYTHONPATH",
                                                        "PYTHONHOME", "VORTEX_AI_BUNDLE")),
                "installed parent environment contains a loader or source override")
        raw = command("installed-matrix", [venv_python, "-I", "-B", "-m", "vortex_ai.launch", "--bundle", bundle,
            "--", script, "--request", request_path, "--output", observations_path],
            installed_work, package_env, 16 * args.run_timeout_seconds + 60)
        observations = _read_json(installed_work, "observations.json")
        _copy(installed_work, "observations.json", output / "artifacts/installed-observations.json")
        report["observations"] = hash_artifacts(output, ["artifacts/installed-observations.json"])[0]
        report["comparison"] = verify_observations(observations, request, native_matmuls=native_matmuls,
            native_models=native_models, model_cases=model_cases, raw_log=raw)
        require(Path(observations["installation"]["package_file"]).parent == site / "vortex_ai",
                "observed package import differs from the independently hashed installation")
        extension = [row["path"] for row in wheel_rows if row["path"].startswith("vortex_ai/_native.")][0]
        require(Path(observations["installation"]["extension_file"]) == site / extension,
                "observed extension import differs from the rebuilt wheel")
        _same(hash_artifacts(installed_work, [script.name])[0], report["installed_script"], "installed script changed")
        _same(_read_json(installed_work, "request.json"), request, "installed request changed")
        _, after = _installed_inventory(venv, wheel_rows)
        _same(after, installed_frozen, "installed package changed during workload")
        report["installed_after"] = snapshot("installed-after", after)
        final_packages = probe_packages("package-tools-after", python, package_env)
        _same(final_packages, package_tools, "offline package prerequisites changed")
        report["package_tools_after"] = snapshot("package-tools-after", final_packages)
        stable()
        native_counts = {"matmul_runs": sum(len(rows) for rows in native_matmuls.values()),
            "model_runs": sum(len(rows) for rows in native_models.values()),
            "matmul_launches": sum(row["dispatch"]["launches"] for rows in native_matmuls.values() for row in rows),
            "model_launches": sum(stage["dispatch"]["launches_enqueued"] for rows in native_models.values()
                                  for row in rows for stage in row["trace"]["native"])}
        native_counts["total_launches"] = native_counts["matmul_launches"] + native_counts["model_launches"]
        _same(native_counts, report["comparison"]["counts"], "independent native/Python launch counts differ")
        report["native_counts"] = native_counts
        report["completed_native_and_python_launches"] = native_counts["total_launches"] * 2
        report["outcome"] = "pass"
    except (OSError, ValueError, RuntimeError, KeyError, ImportError, TypeError,
            EOFError, OverflowError, tarfile.TarError, zipfile.BadZipFile) as error:
        report.update(outcome="fail" if report["commands"] else "blocked", reason=str(error))
    except KeyboardInterrupt:
        report.update(outcome="fail", reason="interrupted")
    finally:
        if initial is not None:
            try:
                final = source_snapshot(source)
                report["source_after"] = snapshot("source-after", final)
                report["source_stable"] = final == initial
                stable()
                if tools is not None:
                    report["tools_after"] = snapshot("tools-after", base.tool_inventory(paths, env, ["simx"]))
                if matmul_frozen is not None:
                    report["matmul_artifacts_after"] = hash_artifacts(build, matmul_run.artifacts("simx"))
            except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
                report.setdefault("failure_reasons", []).append(str(error))
                report.update(outcome="fail", reason=report["reason"] or str(error))
        # Keep a fresh nested native packet and any partial package/result files
        # exactly where the failing stage left them; never delete failed evidence.
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
    parser.add_argument("--tools-dir", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--native-build", type=Path, required=True,
                        help="still-present SimX variant build from the completed P04 CLI")
    parser.add_argument("--native-output", type=Path, required=True,
                        help="completed clean P04 packet from a separate top-level invocation")
    parser.add_argument("--host-bin", type=Path)
    parser.add_argument("--verilator", type=Path, help="retained native path convention; SimX does not execute Verilator")
    parser.add_argument("--format", choices=("fp16", "bf16"), required=True)
    parser.add_argument("--jobs", type=int, choices=(1, 2), default=2)
    parser.add_argument("--timeout-seconds", type=base._timeout, default=1800, help="maximum per build timeout")
    parser.add_argument("--run-timeout-seconds", type=base._timeout, default=180, help="maximum per native comparison timeout")
    return parser


def resolve_paths(args):
    paths = base.resolve_paths(args)
    for name in ("native_build", "native_output"):
        path = base._path(getattr(args, name), existing=True)
        require(path.is_dir(), name + " must be an existing directory")
        require(not any(base._overlap(path, paths[other])
                        for other in ("source", "tools", "work", "output")),
                name + " overlaps another input/output root")
        paths[name] = path
    require(not base._overlap(paths["native_build"], paths["native_output"]),
            "native build and output roots overlap")
    require(paths["native_build"].name == "simx-" + args.format,
            "native build name does not match the selected SimX format")
    return paths


def main(argv=None):
    args = argument_parser().parse_args(argv)
    try:
        report = execute(args, resolve_paths(args))
        print(json.dumps({"outcome": report["outcome"], "reason": report["reason"],
            "report": str(Path(args.output).absolute() / "report.json"), "acceptance_claimed": False}, sort_keys=True))
        return 0 if report["outcome"] == "pass" else 1
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({"outcome": "blocked", "reason": str(error), "acceptance_claimed": False}, sort_keys=True))
        return 1


if __name__ == "__main__":
    sys.exit(main())
