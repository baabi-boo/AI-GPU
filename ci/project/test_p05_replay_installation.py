# SPDX-License-Identifier: Apache-2.0
"""Synthetic host-only installation replay checks; no external originals needed."""

from __future__ import annotations

import base64
import copy
import csv
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import tarfile
import tempfile
import unittest
from unittest import mock
import zipfile

import p05_replay_installation as replay
from p06_replay import _archive_api


REVISION = "a" * 40
TREE = "b" * 40


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def record(name, data):
    return {"path": name, "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)}


def wheel_bytes(files, *, special=None):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, raw in files.items():
            item = zipfile.ZipInfo(name)
            item.compress_type = zipfile.ZIP_DEFLATED
            if name == special:
                item.create_system = 3
                item.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(item, raw)
    return stream.getvalue()


def source_archive(files, *, link=None):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        for name, raw in files.items():
            item = tarfile.TarInfo("vortex_ai-0.1.0/" + name)
            item.size = len(raw)
            archive.addfile(item, io.BytesIO(raw))
        if link is not None:
            item = tarfile.TarInfo("vortex_ai-0.1.0/" + link)
            item.type = tarfile.SYMTYPE
            item.linkname = "/producer/should-not-be-opened"
            archive.addfile(item)
    return stream.getvalue()


def package_record(files):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    for name in sorted(set(files) | {replay.DIST + "RECORD"}):
        if name == replay.DIST + "RECORD":
            writer.writerow((name, "", ""))
        else:
            digest = base64.urlsafe_b64encode(hashlib.sha256(files[name]).digest()).rstrip(b"=").decode()
            writer.writerow((name, "sha256=" + digest, str(len(files[name]))))
    return stream.getvalue().encode()


class SyntheticInstallation:
    """Installation-only fixture, deliberately containing non-executable bytes.

    Numerical/native records are represented by the independent verifier's
    minimal installation-facing result. This fixture cannot qualify a run.
    """

    def __init__(self):
        self.files = {}
        self.pr = {"paths": {"source": "/producer/source", "work": "/producer/python-work", "output": "/producer/python-output"}}
        self.tr = {"paths": {"source": "/producer/source", "work": "/producer/torch-work", "output": "/producer/torch-output",
                             "python_work": self.pr["paths"]["work"], "python_output": self.pr["paths"]["output"],
                             "wheelhouse": "/producer/framework-wheels"}}
        self.contract_raw = Path(__file__).with_name("p05_torch_contract.json").read_bytes()
        self.lock_raw = Path(__file__).with_name("p05_torch_requirements.lock").read_bytes()
        self.contract = json.loads(self.contract_raw)
        sources = {name: ("raise AssertionError('retained source must never execute: " + name + "')\n").encode()
                   for name in replay.SOURCE_PATHS}
        sources.update({"LICENSE": b"Synthetic license\n", "python/README.md": b"Synthetic host-only package\n",
                        replay.CONTRACT: self.contract_raw, replay.LOCK: self.lock_raw})
        for name in replay.HELPERS:
            sources["ci/project/" + name] = self.contract_raw if name.endswith(".json") else b"raise AssertionError('retained checker executed')\n"
        for packet in ("python", "torch"):
            for name, raw in sources.items():
                self.put(packet, "artifacts/source/" + name, raw)
        source = {"checkout": {"revision": REVISION, "tree": TREE, "dirty": False},
                  "files": [record(name, sources[name]) for name in sorted(sources)]}
        self.snapshot("python", self.pr, "source_before", source)
        bundle = {role: ("Synthetic inert bundle bytes: " + role).encode() for role in replay.ROLES}
        artifacts, dependencies = [], []
        for role, (_, original) in replay.ROLES.items():
            (dependencies if role.startswith("ramulator") else artifacts).append(record(original, bundle[role]))
        model_binding = {"source": source["checkout"], "backend": "simx", "format": "fp16", "compiler_records": [],
                         "artifacts": artifacts, "dependencies": dependencies, "profile_sha256": replay.PROFILE_SHA256,
                         "fixture_sha256": replay.FIXTURE_SHA256, "model_id": "p04-tiny-mlp-v1"}
        binding_sources = [{"path": name, "sha256": hashlib.sha256(sources[name]).hexdigest(), "size": len(sources[name])}
                           for name in replay.SOURCE_PATHS]
        self.manifest = {"schema_version": 1, "contract_id": "p05-python-bundle-v1", "backend": "simx", "format": "fp16",
                         "source_revision": REVISION, "source_tree": TREE, "binding_sources": binding_sources,
                         "binding_source_sha256": hashlib.sha256(encoded(binding_sources) + b"\n").hexdigest(),
                         "profile_sha256": replay.PROFILE_SHA256, "fixture_sha256": replay.FIXTURE_SHA256,
                         "qualification_id": hashlib.sha256(encoded(model_binding)).hexdigest(), "native_binding": model_binding,
                         "artifacts": [{"role": role, "path": replay.ROLES[role][0], "sha256": hashlib.sha256(raw).hexdigest(),
                                        "size": len(raw)} for role, raw in bundle.items()]}
        manifest_raw = encoded(self.manifest) + b"\n"
        self.manifest_digest = hashlib.sha256(manifest_raw).hexdigest()
        for packet, report in (("python", self.pr), ("torch", self.tr)):
            for role, raw in bundle.items():
                self.put(packet, "artifacts/bundle/" + replay.ROLES[role][0], raw)
            report["bundle_manifest"] = self.put(packet, "artifacts/bundle/manifest.json", manifest_raw)
            report["bundle_artifacts"] = self.tree(packet, "artifacts/bundle")
        self.pr["native_qualification_id"] = self.manifest["qualification_id"]
        pins = {"manifest.json": manifest_raw, "source_inventory.json": encoded(binding_sources) + b"\n",
                "p05_build_config.h": replay._pin_header(self.manifest, self.manifest_digest)}
        for name, raw in pins.items():
            self.put("python", "artifacts/sdist-pin/" + name, raw)
        sdist_files = {name: sources[name] for name in set(replay.SOURCE_PATHS) | {"LICENSE", "python/README.md"}}
        sdist_files.update({"python/p05_build/" + name: raw for name, raw in pins.items()})
        sdist_files["PKG-INFO"] = b"Synthetic source metadata\n"
        for name in ("PKG-INFO", "SOURCES.txt", "dependency_links.txt", "top_level.txt"):
            sdist_files["python/vortex_ai.egg-info/" + name] = b"Synthetic egg metadata\n"
        self.snapshot("python", self.pr, "extracted_sdist_before_build",
                      [record(name, sdist_files[name]) for name in sorted(sdist_files, key=lambda name: PurePosixPath(name).parts)])
        self.snapshot("python", self.pr, "package_source_stage",
                      [record(name, sources[name]) for name in sorted(set(replay.SOURCE_PATHS) | {"LICENSE", "python/README.md"})])
        self.wheel_members = {name.removeprefix("python/"): raw for name, raw in sources.items() if name.startswith("python/vortex_ai/")}
        self.wheel_members.update({
            replay.EXTENSION: b"SYNTHETIC NON-EXECUTABLE EXTENSION\n",
            replay.DIST + "METADATA": b"Metadata-Version: 2.4\nName: vortex-ai\nVersion: 0.1.0\n\nSynthetic fixture\n",
            replay.DIST + "WHEEL": ("Wheel-Version: 1.0\nRoot-Is-Purelib: false\nBuild: 1" + self.manifest_digest
                                   + "\nTag: cp312-cp312-linux_x86_64\n").encode(),
            replay.DIST + "licenses/LICENSE": sources["LICENSE"], replay.DIST + "top_level.txt": b"vortex_ai\n"})
        self.wheel_members[replay.DIST + "RECORD"] = package_record(self.wheel_members)
        self.wheel_rows = [record(name, self.wheel_members[name]) for name in sorted(self.wheel_members)]
        self.snapshot("python", self.pr, "wheel_inventory", self.wheel_rows)
        wheel_name = "vortex_ai-0.1.0-1" + self.manifest_digest + "-cp312-cp312-linux_x86_64.whl"
        self.wheel_path = "packages/wheel/" + wheel_name
        wheel_row = self.put("python", self.wheel_path, wheel_bytes(self.wheel_members))
        self.pr["packages"] = [self.put("python", "packages/sdist/vortex_ai-0.1.0.tar.gz", source_archive(sdist_files)), wheel_row]
        self.tr["installed_wheel"] = self.put("torch", "packages/" + wheel_name, self.files["python/" + self.wheel_path])
        self.tr["python_revalidation"] = {"wheel": copy.deepcopy(wheel_row), "bundle_sha256": self.manifest_digest}
        plain_files = dict(self.wheel_members)
        plain_files.update({replay.DIST + "INSTALLER": b"pip\n", replay.DIST + "REQUESTED": b"",
                            replay.DIST + "direct_url.json": encoded({"archive_info": {"hash": "sha256=" + wheel_row["sha256"],
                                "hashes": {"sha256": wheel_row["sha256"]}}, "url": "file://" + self.pr["paths"]["output"] + "/" + self.wheel_path})})
        plain_files[replay.DIST + "RECORD"] = package_record(plain_files)
        plain_rows = [record(name, plain_files[name]) for name in sorted(plain_files)]
        for name, raw in plain_files.items():
            self.put("python", "artifacts/installed/" + name, raw)
        for key in ("installed_before", "installed_after"):
            self.snapshot("python", self.pr, key, plain_rows)
        for key, path, raw in (("contract", replay.CONTRACT, self.contract_raw), ("requirements", replay.LOCK, self.lock_raw)):
            self.tr[key] = record("artifacts/source/" + path, raw)
        wheelhouse = [{"path": row["filename"], "sha256": row["sha256"], "size_bytes": row["size"]} for row in self.contract["wheels"]]
        self.tr["wheelhouse"] = {"directory": self.tr["paths"]["wheelhouse"], "files": wheelhouse}
        self.snapshot("torch", self.tr, "wheelhouse_after", wheelhouse)
        payload = {replay.SITE + row["path"]: {**row, "path": replay.SITE + row["path"]} for row in self.wheel_rows}
        roots = {}
        for wheel in self.contract["wheels"]:
            name = wheel["name"].lower().replace("-", "_")
            root = replay.SITE + "-".join(wheel["filename"].split("-")[:2]) + ".dist-info/"
            roots[name] = root
            for leaf in ("METADATA", "WHEEL", "RECORD"):
                payload[root + leaf] = record(root + leaf, ("Recorded missing third-party " + name + "/" + leaf).encode())
        payload[replay.SITE + "torch/__init__.py"] = record(replay.SITE + "torch/__init__.py", b"Missing synthetic torch source")
        large = replay.SITE + "torch/lib/libtorch_cpu.so"
        payload[large] = {"path": large, "sha256": "c" * 64, "size_bytes": 440280512}
        self.large_path = large
        self.snapshot("torch", self.tr, "framework_wheel_payload", sorted(payload.values(), key=lambda row: row["path"]))
        interpreter = record("bin/python", b"Absent synthetic interpreter")
        seed = {"bin/python": interpreter,
                "bin/pip": record("bin/pip", b"Absent synthetic pip script"),
                replay.SITE + "pip-25.0.1.dist-info/METADATA": record(replay.SITE + "pip-25.0.1.dist-info/METADATA", b"Absent seed metadata")}
        self.snapshot("torch", self.tr, "venv_seed", sorted(seed.values(), key=lambda row: row["path"]))
        installed = copy.deepcopy(payload)
        for name in installed:
            if name.endswith(".dist-info/RECORD"):
                installed[name] = record(name, ("Absent rewritten RECORD " + name).encode())
        for leaf in ("INSTALLER", "REQUESTED", "direct_url.json"):
            name = replay.SITE + replay.DIST + leaf
            installed[name] = record(name, plain_files[replay.DIST + leaf] if leaf != "direct_url.json" else b"Absent changed Torch wheel URL")
        installed.update(seed)
        for name in replay.ENTRY_POINTS:
            installed[name] = record(name, ("Absent generated entry point " + name).encode())
        self.tr["framework_entry_points"] = list(replay.ENTRY_POINTS)
        for key in ("installed_before", "installed_after"):
            self.snapshot("torch", self.tr, key, sorted(installed.values(), key=lambda row: row["path"]))
        self.tr["venv_configuration"] = record("pyvenv.cfg", b"Absent configuration content")
        provisioning = {**interpreter, "path": "/producer/python-runtime/bin/python3", "resolved_path": "/producer/python-runtime/bin/python3.12"}
        self.tr["provisioning_interpreter"] = provisioning
        for report in (self.pr, self.tr):
            path = report["paths"]["work"] + "/venv/bin/python"
            report["venv_interpreter"] = {**interpreter, "path": path, "resolved_path": path}
        for key in ("tools_before", "tools_after"):
            self.snapshot("python", self.pr, key, {"python3": provisioning})
        package_tools = {"implementation": "CPython", "python_version": [3, 12, 14], "executable": provisioning["path"],
                         "distributions": {name: {"version": version, "files": [record("/producer/python-runtime/" + name, b"Absent build prerequisite")]}
                                           for name, version in (("setuptools", "84.2.1"), ("wheel", "0.48.0"), ("packaging", "26.3"))}}
        for suffix in ("before", "after"):
            self.snapshot("python", self.pr, "package_tools_" + suffix, package_tools)
            self.put("python", "logs/package-tools-" + suffix + ".log", b"P05_PACKAGE_TOOLS " + encoded(package_tools) + b"\n")
        base_request = {"schema_version": 1, "contract_id": "p05-installed-request-v1", "iterations": 2,
                        "expected_prefix": self.pr["paths"]["work"] + "/venv", "matmul_cases": [], "model_cases": [],
                        "binding": {"backend": "simx", "format": "fp16", "bundle_root": self.pr["paths"]["output"] + "/artifacts/bundle",
                                    "bundle_sha256": self.manifest_digest, "source_sha256": self.manifest["binding_source_sha256"],
                                    "qualification_id": self.manifest["qualification_id"], "source_revision": REVISION}}
        self.snapshot("python", self.pr, "installed_request", base_request)
        torch_base = copy.deepcopy(base_request)
        torch_base["expected_prefix"] = self.tr["paths"]["work"] + "/venv"
        torch_base["binding"]["bundle_root"] = self.tr["paths"]["output"] + "/artifacts/bundle"
        adapter_hash = hashlib.sha256(self.wheel_members["vortex_ai/torch_ops.py"]).hexdigest()
        request = {"schema_version": 1, "contract_id": "p05-torch-request-v1", "base_request": torch_base,
                   "framework": {"version": "2.15.0+cpu", "contract_sha256": replay.CONTRACT_SHA256, "adapter_sha256": adapter_hash}}
        self.snapshot("torch", self.tr, "installed_request", request)
        observations = {"binding": base_request["binding"], "installation": self.installation(base_request)}
        self.pr["observations"] = self.put("python", "artifacts/installed-observations.json", encoded(observations))
        torch_observations = {"base_observations": {"binding": torch_base["binding"], "installation": self.installation(torch_base)},
                              "framework": {**request["framework"], "distribution_version": "2.15.0+cpu",
                                            "adapter_file": torch_base["expected_prefix"] + "/" + replay.SITE + "vortex_ai/torch_ops.py"}}
        self.tr["observations"] = self.put("torch", "artifacts/installed-observations.json", encoded(torch_observations))
        helper_rows = []
        for name in replay.HELPERS:
            helper_rows.append(record(name, sources["ci/project/" + name]))
            self.put("torch", "artifacts/checker/" + name, sources["ci/project/" + name])
        self.snapshot("torch", self.tr, "installed_helpers", helper_rows)
        self.pr["installed_script"] = next(row for row in helper_rows if row["path"] == "p05_installed_check.py")
        environment = {"python_version": [3, 12, 14], "implementation": "CPython", "platform": "linux", "machine": "x86_64",
                       "byteorder": "little", "gil": True, "prefix": torch_base["expected_prefix"], "base_prefix": "/producer/python-runtime",
                       "executable": torch_base["expected_prefix"] + "/bin/python", "isolated": 1, "torch_version": "2.15.0+cpu",
                       "torch_file": torch_base["expected_prefix"] + "/" + replay.SITE + "torch/__init__.py", "cuda": None,
                       "torch_config": "Synthetic absent CPU build", "distributions": {}}
        ownership = {name: [path for path in installed if path.startswith(root)] for name, root in roots.items()}
        ownership["torch"] += [replay.SITE + "torch/__init__.py", large, "bin/torchfrtrace", "bin/torchrun"]
        ownership["numpy"] += ["bin/f2py", "bin/numpy-config"]
        ownership["sympy"].append("bin/isympy")
        ownership["pip"] = [name for name in seed if name != "bin/python"]
        ownership["vortex_ai"] = [name for name in installed if name.startswith((replay.SITE + "vortex_ai/", replay.SITE + replay.DIST))]
        versions = {row["name"].lower().replace("-", "_"): row["version"] for row in self.contract["wheels"]}
        versions.update(pip="25.0.1", vortex_ai="0.1.0")
        for name, paths in ownership.items():
            files = sorted(path[len(replay.SITE):] if path.startswith(replay.SITE) else "../../../" + path for path in paths)
            environment["distributions"][name] = {"version": versions[name], "root": torch_base["expected_prefix"] + "/" + replay.SITE.rstrip("/"), "files": files}
        snapshot = copy.deepcopy(environment)
        for name, distribution in snapshot["distributions"].items():
            distribution["files"] = [installed[replay.SITE + path] if not path.startswith("../../../") else installed[path[9:]]
                                     for path in distribution["files"]]
        for suffix in ("before", "after"):
            self.snapshot("torch", self.tr, "framework_" + suffix, snapshot)
            self.put("torch", "logs/framework-environment-" + suffix + ".log", b"P05_TORCH_ENVIRONMENT " + encoded(environment) + b"\n")
        self.native = {"python_report": self.pr, "python_request": base_request, "python_observations": observations,
                       "python_source": source, "model_binding": model_binding}

    def installation(self, request):
        prefix = request["expected_prefix"]
        return {"python_version": [3, 12, 14], "python_implementation": "CPython", "executable": prefix + "/bin/python",
                "prefix": prefix, "base_prefix": "/producer/python-runtime", "package_file": prefix + "/" + replay.SITE + "vortex_ai/__init__.py",
                "extension_file": prefix + "/" + replay.SITE + replay.EXTENSION, "distribution_version": "0.1.0",
                "build_info": {"binding_api": 1, "bundle_sha256": self.manifest_digest, "source_sha256": self.manifest["binding_source_sha256"]},
                "runtime_libraries": [request["binding"]["bundle_root"] + "/" + replay.ROLES[role][0] for role in replay.LIBRARY_ORDER]}

    def put(self, packet, name, raw):
        self.files[packet + "/" + name] = raw
        return record(name, raw)

    def snapshot(self, packet, report, key, value):
        report[key] = self.put(packet, "snapshots/" + key.replace("_", "-") + ".json", encoded(value) + b"\n")

    def snapshot_value(self, packet, report, key):
        return json.loads(self.files[packet + "/" + report[key]["path"]])

    def tree(self, packet, prefix):
        start = packet + "/" + prefix + "/"
        return [record(name[len(start):], raw) for name, raw in sorted(self.files.items()) if name.startswith(start)]

    def run(self):
        self.put("python", "report.json", encoded(self.pr))
        self.tr["python_report"] = self.put("torch", "python/report.json", encoded(self.pr))
        self.put("torch", "report.json", encoded(self.tr))
        api = _archive_api()
        with tempfile.TemporaryDirectory(prefix="p05-installation-test-") as directory:
            path = Path(directory) / "synthetic-installation.zip"
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for name, raw in self.files.items():
                    archive.writestr(name, raw)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            with api.ArchiveReader(path, digest) as archive:
                return replay.verify_installations(archive.view(), self.tr, self.native,
                                                   expected_revision=REVISION, expected_format="fp16")


class InstallationReplayTests(unittest.TestCase):
    def setUp(self):
        self.fixture = SyntheticInstallation()

    def reject(self, pattern):
        with self.assertRaisesRegex(ValueError, pattern):
            self.fixture.run()

    def mutate_snapshot(self, packet, report, key, mutate):
        value = self.fixture.snapshot_value(packet, report, key)
        mutate(value)
        self.fixture.snapshot(packet, report, key, value)

    def test_complete_synthetic_installation_and_explicit_missing_bytes(self):
        result = self.fixture.run()
        self.assertEqual(set(result), {"python_identity", "torch_identity", "adapter_bytes", "summary"})
        summary = result["summary"]
        self.assertEqual(summary["bound_wheel_members"], 11)
        self.assertEqual(summary["retained_plain_installed_files"], 14)
        self.assertEqual(summary["framework_distribution_receipts"], 13)
        for name in ("third_party_bytes_rehashed", "interpreter_bytes_rehashed", "venv_configuration_bytes_retained",
                     "retained_code_executed", "acceptance_claimed", "phase_acceptance"):
            self.assertIs(summary[name], False)
        self.assertEqual(summary["native_execution"], "not_run")
        self.assertEqual(len(summary["limitations"]), 7)
        self.assertEqual(result["python_identity"].request_sha256, hashlib.sha256(encoded(self.fixture.native["python_request"])).hexdigest())
        self.assertIn(440280512, [row[2] for row in result["torch_identity"].installed_files])

    def test_no_producer_path_access_or_process_execution(self):
        real_resolve, real_open, real_os_open = Path.resolve, Path.open, os.open

        def guard_resolve(path, *args, **kwargs):
            self.assertFalse(str(path).startswith("/producer"), "opened a producer path")
            return real_resolve(path, *args, **kwargs)

        def guard_open(path, *args, **kwargs):
            self.assertFalse(str(path).startswith("/producer"), "opened a producer path")
            return real_open(path, *args, **kwargs)

        def guard_os_open(path, *args, **kwargs):
            self.assertFalse(str(path).startswith("/producer"), "opened a producer path")
            return real_os_open(path, *args, **kwargs)

        with mock.patch.object(Path, "resolve", guard_resolve), mock.patch.object(Path, "open", guard_open), \
             mock.patch.object(os, "open", guard_os_open), mock.patch.object(subprocess, "Popen", side_effect=AssertionError("process executed")), \
             mock.patch.object(os, "system", side_effect=AssertionError("shell executed")):
            self.assertFalse(self.fixture.run()["summary"]["retained_code_executed"])

    def test_external_inventory_bound_is_separate_and_exact(self):
        api = _archive_api()
        row = {"path": "torch/lib.so", "sha256": "d" * 64, "size_bytes": replay.EXTERNAL_FILE_BYTES}
        replay._inventory([row], api, "external")
        with self.assertRaises(ValueError):
            api.descriptor(row)
        for size in (replay.EXTERNAL_FILE_BYTES + 1, True, -1):
            with self.subTest(size=size), self.assertRaises(ValueError):
                replay._inventory([{**row, "size_bytes": size}], api, "external")
        with self.assertRaisesRegex(ValueError, "total byte bound"):
            replay._inventory([row, {**row, "path": "torch/other.so"}], api, "external")

    def test_external_inventory_rejects_duplicates_unsorted_and_path_escapes(self):
        api = _archive_api()
        a, b = record("a", b"a"), record("b", b"b")
        for rows in ([a, a], [b, a], [a, {**b, "path": "a/child"}],
                     [{**a, "path": "../outside"}], [{**a, "path": "bin\\python"}]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                replay._inventory(rows, api, "external")

    def test_payload_identity_mismatch(self):
        self.mutate_snapshot("torch", self.fixture.tr, "framework_wheel_payload", lambda rows: rows[-1].update(sha256="0" * 64))
        self.reject("payload/installation")

    def test_unexplained_installed_file(self):
        for key in ("installed_before", "installed_after"):
            self.mutate_snapshot("torch", self.fixture.tr, key, lambda rows: rows.append(record("share/unexplained", b"unknown")))
        self.reject("unexplained or missing")

    def test_seed_changed(self):
        self.mutate_snapshot("torch", self.fixture.tr, "venv_seed", lambda rows: rows[0].update(sha256="0" * 64))
        self.reject("seed stability")

    def test_missing_entry_point(self):
        for key in ("installed_before", "installed_after"):
            self.mutate_snapshot("torch", self.fixture.tr, key, lambda rows: rows.__setitem__(slice(None), [row for row in rows if row["path"] != "bin/torchrun"]))
        self.reject("unexplained or missing")

    def test_changed_retained_adapter(self):
        self.fixture.files["python/artifacts/installed/vortex_ai/torch_ops.py"] += b"changed"
        self.reject("retained bytes")

    def test_changed_bound_wheel_copy(self):
        self.fixture.files["torch/" + self.fixture.tr["installed_wheel"]["path"]] += b"changed"
        self.reject("descriptor hash or size")

    def test_nested_wheel_rejects_links_and_unsafe_members(self):
        api = _archive_api()
        with self.assertRaisesRegex(ValueError, "member type"):
            replay._wheel_members(wheel_bytes(self.fixture.wheel_members, special=replay.EXTENSION), self.fixture.manifest, api)
        members = dict(self.fixture.wheel_members)
        members["../outside"] = members.pop(replay.EXTENSION)
        with self.assertRaisesRegex(ValueError, "unsafe|noncanonical"):
            replay._wheel_members(wheel_bytes(members), self.fixture.manifest, api)

    def test_nested_sdist_rejects_links_and_unsafe_members(self):
        api = _archive_api()
        with self.assertRaisesRegex(ValueError, "has a link"):
            replay._sdist_members(source_archive({"setup.py": b"inert"}, link="link"), api)
        with self.assertRaisesRegex(ValueError, "unsafe|noncanonical"):
            replay._sdist_members(source_archive({"../../outside": b"inert"}), api)

    def test_nested_wheel_record_must_match_actual_members(self):
        members = dict(self.fixture.wheel_members)
        members[replay.EXTENSION] += b"changed without RECORD update"
        with self.assertRaisesRegex(ValueError, "RECORD file identity"):
            replay._wheel_members(wheel_bytes(members), self.fixture.manifest, _archive_api())

    def test_altered_bundle_source_pin(self):
        manifest = copy.deepcopy(self.fixture.manifest)
        manifest["binding_source_sha256"] = "0" * 64
        for packet, report in (("python", self.fixture.pr), ("torch", self.fixture.tr)):
            report["bundle_manifest"] = self.fixture.put(packet, "artifacts/bundle/manifest.json", encoded(manifest) + b"\n")
        self.reject("source inventory pin")

    def test_framework_log_snapshot_mismatch(self):
        name = "torch/logs/framework-environment-after.log"
        self.fixture.files[name] = self.fixture.files[name].replace(b'"isolated":1', b'"isolated":0')
        self.reject("raw framework environment")

    def test_framework_duplicate_log_marker(self):
        name = "torch/logs/framework-environment-before.log"
        self.fixture.files[name] *= 2
        self.reject("missing or duplicated")

    def test_distribution_list_cannot_omit_payload_files(self):
        for key in ("framework_before", "framework_after"):
            self.mutate_snapshot("torch", self.fixture.tr, key,
                lambda value: value["distributions"]["torch"].__setitem__("files", [row for row in value["distributions"]["torch"]["files"]
                                                                                  if row["path"] != self.fixture.large_path]))
        self.reject("omit installed wheel")

    def test_distribution_normalization_is_lexical_and_contained(self):
        api = _archive_api()
        self.assertEqual(replay._distribution_path("../../../bin/torchrun", api), "bin/torchrun")
        for path in ("../../../../etc/passwd", "/producer/etc/passwd", "C:/outside", "torch/./file", "torch//file", "torch\\file"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                replay._distribution_path(path, api)

    def test_copied_interpreter_mismatch(self):
        self.fixture.tr["venv_interpreter"]["sha256"] = "0" * 64
        self.reject("copied interpreter bytes")

    def test_request_prefix_cannot_be_substituted(self):
        self.mutate_snapshot("torch", self.fixture.tr, "installed_request",
                             lambda value: value["base_request"].update(expected_prefix="/producer/another-venv"))
        self.reject("framework installed request")

    def test_recorded_adapter_path_must_map_to_retained_package(self):
        value = json.loads(self.fixture.files["torch/artifacts/installed-observations.json"])
        value["framework"]["adapter_file"] = "/producer/elsewhere/torch_ops.py"
        self.fixture.tr["observations"] = self.fixture.put("torch", "artifacts/installed-observations.json", encoded(value))
        self.reject("adapter path")

    def test_package_tools_log_must_match_snapshot(self):
        name = "python/logs/package-tools-after.log"
        self.fixture.files[name] = self.fixture.files[name].replace(b'"implementation":"CPython"', b'"implementation":"Other"')
        self.reject("raw package prerequisite")

    def test_framework_contract_cannot_be_replaced_with_self_consistent_lock(self):
        raw = self.fixture.contract_raw + b"\n"
        self.fixture.tr["contract"] = self.fixture.put("torch", "artifacts/source/" + replay.CONTRACT, raw)
        self.reject("unsupported frozen framework contract")


if __name__ == "__main__":
    unittest.main()
