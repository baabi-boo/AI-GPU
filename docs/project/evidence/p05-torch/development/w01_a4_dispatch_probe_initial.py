import contextlib, json, torch, warnings
from torch import Tensor
print('TORCH',torch.__version__)
calls=[]
def gate(*xs):
    if torch.compiler.is_compiling(): raise RuntimeError('reject compiling')
    if torch.jit.is_tracing() or torch.jit.is_scripting(): raise RuntimeError('reject tracing')
    if torch.is_autocast_enabled('cpu'): raise RuntimeError('reject autocast')
    for x in xs:
        if type(x) is not Tensor: raise TypeError('reject subclass')
        if x.device.type!='cpu': raise ValueError('reject device')
        if x.requires_grad: raise ValueError('reject gradient')
        if torch.autograd.forward_ad.unpack_dual(x).tangent is not None: raise ValueError('reject forward AD')
        if x.is_neg() or x.is_conj(): raise ValueError('reject unresolved bits')

def rejected(*args,**kwargs): raise RuntimeError('unsupported torch transform')

@torch.library.custom_op('audit_custom::matmul',mutates_args=(),device_types='cpu')
def cm(a:Tensor,b:Tensor, token:int)->Tensor:
    gate(a,b);calls.append('custom_matmul'); return torch.zeros((a.shape[0],b.shape[1]),dtype=torch.float32)
cm.register_fake(rejected)
cm.register_vmap(rejected)
@torch.library.custom_op('audit_custom::model',mutates_args=())
def cf(case:str,token:int)->Tensor:
    gate();calls.append('custom_model');return torch.zeros((16,4),dtype=torch.float32)
cf.register_fake(rejected)
cf.register_vmap(rejected)

lib=torch.library.Library('audit_library','DEF')
lib.define('matmul(Tensor a, Tensor b, int token) -> Tensor')
lib.define('model(str case, int token) -> Tensor')
def lm(a,b,token):
    gate(a,b);calls.append('library_matmul');return torch.zeros((a.shape[0],b.shape[1]),dtype=torch.float32)
def lf(case,token):
    gate();calls.append('library_model');return torch.zeros((16,4),dtype=torch.float32)
lib.impl('matmul',lm,'CPU')
lib.impl('matmul',lm,'Autograd')
lib.impl('model',lf,'CompositeExplicitAutograd')
for name in ('matmul','model'):
    lib.impl(name,rejected,'Meta')
    lib.impl(name,rejected,'FuncTorchBatched')
    lib.impl(name,rejected,'FuncTorchVmapMode')
    lib.impl(name,rejected,'Functionalize')
    lib.impl(name,rejected,'Tracer')
    lib.impl(name,rejected,'AutocastCPU')

results=[]
def run(name,fn):
    before=len(calls)
    try:
        v=fn(); state='returned';detail=str((tuple(v.shape),v.dtype,v.requires_grad))
    except Exception as e: state='rejected';detail=type(e).__name__+': '+str(e).split('\n')[0][:240]
    row=dict(name=name,state=state,body_calls=len(calls)-before,detail=detail)
    results.append(row); print(json.dumps(row),flush=True)

a=torch.ones((8,8),dtype=torch.float16); b=torch.ones((4,8),dtype=torch.float16).t()
for prefix in ('audit_custom','audit_library'):
    op=getattr(torch.ops,prefix).matmul
    model=getattr(torch.ops,prefix).model
    run(prefix+'_eager',lambda:op(a,b,1))
    run(prefix+'_model_eager',lambda:model('x',1))
    run(prefix+'_grad',lambda:op(a.requires_grad_(),b,1))
    with torch.no_grad(): run(prefix+'_grad_no_grad',lambda:op(a,b,1))
    a.requires_grad_(False)
    with torch.inference_mode(): run(prefix+'_inference',lambda:op(a,b,1))
    with torch.autocast('cpu'):
        run(prefix+'_autocast',lambda:op(a,b,1))
        run(prefix+'_model_autocast',lambda:model('x',1))
    with torch.autograd.forward_ad.dual_level():
        dual=torch.autograd.forward_ad.make_dual(a,torch.ones_like(a))
        run(prefix+'_forward_ad',lambda:op(dual,b,1))
    run(prefix+'_meta',lambda:op(a.to('meta'),b.to('meta'),1))
    run(prefix+'_negative',lambda:op(torch._neg_view(a),b,1))
    run(prefix+'_vmap',lambda:torch.vmap(lambda z:op(z,b,1))(a.unsqueeze(0)))
    run(prefix+'_model_vmap',lambda:torch.vmap(lambda z:model('x',1))(a.unsqueeze(0)))
    from torch._subclasses.fake_tensor import FakeTensorMode
    with FakeTensorMode() as mode:
        fa=mode.from_tensor(a);fb=mode.from_tensor(b)
        run(prefix+'_fake',lambda:op(fa,fb,1))
        run(prefix+'_model_fake',lambda:model('x',1))
    run(prefix+'_compile',lambda:torch.compile(lambda x,y:op(x,y,1),backend='eager',fullgraph=True)(a,b))
    run(prefix+'_model_compile',lambda:torch.compile(lambda x:model('x',1)+x,backend='eager',fullgraph=True)(torch.zeros(16,4)))
    run(prefix+'_trace',lambda:torch.jit.trace(lambda x:op(x,b,1),a))
    run(prefix+'_model_trace',lambda:torch.jit.trace(lambda x:model('x',1)+x,torch.zeros(16,4)))
print('SUMMARY',json.dumps(results))
