# Execution environment reset and recovery

The execution filesystem changed while the first foundation checkpoint was
being verified. The previous checkout under `/tmp`, pinned sources under
`/dev/shm`, local logs, and the original scratch directory disappeared together.
The first master publication had not occurred. Remote master remained
`832ae98178d7ce9022a13f1a69d9082f909c9e0d`.

Work resumed in a fresh checkout at `/workspace/AI-GPU`. Original authors restore
their files from retained tool-call histories where possible; lack of an exact
pre-reset hash is explicitly disclosed. Restored files receive fresh validation.
Earlier test passes are historical development observations, not validation of
the reconstructed candidate. The last pre-reset combined run executed 177 tests
and failed two error-message assertions after the literal-filename fix; the
message correction was applied, but its rerun was interrupted by the reset.

Remote recovery checkpoints preserve restored work while master remains at the
reviewed base. These incomplete checkpoints are not a complete implementation
or a passing native original. Recovery follow-ups do not create extra agents
for the requested sixty-agent count.
