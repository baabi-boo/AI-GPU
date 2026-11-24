import ast
import contextlib
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

ROOT = Path('/workspace/scratch/101d52695253/AI-GPU')
OUT = ROOT.parent / 'agent-notes/a51-probe.json'
FILES = (
    'ci/project/p05_replay_native.py',
    'ci/project/test_p05_replay_effective_headers.py',
    'ci/project/p02_matrix_records.py',
    'ci/project/p03_execution_records.py',
    'ci/project/compiler_records.py',
    'ci/project/baseline_packet_contract.py',
    'ci/project/p05_execute.py',
    'ci/project/p05_execution_records.py',
    'ci/project/p05_torch_records.py',
    'ci/project/p05_installed_check.py',
    'ci/project/p05_torch_replay.py',
    'docs/project/evidence/p05-torch/reviews/archive_reader.py',
)
def hashes():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in FILES}
before = hashes()
unchanged = {}
for name in FILES[2:]:
    revision = 'f01c9d03147343d274ee0a45b71b34f004709c0e' if name in FILES[2:7] or name == FILES[-1] else 'd8abc24d2fd5dab5ceddbae3627e3d3eb9750358'
    blob = subprocess.check_output(['git', 'show', revision + ':' + name], cwd=ROOT)
    unchanged[name] = {'revision': revision, 'byte_equal': blob == (ROOT / name).read_bytes()}
assert all(item['byte_equal'] for item in unchanged.values())

import p03_execution_records as records
import p05_replay_native as replay
from test_p02_matrix import BUILD, SOURCE, STAMP_SAMPLES, sample
module = importlib.import_module('test_p05_replay_effective_headers')
def flatten(suite):
    for case in suite:
        if isinstance(case, unittest.TestSuite):
            yield from flatten(case)
        else:
            yield case.id()
ids = list(flatten(unittest.defaultTestLoader.loadTestsFromModule(module)))
assert len(ids) == len(set(ids)) == 5, ids

observations = []
with contextlib.ExitStack() as stack:
    for target in ('builtins.open', 'pathlib.Path.open', 'pathlib.Path.resolve', 'subprocess.Popen'):
        stack.enter_context(patch(target, side_effect=AssertionError('forbidden helper I/O: ' + target)))
    for fmt in ('fp16', 'bf16'):
        app = sample('application', fmt=fmt).splitlines()
        app[2] = '-L' + str(BUILD / 'sw/runtime') + ' -lvortex'
        parsed = records.validate_records(sample('simx_rt', fmt=fmt), sample('simx_backend', fmt=fmt),
                                          '\n'.join(app) + '\n', driver='simx', fmt=fmt,
                                          source=str(SOURCE), build=str(BUILD), jobs=2)
        assert [row['role'] for row in parsed] == ['runtime', 'backend_cpp', 'kernel', 'host']
        kernel = parsed[2]
        header = STAMP_SAMPLES['header'] + '#define ITYPE ' + fmt + '\n#define OTYPE fp32\n#define KUNROLL 1\n'
        for name, value in (('ITYPE', fmt), ('OTYPE', 'fp32'), ('KUNROLL', '1')):
            # Same prefix, different C macro names must not count as selected definitions.
            control = header + '#define ' + name + '_OTHER(x) x\n#define ' + name + '2 999\n'
            projected = replay._effective_header_macros(control, kernel)
            assert projected == replay.validate_header_macros(STAMP_SAMPLES['header'])
            assert all(key.startswith('VX_CFG_') for key in projected)
            # A tab after #define is collected by the selected-name scan but is not canonical -dM output.
            candidate = control.replace('#define ' + name + ' ' + value + '\n',
                                        '#define\t' + name + ' ' + value + '\n')
            assert candidate != control
            try:
                replay._effective_header_macros(candidate, kernel)
            except ValueError as exc:
                error = str(exc)
                assert error == 'effective header has a malformed ' + name + ' definition', error
            else:
                raise AssertionError('malformed selected definition accepted')
            observations.append({'format': fmt, 'name': name, 'control': 'accepted', 'mutation': 'rejected',
                                 'error': error, 'kernel_role': kernel['role'],
                                 'unchanged_projection': True})

def return_keys(source):
    tree = ast.parse(source)
    fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'verify_native')
    assert isinstance(fn.body[-1], ast.Return) and isinstance(fn.body[-1].value, ast.Dict)
    return [ast.literal_eval(key) for key in fn.body[-1].value.keys]
prior = subprocess.check_output(['git', 'show', 'd8abc24d2fd5dab5ceddbae3627e3d3eb9750358:ci/project/p05_replay_native.py'], cwd=ROOT).decode()
keys = return_keys((ROOT / FILES[0]).read_text())
assert keys == return_keys(prior)
after = hashes()
assert after == before
result = {
    'scope': 'independent synthetic helper probe, static caller review, discovery only; no full public replay',
    'command': 'PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=ci/project python3 -B /tmp/a51-effective-header-probe.py',
    'probe_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    'controls_accepted': len(observations), 'mutations_rejected': len(observations),
    'observations': observations, 'discovery_count': len(ids), 'distinct_ids': len(set(ids)),
    'discovered_ids': ids, 'discovered_tests_executed': False,
    'return_keys_unchanged': keys, 'unchanged_comparisons': unchanged,
    'source_before': before, 'source_after': after, 'source_stable': before == after,
    'native_execution': 'not_run', 'retained_code_executed': False,
    'original_archives_opened': False, 'public_replay_executed': False,
}
OUT.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
print(json.dumps({'controls_accepted': len(observations), 'mutations_rejected': len(observations),
                  'discovery_count': len(ids), 'distinct_ids': len(set(ids)), 'source_stable': before == after,
                  'unchanged_dependency_files': len(unchanged), 'return_keys_unchanged': True,
                  'source_sha256': before[FILES[0]], 'test_sha256': before[FILES[1]],
                  'report': str(OUT)}, indent=2))
