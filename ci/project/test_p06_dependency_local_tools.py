# SPDX-License-Identifier: Apache-2.0
"""Exercise real local tool files behind a synthetic validated dependency graph."""

from copy import deepcopy
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

import p06_dependency_admission as admission
import p06_dependency_contract as contract
from test_p06_dependency_admission import LiveInputs, REVISION
from test_p06_dependency_local_prepare import synthetic_preparation


class LocalNativeToolAdmissionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="p06-native-local-tools-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        host = self.root / "host-cxx"
        host.write_bytes(b"synthetic host compiler")
        self.host_tools = {"g++": admission.base._file_identity(host)}
        self.inputs = LiveInputs(self.source, self.host_tools)
        self.preparation = synthetic_preparation(self.root, REVISION)
        tool_root = Path(self.preparation["tools_dir"])
        for name, row in self.preparation["toolchain_receipt"]["tools"].items():
            path = Path(row["path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(path.relative_to(tool_root).as_posix().encode())
            path.chmod(0o644 if name.startswith(("libc64/", "libcrt64/")) else 0o755)
        self.freeze_preparation()

    def freeze_preparation(self):
        self.inputs.preparation_path.write_bytes(contract.json_bytes(self.preparation) + b"\n")
        self.inputs.document["preparation"] = dict(admission._live_identity(self.inputs.preparation_path),
                                                   path=self.inputs.preparation_path.name)
        self.inputs.write()

    def managed_tools(self):
        return {**deepcopy(self.host_tools), **deepcopy(self.preparation["toolchain_receipt"]["tools"])}

    def test_all_eleven_local_tools_join_at_every_live_stability_boundary(self):
        checked = self.inputs.admit()
        self.assertEqual(len(checked.local_toolchain_tools), 11)
        before = checked.verify_stable(self.managed_tools())
        after = checked.verify_stable(self.managed_tools())
        self.assertEqual(before, after)
        self.assertEqual(set(before), {"receipt_sha256", "source_inputs_sha256", "staged_files_sha256",
                                       "tools_sha256", "helper_sources_sha256"})
        self.assertTrue(all(checked.summary["verification"][name] is False for name in contract.FALSE_CLAIMS))

    def test_changed_compiler_and_library_bytes_are_rejected_before_native_execution(self):
        checked = self.inputs.admit()
        for name in ("clang", "libc64/lib/libm.a"):
            path = Path(checked.local_toolchain_tools[name]["path"])
            original = path.read_bytes()
            path.write_bytes(b"x" * len(original))
            try:
                with self.subTest(name=name), self.assertRaisesRegex(ValueError, "locally provisioned tool identity changed"):
                    checked.verify_stable(self.managed_tools())
            finally:
                path.write_bytes(original)

    def test_changed_compiler_bytes_are_rejected_on_initial_admission(self):
        path = Path(self.preparation["toolchain_receipt"]["tools"]["clang"]["path"])
        path.write_bytes(b"another compiler")
        with self.assertRaisesRegex(ValueError, "locally provisioned tool identity changed"):
            self.inputs.admit()

    def test_identical_tool_at_another_invoked_path_cannot_replace_the_selected_tool(self):
        checked = self.inputs.admit()
        observed = self.managed_tools()
        original = Path(observed["clang"]["path"])
        copied = self.root / "copied-clang"
        shutil.copyfile(original, copied)
        copied.chmod(0o755)
        observed["clang"] = admission.base._file_identity(copied)
        self.assertEqual(observed["clang"]["sha256"], checked.local_toolchain_tools["clang"]["sha256"])
        with self.assertRaisesRegex(ValueError, "managed and locally provisioned tools differ: clang"):
            checked.verify_stable(observed)

    def test_missing_native_tool_in_managed_snapshot_is_rejected(self):
        checked = self.inputs.admit()
        for name in checked.local_toolchain_tools:
            observed = self.managed_tools()
            del observed[name]
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "managed and locally provisioned tools differ"):
                checked.verify_stable(observed)

    def test_changed_managed_tool_digest_is_rejected(self):
        checked = self.inputs.admit()
        observed = self.managed_tools()
        observed["riscv-gcc"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "managed and locally provisioned tools differ: riscv-gcc"):
            checked.verify_stable(observed)

    def test_same_bytes_retargeted_through_an_alias_are_rejected(self):
        checked = self.inputs.admit()
        original = Path(checked.local_toolchain_tools["clang"]["path"])
        moved = original.with_name("clang-other")
        original.rename(moved)
        original.symlink_to(moved.name)
        with self.assertRaisesRegex(ValueError, "locally provisioned tool identity changed: clang"):
            checked.verify_stable(self.managed_tools())

    def test_recorded_archive_symlink_is_supported_without_path_relaxation(self):
        toolchain = self.preparation["toolchain_receipt"]
        tools = toolchain["tools"]
        alias = Path(tools["clang++"]["path"])
        original_size = alias.stat().st_size
        alias.unlink()
        alias.symlink_to("clang")
        relative = alias.relative_to(self.preparation["tools_dir"]).as_posix()
        toolchain["members"] = [
            {"path": relative, "kind": "symlink", "target": "clang"} if row["path"] == relative else row
            for row in toolchain["members"]]
        toolchain["extracted_regular_bytes"] -= original_size
        tools["clang++"] = dict(tools["clang"], path=str(alias))
        self.freeze_preparation()
        checked = self.inputs.admit()
        checked.verify_stable(self.managed_tools())

    def test_lost_compiler_executable_mode_is_rejected_even_when_bytes_match(self):
        checked = self.inputs.admit()
        path = Path(checked.local_toolchain_tools["clang"]["path"])
        path.chmod(0o644)
        self.assertEqual(admission.base._file_identity(path), checked.local_toolchain_tools["clang"])
        with self.assertRaisesRegex(ValueError, "locally provisioned compiler is not executable"):
            checked.verify_stable(self.managed_tools())

    def test_preparation_bytes_changed_between_admission_and_run_are_rejected(self):
        checked = self.inputs.admit()
        path = self.inputs.preparation_path
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "dependency preparation changed after admission"):
            checked.verify_stable(self.managed_tools())

    def test_preparation_bytes_changed_after_graph_validation_are_rejected(self):
        path = self.inputs.preparation_path
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "dependency preparation changed after validation"):
            self.inputs.admit()

    def test_oversized_preparation_is_rejected_before_reading_its_body(self):
        path = self.inputs.preparation_path
        with path.open("r+b") as stream:
            stream.truncate(contract.MAX_RECEIPT_BYTES + 1)
        original_open = Path.open

        def guarded_open(target, *args, **kwargs):
            self.assertNotEqual(target, path, "oversized preparation was opened")
            return original_open(target, *args, **kwargs)

        with mock.patch.object(Path, "open", guarded_open), self.assertRaisesRegex(ValueError, "bounded, unlinked regular file"):
            self.inputs.admit()

    def test_preparation_symlink_cannot_redirect_a_validated_descriptor(self):
        path = self.inputs.preparation_path
        moved = path.with_name("alternate-preparation.json")
        path.rename(moved)
        path.symlink_to(moved.name)
        with self.assertRaisesRegex(ValueError, "without symlink traversal"):
            self.inputs.admit()

    def test_preparation_contract_is_revalidated_at_the_live_boundary(self):
        self.preparation["contract_id"] = "unreviewed-local-preparation"
        self.freeze_preparation()
        with self.assertRaisesRegex(ValueError, "hosted preparation cannot carry local or unrecognized metadata"):
            self.inputs.admit()

    def test_local_tool_population_cannot_be_reduced_before_admission(self):
        del self.preparation["toolchain_receipt"]["tools"]["clang"]
        self.freeze_preparation()
        with self.assertRaisesRegex(ValueError, "selected native tool inventory differs"):
            self.inputs.admit()


if __name__ == "__main__":
    unittest.main()
