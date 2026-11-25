#!/usr/bin/env python3
"""Read-only metadata and packet verification; writes only Agent 59 evidence."""
import concurrent.futures
import datetime
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time
from urllib.parse import unquote, urlsplit

TASK = Path('/tmp/ai-gpu-ae456f837c05')
REPO = TASK / 'AI-GPU'
NOTES = TASK / 'notes'
PACKET = REPO / 'docs/project/evidence/p06-execution-retention'
PYTHON = str(TASK / 'governance-bootstrap/environment/venv/bin/python3')
BASE = '622662ad9cece6da4e3375be7e977dbe04cde862'
ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', TMPDIR=str(TASK / 'tmp'),
           PATH=str(TASK / 'governance-bootstrap/environment/venv/bin') + ':/usr/bin:/bin',
           GIT_OPTIONAL_LOCKS='0')
OUT = {'schema': 'ai-gpu.prepublication-check.v1', 'agent': 59,
       'started_utc': datetime.datetime.now(datetime.UTC).isoformat(),
       'environment_overrides': {k: ENV[k] for k in ('PYTHONDONTWRITEBYTECODE', 'TMPDIR', 'PATH', 'GIT_OPTIONAL_LOCKS')},
       'findings': [], 'commands': []}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read(path, limit=32 * 1024 * 1024):
    info = path.lstat()
    assert stat.S_ISREG(info.st_mode), str(path)
    assert info.st_size <= limit, str(path)
    with path.open('rb') as handle:
        data = handle.read(limit + 1)
    assert len(data) == info.st_size and path.stat().st_mtime_ns == info.st_mtime_ns, str(path)
    return data


def identity(path):
    data = read(path)
    return {'path': str(path.relative_to(TASK)), 'size_bytes': len(data),
            'sha256': digest(data), 'mode': oct(stat.S_IMODE(path.stat().st_mode))}


def blob(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def run(argv):
    result = subprocess.run(argv, cwd=REPO, env=ENV, capture_output=True, timeout=120)
    return result


def git(*args):
    result = run(['git', *args])
    assert result.returncode == 0, (args, result.returncode, result.stderr.decode())
    return result.stdout


def check(name, condition, detail=None):
    if not condition:
        OUT['findings'].append({'check': name, 'detail': detail})
    return bool(condition)


OUT['head'] = git('rev-parse', 'HEAD').decode().strip()
OUT['head_tree'] = git('rev-parse', 'HEAD^{tree}').decode().strip()
OUT['staged_paths'] = git('diff', '--cached', '--name-only', '-z').decode().split('\0')[:-1]
tracked = git('diff', '--name-only', '-z', 'HEAD', '--').decode().split('\0')[:-1]
new = git('ls-files', '--others', '--exclude-standard', '-z').decode().split('\0')[:-1]
candidate = sorted(set(tracked + new))
OUT['candidate_inventory'] = [identity(REPO / p) for p in candidate]
OUT['candidate_counts'] = {'tracked_modified': len(tracked), 'untracked_files': len(new), 'total': len(candidate)}


def command_check(label, argv):
    started = time.monotonic()
    result = run(argv)
    combined = result.stdout + result.stderr
    log = NOTES / ('agent-59-' + label + '.log')
    log.write_bytes(combined)
    return {'label': label, 'argv': argv, 'cwd': str(REPO), 'returncode': result.returncode,
            'duration_seconds': round(time.monotonic() - started, 6),
            'stdout': result.stdout.decode(), 'stderr': result.stderr.decode(), 'log': identity(log)}


command_specs = [
    ('check-project', [PYTHON, '-B', 'ci/project/check_project.py']),
    ('check-baseline-packets', [PYTHON, '-B', 'ci/project/check_baseline_packets.py']),
    ('governance-preflight', [PYTHON, '-B', 'ci/project/preflight.py', '--tier', 'governance', '--json']),
    ('tracked-whitespace', ['git', 'diff', '--check', 'HEAD', '--']),
]
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    futures = [pool.submit(command_check, *spec) for spec in command_specs]
    OUT['commands'] = [future.result() for future in futures]
for result in OUT['commands']:
    check(result['label'], result['returncode'] == 0, {'returncode': result['returncode']})

new_text = []
binary = []
whitespace = []
for rel in candidate:
    data = read(REPO / rel)
    try:
        text = data.decode('utf-8')
        if '\0' in text:
            raise UnicodeError('NUL byte')
    except UnicodeError:
        binary.append(rel)
        continue
    if rel not in new:
        continue
    new_text.append(rel)
    for number, line in enumerate(text.splitlines(), 1):
        reasons = []
        if line.endswith((' ', '\t')):
            reasons.append('trailing_whitespace')
        if re.match(r'^[ \t]* \t', line):
            reasons.append('space_before_tab_in_indent')
        if re.match(r'^(<{7}|={7}|>{7})( |$)', line):
            reasons.append('conflict_marker')
        if reasons:
            whitespace.append({'path': rel, 'line': number, 'reasons': reasons})
    if data.endswith(b'\n\n'):
        whitespace.append({'path': rel, 'reasons': ['new_blank_line_at_eof']})
OUT['new_text_whitespace'] = {'files_checked': len(new_text), 'findings': whitespace}
check('new_text_whitespace', not whitespace)

storage_file = PACKET / 'raw-log-storage.json'
storage = json.loads(read(storage_file))
mapping = {row['logical_path']: row for row in storage['files']}
check('gzip_mapping_count', len(mapping) == len(storage['files']) == 9)
check('gzip_stored_paths_unique', len({row['stored_path'] for row in mapping.values()}) == 9)
raw_results = []
prior = json.loads(read(NOTES / 'agent-54.json'))
prior_files = {row['path']: row for row in prior['files']}
for logical, row in mapping.items():
    assert Path(logical).parts[:1] == ('agents',) and '..' not in Path(logical).parts
    assert row['stored_path'] == logical + '.gz'
    stored_path = PACKET / row['stored_path']
    compressed = read(stored_path, 1024 * 1024)
    assert 0 <= row['original_size_bytes'] <= 1024 * 1024
    with gzip.GzipFile(fileobj=io.BytesIO(compressed), mode='rb') as handle:
        raw = handle.read(row['original_size_bytes'] + 1)
        eof = handle.read(1) == b''
    originals = [directory / Path(logical).name for directory in (NOTES, TASK / 'validation')
                 if (directory / Path(logical).name).is_file()]
    assert len(originals) == 1
    original = read(originals[0], 1024 * 1024)
    prior_row = prior_files[str((PACKET / logical).relative_to(REPO))]
    checks = {
        'bounded_decompression_reached_eof': eof,
        'original_size_matches': len(raw) == row['original_size_bytes'],
        'original_sha256_matches': digest(raw) == row['original_sha256'],
        'stored_size_matches': len(compressed) == row['stored_size_bytes'],
        'stored_sha256_matches': digest(compressed) == row['stored_sha256'],
        'stored_git_blob_matches_independent_hash': blob(compressed) == row['stored_git_blob'],
        'stored_git_blob_matches_git_hash_object': git('hash-object', '--', str(stored_path)).decode().strip() == row['stored_git_blob'],
        'original_notes_equal': raw == original,
        'agent54_reviewed_original_sha256_matches': digest(raw) == prior_row['sha256'],
        'agent54_reviewed_original_size_matches': len(raw) == prior_row['bytes'],
        'deterministic_gzip_bytes_match': gzip.compress(raw, mtime=0) == compressed,
        'zero_gzip_mtime': compressed[4:8] == b'\0\0\0\0',
        'uncompressed_packet_path_absent': not (PACKET / logical).exists(),
    }
    check('gzip_' + logical, all(checks.values()), checks)
    raw_results.append({**row, 'source': str(originals[0].relative_to(TASK)), 'checks': checks})
OUT['raw_log_storage'] = {'mapping_identity': identity(storage_file), 'files': raw_results,
                          'decompression_bound_per_file': 1024 * 1024, 'disk_extraction': False}
zip_path = PACKET / 'base-governance/original.zip'
zip_data = read(zip_path, 2 * 1024 * 1024)
OUT['public_zip'] = {**identity(zip_path), 'git_blob': blob(zip_data),
                     'notes_copy_equal': zip_data == read(NOTES / 'base-governance.zip', 2 * 1024 * 1024),
                     'reexpanded': False}
check('public_zip', len(zip_data) == 1320535 and digest(zip_data) == '928e3d87bf32d2ea2d9b48581457f9bdd3086113b3129e0c562072da8d232156'
      and blob(zip_data) == '91b63b09bea52345e93847c5ee440ee25d3f21a1' and OUT['public_zip']['notes_copy_equal'])
expected_binary = {str(zip_path.relative_to(REPO))} | {str((PACKET / row['stored_path']).relative_to(REPO)) for row in mapping.values()}
OUT['binary_paths'] = binary
check('only_expected_binary_additions', set(binary) == expected_binary)

ledger_path = PACKET / 'agent-ledger.json'
ledger = json.loads(read(ledger_path))
roster = json.loads(read(NOTES / 'agents.json'))
completed = {row['number']: row for row in roster if row['status'] == 'complete'}
ledger_checks = {
    'count_58': ledger['completed_agents'] == len(ledger['agents']) == 58,
    'numbers_complete_unique_1_to_58': sorted(row['number'] for row in ledger['agents']) == list(range(1, 59)),
    'task_names_unique': len({row['canonical_task_name'] for row in ledger['agents']}) == 58,
    'all_rows_complete_fresh': all(row['status'] == 'complete' and row['fresh_context'] is True for row in ledger['agents']),
    'pending_final_explicit': ledger['requested_agents'] == 60 and ledger['all_assignments_complete'] is False,
    'matches_completed_roster': set(completed) == set(range(1, 59)),
}
report_results = []
for row in ledger['agents']:
    report = PACKET / row['report']
    actual = digest(read(report))
    checks = {'report_hash_matches': actual == row['report_sha256'],
              'notes_copy_equal': read(report) == read(NOTES / report.name),
              'roster_fields_match': all(row[k] == v for k, v in completed[row['number']].items()),
              'canonical_task_name_matches': row['canonical_task_name'] == '/root/' + row['task_name']}
    check('ledger_report_' + str(row['number']), all(checks.values()), checks)
    report_results.append({'number': row['number'], 'path': row['report'], 'sha256': actual, 'checks': checks})
check('ledger_structure', all(ledger_checks.values()), ledger_checks)
OUT['ledger'] = {'identity': identity(ledger_path), 'checks': ledger_checks, 'reports': report_results}

links = []
link_files = sorted(PACKET.rglob('*.md')) + [REPO / path for path in tracked + new
                                          if path.endswith('.md') and not (REPO / path).is_relative_to(PACKET)]
for source in link_files:
    text = read(source).decode()
    for match in re.finditer(r'\[[^\]\n]*\]\(([^\n)]*)\)', text):
        target = match.group(1).strip()
        if target.startswith('<'):
            target = target[1:target.find('>')]
        else:
            target = target.split(' ', 1)[0]
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc or not parsed.path:
            continue
        path = (source.parent / unquote(parsed.path)).resolve()
        exists = path.exists()
        mapped = False
        if not exists and path.is_relative_to(PACKET):
            logical = str(path.relative_to(PACKET))
            if logical in mapping:
                exists = (PACKET / mapping[logical]['stored_path']).is_file()
                mapped = True
        record = {'source': str(source.relative_to(REPO)), 'target': target,
                  'exists': exists, 'lossless_storage_map_resolution': mapped}
        links.append(record)
        check('local_link', exists, record)
OUT['local_links'] = {'markdown_files': len(link_files), 'local_links_checked': len(links),
                       'links': links, 'scope': 'local target existence; fragment content not validated'}

publication_path = TASK / 'validation/publication-source-freeze.json'
freeze = json.loads(read(publication_path))
freeze_results = []
for row in freeze['files']:
    actual = identity(REPO / row['path'])
    matches = all(actual[k] == row[k] for k in ('sha256', 'size_bytes', 'mode'))
    check('publication_freeze_' + row['path'], matches)
    freeze_results.append({**row, 'matches_current': matches})
check('publication_freeze_count', len(freeze_results) == 23)
check('publication_freeze_packet_copy', read(publication_path) == read(PACKET / 'validation/publication-source-freeze.json'))
check('publication_freeze_identity', digest(read(publication_path)) == '6c90e8e2c097b1d8db3534835d4f8ae94c4f6dc2c20b1c59283342c0b1c2dbf8')
OUT['publication_freeze'] = {'identity': identity(publication_path), 'files': freeze_results}
historical = TASK / 'validation/operational-source-freeze.json'
check('historical_freeze_identity', digest(read(historical)) == '714deb35f890b197d43e5b2de0a02c3ede1cb8ec0bf944f057cb349c9b1bdceb'
      and read(historical) == read(PACKET / 'validation/operational-source-freeze.json'))
historical_rows = {row['path']: row for row in json.loads(read(historical))['files']}
current_rows = {row['path']: row for row in freeze['files']}
OUT['freeze_comparison'] = {
    'changed': [path for path in historical_rows.keys() & current_rows.keys() if historical_rows[path] != current_rows[path]],
    'added': sorted(current_rows.keys() - historical_rows.keys()), 'removed': sorted(historical_rows.keys() - current_rows.keys()),
}
check('only_final_pack_freeze_change', OUT['freeze_comparison'] == {
    'changed': ['ci/project/p06_qualified_warm_pack.py'],
    'added': ['ci/project/test_p06_pack_final_cleanup.py'], 'removed': []})
frozen_inputs = json.loads(read(TASK / 'validation/frozen-inputs-before.json'))
measurements = json.loads(read(TASK / 'validation/measurement-sources-before.json'))['records']
OUT['protected_identity_checks'] = []
for row in frozen_inputs + measurements:
    data = read(REPO / row['path'])
    matches = digest(data) == row['sha256'] and len(data) == row.get('size_bytes', row.get('bytes'))
    check('protected_' + row['path'], matches)
    OUT['protected_identity_checks'].append({'path': row['path'], 'sha256': digest(data), 'matches': matches})
phase_paths = ['docs/project/roadmap.json', 'docs/project/acceptance.md', 'ROADMAP.md',
               'docs/project/phases/p01-baseline.md', 'docs/project/phases/p06-performance.md',
               'docs/project/evidence/p01-xrt-blocked.json', 'ci/project/p06_qualified_warm_admission.py',
               'docs/designs/qualified_warm_retention_review_v1.md', 'docs/designs/qualified_warm_automation_v1.md']
OUT['phase_base_bindings'] = []
for path in phase_paths:
    data = read(REPO / path)
    matches = data == git('show', BASE + ':' + path)
    check('phase_unchanged_' + path, matches)
    OUT['phase_base_bindings'].append({'path': path, 'sha256': digest(data), 'matches_base': matches})
roadmap = json.loads(read(REPO / 'docs/project/roadmap.json'))
phases = {p['id']: p for p in roadmap['phases']}
OUT['phase_state'] = {'P01': phases['P01']['status'], 'P06': phases['P06']['status'],
                      'P07': phases['P07']['status'], 'P06_evidence_ids': [r['acceptance_id'] for r in phases['P06']['evidence']]}
check('phase_constraints', OUT['phase_state'] == {'P01': 'blocked', 'P06': 'in_progress', 'P07': 'not_started', 'P06_evidence_ids': ['P06-A01']})

patterns = {
    'age_private_identity': rb'AGE-SECRET-KEY-1[0-9A-Z]{50,}',
    'private_pem': rb'-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----',
    'github_token': rb'(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})',
    'openai_token': rb'\bsk-(?:proj-)?[A-Za-z0-9_-]{24,}',
    'slack_token': rb'\bxox[baprs]-[A-Za-z0-9-]{16,}',
    'aws_access_id': rb'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b',
    'google_api_key': rb'\bAIza[A-Za-z0-9_-]{30,}',
    'jwt': rb'\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}',
    'credential_url': rb'https?://[^\s/"<>:]+:[^\s/"<>@]+@',
    'signed_url_parameter': rb'(?i)[?&](?:sig|signature|x-amz-signature|x-goog-signature)=[^\s"<>]+',
    'azure_account_key': rb'(?i)AccountKey=[A-Za-z0-9+/=]{20,}',
    'bearer_literal': rb'(?i)Bearer\s+[A-Za-z0-9._~+/=-]{20,}',
}
recent = sorted(path for n in range(55, 59) for path in NOTES.glob(f'agent-{n}*') if path.is_file())
privacy_rows = []
for path in recent:
    data = read(path)
    data.decode('utf-8')
    hits = []
    for name, pattern in patterns.items():
        found = list(re.finditer(pattern, data))
        if found:
            hits.append({'category': name, 'count': len(found), 'lines': sorted({data[:m.start()].count(b'\n') + 1 for m in found})})
    packet_copy = PACKET / 'agents' / path.name
    same = read(packet_copy) == data
    check('recent_copy_' + path.name, same)
    check('recent_privacy_' + path.name, not hits, hits)
    privacy_rows.append({**identity(path), 'packet_copy_equal': same, 'pattern_candidates': hits})
packet_files = []
special = []
for parent, dirs, files in os.walk(PACKET, followlinks=False):
    for name in dirs + files:
        path = Path(parent) / name
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode) or not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            special.append(str(path.relative_to(PACKET)))
        elif stat.S_ISREG(mode):
            packet_files.append(identity(path))
top_dirs = sorted(str(path.relative_to(PACKET)) for path in PACKET.iterdir() if path.is_dir())
check('packet_structure', not special and top_dirs == ['agents', 'base-governance', 'validation'])
sync_text = read(NOTES / 'sync_evidence.py').decode()
symlink_guard = 'assert not source.is_symlink(), source' in sync_text
check('synchronizer_symlink_guard', symlink_guard)
OUT['recent_privacy'] = {'artifacts': privacy_rows, 'pattern_names': list(patterns), 'match_values_retained': False,
                         'special_packet_entries': special, 'top_level_directories': top_dirs,
                         'private_worktrees_present': False if not special and top_dirs == ['agents', 'base-governance', 'validation'] else None,
                         'synchronizer_symlink_guard_present': symlink_guard,
                         'limits': 'Pattern and structural review cannot exclude every secret encoding. Prior reviewed bytes retain prior scope.'}
OUT['packet_inventory'] = sorted(packet_files, key=lambda row: row['path'])
OUT['reviewed_control_identities'] = [identity(path) for path in (
    NOTES / 'publication-plan.md', NOTES / 'prepared-publication.json', NOTES / 'sync_evidence.py',
    NOTES / 'agent-54.json', REPO / 'AGENTS.md', PACKET / 'README.md', historical,
    REPO / 'ci/project/check_project.py', REPO / 'ci/project/check_baseline_packets.py', REPO / 'ci/project/preflight.py')]
OUT['candidate_changed_during_review'] = [row['path'] for row in OUT['candidate_inventory'] if identity(TASK / row['path']) != row]
check('candidate_stable_during_review', not OUT['candidate_changed_during_review'])
OUT['finished_utc'] = datetime.datetime.now(datetime.UTC).isoformat()
OUT['pass'] = not OUT['findings']
OUT['scope_limits'] = ['No repository or Git writes, native execution, test bodies, full unittest, strict runner, external mutation or child agent.',
                       'Agent 60, final 60-report ledger and final manifest remain explicit root gates.',
                       'Metadata/preflight success does not qualify the unpublished changed source or satisfy native admission.']
output = NOTES / 'agent-59.json'
output.write_text(json.dumps(OUT, indent=2) + '\n')
print(json.dumps({'pass': OUT['pass'], 'findings': OUT['findings'], 'commands': [{'label': c['label'], 'returncode': c['returncode']} for c in OUT['commands']],
                  'candidate_counts': OUT['candidate_counts'], 'new_text_files': len(new_text), 'binary_files': len(binary),
                  'gzip_files': len(raw_results), 'ledger_reports': len(report_results), 'local_links': len(links),
                  'publication_files': len(freeze_results), 'privacy_artifacts': len(privacy_rows),
                  'output': str(output), 'sha256': digest(read(output))}, indent=2))
