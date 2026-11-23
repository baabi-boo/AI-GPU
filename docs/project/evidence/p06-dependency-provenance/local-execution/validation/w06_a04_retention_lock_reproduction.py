import hashlib
import json
from pathlib import Path
import time

from test_p06_dependency_control_replay import SyntheticNativeWithControlTools, SyntheticControls, descriptor
from test_p06_dependency_substitution import ActualSubstitutionBuildTests
import p06_dependency_control_replay as replay

root = Path('/workspace/scratch/279b6658611e/validation')
reader_sha256 = hashlib.sha256(Path(replay.__file__).read_bytes()).hexdigest()
assert reader_sha256 in {
    '28fb88029d28e3adaad61d55ad14b040ac2a718a6031e8f22bdae6dc05086329',
    'f31a0719f0c994dacee907292d9fb155430d3f019bd9ff180029781afb172e8b',
}, 'this historical reproduction requires the reader before the payload-lock correction'
started = time.monotonic()
fixture = ActualSubstitutionBuildTests('test_actual_fresh_marker_library_preserves_tiny_numerics_and_is_byte_different')
fixture.setUp()
try:
    fixture.build_control()
    lock = fixture.output / 'payloads/.retention.lock'
    actual = {'lock_exists': lock.is_file(), 'lock_bytes': lock.stat().st_size,
              'sha256': hashlib.sha256(lock.read_bytes()).hexdigest(),
              'record_count': len(list((fixture.output / 'records').glob('*.json')))}
    assert actual['lock_exists'] and actual['lock_bytes'] == 0 and actual['record_count'] == 2
finally:
    fixture.doCleanups()

original = SyntheticNativeWithControlTools()
native = original.reader()
native.run()
packet = SyntheticControls(original, native)
assert 'payloads/.retention.lock' not in packet.substitution_files, 'requires the pre-fix synthetic fixture'
assert packet.substitution_check()['outcome'] == 'pass'
packet.substitution_files['payloads/.retention.lock'] = b''
row = descriptor('payloads/.retention.lock', b'')
for key in ('control_products_before', 'control_products_after'):
    packet.substitution_report[key] = sorted([*packet.substitution_report[key], row], key=lambda item: item['path'])
try:
    packet.substitution_check()
except ValueError as error:
    rejected = str(error)
else:
    rejected = None

result = {'scope': 'actual tiny recorder plus synthetic complete substitution reader boundary',
          'actual_tiny_recorder': actual, 'synthetic_dependency_boundary_mocked': True,
          'baseline_fixture_outcome': 'pass', 'producer_correct_lock_outcome': 'rejected' if rejected else 'pass',
          'rejection': rejected, 'duration_seconds': time.monotonic() - started,
          'native_gpu_execution': 'not_run', 'original_evidence_modified': False}
(root / 'w06_a04-retention-lock-reproduction.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
assert rejected == 'substitution control_products_before: inventory length differs'
