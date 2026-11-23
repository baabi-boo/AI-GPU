import collections, datetime, hashlib, io, json, os, pathlib, stat, subprocess, sys, tarfile, time
SOURCE=pathlib.Path('/workspace/p06-local-run-source')
PACKET=pathlib.Path('/workspace/p06-local-native-run-01/evidence')
RECEIPT=PACKET/'dependency-preparation.json'
OUTPUT=pathlib.Path('/workspace/scratch/279b6658611e/validation/w04_a04-preparation-review.json')
EXPECTED='463538673387219cfcbeee4bdb47d47b357130fb858cc4d9c6f6fcc45ceda3de'
REV='ac2f2ae761c3644103278f7a41cc6ae7db734a86'
START=time.monotonic()

def digest_stream(f):
    h=hashlib.sha256();n=0
    while b:=f.read(1024**2):h.update(b);n+=len(b)
    return h.hexdigest(),n

def digest(p):
    with p.open('rb') as f:return digest_stream(f)

def check(x,message):
    if not x:raise AssertionError(message)

body=RECEIPT.read_bytes();check(hashlib.sha256(body).hexdigest()==EXPECTED,'preparation pin mismatch')
d=json.loads(body);t=d['toolchain_receipt'];archive=pathlib.Path(t['archive_root']);tools=pathlib.Path(t['tools_root']);members={x['path']:x for x in t['members']}
result={'schema_version':1,'reviewer':'w04_a04','started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'review_scope':'Independent read-only audit of the actual formal local preparation and fresh toolchain installation; no native workload or acceptance claim','source_revision':REV,'preparation':{'path':str(RECEIPT),'sha256':EXPECTED,'size_bytes':len(body)},'outcome':'running','failures':[]}
check(subprocess.check_output(['git','rev-parse','HEAD'],cwd=SOURCE).decode().strip()==REV,'source revision changed')
installer=SOURCE/'ci/project/p06_local_toolchain.py';result['installer_sha256']=digest(installer)[0]
check(result['installer_sha256']=='0bd80e40b6a22bf78a665e8f1b18818a21178bcc32248a20bfd3133d3c3d5aa8','installer differs from independently reviewed final link fixes')
check(subprocess.check_output(['git','show',REV+':ci/project/p06_local_toolchain.py'],cwd=SOURCE)==installer.read_bytes(),'installer working bytes differ from commit')
lock=SOURCE/'ci/project/p01_toolchain.lock.json';lock_bytes=lock.read_bytes();lock_doc=json.loads(lock_bytes)
check((hashlib.sha256(lock_bytes).hexdigest(),len(lock_bytes))==(t['manifest_sha256'],t['manifest_size_bytes']),'lock bytes mismatch')
result['manifest']={'sha256':t['manifest_sha256'],'semantic_sha256':t['manifest_semantic_sha256'],'historical_revision':t['revision']}
selected=[x for x in lock_doc['parts'] if x['path'].split('/')[0] in t['selected_components']]
check(sorted(selected,key=lambda x:x['path'])==t['parts'],'part inventory differs from trusted lock')
part_rows=[]
for row in t['parts']:
    p=archive/row['path'];st=p.lstat();check(stat.S_ISREG(st.st_mode) and st.st_nlink==1,'archive part is not unlinked regular file')
    sha=hashlib.sha256();git=hashlib.sha1(('blob '+str(st.st_size)+'\0').encode());n=0
    with p.open('rb') as f:
        while b:=f.read(1024**2):sha.update(b);git.update(b);n+=len(b)
    check((sha.hexdigest(),git.hexdigest(),n)==(row['sha256'],row['git_blob_sha'],row['size_bytes']),'archive part mismatch '+row['path'])
    part_rows.append({'path':row['path'],'sha256':sha.hexdigest(),'git_blob_sha':git.hexdigest(),'size_bytes':n})
result['archive_parts']={'count':len(part_rows),'bytes':sum(x['size_bytes'] for x in part_rows),'all_hashes_match':True,'rows':part_rows}
print(json.dumps({'progress':'archive part hashes verified','count':len(part_rows)}),flush=True)

class Joined(io.RawIOBase):
    def __init__(self,paths):self.paths=iter(paths);self.f=None
    def readable(self):return True
    def read(self,n=-1):
        check(0<=n<=1024**2,'unbounded independent archive read')
        out=bytearray()
        while len(out)<n:
            if self.f is None:
                p=next(self.paths,None)
                if p is None:break
                self.f=p.open('rb')
            b=self.f.read(n-len(out))
            if b:out.extend(b)
            else:self.f.close();self.f=None
        return bytes(out)
    def close(self):
        if self.f:self.f.close();self.f=None
        super().close()

seen=set();kinds=collections.Counter();regular_bytes=0;links=[];component_rows=[];max_file=0
for component in t['selected_components']:
    count=0;total=0
    parts=[archive/x['path'] for x in t['parts'] if x['path'].split('/')[0]==component]
    with Joined(parts) as stream,tarfile.open(fileobj=stream,mode='r|bz2') as tf:
        for item in tf:
            name=item.name.rstrip('/');check(name not in seen and name in members,'archive member inventory mismatch '+name);seen.add(name);count+=1
            row=members[name];path=tools/name;st=path.lstat()
            check(name.split('/')[0]==component,'component mismatch')
            check(not item.sparse,'sparse member not allowed')
            if item.isreg():
                kinds['file']+=1;check(row['kind']=='file' and stat.S_ISREG(st.st_mode),'regular kind mismatch '+name)
                with tf.extractfile(item) as f:sha,n=digest_stream(f)
                mode=item.mode&0o755
                if not mode&0o100:mode&=~0o111
                mode|=0o600
                check((sha,n,mode)==(row['sha256'],row['size_bytes'],row['mode']),'archive member bytes/mode mismatch '+name)
                check((sha,n)==digest(path) and stat.S_IMODE(st.st_mode)==mode,'installed member mismatch '+name)
                regular_bytes+=n;total+=n;max_file=max(max_file,n)
            elif item.isdir():
                kinds['directory']+=1;check(row['kind']=='directory' and stat.S_ISDIR(st.st_mode),'directory mismatch '+name)
            elif item.issym():
                kinds['symlink']+=1;check(row=={'kind':'symlink','path':name,'target':item.linkname},'symbolic archive metadata mismatch '+name)
                check(stat.S_ISLNK(st.st_mode) and os.readlink(path)==item.linkname,'symbolic installed target mismatch '+name)
                resolved=path.resolve(strict=True);check(resolved.is_relative_to(tools/component),'symbolic escape '+name)
                links.append({'path':name,'kind':'symlink','target':item.linkname,'resolved_relative':str(resolved.relative_to(tools))})
            elif item.islnk():
                kinds['hardlink']+=1;check(row=={'kind':'hardlink','path':name,'target':item.linkname},'hardlink archive metadata mismatch '+name)
                target=tools/item.linkname;check(stat.S_ISREG(st.st_mode) and os.path.samefile(path,target),'installed hardlink relationship mismatch '+name)
                resolved=path.resolve(strict=True);check(resolved.is_relative_to(tools/component),'hardlink escape '+name)
                links.append({'path':name,'kind':'hardlink','target':item.linkname,'same_inode_as_target':True,'resolved_relative':str(resolved.relative_to(tools))})
            else:raise AssertionError('unsupported archive member '+name)
    component_rows.append({'component':component,'member_count':count,'regular_bytes':total})
    print(json.dumps({'progress':'component archive and installed bytes verified','component':component,'members':count,'bytes':total}),flush=True)
check(seen==set(members),'recorded members absent from actual archives')
actual=set()
for root,dirs,files in os.walk(tools,followlinks=False):
    for name in dirs+files:actual.add(str((pathlib.Path(root)/name).relative_to(tools)))
check(actual==seen,'installed inventory missing or extra members')
check(len(seen)==t['member_count'] and regular_bytes==t['extracted_regular_bytes'],'extracted totals mismatch')
result['members']={'count':len(seen),'kinds':dict(kinds),'regular_bytes':regular_bytes,'maximum_regular_file_bytes':max_file,'missing':[],'extra':[],'components':component_rows,'archive_bytes_and_installed_bytes_independently_matched':True}
result['links']={'count':len(links),'unresolved':0,'escaping':0,'relationships_verified':True,'rows_sha256':hashlib.sha256(json.dumps(links,sort_keys=True,separators=(',',':')).encode()).hexdigest()}
selected_tools=[]
for name,row in t['tools'].items():
    path=pathlib.Path(row['path']);resolved=path.resolve(strict=True);sha,n=digest(path)
    check(str(resolved)==row['resolved_path'] and (sha,n)==(row['sha256'],row['size_bytes']),'selected tool identity mismatch '+name)
    check(resolved.is_relative_to(tools),'selected tool escapes')
    check(name.startswith(('libc64/','libcrt64/')) or os.access(path,os.X_OK),'selected compiler not executable '+name)
    selected_tools.append({'name':name,**row})
result['selected_tools']={'count':len(selected_tools),'identities_match':True,'rows':selected_tools,'executed_by_reviewer':False}
claims=('qualified','ready_for_warm','warm_execution','full_warm_coverage','acceptance_claimed','phase_acceptance','performance_acceptance')
for doc in (d,t):check(all(doc[x] is False for x in claims),'unsupported acceptance claim')
check(d['execution_origin']=='local' and d['network_acquisition'] is False and d['dependency_cache_used'] is False and d['toolchain_cache_used'] is False,'origin/acquisition mismatch')
check(d['native_execution']=='not_run' and t['native_execution']=='not_run','preparation claims native execution')
check(d['outcome']=='pass' and d['reason'] is None and d['failures']==[],'preparation not successful')
check(d['source_before']==d['source_after'] and d['source_before']['revision']==REV,'source observations differ')
check(d['budget']['min_free_bytes']==15*1024**3 and d['budget']['max_rss_bytes']==4*1024**3,'preparation resource bounds differ')
for scope in ['resources_before','resources_after']:
    r=d[scope];check(min(r['free_disk_bytes'].values())>=15*1024**3 and r['available_memory_bytes']>=4*1024**3,'resource observations below bound')
check(t['budget']=={'max_extracted_bytes':4*1024**3,'max_member_bytes':1024**3,'max_members':50000,'min_available_memory_bytes':4*1024**3,'min_free_bytes':15*1024**3,'timeout_seconds':1800},'toolchain budgets differ')
outer=json.loads((PACKET/'local-execution.json').read_bytes());stage=next(x for x in outer['stages'] if x['id']=='preparation');check(stage['outcome']=='pass' and stage['duration_seconds']<=1800,'bounded preparation stage mismatch')
result['resources']={name:d[name] for name in ['budget','resources_before','resources_after']};result['resources']['toolchain_budget']=t['budget'];result['resources']['outer_preparation_duration_seconds']=stage['duration_seconds']
result['scope']={'execution_origin':d['execution_origin'],'toolchain_origin':t['origin'],'network_acquisition':False,'cache_reuse':False,'native_execution':'not_run',**dict.fromkeys(claims,False),'limitation':'The reviewer rehashed actual archive/installed bytes and validated recorded preparation resources; this does not authenticate historical acquisition, enforce kernel-level network isolation, defeat malicious concurrent filesystem writers or establish full host-toolchain/native/qualification scope.'}
sys.path.insert(0,str(SOURCE/'ci/project'))
import p06_dependency_local_prepare as validator
validator.validate_local_preparation(d,REV)
result['trusted_metadata_validator_passed']=True
check(RECEIPT.read_bytes()==body,'preparation changed during independent review')
check((PACKET/'dependency-build/preparation.json').read_bytes()==body,'retained preparation copy differs')
check(digest(installer)[0]==result['installer_sha256'],'installer changed during independent review')
result.update(outcome='pass',finished_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),duration_seconds=round(time.monotonic()-START,6),retained_commands_executed=False,retained_binaries_executed=False,producer_source_modified=False,evidence_modified=False)
OUTPUT.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
print(json.dumps({'outcome':'pass','review':str(OUTPUT),'members':len(seen),'links':len(links),'tools':len(selected_tools),'duration_seconds':result['duration_seconds']}),flush=True)
