"""Independent raw BF16 reconciliation; imports no producer or auditor code."""
from fractions import Fraction
import hashlib, json, struct
from pathlib import Path
repo=Path('/workspace/scratch/ba0248fde989/AI-GPU');work=repo.parent/'p05-work/w08_a4'
p=repo.parent/'p05-work/ci-e1420fd/simx-bf16/python'
poisons=(0x7fc0dead,0xdeadbeef)
standalone_ids=['bf16-single-dense_boundaries','bf16-numerical-cross_tile_rounding_positive','bf16-multi-dense_boundaries']
families=['seeded_dense','negated_dense','zero','signed_basis','split_boundary']
model_ids=['bf16-'+name for name in families]
model_fixture=json.loads((repo/'ci/project/fixtures/p04_tiny_mlp_v1.json').read_text())
cases={c['id']:c for c in model_fixture['cases'] if c['format']=='bf16'}
weights=model_fixture['weights']['formats']['bf16']
standalone={c['id']:c for name in ['p02_layout_v1.json','p02_wmma_numerical_v1.json'] for c in json.loads((repo/'ci/project/fixtures'/name).read_text())['cases']}
def raw(path,marker):return [json.loads(line[len(marker)+1:]) for line in path.read_text().splitlines() if line.startswith(marker+' ')]
def packed(words):return b''.join(int(x,16).to_bytes(4,'little') for x in words)
def unpack32(body):return [f'{int.from_bytes(body[i:i+4],"little"):08x}' for i in range(0,len(body),4)]
def binary_value(bits,mantissa_bits):
 exp=(bits>>mantissa_bits)&255;fraction=bits&((1<<mantissa_bits)-1);sign=-1 if bits>>(mantissa_bits+8) else 1
 assert exp!=255
 n=fraction if exp==0 else (1<<mantissa_bits)+fraction
 power=(-126 if exp==0 else exp-127)-mantissa_bits
 return Fraction(sign*n*(1<<power)) if power>=0 else Fraction(sign*n,1<<(-power))
def bf16_values(body):return [binary_value(int.from_bytes(body[i:i+2],'little'),7) for i in range(0,len(body),2)]
def exact32(value):
 word=int.from_bytes(struct.pack('>f',float(value)),'big')
 assert binary_value(word,23)==value
 return f'{word:08x}'
def matrix(a,b,m,n,k):
 av,bv=bf16_values(a),bf16_values(b)
 assert len(av)==m*k and len(bv)==n*k
 return [exact32(sum((av[row*k+t]*bv[col*k+t] for t in range(k)),Fraction())) for row in range(m) for col in range(n)]
def relu_bf16(word):
 bits=int(word,16);value=binary_value(bits,23)
 if value<=0:return b'\0\0'
 # IEEE BF16 nearest-even rounding, independently expressed from the FP32
 # representation. Every positive frozen hidden value is exactly representable.
 half=(bits+0x7fff+((bits>>16)&1))>>16
 assert binary_value(half,7)==value
 return half.to_bytes(2,'little')
installed=p/'logs/installed-matrix.log'
py_mm=raw(installed,'P05_MATMUL');py_models=raw(installed,'P05_MODEL')
obs=json.loads((p/'artifacts/installed-observations.json').read_text())
assert py_mm==obs['matmuls'] and py_models==obs['models']
assert [x['case_id'] for x in py_mm]==[name for name in standalone_ids for _ in poisons]
assert [x['case_id'] for x in py_models]==[name for name in model_ids for _ in poisons]
counts={r:dict(matmul_runs=0,matmul_words=0,model_runs=0,model_stage_words=0,hidden_values=0,bridge_bytes=0,bridge_packed_words=0,assembled_words=0,launches=0,profile_pairs=0) for r in ['python','native']}
boundaries=[]
for i,name in enumerate(standalone_ids):
 native=raw(p/'logs'/('native-'+name+'.log'),'P03_RESULT');assert len(native)==2
 f=standalone[name];shape=f['dimensions'];assert (shape['m'],shape['n'],shape['k'])==[(8,4,8),(8,4,16),(16,8,16)][i]
 for iteration in range(2):
  py=py_mm[i*2+iteration];nat=native[iteration]
  assert py['iteration']==nat['iteration']==iteration and nat['case_id']==name
  assert py['actual_bits']==nat['actual_bits']==f['expected']
  assert py['trace']['poison']==nat['dispatch']['poison']==poisons[iteration]
  assert not any('profile' in key for key in nat['dispatch'])
  for route,row in [('python',py),('native',nat)]:
   c=counts[route];c['matmul_runs']+=1;c['matmul_words']+=len(row['actual_bits']);c['launches']+=1
   if route=='python':assert len(row['trace']['event_profiles'])==5;c['profile_pairs']+=5
for index,name in enumerate(model_ids):
 native=raw(p/'native/logs'/('simx-bf16-'+name+'.log'),'P04_RESULT');assert len(native)==2
 frozen=cases[name]
 for iteration in range(2):
  python=py_models[index*2+iteration];assert python['iteration']==iteration
  py=python['record'];nat=native[iteration]
  for route,record in [('python',py),('native',nat)]:
   t=record['trace'];stages=t['native'];assert t['case_id']==name and record['iteration']==iteration
   assert t['input_dtype']=='bf16' and t['poison']==poisons[iteration]
   assert [(s['operation_id'],s['row_begin'],s['row_end']) for s in stages]==[('hidden_matmul',0,16),('output_rows_0_7',0,8),('output_rows_8_15',8,16)]
   assert bytes.fromhex(stages[0]['a_bytes'])==packed(frozen['input_words'])
   assert bytes.fromhex(stages[0]['b_bytes'])==packed(weights['w1_words'])
   expected_hidden=matrix(bytes.fromhex(stages[0]['a_bytes']),bytes.fromhex(stages[0]['b_bytes']),16,8,16)
   assert expected_hidden==stages[0]['output_words']==t['hidden_words']==frozen['hidden_words']
   bridge=b''.join(relu_bf16(word) for word in expected_hidden)
   assert len(bridge)==256 and bridge.hex()==t['bridge_bytes']
   assert unpack32(bridge)==t['bridge_words']==frozen['bridge_words']
   assert bytes.fromhex(stages[1]['a_bytes'])==bridge[:128]
   assert bytes.fromhex(stages[2]['a_bytes'])==bridge[128:]
   expected_outputs=[]
   for stage in stages[1:]:
    assert bytes.fromhex(stage['b_bytes'])==packed(weights['w2_words'])
    stage_output=matrix(bytes.fromhex(stage['a_bytes']),bytes.fromhex(stage['b_bytes']),8,4,8)
    assert stage_output==stage['output_words'];expected_outputs.extend(stage_output)
   assert expected_outputs==t['output_words']==frozen['output_words']
   assert t['output_words'][28:32]==stages[1]['output_words'][-4:]
   assert t['output_words'][32:36]==stages[2]['output_words'][:4]
   assert all(s['dispatch']['poison']==poisons[iteration] and len(s['dispatch']['event_profiles'])==5 for s in stages)
   c=counts[route];c['model_runs']+=1;c['model_stage_words']+=sum(len(s['output_words']) for s in stages);c['hidden_values']+=len(expected_hidden);c['bridge_bytes']+=len(bridge);c['bridge_packed_words']+=len(t['bridge_words']);c['assembled_words']+=len(t['output_words']);c['launches']+=3;c['profile_pairs']+=15
   boundaries.append({'route':route,'case_id':name,'iteration':iteration,'row7':t['output_words'][28:32],'row8':t['output_words'][32:36],'bridge_row7_hex':bridge[112:128].hex(),'bridge_row8_hex':bridge[128:144].hex()})
  for key in ['hidden_words','bridge_bytes','bridge_words','output_words']:assert py['trace'][key]==nat['trace'][key]
  for a,b in zip(py['trace']['native'],nat['trace']['native']):
   for key in ['a_bytes','b_bytes','output_words']:assert a[key]==b[key]
assert sum(c['launches'] for c in counts.values())==72
assert counts['python']['profile_pairs']==180 and counts['native']['profile_pairs']==150
execution=json.loads((work/'execution.json').read_text())
after={str(f.relative_to(p)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(p.rglob('*')) if f.is_file()}
assert after==execution['before']['packet']
result={'outcome':'pass','scope':'independent raw BF16 retained-data reconciliation; no native execution or producer/auditor imports','source_revision':execution['before']['git'][0],'matmul_case_ids':standalone_ids,'model_case_ids':model_ids,'poisons':[f'{v:08x}' for v in poisons],'counts':counts,'combined_launches':72,'combined_profile_pairs':330,'model_arithmetic':'Exact Fraction BF16 input decoding and matrix products; FP32 values checked for exact representability; independent nearest-even BF16 packing after ReLU','standalone_scope':'Raw native/Python words compared with immutable P02 fixtures, including the cross-tile rounding case; no replacement standalone arithmetic oracle claimed','boundaries':boundaries,'inputs_unchanged':True,'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
(work/'raw-reconciliation.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:result[k] for k in ['outcome','counts','combined_launches','combined_profile_pairs']},indent=2))
