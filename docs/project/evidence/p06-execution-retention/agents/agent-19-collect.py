"""Read-only collection and source-population audit; never executes test bodies."""

import ast
from collections import Counter
from datetime import datetime, timezone
import hashlib
import inspect
import json
import os
from pathlib import Path
import platform
import stat
import subprocess
import sys
import unittest
import zipfile


ROOT = Path('/tmp/ai-gpu-ae456f837c05/AI-GPU')
NOTES = ROOT.parent / 'notes'
PREFIX = sys.argv[1] if len(sys.argv) > 1 else 'agent-19'
BASE = '622662ad9cece6da4e3375be7e977dbe04cde862'
EXPECTED_MODULE_COUNTS = {
    'test_p06_control_closeout_review': 4,
    'test_p06_control_finalization': 8,
    'test_p06_control_operational_failures': 6,
    'test_p06_encrypt_operational_failures': 6,
    'test_p06_encrypt_publication_review': 1,
    'test_p06_hosted_operational_failures': 6,
    'test_p06_input_operational_failures': 3,
    'test_p06_operational_cancellation': 4,
    'test_p06_pack_operational_failures': 4,
    'test_p06_prelaunch_review': 2,
    'test_p06_warm_supervision_failures': 1,
}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def utc():
    return datetime.now(timezone.utc).isoformat()


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def source_snapshot():
    return {str(p.relative_to(ROOT)): sha256(p.read_bytes())
            for p in sorted((ROOT / 'ci/project').rglob('*.py'))}


def aggregate(mapping):
    return sha256(json.dumps(mapping, sort_keys=True, separators=(',', ':')).encode())


def leaves(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from leaves(item)
        else:
            yield item


def markers(source):
    records = []
    wanted = {'skip', 'skipIf', 'skipUnless', 'expectedFailure', 'skipTest', 'SkipTest'}
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            for deco in node.decorator_list:
                expr = deco.func if isinstance(deco, ast.Call) else deco
                name = expr.attr if isinstance(expr, ast.Attribute) else getattr(expr, 'id', '')
                if name in wanted:
                    records.append({'kind': 'decorator', 'name': name, 'target': node.name,
                                    'line': deco.lineno, 'expression': ast.unparse(deco)})
        elif isinstance(node, ast.Call):
            expr = node.func
            name = expr.attr if isinstance(expr, ast.Attribute) else getattr(expr, 'id', '')
            if name in {'skipTest', 'SkipTest'}:
                records.append({'kind': 'call', 'name': name, 'line': node.lineno,
                                'expression': ast.unparse(node)})
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            rendered = ast.unparse(node)
            if '__unittest_skip' in rendered or '__unittest_expecting_failure__' in rendered:
                records.append({'kind': 'attribute_assignment', 'line': node.lineno,
                                'expression': rendered})
    return records


os.chdir(ROOT)
started = utc()
head_before = git('rev-parse', 'HEAD').decode().strip()
status_before = git('status', '--porcelain=v1', '--untracked-files=all').decode()
base_zip = NOTES / 'base-governance.zip'
with zipfile.ZipFile(base_zip) as archive:
    base_manifest_raw = archive.read('run/discovered.json')
    base_manifest = json.loads(base_manifest_raw)
    base_revision = archive.read('logs/source-revision.txt').decode().strip()
base_ids = base_manifest['test_ids']
base_counter = Counter(base_ids)

tree = git('ls-tree', '-r', '--full-tree', '-z', BASE)
tracked_entries = {}
tracked_changes = []
tracked_errors = []
gitlinks = []
raw_inventory = {}
tracked_bytes = 0
for row in tree.split(b'\0'):
    if not row:
        continue
    meta, name_raw = row.split(b'\t', 1)
    mode, kind, oid = meta.decode().split()
    name = os.fsdecode(name_raw)
    if kind == 'commit':
        gitlinks.append({'path': name, 'object_id': oid, 'scope': 'not-inspected'})
        continue
    tracked_entries[name] = {'mode': mode, 'object_id': oid}
    path = ROOT / name
    try:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            data = os.fsencode(os.readlink(path))
            current_mode = '120000'
        elif stat.S_ISREG(metadata.st_mode):
            data = path.read_bytes()
            current_mode = '100755' if metadata.st_mode & stat.S_IXUSR else '100644'
        else:
            raise ValueError('not a regular file or symlink')
        current_oid = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        current_sha = sha256(data)
        tracked_bytes += len(data)
        raw_inventory[name] = {'mode': current_mode, 'sha256': current_sha}
        if current_oid != oid or current_mode != mode:
            tracked_changes.append({'path': name, 'base_object_id': oid,
                                    'current_object_id': current_oid,
                                    'base_mode': mode, 'current_mode': current_mode,
                                    'sha256': current_sha})
    except (OSError, ValueError) as error:
        tracked_errors.append({'path': name, 'error': type(error).__name__})

sources_before = source_snapshot()
sys.path.insert(0, str(ROOT / 'ci/project'))
import governance_env
import governance_run

loader = unittest.TestLoader()
suite = loader.discover(governance_run.DISCOVERY['start_directory'],
                        pattern=governance_run.DISCOVERY['pattern'])
current_ids = governance_run.collect_test_ids(suite)
current_cases = list(leaves(suite))
current_counter = Counter(current_ids)
base_set = set(base_ids)
current_set = set(current_ids)
added_ids = sorted(current_set - base_set)
removed_ids = sorted(base_set - current_set)
added_counts = dict(sorted(Counter(i.split('.')[0] for i in added_ids).items()))
duplicate_ids = sorted(i for i, count in current_counter.items() if count != 1)
loaded_module_names = sorted({case.__class__.__module__ for case in current_cases})
imported_testcase_bindings = []
for module_name in loaded_module_names:
    module = sys.modules[module_name]
    for binding, value in sorted(vars(module).items()):
        if (inspect.isclass(value) and issubclass(value, unittest.TestCase)
                and value.__module__ != module_name and loader.getTestCaseNames(value)):
            imported_testcase_bindings.append({'module': module_name, 'binding': binding,
                'defined_in': value.__module__, 'test_method_count': len(loader.getTestCaseNames(value))})
active_skip_ids = []
expected_failure_ids = []
for case in current_cases:
    method = getattr(case, case._testMethodName)
    if getattr(case.__class__, '__unittest_skip__', False) or getattr(method, '__unittest_skip__', False):
        active_skip_ids.append(case.id())
    if getattr(case.__class__, '__unittest_expecting_failure__', False) or getattr(method, '__unittest_expecting_failure__', False):
        expected_failure_ids.append(case.id())

platform_error = None
try:
    governance_env.platform_checks()
except Exception as error:
    platform_error = str(error)
sources_after = source_snapshot()
source_drift = sorted(name for name in set(sources_before) | set(sources_after)
                      if sources_before.get(name) != sources_after.get(name))

changed_python = sorted(name for name, digest in sources_after.items()
                        if name not in tracked_entries
                        or name in {row['path'] for row in tracked_changes})
introduced_markers = []
for name in changed_python:
    current = markers((ROOT / name).read_text())
    prior = markers(git('show', BASE + ':' + name).decode()) if name in tracked_entries else []
    prior_keys = Counter(json.dumps({k: v for k, v in item.items() if k != 'line'}, sort_keys=True)
                         for item in prior)
    for item in current:
        key = json.dumps({k: v for k, v in item.items() if k != 'line'}, sort_keys=True)
        if prior_keys[key]:
            prior_keys[key] -= 1
        else:
            introduced_markers.append({'path': name, **item})

protected_prefixes = {'native_tests': ('tests/',), 'hardware': ('hw/',),
                      'simulator': ('sim/',), 'runtime_and_kernel': ('runtime/', 'sw/'),
                      'golden_baselines': ('ci/baselines/',), 'testcase_catalog': ('ci/testcases/',)}
protected_summary = {}
change_names = {row['path'] for row in tracked_changes} | {row['path'] for row in tracked_errors}
for label, prefixes in protected_prefixes.items():
    names = sorted(name for name in tracked_entries if name.startswith(prefixes))
    protected_summary[label] = {'tracked_file_count': len(names),
        'changed_or_unreadable_paths': sorted(set(names) & change_names),
        'sha256_inventory_digest': aggregate({name: raw_inventory.get(name) for name in names})}

result = {
    'schema_version': 1, 'scope': 'project-governance-population-audit-only',
    'started_at': started, 'finished_at': utc(), 'base_revision': base_revision,
    'head_before': head_before, 'head_after': git('rev-parse', 'HEAD').decode().strip(),
    'base_archive_sha256': sha256(base_zip.read_bytes()),
    'base_manifest_file_sha256': sha256(base_manifest_raw),
    'discovery': governance_run.DISCOVERY,
    'counts': {'base': len(base_ids), 'current': len(current_ids),
               'retained_base': len(base_set & current_set), 'added': len(added_ids),
               'removed': len(removed_ids), 'duplicate_current_ids': len(duplicate_ids),
               'loader_errors': len(loader.errors),
               'imported_testcase_bindings': len(imported_testcase_bindings),
               'active_skip_flags': len(active_skip_ids),
               'expected_failure_flags': len(expected_failure_ids),
               'new_skip_decorators': sum(m['kind'] == 'decorator' and m.get('name') != 'expectedFailure'
                                          for m in introduced_markers),
               'new_expected_failure_markers': sum(m.get('name') == 'expectedFailure' for m in introduced_markers)},
    'base_manifest_count_and_digest_valid': base_manifest['count'] == 5114 == len(base_ids)
        and base_manifest['sha256'] == governance_run._ids_digest(base_ids)
        and not any(count != 1 for count in base_counter.values()) and base_revision == BASE,
    'base_order_preserved': [identity for identity in current_ids if identity in base_set] == base_ids,
    'base_ids_sha256': governance_run._ids_digest(base_ids),
    'current_ids_sha256': governance_run._ids_digest(current_ids),
    'added_by_module': added_counts, 'expected_added_by_module': EXPECTED_MODULE_COUNTS,
    'added_module_counts_match': added_counts == EXPECTED_MODULE_COUNTS,
    'added_ids': added_ids, 'removed_ids': removed_ids, 'duplicate_ids': duplicate_ids,
    'loader_errors': loader.errors, 'imported_testcase_bindings': imported_testcase_bindings,
    'active_skip_ids': active_skip_ids, 'expected_failure_ids': expected_failure_ids,
    'introduced_skip_or_expected_failure_markers': introduced_markers,
    'platform': {'sys_platform': sys.platform, 'os_name': os.name,
                 'machine': platform.machine(), 'python': sys.version,
                 'executable': sys.executable, 'proc_self_stat_exists': Path('/proc/self/stat').exists(),
                 'new_cancellation_guard_condition': os.name == 'posix' and Path('/proc/self/stat').exists(),
                 'governance_env_platform_checks_passed': platform_error is None,
                 'platform_check_error': platform_error},
    'python_source_snapshot_before_sha256': aggregate(sources_before),
    'python_source_snapshot_after_sha256': aggregate(sources_after),
    'python_source_drift_during_collection': source_drift,
    'changed_python_source_sha256': {name: sources_after[name] for name in changed_python},
    'tracked_tree': {'base_blob_count': len(tracked_entries), 'bytes_read': tracked_bytes,
                     'raw_inventory_sha256': aggregate(raw_inventory),
                     'changed_tracked': tracked_changes, 'unreadable': tracked_errors,
                     'unchanged_count': len(tracked_entries) - len(tracked_changes) - len(tracked_errors),
                     'gitlinks_not_inspected': gitlinks,
                     'protected_categories': protected_summary},
    'status_before': status_before,
    'status_after': git('status', '--porcelain=v1', '--untracked-files=all').decode(),
    'test_bodies_executed': 0, 'full_suite_executed': False, 'native_qualification': False,
}
manifest = {'schema_version': 1, 'scope': 'project-governance-unittest-only',
            'discovery': governance_run.DISCOVERY, 'count': len(current_ids),
            'sha256': governance_run._ids_digest(current_ids), 'test_ids': current_ids}
(NOTES / (PREFIX + '-population.json')).write_text(json.dumps(result, sort_keys=True, separators=(',', ':')) + '\n')
(NOTES / (PREFIX + '-discovered.json')).write_text(json.dumps(manifest, sort_keys=True, separators=(',', ':')) + '\n')
(NOTES / (PREFIX + '-source-hashes.json')).write_text(json.dumps(sources_after, sort_keys=True, indent=2) + '\n')
print(json.dumps({key: result[key] for key in ['started_at', 'finished_at', 'counts',
    'base_manifest_count_and_digest_valid', 'base_order_preserved', 'base_ids_sha256',
    'current_ids_sha256', 'added_by_module', 'added_module_counts_match',
    'python_source_drift_during_collection', 'introduced_skip_or_expected_failure_markers']}, indent=2))
print(json.dumps({'tracked_tree': result['tracked_tree'], 'platform': result['platform']}, indent=2))
