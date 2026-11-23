"""Synthetic full-reader arithmetic controls; no native execution."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

import p06_managed_preflight_contract as preflight
import p06_managed_preflight_records as parent
import p06_managed_preflight_test_fixture as parent_fixture
import p06_native_lifetime_records as lifetime
from p06_native_lifetime_test_fixture import BINDING, EXPECTED_LIBRARIES, raw_records, render_log

ROOT = Path('/tmp/ai-gpu-native-lifetime-dfd857')
OUTPUT = Path('/tmp/ai-gpu-native-lifetime-dfd857-work/w05_a06-reset-boundary.json')
MAX = (1 << 64) - 1
contract = preflight.load_contract()
original = raw_records(contract=contract)
starting = original[4]['constructed_state']['reset_generation']

def shift(value, offset, clamp):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in ('reset_generation', 'reset_before', 'reset_after'):
                value[key] = min(child + offset, MAX) if clamp else child + offset
            else:
                shift(child, offset, clamp)
    elif isinstance(value, (list, tuple)):
        for child in value:
            shift(child, offset, clamp)

rows = []
started = time.monotonic()
for label, new_start, clamp, admitted in (
        ('last_representable_33_reset_window', MAX - 33, False, True),
        ('one_past_window_with_repaired_clamped_endpoints', MAX - 32, True, False)):
    raw = deepcopy(original)
    shift(raw[3:], new_start - starting, clamp)
    args = dict(contract=contract, case=raw[0], fmt='fp16', policy='per_operation',
                binding_id=BINDING, sample_id='warm-simx-fp16-pair0-per_operation',
                process_id='preflight-simx-fp16-per_operation',
                expected_libraries=EXPECTED_LIBRARIES)
    parent.verify_output(parent_fixture.render_log(*raw[1:4]), **args)
    error = None
    try:
        lifetime.verify_output(render_log(*raw[1:]), **args)
        passed = True
    except ValueError as caught:
        passed = False
        error = str(caught)
    assert passed is admitted, (label, passed, error)
    if not admitted:
        assert error == 'native lifetime reset generation would overflow', error
    rows.append(dict(case=label, starting_reset=new_start, parent_admitted=True,
                     lifetime_admitted=passed, expected_lifetime_admission=admitted,
                     error=error))

files = ['ci/project/p06_native_lifetime_records.py',
         'ci/project/p06_native_lifetime_contract.py',
         'ci/project/p06_native_lifetime_test_fixture.py',
         'ci/project/p06_managed_preflight_contract.py',
         'ci/project/p06_managed_preflight_records.py',
         'ci/project/p06_managed_preflight_test_fixture.py']
result = dict(scope='synthetic full-reader reset arithmetic controls', native_execution='not_run',
              source_revision=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              argv=[sys.executable, '-B', str(Path(__file__).resolve())],
              source_sha256={name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in files},
              script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              seconds=time.monotonic() - started, checks=rows, passed=True)
OUTPUT.write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
