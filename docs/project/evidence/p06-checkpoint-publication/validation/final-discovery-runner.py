#!/usr/bin/env python3
"""Inventory canonical discovery without executing test bodies."""
import ast
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import unittest
import zipfile

ROOT = Path('/tmp/ai-gpu-2bfab0261c05/repo')
AREA = ROOT.parent
OUTPUT = AREA / 'validation/a050-discovery.json'
EXPECTED_HEAD = 'd31e8879e7c248b1a72615128882533ccdd0b3b4'
BASE_HEAD = '858090410a992756808256ace90d36b9b3b88dd3'
ARCHIVE = AREA / 'base-governance/run-45762183368-attempt1.zip'
PRIOR = AREA / 'validation/a029-discovery.json'
MODULES = [
    'test_checkpoint_directory_access', 'test_checkpoint_ownership',
    'test_checkpoint_write_failures', 'test_p06_checkpoint_input_recovery',
    'test_p06_checkpoint_prepare_build', 'test_p06_checkpoint_run_recovery',
    'test_p05_launcher_signals',
]

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def ids_digest(ids):
    return sha(''.join(identity + '\n' for identity in ids).encode('utf-8'))

def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).rstrip('\n')

def source():
    files = {}
    for directory in ('ci/project', 'python'):
        for path in sorted((ROOT / directory).rglob('*.py')):
            raw = path.read_bytes()
            files[path.relative_to(ROOT).as_posix()] = {'size_bytes':len(raw), 'sha256':sha(raw)}
    return {
        'head':git('rev-parse', 'HEAD'), 'tree':git('rev-parse', 'HEAD^{tree}'),
        'status_porcelain':git('status', '--short'),
        'python_files':files,
        'python_files_digest':sha(json.dumps(files,sort_keys=True,separators=(',',':')).encode()),
    }

def flatten(node):
    if isinstance(node, unittest.TestSuite):
        for child in node:
            yield from flatten(child)
    else:
        yield node.id()

def duplicates(ids):
    return {key:value for key,value in Counter(ids).items() if value != 1}

def delta(ids, original):
    original_set = set(original)
    current_set = set(ids)
    return {
        'count_delta':len(ids)-len(original),
        'added_test_ids':[identity for identity in ids if identity not in original_set],
        'removed_test_ids':[identity for identity in original if identity not in current_set],
        'existing_id_relative_order_preserved':[identity for identity in ids if identity in original_set] == original,
    }

assert Path.cwd() == ROOT
started = datetime.now(timezone.utc).isoformat()
before = source()
loader = unittest.TestLoader()
begin = time.monotonic()
suite = loader.discover(start_dir='ci/project', pattern='test_*.py', top_level_dir='ci/project')
identities = list(flatten(suite))
duration = time.monotonic() - begin
after = source()
archive_raw = ARCHIVE.read_bytes()
provider = json.loads((AREA/'base-governance/provider-original.json').read_text())
with zipfile.ZipFile(ARCHIVE) as archive:
    original_raw = archive.read('run/discovered.json')
    original = json.loads(original_raw)
prior_raw = PRIOR.read_bytes()
prior = json.loads(prior_raw)
base_ids = original['test_ids']
prior_ids = prior['test_ids']
expected = []
for name in MODULES:
    tree = ast.parse((ROOT/'ci/project'/f'{name}.py').read_bytes())
    for node in tree.body:
        if isinstance(node,ast.ClassDef):
            for method in node.body:
                if isinstance(method,(ast.FunctionDef,ast.AsyncFunctionDef)) and method.name.startswith('test_'):
                    expected.append(f'{name}.{node.name}.{method.name}')
base_delta = delta(identities,base_ids)
prior_delta = delta(identities,prior_ids)
base_delta.update({
    'added_by_module':dict(sorted(Counter(identity.split('.')[0] for identity in base_delta['added_test_ids']).items())),
    'expected_modules':MODULES, 'expected_new_method_count':len(expected),
    'ast_new_method_ids':sorted(expected),
    'added_ids_match_all_ast_new_methods':set(base_delta['added_test_ids'])==set(expected),
})
failed = [identity for identity in identities if identity.startswith('unittest.loader._FailedTest.')]
checks = {
    'head_matches_requested':before['head']==after['head']==EXPECTED_HEAD,
    'head_tree_stable':before['tree']==after['tree'],
    'all_python_source_bytes_stable':before['python_files']==after['python_files'],
    'worktree_status_stable':before['status_porcelain']==after['status_porcelain'],
    'no_loader_errors':not loader.errors,
    'no_failed_placeholders':not failed,
    'no_duplicate_ids':not duplicates(identities),
    'expected_current_population':len(identities)==len(set(identities))==5547,
    'base_population_matches':len(base_ids)==len(set(base_ids))==original['count']==5515,
    'base_digest_matches':ids_digest(base_ids)==original['sha256'],
    'base_archive_matches_provider':sha(archive_raw)==provider['digest'].removeprefix('sha256:'),
    'base_delta_exact':len(base_delta['added_test_ids'])==32 and not base_delta['removed_test_ids'] and base_delta['added_ids_match_all_ast_new_methods'] and base_delta['existing_id_relative_order_preserved'],
    'prior_population_matches':len(prior_ids)==len(set(prior_ids))==prior['count']==5539,
    'prior_digest_matches':ids_digest(prior_ids)==prior['test_ids_sha256_newline_ordered'],
    'prior_delta_exact':len(prior_delta['added_test_ids'])==8 and not prior_delta['removed_test_ids'] and prior_delta['existing_id_relative_order_preserved'] and all(i.startswith('test_p05_launcher_signals.') for i in prior_delta['added_test_ids']),
    'bytecode_disabled':sys.dont_write_bytecode and os.environ.get('PYTHONDONTWRITEBYTECODE')=='1',
}
result = {
    'schema_version':1, 'agent':'/root/a050_final_discovery',
    'scope':'canonical-unittest-discovery-only', 'test_execution':'not_run',
    'started_at':started, 'finished_at':datetime.now(timezone.utc).isoformat(),
    'discovery_seconds':duration, 'command':[sys.executable,'-B',str(Path(__file__))],
    'cwd':str(ROOT), 'python_executable':sys.executable,'python_version':platform.python_version(),
    'pythondontwritebytecode':os.environ.get('PYTHONDONTWRITEBYTECODE'),
    'sys_dont_write_bytecode':sys.dont_write_bytecode, 'loader_class':'unittest.TestLoader',
    'discovery':{'start_directory':'ci/project','pattern':'test_*.py','top_level_dir':'ci/project','filter':None,'canonical_equivalence':'Explicit top_level_dir equals the start directory, which is the default used by governance_run.py.'},
    'source_before':before, 'source_after':after,
    'count':len(identities),'unique_count':len(set(identities)), 'test_ids':identities,
    'test_ids_sha256_newline_ordered':ids_digest(identities),
    'loader_errors':list(loader.errors), 'failed_test_placeholders':failed,
    'duplicate_test_ids':duplicates(identities),
    'baseline':{'source_revision':BASE_HEAD,'archive_path':str(ARCHIVE),'archive_sha256':sha(archive_raw),'provider_digest':provider['digest'],'manifest_member':'run/discovered.json','manifest_bytes_sha256':sha(original_raw),'manifest_count':original['count'],'manifest_id_digest':original['sha256'],'computed_id_digest':ids_digest(base_ids),'duplicate_test_ids':duplicates(base_ids)},
    'prior_discovery':{'path':str(PRIOR),'sha256':sha(prior_raw),'source_revision':prior['source_before']['head'],'count':prior['count'],'id_digest':ids_digest(prior_ids)},
    'base_delta':base_delta,'prior_delta':prior_delta,
    'checks':checks,'all_checks_passed':all(checks.values()),
    'qualification':'Discovery inventories IDs and imports modules; no test suite/test method was executed. This is not strict governance qualification, independent replay, native execution or acceptance.',
}
OUTPUT.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'count':result['count'],'unique_count':result['unique_count'],'sha256':result['test_ids_sha256_newline_ordered'],'base_additions':len(base_delta['added_test_ids']),'prior_additions':len(prior_delta['added_test_ids']),'python_files_observed':len(before['python_files']),'discovery_seconds':duration,'all_checks_passed':result['all_checks_passed'],'failed_checks':[key for key,value in checks.items() if not value]},indent=2))
raise SystemExit(0 if result['all_checks_passed'] else 1)
