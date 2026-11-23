#!/usr/bin/env python3
"""Inert review of the original BF16/per_operation lifetime process."""
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import subprocess
import sys
import time

sys.dont_write_bytecode = True
REPO = Path('/tmp/ai-gpu-native-lifetime-dfd857')
WORK = Path('/tmp/ai-gpu-native-lifetime-dfd857-work')
DATA = WORK / 'native-original/native-lifetime'
REVISION = 'b4127b19a004b5aebb8d52eab9ceda0da3ff4561'
PROCESS = 'preflight-simx-bf16-per_operation'
sys.path.insert(0, str(REPO / 'ci/project'))

import p06_managed_preflight_contract as parent
import p06_native_lifetime_contract as lifetime
import p06_native_lifetime_records as records
import p06_managed_preflight_build as build_records
import p06_warm_contract as warm_contract
from p06_warm_execute import validate_process_duration
from p03_execution_records import qualification_id

started = time.monotonic()
checks = []
identities = []

def check(condition, description):
    if not condition:
        raise AssertionError(description)
    checks.append(description)

def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key: ' + key)
        result[key] = value
    return result

def reject_constant(value):
    raise ValueError('nonfinite JSON constant: ' + value)

def read_json(path):
    body = path.read_bytes()
    check(len(body) <= 64 * 1024**2, 'bounded JSON ' + str(path.relative_to(DATA)))
    return json.loads(body.decode('utf-8'), object_pairs_hook=unique,
                      parse_constant=reject_constant)

def verify_descriptor(descriptor):
    check(set(descriptor) == {'path', 'sha256', 'size_bytes'}, 'exact descriptor shape')
    relative = PurePosixPath(descriptor['path'])
    check(not relative.is_absolute() and '..' not in relative.parts,
          'contained descriptor ' + str(relative))
    target = DATA / relative
    check(not target.is_symlink(), 'regular descriptor input ' + str(relative))
    body = target.read_bytes()
    actual = {'path': str(relative), 'sha256': hashlib.sha256(body).hexdigest(),
              'size_bytes': len(body)}
    check(actual == descriptor, 'descriptor bytes ' + str(relative))
    identities.append(actual)
    return target

report = read_json(DATA / 'report.json')
check(report['expected_revision'] == REVISION, 'expected native source revision')
process = next(row for row in report['processes'] if row['id'] == PROCESS)
variant = next(row for row in report['variants'] if row['id'] == 'simx-bf16')
check(process['outcome'] == variant['outcome'] == 'pass', 'original process and build passed')
contract = parent.load_contract(REPO)
cases = parent.select_cases(contract, REPO)
case = next(row for row in cases if row['format'] == 'bf16')
planned = next(row for row in parent.process_plan(contract, REPO) if row['id'] == PROCESS)
check({key: process[key] for key in parent.PROCESS_FIELDS} == planned,
      'process identity from current canonical plan')
check(case['id'] == 'bf16-single-dense_boundaries' and
      (case['m'], case['n'], case['k']) == (8, 4, 8), 'canonical BF16 fixture selection')
check(read_json(verify_descriptor(report['fixture_snapshot'])) == cases,
      'retained fixtures equal independently selected current cases')
check(read_json(verify_descriptor(report['preflight_contract_snapshot'])) == contract,
      'retained parent contract equals current canonical contract')
check(read_json(verify_descriptor(report['contract_snapshot'])) == lifetime.contract(),
      'retained lifetime contract equals current canonical descriptor')
check(report['preflight_contract_sha256'] == qualification_id(contract),
      'parent contract canonical digest')
check(report['contract_sha256'] == lifetime.contract_hash(), 'lifetime contract digest')

binding = read_json(verify_descriptor(process['binding']))
build = read_json(verify_descriptor(variant['binding']))
check(binding['build'] == build, 'process embeds exact retained build binding')
check(binding['process'] == planned, 'binding process is canonical planned case')
check(build['case'] == case, 'build binds independently selected BF16 fixture')
check(build['format'] == 'bf16' and build['backend'] == 'simx', 'build format and backend')
check(build['source']['checkout']['revision'] == REVISION, 'build checkout revision')
check(qualification_id(build) == variant['build_binding_sha256'] ==
      process['build_binding_sha256'] == binding['build_binding_sha256'],
      'recomputed build binding digest')
check(qualification_id(binding) == process['execution_binding_sha256'],
      'recomputed execution binding digest')
for value in (binding, build):
    check(value['contract_id'] == lifetime.CONTRACT_ID and
          value['contract_sha256'] == lifetime.contract_hash() and
          value['lifetime_contract'] == lifetime.contract() and
          value['preflight_contract_sha256'] == qualification_id(contract),
          'versioned binding contract and descriptor')

source = Path('/home/runner/work/AI-GPU/AI-GPU')
native_build = Path('/home/runner/work/_temp/p06-native-lifetime/work/simx-bf16')
libraries = {name: str(native_build / 'sw/runtime' / name) for name in
             ('libvortex.so', 'libvortex-simx.so', 'libsimx.so')}
libraries.update({'libramulator.so': str(source / 'third_party/ramulator/libramulator.so'),
                  'libramulator-vortex.so': str(source / 'third_party/ramulator_ext/libramulator-vortex.so')})
check(variant['expected_loaded_libraries'] == build['expected_loaded_libraries'] == libraries,
      'expected loader selection independently reconstructed from fixed route')
frozen = DATA / 'artifacts/simx-bf16/frozen'
stamp_paths = ('sw/runtime/simx_rt_config.stamp', 'sw/runtime/simx_config.stamp',
               'tests/regression/ai_counter_preflight/config.stamp')
stamps = []
for relative in stamp_paths:
    descriptor = next(row for stage in variant['retained_builds'] for row in stage['files']
                      if row['path'] == 'artifacts/simx-bf16/frozen/' + relative)
    stamps.append(verify_descriptor(descriptor).read_text())
actual_compiler_records = build_records.validate_records(*stamps, fmt='bf16',
    source=source, build=native_build, jobs=2)
check(actual_compiler_records == variant['compiler_records'] == build['compiler_records'],
      'original BF16 stamps independently reproduce four-role compiler records')
for row in actual_compiler_records:
    config = row['configuration']
    check(config['ITYPE'] == 'bf16' and config['OTYPE'] == 'fp32' and
          config['SIMX_CHECKED_COUNTERS'] == '1' and config['VX_CFG_XLEN'] == '64' and
          config['VX_CFG_TCU_TYPE'] == 'TFR' and config['VX_CFG_FPU_TYPE'] == 'STD',
          'BF16/RV64/checked/TFR/STD selection in ' + row['role'])
    check(not any('P06_PENDING_FORCE_ZERO' in item or 'SIMX_FUNCTIONAL' in item
                  for item in row['macro_flags']), 'no probe mutation or functional mode in ' + row['role'])
for descriptor in variant['retained_binary_payloads'] + report['retained_dependency_payloads']:
    verify_descriptor(descriptor)
check(variant['artifacts_before'] == variant['artifacts_after'] == build['artifacts'],
      'bound build artifacts remain stable')

log_descriptor = next(row for row in report['raw_logs'] if row['path'] == process['log'])
log = verify_descriptor(log_descriptor)
receipt = next(row for row in report['commands'] if row['id'] == PROCESS)
check(receipt['native_process'] is True and receipt['process_started'] is True and
      receipt['outcome'] == 'pass' and receipt['exit_code'] == 0 and
      receipt['cleanup_complete'] is True, 'original native command successful and reaped')
check(receipt['log_sha256'] == log_descriptor['sha256'] and
      receipt['log_size_bytes'] == log_descriptor['size_bytes'], 'raw command log identity')
expected_argv = [str(native_build / parent.APP / 'ai_counter_preflight'), '--lifetime',
                 '--policy', 'per_operation', '--module', str(native_build / parent.APP / 'kernel.vxbin'),
                 '--qualification-id', process['execution_binding_sha256'],
                 '--sample-id', planned['sample_id'], '--pair-index', '0', '--phase', 'warmup']
check(receipt['argv'] == expected_argv, 'exact native argv reconstructed without execution')
check(receipt['environment']['VORTEX_DRIVER'] == 'simx' and
      receipt['environment']['LD_LIBRARY_PATH'] == str(native_build / 'sw/runtime') and
      receipt['environment']['THREADS'] == '1',
      'original native environment route')
check(build['performance_environment'] == {'PERF':'1'} and
      all(next(row for row in report['commands'] if row['id'] == variant[key])['environment']['PERF'] == '1'
          for key in ('backend_build_command','application_build_command')),
      'PERF=1 belongs to actual build commands and the build binding')
observed = records.verify_output(log.read_text(), contract=contract, case=case, fmt='bf16',
    policy='per_operation', binding_id=process['execution_binding_sha256'],
    sample_id=planned['sample_id'], process_id=PROCESS, expected_libraries=libraries)
check(observed == process['observation'] ==
      read_json(verify_descriptor(process['retained_observation'])),
      'trusted raw-reader result exactly reproduces both retained observations')
validate_process_duration(observed['warm'], receipt['duration_seconds'], warm_contract.load_contract(REPO))
check(process['process_duration_seconds'] == receipt['duration_seconds'], 'recorded duration identity')

life, witness, warm = (observed[key] for key in ('lifetime', 'witness', 'warm'))
check(len(life['runs']) == len(warm['operations']) == 33, 'all 33 launches and operations retained')
check(sum(row['checked'] for row in warm['operations']) == 1056 and
      all(row['checked'] == 32 and row['mismatches'] == 0 and row['passed'] is True and
          row['actual_bits'] == case['expected'] and row['dispatch']['launches'] == 1
          for row in warm['operations']), '1056 exact canonical result words and zero mismatches')
check(warm['summary']['checked'] == 1056 and warm['summary']['mismatches'] == 0 and
      warm['summary']['operations'] == 33, 'numerical summary reconciles all operations')
check(warm['summary']['counts']['buffer_create_calls'] ==
      warm['summary']['counts']['buffer_release_calls'] == 99 and
      warm['summary']['counts']['live_buffers'] == 0 and
      warm['summary']['counts']['premature_releases'] == 0 and
      warm['summary']['counts']['errors'] == 0, 'per-operation buffer population and successful release')
check(len(life['reads']) == len(witness['reads']) == 264 and
      len(life['cache_flush_reads']) == len(witness['cache_flush_reads']) == 33,
      'complete read and flush populations')
read_sequences = [row['sequence'] for row in witness['reads']]
flush_sequences = [row['sequence'] for row in witness['cache_flush_reads']]
check(sorted(read_sequences + flush_sequences) == list(range(1, 298)) and
      len(set(read_sequences + flush_sequences)) == 297, 'exact chronological DCR inventory 1 through 297')
check(flush_sequences == [67] + list(range(134, 166)), 'exact flush sequence positions')
check([row['sequence'] for row in life['reads']] == read_sequences and
      [row['sequence'] for row in life['cache_flush_reads']] == flush_sequences,
      'pending read supplements bind exact original DCR sequence')
check(all(row['pending_before'] == row['pending_after'] == 0
          for row in life['reads'] + life['cache_flush_reads']), 'all 594 read/flush pending observations are zero')
check(all(row['completed'] is True and row['status'] == 0 and row['overflow'] is False
          for row in witness['reads'] + witness['cache_flush_reads']), 'all original DCR replies are completed successfully')

opening = life['constructed_state']
baseline = opening['reset_generation']
check(baseline == 1 and opening['generation'] == 1, 'actual construction and reset generation')
prior = opening
run_table = []
all_model_states = [opening, life['destruction']['before']]
for index, run in enumerate(life['runs']):
    ordinal = index + 1
    before, after = run['before'], run['after']
    flush = witness['cache_flush_reads'][index]
    check(run['ordinal'] == ordinal and before['reset_generation'] == baseline + index and
          after['reset_generation'] == baseline + ordinal, 'exact run/reset pair ' + str(ordinal))
    check(before == prior and run['real_call_entered'] is True and run['completed'] is True and
          run['exception'] is False, 'successful real-call chronological join ' + str(ordinal))
    expected_reads = 66 if ordinal == 1 else 131 + ordinal
    check(run['dcr_reads_before'] == run['dcr_reads_after'] == expected_reads and
          run['cache_flushes_before'] == run['cache_flushes_after'] == index,
          'unchanged event counts inside real call ' + str(ordinal))
    check(flush['ticks_before'] == after['ticks'] and flush['ticks_after'] >= after['ticks'] and
          flush['reset_before'] == flush['reset_after'] == baseline + ordinal,
          'run-to-output-flush clock and reset join ' + str(ordinal))
    check(after['core_cycles'] >= before['core_cycles'] and
          after['core_instructions'] >= before['core_instructions'],
          'core cumulative fields do not decrease in run ' + str(ordinal))
    prior = dict(after, ticks=flush['ticks_after'])
    all_model_states.extend((before, after))
    run_table.append({'ordinal': ordinal, 'before_reset': before['reset_generation'],
        'after_reset': after['reset_generation'], 'before_ticks': before['ticks'],
        'run_after_ticks': after['ticks'], 'flush_after_ticks': flush['ticks_after'],
        'core_cycles': after['core_cycles'], 'core_instructions': after['core_instructions']})
    if ordinal == 1:
        check(life['snapshots'][1]['before'] == prior, 'prime snapshot is post-flush model')
check(life['snapshots'][2]['before'] == prior, 'batch snapshot is final post-flush model')
for snap in life['snapshots']:
    check(snap['before'] == snap['after'], 'stable model around snapshot ' + snap['name'])
    all_model_states.extend((snap['before'], snap['after']))
check([row['before']['reset_generation'] for row in life['snapshots']] == [1, 2, 34, 34],
      'actual four snapshot reset generations')
check(life['snapshots'][0]['before'] == opening and
      life['snapshots'][2]['after'] == life['snapshots'][3]['before'] == life['destruction']['before'],
      'construction/opening and final cleanup/destructor equalities')
check(all(row['live'] is True and row['idle'] is True and row['any_running'] is False and
          row['generation'] == 1 and row['pending_reads'] == 0 and row['exitcode'] == 0
          for row in all_model_states), 'all 76 model boundaries are owned, drained and pending zero')
check(len(all_model_states) == 76, '76 extended model states plus 594 read/flush observations = 670 pending checks')
check([(row['device_refs'], row['queues'], row['buffers']) for row in witness['snapshots']] ==
      [(1,0,0),(3,0,1),(3,0,1),(1,0,0)], 'per-operation owner/queue/buffer lifetime')
terminal = witness['snapshots'][-1]
for side in ('cp_before','cp_after'):
    cp = terminal[side]
    check(cp['control'] == cp['queue_control'] == 1 and cp['status'] == cp['error'] == 0 and
          cp['retired'] == cp['expected'], 'enabled error-free retired CP at ' + side)
check(terminal['cp_before']['retired'] == 1158 and terminal['cp_after']['retired'] == 1224,
      'terminal CP retires exactly 66 raw counter queries')
disposal = life['destruction']
check(disposal['completed'] is True and disposal['idle_after'] is True and
      disposal['reset_after'] == 34 and disposal['ticks_after'] == 0,
      'actual destructor completion and live-platform-only after state')
check(disposal['before']['core_cycles'] == 194112 and
      disposal['before']['core_instructions'] == 16797 and disposal['before']['ticks'] == 5900,
      'actual terminal core/clock values')
for value in (report, build, witness, life):
    check(all(value[name] is False for name in parent.FALSE_CLAIMS), 'all seven claims remain false')
    check(value['unresolved_obligations'] == list(parent.UNRESOLVED_OBLIGATIONS),
          'all three original unresolved obligations preserved')

source_hashes = []
for module in tuple(sys.modules.values()):
    file = getattr(module, '__file__', None)
    if not file:
        continue
    path = Path(file).resolve()
    if path.is_relative_to(REPO / 'ci/project') and path.suffix == '.py':
        relative = path.relative_to(REPO).as_posix()
        raw = path.read_bytes()
        committed = subprocess.check_output(['git', 'show', REVISION + ':' + relative], cwd=REPO)
        check(raw == committed, 'trusted imported source matches published blob ' + relative)
        source_hashes.append({'path': relative, 'sha256': hashlib.sha256(raw).hexdigest(), 'size_bytes': len(raw)})
source_hashes.sort(key=lambda row: row['path'])
result = {'scope': 'inert independent BF16/per_operation original review', 'outcome': 'pass',
    'new_native_execution': 'not_run', 'retained_code_executed': False,
    'reviewed_native_revision': REVISION, 'workflow_run_id': 45130300651,
    'artifact_id': 14798140556, 'process_id': PROCESS, 'format': 'bf16', 'policy': 'per_operation',
    'archive_sha256': '3d4879f73c197352689d65feb56e73f537701fc1411e55bf53c92b1b41e13db3',
    'checks_passed': len(checks), 'seconds': time.monotonic() - started,
    'raw_log': log_descriptor, 'build_binding_sha256': variant['build_binding_sha256'],
    'execution_binding_sha256': process['execution_binding_sha256'],
    'counts': {'operations':33,'launches':33,'checked_words':1056,'mismatches':0,
        'raw_half_reads':264,'flush_reads':33,'snapshots':4,'pending_zero_observations':670},
    'case_id': case['id'], 'dimensions': case['dimensions'],
    'snapshot_resets': [row['before']['reset_generation'] for row in life['snapshots']],
    'snapshot_ownership': [{key: row[key] for key in ('name','device_refs','queues','buffers')}
                           for row in witness['snapshots']],
    'terminal': disposal, 'terminal_cp': {key:terminal[key] for key in ('cp_before','cp_after')},
    'library_paths': libraries, 'run_table':run_table,
    'checked_input_descriptors':identities, 'trusted_source_hashes':source_hashes,
    'checks':checks, 'qualified':False, 'ready_for_warm':False, 'phase_acceptance':False,
    'performance_acceptance':False,
    'limitations':['Only this single original process is reviewed here; population-wide and probe reviews are separate.',
        'The original records native timing SimX execution; this checker runs no retained executable.',
        'Product hashes, source bindings and loaded paths do not prove fresh dependency compilation.',
        'No complete 40-component qualification, absolute no-wrap bound, warm speedup or hardware result follows.']}
(WORK / 'w07_a03-receipt.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({key:result[key] for key in ('outcome','process_id','checks_passed','seconds','counts')}))
