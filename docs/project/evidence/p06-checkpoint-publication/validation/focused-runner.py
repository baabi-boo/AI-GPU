#!/usr/bin/env python3
"""One focused development invocation; not strict governance qualification."""

from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import traceback
import unittest


ROOT = Path('/tmp/ai-gpu-2bfab0261c05/repo')
OUTPUT = Path('/tmp/ai-gpu-2bfab0261c05/validation')
JSON_PATH = OUTPUT / 'a023-focused-results.json'
LOG_PATH = OUTPUT / 'a023-focused.log'
EXPECTED_HEAD = '93bb3f0342eff0b469a0da06cb067916af7c539e'
MODULES = [
    'test_checkpoint_write_failures',
    'test_checkpoint_ownership',
    'test_checkpoint_directory_access',
    'test_p06_checkpoint_run_recovery',
    'test_p06_checkpoint_input_recovery',
    'test_p06_checkpoint_prepare_build',
    'test_p02_matrix',
    'test_p02_wgmma_matrix',
    'test_p04_ci_prepare',
    'test_p06_qualified_warm_run',
    'test_p06_qualified_warm_inputs',
    'test_p06_dependency_local_prepare',
    'test_p06_initial_checkpoint_closeout',
    'test_p06_input_initial_closeout',
    'test_p06_preparation_initial_closeout',
    'test_p06_builder_initial_closeout',
]


def now():
    return datetime.now(timezone.utc).isoformat()


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*arguments):
    result = subprocess.run(['git', '-C', str(ROOT), *arguments],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, check=True)
    return result.stdout


def git_state():
    return {
        'head': git('rev-parse', 'HEAD').strip(),
        'status_porcelain_v1': git('status', '--porcelain=v1', '--untracked-files=all'),
        'branch': git('status', '--short', '--branch'),
    }


def process_state():
    signals = {}
    for value in sorted(signal.valid_signals(), key=int):
        try:
            signals[str(int(value))] = repr(signal.getsignal(value))
        except (OSError, ValueError) as error:
            signals[str(int(value))] = type(error).__name__ + ': ' + str(error)
    descriptors = {}
    for entry in sorted(Path('/proc/self/fd').iterdir(), key=lambda p: int(p.name)):
        try:
            fd = int(entry.name)
            target = os.readlink(entry)
            status = os.fstat(fd)
            descriptors[entry.name] = {
                'target': target, 'device': status.st_dev, 'inode': status.st_ino,
                'mode': status.st_mode, 'fd_flags': fcntl.fcntl(fd, fcntl.F_GETFD),
                'status_flags': fcntl.fcntl(fd, fcntl.F_GETFL),
            }
        except OSError:
            pass  # /proc's enumeration descriptor is already closed.
    return {
        'cwd': os.getcwd(),
        'environment_sha256_by_key': {
            key: hashlib.sha256(value.encode()).hexdigest()
            for key, value in sorted(os.environ.items())
        },
        'signal_handlers': signals,
        'blocked_signals': sorted(map(int, signal.pthread_sigmask(signal.SIG_BLOCK, []))),
        'threads': sorted([
            {'name': item.name, 'ident': item.ident, 'native_id': item.native_id,
             'daemon': item.daemon, 'alive': item.is_alive()}
            for item in threading.enumerate()
        ], key=lambda item: (item['name'], item['ident'] or 0)),
        'linux_task_ids': sorted(int(item.name) for item in Path('/proc/self/task').iterdir()),
        'file_descriptors': descriptors,
    }


def state_delta(before, after):
    delta = {}
    for key in before:
        if before[key] == after[key]:
            continue
        if isinstance(before[key], dict):
            old, new = before[key], after[key]
            delta[key] = {
                'added': {name: new[name] for name in new.keys() - old.keys()},
                'removed': {name: old[name] for name in old.keys() - new.keys()},
                'changed': {
                    name: {'before': old[name], 'after': new[name]}
                    for name in old.keys() & new.keys() if old[name] != new[name]
                },
            }
        else:
            delta[key] = {'before': before[key], 'after': after[key]}
    return delta


def local_modules():
    found = {}
    for name, module in tuple(sys.modules.items()):
        location = getattr(module, '__file__', None)
        if not isinstance(location, str):
            continue
        path = Path(location).resolve()
        if path.suffix == '.pyc':
            try:
                path = Path(importlib.util.source_from_cache(str(path)))
            except ValueError:
                pass
        try:
            relative = str(path.relative_to(ROOT))
        except ValueError:
            continue
        found.setdefault(relative, []).append(name)
    return {name: sorted(aliases) for name, aliases in sorted(found.items())}


def flatten(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from flatten(test)
        else:
            yield test


class RecordedResult(unittest.TextTestResult):
    def __init__(self, *arguments, **keywords):
        super().__init__(*arguments, **keywords)
        self.started_ids = []
        self.completed_ids = []
        self.events = []
        self.subtests = []

    def startTest(self, test):
        self.started_ids.append(test.id())
        super().startTest(test)

    def stopTest(self, test):
        self.completed_ids.append(test.id())
        super().stopTest(test)

    def addSuccess(self, test):
        self.events.append({'id': test.id(), 'outcome': 'success'})
        super().addSuccess(test)

    def addFailure(self, test, error):
        self.events.append({'id': test.id(), 'outcome': 'failure'})
        super().addFailure(test, error)

    def addError(self, test, error):
        self.events.append({'id': test.id(), 'outcome': 'error'})
        super().addError(test, error)

    def addSkip(self, test, reason):
        entry = {'id': test.id(), 'outcome': 'skip', 'reason': reason}
        self.events.append(entry)
        if isinstance(test, unittest.case._SubTest):
            self.subtests.append(dict(entry, parent_id=test.test_case.id()))
        super().addSkip(test, reason)

    def addExpectedFailure(self, test, error):
        self.events.append({'id': test.id(), 'outcome': 'expected_failure'})
        super().addExpectedFailure(test, error)

    def addUnexpectedSuccess(self, test):
        self.events.append({'id': test.id(), 'outcome': 'unexpected_success'})
        super().addUnexpectedSuccess(test)

    def addSubTest(self, test, subtest, error):
        outcome = ('success' if error is None else
                   'failure' if issubclass(error[0], test.failureException) else 'error')
        self.subtests.append({'id': subtest.id(), 'parent_id': test.id(), 'outcome': outcome})
        super().addSubTest(test, subtest, error)


class RecordedRunner(unittest.TextTestRunner):
    recorded_result = None

    def _makeResult(self):
        self.recorded_result = super()._makeResult()
        return self.recorded_result


def save(document):
    JSON_PATH.write_text(json.dumps(document, indent=2, sort_keys=True) + '\n')


def main():
    started = time.monotonic()
    document = {
        'schema': 'a023-focused-development-validation-v1',
        'started_at': now(), 'root': str(ROOT), 'expected_head': EXPECTED_HEAD,
        'scope': 'One selected-module host-side unittest invocation; no governance or native qualification.',
        'invocation': {
            'argv': list(sys.argv), 'python': sys.executable, 'python_version': sys.version,
            'cwd': os.getcwd(), 'uid': os.getuid(), 'euid': os.geteuid(),
            'PYTHONDONTWRITEBYTECODE': os.environ.get('PYTHONDONTWRITEBYTECODE'),
            'sys_dont_write_bytecode': sys.dont_write_bytecode,
            'module_selection': MODULES,
            'runner_sha256': sha256(Path(__file__)),
        },
        'result': None,
    }
    if Path.cwd() != ROOT or os.environ.get('PYTHONDONTWRITEBYTECODE') != '1' or not sys.dont_write_bytecode:
        raise RuntimeError('Wrong source cwd or bytecode setting')
    document['git_before'] = git_state()
    if document['git_before']['head'] != EXPECTED_HEAD:
        raise RuntimeError('Unexpected source HEAD')
    tracked = git('ls-files', '--cached', '--others', '--exclude-standard', '-z').split('\0')
    python_paths = sorted({name for name in tracked if name.endswith('.py') and (ROOT / name).is_file()})
    baseline_hashes = {name: sha256(ROOT / name) for name in python_paths}
    selected_paths = ['ci/project/' + name + '.py' for name in MODULES]
    required_paths = selected_paths + ['ci/project/p02_matrix.py']
    for name in required_paths:
        baseline_hashes.setdefault(name, sha256(ROOT / name))
    document['python_inventory_before_count'] = len(baseline_hashes)
    document['all_repository_python_sha256_before'] = baseline_hashes
    sys.path.insert(0, str(ROOT / 'ci/project'))
    with LOG_PATH.open('x', buffering=1) as log, redirect_stdout(log), redirect_stderr(log):
        print('A023 focused development unittest invocation')
        print('HEAD:', document['git_before']['head'])
        print('Initial git status:', repr(document['git_before']['status_porcelain_v1']))
        print('Python:', sys.version)
        print('Modules:', ', '.join(MODULES))
        document['process_before_loading'] = process_state()
        loader = unittest.TestLoader()
        suite = loader.loadTestsFromNames(MODULES)
        test_ids = [test.id() for test in flatten(suite)]
        counts = Counter(test_ids)
        document['selection'] = {
            'module_count': len(MODULES), 'test_count': len(test_ids),
            'test_ids': test_ids, 'unique_test_count': len(counts),
            'duplicate_test_ids': {name: count for name, count in counts.items() if count > 1},
            'loader_errors': list(loader.errors),
            'module_origins': {name: str(Path(sys.modules[name].__file__).resolve())
                               for name in MODULES if name in sys.modules},
        }
        document['local_modules_before_execution'] = local_modules()
        document['process_before_execution'] = process_state()
        document['import_state_delta'] = state_delta(document['process_before_loading'],
                                                     document['process_before_execution'])
        print('Selected tests:', len(test_ids), '; unique:', len(counts))
        print('Duplicate test IDs:', document['selection']['duplicate_test_ids'])
        save(document)
        result = None
        runner = RecordedRunner(stream=log, verbosity=2, resultclass=RecordedResult)
        try:
            result = runner.run(suite)
        except BaseException:
            document['runner_exception'] = traceback.format_exc()
            traceback.print_exc(file=log)
        finally:
            result = runner.recorded_result
            document['process_after_execution'] = process_state()
            document['execution_state_delta'] = state_delta(document['process_before_execution'],
                                                            document['process_after_execution'])
            document['whole_process_state_delta'] = state_delta(document['process_before_loading'],
                                                                document['process_after_execution'])
            document['local_modules_after_execution'] = local_modules()
            relevant_paths = sorted(set(required_paths) | set(document['local_modules_before_execution'])
                                    | set(document['local_modules_after_execution']))
            document['source_hashes'] = {
                name: {
                    'before': baseline_hashes.get(name),
                    'after': sha256(ROOT / name) if (ROOT / name).is_file() else None,
                    'selected_test': name in selected_paths,
                    'production_p02_matrix': name == 'ci/project/p02_matrix.py',
                    'loaded_aliases': document['local_modules_after_execution'].get(name, []),
                }
                for name in relevant_paths
            }
            document['hash_mismatches'] = {
                name: values for name, values in document['source_hashes'].items()
                if values['before'] != values['after']
            }
            document['unbaselined_loaded_paths'] = [
                name for name in relevant_paths if name not in baseline_hashes
            ]
            document['git_after'] = git_state()
            document['finished_at'] = now()
            document['elapsed_seconds'] = time.monotonic() - started
            if result is not None:
                subtest_counts = Counter(item['outcome'] for item in result.subtests)
                executed_counts = Counter(result.started_ids)
                document['result'] = {
                    'wasSuccessful': result.wasSuccessful(), 'testsRun': result.testsRun,
                    'failures_count': len(result.failures), 'errors_count': len(result.errors),
                    'skips_count': len(result.skipped),
                    'expected_failures_count': len(result.expectedFailures),
                    'unexpected_successes_count': len(result.unexpectedSuccesses),
                    'successful_test_events': sum(item['outcome'] == 'success' for item in result.events),
                    'subtests_count': len(result.subtests),
                    'subtest_counts': {key: subtest_counts.get(key, 0)
                                       for key in ['success', 'failure', 'error', 'skip']},
                    'started_ids': result.started_ids, 'completed_ids': result.completed_ids,
                    'duplicate_executed_test_ids': {name: count for name, count in executed_counts.items() if count > 1},
                    'selected_ids_not_started': sorted(set(test_ids) - set(result.started_ids)),
                    'unselected_started_ids': sorted(set(result.started_ids) - set(test_ids)),
                    'events': result.events, 'subtests': result.subtests,
                    'failures': [{'id': test.id(), 'traceback': detail} for test, detail in result.failures],
                    'errors': [{'id': test.id(), 'traceback': detail} for test, detail in result.errors],
                    'skips': [{'id': test.id(), 'reason': reason} for test, reason in result.skipped],
                }
            save(document)
            print('A023_FINAL_RESULT:', json.dumps({
                'testsRun': document['result']['testsRun'] if document['result'] else None,
                'failures': document['result']['failures_count'] if document['result'] else None,
                'errors': document['result']['errors_count'] if document['result'] else None,
                'skips': document['result']['skips_count'] if document['result'] else None,
                'subtests': document['result']['subtests_count'] if document['result'] else None,
                'hash_mismatch_count': len(document['hash_mismatches']),
                'execution_state_delta': document['execution_state_delta'],
                'elapsed_seconds': document['elapsed_seconds'],
            }, sort_keys=True))
    success = (result is not None and result.wasSuccessful()
               and not document.get('runner_exception') and not document['hash_mismatches'])
    print(json.dumps({'json': str(JSON_PATH), 'log': str(LOG_PATH),
                      'wasSuccessful': result.wasSuccessful() if result else False,
                      'testsRun': result.testsRun if result else None}))
    return 0 if success else 1


if __name__ == '__main__':
    raise SystemExit(main())
