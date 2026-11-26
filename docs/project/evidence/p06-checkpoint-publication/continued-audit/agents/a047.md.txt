# Agent 047 — independent launcher lifecycle test review

## Scope and disposition

Read-only review of all eight methods and the fixture in `ci/project/test_p05_launcher_signals.py`, with the production runner and A042's retained positive and explicit-old-revision negative control for context. HEAD was `a693d6f8828e4e10b5374db7fef8c727aa69d34e`; the reviewed launcher and tests were uncommitted. No blocking test defect found. This review did not execute tests, native code, builds or a full suite and did not edit repository files.

Reviewed file identities, unchanged across this review:

- New tests: SHA-256 `21583916f92b8bc6d44a5f7743052dd8222216979d3922f62dcf545ef03f1eed`.
- Production launcher: SHA-256 `01bdadc8469b50fc2b6e511684d37f1bc92d2f4030d3a0900481b8fb5173a128`.

## Actual process tests and bounds

The two primary real-process regressions execute actual `launch.main` through an outer isolated interpreter. Only bundle verification is replaced by an environment-copy stub; process creation, SIGTERM delivery, child execution, parent waiting, status normalization and reaping remain real. This is appropriate host-process ownership coverage and does not stand in for bundle verification or native execution evidence.

The tests wait for an explicit `ready` event before signaling the launcher PID, so they do not select a startup window through a timing sleep. The handled-SIGTERM case waits for the child's `handled` event, verifies the launcher remains alive while the child waits for input, and only then sends its continuation input. Thus it distinguishes forwarding from premature launcher exit and checks that a child's own termination policy is respected.

The probe controller uses five-second select and wait deadlines. The wrapper has a twelve-second alarm, and the inert child has an eight-second alarm. These outer-process probes therefore independently bound a launcher wait-loop regression; a production execution timeout is neither needed nor implied. The stream checks also reject extra child output after the successful parent return.

The wrapper inspects each tracked direct child's reap state before publishing its result. A still-running or unreaped child yields a false reaping flag rather than a successful observation. Expected normalized status 143 and reaped=true must both match in the default termination case; the handled case requires actual child status 21.

## Ownership and test isolation

After the child's ready event, the controller obtains a pidfd and uses that exact process identity for failure cleanup. It does not later reuse the child's numeric PID as a kill target. Launcher PID signaling is performed while the owned `Popen` child remains unreaped. Cleanup nests finally blocks so pidfd close failures or process cleanup failures do not skip closing the three pipe streams. The outer process is killed if still live and reaped with a timeout.

Each test captures its original SIGTERM disposition and registers restoration before installing the custom test handler. The isolated-package context restores module state. The real wait-error case keeps explicit child references and has a separate finally path to kill/reap them even if its assertions fail. The already-collected child case also retains a final wait path. No production probe creates arbitrary descendants.

The worker-thread boundary test uses a finite join and verifies no process creation or signal-disposition change. Its mocked process path does not create a real child. A hypothetical implementation that hangs forever inside the worker could leave the daemon thread after the failed join; this is a negative-path test-isolation limit, not observed behavior of the reviewed implementation.

A042's retained final positive result reports eight tests, zero failures/errors/skips, stable source hashes and unchanged cwd, environment, fd, thread and signal inventories. Those are A042's execution observations, not a second execution by this reviewer.

## Regression sensitivity

The synchronous startup callback is invoked inside the patched Popen factory before the returned child is assigned. Assertions require no child method invocation from the handler and require forwarding after ownership publication. This meaningfully tests the deferred-startup property without claiming to reproduce every real-signal scheduling window.

A042's negative runner extracts the launcher from explicit revision `858090410a992756808256ace90d36b9b3b88dd3`, independently observes launcher exit -15 followed by child continuation on input supplied only after that exit, and then runs the exact new regression method against the old launcher. The retained result has one expected failure and zero errors. A separate isolated Linux subreaper adopts and reaps the intentionally orphaned negative-control child; the retained runner checks no unreaped children and unchanged fd/signal observations. This establishes actual sensitivity to the original ownership bug rather than merely matching the new implementation's internal structure.

## Scope notes

The two outer-process lifecycle probes are independently timeout-bounded. Direct helper tests do not independently bound an arbitrary regression that spins forever in the parent wait loop, including the direct ordinary-child-success method. Do not describe all eight methods as externally timeout-isolated. The earlier A044 observation about the existing real-environment test has the same limited scope; the new outer-process probes supply independent coverage of the wait-loop boundary.

The fixtures use Linux pidfd APIs and belong to the stated Linux governance environment. They do not claim portability to operating systems without those APIs. No concrete supported-CI flake or assertion weakening was found. SIGKILL cancellation, general descendant ownership, native teardown and full-revision qualification remain outside these test claims.
