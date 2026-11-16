# P02 numerical evidence packet

The corrected source tested by this packet is
`a25321496d802f43830c1658487f1adf79c838c3`, tree
`7e459269e22f90691cf410e42068982f5a8c7a2d`.
All 27 formal outer commands retained that exact clean source before and after
execution. The source-contract acceptance decision is recorded separately;
assembling this packet does not grant a phase or acceptance result.

## Acceptance and later checks

The [acceptance record](acceptance.json) attaches **P02-A01 only**, at
`source_present`. P02 remains `in_progress`; A02/A03 need their remaining
processor and concurrency evidence. The [review addendum](review-addendum.json)
retains the independent packet and acceptance-scope reviews performed after
this immutable archive was assembled.

The [later delivery-check index](delivery-checks-index.json) identifies a
separate [compressed text record](delivery-checks.json.gz) containing metadata
validation, 55 passing project-checker tests, preservation audits and verified
reproduction instructions. Its raw and normalized identities remain distinct.
The [collaboration ledger](agent-execution.json) records this continuation's
actual completed assignments; agent counts are not GPU qualification.

## Observed results

| Check | Observed result | Scope |
|---|---|---|
| Full offline suite | 1,343 tests pass; zero failures, errors or skips; 369.310 seconds | Project tooling and host verification |
| Native dense arithmetic | 98 of 98 exact-bit fixtures pass, 49 per input format | Direct native TFR FEDP leaf, without DPI |
| Native enable-stall arithmetic | The same 98 fixtures pass; 306 hold checks pass | Leaf enable behavior |
| Production arithmetic model | The same 98 fixtures pass | Host invocation of `TfrFedp`, separate from full SimX execution |
| Independent layout fixtures | All 20 regenerate byte-for-byte and pass their source checks | Source matrix-memory layout contract; no GPU fixture adapter yet |
| Actual RISC-V API matrix | 47 cases pass: 17 compiler exit-zero results and 30 intended assertion rejections with compiler exit one | Both WMMA and WGMMA contexts in every case; 94 context checks |
| Existing consumer kernels | Four actual ELF64 RISC-V relocatable objects compiled | FP16/BF16 ordinary WMMA; WGMMA uses explicit integration overrides outside ordinary profile qualification |

The stall command repeats its dense prelude. That repetition is not additional
fixture coverage. Signed zero and NaN bits participate in the unsigned 32-bit
comparisons. No tolerance or golden value was changed to obtain these results.

Native tests configured a fresh RV64 `p02-tfr` build. The API matrix used a
separate fresh RV64 build with an empty profile because each of its 47 cases
supplies its exact configuration. Consumer builds each configured `p02-tfr`;
the retained WGMMA command lines declare their additional overrides. Exact
commands, generated configuration, source hashes, tool identities and logs are
in the bundled formal records.

## Files and integrity

- [summary.json](summary.json): result counts and qualification limits.
- [inventory.json](inventory.json): every original-to-published SHA-256 mapping,
  bundle digest and exact size.
- [evidence-bundle.json.gz](evidence-bundle.json.gz): deterministic gzip with
  694 normalized UTF-8 text members, including historical failures and
  expected negative exits. Its size is 1190216 bytes, below the 2 MiB
  packaging cap.

Every pre-existing digest field inside an embedded execution record still
identifies **original raw bytes**. It is deliberately unchanged. The inventory
records a separate `published_sha256` for each normalized member. The exporter
verified 289 distinct retained raw log bindings before normalization;
independent packet review is recorded separately. Public verification checks the
normalized bytes. Original-byte verification requires the retained originals.
The readable README is editorial documentation; it is not an original command
log or a member of the compressed export.

Useful member paths include:

- `formal-native-v2/manifest.json`: six passing clean-source native/model commands.
- `formal-api/report.json`: all 47 cases and selected include dependencies.
- `formal-compiler/manifest.json`: compiler matrix and four consumer objects.
- `formal-governance/manifest.json`: seven source checks, full suite and resource observations.
- `formal-history/failure-disposition.json`: historical failure audit, including its original observation-time limits.
- `formal-native/manifest.json` and `formal-native/fix-diagnostic.json`: the first clean build failure and separate corrected dirty-source diagnostics.
- `reviews/w05a25.json` through `reviews/w05a30.json`, and `reviews/w06a34.json`: independent source and correction reviews.
- `bounded_command.py` and the runner/source snapshots: retained execution helpers.

## Preserved failures and final disposition

The initial stall diagnostic passed its 96 dense cases, then failed while
constructing a second model after the shared Verilator context's clock had
advanced. The harness now owns a separate context per DUT. The original record
has **no preserved pre-fix harness byte snapshot**; the corrected source hash is
not assigned to that earlier failure. The corrected clean candidate's 98-case
stall execution supplies the current proof.

Clean candidate `135cfec14d1fed0b4e950bc243e69a91879e4275` failed native C++
compilation because raw profile `TCU_TYPE=TFR` flags did not propagate their
resolved selector to the harness. That build exited 2 and did not run numerical
fixtures. The separately reviewed correction appends validated resolved flags
to C++ compilation and adds an actual-profile regression. The final six native
commands passed on corrected commit `a25321496d802f43830c1658487f1adf79c838c3`.
The historical failure audit still says this correction was open **at its audit
time**; the later formal records resolve it without rewriting the earlier record.

The retained fast-math build failures are intentional guard rejections. The
original build also rejected that flag: a native stale-object bypass was not
reproduced. Compiler exit one is likewise retained for each expected API
assertion rejection; those invocations are not represented as exit-zero
compilations. The full offline suite separately verifies isolated finite,
signed-zero and NaN-payload mutations without modifying production fixture bits.

## Path normalization, exclusions and resource limits

`${SOURCE}` identifies the tested checkout and `${WORK}` its sibling evidence
workspace. `${RISCV_TOOLS}` and `${VERILATOR}` identify retained tool bundles.
Other roles identify earlier workspaces, host compilers and machine home paths.
Agent identifiers such as `/root/w05a29_a01_contract_review` remain unchanged.
No revision, fixture value, compiler identity, command exit or original digest
is rewritten by normalization.

System/resource header **bodies**, binaries, libraries, toolchains, temporary
files and waveforms are excluded. The selected-input manifests retain their
hashes: the API inventory has 121 selected inputs, including 58 GNU sysroot and
11 Clang resource headers; consumer probes cover 82 selected inputs. The two
inventories can overlap and are not a combined count of unique headers.

Execution retained the two-worker budget, 15 GiB disk reserve and per-command
bounds. Native build sampled peak RSS was below 1 GiB. Roughly 40.95 GiB of disk
remained free. RSS observations are sampled process-group values, not hard
quotas or an aggregate of nested helpers that create separate groups. Compiler
helpers retain their own limits and measurements.

## Verify the normalized packet

From the repository root, Python's standard library can verify the compressed,
expanded and per-member bytes without executing a bundled helper:

```sh
python3 - <<'PYVERIFY'
import gzip, hashlib, json
from pathlib import Path
p = Path('docs/project/evidence/p02-numerics')
sha = lambda b: hashlib.sha256(b).hexdigest()
inventory = json.loads((p / 'inventory.json').read_text())
archive = (p / inventory['bundle_path']).read_bytes()
assert len(archive) == inventory['bundle_size_bytes']
assert sha(archive) == inventory['bundle_sha256']
expanded = gzip.decompress(archive)
assert sha(expanded) == inventory['uncompressed_bundle_sha256']
bundle = json.loads(expanded)
files = bundle['files']
assert len(files) == inventory['file_count'] == len({f['path'] for f in files})
assert [{k:v for k,v in f.items() if k != 'content'} for f in files] == inventory['files']
for member in files:
    body = member['content'].encode('utf-8')
    assert len(body) == member['published_size_bytes']
    assert sha(body) == member['published_sha256']
print('Verified', len(files), 'normalized evidence members')
PYVERIFY
```

These results do not establish whole-processor layout execution, WGMMA
synchronization/concurrency, full-AFU integration, vendor hardware emulation or
physical performance. P02-A02/A03 require their own remaining proof. P01-A03's
blocked vendor evidence remains separate and unchanged.
