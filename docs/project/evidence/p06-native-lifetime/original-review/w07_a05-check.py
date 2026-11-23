#!/usr/bin/env python3
"""Inert independent review of the retained native pending-read probe."""
import argparse
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import struct
import subprocess
import sys
import time
import zipfile

sys.dont_write_bytecode = True
REVISION = 'b4127b19a004b5aebb8d52eab9ceda0da3ff4561'
TREE = 'bd37fb53ab1c34dfebc2ac8805abff5877735fc4'
ARCHIVE_SHA = '3d4879f73c197352689d65feb56e73f537701fc1411e55bf53c92b1b41e13db3'
NATIVE_SOURCE = Path('/home/runner/work/AI-GPU/AI-GPU')
NATIVE_BUILD = Path('/home/runner/work/_temp/p06-native-lifetime/work/simx-fp16')
NATIVE_OUTPUT = Path('/home/runner/work/_temp/p06-native-lifetime/evidence/pending-probe')
GETTER = '_ZNK6vortex9Processor17pending_mem_readsEv'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path('/tmp/ai-gpu-native-lifetime-dfd857'))
    parser.add_argument('--original', type=Path, default=Path('/tmp/ai-gpu-native-lifetime-dfd857-work/native-original'))
    parser.add_argument('--archive', type=Path, default=Path('/tmp/ai-gpu-native-lifetime-dfd857-work/native-original.zip'))
    parser.add_argument('--output', type=Path, default=Path('/tmp/ai-gpu-native-lifetime-dfd857-work/w07_a05-receipt.json'))
    args = parser.parse_args()
    started = time.monotonic()
    count = 0

    def check(value, label):
        nonlocal count
        count += 1
        if not value:
            raise AssertionError(label)

    def identity(data):
        return {'sha256': hashlib.sha256(data).hexdigest(), 'size_bytes': len(data)}

    def matches(data, row, label):
        check(identity(data) == {k: row[k] for k in ('sha256', 'size_bytes')}, label)

    def relative(name):
        path = PurePosixPath(name)
        check(not path.is_absolute() and '..' not in path.parts and '\\' not in name,
              'canonical retained relative path')
        return path

    archive_identity = identity(args.archive.read_bytes())
    check(archive_identity == {'sha256': ARCHIVE_SHA, 'size_bytes': 9086055}, 'original ZIP identity')
    archive = zipfile.ZipFile(args.archive)
    touched = {}

    def read(path):
        path = path.relative_to(args.original).as_posix()
        data = (args.original / relative(path)).read_bytes()
        check(data == archive.read(path), 'extracted bytes equal original ZIP: ' + path)
        touched[path] = identity(data)
        return data

    probe_dir = args.original / 'pending-probe'
    managed_dir = args.original / 'native-lifetime'
    probe_report_bytes = read(probe_dir / 'report.json')
    managed_report_bytes = read(managed_dir / 'report.json')
    report = json.loads(probe_report_bytes)
    managed = json.loads(managed_report_bytes)
    initial = report['inputs_before']
    check(initial == report['inputs_after'], 'all probe inputs stable before/after')
    check(report['state'] == 'finished' and report['outcome'] == 'pass'
          and report['reason'] is None and report['failures'] == [], 'completed probe result')
    check(report['contract_id'] == 'p06-pending-read-probe-v1'
          and report['expected_revision'] == REVISION and report['format'] == 'fp16', 'probe identity')
    check(report['native_execution'] == 'run' and report['native_probe_passed'] is True
          and report['zero_mutation_rejected'] is True, 'both native probe outcomes')
    check(managed['contract_id'] == 'p06-managed-counter-lifetime-v1'
          and managed['expected_revision'] == REVISION and managed['outcome'] == 'pass'
          and managed['native_lifetime_passed'] is True, 'selected managed original')

    git_records = subprocess.check_output(['git', 'ls-tree', '-r', '-z', REVISION], cwd=args.repo)
    tracked = {}
    for row in git_records.split(b'\0'):
        if not row:
            continue
        header, path = row.split(b'\t', 1)
        mode, kind, sha = header.decode().split()
        if kind == 'blob':
            tracked[path.decode()] = sha

    captured_source = {}
    committed_sources = {}
    local_before = {}
    for row in initial['sources']:
        name = row['path']
        check(name not in captured_source, 'unique source descriptor')
        local_payload = probe_dir / 'inputs' / relative(name)
        if not local_payload.is_file():
            local_payload = managed_dir / 'artifacts/source' / relative(name)
        data = read(local_payload)
        matches(data, row, 'captured source identity: ' + name)
        captured_source[name] = identity(data)
        if name in tracked:
            blob = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
            check(blob == tracked[name], 'captured source equals committed blob: ' + name)
            current = (args.repo / name).read_bytes()
            check(current == data, 'current trusted source equals captured source: ' + name)
            committed_sources[name] = dict(identity(current), git_blob=blob)
            local_before[name] = identity(current)
    check(len(captured_source) == 1006 and len(committed_sources) == 813,
          'complete source inventory and root/dependency distinction')

    sys.path.insert(0, str(args.repo / 'ci/project'))
    import p06_pending_probe as trusted_probe
    import p06_managed_preflight_execute as trusted_preflight
    import p06_managed_preflight_contract as contract
    check(Path(trusted_probe.__file__).resolve() == args.repo / 'ci/project/p06_pending_probe.py',
          'trusted current probe parser path')
    check(trusted_probe.bounded_json(probe_dir / 'report.json') == report, 'strict probe JSON parsing')
    check(trusted_probe.bounded_json(managed_dir / 'report.json') == managed, 'strict managed JSON parsing')
    for module in tuple(sys.modules.values()):
        name = getattr(module, '__file__', None)
        if name:
            path = Path(name).resolve()
            if path.is_relative_to(args.repo / 'ci/project') and path.suffix == '.py':
                check(path.relative_to(args.repo).as_posix() in committed_sources,
                      'imported trusted helper is committed and captured')
    for value in (report, managed):
        for key in contract.FALSE_CLAIMS:
            check(value[key] is False, 'false claim: ' + key)
    check(managed['unresolved_obligations'] == list(contract.UNRESOLVED_OBLIGATIONS),
          'unresolved obligations retained')

    variant = next(v for v in managed['variants'] if v['id'] == 'simx-fp16')
    check(variant['build_dir'] == str(NATIVE_BUILD) and variant['format'] == 'fp16'
          and variant['backend'] == 'simx' and variant['outcome'] == 'pass', 'fixed model selection')
    check(initial['checkout']['revision'] == REVISION and initial['checkout']['tree'] == TREE
          and initial['checkout']['dirty'] is False and initial['checkout']['outcome'] == 'pass',
          'clean original source revision/tree')
    check(initial['build'] == variant['artifacts_before'] == variant['artifacts_after'],
          'same 75 build input identities before/after all processes and probe')
    check(len(initial['build']) == 75, 'build input population')
    matches(managed_report_bytes, initial['managed_report'], 'probe binds exact managed report bytes')
    check(initial['managed_report']['path'] == initial['managed_report']['resolved_path']
          == str(NATIVE_OUTPUT.parent / 'native-lifetime/report.json'), 'fixed managed report path')

    snapshots = {}
    for row in initial['managed_snapshots']:
        data = read(managed_dir / relative(row['path']))
        matches(data, row, 'managed snapshot identity')
        snapshots[row['path']] = json.loads(data)
    check(set(snapshots) == {'snapshots/source-before.json', 'snapshots/tools-before.json',
                            'snapshots/dependencies-before.json'}, 'fixed snapshot inventory')
    check(initial['checkout'] == snapshots['snapshots/source-before.json']['checkout'],
          'same managed source checkout')
    check(initial['dependencies'] == snapshots['snapshots/dependencies-before.json'], 'same dependencies')
    tools = snapshots['snapshots/tools-before.json']
    check(initial['compiler'] == tools['g++'], 'compiler identity joins managed build')
    check(initial['compiler']['path'] == '/usr/bin/g++'
          and initial['compiler']['resolved_path'] == '/usr/bin/x86_64-linux-gnu-g++-11',
          'native compiler selection')

    binding_bytes = read(managed_dir / variant['binding']['path'])
    matches(binding_bytes, variant['binding'], 'managed build binding bytes')
    binding = json.loads(binding_bytes)
    check(trusted_preflight.qualification_id(binding) == variant['build_binding_sha256']
          == report['managed_build_binding_sha256'], 'canonical build binding digest')
    check(binding['artifacts'] == initial['build'] and binding['dependencies'] == initial['dependencies']
          and binding['tools']['g++'] == initial['compiler'], 'build binding input joins')
    check(binding['model_build_records']['dependency_compilation_provenance_verified'] is False,
          'dependency build provenance remains unresolved')

    build_descriptors = {r['path']: r for r in initial['build']}
    rehashed_build_paths = set()
    frozen_root = 'artifacts/simx-fp16/frozen/'
    for row in variant['retained_builds'][-1]['files']:
        check(row['path'].startswith(frozen_root), 'fixed frozen input prefix')
        name = row['path'][len(frozen_root):]
        data = read(managed_dir / row['path'])
        matches(data, row, 'frozen retained build identity')
        matches(data, build_descriptors[name], 'probe build joins retained generated input')
        rehashed_build_paths.add(name)
    binary_root = 'artifacts/simx-fp16/binaries/'
    for row in variant['retained_binary_payloads']:
        check(row['path'].startswith(binary_root), 'fixed binary input prefix')
        name = row['path'][len(binary_root):]
        data = read(managed_dir / row['path'])
        matches(data, row, 'retained model binary identity')
        matches(data, build_descriptors[name], 'probe input joins retained model binary')
        rehashed_build_paths.add(name)
    unrehashed_objects = sorted(set(build_descriptors) - rehashed_build_paths)
    check(len(unrehashed_objects) == 43 and all(p.endswith('.o') for p in unrehashed_objects),
          'unretained object payload distinction')

    for row in initial['dependencies']:
        data = read(managed_dir / 'artifacts/dependencies' / relative(row['path']))
        matches(data, row, 'actual reused dependency payload identity')
    expected_libraries = {
        'libsimx.so': str(NATIVE_BUILD / 'sw/runtime/libsimx.so'),
        'libramulator.so': str(NATIVE_SOURCE / 'third_party/ramulator/libramulator.so'),
        'libramulator-vortex.so': str(NATIVE_SOURCE / 'third_party/ramulator_ext/libramulator-vortex.so'),
    }
    check(report['expected_libraries'] == expected_libraries
          == {k: variant['expected_loaded_libraries'][k] for k in expected_libraries},
          'fixed actual library path joins')
    check(report['environment'] == {
        'PATH': ':'.join([str(Path(tools['executing_python']['path']).parent), '/usr/bin', '/bin']),
        'LANG': 'C', 'LC_ALL': 'C', 'TZ': 'UTC', 'TMPDIR': str(NATIVE_OUTPUT / 'tmp'),
        'THREADS': '1', 'CCACHE_DISABLE': '1', 'OBJCACHE': '', 'PYTHONDONTWRITEBYTECODE': '1',
        'PERF': '1', 'LD_LIBRARY_PATH': ':'.join([str(NATIVE_BUILD / 'sw/runtime'),
            str(NATIVE_SOURCE / 'third_party/ramulator'), str(NATIVE_SOURCE / 'third_party/ramulator_ext')]),
    }, 'whitelisted environment and loader routing')

    frozen = managed_dir / frozen_root
    flags, records = trusted_probe.probe_flags(
        (frozen / 'sw/runtime/simx_rt_config.stamp').read_text(),
        (frozen / 'sw/runtime/simx_config.stamp').read_text(),
        (frozen / 'tests/regression/ai_counter_preflight/config.stamp').read_text(),
        source=NATIVE_SOURCE, build=NATIVE_BUILD, fmt='fp16')
    check(flags == report['probe_flags'], 'rederived validated original flags')
    check(records == report['compiler_records'] == variant['compiler_records'], 'independent compiler records')
    check(all(x not in flags for x in ['-MMD', '-MP', '-MF', '-DP06_PENDING_FORCE_ZERO=1']),
          'probe strips only dependency output flags; no mutation in baseline flags')
    ids = ['compiler-version', 'compile-native', 'run-native', 'compile-always-zero', 'run-always-zero']
    check([c['id'] for c in report['commands']] == ids, 'exact five original commands, no retry')
    check(report['budget'] == trusted_probe.BUDGET, 'unchanged resource budgets')
    commands = {c['id']: c for c in report['commands']}
    logs = {}
    for command in report['commands']:
        data = read(probe_dir / relative(command['log']))
        check(identity(data) == {'sha256': command['log_sha256'], 'size_bytes': command['log_size_bytes']},
              'raw command log identity: ' + command['id'])
        check(command['process_started'] is True and command['cleanup_complete'] is True,
              'native command start and complete cleanup')
        check(command['cwd'] == str(NATIVE_OUTPUT), 'fixed command working directory')
        expected_failure = command['id'] == 'run-always-zero'
        check(command['exit_code'] == (1 if expected_failure else 0)
              and command['outcome'] == ('fail' if expected_failure else 'pass')
              and command['reason'] == ('nonzero_exit' if expected_failure else None),
              'exact command outcome: ' + command['id'])
        check(math.isfinite(command['duration_seconds']) and 0 <= command['duration_seconds']
              <= (180 if command['id'].startswith('run-') else 120), 'bounded command duration')
        check(0 <= command['peak_rss_bytes'] <= report['budget']['max_rss_bytes']
              and len(data) <= report['budget']['max_log_bytes'], 'observed RSS/log bounds')
        logs[command['id']] = data.decode('utf-8')
    check(commands['compiler-version']['argv'] == ['/usr/bin/g++', '--version'], 'compiler version command')
    check(logs['compiler-version'] == (managed_dir / 'logs/version-gpp.log').read_text(),
          'same original compiler version output')
    check(logs['compiler-version'].splitlines()[0] == 'g++ (Ubuntu 11.4.0-1ubuntu1~22.04.3) 11.4.0',
          'recorded native compiler version')
    check(logs['compile-native'] == logs['compile-always-zero'] == '', 'both original compiles warning-free')
    check('P06_PENDING_FORCE_ZERO' not in json.dumps(managed['commands']), 'mutation absent from managed commands')
    check('P06_PENDING_FORCE_ZERO' not in json.dumps(variant['model_build_records']),
          'mutation absent from model compilation/link inventory')

    def dynamic_symbols(data):
        check(data[:6] == b'\x7fELF\x02\x01', 'retained ELF64 little-endian image')
        header = struct.unpack_from('<16sHHIQQQIHHHHHH', data)
        check(header[2] == 62, 'host x86-64 ELF machine')
        sections = [struct.unpack_from('<IIQQQQIIQQ', data, header[6] + i * header[11])
                    for i in range(header[12])]
        result = {}
        for section in sections:
            if section[1] != 11:
                continue
            strings = sections[section[6]]
            names = data[strings[4]:strings[4] + strings[5]]
            for offset in range(section[4], section[4] + section[5], section[9]):
                entry = struct.unpack_from('<IBBHQQ', data, offset)
                name = names[entry[0]:].split(b'\0', 1)[0].decode()
                if name:
                    result[name] = {'section': entry[3], 'binding': entry[1] >> 4,
                                    'type': entry[1] & 15, 'size': entry[5]}
        return result

    products = {}
    for mode, defines in [('native', []), ('always-zero', ['-DP06_PENDING_FORCE_ZERO=1'])]:
        target = str(NATIVE_OUTPUT / 'products' / ('pending-reads-' + mode))
        expected_argv = ['/usr/bin/g++', *flags, *defines, str(NATIVE_SOURCE / trusted_probe.PROBE_SOURCE),
            '-L' + str(NATIVE_BUILD / 'sw/runtime'), '-Wl,-rpath,' + str(NATIVE_BUILD / 'sw/runtime'),
            '-lsimx', '-pthread', '-ldl', '-o', target]
        check(commands['compile-' + mode]['argv'] == expected_argv,
              'exact single-TU compile/link command: ' + mode)
        check(commands['run-' + mode]['argv'] == [target], 'exact standalone executable command')
        rows = [p for p in report['products'] if p['mode'] == mode]
        check(len(rows) == 1 and rows[0]['path'] == rows[0]['resolved_path'] == target,
              'fixed retained product identity')
        row = rows[0]
        data = read(probe_dir / 'products' / ('pending-reads-' + mode))
        matches(data, row, 'actual probe executable bytes: ' + mode)
        observation = trusted_probe.verify_output(logs['run-' + mode], expected_libraries,
                                                  zero_control=mode == 'always-zero')
        check(observation == row['observation'], 'raw probe observation reproduces report exactly')
        symbols = dynamic_symbols(data)
        products[mode] = {'identity': identity(data), 'observation': observation,
                          'getter_dynamic_symbol': symbols.get(GETTER)}
    check(len(report['products']) == 2, 'exact two probe executable products')
    native_observation = products['native']['observation']
    check(native_observation['contexts'] == [
        {'gp': gp, 'checked_gp': gp, 'steps': 135, 'positive_samples': 23, 'max_pending': 1,
         'readonly_checks': 137, 'stepped_reset_delta': 1, 'checked_reset_delta': 1, 'pending_final': 0}
        for gp in (7, -1)], 'exact actual native context observations')
    check(products['native']['getter_dynamic_symbol']['section'] == 0,
          'native executable dynamically calls actual model getter')
    check(products['always-zero']['getter_dynamic_symbol'] is None,
          'constant-zero translation unit has no getter symbol reference')
    model_data = read(managed_dir / binary_root / 'sw/runtime/libsimx.so')
    model_getter = dynamic_symbols(model_data)[GETTER]
    check(model_getter['section'] != 0, 'retained model exports actual getter')
    check(managed['completed_counts'] == contract.COMPLETE_COUNTS
          and len(managed['processes']) == 4, 'probe excluded from four-process matrix counts')

    probe_files = sorted(p.relative_to(args.original).as_posix() for p in probe_dir.rglob('*') if p.is_file())
    archive_probe_files = sorted(name for name in archive.namelist()
                                 if name.startswith('pending-probe/') and not name.endswith('/'))
    check(probe_files == archive_probe_files, 'complete original probe file inventory')
    for name in probe_files:
        read(args.original / name)
    for name, expected in local_before.items():
        check(identity((args.repo / name).read_bytes()) == expected, 'trusted source stable after review')
    for name, expected in touched.items():
        check(identity((args.original / name).read_bytes()) == expected, 'retained data stable after review')
    check(identity(args.archive.read_bytes()) == archive_identity, 'original ZIP unchanged after review')

    receipt = {
        'scope': 'inert independent review of actual hosted pending-read probe original',
        'outcome': 'pass', 'review_native_execution': 'not_run', 'retained_code_executed': False,
        'source_revision': REVISION, 'source_tree': TREE, 'run_id': 45130300651,
        'artifact_id': 14798140556, 'archive': archive_identity,
        'probe_report': identity(probe_report_bytes), 'managed_report': identity(managed_report_bytes),
        'assertions': count, 'seconds': round(time.monotonic() - started, 6),
        'retained_probe_files': len(probe_files), 'retained_files_rehashed': len(touched),
        'captured_sources_rehashed': len(captured_source), 'committed_sources': committed_sources,
        'dependency_headers_hash_matched_only': len(captured_source) - len(committed_sources),
        'build_input_identities': len(initial['build']), 'build_payloads_rehashed': len(rehashed_build_paths),
        'object_payloads_not_retained': unrehashed_objects,
        'compiler': initial['compiler'], 'compiler_version': logs['compiler-version'].splitlines()[0],
        'probe_flags': flags, 'managed_build_binding_sha256': report['managed_build_binding_sha256'],
        'library_paths': expected_libraries, 'model_library': identity(model_data),
        'model_getter_dynamic_symbol': model_getter, 'products': products,
        'commands': [{k: c[k] for k in ('id', 'outcome', 'exit_code', 'reason', 'process_started',
                     'cleanup_complete', 'log_sha256', 'log_size_bytes', 'duration_seconds', 'peak_rss_bytes')}
                     for c in report['commands']],
        'qualification_claimed': False,
        'limitations': [
            'The checker never executes retained code, commands or ELF images; this is not a new native run.',
            'Compiler executable bytes are not retained here; its recorded identity joins the managed tool snapshots and original version log.',
            'Forty-three model object payloads are not retained; their recorded identities join the stable build inputs, while final libraries and binaries are rehashed.',
            'Dependency headers and products are rehashed; fresh dependency source/compile/link provenance remains unresolved.',
            'Before/after identities do not prove absence of malicious transient replacement.',
            'The probe is separate from the 4 managed processes / 132 launches / 4224 words and establishes no full counter, warm, RTL or phase qualification.',
        ],
    }
    args.output.write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({k: receipt[k] for k in ('outcome', 'assertions', 'seconds', 'retained_probe_files',
                     'retained_files_rehashed', 'captured_sources_rehashed', 'build_payloads_rehashed')}))


if __name__ == '__main__':
    main()
