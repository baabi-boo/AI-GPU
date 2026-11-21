#!/usr/bin/env python3
"""Read-only delivery review; scan summaries never contain matched secret values."""
import ast
from collections import Counter
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import urllib.parse
import zipfile

REPO = Path('/workspace/scratch/ba0248fde989/AI-GPU')
OUT = REPO.parent / 'p05-work/w10_a6'
EVIDENCE = REPO / 'docs/project/evidence/p05-python'
BASE = '6aac9c421180805a5621156e3d914c685fc6f4a5'
IMPLEMENTATION = 'e1420fd550f716df33a2556057b7086a03032cbe'
TREE = '3a168adfd345ecb3c15dc02b2583dc832bef6049'
OBSERVED = '2026-11-21 05:27:47 UTC'


def sha(body):
    return hashlib.sha256(body).hexdigest()


def load(path):
    return json.loads(path.read_bytes())


def git(*args):
    return subprocess.check_output(['git', *args], cwd=REPO)


def identity(path):
    body = path.read_bytes()
    return {'path': path.relative_to(REPO).as_posix(), 'size_bytes': len(body), 'sha256': sha(body)}


def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


assert git('rev-parse', 'HEAD').decode().strip() == IMPLEMENTATION
assert git('rev-parse', IMPLEMENTATION + '^{tree}').decode().strip() == TREE
assert git('symbolic-ref', '--short', 'HEAD').decode().strip() == 'master'
origin = urllib.parse.urlsplit(git('remote', 'get-url', 'origin').decode().strip())
assert origin.hostname == 'github.com' and origin.path.rstrip('/') == '/baabi-boo/AI-GPU.git'
assert origin.username is None and origin.password is None
source_map = load(EVIDENCE / 'source-map.json')
checked_sources = {}
for section in ('production_test_and_workflow_files', 'binding_sources'):
    for item in source_map[section]:
        path = REPO / item['path']
        body = path.read_bytes()
        assert len(body) == item.get('size_bytes', item.get('size')) and sha(body) == item['sha256'], item['path']
        assert body == git('show', IMPLEMENTATION + ':' + item['path']), item['path']
        checked_sources[item['path']] = identity(path)
protected = {}
for name in ('LICENSE', 'docs/assets/img/vortex_framework_stack.svg',
             'ci/change_impact.py', 'docs/review/change-impact.yaml', 'docs/review/code-review-policy.md'):
    body = (REPO / name).read_bytes()
    assert body == git('show', BASE + ':' + name) == git('show', IMPLEMENTATION + ':' + name), name
    protected[name] = sha(body)
def embed(body):
    return [line for line in body.splitlines() if b'vortex_framework_stack.svg' in line]
assert embed((REPO / 'README.md').read_bytes()) == embed(git('show', BASE + ':README.md'))
tracked_changes = git('diff', '--name-only', IMPLEMENTATION).decode().splitlines()
boundary = source_map['later_change_boundary']
assert all(name in boundary['allowed_document_paths'] or name.startswith(boundary['allowed_evidence_prefix'])
           for name in tracked_changes)
accepted = load(EVIDENCE / 'acceptance-binding.json')
assert accepted['outcome'] == 'pass' and accepted['source_revision'] == IMPLEMENTATION
assert accepted['acceptance_ids'] == ['P05-A01'] and accepted['evidence_level'] == 'simulated'
for row in accepted['artifacts']:
    assert sha((REPO / row['path']).read_bytes()) == row['sha256'], row['path']
phase = next(row for row in load(REPO / 'docs/project/roadmap.json')['phases'] if row['id'] == 'P05')
assert phase['status'] == 'in_progress' and [row['acceptance_id'] for row in phase['evidence']] == ['P05-A01']

# The wrapper is inspected and parsed, never executed here. It runs only a
# hash-checked immutable-base classifier with explicit repository/policy arguments.
wrapper_path = EVIDENCE / 'final-governance/classify_candidate.py'
wrapper = wrapper_path.read_bytes()
ast.parse(wrapper)
plan = load(EVIDENCE / 'final-governance/classifier-plan.json')
assert sha(wrapper) == plan['wrapper']['sha256'] == '3e564996bedf30816254c2fc3b83eeb13086119e76c882659fd0efdb79815415'
assert plan['state'] == 'prepared_not_run' and plan['candidate_sha'] is None
wrapper_text = wrapper.decode()
for text in ('args.head + \'^{commit}\'', "'merge-base', '--is-ancestor'", "git('show', BASE + ':' + source)",
             "sys.executable, '-I'", "'--policy', str(args.output / 'change-impact.yaml')",
             "('complete-change', BASE)", "('qualification-continuation', IMPLEMENTATION)",
             "row['indeterminate'] is False"):
    assert text in wrapper_text, text
assert not re.search(r"\[['\"]git['\"],\s*['\"](?:add|commit|push|reset|update-ref|checkout|switch)['\"]", wrapper_text)
wrapper_pins = {}
for name in ('ci/change_impact.py', 'docs/review/change-impact.yaml'):
    digest = sha(git('show', BASE + ':' + name))
    assert digest in wrapper_text
    wrapper_pins[name] = digest

# Every original archive and member identity is checked before textual scanning.
archive_index = load(EVIDENCE / 'archive-index.json')
archives, member_bodies = [], []
for item in archive_index['archives']:
    name = item['variant'] + '.zip'
    path = EVIDENCE / 'archives' / name
    body = path.read_bytes()
    assert len(body) == item['archive']['size_bytes'] and sha(body) == item['archive']['sha256']
    expected = {row['path']: row for row in item['members']}
    with zipfile.ZipFile(io.BytesIO(body)) as stream:
        assert len(stream.infolist()) == len(expected) == 304
        assert len(set(stream.namelist())) == len(expected)
        for info in stream.infolist():
            assert info.filename in expected and 0 <= info.file_size <= 16 * 1024 * 1024
            value = stream.read(info)
            row = expected[info.filename]
            assert len(value) == row['size_bytes'] and sha(value) == row['sha256']
            member_bodies.append(('archives/' + name + '!' + info.filename, value))
    archives.append(identity(path))
notices = load(EVIDENCE / 'licenses/sources.json')
for row in notices['source_files'] + notices['inspection_artifacts']:
    body = (EVIDENCE / 'licenses' / row['path']).read_bytes()
    assert sha(body) == row['sha256'] and len(body) == row['size_bytes']
assert (EVIDENCE / 'licenses/LICENSE-Apache-2.0.txt').read_bytes() == (REPO / 'LICENSE').read_bytes()
notice_body = (EVIDENCE / 'THIRD_PARTY_NOTICES.md').read_text()
assert all(label in notice_body for label in ('Ramulator', 'SoftFloat', 'yaml-cpp', 'spdlog', 'fmt'))

patterns = {
    'private_key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----'),
    'github_token': re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b'),
    'aws_access_key': re.compile(r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'),
    'signed_url_parameter': re.compile(r'https?://[^\s<>"\']+[?&](?:X-Amz-Signature|X-Goog-Signature|sig|access_token|token)=[^\s<>"\']+', re.I),
    'connector_account_id': re.compile(r'\blink_[0-9a-f]{24,}\b'),
    'home_user_path': re.compile(r'/(?:Users|home)/(?!runner(?:/|\b)|agent(?:/|\b)|ubuntu(?:/|\b)|vortex(?:/|\b))[^/\s"\']+/'),
}
email_pattern = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b')
seen = set()
scan_records, matches, emails = [], [], []
scan_counts = Counter()


def scan(name, body, *, nested=False):
    if name in seen:
        return
    seen.add(name)
    scan_counts['input_bytes'] += len(body)
    try:
        text = body.decode('utf-8')
        if '\x00' in text:
            raise UnicodeError('binary NUL')
    except UnicodeError:
        scan_counts['binary_members_skipped'] += 1
        return
    scan_counts['text_members'] += 1
    scan_counts['text_bytes'] += len(body)
    if nested:
        scan_counts['nested_text_members'] += 1
    scan_records.append({'path': name, 'size_bytes': len(body), 'sha256': sha(body)})
    for category, pattern in patterns.items():
        for match in pattern.finditer(text):
            # Deliberately retain no match contents or hash of secret contents.
            matches.append({'path': name, 'category': category, 'line': text[:match.start()].count('\n') + 1})
    for match in email_pattern.finditer(text):
        emails.append({'path': name, 'line': text[:match.start()].count('\n') + 1})


paths = sorted(path for path in EVIDENCE.rglob('*') if path.is_file()
               and '__pycache__' not in path.parts and path.suffix != '.zip'
               and path.name not in ('final-delivery-review.json', 'general-ci-observation.json', 'agent-ledger.json'))
for path in paths:
    scan(path.relative_to(EVIDENCE).as_posix(), path.read_bytes())
for name in boundary['allowed_document_paths']:
    scan('repository/' + name, (REPO / name).read_bytes())
for name, body in member_bodies:
    scan(name, body)
    if name.endswith('.whl'):
        with zipfile.ZipFile(io.BytesIO(body)) as stream:
            assert len(stream.infolist()) <= 100 and sum(i.file_size for i in stream.infolist()) <= 32 * 1024 * 1024
            for info in stream.infolist():
                scan(name + '!' + info.filename, stream.read(info), nested=True)
    elif name.endswith('.tar.gz'):
        with tarfile.open(fileobj=io.BytesIO(body), mode='r:gz') as stream:
            members = stream.getmembers()
            assert len(members) <= 200 and sum(i.size for i in members) <= 32 * 1024 * 1024
            for info in members:
                if info.isfile():
                    scan(name + '!' + info.name, stream.extractfile(info).read(), nested=True)

master = load(EVIDENCE / 'hosted/master-ref-w10-a6.json')
run = load(EVIDENCE / 'hosted/general-ci-run-w10-a6.json')
jobs = load(EVIDENCE / 'hosted/general-ci-jobs-w10-a6.json')
assert master['ref'] == 'refs/heads/master' and master['object']['sha'] == IMPLEMENTATION
assert run['id'] == 44866368514 and run['head_sha'] == IMPLEMENTATION and run['head_branch'] == 'master'
assert run['status'] == 'completed' and run['conclusion'] == 'success'
assert len(jobs['jobs']) == jobs['total_count'] == 43
assert all(row['status'] == 'completed' and row['conclusion'] == 'success' for row in jobs['jobs'])
observation = {
    'schema_version': 1, 'observed_at_utc': OBSERVED, 'reviewer': '/root/w10_a6_final_delivery_review',
    'method': 'Three successful read-only GitHub REST GET observations through the connected repository account; no CLI exit code is invented.',
    'repository': 'baabi-boo/AI-GPU', 'branch': 'master', 'remote_master_sha': master['object']['sha'],
    'run_id': run['id'], 'run_url': run['html_url'], 'head_sha': run['head_sha'],
    'status': run['status'], 'conclusion': run['conclusion'], 'run_updated_at': run['updated_at'],
    'run_started_at': run['run_started_at'], 'total_jobs': jobs['total_count'],
    'job_outcomes': dict(Counter(row['conclusion'] for row in jobs['jobs'])), 'failed_jobs': [],
    'pagination_complete': len(jobs['jobs']) == jobs['total_count'],
    'raw_observations': [identity(EVIDENCE / 'hosted' / name) for name in (
        'master-ref-w10-a6.json', 'general-ci-run-w10-a6.json', 'general-ci-jobs-w10-a6.json')],
    'limitations': [
        'This is the completed general-CI run for the implementation commit, not CI for a future final evidence/documentation commit.',
        'Earlier pending observations remain valid historical snapshots; this later completed observation does not rewrite them.',
        'The historical tensor DSP area-gate finding and blocked vendor XRT hw_emu are not resolved by this general-CI result.',
        'Root must read current master again immediately before publication and verify the actual final commit/tree after updating it.',
    ],
}
write(EVIDENCE / 'hosted/general-ci-observation.json', observation)
result = {
    'schema_version': 1, 'scope': 'Read-only source/delivery/privacy snapshot; no final candidate or ref update performed',
    'repository': 'baabi-boo/AI-GPU', 'branch': 'master', 'implementation': IMPLEMENTATION, 'tree': TREE,
    'checked_source_bodies': sorted(checked_sources.values(), key=lambda row: row['path']),
    'source_counts': {'production_test_workflow_files': len(source_map['production_test_and_workflow_files']),
                      'binding_inputs': len(source_map['binding_sources'])},
    'protected_sha256': protected, 'tracked_changes': tracked_changes,
    'acceptance_artifact_hashes_verified': len(accepted['artifacts']),
    'wrapper': identity(wrapper_path), 'frozen_policy_pins': wrapper_pins,
    'wrapper_executed': False, 'wrapper_plan_state': plan['state'],
    'archives': archives, 'archive_members_verified': len(member_bodies),
    'notice_sources_verified': len(notices['source_files']),
    'notice_inspection_artifacts_verified': len(notices['inspection_artifacts']),
    'privacy_scan': {'counts': dict(scan_counts), 'records': scan_records, 'candidate_matches': matches,
                     'email_match_count': len(emails), 'email_locations': emails},
    'general_ci_observation': identity(EVIDENCE / 'hosted/general-ci-observation.json'),
    'acceptance_changed': False, 'publication_performed': False,
}
write(OUT / 'checks.json', result)
print(json.dumps({'source_counts': result['source_counts'], 'archive_members': len(member_bodies),
                  'scan_counts': dict(scan_counts), 'candidate_counts': dict(Counter(row['category'] for row in matches)),
                  'candidate_locations': matches, 'email_matches': len(emails),
                  'email_files': sorted(set(row['path'] for row in emails)),
                  'general_ci': {'conclusion': run['conclusion'], 'jobs': jobs['total_count']}}, indent=2))
