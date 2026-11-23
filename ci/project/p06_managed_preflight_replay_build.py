# SPDX-License-Identifier: Apache-2.0
"""Reconstruct managed-preflight build identities without executing packet data."""

from pathlib import PurePosixPath
import re

from baseline_packet_contract import _stamp_flags
from p02_matrix_records import DISABLED, PROFILE_SHA256
from p03_execution_records import qualification_id
from p06_compiler_records import validate_header_macros
from p06_managed_preflight_application_build import validate_application_build
from p06_managed_preflight_backend_build import validate_backend_build
from p06_managed_preflight_generated import validate_generated_headers, validate_generated_flags
import p06_managed_preflight_build as build_records
import p06_managed_preflight_contract as manifest
import p06_managed_preflight_execute as producer
from p06_replay import COPIED, GENERATED, _fields, _integer, _same, require


APP = manifest.APP
HEADER_PROBE = producer.HEADER_PROBE
BINARY_FILES = producer.BINARY_FILES
BACKEND_STAMPS = ("sw/runtime/simx_rt_config.stamp", "sw/runtime/simx_config.stamp",
                  build_records.BACKEND_LINK_STAMP)


def artifact_names(build):
    objects = tuple(build_records.expected_object(name, str(build)).relative_to(build).as_posix()
                    for name in build_records.MODEL_SOURCES)
    return tuple(sorted(set((*GENERATED, *COPIED, *BINARY_FILES, *objects,
        APP + "/Makefile", APP + "/backend.mk", APP + "/config.stamp", HEADER_PROBE,
        *BACKEND_STAMPS))))


class BuildReplayMixin:
    def generated(self):
        row = self.variant
        self.artifacts = row["artifacts_before"]
        self.frozen = self.inventory(self.artifacts, "frozen artifacts", expected=artifact_names(self.build))
        for value in self.frozen.values():
            _integer(value["size_bytes"], 1, self.api.MEMBER_BYTES, "frozen artifact bytes")
        _same(row["artifacts_after"], self.artifacts, "artifact stability")
        generated = self.inventory(row["generated_identity"], "generated identity", expected=GENERATED + COPIED)
        for name, value in generated.items():
            _same(value, self.frozen[name], "generated file identity")
        configured = sorted((*GENERATED, *COPIED, APP + "/Makefile", APP + "/backend.mk"))
        backend = sorted((*configured, HEADER_PROBE, *BACKEND_STAMPS))
        frozen = sorted((*backend, APP + "/config.stamp"))
        stages = row["retained_builds"]
        require(type(stages) is list and len(stages) == 3, "missing retained build stages")
        self.stages = {}
        for stage, (label, names) in zip(stages, (("configured", configured), ("backend", backend), ("frozen", frozen))):
            _fields(stage, ("stage", "files"), "retained stage")
            _same(stage["stage"], label, "build stage order")
            prefix = "artifacts/" + self.variant_id + "/" + label + "/"
            values = self.inventory(stage["files"], "build " + label,
                                    expected=[prefix + name for name in names])
            self.stages[label] = {}
            for name in names:
                value = values[prefix + name]
                _same(value, dict(self.frozen[name], path=prefix + name), "retained build identity")
                self.verified(value, prefix + name)
                self.stages[label][name] = value
        _same(self.build_body(HEADER_PROBE), producer.HEADER_PROBE_CONTENT, "include probe")
        for name in (*COPIED, APP + "/Makefile", APP + "/backend.mk"):
            _same(self.build_body(name), self.source_body(name), "copied source " + name)
        self._configuration_text()
        prefix = "artifacts/" + self.variant_id + "/binaries/"
        self.binary_payloads = self.inventory(row["retained_binary_payloads"], "binary payloads",
                                             expected=[prefix + name for name in BINARY_FILES])
        for name in BINARY_FILES:
            value = self.binary_payloads[prefix + name]
            _same(value, dict(self.frozen[name], path=prefix + name), "retained binary identity")
            self.payload(value, prefix + name)
        self.libraries = {name: str(self.build / "sw/runtime" / name)
                          for name in ("libvortex.so", "libvortex-simx.so", "libsimx.so")}
        self.libraries.update({
            "libramulator.so": str(self.paths["source"] / "third_party/ramulator/libramulator.so"),
            "libramulator-vortex.so": str(self.paths["source"] / "third_party/ramulator_ext/libramulator-vortex.so")})
        _same(row["expected_loaded_libraries"], self.libraries, "selected loaded-library paths")

    def _configuration_text(self):
        names = ("VORTEX_VERSION", "TOOLCHAIN_REV", "GEM5_REV", "FIRESIM_REV")
        pairs = []
        for line in self.source_body("VERSION").decode("utf-8").splitlines():
            match = re.fullmatch(r"([A-Z][A-Z0-9_]*)=([A-Za-z0-9_.+-]+)", line)
            require(match is not None, "invalid retained version pin")
            pairs.append(match.groups())
        _same([name for name, _ in pairs], list(names), "version pin inventory")
        pins = dict(pairs)
        source, build, tools = self.paths["source"], self.build, self.paths["tools"]
        stamp = {"XLEN": "64", "TOOLDIR": str(tools), "OSVERSION": "ubuntu/focal",
                 "PREFIX": str(build / "install"), "PROFILE": "p02-tfr",
                 "SOURCE_DIR": str(source), "BUILDDIR": str(build), **pins}
        _same(self.build_body(".config.stamp"),
              (" ".join(name + "=" + value for name, value in stamp.items()) + "\n").encode(),
              "complete configure stamp")
        replacements = {"VORTEX_HOME": str(source), "XLEN": "64", "TOOLDIR": str(tools),
                        "OSVERSION": "ubuntu/focal", "INSTALLDIR": str(build / "install"),
                        "BUILDDIR": str(build), **pins, "PROFILE": "p02-tfr"}
        config = self.source_body("config.mk.in").decode("utf-8")
        for name, value in replacements.items():
            config = config.replace("@" + name + "@", value)
        _same(self.build_body("config.mk"), config.encode(), "complete generated configuration")
        _same(self.build_body("sim/rtlsim/verilator.vlt"),
              self.source_body("sim/rtlsim/verilator.vlt.in").replace(b"@VORTEX_HOME@", str(source).encode()),
              "generated Verilator configuration")
        self.generated_headers = validate_generated_headers(source_body=self.source_body, build_body=self.build_body)

    def compiler_commands(self):
        source, build, env = self.paths["source"], self.build, self.env
        self.command(self.variant_id + "-configure", [source / "configure", "--xlen=64", "--profile=p02-tfr",
                     "--osversion=ubuntu/focal", "--tooldir=" + str(self.paths["tools"])], build, env,
                     self.limits["configure_timeout_seconds"])
        preprocessor = [self.tools["g++"]["path"], "-E", "-dM", "-x", "c++"]
        tail = ["-include", build / "sw/VX_config.h", "/dev/null"]
        text, _ = self.command(self.variant_id + "-header", [*preprocessor, "-DVX_CFG_XLEN=64",
                               "-DVX_CFG_XLEN_64", *tail], build, env, 30, read=True)
        initial = validate_header_macros(text)
        _same(self.variant["header_macros"], initial, "initial header macros")
        for language, relative in (("cpp", "sw/VX_config.h"), ("verilog", "hw/VX_config.vh")):
            self.command(self.variant_id + "-" + language + "-header-reproduce", [self.tools["python3"]["path"],
                         source / "ci/gen_config.py", "--config=" + str(source / "VX_config.toml"), "--profile=p02-tfr",
                         "--format=" + language, "--output=" + str(build / PurePosixPath(HEADER_PROBE).parent / PurePosixPath(relative).name)],
                         build, dict(env, XLEN="64"), 30)
        raw_flags = "-DITYPE=" + self.fmt + " -DOTYPE=fp32 -DKUNROLL=1"
        text, _ = self.command(self.variant_id + "-expected-flags", [self.tools["python3"]["path"],
                               source / "ci/gen_config.py", "--config=" + str(source / "VX_config.toml"),
                               "--profile=p02-tfr", "--xlen=64", "--format=cflags",
                               "--cflags=" + raw_flags + " -DVX_CFG_XLEN=64"], build, env, 30, read=True)
        self.generated_flags = validate_generated_flags(text, source_body=self.source_body, fmt=self.fmt)
        flags = _stamp_flags(text, "independently generated preflight flags")
        require(flags and all(flag.startswith("-D") for flag in flags), "generated flags contain non-definitions")
        text, _ = self.command(self.variant_id + "-expected-expanded-header", [*preprocessor, *flags,
                               *("-D" + name + "_DISABLE" for name in DISABLED), *tail],
                               build, env, 30, read=True)
        expanded = dict(validate_header_macros(text), **{build_records.GUARD: "1"})
        backend = dict(initial, PERF_ENABLE="1", **{name + "_DISABLE": "1" for name in DISABLED},
                       **{build_records.GUARD: "1"})
        _same(self.variant["expected_expanded_header_macros"], expanded, "expanded configuration")
        _same(self.variant["expected_backend_header_macros"], backend, "backend configuration")
        make = [self.tools["make"]["path"], "--no-print-directory", "-j" + str(self.limits["jobs"]),
                "THREADS=1", "CXX=" + self.tools["g++"]["path"]]
        current = dict(env, CONFIGS=raw_flags + " " + build_records.GUARD_FLAG, PERF="1")
        runtime, app = build / "sw/runtime", build / APP
        backend_text, backend_command = self.command(self.variant_id + "-backend",
            [*make, "CC=" + self.tools["gcc"]["path"], "DESTDIR=" + str(runtime),
             "-f", app / "backend.mk", runtime / "libvortex-simx.so"],
            runtime / "simx", current, self.limits["build_timeout_seconds"], read=True)
        runtime_stamp = self.build_body(BACKEND_STAMPS[0]).decode("utf-8")
        model_stamp = self.build_body(BACKEND_STAMPS[1]).decode("utf-8")
        link_stamp = self.build_body(BACKEND_STAMPS[2]).decode("utf-8")
        self.backend_build = validate_backend_build(backend_text, runtime_stamp, model_stamp, link_stamp,
            source=str(source), build=str(build), compiler=self.tools["g++"]["path"],
            make=self.tools["make"]["path"], fmt=self.fmt, source_files=list(self.sources), source_body=self.source_body)
        self.model_build = self.backend_build["model_build_records"]
        _same(self.variant["model_build_records"], self.model_build, "original model build records")
        _same(self.variant["backend_build_command"], backend_command["id"], "backend command binding")
        application_text, application_command = self.command(self.variant_id + "-application",
            [*make, "--output-sync=target", "all"], app, current, self.limits["build_timeout_seconds"], read=True)
        app_stamp = self.build_body(APP + "/config.stamp").decode("utf-8")
        self.host_build = producer.validate_host_build(application_text, app_stamp,
            source=source, build=build, compiler=self.tools["g++"]["path"])
        _same(self.variant["host_build_records"], self.host_build, "original host build records")
        _same(self.variant["application_build_command"], application_command["id"], "application command binding")
        self.compiler = build_records.validate_records(runtime_stamp, model_stamp, app_stamp,
            fmt=self.fmt, source=str(source), build=str(build), jobs=self.limits["jobs"])
        _same(self.variant["compiler_records"], self.compiler, "independent original compiler records")
        self.application_build = validate_application_build(application_text, app_stamp,
            source=source, build=build, tools_root=self.paths["tools"], tools=self.tools, fmt=self.fmt,
            compiler_records=self.compiler, source_body=self.source_body)
        self.effective = {}
        directories = {"runtime": runtime / "simx", "backend_cpp": build / "sim/simx", "kernel": app, "host": app}
        for record in self.compiler:
            role = record["role"]
            command_id = self.variant_id + "-" + role + "-header"
            text, _ = self.command(command_id, [*preprocessor, *record["macro_flags"],
                                   *("-I" + name for name in record["include_paths"]), build / HEADER_PROBE],
                                   directories[role], env, 30, read=True)
            expected = backend if role == "backend_cpp" else expanded
            self.effective[role] = {"command_id": command_id,
                "macros": build_records.validate_effective_header(text, expected, role=role)}
        _same(self.variant["effective_headers"], self.effective, "effective compiler configuration")

    def build_binding(self):
        binding = {"contract_id": manifest.CONTRACT_ID, "contract_sha256": self.report["contract_sha256"],
            "source": self.source, "loaded_helpers": self.report["loaded_helpers"],
            "format": self.fmt, "backend": "simx", "case": self.case, "corpus": self.report["corpus"],
            "profile_sha256": PROFILE_SHA256, "kernel_source_sha256": producer.KERNEL_SHA256,
            "warm_contract_sha256": manifest.WARM_CONTRACT_SHA256, "compiler_records": self.compiler,
            "model_build_records": self.model_build, "host_build_records": self.host_build,
            "effective_headers": self.effective, "generated_identity": self.variant["generated_identity"],
            "artifacts": self.artifacts, "tools": self.tools, "dependencies": self.dependencies,
            "expected_loaded_libraries": self.libraries, "simulation_workers": 1,
            "performance_environment": {"PERF": "1"},
            "unresolved_obligations": list(manifest.UNRESOLVED_OBLIGATIONS),
            **dict.fromkeys(manifest.FALSE_CLAIMS, False)}
        original = self.api.strict_json(self.verified(self.variant["binding"],
            "snapshots/" + self.variant_id + "-build-binding.json"))
        _same(original, binding, "reconstructed common build binding")
        self.build_id = qualification_id(binding)
        _same(self.variant["build_binding_sha256"], self.build_id, "common build identity")
        self.bindings[self.variant_id] = binding
