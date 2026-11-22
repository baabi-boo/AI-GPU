# Wave 4 independent public-hook review

## Scope and identities

Read-only independent review by `w04_hooks_review`. Reviewed both new files in
full against working-tree base `407ab9fea5e4f793a2a5088f566a87f3e631aa84`.
The files remain uncommitted at this review point; the hashes below, rather
than the base commit alone, identify the reviewed implementation.

| Path | SHA-256 |
| --- | --- |
| `tests/unittest/checked_counters/public_hooks.h` | `cb85ffb6df7151a3b9d747cfe243e464a3f16c4bd1063718b28af0800e86e95a` |
| `tests/unittest/checked_counters/public_hooks.cpp` | `c67ee622d159941d6c0ba3e759847cbe2fc463dcff9f9a989fd8dbf702ef434f` |

Read the repository AGENTS, code-review and simx-review instructions, both
coding-guideline files, bug-fix discipline, review policy, simulator architecture
and relevant framework lifecycle/host-observation sections. Read the hook,
public-main and build handoffs. Compared the new hooks with the actual
Processor, Core, backend, AsyncRun, counter-access and SimPlatform implementations.
The public makefile and caller were inspected at the hook boundaries, not
reviewed as complete independent scopes here.

## Findings

**No F1, F2 or F3 finding.** The following F0 observations explain the scope
and the checks that support that result.

### F0 high static-proof: real model calls and error ownership remain intact

`public_hooks.cpp:196-333` declares five exact `__real_` targets and defines
the corresponding `__wrap_` entry points. The constructor, destructor,
`run_checked`, `dcr_read` and `dcr_write` wrappers invoke those real targets.
There is no substitute Processor/RAM body, direct fake counter exception or
new production fault switch. The run/read/write handlers count actual typed
`PerfCounterError` reasons and rethrow them. Unexpected exceptions are also
counted and rethrown, so they cannot silently satisfy a typed failure case.

The unchanged SimX backend submits execution through `AsyncRun::start` and
model DCR calls through `AsyncRun::invoke`; both remain the actual error
boundary. The backend joins the execution owner before its Processor member
is destroyed. Direct-RAM DMA does not enter the model tick path; the accessor's
compile-time CP-on-LLC/VM/topology exclusions are therefore material to this
narrow observation contract.

### F0 high static-proof: wrapping is attached to the correct library

The supplied actual configured Make transcript places the hook object once
in `libvortex-simx.so` and applies all five `--wrap` entries at that library's
link. The model library excludes the hook object, and the executable links
the same diagnostic backend for the observation API. Wrapping only the
executable would not intercept an already linked backend; the current
arrangement avoids that error.

I independently parsed the retained caller/hook `nm` outputs and the second
Make transcript. Exact Processor symbol sets agree for the normal-header
caller, hook `__real_` references and global exported `__wrap_` definitions:
`C1`, `D1`, `run_checked`, `dcr_read` and `dcr_write`. Local GCC `.cold` clones
are not mistaken for additional exported wrappers. The hook object also
shows the expected GNU-unique inline SimPlatform singleton storage under
the selected GCC/Linux route. Actual interception still requires the native
runtime entry-count assertions; an object/symbol probe is not a native run.

### F0 high static-proof: diagnostic locking does not certify queue completion

The mutex spans each real intercepted execution/read/write call and protects
all hook-owned counters, traces and seed operations. There is no nested call
back into a hook-state accessor from the real methods on this route, so the
review found no lock recursion or join-under-hook-lock cycle. Real run
exceptions unwind the lock before AsyncRun collects them.

This mutex prevents these diagnostic accesses from racing intercepted model
entry points. It does not establish exclusive public ownership or that a
queued launch has been collected. The caller separately waits/finishes its
queues, and the scoped handoff correctly preserves that requirement. Seeds
also require platform idle, no running core and zero pending reads. The
diagnostic does not claim arbitrary concurrent-caller safety.

### F0 high static-proof: backing storage and destructor observations are live

The inventory records the existing 33-selector/40-component accessor pointers
once per live Processor generation. It is reset after actual destruction and
on construction of the next instance. No post-destruction path dereferences
the retained pointer values: `model_state()` handles a null owner without
inventory access, while seed/inventory operations reject a missing owner.

`Destruction.before` is collected before calling the real Processor destructor,
when the Core and component storage still exist. The real destructor deletes
ProcessorImpl, whose destructor finalizes SimPlatform. The subsequent
`ticks_after`, `reset_after` and `idle_after` observations concern the live
platform singleton, not freed model objects. Platform cleanup resets the
clock; comparing a terminal snapshot with `Destruction.before`, and checking
final cleanup separately, is the correct distinction.

The existing Core stats accessor recomputes the unselected derived
`opds_stalls` field. These observations should continue to be described as
preserving the selected 33/40 backing values, not as proving that every
unselected derived statistics field is never assigned. No selected source
is rewritten by the hook observation path.

### F0 high static-proof: bounded traces preserve failure distinctions

Reads carry actual generation, sequence, address/tag, result status, clock,
reset identity and counter class. A failed read is marked incomplete and
records the actual typed-overflow category. Its value field is only populated
for a successful zero-status read; it is not an independent observation of an
exceptional internal output pointer. The public caller separately retains
its actual destination sentinel and failure status.

The actual Core read implementation restores the performance class after a
successful CSR read. A throwing aggregate bypasses that restoration; the
hook correctly captures the resulting class transition instead of repairing
the failed model. That context is terminal. Bounds of 4,096 reads and 16
destructions are explicit; overflow raises/records a violation instead of
silently truncating successful evidence.

## Verification actually completed

- Read every hunk of the two new hook files and checked both final hashes.
- Inspected the retained fresh-configure, standard-flag syntax/object and
  normal-header symbol probes. Those receipts report successful commands;
  this reviewer did not rerun compilation.
- Independently checked the retained five caller symbols, five real targets,
  five global wrapper definitions, absence of an access-control override,
  checked/PIC compile selections, backend-only wrap link and single hook
  object placement using a bounded Python receipt parser.
- Ran `git diff --no-index --check /dev/null <file>` on both new files;
  neither produced a whitespace diagnostic. Exit 1 denotes the expected
  new-file difference.

Independent check receipt:
`/workspace/scratch/98908dfa3444/w04-hooks-review-checks.json`.
The original probe log is
`/workspace/scratch/98908dfa3444/w03-public-hooks-validation.log`.

**Not run:** native model/backend/runtime linking, the five public scenarios,
GPU/kernel execution, RTL parity, warm execution, or a measurement lifetime
qualification. The local native reserve was not bypassed. Native runtime
interception, fault containment and actual teardown remain hosted execution
obligations. The build/parser/caller scopes require their separate reviews.

## Classification and verdict

Treat the coupled hook/model diagnostic scope as **R2**; the surrounding new
enforcement/retained-result contract may warrant **R3** in the overall change
classification. No production API, model timing, ISA, configuration default,
golden value, tolerance or warm-readiness gate is changed by these two files.

**Verdict: land from this static hook-review scope.** No listed fix is needed.
This verdict does not turn pending native execution into a pass and supplies
no warm qualification or phase acceptance.

No repository edits, commits, pushes or destructive Git operations were made
by this reviewer. Only this scratch report and its receipt were written.
