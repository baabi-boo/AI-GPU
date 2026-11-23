#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Independent inert review of one original FP16 reusable process."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import time

sys.dont_write_bytecode = True
REPO = Path('/tmp/ai-gpu-native-lifetime-dfd857')
WORK = Path('/tmp/ai-gpu-native-lifetime-dfd857-work')
ORIGINAL = WORK / 'native-original/native-lifetime'
REVISION = 'b4127b19a004b5aebb8d52eab9ceda0da3ff4561'
PROCESS = 'preflight-simx-fp16-reusable_single_tile'
sys.path.insert(0, str(REPO / 'ci/project'))
from baseline_packet_io import load_json_bytes
from p03_execution_records import qualification_id
import p06_managed_preflight_contract as parent_contract
import p06_native_lifetime_contract as lifetime_contract
import p06_native_lifetime_records as reader
import p06_warm_contract as warm_contract
from p06_warm_execute import validate_process_duration

started = time.monotonic()
checks = []

def require(condition, label):
    if not condition:
        raise AssertionError(label)
    checks.append(label)

def digest(body):
    return hashlib.sha256(body).hexdigest()

def identity(path):
    body = path.read_bytes()
    return {'sha256': digest(body), 'size_bytes': len(body)}

def descriptor(desc, expected):
    require(desc['path'] == expected, 'fixed retained path: ' + expected)
    actual = identity(ORIGINAL / expected)
    require(actual == {k: desc[k] for k in actual}, 'retained bytes: ' + expected)
    return load_json_bytes((ORIGINAL / expected).read_bytes(), expected)

report_path = ORIGINAL / 'report.json'
report_identity = identity(report_path)
report = load_json_bytes(report_path.read_bytes(), 'managed report')
row = next(x for x in report['processes'] if x['id'] == PROCESS)
variant = next(x for x in report['variants'] if x['id'] == 'simx-fp16')
require(report['expected_revision'] == REVISION, 'native revision')
require(report['state'] == 'finished' and report['outcome'] == 'pass', 'completed managed original')
require(row['outcome'] == variant['outcome'] == 'pass', 'completed process and variant')
contract = parent_contract.load_contract(REPO)
case = next(x for x in parent_contract.select_cases(contract, REPO) if x['format'] == 'fp16')
planned = next(x for x in parent_contract.process_plan(contract, REPO) if x['id'] == PROCESS)
require(all(row[k] == v for k, v in planned.items()), 'process is the live canonical plan')
build = descriptor(variant['binding'], 'snapshots/simx-fp16-build-binding.json')
binding = descriptor(row['binding'], 'snapshots/' + PROCESS + '-binding.json')
retained_observation = descriptor(row['retained_observation'], 'snapshots/' + PROCESS + '-observation.json')
require(build['case'] == case, 'fixture is the current independently validated canonical case')
require(build['source']['checkout']['revision'] == REVISION, 'build source revision')
require(build['source']['checkout']['tree'] == 'bd37fb53ab1c34dfebc2ac8805abff5877735fc4', 'build source tree')
require(qualification_id(build) == row['build_binding_sha256'] == variant['build_binding_sha256'], 'canonical build binding digest')
require(binding['build'] == build and binding['process'] == planned, 'exact nested build and planned process')
require(binding['build_binding_sha256'] == row['build_binding_sha256'], 'process references selected build')
require(qualification_id(binding) == row['execution_binding_sha256'], 'canonical process binding digest')
for item in (build, binding):
    require(item['contract_id'] == lifetime_contract.CONTRACT_ID, 'distinct lifetime binding identity')
    require(item['contract_sha256'] == lifetime_contract.contract_hash(), 'canonical lifetime descriptor digest')
    require(item['lifetime_contract'] == lifetime_contract.contract(), 'complete canonical lifetime descriptor')
    require(item['preflight_contract_sha256'] == qualification_id(contract), 'canonical inherited preflight digest')
source = '/home/runner/work/AI-GPU/AI-GPU'
runtime = '/home/runner/work/_temp/p06-native-lifetime/work/simx-fp16/sw/runtime'
expected_libraries = {
    'libramulator-vortex.so': source + '/third_party/ramulator_ext/libramulator-vortex.so',
    'libramulator.so': source + '/third_party/ramulator/libramulator.so',
    'libsimx.so': runtime + '/libsimx.so',
    'libvortex-simx.so': runtime + '/libvortex-simx.so',
    'libvortex.so': runtime + '/libvortex.so',
}
require(build['expected_loaded_libraries'] == variant['expected_loaded_libraries'] == expected_libraries, 'fixed selected loader paths')
log_name = 'logs/' + PROCESS + '.log'
require(row['log'] == log_name, 'fixed raw log path')
raw = (ORIGINAL / log_name).read_bytes()
raw_identity = {'path': log_name, 'sha256': digest(raw), 'size_bytes': len(raw)}
require(raw_identity == next(x for x in report['raw_logs'] if x['path'] == log_name), 'raw log retained identity')
command = next(x for x in report['commands'] if x['id'] == PROCESS)
require(command['log_sha256'] == digest(raw) and command['log_size_bytes'] == len(raw), 'command raw log identity')
require(command['native_process'] is True and command['process_started'] is True and command['cleanup_complete'] is True and command['exit_code'] == 0 and command['outcome'] == 'pass' and command['reason'] is None, 'successful original native receipt')
app = runtime.rsplit('/sw/runtime', 1)[0] + '/tests/regression/ai_counter_preflight'
expected_argv = [app + '/ai_counter_preflight', '--lifetime', '--policy', 'reusable_single_tile', '--module', app + '/kernel.vxbin', '--qualification-id', row['execution_binding_sha256'], '--sample-id', planned['sample_id'], '--pair-index', '0', '--phase', 'warmup']
require(command['argv'] == expected_argv and command['cwd'] == app, 'exact original selected native argv (not executed by review)')
observed = reader.verify_output(raw.decode('utf-8'), contract=contract, case=case, fmt='fp16', policy='reusable_single_tile', binding_id=row['execution_binding_sha256'], sample_id=planned['sample_id'], process_id=PROCESS, expected_libraries=expected_libraries)
require(observed == retained_observation == row['observation'], 'trusted full reader exactly reproduces both retained observations')
validate_process_duration(observed['warm'], command['duration_seconds'], warm_contract.load_contract(REPO))
checks.append('original host duration covers recorded intervals; no performance acceptance')
lifetime, witness, warm = (observed[k] for k in ('lifetime', 'witness', 'warm'))
for item in (report, build, lifetime, witness):
    require(all(item[k] is False for k in parent_contract.FALSE_CLAIMS), 'seven false claims preserved')
    require(item['unresolved_obligations'] == list(parent_contract.UNRESOLVED_OBLIGATIONS), 'three unresolved obligations preserved')
require(len(lifetime['runs']) == 33 and len(lifetime['reads']) == 264 and len(lifetime['cache_flush_reads']) == 33 and len(lifetime['snapshots']) == 4, 'complete per-process populations')
previous = lifetime['constructed_state']
require(previous['reset_generation'] == 1, 'actual opening reset generation')
models = [previous, lifetime['destruction']['before']]
run_table = []
for j, (run, flush) in enumerate(zip(lifetime['runs'], witness['cache_flush_reads']), 1):
    before, after = run['before'], run['after']
    require(run['ordinal'] == j and before['reset_generation'] == j and after['reset_generation'] == j + 1, 'exact reset pair ' + str(j))
    require(before == previous and run['real_call_entered'] is True and run['completed'] is True and run['exception'] is False, 'admitted run and chronological before join ' + str(j))
    dc = 66 if j == 1 else 131 + j
    require(run['dcr_reads_before'] == run['dcr_reads_after'] == dc and run['cache_flushes_before'] == run['cache_flushes_after'] == j - 1, 'DCR/flush positions ' + str(j))
    require(flush['sequence'] == (67 if j == 1 else 132 + j) and flush['completed_runs'] == j and flush['reset_before'] == flush['reset_after'] == j + 1, 'flush position/reset ' + str(j))
    require(flush['ticks_before'] == after['ticks'] and flush['ticks_after'] - flush['ticks_before'] == 12, 'observed flush clock advance ' + str(j))
    require(after['core_cycles'] >= before['core_cycles'] and after['core_instructions'] >= before['core_instructions'], 'cumulative core observations ' + str(j))
    previous = dict(after, ticks=flush['ticks_after'])
    if j in (1,33):
        require(previous == lifetime['snapshots'][1 if j == 1 else 2]['before'], 'post-flush endpoint snapshot ' + str(j))
    models += [before, after]
    run_table.append({'ordinal':j,'reset_before':before['reset_generation'],'reset_after':after['reset_generation'],'ticks_before':before['ticks'],'ticks_after':after['ticks'],'flush_ticks_after':flush['ticks_after'],'cycles_after':after['core_cycles'],'instructions_after':after['core_instructions']})
for supplemental, original in ((lifetime['reads'], witness['reads']), (lifetime['cache_flush_reads'], witness['cache_flush_reads'])):
    for a,b in zip(supplemental, original):
        require(a['sequence'] == b['sequence'] and a['pending_before'] == a['pending_after'] == 0, 'actual pending supplement ' + str(a['sequence']))
require(sorted(x['sequence'] for x in witness['reads'] + witness['cache_flush_reads']) == list(range(1,298)), '297 exact original DCR events')
for i,snapshot in enumerate(lifetime['snapshots']):
    require(snapshot['before'] == snapshot['after'] and snapshot['before']['reset_generation'] == [1,2,34,34][i], 'unchanged snapshot ' + snapshot['name'])
    models += [snapshot['before'], snapshot['after']]
require(all(m['live'] is True and m['idle'] is True and m['any_running'] is False and m['generation'] == 1 and m['pending_reads'] == 0 for m in models), '76 live quiescent extended-model observations')
require(len(models) == 76, 'extended-model observation count')
pending_observations = len(models) + 2 * (len(lifetime['reads']) + len(lifetime['cache_flush_reads']))
require(pending_observations == 670, '670 zero-pending observations including supplements')
snaps = witness['snapshots']
require([(s['device_refs'],s['queues'],s['buffers']) for s in snaps] == [(1,0,0),(6,0,4),(6,0,4),(1,0,0)], 'actual reusable runtime ownership transitions')
terminal = snaps[-1]
cp_before, cp_after = terminal['cp_before'], terminal['cp_after']
for cp,seq in ((cp_before,1158),(cp_after,1224)):
    require(cp['control'] == cp['queue_control'] == 1 and cp['status'] == cp['error'] == 0 and cp['retired'] == cp['expected'] == seq and cp['runtime_tail'] == cp['tail_register_pair_raw'] == seq * 64, 'enabled drained terminal CP ' + str(seq))
require(cp_after['retired'] - cp_before['retired'] == 66, 'terminal queries retire exactly 66 requests')
require(lifetime['snapshots'][2]['after'] == lifetime['snapshots'][3]['before'] == lifetime['destruction']['before'], 'owner cleanup leaves model unchanged through actual destructor entry')
require(lifetime['destruction']['completed'] is True and lifetime['destruction']['idle_after'] is True and lifetime['destruction']['ticks_after'] == 0 and lifetime['destruction']['reset_after'] == 34, 'actual disposal and platform-only post-state')
operations = warm['operations']
require(len(operations) == 33 and [x['operation_index'] for x in operations] == list(range(33)), 'all 33 original operations')
require(all(x['actual_bits'] == case['expected'] and x['checked'] == 32 and x['mismatches'] == 0 and x['passed'] is True for x in operations), '1056 exact golden result words')
addresses = {(x['dispatch']['a_address'],x['dispatch']['b_address'],x['dispatch']['d_address']) for x in operations}
require(addresses == {(196608,196736,196800)}, 'all operations retain the actual three resident tensor addresses')
require(all(x[s]['buffer_create_calls'] == 3 and x[s]['buffer_release_calls'] == 0 and x[s]['live_buffers'] == 3 for x in operations for s in ('counts_before','counts_after')), 'three tensor buffers remain resident through all operations')
summary = warm['summary']
require(summary['operations'] == 33 and summary['checked'] == 1056 and summary['mismatches'] == 0 and summary['passed'] is True, 'successful numerical summary')
require(summary['counts'] == {'buffer_create_calls':3,'buffer_release_calls':3,'device_open_calls':1,'device_release_calls':1,'errors':0,'live_buffers':0,'live_requested_bytes':0,'peak_requested_payload_bytes':320,'premature_releases':0}, 'final tensor owner accounting balances exactly')
require(summary['memory']['after_open'] == summary['memory']['before_release'], 'reported memory returns to opening baseline')
require(summary['device_release']['status'] == 0 and summary['results']['close'] == {'cleanup':0,'complete':True,'primary':0,'validation':0}, 'successful owner close and device release')
require(len([x for x in warm['counter_deltas'] if x['available']]) == 33 and len([x for x in warm['counter_deltas'] if not x['available']]) == 12, '33 available plus12 unavailable selectors')
source_paths = {
    str(Path(m.__file__).resolve().relative_to(REPO))
    for m in list(sys.modules.values()) if getattr(m,'__file__',None)
    and Path(m.__file__).resolve().is_relative_to(REPO)
}
source_paths |= {
 'ci/project/p06_warm_contract.json','tests/regression/sgemm_tcu/p02_fixtures.h',
 'ci/project/fixtures/p02_layout_v1.json','ci/project/fixtures/p02_tfr_v1.json',
 'ci/project/fixtures/p02_wmma_numerical_v1.json',
 'tests/regression/ai_warm_workspace/main.cpp', 'tests/regression/ai_counter_preflight/hooks.cpp',
 'tests/regression/ai_counter_preflight/main.cpp', 'sw/runtime/ai/runtime.cpp',
}
source_rows=[]
for name in sorted(source_paths):
    live = (REPO/name).read_bytes()
    committed = subprocess.check_output(['git','show',REVISION+':'+name],cwd=REPO)
    require(live == committed, 'trusted source equals reviewed commit: ' + name)
    source_rows.append(dict(path=name,sha256=digest(live),size_bytes=len(live)))
require(identity(report_path) == report_identity and identity(ORIGINAL/log_name) == {k:raw_identity[k] for k in ('sha256','size_bytes')}, 'original report and raw log stable through review')
receipt = {
 'scope':'independent inert original-process review; no new native execution',
 'outcome':'pass','reviewed_revision':REVISION,'original_run_id':45130300651,'original_artifact_id':14798140556,
 'process_id':PROCESS,'raw_log':raw_identity,'process_binding':row['binding'],'observation':row['retained_observation'],
 'canonical_process_binding_sha256':row['execution_binding_sha256'],'canonical_build_binding_sha256':row['build_binding_sha256'],
 'retained_observation_reproduced_exactly':True,'trusted_sources':source_rows,
 'run_pairs':run_table,'pending_zero_observations':pending_observations,
 'snapshots':[{'name':s['name'],**s['before']} for s in lifetime['snapshots']],
 'runtime_ownership':[{'name':s['name'],'device_refs':s['device_refs'],'queues':s['queues'],'buffers':s['buffers']} for s in snaps],
 'terminal_cp':{'before':cp_before,'after':cp_after},'destruction':lifetime['destruction'],
 'accounting':warm['accounting'],'tensor_owner_counts':summary['counts'],
 'resident_addresses':list(next(iter(addresses))),'expected_loaded_libraries':expected_libraries,
 'seven_claims_false':True,'unresolved_obligations':list(parent_contract.UNRESOLVED_OBLIGATIONS),
 'checks':checks,'seconds':time.monotonic()-started,'retained_code_executed':False,'new_native_execution':'not_run',
}
(WORK/'w07_a02-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps({'outcome':'pass','checks':len(checks),'sources':len(source_rows),'seconds':receipt['seconds'],'receipt':str(WORK/'w07_a02-receipt.json')}))
