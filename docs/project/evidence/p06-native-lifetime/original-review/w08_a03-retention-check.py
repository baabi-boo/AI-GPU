#!/usr/bin/env python3
"""Inert checks of the exact retained original and publication packet."""
from pathlib import Path, PurePosixPath
import hashlib
import json
import re
import stat
import subprocess
import time
import zipfile

REPO = Path('/tmp/ai-gpu-native-lifetime-dfd857')
WORK = Path('/tmp/ai-gpu-native-lifetime-dfd857-work')
PACKET = REPO / 'docs/project/evidence/p06-native-lifetime'
NATIVE = PACKET / 'native/b4127b19-run45130300651-attempt1'
BASE = '6130a2f7424932a6f3b7377ef8ae4816da2b304f'
HEAD = 'b4127b19a004b5aebb8d52eab9ceda0da3ff4561'
EXPECTED = '3d4879f73c197352689d65feb56e73f537701fc1411e55bf53c92b1b41e13db3'
SIZE = 9086055


def digest(data):
    return hashlib.sha256(data).hexdigest()


def git(*args):
    return subprocess.check_output(['git', *args], cwd=REPO).decode().strip()


def file_identity(path):
    data = path.read_bytes()
    return {'path': str(path), 'sha256': digest(data), 'size_bytes': len(data)}


started = time.monotonic()
assert git('rev-parse', 'HEAD') == HEAD
api = json.loads((WORK / 'w08_a03-github-metadata.json').read_text())
assert api['total_count'] == 1 and len(api['artifacts']) == 1
remote = api['artifacts'][0]
assert remote['id'] == 14798140556
assert remote['digest'] == 'sha256:' + EXPECTED and remote['size_in_bytes'] == SIZE
assert remote['workflow_run']['id'] == 45130300651
assert remote['workflow_run']['head_sha'] == HEAD and remote['workflow_run']['head_branch'] == 'master'
assert remote['expired'] is False
assert json.loads((NATIVE / 'artifact-metadata.json').read_text()) == api

repo_archive = (NATIVE / 'original.zip').read_bytes()
work_archive = (WORK / 'native-original.zip').read_bytes()
assert repo_archive == work_archive and len(repo_archive) == SIZE
assert digest(repo_archive) == EXPECTED
assert git('hash-object', str(NATIVE / 'original.zip')) == '5a9dae6b08ca7b3ee789363666be4827eb553ab8'
inventory = json.loads((NATIVE / 'member-inventory.json').read_text())
assert inventory['archive_sha256'] == EXPECTED and inventory['archive_bytes'] == SIZE
assert (NATIVE / 'member-inventory.json').read_bytes() == (WORK / 'native-original-inventory.json').read_bytes()
assert (NATIVE / 'job-original.log').read_bytes() == (WORK / 'native-job-original.log').read_bytes()
rows = inventory['files']
assert len(rows) == 1264 and len({row['path'] for row in rows}) == len(rows)
index = {row['path']: row for row in rows}

# Only candidate locations/counts are retained, never a matched secret value.
patterns = {
    'signed-cloud-url': re.compile(rb'https?://[^\s<>\"\']+[?&](?:sig|X-Amz-Signature|X-Amz-Credential|X-Amz-Security-Token)=[^\s<>\"\']+', re.I),
    'github-token': re.compile(rb'\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b'),
    'aws-access-key': re.compile(rb'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'),
    'private-key': re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----'),
    'url-password': re.compile(rb'https?://[^\s/:@]+:[^\s/@]+@', re.I),
    'literal-bearer': re.compile(rb'Authorization[\"\']?\s*[:=]\s*[\"\']?Bearer\s+[A-Za-z0-9_./+~-]{24,}', re.I),
}
candidates = []
scanned_text_bytes = 0
scanned_text_files = 0


def scan(label, body):
    global scanned_text_bytes, scanned_text_files
    try:
        body.decode('utf-8', 'strict')
    except UnicodeError:
        return False
    scanned_text_bytes += len(body)
    scanned_text_files += 1
    for name, pattern in patterns.items():
        matches = list(pattern.finditer(body))
        if matches:
            candidates.append({'path': label, 'pattern': name, 'matches': len(matches)})
    return True


members = []
with zipfile.ZipFile(NATIVE / 'original.zip') as archive:
    infos = archive.infolist()
    assert len(infos) == len(index) and len({info.filename for info in infos}) == len(infos)
    assert {info.filename for info in infos} == set(index)
    assert sum(info.file_size for info in infos) == 37138100
    for info in infos:
        name = info.filename
        path = PurePosixPath(name)
        assert name == str(path) and not path.is_absolute() and '..' not in path.parts
        assert '\\' not in name and not info.is_dir()
        assert stat.S_IFMT(info.external_attr >> 16) in (0, stat.S_IFREG)
        assert not info.flag_bits & 1
        body = archive.read(info)  # Read-to-end also checks this member's CRC.
        expected = index[name]
        assert len(body) == info.file_size == expected['size_bytes']
        assert digest(body) == expected['sha256']
        assert body == (WORK / 'native-original' / path).read_bytes()
        members.append({'path': name, 'sha256': expected['sha256'], 'size_bytes': len(body)})
        scan('original.zip:' + name, body)

extracted_names = {str(p.relative_to(WORK / 'native-original'))
                   for p in (WORK / 'native-original').rglob('*') if p.is_file()}
assert extracted_names == set(index)
packet_paths = sorted(p for p in PACKET.rglob('*') if p.is_file() and p.suffix != '.zip')
packet_observation = []
for path in packet_paths:
    body = path.read_bytes()
    packet_observation.append({'path': str(path.relative_to(REPO)),
                               'sha256': digest(body), 'size_bytes': len(body)})
    scan(str(path.relative_to(REPO)), body)
for identity in packet_observation:
    assert digest((REPO / identity['path']).read_bytes()) == identity['sha256']

old_roots = {}
for line in git('ls-tree', BASE + ':docs/project/evidence').splitlines():
    prefix, name = line.split('\t', 1)
    mode, kind, sha = prefix.split()
    old_roots[name] = {'mode': mode, 'type': kind, 'sha': sha}
assert len(old_roots) == 40
assert sum(row['type'] == 'tree' for row in old_roots.values()) == 25
assert sum(row['type'] == 'blob' for row in old_roots.values()) == 15
for name, row in old_roots.items():
    assert git('rev-parse', HEAD + ':docs/project/evidence/' + name) == row['sha']
dirty = subprocess.check_output(['git', 'status', '--porcelain=v1', '-z',
                                 '--untracked-files=all', '--', 'docs/project/evidence'], cwd=REPO)
for raw in dirty.decode().split('\0'):
    if not raw:
        continue
    assert raw[3:].split('/')[3] not in old_roots

historical = []
for relative in (
    'docs/project/evidence/p06-managed-preflight/native/run-45084009157-attempt1.zip',
    'docs/project/evidence/p06-managed-preflight/native/run-45085300171-attempt1.zip',
    'docs/project/evidence/p06-managed-preflight-replay/local-replay/f88cccff/runner/p06-managed-preflight-replay/evidence/failed-control.json',
):
    before = subprocess.check_output(['git', 'show', BASE + ':' + relative], cwd=REPO)
    current = (REPO / relative).read_bytes()
    assert before == current
    historical.append({'path': relative, 'sha256': digest(current), 'size_bytes': len(current)})
assert digest((NATIVE / 'original.zip').read_bytes()) == EXPECTED
assert git('rev-parse', 'HEAD') == HEAD

receipt = {
    'scope': 'inert durable-original retention and point-in-time packet inspection',
    'outcome': 'pass' if not candidates else 'candidate_review_required',
    'reviewed_revision': HEAD,
    'archive': {'sha256': EXPECTED, 'size_bytes': SIZE,
                'git_blob': '5a9dae6b08ca7b3ee789363666be4827eb553ab8',
                'members': len(members), 'expanded_bytes': sum(row['size_bytes'] for row in members)},
    'api_metadata_sha256': digest((WORK / 'w08_a03-github-metadata.json').read_bytes()),
    'native_envelope_files': [file_identity(p) for p in sorted(NATIVE.iterdir()) if p.is_file()],
    'packet_files_observed': packet_observation,
    'secret_pattern_scan': {'patterns': list(patterns), 'utf8_files': scanned_text_files,
                            'utf8_bytes': scanned_text_bytes, 'candidates': candidates,
                            'limitation': 'Pattern-based inspection of the enumerated observed text only; not a universal secret-detection claim.'},
    'historical_top_level_entries_unchanged': old_roots,
    'historical_originals': historical,
    'retained_code_executed': False,
    'retained_binaries_executed': False,
    'native_execution': 'not_run',
    'checker_development_correction': 'The initial checker incorrectly assumed that all 40 top-level historical entries were trees. Git records 25 trees and 15 blobs; the final checker verifies every one of the 40 entries. No artifact or production change was required.',
    'seconds': time.monotonic() - started,
}
(WORK / 'w08_a03-retention-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps({'outcome': receipt['outcome'], 'archive_members': len(members),
                  'packet_files': len(packet_observation), 'scan': receipt['secret_pattern_scan'],
                  'historical_roots': len(old_roots), 'seconds': receipt['seconds']}))
