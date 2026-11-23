#!/usr/bin/env python3
"""Independent read-only actual04 control review; no producer commands execute."""
import collections
import datetime
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time

sys.dont_write_bytecode = True
MODE = sys.argv[1]
assert MODE in ('old', 'new')
TRUSTED = Path('/workspace/p06-local-run-source-04' if MODE == 'old' else '/workspace/ai-gpu-next')
SOURCE = Path('/workspace/p06-local-run-source-04')
EVIDENCE = Path('/workspace/p06-local-native-run-04/evidence')
BASE = Path('/workspace/scratch/279b6658611e')
ARCHIVE = BASE / 'AI-GPU_P06_local_attempt_04_passed_2026-11-23.zip'
OUTPUT = BASE / ('validation/w10_a03-control-' + MODE + '-reader.json')
REVISION = '0f9aaa36d46364c297254164f5dab0d4f0e88349'
PINS = {'archive': 'd3a16e1e6e92a68414f5fdcce564b963dde2e9e801601191d52ceeb974faea6f',
    'dependency': 'f22f564ddd8d8a3d20636410f6d2f04b328018676803fdc5ea483c28ded10e8a',
    'native': '83040361c8b934dcab290bb8ba00d74e0b2b05f4db25f3455518c34945b997a6',
    'source': '04207022c43cc2e5a715e1eca626adb165711c975f2d1757e5ec3baddfbd5bf1',
    'pending': '802e174fb76420957286203b264ddca84dce949cbd32434c847821a36d2d7711',
    'substitution': '042dfc54c7e87ab33e1148a3360e2d4e51c620bdcfff92563f1386fe65699313'}

def check(condition, message):
    if not condition:
        raise AssertionError(message)

def identity(path):
    first = path.lstat()
    check(stat.S_ISREG(first.st_mode) and first.st_nlink == 1, 'nonregular or linked review input: ' + str(path))
    body = path.read_bytes()
    last = path.lstat()
    check((first.st_dev, first.st_ino, first.st_size, first.st_mtime_ns) ==
          (last.st_dev, last.st_ino, last.st_size, last.st_mtime_ns), 'review input changed during read')
    return {'sha256': hashlib.sha256(body).hexdigest(), 'size_bytes': len(body)}

def snapshot(root):
    rows = {}
    for path in sorted(root.rglob('*')):
        check(not path.is_symlink(), 'linked packet entry')
        if path.is_file():
            rows[path.relative_to(root).as_posix()] = identity(path)
    return rows

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def compact(rows):
    return {'files': len(rows), 'bytes': sum(row['size_bytes'] for row in rows.values()), 'manifest_sha256': digest(rows)}

started = time.monotonic()
started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
trusted_head = subprocess.check_output(['git', '-C', str(TRUSTED), 'rev-parse', 'HEAD'], text=True).strip()
source_head = subprocess.check_output(['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], text=True).strip()
check(source_head == REVISION, 'execution source revision differs')
before = snapshot(EVIDENCE)
archive_before = identity(ARCHIVE)
check(archive_before['sha256'] == PINS['archive'], 'archive pin differs')
for name, relative in {'dependency': 'dependency-build/report.json', 'native': 'native-lifetime/report.json',
        'source': 'native-lifetime/snapshots/source-before.json', 'pending': 'pending-probe/report.json',
        'substitution': 'dependency-substitution/report.json'}.items():
    check(before[relative]['sha256'] == PINS[name], name + ' pin differs')
sys.path.insert(0, str(TRUSTED / 'ci/project'))
import p06_dependency_control_replay as controls
native_reader = controls.native_replay
api = native_reader.dependency_replay._archive_api()
reader_before = controls._reader_sources()
active = False
events = []
producer_opens = []

def audit(event, args):
    if not active:
        return
    if event in ('subprocess.Popen', 'os.system', 'os.exec', 'os.posix_spawn', 'os.fork', 'os.forkpty',
                 'pty.spawn', 'ctypes.dlopen', 'os.mkdir', 'os.remove', 'os.rename', 'os.link', 'os.symlink') or event.startswith('socket.'):
        events.append({'event': event})
        raise RuntimeError('forbidden semantic-review action: ' + event)
    if event == 'open':
        name, mode, flags = args
        if isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_TRUNC | os.O_CREAT):
            events.append({'event': 'write-open', 'path': str(name)})
            raise RuntimeError('semantic reader attempted write')
        if isinstance(name, (str, bytes)):
            path = os.fsdecode(name)
            blocked = [str(EVIDENCE), '/workspace/p06-local-native-run-04/work', '/workspace/p06-local-host-02']
            if MODE == 'new':
                blocked.append(str(SOURCE))
            if any(path == root or path.startswith(root + '/') for root in blocked):
                producer_opens.append(path)
                raise RuntimeError('semantic reader attempted original producer path open')

sys.addaudithook(audit)
results = {}
active = True
semantic_start = time.monotonic()
try:
    with api.ArchiveReader(ARCHIVE, PINS['archive']) as archive:
        outer = archive.view('')
        verified, native = native_reader.verify_view(outer.subview('native-lifetime'), outer.subview('dependency-build'), api,
            expected_revision=REVISION, expected_receipt_sha256=PINS['dependency'],
            expected_native_report_sha256=PINS['native'], expected_source_manifest_sha256=PINS['source'])
        for name, folder, function in [('pending', 'pending-probe', controls.verify_probe_view),
                                       ('substitution', 'dependency-substitution', controls.verify_substitution_view)]:
            try:
                result = function(outer.subview(folder), native=native, expected_report_sha256=PINS[name],
                                  expected_native_report_sha256=PINS['native'])
                results[name] = {'outcome': 'pass', 'result': result}
            except ValueError as error:
                results[name] = {'outcome': 'fail', 'reason': str(error)}
        pending_report = outer.subview('pending-probe').json('report.json')
        sub = outer.subview('dependency-substitution')
        report = sub.json('report.json')
        pending_positive = outer.subview('pending-probe').read('logs/run-native.log').decode()
        pending_zero = outer.subview('pending-probe').read('logs/run-always-zero.log').decode()
        raw = sub.read('logs/run-alternate-extension.log').decode()
        case = next(row for row in native.cases if row['format'] == 'fp16')
        checked = report['dependency_control']
        original = sub.read('inputs/gddr6-original.cpp')
        derived = sub.read('work/gddr6-control.cpp')
        check(derived == original + b'\n' + controls.substitution.MARKER_DECLARATION, 'independent marker append differs')
        check(controls.substitution.MARKER in sub.read('work/libramulator-vortex.so'), 'alternate marker absent')
        frozen = report['control_products_before']
        check(frozen == report['control_products_after'], 'frozen control products changed')
        check(all(row['path'] != 'work/ramulator.stats.log' for row in frozen), 'runtime diagnostic entered frozen products')
        check(sum(row['path'] == 'work/ramulator.stats.log' for row in report['retained_files']) == 1,
              'runtime diagnostic final membership differs')
        archive_receipt = {k: v for k, v in archive.receipt().items() if k != 'read_files'}
        read_inventory = archive.receipt()['read_files']
    check(controls._reader_sources() == reader_before, 'trusted reader changed during semantic review')
finally:
    active = False
semantic_seconds = time.monotonic() - semantic_start
if MODE == 'old':
    check(results['pending'] == {'outcome': 'fail', 'reason': 'complete control packet member inventory: value differs'}, 'old pending failure changed')
    check(results['substitution']['outcome'] == 'fail', 'old substitution unexpectedly passed')
else:
    check(all(row['outcome'] == 'pass' for row in results.values()), 'new reader did not pass both controls')

def fp16_integer(bits):
    sign = -1 if bits & 0x8000 else 1
    exponent, fraction = (bits >> 10) & 31, bits & 1023
    check(exponent != 31, 'nonfinite fixture value')
    significand, shift = (fraction, -24) if exponent == 0 else (1024 + fraction, exponent - 25)
    if shift < 0:
        check(significand % (1 << -shift) == 0, 'fixture is not an exact integer')
        return sign * (significand >> -shift)
    return sign * (significand << shift)

def unpack(words):
    return [fp16_integer((int(word, 16) >> offset) & 65535) for word in words for offset in (0, 16)]

def fp32_integer(value):
    if value == 0:
        return '00000000'
    sign, magnitude = ((1 << 31) if value < 0 else 0), abs(value)
    exponent = magnitude.bit_length() - 1
    check(exponent <= 23, 'integer output not exactly representable by this oracle')
    return f'{sign | ((exponent + 127) << 23) | ((magnitude - (1 << exponent)) << (23 - exponent)):08x}'

a, b = unpack(case['a_words']), unpack(case['b_words'])
integers = [sum(a[row * 8 + k] * b[column * 8 + k] for k in range(8)) for row in range(8) for column in range(4)]
expected = [fp32_integer(value) for value in integers]
check(expected == case['expected'], 'independent FP16 integer matrix output differs')
operations = [json.loads(line.split(' ', 1)[1]) for line in raw.splitlines() if line.startswith('P06_WARM_OPERATION ')]
check(len(operations) == 33 and [row['operation_index'] for row in operations] == list(range(33)), 'substitution operation sequence differs')
check(all(row['actual_bits'] == expected and row['checked'] == 32 and row['mismatches'] == 0 and row['passed'] is True
          and row['dispatch']['launches'] == 1 for row in operations), 'substitution raw words differ from independent oracle')
check([row['id'] for row in report['commands']] == ['compile-alternate-extension', 'link-alternate-extension', 'run-alternate-extension'], 'substitution command ids differ')
check([row['exit_code'] for row in report['commands']] == [0, 0, 0], 'substitution command exits differ')
check(len(checked['records']) == 2 and {checked[role]['role'] for role in ('compile', 'link')} == {'compile', 'link'}, 'substitution tool record population differs')
check(report['managed_population_included'] is False and report['control_binding']['managed_population_included'] is False, 'substitution population promoted')
check(report['control_binding_sha256'] not in {row['execution_binding_sha256'] for row in native.report['processes']}, 'substitution binding reused')
check(report['rejection'] == 'loaded library libramulator-vortex.so: differs from the fixed contract', 'wrong original-provenance rejection')
check(all(report[k] is False and pending_report[k] is False for k in controls.contract.FALSE_CLAIMS), 'control claim promoted')
check(verified['counts']['processes'] == 4 and verified['counts']['launches'] == 132 and verified['counts']['checked_words'] == 4224, 'managed population changed')
contexts = [json.loads(line.split(' ', 1)[1]) for line in pending_positive.splitlines() if line.startswith('P06_PENDING_CONTEXT ')]
check(contexts == [dict(gp=gp, steps=135, positive_samples=23, max_pending=1, readonly_checks=137,
    stepped_reset_delta=1, checked_reset_delta=1, pending_final=0, checked_gp=gp) for gp in (7, -1)], 'pending context observations differ')
check(pending_zero.splitlines()[-1] == 'FAILED pending_reads native_probe: pending getter did not observe an outstanding read', 'zero control failure differs')
check(not any(line.startswith(('P06_PENDING_CONTEXT ', 'PASSED pending_reads')) for line in pending_zero.splitlines()), 'zero control passed')
check([row['exit_code'] for row in pending_report['commands']] == [0, 0, 0, 0, 1], 'pending command exits differ')
normal = pending_report['commands'][1]['argv']
zero = list(pending_report['commands'][3]['argv'])
check(zero.count('-DP06_PENDING_FORCE_ZERO=1') == 1, 'zero macro population differs')
zero.remove('-DP06_PENDING_FORCE_ZERO=1')
check(zero[-2] == normal[-2] == '-o', 'pending output argument differs')
zero[-1] = normal[-1]
check(zero == normal, 'zero control has additional compile differences')
check(pending_report['products'][0]['sha256'] != pending_report['products'][1]['sha256'], 'pending control binaries identical')
stats = {name: before[path] for name, path in {'pending': 'pending-probe/ramulator.stats.log',
    'substitution': 'dependency-substitution/work/ramulator.stats.log'}.items()}
if MODE == 'new':
    for name, row in results.items():
        diagnostic = row['result']['runtime_diagnostic']
        check({k: diagnostic[k] for k in ('sha256', 'size_bytes')} == stats[name], 'diagnostic identity differs')
        check(all(diagnostic[k] is False for k in ('interpreted', 'numerical_evidence', 'performance_evidence', 'qualification_evidence')), 'diagnostic promoted to evidence')
        check(all(row['result'][k] is False for k in controls.contract.FALSE_CLAIMS), 'replay control claim promoted')
after = snapshot(EVIDENCE)
check(before == after, 'original whole packet changed')
check(identity(ARCHIVE) == archive_before, 'original archive changed')
check(not events and not producer_opens, 'forbidden event attempted')
check(controls._reader_sources() == reader_before, 'trusted reader bytes changed')
packet_totals = {folder: compact({k[len(folder) + 1:]: v for k, v in before.items() if k.startswith(folder + '/')})
                 for folder in ('dependency-build', 'native-lifetime', 'pending-probe', 'dependency-substitution')}
summary = {'schema_version': 1, 'reviewer': 'w10_a03', 'outcome': 'pass', 'review_mode': MODE,
    'scope': 'Independent actual04 full dependency/native and both separate controls; unchanged original archive',
    'source_revision': REVISION, 'trusted_reader_root': str(TRUSTED), 'trusted_reader_base_revision': trusted_head,
    'pins': PINS, 'reader_files': len(reader_before), 'reader_source_inventory_sha256': digest(reader_before),
    'reader_control_source': next(row for row in reader_before if row['path'] == 'ci/project/p06_dependency_control_replay.py'),
    'reader_sources_unchanged': True, 'results': results, 'whole_original_packet': compact(before), 'packet_totals': packet_totals,
    'whole_original_packet_unchanged': True, 'archive_unchanged': True, 'archive_closing_rehash_passed': True,
    'archive_read': archive_receipt, 'unique_read_members': len(read_inventory), 'unique_read_inventory_sha256': digest(read_inventory),
    'managed_counts': verified['counts'], 'pending_contexts': contexts,
    'pending_command_exit_codes': [row['exit_code'] for row in pending_report['commands']],
    'pending_distinct_binaries': [row['sha256'] for row in pending_report['products']],
    'pending_exact_compile_difference': ['-DP06_PENDING_FORCE_ZERO=1', 'distinct output executable path'],
    'substitution': {'commands': [{'id': row['id'], 'exit_code': row['exit_code'], 'duration_seconds': row['duration_seconds']} for row in report['commands']],
        'tool_records': len(checked['records']), 'source_derivation': report['source_derivation'],
        'control_binding_sha256': report['control_binding_sha256'], 'managed_population_included': False,
        'counts': report['control_counts'], 'original_product': checked['original_product'], 'alternate_product': checked['alternate_product'],
        'original_ramulator_link_input': next(row for row in checked['link']['inputs_before'] if row['path'].endswith('/libramulator.so')),
        'expected_libraries': report['expected_libraries'], 'rejection': report['rejection'],
        'frozen_products': len(frozen), 'final_retained_files': len(report['retained_files']),
        'integer_oracle': {'method': 'independent FP16 integer unpack; row-major A by column-major B integer accumulation; integer-only FP32 encoding',
            'm': 8, 'n': 4, 'k': 8, 'integer_outputs': integers, 'expected_bits': expected,
            'raw_operation_rows': len(operations), 'launches': sum(row['dispatch']['launches'] for row in operations),
            'checked_words': sum(row['checked'] for row in operations), 'all_raw_words_exact': True}},
    'runtime_diagnostics': stats, 'all_seven_claims_false': True, 'native_execution_during_review': 'not_run',
    'retained_code_executed': False, 'prohibited_events': events, 'producer_path_open_attempts': producer_opens,
    'started_at': started_at, 'finished_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'semantic_duration_seconds': round(semantic_seconds, 6), 'duration_seconds': round(time.monotonic() - started, 6),
    'limitations': ['Retained consistency is not producer authentication or a fresh native execution.',
        'The managed four processes, two scalar probe processes and one substitution process remain separate populations.',
        'The diagnostic is opaque and contributes no numerical, performance or qualification evidence.',
        'Complete qualification, no-wrap proof, warm performance and acceptance remain unresolved.']}
OUTPUT.write_text(json.dumps(summary, indent=2, sort_keys=True) + '\n')
print(json.dumps({'outcome': 'pass', 'mode': MODE, 'semantic_seconds': summary['semantic_duration_seconds'],
    'results': {k: {field: value for field, value in row.items() if field != 'result'} for k, row in results.items()},
    'file': str(OUTPUT), 'identity': identity(OUTPUT), 'original_files': len(before), 'forbidden_events': events}, indent=2))
