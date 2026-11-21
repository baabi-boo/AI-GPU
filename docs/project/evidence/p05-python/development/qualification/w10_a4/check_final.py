"""Read-only final P05 metadata, local-link and preserved-boundary checks."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess

ROOT = Path('/workspace/scratch/ba0248fde989/AI-GPU')
OUT = ROOT / 'docs/project/evidence/p05-python/final-governance'
BASE = '6aac9c421180805a5621156e3d914c685fc6f4a5'
IMPLEMENTATION = 'e1420fd550f716df33a2556057b7086a03032cbe'
DOCS = [
    'AGENTS.md', 'README.md', 'ROADMAP.md', 'docs/project/status.md',
    'docs/project/backlog.md', 'docs/project/p05-entry-handoff.md',
    'docs/project/p05-binding-audit.md', 'docs/project/p05-python-compatibility.md',
    'python/README.md', 'docs/designs/python_binding_v1.md',
    'docs/project/phases/p05-framework.md',
    'docs/project/evidence/p05-python/README.md',
    'docs/project/evidence/p05-python/THIRD_PARTY_NOTICES.md',
    'docs/project/evidence/p05-python/reviews/README.md',
    'docs/project/evidence/p05-python/development/README.md',
    'docs/project/evidence/p05-python/development/host-validation.md',
]

def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)

def sha(body):
    return hashlib.sha256(body).hexdigest()

before = {name: sha((ROOT / name).read_bytes()) for name in DOCS + ['docs/project/roadmap.json']}
old = json.loads(git('show', IMPLEMENTATION + ':docs/project/roadmap.json'))
current = json.loads((ROOT / 'docs/project/roadmap.json').read_bytes())
expected = json.loads(json.dumps(old))
phase = next(row for row in expected['phases'] if row['id'] == 'P05')
assert phase['status'] == 'in_progress' and phase['evidence'] == []
phase['evidence'] = [{'acceptance_id': 'P05-A01', 'record': 'docs/project/evidence/p05-python/acceptance-binding.json'}]
assert current == expected, 'Unexpected roadmap delta'
actual_phase = next(row for row in current['phases'] if row['id'] == 'P05')
assert not any(row['acceptance_id'] in ('P05-A02', 'P05-A03') for row in actual_phase['evidence'])
assert next(row for row in current['phases'] if row['id'] == 'P01')['status'] == 'blocked'
acceptance_name = phase['evidence'][0]['record']
acceptance_raw = (ROOT / acceptance_name).read_bytes()
acceptance = json.loads(acceptance_raw)
assert acceptance['outcome'] == 'pass' and acceptance['evidence_level'] == 'simulated'
assert acceptance['source_revision'] == IMPLEMENTATION and acceptance['acceptance_ids'] == ['P05-A01']
assert acceptance['reviewer'].startswith('/root/w09_a2_binding_acceptance_review')
artifacts = []
for row in acceptance['artifacts']:
    p = ROOT / row['path']
    assert p.resolve().is_relative_to(ROOT) and p.is_file()
    body = p.read_bytes()
    assert sha(body) == row['sha256'], row['path']
    artifacts.append({'path': row['path'], 'sha256': sha(body), 'size_bytes': len(body)})
assert len(artifacts) == 57
spec = importlib.util.spec_from_file_location('p05_final_project_checker', ROOT / 'ci/project/check_project.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)
errors = []
checker._validate_report(acceptance, ROOT, acceptance_name, {'P05-A01'}, errors)
assert not errors, errors
links = []
from urllib.parse import unquote, urlsplit
for name in DOCS:
    content = (ROOT / name).read_text()
    if name == 'AGENTS.md':
        content = content.split('## 1. Documentation Map', 1)[0]
    for target in checker._links(content):
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc:
            continue
        decoded = unquote(parsed.path)
        linked = (ROOT / name).parent / decoded if decoded else ROOT / name
        linked = linked.resolve()
        assert linked.is_relative_to(ROOT) and linked.exists(), (name, target)
        if parsed.fragment and linked.suffix.lower() == '.md':
            assert unquote(parsed.fragment) in checker._anchors(linked.read_text()), (name, target)
        links.append({'document': name, 'target': target})
preserved = []
for name in ('LICENSE', 'docs/assets/img/vortex_framework_stack.svg', 'docs/review/code-review-policy.md',
             'docs/review/change-impact.yaml', 'ci/change_impact.py'):
    expected_bytes = git('show', BASE + ':' + name)
    assert expected_bytes == git('show', IMPLEMENTATION + ':' + name) == (ROOT / name).read_bytes(), name
    preserved.append({'path': name, 'sha256': sha(expected_bytes), 'size_bytes': len(expected_bytes)})
asset = 'docs/assets/img/vortex_framework_stack.svg'
extract = lambda body: [line for line in body.decode().splitlines() if asset in line]
assert extract(git('show', BASE + ':README.md')) == extract((ROOT / 'README.md').read_bytes())
assert checker._image_embedded((ROOT / 'README.md').read_text(), asset)
for name in ('docs/project/status.md', 'docs/project/backlog.md', 'docs/project/p05-entry-handoff.md'):
    body = (ROOT / name).read_text()
    assert 'P01-A03' in body and '267' in body and '283' in body
after = {name: sha((ROOT / name).read_bytes()) for name in before}
assert before == after, 'Checked documents changed during bounded verification'
result = {'schema_version': 1, 'outcome': 'pass', 'scope': 'Final source metadata and local links; no native execution, full-suite rerun, final Git-object classification or publication',
          'reviewer': '/root/w10_a4_final_governance_review', 'base_revision': BASE,
          'qualified_implementation': IMPLEMENTATION, 'observed_head': git('rev-parse', 'HEAD').decode().strip(),
          'roadmap_delta': 'Only P05-A01 evidence attached relative to the qualified implementation; P05 remains in_progress',
          'acceptance_sha256': sha(acceptance_raw), 'acceptance_artifacts_verified': artifacts,
          'acceptance_commands': len(acceptance['commands']), 'local_links_checked': len(links),
          'documents_before': before, 'documents_after': after, 'preserved': preserved,
          'protected_image_embedding_unchanged': True, 'all_other_phases_unchanged': True,
          'p05_a02_a03_unearned': True, 'p01_a03_and_dsp_finding_preserved': True,
          'limits': ['Final receipt/ledger files may be added after this check.',
                    'The exact final candidate commit must still be classified and the current remote master checked before a non-force update.',
                    'Existing passing native and complete-host-suite results remain tied to e1420fd; this run provides metadata/link checks only.']}
(OUT / 'metadata-links.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
print(json.dumps({'outcome': 'pass', 'documents': len(DOCS), 'links': len(links), 'acceptance_artifacts': len(artifacts), 'commands': len(acceptance['commands'])}, sort_keys=True))
