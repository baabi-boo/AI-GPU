"""Build focused handoff drafts; apply only after the independent A01 decision."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path('/workspace/scratch/ba0248fde989/AI-GPU')
HERE = ROOT.parent / 'p05-work/w09_a3'
REVISION = 'e1420fd550f716df33a2556057b7086a03032cbe'
BEFORE = json.loads((HERE / 'before.json').read_text())
DRAFTS = {}


def change(path, old, new):
    text = DRAFTS.get(path, (ROOT / path).read_text())
    assert text.count(old) == 1, (path, old[:100], text.count(old))
    DRAFTS[path] = text.replace(old, new)


change('docs/project/status.md', '''**P05-T01 is in progress**, following the
[Python binding handoff](p05-entry-handoff.md) and
[copying-binding audit](p05-binding-audit.md). The first plain-Python binding is
being implemented and independently qualified. P05 acceptance remains unearned;
P04 does not establish a Python/framework backend or physical GPU performance.''', '''**P05-T01 remains in progress; its plain-Python binding now has
[P05-A01 acceptance](evidence/p05-python/acceptance-binding.json).** The
[installed SimX packet](evidence/p05-python/README.md) binds the supported
representations, ownership/error checks and clean installation to
`e1420fd550f716df33a2556057b7086a03032cbe`. The next bounded action is the scoped
PyTorch custom-op route in the [binding handoff](p05-entry-handoff.md).
P05-A02 and P05-A03 remain unearned; this result establishes no framework backend
or physical GPU performance.''')
change('docs/project/status.md', '| P05 — Python binding | `in_progress` | First copying binding development; Python/framework acceptance remains unearned |', '| P05 — Python/framework bridge | `in_progress` | A01 accepts the bounded copying Python binding on SimX; custom-op execution and tested framework compatibility (A02/A03) remain unearned |')
change('docs/project/status.md', '''The [compatibility matrix](p05-python-compatibility.md) separates implemented
behavior, host-only tests and pending native qualification.

The package binds a wheel to exact native bundle and source hashes. Its
qualification workflow builds the unchanged native comparison path, rebuilds
the bound source archive offline, installs the wheel in a fresh environment and
compares actual Python outputs and dispatch records in separate FP16/BF16 SimX
processes. Qualification is pending; no P05 gate is accepted by these additions.
The scoped PyTorch custom-op route remains the following work package.''', '''The [compatibility matrix](p05-python-compatibility.md) separates qualified
SimX execution, host-only failure tests and unsupported framework behavior.

The [A01 record](evidence/p05-python/acceptance-binding.json) accepts the copying
binding at `e1420fd550f716df33a2556057b7086a03032cbe`, with binding-source SHA-256
`c4d476be1ab3dd73fbbe9b3027aac78db4a4890e536efea57319aecffcd6b19a`.
The installed FP16/BF16 matrix passed all six supported matmul signatures and ten
frozen model cases, using two output poisons per route. The combined matrix has
**144 native launches: 72 through Python and 72 through the native comparison**.
Its **660 event/profile pairs** comprise 360 Python and 300 native pairs; the
twelve standalone native comparison launches are unprofiled. The copied original
native packet is not an additional execution.

Each variant rebuilt a bound source archive offline and installed its wheel in a
fresh external environment. Hosted qualification used **CPython 3.12.14 and
G++ 11.4.0**; the separate local packaging checks used GCC/G++ 14.2.0.
The clean hosted source suite passed **2,174 tests in 421.584 seconds** at the
implementation revision. Independent numerical, dispatch and provenance audits
reconcile the original archives, actual outputs, source/build identities and
installation records in the [evidence packet](evidence/p05-python/README.md).

The [host history](evidence/p05-python/development/host-validation.md) retains
107 host-native lifecycle scenarios, eleven targeted probes, actual package
build checks and earlier failures. The changing-source local full-suite failure,
its isolated rechecks and the inherited configure timeout are not relabelled as
passes. Host fault injection does not establish accelerator arithmetic. Current
documentation records the tested implementation revision; it does not claim a
new execution at a later evidence-delivery commit.''')
change('docs/project/status.md', '''**P05-T01 — qualify the first copying Python binding.** Follow the
[entry handoff](p05-entry-handoff.md) and
[implemented contract](../designs/python_binding_v1.md): independently verify all
six declared signatures, frozen model cases, lifetimes, errors and clean package
installation against the native comparison path. P05 is `in_progress`; its
acceptance gates require their own evidence. After the plain-Python route is
qualified, implement and qualify the scoped PyTorch custom operators under the
[P05 phase guide](phases/p05-framework.md).
The [accepted executor packet](evidence/p04-executor/README.md) supplies the
unchanged native comparison path. See the [backlog](backlog.md) for the bounded
work item. P06 still needs a frozen benchmark/counter policy before performance
optimization claims.''', '''**P05-T01 — implement and qualify the scoped PyTorch custom-op route.**
Start from the [accepted copying binding](evidence/p05-python/acceptance-binding.json)
and [handoff](p05-entry-handoff.md). First freeze one tested framework version,
operator schemas, tensor devices/layouts, copying rules and explicit rejection of
unsupported gradients. Then route the declared operators through the existing
owners and reproduce the fixed model against the unchanged native executable,
retaining exact outputs, native dispatch, host bridge work and clean installation.
No PyTorch version is qualified yet. P05 remains `in_progress`; A02 needs actual
framework execution and A03 needs its versioned compatibility/failure matrix.
See the [phase guide](phases/p05-framework.md) and [backlog](backlog.md).
P06 still needs a frozen benchmark/counter policy before performance optimization
claims; the accepted Python binding does not supply those measurements.''')

change('docs/project/backlog.md', '## Start here: P05-T01 Python binding to the qualified native path', '## Start here: P05-T01 scoped PyTorch custom operators')
change('docs/project/backlog.md', '''**Current bounded task: P05-T01 — qualify the first copying Python binding.**
Use the [entry handoff](p05-entry-handoff.md),
[implemented contract](../designs/python_binding_v1.md) and
[compatibility matrix](p05-python-compatibility.md) to verify accepted native
ownership, exact representations, partial failure and trusted frozen model cases.
Keep the native executable as an independent comparison path. P05 is
`in_progress`; package installation, all declared signatures and the later scoped
framework route require their own evidence before acceptance.
The [executor audit](p04-executor-audit.md) retains the unresolved inherited
267 → 283 DSP area-gate failure; P04 does not resolve it.''', '''**P05-A01 now accepts the first copying Python binding** at
`e1420fd550f716df33a2556057b7086a03032cbe`; its
[acceptance record](evidence/p05-python/acceptance-binding.json) and
[execution packet](evidence/p05-python/README.md) retain the two-format installed
SimX matrix, clean packaging, ownership/error tests and independent audits.
The matrix has 144 combined Python/native launches and 660 event/profile pairs;
the clean hosted suite passed 2,174 tests at that source revision.

**Current bounded task: P05-T01 — implement and qualify the scoped PyTorch
custom-op route.** Use the [handoff](p05-entry-handoff.md),
[binding contract](../designs/python_binding_v1.md) and
[compatibility matrix](p05-python-compatibility.md). Freeze one framework version
and explicit dtype/shape/stride/device/copy/error rules before implementing its
operators through the existing owners. Reject unsupported gradients and layouts,
then reproduce the fixed model against the native comparison path in a fresh
installation with actual dispatch and separately recorded host work.
P05 remains `in_progress`; A02/A03 are unearned and no PyTorch version is qualified.
The [executor audit](p04-executor-audit.md) retains the unresolved inherited
267 → 283 DSP area-gate failure; Python qualification does not resolve it.''')
change('docs/project/backlog.md', '''scope. P05-T01 is in progress with the first copying Python binding; detailed
work packages remain in the phase guides, the [development audit](p05-binding-audit.md)
and the [Python binding handoff](p05-entry-handoff.md).''', '''scope. P05-A01 now accepts the bounded copying Python binding; P05-T01 remains
in progress for the scoped framework route. Detailed work packages remain in the
phase guides, the [development audit](p05-binding-audit.md) and the
[Python binding handoff](p05-entry-handoff.md).''')
change('docs/project/backlog.md', '| **P05-T01 — Python/custom-op bridge — in progress** | Qualify the implemented copying binding, native owners, trusted fixed cases and clean installation; then implement and qualify the scoped framework route. | P04; framework integration lead; [entry handoff](p05-entry-handoff.md) | P05-A01, P05-A02, P05-A03 unearned |', '| **P05-T01 — Python/custom-op bridge — in progress** | Preserve the accepted copying binding; freeze the framework version/operator contract, implement scoped custom operators and qualify fixed-model dispatch plus explicit failure behavior. | P04; framework integration lead; [handoff](p05-entry-handoff.md) | [P05-A01 accepted](evidence/p05-python/acceptance-binding.json); P05-A02/P05-A03 unearned |')

change('docs/project/p05-entry-handoff.md', '''# P05 entry handoff — bind the qualified native path

**Current bounded action:** independently qualify the implemented copying Python
binding to the managed matmul owner and frozen P04 case runner. The
[development audit](p05-binding-audit.md),
[implemented contract](../designs/python_binding_v1.md) and
[compatibility matrix](p05-python-compatibility.md) record this continuation.
Keep the native executable as an independent comparison path.
The [P05 phase guide](phases/p05-framework.md) defines the complete phase;
this handoff retains the entry requirements for its first work package.''', '''# P05 handoff — from the copying binding to scoped custom operators

**Current bounded action:** freeze and implement the supported PyTorch custom-op
route through the existing Python/native owners, then qualify the fixed model
against the independent native executable. No PyTorch version or custom operator
is qualified yet. P05 remains `in_progress`; A02 and A03 are unearned.

[P05-A01 accepts the copying binding](evidence/p05-python/acceptance-binding.json)
on SimX at `e1420fd550f716df33a2556057b7086a03032cbe`. The
[packet](evidence/p05-python/README.md) retains both installed formats, all six
matmul signatures, ten frozen model cases, exact outputs and native dispatch,
clean packaging and independently reviewed host lifecycle/error tests. Its full
matrix has 144 combined launches and 660 event/profile pairs; the clean hosted
suite passed 2,174 tests. This is the tested implementation scope, not a new run
at the later documentation commit.

The [development audit](p05-binding-audit.md),
[implemented contract](../designs/python_binding_v1.md),
[compatibility matrix](p05-python-compatibility.md) and
[P05 phase guide](phases/p05-framework.md) define the boundary to preserve.
The entry requirements and first-slice responsibilities below remain the design
history and obligations for any new caller.''')
change('docs/project/p05-entry-handoff.md', '''## First implementation slice

Start with a small C++ extension that owns the existing C++ objects and exposes
opaque Python session/operation objects. Choose and pin the extension mechanism
and Python build environment in a reviewed package contract before adding its
dependency. This keeps the first slice on the existing native implementation;
introducing a general installed C facade is a separate external-contract decision.

The first vertical test should create a qualified session, submit one supported
FP16 matmul, obtain and explicitly close its operation, and compare its actual
FP32 bits with the unchanged native executable/reference. This is an integration
checkpoint only. Expand to all six accepted signatures and both model formats
before claiming the package's declared support matrix.''', '''## Implemented first slice and preserved boundary

The C++17 CPython extension owns the existing C++ objects and exposes opaque
Python session/operation objects. Its reviewed package contract pins the build
environment and source/native identities; it adds no NumPy or PyTorch runtime
dependency. Introducing a general installed C facade remains a separate
external-contract decision.

The installed qualification now covers all six supported matmul signatures and
both frozen model formats, including explicit operation close and comparison of
actual FP32 bits with the unchanged native executable/reference. Extending that
caller into a framework still requires its own representation and dispatch proof.''')
change('docs/project/p05-entry-handoff.md', '## Freeze representations and ownership before code', '## Binding boundaries to preserve in the framework adapter')
change('docs/project/p05-entry-handoff.md', '| Boundary | Initial binding policy to specify and test |', '| Boundary | Binding policy to preserve and test |')
change('docs/project/p05-entry-handoff.md', '| Concurrency | Preserve the native single-caller rule; serialize access to each owner and operation; specify GIL release and Python object retention before allowing waits outside the GIL |', '| Concurrency | One live native context and one outstanding matmul until completed explicit close; main interpreter with the GIL held during native calls; no new queue or out-of-GIL concurrency claim |')
change('docs/project/p05-entry-handoff.md', '''Initially accept packed byte buffers with explicit metadata, so the package's
core correctness does not depend on a framework dtype adapter. Add NumPy or
framework adapters only after their byte order, stride, copy and conversion rules
are declared and tested. Preserve references to Python exporters until copying
finishes; return independent output ownership so closing a native operation
cannot invalidate a Python result.''', '''The core API accepts packed byte buffers with explicit metadata. A framework
adapter must declare and test its byte order, strides, copies and conversions
before using that boundary. Preserve references to tensor exporters until copying
finishes; return independent output ownership so closing a native operation
cannot invalidate a framework result.''')
change('docs/project/p05-entry-handoff.md', '''## Package and qualification work

Record exact tested Python, compiler, extension mechanism, native runtime,
backend, profile and optional framework versions. Select the actual versions in
the implementation environment; this plan does not guess a supported release.
Define how the clean package finds its matched runtime library and module,
records their identities, and rejects missing or mismatched prerequisites.
Build in fresh generated trees, keep incompatible native variants separate, and
test installation from a built artifact in a clean environment outside the source
checkout. Do not silently install or rebuild an entire GPU toolchain at import.

The binding's first qualification packet must cover:''', '''## Completed binding qualification and remaining framework proof

The hosted binding environment is CPython 3.12.14, G++ 11.4.0, Clang 20.1.8 and
GNU Make 4.3; local unbound packaging used GCC/G++ 14.2.0. The package-build pins
are setuptools 84.2.1, wheel 0.48.0 and packaging 26.3. Exact identities, hosted
RUNPATH entries, external dependencies and redistribution notices remain in the
[packet](evidence/p05-python/README.md) and
[compatibility matrix](p05-python-compatibility.md). These are qualified
environments, not a manylinux or arbitrary-host portability claim.

The accepted binding-source digest is
`c4d476be1ab3dd73fbbe9b3027aac78db4a4890e536efea57319aecffcd6b19a`.
Its source archive preserves the compiled bundle/source pins for offline wheel
rebuilding. The installed package rejects mismatched artifacts and does not
install a GPU toolchain at import. Each framework addition must retain fresh
separate builds, exact version identities and installation outside the checkout.

The binding packet covers these obligations, with injected failures identified
as host-only evidence:''')
change('docs/project/p05-entry-handoff.md', '''Use source-bound fixtures and preserve exact native comparisons. Adding Python
does not authorize regenerating the frozen fixture or widening numerical bounds.
The Python route needs its own evidence; existing native records are its baseline,
not proof that the binding ran. Apply independent review to the new external API,
build surface and any changed enforcement before acceptance.

After the plain Python route is qualified, add only the declared PyTorch custom
operators and reproduce the fixed model through them. Report their native
matmuls and the explicitly allowed host bridge separately. Unsupported autograd
must fail explicitly. A scoped custom operator does not establish a full device
backend, arbitrary model support, training, ONNX execution or CUDA compatibility.
All three [P05 acceptance gates](phases/p05-framework.md#deliverables-and-acceptance)
remain necessary: binding/install proof, framework model dispatch, and a tested
compatibility matrix with explicit limits.''', '''Preserve the source-bound fixtures and exact native comparisons. The accepted
Python route does not authorize regenerating fixtures, widening numerical bounds
or relabelling host-injected failures as accelerator observations. The new
framework caller, external operator schemas and any changed enforcement require
independent review and their own evidence.

## Next bounded framework slice

1. Freeze one supported PyTorch version and platform. Specify the operator
   schemas, accepted tensor devices/dtypes/shapes/strides, packing/copy policy,
   result ownership and explicit errors. No supported release is guessed here.
2. Implement only those custom operators through the qualified binding and
   existing owners. Reject unsupported layouts and gradients explicitly. Keep
   the fixed model and its expected arrays inside the trusted qualification
   boundary; arbitrary model loading is a separate contract.
3. In a fresh framework installation, reproduce all declared signatures and the
   ten frozen model cases against the native comparison path. Retain actual
   input/output bits, native launches, ownership/error tests, host ReLU/exact cast,
   assembly and transfer accounting. A reference result cannot replace execution.
4. Earn P05-A02 from the supported framework route's simulated execution and
   P05-A03 from its tested-version/operator/failure matrix. Preserve A01's exact
   source scope; keep P05 in progress until all three gates are satisfied.

A scoped custom operator establishes no full device backend, arbitrary model
support, autograd, training, ONNX execution or CUDA binary compatibility.''')

change('docs/project/p05-binding-audit.md', '''## Decision

The audited base is `6aac9c421180805a5621156e3d914c685fc6f4a5` on `master`.
The next bounded development step is the first plain-Python implementation of
P05-T01: a copying binding to the existing managed matmul owners and the frozen
P04 model-case executor. The [entry handoff](p05-entry-handoff.md) already names
this step, and inspection of the runtime and retained evidence supports it.
The Python route must earn its own execution and installation evidence.''', '''## Initial decision

The audited base was `6aac9c421180805a5621156e3d914c685fc6f4a5` on `master`.
The selected bounded development step was the first plain-Python implementation
of P05-T01: a copying binding to the existing managed matmul owners and frozen
P04 model-case executor. The entry handoff and inspection of the runtime and
retained evidence supported that choice. The resulting implementation and
qualification are recorded below; the [current handoff](p05-entry-handoff.md)
now carries the scoped framework work forward.''')
change('docs/project/p05-binding-audit.md', '## Local execution prerequisites and preserved blockers', '''## Qualification outcome and next development step

The implementation at `e1420fd550f716df33a2556057b7086a03032cbe` now has
[bounded P05-A01 acceptance](evidence/p05-python/acceptance-binding.json).
The [packet](evidence/p05-python/README.md) preserves both installed SimX variants,
all six matmul signatures and ten frozen model cases, native comparison logs,
exact source/build/package identities and independent numerical, dispatch and
provenance audits. Its 144 launches comprise 72 through Python and 72 through
the native comparison; 660 event/profile pairs exclude the unprofiled standalone
native calls. Fresh external installations passed with CPython 3.12.14 and
G++ 11.4.0, and the clean hosted suite passed 2,174 tests in 421.584 seconds.
The binding-source digest is
`c4d476be1ab3dd73fbbe9b3027aac78db4a4890e536efea57319aecffcd6b19a`.

Host-native lifecycle probes and local packaging evidence retain their exact
source scopes in the [host history](evidence/p05-python/development/host-validation.md).
The earlier source-changing local full-suite failure and inherited configure
timeout remain failures; later isolated and clean hosted passes do not erase
them. Independent counterexample reviews also found and repaired evidence-auditor
gaps before the formal matrix review, retaining the original failures.

The next bounded development step is the scoped PyTorch custom-op route:
freeze its framework version and operator/representation/error contract, reuse
the qualified owners, reject unsupported gradients/layouts and reproduce the
fixed model with new installation and native-dispatch evidence. A02 and A03
remain unearned; P05 stays `in_progress`. Neither a documentation delivery commit
nor the number of worker assignments establishes new execution or phase closure.

## Local execution prerequisites and preserved blockers''')
change('docs/project/p05-binding-audit.md', 'The audit environment has CPython 3.12.14, GCC 14.2.0, setuptools 84.2.1 and\nwheel 0.48.0. Its governance check passes.', 'The initial local audit environment has CPython 3.12.14, GCC 14.2.0, setuptools\n84.2.1 and wheel 0.48.0. Its governance check passes.')

change('README.md', '''**Current work: P05-T01 — the Python/custom-op bridge (`in_progress`).** The
first copying binding is implemented and undergoing independent qualification.
Start with the [binding handoff](docs/project/p05-entry-handoff.md),
[API contract](docs/designs/python_binding_v1.md) and
[package guide](python/README.md). The scoped PyTorch route remains subsequent work.
Processor RTL qualification does not establish full-AFU integration, physical
FPGA performance or a full framework backend. The
[executor audit](docs/project/p04-executor-audit.md) also preserves the unresolved
inherited tensor DSP area-gate failure.''', '''**Current work: P05-T01 — the Python/custom-op bridge (`in_progress`).**
[P05-A01 now accepts the copying Python binding](docs/project/evidence/p05-python/acceptance-binding.json)
on SimX at
[`e1420fd`](https://github.com/baabi-boo/AI-GPU/commit/e1420fd550f716df33a2556057b7086a03032cbe).
Both fresh installed formats passed the six supported matmul signatures and ten
frozen model cases: **144 combined Python/native launches and 660 event/profile
pairs**, plus **2,174 clean hosted source tests**. The
[Python evidence packet](docs/project/evidence/p05-python/README.md) retains exact
source/build/package identities, independent reviews and earlier failures.

The next bounded step is to freeze, implement and qualify the scoped PyTorch
custom-op route. **P05-A02/A03 remain unearned; no PyTorch version is qualified.**
Start with the [handoff](docs/project/p05-entry-handoff.md),
[API contract](docs/designs/python_binding_v1.md) and [package guide](python/README.md).
This simulated binding result establishes no Python RTL/XRT qualification,
physical FPGA performance or full framework backend. The
[executor audit](docs/project/p04-executor-audit.md) preserves the unresolved
inherited tensor DSP area-gate failure.''')
change('README.md', '| Software | Accepted bounded matmul library and fixed tiny-model execution, native tensor kernels and existing OpenCL/basic HIP routes | Add the qualified Python/custom-op bridge and preserve explicit placement/lifetimes |', '| Software | Accepted bounded matmul library, fixed tiny-model execution and copying Python binding; native tensor kernels and existing OpenCL/basic HIP routes | Add scoped PyTorch custom operators while preserving explicit placement/lifetimes |')

change('ROADMAP.md', '''contract. **P05-T01 is in progress**, with the first copying Python binding and
its independent qualification described in the
[binding handoff](docs/project/p05-entry-handoff.md) and
[implemented contract](docs/designs/python_binding_v1.md). P05 acceptance remains
unearned; P06–P11 remain `not_started`.
The [executor audit](docs/project/p04-executor-audit.md) records why this step
follows P03 and preserves the unresolved inherited CI area-gate failure.''', '''contract. **P05-T01 remains in progress, with
[P05-A01 accepted](docs/project/evidence/p05-python/acceptance-binding.json) for
the copying Python binding.** Its installed two-format SimX matrix at
`e1420fd550f716df33a2556057b7086a03032cbe` passed 144 combined Python/native
launches and 660 event/profile pairs; 2,174 clean hosted source tests passed.
The [Python packet](docs/project/evidence/p05-python/README.md) retains source-bound
installation, lifecycle/error tests, exact outputs and independent review.
The next bounded task is the scoped PyTorch custom-op route: freeze its supported
version and operator contract, implement it through the existing owners, then
reproduce the fixed model with actual dispatch and clean-install evidence.
The [handoff](docs/project/p05-entry-handoff.md) preserves the
[implemented binding contract](docs/designs/python_binding_v1.md).
P05-A02/A03 remain unearned; no framework version is qualified, and P06–P11
remain `not_started`. The [executor audit](docs/project/p04-executor-audit.md)
preserves the unresolved inherited CI area-gate failure.''')

roadmap = json.loads((ROOT / 'docs/project/roadmap.json').read_text())
phase = next(row for row in roadmap['phases'] if row['id'] == 'P05')
assert phase['status'] == 'in_progress' and phase['evidence'] == []
phase['evidence'] = [{'acceptance_id': 'P05-A01', 'record': 'docs/project/evidence/p05-python/acceptance-binding.json'}]
DRAFTS['docs/project/roadmap.json'] = json.dumps(roadmap, indent=2) + '\n'

draft_dir = HERE / 'drafts'
draft_dir.mkdir(exist_ok=True)
for name, text in DRAFTS.items():
    destination = draft_dir / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text)
if '--apply' not in sys.argv:
    print(json.dumps({'drafted': len(DRAFTS), 'repository_changes': False}))
    sys.exit(0)

acceptance_path = ROOT / 'docs/project/evidence/p05-python/acceptance-binding.json'
acceptance_bytes = acceptance_path.read_bytes()
acceptance = json.loads(acceptance_bytes)
assert acceptance['outcome'] == 'pass' and acceptance['evidence_level'] == 'simulated'
assert acceptance['source_revision'] == REVISION and acceptance['acceptance_ids'] == ['P05-A01']
assert acceptance['reviewer'].startswith('/root/w09_a2_binding_acceptance_review ')
assert hashlib.sha256(acceptance_bytes).hexdigest() == '1896bae3b59273f51448b554b965dc7d98d6beafcd446527c41c878a32c740c5'
review_bytes = (ROOT / 'docs/project/evidence/p05-python/binding-acceptance-review.json').read_bytes()
assert hashlib.sha256(review_bytes).hexdigest() == '3727a33b843e91d9faa9218182d03a80672d23f2b5cf9ab226edb280abd29ce3'
review = json.loads(review_bytes)
assert review['outcome'] == 'pass' and review['reviewer'] == '/root/w09_a2_binding_acceptance_review'
assert review['decision'] == {'P05': 'remain in_progress',
    'P05-A01': 'accept at simulated evidence level for the explicitly bounded plain-Python contract',
    'P05-A02': 'unearned', 'P05-A03': 'unearned'}
artifacts = []
for artifact in acceptance['artifacts']:
    body = (ROOT / artifact['path']).read_bytes()
    assert hashlib.sha256(body).hexdigest() == artifact['sha256'], artifact['path']
    artifacts.append(artifact['path'])
for name in DRAFTS:
    assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == BEFORE['files'][name], name
for name, text in DRAFTS.items():
    (ROOT / name).write_text(text)
report = {'acceptance_sha256': hashlib.sha256(acceptance_bytes).hexdigest(), 'acceptance_artifacts_verified': artifacts,
          'files': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in DRAFTS}}
(HERE / 'applied.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({'applied': len(DRAFTS), 'artifacts_verified': len(artifacts)}))
