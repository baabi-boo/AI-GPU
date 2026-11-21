#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Read-only classification of a real final candidate, using frozen base policy.

This does not create commits, stage files, update refs, publish or grant approval.
The candidate must already exist locally and descend from the tested implementation.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

BASE = '6aac9c421180805a5621156e3d914c685fc6f4a5'
IMPLEMENTATION = 'e1420fd550f716df33a2556057b7086a03032cbe'
PINS = {
    'change_impact.py': ('ci/change_impact.py', 'bd2ef579de90b14b7ab4cd5ef2f6b7c911753e154c4201aaf0f0d0b25a460779'),
    'change-impact.yaml': ('docs/review/change-impact.yaml', '489d1018c790bb6c383b774b119223889bb508be6c63db654d5c6c80520d0333'),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True, type=Path)
    parser.add_argument('--head', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if not re.fullmatch('[0-9a-f]{40}', args.head):
        parser.error('--head must be a complete commit object ID')
    if not args.repo.is_absolute() or args.repo.resolve(strict=True) != args.repo:
        parser.error('--repo must be an existing canonical absolute path')
    if (not args.output.is_absolute() or args.output.parent.resolve(strict=True) != args.output.parent
            or os.path.lexists(args.output) or args.output.is_relative_to(args.repo)):
        parser.error('--output must be a fresh absolute path outside the repository, under an existing canonical parent')
    def git(*values):
        return subprocess.check_output(['git', *values], cwd=args.repo)
    if git('rev-parse', '--verify', args.head + '^{commit}').decode().strip() != args.head:
        parser.error('candidate does not resolve to the requested commit')
    for base in (BASE, IMPLEMENTATION):
        subprocess.run(['git', 'merge-base', '--is-ancestor', base, args.head], cwd=args.repo, check=True)
    bodies = {}
    for name, (source, digest) in PINS.items():
        body = git('show', BASE + ':' + source)
        if hashlib.sha256(body).hexdigest() != digest or body != git('show', IMPLEMENTATION + ':' + source):
            parser.error('frozen classifier/policy body differs: ' + name)
        bodies[name] = body
    args.output.mkdir()
    for name, body in bodies.items():
        (args.output / name).write_bytes(body)
    results = []
    for label, base in (('complete-change', BASE), ('qualification-continuation', IMPLEMENTATION)):
        command = [sys.executable, '-I', str(args.output / 'change_impact.py'), '--repo', str(args.repo),
                   '--policy', str(args.output / 'change-impact.yaml'), 'classify', '--base', base,
                   '--head', args.head, '--event', 'push', '--format', 'json']
        child = subprocess.run(command, cwd=args.repo, stdin=subprocess.DEVNULL, capture_output=True,
                               timeout=120, check=False)
        (args.output / (label + '.stdout.json')).write_bytes(child.stdout)
        (args.output / (label + '.stderr.log')).write_bytes(child.stderr)
        data = json.loads(child.stdout) if child.returncode == 0 else None
        results.append({'scope': label, 'command': command, 'exit_code': child.returncode,
                        'class': data.get('class') if data else None,
                        'indeterminate': data.get('indeterminate') if data else None,
                        'stdout_sha256': hashlib.sha256(child.stdout).hexdigest(),
                        'stderr_sha256': hashlib.sha256(child.stderr).hexdigest()})
    receipt = {'schema_version': 1, 'candidate': args.head, 'candidate_tree': git('rev-parse', args.head + '^{tree}').decode().strip(),
               'scope': 'Read-only actual-object classification; no staging, ref change, publication or approval',
               'commands': results, 'outcome': 'pass' if all(row['exit_code'] == 0 and row['indeterminate'] is False for row in results) else 'fail'}
    (args.output / 'classification.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt['outcome'] == 'pass' else 1


if __name__ == '__main__':
    sys.exit(main())
