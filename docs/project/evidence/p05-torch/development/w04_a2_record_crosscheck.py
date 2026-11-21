from pathlib import Path
import hashlib, json, sys
root = Path(__file__).resolve().parent.parent / 'AI-GPU'
work = root.parent / 'p05-torch-work'
output = work / 'w04_a2-install'
venv = work / 'w04_a2-venv'
sys.dont_write_bytecode = True
sys.path.insert(0, str(root / 'ci/project'))
import p05_torch_execute as runner
before = json.loads((output / 'installed-before.json').read_text())
by_path = {row['path']: row for row in before}
probe = json.loads((output / 'framework-probe.json').read_text())
counts, visited = {}, set()
for name, value in probe['distributions'].items():
    assert set(value) == {'version', 'root', 'files'}
    assert value['root'] == str(venv / runner.SITE)
    assert value['files'] and len(value['files']) == len(set(value['files']))
    for item in value['files']:
        assert isinstance(item, str) and item and '\\' not in item and not any(ord(char) < 32 for char in item)
        target = (venv / runner.SITE / item).resolve(strict=True)
        assert target.is_relative_to(venv)
        relative = target.relative_to(venv).as_posix()
        assert relative in by_path, relative
        visited.add(relative)
    counts[name] = len(value['files'])
def identity(path):
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'size_bytes': path.stat().st_size}
original = identity(Path(sys.executable).resolve())
copied = identity(venv / 'bin/python')
assert (original['sha256'], original['size_bytes']) == (copied['sha256'], copied['size_bytes'])
report = {'scope': 'host-only-real-framework-provenance', 'outcome': 'pass', 'acceptance_claimed': False,
          'native_execution': 'not_run', 'distribution_record_files': counts, 'unique_distribution_files': len(visited),
          'original_interpreter': original, 'copied_interpreter': copied, 'loaded_helpers': runner.LOADED_HELPERS}
(output / 'record-crosscheck.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({'outcome': 'pass', 'distribution_count': len(counts), 'unique_files': len(visited),
                  'interpreter_copied_exactly': True}, sort_keys=True))
