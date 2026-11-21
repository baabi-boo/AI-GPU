# Independent P05 evidence review

The three current auditors inspect retained data from implementation
`e1420fd550f716df33a2556057b7086a03032cbe`. They execute no installed extension,
native application or simulator. Numerical, dispatch and provenance obligations
are complementary; none of these scripts grants phase acceptance.

| Auditor | Current SHA-256 | Responsibility |
|---|---|---|
| `audit_numerics.py` | `608b16c80a1a40816ef15f04b2670c736e2abca7768e7c6ad546c8a96f23e736` | Frozen inputs and references, exact intermediate/output bits, live bridge lineage, complete case/iteration membership and independently derived counts |
| `audit_dispatch.py` | `ab0a1d1d6d0268b0766e5d3bc211e2830efb5e9683a413854fc1a16a3d5de391` | Native argument bytes, owner completion/cleanup, allocator bounds, ordered events, transfers and consistent per-command host timing |
| `audit_provenance.py` | `4684a4e928ff672d371bdb78ab5f646b61ae59d1147c3c690e722a22a89186ac` | Git/source/helper identities, generated configuration, compiler roles, monitored commands, bundle closure, compiled pins, offline packaging and installed-file identities |

Each reuses the corresponding independently reviewed P04 helper only after its
whole body matches a fixed SHA-256. No P05 producer, runner or record-validation
module is imported. Main-repository source is checked against immutable Git
objects where required. Recorded external tool, submodule and system-library
identities do not turn this packet into a reproducible transitive build archive.

## Counterexample review and corrections

The initial auditor bodies and before/after probe results remain in `history/`.
The numerical review found two false accepts: an unrecognized observation prefix
and a valid extra observation in an auxiliary log. The unchanged 24-case recheck
now passes both controls and rejects all 22 counterexamples.

The dispatch review first exposed rejection of a legitimate multiline Python
argument. It then found eleven accepted contradictions across address/resource
bounds, durations/owner chronology, hidden command membership, impossible
successful submission/wait states and explicit fallback text. All 42 unchanged
checks now meet their expectations: three controls and 39 rejections. The repair
worker and independent reviewer produced identical deterministic result bytes.

The provenance review first exposed rejection of the legitimate `GEM5_REV` key.
Its subsequent six false accepts covered impossible elapsed time, altered fixed
deadlines, a reserved failure marker, an unrecorded PATH, insufficient initial
memory and an altered native memory budget. All 26 bounded semantic checks and
four explicit CLI scope/output controls now meet expectations. Original failing
receipts remain separate from the successful rechecks.

These are evidence-checker corrections. The tested implementation, native
runtime, fixtures and numerical bounds were not changed to obtain the passing
review results. Worker receipts identify exact tested versions and any reviewer
harness corrections; an earlier receipt is never relabelled as a later run.

## Relocated data replay

From the repository root, choose a fresh absolute destination outside the
checkout. The extractor verifies both exact provider archives, the pinned member
index and every extracted member before the audits run. It preserves hidden
configuration stamp files and rejects an existing destination.

```sh
P05_REPLAY=/absolute/fresh/p05-retained-replay
python3 -B docs/project/evidence/p05-python/reviews/extract_retained.py \
  --output "$P05_REPLAY"

for P05_AUDIT in numerics dispatch provenance; do
  python3 -B "docs/project/evidence/p05-python/reviews/audit_$P05_AUDIT.py" \
    --source-dir "$PWD" \
    --packet "$P05_REPLAY/simx-fp16/python" \
    --packet "$P05_REPLAY/simx-bf16/python" \
    --output "$P05_REPLAY/$P05_AUDIT.json"
done
```

The default auditor invocation requires both formats. A per-format reviewer must
explicitly pass `--selected-scope`; its report then says the matrix is incomplete.
The copied `native/` records inside each Python packet are the native comparison
route. The additional top-level native packet in each ZIP is the original copy,
not another execution to add to the totals.

Raw steady-clock timestamps from separate processes are not aligned. Event
service and host wait/advance measurements overlap and must not be summed into
device latency. No retained-data review establishes physical throughput, a
hostile-process security boundary, arbitrary-host wheel portability, a PyTorch
custom operator or completion of P05.
