# P01 XRT tooling verification packet

The retained candidate run passed **875 project/tooling tests with zero failures,
errors or skips**. The actual prerequisite probe and the unchanged example
manifest plan both returned **blocked, exit 1**. The immutable-base classifier
returned advisory **R2**. No vendor `hw_emu`, GPU workload, physical FPGA or
silicon execution is established by these checks. **P01-A03 remains blocked.**

[verification.json](verification.json) is the unsigned, schema-version-1
`toolchain_verification` inventory. It records exact captured commands, results,
raw-file identities, selected candidate input hashes and explicit limitations.
It is not a roadmap acceptance report: `phase_complete` is `false`, `acceptance`
is `not_evaluated`, and `vendor_hw_emu_executed` is `false`.

## Exact implementation and observation identities

| Identity | Value |
|---|---|
| Tested source and tooling commit | `42e36724a2f2a02766b26de8deb9b04b7557fa27` |
| Tested tree | `c0f28a660c0a5c8b16d3f82adee06d104668d4e5` |
| Classifier source/policy and comparison base | `91b82fe300f94ab0a70dd0e0e4a69a0e23b16101` |
| Full suite observation | 2026-11-16, 00:29:34.078112 to 00:31:12.941418 UTC; exit 0 |
| Full suite elapsed time | 98.862 seconds wall time in metadata; 98.655 seconds reported by unittest |
| Protected SVG SHA-256 | `db123c71024f85f379c2504c7465c03ee9df8959a5d17fc3d3e94a94a1cd3aa4` |

The manifest hashes all 68 tracked files under `ci/project` at the candidate and
26 selected configure, generator, native-build, XRT and demo inputs. Each of
these 94 working-tree files was byte-compared to its candidate Git blob during
assembly. This selected inventory does not capture every dependency, submodule,
vendor installation, generated binary or environment setting. The SVG was also
checked against the candidate blob, working copy and candidate roadmap digest;
the candidate README still references it.

## Retained captures

All 13 raw files, totaling 185,864 bytes, are byte-preserving copies of the
inspected captures. Their SHA-256 values and byte sizes are in `artifacts` in
the manifest. The empty stderr files are retained too.

| Capture | Files | Interpretation |
|---|---|---|
| Full suite | [Metadata](p01-xrt-full-tests.json), [verbose log](p01-xrt-full-tests.log) | 875 tests pass; source-root tooling coverage only |
| Actual probe | [JSON output](p01-xrt-probe.json), [metadata](p01-xrt-probe-metadata.json), [stderr](p01-xrt-probe.stderr.txt) | Missing vendor executables/roots and qualified manifest/receipt; blocked |
| Example manifest plan | [JSON output](p01-xrt-example-plan.json), [metadata](p01-xrt-example-plan-metadata.json), [stderr](p01-xrt-example-plan.stderr.txt) | Unchanged example rejected at the placeholder `source.revision`; blocked before a ready plan |
| Base classifier | [JSON output](p01-xrt-change-impact.json), [command log](p01-xrt-change-impact.log), [base provenance](p01-xrt-change-impact.provenance.json), [explanation](p01-xrt-change-impact.explain.txt), [help log](p01-xrt-change-impact.help.log) | Determinate R2 for the recorded 32-path base-to-candidate delta; advisory |

The verbose suite has 875 test entries. One SST fixture prints intervening
messages before a separate `ok`; the other 874 entries have inline `ok` results.
The terminal summary is `Ran 875 tests` followed by plain `OK`, without skip or
failure annotations. Synthetic runner and packet records remain test fixtures.
Actual local configure, CPU ELF, process-control and disposable Git checks
within the suite do not turn those fixtures into GPU or vendor evidence.

The CLI metadata records its own interpreter identity, safe explicit
`PYTHONDONTWRITEBYTECODE=1` override, exact arguments, timestamps, hashes and
before/after observations. The suite metadata does not capture an equivalent
interpreter/environment inventory; the CLI record is not substituted for it.
Filesystem fingerprints exclude `.git` and access times and are not full-tree
content hashes. The Git index is hashed separately. No process execution trace
was collected.

## Historical paths are preserved

Raw metadata and logs retain the original generic workspace paths under
`/workspace/scratch/4f0bc2b9a6f1/`. The CLI's temporary build/output/tools roots
and the classifier's scratch snapshot directory describe the capture context;
they are not portable dependencies or current packet locations. The owned
empty CLI temporary directories were removed after capture. Other original
scratch paths may no longer exist.

Use the repository-relative `artifacts[].path` values to locate retained files.
`source_path_at_capture` and nested original metadata paths are provenance only.
No raw JSON was reserialized, no path was silently rewritten, and no log was
sanitized. Inspection found no credentials, license contents, raw environment
dump or personal user data in these captures. A future publication that needs
redaction must preserve these original identities and explicitly describe the
derivative instead of silently changing the files.

## Verify bytes without rerunning tests or builds

From the repository root, this read-only check verifies retained artifacts,
candidate input blobs, the selected current input files and the protected SVG:

```sh
python3 -B - <<'PY'
import hashlib
import json
from pathlib import Path
import subprocess

packet = Path('docs/project/evidence/p01-xrt-tooling')
record = json.loads((packet / 'verification.json').read_text())
revision = record['source_revision']
tree = subprocess.check_output(
    ['git', 'rev-parse', revision + '^{tree}'], text=True).strip()
assert tree == record['source_tree']

def check(data, item):
    assert len(data) == item['size_bytes'], item['path']
    assert hashlib.sha256(data).hexdigest() == item['sha256'], item['path']

for item in record['artifacts']:
    check(Path(item['path']).read_bytes(), item)
for item in record['source_files']:
    blob = subprocess.check_output(['git', 'show', revision + ':' + item['path']])
    check(blob, item)
    assert Path(item['path']).read_bytes() == blob, item['path']
asset = record['protected_asset']
check(Path(asset['path']).read_bytes(), asset)
print('Verified', len(record['artifacts']), 'retained captures,',
      len(record['source_files']), 'candidate inputs and the protected SVG.')
PY
```

This does not depend on the original scratch directories. A later intentional
implementation change will fail the current-input comparisons even if the
historical candidate and retained captures remain intact. Documentation added
after the test is deliberately outside that selected implementation inventory.
There is no manifest self-hash or self-referential attachment-commit identity.
Unsigned matching hashes do not authenticate the producer or independently
prove the truth of a recorded event.

## Reproduce new tooling observations

Use a separate checkout at the tested candidate, with suitable local Python,
compiler, `readelf` and operating-system prerequisites for the suite. From that
source root, the captured suite command is:

```sh
python3 -m unittest discover -s ci/project -p 'test_*.py' -v
```

Retain the new command output, exit status, actual source/tree, interpreter,
prerequisites and any skip reasons. A different host can produce different
results; do not copy the zero-skip assertion into an unobserved reproduction.
This packet was assembled without repeating that suite or any build.

The actual read-only CLI commands can be reproduced with fresh temporary paths:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 ci/project/xrt_baseline.py probe
verification_source="$PWD"
verification_tmp="$(mktemp -d)"
mkdir "$verification_tmp/tools"
PYTHONDONTWRITEBYTECODE=1 python3 ci/project/xrt_baseline.py plan \
  --source "$verification_source" \
  --build-dir "$verification_tmp/build" \
  --tool-dir "$verification_tmp/tools" \
  --manifest "$verification_source/ci/project/p01_xrt_environment.example.json" \
  --bundle-manifest "$verification_source/ci/project/p01_toolchain.lock.json" \
  --output "$verification_tmp/output"
```

Both captured invocations returned exit 1. Probe results depend on the actual
host. The unchanged example plan is deliberately incomplete and should remain
blocked; do not replace its placeholders and describe that as reproducing this
observation. The exact original arguments and paths are retained in the metadata.

To reproduce the advisory classification, extract `ci/change_impact.py`,
`docs/review/change-impact.yaml` and `docs/review/code-review-policy.md` from
base commit `91b82fe300f94ab0a70dd0e0e4a69a0e23b16101` into a separate scratch
directory using `git show <base>:<path>`. Compare their Git blob identities and
SHA-256 values with the retained provenance before invoking the extracted
classifier. Use the recorded `python3 -I` commands from the command log, replacing
only the obsolete scratch and repository paths. Keep global `--repo` and
`--policy` options before `classify` or `explain`; retain the recorded base,
candidate and `--event push`. The base classifier/policy must remain distinct
from any later working-tree versions. No classifier was rerun during assembly.

## Later documentation, review and acceptance

This packet and the accompanying review/handoff documents were added after the
candidate test run. Final documentation checks must identify their own revision
and results; they must not relabel the 875-test result as a test of a later
documentation commit. The manifest explicitly leaves those final checks and
publication observations unrecorded. The retained R2 classification also covers
the implementation delta only, not later additions to the documentation.

The packet makes no claim that an assignment total is complete or that a commit
has been published. Existing P01-A01/A02 records remain separate. P01-A03 needs
a qualified vendor environment/platform, matched artifacts and reviewed build
receipt, followed by an actual bounded `hw_emu` run and independent acceptance
review under the [integration guide](../../p01-xrt-integration.md) and
[acceptance policy](../../acceptance.md).
