# Checkpoint publication v1

## Purpose and scope

The shared `p02_matrix._write_json` writer publishes bounded JSON checkpoints
for the native-development runners and P06 preparation, dependency and qualified
warm orchestration. A failed temporary write must not prevent a caller's
existing failure-finalization path from publishing its final report when the
underlying filesystem becomes writable again.

This is a filesystem publication contract. It does not retry a checkpoint,
restart a child, resume an experiment, change a receipt schema or turn a failed
attempt into a success. Each caller remains responsible for recording failures,
distinguishing a known nonstart from an unresolved launch, and deciding whether
its final report can be written.

## Publication sequence

1. Serialize with the existing deterministic JSON encoding and enforce the
   existing 16 MiB limit before creating a file.
2. Open the destination directory and exclusively create the existing
   `<filename>.tmp` name within that directory. A pre-existing temporary is a
   collision; the writer does not adopt, truncate or remove it.
3. Retain the created file descriptor and its device/inode identity. Write the
   complete document, flush the buffer, synchronize the file and close the
   buffered stream before publication.
4. Verify that the temporary directory entry still refers to the created inode,
   then replace the destination atomically within the opened directory.
5. On failure before publication, remove the temporary entry only if it still
   refers to the inode owned by this invocation. Keep the descriptor open during
   that identity check so an unlinked inode cannot be reused first. Close owned
   descriptors without repeating close against a potentially reused number.

The previous committed destination is unchanged when a write, flush, file sync
or pre-publication check fails. After a successful replacement, the newly
committed file remains in place even if later descriptor cleanup reports an
error. A cleanup error does not replace an earlier exception. An explicit later
call is a separate publication attempt, not an automatic retry.

## Recovery and ownership limits

The writer handles ordinary exceptions and cooperative `KeyboardInterrupt`
through the same cleanup path. Cleanup remains best effort: an unlink failure,
another interruption, an uncatchable kill, or failure before a trustworthy file
identity is available can leave a temporary behind. Such a collision continues
to fail closed; the writer never removes a file merely because its name ends in
`.tmp`.

Directory-relative operations retain the original directory as their target
even if its pathname is renamed. Identity checks are observations, not a lock
against malicious concurrent filesystem writers. Concurrent modification and
the visibility of a renamed directory require separate caller handling. The
writer does not promise persistence across machine or filesystem failure:
directory metadata is not synchronized, and no recovery journal is maintained.

## Qualification boundaries

Host filesystem tests establish preservation, cleanup, failure propagation and
consumer accounting only. Synthetic child fixtures do not execute GPU kernels
or supply warm-performance measurements. The qualified warm experiment keeps
its frozen measurement sources, dependency descriptors, workload population,
resource requirements, numerical references and performance predicates.

See the [project status](../project/status.md),
[qualified warm handoff](../project/p06-qualified-warm-handoff.md) and
[governance runbook](../project/governance-runbook.md) for the separate execution,
original-artifact replay and acceptance requirements.
