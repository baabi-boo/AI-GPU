#!/usr/bin/env python3
"""Complete the separate GCC 12 host root without changing its failed predecessor."""
import datetime
import hashlib
import json
import lzma
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import time

ROOT = Path('/workspace/p06-local-host-02')
OLD = Path('/workspace/p06-local-host')
VERSION = '12.2.0-14+deb12u1'
SOURCE = Path('/workspace/ai-gpu-next')
ROOT.mkdir(mode=0o700)
for name in ('packages', 'extracted', 'metadata', 'logs', 'bin', 'probe', 'gnupg'):
    (ROOT / name).mkdir(mode=0o700)
report = {'schema_version': 1, 'scope': 'separate host installation repair; not GPU execution',
          'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'old_root': str(OLD), 'new_root': str(ROOT), 'commands': [], 'packages': [],
          'outcome': 'running', 'failures': []}

def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        while b := f.read(1024 * 1024): h.update(b)
    return h.hexdigest()

def save():
    (ROOT / 'receipt.json').write_text(json.dumps(report, indent=2) + '\n')

def identity(path):
    return {'path': str(path), 'resolved_path': str(path.resolve(strict=True)),
            'sha256': digest(path), 'size_bytes': path.stat().st_size}

def inventory(root):
    rows = []
    for p in sorted(root.rglob('*')):
        s = p.lstat(); row = {'path': p.relative_to(root).as_posix(), 'mode': stat.S_IMODE(s.st_mode)}
        if stat.S_ISLNK(s.st_mode): row.update(kind='symlink', target=os.readlink(p))
        elif stat.S_ISREG(s.st_mode): row.update(kind='file', size_bytes=s.st_size, sha256=digest(p))
        elif stat.S_ISDIR(s.st_mode): row.update(kind='directory')
        else: raise RuntimeError('unexpected old-host member')
        rows.append(row)
    return rows

def run(name, argv, *, env=None, timeout=60, check=True):
    begin = time.monotonic()
    p = subprocess.run(argv, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, timeout=timeout)
    for channel, body in (('stdout', p.stdout), ('stderr', p.stderr)):
        (ROOT / 'logs' / (name + '.' + channel + '.log')).write_bytes(body)
    row = {'id': name, 'argv': argv, 'cwd': str(ROOT), 'exit_code': p.returncode,
           'duration_seconds': time.monotonic() - begin,
           'stdout': identity(ROOT / 'logs' / (name + '.stdout.log')),
           'stderr': identity(ROOT / 'logs' / (name + '.stderr.log'))}
    report['commands'].append(row); save()
    if check and p.returncode != 0: raise RuntimeError(name + ' failed: ' + p.stderr.decode(errors='replace'))
    return p

def download(name, url, path, maximum):
    run(name, ['curl', '--proto', '=https', '--location', '--fail', '--silent', '--show-error',
              '--connect-timeout', '20', '--max-time', '60', '--max-filesize', str(maximum),
              '--output', str(path), url], timeout=65)
    return dict(identity(path), url=url)

try:
    before = inventory(OLD)
    (ROOT / 'metadata' / 'old-host-before.json').write_text(json.dumps(before, indent=2) + '\n')
    report['old_inventory_before'] = identity(ROOT / 'metadata' / 'old-host-before.json')
    keyring = Path('/usr/share/keyrings/debian-archive-keyring.pgp')
    report['keyring'] = identity(keyring)
    report['keyring_package'] = run('keyring-version', ['dpkg-query', '-W', 'debian-archive-keyring']).stdout.decode().strip()
    release = ROOT / 'metadata' / 'InRelease'
    report['inrelease'] = download('inrelease', 'https://deb.debian.org/debian/dists/bookworm/InRelease', release, 1024 * 1024)
    run('verify-inrelease', ['gpg', '--batch', '--no-tty', '--no-options', '--no-auto-key-retrieve',
        '--homedir', str(ROOT / 'gnupg'), '--no-default-keyring', '--keyring', str(keyring),
        '--status-fd', '2', '--output', str(ROOT / 'metadata' / 'Release'), '--decrypt', str(release)])
    statuses = (ROOT / 'logs' / 'verify-inrelease.stderr.log').read_text()
    valid = [line for line in statuses.splitlines() if line.startswith('[GNUPG:] VALIDSIG ')]
    assert valid, 'no valid signature from the installed Debian keyring'
    report['valid_signatures'] = valid
    text = (ROOT / 'metadata' / 'Release').read_text()
    fields = dict(line.split(': ', 1) for line in text.splitlines() if ': ' in line and not line.startswith(' '))
    assert fields['Origin'] == 'Debian' and fields['Codename'] == 'bookworm'
    report['release_fields'] = {k: fields.get(k) for k in ('Origin', 'Label', 'Suite', 'Version', 'Codename', 'Date', 'Valid-Until')}
    block = text.split('\nSHA256:\n', 1)[1].split('\nSHA512:', 1)[0]
    matches = [line.split() for line in block.splitlines() if line.split() and line.split()[-1] == 'main/binary-amd64/Packages.xz']
    assert len(matches) == 1 and len(matches[0]) == 3
    sha, size, rel = matches[0]; size = int(size)
    index = ROOT / 'metadata' / 'Packages.xz'
    report['package_index'] = download('package-index', 'https://deb.debian.org/debian/dists/bookworm/' + rel, index, size)
    assert index.stat().st_size == size and digest(index) == sha
    report['package_index'].update(signed_sha256=sha, signed_size_bytes=size, verified=True)
    stanzas = []
    for text in lzma.decompress(index.read_bytes()).decode().split('\n\n'):
        if text.startswith('Package: libstdc++6\n'):
            row = dict(line.split(': ', 1) for line in text.splitlines() if ': ' in line and not line.startswith(' '))
            if row.get('Architecture') == 'amd64' and row.get('Version') == VERSION: stanzas.append(row)
    assert len(stanzas) == 1
    stanza = stanzas[0]
    (ROOT / 'metadata' / 'libstdc++6-stanza.json').write_text(json.dumps(stanza, indent=2) + '\n')
    old_receipt = json.loads((OLD / 'receipt.json').read_text())
    for row in old_receipt['downloads']:
        p = Path(row['path']); target = ROOT / 'packages' / p.name
        assert p.stat().st_size == row['expected_size_bytes'] and digest(p) == row['expected_sha256']
        shutil.copyfile(p, target)
        report['packages'].append(dict(identity(target), name=p.name, source='verified predecessor package',
            expected_sha256=row['expected_sha256'], expected_size_bytes=row['expected_size_bytes']))
    runtime = ROOT / 'packages' / Path(stanza['Filename']).name
    runtime_record = download('runtime-package', 'https://deb.debian.org/debian/' + stanza['Filename'], runtime, int(stanza['Size']))
    assert runtime.stat().st_size == int(stanza['Size']) and digest(runtime) == stanza['SHA256']
    report['packages'].append(dict(runtime_record, name=runtime.name, source='signed Debian package index',
        expected_sha256=stanza['SHA256'], expected_size_bytes=int(stanza['Size'])))
    for n, row in enumerate(report['packages']):
        assert row['sha256'] == row['expected_sha256'] and row['size_bytes'] == row['expected_size_bytes']
        run('extract-' + str(n), ['dpkg-deb', '-x', row['path'], str(ROOT / 'extracted')])
    for name in ('gcc', 'g++'):
        (ROOT / 'bin' / name).symlink_to(ROOT / 'extracted' / 'usr' / 'bin' / (name + '-12'))
    (ROOT / 'bin' / 'cmake').symlink_to('/workspace/p06-build-tools/cmake/data/bin/cmake')
    env = {'PATH': str(ROOT / 'bin') + ':/usr/bin:/bin', 'LANG': 'C', 'LC_ALL': 'C', 'TZ': 'UTC'}
    report['probe_environment'] = env
    report['aliases'] = {}
    for name in ('gcc', 'g++', 'cmake'):
        path = ROOT / 'bin' / name
        version = run(name.replace('+','p') + '-version', [str(path), '--version'], env=env)
        report['aliases'][name] = dict(identity(path), version=version.stdout.decode().splitlines()[0])
    selected = run('stdcxx-selection', [str(ROOT / 'bin' / 'g++'), '-print-file-name=libstdc++.so'], env=env).stdout.decode().strip()
    assert Path(selected).is_absolute() and Path(selected).is_file()
    report['selected_shared_runtime'] = identity(Path(selected))
    assert report['selected_shared_runtime']['resolved_path'].startswith(str(ROOT / 'extracted') + '/')
    (ROOT / 'probe' / 'probe.cpp').write_text('#include <future>\n#include <string>\nextern "C" int p06_host_probe() { auto f=std::async(std::launch::async, []{return 40;}); return f.get()+int(std::string("ok").size()); }\n')
    (ROOT / 'probe' / 'main.cpp').write_text('#include <cstdio>\nextern "C" int p06_host_probe();\nint main(){int r=p06_host_probe(); std::printf("%d\\n",r); return r==42?0:1;}\n')
    cxx = str(ROOT / 'bin' / 'g++'); probe = ROOT / 'probe'
    run('shared-compile-link', [cxx, '-std=c++17', '-O2', '-fPIC', '-Wall', '-Wextra', '-Wfatal-errors', '-Werror',
        '-shared', '-pthread', str(probe / 'probe.cpp'), '-Wl,-Map,' + str(probe / 'probe.map'), '-o', str(probe / 'libprobe.so')], env=env)
    run('driver-compile-link', [cxx, '-std=c++17', '-O2', '-Wall', '-Wextra', '-Wfatal-errors', '-Werror',
        str(probe / 'main.cpp'), '-L' + str(probe), '-lprobe', '-Wl,-rpath,' + str(probe), '-o', str(probe / 'probe')], env=env)
    dynamic = run('shared-dynamic', ['readelf', '-d', str(probe / 'libprobe.so')], env=env).stdout.decode()
    assert re.search(r'\(NEEDED\).*\[libstdc\+\+\.so\.6\]', dynamic)
    loader = run('loader-inspection', ['ldd', str(probe / 'probe')], env=env).stdout.decode()
    executed = run('probe-run', [str(probe / 'probe')], env=dict(env, LD_DEBUG='libs'))
    assert executed.stdout == b'42\n'
    map_text = (probe / 'probe.map').read_text()
    assert not re.search(r'libstdc\+\+\.a\([^)]*\)', map_text)
    report['shared_probe'] = {'stdout': executed.stdout.decode(), 'needed_libstdcxx_so6': True,
        'no_static_libstdcxx_members': True, 'link_map': identity(probe / 'probe.map'), 'loader_output': loader,
        'runtime_note': 'Link-time libstdc++ is the extracted matching GCC12 package; default runtime loader still selects system libraries, outside complete host-toolchain provenance scope.'}
    after = inventory(OLD)
    assert before == after, 'predecessor host root changed'
    report['old_root_unchanged'] = True
    report['outcome'] = 'pass'
except BaseException as error:
    report.update(outcome='fail'); report['failures'].append(str(error)); save(); raise
finally:
    report['finished_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    save()
print(json.dumps({'outcome': report['outcome'], 'root': str(ROOT), 'packages': len(report['packages']),
                  'receipt': str(ROOT / 'receipt.json')}))
