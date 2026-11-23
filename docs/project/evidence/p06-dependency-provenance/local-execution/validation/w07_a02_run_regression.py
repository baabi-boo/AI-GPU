"""Run the requested frozen-checkpoint reader regression without editing source."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


SOURCE = Path('/workspace/p06-reader-regression-source')
OUTPUT = Path('/workspace/scratch/279b6658611e/validation')
REVISION = '7251f078972c1d524de06d069e91b014b55896f5'
TREE = 'c44b5a93ab3aabaf2438e9e7d102339c9dc80542'
MODULES = [
    'test_p06_dependency_build',
    'test_p06_dependency_receipt',
    'test_p06_dependency_admission',
    'test_p06_dependency_replay',
    'test_p06_dependency_native_replay',
    'test_p06_dependency_control_replay',
    'test_p06_dependency_local_replay',
    'test_p06_dependency_control_host_bin_review',
    'test_p06_dependency_retention_order_review',
    'test_p06_dependency_substitution_retention_review',
]


def now():
    return datetime.now(timezone.utc).isoformat()


def git(*arguments):
    return subprocess.check_output(['git', '-C', str(SOURCE), *arguments], text=True).strip()


def identity(path):
    body = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(body).hexdigest(), 'size_bytes': len(body)}


def source_state():
    files = []
    for relative in git('ls-files', 'ci/project').splitlines():
        if relative.endswith(('.py', '.json')):
            row = identity(SOURCE / relative)
            row['path'] = relative
            files.append(row)
    return {'revision': git('rev-parse', 'HEAD'), 'tree': git('rev-parse', 'HEAD^{tree}'),
            'status': git('status', '--porcelain', '--untracked-files=all'),
            'submodules': git('submodule', 'status', '--recursive'),
            'files': files}


before = source_state()
assert before['revision'] == REVISION and before['tree'] == TREE
assert before['status'] == ''
assert all(not line.startswith(('-', '+', 'U')) for line in before['submodules'].splitlines())
assert len(before['submodules'].splitlines()) == 8
environment = dict(os.environ)
environment['PATH'] = '/workspace/p06-build-tools/cmake/data/bin:' + environment['PATH']
environment['PYTHONDONTWRITEBYTECODE'] = '1'
environment['PYTHONPATH'] = 'ci/project'
command = [sys.executable, '-B', '-m', 'unittest', '-v', *MODULES]
cmake = subprocess.check_output(['which', 'cmake'], env=environment, text=True).strip()
assert cmake == '/workspace/p06-build-tools/cmake/data/bin/cmake'
log_path = OUTPUT / 'w07_a02-affected-reader-regression.log'
result_path = OUTPUT / 'w07_a02-affected-reader-regression.json'
identities_path = OUTPUT / 'w07_a02-source-identities.json'
record = {'schema_version': 1, 'scope': 'Affected reader regression at the corrected source checkpoint',
          'started_at': now(), 'finished_at': None, 'state': 'running', 'argv': command,
          'cwd': str(SOURCE), 'modules': MODULES, 'expected_revision': REVISION, 'expected_tree': TREE,
          'environment_overrides': {key: environment[key] for key in ('PYTHONPATH', 'PYTHONDONTWRITEBYTECODE')},
          'path_prefix': '/workspace/p06-build-tools/cmake/data/bin',
          'python': identity(Path(sys.executable).resolve()), 'python_version': sys.version,
          'cmake': identity(Path(cmake).resolve()), 'status_before': before['status'],
          'source_identity_file': identities_path.name,
          'native_gpu_execution_established': False, 'qualification_or_acceptance_claimed': False,
          'log': log_path.name}
identities_path.write_text(json.dumps({'before': before}, indent=2) + '\n')
result_path.write_text(json.dumps(record, indent=2) + '\n')
begun = time.monotonic()
with log_path.open('wb') as stream:
    child = subprocess.run(command, cwd=SOURCE, env=environment, stdout=stream,
                           stderr=subprocess.STDOUT)
elapsed = time.monotonic() - begun
after = source_state()
identities_path.write_text(json.dumps({'before': before, 'after': after}, indent=2) + '\n')
text = log_path.read_text(errors='replace')
summary = re.findall(r'^Ran (\d+) tests? in ([0-9.]+)s$', text, re.MULTILINE)
record.update(state='finished', finished_at=now(), duration_seconds=elapsed,
              exit_code=child.returncode, source_unchanged=before == after,
              status_after=after['status'], log_identity=identity(log_path),
              source_identity=identity(identities_path),
              tests_run=int(summary[-1][0]) if summary else None,
              unittest_duration_seconds=float(summary[-1][1]) if summary else None,
              failure_lines=[line for line in text.splitlines()
                             if line.endswith((' ... FAIL', ' ... ERROR'))],
              terminal_summary=text.splitlines()[-8:])
record['outcome'] = ('pass' if child.returncode == 0 and before == after and summary
                     and re.search(r'^OK(?: \([^\n]+\))?$', text, re.MULTILINE) else 'fail')
result_path.write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record, indent=2))
raise SystemExit(0 if record['outcome'] == 'pass' else 1)
