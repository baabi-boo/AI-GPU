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
HOST = ROOT / 'docs/project/evidence/p06-counter-diagnostics/host'
REVISION = '142b2d6aaea2fa4226118b857514113032d2e26c'
TREE = '754ef8577f9a72785c0809048762c70b16cb4857'
PARENT = '4268d2d5d811063bb886cde7bd0e27e61a79c9b4'
PREFIX = 'w09-hosted-checkpoint-review-142b2d6'
CHANGED = {
    'ci/project/test_p06_counter_diagnostics_replay.py': 'c8d213737b6332a5e6c924114b3e403a2ddcea3e0a2eac2f1fd431a5f4842430',
    'ci/project/test_p06_counter_public_replay.py': '241299ec7abfbbafe857c9d23ea10a0350b2606b10af4d942912780068d01a5d',
}

def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)

def digest(data):
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
assert git('rev-parse', REVISION + '^{tree}').decode().strip() == TREE
assert git('rev-parse', REVISION + '^').decode().strip() == PARENT
changed = git('diff', '--name-only', PARENT, REVISION).decode().splitlines()
assert sorted(changed) == sorted(CHANGED)
before_index = (HOST / 'index.json').read_bytes()
snapshot = SCRATCH / (PREFIX + '-index-before.json')
if snapshot.exists():
    assert snapshot.read_bytes() == before_index
else:
    snapshot.write_bytes(before_index)
previous = json.loads(before_index)
assert len(previous['attempts']) == 4 and previous['attempts'][-1]['outcome'] == 'fail'
existing_host = []
for path in sorted(HOST.rglob('*')):
    if path.is_file():
        existing_host.append({'path': path.relative_to(HOST).as_posix(), **digest(path.read_bytes())})
for row in previous['logs']:
    assert {'path': row['path'], **digest((HOST / row['path']).read_bytes())} == row

projection = []
for item in git('ls-tree', '-rz', REVISION, '--', 'ci/project', '.github/workflows').split(b'\0'):
    if not item:
        continue
    entry, path_bytes = item.split(b'\t', 1)
    mode, kind, blob = entry.decode().split()
    path = path_bytes.decode()
    assert kind == 'blob'
    data = git('show', REVISION + ':' + path)
    assert data == (ROOT / path).read_bytes(), path
    if path in CHANGED:
        assert digest(data)['sha256'] == CHANGED[path]
    projection.append({'path': path, 'git_blob': blob, 'mode': mode, **digest(data),
                       'current_bytes_match_checkpoint': True})
assert len(projection) == 353
status = git('status', '--porcelain', '--untracked-files=all', '--', 'ci/project', '.github/workflows').decode()
assert not status, status

loader = unittest.TestLoader()
tests = list(flatten(loader.discover(str(ROOT / 'ci/project'), pattern='test_*.py')))
assert not loader.errors, loader.errors
ids = [test.id() for test in tests]
assert len(ids) == len(set(ids)) == 3318
old = json.loads((HOST / 'checkpoint-4268d2d/test-results.json').read_bytes())
old_ids = {row['id'] for row in old['test_results']}
new_ids = sorted(set(ids) - old_ids)
removed = sorted(old_ids - set(ids))
assert len(old_ids) == 3312 and len(new_ids) == 6 and not removed
modules = {}
ast_new = []
for name, count in [('test_p06_counter_diagnostics_replay', 47), ('test_p06_counter_public_replay', 42),
                    ('test_p06_counter_inventory_replay', 23), ('test_p06_counter_source_inventory', 48)]:
    selected = [test for test in tests if test.__class__.__module__ == name]
    assert len(selected) == count
    skipped = [test.id() for test in selected if getattr(type(test), '__unittest_skip__', False)
               or getattr(getattr(test, test._testMethodName), '__unittest_skip__', False)]
    assert not skipped, skipped
    modules[name] = {'discovered': count,
                    'class_counts': dict(Counter(type(test).__name__ for test in selected)),
                    'active_skip_decorators': [], 'test_ids': [test.id() for test in selected]}
for name in CHANGED:
    inventories = []
    for revision in [PARENT, REVISION]:
        parsed = ast.parse(git('show', revision + ':' + name))
        inventories.append({name.removeprefix('ci/project/').removesuffix('.py') + '.' + node.name + '.' + method.name
                            for node in parsed.body if isinstance(node, ast.ClassDef)
                            for method in node.body if isinstance(method, ast.FunctionDef) and method.name.startswith('test_')})
    assert inventories[0] <= inventories[1]
    ast_new.extend(inventories[1] - inventories[0])
assert set(ast_new) == set(new_ids)
old_failed = [row['id'] for row in old['test_results'] if row['result'] == 'FAIL']
assert len(old_failed) == 2 and set(old_failed) <= set(ids)

public = importlib.import_module('test_p06_counter_public_replay')
path, sha, revision = public.successful_original()
assert revision == 'e5f152464dda5e488d6d1a030c1fcdc49b5a9701'
assert sha == digest(path.read_bytes())['sha256']
fixtures = []
paths = [path, public.FAILED_ORIGINAL, public.SUCCESS_RECEIPT,
         ROOT / 'docs/project/evidence/p06-counter-diagnostics/native/run-45026112992-attempt1.zip',
         ROOT / 'docs/project/evidence/p05-torch/reviews/archive_reader.py']
for path in paths:
    relative = path.relative_to(ROOT).as_posix()
    data = path.read_bytes()
    assert data == git('show', PARENT + ':' + relative) == git('show', REVISION + ':' + relative)
    fixtures.append({'path': relative, **digest(data), 'parent_checkpoint_current_bytes_identical': True})
pins = []
for name in ['ci/project/p06_counter_public_execute.py', '.github/workflows/p06-checked-counters.yml',
             '.github/workflows/project-governance.yml', 'ci/project/test_p06_counter_public_execute.py']:
    data = (ROOT / name).read_bytes()
    assert data == git('show', PARENT + ':' + name) == git('show', REVISION + ':' + name)
    pins.append({'path': name, **digest(data), 'parent_checkpoint_current_bytes_identical': True})

result = {
    'schema_version': 1, 'reviewer': 'Agent 54 /root/w09_hosted_checkpoint_review',
    'observed_at_utc': datetime.now(timezone.utc).isoformat(),
    'source_revision': REVISION, 'source_tree': TREE, 'parent_revision': PARENT,
    'workflow_run_id': 45040805357, 'job_id': 137264592244,
    'method': 'Exact Git/current source comparison, AST inventory and unittest loader discovery; no test method or setUpClass executed',
    'local_discovery_interpreter': sys.version,
    'changed_paths_entire_commit': changed, 'changed_source_sha256': CHANGED,
    'source_projection': projection, 'source_scope_porcelain': status,
    'discovered': len(ids), 'unique_test_ids': len(set(ids)), 'expected_hosted_total': 3318,
    'old_unique_test_ids': 3312, 'added_test_ids': new_ids, 'removed_test_ids': removed,
    'old_failed_ids_retained': old_failed, 'new_ast_ids_equal_discovery_delta': True,
    'modules': modules, 'all_discovered_test_ids': ids, 'discovery_errors': [],
    'fixture_inputs': fixtures, 'successful_original_intake': 'returned without SkipTest',
    'native_pin_and_governance_files': pins,
    'existing_host_files_before': existing_host, 'host_index_before': digest(before_index),
    'independent_delta_review': [
        {'path': name, **digest((SCRATCH / name).read_bytes())}
        for name in ['w10-replay-guard-review.md', 'w10-replay-guard-review.json']],
    'hosted_outcome': 'pending', 'native_execution': 'not_run', 'local_test_execution': 'not_run',
    'qualified': False, 'ready_for_warm': False, 'warm_execution': False, 'acceptance': False,
}
output = SCRATCH / (PREFIX + '-discovery.json')
output.write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({'output': str(output), 'discovered': len(ids), 'new_ids': new_ids,
                  'removed_ids': removed, 'source_files_match': len(projection),
                  'changed_files': changed, 'old_failures_retained': old_failed,
                  'fixture_inputs_unchanged': len(fixtures), 'local_test_execution': 'not_run'}))
