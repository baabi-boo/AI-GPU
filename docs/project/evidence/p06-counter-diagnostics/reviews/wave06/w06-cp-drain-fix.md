# CP terminal-observation repair

## Scope and status

Agent31of60, wave6first. Base revision: `81ed6871634fefbf5c78fb27cf10dce913bd4d9c`.
The owned files are frozen for an independent review. Only the three files listed below were changed by this agent. No production model/runtime file, VM/CP route, native build, native execution, commit, or push was performed.

Source repair and focused validation are complete. A fresh native execution remains required; these checks are not native acceptance.

## Finding

Severity **F2**, confidence **high**, evidence **static-proof plus retained native failure**: the public diagnostic incorrectly treats the zero-initialized host head-writeback buffer as an observed CP ring head. `CommandProcessor::mmio_write` stores the writeback address, but no production code publishes the internal head to it. `publish_completion()` writes only the retired sequence to the completion address. Consequently the first terminal normal observation fails its old `head == tail` assertion even after retirement.

The retained native archive is `native/run-45029135146-attempt1.zip`, SHA-256 `d628813ec8815140830825adef22cd2ea9191707686931e49145d5a4e4247db5`. Its public normal cell exited 1 with:

```
FAIL native public counter diagnostic: terminal CP ring is not drained
```

Its execution error remains `public-normal failed: nonzero_exit`; immediate-overflow, delayed-overflow, cache-overflow, and coherent-terminal remain blocked in that original report. Neither archive copy nor the original report/log was modified. The archived 45-TU model build and 19-TU/four-link public build do not constitute public execution success.

## Correct observation and source argument

Schema version 2 retains actual host bytes as `head_writeback_raw: 0`, explicitly labelled `head_writeback_status: "not-published"`. The raw bytes are checked against the initialized, unpublished contract, and are never substituted for an internal head or used as drain evidence.

The diagnostic reads both queue-tail register words over the existing CP register transport and retains their combined value as `tail_register`, independently of the observed runtime `runtime_tail`. It requires enabled global and queue controls, zero busy/error status, `retired == expected`, and `tail_register == runtime_tail == expected * 64`. The bounded expected sequence rules out overflow in byte-count multiplication.

`CommandProcessor::busy()` includes `head < tail`, a loaded cacheline, and both command and launch engine states while enabled. With exclusive device ownership and the runtime's one-command-per-64-byte-cacheline submission invariant, zero busy status plus exact retirement/tail accounting establishes a drained CP. This is recorded as `drain_basis: "enabled-idle-status-and-retired-sequence"`, a source-backed inference. There is no claim that the internal head was read.

Each CP observation adds two register-read success checks, one check that raw unpublished storage stays zero, and one exact byte-accounting check: +4 assertions per observation. A successful context observes CP twice. Versioned assertion counts are normal 1668, coherent-terminal 1814, immediate-overflow 1176, delayed-overflow 1176, cache-overflow 1173. These counts are derived from control flow, not represented as an execution receipt.

The five modes preserve all false qualification/warm/acceptance guards, exact 33-selector/40-component/66-half-read inventories, query status/tag/value checks, exclusive ownership, real model construction/destruction, typed failure containment, unchanged failed destinations, and fresh-context success obligations.

## Nearby assumptions audited

- The actual archived compile flags exclude VM, so `ensure_mmu_satp` and `check_mmu_fault` add no model DCR activity. The preprogrammed legacy launch has no extra kernel/argument/grid DCR writes. Exactly 19 descriptor DCR writes occur per context, 38 globally; failure-suppression counts remain fixed at 19.
- Empty COUT metadata is initialized through two CP memory writes and read after successful launch through two IO-aperture CP memory reads. Those IO reads bypass lazy cache-flush insertion, so they add no DCR reads/writes. The synthetic terminal CP examples now use the source-derived 26 pre-read commands and 92 after 66 half-read commands, while the validator retains its existing bounded sequence policy plus exact per-observation accounting.
- Timing `SimPlatform::cleanup()` explicitly clears cycles to zero, retires inflight state and leaves reset generation unchanged. The existing `ticks_after == 0`, idle-after, and unchanged reset-generation obligations are correct and retained.

## Narrow public log parser repair

A second concrete parser hole admitted a valid public record accompanied by a bare or tab-delimited reserved result marker. The parser now requires exactly one occurrence among `CHECKED_COUNTERS_RESULT`, `CHECKED_COUNTERS_FAILURE_RESULT`, and `COUNTER_PUBLIC_RESULT`, in addition to its pre-existing exact expected-prefix final-line rule. This matches the independently edited checked-log parser's reserved-family logic. Forty-five synthetic marker mutations cover mixed families, bare/tab/colon/suffixed forms, and leading whitespace/embedded noise. Ordinary dependency/statistics lines remain permitted. No failed/mixed original output was converted into pass evidence.

## Validation

- **Run, pass:** `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s ci/project -p test_p06_counter_public_records.py -v` from the source root: 33 tests in 2.031 seconds. These are synthetic retained-record checks, not processor execution.
- **Run, pass:** `/usr/bin/g++` (Debian 14.2.0-19) `-fsyntax-only` on the edited public main using the original native main compiler stamp and original generated headers from the failed ZIP. Only the source/generated include roots were relocated into this workspace; `-MMD`, `-MP`, and `-MF` output side effects were removed. All recorded macro, language, strict-warning, optimization, and PIC flags were retained. The check ran in the scratch generated-header tree and emitted no diagnostics. Receipt: `/workspace/scratch/98908dfa3444/w06-cp-drain-syntax/receipt.json`; log: `w06-cp-drain-syntax/syntax.log`.
- **Run, pass:** `git diff --check`.
- **Not run:** native build/link/execution, broad tests, model parity, RTL/hardware checks. No production change or timing modification is claimed.

The enforcement/schema change requires an independent review under the repository policy; this memo is the author record, not that review.

## Frozen file identities

- `tests/unittest/checked_counters/public_main.cpp`: `da176997e4ad4be4ec5d9e46b5d762c3d107cef4669a9a9f42a2f0df1ea819bf`
- `ci/project/p06_counter_public_records.py`: `c044522ae416cce3f038f2c0075a73e37b2460a20ca1ef11858de19aff0b8154`
- `ci/project/test_p06_counter_public_records.py`: `4c505133c7c7b32b4a14866b25152b38399e437b3a04adc2314b1f8826d4bac4`

Owned diff: `/workspace/scratch/98908dfa3444/w06-cp-drain-fix.patch`.
