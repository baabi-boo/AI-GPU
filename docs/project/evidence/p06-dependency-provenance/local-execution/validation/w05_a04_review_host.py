"""Read-only independent package-to-installation review; no package extraction."""
from collections import Counter
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import tarfile
import time

ROOT = Path('/workspace/p06-local-host-02')
OUT = Path('/workspace/scratch/279b6658611e/validation/w05_a04-package-review.json')

def digest(path):
    h = hashlib.sha256()
    size = 0
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
            size += len(block)
    return {'sha256': h.hexdigest(), 'size_bytes': size}

def check():
    start = time.monotonic()
    packages = sorted((ROOT / 'packages').glob('*.deb'))
    assert len(packages) == 7, len(packages)
    results = []
    retained_names = set()
    for package in packages:
        before = digest(package)
        proc = subprocess.Popen(['dpkg-deb', '--fsys-tarfile', str(package)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        counts = Counter()
        byte_count = 0
        with tarfile.open(fileobj=proc.stdout, mode='r|') as stream:
            for member in stream:
                literal = member.name.removeprefix('./').rstrip('/')
                if literal in ('', '.'):
                    continue
                rel = PurePosixPath(literal)
                assert not rel.is_absolute() and '..' not in rel.parts
                path = ROOT / 'extracted' / rel
                retained_names.add(literal)
                if member.isdir():
                    assert path.is_dir() and not path.is_symlink(), literal
                    counts['directory'] += 1
                elif member.issym():
                    assert path.is_symlink() and os.readlink(path) == member.linkname, literal
                    counts['symlink'] += 1
                elif member.isfile():
                    assert path.is_file() and not path.is_symlink(), literal
                    expected = hashlib.sha256()
                    total = 0
                    source = stream.extractfile(member)
                    for block in iter(lambda: source.read(1024 * 1024), b''):
                        expected.update(block)
                        total += len(block)
                    assert total == member.size
                    actual = digest(path)
                    assert actual == {'sha256': expected.hexdigest(), 'size_bytes': total}, literal
                    assert stat.S_IMODE(path.stat().st_mode) == member.mode, literal
                    counts['regular'] += 1
                    byte_count += total
                elif member.islnk():
                    target_rel = PurePosixPath(member.linkname.removeprefix('./'))
                    assert not target_rel.is_absolute() and '..' not in target_rel.parts
                    target = ROOT / 'extracted' / target_rel
                    assert path.is_file() and target.is_file() and path.samefile(target), literal
                    counts['hardlink'] += 1
                else:
                    raise AssertionError(('unsupported member', literal, member.type))
        stderr = proc.stderr.read().decode('utf-8')
        assert proc.wait(timeout=30) == 0, stderr
        assert before == digest(package), package
        results.append({'package': package.name, **before, 'members': dict(counts),
            'regular_bytes': byte_count, 'stderr': stderr})
    actual_names = {p.relative_to(ROOT / 'extracted').as_posix()
        for p in (ROOT / 'extracted').rglob('*')}
    assert actual_names == retained_names, {'extra': sorted(actual_names-retained_names),
        'missing': sorted(retained_names-actual_names)}
    selected = {}
    for name in ('gcc', 'g++', 'cmake'):
        path = ROOT / 'bin' / name
        resolved = path.resolve(strict=True)
        selected[name] = {'path': str(path), 'target': os.readlink(path),
            'resolved_path': str(resolved), **digest(resolved)}
    development = ROOT / 'extracted/usr/lib/gcc/x86_64-linux-gnu/12/libstdc++.so'
    runtime = development.resolve(strict=True)
    result = {'outcome': 'pass', 'scope': 'package member bytes/modes/links and selected aliases',
        'packages': results, 'installed_unique_entries': len(actual_names),
        'selected_aliases': selected, 'development_link': {'path': str(development),
            'target': os.readlink(development), 'resolved_path': str(runtime), **digest(runtime)},
        'duration_seconds': time.monotonic() - start,
        'package_scripts_executed': False, 'retained_evidence_executed': False,
        'host_root_modified': False}
    OUT.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'outcome': result['outcome'], 'packages': len(results),
        'installed_unique_entries': len(actual_names), 'duration_seconds': result['duration_seconds']}))

if __name__ == '__main__':
    check()
