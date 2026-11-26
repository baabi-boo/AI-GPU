#!/usr/bin/env python3
"""Run the bounded closeout integration selection against unchanged source bytes."""

import collections
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import traceback
import unittest


ROOT = Path('/home/agent/ai-gpu-work-4c990083f078/AI-GPU')
REPORTS = ROOT.parent / 'reports'
EXPECTED_HEAD = '43c93ce892f1f3f6c0555597da342709ec9f7e49'
REPORT = REPORTS / 'a085-integration.json'
SUMMARY = REPORTS / 'a085.txt'
BASELINE_REPORT = REPORTS / 'a052-integration.json'
FINAL_FIXTURE = 'ci/project/test_p06_hosted_prelaunch_emission.py'
FINAL_FIXTURE_SHA256 = '9c6de0268be3eaaa2efd5271ca2dec383ac6f8bd8ed96e42c20fa3c6bae2406e'
PRODUCTION = [
    'ci/project/p06_dependency_build.py',
    'ci/project/p06_dependency_local_prepare.py',
    'ci/project/p06_qualified_warm_control.py',
    'ci/project/p06_qualified_warm_encrypt.py',
    'ci/project/p06_qualified_warm_hosted.py',
    'ci/project/p06_qualified_warm_inputs.py',
    'ci/project/p06_qualified_warm_run.py',
]
NEW_MODULES = [
    'test_p06_builder_initial_closeout',
    'test_p06_control_sigterm_closeout',
    'test_p06_encrypt_descriptor_closeout',
    'test_p06_encrypt_final_directory',
    'test_p06_encrypt_sigterm_closeout',
    'test_p06_hosted_closeout_interruptions',
    'test_p06_hosted_prelaunch_emission',
    'test_p06_initial_checkpoint_closeout',
    'test_p06_input_initial_closeout',
    'test_p06_preparation_initial_closeout',
]
BOUND_PATHS = PRODUCTION + [f'ci/project/{name}.py' for name in NEW_MODULES]
LOG_SOURCES = [
    'recovered-integration.log',
    'closeout-current-focused.log',
    'a022-focused.log',
]
ADDITIONAL_SELECTORS = [
    'test_p06_dependency_build.DependencyBuildTests.test_stage_is_exclusive_and_rejects_aliases',
    'test_p06_dependency_build.DependencyBuildTests.test_pinned_literal_parentheses_do_not_relax_root_or_shell_rules',
    'test_p06_dependency_build.DependencyBuildTests.test_receipt_lock_is_only_permitted_nondocument_and_must_be_empty',
    'test_p06_dependency_build.DependencyBuildTests.test_clean_environment_removes_caller_compiler_selection',
    'test_p06_dependency_build.DependencyBuildTests.test_first_failure_remains_primary_and_no_pass_flag_survives',
    'test_p06_dependency_build.DependencyBuildTests.test_resource_block_retains_original_preparation_and_failure',
    'test_p06_qualified_warm_hosted.HostedCompositionTests',
    'test_p06_dependency_local_execute_review',
    'test_p06_encrypt_publication_review',
    'test_p06_dependency_cancellation.DependencyCancellationTests.test_direct_builder_keeps_worker_thread_execution',
]


def utc():
    return datetime.now(timezone.utc).isoformat()


def hashes(paths):
    return {name: {'sha256': hashlib.sha256((ROOT / name).read_bytes()).hexdigest(),
                   'size_bytes': (ROOT / name).stat().st_size} for name in paths}


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def flatten(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from flatten(test)
        else:
            yield test


def signal_state():
    return {name: signal.getsignal(getattr(signal, name))
            for name in ('SIGINT', 'SIGTERM', 'SIGALRM')}


def process_state():
    return {
        'cwd': str(Path.cwd()),
        'environment_sha256': hashlib.sha256(json.dumps(dict(os.environ), sort_keys=True).encode()).hexdigest(),
        'signal_handlers': {name: repr(handler) for name, handler in signal_state().items()},
        'thread_inventory': [(thread.name, thread.ident) for thread in threading.enumerate()],
    }


def retained_hashes(paths):
    return {str(path): {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                       'size_bytes': path.stat().st_size} for path in paths}


class RecordedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.events = []
        self.test_ids_run = []
        self.success_ids = []
        self.successful_subtests = 0
        self.failed_subtests = 0
        self._started = {}

    def startTest(self, test):
        self.test_ids_run.append(test.id())
        self._started[test.id()] = time.monotonic()
        self.events.append({'event': 'start', 'id': test.id(), 'utc': utc()})
        super().startTest(test)

    def stopTest(self, test):
        self.events.append({'event': 'stop', 'id': test.id(), 'utc': utc(),
                            'duration_seconds': time.monotonic() - self._started[test.id()]})
        super().stopTest(test)

    def addSuccess(self, test):
        self.success_ids.append(test.id())
        self.events.append({'event': 'success', 'id': test.id()})
        super().addSuccess(test)

    def addSubTest(self, test, subtest, err):
        if err is None:
            self.successful_subtests += 1
        else:
            self.failed_subtests += 1
            self.events.append({'event': 'failed_subtest', 'id': test.id(), 'subtest': str(subtest)})
        super().addSubTest(test, subtest, err)

    def addFailure(self, test, err):
        self.events.append({'event': 'failure', 'id': test.id()})
        super().addFailure(test, err)

    def addError(self, test, err):
        self.events.append({'event': 'error', 'id': test.id()})
        super().addError(test, err)


def main():
    start_utc, start_monotonic = utc(), time.monotonic()
    command = ('PYTHONDONTWRITEBYTECODE=1 '
               'TMPDIR=/home/agent/ai-gpu-work-4c990083f078/tmp/a085-work '
               'python3 -B /home/agent/ai-gpu-work-4c990083f078/tmp/a085-integration-runner.py '
               '> /home/agent/ai-gpu-work-4c990083f078/reports/a085-integration.log 2>&1')
    record = {
        'schema_version': 1,
        'agent': 'a085',
        'scope': 'Focused Python host fault-handling integration; no full strict governance or native qualification.',
        'repository': str(ROOT),
        'expected_base_revision': EXPECTED_HEAD,
        'command': command,
        'cwd': str(Path.cwd()),
        'executable': sys.executable,
        'executable_resolved': str(Path(sys.executable).resolve()),
        'python3_which': shutil.which('python3'),
        'python_version': sys.version,
        'argv': list(sys.argv),
        'sys_orig_argv': list(sys.orig_argv),
        'environment': {name: os.environ.get(name) for name in ('PYTHONDONTWRITEBYTECODE', 'TMPDIR')},
        'start_utc': start_utc,
        'source_hash_algorithm': 'SHA256',
        'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'production_paths': PRODUCTION,
        'new_test_modules': NEW_MODULES,
        'full_strict_governance_executed': False,
        'native_workload_executed': False,
        'network_acquisition_executed': False,
        'test_retries': 0,
        'status': 'running',
    }
    result = None
    loader = unittest.TestLoader()
    before_environment = dict(os.environ)
    before_signals = signal_state()
    before_threads = [(thread.name, thread.ident) for thread in threading.enumerate()]
    record['process_state_before'] = process_state()
    retained_paths = [
        ROOT.parent / 'tmp/a052-integration-runner.py',
        BASELINE_REPORT,
        REPORTS / 'a052-integration.log',
        REPORTS / 'a052.txt',
        *(REPORTS / name for name in LOG_SOURCES),
        ROOT / 'docs/project/evidence/p06-closeout-reliability/validation/a030-integration.json',
        *(ROOT / 'docs/project/evidence/p06-closeout-reliability/validation' / name
          for name in ('a052-integration-runner.py', 'a052-integration.json', 'a052-integration.log')),
        *sorted(REPORTS.glob('a080*')),
        *sorted(REPORTS.glob('a081*')),
    ]
    record['retained_receipt_hashes_before'] = retained_hashes(retained_paths)
    try:
        if Path.cwd() != ROOT:
            raise RuntimeError('Tests must run from the source root')
        if os.environ.get('PYTHONDONTWRITEBYTECODE') != '1' or not sys.dont_write_bytecode:
            raise RuntimeError('Bytecode writing must be disabled')
        if os.environ.get('TMPDIR') != str(ROOT.parent / 'tmp/a085-work'):
            raise RuntimeError('Unexpected temporary directory')
        record['base_revision_before'] = git('rev-parse', 'HEAD')
        record['git_status_before'] = git('status', '--short')
        if record['base_revision_before'] != EXPECTED_HEAD:
            raise RuntimeError('Repository base revision changed')
        record['source_hashes_before'] = hashes(BOUND_PATHS)
        sys.path.insert(0, str(ROOT / 'ci/project'))
        selectors = list(NEW_MODULES)
        log_ids = {}
        for name in LOG_SOURCES:
            contents = (REPORTS / name).read_text()
            ids = re.findall(r'^test_\S+ \(([^)]+)\)', contents, re.MULTILINE)
            if not ids or not contents.rstrip().endswith('OK'):
                raise RuntimeError(f'Selection log lacks a passing run: {name}')
            log_ids[name] = ids
            selectors.extend(ids)
        selectors.extend(ADDITIONAL_SELECTORS)
        unique = {}
        loaded = list(flatten(loader.loadTestsFromNames(selectors)))
        for test in loaded:
            unique.setdefault(test.id(), test)
        ids = list(unique)
        new_ids = [identifier for identifier in ids if identifier.split('.')[0] in NEW_MODULES]
        record.update({
            'selection_method': 'unittest.TestLoader.loadTestsFromNames followed by first-occurrence deduplication by TestCase.id()',
            'selection_sources': log_ids,
            'additional_selectors': ADDITIONAL_SELECTORS,
            'selected_test_ids': ids,
            'selected_method_count': len(ids),
            'selected_unique_method_count': len(set(ids)),
            'loaded_method_occurrences_before_deduplication': len(loaded),
            'selected_modules': dict(sorted(collections.Counter(identifier.split('.')[0] for identifier in ids).items())),
            'new_test_ids': new_ids,
            'new_method_count': len(new_ids),
            'new_module_counts': dict(sorted(collections.Counter(identifier.split('.')[0] for identifier in new_ids).items())),
            'loader_errors': list(loader.errors),
        })
        if loader.errors or any(type(test).__name__ == '_FailedTest' for test in unique.values()):
            raise RuntimeError('Test loading failed')
        previous_path = ROOT / 'docs/project/evidence/p06-closeout-reliability/validation/a030-integration.json'
        previous_bytes = previous_path.read_bytes()
        previous = json.loads(previous_bytes)
        retained_ids = [identifier for identifier in ids
                        if identifier.split('.')[0] != 'test_p06_encrypt_final_directory']
        record['previous_integration_receipt'] = {
            'path': str(previous_path.relative_to(ROOT)),
            'sha256': hashlib.sha256(previous_bytes).hexdigest(),
            'selected_unique_methods': previous['selected_unique_method_count'],
            'exact_previous_test_order_preserved': retained_ids == previous['selected_test_ids'],
        }
        record['added_test_ids'] = [identifier for identifier in ids if identifier not in retained_ids]
        if previous['status'] != 'pass' or len(retained_ids) != 227 or retained_ids != previous['selected_test_ids']:
            raise RuntimeError('Selection must preserve the exact prior 227-method order')
        if len(ids) != 228 or len(new_ids) != 44 or len(record['added_test_ids']) != 1:
            raise RuntimeError('Selection must contain exactly 228 unique methods including all 44 new methods')
        baseline_bytes = BASELINE_REPORT.read_bytes()
        baseline = json.loads(baseline_bytes)
        record['a052_selection_comparison'] = {
            'path': str(BASELINE_REPORT),
            'sha256': hashlib.sha256(baseline_bytes).hexdigest(),
            'exact_test_ids_and_order': ids == baseline['selected_test_ids'],
            'exact_new_test_ids_and_order': new_ids == baseline['new_test_ids'],
            'exact_module_counts': record['selected_modules'] == baseline['selected_modules'],
        }
        if (baseline['status'] != 'pass' or len(record['selected_modules']) != 27
                or not all(record['a052_selection_comparison'][name] for name in
                           ('exact_test_ids_and_order', 'exact_new_test_ids_and_order', 'exact_module_counts'))):
            raise RuntimeError('Selection must preserve the exact a052 228 IDs/order, 44 new IDs/order and 27 modules')
        if '--manifest-only' in sys.argv:
            print(json.dumps({key: record[key] for key in ('selected_method_count', 'new_method_count', 'selected_modules', 'new_module_counts', 'loader_errors')}, indent=2))
            return 0
        selected_test_paths = [f'ci/project/{module}.py' for module in record['selected_modules']]
        record['selected_test_hashes_before'] = hashes(selected_test_paths)
        all_bound_paths = list(dict.fromkeys(PRODUCTION + selected_test_paths))
        record['all_unique_source_test_paths'] = all_bound_paths
        record['all_unique_source_test_hashes_before'] = hashes(all_bound_paths)
        baseline_hashes = {**baseline['source_hashes_after'], **baseline['selected_test_hashes_after']}
        current_hashes = record['all_unique_source_test_hashes_before']
        changed_paths = [path for path in current_hashes if current_hashes[path] != baseline_hashes.get(path)]
        record['source_changes_from_a052'] = changed_paths
        record['expected_final_fixture_sha256'] = FINAL_FIXTURE_SHA256
        record['production_hashes_match_a052'] = all(current_hashes[path] == baseline_hashes[path] for path in PRODUCTION)
        if (len(all_bound_paths) != 34 or set(current_hashes) != set(baseline_hashes)
                or changed_paths != [FINAL_FIXTURE]
                or current_hashes[FINAL_FIXTURE]['sha256'] != FINAL_FIXTURE_SHA256):
            raise RuntimeError('The 34 bound files must match a052 except for the reviewed final fixture hash')
        REPORT.write_text(json.dumps(record, indent=2) + '\n')
        print(json.dumps({key: record[key] for key in ('command', 'cwd', 'executable', 'python_version', 'start_utc', 'selected_method_count', 'new_method_count', 'selected_modules')}, indent=2), flush=True)
        record['test_start_utc'] = utc()
        test_started = time.monotonic()
        runner = unittest.TextTestRunner(stream=sys.stdout, verbosity=2,
                                         resultclass=RecordedResult, failfast=True)
        result = runner.run(unittest.TestSuite(unique.values()))
        record['test_duration_seconds'] = time.monotonic() - test_started
        record['test_end_utc'] = utc()
        record['tests_run'] = result.testsRun
        record['test_ids_run'] = result.test_ids_run
        record['successful_test_ids'] = result.success_ids
        record['events'] = result.events
        record['counts'] = {
            'selected_unique_methods': len(ids),
            'executed_methods': result.testsRun,
            'successful_methods': len(result.success_ids),
            'failures': len(result.failures),
            'errors': len(result.errors),
            'skips': len(result.skipped),
            'expected_failures': len(result.expectedFailures),
            'unexpected_successes': len(result.unexpectedSuccesses),
            'loader_errors': len(loader.errors),
            'successful_subtests': result.successful_subtests,
            'failed_subtests': result.failed_subtests,
        }
        for name in ('failures', 'errors', 'skipped', 'expectedFailures'):
            record[name] = [{'id': test.id(), 'detail': detail} for test, detail in getattr(result, name)]
        record['unexpectedSuccesses'] = [test.id() for test in result.unexpectedSuccesses]
        record['selected_test_hashes_after'] = hashes(selected_test_paths)
        record['source_hashes_after'] = hashes(BOUND_PATHS)
        record['all_unique_source_test_hashes_after'] = hashes(all_bound_paths)
        record['all_unique_source_test_bytes_unchanged'] = record['all_unique_source_test_hashes_before'] == record['all_unique_source_test_hashes_after']
        record['source_bytes_unchanged'] = record['source_hashes_before'] == record['source_hashes_after']
        record['selected_test_bytes_unchanged'] = record['selected_test_hashes_before'] == record['selected_test_hashes_after']
        record['base_revision_after'] = git('rev-parse', 'HEAD')
        record['git_status_after'] = git('status', '--short')
        record['state_restored'] = {
            'cwd': Path.cwd() == ROOT,
            'environment': dict(os.environ) == before_environment,
            'signal_handlers': signal_state() == before_signals,
            'thread_inventory': [(thread.name, thread.ident) for thread in threading.enumerate()] == before_threads,
        }
        record['process_state_after'] = process_state()
        record['retained_receipt_hashes_after'] = retained_hashes(retained_paths)
        record['retained_receipt_bytes_unchanged'] = record['retained_receipt_hashes_before'] == record['retained_receipt_hashes_after']
        strict_counts = all(record['counts'][name] == 0 for name in
                            ('failures', 'errors', 'skips', 'expected_failures', 'unexpected_successes', 'loader_errors', 'failed_subtests'))
        record['status'] = 'pass' if (
            result.wasSuccessful() and strict_counts and result.testsRun == len(ids)
            and result.test_ids_run == ids and len(result.success_ids) == len(ids)
            and record['source_bytes_unchanged'] and record['selected_test_bytes_unchanged']
            and record['all_unique_source_test_bytes_unchanged'] and record['retained_receipt_bytes_unchanged']
            and result.successful_subtests == 331
            and record['base_revision_after'] == EXPECTED_HEAD
            and all(record['state_restored'].values())
        ) else 'fail'
    except BaseException as error:
        record['status'] = 'error'
        record['runner_error'] = {'type': type(error).__name__, 'message': str(error), 'traceback': traceback.format_exc()}
        record['loader_errors'] = list(loader.errors)
        traceback.print_exc()
        if 'source_hashes_before' in record:
            record['source_hashes_after'] = hashes(BOUND_PATHS)
            record['source_bytes_unchanged'] = record['source_hashes_before'] == record['source_hashes_after']
    finally:
        if '--manifest-only' not in sys.argv:
            record['end_utc'] = utc()
            record['duration_seconds'] = time.monotonic() - start_monotonic
            record['exit_code'] = 0 if record['status'] == 'pass' else 1
            REPORT.write_text(json.dumps(record, indent=2) + '\n')
            counts = record.get('counts', {})
            summary = (
                f"Agent a085 — final focused integration after a080/a081: {record['status'].upper()}.\n"
                f"Base: {EXPECTED_HEAD}, plus uncommitted changes.\n"
                f"Exact a052 selection/order: {counts.get('executed_methods', 0)} methods, {len(record.get('selected_modules', {}))} modules, "
                f"all {record.get('new_method_count', 0)} new methods; {counts.get('successful_subtests', 0)} successful subtests. "
                f"Failures/errors/skips/expected failures/unexpected successes/loader errors/failed subtests: "
                f"{counts.get('failures', 0)}/{counts.get('errors', 0)}/{counts.get('skips', 0)}/"
                f"{counts.get('expected_failures', 0)}/{counts.get('unexpected_successes', 0)}/{counts.get('loader_errors', len(loader.errors))}/{counts.get('failed_subtests', 0)}.\n"
                f"Exit {record['exit_code']}; test duration {record.get('test_duration_seconds', 0):.3f}s; total {record['duration_seconds']:.3f}s.\n"
                f"All 34 source/test before/after hashes unchanged={record.get('all_unique_source_test_bytes_unchanged', False)}; "
                f"prior receipts unchanged={record.get('retained_receipt_bytes_unchanged', False)}. "
                f"Cwd/environment/signals/threads restored={all(record.get('state_restored', {'missing': False}).values())}.\n"
                "Seven production files match a052; sole intervening file change is the reviewed prelaunch-emission fixture.\n"
                "One python3 -B invocation with task TMPDIR; no retries, source/test/docs edits, native/network work or commit. "
                "Focused development evidence only, not strict governance or native qualification.\n"
                "Exact command, UTC, interpreter, IDs, timings and hashes: a085-integration.json; raw output: a085-integration.log.\n"
            )
            SUMMARY.write_text(summary)
            print(json.dumps({key: record.get(key) for key in ('status', 'counts', 'source_bytes_unchanged', 'selected_test_bytes_unchanged', 'state_restored', 'end_utc', 'duration_seconds', 'exit_code')}, indent=2), flush=True)
    return record.get('exit_code', 1)


if __name__ == '__main__':
    raise SystemExit(main())
