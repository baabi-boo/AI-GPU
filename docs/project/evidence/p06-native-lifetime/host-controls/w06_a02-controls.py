"""Focused inert parser checks; no native execution or production edits."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path('/tmp/ai-gpu-native-lifetime-dfd857')
WORK = Path('/tmp/ai-gpu-native-lifetime-dfd857-work')
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'ci/project'))
import p06_managed_preflight_contract as preflight
import p06_managed_preflight_records as parent
import p06_native_lifetime_contract as manifest
import p06_native_lifetime_records as records
from p06_native_lifetime_test_fixture import BINDING, EXPECTED_LIBRARIES, raw_records, render_log

paths = [
    'ci/project/p06_native_lifetime_records.py',
    'ci/project/p06_native_lifetime_contract.py',
    'ci/project/p06_native_lifetime_test_fixture.py',
    'ci/project/p06_managed_preflight_contract.py',
    'ci/project/p06_managed_preflight_records.py',
    'ci/project/p06_warm_records.py',
    'ci/project/test_p06_native_lifetime_records.py',
]
def identities():
    return {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths}

before = identities()
started = time.monotonic()
contract = preflight.load_contract()
raw = raw_records(contract=contract)
kwargs = dict(contract=contract, case=raw[0], fmt='fp16', policy='per_operation',
              binding_id=BINDING, sample_id='warm-simx-fp16-pair0-per_operation',
              process_id='preflight-simx-fp16-per_operation', expected_libraries=EXPECTED_LIBRARIES)
text = render_log(*raw[1:])
prefix, _ = records._split_output(text)
body = json.dumps(raw[4], separators=(',', ':'))
rows = []

def check(name, function, *, reject=False, pattern=None):
    try:
        function()
    except ValueError as error:
        if not reject or (pattern is not None and pattern not in str(error)):
            raise
        rows.append(dict(name=name, outcome='expected_rejection', reason=str(error)))
    else:
        if reject:
            raise AssertionError(name + ': malformed input was accepted')
        rows.append(dict(name=name, outcome='pass'))

def verify_body(value):
    return records.verify_output(prefix + manifest.WITNESS_PREFIX + value + '\n', **kwargs)

check('valid_complete_synthetic_transcript', lambda: records.verify_output(text, **kwargs))
check('escaped_equivalent_field_name_remains_unambiguous',
      lambda: verify_body(body.replace('"schema_version"', '"\\u0073chema_version"', 1)))
check('escaped_duplicate_top_level_key',
      lambda: verify_body(body[:-1] + ',"\\u0073chema_version":1}'), reject=True, pattern='duplicate')
check('escaped_duplicate_nested_key',
      lambda: verify_body(body.replace('"pending_reads":0', '"pending_reads":0,"\\u0070ending_reads":0', 1)),
      reject=True, pattern='duplicate')
check('object_suffix_cannot_escape_record_root',
      lambda: verify_body(body + ',"qualified":true'), reject=True)
check('second_concatenated_object', lambda: verify_body(body + '{}'), reject=True)
check('unpaired_escaped_surrogate',
      lambda: verify_body(body.replace('"backend":"simx"', '"backend":"\\ud800"', 1)), reject=True)
check('unpaired_raw_surrogate', lambda: records._split_output(text + '\ud800'), reject=True, pattern='UTF-8')
for token in ('0e0', '-0.0', 'Infinity', '-Infinity', '18446744073709551616', '-9223372036854775809', '100000000000000000000'):
    check('numeric_token_' + token,
          lambda token=token: verify_body(body.replace('"pending_reads":0', '"pending_reads":' + token, 1)),
          reject=True)

padded = body + ' ' * (manifest.MAX_RECORD_BYTES - len(body.encode()))
check('exact_record_byte_limit', lambda: verify_body(padded))
check('record_byte_limit_plus_one', lambda: verify_body(padded + ' '), reject=True, pattern='bounded UTF-8')

depth16 = b'{"value":' + b'[' * 15 + b'0' + b']' * 15 + b'}'
depth17 = b'{"value":' + b'[' * 16 + b'0' + b']' * 16 + b'}'
check('decoder_exact_depth16', lambda: preflight.decode_record(depth16))
check('decoder_depth17', lambda: preflight.decode_record(depth17), reject=True, pattern='nesting')
check('decoder_invalid_utf8', lambda: preflight.decode_record(b'{"x":"\xff"}'), reject=True)
check('decoder_u64_maximum', lambda: preflight.decode_record(b'{"x":18446744073709551615}'))
check('decoder_signed_storage_minimum', lambda: preflight.decode_record(b'{"x":-9223372036854775808}'))

sidecar = text[len(prefix):]
reordered = prefix.replace('PASSED!\n', sidecar + 'PASSED!\n', 1)
check('old_reader_rejects_reordered_new_marker', lambda: parent.verify_output(reordered, **kwargs), reject=True)
check('new_reader_rejects_reordered_marker', lambda: records.verify_output(reordered, **kwargs), reject=True)
check('old_reader_rejects_new_marker_before_warm_operations',
      lambda: parent.verify_output(sidecar + prefix, **kwargs), reject=True, pattern='wrong-route')
check('new_reader_rejects_new_marker_before_warm_operations',
      lambda: records.verify_output(sidecar + prefix, **kwargs), reject=True, pattern='final lifetime witness')

needed = manifest.MAX_OUTPUT_BYTES - len(text.encode())
chunks = []
while needed:
    count = min(needed, 65536)
    if count == 1:
        chunks.append('\n')
    else:
        chunks.append('x' * (count - 1) + '\n')
    needed -= count
at_limit = ''.join(chunks) + text
assert len(at_limit.encode()) == manifest.MAX_OUTPUT_BYTES
check('exact_complete_output_byte_limit', lambda: records.verify_output(at_limit, **kwargs))
check('complete_output_byte_limit_plus_one',
      lambda: records.verify_output('x' + at_limit, **kwargs), reject=True, pattern='byte bound')

after = identities()
assert before == after
revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
matches = {p: subprocess.check_output(['git', 'show', revision + ':' + p], cwd=ROOT) == (ROOT / p).read_bytes() for p in paths}
assert all(matches.values())
receipt = dict(scope='inert synthetic parser boundary checks; no native/build/test-suite execution',
               revision=revision, seconds=time.monotonic()-started, checks=rows,
               passed=len(rows), source_before=before, source_after=after,
               source_stable=True, matches_published_commit=matches, native_execution='not_run')
(WORK / 'w06_a02-controls.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(dict(checks=len(rows), seconds=receipt['seconds'], source_stable=True)))
