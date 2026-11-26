import ctypes
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import signal
import sys
import unittest

root = Path('/tmp/ai-gpu-2bfab0261c05/repo')
sys.path.insert(0, str(root))
module = importlib.import_module('ci.project.test_p05_launcher_signals')
module.LAUNCH_PATH = Path('/tmp/ai-gpu-2bfab0261c05/a042-baseline-launch.py')
libc = ctypes.CDLL(None, use_errno=True)
if libc.prctl(36, 1, 0, 0, 0):
    raise OSError(ctypes.get_errno(), 'could not retain orphan probes for reaping')
fds_before = sorted(os.listdir('/proc/self/fd'))
signals_before = {int(s): signal.getsignal(s) for s in signal.valid_signals() if s != signal.SIGKILL and s != signal.SIGSTOP}
fixture = module.LauncherSignalTests('test_pid_directed_sigterm_reaches_child_and_reaps_before_return')
with fixture.probe('default') as (process, event):
    ready = event()
    os.kill(process.pid, signal.SIGTERM)
    parent_status = process.wait(timeout=5)
    process.stdin.write(b'finish-after-parent-exit\n')
    continued = event()
    adopted_pid, child_status = os.waitpid(ready['pid'], 0)
    stderr = process.stderr.read().decode()
assert parent_status == -signal.SIGTERM
assert continued == {'event': 'continued', 'input': 'finish-after-parent-exit\n'}
assert adopted_pid == ready['pid'] and os.waitstatus_to_exitcode(child_status) == 21
assert not stderr
stream = io.StringIO()
result = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.TestSuite([
    module.LauncherSignalTests('test_pid_directed_sigterm_reaches_child_and_reaps_before_return')]))
assert result.testsRun == 1 and len(result.failures) == 1 and not result.errors
Path('/tmp/ai-gpu-2bfab0261c05/a042-baseline.log').write_text(stream.getvalue())
try:
    residual = os.waitpid(-1, os.WNOHANG)
except ChildProcessError:
    residual = None
assert residual is None
fds_after = sorted(os.listdir('/proc/self/fd'))
signals_after = {int(s): signal.getsignal(s) for s in signal.valid_signals() if s != signal.SIGKILL and s != signal.SIGSTOP}
assert fds_before == fds_after
assert signals_before == signals_after
summary = {
    'baseline_revision': '858090410a992756808256ace90d36b9b3b88dd3',
    'baseline_launcher': str(module.LAUNCH_PATH),
    'baseline_launcher_sha256': hashlib.sha256(module.LAUNCH_PATH.read_bytes()).hexdigest(),
    'test_sha256': hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest(),
    'parent_status': parent_status,
    'child_event_after_parent_exit': continued,
    'adopted_child_exit_status': os.waitstatus_to_exitcode(child_status),
    'negative_tests_run': result.testsRun,
    'expected_failures': len(result.failures),
    'errors': len(result.errors),
    'no_unreaped_children': residual is None,
    'fd_inventory_unchanged': fds_before == fds_after,
    'signal_dispositions_unchanged': signals_before == signals_after,
    'scope': 'host-only launcher; bundle verification stub; no native execution',
}
Path('/tmp/ai-gpu-2bfab0261c05/a042-baseline.json').write_text(json.dumps(summary, indent=2) + '\n')
print(json.dumps(summary, indent=2))
