"""Retain one exact host-only governance run and its selected source identities."""
import contextlib
import hashlib
import json
import pathlib
import subprocess
import sys
import time
import unittest

out = pathlib.Path('../validation')
modules = sorted(p.stem for p in pathlib.Path('ci/project').glob('test_*.py'))
paths = set(pathlib.Path('ci/project').glob('*.py'))
paths.update(pathlib.Path('python').rglob('*.py'))
paths.update(pathlib.Path('profiles').glob('*.json'))
paths.update(pathlib.Path('docs/project').glob('*.json'))

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

before = [{'path': str(path), 'sha256': digest(path)} for path in sorted(paths)]
metadata = {
    'git_head_at_start': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
    'host_only': True,
    'runner_sha256': digest(pathlib.Path(__file__)),
    'modules': modules,
    'files': before,
}
(out / 'governance-before.json').write_text(json.dumps(metadata, indent=2) + '\n')
with (out / 'governance.log').open('w') as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
    suite = unittest.TestLoader().loadTestsFromNames(modules)

    def identifiers(group):
        for test in group:
            if isinstance(test, unittest.TestSuite):
                yield from identifiers(test)
            else:
                yield test.id()

    ids = list(identifiers(suite))
    (out / 'governance-test-ids.json').write_text(json.dumps(ids, indent=2) + '\n')
    started = time.monotonic()
    result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    elapsed = time.monotonic() - started
changed = [row['path'] for row in before if digest(pathlib.Path(row['path'])) != row['sha256']]
summary = {
    'tests_run': result.testsRun,
    'unique_test_ids': len(set(ids)),
    'failures': len(result.failures),
    'errors': len(result.errors),
    'skips': len(result.skipped),
    'elapsed_seconds': round(elapsed, 3),
    'source_changed': changed,
    'success': result.wasSuccessful() and not changed,
    'host_only': True,
    'native_execution': 'not_run',
}
(out / 'governance-result.json').write_text(json.dumps(summary, indent=2) + '\n')
print(json.dumps(summary), flush=True)
sys.exit(0 if summary['success'] else 1)
