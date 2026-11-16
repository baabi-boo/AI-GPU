# Licensed under the Apache License, Version 2.0.
"""Inert, independently hashed inputs for vendor-orchestration tests only."""

import copy
import hashlib
import json
from pathlib import Path


FIXTURE_CONFIGS = [
    "-DVX_CFG_NUM_CLUSTERS=1", "-DVX_CFG_NUM_CORES=1",
    "-DVX_CFG_NUM_WARPS=4", "-DVX_CFG_NUM_THREADS=4",
    "-DVX_CFG_ISSUE_WIDTH=1", "-DVX_CFG_FPU_TYPE_STD",
]


def compiler_stamps(build):
    """Model the generated record layout without claiming compiler execution."""
    flags = " ".join(("-DVX_CFG_XLEN=64", "-DVX_CFG_XLEN_64", *FIXTURE_CONFIGS))
    return {
        "runtime": flags + " -std=c++17 -fPIC -O2 -DNDEBUG\n",
        "demo": "\n".join((
            "-march=rv64imafd -mabi=lp64d " + flags + " -O3 -DNDEBUG",
            flags + " -std=c++17 -O2 -DNDEBUG",
            "-L" + str(Path(build) / "sw/runtime") + " -lvortex",
            "",
        )),
    }


def identity(path):
    path = Path(path)
    contents = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(contents).hexdigest(),
            "size_bytes": len(contents)}


def write_file(path, contents, executable=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(contents, str):
        contents = contents.encode("utf-8")
    path.write_bytes(contents)
    if executable:
        path.chmod(0o700)
    return identity(path)


def write_json(path, value):
    return write_file(path, json.dumps(value, sort_keys=True, indent=2) + "\n")


class VendorFixture:
    """Create fake file relationships; none of these bytes are vendor artifacts."""

    def __init__(self, base):
        self.base = Path(base)
        self.source = self.base / "source"
        self.build = self.base / "build64"
        self.tools = self.base / "tools"
        self.output = self.base / "output"
        self.vitis = self.base / "vendor/vitis"
        self.vivado = self.base / "vendor/vivado"
        self.xrt = self.base / "vendor/xrt"
        self.artifacts = self.base / "artifacts"
        for path in (self.source, self.build, self.tools, self.vitis,
                     self.vivado, self.xrt, self.artifacts):
            path.mkdir(parents=True, exist_ok=True)
        self.source_record = {
            "outcome": "pass", "blockers": [], "revision": "a" * 40,
            "tree": "b" * 40, "dirty": False, "pins": {},
            "submodules": {"entries": [], "errors": []}, "inputs": [],
        }
        role_paths = {
            "vpp": self.vitis / "bin/v++",
            "vivado": self.vivado / "bin/vivado",
            "emconfigutil": self.vitis / "bin/emconfigutil",
            "platforminfo": self.vitis / "bin/platforminfo",
            "xrt_header": self.xrt / "include/experimental/xrt_device.h",
            "xrt_coreutil": self.xrt / "lib/libxrt_coreutil.so",
        }
        self.files = {
            role: write_file(path, "INERT TEST INPUT: " + role + "\n",
                             executable=role in ("vpp", "vivado", "emconfigutil", "platforminfo"))
            for role, path in role_paths.items()
        }
        write_file(self.vivado / "bin/xsim", "INERT TEST INPUT: simulator\n", executable=True)
        for name in ("xrt_bo.h", "xrt_error.h", "xrt_ip.h", "xrt_kernel.h", "xrt_xclbin.h"):
            write_file(self.xrt / "include/experimental" / name, "INERT TEST HEADER\n")
        platform = write_file(self.base / "platform/synthetic.xpfm", "INERT TEST PLATFORM\n")
        xclbin = write_file(self.artifacts / "vortex_afu.xclbin", "INERT TEST IMAGE\n")
        emconfig = write_json(self.artifacts / "emconfig.json", {"synthetic_fixture": True})
        review = write_file(self.base / "records/review.txt",
                            "Synthetic orchestration fixture. No vendor qualification or approval.\n")
        self.receipt_path = self.base / "records/build-receipt.json"
        self.manifest_path = self.base / "manifest.json"
        self.manifest = {
            "schema_version": 1, "id": "p01-xrt-hw-emu-demo-v1",
            "driver": "xrt", "target": "hw_emu",
            "source": {"revision": "a" * 40, "tree": "b" * 40},
            "configuration": {"xlen": 64, "configs": list(FIXTURE_CONFIGS),
                              "app": "demo", "args": ["-n1"], "expected_points": 16},
            "platform": {"name": "synthetic_fixture", "file": platform},
            "vendor": {"release": "fixture-only", "vitis_root": str(self.vitis),
                       "vivado_root": str(self.vivado), "xrt_root": str(self.xrt),
                       "files": self.files},
            "artifacts": {"xclbin": xclbin, "emconfig": emconfig},
            "build_receipt": {}, "qualification_review": review,
        }
        self.receipt = {
            key: copy.deepcopy(self.manifest[key]) for key in
            ("schema_version", "driver", "target", "source", "configuration",
             "platform", "vendor", "artifacts")
        }
        self.receipt["commands"] = [{
            "argv": ["fixture-command-never-executed", "--synthetic"],
            "cwd": str(self.source), "exit_code": 0,
            "log": write_file(self.base / "records/build.log", "Synthetic command record only.\n"),
        }]
        self.refresh()

    def refresh(self, bind_receipt=False):
        if bind_receipt:
            for key in ("schema_version", "driver", "target", "source", "configuration",
                        "platform", "vendor", "artifacts"):
                self.receipt[key] = copy.deepcopy(self.manifest[key])
        self.manifest["build_receipt"] = write_json(self.receipt_path, self.receipt)
        write_json(self.manifest_path, self.manifest)
