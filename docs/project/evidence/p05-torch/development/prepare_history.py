from pathlib import Path
import hashlib, json, subprocess
work=Path(__file__).resolve().parent
root=work.parent/'AI-GPU'
base='bdd3485243f820947df94f7962641d10f2169834'
original='docs/project/evidence/p05-python/acceptance-binding.json'
raw=subprocess.check_output(['git','show',base+':'+original],cwd=root)
record=json.loads(raw)
changed={'python/vortex_ai/_bundle.py','MANIFEST.in','ci/project/test_p05_packaging.py','ci/project/test_p05_bundle.py'}
rows=[]
for artifact in record['artifacts']:
 if artifact['path'] not in changed: continue
 old=artifact['path'];body=subprocess.check_output(['git','show',base+':'+old],cwd=root)
 assert hashlib.sha256(body).hexdigest()==artifact['sha256'],old
 target='docs/project/evidence/p05-torch/history/p05-a01/'+old+'.txt'
 path=work/'drafts/history'/target
 path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(body)
 artifact['path']=target
 rows.append({'original_path':old,'retained_path':target,'sha256':artifact['sha256'],'bytes':len(body)})
record['record_id']='p05-a01-copying-binding-retained-source-v1'
record['scope']+=' Historical source retention: four mutable artifact paths resolve to exact original bytes; this publication establishes no new native execution or acceptance scope.'
record['reviewer']='pending'
record['artifacts'].append({'path':original,'sha256':hashlib.sha256(raw).hexdigest()})
record['limitations'].append('The original acceptance record remains byte-for-byte unchanged. Four source artifact locations are preserved because the later optional framework adapter updates those live paths; original artifact hashes, tested revision, commands, limitations and original reviews are unchanged.')
p=work/'drafts/a01-retained-binding.json';p.write_text(json.dumps(record,indent=2)+'\n')
mapping={'schema_version':1,'scope':'historical-source-retention-only','source_revision':record['source_revision'],'publication_base':base,'original_record':{'path':original,'sha256':hashlib.sha256(raw).hexdigest()},'mappings':rows,'execution_claimed':False,'acceptance_scope_changed':False}
(work/'drafts/a01-source-retention.json').write_text(json.dumps(mapping,indent=2)+'\n')
print(json.dumps(mapping,indent=2))
