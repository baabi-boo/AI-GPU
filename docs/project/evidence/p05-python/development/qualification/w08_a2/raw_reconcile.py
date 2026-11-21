"""Read raw JSON lines independently; no auditor/producer imports or execution."""
from pathlib import Path
import hashlib
import json
import struct

ROOT=Path('/workspace/scratch/ba0248fde989/p05-work/ci-e1420fd/simx-fp16/python')
OUT=Path('/workspace/scratch/ba0248fde989/p05-work/w08_a2/manual-reconciliation.json')
AUDIT=Path('/workspace/scratch/ba0248fde989/AI-GPU/docs/project/evidence/p05-python/reviews/fp16-dispatch.json')
REVIS='e1420fd550f716df33a2556057b7086a03032cbe'
NATIVE_OK={'cleanup':0,'complete':True,'primary':0,'validation':0}
PYTHON_OK=dict(NATIVE_OK,validation='success')
PENDING=dict(NATIVE_OK,complete=False)
POOL=0x200000000-0x10000

def read_rows(root, commands, marker):
    rows=[]
    for command in commands:
        body=(root/command['log']).read_bytes()
        assert len(body)==command['log_size_bytes']
        assert hashlib.sha256(body).hexdigest()==command['log_sha256']
        for line in body.decode().splitlines():
            if line.startswith(marker+' '):
                rows.append((command,json.loads(line[len(marker)+1:])))
    return rows

def memory(value):
    assert value['free_before']==value['free_after']
    assert value['used_before']==value['used_after']>0
    assert value['free_before']+value['used_before']==POOL
    assert value['free_before']%64==value['used_before']%64==0

def dispatch(value,native=False):
    sizes=[value[k+'_bytes'] for k in ('a','b','d')]
    addresses=[value[k+'_address'] for k in ('a','b','d')]
    for start,length in zip(addresses,sizes):
        assert start%64==0 and 0x10000<=start<start+length<=0x200000000
    spans=sorted(zip(addresses,sizes))
    assert all(left[0]+left[1]<=right[0] for left,right in zip(spans,spans[1:]))
    wire=struct.unpack('<8I3Q',bytes.fromhex(value['argument_bytes']))
    assert wire[:4]==(1,56,1,0) and wire[7]==0 and wire[8:]==tuple(addresses)
    m,n,k=wire[4:7]
    assert sizes==[m*k*2,k*n*2,m*n*4]
    assert [value[x] for x in (('writes','launches','reads') if native else ('writes_enqueued','launches_enqueued','reads_enqueued'))]==[3,1,1]
    assert value['waits' if native else 'wait_calls']==1
    if native:
        return {'h2d':sum(sizes),'d2h':sizes[2],'profiles':0}
    assert value['timed_out_waits']==0
    assert value['profiling_enabled'] is True
    assert value['event_results']==value['event_profile_results']==[0]*5
    assert value['event_profile_queried']==[True]*5
    profiles=value['event_profiles'];assert len(profiles)==5
    previous_queued=previous_end=0
    for event in profiles:
        q,s,b,e=[event[k] for k in ('queued_ns','submit_ns','start_ns','end_ns')]
        assert previous_queued<=q<=s<=b<=e and previous_end<=s
        previous_queued,previous_end=q,e
    return {'h2d':sum(sizes),'d2h':sizes[2],'profiles':5,'first_ns':profiles[0]['queued_ns'],'last_ns':profiles[-1]['end_ns']}

def totals(matmuls,models,python):
    values=[];model_bounds=[];host={k:[] for k in ('advance_ns','bridge_ns','bridge_compare_ns','assembly_ns','output_compare_ns','close_ns')}
    poisons=[]
    for command,row in matmuls:
        memory(row['resources'])
        if python:assert row['status']==row['close_status']==PYTHON_OK
        d=row['trace' if python else 'dispatch'];poisons.append(d['poison'])
        values.append(dispatch(d,native=not python))
    for command,wrapper in models:
        row=wrapper['record'] if python else wrapper
        assert row['source_revision']==REVIS and row['backend']=='simx'
        trace=row['trace'];memory(trace['resources'])
        assert trace['owner_closed'] is True and trace['owner_cleanup']==NATIVE_OK
        assert trace['result']=={'execution':NATIVE_OK,'status':'success','terminal':True}
        stages=trace['native'];assert len(stages)==3
        assert [(s['operation_id'],s['sequence'],s['row_begin'],s['row_end']) for s in stages]==[
            ('hidden_matmul',0,0,16),('output_rows_0_7',1,0,8),('output_rows_8_15',2,8,16)]
        assert trace['hidden_words']==stages[0]['output_words']
        assert trace['output_words']==stages[1]['output_words']+stages[2]['output_words']
        bridge=bytes.fromhex(trace['bridge_bytes']);assert len(bridge)==256
        assert bytes.fromhex(stages[1]['a_bytes'])==bridge[:128]
        assert bytes.fromhex(stages[2]['a_bytes'])==bridge[128:]
        stage_values=[]
        for stage in stages:
            assert stage['submission']==PENDING
            assert stage['completion']==stage['cleanup']==NATIVE_OK
            assert all(stage[k] is True for k in ('submitted','waited','trace_valid','output_valid','compared','closed'))
            event=dispatch(stage['dispatch']);stage_values.append(event);values.append(event)
            assert stage['submit_begin_ns']<=event['first_ns']<=stage['submit_end_ns']
        assert stage_values[0]['last_ns']<=stage_values[1]['first_ns']
        assert stage_values[1]['last_ns']<=stage_values[2]['first_ns']
        assert trace['create_begin_ns']<=trace['create_end_ns']<=stage_values[0]['first_ns']
        lower_end=stage_values[-1]['last_ns']+trace['close_ns']
        model_bounds.append({'case':trace['case_id'],'iteration':row['iteration'],'command':command['id'],
                             'create_ns':trace['create_begin_ns'],'last_read_ns':stage_values[-1]['last_ns'],
                             'close_ns':trace['close_ns'],'lower_close_end_ns':lower_end,
                             'monitored_duration_ns':round(command['duration_seconds']*1e9)})
        for key in host:host[key].append(trace[key])
        poisons.append(trace['poison'])
    gaps=[]
    for a,b in zip(model_bounds,model_bounds[1:]):
        if a['command']==b['command']:
            gap=b['create_ns']-a['lower_close_end_ns'];assert gap>=0;gaps.append(gap)
    assert set(poisons)=={0x7fc0dead,0xdeadbeef}
    answer={'matmul_runs':len(matmuls),'model_runs':len(models),'launches':len(values),
            'h2d_transfers':len(values)*3,'d2h_transfers':len(values),
            'tensor_h2d_bytes':sum(v['h2d'] for v in values),'tensor_d2h_bytes':sum(v['d2h'] for v in values),
            'profile_pairs':sum(v['profiles'] for v in values),'argument_block_bytes':len(values)*56,
            'host_bridge_bytes':len(models)*256,'host_assembly_bytes':len(models)*256,
            'host_duration_ns':{k:{'count':len(v),'min':min(v),'max':max(v),'sum':sum(v)} for k,v in host.items()},
            'close_to_next_create_slack_ns':{'count':len(gaps),'min':min(gaps),'max':max(gaps)},
            'model_bounds':model_bounds}
    if python:
        profiled=[v for v in values if v['profiles']]
        first,last=profiled[0]['first_ns'],profiled[-1]['last_ns']
        assert last-first<=model_bounds[-1]['monitored_duration_ns']
        answer['installed_profile_span_ns']=last-first
        answer['installed_command_duration_ns']=model_bounds[-1]['monitored_duration_ns']
    return answer

report=json.loads((ROOT/'report.json').read_text());native=json.loads((ROOT/'native/report.json').read_text())
python_matmul=read_rows(ROOT,report['commands'],'P05_MATMUL')
python_models=read_rows(ROOT,report['commands'],'P05_MODEL')
native_matmul=read_rows(ROOT,report['commands'],'P03_RESULT')
native_models=read_rows(ROOT/'native',native['commands'],'P04_RESULT')
assert [len(x) for x in (python_matmul,python_models,native_matmul,native_models)]==[6,10,6,10]
result={'schema_version':1,'scope':'independent raw-record reconciliation; no auditor or producer imports; no native execution',
        'python':totals(python_matmul,python_models,True),'native_comparison':totals(native_matmul,native_models,False),
        'commands':{'outer':len(report['commands']),'native':len(native['commands'])},'outcome':'pass','acceptance_claimed':False}
audit=json.loads(AUDIT.read_text())
mapping={'launches':'total_launches','profile_pairs':'event_profile_pairs'}
for route in ('python','native_comparison'):
    for key in ('launches','profile_pairs','tensor_h2d_bytes','tensor_d2h_bytes','h2d_transfers','d2h_transfers','argument_block_bytes','host_bridge_bytes','host_assembly_bytes','matmul_runs','model_runs'):
        assert result[route][key]==audit['counts'][route][mapping.get(key,key)]
OUT.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
print(json.dumps({route:{k:v for k,v in result[route].items() if k not in ('model_bounds','host_duration_ns')} for route in ('python','native_comparison')},indent=2))
