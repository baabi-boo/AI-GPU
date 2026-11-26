# A051 final protected-input audit

**Result: all 14 requested checks passed.** This was a read-only source and evidence-reference audit. No test bodies, builds, simulator, RTL, FPGA, native cancellation or physical-device work ran.

Observed HEAD: `d31e8879e7c248b1a72615128882533ccdd0b3b4`. Audited base: `858090410a992756808256ace90d36b9b3b88dd3`.
Observation interval: `2026-11-26T07:07:39.741783+00:00` through `2026-11-26T07:07:39.888661+00:00`. HEAD and short working-tree status were unchanged during the audit. The observed working tree intentionally includes uncommitted documentation and historical-reference updates.

## Preserved source and execution inputs

- All **69** distinct measurement sources match their frozen byte lengths and SHA-256 values: **1,303,138 bytes** read. Their exact base-to-working-tree diff is empty.
- All **21** complete Ramulator dependency descriptors equal the base proof. The proof revision, dependency pin and gitlink agree at `e62c84a6f0e06566ba6e182d308434b4532068a5`. **None of these 21 dependency source files is materialized locally; zero dependency source bytes were rehashed.** This verifies descriptor and pin preservation, not a fresh dependency build or source fetch.
- Both frozen proofs match their declared byte lengths, SHA-256 values and canonical-JSON SHA-256 values, remain byte-identical to base, and retain false claim fields.
- All **25** inherited golden files and **39** tracked numerical fixture files are unchanged. The exact selected resource/performance contracts and enforcement paths, native workflow, dependency contract, phase documents and acceptance policy have empty base-to-working-tree diffs.
- The unchanged qualified-warm population is **24 processes, 792 launches and 25,344 checked FP32 words**. Sampling and analysis remain unchanged, including one warm-up pair and five measured pairs, one prime and 32 timed operations, no replacements or optional stopping, a candidate median at most 95% of reference, and both formats required to improve.
- The **15 GiB** free-disk gate, **4 GiB** RSS bound and unchanged capacity code remain intact. No claim is made that this workspace meets native admission.

## Roadmap and historical evidence

Only the following two roadmap evidence references differ. Reversing exactly these references makes the **entire parsed roadmap document equal to base**, including every phase state, acceptance criterion, dependency, protected asset and other reference.

| Acceptance | Prior reference | Corrected reference |
|---|---|---|
| P02-A02 | `docs/project/evidence/p02-wmma/acceptance.json` | `docs/project/evidence/p02-wmma/acceptance-retained-source.json` |
| P05-A01 | `docs/project/evidence/governance-readiness/a01-retained-binding.json` | `docs/project/evidence/p06-checkpoint-publication/launcher/a01-retained-binding.json` |

The original P02 and P05 acceptance records remain byte-for-byte unchanged. The new records retain the historical helper/launcher/test digests and explicitly separate reference maintenance from new execution; A045 and A046 independently reviewed those concrete mappings. This audit confirms preservation of the original records and roadmap scope, not a new acceptance decision.

| Original record | Bytes | SHA-256 |
|---|---:|---|
| `docs/project/evidence/p02-wmma/acceptance.json` | 17,015 | `364f49da0eb495ffcd2ea9ff5a402396eab531db3422819a972ccb2f7be9396a` |
| `docs/project/evidence/governance-readiness/a01-retained-binding.json` | 26,412 | `d015566195b25e387f6f0593310e3bf3037a3a7511c4f91e083a23ad72200f39` |

Within the pre-existing tracked `docs/project/evidence` tree, the only changed path is `docs/project/evidence/p02-wmma/README.md`, which explains the retained helper reference. Original archives, acceptance JSON, inventories and execution evidence are unchanged. New snapshots, corrected reference records and continuation evidence are additive. This preservation statement uses exact Git diffs and explicit original-acceptance hashes; it is **not** a fresh rehash of every historical artifact.

## Retained graphic

`docs/assets/img/vortex_framework_stack.svg` remains **48,225 bytes**, SHA-256 `db123c71024f85f379c2504c7465c03ee9df8959a5d17fc3d3e94a94a1cd3aa4`. It matches the protected roadmap digest, is byte-identical to base, and remains embedded in the current README.

## Method and retained outputs

The standalone verifier imports Python standard-library modules only. It parses contract literals with `ast.literal_eval`, reads frozen source bytes, compares descriptors and complete roadmap JSON, and invokes read-only Git queries. It does not import or execute project modules.

```bash
cd /tmp/ai-gpu-2bfab0261c05/repo
python3 -B /tmp/ai-gpu-2bfab0261c05/validation/a051-protected-inputs.py
```

- Script: `/tmp/ai-gpu-2bfab0261c05/validation/a051-protected-inputs.py`, SHA-256 `4373eed20ecc1d0a46b1caaba56657605bd53bf6fe9f67eed246f9ee7ad64c11`.
- Result: `/tmp/ai-gpu-2bfab0261c05/validation/a051-protected-inputs.json`, SHA-256 `ad35aaa25d6c5f4aad156bf36b0e58b9eb0260dea94b5e05c2fa58aaa0c29caa`.
- The result retains all 69 measured-file hashes, 21 dependency descriptors, both proof identities, complete golden/fixture hash inventories, exact protected path lists and Git diffs, intended roadmap references, original acceptance hashes, resource/sampling/analysis values, and before/after status.

## Scope limits

- No tests, builds, native runs, dependency fetching or native/phase qualification were performed.
- The 21 dependency descriptors and gitlink are preserved; dependency source bytes are absent and were not rehashed.
- Historical tree preservation uses exact git diffs plus explicit acceptance-record hashes; every historical artifact was not separately rehashed.
- Status/backlog/README updates and new evidence are allowed presentation/provenance additions, not changes to accepted numerical scope.
- This audit describes the observed working tree; a later published revision still requires its own full strict governance and independent original replay.
