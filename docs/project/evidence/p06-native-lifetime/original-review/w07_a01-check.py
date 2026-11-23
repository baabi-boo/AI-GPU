# SPDX-License-Identifier: Apache-2.0
"""Inert independent FP16/per-operation original review; never runs retained code."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import zipfile

sys.dont_write_bytecode = True
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--repo', type=Path, default=Path('/tmp/ai-gpu-native-lifetime-dfd857'))
parser.add_argument('--evidence', type=Path, default=Path('/tmp/ai-gpu-native-lifetime-dfd857-work/native-original/native-lifetime'))
parser.add_argument('--archive', type=Path, default=Path('/tmp/ai-gpu-native-lifetime-dfd857-work/native-original.zip'))
parser.add_argument('--output', type=Path, default=Path('/tmp/ai-gpu-native-lifetime-dfd857-work/w07_a01-receipt.json'))
args = parser.parse_args()
repo, evidence = args.repo.resolve(), args.evidence.resolve()
assert not evidence.is_relative_to(repo / 'ci')
sys.path.insert(0, str(repo / 'ci/project'))
import p06_managed_preflight_contract as parent
import p06_native_lifetime_contract as manifest
import p06_native_lifetime_records as reader

REVISION = 'b4127b19a004b5aebb8d52eab9ceda0da3ff4561'
TREE = 'bd37fb53ab1c34dfebc2ac8805abff5877735fc4'
PROCESS = 'preflight-simx-fp16-per_operation'
ARCHIVE_SHA = '3d4879f73c197352689d65feb56e73f537701fc1411e55bf53c92b1b41e13db3'
started = time.monotonic()


def digest(body):
    return hashlib.sha256(body).hexdigest()


def canonical(value):
    return digest(json.dumps(value, sort_keys=True, separators=(',', ':'),
                             allow_nan=False).encode())


def read_descriptor(descriptor, expected):
    assert set(descriptor) == {'path', 'sha256', 'size_bytes'}
    assert descriptor['path'] == expected
    data = (evidence / expected).read_bytes()
    assert len(data) == descriptor['size_bytes']
    assert digest(data) == descriptor['sha256']
    return data


source_names = {
    'ci/project/p06_warm_contract.json',
    'ci/project/fixtures/p02_layout_v1.json',
    'ci/project/fixtures/p02_tfr_v1.json',
    'ci/project/fixtures/p02_wmma_numerical_v1.json',
    'tests/regression/sgemm_tcu/p02_fixtures.h',
    'tests/regression/ai_counter_preflight/main.cpp',
    'tests/regression/ai_counter_preflight/hooks.h',
    'tests/regression/ai_counter_preflight/hooks.cpp',
    'sim/simx/processor.h', 'sim/simx/processor.cpp',
    'sim/simx/processor_impl.h',
    'docs/designs/managed_counter_lifetime_v1.md',
}
for module in tuple(sys.modules.values()):
    location = getattr(module, '__file__', None)
    if location:
        location = Path(location).resolve()
        if location.is_relative_to(repo / 'ci/project'):
            source_names.add(location.relative_to(repo).as_posix())
before = {}
for name in sorted(source_names):
    data = (repo / name).read_bytes()
    committed = subprocess.check_output(['git', 'show', REVISION + ':' + name], cwd=repo)
    assert data == committed
    before[name] = {'sha256': digest(data), 'size_bytes': len(data)}

archive = args.archive.read_bytes()
assert len(archive) == 9086055 and digest(archive) == ARCHIVE_SHA
report = json.loads((evidence / 'report.json').read_bytes())
assert report['expected_revision'] == REVISION
assert report['contract_id'] == manifest.CONTRACT_ID
assert report['contract_sha256'] == canonical(manifest.contract()) == manifest.contract_hash()
assert report['outcome'] == 'pass' and report['state'] == 'finished'
assert report['native_lifetime_passed'] is True and report['native_execution'] == 'run'
contract = parent.load_contract(repo)
cases = parent.select_cases(contract, repo)
case = next(row for row in cases if row['format'] == 'fp16')
planned = next(row for row in parent.process_plan(contract, repo) if row['id'] == PROCESS)
process = next(row for row in report['processes'] if row['id'] == PROCESS)
variant = next(row for row in report['variants'] if row['id'] == 'simx-fp16')
assert variant['outcome'] == process['outcome'] == 'pass'
assert {name: process[name] for name in planned} == planned
assert json.loads(read_descriptor(report['fixture_snapshot'], 'snapshots/selected-fixtures.json')) == cases
assert json.loads(read_descriptor(report['contract_snapshot'], 'snapshots/contract.json')) == manifest.contract()
assert json.loads(read_descriptor(report['preflight_contract_snapshot'], 'snapshots/preflight-contract.json')) == contract
build_bytes = read_descriptor(variant['binding'], 'snapshots/simx-fp16-build-binding.json')
binding_bytes = read_descriptor(process['binding'], 'snapshots/' + PROCESS + '-binding.json')
build_binding, process_binding = map(json.loads, (build_bytes, binding_bytes))
assert canonical(build_binding) == variant['build_binding_sha256'] == process['build_binding_sha256']
assert canonical(process_binding) == process['execution_binding_sha256']
assert process_binding['build'] == build_binding
assert process_binding['build_binding_sha256'] == variant['build_binding_sha256']
assert process_binding['process'] == planned and build_binding['case'] == case
assert build_binding['source']['checkout']['revision'] == REVISION
assert build_binding['source']['checkout']['tree'] == TREE
assert build_binding['source']['checkout']['dirty'] is False
assert build_binding['source']['checkout']['changed_paths'] == []
assert build_binding['source']['checkout']['untracked_paths'] == []
for binding in (build_binding, process_binding):
    assert binding['contract_id'] == manifest.CONTRACT_ID
    assert binding['contract_sha256'] == manifest.contract_hash()
    assert binding['lifetime_contract'] == manifest.contract()
    assert binding['preflight_contract_sha256'] == canonical(contract)

native_source = Path('/home/runner/work/AI-GPU/AI-GPU')
native_build = Path('/home/runner/work/_temp/p06-native-lifetime/work/simx-fp16')
assert report['paths']['source'] == str(native_source)
assert variant['build_dir'] == str(native_build)
libraries = {name: str(native_build / 'sw/runtime' / name) for name in
             ('libsimx.so', 'libvortex-simx.so', 'libvortex.so')}
libraries.update({
    'libramulator.so': str(native_source / 'third_party/ramulator/libramulator.so'),
    'libramulator-vortex.so': str(native_source / 'third_party/ramulator_ext/libramulator-vortex.so'),
})
assert libraries == variant['expected_loaded_libraries'] == build_binding['expected_loaded_libraries']
command = next(row for row in report['commands'] if row['id'] == PROCESS)
log_path = 'logs/' + PROCESS + '.log'
log_descriptor = {'path': log_path, 'sha256': command['log_sha256'],
                  'size_bytes': command['log_size_bytes']}
assert log_descriptor in report['raw_logs']
log_bytes = read_descriptor(log_descriptor, log_path)
assert command['outcome'] == 'pass' and command['exit_code'] == 0
assert command['reason'] is None and command['cleanup_complete'] is True
assert command['process_started'] is True and command['native_process'] is True
assert command['timeout_seconds'] == 180 and 0 < command['duration_seconds'] < 180
assert 0 < command['peak_rss_bytes'] <= 4 * 1024**3
app = native_build / 'tests/regression/ai_counter_preflight'
assert command['argv'] == [str(app / 'ai_counter_preflight'), '--lifetime', '--policy',
    'per_operation', '--module', str(app / 'kernel.vxbin'), '--qualification-id',
    process['execution_binding_sha256'], '--sample-id', planned['sample_id'],
    '--pair-index', '0', '--phase', 'warmup']
assert command['cwd'] == str(app)
assert command['environment']['VORTEX_DRIVER'] == 'simx'
assert command['environment']['LD_LIBRARY_PATH'] == str(native_build / 'sw/runtime')

observation_bytes = read_descriptor(process['retained_observation'],
                                   'snapshots/' + PROCESS + '-observation.json')
with zipfile.ZipFile(args.archive) as original:
    for name, data in ((log_path, log_bytes), (process['binding']['path'], binding_bytes),
                       (variant['binding']['path'], build_bytes),
                       (process['retained_observation']['path'], observation_bytes)):
        assert original.read('native-lifetime/' + name) == data
verified = reader.verify_output(log_bytes.decode('utf-8', errors='strict'),
    contract=contract, case=case, fmt='fp16', policy='per_operation',
    binding_id=process['execution_binding_sha256'], sample_id=planned['sample_id'],
    process_id=PROCESS, expected_libraries=libraries)
assert verified == process['observation'] == json.loads(observation_bytes)
warm, witness, lifetime = (verified[name] for name in ('warm', 'witness', 'lifetime'))
for claims in (report, build_binding, witness, lifetime):
    assert all(claims[name] is False for name in parent.FALSE_CLAIMS)
    assert claims['unresolved_obligations'] == list(parent.UNRESOLVED_OBLIGATIONS)
assert warm['performance_acceptance'] is warm['phase_acceptance'] is False
operations = warm['operations']
assert len(operations) == 33
assert all(row['actual_bits'] == case['expected'] and row['checked'] == 32
           and row['mismatches'] == 0 and row['passed'] is True for row in operations)
assert sum(len(row['actual_bits']) for row in operations) == 1056
assert warm['summary']['checked'] == 1056 and warm['summary']['mismatches'] == 0
assert warm['summary']['counts']['buffer_create_calls'] == 99
assert warm['summary']['counts']['buffer_release_calls'] == 99
assert warm['summary']['counts']['live_buffers'] == 0

runs, reads, flushes, snapshots = (lifetime[name] for name in
                                 ('runs', 'reads', 'cache_flush_reads', 'snapshots'))
assert (len(runs), len(reads), len(flushes), len(snapshots)) == (33, 264, 33, 4)
assert [row['ordinal'] for row in runs] == list(range(1, 34))
assert [row['before']['reset_generation'] for row in runs] == list(range(1, 34))
assert [row['after']['reset_generation'] for row in runs] == list(range(2, 35))
assert [row['before']['reset_generation'] for row in snapshots] == [1, 2, 34, 34]
assert lifetime['constructed_state'] == snapshots[0]['before'] == runs[0]['before']
run_rows = []
for index, (run, flush) in enumerate(zip(runs, witness['cache_flush_reads']), 1):
    expected_reads = 66 if index == 1 else 131 + index
    assert run['dcr_reads_before'] == run['dcr_reads_after'] == expected_reads
    assert run['cache_flushes_before'] == run['cache_flushes_after'] == index - 1
    assert run['real_call_entered'] is run['completed'] is True and run['exception'] is False
    assert run['before']['pending_reads'] == run['after']['pending_reads'] == 0
    assert flush['sequence'] == (67 if index == 1 else 132 + index)
    assert flush['completed_runs'] == index
    assert flush['reset_before'] == flush['reset_after'] == index + 1
    assert run['after']['ticks'] == flush['ticks_before']
    post_flush = dict(run['after'], ticks=flush['ticks_after'])
    if index < 33:
        assert post_flush == runs[index]['before']
    if index == 1:
        assert post_flush == snapshots[1]['before']
    if index == 33:
        assert post_flush == snapshots[2]['before']
    run_rows.append({'ordinal': index, 'reset_before': index, 'reset_after': index + 1,
        'before_ticks': run['before']['ticks'], 'after_ticks': run['after']['ticks'],
        'flush_after_ticks': flush['ticks_after'], 'core_cycles': run['after']['core_cycles'],
        'core_instructions': run['after']['core_instructions']})
for supplements, original_reads in ((reads, witness['reads']),
                                    (flushes, witness['cache_flush_reads'])):
    for supplemental, original in zip(supplements, original_reads):
        assert supplemental == {'sequence': original['sequence'], 'pending_before': 0, 'pending_after': 0}
        assert original['status'] == 0 and original['completed'] is True
        assert original['overflow'] is False and original['reset_before'] == original['reset_after']
        assert original['idle_before'] is original['idle_after'] is True
        assert original['any_running_before'] is original['any_running_after'] is False
assert sorted(row['sequence'] for row in witness['reads'] + witness['cache_flush_reads']) == list(range(1, 298))
assert all(row['before'] == row['after'] and row['before']['pending_reads'] == 0 for row in snapshots)
terminal = snapshots[-1]['after']
assert terminal == snapshots[-2]['after'] == lifetime['destruction']['before']
assert lifetime['destruction']['completed'] is True and lifetime['destruction']['idle_after'] is True
assert lifetime['destruction']['reset_after'] == 34 and lifetime['destruction']['ticks_after'] == 0
assert terminal['pending_reads'] == 0 and terminal['ticks'] == 5900
assert terminal['core_cycles'] == 194112 and terminal['core_instructions'] == 16797
terminal_original = witness['snapshots'][-1]
assert (terminal_original['device_refs'], terminal_original['queues'], terminal_original['buffers']) == (1, 0, 0)
assert terminal_original['cp_after']['retired'] - terminal_original['cp_before']['retired'] == 66
assert terminal_original['cp_before']['retired'] == terminal_original['cp_before']['expected'] == 1158
assert terminal_original['cp_after']['retired'] == terminal_original['cp_after']['expected'] == 1224
assert {row['name']: row['path'] for row in witness['loaded_libraries']} == libraries

after = {name: {'sha256': digest((repo / name).read_bytes()),
                'size_bytes': (repo / name).stat().st_size} for name in sorted(source_names)}
assert before == after
assert digest(args.archive.read_bytes()) == ARCHIVE_SHA
receipt = {
    'scope': 'independent inert review of one original native FP16/per_operation process',
    'verdict': 'pass', 'native_execution_by_review': 'not_run', 'retained_code_executed': False,
    'reviewed_revision': REVISION, 'reviewed_tree': TREE, 'github_run_id': 45130300651,
    'github_artifact_id': 14798140556, 'archive_sha256': ARCHIVE_SHA,
    'process_id': PROCESS, 'case_id': case['id'],
    'raw_log': log_descriptor, 'process_binding': process['binding'],
    'build_binding': variant['binding'], 'retained_observation': process['retained_observation'],
    'execution_binding_sha256': process['execution_binding_sha256'],
    'build_binding_sha256': variant['build_binding_sha256'],
    'exact_observation_match': True, 'fixture_from_current_committed_source': True,
    'counts': {'launches': 33, 'checked_words': 1056, 'mismatches': 0, 'run_pairs': 33,
               'raw_half_reads': 264, 'flush_reads': 33, 'snapshots': 4, 'terminal_cp_read_retirements': 66},
    'snapshot_resets': [row['before']['reset_generation'] for row in snapshots],
    'snapshot_ticks': [row['before']['ticks'] for row in snapshots],
    'snapshot_core_cycles': [row['before']['core_cycles'] for row in snapshots],
    'snapshot_core_instructions': [row['before']['core_instructions'] for row in snapshots],
    'run_rows': run_rows, 'all_recorded_pending_balances_zero': True,
    'terminal_model': terminal, 'destruction': lifetime['destruction'],
    'loaded_libraries': libraries, 'false_claims': {name: lifetime[name] for name in parent.FALSE_CLAIMS},
    'unresolved_obligations': lifetime['unresolved_obligations'],
    'trusted_source_files': before, 'trusted_sources_stable': True,
    'seconds': round(time.monotonic() - started, 6),
    'limitations': ['This inert review does not perform a new native run.',
        'It covers only this original process; other processes/build and envelope premises have separate reviews.',
        'All-40-component lifetime, fresh dependency compilation provenance, absolute no-wrap, warm speedup and phase acceptance remain unqualified.'],
}
args.output.write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps({key: receipt[key] for key in ('verdict', 'process_id', 'counts', 'snapshot_resets', 'snapshot_ticks', 'seconds')}))
