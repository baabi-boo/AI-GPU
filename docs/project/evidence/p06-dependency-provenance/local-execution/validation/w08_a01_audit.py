#!/usr/bin/env python3
"""Read-only, independently selected FP16 audit of the sealed attempt-03 original."""
import sys
sys.dont_write_bytecode=True
import os,json,pathlib,hashlib,struct,subprocess,collections,datetime
SRC=pathlib.Path('/workspace/p06-local-run-source-03')
ROOT=pathlib.Path('/workspace/p06-local-native-run-03/evidence/native-lifetime')
DEP=ROOT.parent/'dependency-build'
OUT=pathlib.Path('/workspace/scratch/279b6658611e/validation/w08_a01-fp16-original-review.json')
REV='7251f078972c1d524de06d069e91b014b55896f5'
REPORT_PIN='bba2af32da50326b43c0225f63478a3003865a6fc34eaef2e79b9228697a56d0'
DEP_PIN='202ee0fb2d79d4c47380e41dfb9356a2f353c36f977348442111461d2ffb4924'
seen={}
def digest(body):return hashlib.sha256(body).hexdigest()
def read(path):
 path=pathlib.Path(path);body=path.read_bytes();row={'sha256':digest(body),'size_bytes':len(body)}
 if str(path) in seen:assert seen[str(path)]==row,('changed during review',str(path))
 seen[str(path)]=row
 return body
def verified(row,base=ROOT):
 p=pathlib.PurePosixPath(row['path']);assert not p.is_absolute() and '..' not in p.parts
 body=read(base/p);assert digest(body)==row['sha256'] and len(body)==row['size_bytes'],row['path']
 return body
def document(row,base=ROOT):return json.loads(verified(row,base))
def identity(path):
 b=read(path);return {'path':str(path),'sha256':digest(b),'size_bytes':len(b)}
def qid(x):return digest(json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode())
# Only these trusted git metadata queries precede the command-execution guard.
git=lambda *args:subprocess.run(['git','-C',str(SRC),*args],check=True,text=True,stdout=subprocess.PIPE,env=dict(os.environ,GIT_OPTIONAL_LOCKS='0')).stdout.strip()
source_checkout={'revision':git('rev-parse','HEAD'),'tree':git('rev-parse','HEAD^{tree}'),'status':git('status','--porcelain=v1')}
assert source_checkout['revision']==REV and source_checkout['status']==''
blocked=[]
def forbid(*args,**kwargs):
 blocked.append(str(args[:1]));raise AssertionError('The FP16 review forbids subprocess execution')
subprocess.run=forbid;subprocess.Popen=forbid;os.system=forbid
for name in ('execv','execve','execvp','execvpe','spawnv','spawnve','spawnvp','spawnvpe','posix_spawn','posix_spawnp'):
 if hasattr(os,name):setattr(os,name,forbid)
sys.path.insert(0,str(SRC/'ci/project'))
import p06_managed_preflight_build as builds
import p06_managed_preflight_application_build as applications
import p06_managed_preflight_generated as generated
import p06_managed_preflight_execute as producer
import p06_native_lifetime_records as lifetime_records
import p06_managed_preflight_contract as contract
import p06_dependency_binary as binary
import p06_dependency_native_replay as native_reader
import p06_dependency_contract as dep_contract
from p06_compiler_records import validate_header_macros
from p02_matrix_records import DISABLED

report_bytes=read(ROOT/'report.json');assert digest(report_bytes)==REPORT_PIN
r=json.loads(report_bytes);assert r['state']=='finished' and r['outcome']=='pass' and not r['failures']
dep_bytes=read(DEP/'report.json');assert digest(dep_bytes)==DEP_PIN
d=json.loads(dep_bytes);assert d['state']=='finished' and d['outcome']=='pass'
assert r['expected_revision']==REV and r['dependency_receipt_sha256']==DEP_PIN
v=next(x for x in r['variants'] if x['id']=='simx-fp16');assert v['outcome']=='pass'
build=pathlib.Path(v['build_dir']);assert build==pathlib.Path('/workspace/p06-local-native-run-03/work/simx-fp16')
source=document(r['source_before']);tools=document(r['tools_before']);deps=document(r['dependencies_before'])
for name,obj in (('source',source),('tools',tools),('dependencies',deps)):
 assert r[name+'_stable'] is True and document(r[name+'_after'])==obj
assert source['checkout']['revision']==REV and source['checkout']['tree']==source_checkout['tree']
assert source['checkout']['dirty'] is False and source['checkout']['changed_paths']==[] and source['checkout']['untracked_paths']==[]
source_rows={x['path']:x for x in source['files']};assert len(source_rows)==1023
for row in source['files']:
 retained=dict(row,path='artifacts/source/'+row['path'])
 assert retained in r['retained_sources'];assert verified(retained)==read(SRC/row['path'])
def source_body(name):return verified(dict(source_rows[name],path='artifacts/source/'+name))
for row in r['loaded_helpers']:assert row==source_rows[row['path']]
assert verified(r['retained_dependency_receipt'])==dep_bytes
prep=document(d['preparation'],DEP)
assert len(prep['toolchain_receipt']['tools'])==11
for name,value in prep['toolchain_receipt']['tools'].items():assert tools[name]==value
shared_tools=sorted(set(d['tools']) & set(tools))
for name in shared_tools:assert d['tools'][name]==tools[name]
for x in r['stability_checks']:
 for name,obj in (('source',source),('tools',tools),('dependencies',deps)):assert x[name+'_sha256']==qid(obj)
 assert x['dependency_admission']==r['dependency_admission_before']==r['dependency_admission_after']
expected_deps=[{'path':rel,'sha256':d['products'][name]['sha256'],'size_bytes':d['products'][name]['size_bytes']} for name,rel in dep_contract.PRODUCTS.items()]
assert deps==expected_deps
for row in deps:
 body=verified(dict(row,path='artifacts/dependencies/'+row['path']))
 product=next(x for x in d['products'].values() if x['staged_path']==str(SRC/row['path']))
 assert body==read(DEP/product['payload'])

assert v['artifacts_before']==v['artifacts_after']
frozen={x['path']:x for x in v['artifacts_before']};assert len(frozen)==77
for stage in v['retained_builds']:
 for row in stage['files']:
  prefix='artifacts/simx-fp16/'+stage['stage']+'/'
  assert row==dict(frozen[row['path'].removeprefix(prefix)],path=row['path']);verified(row)
for name in ('retained_binary_payloads','retained_dependency_model_payloads'):
 for row in v[name]:verified(row)
assert len(v['retained_binary_payloads'])==7 and len(v['retained_dependency_model_payloads'])==44
bodies={}
for row in v['retained_builds'][-1]['files']:
 name=row['path'].removeprefix('artifacts/simx-fp16/frozen/');bodies[name]=verified(row)
def build_body(name):return bodies[name]
headers=generated.validate_generated_headers(source_body=source_body,build_body=build_body)
commands={x['id']:x for x in r['commands']}
fp_commands=[x for x in r['commands'] if 'fp16' in x['id']]
assert len(fp_commands)==15
for c in fp_commands:
 body=read(ROOT/c['log']);assert digest(body)==c['log_sha256'] and len(body)==c['log_size_bytes']
 assert c['outcome']=='pass' and c['exit_code']==0 and c['reason'] is None and c['cleanup_complete'] is True and c['process_started'] is True
 assert c['duration_seconds']<=c['timeout_seconds'] and c['peak_rss_bytes']<r['budget']['max_rss_bytes'] and len(body)<r['budget']['max_log_bytes']
def log(name):return read(ROOT/commands['simx-fp16-'+name]['log']).decode()
runtime_stamp=build_body('sw/runtime/simx_rt_config.stamp').decode()
model_stamp=build_body('sw/runtime/simx_config.stamp').decode()
link_stamp=build_body('sw/runtime/preflight_backend_link.stamp').decode()
app_stamp=build_body('tests/regression/ai_counter_preflight/config.stamp').decode()
compiler=builds.validate_records(runtime_stamp,model_stamp,app_stamp,fmt='fp16',source=str(SRC),build=str(build),jobs=2)
assert compiler==v['compiler_records'] and [x['role'] for x in compiler]==['runtime','backend_cpp','kernel','host']
model=builds.validate_build_commands(log('dependency-model')+'\n'+log('backend'),runtime_stamp,model_stamp,link_stamp,source=str(SRC),build=str(build),compiler=tools['g++']['path'],make=tools['make']['path'],fmt='fp16',source_files=list(source_rows),dependency_map=str(build/'sw/runtime/dependency-model.map'))
assert model==v['model_build_records'] and (model['model_translation_units'],model['backend_translation_units'],model['link_count'])==(43,4,2)
graph=native_reader._backend_graph(log('dependency-model'),log('backend'),compiler=tools['g++']['path'],make=tools['make']['path'],source=SRC,build=build,source_body=source_body)
app=applications.validate_application_build(log('application'),app_stamp,source=SRC,build=build,tools_root=pathlib.Path(r['paths']['tools']),tools=tools,fmt='fp16',compiler_records=compiler,source_body=source_body)
assert app==v['application_build_records'] and app['command_count']==30
host=producer.validate_host_build(log('application'),app_stamp,source=SRC,build=build,compiler=tools['g++']['path']);assert host==v['host_build_records']
flags=generated.validate_generated_flags(log('expected-flags'),source_body=source_body,fmt='fp16')
initial=validate_header_macros(log('header'));assert initial==v['header_macros']
expanded=dict(validate_header_macros(log('expected-expanded-header')),SIMX_CHECKED_COUNTERS='1')
backend=dict(initial,PERF_ENABLE='1',**{name+'_DISABLE':'1' for name in DISABLED},SIMX_CHECKED_COUNTERS='1')
assert expanded==v['expected_expanded_header_macros'] and backend==v['expected_backend_header_macros']
for role in ('runtime','backend_cpp','kernel','host'):
 macros=builds.validate_effective_header(log(role+'-header'),backend if role=='backend_cpp' else expanded,role=role)
 assert macros==v['effective_headers'][role]['macros']
make=[tools['make']['path'],'--no-print-directory','-j2','THREADS=1','CXX='+tools['g++']['path']]
appdir=build/'tests/regression/ai_counter_preflight';runtime=build/'sw/runtime'
expected_argv={
 'configure':[str(SRC/'configure'),'--xlen=64','--profile=p02-tfr','--osversion=ubuntu/focal','--tooldir='+r['paths']['tools']],
 'dependency-model':[*make,'CC='+tools['gcc']['path'],'DESTDIR='+str(runtime),'-f',str(appdir/'dependency_model.mk'),str(runtime/'libsimx.so')],
 'backend':[*make,'CC='+tools['gcc']['path'],'DESTDIR='+str(runtime),'-f',str(appdir/'backend.mk'),str(runtime/'libvortex-simx.so')],
 'application':[*make,'--output-sync=target','all']}
for name,argv in expected_argv.items():assert commands['simx-fp16-'+name]['argv']==argv
for name in ('dependency-model','backend','application'):
 c=commands['simx-fp16-'+name];assert c['environment']['CONFIGS']=='-DITYPE=fp16 -DOTYPE=fp32 -DKUNROLL=1 -DSIMX_CHECKED_COUNTERS=1' and c['environment']['PERF']=='1'

sf=next(x for x in d['archives'] if x['name']=='softfloat')
sfbody=verified(sf['descriptor'],DEP);archive=binary.validate_archive(sfbody,sf['members']);assert len(archive['members'])==309
maprow=next(x for x in v['retained_dependency_model_payloads'] if x['path'].endswith('/dependency-model.map'))
archives={d['products']['softfloat']['staged_path']:sf['members']}
assert d['external_archives']==[]
map_result=binary.validate_link_map(verified(maprow).decode(),cwd=str(build/'sim/simx'),archives=archives,required_archives=list(archives),required_loads=[d['products'][n]['staged_path'] for n in ('ramulator','extension')])
assert map_result==v['dependency_model_link']['verification']
loads=collections.Counter(map_result['loads']);assert all(loads[x]==1 for x in model['object_paths'])
project_roots=[str(SRC)+'/',str(build.parent)+'/',d['paths']['workspace']+'/']
project_loads=[x for x in map_result['loads'] if any(x.startswith(p) for p in project_roots)]
assert sorted(project_loads)==sorted(model['object_paths']+[x['staged_path'] for x in d['products'].values()])
assert v['dependency_model_link']['dependency_receipt_sha256']==DEP_PIN
assert v['dependency_model_link']['products']==d['products']

# Parse ELF dynamic section bytes directly; never invoke a binary or readelf.
def elf(body):
 assert body[:6]==b'\x7fELF\x02\x01';machine=struct.unpack_from('<H',body,18)[0]
 off=struct.unpack_from('<Q',body,40)[0];entsize,count=struct.unpack_from('<HH',body,58)
 sections=[struct.unpack_from('<IIQQQQIIQQ',body,off+i*entsize) for i in range(count)]
 needed=[]
 for s in sections:
  if s[1]!=6:continue
  strings=sections[s[6]];strtab=body[strings[4]:strings[4]+strings[5]]
  for pos in range(s[4],s[4]+s[5],s[9]):
   tag,value=struct.unpack_from('<qQ',body,pos)
   if tag==1:needed.append(strtab[value:strtab.index(b'\0',value)].decode())
 return {'machine':machine,'needed':needed}
elfs={}
for row in v['retained_binary_payloads']:
 body=verified(row)
 if body.startswith(b'\x7fELF'):elfs[pathlib.PurePosixPath(row['path']).name]=elf(body)
assert elfs['libsimx.so']['machine']==62 and elfs['kernel.elf']['machine']==243
assert 'libramulator.so' in elfs['libsimx.so']['needed'] and 'libramulator-vortex.so' in elfs['libsimx.so']['needed']
assert 'libsimx.so' in elfs['libvortex-simx.so']['needed']
assert {'libvortex.so','libvortex-simx.so'}<=set(elfs['ai_counter_preflight']['needed'])

binding=document(v['binding']);assert qid(binding)==v['build_binding_sha256']
for key,value in (('source',source),('tools',tools),('dependencies',deps),('compiler_records',compiler),('model_build_records',model),('host_build_records',host),('application_build_records',app),('artifacts',v['artifacts_before']),('dependency_model_link',v['dependency_model_link'])):assert binding[key]==value
assert binding['format']=='fp16' and binding['dependency_receipt_sha256']==DEP_PIN and binding['simulation_workers']==1
case=next(x for x in document(r['fixture_snapshot']) if x['format']=='fp16')
preflight=document(r['preflight_contract_snapshot']);assert preflight==contract.load_contract(SRC)
process_results=[]
for p in [x for x in r['processes'] if x['format']=='fp16']:
 c=commands[p['command_id']];pb=document(p['binding']);assert pb['build']==binding and pb['build_binding_sha256']==v['build_binding_sha256'] and qid(pb)==p['execution_binding_sha256']
 expected=[str(appdir/'ai_counter_preflight'),'--lifetime','--policy',p['policy'],'--module',str(appdir/'kernel.vxbin'),'--qualification-id',p['execution_binding_sha256'],'--sample-id',p['sample_id'],'--pair-index','0','--phase','warmup']
 assert c['argv']==expected and c['native_process'] is True and c['cwd']==str(appdir)
 assert c['environment']['VORTEX_DRIVER']=='simx' and c['environment']['LD_LIBRARY_PATH']==str(runtime) and c['environment']['THREADS']=='1'
 observed=lifetime_records.verify_output(read(ROOT/p['log']).decode(),contract=preflight,case=case,fmt='fp16',policy=p['policy'],binding_id=p['execution_binding_sha256'],sample_id=p['sample_id'],process_id=p['id'],expected_libraries=v['expected_loaded_libraries'])
 assert observed==p['observation']==document(p['retained_observation'])
 ops=observed['warm']['operations'];lt=observed['lifetime'];w=observed['witness']
 assert len(ops)==33 and len(lt['runs'])==33 and sum(x['checked'] for x in ops)==1056 and sum(x['dispatch']['launches'] for x in ops)==33
 assert all(x['actual_bits']==case['expected'] and x['mismatches']==0 and x['passed'] is True for x in ops)
 assert [x['ordinal'] for x in lt['runs']]==list(range(1,34))
 assert [x['before']['reset_generation'] for x in lt['snapshots']]==[1,2,34,34]
 assert all(x['before']['pending_reads']==x['after']['pending_reads']==0 for x in lt['runs'])
 assert lt['destruction']['before']['pending_reads']==0
 for obj in (r,v['dependency_model_link'],binding,lt,w):assert all(obj[k] is False for k in contract.FALSE_CLAIMS)
 assert {x['name']:x['path'] for x in w['loaded_libraries']}==v['expected_loaded_libraries']
 count=producer.completion_counts([{'outcome':'pass','observation':observed}])
 process_results.append({'id':p['id'],'policy':p['policy'],'execution_binding_sha256':p['execution_binding_sha256'],'log_sha256':c['log_sha256'],'log_size_bytes':c['log_size_bytes'],'duration_seconds':c['duration_seconds'],'peak_rss_bytes':c['peak_rss_bytes'],'counts':count,'runs':len(lt['runs']),'snapshot_reset_generations':[x['before']['reset_generation'] for x in lt['snapshots']],'terminal_pending_reads':lt['destruction']['before']['pending_reads'],'loaded_libraries':w['loaded_libraries'],'allocation_counts':observed['warm']['summary']['counts']})
assert [x['policy'] for x in process_results]==['per_operation','reusable_single_tile']
counts={k:sum(x['counts'][k] for x in process_results) for k in process_results[0]['counts']}
assert counts=={'available_queries':264,'cache_flush_reads':66,'checked_words':2112,'dcr_reads':594,'half_replies':528,'launches':66,'processes':2,'snapshots':8,'unavailable_rows':96}
outer_body=read(ROOT.parent/'local-execution.json');outer=json.loads(outer_body)
assert outer['outcome']=='fail' and outer['reason']=='local child report: JSON structure exceeds the limit'
assert [x['id'] for x in outer['stages']]==['preparation','dependency-build','native-lifetime']
assert not blocked
for path,row in seen.items():
 body=pathlib.Path(path).read_bytes();assert digest(body)==row['sha256'] and len(body)==row['size_bytes'],('closing stability',path)
summary={
 'schema_version':1,'review':'wave-08-agent-01-actual-fp16-native-original','outcome':'pass','scope':'sealed attempt-03 FP16 native variant; not the enclosing local execution or controls','reviewed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'outer_execution':{'sha256':digest(outer_body),'size_bytes':len(outer_body),'outcome':outer['outcome'],'reason':outer['reason'],'completed_stages':[x['id'] for x in outer['stages']]},'native_report':{'sha256':REPORT_PIN,'size_bytes':len(report_bytes)},'dependency_receipt':{'sha256':DEP_PIN,'size_bytes':len(dep_bytes)},'source_checkout':source_checkout,'source_snapshot':r['source_before'],'source_files_checked':len(source_rows),'source_bytes_checked':sum(x['size_bytes'] for x in source_rows.values()),'loaded_helpers_checked':len(r['loaded_helpers']),'prepared_native_tool_identities_checked':11,'shared_dependency_native_tools':shared_tools,'stability_observations_checked':len(r['stability_checks']),'fp16_build_binding_sha256':v['build_binding_sha256'],'fp16_binding_file':v['binding'],'build_graph':graph,'model_translation_units':43,'backend_translation_units':4,'model_backend_links':2,'application_build':app,'generated_headers':headers,'generated_flags':flags,'compiler_roles':[x['role'] for x in compiler],'effective_header_configuration_verified':True,'artifacts_before_after_checked':len(frozen),'retained_build_stages':{s['stage']:len(s['files']) for s in v['retained_builds']},'retained_binaries':v['retained_binary_payloads'],'retained_model_object_count':43,'model_map':maprow,'model_map_load_count':len(map_result['loads']),'softfloat_archive_members':309,'model_map_selected_archive_members':len(map_result['selected_members']),'dependency_products':d['products'],'elf_dynamic_dependencies':elfs,'processes':process_results,'fp16_counts':counts,'commands_checked':len(fp_commands),'maximum_sampled_command_rss_bytes':max(x['peak_rss_bytes'] for x in fp_commands),'budget':r['budget'],'retained_or_native_commands_executed':False,'subprocess_execution_attempts_under_guard':len(blocked),'closing_rehash_files':len(seen),'closing_rehash_bytes':sum(x['size_bytes'] for x in seen.values()),'all_reviewed_files_stable':True,'claims':{k:False for k in contract.FALSE_CLAIMS},'limitations':['FP16 scope only; BF16 and the complete original are reviewed separately.','Attempt 03 enclosing local orchestration failed after native success because its generic JSON reader exceeded a structural limit; neither pending nor substitution control ran in that attempt.','No native rerun, compiler invocation, retained-code execution or command-string execution was performed by this reviewer.','Native logs plus retained consistency do not authenticate the producer or inventory all host/system/compiler runtime dependencies.','Polled RSS and disk limits are observed budgets, not cgroup or filesystem quotas.','Complete 40-component qualification, no-wrap bounds, warm performance, and phase acceptance remain open.']}
OUT.write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n')
print(json.dumps({'output':str(OUT),'sha256':digest(OUT.read_bytes()),'counts':counts,'files_rehashed':len(seen),'source_files':len(source_rows),'outcome':'pass'}))
