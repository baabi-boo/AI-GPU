#!/usr/bin/env python3
"""Independent host-only probe of adapter construction and ownership."""
import argparse
import gc
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import traceback
from unittest import mock

p=argparse.ArgumentParser()
p.add_argument('--adapter', type=Path, required=True)
p.add_argument('--source-dir', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
a=p.parse_args()
sys.path[:0]=[str(a.source_dir/'python'),str(a.source_dir/'ci/project')]
import torch
import vortex_ai as api
from test_p05_python_api import NativeMock, status
spec=importlib.util.spec_from_file_location('vortex_ai.torch_ops',a.adapter)
ops=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=ops
spec.loader.exec_module(ops)
rows=[]


def restore():
    for adapter in tuple(ops._REGISTRY.values()):
        for operation in adapter.session.pending_operations():
            operation.close()
        adapter.close()
        adapter.session.close()
    gc.collect()


def probe_partial(mode):
    native=NativeMock()
    sys.modules['vortex_ai._native']=native
    if mode=='native_error':
        native.session_open=lambda root: ({'ops':[],'closed':False},status(primary=6))
    elif mode=='malformed_info':
        native.session_info=lambda cap: {'format':'fp16'}
    elif mode=='interrupted_info':
        def interrupt(_cap):
            raise KeyboardInterrupt('injected identity publication interruption')
        native.session_info=interrupt
    elif mode=='malformed_status':
        native.session_open=lambda root: ({'ops':[],'closed':False},{'primary':6})
    try:
        session=api.Session.open('/host-only/scripted-bundle')
        raise AssertionError('open unexpectedly succeeded')
    except BaseException as error:
        session=error.session
        row={'case':mode,'open_error':type(error).__name__,'session_info':dict(session.info)}
    try:
        adapter=ops.TorchSession(session)
        row['attach']='accepted'
        try:
            adapter.fixed_mlp('fp16-seeded_dense')
            row['first_call']='returned'
        except BaseException as error:
            row['first_call']=type(error).__name__+': '+str(error)
        adapter.close()
    except BaseException as error:
        row['attach']='rejected'
        row['attach_error']=type(error).__name__+': '+str(error)
    row['native_model_submissions']=sum(isinstance(c,tuple) and c[0]=='model_create' for c in native.calls)
    try:
        row['session_close_ok']=session.close().ok
    except BaseException as error:
        row['session_close_error']=type(error).__name__+': '+str(error)
    rows.append(row)
    restore()


def probe_return_interrupt():
    native=NativeMock()
    sys.modules['vortex_ai._native']=native
    session=api.Session.open('/host-only/scripted-bundle')
    def trace(frame,event,arg):
        if frame.f_code is ops.TorchSession.__init__.__code__ and event=='return':
            raise KeyboardInterrupt('injected constructor return-publication interruption')
        return trace
    sys.settrace(trace)
    try:
        adapter=ops.TorchSession(session)
        raise AssertionError('construction unexpectedly published')
    except KeyboardInterrupt as error:
        row={'case':'constructor_return_interrupt','attached_error_adapter':hasattr(error,'adapter'),
             'registry_count_after_error':len(ops._REGISTRY)}
    finally:
        sys.settrace(None)
    try:
        replacement=ops.TorchSession(session)
        row['reattach']='succeeded'
        replacement.close()
    except BaseException as error:
        row['reattach']='rejected'
        row['reattach_error']=type(error).__name__+': '+str(error)
        row['reattach_error_has_adapter']=hasattr(error,'adapter')
        if hasattr(error,'adapter'):
            row['reattach_error_adapter_registered']=error.adapter in ops._REGISTRY.values()
    row['session_close_ok']=session.close().ok
    row['registry_after_session_close']=len(ops._REGISTRY)
    rows.append(row)
    restore()

for mode in ('native_error','malformed_info','interrupted_info','malformed_status'):
    probe_partial(mode)
probe_return_interrupt()
report={'scope':'host-only-real-pytorch-scripted-native-mock','acceptance_claimed':False,
        'python_version':sys.version.split()[0],'torch_version':torch.__version__,
        'adapter':str(a.adapter),'adapter_sha256':hashlib.sha256(a.adapter.read_bytes()).hexdigest(),
        'cases':rows}
a.output.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
