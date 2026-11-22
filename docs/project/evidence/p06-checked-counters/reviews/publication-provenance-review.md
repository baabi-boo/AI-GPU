# Independent publication provenance review

Reviewer: `/root/w07_a06_publication_provenance`. The root coordinator retained
this summary of the independent read-only review. The reviewer made no
publication changes.

**Result: both published implementation checkpoints have exactly the reviewed
local trees, and the published history preserves the observed upstream head.**

| Local reviewed commit | Published commit | Identical complete tree |
|---|---|---|
| `53f4ad08c469a1cc73fa604249b302f9416055e0` | `a9227933c340fd44e73deaffafdd353fecf65492` | `80553bb237af44b187dd6d18178e851cd6671ec8` |
| `713e05d99f8b37d4370f7607d1f8129d40cde73b` | `9fd7eac203c77fa54c7af80fa0220ae09553cd55` | `973fa9a286686990c96d10f95ab2e77ed6328f1a` |

The first published checkpoint directly descends from observed upstream
`89aa43236038fcfff5d36a7cdb95646b038fe2fb`; the second directly descends from
the first. Publication used the authorized repository and a non-forced branch
update with an expected-head lease. The original local history is retained at
`audit/local-checked-counters-713e05d99`.

The review confirmed historical inputs and evidence were preserved. This
mapping establishes repository byte equivalence, including executable modes
and gitlinks represented by the tree. It does not establish identical commit
metadata, repeat any test, or convert the local governance run into a run at
the published SHA. The hosted native run records its own actual source,
`9fd7eac203c77fa54c7af80fa0220ae09553cd55`.

See [publication.json](../publication.json) for the machine-readable mapping.
This receipt covers the two implementation checkpoints, not a claim about a
future documentation/evidence commit.
