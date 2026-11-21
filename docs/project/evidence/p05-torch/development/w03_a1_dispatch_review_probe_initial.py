from pathlib import Path
import contextlib
import hashlib
import importlib.util
import json
import struct
import sys
import traceback

ROOT = Path('/workspace/scratch/55f1fb23ad42/AI-GPU')
WORK = ROOT.parent / 'p05-torch-work'
ADAPTER = WORK / 'drafts/torch_ops.py'
sys.path[:0] = [str(ROOT / 'python'), str(ROOT / 'ci/project')]
import torch
import vortex_ai
from test_p05_python_api import NativeMock
native = NativeMock()
sys.modules['vortex_ai._native'] = native
spec = importlib.util.spec_from_file_location('vortex_ai.torch_ops', ADAPTER)
ops = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = ops
spec.loader.exec_module(ops)

session = vortex_ai.Session.open('/host-only/scripted-bundle')
adapter = ops.TorchSession(session)
a = torch.zeros((8, 8), dtype=torch.float16)
b = torch.zeros((4, 8), dtype=torch.float16).t()
x = torch.zeros((16,4))
rows = []

def count():
    return sum(isinstance(call, tuple) and call[0] in ('submit', 'model_create') for call in native.calls)
def mat(left=a, right=b):
    return torch.ops.vortex_ai.matmul_v1(left, right, adapter.token, 0x7fc0dead)
def model():
    return torch.ops.vortex_ai.fixed_mlp_v1('fp16-seeded_dense', adapter.token, 0x7fc0dead)
def record(name, function, expected='reject'):
    before=count()
    row={'name':name, 'expected':expected}
    try:
        value=function()
        row['outcome']='returned'
        row['return_type']=type(value).__name__
        if type(value) is torch.Tensor:
            row['result']={'shape':list(value.shape),'strides':list(value.stride()),'dtype':str(value.dtype),'device':str(value.device),'requires_grad':value.requires_grad}
    except BaseException as error:
        row.update(outcome='raised',error=type(error).__name__,message=str(error)[:800])
    row['native_calls']=count()-before
    row['pending']=len(session.pending_operations())
    if expected=='reject':
        row['pass']=row['outcome']=='raised' and row['native_calls']==0 and row['pending']==0
    elif expected=='success':
        row['pass']=row['outcome']=='returned' and row['native_calls']==1 and row['pending']==0
    rows.append(row)
    print(json.dumps(row),flush=True)

def contextual(context, function):
    with context:
        return function()

record('ordinary',mat,'success')
record('model',model,'success')
record('inference_new_inputs',lambda: contextual(torch.inference_mode(),lambda:mat(a.clone(),b.t().clone().t())),'success')
record('inference_existing_requires_grad',lambda: contextual(torch.inference_mode(),lambda:mat(a.clone().requires_grad_(True),b)))
record('nn_Parameter',lambda:mat(torch.nn.Parameter(a,requires_grad=False),b))
record('typed_subclass',lambda:mat(a.as_subclass(type('Sub',(torch.Tensor,),{})),b))
record('sparse_csr',lambda:mat(a.to_sparse_csr(),b))
record('mkldnn',lambda:mat(a.to_mkldnn(),b))
record('nested',lambda:mat(torch.nested.nested_tensor([a,a]),b))
record('negative_b',lambda:mat(a,torch._neg_view(b)))
record('no_grad_negative_b',lambda:contextual(torch.no_grad(),lambda:mat(a,torch._neg_view(b))))
record('inference_negative_b',lambda:contextual(torch.inference_mode(),lambda:mat(a,torch._neg_view(b))))
record('default_dtype_float64',lambda:contextual(contextlib.nullcontext(),mat),'success')
record('default_device_meta',lambda:contextual(torch.device('meta'),mat),'success')
record('default_device_meta_model',lambda:contextual(torch.device('meta'),model),'success')

with torch.autograd.forward_ad.dual_level():
    dual_a=torch.autograd.forward_ad.make_dual(a,torch.ones_like(a))
    dual_b=torch.autograd.forward_ad.make_dual(b,torch.ones_like(b))
    record('forward_dual_a',lambda:mat(dual_a,b))
    record('forward_dual_b',lambda:mat(a,dual_b))
    record('forward_dual_b_no_grad',lambda:contextual(torch.no_grad(),lambda:mat(a,dual_b)))
    record('forward_dual_a_inference',lambda:contextual(torch.inference_mode(),lambda:mat(dual_a,b)))
    record('forward_dual_b_inference',lambda:contextual(torch.inference_mode(),lambda:mat(a,dual_b)))

for name, transform in [
 ('func_grad', lambda f,z:torch.func.grad(lambda p:f(p).sum())(z)),
 ('func_vjp', lambda f,z:torch.func.vjp(f,z)),
 ('func_jacfwd',lambda f,z:torch.func.jacfwd(f)(z)),
 ('func_jacrev',lambda f,z:torch.func.jacrev(f)(z)),
 ('func_hessian',lambda f,z:torch.func.hessian(lambda p:f(p).sum())(z)),
 ('func_linearize',lambda f,z:torch.func.linearize(f,z)),
 ('func_vmap',lambda f,z:torch.vmap(f)(z.unsqueeze(0))),
 ('func_functionalize_views',lambda f,z:torch.func.functionalize(f,remove='mutations_and_views')(z))]:
    record(name+'_matmul',lambda transform=transform:transform(lambda p:mat(p,b),a))
    record(name+'_model',lambda transform=transform:transform(lambda p:model()+p,x))

record('jit_trace_model_no_check',lambda:torch.jit.trace(lambda y:model()+y,x,check_trace=False))
record('fx_symbolic_trace_matmul',lambda:torch.fx.symbolic_trace(lambda a,b:mat(a,b)),'observe')
record('fx_symbolic_trace_model',lambda:torch.fx.symbolic_trace(lambda y:model()+y),'observe')

class MatModule(torch.nn.Module):
    def forward(self,a,b):
        return torch.ops.vortex_ai.matmul_v1(a,b,4294967296,2143346349)
class ModelModule(torch.nn.Module):
    def forward(self,x):
        return torch.ops.vortex_ai.fixed_mlp_v1('fp16-seeded_dense',4294967296,2143346349)+x
record('export_strict_matmul',lambda:torch.export.export(MatModule(),(a,b),strict=True))
record('export_strict_model',lambda:torch.export.export(ModelModule(),(x,),strict=True))
record('export_nonstrict_matmul',lambda:torch.export.export(MatModule(),(a,b),strict=False))
record('export_nonstrict_model',lambda:torch.export.export(ModelModule(),(x,),strict=False))
record('jit_script_create_matmul',lambda:torch.jit.script(MatModule()),'observe')
record('jit_script_run_matmul',lambda:torch.jit.script(MatModule())(a,b),'observe')
record('jit_script_create_model',lambda:torch.jit.script(ModelModule()),'observe')
record('jit_script_run_model',lambda:torch.jit.script(ModelModule())(x),'observe')

for op in session.pending_operations():op.close()
adapter.close()
session.close()
report={'scope':'host-only-real-pytorch-scripted-native-mock','native_execution':'not_run','acceptance_claimed':False,'torch_version':str(torch.__version__),'adapter_sha256':hashlib.sha256(ADAPTER.read_bytes()).hexdigest(),'rows':rows}
(WORK/'w03_a1_dispatch_review_probe.json').write_text(json.dumps(report,indent=2)+'\n')
print('SUMMARY',json.dumps({'checks':len(rows),'rejections':sum(r['expected']=='reject' for r in rows),'unexpected':sum(r.get('pass') is False for r in rows)}))
