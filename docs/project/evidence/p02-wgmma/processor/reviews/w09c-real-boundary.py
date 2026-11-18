#!/usr/bin/env python3
"""Read-only review of the captured W09A snapshot at the checkout binding boundary.

This does not create source_after, run the complete-packet verifier, import
packet-retained Python, compile code, or launch a processor model.
"""

import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

WORK = Path('${WORK}')
CANDIDATE = WORK / 'verifier-candidate'
REVIEWS = WORK / 'reviews'
PACKET = WORK / 'wgmma-gcc12-formal-evidence'
REPORT = REVIEWS / 'w09a-report-partial.json'
EXPECTED_REPORT_SHA256 = 'dd60b9a2037d34b72b407612e89cbf7f4ced3e5dca208c0828e24e1ec23b6ad2'
EXPECTED_SOURCE_SHA256 = '96fabbd00a1fa59a8234530add191ff951c3bd5741509d97df2f8dbb8d9f41f5'
EXPECTED_SOURCE_INPUTS = (
    'VERSION', '.gitmodules', 'configure', 'config.mk.in', 'VX_config.toml',
    'VX_types.toml', 'ci/gen_config.py', 'ci/blackbox.sh',
)
CHECKOUT_ONLY = 'ci/blackbox.sh'

blocked_process_attempts = []


def deny_processes(event, args):
    if event in {'subprocess.Popen', 'os.system', 'os.posix_spawn', 'os.spawn', 'os.exec'}:
        blocked_process_attempts.append(event)
        raise RuntimeError('W09C review forbids external process execution: ' + event)


sys.addaudithook(deny_processes)
sys.path.insert(0, str(CANDIDATE / 'ci/project'))
import baseline_inventory
import p02_wgmma_packet as verifier


def file_identity(path):
    raw = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'size_bytes': len(raw)}


def source_identities():
    names = sorted(set(verifier.HELPERS + (verifier.WITNESS_PARSER,
        'ci/project/p02_wgmma_packet.py', 'ci/project/test_p02_wgmma_packet.py')))
    return [dict(file_identity(CANDIDATE / name), path=name) for name in names]


data = {
    'review_id': 'w09c',
    'scope': 'original captured source_before checkout/execution inventory boundary only',
    'started_at': datetime.now(timezone.utc).isoformat(),
    'full_verifier_invoked': False,
    'final_source_after_synthesized': False,
    'packet_files_modified': False,
    'acceptance_claimed': False,
    'qualifies_P02_A03': False,
    'phase_complete': False,
    'candidate_sources_before': source_identities(),
    'script': file_identity(Path(__file__)),
    'checks': [],
    'failures': [],
}


def check(name, function):
    try:
        result = function()
        data['checks'].append({'name': name, 'outcome': 'pass', 'result': result})
        print('PASS: ' + name, flush=True)
    except Exception as exc:
        failure = {'name': name, 'outcome': 'fail', 'error_type': type(exc).__name__, 'reason': str(exc)}
        data['checks'].append(failure)
        data['failures'].append(failure)
        print('FAIL: ' + name + ': ' + str(exc), flush=True)


def equal(actual, expected):
    verifier.same(actual, expected, 'independent review expectation')
    return actual


def expect_rejection(function, message):
    try:
        function()
    except ValueError as exc:
        if message not in str(exc):
            raise AssertionError('Unexpected rejection: ' + str(exc)) from exc
        return {'error_type': type(exc).__name__, 'reason': str(exc)}
    raise AssertionError('Mutation was accepted')


try:
    raw = REPORT.read_bytes()
    report = verifier.parse_json(raw, 'unchanged W09A captured report')
    data['captured_report'] = file_identity(REPORT)
    equal(data['captured_report']['sha256'], EXPECTED_REPORT_SHA256)
    equal(report['state'], 'running')
    equal('source_after' in report, False)
    equal(tuple(baseline_inventory.SOURCE_INPUTS), EXPECTED_SOURCE_INPUTS)
    with verifier.Reader(PACKET) as reader:
        source = reader.json(report['source_before'])
        data['source_before'] = report['source_before']
        equal(report['source_before']['sha256'], EXPECTED_SOURCE_SHA256)
        original_inputs = source['checkout']['inputs']
        files = verifier.inventory(source['files'], 'actual source files')
        inputs_by_path = verifier.inventory(original_inputs, 'actual checkout inputs')
        blackbox = inputs_by_path[CHECKOUT_ONLY]
        overlap = sorted(set(EXPECTED_SOURCE_INPUTS) - {CHECKOUT_ONLY})
        data['actual_inventory'] = {
            'source_file_count': len(files), 'checkout_input_count': len(original_inputs),
            'checkout_paths': [row['path'] for row in original_inputs],
            'overlap_paths': overlap, 'checkout_only_identity': blackbox,
            'captured_source_revision': source['checkout']['revision'],
            'captured_source_tree': source['checkout']['tree'],
        }
        equal(len(files), 740)
        equal(len(original_inputs), 8)
        equal(sorted(set(inputs_by_path) - set(files)), [CHECKOUT_ONLY])

        def old_rule():
            for row in verifier.inventory(original_inputs, 'old-rule checkout inputs').values():
                verifier.same(row, files.get(row['path']), 'checkout/source input')

        check('original rule still reproduces retained W09A rejection',
              lambda: expect_rejection(old_rule, 'checkout/source input differs'))
        check('unchanged actual snapshot accepted by new boundary with exact identity-only row',
              lambda: equal(verifier.bind_checkout_inputs(original_inputs, files), [blackbox]))

        for path in EXPECTED_SOURCE_INPUTS:
            changed = [copy.deepcopy(row) for row in original_inputs if row['path'] != path]
            check('reject checkout omission: ' + path,
                  lambda changed=changed: expect_rejection(
                      lambda: verifier.bind_checkout_inputs(changed, files), 'checkout input inventory'))

        extra = dict(blackbox, path='ci/unexpected-review-input.sh')
        check('reject extra checkout path', lambda: expect_rejection(
            lambda: verifier.bind_checkout_inputs(copy.deepcopy(original_inputs) + [extra], files),
            'checkout input inventory'))
        replaced = [copy.deepcopy(row) for row in original_inputs if row['path'] != CHECKOUT_ONLY] + [extra]
        check('reject eight-row checkout path substitution', lambda: expect_rejection(
            lambda: verifier.bind_checkout_inputs(replaced, files), 'checkout input inventory'))
        check('reject duplicate checkout identity', lambda: expect_rejection(
            lambda: verifier.bind_checkout_inputs(copy.deepcopy(original_inputs) + [copy.deepcopy(blackbox)], files),
            'repeats a path'))

        for path in overlap:
            omitted = copy.deepcopy(files)
            del omitted[path]
            check('reject missing required execution identity: ' + path,
                  lambda omitted=omitted: expect_rejection(
                      lambda: verifier.bind_checkout_inputs(original_inputs, omitted),
                      'checkout input lacks execution source identity'))
            for field in ('sha256', 'size_bytes'):
                changed = copy.deepcopy(original_inputs)
                row = next(row for row in changed if row['path'] == path)
                row[field] = ('0' * 64 if row[field] != '0' * 64 else '1' * 64) if field == 'sha256' else row[field] + 1
                check('reject overlap ' + field + ' drift: ' + path,
                      lambda changed=changed: expect_rejection(
                          lambda: verifier.bind_checkout_inputs(changed, files), 'checkout/source input'))

        overlapping_blackbox = copy.deepcopy(files)
        overlapping_blackbox[CHECKOUT_ONLY] = copy.deepcopy(blackbox)
        check('matching blackbox overlap is checked and no longer reported outside execution inventory',
              lambda: equal(verifier.bind_checkout_inputs(original_inputs, overlapping_blackbox), []))
        for field in ('sha256', 'size_bytes'):
            changed = copy.deepcopy(overlapping_blackbox)
            changed[CHECKOUT_ONLY][field] = ('0' * 64 if blackbox[field] != '0' * 64 else '1' * 64) if field == 'sha256' else blackbox[field] + 1
            check('reject blackbox overlap ' + field + ' drift',
                  lambda changed=changed: expect_rejection(
                      lambda: verifier.bind_checkout_inputs(original_inputs, changed), 'checkout/source input'))

        for label, updates, reason in (
            ('invalid checkout-only digest', {'sha256': 'invalid'}, 'invalid SHA-256 identity'),
            ('boolean checkout-only size', {'size_bytes': True}, 'invalid file size'),
            ('extra checkout-only identity field', {'unknown': 1}, 'invalid file identity fields'),
        ):
            changed = copy.deepcopy(original_inputs)
            next(row for row in changed if row['path'] == CHECKOUT_ONLY).update(updates)
            check('reject ' + label,
                  lambda changed=changed, reason=reason: expect_rejection(
                      lambda: verifier.bind_checkout_inputs(changed, files), reason))

        check('incomplete actual report still rejected by complete source-stability gate',
              lambda: expect_rejection(
                  lambda: verifier.verify_source(reader, report, report['variants']),
                  'source stability snapshot inventory'))
        reader.recheck()
        data['checked_packet_members'] = reader.inventory()
        data['packet_reader_recheck'] = 'pass'
    equal(file_identity(REPORT), data['captured_report'])
except Exception as exc:
    data['failures'].append({'name': 'audit setup/finalization', 'error_type': type(exc).__name__, 'reason': str(exc)})
    print('FAIL: audit setup/finalization: ' + str(exc), flush=True)

data['candidate_sources_after'] = source_identities()
if data['candidate_sources_after'] != data['candidate_sources_before']:
    data['failures'].append({'name': 'candidate stability', 'reason': 'Candidate source identities changed during audit'})
data['blocked_process_attempts'] = blocked_process_attempts
if blocked_process_attempts:
    data['failures'].append({'name': 'external process execution', 'reason': 'A forbidden process launch was attempted'})
data['finished_at'] = datetime.now(timezone.utc).isoformat()
data['outcome'] = 'pass' if not data['failures'] else 'fail'
data['check_count'] = len(data['checks'])
(REVIEWS / 'w09c-real-boundary-data.json').write_text(json.dumps(data, indent=2) + '\n')
print(json.dumps({'outcome': data['outcome'], 'checks': data['check_count'], 'failures': len(data['failures'])}), flush=True)
sys.exit(bool(data['failures']))
