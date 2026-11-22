from pathlib import Path, PurePosixPath
from collections import Counter
from contextlib import redirect_stdout
import ast
import copy
import hashlib
import io
import json
import shlex
import sys
import tempfile
import unittest.mock as mock
import zipfile

sys.dont_write_bytecode = True
ROOT = Path('/workspace/scratch/98908dfa3444/AI-GPU')
MOD = ROOT / 'ci/project'
sys.path.insert(0, str(MOD))
import p06_counter_diagnostics_replay as replay

ORIGINAL = ROOT / 'docs/project/evidence/p06-counter-diagnostics/native/run-45026112992-attempt1.zip'
SHA = 'c4a7ae49259bbb72066d55f7c3e733ce5696f215175ce308f654e1cec9e9c13f'
REV = '407ab9fea5e4f793a2a5088f566a87f3e631aa84'
PREFIX = 'checked-counters/'
assert hashlib.sha256(ORIGINAL.read_bytes()).hexdigest() == SHA
with zipfile.ZipFile(ORIGINAL) as archive:
    members = {name: archive.read(name) for name in archive.namelist()}
report = json.loads(members[PREFIX + 'report.json'])
assert len(members) == 327
assert report['expected_revision'] == REV

def same(a, b):
    assert type(a) is type(b), (type(a), type(b))
    if isinstance(a, dict):
        assert set(a) == set(b)
        for key in a:
            same(a[key], b[key])
    elif isinstance(a, list):
        assert len(a) == len(b)
        for x, y in zip(a, b):
            same(x, y)
    else:
        assert a == b, (a, b)

def body(row):
    raw = members[PREFIX + row['path']]
    same(row['size_bytes'], len(raw))
    same(row['sha256'], hashlib.sha256(raw).hexdigest())
    return raw

same(report['source_before'], report['source_after'])
same(report['tools_before'], report['tools_after'])
sources = report['source_before']['files']
assert len(sources) == 270
names = [row['path'] for row in sources]
assert names == sorted(set(names))
source_name_sha = hashlib.sha256(''.join(name + '\n' for name in names).encode()).hexdigest()
same(source_name_sha, 'd074477d6c6b9a0521c2a79e912b3113e9648bc73a3e6cc3dc0f3bc311106108')
same(report['retained_sources'], [dict(row, path='artifacts/source/' + row['path']) for row in sources])
for row in report['retained_sources']:
    body(row)
print('SOURCE_BYTES', json.dumps(dict(files=len(sources), names_sha256=source_name_sha, snapshots_equal=True)))

budget = dict(jobs=2, threads=1, max_rss_bytes=4 * 1024**3, min_free_bytes=15 * 1024**3,
              max_log_bytes=16 * 1024**2, timeouts_seconds=dict(configure=120, build=1800, run=180))
same(report['budget'], budget)
assert type(report['available_memory_bytes']) is int and 4 * 1024**3 <= report['available_memory_bytes'] < 2**64
assert all(type(v) is int and 15 * 1024**3 <= v < 2**64 for v in report['free_disk_bytes'].values())
expected_commands = ['version-make', 'version-gpp', 'version-python3', 'version-executing_python',
    'ordinary-configure', 'ordinary-build', 'ordinary-header', 'ordinary-boundaries',
    'checked-configure', 'checked-build', 'checked-header', 'checked-boundaries',
    'checked-core-overflow', 'checked-cache-aggregate-overflow', 'checked-pending-underflow',
    'checked-cache-backing-overflow', 'checked-tcu-backing-overflow']
same([row['id'] for row in report['commands']], expected_commands)
commands = {row['id']: row for row in report['commands']}
for row in report['commands']:
    name = row['id']
    timeout = 30 if name.startswith('version-') else 1800 if name.endswith('-build') else 120 if name.endswith(('-configure', '-header')) else 180
    same(row['timeout_seconds'], timeout)
    same(row['outcome'], 'pass')
    same(row['exit_code'], 0)
    same(row['reason'], None)
    same(row['process_started'], True)
    same(row['cleanup_complete'], True)
    same(row['environment'], report['environment'])
    assert type(row['peak_rss_bytes']) is int and 0 <= row['peak_rss_bytes'] <= 4 * 1024**3
    assert type(row['log_size_bytes']) is int and 0 <= row['log_size_bytes'] <= 16 * 1024**2
    assert type(row['duration_seconds']) in (int, float) and 0 <= row['duration_seconds'] <= timeout + 5
    body(dict(path=row['log'], sha256=row['log_sha256'], size_bytes=row['log_size_bytes']))
print('COMMANDS', json.dumps(dict(count=len(commands), all_status_and_resource_bounds=True,
    max_observed_rss=max(c['peak_rss_bytes'] for c in commands.values()),
    max_observed_log=max(c['log_size_bytes'] for c in commands.values()))))

for variant in report['variants']:
    name = variant['id']
    for key in ('generated', 'compiler_stamp', 'diagnostic_sources', 'binary'):
        same(variant[key + '_before'], variant[key + '_after'])
    same(variant['compiler_records']['object_identities'], variant['objects_after'])
    for key in ('retained_configuration', 'retained_compiler_stamp', 'retained_diagnostic_sources', 'retained_probe'):
        for row in variant[key]:
            body(row)
    compiler = report['tools_before']['tools']['g++']['path']
    records = [shlex.split(line) for line in members[PREFIX + 'logs/' + name + '-build.log'].decode().splitlines() if line.strip()]
    assert all(words[0] == compiler for words in records)
    compiles = [words for words in records if '-c' in words]
    links = [words for words in records if '-c' not in words]
    assert (len(compiles), len(links)) == (45, 1)
    stamp = shlex.split(body(variant['retained_compiler_stamp'][0]).decode())
    def no_dep(words):
        i = words.index('-MF')
        return words[:i] + words[i + 2:]
    inputs, objects = [], []
    for words in compiles:
        assert words[-4] == '-c' and words[-2] == '-o'
        original, target = words[-3], words[-1]
        inputs.append(original)
        objects.append(target)
        same(no_dep(words[1:-4]), no_dep(stamp))
        same(words[words.index('-MF') + 1], str(PurePosixPath(target).with_suffix('.d')))
    assert len(set(inputs)) == len(set(objects)) == 45
    same(sorted(inputs), variant['compiler_records']['compiled_sources'])
    same(objects, [row['path'] for row in variant['compiler_records']['object_identities']])
    link = links[0]
    assert link[-2] == '-o'
    same(link[-1], variant['binary_path'])
    same(link[1:1+len(stamp)], [variant['binary_path'] if i and stamp[i-1] == '-MF' else token for i, token in enumerate(stamp)])
    suffix = link[1+len(stamp):-2]
    same(Counter(suffix[:45]), Counter(objects))
    source = report['paths']['source']
    same(suffix[45:], [source + '/third_party/softfloat/build/Linux-x86_64-GCC/softfloat.a',
        '-Wl,-rpath,' + source + '/third_party/ramulator', '-L' + source + '/third_party/ramulator', '-lramulator',
        '-Wl,-rpath,' + source + '/third_party/ramulator_ext', '-L' + source + '/third_party/ramulator_ext',
        '-Wl,--push-state,--no-as-needed', '-lramulator-vortex', '-Wl,--pop-state'])
    same(variant['compiler_records']['translation_units'], 45)
    same(variant['compiler_records']['link_count'], 1)
    generated = body(variant['retained_diagnostic_sources'][0])
    same(generated, members[PREFIX+'artifacts/source/sim/simx/tcu/tcu_tbuf.cpp'] + b'\n' +
         members[PREFIX+'artifacts/source/tests/unittest/checked_counters/access_tcu.cpp'])
    print('BUILD_BYTES', json.dumps(dict(variant=name, translation_units=len(compiles), links=len(links),
          exact_fresh_objects_and_libraries=True, source_configuration_object_binary_stable=True)))

pending, closure = ['p06_counter_diagnostics_replay'], set()
while pending:
    name = pending.pop()
    if name in closure:
        continue
    closure.add(name)
    for node in ast.walk(ast.parse((MOD / (name+'.py')).read_text())):
        children = ([n.name.split('.')[0] for n in node.names] if isinstance(node, ast.Import) else
                    [node.module.split('.')[0]] if isinstance(node, ast.ImportFrom) and node.module else [])
        pending.extend(n for n in children if (MOD / (n+'.py')).is_file())
rows = replay._reader_sources()
same(closure, {Path(row['path']).stem for row in rows})
assert len(rows) == 24
original_read = Path.read_bytes
for row in rows:
    changed = False
    selected = ROOT / row['path']
    def drift(path):
        raw = original_read(path)
        return raw + b'\n# synthetic stability drift\n' if changed and path == selected else raw
    try:
        with mock.patch.object(Path, 'read_bytes', drift):
            with replay.open_archive(ORIGINAL, SHA, prefix='checked-counters'):
                changed = True
    except ValueError as error:
        assert 'trusted reader source stability' in str(error)
    else:
        raise AssertionError('reader drift accepted: '+row['path'])
print('READER_CLOSURE', json.dumps(dict(local_modules=len(closure), omitted=[], stability_mutations_rejected=len(rows))))

with tempfile.TemporaryDirectory(prefix='w06-diagnostic-review-') as temporary:
    archive_path = Path(temporary) / 'mutation.zip'
    def mutate(change):
        changed_report = copy.deepcopy(report)
        change(changed_report)
        altered = dict(members)
        altered[PREFIX+'report.json'] = (json.dumps(changed_report, sort_keys=True, allow_nan=False)+'\n').encode()
        with zipfile.ZipFile(archive_path, 'w', compression=zipfile.ZIP_STORED) as archive:
            for name, raw in sorted(altered.items()):
                archive.writestr(name, raw)
        digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
        return replay.replay_archive(archive_path, digest, expected_revision=REV)
    accepted = []
    for value in (2**53+1, 2**64-1):
        def change(r):
            for key in ('binary_before', 'binary_after'):
                r['variants'][0][key]['size_bytes'] = value
        result = mutate(change)
        same(result['variants'][0]['recorded_binary_identity']['size_bytes'], value)
        assert result['native_execution'] == 'not_run'
        for field in ('qualified','ready_for_warm','warm_execution','acceptance','acceptance_claimed',
                      'phase_acceptance','performance_acceptance','full_warm_coverage','retained_code_executed'):
            same(result[field], False)
        accepted.append(value)
    rejected = []
    for value in (True, 1.0, -1, 0, 2**64):
        def change(r):
            for key in ('binary_before', 'binary_after'):
                r['variants'][0][key]['size_bytes'] = value
        try:
            mutate(change)
        except ValueError as error:
            assert 'recorded file size' in str(error)
        else:
            raise AssertionError('invalid uint64 size accepted: '+repr(value))
        rejected.append(repr(value))
    print('UINT64_RECORDED_IDENTITIES', json.dumps(dict(exact_integers_accepted=accepted, invalid_values_rejected=rejected,
          payload_authentication=False, acceptance=False)))

print('RESULT independent reconstruction and 31 targeted stability/integer probes passed; no native execution')
