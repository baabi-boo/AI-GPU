# SPDX-License-Identifier: Apache-2.0
"""Actual Torch, frozen fixtures and scripted owners; no native execution."""
from contextlib import ExitStack
from dataclasses import dataclass
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest import mock

ROOT = Path('/workspace/scratch/55f1fb23ad42/AI-GPU')
WORK = ROOT.parent / 'p05-torch-work'
sys.path.insert(0, str(ROOT / 'ci/project'))
import torch
from p05_torch_qualification_test_fixture import packed, raw_log, synthetic
import p05_torch_records as records

@dataclass
class Status:
    validation: str = 'success'
    primary: int = 0
    cleanup: int = 0
    complete: bool = True
    def raise_for_status(self, *_):
        assert (self.validation, self.primary, self.cleanup, self.complete) == ('success', 0, 0, True)

class Operation:
    def __init__(self, row):
        self.row = row
        self.status = Status()
    def close(self, *_): return Status()
    def trace(self): return self.row['trace']
    def output_bytes(self): return packed(self.row['actual_bits'])

class Model(Operation):
    def record(self, iteration):
        assert iteration == self.row['iteration']
        return self.row['record']
    def trace(self): return self.row['record']['trace']
    def output_bytes(self): return packed(self.trace()['output_words'])

class TorchProxy:
    def __init__(self, ops): self.ops = ops
    def __getattr__(self, name): return getattr(torch, name)

def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, WORK / 'drafts' / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

for label, filename in [('original', 'p05_torch_installed_check.py'),
                        ('fixed', 'w03_a4_p05_torch_installed_check.py')]:
    checker = load('w03_a4_' + label, filename)
    for fmt in ('fp16', 'bf16'):
        with tempfile.TemporaryDirectory(prefix='p05-scripted-frozen-overlap-') as tmp:
            template, request, native = synthetic(Path(tmp), fmt)
            base = template['base_observations']
            first_memory = base['matmuls'][0]['resources']
            session = SimpleNamespace(status=Status(), pending_operations=lambda: (), close=lambda: Status(),
                memory_info=lambda: (0, first_memory['free_before'], first_memory['used_before']))
            adapter = SimpleNamespace(token=1, last_operation=None, close=lambda: None)
            matmuls, models = iter(base['matmuls']), iter(base['models'])
            backing = bytearray(260)
            zero_tensors = []
            def matmul(*_):
                adapter.last_operation = Operation(next(matmuls))
                return torch.frombuffer(bytearray(adapter.last_operation.output_bytes()), dtype=torch.float32).clone().view(8,4)
            def model(case_id, *_):
                adapter.last_operation = Model(next(models))
                data = adapter.last_operation.output_bytes()
                if case_id == fmt + '-zero':
                    assert data == bytes(256)
                    value = torch.frombuffer(backing, dtype=torch.float32, count=64,
                                             offset=4*len(zero_tensors)).view(16,4)
                    zero_tensors.append(value)
                    return value
                return torch.frombuffer(bytearray(data), dtype=torch.float32).clone().view(16,4)
            # The third matmul has (16,8) output; derive shape from its actual row.
            def matmul_shape(*_):
                adapter.last_operation = Operation(next(matmuls))
                trace = adapter.last_operation.trace()
                return torch.frombuffer(bytearray(adapter.last_operation.output_bytes()), dtype=torch.float32).clone().view(trace['m'],trace['n'])
            api = SimpleNamespace(Session=SimpleNamespace(open=lambda *_: session), Operation=Operation, ModelOperation=Model)
            proxy = TorchProxy(SimpleNamespace(vortex_ai=SimpleNamespace(matmul_v1=matmul_shape, fixed_mlp_v1=model)))
            try:
                with mock.patch.object(checker.check, 'session_identity', return_value=base['installation']['runtime_libraries']), \
                        mock.patch.object(checker.check, 'emit'):
                    value = checker.run_matrix(request, api, proxy, SimpleNamespace(TorchSession=lambda *_: adapter),
                        base['installation'], template['framework'], checker.check.RunState())
                result = records.verify_observations(value, request, **native, raw_log=raw_log(value))
                print(json.dumps({'checker':label, 'format':fmt,'outcome':'accepted',
                    'scope':'host-only-scripted-native-frozen-fixtures','native_execution':False,
                    'verified_framework_calls':result['operator_calls'],
                    'overlapping_zero_result_offset':zero_tensors[1].untyped_storage().data_ptr()-zero_tensors[0].untyped_storage().data_ptr()}))
            except ValueError as error:
                print(json.dumps({'checker':label,'format':fmt,'outcome':'rejected','reason':str(error),
                    'scope':'host-only-scripted-native-frozen-fixtures','native_execution':False}))
