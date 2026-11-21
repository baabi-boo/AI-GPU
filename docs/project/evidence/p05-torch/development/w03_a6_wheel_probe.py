from pathlib import Path
import email, hashlib, importlib.util, json, sys, tempfile, zipfile
from packaging.requirements import Requirement
from packaging.markers import default_environment
from packaging.utils import canonicalize_name
root=Path(__file__).resolve().parent.parent/'AI-GPU'
work=root.parent/'p05-torch-work'
manifest=json.loads((root/'ci/project/p05_torch_contract.json').read_text())
wheels=work/'wheelhouse'
env=default_environment()
env.update(python_version='3.12',python_full_version='3.12.14',implementation_name='cpython',platform_python_implementation='CPython',sys_platform='linux',platform_system='Linux',platform_machine='x86_64',extra='')
locked={canonicalize_name(row['name']):row for row in manifest['wheels']}
rows=[]
assert set(p.name for p in wheels.iterdir())==set(row['filename'] for row in locked.values())
for name,row in locked.items():
    path=wheels/row['filename'];h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    assert h.hexdigest()==row['sha256'] and path.stat().st_size==row['size']
    with zipfile.ZipFile(path) as z:
        all_metadata=[i for i in z.namelist() if i.endswith('.dist-info/METADATA')]
        names=[i for i in all_metadata if len(i.split('/'))==2]
        assert len(names)==1
        md=email.message_from_bytes(z.read(names[0]))
        assert canonicalize_name(md['Name'])==name and md['Version']==row['version']
        active=[]
        for text in md.get_all('Requires-Dist',[]):
            req=Requirement(text)
            if req.marker is not None and not req.marker.evaluate(env): continue
            key=canonicalize_name(req.name)
            assert key in locked,(name,text)
            assert locked[key]['version'] in req.specifier,(name,text,locked[key]['version'])
            active.append(text)
    rows.append({'name':name,'version':row['version'],'wheel_sha256':h.hexdigest(),'size_bytes':path.stat().st_size,'active_dependencies':active,'vendored_metadata_count':len(all_metadata)-1})
result={'scope':'read-only-framework-wheel-closure','outcome':'pass','wheel_count':len(rows),'wheel_bytes':sum(row['size_bytes'] for row in rows),'lock_sha256':hashlib.sha256((root/'ci/project/p05_torch_requirements.lock').read_bytes()).hexdigest(),'environment':env,'wheels':rows}
assert result['lock_sha256']==manifest['requirements']['sha256']
(work/'w03_a6-wheel-closure.json').write_text(json.dumps(result,indent=2)+'\n')
sys.path.insert(0,str(root/'ci/project'))
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module
    spec.loader.exec_module(module);return module
original_path=work/'w03_a6_original_p05_torch_execute.py'
if not original_path.exists():
    source=(root/'ci/project/p05_torch_execute.py').read_bytes()
    assert hashlib.sha256(source).hexdigest()=='50aefed73bdd6b550079ecf3b68b3615c7e6667755c7e0781ec1c8477a7962d3'
    original_path.write_bytes(source)
original=load('w03_a6_original',original_path)
corrected=load('w03_a6_corrected',work/'drafts/w03_a6_p05_torch_execute.py')
probes={}
for label,module in [('original',original),('corrected',corrected)]:
    payload,scripts=module._wheel_payload(wheels/'setuptools-84.2.1-py3-none-any.whl')
    probe={'setuptools_scripts':scripts,'immutable_payload_files':len(payload)}
    def accepted(action):
        with tempfile.TemporaryDirectory(prefix='w03-a6-vendor-',dir=work) as temp:
            venv=Path(temp);site=venv/module.SITE
            top=site/'demo-1.dist-info/RECORD';nested=site/'demo/_vendor/helper-1.dist-info/RECORD'
            for path in (top,nested):path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'original\n')
            expected=module._installation_tree(venv)
            if action=='nested-record':nested.write_bytes(b'changed vendor inventory\n')
            elif action=='nested-installer':(nested.parent/'INSTALLER').write_bytes(b'pip\n')
            elif action=='top-level-record':top.write_bytes(b'installed inventory\n');(top.parent/'INSTALLER').write_bytes(b'pip\n')
            try:module._installed_inventory(venv,expected,[],[])
            except ValueError:return False
            return True
    for action in ('nested-record','nested-installer','top-level-record'):
        probe[action+'_accepted']=accepted(action)
    probes[label]=probe
assert probes['original']['setuptools_scripts']==['bin/wheel']
assert probes['corrected']['setuptools_scripts']==[]
assert probes['original']['nested-record_accepted'] is True
assert probes['corrected']['nested-record_accepted'] is False
assert probes['original']['nested-installer_accepted'] is True
assert probes['corrected']['nested-installer_accepted'] is False
assert probes['corrected']['top-level-record_accepted'] is True
probes.update(scope='host-only-package-metadata-validation',actual_pinned_venv_wheel_script_exists=(work/'torch-venv/bin/wheel').exists())
(work/'w03_a6-vendored-metadata-probe.json').write_text(json.dumps(probes,indent=2)+'\n')
print(json.dumps({'closure':{'outcome':'pass','wheel_count':len(rows),'wheel_bytes':result['wheel_bytes'],'active_dependency_edges':sum(len(r['active_dependencies']) for r in rows)},'probes':probes},indent=2))
