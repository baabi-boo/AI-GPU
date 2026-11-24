#!/usr/bin/env python3
"""Independent c0 FP16 retained-data review; no retained code is loaded."""
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import time

ROOT = Path('/workspace/scratch/101d52695253/AI-GPU')
NOTES = ROOT.parent / 'agent-notes'
ARCHIVE = ROOT.parent / 'originals/p05-torch-fp16-c0b44ce6-original.zip'
DIGEST = '8c42f7e9f310972e2c0c67c56a03ce8f5460d706cb8dc3a5397435445ea6737c'
REVISION = 'c0b44ce64665fe11895f869eea8c38c9b820d6f7'
POISONS = (0x7fc0dead, 0xdeadbeef)
SHAPES = [('single-dense_boundaries', [8, 4, 8]),
          ('numerical-cross_tile_rounding_positive', [8, 4, 16]),
          ('multi-dense_boundaries', [16, 8, 16])]
FAMILIES = ('seeded_dense', 'negated_dense', 'zero', 'signed_basis', 'split_boundary')
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'ci/project'))
import p05_torch_replay as replay
from p02_wmma_fixtures import load_cases as matmul_cases
from p04_fixture_adapter import load_cases as model_cases


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def packed(words):
    return b''.join(int(word, 16).to_bytes(4, 'little') for word in words)


def check(condition, label):
    if not condition:
        raise AssertionError(label)


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def snapshot():
    return {'head': git('rev-parse', 'HEAD').decode().strip(),
            'status': git('status', '--short').decode().splitlines(),
            'sources': replay._reader_sources()}


def tensor(row, shape, strides, dtype, raw):
    check(row == {'bytes': raw.hex(), 'device': 'cpu', 'dtype': dtype,
                  'requires_grad': False, 'shape': shape, 'storage_offset': 0,
                  'strides': strides}, 'tensor layout/bytes')


def restored(resources):
    check(resources['used_before'] == resources['used_after']
          and resources['free_before'] == resources['free_after'], 'resource restoration')


def complete(status):
    check(status['primary'] == status['cleanup'] == 0 and status['complete'] is True
          and status['validation'] in (0, 'success'), 'completed successful cleanup')


def main():
    before = snapshot()
    check(sha(ARCHIVE.read_bytes()) == DIGEST, 'external original hash before')
    command = [sys.executable, 'ci/project/p05_torch_replay.py', '--archive', str(ARCHIVE),
               '--sha256', DIGEST, '--expected-revision', REVISION, '--format', 'fp16']
    start = time.monotonic()
    process = subprocess.run(command, cwd=ROOT, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'},
                             capture_output=True, timeout=120, check=False)
    seconds = time.monotonic() - start
    check(process.returncode == 0, 'public CLI exit: ' + process.stderr.decode(errors='replace'))
    result = json.loads(process.stdout)
    check(result['outcome'] == 'pass' and process.stderr == b'', 'public CLI result/stderr')
    check(result['reader_sources'] == before['sources'], 'CLI source manifest')
    check(result['native_execution'] == 'not_run' and result['retained_code_executed'] is False
          and result['acceptance_claimed'] is False and result['phase_acceptance'] is False,
          'noexecution/noacceptance boundary')
    api = replay._archive_api()
    trusted_matmuls = {c['id']: c for c in matmul_cases(ROOT)}
    trusted_models = {c['id']: c for c in model_cases(ROOT)}
    matmul_rows, model_rows, checked_members = [], [], {}
    route_counts = {name: {'matmul_runs': 0, 'model_runs': 0, 'matmul_launches': 0,
                           'model_launches': 0, 'event_profile_pairs': 0}
                    for name in ('native', 'python', 'torch')}
    with api.ArchiveReader(ARCHIVE, DIGEST) as archive:
        view = archive.view()

        def document(name):
            raw = view.read(name)
            checked_members[name] = {'sha256': sha(raw), 'size_bytes': len(raw)}
            return api.strict_json(raw)

        def records(name, marker):
            raw = view.read(name, limit=16 * 1024**2)
            checked_members[name] = {'sha256': sha(raw), 'size_bytes': len(raw)}
            return [api.strict_json(line[len(marker) + 1:].encode(), integers_only=True)
                    for line in raw.decode().splitlines() if line.startswith(marker + ' ')]

        native = document('native-model/report.json')
        pr = document('python/report.json')
        tr = document('torch/report.json')
        py = document('python/artifacts/installed-observations.json')
        torch = document('torch/artifacts/installed-observations.json')
        tb = torch['base_observations']
        selected = document('python/snapshots/selection.json')
        check([(c['id'].removeprefix('fp16-'), [c[k] for k in ('m', 'n', 'k')])
               for c in selected['matmuls']] == SHAPES, 'three frozen matmul signatures')
        check([c['family'] for c in selected['models']] == list(FAMILIES), 'five model families')
        check(all(c == trusted_matmuls[c['id']] for c in selected['matmuls']), 'trusted matmul fixtures')
        check(all(c == trusted_models[c['id']] for c in selected['models']), 'trusted model fixtures')
        for prefix, obs in (('python', py), ('torch', tb)):
            log = prefix + '/logs/' + ('installed-matrix.log' if prefix == 'python'
                                      else 'installed-framework-matrix.log')
            check(records(log, 'P05_MATMUL') == obs['matmuls'], prefix + ' matmul JSON/raw')
            check(records(log, 'P05_MODEL') == obs['models'], prefix + ' model JSON/raw')
        tlog = 'torch/logs/installed-framework-matrix.log'
        for kind, marker in (('matmuls', 'P05_TORCH_MATMUL'), ('models', 'P05_TORCH_MODEL')):
            check(records(tlog, marker) == torch['framework_' + kind], 'framework JSON/raw ' + kind)
        for index, case in enumerate(selected['matmuls']):
            raws = records('python/logs/native-' + case['id'] + '.log', 'P03_RESULT')
            check(raws == pr['native_matmuls'][index]['observations'] and len(raws) == 2,
                  'native matmul JSON/raw identity')
            for iteration, n in enumerate(raws):
                p, t, f = (py['matmuls'][2*index+iteration], tb['matmuls'][2*index+iteration],
                            torch['framework_matmuls'][2*index+iteration])
                for route, row, dispatch in (('native', n, n['dispatch']), ('python', p, p['trace']),
                                             ('torch', t, t['trace'])):
                    check(row['case_id'] == case['id'] and row['iteration'] == iteration,
                          route + ' matmul case/iteration')
                    check(row['actual_bits'] == case['expected'], route + ' matmul actual words')
                    check(dispatch['poison'] == POISONS[iteration], route + ' matmul poison')
                    restored(row['resources'])
                    route_counts[route]['matmul_runs'] += 1
                    route_counts[route]['matmul_launches'] += dispatch.get('launches', dispatch.get('launches_enqueued'))
                    route_counts[route]['event_profile_pairs'] += len(dispatch.get('event_profiles', []))
                    if route != 'native':
                        complete(row['status']); complete(row['close_status'])
                m, ncols, k = (case[key] for key in ('m', 'n', 'k'))
                check(f['case_id'] == case['id'] and f['iteration'] == iteration, 'framework matmul identity')
                tensor(f['a'], [m, k], [k, 1], 'torch.float16', packed(case['a_words']))
                tensor(f['b'], [k, ncols], [1, k], 'torch.float16', packed(case['b_words']))
                tensor(f['result'], [m, ncols], [ncols, 1], 'torch.float32', packed(n['actual_bits']))
                matmul_rows.append({'id': case['id'], 'iteration': iteration, 'shape': [m, ncols, k],
                                    'poison': f'{POISONS[iteration]:08x}', 'checked_words': len(n['actual_bits']),
                                    'result_sha256': sha(packed(n['actual_bits']))})
        for index, case in enumerate(selected['models']):
            raws = records('native-model/logs/simx-fp16-' + case['id'] + '.log', 'P04_RESULT')
            check(raws == native['variants'][0]['cases'][index]['observations'] and len(raws) == 2,
                  'native model JSON/raw identity')
            for iteration, n in enumerate(raws):
                p, t, f = (py['models'][2*index+iteration], tb['models'][2*index+iteration],
                            torch['framework_models'][2*index+iteration])
                for label, row in (('python', p), ('torch', t), ('framework', f)):
                    check(row['case_id'] == case['id'] and row['iteration'] == iteration,
                          label + ' model case/iteration')
                traces = [n['trace'], p['record']['trace'], t['record']['trace']]
                for route, trace in zip(('native', 'python', 'torch'), traces):
                    check(trace['case_id'] == case['id'] and trace['poison'] == POISONS[iteration],
                          route + ' model identity/poison')
                    for key in ('hidden_words', 'bridge_words', 'output_words'):
                        check(trace[key] == case[key], route + ' frozen ' + key)
                    bridge = bytes.fromhex(trace['bridge_bytes'])
                    check(bridge == packed(trace['bridge_words']), 'bridge bytes/words')
                    # CPython binary16 packing independently checks this FP16
                    # corpus's actual FP32 -> ReLU -> nearest-even FP16 bridge.
                    converted = b''.join(struct.pack('<e', max(0.0, struct.unpack('<f', int(word, 16).to_bytes(4, 'little'))[0]))
                                         for word in trace['hidden_words'])
                    check(converted == bridge, route + ' actual hidden-to-bridge conversion')
                    stages = trace['native']
                    check(len(stages) == 3 and [s['operation_id'] for s in stages]
                          == ['hidden_matmul', 'output_rows_0_7', 'output_rows_8_15'], 'model operation order')
                    check(stages[0]['output_words'] == trace['hidden_words'], 'actual hidden lineage')
                    check(bytes.fromhex(stages[0]['a_bytes']) == packed(case['input_words']), 'model input bytes')
                    check(bytes.fromhex(stages[0]['b_bytes']) == packed(case['w1_words']), 'first weights')
                    for block, stage in enumerate(stages[1:]):
                        check(bytes.fromhex(stage['a_bytes']) == bridge[128*block:128*(block+1)], 'live bridge slice')
                        check(bytes.fromhex(stage['b_bytes']) == packed(case['w2_words']), 'second weights')
                    check(stages[1]['output_words'] + stages[2]['output_words'] == trace['output_words'],
                          'actual output block assembly')
                    for stage in stages:
                        check(stage['dispatch']['poison'] == POISONS[iteration], 'all model stage poisons')
                        complete(stage['completion']); complete(stage['cleanup'])
                        check(stage['closed'] is True, 'model stage explicit close')
                        route_counts[route]['model_launches'] += stage['dispatch']['launches_enqueued']
                        route_counts[route]['event_profile_pairs'] += len(stage['dispatch']['event_profiles'])
                    restored(trace['resources']); complete(trace['owner_cleanup'])
                    check(trace['owner_closed'] is True, 'model owner explicit close')
                    route_counts[route]['model_runs'] += 1
                tensor(f['result'], [16, 4], [4, 1], 'torch.float32', packed(traces[0]['output_words']))
                model_rows.append({'id': case['id'], 'iteration': iteration, 'poison': f'{POISONS[iteration]:08x}',
                                   'hidden_words': len(case['hidden_words']), 'bridge_words': len(case['bridge_words']),
                                   'output_words': len(case['output_words']),
                                   'lineage_sha256': sha(canonical({key: traces[0][key] for key in
                                       ('hidden_words', 'bridge_words', 'bridge_bytes', 'output_words')}))})
        copy_counts = []
        for left_name, right_name in (('native-model', 'python/native'), ('python', 'torch/python')):
            left, right = view.subview(left_name), view.subview(right_name)
            check(left.files() == right.files(), 'copied packet membership')
            for name in left.files():
                check(left.read(name, limit=api.MEMBER_BYTES) == right.read(name, limit=api.MEMBER_BYTES),
                      'copied packet bytes: ' + name)
            copy_counts.append({'left': left_name, 'right': right_name, 'members': len(left.files()),
                                'additional_executions': 0})
        native_summary = {k: native[k] for k in ('completed_case_executions', 'completed_model_runs',
                          'completed_launches', 'comparison_counts', 'tensor_h2d_bytes', 'tensor_d2h_bytes')}
        for counts in route_counts.values():
            counts['total_launches'] = counts['matmul_launches'] + counts['model_launches']
            check([counts[k] for k in ('matmul_runs', 'model_runs', 'matmul_launches', 'model_launches', 'total_launches')]
                  == [6, 10, 6, 30, 36], 'independent route counts')
        check(sum(c['total_launches'] for c in route_counts.values()) == 108, 'distinct launch total')
        independent_receipt = archive.receipt()
    after = snapshot()
    check(sha(ARCHIVE.read_bytes()) == DIGEST, 'external original hash after')
    check(before['head'] == after['head'] and before['sources'] == after['sources'], 'reader identity stability')
    source_vs_head = []
    for row in before['sources']:
        head_raw = git('show', before['head'] + ':' + row['path'])
        if sha(head_raw) != row['sha256']:
            source_vs_head.append({'path': row['path'], 'head_sha256': sha(head_raw),
                                   'working_sha256': row['sha256']})
    compact_archive = {key: value for key, value in result['archive_read'].items() if key != 'read_files'}
    compact_archive['read_file_manifest_sha256'] = sha(canonical(result['archive_read']['read_files']))
    compact_archive['close_rehash_passed'] = True
    receipt = {'agent': 37, 'scope': 'actual-original-c0-fp16-retained-consistency',
               'archive': {'path': str(ARCHIVE), 'sha256': DIGEST, 'size_bytes': ARCHIVE.stat().st_size},
               'execution_revision': REVISION, 'reader_head': before['head'],
               'reader_source_files': before['sources'], 'reader_source_count': len(before['sources']),
               'reader_source_manifest_sha256': sha(canonical(before['sources'])),
               'reader_sources_stable': True, 'reader_source_differences_from_head': source_vs_head,
               'checkout_status_before': before['status'], 'checkout_status_after': after['status'],
               'checkout_claimed_clean': False, 'public_command': command,
               'public_exit_code': process.returncode, 'public_seconds': seconds,
               'public_stdout_sha256': sha(process.stdout), 'public_stderr_bytes': len(process.stderr),
               'public_result': {key: result[key] for key in ('outcome', 'format', 'native_execution',
                   'retained_code_executed', 'acceptance_claimed', 'phase_acceptance', 'counts',
                   'host_fault_semantics_revalidated', 'python_comparison', 'framework_comparison',
                   'installation', 'limitations')}, 'public_archive_read': compact_archive,
               'independent_route_counts': route_counts, 'independent_matmul_rows': matmul_rows,
               'independent_model_rows': model_rows, 'native_report_counts': native_summary,
               'copied_packet_checks': copy_counts, 'checked_record_identities': checked_members,
               'independent_close_rehash_passed': True,
               'independent_read_file_manifest_sha256': sha(canonical(independent_receipt['read_files'])),
               'independent_read_files': len(independent_receipt['read_files']),
               'external_before_after_digest_matched': True,
               'probe_sha256': sha(Path(__file__).read_bytes()),
               'limitations': ['Recorded execution only; no new native execution or acceptance.',
                   'No retained import/execution/extraction or recorded producer-path access.',
                   'No source-to-Git historical audit repeated; independent agent49 report is separate.',
                   'No unit/governance suite or BF16 run repeated.',
                   'Native P03 matmul records lack five-event profile arrays; native profile count is model-only.',
                   'Absent third-party/compiler/interpreter/submodule bytes are not freshly qualified.']}
    path = NOTES / 'a37-receipt.json'
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'outcome': 'pass', 'receipt': str(path), 'seconds': seconds,
                      'counts': result['counts'], 'source_differences_from_head': source_vs_head}, sort_keys=True))


if __name__ == '__main__':
    main()
