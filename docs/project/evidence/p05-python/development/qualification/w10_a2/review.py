"""Bounded read-only documentation review; never imports project/native code."""
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tomllib
from urllib.parse import unquote, urlsplit

ROOT = Path('/workspace/scratch/ba0248fde989/AI-GPU')
WORK = ROOT.parent / 'p05-work/w10_a2'
REVISION = 'e1420fd550f716df33a2556057b7086a03032cbe'
TREE = '3a168adfd345ecb3c15dc02b2583dc832bef6049'
SOURCE_SHA = 'c4d476be1ab3dd73fbbe9b3027aac78db4a4890e536efea57319aecffcd6b19a'
EVIDENCE = ROOT / 'docs/project/evidence/p05-python'
DOCS = ['python/README.md', 'docs/project/p05-python-compatibility.md',
        'docs/designs/python_binding_v1.md', 'README.md', 'ROADMAP.md',
        'docs/project/status.md', 'docs/project/backlog.md',
        'docs/project/p05-entry-handoff.md', 'docs/project/p05-binding-audit.md']
EXPECTED_DOCS = {
    'docs/project/p05-python-compatibility.md': 'da5c9a9470985f4c100dc46e6dc5909540b04f141a09bcb78854f0b760fb69a0',
    'python/README.md': '3fc591670907a2ce97006222f0ca3931185c236c0c6f6528674899a160929529',
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path):
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def read_json(path):
    return json.loads(path.read_text())


commands = []


def command(argv):
    result = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True)
    commands.append({'argv': argv, 'exit_code': result.returncode})
    assert result.returncode == 0, (argv, result.stdout, result.stderr)
    return result.stdout


manifest_paths = [ROOT.parent / f'p05-work/ci-e1420fd/simx-{fmt}/python/artifacts/bundle/manifest.json'
                  for fmt in ('fp16', 'bf16')]
manifests = [read_json(p) for p in manifest_paths]
observation_paths = [p.parent.parent / 'installed-observations.json' for p in manifest_paths]
source_paths = [ROOT / entry['path'] for entry in manifests[0]['binding_sources']]
inputs = list(dict.fromkeys(
    [ROOT / p for p in DOCS] + [ROOT / 'docs/project/roadmap.json'] + source_paths
    + manifest_paths + observation_paths + [EVIDENCE / p for p in (
        'acceptance-binding.json', 'binding-acceptance-review.json',
        'reviews/full-provenance.json', 'reviews/full-numerics.json',
        'reviews/full-dispatch.json', 'relocated-replay.json')]))
before = {relative(p): digest(p) for p in inputs}
assert command(['git', 'rev-parse', REVISION + '^{tree}']).strip() == TREE
assert len(source_paths) == 22
source_checks = []
for manifest in manifests:
    assert manifest['source_revision'] == REVISION
    assert manifest['source_tree'] == TREE
    assert manifest['binding_source_sha256'] == SOURCE_SHA
    assert manifest['binding_sources'] == manifests[0]['binding_sources']
for item in manifests[0]['binding_sources']:
    data = (ROOT / item['path']).read_bytes()
    assert len(data) == item['size']
    assert hashlib.sha256(data).hexdigest() == item['sha256']
    committed = subprocess.run(['git', 'show', REVISION + ':' + item['path']], cwd=ROOT,
                               capture_output=True, check=True).stdout
    assert data == committed
    source_checks.append({'path': item['path'], 'sha256': item['sha256'],
                          'size': len(data), 'same_as_qualified_commit': True})
assert all(before[p] == sha for p, sha in EXPECTED_DOCS.items())

api = ast.parse((ROOT / 'python/vortex_ai/_api.py').read_text())
constants = {}
for node in api.body:
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        try:
            constants[node.targets[0].id] = ast.literal_eval(node.value)
        except (ValueError, TypeError):
            pass
assert constants['BINDING_API'] == 1
assert constants['_SHAPES'] == ((8, 4, 8), (8, 4, 16), (16, 8, 16))
assert constants['_DEFAULT_TIMEOUT_NS'] == 100_000_000
assert constants['_MAX_TIMEOUT_NS'] == 1_000_000_000
classes = {node.name: node for node in api.body if isinstance(node, ast.ClassDef)}
expected_methods = {
    'Session': {'open', 'submit', 'model', 'pending_operations', 'close'},
    'Operation': {'wait', 'close', 'output_bytes'},
    'ModelOperation': {'advance', 'close', 'output_bytes', 'record'},
}
api_signatures = {}
for name, methods in expected_methods.items():
    found = {node.name: ast.unparse(node.args) for node in classes[name].body if isinstance(node, ast.FunctionDef)}
    assert methods <= set(found)
    api_signatures[name] = {method: found[method] for method in sorted(methods)}
project = tomllib.loads((ROOT / 'pyproject.toml').read_text())
assert project['project']['requires-python'] == '>=3.12,<3.13'
assert project['project']['dependencies'] == []
assert set(project['build-system']['requires']) == {'setuptools==84.2.1', 'wheel==0.48.0', 'packaging==26.3'}

libraries = {'libramulator.so', 'libramulator-vortex.so', 'libvortex.so', 'libsimx.so', 'libvortex-simx.so'}
installed = []
signatures = set()
model_cases = set()
for path in observation_paths:
    observed = read_json(path)
    binding = observed['binding']
    install = observed['installation']
    assert observed['outcome'] == 'pass'
    assert binding['source_revision'] == REVISION and binding['source_sha256'] == SOURCE_SHA
    assert install['distribution_version'] == '0.1.0'
    assert install['python_implementation'] == 'CPython' and install['python_version'] == [3, 12, 14]
    assert install['build_info']['binding_api'] == 1 and install['build_info']['source_sha256'] == SOURCE_SHA
    assert '/site-packages/' in install['package_file']
    assert '/site-packages/' in install['extension_file']
    assert {Path(p).name for p in install['runtime_libraries']} == libraries
    for item in observed['matmuls']:
        trace = item['trace']
        signatures.add((trace['input_dtype'], trace['m'], trace['n'], trace['k']))
        for key in ('status', 'close_status'):
            assert item[key] == {'validation': 'success', 'primary': 0, 'cleanup': 0, 'complete': True}
    model_cases.update(item['case_id'] for item in observed['models'])
    installed.append({'format': binding['format'], 'binding': binding, 'installation': install,
                      'counts': observed['counts'], 'source': str(path)})
assert signatures == {(fmt, *shape) for fmt in ('fp16', 'bf16') for shape in constants['_SHAPES']}
assert len(model_cases) == 10
assert sum(p['counts']['total_launches'] for p in installed) == 72
provenance = read_json(EVIDENCE / 'reviews/full-provenance.json')
assert provenance['outcome'] == 'pass' and provenance['full_matrix'] is True
hosted = []
for packet in provenance['packets']:
    versions = {name: value['version'] for name, value in packet['native_tool_versions'].items()}
    assert versions == {'clang': '20.1.8', 'g++': '11.4.0', 'make': '4.3'}
    assert packet['package_versions'] == {'packaging': '26.3', 'setuptools': '84.2.1', 'wheel': '0.48.0'}
    extension = next(elf for elf in packet['elf_identities'] if '/_native.cpython-' in elf['path'])
    simx = next(elf for elf in packet['elf_identities'] if elf['path'].endswith('/libsimx.so'))
    assert extension['runpath'] == ['/opt/hostedtoolcache/Python/3.12.14/x64/lib']
    assert simx['runpath'] and 'third_party/ramulator' in simx['runpath'][0]
    hosted.append({'format': packet['format'], 'native_versions': versions,
                   'package_versions': packet['package_versions'],
                   'extension_runpath': extension['runpath'], 'simx_runpath': simx['runpath']})
acceptance = read_json(EVIDENCE / 'acceptance-binding.json')
assert acceptance['source_revision'] == REVISION and acceptance['outcome'] == 'pass'
assert acceptance['acceptance_ids'] == ['P05-A01'] and acceptance['evidence_level'] == 'simulated'
phase = next(p for p in read_json(ROOT / 'docs/project/roadmap.json')['phases'] if p['id'] == 'P05')
assert phase['status'] == 'in_progress'
assert phase['evidence'] == [{'acceptance_id': 'P05-A01', 'record': 'docs/project/evidence/p05-python/acceptance-binding.json'}]

syntax = []
for name in DOCS[:2]:
    for index, match in enumerate(re.finditer(r'^```([^\n]*)\n(.*?)^```\s*$', (ROOT / name).read_text(), re.M | re.S), 1):
        language, code = match.groups()
        target = WORK / f'{Path(name).stem}-{index}.{language}'
        target.write_text(code)
        if language == 'sh':
            command(['bash', '-n', str(target)])
        elif language == 'python':
            ast.parse(code)
        else:
            raise AssertionError((name, language))
        syntax.append({'document': name, 'block': index, 'language': language, 'outcome': 'pass', 'executed': False})
assert len(syntax) == 6 and sum(p['language'] == 'sh' for p in syntax) == 5
links = []
for name in DOCS:
    for match in re.finditer(r'\[[^\]\n]+\]\(([^)\n]+)\)', (ROOT / name).read_text()):
        target = match.group(1).split(' "', 1)[0].strip('<>')
        parsed = urlsplit(target)
        if parsed.scheme or target.startswith('//') or not parsed.path:
            continue
        path = (ROOT / name).parent / unquote(parsed.path)
        assert path.exists(), (name, target)
        links.append({'document': name, 'target': target})
replay_doc = EVIDENCE / 'reviews/README.md'
assert '## Relocated data replay' in replay_doc.read_text()
after = {relative(p): digest(p) for p in inputs}
assert before == after
checks = {
    'outcome': 'pass', 'implementation_revision': REVISION, 'implementation_tree': TREE,
    'source_files': source_checks, 'binding_source_sha256_from_both_manifests': SOURCE_SHA,
    'api_signatures': api_signatures, 'supported_signatures': sorted(signatures),
    'frozen_model_cases_observed': sorted(model_cases), 'installed_observations': installed,
    'hosted_provenance': hosted, 'syntax_checks': syntax, 'local_links': links,
    'local_links_scope': 'Inline Markdown local target existence across nine documents; relocated-data-replay heading checked separately. Other fragments and external URLs were not crawled.',
    'acceptance': {'ids': acceptance['acceptance_ids'], 'level': acceptance['evidence_level'], 'phase_status': phase['status']},
    'stable_input_sha256': before, 'read_only_inputs_unchanged': True, 'commands': commands,
    'git_source_comparisons': 22,
    'scope_limit': 'Read-only source/metadata inspection and bash -n / ast.parse only; no project import, native execution, package build, tests or auditor replay.'
}
(WORK / 'checks.json').write_text(json.dumps(checks, indent=2, sort_keys=True) + '\n')
print(json.dumps({'outcome': 'pass', 'stable_inputs': len(inputs), 'source_files': len(source_checks),
                  'qualified_signatures': len(signatures), 'frozen_model_cases': len(model_cases),
                  'syntax_blocks': len(syntax), 'local_links': len(links), 'checks_sha256': digest(WORK / 'checks.json')}, sort_keys=True))
