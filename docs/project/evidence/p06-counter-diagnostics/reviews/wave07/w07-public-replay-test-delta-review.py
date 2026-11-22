"""Independent read-only probes of agent 41's test delta; no native packet."""

import ast
import builtins
from contextlib import ExitStack
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest import mock

import test_p06_counter_public_records as records_fixture
import test_p06_counter_public_replay as replay_tests


REPO = Path('/workspace/scratch/98908dfa3444/AI-GPU')
SCRATCH = REPO.parent
TEST_FILE = REPO / 'ci/project/test_p06_counter_public_replay.py'
BEFORE = SCRATCH / 'w07-public-replay-integration-tests-before.py'
METHODS = (
    'test_suppressed_dma_requires_original_ram_and_complemented_attempt',
    'test_terminal_counters_components_halves_and_clock_are_verified',
    'test_terminal_requires_exclusive_ownership_retired_cp_and_destruction',
    'test_overflow_requires_original_callback_and_fresh_context_evidence',
    'test_observation_types_keys_and_integer_bounds_are_strict',
    'test_public_result_duplicate_keys_numbers_and_record_boundaries_are_strict',
)
old_text, new_text = BEFORE.read_text(), TEST_FILE.read_text()


def source_function(text, name):
    return ast.get_source_segment(text, next(node for node in ast.parse(text).body
        if isinstance(node, ast.FunctionDef) and node.name == name))


assert source_function(old_text, 'successful_original') == source_function(new_text, 'successful_original')
initial_sha256 = hashlib.sha256(TEST_FILE.read_bytes()).hexdigest()


class RawMutationAudit(unittest.TestCase):
    """Only raw logs/observations exist here; there is no complete archive or pass report."""
    mutations = []

    def setUp(self):
        self.original = {}
        report = {'commands': [], 'cells': []}
        for mode in replay_tests.replay.MODES:
            value = records_fixture.result(mode)
            text = records_fixture.output(value)
            replay_tests.replay.public_records.verify_output(text, mode)
            body = text.encode()
            log = 'logs/public-' + mode + '.log'
            self.original[replay_tests.PREFIX + log] = body
            report['commands'].append({'id': 'public-' + mode, 'log': log,
                'log_sha256': hashlib.sha256(body).hexdigest(), 'log_size_bytes': len(body)})
            report['cells'].append({'mode': mode, 'observations': value})
        self.original[replay_tests.REPORT] = replay_tests.encoded(report)

    def reject(self, members, pattern='.', **_kwargs):
        changed = [(name, body) for name, body in members.items()
                   if name.endswith('.log') and body != self.original[name]]
        self.assertEqual(len(changed), 1)
        name, body = changed[0]
        mode = name.rsplit('/public-', 1)[1][:-4]
        with self.assertRaisesRegex(ValueError, pattern) as rejected:
            replay_tests.replay.public_records.verify_output(body.decode(), mode)
        self.mutations.append({'method': self._testMethodName, 'mode': mode,
            'changed_raw_bytes': True, 'rejection': str(rejected.exception)})

    reject_observation = replay_tests.OriginalPublicReplayTests.reject_observation


for method in METHODS:
    setattr(RawMutationAudit, method, getattr(replay_tests.OriginalPublicReplayTests, method))


class GuardAudit(unittest.TestCase):
    def test_value_guard_distinguishes_bool_from_int_and_rejects_existing_value(self):
        value = {'checked': True}
        with self.assertRaisesRegex(AssertionError, 'did not change'):
            replay_tests.replace(value, ('checked',), True)
        replay_tests.replace(value, ('checked',), 1)
        self.assertIs(type(value['checked']), int)
        with self.assertRaises(KeyError):
            replay_tests.replace(value, ('obsolete_field',), 1)

    def test_payload_guard_rejects_unchanged_bytes(self):
        members = {replay_tests.PREFIX + 'body': b'retained'}
        with self.assertRaisesRegex(AssertionError, 'did not change'):
            replay_tests.replace_payload(members, 'body', b'retained')

    def test_build_guard_rejects_unchanged_selected_command(self):
        body = b'g++ -c source.cpp -o source.o\n'
        members = {replay_tests.PREFIX + 'logs/build.log': body,
            replay_tests.REPORT: replay_tests.encoded({'commands': [{'id': 'build', 'log': 'logs/build.log'}]})}
        with self.assertRaisesRegex(AssertionError, 'did not change'):
            replay_tests.alter_build(members, 'build', lambda line: True, lambda line: line)


class Result(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.subtests = 0

    def addSubTest(self, test, subtest, error):
        self.subtests += 1
        super().addSubTest(test, subtest, error)


suite = unittest.TestSuite((unittest.defaultTestLoader.loadTestsFromTestCase(RawMutationAudit),
                          unittest.defaultTestLoader.loadTestsFromTestCase(GuardAudit)))
stream = io.StringIO()
with ExitStack() as guards:
    for owner, name in ((builtins, 'open'), (io, 'open'), (os, 'open'), (Path, 'open'),
                        (subprocess, 'run'), (subprocess, 'Popen'),
                        (replay_tests.replay, 'replay_archive')):
        guards.enter_context(mock.patch.object(owner, name, side_effect=AssertionError('forbidden IO/execution: ' + name)))
    result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=Result).run(suite)
after_sha256 = hashlib.sha256(TEST_FILE.read_bytes()).hexdigest()
record = {'reviewed_sha256': initial_sha256, 'after_sha256': after_sha256,
    'sources_unchanged': initial_sha256 == after_sha256,
    'genuine_original_intake_function_unchanged': True,
    'methods_run': result.testsRun, 'subtests_run': result.subtests,
    'raw_mutations_rejected': len(RawMutationAudit.mutations),
    'failures': len(result.failures), 'errors': len(result.errors), 'skips': len(result.skipped),
    'native_execution': 'not_run', 'synthetic_native_archive_created': False,
    'mutations': RawMutationAudit.mutations}
(SCRATCH / 'w07-public-replay-test-delta-review.log').write_text(stream.getvalue())
(SCRATCH / 'w07-public-replay-test-delta-review.json').write_text(json.dumps(record, indent=2) + '\n')
print(stream.getvalue(), end='')
print(json.dumps({key: value for key, value in record.items() if key != 'mutations'}, indent=2))
raise SystemExit(0 if result.wasSuccessful() and initial_sha256 == after_sha256 else 1)
