from pathlib import Path
import hashlib,json,re,shutil
ROOT=Path('/workspace/scratch/ba0248fde989/AI-GPU');P=ROOT/'docs/project/evidence/p05-python';W=ROOT.parent/'p05-work/w09_a1'
REV='e1420fd550f716df33a2556057b7086a03032cbe';TREE='3a168adfd345ecb3c15dc02b2583dc832bef6049'
KINDS=('numerics','dispatch','provenance');FORMATS=('fp16','bf16')
def sha(raw):return hashlib.sha256(raw).hexdigest()
def load(path):return json.loads(path.read_bytes())
def artifact(path):
 raw=path.read_bytes();return {'path':path.relative_to(ROOT).as_posix(),'sha256':sha(raw),'size_bytes':len(raw)}
def full(d):return d.get('full_matrix_verified',d.get('full_matrix_checked',d.get('full_matrix')))
fulls={k:load(P/'reviews'/('full-'+k+'.json')) for k in KINDS}
commands=[];selected=[]
for kind,d in fulls.items():
 assert d['outcome']=='pass' and full(d) is True
 assert not d.get('phase_acceptance',False) and not d.get('acceptance_claimed',False)
 assert d.get('source_revision',REV)==REV and d.get('source_tree',TREE)==TREE
 e=load(W/(kind+'-execution.json'));assert e['exit_code']==0 and e['stable'] and e['before']==e['after']
 assert e['before']['git']==[REV,TREE]
 assert all(len(v)==206 for v in e['before']['packets'].values())
 assert len(e['before']['binding_sources'])==22
 assert d['auditor_sha256']==e['before']['auditors'][kind]['sha256']
 commands.append({'audit':kind,'command':e['command'],'cwd':e['cwd'],'exit_code':e['exit_code'],'elapsed_seconds':e['elapsed_seconds'],'outcome':d['outcome'],'full_matrix':full(d),'input_source_auditor_stable':e['stable'],'result':artifact(P/'reviews'/('full-'+kind+'.json')),'log':artifact(P/'reviews'/('full-'+kind+'.log'))})
 for fmt in FORMATS:
  path=P/'reviews'/(fmt+'-'+kind+'.json');s=load(path)
  assert s['outcome']=='pass' and full(s) is False and len(s['packets'])==1
  packet=next(row for row in d['packets'] if row['format']==fmt)
  assert s['packets'][0]==packet,(fmt,kind,'selected/full packet differs')
  selected.append({'format':fmt,'audit':kind,'selected_scope':True,'full_matrix':False,'packet_identical_to_full_result':True,**artifact(path)})
num=fulls['numerics'];disp=fulls['dispatch'];prov=fulls['provenance'];combined=disp['counts']['combined']
assert num['total_launches']==combined['total_launches']==144
assert num['event_profile_pairs']==combined['event_profile_pairs']==660
for nr,dr in [('native','native_comparison'),('python','python')]:
 n=num['counts'][nr];d=disp['counts'][dr]
 for key in ('matmul_runs','model_runs','matmul_launches','model_launches','total_launches','event_profile_pairs'):assert n[key]==d[key]
assert combined['tensor_h2d_bytes']==93696 and combined['tensor_d2h_bytes']==36864
assert combined['host_bridge_bytes']==combined['host_assembly_bytes']==10240
for fmt in FORMATS:
 n=next(x for x in num['packets'] if x['format']==fmt);d=next(x for x in disp['packets'] if x['format']==fmt);p=next(x for x in prov['packets'] if x['format']==fmt)
 assert n['source_revision']==d['source_revision']==p['revision']==REV and n['source_tree']==d['source_tree']==p['tree']==TREE
 assert n['native_qualification_id']==d['model_qualification_id']==p['native_qualification_id']
 assert n['matmul_qualification_id']==d['matmul_qualification_id']==p['native_matmul_qualification_id']
 assert d['bundle_sha256']==p['bundle_sha256'] and d['binding_source_sha256']==p['binding_source_sha256']
 assert p['installation']['python_version']==[3,12,14] and p['installation']['distribution_version']=='0.1.0'
 assert p['commands_verified']==12 and p['native_commands_verified']==15
 assert p['packages']['sdist_members']==32 and p['packages']['wheel_members']==10 and p['packages']['installed_members']==13
 assert p['native_tool_versions']['g++']['version']=='11.4.0'
idx=load(P/'archive-index.json');provider=load(P/'hosted/p05-artifacts.json');archives=[]
for row in idx['archives']:
 a=artifact(P/'archives'/row['archive']['path']);remote=next(x for x in provider['artifacts'] if row['variant'] in x['name'])
 assert a['sha256']==row['archive']['sha256']==remote['digest'].split(':',1)[1]
 assert a['size_bytes']==row['archive']['size_bytes']==remote['size_in_bytes']
 assert len(row['members'])==304
 archives.append(dict(a,provider_artifact_id=remote['id'],member_count=304))
hosted={}
for name,rid,count in [('p05',44866368565,2),('p04',44866368512,4),('governance',44866368570,1)]:
 run=load(P/'hosted'/(name+'-run.json'));jobs=load(P/'hosted'/(name+'-jobs.json'))['jobs']
 assert run['id']==rid and run['head_sha']==REV and run['conclusion']=='success'
 assert len(jobs)==count and all(j['conclusion']=='success' and j['head_sha']==REV for j in jobs)
 hosted[name]={'run_id':rid,'outcome':'success','job_ids':[j['id'] for j in jobs],'run':artifact(P/'hosted'/(name+'-run.json')),'jobs':artifact(P/'hosted'/(name+'-jobs.json'))}
log=(P/'hosted/governance-job.log').read_text();assert 'Ran 2174 tests in 421.584s' in log and re.search(r'\bOK\b',log)
hosted['governance'].update(tests=2174,seconds=421.584,raw_log=artifact(P/'hosted/governance-job.log'))
if not (W/'run_audit-initial.py').exists():shutil.copyfile(W/'run_audit.py',W/'run_audit-initial.py')
wrapper={'scope':'aggregation-wrapper correction; auditor outputs and commands not rerun','initial_wrapper_exit':1,'affected_audit':'dispatch','auditor_exit':0,'reason':'wrapper read full_matrix_verified/full_matrix but dispatch uses full_matrix_checked','observed_full_matrix_checked':disp['full_matrix_checked'],'original_execution_record':{'path':'dispatch-execution.json','sha256':sha((W/'dispatch-execution.json').read_bytes())},'source_and_auditors_modified':False,'result':'scope independently reconciled against both packets and six selected reports'}
(W/'wrapper-reconciliation.json').write_text(json.dumps(wrapper,indent=2,sort_keys=True)+'\n')
summary={'schema_version':1,'record_id':'p05-copying-binding-full-matrix-independent-review-v1','reviewer':'/root/w09_a1_full_matrix_evidence_review','source_revision':REV,'source_tree':TREE,'scope':'Full two-format retained-data numerical, dispatch and provenance review of the installed copying Python binding on SimX; no new native execution','outcome':'pass','acceptance_claimed':False,'phase_complete':False,'matrix':{'formats':list(FORMATS),'backend':'simx','iterations':2,'supported_matmul_signatures':6,'frozen_model_cases':10},'commands':commands,'selected_reviews':selected,'counts':{'numerics':num['counts'],'dispatch':disp['counts']},'combined_comparisons':{'standalone_fp32_words':sum(x['matmul_words'] for x in num['counts'].values()),'model_hidden_fp32_words':sum(x['model_hidden_words'] for x in num['counts'].values()),'model_stage_output_fp32_words':sum(x['model_hidden_words']+x['model_output_block_words'] for x in num['counts'].values()),'model_bridge_packed_32bit_words':sum(x['model_bridge_words'] for x in num['counts'].values()),'assembled_fp32_words':sum(x['model_output_words'] for x in num['counts'].values())},'archives':archives,'hosted':hosted,'host_history':artifact(P/'development/host-validation.md'),'wrapper_correction':wrapper,'recommendation':{'P05-A01':'Supports bounded acceptance when combined with the independently reviewed host lifecycle/error tests and source-matched clean hosted suite; separate gate reviewer makes the decision.','P05-A02':'Unearned: no implemented or tested PyTorch custom operator.','P05-A03':'Unearned for the framework obligation: no tested framework version; the plain-Python matrix is separately documented.','P05':'Remain in_progress.'},'limitations':['Trusted-builder retained observations establish consistency, not cryptographic execution attestation or reproducible transitive compilation.','The top-level native packet and python/native are copies of the same comparison evidence, not separate executions. Supplemental P04 workflow results are not counted in this P05 matrix.','Native standalone comparison has twelve unprofiled launches; 132 profiled launches produce 660 event/profile pairs, not 720.','Host allocator/fault injection and packaging checks are separate from real installed SimX arithmetic. The clean hosted suite includes overlapping coverage and is not added to the 107+11 host-child count.','Command timings are host simulator measurements; clocks across processes are not aligned, and wait/advance intervals overlap event timings. No physical speed or power claim.','Submodule and cached prerequisite library identities are retained; missing transitive source/compiler/system-library bodies are not reconstructed.','Hosted bound extension and libsimx retain reported RUNPATH entries; arbitrary-host portability, manylinux and complete OS/runtime replay are unqualified.','Source-changing local full-suite and baseline timeout failures remain retained; isolated rechecks and later clean hosted success do not erase them.','No Python RTL/XRT qualification, physical FPGA evidence, arbitrary models, autograd, training, full framework device backend or CUDA compatibility.','P01-A03 vendor hw_emu and inherited DSP267-to283 finding remain unresolved.']}
(P/'qualification-review.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n')
(W/'aggregate-checks.json').write_text(json.dumps({'outcome':'pass','full_audits':3,'selected_reviews':6,'per_format_records_identical':6,'commands':sum(x['commands_verified']+x['native_commands_verified'] for x in prov['packets']),'total_launches':144,'event_profile_pairs':660,'combined_comparisons':summary['combined_comparisons'],'qualification_review':artifact(P/'qualification-review.json')},indent=2,sort_keys=True)+'\n')
print(json.dumps({'outcome':'pass','full_audits':3,'selected_reviews':6,'launches':144,'profile_pairs':660,'qualification_review':artifact(P/'qualification-review.json')},sort_keys=True))
