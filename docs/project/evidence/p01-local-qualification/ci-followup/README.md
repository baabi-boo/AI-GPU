# Governance timeout assertion follow-up

**The corrected clean local source passes all 1,260 tooling tests in 257.346 seconds, with zero failures, errors or skips.** This later record preserves the first published-head CI failure and its specific correction. The original [60-agent packet](../README.md) and all nine of its distributed files remain byte-for-byte unchanged.

## Failure and correction

[Project Governance run 43804865837](https://github.com/baabi-boo/AI-GPU/actions/runs/43804865837/job/133093201531) ran at `1b1bf5727c7a75deae1568b22c9d128e92ddc2d5`. It completed 1,260 tests in 197.634 seconds with one failure and process exit 1. The workflow-contract test still expected five minutes while the reviewed workflow and policy required ten. The [complete saved failure log](hosted-failure.log) and [terminal run/job metadata](hosted-failure.json) preserve that result.

The [one-line correction](correction.patch) requires exactly ten minutes. It retains exact equality and all permission, checkout, runner, Python, step-order and failure-propagation checks. The separate integer timeout guardrail still requires exactly one value in the range 1–10. The workflow itself is unchanged by this correction. See the [independent change review](change-review.json).

| Identity | Value |
| --- | --- |
| Actual tested local commit | `420937ede5c72653cf4abc7042caf9bec19c88b2` |
| Corresponding GitHub commit | [`f269505c`](https://github.com/baabi-boo/AI-GPU/commit/f269505cd15b69c853c04fd0b9c3d0adae7d81a1) |
| Identical source tree | `726d6e77166e1e47a0ee8e271696a5982c3b0e90` |
| Original commit bytes | [420937e.commit](420937e.commit) |

GitHub assigns different commit metadata. The mapping establishes exact source-tree identity; execution remains attached to the local commit actually run. Branch delivery and later hosted outcomes are observable on the GitHub commit containing this record and its checks, not inferred from a prepared object or local test pass.

## Fresh local verification

The unchanged discovery command ran from a clean checkout of the corrected source:

```sh
python3 -B -m unittest discover -s ci/project -p 'test_*.py'
```

All **1,260 tests passed**, with plain `OK`, in **257.346 seconds**. The bounded process exited zero, completed cleanup and took 257.709009 seconds overall. All 104 source-input hashes matched; Git revision and clean status matched before and after. Peak sampled process RSS was 94,474,240 bytes. The monitor used a 900-second limit, 1-GiB sampled-RSS limit, 4-MiB log limit and 15-GiB free-disk reserve; these are polled budgets, not hard quotas.

Retained inputs are the [result record](full-suite.json), [full log](full-suite.log), [independent completion review](full-suite-review.json) and [executed monitor script snapshot](run_clean_suite.py.txt). The script snapshot may contain inert public path tokens; use the discovery command above for normal reproduction. [verification.json](verification.json) records exact scopes and identities.

This tooling rerun does not repeat the eight native cases or two-unit RTL follow-up. Those retain their earlier tested revisions. GPU code, numerical bounds, vendor qualification flags and phase states are unchanged: P01-A03 remains blocked, and P02–P11 remain `not_started`.

## Integrity and historical scope

From this directory, run `sha256sum --check SHA256SUMS`. The [raw/public mapping](raw-public-map.json) preserves both hash domains and declares literal path substitutions. The public hosted-failure log also removes trailing spaces/tabs and final empty lines; its raw bytes and identity remain retained separately. Embedded result hashes still identify raw bytes. The checksum inventory validates distributed integrity; unsigned records do not authenticate execution.

The original archive remains SHA-256 `555b9daaa54630d74c4793c4d79dc79c5c390d8eb6fdbe064040b8dfad95b825`. Its 60 distinct agents and ten waves retain their original scope and timestamps. This follow-up reuses existing reviewers and records later outcomes separately without rewriting the sealed ledger.
