"""Read-only failure diagnosis; the hypothetical document never leaves memory."""

from copy import deepcopy
from contextlib import ExitStack
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest import mock

sys.dont_write_bytecode = True
FROZEN = Path('/workspace/p06-local-run-source-02')
sys.path.insert(0, str(FROZEN / 'ci/project'))
import p06_dependency_contract as contract
import p06_dependency_receipt as receipt

ROOT = Path('/workspace/p06-local-native-run-02/evidence/dependency-build')
REPORT = ROOT / 'report.json'
EXPECTED = '344c43fe145a76f11938c45abcdb940ddda5a47da52c9ced6249713b9d62123b'
OUT = Path('/workspace/scratch/279b6658611e/validation/w06_a05-retention-review.json')


def digest(path):
    value = hashlib.sha256()
    size = 0
    with path.open('rb') as stream:
        while block := stream.read(1024 ** 2):
            value.update(block)
            size += len(block)
    return {'sha256': value.hexdigest(), 'size_bytes': size}


def original_inventory():
    rows = {}
    for path in sorted(ROOT.rglob('*')):
        assert not path.is_symlink()
        if path.is_file():
            rows[path.relative_to(ROOT).as_posix()] = digest(path)
    return rows


started = time.monotonic()
before = original_inventory()
assert before['report.json']['sha256'] == EXPECTED
raw = REPORT.read_bytes()
original = receipt.decode(raw)
assert original['state'] == 'finished' and original['outcome'] == 'fail'
assert original['fresh_dependency_build_passed'] is False
assert all(original[name] is False for name in contract.FALSE_CLAIMS)
names = [row['path'] for row in original['retained_files']]
result = {'schema_version': 1,
          'scope': 'Read-only hypothetical inventory-order diagnostic; not an original pass or re-execution',
          'source_revision': original['expected_revision'],
          'reader_root': str(FROZEN),
          'reader_sha256': digest(FROZEN / 'ci/project/p06_dependency_receipt.py')['sha256'],
          'report_before': before['report.json'],
          'original_outcome': original['outcome'], 'original_reason': original['reason'],
          'original_fresh_dependency_build_passed': False,
          'native_execution': 'not_run', 'retained_code_executed': False,
          'descending_pairs': [[names[i - 1], names[i]] for i in range(1, len(names))
                               if names[i - 1] > names[i]],
          'original_file_count': len(before),
          'original_bytes': sum(row['size_bytes'] for row in before.values()),
          'hypothetical_mutations': ['outcome=pass', 'reason=None', 'failures=[]',
                                    'fresh_dependency_build_passed=True',
                                    'retained_files sorted by relative POSIX path string'],
          'all_seven_claims_remain_false': True,
          'hypothetical_document_written': False,
          'checks': []}


def exercise(name, document):
    entry = {'case': name}
    then = time.monotonic()
    try:
        verified = receipt.verify_document(document, receipt.PacketReader(ROOT),
                                           expected_revision=original['expected_revision'])
        entry.update(result='accepted', semantic_result={
            'tool_execution_records': verified['tool_execution_records'],
            'translation_units': verified['translation_units'],
            'archive_names': sorted(verified['archives']),
            'link_names': sorted(verified['links']),
            'product_names': sorted(verified['products']),
            'source_manifest_sha256': verified['source_manifest_sha256'],
            'all_seven_claims_false': all(verified[key] is False for key in contract.FALSE_CLAIMS)})
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        entry.update(result='rejected', reason=str(error), error_type=type(error).__name__)
    entry['duration_seconds'] = round(time.monotonic() - then, 6)
    result['checks'].append(entry)
    return entry


with ExitStack() as guards:
    guards.enter_context(mock.patch.object(subprocess, 'Popen', side_effect=AssertionError('no child execution')))
    guards.enter_context(mock.patch.object(os, 'system', side_effect=AssertionError('no shell execution')))
    unchanged = exercise('unchanged failed original', original)
    assert unchanged['result'] == 'rejected'
    assert unchanged['reason'] == 'dependency receipt is not a complete successful build'
    hypothetical = deepcopy(original)
    hypothetical.update(outcome='pass', reason=None, failures=[], fresh_dependency_build_passed=True)
    assert all(hypothetical[name] is False for name in contract.FALSE_CLAIMS)
    status_only = exercise('hypothetical status only, original inventory order', hypothetical)
    assert status_only['result'] == 'rejected' and status_only['reason'] == 'retained inventory ordering differs'
    hypothetical['retained_files'] = sorted(hypothetical['retained_files'], key=lambda row: row['path'])
    prospective = exercise('hypothetical status plus prospective lexical inventory order', hypothetical)

after = original_inventory()
assert after == before and REPORT.read_bytes() == raw
assert receipt.decode(REPORT.read_bytes()) == original
result.update(original_unchanged=True, report_after=after['report.json'],
              original_file_inventory_sha256=hashlib.sha256(contract.json_bytes(before)).hexdigest(),
              duration_seconds=round(time.monotonic() - started, 6),
              finished_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
              prospective_reader_result=prospective['result'],
              original_reclassified=False)
OUT.write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
