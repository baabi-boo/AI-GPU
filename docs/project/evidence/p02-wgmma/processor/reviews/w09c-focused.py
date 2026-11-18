#!/usr/bin/env python3
"""Ten selected Python-only verifier controls; no compiler or processor launch."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import unittest

WORK = Path('${WORK}')
CANDIDATE = WORK / 'verifier-candidate'
REVIEWS = WORK / 'reviews'
TEST_NAMES = (
    'test_real_checkout_inventory_keeps_unused_blackbox_identity_explicit',
    'test_checkout_inventory_rejects_missing_extra_replaced_and_duplicate_inputs',
    'test_nonallowlisted_checkout_inputs_require_execution_identities',
    'test_all_checkout_overlaps_reject_digest_and_size_drift',
    'test_matching_blackbox_execution_identity_does_not_require_unused_body',
    'test_full_original_packet_replays_exact_inventory_and_keeps_acceptance_false',
    'test_source_tool_and_dependency_header_drift_reject',
    'test_missing_helper_fixture_and_retained_source_evidence_reject',
    'test_full_packet_cannot_omit_host_and_both_kernel_source_chains',
    'test_required_consumer_and_helper_source_chains_cannot_be_omitted',
)
blocked_process_attempts = []


def deny_processes(event, args):
    if event in {'subprocess.Popen', 'os.system', 'os.posix_spawn', 'os.spawn', 'os.exec'}:
        blocked_process_attempts.append(event)
        raise RuntimeError('W09C review forbids external process execution: ' + event)


sys.addaudithook(deny_processes)
sys.path.insert(0, str(CANDIDATE / 'ci/project'))
import test_p02_wgmma_packet as tests


def file_identity(path):
    raw = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'size_bytes': len(raw)}


def candidate_identities():
    return [dict(file_identity(CANDIDATE / name), path=name) for name in (
        'ci/project/p02_wgmma_packet.py', 'ci/project/test_p02_wgmma_packet.py')]


class ReviewResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.subtest_records = []

    def addSubTest(self, test, subtest, err):
        self.subtest_records.append({'test': str(subtest), 'outcome': 'pass' if err is None else 'fail'})
        super().addSubTest(test, subtest, err)


data = {'review_id': 'w09c', 'scope': 'five new plus five selected existing/modified verifier tests',
        'started_at': datetime.now(timezone.utc).isoformat(), 'python': sys.version,
        'test_names': ['test_p02_wgmma_packet.PacketTests.' + name for name in TEST_NAMES],
        'candidate_before': candidate_identities(), 'script': file_identity(Path(__file__)),
        'full_suite_invoked': False, 'acceptance_claimed': False,
        'qualifies_P02_A03': False, 'phase_complete': False}
suite = unittest.TestSuite(tests.PacketTests(name) for name in TEST_NAMES)
result = unittest.TextTestRunner(verbosity=2, resultclass=ReviewResult).run(suite)
data.update(tests_run=result.testsRun, subtests=result.subtest_records,
            failure_count=len(result.failures), error_count=len(result.errors), skipped_count=len(result.skipped),
            blocked_process_attempts=blocked_process_attempts, candidate_after=candidate_identities(),
            finished_at=datetime.now(timezone.utc).isoformat())
data['outcome'] = 'pass' if (result.wasSuccessful() and not blocked_process_attempts
    and data['candidate_before'] == data['candidate_after'] and result.testsRun == len(TEST_NAMES)) else 'fail'
(REVIEWS / 'w09c-focused-data.json').write_text(json.dumps(data, indent=2) + '\n')
print(json.dumps({'outcome': data['outcome'], 'tests': data['tests_run'], 'subtests': len(data['subtests']),
                  'failures': data['failure_count'], 'errors': data['error_count']}), flush=True)
sys.exit(data['outcome'] != 'pass')
