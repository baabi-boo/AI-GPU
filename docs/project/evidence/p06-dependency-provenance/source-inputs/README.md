# Pinned dependency source graph observations

This directory retains the source inventory and selected compilation plan
observed again after the workspace reset. W03-A02 materialized all five exact
Git object trees reacquired by the parent; no dependency source was compiled.
See [the agent report](../agents/w03_a02.md) for the original findings, restored
code identities, verification commands and recovery limitations.

| File | Meaning |
| --- | --- |
| `manifest.json` | Complete 1,294-blob inventory; all Git blob identities reconstruct the five locked root trees |
| `source-plan.json` | Ordered 406-unit graph derived from the verified pinned build definitions and source bytes |
| `recovery-observation.json` | New source-only observation, counts and canonical digests; native execution and acceptance remain unavailable |
| `recovery-code-identities.json` | Six restored code/test files matched against their pre-reset SHA-256 identities |

The canonical JSON manifest SHA-256 is
`c677abd7a1cbb78cab13c23b40a92a83be427e06c3dffa40419de92b8697cd2e`.
The canonical JSON source-plan SHA-256 is
`f479cc6ed3ee4d4dd7fd305bc45943af33a3a2ba9069da48eebe627c5f817570`.
Both match the earlier W03-A02 observations. Canonical digests use
`p06_dependency_contract.json_bytes()`; the retained JSON files additionally end
with a newline, so a raw file SHA-256 is a separate identity.

The complete materialized source trees remain analysis inputs outside the
checkout at `/workspace/p06-pinned-inputs/materialized/`. This evidence is an
immutable-source and selected-plan audit. It does not establish actual compiler
execution, product provenance, native execution, counter qualification, warm
performance or phase acceptance.
