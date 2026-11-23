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
TRUSTED = Path('/workspace/ai-gpu-next')
SOURCE = Path('/workspace/p06-local-run-source-04')
EVIDENCE = Path('/workspace/p06-local-native-run-04/evidence')
PENDING = EVIDENCE / 'pending-probe'
ARCHIVE = Path('/workspace/scratch/279b6658611e/AI-GPU_P06_local_attempt_04_passed_2026-11-23.zip')
OUT = Path('/workspace/scratch/279b6658611e/validation/w10_a02-pending-original-review.json')
REVISION = '0f9aaa36d46364c297254164f5dab0d4f0e88349'
PINS = {
    'archive': 'd3a16e1e6e92a68414f5fdcce564b963dde2e9e801601191d52ceeb974faea6f',
    'dependency': 'f22f564ddd8d8a3d20636410f6d2f04b328018676803fdc5ea483c28ded10e8a',
    'native': '83040361c8b934dcab290bb8ba00d74e0b2b05f4db25f3455518c34945b997a6',
    'source': '04207022c43cc2e5a715e1eca626adb165711c975f2d1757e5ec3baddfbd5bf1',
    'pending': '802e174fb76420957286203b264ddca84dce949cbd32434c847821a36d2d7711',
}

def identity(path):
    before = path.stat()
    assert stat.S_ISREG(before.st_mode)
    body = path.read_bytes()
    after = path.stat()
    assert (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    return {'sha256': hashlib.sha256(body).hexdigest(), 'size_bytes': len(body)}

def packet_snapshot(root):
    result = {}
    for path in sorted(root.rglob('*')):
        assert not path.is_symlink()
        if path.is_file():
            assert path.stat().st_nlink == 1
            result[path.relative_to(root).as_posix()] = identity(path)
    return result

def summary(rows):
    return {'files': len(rows), 'bytes': sum(row['size_bytes'] for row in rows.values()),
            'manifest_sha256': hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()).hexdigest()}

def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args]).decode().strip()

started = time.monotonic()
report = json.loads((PENDING / 'report.json').read_bytes())
native_report = json.loads((EVIDENCE / 'native-lifetime/report.json').read_bytes())
assert identity(PENDING / 'report.json')['sha256'] == PINS['pending']
assert identity(EVIDENCE / 'native-lifetime/report.json')['sha256'] == PINS['native']
assert identity(EVIDENCE / 'dependency-build/report.json')['sha256'] == PINS['dependency']
assert identity(ARCHIVE)['sha256'] == PINS['archive']
assert git(SOURCE, 'rev-parse', 'HEAD') == REVISION
assert git(SOURCE, 'status', '--porcelain=v1', '--untracked-files=all') == ''
packets_before = {name: packet_snapshot(EVIDENCE / name) for name in ('dependency-build', 'native-lifetime', 'pending-probe')}
assert report['inputs_before'] == report['inputs_after']
initial = report['inputs_before']
variant = native_report['variants'][0]
build = Path(variant['build_dir'])
selected = {}
for label, base, rows in (('source', SOURCE, initial['sources']), ('build', build, initial['build']), ('dependency', SOURCE, initial['dependencies'])):
    for row in rows:
        path = base / row['path']
        found = identity(path)
        assert found == {k: row[k] for k in ('sha256', 'size_bytes')}, (label, path)
        selected[str(path)] = found
compiler = initial['compiler']
assert str(Path(compiler['path']).resolve()) == compiler['resolved_path']
selected[compiler['path']] = identity(Path(compiler['path']))
assert selected[compiler['path']] == {k: compiler[k] for k in ('sha256', 'size_bytes')}
assert initial['managed_report']['sha256'] == PINS['native']
assert report['managed_build_binding_sha256'] == variant['build_binding_sha256']
ids = ['compiler-version', 'compile-native', 'run-native', 'compile-always-zero', 'run-always-zero']
assert [row['id'] for row in report['commands']] == ids
assert [row['exit_code'] for row in report['commands']] == [0, 0, 0, 0, 1]
commands = {row['id']: row for row in report['commands']}
normal = commands['compile-native']['argv']
zero = list(commands['compile-always-zero']['argv'])
assert zero.count('-DP06_PENDING_FORCE_ZERO=1') == 1
zero.remove('-DP06_PENDING_FORCE_ZERO=1')
assert zero[-2] == normal[-2] == '-o'
zero[-1] = normal[-1]
assert zero == normal
assert report['environment']['PATH'].split(':')[0] == '/workspace/p06-local-host-02/bin'
assert normal[0] == '/workspace/p06-local-host-02/bin/g++'
positive_text = (PENDING / 'logs/run-native.log').read_text()
negative_text = (PENDING / 'logs/run-always-zero.log').read_text()
contexts = [json.loads(line.split(' ', 1)[1]) for line in positive_text.splitlines() if line.startswith('P06_PENDING_CONTEXT ')]
expected = [dict(gp=gp, steps=135, positive_samples=23, max_pending=1, readonly_checks=137,
                 stepped_reset_delta=1, checked_reset_delta=1, pending_final=0, checked_gp=gp) for gp in (7, -1)]
assert contexts == expected
assert len(positive_text.splitlines()) == 6 and len(negative_text.splitlines()) == 4
expected_failure = 'FAILED pending_reads native_probe: pending getter did not observe an outstanding read'
assert negative_text.splitlines()[-1] == expected_failure
assert not any(line.startswith(('P06_PENDING_CONTEXT ', 'PASSED pending_reads')) for line in negative_text.splitlines())
for text in (positive_text, negative_text):
    libraries = [json.loads(line.split(' ', 1)[1]) for line in text.splitlines() if line.startswith('P06_PENDING_LIBRARY ')]
    assert libraries == [{'name': name, 'path': report['expected_libraries'][name]} for name in ('libsimx.so', 'libramulator.so', 'libramulator-vortex.so')]
for row in report['products']:
    assert identity(Path(row['path'])) == {k: row[k] for k in ('sha256', 'size_bytes')}
assert report['products'][0]['sha256'] != report['products'][1]['sha256']
probe_source = (PENDING / 'inputs/tests/unittest/pending_reads/main.cpp').read_bytes()
assert b'#ifdef P06_PENDING_FORCE_ZERO\n  (void)processor;\n  return 0;\n#else\n  return processor.pending_mem_reads();\n#endif' in probe_source
assert probe_source == (SOURCE / 'tests/unittest/pending_reads/main.cpp').read_bytes()
dram_source = (SOURCE / 'sim/common/dram_sim.cpp').read_bytes()
assert b'  ~RamulatorDram() override {\n    std::ofstream nullstream("ramulator.stats.log");\n' in dram_source
stats = identity(PENDING / 'ramulator.stats.log')
assert b'.nan' in (PENDING / 'ramulator.stats.log').read_bytes()
sys.path.insert(0, str(TRUSTED / 'ci/project'))
import p06_dependency_control_replay as controls
native = controls.native_replay
api = native.dependency_replay._archive_api()
reader_before = controls._reader_sources()
original_expected = {'report.json', *('inputs/' + name for name in set(controls.PROBE_HELPERS) | set(controls.probe.SOURCE_FILES)),
    *('logs/' + name + '.log' for name in ids), 'products/pending-reads-native', 'products/pending-reads-always-zero'}
assert set(packets_before['pending-probe']) - original_expected == {'ramulator.stats.log'}
assert original_expected <= set(packets_before['pending-probe'])
events = []
active = True

def audit(event, args):
    if not active:
        return
    if event in ('subprocess.Popen', 'os.system', 'os.exec', 'os.posix_spawn', 'socket.connect', 'ctypes.dlopen', 'os.mkdir', 'os.remove', 'os.rename'):
        events.append({'event': event})
        raise RuntimeError('semantic audit prohibited event: ' + event)
    if event == 'open':
        path, mode, flags = args
        if isinstance(path, (str, bytes)) and str(path).startswith((str(SOURCE), str(EVIDENCE))):
            events.append({'event': event, 'path': str(path)})
            raise RuntimeError('semantic reader attempted producer-path open')
        if isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_TRUNC | os.O_CREAT):
            events.append({'event': event, 'path': str(path)})
            raise RuntimeError('semantic reader attempted write')

sys.addaudithook(audit)
semantic_started = time.monotonic()
try:
    with api.ArchiveReader(ARCHIVE, PINS['archive']) as archive:
        outer = archive.view('')
        verified, context = native.verify_view(outer.subview('native-lifetime'), outer.subview('dependency-build'), api,
            expected_revision=REVISION, expected_receipt_sha256=PINS['dependency'], expected_native_report_sha256=PINS['native'],
            expected_source_manifest_sha256=PINS['source'])
        pending = controls.verify_probe_view(outer.subview('pending-probe'), native=context,
            expected_report_sha256=PINS['pending'], expected_native_report_sha256=PINS['native'])
        archive_receipt = {k: v for k, v in archive.receipt().items() if k != 'read_files'}
    assert controls._reader_sources() == reader_before
finally:
    active = False
semantic_duration = time.monotonic() - semantic_started
assert pending['outcome'] == 'pass' and pending['runtime_diagnostic']['sha256'] == stats['sha256']
assert pending['retained_files_checked'] == 43
assert verified['counts']['processes'] == 4 and verified['counts']['launches'] == 132
assert all(report[key] is False and pending[key] is False for key in controls.contract.FALSE_CLAIMS)
packets_after = {name: packet_snapshot(EVIDENCE / name) for name in packets_before}
assert packets_after == packets_before
assert {name: identity(Path(name)) for name in selected} == selected
assert identity(ARCHIVE)['sha256'] == PINS['archive']
assert not events
result = {'schema_version': 1, 'outcome': 'pass', 'scope': 'Actual pending control original, authored reader-side-output correction and unmocked semantic validation; independent correction review belongs to w10_a03',
    'observed_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'source_revision': REVISION,
    'trusted_reader_checkout': str(TRUSTED), 'trusted_reader_base_revision': git(TRUSTED, 'rev-parse', 'HEAD'),
    'pins': PINS, 'reader_profile': reader_before, 'original_packets_before_after': {name: summary(rows) for name, rows in packets_before.items()},
    'selected_current_inputs_before_after': summary(selected), 'selected_source_count': len(initial['sources']),
    'selected_build_count': len(initial['build']), 'selected_dependency_count': len(initial['dependencies']),
    'command_ids': ids, 'command_exit_codes': [row['exit_code'] for row in report['commands']],
    'exact_compile_difference': ['-DP06_PENDING_FORCE_ZERO=1', 'distinct output executable path'],
    'positive_contexts': contexts, 'zero_failure': expected_failure,
    'compiler': compiler, 'environment': report['environment'], 'products': report['products'],
    'runtime_diagnostic': dict(stats, path='ramulator.stats.log', interpreted=False, performance_evidence=False, qualification_evidence=False),
    'prior_reader_inventory': {'expected_files': len(original_expected), 'actual_files': len(packets_before['pending-probe']), 'sole_unconsumed_member': 'ramulator.stats.log'},
    'unmocked_pending_reader': pending, 'unmocked_native_context_counts': verified['counts'], 'archive_read': archive_receipt,
    'semantic_duration_seconds': semantic_duration, 'audit_duration_seconds': time.monotonic() - started,
    'prohibited_events': events, 'all_originals_unchanged': True, 'all_selected_current_inputs_unchanged': True,
    'retained_code_executed': False, 'all_seven_claims_false': True,
    'population_boundary': 'One positive scalar process observes two gp contexts; one separate always-zero process fails intentionally. Neither enters the four-process managed population.'}
OUT.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
print(json.dumps({'outcome': result['outcome'], 'audit_duration_seconds': result['audit_duration_seconds'],
                  'semantic_duration_seconds': semantic_duration, 'pending_files': pending['retained_files_checked'],
                  'prohibited_events': events, 'result_sha256': identity(OUT)['sha256'], 'result_bytes': OUT.stat().st_size}, indent=2))
