# SPDX-License-Identifier: Apache-2.0
"""Host-only probes of checker ownership policy; no Torch or native work runs."""
from contextlib import ExitStack
import unittest
from types import SimpleNamespace
from unittest import mock
import p05_torch_installed_check as checker

class FakeStorage:

    def __init__(self, address, size):
        self.address, self.size = (address, size)

    def data_ptr(self):
        return self.address

    def nbytes(self):
        return self.size

class FakeTensor:

    def __init__(self, address, size):
        self.storage = FakeStorage(address, size)

    def untyped_storage(self):
        return self.storage

class FakeOperation:

    def __init__(self, size):
        self.size = size
        self.status = SimpleNamespace(raise_for_status=lambda *_: None)

    def close(self, *_):
        return SimpleNamespace(complete=True)

    def output_bytes(self):
        return bytes(self.size)

    def trace(self):
        return {'launches_enqueued': 1, 'event_profiles': [{'queued_ns': 100}]}

class FakeModel(FakeOperation):

    def record(self, iteration):
        return {'trace': {'native': [{'dispatch': {'launches_enqueued': 1}} for _ in range(3)], 'create_begin_ns': 100}}

def exercise(kind='outputs', relation='overlap', boundary='matmul', *, module=None):
    module = checker if module is None else module
    session = SimpleNamespace(status=object(), pending_operations=lambda: (), close=lambda: SimpleNamespace(complete=True))
    adapter = SimpleNamespace(token=1, last_operation=None, close=lambda: None)
    generated = []
    emitted = []
    calls = []

    def inputs(_torch, data, shape, dtype, **kw):
        value = FakeTensor(100000 + len(generated) * 10000, len(data))
        generated.append(value)
        return value

    def observation(_torch, value, *, shape, strides, dtype, **kw):
        return {'shape': list(shape), 'strides': list(strides), 'dtype': dtype, 'device': 'cpu', 'storage_offset': 0, 'requires_grad': False, 'bytes': bytes(value.storage.size).hex()}

    def output(size, call_kind, source=()):
        index = len(calls)
        calls.append(call_kind)
        address = 1000000 + index * 10000
        selected = call_kind == boundary and (index == 1 if boundary == 'matmul' else index == 6)
        if selected and kind == 'outputs':
            base = 1000000
            address = base + {'overlap': 4, 'adjacent': 128}[relation]
        if selected and kind == 'inputs':
            address = (source[0] if source else generated[0]).storage.address + 4
        adapter.last_operation = (FakeOperation if call_kind == 'matmul' else FakeModel)(size)
        return FakeTensor(address, size)

    def matmul(a, b, *_):
        return output(128, 'matmul', (a, b))

    def model(*_):
        return output(256, 'model')
    torch = SimpleNamespace(float16='fp16', bfloat16='bf16', float32='fp32', ops=SimpleNamespace(vortex_ai=SimpleNamespace(matmul_v1=matmul, fixed_mlp_v1=model)))
    api = SimpleNamespace(Session=SimpleNamespace(open=lambda *_: session), Operation=FakeOperation, ModelOperation=FakeModel)
    request = {'base_request': {'binding': {'bundle_root': 'HOST-ONLY', 'format': 'fp16', 'qualification_id': 'HOST-ONLY'}, 'matmul_cases': [{'id': str(i), 'm': 8, 'n': 4, 'k': 8, 'format': 'fp16', 'a_words': ['00000000'] * 32, 'b_words': ['00000000'] * 16, 'expected': ['00000000'] * 32} for i in range(3)], 'model_cases': ['host-only-' + str(i) for i in range(5)]}}
    with ExitStack() as stack:
        for name, value in {'successful': lambda value, *_: {}, 'session_identity': lambda *_: [], 'memory_info': lambda *_: {}, 'emit': lambda *args, **_: emitted.append(args), 'dispatch': lambda *_: 100, 'check_model': lambda *_: 100, 'resources': lambda *_: {}}.items():
            stack.enter_context(mock.patch.object(module.check, name, value))
        stack.enter_context(mock.patch.object(module, '_input', inputs))
        stack.enter_context(mock.patch.object(module, 'tensor_observation', observation))
        return module.run_matrix(request, api, torch, SimpleNamespace(TorchSession=lambda *_: adapter), {}, {}, module.check.RunState())

class ResultStorageIndependenceTests(unittest.TestCase):

    def test_partial_overlap_with_earlier_live_result_is_rejected(self):
        for boundary in ('matmul', 'model'):
            with self.subTest(boundary=boundary):
                with self.assertRaisesRegex(ValueError, 'aliases'):
                    exercise(boundary=boundary)

    def test_partial_overlap_with_current_matmul_input_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'aliases'):
            exercise(kind='inputs')

    def test_model_result_cannot_alias_a_previous_matrix_input(self):
        with self.assertRaisesRegex(ValueError, 'aliases'):
            exercise(kind='inputs', boundary='model')

    def test_adjacent_nonoverlapping_results_remain_valid(self):
        for boundary in ('matmul', 'model'):
            with self.subTest(boundary=boundary):
                value = exercise(relation='adjacent', boundary=boundary)
                self.assertEqual(value['outcome'], 'pass')
                self.assertEqual(value['base_observations']['counts']['total_launches'], 36)
if __name__ == '__main__':
    unittest.main(verbosity=2)
