import collections
import datetime
import gzip
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time
import zipfile

ROOT = Path('/tmp/ai-gpu-2bfab0261c05')
SOURCE = ROOT / 'published-source'
OUT = ROOT / 'current-governance/replay'
ARCHIVE = ROOT / 'current-governance/run-45775559523-attempt1.zip'
REVISION = '30b2e8ca69fba47646392c0cf6650cbb75155843'
TREE = '548b85370e3d13119730b5a30d1ec388d3e141a9'
DIGEST = '446526e0735f450081978566f713f1288d56562bf2ce65e9e4fb3f9b3bd9b864'
DISCOVERY = '0e8dbaad34266093f76db937eba670ce8f628ceb500998cb9094cdd2f12071fa'
READER_NAMES = ['governance_replay.py', 'governance_replay_archive.py',
                'governance_replay_collect.py', 'governance_replay_events.py',
                'governance_replay_records.py', 'governance_replay_source.py',
                'baseline_packet_io.py']


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def hash_bytes(data):
    return hashlib.sha256(data).hexdigest()


def file_hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def save(path, data):
    with path.open('x', encoding='utf-8') as handle:
        json.dump(data, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write('\n')


GIT_ENV = {'PATH': '/usr/bin:/bin', 'HOME': '/nonexistent', 'LANG': 'C',
           'LC_ALL': 'C', 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null',
           'GIT_OPTIONAL_LOCKS': '0', 'GIT_NO_REPLACE_OBJECTS': '1',
           'GIT_NO_LAZY_FETCH': '1', 'GIT_TERMINAL_PROMPT': '0',
           'GIT_ALLOW_PROTOCOL': '', 'GIT_ATTR_NOSYSTEM': '1'}


def git(*args):
    return subprocess.check_output(['/usr/bin/git', '--no-pager', '--no-optional-locks',
                                    '-c', 'core.fsmonitor=false', '-c',
                                    'core.hooksPath=/dev/null', '-c',
                                    'core.untrackedCache=false', *args],
                                   cwd=SOURCE, env=GIT_ENV, timeout=30)


def inventory():
    head = git('rev-parse', 'HEAD').decode().strip()
    tree = git('rev-parse', 'HEAD^{tree}').decode().strip()
    status = git('status', '--porcelain=v1', '--untracked-files=all').decode()
    assert head == REVISION and tree == TREE and not status
    entries, modes, links, total_bytes = [], collections.Counter(), [], 0
    for raw in git('ls-tree', '-r', '-z', 'HEAD').split(b'\0')[:-1]:
        metadata, name = raw.split(b'\t', 1)
        mode, kind, oid = metadata.decode().split()
        relative = name.decode()
        record = {'path': relative, 'mode': mode, 'type': kind, 'object_sha': oid}
        modes[mode] += 1
        if mode == '160000':
            links.append({'path': relative, 'pinned_oid': oid})
        else:
            path = SOURCE / relative
            before = path.lstat()
            if mode == '120000':
                assert stat.S_ISLNK(before.st_mode)
                body = os.fsencode(os.readlink(path))
            else:
                assert stat.S_ISREG(before.st_mode)
                assert bool(before.st_mode & 0o111) == (mode == '100755')
                body = path.read_bytes()
            after = path.lstat()
            assert (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
                    before.st_ctime_ns) == (after.st_dev, after.st_ino, after.st_size,
                                          after.st_mtime_ns, after.st_ctime_ns)
            assert hashlib.sha1(b'blob ' + str(len(body)).encode() + b'\0' + body).hexdigest() == oid
            record.update(bytes=len(body), sha256=hash_bytes(body))
            total_bytes += len(body)
        entries.append(record)
    raw_inventory = json.dumps(entries, separators=(',', ':'), sort_keys=True,
                               allow_nan=False).encode() + b'\n'
    summary = {'head': head, 'tree': tree, 'status': status, 'root': str(SOURCE),
               'entries': len(entries), 'materialized_bytes': total_bytes,
               'modes': dict(modes), 'gitlinks': links,
               'independent_inventory_json_bytes': len(raw_inventory),
               'independent_inventory_sha256': hash_bytes(raw_inventory),
               'inventory_encoding': 'sorted-key compact JSON entry array followed by LF; Git ls-tree order',
               'every_materialized_blob_matches_git_object': True}
    return summary, raw_inventory


def original():
    st = ARCHIVE.lstat()
    assert stat.S_ISREG(st.st_mode) and st.st_nlink == 1 and ARCHIVE.resolve() == ARCHIVE
    result = {'path': str(ARCHIVE), 'bytes': st.st_size, 'sha256': file_hash(ARCHIVE),
              'device': st.st_dev, 'inode': st.st_ino, 'nlink': st.st_nlink,
              'mtime_ns': st.st_mtime_ns, 'ctime_ns': st.st_ctime_ns}
    assert result['bytes'] == 1397895 and result['sha256'] == DIGEST
    return result


def reader_files():
    entries = []
    for name in READER_NAMES:
        relative = 'ci/project/' + name
        body = (SOURCE / relative).read_bytes()
        equal = body == git('show', REVISION + ':' + relative)
        assert equal
        entries.append({'path': relative, 'bytes': len(body), 'sha256': hash_bytes(body),
                        'equals_reader_commit': equal})
    return entries


def runtime():
    interpreter = Path(sys.executable)
    return {'python_executable': str(interpreter), 'python_resolved': str(interpreter.resolve()),
            'python_version': sys.version, 'python_sha256': file_hash(interpreter.resolve()),
            'git_executable': '/usr/bin/git', 'git_resolved': str(Path('/usr/bin/git').resolve()),
            'git_sha256': file_hash(Path('/usr/bin/git').resolve())}


assert SOURCE.resolve() == SOURCE and not OUT.exists()
OUT.mkdir(mode=0o700)
(OUT / 'reader-source').mkdir(mode=0o700)
before_time = utc()
source_before, raw_inventory = inventory()
save(OUT / 'source-before.json', source_before)
inventory_compressed = gzip.compress(raw_inventory, mtime=0)
with (OUT / 'source-inventory.json.gz').open('xb') as handle:
    handle.write(inventory_compressed)
reader_before = reader_files()
for item in reader_before:
    body = (SOURCE / item['path']).read_bytes()
    with (OUT / 'reader-source' / Path(item['path']).name).open('xb') as handle:
        handle.write(body)
original_before = original()
runtime_before = runtime()
environment = {'PATH': str(Path(sys.executable).parent) + ':/usr/bin:/bin',
               'HOME': '/nonexistent', 'LANG': 'C', 'LC_ALL': 'C', 'TZ': 'UTC',
               'PYTHONUTF8': '1', 'PYTHONDONTWRITEBYTECODE': '1'}
command = [sys.executable, '-B', str(SOURCE / 'ci/project/governance_replay.py'),
           '--archive', str(ARCHIVE), '--expected-revision', REVISION,
           '--source-dir', str(SOURCE), '--expected-sha256', DIGEST,
           '--output', str(OUT / 'replay.json')]
record = {'reader_revision': REVISION, 'reader_root': str(SOURCE), 'reader_tree': TREE,
          'reader_files': reader_before, 'source_before': source_before,
          'original_before': original_before, 'runtime_before': runtime_before,
          'command': command, 'cwd': str(SOURCE), 'environment': environment,
          'observation_start_utc': before_time, 'start_utc': utc(),
          'scope': 'independent-current-source-governance-artifact-replay',
          'source_inventory_gzip': {'path': 'source-inventory.json.gz',
                                    'bytes': len(inventory_compressed),
                                    'sha256': hash_bytes(inventory_compressed)}}
save(OUT / 'invocation.json', record)
print(json.dumps({'event': 'starting replay', 'source': REVISION,
                  'inventory_entries': source_before['entries'],
                  'inventory_bytes': source_before['materialized_bytes'],
                  'reader_files': len(reader_before), 'start_utc': record['start_utc']}), flush=True)
started = time.monotonic()
with (OUT / 'replay.stdout.log').open('xb') as stdout, (OUT / 'replay.stderr.log').open('xb') as stderr:
    process = subprocess.run(command, cwd=SOURCE, env=environment,
                             stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                             timeout=180, check=False)
record.update(exit_code=process.returncode, replay_wall_seconds=time.monotonic() - started,
              end_utc=utc())
source_after, raw_after = inventory()
save(OUT / 'source-after.json', source_after)
record.update(source_after=source_after, original_after=original(),
              runtime_after=runtime(), reader_files_after=reader_files())
record['source_unchanged'] = source_after == source_before and raw_after == raw_inventory
record['reader_files_unchanged'] = record['reader_files_after'] == reader_before
record['original_unchanged'] = record['original_after'] == original_before
record['runtime_unchanged'] = record['runtime_after'] == runtime_before
for filename in ('replay.json', 'replay.stdout.log', 'replay.stderr.log'):
    path = OUT / filename
    record[filename] = {'bytes': path.stat().st_size, 'sha256': file_hash(path)} if path.exists() else None
save(OUT / 'invocation-completed.json', record)
assert process.returncode == 0, 'reader failed; retain invocation and original'
assert all(record[key] for key in ('source_unchanged', 'reader_files_unchanged',
                                   'original_unchanged', 'runtime_unchanged'))
receipt = json.loads((OUT / 'replay.json').read_text())
assert receipt['revision'] == REVISION and receipt['source_tree'] == TREE
assert receipt['canonical_tests'] == 5547 and receipt['canonical_ids_sha256'] == DISCOVERY
assert receipt['independent_packet_replay'] is True
for key in ('provider_authenticated', 'retained_code_executed', 'tests_executed_by_replay',
            'native_acceptance', 'phase_acceptance', 'performance_acceptance'):
    assert receipt[key] is False
with zipfile.ZipFile(ARCHIVE) as archive:
    summary = json.loads(archive.read('run/summary.json'))
    discovered = json.loads(archive.read('run/discovered.json'))
    member_inventory = [{'name': item.filename, 'bytes': item.file_size,
                         'compressed_bytes': item.compress_size, 'crc32': item.CRC}
                        for item in archive.infolist()]
save(OUT / 'retained-execution-summary.json', summary['execution'])
save(OUT / 'original-member-inventory.json', member_inventory)
assert hash_bytes(('\n'.join(discovered['test_ids']) + '\n').encode()) == DISCOVERY
assert summary['governance_passed'] is True
assert summary['execution']['strict_success'] is True
assert summary['execution']['tests_run'] == receipt['canonical_tests']
print(json.dumps({'event': 'replay completed', 'exit_code': process.returncode,
                  'tests': receipt['canonical_tests'], 'successful_subtests': receipt['successful_subtests'],
                  'events': receipt['events'], 'retained_duration_seconds': receipt['duration_seconds'],
                  'replay_wall_seconds': record['replay_wall_seconds'],
                  'receipt_sha256': record['replay.json']['sha256'],
                  'source_reader_original_runtime_stable': True}), flush=True)
