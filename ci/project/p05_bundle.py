#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Package one freshly qualified P04 SimX build for the copying Python binding.

This is the trusted producer, not a way to qualify arbitrary native binaries.
The completed P04 packet and its still-present source, tools, dependencies and
build must agree. Raw model logs and compiler records are checked again before
any bundle is created. A bundle does not establish Python execution or accept a
phase. The existing trusted-builder/non-adversarial-filesystem boundary applies.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import tempfile

from baseline_inventory import _probe, hash_artifacts
import p04_execute as native_run
from p03_execution_records import qualification_id, validate_records
from p04_execution_records import verify_output
from p04_fixture_adapter import load_cases, render_header
from p02_matrix_records import require, validate_header_macros


ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "p05_bundle_contract", ROOT / "python/vortex_ai/_bundle.py")
_bundle = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_bundle)

MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_FILE_BYTES = 256 * 1024 * 1024
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_NATIVE_PATHS = {
    "ramulator": ("source", "third_party/ramulator/libramulator.so"),
    "ramulator_extension": ("source", "third_party/ramulator_ext/libramulator-vortex.so"),
    "runtime": ("build", "sw/runtime/libvortex.so"),
    "simulator": ("build", "sw/runtime/libsimx.so"),
    "backend": ("build", "sw/runtime/libvortex-simx.so"),
    "module": ("build", native_run.APP + "/kernel.vxbin"),
}
_LOADED_HELPERS = hash_artifacts(ROOT, sorted({
    Path(module.__file__).resolve().relative_to(ROOT).as_posix()
    for module in tuple(sys.modules.values())
    if getattr(module, "__file__", None) and Path(module.__file__).suffix == ".py"
    and Path(module.__file__).resolve().is_relative_to(ROOT / "ci/project")
} | {"ci/project/p05_bundle.py", "python/vortex_ai/_bundle.py"}))


def _same(actual, expected, message):
    # JSON identity also distinguishes booleans from integers and 1 from 1.0.
    require(_bundle.canonical_bytes(actual) == _bundle.canonical_bytes(expected), message)


def _root(value, label, *, fresh=False):
    path = Path(os.path.abspath(value))
    require(not any(ord(char) < 32 for char in str(path)), "unsafe " + label + " path")
    require(not any(part.is_symlink() for part in (path, *path.parents)),
            label + " path contains a symlink")
    if fresh:
        require(not os.path.lexists(path) and path.parent.is_dir(),
                label + " must be new under an existing directory")
        require(path.parent.resolve(strict=True) == path.parent, "unsafe " + label + " parent")
    else:
        require(path.resolve(strict=True) == path and path.is_dir(),
                label + " must be an existing directory without symlink traversal")
    return path


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _consume(root, relative, *, limit, collect=False, sink=None):
    """Read one contained regular file, preserving identity across the read."""
    path = _bundle._relative(root, relative)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    chunks = [] if collect else None
    digest = hashlib.sha256()
    count = 0
    with os.fdopen(os.open(path, flags), "rb") as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and 0 <= before.st_size <= limit,
                "required file is nonregular or oversized: " + relative)
        while chunk := stream.read(1024 * 1024):
            count += len(chunk)
            require(count <= limit, "required file grew beyond its limit: " + relative)
            digest.update(chunk)
            if collect:
                chunks.append(chunk)
            if sink is not None:
                sink.write(chunk)
        after = os.fstat(stream.fileno())
    current = _bundle._relative(root, relative).stat(follow_symlinks=False)
    require(_stamp(before) == _stamp(after) == _stamp(current) and count == before.st_size,
            "required file changed while reading: " + relative)
    return ({"path": relative, "sha256": digest.hexdigest(), "size_bytes": count},
            _stamp(before), b"".join(chunks) if collect else None)


class _Inputs:
    """Remember all source/build/packet reads until publication has completed."""

    def __init__(self):
        self.seen = {}

    def observe(self, root, relative, *, limit=MAX_FILE_BYTES, collect=False, sink=None):
        record, stamp, data = _consume(root, relative, limit=limit, collect=collect, sink=sink)
        key = (root, relative)
        previous = self.seen.get(key)
        require(previous is None or (record, stamp) == previous[:2],
                "input changed between observations: " + relative)
        self.seen[key] = (record, stamp, min(limit, previous[2]) if previous else limit)
        return data if collect else record

    def read(self, root, relative, *, limit=MAX_JSON_BYTES):
        return self.observe(root, relative, limit=limit, collect=True)

    def records(self, root, names, *, limit=MAX_FILE_BYTES):
        require(len(names) == len(set(names)), "duplicate input path")
        return [self.observe(root, name, limit=limit) for name in names]

    def stable(self):
        for (root, relative), (expected, stamp, limit) in self.seen.items():
            actual, current, _ = _consume(root, relative, limit=limit)
            require((actual, current) == (expected, stamp),
                    "input changed during bundle production: " + relative)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON field: " + key)
        result[key] = value
    return result


def _number(token):
    value = float(token)
    require(math.isfinite(value), "nonfinite JSON value")
    return value


def _json(raw, label):
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                          parse_float=_number, parse_constant=_number)
    except (UnicodeError, ValueError, RecursionError, OverflowError) as error:
        raise ValueError("invalid strict JSON in " + label) from error


def _record(row):
    require(type(row) is dict and set(row) == {"path", "sha256", "size_bytes"},
            "invalid native file record")
    require(type(row["path"]) is str and type(row["sha256"]) is str
            and _HEX64.fullmatch(row["sha256"]), "invalid native file identity")
    require(type(row["size_bytes"]) is int and 0 <= row["size_bytes"] <= MAX_FILE_BYTES,
            "invalid native file size")


def _records(rows):
    require(type(rows) is list and rows, "missing native file inventory")
    for row in rows:
        _record(row)
    require(len({row["path"] for row in rows}) == len(rows), "duplicate native file record")
    return rows


def _snapshot(inputs, output, row, relative):
    _record(row)
    require(row["path"] == relative, "unexpected snapshot reference: " + relative)
    raw = inputs.read(output, relative)
    _same(inputs.observe(output, relative), row, "snapshot hash or size differs: " + relative)
    return _json(raw, relative)


def _commands(inputs, output, report):
    rows = report.get("commands")
    require(type(rows) is list and rows, "native command results are missing")
    commands = {}
    for row in rows:
        require(type(row) is dict and type(row.get("id")) is str
                and native_run.base.CASE_ID.fullmatch(row["id"])
                and row["id"] not in commands, "invalid or duplicate native command")
        require(row.get("outcome") == "pass" and type(row.get("exit_code")) is int
                and row["exit_code"] == 0 and row.get("cleanup_complete") is True
                and row.get("reason") is None, "native command did not complete successfully")
        require(row.get("log") == "logs/" + row["id"] + ".log", "unexpected native log path")
        actual = inputs.observe(output, row["log"], limit=native_run.BUDGET["max_log_bytes"])
        require(type(row.get("log_size_bytes")) is int
                and row["log_size_bytes"] == actual["size_bytes"]
                and row.get("log_sha256") == actual["sha256"], "native command log changed")
        require(type(row.get("argv")) is list and row["argv"]
                and all(type(arg) is str and arg for arg in row["argv"]), "invalid native command argv")
        require(type(row.get("environment")) is dict
                and all(type(key) is str and type(value) is str
                        for key, value in row["environment"].items()), "invalid native command environment")
        commands[row["id"]] = row
    return commands


def _generated_headers(inputs, source, build):
    """Regenerate all four headers without modifying the completed build."""
    environment = {"PATH": os.defpath, "XLEN": "64", "LANG": "C", "LC_ALL": "C",
                   "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    with tempfile.TemporaryDirectory(prefix="p05-bundle-headers-") as temporary:
        for relative in ("sw/VX_config.h", "hw/VX_config.vh", "sw/VX_types.h", "hw/VX_types.vh"):
            stem = Path(relative).stem
            destination = Path(temporary) / Path(relative).name
            argv = [sys.executable, "-I", "-S", "-B", str(source / "ci/gen_config.py"),
                    "--config=" + str(source / (stem + ".toml")),
                    "--format=" + ("cpp" if relative.startswith("sw/") else "verilog"),
                    "--output=" + str(destination),
                    "--profile=p02-tfr" if stem == "VX_config" else "--resolved"]
            code, _ = _probe(argv, cwd=temporary, environment=environment, timeout=30)
            require(code == 0, "cannot reproduce generated native header: " + relative)
            require(destination.read_bytes() == inputs.read(build, relative),
                    "generated native header differs from current source: " + relative)


def _retained_sources(inputs, source, output, report, source_files):
    rows = _records(report.get("retained_sources"))
    required = set(native_run.base.TOOLING + native_run.base.CORPUS
                   + native_run.operator_run.SOURCE_FILES + native_run.SOURCE_FILES
                   + ("profiles/p02-tfr.json",))
    loaded = _records(report.get("loaded_helpers"))
    _same(inputs.records(source, [row["path"] for row in loaded]), loaded,
          "native runner/helper source changed")
    source_index = {row["path"]: row for row in source_files}
    for row in loaded:
        _same(source_index.get(row["path"]), row,
              "native loaded helper is absent from or differs from the source snapshot: " + row["path"])
    required.update(row["path"] for row in loaded)
    retained = set()
    for row in rows:
        prefix = "artifacts/source/"
        require(row["path"].startswith(prefix), "retained source reference escapes its source inventory")
        relative = row["path"][len(prefix):]
        actual = inputs.observe(source, relative)
        expected = dict(actual, path=row["path"])
        _same(inputs.observe(output, row["path"]), expected, "retained native source differs")
        _same(row, expected, "retained native source identity differs")
        retained.add(relative)
    require(required <= retained, "native packet omits required runner or source bodies")


def create_bundle(*, source, build, native_output, fmt, destination):
    """Return the exact manifest after creating a new, verified native bundle.

    ``native_output`` is an unmodified completed P04 output directory. ``build``
    must be its original, still-present ``simx-<format>`` build. No development
    packet, shortened model selection, caller-defined binding or existing output
    directory is accepted. Failure leaves no qualified manifest in a new output.
    """
    require(type(fmt) is str and fmt in ("fp16", "bf16"), "unsupported bundle format")
    source = _root(source, "source")
    build = _root(build, "build")
    output = _root(native_output, "native output")
    destination = _root(destination, "destination", fresh=True)
    require(source == ROOT, "run the bundle producer from the selected source checkout")
    roots = (source, build, output, destination)
    require(not any(native_run.base._overlap(left, right)
                    for index, left in enumerate(roots) for right in roots[index + 1:]),
            "source, build, packet and bundle roots must be separate")
    require(set(_NATIVE_PATHS) == set(_bundle.ROLES), "producer and bundle artifact roles differ")
    inputs = _Inputs()
    _same(inputs.records(source, [row["path"] for row in _LOADED_HELPERS]), _LOADED_HELPERS,
          "executing producer/helper bytes changed after import")
    report = _json(inputs.read(output, "report.json"), "native report")
    require(type(report) is dict and type(report.get("schema_version")) is int
            and report["schema_version"] == 1
            and report.get("contract_id") == "p04-managed-model-execution-v1",
            "unsupported native execution packet")
    require(report.get("state") == "finished" and report.get("outcome") == "pass"
            and report.get("reason") is None and report.get("development") is False
            and report.get("acceptance_claimed") is False and report.get("phase_complete") is False,
            "bundle requires a completed, passing, nondevelopment P04 packet")
    require(type(report.get("iterations")) is int and report["iterations"] == 2,
            "bundle qualification requires both model output poisons")
    require(report.get("source_stable") is True, "native packet did not retain stable source")
    initial = native_run.source_snapshot(source)
    native_run.base._source_ok(initial, False)
    for key, relative in (("source_before", "snapshots/source-before.json"),
                          ("source_after", "snapshots/source-after.json")):
        _same(_snapshot(inputs, output, report.get(key), relative), initial,
              "native packet does not match the current clean source: " + key)
    _same(inputs.records(source, [row["path"] for row in _records(initial["files"])]),
          initial["files"], "source snapshot changed while reading")
    binding_sources = _bundle.source_inventory(source)
    for row in binding_sources:
        _same(inputs.observe(source, row["path"]),
              {"path": row["path"], "sha256": row["sha256"], "size_bytes": row["size"]},
              "binding source changed while reading")
    _retained_sources(inputs, source, output, report, initial["files"])
    require(inputs.observe(source, "profiles/p02-tfr.json")["sha256"] == _bundle.PROFILE_SHA256,
            "frozen native profile changed")
    fixture = inputs.observe(source, "ci/project/fixtures/p04_tiny_mlp_v1.json")
    require(fixture["sha256"] == _bundle.FIXTURE_SHA256
            and report.get("fixture_sha256") == _bundle.FIXTURE_SHA256, "frozen model fixture changed")
    cases = load_cases(source)
    require(inputs.read(source, native_run.APP + "/p04_fixtures.h") == render_header(source).encode("utf-8"),
            "generated model fixture header is stale")
    selected = [case for case in cases if case["format"] == fmt]
    require(len(selected) == 5, "expected all five frozen model families")
    variants = report.get("variants")
    require(type(variants) is list and variants, "native variant inventory is missing")
    variant_ids = []
    for row in variants:
        require(type(row) is dict and row.get("backend") in native_run.base.BACKENDS
                and row.get("format") in native_run.base.FORMATS
                and row.get("id") == row["backend"] + "-" + row["format"]
                and row.get("outcome") == "pass", "invalid or unfinished native variant")
        variant_ids.append(row["id"])
    require(len(set(variant_ids)) == len(variant_ids), "duplicate native variant")
    variant_id = "simx-" + fmt
    require(variant_id in variant_ids, "selected native variant is missing")
    variant = variants[variant_ids.index(variant_id)]
    native_cases = variant.get("cases")
    require(type(native_cases) is list and all(type(row) is dict for row in native_cases)
            and [row.get("id") for row in native_cases] == [case["id"] for case in selected],
            "native variant must contain all five cases exactly once in fixture order")
    fixture_cases = _snapshot(inputs, output, report.get("fixture_snapshot"), "snapshots/fixtures.json")
    require(type(report.get("case_ids")) is list
            and len(set(report["case_ids"])) == len(report["case_ids"]), "duplicate or missing native case selection")
    expected_cases = [case for case in cases if case["id"] in report["case_ids"]]
    require([case["id"] for case in expected_cases] == report["case_ids"]
            and all(case["id"] in report["case_ids"] for case in selected), "native case selection differs")
    _same(fixture_cases, expected_cases, "retained native fixture selection differs")

    paths = report.get("paths")
    require(type(paths) is dict and paths.get("source") == str(source)
            and paths.get("work") == str(build.parent) and build.name == variant_id,
            "supplied build is not the native packet's original variant build")
    tool_paths = dict(paths, source=source, work=build.parent, output=output,
                      tools=_root(paths.get("tools"), "tools"))
    tool_paths["host_bin"] = _root(paths["host_bin"], "host tools") if paths.get("host_bin") else None
    tool_paths["verilator"] = Path(paths["verilator"]) if paths.get("verilator") else None
    budget = report.get("budget")
    require(type(budget) is dict and type(budget.get("jobs")) is int and budget["jobs"] in (1, 2),
            "native build job count is missing or unsupported")
    jobs = budget["jobs"]
    for key, value in native_run.BUDGET.items():
        require(type(budget.get(key)) is int and budget[key] == value, "native resource budget differs")
    env = native_run.base.clean_environment(tool_paths, jobs)
    env.pop("HOME", None)
    backends = sorted({row["backend"] for row in variants})
    tools = native_run.base.tool_inventory(tool_paths, env, backends)
    for key, relative in (("tools_before", "snapshots/tools-before.json"),
                          ("tools_after", "snapshots/tools-after.json")):
        _same(_snapshot(inputs, output, report.get(key), relative), tools, "native tools changed: " + key)
    commands = _commands(inputs, output, report)
    command_ids = [variant_id + "-" + suffix for suffix in (
        "configure", "header", "cpp-header-reproduce", "verilog-header-reproduce",
        "runtime", "application", "effective-header")]
    command_ids += [variant_id + "-" + case["id"] for case in selected]
    require(all(name in commands for name in command_ids), "native variant lacks required commands")
    require({name for name in commands if name.startswith(variant_id + "-")} == set(command_ids),
            "unexpected or repeated selected native variant commands")
    configure = commands[variant_id + "-configure"]
    _same(configure["argv"], [str(source / "configure"), "--xlen=64", "--profile=p02-tfr",
                             "--osversion=ubuntu/focal", "--tooldir=" + str(tool_paths["tools"])],
          "native configure invocation differs")
    require(configure.get("cwd") == str(build), "native configure used a different build")
    _same(configure["environment"], env, "native configure environment differs")
    frozen = inputs.records(build, native_run.artifacts("simx"))
    for key in ("artifacts_before", "artifacts_after"):
        _same(variant.get(key), frozen, "native build artifact inventory differs: " + key)
    for row in frozen:
        name = row["path"]
        if name.endswith((".stamp", ".mk", ".h", ".vh", ".vlt")) or Path(name).name == "Makefile":
            retained = "artifacts/" + variant_id + "/" + name
            _same(inputs.observe(output, retained), dict(row, path=retained),
                  "retained native generated/configuration body differs: " + name)
    dependencies = inputs.records(source, native_run.base.DEPENDENCIES)
    _same(report.get("dependencies_before"), dependencies, "native dependencies changed")
    inputs.records(build, native_run.base.COPIED)
    native_run.base._generated_identity(build, source, tool_paths["tools"])
    require(inputs.read(build, native_run.APP + "/Makefile") == inputs.read(source, native_run.APP + "/Makefile"),
            "generated native model Makefile differs from source")
    _generated_headers(inputs, source, build)
    compiler = validate_records(
        inputs.read(build, "sw/runtime/simx_rt_config.stamp").decode("utf-8"),
        inputs.read(build, "sw/runtime/simx_config.stamp").decode("utf-8"),
        inputs.read(build, native_run.APP + "/config.stamp").decode("utf-8"),
        driver="simx", fmt=fmt, source=source, build=build, jobs=jobs)
    _same(variant.get("compiler_records"), compiler, "native compiler records changed")
    for suffix, key in (("header", "header_macros"), ("effective-header", "backend_header_macros")):
        text = inputs.read(output, commands[variant_id + "-" + suffix]["log"]).decode("utf-8")
        _same(variant.get(key), validate_header_macros(text), "native effective header differs")
    binding = _snapshot(inputs, output, variant.get("binding"), "snapshots/" + variant_id + "-binding.json")
    expected_binding = {"source": initial["checkout"], "backend": "simx", "format": fmt,
                        "compiler_records": compiler, "artifacts": frozen, "dependencies": dependencies,
                        "profile_sha256": _bundle.PROFILE_SHA256,
                        "fixture_sha256": _bundle.FIXTURE_SHA256, "model_id": "p04-tiny-mlp-v1"}
    _same(binding, expected_binding, "native binding differs from actual source, records or artifacts")
    binding_id = qualification_id(binding)
    require(variant.get("qualification_id") == binding_id, "native binding hash differs")
    app = build / native_run.APP
    build_env = dict(env, CONFIGS=f"-DITYPE={fmt} -DOTYPE=fp32 -DKUNROLL=1")
    make = [tools["make"]["path"], "--no-print-directory", "-j" + str(jobs),
            "THREADS=" + str(jobs), "VERILATOR_PATH=" + str(tool_paths["verilator"])]
    for suffix, target in (("runtime", "runtime-simx"), ("application", "all")):
        command = commands[variant_id + "-" + suffix]
        _same(command["argv"], make + [target], "native build invocation differs")
        _same(command["environment"], build_env, "native build environment differs")
        require(command.get("cwd") == str(app), "native build used a different application directory")
    for case, saved in zip(selected, native_cases):
        command = commands[variant_id + "-" + case["id"]]
        argv = [str(app / "ai_mlp"), "--case", case["id"], "--iterations", "2",
                "--module", str(app / "kernel.vxbin"), "--qualification-id", binding_id,
                "--backend", "simx", "--source-revision", initial["checkout"]["revision"]]
        _same(command["argv"], argv, "native model invocation differs")
        _same(command["environment"], dict(env, VORTEX_DRIVER="simx", LD_LIBRARY_PATH=str(build / "sw/runtime")),
              "native model launch environment differs")
        require(command.get("cwd") == str(app) and saved.get("outcome") == "pass",
                "native case was not completed in its qualified application directory")
        observations = verify_output(inputs.read(output, command["log"]).decode("utf-8"), case, 2,
                                     binding_id, backend="simx", source_revision=initial["checkout"]["revision"],
                                     fixture_sha256=_bundle.FIXTURE_SHA256)
        _same(saved.get("observations"), observations, "native report observations differ from raw model logs")

    manifest = {"schema_version": 1, "contract_id": _bundle.CONTRACT_ID, "backend": "simx", "format": fmt,
                "source_revision": initial["checkout"]["revision"], "source_tree": initial["checkout"]["tree"],
                "binding_sources": binding_sources, "binding_source_sha256": _bundle.inventory_digest(binding_sources),
                "profile_sha256": _bundle.PROFILE_SHA256, "fixture_sha256": _bundle.FIXTURE_SHA256,
                "qualification_id": binding_id, "native_binding": binding, "artifacts": []}
    root_map = {"source": source, "build": build}
    for role, relative in _bundle.ROLES.items():
        origin, original = _NATIVE_PATHS[role]
        row = inputs.observe(root_map[origin], original)
        manifest["artifacts"].append({"role": role, "path": relative,
                                      "sha256": row["sha256"], "size": row["size_bytes"]})
    _bundle._validate_manifest(manifest)
    raw_manifest = _bundle.canonical_bytes(manifest)
    require(len(raw_manifest) <= 4 * 1024 * 1024, "bundle manifest exceeds its size bound")
    inputs.stable()
    _root(destination, "destination", fresh=True)
    destination.mkdir(mode=0o700)
    manifest_written = False
    try:
        (destination / "lib").mkdir(mode=0o700)
        for row in manifest["artifacts"]:
            origin, original = _NATIVE_PATHS[row["role"]]
            target = _bundle._relative(destination, row["path"])
            with target.open("xb") as stream:
                inputs.observe(root_map[origin], original, sink=stream)
                stream.flush()
                os.fsync(stream.fileno())
        _bundle.validate_files(destination, manifest)
        _same(native_run.source_snapshot(source), initial, "source changed during bundle copying")
        _same(_bundle.source_inventory(source), binding_sources, "binding source changed during bundle copying")
        _same(native_run.base.tool_inventory(tool_paths, env, backends), tools, "tools changed during bundle copying")
        inputs.stable()
        with (destination / "manifest.json").open("xb") as stream:
            manifest_written = True
            stream.write(raw_manifest)
            stream.flush()
            os.fsync(stream.fileno())
        root, digest, checked = _bundle.read_manifest(destination)
        require(digest == hashlib.sha256(raw_manifest).hexdigest(), "published manifest changed")
        _bundle.validate_files(root, checked)
        return manifest
    except BaseException:
        if manifest_written:
            (destination / "manifest.json").unlink(missing_ok=True)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=ROOT)
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("--native-output", type=Path, required=True)
    parser.add_argument("--format", dest="fmt", choices=("fp16", "bf16"), required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        manifest = create_bundle(source=args.source_dir, build=args.build_dir,
                                 native_output=args.native_output, fmt=args.fmt, destination=args.destination)
        path = Path(os.path.abspath(args.destination)) / "manifest.json"
        print(json.dumps({"outcome": "pass", "manifest": str(path),
                          "sha256": hashlib.sha256(_bundle.canonical_bytes(manifest)).hexdigest(),
                          "qualification_id": manifest["qualification_id"], "acceptance_claimed": False}))
        return 0
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as error:
        print(json.dumps({"outcome": "blocked", "reason": str(error), "acceptance_claimed": False}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
