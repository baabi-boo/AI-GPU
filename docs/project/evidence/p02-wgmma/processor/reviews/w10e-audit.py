#!/usr/bin/env python3
"""Read-only source and immutable-publication preflight; no GPU/test execution."""
import collections
import datetime
import gzip
import hashlib
import json
import pathlib
import re
import shutil
import subprocess

WORK = pathlib.Path('${WORK}')
REPO = WORK/'verifier-candidate'
PRIMARY = WORK.parent/'AI-GPU'
OUT = WORK/'reviews'
DELIVERY = REPO/'docs/project/evidence/p02-wgmma/processor'
BASE = '86a76803d122ad7044c951b9262bff3639a931d5'
LOCAL = '5e3b74fd569169ad921315223c121a037ae656b7'
PUBLISHED = '359a8c007f450a8146540f795cb576b29818fa03'
TREE = '97116818da872f43f952a351eb6616fc327be438'
EXPECTED_CODE = tuple('ci/project/'+x for x in (
    'p02_wgmma_dependencies.py','p02_wgmma_matrix.py','p02_wgmma_packet.py',
    'p02_wgmma_records.py','test_p02_wgmma_dependencies.py','test_p02_wgmma_lmem.py',
    'test_p02_wgmma_matrix.py','test_p02_wgmma_packet.py','test_p02_wgmma_retention.py'))

def git(*args, repo=REPO):
    result = subprocess.run(['git', *args], cwd=repo, capture_output=True, check=True)
    return result.stdout

def identity(path):
    assert path.is_file() and not path.is_symlink(), path
    before = path.stat()
    data = path.read_bytes()
    after = path.stat()
    assert (before.st_ino,before.st_size,before.st_mtime_ns)==(after.st_ino,after.st_size,after.st_mtime_ns),path
    return {'sha256':hashlib.sha256(data).hexdigest(),'size_bytes':len(data)}

def tree_map(revision):
    rows = {}
    for raw in git('ls-tree','-rz',revision).split(b'\0'):
        if not raw: continue
        description,path = raw.split(b'\t',1)
        mode,kind,sha=description.decode().split()
        rows[path.decode()]={'mode':mode,'kind':kind,'sha':sha}
    return rows

base_tree,head_tree = tree_map(BASE),tree_map('HEAD')
changed = sorted(path for path in set(base_tree)|set(head_tree) if base_tree.get(path)!=head_tree.get(path))
assert changed == sorted(EXPECTED_CODE), changed
assert git('rev-parse','HEAD').decode().strip()==LOCAL
assert git('rev-parse','HEAD^{tree}').decode().strip()==TREE
assert git('rev-parse','HEAD',repo=PRIMARY).decode().strip()=='4af2307e57202c1269e20f893267a5583ad3cba0'
assert not git('status','--porcelain',repo=PRIMARY).strip()

current = {path:identity(REPO/path) for path in EXPECTED_CODE}
for path,row in current.items():
    assert row['sha256']==hashlib.sha256(git('show','HEAD:'+path)).hexdigest(),path
assert current['ci/project/p02_wgmma_packet.py']['sha256']=='11497b57db50c4c1e690d38c406d0de94f86b2017cec036f7ed79008151e72a4'
assert current['ci/project/test_p02_wgmma_packet.py']['sha256']=='b22daed1c623ae72389da7bf9ab12c242e92ef300d7a7762e3946ec1d38271bf'

protected_prefixes=('hw/','sim/','sw/','runtime/','profiles/','ci/testcases/','ci/baselines/',
                    'ci/project/fixtures/','docs/designs/','docs/project/evidence/')
protected_singletons=('VERSION','configure','VX_config.toml','VX_types.toml','AGENTS.md',
                      'docs/project/acceptance.md','docs/review/code-review-policy.md',
                      'ci/project/p02_wgmma_matrix.json','ci/project/p02_tensor_contract.json',
                      'docs/assets/img/vortex_framework_stack.svg','LICENSE')
protected = sorted(p for p in base_tree if p.startswith(protected_prefixes) or p in protected_singletons)
for path in protected:
    assert head_tree.get(path)==base_tree[path],path
working_changes=git('diff','--name-only','HEAD').decode().splitlines()
allowed_docs={'README.md','ROADMAP.md','docs/project/roadmap.json','docs/project/backlog.md',
              'docs/project/developer-guide.md','docs/project/p02-wgmma-handoff.md',
              'docs/project/phases/p02-tensor.md','docs/project/status.md'}
assert set(working_changes)<=allowed_docs,working_changes
frozen_paths=('ci/project/p02_wgmma_matrix.json','ci/project/p02_tensor_contract.json',
              'docs/designs/tensor_numerics_v1.md','docs/assets/img/vortex_framework_stack.svg')
frozen={p:identity(REPO/p) for p in frozen_paths}
for path,row in frozen.items():
    assert row['sha256']==hashlib.sha256(git('show',BASE+':'+path)).hexdigest(),path
assert frozen['ci/project/p02_wgmma_matrix.json']['sha256']=='fdc3ea03364babc00892f7de31fb2f2053074bf1ea76cb605dfbe5c5ac31b002'
assert 'docs/assets/img/vortex_framework_stack.svg' in (REPO/'README.md').read_text()

lineage=[]
for name,local,published,tree in (
    ('implementation-publication.json','7360bbadf4f9dcbd80a3f326c91a1c9cd72ffa7b','4af2307e57202c1269e20f893267a5583ad3cba0','42e5d6f2c9c0c2035c4d3ec8c86125e8cca45192'),
    ('verifier-publication.json','ba12d66e14771be32dbed7a67a988b839cd41e23','ad94b696409d4d05c1063541ac014478f90c3e71','14777b89cabaf7656accceeb846f128fb9bca542'),
    ('verifier-fix-publication.json',LOCAL,PUBLISHED,TREE)):
    data=json.loads((WORK/name).read_text())
    raw=data['local_raw_commit'].encode()
    assert hashlib.sha1(b'commit '+str(len(raw)).encode()+b'\0'+raw).hexdigest()==local
    assert git('cat-file','commit',local)==raw
    assert git('rev-parse',local+'^{tree}').decode().strip()==tree
    assert data['published_tree']==tree
    assert data.get('published_revision',data.get('published_commit'))==published
    assert data['branch_readback']['object']['sha']==published
    lineage.append({'receipt':name,**identity(WORK/name),'local_revision':local,
                    'published_revision':published,'identical_tree':tree})
remote=json.loads((OUT/'w10e-remote-commit.json').read_text())
assert remote['sha']==PUBLISHED and remote['tree']['sha']==TREE
assert [p['sha'] for p in remote['parents']]==['ad94b696409d4d05c1063541ac014478f90c3e71']

components=[]
secrets=[]
patterns={
 'private_key_header':re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----'),
 'github_token':re.compile(r'(?<![A-Za-z0-9_])gh[pousr]_[A-Za-z0-9]{30,}(?![A-Za-z0-9_])'),
 'github_pat':re.compile(r'(?<![A-Za-z0-9_])github_pat_[A-Za-z0-9_]{60,}(?![A-Za-z0-9_])'),
 'aws_access_key':re.compile(r'(?<![A-Z0-9])AKIA[A-Z0-9]{16}(?![A-Z0-9])')}
def scan(label,text):
    for name,pattern in patterns.items():
        count=len(pattern.findall(text))
        if count: secrets.append({'path':label,'pattern':name,'count':count})

for component in ('processor-core','processor-artifacts','processor-historical-verifier','compiler-recovery-v2'):
    directory=DELIVERY/component
    for path in sorted(directory.iterdir()):
        assert identity(path)==identity(WORK/'publication-staging'/component/path.name),path
    inventory=json.loads((directory/'inventory.json').read_text())
    bundle=directory/'evidence-bundle.json.gz'
    assert identity(bundle)=={'sha256':inventory['bundle_sha256'],'size_bytes':inventory['bundle_size_bytes']}
    assert bundle.stat().st_size<=4194304
    with gzip.open(bundle,'rb') as stream:
        expanded=stream.read(100663297)
    assert len(expanded)<=100663296
    data=json.loads(expanded)
    assert len(data['files'])==inventory['file_count']<=4096
    indexed={r['path']:r for r in inventory['files']}
    assert len(indexed)==len(data['files'])
    suspicious=[]
    for row in data['files']:
        name=row['path']; text=row['content']; content=text.encode()
        assert hashlib.sha256(content).hexdigest()==indexed[name]['published_sha256'],name
        assert len(content)==indexed[name]['published_size_bytes'],name
        assert '\0' not in text and not content.startswith(b'\x7fELF'),name
        if pathlib.PurePosixPath(name).suffix.lower() in ('.elf','.vxbin','.o','.so','.a','.vcd','.fst','.deb','.tar','.zip'):
            suspicious.append(name)
        scan(component+':'+name,text)
    assert not suspicious,(component,suspicious)
    components.append({'component':component,'files':len(data['files']),
                       'bundle':identity(bundle),'expanded_bytes':len(expanded),
                       'binary_waveform_archive_members':suspicious})

new_paths=git('ls-files','--others','--exclude-standard').decode().splitlines()
assert all(p.startswith('docs/project/evidence/p02-wgmma/processor/') for p in new_paths),new_paths
extensions=collections.Counter()
new_file_bytes=0
for relative in new_paths:
    path=REPO/relative
    row=identity(path); new_file_bytes+=row['size_bytes']; extensions[path.suffix or '<none>']+=1
    assert row['size_bytes']<=4194304,(relative,row)
    assert not path.stat().st_mode & 0o111,relative
    if path.suffix=='.gz':
        assert path.name=='evidence-bundle.json.gz',relative
    else:
        data=path.read_bytes()
        assert b'\0' not in data and not data.startswith(b'\x7fELF'),relative
        scan(relative,data.decode('utf-8'))

diff=subprocess.run(['git','diff','--check',BASE],cwd=REPO,capture_output=True)
assert diff.returncode==0,diff.stdout.decode()+diff.stderr.decode()
for path,row in current.items(): assert identity(REPO/path)==row,path
assert not secrets,secrets
result={
 'schema_version':1,'reviewer':'/root/w10e_final_source_preflight',
 'reviewed_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
 'decision':'approve_fixed_code_and_immutable_component_preflight','findings':[],
 'scope':'Read-only final source/diff/publication preflight. Documentation and final acceptance are being assembled by other owners. This review does not certify their eventual final bytes, final tree, publication push or phase closure.',
 'base_revision':BASE,'fixed_local_revision':LOCAL,'fixed_published_revision':PUBLISHED,'fixed_tree':TREE,
 'primary_execution_checkout':{'revision':'4af2307e57202c1269e20f893267a5583ad3cba0','clean':True},
 'code_changed_paths':changed,'fixed_code_identities':current,'protected_tree_entries_unchanged':len(protected),
 'unchanged_legacy_evidence_tree_entries':sum(p.startswith('docs/project/evidence/') for p in protected),
 'frozen_current_identities':frozen,'working_tracked_documentation_at_observation':working_changes,
 'local_and_published_lineage':lineage,'fresh_remote_commit_receipt':{'path':'reviews/w10e-remote-commit.json',**identity(OUT/'w10e-remote-commit.json')},
 'immutable_components':components,
 'new_publication_observation':{'file_count':len(new_paths),'total_bytes':new_file_bytes,'extensions':dict(extensions),
    'all_new_paths_under_requested_processor_evidence':True,'all_files_bounded_at_four_mib':True,
    'gzip_files_are_named_evidence_bundles':True,'no_other_binary_or_executable_file_observed':True},
 'bounded_credential_pattern_scan':{'patterns':list(patterns),'matches':secrets,
    'limitation':'A bounded literal-pattern scan of observed UTF-8 publication files and decoded archive members, not a complete secret or redistribution-rights audit.'},
 'diff_check':{'command':'git diff --check '+BASE,'exit_code':diff.returncode},
 'resource_observation':{'free_disk_bytes':shutil.disk_usage(WORK).free},
 'not_run':['GPU execution','RTL builds','compiler builds','unit tests','full offline suite','final governance checks owned by coordinator'],
 'acceptance_granted':False,'phase_complete_claimed':False,'human_approval_claimed':False,
 'audit_script':{'path':'reviews/w10e-audit.py',**identity(pathlib.Path(__file__))}}
(OUT/'w10e.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'decision':result['decision'],'code_paths':len(changed),'protected_entries':len(protected),
 'legacy_evidence_entries':result['unchanged_legacy_evidence_tree_entries'],
 'component_members':sum(x['files'] for x in components),'new_files_observed':len(new_paths),
 'new_bytes_observed':new_file_bytes,'credential_pattern_matches':len(secrets)},indent=2))
