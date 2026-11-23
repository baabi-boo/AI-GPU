import argparse
import datetime
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

sys.dont_write_bytecode = True
parser = argparse.ArgumentParser()
parser.add_argument('--source', type=Path, required=True)
parser.add_argument('--revision', required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
root = args.source.resolve(strict=True)
out = args.output.absolute()
out.mkdir(parents=True, exist_ok=False)
scripts = out / 'scripts'
scripts.mkdir()
runner = out / 'runner'
runner.mkdir()
environment_file = out / 'github-env'
environment_file.touch()
workflow_path = '.github/workflows/p06-managed-preflight-replay.yml'

def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def git(*arguments):
    return subprocess.check_output(['git', *arguments], cwd=root, text=True).strip()

def digest(body):
    return hashlib.sha256(body).hexdigest()

def resources():
    memory = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
    return {'free_disk_bytes': shutil.disk_usage(root).free,
            'available_memory_bytes': int(memory['MemAvailable'].split()[0]) * 1024}

def source_identities():
    names = [path.relative_to(root).as_posix() for path in (root / 'ci/project').glob('*.py')]
    names.extend((workflow_path, 'ci/gen_config.py', 'VX_config.toml', 'VX_types.toml',
                  'profiles/p02-tfr.json',
                  'docs/project/evidence/p05-torch/reviews/archive_reader.py'))
    rows = []
    for name in sorted(names):
        body = (root / name).read_bytes()
        retained = subprocess.check_output(['git', 'show', args.revision + ':' + name], cwd=root)
        if body != retained:
            raise RuntimeError('Source differs from selected immutable commit: ' + name)
        rows.append({'path': name, 'sha256': digest(body), 'size_bytes': len(body)})
    return rows

before = git('status', '--porcelain', '--untracked-files=all')
if git('rev-parse', 'HEAD') != args.revision or before:
    raise SystemExit('Source is not a clean checkout of the selected commit')
available = resources()
if available['free_disk_bytes'] < 1024**3:
    raise SystemExit('Governance temporary-storage reserve is below 1 GiB')
if sys.version_info[:2] != (3, 12):
    raise SystemExit('Selected interpreter must be CPython 3.12')
sys.path.insert(0, str(root / 'ci/project'))
from test_p05_ci_workflow import children, script, steps, workflow

document = workflow(root / workflow_path)
job = children(children(document, 'jobs', 2), 'replay', 4)
selected = [(step['name'][0], script(step) + '\n') for step in steps(job) if 'run' in step]
expected_names = [
    'Retain replay identity and verify pinned inputs',
    'Replay the original successful archive',
    'Require the original failed archive to remain rejected',
    'Test the inert replay and source derivation',
]
if [name for name, _ in selected] != expected_names:
    raise SystemExit('Workflow run-step inventory changed')
manual = []
lines = (root / workflow_path).read_text().splitlines()
for index, line in enumerate(lines):
    if line == '        run: |':
        body = []
        for following in lines[index + 1:]:
            if following.startswith('          '):
                body.append(following[10:])
            elif not following.strip():
                body.append('')
            else:
                break
        manual.append('\n'.join(body).rstrip('\n') + '\n')
if manual != [body for _, body in selected]:
    raise SystemExit('Independent literal-block extraction differs')

synthetic = {
    'GITHUB_SHA': args.revision, 'GITHUB_EVENT_NAME': 'workflow_dispatch',
    'GITHUB_RUN_ID': 'local-w08-a02', 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_JOB': 'replay',
    'GITHUB_REPOSITORY': 'baabi-boo/AI-GPU', 'GITHUB_REF': 'refs/heads/master',
    'GITHUB_WORKSPACE': str(root), 'GITHUB_ENV': str(environment_file),
    'RUNNER_TEMP': str(runner),
}
environment = dict(os.environ)
for inherited_name in ('PYTHONPATH', 'PYTHONHOME', 'BASH_ENV', 'ENV'):
    environment.pop(inherited_name, None)
environment.update(synthetic)
environment.update(PYTHONDONTWRITEBYTECODE='1',
                   PATH=str(Path(sys.executable).parent) + os.pathsep + os.defpath)
bash = shutil.which('bash', path=os.defpath)
if bash is None:
    raise SystemExit('Bash is unavailable')
receipt = {
    'schema_version': 1, 'scope': 'local-execution-of-dedicated-replay-workflow-run-steps',
    'source_revision': args.revision, 'source_tree': git('rev-parse', 'HEAD^{tree}'),
    'source_root': str(root), 'workflow_path': workflow_path,
    'workflow_sha256': digest((root / workflow_path).read_bytes()),
    'python_version': sys.version, 'python_executable': sys.executable,
    'started_at': now(), 'resources_before': available, 'git_status_before': before,
    'synthetic_local_environment': synthetic, 'hosted_execution': 'not_run',
    'checkout_action': 'not_run_clean_worktree_supplied', 'upload_artifact_action': 'not_run',
    'native_gpu_execution': 'not_run', 'retained_code_executed': False,
    'dependency_compilation_provenance_verified': False,
    'qualified': False, 'ready_for_warm': False, 'warm_execution': False,
    'full_warm_coverage': False, 'acceptance_claimed': False,
    'phase_acceptance': False, 'performance_acceptance': False,
    'job_timeout_seconds': 1200, 'commands': [], 'outcome': 'running',
    'source_identities_before': source_identities(),
    'limitations': [
        'This executes the four workflow shell blocks locally, not GitHub-hosted Actions.',
        'Synthetic CI environment values do not identify an actual hosted run.',
        'Checkout and artifact-upload actions are not executed by this local harness.',
        'The focused test selection is not the complete project governance suite.',
        'Original archive replay does not establish new native execution or qualification.',
    ],
}

def save():
    (out / 'receipt.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')

save()
start = time.monotonic()
for index, (name, body) in enumerate(selected, 1):
    script_path = scripts / ('step-' + str(index) + '.sh')
    script_path.write_text(body)
    log_path = out / ('step-' + str(index) + '.log')
    command = [bash, '--noprofile', '--norc', '-e', '-o', 'pipefail', str(script_path)]
    remaining = 1200 - (time.monotonic() - start)
    record = {'name': name, 'argv': command, 'script': 'scripts/' + script_path.name,
              'script_sha256': digest(body.encode()), 'log': log_path.name,
              'started_at': now(), 'remaining_job_budget_seconds': remaining}
    receipt['commands'].append(record)
    save()
    step_start = time.monotonic()
    with log_path.open('wb') as log:
        process = subprocess.Popen(command, cwd=root, env=environment,
                                   stdin=subprocess.DEVNULL, stdout=log,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        try:
            record['exit_code'] = process.wait(timeout=max(0.001, remaining))
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            record['exit_code'] = None
            record['timed_out'] = True
    record.update(elapsed_seconds=round(time.monotonic() - step_start, 3), finished_at=now())
    log_body = log_path.read_bytes()
    record.update(log_sha256=digest(log_body), log_size_bytes=len(log_body))
    (out / (log_path.name + '.gz')).write_bytes(gzip.compress(log_body, mtime=0))
    save()
    print(json.dumps(record), flush=True)
    if record['exit_code'] != 0:
        receipt['outcome'] = 'fail'
        break
    for line in environment_file.read_text().splitlines():
        name, value = line.split('=', 1)
        if name != 'P06_MANAGED_REPLAY_ROOT' or value != str(runner / 'p06-managed-preflight-replay'):
            raise RuntimeError('Initializer wrote an unexpected environment export')
        environment[name] = value
else:
    receipt['outcome'] = 'pass'

receipt.update(finished_at=now(), elapsed_seconds=round(time.monotonic() - start, 3),
               git_status_after=git('status', '--porcelain', '--untracked-files=all'),
               resources_after=resources(), source_identities_after=source_identities())
receipt['source_identities_stable'] = receipt['source_identities_before'] == receipt['source_identities_after']
if receipt['git_status_after'] or not receipt['source_identities_stable']:
    receipt['outcome'] = 'fail'
suite_log = runner / 'p06-managed-preflight-replay/evidence/tests.log'
if suite_log.exists():
    suite_text = suite_log.read_text()
    summary = re.findall(r'^Ran ([0-9]+) tests in ([0-9.]+)s$', suite_text, re.MULTILINE)
    if len(summary) == 1:
        receipt['test_summary'] = {'tests_run': int(summary[0][0]),
                                   'reported_seconds': float(summary[0][1]),
                                   'terminal_line': suite_text.rstrip().splitlines()[-1]}
save()
print(json.dumps({'outcome': receipt['outcome'], 'receipt': str(out / 'receipt.json'),
                  'test_summary': receipt.get('test_summary')}), flush=True)
raise SystemExit(0 if receipt['outcome'] == 'pass' else 1)
