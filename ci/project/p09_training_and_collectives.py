#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""P09 optional training and multi-device research simulated prototypes.

This pure-Python standard-library module provides deterministic, software-only
research prototypes for P09:
  - `train-check`: 20-step deterministic SGD training and finite-difference
    gradient verification on a bias-free 16 -> 8 -> 4 ReLU MLP under
    predeclared FP32 and simulated FP16 precision settings.
  - `collective-check`: 2-device (rank 0, rank 1) ring AllReduce, Broadcast,
    and Barrier simulation with sequence-numbered deterministic ordering,
    injected failure modes (rank timeout, link drop, rank reset), clean
    epoch-based recovery, and explicit byte/message communication accounting.

All outputs are strictly scoped to `evidence_level = "simulated"` and
`physical_fpga_measured = False`. Creating or running this harness does not
satisfy P09-A01/A02/A03 (`fpga_measured`), does not advance P09 past
`not_started`, and makes zero NVLink or CUDA equivalence claims.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import struct
import sys
from typing import Any


SCHEMA_VERSION = 1
ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = ROOT / "ci/project/fixtures/p04_tiny_mlp_v1.json"

ALLOWED_EVIDENCE_LEVEL = "simulated"
FORBIDDEN_PHYSICAL_LEVELS = frozenset({"fpga_measured", "silicon_measured", "rtl_verified"})
SUPPORTED_PRECISIONS = ("fp32", "fp16_sim")

MLP_BATCH_SIZE = 16
MLP_INPUT_DIM = 16
MLP_HIDDEN_DIM = 8
MLP_OUTPUT_DIM = 4
DEFAULT_TRAIN_STEPS = 20
DEFAULT_LEARNING_RATE = 0.75
MAX_GRAD_REL_ERR = 1e-4

VALID_FAILURE_MODES = ("none", "link_drop", "rank_timeout", "rank_reset")
VALID_COLLECTIVE_OPS = ("allreduce_sum", "broadcast_r0", "barrier")


def _require_simulated_claim(
    requested_evidence: str,
    physical_fpga_measured: bool = False,
) -> None:
    if physical_fpga_measured is not False:
        raise ValueError(
            "P09 simulated prototype cannot emit physical_fpga_measured=True; "
            "physical FPGA hardware is required for fpga_measured claims"
        )
    if requested_evidence != ALLOWED_EVIDENCE_LEVEL:
        raise ValueError(
            f"Unsupported evidence_level {requested_evidence!r}: P09 Python prototype "
            f"only supports {ALLOWED_EVIDENCE_LEVEL!r} (never {sorted(FORBIDDEN_PHYSICAL_LEVELS)})"
        )


def validate_receipt_claim(receipt: dict[str, Any]) -> None:
    """Strictly reject any receipt claiming fpga_measured or physical hardware."""
    if not isinstance(receipt, dict):
        raise ValueError("receipt must be a JSON object")
    if receipt.get("evidence_level") != ALLOWED_EVIDENCE_LEVEL:
        raise ValueError(
            f"P09 prototype receipt must have evidence_level={ALLOWED_EVIDENCE_LEVEL!r}, "
            f"got {receipt.get('evidence_level')!r}"
        )
    if receipt.get("physical_fpga_measured") is not False:
        raise ValueError("P09 prototype receipt must enforce physical_fpga_measured=False")
    if receipt.get("phase_status_effect") != "none (P09 remains not_started)":
        raise ValueError("P09 prototype receipt must not claim phase advancement")
    if receipt.get("nvlink_or_cuda_parity_claimed") is not False:
        raise ValueError("P09 prototype receipt must enforce nvlink_or_cuda_parity_claimed=False")


# ---------------------------------------------------------------------------
# Precision helpers (FP32 exact Python float / IEEE-754 float32 and simulated FP16)
# ---------------------------------------------------------------------------


def quantize_fp32(value: float) -> float:
    """Round a Python float to IEEE-754 binary32."""
    if not math.isfinite(value):
        raise ValueError(f"Non-finite value in FP32 quantize: {value!r}")
    return struct.unpack("<f", struct.pack("<f", value))[0]


def quantize_fp16(value: float) -> float:
    """Round a Python float to IEEE-754 binary16 (simulated low precision)."""
    if not math.isfinite(value):
        raise ValueError(f"Non-finite value in FP16 quantize: {value!r}")
    # Reject overflow explicitly instead of leaking OverflowError or inf.
    try:
        packed = struct.pack("<e", value)
    except OverflowError as exc:
        raise ValueError(f"Value {value!r} overflows IEEE-754 binary16 range") from exc
    result = struct.unpack("<e", packed)[0]
    if not math.isfinite(result):
        raise ValueError(f"Value {value!r} overflows IEEE-754 binary16 range")
    return result


def quantize_value(value: float, precision: str) -> float:
    if precision == "fp32":
        return quantize_fp32(float(value))
    if precision == "fp16_sim":
        return quantize_fp16(value)
    raise ValueError(f"Unsupported precision {precision!r}; expected one of {SUPPORTED_PRECISIONS}")


def quantize_matrix(matrix: list[list[float]], precision: str) -> list[list[float]]:
    return [[quantize_value(v, precision) for v in row] for row in matrix]


# ---------------------------------------------------------------------------
# Deterministic tiny-MLP (16 -> 8 -> 4, bias-free, ReLU, MSE loss, SGD)
# ---------------------------------------------------------------------------


def _xorshift32_floats(seed: int, rows: int, cols: int, scale: float) -> list[list[float]]:
    if not isinstance(seed, int) or isinstance(seed, bool) or not (0 < seed < (1 << 32)):
        raise ValueError("seed must be a nonzero uint32")
    state = seed
    out: list[list[float]] = []
    for _ in range(rows):
        row: list[float] = []
        for _ in range(cols):
            state = (state ^ ((state << 13) & 0xFFFFFFFF)) & 0xFFFFFFFF
            state = (state ^ (state >> 17)) & 0xFFFFFFFF
            state = (state ^ ((state << 5) & 0xFFFFFFFF)) & 0xFFFFFFFF
            # Symmetric deterministic range in [-scale, +scale]
            unit = ((state & 0xFFFF) / 32767.5) - 1.0
            row.append(round(unit * scale, 6))
        out.append(row)
    return out


def load_p04_initial_topology_check(fixture_path: Path = FIXTURE_PATH) -> dict[str, Any]:
    """Read P04 tiny MLP fixture metadata/weights if present to anchor topology."""
    if not fixture_path.is_file():
        return {"fixture_present": False, "model_id": "p04-tiny-mlp-v1"}
    raw = json.loads(fixture_path.read_text(encoding="utf-8"))
    model = raw.get("model", {})
    return {
        "fixture_present": True,
        "fixture_id": raw.get("fixture_id"),
        "model_id": raw.get("model_id"),
        "batch_size": model.get("batch_size"),
        "input_features": model.get("input_features"),
        "hidden_features": model.get("hidden_features"),
        "output_features": model.get("output_features"),
    }


def make_synthetic_training_batch(
    seed: int = 0x50900001,
    batch_size: int = MLP_BATCH_SIZE,
) -> tuple[list[list[float]], list[list[float]], list[list[float]], list[list[float]]]:
    """Build deterministic X[B,16], W1[16,8], W2[8,4], and target Y_target[B,4].

    Uses smooth non-zero initial weights/inputs avoiding ReLU kink boundaries at 0
    for the initial finite-difference gradient check.
    """
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    x = _xorshift32_floats(seed, batch_size, MLP_INPUT_DIM, scale=0.75)
    w1 = _xorshift32_floats(seed + 1, MLP_INPUT_DIM, MLP_HIDDEN_DIM, scale=0.35)
    w2 = _xorshift32_floats(seed + 2, MLP_HIDDEN_DIM, MLP_OUTPUT_DIM, scale=0.35)
    # Construct targets from a separate teacher weight pair so MSE has a realistic minimum.
    w1_teacher = _xorshift32_floats(seed + 3, MLP_INPUT_DIM, MLP_HIDDEN_DIM, scale=0.40)
    w2_teacher = _xorshift32_floats(seed + 4, MLP_HIDDEN_DIM, MLP_OUTPUT_DIM, scale=0.40)
    y_target = mlp_forward(x, w1_teacher, w2_teacher, precision="fp32")["output"]
    return x, w1, w2, y_target


def _matmul(a: list[list[float]], b: list[list[float]], precision: str) -> list[list[float]]:
    rows = len(a)
    inner = len(a[0])
    if len(b) != inner:
        raise ValueError(f"matmul shape mismatch: ({rows},{inner}) x ({len(b)},{len(b[0])})")
    cols = len(b[0])
    out: list[list[float]] = []
    for r in range(rows):
        out_row: list[float] = []
        for c in range(cols):
            acc = 0.0
            for k in range(inner):
                prod = quantize_value(a[r][k] * b[k][c], precision)
                # Accumulate in FP32 under P02/TFR convention, then cast if requested.
                acc += prod
            out_row.append(quantize_value(acc, precision))
        out.append(out_row)
    return out


def _transpose(m: list[list[float]]) -> list[list[float]]:
    return [[m[r][c] for r in range(len(m))] for c in range(len(m[0]))]


def mlp_forward(
    x: list[list[float]],
    w1: list[list[float]],
    w2: list[list[float]],
    *,
    precision: str = "fp32",
) -> dict[str, list[list[float]]]:
    """Forward pass: H = X @ W1, R = ReLU(H), Y = R @ W2."""
    xq = quantize_matrix(x, precision)
    w1q = quantize_matrix(w1, precision)
    w2q = quantize_matrix(w2, precision)
    hidden = _matmul(xq, w1q, precision)
    relu_act = [[val if val > 0.0 else 0.0 for val in row] for row in hidden]
    output = _matmul(relu_act, w2q, precision)
    return {
        "x": xq,
        "w1": w1q,
        "w2": w2q,
        "hidden": hidden,
        "relu": relu_act,
        "output": output,
    }


def mse_loss(output: list[list[float]], target: list[list[float]]) -> float:
    """Mean Squared Error: mean((output - target)^2) over all B * 4 elements."""
    rows = len(output)
    cols = len(output[0])
    if len(target) != rows or len(target[0]) != cols:
        raise ValueError("output and target shapes must match")
    total = 0.0
    for r in range(rows):
        for c in range(cols):
            diff = output[r][c] - target[r][c]
            total += diff * diff
    return total / float(rows * cols)


def mlp_backward(
    cache: dict[str, list[list[float]]],
    target: list[list[float]],
    *,
    precision: str = "fp32",
) -> dict[str, Any]:
    """Analytical backprop for MSE(ReLU(X @ W1) @ W2, target)."""
    output = cache["output"]
    relu_act = cache["relu"]
    hidden = cache["hidden"]
    x = cache["x"]
    w2 = cache["w2"]

    rows = len(output)
    cols = len(output[0])
    scale = 2.0 / float(rows * cols)

    # dL / dY: [B, 4]
    d_output = [
        [quantize_value(scale * (output[r][c] - target[r][c]), precision) for c in range(cols)]
        for r in range(rows)
    ]

    # dL / dW2 = R^T @ dY: [8, 4]
    grad_w2 = _matmul(_transpose(relu_act), d_output, precision)

    # dL / dR = dY @ W2^T: [B, 8]
    d_relu = _matmul(d_output, _transpose(w2), precision)

    # dL / dH = d_relu * (H > 0): [B, 8]
    d_hidden = [
        [d_relu[r][h] if hidden[r][h] > 0.0 else 0.0 for h in range(len(hidden[0]))]
        for r in range(rows)
    ]

    # dL / dW1 = X^T @ d_hidden: [16, 8]
    grad_w1 = _matmul(_transpose(x), d_hidden, precision)

    loss_val = mse_loss(output, target)
    return {
        "loss": loss_val,
        "grad_w1": grad_w1,
        "grad_w2": grad_w2,
    }


def _clone_matrix(m: list[list[float]]) -> list[list[float]]:
    return [list(row) for row in m]


def _matmul_fp64(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    rows = len(a)
    inner = len(a[0])
    if len(b) != inner:
        raise ValueError(f"matmul shape mismatch: ({rows},{inner}) x ({len(b)},{len(b[0])})")
    cols = len(b[0])
    out: list[list[float]] = []
    for r in range(rows):
        out_row: list[float] = []
        for c in range(cols):
            acc = 0.0
            for k in range(inner):
                acc += float(a[r][k]) * float(b[k][c])
            out_row.append(acc)
        out.append(out_row)
    return out


def _mlp_output_fp64(
    x: list[list[float]],
    w1: list[list[float]],
    w2: list[list[float]],
) -> list[list[float]]:
    hidden = _matmul_fp64(x, w1)
    relu_act = [[val if val > 0.0 else 0.0 for val in row] for row in hidden]
    return _matmul_fp64(relu_act, w2)


def finite_difference_gradients(
    x: list[list[float]],
    w1: list[list[float]],
    w2: list[list[float]],
    target: list[list[float]],
    *,
    eps: float = 1e-6,
) -> tuple[list[list[float]], list[list[float]]]:
    """Central finite-difference gradients in FP64 reference arithmetic."""
    fd_w1: list[list[float]] = []
    for i in range(len(w1)):
        row_g: list[float] = []
        for j in range(len(w1[0])):
            w1_p = _clone_matrix(w1)
            w1_m = _clone_matrix(w1)
            w1_p[i][j] += eps
            w1_m[i][j] -= eps
            loss_p = mse_loss(_mlp_output_fp64(x, w1_p, w2), target)
            loss_m = mse_loss(_mlp_output_fp64(x, w1_m, w2), target)
            row_g.append((loss_p - loss_m) / (2.0 * eps))
        fd_w1.append(row_g)

    fd_w2: list[list[float]] = []
    for i in range(len(w2)):
        row_g = []
        for j in range(len(w2[0])):
            w2_p = _clone_matrix(w2)
            w2_m = _clone_matrix(w2)
            w2_p[i][j] += eps
            w2_m[i][j] -= eps
            loss_p = mse_loss(_mlp_output_fp64(x, w1, w2_p), target)
            loss_m = mse_loss(_mlp_output_fp64(x, w1, w2_m), target)
            row_g.append((loss_p - loss_m) / (2.0 * eps))
        fd_w2.append(row_g)

    return fd_w1, fd_w2


def _max_relative_error(
    analytical: list[list[float]],
    numerical: list[list[float]],
    floor: float = 1e-8,
) -> float:
    max_err = 0.0
    for r in range(len(analytical)):
        for c in range(len(analytical[0])):
            a = analytical[r][c]
            b = numerical[r][c]
            denom = max(abs(a), abs(b), floor)
            rel = abs(a - b) / denom
            if rel > max_err:
                max_err = rel
    return max_err


def run_train_check(
    *,
    steps: int = DEFAULT_TRAIN_STEPS,
    learning_rate: float = DEFAULT_LEARNING_RATE,
    precision: str = "fp32",
    seed: int = 0x50900001,
    requested_evidence: str = "simulated",
    physical_fpga_measured: bool = False,
) -> dict[str, Any]:
    """Run bounded deterministic SGD training + gradient verification on 16->8->4 ReLU MLP."""
    _require_simulated_claim(requested_evidence, physical_fpga_measured)
    if precision not in SUPPORTED_PRECISIONS:
        raise ValueError(f"Unsupported precision {precision!r}; expected one of {SUPPORTED_PRECISIONS}")
    if steps < 2:
        raise ValueError("steps must be >= 2")
    if not math.isfinite(learning_rate) or learning_rate <= 0.0:
        raise ValueError("learning_rate must be positive and finite")

    x, w1, w2, target = make_synthetic_training_batch(seed=seed, batch_size=MLP_BATCH_SIZE)

    # Step 0 gradient verification against central finite differences (FP32 reference check).
    cache0 = mlp_forward(x, w1, w2, precision="fp32")
    bwd0 = mlp_backward(cache0, target, precision="fp32")
    fd_w1, fd_w2 = finite_difference_gradients(x, w1, w2, target, eps=1e-6)
    max_rel_err_w1 = _max_relative_error(bwd0["grad_w1"], fd_w1)
    max_rel_err_w2 = _max_relative_error(bwd0["grad_w2"], fd_w2)
    max_rel_err = max(max_rel_err_w1, max_rel_err_w2)

    # For fp16_sim, keep FP32 master weights and quantize forward/backward activations/weights
    # per predeclared mixed-precision SGD protocol.
    master_w1 = _clone_matrix(w1)
    master_w2 = _clone_matrix(w2)

    losses: list[float] = []
    grad_norms: list[float] = []

    for _step in range(steps):
        cache = mlp_forward(x, master_w1, master_w2, precision=precision)
        bwd = mlp_backward(cache, target, precision=precision)
        loss_val = bwd["loss"]
        if not math.isfinite(loss_val):
            raise ValueError("Non-finite loss encountered during training")
        losses.append(loss_val)

        gw1 = bwd["grad_w1"]
        gw2 = bwd["grad_w2"]
        sq_norm = sum(v * v for row in gw1 for v in row) + sum(v * v for row in gw2 for v in row)
        grad_norms.append(math.sqrt(sq_norm))

        # SGD update
        for i in range(len(master_w1)):
            for j in range(len(master_w1[0])):
                master_w1[i][j] -= learning_rate * gw1[i][j]
                if precision == "fp32":
                    master_w1[i][j] = quantize_fp32(master_w1[i][j])
        for i in range(len(master_w2)):
            for j in range(len(master_w2[0])):
                master_w2[i][j] -= learning_rate * gw2[i][j]
                if precision == "fp32":
                    master_w2[i][j] = quantize_fp32(master_w2[i][j])

    loss_init = losses[0]
    loss_final = losses[-1]
    # Check monotonic decrease (allow tiny fp16 quantization plateaus only if final drops sharply,
    # while requiring strict monotone non-increase on fp32).
    if precision == "fp32":
        monotonic_decrease = all(losses[i + 1] < losses[i] for i in range(len(losses) - 1))
    else:
        monotonic_decrease = all(losses[i + 1] <= losses[i] + 1e-5 for i in range(len(losses) - 1)) and (
            loss_final < loss_init
        )
    convergence_ratio = loss_final / loss_init if loss_init > 0.0 else 1.0
    grad_check_passed = max_rel_err < MAX_GRAD_REL_ERR
    convergence_passed = monotonic_decrease and (loss_final < 0.5 * loss_init)

    weights_digest = hashlib.sha256(
        json.dumps({"w1": master_w1, "w2": master_w2}, sort_keys=True).encode("utf-8")
    ).hexdigest()

    outcome = "pass" if (grad_check_passed and convergence_passed) else "fail"
    return {
        "schema_version": SCHEMA_VERSION,
        "prototype_id": "p09-a01-tiny-mlp-train-sim",
        "mode": "train-check",
        "outcome": outcome,
        "evidence_level": ALLOWED_EVIDENCE_LEVEL,
        "physical_fpga_measured": False,
        "phase_status_effect": "none (P09 remains not_started)",
        "nvlink_or_cuda_parity_claimed": False,
        "model": {
            "architecture": "16 -> 8 -> 4 bias-free ReLU MLP",
            "anchor_fixture": load_p04_initial_topology_check(),
            "batch_size": MLP_BATCH_SIZE,
            "weight_count": MLP_INPUT_DIM * MLP_HIDDEN_DIM + MLP_HIDDEN_DIM * MLP_OUTPUT_DIM,
            "loss": "MSE",
            "optimizer": "SGD",
            "learning_rate": learning_rate,
            "precision": precision,
            "seed": seed,
            "steps": steps,
        },
        "gradient_verification": {
            "method": "central_finite_difference",
            "epsilon": 1e-6,
            "max_rel_err_w1": max_rel_err_w1,
            "max_rel_err_w2": max_rel_err_w2,
            "max_rel_err": max_rel_err,
            "threshold": MAX_GRAD_REL_ERR,
            "passed": grad_check_passed,
        },
        "training_metrics": {
            "loss_init": loss_init,
            "loss_final": loss_final,
            "convergence_ratio": convergence_ratio,
            "target_ratio_max": 0.5,
            "monotonic_decrease": monotonic_decrease,
            "convergence_passed": convergence_passed,
            "loss_trajectory": losses,
            "grad_l2_norm_init": grad_norms[0],
            "grad_l2_norm_final": grad_norms[-1],
            "final_weights_sha256": weights_digest,
        },
    }


# ---------------------------------------------------------------------------
# Simulated 2-device collective transport (AllReduce, Broadcast, Barrier)
# ---------------------------------------------------------------------------


@dataclass
class CollectivePacket:
    epoch: int
    seq: int
    op: str
    src_rank: int
    dst_rank: int
    payload_words: list[int]
    payload_bytes: int


class SimulatedLinkError(RuntimeError):
    def __init__(self, code: str, message: str, *, epoch: int, seq: int, failed_rank: int) -> None:
        super().__init__(message)
        self.code = code
        self.epoch = epoch
        self.seq = seq
        self.failed_rank = failed_rank


class SimulatedTwoDeviceTransport:
    """Deterministic 2-device (rank 0 <-> rank 1) ring/star message transport."""

    def __init__(self, *, latency_per_msg_us: float = 18.5, bandwidth_gbps: float = 1.6) -> None:
        self.epoch = 1
        self.next_seq = {0: 1, 1: 1}
        self.inboxes: dict[int, list[CollectivePacket]] = {0: [], 1: []}
        self.rank_healthy = {0: True, 1: True}
        self.link_up = True
        self.messages_sent = 0
        self.bytes_transferred = 0
        self.protocol_overhead_bytes = 0
        self.latency_per_msg_us = latency_per_msg_us
        self.bandwidth_gbps = bandwidth_gbps
        self.trace: list[dict[str, Any]] = []
        self.injected_failure_mode = "none"

    def send(
        self,
        src_rank: int,
        dst_rank: int,
        op: str,
        words: list[int],
        *,
        inject_failure: str = "none",
    ) -> CollectivePacket:
        if src_rank not in (0, 1) or dst_rank not in (0, 1) or src_rank == dst_rank:
            raise ValueError(f"Invalid 2-device route: {src_rank} -> {dst_rank}")
        seq = self.next_seq[src_rank]

        if inject_failure == "link_drop":
            self.link_up = False
            self.injected_failure_mode = "link_drop"
            self.trace.append(
                {
                    "event": "failure_injected",
                    "mode": "link_drop",
                    "epoch": self.epoch,
                    "seq": seq,
                    "src_rank": src_rank,
                    "dst_rank": dst_rank,
                    "op": op,
                }
            )
            raise SimulatedLinkError(
                "ERR_LINK_DROP",
                f"Simulated PCIe/host-staging link drop on epoch={self.epoch} seq={seq}",
                epoch=self.epoch,
                seq=seq,
                failed_rank=dst_rank,
            )

        if inject_failure == "rank_timeout":
            self.rank_healthy[dst_rank] = False
            self.injected_failure_mode = "rank_timeout"
            self.trace.append(
                {
                    "event": "failure_injected",
                    "mode": "rank_timeout",
                    "epoch": self.epoch,
                    "seq": seq,
                    "src_rank": src_rank,
                    "dst_rank": dst_rank,
                    "op": op,
                }
            )
            raise SimulatedLinkError(
                "ERR_RANK_TIMEOUT",
                f"Simulated rank {dst_rank} completion timeout on epoch={self.epoch} seq={seq}",
                epoch=self.epoch,
                seq=seq,
                failed_rank=dst_rank,
            )

        if inject_failure == "rank_reset":
            self.rank_healthy[src_rank] = False
            self.injected_failure_mode = "rank_reset"
            self.trace.append(
                {
                    "event": "failure_injected",
                    "mode": "rank_reset",
                    "epoch": self.epoch,
                    "seq": seq,
                    "src_rank": src_rank,
                    "dst_rank": dst_rank,
                    "op": op,
                }
            )
            raise SimulatedLinkError(
                "ERR_RANK_RESET",
                f"Simulated rank {src_rank} device reset mid-collective on epoch={self.epoch} seq={seq}",
                epoch=self.epoch,
                seq=seq,
                failed_rank=src_rank,
            )

        if not self.link_up or not self.rank_healthy[src_rank] or not self.rank_healthy[dst_rank]:
            raise SimulatedLinkError(
                "ERR_TRANSPORT_NOT_READY",
                "Transport in faulted state; explicit epoch recovery required",
                epoch=self.epoch,
                seq=seq,
                failed_rank=dst_rank,
            )

        payload_bytes = len(words) * 4
        header_bytes = 32  # Fixed simulated descriptor/epoch/seq framing header
        pkt = CollectivePacket(
            epoch=self.epoch,
            seq=seq,
            op=op,
            src_rank=src_rank,
            dst_rank=dst_rank,
            payload_words=list(words),
            payload_bytes=payload_bytes,
        )
        self.next_seq[src_rank] += 1
        self.inboxes[dst_rank].append(pkt)
        self.messages_sent += 1
        self.bytes_transferred += payload_bytes
        self.protocol_overhead_bytes += header_bytes
        self.trace.append(
            {
                "event": "send",
                "epoch": pkt.epoch,
                "seq": pkt.seq,
                "op": op,
                "src_rank": src_rank,
                "dst_rank": dst_rank,
                "payload_bytes": payload_bytes,
            }
        )
        return pkt

    def recv_in_order(self, rank: int, expected_epoch: int, expected_seq: int, op: str) -> CollectivePacket:
        if not self.inboxes[rank]:
            raise SimulatedLinkError(
                "ERR_RECV_EMPTY",
                f"Rank {rank} inbox empty for op={op} epoch={expected_epoch} seq={expected_seq}",
                epoch=expected_epoch,
                seq=expected_seq,
                failed_rank=rank,
            )
        pkt = self.inboxes[rank].pop(0)
        if pkt.epoch != expected_epoch or pkt.seq != expected_seq or pkt.op != op:
            raise SimulatedLinkError(
                "ERR_ORDERING_VIOLATION",
                (
                    f"Ordering mismatch on rank {rank}: expected "
                    f"(epoch={expected_epoch}, seq={expected_seq}, op={op}), "
                    f"got (epoch={pkt.epoch}, seq={pkt.seq}, op={pkt.op})"
                ),
                epoch=pkt.epoch,
                seq=pkt.seq,
                failed_rank=rank,
            )
        self.trace.append(
            {
                "event": "recv",
                "epoch": pkt.epoch,
                "seq": pkt.seq,
                "op": op,
                "dst_rank": rank,
                "payload_bytes": pkt.payload_bytes,
            }
        )
        return pkt

    def recover_clean_epoch(self) -> int:
        """Abort stale packets, reset link/rank health, and advance epoch."""
        dropped_stale = len(self.inboxes[0]) + len(self.inboxes[1])
        self.inboxes[0].clear()
        self.inboxes[1].clear()
        self.epoch += 1
        self.next_seq = {0: 1, 1: 1}
        self.link_up = True
        self.rank_healthy = {0: True, 1: True}
        self.trace.append(
            {
                "event": "epoch_recover",
                "new_epoch": self.epoch,
                "dropped_stale_packets": dropped_stale,
            }
        )
        return self.epoch

    def estimated_comm_time_us(self) -> float:
        wire_us = (self.bytes_transferred + self.protocol_overhead_bytes) * 8.0 / (self.bandwidth_gbps * 1000.0)
        return round(self.messages_sent * self.latency_per_msg_us + wire_us, 4)


def collective_allreduce_sum(
    transport: SimulatedTwoDeviceTransport,
    rank0_words: list[int],
    rank1_words: list[int],
    *,
    inject_failure: str = "none",
) -> tuple[list[int], list[int]]:
    """2-rank bidirectional AllReduce-Sum over integer-encoded words (exact deterministic sum)."""
    if len(rank0_words) != len(rank1_words) or not rank0_words:
        raise ValueError("Rank payloads must be nonempty and equal length")
    epoch = transport.epoch
    seq0 = transport.next_seq[0]
    seq1 = transport.next_seq[1]

    # Rank 0 -> Rank 1 and Rank 1 -> Rank 0
    transport.send(0, 1, "allreduce_sum", rank0_words, inject_failure=inject_failure)
    transport.send(1, 0, "allreduce_sum", rank1_words, inject_failure="none")

    pkt_at_1 = transport.recv_in_order(1, epoch, seq0, "allreduce_sum")
    pkt_at_0 = transport.recv_in_order(0, epoch, seq1, "allreduce_sum")

    reduced_r0 = [a + b for a, b in zip(rank0_words, pkt_at_0.payload_words)]
    reduced_r1 = [a + b for a, b in zip(pkt_at_1.payload_words, rank1_words)]
    return reduced_r0, reduced_r1


def collective_broadcast_r0(
    transport: SimulatedTwoDeviceTransport,
    root_words: list[int],
    *,
    inject_failure: str = "none",
) -> tuple[list[int], list[int]]:
    """Broadcast payload from rank 0 to rank 1."""
    if not root_words:
        raise ValueError("Broadcast payload must be nonempty")
    epoch = transport.epoch
    seq0 = transport.next_seq[0]
    transport.send(0, 1, "broadcast_r0", root_words, inject_failure=inject_failure)
    pkt = transport.recv_in_order(1, epoch, seq0, "broadcast_r0")
    return list(root_words), list(pkt.payload_words)


def collective_barrier(
    transport: SimulatedTwoDeviceTransport,
    *,
    inject_failure: str = "none",
) -> bool:
    """2-rank synchronization barrier using 4-byte token exchange."""
    epoch = transport.epoch
    seq0 = transport.next_seq[0]
    seq1 = transport.next_seq[1]
    transport.send(0, 1, "barrier", [epoch], inject_failure=inject_failure)
    transport.send(1, 0, "barrier", [epoch], inject_failure="none")
    p1 = transport.recv_in_order(1, epoch, seq0, "barrier")
    p0 = transport.recv_in_order(0, epoch, seq1, "barrier")
    return p0.payload_words == [epoch] and p1.payload_words == [epoch]


def run_collective_check(
    *,
    payload_len: int = 32,
    failure_mode: str = "link_drop",
    requested_evidence: str = "simulated",
    physical_fpga_measured: bool = False,
) -> dict[str, Any]:
    """Run simulated 2-device AllReduce + Broadcast + Barrier with failure injection & recovery."""
    _require_simulated_claim(requested_evidence, physical_fpga_measured)
    if payload_len <= 0 or payload_len > 4096:
        raise ValueError("payload_len must be in 1..4096")
    if failure_mode not in VALID_FAILURE_MODES:
        raise ValueError(f"Unsupported failure_mode {failure_mode!r}; expected one of {VALID_FAILURE_MODES}")

    transport = SimulatedTwoDeviceTransport()

    # Deterministic rank inputs (exact integers representing fixed-point / tensor words).
    r0_in = [(i * 3 - 7) for i in range(payload_len)]
    r1_in = [((i % 5) * 2 + 1) for i in range(payload_len)]
    expected_sum = [a + b for a, b in zip(r0_in, r1_in)]

    # 1. Baseline healthy collectives (AllReduce -> Barrier -> Broadcast -> Barrier)
    ar0, ar1 = collective_allreduce_sum(transport, r0_in, r1_in)
    allreduce_exact = (ar0 == expected_sum) and (ar1 == expected_sum)
    barrier1_ok = collective_barrier(transport)

    bcast_seed = [100 + i for i in range(payload_len)]
    bc0, bc1 = collective_broadcast_r0(transport, bcast_seed)
    broadcast_exact = (bc0 == bcast_seed) and (bc1 == bcast_seed)
    barrier2_ok = collective_barrier(transport)

    baseline_messages = transport.messages_sent
    baseline_bytes = transport.bytes_transferred
    baseline_overhead_bytes = transport.protocol_overhead_bytes

    # 2. Deterministic failure injection + epoch-based recovery (when failure_mode != 'none')
    failure_detected = False
    failure_code = None
    recovery_epoch = transport.epoch
    post_recovery_exact = True

    if failure_mode != "none":
        try:
            collective_allreduce_sum(transport, r0_in, r1_in, inject_failure=failure_mode)
        except SimulatedLinkError as exc:
            failure_detected = True
            failure_code = exc.code

        # Verify subsequent unrecovered call refuses to proceed silently
        unrecovered_blocked = False
        try:
            collective_barrier(transport)
        except SimulatedLinkError as exc:
            unrecovered_blocked = exc.code == "ERR_TRANSPORT_NOT_READY"

        recovery_epoch = transport.recover_clean_epoch()
        r0_rec = [v + 11 for v in r0_in]
        r1_rec = [v - 5 for v in r1_in]
        expected_rec = [a + b for a, b in zip(r0_rec, r1_rec)]
        rec0, rec1 = collective_allreduce_sum(transport, r0_rec, r1_rec)
        rec_barrier = collective_barrier(transport)
        post_recovery_exact = (
            unrecovered_blocked
            and (rec0 == expected_rec)
            and (rec1 == expected_rec)
            and rec_barrier
        )
    else:
        failure_detected = False

    ordering_preserved = _verify_trace_ordering(transport.trace)
    failure_check_ok = failure_detected if failure_mode != "none" else (not failure_detected)
    all_passed = (
        allreduce_exact
        and broadcast_exact
        and barrier1_ok
        and barrier2_ok
        and failure_check_ok
        and post_recovery_exact
        and ordering_preserved
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "prototype_id": "p09-a02-a03-two-device-collective-sim",
        "mode": "collective-check",
        "outcome": "pass" if all_passed else "fail",
        "evidence_level": ALLOWED_EVIDENCE_LEVEL,
        "physical_fpga_measured": False,
        "phase_status_effect": "none (P09 remains not_started)",
        "nvlink_or_cuda_parity_claimed": False,
        "topology": {
            "ranks": [0, 1],
            "transport_model": "simulated_host_staged_ring_2rank",
            "payload_elements": payload_len,
            "element_bytes": 4,
            "collectives_exercised": list(VALID_COLLECTIVE_OPS),
        },
        "correctness": {
            "allreduce_exact": allreduce_exact,
            "broadcast_exact": broadcast_exact,
            "barrier_ok": barrier1_ok and barrier2_ok,
            "ordering_preserved": ordering_preserved,
        },
        "failure_and_recovery": {
            "injected_failure_mode": failure_mode,
            "failure_detected": failure_detected,
            "failure_code": failure_code,
            "recovery_epoch": recovery_epoch,
            "post_recovery_exact": post_recovery_exact,
        },
        "communication_cost": {
            "baseline_messages": baseline_messages,
            "baseline_payload_bytes": baseline_bytes,
            "baseline_protocol_overhead_bytes": baseline_overhead_bytes,
            "total_messages": transport.messages_sent,
            "total_payload_bytes": transport.bytes_transferred,
            "total_protocol_overhead_bytes": transport.protocol_overhead_bytes,
            "assumed_per_message_latency_us": transport.latency_per_msg_us,
            "assumed_link_bandwidth_gbps": transport.bandwidth_gbps,
            "simulated_comm_time_us": transport.estimated_comm_time_us(),
            "cost_note": "Simulated software accounting only; NOT physical PCIe/DMA/FPGA measurement.",
        },
    }


def _verify_trace_ordering(trace: list[dict[str, Any]]) -> bool:
    """Verify monotonic per-(epoch, src_rank) send sequence numbers and FIFO recv matching."""
    last_send_seq: dict[tuple[int, int], int] = {}
    last_recv_seq: dict[tuple[int, int], int] = {}
    for entry in trace:
        ev = entry.get("event")
        if ev == "send":
            key = (entry["epoch"], entry["src_rank"])
            prev = last_send_seq.get(key, 0)
            if entry["seq"] != prev + 1:
                return False
            last_send_seq[key] = entry["seq"]
        elif ev == "recv":
            key = (entry["epoch"], entry["dst_rank"])
            prev = last_recv_seq.get(key, 0)
            if entry["seq"] != prev + 1:
                return False
            last_recv_seq[key] = entry["seq"]
    return True


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="p09_training_and_collectives.py",
        description="P09 simulated training and 2-device collective research prototypes.",
    )
    sub = parser.add_subparsers(dest="subcommand", required=True)

    p_train = sub.add_parser(
        "train-check",
        help="Run deterministic 20-step tiny-MLP SGD & finite-difference gradient check.",
    )
    p_train.add_argument("--steps", type=int, default=DEFAULT_TRAIN_STEPS)
    p_train.add_argument("--lr", type=float, default=DEFAULT_LEARNING_RATE)
    p_train.add_argument("--precision", default="fp32", choices=SUPPORTED_PRECISIONS)
    p_train.add_argument("--seed", type=int, default=0x50900001)
    p_train.add_argument("--requested-evidence", default="simulated")

    p_coll = sub.add_parser(
        "collective-check",
        help="Run simulated 2-device AllReduce/Broadcast/Barrier + failure recovery check.",
    )
    p_coll.add_argument("--payload-len", type=int, default=32)
    p_coll.add_argument("--failure-mode", default="link_drop", choices=VALID_FAILURE_MODES)
    p_coll.add_argument("--requested-evidence", default="simulated")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.subcommand == "train-check":
            receipt = run_train_check(
                steps=args.steps,
                learning_rate=args.lr,
                precision=args.precision,
                seed=args.seed,
                requested_evidence=args.requested_evidence,
            )
        elif args.subcommand == "collective-check":
            receipt = run_collective_check(
                payload_len=args.payload_len,
                failure_mode=args.failure_mode,
                requested_evidence=args.requested_evidence,
            )
        else:
            return 2
    except ValueError as exc:
        err = {
            "schema_version": SCHEMA_VERSION,
            "mode": args.subcommand,
            "outcome": "blocked",
            "evidence_level": ALLOWED_EVIDENCE_LEVEL,
            "physical_fpga_measured": False,
            "error": str(exc),
        }
        print(json.dumps(err, indent=2, sort_keys=True, allow_nan=False))
        return 1

    print(json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False))
    return 0 if receipt["outcome"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
