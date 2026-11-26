# Agent028 independent base governance-original replay

## Result

**PASS — replay exit status 0.** The current reviewed reader reconciled the unchanged original for exact base source `858090410a992756808256ace90d36b9b3b88dd3` against a separate, clean detached checkout. No test bodies or code from the archive were executed. The selected trusted source was imported for canonical discovery in the reader's bounded child.

| Observation | Exact value |
| --- | --- |
| Original source revision | `858090410a992756808256ace90d36b9b3b88dd3` |
| Original source tree | `edb7faf37ac726f98c33f1bb3fa7dca4632564c3` |
| Canonical discovered / started / stopped / successful tests | **5,515 / 5,515 / 5,515 / 5,515** |
| Successful subtests | **38,655** |
| Ordered events | **55,200** |
| Original recorded execution duration | **3,134.501976 seconds** |
| Local replay wall duration | **10.897541513 seconds** |
| Non-successful IDs, loader errors, missing/duplicate/unexpected execution IDs | All empty |
| Coverage complete, counts match, order matches, execution completed, strict success | All true |
| Canonical test-ID SHA-256 | `e3ea87ea3f66c60bc7ce9bdf53cfd6d763df6e33a9aef7672310f6514c1327ce` |
| Archive bytes | **1,395,652** |
| Archive SHA-256 | `21c1c6bda5e8513d99642dd12d5db8c52d4b2bcae8726119b12236e7708fc74e` |
| Source tracked files / bytes | **8,295 / 529,054,119** |
| Source tracked SHA-256 | `d5dc42553a62622f2ad3cc869269bed2dad2725b84add01c6300168e3e8dd960` |
| Environment receipt SHA-256 | `fd601b55ce1a1d29f72aed8059de794b451fe67e672d296577e356463ab7b363` |
| Event bytes | **19,791,689** |
| Inner / outer log bytes | **990,785 / 991,288** |
| Replay started UTC | `2026-11-26T06:33:15.738522+00:00` |
| Replay completed UTC | `2026-11-26T06:33:26.636348+00:00` |

The original execution's only test and subtest outcome category is `success`; there are zero failures, errors, skips, expected failures or unexpected successes. The complete reconciled execution object is retained separately as `base-governance/a028/retained-execution-summary.json`.

## Independently selected inputs and provider boundary

The parent supplied the exact published base revision, run **45762183368**, attempt **1**, original artifact **15092372891**, expected archive size and expected SHA-256 from its authenticated provider observation. The adjacent `provider-original.json` binds the digest, size, artifact name and run revision. This agent independently recomputed the local original's digest and confirmed the exact supplied SHA-256; it did not select the expected digest by trusting the download itself.

The local receipt deliberately has `provider_authenticated: false`. This agent did not repeat the parent's authenticated download or provider API observation, and the local replay receipt alone makes no provider authentication claim. Retain the parent's provider-status and original-metadata evidence with the original ZIP.

Original retained unchanged at:

`/tmp/ai-gpu-2bfab0261c05/base-governance/run-45762183368-attempt1.zip`

Exact selected source retained at:

`/tmp/ai-gpu-2bfab0261c05/base-governance/source`

Before checkout, `df -h /tmp` reported **4.2 GiB available**, and `free -h` reported **6.6 GiB available memory** (rounded command output). The roughly 520 MiB checkout fit this budget. These observations concern this replay, and do not satisfy the separate native runner's 15 GiB free-disk admission requirement. The worktree was created using:

```bash
git worktree add --detach /tmp/ai-gpu-2bfab0261c05/base-governance/source 858090410a992756808256ace90d36b9b3b88dd3
```

`git status --porcelain=v1 --untracked-files=all` on the selected source was empty before and after replay. The reader separately verified exact tracked source materialization and unchanged source bindings during the invocation.

## Reader identity and exact invocation

Reader repository: `/tmp/ai-gpu-2bfab0261c05/repo`

Reader revision: `a693d6f8828e4e10b5374db7fef8c727aa69d34e`

The reader tree had one untracked audit document, `docs/project/p06-checkpoint-publication-audit.md`; there were no tracked changes. All seven reader and transitive local helper files were copied to `base-governance/a028/reader-source/`, compared byte-for-byte to their Git commit blobs before use, and confirmed unchanged after use. The untracked audit document was also snapshotted at invocation; it is not imported by replay. Its captured SHA-256 is `bf45a7ba1fe51500f4b881664761a693ef31e7c71420ac361acccef30e011503`. The root agent may subsequently continue editing that separate audit.

| Reader source file | Bytes | SHA-256 |
| --- | ---: | --- |
| `ci/project/governance_replay.py` | 15883 | `256a07bacab995253ae2716467e5912249d0c631b38aeb24c442d90a19574c66` |
| `ci/project/governance_replay_archive.py` | 12830 | `cf9f721c3e54282113b81b97b7269a34b1ad50720a46bcc09832e71bbf76f65a` |
| `ci/project/governance_replay_collect.py` | 17625 | `dbb04f76fb6632ac7e26de40113dff392ed15f5f497875e71fbde19ea283ecf9` |
| `ci/project/governance_replay_events.py` | 9710 | `743799138f8cab40dd44941650075c132071e47e801c7cb92649b0f9a1454195` |
| `ci/project/governance_replay_records.py` | 26503 | `561b2d64fa27f6704ef35b0959fd725ac41ede194d076b63b1cf5863918c9d44` |
| `ci/project/governance_replay_source.py` | 15570 | `8ffd8f69585f984a83f41e22ab87051602a9da3fc2e698561e52f9b6e39b1fea` |
| `ci/project/baseline_packet_io.py` | 14506 | `469583bc558ccb010af82259de38248d7a9a8283cd873a96726aa3c3e2aaa94c` |

Local Python: `3.12.14 (main, Aug 25 2026, 14:00:49) [Clang 22.1.3 ]` at `/opt/codex/runtimes/codex-primary-runtime/dependencies/python/bin/python3` (resolved `/opt/codex/runtimes/codex-primary-runtime/dependencies/python/bin/python3.12`), SHA-256 `fa67443527ed9647f760d807e2a38f26340757123e643c4639cf273ed15d5ea7`.

Local Git: `/usr/bin/git`, version **2.47.3**, SHA-256 `356db14e102d68a1a37d8a1ac577dfd678d45d46e92f468bef8b7154e7bfdc60`.

Working directory was the reader repository; `PYTHONDONTWRITEBYTECODE=1` was set. The exact argument vector is retained in both invocation JSON files. The command was:

```bash
PYTHONDONTWRITEBYTECODE=1 /opt/codex/runtimes/codex-primary-runtime/dependencies/python/bin/python3 -B /tmp/ai-gpu-2bfab0261c05/repo/ci/project/governance_replay.py --archive /tmp/ai-gpu-2bfab0261c05/base-governance/run-45762183368-attempt1.zip --expected-revision 858090410a992756808256ace90d36b9b3b88dd3 --source-dir /tmp/ai-gpu-2bfab0261c05/base-governance/source --expected-sha256 21c1c6bda5e8513d99642dd12d5db8c52d4b2bcae8726119b12236e7708fc74e --output /tmp/ai-gpu-2bfab0261c05/base-governance/a028/replay.json
```

Stdout and stderr were combined into the new `replay.log`. The receipt destination was absent, canonical and outside the selected source; the reader exclusively published it with mode 0600. No archive extraction, retained tool invocation, full test run, native build, source change or publication was performed.

## Reader bounds and claim limits

The current reader keeps these checks in force:

- Original ZIP and aggregate compressed member bytes: at most 256 MiB each; one expanded member: at most 256 MiB; aggregate expanded data: at most 512 MiB. The accepted governance packet has exactly its required 12 named members.
- The low-level archive grammar caps entries at 64, central-directory bytes at 64 KiB, and name bytes at 512; each required member also has its narrower documented cap.
- Retained canonical population: at most 100,000 test IDs of at most 4,096 bytes; at most 1,000,000 event records, each line at most 64 KiB, within the 32 MiB event record cap.
- Source observation: at most 32,768 files, 128 MiB per tracked file, 1 GiB tracked total, and 32 gitlinks, within a 30-second observation deadline; Git output is bounded to 4 MiB and subprocess execution to at most 10 seconds within that deadline.
- Trusted-source collection child: 60-second deadline, 1 GiB address-space limit, 32 MiB result cap, 1 MiB diagnostic cap, with 8 MiB request cap, disabled core dumps and bounded CPU/file output.

Scope is **`project-governance-artifact-replay-only`**. `independent_packet_replay` and `trusted_source_imported` are true. `provider_authenticated`, `retained_code_executed`, `tests_executed_by_replay`, `native_acceptance`, `phase_acceptance` and `performance_acceptance` are false.

This replays the retained base execution; it does not reproduce those tests, freshly identify the original runner binaries, execute their probes or qualify the current changed reader revision. A later changed revision needs its own complete strict governance original and independent replay. No P06-A02/A03 acceptance or vendor-integration closure follows from this result.

## Retained evidence

All inputs, worktree, raw log, receipt and reader-source records remain in place; nothing was deleted.

| File | SHA-256 |
| --- | --- |
| `/tmp/ai-gpu-2bfab0261c05/base-governance/a028/replay.json` | `503a7ba1cc0e9463b08dbbbda68ec6fb1785024ae6929f68b6b5be0fe6d57a49` |
| `/tmp/ai-gpu-2bfab0261c05/base-governance/a028/replay.log` | `503a7ba1cc0e9463b08dbbbda68ec6fb1785024ae6929f68b6b5be0fe6d57a49` |
| `/tmp/ai-gpu-2bfab0261c05/base-governance/a028/invocation.json` | `62cef2ca23ea693ddfcaff817db473784e01ae0a2183806b3831c27f158d165c` |
| `/tmp/ai-gpu-2bfab0261c05/base-governance/a028/invocation-completed.json` | `fcc6369b405036e0402199d523b03b0ac9f79cbe5e8a16ee14d689d9c8981a56` |
| `/tmp/ai-gpu-2bfab0261c05/base-governance/a028/reader-status.txt` | `ce6b93aa04a7b3bd70c79f2b2d52174679dfe2594582cb708aee3c851a443872` |
| `/tmp/ai-gpu-2bfab0261c05/base-governance/a028/retained-execution-summary.json` | `2d8c0e6c9e24efe9c4a3c9d2884026dbd89aa6f9d84e9af2a045ba9fee8e65d8` |
| `/tmp/ai-gpu-2bfab0261c05/base-governance/provider-original.json` | `2fd0b392a145839228c0c5f0efa59474c641c4a8786fd8d783cbfd39564ed9cd` |

`provider-status-a018.json` also remains adjacent to the original. This report is a local independent review record for the root agent to incorporate with the retained provenance.
