import errno
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest import mock

repo = Path('/home/agent/ai-gpu-d7ec98164a68/repo')
sys.path.insert(0, str(repo / 'ci/project'))
import governance_replay_archive as reader

source = repo / 'ci/project/governance_replay_archive.py'
before_hash = hashlib.sha256(source.read_bytes()).hexdigest()
real_close, real_fdopen, real_directory = os.close, os.fdopen, reader._directory


def is_open(fd):
    try:
        os.fstat(fd)
        return True
    except OSError as error:
        if error.errno != errno.EBADF:
            raise
        return False


def release_witnesses(state):
    # This only closes descriptors observed still open. Never retries an
    # ambiguous consumed close; a recycled witness is a distinct owned fd.
    for key in ('parent', 'fresh', 'witness'):
        descriptor = state.get(key)
        if descriptor is not None and is_open(descriptor):
            real_close(descriptor)


results = []
with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR'], prefix='input-') as directory:
    path = Path(directory) / 'archive.zip'
    path.write_bytes(b'x' * 32)

    state = {'close_calls': 0}
    primary = RuntimeError('injected fdopen construction failure')
    cleanup = OSError(errno.EIO, 'injected consuming raw close failure')

    def tracking_directory(selected):
        result = real_directory(selected)
        state['parent'] = result[0]
        return result

    def fail_fdopen(descriptor, mode):
        state['leaf'] = descriptor
        raise primary

    def consuming_close(descriptor):
        if descriptor == state.get('leaf'):
            state['close_calls'] += 1
            real_close(descriptor)
            state['witness'] = os.open('/dev/null', os.O_RDONLY)
            raise cleanup
        return real_close(descriptor)

    try:
        with mock.patch.object(reader, '_directory', side_effect=tracking_directory), \
             mock.patch.object(reader.os, 'fdopen', side_effect=fail_fdopen), \
             mock.patch.object(reader.os, 'close', side_effect=consuming_close):
            try:
                with reader._input(path):
                    raise AssertionError('body must not run')
            except BaseException as raised:
                result = {
                    'case': 'consuming_raw_close_after_fdopen_failure',
                    'raised_cleanup_error': raised is cleanup,
                    'primary_only_in_context': raised.__context__ is primary,
                    'parent_leaked': is_open(state['parent']),
                    'recycled_descriptor': state['witness'] == state['leaf'],
                    'witness_survives': is_open(state['witness']),
                    'close_attempts': state['close_calls'],
                }
        assert result['parent_leaked'] and result['raised_cleanup_error']
        assert result['primary_only_in_context'] and result['recycled_descriptor']
        assert result['witness_survives'] and result['close_attempts'] == 1
        results.append(result)
    finally:
        release_witnesses(state)

    state = {'close_calls': 0}
    primary = RuntimeError('injected body failure')
    cleanup = OSError(errno.EIO, 'injected consuming stream close failure')

    def tracking_directory(selected):
        result = real_directory(selected)
        state['parent'] = result[0]
        return result

    def close_fault_stream(descriptor, mode):
        stream = real_fdopen(descriptor, mode)
        state['stream'] = stream
        state['leaf'] = descriptor
        original_close = stream.close
        def close():
            state['close_calls'] += 1
            original_close()
            raise cleanup
        stream.close = close
        return stream

    try:
        with mock.patch.object(reader, '_directory', side_effect=tracking_directory), \
             mock.patch.object(reader.os, 'fdopen', side_effect=close_fault_stream):
            try:
                with reader._input(path):
                    raise primary
            except BaseException as raised:
                result = {
                    'case': 'consuming_stream_close_during_body_failure',
                    'raised_cleanup_error': raised is cleanup,
                    'primary_only_in_context': raised.__context__ is primary,
                    'parent_closed': not is_open(state['parent']),
                    'stream_closed': state['stream'].closed,
                    'close_attempts': state['close_calls'],
                }
        assert result['raised_cleanup_error'] and result['primary_only_in_context']
        assert result['parent_closed'] and result['stream_closed']
        assert result['close_attempts'] == 1
        results.append(result)
    finally:
        release_witnesses(state)

    state = {'directory_calls': 0, 'close_calls': 0}
    cleanup = OSError(errno.EIO, 'injected consuming fresh parent close failure')

    def tracking_directory(selected):
        result = real_directory(selected)
        state['directory_calls'] += 1
        state['parent' if state['directory_calls'] == 1 else 'fresh'] = result[0]
        return result

    def consuming_fresh_close(descriptor):
        if descriptor == state.get('fresh'):
            state['close_calls'] += 1
            real_close(descriptor)
            state['witness'] = os.open('/dev/null', os.O_RDONLY)
            raise cleanup
        return real_close(descriptor)

    try:
        with mock.patch.object(reader, '_directory', side_effect=tracking_directory), \
             mock.patch.object(reader.os, 'close', side_effect=consuming_fresh_close):
            try:
                with reader._input(path) as (stream, size):
                    state['stream'] = stream
                    path.write_bytes(b'y' * (size + 1))
            except BaseException as raised:
                result = {
                    'case': 'fresh_parent_close_during_validation_failure',
                    'raised_cleanup_error': raised is cleanup,
                    'validation_only_in_context': isinstance(raised.__context__, reader.ArchiveError),
                    'context_message': str(raised.__context__),
                    'parent_closed': not is_open(state['parent']),
                    'stream_closed': state['stream'].closed,
                    'recycled_descriptor': state['witness'] == state['fresh'],
                    'witness_survives': is_open(state['witness']),
                    'close_attempts': state['close_calls'],
                }
        assert result['raised_cleanup_error'] and result['validation_only_in_context']
        assert result['parent_closed'] and result['stream_closed']
        assert result['recycled_descriptor'] and result['witness_survives']
        assert result['close_attempts'] == 1
        results.append(result)
    finally:
        # fresh is the consumed fd and is now owned by witness: remove its alias.
        state.pop('fresh', None)
        release_witnesses(state)

after_hash = hashlib.sha256(source.read_bytes()).hexdigest()
assert before_hash == after_hash
print(json.dumps({'source_sha256': before_hash, 'source_stable': True, 'cases': results}, indent=2))
