# SPDX-License-Identifier: Apache-2.0
"""Build the copying extension and retain its immutable pin in source archives."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import sys
import sysconfig
import tempfile

from setuptools import Extension, setup
from setuptools.command.bdist_wheel import bdist_wheel
from setuptools.command.build_ext import build_ext
from setuptools.command.build_py import build_py
from setuptools.command.sdist import sdist


ROOT = Path(__file__).resolve().parent
CONFIG_RELATIVE = Path("python/p05_build")
HEADER_NAME = "p05_build_config.h"
INVENTORY_NAME = "source_inventory.json"
NATIVE_SOURCES = (
    "python/native/module.cpp", "python/native/runtime_loader.cpp",
    "sw/runtime/ai/contract.cpp", "sw/runtime/ai/runtime.cpp",
    "sw/runtime/ai/mlp_host.cpp", "sw/runtime/ai/mlp_runtime.cpp",
)
INCLUDE_DIRECTORIES = (
    "python/native", "sw/runtime/ai", "sw/runtime/include",
    "sw/common", "tests/regression/ai_mlp",
)


def _bundle_module():
    path = ROOT / "python/vortex_ai/_bundle.py"
    spec = importlib.util.spec_from_file_location("_vortex_ai_build_bundle", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load the Vortex bundle build validator")
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


BUNDLE = _bundle_module()


def _source_inventory(root):
    expected = {
        path for path in BUNDLE.SOURCE_PATHS
        if path.startswith(("python/vortex_ai/", "python/native/"))
    }
    found = {
        path.relative_to(root).as_posix()
        for directory, suffixes in (
            ("python/vortex_ai", {".py"}),
            ("python/native", {".cpp", ".h"}),
        )
        for path in (root / directory).rglob("*")
        if path.suffix in suffixes
    }
    if found != expected:
        raise RuntimeError("Python/native sources differ from the binding inventory")
    return BUNDLE.source_inventory(root)


def _checked_bytes(root, relative, limit=4 * 1024 * 1024):
    record, raw = BUNDLE.read_file(root, relative, limit=limit)
    if (len(raw) != record["size"]
            or hashlib.sha256(raw).hexdigest() != record["sha256"]):
        raise RuntimeError("Build input changed while reading: " + relative)
    return raw


def _header(bundle_sha256, source_sha256, manifest):
    values = {
        "bundle_sha256": bundle_sha256,
        "source_sha256": source_sha256,
        "backend": "",
        "format": "",
        "qualification_id": "",
        "source_revision": "",
    }
    artifacts = [{"role": "", "path": "", "sha256": "", "size": 0}] * 6
    if manifest is not None:
        for key in ("backend", "format", "qualification_id", "source_revision"):
            values[key] = manifest[key]
        artifacts = sorted(manifest["artifacts"], key=lambda row: row["role"])
    lines = [
        "// SPDX-License-Identifier: Apache-2.0",
        "// Generated from validated build inputs. Do not edit.",
        "#ifndef VORTEX_AI_P05_BUILD_CONFIG_H",
        "#define VORTEX_AI_P05_BUILD_CONFIG_H",
        "#include <array>",
        "#include <cstdint>",
        "namespace vortex_ai_python::build {",
        "struct Artifact {",
        "  const char* role;",
        "  const char* path;",
        "  const char* sha256;",
        "  std::uint64_t size;",
        "};",
    ]
    lines.extend(
        "inline constexpr char " + key + "[] = " + json.dumps(value) + ";"
        for key, value in values.items()
    )
    lines.append("inline constexpr std::array<Artifact, 6> artifacts{{")
    for row in artifacts:
        fields = [json.dumps(row[key]) for key in ("role", "path", "sha256")]
        fields.append(str(row["size"]) + "ULL")
        lines.append("  {" + ", ".join(fields) + "},")
    lines.extend(("}};", "}  // namespace vortex_ai_python::build", "#endif", ""))
    return "\n".join(lines).encode("utf-8")


class BuildIdentity:
    def __init__(self):
        self.sources = _source_inventory(ROOT)
        self.source_sha256 = BUNDLE.inventory_digest(self.sources)
        self.source_bytes = BUNDLE.canonical_bytes(self.sources)
        self.bundle_sha256 = ""
        self.manifest = None
        self.manifest_bytes = None
        prepared = ROOT / CONFIG_RELATIVE
        bundle_root = os.environ.get("VORTEX_AI_BUNDLE")
        if bundle_root == "":
            raise RuntimeError("VORTEX_AI_BUNDLE must name a qualified bundle directory")

        if prepared.exists() or prepared.is_symlink():
            if prepared.is_symlink() or not prepared.is_dir():
                raise RuntimeError("The retained sdist build configuration must be a directory")
            names = {path.name for path in prepared.iterdir()}
            required = {HEADER_NAME, INVENTORY_NAME}
            if names not in (required, required | {"manifest.json"}):
                raise RuntimeError("The retained sdist build configuration is incomplete")
            if _checked_bytes(prepared, INVENTORY_NAME) != self.source_bytes:
                raise RuntimeError("The sdist sources differ from its immutable source inventory")
            if "manifest.json" in names:
                _, self.bundle_sha256, self.manifest = BUNDLE.read_manifest(prepared)
                if (self.manifest["binding_sources"] != self.sources
                        or self.manifest["binding_source_sha256"] != self.source_sha256):
                    raise RuntimeError("The sdist sources differ from the retained bundle")
                self.manifest_bytes = _checked_bytes(prepared, "manifest.json")
            self.header_bytes = _header(
                self.bundle_sha256, self.source_sha256, self.manifest)
            if _checked_bytes(prepared, HEADER_NAME) != self.header_bytes:
                raise RuntimeError("The retained sdist build header differs from its receipt")
            if bundle_root is not None:
                digest, source_digest = BUNDLE.build_binding(bundle_root, ROOT)
                if (digest != self.bundle_sha256
                        or source_digest != self.source_sha256):
                    raise RuntimeError("VORTEX_AI_BUNDLE cannot replace an immutable sdist pin")
        else:
            if (ROOT / "PKG-INFO").exists():
                raise RuntimeError("The source archive is missing its immutable build configuration")
            if bundle_root is not None:
                self.bundle_sha256, source_digest = BUNDLE.build_binding(bundle_root, ROOT)
                bundle, digest, self.manifest = BUNDLE.read_manifest(bundle_root)
                if digest != self.bundle_sha256 or source_digest != self.source_sha256:
                    raise RuntimeError("The bundle changed during package validation")
                self.manifest_bytes = _checked_bytes(bundle, "manifest.json")
            self.header_bytes = _header(
                self.bundle_sha256, self.source_sha256, self.manifest)
        if (self.manifest_bytes is not None
                and hashlib.sha256(self.manifest_bytes).hexdigest() != self.bundle_sha256):
            raise RuntimeError("The retained manifest bytes differ from the compiled pin")

    def assert_unchanged(self):
        if _source_inventory(ROOT) != self.sources:
            raise RuntimeError("Binding sources changed during the package build")

    def stage(self, directory):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / HEADER_NAME).write_bytes(self.header_bytes)
        (directory / INVENTORY_NAME).write_bytes(self.source_bytes)
        if self.manifest_bytes is not None:
            (directory / "manifest.json").write_bytes(self.manifest_bytes)


IDENTITY = BuildIdentity()


class PinnedBuildPy(build_py):
    def run(self):
        IDENTITY.assert_unchanged()
        self.force = True
        super().run()
        IDENTITY.assert_unchanged()


class PinnedBuildExt(build_ext):
    def run(self):
        if (platform.python_implementation() != "CPython"
                or sys.version_info[:2] != (3, 12)
                or not sys.platform.startswith("linux")
                or sysconfig.get_config_var("Py_GIL_DISABLED")):
            raise RuntimeError("vortex-ai requires Linux CPython 3.12 with the GIL")
        IDENTITY.assert_unchanged()
        build_temp = Path(self.build_temp).resolve()
        build_temp.mkdir(parents=True, exist_ok=True)
        staged = Path(tempfile.mkdtemp(prefix="p05-source-", dir=build_temp))
        for row in IDENTITY.sources:
            raw = _checked_bytes(ROOT, row["path"], limit=16 * 1024 * 1024)
            if (len(raw) != row["size"]
                    or hashlib.sha256(raw).hexdigest() != row["sha256"]):
                raise RuntimeError("Binding input changed while staging: " + row["path"])
            target = staged / row["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        if _source_inventory(staged) != IDENTITY.sources:
            raise RuntimeError("Staged compiler inputs differ from the binding inventory")
        config_id = hashlib.sha256(IDENTITY.header_bytes).hexdigest()
        generated = staged / "p05-config" / config_id
        IDENTITY.stage(generated)
        for extension in self.extensions:
            # Compile only pinned files: stale local headers must not shadow the ABI.
            extension.sources = [str(staged / path) for path in NATIVE_SOURCES]
            extension.include_dirs = [str(generated)] + [
                str(staged / path) for path in INCLUDE_DIRECTORIES]
            extension.depends = [str(staged / path) for path in BUNDLE.SOURCE_PATHS
                                 if path.endswith(".h")] + [str(generated / HEADER_NAME)]
        # Never reuse an extension carrying an earlier bundle or source pin.
        self.force = True
        if self.parallel is None:
            self.parallel = 1
        super().run()
        IDENTITY.assert_unchanged()


class PinnedSDist(sdist):
    def make_release_tree(self, base_dir, files):
        IDENTITY.assert_unchanged()
        stage = Path(base_dir)
        if stage.exists() or stage.is_symlink():
            raise RuntimeError("Refusing to reuse an existing sdist staging directory: " + base_dir)
        egg_info = Path(self.get_finalized_command("egg_info").egg_info)
        if egg_info.is_absolute():
            egg_info = egg_info.relative_to(ROOT)
        allowed = set(BUNDLE.SOURCE_PATHS) | {"LICENSE", "python/README.md"}
        allowed.update(
            (egg_info / name).as_posix()
            for name in ("PKG-INFO", "SOURCES.txt", "dependency_links.txt", "top_level.txt")
        )
        selected = sorted(path for path in files if Path(path).as_posix() in allowed)
        if not set(BUNDLE.SOURCE_PATHS).issubset(selected):
            raise RuntimeError("The source distribution omits a binding build input")
        super().make_release_tree(base_dir, selected)
        IDENTITY.stage(stage / CONFIG_RELATIVE)
        if _source_inventory(stage) != IDENTITY.sources:
            raise RuntimeError("The staged source distribution differs from the validated inputs")
        # Static project metadata needs no setuptools-generated setup.cfg input.
        (stage / "setup.cfg").unlink(missing_ok=True)
        sources = stage / egg_info / "SOURCES.txt"
        sources.unlink(missing_ok=True)
        members = sorted(
            path.relative_to(stage).as_posix() for path in stage.rglob("*") if path.is_file()
        )
        members.append((egg_info / "SOURCES.txt").as_posix())
        sources.write_text("\n".join(sorted(set(members))) + "\n", encoding="utf-8")
        IDENTITY.assert_unchanged()


class PinnedWheel(bdist_wheel):
    def finalize_options(self):
        super().finalize_options()
        if IDENTITY.bundle_sha256:
            expected = "1" + IDENTITY.bundle_sha256
            if self.build_number and self.build_number != expected:
                raise RuntimeError("A bound wheel build tag must identify its complete bundle pin")
            self.build_number = expected

    def run(self):
        if self.skip_build:
            raise RuntimeError("A pinned wheel requires a fresh extension build; --skip-build is unsupported")
        super().run()

    def write_wheelfile(self, wheelfile_base, **kwargs):
        IDENTITY.assert_unchanged()
        root = Path(self.bdist_dir).resolve(strict=True)
        metadata = Path(wheelfile_base).resolve(strict=True)
        sources = {
            row["path"].removeprefix("python/"): row
            for row in IDENTITY.sources if row["path"].startswith("python/vortex_ai/")
        }
        native = self.get_finalized_command("build_ext").get_ext_filename("vortex_ai._native")
        payload = {
            path.relative_to(root).as_posix() for path in root.rglob("*")
            if path.is_file() and not path.is_relative_to(metadata)
        }
        if payload != set(sources) | {native}:
            raise RuntimeError("The wheel payload differs from its source inventory; use a fresh build directory")
        for relative, expected in sources.items():
            actual = BUNDLE.file_record(root, relative, limit=16 * 1024 * 1024)
            if any(actual[key] != expected[key] for key in ("sha256", "size")):
                raise RuntimeError("A wheel Python source differs from its compiled inventory: " + relative)
        BUNDLE.file_record(root, native)
        super().write_wheelfile(wheelfile_base, **kwargs)
        IDENTITY.assert_unchanged()


setup(
    ext_modules=[Extension(
        "vortex_ai._native",
        sources=list(NATIVE_SOURCES),
        include_dirs=list(INCLUDE_DIRECTORIES),
        depends=[path for path in BUNDLE.SOURCE_PATHS if path.endswith(".h")],
        language="c++",
        extra_compile_args=["-std=c++17", "-O2", "-fvisibility=hidden", "-pthread"],
        libraries=["dl"],
        extra_link_args=["-pthread"],
    )],
    cmdclass={
        "build_py": PinnedBuildPy, "build_ext": PinnedBuildExt,
        "sdist": PinnedSDist, "bdist_wheel": PinnedWheel,
    },
)
