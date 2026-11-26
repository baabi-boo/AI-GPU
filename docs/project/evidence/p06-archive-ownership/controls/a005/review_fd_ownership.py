from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import types

repo = Path.cwd()
private = Path(os.environ['TMPDIR'])
relative = 'ci/project/p06_qualified_warm_pack.py'
base = subprocess.check_output(['git', 'show', '81d7a35c641f3a969c23c8e604f7468a4d88644a:' + relative])
fixed = (private / 'pack_input.py').read_bytes()
sys.path.insert(0, str(repo / 'ci/project'))
def load(name, raw):
    module = types.ModuleType(name)
    module.__file__ = str(repo / relative)
    sys.modules[name] = module
    exec(compile(raw, module.__file__, 'exec'), module.__dict__)
    return module
baseline = load('a005_baseline', base)
changed = load('a005_changed', fixed)
probe = private / 'input.bin'
state = {'active': False, 'raise': False, 'fds': []}
def hook(event, args):
    if state['active'] and event == 'open' and type(args[0]) is int:
        state['fds'].append(args[0])
        if state['raise']:
            raise PermissionError('a005 real audit rejection')
sys.addaudithook(hook)
def live(fd):
    try:
        os.fstat(fd)
        return True
    except OSError:
        return False
rows = []
for operation in ('read', 'exclusive'):
    state.update(active=True, **{'raise': True, 'fds': []})
    try:
        if operation == 'read':
            baseline._read_file(probe)
        else:
            with baseline._exclusive(private / 'baseline-exclusive.bin'):
                raise AssertionError('unreachable')
    except PermissionError:
        pass
    else:
        raise AssertionError('audit rejection did not propagate')
    finally:
        state['active'] = False
    assert len(state['fds']) == 1
    still_open = live(state['fds'][0])
    rows.append({'snapshot': 'baseline', 'operation': operation, 'trigger': 'PermissionError at real fdopen audit', 'fd_remained_open': still_open})
    assert still_open, 'baseline negative control failed to reproduce'
    os.close(state['fds'][0])
for operation in ('read_destination', 'exclusive_body'):
    for failure in (PermissionError, KeyboardInterrupt):
        marker = failure('a005 body marker')
        class Destination:
            def write(self, value):
                raise marker
        state.update(active=True, **{'raise': False, 'fds': []})
        try:
            if operation == 'read_destination':
                changed._read_file(probe, destination=Destination())
            else:
                with changed._exclusive(private / ('changed-body-' + failure.__name__ + '.bin')) as stream:
                    stream.write(b'partial retained')
                    raise marker
        except BaseException as observed:
            assert observed is marker, 'first failure identity changed'
        else:
            raise AssertionError('failure did not propagate')
        finally:
            state['active'] = False
        assert len(state['fds']) == 1
        closed = not live(state['fds'][0])
        assert closed, 'changed snapshot leaked body failure fd'
        rows.append({'snapshot': 'changed', 'operation': operation, 'trigger': failure.__name__, 'fd_closed': closed, 'same_exception': True})
result = {'baselineSHA': hashlib.sha256(base).hexdigest(),
          'changedSHA': hashlib.sha256(fixed).hexdigest(), 'checks': rows,
          'end_worktreeSHA': hashlib.sha256((repo / relative).read_bytes()).hexdigest(),
          'end_HEAD': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
          'end_status': subprocess.check_output(['git', 'status', '--short'], text=True)}
(private / 'review-results.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
