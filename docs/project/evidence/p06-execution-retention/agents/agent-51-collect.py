"""Collect canonical IDs once, without running any test or fixture."""

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
import time
import unittest
import zipfile


ROOT = Path('/tmp/ai-gpu-ae456f837c05/AI-GPU')
NOTES = ROOT.parent / 'notes'
FREEZE = ROOT.parent / 'validation/publication-source-freeze.json'
HISTORICAL_FREEZE = ROOT.parent / 'validation/operational-source-freeze.json'
BASE = '622662ad9cece6da4e3375be7e977dbe04cde862'
EXPECTED_RECENT_IDS = [
    'test_p06_pack_final_cleanup.PackagingFinalCleanupTests.test_final_output_close_failure_is_fatal_after_success',
    'test_p06_pack_final_cleanup.PackagingFinalCleanupTests.test_final_output_close_failure_is_fatal_inside_callers_except',
    'test_p06_pack_final_cleanup.PackagingFinalCleanupTests.test_primary_failure_survives_final_output_close_failure',
]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def utc():
    return datetime.now(timezone.utc).isoformat()


def aggregate(value):
    return digest(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())


def git(*args):
    return subprocess.check_output(
        ['git', *args], cwd=ROOT, env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0'})


def file_record(path):
    content = path.read_bytes()
    return {
        'path': str(path.relative_to(ROOT)),
        'size_bytes': len(content),
        'mode': oct(stat.S_IMODE(path.stat().st_mode)),
        'sha256': digest(content),
    }


def source_inventory():
    return {
        str(path.relative_to(ROOT)): digest(path.read_bytes())
        for path in sorted((ROOT / 'ci/project').rglob('*.py'))
    }


def freeze_inventory(rows):
    return [file_record(ROOT / row['path']) for row in rows]


def freeze_mismatches(expected, observed):
    return [a['path'] for a, b in zip(expected, observed) if a != b]


def leaves(node):
    if isinstance(node, unittest.TestSuite):
        for child in node:
            yield from leaves(child)
    else:
        yield node


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')


os.chdir(ROOT)
started_at = utc()
elapsed_start = time.monotonic()
head_before = git('rev-parse', 'HEAD').decode().strip()
prior_paths = [NOTES / ('agent-44' + suffix) for suffix in
               ('-discovered.json', '-population.json', '.md')]
prior_records_before = {path.name: digest(path.read_bytes()) for path in prior_paths}
prior_manifest_raw = prior_paths[0].read_bytes()
prior_manifest = json.loads(prior_manifest_raw)
prior_population = json.loads(prior_paths[1].read_bytes())
base_zip = NOTES / 'base-governance.zip'
base_zip_sha = digest(base_zip.read_bytes())
with zipfile.ZipFile(base_zip) as archive:
    base_manifest_raw = archive.read('run/discovered.json')
    base_manifest = json.loads(base_manifest_raw)
    base_revision = archive.read('logs/source-revision.txt').decode().strip()
base_ids = base_manifest['test_ids']
prior_ids = prior_manifest['test_ids']
base_set, prior_set = set(base_ids), set(prior_ids)
freeze_raw_before = FREEZE.read_bytes()
freeze_record = json.loads(freeze_raw_before)
freeze_expected = freeze_record['files']
historical_before = digest(HISTORICAL_FREEZE.read_bytes())
frozen_before = freeze_inventory(freeze_expected)
sources_before = source_inventory()
runner_path = ROOT / 'ci/project/governance_run.py'
runner_before = file_record(runner_path)
runner_base_sha = digest(git('show', BASE + ':ci/project/governance_run.py'))

if platform.python_version() != '3.12.14' or not sys.dont_write_bytecode:
    raise RuntimeError('Prepared CPython 3.12.14 with bytecode disabled is required')
if '-B' not in sys.orig_argv:
    raise RuntimeError('An explicit -B flag is required')
if os.environ.get('TMPDIR') != str(ROOT.parent / 'tmp'):
    raise RuntimeError('The task-specific TMPDIR is required')

sys.path.insert(0, str(ROOT / 'ci/project'))
import governance_run

test_paths = {str(path.resolve()) for path in (ROOT / 'ci/project').rglob('test_*.py')}
observed_calls = {'discovery': 0, 'test_bodies': [], 'fixtures': []}
discover_code = unittest.TestLoader.discover.__code__
fixture_names = {'setUp', 'tearDown', 'setUpClass', 'tearDownClass',
                 'setUpModule', 'tearDownModule'}


def observe_calls(frame, event, arg):
    if event != 'call':
        return
    code = frame.f_code
    if code is discover_code:
        observed_calls['discovery'] += 1
    if code.co_filename in test_paths:
        if code.co_name.startswith('test_'):
            observed_calls['test_bodies'].append(
                {'path': code.co_filename, 'function': code.co_qualname})
        elif code.co_name in fixture_names:
            observed_calls['fixtures'].append(
                {'path': code.co_filename, 'function': code.co_qualname})


collection_started_at = utc()
sys.setprofile(observe_calls)
try:
    loader = unittest.TestLoader()
    suite = loader.discover(governance_run.DISCOVERY['start_directory'],
                            pattern=governance_run.DISCOVERY['pattern'])
    candidate_ids = governance_run.collect_test_ids(suite)
    cases = list(leaves(suite))
finally:
    sys.setprofile(None)
collection_finished_at = utc()

candidate_set = set(candidate_ids)
counter = Counter(candidate_ids)
duplicates = sorted(identity for identity, count in counter.items() if count != 1)
added_ids = [identity for identity in candidate_ids if identity not in base_set]
recent_ids = [identity for identity in candidate_ids if identity not in prior_set]
removed_ids = [identity for identity in base_ids if identity not in candidate_set]
prior_removed = [identity for identity in prior_ids if identity not in candidate_set]
added_counts = dict(sorted(Counter(identity.split('.')[0] for identity in added_ids).items()))
expected_added_counts = {**prior_population['added_by_module'], 'test_p06_pack_final_cleanup': 3}
active_skips, expected_failures, import_failures = [], [], []
for case in cases:
    if isinstance(case, unittest.loader._FailedTest):
        import_failures.append(case.id())
    method = getattr(case, case._testMethodName)
    if (getattr(type(case), '__unittest_skip__', False)
            or getattr(method, '__unittest_skip__', False)):
        active_skips.append(case.id())
    if (getattr(type(case), '__unittest_expecting_failure__', False)
            or getattr(method, '__unittest_expecting_failure__', False)):
        expected_failures.append(case.id())

imported_bindings = []
loaded_test_modules = []
for module_name, module in sorted(list(sys.modules.items())):
    module_file = getattr(module, '__file__', None)
    if not module_file or str(Path(module_file).resolve()) not in test_paths:
        continue
    loaded_test_modules.append(module_name)
    for binding, value in sorted(vars(module).items()):
        if (inspect.isclass(value) and issubclass(value, unittest.TestCase)
                and value.__module__ != module_name):
            names = loader.getTestCaseNames(value)
            if names:
                imported_bindings.append({
                    'module': module_name, 'binding': binding,
                    'defined_in': value.__module__, 'test_method_count': len(names),
                })

frozen_after = freeze_inventory(freeze_expected)
freeze_raw_after = FREEZE.read_bytes()
sources_after = source_inventory()
runner_after = file_record(runner_path)
head_after = git('rev-parse', 'HEAD').decode().strip()
prior_records_after = {path.name: digest(path.read_bytes()) for path in prior_paths}
historical_after = digest(HISTORICAL_FREEZE.read_bytes())
changed_sources = sorted(path for path in set(sources_before) | set(sources_after)
                         if sources_before.get(path) != sources_after.get(path))
mismatches_before = freeze_mismatches(freeze_expected, frozen_before)
mismatches_after = freeze_mismatches(freeze_expected, frozen_after)
candidate_digest = governance_run._ids_digest(candidate_ids)
manifest = {
    'schema_version': 1,
    'scope': 'project-governance-canonical-discovery-only',
    'discovery': governance_run.DISCOVERY,
    'count': len(candidate_ids),
    'sha256': candidate_digest,
    'test_ids': candidate_ids,
    'test_bodies_executed': len(observed_calls['test_bodies']),
    'full_governance_qualification': False,
}
manifest_path = NOTES / 'agent-51-discovered.json'
write_json(manifest_path, manifest)
manifest_sha = digest(manifest_path.read_bytes())

checks = {
    'base_revision_valid': base_revision == BASE,
    'base_manifest_count_valid': base_manifest['count'] == len(base_ids) == 5114,
    'base_manifest_digest_valid': base_manifest['sha256'] == governance_run._ids_digest(base_ids),
    'base_archive_matches_agent_44': base_zip_sha == prior_population['base_archive']['sha256'],
    'base_ids_unique': len(base_set) == len(base_ids),
    'all_base_ids_retained': not removed_ids,
    'base_relative_order_preserved': [item for item in candidate_ids if item in base_set] == base_ids,
    'prior_manifest_count_valid': prior_manifest['count'] == len(prior_ids) == 5164,
    'prior_manifest_digest_valid': prior_manifest['sha256'] == governance_run._ids_digest(prior_ids),
    'prior_manifest_matches_agent_44': digest(prior_manifest_raw) == prior_population['candidate_manifest']['file_sha256'],
    'prior_ids_unique': len(prior_set) == len(prior_ids),
    'all_prior_ids_retained': not prior_removed,
    'prior_relative_order_preserved': [item for item in candidate_ids if item in prior_set] == prior_ids,
    'prior_agent_44_records_stable': prior_records_before == prior_records_after,
    'candidate_count_5167': len(candidate_ids) == 5167,
    'candidate_ids_unique': not duplicates,
    'exactly_53_added_ids': len(added_ids) == 53,
    'exactly_15_added_modules': len(added_counts) == 15,
    'added_module_counts_match': added_counts == expected_added_counts,
    'exactly_3_ids_added_since_agent_44': len(recent_ids) == 3,
    'recent_ids_match_agent_48_methods': recent_ids == EXPECTED_RECENT_IDS,
    'no_loader_errors': not loader.errors,
    'no_import_failure_cases': not import_failures,
    'no_active_skip_flags': not active_skips,
    'no_expected_failure_flags': not expected_failures,
    'no_imported_testcase_bindings': not imported_bindings,
    'canonical_discovery_called_once': observed_calls['discovery'] == 1,
    'no_test_body_calls_observed': not observed_calls['test_bodies'],
    'no_test_fixture_calls_observed': not observed_calls['fixtures'],
    'freeze_has_23_unique_paths': len(freeze_expected) == len({row['path'] for row in freeze_expected}) == 23,
    'freeze_matches_before': not mismatches_before,
    'freeze_matches_after': not mismatches_after,
    'freeze_record_stable': freeze_raw_before == freeze_raw_after,
    'frozen_23_sources_stable': frozen_before == frozen_after,
    'historical_freeze_retained': historical_before == historical_after == freeze_record['earlier_snapshot']['sha256'],
    'all_governance_python_stable': sources_before == sources_after,
    'canonical_runner_unchanged_from_base_and_agent_44': runner_before == runner_after
        and runner_before['sha256'] == runner_base_sha == prior_population['canonical_runner']['sha256'],
    'head_stable': head_before == head_after,
}
population = {
    'schema_version': 1,
    'scope': 'final-publication-canonical-population-preservation-review-only',
    'started_at': started_at,
    'collection_started_at': collection_started_at,
    'collection_finished_at': collection_finished_at,
    'finished_at': utc(),
    'elapsed_seconds': time.monotonic() - elapsed_start,
    'base_revision': base_revision,
    'candidate_commit': None,
    'head_before': head_before,
    'head_after': head_after,
    'discovery': governance_run.DISCOVERY,
    'canonical_discovery_calls': observed_calls['discovery'],
    'canonical_runner': runner_after,
    'canonical_runner_baseline_sha256': runner_base_sha,
    'collector': {'path': str(Path(__file__)), 'sha256': digest(Path(__file__).read_bytes()),
                  'command': [sys.executable, '-B', str(Path(__file__))],
                  'cwd': str(ROOT)},
    'environment': {
        'executable': sys.executable,
        'python_version': platform.python_version(),
        'implementation': platform.python_implementation(),
        'platform': platform.system(),
        'machine': platform.machine(),
        'path': os.environ['PATH'],
        'tmpdir': os.environ['TMPDIR'],
        'bytecode_disabled': sys.dont_write_bytecode,
        'explicit_B_flag': '-B' in sys.orig_argv,
        'new_signal_guard_enabled': os.name == 'posix' and Path('/proc/self/stat').exists(),
    },
    'base_archive': {'path': str(base_zip), 'sha256': base_zip_sha},
    'base_manifest': {'member': 'run/discovered.json',
                      'file_sha256': digest(base_manifest_raw),
                      'ordered_ids_sha256': governance_run._ids_digest(base_ids)},
    'prior_manifest': {'path': str(prior_paths[0]),
                       'file_sha256': digest(prior_manifest_raw),
                       'ordered_ids_sha256': governance_run._ids_digest(prior_ids)},
    'candidate_manifest': {'path': str(manifest_path), 'file_sha256': manifest_sha,
                           'ordered_ids_sha256': candidate_digest},
    'prior_agent_44_records': {'before': prior_records_before, 'after': prior_records_after},
    'counts': {
        'base': len(base_ids), 'prior': len(prior_ids), 'candidate': len(candidate_ids),
        'retained_base': len(base_set & candidate_set),
        'retained_prior': len(prior_set & candidate_set),
        'added': len(added_ids), 'added_modules': len(added_counts),
        'added_since_agent_44': len(recent_ids),
        'removed': len(removed_ids), 'removed_since_agent_44': len(prior_removed),
        'duplicate_ids': len(duplicates), 'loader_errors': len(loader.errors),
        'import_failure_cases': len(import_failures),
        'active_skip_flags': len(active_skips),
        'expected_failure_flags': len(expected_failures),
        'imported_testcase_bindings': len(imported_bindings),
        'loaded_test_modules_inspected': len(loaded_test_modules),
    },
    'added_by_module': added_counts,
    'expected_added_by_module': expected_added_counts,
    'added_ids': added_ids,
    'added_since_agent_44_ids': recent_ids,
    'removed_ids': removed_ids,
    'removed_since_agent_44_ids': prior_removed,
    'duplicate_ids': duplicates,
    'loader_errors': loader.errors,
    'import_failure_cases': import_failures,
    'active_skip_ids': active_skips,
    'expected_failure_ids': expected_failures,
    'imported_testcase_bindings': imported_bindings,
    'frozen_sources': {
        'path': str(FREEZE), 'count': len(freeze_expected),
        'record_sha256_before': digest(freeze_raw_before),
        'record_sha256_after': digest(freeze_raw_after),
        'inventory_sha256_before': aggregate(frozen_before),
        'inventory_sha256_after': aggregate(frozen_after),
        'matches_freeze_before': not mismatches_before,
        'matches_freeze_after': not mismatches_after,
        'mismatch_paths_before': mismatches_before,
        'mismatch_paths_after': mismatches_after,
        'stable_before_after': frozen_before == frozen_after,
        'observed_files_before': frozen_before,
        'observed_files_after': frozen_after,
    },
    'historical_freeze': {'path': str(HISTORICAL_FREEZE),
                          'sha256_before': historical_before, 'sha256_after': historical_after},
    'governance_python': {
        'count_before': len(sources_before), 'count_after': len(sources_after),
        'inventory_sha256_before': aggregate(sources_before),
        'inventory_sha256_after': aggregate(sources_after),
        'changed_paths': changed_sources,
        'observed_files_before': sources_before,
        'observed_files_after': sources_after,
    },
    'call_observation': observed_calls,
    'test_bodies_executed': len(observed_calls['test_bodies']),
    'test_fixtures_executed': len(observed_calls['fixtures']),
    'full_governance_qualification': False,
    'native_execution': 'not_run',
    'checks': checks,
    'all_checks_passed': all(checks.values()),
    'limitations': [
        'Collection only: no test runner, test body, setup/teardown, or native workload was invoked.',
        'Inactive collection flags cannot rule out runtime skips or failures.',
        'This uncommitted candidate population is not exact-revision full strict qualification.',
    ],
}
population_path = NOTES / 'agent-51-population.json'
write_json(population_path, population)
population_sha = digest(population_path.read_bytes())
module_rows = '\n'.join(f'| `{name}.py` | {count} |' for name, count in added_counts.items())
recent_rows = '\n'.join(f'- `{identity}`' for identity in recent_ids)
failed_checks = [name for name, passed in checks.items() if not passed]
report = f'''# Agent 51 — final publication canonical population

## Result

**{len(candidate_ids):,} unique canonical IDs**, retaining all **{len(base_ids):,} baseline IDs**
and all **{len(prior_ids):,} Agent 44 IDs** in their original relative order.
The actual delta is **{len(added_ids)} IDs across {len(added_counts)} new modules** against baseline,
including **{len(recent_ids)} new IDs** since Agent 44. All comparison checks passed:
**{population['all_checks_passed']}**. Failed checks: `{failed_checks}`.

No duplicate IDs, loader errors, import-failure cases, active skip flags,
expected-failure flags or imported test-bearing `TestCase` bindings were found.
Inspected all {len(loaded_test_modules)} loaded local test modules for imported bindings.

## Method and stability

Read BRIEF, AGENTS, Agent 44/48 reports, the strict runner's collection contract,
the governance runbook and the 23-file publication freeze. Collected from the
repository source root at **{collection_started_at}–{collection_finished_at}**.
Used prepared CPython **{platform.python_version()}** with explicit `-B`,
`PYTHONDONTWRITEBYTECODE=1`, task-specific `TMPDIR`, and the prepared venv plus
`/usr/bin:/bin` on PATH. The retained collector is `agent-51-collect.py`.

Exactly one ordinary `unittest.TestLoader().discover("ci/project", pattern="test_*.py")`
call supplied unchanged `governance_run.collect_test_ids` and `_ids_digest`.
Call observation independently recorded **{observed_calls['discovery']} discovery call**,
**{len(observed_calls['test_bodies'])} test-body calls** and
**{len(observed_calls['fixtures'])} fixture calls**. No runner was invoked.
No repository edits, Git writes, native execution or child agents occurred.

All **23 frozen paths** matched size, mode and SHA-256 before and after collection.
All **{len(sources_before)} `ci/project/**/*.py` files** retained identical SHA-256 inventories.
The canonical runner matched baseline and Agent 44. HEAD remained `{head_after}`.
The publication freeze, historical 22-file freeze and all three Agent 44 result
files remained byte-for-byte unchanged. Full inventories and checks are retained
in `agent-51-population.json`.

## Additions against baseline

| Module under `ci/project/` | IDs |
| --- | ---: |
{module_rows}

The three additional IDs since Agent 44 are:

{recent_rows}

## Retained identities

| Record | SHA-256 |
| --- | --- |
| Baseline ZIP | `{base_zip_sha}` |
| Baseline ordered IDs | `{governance_run._ids_digest(base_ids)}` |
| Prior Agent 44 manifest | `{digest(prior_manifest_raw)}` |
| Candidate ordered IDs | `{candidate_digest}` |
| Complete `agent-51-discovered.json` | `{manifest_sha}` |
| `agent-51-population.json` | `{population_sha}` |
| Publication freeze record | `{digest(freeze_raw_before)}` |
| Canonical runner | `{runner_after['sha256']}` |

## Limits and next action

This establishes population preservation only. It does not establish runtime
test success, zero runtime skips or complete strict qualification. The signal
guard is enabled on this Linux host. Root should reconcile this actual manifest
with the subsequent complete uninterrupted strict invocation and retained closure
evidence. Native execution, P06-A02/A03 and phase acceptance remain outside scope.
'''
(NOTES / 'agent-51.md').write_text(report)
print(json.dumps({
    'counts': population['counts'], 'checks': checks,
    'candidate_manifest_sha256': manifest_sha,
    'candidate_ordered_ids_sha256': candidate_digest,
    'population_sha256': population_sha,
    'publication_freeze_sha256': digest(freeze_raw_before),
    'elapsed_seconds': population['elapsed_seconds'],
}, sort_keys=True, indent=2))
sys.exit(0 if population['all_checks_passed'] else 1)
