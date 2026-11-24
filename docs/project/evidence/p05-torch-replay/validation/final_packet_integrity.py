"""Final immutable-artifact/phase/count check, with no source mutation."""
import hashlib
import json
from pathlib import Path
import subprocess

root = Path.cwd().resolve()
packet = root / 'docs/project/evidence/p05-torch-replay'
out = Path('/workspace/scratch/101d52695253/validation/final-packet-integrity.json')
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
read = lambda p: json.loads(p.read_text())
references = []
for name in ('acceptance-torch.json', 'acceptance-compatibility.json'):
    for row in read(packet / name)['artifacts']:
        assert sha(root / row['path']) == row['sha256'], row['path']
        references.append(row['path'])
summary = read(packet / 'validation-summary.json')
for row in summary['artifact_integrity']:
    assert sha(root / row['path']) == row['sha256'], row['path']
for key in ('P05-A02', 'P05-A03'):
    row = summary['acceptance_decision'][key]
    assert sha(root / row['path']) == row['sha256'], key
ledger = read(packet / 'reviews/ledger.json')
assert ledger['actual_distinct_agents_launched'] == ledger['actual_completed_agents'] == 60
rows = ledger['records']
assert len(rows) == len({x['number'] for x in rows}) == len({x['canonical_task_name'] for x in rows}) == 60
assert sorted(x['number'] for x in rows) == list(range(1, 61))
for row in rows:
    assert row['status'] == 'completed' and row['completed'] is True
    assert row['fork_turns'] == 'none' and row['actual_launch_recorded'] is True
    assert row['model_override'] is None and row['reasoning_effort_override'] is None
    assert sha(root / row['report']) == row['report_sha256'], row['report']
assert summary['review_completion']['actual_completed_agents'] == 60
assert summary['review_completion']['ledger_sha256'] == sha(packet / 'reviews/ledger.json')
base = 'f01c9d03147343d274ee0a45b71b34f004709c0e'
git = lambda *a: subprocess.check_output(['git', *a])
before = json.loads(git('show', base + ':docs/project/roadmap.json'))
after = read(root / 'docs/project/roadmap.json')
for old, new in zip(before['phases'], after['phases']):
    if old['id'] != 'P05':
        assert old == new, old['id']
    else:
        assert new['status'] == 'complete'
        assert new['evidence'][0] == old['evidence'][0]
        assert [x['acceptance_id'] for x in new['evidence']] == ['P05-A01','P05-A02','P05-A03']
        assert {k:v for k,v in old.items() if k not in ('status','evidence')} == {k:v for k,v in new.items() if k not in ('status','evidence')}
assert {k:v for k,v in before.items() if k!='phases'} == {k:v for k,v in after.items() if k!='phases'}
protected = ['hw','sim','sw','profiles','ci/baselines','ci/testcases','VERSION',
             'VX_config.toml','VX_types.toml','docs/assets/img/vortex_framework_stack.svg']
assert not git('diff','--name-only',base,'--',*protected).strip()
shared = root / 'docs/project/evidence/p05-torch/reviews/archive_reader.py'
assert sha(shared) == '4144becd4fe3c829380f7e66cdb66f7cf073b5e189c2620cd60c62940b9317d3'
reader = read(packet / 'validation/final-c6-fp16-replay.json')['reader_sources']
for row in reader:
    assert sha(root / row['path']) == row['sha256'], row['path']
result = {'outcome':'pass','scope':'Final integrity, exact phase change and actual completion records; no native execution',
          'cwd':str(root),'head_before_final_docs_commit':git('rev-parse','HEAD').decode().strip(),
          'acceptance_reference_occurrences':len(references),'unique_acceptance_artifacts':len(set(references)),
          'summary_artifacts_verified':len(summary['artifact_integrity']),
          'actual_distinct_agents':60,'actual_completed_agents':60,
          'fresh_context_records':60,'report_hashes_verified':60,
          'reader_source_files_verified':len(reader),
          'only_phase_status_change':'P05 in_progress to complete; A02/A03 added; A01 and frozen criteria unchanged',
          'protected_source_paths_changed':False,'shared_archive_reader_changed':False,
          'ledger_sha256':sha(packet / 'reviews/ledger.json'),
          'criterion_sha256':{name:sha(packet/name) for name in ('acceptance-torch.json','acceptance-compatibility.json')}}
out.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
