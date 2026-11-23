#!/usr/bin/env python3
"""Inert final source/preservation review; does not execute retained programs."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile

ROOT = Path('/tmp/ai-gpu-native-lifetime-dfd857')
WORK = Path('/tmp/ai-gpu-native-lifetime-dfd857-work')
BASE = '6130a2f7424932a6f3b7377ef8ae4816da2b304f'
HEAD = 'b4127b19a004b5aebb8d52eab9ceda0da3ff4561'
def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args])
def digest(data):
    return hashlib.sha256(data).hexdigest()
def blob(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\x00' + data).hexdigest()
def tree(revision):
    result = {}
    for row in git('ls-tree', '-r', '-z', revision).split(b'\x00'):
        if not row:
            continue
        info, path = row.split(b'\t', 1)
        mode, kind, oid = info.decode().split()
        result[path.decode()] = {'mode': mode, 'kind': kind, 'oid': oid}
    return result
def live(path):
    p = ROOT / path
    if p.is_symlink():
        return os.readlink(p).encode(), '120000'
    return p.read_bytes(), '100755' if p.stat().st_mode & 0o111 else '100644'
def same_live(path, expected):
    assert expected['kind'] == 'blob', (path, expected)
    data, mode = live(path)
    assert blob(data) == expected['oid'], ('live blob differs', path)
    assert mode == expected['mode'], ('live mode differs', path)
    return {'path': path, 'sha256': digest(data), 'size_bytes': len(data), 'git_blob_sha': expected['oid'], 'git_mode': mode}

before_status = git('status', '--porcelain=v1', '-uall').decode().splitlines()
base_tree, head_tree = tree(BASE), tree(HEAD)
assert git('rev-parse', 'HEAD').decode().strip() == HEAD
prior = json.loads((WORK / 'w06_a05-preservation.json').read_text())
source_projection = json.loads((WORK / 'w09_a02-projection.json').read_text())
protected_trees = []
protected_members = set()
for item in prior['protected_trees']:
    path = item['path']
    base_oid = git('rev-parse', BASE + ':' + path).decode().strip()
    head_oid = git('rev-parse', HEAD + ':' + path).decode().strip()
    assert base_oid == head_oid
    members = [p for p in base_tree if p.startswith(path + '/')]
    for p in members:
        assert base_tree[p] == head_tree[p]
        same_live(p, head_tree[p])
        protected_members.add(p)
    protected_trees.append({'path': path, 'git_tree': base_oid, 'tracked_blobs_verified': len(members)})
protected_files = []
for item in prior['protected_files']:
    path = item['path']
    assert base_tree[path] == head_tree[path]
    if path == 'README.md':
        continue
    protected_files.append(same_live(path, head_tree[path]))
readme = (ROOT / 'README.md').read_text()
assert 'docs/assets/img/vortex_framework_stack.svg' in readme
historical_entries = []
for raw in git('ls-tree', BASE + ':docs/project/evidence').decode().splitlines():
    info, name = raw.split('\t', 1)
    mode, kind, oid = info.split()
    path = 'docs/project/evidence/' + name
    assert git('rev-parse', HEAD + ':' + path).decode().strip() == oid
    members = [path] if kind == 'blob' else [p for p in base_tree if p.startswith(path + '/')]
    for p in members:
        same_live(p, base_tree[p])
    historical_entries.append({'path': path, 'kind': kind, 'git_oid': oid, 'tracked_blobs_verified': len(members)})
assert len(historical_entries) == 40
assert sum(x['kind'] == 'tree' for x in historical_entries) == 25
assert sum(x['kind'] == 'blob' for x in historical_entries) == 15

changed = git('diff', '--name-only', BASE, HEAD).decode().splitlines()
source_paths = [p for p in changed if not p.startswith('docs/project/')]
assert len(source_paths) == 24
changed_sources = [same_live(p, head_tree[p]) for p in source_paths]
archive = ROOT / 'docs/project/evidence/p06-native-lifetime/native/b4127b19-run45130300651-attempt1/original.zip'
archive_data = archive.read_bytes()
assert len(archive_data) == 9086055
assert digest(archive_data) == '3d4879f73c197352689d65feb56e73f537701fc1411e55bf53c92b1b41e13db3'
projected = []
with zipfile.ZipFile(archive) as z:
    for row in source_projection['root_source_join']:
        path = row['path']
        checked = same_live(path, head_tree[path])
        assert checked['sha256'] == row['sha256'] and checked['size_bytes'] == row['size_bytes']
        for member in row['retained_copies']:
            data = z.read(member)
            assert blob(data) == head_tree[path]['oid']
            assert digest(data) == checked['sha256'] and len(data) == checked['size_bytes']
        projected.append(checked)
    native = json.loads(z.read('native-lifetime/report.json'))
    probe = json.loads(z.read('pending-probe/report.json'))
    claims = ['qualified','ready_for_warm','warm_execution','full_warm_coverage','acceptance_claimed','phase_acceptance','performance_acceptance']
    for report in (native, probe):
        assert all(report[k] is False for k in claims)
    assert native['outcome'] == probe['outcome'] == 'pass'
assert len(projected) == 813
inventory = [{k: row[k] for k in ('path','sha256','size_bytes')} for row in sorted(projected,key=lambda x:x['path'])]
inventory_sha = digest(json.dumps(inventory,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode())
assert inventory_sha == 'd096aef75122b0640c0ef528fcf6797555ed96ce82815de18bd60c3915a6e595'
contracts = [same_live(row['path'],head_tree[row['path']]) for row in source_projection['frozen_design_contracts']]
assert len(contracts) == 7
for row in contracts:
    row['present_at_audit_base'] = row['path'] in base_tree
    if row['present_at_audit_base']:
        assert base_tree[row['path']] == head_tree[row['path']]
    else:
        assert row['path'] == 'docs/designs/managed_counter_lifetime_v1.md'
classifier = WORK / 'w10_a01-immutable-base'
classifier.mkdir(exist_ok=True)
classifier_files = []
for original, name in [('ci/change_impact.py','change_impact.py'),('docs/review/change-impact.yaml','change-impact.yaml')]:
    data = git('show', BASE + ':' + original)
    assert data == (ROOT / original).read_bytes()
    (classifier / name).write_bytes(data)
    classifier_files.append({'source_path': original, 'retained_path': str(classifier / name), 'sha256': digest(data)})
command = ['python3','-I',str(classifier / 'change_impact.py'),'--repo',str(ROOT),'--policy',str(classifier / 'change-impact.yaml'),'explain','--base',BASE,'--head',HEAD]
run = subprocess.run(command,capture_output=True,text=True,check=True)
(WORK / 'w10_a01-classification.txt').write_text(run.stdout)
assert 'R2' in run.stdout
after_status = git('status', '--porcelain=v1', '-uall').decode().splitlines()
for line in after_status:
    path = line[3:]
    assert path == 'README.md' or path.startswith('docs/'), ('nondocumentation workspace delta', line)
result = {
    'scope':'Final independent R3 code/preservation review; inert Git, bytes, modes and original-data inspection only.',
    'observed_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'base_revision':BASE,'reviewed_revision':HEAD,'reviewed_tree':git('rev-parse',HEAD+'^{tree}').decode().strip(),
    'outcome':'pass','findings':[], 'unit_tests':'not_run_by_this_review','native_execution':'not_run_by_this_review','retained_programs_executed':False,
    'protected_trees':protected_trees,'unique_protected_tree_blobs':len(protected_members),'protected_files':protected_files,
    'readme_exception':'Current progress documentation is intentionally edited; inherited SVG bytes/mode and README embedding are preserved.',
    'historical_evidence_entries':historical_entries,'historical_entry_counts':{'trees':25,'files':15,'total':40},
    'changed_source_files':changed_sources,'projected_source_count':len(projected),'root_source_inventory_sha256':inventory_sha,
    'frozen_design_contracts':contracts,'reviewer_correction':'Initial check assumed all seven contracts existed at the audit base and stopped on the new lifetime contract; corrected to six unchanged base contracts plus one new contract unchanged from the implementation revision. No repository or retained evidence was altered.','archive':{'sha256':digest(archive_data),'size_bytes':len(archive_data),'git_blob_sha':blob(archive_data)},
    'original_claim_flags':dict.fromkeys(claims,False),'classifier_inputs':classifier_files,'classifier_command':command,
    'classification':{'automatic':'R2','manual':'R3','reason':'Separately versioned external lifetime transcript and explicit CLI mode'},
    'working_status_before':before_status,'working_status_after':after_status,
    'limits':['No fresh dependency compilation provenance or full counter qualification is inferred.','No warm/hardware/RTL/performance acceptance is inferred.','Documentation/evidence remains in progress; root must verify final committed tree and publication lease.']
}
(WORK / 'w10_a01-preservation.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'outcome':'pass','protected_trees':len(protected_trees),'unique_protected_tree_blobs':len(protected_members),'unchanged_protected_files':len(protected_files),'historical_entries':40,'changed_source_files':len(changed_sources),'projected_sources':len(projected),'frozen_contracts':len(contracts),'root_source_inventory_sha256':inventory_sha,'receipt_sha256':digest((WORK/'w10_a01-preservation.json').read_bytes())},indent=2))
