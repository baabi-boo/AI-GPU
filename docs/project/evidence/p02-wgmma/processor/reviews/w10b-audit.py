#!/usr/bin/env python3
"""Independent read-only publication integrity audit; does not import exporter code."""
from pathlib import Path, PurePosixPath
from collections import Counter
from datetime import datetime, timezone
import fnmatch
import gzip
import hashlib
import io
import json
import os
import re
import stat
import subprocess

ROOT = Path('${WORK}/..')
WORK = ROOT / 'ai-gpu-work'
STAGE = WORK / 'publication-staging'
LIMITS = dict(compressed_bundle_bytes=4194304, expanded_bundle_bytes=100663296,
              member_bytes=16777216, members=4096, total_original_bytes=67108864,
              total_published_bytes=67108864)
COMPONENTS = ('processor-core', 'processor-artifacts', 'processor-historical-verifier', 'compiler-recovery-v2')
EXPECTED = {
    'processor-core': '0c3b7ac77f5993a50ffb570f952088c73239e21292510ca5be0cca44fdd8d864',
    'processor-artifacts': '14cf02356dfbba42f157e2ff6e31d820efe7dd40cbb95901cbb0745f79cba7ef',
    'processor-historical-verifier': 'ffc1862caf5d311e358228bb380da3da5d7b73f74b48781caac9846ea0dca344',
    'compiler-recovery-v2': 'd293fe7f7ccb0479d9090338fddfa5daae664381d8f5ae19e5bf1756b48983b4',
}
RULES = sorted([(str(WORK), '${WORK}'), (str(ROOT/'AI-GPU'), '${SOURCE}'),
                (str(WORK/'tools'), '${TOOLS}'), (str(ROOT), '${WORK}/..')],
               key=lambda x: (-len(x[0]), x[0]))
HASH = re.compile(r'[a-f0-9]{64}\Z')
TOKENS = re.compile(r'(?<![A-Fa-f0-9])(?:[a-f0-9]{64}|[a-f0-9]{40})(?![A-Fa-f0-9])')
observed = {}


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read(path, cap=LIMITS['member_bytes']):
    path = Path(path)
    check(all(not x.is_symlink() for x in (path, *path.parents)), 'symlink: ' + str(path))
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        check(stat.S_ISREG(before.st_mode) and before.st_size <= cap, 'type/size: '+str(path))
        with os.fdopen(os.dup(fd), 'rb') as f:
            data = f.read(cap+1)
        after = os.fstat(fd)
        key = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        check(key(before) == key(after) and len(data) == before.st_size, 'changed read: '+str(path))
        identity = (digest(data), len(data))
        if str(path) in observed:
            check(observed[str(path)] == identity, 'changed between reads: '+str(path))
        observed[str(path)] = identity
        return data
    finally:
        os.close(fd)


def pairs(items):
    d = {}
    for k,v in items:
        check(k not in d, 'duplicate JSON key: '+k)
        d[k] = v
    return d


def parse(data):
    return json.loads(data, object_pairs_hook=pairs,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))


def load(path):
    return parse(read(path))


def normalize(text):
    counts = {}
    for before, after in RULES:
        text, n = re.subn(re.escape(before)+r'(?=$|[^A-Za-z0-9_.+\-])', lambda m: after, text)
        if n:
            counts[after] = n
    check(all(a not in text for a,b in RULES), 'unhandled prefix')
    return text, counts


def identity_record(path):
    data = read(path)
    return dict(path=str(path.relative_to(WORK)), sha256=digest(data), size_bytes=len(data))


def check_binding_record(record, path):
    raw = read(path)
    check(digest(raw) == record['sha256'] and len(raw) == record['size_bytes'], 'identity record '+str(path))
    return raw


def embedded_bindings(originals):
    good, external, historical = set(), set(), []
    rules = [('log','log_sha256','log_size_bytes'), ('path','sha256','size_bytes'),
             ('snapshot','sha256','size_bytes'), ('source','source_sha256',None),
             ('record','record_sha256',None)]
    def visit(node, owner):
        if isinstance(node, list):
            for x in node:
                visit(x, owner)
        elif isinstance(node, dict):
            for pk,hk,sk in rules:
                p,h = node.get(pk), node.get(hk)
                if not isinstance(p,str) or not isinstance(h,str) or not HASH.fullmatch(h):
                    continue
                candidates = [p] if os.path.isabs(p) else [str(Path(owner).parent/p),str(WORK/p)]
                matches = {os.path.normpath(x) for x in candidates if os.path.normpath(x) in originals}
                if pk == 'path' and node.get('live_file_snapshot_only') is True:
                    target = sorted(matches)[0] if matches else None
                    historical.append(dict(record=str(Path(owner).relative_to(WORK)),
                        target_member=str(Path(target).relative_to(WORK)) if target else None,
                        observed_sha256=h, selected_original_sha256=digest(originals[target]) if target else None,
                        meaning='historical live-file observation; not a binding to current bytes'))
                elif not matches:
                    external.add((owner,pk,p,h))
                else:
                    check(len(matches)==1, 'ambiguous binding '+owner)
                    target=next(iter(matches)); raw=originals[target]
                    check(digest(raw)==h, 'embedded digest mismatch '+owner+' => '+target)
                    if sk and sk in node:
                        check(node[sk]==len(raw), 'embedded size mismatch '+owner)
                    good.add((owner,pk,target,h))
            for x in node.values():
                visit(x, owner)
    for owner,raw in originals.items():
        if owner.endswith('.json'):
            visit(parse(raw), owner)
    return dict(recognized_original_bindings_verified=len(good),
                recognized_external_or_excluded_bindings_not_verified=len(external),
                historical_live_file_observations=historical)


results={}; all_members={}; union={}; union_originals={}; counts=Counter()
for name in COMPONENTS:
    base=STAGE/name
    inv=load(base/'inventory.json')
    compressed=read(base/'evidence-bundle.json.gz', LIMITS['compressed_bundle_bytes'])
    check(digest(compressed)==EXPECTED[name]==inv['bundle_sha256'], 'bundle pin '+name)
    check(len(compressed)==inv['bundle_size_bytes'], 'compressed bytes '+name)
    check(compressed[:8]==b'\x1f\x8b\x08\x00\0\0\0\0', 'gzip header '+name)
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as f:
        expanded=f.read(LIMITS['expanded_bundle_bytes']+1)
    check(len(expanded)<=LIMITS['expanded_bundle_bytes'], 'expanded cap '+name)
    check(digest(expanded)==inv['uncompressed_bundle_sha256'] and len(expanded)==inv['uncompressed_bundle_size_bytes'], 'expanded identity '+name)
    bundle=parse(expanded)
    check(bundle['schema_version']==1 and bundle['format']=='normalized-text-evidence-v2', 'format '+name)
    check(bundle['limits']==LIMITS and inv['limits']==LIMITS, 'changed caps '+name)
    check(bundle['acceptance_claimed'] is False and not inv['deferred_inputs'] and not inv['missing_required_inputs'], 'unready or claims '+name)
    for key,value in bundle.items():
        if key!='files':
            check(inv[key]==value,'bundle/inventory '+key)
    members=bundle['files']; names=[x['path'] for x in members]
    check(names==sorted(set(names)) and len(names)==inv['file_count']<=LIMITS['members'], 'names '+name)
    check([{k:v for k,v in x.items() if k!='content'} for x in members]==inv['files'],'metadata '+name)
    selection=inv['selection']; check(len(selection['inputs'])<=256,'selector cap '+name)
    for group,patterns in selection['required_groups'].items():
        check(any(fnmatch.fnmatchcase(n,p) for n in names for p in patterns), 'missing group '+group)
    for inp in selection['inputs']:
        if inp.get('required'):
            check(any(n==inp['path'] or n.startswith(inp['path']+'/') for n in names),'empty required '+inp['path'])
    originals={}; sums=Counter(); subst=Counter(); tokens=0
    for m in members:
        p=m['path']; parts=PurePosixPath(p).parts
        check(not p.startswith('/') and '\\' not in p and all(x not in ('','.','..') for x in p.split('/')), 'unsafe member '+p)
        check(all(ord(x)>=32 for x in p),'control in path')
        check(any(p==s['path'] or p.startswith(s['path']+'/') for s in selection['inputs']),'unselected '+p)
        check(not any(fnmatch.fnmatchcase(p,x) for x in selection['exclude']),'explicitly excluded '+p)
        raw=read(WORK/p); pub=m['content'].encode('utf-8')
        check(m['encoding']=='utf-8' and len(raw)==m['original_size_bytes'] and digest(raw)==m['original_sha256'],'original '+p)
        check(len(pub)==m['published_size_bytes']<=LIMITS['member_bytes'] and digest(pub)==m['published_sha256'],'published '+p)
        normalized, substitutions=normalize(raw.decode('utf-8'))
        check(normalized==m['content'] and substitutions==m['substitutions'],'normalization '+p)
        raw_tokens=TOKENS.findall(raw.decode('utf-8'))
        check(raw_tokens==TOKENS.findall(m['content']),'embedded identity mutation '+p)
        tokens+=len(raw_tokens); subst.update(substitutions)
        sums['original']+=len(raw); sums['published']+=len(pub); sums['changed']+=raw!=pub
        originals[str(WORK/p)]=raw
        if p in all_members:
            check(all_members[p]==m,'cross-component member mutation '+p)
        all_members[p]=m; counts[p]+=1
        if name!='compiler-recovery-v2':
            union[p]=m; union_originals[str(WORK/p)]=raw
    check(sums['original']==inv['original_total_bytes']<=LIMITS['total_original_bytes'],'original aggregate '+name)
    check(sums['published']==inv['published_text_bytes']<=LIMITS['total_published_bytes'],'published aggregate '+name)
    binding=embedded_bindings(originals)
    check(binding==inv['binding_audit'],'binding audit '+name)
    index=load(base/'component-index.json')
    check(index['limits']==LIMITS,'index caps '+name)
    claims=index.get('claims',index)
    for k in ['acceptance_claimed','phase_complete','qualifies_P02_A03']:
        check(claims[k] is False,'export claims '+name+':'+k)
    for a in index['artifacts']:
        target=base/a['path'] if name!='compiler-recovery-v2' else WORK/a['path']
        check_binding_record(a,target)
    if name!='compiler-recovery-v2':
        check(load(base/'selection.json')==selection,'selection copy '+name)
        receipt_original=read(STAGE/'processor-control'/(name.removeprefix('processor-')+'-verification-receipts-original.json'))
        receipt_published=read(base/'verification-receipts.json')
        v=index['verification']
        check(digest(receipt_original)==v['receipt_original_sha256'] and len(receipt_original)==v['receipt_original_size_bytes'],'receipt original')
        normalized,ns=normalize(receipt_original.decode())
        check(normalized.encode()==receipt_published and ns==v['receipt_substitutions'],'receipt normalization')
        check(digest(receipt_published)==v['receipt_published_sha256'],'receipt published')
        r=parse(receipt_original)
        check(len(r['commands'])==4 and all(x['exit_code']==0 and not x['stderr'] for x in r['commands']),'four export commands')
        plan=load(STAGE/(name+'-plan.json'))
        check(plan['bundle_sha256']==digest(compressed),'plan/build identity')
    results[name]=dict(bundle=identity_record(base/'evidence-bundle.json.gz'),inventory=identity_record(base/'inventory.json'),
        component_index=identity_record(base/'component-index.json'),members=len(members),expanded_bytes=len(expanded),
        original_bytes=sums['original'],published_bytes=sums['published'],changed_members=sums['changed'],
        unchanged_members=len(members)-sums['changed'],substitutions=dict(subst),embedded_identity_tokens_preserved=tokens,
        selectors=len(selection['inputs']),binding_audit=binding)

check(digest(read(WORK/'package_wgmma_evidence.py'))=='591a5e769f318a1889a4de2706238c3ab1b82156fe97a5c9e0d803495b0ec8cd','exporter changed')
u=load(STAGE/'processor-union-coverage.json')
check(set(union)=={x['path'] for x in u['members']},'union member set')
for x in u['members']:
    check(all(union[x['path']][k]==x[k] for k in ['original_sha256','original_size_bytes','published_sha256','published_size_bytes']),'union metadata')
check(len(union)==u['actual_unique_members'],'union count')
check(sum(results[n]['members'] for n in COMPONENTS[:3])==u['component_member_total'],'component total')
check(sum(x['original_size_bytes'] for x in union.values())==u['unique_original_total_bytes'],'union original total')
check(sum(x['published_size_bytes'] for x in union.values())==u['unique_published_total_bytes'],'union published total')
union_binding=embedded_bindings(union_originals)
check(union_binding==u['binding_audit_on_original_union'],'union binding audit')
check(not u['missing_desired_members'] and not u['original_identity_mismatches'],'desired union misses')
for r in u['desired_source_manifests']:
    check(digest(read(STAGE/r['path']))==r['sha256'],'desired manifest identity')
desired={}
allow_suffix=set('.json .log .txt .md .csv .tsv .yaml .yml .py .sh .h .hpp .c .cc .cpp .sv .v .vh .mk .in .toml .stamp .d .vlt .s .diff .patch .map .list .cfg .ini .dat'.split())
allow_names={'Makefile','makefile','configure','VERSION','LICENSE','COPYING'}
for short in ['full','historical-verifier']:
    selection_path=WORK/'publication-drafts'/('processor-'+short+'-selection.json')
    selection=load(selection_path)
    snapshot=load(STAGE/'processor-control'/(short+'-desired-members.json'))
    check(digest(read(selection_path))==snapshot['selection_sha256'],'desired selector identity')
    enumerated=set()
    # These selectors contain only two bounded evidence/input directories (one in
    # the historical component); neither contains tool/cache/build-tree roots.
    for s in selection['inputs']:
        p=WORK/s['path']; check(p.exists(),'missing desired selector '+s['path'])
        candidates=[x for x in p.rglob('*') if x.is_file()] if p.is_dir() else [p]
        for q in candidates:
            rel=str(q.relative_to(WORK))
            if any(fnmatch.fnmatchcase(rel,x) for x in selection['exclude']):
                continue
            if q.suffix.lower() not in allow_suffix and q.name not in allow_names and not q.name.endswith('-Makefile'):
                continue
            enumerated.add(rel)
    check(enumerated=={x['path'] for x in snapshot['members']},'independent desired enumeration '+short)
    check(len(enumerated)==snapshot['file_count'],'desired snapshot count')
    for m in snapshot['members']:
        check(m['path'] in union,'desired member absent '+m['path'])
        check(all(m[k]==union[m['path']][k] for k in ['original_sha256','original_size_bytes']),'desired identity '+m['path'])
        desired[m['path']]=m
check(len(desired)==u['desired_unique_members']==1236,'desired deduplicated count')
check(set(union)-set(desired)==set(u['additional_packaging_selection_members']),'unexpected union extras')

formal=WORK/'wgmma-gcc12-formal-evidence'
formal_files={str(p.relative_to(WORK)):p for p in formal.rglob('*') if p.is_file()}
direct=set(formal_files)&set(union); missing=set(formal_files)-direct
copy_map=load(WORK/'publication-drafts/processor-inputs/source-copy-map.json')
copy_count=0; committed_copies=0
for c in copy_map['copies']:
    a,b=c['original'],c['copy']
    original=check_binding_record(a,Path(a['path'])); copied=check_binding_record(b,Path(b['path']))
    check(original==copied and c['byte_identical'] is True,'source copy')
    copy_count+=1
    if 'committed_revision' in c:
        blob=subprocess.check_output(['git','-C',str(WORK/'verifier-candidate'),'show',c['committed_revision']+':'+c['repository_path']])
        check(blob==copied,'committed source copy '+c['repository_path']); committed_copies+=1
mapped=[x for x in copy_map['copies'] if x['original']['path']==str(formal/'artifacts/source/.gitmodules')]
check(len(mapped)==1,'gitmodules mapping')
mapped_name='wgmma-gcc12-formal-evidence/artifacts/source/.gitmodules'
check(mapped_name in missing and str(Path(mapped[0]['copy']['path']).relative_to(WORK)) in union,'mapped body absent')
missing.remove(mapped_name)
report=load(formal/'report.json')
check(digest(read(formal/'report.json'))=='b5b136bb3144613d7c32c47a888f744e864d9dab737c19e954f9da7dabcadb78','final report pin')
retained={('wgmma-gcc12-formal-evidence/'+a['path']):a for v in report['variants'] for a in v['retained_artifacts']}
omissions=[]
for p in sorted(missing):
    check(Path(p).name in ('kernel.elf','kernel.vxbin','p02_wgmma'),'unexplained omitted formal body '+p)
    raw=check_binding_record(retained[p],WORK/p)
    omissions.append(dict(path=p,sha256=digest(raw),size_bytes=len(raw),recorded_in_report=True,body_in_export=False))
check(len(missing)==36,'binary omission count')
check(len(formal_files)==1103 and len(direct)==1066,'formal coverage counts')
check(set(missing)=={x['path'] for x in u['formal_packet_coverage']['identity_only_omitted_binary_bodies']},'omission receipt set')
for x in u['formal_packet_coverage']['identity_only_omitted_binary_bodies']:
    raw=read(WORK/x['path']); check(digest(raw)==x['original_sha256'] and len(raw)==x['original_size_bytes'],'omission receipt identity')
formal_logs={str(p.relative_to(WORK)) for p in (formal/'logs').iterdir() if p.is_file()}
check(len(formal_logs)==113 and formal_logs<=direct,'formal logs missing')
review_names={str(p.relative_to(WORK)) for p in (WORK/'reviews').iterdir() if p.is_file() and re.match(r'w0[1-8]',p.name) and p.suffix in ('.md','.json','.log','.py','.txt')}
check(review_names<=set(union),'W01-W08 review omission: '+str(review_names-set(union)))
resolution=load(WORK/'publication-drafts/processor-inputs/review-log-resolution.json')
resolution_rows=resolution.get('resolutions',resolution.get('references',[]))
if not resolution_rows:
    resolution_rows=next(x for x in resolution.values() if isinstance(x,list) and x and isinstance(x[0],dict))
for x in resolution_rows:
    target=x['resolved_selected_original']; check_binding_record(target,Path(target['path']))
    check(str(Path(target['path']).relative_to(WORK)) in union,'resolved log unselected')
    check(target['sha256']==x['recorded_original_sha256'],'resolved digest')
    if x.get('recorded_original_size_bytes') is not None:
        check(target['size_bytes']==x['recorded_original_size_bytes'],'resolved size')
    check(not (WORK/x['unresolved_literal_path']).exists(),'alias unexpectedly exists')
check(len(resolution_rows)==54 and not resolution['unresolved'],'relative log resolution')

failed=load(WORK/'wgmma-formal-evidence/report.json')
check(failed['state']=='finished' and failed['outcome']=='fail' and failed['verified_launches']==0 and failed['checked_output_words']==0,'compiler failure erased')
check(all(failed[k]=='not_run' for k in ('arithmetic_outcome','witness_outcome','parity_outcome')),'failed run upgraded')
check('wgmma-formal-evidence/report.json' in all_members,'failed report omitted')
partial=load(WORK/'reviews/w09a-report-partial.json')
check(partial['state']=='running' and digest(read(WORK/'reviews/w09a-report-partial.json'))=='dd60b9a2037d34b72b407612e89cbf7f4ced3e5dca208c0828e24e1ec23b6ad2','historical partial report changed')
check('reviews/w09a-report-partial.json' in union and 'reviews/w09a-initial-failure.json' in union,'historical verifier failure omitted')
for p in (WORK/'host-compat').iterdir():
    if p.is_file(): check(str(p.relative_to(WORK)) in all_members,'host compatibility omission '+str(p))
old=WORK/'publication-drafts/processor-historical-verifier-inputs/historical-verifier/p02_wgmma_packet.py'
new=WORK/'publication-drafts/processor-inputs/verifier/p02_wgmma_packet.py'
check(digest(read(old))=='ce33df0111d33cbb22a4f6c2360b0b1da7fb7c8063db66b98e081d310069c0a4','old verifier identity')
check(digest(read(new))=='11497b57db50c4c1e690d38c406d0de94f86b2017cec036f7ed79008151e72a4','corrected verifier identity')
historical_copies=load(WORK/'publication-drafts/processor-historical-verifier-inputs/source-copy-map.json')
for c in historical_copies['copies']:
    copied=check_binding_record(c['copy'],Path(c['copy']['path']))
    if c.get('source_is_git_object_not_current_worktree'):
        source_bytes=subprocess.check_output(['git','-C',str(WORK/'verifier-candidate'),'show',c['committed_revision']+':'+c['repository_path']])
        check(digest(source_bytes)==c['original']['sha256'] and len(source_bytes)==c['original']['size_bytes'],'historical git object identity')
    else:
        source_bytes=check_binding_record(c['original'],Path(c['original']['path']))
    check(copied==source_bytes,'historical source copy bytes')
failed_files={str(p.relative_to(WORK)) for p in (WORK/'wgmma-formal-evidence').rglob('*') if p.is_file()}
failed_missing=failed_files-set(all_members)
check(len(failed_files)==61 and failed_missing=={'wgmma-formal-evidence/artifacts/source/.gitmodules'},'failed packet coverage')
failed_map=load(WORK/'publication-drafts/compiler-recovery-source-inputs/source-copy.json')
check(read(WORK/failed_map['original_path'])==read(WORK/failed_map['copy_path']),'failed source mapped bytes')
check(failed_map['copy_path'] in all_members,'failed source copy missing')
compiler_context=load(WORK/'publication-drafts/compiler-recovery-inputs/component-context.json')
for c in compiler_context['verbatim_metadata_copies']:
    original=read(WORK/c['original']); copied=read(WORK/c['copy'])
    check(original==copied and digest(original)==c['sha256'] and len(original)==c['size_bytes'],'compiler metadata copy')
    check(c['copy'] in all_members,'compiler metadata copy unselected')
check(any('signature validation was not performed' in s for s in compiler_context['limitations']),'unsigned metadata limit lost')
aggregate=load(STAGE/'processor-component-index.json')
check(aggregate['unchanged_limits']==LIMITS,'aggregate caps')
check(aggregate['acceptance_claimed'] is False and aggregate['phase_complete'] is False and aggregate['qualifies_P02_A03'] is False,'aggregate acceptance')
check_binding_record(aggregate['union_coverage'],STAGE/aggregate['union_coverage']['path'])
for c in aggregate['components']:
    check_binding_record(c['index'],STAGE/c['index']['path'])
failed_plan=load(STAGE/'processor-control/full-plan-command.json')
check(failed_plan['exit_code']==1 and parse(failed_plan['stderr'])['error']=='compressed-bundle limit exceeded','full plan failure lost')
check(not (STAGE/'processor-full-plan.json').exists(),'failed plan unexpectedly exists')
check(parse(normalize(json.dumps(failed_plan))[0])==aggregate['full_selection_plan_failure'],'full plan receipt normalization')

# Final read-through catches writers changing anything this audit consumed.
baseline=dict(observed)
for p, expected in baseline.items():
    raw=read(Path(p)); check((digest(raw),len(raw))==expected,'end stability '+p)
output=dict(schema_version=1, reviewer='/root/w10b_publication_integrity', outcome='pass',
    completed_at=datetime.now(timezone.utc).isoformat(),
    scope='Independent bounded text publication integrity, preservation, normalization and original-directory union coverage; no independent numerical rerun or canonical acceptance decision.',
    exporter_imported_or_executed=False, compiler_build_or_test_suite_executed=False,
    caps=LIMITS, components=results,
    processor_union=dict(unique_members=len(union),component_member_total=u['component_member_total'],
        original_bytes=u['unique_original_total_bytes'],published_bytes=u['unique_published_total_bytes'],
        binding_audit=union_binding, inventory=identity_record(STAGE/'processor-union-coverage.json')),
    all_four_components=dict(member_occurrences=sum(results[n]['members'] for n in COMPONENTS),
        unique_members=len(all_members),duplicate_paths=[p for p,n in sorted(counts.items()) if n>1]),
    formal_coverage=dict(original_files=len(formal_files),direct_original_named_text_bodies=len(direct),
        mapped_gitmodules_bodies=1,command_logs=len(formal_logs),identity_only_binaries=omissions,
        identity_only_binary_bytes=sum(x['size_bytes'] for x in omissions),all_text_bodies_retained=True),
    source_copies=dict(total=copy_count,committed_current_verifier_sources=committed_copies,
        historical_copies=len(historical_copies['copies']),compiler_metadata_copies=len(compiler_context['verbatim_metadata_copies'])),
    historical_preservation=dict(compiler_failure_outcome='fail',compiler_failure_launches=0,
        partial_verifier_report_state='running',partial_verifier_report_sha256=digest(read(WORK/'reviews/w09a-report-partial.json')),
        w01_w08_review_members=len(review_names),relative_review_log_resolutions=len(resolution_rows),
        original_failed_packet_files=len(failed_files),original_failed_packet_mapped_bodies=1,
        full_selection_compressed_cap_failure_preserved=True,desired_members_independently_enumerated=len(desired)),
    final_stability_file_count=len(baseline), component_index=identity_record(STAGE/'processor-component-index.json'),
    findings=[], acceptance_claimed=False, phase_complete=False,
    limitations=['Excluded binary, compiler, dependency and runtime bodies remain identities only.',
        'Published normalized archives are not accepted inputs to the original-location packet-verifier CLI.',
        'Digest identity is not digital signature or origin authentication; GCC12 InRelease signature verification remains unperformed.',
        'Historical unit and processor scopes, dense NRC16 RS forced pressure and auxiliary counter limits remain separate.',
        'P01-A03 remains blocked; this review supplies publication integrity for a separate P02-A03 acceptance decision.'])
(WORK/'reviews/w10b-data.json').write_text(json.dumps(output,indent=2,sort_keys=True)+'\n')
print(json.dumps({k:output[k] for k in ['outcome','processor_union','all_four_components','final_stability_file_count','source_copies']},indent=2))
