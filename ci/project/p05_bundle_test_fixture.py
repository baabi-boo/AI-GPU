# SPDX-License-Identifier: Apache-2.0
"""Synthetic host-only P04 packets; no native binary or accelerator is run.

An isolated import of unchanged P04 execute writes the packet and applies its
real compiler-record, fixture, header and model-record validators. Only external
commands, Git metadata, tool inventory and resource observations are injected.
Host Python generates real headers and host g++ only preprocesses them. Every
library, executable, kernel and dependency payload is inert labeled text.
"""

from contextlib import ExitStack, contextmanager
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from unittest import mock

import p05_bundle as producer
import p04_model_contract as model_contract
from test_p02_matrix import sample
from test_p04_execution_records import result, output


ROOT = Path(__file__).resolve().parents[2]
SCOPE = "SYNTHETIC HOST-ONLY P05 PRODUCER TEST; NO NATIVE OR ACCELERATOR EXECUTION"


def write(root, name, data):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)


def record(root, name):
    raw = (root / name).read_bytes()
    return {"path": name, "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}


def save(root, name, value):
    write(root, name, json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    return record(root, name)


class SyntheticP04Packet:
    """An actual P04 report writer around labeled, nonnative process callbacks."""

    def __init__(self, directory, fmt="fp16", *, _prepared=False):
        self.area = Path(directory)
        self.source = self.area / "source"
        self.work = self.area / "work"
        self.packet = self.area / "packet"
        self.tools = self.area / "tools"
        self.fmt = fmt
        self.variant_id = "simx-" + fmt
        self.build = self.work / self.variant_id
        self.destination = self.area / "bundle"
        if not _prepared:
            self.source.mkdir()
            self.tools.mkdir()
        self.paths = {"source": self.source, "work": self.work, "output": self.packet,
                      "tools": self.tools, "host_bin": None, "verilator": self.tools / "verilator"}
        self.checkout = {"revision": "1" * 40, "tree": "2" * 40, "dirty": False,
                         "changed_paths": [], "untracked_paths": [], "blockers": []}
        self.host_cxx = shutil.which("g++")
        if self.host_cxx is None:
            raise RuntimeError("producer host tests require g++ preprocessing; no test is skipped")
        self.tool_inventory = {name: {"path": "/synthetic-host-only-tools/" + name,
                                     "scope": SCOPE}
                               for name in ("make", "clang")}
        self.tool_inventory.update({"g++": {"path": self.host_cxx, "scope": SCOPE},
                                    "python3": {"path": sys.executable, "scope": SCOPE}})
        self.native = producer.native_run
        required = set(self.native.base.TOOLING + self.native.base.CORPUS
                       + self.native.base.COPIED + self.native.operator_run.SOURCE_FILES
                       + self.native.SOURCE_FILES + tuple(model_contract.ARTIFACT_PATHS)
                       + producer._bundle.SOURCE_PATHS)
        required.update(("configure", "config.mk.in", "VERSION", ".gitmodules",
                         "VX_config.toml", "VX_types.toml", "profiles/p02-tfr.json",
                         "ci/project/p02_tensor_contract.json", "sim/rtlsim/verilator.vlt.in"))
        required.update(row["path"] for row in producer._LOADED_HELPERS)
        required.update(row["path"] for row in self.native.LOADED_HELPERS)
        for module in tuple(sys.modules.values()):
            name = getattr(module, "__file__", None)
            if name and Path(name).suffix == ".py":
                path = Path(name).resolve()
                if path.is_relative_to(ROOT / "ci/project"):
                    relative = path.relative_to(ROOT).as_posix()
                    required.add(relative)
        if not _prepared:
            for name in sorted(required):
                write(self.source, name, (ROOT / name).read_bytes())
            for name in self.native.base.DEPENDENCIES:
                write(self.source, name, SCOPE + ": inert dependency " + name + "\n")
        self.cases = [case for case in producer.load_cases(self.source) if case["format"] == fmt]
        self.process_ids = []
        if _prepared:
            self.execute_callback_packet()
        else:
            # P04 captures loaded helpers at import. Import it before test code
            # in a fresh process, matching its standalone CLI helper closure.
            bootstrap = (
                "import sys; sys.path.insert(0, sys.argv[1]); import p04_execute; "
                "from p05_bundle_test_fixture import SyntheticP04Packet; "
                "SyntheticP04Packet(sys.argv[2], sys.argv[3], _prepared=True)"
            )
            child = subprocess.run(
                [sys.executable, "-I", "-S", "-B", "-c", bootstrap,
                 str(self.source / "ci/project"), str(self.area), fmt],
                capture_output=True, text=True, timeout=45)
            if child.returncode:
                raise AssertionError("synthetic P04 host callback failed:\n" + child.stderr[-8000:])
        self.report = json.loads((self.packet / "report.json").read_text())
        if self.report["outcome"] != "pass":
            raise AssertionError("synthetic P04 callback packet failed: " + str(self.report["reason"]))
        self.process_ids = [row["id"] for row in self.report["commands"]]
        self.variant = self.report["variants"][0]
        self.binding = json.loads((self.packet / self.variant["binding"]["path"]).read_text())

    def execute_callback_packet(self):
        args = self.native.base.argument_parser().parse_args([
            "run", "--source-dir", str(self.source), "--tools-dir", str(self.tools),
            "--work-dir", str(self.work), "--output", str(self.packet),
            "--backend", "simx", "--format", self.fmt, "--jobs", "2", "--iterations", "2",
            "--timeout-seconds", "30", "--run-timeout-seconds", "30"])
        resources = {"scope": SCOPE,
                     "available_memory_bytes": self.native.BUDGET["max_rss_bytes"],
                     "free_disk_bytes": {key: self.native.BUDGET["min_free_bytes"]
                                         for key in ("source", "tools", "work", "output")}}
        with self.observations(), ExitStack() as stack:
            stack.enter_context(mock.patch.object(self.native.base, "_resources", return_value=resources))
            stack.enter_context(mock.patch.object(self.native, "run_bounded", side_effect=self.process))
            self.native.execute(args, self.paths)

    @contextmanager
    def observations(self):
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(producer, "ROOT", self.source))
            stack.enter_context(mock.patch.object(self.native.base, "collect_source",
                                                  side_effect=lambda _: copy.deepcopy(self.checkout)))
            stack.enter_context(mock.patch.object(self.native.base, "tool_inventory",
                                                  side_effect=lambda *_: copy.deepcopy(self.tool_inventory)))
            yield

    def generate_build(self):
        for name in self.native.artifacts("simx"):
            write(self.build, name, SCOPE + ": inert build artifact " + name + "\n")
        for name in self.native.base.COPIED + (self.native.APP + "/Makefile",):
            write(self.build, name, (self.source / name).read_bytes())
        write(self.build, ".config.stamp",
              f"XLEN=64 PROFILE=p02-tfr SOURCE_DIR={self.source} BUILDDIR={self.build} TOOLDIR={self.tools}\n")
        write(self.build, "config.mk", f"XLEN ?= 64\nPROFILE ?= p02-tfr\nVORTEX_HOME ?= {self.source}\n"
              f"TOOLDIR ?= {self.tools}\nOSVERSION ?= ubuntu/focal\n")
        write(self.build, "sim/rtlsim/verilator.vlt",
              (self.source / "sim/rtlsim/verilator.vlt.in").read_text().replace("@VORTEX_HOME@", str(self.source)))
        for name in ("sw/VX_config.h", "hw/VX_config.vh", "sw/VX_types.h", "hw/VX_types.vh"):
            stem = Path(name).stem
            argv = [sys.executable, "-I", "-S", "-B", str(self.source / "ci/gen_config.py"),
                    "--config=" + str(self.source / (stem + ".toml")), "--output=" + str(self.build / name),
                    "--format=" + ("cpp" if name.startswith("sw/") else "verilog"),
                    "--profile=p02-tfr" if stem == "VX_config" else "--resolved"]
            self.host_command(argv, {"PATH": "/usr/bin:/bin", "XLEN": "64"})
        for name, role in (("sw/runtime/simx_rt_config.stamp", "simx_rt"),
                           ("sw/runtime/simx_config.stamp", "simx_backend"),
                           (self.native.APP + "/config.stamp", "application")):
            text = sample(role, source=self.source, build=self.build, tools=self.tools, fmt=self.fmt)
            if role == "application":
                lines = text.splitlines()
                lines[2] = "-L" + str(self.build / "sw/runtime") + " -lvortex"
                text = "\n".join(lines) + "\n"
            write(self.build, name, text)

    @staticmethod
    def host_command(argv, environment):
        return subprocess.run(argv, env=environment, capture_output=True, text=True,
                              check=True, timeout=30).stdout

    def process(self, argv, cwd, environment, logfile, **budgets):
        name = logfile.stem
        self.process_ids.append(name)
        if budgets["timeout_seconds"] > 30:
            # P04 configure carries a fixed 120-second budget. No configure
            # process is launched; all real host subprocesses use 30 seconds.
            if not name.endswith("-configure"):
                raise AssertionError("unexpected synthetic callback timeout")
        text = SCOPE + ": injected command completion\n"
        if name.endswith("-configure"):
            self.generate_build()
        elif name.endswith(("-header", "-header-reproduce")):
            text = self.host_command(argv, environment)
        elif "--case" in argv:
            case = next(case for case in self.cases if case["id"] == argv[argv.index("--case") + 1])
            binding_id = argv[argv.index("--qualification-id") + 1]
            rows = [result(case, iteration) for iteration in range(2)]
            for row in rows:
                row.update(source_revision=self.checkout["revision"], qualification_id=binding_id)
                for stage in row["trace"]["native"]:
                    stage["dispatch"]["qualification_id"] = binding_id
            text = SCOPE + "\n" + output(rows)
        elif not (name.startswith("version-") or name.endswith(("-runtime", "-application"))):
            raise AssertionError("unexpected synthetic process: " + name)
        logfile.write_text(text, encoding="utf-8")
        raw = logfile.read_bytes()
        return {"outcome": "pass", "exit_code": 0, "cleanup_complete": True, "reason": None,
                "log_sha256": hashlib.sha256(raw).hexdigest(), "log_size_bytes": len(raw),
                "synthetic_host_only_scope": SCOPE}

    def save_report(self):
        save(self.packet, "report.json", self.report)

    def command(self, suffix):
        return next(row for row in self.report["commands"] if row["id"] == self.variant_id + "-" + suffix)

    def save_log(self, command, text):
        write(self.packet, command["log"], text)
        identity = record(self.packet, command["log"])
        command.update(log_sha256=identity["sha256"], log_size_bytes=identity["size_bytes"])
        self.save_report()

    def rehash_build(self):
        frozen = producer.hash_artifacts(self.build, self.native.artifacts("simx"))
        self.variant["artifacts_before"] = self.variant["artifacts_after"] = frozen
        for row in frozen:
            name = row["path"]
            if name.endswith((".stamp", ".mk", ".h", ".vh", ".vlt")) or Path(name).name == "Makefile":
                write(self.packet, "artifacts/" + self.variant_id + "/" + name,
                      (self.build / name).read_bytes())
        self.save_report()

    def create(self, **overrides):
        arguments = dict(source=self.source, build=self.build, native_output=self.packet,
                         fmt=self.fmt, destination=self.destination)
        arguments.update(overrides)
        with self.observations():
            return producer.create_bundle(**arguments)
