# Independent immutable governance receipt review

Reviewer: `/root/w06_a05_governance_receipt_review`. The root coordinator
retained this summary of the independent completed-receipt review. The
reviewer did not author the implementation or alter its execution receipts.

**Result: the completed host-governance pass is supported by its original
log and report.** This is host evidence at the revision below, not a native
model run or a warm qualification.

## Execution identity

- Actual local revision: `53f4ad08c469a1cc73fa604249b302f9416055e0`.
- Actual tree: `80553bb237af44b187dd6d18178e851cd6671ec8`.
- Published commit with the same complete tree:
  `a9227933c340fd44e73deaffafdd353fecf65492`.
- Command: `python3 -m unittest discover -s ci/project -p 'test_*.py' -v`,
  with bytecode writing disabled, from the detached clean source checkout.
- Executing Python: resolved CPython 3.12 executable recorded in the original
  report, SHA-256
  `fa67443527ed9647f760d807e2a38f26340757123e643c4639cf273ed15d5ea7`.

The original report's source and interpreter identities are equal before and
after execution. Source was clean at both boundaries. Identical published
tree bytes do not relabel the local run as execution at another commit.

## Independently checked outcome

The original log ends with **3,043 tests in 1,647.227 seconds, OK**, with no
failures, errors or skips. The bounded process exited zero, recorded complete
cleanup and elapsed time of 1,648.962310 seconds. Recorded peak process-group
RSS was 326,823,936 bytes. The separate preflight and project-structure checks
also completed successfully.

The [retained index](../local/governance-53f4ad08c/index.json) binds the four
original files. In particular:

| Receipt | Bytes | SHA-256 |
|---|---:|---|
| `governance.log` | 527,529 | `e52d80f9df1545219bec0cdbce2dfa428a8d7c5815b1a2d6454436a2bef3fa79` |
| `report.json` | 10,157 | `995c6f007580ebc4b28d152435922fa19c7feaa5c498774ec64e88aaab189256` |

The source inventory's uninitialized native dependencies do not turn this
host-only run into native execution. The separate native preflight remained
blocked on the unchanged 15 GiB free-disk reserve. Later workflow and controlled
public-runtime tests were absent from this exact execution and were tested
separately; adding their count does not create a later full-suite run.

## Disposition

The immutable host-governance receipt can be retained as a passing result at
its actual source. No native, all-selector, aggregate-lifetime, warm-readiness
or acceptance claim follows from it. The original files remain unchanged.
