#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check all-33 native counter packets as inert retained data.

An independently supplied original ZIP digest and source revision are required.
Later source inventories require an explicit external manifest and its digest.
This reader checks consistency, not execution authenticity or qualification. It
never extracts archive members, executes retained code, opens recorded producer
paths, or rehashes the absent object/binary payloads. The reusable packet helpers
also support the separately versioned public-runtime diagnostic reader.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys

sys.dont_write_bytecode = True

from baseline_inventory import SOURCE_INPUTS
from baseline_process import LIMITATIONS as PROCESS_LIMITATIONS
from p02_matrix_records import PROFILE_SHA256
import p06_checked_execute as checked
import p06_counter_source_inventory as source_inventory_contract
import p06_replay as trusted


CONTRACT_ID = "simx-checked-counters-native-v2"
REPLAY_CONTRACT_ID = "simx-counter-diagnostics-replay-v1"
BUDGET = {"max_rss_bytes": 4 * 1024**3, "min_free_bytes": 15 * 1024**3,
          "max_log_bytes": 16 * 1024**2, "jobs": 2, "threads": 1,
          "timeouts_seconds": {"configure": 120, "build": 1800, "run": 180}}
TIMEOUTS = BUDGET["timeouts_seconds"]
HEADER_PROBE = "checked-header-probe.cpp"
HEADER_PROBE_CONTENT = b"#include <VX_config.h>\n#include <perf_counter.h>\n"
HOST_TOOLS = ("make", "g++", "gcc", "ar", "as", "ld", "bash", "python3", "executing_python")
DEPENDENCIES = (
    "third_party/softfloat/build/Linux-x86_64-GCC/softfloat.a",
    "third_party/ramulator/libramulator.so",
    "third_party/ramulator_ext/libramulator-vortex.so",
)
REPORT_FIELDS = {
    "schema_version", "contract_id", "started_at", "finished_at", "state", "outcome",
    "qualified", "ready_for_warm", "acceptance_claimed", "full_warm_coverage", "warm_execution",
    "native_prerequisites_passed", "all_available_selector_transport", "expected_revision", "paths",
    "commands", "variants", "cells", "errors", "limitations", "budget", "environment",
    "available_memory_bytes", "free_disk_bytes", "source_before", "source_after", "source_stable",
    "tools_before", "tools_after", "tools_stable", "retained_sources", "ordinary_checked_observations_equal",
}
VARIANT_FIELDS = {
    "id", "checked", "build_dir", "binary_path", "configure_command", "build_command",
    "generated_before", "generated_after", "retained_configuration",
    "compiler_stamp_before", "compiler_stamp_after", "retained_compiler_stamp",
    "diagnostic_sources_before", "diagnostic_sources_after", "retained_diagnostic_sources",
    "compiler_records", "binary_before", "binary_after", "retained_probe",
    "effective_configuration", "objects_after",
}
CELL_FIELDS = {"id", "variant", "mode", "outcome", "run_command", "run_outcome", "exit_code",
               "run_process_started", "observations"}
SOURCE_REQUIRED = tuple(dict.fromkeys((*checked.CRITICAL, *checked.MODEL_SOURCES,
                                      *checked.WRAPPER_SOURCES.values())))
# The native-v2 producer retains the entire model/common-source inventory. This
# name-list pin prevents omission of uncompiled headers or helper source bodies.
# It is SHA-256 of the sorted source-relative names, each followed by LF.
NATIVE_V2_SOURCE_INVENTORY_SHA256 = "d074477d6c6b9a0521c2a79e912b3113e9648bc73a3e6cc3dc0f3bc311106108"
LIMITATIONS = [
    "This is retained-data consistency checking, not a new native execution or producer authentication.",
    "The externally supplied ZIP digest and source revision do not independently authenticate GitHub origin.",
    "Consistent synthetic or forged records remain synthetic or forged; replay cannot establish actual execution.",
    "Retained source bytes and reported clean revision/tree/submodule identities are internally bound, not a Git tree proof.",
    "Without an external source manifest, the complete original 270-name source inventory remains pinned.",
    "An external manifest's caller-supplied digest defines expected source descriptors; it does not independently prove Git provenance or execution.",
    "Object, executable, tool and dependency payloads are absent; their recorded identities are not independently rehashed.",
    "Recorded producer paths are interpreted syntactically and are never opened, resolved or executed on this host.",
    "All-33 transport and directed guard observations do not prove complete lifetime bounds or public-runtime recovery.",
    "No terminal source proof, warm GEMM experiment, workspace performance result, hardware result or acceptance is established.",
    "Before/after identities do not defend against malicious concurrent producer filesystem writers.",
    *PROCESS_LIMITATIONS,
]
require = trusted.require
_same = trusted._same
_fields = trusted._fields
_integer = trusted._integer
_number = trusted._number


def nonacceptance_result():
    """The invariant claims for success and failure, including composed readers."""
    return {"qualified": False, "ready_for_warm": False, "warm_execution": False,
            "acceptance": False, "acceptance_claimed": False, "phase_acceptance": False,
            "performance_acceptance": False, "full_warm_coverage": False,
            "native_execution": "not_run", "retained_code_executed": False}


def _reader_sources():
    names = set(trusted.REPLAY_MODULES) | {
        "p06_replay", "p06_checked_execute", "p06_mpm_execute", "p06_counter_source_inventory",
        "baseline_inventory", "preflight", __name__}
    result = []
    for name in sorted(names):
        module = sys.modules[name]
        path = Path(module.__file__).resolve()
        filename = "p06_counter_diagnostics_replay.py" if name == __name__ else name + ".py"
        require(path == trusted.ROOT / "ci/project" / filename, "reader helper is outside the trusted repository")
        body = path.read_bytes()
        result.append({"path": "ci/project/" + filename, "sha256": hashlib.sha256(body).hexdigest(),
                       "size_bytes": len(body)})
    return sorted(result, key=lambda row: row["path"])


def source_inventory_pair(path, sha256):
    """Reject partial explicit expectations before opening an archive."""
    require((path is None) == (sha256 is None),
            "source inventory path and SHA-256 must be supplied together")


def load_expected_inventory(path, sha256, *, expected_revision, producer_contract_id):
    """Load only the caller-selected manifest; explicit failures never fall back."""
    source_inventory_pair(path, sha256)
    if path is None:
        return None
    return source_inventory_contract.load_source_inventory(path, expected_sha256=sha256,
        expected_revision=expected_revision, producer_contract_id=producer_contract_id)


def inventory_expectation(packet, path, sha256):
    """Disclose whether names or caller-pinned complete descriptors were expected."""
    external = path is not None
    return {"source": "external-manifest" if external else "original-inventory",
            "manifest_path": str(path) if external else None,
            "manifest_sha256": sha256 if external else None,
            "source_files": len(packet.sources),
            "source_names_sha256": packet.source_inventory_sha256,
            "trust_boundary": (
                "The caller-supplied manifest digest defines the expected complete source descriptors; "
                "matching revision labels do not independently prove Git/GitHub provenance, binary contents or execution."
                if external else
                "The trusted reader pins the complete original source-name inventory; retained body hashes establish "
                "archive consistency without independently proving Git/GitHub provenance, binary contents or execution.")}


class DiagnosticPacket:
    """Shared inert archive, provenance, command and model-build validation.

    Only the externally selected archive, optional external source manifest and
    trusted repository helpers are filesystem inputs. Every producer path is
    represented by PurePosixPath.
    """

    def __init__(self, view, api):
        self.view, self.api = view, api
        self.report = view.json("report.json")
        require(type(self.report) is dict, "diagnostic report is not an object")
        self.members = {"report.json"}
        self.paths, self.sources, self.tools = {}, {}, {}
        self.commands = self.report.get("commands")
        self.command_index = 0
        self.osversions = {}

    def inventory(self, rows, label, *, expected=None, sorted_paths=False):
        require(type(rows) is list and 0 < len(rows) <= 20000, label + ": invalid inventory")
        names, result = [], {}
        for row in rows:
            self.api.descriptor(row)
            require(row["path"] not in result, label + ": repeated path")
            names.append(row["path"])
            result[row["path"]] = row
        if expected is not None:
            _same(names, list(expected), label + " paths")
        if sorted_paths:
            _same(names, sorted(names), label + " order")
        return result

    def retained(self, rows, *, expected=None):
        inventory = self.inventory(rows, "retained evidence", expected=expected)
        result = {}
        for name, row in inventory.items():
            result[name] = self.view.verified(row)
            self.members.add(name)
        return result

    def identity(self, row, *, expected_path=None, resolved_equal=False):
        _fields(row, ("path", "resolved_path", "sha256", "size_bytes"), "recorded file identity")
        self.api.recorded_absolute(row["path"])
        self.api.recorded_absolute(row["resolved_path"])
        require(type(row["sha256"]) is str and trusted.SHA256.fullmatch(row["sha256"]),
                "invalid recorded file digest")
        _integer(row["size_bytes"], 1, 2**64 - 1, "recorded file size")
        if expected_path is not None:
            _same(row["path"], str(expected_path), "recorded file path")
        if resolved_equal:
            _same(row["resolved_path"], row["path"], "recorded path resolution")
        return row

    def setup(self):
        report = self.report
        _fields(report["paths"], ("source", "tools", "work", "output"), "recorded roots")
        self.paths = {name: self.api.recorded_absolute(value) for name, value in report["paths"].items()}
        for name, root in self.paths.items():
            require(re.fullmatch(r"[A-Za-z0-9_./+-]+", str(root)), "unsafe producer root")
            if name in ("work", "output"):
                require(not any(root == other or root in other.parents or other in root.parents
                                for key, other in self.paths.items() if key != name),
                        "recorded work/output roots overlap")
        _same(report["budget"], BUDGET, "fixed diagnostic budget")
        _integer(report["available_memory_bytes"], BUDGET["max_rss_bytes"], 2**64 - 1, "available memory")
        _fields(report["free_disk_bytes"], self.paths, "initial free disk")
        for value in report["free_disk_bytes"].values():
            _integer(value, BUDGET["min_free_bytes"], 2**64 - 1, "initial disk reserve")
        env = report["environment"]
        require(type(env) is dict, "sanitized environment is not an object")
        expected = {"PATH": env.get("PATH"), "HOME": str(self.paths["work"] / "home"),
            "TMPDIR": str(self.paths["work"] / "tmp"), "LANG": "C", "LC_ALL": "C", "TZ": "UTC",
            "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1", "CCACHE_DISABLE": "1",
            "MAKEFLAGS": "-j2", "THREADS": "1", "CMAKE_BUILD_PARALLEL_LEVEL": "2"}
        _same(env, expected, "sanitized environment")
        require(type(env["PATH"]) is str and 0 < len(env["PATH"]) <= 16384, "invalid recorded PATH")
        entries = env["PATH"].split(":")
        require(len(entries) == len(set(entries)) and len(entries) <= 128, "PATH is repeated or too long")
        for entry in entries:
            self.api.recorded_absolute(entry)
        require("/usr/bin" in entries and "/bin" in entries, "required PATH fallbacks are missing")
        self.environment = env
        require(type(self.commands) is list and 0 < len(self.commands) <= 64, "invalid command inventory")

    def source(self, expected_revision, *, required, inventory_sha256=None,
               expected_inventory=None, producer_contract_id=None):
        require(type(expected_revision) is str and trusted.REVISION.fullmatch(expected_revision),
                "an external 40-character source revision is required")
        _same(self.report["expected_revision"], expected_revision, "requested producer revision")
        before = self.report["source_before"]
        _same(self.report["source_after"], before, "source before/after")
        _same(self.report["source_stable"], True, "source stability")
        _fields(before, ("checkout", "files", "untracked_critical"), "source snapshot")
        _same(before["untracked_critical"], [], "untracked critical source")
        checkout = before["checkout"]
        _fields(checkout, ("revision", "tree", "dirty", "changed_paths", "untracked_paths", "submodules",
                           "pins", "blockers", "inputs", "outcome"), "source checkout")
        _same(checkout["revision"], expected_revision, "source revision")
        require(type(checkout["tree"]) is str and trusted.REVISION.fullmatch(checkout["tree"]), "invalid source tree")
        for name, expected in (("dirty", False), ("changed_paths", []), ("untracked_paths", []),
                               ("blockers", []), ("outcome", "pass")):
            _same(checkout[name], expected, "checkout " + name)
        self.sources = self.inventory(before["files"], "source files", sorted_paths=True)
        require(set(required) <= set(self.sources), "source inventory omits a required body")
        names_digest = hashlib.sha256("".join(name + "\n" for name in self.sources).encode()).hexdigest()
        if expected_inventory is not None:
            source_inventory_contract.validate_archive_sources(before["files"], expected_inventory,
                expected_revision=expected_revision, producer_contract_id=producer_contract_id)
        elif inventory_sha256 is not None:
            _same(names_digest, inventory_sha256, "versioned source inventory")
        self.source_inventory_sha256 = names_digest
        expected_retained = [dict(row, path="artifacts/source/" + row["path"]) for row in before["files"]]
        _same(self.report["retained_sources"], expected_retained, "retained source inventory")
        self.retained(expected_retained)
        for name, row in self.inventory(checkout["inputs"], "checkout inputs", expected=SOURCE_INPUTS).items():
            _same(row, self.sources.get(name), "checkout input identity")
        pins = {}
        for line in self.source_body("VERSION").decode("utf-8").splitlines():
            if line.strip() and not line.lstrip().startswith("#"):
                match = re.fullmatch(r"([A-Z][A-Z0-9_]*)=([A-Za-z0-9_.-]+)", line)
                require(match is not None and match[1] not in pins, "invalid retained VERSION")
                pins[match[1]] = match[2]
        _fields(pins, ("VORTEX_VERSION", "TOOLCHAIN_REV", "GEM5_REV", "FIRESIM_REV"), "source version pins")
        _same(checkout["pins"], pins, "checkout version pins")
        self.pins = pins
        _same(self.sources["profiles/p02-tfr.json"]["sha256"], PROFILE_SHA256, "frozen p02-tfr profile")
        submodules = checkout["submodules"]
        _fields(submodules, ("declared_count", "entries", "errors"), "submodule inventory")
        _same(submodules["errors"], [], "submodule errors")
        declarations = re.findall(r"^[ \t]*path[ \t]*=[ \t]*(\S+)[ \t]*$",
                                  self.source_body(".gitmodules").decode("utf-8"), re.MULTILINE)
        require(declarations and len(declarations) == len(set(declarations)), "submodule declarations are absent or repeated")
        _same(submodules["declared_count"], len(declarations), "declared submodule count")
        require(type(submodules["entries"]) is list and 0 < len(submodules["entries"]) <= 128,
                "submodule identities are absent or excessive")
        names = []
        for row in submodules["entries"]:
            _fields(row, ("path", "revision", "status"), "submodule identity")
            self.api.relative_name(row["path"])
            _same(row["status"], "initialized", "submodule status")
            require(type(row["revision"]) is str and trusted.REVISION.fullmatch(row["revision"]), "invalid submodule revision")
            names.append(row["path"])
        require(len(names) == len(set(names)) and set(declarations) <= set(names), "missing or repeated pinned submodule")
        require(all(any(name == declared or name.startswith(declared + "/") for declared in declarations)
                    for name in names), "unrelated submodule identity")
        _same(names, sorted(names), "submodule order")
        return before

    def source_body(self, name):
        require(name in self.sources, "missing retained source body: " + name)
        row = dict(self.sources[name], path="artifacts/source/" + name)
        self.members.add(row["path"])
        return self.view.verified(row)

    def toolchain(self):
        before = self.report["tools_before"]
        _same(self.report["tools_after"], before, "tools before/after")
        _same(self.report["tools_stable"], True, "tools stability")
        _fields(before, ("tools", "dependencies", "missing"), "tool snapshot")
        _same(before["missing"], [], "missing tools")
        selected = before["tools"]
        require(type(selected) is dict and set(HOST_TOOLS) <= set(selected)
                and set(selected) <= set(HOST_TOOLS) | {"ccache"}, "tool inventory differs")
        for name, row in selected.items():
            self.identity(row)
            path = PurePosixPath(row["path"])
            require(str(path.parent) in self.environment["PATH"].split(":"), "tool is outside the recorded PATH")
            if name != "executing_python":
                _same(path.name, name, "tool executable name")
        for key in ("resolved_path", "sha256", "size_bytes"):
            _same(selected["python3"][key], selected["executing_python"][key], "executing/PATH Python " + key)
        _fields(before["dependencies"], DEPENDENCIES, "linked dependencies")
        for name, row in before["dependencies"].items():
            self.identity(row, expected_path=self.paths["source"] / name, resolved_equal=True)
        self.tools = selected
        return before

    def command(self, name, argv, cwd, timeout, *, environment=None):
        require(self.command_index < len(self.commands), "required command is missing: " + name)
        entry = self.commands[self.command_index]
        self.command_index += 1
        _fields(entry, trusted.COMMAND_FIELDS, "command " + name)
        _same(entry["id"], name, "command order")
        _same(entry["argv"], list(map(str, argv)), "command argv " + name)
        _same(entry["cwd"], str(cwd), "command cwd " + name)
        _same(entry["environment"], self.environment if environment is None else environment, "command environment " + name)
        _same(entry["timeout_seconds"], timeout, "command timeout " + name)
        for key, expected in (("outcome", "pass"), ("exit_code", 0), ("reason", None),
                               ("process_started", True), ("cleanup_complete", True)):
            _same(entry[key], expected, "command " + name + " " + key)
        _same(entry["limitations"], list(PROCESS_LIMITATIONS), "process limitations")
        _number(entry["duration_seconds"], 0, timeout + 5, "command duration")
        _integer(entry["peak_rss_bytes"], 0, BUDGET["max_rss_bytes"], "command peak RSS")
        _integer(entry["log_size_bytes"], 0, BUDGET["max_log_bytes"], "command log bytes")
        _same(entry["log"], "logs/" + name + ".log", "command log path")
        row = {"path": entry["log"], "sha256": entry["log_sha256"], "size_bytes": entry["log_size_bytes"]}
        raw = self.retained([row])[row["path"]]
        return entry, raw.decode("utf-8")

    def version_commands(self):
        logs = {}
        for name in ("make", "g++", "python3", "executing_python"):
            _, text = self.command("version-" + name.replace("+", "p"),
                [self.tools[name]["path"], "--version"], self.paths["work"], 30)
            require(text.strip(), "version command produced no output")
            logs[name] = text
        for name in ("python3", "executing_python"):
            _same(logs[name], "Python 3.12.14\n", "pinned interpreter version")
        return logs

    def configuration(self, rows, *, build, copied=checked.COPIED, original=None):
        build = self.api.recorded_absolute(str(build))
        require(build.parent == self.paths["work"], "build root is not a direct child of work")
        names = (*checked.GENERATED, *copied)
        prefix = "artifacts/" + build.name + "/"
        retained = self.retained(rows, expected=[prefix + name for name in names])
        bodies = {name: retained[prefix + name] for name in names}
        if original is not None:
            self.inventory(original, "generated configuration", expected=names)
            _same(rows, [dict(row, path=prefix + row["path"]) for row in original], "retained configuration binding")
        for name in copied:
            _same(bodies[name], self.source_body(name), "copied source " + name)
        text = bodies["config.mk"].decode("utf-8")
        osversions = re.findall(r"^OSVERSION[ \t]*\?=[ \t]*(.*?)[ \t]*$", text, re.MULTILINE)
        require(len(osversions) == 1 and re.fullmatch(r"[A-Za-z0-9_/-]+", osversions[0]), "invalid generated OS bundle")
        osversion = osversions[0]
        values = {"VORTEX_HOME": str(self.paths["source"]), "XLEN": "64", "TOOLDIR": str(self.paths["tools"]),
                  "OSVERSION": osversion, "INSTALLDIR": str(build / "install"), "BUILDDIR": str(build),
                  "PROFILE": "p02-tfr", **self.pins}
        template = self.source_body("config.mk.in").decode("utf-8")
        for key, value in values.items():
            template = template.replace("@" + key + "@", value)
        _same(text, template, "generated config.mk template expansion")
        expected_stamp = " ".join(key + "=" + value for key, value in (
            ("XLEN", "64"), ("TOOLDIR", str(self.paths["tools"])), ("OSVERSION", osversion),
            ("PREFIX", str(build / "install")), ("PROFILE", "p02-tfr"),
            ("SOURCE_DIR", str(self.paths["source"])), ("BUILDDIR", str(build)),
            *((key, self.pins[key]) for key in ("VORTEX_VERSION", "TOOLCHAIN_REV", "GEM5_REV", "FIRESIM_REV")))) + "\n"
        _same(bodies[".config.stamp"].decode("utf-8"), expected_stamp, "generated configure stamp")
        self.osversions[str(build)] = osversion
        return bodies

    def model_build(self, *, build, binary, stamp_rows, generated_rows, compiler_records,
                    build_text, is_checked=True):
        build = self.api.recorded_absolute(str(build))
        binary = self.api.recorded_absolute(str(binary))
        prefix = "artifacts/" + build.name + "/"
        stamps = self.retained(stamp_rows, expected=[prefix + checked.STAMP])
        generated = self.retained(generated_rows, expected=[prefix + checked.GENERATED_TCU])
        words = checked.compile_flags(stamps[prefix + checked.STAMP].decode("utf-8"),
                                      checked=is_checked, source=self.paths["source"], build=build)
        recomputed = checked.parse_build_records(build_text, words, source=self.paths["source"], build=build,
            binary=binary, compiler=self.tools["g++"]["path"], source_files=set(self.sources),
            source_contents={name: self.source_body(name) for name in checked.DIAGNOSTIC_CONTENTS},
            generated_contents={checked.GENERATED_TCU: generated[prefix + checked.GENERATED_TCU]})
        object_paths = recomputed.pop("object_paths")
        require(type(compiler_records) is dict, "compiler summary is not an object")
        identities = compiler_records.get("object_identities")
        require(type(identities) is list and len(identities) == len(object_paths), "object identity inventory differs")
        for row, expected in zip(identities, object_paths):
            self.identity(row, expected_path=expected, resolved_equal=True)
        recomputed["object_identities"] = identities
        _same(compiler_records, recomputed, "recomputed compiler/link/source/object summary")
        return words, recomputed

    def finish(self):
        _same(self.command_index, len(self.commands), "trailing command inventory")
        _same(sorted(self.view.files()), sorted(self.members), "diagnostic archive member closure")


@contextmanager
def open_archive(path, sha256, *, prefix):
    """Open the external digest-pinned ZIP, checking identity again on close."""
    original_readers = _reader_sources()
    api = trusted._archive_api()
    try:
        with api.ArchiveReader(path, sha256) as archive:
            packet = DiagnosticPacket(archive.view(prefix), api)
            yield packet, archive
            _same(_reader_sources(), original_readers, "trusted reader source stability")
    except (KeyError, TypeError, IndexError, UnicodeError, OverflowError, RecursionError) as error:
        raise trusted.ReplayError("malformed retained diagnostic packet: " + str(error)) from error


def _configure_command(packet, variant, build):
    name = variant["id"] + "-configure"
    _same(variant["configure_command"], name, "variant configure binding")
    # OS selection may be explicit or auto-detected by the original configure.
    # The retained generated configuration must agree with an explicit option.
    require(packet.command_index < len(packet.commands), "configure command is missing")
    actual = packet.commands[packet.command_index]
    require(type(actual) is dict and type(actual.get("argv")) is list, "invalid configure command")
    argv = [str(packet.paths["source"] / "configure"), "--xlen=64", "--profile=p02-tfr",
            "--tooldir=" + str(packet.paths["tools"])]
    if len(actual["argv"]) == 5:
        argv.append("--osversion=" + packet.osversions[str(build)])
    packet.command(name, argv, build, TIMEOUTS["configure"])


def _variant(packet, variant, cells):
    _fields(variant, VARIANT_FIELDS, "native variant")
    name, is_checked = variant["id"], variant["id"] == "checked"
    _same(variant["checked"], is_checked, "variant guard selection")
    build = packet.paths["work"] / name
    unit, binary = build / "sim/simx", build / "sim/simx/checked_counters_test"
    _same(variant["build_dir"], str(build), "variant build root")
    _same(variant["binary_path"], str(binary), "variant binary path")
    for key in ("generated", "compiler_stamp", "diagnostic_sources", "binary"):
        _same(variant[key + "_after"], variant[key + "_before"], "before/after " + key)
    packet.configuration(variant["retained_configuration"], build=build, original=variant["generated_before"])
    _configure_command(packet, variant, build)
    build_name = name + "-build"
    _same(variant["build_command"], build_name, "variant build binding")
    _, build_text = packet.command(build_name, [packet.tools["make"]["path"], "--no-print-directory", "-j2",
        "THREADS=1", "PROFILE=p02-tfr", "CONFIGS=" + ("-D" + checked.GUARD + "=1" if is_checked else ""),
        "PERF=1", "CXX=" + packet.tools["g++"]["path"], "-f", "checked_counters.mk", binary], unit, TIMEOUTS["build"])
    for key, retained_key, paths in (("compiler_stamp", "retained_compiler_stamp", [checked.STAMP]),
                                    ("diagnostic_sources", "retained_diagnostic_sources", [checked.GENERATED_TCU])):
        packet.inventory(variant[key + "_before"], key, expected=paths)
        expected = [dict(row, path="artifacts/" + name + "/" + row["path"]) for row in variant[key + "_before"]]
        _same(variant[retained_key], expected, "retained " + key + " binding")
    words, summary = packet.model_build(build=build, binary=binary, stamp_rows=variant["retained_compiler_stamp"],
        generated_rows=variant["retained_diagnostic_sources"], compiler_records=variant["compiler_records"],
        build_text=build_text, is_checked=is_checked)
    _same(variant["objects_after"], summary["object_identities"], "object before/after identities")
    packet.identity(variant["binary_before"], expected_path=binary, resolved_equal=True)
    probe_name = "artifacts/" + name + "/" + HEADER_PROBE
    probe = packet.retained(variant["retained_probe"], expected=[probe_name])
    _same(probe[probe_name], HEADER_PROBE_CONTENT, "header probe source")
    flags = [word for word in checked.dependency_flags(words, build / checked.STAMP) if word not in ("-MMD", "-MP")]
    _, text = packet.command(name + "-header", [packet.tools["g++"]["path"], *flags,
        "-E", "-dM", "-x", "c++", build / HEADER_PROBE], unit, TIMEOUTS["configure"])
    effective = checked.verify_header(text, is_checked)
    _same(variant["effective_configuration"], effective, "recomputed effective configuration")
    results = []
    for cell in cells:
        _fields(cell, CELL_FIELDS, "native diagnostic cell")
        mode = cell["mode"]
        expected_id = name + "-" + mode
        for key, expected in (("id", expected_id), ("variant", name), ("outcome", "pass"),
                               ("run_command", expected_id), ("run_outcome", "pass"),
                               ("exit_code", 0), ("run_process_started", True)):
            _same(cell[key], expected, "cell " + key)
        entry, text = packet.command(expected_id, [packet.tools["executing_python"]["path"], "-I", "-c",
            checked.NO_CORE_WRAPPER, binary, mode], unit, TIMEOUTS["run"])
        observations = checked.verify_output(text, is_checked) if mode == "boundaries" else checked.verify_negative(text, entry, mode)
        _same(cell["observations"], observations, "recomputed diagnostic observations")
        results.append({"id": expected_id, "observations": observations})
    return {"id": name, "translation_units": summary["translation_units"], "link_count": summary["link_count"],
            "recorded_binary_identity": variant["binary_before"], "cells": results}


def replay_archive(path, sha256, *, expected_revision, prefix="checked-counters", expected_contract=CONTRACT_ID,
                   source_inventory=None, source_inventory_sha256=None):
    """Recheck one complete native-v2 packet with no execution or acceptance."""
    _same(expected_contract, CONTRACT_ID, "supported external diagnostic contract")
    require(type(expected_revision) is str and trusted.REVISION.fullmatch(expected_revision), "invalid external source revision")
    source_inventory_pair(source_inventory, source_inventory_sha256)
    with open_archive(path, sha256, prefix=prefix) as (packet, archive):
        expected_inventory = load_expected_inventory(source_inventory, source_inventory_sha256,
            expected_revision=expected_revision, producer_contract_id=CONTRACT_ID)
        report = packet.report
        _fields(report, REPORT_FIELDS, "native-v2 report")
        for key, expected in (("schema_version", 2), ("contract_id", CONTRACT_ID), ("state", "finished"),
            ("outcome", "pass"), ("qualified", False), ("ready_for_warm", False), ("acceptance_claimed", False),
            ("full_warm_coverage", False), ("warm_execution", False), ("native_prerequisites_passed", True),
            ("all_available_selector_transport", True), ("ordinary_checked_observations_equal", True), ("errors", [])):
            _same(report[key], expected, "producer " + key)
        require(trusted._timestamp(report["finished_at"]) >= trusted._timestamp(report["started_at"]), "producer timestamps are reversed")
        _same(report["limitations"], checked.LIMITATIONS, "producer limitations")
        packet.setup()
        packet.source(expected_revision, required=SOURCE_REQUIRED, inventory_sha256=NATIVE_V2_SOURCE_INVENTORY_SHA256,
                      expected_inventory=expected_inventory, producer_contract_id=CONTRACT_ID)
        packet.toolchain()
        packet.version_commands()
        require(type(report["variants"]) is list and len(report["variants"]) == 2
                and all(type(item) is dict for item in report["variants"]), "native variant inventory differs")
        _same([item.get("id") for item in report["variants"]], ["ordinary", "checked"], "native variant order")
        require(type(report["cells"]) is list and len(report["cells"]) == 7
                and all(type(item) is dict for item in report["cells"]), "native cell inventory differs")
        expected_modes = [("ordinary", "boundaries"), ("checked", "boundaries"), *(("checked", name) for name in checked.NEGATIVE)]
        _same([[cell.get("variant"), cell.get("mode")] for cell in report["cells"]],
              [list(pair) for pair in expected_modes], "native cell order")
        variants = [_variant(packet, variant, [cell for cell in report["cells"] if cell["variant"] == variant["id"]])
                    for variant in report["variants"]]
        boundaries = [{key: value for key, value in variant["cells"][0]["observations"].items() if key != "checked"}
                      for variant in variants]
        _same(boundaries[0], boundaries[1], "ordinary/checked boundary equality")
        _same(len(packet.commands), 17, "exact native command count")
        packet.finish()
        result = {"schema_version": 1, "contract_id": REPLAY_CONTRACT_ID, "producer_contract_id": CONTRACT_ID,
            "outcome": "pass", "scope": "retained-data-consistency-only", "retained_data_consistent": True,
            **nonacceptance_result(), "source_revision": expected_revision,
            "source_inventory_sha256": packet.source_inventory_sha256, "retained_source_files": len(packet.sources),
            "source_inventory_expectation": inventory_expectation(packet, source_inventory, source_inventory_sha256),
            "commands_checked": packet.command_index, "cells_checked": 7, "variants": variants,
            "transport_selectors_per_variant": 33, "source_components_per_variant": 40,
            "checks_per_variant": 6389, "half_reads_per_variant": 1788,
            "limitations": LIMITATIONS, "archive_read": archive.receipt(),
            "trusted_archive_reader": {"path": trusted.ARCHIVE_READER_PATH, "sha256": trusted.ARCHIVE_READER_SHA256},
            "trusted_replay_sources": _reader_sources()}
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--source-inventory", type=Path,
                        help="external complete source manifest; requires --source-inventory-sha256")
    parser.add_argument("--source-inventory-sha256", help="independently supplied external manifest SHA-256")
    parser.add_argument("--prefix", default="checked-counters")
    parser.add_argument("--expected-contract", default=CONTRACT_ID)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = replay_archive(args.archive, args.sha256, expected_revision=args.source_revision,
                                prefix=args.prefix, expected_contract=args.expected_contract,
                                source_inventory=args.source_inventory,
                                source_inventory_sha256=args.source_inventory_sha256)
        if args.output is None:
            print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
        else:
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
            print(json.dumps({"outcome": "pass", "scope": result["scope"], "report": str(args.output),
                              "cells_checked": result["cells_checked"], **nonacceptance_result()}))
        return 0
    except (OSError, ValueError) as error:
        print(json.dumps({"outcome": "fail", "reason": str(error), **nonacceptance_result()}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
