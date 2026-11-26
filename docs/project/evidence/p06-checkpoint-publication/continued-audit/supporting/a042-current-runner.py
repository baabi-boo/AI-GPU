import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import unittest
root = Path('/tmp/ai-gpu-2bfab0261c05/repo')
sys.path.insert(0, str(root))
module = importlib.import_module('ci.project.test_p05_launcher_signals')
paths = ['python/vortex_ai/launch.py', 'ci/project/test_p05_launcher_signals.py']
def hashes():
    return {p: hashlib.sha256((root/p).read_bytes()).hexdigest() for p in paths}
def state():
    return {'fds': sorted(os.listdir('/proc/self/fd')),
            'cwd': os.getcwd(), 'environment': dict(os.environ),
            'threads': [(t.name, t.ident) for t in threading.enumerate()],
            'signals': {int(s): repr(signal.getsignal(s)) for s in signal.valid_signals()
                        if s not in (signal.SIGKILL, signal.SIGSTOP)}}
source_before, before = hashes(), state()
stream = io.StringIO()
result = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(module))
source_after, after = hashes(), state()
Path('/tmp/ai-gpu-2bfab0261c05/a042-current.log').write_text(stream.getvalue())
assert result.testsRun == 8 and result.wasSuccessful() and not result.skipped
assert before == after, {key: (before[key], after[key]) for key in before if before[key] != after[key]}
assert source_before == source_after
summary = {'head': subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),
           'tests_run': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
           'skips': len(result.skipped), 'source_sha256': source_before,
           'source_stable': source_before == source_after, 'process_state_unchanged': before == after,
           'scope': 'host-only launcher regression selection; no native execution'}
Path('/tmp/ai-gpu-2bfab0261c05/a042-current.json').write_text(json.dumps(summary,indent=2)+'\n')
print(stream.getvalue())
print(json.dumps(summary,indent=2))
