#!/usr/bin/env python3
"""Finish the snapshot review while explicitly identifying active ledger work."""
import ast
import hashlib
import json
from pathlib import Path
import re

R = Path('/workspace/scratch/ba0248fde989/AI-GPU')
E = R / 'docs/project/evidence/p05-python'
W = R.parent / 'p05-work/w10_a6'
d = json.loads((W / 'checks.json').read_bytes())
email = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b')
locations = []
for name in sorted({x['path'] for x in d['privacy_scan']['email_locations']}):
    obj = json.loads((E / name).read_bytes())
    def walk(value, path):
        if isinstance(value, dict):
            for k, v in value.items():
                walk(v, path + [k])
        elif isinstance(value, list):
            for i, v in enumerate(value):
                walk(v, path + [str(i)])
        elif isinstance(value, str) and email.search(value):
            assert path in [['head_commit', 'author', 'email'], ['head_commit', 'committer', 'email']]
            locations.append({'path': name, 'property_path': '.'.join(path),
                              'disposition': 'Public GitHub commit authorship metadata from the repository run API.'})
    walk(obj, [])
assert len(locations) == 12

changed = []
for row in d['privacy_scan']['records']:
    name = row['path']
    if name.startswith('archives/'):
        continue
    p = R / name[len('repository/'):] if name.startswith('repository/') else E / name
    if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != row['sha256']:
        changed.append(name)
assert changed == ['development/build_agent_ledger.py'], changed

builder = E / changed[0]
body = builder.read_bytes()
assert len(body) > 1000
text = body.decode('utf-8')
ast.parse(text)
patterns = {
    'private_key': r'-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----',
    'github_token': r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b',
    'aws_access_key': r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b',
    'signed_url_parameter': r'https?://[^\s<>"\']+[?&](?:X-Amz-Signature|X-Goog-Signature|sig|access_token|token)=[^\s<>"\']+',
    'connector_account_id': r'\blink_[0-9a-f]{24,}\b',
    'home_user_path': r'/(?:Users|home)/(?!runner(?:/|\b)|agent(?:/|\b)|ubuntu(?:/|\b)|vortex(?:/|\b))[^/\s"\']+/',
}
matches = [label for label, pattern in patterns.items() if re.search(pattern, text, re.I if label == 'signed_url_parameter' else 0)]
assert not matches and not email.search(text)
assert builder.read_bytes() == body
for row in d['archives'] + d['checked_source_bodies']:
    assert hashlib.sha256((R / row['path']).read_bytes()).hexdigest() == row['sha256'], row['path']
initial = {
    'scope': 'Separate read-only post-scan stability assertion, after the main delivery scan exited 0.',
    'exit_code': 1, 'outcome': 'fail', 'observation': "AssertionError: ['development/build_agent_ledger.py']",
    'disposition': 'The designated ledger writer was still editing this one unqualified evidence tool. The original scan is retained, its current body is separately scanned, and final ledger/candidate freeze remains pending with root.',
    'tool_output_retention': 'Transcription of the observed exec tool completion; no separate command timer or stdout file existed for that inline probe.',
}
(W / 'initial-stability-observation.json').write_text(json.dumps(initial, indent=2, sort_keys=True) + '\n')
result = {
    'schema_version': 1, 'outcome': 'pass', 'candidate_secret_matches': 0,
    'email_occurrences': len(locations), 'email_dispositions': locations,
    'all_other_scanned_existing_text_inputs_stable': True,
    'concurrent_evidence_tool': {'path': changed[0], 'size_bytes': len(body),
                                'rescanned_sha256': hashlib.sha256(body).hexdigest(), 'candidate_matches': [],
                                'stable_during_targeted_rescan': True, 'final_freeze_required': True},
    'archives_and_checked_source_bodies_stable': True,
    'limitations': [
        'UTF-8 text and raw/nested archive text only; binaries were neither executed nor treated as complete secret scans.',
        'This is not an attestation of a future final tree. Later receipts and ledger additions require root finalization.',
        'Public GitHub commit-author/committer email metadata is retained as public repository attribution; matched values are not repeated in this review.',
    ],
}
(W / 'privacy-disposition.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
print(json.dumps({'outcome': 'pass', 'public_email_properties': len(locations),
                  'concurrent_tool_rescanned_sha256': result['concurrent_evidence_tool']['rescanned_sha256'],
                  'secret_matches': 0}, sort_keys=True))
