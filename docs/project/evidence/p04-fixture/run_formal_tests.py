#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

parser = argparse.ArgumentParser()
parser.add_argument('--source', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
source = args.source.resolve(strict=True)
output = args.output.resolve()
output.mkdir(parents=True, exist_ok=False)

def git(*args):
    return subprocess.check_output(['git', '-C', str(source), *args], text=True).strip()

if git('status', '--porcelain=v1'):
    raise SystemExit('formal source must be clean')
sys.path.insert(0, str(source / 'ci/project'))
from baseline_process import run_bounded, GIB, MIB

record = {
    'source_revision': git('rev-parse', 'HEAD'),
    'source_tree': git('rev-parse', 'HEAD^{tree}'),
    'python': sys.version,
    'compiler': subprocess.check_output(['g++', '--version'], text=True).splitlines()[0],
    'scope': 'Host tooling and source contract qualification; no GPU execution.',
    'commands': [],
}
environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', CCACHE_DISABLE='1')
commands = [
    ('fixture', ['python3', 'ci/project/p04_reference.py', '--check']),
    ('contract', ['python3', 'ci/project/p04_model_contract.py', '--check']),
    ('governance', ['python3', 'ci/project/check_project.py']),
    ('baseline-packets', ['python3', 'ci/project/check_baseline_packets.py']),
    ('full-suite', ['python3', '-m', 'unittest', 'discover', '-s', 'ci/project', '-p', 'test_*.py']),
]
for name, command in commands:
    log = output / (name + '.log')
    print('START ' + name, flush=True)
    result = run_bounded(command, source, environment, log,
                         timeout_seconds=1800, min_free_bytes=15 * GIB,
                         max_log_bytes=5 * MIB, max_rss_bytes=3 * GIB,
                         resource_paths=(source, output))
    entry = {'name': name, 'argv': command, 'cwd': '${SOURCE}', 'receipt': result,
             'log': log.name, 'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()}
    record['commands'].append(entry)
    record['source_unchanged'] = (git('rev-parse', 'HEAD') == record['source_revision']
                                  and git('status', '--porcelain=v1') == '')
    (output / 'verification.json').write_text(json.dumps(record, indent=2) + '\n')
    print('DONE ' + name + ' ' + result['outcome'], flush=True)
    if result['outcome'] != 'pass' or not record['source_unchanged']:
        raise SystemExit(1)
print('FORMAL HOST QUALIFICATION PASS', flush=True)
