#!/usr/bin/env python3
"""Independently audit checkpoint 4268 original bytes and caller-pinned replay.

The baseline byte/build/log checks are adapted from the reviewed wave-7 auditor.
Catalogs are derived before archive inspection from immutable producer Git, the
frozen original name inventory, and the reviewed seven-file addition. Only the
current immutable-Git-pinned local parser closure executes; retained code does not.
"""
from __future__ import annotations

import argparse
import ast
import builtins
from contextlib import ExitStack
import io
import os
from unittest import mock
import datetime
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import zipfile

sys.dont_write_bytecode = True
TRUSTED = '4268d2d5d811063bb886cde7bd0e27e61a79c9b4'
ORIGINAL_PASS = 'e5f152464dda5e488d6d1a030c1fcdc49b5a9701'
FAILED = '81ed6871634fefbf5c78fb27cf10dce913bd4d9c'
GATES = ('qualified', 'ready_for_warm', 'acceptance_claimed', 'full_warm_coverage', 'warm_execution')
SOURCE_ROOTS = ('ci/project', 'sim', 'sw/common', 'sw/include', 'sw/runtime', 'sw/kernel/include',
                'tests/unittest/checked_counters', 'tests/regression/ai_bench_common', 'third_party/ramulator_ext')


def require(ok, label):
    if not ok:
        raise ValueError(label)


def same(actual, expected, label):
    require(type(actual) is type(expected) and actual == expected, label)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def unique(pairs):
    out = {}
    for key, value in pairs:
        require(key not in out, 'duplicate JSON key: ' + key)
        out[key] = value
    return out


def strict_json(body):
    def reject(value):
        raise ValueError('non-finite JSON number: ' + value)
    return json.loads(body, object_pairs_hook=unique, parse_constant=reject)


def path_name(name, absolute=False):
    require(type(name) is str and '\x00' not in name and '\\' not in name, 'invalid path text')
    value = PurePosixPath(name)
    require(value.is_absolute() == absolute and value.as_posix() == name
            and '..' not in value.parts and '.' not in value.parts, 'noncanonical path: ' + name)
    return value


def identity(value):
    same(set(value), {'path', 'resolved_path', 'sha256', 'size_bytes'}, 'identity shape')
    path_name(value['path'], True)
    same(value['resolved_path'], value['path'], 'identity is an alias')
    require(re.fullmatch('[0-9a-f]{64}', value['sha256']) is not None, 'identity digest')
    require(type(value['size_bytes']) is int and value['size_bytes'] > 0, 'identity size')


class Audit:
    def __init__(self, args):
        self.args = args
        self.repo = args.repo.resolve()
        self.out = {'schema_version': 1, 'audited_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    'audit_kind': 'independent-original-archive-data-review', 'trusted_parser_revision': TRUSTED,
                    'native_execution_by_auditor': False, 'archive_extraction': False,
                    'retained_code_execution': False, 'qualified': False, 'ready_for_warm': False,
                    'warm_execution': False, 'acceptance': False, 'reports': {}}
        self.blobs = {}
        self.used = set()

    def git(self, *args, input=None):
        return subprocess.run(['git', '-C', str(self.repo), *args], input=input,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout

    def blob(self, revision, name):
        key = revision + ':' + name
        if key not in self.blobs:
            self.blobs[key] = self.git('show', key)
        return self.blobs[key]

    def names(self, revision, *roots):
        return set(self.git('ls-tree', '-r', '--name-only', revision, '--', *roots).decode().splitlines())

    def pin_parsers(self):
        names = sorted(name for name in self.names(TRUSTED, 'ci/project')
                       if name.endswith('.py') and not PurePosixPath(name).name.startswith('test_'))
        for name in names:
            same((self.repo / name).read_bytes(), self.blob(TRUSTED, name), 'trusted helper changed: ' + name)
        sys.path.insert(0, str(self.repo / 'ci/project'))
        global checked, public_build, public_records, inventory, checked_replay, public_replay
        import p06_checked_execute as checked
        import p06_counter_public_build as public_build
        import p06_counter_public_records as public_records
        import p06_counter_source_inventory as inventory
        import p06_counter_diagnostics_replay as checked_replay
        import p06_counter_public_replay as public_replay
        self.out['trusted_local_helpers'] = {name: sha(self.blob(TRUSTED, name)) for name in names}

    def save_json(self, filename, value):
        path = self.args.out.parent / filename
        body = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()
        if path.exists():
            same(path.read_bytes(), body, 'existing immutable review artifact: ' + filename)
        else:
            path.write_bytes(body)
        return {'path': filename, 'sha256': sha(body), 'size_bytes': len(body)}

    def _catalog_at(self, revision, public):
        if not public:
            return self.names(revision, 'sim', 'sw/common', 'third_party/ramulator_ext',
                              *checked.CRITICAL) | set(checked.CRITICAL)
        helper_names = {name for name in self.names(revision, 'ci/project')
                        if name.endswith('.py') and not PurePosixPath(name).name.startswith('test_')}
        critical = set(checked.CRITICAL) | helper_names | {
            'tests/unittest/checked_counters/public.mk', '.github/workflows/p06-checked-counters.yml',
            'tests/unittest/checked_counters/public_hooks.h', 'tests/unittest/checked_counters/public_hooks.cpp',
            'tests/unittest/checked_counters/public_main.cpp', 'tests/regression/ai_bench_common/counters.h'}
        return self.names(revision, *SOURCE_ROOTS, *sorted(critical)) | critical

    def derive_catalogs(self):
        """Freeze expectations from Git before inspecting the selected new ZIP."""
        same(self.git('rev-parse', TRUSTED + '^{tree}').decode().strip(),
             '061ecbddc9b321edbd70c054c8efce4d188de04f', 'independent immutable tree pin')
        additions = {
            'ci/project/p06_counter_diagnostics_replay.py',
            'ci/project/p06_counter_public_replay.py',
            'ci/project/p06_counter_source_inventory.py',
            'ci/project/test_p06_counter_diagnostics_replay.py',
            'ci/project/test_p06_counter_inventory_replay.py',
            'ci/project/test_p06_counter_public_replay.py',
            'ci/project/test_p06_counter_source_inventory.py',
        }
        selection_sources = []
        for name, original, identifiers in (
            ('ci/project/p06_checked_execute.py', inventory.CHECKED_SOURCE_REVISION,
             ('HELPERS', 'CRITICAL', 'source_snapshot')),
            ('ci/project/p06_counter_public_execute.py', inventory.PUBLIC_SOURCE_REVISION,
             ('HELPERS', 'CRITICAL', 'SOURCE_ROOTS', 'source_snapshot')),
        ):
            def selected_tree(revision):
                tree = ast.parse(self.blob(revision, name), filename=revision + ':' + name)
                result = {}
                for node in tree.body:
                    label = node.name if isinstance(node, ast.FunctionDef) else (
                        node.targets[0].id if isinstance(node, ast.Assign)
                        and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) else '')
                    if label in identifiers:
                        result[label] = ast.dump(node, include_attributes=False)
                        if label == 'SOURCE_ROOTS':
                            same(ast.literal_eval(node.value), SOURCE_ROOTS, 'reviewed producer source roots')
                same(set(result), set(identifiers), 'producer selection AST inventory')
                return result
            same(selected_tree(TRUSTED), selected_tree(original), 'immutable producer selection unchanged')
            selection_sources.append({'path': name, 'original_revision': original,
                                      'source_sha256': sha(self.blob(TRUSTED, name)),
                                      'selection_ast_unchanged': True})
        catalogs = {}
        for prefix, public, contract in (
            ('checked-counters', False, inventory.CHECKED_PRODUCER_CONTRACT_ID),
            ('public-counters', True, inventory.PUBLIC_PRODUCER_CONTRACT_ID),
        ):
            original = inventory.PUBLIC_SOURCE_REVISION if public else inventory.CHECKED_SOURCE_REVISION
            frozen = set(inventory.required_source_names(contract))
            same(self._catalog_at(original, public), frozen, 'immutable original/frozen catalog agreement')
            same(self._catalog_at(ORIGINAL_PASS, public), frozen, 'e5 catalog/frozen agreement')
            current = self._catalog_at(TRUSTED, public)
            same(current - frozen, additions if public else set(), 'reviewed exact catalog additions')
            same(frozen - current, set(), 'no original source deletion')
            same(len(current), 683 if public else 270, 'independent catalog count')
            catalogs[prefix] = sorted(current)
        tree_entries = {}
        for record in self.git('ls-tree', '-rz', '--full-tree', TRUSTED).split(b'\0'):
            if not record:
                continue
            head, name = record.split(b'\t', 1)
            mode, kind, oid = head.decode().split()
            tree_entries[name.decode()] = (mode, kind, oid)
        descriptors, git_descriptors = [], []
        for name in catalogs['public-counters']:
            body = self.blob(TRUSTED, name)
            mode, kind, oid = tree_entries[name]
            require(mode in ('100644', '100755') and kind == 'blob', 'Git source is not a regular blob')
            same(hashlib.sha1(b'blob ' + str(len(body)).encode() + b'\0' + body).hexdigest(), oid,
                 'Git object bytes/hash binding')
            desc = {'path': name, 'sha256': sha(body), 'size_bytes': len(body)}
            descriptors.append(desc)
            git_descriptors.append(dict(desc, git_blob=oid, git_mode=mode))
            if name not in additions:
                same(body, self.blob(ORIGINAL_PASS, name), 'existing source body changed since e5')
        by_name = {row['path']: row for row in descriptors}
        self.expected_descriptors = {prefix: [by_name[name] for name in names]
                                     for prefix, names in catalogs.items()}
        manifest = {'schema_version': 1, 'contract_id': inventory.CONTRACT_ID,
                    'producer_contract_id': inventory.PUBLIC_PRODUCER_CONTRACT_ID,
                    'source_revision': TRUSTED, 'sources': descriptors}
        self.manifest_receipt = self.save_json('public-source-inventory-4268d2d5.json', manifest)
        self.manifest_path = self.args.out.parent / self.manifest_receipt['path']
        self.source_names_digest = sha(''.join(name + '\n' for name in catalogs['public-counters']).encode())
        derivation = {
            'schema_version': 1, 'scope': 'independent-immutable-git-source-expectations',
            'source_revision': TRUSTED, 'source_tree': self.out['source_tree'],
            'expectations_read_from_selected_archive': False,
            'producer_selection_sources': selection_sources,
            'frozen_checked_revision': inventory.CHECKED_SOURCE_REVISION,
            'frozen_public_revision': inventory.PUBLIC_SOURCE_REVISION,
            'frozen_checked_name_count': 270, 'frozen_public_name_count': 676,
            'frozen_checked_name_sha256': inventory.CHECKED_SOURCE_NAMES_SHA256,
            'frozen_public_name_sha256': inventory.PUBLIC_SOURCE_NAMES_SHA256,
            'current_checked_name_count': 270, 'current_public_name_count': 683,
            'current_public_name_sha256': self.source_names_digest,
            'additions': [row for row in git_descriptors if row['path'] in additions],
            'removed_original_names': [], 'existing_public_source_body_changes_since_e5': [],
            'public_manifest': self.manifest_receipt, 'public_sources': git_descriptors,
            'checked_sources': [row for row in git_descriptors
                                if row['path'] in set(catalogs['checked-counters'])],
            'explanation': 'The immutable public source_snapshot selects all tracked ci/project files. '
                           'The three new non-test helpers and four new tests are therefore all retained. '
                           'The independently frozen 676-name original is preserved in full.',
            'qualified': False, 'ready_for_warm': False, 'warm_execution': False, 'acceptance': False,
        }
        self.out['source_derivation'] = self.save_json('w10-native-checkpoint-audit-source-derivation.json', derivation)
        self.out['public_source_inventory'] = dict(self.manifest_receipt, source_files=683,
                                                  source_names_sha256=self.source_names_digest)
        self.out['source_additions'] = derivation['additions']
        print('Independent Git catalogs: checked=270; public=676+7=683; existing bodies unchanged', flush=True)

    def read(self, name):
        path_name(name)
        self.used.add(name)
        return self.zip.read(name)

    def verified(self, prefix, desc):
        same(set(desc), {'path', 'sha256', 'size_bytes'}, 'retained descriptor fields')
        path_name(desc['path'])
        body = self.read(prefix + '/' + desc['path'])
        same(len(body), desc['size_bytes'], 'retained byte count: ' + desc['path'])
        same(sha(body), desc['sha256'], 'retained digest: ' + desc['path'])
        return body

    def descriptor_walk(self, prefix, value):
        if isinstance(value, dict):
            if set(value) == {'path', 'sha256', 'size_bytes'} and value['path'].startswith('artifacts/'):
                self.verified(prefix, value)
            else:
                for item in value.values():
                    self.descriptor_walk(prefix, item)
        elif isinstance(value, list):
            for item in value:
                self.descriptor_walk(prefix, item)

    def expected_source_names(self, public):
        prefix = 'public-counters' if public else 'checked-counters'
        return {row['path'] for row in self.expected_descriptors[prefix]}

    def sources(self, prefix, report):
        before = report['source_before']
        same(before['files'], self.expected_descriptors[prefix], 'independent immutable Git descriptors')
        same(before, report['source_after'], prefix + ' source stability')
        same(report['source_stable'], True, prefix + ' source stable flag')
        same(before['untracked_critical'], [], 'untracked critical source')
        checkout = before['checkout']
        same(checkout['revision'], self.rev, 'source revision')
        same(checkout['tree'], self.git('rev-parse', self.rev + '^{tree}').decode().strip(), 'source tree')
        same(checkout['outcome'], 'pass', 'checkout pass')
        same(checkout['dirty'], False, 'checkout dirty')
        for key in ('blockers', 'changed_paths', 'untracked_paths'):
            same(checkout[key], [], 'checkout ' + key)
        same(checkout['submodules']['errors'], [], 'submodule errors')
        entries = {row['path']: row for row in checkout['submodules']['entries']}
        same(len(entries), 8, 'recursive submodule count')
        for line in self.git('ls-tree', '-r', self.rev).decode().splitlines():
            desc, name = line.split('\t', 1)
            mode, kind, oid = desc.split()
            if kind == 'commit':
                same(entries[name]['revision'], oid, 'direct submodule pin: ' + name)
                same(entries[name]['status'], 'initialized', 'direct submodule state')
        names = [row['path'] for row in before['files']]
        same(names, sorted(self.expected_source_names(prefix == 'public-counters')), 'exact tracked source inventory')
        same(len(names), 683 if prefix == 'public-counters' else 270, 'source inventory count')
        same(len(report['retained_sources']), len(names), 'retained source count')
        contents = {}
        for desc, retained in zip(before['files'], report['retained_sources']):
            same(retained, dict(desc, path='artifacts/source/' + desc['path']), 'source descriptor binding')
            body = self.verified(prefix, retained)
            same(body, self.blob(self.rev, desc['path']), 'source body differs from immutable Git: ' + desc['path'])
            contents[desc['path']] = body
        for desc in checkout['inputs']:
            body = self.blob(self.rev, desc['path'])
            same((sha(body), len(body)), (desc['sha256'], desc['size_bytes']), 'checkout input digest')
        return contents

    def commands(self, prefix, report):
        same(report['tools_before'], report['tools_after'], 'tool/dependency stability')
        same(report['tools_stable'], True, 'tool stability flag')
        same(report['tools_before']['missing'], [], 'missing tool/dependency')
        for value in report['tools_before']['tools'].values():
            require(re.fullmatch('[0-9a-f]{64}', value['sha256']) is not None and value['size_bytes'] > 0, 'tool identity')
        logs, commands = {}, {}
        for command in report['commands']:
            name = command['id']
            require(name not in commands, 'repeated command')
            commands[name] = command
            same(command['log'], 'logs/' + name + '.log', 'command log path')
            body = self.read(prefix + '/' + command['log'])
            same((sha(body), len(body)), (command['log_sha256'], command['log_size_bytes']), 'command log identity')
            same(command['process_started'], True, 'process started')
            same(command['cleanup_complete'], True, 'process cleanup')
            env = dict(report['environment'])
            if name.startswith('public-') and name != 'public-build':
                env['VORTEX_DRIVER'] = 'simx'
            same(command['environment'], env, 'command environment')
            duration = command['duration_seconds']
            require(type(duration) in (int, float) and math.isfinite(duration)
                    and 0 <= duration < command['timeout_seconds'], 'command duration')
            require(0 <= command['peak_rss_bytes'] < report['budget']['max_rss_bytes'], 'command RSS budget')
            require(len(body) <= report['budget']['max_log_bytes'], 'command log budget')
            if command['outcome'] == 'pass':
                same(command['exit_code'], 0, 'passing command exit')
                same(command['reason'], None, 'passing command reason')
            else:
                same(command['outcome'], 'fail', 'unexpected command state')
                require(command['exit_code'] != 0, 'failed command unexpectedly zero exit')
            logs[name] = body.decode('utf-8')
        env = report['environment']
        for key, value in {'CCACHE_DISABLE':'1', 'THREADS':'1', 'MAKEFLAGS':'-j2', 'CMAKE_BUILD_PARALLEL_LEVEL':'2',
                           'LANG':'C', 'LC_ALL':'C', 'TZ':'UTC', 'PYTHONDONTWRITEBYTECODE':'1'}.items():
            same(env[key], value, 'environment ' + key)
        selected=report['tools_before']['tools']
        for name in ('make','g++','python3','executing_python'):
            self.command_binding(commands,'version-'+name.replace('+','p'),[selected[name]['path'],'--version'],
                                 report['paths']['work'],30)
        for name in ('python3','executing_python'):
            same(logs['version-'+name],'Python 3.12.14\n','actual provisioned interpreter version output')
        return commands, logs

    def command_binding(self, commands, name, argv, cwd, timeout):
        same(commands[name]['argv'], list(map(str, argv)), 'argv: ' + name)
        same(commands[name]['cwd'], str(cwd), 'cwd: ' + name)
        same(commands[name]['timeout_seconds'], timeout, 'timeout: ' + name)

    def model_build(self, prefix, report, variant, name, sources, commands, logs):
        public = prefix == 'public-counters'
        source = Path(report['paths']['source'])
        build = Path(report['build_dir'] if public else variant['build_dir'])
        is_checked = name == 'checked'
        binary = build / 'sim/simx/checked_counters_test'
        compiler = report['tools_before']['tools']['g++']['path']
        retained_config = report['retained_configuration'] if public else variant['retained_configuration']
        bodies = {row['path'].removeprefix('artifacts/' + name + '/'): self.verified(prefix, row) for row in retained_config}
        for row in variant['retained_compiler_stamp'] + variant['retained_probe'] + variant['retained_diagnostic_source' if public else 'retained_diagnostic_sources']:
            bodies[row['path'].removeprefix('artifacts/' + name + '/')] = self.verified(prefix, row)
        for key in checked.COPIED + (('tests/unittest/checked_counters/public.mk',) if public else ()):
            same(bodies[key], sources[key], 'configure-copied input: ' + key)
        for key, val in {'XLEN':'64', 'PROFILE':'p02-tfr', 'VORTEX_HOME':str(source), 'TOOLDIR':report['paths']['tools']}.items():
            same(re.findall(r'^' + key + r'[ \t]*\?=[ \t]*(.*?)[ \t]*$', bodies['config.mk'].decode(), re.M), [val], 'generated configuration ' + key)
        same(bodies['checked-header-probe.cpp'], b'#include <VX_config.h>\n#include <perf_counter.h>\n', 'header probe')
        words = checked.compile_flags(bodies[checked.STAMP].decode(), checked=is_checked, source=source, build=build)
        parsed = checked.parse_build_records(logs[name + '-build'], words, source=source, build=build,
            binary=binary, compiler=compiler, source_files=set(sources), source_contents=sources,
            generated_contents={checked.GENERATED_TCU:bodies[checked.GENERATED_TCU]})
        objects = parsed.pop('object_paths')
        recorded = dict(variant['compiler_records'])
        identities = recorded.pop('object_identities')
        same(parsed, recorded, 'recomputed model build records')
        same([row['path'] for row in identities], objects, 'exact model objects')
        for row in identities:
            identity(row)
        if not public:
            same(variant['objects_after'], identities, 'model object stability')
            same(variant['binary_before'], variant['binary_after'], 'model binary stability')
            for key in ('generated', 'compiler_stamp', 'diagnostic_sources'):
                same(variant[key + '_before'], variant[key + '_after'], 'model ' + key + ' stability')
        same(parsed['translation_units'], 45, 'model TU count')
        same(parsed['link_count'], 1, 'model link count')
        same(checked.verify_header(logs[name + '-header'], is_checked), variant['effective_configuration'], 'effective configuration')
        selected = report['tools_before']['tools']
        self.command_binding(commands, name + '-configure', [source / 'configure', '--xlen=64', '--profile=p02-tfr',
            '--tooldir=' + report['paths']['tools']], build, 120)
        make = [selected['make']['path'], '--no-print-directory', '-j2', 'THREADS=1', 'PROFILE=p02-tfr',
                'CONFIGS=' + ('-DSIMX_CHECKED_COUNTERS=1' if is_checked else ''), 'PERF=1', 'CXX=' + compiler]
        self.command_binding(commands, name + '-build', [*make, '-f', 'checked_counters.mk', binary], build / 'sim/simx', 1800)
        flags = [x for x in checked.dependency_flags(words, build / checked.STAMP) if x not in ('-MMD','-MP')]
        self.command_binding(commands, name + '-header', [compiler,*flags,'-E','-dM','-x','c++',build / 'checked-header-probe.cpp'], build / 'sim/simx',120)
        return words, {'translation_units':45, 'links':1, 'object_identities_only':True,
                       'compiler_stamp_sha256':sha(bodies[checked.STAMP]), 'generated_tcu_sha256':sha(bodies[checked.GENERATED_TCU])}

    def checked_report(self, report, sources, commands, logs):
        expected = ['version-make','version-gpp','version-python3','version-executing_python',
                    'ordinary-configure','ordinary-build','ordinary-header','ordinary-boundaries',
                    'checked-configure','checked-build','checked-header','checked-boundaries',
                    *['checked-' + mode for mode in checked.NEGATIVE]]
        same(list(commands), expected, '17 model command order')
        same(report['outcome'], 'pass', 'seven-cell model report')
        same(report['errors'], [], 'model report errors')
        same([x['id'] for x in report['variants']], ['ordinary','checked'], 'model variants')
        variants = {}
        for variant in report['variants']:
            _, variants[variant['id']] = self.model_build('checked-counters',report,variant,variant['id'],sources,commands,logs)
        same([x['id'] for x in report['cells']], ['ordinary-boundaries','checked-boundaries',
             *['checked-' + mode for mode in checked.NEGATIVE]], 'seven model cells')
        for cell in report['cells']:
            name, mode = cell['variant'], cell['mode']
            same(cell['outcome'], 'pass', 'model cell outcome')
            observed = checked.verify_output(logs[cell['id']], name == 'checked') if mode == 'boundaries' else checked.verify_negative(logs[cell['id']],commands[cell['id']],mode)
            same(observed, cell['observations'], 'model raw result/reported observation')
            binary = Path(report['paths']['work']) / name / 'sim/simx/checked_counters_test'
            self.command_binding(commands,cell['id'],[report['tools_before']['tools']['executing_python']['path'],'-I','-c',checked.NO_CORE_WRAPPER,binary,mode],binary.parent,180)
        normal, guard = (dict(cell['observations']) for cell in report['cells'][:2])
        normal.pop('checked');guard.pop('checked')
        same(normal,guard,'ordinary/checked raw equivalence')
        return {'outcome':'pass','source_bodies_verified':len(sources),'commands_verified':len(commands),'variants':variants,
                'cells':[{'id':x['id'],'outcome':x['outcome']} for x in report['cells']]}

    def public_report(self, report, sources, commands, logs):
        prefix = 'public-counters'
        words, model_summary = self.model_build(prefix,report,report['model'],'checked',sources,commands,logs)
        source,build = Path(report['paths']['source']),Path(report['build_dir'])
        selected = report['tools_before']['tools']
        stamps = {PurePosixPath(row['path']).name.removesuffix('_config.stamp'): self.verified(prefix,row).decode()
                  for row in report['public']['retained_compiler_stamps']}
        parsed = public_build.parse_build_records(logs['public-build'],words,stamps,source=source,build=build,
            compiler=selected['g++']['path'],source_files=set(sources),model_records=report['model']['compiler_records'])
        object_paths = parsed.pop('object_paths')
        recorded = dict(report['public']['compiler_records']); identities=recorded.pop('object_identities')
        same(parsed,recorded,'recomputed public build records')
        same([x['path'] for x in identities],object_paths,'public object identities')
        same(len(parsed['reused_model_object_identities']),44,'reused model objects')
        for row in identities:
            identity(row)
        names=['configuration','model-stamp','generated-diagnostic-source','model-objects','model-binary','header-probe',
               'public-stamps','public-objects','public-artifacts']
        same(set(report['bindings']),set(names),'binding inventory')
        for name,value in report['bindings'].items():
            same(value['before'],value['after'],'public binding stability: ' + name)
            for row in value['before']:
                identity(row)
        same(report['bindings']['model-objects']['before'],report['model']['compiler_records']['object_identities'],'model object binding')
        same(report['bindings']['public-objects']['before'],identities,'public object binding')
        same([x['path'] for x in report['bindings']['public-artifacts']['before']], [str(build / x) for x in public_build.ARTIFACTS],'public artifact role binding')
        expected=['version-make','version-gpp','version-python3','version-executing_python',
                  'checked-configure','checked-build','checked-header','checked-boundaries','public-build']
        failed=self.rev==FAILED
        expected += ['public-normal'] if failed else ['public-' + mode for mode in public_records.MODES]
        same(list(commands),expected,'public command order')
        stable=[]
        for index,name in enumerate(expected):
            binds=[] if index<5 else names[:1] if index==5 else names[:6] if index<9 else names
            stable.append({'stage':'before-'+name,'bindings':binds})
            if not(failed and name=='public-normal'):
                stable.append({'stage':'after-'+name,'bindings':binds})
        same(report['stability_checks'],stable,'exact per-command stability chain')
        control=report['model_control'];same(control['outcome'],'pass','public model boundary control')
        same(checked.verify_output(logs['checked-boundaries'],True),control['observations'],'public control raw result')
        self.command_binding(commands,'checked-boundaries',[selected['executing_python']['path'],'-I','-c',checked.NO_CORE_WRAPPER,
            build / 'sim/simx/checked_counters_test','boundaries'],build / 'sim/simx',180)
        make=[selected['make']['path'],'--no-print-directory','-j2','THREADS=1','PROFILE=p02-tfr',
              'CONFIGS=-DSIMX_CHECKED_COUNTERS=1','PERF=1','CXX='+selected['g++']['path']]
        self.command_binding(commands,'public-build',[*make,'-f','../../tests/unittest/checked_counters/public.mk','checked-public'],build / 'sim/simx',1800)
        same([x['mode'] for x in report['cells']],list(public_records.MODES),'public mode inventory')
        cells=[]
        for cell in report['cells']:
            name=cell['id'];mode=cell['mode']
            if name in commands:
                self.command_binding(commands,name,[selected['executing_python']['path'],'-I','-c',checked.NO_CORE_WRAPPER,
                    build / public_build.ROOT / 'checked_public_test',mode],build / public_build.ROOT,180)
            if failed:
                same(cell['outcome'],'fail' if mode=='normal' else 'blocked','historical failure preserved')
                require('observations' not in cell,'failed/blocked cell contains passing observations')
            else:
                same(cell['outcome'],'pass','public mode did not pass')
                observed=public_records.verify_output(logs[name],mode)
                same(observed,cell['observations'],'public raw schema2 observations')
                cells.append({'id':name,'outcome':'pass','checks':observed['checks'],
                              'constructed':observed['constructed'],'destroyed':observed['destroyed'],
                              'overflow_errors':observed['overflow_errors'],'dcr_read_entries':observed['dcr_read_entries']})
        if failed:
            same(report['outcome'],'fail','original failed report outcome')
            same(report['errors'],[{'stage':'execution','reason':'public-normal failed: nonzero_exit'}],'original failure reason')
            same(logs['public-normal'],'FAIL native public counter diagnostic: terminal CP ring is not drained\n','original failure text')
            try:
                public_records.verify_output(logs['public-normal'],'normal')
            except ValueError:
                pass
            else:
                raise ValueError('failed original log promoted to pass')
            cells=[{'id':x['id'],'outcome':x['outcome']} for x in report['cells']]
        else:
            same(report['outcome'],'pass','native public result')
            same(report['errors'],[],'native public errors')
        for key in ('native_public_diagnostics_passed','all_available_selector_transport'):
            same(report[key],not failed,'native report success consistency')
        return {'outcome':report['outcome'],'source_bodies_verified':len(sources),'commands_verified':len(commands),
                'model':model_summary,'public_build':{'new_translation_units':19,'reused_model_objects':44,'links':4,
                'roles':{'libchecked-simx.so':'model','libvortex.so':'14 runtime objects',
                         'libvortex-simx.so':'3 backend objects plus hooks','checked_public_test':'main'}},
                'public_boundary_control':'pass','cells':cells,'raw_results_decoded_with':'Python arbitrary-precision integers'}

    def extra_observations(self, report):
        """Reconcile raw terminal vectors and exceptional paths with Python ints."""
        expected_checks = {'normal': 1668, 'immediate-overflow': 1176,
                           'delayed-overflow': 1176, 'cache-overflow': 1173,
                           'coherent-terminal': 1814}
        max64 = (1 << 64) - 1
        modes = []
        total_contexts = total_disposals = total_terminals = total_queries = total_replies = 0

        def integer_data(value):
            require(not isinstance(value, float), 'public raw number is not an exact Python integer')
            if isinstance(value, dict):
                for item in value.values():
                    integer_data(item)
            elif isinstance(value, list):
                for item in value:
                    integer_data(item)

        with zipfile.ZipFile(self.args.zip) as archive:
            for cell in report['cells']:
                mode = cell['mode']
                log = archive.read('public-counters/logs/public-' + mode + '.log').decode()
                lines = [line for line in log.splitlines() if line.startswith('COUNTER_PUBLIC_RESULT ')]
                same(len(lines), 1, 'unique raw public result')
                value = strict_json(lines[0].removeprefix('COUNTER_PUBLIC_RESULT '))
                integer_data(value)
                same(value, cell['observations'], 'raw/report exact public integer equality')
                same(value['checks'], expected_checks[mode], 'independent assertion count')
                same((value['schema_version'], value['constructed'], value['destroyed']), (2, 2, 2),
                     'raw schema/context/disposal count')
                total_contexts += value['constructed']
                total_disposals += value['destroyed']
                cp_vectors = []
                for terminal in value['terminal_snapshots']:
                    total_terminals += 1
                    same((terminal['selectors'], terminal['components'], terminal['unavailable_unqueried']),
                         (33, 40, 12), 'independent raw transport inventory')
                    same((terminal['device_refs'], terminal['queues'], terminal['buffers']), (1, 0, 0),
                         'terminal exclusive owner state')
                    same(terminal['before'], terminal['after'], 'terminal model snapshot equality')
                    same(len(terminal['rows']), 33, 'raw terminal row count')
                    same([row['name'] for row in terminal['rows']], list(checked.SELECTORS), 'fixed selector ordering')
                    components = terminal['before']['components']
                    same(len(components), 40, 'raw backing component count')
                    offset = 0
                    for index, row in enumerate(terminal['rows']):
                        count = 2 if row['name'].startswith('dcache_') or row['name'] == 'tcu_lmem_reads' else 1
                        same(row['components'], count, 'independent backing multiplicity')
                        expected = sum(components[offset:offset + count])
                        same(row['value'], expected, 'independent backing aggregate')
                        require(expected <= max64, 'aggregate overflow')
                        same(row['value'], (row['high']['value'] << 32) | row['low']['value'],
                             'independent exact low/high reconstruction')
                        for high, half in enumerate(('low', 'high')):
                            read = row[half]
                            same(read['value'], (expected >> (32 * high)) & 0xffffffff, 'exact native half')
                            same((read['ticks_before'], read['ticks_after']),
                                 (terminal['before']['ticks'], terminal['after']['ticks']), 'read ticks unchanged')
                            same((read['reset_before'], read['reset_after']),
                                 (terminal['before']['reset_generation'], terminal['after']['reset_generation']),
                                 'read reset generation unchanged')
                            same((read['completed'], read['status'], read['overflow']), (True, 0, False),
                                 'native reply success')
                        if terminal['seeded']:
                            same(components[offset:offset + count],
                                 [0x1234567800000000 + 2 * index + k for k in range(count)],
                                 'independent coherent source seeds')
                        offset += count
                        total_queries += 1
                        total_replies += 2
                    same(offset, 40, 'all backing components consumed')
                    cp_before, cp_after = terminal['cp_before'], terminal['cp_after']
                    for cp, expected_sequence in ((cp_before, 26), (cp_after, 92)):
                        same((cp['control'], cp['queue_control'], cp['status'], cp['error']), (1, 1, 0, 0),
                             'enabled idle CP status')
                        same((cp['retired'], cp['expected']), (expected_sequence, expected_sequence),
                             'exact serialized retired sequence')
                        same((cp['runtime_tail'], cp['tail_register_pair_raw']),
                             (64 * expected_sequence, 64 * expected_sequence), '64-byte CP retirement accounting')
                        same((cp['head_writeback_raw'], cp['head_writeback_status']), (0, 'not-published'),
                             'unpublished head-writeback observation')
                    cp_vectors.append({'generation': terminal['before']['generation'], 'seeded': terminal['seeded'],
                                       'before': cp_before, 'after': cp_after})
                for disposal in value['destructions']:
                    same((disposal['completed'], disposal['ticks_after'], disposal['idle_after']), (True, 0, True),
                         'complete actual disposal')
                failure = value['failure']
                failure_summary = None
                if failure is not None:
                    expected_seed = max64 - (2 if mode == 'delayed-overflow' else 0)
                    same(failure['seed'], expected_seed, 'exact uint64 seed')
                    require(type(failure['seed']) is int and failure['seed'] > 2**53, 'uint64 integer preserved')
                    same(failure['suppression']['before_entries'], failure['suppression']['after_entries'],
                         'five suppressed operations do not reenter model')
                    dma = failure['suppression']['dma']
                    words = [7340435, 28683, 11]
                    same(dma, {'address': 196608, 'status': 3, 'before': words,
                               'attempted': [word ^ 0xffffffff for word in words], 'after': words},
                         'actual rejected DMA leaves RAM unchanged')
                    for query in failure['suppression']['queries']:
                        same((query['status'], query['before'], query['after']),
                             (3, 0xDECAFBAD12345678, 0xDECAFBAD12345678), 'query sentinel preserved')
                    if mode in ('immediate-overflow', 'delayed-overflow'):
                        same((failure['after']['core_cycles'], failure['after']['core_instructions']),
                             (max64, 0), 'updater overflow does not wrap or retire program')
                        same(failure['after']['core_cycles'] - failure['before']['core_cycles'],
                             2 if mode == 'delayed-overflow' else 0, 'exact observed preoverflow increments')
                    else:
                        same(failure['before'], failure['after'], 'aggregate source state unchanged')
                        same(failure['before']['components'][16:18], [max64, 1], 'actual poisoned cache components')
                        same(len(failure['reads']), 1, 'one failed native DCR read')
                        same((failure['reads'][0]['completed'], failure['reads'][0]['overflow']),
                             (False, True), 'failed typed overflow read')
                    failure_summary = {'seed': failure['seed'], 'before_cycles': failure['before']['core_cycles'],
                                       'after_cycles': failure['after']['core_cycles'], 'dma': dma,
                                       'suppression': failure['suppression'], 'failed_reads': failure['reads']}
                modes.append({'mode': mode, 'schema_version': 2, 'checks': value['checks'],
                              'constructed': 2, 'disposed': 2, 'native_reads': value['dcr_read_entries'],
                              'typed_overflows': value['overflow_errors'], 'terminal_vectors': cp_vectors,
                              'failure': failure_summary})
        same((total_contexts, total_disposals, total_terminals, total_queries, total_replies),
             (10, 10, 7, 231, 462), 'complete raw public totals')
        with zipfile.ZipFile(self.args.zip) as current, zipfile.ZipFile(
            self.repo / 'docs/project/evidence/p06-counter-diagnostics/native/run-45031746149-attempt1.zip') as old:
            added = sorted(set(current.namelist()) - set(old.namelist()))
            removed = sorted(set(old.namelist()) - set(current.namelist()))
        same(added, sorted('public-counters/artifacts/source/' + row['path'] for row in self.out['source_additions']),
             'exact new ZIP members')
        same(removed, [], 'original ZIP member names not removed')
        self.out['member_delta_from_e5'] = {'previous_members': 1039, 'current_members': 1046,
                                           'added': added, 'removed': removed}
        self.out['raw_public_review'] = {'integer_decoder': 'Python arbitrary-precision integers',
            'javascript_native_json_roundtrip': False, 'selectors': 33, 'backing_components': 40,
            'unavailable_unqueried': 12, 'contexts_constructed': total_contexts,
            'contexts_disposed': total_disposals, 'terminal_vectors': total_terminals,
            'successful_selector_queries': total_queries, 'successful_native_halves': total_replies,
            'additional_failed_native_reads': 1, 'modes': modes,
            'cp_drain_is_source_backed_inference': True,
            'cp_source_paths': ['sim/common/cmd_processor.cpp', 'sw/runtime/common/device.cpp',
                                'tests/unittest/checked_counters/public_main.cpp',
                                'tests/unittest/checked_counters/public_hooks.cpp'],
            'cp_limit': 'The head writeback is not published. The tail pair is staged-low/committed-high. '
                        'Drain follows only under exclusive serial ownership from the enabled zero-busy '
                        'source invariant and exact completed retirement accounting.'}

    def guarded_public_replay(self):
        """Allow only trusted reader execution and the two selected data files."""
        parser = self.repo / checked_replay.trusted.ARCHIVE_READER_PATH
        allowed = {self.args.zip, self.manifest_path, parser,
                   *(self.repo / row['path'] for row in public_replay._reader_sources())}
        directories = {parent for path in allowed for parent in path.parents}
        descriptors, opened = {}, set()
        original_open, original_exec = os.open, builtins.exec
        cwd = Path.cwd()

        def selected(path, *, dir_fd=None, directory=False):
            if isinstance(path, int):
                require(path in descriptors, 'unknown descriptor access')
                return descriptors[path]
            candidate = PurePosixPath(os.fsdecode(path))
            if not candidate.is_absolute():
                candidate = (PurePosixPath(descriptors[dir_fd]) if dir_fd is not None else cwd) / candidate
            candidate = Path(candidate)
            require(candidate in (allowed | directories if directory else allowed),
                    'unrelated path accessed: ' + str(candidate))
            return candidate

        def wrap(function, directory=False):
            def guarded(path, *args, **kwargs):
                selected(path, dir_fd=kwargs.get('dir_fd'), directory=directory)
                return function(path, *args, **kwargs)
            return guarded

        def open_fd(path, flags, *args, **kwargs):
            candidate = selected(path, dir_fd=kwargs.get('dir_fd'), directory=bool(flags & os.O_DIRECTORY))
            require(not flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC), 'replay attempted write')
            fd = original_open(path, flags, *args, **kwargs)
            descriptors[fd] = candidate
            opened.add(candidate)
            return fd

        def execute(code, globals=None, locals=None, **kwargs):
            same(getattr(code, 'co_filename', None), str(parser), 'execution outside pinned trusted archive reader')
            return original_exec(code, globals, locals, **kwargs)

        with ExitStack() as stack:
            for owner, name in ((builtins, 'open'), (io, 'open'), (Path, 'open')):
                stack.enter_context(mock.patch.object(owner, name, wrap(getattr(owner, name))))
            for owner, name in ((os, 'stat'), (os, 'lstat'), (os, 'readlink'), (Path, 'resolve'),
                                (Path, 'stat'), (Path, 'lstat'), (Path, 'exists'), (Path, 'is_file'), (Path, 'is_dir')):
                stack.enter_context(mock.patch.object(owner, name, wrap(getattr(owner, name), directory=True)))
            stack.enter_context(mock.patch.object(os, 'open', open_fd))
            stack.enter_context(mock.patch.object(os, 'supports_dir_fd', os.supports_dir_fd | {os.open, os.stat}))
            stack.enter_context(mock.patch.object(os, 'supports_follow_symlinks', os.supports_follow_symlinks | {os.stat}))
            for owner, name in ((subprocess, 'Popen'), (subprocess, 'run'), (subprocess, 'call'),
                                (subprocess, 'check_call'), (subprocess, 'check_output'), (os, 'system'), (os, 'popen'),
                                (os, 'fork'), (os, 'execv'), (os, 'execve'), (os, 'execvp'), (os, 'execvpe'),
                                (os, 'posix_spawn'), (os, 'posix_spawnp'), (os, 'listdir'), (os, 'scandir'),
                                (Path, 'glob'), (Path, 'rglob'), (Path, 'write_bytes'), (Path, 'write_text'),
                                (zipfile.ZipFile, 'extract'), (zipfile.ZipFile, 'extractall'),
                                (checked, 'validate_build'), (checked, 'source_snapshot')):
                if hasattr(owner, name):
                    stack.enter_context(mock.patch.object(owner, name, side_effect=AssertionError('prohibited: ' + name)))
            stack.enter_context(mock.patch.object(builtins, 'exec', execute))
            result = public_replay.replay_archive(self.args.zip, self.out['archive_sha256'],
                expected_revision=TRUSTED, source_inventory=self.manifest_path,
                source_inventory_sha256=self.manifest_receipt['sha256'])
        require(self.args.zip in opened and self.manifest_path in opened, 'selected files were not actually opened')
        return result, {'outcome': 'pass', 'archive_and_manifest_opened': True,
                        'opened_data_files': [str(self.args.zip), str(self.manifest_path)],
                        'retained_code_execution': False, 'archive_extraction': False,
                        'native_build_or_execution': False, 'subprocesses': False,
                        'unrelated_path_access': False, 'writes': False}

    def replay_routes(self):
        common = ['--archive', str(self.args.zip), '--sha256', self.out['archive_sha256'],
                  '--source-revision', TRUSTED]
        manifest = ['--source-inventory', str(self.manifest_path),
                    '--source-inventory-sha256', self.manifest_receipt['sha256']]
        routes = (
            ('checked', 'p06_counter_diagnostics_replay.py', [], 0, None),
            ('public-legacy', 'p06_counter_public_replay.py', [], 1, 'versioned source inventory'),
            ('public', 'p06_counter_public_replay.py', manifest, 0, None),
            ('public-wrong-digest', 'p06_counter_public_replay.py', manifest[:-1] + ['0' * 64], 1,
             'source inventory manifest SHA-256 differs from the external digest'),
        )
        results, receipts = {}, []
        for label, reader, extra, expected_code, failure in routes:
            output = self.args.out.parent / ('w10-native-checkpoint-audit-' + label + '-replay.json')
            require(not output.exists(), 'CLI requires a fresh output path: ' + str(output))
            require(output.parent.resolve(strict=True) == output.parent, 'output parent is an alias')
            command = [sys.executable, '-B', str(self.repo / 'ci/project' / reader),
                       *common, *extra, '--output', str(output)]
            completed = subprocess.run(command, cwd=self.repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
            same(completed.returncode, expected_code, 'actual CLI exit: ' + label + ': ' + completed.stdout.decode())
            same(completed.stderr, b'', 'CLI stderr')
            stdout = strict_json(completed.stdout)
            if expected_code == 0:
                result = strict_json(output.read_bytes())
                same(result['outcome'], 'pass', 'CLI outcome')
                results[label] = result
                output_receipt = {'path': output.name, 'sha256': sha(output.read_bytes()),
                                  'size_bytes': output.stat().st_size}
            else:
                require(not output.exists(), 'rejected CLI unexpectedly created output')
                require(failure in stdout['reason'], 'CLI rejected for wrong reason')
                result = stdout
                output_receipt = None
            same(result['native_execution'], 'not_run', 'replayer did not perform native execution')
            for name in ('qualified', 'ready_for_warm', 'warm_execution', 'acceptance', 'acceptance_claimed',
                         'phase_acceptance', 'performance_acceptance', 'full_warm_coverage', 'retained_code_executed'):
                same(result[name], False, 'replay nonacceptance: ' + name)
            stdout_receipt = self.save_json('w10-native-checkpoint-audit-' + label + '-cli.json', stdout)
            receipts.append({'route': label, 'command': command, 'exit_code': completed.returncode,
                             'stdout': stdout, 'stdout_receipt': stdout_receipt, 'result': output_receipt,
                             'stderr': '', 'fallback': False})
            print('Current CLI ' + label + ': exit=' + str(completed.returncode) + '; ' + stdout['outcome'], flush=True)
        checked_result, public_result = results['checked'], results['public']
        same((checked_result['retained_source_files'], checked_result['commands_checked'], checked_result['cells_checked']),
             (270, 17, 7), 'checked original-inventory replay totals')
        same(checked_result['source_inventory_expectation']['source'], 'original-inventory', 'checked fixed route')
        same((public_result['retained_source_files'], public_result['commands_checked'],
              public_result['cells_checked'], public_result['public_cells_checked']), (683, 14, 6, 5),
             'public external-inventory replay totals')
        same(public_result['source_inventory_expectation']['source'], 'external-manifest', 'explicit public route')
        same(public_result['source_inventory_expectation']['manifest_sha256'], self.manifest_receipt['sha256'],
             'explicit manifest digest receipt')
        guarded, guard_receipt = self.guarded_public_replay()
        same(guarded, public_result, 'guarded replay/actual CLI result equality')
        for label, result in results.items():
            same(strict_json(json.dumps(result, allow_nan=False).encode()), result, 'Python-only JSON roundtrip')
            for row in result['trusted_replay_sources']:
                same((self.repo / row['path']).read_bytes(), self.blob(TRUSTED, row['path']),
                     'current reader source/immutable Git pin')
        self.out['replay_cli_results'] = self.save_json('w10-native-checkpoint-audit-cli-results.json',
            {'schema_version': 1, 'outcome': 'pass', 'routes': receipts, 'guarded_public_replay': guard_receipt,
             'native_execution': 'not_run', 'qualified': False, 'ready_for_warm': False,
             'warm_execution': False, 'acceptance': False})
        self.out['replay_routes'] = [{'route': row['route'], 'exit_code': row['exit_code'],
                                      'outcome': row['stdout']['outcome'], 'result': row['result'],
                                      'stdout_receipt': row['stdout_receipt']} for row in receipts]
        self.out['guarded_public_replay'] = guard_receipt
        self.out['trusted_reader_closure_sizes'] = {label: len(value['trusted_replay_sources'])
                                                  for label, value in results.items()}

    def verify_preservation(self):
        native = self.repo / 'docs/project/evidence/p06-counter-diagnostics/native'
        before = strict_json((native / 'w10-native-checkpoint-audit-originals-before.json').read_bytes())
        verified = {}
        for name, expected in before.items():
            if name in ('original_index', 'index.json'):
                continue
            body = (native / name).read_bytes()
            same({'sha256': sha(body), 'size_bytes': len(body)}, expected, 'original preserved: ' + name)
            verified[name] = expected
        current_index = strict_json((native / 'index.json').read_bytes())
        old_index = before['original_index']
        same(current_index['artifacts'][:3], old_index['artifacts'], 'first three original index entries preserved')
        same({key: value for key, value in current_index.items() if key != 'artifacts'},
             {key: value for key, value in old_index.items() if key != 'artifacts'}, 'original index fields preserved')
        same(strict_json((native / 'public-runtime-pass.json').read_bytes()),
             {'archive': 'run-45031746149-attempt1.zip',
              'sha256': '05f79eef4c9e30b97302e02fec9e2cca47e08fc10c4d5f8235b21f40f41d7276',
              'source_revision': ORIGINAL_PASS}, 'exact three-field historical public fixture receipt')
        for name, expected in self.out['trusted_local_helpers'].items():
            same(sha((self.repo / name).read_bytes()), expected, 'trusted helper changed during audit')
        self.out['preserved_originals'] = verified
        self.out['original_index_entries_preserved'] = True
        self.out['trusted_local_helpers_stable'] = True

    def run(self):
        meta = strict_json(self.args.api.read_bytes())
        records=meta.get('artifacts',meta.get('structuredContent',{}).get('artifacts'))
        require(type(records) is list,'API artifact response absent')
        found=[row for row in records if row['id']==self.args.artifact_id]
        same(len(found),1,'selected API artifact metadata')
        api=found[0];self.rev=api['workflow_run']['head_sha']
        require(self.rev in (FAILED,TRUSTED),'unreviewed producer revision')
        require(api['digest'].startswith('sha256:'),'GitHub API digest is not SHA-256')
        expected=api['digest'].removeprefix('sha256:')
        original=self.args.zip.read_bytes()
        same(len(original),api['size_in_bytes'],'original archive/API byte count')
        same(sha(original),expected,'original archive/API SHA-256')
        self.out.update(archive=str(self.args.zip.resolve()),archive_sha256=expected,archive_size_bytes=len(original),
                        artifact_id=api['id'],workflow_run_id=api['workflow_run']['id'],source_revision=self.rev,
                        source_tree=self.git('rev-parse',self.rev+'^{tree}').decode().strip())
        jobs=strict_json(self.args.jobs_api.read_bytes())['jobs']
        same(len(jobs),1,'native job count')
        job_meta=jobs[0]
        same(job_meta['run_id'],api['workflow_run']['id'],'job/run binding')
        same(job_meta['status'],'completed','native job still incomplete')
        same(job_meta['conclusion'],'failure' if self.rev==FAILED else 'success','native job API conclusion')
        steps={item['number']:item for item in job_meta['steps']}
        for number in (11,12,13):
            same(steps[number]['status'],'completed','native execution/upload step incomplete')
            same(steps[number]['conclusion'],'failure' if self.rev==FAILED and number==12 else 'success','native execution/upload step conclusion')
        self.out.update(job_id=job_meta['id'],job_conclusion=job_meta['conclusion'],
                        artifacts_api_sha256=sha(self.args.api.read_bytes()),jobs_api_sha256=sha(self.args.jobs_api.read_bytes()))
        self.pin_parsers()
        self.derive_catalogs()
        with zipfile.ZipFile(self.args.zip) as archive:
            self.zip=archive
            infos=archive.infolist();same(len({x.filename for x in infos}),len(infos),'duplicate ZIP member')
            require(len(infos)<5000 and sum(x.file_size for x in infos)<128*2**20,'ZIP inventory budget')
            files=set()
            for info in infos:
                name=info.filename.rstrip('/') if info.is_dir() else info.filename
                path_name(name)
                kind=stat.S_IFMT(info.external_attr >> 16)
                require(kind in (0,stat.S_IFREG,stat.S_IFDIR),'ZIP special/symlink member')
                require(info.file_size <= 64*2**20 and not info.flag_bits & 1,'ZIP member limit/encryption')
                if not info.is_dir():
                    files.add(info.filename)
            reports={}
            for prefix in ('checked-counters','public-counters'):
                body=self.read(prefix+'/report.json');report=strict_json(body);reports[prefix]=report
                same(report['expected_revision'],self.rev,'report expected revision')
                same(report['state'],'finished','report state')
                for key in GATES + (('phase_acceptance','performance_acceptance') if prefix=='public-counters' else ()):
                    same(report[key],False,'excluded acceptance gate '+key)
                sources=self.sources(prefix,report);self.descriptor_walk(prefix,report)
                commands,logs=self.commands(prefix,report)
                summary=self.public_report(report,sources,commands,logs) if prefix=='public-counters' else self.checked_report(report,sources,commands,logs)
                summary['report_sha256']=sha(body)
                self.out['reports'][prefix]=summary
            job=strict_json(self.read('job.json'));preparation=strict_json(self.read('preparation.json'))
            workflow=self.read('workflow.yml')
            same(workflow,self.blob(self.rev,'.github/workflows/p06-checked-counters.yml'),'workflow immutable body')
            same(job['workflow_sha256'],sha(workflow),'workflow job binding')
            for key,value in {'GITHUB_SHA':self.rev,'GITHUB_RUN_ID':str(api['workflow_run']['id']),
                              'GITHUB_RUN_ATTEMPT':'1','GITHUB_REPOSITORY':'baabi-boo/AI-GPU',
                              'native_execution':'not_run','record_stage':'job-initialization'}.items():
                same(job[key],value,'job identity/scope '+key)
            same(preparation['expected_revision'],self.rev,'preparation revision')
            same(preparation['outcome'],'pass','preparation result')
            same(preparation['native_execution'],'not_run','preparation scope')
            provision=strict_json(self.read('python-provision.json'))
            same(provision['python_version'],[3,12,14],'CPython version')
            same(provision['implementation'],'CPython','Python implementation')
            same(provision['platform'],'linux','Python platform')
            for prefix,report in reports.items():
                same(preparation['source'],report['source_before']['checkout'],'preparation checkout chain')
                selected=report['tools_before']['tools']
                same(provision['executable'],selected['executing_python']['path'],'provisioned interpreter binding')
                same(provision['python3_on_path'],selected['python3']['path'],'PATH interpreter binding')
                for desc in preparation['dependency_identities']:
                    row=report['tools_before']['dependencies'][desc['path']]
                    same((desc['sha256'],desc['size_bytes']),(row['sha256'],row['size_bytes']),'preparation dependency chain')
            for desc in preparation['preparation_sources']:
                body=self.blob(self.rev,desc['path'])
                same((sha(body),len(body)),(desc['sha256'],desc['size_bytes']),'preparation source chain')
            for name,prefix,field in (('execution.log','checked-counters','native_prerequisites_passed'),
                                      ('public-execution.log','public-counters','native_public_diagnostics_passed')):
                report=reports[prefix]
                same(strict_json(self.read(name)),{'outcome':report['outcome'],field:report[field],
                     'qualified':False,'ready_for_warm':False,'report':report['paths']['output']+'/report.json'},
                     'top-level execution summary/report chain')
            same(strict_json(self.read('preparation.log')),{'outcome':'pass','reason':None,'native_execution':'not_run'},
                 'top-level preparation summary')
            root_logs=files-self.used
            require(all('/' not in name and name.endswith('.log') for name in root_logs),'unaccounted archive file: '+repr(sorted(root_logs)))
            self.out['root_logs']={name:{'sha256':sha(self.read(name)),'size_bytes':archive.getinfo(name).file_size} for name in sorted(root_logs)}
            self.out['archive_members']=len(infos)
            self.out['archive_file_members']=len(files)
            self.out['all_archive_files_accounted']=self.used==files
        self.extra_observations(reports['public-counters'])
        self.replay_routes()
        self.out['native_outcome']='fail' if self.rev==FAILED else 'pass'
        self.out['audit_outcome']='pass'
        self.out['limitations']=[
            'This is a data replay of the original hosted native packet, not a fresh native execution.',
            'Build/link text and stable object/binary hashes are producer records; omitted object and binary bytes cannot be rehashed here.',
            'Tool/dependency hashes do not independently prove cached dependency compilation origin or the complete host dependency closure.',
            'Raw CP tail is staged-low/committed-high; drain is inferred from the source invariant and exact serialized retirement accounting.',
            'Seeded diagnostics and the scalar control do not qualify seed-free warm measurement binaries, GEMM, workspace reuse or cumulative warm performance.',
            'No warm, phase, performance, RTL, full-AFU, vendor or physical hardware acceptance is claimed.']
        self.verify_preservation()
        self.args.out.write_text(json.dumps(self.out,indent=2,sort_keys=True,allow_nan=False)+'\n')
        print(json.dumps({key:self.out[key] for key in ('audit_outcome','native_outcome','source_revision','archive_sha256','archive_members','all_archive_files_accounted')},indent=2))
        print(json.dumps(self.out['reports'],indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,default=Path('/workspace/scratch/98908dfa3444/AI-GPU'))
    parser.add_argument('--zip',type=Path,required=True)
    parser.add_argument('--api',type=Path,required=True)
    parser.add_argument('--jobs-api',type=Path,required=True)
    parser.add_argument('--artifact-id',type=int,required=True)
    parser.add_argument('--out',type=Path,required=True)
    Audit(parser.parse_args()).run()


if __name__=='__main__':
    main()
