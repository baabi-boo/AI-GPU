"""Read-only invariants for the seven owned handoff files."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path('/workspace/scratch/ba0248fde989/AI-GPU')
HERE = ROOT.parent / 'p05-work/w09_a3'
before = json.loads((HERE / 'before.json').read_text())
paths = list(before['files'])

def digest(body):
    return hashlib.sha256(body).hexdigest()

def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)

assert git('rev-parse', 'HEAD').decode().strip() == before['head']
for path in paths:
    assert digest(git('show', before['head'] + ':' + path)) == before['files'][path], path
old = json.loads(git('show', before['head'] + ':docs/project/roadmap.json'))
new = json.loads((ROOT / 'docs/project/roadmap.json').read_bytes())
expected = json.loads(json.dumps(old))
p05 = next(row for row in expected['phases'] if row['id'] == 'P05')
p05['evidence'] = [{'acceptance_id': 'P05-A01', 'record': 'docs/project/evidence/p05-python/acceptance-binding.json'}]
assert new == expected
assert p05['status'] == 'in_progress'
assert next(row for row in new['phases'] if row['id'] == 'P01')['status'] == 'blocked'
assert all(row['status'] == 'not_started' for row in new['phases'] if row['id'] in ('P06', 'P07', 'P08', 'P09', 'P10', 'P11'))
assert digest((ROOT / 'docs/assets/img/vortex_framework_stack.svg').read_bytes()) == before['svg']
embed = [line for line in (ROOT / 'README.md').read_text().splitlines() if 'vortex_framework_stack.svg' in line]
assert embed == before['embed_lines']
links = []
for path in paths:
    if not path.endswith('.md'):
        continue
    text = (ROOT / path).read_text()
    for destination in re.findall(r'\[[^\]]*\]\(([^)]+)\)', text):
        if re.match(r'^[a-z]+:', destination, re.I) or destination.startswith('#'):
            continue
        name = destination.split('#', 1)[0]
        if not name:
            continue
        target = (ROOT / path).parent / name
        assert target.resolve().is_relative_to(ROOT) and target.is_file(), (path, destination)
        links.append({'document': path, 'target': target.resolve().relative_to(ROOT).as_posix()})
    assert 'P05 acceptance remains unearned' not in text
    assert not any(line.rstrip() != line for line in text.splitlines())

manifest = json.loads((ROOT.parent / 'p05-work/ci-e1420fd/simx-fp16/python/artifacts/bundle/manifest.json').read_text())
for row in manifest['binding_sources']:
    assert digest((ROOT / row['path']).read_bytes()) == row['sha256'], row['path']
acceptance = json.loads((ROOT / p05['evidence'][0]['record']).read_text())
for row in acceptance['artifacts']:
    assert digest((ROOT / row['path']).read_bytes()) == row['sha256'], row['path']
diff = subprocess.run(['git', 'diff', '--check', '--', *paths], cwd=ROOT, capture_output=True, text=True)
assert diff.returncode == 0, diff.stdout + diff.stderr
report = {'outcome': 'pass', 'head': before['head'], 'owned_files': len(paths),
          'roadmap_delta': 'P05-A01 evidence reference only; all phase states and other fields unchanged',
          'protected_svg_and_embed_unchanged': True, 'binding_sources_unchanged': len(manifest['binding_sources']),
          'acceptance_artifact_hashes_verified': len(acceptance['artifacts']), 'local_links_verified': len(links),
          'links': links, 'whitespace_check_exit': diff.returncode,
          'files': {path: digest((ROOT / path).read_bytes()) for path in paths}}
(HERE / 'checks.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({k:v for k,v in report.items() if k not in ('files','links')}, sort_keys=True))
