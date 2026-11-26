# A087 supplemental — independent terminal provider selection

Independently reobserved the authenticated GitHub provider through account `baabi-boo` during **2026-11-26 10:55:38.299–10:55:54.482 UTC**. Read the prior A087/A084 selection guidance and the hosted helper's required-step contract. The earlier `reports/a087.md` remains unchanged. No download, replay, test execution, trigger, source edit or provider mutation occurred.

## Verified terminal identity

Current `master` resolves to **`81d7a35c641f3a969c23c8e604f7468a4d88644a`**, tree `9da606f541ecb85248ef00995e8288c1266eea88`. Run **`45796540254`**, current attempt **`1`**, is **completed/success** for that source, branch `master`, event `push`, workflow `418772913`, path `.github/workflows/project-governance.yml`. Both repository identities match `baabi-boo/AI-GPU`, ID `1457409699`.

Attempt jobs pagination returned exactly one unique `governance` job, **`139828665982`**, with a consistent total of one and an empty closing page 2. Its source/run/attempt match; **all 13 steps completed successfully**, including exactly one instance of each of the eight required steps. The job completed at **10:51:03 UTC**.

Run artifact pagination also returned a consistent total of one and an empty closing page 2. The sole artifact is:

| Bound field | Authenticated observation |
| --- | --- |
| ID | `15109565376` |
| Exact name | `project-governance-81d7a35c641f3a969c23c8e604f7468a4d88644a-run45796540254-attempt1` |
| Bytes | `1414721` |
| Provider SHA-256 | `5596e541ebf8eb272d813ee353b8e5eb998a641aef7b675f5b014cfd8e2ef045` |
| Expired | `false` |
| Created / updated | `2026-11-26T10:51:01Z` / `2026-11-26T10:51:01Z` |
| Expires | `2026-12-26T10:51:00Z` |

Artifact API/detail and `/zip` URLs match the ID exactly; nested run, repository/head-repository, branch and source fields match. Creation/update/expiry ordering and future expiry pass. The artifact omits a separate `workflow_run.run_attempt` field; attempt binding comes from its exact name, the current successful run and attempt-scoped jobs. A final run GET sealed selection with **byte-identical and canonical-identical** content to the first run GET.

## Retention and limits

`../a087-terminal-provider/` preserves seven exact returned UTF-8 bodies, request URLs/timestamps, connector metadata, summary and independently verified raw-byte/canonical-JSON hashes. Authored metadata omits `link_id`; provider bodies have no added newline. Headers are not exposed by the connector.

These non-atomic observations verify terminal provider selection, not original bytes or replay. Workflow-active/artifact-detail endpoints were unavailable in retained A025 review and were not reprobed. Artifact-list metadata cannot replace production detail reobservation, token-isolated transport or anonymous staging. Later local replay must retain `provider_authenticated:false` and remain separate from these observations. No full hosted admission, native/performance acceptance or phase acceptance is established.
