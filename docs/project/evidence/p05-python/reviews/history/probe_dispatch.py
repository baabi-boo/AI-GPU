#!/usr/bin/env python3
"""Bounded W07 retained-packet counterexamples; executes Python auditors only."""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile


ROOT = Path('/workspace/scratch/ba0248fde989/AI-GPU')
PACKETS = Path('/workspace/scratch/ba0248fde989/p05-work/ci-e1420fd')
HERE = Path(__file__).resolve().parent


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def inventory(root):
    return {str(p.relative_to(root)): sha(p.read_bytes()) for p in sorted(root.rglob('*')) if p.is_file()}


def descriptor(path, data):
    return {'path': path, 'sha256': sha(data), 'size_bytes': len(data)}


def rewire(dispatch):
    dispatch['argument_bytes'] = struct.pack('<8I3Q', 1, 56,
        1 if dispatch.get('input_dtype', 'fp16') == 'fp16' else 2, 0,
        dispatch.get('m', 8), dispatch.get('n', 4), dispatch.get('k', 8), 0,
        *(dispatch[key + '_address'] for key in ('a', 'b', 'd'))).hex()


class Mutation:
    def __init__(self, root, original):
        self.root, self.original = root, original
        self.report = json.loads((original / 'report.json').read_bytes())
        self.native = json.loads((original / 'native/report.json').read_bytes())
        self.observed = json.loads((original / 'artifacts/installed-observations.json').read_bytes())
        self.installed_suffix = b''
        self.extra_commands = []
        self.changed = set()

    def write(self, relative, data):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        self.changed.add(relative)
        return descriptor(relative, data)

    def records(self, relative, marker, rows):
        data = (self.original / relative).read_bytes()
        lines, index = [], 0
        for line in data.splitlines(keepends=True):
            if line.startswith(marker + b' '):
                if index < len(rows):
                    lines.append(marker + b' ' + encoded(rows[index]))
                index += 1
            else:
                lines.append(line)
        lines.extend(marker + b' ' + encoded(row) for row in rows[index:])
        return b''.join(lines)

    def update_log(self, report, command_id, raw, prefix=''):
        command = next(c for c in report['commands'] if c['id'] == command_id)
        desc = self.write(prefix + command['log'], raw)
        command.update(log_sha256=desc['sha256'], log_size_bytes=desc['size_bytes'])

    def flush(self):
        observed = self.observed
        self.report['observations'] = self.write('artifacts/installed-observations.json', encoded(observed))
        raw = (self.original / 'logs/installed-matrix.log').read_bytes()
        rows = iter([('P05_MATMUL', row) for row in observed['matmuls']] +
                    [('P05_MODEL', row) for row in observed['models']])
        lines = []
        for line in raw.splitlines(keepends=True):
            if line.startswith((b'P05_MATMUL ', b'P05_MODEL ')):
                item = next(rows, None)
                if item:
                    lines.append(item[0].encode() + b' ' + encoded(item[1]))
            else:
                lines.append(line)
        lines.extend(marker.encode() + b' ' + encoded(row) for marker, row in rows)
        self.update_log(self.report, 'installed-matrix', b''.join(lines) + self.installed_suffix)
        for case in self.report['native_matmuls']:
            cid = 'native-' + case['id']
            relative = 'logs/' + cid + '.log'
            self.update_log(self.report, cid, self.records(relative, b'P03_RESULT', case['observations']))
        for case in self.native['variants'][0]['cases']:
            cid = 'simx-fp16-' + case['id']
            relative = 'native/logs/' + cid + '.log'
            self.update_log(self.native, cid, self.records(relative, b'P04_RESULT', case['observations']), 'native/')
        for report, command, raw, prefix in self.extra_commands:
            report['commands'].append(command)
            self.update_log(report, command['id'], raw, prefix)
        self.report['native_report'] = self.write('native/report.json', encoded(self.native))
        self.write('report.json', encoded(self.report))

    def restore(self):
        for relative in self.changed:
            original = self.original / relative
            target = self.root / relative
            if original.is_file():
                shutil.copyfile(original, target)
            else:
                target.unlink()


def matmul(p):
    return p.observed['matmuls'][0]


def trace(p):
    return matmul(p)['trace']


def model(p):
    return p.observed['models'][0]['record']['trace']


def stage(p):
    return model(p)['native'][0]


def address(p, key, value):
    trace(p)[key + '_address'] = value
    rewire(trace(p))


def extra_native_command(p):
    command = copy.deepcopy(next(c for c in p.report['commands'] if c['id'].startswith('native-fp16-single')))
    raw = (p.original / command['log']).read_bytes()
    command['id'] = 'native-unaccounted'
    command['log'] = 'logs/native-unaccounted.log'
    index = command['argv'].index('--case')
    command['argv'][index:index + 2] = ['--case=' + command['argv'][index + 1]]
    p.extra_commands.append((p.report, command, raw, ''))


def bridge_inconsistent(p):
    t = model(p)
    word = '3f800000' if t['hidden_words'][0] != '3f800000' else '40000000'
    t['hidden_words'][0] = t['native'][0]['output_words'][0] = word


def impossible_memory(p):
    for key in ('free_before', 'free_after', 'used_before', 'used_after'):
        matmul(p)['resources'][key] = 0


def impossible_final_end(p):
    last = p.observed['models'][-1]['record']['trace']['native'][-1]['dispatch']['event_profiles'][-1]
    last['end_ns'] += 4000 * 10**9


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--auditor', type=Path, default=ROOT / 'docs/project/evidence/p05-python/reviews/audit_dispatch.py')
    parser.add_argument('--receipt', type=Path, required=True)
    args = parser.parse_args()
    if args.receipt.exists():
        raise SystemExit('receipt must be fresh')
    module_spec = importlib.util.spec_from_file_location('review_dispatch', args.auditor)
    audit = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(audit)
    fp16, bf16 = (PACKETS / ('simx-' + fmt) / 'python' for fmt in ('fp16', 'bf16'))
    before = {fmt: inventory(packet) for fmt, packet in (('fp16', fp16), ('bf16', bf16))}
    auditor_before = sha(args.auditor.read_bytes())
    support = audit.load_support(ROOT)
    checks = []

    def run(name, action, reject):
        try:
            value = action()
        except (OSError, ValueError, KeyError, TypeError, OverflowError, IndexError, AttributeError) as error:
            checks.append({'name': name, 'expected': 'reject' if reject else 'pass',
                           'outcome': 'rejected', 'reason': str(error)})
            if not reject:
                raise
            return None
        checks.append({'name': name, 'expected': 'reject' if reject else 'pass',
                       'outcome': 'ACCEPTED_CONTRADICTION' if reject else 'passed'})
        return value

    full = run('complete_real_two_format_control', lambda: audit.audit_packets(ROOT, [fp16, bf16]), False)
    assert full['counts']['combined']['total_launches'] == 144
    assert full['counts']['combined']['event_profile_pairs'] == 660
    assert full['counts']['python']['tensor_h2d_bytes'] == 46848
    assert full['counts']['python']['tensor_d2h_bytes'] == 18432
    selected = run('explicit_selected_scope_control', lambda: audit.audit_packets(ROOT, [fp16], True), False)
    assert selected['full_matrix_checked'] is False and selected['selected_scope'] is True
    assert selected['scope'] == 'incomplete-selected-format-matrix' and selected['phase_acceptance'] is False
    run('implicit_incomplete_scope', lambda: audit.audit_packets(ROOT, [fp16]), True)
    run('duplicate_format', lambda: audit.audit_packets(ROOT, [fp16, fp16]), True)

    probes = [
        ('abi_flags', lambda p: trace(p).update(argument_bytes=trace(p)['argument_bytes'][:24] + '01000000' + trace(p)['argument_bytes'][32:])),
        ('tensor_extent', lambda p: trace(p).update(a_bytes=126)),
        ('address_alignment', lambda p: address(p, 'a', trace(p)['a_address'] + 2)),
        ('address_overlap', lambda p: address(p, 'a', trace(p)['b_address'])),
        ('address_u64_overflow', lambda p: address(p, 'a', 2**64 - 4)),
        ('address_outside_simx_pool', lambda p: address(p, 'a', 2**40)),
        ('address_below_user_pool', lambda p: address(p, 'a', 0)),
        ('profile_event_failure', lambda p: trace(p)['event_results'].__setitem__(2, 1)),
        ('profile_query_failure', lambda p: trace(p)['event_profile_results'].__setitem__(1, 1)),
        ('profile_query_missing', lambda p: trace(p)['event_profile_queried'].__setitem__(3, False)),
        ('profile_event_dependency', lambda p: trace(p)['event_profiles'][1].update(submit_ns=trace(p)['event_profiles'][0]['end_ns'] - 1)),
        ('profile_enqueue_reversed', lambda p: trace(p)['event_profiles'][1].update(queued_ns=trace(p)['event_profiles'][0]['queued_ns'] - 1)),
        ('model_enqueue_outside_submission', lambda p: stage(p)['dispatch']['event_profiles'][0].update(queued_ns=stage(p)['submit_begin_ns'] - 1)),
        ('profile_duration_exceeds_command_timeout', impossible_final_end),
        ('model_host_duration_exceeds_command_timeout', lambda p: model(p).update(advance_ns=4000 * 10**9)),
        ('model_close_overlaps_next_model', lambda p: model(p).update(close_ns=10**9)),
        ('nested_host_duration_exceeds_advance', lambda p: model(p).update(advance_ns=0)),
        ('extra_successful_matmul_wait', lambda p: trace(p).update(wait_calls=2)),
        ('extra_native_p03_wait', lambda p: p.report['native_matmuls'][0]['observations'][0]['dispatch'].update(waits=2)),
        ('model_submission_claims_complete', lambda p: stage(p)['submission'].update(complete=True)),
        ('operation_close_incomplete', lambda p: matmul(p)['close_status'].update(complete=False)),
        ('model_stage_cleanup_error', lambda p: stage(p)['cleanup'].update(cleanup=1)),
        ('model_owner_cleanup_error', lambda p: model(p)['owner_cleanup'].update(cleanup=1)),
        ('memory_baseline_not_restored', lambda p: matmul(p)['resources'].update(used_after=0)),
        ('memory_impossible_zero_capacity', impossible_memory),
        ('model_frozen_weight_replaced', lambda p: stage(p).update(b_bytes='00' * stage(p)['b_size'])),
        ('actual_hidden_bridge_disagrees', bridge_inconsistent),
        ('model_stage_reordered', lambda p: model(p)['native'].reverse()),
        ('model_output_assembly_disagrees', lambda p: model(p)['output_words'].__setitem__(0, '7fc00000')),
        ('duplicate_matmul_membership', lambda p: p.observed['matmuls'].__setitem__(1, copy.deepcopy(p.observed['matmuls'][0]))),
        ('missing_model_membership', lambda p: p.observed['models'].pop()),
        ('python_count_forged', lambda p: p.observed['counts'].update(total_launches=37)),
        ('native_count_forged', lambda p: p.report['native_counts'].update(total_launches=37)),
        ('native_model_traffic_forged', lambda p: p.native.update(tensor_h2d_bytes=p.native['tensor_h2d_bytes'] + 4)),
        ('additional_native_equals_case_invocation', extra_native_command),
        ('explicit_fallback_in_execution_log', lambda p: setattr(p, 'installed_suffix', b'CPU matmul fallback executed for fp16-single-dense_boundaries\n')),
        ('phase_acceptance_claim', lambda p: p.report.update(acceptance_claimed=True)),
    ]
    with tempfile.TemporaryDirectory(prefix='w07-a2-packet-', dir=HERE) as temporary:
        copy_root = Path(temporary) / 'fp16'
        shutil.copytree(fp16, copy_root)
        for name, mutation in probes:
            packet = Mutation(copy_root, fp16)
            mutation(packet)
            packet.flush()
            changed = {name: sha((copy_root / name).read_bytes()) for name in sorted(packet.changed)}
            run(name, lambda: audit.audit_packet(copy_root, support), True)
            checks[-1]['mutated_members'] = changed
            packet.restore()
        fresh = Path(temporary) / 'exclusive-output.json'
        cmd = [sys.executable, '-B', str(args.auditor), '--source-dir', str(ROOT),
               '--packet', str(fp16), '--selected-scope', '--output', str(fresh)]
        first = subprocess.run(cmd, capture_output=True, check=False, timeout=30)
        assert first.returncode == 0, first.stdout + first.stderr
        initial_output = fresh.read_bytes()
        second = subprocess.run(cmd, capture_output=True, check=False, timeout=30)
        assert second.returncode == 2 and fresh.read_bytes() == initial_output
        checks.append({'name': 'fresh_output_and_refuse_overwrite', 'expected': 'pass', 'outcome': 'passed'})

    after = {fmt: inventory(packet) for fmt, packet in (('fp16', fp16), ('bf16', bf16))}
    assert before == after, 'original packet bytes changed'
    auditor_after = sha(args.auditor.read_bytes())
    assert auditor_before == auditor_after, 'auditor changed during review; rerun on stable revision'
    receipt = {'scope': 'W07 adversarial retained-data review; Python auditor only; no native execution or acceptance',
               'auditor_sha256_before': auditor_before, 'auditor_sha256_after': auditor_after,
               'counts': full['counts'], 'selected_scope': {k: selected[k] for k in ('scope', 'selected_scope', 'full_matrix_checked', 'phase_acceptance')},
               'packet_inventory_sha256_before': {fmt: sha(encoded(inv)) for fmt, inv in before.items()},
               'packet_inventory_sha256_after': {fmt: sha(encoded(inv)) for fmt, inv in after.items()},
               'original_file_counts': {fmt: len(inv) for fmt, inv in before.items()},
               'checks': checks,
               'accepted_contradictions': [c['name'] for c in checks if c['outcome'] == 'ACCEPTED_CONTRADICTION']}
    args.receipt.write_bytes(encoded(receipt))
    print(json.dumps({k: receipt[k] for k in ('auditor_sha256_before', 'counts', 'accepted_contradictions')}, indent=2))


if __name__ == '__main__':
    main()
