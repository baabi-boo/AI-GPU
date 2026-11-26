#!/usr/bin/env python3
"""Read-only protected-input audit; write results only outside the repository."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess
from datetime import datetime, timezone

ROOT = Path('/tmp/ai-gpu-2bfab0261c05/repo')
OUT = ROOT.parent / 'validation'
BASE = '858090410a992756808256ace90d36b9b3b88dd3'
EXPECTED_HEAD = 'd31e8879e7c248b1a72615128882533ccdd0b3b4'

def git(*args, binary=False):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=not binary)

def sha(body):
    return hashlib.sha256(body).hexdigest()

def load(path):
    return json.loads((ROOT / path).read_bytes())

def base_bytes(path):
    return git('show', BASE + ':' + path, binary=True)

def literals(path):
    values = {}
    for node in ast.parse((ROOT / path).read_text()).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                values[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                pass
    return values

def diff_paths(paths):
    value = git('diff', '--name-status', BASE, '--', *paths).splitlines()
    return {'paths': paths, 'changes': value, 'unchanged': not value}

def inventory(prefix):
    rows=[]
    for name in sorted(git('ls-files', '--', prefix).splitlines()):
        path=ROOT/name
        if path.is_file():
            raw=path.read_bytes()
            rows.append({'path':name,'size_bytes':len(raw),'sha256':sha(raw)})
    return rows

started = datetime.now(timezone.utc).isoformat()
head_before=git('rev-parse','HEAD').strip()
status_before=git('status','--short').splitlines()
qualified=load('ci/project/p06_qualified_warm_proof.json')
counter=load('ci/project/p06_counter_qualification_proof.json')
measurement=[]
for row in qualified['measurement_sources']:
    raw=(ROOT/row['path']).read_bytes()
    measurement.append({'path':row['path'],'size_bytes':len(raw),'sha256':sha(raw),
                        'expected_size_bytes':row['size_bytes'],'expected_sha256':row['sha256'],
                        'matches':len(raw)==row['size_bytes'] and sha(raw)==row['sha256']})
measurement_ok=len(measurement)==69 and len({r['path'] for r in measurement})==69 and all(r['matches'] for r in measurement)
proofs=[]
for name in ('p06_qualified_warm_contract.py','p06_counter_qualification_contract.py'):
    contract='ci/project/'+name
    c=literals(contract)
    raw=(ROOT/c['SOURCE_PROOF_PATH']).read_bytes()
    value=json.loads(raw)
    canonical=json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()
    checks={'size_matches':len(raw)==c['SOURCE_PROOF_BYTES'],'sha256_matches':sha(raw)==c['SOURCE_PROOF_SHA256'],
            'canonical_sha256_matches':sha(canonical)==c['SOURCE_PROOF_DOCUMENT_SHA256'],
            'byte_identical_to_base':raw==base_bytes(c['SOURCE_PROOF_PATH']),
            'all_claims_false':all(v is False for v in value['claims'].values())}
    proofs.append({'path':c['SOURCE_PROOF_PATH'],'contract':contract,'size_bytes':len(raw),'sha256':sha(raw),
                   'canonical_sha256':sha(canonical),'claims':value['claims'],'checks':checks,'passes':all(checks.values())})
base_counter=json.loads(base_bytes('ci/project/p06_counter_qualification_proof.json'))
deps=[]
base_deps={r['path']:r for r in base_counter['dependency_sources']}
for row in counter['dependency_sources']:
    path=ROOT/'third_party/ramulator'/row['path']
    deps.append({**row,'descriptor_equals_base':row==base_deps.get(row['path']),'local_source_present':path.is_file()})
pin=literals('ci/project/p06_dependency_contract.py')['PINS']['ramulator']
gitlink_base=git('ls-tree',BASE,'third_party/ramulator').strip()
gitlink_head=git('ls-tree','HEAD','third_party/ramulator').strip()
deps_ok=(len(deps)==len(base_deps)==21 and len({r['path'] for r in deps})==21
         and all(r['descriptor_equals_base'] for r in deps)
         and gitlink_base==gitlink_head and pin['revision']==counter['dependency_revision']
         and pin['revision'] in gitlink_head)
resource_paths=['ci/project/p06_warm_contract.json','ci/project/p06_warm_contract.py',
 'ci/project/p06_benchmark_contract.json','ci/project/p06_contract.py','ci/project/p06_workspace_contract.json',
 'ci/project/p06_warm_analysis.py','ci/project/p06_dependency_contract.py','ci/project/p06_managed_preflight_contract.py',
 'ci/project/p06_qualified_warm_capacity.py','ci/project/p06_qualified_warm_analyze.py',
 'ci/project/p06_qualified_warm_hosted.py','ci/project/p06_qualified_warm_run.py',
 '.github/workflows/p06-qualified-warm.yml','docs/project/developer-guide.md',
 'ci/asic_gate.py','ci/fpga_gate.py','ci/logic_gate.py','ci/synth_gate.py','ci/perf_baseline.py']
resource_paths=[p for p in resource_paths if (ROOT/p).is_file()]
groups={
 'measurement_sources':diff_paths([r['path'] for r in measurement]),
 'golden_baselines':diff_paths(['ci/baselines']),
 'numerical_fixtures':diff_paths(['ci/project/fixtures']),
 'resource_performance_contracts_and_enforcement':diff_paths(resource_paths),
 'proofs_dependency_contract_and_gitlink':diff_paths(['ci/project/p06_qualified_warm_proof.json','ci/project/p06_counter_qualification_proof.json','ci/project/p06_qualified_warm_contract.py','ci/project/p06_counter_qualification_contract.py','ci/project/p06_dependency_contract.py','.gitmodules','third_party/ramulator']),
 'phase_documents_acceptance_policy_and_decisions':diff_paths(['ROADMAP.md','docs/project/acceptance.md','docs/project/phases','docs/project/evidence/p01-xrt-blocked.json','docs/project/evidence/p06-baseline/acceptance.json','docs/project/evidence/p06-serial-workspace/p06-a01-retained-baseline.json'])}
roadmap=load('docs/project/roadmap.json');base_roadmap=json.loads(base_bytes('docs/project/roadmap.json'))
expected_refs={
 ('P02','P02-A02'):('docs/project/evidence/p02-wmma/acceptance.json','docs/project/evidence/p02-wmma/acceptance-retained-source.json'),
 ('P05','P05-A01'):('docs/project/evidence/governance-readiness/a01-retained-binding.json','docs/project/evidence/p06-checkpoint-publication/launcher/a01-retained-binding.json')}
normalized=json.loads(json.dumps(roadmap));ref_changes=[]
for phase in normalized['phases']:
    for e in phase['evidence']:
        key=(phase['id'],e['acceptance_id'])
        if key in expected_refs:
            before,after=expected_refs[key]
            ref_changes.append({'phase':key[0],'acceptance_id':key[1],'before':before,'after':e['record'],'matches_expected':e['record']==after})
            e['record']=before
roadmap_ok=len(ref_changes)==2 and all(r['matches_expected'] for r in ref_changes) and normalized==base_roadmap
originals=[]
for name in ('docs/project/evidence/p02-wmma/acceptance.json','docs/project/evidence/governance-readiness/a01-retained-binding.json'):
    raw=(ROOT/name).read_bytes();originals.append({'path':name,'size_bytes':len(raw),'sha256':sha(raw),'byte_identical_to_base':raw==base_bytes(name)})
evidence_changes=git('diff','--name-status',BASE,'--','docs/project/evidence').splitlines()
evidence_ok=evidence_changes==['M\tdocs/project/evidence/p02-wmma/README.md']
new_evidence=git('ls-files','--others','--exclude-standard','--','docs/project/evidence').splitlines()
svg_path='docs/assets/img/vortex_framework_stack.svg';raw=(ROOT/svg_path).read_bytes()
svg_expected=next(r['sha256'] for r in roadmap['protected_assets'] if r['path']==svg_path)
svg={'path':svg_path,'size_bytes':len(raw),'sha256':sha(raw),'matches_protected_digest':sha(raw)==svg_expected,
     'byte_identical_to_base':raw==base_bytes(svg_path),'embedded_in_readme':svg_path in (ROOT/'README.md').read_text()}
goldens=inventory('ci/baselines');fixtures=inventory('ci/project/fixtures')
warm=load('ci/project/p06_warm_contract.json')
checks={
 'head_is_requested_revision':head_before==EXPECTED_HEAD,'69_measurements_match':measurement_ok,
 '21_dependency_descriptors_and_pins_match':deps_ok,'both_frozen_proofs_match':all(r['passes'] for r in proofs),
 'protected_groups_unchanged':all(r['unchanged'] for r in groups.values()),'only_two_roadmap_reference_changes':roadmap_ok,
 'original_acceptance_records_unchanged':all(r['byte_identical_to_base'] for r in originals),
 'historical_evidence_tracked_changes_only_p02_readme':evidence_ok,
 'svg_preserved_and_embedded':all(svg[k] for k in ('matches_protected_digest','byte_identical_to_base','embedded_in_readme')),
 '25_golden_files_present':len(goldens)==25,'39_fixture_files_present':len(fixtures)==39,
 'frozen_complete_counts':{k:qualified['complete_counts'][k] for k in ('processes','launches','checked_words')}=={'processes':24,'launches':792,'checked_words':25344},
 'frozen_disk_memory_and_performance_bounds':warm['budget']['min_free_bytes']==15*1024**3 and warm['budget']['max_rss_bytes']==4*1024**3 and warm['analysis']['candidate_median_percent_of_reference_max']==95 and warm['analysis']['all_formats_must_improve'] is True and warm['sampling']['optional_stopping'] is False}
head_after=git('rev-parse','HEAD').strip();status_after=git('status','--short').splitlines()
checks['head_and_status_stable']=head_after==head_before and status_after==status_before
result={'schema_version':1,'reviewer':'/root/a051_final_protected_inputs','scope':'read-only protected source and evidence-reference audit; no test-body or native execution',
 'start_utc':started,'end_utc':datetime.now(timezone.utc).isoformat(),'repository':str(ROOT),'base_revision':BASE,'head_before':head_before,'head_after':head_after,
 'status_before':status_before,'status_after':status_after,'checks':checks,'all_pass':all(checks.values()),
 'measurement_sources':{'count':len(measurement),'total_bytes':sum(r['size_bytes'] for r in measurement),'inventory':measurement},
 'dependency_descriptors':{'count':len(deps),'inventory':deps,'pin':pin,'proof_revision':counter['dependency_revision'],'gitlink_base':gitlink_base,'gitlink_head':gitlink_head,'local_source_files_present':sum(r['local_source_present'] for r in deps),'source_bytes_rehashed':0},
 'frozen_proofs':proofs,'protected_groups':groups,'golden_baselines':goldens,'numerical_fixtures':fixtures,
 'roadmap':{'reference_changes':ref_changes,'entire_document_unchanged_after_reversing_two_references':roadmap_ok,'phases':[{'id':p['id'],'status':p['status']} for p in roadmap['phases']]},
 'original_acceptance_records':originals,'historical_evidence':{'tracked_changes':evidence_changes,'new_untracked_files':new_evidence,'preserved_originals_established_by_git_diff':True,'all_historical_artifact_bytes_rehashed':False},
 'svg':svg,'warm_budget':warm['budget'],'warm_sampling':warm['sampling'],'warm_analysis':warm['analysis'],'complete_counts':qualified['complete_counts'],
 'limitations':['No tests, builds, native runs, dependency fetching or native/phase qualification were performed.','The 21 dependency descriptors and gitlink are preserved; dependency source bytes are absent and were not rehashed.','Historical tree preservation uses exact git diffs plus explicit acceptance-record hashes; every historical artifact was not separately rehashed.','Status/backlog/README updates and new evidence are allowed presentation/provenance additions, not changes to accepted numerical scope.','This audit describes the observed working tree; a later published revision still requires its own full strict governance and independent original replay.']}
path=OUT/'a051-protected-inputs.json';path.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
print(json.dumps({'all_pass':result['all_pass'],'checks':checks,'measurement_bytes':result['measurement_sources']['total_bytes'],'new_evidence_files':len(new_evidence),'output':str(path)},indent=2))
raise SystemExit(0 if result['all_pass'] else 1)
