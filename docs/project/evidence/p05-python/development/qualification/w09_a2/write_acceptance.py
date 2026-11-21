#!/usr/bin/env python3
"""Assemble reviewed A01 records from already verified retained observations."""
import hashlib
import json
from pathlib import Path
import shlex

ROOT = Path('/workspace/scratch/ba0248fde989/AI-GPU')
BASE = ROOT / 'docs/project/evidence/p05-python'
WORK = ROOT.parent / 'p05-work/w09_a2'
REVISION = 'e1420fd550f716df33a2556057b7086a03032cbe'
TREE = '3a168adfd345ecb3c15dc02b2583dc832bef6049'
REVIEWER = '/root/w09_a2_binding_acceptance_review'

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def artifact(name):
    raw = (ROOT / name).read_bytes()
    return {'path': name, 'sha256': sha(raw)}

def save(name, value):
    with (BASE / name).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')

verified = json.loads((WORK / 'input-verification.json').read_bytes())
aggregate = json.loads((BASE / 'qualification-review.json').read_bytes())
host = json.loads((BASE / 'development/host/w06_a1_run.json').read_bytes())
assert verified['outcome'] == aggregate['outcome'] == 'pass'
assert verified['source_revision'] == aggregate['source_revision'] == REVISION

limitations = [
    'P05-A01 only. P05 remains in_progress. P05-A02 and P05-A03 remain unearned: no implemented or tested PyTorch custom operator or tested framework-version matrix is accepted.',
    'Qualified installed execution is Linux x86_64, GIL CPython 3.12.14, RV64 SimX with the p02-tfr profile. Python processor-RTL, full-AFU/XRT, physical FPGA and silicon execution are not qualified by this record.',
    'Only six packed little-endian FP16/BF16-to-FP32 matmul signatures and the ten frozen P04 model cases are supported. Arbitrary strides, transposes, broadcasting, models, weights, autograd, training, multi-device execution and CUDA binary compatibility are outside scope.',
    'Inputs and outputs are copied. One format/bundle and one live native context are permitted per process; a completed wait alone does not release the outstanding matmul ownership restriction. Explicit completed close is required.',
    'Timeouts are retryable and never cancellation. Native destruction may drain indefinitely. Cleanup failure poisons new work in the process; no device reset, broad physical fault recovery or exhaustive process-heap leak guarantee is established.',
    'The 107 compiled-boundary scenarios and 11 fresh-process probes use host-only fake runtime libraries. Their injected failures, status-publication MemoryError and interruption cases are not actual SimX/device-fault or global CPython out-of-memory tests. Actual installed SimX normal execution is separately retained.',
    'The local unbound packaging check used GCC/G++ 14.2.0 and one six-translation-unit build. Hosted bound qualification used G++ 11.4.0 and its wheel command compiled two groups of six translation units and linked twice. These source scopes and observations remain separate.',
    'The hosted extension and libsimx retain recorded RUNPATH entries. System ELF dependencies and compatible host Python/build tools remain prerequisites; ABI3, manylinux and arbitrary-host binary portability are not claimed.',
    'Source, compiler, dependency and package byte identities are retained, including required adjacent notices. This is trusted-builder consistency evidence, not authenticated binary authorship, a reproducible transitive toolchain build or a complete archived operating-system runtime.',
    'The allowed host ReLU, exact representation cast and row assembly are explicit. Host steady-clock event service, wait and advance intervals overlap and clocks from separate processes are not aligned. No physical latency, speedup, power or whole-system throughput claim follows.',
    'The native top-level packet and its python/native copy identify the same executions. The twelve native standalone launches are unprofiled; 132 profiled launches account for 660 event/profile pairs. Supplemental P04 workflow runs and overlapping host suites are not added to these counts.',
    'Earlier baseline timeout and source-changing local full-suite failures remain retained. One inherited workload-start assertion failed and later passed in isolation without a retained original inner report; its root cause is not asserted. Clean hosted 2174-test success qualifies the integrated implementation without erasing that history.',
    'P01-A03 vendor hw_emu remains blocked and the inherited tensor DSP267-to283 area-gate finding remains unresolved. Neither is waived or closed by Python acceptance.',
]

coverage = [
    {
        'obligation': 'Declared dtypes, shapes, strides and representations',
        'disposition': 'satisfied in bounded scope',
        'reason': 'All three (M,N,K) tuples (8,4,8), (8,4,16), (16,8,16) ran in each format through installed Python and the unchanged native comparison, twice with distinct poisons. Exact standalone/intermediate/final words and input lineage pass independent numerical review. Source-matched host tests explicitly reject nonpacked, negative/zero/mismatched strides, rank/extent/type errors, bool/subclass confusion, overflows, layout mismatch and unsupported signatures before native submission.',
        'evidence': ['docs/designs/python_binding_v1.md', 'ci/project/test_p05_python_api.py',
                     'docs/project/evidence/p05-python/reviews/full-numerics.json',
                     'docs/project/evidence/p05-python/hosted/governance-job.log'],
    },
    {
        'obligation': 'Lifetimes, copying and completion',
        'disposition': 'satisfied in bounded scope',
        'reason': 'Actual installed SimX runs complete and explicitly close sequential owners with restored declared allocator snapshots. The 107 maintained compiled-boundary scenarios and 11 probes additionally check copy ownership, output lifetime, pending owners, single-context and single-operation leases, session suspension/resume, partial submissions, timeout retry, context exits, destruction/fork behavior and sticky cleanup poison. All 64 recorded host-check source hashes match the qualified Git revision; fake-runtime failure evidence remains host-only.',
        'evidence': ['ci/project/test_p05_native_binding.py', 'docs/project/evidence/p05-python/development/host/w06_a1_run.json',
                     'docs/project/evidence/p05-python/development/host/w06_a1-native/results.json',
                     'docs/project/evidence/p05-python/development/host/w06_a1-probes/results.json',
                     'docs/project/evidence/p05-python/reviews/full-dispatch.json'],
    },
    {
        'obligation': 'Explicit validation, state and native error behavior',
        'disposition': 'satisfied in bounded scope',
        'reason': 'Clean hosted coverage and source-matched compiled probes check separate validation/primary/cleanup/completion dimensions, explicit TypeError/ValueError/OverflowError/BindingError mappings, detached diagnostics, closed/reentrant/inherited state refusal, failed lazy resume and recovery of retained empty or pending owners. Model output requires successful terminal inference and completed close. The complete clean source suite passed 2174 tests.',
        'evidence': ['python/vortex_ai/_api.py', 'python/native/module.cpp', 'ci/project/test_p05_python_api.py',
                     'docs/project/evidence/p05-python/development/host/w06_a1-probes/results.json',
                     'docs/project/evidence/p05-python/hosted/governance-jobs.json',
                     'docs/project/evidence/p05-python/hosted/governance-job.log'],
    },
    {
        'obligation': 'Clean installation and dependency lock/provenance',
        'disposition': 'satisfied in bounded scope',
        'reason': 'Each format produced a bound sdist outside source, rebuilt its wheel offline without the original bundle environment, created a fresh copied-interpreter venv, installed with --no-index --no-deps and imported/executed from outside the checkout. The independent provenance review verifies 22 pinned binding inputs, generated receipt/header, six bundle artifacts, 32 sdist files, 10 wheel members, 13 installed members, both RECORD tables, tool/package identities, ELF dependencies and actual project-library paths. Eight real local unbound package commands supply separate packaging evidence; all 22 inputs match the qualified source.',
        'evidence': ['pyproject.toml', 'setup.py', 'docs/project/evidence/p05-python/reviews/full-provenance.json',
                     'docs/project/evidence/p05-python/archives/simx-fp16.zip',
                     'docs/project/evidence/p05-python/archives/simx-bf16.zip',
                     'docs/project/evidence/p05-python/development/host/w06_a2-checks/commands.json',
                     'docs/project/evidence/p05-python/THIRD_PARTY_NOTICES.md'],
    },
]

review = {
    'schema_version': 1, 'record_id': 'p05-a01-independent-binding-review-e1420fd',
    'reviewer': REVIEWER, 'source_revision': REVISION, 'source_tree': TREE,
    'scope': 'Independent technical gate review of supported plain-Python binding representations, lifetimes, explicit errors and clean installation',
    'decision': {'P05-A01': 'accept at simulated evidence level for the explicitly bounded plain-Python contract',
                 'P05': 'remain in_progress', 'P05-A02': 'unearned', 'P05-A03': 'unearned'},
    'outcome': 'pass', 'unresolved_findings_in_scope': [], 'coverage': coverage,
    'input_reconciliation': {key: value for key, value in verified.items() if key != 'installed_command_receipts'},
    'reconciliation_execution': {
        'command': 'cwd=/workspace/scratch/ba0248fde989/AI-GPU; python -B /workspace/scratch/ba0248fde989/p05-work/w09_a2/verify_gate_inputs.py',
        'exit_code': 0, 'outcome': 'pass',
        'script_sha256': sha((WORK / 'verify_gate_inputs.py').read_bytes()),
        'result_sha256': sha((WORK / 'input-verification.json').read_bytes()),
        'log_sha256': sha((WORK / 'verify-gate-inputs.log').read_bytes()),
        'scope': 'Read-only JSON, archive/member, source Git blob and log checks; no native/package execution or full suite',
    },
    'reviewed_source_contract': artifact('docs/designs/python_binding_v1.md'),
    'independent_review_chain': {
        'production_boundary': ['development/w05_a1.md', 'development/w05_a2.md', 'development/w05_a3.md',
                                'development/w05_a4.md', 'development/w05_a5.md', 'development/w05_a6.md', 'development/w06_a3.md'],
        'auditor_adversarial_rechecks': ['reviews/history/numerics-after.json', 'reviews/history/dispatch-after.json',
                                       'reviews/history/provenance-after.json', 'reviews/history/provenance-cli-recheck.json'],
        'selected_and_full_matrix': ['reviews/fp16-numerics.json', 'reviews/fp16-dispatch.json', 'reviews/fp16-provenance.json',
                                     'reviews/bf16-numerics.json', 'reviews/bf16-dispatch.json', 'reviews/bf16-provenance.json',
                                     'reviews/full-numerics.json', 'reviews/full-dispatch.json', 'reviews/full-provenance.json'],
    },
    'authorization_boundary': 'The originating user requested implementation and direct master publication. This record is the named agent technical review, not an invented human review, maintainer waiver, procurement approval or phase-completion decision.',
    'limitations': limitations,
}
save('binding-acceptance-review.json', review)

commands = []
for row in verified['installed_command_receipts']:
    commands.append({'command': 'Retained ' + row['variant'] + ' original workflow packet, python/report.json [' + row['id']
                     + ']: cwd=' + shlex.quote(row['cwd']) + '; ' + shlex.join(row['argv'])
                     + '. Exact clean environment, deadline, raw log descriptor, process start and cleanup observations are retained in that archive member.',
                     'result': 'pass', 'exit_code': row['exit_code']})
commands.append({'command': 'Host-only source-bound development run: cwd=' + shlex.quote(host['cwd']) + '; '
                 + shlex.join(host['command']) + '. Exact environment and original dirty snapshot are retained in development/host/w06_a1_run.json; all 64 recorded source hashes match ' + REVISION + '.',
                 'result': 'pass', 'exit_code': host['returncode']})
for row in aggregate['commands']:
    commands.append({'command': 'Retained-data review only: cwd=' + shlex.quote(row['cwd']) + '; ' + shlex.join(row['command']),
                     'result': 'pass', 'exit_code': row['exit_code']})

names = [
    'docs/designs/python_binding_v1.md', 'python/vortex_ai/_api.py', 'python/native/module.cpp',
    'python/native/runtime_loader.cpp', 'python/vortex_ai/_bundle.py', 'python/vortex_ai/launch.py',
    'setup.py', 'pyproject.toml', 'MANIFEST.in',
    'ci/project/test_p05_python_api.py', 'ci/project/test_p05_native_binding.py',
    'ci/project/test_p05_packaging.py', 'ci/project/test_p05_bundle.py', 'ci/project/test_p05_launcher.py',
] + ['docs/project/evidence/p05-python/' + name for name in [
    'binding-acceptance-review.json', 'qualification-review.json', 'archive-index.json',
    'archives/simx-fp16.zip', 'archives/simx-bf16.zip', 'hosted/p05-run.json', 'hosted/p05-jobs.json',
    'hosted/p05-artifacts.json', 'hosted/governance-run.json', 'hosted/governance-jobs.json', 'hosted/governance-job.log',
    'reviews/audit_numerics.py', 'reviews/audit_dispatch.py', 'reviews/audit_provenance.py',
    'reviews/full-numerics.json', 'reviews/full-dispatch.json', 'reviews/full-provenance.json',
    'reviews/fp16-numerics.json', 'reviews/fp16-dispatch.json', 'reviews/fp16-provenance.json',
    'reviews/bf16-numerics.json', 'reviews/bf16-dispatch.json', 'reviews/bf16-provenance.json',
    'reviews/history/numerics-after.json', 'reviews/history/dispatch-after.json', 'reviews/history/provenance-after.json',
    'reviews/history/provenance-cli-recheck.json',
    'development/host-validation.md', 'development/host-review.json', 'development/host-retention.json',
    'development/host/w06_a1_run.json', 'development/host/w06_a1-native/results.json',
    'development/host/w06_a1-probes/results.json', 'development/host/w06_a2-checks/commands.json',
    'development/host/w06_a2-checks/result.json', 'development/host/w06_a2-checks/source-inventory.json',
    'development/host/full-host-development.json', 'development/host/full-host-development.log',
    'development/host/full-host-first-failure-recheck.log', 'development/host/baseline-host.log',
    'development/host/baseline-generated-records-recheck.log', 'THIRD_PARTY_NOTICES.md', 'licenses/sources.json',
]]
record = {
    'schema_version': 1, 'record_id': 'p05-a01-copying-python-binding-e1420fd', 'kind': 'simulation',
    'outcome': 'pass', 'evidence_level': 'simulated', 'acceptance_ids': ['P05-A01'],
    'source_revision': REVISION,
    'scope': 'Accept the first plain-Python copying binding for six declared FP16/BF16 matmul signatures and ten fixed model cases on RV64 SimX. The two clean installed routes match unchanged native comparison paths, with 144 combined launches and 660 event/profile pairs. Source-matched host checks establish the declared representation validation, copied ownership, completion/error behavior and recovery boundaries; actual clean bound package installations pass in both formats. This accepts P05-A01 only, not P05 completion or a framework/device backend.',
    'configuration': 'Clean implementation tree ' + TREE + '; vortex-ai 0.1.0 / binding API 1; Linux x86_64 GIL CPython 3.12.14, C++17, hosted G++ 11.4.0, Vortex Clang 20.1.8 and GNU Make 4.3; TOOLCHAIN_REV v3.0.2. Package tools setuptools 84.2.1, wheel 0.48.0, packaging 26.3; no runtime NumPy/PyTorch dependency. Exact 22-input binding digest c4d476be1ab3dd73fbbe9b3027aac78db4a4890e536efea57319aecffcd6b19a. Profile p02-tfr, two poisons/iterations per case, one FP16 or BF16 pinned bundle per fresh process, copied packed A row-major/B column-major and raw row-major FP32 output. Per-format source/configuration/tool/compiler records, six artifact pins, 12 P05 and 15 native command observations are retained in the two original archives; the full provenance review verifies their bound sdist, offline wheel, fresh venv installation and outside-checkout execution.',
    'commands': commands, 'artifacts': [artifact(name) for name in names], 'limitations': limitations,
    'reviewer': REVIEWER + ' independently accepts the bounded P05-A01 technical evidence after source/contract review and read-only reconciliation of 64 host source hashes, 22 package inputs, 608 original archive members, six selected reports and three full-matrix audits. W08 format reviewers, W07 adversarial reviewers and W09 A1 full-matrix review provide separate recorded scrutiny. No human review, maintainer waiver or phase-completion approval is fabricated.',
}
save('acceptance-binding.json', record)
print(json.dumps({'outcome': 'pass', 'acceptance': artifact('docs/project/evidence/p05-python/acceptance-binding.json'),
                  'review': artifact('docs/project/evidence/p05-python/binding-acceptance-review.json'),
                  'commands': len(commands), 'artifacts': len(names)}, sort_keys=True))
