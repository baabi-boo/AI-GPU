"""Narrow W06 packaging integration; one real sequential unbound extension build.

Adapted from the W04 A06 harness. It never creates or loads a synthetic DSO.
"""
from pathlib import Path
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import platform
import re
import resource
import shutil
import signal
import subprocess
import sys
import tarfile
import time
import traceback
import zipfile


ROOT = Path('/workspace/scratch/ba0248fde989/AI-GPU')
WORK = Path('/workspace/scratch/ba0248fde989/p05-work/w06_a2-checks')
WORK.mkdir(exist_ok=True)
(WORK / 'logs').mkdir(exist_ok=True)
spec = importlib.util.spec_from_file_location('p05_w06_bundle', ROOT / 'python/vortex_ai/_bundle.py')
BUNDLE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(BUNDLE)
ENV = {
    key: value for key, value in os.environ.items()
    if not key.startswith(('PYTHON', 'PIP_')) and key not in (
        'VORTEX_AI_BUNDLE', 'VORTEX_DRIVER', 'LD_LIBRARY_PATH', 'LD_PRELOAD',
        'LD_AUDIT', 'CFLAGS', 'CXXFLAGS', 'CPPFLAGS', 'LDFLAGS', 'ARCHFLAGS',
        'CPATH', 'C_INCLUDE_PATH', 'CPLUS_INCLUDE_PATH', 'LIBRARY_PATH')
}
ENV.update(CC=shutil.which('gcc'), CXX=shutil.which('g++'), MAKEFLAGS='-j1',
           MAX_JOBS='1', CMAKE_BUILD_PARALLEL_LEVEL='1', PYTHONDONTWRITEBYTECODE='1')
COMMANDS = []


def save(name, value):
    (WORK / name).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def identity(path):
    raw = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}


def limit_memory():
    resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))


def run(label, argv, cwd, *, timeout=45):
    argv = [str(item) for item in argv]
    timed_argv = ['/usr/bin/time', '-v', '-o', str(WORK / 'logs' / (label + '.time')), *argv]
    started = time.monotonic()
    process = subprocess.Popen(
        timed_argv, cwd=cwd, env=ENV, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, start_new_session=True,
        preexec_fn=limit_memory)
    timed_out = False
    try:
        output, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        os.killpg(process.pid, signal.SIGTERM)
        try:
            output, _ = process.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            output, _ = process.communicate(timeout=3)
    log = WORK / 'logs' / (label + '.log')
    log.write_text(output)
    timing_file = WORK / 'logs' / (label + '.time')
    timing = timing_file.read_text() if timing_file.exists() else ''
    rss = re.search(r'Maximum resident set size \(kbytes\): (\d+)', timing)
    record = {
        'id': label, 'argv': argv, 'timed_argv': timed_argv, 'cwd': str(cwd),
        'exit_code': process.returncode, 'timeout_seconds': timeout,
        'timed_out': timed_out, 'address_space_limit_bytes': 2 * 1024**3,
        'elapsed_seconds': round(time.monotonic() - started, 3),
        'maximum_rss_kib': int(rss.group(1)) if rss else None, 'log': identity(log),
    }
    COMMANDS.append(record)
    save('commands.json', COMMANDS)
    assert not timed_out, (label, 'timed out')
    assert process.returncode == 0, (label, output[-6000:])
    print(label + ': PASS', flush=True)
    return output


def py(label, code, cwd, *args):
    return run(label, [sys.executable, '-I', '-B', '-c', code, *args], cwd)


def inspect_sdist(archive, destination, label):
    expected = set(BUNDLE.SOURCE_PATHS) | {
        'LICENSE', 'python/README.md', 'PKG-INFO',
        'python/p05_build/p05_build_config.h', 'python/p05_build/source_inventory.json',
    }
    expected.update('python/vortex_ai.egg-info/' + name for name in (
        'PKG-INFO', 'SOURCES.txt', 'dependency_links.txt', 'top_level.txt'))
    with tarfile.open(archive) as stream:
        members = stream.getmembers()
        prefix = 'vortex_ai-0.1.0/'
        assert all(member.isdir() or member.isfile() for member in members)
        files = [member for member in members if member.isfile()]
        assert all(member.name.startswith(prefix) for member in files)
        actual = {member.name.removeprefix(prefix) for member in files}
        assert actual == expected, {
            'missing': sorted(expected - actual), 'extra': sorted(actual - expected)}
        assert len(actual) == 31
        assert not any(Path(name).suffix in {'.so', '.o', '.a', '.vxbin', '.pyc'} for name in actual)
        source_list = stream.extractfile(prefix + 'python/vortex_ai.egg-info/SOURCES.txt').read().decode()
        assert set(source_list.splitlines()) == expected
        assert not any(Path(line).is_absolute() or 'p05-source-' in line
                       for line in source_list.splitlines())
        stream.extractall(destination, filter='data')
    save(label + '-sdist-members.json', sorted(actual))
    return destination / 'vortex_ai-0.1.0'


def main():
    pins = {'setuptools': '84.2.1', 'wheel': '0.48.0', 'packaging': '26.3'}
    observed = {name: importlib.metadata.version(name) for name in pins}
    assert observed == pins
    assert sys.version_info[:2] == (3, 12) and platform.python_implementation() == 'CPython'
    assert sys.platform == 'linux'
    assert all(shutil.which(name) for name in ('gcc', 'g++', 'readelf', 'nm'))
    assert Path('/usr/bin/time').is_file()
    initial_disk = shutil.disk_usage(WORK).free
    assert initial_disk > 1024**3
    save('prerequisites.json', {
        'build_tools': observed, 'pip': importlib.metadata.version('pip'),
        'python': sys.version, 'executable': sys.executable,
        'compiler': ENV['CXX'], 'compiler_version': subprocess.check_output(
            [ENV['CXX'], '--version'], text=True).splitlines()[0],
        'free_disk_bytes': initial_disk, 'meminfo': Path('/proc/meminfo').read_text(),
        'single_job': True, 'compiler_release': 'root W06 A01 completion message',
    })
    sources = BUNDLE.source_inventory(ROOT)
    assert len(sources) == 22
    source_pin = BUNDLE.inventory_digest(sources)
    save('source-inventory.json', sources)
    save('source-identity.json', {
        'source_sha256': source_pin,
        'base_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'scope': 'exact uncommitted 22-input source bytes; host packaging only',
    })
    source = WORK / 'fresh-unbound-source'
    source.mkdir()
    for relative in [row['path'] for row in sources] + ['LICENSE', 'python/README.md']:
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    assert BUNDLE.source_inventory(source) == sources
    assert BUNDLE.source_inventory(ROOT) == sources
    save('input-hashes.json', [identity(source / relative) for relative in (
        [row['path'] for row in sources] + ['LICENSE', 'python/README.md'])])
    sdist_code = 'import sys; from setuptools.build_meta import build_sdist; print(build_sdist(sys.argv[1]))'
    py('clean-unbound-sdist', sdist_code, source, WORK / 'unbound-sdist')
    archive = WORK / 'unbound-sdist/vortex_ai-0.1.0.tar.gz'
    unbound = inspect_sdist(archive, WORK / 'unbound-extracted', 'unbound')
    source.rename(WORK / 'original-source-unavailable')
    assert BUNDLE.source_inventory(unbound) == sources
    assert (unbound / 'python/p05_build/source_inventory.json').read_bytes() == BUNDLE.canonical_bytes(sources)
    poisons = []
    for name in ('p05_build_config.h', 'vortex2.h', 'array'):
        path = unbound / 'sw/runtime/ai' / name
        assert not path.exists()
        path.write_text('#error W06_A02_UNPINNED_ORIGINAL_HEADER_MUST_NOT_COMPILE\n')
        poisons.append(identity(path))
    save('stale-headers.json', poisons)
    assert BUNDLE.source_inventory(unbound) == sources
    assert BUNDLE.source_inventory(ROOT) == sources
    wheels = WORK / 'wheels'
    wheel_output = run('unbound-offline-wheel', [
        sys.executable, '-I', '-m', 'pip', '--isolated', 'wheel', '--verbose',
        '--disable-pip-version-check', '--no-index', '--no-deps', '--no-build-isolation',
        '--no-cache-dir', '--wheel-dir', wheels, unbound], WORK, timeout=240)
    compile_lines = [line.strip() for line in wheel_output.splitlines()
                     if ('g++ ' in line or 'gcc ' in line) and ' -c ' in line]
    link_lines = [line.strip() for line in wheel_output.splitlines()
                  if ('g++ ' in line or 'gcc ' in line) and ' -shared ' in line]
    assert len(compile_lines) == 6, compile_lines
    assert len(link_lines) == 1, link_lines
    stages = list((unbound / 'build').glob('temp*/p05-source-*'))
    assert len(stages) == 1, stages
    staged = stages[0]
    assert BUNDLE.source_inventory(staged) == sources
    assert all(str(staged) in line for line in compile_lines)
    assert all(not (staged / 'sw/runtime/ai' / name).exists()
               for name in ('p05_build_config.h', 'vortex2.h', 'array'))
    assert all(identity(Path(row['path'])) == row for row in poisons)
    generated = list((staged / 'p05-config').iterdir())
    assert len(generated) == 1
    assert (generated[0] / 'p05_build_config.h').read_bytes() == (unbound / 'python/p05_build/p05_build_config.h').read_bytes()
    assert set(path.relative_to(staged).as_posix() for path in staged.rglob('*') if path.is_file()) == (
        set(BUNDLE.SOURCE_PATHS) | {
            (generated[0] / name).relative_to(staged).as_posix()
            for name in ('p05_build_config.h', 'source_inventory.json')})
    save('compiler-staging.json', {
        'compile_commands': compile_lines, 'link_commands': link_lines,
        'stage': str(staged), 'exact_source_sha256': source_pin,
        'staged_source_count': len(sources), 'stale_headers_not_staged': True,
    })
    metadata_files = [path for path in (unbound / 'python/vortex_ai.egg-info').rglob('*') if path.is_file()]
    metadata_leaks = {}
    for path in metadata_files:
        content = path.read_text()
        leaked = [line for line in content.splitlines()
                  if 'p05-source-' in line or (path.name == 'SOURCES.txt' and Path(line).is_absolute())]
        if leaked:
            metadata_leaks[path.relative_to(unbound).as_posix()] = leaked
    save('postbuild-metadata.json', {'absolute_or_stage_path_leaks': metadata_leaks,
                                   'file_hashes': [identity(path) for path in metadata_files]})
    assert not metadata_leaks, metadata_leaks
    py('postbuild-sdist-repack', sdist_code, unbound, WORK / 'postbuild-sdist')
    repacked_archive = WORK / 'postbuild-sdist/vortex_ai-0.1.0.tar.gz'
    repacked = inspect_sdist(repacked_archive, WORK / 'repacked-extracted', 'postbuild')
    assert BUNDLE.source_inventory(repacked) == sources
    for name in ('p05_build_config.h', 'source_inventory.json'):
        assert (repacked / 'python/p05_build' / name).read_bytes() == (unbound / 'python/p05_build' / name).read_bytes()
    candidates = list(wheels.glob('*.whl'))
    assert len(candidates) == 1
    wheel = candidates[0]
    assert wheel.name == 'vortex_ai-0.1.0-cp312-cp312-linux_x86_64.whl'
    with zipfile.ZipFile(wheel) as stream:
        members = stream.namelist()
        python_members = {row['path'].removeprefix('python/') for row in sources
                          if row['path'].startswith('python/vortex_ai/')}
        assert {name for name in members if name.endswith('.py')} == python_members
        assert len([name for name in members if name.endswith('.so')]) == 1
        assert not any('p05_build' in name or name.endswith(('.vxbin', '.o', '.a', '.cpp', '.h')) for name in members)
        assert all(not Path(name).is_absolute() and 'p05-source-' not in name for name in members)
        for row in sources:
            if row['path'].startswith('python/vortex_ai/'):
                assert hashlib.sha256(stream.read(row['path'].removeprefix('python/'))).hexdigest() == row['sha256']
        for name in members:
            if '.dist-info/' in name:
                assert b'p05-source-' not in stream.read(name)
        assert stream.read('vortex_ai-0.1.0.dist-info/licenses/LICENSE') == (unbound / 'LICENSE').read_bytes()
        metadata = stream.read('vortex_ai-0.1.0.dist-info/METADATA').decode()
        assert not any(line.startswith('Requires-Dist:') for line in metadata.splitlines())
    save('wheel-members.json', members)
    venv = WORK / 'fresh-venv'
    run('fresh-venv', [sys.executable, '-I', '-m', 'venv', '--without-pip', venv], WORK)
    interpreter = venv / 'bin/python'
    run('offline-install', [sys.executable, '-I', '-m', 'pip', '--isolated', '--python',
        interpreter, 'install', '--disable-pip-version-check', '--no-index', '--no-deps',
        '--no-cache-dir', '--no-compile', wheel], WORK)
    outside = WORK / 'outside-checkout'
    outside.mkdir()
    smoke = '''
import importlib.metadata, importlib.util, json, pathlib, sys
root, expected_pin = pathlib.Path(sys.argv[1]), sys.argv[2]
assert not pathlib.Path.cwd().is_relative_to(root)
import vortex_ai
import vortex_ai.launch
assert 'vortex_ai._native' not in sys.modules
assert all(importlib.util.find_spec(name) is None for name in ('numpy','torch','setuptools'))
identity = vortex_ai.build_info()
assert identity == {'binding_api': 1, 'bundle_sha256': '', 'source_sha256': expected_pin}
from vortex_ai import _native
prefix = pathlib.Path(sys.prefix)
for path in (vortex_ai.__file__, _native.__file__, vortex_ai.launch.__file__):
    assert pathlib.Path(path).is_relative_to(prefix), path
    assert not pathlib.Path(path).is_relative_to(root), path
distribution = importlib.metadata.distribution('vortex-ai')
assert distribution.version == vortex_ai.__version__ == '0.1.0'
assert not distribution.metadata.get_all('Requires-Dist')
cases = vortex_ai.fixture_cases()
assert len(cases) == len(set(cases)) == 10
try:
    vortex_ai.Session.open('/intentionally-absent-unbound-bundle')
except vortex_ai.BindingError as error:
    assert 'unbound' in str(error) and 'wheel' in str(error)
    failure = {'type': type(error).__name__, 'kind': error.kind, 'message': str(error)}
else:
    raise AssertionError('unbound wheel unexpectedly opened a session')
try:
    vortex_ai.launch.verified_environment('/intentionally-absent-unbound-bundle', environment={})
except ValueError as error:
    assert 'not a bound API-1 package' in str(error)
else:
    raise AssertionError('unbound launcher accepted a bundle')
maps = pathlib.Path('/proc/self/maps').read_text()
project_names = ('libvortex', 'libsimx', 'libramulator')
assert not any(name in maps for name in project_names)
package_root = pathlib.Path(vortex_ai.__file__).parent
payload = sorted(path.relative_to(package_root).as_posix() for path in package_root.rglob('*') if path.is_file())
assert len(payload) == 5 and len([name for name in payload if name.endswith('.py')]) == 4
assert not any(name.endswith('.pyc') for name in payload)
print(json.dumps({'package': vortex_ai.__file__, 'extension': _native.__file__,
                  'launcher': vortex_ai.launch.__file__, 'build_info': identity,
                  'fixture_count': len(cases), 'failure': failure,
                  'loaded_project_libraries': [], 'runtime_requirements': [],
                  'installed_package_payload': payload,
                  'installed_files': sorted(str(path) for path in distribution.files)}, indent=2))
'''
    imported = run('clean-installed-import', [interpreter, '-I', '-B', '-c', smoke,
                                            ROOT, source_pin], outside)
    report = json.loads(imported)
    save('import-smoke.json', report)
    extension = Path(report['extension'])
    dynamic = run('elf-dynamic', ['readelf', '-d', extension], outside)
    exports = run('elf-exports', ['nm', '-D', '--defined-only', extension], outside)
    needed = re.findall(r'\(NEEDED\).*\[([^]]+)\]', dynamic)
    assert set(needed).issubset({'libstdc++.so.6', 'libgcc_s.so.1', 'libc.so.6',
                               'libm.so.6', 'libdl.so.2', 'libpthread.so.0'})
    assert not any(name in dynamic for name in ('RPATH', 'RUNPATH', 'libvortex', 'libsimx', 'libramulator'))
    assert any(line.split()[-1] == 'PyInit__native' for line in exports.splitlines())
    assert not any(line.split()[-1].startswith('vx_') for line in exports.splitlines())
    assert BUNDLE.source_inventory(ROOT) == sources, 'production source changed during qualification'
    save('artifact-hashes.json', [identity(path) for path in (archive, repacked_archive, wheel, extension)])
    save('result.json', {
        'outcome': 'pass', 'source_sha256': source_pin, 'elf_needed': needed,
        'commands': len(COMMANDS), 'single_extension_build': True,
        'translation_units_compiled': len(compile_lines), 'links': len(link_lines),
        'synthetic_native_payload_created_or_loaded': False,
        'postbuild_metadata_stage_paths': 0, 'sdist_regular_files': 31,
        'child_maxrss_kib': resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
        'initial_free_disk_bytes': initial_disk, 'final_free_disk_bytes': shutil.disk_usage(WORK).free,
        'retained_regular_file_bytes': sum(path.stat().st_size for path in WORK.rglob('*') if path.is_file()),
        'scope': 'host packaging and unbound isolated import; no accelerator/native bundle execution',
    })
    print(json.dumps(json.loads((WORK / 'result.json').read_text()), indent=2), flush=True)


if __name__ == '__main__':
    try:
        main()
    except BaseException as error:
        save('result.json', {
            'outcome': 'fail', 'type': type(error).__name__, 'error': str(error),
            'traceback': traceback.format_exc(), 'completed_commands': len(COMMANDS),
        })
        raise
