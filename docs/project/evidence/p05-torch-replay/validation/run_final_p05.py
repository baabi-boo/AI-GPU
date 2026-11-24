"""Record the exact bounded final P05 host selection, not a full-suite pass."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

root = Path.cwd().resolve()
out = Path('/workspace/scratch/101d52695253/validation')
sys.path.insert(0, str(root / 'ci/project'))

def git(*args):
    return subprocess.check_output(['git', *args], text=True).strip()

def sources():
    paths = sorted(set(root.glob('ci/project/*.py')) | set(root.glob('python/**/*.py')) |
                   set(root.glob('ci/project/fixtures/*')) | set(root.glob('profiles/*.json')))
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in paths if p.is_file()}

def ids(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from ids(item)
        else:
            yield item.id()

assert not git('status', '--porcelain'), 'isolated test checkout is not clean'
temp = tempfile.gettempdir()
before = sources()
suite = unittest.defaultTestLoader.discover(str(root / 'ci/project'), pattern='test_p05*.py')
selected = list(ids(suite))
assert len(selected) == len(set(selected)), 'duplicate selected test IDs'
receipt = {'command': 'TMPDIR=/tmp/ai-gpu-p05-host-temp-101d52695253 PYTHONDONTWRITEBYTECODE=1 python3 -B /workspace/scratch/101d52695253/validation/run_final_p05.py',
           'cwd': str(root), 'source_revision': git('rev-parse', 'HEAD'),
           'source_tree': git('rev-parse', 'HEAD^{tree}'), 'source_clean': True,
           'python': sys.version, 'temporary_directory': temp,
           'temporary_free_bytes_before': shutil.disk_usage(temp).free,
           'selection': 'ci/project/test_p05*.py', 'selected_count': len(selected),
           'selected_test_ids': selected, 'source_sha256_before': before}
(out / 'final-p05-before.json').write_text(json.dumps(receipt, indent=2) + '\n')
started = time.monotonic()
with (out / 'final-p05.log').open('w') as log:
    result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
after = sources()
summary = {'scope': 'host-only bounded P05 regression, not full governance',
           'source_revision': receipt['source_revision'], 'source_tree': receipt['source_tree'],
           'selected_count': len(selected), 'tests_run': result.testsRun,
           'failures': len(result.failures), 'errors': len(result.errors),
           'skips': len(result.skipped), 'expected_failures': len(result.expectedFailures),
           'unexpected_successes': len(result.unexpectedSuccesses),
           'duration_seconds': round(time.monotonic() - started, 6),
           'source_changed': sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p)),
           'source_clean_after': not git('status', '--porcelain'),
           'temporary_free_bytes_after': shutil.disk_usage(temp).free}
passed = result.wasSuccessful() and result.testsRun == len(selected) and not result.skipped and not summary['source_changed'] and summary['source_clean_after']
summary.update(outcome='pass' if passed else 'fail', exit_code=0 if passed else 1)
(out / 'final-p05-result.json').write_text(json.dumps(summary, indent=2) + '\n')
print(json.dumps(summary))
sys.exit(summary['exit_code'])
