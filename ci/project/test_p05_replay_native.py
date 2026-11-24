# SPDX-License-Identifier: Apache-2.0
"""Synthetic host-only native replay checks; no original archive or native run."""

import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import p05_replay_native as replay
from p05_execution_records import select_matmul_cases, select_model_cases
from p02_wmma_fixtures import load_cases as load_matmul_cases
from p04_fixture_adapter import load_cases as load_model_cases
from test_p03_execution_records import result as matmul_result, output as matmul_output
from test_p04_execution_records import result as model_result, output as model_output


REVISION = "1" * 40
MODEL_ID = "2" * 64
MATMUL_ID = "3" * 64
SCOPE = "SYNTHETIC HOST-ONLY DATA; NO ACCELERATOR EXECUTION"


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def descriptor(name, body):
    return {"path": name, "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)}


class MemoryView:
    """Small bounded data view, with no producer-path filesystem operations."""

    def __init__(self, files, prefix=""):
        self.payloads, self.prefix = files, prefix

    def name(self, relative):
        return self.prefix + "/" + relative if self.prefix else relative

    def files(self):
        prefix = self.prefix + "/" if self.prefix else ""
        return tuple(name[len(prefix):] for name in sorted(self.payloads) if name.startswith(prefix))

    def subview(self, relative):
        return MemoryView(self.payloads, self.name(relative))

    def read(self, relative, *, limit=16 * 1024 * 1024):
        body = self.payloads[self.name(relative)]
        if len(body) > limit:
            raise ValueError("synthetic member exceeds bound")
        return body

    def identity(self, relative):
        return descriptor(relative, self.read(relative, limit=replay.MAX_MEMBER_BYTES))

    def verified(self, row, expected_path=None, *, limit=16 * 1024 * 1024):
        replay._descriptor(row)
        body = self.read(row["path"], limit=limit)
        if descriptor(row["path"], body) != row or (expected_path is not None and expected_path != row["path"]):
            raise ValueError("synthetic retained descriptor differs")
        return body

    def json(self, relative, *, integers_only=False):
        return json.loads(self.read(relative))

    def document(self, row, expected_path=None, *, integers_only=False):
        return json.loads(self.verified(row, expected_path))

    def inventory(self):
        return [self.identity(name) for name in self.files()]


def synthetic_results(fmt="fp16"):
    matmuls = select_matmul_cases(load_matmul_cases(replay.ROOT), fmt)
    models = select_model_cases(load_model_cases(replay.ROOT), fmt)
    files, model_rows, matmul_rows = {}, [], []
    for case in models:
        rows = [model_result(case, iteration) for iteration in range(2)]
        for row in rows:
            row.update(source_revision=REVISION, qualification_id=MODEL_ID)
            for stage in row["trace"]["native"]:
                stage["dispatch"]["qualification_id"] = MODEL_ID
        files["native/logs/simx-" + fmt + "-" + case["id"] + ".log"] = model_output(rows).encode()
        model_rows.append({"id": case["id"], "outcome": "pass", "observations": rows})
    for case in matmuls:
        rows = [dict(matmul_result(case, iteration), qualification_id=MATMUL_ID) for iteration in range(2)]
        files["python/logs/native-" + case["id"] + ".log"] = matmul_output(rows).encode()
        matmul_rows.append({"id": case["id"], "observations": rows})
    native = {"variants": [{"cases": model_rows}], "completed_case_executions": 5,
              "completed_model_runs": 10, "completed_launches": 30,
              "comparison_counts": {"hidden_words": 1280, "bridge_words": 640,
                                    "output_block_words": 640, "assembled_output_words": 640},
              "tensor_h2d_bytes": 19200, "tensor_d2h_bytes": 7680}
    python = {"native_matmuls": matmul_rows, "native_counts": {"matmul_runs": 6, "model_runs": 10,
              "matmul_launches": 6, "model_launches": 30, "total_launches": 36},
              "completed_native_and_python_launches": 72}
    return files, native, python, matmuls, models


class NativeResultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.samples = {fmt: synthetic_results(fmt) for fmt in ("fp16", "bf16")}

    def sample(self, fmt="fp16"):
        return copy.deepcopy(self.samples[fmt])

    def verify(self, sample, fmt="fp16"):
        files, native, python, matmuls, models = sample
        view = MemoryView(files)
        return replay._results(view.subview("native"), view.subview("python"), native, python,
                               matmuls, models, MODEL_ID, MATMUL_ID, REVISION, fmt)

    def rewrite_model_log(self, sample, index=0):
        case = sample[1]["variants"][0]["cases"][index]
        sample[0]["native/logs/simx-fp16-" + case["id"] + ".log"] = model_output(case["observations"]).encode()

    def rewrite_matmul_log(self, sample, index=0):
        case = sample[2]["native_matmuls"][index]
        sample[0]["python/logs/native-" + case["id"] + ".log"] = matmul_output(case["observations"]).encode()

    def test_both_formats_reconstruct_fresh_comparator_dicts_and_counts(self):
        for fmt in ("fp16", "bf16"):
            sample = self.sample(fmt)
            matmuls, models, counts = self.verify(sample, fmt)
            self.assertEqual(counts, {"matmul_runs": 6, "model_runs": 10, "matmul_launches": 6,
                                      "model_launches": 30, "total_launches": 36})
            self.assertEqual(list(matmuls), [row["id"] for row in sample[3]])
            self.assertEqual(list(models), [row["id"] for row in sample[4]])
            self.assertIsNot(matmuls[next(iter(matmuls))], sample[2]["native_matmuls"][0]["observations"])
            self.assertIsNot(models[next(iter(models))], sample[1]["variants"][0]["cases"][0]["observations"])

    def test_report_only_model_or_matmul_change_is_rejected(self):
        for model in (True, False):
            sample = self.sample()
            if model:
                sample[1]["variants"][0]["cases"][0]["observations"][0]["trace"]["advance_ns"] += 1
            else:
                sample[2]["native_matmuls"][0]["observations"][0]["dispatch"]["waits"] += 1
            with self.subTest(model=model), self.assertRaisesRegex(ValueError, "report/raw"):
                self.verify(sample)

    def test_matching_raw_and_report_output_corruption_is_rejected(self):
        sample = self.sample()
        sample[2]["native_matmuls"][0]["observations"][0]["actual_bits"][0] = "ffffffff"
        self.rewrite_matmul_log(sample)
        with self.assertRaisesRegex(ValueError, "independent fixture"):
            self.verify(sample)
        for key in ("hidden_words", "bridge_words", "output_words"):
            sample = self.sample()
            sample[1]["variants"][0]["cases"][0]["observations"][0]["trace"][key][0] = "ffffffff"
            self.rewrite_model_log(sample)
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.verify(sample)

    def test_actual_stage_operands_are_checked_against_frozen_model(self):
        for key in ("a_bytes", "b_bytes", "output_words"):
            sample = self.sample()
            stage = sample[1]["variants"][0]["cases"][0]["observations"][0]["trace"]["native"][0]
            if key == "output_words":
                stage[key][0] = "ffffffff"
            else:
                stage[key] = "ff" + stage[key][2:]
            self.rewrite_model_log(sample)
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.verify(sample)

    def test_poison_cleanup_and_resource_failure_are_rejected(self):
        for field in ("poison", "cleanup", "resources"):
            sample = self.sample()
            row = sample[2]["native_matmuls"][0]["observations"][1]
            if field == "poison":
                row["dispatch"]["poison"] = 0x7FC0DEAD
            elif field == "cleanup":
                row["resources"]["cleanup"] = 1
            else:
                row["resources"]["used_after"] += 4
            self.rewrite_matmul_log(sample)
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.verify(sample)

    def test_missing_duplicate_or_reordered_cases_are_rejected(self):
        for kind in ("model", "matmul"):
            for operation in ("pop", "duplicate", "reverse"):
                sample = self.sample()
                rows = sample[1]["variants"][0]["cases"] if kind == "model" else sample[2]["native_matmuls"]
                if operation == "pop":
                    rows.pop()
                elif operation == "duplicate":
                    rows[1] = copy.deepcopy(rows[0])
                else:
                    rows.reverse()
                with self.subTest(kind=kind, operation=operation), self.assertRaises(ValueError):
                    self.verify(sample)

    def test_all_declared_counts_are_derived(self):
        for field in ("completed_case_executions", "completed_model_runs", "completed_launches",
                      "tensor_h2d_bytes", "tensor_d2h_bytes"):
            sample = self.sample()
            sample[1][field] += 1
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.verify(sample)
        for field in ("hidden_words", "bridge_words", "output_block_words", "assembled_output_words"):
            sample = self.sample()
            sample[1]["comparison_counts"][field] += 1
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.verify(sample)
        sample = self.sample()
        sample[2]["native_counts"]["total_launches"] = 108
        with self.assertRaises(ValueError):
            self.verify(sample)

    def test_no_producer_path_access_or_subprocess_is_needed_for_records(self):
        sample = self.sample()
        with patch.object(Path, "open", side_effect=AssertionError("filesystem access")), \
             patch.object(Path, "resolve", side_effect=AssertionError("path resolution")), \
             patch("subprocess.Popen", side_effect=AssertionError("process launch")):
            self.assertEqual(self.verify(sample)[2]["total_launches"], 36)


class NativeEnvelopeTests(unittest.TestCase):
    def test_every_copied_member_is_byte_identical(self):
        files = {"left/record.json": b"{}", "right/record.json": b"{}",
                 "left/unused.py": b"raise RuntimeError('NEVER EXECUTE')\n",
                 "right/unused.py": b"raise RuntimeError('NEVER EXECUTE')\n"}
        view = MemoryView(files)
        replay._copies(view.subview("left"), view.subview("right"), "synthetic")
        files["right/unused.py"] += b"# changed\n"
        with self.assertRaisesRegex(ValueError, "copied member bytes"):
            replay._copies(view.subview("left"), view.subview("right"), "synthetic")

    def test_missing_and_extra_copied_members_are_rejected(self):
        view = MemoryView({"left/data": b"a", "right/data": b"a", "right/extra": b"b"})
        with self.assertRaisesRegex(ValueError, "members"):
            replay._copies(view.subview("left"), view.subview("right"), "synthetic")

    def test_public_entry_rejects_bad_pins_before_any_archive_access(self):
        for revision, fmt in ((True, "fp16"), ("A" * 40, "fp16"), (REVISION, "fp32")):
            with self.subTest(revision=revision, fmt=fmt), self.assertRaises(ValueError):
                replay.verify_native(None, expected_revision=revision, expected_format=fmt)

    def test_recorded_paths_are_strictly_lexical(self):
        with patch.object(Path, "resolve", side_effect=AssertionError("must not resolve")):
            self.assertEqual(str(replay._path("/nonexistent/producer", absolute=True)), "/nonexistent/producer")
            for name in ("/a/../b", "//producer", "/a//b", "/a/./b", "/a\\b", "/a\nb"):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    replay._path(name, absolute=True)

    def test_command_receipt_and_log_bytes_are_required(self):
        body = (SCOPE + "\n").encode()
        log = descriptor("logs/check.log", body)
        row = {"id": "check", "argv": ["/producer/tool", "--check"], "cwd": "/producer/work",
               "environment": {}, "log": log["path"], "log_sha256": log["sha256"],
               "log_size_bytes": log["size_bytes"], "timeout_seconds": 30, "outcome": "pass", "exit_code": 0,
               "reason": None, "process_started": True, "duration_seconds": 0.1, "peak_rss_bytes": 1024,
               "cleanup_complete": True, "limitations": list(replay.PROCESS_LIMITATIONS)}
        view = MemoryView({log["path"]: body})
        report = {"commands": [row], "budget": {"max_rss_bytes": 4096}}
        self.assertEqual(replay._commands(view, report, ["check"])["check"], row)
        for key, value in (("exit_code", 1), ("exit_code", False), ("cleanup_complete", False),
                           ("process_started", False), ("reason", "aborted"), ("duration_seconds", 999),
                           ("peak_rss_bytes", 8192), ("log_sha256", "0" * 64), ("log_size_bytes", 0)):
            bad = copy.deepcopy(report)
            bad["commands"][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                replay._commands(view, bad, ["check"])
        view.payloads["logs/check.log"] += b"altered"
        with self.assertRaises(ValueError):
            replay._commands(view, report, ["check"])

    def test_empty_missing_duplicate_and_extra_command_receipts_are_rejected(self):
        view = MemoryView({"logs/extra.log": b""})
        for rows in ([], [{"id": "a"}, {"id": "a"}], [{"id": "b"}]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                replay._commands(view, {"commands": rows}, ["a"])

    def test_trusted_fixture_loaders_receive_only_the_reviewed_root(self):
        files = {"artifacts/source/ci/project/fixtures/" + name:
                 (replay.ROOT / "ci/project/fixtures" / name).read_bytes() for name in replay.FIXTURES}
        files["artifacts/source/profiles/p02-tfr.json"] = (replay.ROOT / "profiles/p02-tfr.json").read_bytes()
        view = MemoryView(files)
        with patch.object(replay, "load_matmul_cases", wraps=load_matmul_cases) as matmul_loader, \
             patch.object(replay, "load_model_cases", wraps=load_model_cases) as model_loader:
            matmuls, models = replay._frozen_cases(view, "fp16")
            self.assertEqual((len(matmuls), len(models)), (3, 5))
            matmul_loader.assert_called_once_with(replay.ROOT)
            model_loader.assert_called_once_with(replay.ROOT)
        files["artifacts/source/ci/project/fixtures/p04_tiny_mlp_v1.json"] += b" "
        with self.assertRaisesRegex(ValueError, "frozen fixture differs"):
            replay._frozen_cases(view, "fp16")

    def test_finished_report_cannot_claim_acceptance_or_incomplete_execution(self):
        report = {"schema_version": 1, "contract_id": "synthetic", "state": "finished", "outcome": "pass",
                  "reason": None, "development": False, "acceptance_claimed": False, "phase_complete": False,
                  "iterations": 2, "started_at": "2026-01-01T00:00:00+00:00", "finished_at": "2026-01-01T00:00:01+00:00",
                  "limitations": [SCOPE]}
        replay._finished(report, "synthetic")
        for key, value in (("acceptance_claimed", True), ("state", "running"), ("outcome", "blocked"),
                           ("iterations", True), ("finished_at", "2025-01-01T00:00:00+00:00")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                replay._finished(dict(report, **{key: value}), "synthetic")


if __name__ == "__main__":
    unittest.main()
