# P06-A02 / P06-A03 Closure: Fused Native Tiny-MLP Optimization & Resource Budgets

This packet closes **`P06-A02`** ([`acceptance-optimization.json`](acceptance-optimization.json)) and **`P06-A03`** ([`acceptance-resources.json`](acceptance-resources.json)) at `rtl_verified` evidence level while preserving the accepted **`P06-A01`** cold-context SimX baseline ([`p06-a01-retained-baseline.json`](../p06-serial-workspace/p06-a01-retained-baseline.json)) untouched.

## Summary of Published Commits (`origin/master`)

| Wave / Scope | Commit | Verified Scope & Results |
|---|---|---|
| **SimX TraceOwner RAII** | `8a38d88` (`8a38d8847605867fd1793d21e4f863289796bd80`) | Core-scoped `TraceOwner` RAII ownership for `instr_trace_t`; verified on `simx` timed, `simx_completion_test`, `SIMX_MT=2` (bit-identical `instrs=2460`, `cycles=6448` vs `rtlsim` `2460`/`6404`), `SIMX_FUNCTIONAL`, `demo`, `sgemm_tcu`, and independent Neon R2 review. |
| **TCU MX Scale Shift Fix** | `1cf68ff` (`1cf68ff701c78331f84cb68607764de445689381`) | Precomputed `localparam` shifts in `mx_scale_at` in [`VX_tcu_core.sv`](../../../../hw/rtl/tcu/VX_tcu_core.sv); eliminated `+16` DSP regression (`283 -> 267` DSP `+0%`, `258,820` LUT `-1%`, `max_lv 25 +0%`, `p_fmax 253.4 MHz +0%` PASS on `logic_gate -b tensor`), `logic_gate -b core -b tcu` PASS, Verilator 5.050 `--lint-only` (`0` errors/warnings), and independent Neon R2 RTL review. |
| **Fused Native Tiny-MLP (`P06-A02`)** | `786f0ee` (`786f0ee43fbc4a5153c82c66baef98eaef2c372f`) | Single-launch 4-warp fused native `16 -> 8 -> 4` Tiny-MLP (`ai_mlp_fused`) using on-device ReLU + exact IEEE-754 RNE FP32→FP16/BF16 cast in registers and an on-core LMEM bridge with zero host round-trip; verified on `build64_p02tfr` (`--xlen=64 --profile=p02-tfr`) on both SimX and native processor RTL (`rtlsim`), plus independent Neon R2 review. |
| **Additive v2 AI Operators** | `cc459f8` (`cc459f843efe72d47a1ff0a0728680fb1e0676cd`) | 10/10 native v2 opcodes (`relu_fp32`, `gelu_fp32`, `cast_*`, `softmax_fp32`, `rmsnorm_fp32`, `layernorm_fp32`, `attention_fp32`) passed on SimX (`40,030` instrs, `159,046` cycles) and `rtlsim` (`40,030` instrs exact, `158,597` cycles, `0.28%` parity, `0` mismatches). |
| **P07–P11 Preparatory Tooling** | `3b8ca48` (`3b8ca48418e9c80f8708ffbbdac9a8ac5db95799`) | Machine-checked P07–P11 harnesses, dossiers, SBOM, and simulated P09 research prototypes (`71/71` unit tests passing, independent Neon R1 review). |

## P06-A02 Before/After Comparison (`build64_p02tfr`, RV64 `p02-tfr`)

| Metric / Case | P06-A01 Baseline (`84b6ca0`, SimX) | Optimized `ai_mlp_fused` (`786f0ee`) | Delta / Parity |
|---|---:|---:|---|
| Launches per model | `3` | `1` | `3.0x` fewer launches |
| Activation bridge | Host ReLU / cast / row assembly | On-core LMEM + register ReLU / IEEE-754 RNE cast | Zero host round-trip |
| Logical H2D + D2H bytes | `2,688 B` | `1,344 B` (`1,088 B` H2D + `256 B` D2H) | `2.0x` less H2D+D2H traffic |
| **BF16 `seeded_dense` (SimX vs SimX)** | `18,189` cycles (SimX) | `9,913` (`-n 2` post-fix) / `10,130` (`simx` cycles) | `1.83x` / `~1.80x` SimX speedup, `0` mismatches |
| **BF16 `seeded_dense` (`rtlsim`)** | `18,189` cycles (SimX baseline; no `rtlsim` in `P06-A01`) | `10,078` `rtlsim` cycles (`3,256` instrs) | `~1.80x` vs SimX baseline, `0.51%`–`1.64%` SimX/`rtlsim` parity, `0` mismatches |
| **BF16 5-case `rtlsim` total** | — | `16,040` instrs, `49,278` cycles, `320/320` exact FP32 logits | `0` mismatches |
| **FP16 `seeded_dense` (SimX vs SimX)** | `18,189` cycles (SimX) | `12,628` `simx` cycles (`3,946` instrs) | `1.44x` SimX speedup, `0` mismatches |
| **FP16 `seeded_dense` (`rtlsim`)** | `18,189` cycles (SimX baseline; no `rtlsim` in `P06-A01`) | `12,573` `rtlsim` cycles (`3,946` instrs) | `1.45x` vs SimX baseline, `0`-instr delta, `0.44%` SimX/`rtlsim` cycle parity, `0` mismatches |
| **FP16 5-case total (`-n 2 -v`)** | — | `320/320` exact logits, `640/640` exact FP32 hidden, `320/320` exact bridge words (`h_scratch` verified via `-v`) | `0` mismatches |

Note on `SimX` vs `rtlsim` pairing and post-fix `-n 2` / `h_scratch` runs: `P06-A01` is `simulated`-only (`18,189` SimX active core cycles), so direct apples-to-apples SimX comparisons are `18,189 -> 9,913`/`10,130` (BF16) and `18,189 -> 12,628` (FP16), while `rtlsim` (`10,078` BF16 / `12,573` FP16) adds native processor RTL parity. The BF16 SimX `9,913` cycle count reflects the post-R2-fix `-n 2` multi-iteration run (differing from the initial `10,130` `-n 1` sample due to warm iteration caching), and the FP16 `-n 2 -v` run explicitly enables `-v` (`verify_hidden`) to materialize and check `h_scratch` (`640/640` FP32 hidden + `320/320` bridge words) alongside the default logits check.

Detailed machine-readable breakdown: [`optimization-results.json`](optimization-results.json).

## P06-A03 Resource & Timing Budgets (`rtl_verified` Estimates Only)

All figures below are open-source Beacon and Yosys synthesis estimates, **explicitly not physical Vivado FPGA timing or foundry ASIC sign-off**:

1. **Local RV64 Beacon (`virtexuplusHBM`, `xcu55c-fsvh2892-2L-e` U55C) at `1cf68ff`:**
   - **`p02-tfr` 1-core RV64 (`VX_core_top`):** `132,962` LUT (`10.2%` U55C), `89,432` FF (`3.4%`), `3,904` LUTRAM, `20.0` BRAM (`1.0%`), `0` URAM, `33` DSP (`0.37%`), `24` max logic levels.
   - **`VX_tensor_top` scaled RV64 2-core + 256 KiB L2 + WGMMA + DXA (`USE_DSP=0`, `STD` FPU):** `367,926` LUT (`28.2%` U55C), `197,220` FF (`7.6%`), `15,818` LUTRAM, `132.5` BRAM (`6.6%`), `0` URAM, `11` DSP (`0.12%`), `25` max logic levels.
2. **Gated XLEN=32 Beacon `logic_gate` at `1cf68ff` (live `logic_gate` measurements vs checked-in baselines):**
   - `tensor`: **PASS** (`267` DSP `+0%`, `258,820` LUT `-1%` live at `1cf68ff` vs `260,189` LUT in [`ci/baselines/synthesis/beacon/tensor.json`](../../../../ci/baselines/synthesis/beacon/tensor.json), `253.4 MHz`).
   - `core`: **PASS** (`97` DSP `+0%`, `143,793` LUT, `285.6 MHz`, matching [`ci/baselines/synthesis/beacon/core.json`](../../../../ci/baselines/synthesis/beacon/core.json)).
   - `tcu`: **PASS** (`769` DSP `+0%`, `119,629` LUT live at `1cf68ff` vs `119,887` LUT in [`ci/baselines/synthesis/beacon/tensor.json`](../../../../ci/baselines/synthesis/beacon/tensor.json), `277.7 MHz`).
3. **Academic ASAP7 Yosys pre-layout estimates (`xlen=32`, separate scope):** retained in [`ci/baselines/synthesis/yosys/core.json`](../../../../ci/baselines/synthesis/yosys/core.json) and [`ci/baselines/synthesis/yosys/tensor.json`](../../../../ci/baselines/synthesis/yosys/tensor.json) as pre-layout academic estimates only.

Detailed machine-readable budget summary: [`resource-budgets.json`](resource-budgets.json).

## Preserved External Blockers (No Waivers)

- **Local `p06_qualified_warm` execution:** externally blocked because the owner-retained private control archive (`d3a16e1e6e92a68414f5fdcce564b963dde2e9e801601191d52ceeb974faea6f`) was not supplied; preserved without waiver.
- **`P01-A03` vendor XRT `hw_emu`:** remains `blocked`.
- **`P07`–`P11`:** remain `not_started`, awaiting physical Alveo U55C/V80 FPGA hardware (`P07`/`P08`/`P09`) and human go/no-go approval and funding (`P10`/`P11`).
