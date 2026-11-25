# Agent 58 — concrete publication-plan review

## Decision and scope

**The publication plan is ready to execute after its listed prepublication gates; no concrete bad step found.** This is a read-only review of `BRIEF.md`, repository instructions, `publication-plan.md`, `prepared-publication.json`, `sync_evidence.py`, the current packet, Agent 24 source fields and the 23-file publication freeze. Only this report and its JSON companion were written. No Git writes, external mutations, test bodies, native execution or strict governance occurred.

## Required ordering is sound

The target is exclusively `baabi-boo/AI-GPU:master`. The plan refreshes both authenticated API and public-fetch observations before selecting the commit parent, preserves concurrent work, and requires a fresh reconciliation after a rejected lease. `expected_sha` plus `force: false` is supported by the available update-ref tool. The current configured fetch/push remote is exactly `https://github.com/baabi-boo/AI-GPU.git`, tracking `refs/heads/master`.

Tree construction reads staged blobs through structured JSON, binds worktree bytes and Git modes to the index, preserves untouched entries through the parent tree, and requires final API tree equality with `git write-tree` before creating the commit. Sequential tree batches prevent a later batch from dropping earlier changes. No file body is interpolated into shell command text. The commit uses the freshly observed parent and does not claim future CI success.

The plan verifies API/remote-tracking head, parent, tree, index and worktree before the optional `reset --soft`; it then requires a clean checkout. Actual published-commit classification follows publication. Exact-SHA push-triggered Actions results precede downloading and reconciling the final strict original, including provider digest, source/run/attempt, ordered 5,167-ID accounting and stable environment. Native dispatch and phase acceptance remain separate.

## Observed local evidence

- HEAD and local `origin/master`: `622662ad9cece6da4e3375be7e977dbe04cde862`; HEAD tree: `e494603f4e13517f3b5a4f1a39d386f1fc6c855b`. **Zero staged paths**; staged/API tree equality remains a future gate.
- The current 204 modified/untracked candidate paths contain one binary and no symlinks. That binary is the public governance original: **1,320,535 bytes**, SHA-256 `928e3d87bf32d2ea2d9b48581457f9bdd3086113b3129e0c562072da8d232156`, Git blob `91b63b09bea52345e93847c5ee440ee25d3f21a1`. Independent raw-byte Git hashing and read-only `git hash-object` agree with prepared metadata; the notes and packet copies are identical. I did not independently query the remote blob object.
- All 23 publication-freeze file hashes, sizes and modes match; the packet freeze is byte-identical. Against the historical 22-file freeze, only packaging changes and its final-cleanup regression is added.
- Agent 24 contains eight source identity fields. Seven still match; its packaging hash is historical, as its report explicitly scopes. That earlier review must not be promoted to validation of final packaging bytes.
- The observed packet ledger has 54 completed assignments, valid report hashes and `all_assignments_complete: false`. Final synchronization and all 60 reports remain required. The synchronizer copies selected completed-agent records byte-for-byte, rejects changed existing copies, and requires all 60 in final mode. It uses no shell execution and copies only the explicitly named ZIP. No complete age-private-key pattern was found in candidate files; this narrow check does not replace the separate packet privacy review.

## Identities, limits and next action

The JSON companion records reviewed hashes and observations. Publication-freeze SHA-256: `6c90e8e2c097b1d8db3534835d4f8ae94c4f6dc2c20b1c59283342c0b1c2dbf8`. Root should finish packet reconciliation, stage the exact reviewed candidate, and execute the ordered plan. This report establishes no final commit, push, exact-head CI success, strict qualification or native acceptance.
