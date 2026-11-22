#!/usr/bin/env python3
"""One-off read-only original-packet audit; retained bytes are never executed."""
from pathlib import Path, PurePosixPath
import sys
sys.dont_write_bytecode = True
import datetime
import hashlib
import importlib.util
import json
import math
import re
import subprocess

ROOT = Path('/workspace/scratch/98908dfa3444/AI-GPU')
OUT = ROOT.parent
REV = '407ab9fea5e4f793a2a5088f566a87f3e631aa84'
ZIP = OUT / 'native/run-45026112992-attempt1.zip'
ZIP_SHA = 'c4a7ae49259bbb72066d55f7c3e733ce5696f215175ce308f654e1cec9e9c13f'
READER = 'docs/project/evidence/p05-torch/reviews/archive_reader.py'
READER_SHA = '4144becd4fe3c829380f7e66cdb66f7cf073b5e189c2620cd60c62940b9317d3'
CHECKED_SHA = 'bcab9b048606a0d1d4ab8be3f91df9ebe5bce2a41375cd98b9dc2a279b5e2f99'

def sha(body):
    return hashlib.sha256(body).hexdigest()

def require(condition, message):
    if not condition:
        raise ValueError(message)

def same(actual, expected, message):
    require(type(actual) is type(expected) and actual == expected, message)

def git(*args):
    return subprocess.run(['git', '-C', str(ROOT), *args], check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout

def blob(name):
    return git('show', REV + ':' + name)

require(sha((ROOT / READER).read_bytes()) == READER_SHA, 'trusted archive reader changed')
require(sha((ROOT / 'ci/project/p06_checked_execute.py').read_bytes()) == CHECKED_SHA,
        'trusted checked runner changed')
spec = importlib.util.spec_from_file_location('w05_trusted_archive_reader', ROOT / READER)
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)
sys.path.insert(0, str(ROOT / 'ci/project'))
import p06_checked_execute as checked

trusted_helpers = {name: (ROOT / name).read_bytes() for name in checked.HELPERS}
for name, body in trusted_helpers.items():
    same(body, blob(name), 'trusted local helper differs from published revision: ' + name)

def identity(row, path=None, resolved_equal=False):
    same(set(row), {'path', 'resolved_path', 'sha256', 'size_bytes'}, 'live identity fields')
    api.recorded_absolute(row['path'])
    api.recorded_absolute(row['resolved_path'])
    require(re.fullmatch('[0-9a-f]{64}', row['sha256']) is not None, 'live identity digest')
    require(type(row['size_bytes']) is int and row['size_bytes'] > 0, 'live identity size')
    if path is not None:
        same(row['path'], str(path), 'live identity path')
    if resolved_equal:
        same(row['resolved_path'], row['path'], 'live identity resolved alias')

summary = {}
with api.ArchiveReader(str(ZIP), ZIP_SHA) as archive:
    same(ZIP.stat().st_size, 1137709, 'original ZIP byte count')
    view = archive.view('checked-counters')
    report = view.json('report.json')
    same(report['schema_version'], 2, 'report schema')
    same(report['contract_id'], 'simx-checked-counters-native-v2', 'report contract')
    same(report['expected_revision'], REV, 'report source revision')
    same(report['state'], 'finished', 'report state')
    same(report['outcome'], 'pass', 'report outcome')
    same(report['errors'], [], 'report errors')
    for key in ('qualified', 'ready_for_warm', 'acceptance_claimed', 'full_warm_coverage', 'warm_execution'):
        same(report[key], False, 'excluded acceptance: ' + key)
    for key in ('native_prerequisites_passed', 'all_available_selector_transport',
                'ordinary_checked_observations_equal', 'source_stable', 'tools_stable'):
        same(report[key], True, 'success/stability field: ' + key)
    started = datetime.datetime.fromisoformat(report['started_at'])
    finished = datetime.datetime.fromisoformat(report['finished_at'])
    require(started.tzinfo is not None and finished.tzinfo is not None and finished > started,
            'report timestamps')
    same(report['limitations'], checked.LIMITATIONS, 'report limitations changed')
    same(report['budget'], dict(checked.BUDGET, jobs=2, threads=1,
                               timeouts_seconds=checked.TIMEOUTS), 'native budget')
    require(type(report['available_memory_bytes']) is int and
            report['available_memory_bytes'] >= 4 * 2**30, 'memory preflight')
    same(set(report['free_disk_bytes']), set(report['paths']), 'disk paths')
    require(all(type(n) is int and n >= 15 * 2**30 for n in report['free_disk_bytes'].values()),
            'disk reserve')
    paths = {key: api.recorded_absolute(value) for key, value in report['paths'].items()}
    same(set(paths), {'source', 'work', 'tools', 'output'}, 'path roles')
    for key in ('work', 'output'):
        require(not any(paths[key].is_relative_to(p) or p.is_relative_to(paths[key])
                        for name, p in paths.items() if name != key), 'overlapping roots')
    source, work = paths['source'], paths['work']
    environment = report['environment']
    expected_environment = {'PATH': environment['PATH'], 'HOME': str(work / 'home'),
        'TMPDIR': str(work / 'tmp'), 'LANG': 'C', 'LC_ALL': 'C', 'TZ': 'UTC',
        'PYTHONUTF8': '1', 'PYTHONDONTWRITEBYTECODE': '1', 'CCACHE_DISABLE': '1',
        'MAKEFLAGS': '-j2', 'THREADS': '1', 'CMAKE_BUILD_PARALLEL_LEVEL': '2'}
    same(environment, expected_environment, 'clean environment')
    path_entries = environment['PATH'].split(':')
    require(len(path_entries) == len(set(path_entries)), 'duplicate PATH entries')
    for path in path_entries:
        api.recorded_absolute(path)

    same(report['source_before'], report['source_after'], 'source before/after')
    source_before = report['source_before']
    same(source_before['untracked_critical'], [], 'untracked critical sources')
    checkout = source_before['checkout']
    same(checkout['revision'], REV, 'checkout revision')
    tree = git('rev-parse', REV + '^{tree}').decode().strip()
    same(checkout['tree'], tree, 'checkout tree')
    for key in ('blockers', 'changed_paths', 'untracked_paths'):
        same(checkout[key], [], 'checkout ' + key)
    same(checkout['dirty'], False, 'checkout dirty')
    same(checkout['outcome'], 'pass', 'checkout outcome')
    same(checkout['submodules']['errors'], [], 'submodule errors')
    same(checkout['submodules']['declared_count'], 5, 'declared submodules')
    entries = {row['path']: row for row in checkout['submodules']['entries']}
    same(len(entries), 8, 'recursive submodule entry count')
    for path, row in entries.items():
        api.relative_name(path)
        same(row['status'], 'initialized', 'submodule state')
        require(re.fullmatch('[0-9a-f]{40}', row['revision']) is not None, 'submodule SHA')
    direct_links = {}
    for line in git('ls-tree', '-r', REV).decode().splitlines():
        desc, path = line.split('\t', 1)
        mode, kind, oid = desc.split()
        if kind == 'commit':
            direct_links[path] = oid
    same(len(direct_links), 5, 'top-level published gitlinks')
    for path, oid in direct_links.items():
        same(entries[path]['revision'], oid, 'published submodule pin: ' + path)
    source_ids = source_before['files']
    expected_source_paths = set(git('ls-tree', '-r', '--name-only', REV, '--',
        'sim', 'sw/common', 'third_party/ramulator_ext', *checked.CRITICAL).decode().splitlines())
    expected_source_paths |= set(checked.CRITICAL)
    same({row['path'] for row in source_ids}, expected_source_paths, 'exact published source inventory')
    same([row['path'] for row in source_ids], sorted({row['path'] for row in source_ids}),
         'source descriptor order/uniqueness')
    same(len(source_ids), 270, 'retained source count')
    retained_sources = report['retained_sources']
    same(len(retained_sources), len(source_ids), 'retained source descriptor count')
    source_contents = {}
    for original, retained in zip(source_ids, retained_sources):
        api.descriptor(original)
        same(retained, dict(original, path='artifacts/source/' + original['path']),
             'retained source descriptor binding')
        body = view.verified(retained)
        same(body, blob(original['path']), 'retained source differs from Git: ' + original['path'])
        source_contents[original['path']] = body
    for row in checkout['inputs']:
        api.descriptor(row)
        body = source_contents[row['path']]
        same((row['sha256'], row['size_bytes']), (sha(body), len(body)), 'checkout input binding')
    for name, body in trusted_helpers.items():
        same(source_contents[name], body, 'retained trusted helper differs: ' + name)

    same(report['tools_before'], report['tools_after'], 'tool before/after')
    tools = report['tools_before']
    same(tools['missing'], [], 'missing tool/dependency')
    same(set(tools['tools']), {'make', 'g++', 'gcc', 'ar', 'as', 'ld', 'bash', 'python3',
                              'executing_python', 'ccache'}, 'tool identity set')
    same(set(tools['dependencies']), set(checked.native.DEPENDENCIES), 'dependency set')
    for row in tools['tools'].values():
        identity(row)
    for name, row in tools['dependencies'].items():
        identity(row, source / name, resolved_equal=True)
    same(tools['tools']['python3'], tools['tools']['executing_python'], 'Python interpreter selection')
    selected = tools['tools']

    expected_commands = ['version-make', 'version-gpp', 'version-python3', 'version-executing_python',
        'ordinary-configure', 'ordinary-build', 'ordinary-header', 'ordinary-boundaries',
        'checked-configure', 'checked-build', 'checked-header', 'checked-boundaries',
        *['checked-' + mode for mode in checked.NEGATIVE]]
    same([c['id'] for c in report['commands']], expected_commands, 'exact 17 command order')
    commands = {row['id']: row for row in report['commands']}
    command_logs = {}
    for name, command in commands.items():
        same(command['log'], 'logs/' + name + '.log', 'command log path')
        body = view.read(command['log'])
        same(command['log_size_bytes'], len(body), 'command log byte count')
        same(command['log_sha256'], sha(body), 'command log digest')
        command_logs[name] = body.decode('utf-8')
        for key in ('process_started', 'cleanup_complete'):
            same(command[key], True, 'command ' + name + ' ' + key)
        same(command['outcome'], 'pass', 'command outcome')
        same(command['reason'], None, 'command failure reason')
        same(command['exit_code'], 0, 'command exit status')
        same(command['environment'], environment, 'per-command environment')
        same(command['limitations'], list(checked.native.PROCESS_LIMITATIONS), 'process limitations')
        require(type(command['peak_rss_bytes']) is int and
                0 <= command['peak_rss_bytes'] < checked.BUDGET['max_rss_bytes'], 'RSS budget')
        require(len(body) <= checked.BUDGET['max_log_bytes'], 'log budget')
        duration = command['duration_seconds']
        require(type(duration) in (int, float) and math.isfinite(duration)
                and 0 <= duration < command['timeout_seconds'], 'duration budget')

    def command_binding(name, argv, cwd, timeout):
        row = commands[name]
        same(row['argv'], [str(x) for x in argv], 'command argv: ' + name)
        same(row['cwd'], str(cwd), 'command cwd: ' + name)
        same(row['timeout_seconds'], timeout, 'command timeout: ' + name)

    for name in ('make', 'g++', 'python3', 'executing_python'):
        command_binding('version-' + name.replace('+', 'p'),
                        [selected[name]['path'], '--version'], work, 30)
    same([v['id'] for v in report['variants']], ['ordinary', 'checked'], 'variant order')
    variant_summaries = []
    retained_names = set(row['path'] for row in retained_sources)
    for variant in report['variants']:
        name = variant['id']
        is_checked = name == 'checked'
        same(variant['checked'], is_checked, 'checked variant flag')
        build = work / name
        unit = build / 'sim/simx'
        binary = unit / 'checked_counters_test'
        same(variant['build_dir'], str(build), 'variant build directory')
        same(variant['binary_path'], str(binary), 'variant binary path')
        same(variant['configure_command'], name + '-configure', 'configure reference')
        same(variant['build_command'], name + '-build', 'build reference')
        command_binding(name + '-configure', [source / 'configure', '--xlen=64', '--profile=p02-tfr',
                        '--tooldir=' + str(paths['tools'])], build, 120)
        command_binding(name + '-build', [selected['make']['path'], '--no-print-directory', '-j2',
            'THREADS=1', 'PROFILE=p02-tfr', 'CONFIGS=' + ('-DSIMX_CHECKED_COUNTERS=1' if is_checked else ''),
            'PERF=1', 'CXX=' + selected['g++']['path'], '-f', 'checked_counters.mk', binary], unit, 1800)
        generated_bodies = {}
        for key, retained_key, names in (
            ('generated', 'retained_configuration', [*checked.GENERATED, *checked.COPIED]),
            ('compiler_stamp', 'retained_compiler_stamp', [checked.STAMP]),
            ('diagnostic_sources', 'retained_diagnostic_sources', [checked.GENERATED_TCU])):
            before = variant[key + '_before']
            same(before, variant[key + '_after'], name + ' ' + key + ' stability')
            same([r['path'] for r in before], names, name + ' ' + key + ' paths')
            retained = variant[retained_key]
            same(len(retained), len(before), name + ' retained descriptor count')
            for original, row in zip(before, retained):
                api.descriptor(original)
                same(row, dict(original, path='artifacts/' + name + '/' + original['path']),
                     name + ' retained path binding')
                body = view.verified(row)
                generated_bodies[original['path']] = body
                retained_names.add(row['path'])
        for copied in checked.COPIED:
            same(generated_bodies[copied], source_contents[copied], name + ' copied build input')
        cfg = generated_bodies['config.mk'].decode('utf-8')
        cfg_vars = {'XLEN': '64', 'PROFILE': 'p02-tfr', 'VORTEX_HOME': str(source),
                    'TOOLDIR': str(paths['tools']), 'INSTALLDIR': str(build / 'install')}
        for key, value in cfg_vars.items():
            same(re.findall(r'^' + key + r'[ \t]*\?=[ \t]*(.*?)[ \t]*$', cfg, re.M),
                 [value], name + ' configured ' + key)
        stamp_text = generated_bodies[checked.STAMP].decode('utf-8')
        words = checked.compile_flags(stamp_text, checked=is_checked, source=source, build=build)
        parsed = checked.parse_build_records(command_logs[name + '-build'], words,
            source=source, build=build, binary=binary, compiler=selected['g++']['path'],
            source_files=set(source_contents), source_contents=source_contents,
            generated_contents={checked.GENERATED_TCU: generated_bodies[checked.GENERATED_TCU]})
        object_paths = parsed.pop('object_paths')
        recorded = dict(variant['compiler_records'])
        object_identities = recorded.pop('object_identities')
        same(parsed, recorded, name + ' recomputed compiler records')
        same(parsed['translation_units'], 45, name + ' exact compile count')
        same(parsed['link_count'], 1, name + ' exact link count')
        same([row['path'] for row in object_identities], object_paths, name + ' object bindings')
        same(variant['objects_after'], object_identities, name + ' object stability')
        for row, path in zip(object_identities, object_paths):
            identity(row, path, resolved_equal=True)
        same(variant['binary_before'], variant['binary_after'], name + ' binary stability')
        identity(variant['binary_before'], binary, resolved_equal=True)
        same(len(variant['retained_probe']), 1, name + ' header probe count')
        probe = variant['retained_probe'][0]
        same(probe['path'], 'artifacts/' + name + '/checked-header-probe.cpp', 'header probe path')
        same(view.verified(probe), b'#include <VX_config.h>\n#include <perf_counter.h>\n', 'header probe body')
        retained_names.add(probe['path'])
        probe_flags = [word for word in checked.dependency_flags(words, build / checked.STAMP)
                       if word not in ('-MMD', '-MP')]
        command_binding(name + '-header', [selected['g++']['path'], *probe_flags, '-E', '-dM', '-x',
                                          'c++', build / 'checked-header-probe.cpp'], unit, 120)
        effective = checked.verify_header(command_logs[name + '-header'], is_checked)
        same(effective, variant['effective_configuration'], name + ' preprocessed effective config')
        variant_summaries.append({'id': name, 'translation_units': len(object_paths), 'links': parsed['link_count'],
            'effective_configuration': effective, 'binary_identity_only': variant['binary_before'],
            'generated_tcu_sha256': sha(generated_bodies[checked.GENERATED_TCU]),
            'compiler_stamp_sha256': sha(generated_bodies[checked.STAMP])})

    expected_cells = ['ordinary-boundaries', 'checked-boundaries',
                      *['checked-' + mode for mode in checked.NEGATIVE]]
    same([cell['id'] for cell in report['cells']], expected_cells, 'exact seven cell order')
    cell_summaries = []
    for cell in report['cells']:
        name, mode = cell['variant'], cell['mode']
        same(cell['id'], name + '-' + mode, 'cell mode identifier')
        same(cell['run_command'], cell['id'], 'cell command binding')
        same(cell['run_outcome'], 'pass', 'cell process outcome')
        same(cell['run_process_started'], True, 'cell process started')
        same(cell['exit_code'], 0, 'cell exit code')
        same(cell['outcome'], 'pass', 'cell outcome')
        binary = work / name / 'sim/simx/checked_counters_test'
        command_binding(cell['id'], [selected['executing_python']['path'], '-I', '-c',
            checked.NO_CORE_WRAPPER, binary, mode], binary.parent, 180)
        raw = command_logs[cell['id']]
        observed = (checked.verify_output(raw, name == 'checked') if mode == 'boundaries'
                    else checked.verify_negative(raw, commands[cell['id']], mode))
        same(observed, cell['observations'], 'cell raw observations')
        cell_summaries.append({'id': cell['id'], 'observations': observed})
    boundaries = [{key: value for key, value in cell['observations'].items() if key != 'checked'}
                  for cell in report['cells'] if cell['mode'] == 'boundaries']
    same(boundaries[0], boundaries[1], 'ordinary/checked raw boundary equivalence')
    same((400 + 14 + 33) * 4, boundaries[0]['transport_reads'], 'source-derived read count')
    same((400 + 14 + 33) * 14 + 40 + 40 + (8 + 3 + 4 + 1 + 1) * 3,
         boundaries[0]['checks'], 'source-derived assertion count')

    root_names = {'execution.log', 'host-dependencies.log', 'job.json', 'preparation.json',
                  'preparation.log', 'python-provision.json', 'workflow.yml'}
    same(set(view.files()), retained_names | {'report.json'} |
         {row['log'] for row in commands.values()}, 'exact checked packet inventory')
    same(set(archive.files()), {'checked-counters/' + name for name in view.files()} | root_names,
         'exact root archive inventory')
    job = api.strict_json(archive.read('job.json'))
    expected_job = {'GITHUB_EVENT_NAME': 'push', 'GITHUB_JOB': 'native-counters',
        'GITHUB_REF': 'refs/heads/master', 'GITHUB_REPOSITORY': 'baabi-boo/AI-GPU',
        'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_RUN_ID': '45026112992', 'GITHUB_SHA': REV,
        'scope': 'native-checked-counter-prerequisites', 'record_stage': 'job-initialization',
        'native_execution': 'not_run', 'requested_modes': ['ordinary', 'checked'],
        'requested_xlen': 64, 'requested_profile': 'p02-tfr', 'requested_perf': 'on',
        'qualified': False, 'ready_for_warm': False, 'acceptance_claimed': False}
    for key, value in expected_job.items():
        same(job[key], value, 'host job field: ' + key)
    workflow_body = archive.read('workflow.yml')
    same(workflow_body, blob('.github/workflows/p06-checked-counters.yml'), 'published workflow bytes')
    same(sha(workflow_body), job['workflow_sha256'], 'job workflow identity')
    require(job['free_disk_bytes_before_cache'] >= 15 * 2**30 and
            job['available_memory_bytes_before_cache'] >= 4 * 2**30, 'job preflight budgets')
    provision = api.strict_json(archive.read('python-provision.json'))
    same(provision['python_version'], [3, 12, 14], 'pinned interpreter version')
    same(provision['implementation'], 'CPython', 'pinned interpreter implementation')
    same(provision['platform'], 'linux', 'pinned interpreter platform')
    same(provision['executable'], selected['executing_python']['path'], 'provisioned execution interpreter')
    same(provision['python3_on_path'], selected['python3']['path'], 'provisioned PATH interpreter')
    preparation = api.strict_json(archive.read('preparation.json'))
    same(preparation['expected_revision'], REV, 'preparation revision')
    same(preparation['source'], checkout, 'preparation clean source')
    same(preparation['outcome'], 'pass', 'preparation outcome')
    same(preparation['reason'], None, 'preparation reason')
    same(preparation['native_execution'], 'not_run', 'preparation execution scope')
    same(preparation['backend'], 'simx', 'preparation backend')
    same(preparation['budget'], dict(checked.BUDGET, jobs=2), 'preparation budgets')
    for key in ('qualified', 'ready_for_warm', 'acceptance_claimed'):
        if key in preparation:
            same(preparation[key], False, 'preparation excluded acceptance')
    for row in preparation['dependency_identities']:
        api.descriptor(row)
        expected = tools['dependencies'][row['path']]
        same((row['sha256'], row['size_bytes']), (expected['sha256'], expected['size_bytes']),
             'prepared dependency binding')
    for name, row in tools['tools'].items():
        if name in preparation['tool_identities']:
            same(row, preparation['tool_identities'][name], 'prepared tool binding')
    for row in preparation['preparation_sources']:
        api.descriptor(row)
        body = blob(row['path'])
        same((row['sha256'], row['size_bytes']), (sha(body), len(body)), 'published preparation helper binding')
    quarantine = preparation['cache_quarantine']
    same(quarantine['revision_before'], quarantine['expected_revision'], 'quarantine input pin')
    same(quarantine['revision_after'], quarantine['expected_revision'], 'quarantine final pin')
    same(quarantine['status_after'], [], 'quarantine clean result')
    same(quarantine['expected_revision'], entries['third_party/cocogfx']['revision'], 'quarantine source pin')
    for row in quarantine['files']:
        same(row['moved'], True, 'quarantine relocation')
        same((row['sha256'], row['size_bytes']), (row['after_sha256'], row['after_size_bytes']),
             'quarantine identity stability')
    execution_log = archive.read('execution.log')
    preparation_log = archive.read('preparation.log')
    same(api.strict_json(execution_log), {'outcome': 'pass', 'native_prerequisites_passed': True,
        'qualified': False, 'ready_for_warm': False, 'report': str(paths['output'] / 'report.json')},
        'root execution log report binding')
    same(api.strict_json(preparation_log), {'outcome': 'pass', 'reason': None, 'native_execution': 'not_run'},
         'root preparation log binding')
    all_identities = archive.view().inventory()
    archive_receipt = archive.receipt()
    same(len(all_identities), 327, 'complete original member count')
    same(len(archive_receipt['read_files']), 327, 'every member read and hashed')
    summary = {
        'scope': 'independent-data-only-review-of-original-hosted-seven-cell-packet',
        'result': 'pass-with-explicit-evidence-limitations',
        'revision': REV, 'tree': tree, 'started_at': report['started_at'], 'finished_at': report['finished_at'],
        'archive': archive_receipt['archive'],
        'archive_reader': {'path': READER, 'sha256': READER_SHA},
        'trusted_checked_runner_sha256': CHECKED_SHA,
        'all_files_read': len(all_identities), 'expanded_bytes': archive_receipt['expanded_bytes'],
        'archive_read_bytes': archive_receipt['read_bytes'], 'archive_read_count': archive_receipt['read_count'],
        'source_files_equal_published_git': len(source_contents),
        'trusted_helpers_equal_published_and_retained': len(trusted_helpers),
        'workflow_sha256': sha(workflow_body), 'variants': variant_summaries, 'cells': cell_summaries,
        'commands': [{key: c[key] for key in ('id', 'duration_seconds', 'peak_rss_bytes',
                     'log_size_bytes', 'log_sha256', 'timeout_seconds')} for c in commands.values()],
        'versions': {name: command_logs[name].splitlines()[0] for name in expected_commands[:4]},
        'preflight': {'available_memory_bytes': report['available_memory_bytes'],
                      'free_disk_bytes': report['free_disk_bytes']},
        'execution_log': execution_log.decode(),
        'preparation_log': preparation_log.decode(),
        'retained_code_executed': False, 'native_execution_performed_by_reviewer': False,
        'archived_absolute_paths_opened': False, 'archive_extracted': False,
        'qualified': False, 'ready_for_warm': False, 'acceptance_claimed': False,
        'public_runtime_test_present': False,
    }
for name, body in trusted_helpers.items():
    same((ROOT / name).read_bytes(), body, 'trusted local helper changed during audit: ' + name)
require(sha((ROOT / READER).read_bytes()) == READER_SHA, 'archive reader changed during audit')
summary['original_archive_reverified_at_close'] = True
(OUT / 'w05-native-all33-details.json').write_text(json.dumps(summary, indent=2) + '\n')
print(json.dumps({key: value for key, value in summary.items() if key not in
                 ('cells', 'variants', 'commands', 'execution_log', 'preparation_log')}, indent=2))
print('command_summaries=' + json.dumps(summary['commands']))
print('variant_summaries=' + json.dumps([{key: value for key, value in row.items()
    if key != 'effective_configuration'} for row in summary['variants']]))
print('execution_log=' + summary['execution_log'])
print('preparation_log=' + summary['preparation_log'])
