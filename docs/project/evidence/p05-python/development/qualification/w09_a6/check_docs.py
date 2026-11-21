import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path('/workspace/scratch/ba0248fde989/AI-GPU')
OUT = ROOT.parent / 'p05-work/w09_a6'
OWNED = ['docs/project/p05-python-compatibility.md', 'python/README.md']

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def blocks(text):
    return re.findall(r'^```([^\n]*)\n(.*?)^```\s*$', text, flags=re.M | re.S)

links, shell, python, unchanged_examples = [], [], [], []
for name in OWNED:
    path = ROOT / name
    text = path.read_text()
    old = (OUT / (path.name + '.before')).read_text()
    assert blocks(text) == blocks(old), 'A usage block changed: ' + name
    unchanged_examples.append({'path': name, 'code_blocks': len(blocks(text))})
    for target in re.findall(r'\[[^\]]*\]\(([^\s)]+)\)', text):
        if target.startswith(('https://', 'http://')):
            continue
        relative, _, anchor = target.partition('#')
        linked = (path.parent / relative).resolve(strict=True)
        assert linked.is_relative_to(ROOT) and linked.is_file(), target
        if anchor:
            headings = re.findall(r'^#+\s+(.*)', linked.read_text(), flags=re.M)
            slugs = [re.sub(r'[^\w\s-]', '', h).lower().replace(' ', '-') for h in headings]
            assert anchor in slugs, target
        links.append({'document': name, 'target': target})
    for index, (language, body) in enumerate(blocks(text)):
        if language == 'python':
            ast.parse(body)
            python.append({'document': name, 'block': index, 'syntax': 'pass'})
        elif language == 'sh':
            p = OUT / (path.parent.name + '-' + path.name + '-block-' + str(index) + '.sh')
            p.write_text(body)
            process = subprocess.run(['bash', '-n', str(p)], capture_output=True, text=True)
            assert process.returncode == 0, process.stderr
            shell.append({'command': ['bash', '-n', str(p)], 'exit_code': process.returncode})

acceptance = json.loads((ROOT / 'docs/project/evidence/p05-python/acceptance-binding.json').read_text())
assert acceptance['outcome'] == 'pass' and acceptance['acceptance_ids'] == ['P05-A01']
assert acceptance['source_revision'] == 'e1420fd550f716df33a2556057b7086a03032cbe'
pins = json.loads((OUT / 'acceptance-pins-before.json').read_text())
assert all(digest(ROOT / name) == value for name, value in pins.items())
protected = json.loads((OUT / 'protected-inputs.json').read_text())
assert all(digest(ROOT / name) == value for name, value in protected.items())
numeric = json.loads((ROOT / 'docs/project/evidence/p05-python/reviews/full-numerics.json').read_text())
dispatch = json.loads((ROOT / 'docs/project/evidence/p05-python/reviews/full-dispatch.json').read_text())
assert numeric['total_launches'] == dispatch['counts']['combined']['total_launches'] == 144
assert numeric['event_profile_pairs'] == dispatch['counts']['combined']['event_profile_pairs'] == 660
assert numeric['counts']['python']['event_profile_pairs'] == 360
assert numeric['counts']['native']['event_profile_pairs'] == 300
assert dispatch['counts']['combined']['unprofiled_launches'] == 12
api = ast.parse((ROOT / 'python/vortex_ai/_api.py').read_text())
classes = {node.name: node for node in api.body if isinstance(node, ast.ClassDef)}
for cls, names in {'Session': ['open', 'submit', 'model', 'close', 'pending_operations'],
                   'Operation': ['wait', 'close'], 'ModelOperation': ['advance', 'close', 'record']}.items():
    methods = {node.name for node in classes[cls].body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert set(names) <= methods
tree = subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], cwd=ROOT, text=True).strip()
assert tree == '3a168adfd345ecb3c15dc02b2583dc832bef6049'
result = {'outcome': 'pass', 'scope': 'documentation syntax, references, facts and unchanged implementation pins; no package or native execution',
          'source_revision': acceptance['source_revision'], 'source_tree': tree,
          'unchanged_usage_examples': unchanged_examples, 'shell_syntax': shell, 'python_syntax': python,
          'local_links': links, 'acceptance_artifacts_unchanged': len(pins),
          'protected_binding_inputs_and_contract_unchanged': len(protected),
          'counts': {'launches': 144, 'event_profile_pairs': 660, 'unprofiled_native_standalone': 12},
          'documents': {name: {'sha256': digest(ROOT / name), 'size_bytes': (ROOT / name).stat().st_size} for name in OWNED}}
(OUT / 'checks.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({'outcome': 'pass', 'links': len(links), 'shell_blocks': len(shell), 'python_blocks': len(python),
                  'acceptance_artifacts_unchanged': len(pins), 'protected_inputs_unchanged': len(protected)}, sort_keys=True))
