from pathlib import Path
import json,hashlib,re,datetime
scratch=Path('/workspace/scratch/98908dfa3444');repo=scratch/'AI-GPU';packet=repo/'docs/project/evidence/p06-counter-diagnostics';reviews=packet/'reviews'
m=json.loads((reviews/'retained-files.json').read_text());t=json.loads((reviews/'task-artifact-map.json').read_text());l=json.loads((reviews/'session-agents-wave08.json').read_text())
errors=[];seen=set();source_changes=[]
for f in m['files']:
 p=repo/f['retained_path'];raw=p.read_bytes()
 if len(raw)!=f['size_bytes'] or hashlib.sha256(raw).hexdigest()!=f['sha256']:errors.append('file digest/size mismatch '+f['retained_path'])
 if f['retained_path'] in seen:errors.append('duplicate retained path '+f['retained_path'])
 seen.add(f['retained_path'])
 src=Path(f['original_scratch_path'])
 if src.is_file() and hashlib.sha256(src.read_bytes()).hexdigest()!=f['sha256']:
  source_changes.append({'original_name':f['original_name'],'captured_path':f['retained_path'],'later_version_retained':any(g['original_scratch_path']==f['original_scratch_path'] and g.get('captured_after_frozen_intake') for g in m['files'])})
ld=m['ledger_snapshot'];raw=(repo/ld['path']).read_bytes()
if len(raw)!=ld['size_bytes'] or hashlib.sha256(raw).hexdigest()!=ld['sha256']:errors.append('ledger mismatch')
actual=[n for w in l['waves'] for n in w['tasks']];mapped=[r['task_name'] for r in t['tasks']]
if actual!=mapped or len(mapped)!=len(set(mapped)):errors.append('task coverage mismatch')
for r in t['tasks']:
 for p in r['associated_artifacts']+r['related_artifacts']+r['related_integrated_source_paths']+([r['primary_note']] if r['primary_note'] else []):
  if not (repo/p).is_file():errors.append('task artifact missing '+p)
links=0
for p in [packet/'README.md',reviews/'README.md',reviews/'ARTIFACTS.md']:
 for dest in re.findall(r'\[[^\]]*\]\(([^)]+)\)',p.read_text()):
  if dest.startswith(('https://','http://','#')):continue
  target=(p.parent/dest.split('#')[0]).resolve();links+=1
  if not target.exists():errors.append('link missing '+str(p.relative_to(repo))+' -> '+dest)
 if any(line.rstrip()!=line for line in p.read_text().splitlines()):errors.append('generated document trailing whitespace '+p.name)
patterns={'token':r'(?:ghp_|github_pat_|gho_|ghu_|ghs_)[A-Za-z0-9_]{16,}', 'private_key':r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----', 'authorization':r'(?i)authorization[\"\s:]+(?:bearer|token|basic)\s+[A-Za-z0-9+/=_-]{12,}', 'signed_url':r'(?i)(?:[?&](?:sig|X-Amz-Signature|X-Goog-Signature)=)[^&\s\"\']{12,}'}
secret_hits=[]
for f in m['files']:
 txt=(repo/f['retained_path']).read_text(errors='replace')
 for label,pat in patterns.items():
  if re.search(pat,txt):secret_hits.append({'file':f['retained_path'],'category':label})
if secret_hits:errors.append('sensitive pattern candidates')
all_paths=[p for p in reviews.rglob('*') if p.is_file()]
expected_copies={f['retained_path'] for f in m['files'] if f['retention']=='byte_for_byte_copy'}
expected_paths=expected_copies|{ld['path']}|{str((reviews/name).relative_to(repo)) for name in ['README.md','ARTIFACTS.md','task-artifact-map.json','retained-files.json']}
if expected_paths!={str(p.relative_to(repo)) for p in all_paths}:errors.append('retained directory membership mismatch')
result={'checked_at':datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),'outcome':'pass' if not errors else 'fail','captured_task_count':len(actual),'retained_original_records':len(m['files']),'copied_original_files':m['file_counts']['byte_for_byte_copied_originals'],'copied_original_bytes':m['file_counts']['byte_for_byte_copied_original_bytes'],'existing_identical_references':m['file_counts']['existing_identical_references'],'ledger_snapshots':1,'generated_catalogs':4,'review_directory_files':len(all_paths),'review_directory_bytes':sum(p.stat().st_size for p in all_paths),'local_links_checked':links,'retained_standalone_notes':sum(r['standalone_note_status']=='retained' for r in t['tasks']),'missing_standalone_task_notes':[r['task_name'] for r in t['tasks'] if r['standalone_note_status']!='retained'],'historical_source_changes_preserved_as_separate_versions':source_changes,'secret_pattern_candidates':secret_hits,'errors':errors,'native_execution':'not_run','full_test_discovery':'not_run','qualified':False,'ready_for_warm':False,'warm_execution':False,'acceptance':False}
(scratch/'w08-evidence-retention-validation.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
raise SystemExit(bool(errors))
