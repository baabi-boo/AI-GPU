#!/usr/bin/env python3
"""Bounded W07 auditor review on full copies of retained P05 packets."""
import argparse
import copy
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys


BASE = Path('/workspace/scratch/ba0248fde989')
SOURCE = BASE / 'AI-GPU'
RETAINED = BASE / 'p05-work/ci-e1420fd'
DEFAULT_AUDITOR = SOURCE / 'docs/project/evidence/p05-python/reviews/audit_numerics.py'
FORMATS = ('fp16', 'bf16')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded(value))


def descriptor(root, name):
    data = (root / name).read_bytes()
    return {'path': name, 'size_bytes': len(data), 'sha256': sha(data)}


def inventory(root):
    return {str(p.relative_to(root)): sha(p.read_bytes()) for p in sorted(root.rglob('*')) if p.is_file()}


def log_replace(data, marker, rows):
    rendered = [marker + ' ' + json.dumps(row, separators=(',', ':')) for row in rows]
    result, inserted = [], False
    for line in data.decode().splitlines():
        if line.startswith(marker + ' '):
            if not inserted:
                result.extend(rendered)
                inserted = True
        else:
            result.append(line)
    assert inserted
    return ('\n'.join(result) + '\n').encode()


class Packet:
    def __init__(self, root):
        self.root = root
        self.report = json.loads((root / 'report.json').read_bytes())
        self.observed = json.loads((root / 'artifacts/installed-observations.json').read_bytes())
        self.native = json.loads((root / 'native/report.json').read_bytes())

    def log(self, report, root, identifier, data):
        command = next(row for row in report['commands'] if row['id'] == identifier)
        (root / command['log']).write_bytes(data)
        command.update(log_sha256=sha(data), log_size_bytes=len(data))

    def save_observed(self, sync_raw=True):
        save(self.root / 'artifacts/installed-observations.json', self.observed)
        self.report['observations'] = descriptor(self.root, 'artifacts/installed-observations.json')
        if sync_raw:
            data = (self.root / 'logs/installed-matrix.log').read_bytes()
            for marker, key in (('P05_MATMUL', 'matmuls'), ('P05_MODEL', 'models')):
                data = log_replace(data, marker, self.observed[key])
            self.log(self.report, self.root, 'installed-matrix', data)

    def save_native_matmuls(self):
        for case in self.report['native_matmuls']:
            name = 'native-' + case['id']
            data = (self.root / 'logs' / (name + '.log')).read_bytes()
            self.log(self.report, self.root, name, log_replace(data, 'P03_RESULT', case['observations']))

    def save_native_models(self):
        root = self.root / 'native'
        for case in self.native['variants'][0]['cases']:
            name = 'simx-' + self.report['format'] + '-' + case['id']
            data = (root / 'logs' / (name + '.log')).read_bytes()
            self.log(self.native, root, name, log_replace(data, 'P04_RESULT', case['observations']))
        save(root / 'report.json', self.native)
        self.report['native_report'] = descriptor(self.root, 'native/report.json')

    def commit(self):
        save(self.root / 'report.json', self.report)

    def model_records(self, case_index=0, iteration=0):
        return (self.observed['models'][case_index * 2 + iteration]['record'],
                self.native['variants'][0]['cases'][case_index]['observations'][iteration])


def flip(word):
    return f'{int(word, 16) ^ 1:08x}'


def decode_half(payload, fmt):
    fraction_bits, exponent_bits = (10, 5) if fmt == 'fp16' else (7, 8)
    values = []
    for offset in range(0, len(payload), 2):
        bits = int.from_bytes(payload[offset:offset + 2], 'little')
        exponent = (bits >> fraction_bits) & ((1 << exponent_bits) - 1)
        mantissa = bits & ((1 << fraction_bits) - 1)
        assert exponent != (1 << exponent_bits) - 1
        bias = (1 << (exponent_bits - 1)) - 1
        significand = Fraction(mantissa, 1 << fraction_bits) + int(exponent != 0)
        value = significand * Fraction(2) ** ((exponent or 1) - bias)
        values.append(-value if bits & 0x8000 else value)
    return values


def fp32_word(value):
    assert value.denominator == 1 and abs(value) <= 1024
    return f'{struct.unpack("<I", struct.pack("<f", int(value)))[0]:08x}'


def independent_model_control(packets):
    counts = {'model_records': 0, 'stage_words': 0, 'bridge_bytes': 0, 'assembled_words': 0}
    for root in packets:
        packet = Packet(root)
        for case_index in range(5):
            for iteration in range(2):
                for record in packet.model_records(case_index, iteration):
                    trace, fmt = record['trace'], packet.report['format']
                    blocks, bridge_bytes = [], None
                    for index, (m, n, k) in enumerate(((16, 8, 16), (8, 4, 8), (8, 4, 8))):
                        stage = trace['native'][index]
                        a_raw, b_raw = bytes.fromhex(stage['a_bytes']), bytes.fromhex(stage['b_bytes'])
                        if index:
                            assert a_raw == bridge_bytes[(index - 1) * 128:index * 128]
                        a, b = decode_half(a_raw, fmt), decode_half(b_raw, fmt)
                        values = [sum((a[i * k + t] * b[j * k + t] for t in range(k)), Fraction())
                                  for i in range(m) for j in range(n)]
                        expected = [fp32_word(value) for value in values]
                        assert stage['output_words'] == expected
                        counts['stage_words'] += len(expected)
                        if index == 0:
                            assert trace['hidden_words'] == expected
                            if fmt == 'fp16':
                                bridge_bytes = b''.join(struct.pack('<e', max(0, int(v))) for v in values)
                            else:
                                packed = [struct.pack('<f', max(0, int(v))) for v in values]
                                assert all(value[:2] == b'\x00\x00' for value in packed)
                                bridge_bytes = b''.join(value[2:] for value in packed)
                            assert trace['bridge_bytes'] == bridge_bytes.hex()
                            assert trace['bridge_words'] == [f'{int.from_bytes(bridge_bytes[i:i + 4], "little"):08x}'
                                                             for i in range(0, 256, 4)]
                            counts['bridge_bytes'] += len(bridge_bytes)
                        else:
                            blocks.extend(expected)
                    assert trace['output_words'] == blocks
                    counts['model_records'] += 1
                    counts['assembled_words'] += len(blocks)
    return counts


def mutate(packet, name):
    if name == 'both-routes-wrong-standalone-bit':
        word = flip(packet.observed['matmuls'][0]['actual_bits'][0])
        packet.observed['matmuls'][0]['actual_bits'][0] = word
        packet.report['native_matmuls'][0]['observations'][0]['actual_bits'][0] = word
        packet.save_observed()
        packet.save_native_matmuls()
    elif name == 'both-routes-wrong-hidden-bit':
        for record in packet.model_records():
            trace = record['trace']
            word = flip(trace['native'][0]['output_words'][0])
            trace['native'][0]['output_words'][0] = trace['hidden_words'][0] = word
        packet.save_observed()
        packet.save_native_models()
    elif name == 'both-routes-bridge-and-dependent-input-substitution':
        for record in packet.model_records():
            trace = record['trace']
            data = bytearray.fromhex(trace['bridge_bytes'])
            nonzero = next(i for i in range(0, len(data), 2) if data[i:i+2] != b'\0\0')
            data[nonzero:nonzero+2] = b'\0\0'
            trace['bridge_bytes'] = data.hex()
            trace['bridge_words'] = [f'{int.from_bytes(data[i:i+4], "little"):08x}' for i in range(0, 256, 4)]
            for index in (1, 2):
                trace['native'][index]['a_bytes'] = data[(index-1)*128:index*128].hex()
        packet.save_observed()
        packet.save_native_models()
    elif name == 'both-routes-dependent-input-substitution':
        for record in packet.model_records():
            record['trace']['native'][1]['a_bytes'] = '00' * 128
        packet.save_observed()
        packet.save_native_models()
    elif name == 'both-routes-wrong-output-and-assembly':
        for record in packet.model_records():
            trace = record['trace']
            word = flip(trace['native'][1]['output_words'][0])
            trace['native'][1]['output_words'][0] = trace['output_words'][0] = word
        packet.save_observed()
        packet.save_native_models()
    elif name == 'both-routes-swapped-assembly':
        for record in packet.model_records():
            trace = record['trace']
            swapped = trace['output_words'][32:] + trace['output_words'][:32]
            assert swapped != trace['output_words']
            trace['output_words'] = swapped
        packet.save_observed()
        packet.save_native_models()
    elif name == 'both-routes-negative-zero-hidden':
        for record in packet.model_records(case_index=2):
            trace = record['trace']
            assert trace['native'][0]['output_words'][0] == '00000000'
            trace['native'][0]['output_words'][0] = trace['hidden_words'][0] = '80000000'
        packet.save_observed()
        packet.save_native_models()
    elif name == 'second-poison-replayed':
        packet.observed['matmuls'][1]['trace']['poison'] = 0x7FC0DEAD
        packet.report['native_matmuls'][0]['observations'][1]['dispatch']['poison'] = 0x7FC0DEAD
        packet.save_observed()
        packet.save_native_matmuls()
    elif name == 'rehashed-json-raw-disagreement':
        packet.observed['matmuls'][0]['actual_bits'][0] = flip(packet.observed['matmuls'][0]['actual_bits'][0])
        packet.save_observed(sync_raw=False)
    elif name == 'duplicate-model-observation':
        packet.observed['models'][1] = copy.deepcopy(packet.observed['models'][0])
        packet.save_observed()
    elif name == 'omitted-model-observation':
        del packet.observed['models'][-1]
        packet.save_observed()
    elif name == 'extra-model-observation':
        packet.observed['models'].append(copy.deepcopy(packet.observed['models'][0]))
        packet.save_observed()
    elif name == 'rehashed-extra-raw-observation':
        path = packet.root / 'logs/installed-matrix.log'
        extra = 'P05_MODEL ' + json.dumps(packet.observed['models'][0], separators=(',', ':')) + '\n'
        packet.log(packet.report, packet.root, 'installed-matrix', path.read_bytes() + extra.encode())
    elif name == 'rehashed-malformed-observation-prefix':
        path = packet.root / 'logs/installed-matrix.log'
        packet.log(packet.report, packet.root, 'installed-matrix', path.read_bytes() + b'P05_123 {}\n')
    elif name == 'rehashed-observation-in-auxiliary-log':
        path = packet.root / 'logs/package-create-venv.log'
        extra = 'P05_MODEL ' + json.dumps(packet.observed['models'][0], separators=(',', ':')) + '\n'
        packet.log(packet.report, packet.root, 'package-create-venv', path.read_bytes() + extra.encode())
    elif name == 'synchronized-count-overclaim':
        packet.observed['counts']['total_launches'] = 72
        packet.report['comparison']['counts']['total_launches'] = 72
        packet.report['native_counts']['total_launches'] = 72
        packet.report['completed_native_and_python_launches'] = 144
        packet.save_observed()
    elif name == 'unsupported-full-matrix-claim':
        packet.report['full_matrix_verified'] = True
    elif name == 'frozen-selection-and-request-substitution':
        for field, name in (('selection', 'snapshots/selection.json'), ('installed_request', 'snapshots/installed-request.json')):
            value = json.loads((packet.root / name).read_bytes())
            case = value['matmuls'][0] if field == 'selection' else value['matmul_cases'][0]
            case['expected'][0] = flip(case['expected'][0])
            save(packet.root / name, value)
            packet.report[field] = descriptor(packet.root, name)
    else:
        raise ValueError(name)
    packet.commit()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--auditor', type=Path, default=DEFAULT_AUDITOR)
    args = parser.parse_args()
    run = args.run_dir.resolve()
    run.mkdir(parents=True, exist_ok=False)
    original = {fmt: inventory(RETAINED / ('simx-' + fmt) / 'python') for fmt in FORMATS}
    original_archives = {fmt: sha((RETAINED / ('simx-' + fmt + '.zip')).read_bytes()) for fmt in FORMATS}
    save(run / 'original-input-receipts.json', {'packets': original, 'archives': original_archives})
    frozen_auditor = run / 'auditor-under-test.py'
    frozen_auditor.write_bytes(args.auditor.read_bytes())
    initial_hash = sha(frozen_auditor.read_bytes())
    packets = []
    for fmt in FORMATS:
        destination = run / 'positive' / fmt
        shutil.copytree(RETAINED / ('simx-' + fmt) / 'python', destination)
        packets.append(destination)
    rational_control = independent_model_control(packets)
    receipts = []

    def check(name, roots, *, selected=False, expected=1, source=SOURCE, positive=False):
        output = run / ('result-' + name + '.json')
        argv = [sys.executable, str(frozen_auditor), '--source-dir', str(source), '--output', str(output)]
        for root in roots:
            argv += ['--packet', str(root)]
        if selected:
            argv.append('--selected-scope')
        process = subprocess.run(argv, capture_output=True, text=True, timeout=30)
        result = json.loads(output.read_bytes()) if output.exists() else {}
        met = process.returncode == expected and result.get('outcome') == ('pass' if expected == 0 else 'fail')
        if positive:
            full = len(roots) == 2
            met = met and result.get('full_matrix_verified') is full
            met = met and result.get('total_launches') == (144 if full else 72)
            met = met and result.get('event_profile_pairs') == (660 if full else 330)
            met = met and result.get('matrix_scope') == ('complete' if full else 'incomplete_selected_format')
        receipt = {'case': name, 'expected_exit': expected, 'exit_code': process.returncode,
                   'outcome': result.get('outcome'), 'reason': result.get('reason'),
                   'expectation_met': met, 'argv': argv, 'stdout': process.stdout, 'stderr': process.stderr,
                   'result_sha256': sha(output.read_bytes()) if output.exists() else None}
        receipts.append(receipt)
        print(json.dumps({key: receipt[key] for key in ('case', 'exit_code', 'reason', 'expectation_met')}), flush=True)

    check('complete-positive', packets, expected=0, positive=True)
    check('selected-positive', packets[:1], selected=True, expected=0, positive=True)
    check('missing-format-default', packets[:1])
    check('duplicate-identical-packet', [packets[0], packets[0]])
    duplicate = run / 'duplicate-format'
    shutil.copytree(packets[0], duplicate)
    check('duplicate-format-distinct-paths', [packets[0], duplicate])
    names = (
        'both-routes-wrong-standalone-bit', 'both-routes-wrong-hidden-bit',
        'both-routes-bridge-and-dependent-input-substitution', 'both-routes-dependent-input-substitution',
        'both-routes-wrong-output-and-assembly', 'both-routes-swapped-assembly',
        'both-routes-negative-zero-hidden', 'second-poison-replayed', 'rehashed-json-raw-disagreement',
        'duplicate-model-observation', 'omitted-model-observation', 'extra-model-observation',
        'rehashed-extra-raw-observation', 'rehashed-malformed-observation-prefix',
        'rehashed-observation-in-auxiliary-log', 'synchronized-count-overclaim',
        'unsupported-full-matrix-claim', 'frozen-selection-and-request-substitution',
    )
    for name in names:
        destination = run / 'mutated' / name
        shutil.copytree(packets[0], destination)
        mutate(Packet(destination), name)
        check(name, [destination], selected=True)
    altered_source = run / 'altered-helper-source'
    for relative in ('ci/project/fixtures/p02_layout_v1.json', 'ci/project/fixtures/p02_wmma_numerical_v1.json',
                     'ci/project/fixtures/p04_tiny_mlp_v1.json', 'docs/project/evidence/p04-executor/reviews/audit_numerics.py'):
        destination = altered_source / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SOURCE / relative, destination)
    helper = altered_source / 'docs/project/evidence/p04-executor/reviews/audit_numerics.py'
    helper.write_bytes(helper.read_bytes() + b'\n# altered helper body probe\n')
    check('accepted-helper-body-substitution', packets[:1], selected=True, source=altered_source)
    unchanged = all(inventory(RETAINED / ('simx-' + fmt) / 'python') == original[fmt]
                    and sha((RETAINED / ('simx-' + fmt + '.zip')).read_bytes()) == original_archives[fmt]
                    for fmt in FORMATS)
    assert unchanged
    summary = {'review_only': True, 'phase_acceptance': False, 'accelerator_executed': False,
               'auditor_initial_sha256': initial_hash, 'auditor_final_sha256': sha(args.auditor.read_bytes()),
               'original_packets_and_archives_unchanged': unchanged, 'independent_rational_control': rational_control,
               'cases': receipts, 'unexpected_results': [r['case'] for r in receipts if not r['expectation_met']]}
    save(run / 'probe-results.json', summary)
    print(json.dumps({'cases': len(receipts), 'unexpected_results': summary['unexpected_results'],
                      'independent_rational_control': rational_control, 'originals_unchanged': unchanged}), flush=True)
    return int(bool(summary['unexpected_results']))


if __name__ == '__main__':
    sys.exit(main())
