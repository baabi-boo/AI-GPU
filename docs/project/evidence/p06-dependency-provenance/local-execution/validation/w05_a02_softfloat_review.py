#!/usr/bin/env python3
"""Independent read-only audit of the actual completed SoftFloat subgraph."""
import collections, datetime, hashlib, json, os, pathlib, re, stat, struct, subprocess, time
SOURCE=pathlib.Path('/workspace/p06-local-run-source')
PACKET=pathlib.Path('/workspace/p06-local-native-run-01/evidence/dependency-build')
MATERIALIZED=pathlib.Path('/workspace/p06-local-native-run-01/dependency-sources/softfloat')
REV='ac2f2ae761c3644103278f7a41cc6ae7db734a86'
PIN='b51ef8f3201669b2288104c28546fc72532a1ea4'
TREE='8d9d47a6d74670d25bbbcc956a04de4c2605253b'
OUTPUT=pathlib.Path('/workspace/scratch/279b6658611e/validation/w05_a02-softfloat-review.json')
start=time.monotonic()
def need(ok, label):
    if not ok: raise ValueError(label)
def sha(data):return hashlib.sha256(data).hexdigest()
def file_id(path):
    data=path.read_bytes();return {'sha256':sha(data),'size_bytes':len(data)}
def git(*args, root=SOURCE):
    return subprocess.check_output(['git','-C',str(root),*args],env={**os.environ,'GIT_CONFIG_NOSYSTEM':'1','GIT_TERMINAL_PROMPT':'0'})
need(git('rev-parse','HEAD').decode().strip()==REV,'source revision differs')
repo=SOURCE/'third_party/softfloat'
need(git('rev-parse',PIN+'^{tree}',root=repo).decode().strip()==TREE,'SoftFloat locked tree differs')
entries={}
for row in git('ls-tree','-r','-z',PIN,root=repo).split(b'\0'):
    if row:
        metadata,name=row.split(b'\t');mode,kind,oid=metadata.split();need(kind==b'blob','unexpected Git entry')
        entries[name.decode()]={'mode':mode.decode(),'oid':oid.decode()}
blobs={}
def blob(relative):
    if relative not in blobs:
        row=entries[relative];data=git('cat-file','blob',row['oid'],root=repo)
        need(hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()==row['oid'],'Git blob mismatch')
        blobs[relative]=data
    return blobs[relative]
makefile=blob('build/Linux-x86_64-GCC/Makefile').decode()
need((MATERIALIZED/'build/Linux-x86_64-GCC/Makefile').read_bytes()==makefile.encode(),'materialized Makefile differs')
selected=[];groups={}
for group,directory in [('PRIMITIVES','source'),('SPECIALIZE','source/RISCV'),('OTHERS','source')]:
    lines=makefile.splitlines();first=[n for n,x in enumerate(lines) if x.startswith('OBJS_'+group+' =')]
    need(len(first)==1,'ambiguous Makefile group');n=first[0];words=[]
    while True:
        line=lines[n].split('=',1)[1] if n==first[0] else lines[n]
        continued=line.rstrip().endswith('\\');line=line.rstrip().removesuffix('\\')
        words+=line.split();n+=1
        if not continued:break
    need(all(re.fullmatch(r'[A-Za-z0-9_]+\$\(OBJ\)',w) for w in words),'unexpected Makefile token')
    names=[w.removesuffix('$(OBJ)') for w in words];groups[group]=len(names)
    selected += [{'name':name+'.o','source':directory+'/'+name+'.c'} for name in names]
need(groups=={'PRIMITIVES':31,'SPECIALIZE':20,'OTHERS':258},'selected Makefile groups differ')
need(len({x['name'] for x in selected})==309,'SoftFloat object population differs')
record_bytes={};records=[]
for path in sorted((PACKET/'records').glob('*.json')):
    body=path.read_bytes();row=json.loads(body)
    if row.get('cwd')==str(MATERIALIZED/'build/Linux-x86_64-GCC'):
        need(path.stem==row['id'],'record filename/id mismatch');records.append(row);record_bytes[path.name]=body
compiles=[x for x in records if x['role']=='compile'];archives=[x for x in records if x['role']=='archive']
need(len(records)==310 and len(compiles)==309 and len(archives)==1,'SoftFloat recorder population differs')
by_name={pathlib.PurePosixPath(x['output_path']).name:x for x in compiles}
need(len(by_name)==309 and set(by_name)=={x['name'] for x in selected},'compiled objects differ from Makefile')
config_body=(PACKET/'tool-config.json').read_bytes();config=json.loads(config_body)
prep=json.loads((PACKET/'preparation.json').read_bytes())
recorder=(SOURCE/'ci/project/p06_dependency_record.py').read_bytes()
root=pathlib.PurePosixPath(str(MATERIALIZED/'build/Linux-x86_64-GCC'))
payloads={};system_inputs={};pinned_inputs={};observed_symbols=[];output_bytes={}
def payload(row):
    key=row['payload'];need(re.fullmatch(r'[0-9a-f]{64}\.bin',key),'payload name differs')
    if key not in payloads:payloads[key]=(PACKET/'payloads'/key).read_bytes()
    body=payloads[key];need((sha(body),len(body))==(row['sha256'],row['size_bytes']),'payload identity differs')
    return body
def deps(body):
    text=body.decode().replace('\\\n',' ');target,names=text.split(':',1)
    need(target.strip().startswith(str(root)+'/'),'dependency target differs')
    result=[]
    for name in names.split():
        need('\\' not in name,'unexpected escaped dependency name')
        resolved=os.path.normpath(str(root/name))
        if resolved not in result:result.append(resolved)
    return target.strip(),result

def elf_symbols(body):
    need(len(body)>=64 and body[:7]==b'\x7fELF\x02\x01\x01','object is not ELF64 little endian')
    h=struct.unpack_from('<16sHHIQQQIHHHHHH',body)
    need(h[1]==1 and h[2]==62 and h[3]==1,'object is not an x86-64 relocatable')
    off,esize,count=h[6],h[11],h[12];need(esize==64 and 0<count<256 and off+count*64<=len(body),'invalid ELF section table')
    sections=[struct.unpack_from('<IIQQQQIIQQ',body,off+i*64) for i in range(count)]
    tables=[s for s in sections if s[1]==2];need(len(tables)==1,'ELF symbol table population differs')
    s=tables[0];need(s[9]==24 and s[5]%24==0 and s[6]<count,'invalid ELF symbol table')
    strings=sections[s[6]];need(strings[1]==3 and strings[4]+strings[5]<=len(body),'invalid ELF symbol names')
    names=body[strings[4]:strings[4]+strings[5]];result=[]
    for i in range(s[5]//24):
        name,info,other,shndx,value,size=struct.unpack_from('<IBBHQQ',body,s[4]+i*24)
        if info>>4 in (1,2,10) and shndx!=0:
            need(name<len(names),'ELF symbol name outside table');end=names.index(0,name);symbol=names[name:end].decode('ascii')
            need(symbol,'empty defined external symbol');result.append(symbol)
    return result

prefix=['-c','-Werror-implicit-function-declaration','-DSOFTFLOAT_FAST_INT64','-fPIC','-DSOFTFLOAT_ROUND_ODD','-DINLINE_LEVEL=5','-DSOFTFLOAT_FAST_DIV32TO16','-DSOFTFLOAT_FAST_DIV64TO32','-DTHREAD_LOCAL=_Thread_local','-I.','-I../../source/RISCV','-I../../source/include','-O2','-o']
children=0
for row in records:
    need(row['state']=='finished' and row['outcome']=='pass' and row['exit_code']==0 and row['failures']==[] and row['reason'] is None and row['process_started'] is True,'unsuccessful recorder')
    need(row['output_absent_before'] is True and row['output_before'] is None,'output was not fresh')
    need(row['config_sha256']==sha(config_body),'config pin differs')
    need(row['recorder']['sha256']==sha(recorder) and row['recorder']['size_bytes']==len(recorder),'recorder identity differs')
    need(row['tool']==prep['host_tools'][row['tool_name']],'tool/preparation join differs')
    need(row['inputs_before']==row['inputs_after'],'inputs changed across recorder')
    need(row['environment']['CCACHE_DISABLE']=='1' and row['environment']['OBJCACHE']=='','cache environment differs')
    need(all(value is None for key,value in row['environment'].items() if key not in ('PATH','CCACHE_DISABLE','OBJCACHE')),'injected compiler environment')
    for c in row['children']:
        need(c['process_started'] is True and c['exit_code']==0 and row['started_ns']<=c['started_ns']<=c['finished_ns']<=row['finished_ns'],'child process or chronology differs')
        children+=1
    out=payload(row['output']);need(pathlib.Path(row['output_path']).read_bytes()==out,'current output differs from retained bytes')
    output_bytes[pathlib.PurePosixPath(row['output_path']).name]=out
for selection in selected:
    row=by_name[selection['name']];source_argument='../../'+selection['source']
    args=prefix+[selection['name'],source_argument]
    need(row['requested_arguments']==args,'compile recipe differs')
    need(row['tool_name']=='gcc','SoftFloat compiler differs')
    absolute=str(root/selection['name']);added=['-MD','-MF',absolute+'.d','-MT',absolute]
    need(row['arguments']==args+added,'dependency-recording compiler argv differs')
    need([c['stage'] for c in row['children']]==['dependencies','tool'],'compile child stages differ')
    need(row['children'][1]['argv']==[row['tool']['path'],*row['arguments']],'actual compiler child argv differs')
    prepass=[row['tool']['path'],*args[1:-3],source_argument,'-M','-MF',absolute+'.p06-before.d','-MT',absolute]
    need(row['children'][0]['argv']==prepass,'actual dependency child argv differs')
    before=payload(row['dependency_prepass_file']);after=payload(row['dependency_file'])
    need(before==after,'dependency set changed across compile')
    target,names=deps(before);need(target==absolute and names==[x['path'] for x in row['inputs_before']],'dependency list/input inventory differs')
    need(str(MATERIALIZED/selection['source']) in names,'selected source absent from dependencies')
    for item in row['inputs_before']:
        body=payload(item);p=pathlib.PurePosixPath(item['path'])
        if p.is_relative_to(str(MATERIALIZED)):
            relative=p.relative_to(str(MATERIALIZED)).as_posix();need(relative in entries,'unlocked SoftFloat input')
            need(body==blob(relative),'pinned source/header payload differs from Git object')
            need((MATERIALIZED/relative).read_bytes()==body,'current materialized input differs')
            pinned_inputs[relative]={'oid':entries[relative]['oid'],'sha256':sha(body),'size_bytes':len(body)}
        else:
            need(p.is_relative_to('/usr/include') or p.is_relative_to('/workspace/p06-local-host/extracted/usr/lib/gcc'),'unexpected external header root')
            need(pathlib.Path(p).read_bytes()==body,'current recorded system header differs')
            system_inputs[str(p)]={'sha256':sha(body),'size_bytes':len(body)}
    observed_symbols += [(selection['name'],s) for s in elf_symbols(output_bytes[selection['name']])]
a=archives[0]
need(a['tool_name']=='ar' and a['requested_arguments']==['crs','softfloat.a',*[x['name'] for x in selected]],'archive operation differs')
need(a['arguments']==a['requested_arguments'] and a['children'][0]['argv']==[a['tool']['path'],*a['arguments']],'archive child argv differs')
need(len(a['children'])==1 and a['children'][0]['stage']=='tool','archive child population differs')
need(a['started_ns']>=max(row['finished_ns'] for row in compiles),'archive started before compilation finished')
need([x['path'] for x in a['inputs_before']]==[str(root/s['name']) for s in selected],'archive ordered input list differs')
for item,selection in zip(a['inputs_before'],selected):
    need(payload(item)==output_bytes[selection['name']],'archive input differs from compile output')
archive=output_bytes['softfloat.a'];need(archive[:8]==b'!<arch>\n','not an ordinary archive')
offset=8;headers=[]
while offset<len(archive):
    h=archive[offset:offset+60];need(len(h)==60 and h[58:60]==b'`\n','archive header malformed');size=int(h[48:58]);body=archive[offset+60:offset+60+size];need(len(body)==size,'archive member truncated');headers.append((offset,h[:16].rstrip().decode(),body));offset+=60+size+(size%2)
need(offset==len(archive),'archive padding/length mismatch')
long=next((body for _,name,body in headers if name=='//'),b'');members=[];offset_names={};symbol_table=[]
for off,name,body in headers:
    if name in ('/','//'):continue
    if name.startswith('/'):
        n=int(name[1:]);end=long.index(b'/\n',n);name=long[n:end].decode()
    else:need(name.endswith('/'),'unsupported archive member');name=name[:-1]
    need(name not in offset_names.values(),'duplicate archive member')
    members.append(name);offset_names[off]=name;need(body==output_bytes[name],'archive member differs from compiled object')
need(members==[x['name'] for x in selected],'archive ordered members differ from pinned recipe')
index=[body for _,name,body in headers if name=='/'];need(len(index)==1,'archive symbol index missing/duplicate')
body=index[0];count=int.from_bytes(body[:4],'big');need(4*(count+1)<=len(body),'truncated archive symbol index');namebytes=body[4*(count+1):];names=namebytes.split(b'\0');need(all(names[:count]),'empty indexed symbol')
for n in range(count):
    off=int.from_bytes(body[4+4*n:8+4*n],'big');need(off in offset_names,'index offset outside object');symbol_table.append((offset_names[off],names[n].decode()))
need(collections.Counter(symbol_table)==collections.Counter(observed_symbols),'archive index differs from ELF-defined global symbols')
log=(PACKET/'logs/softfloat.log').read_bytes();report_body=(PACKET/'report.json').read_bytes();report=json.loads(report_body);outer=next(c for c in report['commands'] if c['id']=='softfloat')
need(outer['outcome']=='pass' and outer['exit_code']==0 and outer['cleanup_complete'] is True,'SoftFloat outer command did not pass')
need((sha(log),len(log))==(outer['log_sha256'],outer['log_size_bytes']),'outer command log identity differs')
need(sum(b'--tool gcc --role compile -- ' in line for line in log.splitlines())==309,'log compilation population differs')
need(sum(b'--tool ar --role archive -- ' in line for line in log.splitlines())==1,'log archive population differs')
initial=next(c for c in report['stability_checks'] if c['label']=='sources-frozen')['sources']
need(initial['generated_files']==0 and initial['generated_bytes']==0,'source freeze contains generated products')
staged=SOURCE/'third_party/softfloat/build/Linux-x86_64-GCC/softfloat.a'
staging={'observed':staged.exists()}
if staged.exists():
    need(staged.read_bytes()==archive,'staged archive bytes differ');staging.update(file_id(staged));product=report.get('products',{}).get('softfloat')
    if product:
        need(product['sha256']==sha(archive) and product['size_bytes']==len(archive) and product['staged_path']==str(staged),'staged product receipt differs');staging['receipt_join']=True
    else:staging['receipt_join']=False
for name,body in record_bytes.items():need((PACKET/'records'/name).read_bytes()==body,'reviewed recorder changed')
need((PACKET/'tool-config.json').read_bytes()==config_body,'config changed during review')
need((PACKET/'logs/softfloat.log').read_bytes()==log,'SoftFloat log changed during review')
need(pathlib.Path(a['output_path']).read_bytes()==archive,'archive changed during review')
result={'schema_version':1,'reviewer':'w05_a02','review_scope':'Actual completed SoftFloat compilation/archive subgraph; separate from full dependency/native acceptance','reviewed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'outcome':'pass','findings':[],'source_revision':REV,'softfloat_revision':PIN,'softfloat_tree':TREE,'makefile_sha256':sha(makefile.encode()),'makefile_groups':groups,'compile_records':len(compiles),'archive_records':len(archives),'successful_children':children,'all_outputs_absent_before':True,'exact_compile_flags':prefix,'pinned_input_files':len(pinned_inputs),'pinned_input_bytes':sum(x['size_bytes'] for x in pinned_inputs.values()),'selected_system_header_files':len(system_inputs),'recorded_input_occurrences':sum(len(x['inputs_before']) for x in compiles),'elf_objects':len(compiles),'elf_architecture':'ELF64 little-endian x86-64 ET_REL','defined_external_symbols':len(observed_symbols),'archive_index_symbols':count,'archive':{'sha256':sha(archive),'size_bytes':len(archive),'members':len(members),'member_order_matches_pinned_recipe':True,'member_bytes_match_compile_outputs':True,'symbol_index_matches_elf_definitions':True},'staging':staging,'outer_command':{'duration_seconds':outer['duration_seconds'],'peak_rss_bytes':outer['peak_rss_bytes'],'log_sha256':sha(log),'log_size_bytes':len(log),'exit_code':outer['exit_code']},'config_sha256':sha(config_body),'recorder_sha256':sha(recorder),'reviewed_record_set_sha256':sha(b''.join(name.encode()+b'\0'+hashlib.sha256(body).digest() for name,body in sorted(record_bytes.items()))),'report_snapshot':{'sha256':sha(report_body),'size_bytes':len(report_body),'state':report['state'],'outcome':report['outcome'],'reason':report['reason']},'all_reviewed_record_config_log_archive_bytes_stable':True,'retained_code_commands_or_binaries_executed':False,'new_build_or_compiler_execution':False,'duration_seconds':round(time.monotonic()-start,6),'limitations':['Independent recorded-data and current-byte consistency is not producer authentication or proof against malicious concurrent writers.','Only recorded selected system headers are rehashed; no complete host compiler or system-library provenance is asserted.','Full dependency build, model linkage, loaded-library identity, native population and all qualification/acceptance gates require their separate evidence.'],'pinned_inputs_identity_sha256':sha(json.dumps(pinned_inputs,sort_keys=True,separators=(',',':')).encode()),'selected_system_headers_identity_sha256':sha(json.dumps(system_inputs,sort_keys=True,separators=(',',':')).encode())}
OUTPUT.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n');print(json.dumps({k:v for k,v in result.items() if k not in ('pinned_inputs','selected_system_headers')},indent=2))
