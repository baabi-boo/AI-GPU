#!/usr/bin/env python3
"""Independent scratch probes; never execute retained producer data."""
import builtins
import ast
import contextlib
import ctypes
import hashlib
import io
import json
import os
from pathlib import Path
import runpy
import socket
import subprocess
import sys
import types
import unittest
from unittest import mock
import zipfile

import p06_dependency_local_replay as replay
import p06_managed_preflight_generated as generated
from test_p06_dependency_local_replay import LocalDependencyReplayTests

ROOT = Path('/workspace/ai-gpu-next')
OUTPUT = Path('/workspace/scratch/279b6658611e/validation/w04_a06-inertness-observations.json')
PREPARATION = Path('/workspace/p06-local-native-run-01/evidence/dependency-preparation.json')
OBSERVATIONS = {}


@contextlib.contextmanager
def guard(archive=None, preparation_only=False):
    opened, compiled, executed, resolutions, directories, parsed, expressions = [], [], [], [], [], [], []
    descriptor_paths = {}
    known_code = set()
    known_expressions = set()
    original_open, original_io_open, original_os_open = builtins.open, io.open, os.open
    original_compile, original_exec, original_resolve = builtins.compile, builtins.exec, Path.resolve
    original_eval = builtins.eval
    trusted_helper = ROOT / replay.native_replay.archive_helpers.ARCHIVE_READER_PATH
    trusted_digest = replay.native_replay.archive_helpers.ARCHIVE_READER_SHA256
    lock = ROOT / replay.LOCK

    def allowed_path(value):
        if isinstance(value, int):
            return
        value = os.fsdecode(value)
        path = Path(value)
        assert path.is_absolute(), 'relative live path: ' + value
        if preparation_only:
            assert path == lock, 'unexpected preparation live read: ' + value
        else:
            assert path == archive or path.is_relative_to(ROOT), 'producer/untrusted live path: ' + value
        opened.append(value)

    def open_guard(original):
        def call(file, mode='r', *args, **kwargs):
            allowed_path(file)
            assert not set(str(mode)) & set('wax+'), 'write during replay'
            return original(file, mode, *args, **kwargs)
        return call

    def os_open_guard(path, flags, *args, **kwargs):
        selected = Path(os.fsdecode(path))
        if not selected.is_absolute():
            selected = descriptor_paths[kwargs['dir_fd']] / selected
        if flags & os.O_DIRECTORY:
            assert selected.is_relative_to(ROOT) or ROOT.is_relative_to(selected)
            directories.append(str(selected))
        else:
            allowed_path(selected)
        assert flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND) == 0
        descriptor = original_os_open(path, flags, *args, **kwargs)
        descriptor_paths[descriptor] = selected
        return descriptor

    def resolve_guard(path, *args, **kwargs):
        text = str(path)
        assert not text.startswith(('/home/runner/', '/synthetic-', '/workspace/p06-local-native-run-01',
                                    '/workspace/p06-local-run-source', '/workspace/p06-native-prebuilt',
                                    '/workspace/p06-local-host', '/workspace/p06-pinned-inputs')), \
            'producer path resolved: ' + text
        resolutions.append(text)
        return original_resolve(path, *args, **kwargs)

    def compile_guard(source, filename, mode, *args, **kwargs):
        assert not preparation_only, 'preparation metadata compiled code'
        flags = args[0] if args else kwargs.get('flags', 0)
        if flags & ast.PyCF_ONLY_AST:
            value = original_compile(source, filename, mode, *args, **kwargs)
            assert isinstance(value, ast.AST)
            parsed.append(str(filename))
            return value
        if filename == '<cfg-expr>':
            assert sys._getframe(1).f_globals is generated.TRUSTED_GENERATOR_MODULE.__dict__
            code = original_compile(source, filename, mode, *args, **kwargs)
            known_expressions.add(id(code))
            expression = ast.dump(source, include_attributes=False) if isinstance(source, ast.AST) else source
            expressions.append({'sha256': hashlib.sha256(expression.encode()).hexdigest(), 'ast': expression})
            return code
        assert str(filename) == str(trusted_helper), 'untrusted code compilation: ' + str(filename)
        assert isinstance(source, bytes) and hashlib.sha256(source).hexdigest() == trusted_digest
        code = original_compile(source, filename, mode, *args, **kwargs)
        known_code.add(id(code))
        compiled.append(str(filename))
        return code

    def exec_guard(code, globals=None, locals=None, *args, **kwargs):
        assert isinstance(code, types.CodeType) and id(code) in known_code, 'untrusted code execution'
        executed.append(code.co_filename)
        return original_exec(code, globals, locals, *args, **kwargs)

    def eval_guard(code, globals=None, locals=None):
        assert isinstance(code, types.CodeType) and id(code) in known_expressions
        assert sys._getframe(1).f_globals is generated.TRUSTED_GENERATOR_MODULE.__dict__
        return original_eval(code, globals, locals)

    forbidden = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('execution or network API reached'))
    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch.object(os, 'supports_dir_fd', os.supports_dir_fd | {os_open_guard}))
        for owner, name, replacement in ((builtins, 'open', open_guard(original_open)),
                (io, 'open', open_guard(original_io_open)), (os, 'open', os_open_guard),
                (Path, 'resolve', resolve_guard), (builtins, 'compile', compile_guard),
                (builtins, 'exec', exec_guard), (builtins, 'eval', eval_guard),
                (subprocess, 'Popen', forbidden), (os, 'system', forbidden),
                (runpy, 'run_path', forbidden), (ctypes, 'CDLL', forbidden),
                (socket, 'socket', forbidden), (socket, 'create_connection', forbidden),
                (zipfile.ZipFile, 'extract', forbidden), (zipfile.ZipFile, 'extractall', forbidden)):
            stack.enter_context(mock.patch.object(owner, name, new=replacement))
        for name in ('fork', 'forkpty', 'posix_spawn', 'posix_spawnp', 'execv', 'execve', 'execvp', 'execvpe'):
            if hasattr(os, name):
                stack.enter_context(mock.patch.object(os, name, new=forbidden))
        yield {'live_reads': opened, 'trusted_compiles': compiled, 'trusted_execs': executed,
               'resolved_paths': resolutions, 'directory_traversals': directories, 'inert_ast_parses': parsed,
               'trusted_configuration_expressions': expressions}


class IndependentInertnessTests(unittest.TestCase):
    def test_actual_preparation_is_metadata_only(self):
        body = PREPARATION.read_bytes()
        document = json.loads(body)
        with guard(preparation_only=True) as observations:
            result = replay.receipts.local_prepare.validate_local_preparation(document, document['expected_revision'])
        self.assertIs(result, document)
        self.assertEqual(set(observations['live_reads']), {str(ROOT / replay.LOCK)})
        self.assertEqual(observations['trusted_execs'], [])
        self.assertEqual(observations['resolved_paths'], [])
        OBSERVATIONS['actual_preparation'] = dict(observations, sha256=hashlib.sha256(body).hexdigest(),
            size_bytes=len(body), outcome='pass', archive_or_installed_paths_read=False)

    def test_complete_local_synthetic_path_has_only_trusted_live_inputs(self):
        LocalDependencyReplayTests.setUpClass()
        fixture = LocalDependencyReplayTests('test_complete_local_archive_reuses_native_and_both_control_semantics_inertly')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        pin = fixture.archive()
        with mock.patch.object(replay.native_replay.dependency_replay, 'verify_view',
                               side_effect=fixture.dependency_boundary):
            with guard(fixture.path) as observations:
                result = replay.replay_archive(fixture.path, pin, **fixture.arguments())
        self.assertEqual(result['outcome'], 'pass')
        self.assertFalse(result['retained_code_executed'])
        self.assertEqual(result['native_execution'], 'not_run')
        self.assertEqual(len(observations['trusted_execs']), 1)
        OBSERVATIONS['synthetic_complete_local_path'] = dict(observations, outcome='pass',
            dependency_semantic_boundary_mocked=True, native_and_control_semantics_mocked=False,
            managed_counts=result['managed_counts'], archive_read=result['archive_read'])


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(IndependentInertnessTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    OUTPUT.write_text(json.dumps(OBSERVATIONS, indent=2, sort_keys=True) + '\n')
    raise SystemExit(0 if result.wasSuccessful() else 1)
