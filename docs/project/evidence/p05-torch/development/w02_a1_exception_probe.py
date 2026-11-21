from pathlib import Path
import hashlib
import importlib.util
import json
import struct
import sys

root = Path('/workspace/scratch/55f1fb23ad42/AI-GPU')
draft = Path('/workspace/scratch/55f1fb23ad42/p05-torch-work/drafts/torch_ops.py')
sys.path[:0] = [str(root / 'python'), str(root / 'ci/project')]
import torch
import vortex_ai
from test_p05_python_api import NativeMock
native = NativeMock()
sys.modules['vortex_ai._native'] = native
spec = importlib.util.spec_from_file_location('vortex_ai.torch_ops', draft)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

class NoAttributesError(RuntimeError):
    def __setattr__(self, name, value):
        raise MemoryError('exception attribute attachment deliberately fails')

session = vortex_ai.Session.open('/mock/bundle')
adapter = module.TorchSession(session)
a = torch.zeros((8, 8), dtype=torch.float16)
b = torch.zeros((4, 8), dtype=torch.float16).t()

def fail_after_enqueue():
    raise NoAttributesError('submission interrupted after pending registration')

native.on_submit = fail_after_enqueue
try:
    adapter.matmul(a, b)
except NoAttributesError as error:
    assert not hasattr(error, 'operation') and not hasattr(error, 'session')
else:
    raise AssertionError('injected exception was hidden')
pending = adapter.pending_operations()
assert len(pending) == 1 and adapter.last_operation is pending[0]
assert pending[0].wait().ok and pending[0].close().ok
native.on_submit = None
result = adapter.matmul(a, b)
assert result.shape == (8, 4)
closed = adapter.last_operation
original = native.operation_output
native.operation_output = lambda cap: (_ for _ in ()).throw(MemoryError('output publication fault'))
try:
    adapter.matmul(a, b)
except MemoryError as error:
    assert error.adapter is adapter and error.operation is adapter.last_operation
    assert error.session is session and error.operation is not closed
    assert error.operation.status.ok and not adapter.pending_operations()
else:
    raise AssertionError('output construction failure was hidden')
native.operation_output = original
assert adapter.matmul(a, b).shape == (8, 4)
retained = adapter.last_operation
token = adapter.token
adapter.close()
adapter.close()
assert session.status.ok
assert session.close().ok
assert retained.output_words() == tuple(range(32))
try:
    torch.ops.vortex_ai.matmul_v1(a, b, token, 0x7FC0DEAD)
except vortex_ai.BindingError as error:
    assert error.kind == 'state'
else:
    raise AssertionError('detached token accepted')
report = {'scope':'host-only actual PyTorch with scripted native responses',
 'torch':str(torch.__version__), 'adapter_sha256':hashlib.sha256(draft.read_bytes()).hexdigest(),
 'checks':['exception_attributes_unavailable_pending_recoverable',
 'output_publication_failure_after_close_owner_retained', 'recovery_resubmission',
 'detach_idempotent_native_session_borrowed', 'closed_output_survives', 'detached_raw_token_rejected'],
 'outcome':'pass', 'native_accelerator_execution':False}
print(json.dumps(report, indent=2))
