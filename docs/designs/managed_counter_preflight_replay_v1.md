# Complete managed-preflight replay v1

Contract ID: **p06-managed-counter-preflight-replay-v1**

## Purpose and scope

The [managed-counter preflight](managed_counter_preflight_v1.md) records a bounded,
seed-free SimX observation for two numerical formats and two ownership policies.
This contract defines the separate, complete retained-archive reader. A successful
replay establishes consistency with independently selected source expectations.
It does not establish a new native execution, producer authentication, dependency
compilation provenance, counter qualification, warm readiness, performance, or
phase acceptance.

The reader does not execute retained commands, import archived Python, load
retained binaries, or extract the ZIP. It executes trusted current reader code,
including the separately pinned current configuration renderer. The
[evidence packet](../project/evidence/p06-managed-preflight-replay/README.md)
distinguishes original producer evidence, current replay checks, independent
engineering reviews, and pending publication/CI results.

## Required external inputs

The [API and CLI](../../ci/project/p06_managed_preflight_replay.py) require all
seven inputs. The archive cannot supply its own trust anchors.

| CLI input | Meaning |
| --- | --- |
| `--archive` | Absolute, canonical path to a local regular ZIP; no symlink component |
| `--sha256` | Expected archive SHA-256 obtained outside the packet |
| `--source-revision` | Full lowercase producer Git commit |
| `--source-inventory` | Independently produced inventory of selected source bodies |
| `--source-inventory-sha256` | Expected digest of the exact inventory bytes |
| `--source-derivation` | Independent Git-object export receipt |
| `--source-derivation-sha256` | Expected digest of the exact derivation bytes |

The [source-inventory-v1 schema](../../ci/project/p06_managed_preflight_sources.py)
is unchanged. The additional [derivation reader](../../ci/project/p06_managed_preflight_derivation.py)
binds that inventory digest to the selected source revision/tree, Ramulator and
SoftFloat Gitlinks, two explicitly selected FetchContent commits, and every
selected body's repository mapping and Git blob identity. It checks the retained
checkout tree and Gitlinks against those externally selected values. Replay does
not invoke Git or independently revalidate Git object membership or remote origin.

The separate [source exporter](../../ci/project/p06_managed_preflight_source_export.py)
reads explicitly selected local Git objects without checkout, source imports, or
archive input. Fixed reviewed discovery recipes select 999 bodies: 806 first-party,
50 Ramulator, 7 SoftFloat, 99 spdlog, and 37 yaml-cpp. Unsupported discovery-helper
changes reject. The exporter independently computes each blob identity; matching
caller-selected objects do not authenticate remote repositories or mutable tags.
See the [independent export/derivation review](../project/evidence/p06-managed-preflight-replay/agents/w04_a04.md)
for exact dependency commits, both reproduced manifests/receipts, and limits.

## Complete verification relationships

| Area | Required relationship |
| --- | --- |
| Source | Every retained source descriptor and body agrees with the external inventory and derivation receipt |
| Producer identity | Checkout, loaded helpers, fixtures, profile, kernel, and historical warm-contract identities agree with their declared scope |
| Tools and resources | Recorded selected paths, identities, sanitized environments, limits, and before/after observations reconcile |
| Outer commands | All 35 envelopes occur in the planned order with exact arguments, directories, environments, classification, completion, and bounded observations |
| Generated configuration | Full configuration templates and stamps agree; four retained headers and both complete cflags streams are reproduced |
| Application graph | All 30 commands per format match eight retained recipes and obey their prerequisites |
| Backend graph | All 46 records per format match six retained recipes and obey compile/link prerequisites |
| Build artifacts | Both format builds have exact artifact, stage, compiler-role, source/object, and link inventories |
| Payloads | All 17 retained binary bodies are streamed, hashed, and bound to their recorded artifact/dependency identities |
| Processes | Native log text is reparsed against both recorded observations, the process plan, and reconstructed execution/build bindings |
| Lifecycle and counters | Operations, exact output words, counter pairing, selector availability, snapshots, terminal accounting, and loaded libraries reconcile |
| Stability | Complete ordered observations bind recorded source, tool, and dependency identities throughout the original attempt |
| Hosted envelope | Job, preparation, workflow, interpreter provisioning, and execution summaries agree; every archive file is accounted for |

The 35 outer command envelopes comprise seven tool-version observations and
14 commands per format: 12 configuration/build/inspection commands plus two
native processes. Their application and backend logs contain the finer command
graphs below; these are separate counts, not additional producer envelopes.

### Application and backend command graphs

The [application checker](../../ci/project/p06_managed_preflight_application_build.py)
requires, per format, one host dependency command, two recursive make commands,
14 RISC-V compiles (seven ordinary and seven KMU), two archives, two archive
dumps, five Clang kernel/startup/link commands, one vxbin conversion, one kernel
dump, one stub compile/link, and one host compile/link: **30 commands**. Shell
quoting and operators remain significant; the recorded startup `$(...)` stays
inert text. Each command occurs exactly once after its prerequisites.

The [backend checker](../../ci/project/p06_managed_preflight_backend_build.py)
closes the **46-record** backend log: one exact nested make record, 43 model
compiles, one model-library link, and one wrapped backend compile/link. All
model compiles follow nested make; the model link follows every object compile;
the backend link follows the model link. Independent object compiles may appear
in any order. Unknown, missing, duplicate, or prematurely linked records reject.
The [build review and repair](../project/evidence/p06-managed-preflight-replay/agents/w04_a03.md)
records the rehashed archives that exposed this gap and the precise rejections.

Changed recipes require a reviewed grammar update. Neither checker executes a
recipe to discover its meaning. The new application, backend, and generated
receipts remain separate from the unchanged original build bindings.

### Generated bytes, descriptors, and retained bodies

The [generated-input checker](../../ci/project/p06_managed_preflight_generated.py)
compiles hash-verified **current** `ci/gen_config.py` bytes directly, bypassing
cached bytecode. Retained generator, TOML, and profile bodies must equal the
pinned current inputs before rendering or expression resolution. A private
environment fixes XLEN to 64. It reproduces `sw/VX_config.h`, `hw/VX_config.vh`,
`sw/VX_types.h`, and `hw/VX_types.vh`; stage equality covers four headers × three
stages × two formats = **24 retained copies**. Both complete cflags streams have
273 flags. Two generated `vortex_opae` headers and their input were not retained
and remain outside this coverage. The
[independent generated-input review](../project/evidence/p06-managed-preflight-replay/agents/w04_a01.md)
includes stale-bytecode and altered-generator controls.

Each format contains **75 frozen artifact descriptors**, with 20/24/25 retained
files in the configured/backend/frozen stages. Descriptors record identities;
they do not imply that every described binary body is present. In particular,
the **43 model object bodies per format were not retained**. Their names,
recorded identities, and command/binding relationships are checked, but their
absent bodies cannot be independently rehashed and their compilation is not
proved. The reader does hash all seven retained binary payloads per format plus
three dependency products: **17 bodies totaling 13,315,886 bytes**.

The loaded-library inventory has five entries: three runtime libraries and two
Ramulator libraries. The retained SoftFloat static archive has a separate link
binding. Matching cached products to source inventories and loader observations
does not establish that those sources produced those binaries.

## Original controls and exact pins

The successful original is run **45085300171**, attempt **1**, job **137402429866**,
artifact **14779276315**, at source
`57248e73dfce4ae2d21d2cbdb82c3953eef2e3db` and tree
`cd61992a845ad14cbebd24b930c5801f727d5b41`. Its
[intake receipt](../project/evidence/p06-managed-preflight/native/run-45085300171-intake.json)
records service metadata separately from replay's unauthenticated consistency
claim. The original ZIP has 8,661,838 bytes and 1,215 files totaling 35,018,089
expanded bytes. Inside `managed-preflight/` are 1,208 files: one report,
1,172 retained files, and 35 logs. Seven hosted-envelope files sit outside that
directory and are also accounted for.

| Positive original input | SHA-256 |
| --- | --- |
| [Archive](../project/evidence/p06-managed-preflight/native/run-45085300171-attempt1.zip) | `cee5be4dba875494f6eafb83484933ab7693428e4773b932a26d5b91bd17969d` |
| [Source inventory](../project/evidence/p06-managed-preflight/native/source-inventory-57248e73.json) | `72ca7e9237060ca2831a275811d27ec6fdb3507dfd9a00b693aa177aa68382e8` |
| [Source derivation](../project/evidence/p06-managed-preflight/native/source-derivation-57248e73.json) | `3b25d30eceeee2dc5cebd1cce8ed7ab90da0fec64857e82fc7cc7fc3ca38e171` |

| Recomputed original population | Per process | All four processes |
| --- | ---: | ---: |
| Operations / launches (one prime plus 32) | 33 | 132 |
| Exact checked words | 1,056 | 4,224 |
| Snapshots | 4 | 16 |
| Available queries | 132 | 528 |
| Half replies | 264 | 1,056 |
| Cache-flush reads/replies | 33 | 132 |
| Total DCR reads/replies | 297 | 1,188 |
| Unavailable rows | 48 | 192 |

The four processes are FP16/BF16 × `per_operation`/`reusable_single_tile`, each
with its recorded model construction and destruction. The reader checks 999
source bodies totaling 11,097,225 bytes and all 1,172 retained-file descriptors.
These are recomputed historical observations, not new native launches.

The failed original is run **45084009157**, attempt **1**, job **137398337318**,
artifact **14778358605**, at source
`8756f40029e59c87546fa22f4da33acd4e5d8e02`. A host `CC` override propagated into
the RISC-V application build; no managed process, launch, or checked word
completed. See its [original intake](../project/evidence/p06-managed-preflight/native/run-45084009157-intake.json)
and [job log](../project/evidence/p06-managed-preflight/native/run-45084009157-job-137398337318.log).

| Failed original replay input | SHA-256 |
| --- | --- |
| [Archive](../project/evidence/p06-managed-preflight/native/run-45084009157-attempt1.zip) | `4f1e177ba930c132f5e8cc7558b3087d39789c346763f00a9d1bdd2a6d17d00c` |
| [Canonical replay inventory](../project/evidence/p06-managed-preflight/native/source-inventory-8756f400-replay.json) | `57a1290e4cadb7e357d109b49ff7e2ee85459c42b9a54d9522e1e178f3323c30` |
| [Canonical replay derivation](../project/evidence/p06-managed-preflight/native/source-derivation-8756f400-replay.json) | `492b142b047e71a84a62425aebf5d46bb35f2ec022a173d42d6463e04fe834b8` |

The positive reader must reject that correctly pinned failed original with exit
status **1** and reason **`report.outcome: value differs`**. A missing script,
usage error, stale digest, or unrelated exception does not satisfy this control.
The [older manually serialized inventory](../project/evidence/p06-managed-preflight/native/source-inventory-8756f400.json)
and [older derivation](../project/evidence/p06-managed-preflight/native/source-derivation-8756f400.json)
remain unchanged. The old inventory digest begins `9ae094b7`; it must not be
paired with the new canonical replay derivation.

## API and runnable CLI

The Python entry point is:

```python
replay_archive(path, sha256, *, expected_revision, source_inventory_path,
               source_inventory_sha256, source_derivation_path,
               source_derivation_sha256, prefix="managed-preflight")
```

Run the following from the repository source root. `pwd -P` supplies canonical
absolute input paths; `mktemp -d` supplies an existing temporary output directory
with a fresh filename. The reader requires the archive path itself to be
absolute and canonical and does not normalize a relative CLI archive argument.

```sh
replay_root="$(pwd -P)"
replay_output_dir="$(mktemp -d)"
python3 "$replay_root/ci/project/p06_managed_preflight_replay.py" \
  --archive "$replay_root/docs/project/evidence/p06-managed-preflight/native/run-45085300171-attempt1.zip" \
  --sha256 cee5be4dba875494f6eafb83484933ab7693428e4773b932a26d5b91bd17969d \
  --source-revision 57248e73dfce4ae2d21d2cbdb82c3953eef2e3db \
  --source-inventory "$replay_root/docs/project/evidence/p06-managed-preflight/native/source-inventory-57248e73.json" \
  --source-inventory-sha256 72ca7e9237060ca2831a275811d27ec6fdb3507dfd9a00b693aa177aa68382e8 \
  --source-derivation "$replay_root/docs/project/evidence/p06-managed-preflight/native/source-derivation-57248e73.json" \
  --source-derivation-sha256 3b25d30eceeee2dc5cebd1cce8ed7ab90da0fec64857e82fc7cc7fc3ca38e171 \
  --output "$replay_output_dir/replay.json"
```

On success, stdout identifies the full receipt's output path. `--output` is
optional; omitting it prints the full receipt. Output creation is exclusive and
preserves an existing file. A validation failure does not write a successful
replay receipt. This does not promise atomic recovery from output-device failures.

`--prefix` defaults to `managed-preflight`. A complete enclosing wrapper, such
as `outer/inner/managed-preflight`, is supported; unrelated members outside that
selected hosted parent reject. Recorded producer paths are inert path data,
never paths to inspect on the replay host.

## Trust, limits, and receipt interpretation

The pinned [ArchiveReader](../project/evidence/p05-torch/reviews/archive_reader.py)
has SHA-256 `4144becd4fe3c829380f7e66cdb66f7cf073b5e189c2620cd60c62940b9317d3`.
The managed reader compiles its verified current source bytes directly, bypassing
cached bytecode. It checks canonical member names, duplicates, directory/file
collisions, symlinks/special members, strict JSON, no-follow regular-file access,
archive stability, and bounded streaming without extraction. Limits are 256 MiB
compressed, 1 GiB aggregate expanded data, 20,000 files, 16 MiB per JSON read,
and 2 GiB aggregate reads. Replay additionally bounds binary payloads to 64 MiB
each and 256 MiB total. These ceilings are not expected allocations.

Current `trusted_replay_sources` contains **46** source identities, including
the new backend validator and explicit configuration renderer identity, checked
before and after replay. Earlier isolation evidence lists 45 because it predates
the backend module; its count must not be presented as the current closure.
The [isolation controls](../project/evidence/p06-managed-preflight-replay/agents/w03_a06.md)
separate trusted current initialization from prohibited archive execution and
producer-path reads. Python, its standard library, and the current trusted reader
process remain trusted; the contract does not sandbox a hostile interpreter.

The outer `host-dependencies.log` is retained and hashed, but its installation
semantics are not verified. Recorded tool identities omit parts of the tool,
system-header, compiler-support, and system-library closure. Before/after
observations do not defeat a malicious concurrent producer filesystem writer.
A consistently forged packet with caller-supplied matching pins can be
consistent without proving that the claimed execution occurred.

Every successful receipt therefore retains `native_execution="not_run"`,
`retained_code_executed=false`, and
`dependency_compilation_provenance_verified=false`. Hosted
`origin_authenticated` and `host_installation_log_semantics_verified` remain
false. All seven claim fields remain false:

- `qualified`
- `ready_for_warm`
- `warm_execution`
- `full_warm_coverage`
- `acceptance_claimed`
- `phase_acceptance`
- `performance_acceptance`

All three unresolved obligations are preserved verbatim:

- `all_40_component_lifetime_and_pending_balance`
- `dependency_source_to_loaded_binary_provenance`
- `independent_complete_counter_qualification`

## Next bounded native development

The [lifetime audit](../project/evidence/p06-managed-preflight-replay/agents/w01_a01.md)
calls for a read-only internal pending-read accessor and a separately versioned
witness at all 33 run boundary pairs, with zero balance before reset, after runs
and flushes, at the terminal observation, and at destruction, plus exact reset
increments. A source-bound argument must relate 33 available selectors to all
40 monotonic checked backing components and successful terminal sums. A new
public 40-field inspector is unnecessary if those premises are explicit.

The [dependency audit](../project/evidence/p06-managed-preflight-replay/agents/w01_a02.md)
requires fresh configure/compile/link/product receipts bound to the selected
loaded libraries and the static SoftFloat link. Retaining cached product hashes
does not discharge this obligation. Independent complete qualification must
then review both kinds of evidence before a separately reviewed warm admission
path can exist.

The [historical warm-v1 contract](warm_workspace_benchmark_v1.md) keeps its
unconditional `P06-WARM-RV64-MPM-HIGH-HALF` rejection and
`absolute_no_wrap_bound="not_established"`. P06-A02/A03, vendor XRT `hw_emu`,
physical FPGA, and silicon qualification are not earned by archive replay.
