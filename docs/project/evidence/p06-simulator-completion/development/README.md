# Simulator completion development archives

These archives preserve original development records and their failures. The [packet index](../README.md) states the evidence boundary. Each archive has an external manifest and an identical `MANIFEST.json` member; every original-file member has its exact original path, byte count and SHA-256. The top-level [packet manifest](../manifest.json) binds the archives, manifests, reviews and existing initial host records.

| Proof | Retained outcome and scope | Files | Archive bytes |
|---|---|---:|---:|
| [w03-a05-runner-review](w03-a05-runner-review.tar.gz) ([manifest](w03-a05-runner-review.manifest.json)) | 26 host tests ran; 10 subtest failures reproduce fast-math and unretained include-search acceptance across five roles. Two host preprocessor comparisons retain the actual macro divergence. | 8 | 10,328 |
| [w04-a01-runner-repair](w04-a01-runner-repair.tar.gz) ([manifest](w04-a01-runner-repair.manifest.json)) | Generated stamp, option/include rejection, four host preprocessing and complete config-template checks pass. Pinned RISC-V kernel preprocessing and native execution are not_run. | 26 | 26,309 |
| [w04-a02](w04-a02.tar.gz) ([manifest](w04-a02.manifest.json)) | All 15 original test methods and existing assertions retained; final source-stable receipt records 26 passing host tests. The earlier generated compiler-selection gap is retained. | 9 | 13,590 |
| [w04-a03](w04-a03.tar.gz) ([manifest](w04-a03.manifest.json)) | Eight helper groups pass. All seven older groups pass the built targeted mutant, while the new immediate_check group fails its intended busy-edge assertion. | 29 | 21,951 |
| [w04-a04-native-probe](w04-a04-native-probe.tar.gz) ([manifest](w04-a04-native-probe.manifest.json)) | The actual-header probe compiles and exits zero because it reproduces the defect: inflight=1 and idle=0 survive full destruction and fresh-context consumption. Its historical name does not signify native Processor execution. | 5 | 5,909 |
| [w05-a01](w05-a01.tar.gz) ([manifest](w05-a01.manifest.json)) | The old header builds and fails the recovery assertion; the repaired header passes in release and debug. The failed live context remains non-idle until teardown. | 18 | 34,225 |
| [w05-a02](w05-a02.tar.gz) ([manifest](w05-a02.manifest.json)) | Four groups times two actual production headers: eight candidate cells pass, six built parent cells fail intended behavioral assertions, and both parent normal controls pass. | 54 | 92,235 |
| [w05-a03](w05-a03.tar.gz) ([manifest](w05-a03.manifest.json)) | Old functional header builds in release and debug and fails both recovery assertions; repaired header builds and passes both cells. Joined asynchronous host fault task; no native functional Processor execution. | 35 | 54,256 |
| [w05-a04-cleanup-probe](w05-a04-cleanup-probe.tar.gz) ([manifest](w05-a04-cleanup-probe.manifest.json)) | Four timing/functional times debug/release cells pass: healthy two-worker stop, discarded scheduled/immediate/cross-inbox payloads, destruction-only late owners, and fresh-context accounting. No internal-worker fault transport is tested. | 50 | 140,281 |
| [source-at-assembly](source-at-assembly.tar.gz) ([manifest](source-at-assembly.manifest.json)) | Later source snapshot at packet assembly; match recorded per-file hashes before associating with any execution. Includes local Python validator import closure; no build products. | 70 | 283,371 |

## Entry paths inside the archives

### w03-a05-runner-review

- `w03-a05-runner-review/initial-runner-failures.json`
- `w03-a05-runner-review/initial-runner-failures.log`
- `w03-a05-runner-review/preprocessor-probe.json`
- `w03-a05-runner-review/probe.py`

### w04-a01-runner-repair

- `w04-a01-runner-repair/generated-proof.json`
- `w04-a01-runner-repair/config-template-proof.json`
- `w04-a01-runner-repair/stamps/`

### w04-a02

- `w04-a02/assertion-preservation.json`
- `w04-a02/runner-tests-final.json`
- `w04-a02/runner-tests-final.log`
- `w04-a02/generated-compiler-selection-gap.json`
- `w04-a02/fixture.diff`

### w04-a03

- `w04-a03/report.md`
- `w04-a03/probe.json`
- `w04-a03/successful-check-mutation.diff`
- `w04-a03/mutant-immediate_check.log`
- `w04-a03/source/`

### w04-a04-native-probe

- `w04-a04-native-probe/commands.json`
- `w04-a04-native-probe/review-inputs.json`
- `w04-a04-native-probe/abandoned_channel.cpp`
- `w04-a04-native-probe/run.log`

### w05-a01

- `w05-a01/report.md`
- `w05-a01/report.json`
- `w05-a01/commands.json`
- `w05-a01/simobject.before.h`
- `w05-a01/simobject.after.h`
- `w05-a01/before_run.log`
- `w05-a01/after_release_run.log`
- `w05-a01/after_debug_run.log`

### w05-a02

- `w05-a02/summary.json`
- `w05-a02/metadata.json`
- `w05-a02/commands.json`
- `w05-a02/unittest-current.log`
- `w05-a02/sources/`

### w05-a03

- `w05-a03/report.json`
- `w05-a03/functional-cleanup.patch`
- `w05-a03/before/manifest.json`
- `w05-a03/after/manifest.json`
- `w05-a03/before/source/`
- `w05-a03/after/source/`

### w05-a04-cleanup-probe

- `w05-a04-cleanup-probe/summary.json`
- `w05-a04-cleanup-probe/commands.json`
- `w05-a04-cleanup-probe/lifecycle_probe.cpp`
- `w05-a04-cleanup-probe/run_probe.py`
- `w05-a04-cleanup-probe/source/`

### source-at-assembly

- `source-at-assembly/ci/project/p06_simulator_execute.py`
- `source-at-assembly/sim/common/simobject.h`
- `source-at-assembly/sim/common/simobject_functional.h`

## Provenance and exclusions

Original proof files are copied byte-for-byte. Reports may name temporary absolute paths or compiled binaries that were available during the run. Those historical statements are preserved. Executables, object/archive/shared-library files and Python caches are excluded; each sidecar lists every excluded original file and its reason. No native build tree or toolchain is included.

The [source bindings](source-bindings.json) distinguish the final host receipt from earlier runner revisions. All 11 source hashes in the final 26-test receipt match the later source-at-assembly snapshot. The original timing and functional headers are also retained by the before/after and parent proof archives. Complete runner source snapshots for the initial `b3b5013…` and intermediate `9326bbc…` states were unavailable; their original hashes, commands and logs remain retained. The final runner `373ed9b…` must not be substituted for those earlier states.

The source-at-assembly archive includes the current completion sources, fixtures, workflow/build inputs, the shared compiler validator and its transitive local Python helpers. It records source presence, not extra execution. It does not describe a clean checkpoint or replace each proof's own recorded source inventory.

Archived reviews are historical and use their original severity and scope language. The later runner review classifies the earlier compiler-record defects as F3; this does not rewrite the earlier failure record. Final exact-commit reviews and native CI artifacts remain separate additions.
