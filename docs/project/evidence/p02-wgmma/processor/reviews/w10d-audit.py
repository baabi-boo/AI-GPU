"""Read-only hosted CI evidence audit; writes only this review's derived files."""
from pathlib import Path
from collections import Counter
import hashlib, json, re, subprocess

ROOT = Path(__file__).resolve().parent
WORK = ROOT.parent
EXPECTED = '359a8c007f450a8146540f795cb576b29818fa03'
TREE = '97116818da872f43f952a351eb6616fc327be438'
LOCAL = '5e3b74fd569169ad921315223c121a037ae656b7'
PREVIOUS = 'ad94b696409d4d05c1063541ac014478f90c3e71'
EXECUTION = '4af2307e57202c1269e20f893267a5583ad3cba0'

def read(name):
    return json.loads((ROOT / ('w10d-' + name + '.json')).read_text())

def identity(path):
    body = path.read_bytes()
    return {'file': path.name, 'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest()}

def brief(job):
    return {key: job.get(key) for key in ('id','name','status','conclusion','run_attempt','head_sha','html_url')}

def status(run_name, jobs_name, expected_sha):
    run, data = read(run_name), read(jobs_name)
    assert run['head_sha'] == expected_sha
    assert data['total_count'] == len(data['jobs'])
    assert all(job['head_sha'] == expected_sha for job in data['jobs'])
    counts = Counter(job['status'] + ':' + str(job['conclusion']) for job in data['jobs'])
    bad = [brief(job) for job in data['jobs'] if job['conclusion'] not in (None,'success','neutral','skipped')]
    return {'run_id':run['id'],'run_attempt':run['run_attempt'],'head_sha':run['head_sha'],
            'status':run['status'],'conclusion':run['conclusion'],'run_url':run['html_url'],
            'total_jobs':len(data['jobs']),'job_status_counts':dict(counts),'adverse_jobs':bad,
            'jobs':[brief(job) for job in data['jobs']],
            'pass_claimed':run['status']=='completed' and run['conclusion']=='success'}

capture = read('provenance')
run, jobs, commit = read('governance-run'), read('governance-jobs'), read('commit')
assert run['head_sha'] == EXPECTED and run['status'] == 'completed' and run['conclusion'] == 'success'
assert run['run_attempt'] == 1
assert jobs['total_count'] == len(jobs['jobs']) == 1
job = jobs['jobs'][0]
assert job['id'] == 134590278005 and job['head_sha'] == EXPECTED
assert job['status'] == 'completed' and job['conclusion'] == 'success' and job['run_attempt'] == 1
assert commit['sha'] == EXPECTED and commit['tree']['sha'] == TREE
assert [parent['sha'] for parent in commit['parents']] == [PREVIOUS]
test_steps = [step for step in job['steps'] if step['name'] == 'Test governance tooling']
assert len(test_steps) == 1 and test_steps[0]['conclusion'] == 'success'

raw = (ROOT / 'w10d-governance.log').read_text(encoding='utf-8')
lines = [re.sub(r'\x1b\[[0-9;]*m', '', re.sub(r'^\ufeff?\d{4}-\d{2}-\d{2}T\S+Z ', '', line)) for line in raw.splitlines()]
summaries = [(i + 1, re.fullmatch(r'Ran (\d+) tests in ([0-9.]+)s', line)) for i, line in enumerate(lines)]
summaries = [(line, match) for line, match in summaries if match]
assert len(summaries) == 1
summary_line, summary = summaries[0]
count, duration = int(summary.group(1)), float(summary.group(2))
result_lines = [(i + 1, line) for i, line in enumerate(lines) if line == 'OK']
assert len(result_lines) == 1 and result_lines[0][0] > summary_line
progress = [(i + 1, line) for i, line in enumerate(lines) if re.fullmatch(r'[.FEsexu]+', line)]
assert len(progress) == 1
assert Counter(progress[0][1]) == {'.': count}
commands = [(i + 1, line) for i, line in enumerate(lines) if line == "python3 -m unittest discover -s ci/project -p 'test_*.py'"]
assert len(commands) == 1
assert EXPECTED in lines
assert any(line == 'Source: ' + EXPECTED + ' (tracked changes: False)' for line in lines)
assert 'Project governance validation passed (structure and metadata only; no GPU execution certified).' in lines
assert not any(line.startswith('##[error]') or line.startswith('FAILED (') for line in lines)

candidate = WORK / 'verifier-candidate'
local_tree = subprocess.check_output(['git','show','-s','--format=%T',LOCAL], cwd=candidate, text=True).strip()
assert local_tree == TREE
expected_files = {
 'ci/project/p02_wgmma_packet.py':'11497b57db50c4c1e690d38c406d0de94f86b2017cec036f7ed79008151e72a4',
 'ci/project/test_p02_wgmma_packet.py':'b22daed1c623ae72389da7bf9ab12c242e92ef300d7a7762e3946ec1d38271bf',
}
code = []
for path, expected_hash in expected_files.items():
    body = subprocess.check_output(['git','show',LOCAL+':'+path], cwd=candidate)
    actual = hashlib.sha256(body).hexdigest()
    assert actual == expected_hash
    assert (candidate/path).read_bytes() == body
    code.append({'path':path,'bytes':len(body),'sha256':actual,'source':'committed local tree '+LOCAL,'working_copy_equal':True})

current = status('ci-run','ci-jobs',EXPECTED)
base = status('base-ci-run','base-ci-jobs',EXECUTION)
previous = status('pre-fix-ci-run','pre-fix-ci-jobs',PREVIOUS)
assert not current['adverse_jobs'] and not base['adverse_jobs'] and not previous['adverse_jobs']
assert base['pass_claimed'] and base['job_status_counts'] == {'completed:success':42}

old = json.loads((ROOT / 'w08f.json').read_text())
assert old['expected_commit'] == PREVIOUS and old['governance']['tests']['tests_run'] == 1619
old_log = identity(ROOT/'w08f-governance.log')
assert old_log['sha256'] == 'db44988b1669f7ab6f2786fc7ab95cfff237aefd13db4fe7ea48c5d8850d3e90'

record = {
 'schema':'w10d_corrected_hosted_ci_review_v1','reviewer':'/root/w10d_corrected_ci',
 'verdict':'PASS_CORRECTED_SOURCE_FULL_OFFLINE_GOVERNANCE',
 'observation_capture':capture,'repository':'baabi-boo/AI-GPU',
 'source_identity':{'published_commit':EXPECTED,'published_parent':PREVIOUS,'published_tree':TREE,
                    'equivalent_local_commit':LOCAL,'local_tree':local_tree,'corrected_files':code},
 'governance':{'run_id':run['id'],'run_attempt':run['run_attempt'],'head_sha':run['head_sha'],
               'status':run['status'],'conclusion':run['conclusion'],'run_url':run['html_url'],
               'job':brief(job),'test_step':test_steps[0],
               'tests':{'command_line':commands[0][0],'command':commands[0][1],
                        'summary_line':summary_line,'summary':summary.group(0),
                        'result_line':result_lines[0][0],'result':result_lines[0][1],
                        'tests_run':count,'duration_seconds':duration,'failures':0,'errors':0,'skipped':0,
                        'progress_line':progress[0][0],'progress_counts':dict(Counter(progress[0][1]))}},
 'corrected_source_general_ci':current,
 'execution_source_general_ci':base,
 'historical_pre_fix_general_ci':previous,
 'historical_full_suite':{'published_commit':PREVIOUS,'tests_run':1619,'log_identity':old_log,
                          'distinct_from_corrected_suite':True,'historical_files_unchanged':True},
 'limits':[
    'Hosted governance checks offline tooling, project metadata and baseline packets; it does not run or certify GPU arithmetic.',
    'The completed corrected-source suite is one actual full discovery invocation of 1624 tests, not the sum of earlier 1602, 17, or 22 focused invocations.',
    'The earlier full 1619-test run binds the pre-correction ad94 commit and remains historical evidence.',
    'General CI for corrected 359a8c and historical ad94 was in progress at capture; neither is claimed as complete.',
    'Execution-source 4af general CI completed successfully with all 42 observed jobs successful; that status does not transfer to later commits.',
    'API snapshots are sequential observations, not an atomic snapshot. Non-verbose unittest output provides an aggregate result and progress, not individual test names.',
    'The raw log preserves a nonblocking Node.js action deprecation warning and an explicitly governance-permitted uninitialized-submodule warning.',
 ],
 'artifacts':[identity(ROOT/name) for name in capture['source_urls']]+[identity(ROOT/'w10d-provenance.json'),identity(Path(__file__).resolve())],
 'method':'Read-only GitHub connector retrieval; local parsing and committed-tree identities only. No workflow mutation, retry, cancellation, source edit, build or test rerun.'
}
(ROOT/'w10d.json').write_text(json.dumps(record,indent=2)+'\n')
log_id = identity(ROOT/'w10d-governance.log')
md = f'''# W10D — corrected-source hosted CI review

**PASS: the actual corrected-source full offline Governance suite ran {count:,} tests in {duration:.3f} seconds and returned OK, with zero failures, errors or skips.** This is independently read from the hosted decoded job log and corroborated by run/job metadata, not calculated by adding earlier test counts.

## Source and observed result

- Published commit: `{EXPECTED}`; tree `{TREE}`; parent `{PREVIOUS}`.
- Equivalent committed local tree: `{LOCAL}`. Both changed verifier/test file bodies match their frozen hashes and current candidate bodies; pending documentation changes are outside this code binding.
- Governance [run {run['id']}]({run['html_url']}), attempt 1, job `{job['id']}`: completed / success. The checkout log prints the exact published commit and reports tracked changes False.
- Command: `python3 -m unittest discover -s ci/project -p 'test_*.py'` (raw log line {commands[0][0]}).
- Summary: `{summary.group(0)}` (line {summary_line}); result `OK` (line {result_lines[0][0]}). The sole progress line has exactly {count} success dots and no failure, error or skip markers.
- Exact decoded log: `w10d-governance.log`, {log_id['bytes']:,} bytes, SHA-256 `{log_id['sha256']}`. UTF-8 BOM and ANSI bytes are retained; round-trip equality to the connector text was checked before audit.

The current-response capture completed at `{capture['current_response_capture_completed_at']}`; older-source status capture completed at `{capture['older_response_capture_completed_at']}`. These are non-atomic observations.

## General CI status, separated by source

| Source | Run | Observed result | Job status |
|---|---:|---|---|
| Corrected `{EXPECTED[:7]}` | {current['run_id']} | in progress; no pass claimed | 3 succeeded, 2 running |
| Execution `{EXECUTION[:7]}` | {base['run_id']} | completed / success | all 42 succeeded |
| Historical pre-fix `{PREVIOUS[:7]}` | {previous['run_id']} | in progress; no pass claimed | 28 succeeded, 13 running |

No adverse job conclusion was present in any of those complete returned job lists. These observations are recorded with every job ID and head SHA in `w10d.json`; the retained API JSON is the source of truth if later statuses change.

## Distinction from historical evidence

The earlier hosted full discovery result was **1,619 tests** on `{PREVIOUS}`. Its original review and log remain unchanged; the historical log still hashes to `{old_log['sha256']}`. The new 1,624-test result belongs to the correction at `{EXPECTED}`. The 1,602-test base result and 17-/22-test focused results remain separately scoped; none was added together to infer this full result.

## Limits and reproducibility

Governance validates offline tooling, metadata and baseline packets. It does not itself certify GPU execution; the native qualification remains separately bound to `{EXECUTION}`. The non-verbose suite log has aggregate progress and results, not all individual test names. The action Node.js deprecation and governance-permitted submodule warning are retained and did not fail the job. No running general workflow is labelled complete, and no result is transferred to a later documentation commit.

`w10d-audit.py` independently parses the raw observations, validates source/run/job identity, recounts actual success markers, checks the two committed corrected file hashes and historical log, and regenerates `w10d.json`. All retained response identities, source URLs and capture scope appear in the receipt and `w10d-provenance.json`.

This review used only read-only connector retrieval and bounded local evidence parsing. No workflow mutations, retries, cancellations, builds, source edits, test reruns or subagents were used.
'''
(ROOT/'w10d.md').write_text(md)
print(json.dumps({'verdict':record['verdict'],'tests_run':count,'seconds':duration,'governance_log':log_id,
                  'review':identity(ROOT/'w10d.md'),'receipt':identity(ROOT/'w10d.json'),
                  'current_ci':current['job_status_counts'],'base_ci':base['job_status_counts'],
                  'pre_fix_ci':previous['job_status_counts']},indent=2))
