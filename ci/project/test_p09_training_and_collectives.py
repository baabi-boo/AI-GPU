# SPDX-License-Identifier: Apache-2.0
"""Offline unit tests for ci/project/p09_training_and_collectives.py (stdlib only)."""

from __future__ import annotations

import copy
import io
import json
from pathlib import Path
import sys
import unittest
from contextlib import redirect_stdout

_THIS_DIR = str(Path(__file__).resolve().parent)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

import p09_training_and_collectives as p09


class TrainingPrototypeTests(unittest.TestCase):
    def test_fp32_gradient_accuracy_and_convergence(self):
        receipt = p09.run_train_check(precision="fp32")
        p09.validate_receipt_claim(receipt)
        self.assertEqual(receipt["outcome"], "pass")
        self.assertEqual(receipt["evidence_level"], "simulated")
        self.assertFalse(receipt["physical_fpga_measured"])
        self.assertFalse(receipt["nvlink_or_cuda_parity_claimed"])
        self.assertEqual(receipt["phase_status_effect"], "none (P09 remains not_started)")

        grad = receipt["gradient_verification"]
        self.assertTrue(grad["passed"])
        self.assertLess(grad["max_rel_err"], 1e-4)
        self.assertLess(grad["max_rel_err_w1"], 1e-4)
        self.assertLess(grad["max_rel_err_w2"], 1e-4)

        tm = receipt["training_metrics"]
        self.assertTrue(tm["monotonic_decrease"])
        self.assertTrue(tm["convergence_passed"])
        self.assertLess(tm["loss_final"], 0.5 * tm["loss_init"])
        self.assertEqual(len(tm["loss_trajectory"]), 20)

    def test_fp16_sim_gradient_and_convergence(self):
        receipt = p09.run_train_check(precision="fp16_sim")
        p09.validate_receipt_claim(receipt)
        self.assertEqual(receipt["outcome"], "pass")
        self.assertEqual(receipt["model"]["precision"], "fp16_sim")
        self.assertTrue(receipt["gradient_verification"]["passed"])
        self.assertTrue(receipt["training_metrics"]["convergence_passed"])
        self.assertLess(
            receipt["training_metrics"]["loss_final"],
            0.5 * receipt["training_metrics"]["loss_init"],
        )

    def test_training_is_deterministic_across_runs(self):
        r1 = p09.run_train_check(precision="fp32")
        r2 = p09.run_train_check(precision="fp32")
        self.assertEqual(r1, r2)

    def test_analytical_gradients_detect_intentional_perturbation(self):
        x, w1, w2, target = p09.make_synthetic_training_batch()
        cache = p09.mlp_forward(x, w1, w2, precision="fp32")
        bwd = p09.mlp_backward(cache, target, precision="fp32")
        fd_w1, fd_w2 = p09.finite_difference_gradients(x, w1, w2, target, eps=1e-6)

        bad_w1 = copy.deepcopy(bwd["grad_w1"])
        bad_w1[0][0] += 0.05
        self.assertGreater(p09._max_relative_error(bad_w1, fd_w1), 1e-4)
        self.assertLess(p09._max_relative_error(bwd["grad_w2"], fd_w2), 1e-4)

    def test_rejects_invalid_training_hyperparameters(self):
        with self.assertRaises(ValueError):
            p09.run_train_check(precision="fp8")
        with self.assertRaises(ValueError):
            p09.run_train_check(steps=1)
        with self.assertRaises(ValueError):
            p09.run_train_check(learning_rate=0.0)
        with self.assertRaises(ValueError):
            p09.run_train_check(learning_rate=float("nan"))

    def test_fp16_overflow_is_rejected_not_silently_inf(self):
        with self.assertRaises(ValueError):
            p09.quantize_fp16(1e5)


class CollectivePrototypeTests(unittest.TestCase):
    def test_collective_allreduce_broadcast_barrier_and_recovery_all_failure_modes(self):
        for mode in ("none", "link_drop", "rank_timeout", "rank_reset"):
            with self.subTest(failure_mode=mode):
                receipt = p09.run_collective_check(payload_len=32, failure_mode=mode)
                p09.validate_receipt_claim(receipt)
                self.assertEqual(receipt["outcome"], "pass")
                self.assertTrue(receipt["correctness"]["allreduce_exact"])
                self.assertTrue(receipt["correctness"]["broadcast_exact"])
                self.assertTrue(receipt["correctness"]["barrier_ok"])
                self.assertTrue(receipt["correctness"]["ordering_preserved"])
                if mode == "none":
                    self.assertFalse(receipt["failure_and_recovery"]["failure_detected"])
                    self.assertIsNone(receipt["failure_and_recovery"]["failure_code"])
                else:
                    self.assertTrue(receipt["failure_and_recovery"]["failure_detected"])
                    self.assertIsNotNone(receipt["failure_and_recovery"]["failure_code"])
                self.assertTrue(receipt["failure_and_recovery"]["post_recovery_exact"])

                cost = receipt["communication_cost"]
                self.assertEqual(cost["baseline_messages"], 7)
                self.assertEqual(cost["baseline_payload_bytes"], 32 * 4 * 3 + 4 * 4)
                self.assertEqual(cost["baseline_protocol_overhead_bytes"], 7 * 32)
                self.assertGreater(cost["simulated_comm_time_us"], 0.0)
                if mode == "none":
                    self.assertEqual(receipt["failure_and_recovery"]["recovery_epoch"], 1)
                    self.assertEqual(cost["total_messages"], 7)
                else:
                    self.assertEqual(receipt["failure_and_recovery"]["recovery_epoch"], 2)
                    self.assertEqual(cost["total_messages"], 11)

    def test_ordering_violation_is_detected(self):
        transport = p09.SimulatedTwoDeviceTransport()
        transport.send(0, 1, "allreduce_sum", [1, 2, 3])
        transport.send(0, 1, "broadcast_r0", [4, 5, 6])
        # Out-of-order expectation (requesting seq=2 when seq=1 is head of FIFO inbox)
        with self.assertRaises(p09.SimulatedLinkError) as ctx:
            transport.recv_in_order(1, expected_epoch=1, expected_seq=2, op="broadcast_r0")
        self.assertEqual(ctx.exception.code, "ERR_ORDERING_VIOLATION")

    def test_stale_packets_dropped_on_epoch_recovery(self):
        transport = p09.SimulatedTwoDeviceTransport()
        transport.send(0, 1, "allreduce_sum", [10, 20])
        self.assertEqual(len(transport.inboxes[1]), 1)
        new_epoch = transport.recover_clean_epoch()
        self.assertEqual(new_epoch, 2)
        self.assertEqual(len(transport.inboxes[1]), 0)
        self.assertEqual(transport.next_seq, {0: 1, 1: 1})

    def test_unrecovered_transport_blocks_subsequent_send(self):
        transport = p09.SimulatedTwoDeviceTransport()
        with self.assertRaises(p09.SimulatedLinkError) as ctx:
            p09.collective_allreduce_sum(transport, [1, 2], [3, 4], inject_failure="rank_timeout")
        self.assertEqual(ctx.exception.code, "ERR_RANK_TIMEOUT")

        with self.assertRaises(p09.SimulatedLinkError) as ctx2:
            p09.collective_barrier(transport)
        self.assertEqual(ctx2.exception.code, "ERR_TRANSPORT_NOT_READY")


class EvidenceBoundaryTests(unittest.TestCase):
    def test_rejects_fpga_measured_and_non_simulated_claims(self):
        for bad_level in ("fpga_measured", "silicon_measured", "rtl_verified", "source_present"):
            with self.subTest(level=bad_level):
                with self.assertRaises(ValueError):
                    p09.run_train_check(requested_evidence=bad_level)
                with self.assertRaises(ValueError):
                    p09.run_collective_check(requested_evidence=bad_level)

        with self.assertRaises(ValueError):
            p09.run_train_check(physical_fpga_measured=True)
        with self.assertRaises(ValueError):
            p09.run_collective_check(physical_fpga_measured=True)

    def test_validate_receipt_claim_rejects_forged_fields(self):
        valid = p09.run_collective_check(failure_mode="none")
        p09.validate_receipt_claim(valid)

        for field, bad_val in (
            ("evidence_level", "fpga_measured"),
            ("physical_fpga_measured", True),
            ("phase_status_effect", "complete"),
            ("nvlink_or_cuda_parity_claimed", True),
        ):
            with self.subTest(field=field):
                forged = copy.deepcopy(valid)
                forged[field] = bad_val
                with self.assertRaises(ValueError):
                    p09.validate_receipt_claim(forged)

    def test_cli_train_and_collective_and_blocked_claim(self):
        buf_train = io.StringIO()
        with redirect_stdout(buf_train):
            rc = p09.main(["train-check", "--precision", "fp32"])
        self.assertEqual(rc, 0)
        train_json = json.loads(buf_train.getvalue())
        p09.validate_receipt_claim(train_json)
        self.assertEqual(train_json["outcome"], "pass")

        buf_coll = io.StringIO()
        with redirect_stdout(buf_coll):
            rc = p09.main(["collective-check", "--failure-mode", "rank_reset"])
        self.assertEqual(rc, 0)
        coll_json = json.loads(buf_coll.getvalue())
        p09.validate_receipt_claim(coll_json)
        self.assertEqual(coll_json["outcome"], "pass")

        buf_bad = io.StringIO()
        with redirect_stdout(buf_bad):
            rc = p09.main(["collective-check", "--requested-evidence", "fpga_measured"])
        self.assertEqual(rc, 1)
        bad_json = json.loads(buf_bad.getvalue())
        self.assertEqual(bad_json["outcome"], "blocked")
        self.assertFalse(bad_json["physical_fpga_measured"])


if __name__ == "__main__":
    unittest.main()
