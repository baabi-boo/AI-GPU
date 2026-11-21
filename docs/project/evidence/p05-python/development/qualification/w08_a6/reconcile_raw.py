"""Independent BF16 raw-data reconciliation; imports no project modules."""
import base64
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import shlex
import subprocess
import tarfile
import zipfile

REPO = Path('/workspace/scratch/ba0248fde989/AI-GPU')
WORK = REPO.parent / 'p05-work/w08_a6'
PACKET = REPO.parent / 'p05-work/ci-e1420fd/simx-bf16/python'
REVISION = 'e1420fd550f716df33a2556057b7086a03032cbe'

def sha(body):
    return hashlib.sha256(body).hexdigest()

def document(name):
    return json.loads((PACKET / name).read_bytes())

def check_inventory(data, entries):
    assert set(data) == {entry['path'] for entry in entries}
    for entry in entries:
        body = data[entry['path']]
        assert sha(body) == entry['sha256'] and len(body) == entry.get('size_bytes', entry.get('size'))

def verify_record(files):
    record = next(name for name in files if name.endswith('.dist-info/RECORD'))
    rows = list(csv.reader(io.StringIO(files[record].decode())))
    assert len(rows) == len(files) and {row[0] for row in rows} == set(files)
    for name, encoded_hash, size in rows:
        if name == record:
            assert encoded_hash == size == ''
        else:
            expected = 'sha256=' + base64.urlsafe_b64encode(hashlib.sha256(files[name]).digest()).decode().rstrip('=')
            assert encoded_hash == expected and int(size) == len(files[name])
    return len(rows)

report = document('report.json')
native = document('native/report.json')
manifest_raw = (PACKET / 'artifacts/bundle/manifest.json').read_bytes()
manifest = json.loads(manifest_raw)
stage = document('snapshots/package-source-stage.json')
assert len(stage) == 24
for row in stage:
    blob = subprocess.check_output(['git', '-C', str(REPO), 'show', REVISION + ':' + row['path']])
    assert len(blob) == row['size_bytes'] and sha(blob) == row['sha256']

package_files = {}
for row in report['packages']:
    raw = (PACKET / row['path']).read_bytes()
    assert sha(raw) == row['sha256'] and len(raw) == row['size_bytes']
    package_files[row['path']] = raw
sdist_name = next(name for name in package_files if name.endswith('.tar.gz'))
with tarfile.open(fileobj=io.BytesIO(package_files[sdist_name])) as stream:
    sdist = {item.name.removeprefix('vortex_ai-0.1.0/'): stream.extractfile(item).read()
             for item in stream.getmembers() if item.isfile()}
assert len(sdist) == 32
for row in stage:
    assert sha(sdist[row['path']]) == row['sha256'] and len(sdist[row['path']]) == row['size_bytes']
header = (PACKET / 'artifacts/sdist-pin/p05_build_config.h').read_bytes()
assert sdist['python/p05_build/p05_build_config.h'] == header
assert sdist['python/p05_build/manifest.json'] == manifest_raw
assert json.loads(sdist['python/p05_build/source_inventory.json']) == manifest['binding_sources']
pins = dict(re.findall(r'inline constexpr char (\w+)\[\] = "([^"]*)";', header.decode()))
expected_pins = {'bundle_sha256': sha(manifest_raw), 'source_sha256': manifest['binding_source_sha256'],
                 'backend': 'simx', 'format': 'bf16', 'qualification_id': manifest['qualification_id'],
                 'source_revision': REVISION}
assert pins == expected_pins
artifact_tuples = re.findall(r'\{"([^"]+)", "([^"]+)", "([0-9a-f]+)", ([0-9]+)ULL\}', header.decode())
assert len(artifact_tuples) == len(manifest['artifacts']) == 6
assert set(artifact_tuples) == {(r['role'], r['path'], r['sha256'], str(r['size'])) for r in manifest['artifacts']}
for row in manifest['artifacts']:
    raw = (PACKET / 'artifacts/bundle' / row['path']).read_bytes()
    assert sha(raw) == row['sha256'] and len(raw) == row['size']

wheel_name = next(name for name in package_files if name.endswith('.whl'))
assert '-1' + pins['bundle_sha256'] + '-cp312-cp312-linux_x86_64.whl' in wheel_name
with zipfile.ZipFile(io.BytesIO(package_files[wheel_name])) as stream:
    wheel = {name: stream.read(name) for name in stream.namelist()}
assert len(wheel) == 10
check_inventory(wheel, document('snapshots/wheel-inventory.json'))
wheel_record_rows = verify_record(wheel)
installed = {p.relative_to(PACKET / 'artifacts/installed').as_posix(): p.read_bytes()
             for p in (PACKET / 'artifacts/installed').rglob('*') if p.is_file()}
assert len(installed) == 13
before = document('snapshots/installed-before.json')
assert before == document('snapshots/installed-after.json')
check_inventory(installed, before)
installed_record_rows = verify_record(installed)
for name, body in wheel.items():
    if not name.endswith('/RECORD'):
        assert installed[name] == body
extension_name = next(name for name in wheel if name.endswith('.so'))
extension = installed[extension_name]
for key in ('bundle_sha256', 'source_sha256', 'qualification_id', 'source_revision'):
    assert pins[key].encode() + b'\0' in extension
assert 'Requires-Dist:' not in wheel['vortex_ai-0.1.0.dist-info/METADATA'].decode()
installation = document('artifacts/installed-observations.json')['installation']
assert installation['python_implementation'] == 'CPython' and installation['python_version'] == [3, 12, 14]
assert installation['distribution_version'] == '0.1.0'
assert installation['build_info'] == {'binding_api': 1, 'bundle_sha256': pins['bundle_sha256'], 'source_sha256': pins['source_sha256']}
prefix = report['paths']['work'] + '/venv'
assert installation['prefix'] == prefix and installation['prefix'] != installation['base_prefix']
assert installation['package_file'].startswith(prefix + '/lib/python3.12/site-packages/')
assert installation['extension_file'] == prefix + '/lib/python3.12/site-packages/' + extension_name
assert set(installation['runtime_libraries']) == {report['paths']['output'] + '/artifacts/bundle/' + r['path']
                                                for r in manifest['artifacts'] if r['role'] != 'module'}

commands = []
for root, packet, package in [(PACKET, report, True), (PACKET / 'native', native, False)]:
    budget = {'jobs': 2, 'max_log_bytes': 16 * 1024**2, 'max_rss_bytes': 4 * 1024**3, 'min_free_bytes': 15 * 1024**3}
    if package:
        budget['package_jobs'] = 1
    assert packet['budget'] == budget
    assert packet['resources_before']['available_memory_bytes'] >= 4 * 1024**3
    assert min(packet['resources_before']['free_disk_bytes'].values()) >= 15 * 1024**3
    tools = json.loads((root / packet['tools_before']['path']).read_bytes())
    path_entries = ([packet['paths']['host_bin']] if packet['paths']['host_bin'] else [])
    path_entries += [str(Path(tools['python3']['path']).parent), '/usr/bin', '/bin']
    expected_path = ':'.join(dict.fromkeys(path_entries))
    for command in packet['commands']:
        assert command['process_started'] and command['cleanup_complete'] and command['exit_code'] == 0
        assert command['reason'] is None and command['outcome'] == 'pass'
        assert 0 < command['duration_seconds'] <= command['timeout_seconds'] + 10
        assert command['peak_rss_bytes'] <= budget['max_rss_bytes']
        body = (root / command['log']).read_bytes()
        assert sha(body) == command['log_sha256'] and len(body) == command['log_size_bytes'] <= budget['max_log_bytes']
        assert command['environment']['PATH'] == expected_path
        commands.append({'id': command['id'], 'timeout_seconds': command['timeout_seconds'],
                         'duration_seconds': command['duration_seconds'], 'peak_rss_bytes': command['peak_rss_bytes']})
assert len(commands) == 27
outer = {row['id']: row for row in report['commands']}
assert outer['package-create-venv']['timeout_seconds'] == outer['package-install-wheel']['timeout_seconds'] == 120
assert outer['package-tools-before']['timeout_seconds'] == outer['package-tools-after']['timeout_seconds'] == 60
assert outer['installed-matrix']['timeout_seconds'] == 16 * 180 + 60
assert outer['package-offline-wheel']['environment'].get('VORTEX_AI_BUNDLE') is None
assert '--no-index' in outer['package-install-wheel']['argv'] and '--no-deps' in outer['package-install-wheel']['argv']
records = report['matmul_compiler_records'] + native['variants'][0]['compiler_records']
assert [r['role'] for r in records] == ['runtime', 'backend_cpp', 'kernel', 'host'] * 2
for row in records:
    configuration = row['configuration']
    assert configuration['VX_CFG_XLEN'] == '64'
    if row['role'] in ('kernel', 'host'):
        assert configuration['ITYPE'] == 'bf16' and configuration['OTYPE'] == 'fp32' and configuration['KUNROLL'] == '1'
assert report['matmul_compiler_records'] == native['variants'][0]['compiler_records']
build_lines = [shlex.split(line) for line in (PACKET / 'logs/package-offline-wheel.log').read_text().splitlines()
               if line.startswith('/usr/bin/g++ ')]
compiles = [line for line in build_lines if '-c' in line]
links = [line for line in build_lines if '-shared' in line]
assert len(compiles) == 12 and len(links) == 2
stage_groups = {}
for line in compiles:
    source = line[line.index('-c') + 1]
    stage = re.search(r'/p05-source-([^/]+)/', source)[1]
    stage_groups.setdefault(stage, []).append(source.split('/p05-source-' + stage + '/', 1)[1])
assert len(stage_groups) == 2 and all(len(group) == 6 for group in stage_groups.values())

elf_results = []
for relative in [r['path'] for r in manifest['artifacts'] if r['role'] != 'module']:
    path = PACKET / 'artifacts/bundle' / relative
    command = ['readelf', '-d', str(path)]
    child = subprocess.run(command, capture_output=True, check=False)
    assert child.returncode == 0
    (WORK / ('elf-' + Path(relative).name + '.log')).write_bytes(child.stdout)
    elf_results.append({'path': relative, 'command': command, 'exit_code': child.returncode,
                        'log_sha256': sha(child.stdout), 'needed': re.findall(r'\(NEEDED\).*\[([^]]+)\]', child.stdout.decode()),
                        'runpath': re.findall(r'\(RUNPATH\).*\[([^]]+)\]', child.stdout.decode())})
command = ['readelf', '-d', str(PACKET / 'artifacts/installed' / extension_name)]
child = subprocess.run(command, capture_output=True, check=False)
assert child.returncode == 0
(WORK / 'elf-extension.log').write_bytes(child.stdout)
elf_results.append({'path': extension_name, 'command': command, 'exit_code': child.returncode,
                    'log_sha256': sha(child.stdout), 'needed': re.findall(r'\(NEEDED\).*\[([^]]+)\]', child.stdout.decode()),
                    'runpath': re.findall(r'\(RUNPATH\).*\[([^]]+)\]', child.stdout.decode())})
assert elf_results[-1]['runpath'] == ['/opt/hostedtoolcache/Python/3.12.14/x64/lib']
result = {'scope': 'independent raw BF16 package/provenance reconciliation; no producer/auditor imports or native execution',
          'source_revision': REVISION, 'outcome': 'pass', 'stage_git_sources': 24, 'binding_sources': 22,
          'sdist_members': len(sdist), 'wheel_members': len(wheel), 'installed_members': len(installed),
          'wheel_record_rows': wheel_record_rows, 'installed_record_rows': installed_record_rows,
          'compiled_pins': pins, 'bundle_artifacts': manifest['artifacts'], 'commands': commands,
          'compiler_records': [{'role': r['role'], 'sha256': r['sha256']} for r in records],
          'offline_wheel_compile_groups': stage_groups, 'offline_wheel_compile_commands': len(compiles),
          'offline_wheel_links': len(links), 'elf_metadata': elf_results}
(WORK / 'raw-reconciliation.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
print(json.dumps({key: result[key] for key in ('outcome', 'stage_git_sources', 'binding_sources', 'sdist_members',
                                            'wheel_members', 'installed_members', 'offline_wheel_compile_commands', 'offline_wheel_links')}))
