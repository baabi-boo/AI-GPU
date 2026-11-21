from pathlib import Path
import hashlib, json, os, platform, re, shutil, subprocess, sys, time, traceback
sys.dont_write_bytecode = True
work = Path(__file__).resolve().parent
root = work.parent / 'AI-GPU'
sys.path.insert(0, str(root / 'ci/project'))
import p05_torch_execute as runner
output = work / 'w04_a2-install'
venv = work / 'w04_a2-venv'
assert not output.exists() and not venv.exists(), 'fresh dedicated destinations required'
output.mkdir()
(output / 'tmp').mkdir()
report = {'scope':'host-only-real-framework-dependency-installation', 'acceptance_claimed':False,
          'native_execution':'not_run', 'outcome':'running', 'commands':[],
          'python_version':platform.python_version(), 'source_revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),
          'source_dirty':True, 'source_files':[], 'free_disk_before':shutil.disk_usage(work).free}
for relative in ('ci/project/p05_torch_execute.py', runner.CONTRACT, runner.LOCK):
    raw = (root / relative).read_bytes()
    report['source_files'].append({'path':relative,'sha256':hashlib.sha256(raw).hexdigest(),'size_bytes':len(raw)})
    (output / Path(relative).name).write_bytes(raw)
with open('/proc/meminfo') as stream:
    mem = {line.split(':')[0]: int(line.split()[1])*1024 for line in stream if line.split()[1].isdigit()}
report['available_memory_before'] = mem.get('MemAvailable')
assert report['free_disk_before'] >= 11*1024**3, '10 GiB reserve plus install headroom required'
assert report['available_memory_before'] >= 1024**3, 'at least 1 GiB memory required for dependency-only check'
env = dict(runner.base.clean_environment({'work':output,'host_bin':None},1), OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MAX_JOBS='1')
env.pop('HOME',None)
def write(name,value):
    (output / name).write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')
def checkpoint():
    write('report.json',report)
def command(name,argv,timeout):
    row={'id':name,'argv':[str(x) for x in argv],'cwd':str(work),'environment':env,'timeout_seconds':timeout}
    report['commands'].append(row);checkpoint()
    start=time.monotonic()
    with (output/(name+'.log')).open('w') as stream:
        result=subprocess.run(row['argv'],cwd=work,env=env,stdout=stream,stderr=subprocess.STDOUT,timeout=timeout)
    row.update(exit_code=result.returncode,duration_seconds=time.monotonic()-start,log=name+'.log')
    checkpoint()
    assert result.returncode == 0, name+' failed'
    assert shutil.disk_usage(work).free >= 10*1024**3, 'local disk reserve fell below 10 GiB'
    return (output/(name+'.log')).read_text()
try:
    inputs=runner.bundle_producer._Inputs()
    contract,wheels=runner._contract(inputs,root,work/'wheelhouse')
    write('wheels.json',wheels)
    command('create-venv',[sys.executable,'-I','-B','-m','venv','--copies',venv],180)
    seed=runner._installation_tree(venv)
    write('seed.json',seed)
    report['seed_files']=len(seed)
    payload=[];scripts=[]
    for wheel in contract['wheels']:
        rows,entries=runner._wheel_payload(work/'wheelhouse'/wheel['filename'])
        payload.extend(rows);scripts.extend(entries)
    assert len({r['path'] for r in payload}) == len(payload)
    assert len(set(scripts)) == len(scripts)
    write('payload.json',payload);write('entry-points.json',scripts)
    report.update(payload_files=len(payload),payload_bytes=sum(row['size_bytes'] for row in payload),entry_points=scripts)
    command('install-locked-wheels',[venv/'bin/python','-I','-B','-m','pip','--isolated','install','--no-index','--find-links',work/'wheelhouse','--only-binary=:all:','--require-hashes','--no-deps','--no-compile','--no-cache-dir','--disable-pip-version-check','-r',root/runner.LOCK],300)
    before=runner._installed_inventory(venv,payload,scripts,seed)
    write('installed-before.json',before)
    report.update(installed_files=len(before),installed_bytes=sum(row['size_bytes'] for row in before),inventory_before='pass')
    checkpoint()
    pip_records=[r for r in seed if re.fullmatch(runner.SITE+r'pip-[^/]+\.dist-info/METADATA',r['path'])]
    assert len(pip_records)==1
    pip_version=pip_records[0]['path'].split('/')[-2].removeprefix('pip-').removesuffix('.dist-info')
    expected={runner._normal_name(row['name']):row['version'] for row in contract['wheels']}
    expected['pip']=pip_version
    raw=command('framework-probe',[venv/'bin/python','-I','-B','-c',runner.FRAMEWORK_PROBE,venv,json.dumps(expected,sort_keys=True,separators=(',',':'))],120)
    markers=[line.removeprefix('P05_TORCH_ENVIRONMENT ') for line in raw.splitlines() if line.startswith('P05_TORCH_ENVIRONMENT ')]
    assert len(markers)==1
    probe=json.loads(markers[0]);write('framework-probe.json',probe)
    after=runner._installed_inventory(venv,payload,scripts,seed)
    write('installed-after.json',after)
    assert after==before,'framework import changed installed bytes'
    inputs.stable()
    assert all(hashlib.sha256((root/row['path']).read_bytes()).hexdigest()==row['sha256'] for row in report['source_files'])
    report.update(outcome='pass',inventory_after='pass',torch_version=probe['torch_version'],distribution_versions={k:v['version'] for k,v in probe['distributions'].items()},framework_import_changed_files=False)
except BaseException as error:
    report.update(outcome='fail',error=type(error).__name__+': '+str(error),traceback=traceback.format_exc())
    print(report['traceback'])
finally:
    report['free_disk_after']=shutil.disk_usage(work).free
    checkpoint()
print(json.dumps({k:v for k,v in report.items() if k not in ('commands','traceback')},sort_keys=True))
raise SystemExit(0 if report['outcome']=='pass' else 1)
