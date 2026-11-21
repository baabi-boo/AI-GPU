"""Independent BF16 raw-line reconciliation; imports no producer or auditor."""
import hashlib
import json
from pathlib import Path
import struct

ROOT = Path('/workspace/scratch/ba0248fde989/p05-work/ci-e1420fd/simx-bf16/python')
OUT = ROOT.parents[2] / 'w08_a5/manual-reconciliation.json'
AUDIT = ROOT.parents[3] / 'AI-GPU/docs/project/evidence/p05-python/reviews/bf16-dispatch.json'
REVISION = 'e1420fd550f716df33a2556057b7086a03032cbe'
OK = {'validation': 0, 'primary': 0, 'cleanup': 0, 'complete': True}
PY_OK = dict(OK, validation='success')
PENDING = dict(OK, complete=False)
POOL = 0x200000000 - 0x10000
POISONS = (0x7fc0dead, 0xdeadbeef)
MATMULS = ['bf16-' + name for name in ('single-dense_boundaries', 'numerical-cross_tile_rounding_positive', 'multi-dense_boundaries')]
MODELS = ['bf16-' + name for name in ('seeded_dense', 'negated_dense', 'zero', 'signed_basis', 'split_boundary')]

def raw(root, commands, marker):
    answer = []
    for command in commands:
        data = (root / command['log']).read_bytes()
        assert len(data) == command['log_size_bytes']
        assert hashlib.sha256(data).hexdigest() == command['log_sha256']
        for line in data.decode().splitlines():
            if line.startswith(marker + ' '):
                answer.append((command, json.loads(line[len(marker) + 1:])))
    return answer

def memory(row):
    assert row['free_before'] == row['free_after'] > 0
    assert row['used_before'] == row['used_after'] > 0
    assert row['free_before'] + row['used_before'] == POOL
    assert row['free_before'] % 64 == row['used_before'] % 64 == 0

def one_dispatch(row, profiled):
    wire = struct.unpack('<8I3Q', bytes.fromhex(row['argument_bytes']))
    assert wire[:4] == (1, 56, 2, 0) and wire[7] == 0
    m, n, k = wire[4:7]
    assert (m, n, k) in ((8, 4, 8), (8, 4, 16), (16, 8, 16))
    addresses = [row[name + '_address'] for name in ('a', 'b', 'd')]
    lengths = [row[name + '_bytes'] for name in ('a', 'b', 'd')]
    assert tuple(addresses) == wire[8:] and lengths == [m * k * 2, k * n * 2, m * n * 4]
    ranges = sorted(zip(addresses, lengths))
    assert all(start % 64 == 0 and 0x10000 <= start < start + size <= 0x200000000 for start, size in ranges)
    assert all(a + size <= b for (a, size), (b, _) in zip(ranges, ranges[1:]))
    keys = ('writes_enqueued', 'launches_enqueued', 'reads_enqueued', 'wait_calls') if profiled else ('writes', 'launches', 'reads', 'waits')
    assert [row[key] for key in keys] == [3, 1, 1, 1]
    answer = {'h2d': sum(lengths), 'd2h': lengths[2], 'profiles': 5 if profiled else 0}
    if profiled:
        assert row['input_dtype'] == 'bf16' and row['timed_out_waits'] == 0
        assert row['profiling_enabled'] is True and row['event_profile_queried'] == [True] * 5
        assert row['event_results'] == row['event_profile_results'] == [0] * 5
        profiles = row['event_profiles']
        assert len(profiles) == 5
        last_q = last_end = 0
        for event in profiles:
            q, submit, start, end = [event[key] for key in ('queued_ns', 'submit_ns', 'start_ns', 'end_ns')]
            assert last_q <= q <= submit <= start <= end and last_end <= submit
            last_q, last_end = q, end
        answer.update(first=profiles[0]['queued_ns'], last=profiles[-1]['end_ns'])
    else:
        assert not any('profil' in key for key in row)
    return answer

def review(matmuls, models, python):
    assert [(row['case_id'], row['iteration']) for _, row in matmuls] == [(case, iteration) for case in MATMULS for iteration in (0, 1)]
    operations, spans, resources, bridge_boundaries = [], [], [], []
    host = {key: [] for key in ('advance_ns', 'bridge_ns', 'bridge_compare_ns', 'assembly_ns', 'output_compare_ns', 'close_ns')}
    for command, row in matmuls:
        memory(row['resources']); resources.append(row['resources']['used_before'])
        trace = row['trace'] if python else row['dispatch']
        assert trace['poison'] == POISONS[row['iteration']]
        if python:
            assert row['status'] == row['close_status'] == PY_OK
        else:
            assert row['resources']['primary'] == row['resources']['cleanup'] == row['mismatches'] == 0
        operations.append(one_dispatch(trace, python))
    observed = []
    for command, wrapper in models:
        record = wrapper['record'] if python else wrapper
        trace = record['trace']; iteration = record['iteration']
        observed.append((trace['case_id'], iteration))
        assert record['source_revision'] == REVISION and record['backend'] == 'simx'
        assert trace['input_dtype'] == 'bf16' and trace['poison'] == POISONS[iteration]
        assert trace['result'] == {'execution': OK, 'status': 'success', 'terminal': True}
        assert trace['owner_cleanup'] == OK and trace['owner_closed'] is True
        assert all(trace[key] is True for key in ('hidden_valid', 'bridge_attempted', 'bridge_valid', 'bridge_compared', 'assembled', 'logits_valid', 'logits_compared'))
        assert trace['bridge_status'] == trace['bridge_mismatches'] == trace['output_mismatches'] == 0
        assert trace['bridge_checked_words'] == trace['output_checked_words'] == 64
        memory(trace['resources']); resources.append(trace['resources']['used_before'])
        stages = trace['native']
        assert [(row['operation_id'], row['sequence'], row['row_begin'], row['row_end']) for row in stages] == [
            ('hidden_matmul', 0, 0, 16), ('output_rows_0_7', 1, 0, 8), ('output_rows_8_15', 2, 8, 16)]
        bridge = bytes.fromhex(trace['bridge_bytes'])
        assert len(bridge) == 256
        assert trace['hidden_words'] == stages[0]['output_words']
        assert bytes.fromhex(stages[1]['a_bytes']) == bridge[:128]
        assert bytes.fromhex(stages[2]['a_bytes']) == bridge[128:]
        assert trace['output_words'] == stages[1]['output_words'] + stages[2]['output_words']
        event_spans = []
        for stage in stages:
            assert stage['submission'] == PENDING and stage['completion'] == stage['cleanup'] == OK
            assert all(stage[key] is True for key in ('submitted', 'waited', 'trace_valid', 'output_valid', 'compared', 'closed'))
            event = one_dispatch(stage['dispatch'], True)
            assert stage['submit_begin_ns'] <= event['first'] <= stage['submit_end_ns']
            assert stage['dispatch']['poison'] == POISONS[iteration]
            operations.append(event); event_spans.append(event)
        assert trace['create_begin_ns'] <= trace['create_end_ns'] <= event_spans[0]['first']
        assert all(left['last'] <= right['first'] for left, right in zip(event_spans, event_spans[1:]))
        for key in host: host[key].append(trace[key])
        assert trace['advance_ns'] >= sum(trace[key] for key in ('bridge_ns', 'bridge_compare_ns', 'assembly_ns', 'output_compare_ns'))
        span = {'case': trace['case_id'], 'iteration': iteration, 'command': command['id'],
                'begin_ns': trace['create_begin_ns'], 'last_read_ns': event_spans[-1]['last'],
                'close_ns': trace['close_ns'], 'command_ns': round(command['duration_seconds'] * 1e9)}
        assert span['last_read_ns'] - span['begin_ns'] + span['close_ns'] <= span['command_ns']
        spans.append(span)
        bridge_boundaries.append({'case': trace['case_id'], 'iteration': iteration,
                                  'input_row7_last_element': bridge[126:128].hex(), 'input_row8_first_element': bridge[128:130].hex(),
                                  'output_row7_last_word': trace['output_words'][31], 'output_row8_first_word': trace['output_words'][32]})
    assert observed == [(case, iteration) for case in MODELS for iteration in (0, 1)]
    gaps = [right['begin_ns'] - left['last_read_ns'] - left['close_ns'] for left, right in zip(spans, spans[1:]) if left['command'] == right['command']]
    assert gaps and min(gaps) >= 0
    result = {'matmul_runs': len(matmuls), 'model_runs': len(models), 'total_launches': len(operations),
              'event_profile_pairs': sum(row['profiles'] for row in operations),
              'tensor_h2d_bytes': sum(row['h2d'] for row in operations), 'tensor_d2h_bytes': sum(row['d2h'] for row in operations),
              'h2d_transfers': 3 * len(operations), 'd2h_transfers': len(operations),
              'argument_block_bytes': 56 * len(operations), 'host_bridge_bytes': 256 * len(models),
              'host_assembly_bytes': 256 * len(models), 'live_context_used_bytes': sorted(set(resources)),
              'close_to_next_model_gap_ns': {'count': len(gaps), 'minimum': min(gaps), 'maximum': max(gaps)},
              'model_spans': spans, 'bridge_row_boundaries': bridge_boundaries,
              'host_duration_ns': {key: {'count': len(values), 'minimum': min(values), 'maximum': max(values)} for key, values in host.items()}}
    if python:
        result['installed_profile_span_ns'] = operations[-1]['last'] - operations[0]['first']
        result['installed_command_ns'] = spans[-1]['command_ns']
        assert result['installed_profile_span_ns'] <= result['installed_command_ns']
    return result

outer = json.loads((ROOT / 'report.json').read_text())
native = json.loads((ROOT / 'native/report.json').read_text())
groups = [raw(ROOT, outer['commands'], marker) for marker in ('P05_MATMUL', 'P05_MODEL', 'P03_RESULT')]
groups.append(raw(ROOT / 'native', native['commands'], 'P04_RESULT'))
assert [len(group) for group in groups] == [6, 10, 6, 10]
result = {'scope': 'independent BF16 raw-line reconciliation; no auditor or producer imports; no native execution',
          'python': review(groups[0], groups[1], True), 'native_comparison': review(groups[2], groups[3], False),
          'commands': {'outer': len(outer['commands']), 'native': len(native['commands'])}, 'outcome': 'pass', 'acceptance_claimed': False}
audit = json.loads(AUDIT.read_text())
for route in ('python', 'native_comparison'):
    for key in ('matmul_runs', 'model_runs', 'total_launches', 'event_profile_pairs', 'tensor_h2d_bytes', 'tensor_d2h_bytes',
                'h2d_transfers', 'd2h_transfers', 'argument_block_bytes', 'host_bridge_bytes', 'host_assembly_bytes'):
        assert result[route][key] == audit['counts'][route][key]
OUT.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
print(json.dumps({route: {k: v for k, v in result[route].items() if k not in ('model_spans', 'bridge_row_boundaries', 'host_duration_ns')} for route in ('python', 'native_comparison')}, indent=2))
