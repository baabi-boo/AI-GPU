import ast
from contextlib import ExitStack
import hashlib
import importlib
import json
from pathlib import Path
import signal
import sys
from types import SimpleNamespace
from unittest import mock

ROOT = Path('/home/agent/ai-gpu-work-4c990083f078/AI-GPU')
sys.path.insert(0, str(ROOT / 'ci/project'))
NAMES = ('p06_dependency_local_prepare', 'p06_qualified_warm_control', 'p06_qualified_warm_encrypt')
PATHS = {name: ROOT / 'ci/project' / (name + '.py') for name in NAMES}
PATHS['test_p06_cli_signal_setup'] = ROOT / 'ci/project/test_p06_cli_signal_setup.py'
BEFORE = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in PATHS.items()}
modules = [importlib.import_module(name) for name in NAMES]
install = signal.signal
signals = (signal.SIGTERM, signal.SIGINT, signal.SIGALRM)
originals = {number: signal.getsignal(number) for number in signals}
results = []

def enclosing(number, frame):
    raise AssertionError('unexpected signal delivery')

class ProbeStop(BaseException):
    pass

def unchanged(expected):
    for number, handler in expected.items():
        assert signal.getsignal(number) is handler, (number, handler, signal.getsignal(number))

try:
    for module in modules:
        for prior_name, prior in [('default', signal.SIG_DFL), ('ignored', signal.SIG_IGN), ('callable', enclosing)]:
            install(signal.SIGTERM, prior)
            expected = {number: signal.getsignal(number) for number in signals}
            calls = []
            def install_then_interrupt(number, handler):
                previous = install(number, handler)
                calls.append((number, handler))
                if len(calls) == 1:
                    raise KeyboardInterrupt('synthetic post-install interruption')
                return previous
            with mock.patch.object(module, '_main') as body, \
                    mock.patch.object(signal, 'signal', side_effect=install_then_interrupt), \
                    mock.patch.object(signal, 'setitimer', side_effect=AssertionError('unexpected timer operation')):
                try:
                    module.main([])
                except KeyboardInterrupt:
                    pass
                else:
                    raise AssertionError('interruption not propagated')
                body.assert_not_called()
            assert [number for number, handler in calls] == [signal.SIGTERM, signal.SIGTERM]
            assert calls[-1][1] is prior
            unchanged(expected)
            results.append({'module': module.__name__, 'case': 'installation_interrupt_' + prior_name, 'result': 'pass'})
        for disposition in ('return', 'handler_interrupt'):
            install(signal.SIGTERM, enclosing)
            expected = {number: signal.getsignal(number) for number in signals}
            args = ['probe-marker']
            def body(actual_args):
                assert actual_args is args
                handler = signal.getsignal(signal.SIGTERM)
                assert callable(handler) and handler is not enclosing
                assert signal.getsignal(signal.SIGINT) is expected[signal.SIGINT]
                assert signal.getsignal(signal.SIGALRM) is expected[signal.SIGALRM]
                if disposition == 'handler_interrupt':
                    handler(signal.SIGTERM, None)
                    raise AssertionError('handler returned')
                return 73
            with mock.patch.object(module, '_main', side_effect=body) as called, \
                    mock.patch.object(signal, 'signal', wraps=install) as spy, \
                    mock.patch.object(signal, 'setitimer', side_effect=AssertionError('unexpected timer operation')):
                if disposition == 'return':
                    assert module.main(args) == 73
                else:
                    try:
                        module.main(args)
                    except KeyboardInterrupt:
                        pass
                    else:
                        raise AssertionError('handler interruption not propagated')
                called.assert_called_once_with(args)
                assert [call.args[0] for call in spy.call_args_list] == [signal.SIGTERM, signal.SIGTERM]
            unchanged(expected)
            results.append({'module': module.__name__, 'case': disposition, 'result': 'pass'})
        install(signal.SIGTERM, enclosing)
        expected = {number: signal.getsignal(number) for number in signals}
        with mock.patch.object(module, 'main', side_effect=AssertionError('unexpected wrapper')) as wrapped, \
                mock.patch.object(signal, 'signal', side_effect=AssertionError('unexpected signal installation')) as spy, \
                mock.patch.object(module, 'argument_parser', side_effect=ProbeStop) as entry:
            try:
                module._main([])
            except ProbeStop:
                pass
            else:
                raise AssertionError('direct _main entry not reached')
            entry.assert_called_once_with()
            wrapped.assert_not_called()
            spy.assert_not_called()
        unchanged(expected)
        results.append({'module': module.__name__, 'case': 'direct_main_boundary', 'result': 'pass'})
        with ExitStack() as stack:
            wrapped = stack.enter_context(mock.patch.object(module, 'main', side_effect=AssertionError('unexpected wrapper')))
            spy = stack.enter_context(mock.patch.object(signal, 'signal', side_effect=AssertionError('unexpected signal installation')))
            if module.__name__ == NAMES[0]:
                entry = stack.enter_context(mock.patch.object(module.base, '_path', side_effect=ProbeStop))
                invoke = lambda: module.prepare(SimpleNamespace(source_dir='unused'))
                api = 'prepare'
            elif module.__name__ == NAMES[1]:
                stack.enter_context(mock.patch.object(module.os, 'environ', {}))
                entry = stack.enter_context(mock.patch.object(module, '_PrivateOutput', side_effect=ProbeStop))
                invoke = lambda: module.acquire_control('unused')
                api = 'acquire_control'
            else:
                entry = stack.enter_context(mock.patch.object(module, 'validate_recipient', side_effect=ProbeStop))
                invoke = lambda: module.encrypt_private_directory(input_dir='unused', output_dir='unused', recipient='unused')
                api = 'encrypt_private_directory'
            try:
                invoke()
            except ProbeStop:
                pass
            else:
                raise AssertionError('library boundary not reached')
            entry.assert_called_once()
            wrapped.assert_not_called()
            spy.assert_not_called()
        unchanged(expected)
        tree = ast.parse(PATHS[module.__name__].read_text())
        library_fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == api)
        assert not library_fn.decorator_list
        assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ('main', '_main') for node in ast.walk(library_fn))
        results.append({'module': module.__name__, 'case': 'direct_' + api + '_boundary', 'result': 'pass'})
finally:
    for number, handler in originals.items():
        install(number, handler)
    unchanged(originals)
AFTER = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in PATHS.items()}
assert BEFORE == AFTER, 'reviewed source changed during probe'
record = {'scope': 'host-only bounded signal setup and direct-entry boundary probes; no signal delivery, network, native execution or suite',
          'results': results, 'checks': len(results), 'source_sha256': BEFORE, 'source_stable': True}
Path('/home/agent/ai-gpu-work-4c990083f078/tmp/a034/probe-result.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record, sort_keys=True))
