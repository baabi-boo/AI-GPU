# SPDX-License-Identifier: Apache-2.0
"""Synthetic inputs for planner tests; never vendor or acceptance evidence."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from hwemu_contract import CONFIGS, GENERATED_PATHS, GIB, MIB, validate_manifest


SOURCE = Path(__file__).resolve().parents[2]
SOURCE_FILES = (
    "configure", "VERSION", "config.mk.in", "VX_config.toml", "VX_types.toml",
    "vortex_opae.toml", "ci/gen_config.py", "ci/blackbox.sh", "sw/kernel/Makefile",
    "sw/runtime/stub/Makefile", "sw/runtime/common.mk", "sw/runtime/xrt/Makefile",
    "sw/runtime/xrt/xrt.ini.in", "sw/runtime/xrt/xsim.tcl",
    "tests/regression/demo/Makefile", "tests/regression/common.mk",
    "hw/syn/xilinx/xrt/Makefile", "hw/syn/xilinx/common.mk",
    "hw/syn/xilinx/platform.mk",
)


def identity(path, *, include_path=True):
    path = Path(path)
    contents = path.read_bytes()
    result = {"size_bytes": len(contents), "sha256": hashlib.sha256(contents).hexdigest()}
    if include_path:
        result["path"] = str(path)
    return result


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _environment():
    # These tests run trusted local configure/Git, never the synthetic vendor files.
    return {"PATH": os.defpath, "LANG": "C", "LC_ALL": "C",
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
            "PYTHONDONTWRITEBYTECODE": "1"}


def _git(root, *arguments):
    return subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=Synthetic Fixture",
         "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false",
         *arguments], env=_environment(), capture_output=True, text=True,
        check=True, timeout=10,
    ).stdout.strip()


class HwemuFixture:
    """Own a small disposable source/build pair and visibly synthetic artifacts."""

    def __init__(self, base=None):
        self._temporary = tempfile.TemporaryDirectory(prefix="ai-gpu-hwemu-fixture-") if base is None else None
        self.base = Path(self._temporary.name if self._temporary else base).absolute()
        self.source = self.base / "source"
        self.build = self.base / "build64"
        self.tools = self.base / "tools"
        self.vendor = self.base / "vendor"
        self.artifacts = self.base / "artifacts"
        self.manifest_path = self.base / "manifest.json"
        self.receipt_path = self.base / "build-receipt.json"
        try:
            self._populate()
        except BaseException:
            self.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, _kind, _value, _traceback):
        self.close()

    def close(self):
        if self._temporary is not None:
            self._temporary.cleanup()
            self._temporary = None

    def _populate(self):
        self.source.mkdir(parents=True, exist_ok=False)
        self.build.mkdir()
        self.tools.mkdir()
        for relative in SOURCE_FILES:
            destination = self.source / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SOURCE / relative, destination)
            destination.chmod((SOURCE / relative).stat().st_mode & 0o777)
        _write(self.source / ".gitmodules", "")
        _write(self.source / "SYNTHETIC.md", "Synthetic planner fixture; no vendor execution or acceptance evidence.\n")
        _git(self.source, "init", "-q")
        _git(self.source, "add", ".")
        _git(self.source, "commit", "-qm", "Synthetic planner input fixture")
        revision = _git(self.source, "rev-parse", "HEAD")
        tree = _git(self.source, "rev-parse", "HEAD^{tree}")
        configured = subprocess.run(
            [str(self.source / "configure"), "--xlen=64", "--profile=",
             "--osversion=ubuntu/focal", "--tooldir=" + str(self.tools)],
            cwd=self.build, env=_environment(), capture_output=True, text=True,
            check=False, timeout=30,
        )
        if configured.returncode:
            raise ValueError("synthetic fixture configure failed: " + configured.stdout + configured.stderr)
        macros = " ".join((*CONFIGS, "-DVX_CFG_XLEN=64", "-DVX_CFG_XLEN_64"))
        _write(self.build / "sw/runtime/xrt_config.stamp", macros + " -fPIC\n")
        _write(self.build / "tests/regression/demo/config.stamp",
               macros + " -march=rv64imafd -mabi=lp64d\n" + macros
               + " -O2\n-L" + str(self.build / "sw/runtime") + " -lvortex\n")
        roles = {
            "vpp": self.vendor / "vitis/bin/v++",
            "vivado": self.vendor / "vivado/bin/vivado",
            "emconfigutil": self.vendor / "vitis/bin/emconfigutil",
            "platforminfo": self.vendor / "vitis/bin/platforminfo",
            "xrt_header": self.vendor / "xrt/include/xrt.h",
            "xrt_library": self.vendor / "xrt/lib/libxrt_coreutil.so.1",
            "platform": self.vendor / "platform/synthetic_platform.xpfm",
            "xclbin": self.artifacts / "vortex_afu.xclbin",
            "emconfig": self.artifacts / "emconfig.json",
            "build_receipt": self.receipt_path,
            "xsim_hook": self.source / "sw/runtime/xrt/xsim.tcl",
        }
        for role, path in roles.items():
            if role not in ("build_receipt", "xsim_hook"):
                _write(path, "SYNTHETIC " + role + ": not vendor code or hardware evidence.\n")
        _write(roles["emconfig"], json.dumps({"SYNTHETIC": "not a vendor emulation configuration"}) + "\n")
        self.manifest = {
            "schema_version": 1, "target": "hw_emu",
            "source": {"root": str(self.source), "revision": revision, "tree": tree},
            "build": {"root": str(self.build), "tool_dir": str(self.tools),
                      "xlen": 64, "profile": "", "configs": list(CONFIGS)},
            "vendor": {name: {"root": str(self.vendor / name), "release": "SYNTHETIC-UNQUALIFIED"}
                       for name in ("vitis", "vivado", "xrt")},
            "platform": {"name": "synthetic_platform"},
            "files": {role: {"path": str(path)} for role, path in roles.items()},
            "generated": {},
            "budget": {"jobs": 2, "timeout_seconds": 1800, "min_free_bytes": 15 * GIB,
                       "max_rss_bytes": 6 * GIB, "max_log_bytes": 16 * MIB,
                       "max_input_bytes": 512 * MIB},
        }
        self.source_observation = {
            "revision": revision, "tree": tree, "dirty": False, "clean": True,
            "outcome": "pass", "submodules": {"declared_count": 0, "observed_count": 0,
            "initialized_count": 0, "at_recorded_revisions": True, "errors": []},
            "blockers": [],
        }
        self.refresh()

    def refresh(self):
        """Rebind synthetic identities after a test deliberately changes a member."""
        for role, value in self.manifest["files"].items():
            if role != "build_receipt":
                self.manifest["files"][role] = identity(value["path"])
        self.manifest["generated"] = {
            relative: identity(self.build / relative, include_path=False)
            for relative in GENERATED_PATHS
        }
        self.refresh_receipt()
        return self.manifest

    def refresh_receipt(self):
        """Rewrite only synthetic declarations, preserving deliberate hash mutations."""
        receipt = deepcopy({key: value for key, value in self.manifest.items() if key != "budget"})
        receipt["files"].pop("build_receipt", None)
        self.receipt_path.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        self.manifest["files"]["build_receipt"] = identity(self.receipt_path)
        self.write_manifest()
        return receipt

    def write_manifest(self):
        self.manifest_path.write_text(json.dumps(self.manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    def validated_manifest(self):
        return validate_manifest(self.manifest)


Fixture = HwemuFixture
