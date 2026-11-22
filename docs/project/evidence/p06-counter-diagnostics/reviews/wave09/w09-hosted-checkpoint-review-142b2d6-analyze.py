from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess

ROOT = Path('/workspace/scratch/98908dfa3444/AI-GPU')
SCRATCH = ROOT.parent
HOST = ROOT / 'docs/project/evidence/p06-counter-diagnostics/host'
PACKET = HOST / 'checkpoint-142b2d6'
PREFIX = 'w09-hosted-checkpoint-review-142b2d6'
REVISION = '142b2d6aaea2fa4226118b857514113032d2e26c'
TREE = '754ef8577f9a72785c0809048762c70b16cb4857'
LOG = 'run-45040805357-job-137264592244.log'

def digest(data):
    return {'sha256': hashlib.sha256(data).hexdigest(), 'size_bytes': len(data)}

def main():
    discovery = json.loads((SCRATCH / (PREFIX + '-discovery.json')).read_bytes())
    previous = json.loads((HOST / 'checkpoint-4268d2d/test-results.json').read_bytes())
    expected_ids = set(discovery['all_discovered_test_ids'])
    old_ids = {row['id'] for row in previous['test_results']}
    assert len(expected_ids) == 3318 and len(old_ids) == 3312
    assert expected_ids - old_ids == set(discovery['added_test_ids'])
    assert not old_ids - expected_ids
    run = json.loads((PACKET / 'workflow-run-api.json').read_bytes())
    jobs = json.loads((PACKET / 'workflow-jobs-api.json').read_bytes())
    wrapper = json.loads((PACKET / 'jobs-tool-metadata.json').read_bytes())
    assert run['id'] == 45040805357 and run['run_attempt'] == 1
    assert run['head_sha'] == REVISION and run['head_commit']['tree_id'] == TREE
    assert run['repository']['full_name'] == 'baabi-boo/AI-GPU'
    assert run['status'] == 'completed'
    assert jobs['total_count'] == len(jobs['jobs']) == len(wrapper['jobs']) == 1
    job = jobs['jobs'][0]
    assert job['id'] == 137264592244 and job['run_id'] == run['id']
    assert job['head_sha'] == REVISION and job['status'] == 'completed'
    assert job['conclusion'] == wrapper['jobs'][0]['conclusion'] == run['conclusion']
    spec = importlib.util.spec_from_file_location('review_log_parser', SCRATCH / 'w09-hosted-checkpoint-review-log.py')
    parser = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parser)
    parsed = parser.parse(PACKET / LOG)
    parsed['path'] = LOG
    actual_ids = {row['id'] for row in parsed['test_results']}
    results_by_id = {row['id']: row for row in parsed['test_results']}
    assert actual_ids == expected_ids, {'missing': sorted(expected_ids - actual_ids), 'extra': sorted(actual_ids - expected_ids)}
    parsed['expected_checkpoint_discovery_ids_match'] = True
    parsed['parent_ids_retained'] = 3312
    parsed['delta'] = 6
    parsed['added_test_results'] = [results_by_id[name] for name in discovery['added_test_ids']]
    parsed['formerly_failed_test_results'] = [results_by_id[name] for name in discovery['old_failed_ids_retained']]
    parsed['selected_module_results'] = {
        name: {'tests': len(module['test_ids']),
               'outcomes': dict(Counter(results_by_id[name]['result'] for name in module['test_ids']))}
        for name, module in discovery['modules'].items()}
    source_checks = []
    for row in discovery['source_projection']:
        observed = digest((ROOT / row['path']).read_bytes())
        source_checks.append({'path': row['path'], **observed,
                              'matches_checkpoint': all(observed[key] == row[key] for key in observed)})
    fixtures = []
    for row in discovery['fixture_inputs']:
        observed = digest((ROOT / row['path']).read_bytes())
        fixtures.append({'path': row['path'], **observed,
                         'matches_checkpoint': all(observed[key] == row[key] for key in observed)})
    scope_status = subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=all', '--',
                                             'ci/project', '.github/workflows'], cwd=ROOT).decode()
    prior_preserved = []
    for row in discovery['existing_host_files_before']:
        assert row['path'] != 'checkpoint-142b2d6/' + LOG
        if row['path'] == 'index.json':
            original_index = json.loads((SCRATCH / (PREFIX + '-index-before.json')).read_bytes())
            current_index = json.loads((HOST / 'index.json').read_bytes())
            assert current_index['attempts'][:len(original_index['attempts'])] == original_index['attempts']
            assert current_index['logs'][:len(original_index['logs'])] == original_index['logs']
            continue
        observed = digest((HOST / row['path']).read_bytes())
        assert all(observed[key] == row[key] for key in observed), row['path']
        prior_preserved.append(row['path'])
    raw = (PACKET / LOG).read_bytes()
    lines = [parser.ANSI.sub('', parser.STAMP.sub('', line)) for line in raw.decode('utf-8').splitlines()]
    checkout_lines = [i + 1 for i, line in enumerate(lines) if line == REVISION]
    assert len(checkout_lines) == 1
    assert len(parsed['source_lines']) == 1
    assert parsed['source_lines'][0][1] == 'Source: ' + REVISION + ' (tracked changes: False)'
    assert len(parsed['interpreter_lines']) == 1
    version = parsed['interpreter_lines'][0][1].split()[0]
    command = "python3 -m unittest discover -s ci/project -p 'test_*.py' -v"
    assert sum(row[1] == command for row in parsed['command_lines']) == 1
    execution_step = next(row for row in job['steps'] if row['name'] == 'Test governance tooling')
    explicit_exit = [(i + 1, re.search(r'Process completed with exit code ([0-9]+)\.', line))
                     for i, line in enumerate(lines)]
    explicit_exit = [(line, int(match.group(1))) for line, match in explicit_exit if match]
    if execution_step['conclusion'] == 'success':
        assert parsed['overall_result'] == 'OK' and parsed['results'] == {'ok': 3318}
        assert not explicit_exit
        exit_code = 0
        exit_basis = 'Inferred from GitHub success for the sole unittest command under /usr/bin/bash -e; no numeric zero exit line is emitted.'
        outcome = 'pass'
    else:
        assert execution_step['conclusion'] == 'failure'
        assert len(explicit_exit) == 1
        exit_code = explicit_exit[0][1]
        exit_basis = 'Explicit completed-log line ' + str(explicit_exit[0][0])
        outcome = 'fail'
    parsed['exit_code'] = exit_code
    parsed['exit_code_basis'] = exit_basis
    parsed['outcome'] = outcome
    summary = {
        'schema_version': 1, 'reviewer': 'Agent 54 /root/w09_hosted_checkpoint_review',
        'reviewed_at_utc': datetime.now(timezone.utc).isoformat(),
        'source_revision': REVISION, 'source_tree': TREE,
        'workflow_run_id': run['id'], 'workflow_run_attempt': 1, 'job_id': job['id'],
        'url': run['html_url'], 'job_url': job['html_url'],
        'job_started_at': job['started_at'], 'job_completed_at': job['completed_at'],
        'outcome': outcome, 'platform_conclusion': job['conclusion'],
        'tests': parsed['tests'], 'unique_test_ids': parsed['unique_test_ids'],
        'seconds': parsed['seconds'], 'results': parsed['results'],
        'exit_code': exit_code, 'exit_code_basis': exit_basis,
        'python_version': version, 'python_log_line': parsed['interpreter_lines'][0][0],
        'checkout_commit_log_line': checkout_lines[0], 'tracked_cleanliness_log_line': parsed['source_lines'][0][0],
        'before_run_tracked_changes': False, 'before_run_untracked_attestation': 'not_recorded',
        'post_suite_source_snapshot': 'not_retained', 'command': command,
        'added_test_results': parsed['added_test_results'],
        'formerly_failed_test_results': parsed['formerly_failed_test_results'],
        'selected_module_results': parsed['selected_module_results'],
        'source_projection_initial_utc': discovery['observed_at_utc'],
        'source_projection_completion_observed': source_checks,
        'all_353_current_code_workflow_files_match_checkpoint': all(row['matches_checkpoint'] for row in source_checks),
        'source_scope_porcelain': scope_status,
        'current_fixture_inputs': fixtures,
        'all_selected_fixture_inputs_match_checkpoint': all(row['matches_checkpoint'] for row in fixtures),
        'prior_host_files_verified_unchanged_before_append': prior_preserved,
        'prior_four_index_attempts_and_logs_preserved': True,
        'decoded_log': {**digest(raw), 'path': LOG, 'utf8_bom_preserved': raw.startswith(b'\xef\xbb\xbf'),
                        'representation': 'Exact UTF-8 encoding of connector-decoded log text; raw redirected HTTP bytes not observed'},
        'native_execution': 'not_run', 'local_test_execution': 'not_run',
        'qualified': False, 'ready_for_warm': False, 'warm_execution': False, 'acceptance': False,
    }
    (PACKET / 'test-results.json').write_text(json.dumps(parsed, indent=2) + '\n')
    destination = SCRATCH / (PREFIX + '-completed-analysis.json')
    destination.write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({key: summary[key] for key in ['outcome', 'tests', 'unique_test_ids', 'seconds', 'results',
          'exit_code', 'python_version', 'all_353_current_code_workflow_files_match_checkpoint',
          'all_selected_fixture_inputs_match_checkpoint', 'added_test_results', 'formerly_failed_test_results']}))

if __name__ == '__main__':
    main()
