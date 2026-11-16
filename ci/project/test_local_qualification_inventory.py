# Licensed under the Apache License, Version 2.0.
"""Independent local qualification inventories using disposable files and Git repos."""

import hashlib
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import baseline_inventory
import local_qualification_inventory as inventory
import test_baseline_inventory as baseline_fixtures


write = baseline_fixtures.write
git = baseline_fixtures.git
REPOSITORY = Path(__file__).resolve().parents[2]
LIBRARIES = (
    "third_party/softfloat/build/Linux-x86_64-GCC/softfloat.a",
    "third_party/ramulator/libramulator.so",
    "third_party/ramulator_ext/libramulator-vortex.so",
)
HEADER_ROOTS = (
    "third_party/ramulator/ext/spdlog/include",
    "third_party/ramulator/ext/yaml-cpp/include",
)
LOCAL_COPIES = {
    "sim/xrtsim/Makefile": "sim/xrtsim/Makefile",
    "sim/xrtsim/verilator.vlt": "sim/xrtsim/verilator.vlt.in",
    "sw/runtime/xrt/Makefile": "sw/runtime/xrt/Makefile",
    "sw/runtime/xrt/xrt.ini": "sw/runtime/xrt/xrt.ini.in",
    "hw/unittest/common.mk": "hw/unittest/common.mk",
    "hw/unittest/verilator.vlt": "hw/unittest/verilator.vlt.in",
}


def identity(root, relative):
    contents = (root / relative).read_bytes()
    return {"path": relative, "size_bytes": len(contents),
            "sha256": hashlib.sha256(contents).hexdigest()}


def commit(root, message="local fixture"):
    git(root, "add", ".")
    git(root, "commit", "-qm", message)


def executable(path, body):
    write(path, "#!/bin/sh\n" + body)
    path.chmod(0o755)


class FileFixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="local-inventory-test-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()

    def assertBlocked(self, report, fragment=None):
        self.assertEqual(report["outcome"], "blocked", report)
        self.assertTrue(report["blockers"], report)
        if fragment is not None:
            self.assertTrue(any(fragment in item for item in report["blockers"]), report)


class DependencyFixture(FileFixture):
    def setUp(self):
        super().setUp()
        upstream = self.base / "ramulator-upstream"
        upstream.mkdir()
        git(upstream, "init", "-q")
        write(upstream / "src/dram/impl/GDDR6.cpp", "committed GDDR6 extension\n")
        write(upstream / ".gitignore", "/ext/\n/libramulator.so\n")
        commit(upstream)
        self.source = self.base / "source"
        baseline_fixtures.populate_source(self.source)
        write(self.source / ".gitignore",
              "/build*/\n/third_party/softfloat/\n/third_party/ramulator_ext/\n")
        write(self.source / "third_party/Makefile", "all:\n\t@echo inert extension recipe\n")
        git(self.source, "init", "-q")
        git(self.source, "-c", "protocol.file.allow=always", "submodule", "add", "-q",
            str(upstream), "third_party/ramulator")
        commit(self.source)
        self.supplier = self.base / "supplier"
        git(self.base, "clone", "-q", "--no-hardlinks", str(self.source), str(self.supplier))
        git(self.supplier, "-c", "protocol.file.allow=always", "submodule", "update",
            "--init", "--recursive", "--quiet")
        for relative in LIBRARIES:
            write(self.supplier / relative, "inert reused binary: " + relative + "\n")
        for relative in HEADER_ROOTS:
            write(self.supplier / relative / "dependency.h", "external fixture header\n")

    def inspect_dependencies(self):
        return inventory._collect_dependencies(
            self.source, inventory.collect_source(self.source), self.supplier)


class DependencyInventoryTests(DependencyFixture):
    def test_clean_matching_gitlinks_identify_exact_reused_inputs(self):
        write(self.supplier / "unrelated-note.txt", "another root commit is permitted\n")
        commit(self.supplier)
        self.assertNotEqual(git(self.source, "rev-parse", "HEAD"),
                            git(self.supplier, "rev-parse", "HEAD"))
        report = self.inspect_dependencies()
        self.assertEqual(report["outcome"], "pass", report)
        self.assertTrue(report["reused"])
        self.assertTrue(report["gitlinks_match"])
        self.assertEqual(report["source"]["revision"], git(self.supplier, "rev-parse", "HEAD"))
        self.assertEqual(report["libraries"], [identity(self.supplier, path) for path in LIBRARIES])
        self.assertEqual(report["extension_inputs"], [identity(self.source, path) for path in (
            "third_party/Makefile", "third_party/ramulator/src/dram/impl/GDDR6.cpp")])
        self.assertEqual(report["external_headers"], [identity(self.supplier, path + "/dependency.h")
                                                      for path in HEADER_ROOTS])

    def test_committed_supplier_recipe_drift_is_not_hidden_by_matching_gitlinks(self):
        write(self.supplier / "third_party/Makefile", "all:\n\t@echo substituted recipe\n")
        commit(self.supplier)
        report = self.inspect_dependencies()
        self.assertEqual(report["source"]["outcome"], "pass", report)
        self.assertTrue(report["gitlinks_match"])
        self.assertBlocked(report, "extension build inputs differ")

    def test_gddr6_worktree_drift_is_not_hidden_by_matching_gitlinks(self):
        write(self.supplier / "third_party/ramulator/src/dram/impl/GDDR6.cpp", "different extension\n")
        report = self.inspect_dependencies()
        self.assertTrue(report["gitlinks_match"])
        self.assertBlocked(report, "extension build inputs differ")
        self.assertTrue(report["source"]["dirty"])

    def test_identical_but_untracked_extension_recipe_is_rejected(self):
        git(self.supplier, "rm", "--cached", "third_party/Makefile")
        ignored = self.supplier / ".gitignore"
        write(ignored, ignored.read_text() + "/third_party/Makefile\n")
        commit(self.supplier)
        self.assertEqual((self.source / "third_party/Makefile").read_bytes(),
                         (self.supplier / "third_party/Makefile").read_bytes())
        report = self.inspect_dependencies()
        self.assertEqual(report["source"]["outcome"], "pass", report)
        self.assertBlocked(report, "dependency reuse could not be verified")

    def test_clean_supplier_with_different_submodule_commit_is_rejected(self):
        checkout = self.supplier / "third_party/ramulator"
        write(checkout / "unrelated-input.txt", "a different pinned dependency\n")
        commit(checkout)
        commit(self.supplier)
        report = self.inspect_dependencies()
        self.assertEqual(report["source"]["outcome"], "pass", report)
        self.assertBlocked(report, "different recursive submodule pins")
        self.assertFalse(report["gitlinks_match"])

    def test_uninitialized_supplier_submodule_is_blocked(self):
        git(self.supplier, "submodule", "deinit", "-f", "--", "third_party/ramulator")
        report = self.inspect_dependencies()
        self.assertBlocked(report, "submodule")
        self.assertFalse(report["gitlinks_match"])

    def test_dirty_supplier_outside_hashed_extension_inputs_remains_blocked(self):
        write(self.supplier / "configure", "uncommitted supplier edit\n")
        report = self.inspect_dependencies()
        self.assertTrue(report["gitlinks_match"])
        self.assertEqual(len(report["libraries"]), 3)
        self.assertBlocked(report, "tracked changes")

    def test_hidden_supplier_edits_are_blocked_by_real_index_inspection(self):
        for flag in ("skip-worktree", "assume-unchanged"):
            with self.subTest(flag=flag):
                git(self.supplier, "update-index", "--" + flag, "configure")
                write(self.supplier / "configure", "hidden supplier input\n")
                self.assertEqual(git(self.supplier, "status", "--porcelain"), "")
                self.assertBlocked(self.inspect_dependencies(), flag)
                git(self.supplier, "update-index", "--no-" + flag, "configure")
                git(self.supplier, "checkout", "--", "configure")

    def test_every_reused_library_is_required(self):
        for relative in LIBRARIES:
            with self.subTest(relative=relative):
                path = self.supplier / relative
                contents = path.read_bytes()
                path.unlink()
                self.assertBlocked(self.inspect_dependencies(), "dependency reuse")
                path.write_bytes(contents)

    def test_reused_binary_changes_are_identified_despite_preserved_timestamp(self):
        before = self.inspect_dependencies()
        path = self.supplier / LIBRARIES[0]
        metadata = path.stat()
        contents = path.read_bytes()
        path.write_bytes(b"X" + contents[1:])
        os.utime(path, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
        after = self.inspect_dependencies()
        self.assertEqual(after["outcome"], "pass", after)
        self.assertEqual(before["libraries"][0]["size_bytes"], after["libraries"][0]["size_bytes"])
        self.assertNotEqual(before["libraries"][0]["sha256"], after["libraries"][0]["sha256"])

    def test_external_library_symlink_cannot_supply_identical_bytes(self):
        path = self.supplier / LIBRARIES[0]
        outside = self.base / "outside-library.a"
        outside.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(outside)
        self.assertBlocked(self.inspect_dependencies(), "contained regular file")

    @unittest.skipUnless(hasattr(os, "mkfifo"), "requires POSIX FIFOs")
    def test_library_fifo_is_rejected_without_a_writer(self):
        path = self.supplier / LIBRARIES[0]
        path.unlink()
        os.mkfifo(path)
        self.assertBlocked(self.inspect_dependencies(), "contained regular file")

    def test_each_dependency_header_tree_must_be_nonempty(self):
        for relative in HEADER_ROOTS:
            with self.subTest(relative=relative):
                header = self.supplier / relative / "dependency.h"
                contents = header.read_bytes()
                header.unlink()
                self.assertBlocked(self.inspect_dependencies(), "no files")
                header.write_bytes(contents)

    def test_external_header_changes_are_retained_in_the_identity(self):
        before = self.inspect_dependencies()
        write(self.supplier / HEADER_ROOTS[0] / "dependency.h", "different external header\n")
        after = self.inspect_dependencies()
        self.assertEqual(after["outcome"], "pass", after)
        self.assertNotEqual(before["external_headers"], after["external_headers"])

    def test_gitlink_records_reject_missing_duplicate_or_uninitialized_entries(self):
        source = inventory.collect_source(self.source)
        entry = source["submodules"]["entries"][0]
        for entries in ([], [entry, entry], [dict(entry, status="not_initialized")],
                        [dict(entry, status="revision_mismatch")]):
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                inventory._gitlinks(dict(source, submodules={"entries": entries}))


class InputBindingTests(DependencyFixture):
    def setUp(self):
        super().setUp()
        self.tools = self.base / "tools"
        self.tools.mkdir()
        for relative in baseline_fixtures.BINARIES:
            executable(self.tools / relative, "printf '%s\\n' 'inert tool 1.0'\n")
        for relative in baseline_fixtures.LIBRARIES:
            write(self.tools / relative, "inert tool library\n")
        self.headers = self.base / "include"
        write(self.headers / "uuid/uuid.h", "inert uuid declaration\n")
        self.bin = self.base / "host-bin"
        self.bin.mkdir()
        frontend = self.bin / "cc1plus"
        self.marker = self.base / "frontend-executed"
        executable(frontend, "printf unexpected > " + shlex.quote(str(self.marker)) + "\nexit 99\n")
        versions = {"gcc": "gcc 11.3.0", "g++": "g++ 11.3.0", "make": "GNU Make 4.4.1",
                    "ld": "GNU ld 2.44", "as": "GNU assembler 2.44", "python3": "Python 3.12.1"}
        for name, version in versions.items():
            body = ""
            if name == "g++":
                body = ('if [ "$1" = "-print-prog-name=cc1plus" ]; then\n'
                        "  printf '%s\\n' " + shlex.quote(str(frontend)) + "\n  exit 0\nfi\n")
            executable(self.bin / name, body + "printf '%s\\n' " + shlex.quote(version) + "\n")
        self.environment = {"PATH": str(self.bin),
                            "THIRD_PARTY_DIR": str(self.supplier / "third_party"),
                            "CPLUS_INCLUDE_PATH": str(self.headers)}

    def inspect(self, **overrides):
        arguments = dict(source=self.source, tool_dir=self.tools,
                         dependency_source=self.supplier, header_dir=self.headers,
                         environment=self.environment)
        arguments.update(overrides)
        return inventory.collect_inputs(**arguments)

    def test_exact_effective_paths_collect_real_file_and_git_identities(self):
        report = self.inspect()
        self.assertEqual(report["outcome"], "pass", report)
        self.assertEqual(report["headers"], [identity(self.headers, "uuid/uuid.h")])
        self.assertEqual(report["source"]["revision"], git(self.source, "rev-parse", "HEAD"))
        self.assertEqual(set(report["tools"]["tools"]),
                         {"riscv_gcc", "llvm_clang", "verilator", "verilator_binary"})
        self.assertEqual(report["host"]["tools"]["gcc"]["sha256"],
                         identity(self.bin, "gcc")["sha256"])
        self.assertFalse(self.marker.exists())
        self.assertTrue(any("not freshly rebuilt" in item for item in report["limitations"]))
        self.assertTrue(any("do not prove an upstream origin" in item for item in report["limitations"]))

    def test_dependency_and_include_search_paths_must_match_exactly(self):
        for key in ("THIRD_PARTY_DIR", "CPLUS_INCLUDE_PATH"):
            for value in (None, "", self.environment[key] + "/",
                          self.environment[key] + os.pathsep + str(self.base)):
                with self.subTest(key=key, value=value):
                    environment = dict(self.environment)
                    if value is None:
                        del environment[key]
                    else:
                        environment[key] = value
                    report = self.inspect(environment=environment)
                    self.assertBlocked(report, "effective dependency and header paths differ")
                    self.assertIsNone(report["tools"])
                    self.assertIsNone(report["host"])

    def test_every_input_root_rejects_symlink_traversal(self):
        for name, root in (("source", self.source), ("tool_dir", self.tools),
                           ("dependency_source", self.supplier), ("header_dir", self.headers)):
            with self.subTest(name=name):
                alias = self.base / (name + "-alias")
                alias.symlink_to(root, target_is_directory=True)
                report = self.inspect(**{name: alias})
                self.assertBlocked(report, "without symlink traversal")
                self.assertIsNone(report["source"])

    def test_malformed_environment_is_blocked_without_a_probe(self):
        for environment in (None, [], "THIRD_PARTY_DIR=/different"):
            with self.subTest(environment=environment):
                report = self.inspect(environment=environment)
                self.assertBlocked(report, "must be a mapping")
                self.assertIsNone(report["tools"])

    def test_selected_source_and_supplier_blockers_both_survive_collection(self):
        write(self.source / "new-source.txt", "untracked selected source\n")
        write(self.supplier / "configure", "modified supplier source\n")
        report = self.inspect()
        self.assertBlocked(report, "source: source contains")
        self.assertTrue(any(item.startswith("dependencies: source contains")
                            for item in report["blockers"]), report)

    def test_uuid_tree_cannot_substitute_a_differently_named_header(self):
        (self.headers / "uuid/uuid.h").rename(self.headers / "uuid/other.h")
        self.assertBlocked(self.inspect(), "does not contain uuid/uuid.h")

    def test_uuid_header_changes_are_identified_even_without_git_tracking(self):
        before = self.inspect()
        write(self.headers / "uuid/uuid.h", "replacement UUID declaration\n")
        after = self.inspect()
        self.assertEqual(after["outcome"], "pass", after)
        self.assertNotEqual(before["headers"], after["headers"])

    def test_include_headers_outside_uuid_are_identified_and_content_changes_retained(self):
        for relative in ("vector", "stdint.h"):
            write(self.headers / relative, "inert include override: " + relative + "\n")
        report = self.inspect()
        self.assertEqual(report["outcome"], "pass", report)
        self.assertEqual(report["headers"], [identity(self.headers, relative)
                                              for relative in ("stdint.h", "uuid/uuid.h", "vector")])
        before = {item["path"]: item for item in report["headers"]}
        for relative in ("vector", "stdint.h"):
            with self.subTest(relative=relative):
                path = self.headers / relative
                metadata = path.stat()
                contents = path.read_bytes()
                path.write_bytes(b"X" + contents[1:])
                os.utime(path, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
                report = self.inspect()
                self.assertEqual(report["outcome"], "pass", report)
                after = {item["path"]: item for item in report["headers"]}
                self.assertEqual(after[relative], identity(self.headers, relative))
                self.assertEqual(before[relative]["size_bytes"], after[relative]["size_bytes"])
                self.assertNotEqual(before[relative]["sha256"], after[relative]["sha256"])
                self.assertEqual(before["uuid/uuid.h"], after["uuid/uuid.h"])
                before = after


class HeaderBoundaryTests(FileFixture):
    def setUp(self):
        super().setUp()
        self.root = self.base / "headers"
        (self.root / "uuid").mkdir(parents=True)

    def inspect(self):
        return inventory._header_files(self.root, ("uuid",))

    def test_nested_header_hashes_are_sorted_and_content_exact(self):
        for relative, contents in (("uuid/z.h", "zeta\n"), ("uuid/nested/a.h", "alpha\n")):
            write(self.root / relative, contents)
        self.assertEqual(self.inspect(), [identity(self.root, relative)
                                          for relative in ("uuid/nested/a.h", "uuid/z.h")])

    def test_file_symlinks_are_rejected_even_for_identical_internal_targets(self):
        write(self.root / "uuid/uuid.h", "header\n")
        (self.root / "uuid/alias.h").symlink_to("uuid.h")
        with self.assertRaisesRegex(ValueError, "contains a symlink"):
            self.inspect()

    def test_header_root_and_ancestor_symlinks_are_rejected(self):
        (self.root / "uuid").rmdir()
        write(self.root / "actual/uuid.h", "header\n")
        (self.root / "uuid").symlink_to("actual", target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.inspect()
        (self.root / "uuid").unlink()
        (self.root / "uuid").mkdir()
        (self.root / "uuid/nested").symlink_to("../actual", target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.inspect()

    @unittest.skipUnless(hasattr(os, "mkfifo"), "requires POSIX FIFOs")
    def test_nonregular_header_is_rejected_without_opening_a_fifo(self):
        os.mkfifo(self.root / "uuid/uuid.h")
        with self.assertRaisesRegex(ValueError, "nonregular"):
            self.inspect()

    def test_empty_header_tree_is_not_an_inventory(self):
        with self.assertRaisesRegex(ValueError, "no files"):
            self.inspect()

    def test_entry_limit_counts_long_chains_of_empty_directories(self):
        write(self.root / "uuid/uuid.h", "header\n")
        current = self.root / "uuid"
        with mock.patch.object(inventory, "MAX_HEADER_FILES", 4):
            for _ in range(3):
                current = current / "empty"
                current.mkdir()
            self.assertEqual(len(self.inspect()), 1)
            (current / "over-limit").mkdir()
            with self.assertRaisesRegex(ValueError, "entry limit"):
                self.inspect()

    def test_individual_file_limit_accepts_boundary_and_rejects_one_more_byte(self):
        path = self.root / "uuid/uuid.h"
        with mock.patch.object(inventory, "MAX_FILE_BYTES", 8):
            path.write_bytes(b"12345678")
            self.assertEqual(self.inspect()[0]["size_bytes"], 8)
            path.write_bytes(b"123456789")
            with self.assertRaisesRegex(ValueError, "file or byte limit"):
                self.inspect()

    def test_aggregate_byte_limit_cannot_be_evaded_by_multiple_small_files(self):
        write(self.root / "uuid/uuid.h", "123456")
        write(self.root / "uuid/extra.h", "123456")
        with mock.patch.object(inventory, "MAX_FILE_BYTES", 8), \
                mock.patch.object(inventory, "MAX_HEADER_BYTES", 12):
            self.assertEqual(sum(item["size_bytes"] for item in self.inspect()), 12)
            write(self.root / "uuid/extra.h", "1234567")
            with self.assertRaisesRegex(ValueError, "file or byte limit"):
                self.inspect()


class GeneratedRecipeTests(FileFixture):
    def setUp(self):
        super().setUp()
        self.source = self.base / "source"
        baseline_fixtures.populate_source(self.source)
        self.build = self.base / "build64"
        self.build.mkdir()
        stamp = {"XLEN": "64", "TOOLDIR": str(self.base / "tools"),
                 "OSVERSION": "ubuntu/focal", "PREFIX": str(self.build / "install"),
                 "PROFILE": "", "SOURCE_DIR": str(self.source), "BUILDDIR": str(self.build),
                 **baseline_fixtures.PINS}
        config = {"XLEN": "64", "TOOLDIR": stamp["TOOLDIR"], "OSVERSION": "ubuntu/focal",
                  "PROFILE": "", "VORTEX_HOME": str(self.source)}
        write(self.source / "config.mk.in", "".join(f"{key} ?= @{key}@\n" for key in config))
        write(self.build / ".config.stamp", " ".join(f"{key}={value}" for key, value in stamp.items()))
        write(self.build / "config.mk", "".join(f"{key} ?= {value}\n" for key, value in config.items()))
        for relative in ("VX_config.toml", "VX_types.toml", "ci/gen_config.py"):
            write(self.source / relative, (REPOSITORY / relative).read_text())
        substitutions = dict(stamp, VORTEX_HOME=str(self.source), INSTALLDIR=stamp["PREFIX"])
        for destination, origin in baseline_inventory.COPIED_BUILD_INPUTS.items():
            contents = (REPOSITORY / origin).read_text()
            write(self.source / origin, contents)
            if origin.endswith(".in"):
                for key, value in substitutions.items():
                    contents = contents.replace("@" + key + "@", value)
            write(self.build / destination, contents)
        write(self.build / "ci/blackbox.sh", (self.source / "ci/blackbox.sh").read_text())
        for relative in ("sw/VX_config.h", "hw/VX_config.vh", "sw/VX_types.h", "hw/VX_types.vh"):
            target = self.build / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            arguments = [sys.executable, "-I", "-S", "-B", str(self.source / "ci/gen_config.py"),
                         "--config", str(self.source / (target.stem + ".toml")),
                         "--output", str(target), "--format",
                         "cpp" if relative.startswith("sw/") else "verilog"]
            if target.stem == "VX_types":
                arguments.append("--resolved")
            subprocess.run(arguments, check=True, capture_output=True, timeout=10,
                           env=dict(os.environ, XLEN="64"))
            os.utime(target, (time.time() + 10, time.time() + 10))
        for destination, origin in LOCAL_COPIES.items():
            contents = (REPOSITORY / origin).read_text()
            write(self.source / origin, contents)
            write(self.build / destination, contents.replace("@VORTEX_HOME@", str(self.source))
                  if origin.endswith(".in") else contents)
        self.cases = [
            {"kind": "app", "app": "demo", "sources": ["tests/regression/demo/kernel.cpp"]},
            {"kind": "unit", "app": "VX_fpu", "sources": ["hw/unittest/VX_fpu/testbench.cpp"]},
        ]
        for case in self.cases:
            prefix = "tests/regression" if case["kind"] == "app" else "hw/unittest"
            relative = prefix + "/" + case["app"] + "/Makefile"
            write(self.source / relative, "all:\n\t@echo fixture recipe\n")
            write(self.build / relative, (self.source / relative).read_text())
            for name in case["sources"]:
                write(self.source / name, "inert selected source\n")

    def inspect(self, cases=None, **overrides):
        return inventory.collect_generated(overrides.get("build", self.build),
                                           overrides.get("source", self.source),
                                           self.cases if cases is None else cases)

    def test_current_recipes_and_real_generated_headers_have_exact_identities(self):
        report = self.inspect()
        self.assertEqual(report["outcome"], "pass", report)
        self.assertTrue(report["baseline"]["identity_matches"])
        files = {item["path"]: item for item in report["files"]}
        sources = {item["path"]: item for item in report["source_files"]}
        for relative in (*LOCAL_COPIES, "tests/regression/demo/Makefile", "hw/unittest/VX_fpu/Makefile"):
            self.assertEqual(files[relative], identity(self.build, relative))
        for case in self.cases:
            for relative in case["sources"]:
                self.assertEqual(sources[relative], identity(self.source, relative))
        self.assertNotIn("@VORTEX_HOME@", (self.build / "sw/runtime/xrt/xrt.ini").read_text())
        self.assertTrue(any("does not establish successful compilation" in item
                            for item in report["limitations"]))

    def test_every_local_generated_recipe_rejects_newer_but_stale_bytes(self):
        names = (*LOCAL_COPIES, "tests/regression/demo/Makefile", "hw/unittest/VX_fpu/Makefile")
        for relative in names:
            with self.subTest(relative=relative):
                path = self.build / relative
                contents = path.read_bytes()
                path.write_bytes(contents + b"\n# substituted recipe\n")
                os.utime(path, (2_000_000_000, 2_000_000_000))
                self.assertBlocked(self.inspect(), "generated recipe differs from source: " + relative)
                path.write_bytes(contents)

    def test_templates_must_bind_the_current_source_directory(self):
        for relative in ("sim/xrtsim/verilator.vlt", "sw/runtime/xrt/xrt.ini", "hw/unittest/verilator.vlt"):
            with self.subTest(relative=relative):
                path = self.build / relative
                contents = path.read_bytes()
                self.assertIn(str(self.source).encode(), contents)
                path.write_bytes(contents.replace(str(self.source).encode(), b"/previous/source"))
                self.assertBlocked(self.inspect(), "generated recipe differs from source")
                path.write_bytes(contents)

    def test_baseline_header_drift_is_blocked_even_when_all_local_recipes_match(self):
        target = self.build / "sw/VX_config.h"
        write(target, target.read_text() + "\n#define UNRECORDED_CONFIG 1\n")
        os.utime(target, (2_000_000_000, 2_000_000_000))
        report = self.inspect()
        self.assertBlocked(report, "build provenance")
        self.assertFalse(report["baseline"]["identity_matches"])

    def test_missing_selected_source_cannot_leave_an_apparently_complete_inventory(self):
        (self.source / self.cases[0]["sources"][0]).unlink()
        self.assertBlocked(self.inspect(), "generated local recipes could not be verified")

    def test_selected_source_changes_update_the_retained_source_identity(self):
        before = self.inspect()
        relative = self.cases[0]["sources"][0]
        write(self.source / relative, "changed selected source\n")
        after = self.inspect()
        self.assertEqual(after["outcome"], "pass", after)
        previous = next(item for item in before["source_files"] if item["path"] == relative)
        current = next(item for item in after["source_files"] if item["path"] == relative)
        self.assertNotEqual(previous["sha256"], current["sha256"])

    def test_case_kind_and_directory_names_cannot_select_arbitrary_paths(self):
        mutations = [{"kind": "shell"}, {"app": "../demo"}, {"app": "/tmp/demo"},
                     {"app": "demo/child"}, {"app": "demo;touch-marker"}, {"app": "démø"},
                     {"app": ""}, {"app": None}]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                case = dict(self.cases[0], **mutation)
                self.assertBlocked(self.inspect(cases=[case]), "case contains")

    def test_source_input_paths_and_types_cannot_escape_the_selected_source(self):
        outside = self.base / "outside.cpp"
        write(outside, "outside source\n")
        for sources in ("kernel.cpp", [None], ["../outside.cpp"], [str(outside)],
                        ["tests/regression/demo/../../../../outside.cpp"]):
            with self.subTest(sources=sources):
                case = dict(self.cases[0], sources=sources)
                self.assertBlocked(self.inspect(cases=[case]), "generated local recipes could not be verified")

    def test_copied_recipe_symlinks_are_rejected_on_both_sides(self):
        relative = "sim/xrtsim/Makefile"
        for root in (self.source, self.build):
            with self.subTest(root=root.name):
                path = root / relative
                backup = root / "identical-recipe"
                path.rename(backup)
                path.symlink_to(backup)
                self.assertBlocked(self.inspect(), "not a symlink")
                path.unlink()
                backup.rename(path)

    def test_symlinked_generated_build_root_is_rejected(self):
        alias = self.base / "build-alias"
        alias.symlink_to(self.build, target_is_directory=True)
        self.assertBlocked(self.inspect(build=alias), "without symlink traversal")

    def test_oversized_local_recipe_is_blocked_even_when_both_copies_match(self):
        relative = "sim/xrtsim/Makefile"
        contents = "#" * (inventory.MAX_FILE_BYTES + 1)
        write(self.source / relative, contents)
        write(self.build / relative, contents)
        self.assertBlocked(self.inspect(), "input file exceeds its byte limit")


class HelperClosureTests(FileFixture):
    def setUp(self):
        super().setUp()
        self.root = self.base / "helpers"
        self.root.mkdir()
        for relative in ("local_qualification.py", "local_qualification_cases.py",
                         "local_qualification_inventory.py"):
            write(self.root / relative, "# inert helper fixture\n")
        write(self.root / "p01_toolchain.lock.json", "{\"fixture\": true}\n")
        self.enterContext(mock.patch.object(inventory, "HERE", self.root))

    def test_transitive_imports_cycles_and_nested_imports_are_hashed_without_execution(self):
        write(self.root / "local_qualification.py", "import first_helper\n")
        write(self.root / "first_helper.py",
              "from second_helper import check\nraise AssertionError('must not execute')\n")
        write(self.root / "second_helper.py", "def check():\n    import third_helper\n")
        write(self.root / "third_helper.py", "import first_helper\nimport pathlib\n")
        write(self.root / "unrelated_helper.py", "raise AssertionError('not imported')\n")
        expected = sorted(("local_qualification.py", "local_qualification_cases.py",
                           "local_qualification_inventory.py", "first_helper.py",
                           "second_helper.py", "third_helper.py")) + ["p01_toolchain.lock.json"]
        self.assertEqual(inventory.collect_helpers(), [identity(self.root, name) for name in expected])

    def test_transitive_helper_and_lock_changes_cannot_reuse_an_old_identity(self):
        write(self.root / "local_qualification.py", "import indirect\n")
        write(self.root / "indirect.py", "VALUE = 1\n")
        for relative in ("indirect.py", "p01_toolchain.lock.json"):
            with self.subTest(relative=relative):
                before = {item["path"]: item for item in inventory.collect_helpers()}
                write(self.root / relative, "VALUE = 2\n" if relative.endswith(".py") else "{}\n")
                after = {item["path"]: item for item in inventory.collect_helpers()}
                self.assertNotEqual(before[relative]["sha256"], after[relative]["sha256"])

    def test_relative_imports_cannot_silently_omit_local_dependencies(self):
        write(self.root / "local_qualification.py", "from . import hidden_helper\n")
        with self.assertRaisesRegex(ValueError, "relative local helper imports"):
            inventory.collect_helpers()

    def test_helper_count_limit_rejects_partial_closure_and_accepts_exact_boundary(self):
        write(self.root / "local_qualification.py", "import extra_helper\n")
        write(self.root / "extra_helper.py", "VALUE = 1\n")
        with mock.patch.object(inventory, "MAX_HELPERS", 4):
            self.assertEqual(len(inventory.collect_helpers()), 5)
        with mock.patch.object(inventory, "MAX_HELPERS", 3):
            with self.assertRaisesRegex(ValueError, "closure exceeds"):
                inventory.collect_helpers()

    def test_helper_aggregate_byte_limit_accepts_boundary_and_rejects_one_more_byte(self):
        size = sum((self.root / name).stat().st_size for name in (
            "local_qualification.py", "local_qualification_cases.py", "local_qualification_inventory.py"))
        with mock.patch.object(inventory, "MAX_HELPER_BYTES", size):
            self.assertEqual(len(inventory.collect_helpers()), 4)
            path = self.root / "local_qualification.py"
            write(path, path.read_text() + "\n")
            with self.assertRaisesRegex(ValueError, "closure exceeds"):
                inventory.collect_helpers()

    def test_oversized_helper_is_rejected_before_ast_parsing(self):
        write(self.root / "local_qualification.py", "#" * 65)
        with mock.patch.object(inventory, "MAX_FILE_BYTES", 64):
            with self.assertRaisesRegex(ValueError, "input file exceeds"):
                inventory.collect_helpers()

    def test_helper_symlinks_cannot_substitute_identical_internal_bytes(self):
        path = self.root / "local_qualification.py"
        path.rename(self.root / "real.py")
        path.symlink_to("real.py")
        with self.assertRaisesRegex(ValueError, "not a symlink"):
            inventory.collect_helpers()

    @unittest.skipUnless(hasattr(os, "mkfifo"), "requires POSIX FIFOs")
    def test_helper_fifo_is_rejected_without_waiting_for_a_writer(self):
        path = self.root / "local_qualification.py"
        path.unlink()
        os.mkfifo(path)
        with self.assertRaisesRegex(ValueError, "regular file"):
            inventory.collect_helpers()

    def test_missing_lock_cannot_return_only_the_python_helper_hashes(self):
        (self.root / "p01_toolchain.lock.json").unlink()
        with self.assertRaises(ValueError):
            inventory.collect_helpers()


if __name__ == "__main__":
    unittest.main()
