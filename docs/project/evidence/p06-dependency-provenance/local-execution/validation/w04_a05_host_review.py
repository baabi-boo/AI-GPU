"""Read-only review of actual host inputs and a bounded live-build snapshot."""
import collections
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile

ROOT = Path('/workspace/p06-local-native-run-01/evidence')
BUILD = ROOT / 'dependency-build'
SOURCE = Path('/workspace/p06-local-run-source')
OUT = Path('/workspace/scratch/279b6658611e/validation/w04_a05-host-provenance.json')

def digest(body):
    return hashlib.sha256(body).hexdigest()

def read(path):
    body = path.read_bytes()
    return json.loads(body), {'path': str(path), 'sha256': digest(body), 'size_bytes': len(body)}

def identity(name):
    path = Path(name)
    resolved = path.resolve(strict=True)
    body = path.read_bytes()
    return {'path': str(path), 'resolved_path': str(resolved), 'sha256': digest(body), 'size_bytes': len(body)}

preparation, prep_identity = read(ROOT / 'dependency-preparation.json')
document, report_snapshot = read(BUILD / 'report.json')
config, config_identity = read(BUILD / 'tool-config.json')
assert preparation['outcome'] == 'pass'
assert document['tools'] == preparation['host_tools']
observed_tools = {name: identity(row['path']) for name, row in document['tools'].items()}
assert observed_tools == document['tools']
assert all(os.access(row['path'], os.X_OK) for row in observed_tools.values())
assert config['tools'] == {name: observed_tools[name] for name in ('gcc', 'g++', 'ar', 'ranlib')}
expected_path = ':'.join(['/workspace/p06-local-host/bin', str(Path(observed_tools['python3']['path']).parent), '/usr/bin', '/bin'])
assert document['environment']['PATH'] == expected_path
assert document['environment']['CCACHE_DISABLE'] == '1'
assert document['environment']['OBJCACHE'] == ''
assert document['environment']['MAKEFLAGS'] == '-j2'
assert document['environment']['CMAKE_BUILD_PARALLEL_LEVEL'] == '2'
assert document['environment']['THREADS'] == '1'
assert all(command['environment'] == document['environment'] for command in document['commands'])
assert not {'CFLAGS','CXXFLAGS','CPATH','C_INCLUDE_PATH','CPLUS_INCLUDE_PATH','COMPILER_PATH','GCC_EXEC_PREFIX','LIBRARY_PATH','LD_PRELOAD','LD_AUDIT'} & document['environment'].keys()

record_paths = sorted((BUILD / 'records').glob('*.json'))
records = []
record_ids = []
for path in record_paths:
    row, descriptor = read(path)
    if row['state'] != 'finished':
        continue
    assert row['outcome'] == 'pass' and row['exit_code'] == 0 and row['failures'] == []
    assert row['config_sha256'] == config_identity['sha256']
    assert row['tool'] == observed_tools[row['tool_name']]
    assert row['recorder'] == identity(SOURCE / 'ci/project/p06_dependency_record.py')
    assert row['environment']['PATH'] == expected_path
    assert row['environment']['CCACHE_DISABLE'] == '1' and row['environment']['OBJCACHE'] == ''
    assert all(value is None for key,value in row['environment'].items() if key not in ('PATH','CCACHE_DISABLE','OBJCACHE'))
    assert all(child['argv'][0] == row['tool']['path'] and child['process_started'] is True and child['exit_code'] == 0 for child in row['children'])
    assert row['process_started'] is True
    assert not any(arg == '-w' or arg == '-fpermissive' or arg.startswith('-Wno-error') for arg in row['arguments'])
    assert digest(path.read_bytes()) == descriptor['sha256']
    records.append(row)
    record_ids.append(descriptor)

configure = next(row for row in document['commands'] if row['id'] == 'ramulator-configure')
options = dict(value[2:].split('=', 1) for value in configure['argv'] if value.startswith('-D'))
assert options['CMAKE_CXX_COMPILER'] == observed_tools['g++']['path']
assert options['CMAKE_MAKE_PROGRAM'] == observed_tools['make']['path']
assert options['FETCHCONTENT_FULLY_DISCONNECTED'] == 'ON'
assert options['FETCHCONTENT_UPDATES_DISCONNECTED'] == 'ON'
for name in ('ARGPARSE','SPDLOG','YAML-CPP'):
    assert options['FETCHCONTENT_SOURCE_DIR_'+name] == '/workspace/p06-local-native-run-01/dependency-sources/'+name.lower()
for name, role in [('ar','archive'),('ranlib','index')]:
    expected = '#!/bin/sh\nexec '+observed_tools['python3']['path']+' '+str(SOURCE / 'ci/project/p06_dependency_record.py')+' --config '+str(BUILD / 'tool-config.json')+' --config-sha256 '+config_identity['sha256']+' --tool '+name+' --role '+role+' -- "$@"\n'
    assert (BUILD/'launchers'/f'{name}.sh').read_text() == expected

cache = Path('/workspace/p06-local-native-run-01/dependency-build/ramulator/CMakeCache.txt').read_text()
cache_entries = {}
for line in cache.splitlines():
    if '=' in line and not line.startswith(('#','//')):
        key,value = line.split('=',1)
        cache_entries[key.split(':',1)[0]] = value
assert cache_entries['CMAKE_CXX_FLAGS'] == ''
assert cache_entries['CMAKE_CXX_FLAGS_RELEASE'] == '-O3 -DNDEBUG'
assert cache_entries['FETCHCONTENT_FULLY_DISCONNECTED'] == 'ON'
assert cache_entries['FETCHCONTENT_UPDATES_DISCONNECTED'] == 'ON'
compiler_info = Path('/workspace/p06-local-native-run-01/dependency-build/ramulator/CMakeFiles/3.22.6/CMakeCXXCompiler.cmake').read_text()
assert 'set(CMAKE_CXX_COMPILER_ID "GNU")' in compiler_info
assert 'set(CMAKE_CXX_COMPILER_VERSION "12.2.0")' in compiler_info

acquisition, acquisition_id = read(Path('/workspace/p06-local-host/receipt.json'))
package_observations = []
for row in acquisition['downloads']:
    path = Path(row['path'])
    body = path.read_bytes()
    assert digest(body) == row['expected_sha256'] == row['sha256']
    assert len(body) == row['expected_size_bytes'] == row['size_bytes']
    package_observations.append({'filename':path.name,'sha256':digest(body),'size_bytes':len(body)})
driver_members = []
for name in ('gcc','g++'):
    selected = next(row for row in acquisition['downloads'] if Path(row['path']).name.startswith(name+'-12_'))
    target = 'usr/bin/x86_64-linux-gnu-'+name+'-12'
    process = subprocess.Popen(['dpkg-deb','--fsys-tarfile',selected['path']], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    found = None
    with tarfile.open(fileobj=process.stdout, mode='r|') as archive:
        for member in archive:
            if member.name.removeprefix('./') == target:
                body = archive.extractfile(member).read()
                found = {'tool':name,'package':Path(selected['path']).name,'member':member.name,'sha256':digest(body),'size_bytes':len(body)}
    assert process.wait() == 0 and process.stderr.read() == b''
    assert found and found['sha256'] == observed_tools[name]['sha256'] and found['size_bytes'] == observed_tools[name]['size_bytes']
    driver_members.append(found)

old, old_id = read(Path('/workspace/scratch/279b6658611e/validation/gcc14-dram-probe.json'))
new, new_id = read(Path('/workspace/scratch/279b6658611e/validation/gcc12-dram-probe.json'))
def normalize(args):
    result = list(args[1:])
    for flag in ('-o','-MF'):
        if flag in result:
            result[result.index(flag)+1] = '<output>'
    return result
assert old['exit_code'] != 0 and all(row['exit_code'] == 0 for row in new)
assert all(normalize(old['arguments']) == normalize(row['arguments']) for row in new)
assert all('-Werror' in row['arguments'] and '-Wall' in row['arguments'] and '-Wextra' in row['arguments'] and '-Wfatal-errors' in row['arguments'] for row in new)
yaml = Path('/workspace/p06-local-native-run-01/dependency-sources/yaml-cpp/CMakeLists.txt')
assert '$<${not-msvc}:-Wall -Wextra -Wshadow -Weffc++ -Wno-long-long>' in yaml.read_text()
yaml_manifest = next(row for row in preparation['source_manifest']['sources'] if row['name'] == 'yaml-cpp')
yaml_cmake = next(row for row in yaml_manifest['files'] if row['path'] == 'CMakeLists.txt')
assert digest(yaml.read_bytes()) == yaml_cmake['sha256'] and yaml.stat().st_size == yaml_cmake['size_bytes']

result = {
    'schema_version':1,'scope':'host inputs, actual recorder/environment snapshot; not complete build/native acceptance',
    'reviewer':'w04_a05','observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'source_revision':'ac2f2ae761c3644103278f7a41cc6ae7db734a86','outcome':'pass','blocking_findings':[],
    'preparation':prep_identity,'build_report_snapshot':report_snapshot,'build_state_at_snapshot':document['state'],
    'build_outcome_at_snapshot':document['outcome'],'tool_configuration':config_identity,'observed_host_tools':observed_tools,
    'preparation_tool_identity_join':True,'all_current_tool_bytes_match':True,'exact_clean_environment':document['environment'],
    'complete_records_reviewed':len(records),'observed_record_files':len(record_paths),'roles':dict(collections.Counter(row['role'] for row in records)),
    'tool_population':dict(collections.Counter(row['tool_name'] for row in records)),'successful_children_reviewed':sum(len(row['children']) for row in records),
    'record_snapshot_identity':digest(json.dumps(record_ids,sort_keys=True,separators=(',',':')).encode()),
    'record_config_tool_recorder_and_child_joins':True,'record_input_injection_environment_absent':True,
    'warning_flags':sorted({arg for row in records for arg in row['arguments'] if arg.startswith('-W')}),
    'new_warning_suppression_observed':False,'inherited_warning_suppression':'yaml-cpp locked CMakeLists.txt selects -Wno-long-long',
    'yaml_cmake_manifest_sha256':yaml_cmake['sha256'],
    'cmake_compiler':{'id':'GNU','version':'12.2.0','base_cxx_flags':cache_entries['CMAKE_CXX_FLAGS'],'release_cxx_flags':cache_entries['CMAKE_CXX_FLAGS_RELEASE']},
    'fetchcontent_disconnected_and_local_roots':True,'launcher_scripts_exact':True,
    'host_acquisition':acquisition_id,'package_bytes':package_observations,'package_driver_members':driver_members,
    'gcc14_diagnostic':old_id,'gcc12_diagnostic':new_id,'diagnostic_flags_equal_except_compiler_and_outputs':True,
    'native_strict_warning_flags_preserved':True,
    'limitations':[
        'The dependency report and record directory were observed while the producer was still running; this bounded snapshot does not prove the final 413-operation population.',
        'Disconnected CMake and local Git object materialization prevent implicit dependency fetching; there is no operating-system network isolation claim.',
        'Selected driver bytes and observed compiler dependency headers are recorded, but complete compiler support executable, system-library and host-toolchain closure is not claimed.',
        'Before/after observations do not defeat malicious concurrent filesystem writers.',
        'No compiler, native workload, replay reader or retained command was executed by this reviewer; dpkg-deb was used only to stream package contents for driver-byte comparison.',
        'Full native execution, loaded-library provenance, counter qualification, warm/performance and phase acceptance require separate evidence.'
    ]
}
OUT.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
print(json.dumps({'outcome':result['outcome'],'complete_records_reviewed':len(records),'observed_record_files':len(record_paths),'roles':result['roles'],'selected_host_tools':len(observed_tools),'packages':len(package_observations),'driver_members':len(driver_members),'output':str(OUT)}))
