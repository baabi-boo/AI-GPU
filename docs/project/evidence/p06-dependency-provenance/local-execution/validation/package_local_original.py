import argparse
import collections
import datetime
import hashlib
import json
from pathlib import Path
import stat
import zipfile

parser = argparse.ArgumentParser()
parser.add_argument('evidence', type=Path)
parser.add_argument('archive', type=Path)
args = parser.parse_args()
root = args.evidence.resolve(strict=True)
assert root.is_dir() and not args.archive.exists()
envelope = json.loads((root / 'local-execution.json').read_text())
assert envelope['state'] == 'finished'
identities = {}

def identity(path):
    status = path.lstat()
    assert stat.S_ISREG(status.st_mode) and status.st_nlink == 1
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 ** 2):
            digest.update(chunk)
    after = path.lstat()
    assert (status.st_dev, status.st_ino, status.st_size, status.st_mtime_ns) == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    return {'sha256': digest.hexdigest(), 'size_bytes': status.st_size}

files = sorted(path for path in root.rglob('*') if path.is_file() or path.is_symlink())
for path in files:
    assert path.resolve(strict=True) == path
    identities[path.relative_to(root).as_posix()] = identity(path)
with zipfile.ZipFile(args.archive, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
    for path in files:
        relative = path.relative_to(root).as_posix()
        info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = (stat.S_IFREG | 0o644) << 16
        with path.open('rb') as source, archive.open(info, 'w') as destination:
            while chunk := source.read(1024 ** 2):
                destination.write(chunk)
        assert identity(path) == identities[relative]
with zipfile.ZipFile(args.archive) as archive:
    assert archive.testzip() is None
    assert set(archive.namelist()) == set(identities)
    for name, expected in identities.items():
        digest = hashlib.sha256()
        size = 0
        with archive.open(name) as stream:
            while chunk := stream.read(1024 ** 2):
                size += len(chunk)
                digest.update(chunk)
        assert {'sha256': digest.hexdigest(), 'size_bytes': size} == expected
assert {path.relative_to(root).as_posix(): identity(path) for path in files} == identities
assert sorted(path.relative_to(root).as_posix() for path in root.rglob('*') if path.is_file() or path.is_symlink()) == sorted(identities)
result = {'schema_version': 1, 'filename': args.archive.name, **identity(args.archive),
          'original_revision': envelope['expected_revision'], 'original_outcome': envelope['outcome'],
          'original_native_execution': envelope['native_execution'], 'original_evidence_root': str(root),
          'member_count': len(identities), 'uncompressed_bytes': sum(row['size_bytes'] for row in identities.values()),
          'subpacket_file_counts': dict(collections.Counter(name.split('/')[0] for name in identities)),
          'all_members_rehashed_against_original': True, 'original_rehashed_after_packaging': True,
          'zip_crc_verified': True, 'retained_code_executed': False,
          'packaged_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'external_report_pins': {name: identities[name] for name in identities if name in ({'local-execution.json', 'dependency-preparation.json'} | {row['path'] for row in envelope['reports'].values()})}}
target = args.archive.with_suffix('.identity.json')
target.write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
