from pathlib import Path
import datetime, hashlib, json, re, subprocess
root=Path('/tmp/ai-gpu-native-lifetime-dfd857')
work=Path('/tmp/ai-gpu-native-lifetime-dfd857-work')
rev='b4127b19a004b5aebb8d52eab9ceda0da3ff4561'
before=json.loads((work/'w08_a06-before.json').read_text())
sha=lambda data: hashlib.sha256(data).hexdigest()
def git(*args):
    return subprocess.check_output(['git', *args],cwd=root)
def missing_links(path,body):
    out=[]
    for value in re.findall(r'\[[^\]]*\]\(([^)]+)\)',body):
        target=value.split('#',1)[0]
        if not target or re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:',target):
            continue
        if not (root/path).parent.joinpath(target).exists():
            out.append(target)
    return sorted(set(out))
files=[]
for name,digest in before.items():
    prior=(work/'w08_a06-before'/name).read_bytes()
    current=(root/name).read_bytes()
    assert sha(prior)==digest, name
    assert sha(prior)==sha(git('show',f'{rev}:{name}')), name
    files.append({'path':name,'before_sha256':digest,'after_sha256':sha(current),'before_bytes':len(prior),'after_bytes':len(current),'missing_links_before':missing_links(name,prior.decode()),'missing_links_after':missing_links(name,current.decode())})

historical='docs/project/p06-managed-preflight-handoff.md'
old=(work/'w08_a06-before'/historical).read_text(); new=(root/historical).read_text()
marker='## Next bounded action and present scope'
assert old[old.index(marker):]==new[new.index(marker):]
workspace='docs/project/p06-workspace-handoff.md'
oldws=(work/'w08_a06-before'/workspace).read_text(); newws=(root/workspace).read_text()
markerws='## Current implementation and evidence'
assert oldws[oldws.index(markerws):]==newws[newws.index(markerws):]

frozen=[
'docs/designs/ai_operator_contract_v1.md',
'docs/designs/managed_counter_preflight_v1.md',
'docs/designs/serial_matmul_workspace_v1.md',
'docs/designs/simx_counter_lifetime_v1.md',
'docs/designs/tensor_numerics_v1.md',
'docs/designs/warm_workspace_benchmark_v1.md',
'docs/designs/managed_counter_lifetime_v1.md',
'docs/assets/img/vortex_framework_stack.svg',
'ROADMAP.md','docs/project/roadmap.json','docs/project/acceptance.md']
protected=[]
for path in frozen:
    native=git('show',f'{rev}:{path}'); current=(root/path).read_bytes()
    assert native==current,path
    protected.append({'path':path,'sha256':sha(current),'unchanged_from':rev})
changed=git('diff','--name-only',rev).decode().splitlines()
acceptance_or_golden=[p for p in changed if p.startswith('ci/baselines/') or ('acceptance' in Path(p).name and p.endswith('.json'))]
assert not acceptance_or_golden,acceptance_or_golden
historical_changes=[p for p in changed if p.startswith('docs/project/evidence/') and not p.startswith('docs/project/evidence/p06-native-lifetime/')]
assert not historical_changes,historical_changes
old_readme=(work/'w08_a06-before/README.md').read_text(); new_readme=(root/'README.md').read_text()
img_old=[line for line in old_readme.splitlines() if '<img ' in line]
img_new=[line for line in new_readme.splitlines() if '<img ' in line]
assert img_old==img_new and any('vortex_framework_stack.svg' in x for x in img_new)
checks=subprocess.run(['git','diff','--check','--',*before],cwd=root,capture_output=True,text=True)
assert checks.returncode==0,(checks.returncode,checks.stdout,checks.stderr)
assert not [f for f in files if f['missing_links_after']],files
report={
'schema':'w08-a06-current-docs-static-review-v1',
'checked_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
'baseline_revision':rev,
'owned_files':files,
'protected_files':protected,
'historical_managed_handoff_body_unchanged':True,
'historical_workspace_body_unchanged':True,
'readme_upstream_image_embedding_unchanged':True,
'acceptance_or_golden_diffs':acceptance_or_golden,
'historical_evidence_diffs':historical_changes,
'diff_check':{'exit_code':checks.returncode,'stdout':checks.stdout,'stderr':checks.stderr},
'new_test_or_build_execution':False,
'governance_and_generic_ci_result_claimed':False,
'concurrent_changes_outside_ownership':[p for p in changed if p not in before]
}
(work/'w08_a06-static-check.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'owned_files':len(files),'relative_links_missing':sum(len(f['missing_links_after']) for f in files),'protected_exact_byte_checks':len(protected),'historical_handoff_bodies_unchanged':True,'upstream_embedding_unchanged':True,'diff_check_exit':checks.returncode,'receipt':str(work/'w08_a06-static-check.json')}))
