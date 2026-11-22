import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone


ROOT = Path('/tmp/ai-gpu-governance-142b2d6')
TEMP = Path('/tmp/ai-gpu-governance-temp-142b2d6')
OUT = Path('/workspace/scratch/98908dfa3444/local-clean-governance-142b')
REVISION = '142b2d6aaea2fa4226118b857514113032d2e26c'
TREE = '754ef8577f9a72785c0809048762c70b16cb4857'
DISK_FLOOR = 1024 ** 3
MEMORY_FLOOR = 512 * 1024 ** 2
TIME_LIMIT = 40 * 60


def now():
    return datetime.now(timezone.utc).isoformat()


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT).decode().strip()


def resources():
    available = None
    for line in Path('/proc/meminfo').read_text().splitlines():
        if line.startswith('MemAvailable:'):
            available = int(line.split()[1]) * 1024
    return {'temporary_free_bytes': shutil.disk_usage(TEMP).free,
            'available_memory_bytes': available}


def sources():
    names = git('ls-tree', '-r', '--name-only', REVISION, '--',
                'ci/project', '.github/workflows',
                'tests/unittest/checked_counters',
                'sim/simx/checked_counters.mk').splitlines()
    return [{'path': name, 'sha256': hashlib.sha256((ROOT / name).read_bytes()).hexdigest(),
             'size_bytes': (ROOT / name).stat().st_size} for name in names]


def write_json(name, value):
    destination = OUT / name
    temporary = destination.with_suffix(destination.suffix + '.writing')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(destination)


OUT.mkdir(exist_ok=False)
TEMP.mkdir(exist_ok=False)
assert git('rev-parse', 'HEAD') == REVISION
assert git('rev-parse', 'HEAD^{tree}') == TREE
assert git('status', '--porcelain') == ''
before = sources()
record = {
    'schema_version': 1,
    'scope': 'isolated-clean-local-governance',
    'source_revision': REVISION,
    'source_tree': TREE,
    'working_directory': str(ROOT),
    'temporary_directory': str(TEMP),
    'python_executable': sys.executable,
    'python_version': platform.python_version(),
    'python_implementation': platform.python_implementation(),
    'platform': sys.platform,
    'started_at': now(),
    'disk_floor_bytes': DISK_FLOOR,
    'available_memory_floor_bytes': MEMORY_FLOOR,
    'per_command_timeout_seconds': TIME_LIMIT,
    'source_before': before,
    'git_status_before': '',
    'commands': [],
    'resources_before': resources(),
    'native_gpu_execution': 'not_run',
    'hosted_execution': False,
    'qualified': False,
    'ready_for_warm': False,
    'warm_execution': False,
    'acceptance': False,
}
write_json('receipt.json', record)
env = os.environ.copy()
env.update(PYTHONDONTWRITEBYTECODE='1', TMPDIR=str(TEMP), PWD=str(ROOT))
commands = [
    ('preflight', [sys.executable, 'ci/project/preflight.py', '--tier', 'governance', '--json']),
    ('project-metadata', [sys.executable, 'ci/project/check_project.py']),
    ('baseline-packets', [sys.executable, 'ci/project/check_baseline_packets.py']),
    ('unittest', [sys.executable, '-m', 'unittest', 'discover', '-s', 'ci/project', '-p', 'test_*.py', '-v']),
]
for label, command in commands:
    initial = resources()
    if initial['temporary_free_bytes'] < DISK_FLOOR or initial['available_memory_bytes'] < MEMORY_FLOOR:
        record['aborted_before_command'] = {'label': label, 'reason': 'resource_floor', 'resources': initial}
        break
    log_path = OUT / (label + '.log')
    start = time.monotonic()
    entry = {'label': label, 'argv': command, 'started_at': now(),
             'log': str(log_path), 'resource_minima': dict(initial)}
    print(json.dumps({'event': 'started', 'label': label, 'at': entry['started_at']}), flush=True)
    with log_path.open('xb') as log:
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        reason = None
        while process.poll() is None:
            observed = resources()
            for key, value in observed.items():
                entry['resource_minima'][key] = min(entry['resource_minima'][key], value)
            elapsed = time.monotonic() - start
            write_json('status.json', {'label': label, 'pid': process.pid, 'at': now(),
                                      'elapsed_seconds': elapsed, 'resources': observed})
            if observed['temporary_free_bytes'] < DISK_FLOOR or observed['available_memory_bytes'] < MEMORY_FLOOR:
                reason = 'resource_floor'
            elif elapsed > TIME_LIMIT:
                reason = 'time_limit'
            if reason:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                break
            time.sleep(5)
        entry.update(returncode=process.wait(), finished_at=now(),
                     elapsed_seconds=time.monotonic() - start, termination_reason=reason)
    raw = log_path.read_bytes()
    entry.update(size_bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    if label == 'unittest':
        text = raw.decode('utf-8', errors='strict')
        matches = re.findall(r'^Ran (\d+) tests in ([0-9.]+)s$', text, re.M)
        entry['test_summary'] = [{'tests': int(count), 'seconds': float(seconds)} for count, seconds in matches]
        entry['ok_footer_observed'] = bool(re.search(r'^OK$', text, re.M))
    record['commands'].append(entry)
    write_json('receipt.json', record)
    print(json.dumps({'event': 'finished', 'label': label, 'returncode': entry['returncode'],
                      'termination_reason': reason, 'elapsed_seconds': entry['elapsed_seconds']}), flush=True)
    if entry['returncode'] != 0 or reason:
        break
record.update(finished_at=now(), source_after=sources(), git_status_after=git('status', '--porcelain'),
              resources_after=resources())
record['source_closure_unchanged'] = record['source_before'] == record['source_after']
record['verification_passed'] = (len(record['commands']) == len(commands)
                                 and all(row['returncode'] == 0 and row['termination_reason'] is None
                                         for row in record['commands'])
                                 and record['source_closure_unchanged']
                                 and record['git_status_after'] == '')
write_json('receipt.json', record)
write_json('status.json', {'event': 'completed', 'at': now(), 'verification_passed': record['verification_passed']})
print(json.dumps({'event': 'completed', 'verification_passed': record['verification_passed'],
                  'receipt': str(OUT / 'receipt.json')}), flush=True)
raise SystemExit(0 if record['verification_passed'] else 1)
