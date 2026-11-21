# SPDX-License-Identifier: Apache-2.0
"""Host-only framework orchestration checks; never install/import a framework.

Synthetic wheels and inert packet files exercise rejection and retention seams.
No mock result in this module is native/framework qualification evidence.
"""
from contextlib import ExitStack, redirect_stderr
import ast
import hashlib
import io
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest import mock
import warnings
import zipfile

import p05_torch_execute as runner


ROOT = runner.ROOT


def write(path, raw=b"synthetic host-only bytes\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return {"path": path.name, "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}


def args(root, *options):
    return runner.argument_parser().parse_args([
        "run", "--source-dir", str(ROOT), "--python-work", str(root / "python-work"),
        "--python-output", str(root / "python-output"), "--wheelhouse", str(root / "wheelhouse"),
        "--work-dir", str(root / "work"), "--output", str(root / "output"), "--format", "fp16", *options,
    ])


class TemporaryCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="p05-torch-host-only-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()


class PathContracts(TemporaryCase):
    def setUp(self):
        super().setUp()
        for name in ("python-work", "python-output", "wheelhouse"):
            (self.root / name).mkdir()

    def test_original_stage_roots_are_required(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            runner.argument_parser().parse_args(["run", "--format", "fp16"])

    def test_fresh_external_roots_and_venv_convention(self):
        paths = runner.resolve_paths(args(self.root))
        self.assertEqual(paths["work"] / "venv/bin/python", self.root / "work/venv/bin/python")
        (self.root / "work").mkdir()
        with self.assertRaisesRegex(ValueError, "fresh"):
            runner.resolve_paths(args(self.root))

    def test_overlapping_roots_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "separate"):
            runner.resolve_paths(args(self.root, "--output", str(self.root / "python-output/child")))

    def test_symlinked_input_root_is_rejected(self):
        (self.root / "alias").symlink_to(self.root / "python-work", target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            runner.resolve_paths(args(self.root, "--python-work", str(self.root / "alias")))

    def test_no_imported_earlier_execution_or_native_build_command(self):
        tree = ast.parse(Path(runner.__file__).read_text())
        earlier = {"python_run", "base", "model_run", "matmul_run", "bundle_producer"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                root = node.func.value
                while isinstance(root, ast.Attribute):
                    root = root.value
                if isinstance(root, ast.Name) and root.id in earlier:
                    self.assertNotIn(node.func.attr, ("main", "execute", "execute_run"))
        self.assertNotIn("torch", sys.modules)


class WheelhouseContracts(TemporaryCase):
    def setUp(self):
        super().setUp()
        self.source, self.wheelhouse = self.root / "source", self.root / "wheelhouse"
        self.wheelhouse.mkdir()
        names = ("filelock", "fsspec", "Jinja2", "MarkupSafe", "mpmath", "networkx", "numpy", "setuptools",
                 "sympy", "torch", "typing_extensions")
        wheels = []
        lines = []
        for name in names:
            version = "2.15.0+cpu" if name == "torch" else "1.0"
            filename = name.lower() + "-" + version + "-py3-none-any.whl"
            row = write(self.wheelhouse / filename, ("SYNTHETIC HOST-ONLY WHEEL " + name).encode())
            wheels.append({"name": name, "version": version, "filename": filename,
                           "sha256": row["sha256"], "size": row["size_bytes"]})
            lines.append(name + "==" + version + " --hash=sha256:" + row["sha256"])
        lock = ("# Synthetic host-only closure; not a framework installation.\n" + "\n".join(lines) + "\n").encode()
        write(self.source / runner.LOCK, lock)
        self.contract = {"schema_version": 1, "contract_id": "p05-torch-custom-ops-v1", "acceptance_claimed": False,
            "framework": {"name": "torch", "version": "2.15.0+cpu", "distribution": "cpu", "python": "3.12.14",
                          "implementation": "CPython", "gil": True, "platform": "linux", "machine": "x86_64", "byteorder": "little"},
            "requirements": {"path": runner.LOCK, "sha256": hashlib.sha256(lock).hexdigest()}, "wheels": wheels}
        self.save()

    def save(self):
        write(self.source / runner.CONTRACT, json.dumps(self.contract).encode())

    def validate(self):
        return runner._contract(runner.bundle_producer._Inputs(), self.source, self.wheelhouse)

    def test_exact_closed_identity_set_is_accepted(self):
        value, rows = self.validate()
        self.assertEqual(value, self.contract)
        self.assertEqual(len(rows), 11)

    def test_extra_missing_and_symlink_entries_are_rejected(self):
        extra = self.wheelhouse / "extra.txt"
        write(extra)
        with self.assertRaisesRegex(ValueError, "missing or extra"):
            self.validate()
        extra.unlink()
        first = self.wheelhouse / self.contract["wheels"][0]["filename"]
        raw = first.read_bytes()
        first.unlink()
        with self.assertRaisesRegex(ValueError, "missing or extra"):
            self.validate()
        outside = self.root / "outside.whl"
        write(outside, raw)
        first.symlink_to(outside)
        with self.assertRaises(ValueError):
            self.validate()

    def test_changed_wheel_and_lock_are_rejected(self):
        first = self.wheelhouse / self.contract["wheels"][0]["filename"]
        first.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "frozen lock"):
            self.validate()
        (self.source / runner.LOCK).write_text("torch>=2\n")
        with self.assertRaisesRegex(ValueError, "lock identity"):
            self.validate()

    def test_rehashed_but_unpinned_lock_is_rejected(self):
        path = self.source / runner.LOCK
        raw = path.read_bytes() + b"--extra-index-url https://invalid.example\n"
        path.write_bytes(raw)
        self.contract["requirements"]["sha256"] = hashlib.sha256(raw).hexdigest()
        self.save()
        with self.assertRaisesRegex(ValueError, "exact manifest"):
            self.validate()

    def test_duplicate_dependencies_and_boolean_schema_are_rejected(self):
        self.contract["wheels"][-1] = self.contract["wheels"][0]
        self.save()
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.validate()
        self.contract["schema_version"] = True
        self.save()
        with self.assertRaisesRegex(ValueError, "contract"):
            self.validate()


class StreamingInstallationContracts(TemporaryCase):
    def wheel(self, members):
        path = self.root / "synthetic.whl"
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as stream:
            for name, data in members:
                stream.writestr(name, data)
        return path

    def test_large_binary_is_streamed_and_matched_to_actual_installation(self):
        # Exceeds the old source-file ceiling. The checker must never read this
        # entire member through ZipFile.read or Path.read_bytes.
        raw = b"\0" * (17 * runner.MIB)
        wheel = self.wheel([("synthetic/lib/large.so", raw), ("synthetic-1.dist-info/RECORD", b"old record")])
        with mock.patch.object(zipfile.ZipFile, "read", side_effect=AssertionError("must stream wheel payload")):
            payload, scripts = runner._wheel_payload(wheel)
        venv = self.root / "venv"
        write(venv / runner.SITE / "synthetic/lib/large.so", raw)
        write(venv / runner.SITE / "synthetic-1.dist-info/RECORD", b"rewritten by installer")
        with mock.patch.object(Path, "read_bytes", side_effect=AssertionError("must stream installed payload")):
            rows = runner._installed_inventory(venv, payload, scripts, [])
        self.assertEqual(len(rows), 2)
        with (venv / runner.SITE / "synthetic/lib/large.so").open("r+b") as stream:
            stream.write(b"X")
        with self.assertRaisesRegex(ValueError, "differs from locked wheel"):
            runner._installed_inventory(venv, payload, scripts, [])

    def test_entry_points_and_data_scheme_have_explicit_installed_paths(self):
        wheel = self.wheel([("tiny-1.dist-info/entry_points.txt", b"[console_scripts]\ntiny = tiny:main\n"),
                            ("tiny-1.data/data/share/man/man1/tiny.1", b"manual")])
        rows, scripts = runner._wheel_payload(wheel)
        self.assertEqual(scripts, ["bin/tiny"])
        self.assertIn("share/man/man1/tiny.1", {row["path"] for row in rows})

    def test_unsafe_duplicate_symlink_and_oversized_zip_members_are_rejected(self):
        link = zipfile.ZipInfo("tiny/link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        fixtures = [[("../escape", b"x")], [("tiny/a", b"x"), ("tiny/a", b"x")], [(link, b"../outside")]]
        for fixture in fixtures:
            with self.subTest(fixture=fixture), warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                with self.assertRaises(ValueError):
                    runner._wheel_payload(self.wheel(fixture))
        wheel = self.wheel([("tiny/a", b"12345")])
        with mock.patch.object(runner, "MAX_FRAMEWORK_FILE", 4), self.assertRaisesRegex(ValueError, "byte budget"):
            runner._wheel_payload(wheel)

    def test_unexplained_file_missing_script_and_changed_seed_are_rejected(self):
        wheel = self.wheel([("tiny/a.py", b"payload")])
        rows, _ = runner._wheel_payload(wheel)
        venv = self.root / "venv"
        write(venv / runner.SITE / "tiny/a.py", b"payload")
        self.assertEqual(runner._installed_inventory(venv, rows, [], []), rows)
        with self.assertRaisesRegex(ValueError, "missing files"):
            runner._installed_inventory(venv, rows, ["bin/missing"], [])
        write(venv / runner.SITE / "tiny/untracked.py")
        with self.assertRaisesRegex(ValueError, "unexplained"):
            runner._installed_inventory(venv, rows, [], [])
        (venv / runner.SITE / "tiny/untracked.py").unlink()
        seed = write(venv / "bin/python", b"seed bytes")
        seed["path"] = "bin/python"
        write(venv / "bin/python", b"changed seed")
        with self.assertRaisesRegex(ValueError, "seed interpreter"):
            runner._installed_inventory(venv, rows, [], [seed])

    def test_symlinked_installed_payload_is_rejected(self):
        venv = self.root / "venv"
        path = venv / runner.SITE / "tiny/a.py"
        write(self.root / "outside.py")
        path.parent.mkdir(parents=True)
        path.symlink_to(self.root / "outside.py")
        with self.assertRaisesRegex(ValueError, "symlink"):
            runner._installation_tree(venv)


class SyntheticStageHarness:
    def __init__(self, test):
        self.root = test.root
        for name in ("python-work", "python-output", "wheelhouse"):
            (self.root / name).mkdir()
        self.args = args(self.root)
        self.paths = runner.resolve_paths(self.args)
        self.output = self.paths["output"]
        write(self.paths["python_output"] / "report.json", b'{"synthetic_host_only":true}\n')
        write(self.paths["python_output"] / ".hidden-failed-stamp", b"retained synthetic packet")
        self.packet = runner.python_run._tree_records(self.paths["python_output"])
        self.source = {"checkout": {"revision": "1" * 40, "tree": "2" * 40, "dirty": False,
            "changed_paths": [], "untracked_paths": [], "blockers": []}, "files": []}
        self.stage_error = ValueError("injected original P05 revalidation rejection")
        stack = ExitStack()
        test.addCleanup(stack.close)
        stack.enter_context(mock.patch.object(runner, "source_snapshot", return_value=self.source))
        stack.enter_context(mock.patch.object(runner, "SOURCE_FILES", ()))
        stack.enter_context(mock.patch.object(runner, "LOADED_HELPERS", []))
        stack.enter_context(mock.patch.object(runner.base, "_resources", return_value={
            "available_memory_bytes": runner.BUDGET["max_rss_bytes"],
            "free_disk_bytes": {name: runner.BUDGET["min_free_bytes"] for name in ("source", "work", "output")}}))
        self.native_entry = stack.enter_context(mock.patch.object(runner.python_run.model_run, "execute",
            side_effect=AssertionError("no earlier native runner may execute")))
        self.python_entry = stack.enter_context(mock.patch.object(runner.python_run, "execute",
            side_effect=AssertionError("no earlier Python runner may execute")))
        self.verifier = stack.enter_context(mock.patch.object(runner, "_verify_python_packet", side_effect=self.verify))
        stack.enter_context(mock.patch.object(runner, "_contract", side_effect=self.contract))
        self.process = stack.enter_context(mock.patch.object(runner, "run_bounded", side_effect=self.command))

    def contract(self, *_):
        # This injection is the synthetic boundary, not an accepted dependency
        # lock. The exercised seam starts at packet retention/revalidation.
        for name in (runner.CONTRACT, runner.LOCK):
            write(self.output / "artifacts/source" / name, b"SYNTHETIC HOST-ONLY CONTRACT\n")
        return {"synthetic_host_only": True}, []

    def verify(self, **kwargs):
        if self.stage_error is not None:
            raise self.stage_error
        bundle = self.output / "artifacts/bundle"
        write(bundle / "manifest.json", b'{"synthetic_host_only":true}')
        kwargs["report"]["bundle_artifacts"] = runner.python_run._tree_records(bundle)
        interpreter = Path(sys.executable)
        return {"bundle": bundle, "python": interpreter, "python_identity": runner.base._file_identity(interpreter)}

    def command(self, argv, cwd, env, log, **limits):
        if log.stem != "framework-create-venv":
            raise AssertionError("unexpected attempted external process")
        raw = b"SYNTHETIC STOP BEFORE VENV OR FRAMEWORK INSTALLATION\n"
        log.write_bytes(raw)
        return {"outcome": "fail", "exit_code": 9, "cleanup_complete": True,
                "reason": "injected provisioning failure", "log_sha256": hashlib.sha256(raw).hexdigest(),
                "log_size_bytes": len(raw)}

    def run(self):
        report = runner.execute(self.args, self.paths)
        saved = json.loads((self.output / "report.json").read_text())
        assert report == saved
        return report


class RetentionContracts(TemporaryCase):
    def test_rejected_input_is_preserved_without_any_framework_process(self):
        fixture = SyntheticStageHarness(self)
        report = fixture.run()
        self.assertEqual(report["outcome"], "blocked")
        self.assertEqual(report["state"], "finished")
        self.assertIn("revalidation rejection", report["reason"])
        self.assertFalse(report["acceptance_claimed"])
        self.assertFalse(report["phase_complete"])
        self.assertEqual(runner.python_run._tree_records(fixture.output / "python"), fixture.packet)
        fixture.process.assert_not_called()
        fixture.native_entry.assert_not_called()
        fixture.python_entry.assert_not_called()

    def test_nonzero_command_retains_log_receipt_and_never_passes(self):
        fixture = SyntheticStageHarness(self)
        fixture.stage_error = None
        report = fixture.run()
        self.assertEqual(report["outcome"], "fail")
        self.assertIn("injected provisioning failure", report["reason"])
        self.assertEqual([row["id"] for row in report["commands"]], ["framework-create-venv"])
        self.assertEqual(report["commands"][0]["exit_code"], 9)
        self.assertTrue((fixture.output / "logs/framework-create-venv.log").is_file())
        self.assertEqual(runner.python_run._tree_records(fixture.output / "python"), fixture.packet)
        fixture.native_entry.assert_not_called()
        fixture.python_entry.assert_not_called()

    def test_changed_retained_packet_is_reported_as_failure(self):
        fixture = SyntheticStageHarness(self)
        def reject(**kwargs):
            (fixture.output / "python/.hidden-failed-stamp").write_text("tampered copy")
            raise ValueError("injected stop")
        fixture.verifier.side_effect = reject
        report = fixture.run()
        self.assertEqual(report["outcome"], "fail")
        self.assertTrue(any("retained original P05 packet changed" in reason for reason in report["failure_reasons"]))

    def test_original_pass_string_without_matching_contract_is_rejected(self):
        root = self.root / "original"
        write(root / "report.json", b'{"outcome":"pass"}')
        with self.assertRaisesRegex(ValueError, "unsupported original P05 packet"):
            runner._verify_python_packet(inputs=runner.bundle_producer._Inputs(), source=ROOT,
                python_work=self.root / "work", python_output=root, work=self.root / "new-work",
                output=self.root / "new-output", fmt="fp16", current={}, report={})

    def test_raw_log_identity_is_checked_before_original_commands_are_trusted(self):
        root = self.root / "original"
        row = write(root / "logs/installed-matrix.log", b"first bytes\n")
        command = {"id": "installed-matrix", "outcome": "pass", "exit_code": 0, "cleanup_complete": True,
                   "reason": None, "log": "logs/installed-matrix.log", "log_sha256": row["sha256"],
                   "log_size_bytes": row["size_bytes"], "argv": ["synthetic"], "environment": {}}
        (root / command["log"]).write_bytes(b"replaced bytes\n")
        with self.assertRaisesRegex(ValueError, "command log changed"):
            runner.bundle_producer._commands(runner.bundle_producer._Inputs(), root, {"commands": [command]})


if __name__ == "__main__":
    unittest.main()
