#!/usr/bin/env python3
"""Retain a small, source-bound summary of a finished diagnostic attempt."""
from collections import Counter
import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path('/workspace/AI-GPU')
PACKET = ROOT / 'docs/project/evidence/p06-dependency-provenance/host-diagnostic'
WORKSPACE = Path('/workspace/p06-host-diagnostic-fixed-05')
EVIDENCE = WORKSPACE / 'evidence'
HELPERS = Path('/workspace/p06-dependency-corrected')
REVISION = '19333193192ba5a2d3667c0111235ec9e21a5898'
TREE = 'baeeb7bc7078e9301c68e94b1207032329be343d'
FALSE_CLAIMS = ('qualified', 'ready_for_warm', 'warm_execution', 'full_warm_coverage',
                'acceptance_claimed', 'phase_acceptance', 'performance_acceptance')

def identity(path, relative_to=None):
    assert path.is_file() and not path.is_symlink()
    raw = path.read_bytes()
    return {'path': path.relative_to(relative_to).as_posix() if relative_to else str(path),
            'sha256': hashlib.sha256(raw).hexdigest(), 'size_bytes': len(raw)}

def write(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')

def copy_original(source, name):
    raw = source.read_bytes()
    target = PACKET / name
    with target.open('xb') as stream:
        stream.write(raw)
    assert target.read_bytes() == source.read_bytes()
    return {'source': identity(source), 'retained': identity(target, PACKET)}

def main():
    report_path = EVIDENCE / 'host-diagnostic.json'
    original_report = identity(report_path)
    report = json.loads(report_path.read_text())
    observed = report['observations']
    assert report['state'] == 'finished'
    assert observed['helper_revision'] == REVISION
    assert all(report[key] is False for key in FALSE_CLAIMS)
    assert all(report[key] is False for key in ('fresh_dependency_build_passed', 'dependency_source_to_loaded_binary_verified', 'formal_preparation_executed', 'measurement_staging_executed', 'cache_restoration_claimed'))
    assert report['native_execution'] == 'not_run'
    assert subprocess.check_output(['git', '-C', str(HELPERS), 'rev-parse', 'HEAD']).decode().strip() == REVISION
    assert subprocess.check_output(['git', '-C', str(HELPERS), 'rev-parse', 'HEAD^{tree}']).decode().strip() == TREE
    assert subprocess.check_output(['git', '-C', str(HELPERS), 'status', '--porcelain=v1']) == b''
    preparation = json.loads((PACKET / 'preparation-05.json').read_text())
    assert identity(WORKSPACE / 'prepared.json') == preparation['prepared']
    assert identity(PACKET / 'driver-05.py') == preparation['driver']
    assert identity(EVIDENCE / 'tool-config.json') == preparation['tool_config']
    for expected in preparation['prior_attempt_protected_identities']:
        assert identity(Path(expected['path'])) == expected
    for row in observed['helper_sources']:
        current = identity(HELPERS / row['path'])
        assert (current['sha256'], current['size_bytes']) == (row['sha256'], row['size_bytes'])
    retained = [identity(path, EVIDENCE) for path in sorted(EVIDENCE.rglob('*')) if path.is_file() and path != report_path]
    assert retained == observed['retained_files']
    assert sum(row['size_bytes'] for row in retained) == observed['retained_bytes']
    rows = [(path, json.loads(path.read_text())) for path in sorted((EVIDENCE / 'records').glob('*.json'))]
    records = [row for _, row in rows]
    actual_roles = dict(Counter(row['role'] for row in records))
    passing_roles = dict(Counter(row['role'] for row in records if row['state'] == 'finished' and row['outcome'] == 'pass'))
    assert actual_roles == observed['actual_record_roles']
    assert passing_roles == observed['passing_record_roles']
    manifest = [{'record': identity(path, EVIDENCE), 'id': row['id'], 'role': row['role'],
                 'state': row['state'], 'outcome': row['outcome'], 'reason': row['reason'],
                 'output_path': row['output_path'], 'output': row['output'],
                 'process_started': row['process_started'], 'started_ns': row['started_ns'],
                 'finished_ns': row['finished_ns']} for path, row in rows]
    write(PACKET / 'execution-05-record-manifest.json', manifest)
    small = []
    commands = []
    for command in observed['commands']:
        assert re.fullmatch(r'[a-z0-9-]+', command['id'])
        source = EVIDENCE / command['log']
        current = identity(source)
        assert (current['sha256'], current['size_bytes']) == (command['log_sha256'], command['log_size_bytes'])
        copied = copy_original(source, 'execution-05-' + command['id'] + '.log')
        small.append(copied)
        commands.append({**command, 'retained_log': copied['retained']})
    selected_records = []
    for path, row in rows:
        if row['role'] == 'link' or row['outcome'] != 'pass' or (row['role'] == 'compile' and any(word.endswith('/s_shortShiftLeft128.c') for word in row['requested_arguments'])):
            label = ('record-' + row['role'] + '-' + row['id'][:12])
            copied = copy_original(path, 'execution-05-' + label + '.json')
            small.append(copied)
            selected_records.append({'id': row['id'], 'role': row['role'], 'state': row['state'], 'outcome': row['outcome'], 'retained_record': copied['retained']})
            if row['role'] == 'compile':
                for key in ('dependency_prepass_file', 'dependency_file'):
                    value = row.get(key)
                    if value:
                        source = EVIDENCE / 'payloads' / value['payload']
                        small.append(copy_original(source, 'execution-05-' + label + '-' + key + '.d'))
    driver_result = json.loads((PACKET / 'execution-05-driver-result.json').read_text())
    assert driver_result['completion_observed'] is True
    small.append(copy_original(Path(driver_result['driver_stdout']), 'execution-05-driver.stdout.log'))
    links = []
    for name, value in observed.get('verified_links', {}).items():
        record = next(row for row in records if row['id'] == value['record_id'])
        checked = value['map']
        links.append({'name': name, 'record_id': value['record_id'], 'output': value['output'],
                      'link_map': record['link_map'], 'selected_members': len(checked['selected_members']),
                      'selected_members_by_archive': dict(Counter(item['archive'] for item in checked['selected_members'])),
                      'loads': len(checked['loads']), 'required_archives': checked['required_archives'],
                      'required_loads': checked['required_loads']})
    children = [child for row in records for child in row['children']]
    if report['host_diagnostic_passed']:
        assert Counter(child['stage'] for child in children) == {'dependencies': 406, 'tool': 413}
        assert all(child['process_started'] is True and child['exit_code'] == 0 for child in children)
    summary = {'schema_version': 1,
        'scope': 'Actual host dependency diagnostic attempt05; formal dependency producer, measurement staging, managed/native execution and qualification are outside this original',
        'recorded_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'helper_revision': REVISION, 'helper_tree': TREE, 'helper_checkout': str(HELPERS), 'helper_checkout_clean_after': True,
        'driver': preparation['driver'], 'prepared': preparation['prepared'], 'tool_config': preparation['tool_config'],
        'original_workspace': str(WORKSPACE), 'original_report': original_report,
        'driver_result': 'execution-05-driver-result.json', 'driver_exit_code': driver_result['driver_exit_code'],
        'state': report['state'], 'outcome': report['outcome'], 'reason': report['reason'], 'failures': report['failures'],
        'commands': commands, 'budget': observed['budget'],
        'source_manifest_sha256': preparation['source_manifest_sha256'], 'source_plan_sha256': preparation['source_plan_sha256'],
        'source_files': preparation['source_files'], 'source_bytes': preparation['source_bytes'],
        'planned_translation_units': preparation['planned_translation_units'],
        'actual_record_roles': actual_roles, 'passing_record_roles': passing_roles,
        'all_records_finished': all(row['state'] == 'finished' for row in records),
        'selected_tools_started': sum(row['process_started'] is True for row in records),
        'selected_tool_children_exit_zero': sum(child['stage'] == 'tool' and child['process_started'] is True and child['exit_code'] == 0 for child in children),
        'dependency_prepass_children_exit_zero': sum(child['stage'] == 'dependencies' and child['process_started'] is True and child['exit_code'] == 0 for child in children),
        'record_manifest': identity(PACKET / 'execution-05-record-manifest.json', PACKET),
        'recorded_generated_inputs': len(observed['generated_inputs']), 'compile_database_retained': observed['compile_database'] is not None,
        'verified_compile_count': observed.get('verified_compile_count'), 'verified_object_count': observed.get('verified_object_count'),
        'verified_archives': {name: {'path': value['path'], 'members': len(value['members']), 'output': value['output'], 'finished_ns': value['finished_ns']} for name, value in observed.get('verified_archives', {}).items()},
        'verified_links': links, 'recorded_stability_checks': len(observed['stability_checks']),
        'retained_original_files': len(retained), 'retained_original_bytes_excluding_report': observed['retained_bytes'],
        'all_retained_files_rehashed_after_completion': True,
        'selected_raw_records': selected_records, 'retained_small_originals': small,
        'previous_attempts03_and04_preserved': True, 'prepared05_and_driver05_preserved': True,
        **{key: report[key] for key in ('host_diagnostic_passed', 'fresh_dependency_build_passed', 'dependency_source_to_loaded_binary_verified', 'native_execution', 'formal_preparation_executed', 'measurement_staging_executed', 'cache_restoration_claimed', *FALSE_CLAIMS)},
        'limitations': ['This is a host dependency diagnostic, not the formal dependency receipt or managed/native original.',
                        'A passing actual dependency graph supplies no native loader, hardware, warm or phase-acceptance result.',
                        'Independent original review is a separate contribution; this is the execution owner summary.',
                        'Complete raw payloads and source/helper originals remain in the named workspace for separate archival.']}
    assert identity(report_path) == original_report
    write(PACKET / 'execution-05-summary.json', summary)
    print(json.dumps({key: summary[key] for key in ('state','outcome','reason','actual_record_roles','passing_record_roles','verified_compile_count','recorded_generated_inputs','compile_database_retained','recorded_stability_checks','retained_original_files','retained_original_bytes_excluding_report','original_report','host_diagnostic_passed','native_execution')}, indent=2))
    print(json.dumps(identity(PACKET / 'execution-05-summary.json'), sort_keys=True))

if __name__ == '__main__':
    main()
