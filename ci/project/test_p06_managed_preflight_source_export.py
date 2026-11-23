# SPDX-License-Identifier: Apache-2.0
"""Focused Git-object boundary tests, reconstructed after workspace recovery.

Fixtures are tiny local repositories, never native builds or downloaded code.
"""

from contextlib import ExitStack
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import p06_managed_preflight_source_export as exporter
import p06_managed_preflight_sources as inventory


REQUIRED = (".gitmodules", "ci/project/helper.py", "sw/common/core.h")
HELPER = b"# Synthetic reviewed discovery helper.\n"
MODULES = b'''[submodule "third_party/ramulator"]
    path = third_party/ramulator
    url = https://github.com/CMU-SAFARI/ramulator2.git
[submodule "third_party/softfloat"]
    path = third_party/softfloat
    url = https://github.com/ucb-bar/berkeley-softfloat-3.git
'''
CMAKE = b'''FetchContent_Declare(
  yaml-cpp
  GIT_REPOSITORY https://github.com/jbeder/yaml-cpp.git
  GIT_TAG yaml-cpp-0.7.0
  SOURCE_DIR ${CMAKE_SOURCE_DIR}/ext/yaml-cpp
)
FetchContent_Declare(
  spdlog
  GIT_REPOSITORY https://github.com/gabime/spdlog.git
  GIT_TAG v1.11.0
  SOURCE_DIR ${CMAKE_SOURCE_DIR}/ext/spdlog
)
'''


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def git(repo, *args, data=None):
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
               GIT_AUTHOR_NAME="Fixture", GIT_AUTHOR_EMAIL="fixture@example.invalid",
               GIT_COMMITTER_NAME="Fixture", GIT_COMMITTER_EMAIL="fixture@example.invalid")
    result = subprocess.run(["git", "-c", "core.hooksPath=" + os.devnull,
                             "-C", str(repo), *args], input=data, capture_output=True,
                            env=env, check=True, timeout=10)
    return result.stdout


class Repositories:
    def __init__(self, root):
        self.root = root
        self.paths = {key: root / key for key in
                      ("source", "ramulator", "softfloat", "spdlog", "yaml-cpp")}
        self.revisions = {}
        files = {
            "source": {".gitmodules": MODULES, "ci/project/helper.py": HELPER,
                       "sw/common/core.h": b"/* core */\r\n",
                       "sw/common/addition.cc": b"/* discovered addition */\n",
                       "tests/runtime/case.cpp": b"/* discovered runtime test */\n"},
            "ramulator": {"CMakeLists.txt": CMAKE, "src/component.h": b"/* ramulator */\n"},
            "softfloat": {"source/include/softfloat.h": b"/* softfloat */\n",
                          "source/RISCV/specialize.h": b"/* RISCV */\n"},
            "spdlog": {"include/spdlog/common.h": b"/* spdlog */\n"},
            "yaml-cpp": {"include/yaml-cpp/yaml.h": b"/* yaml */\n"},
        }
        for key, contents in files.items():
            self.paths[key].mkdir()
            git(self.paths[key], "init", "--quiet")
            self.update(key, contents)
        for key in ("ramulator", "softfloat"):
            git(self.paths["source"], "update-index", "--add", "--cacheinfo",
                "160000," + self.revisions[key] + ",third_party/" + key)
        self.commit("source")

    def commit(self, key):
        git(self.paths[key], "commit", "--quiet", "--allow-empty", "-m", "fixture")
        self.revisions[key] = git(self.paths[key], "rev-parse", "HEAD").decode().strip()

    def update(self, key, files):
        for name, body in files.items():
            path = self.paths[key] / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
            git(self.paths[key], "add", "--", name)
        self.commit(key)

    def arguments(self):
        return {"source_repository": self.paths["source"],
                "source_revision": self.revisions["source"],
                "ramulator_repository": self.paths["ramulator"],
                "softfloat_repository": self.paths["softfloat"],
                "spdlog_repository": self.paths["spdlog"],
                "spdlog_revision": self.revisions["spdlog"],
                "yaml_cpp_repository": self.paths["yaml-cpp"],
                "yaml_cpp_revision": self.revisions["yaml-cpp"]}


class GitObjectBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.repo = self.root / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "--quiet")
        self.body = b"original Git bytes\x00with CRLF\r\n"
        (self.repo / "source.cpp").write_bytes(self.body)
        git(self.repo, "add", "source.cpp")
        git(self.repo, "commit", "--quiet", "-m", "fixture")
        self.revision = git(self.repo, "rev-parse", "HEAD").decode().strip()

    def reader(self, **kwargs):
        return exporter.GitObjects(self.repo, self.revision, **kwargs)

    def test_reads_git_bytes_and_ignores_changed_checkout_and_untracked_files(self):
        (self.repo / "source.cpp").write_bytes(b"changed checkout")
        (self.repo / "untracked.cpp").write_bytes(b"untracked")
        reader = self.reader()
        self.assertEqual(reader.blob("source.cpp"), self.body)
        self.assertNotIn("untracked.cpp", reader.entries)
        commands = reader.commands
        self.assertEqual(reader.blob("source.cpp"), self.body)
        self.assertEqual(reader.commands, commands)

    def test_revision_requires_an_explicit_full_lowercase_commit(self):
        for revision in (None, True, "HEAD", self.revision[:8], "A" * 40, "0" * 39,
                         self.revision + "\n", self.revision + "^{tree}"):
            with self.subTest(revision=revision), mock.patch.object(exporter, "_bounded_command") as run:
                with self.assertRaises(exporter.ExportError):
                    exporter.GitObjects(self.repo, revision)
                run.assert_not_called()

    def test_inherited_git_environment_is_not_used(self):
        poison = {"GIT_DIR": str(self.root / "missing"), "GIT_OBJECT_DIRECTORY": "/missing",
                  "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.repositoryformatversion",
                  "GIT_CONFIG_VALUE_0": "999", "GIT_CONFIG_GLOBAL": "/missing"}
        with mock.patch.dict(os.environ, poison):
            reader = self.reader()
            self.assertEqual(reader.blob("source.cpp"), self.body)
            self.assertNotIn("GIT_DIR", reader.environment)
            self.assertNotIn("GIT_CONFIG_COUNT", reader.environment)

    def test_git_replace_cannot_replace_expected_blob_bytes(self):
        original = git(self.repo, "rev-parse", self.revision + ":source.cpp").decode().strip()
        replacement = git(self.repo, "hash-object", "-w", "--stdin", data=b"replacement").decode().strip()
        git(self.repo, "replace", original, replacement)
        self.assertEqual(self.reader().blob("source.cpp"), self.body)

    def test_repository_path_and_symlink_ancestors_reject(self):
        linked = self.root / "linked"
        linked.symlink_to(self.repo, target_is_directory=True)
        ancestor = self.root / "ancestor"
        ancestor.symlink_to(self.root, target_is_directory=True)
        for path in (linked, ancestor / "repo", Path("relative")):
            with self.subTest(path=path), self.assertRaises(exporter.ExportError):
                exporter.GitObjects(path, self.revision)

    def test_selected_symlink_git_blob_rejects(self):
        (self.repo / "link.h").symlink_to("source.cpp")
        git(self.repo, "add", "link.h")
        git(self.repo, "commit", "--quiet", "-m", "symlink")
        self.revision = git(self.repo, "rev-parse", "HEAD").decode().strip()
        with self.assertRaisesRegex(exporter.ExportError, "regular Git blob"):
            self.reader().blob("link.h")

    def test_blob_size_bound_rejects_before_payload_read(self):
        reader = self.reader()
        with mock.patch.object(exporter, "MAX_BLOB_BYTES", len(self.body) - 1), \
                mock.patch.object(reader, "run", wraps=reader.run) as run:
            with self.assertRaisesRegex(exporter.ExportError, "byte budget"):
                reader.blob("source.cpp")
            self.assertEqual([call.args[0][:2] for call in run.call_args_list], [["cat-file", "-s"]])

    def test_total_byte_budget_is_shared_across_repositories(self):
        budget = {"commands": 0, "bytes": 0}
        first, second = self.reader(budget=budget), self.reader(budget=budget)
        with mock.patch.object(exporter, "MAX_TOTAL_BYTES", len(self.body)):
            self.assertEqual(first.blob("source.cpp"), self.body)
            with mock.patch.object(second, "run", wraps=second.run) as run:
                with self.assertRaisesRegex(exporter.ExportError, "byte budget"):
                    second.blob("source.cpp")
                self.assertEqual(len(run.call_args_list), 1)
        self.assertEqual(budget["bytes"], len(self.body))

    def test_command_budget_is_shared_and_checked_before_launch(self):
        budget = {"commands": 0, "bytes": 0}
        first, second = self.reader(budget=budget), self.reader(budget=budget)
        self.assertEqual(budget["commands"], first.commands + second.commands)
        with mock.patch.object(exporter, "MAX_GIT_COMMANDS", budget["commands"]), \
                mock.patch.object(exporter, "_bounded_command") as run:
            with self.assertRaisesRegex(exporter.ExportError, "command budget"):
                second.blob("source.cpp")
            run.assert_not_called()

    def test_blob_identity_is_recomputed_from_exact_raw_bytes(self):
        reader = self.reader()
        forged = b"x" * len(self.body)
        with mock.patch.object(reader, "run", side_effect=[str(len(forged)).encode() + b"\n", forged]):
            with self.assertRaisesRegex(exporter.ExportError, "object identity"):
                reader.blob("source.cpp")
        self.assertEqual(reader.bytes_read, 0)
        self.assertEqual(reader.cache, {})

    def test_duplicate_unsafe_and_malformed_git_tree_entries_reject(self):
        reader = self.reader()
        oid = reader.entries["source.cpp"]["oid"].encode()
        valid = b"100644 blob " + oid + b"\tsource.cpp\0"
        cases = [valid + valid, valid[:-1], b"", b"100644 blob " + oid + b"\t../source.cpp\0",
                 b"100644 blob " + oid + b"\t/root.cpp\0", b"100644 blob " + oid + b"\ta//b\0",
                 b"100644 blob " + oid + b"\tbad\nname\0", b"100644 blob " + oid + b"\tbad\xff\0",
                 b"160000 blob " + oid + b"\tsource.cpp\0", b"100644 blob z\tsource.cpp\0"]
        for raw in cases:
            with self.subTest(raw=raw), mock.patch.object(reader, "run", return_value=raw):
                with self.assertRaises(exporter.ExportError):
                    reader._tree()

    def test_actual_subprocess_stdout_and_stderr_bounds(self):
        for code in ("import os; os.write(1,b'x'*4096)", "import os; os.write(2,b'x'*70000)"):
            with self.subTest(code=code), self.assertRaisesRegex(exporter.ExportError, "output bound"):
                exporter._bounded_command([sys.executable, "-c", code], {}, 32, timeout=2)

    def test_actual_subprocess_timeout_is_enforced(self):
        with self.assertRaisesRegex(exporter.ExportError, "time bound|timed out"):
            exporter._bounded_command([sys.executable, "-c", "import time; time.sleep(10)"],
                                      {}, 32, timeout=0.05)


class SourceExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repos = Repositories(Path(self.tmp.name).resolve())
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        helpers = [{"path": "ci/project/helper.py", "sha256": hashlib.sha256(HELPER).hexdigest(),
                    "size_bytes": len(HELPER)}]
        self.helper_sha = hashlib.sha256(encoded(helpers)).hexdigest()
        self.stack.enter_context(mock.patch.object(inventory, "required_source_names", return_value=REQUIRED))
        self.stack.enter_context(mock.patch.object(exporter, "DISCOVERY_HELPER_SHA256", {self.helper_sha}))

    def export(self, **overrides):
        arguments = self.repos.arguments()
        arguments.update(overrides)
        return exporter.export_inventory(**arguments)

    def test_complete_synthetic_export_derives_origins_and_riscv_headers(self):
        manifest, receipt = self.export()
        self.assertEqual(len(manifest["sources"]), 10)
        self.assertEqual(receipt["source_files"], 10)
        names = [row["path"] for row in manifest["sources"]]
        self.assertIn("sw/common/addition.cc", names)
        self.assertIn("tests/runtime/case.cpp", names)
        self.assertIn("third_party/softfloat/source/RISCV/specialize.h", names)
        self.assertEqual(names, sorted(set(names)))
        self.assertEqual(receipt["manifest_sha256"], hashlib.sha256(encoded(manifest)).hexdigest())
        for key, repo in self.repos.paths.items():
            record = receipt["repositories"][key]
            self.assertEqual(record["commit"], self.repos.revisions[key])
            self.assertEqual(record["tree"], git(repo, "rev-parse", record["commit"] + "^{tree}").decode().strip())
        for row in receipt["sources"]:
            body = git(self.repos.paths[row["repository"]], "cat-file", "blob", row["git_blob"])
            self.assertEqual(row["sha256"], hashlib.sha256(body).hexdigest())
            self.assertEqual(row["size_bytes"], len(body))
            self.assertEqual(row["git_blob"], hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest())
        for claim in exporter.FALSE_CLAIMS + ("retained_code_executed", "dependency_compilation_provenance_verified"):
            self.assertIs(receipt[claim], False)
        self.assertEqual(receipt["native_execution"], "not_run")

    def test_changed_producer_helper_requires_new_review(self):
        self.repos.update("source", {"ci/project/helper.py": HELPER + b"# discovery changed\n"})
        with self.assertRaisesRegex(exporter.ExportError, "reviewed recipe"):
            self.export()

    def test_wrong_dependency_store_and_missing_gitlink_reject(self):
        with self.assertRaises(exporter.ExportError):
            self.export(ramulator_repository=self.repos.paths["softfloat"])
        git(self.repos.paths["source"], "update-index", "--force-remove", "third_party/ramulator")
        self.repos.commit("source")
        with self.assertRaisesRegex(exporter.ExportError, "gitlink is missing"):
            self.export()

    def test_changed_gitmodules_url_and_cmake_fetch_tag_reject(self):
        self.repos.update("source", {".gitmodules": MODULES.replace(b"CMU-SAFARI", b"unreviewed-owner")})
        with self.assertRaisesRegex(exporter.ExportError, "dependency declaration differs"):
            self.export()
        self.repos.update("source", {".gitmodules": MODULES})
        self.repos.update("ramulator", {"CMakeLists.txt": CMAKE.replace(b"v1.11.0", b"unreviewed-tag")})
        git(self.repos.paths["source"], "update-index", "--add", "--cacheinfo",
            "160000," + self.repos.revisions["ramulator"] + ",third_party/ramulator")
        self.repos.commit("source")
        with self.assertRaisesRegex(exporter.ExportError, "FetchContent declaration differs"):
            self.export()

    def test_empty_dependency_header_selection_rejects(self):
        git(self.repos.paths["spdlog"], "rm", "--quiet", "include/spdlog/common.h")
        self.repos.update("spdlog", {"README": b"no headers\n"})
        with self.assertRaisesRegex(exporter.ExportError, "header inventory is empty"):
            self.export()

    def test_manifest_is_accepted_only_with_its_external_exact_byte_digest(self):
        manifest, receipt = self.export()
        raw = encoded(manifest)
        self.assertEqual(inventory.decode_source_inventory(raw, expected_revision=self.repos.revisions["source"],
                         expected_sha256=receipt["manifest_sha256"]), manifest)
        with self.assertRaises(inventory.SourceInventoryError):
            inventory.decode_source_inventory(raw + b" ", expected_revision=self.repos.revisions["source"],
                                              expected_sha256=receipt["manifest_sha256"])

    def test_serialized_manifest_size_is_bounded(self):
        with mock.patch.object(inventory, "MAX_MANIFEST_BYTES", 1):
            with self.assertRaisesRegex(exporter.ExportError, "manifest exceeds"):
                self.export()


class OutputBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()

    def test_paired_output_failure_preserves_existing_and_removes_new_file(self):
        new, existing = self.root / "new.json", self.root / "existing.json"
        existing.write_bytes(b"preserve me")
        with self.assertRaises(FileExistsError):
            exporter.write_outputs(((new, {}), (existing, {})))
        self.assertFalse(new.exists())
        self.assertEqual(existing.read_bytes(), b"preserve me")
        exporter.write_outputs(((new, {"created": True}),))
        self.assertEqual(new.read_bytes(), encoded({"created": True}))

    def test_duplicate_output_paths_and_symlinks_reject_without_overwrite(self):
        path = self.root / "duplicate.json"
        with self.assertRaisesRegex(exporter.ExportError, "distinct"):
            exporter.write_outputs(((path, {}), (path, {})))
        self.assertFalse(path.exists())
        target = self.root / "target.json"
        target.write_bytes(b"keep")
        link = self.root / "link.json"
        link.symlink_to(target)
        with self.assertRaises(FileExistsError):
            exporter.write_outputs(((link, {}),))
        linked_parent = self.root / "parent"
        linked_parent.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(exporter.ExportError, "canonical"):
            exporter.write_outputs(((linked_parent / "new.json", {}),))
        self.assertEqual(target.read_bytes(), b"keep")
        self.assertTrue(link.is_symlink())

    def test_cli_stdout_paired_options_and_exclusive_file_outputs(self):
        args = []
        for key in ("source", "ramulator", "softfloat", "spdlog", "yaml-cpp"):
            args += ["--" + key + "-repository", str(self.root)]
        for key in ("source", "spdlog", "yaml-cpp"):
            args += ["--" + key + "-revision", "a" * 40]
        manifest = {"synthetic": "manifest"}
        receipt = {"source_files": 1, "manifest_sha256": hashlib.sha256(encoded(manifest)).hexdigest()}
        output, derivation = self.root / "manifest.json", self.root / "receipt.json"
        with mock.patch.object(exporter, "export_inventory", return_value=(manifest, receipt)) as export:
            with mock.patch("sys.stderr", new_callable=io.StringIO):
                with self.assertRaises(SystemExit) as raised:
                    exporter.main(args + ["--output", str(output)])
                self.assertEqual(raised.exception.code, 2)
                export.assert_not_called()
            with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                self.assertEqual(exporter.main(args), 0)
                self.assertEqual(json.loads(stdout.getvalue()), {"manifest": manifest, "derivation": receipt})
            file_args = args + ["--output", str(output), "--receipt", str(derivation)]
            with mock.patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(exporter.main(file_args), 0)
                self.assertEqual(exporter.main(file_args), 1)
            self.assertEqual(output.read_bytes(), encoded(manifest))
            self.assertEqual(derivation.read_bytes(), encoded(receipt))


if __name__ == "__main__":
    unittest.main()
