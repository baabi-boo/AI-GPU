"""A54 canonical enumeration and one focused eight-module strict-accounting run."""
import ast
from collections import Counter
from datetime import datetime, timezone
import hashlib
import inspect
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import unittest

ROOT = Path('/tmp/ai-gpu-850acdff3419/repo')
OUT = ROOT.parent / 'validation/A54'
BASE = 'e8e73347ba598c9cd0ceed353148163721b7603d'
RECEIPT = ROOT.parent / 'validation/A37/environment/environment.json'
sys.path.insert(0, str(ROOT / 'ci/project'))
import governance_run

def write(name, value):
    with (OUT / name).open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')

def git(*args):
    return subprocess.check_output(['git', '--no-optional-locks', *args], cwd=ROOT)

def identity(path):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        raw, mode = os.fsencode(os.readlink(path)), '120000'
    elif stat.S_ISREG(info.st_mode):
        raw, mode = path.read_bytes(), '100755' if info.st_mode & 0o111 else '100644'
    elif stat.S_ISDIR(info.st_mode):
        return {'kind': 'directory'}
    else:
        raise AssertionError('unexpected special source: ' + str(path))
    return {'mode': mode, 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def source_snapshot():
    paths = git('ls-files', '--cached', '--others', '--exclude-standard', '-z', '--',
                'ci/project', '.github/workflows', 'sw', 'sim', 'hw', 'tests').decode().split('\0')
    return {path: identity(ROOT / path) for path in sorted(set(paths) - {''})}

def evidence_snapshot():
    paths = [ROOT.parent / ('agents/' + name + '.md') for name in ('A37', 'A39', 'A51')]
    paths.append(RECEIPT)
    for name in ('A37', 'A39', 'A51'):
        directory = ROOT.parent / ('validation/' + name)
        paths.extend(path for path in directory.rglob('*') if path.is_file()
                     and not {'environment', 'cmake-package'} & set(path.relative_to(directory).parts))
    return {str(path.relative_to(ROOT.parent)): identity(path) for path in sorted(set(paths))}

assert Path.cwd() == ROOT
assert git('rev-parse', 'HEAD').decode().strip() == BASE
prepared = json.loads(RECEIPT.read_text())
assert dict(os.environ) == prepared['environment'], 'active environment differs from A37 preparation'
assert Path(sys.executable).name == 'python3' and sys.version_info[:3] == (3, 12, 14)
environment_before = governance_run.environment_snapshot(RECEIPT)
source_before = source_snapshot()
evidence_before = evidence_snapshot()
write('source-before.json', source_before)
write('prior-evidence-before.json', evidence_before)

seven = ['test_p06_qualified_warm_' + name for name in ('capacity', 'control', 'encrypt', 'hosted', 'inputs', 'pack', 'run')]
names = ['test_governance_workflow', *seven]
base_path = ROOT.parent / 'validation/base-governance-discovered.json'
base_manifest = json.loads(base_path.read_text())
base_ids = base_manifest['test_ids']
assert base_manifest['source_revision'] == BASE
loader = unittest.TestLoader()
canonical = loader.discover(governance_run.DISCOVERY['start_directory'], pattern=governance_run.DISCOVERY['pattern'])
ids = governance_run.collect_test_ids(canonical)
base_set = set(base_ids)
added = [item for item in ids if item not in base_set]
duplicates = sorted(key for key, count in Counter(ids).items() if count != 1)
module_reviews = {}
for name in names:
    module = sys.modules[name]
    classes = {key: value for key, value in vars(module).items()
               if inspect.isclass(value) and issubclass(value, unittest.TestCase)}
    findings = []
    for key, cls in classes.items():
        if cls.__module__ != name:
            findings.append({'kind': 'imported_TestCase', 'class': key, 'origin': cls.__module__})
        for flag in ('__unittest_skip__', '__unittest_expecting_failure__'):
            if getattr(cls, flag, False):
                findings.append({'kind': flag, 'class': key})
        for method in loader.getTestCaseNames(cls):
            for flag in ('__unittest_skip__', '__unittest_expecting_failure__'):
                if getattr(getattr(cls, method), flag, False):
                    findings.append({'kind': flag, 'method': key + '.' + method})
    forbidden = {'skip', 'skipIf', 'skipUnless', 'skipTest', 'SkipTest', 'expectedFailure',
                 '__unittest_skip__', '__unittest_expecting_failure__'}
    references = []
    for node in ast.walk(ast.parse(Path(module.__file__).read_text())):
        token = node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else None
        if token in forbidden:
            references.append({'token': token, 'line': node.lineno})
    module_reviews[name] = {'count': sum(item.split('.')[0] == name for item in ids),
                            'classes': sorted(classes), 'findings': findings,
                            'skip_xfail_ast_references': references,
                            'custom_load_tests': hasattr(module, 'load_tests')}

old_test_paths = [path for path in git('ls-tree', '-r', '--name-only', BASE, '--', 'ci/project').decode().splitlines()
                  if Path(path).name.startswith('test_') and path.endswith('.py')]
changed_old_tests = []
for path in old_test_paths:
    old = git('show', BASE + ':' + path)
    if old != (ROOT / path).read_bytes():
        changed_old_tests.append(path)
assert changed_old_tests == ['ci/project/test_governance_workflow.py'], changed_old_tests
gov_path = ROOT / changed_old_tests[0]
old_gov = ast.parse(git('show', BASE + ':' + changed_old_tests[0]).decode())
new_gov = ast.parse(gov_path.read_text())
def strip_filters(tree):
    result = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'PATH_FILTERS' for target in node.targets):
            continue
        result.append(ast.dump(node, include_attributes=False))
    return result
assert strip_filters(old_gov) == strip_filters(new_gov), 'existing governance method semantics changed'
old_filters = next(ast.literal_eval(node.value) for node in old_gov.body
                   if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'PATH_FILTERS' for t in node.targets))
new_filters = sys.modules['test_governance_workflow'].PATH_FILTERS
assert new_filters - old_filters == {'.github/workflows/p06-qualified-warm.yml', 'docs/designs/qualified_warm_automation_v1.md'}
assert not old_filters - new_filters
discovery = {'scope': 'canonical unfiltered enumeration only; no full-suite execution',
             'timestamp_utc': datetime.now(timezone.utc).isoformat(), 'base_revision': BASE,
             'base_manifest_sha256': hashlib.sha256(base_path.read_bytes()).hexdigest(),
             'base_count': len(base_ids), 'base_unique_count': len(base_set),
             'current_count': len(ids), 'current_unique_count': len(set(ids)),
             'added_count': len(added), 'missing_base_ids': [item for item in base_ids if item not in set(ids)],
             'base_order_preserved': [item for item in ids if item in base_set] == base_ids,
             'duplicate_ids': duplicates, 'loader_errors': list(loader.errors),
             'loader_failure_ids': [item for item in ids if item.startswith('unittest.loader._FailedTest.')],
             'added_outside_seven_modules': [item for item in added if item.split('.')[0] not in seven],
             'module_reviews': module_reviews, 'existing_test_module_count': len(old_test_paths),
             'changed_existing_test_paths': changed_old_tests,
             'existing_test_method_asts_unchanged': True,
             'only_existing_ast_delta': 'two added PATH_FILTERS values; no original value removed'}
discovery['passed'] = (len(base_ids) == len(base_set) == 4812 and len(ids) == len(set(ids)) == 5036
                       and len(added) == 224 and not discovery['missing_base_ids']
                       and discovery['base_order_preserved'] and not duplicates and not loader.errors
                       and not discovery['loader_failure_ids'] and not discovery['added_outside_seven_modules']
                       and all(not row['findings'] and not row['skip_xfail_ast_references'] and not row['custom_load_tests']
                               for row in module_reviews.values()))
write('canonical-discovered.json', {'scope': discovery['scope'], 'discovery': governance_run.DISCOVERY,
                                   'count': len(ids), 'sha256': governance_run._ids_digest(ids), 'test_ids': ids})
write('added-test-ids.json', {'count': len(added), 'test_ids': added})
write('discovery-summary.json', discovery)
print('A54 canonical discovery:', json.dumps({key: discovery[key] for key in ('passed', 'base_count', 'current_count', 'added_count', 'base_order_preserved')}), flush=True)
assert discovery['passed'], 'canonical discovery regression'

focused_loader = unittest.TestLoader()
suite = focused_loader.loadTestsFromNames(names)
focused_ids = governance_run.collect_test_ids(suite)
assert len(focused_ids) == 236
assert focused_ids == [item for item in ids if item.split('.')[0] in names]
prior_seven = json.loads((ROOT.parent / 'validation/A39/seven-discovered.json').read_text())['ids']
assert [item for item in focused_ids if item.split('.')[0] in seven] == prior_seven
write('focused-discovered.json', {'modules': names, 'count': len(focused_ids),
                                 'sha256': governance_run._ids_digest(focused_ids), 'test_ids': focused_ids})
with (OUT / 'focused-events.jsonl').open('x') as events:
    def emit(row):
        events.write(json.dumps(row, sort_keys=True) + '\n')
        events.flush()
    result = governance_run.run_suite(suite, stream=sys.stdout, event_sink=emit,
                                      loader_errors=focused_loader.errors)
environment_after = governance_run.environment_snapshot(RECEIPT)
source_after = source_snapshot()
evidence_after = evidence_snapshot()
write('source-after.json', source_after)
write('prior-evidence-after.json', evidence_after)
write('environment-stability.json', {'before': environment_before, 'after': environment_after,
                                    'stable': environment_before == environment_after})
summary = {'scope': 'seven new helper modules plus existing test_governance_workflow; focused development check, not full governance qualification',
           'base_revision': BASE, 'strict_accounting': result.summary,
           'python_executable': sys.executable, 'python_version': sys.version, 'environment': dict(os.environ),
           'active_environment_exactly_matches_A37_preparation': True,
           'source_stable': source_before == source_after, 'source_manifest_entries': len(source_before),
           'environment_stable': environment_before == environment_after,
           'prior_A37_A39_A51_evidence_stable': evidence_before == evidence_after,
           'tests_run': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
           'skips': len(result.skipped), 'expected_failures': len(result.expectedFailures),
           'unexpected_successes': len(result.unexpectedSuccesses), 'canonical_discovery_passed': discovery['passed']}
summary['passed'] = (result.strict_success and summary['source_stable'] and summary['environment_stable']
                     and summary['prior_A37_A39_A51_evidence_stable'])
write('focused-summary.json', summary)
print('A54 focused summary:', json.dumps(summary, sort_keys=True), flush=True)
raise SystemExit(0 if summary['passed'] else 1)
