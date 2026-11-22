from pathlib import Path
from datetime import datetime,timezone
import json,hashlib,re,os

scratch=Path('/workspace/scratch/98908dfa3444');repo=scratch/'AI-GPU';packet=repo/'docs/project/evidence/p06-counter-diagnostics';reviews=packet/'reviews'
cap=json.loads((scratch/'w08-evidence-retention-intake.json').read_text())
ledger=json.loads((repo/cap['ledger_snapshot']['path']).read_text())
files=cap['files'][:]
raw=(scratch/'w08-evidence-retention.md').read_bytes();dest=reviews/'wave08/w08-evidence-retention.md';dest.write_bytes(raw)
files.append({'original_scratch_path':str(scratch/'w08-evidence-retention.md'),'original_name':'w08-evidence-retention.md','retained_path':str(dest.relative_to(repo)),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'retention':'byte_for_byte_copy','wave':8,'artifact_type':'original_note','authorship':'w08_evidence_retention author handoff','captured_after_frozen_intake':True})
# Preserve the original snapshot and the author's subsequent correction as separate versions.
public_src=scratch/'w08-public-design.md'; public_raw=public_src.read_bytes(); public_dest=reviews/'wave08/w08-public-design-after-snapshot.md';public_dest.write_bytes(public_raw)
files.append({'original_scratch_path':str(public_src),'original_name':'w08-public-design.md','retained_path':str(public_dest.relative_to(repo)),'size_bytes':len(public_raw),'sha256':hashlib.sha256(public_raw).hexdigest(),'retention':'byte_for_byte_copy','wave':8,'artifact_type':'original_note','authorship':'original author correction observed after frozen intake; no text rewritten by retention','captured_after_frozen_intake':True,'version_note':'Corrected gate-name preservation claim and document hashes; captured predecessor remains intact.'})
by_name={f['original_name']:f for f in files}

def js(path,val):path.write_text(json.dumps(val,indent=2)+'\n')
def rel(path,base=reviews):return os.path.relpath(repo/path,base)
def link(path,label=None,base=reviews):return f'[{label or Path(path).name}]({rel(path,base)})'

primary={
'w01_lifetime':'w01-lifetime.md','w01_selectors':'w01-selectors.md','w01_public':'w01-public.md','w01_build':'w01-build.md','w01_reader':'w01-reader.md','w01_dependency':'w01-dependency.md',
'w02_access':'w02-access.md','w02_harness':None,'w02_runner':None,'w02_harness_review':'w02-harness-review.md','w02_access_review':'w02-access-review.md','w02_runner_review':'w02-runner-review.md',
'w03_public_hooks':'w03-public-hooks.md','w03_public_main':'w03-public-main.md','w03_public_build':'w03-public-build.md','w03_public_runner':'w03-public-runner.md','w03_public_build_records':'w03-public-build-records.md','w03_public_records':'w03-public-records.md',
'w04_hooks_review':'w04-hooks-review.md','w04_main_review':'w04-main-review.md','w04_build_ci_review':'w04-build-ci-review.md','w04_runner_review':'w04-runner-review.md','w04_build_records_review':'w04-build-records-review.md','w04_records_review':'w04-records-review.md',
'w05_lifetime_proof':None,'w05_native_all33_audit':'w05-native-all33-review.md','w05_checked_replay':'w05-checked-replay-api.md','w05_public_replay':None,'w05_checked_replay_tests':'w05-checked-replay-tests.md','w05_public_replay_tests':'w05-public-replay-tests-handoff.md',
'w06_cp_drain_fix':'w06-cp-drain-fix.md','w06_checked_log_fix':'w06-checked-log-fix.md','w06_cp_drain_review':'w06-cp-drain-review.md','w06_lifetime_review':'w06-lifetime-review.md','w06_governance_fixture_fix':'w06-governance-fixture-fix.md','w06_checked_replay_review':'w06-checked-replay-review.md',
'w07_public_replay_review':'w07-public-replay-review.md','w07_source_inventory':'w07-source-inventory.md','w07_source_inventory_tests':'w07-source-inventory-tests.md','w07_replay_inventory_integration':'w07-replay-inventory-integration.md','w07_public_replay_integration_tests':'w07-public-replay-integration-tests.md','w07_native_public_audit':'w07-native-public-audit.md',
'w08_source_inventory_review':'w08-source-inventory-review.md','w08_replay_integration_review':'w08-replay-integration-review.md','w08_public_design':'w08-public-design.md','w08_evidence_retention':'w08-evidence-retention.md','w08_qualification_plan':None}
prefixes={task:[task.replace('_','-')] for w in ledger['waves'] for task in w['tasks']}
prefixes.update({
'w01_dependency':['w01-dependency','w01-ramulator'],
'w03_public_build':['w03-public-build','w03-public-backend_config','w03-public-main_config','w03-public-runtime_config','w03-public-first-build','w03-public-second-build','w03-public-ci-tests'],
'w03_public_build_records':['w03-public-build-record'],
'w04_build_ci_review':['w04-build-ci'],
'w06_governance_fixture_fix':['w06-governance-fixture'],
'w05_native_all33_audit':['w05-native-all33'],
'w07_native_public_audit':['w07-native-','w07-corrected-','w07-failed-'],
'w07_replay_inventory_integration':['w07-replay-inventory','w07-public-replay-test-delta-review'],
'w07_public_replay_integration_tests':['w07-public-replay-integration','w07-public-replay-genuine','w07-public-replay-focused','w07-public-replay-raw'],
'w08_replay_integration_review':['w08-replay-integration']})

# Filename associations are indexes, not claims of author identity.
for f in files:
 matches=[(len(p),t) for t,ps in prefixes.items() for p in ps if f['original_name'].startswith(p)]
 if matches:
  maxlen=max(n for n,t in matches);assigned=sorted(set(t for n,t in matches if n==maxlen))
 else:assigned=[]
 f['associated_tasks']=assigned
 f['association_basis']='task-named filename or explicit documented prefix' if assigned else 'shared or unattributed context; no task authorship inferred'

related={
'w02_harness':['w02-harness-review.md'],
'w02_runner':['w02-runner-review.md','w02-runner-review-tests.log'],
'w05_lifetime_proof':['w06-lifetime-review.md','w06-lifetime-review-receipt.json'],
'w05_public_replay':['w05-public-replay-tests-handoff.md','w05-public-replay-tests-final.log','w07-public-replay-review.md'],
'w04_main_review':['w04-dma-records-tests.log','w04-dma-syntax.log','w04-helper-drift-control.log','w04-records-review.md'],
'w03_public_runner':['w03-public-interfaces.md'],
'w03_public_build_records':['w03-public-interfaces.md'],
'w03_public_records':['w03-public-interfaces.md'],
'w07_public_replay_review':['w07-public-replay-test-delta-review.md','w07-public-replay-integration-tests.md'],
'w08_public_design':['w08-lifetime-before.md']}
source_related={
'w02_harness':['tests/unittest/checked_counters/main.cpp'],
'w02_runner':['ci/project/p06_checked_execute.py'],
'w05_lifetime_proof':['docs/designs/simx_counter_lifetime_v1.md','docs/project/evidence/p06-counter-diagnostics/lifetime-source-manifest.json','docs/project/evidence/p06-counter-diagnostics/dependency-source-manifest.json','docs/project/evidence/p06-counter-diagnostics/dependency-source-bodies.json'],
'w05_public_replay':['ci/project/p06_counter_public_replay.py']}
gap_notes={
'w02_harness':'No standalone author note was established; related reviewer evidence and integrated source are not substituted author testimony.',
'w02_runner':'No standalone author note was established; related reviewer evidence and integrated source are not substituted author testimony.',
'w05_lifetime_proof':'Original author validation receipt exists, but no standalone author handoff was established. Independent reviewer evidence is separate.',
'w05_public_replay':'No standalone author note was established; independently authored tests and later reader review are separate evidence.',
'w08_qualification_plan':'Task was newly recorded and active at the frozen intake; no task artifact was then present. Later retention must append its actual output.'}
rows=[]
for w in ledger['waves']:
 for task in w['tasks']:
  own=[f for f in files if task in f['associated_tasks']]
  pn=primary.get(task);pf=by_name.get(pn) if pn else None
  scope='source review or host-side validation; exact executed checks and omissions remain in originals'
  if 'replay' in task:scope='inert retained-data replay and/or controlled synthetic host tests; no native execution by retention/reviewer inferred'
  if task in ('w05_native_all33_audit','w07_native_public_audit'):scope='independent inspection of retained original hosted native artifacts; auditor did not execute a new native test'
  if task in ('w05_lifetime_proof','w06_lifetime_review'):scope='source-bound conditional lifetime argument or review; not execution qualification'
  if task=='w08_evidence_retention':scope='retention-integrity and index checks only; author handoff added after frozen intake'
  if task=='w08_qualification_plan':scope='active task with no artifact at capture'
  rows.append({'task_name':task,'wave':w['wave'],'ledger_wave_state':w['state'],'standalone_note_status':'retained' if pf else 'missing_at_snapshot','primary_note':pf['retained_path'] if pf else None,'associated_artifacts':[f['retained_path'] for f in own],'related_artifacts':[by_name[n]['retained_path'] for n in related.get(task,[]) if n in by_name],'related_integrated_source_paths':source_related.get(task,[]),'association_scope':scope,'limitation':gap_notes.get(task,'Original notes are contemporaneous scoped evidence, not a transcript or independent completion/approval attestation.')})

mapping={'schema_version':1,'captured_at':cap['captured_at'],'ledger_snapshot':cap['ledger_snapshot'],'requested_agent_count':cap['requested_agent_count'],'recorded_task_count':len(rows),'completed_wave_task_count':cap['completed_wave_task_count'],'in_progress_wave_task_count':cap['in_progress_wave_task_count'],'mapping_semantics':'Exact actual task names from frozen ledger. Filename association and related reviews do not independently prove authorship or individual completion. No reconstructed transcripts.','tasks':rows,'unattributed_artifacts':[f['retained_path'] for f in files if not f['associated_tasks']],'limitations':['Partial 47-task snapshot; requested 60/10-wave continuation is unfinished here.','w08_evidence_retention author handoff and later w08_public_design author correction are explicitly labeled post-intake supplements.','Source task brief, baseline log and observed generator have unverified authorship/source binding as noted in README.','Original note claims are preserved at their original time, including failures, skipped tests and later-corrected prose.'],'qualified':False,'ready_for_warm':False,'warm_execution':False,'acceptance':False}
js(reviews/'task-artifact-map.json',mapping)
manifest={k:v for k,v in cap.items() if k!='files'}
manifest['files']=files
manifest['file_counts']={'preexisting_scratch_originals':len(cap['files']),'post_intake_author_handoffs':2,'byte_for_byte_copied_originals':sum(f['retention']=='byte_for_byte_copy' for f in files),'byte_for_byte_copied_original_bytes':sum(f['size_bytes'] for f in files if f['retention']=='byte_for_byte_copy'),'existing_identical_references':sum(f['retention']!='byte_for_byte_copy' for f in files),'ledger_snapshot_count':1,'generated_catalog_files_excluded_from_original_counts':['README.md','ARTIFACTS.md','task-artifact-map.json','retained-files.json']}
manifest['integrity_semantics']='SHA-256 and bytes describe retained original contents. Original scratch paths are inert provenance strings, not paths an auditor must execute or trust. The inventory does not hash itself or generated catalogs; the ledger is separately hashed above.'
js(reviews/'retained-files.json',manifest)

readme=f'''# Counter diagnostics retained reviews

This is an auditable **partial snapshot of {len(rows)} actual task names**, captured at `{cap['captured_at']}`. The root-maintained original ledger marks 42 tasks in waves 1–7 under completed wave states and five tasks in wave 8 under an in-progress wave state. The request was for 60 agents across ten waves; this snapshot does not assert that work is complete. The repository HEAD at capture was `{cap['repository_head_at_capture']}`. Each original report retains its own tested/reviewed source identity.

## Browse and verify

- [Original ledger snapshot](session-agents-wave08.json): unchanged bytes from `session-agents.json` at capture.
- [Task-to-artifact map](task-artifact-map.json): every actual captured task name, direct task-named artifacts, related reviews, integrated source pointers and explicit gaps.
- [Readable artifact inventory](ARTIFACTS.md): links, exact byte lengths and SHA-256 digests.
- [Machine-readable retained-file manifest](retained-files.json): original scratch paths, normalized repository locations, copy/reference disposition and integrity metadata.
- [Retention author handoff](wave08/w08-evidence-retention.md): exact scope and work reserved for the continuation.
- [Packet evidence overview](../README.md): native, replay, synthetic/host and governance outcomes.

The frozen intake contains 176 pre-existing scratch originals: 172 copied files totaling 9,046,841 bytes, plus four byte-identical references to evidence already retained elsewhere in this packet. The ledger, retention author's handoff and public-design author's subsequent correction are additional records. Final counts are in `retained-files.json`. Original native ZIPs, build trees, extracted archives, tools and large objects are not duplicated here.

## Actual task mapping

A retained note is original text, not a reconstructed conversation transcript. A related reviewer note is not substituted for a missing author note. File-prefix associations are navigational evidence and do not independently establish authorship. All task and wave names below come from the retained ledger.

| Actual task | Original standalone note | Task-named artifacts | Scope or explicit gap |
|---|---|---:|---|
'''
for r in rows:
 note=link(r['primary_note']) if r['primary_note'] else '**Missing at snapshot**'
 desc=gap_notes.get(r['task_name'],'Original scoped report; see map for related evidence.')
 if r['task_name']=='w08_evidence_retention':desc='Author handoff added after frozen intake; no native or replay test claimed.'
 readme+=f"| `{r['task_name']}` | {note} | {len(r['associated_artifacts'])} | {desc} |\n"
readme+='''
## Retained historical errors, failures and limitations

The original `w04-build-records-review.md` contains a prose typo reversing the runtime/stub and backend/hook library names. It remains unchanged. The correct mapping is:

| Artifact | Actual contents |
|---|---|
| `libchecked-simx.so` | 44 reused model/access objects |
| `libvortex.so` | 14 runtime/stub objects |
| `libvortex-simx.so` | Three backend/hook objects; the five Processor wrappers are applied at this backend link |
| `checked_public_test` | `main.o`, linked with its declared libraries |

See the [original erroneous note](wave04/w04-build-records-review.md), the [independent native/public artifact audit](wave07/w07-native-public-audit.md), and the [public diagnostic contract](../../../../designs/simx_counter_public_diagnostics_v1.md). This index corrects the prose while preserving the source note's bytes.

The early checked-replay negative test and its contradictory-log follow-ups remain in [the wave-5 note](wave05/w05-checked-replay-tests.md) and [wave-6 repair evidence](wave06/w06-checked-log-fix.md). The public replay's earlier 29 success-dependent methods were genuinely not run, as retained in [its early handoff](wave05/w05-public-replay-tests-handoff.md). The later [stale schema mutation finding](wave07/w07-public-replay-review.md), [pre-intake partial handoff](wave07/w07-public-replay-integration-tests-before-genuine-intake.md), [test-delta review](wave07/w07-public-replay-test-delta-review.md), and [complete genuine-original replay handoff](wave07/w07-public-replay-integration-tests.md) remain distinct.

The W08 reviewer initially wrote an incorrect expected count of 36 reused model objects; the original packet's count is 44. The [initial failure log](wave08/w08-replay-integration-review-initial.log), [initial receipt](wave08/w08-replay-integration-review-initial.json), and [final corrected review](wave08/w08-replay-integration-review.md) are all retained. A later pass never deletes a failed attempt.

Original notes retain contemporaneous pending claims, command paths and spelling. Their scratch paths are historical provenance, not portable paths to execute. Use this index for the normalized retained locations. Exact configuration, tested source and omission statements remain in the original notes; retention does not upgrade them to qualification or human approval.

## Shared artifacts and continuation gaps

The [observed generator](shared/build_lifetime_manifests.py) has **unverified authorship** and was not executed during retention. The [task brief](shared/COUNTER_DIAGNOSTIC_TASK.md) is planning context. The [baseline 64-test log](shared/baseline-checked.log) has no standalone source/command binding and is not an immutable-governance claim. The [earlier lifetime text](wave08/w08-lifetime-before.md) is a historical comparison snapshot, not the current design contract. Other unattributed scratch receipts remain listed explicitly in the machine-readable map.

Five captured tasks lack standalone notes: `w02_harness`, `w02_runner`, `w05_lifetime_proof`, `w05_public_replay`, and the then-active `w08_qualification_plan`. The lifetime author has a real validation JSON; the others have only the exact related artifacts described in the table/map, or no artifact yet. No missing transcript or test result has been fabricated.

The [captured public-design note](wave08/w08-public-design.md) and [subsequent author correction](wave08/w08-public-design-after-snapshot.md) are both retained. The correction updates document hashes and explains the permitted gate-name typo fix; it does not rewrite original test receipts.

The continuation must append actual remaining task artifacts and a new final ledger snapshot, preserving this partial snapshot. It must bind any later reader/governance results to their actual source revision and keep the already-retained failed native/host attempts. All diagnostic qualification, readiness, warm execution and acceptance flags remain false, and `P06-WARM-RV64-MPM-HIGH-HALF` remains unconditional.
'''
(reviews/'README.md').write_text(readme)

art=f'''# Retained original artifact inventory

Snapshot: `{cap['captured_at']}`. SHA-256 and byte counts below describe original contents. Existing byte-identical packet files are linked once rather than copied again. The retention author's handoff and later public-design author correction are labeled post-intake supplements. Generated navigation/catalog files are not presented as original test evidence.

Ledger snapshot: {link(cap['ledger_snapshot']['path'])}; {cap['ledger_snapshot']['size_bytes']} bytes; SHA-256 `{cap['ledger_snapshot']['sha256']}`.

| Original scratch file | Retained artifact | Bytes | SHA-256 | Retention |
|---|---|---:|---|---|
'''
for f in files:
 kind='copy' if f['retention']=='byte_for_byte_copy' else 'existing identical reference'
 if f.get('captured_after_frozen_intake'):kind+='; post-intake handoff'
 art+=f"| `{f['original_name']}` | {link(f['retained_path'])} | {f['size_bytes']} | `{f['sha256']}` | {kind} |\n"
(reviews/'ARTIFACTS.md').write_text(art)
print(json.dumps(manifest['file_counts'],indent=2))
