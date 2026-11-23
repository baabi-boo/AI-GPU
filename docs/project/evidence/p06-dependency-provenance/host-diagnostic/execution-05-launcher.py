#!/usr/bin/env python3
"""Launch the separately sealed host diagnostic once and retain its exit."""
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path('/workspace/AI-GPU')
PACKET = ROOT / 'docs/project/evidence/p06-dependency-provenance/host-diagnostic'
HELPERS = Path('/workspace/p06-dependency-corrected')
WORKSPACE = Path('/workspace/p06-host-diagnostic-fixed-05')
REVISION = '19333193192ba5a2d3667c0111235ec9e21a5898'
TREE = 'baeeb7bc7078e9301c68e94b1207032329be343d'
DRIVER_SHA256 = '28c5abdeb959e92c53fa7d57bc09b5093478c78d57a09443c2b3479e2fe32682'
PREPARED_SHA256 = 'a3a84f71db0eaea7bc270ef8ee5773841038fa65c396046ba125cfbdac83adbb'

def write(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')

def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    assert subprocess.check_output(['git', '-C', str(HELPERS), 'rev-parse', 'HEAD']).decode().strip() == REVISION
    assert subprocess.check_output(['git', '-C', str(HELPERS), 'rev-parse', 'HEAD^{tree}']).decode().strip() == TREE
    assert subprocess.check_output(['git', '-C', str(HELPERS), 'status', '--porcelain=v1']) == b''
    assert not (WORKSPACE / 'execution-started').exists()
    driver = PACKET / 'driver-05.py'
    assert sha256(driver) == DRIVER_SHA256
    assert sha256(WORKSPACE / 'prepared.json') == PREPARED_SHA256
    report = json.loads((WORKSPACE / 'evidence/host-diagnostic.json').read_text())
    assert report['state'] == 'prepared' and report['outcome'] == 'not_run'
    available = next(int(line.split()[1]) * 1024 for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:'))
    free = shutil.disk_usage(WORKSPACE).free
    assert available >= 6 * 1024**3, '2 GiB governance plus 4 GiB diagnostic aggregate memory entry bound'
    assert free >= 15 * 1024**3, 'unchanged 15 GiB disk reserve'
    argv = [sys.executable, '-I', '-B', str(driver), 'run', '--helpers', str(HELPERS), '--workspace', str(WORKSPACE)]
    stdout = Path('/workspace/w10-a05-driver-05.stdout')
    launch = {'schema_version': 1,
        'scope': 'Single actual host-only attempt05 execution; formal and native claims remain false',
        'launch_checked_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'argv': argv, 'cwd': str(ROOT), 'available_memory_bytes': available,
        'free_disk_bytes': free, 'aggregate_rss_ceiling_bytes': 6 * 1024**3,
        'helper_revision': REVISION, 'helper_tree': TREE, 'helper_checkout_clean': True,
        'driver_sha256': DRIVER_SHA256, 'prepared_sha256': PREPARED_SHA256,
        'review_basis': 'Parent-authorized exact three-change driver transformation; W10-A04 map category review; W10-A06 independent archive selection and combined125-test review.',
        'preparation_verification': 'preparation-05.json', 'driver_stdout': str(stdout),
        'driver_exit_code': None, 'completion_observed': False}
    write(PACKET / 'execution-05-launch.json', launch)
    try:
        with stdout.open('xb') as stream:
            result = subprocess.run(argv, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT, check=False)
        launch.update(driver_exit_code=result.returncode, completion_observed=True,
            completion_observed_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    except BaseException as error:
        launch.update(launcher_error=type(error).__name__ + ': ' + str(error),
            launcher_error_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
        write(PACKET / 'execution-05-driver-result.json', launch)
        raise
    write(PACKET / 'execution-05-driver-result.json', launch)
    print(json.dumps(launch, sort_keys=True))
    print(stdout.read_text())
    return result.returncode

if __name__ == '__main__':
    raise SystemExit(main())
