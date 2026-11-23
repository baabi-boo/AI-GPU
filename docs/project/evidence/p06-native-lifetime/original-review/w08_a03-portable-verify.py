"""Run from the repository root; checks archive bytes without extraction."""
from pathlib import Path
import hashlib
import json
import zipfile

packet = Path('docs/project/evidence/p06-native-lifetime/native/b4127b19-run45130300651-attempt1')
expected = '3d4879f73c197352689d65feb56e73f537701fc1411e55bf53c92b1b41e13db3'
archive = packet / 'original.zip'
assert archive.stat().st_size == 9086055
assert hashlib.sha256(archive.read_bytes()).hexdigest() == expected
inventory = json.loads((packet / 'member-inventory.json').read_text())
assert inventory['archive_sha256'] == expected
assert inventory['archive_bytes'] == 9086055
rows = inventory['files']
index = {row['path']: row for row in rows}
assert len(rows) == len(index) == 1264
with zipfile.ZipFile(archive) as data:
    names = data.namelist()
    assert len(names) == len(set(names)) == len(index)
    assert set(names) == set(index)
    for name, identity in index.items():
        body = data.read(name)  # CRC checked by the ZIP reader.
        assert len(body) == identity['size_bytes']
        assert hashlib.sha256(body).hexdigest() == identity['sha256']
print('Verified original archive and 1264 members; nothing extracted or executed.')
