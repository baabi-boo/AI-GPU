# SPDX-License-Identifier: Apache-2.0
"""Run one immutable candidate's full governance suite with retained bounds."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


GIB = 1024 ** 3
ROOT = Path('/workspace/p06-candidate-governance')
OUTPUT = Path('/workspace/p06-candidate-governance-results')
CMAKE_BIN = Path('/workspace/p06-build-tools/cmake/data/bin')


def now():
    return datetime.now(timezone.utc).isoformat()


def identity(path):
    body = path.read_bytes()
    return {'path': str(path), 'size_bytes': len(body),
            'sha256': hashlib.sha256(body).hexdigest()}


def git(*args):
    result = subprocess.run(['git', '--no-optional-locks', '-C', str(ROOT), *args],
                            capture_output=True, text=True, timeout=30, check=True)
    return result.stdout.strip()


def source_state():
    return {'revision': git('rev-parse', 'HEAD'),
            'tree': git('rev-parse', 'HEAD^{tree}'),
            'status': git('status', '--porcelain', '--untracked-files=all'),
            'python_sources': [identity(path) for path in sorted((ROOT / 'ci/project').glob('*.py'))]}


def write_new(path, document):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(document, stream, indent=2)
        stream.write('\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--tree', required=True)
    args = parser.parse_args()
    if not all(re.fullmatch(r'[0-9a-f]{40}', value) for value in (args.revision, args.tree)):
        raise ValueError('revision and tree must be exact Git identities')
    if sys.version_info[:2] != (3, 12):
        raise ValueError('the reviewed governance interpreter is Python 3.12')
    if ROOT.resolve(strict=True) != ROOT or not ROOT.is_dir():
        raise ValueError('candidate worktree is absent or resolves elsewhere')
    if OUTPUT.exists():
        raise ValueError('governance result directory must be fresh')
    before = source_state()
    if before['revision'] != args.revision or before['tree'] != args.tree or before['status']:
        raise ValueError('candidate revision/tree differs or worktree is not clean')

    sys.path.insert(0, str(ROOT / 'ci/project'))
    import baseline_process
    import preflight
    for module in (baseline_process, preflight):
        expected = ROOT / 'ci/project' / (module.__name__ + '.py')
        if Path(module.__file__).resolve(strict=True) != expected:
            raise ValueError('governance helper origin differs')

    resources = {'observed_at_utc': now(),
                 'available_memory_bytes': preflight.available_memory_bytes(),
                 'free_disk_bytes': shutil.disk_usage(ROOT).free,
                 'affinity_cpus': len(os.sched_getaffinity(0)),
                 'minimum_available_memory_bytes': 6 * GIB,
                 'minimum_free_disk_bytes': 15 * GIB,
                 'aggregate_concurrent_supervisor_rss_ceiling_bytes': 6 * GIB,
                 'scope': 'governance 2 GiB plus either foundation governance or separate host diagnostic 4 GiB'}
    if (resources['available_memory_bytes'] or 0) < 6 * GIB:
        raise ValueError('available memory is below the aggregate 6 GiB launch requirement')
    if resources['free_disk_bytes'] < 15 * GIB:
        raise ValueError('candidate full governance needs a 15 GiB disk reserve')

    selected_environment = {'PYTHONPATH': str(ROOT / 'ci/project'),
                            'PYTHONDONTWRITEBYTECODE': '1',
                            'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1',
                            'MKL_NUM_THREADS': '1', 'NUMEXPR_NUM_THREADS': '1',
                            'CMAKE_BUILD_PARALLEL_LEVEL': '2', 'MAKEFLAGS': '-j2'}
    environment = dict(os.environ, **selected_environment)
    environment['PATH'] = str(CMAKE_BIN) + os.pathsep + os.environ['PATH']
    tools = {}
    for name in ('git', 'make', 'cmake', 'cc', 'c++'):
        selected = shutil.which(name, path=environment['PATH'])
        if selected is None:
            raise ValueError('missing governance host tool: ' + name)
        resolved = Path(selected).resolve(strict=True)
        result = subprocess.run([selected, '--version'], env=environment,
                                capture_output=True, text=True, timeout=10, check=True)
        if len(result.stdout.encode()) + len(result.stderr.encode()) > 65536:
            raise ValueError('tool version observation exceeded its bound')
        tools[name] = {'selected_path': selected, 'resolved_executable': identity(resolved),
                       'version_stdout': result.stdout, 'version_stderr': result.stderr,
                       'exit_code': result.returncode}
    if not tools['cmake']['version_stdout'].startswith('cmake version 3.22.6\n'):
        raise ValueError('CMake version differs from the reviewed 3.22.6 tool')
    OUTPUT.mkdir(mode=0o700)
    argv = [sys.executable, '-B', '-m', 'unittest', 'discover',
            '-s', 'ci/project', '-p', 'test_*.py', '-v']
    budget = {'timeout_seconds': 4200, 'min_free_bytes': 15 * GIB,
              'max_rss_bytes': 2 * GIB, 'max_log_bytes': 16 * 1024 ** 2}
    launch = {'schema_version': 1, 'started_at_utc': now(),
              'scope': 'Full project-governance unit discovery on one immutable candidate; no fresh native original or phase qualification is claimed.',
              'source_before': before, 'argv': argv, 'cwd': str(ROOT),
              'python_version': sys.version, 'python_executable': identity(Path(sys.executable).resolve(strict=True)),
              'tools': tools, 'selected_environment': selected_environment,
              'path_prefix': str(CMAKE_BIN), 'resource_inventory': resources,
              'budget': budget, 'runner': identity(Path(__file__).resolve(strict=True)),
              'qualified': False, 'ready_for_warm': False, 'warm_execution': False,
              'full_warm_coverage': False, 'acceptance_claimed': False,
              'phase_acceptance': False, 'performance_acceptance': False}
    write_new(OUTPUT / 'launch.json', launch)
    result = baseline_process.run_bounded(argv, ROOT, environment, OUTPUT / 'unittest.log',
                                         resource_paths=(ROOT, OUTPUT), **budget)
    after = source_state()
    stable = before == after
    raw_log = (OUTPUT / 'unittest.log').read_text(encoding='utf-8')
    summary = re.search(r'^Ran (\d+) tests in ([0-9.]+)s\n\n([^\n]+)', raw_log, re.MULTILINE)
    receipt = {**launch, 'finished_at_utc': now(), 'source_after': after,
               'sources_stable': stable, 'supervisor': result,
               'log': identity(OUTPUT / 'unittest.log'),
               'test_summary': None if summary is None else {'tests': int(summary.group(1)),
                   'duration_seconds': float(summary.group(2)), 'terminal': summary.group(3)},
               'passed': result['outcome'] == 'pass' and stable and summary is not None
                   and summary.group(3) == 'OK'}
    write_new(OUTPUT / 'receipt.json', receipt)
    print(json.dumps({'receipt': str(OUTPUT / 'receipt.json'), 'passed': receipt['passed'],
                      'supervisor': result, 'test_summary': receipt['test_summary'],
                      'sources_stable': stable}))
    return 0 if receipt['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
