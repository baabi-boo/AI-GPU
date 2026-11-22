from pathlib import Path
from datetime import datetime, timezone
import hashlib,json,re,subprocess

scratch=Path('/workspace/scratch/98908dfa3444')
repo=scratch/'AI-GPU'
packet=repo/'docs/project/evidence/p06-counter-diagnostics'
reviews=packet/'reviews'
reviews.mkdir(exist_ok=True)
meta=scratch/'w08-evidence-retention-intake.json'

def digest(data):
 return hashlib.sha256(data).hexdigest()

def write_json(path,value):
 path.write_text(json.dumps(value,indent=2,sort_keys=False)+'\n')

if meta.exists():
 raise SystemExit('Refusing to overwrite the frozen intake; finalize from the retained snapshot.')

captured=datetime.now(timezone.utc).isoformat(timespec='seconds')
ledger_raw=(scratch/'session-agents.json').read_bytes()
ledger=json.loads(ledger_raw)
tasks=[task for wave in ledger['waves'] for task in wave['tasks']]
if len(tasks)!=len(set(tasks)):
 raise SystemExit('duplicate tasks in ledger')
ledger_path=reviews/'session-agents-wave08.json'
ledger_path.write_bytes(ledger_raw)

existing={}
for d in ('native','host'):
 for path in sorted((packet/d).iterdir()):
  if path.is_file() and path.suffix not in ('.zip',):
   raw=path.read_bytes()
   existing.setdefault((digest(raw),len(raw)),[]).append(path)
for name in ['dependency-source-bodies.json','dependency-source-manifest.json','lifetime-source-manifest.json']:
 path=packet/name
 if path.exists():
  raw=path.read_bytes();existing.setdefault((digest(raw),len(raw)),[]).append(path)

candidates=[p for p in sorted(scratch.iterdir()) if p.is_file() and re.match(r'^w0[1-8]-',p.name) and not p.name.startswith('w08-evidence-retention') and p.suffix in ('.md','.json','.log','.py','.sh','.patch','.stamp','.txt')]
candidates += [scratch/name for name in ('COUNTER_DIAGNOSTIC_TASK.md','build_lifetime_manifests.py','baseline-checked.log') if (scratch/name).is_file()]
files=[]
for src in candidates:
 raw=src.read_bytes(); h=digest(raw); n=len(raw)
 if src.read_bytes()!=raw: raise SystemExit('source changed during capture: '+src.name)
 wave=int(src.name[1:3]) if re.match(r'^w\d\d-',src.name) else None
 category={'.md':'original_note','.json':'original_receipt_or_data','.log':'original_log','.txt':'original_text_record','.py':'original_audit_or_historical_source','.sh':'original_audit_script','.patch':'original_change_snapshot','.stamp':'original_configuration_stamp'}.get(src.suffix,'original_artifact')
 if (h,n) in existing:
  dest=existing[(h,n)][0]
  retention='existing_identical_artifact_reference'
 else:
  dest=reviews/(f'wave{wave:02}' if wave else 'shared')/src.name
  dest.parent.mkdir(exist_ok=True)
  if dest.exists() and dest.read_bytes()!=raw: raise SystemExit('refusing overwrite: '+str(dest))
  dest.write_bytes(raw)
  retention='byte_for_byte_copy'
 if dest.read_bytes()!=raw: raise SystemExit('copy mismatch: '+src.name)
 files.append({'original_scratch_path':str(src),'original_name':src.name,'retained_path':str(dest.relative_to(repo)),'size_bytes':n,'sha256':h,'retention':retention,'wave':wave,'artifact_type':category,'authorship':'not independently attested; task association is documented separately'})

capture={'schema_version':1,'captured_at':captured,'repository_head_at_capture':subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip(),'requested_agent_count':ledger['requested_agents'],'requested_wave_count':ledger['requested_waves'],'recorded_task_count':len(tasks),'completed_wave_task_count':sum(len(w['tasks']) for w in ledger['waves'] if w['state']=='completed'),'in_progress_wave_task_count':sum(len(w['tasks']) for w in ledger['waves'] if w['state']=='in_progress'),'task_completion_source':'copied root-maintained ledger wave states; not independent completion attestation','ledger_snapshot':{'path':str(ledger_path.relative_to(repo)),'size_bytes':len(ledger_raw),'sha256':digest(ledger_raw)},'files':files,'scope':'Current partial wave01-wave08 scratch snapshot; no transcripts reconstructed; no native execution, full test discovery or build performed.','qualified':False,'ready_for_warm':False,'full_warm_coverage':False,'warm_execution':False,'acceptance':False,'unconditional_blocker':'P06-WARM-RV64-MPM-HIGH-HALF'}
write_json(meta,capture)
print(json.dumps({'captured_at':captured,'recorded_tasks':len(tasks),'copied_files':sum(f['retention']=='byte_for_byte_copy' for f in files),'copied_bytes':sum(f['size_bytes'] for f in files if f['retention']=='byte_for_byte_copy'),'existing_identical_references':sum(f['retention']!='byte_for_byte_copy' for f in files),'all_original_files':len(files)},indent=2))
