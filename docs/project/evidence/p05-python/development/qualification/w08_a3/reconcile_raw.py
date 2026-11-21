"""Independent bounded reconciliation: standard library only, no auditor imports."""
import base64
import csv
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess
import tarfile
import zipfile

repo = Path('/workspace/scratch/ba0248fde989/AI-GPU')
work = repo.parent / 'p05-work/w08_a3'
packet = repo.parent / 'p05-work/ci-e1420fd/simx-fp16/python'
report = json.loads((packet / 'report.json').read_text())
native = json.loads((packet / 'native/report.json').read_text())
manifest_raw = (packet / 'artifacts/bundle/manifest.json').read_bytes()
manifest = json.loads(manifest_raw)
revision = manifest['source_revision']
def sha(data): return hashlib.sha256(data).hexdigest()

source_stage = json.loads((packet / 'snapshots/package-source-stage.json').read_text())
stage_git_matches = []
for row in source_stage:
    body = subprocess.check_output(['git', '-C', str(repo), 'show', revision + ':' + row['path']])
    assert len(body) == row['size_bytes'] and sha(body) == row['sha256']
    stage_git_matches.append(row['path'])
assert len(stage_git_matches) == 24

sdist_row, wheel_row = report['packages']
assert sdist_row['path'].endswith('.tar.gz') and wheel_row['path'].endswith('.whl')
with tarfile.open(fileobj=io.BytesIO((packet / sdist_row['path']).read_bytes())) as stream:
    sdist = {str(PurePosixPath(row.name).relative_to('vortex_ai-0.1.0')): stream.extractfile(row).read()
             for row in stream.getmembers() if row.isfile()}
with zipfile.ZipFile(io.BytesIO((packet / wheel_row['path']).read_bytes())) as stream:
    wheel = {name: stream.read(name) for name in stream.namelist()}
installed = {str(path.relative_to(packet / 'artifacts/installed')): path.read_bytes()
             for path in (packet / 'artifacts/installed').rglob('*') if path.is_file()}
assert (len(sdist), len(wheel), len(installed)) == (32, 10, 13)
for row in source_stage:
    assert sha(sdist[row['path']]) == row['sha256'] and len(sdist[row['path']]) == row['size_bytes']
dist = 'vortex_ai-0.1.0.dist-info/'
record_counts = {}
for label, files in [('wheel', wheel), ('installed', installed)]:
    rows = list(csv.reader(io.StringIO(files[dist + 'RECORD'].decode())))
    assert {row[0] for row in rows} == set(files) and len(rows) == len(files)
    checked = 0
    for name, encoded, length in rows:
        if name == dist + 'RECORD':
            assert encoded == length == ''
        else:
            assert int(length) == len(files[name])
            assert encoded.startswith('sha256=')
            assert base64.urlsafe_b64decode(encoded[7:] + '==') == hashlib.sha256(files[name]).digest()
            checked += 1
    record_counts[label] = checked
for name, body in wheel.items():
    if name != dist + 'RECORD': assert body == installed[name]
assert not any(line.startswith('Requires-Dist:') for line in wheel[dist + 'METADATA'].decode().splitlines())
for name in ['manifest.json', 'source_inventory.json', 'p05_build_config.h']:
    assert sdist['python/p05_build/' + name] == (packet / 'artifacts/sdist-pin' / name).read_bytes()
assert sdist['python/p05_build/manifest.json'] == manifest_raw
extension = wheel['vortex_ai/_native.cpython-312-x86_64-linux-gnu.so']
compiled_pins = [sha(manifest_raw), manifest['binding_source_sha256'], manifest['qualification_id'], revision]
compiled_pins += [row['sha256'] for row in manifest['artifacts']]
assert all(value.encode() in extension for value in compiled_pins)
for row in manifest['artifacts']:
    body = (packet / 'artifacts/bundle' / row['path']).read_bytes()
    assert sha(body) == row['sha256'] and len(body) == row['size']

build_lines = (packet / 'logs/package-offline-wheel.log').read_text().splitlines()
compile_groups, links = {}, []
header_hash = sha(sdist['python/p05_build/p05_build_config.h'])
for line in build_lines:
    if not line.startswith('/usr/bin/g++ '): continue
    argv = shlex.split(line)
    if '-c' in argv:
        path = argv[argv.index('-c') + 1]
        match = re.fullmatch(r'(.*/p05-source-[^/]+)/(.*)', path)
        assert match and match[2] in stage_git_matches
        includes = [value[2:] for value in argv if value.startswith('-I')]
        assert includes[0] == match[1] + '/p05-config/' + header_hash
        assert '-std=c++17' in argv and '-fvisibility=hidden' in argv
        compile_groups.setdefault(match[1], []).append(match[2])
    elif '-shared' in argv: links.append(line)
expected_tus = {'python/native/module.cpp', 'python/native/runtime_loader.cpp',
                'sw/runtime/ai/contract.cpp', 'sw/runtime/ai/runtime.cpp',
                'sw/runtime/ai/mlp_host.cpp', 'sw/runtime/ai/mlp_runtime.cpp'}
assert len(compile_groups) == 2 and len(links) == 2
assert all(len(names) == 6 and set(names) == expected_tus for names in compile_groups.values())

commands = []
for prefix, data in [('', report), ('native/', native)]:
    assert data['budget']['max_rss_bytes'] == 4 * 1024**3
    assert data['budget']['max_log_bytes'] == 16 * 1024**2
    assert data['budget']['min_free_bytes'] == 15 * 1024**3
    assert data['resources_before']['available_memory_bytes'] >= 4 * 1024**3
    assert min(data['resources_before']['free_disk_bytes'].values()) >= 15 * 1024**3
    for command in data['commands']:
        log = (packet / prefix / command['log']).read_bytes()
        assert len(log) == command['log_size_bytes'] and sha(log) == command['log_sha256']
        assert command['exit_code'] == 0 and command['process_started'] and command['cleanup_complete']
        assert command['duration_seconds'] < command['timeout_seconds']
        assert command['peak_rss_bytes'] <= data['budget']['max_rss_bytes']
        commands.append({key: command[key] for key in ('id', 'duration_seconds', 'timeout_seconds', 'peak_rss_bytes')})
assert len(commands) == 27
rows = {row['id']: row for row in report['commands']}
assert 'VORTEX_AI_BUNDLE' in rows['package-bound-sdist']['environment']
assert 'VORTEX_AI_BUNDLE' not in rows['package-offline-wheel']['environment']
assert '--no-index' in rows['package-install-wheel']['argv'] and '--no-deps' in rows['package-install-wheel']['argv']
assert json.loads((packet / 'snapshots/installed-before.json').read_text()) == json.loads((packet / 'snapshots/installed-after.json').read_text())
result = {
    'outcome': 'pass', 'scope': 'independent read-only FP16 source/archive/command reconciliation; no native execution',
    'source_revision': revision, 'stage_sources_matching_git': stage_git_matches,
    'binding_input_count': len(manifest['binding_sources']), 'bundle_artifact_count': len(manifest['artifacts']),
    'sdist_files': len(sdist), 'wheel_files': len(wheel), 'installed_files': len(installed),
    'record_hash_entries_verified': record_counts, 'compiled_identity_strings_found': len(compiled_pins),
    'offline_extension_compile_groups': compile_groups, 'offline_extension_link_commands': len(links),
    'commands': commands, 'max_recorded_command_rss_bytes': max(row['peak_rss_bytes'] for row in commands),
    'package_extension_sha256': sha(extension), 'pin_header_sha256': header_hash,
    'limits': ['Identity consistency does not establish a reproducible transitive build or authenticated execution.',
               'Compiler/runtime/system dependencies beyond retained source bodies and package artifacts are identified, not reconstructed.'],
}
(work / 'raw-reconciliation.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
print(json.dumps({key: result[key] for key in ('outcome', 'binding_input_count', 'bundle_artifact_count', 'sdist_files', 'wheel_files', 'installed_files', 'record_hash_entries_verified', 'offline_extension_link_commands', 'max_recorded_command_rss_bytes')}))
