#!/usr/bin/env python3
"""Inert review of the two published lifetime build/product originals."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import struct
import subprocess
import sys
import time
from types import SimpleNamespace

sys.dont_write_bytecode = True
parser = argparse.ArgumentParser()
parser.add_argument('--repo', type=Path, default=Path('/tmp/ai-gpu-native-lifetime-dfd857'))
parser.add_argument('--packet', type=Path, default=Path('/tmp/ai-gpu-native-lifetime-dfd857-work/native-original/native-lifetime'))
parser.add_argument('--output', type=Path, default=Path('/tmp/ai-gpu-native-lifetime-dfd857-work/w07_a06-receipt.json'))
args = parser.parse_args()
REPO, PACKET = args.repo.resolve(), args.packet.resolve()
REVISION = 'b4127b19a004b5aebb8d52eab9ceda0da3ff4561'
started = time.monotonic()
checks = 0
verified_members = {}
used_source = {}

def check(condition, label):
    global checks
    checks += 1
    if not condition:
        raise AssertionError(label)

def sha(body):
    return hashlib.sha256(body).hexdigest()

def pairs(items):
    out = {}
    for name, value in items:
        check(name not in out, 'duplicate JSON key')
        out[name] = value
    return out

def decode(body):
    return json.loads(body, object_pairs_hook=pairs)

def member(name):
    path = PurePosixPath(name)
    check(not path.is_absolute() and '..' not in path.parts and '\\' not in name, 'contained original member')
    target = PACKET / path
    check(target.is_file() and not target.is_symlink(), 'regular original member')
    return target.read_bytes()

def verified(row, expected=None):
    check(type(row) is dict and set(row) == {'path', 'sha256', 'size_bytes'}, 'descriptor fields')
    if expected is not None:
        check(row['path'] == expected, 'expected descriptor path')
    body = member(row['path'])
    check(type(row['size_bytes']) is int and len(body) == row['size_bytes'] and sha(body) == row['sha256'], 'retained bytes match descriptor')
    verified_members[row['path']] = dict(row)
    return body

def committed(name):
    body = (REPO / name).read_bytes()
    original = subprocess.check_output(['git', 'show', REVISION + ':' + name], cwd=REPO)
    check(body == original, 'trusted source matches committed blob: ' + name)
    used_source[name] = {'path': name, 'sha256': sha(body), 'size_bytes': len(body)}
    return body

initial_modules = ('p06_managed_preflight_replay_build', 'p06_native_lifetime_contract',
                   'p06_managed_preflight_contract', 'p06_managed_preflight_execute')
for name in initial_modules:
    committed('ci/project/' + name + '.py')
sys.path.insert(0, str(REPO / 'ci/project'))
from p06_managed_preflight_replay_build import BuildReplayMixin
import p06_managed_preflight_build as build_records
import p06_managed_preflight_application_build as application_records
import p06_managed_preflight_contract as parent
import p06_managed_preflight_execute as producer
import p06_native_lifetime_contract as lifetime
import p06_replay as archive_helpers
from p03_execution_records import qualification_id

report = decode(member('report.json'))
check(report['expected_revision'] == REVISION and report['outcome'] == 'pass', 'selected successful original')
parent.false_claims(report)
check(report['unresolved_obligations'] == list(parent.UNRESOLVED_OBLIGATIONS), 'all broad obligations retained')
check([row['format'] for row in report['variants']] == ['fp16', 'bf16'], 'two exact original formats')
contract = parent.load_contract(REPO)
cases = parent.select_cases(contract, REPO)
check(decode(verified(report['preflight_contract_snapshot'])) == contract, 'parent contract reproduced')
check(report['preflight_contract_sha256'] == qualification_id(contract), 'parent contract digest')
active_contract = lifetime.contract()
check(decode(verified(report['contract_snapshot'])) == active_contract, 'lifetime descriptor reproduced')
check(report['contract_sha256'] == lifetime.contract_hash() == qualification_id(active_contract), 'lifetime descriptor digest')
check(decode(verified(report['fixture_snapshot'])) == cases, 'canonical selected fixtures')
snapshots = {}
for name in ('source', 'tools', 'dependencies'):
    before = decode(verified(report[name + '_before']))
    after = decode(verified(report[name + '_after']))
    check(before == after and report[name + '_stable'] is True, name + ' observation stability')
    snapshots[name] = before
source = snapshots['source']
check(source['checkout']['revision'] == REVISION, 'source checkout revision')
source_rows = {row['path']: row for row in source['files']}
retained_sources = {row['path']: row for row in report['retained_sources']}
check(len(source_rows) == len(source['files']) == 1004, 'complete unique source inventory')
check(len(retained_sources) == len(report['retained_sources']) == len(source_rows)
      and set(retained_sources) == {'artifacts/source/' + name for name in source_rows}, 'complete retained source inventory')
for name, row in source_rows.items():
    body = verified(retained_sources['artifacts/source/' + name])
    check(row == {'path': name, 'sha256': sha(body), 'size_bytes': len(body)}, 'every retained source joins frozen snapshot')
tool_rows = snapshots['tools']
check(set(tool_rows) == set(archive_helpers.HOST_TOOLS) | set(archive_helpers.TOOL_SUFFIXES)
      | {'executing_python'}, 'exact tool inventory')
for name, row in tool_rows.items():
    check(set(row) == {'path', 'resolved_path', 'sha256', 'size_bytes'}, 'tool descriptor fields')
    for key in ('path', 'resolved_path'):
        parent.absolute_path(row[key], 'recorded tool ' + key)
    check(type(row['size_bytes']) is int and 0 < row['size_bytes'] < 2**64
          and archive_helpers.SHA256.fullmatch(row['sha256']), 'tool identity observation')
    if name in archive_helpers.TOOL_SUFFIXES:
        check(row['path'] == str(PurePosixPath(report['paths']['tools']) / archive_helpers.TOOL_SUFFIXES[name]),
              'selected original tool path')
for key in ('resolved_path', 'sha256', 'size_bytes'):
    check(tool_rows['python3'][key] == tool_rows['executing_python'][key], 'executing interpreter identity')

def source_body(name):
    value = verified(retained_sources['artifacts/source/' + name])
    check(source_rows[name] == {'path': name, 'sha256': sha(value), 'size_bytes': len(value)}, 'source snapshot join')
    check(committed(name) == value, 'retained source is trusted committed input')
    return value

for row in report['loaded_helpers']:
    check(source_body(row['path']) == (REPO / row['path']).read_bytes(), 'original helper source join')
dependency_payloads = {}
check(len(snapshots['dependencies']) == 3 and {row['path'] for row in snapshots['dependencies']}
      == set(archive_helpers.DEPENDENCIES), 'exact reused dependency inventory')
for row in report['retained_dependency_payloads']:
    body = verified(row)
    name = row['path'].removeprefix('artifacts/dependencies/')
    check({'path': name, 'sha256': sha(body), 'size_bytes': len(body)} in snapshots['dependencies'], 'dependency product join')
    dependency_payloads[name] = row
check(set(dependency_payloads) == set(archive_helpers.DEPENDENCIES), 'complete reused dependency payloads')

commands = {row['id']: row for row in report['commands']}
check(len(commands) == len(report['commands']) == 35, 'unique managed command inventory')

def elf(body):
    check(body[:6] == b'\x7fELF\x02\x01', 'ELF64 little-endian product')
    check(len(body) >= 64, 'ELF header bounds')
    machine = struct.unpack_from('<H', body, 18)[0]
    shoff = struct.unpack_from('<Q', body, 40)[0]
    entsize, count, string_index = struct.unpack_from('<HHH', body, 58)
    check(entsize == 64 and shoff + count * entsize <= len(body) and string_index < count, 'ELF section table bounds')
    sections = [struct.unpack_from('<IIQQQQIIQQ', body, shoff + i * entsize) for i in range(count)]
    def section_bytes(index):
        row = sections[index]
        check(row[4] + row[5] <= len(body), 'ELF section byte bounds')
        return body[row[4]:row[4] + row[5]]
    strings = section_bytes(string_index)
    def cstr(table, offset):
        check(offset < len(table), 'ELF string offset')
        end = table.find(b'\x00', offset)
        check(end >= 0, 'ELF string terminator')
        return table[offset:end].decode('utf-8')
    by_name = {cstr(strings, row[0]): i for i, row in enumerate(sections)}
    result = {'machine': machine, 'needed': [], 'rpaths': [], 'defined_dynamic_symbols': []}
    if '.dynamic' in by_name:
        index = by_name['.dynamic']
        data, table = section_bytes(index), section_bytes(sections[index][6])
        check(len(data) % 16 == 0, 'ELF dynamic entry size')
        for offset in range(0, len(data), 16):
            tag, value = struct.unpack_from('<qQ', data, offset)
            if tag == 1:
                result['needed'].append(cstr(table, value))
            elif tag in (15, 29):
                result['rpaths'].append(cstr(table, value))
    if '.dynsym' in by_name:
        index = by_name['.dynsym']
        data, table = section_bytes(index), section_bytes(sections[index][6])
        check(len(data) % 24 == 0, 'ELF dynamic symbol size')
        for offset in range(0, len(data), 24):
            name, _, _, defined, _, _ = struct.unpack_from('<IBBHQQ', data, offset)
            if name and defined:
                result['defined_dynamic_symbols'].append(cstr(table, name))
    return result

class Review(BuildReplayMixin):
    def __init__(self, variant):
        self.variant, self.report = variant, report
        self.variant_id, self.fmt = variant['id'], variant['format']
        self.build = PurePosixPath(variant['build_dir'])
        self.paths = {key: PurePosixPath(value) if value is not None else None for key, value in report['paths'].items()}
        self.env, self.tools = report['environment'], snapshots['tools']
        self.source, self.sources = source, source_rows
        self.dependencies = snapshots['dependencies']
        self.case = next(case for case in cases if case['format'] == self.fmt)
        self.limits = {'jobs': 2, 'configure_timeout_seconds': 120, 'build_timeout_seconds': 1800}
        self.api = SimpleNamespace(MEMBER_BYTES=64 * 1024**2)
        self.verified = verified
        self.source_body = source_body
        self.command_ids = []

    def inventory(self, rows, label, expected):
        result = {}
        for row in rows:
            check(set(row) == {'path', 'sha256', 'size_bytes'}, label + ' descriptor')
            check(row['path'] not in result and type(row['size_bytes']) is int and row['size_bytes'] > 0, label + ' inventory uniqueness')
            check(len(row['sha256']) == 64 and all(c in '0123456789abcdef' for c in row['sha256']), label + ' digest')
            result[row['path']] = row
        check(set(result) == set(expected), label + ' exact inventory')
        return result

    def payload(self, row, expected):
        return verified(row, expected)

    def build_body(self, name):
        return verified(self.stages['frozen'][name])

    def command(self, identifier, argv, cwd, environment, timeout, read=False):
        row = commands[identifier]
        check(row['argv'] == list(map(str, argv)), identifier + ' exact argv')
        check(row['cwd'] == str(cwd) and row['environment'] == environment, identifier + ' execution context')
        check(row['timeout_seconds'] == timeout and row['native_process'] is False, identifier + ' command scope')
        check(row['outcome'] == 'pass' and row['exit_code'] == 0 and row['reason'] is None
              and row['process_started'] is True and row['cleanup_complete'] is True, identifier + ' successful command receipt')
        check(0 <= row['peak_rss_bytes'] <= report['budget']['max_rss_bytes'], identifier + ' resource receipt')
        body = verified({'path': row['log'], 'sha256': row['log_sha256'], 'size_bytes': row['log_size_bytes']})
        self.command_ids.append(identifier)
        return body.decode('utf-8'), row

    def reconstruct_binding(self):
        binding = {'contract_id': lifetime.CONTRACT_ID, 'contract_sha256': lifetime.contract_hash(),
            'source': source, 'loaded_helpers': report['loaded_helpers'], 'format': self.fmt,
            'backend': 'simx', 'case': self.case, 'corpus': report['corpus'],
            'profile_sha256': producer.PROFILE_SHA256, 'kernel_source_sha256': producer.KERNEL_SHA256,
            'warm_contract_sha256': parent.WARM_CONTRACT_SHA256, 'compiler_records': self.compiler,
            'model_build_records': self.model_build, 'host_build_records': self.host_build,
            'effective_headers': self.effective, 'generated_identity': self.variant['generated_identity'],
            'artifacts': self.artifacts, 'tools': self.tools, 'dependencies': self.dependencies,
            'expected_loaded_libraries': self.libraries, 'simulation_workers': 1,
            'performance_environment': {'PERF': '1'}, 'unresolved_obligations': list(parent.UNRESOLVED_OBLIGATIONS),
            **dict.fromkeys(parent.FALSE_CLAIMS, False), 'lifetime_contract': active_contract,
            'preflight_contract_sha256': qualification_id(contract)}
        check(decode(verified(self.variant['binding'])) == binding, 'complete reconstructed lifetime build binding')
        check(qualification_id(binding) == self.variant['build_binding_sha256'], 'canonical build identity')
        return binding

results = []
for variant in report['variants']:
    review = Review(variant)
    review.generated()
    review.compiler_commands()
    binding = review.reconstruct_binding()
    check(review.model_build['model_translation_units'] == 43 and review.model_build['backend_translation_units'] == 4
          and review.model_build['link_count'] == 2, 'exact fresh model/backend inventory')
    check(review.model_build['dependency_compilation_provenance_verified'] is False, 'unresolved dependency provenance retained')
    for name in (build_records.MODEL_SOURCES + build_records.BACKEND_SOURCES + build_records.APP_SOURCES
                 + application_records.STUB_SOURCES
                 + tuple('sw/kernel/src/' + name for name in application_records.KERNEL_SOURCES)):
        source_body(name)
    objects = [name for name in review.frozen if name.endswith('.o')]
    check(len(objects) == 43, 'recorded model object hash inventory')
    product_rows = []
    elf_data = {}
    for name in producer.BINARY_FILES:
        row = review.binary_payloads['artifacts/' + variant['id'] + '/binaries/' + name]
        body = verified(row)
        product = dict(row)
        if body.startswith(b'\x7fELF'):
            parsed = elf(body)
            check(parsed['machine'] == (243 if name.endswith('kernel.elf') else 62), 'product architecture')
            elf_data[name] = parsed
            product['elf'] = {key: value for key, value in parsed.items() if key != 'defined_dynamic_symbols'}
        elif name.endswith('.a'):
            check(body.startswith(b'!<arch>\n'), 'retained kernel archive framing')
        product_rows.append(product)
    model = elf_data['sw/runtime/libsimx.so']
    check('_ZNK6vortex9Processor17pending_mem_readsEv' in model['defined_dynamic_symbols'], 'actual model exports pending accessor')
    check({'libramulator.so', 'libramulator-vortex.so'} <= set(model['needed']), 'model dynamic dependency links')
    check('libsimx.so' in elf_data['sw/runtime/libvortex-simx.so']['needed'], 'wrapped backend needs selected model')
    check({'libvortex.so', 'libvortex-simx.so'} <= set(elf_data[parent.APP + '/ai_counter_preflight']['needed']), 'native application runtime dependencies')
    process_ids = []
    for process in report['processes']:
        if process['format'] != review.fmt:
            continue
        process_binding = decode(verified(process['binding']))
        check(process_binding['build'] == binding and process_binding['build_binding_sha256'] == qualification_id(binding), 'process binds reviewed build')
        check(qualification_id(process_binding) == process['execution_binding_sha256'], 'process binding digest')
        libraries = process['observation']['witness']['loaded_libraries']
        check({row['name']: row['path'] for row in libraries} == review.libraries, 'actual observed library path joins')
        process_ids.append(process['id'])
    check(process_ids == variant['process_ids'] and len(process_ids) == 2, 'both policies use one reviewed format build')
    results.append({'format': review.fmt, 'build_binding_sha256': qualification_id(binding),
        'checked_command_ids': review.command_ids, 'backend_graph': review.backend_build,
        'application_graph': review.application_build, 'generated_headers': review.generated_headers,
        'generated_flags': review.generated_flags, 'model_object_hashes_observed': len(objects),
        'model_object_bytes_retained': False, 'compiler_roles': [row['role'] for row in review.compiler],
        'stub_source_files': [used_source[name] for name in application_records.STUB_SOURCES],
        'products': product_rows, 'process_ids': process_ids, 'loaded_libraries': review.libraries})

for module in tuple(sys.modules.values()):
    path = getattr(module, '__file__', None)
    if path and Path(path).suffix == '.py':
        absolute = Path(path).resolve()
        if absolute.is_relative_to(REPO / 'ci'):
            committed(absolute.relative_to(REPO).as_posix())
for name, row in used_source.items():
    check(sha((REPO / name).read_bytes()) == row['sha256'], 'trusted source remained stable')
for row in tuple(verified_members.values()):
    verified(row)
result = {'scope': 'independent inert build and retained product review; no new native execution',
    'revision': REVISION, 'run_id': 45130300651, 'outcome': 'pass', 'checks': checks,
    'seconds': time.monotonic() - started, 'retained_code_executed': False,
    'retained_commands_executed': False, 'retained_binaries_executed': False,
    'lifetime_contract_sha256': report['contract_sha256'],
    'parent_contract_sha256': report['preflight_contract_sha256'],
    'snapshot_descriptors': {name: report[name + '_before'] for name in ('source', 'tools', 'dependencies')},
    'source_payloads_rehashed': len(source_rows), 'recorded_tool_identity_count': len(tool_rows),
    'variants': results, 'verified_member_count': len(verified_members),
    'trusted_source_files': sorted(used_source.values(), key=lambda row: row['path']),
    'dependencies': snapshots['dependencies'], 'dependency_payloads': dependency_payloads,
    'limitations': ['The live producer validates its final host command; this review additionally applies the existing inert 30-command application graph, including the 14-source stub compile/link.',
        '43 model object identities per format are recorded and stable; individual model object bytes were not retained. Final products are retained and rehashed.',
        'The three dependency products remain cached/reused inputs with no fresh source-to-compilation provenance.',
        'Recorded tool identities are stable observations; this archive does not retain all tool payloads, support files, system headers or system libraries.',
        'This consistency review relies on the separately verified GitHub original identity; it does not authenticate an arbitrary producer or defeat malicious concurrent replacement.',
        'All seven qualification/readiness/acceptance claims and all three broad obligations remain unchanged.']}
args.output.write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({'outcome': result['outcome'], 'checks': checks, 'seconds': result['seconds'],
    'verified_members': len(verified_members), 'trusted_sources': len(used_source),
    'formats': [row['format'] for row in results], 'receipt': str(args.output)}))
