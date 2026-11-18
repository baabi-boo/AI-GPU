from pathlib import Path
from collections import Counter, defaultdict
import datetime, hashlib, json, re

WORK = Path('${WORK}')
SOURCE = WORK.parent / 'AI-GPU'
PACKET = WORK / 'wgmma-gcc12-formal-evidence'
REVIEW = WORK / 'reviews'
PIN = 'b5b136bb3144613d7c32c47a888f744e864d9dab737c19e954f9da7dabcadb78'
REV = '4af2307e57202c1269e20f893267a5583ad3cba0'
seen = {}

def pairs_unique(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError('duplicate JSON key: ' + key)
        obj[key] = value
    return obj

def parse(raw):
    return json.loads(raw, object_pairs_hook=pairs_unique)

def read(path):
    path = Path(path)
    raw = path.read_bytes()
    seen[str(path)] = {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'size_bytes': len(raw)}
    return raw

def load(path):
    return parse(read(path))

def verify(row, base):
    path = Path(row['path'])
    if not path.is_absolute():
        path = base / path
    raw = read(path)
    assert hashlib.sha256(raw).hexdigest() == row['sha256'], str(path)
    assert len(raw) == row['size_bytes'], str(path)
    return raw

report_raw = read(PACKET/'report.json')
assert hashlib.sha256(report_raw).hexdigest() == PIN and len(report_raw) == 2952368
report = parse(report_raw)
anchor = load(WORK/'formal-completion-anchor.json')
assert anchor['report_sha256'] == PIN and anchor['report_bytes'] == len(report_raw)
assert report['source_revision'] == REV and report['source_dirty'] is False and report['source_stable'] is True
assert report['development'] is False and report['full_matrix_requested'] is True and report['witness_requested'] is True
assert report['state'] == 'finished'
for key in ['outcome', 'arithmetic_outcome', 'witness_outcome', 'parity_outcome']:
    assert report[key] == 'pass', key
for key in ['acceptance_claimed', 'qualifies_P02_A03', 'phase_complete']:
    assert report[key] is False, key
manifest = parse(verify(report['manifest'], SOURCE))
assert manifest['performance']['cycle_tolerance_percent'] == 5
assert manifest['performance']['cycle_relative_denominator'] == 'rtlsim_cycles'
for row in manifest['fixture_inputs']:
    verify(row, SOURCE)
corpus = load(PACKET/'artifacts/source/ci/project/fixtures/p02_wgmma_v1.json')
assert corpus == load(SOURCE/'ci/project/fixtures/p02_wgmma_v1.json')
fixtures = {x['id']:x for x in corpus['cases']}
configs = {x['id']:x for x in manifest['variants']}

commands = {c['id']:c for c in report['commands']}
assert len(commands) == len(report['commands']) == 113
for c in commands.values():
    assert c['outcome'] == 'pass' and c['exit_code'] == 0 and c['process_started'] and c['cleanup_complete']
    assert c['reason'] is None
    verify({'path': c['log'], 'sha256': c['log_sha256'], 'size_bytes': c['log_size_bytes']}, PACKET)

source_snapshot = parse(verify(report['source_before'], PACKET))
assert len(source_snapshot['files']) == 740
for row in source_snapshot['files']:
    verify(row, SOURCE)
source_refs = [v for k,v in report.items() if k.startswith('source_') and isinstance(v,dict) and set(['path','sha256','size_bytes']) <= set(v)]
assert len(source_refs) == 38
for row in source_refs:
    assert parse(verify(row, PACKET)) == source_snapshot
assert verify(report['tools_before'], PACKET) == verify(report['tools_after'], PACKET)
assert report['dependencies_before'] == report['dependencies_after']
assert report['dependency_headers_before'] == report['dependency_headers_after']
assert len(report['dependencies_before']) == 3 and len(report['dependency_headers_before']) == 137
for row in report['source_snapshots']:
    verify(row, PACKET)

variant_ids = {b+'-'+v for b in ['simx','rtlsim'] for v in configs}
assert {v['id'] for v in report['variants']} == variant_ids
launches = []
witness_launches = []
for variant in report['variants']:
    assert variant['outcome'] == 'pass'
    cfg = configs[variant['configuration_id']]
    assert [c['id'] for c in variant['cases']] == cfg['cases']
    assert variant['artifacts_before'] == variant['artifacts_after']
    for row in variant['retained_artifacts']:
        verify(row, PACKET)
    for case in variant['cases']:
        case_id = case['id']
        assert case['arithmetic_outcome'] == case['outcome'] == 'pass'
        lines = read(PACKET/commands[case['command_id']]['log']).decode().splitlines()
        expected = fixtures[case_id]['expected']
        assert len(expected) == 512
        begins, results, perfs, passes = [], [], [], []
        events = defaultdict(list)
        current = None
        major = []
        for number,line in enumerate(lines,1):
            if line.startswith('P02_WGMMA_BEGIN '):
                obj = parse(line.split(' ',1)[1]);begins.append(obj);current=obj['iteration'];major.append('B')
            elif line.startswith('P02_WGMMA_RESULT '):
                obj = parse(line.split(' ',1)[1]);results.append(obj);major.append('R')
            elif line.startswith('P02_WGMMA_PASS '):
                passes.append(parse(line.split(' ',1)[1]));major.append('P')
            elif line.startswith('P02_WGMMA_META '):
                assert variant['backend']=='rtlsim' and cfg['id']=='sparse-fp16-ss' and current in (0,1)
                obj=parse(line.split(' ',1)[1]);obj['raw_line']=number;events[current].append(obj)
            elif line.startswith('PERF: instrs='):
                m=re.fullmatch(r'PERF: instrs=(\d+), cycles=(\d+), IPC=([0-9.]+)',line)
                assert m;perfs.append((int(m[1]),int(m[2])));major.append('F')
            else:
                assert line.startswith(('CONFIGS:','PERF: core0: tcu:','PERF: tcu:')), line[:100]
        assert major == ['B','R','F','B','R','F','P'], (variant['id'],case_id,major)
        assert passes == [{'case_id':case_id,'iterations':2,'checked':1024}]
        previous=(0,0)
        for iteration,(begin,result,perf) in enumerate(zip(begins,results,perfs)):
            for key,value in {'case_id':case_id,'format':cfg['format'],'sparse':cfg['sparse'],'mode':cfg['mode'],'a_layout':cfg['a_layout'],'iteration':iteration}.items():
                assert begin[key] == result[key] == value
            assert {k:begin[k] for k in ['m','n','k','words']} == {'m':64,'n':8,'k':16,'words':512}
            assert result['checked']==512 and result['mismatches']==0
            assert result['actual_bits']==expected and result['expected_bits']==expected
            instructions,cycles=perf[0]-previous[0],perf[1]-previous[1];previous=perf
            assert instructions>0 and cycles>0
            observation=case['observations']['launches'][iteration]
            assert observation['performance']['instructions']==instructions and observation['performance']['cycles']==cycles
            launches.append({'backend':variant['backend'],'configuration':cfg['id'],'case_id':case_id,'iteration':iteration,'instructions':instructions,'cycles':cycles,'words':512})
            if events[iteration]:
                grouped=defaultdict(list)
                for event in events[iteration]:
                    grouped[(event['instance'],event['wis'],event['epoch'],event['sequence'])].append(event)
                assert len(events[iteration])==64 and len(grouped)==16
                warps=Counter();instances=defaultdict(set);ctas=defaultdict(set);wait_sum=0;gaps=[]
                transaction_rows=[]
                for key,tx in grouped.items():
                    assert [e['event'] for e in tx]==['reserve','wait','release','issue']
                    reserve,wait,release,issue=tx
                    for name in ['load_pc','load_uuid','load_cta','wid']:
                        assert len({e[name] for e in tx})==1
                    assert reserve['pc']==release['pc']==reserve['load_pc']=='0x18000017c'
                    assert wait['pc']==issue['pc']=='0x180000180'
                    assert reserve['uuid']==release['uuid']==reserve['load_uuid']
                    assert wait['uuid']==issue['uuid']
                    assert all(e['cta']==reserve['load_cta'] for e in tx)
                    assert reserve['cycle']<=wait['cycle']<release['cycle']<=issue['cycle']
                    assert release['wait_cycles']==issue['wait_cycles']==release['cycle']-wait['cycle']>0
                    assert key[2]==1 and key[3] in (iteration*2+1,iteration*2+2)
                    wid=reserve['wid'];issue_index=int(re.search(r'issue(\d+)-scoreboard$',key[0])[1])
                    assert wid == issue_index + 4*key[1]
                    warps[wid]+=1;instances[key[0]].add(key[1]);ctas[reserve['load_cta']].add(wid)
                    wait_sum+=release['wait_cycles'];gaps.append(issue['cycle']-release['cycle'])
                    transaction_rows.append({'instance':key[0],'wis':key[1],'epoch':key[2],'sequence':key[3],'wid':wid,'cta':reserve['load_cta'],'reserve':reserve['cycle'],'wait':wait['cycle'],'release':release['cycle'],'issue':issue['cycle'],'wait_cycles':release['wait_cycles'],'raw_lines':[e['raw_line'] for e in tx]})
                assert warps==Counter({w:2 for w in range(8)})
                assert len(instances)==4 and all(v=={0,1} for v in instances.values())
                assert len(ctas)==2 and sorted(sorted(x) for x in ctas.values())==[list(range(4)),list(range(4,8))]
                witness_launches.append({'case_id':case_id,'iteration':iteration,'events':64,'transactions':16,'waited_transactions':16,'summed_warp_wait_cycles':wait_sum,'release_issue_gaps':sorted(set(gaps)),'transactions_detail':transaction_rows})
        if variant['backend']=='rtlsim' and cfg['id']=='sparse-fp16-ss':
            assert case['witness_outcome']=='pass'
            assert set(events)=={0,1}

assert len(launches)==48 and sum(x['words'] for x in launches)==24576
lookup={(x['backend'],x['configuration'],x['case_id'],x['iteration']):x for x in launches}
paired=[]
for x in launches:
    if x['backend']!='simx':continue
    y=lookup[('rtlsim',x['configuration'],x['case_id'],x['iteration'])]
    assert x['instructions']==y['instructions']
    gap=abs(x['cycles']-y['cycles'])
    assert gap*100<=y['cycles']*5
    paired.append({'configuration':x['configuration'],'case_id':x['case_id'],'iteration':x['iteration'],'instructions':x['instructions'],'simx_cycles':x['cycles'],'rtlsim_cycles':y['cycles'],'absolute_cycle_difference':gap,'cycle_difference_percent':gap*100/y['cycles']})
assert len(paired)==24 and len(witness_launches)==4
assert sum(x['transactions'] for x in witness_launches)==64
assert sum(x['summed_warp_wait_cycles'] for x in witness_launches)==2748

receipt=load(REVIEW/'w09a-final-command.json')
assert receipt['exit_code']==0 and receipt['independent_report_pin']==PIN
assert '--require-witness' in receipt['argv'] and receipt['argv'][-1]==PIN
assert receipt['trusted_candidate_before']==receipt['trusted_candidate_after']=={'revision':'5e3b74fd569169ad921315223c121a037ae656b7','tree':'97116818da872f43f952a351eb6616fc327be438','dirty':False}
for key in ['anchor_file','report_before','report_after','stdout','stderr']:
    verify(receipt[key], WORK)
assert receipt['verifier_sources_before']==receipt['verifier_sources_after']
for row in receipt['verifier_sources_before']:
    verify(row,WORK/'verifier-candidate')
for key in ['test_source_before','test_source_after']:
    verify(receipt[key], WORK/'verifier-candidate')
for row in receipt['historical_review_files_before']:
    verify(row,WORK)
official=load(REVIEW/'w09a-final-output.json')
assert official['packet_valid'] and official['trust_anchor']=='external_report_sha256' and official['report_sha256']==PIN
assert official['qualification_status']=='independent_review_required' and official['verified_file_count']==1103
assert official['counts']=={'backend_variants':12,'case_executions':24,'checked_output_words':24576,'commands':113,'launches':48,'performance_pairs':12,'witness_case_executions':2}
assert {x['path']:x for x in official['verifier_sources']} == {x['path']:x for x in receipt['verifier_sources_before']}
fix=load(REVIEW/'w09c-data.json')
assert fix['decision']=='approve' and not fix['findings']
for row in fix['artifacts']:
    verify(row,REVIEW)
tests=load(WORK/'verifier-input-fix-clean-tests.json')
assert tests['outcome']=='pass' and tests['exit_code']==0 and tests['source_dirty'] is False
assert tests['source_revision']==receipt['trusted_candidate_before']['revision']
test_log=verify(tests['log'],WORK).decode();assert re.search(r'Ran 22 tests in [0-9.]+s\s+OK\s*$',test_log)
pub=load(WORK/'verifier-fix-publication.json')
assert pub['local_revision']==tests['source_revision'] and pub['local_tree']==pub['published_tree']==tests['tree']
assert pub['published_revision']==pub['branch_readback']['object']['sha']==pub['remote_commit']['sha']=='359a8c007f450a8146540f795cb576b29818fa03'
assert pub['force'] is False
sparse_review=load(REVIEW/'w07f-data.json')
assert sparse_review['review_disposition']=='pass_for_reviewed_sparse_processor_scope' and sparse_review['report_sha256_at_read']==PIN
for key in ['native_binding','raw_correlator_output']:
    verify(sparse_review[key],WORK)
binding=load(REVIEW/'w07f-native-binding.json')
assert binding['outcome']=='pass' and binding['verilator_assert_count']==1 and binding['assertions_reenabled_after_reset'] is True
assert len(binding['bound_issue_local_warp_pairs'])==8 and len(binding['native_fedp_coordinates'])==32 and binding['std_fpu_hierarchy_present']
assert set(binding['dpi_imports'])=={'dpi_assert','dpi_idiv','dpi_imul','dpi_ldiv','dpi_lmul','dpi_register','dpi_trace'}
for key in ['audit_script','generated_assertion_cpp','report','runtime_build_log']:
    verify(binding[key],WORK)
for key in ['native_artifacts','frozen_source_checks']:
    for row in binding[key]:verify(row,WORK)
resources=load(REVIEW/'w08e-data.json')
assert resources['interim'] is False and resources['report']['captured_sha256']==PIN
assert resources['completed_commands']['all_recorded_values_within_budgets'] and resources['completed_commands']['all_started_exit_zero_cleanup_complete_reason_null']
assert not resources['completed_commands']['log_hash_size_mismatches']
assert resources['source_stability']['available_snapshot_count']==38
assert not resources['source_stability']['current_inventory_mismatches'] and not resources['source_stability']['snapshot_identity_or_content_mismatches']
assert resources['tool_stability']['entry_count']==22 and resources['tool_stability']['final_snapshot_equals_initial']
assert resources['dependency_stability']['final_headers_equal_initial'] and resources['dependency_stability']['final_libraries_equal_initial']
assert not resources['dependency_stability']['current_header_mismatches'] and not resources['dependency_stability']['current_library_mismatches']
assert not resources['preservation']['retained_copy_hash_size_mismatches'] and resources['preservation']['successful_build_trees_retained']
assert not resources['waveforms']['waveform_files_in_completed_trees']

for name in ['w09e.md','w09e.json','w07a.md','w07b.md','w07c.md','w07d.md','w07e.md','w07f-final.md','w08e.md','w09a-final.md','w09c.md']:
    read(REVIEW/name)
for identity in list(seen.values()):
    raw=Path(identity['path']).read_bytes()
    assert hashlib.sha256(raw).hexdigest()==identity['sha256'] and len(raw)==identity['size_bytes'], identity['path']
output={'schema_version':1,'outcome':'pass','scope':'Read-only final acceptance corroboration; no compiler/GPU/test-suite execution, no production parser imports','observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source_revision':REV,'report_sha256':PIN,'report_size_bytes':len(report_raw),'commands_checked':113,'raw_case_logs_checked':24,'launches_checked':48,'actual_words_checked_against_frozen_corpus':24576,'source_snapshots_checked':38,'source_inventory_files_checked':740,'retained_source_copies_checked':len(report['source_snapshots']),'retained_variant_artifacts_checked':sum(len(v['retained_artifacts']) for v in report['variants']),'paired_launches':paired,'maximum_cycle_difference_percent':max(x['cycle_difference_percent'] for x in paired),'metadata_witness':{'launches':witness_launches,'events':256,'transactions':64,'waited_transactions':64,'summed_warp_wait_cycles':2748,'summed_waits_are_elapsed_stall_time':False},'official_verified_packet_files':1103,'official_qualification_status':official['qualification_status'],'fix_review':'approve','clean_focused_tests':22,'corrected_verifier_local_revision':tests['source_revision'],'corrected_verifier_published_revision':pub['published_revision'],'corrected_verifier_tree':pub['published_tree'],'consumed_file_count':len(seen),'consumed_files':sorted(seen.values(),key=lambda x:x['path']),'end_recheck':'all consumed identities unchanged','acceptance_claimed':False,'phase_complete':False}
(REVIEW/'w09e-final-proof-data.json').write_text(json.dumps(output,indent=2)+'\n')
print(json.dumps({k:output[k] for k in ['outcome','commands_checked','raw_case_logs_checked','launches_checked','actual_words_checked_against_frozen_corpus','source_snapshots_checked','source_inventory_files_checked','retained_source_copies_checked','retained_variant_artifacts_checked','maximum_cycle_difference_percent','consumed_file_count','official_verified_packet_files']},indent=2))
