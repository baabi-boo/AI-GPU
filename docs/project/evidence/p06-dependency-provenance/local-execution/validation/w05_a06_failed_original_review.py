"""Independent negative controls for an actual failed dependency original."""
from collections import Counter
import copy
import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import time
import zipfile

ROOT = Path('/workspace/scratch/279b6658611e')
VALIDATION = ROOT / 'validation'
SOURCE = Path('/workspace/p06-local-run-source')
ARCHIVE = ROOT / 'AI-GPU_P06_local_attempt_01_failed_2026-11-23.zip'
ARCHIVE_PIN = '8021368d5efe755ae282ff2a89675979d8a1377582f84fbbea57e35b5ddad502'
REPORT_PIN = '97fe819aacd6d308e0c799701344efe5bd7229ac4d737f0c04ff1e69956151b1'
REVISION = 'ac2f2ae761c3644103278f7a41cc6ae7db734a86'
FALSE_CLAIMS = ('qualified', 'ready_for_warm', 'warm_execution', 'full_warm_coverage',
                'acceptance_claimed', 'phase_acceptance', 'performance_acceptance')

def file_identity(path):
    status = path.stat()
    sha = hashlib.sha256()
    with path.open('rb') as stream:
        while body := stream.read(1024**2):
            sha.update(body)
    return {'sha256': sha.hexdigest(), 'size_bytes': status.st_size}

before = file_identity(ARCHIVE)
assert before == {'sha256': ARCHIVE_PIN, 'size_bytes': 29286833}
with zipfile.ZipFile(ARCHIVE) as stream:
    original_report_bytes = stream.read('dependency-build/report.json')
    original_report = json.loads(original_report_bytes)
    assert hashlib.sha256(original_report_bytes).hexdigest() == REPORT_PIN
    records = [json.loads(stream.read('dependency-build/' + row['path']))
               for row in original_report['records']]
    actual_roles = dict(Counter(row['role'] for row in records))
    assert actual_roles == {'compile': 406, 'archive': 3, 'index': 2, 'link': 2}
    assert all(row['outcome'] == 'pass' for row in records)
    assert original_report['outcome'] == 'fail' and original_report['products'] == {}
    envelope = json.loads(stream.read('local-execution.json'))
    assert envelope['native_execution'] == 'not_run'

results = []
started = time.monotonic()

def run_case(name, *, archive=ARCHIVE, archive_pin=ARCHIVE_PIN,
             report_pin=REPORT_PIN, revision=REVISION, expected_reason):
    argv = ['python3', '-B', str(SOURCE / 'ci/project/p06_dependency_replay.py'),
            '--archive', str(archive), '--sha256', archive_pin,
            '--source-revision', revision, '--dependency-receipt-sha256', report_pin,
            '--prefix', 'dependency-build']
    start = time.monotonic()
    result = subprocess.run(argv, cwd=SOURCE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=120)
    body = json.loads(result.stdout)
    assert result.returncode == 1 and result.stderr == b''
    assert body['outcome'] == 'fail' and body['retained_consistency'] is False
    assert body['native_execution'] == 'not_run' and body['retained_code_executed'] is False
    assert all(body[name] is False for name in FALSE_CLAIMS)
    assert expected_reason in body['reason'], body
    results.append({'case': name, 'argv': argv, 'exit_code': result.returncode,
                    'duration_seconds': time.monotonic() - start, 'result': body})

run_case('actual_failed_original', expected_reason='dependency receipt is not a complete successful build')
run_case('malformed_archive_pin', archive_pin='not-a-sha256',
         expected_reason='external original ZIP SHA-256 is required')
run_case('malformed_revision_pin', revision='master',
         expected_reason='exact external source revision is required')
run_case('malformed_dependency_pin', report_pin='G' * 64,
         expected_reason='external dependency receipt SHA-256 is required')
run_case('wrong_well_formed_archive_pin', archive_pin='0' * 64,
         expected_reason='SHA-256')
run_case('wrong_well_formed_dependency_pin', report_pin='0' * 64,
         expected_reason='dependency receipt SHA-256 differs from the external intake identity')

mutated = copy.deepcopy(original_report)
mutated.update(outcome='pass', reason=None, failures=[], fresh_dependency_build_passed=True)
mutated_body = (json.dumps(mutated, indent=2, sort_keys=True) + '\n').encode()
synthetic = VALIDATION / 'w05_a06_SYNTHETIC_forged_pass_not_original.zip'
if not synthetic.exists():
    with zipfile.ZipFile(ARCHIVE) as source, zipfile.ZipFile(synthetic, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as output:
        for item in source.infolist():
            output.writestr(item, mutated_body if item.filename == 'dependency-build/report.json' else source.read(item.filename))
with zipfile.ZipFile(ARCHIVE) as source, zipfile.ZipFile(synthetic) as control:
    assert source.namelist() == control.namelist()
    for name in source.namelist():
        assert control.read(name) == (mutated_body if name == 'dependency-build/report.json' else source.read(name))
synthetic_identity = file_identity(synthetic)
synthetic_report_pin = hashlib.sha256(mutated_body).hexdigest()
run_case('synthetic_rebound_pass_flags_cannot_supply_missing_evidence', archive=synthetic,
         archive_pin=synthetic_identity['sha256'], report_pin=synthetic_report_pin,
         expected_reason='retained inventory ordering differs')
assert file_identity(ARCHIVE) == before
assert hashlib.sha256((Path('/workspace/p06-local-native-run-01/evidence/dependency-build/report.json')).read_bytes()).hexdigest() == REPORT_PIN
assert hashlib.sha256((SOURCE / 'ci/project/p06_dependency_replay.py').read_bytes()).hexdigest() == hashlib.sha256(subprocess.check_output(['git','-C',str(SOURCE),'show',REVISION+':ci/project/p06_dependency_replay.py'])).hexdigest()
summary = {'schema_version': 1, 'scope': 'actual failed-original and explicitly synthetic negative replay controls',
           'outcome': 'pass', 'source_revision': REVISION, 'original_archive': before,
           'original_report_sha256': REPORT_PIN, 'original_operation_roles': actual_roles,
           'all_original_operation_records_passed': True, 'original_overall_outcome': 'fail',
           'original_native_execution': 'not_run', 'original_products': {},
           'tests': results, 'tests_passed': len(results),
           'synthetic_control': {'filename': synthetic.name, **synthetic_identity,
                                 'report_sha256': synthetic_report_pin,
                                 'changed_fields': ['outcome','reason','failures','fresh_dependency_build_passed'],
                                 'original_evidence': False},
           'original_archive_and_report_unchanged': True,
           'retained_code_executed': False, 'production_source_edited': False,
           'duration_seconds': time.monotonic() - started,
           'finished_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
           'limitations': ['Negative controls do not establish a successful complete dependency or native original.',
                          'The synthetic archive changes only success-related fields and external pins; it is never original execution evidence.']}
(VALIDATION / 'w05_a06-failed-original-review.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps({'outcome':'pass','cases':len(results),'rejections':[{ 'case':row['case'],'reason':row['result']['reason']} for row in results], 'duration_seconds':summary['duration_seconds']},indent=2))
