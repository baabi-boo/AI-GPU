"""Independent host-only counterexamples, using copies of an actual packet.

No simulator is run and no copied mutation is native evidence.
"""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import tempfile

ROOT = Path('/workspace/scratch/6ae68c392555/AI-GPU')
SCRIPT = ROOT / 'docs/project/evidence/p04-executor/reviews/audit_dispatch.py'
PACKET = ROOT.parent / 'p04-native-f4c6a3/simx-fp16/model'
spec = importlib.util.spec_from_file_location('dispatch_review', SCRIPT)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
report = json.loads((PACKET / 'report.json').read_bytes())
variant = report['variants'][0]
case = variant['cases'][0]
base = case['observations'][0]
results = []


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_record(name, mutate, expected):
    row = copy.deepcopy(base)
    mutate(row)
    try:
        audit.audit_record(row, case_id=case['id'], backend=variant['backend'],
                           fmt=variant['format'], revision=row['source_revision'],
                           binding=variant['qualification_id'], iteration=0, statistics={})
        actual, reason = 'accepted', None
    except (ValueError, KeyError, TypeError, OverflowError) as error:
        actual, reason = 'rejected', str(error)
    assert actual == expected, (name, actual, reason)
    results.append(dict(probe=name, layer='record', outcome=actual, reason=reason))


def addresses(row, values):
    d = row['trace']['native'][0]['dispatch']
    d.update(zip(('a_address', 'b_address', 'd_address'), values))
    d['argument_bytes'] = struct.pack('<8I3Q', 1, 56, 1, 0, 16, 8, 16, 0, *values).hex()


def reverse_queued(row):
    profiles = row['trace']['native'][0]['dispatch']['event_profiles']
    profiles[0]['queued_ns'], profiles[1]['queued_ns'] = profiles[1]['queued_ns'], profiles[0]['queued_ns']


def zero_durations(row):
    t = row['trace']
    for key in ('create_begin_ns', 'create_end_ns', 'advance_ns', 'bridge_ns',
                'bridge_compare_ns', 'assembly_ns', 'output_compare_ns', 'close_ns'):
        t[key] = 0
    for stage in t['native']:
        for key in ('submit_begin_ns', 'submit_end_ns', 'wait_ns', 'compare_ns', 'close_ns'):
            stage[key] = 0
        for profile in stage['dispatch']['event_profiles']:
            profile.update({key: 0 for key in profile})


def nested_sum(row):
    t = row['trace']
    for stage in t['native']:
        stage['wait_ns'] = t['advance_ns'] // 2


run_record('observed_zero_durations', zero_durations, 'accepted')
run_record('adjacent_nonoverlapping_ranges_repacked_abi', lambda r: addresses(r, (4096, 4608, 4864)), 'accepted')
run_record('range_ending_at_uint64_max_repacked_abi', lambda r: addresses(r, (4096, 8192, (1 << 64) - 512)), 'accepted')
run_record('range_overflow_repacked_abi', lambda r: addresses(r, (4096, 8192, (1 << 64) - 508)), 'rejected')
run_record('four_byte_alias_repacked_abi', lambda r: addresses(r, (4096, 4604, 8192)), 'rejected')
run_record('advance_zero_positive_nested_duration', lambda r: r['trace'].__setitem__('advance_ns', 0), 'accepted')
run_record('disjoint_nested_sum_exceeds_advance', nested_sum, 'accepted')
run_record('reverse_sequential_enqueue_timestamps', reverse_queued, 'accepted')


def run_packet(name, mutate):
    with tempfile.TemporaryDirectory(prefix='w08c-mutated-' + name + '-', dir=ROOT.parent) as temp:
        target = Path(temp) / 'model'
        shutil.copytree(PACKET, target)
        modified = copy.deepcopy(report)
        c = modified['variants'][0]['cases'][0]
        mutate(c['observations'][0])
        command = next(cmd for cmd in modified['commands']
                       if cmd['id'] == variant['id'] + '-' + c['id'])
        log_path = target / command['log']
        lines = log_path.read_text().splitlines()
        record_index = 0
        for index, line in enumerate(lines):
            if line.startswith('P04_RESULT '):
                lines[index] = 'P04_RESULT ' + json.dumps(c['observations'][record_index], separators=(',', ':'))
                record_index += 1
        assert record_index == 2
        log = ('\n'.join(lines) + '\n').encode()
        log_path.write_bytes(log)
        command.update(log_sha256=hashlib.sha256(log).hexdigest(), log_size_bytes=len(log))
        (target / 'report.json').write_text(json.dumps(modified, indent=2, sort_keys=True) + '\n')
        audited = audit.audit_packets([target], allow_partial=True)
        assert audited['outcome'] == 'pass'
        results.append(dict(probe=name, layer='packet_with_rehashed_matching_raw_log', outcome='accepted',
                            phase_acceptance=audited['phase_acceptance'],
                            mutated_report_sha256=digest(target / 'report.json'),
                            mutated_log_sha256=digest(log_path)))


run_packet('advance_zero_positive_nested_duration', lambda r: r['trace'].__setitem__('advance_ns', 0))
run_packet('disjoint_nested_sum_exceeds_advance', nested_sum)
run_packet('reverse_sequential_enqueue_timestamps', reverse_queued)

original = audit.audit_packets([PACKET], allow_partial=True)
encoded = (json.dumps(original, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()
assert encoded == (ROOT / 'docs/project/evidence/p04-executor/reviews/simx-fp16-dispatch.json').read_bytes()
print(json.dumps(dict(script_sha256=digest(SCRIPT), packet_report_sha256=digest(PACKET / 'report.json'),
                     original_selected_result_sha256=hashlib.sha256(encoded).hexdigest(), probes=results), indent=2))
