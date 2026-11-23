#!/usr/bin/env python3
"""Read-only, source-pinned BF16 original audit; never execute retained content."""
from __future__ import annotations
import collections
import datetime
import hashlib
import json
import os
from pathlib import Path
import shlex
import stat
import sys
import time

sys.dont_write_bytecode = True
SOURCE = Path('/workspace/p06-local-run-source-03')
PACKET = Path('/workspace/p06-local-native-run-03/evidence/native-lifetime')
DEPENDENCY = PACKET.parent / 'dependency-build/report.json'
REVISION = '7251f078972c1d524de06d069e91b014b55896f5'
NATIVE_PIN = 'bba2af32da50326b43c0225f63478a3003865a6fc34eaef2e79b9228697a56d0'
DEPENDENCY_PIN = '202ee0fb2d79d4c47380e41dfb9356a2f353c36f977348442111461d2ffb4924'
OUTPUT = Path('/workspace/scratch/279b6658611e/validation/w08_a03-bf16-review.json')
sys.path.insert(0, str(SOURCE / 'ci/project'))
import p06_dependency_receipt as receipt
import p06_dependency_contract as dependency_contract
import p06_dependency_binary as binary
import p06_dependency_admission as admission
import p06_managed_preflight_build as build_records
import p06_managed_preflight_execute as producer
import p06_managed_preflight_application_build as application
import p06_managed_preflight_generated as generated
import p06_managed_preflight_contract as contract
import p06_native_lifetime_records as lifetime_records
import p06_native_lifetime_contract as lifetime_contract
import p06_compiler_records as compiler_records
import p06_dependency_native_replay as native_replay
from p02_wmma_fixtures import load_cases, render_header
from p03_execution_records import qualification_id
from p02_matrix_records import DISABLED

PROHIBITED = []
def audit(event, args):
    if event in {'subprocess.Popen', 'os.system', 'os.posix_spawn', 'os.exec', 'os.fork', 'pty.spawn'} or event.startswith('socket.'):
        PROHIBITED.append(event)
        raise RuntimeError('Execution/network forbidden during inert review: ' + event)
sys.addaudithook(audit)

def require(value, reason):
    if not value:
        raise AssertionError(reason)

def digest(body):
    return hashlib.sha256(body).hexdigest()

def identity(path):
    body = path.read_bytes()
    return {'sha256': digest(body), 'size_bytes': len(body)}

def snapshot(root):
    result = {}
    for directory, dirs, names in os.walk(root, followlinks=False):
        for name in dirs:
            require(not (Path(directory) / name).is_symlink(), 'packet directory symlink')
        for name in names:
            path = Path(directory) / name
            info = path.lstat()
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'packet file is not unlinked regular data')
            result[path.relative_to(root).as_posix()] = identity(path)
    return result

def verify(row, base=PACKET):
    path = base / row['path']
    actual = identity(path)
    require(actual == {k:row[k] for k in ('sha256','size_bytes')}, 'descriptor differs: ' + str(path))
    return path.read_bytes()

started = time.monotonic()
started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
before = snapshot(PACKET)
require(before['report.json']['sha256'] == NATIVE_PIN, 'native report external pin differs')
report = json.loads((PACKET / 'report.json').read_bytes())
outer_before = identity(PACKET.parent / 'local-execution.json')
outer = json.loads((PACKET.parent / 'local-execution.json').read_bytes())
require(outer['outcome'] == 'fail' and outer['reason'] == 'local child report: JSON structure exceeds the limit', 'unexpected outer result')
require(report['state'] == 'finished' and report['outcome'] == 'pass' and report['reason'] is None, 'native unfinished/failed')
require(report['native_execution'] == 'run' and report['native_lifetime_passed'] is True, 'native actual execution missing')
require(report['expected_revision'] == REVISION, 'wrong expected revision')
require(all(report[k] is False for k in contract.FALSE_CLAIMS), 'native claim promoted')
declared = report['retained_files'] + report['raw_logs']
require(len({r['path'] for r in declared}) == len(declared), 'duplicate native descriptor')
require({r['path'] for r in declared} | {'report.json'} == set(before), 'native packet member inventory differs')
for row in declared:
    verify(row)
source_snapshot = json.loads(verify(report['source_before']))
require(json.loads(verify(report['source_after'])) == source_snapshot, 'source before/after differs')
require(source_snapshot['checkout']['revision'] == REVISION and source_snapshot['checkout']['dirty'] is False, 'source identity differs')
sources = {r['path']:r for r in source_snapshot['files']}
current_source_before = {}
for name, row in sources.items():
    current_source_before[name] = identity(SOURCE / name)
    require(current_source_before[name] == {k:row[k] for k in ('sha256','size_bytes')}, 'current source differs: ' + name)
    require((PACKET / 'artifacts/source' / name).read_bytes() == (SOURCE / name).read_bytes(), 'retained source differs: ' + name)
for row in report['loaded_helpers']:
    require(row == sources[row['path']], 'helper outside pinned source snapshot')
require({row['path'] for row in report['loaded_helpers']} == set(native_replay.RUNNER_HELPERS), 'native loaded helper closure differs')
tools = json.loads(verify(report['tools_before']))
require(json.loads(verify(report['tools_after'])) == tools, 'tool before/after differs')
current_tools_before = {}
for name, row in tools.items():
    path = Path(row['path'])
    require(str(path.resolve(strict=True)) == row['resolved_path'], 'tool symlink target differs')
    current_tools_before[name] = identity(path)
    require(current_tools_before[name] == {k:row[k] for k in ('sha256','size_bytes')}, 'current tool differs: ' + name)

dependency_packet_before = snapshot(DEPENDENCY.parent)
dependency, dependency_result = receipt.load_receipt(DEPENDENCY, DEPENDENCY_PIN, REVISION)
require(verify(report['retained_dependency_receipt']) == DEPENDENCY.read_bytes(), 'native retained dependency report differs')
products = dependency['products']
expected_dependencies = [{'path':relative, **{k:products[name][k] for k in ('sha256','size_bytes')}} for name,relative in dependency_contract.PRODUCTS.items()]
require(json.loads(verify(report['dependencies_before'])) == expected_dependencies, 'dependency product input differs')
require(json.loads(verify(report['dependencies_after'])) == expected_dependencies, 'dependency product final differs')

variant = next(v for v in report['variants'] if v['format'] == 'bf16')
build = Path(variant['build_dir'])
variant_id = 'simx-bf16'
require(variant['id'] == variant_id and variant['outcome'] == 'pass', 'BF16 variant identity differs')
require(variant['artifacts_before'] == variant['artifacts_after'], 'BF16 artifact stability differs')
artifacts = {r['path']:r for r in variant['artifacts_before']}
current_build_before = {}
for name,row in artifacts.items():
    current_build_before[name] = identity(build / name)
    require(current_build_before[name] == {k:row[k] for k in ('sha256','size_bytes')}, 'BF16 current artifact differs: ' + name)
for stage in variant['retained_builds']:
    stem = f'artifacts/{variant_id}/{stage["stage"]}/'
    for row in stage['files']:
        name = row['path'].removeprefix(stem)
        require(row == dict(artifacts[name], path=row['path']), 'retained build descriptor differs')
        verify(row)
for kind in ('retained_binary_payloads', 'retained_dependency_model_payloads'):
    for row in variant[kind]:
        verify(row)
        prefix = f'artifacts/{variant_id}/' + ('binaries/' if kind == 'retained_binary_payloads' else 'dependency-model/')
        name = row['path'].removeprefix(prefix)
        require(row == dict(artifacts[name], path=row['path']), 'retained payload/frozen-artifact join differs')
require(len(variant['retained_binary_payloads']) == 7, 'binary population differs')
require(len(variant['retained_dependency_model_payloads']) == 44, 'model payload population differs')

def source_body(name):
    return (PACKET / 'artifacts/source' / name).read_bytes()
def build_body(name):
    return (PACKET / f'artifacts/{variant_id}/frozen' / name).read_bytes()
generated_result = generated.validate_generated_headers(source_body=source_body, build_body=build_body)
config = source_body('config.mk.in').decode()
version = dict(line.split('=',1) for line in source_body('VERSION').decode().splitlines() if line.strip() and not line.startswith('#'))
replacements = dict(VORTEX_HOME=str(SOURCE),XLEN='64',TOOLDIR=report['paths']['tools'],OSVERSION='ubuntu/focal',INSTALLDIR=str(build/'install'),BUILDDIR=str(build),PROFILE='p02-tfr',**version)
for key,value in replacements.items():
    config = config.replace('@'+key+'@',value)
require(build_body('config.mk') == config.encode(), 'generated config template differs')
require(build_body('sim/rtlsim/verilator.vlt') == source_body('sim/rtlsim/verilator.vlt.in').replace(b'@VORTEX_HOME@',str(SOURCE).encode()), 'generated config VLT differs')
commands = {c['id']:c for c in report['commands']}
def command_log(cid):
    c = commands[cid]
    require(c['exit_code'] == 0 and c['outcome'] == 'pass' and c['cleanup_complete'] is True and c['reason'] is None, 'failed command: '+cid)
    raw = (PACKET/c['log']).read_bytes()
    require(digest(raw) == c['log_sha256'] and len(raw)==c['log_size_bytes'], 'command log pin differs')
    require(c['environment']['CCACHE_DISABLE']=='1' and c['environment']['THREADS']=='1', 'cache/worker environment differs')
    return raw.decode()
model_text=command_log('simx-bf16-dependency-model')
backend_text=command_log('simx-bf16-backend')
app_text=command_log('simx-bf16-application')
model_lines=[shlex.split(line) for line in model_text.splitlines() if line.strip()]
backend_lines=[shlex.split(line) for line in backend_text.splitlines() if line.strip()]
require(len(model_lines)==44 and len(backend_lines)==2, 'raw command graph population differs')
require(all(row[0]==tools['g++']['path'] and '-c' in row for row in model_lines[:43]), 'model compiler/source order differs')
require('-shared' in model_lines[-1] and '-c' not in model_lines[-1], 'model link command differs')
expected_objects={str(build_records.expected_object(name,str(build))) for name in build_records.MODEL_SOURCES}
require({row[row.index('-o')+1] for row in model_lines[:43]}==expected_objects, 'model object population differs')
require(backend_lines[1][0]==tools['g++']['path'] and '-shared' in backend_lines[1], 'backend compile/link differs')
require(len([w for w in backend_lines[1] if w.endswith('.cpp')])==4, 'backend source population differs')
runtime_stamp=build_body('sw/runtime/simx_rt_config.stamp').decode()
model_stamp=build_body('sw/runtime/simx_config.stamp').decode()
link_stamp=build_body(build_records.BACKEND_LINK_STAMP).decode()
app_stamp=build_body(contract.APP+'/config.stamp').decode()
recomputed_model=build_records.validate_build_commands(model_text+'\n'+backend_text,runtime_stamp,model_stamp,link_stamp,source=str(SOURCE),build=str(build),compiler=tools['g++']['path'],make=tools['make']['path'],fmt='bf16',source_files=list(sources),dependency_map=str(build/admission.MODEL_MAP))
require(recomputed_model==variant['model_build_records'], 'strict reconstructed model record differs')
recomputed_compiler=build_records.validate_records(runtime_stamp,model_stamp,app_stamp,fmt='bf16',source=str(SOURCE),build=str(build),jobs=2)
require(recomputed_compiler==variant['compiler_records'], 'compiler role records differ')
recomputed_host=producer.validate_host_build(app_text,app_stamp,source=SOURCE,build=build,compiler=tools['g++']['path'])
require(recomputed_host==variant['host_build_records'], 'host compile record differs')
recomputed_app=application.validate_application_build(app_text,app_stamp,source=SOURCE,build=build,tools_root=Path(report['paths']['tools']),tools=tools,fmt='bf16',compiler_records=recomputed_compiler,source_body=source_body)
require(recomputed_app==variant['application_build_records'] and recomputed_app['command_count']==30, 'application graph differs')
generated_flags=generated.validate_generated_flags(command_log('simx-bf16-expected-flags'),source_body=source_body,fmt='bf16')
initial=compiler_records.validate_header_macros(command_log('simx-bf16-header'))
expanded=dict(compiler_records.validate_header_macros(command_log('simx-bf16-expected-expanded-header')),**{build_records.GUARD:'1'})
backend=dict(initial,PERF_ENABLE='1',**{name+'_DISABLE':'1' for name in DISABLED},**{build_records.GUARD:'1'})
require(initial==variant['header_macros'] and expanded==variant['expected_expanded_header_macros'] and backend==variant['expected_backend_header_macros'],'header macros differ')
for record in recomputed_compiler:
    role=record['role'];cid=f'{variant_id}-{role}-header'
    effective=build_records.validate_effective_header(command_log(cid),backend if role=='backend_cpp' else expanded,role=role)
    require(variant['effective_headers'][role]=={'command_id':cid,'macros':effective},'effective role header differs')
softfloat=products['softfloat']
members=dependency_result['archives']['softfloat']['members']
archives={softfloat['staged_path']:members}
archives.update({row['original_path']:row['members'] for row in dependency['external_archives']})
map_path=f'artifacts/{variant_id}/dependency-model/{admission.MODEL_MAP}'
map_result=binary.validate_link_map((PACKET/map_path).read_text(),cwd=str(build/'sim/simx'),archives=archives,required_archives=[softfloat['staged_path']],required_loads=[products[name]['staged_path'] for name in ('ramulator','extension')])
require(map_result==variant['dependency_model_link']['verification'],'model map reconstruction differs')
loads=collections.Counter(map_result['loads'])
require(all(loads[name]==1 for name in expected_objects),'model map lacks exact object load')
require(all(loads[products[name]['staged_path']]==1 for name in products),'dependency load missing/duplicated')
model_identity = lambda name: dict(artifacts[name], path=str(build/name))
recomputed_link = {'dependency_receipt_sha256':DEPENDENCY_PIN, 'map':model_identity(admission.MODEL_MAP), 'verification':map_result, 'model':model_identity('sw/runtime/libsimx.so'), 'objects':[model_identity(Path(name).relative_to(build).as_posix()) for name in sorted(expected_objects)], 'products':products, 'source_to_model_link_verified':True, **dict.fromkeys(contract.FALSE_CLAIMS,False)}
require(recomputed_link == variant['dependency_model_link'], 'complete dependency/model link binding differs')
build_binding=json.loads(verify(variant['binding']))
require(qualification_id(build_binding)==variant['build_binding_sha256'],'build binding digest differs')
for key,value in [('source',source_snapshot),('loaded_helpers',report['loaded_helpers']),('tools',tools),('dependencies',expected_dependencies),('compiler_records',recomputed_compiler),('model_build_records',recomputed_model),('host_build_records',recomputed_host),('application_build_records',recomputed_app),('dependency_model_link',variant['dependency_model_link']),('generated_identity',variant['generated_identity']),('artifacts',variant['artifacts_before']),('effective_headers',variant['effective_headers']),('expected_loaded_libraries',variant['expected_loaded_libraries'])]:
    require(build_binding[key]==value,'build binding field differs: '+key)

cases=load_cases(SOURCE)
require(render_header(cases)==source_body('tests/regression/sgemm_tcu/p02_fixtures.h'),'frozen header reproduction differs')
selected=contract.select_cases(contract.load_contract(SOURCE),SOURCE)
require(selected==json.loads(verify(report['fixture_snapshot'])),'selected fixture differs')
case=next(c for c in selected if c['format']=='bf16')
admission_summary,admission_stability=native_replay._admission_values(dependency,dependency_result,DEPENDENCY_PIN)
require(report['dependency_admission']==admission_summary and report['dependency_admission_before']==report['dependency_admission_after']==admission_stability, 'dependency admission binding differs')
complete_build_binding={'contract_id':admission.CONTRACT_ID,'contract_sha256':admission.contract_hash(),'source':source_snapshot,'loaded_helpers':report['loaded_helpers'],'format':'bf16','backend':'simx','case':case,'corpus':report['corpus'],'profile_sha256':native_replay.PROFILE_SHA256,'kernel_source_sha256':producer.KERNEL_SHA256,'warm_contract_sha256':contract.WARM_CONTRACT_SHA256,'compiler_records':recomputed_compiler,'model_build_records':recomputed_model,'host_build_records':recomputed_host,'effective_headers':variant['effective_headers'],'generated_identity':variant['generated_identity'],'artifacts':variant['artifacts_before'],'tools':tools,'dependencies':expected_dependencies,'expected_loaded_libraries':variant['expected_loaded_libraries'],'simulation_workers':1,'performance_environment':{'PERF':'1'},'unresolved_obligations':list(contract.UNRESOLVED_OBLIGATIONS),**dict.fromkeys(contract.FALSE_CLAIMS,False),'lifetime_contract':lifetime_contract.contract(),'preflight_contract_sha256':qualification_id(contract.load_contract(SOURCE)),'dependency_receipt_sha256':DEPENDENCY_PIN,'dependency_admission':admission_summary,'application_build_records':recomputed_app,'dependency_model_link':recomputed_link}
require(build_binding==complete_build_binding,'complete reconstructed BF16 build binding differs')
def integer_bf16(bits):
    sign=-1 if bits&0x8000 else 1
    exponent=(bits>>7)&255
    fraction=bits&127
    if exponent==0:
        require(fraction==0,'fixture unexpectedly nonzero subnormal');return 0
    require(exponent!=255,'fixture nonfinite')
    significand=128+fraction;shift=exponent-134
    if shift<0:
        require(significand%(1<<(-shift))==0,'fixture not integer')
        return sign*(significand>>(-shift))
    return sign*(significand<<shift)
def unpack(words):
    return [integer_bf16((int(word,16)>>offset)&65535) for word in words for offset in (0,16)]
def integer_fp32(value):
    if value==0:return '00000000'
    sign=(1<<31) if value<0 else 0; value=abs(value); e=value.bit_length()-1
    require(e<=23,'fixture result not exactly small integer')
    mantissa=(value-(1<<e))<<(23-e)
    return f'{sign|((e+127)<<23)|mantissa:08x}'
a,b=unpack(case['a_words']),unpack(case['b_words'])
values=[sum(a[i*8+k]*b[j*8+k] for k in range(8)) for i in range(8) for j in range(4)]
expected=[integer_fp32(value) for value in values]
require(expected==case['expected'],'independent integer matrix result differs')
require(build_binding['case']==case,'build fixture binding differs')
process_results=[]
for process in [row for row in report['processes'] if row['format']=='bf16']:
    cid=process['id']; text=command_log(cid)
    prefixes=collections.Counter(line.split(' ',1)[0] for line in text.splitlines())
    require(prefixes=={'P06_WARM_OPERATION':33,'P06_WARM_SUMMARY':1,'PASSED!':1,'P06_MANAGED_COUNTER_WITNESS':1,'P06_MANAGED_COUNTER_LIFETIME':1},'raw process marker population differs')
    rows=[json.loads(line.split(' ',1)[1]) for line in text.splitlines() if line.startswith('P06_WARM_OPERATION ')]
    require([r['operation_index'] for r in rows]==list(range(33)),'operation ordering differs')
    require(all(r['actual_bits']==expected and r['checked']==32 and r['mismatches']==0 and r['passed'] is True and r['dispatch']['launches']==1 for r in rows),'independent raw output comparison failed')
    binding=json.loads(verify(process['binding']))
    planned=next(row for row in contract.process_plan(source=SOURCE) if row['id']==cid)
    complete_process_binding={'contract_id':admission.CONTRACT_ID,'contract_sha256':admission.contract_hash(),'build_binding_sha256':variant['build_binding_sha256'],'build':complete_build_binding,'process':planned,'lifetime_contract':lifetime_contract.contract(),'preflight_contract_sha256':qualification_id(contract.load_contract(SOURCE)),'dependency_receipt_sha256':DEPENDENCY_PIN}
    require(binding==complete_process_binding,'complete process binding differs')
    app=build/contract.APP
    expected_argv=[str(app/'ai_counter_preflight'),lifetime_contract.APP_FLAG,'--policy',planned['policy'],'--module',str(app/'kernel.vxbin'),'--qualification-id',process['execution_binding_sha256'],'--sample-id',planned['sample_id'],'--pair-index','0','--phase','warmup']
    command=commands[cid]
    require(command['argv']==expected_argv and command['cwd']==str(app) and command['environment']==dict(report['environment'],VORTEX_DRIVER='simx',LD_LIBRARY_PATH=str(build/'sw/runtime')) and command['timeout_seconds']==180 and command['native_process'] is True,'complete native launch binding differs')
    require(binding['build']==build_binding and binding['build_binding_sha256']==variant['build_binding_sha256'],'process build binding differs')
    require(qualification_id(binding)==process['execution_binding_sha256'],'execution binding digest differs')
    observed=lifetime_records.verify_output(text,contract=contract.load_contract(SOURCE),case=case,fmt='bf16',policy=process['policy'],binding_id=process['execution_binding_sha256'],sample_id=process['sample_id'],process_id=cid,expected_libraries=variant['expected_loaded_libraries'])
    require(observed==process['observation'] and observed==json.loads(verify(process['retained_observation'])),'reconstructed process observation differs')
    witness,lifetime=observed['witness'],observed['lifetime']
    require({row['name']:row['path'] for row in witness['loaded_libraries']}==variant['expected_loaded_libraries'],'loaded library route differs')
    for label in ('witness','lifetime'):
        require(all(observed[label][key] is False for key in contract.FALSE_CLAIMS),'process claim promoted')
    counters=[row for snap in observed['warm']['summary']['snapshots'].values() for row in snap['counters']]
    available=[row for row in counters if row['enabled']]
    unavailable=[row for row in counters if not row['enabled']]
    require(len(available)==132 and len(unavailable)==48,'counter population differs')
    require(all(row['status'] is None and row['value'] is None for row in unavailable),'unavailable rows substituted')
    require(len(lifetime['runs'])==33 and len(lifetime['reads'])==264 and len(lifetime['cache_flush_reads'])==33,'lifetime population differs')
    require(all(run['before']['pending_reads']==run['after']['pending_reads']==0 for run in lifetime['runs']),'pending run balance differs')
    summary=observed['warm']['summary']
    process_results.append({'id':cid,'policy':process['policy'],'log':next(row for row in report['raw_logs'] if row['path']==process['log']),'execution_binding_sha256':process['execution_binding_sha256'],'build_binding_sha256':process['build_binding_sha256'],'process_duration_seconds':process['process_duration_seconds'],'launches':sum(r['dispatch']['launches'] for r in rows),'checked_words':sum(r['checked'] for r in rows),'available_queries':len(available),'unavailable_rows':len(unavailable),'half_replies':len(witness['reads']),'snapshots':len(witness['snapshots']),'cache_flush_reads':len(witness['cache_flush_reads']),'dcr_reads':witness['observation']['dcr_read_completed'],'lifetime_runs':len(lifetime['runs']),'terminal_pending_reads':lifetime['destruction']['before']['pending_reads'],'terminal_core_cycles':lifetime['destruction']['before']['core_cycles'],'terminal_core_instructions':lifetime['destruction']['before']['core_instructions'],'reset_generation_start':lifetime['constructed_state']['reset_generation'],'reset_generation_end':lifetime['destruction']['reset_after'],'allocations':summary['counts']['buffer_create_calls'],'releases':summary['counts']['buffer_release_calls'],'final_live_buffers':summary['counts']['live_buffers'],'all_seven_claims_false':True})
require(len(process_results)==2 and {r['policy'] for r in process_results}=={'per_operation','reusable_single_tile'},'BF16 process policy population differs')

after=snapshot(PACKET)
require(before==after,'native packet changed during review')
require(dependency_packet_before==snapshot(DEPENDENCY.parent),'dependency packet changed during review')
require(outer_before==identity(PACKET.parent/'local-execution.json'),'outer envelope changed during review')
require(current_source_before=={name:identity(SOURCE/name) for name in sources},'current source changed during review')
require(current_tools_before=={name:identity(Path(row['path'])) for name,row in tools.items()},'current tools changed during review')
require(current_build_before=={name:identity(build/name) for name in artifacts},'current BF16 artifacts changed during review')
require(PROHIBITED==[],'execution/network event occurred')
result={'schema_version':1,'reviewer':'w08_a03','scope':'actual-attempt03-BF16-native-original-read-only','outcome':'pass','native_execution_during_review':'not_run','retained_code_executed':False,'source_revision':REVISION,'source_tree':source_snapshot['checkout']['tree'],'native_report':{'path':str(PACKET/'report.json'),**before['report.json']},'dependency_report':{'path':str(DEPENDENCY),**identity(DEPENDENCY)},'source_snapshot':report['source_before'],'outer_outcome':outer['outcome'],'outer_reason':outer['reason'],'native_packet_files':len(before),'native_packet_bytes':sum(r['size_bytes'] for r in before.values()),'native_packet_inventory_sha256':qualification_id(before),'dependency_packet_files':len(dependency_packet_before),'all_original_bytes_unchanged':True,'reviewed_current_source_files':len(sources),'loaded_helpers':len(report['loaded_helpers']),'reviewed_current_tools':len(tools),'reviewed_current_BF16_build_files':len(artifacts),'build':{'model_compilation_commands':43,'backend_translation_units':4,'shared_links':2,'model_payloads':44,'binary_payloads':7,'application_command_count':30,'application_command_counts':recomputed_app['command_counts'],'compiler_roles':[r['role'] for r in recomputed_compiler],'build_binding_sha256':variant['build_binding_sha256'],'generated_headers':generated_result,'generated_flags':generated_flags,'model_link_map':variant['dependency_model_link']['map'],'model_library':variant['dependency_model_link']['model'],'map_selected_archive_members':len(map_result['selected_members']),'map_required_products':{name:products[name]['sha256'] for name in products}},'fixture':{'case_id':case['id'],'method':'signed BF16 integer decode, row-major A x column-major B exact integer accumulation, integer-only IEEE754 FP32 encoding','m':8,'n':4,'k':8,'output_words':32,'integer_values':values,'expected_bits':expected,'all_frozen_fixtures_and_header_reproduced':True},'processes':process_results,'bf16_totals':{k:sum(r[k] for r in process_results) for k in ['launches','checked_words','available_queries','unavailable_rows','half_replies','snapshots','cache_flush_reads','dcr_reads','lifetime_runs']},'prohibited_process_network_events':PROHIBITED,'all_seven_claims_false':True,'limitations':['BF16 evidence only; FP16 is independently reviewed by another agent.','Outer attempt03 failed after native completion; pending and substitution controls did not run in this attempt.','Recorded command and loader observations are consistency evidence, not producer authentication or physical hardware measurement.','No complete 40-component qualification, no-wrap proof, warm performance or phase acceptance is established.'],'started_at':started_at,'finished_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'duration_seconds':round(time.monotonic()-started,6)}
OUTPUT.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
print(json.dumps({'outcome':'pass','output':str(OUTPUT),'identity':identity(OUTPUT),'bf16_totals':result['bf16_totals'],'duration_seconds':result['duration_seconds']}))
