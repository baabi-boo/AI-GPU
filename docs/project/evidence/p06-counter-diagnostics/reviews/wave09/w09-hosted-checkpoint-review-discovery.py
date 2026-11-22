from collections import Counter
from datetime import datetime, timezone
import ast
import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path('/workspace/scratch/98908dfa3444/AI-GPU')
SCRATCH = ROOT.parent
REVISION = '4268d2d5d811063bb886cde7bd0e27e61a79c9b4'
PARENT = 'e5f152464dda5e488d6d1a030c1fcdc49b5a9701'
HOST = ROOT / 'docs/project/evidence/p06-counter-diagnostics/host'
MODULES = {
    'test_p06_counter_diagnostics_replay': 43,
    'test_p06_counter_public_replay': 40,
    'test_p06_counter_inventory_replay': 23,
    'test_p06_counter_source_inventory': 48,
}

def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)

def identity(path):
    data = path.read_bytes()
    return {'sha256': hashlib.sha256(data).hexdigest(), 'size_bytes': len(data)}

def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item

os.chdir(ROOT)
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'ci/project'))
before_index = (HOST / 'index.json').read_bytes()
backup = SCRATCH / 'w09-hosted-checkpoint-review-index-before.json'
if backup.exists():
    assert backup.read_bytes() == before_index
else:
    backup.write_bytes(before_index)
old_index = json.loads(before_index)
old_log_identities = []
for row in old_index['logs']:
    observed = {'path': row['path'], **identity(HOST / row['path'])}
    assert observed == row
    old_log_identities.append(observed)

listed = git('ls-tree', '-rz', REVISION, '--', 'ci/project', '.github/workflows').split(b'\0')
source_projection = []
for entry in listed:
    if not entry:
        continue
    info, path_bytes = entry.split(b'\t', 1)
    mode, kind, blob = info.decode().split()
    path = path_bytes.decode()
    assert kind == 'blob', (path, kind)
    original = git('show', f'{REVISION}:{path}')
    current = (ROOT / path).read_bytes()
    source_projection.append({'path': path, 'mode': mode, 'git_blob': blob,
        'sha256': hashlib.sha256(original).hexdigest(), 'size_bytes': len(original),
        'current_bytes_match_tested_revision': current == original})
assert all(row['current_bytes_match_tested_revision'] for row in source_projection)
scope_status = git('status', '--porcelain', '--untracked-files=all', '--', 'ci/project', '.github/workflows').decode()
assert not scope_status, scope_status

loader = unittest.TestLoader()
tests = list(flatten(loader.discover(str(ROOT / 'ci/project'), pattern='test_*.py')))
assert not loader.errors, loader.errors
ids = [test.id() for test in tests]
assert len(ids) == len(set(ids))
counts = Counter(test.__class__.__module__ for test in tests)
new_ids = []
modules = {}
for name, expected in MODULES.items():
    selected = [test for test in tests if test.__class__.__module__ == name]
    assert len(selected) == expected, (name, len(selected))
    parsed = ast.parse((ROOT / 'ci/project' / (name + '.py')).read_bytes())
    static = [node.name for node in ast.walk(parsed)
              if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith('test_')]
    assert len(static) == expected, (name, len(static))
    skipped = [test.id() for test in selected
               if getattr(test.__class__, '__unittest_skip__', False)
               or getattr(getattr(test, test._testMethodName), '__unittest_skip__', False)]
    assert not skipped, skipped
    modules[name] = {'discovered_methods': len(selected), 'static_test_methods': len(static),
                     'class_counts': dict(Counter(type(test).__name__ for test in selected)),
                     'active_decorator_skips': skipped,
                     'test_ids': [test.id() for test in selected]}
    new_ids.extend(test.id() for test in selected)

public = importlib.import_module('test_p06_counter_public_replay')
archive, archive_sha, native_revision = public.successful_original()
assert public.FAILED_ORIGINAL.is_file()
assert identity(public.FAILED_ORIGINAL)['sha256'] == public.FAILED_SHA256
originals = []
for path in [archive, public.FAILED_ORIGINAL,
             ROOT / 'docs/project/evidence/p06-counter-diagnostics/native/run-45026112992-attempt1.zip',
             public.SUCCESS_RECEIPT]:
    relative = path.relative_to(ROOT).as_posix()
    checkpoint_bytes = git('show', f'{REVISION}:{relative}')
    assert checkpoint_bytes == path.read_bytes()
    originals.append({'path': relative, **identity(path), 'checkpoint_bytes_match': True})

old_log = (HOST / 'run-45031746158-job-137236633104.log').read_text()
assert 'Ran 3158 tests in 1305.183s' in old_log
assert len(ids) == 3158 + sum(MODULES.values()) == 3312

result = {
    'schema_version': 1,
    'reviewer': 'agent54 /root/w09_hosted_checkpoint_review',
    'observed_at_utc': datetime.now(timezone.utc).isoformat(),
    'review_method': 'AST method inventory plus unittest loader discovery only; no test methods or setUpClass executed',
    'source_revision': REVISION,
    'source_tree': git('rev-parse', f'{REVISION}^{{tree}}').decode().strip(),
    'parent_revision': PARENT,
    'parent_logged_test_total': 3158,
    'new_test_delta': sum(MODULES.values()),
    'expected_hosted_test_total': 3312,
    'discovery_total': len(ids),
    'unique_discovery_total': len(set(ids)),
    'discovery_errors': loader.errors,
    'modules': modules,
    'all_discovered_test_ids': ids,
    'source_projection': source_projection,
    'source_scope_porcelain': scope_status,
    'parent_code_diff_names': git('diff', '--name-status', PARENT, REVISION, '--', 'ci/project', '.github/workflows').decode().splitlines(),
    'existing_host_index_before': identity(backup),
    'existing_host_logs': old_log_identities,
    'archive_fixture_intake': {
        'successful_original_receipt_call': 'returned without SkipTest',
        'success_archive_revision': native_revision,
        'success_archive_sha256': archive_sha,
        'failed_original_present': True,
        'posix_no_follow_available': os.name == 'posix' and hasattr(os, 'O_NOFOLLOW'),
        'identities': originals,
    },
    'hosted_outcome': 'pending',
    'local_test_execution': 'not_run',
    'native_execution': 'not_run',
    'qualified': False,
    'ready_for_warm': False,
    'warm_execution': False,
    'acceptance': False,
}
output = SCRATCH / 'w09-hosted-checkpoint-review-discovery.json'
output.write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({'output': str(output), 'discovered': len(ids), 'delta': sum(MODULES.values()),
                  'modules': {name: value['discovered_methods'] for name, value in modules.items()},
                  'source_files_compared': len(source_projection), 'scope_unchanged': True,
                  'existing_log_hashes_preserved': True, 'native_intake_present': True}))
