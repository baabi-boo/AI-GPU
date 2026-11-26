"""Source-scoped discovery, preservation, and metadata checks; no test execution."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path('/tmp/ai-gpu-b4f42b8a9d4b/repo')
OUT = ROOT.parent / 'a047-validation'
BASE = '30b2e8ca69fba47646392c0cf6650cbb75155843'
EXPECTED_HEAD = '596cbf9c7a67b05d2a77df80157d4da9fe2ec38b'
MINIMUM = 1024 ** 3

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def read(rel):
    return (ROOT / rel).read_bytes()

def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)

def base_bytes(rel):
    return git('show', BASE + ':' + rel)

def identity(raw):
    return {'sha256': sha(raw), 'size_bytes': len(raw)}

def write(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')

def bytecode():
    result = {}
    for directory, dirs, files in os.walk(ROOT):
        dirs[:] = [name for name in dirs if name != '.git']
        path = Path(directory)
        if path.name == '__pycache__':
            result[str(path.relative_to(ROOT)) + '/'] = 'directory'
        for name in files:
            if name.endswith(('.pyc', '.pyo')):
                child = path / name
                result[str(child.relative_to(ROOT))] = identity(child.read_bytes())
    return result

started = datetime.now(timezone.utc).isoformat()
head_before = git('rev-parse', 'HEAD').decode().strip()
assert head_before == EXPECTED_HEAD
assert shutil.disk_usage('/tmp').free >= MINIMUM
reviewed = {
    'ci/project/governance_replay_archive.py': '79c75dc2e70c7d848d17527f669a1addf5c734941cff4314f8d591c32c9454b5',
    'ci/project/test_governance_directory_ownership.py': '06670039069e2a5c09ec292ebca08a1624d5ed5c75e82219d26ee8778db8b694',
}
assert all(sha(read(path)) == expected for path, expected in reviewed.items())
environment_before = dict(os.environ)
parent_cwd_before = os.getcwd()
bytecode_before = bytecode()
free_samples = [shutil.disk_usage('/tmp').free]
env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONPATH='ci/project')
commands = []
for command, log in [
    ([sys.executable, '-B', str(OUT / 'canonical-discovery-runner.py')], 'canonical-discovery.log'),
    ([sys.executable, '-B', 'ci/project/check_project.py'], 'check-project.log'),
    ([sys.executable, '-B', 'ci/project/check_baseline_packets.py'], 'check-baseline-packets.log'),
    (['git', 'diff', '--check'], 'git-diff-check.log'),
]:
    before = time.monotonic()
    with (OUT / log).open('wb') as stream:
        result = subprocess.run(command, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=90)
    free_samples.append(shutil.disk_usage('/tmp').free)
    item = {'command': command, 'log': log, 'exit_code': result.returncode,
            'elapsed_seconds': time.monotonic() - before,
            'log_identity': identity((OUT / log).read_bytes())}
    commands.append(item)
    print(json.dumps({'log': log, 'exit_code': result.returncode}), flush=True)

proof_paths = ['ci/project/p06_qualified_warm_proof.json', 'ci/project/p06_counter_qualification_proof.json']
proofs = {path: {'current': identity(read(path)), 'base': identity(base_bytes(path)),
                'unchanged_from_base': read(path) == base_bytes(path)} for path in proof_paths}
qualified = json.loads(read(proof_paths[0]))
counter = json.loads(read(proof_paths[1]))
base_counter = json.loads(base_bytes(proof_paths[1]))
measurements = []
for row in qualified['measurement_sources']:
    actual = identity(read(row['path']))
    measurements.append({'path': row['path'], 'expected': {'sha256': row['sha256'], 'size_bytes': row['size_bytes']},
                         'actual': actual, 'matches_frozen': actual == {'sha256': row['sha256'], 'size_bytes': row['size_bytes']}})
roadmap_path = 'docs/project/roadmap.json'
roadmap = json.loads(base_bytes(roadmap_path))
active = sorted({row['record'] for phase in roadmap['phases'] for row in phase.get('evidence', [])})
found = git('grep', '-l', '-z', '--fixed-strings', '"acceptance_ids"', BASE, '--', 'docs/project/evidence/*.json').decode().split('\0')
acceptances = set(active)
for hit in filter(None, found):
    rel = hit.split(':', 1)[1]
    try:
        value = json.loads(base_bytes(rel))
    except (ValueError, UnicodeError):
        continue
    if isinstance(value, dict) and 'acceptance_ids' in value:
        acceptances.add(rel)
base_paths = git('ls-tree', '-rz', '--name-only', BASE).decode().split('\0')
goldens = sorted(path for path in base_paths if path.startswith('ci/baselines/'))
svg = 'docs/assets/img/vortex_framework_stack.svg'
embed = '<img src="' + svg + '" alt="Vortex framework stack" width="100%">'
protected_paths = sorted(acceptances | set(goldens) | {svg, roadmap_path})
protected = {path: {'base': identity(base_bytes(path)), 'current': identity(read(path)),
                    'unchanged_from_base': read(path) == base_bytes(path)} for path in protected_paths}
dependencies = counter['dependency_sources']
preservation_checks = {
    'measurement_count_69_unique': len(measurements) == len({row['path'] for row in measurements}) == 69,
    'all_measurement_sizes_and_hashes_match': all(row['matches_frozen'] for row in measurements),
    'both_proof_bytes_unchanged': all(row['unchanged_from_base'] for row in proofs.values()),
    'dependency_descriptors_21_unique': len(dependencies) == len({row['path'] for row in dependencies}) == 21,
    'dependency_descriptors_unchanged': dependencies == base_counter['dependency_sources'],
    'dependency_revision_and_graph_unchanged': all(counter[key] == base_counter[key] for key in ('dependency_revision', 'dependency_selected_graph')),
    'active_acceptances_18': len(active) == 18,
    'original_acceptances_unchanged': all(protected[path]['unchanged_from_base'] for path in acceptances),
    'baseline_goldens_25': len(goldens) == 25,
    'baseline_goldens_unchanged': all(protected[path]['unchanged_from_base'] for path in goldens),
    'protected_svg_matches_pin': sha(read(svg)) == 'db123c71024f85f379c2504c7465c03ee9df8959a5d17fc3d3e94a94a1cd3aa4',
    'protected_svg_bytes_unchanged': protected[svg]['unchanged_from_base'],
    'readme_exact_embed_preserved': read('README.md').decode().count(embed) == base_bytes('README.md').decode().count(embed) == 1,
    'roadmap_unchanged': protected[roadmap_path]['unchanged_from_base'],
}
preservation = {'base_revision': BASE, 'proofs': proofs, 'measurements': measurements,
                'dependency_records_count': len(dependencies), 'dependency_records': dependencies,
                'active_acceptance_paths': active, 'original_acceptance_paths': sorted(acceptances),
                'baseline_golden_paths': goldens, 'protected_identities': protected,
                'checks': preservation_checks, 'outcome': 'pass' if all(preservation_checks.values()) else 'fail'}
write('preservation.json', preservation)
source_after = {str(path.relative_to(ROOT)): identity(path.read_bytes()) for path in sorted((ROOT / 'ci/project').glob('*.py'))}
write('source-after.json', source_after)
source_before = json.loads((OUT / 'source-before.json').read_bytes())
bytecode_after = bytecode()
write('bytecode.json', {'before': bytecode_before, 'after': bytecode_after, 'unchanged': bytecode_before == bytecode_after})
discovery = json.loads((OUT / 'canonical-discovery.json').read_bytes())
head_after = git('rev-parse', 'HEAD').decode().strip()
checks = {
    'commands_exit_zero': all(row['exit_code'] == 0 for row in commands),
    'discovery_pass': discovery['outcome'] == 'pass',
    'preservation_pass': preservation['outcome'] == 'pass',
    'sources_unchanged_through_metadata': source_before == source_after,
    'reviewed_source_hashes_unchanged': all(sha(read(path)) == expected for path, expected in reviewed.items()),
    'bytecode_unchanged': bytecode_before == bytecode_after,
    'parent_environment_unchanged': environment_before == dict(os.environ),
    'parent_cwd_unchanged': parent_cwd_before == os.getcwd(),
    'parent_has_no_repository_imports': not any(getattr(module, '__file__', None) and str(module.__file__).startswith(str(ROOT) + '/') for module in sys.modules.values()),
    'head_stable': head_before == head_after,
    'tmp_reserve_preserved': min(free_samples) >= MINIMUM,
}
receipt = {'schema_version': 1, 'assignment': 'a047',
           'scope': 'One isolated canonical discovery-only comparison; frozen-identity preservation and metadata checks only. No test bodies, full governance, builds or native execution.',
           'started_utc': started, 'ended_utc': datetime.now(timezone.utc).isoformat(),
           'head_before': head_before, 'head_after': head_after, 'commands': commands,
           'python_version': sys.version, 'reviewed_source_sha256': reviewed,
           'discovery': {key: discovery[key] for key in ('count', 'unique_count', 'ids_sha256', 'added_ids', 'removed_ids', 'outcome')},
           'preservation': {'measurement_count': len(measurements), 'dependency_records_count': len(dependencies),
                            'active_acceptance_count': len(active), 'original_acceptance_count': len(acceptances),
                            'baseline_golden_count': len(goldens), 'outcome': preservation['outcome']},
           'source_snapshot_count': len(source_before), 'source_changes': [path for path in sorted(set(source_before) | set(source_after)) if source_before.get(path) != source_after.get(path)],
           'bytecode_entries_before': len(bytecode_before), 'bytecode_entries_after': len(bytecode_after),
           'tmp_free_minimum_observed_bytes': min(free_samples), 'tmp_reserve_bytes': MINIMUM,
           'checks': checks, 'outcome': 'pass' if all(checks.values()) else 'fail'}
write('receipt.json', receipt)
artifacts = {path.name: identity(path.read_bytes()) for path in sorted(OUT.iterdir()) if path.is_file() and path.name != 'artifact-hashes.json'}
write('artifact-hashes.json', artifacts)
print(json.dumps({'outcome': receipt['outcome'], 'count': discovery['count'], 'additions': len(discovery['added_ids']), 'removals': len(discovery['removed_ids']), 'original_acceptances': len(acceptances), 'source_count': len(source_before), 'failed_checks': [key for key, value in checks.items() if not value]}), flush=True)
raise SystemExit(0 if receipt['outcome'] == 'pass' else 1)
