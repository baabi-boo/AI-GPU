#!/usr/bin/env python3
"""W09 A4 independent archive relocation and retained-data replay record."""
import hashlib
import json
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import time

SOURCE = Path('/workspace/scratch/ba0248fde989/AI-GPU')
EVIDENCE = SOURCE / 'docs/project/evidence/p05-python'
WORK = SOURCE.parent / 'p05-work/w09_a4'
DEST = WORK / 'relocated'
ORIGINAL = SOURCE.parent / 'p05-work/ci-e1420fd'
KINDS = ('numerics', 'dispatch', 'provenance')
PINS = {
    'numerics': '608b16c80a1a40816ef15f04b2670c736e2abca7768e7c6ad546c8a96f23e736',
    'dispatch': 'ab0a1d1d6d0268b0766e5d3bc211e2830efb5e9683a413854fc1a16a3d5de391',
    'provenance': '4684a4e928ff672d371bdb78ab5f646b61ae59d1147c3c690e722a22a89186ac',
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def record(path):
    raw = path.read_bytes()
    return {'path': str(path), 'size_bytes': len(raw), 'sha256': sha(raw)}


def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')


def inventory(root):
    rows = {}
    for path in sorted(root.rglob('*')):
        mode = path.lstat().st_mode
        assert stat.S_ISDIR(mode) or stat.S_ISREG(mode), str(path)
        if stat.S_ISREG(mode):
            raw = path.read_bytes()
            rows[path.relative_to(root).as_posix()] = {'size_bytes': len(raw), 'sha256': sha(raw)}
    return rows


def run(label, argv, log, timeout=180):
    start = time.monotonic()
    with log.open('xb') as stream:
        child = subprocess.run(argv, cwd=SOURCE, stdin=subprocess.DEVNULL,
                               stdout=stream, stderr=subprocess.STDOUT, timeout=timeout, check=False)
    row = {'id': label, 'command': argv, 'cwd': str(SOURCE), 'exit_code': child.returncode,
           'duration_seconds': time.monotonic() - start, 'log': record(log), 'timeout_seconds': timeout}
    receipt['commands'].append(row)
    save(WORK / 'execution.json', receipt)
    return row


def normalize(value, prefix):
    if isinstance(value, str):
        return value.replace(str(prefix), '<retained-packets>')
    if isinstance(value, list):
        return [normalize(item, prefix) for item in value]
    if isinstance(value, dict):
        return {normalize(key, prefix): normalize(item, prefix) for key, item in value.items()}
    return value


def git(*args):
    return subprocess.check_output(['git', *args], cwd=SOURCE).decode().strip()


extractor = EVIDENCE / 'reviews/extract_retained.py'
tracked = [extractor, EVIDENCE / 'archive-index.json']
tracked += [EVIDENCE / 'archives' / (variant + '.zip') for variant in ('simx-fp16', 'simx-bf16')]
tracked += [EVIDENCE / 'reviews' / ('audit_' + name + '.py') for name in KINDS]
tracked += [EVIDENCE / 'reviews' / ('full-' + name + '.json') for name in KINDS]
receipt = {
    'schema_version': 1, 'reviewer': '/root/w09_a4_relocated_replay_review',
    'scope': 'relocated retained-data replay and bounded extractor review; no native execution',
    'execution_performed': False, 'acceptance_claimed': False, 'outcome': 'running',
    'source_revision': git('rev-parse', 'HEAD'), 'source_tree': git('rev-parse', 'HEAD^{tree}'),
    'before': [record(path) for path in tracked],
    'free_disk_bytes_before': shutil.disk_usage(WORK).free, 'commands': [],
}
save(WORK / 'execution.json', receipt)
for name in KINDS:
    assert record(EVIDENCE / 'reviews' / ('audit_' + name + '.py'))['sha256'] == PINS[name]

row = run('extract-original-archives', [sys.executable, '-B', str(extractor), '--output', str(DEST)],
          WORK / 'extraction.log')
assert row['exit_code'] == 0
index = json.loads((EVIDENCE / 'archive-index.json').read_text())
archive_checks = []
for archive in index['archives']:
    variant = archive['variant']
    actual = inventory(DEST / variant)
    expected = {row['path']: {key: row[key] for key in ('size_bytes', 'sha256')} for row in archive['members']}
    assert actual == expected and len(actual) == 304
    originals = inventory(ORIGINAL / variant)
    assert actual == originals
    stamps = [name for name in actual if Path(name).name == '.config.stamp']
    assert stamps
    archive_checks.append({'variant': variant, 'member_count': len(actual),
        'expanded_size_bytes': sum(item['size_bytes'] for item in actual.values()),
        'inventory_sha256': sha(json.dumps(actual, sort_keys=True, separators=(',', ':')).encode()),
        'hidden_configuration_stamps': stamps, 'matches_index_and_original_extraction': True})
receipt['archive_checks'] = archive_checks
receipt['extraction'] = record(DEST / 'extraction.json')
save(WORK / 'execution.json', receipt)

comparisons = {}
for name in KINDS:
    script = EVIDENCE / 'reviews' / ('audit_' + name + '.py')
    output = EVIDENCE / 'reviews' / ('replay-' + name + '.json')
    log = EVIDENCE / 'reviews' / ('replay-' + name + '.log')
    command = [sys.executable, '-B', str(script), '--source-dir', str(SOURCE)]
    for variant in ('simx-fp16', 'simx-bf16'):
        command += ['--packet', str(DEST / variant / 'python')]
    command += ['--output', str(output)]
    row = run('relocated-' + name, command, log)
    assert row['exit_code'] == 0
    observed = json.loads(output.read_text())
    expected = json.loads((EVIDENCE / 'reviews' / ('full-' + name + '.json')).read_text())
    full_key = {'numerics': 'full_matrix_verified', 'dispatch': 'full_matrix_checked', 'provenance': 'full_matrix'}[name]
    assert observed['outcome'] == 'pass' and observed[full_key] is True
    assert normalize(observed, DEST) == normalize(expected, ORIGINAL), 'relocated result differs: ' + name
    comparisons[name] = {'outcome': 'pass', 'full_scope_field': full_key, 'full_scope': True,
        'original_result': record(EVIDENCE / 'reviews' / ('full-' + name + '.json')),
        'relocated_result': record(output), 'exact_match_after_only_packet_path_normalization': True}
receipt['comparisons'] = comparisons
save(WORK / 'execution.json', receipt)

# Negative checks use only copies; the validated extraction is never rewritten.
preserved = inventory(DEST)
row = run('existing-destination-rejected', [sys.executable, '-B', str(extractor), '--output', str(DEST)],
          WORK / 'negative-existing.log')
assert row['exit_code'] == 2 and 'output must be fresh' in (WORK / 'negative-existing.log').read_text()
assert inventory(DEST) == preserved
negatives = [{'case': 'existing-destination', 'exit_code': 2, 'retained_destination_unchanged': True}]
for kind in ('index', 'archive'):
    fixture = WORK / ('negative-' + kind)
    (fixture / 'reviews').mkdir(parents=True)
    shutil.copyfile(extractor, fixture / 'reviews/extract_retained.py')
    shutil.copyfile(EVIDENCE / 'archive-index.json', fixture / 'archive-index.json')
    if kind == 'index':
        path = fixture / 'archive-index.json'
        path.write_bytes(path.read_bytes() + b'\n')
        reason = 'retained archive index changed'
    else:
        (fixture / 'archives').mkdir()
        for variant in ('simx-fp16', 'simx-bf16'):
            shutil.copyfile(EVIDENCE / 'archives' / (variant + '.zip'), fixture / 'archives' / (variant + '.zip'))
        path = fixture / 'archives/simx-fp16.zip'
        body = bytearray(path.read_bytes())
        body[100] ^= 1
        path.write_bytes(body)
        reason = 'original archive identity differs: simx-fp16'
    output = WORK / ('negative-' + kind + '-output')
    row = run('corrupt-' + kind + '-rejected', [sys.executable, '-B', str(fixture / 'reviews/extract_retained.py'),
              '--output', str(output)], WORK / ('negative-' + kind + '.log'))
    assert row['exit_code'] == 2 and reason in (WORK / ('negative-' + kind + '.log')).read_text()
    assert not output.exists()
    negatives.append({'case': 'corrupt-' + kind, 'exit_code': 2, 'reason': reason,
                      'mutated_input': record(path), 'no_output_directory_created': True})
receipt['negative_checks'] = negatives
receipt['after'] = [record(path) for path in tracked]
assert receipt['before'] == receipt['after']
assert inventory(DEST) == preserved
assert git('rev-parse', 'HEAD') == receipt['source_revision']
assert git('rev-parse', 'HEAD^{tree}') == receipt['source_tree']
receipt['original_inputs_and_reviewed_scripts_unchanged'] = True
receipt['outcome'] = 'pass'
receipt['limitations'] = [
    'Data-only audit replay: no kernel, extension, native application or simulator was executed.',
    'Immutable archives and member index are pinned; this is not a general-purpose ZIP extractor.',
    'Canonical paths, fresh exclusive files, regular ZIP members and byte bounds are checked; hostile concurrent filesystem mutation is outside this review.',
    'The exact retained source Git objects remain required for provenance review; external tools/system libraries are not reconstructed.',
    'Recorded data consistency does not authenticate the original execution or establish physical performance, package portability or framework support.',
]
save(WORK / 'execution.json', receipt)
save(EVIDENCE / 'relocated-replay.json', receipt)
print(json.dumps({'outcome': 'pass', 'commands': len(receipt['commands']), 'variants': len(archive_checks),
                  'members': sum(row['member_count'] for row in archive_checks), 'negative_checks': len(negatives)}, sort_keys=True))
