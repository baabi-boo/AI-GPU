# Final governance retention contract

This is a prepared retention procedure, not a completed run or retention receipt.
The native 24-process experiment remains unstarted and resource blocked. The
4,527-test, two-partition governance run was still running when this was prepared.

After independent W10A03 reconciliation and observing supervisor process exit,
the coordinator supplies the reconciled SHA-256 of the original final
`execution.json` and explicitly selects the supervisor stdout:

```sh
python3 -B docs/project/evidence/p06-qualified-warm/validation/w10_a05-retain-governance.py.txt \
  --reconciled-execution-sha256 FINAL_EXECUTION_SHA256 \
  --supervisor-exit-confirmed \
  --supervisor-stdout /workspace/scratch/dc8be1693f91/validation/governance-partitioned-supervisor.stdout.log
```

Add `--allow-failed-finished` only to retain a finished failed/interrupted attempt.
Neither this option nor the exit declaration permits a running execution or
unfinished cleanup. The stdout's final JSON line must agree with the original
execution path and outcome. Exit observation is a coordinator declaration, not
a process-liveness measurement implemented by this script.

The fixed fresh destination is `validation/governance/final-c0b44ce6`, relative
to this packet. Any existing destination, including an incomplete attempt or
symlink, is refused. The program never deletes or rewrites original evidence.
Failure after exclusive destination creation leaves an incomplete directory;
do not mistake it for a successful packet or automatically remove/reuse it.

Every regular file recursively present in the original output directory is
inventoried, including an interrupted run's stop request and incomplete worker
result if present. Symbolic links, hard links and special files are refused.
Original `execution.json` is copied verbatim to destination `execution.json`.
All other output files are losslessly gzip encoded under `output/`, retaining
their relative names plus `.gz`; no text decoding, newline conversion or JSON
reserialization occurs. Gzip uses empty filename and `mtime=0`. The explicitly
selected external stdout is separately encoded under `coordinator/` and marked
`coordinator-selected-supervisor-stdout`. No venv, temporary tree or source
checkout is copied; the supervision code is already separately retained.

`retention-manifest.json` is written last. Its `entries` map each original path
to the retained path, original size/SHA-256, compressed size/SHA-256, decoded
size/SHA-256 and successful byte-by-byte decode comparison. The manifest keeps
the complete original output inventories before and after retention, plus
separate stdout inventories, and requires equality including metadata except
atime. Its execution summary copies only existing final execution fields;
it does not invent test counts, infer passing tests or modify result evidence.
The final publication inventory must bind the retention manifest itself.

Retention verifies preservation, not reconciliation, native execution, hardware
qualification, phase acceptance, or a successful governance outcome. A finished
failure remains a failure in its byte-exact original execution record.
