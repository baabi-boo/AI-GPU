#!/usr/bin/env python3
"""Read-only artifact and publication snapshot; writes only its own JSON result."""
import collections
import datetime
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import zipfile

SCRATCH = Path('/workspace/scratch/279b6658611e')
REPO = Path('/workspace/ai-gpu-next')
ROOT = REPO / 'docs/project/evidence/p06-dependency-provenance/local-execution'
BASE = '849469e1111870fbcfe0346afd33b284a5a1edd8'
READER = 'ba2d649d4150e046c2ba610de02725d9d062b1be'
SOURCE = '0f9aaa36d46364c297254164f5dab0d4f0e88349'
CLAIMS = ('qualified', 'ready_for_warm', 'warm_execution', 'full_warm_coverage',
          'acceptance_claimed', 'phase_acceptance', 'performance_acceptance')
EXPECTED = {f'w{wave:02d}_a{agent:02d}' for wave in range(1, 11) for agent in range(1, 7)}
PINS = [
    ('01', 'failed', '8021368d5efe755ae282ff2a89675979d8a1377582f84fbbea57e35b5ddad502', 29286833, 3540),
    ('02', 'failed', '8d407e6b5355aec7e9736957de613ce8ac0b69b45284617bcc5dcc10305a5b32', 28674439, 3685),
    ('03', 'failed', 'd4136feb365a809ad975bde4e5c553fecbfc3143a5fff8da25a6de191a6cb5cc', 41603298, 5016),
    ('04', 'passed', 'd3a16e1e6e92a68414f5fdcce564b963dde2e9e801601191d52ceeb974faea6f', 47632218, 5597),
]
result = {'schema_version': 1, 'agent': 'w10_a06', 'scope': 'Read-only pre-finalization snapshot; not final ledger or publication proof',
          'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'failures': []}

def check(condition, message):
    if not condition:
        result['failures'].append(message)

def sha(body):
    return hashlib.sha256(body).hexdigest()

def identity(path):
    body = path.read_bytes()
    return {'sha256': sha(body), 'size_bytes': len(body)}

def safe_path(name):
    p = PurePosixPath(name)
    return (bool(name) and not p.is_absolute() and p.as_posix() == name
            and not any(x in ('', '.', '..') for x in name.split('/'))
            and '\\' not in name and not re.match(r'^[A-Za-z]:', name)
            and not any(ord(c) < 32 or ord(c) == 127 for c in name))

def git(*args):
    return subprocess.check_output(['git', *args], cwd=REPO, text=True).strip()

uploads = json.loads((SCRATCH / 'library-upload-result.json').read_text())['results']
private_values = {v.encode() for row in uploads for k, v in row.items()
                  if k in ('file_id', 'library_file_id') and isinstance(v, str) and v}
private_hits = []
secret_candidates = []
patterns = {
    'signed_transfer_url': re.compile(rb'https?://[^\s"<>]+[?&](?:sig|X-Amz-Signature|X-Goog-Signature)=[^\s"<>]+', re.I),
    'github_token': re.compile(rb'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{70,})\b'),
    'private_key_block': re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----\r?\n'),
}

def scan(body, label):
    if any(v in body for v in private_values):
        private_hits.append(label)
    for name, pattern in patterns.items():
        if pattern.search(body):
            secret_candidates.append({'path': label, 'pattern': name})

result['git'] = {'head': git('rev-parse', 'HEAD'), 'tree': git('rev-parse', 'HEAD^{tree}'),
                 'status': git('status', '--short').splitlines(),
                 'master_observation': git('ls-remote', 'origin', 'refs/heads/master')}
result['git']['descends_audited_base'] = subprocess.run(['git', 'merge-base', '--is-ancestor', BASE, 'HEAD'], cwd=REPO).returncode == 0
check(result['git']['head'] == READER, 'reviewed HEAD changed')
check(result['git']['descends_audited_base'], 'HEAD does not descend audited base')
check(result['git']['master_observation'] == BASE + '\trefs/heads/master', 'remote master moved from expected base')

result['archives'] = []
for number, outcome, pin, size, members in PINS:
    name = f'AI-GPU_P06_local_attempt_{number}_{outcome}_2026-11-23.zip'
    path = SCRATCH / name
    before = identity(path)
    sidecar_path = SCRATCH / name.replace('.zip', '.identity.json')
    sidecar = json.loads(sidecar_path.read_text())
    check(before == {'sha256': pin, 'size_bytes': size}, name + ': external identity differs')
    check(identity(ROOT / 'originals' / sidecar_path.name) == identity(sidecar_path), name + ': copied sidecar differs')
    check(sidecar['sha256'] == pin and sidecar['size_bytes'] == size and sidecar['member_count'] == members, name + ': sidecar identity differs')
    check(re.fullmatch(r'[A-Za-z0-9._-]+', name), name + ': unsafe delivery filename')
    check(stat.S_ISREG(path.lstat().st_mode) and path.lstat().st_nlink == 1, name + ': original is not an unlinked regular file')
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        names = [i.filename for i in infos]
        check(len(infos) == members and len(set(names)) == members, name + ': member count or uniqueness differs')
        check(all(safe_path(n) for n in names), name + ': unsafe member name')
        check(all(i.external_attr >> 16 == stat.S_IFREG | 0o644 for i in infos), name + ': member permissions differ from regular 0644')
        check(all(i.date_time == (1980, 1, 1, 0, 0, 0) for i in infos), name + ': deterministic timestamp differs')
        count = collections.Counter(n.split('/')[0] for n in names)
        check(dict(count) == sidecar['subpacket_file_counts'], name + ': packet counts differ')
        check(sum(i.file_size for i in infos) == sidecar['uncompressed_bytes'], name + ': expanded size differs')
        pins_checked = 0
        for info in infos:
            body = archive.read(info)
            scan(body, name + ':' + info.filename)
            if info.filename in sidecar['external_report_pins']:
                check({'sha256': sha(body), 'size_bytes': len(body)} == sidecar['external_report_pins'][info.filename], name + ': report pin differs: ' + info.filename)
                pins_checked += 1
        check(pins_checked == len(sidecar['external_report_pins']), name + ': absent pinned report')
        env = json.loads(archive.read('local-execution.json'))
        check(all(env[k] is False for k in CLAIMS), name + ': elevated envelope claim')
        check(env['outcome'] == sidecar['original_outcome'] and env['native_execution'] == sidecar['original_native_execution'], name + ': sidecar envelope outcome differs')
        check(env['expected_revision'] == sidecar['original_revision'], name + ': source revision differs')
        row = {'filename': name, **before, 'member_count': members,
               'expanded_bytes': sum(i.file_size for i in infos), 'all_members_crc_read': True,
               'safe_unique_regular_0644_members': True, 'external_reports_verified': pins_checked,
               'source_revision': env['expected_revision'], 'outcome': env['outcome'],
               'native_execution': env['native_execution'], 'duration_seconds': env['duration_seconds'],
               'all_seven_claims_false': all(env[k] is False for k in CLAIMS),
               'stages': [{'id': s['id'], 'outcome': s['outcome'], 'exit_code': s.get('exit_code')} for s in env['stages']]}
        if number in ('03', '04'):
            native = json.loads(archive.read('native-lifetime/report.json'))
            row['child_native_outcome'] = native['outcome']
            row['child_native_execution'] = native['native_execution']
        if number == '04':
            check(env['expected_revision'] == SOURCE and len(env['stages']) == 5 and all(s['outcome'] == 'pass' and s['exit_code'] == 0 for s in env['stages']), 'attempt04 complete execution scope differs')
            check(all(env[k] is True for k in ('fresh_dependency_build_passed', 'dependency_source_to_loaded_binary_verified', 'separate_controls_passed')), 'attempt04 execution joins differ')
            check(env['duration_seconds'] == 894.591061, 'attempt04 duration differs')
    check(identity(path) == before, name + ': original changed during read')
    result['archives'].append(row)

host = SCRATCH / 'validation/p06-hosted-failed-19333193-run45162083701.zip'
result['hosted_failed_archive'] = identity(host)
check(result['hosted_failed_archive'] == {'sha256': '6c130c17cc944f633f04835dbad6fd512880e6d987f477b01c48d32d4dd68472', 'size_bytes': 9225}, 'hosted failed ZIP identity differs')
check(identity(ROOT / 'originals' / host.name) == identity(host), 'copied hosted ZIP differs')
with zipfile.ZipFile(host) as archive:
    result['hosted_failed_archive']['members'] = len(archive.infolist())
    for i in archive.infolist():
        check(safe_path(i.filename.rstrip('/')), 'hosted ZIP unsafe member')
        scan(archive.read(i), host.name + ':' + i.filename)

index_path = ROOT / 'evidence-index.json'
index_before = identity(index_path)
index = json.loads(index_path.read_text())
paths = [row['path'] for row in index['files']]
check(len(paths) == len(set(paths)), 'duplicate evidence-index paths')
compressed = 0
stored_bytes = 0
for row in index['files']:
    check(safe_path(row['path']), 'unsafe evidence-index path: ' + row['path'])
    p = ROOT / row['path']
    check(stat.S_ISREG(p.lstat().st_mode) and p.lstat().st_nlink == 1 and p.lstat().st_mode & 0o777 == 0o644, 'indexed file type/mode differs: ' + row['path'])
    body = p.read_bytes()
    check(sha(body) == row['sha256'] and len(body) == row['size_bytes'], 'stored index identity differs: ' + row['path'])
    stored_bytes += len(body)
    if row['compression'] == 'gzip-mtime-zero':
        check(int.from_bytes(body[4:8], 'little') == 0, 'gzip timestamp not zero: ' + row['path'])
        body = gzip.decompress(body)
        compressed += 1
    else:
        check(row['compression'] == 'none', 'unknown evidence compression')
    check(sha(body) == row['uncompressed_sha256'] and len(body) == row['uncompressed_size_bytes'], 'uncompressed index identity differs: ' + row['path'])
    scan(body, row['path'])
check(identity(index_path) == index_before, 'evidence index changed during snapshot')
result['evidence_index'] = {**index_before, 'files_verified': len(paths), 'stored_bytes': stored_bytes, 'gzip_files_verified': compressed, 'copied_report_count': index['completed_agent_reports'], 'unchanged_during_read': identity(index_path) == index_before}

copied = {p.stem: p for p in (ROOT / 'agents').glob('*.md')}
scratch_reports = {p.stem: p for p in (SCRATCH / 'agent-reports').glob('*.md')}
check(set(copied) <= EXPECTED and set(scratch_reports) <= EXPECTED, 'unexpected report identity')
check(set(copied) == set(index['agents']) and len(copied) == index['completed_agent_reports'], 'index report inventory differs')
pending_report_refresh = []
for name, p in copied.items():
    if p.read_bytes() != scratch_reports[name].read_bytes():
        if name in ('w09_a03', 'w09_a04'):
            pending_report_refresh.append({'agent': name, 'copied': identity(p), 'current_scratch': identity(scratch_reports[name]), 'reason': 'Known provisional documentation report finalized after this copied-index snapshot; refresh required before publication'})
        else:
            check(False, 'copied report differs: ' + name)
    titles = [line[2:].strip() for line in p.read_text(encoding='utf-8').splitlines() if line.startswith('# ')]
    check(len(titles) == 1 and bool(titles[0]), 'report title malformed: ' + name)
ledger = json.loads((ROOT / 'agent-execution.json').read_text())
check(len(ledger['entries']) == 60 and {r['agent'] for r in ledger['entries']} == EXPECTED, 'ledger requested identity set differs')
retained = [r for r in ledger['entries'] if r['status'] == 'report_retained']
for row in retained:
    check(row['canonical_task'] == '/root/' + row['agent'], 'ledger canonical task differs')
    check(identity(ROOT / row['report_path']) == {k: row[k] for k in ('sha256', 'size_bytes')}, 'ledger fabricates/stales completed identity: ' + row['agent'])
check(len(retained) == ledger['retained_report_count'], 'ledger completed count differs')
check(ledger['complete'] == (len(retained) == 60), 'ledger completion flag fabricated')
identity_rows = [{k: row[k] for k in ('agent', 'report_path', 'size_bytes', 'sha256')} for row in retained]
check(sha(json.dumps(identity_rows, sort_keys=True, separators=(',', ':')).encode()) == ledger['report_identity_set_sha256'], 'ledger set digest differs')
result['report_inventory_snapshot'] = {'expected': 60, 'copied': len(copied), 'scratch': len(scratch_reports), 'ledger_retained': len(retained), 'ledger_complete': ledger['complete'], 'copied_missing': sorted(EXPECTED-set(copied)), 'scratch_missing': sorted(EXPECTED-set(scratch_reports)), 'ledger_missing': ledger['missing_reports'], 'copied_reports_match_scratch': not pending_report_refresh, 'pending_documentation_report_refresh': pending_report_refresh, 'self_report_not_yet_written': 'w10_a06' not in scratch_reports}

replay_path = SCRATCH / 'validation/local-attempt-04-replay.json'
replay_summary_path = SCRATCH / 'validation/local-attempt-04-replay-summary.json'
replay = json.loads(replay_path.read_text())
summary = json.loads(replay_summary_path.read_text())
process = json.loads((SCRATCH / 'validation/local-attempt-04-replay-process.json').read_text())
check(identity(replay_path) == {'sha256': '2a28ebd63c136ccfde0b0b98c109e45765911fe1c53765ee0ca2b6cbdd669c3d', 'size_bytes': 1595517}, 'public replay pin differs')
check(identity(replay_summary_path) == {'sha256': 'e262d14fa2fb038b5f14fb1fa5831231335f29af938535d22380d506eacd140a', 'size_bytes': 9807}, 'public replay summary pin differs')
check(replay['outcome'] == 'pass' and replay['native_execution'] == 'not_run' and replay['retained_code_executed'] is False and all(replay[k] is False for k in CLAIMS), 'replay outcome/scope differs')
check(process['reader_revision'] == READER and process['source_revision'] == SOURCE and process['exit_code'] == 0 and process['prohibited_events'] == [] and process['archive_unchanged'], 'public replay execution receipt differs')
check(replay['managed_counts'] == {'available_queries':528,'cache_flush_reads':132,'checked_words':4224,'dcr_reads':1188,'half_replies':1056,'launches':132,'processes':4,'snapshots':16,'unavailable_rows':192}, 'managed native counts differ')
check(replay['local_identity']['origin_authenticated'] is False and replay['local_identity']['stages_checked'] == 5 and replay['local_identity']['retained_members_checked'] == 5597, 'local original scope differs')
result['public_replay'] = {**identity(replay_path), 'summary': identity(replay_summary_path), 'reader_revision': READER, 'original_source_revision': SOURCE, 'outcome': replay['outcome'], 'native_execution': replay['native_execution'], 'retained_code_executed': False, 'all_seven_claims_false': True, 'duration_seconds': process['duration_seconds'], 'prohibited_events': process['prohibited_events'], 'managed_counts': replay['managed_counts'], 'control_population_included': False}

logs = [('full-governance-ac2f2ae7.log', 4256, 'clean ac2f2ae7'), ('w07_a02-affected-reader-regression.log', 136, 'clean 7251f078'), ('w08_a02-json-regression.log', 118, 'changed-file profile over 7251f078, projected to 0f9aaa36'), ('w09_a01-hosted-prepare-tests.log', 40, 'changed-file profile over 0f9aaa36, projected to 8d735eba'), ('w08_a05-hosted-layout-final.log', 7, 'test profile over 0f9aaa36 at actual hosted pathname, projected to 8d735eba'), ('w10_a02-runtime-diagnostic-tests.log', 8, 'changed-file profile over 8d735eba, projected to ba2d649d'), ('w10_a02-existing-control-tests.log', 14, 'changed-file profile over 8d735eba, projected to ba2d649d')]
result['test_log_observations'] = []
for name, expected, source in logs:
    p = SCRATCH / 'validation' / name
    text = p.read_text()
    runs = re.findall(r'^Ran (\d+) tests? in ([0-9.]+)s$', text, re.M)
    check(len(runs) == 1 and int(runs[0][0]) == expected and re.search(r'^OK$', text, re.M), 'test log count/success differs: ' + name)
    result['test_log_observations'].append({'filename': name, **identity(p), 'tests': expected, 'source_scope': source})

expected_upload_names = {r['filename'] for r in result['archives']}
check(len(uploads) == 4 and all(r['status'] == 'succeeded' for r in uploads), 'durable original upload failed/missing')
check({Path(r['local_path']).name for r in uploads} == expected_upload_names and {r['file_name'] for r in uploads} == expected_upload_names, 'upload source/delivery filenames differ')
result['durable_original_delivery'] = {'succeeded': 4, 'exact_expected_filenames': True, 'private_identifiers_intentionally_not_recorded': True, 'scope': 'Successful uploader metadata; no additional remote byte read-back performed'}

text_scan_paths = []
for raw in git('diff', '--name-only', BASE).splitlines():
    p = REPO / raw
    if p.is_file():
        scan(p.read_bytes(), raw)
        text_scan_paths.append(raw)
for p in ROOT.rglob('*'):
    if p.is_file() and p.suffix in ('.md', '.json', '.py') and p.relative_to(ROOT).as_posix() not in paths:
        scan(p.read_bytes(), p.relative_to(REPO).as_posix())
check(not private_hits, 'private delivery identifier found in publishable evidence')
check(not secret_candidates, 'sensitive transfer/credential candidate requires review')
result['privacy_scan'] = {'exact_private_identifier_hits': private_hits, 'signed_url_or_credential_candidates': secret_candidates, 'scope': 'All local ZIP members, hosted ZIP members, every decoded indexed file, changed tracked files and uncopied package text'}
roadmap = json.loads((REPO / 'docs/project/roadmap.json').read_text())
phases = {p['id']:p for p in roadmap['phases']}
check(phases['P01']['status'] == 'blocked' and phases['P06']['status'] == 'in_progress', 'phase status promoted')
check({x['acceptance_id'] for x in phases['P06']['evidence']} == {'P06-A01'}, 'P06 acceptance promoted')
result['remaining_gate'] = {'P01': 'blocked on vendor XRT hw_emu', 'P06': 'in_progress', 'P06_A02_A03': 'open', 'next_bounded_step': 'Separately versioned 33-selector / 40-cumulative-component / ten-lifetime-premise qualification and admission; warm experiment follows only after admission', 'pending_reads': 'transient balance, not cumulative component 41', 'planned_warm_processes':24}
result['pending_finalization'] = ['Complete final documentation integration from successful original04 and ba2 reader evidence', 'Refresh copied reports/index after all 60 own reports exist', 'Build strict complete ledger and validate its final report identities', 'Recheck evidence index and final tree after assembly; this snapshot predates those writes', 'Create final documentation/evidence commit after appropriate gates', 'Read remote master immediately before expected-SHA, force:false update and verify resulting ref; no publication is claimed here']
result['retained_code_executed'] = False
result.update({k: False for k in CLAIMS})
result['finished_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
result['outcome'] = 'pass_current_snapshot_pending_finalization' if not result['failures'] else 'fail'
output = SCRATCH / 'validation/w10_a06-publication-preflight.json'
output.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
print(json.dumps({'outcome':result['outcome'], 'failures':result['failures'], 'evidence_index':result['evidence_index'], 'reports':result['report_inventory_snapshot'], 'privacy_scan':result['privacy_scan'], 'output':str(output), **identity(output)}, indent=2))
raise SystemExit(bool(result['failures']))
