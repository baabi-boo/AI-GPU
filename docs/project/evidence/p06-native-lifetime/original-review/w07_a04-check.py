#!/usr/bin/env python3
"""Inert review of one original BF16 resident-workspace process."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import struct
import subprocess
import sys
import time
import zipfile

sys.dont_write_bytecode = True
REPO = Path('/tmp/ai-gpu-native-lifetime-dfd857')
WORK = Path('/tmp/ai-gpu-native-lifetime-dfd857-work')
DATA = WORK / 'native-original/native-lifetime'
REVISION = 'b4127b19a004b5aebb8d52eab9ceda0da3ff4561'
ARCHIVE_SHA = '3d4879f73c197352689d65feb56e73f537701fc1411e55bf53c92b1b41e13db3'
PROCESS = 'preflight-simx-bf16-reusable_single_tile'
sys.path.insert(0, str(REPO / 'ci/project'))
import p06_managed_preflight_contract as preflight
import p06_native_lifetime_contract as lifetime_contract
import p06_native_lifetime_records as reader

START = time.monotonic()
checks = 0
verified_files = {}

def check(condition, label):
    global checks
    checks += 1
    if not condition:
        raise AssertionError(label)

def digest(body):
    return hashlib.sha256(body).hexdigest()

def canonical(value):
    return digest(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode())

def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key: ' + key)
        result[key] = value
    return result

def load_bytes(body):
    return json.loads(body, object_pairs_hook=unique)

def described(descriptor, expected):
    check(set(descriptor) == {'path', 'sha256', 'size_bytes'}, 'descriptor shape')
    check(descriptor['path'] == expected, 'descriptor fixed path')
    path = PurePosixPath(expected)
    check(not path.is_absolute() and '..' not in path.parts, 'contained data path')
    body = (DATA / path).read_bytes()
    check(len(body) == descriptor['size_bytes'] and digest(body) == descriptor['sha256'], 'descriptor bytes')
    verified_files[expected] = dict(descriptor)
    return body

def data_json(descriptor, expected):
    return load_bytes(described(descriptor, expected))

def source_inventory():
    paths = set()
    for module in tuple(sys.modules.values()):
        name = getattr(module, '__file__', None)
        if name:
            path = Path(name).resolve()
            if path.suffix == '.py' and path.is_relative_to(REPO / 'ci/project'):
                paths.add(path.relative_to(REPO).as_posix())
    paths.update((
        'ci/project/p06_warm_contract.json',
        'ci/project/fixtures/p02_layout_v1.json',
        'ci/project/fixtures/p02_tfr_v1.json',
        'ci/project/fixtures/p02_wmma_numerical_v1.json',
        'tests/regression/sgemm_tcu/p02_fixtures.h',
        'tests/regression/ai_counter_preflight/main.cpp',
        'tests/regression/ai_counter_preflight/hooks.cpp',
        'tests/regression/ai_counter_preflight/hooks.h',
        'tests/regression/ai_warm_workspace/main.cpp',
        'sw/common/ai_matmul_args.h', 'sw/common/ai_matmul_profile.h',
        'docs/designs/managed_counter_lifetime_v1.md',
    ))
    rows = []
    for path in sorted(paths):
        body = (REPO / path).read_bytes()
        committed = subprocess.check_output(['git', 'show', REVISION + ':' + path], cwd=REPO)
        check(body == committed, 'trusted source matches committed blob: ' + path)
        retained = DATA / 'artifacts/source' / path
        check(retained.is_file() and retained.read_bytes() == body, 'retained source matches trusted source: ' + path)
        rows.append({'path': path, 'sha256': digest(body), 'size_bytes': len(body)})
    return rows

contract = preflight.load_contract(REPO)
cases = preflight.select_cases(contract, REPO)
case = next(row for row in cases if row['format'] == 'bf16')
planned = next(row for row in preflight.process_plan(contract, REPO) if row['id'] == PROCESS)
sources_before = source_inventory()
report_body = (DATA / 'report.json').read_bytes()
report = load_bytes(report_body)
process = next(row for row in report['processes'] if row['id'] == PROCESS)
variant = next(row for row in report['variants'] if row['format'] == 'bf16')
check(report['expected_revision'] == REVISION, 'original source revision')
check(report['outcome'] == 'pass' and report['native_lifetime_passed'] is True, 'original reported outcome')
check({key: process[key] for key in preflight.PROCESS_FIELDS} == planned, 'canonical process identity')
source = data_json(report['source_before'], 'snapshots/source-before.json')
tools = data_json(report['tools_before'], 'snapshots/tools-before.json')
dependencies = data_json(report['dependencies_before'], 'snapshots/dependencies-before.json')
check(source['checkout']['revision'] == REVISION, 'source snapshot revision')
check(data_json(report['fixture_snapshot'], 'snapshots/selected-fixtures.json') == cases, 'canonical selected fixtures')
active_contract = lifetime_contract.contract()
check(report['contract_id'] == lifetime_contract.CONTRACT_ID, 'selected contract identity')
check(report['contract_sha256'] == canonical(active_contract), 'selected contract hash')
check(report['preflight_contract_sha256'] == canonical(contract), 'parent contract hash')
build = data_json(variant['binding'], 'snapshots/simx-bf16-build-binding.json')
expected_source = '/home/runner/work/AI-GPU/AI-GPU'
expected_build = '/home/runner/work/_temp/p06-native-lifetime/work/simx-bf16'
libraries = {name: expected_build + '/sw/runtime/' + name for name in ('libvortex.so', 'libvortex-simx.so', 'libsimx.so')}
libraries.update({'libramulator.so': expected_source + '/third_party/ramulator/libramulator.so',
                  'libramulator-vortex.so': expected_source + '/third_party/ramulator_ext/libramulator-vortex.so'})
check(report['paths']['source'] == expected_source and variant['build_dir'] == expected_build, 'fixed original build route')
check(variant['expected_loaded_libraries'] == libraries, 'fixed library inventory')
rebuilt = {
    'contract_id': lifetime_contract.CONTRACT_ID, 'contract_sha256': canonical(active_contract),
    'source': source, 'loaded_helpers': report['loaded_helpers'], 'format': 'bf16', 'backend': 'simx', 'case': case,
    'corpus': report['corpus'], 'profile_sha256': report['profile_sha256'], 'kernel_source_sha256': report['kernel_source_sha256'],
    'warm_contract_sha256': preflight.WARM_CONTRACT_SHA256,
    'compiler_records': variant['compiler_records'], 'model_build_records': variant['model_build_records'],
    'host_build_records': variant['host_build_records'], 'effective_headers': variant['effective_headers'],
    'generated_identity': variant['generated_identity'], 'artifacts': variant['artifacts_before'],
    'tools': tools, 'dependencies': dependencies, 'expected_loaded_libraries': libraries,
    'simulation_workers': 1, 'performance_environment': {'PERF': '1'},
    'unresolved_obligations': list(preflight.UNRESOLVED_OBLIGATIONS),
    **dict.fromkeys(preflight.FALSE_CLAIMS, False),
    'lifetime_contract': active_contract, 'preflight_contract_sha256': canonical(contract),
}
check(build == rebuilt, 'reconstructed build binding')
check(canonical(rebuilt) == variant['build_binding_sha256'] == process['build_binding_sha256'], 'build binding digest')
binding = data_json(process['binding'], 'snapshots/' + PROCESS + '-binding.json')
expected_binding = {'contract_id': lifetime_contract.CONTRACT_ID, 'contract_sha256': canonical(active_contract),
    'build_binding_sha256': canonical(rebuilt), 'build': rebuilt, 'process': planned,
    'lifetime_contract': active_contract, 'preflight_contract_sha256': canonical(contract)}
check(binding == expected_binding, 'reconstructed process binding')
check(canonical(binding) == process['execution_binding_sha256'], 'process binding digest')
for row in variant['compiler_records']:
    configuration = row['configuration']
    check(all(configuration[name] == value for name, value in {
        'ITYPE': 'bf16', 'OTYPE': 'fp32', 'SIMX_CHECKED_COUNTERS': '1',
        'VX_CFG_XLEN': '64', 'VX_CFG_TCU_TYPE': 'TFR', 'VX_CFG_FPU_TYPE': 'STD'}.items()), 'BF16 role selection')
raw_descriptor = next(row for row in report['raw_logs'] if row['path'] == process['log'])
raw = described(raw_descriptor, 'logs/' + PROCESS + '.log')
command = next(row for row in report['commands'] if row['id'] == PROCESS)
check(command['log_sha256'] == digest(raw) and command['log_size_bytes'] == len(raw), 'command log identity')
check(command['outcome'] == 'pass' and command['exit_code'] == 0 and command['process_started'] is True
      and command['cleanup_complete'] is True and command['native_process'] is True, 'successful native command receipt')
expected_argv = [expected_build + '/tests/regression/ai_counter_preflight/ai_counter_preflight', '--lifetime',
    '--policy', 'reusable_single_tile', '--module', expected_build + '/tests/regression/ai_counter_preflight/kernel.vxbin',
    '--qualification-id', canonical(binding), '--sample-id', planned['sample_id'], '--pair-index', '0', '--phase', 'warmup']
check(command['argv'] == expected_argv, 'fixed invocation arguments')
check(command['environment']['LD_LIBRARY_PATH'] == expected_build + '/sw/runtime'
      and command['environment']['VORTEX_DRIVER'] == 'simx', 'selected loader environment')
observed = reader.verify_output(raw.decode('utf-8'), contract=contract, case=case, fmt='bf16',
    policy='reusable_single_tile', binding_id=canonical(binding), sample_id=planned['sample_id'],
    process_id=PROCESS, expected_libraries=libraries)
retained = data_json(process['retained_observation'], 'snapshots/' + PROCESS + '-observation.json')
check(observed == retained == process['observation'], 'full trusted-reader reproduction')
warm, witness, lifetime = (observed[name] for name in ('warm', 'witness', 'lifetime'))
for record in (report, lifetime, witness):
    check(all(record[key] is False for key in preflight.FALSE_CLAIMS), 'seven false claims')
    check(record['unresolved_obligations'] == list(preflight.UNRESOLVED_OBLIGATIONS), 'three unresolved obligations')
check(len(warm['operations']) == len(lifetime['runs']) == 33, 'complete operation/run populations')
addresses = None
for index, operation in enumerate(warm['operations']):
    check(operation['operation_index'] == index and operation['format'] == 'bf16'
          and operation['policy'] == 'reusable_single_tile', 'operation identity')
    check(operation['actual_bits'] == case['expected'] and operation['checked'] == 32
          and operation['mismatches'] == 0 and operation['passed'] is True, 'exact independent expected words')
    dispatch = operation['dispatch']
    values = tuple(dispatch[key] for key in ('a_address', 'b_address', 'd_address'))
    if addresses is None:
        addresses = values
    check(values == addresses and len(set(values)) == 3, 'stable distinct resident addresses')
    check(tuple(struct.unpack('<8I3Q', bytes.fromhex(dispatch['argument_bytes'])))
          == (1, 56, 2, 0, 8, 4, 8, 0, *addresses), 'BF16 launch argument ABI')
    check((dispatch['a_bytes'], dispatch['b_bytes'], dispatch['d_bytes']) == (128, 64, 128), 'tensor byte sizes')
    check(dispatch['launches'] == dispatch['reads'] == dispatch['waits'] == 1
          and dispatch['writes'] == 3 and dispatch['timed_out_waits'] == 0
          and dispatch['event_results'] == [0] * 5, 'successful operation dispatch')
summary = warm['summary']
check(summary['operations'] == 33 and summary['checked'] == 1056 and summary['mismatches'] == 0
      and summary['passed'] is True, 'complete numerical summary')
check(summary['counts']['buffer_create_calls'] == summary['counts']['buffer_release_calls'] == 3
      and summary['counts']['live_buffers'] == summary['counts']['live_requested_bytes']
      == summary['counts']['premature_releases'] == summary['counts']['errors'] == 0,
      'resident tensor lifetime cleanup')
check(summary['device_release']['status'] == 0 and summary['results']['close']['complete'] is True
      and all(summary['results']['close'][k] == 0 for k in ('validation', 'primary', 'cleanup')), 'successful owner close')
check(len(lifetime['reads']) == len(witness['reads']) == 264
      and len(lifetime['cache_flush_reads']) == len(witness['cache_flush_reads']) == 33, 'read populations')
check(sorted(row['sequence'] for row in witness['reads'] + witness['cache_flush_reads']) == list(range(1, 298)),
      'raw reads and flushes partition every DCR sequence')
pending_values = [lifetime['constructed_state']['pending_reads'], lifetime['destruction']['before']['pending_reads']]
models = [lifetime['constructed_state'], lifetime['destruction']['before']]
for name in ('reads', 'cache_flush_reads'):
    for supplement, original in zip(lifetime[name], witness[name]):
        check(supplement['sequence'] == original['sequence'], 'one-to-one read supplement')
        pending_values.extend((supplement['pending_before'], supplement['pending_after']))
        check(original['status'] == 0 and original['completed'] is True and original['overflow'] is False,
              'successful raw getter/flush status')
        check(original['idle_before'] is True and original['idle_after'] is True
              and original['any_running_before'] is False and original['any_running_after'] is False,
              'quiescent raw getter/flush boundary')
baseline = lifetime['constructed_state']['reset_generation']
check(baseline == 1, 'observed initial reset generation')
previous = lifetime['constructed_state']
for ordinal, (run, flush) in enumerate(zip(lifetime['runs'], witness['cache_flush_reads']), 1):
    before, after = run['before'], run['after']
    models.extend((before, after)); pending_values.extend((before['pending_reads'], after['pending_reads']))
    check(run['ordinal'] == ordinal and before == previous, 'exact preceding run/flush join')
    check(before['reset_generation'] == baseline + ordinal - 1 and after['reset_generation'] == baseline + ordinal,
          'exact one-reset lifetime window')
    check(run['real_call_entered'] is True and run['completed'] is True and run['exception'] is False, 'real run success')
    count = 66 if ordinal == 1 else 131 + ordinal
    check(run['dcr_reads_before'] == run['dcr_reads_after'] == count
          and run['cache_flushes_before'] == run['cache_flushes_after'] == ordinal - 1, 'run event offsets')
    check(flush['sequence'] == (67 if ordinal == 1 else 132 + ordinal)
          and flush['completed_runs'] == ordinal and flush['reset_before'] == flush['reset_after'] == baseline + ordinal,
          'corresponding flush identity/reset')
    check(flush['ticks_before'] == after['ticks'] and flush['ticks_after'] >= after['ticks'], 'reset-local flush clock')
    check(after['core_cycles'] >= before['core_cycles'] and after['core_instructions'] >= before['core_instructions'],
          'cumulative core counters within run')
    previous = dict(after, ticks=flush['ticks_after'])
    if ordinal == 1:
        check(lifetime['snapshots'][1]['before'] == previous, 'prime snapshot join')
check(lifetime['snapshots'][2]['before'] == previous, 'batch snapshot join')
for index, (snapshot, original) in enumerate(zip(lifetime['snapshots'], witness['snapshots'])):
    check(snapshot['name'] == preflight.SNAPSHOT_NAMES[index] and snapshot['before'] == snapshot['after'], 'snapshot identity/read-only state')
    check(snapshot['before']['reset_generation'] == (1, 2, 34, 34)[index], 'snapshot reset progression')
    for side in ('before', 'after'):
        models.append(snapshot[side]); pending_values.append(snapshot[side]['pending_reads'])
        check({k: v for k, v in snapshot[side].items() if k != 'pending_reads'} == original[side], 'parent snapshot projection')
    for read in witness['reads'][original['read_begin']:original['read_end']]:
        check(read['reset_before'] == read['reset_after'] == snapshot['before']['reset_generation']
              and read['ticks_before'] == read['ticks_after'] == snapshot['before']['ticks'], 'all snapshot raw reads stable')
check(len(pending_values) == 670 and all(type(x) is int and x == 0 for x in pending_values), 'all 670 exact zero pending observations')
check(all(x['live'] is True and x['idle'] is True and x['any_running'] is False and x['generation'] == 1 for x in models), 'all live model boundaries quiescent/owned')
terminal = witness['snapshots'][-1]
check(terminal['device_refs'] == 1 and terminal['queues'] == terminal['buffers'] == 0, 'terminal runtime ownership')
for cp in (terminal['cp_before'], terminal['cp_after']):
    check(cp['control'] == cp['queue_control'] == 1 and cp['status'] == cp['error'] == 0
          and cp['retired'] == cp['expected'] and cp['drain_basis'] == 'enabled-idle-status-and-retired-sequence', 'enabled CP drain observations')
check(terminal['cp_before']['retired'] == 1158 and terminal['cp_after']['retired'] == 1224, 'terminal 66 exact command retirements')
destruction = lifetime['destruction']
check(lifetime['snapshots'][2]['after'] == lifetime['snapshots'][3]['before']
      == lifetime['snapshots'][3]['after'] == destruction['before'], 'cleanup and actual destructor-entry join')
check(destruction['completed'] is True and destruction['idle_after'] is True
      and destruction['reset_after'] == 34 and destruction['ticks_after'] == 0, 'actual platform disposal observation')
archive = WORK / 'native-original.zip'
check(digest(archive.read_bytes()) == ARCHIVE_SHA, 'original archive identity')
with zipfile.ZipFile(archive) as z:
    for path in verified_files:
        check(z.read('native-lifetime/' + path) == (DATA / path).read_bytes(), 'original ZIP member equality')
    check(z.read('native-lifetime/report.json') == report_body, 'original report ZIP equality')
sources_after = source_inventory()
check(sources_before == sources_after, 'trusted source stability')
check((DATA / 'report.json').read_bytes() == report_body, 'original report stability')
for path, descriptor in verified_files.items():
    body = (DATA / path).read_bytes()
    check(digest(body) == descriptor['sha256'] and len(body) == descriptor['size_bytes'], 'reviewed input stability')
receipt = {
    'scope': 'inert original BF16 reusable_single_tile review; no native execution', 'outcome': 'pass',
    'source_revision': REVISION, 'run_id': 45130300651, 'artifact_id': 14798140556,
    'process_id': PROCESS, 'archive_sha256': ARCHIVE_SHA, 'report_sha256': digest(report_body),
    'raw_log': raw_descriptor, 'build_binding_sha256': canonical(rebuilt), 'execution_binding_sha256': canonical(binding),
    'retained_observation': process['retained_observation'], 'inert_assertions': checks,
    'seconds': round(time.monotonic() - START, 6), 'source_stable': True,
    'trusted_source_files': sources_before, 'verified_data_files': list(verified_files.values()),
    'counts': {'launches': 33, 'checked_words': 1056, 'mismatches': 0, 'pending_observations': 670,
               'mpm_half_reads': 264, 'flush_reads': 33, 'dcr_sequences': 297, 'snapshots': 4},
    'resident_addresses': dict(zip(('a', 'b', 'd'), addresses)), 'tensor_cleanup': summary['counts'],
    'reset_range': [1, 34], 'snapshot_reset_generations': [1, 2, 34, 34],
    'terminal_model': destruction['before'], 'destruction': destruction,
    'terminal_cp_retired': [1158, 1224], 'terminal_ownership': {'device_refs': 1, 'queues': 0, 'buffers': 0},
    'retained_code_executed': False, 'native_execution': 'not_run', 'qualified': False,
    'seven_claims_false': True, 'unresolved_obligations': list(preflight.UNRESOLVED_OBLIGATIONS),
    'limits': ['Build binding reconstruction is not independent admission of every compiler/link command.',
               'No complete all-40 backing-component or fresh dependency compilation qualification.',
               'No wall-clock performance, warm readiness, phase acceptance or physical hardware claim.'],
}
(WORK / 'w07_a04-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps({k: receipt[k] for k in ('outcome', 'process_id', 'inert_assertions', 'seconds', 'counts')}))
