#!/usr/bin/env python3
"""Materialize the final auditor review from static inspection and reconciliation."""
import hashlib
import json
from pathlib import Path

ROOT = Path('/workspace/scratch/ba0248fde989/AI-GPU')
WORK = ROOT.parent / 'p05-work/w10_a3'
EVIDENCE = ROOT / 'docs/project/evidence/p05-python'
check = json.loads((WORK / 'reconciliation.json').read_text())

def identity(path, published=None):
    raw = path.read_bytes()
    return {'path': published or str(path.relative_to(ROOT)),
            'sha256': hashlib.sha256(raw).hexdigest(), 'size_bytes': len(raw)}

def retained(name):
    return identity(WORK / name, 'docs/project/evidence/p05-python/development/qualification/w10_a3/' + name)

def obligation(name, source, assessment, evidence, limits=None):
    row = {'obligation': name, 'source_anchors': source, 'assessment': assessment,
           'evidence': evidence, 'disposition': 'satisfied_in_reviewed_scope', 'confidence': 'high'}
    if limits:
        row['limits'] = limits
    return row

review = {
    'schema_version': 1,
    'record_id': 'p05-final-independent-auditor-review-v1',
    'reviewer': '/root/w10_a3_final_auditor_review',
    'assignment': {'wave': 10, 'assignment': 3, 'distinct_agent': 57},
    'outcome': 'pass',
    'disposition': 'bounded_independent_technical_approval',
    'scope': 'Static review of retained numerical, dispatch, provenance auditors and pinned extraction; reconciliation of existing W07 counterexamples, W08 selected reports, W09 full reports and relocated replay',
    'source_revision': check['source_revision'],
    'source_tree': check['source_tree'],
    'acceptance_claimed': False,
    'phase_complete': False,
    'human_approval_claimed': False,
    'waivers_requested_or_granted': [],
    'unresolved_findings': [],
    'unresolved_f2_f3': 0,
    'current_auditor_and_extractor_sha256': check['current_source_pins'],
    'initial_auditor_sha256': check['initial_source_pins'],
    'p04_helpers': check['p04_helper_pins_checked_against_git'],
    'independence': {
        'final_reviewer_authored_reviewed_sources': False,
        'final_reviewer_edited_reviewed_sources': False,
        'authors': {'numerics': '/root/w06_a4_numerical_auditor',
                    'dispatch': '/root/w06_a5_dispatch_auditor',
                    'provenance': 'W06 A6, distinct agent 36'},
        'adversarial_reviewers': {'numerics': '/root/w07_a1_numerical_adversarial_review',
                                'dispatch': '/root/w07_a2_dispatch_adversarial_review',
                                'provenance': 'W07 A3, distinct agent 39'},
        'repairs': {'numerics': 'Root; independently rechecked by W07 A1.',
                    'dispatch': 'Root fixed legitimate multiline argv; W07 A4 repaired semantic checks; W07 A2 independently repeated the unchanged probes.',
                    'provenance': 'Root; independently rechecked by W07 A3, including the corrected same-case tool-drift namespace refresh.'},
        'evidence': ['development/w06_a4.md', 'development/w06_a5.md', 'development/w06_a6.md',
                     'development/w07_a1.md', 'development/w07_a2.md', 'development/w07_a3.md', 'development/w07_a4.md'],
        'assessment': 'Distinct implementation, adversarial, formal packet and final reviewer assignments are evidenced. The final reviewer inspected current bodies and initial-to-current changes and reconciled preserved reports without importing the audited implementations.',
        'limits': 'This is agent-role separation within one shared workspace/tool environment, not external human review or independent execution attestation. All three auditors explicitly reuse separate, whole-body-pinned accepted P04 helpers; numerical and dispatch obligations overlap and are complementary. W07 numerical review adds an independent Fraction/struct arithmetic control without producer/auditor imports.'
    },
    'reviewed_obligations': [
        obligation('Complementary numerical, dispatch and provenance obligations',
            ['reviews/README.md', 'audit_numerics.py:main', 'audit_dispatch.py:audit_packets', 'audit_provenance.py:main'],
            'A numerical pass alone does not establish exact lifecycle, timing or compiler/package provenance. Dispatch strengthens wait/submission/allocator checks; provenance binds exact source, package, commands and environment. All three report explicit scope and no phase acceptance, require both distinct formats by default, and label deliberate selected-format operation incomplete.',
            ['All six W08 selected reports have incomplete scope and equal corresponding W09 packet results.', 'W09 full flags are full_matrix_verified, full_matrix_checked and full_matrix respectively; all are true.', 'W09 dispatch aggregation-wrapper field mismatch is preserved as wrapper failure, not an auditor failure or rerun.']),
        obligation('Exact case, iteration, raw observation and command/log membership',
            ['audit_numerics.py:commands,command_log,raw_rows', 'audit_dispatch.py:commands,command_membership,raw_rows,audit_packet', 'audit_provenance.py:commands,command_contract,installed_check'],
            'The fixed three matmul cases, five model cases, two ordered repetitions and six-matmul/ten-model installed raw sequence are checked against frozen inputs and retained observations. All declared logs are bounded and hash-verified. Numerical and dispatch checks close the log-directory inventory; dispatch and provenance require exact ordered 12 outer/15 native commands per format. Malformed reserved prefixes in designated execution logs reject before parsing; numerical records in auxiliary logs and explicit auxiliary runtime failures reject.',
            ['W07 numerical malformed-prefix and auxiliary-record false accepts now reject.', 'W07 dispatch extra equals-form native command now rejects against exact command membership.', 'W07 provenance rehashed auxiliary P05_FAILURE now rejects.', 'Raw/JSON disagreement, missing/duplicate/extra cases and synchronized count overclaims remain rejected in preserved probes.']),
        obligation('Independent numerical values and live intermediate lineage',
            ['audit_numerics.py:fixtures,matmul,model,packet', 'audit_dispatch.py:bridge_from_actual,audit_model'],
            'Standalone actual FP32 words compare with hash-frozen P02 references, while the pinned P04 mathematical helper recomputes model dot products and checks actual hidden values, exact ReLU/conversion bridge bytes, dependent operands and row assembly. The comparison requires both native/Python routes to agree, and independent expected values prevent two equally corrupted routes from passing.',
            ['W07 synchronized hidden/bridge/input/output substitutions reject.', 'The retained independent Fraction/struct control reproduced 40 model records, 7680 stage words, 10240 bridge bytes and 2560 assembled words.', 'W09 totals are 144 launches, 660 profiles, 1536 standalone words and 7680 model-stage output words.'],
            ['Standalone uploads are not separately retained; frozen request and source provenance remain necessary.', 'Equal retained bytes do not alone identify the host pointer that supplied them.']),
        obligation('Allocator, asynchronous state, waits and cleanup',
            ['audit_dispatch.py:NATIVE_PINS,ALLOCATOR_PINS,memory_capacity,memory_restored,audit_abi,audit_model'],
            'Pinned RV64 non-VM SimX definitions constrain 64-byte-aligned, disjoint allocation spans to [0x10000,0x200000000). Free plus used must equal 8589869056 bytes, with live allocated space and sufficient capacity. ABI encoding is exact 56-byte little-endian <8I3Q; three writes, one launch and one read are required. Successful profiled waits equal timeouts plus one, native P03 waits equal one, successful submissions remain incomplete until completion, and completion/close/resource-restoration statuses must succeed.',
            ['All address-outside/below-pool, zero-capacity, extra-wait and premature-complete W07 counterexamples reject on current source.', 'Allocator/native body hashes remain pinned and effective macro observations require RV64 and disabled VM.'],
            ['Per-operation restoration does not prove exhaustive heap leak freedom.', 'There is no separate top-level Session.close status observation.']),
        obligation('Timing consistency and dispatch claim boundaries',
            ['audit_dispatch.py:command_duration_ns,CommandTiming,audit_profiles,audit_model,commands'],
            'Same-process enqueue/dependency/event chronology is ordered; stage compare/release/bridge lower bounds precede dependent submission, final work plus close precedes the next model, and first-to-last spans plus disjoint host durations fit the enclosing monitored command with a conservative 1 ms serialization allowance. Overlapping wait/event/advance categories are not added as independent costs. Explicit affirmative CPU/host matmul fallback diagnostics reject; findings correctly claim required native dispatch rather than absence of every possible unrecorded host computation.',
            ['All three oversized event/advance/close W07 counterexamples reject.', 'The explicit fallback diagnostic now rejects and the broad unsupported no-fallback assertion was narrowed.'],
            ['Separate process clocks are not aligned; this is host simulator timing and not physical GPU latency, throughput, bandwidth or speedup.']),
        obligation('Git source, helper and compiled package identities',
            ['audit_numerics.py:fixtures', 'audit_dispatch.py:load_support,source_identity', 'audit_provenance.py:Git,load_p04,imported_helpers,source_check,bundle_check,pin_header,package_check'],
            'P04 helper bodies must match their explicit hashes before execution. Provenance uses read-only Git objects with replacement objects and lazy fetch disabled, verifies commit/tree and exact retained source/helper closure, and binds all 22 package inputs, canonical source inventory, generated native pin header, six-artifact bundle, wheel build tag and embedded extension pins. No P05 producer, record validator, package module or native binary is imported by the auditors.',
            ['The three helper bodies hash-match both the current checkout and exact e1420fd Git blobs in this reconciliation.', 'W07 retained-source, source-in-sdist/wheel, compiled-pin and helper substitutions reject.', 'AST import inspection found only standard-library imports in all four reviewed utilities.'],
            ['Hash-bound producer observations are not authenticated native execution or reproducible transitive compilation.', 'Submodule/system/tool-support bodies omitted from retained inputs are identified, not reconstructed.']),
        obligation('Bounded archive and installed RECORD verification',
            ['audit_provenance.py:archive,check_record,package_check,elf'],
            'Sdist/wheel members are parsed from verified retained bytes with count/expanded-size limits, canonical names, unique membership, no links/special members/encryption and no file/directory collisions. Exact source and pin inventories are required. Wheel and installed RECORD rows uniquely cover every file with SHA-256 and exact size; RECORD itself has empty hash/size. Installed before/after trees, wheel payload, installer metadata, direct wheel URL, ELF machine/class/dependency/search-path observations and compiled pins are reconciled without loading code.',
            ['Preserved W07 traversal/link/duplicate/source/dependency/ELF/pin/RECORD/installed-drift cases reject.', 'W09 provenance passes for both formats with exact copied external installation identities.'],
            ['Reported RUNPATH and external system dependencies remain visible limitations; no manylinux, arbitrary-host portability or native relocation claim follows.']),
        obligation('Exact PATH, resource and deadline contracts',
            ['audit_provenance.py:base_environment,check_command,command_contract,commands,audit_packet.resource_contract', 'audit_dispatch.py:commands,command_duration_ns'],
            'Provenance derives PATH from optional recorded host_bin, recorded interpreter parent, /usr/bin and /bin in source order with deduplication, and compares complete environments/argv/cwd. It enforces literal probe/header/version/venv/configure deadlines plus shared bounded build/run groups and installed timeout 16*run+60. Both outer and original-native budgets require 4 GiB RSS, 16 MiB logs, 15 GiB initial disk reserve and 1-2 jobs; package jobs equal one; pre-run memory is at least 4 GiB. Source duration checks and dispatch duration checks complement each other.',
            ['All six original provenance false accepts are resolved.', 'Provenance allows at most 10 s monitor/serialization slack; dispatch supplies the tighter 1 ms command-duration bound for these same frozen packets.', 'W07 genuine GEM5_REV source key is accepted after fixing the VERSION identifier grammar; legitimate multiline Python -c source is accepted after separating argv and path grammars.']),
        obligation('Pinned extraction, fresh outputs and relocated replay',
            ['extract_retained.py', 'audit_numerics.py:main', 'audit_dispatch.py:main', 'audit_provenance.py:root_path,main'],
            'Extractor pins the exact index and two archive identities, reads each archive once and parses those bytes through BytesIO, checks exact 304-member inventories and every member size/hash before creating output. Canonical regular paths, unique relative names, no links/encryption, bounded expansion and exclusive fresh destination/file creation preserve all members including hidden stamps. Auditor output paths are fresh and outside input packets; existing outputs are preserved in the supported sequential workflow.',
            ['Independent reconciliation hashes both unchanged archives and the index.', 'Prior relocated extraction plus all three audits exited zero; 608 members and all six hidden .config.stamp copies are accounted for.', 'Three prior extraction negatives exited two: existing destination preserved, changed index rejected before output, changed archive rejected before output.', 'All three replay reports exactly equal W09 full reports after only the two extracted packet-root prefixes are normalized.', 'Preserved numerical/dispatch/provenance controls require explicit selected scope and reject incomplete default/duplicate formats or existing output.'],
            ['This fixed retained-archive utility is not a general ZIP extractor or hostile-concurrent-filesystem sandbox.', 'Provenance replay still requires exact retained source Git objects; replay did not execute native code.'])
    ],
    'historical_repairs': check['historical_repairs'],
    'history_totals': {'numerics': {'cases': 24, 'positive_controls': 2, 'rejections': 22, 'repaired_false_accepts': 2},
                      'dispatch': {'cases': 42, 'positive_controls': 3, 'rejections': 39, 'repaired_false_accepts': 11},
                      'provenance': {'semantic_cases': 26, 'cli_controls': 4, 'repaired_false_accepts': 6}},
    'verification': {
        'kind': 'read_only_reconciliation_of_existing_results_and_source_identity',
        'command': ['python3', '-B', str(WORK / 'reconcile_existing.py'), str(WORK / 'reconciliation.json')],
        'cwd': str(ROOT), 'exit_code': 0,
        'script': retained('reconcile_existing.py'), 'result': retained('reconciliation.json'), 'log': retained('reconciliation.log'),
        'reviewed_input_files': len(check['reviewed_files']), 'reviewed_inputs_unchanged': True,
        'selected_results_reconciled': 6, 'complete_and_relocated_equalities': 3,
        'new_counterexample_cases': 0, 'auditor_or_matrix_reruns': 0, 'native_or_full_suite_runs': 0,
        'initial_wrapper_failure': {'exit_code': 1, 'source': retained('reconcile_existing-initial.py'),
            'log': retained('reconciliation-initial.log'),
            'reason': 'The review wrapper initially expected the extractor hash in reviews/README.md, whose table lists only the three auditors.',
            'correction': 'Restricted that README-table assertion to the three auditors. The extractor hash remains independently pinned and checked against relocated replay before/after descriptors. No reviewed script or evidence was edited.'}
    },
    'evidence': check['reviewed_files'],
    'acceptance_boundary': {
        'P05_A01': 'Existing separate scoped SimX/plain-Python acceptance is neither expanded nor reissued by this review.',
        'P05': 'Remains in_progress; this review is not phase completion.',
        'P05_A02_A03': 'No PyTorch custom operator or framework qualification follows.',
        'hardware': 'No vendor hw_emu, FPGA/silicon or inherited DSP-area finding is resolved here.'
    },
    'limitations': [
        'Static source and preserved-record review plus bounded read-only reconciliation; no new auditor matrix, probe, native execution, package installation or full suite.',
        'The 92 existing semantic/control outcomes and four provenance CLI controls are bounded examples, not exhaustive parser/state/path proof.',
        'Consistency of retained records does not authenticate the originating runner, exclude unrecorded host computation or identify original memory pointers.',
        'Trusted builder and non-hostile filesystem are explicit; path and exclusive-create checks are not a sandbox against malicious concurrent replacement.',
        'The original ZIP includes duplicate retained native comparison packets; those bytes are not additional executions and were not double-counted.',
        'Source/tool/library identities, ELF records and compiled pins do not establish byte-reproducible compilation or archived transitive toolchain/system closure.',
        'No human approval, exception, waiver, acceptance transition, release or branch publication is performed by this reviewer.'
    ]
}
target = EVIDENCE / 'final-auditor-review.json'
with target.open('x') as stream:
    json.dump(review, stream, indent=2, sort_keys=True)
    stream.write('\n')
print(json.dumps(identity(target), sort_keys=True))
