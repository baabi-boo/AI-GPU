from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess

SCRATCH = Path('/workspace/scratch/98908dfa3444')
REPO = SCRATCH / 'AI-GPU'
RUN = SCRATCH / 'local-clean-governance-142b'
WORKTREE = Path('/tmp/ai-gpu-governance-142b2d6')
PREFIX = 'w09-hosted-checkpoint-review-142b2d6'
REVISION = '142b2d6aaea2fa4226118b857514113032d2e26c'
TREE = '754ef8577f9a72785c0809048762c70b16cb4857'

def digest(data):
    return {'sha256': hashlib.sha256(data).hexdigest(), 'size_bytes': len(data)}

def git(*args, cwd=WORKTREE):
    return subprocess.check_output(['git', *args], cwd=cwd)

def main():
    receipt = json.loads((RUN / 'receipt.json').read_bytes())
    status = json.loads((RUN / 'status.json').read_bytes())
    assert receipt.get('finished_at') and status.get('event') == 'completed', 'local suite is not complete'
    assert receipt['scope'] == 'isolated-clean-local-governance'
    assert receipt['source_revision'] == REVISION and receipt['source_tree'] == TREE
    assert receipt['working_directory'] == str(WORKTREE)
    assert receipt['hosted_execution'] is False and receipt['native_gpu_execution'] == 'not_run'
    assert all(receipt[name] is False for name in ['qualified', 'ready_for_warm', 'warm_execution', 'acceptance'])
    wrapper = SCRATCH / 'run_clean_governance_142b.py'
    assert wrapper.read_bytes() == (SCRATCH / (PREFIX + '-local-wrapper.py')).read_bytes()
    assert git('rev-parse', 'HEAD').decode().strip() == REVISION
    assert git('rev-parse', 'HEAD^{tree}').decode().strip() == TREE
    assert receipt['git_status_before'] == receipt['git_status_after'] == ''
    current_status = git('status', '--porcelain', '--untracked-files=all').decode()
    assert not current_status, current_status
    assert receipt['source_before'] == receipt['source_after']
    names = git('ls-tree', '-r', '--name-only', REVISION, '--', 'ci/project', '.github/workflows',
                'tests/unittest/checked_counters', 'sim/simx/checked_counters.mk').decode().splitlines()
    assert len(names) == 365
    assert [row['path'] for row in receipt['source_before']] == names
    verified_sources = []
    for row in receipt['source_before']:
        immutable = git('show', REVISION + ':' + row['path'], cwd=REPO)
        observed = (WORKTREE / row['path']).read_bytes()
        assert observed == immutable
        assert digest(immutable) == {key: row[key] for key in ['sha256', 'size_bytes']}, row['path']
        verified_sources.append(row)
    discovery = json.loads((SCRATCH / (PREFIX + '-discovery.json')).read_bytes())
    verified_fixtures = []
    for row in discovery['fixture_inputs']:
        original = git('show', REVISION + ':' + row['path'], cwd=REPO)
        actual = (WORKTREE / row['path']).read_bytes()
        assert actual == original
        assert digest(actual) == {key: row[key] for key in ['sha256', 'size_bytes']}
        verified_fixtures.append({'path': row['path'], **digest(actual)})
    expected_argv = [
        ['ci/project/preflight.py', '--tier', 'governance', '--json'],
        ['ci/project/check_project.py'], ['ci/project/check_baseline_packets.py'],
        ['-m', 'unittest', 'discover', '-s', 'ci/project', '-p', 'test_*.py', '-v'],
    ]
    assert len(receipt['commands']) == 4
    for command, expected in zip(receipt['commands'], expected_argv):
        assert command['argv'] == [receipt['python_executable'], *expected]
        actual = (RUN / (command['label'] + '.log')).read_bytes()
        assert command['log'] == str(RUN / (command['label'] + '.log'))
        assert digest(actual) == {key: command[key] for key in ['sha256', 'size_bytes']}
        assert command['returncode'] == 0 and command['termination_reason'] is None
        assert command['resource_minima']['temporary_free_bytes'] >= receipt['disk_floor_bytes']
        assert command['resource_minima']['available_memory_bytes'] >= receipt['available_memory_floor_bytes']
        assert command['elapsed_seconds'] < receipt['per_command_timeout_seconds']
    assert receipt['disk_floor_bytes'] == 1024 ** 3
    assert receipt['available_memory_floor_bytes'] == 512 * 1024 ** 2
    assert receipt['per_command_timeout_seconds'] == 40 * 60
    spec = importlib.util.spec_from_file_location('independent_log_parser', SCRATCH / 'w09-hosted-checkpoint-review-log.py')
    parser = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parser)
    parser.TERMINAL = re.compile(r'(?:\.\.\. |^)(ok|FAIL|ERROR|expected failure|unexpected success|skipped(?: .*)?)$')
    parsed = parser.parse(RUN / 'unittest.log')
    parsed['path'] = 'unittest.log'
    actual_ids = {row['id'] for row in parsed['test_results']}
    assert actual_ids == set(discovery['all_discovered_test_ids'])
    assert parsed['tests'] == parsed['unique_test_ids'] == 3318
    assert parsed['results'] == {'ok': 3318} and parsed['overall_result'] == 'OK'
    text = (RUN / 'unittest.log').read_text()
    single_line_ok_headers = len(re.findall(r'^test_\S+ \(test_[A-Za-z0-9_.]+\) \.\.\. ok$', text, re.M))
    ellipsis_ok_lines = len(re.findall(r'\.\.\. ok$', text, re.M))
    bare_ok_lines = [i + 1 for i, line in enumerate(text.splitlines()) if line == 'ok']
    assert single_line_ok_headers == 3316 and ellipsis_ok_lines == 3317 and len(bare_ok_lines) == 1
    parent_result = json.loads((REPO / 'docs/project/evidence/p06-counter-diagnostics/host/checkpoint-4268d2d/test-results.json').read_bytes())
    assert set(parsed['multiline_test_result_ids']) == set(parent_result['multiline_test_result_ids']) | {
        'test_sst_setup.SstSetupTests.test_hostless_dispatch_passes_plugin_path_to_both_kernels'}
    assert receipt['commands'][-1]['test_summary'] == [{'tests': 3318, 'seconds': parsed['seconds']}]
    assert receipt['commands'][-1]['ok_footer_observed'] is True
    assert receipt['verification_passed'] is True and receipt['source_closure_unchanged'] is True
    assert status['verification_passed'] is True
    by_id = {row['id']: row for row in parsed['test_results']}
    preflight = json.loads((RUN / 'preflight.log').read_bytes())
    assert preflight['outcome'] == 'pass' and preflight['tier'] == 'governance'
    result = {
        'schema_version': 1, 'reviewer': 'Agent 54 /root/w09_hosted_checkpoint_review',
        'reviewed_at_utc': datetime.now(timezone.utc).isoformat(),
        'evidence_kind': 'independently-reviewed-isolated-local-governance',
        'source_revision': REVISION, 'source_tree': TREE, 'working_directory': str(WORKTREE),
        'outcome': 'pass', 'tests': 3318, 'unique_test_ids': 3318, 'ok': 3318,
        'failures': 0, 'errors': 0, 'skips': 0, 'expected_failures': 0, 'unexpected_successes': 0,
        'seconds': parsed['seconds'], 'exit_code': 0,
        'python_version': receipt['python_version'], 'python_implementation': receipt['python_implementation'],
        'python_executable': receipt['python_executable'], 'platform': receipt['platform'],
        'source_before_after_exact': True, 'git_status_before_after_and_review': '',
        'verified_immutable_source_files': verified_sources, 'verified_fixture_inputs': verified_fixtures,
        'added_test_results': [by_id[name] for name in discovery['added_test_ids']],
        'formerly_failed_test_results': [by_id[name] for name in discovery['old_failed_ids_retained']],
        'selected_module_results': {name: {'tests': module['discovered'],
          'outcomes': dict(Counter(by_id[identifier]['result'] for identifier in module['test_ids']))}
          for name, module in discovery['modules'].items()},
        'commands': receipt['commands'], 'resource_sampling_interval_seconds': 5,
        'resource_limit_scope': 'Governance-only observed temporary free-space and host MemAvailable samples; not native execution budgets or continuous/cgroup attestation',
        'root_receipt_identity': digest((RUN / 'receipt.json').read_bytes()),
        'wrapper_identity': digest(wrapper.read_bytes()),
        'raw_local_log_identity': digest((RUN / 'unittest.log').read_bytes()),
        'raw_local_log_representation': 'Exact subprocess combined stdout/stderr bytes written by the local wrapper; not a GitHub downloaded/decoded log',
        'log_result_reconciliation': {'single_line_ok_headers': single_line_ok_headers,
            'ellipsis_ok_terminals': ellipsis_ok_lines, 'standalone_ok_lines': bare_ok_lines,
            'multiline_result_ids': parsed['multiline_test_result_ids'],
            'reviewer_parser_note': 'The first strict GitHub-log parser attempt stopped on SST stdout interleaved before its standalone ok. Only the reviewer parser was adapted; the original log and tests were unchanged.'},
        'hosted_execution': False, 'hosted_result_claimed': False,
        'native_execution': 'not_run', 'reviewer_reran_tests': False,
        'qualified': False, 'ready_for_warm': False, 'warm_execution': False, 'acceptance': False,
    }
    (SCRATCH / (PREFIX + '-local-completed-analysis.json')).write_text(json.dumps(result, indent=2) + '\n')
    (SCRATCH / (PREFIX + '-local-test-results.json')).write_text(json.dumps(parsed, indent=2) + '\n')
    print(json.dumps({key: result[key] for key in ['outcome', 'tests', 'unique_test_ids', 'seconds',
          'python_version', 'exit_code', 'hosted_execution', 'added_test_results', 'formerly_failed_test_results']}))

if __name__ == '__main__':
    main()
