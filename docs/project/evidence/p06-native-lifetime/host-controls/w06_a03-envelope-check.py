#!/usr/bin/env python3
"""Inert, independent audit of the specified original artifact envelope."""
from pathlib import Path, PurePosixPath
import hashlib
import json
import stat
import subprocess
import time
import zipfile

WORK = Path('/tmp/ai-gpu-native-lifetime-dfd857-work')
REPO = Path('/tmp/ai-gpu-native-lifetime-dfd857')
ROOT = WORK / 'native-original'
NATIVE = ROOT / 'native-lifetime'
REV = 'b4127b19a004b5aebb8d52eab9ceda0da3ff4561'
TREE = 'bd37fb53ab1c34dfebc2ac8805abff5877735fc4'
ARCHIVE_HASH = '3d4879f73c197352689d65feb56e73f537701fc1411e55bf53c92b1b41e13db3'
FALSE = ('qualified', 'ready_for_warm', 'warm_execution', 'full_warm_coverage',
         'acceptance_claimed', 'phase_acceptance', 'performance_acceptance')
OBLIGATIONS = ['all_40_component_lifetime_and_pending_balance',
               'dependency_source_to_loaded_binary_provenance',
               'independent_complete_counter_qualification']

def require(condition, message):
    if not condition:
        raise ValueError(message)

def sha(body):
    return hashlib.sha256(body).hexdigest()

def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, 'duplicate JSON key')
        result[key] = value
    return result

def invalid_constant(value):
    raise ValueError('nonfinite JSON value: ' + value)

def load(path):
    raw = path.read_bytes()
    require(len(raw) <= 32 * 1024**2, 'JSON exceeds audit size bound')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant)

def descriptor(base, row):
    require(set(row) == {'path', 'sha256', 'size_bytes'}, 'descriptor fields differ')
    p = PurePosixPath(row['path'])
    require(not p.is_absolute() and '..' not in p.parts and '\\' not in str(p), 'unsafe descriptor path')
    target = base / p
    require(target.is_file() and not target.is_symlink(), 'missing or symlink descriptor')
    body = target.read_bytes()
    require(sha(body) == row['sha256'] and len(body) == row['size_bytes'], 'descriptor bytes differ: ' + str(p))
    return body

start = time.monotonic()
github = load(WORK / 'w06_a03-independent-github.json')
run, artifact, jobs = github['run'], github['artifact'], github['jobs']
require(run['id'] == 45130300651 and run['head_sha'] == REV and run['run_attempt'] == 1,
        'GitHub run identity differs')
require(run['status'] == 'completed' and run['conclusion'] == 'success'
        and run['path'] == '.github/workflows/p06-native-lifetime.yml'
        and run['head_branch'] == 'master' and run['event'] == 'push', 'GitHub run route differs')
require(artifact['id'] == 14798140556 and artifact['size_in_bytes'] == 9086055
        and artifact['digest'] == 'sha256:' + ARCHIVE_HASH and artifact['expired'] is False,
        'GitHub artifact identity differs')
require(artifact['workflow_run']['head_sha'] == REV and artifact['workflow_run']['id'] == run['id'],
        'artifact is attributed to another run')
require(len(jobs) == 1 and jobs[0]['id'] == 137544022426
        and jobs[0]['conclusion'] == 'success' and jobs[0]['head_sha'] == REV, 'job identity differs')
for name in ('Execute all managed lifetime processes serially',
             'Observe native pending reads and reject the always-zero control',
             'Retain preparation and native execution packet'):
    selected = [s for s in jobs[0]['steps'] if s['name'] == name]
    require(len(selected) == 1 and selected[0]['conclusion'] == 'success', 'required job step did not pass')

archive = (WORK / 'native-original.zip').read_bytes()
require(len(archive) == 9086055 and sha(archive) == ARCHIVE_HASH, 'archive bytes differ')
members = []
seen = set()
with zipfile.ZipFile(WORK / 'native-original.zip') as z:
    for entry in z.infolist():
        p = PurePosixPath(entry.filename)
        require(not p.is_absolute() and '..' not in p.parts and '\\' not in entry.filename,
                'unsafe archive path')
        require(entry.filename not in seen and not stat.S_ISLNK(entry.external_attr >> 16),
                'duplicate archive name or symlink')
        seen.add(entry.filename)
        if entry.is_dir():
            continue
        body = z.read(entry)  # zipfile also verifies each member CRC.
        require((ROOT / p).read_bytes() == body, 'extracted member differs: ' + str(p))
        members.append({'path': str(p), 'sha256': sha(body), 'size_bytes': len(body)})
require(len(members) == 1264 and sum(x['size_bytes'] for x in members) == 37138100,
        'member population differs')
inventory = load(WORK / 'native-original-inventory.json')
require(inventory['archive_sha256'] == ARCHIVE_HASH and inventory['archive_bytes'] == len(archive)
        and inventory['files'] == members, 'retained member inventory differs')
require({str(x.relative_to(ROOT)) for x in ROOT.rglob('*') if x.is_file()}
        == {m['path'] for m in members}, 'unexpected extracted files')

job = load(ROOT / 'job.json')
preparation = load(ROOT / 'preparation.json')
provision = load(ROOT / 'python-provision.json')
report = load(NATIVE / 'report.json')
probe = load(ROOT / 'pending-probe/report.json')
require(job['GITHUB_SHA'] == REV and job['GITHUB_RUN_ID'] == str(run['id'])
        and job['GITHUB_RUN_ATTEMPT'] == '1' and job['GITHUB_JOB'] == 'native-lifetime'
        and job['GITHUB_REPOSITORY'] == 'baabi-boo/AI-GPU'
        and job['GITHUB_EVENT_NAME'] == 'push' and job['GITHUB_REF'] == 'refs/heads/master',
        'initial job identity differs')
require(job['record_stage'] == 'job-initialization' and job['native_execution'] == 'not_run',
        'initialization record conflates later execution')
workflow = (ROOT / 'workflow.yml').read_bytes()
committed_workflow = subprocess.check_output(['git', 'show', REV + ':.github/workflows/p06-native-lifetime.yml'], cwd=REPO)
require(workflow == committed_workflow and sha(workflow) == job['workflow_sha256'], 'workflow bytes differ')
require(provision == {'python_version': [3, 12, 14], 'implementation': 'CPython', 'platform': 'linux',
        'executable': '/opt/hostedtoolcache/Python/3.12.14/x64/bin/python3',
        'python3_on_path': '/opt/hostedtoolcache/Python/3.12.14/x64/bin/python3'}, 'provisioned interpreter differs')
require(report['interpreter'] == {'implementation': 'CPython', 'platform': 'linux', 'version': [3, 12, 14]},
        'executing interpreter differs')
for row in (job, report, probe):
    require(all(row[k] is False for k in FALSE), 'acceptance claim changed')
require(job['dependency_compilation_provenance_verified'] is False, 'dependency qualification claimed')
require(report['unresolved_obligations'] == OBLIGATIONS, 'remaining obligations changed')
require(report['state'] == 'finished' and report['outcome'] == 'pass' and report['reason'] is None
        and report['failures'] == [] and report['expected_revision'] == REV
        and report['native_execution'] == 'run' and report['native_lifetime_passed'] is True
        and report['native_preflight_passed'] is True, 'native report state differs')
require(preparation['outcome'] == 'pass' and preparation['reason'] is None
        and preparation['expected_revision'] == REV and preparation['backend'] == 'simx'
        and preparation['formats'] == ['fp16', 'bf16'], 'preparation did not admit selected route')
require(report['contract_id'] == job['contract_id'] == 'p06-managed-counter-lifetime-v1', 'contract differs')
require(job['requested_xlen'] == 64 and job['requested_profile'] == 'p02-tfr'
        and job['requested_perf'] == 'on' and job['requested_build_jobs'] == 2
        and job['requested_simulation_workers'] == 1, 'requested configuration differs')
require(job['free_disk_bytes_before_cache'] >= 15 * 1024**3
        and job['available_memory_bytes_before_cache'] >= 4 * 1024**3, 'initial budget not met')

verified_descriptors = 0
for group in ('retained_files', 'retained_sources', 'raw_logs'):
    require(len({r['path'] for r in report[group]}) == len(report[group]), 'duplicate descriptor path')
    for row in report[group]:
        descriptor(NATIVE, row)
        verified_descriptors += 1
for key in ('source_before', 'source_after', 'tools_before', 'tools_after', 'dependencies_before',
            'dependencies_after', 'contract_snapshot', 'preflight_contract_snapshot', 'fixture_snapshot'):
    descriptor(NATIVE, report[key])
for stem in ('source', 'tools', 'dependencies'):
    require((NATIVE / report[stem + '_before']['path']).read_bytes()
            == (NATIVE / report[stem + '_after']['path']).read_bytes(), stem + ' bytes changed')
    require(report[stem + '_stable'] is True, stem + ' stability flag differs')
require(report['retained_files_stable'] is True, 'retained file stability missing')
source = load(NATIVE / report['source_before']['path'])
checkout = source['checkout']
require(checkout == preparation['source'] and checkout['revision'] == REV and checkout['tree'] == TREE
        and checkout['dirty'] is False and checkout['changed_paths'] == [] and checkout['untracked_paths'] == []
        and checkout['blockers'] == [] and checkout['outcome'] == 'pass', 'clean source identity differs')
require(checkout['submodules']['errors'] == []
        and all(row['status'] == 'initialized' for row in checkout['submodules']['entries']), 'submodule state differs')
tools = load(NATIVE / report['tools_before']['path'])
require({k: tools[k] for k in preparation['tool_identities']} == preparation['tool_identities'],
        'prepared and executing tool identities differ')
require(tools['executing_python'] == tools['python3'], 'PATH Python and executing interpreter differ')
require(load(NATIVE / report['dependencies_before']['path']) == preparation['dependency_identities'],
        'prepared dependency bytes differ')

tree_rows = subprocess.check_output(['git', 'ls-tree', '-rz', REV], cwd=REPO).split(b'\0')
git_files = {}
git_links = {}
for row in tree_rows:
    if row:
        info, name = row.split(b'\t', 1)
        mode, kind, oid = info.decode().split()
        if kind == 'blob':
            git_files[name.decode()] = oid
        elif kind == 'commit':
            git_links[name.decode()] = oid
submodule_revisions = {row['path']: row['revision'] for row in checkout['submodules']['entries']}
require(len(git_links) == checkout['submodules']['declared_count'] == 5
        and all(submodule_revisions.get(path) == oid for path, oid in git_links.items()),
        'top-level submodule revision differs from committed Git link')
retained = {r['path']: r for r in report['retained_sources']}
root_source_count = 0
external_sources = []
for row in source['files']:
    require(set(row) == {'path', 'sha256', 'size_bytes'}, 'source descriptor fields differ')
    expected = dict(row, path='artifacts/source/' + row['path'])
    require(retained[expected['path']] == expected, 'source retention mapping differs')
    body = descriptor(NATIVE, expected)
    if row['path'] in git_files:
        git_blob = hashlib.sha1(b'blob ' + str(len(body)).encode() + b'\0' + body).hexdigest()
        require(git_blob == git_files[row['path']], 'retained source differs from committed Git object')
        root_source_count += 1
    else:
        require(row['path'].startswith(('third_party/ramulator/', 'third_party/softfloat/')), 'unexpected external source')
        external_sources.append(row['path'])
require(root_source_count == 811 and len(external_sources) == 193 and len(source['files']) == 1004,
        'source projection population differs')
require(subprocess.check_output(['git', 'rev-parse', REV + '^{tree}'], cwd=REPO).decode().strip() == TREE,
        'commit tree differs')
for row in report['loaded_helpers']:
    require(row in source['files'] and row['path'] in git_files, 'helper not bound to committed source')

expected_counts = {'available_queries': 528, 'cache_flush_reads': 132, 'checked_words': 4224,
                   'dcr_reads': 1188, 'half_replies': 1056, 'launches': 132, 'processes': 4,
                   'snapshots': 16, 'unavailable_rows': 192}
require(report['expected_counts'] == report['completed_counts'] == expected_counts, 'native population differs')
require((job['requested_processes'], job['requested_launches'], job['requested_checked_words']) == (4, 132, 4224),
        'requested population differs')
selected = [(fmt, policy) for fmt in ('fp16', 'bf16') for policy in ('per_operation', 'reusable_single_tile')]
require([(r['format'], r['policy']) for r in report['processes']] == selected
        and [(r['format'], r['policy']) for r in report['expected_processes']] == selected, 'matrix differs')
process_rows = []
for process in report['processes']:
    require(process['outcome'] == 'pass', 'process failed')
    obs = process['observation']
    summary = obs['warm']['summary']
    require(summary['operations'] == len(obs['warm']['operations']) == 33 and summary['checked'] == 1056
            and summary['mismatches'] == 0 and summary['passed'] is True, 'per-process population differs')
    for key in ('witness', 'lifetime'):
        require(all(obs[key][f] is False for f in FALSE) and obs[key]['unresolved_obligations'] == OBLIGATIONS,
                'per-process acceptance boundary differs')
    process_rows.append({'id': process['id'], 'format': process['format'], 'policy': process['policy'],
                         'operations': summary['operations'], 'checked_words': summary['checked'],
                         'mismatches': summary['mismatches'], 'log': process['log']})
require(len(report['commands']) == len(report['raw_logs']) == 35, 'command/log inventory differs')
for command in report['commands']:
    require(command['process_started'] is True and command['cleanup_complete'] is True
            and command['outcome'] == 'pass' and command['exit_code'] == 0 and command['reason'] is None,
            'managed command did not pass')
    descriptor(NATIVE, {'path': command['log'], 'sha256': command['log_sha256'],
                        'size_bytes': command['log_size_bytes']})
require(sum(c['native_process'] is True for c in report['commands']) == 4, 'native command count differs')
contract = load(NATIVE / report['contract_snapshot']['path'])
encoded = json.dumps(contract, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()
require(sha(encoded) == report['contract_sha256'] == 'e3558209c7d467044eb46ef382f0cf03e1b4479a855a3a3ffe8ae4c3c1a05ec9',
        'contract descriptor digest differs')

receipt = {'scope': 'independent inert original archive envelope and attribution audit', 'outcome': 'pass',
    'revision': REV, 'tree': TREE, 'run_id': run['id'], 'job_id': jobs[0]['id'], 'artifact_id': artifact['id'],
    'archive_sha256': ARCHIVE_HASH, 'archive_size_bytes': len(archive), 'verified_members': len(members),
    'expanded_bytes': sum(m['size_bytes'] for m in members), 'retained_descriptor_checks': verified_descriptors,
    'retained_source_files': len(source['files']), 'root_commit_source_objects_verified': root_source_count,
    'dependency_source_bytes_only': len(external_sources), 'loaded_helpers_bound_to_root_commit': len(report['loaded_helpers']),
    'top_level_submodule_gitlinks_verified': len(git_links),
    'managed_command_receipts': len(report['commands']), 'managed_native_command_receipts': 4,
    'completed_counts': expected_counts, 'processes': process_rows, 'all_seven_claims_false': True,
    'unresolved_obligations': OBLIGATIONS, 'review_executed_native_code': False,
    'seconds': time.monotonic() - start,
    'limits': ['Process transcript semantic admission and probe behavioral review are separate assignments.',
               'Retained dependency source hashes do not prove immutable fetched-source identity or fresh dependency compilation.',
               'No complete archive-validator qualification, all-40-component qualification, warm result or phase acceptance is claimed.'],
    'evidence_sha256': {p.name: sha(p.read_bytes()) for p in
        (WORK / 'w06_a03-independent-github.json', WORK / 'native-original-inventory.json', WORK / 'native-job-original.log')},
    'review_script_sha256': sha(Path(__file__).read_bytes())}
(WORK / 'w06_a03-envelope-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps({k: receipt[k] for k in ('outcome', 'verified_members', 'root_commit_source_objects_verified',
      'dependency_source_bytes_only', 'managed_command_receipts', 'seconds')}, sort_keys=True))
