import hashlib,json,struct
from pathlib import Path
repo=Path('/workspace/scratch/ba0248fde989/AI-GPU')
root=Path('/workspace/scratch/ba0248fde989/p05-work/ci-e1420fd/simx-fp16/python')
result=json.loads((repo/'docs/project/evidence/p05-python/reviews/fp16-numerics.json').read_text())
report=json.loads((root/'report.json').read_text())
native=json.loads((root/'native/report.json').read_text())
selection=json.loads((root/'snapshots/selection.json').read_text())
fixture=json.loads((repo/'ci/project/fixtures/p04_tiny_mlp_v1.json').read_text())
fixtures={r['id']:r for r in fixture['cases']}
observed=json.loads((root/'artifacts/installed-observations.json').read_text())
def rows(path,marker):
 return [json.loads(line[len(marker)+1:]) for line in path.read_text().splitlines() if line.startswith(marker+' ')]
py_matmul=rows(root/'logs/installed-matrix.log','P05_MATMUL')
py_model=rows(root/'logs/installed-matrix.log','P05_MODEL')
assert py_matmul==observed['matmuls'] and py_model==observed['models']
assert len(py_matmul)==6 and len(py_model)==10
poisons=[0x7fc0dead,0xdeadbeef]
counts={'python':{'matmul_words':0,'model_hidden_words':0,'model_bridge_words':0,'model_output_block_words':0,'model_output_words':0,'event_profile_pairs':0},'native':{'matmul_words':0,'model_hidden_words':0,'model_bridge_words':0,'model_output_block_words':0,'model_output_words':0,'event_profile_pairs':0}}
boundaries=[]
for index,case in enumerate(selection['matmuls']):
 actual=rows(root/('logs/native-'+case['id']+'.log'),'P03_RESULT')
 assert actual==report['native_matmuls'][index]['observations'] and len(actual)==2
 for iteration in range(2):
  left=py_matmul[index*2+iteration];right=actual[iteration]
  assert left['actual_bits']==right['actual_bits']==case['expected']
  assert (right['m'],right['n'],right['k'])==((8,4,8),(8,4,16),(16,8,16))[index]
  for route,row,trace in [('python',left,left['trace']),('native',right,right['dispatch'])]:
   assert row['iteration']==iteration and trace['poison']==poisons[iteration]
   counts[route]['matmul_words']+=len(row['actual_bits'])
   counts[route]['event_profile_pairs']+=sum(trace['event_profile_queried'])
for index,case in enumerate(selection['models']):
 actual=rows(root/('native/logs/simx-fp16-'+case['id']+'.log'),'P04_RESULT')
 assert actual==native['variants'][0]['cases'][index]['observations'] and len(actual)==2
 for iteration in range(2):
  left=py_model[index*2+iteration]['record'];right=actual[iteration]
  assert left['trace']['hidden_words']==right['trace']['hidden_words']
  assert left['trace']['bridge_bytes']==right['trace']['bridge_bytes']
  assert left['trace']['output_words']==right['trace']['output_words']
  for route,record in [('python',left),('native',right)]:
   trace=record['trace'];stages=trace['native']; frozen=fixtures[case['id']]
   assert record['iteration']==iteration and trace['poison']==poisons[iteration]
   assert [(s['operation_id'],s['row_begin'],s['row_end']) for s in stages]==[('hidden_matmul',0,16),('output_rows_0_7',0,8),('output_rows_8_15',8,16)]
   for name in ('hidden_words','bridge_words','output_words'):
    assert trace[name]==frozen[name]
   assert trace['hidden_words']==stages[0]['output_words']
   bridge=bytes.fromhex(trace['bridge_bytes'])
   independent_bridge=b''.join(struct.pack('<e',max(0.0,struct.unpack('<f',bytes.fromhex(word)[::-1])[0])) for word in trace['hidden_words'])
   assert bridge==independent_bridge and len(bridge)==256
   assert trace['bridge_words']==[f'{int.from_bytes(bridge[i:i+4],"little"):08x}' for i in range(0,len(bridge),4)]
   assert stages[1]['a_bytes']==bridge[:128].hex() and stages[2]['a_bytes']==bridge[128:].hex()
   assert trace['output_words']==stages[1]['output_words']+stages[2]['output_words']
   assert all(s['mismatches']==0 and s['checked_words']==len(s['output_words']) for s in stages)
   assert trace['bridge_mismatches']==trace['output_mismatches']==0
   counts[route]['model_hidden_words']+=len(trace['hidden_words'])
   counts[route]['model_bridge_words']+=len(trace['bridge_words'])
   counts[route]['model_output_block_words']+=sum(len(s['output_words']) for s in stages[1:])
   counts[route]['model_output_words']+=len(trace['output_words'])
   counts[route]['event_profile_pairs']+=sum(sum(s['dispatch']['event_profile_queried']) for s in stages)
   if route=='python':
    boundaries.append({'case':case['id'],'iteration':iteration,'poison':f'{trace["poison"]:08x}','row7':trace['output_words'][28:32],'row8':trace['output_words'][32:36]})
for route,values in counts.items():
 for key,value in values.items(): assert value==result['counts'][route][key],(route,key,value)
receipt={'outcome':'pass','scope':'read-only raw count, poison, exact bridge and row-boundary reconciliation; no auditor/producer imports or native execution','counts':counts,'standalone_shapes':[[8,4,8],[8,4,16],[16,8,16]],'model_case_ids':[c['id'] for c in selection['models']],'poisons':[f'{p:08x}' for p in poisons],'row_boundaries':boundaries,'standalone_raw_records_per_route':6,'model_raw_records_per_route':10,'model_stages_per_route':30,'independent_bridge_conversions':2560,'source_revision':result['source_revision']}
Path('/workspace/scratch/ba0248fde989/p05-work/w08_a1/raw-reconciliation.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps({k:v for k,v in receipt.items() if k!='row_boundaries'},indent=2))
