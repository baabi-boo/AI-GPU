"""Read-only final claim/receipt reconciliation; executes no retained code."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zipfile

REPO = Path('/workspace/scratch/ba0248fde989/AI-GPU')
EVIDENCE = REPO / 'docs/project/evidence/p05-python'
OUTPUT = REPO.parent / 'p05-work/w10_a1'
REV = 'e1420fd550f716df33a2556057b7086a03032cbe'
TREE = '3a168adfd345ecb3c15dc02b2583dc832bef6049'

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def load(path):
    return json.loads(path.read_bytes())

def ident(path):
    raw = path.read_bytes()
    return {'path': str(path.relative_to(REPO)), 'size_bytes': len(raw), 'sha256': digest(raw)}

def record(path):
    return load(EVIDENCE / path)

acceptance = record('acceptance-binding.json')
gate_review = record('binding-acceptance-review.json')
aggregate = record('qualification-review.json')
replay = record('relocated-replay.json')
assert digest((EVIDENCE/'acceptance-binding.json').read_bytes()) == '1896bae3b59273f51448b554b965dc7d98d6beafcd446527c41c878a32c740c5'
assert digest((EVIDENCE/'binding-acceptance-review.json').read_bytes()) == '3727a33b843e91d9faa9218182d03a80672d23f2b5cf9ab226edb280abd29ce3'
assert acceptance['outcome'] == 'pass' and acceptance['evidence_level'] == 'simulated'
assert acceptance['acceptance_ids'] == ['P05-A01'] and acceptance['source_revision'] == REV
assert gate_review['outcome'] == aggregate['outcome'] == replay['outcome'] == 'pass'
assert all(row['source_revision'] == REV and row['source_tree'] == TREE for row in (gate_review,aggregate,replay))
assert subprocess.check_output(['git','rev-parse',REV+'^{tree}'],cwd=REPO).decode().strip() == TREE
artifact_paths = [REPO / row['path'] for row in acceptance['artifacts']]
assert len(artifact_paths) == len(set(artifact_paths)) == 57
before = {str(path.relative_to(REPO)): ident(path) for path in artifact_paths}
for descriptor in acceptance['artifacts']:
    assert before[descriptor['path']]['sha256'] == descriptor['sha256']
source_artifacts = []
for path in artifact_paths:
    rel = str(path.relative_to(REPO))
    if not rel.startswith('docs/project/evidence/p05-python/'):
        assert subprocess.check_output(['git','show',REV+':'+rel],cwd=REPO) == path.read_bytes()
        source_artifacts.append(rel)
phase = next(p for p in load(REPO/'docs/project/roadmap.json')['phases'] if p['id']=='P05')
assert phase['status'] == 'in_progress'
assert phase['evidence'] == [{'acceptance_id':'P05-A01','record':'docs/project/evidence/p05-python/acceptance-binding.json'}]
assert gate_review['decision']['P05-A02'] == gate_review['decision']['P05-A03'] == 'unearned'

counts = {'python':Counter(), 'native':Counter()}
archive_checks = []
command_lookup = {}
archive_index = record('archive-index.json')
providers = {a['name'].split('-')[2]:a for a in record('hosted/p05-artifacts.json')['artifacts']}
raw_equalities = 0
for entry in archive_index['archives']:
    fmt = entry['variant'].split('-')[1]
    path = EVIDENCE/'archives'/entry['archive']['path']
    raw = path.read_bytes()
    assert digest(raw) == entry['archive']['sha256'] == providers[fmt]['digest'].split(':')[1]
    assert len(raw) == entry['archive']['size_bytes'] == providers[fmt]['size_in_bytes']
    with zipfile.ZipFile(path) as archive:
        expected = {item['path']:item for item in entry['members']}
        assert len(archive.namelist()) == len(expected) == 304
        assert set(archive.namelist()) == set(expected)
        members = {name:archive.read(name) for name in archive.namelist()}
        for name,body in members.items():
            assert digest(body) == expected[name]['sha256'] and len(body)==expected[name]['size_bytes']
        duplicate_native = 0
        for name,body in members.items():
            if name.startswith('python/native/'):
                assert body == members['native-model/'+name.removeprefix('python/native/')]
                duplicate_native += 1
        report = json.loads(members['python/report.json'])
        native = json.loads(members['python/native/report.json'])
        observations = json.loads(members['python/artifacts/installed-observations.json'])
        source = json.loads(members['python/snapshots/source-before.json'])['checkout']
        assert source['revision'] == REV and source['tree'] == TREE and source['dirty'] is False
        assert source['blockers'] == source['changed_paths'] == source['untracked_paths'] == []
        assert report['format'] == fmt and report['backend'] == 'simx'
        assert len(report['commands']) == 12 and len(native['commands']) == 15
        for packet,prefix in ((report,'python/'),(native,'python/native/')):
            assert packet['outcome']=='pass' and packet['source_stable'] is True
            assert packet['development'] is False and packet['acceptance_claimed'] is False and packet['phase_complete'] is False
            for command in packet['commands']:
                assert command['outcome']=='pass' and command['exit_code']==0
                assert command['process_started'] is True and command['cleanup_complete'] is True and command['reason'] is None
                log = members[prefix+command['log']]
                assert len(log)==command['log_size_bytes'] and digest(log)==command['log_sha256']
                command_lookup[(fmt,command['id'])]=command
        py_matmuls = observations['matmuls']
        n_matmuls = [row for case in report['native_matmuls'] for row in case['observations']]
        py_models = [row['record'] for row in observations['models']]
        n_models = [row for case in native['variants'][0]['cases'] for row in case['observations']]
        assert len(py_matmuls)==len(n_matmuls)==6 and len(py_models)==len(n_models)==10
        for py,native_row in zip(py_matmuls,n_matmuls):
            assert py['case_id']==native_row['case_id'] and py['iteration']==native_row['iteration']
            assert py['actual_bits']==native_row['actual_bits']
            raw_equalities+=1
        for py,native_row in zip(py_models,n_models):
            assert py['source_revision']==native_row['source_revision']==REV
            for key in ('hidden_words','bridge_bytes','bridge_words','output_words'):
                assert py['trace'][key] == native_row['trace'][key]
                raw_equalities+=1
        for route,matmuls,models,trace_key in (
                ('python',py_matmuls,py_models,'trace'),('native',n_matmuls,n_models,'dispatch')):
            target=counts[route]
            target['matmul_runs']+=len(matmuls)
            target['model_runs']+=len(models)
            target['standalone_words']+=sum(len(row['actual_bits']) for row in matmuls)
            for index,row in enumerate(matmuls):
                assert row['iteration']==index%2
                assert row[trace_key]['poison']==(0x7fc0dead,0xdeadbeef)[index%2]
            traces=[row[trace_key] for row in matmuls]
            for index,row in enumerate(models):
                trace=row['trace']
                assert row['iteration']==index%2 and trace['poison']==(0x7fc0dead,0xdeadbeef)[index%2]
                assert len(trace['native'])==3
                traces.extend(stage['dispatch'] for stage in trace['native'])
                target['model_stage_words']+=sum(len(stage['output_words']) for stage in trace['native'])
                target['assembled_words']+=len(trace['output_words'])
                target['bridge_bytes']+=len(bytes.fromhex(trace['bridge_bytes']))
            assert len(traces)==36
            for trace in traces:
                assert trace.get('launches_enqueued',trace.get('launches'))==1
                assert trace.get('writes_enqueued',trace.get('writes'))==3
                assert trace.get('reads_enqueued',trace.get('reads'))==1
                target['launches']+=1
                target['h2d_bytes']+=trace['a_bytes']+trace['b_bytes']+trace['d_bytes']
                target['d2h_bytes']+=trace['d_bytes']
                queried=trace.get('event_profile_queried',[])
                if queried:
                    assert queried==[True]*5 and len(trace['event_profiles'])==5
                    target['profile_pairs']+=5
        archive_checks.append({'format':fmt,**ident(path),'members':len(members),
                               'duplicate_native_members_not_counted_twice':duplicate_native,
                               'commands':27,'source_revision':source['revision'],'source_tree':source['tree']})
assert len(command_lookup)==54
combined=counts['python']+counts['native']
assert combined==Counter(launches=144,profile_pairs=660,h2d_bytes=93696,d2h_bytes=36864,
    matmul_runs=24,model_runs=40,standalone_words=1536,model_stage_words=7680,assembled_words=2560,bridge_bytes=10240)
assert counts['python']['launches']==counts['native']['launches']==72
assert counts['python']['profile_pairs']==360 and counts['native']['profile_pairs']==300

full_flags={'numerics':'full_matrix_verified','dispatch':'full_matrix_checked','provenance':'full_matrix'}
selected_matches=[]
for audit,flag in full_flags.items():
    full=record('reviews/full-'+audit+'.json')
    relocated=record('reviews/replay-'+audit+'.json')
    assert full['outcome']==relocated['outcome']=='pass' and full[flag] is True and relocated[flag] is True
    assert full['auditor_sha256']==digest((EVIDENCE/'reviews'/('audit_'+audit+'.py')).read_bytes())
    for packet in full['packets']:
        fmt=packet['format']
        selected=record('reviews/'+fmt+'-'+audit+'.json')
        assert selected['outcome']=='pass' and selected[flag] is False and selected['packets']==[packet]
        selected_matches.append({'format':fmt,'audit':audit,'identical_packet':True})
    def packet_base(document):
        first=document['packets'][0]
        return (first.get('path') or first['packet']).split('/simx-')[0]
    old=packet_base(full)
    new=packet_base(relocated)
    assert json.dumps(full,sort_keys=True).replace(old,'<PACKETS>') == json.dumps(relocated,sort_keys=True).replace(new,'<PACKETS>')
for command in aggregate['commands']:
    assert command['exit_code']==0 and command['outcome']=='pass' and command['full_matrix'] is True
    for key in ('log','result'):
        descriptor=command[key];raw=(REPO/descriptor['path']).read_bytes()
        assert digest(raw)==descriptor['sha256'] and len(raw)==descriptor['size_bytes']
host=record('development/host/w06_a1_run.json')
assert host['returncode']==0 and host['sources_unchanged'] is True
for command in acceptance['commands']:
    assert command['result']=='pass' and command['exit_code']==0
    match=re.search(r'Retained simx-(fp16|bf16).*\[([^]]+)\]',command['command'])
    if match:
        actual=command_lookup[match.groups()]
        assert ' '.join(actual['argv']) in command['command']
    elif command['command'].startswith('Host-only'):
        assert ' '.join(host['command']) in command['command']
    else:
        assert any(' '.join(actual['command']) in command['command'] for actual in aggregate['commands'])
governance=record('hosted/governance-run.json')
assert governance['head_sha']==REV and governance['conclusion']=='success'
jobs=record('hosted/governance-jobs.json')['jobs']
assert len(jobs)==1 and jobs[0]['conclusion']=='success'
govlog=(EVIDENCE/'hosted/governance-job.log').read_text()
assert re.search(r'Ran 2174 tests in 421\.584s',govlog) and re.search(r'\bOK\b',govlog)
failed=record('development/host/full-host-development.json')
assert failed['exit_code']==1 and failed['changed_during']
failedlog=(EVIDENCE/'development/host/full-host-development.log').read_text()
assert 'FAILED (failures=49, errors=2)' in failedlog
assert 'test_oracle_failure_does_not_verify_a_successful_workload_command' in failedlog
after={str(path.relative_to(REPO)):ident(path) for path in artifact_paths}
assert before==after
result={'schema_version':1,'scope':'read-only independent final acceptance claim reconciliation; no auditor/native/test execution',
        'outcome':'pass','source_revision':REV,'source_tree':TREE,'acceptance_artifacts_verified':len(before),
        'unchanged_qualified_source_artifacts':source_artifacts,'before':before,'after':after,
        'archives':archive_checks,'underlying_command_success_receipts':len(command_lookup),
        'acceptance_commands_matched':len(acceptance['commands']),'raw_route_value_equalities':raw_equalities,
        'counts':{**{k:dict(v) for k,v in counts.items()},'combined':dict(combined)},
        'selected_full_matches':selected_matches,'relocated_full_reports_match':True,
        'hosted_suite':{'tests':2174,'seconds':421.584,'conclusion':'success','source_revision':REV},
        'failed_development_run_retained':True,'P05_status':phase['status'],'accepted_ids':['P05-A01']}
(OUTPUT/'reconciliation.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
print(json.dumps({'outcome':'pass','artifacts':57,'archive_members':608,'commands':54,'counts':dict(combined)},sort_keys=True))
