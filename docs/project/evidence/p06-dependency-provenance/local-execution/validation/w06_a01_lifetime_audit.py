import ast
import datetime
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path('/workspace/p06-local-run-source-02')
OUT = Path('/workspace/scratch/279b6658611e/validation/w06_a01-lifetime-audit.json')
BASE = '849469e1111870fbcfe0346afd33b284a5a1edd8'
REVISION = 'ac2f2ae761c3644103278f7a41cc6ae7db734a86'
FILES = (
    'tests/regression/ai_counter_preflight/main.cpp',
    'tests/regression/ai_counter_preflight/hooks.cpp',
    'tests/regression/ai_counter_preflight/hooks.h',
    'tests/regression/ai_counter_preflight/Makefile',
    'tests/regression/ai_warm_workspace/main.cpp',
    'tests/regression/ai_warm_workspace/observer.cpp',
    'tests/regression/ai_bench_common/counters.h',
    'tests/regression/sgemm_tcu/p02_fixtures.h',
    'sw/kernel/ai/matmul.cpp',
    'sw/common/ai_matmul_args.h',
    'sw/common/ai_matmul_profile.h',
    'ci/project/fixtures/p02_layout_v1.json',
    'ci/project/p06_warm_contract.py',
    'ci/project/p06_warm_contract.json',
    'ci/project/p06_warm_records.py',
    'ci/project/p06_managed_preflight_contract.py',
    'ci/project/p06_managed_preflight_records.py',
    'ci/project/p06_managed_preflight_execute.py',
    'ci/project/p06_native_lifetime_contract.py',
    'ci/project/p06_native_lifetime_records.py',
    'ci/project/p06_dependency_lifetime_execute.py',
    'ci/project/p06_dependency_native_replay.py',
    'ci/project/p06_dependency_local_execute.py',
)

def digest(body):
    return hashlib.sha256(body).hexdigest()

def literal(path, name):
    tree = ast.parse((ROOT / path).read_text())
    nodes = [n.value for n in tree.body if isinstance(n, ast.Assign)
             and any(isinstance(t, ast.Name) and t.id == name for t in n.targets)]
    assert len(nodes) == 1, name
    return ast.literal_eval(nodes[0])

def const_cpp(body, name):
    values = re.findall(r'constexpr size_t ' + re.escape(name) + r'\s*=\s*(\d+);', body)
    assert len(values) == 1, name
    return int(values[0])

before = {name: {'sha256': digest((ROOT / name).read_bytes()),
                 'size_bytes': (ROOT / name).stat().st_size} for name in FILES}
revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip()
assert revision == REVISION
warm = (ROOT / 'tests/regression/ai_warm_workspace/main.cpp').read_text()
main = (ROOT / 'tests/regression/ai_counter_preflight/main.cpp').read_text()
formats = literal('ci/project/p06_warm_contract.py', 'FORMATS')
policies = literal('ci/project/p06_warm_contract.py', 'POLICIES')
operations, words = const_cpp(warm, 'kOperations'), const_cpp(warm, 'kWords')
snapshots, selectors = const_cpp(main, 'kSnapshots'), const_cpp(main, 'kSelectors')
table = (ROOT / 'tests/regression/ai_bench_common/counters.h').read_text().split('constexpr Counter kCounters[] = {', 1)[1].split('\n};', 1)[0]
rows = []
for line in table.splitlines():
    if line.strip():
        match = re.fullmatch(r'\s*\{"([^"]+)", .*, (VX_ISA_EXT_[A-Z0-9_]+|0ull)\},', line)
        assert match, line
        rows.append({'name': match.group(1), 'required_isa': match.group(2)})
assert len({r['name'] for r in rows}) == len(rows)
unavailable = [r for r in rows if r['required_isa'] in ('VX_ISA_EXT_L2CACHE', 'VX_ISA_EXT_L3CACHE')]
available = [r for r in rows if r not in unavailable]
assert selectors == len(available) and len(rows) == 45
per_process = dict(operations=operations, launches=operations, checked_words=operations * words,
    snapshots=snapshots, available_queries=snapshots * len(available),
    half_replies=snapshots * len(available) * 2, cache_flush_reads=operations,
    dcr_reads=snapshots * len(available) * 2 + operations,
    unavailable_rows=snapshots * len(unavailable))
population = len(formats) * len(policies)
complete = {'processes': population, **{name: value * population for name, value in per_process.items() if name != 'operations'}}
assert per_process == literal('ci/project/p06_managed_preflight_contract.py', 'PER_PROCESS')
assert complete == literal('ci/project/p06_managed_preflight_contract.py', 'COMPLETE_COUNTS')
assert complete == literal('ci/project/p06_dependency_local_execute.py', 'COMPLETE_COUNTS')

def decode16(bits, fmt):
    fraction_bits, exponent_bits, bias = (10, 5, 15) if fmt == 'fp16' else (7, 8, 127)
    sign = -1 if bits & 0x8000 else 1
    exponent = (bits >> fraction_bits) & ((1 << exponent_bits) - 1)
    fraction = bits & ((1 << fraction_bits) - 1)
    assert exponent != (1 << exponent_bits) - 1
    significand = fraction if exponent == 0 else (1 << fraction_bits) + fraction
    power = (1 if exponent == 0 else exponent) - bias - fraction_bits
    value = sign * Fraction(significand) * (Fraction(2) ** power)
    assert value.denominator == 1
    return int(value)

def unpack(values, fmt):
    return [decode16((int(word, 16) >> offset) & 0xffff, fmt) for word in values for offset in (0, 16)]

def exact_integer_fp32(value):
    if value == 0:
        return '00000000'
    absolute = abs(value)
    shift = absolute.bit_length() - 1
    assert shift <= 23
    significand = absolute << (23 - shift)
    bits = ((1 if value < 0 else 0) << 31) | ((127 + shift) << 23) | (significand - (1 << 23))
    return f'{bits:08x}'

layout = json.loads((ROOT / 'ci/project/fixtures/p02_layout_v1.json').read_text())
header = (ROOT / 'tests/regression/sgemm_tcu/p02_fixtures.h').read_text()
fixture_results = []
for fmt in formats:
    case_id = fmt + '-single-dense_boundaries'
    cases = [c for c in layout['cases'] if c['id'] == case_id]
    assert len(cases) == 1
    case = cases[0]
    m, n, k = (case['dimensions'][x] for x in ('m', 'n', 'k'))
    assert (m, n, k) == (8, 4, 8)
    a, b = unpack(case['a_words'], fmt), unpack(case['b_words'], fmt)
    assert (len(a), len(b)) == (m*k, n*k)
    outputs = [sum(a[row*k+i] * b[col*k+i] for i in range(k)) for row in range(m) for col in range(n)]
    expected = [exact_integer_fp32(v) for v in outputs]
    assert expected == case['expected'] and len(expected) == words
    selected = re.search(r'\{"' + case_id + r'", "' + fmt + r'", 8u, 4u, 8u,\s*kA(\d+), 32u, kB\1, 16u,\s*kExpected\1, 32u\}', header)
    assert selected, case_id
    index = selected.group(1)
    for name, reference in [('A', case['a_words']), ('B', case['b_words']), ('Expected', expected)]:
        text = re.search(r'inline constexpr uint32_t k' + name + index + r'\[\] = \{([^}]+)\};', header).group(1)
        assert re.findall(r'0x([0-9a-f]{8})u', text) == reference
    fixture_results.append({'case_id': case_id, 'shape': [m, n, k],
        'packed_a_words': len(case['a_words']), 'packed_b_words': len(case['b_words']),
        'checked_output_words': len(expected), 'exact_integer_outputs': outputs,
        'expected_fp32_sha256': digest(bytes.fromhex(''.join(expected))),
        'independent_integer_recomputation_and_cpp_header_match': True,
        'production_arithmetic_model_used': False})

unchanged = []
for name in FILES:
    if name == 'ci/project/p06_dependency_local_execute.py':
        continue
    original = subprocess.check_output(['git', 'show', BASE + ':' + name], cwd=ROOT)
    if digest(original) == before[name]['sha256']:
        unchanged.append(name)
changed = sorted(set(FILES) - set(unchanged))
assert changed == ['ci/project/p06_dependency_local_execute.py', 'ci/project/p06_dependency_native_replay.py']
assert before == {name: {'sha256': digest((ROOT / name).read_bytes()), 'size_bytes': (ROOT / name).stat().st_size} for name in FILES}
result = {'schema_version': 1, 'review_id': 'w06_a01', 'outcome': 'pass',
    'scope': 'independent fixed-workload/source/fixture/count audit; no native execution or original transcript replay',
    'source_revision': revision,
    'source_tree': subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], cwd=ROOT).decode().strip(),
    'reviewed_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'formats': list(formats), 'policies': list(policies), 'per_process': per_process,
    'complete_counts': complete, 'available_selectors': available, 'unavailable_selectors': unavailable,
    'fixture_checks': fixture_results, 'snapshot_reset_offsets': [0, 1, operations, operations],
    'checked_lifetime_run_pairs_per_process': operations,
    'runtime_allocations_per_process': {'per_operation': operations * 3, 'reusable_single_tile': 3},
    'selected_user_payload_bytes': 128 + 64 + 128,
    'native_execution_by_reviewer': 'not_run', 'retained_native_code_executed': False,
    'fixture_checks_used_only_data_and_independent_integer_arithmetic': True,
    'source_hashes': before, 'source_files_stable': True,
    'unchanged_since_audit_base': unchanged,
    'changed_reviewed_files': changed,
    'findings': [],
    'remaining': ['Read actual complete original logs and independently replay them without mocks.',
        'Verify exact native source/build/artifact/loader joins and every run/reset/read boundary.',
        'The four-process boundary observations do not close all 40 component lifetimes, an absolute no-wrap proof, complete counter qualification, or performance acceptance.'],
    **dict.fromkeys(('qualified', 'ready_for_warm', 'warm_execution', 'full_warm_coverage', 'acceptance_claimed', 'phase_acceptance', 'performance_acceptance'), False)}
OUT.write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({'outcome': result['outcome'], 'counts': complete, 'fixtures_verified': len(fixture_results),
                  'source_files_hashed': len(before), 'result': str(OUT), 'result_sha256': digest(OUT.read_bytes())}))
