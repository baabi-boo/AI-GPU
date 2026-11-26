# P09 Optional Research Prototypes — Training & Multi-Device Simulation

> [!IMPORTANT]
> **Phase status: `not_started`** in [roadmap.json](roadmap.json).
> This document and its companion simulator [ci/project/p09_training_and_collectives.py](../../ci/project/p09_training_and_collectives.py)
> are **preparatory, software-simulated research prototypes (`simulated` / `source_present`) only**.
> - **P09 is optional** and is **not** a prerequisite for [P10](phases/p10-asic.md) or [P11](phases/p11-silicon.md) (per [ADR-003](decisions.md#adr-003--physical-fpga-proof-before-funded-asic-realization)).
> - **P09 remains `not_started`** until [P08](phases/p08-reliability.md) closes and actual physical FPGA multi-device runs (`fpga_measured`) are executed and independently reviewed.
> - **Zero NVLink or CUDA equivalence claims** are made or implied.

---

## 1. Scope and evidence boundary

Under [the P09 phase specification](phases/p09-research.md) and [the acceptance policy](acceptance.md),
gates `P09-A01`, `P09-A02`, and `P09-A03` require `fpga_measured` proof on identified
physical hardware. Pure-Python / software simulation models can validate mathematical
derivations, ordering state machines, failure-recovery invariants, and communication
cost accounting prior to hardware availability, **but they cannot satisfy `fpga_measured` gates**.

| Prototype capability | Companion CLI subcommand | Allowed evidence label | What it does NOT establish |
|---|---|---|---|
| Tiny-MLP forward/backward gradient check & 20-step SGD loop | `train-check` | `simulated` | Native tensor RTL backprop, physical FPGA speed, or frontier-model training |
| 2-device ring/star collective ordering, failure injection, & cost model | `collective-check` | `simulated` | Physical multi-FPGA DMA/PCIe throughput, NVLink parity, or CUDA compatibility |

Any attempt to emit or validate a receipt with `evidence_level="fpga_measured"`,
`physical_fpga_measured=True`, or `nvlink_or_cuda_parity_claimed=True` from this
prototype is strictly rejected by `validate_receipt_claim` and the CLI harness.

---

## 2. P09-A01 Simulated Training & Gradient Verification Protocol

### 2.1 Architecture and frozen workload

The training prototype extends the [fixed tiny MLP v1](../designs/tiny_mlp_fixture_v1.md)
topology (`16 -> 8 -> 4`, bias-free, ReLU hidden activation, batch size `16`, `160` trainable weights):

- Forward equations:
  $$H = X W_1, \quad R = \max(H, 0), \quad \hat{Y} = R W_2$$
- Loss function: Mean Squared Error (MSE) over all $B \times 4 = 64$ output elements:
  $$\mathcal{L}(\hat{Y}, Y^*) = \frac{1}{64} \sum_{i=0}^{15} \sum_{j=0}^{3} (\hat{Y}_{i,j} - Y^*_{i,j})^2$$
- Optimizer: Deterministic vanilla SGD (`learning_rate = 0.75`, `steps = 20`, no momentum, no weight decay).
- Synthetic data provenance: Deterministic `xorshift32` streams (`seed = 0x50900001`), requiring no external datasets or pretrained weights.

### 2.2 Predeclared precision settings

Two precision modes are defined prior to execution:

1. **`fp32`**: IEEE-754 binary32 weight storage and intermediate matmul/gradient quantization (`quantize_value(..., "fp32")` -> `quantize_fp32`), with FP32 accumulation (while step-0 central finite differences use FP64 reference arithmetic so `eps=1e-6` perturbations are not rounded away).
2. **`fp16_sim`**: Simulated IEEE-754 binary16 quantization (`struct.pack("<e", ...)` / `quantize_fp16`) applied to inputs, weights, activations, and backward gradients, paired with FP32 accumulation and FP32 master weights for the SGD update step.

### 2.3 Analytical vs. finite-difference gradient check and convergence criteria

1. **Gradient check (Step 0):** Analytical gradients $\nabla_{W_1}\mathcal{L}$ and $\nabla_{W_2}\mathcal{L}$ are compared elementwise against central finite differences ($\varepsilon = 10^{-6}$ in FP64 reference arithmetic). Passing requires:
   $$\max_{p} \frac{|g^{\text{analytical}}_p - g^{\text{numerical}}_p|}{\max(|g^{\text{analytical}}_p|, |g^{\text{numerical}}_p|, 10^{-8})} < 10^{-4}$$
2. **Convergence check (20 SGD steps):**
   - Loss must decrease monotonically across all 20 steps ($\mathcal{L}_{t+1} < \mathcal{L}_t$ for `fp32`; $\mathcal{L}_{t+1} \le \mathcal{L}_t + 10^{-5}$ with $\mathcal{L}_{19} < \mathcal{L}_0$ for `fp16_sim` quantization rounding).
   - Final loss must satisfy $\mathcal{L}_{\text{final}} < 0.5 \cdot \mathcal{L}_{\text{init}}$.
   - All losses and gradients must remain finite (`math.isfinite`).

---

## 3. P09-A02 / P09-A03 Simulated 2-Device Collective & Cost Protocol

### 3.1 Declared 2-device topology and collective primitives

The simulated transport models two cooperating accelerator ranks (`rank 0` and `rank 1`)
connected via a host-staged bidirectional message channel (`SimulatedTwoDeviceTransport`).
No hardware peer-to-peer DMA, NVLink fabric, or CUDA/NCCL ABI is assumed or claimed.

Three foundational collectives are simulated over exact integer-encoded 32-bit word payloads:

| Collective | Communication pattern | Ordering invariant |
|---|---|---|
| `allreduce_sum` | Bidirectional exchange (`0 -> 1` and `1 -> 0`) followed by elementwise sum | Per-`(epoch, src_rank)` monotonic sequence numbers (`seq = 1, 2, ...`); FIFO inbox matching `(epoch, seq, op)` |
| `broadcast_r0` | Directed root-to-peer transfer (`0 -> 1`) | Sequence-checked delivery matching active `epoch` and `seq` |
| `barrier` | Bidirectional 4-byte epoch token exchange (`0 <-> 1`) | Both ranks observe matching active `epoch` token before proceeding |

### 3.2 Deterministic failure injection and epoch-based recovery

To mirror physical reliability requirements before multi-board hardware bring-up,
the transport supports deterministic fault injection across four modes:

0. **`none`**: Baseline healthy collectives only; `failure_detected` is reported as `False` (`failure_code: null`) and `recovery_epoch` remains `1`.
1. **`link_drop`**: Drops the active link mid-collective (`ERR_LINK_DROP`).
2. **`rank_timeout`**: Marks destination rank unresponsive (`ERR_RANK_TIMEOUT`).
3. **`rank_reset`**: Simulates unexpected source rank reset mid-transfer (`ERR_RANK_RESET`).

**Recovery invariants:**
- Once a fault occurs, any subsequent collective call **must fail explicitly** with `ERR_TRANSPORT_NOT_READY` rather than silently succeeding or returning stale data.
- Recovery requires invoking `recover_clean_epoch()`, which flushes stale in-flight inbox packets, increments the global `epoch` counter, resets per-rank sequence counters to `1`, and restores rank/link health.
- Post-recovery `allreduce_sum` and `barrier` must execute in the new epoch and match exact expected sums.

### 3.3 Explicit communication-cost accounting model

Every simulated send accounts explicitly for:
- `messages_sent`: Total point-to-point transport messages issued (baseline and total including post-recovery).
- `payload_bytes`: `len(words) * 4` bytes of tensor payload transferred.
- `protocol_overhead_bytes`: Fixed `32` bytes per message for framing (`epoch`, `seq`, `op`, ranks).
- `simulated_comm_time_us`: Deterministic analytical accounting model:
  $$T_{\text{comm, sim}} = N_{\text{msg}} \cdot L_{\text{msg}} + \frac{(B_{\text{payload}} + B_{\text{overhead}}) \cdot 8}{\text{BW}_{\text{Gbps}} \cdot 1000}$$
  with declared defaults $L_{\text{msg}} = 18.5\,\mu\text{s}$ and $\text{BW} = 1.6\,\text{Gbps}$.

This figure is explicitly tagged as a **simulated software accounting estimate**, never
a physical PCIe/DMA/FPGA measurement or scaling guarantee.

---

## 4. Verification commands

Run from the repository source root (no GPU build tree required):

```bash
python3 ci/project/p09_training_and_collectives.py train-check --precision fp32
python3 ci/project/p09_training_and_collectives.py train-check --precision fp16_sim
python3 ci/project/p09_training_and_collectives.py collective-check --failure-mode link_drop
python3 -m unittest ci/project/test_p09_training_and_collectives.py
```

These checks establish `simulated` / `source_present` readiness only. Physical
`fpga_measured` qualification remains blocked until [P08](phases/p08-reliability.md)
closes and two physical FPGA boards are provisioned and measured under `ODR-006`.
