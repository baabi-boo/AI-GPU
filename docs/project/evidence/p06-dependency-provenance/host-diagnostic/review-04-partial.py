#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Review the actual failed attempt04 graph without completing missing evidence."""

from collections import Counter
import hashlib
import importlib
import json
import math
from pathlib import Path, PurePosixPath
import shlex
import stat
import subprocess
import sys
import time
from unittest import mock

ROOT = Path('/workspace/AI-GPU/docs/project/evidence/p06-dependency-provenance/host-diagnostic')
HELPERS = Path('/workspace/p06-depfile-fixed')
WORKSPACE = Path('/workspace/p06-host-diagnostic-fixed-04')
REVISION = '146253db8407e21aaef70e05f3f0dd3c7f5f6d33'
REPORT_SHA256 = '8f1afcb69d5bd17dc9fa727411d0dd2bb67b5ae655fa484236cb9bed9bc36798'
MAP_SHA256 = '9d6fa3c32d3e5f821d830ebd23373d4f8e626d89f801e8ba00af3fe643d16ec4'


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def digest(body):
    return hashlib.sha256(body).hexdigest()


def main():
    start = time.monotonic()
    require(subprocess.check_output(['git', '-C', str(HELPERS), 'rev-parse', 'HEAD']).decode().strip()
            == REVISION, 'trusted helper checkout revision differs')
    require(not subprocess.check_output(['git', '-C', str(HELPERS), 'status', '--porcelain=v1']),
            'trusted helper checkout is dirty')
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(HELPERS / 'ci/project'))
    modules = {}
    for name in ('receipt', 'binary', 'contract', 'record', 'graph', 'sources'):
        module = importlib.import_module('p06_dependency_' + name)
        path = Path(module.__file__)
        require(path == HELPERS / 'ci/project' / ('p06_dependency_' + name + '.py'),
                'trusted helper module origin differs')
        require(path.read_bytes() == subprocess.check_output(['git', '-C', str(HELPERS), 'show',
                REVISION + ':' + path.relative_to(HELPERS).as_posix()]), 'trusted helper bytes differ')
        modules[name] = module
    receipt, binary, contract, recorder, graph, sources = (modules[name] for name in
            ('receipt', 'binary', 'contract', 'record', 'graph', 'sources'))
    result = {'schema_version': 1, 'scope': 'partial-original-host-diagnostic-consistency-only',
        'original_report_sha256': REPORT_SHA256, 'original_outcome': 'fail', 'review_outcome': 'fail',
        'trusted_revision': REVISION, 'full_selected_graph_verified': False, 'native_execution': 'not_run',
        'retained_code_executed': False,
        **dict.fromkeys((*contract.FALSE_CLAIMS, 'host_diagnostic_passed', 'fresh_dependency_build_passed',
            'dependency_source_to_loaded_binary_verified', 'formal_preparation_executed',
            'measurement_staging_executed', 'cache_restoration_claimed'), False)}
    try:
        with mock.patch.object(subprocess, 'Popen', side_effect=AssertionError('inert review cannot launch a process')):
            packet = receipt.PacketReader(WORKSPACE / 'evidence')
            report_bytes = packet('host-diagnostic.json')
            require(digest(report_bytes) == REPORT_SHA256, 'original report differs')
            report = receipt.decode(report_bytes)
            document = report['observations']
            baseline_bytes = (ROOT / 'review-04-records-02.json').read_bytes()
            baseline = receipt.decode(baseline_bytes)
            require(baseline['review_outcome'] == 'pass' and baseline['partial_original_only'] is True
                    and baseline['original_bytes_stable_during_review'] is True
                    and baseline['original_report']['sha256'] == REPORT_SHA256,
                    'complete individual-record review is absent')
            result['individual_record_review_sha256'] = digest(baseline_bytes)
            inventory = {row['path']: row for row in document['retained_files']}

            def read(name):
                require(name in inventory, 'reference is outside retained inventory')
                return receipt.descriptor(inventory[name], packet)

            config = receipt.decode(receipt.descriptor(document['tool_config'], read))
            records = [receipt.decode(receipt.descriptor(row, read)) for row in document['record_identities']]
            require(Counter(row['role'] for row in records) == {'compile': 405, 'archive': 3, 'index': 2, 'link': 1},
                    'actual partial operation population differs')
            require(Counter(row['role'] for row in records if row['outcome'] == 'pass')
                    == {'compile': 405, 'archive': 3, 'index': 2}, 'passing operation population differs')
            failed = [row for row in records if row['outcome'] != 'pass']
            require(len(failed) == 1 and failed[0]['role'] == 'link', 'first failed operation differs')
            link = failed[0]
            source_root, build_root = document['paths']['sources'], document['paths']['build']
            require(source_root == str(WORKSPACE / 'dependency-sources')
                    and build_root == str(WORKSPACE / 'dependency-build'), 'selected workspace differs')
            manifest = sources.validate_manifest(document['source_manifest'])
            source_files = {}
            for source in manifest['sources']:
                for item in source['files']:
                    name = source['name'] + '/' + item['path']
                    body = receipt.descriptor({'path': 'sources/' + name, 'sha256': item['sha256'],
                                               'size_bytes': item['size_bytes']}, read)
                    require(hashlib.sha1(b'blob ' + str(len(body)).encode() + b'\0' + body).hexdigest()
                            == item['oid'], 'source differs from locked Git blob')
                    source_files[name] = item
            plan = graph.source_plan(manifest, lambda owner, name: read('sources/' + owner + '/' + name))
            require(plan == document['source_plan'] and len(source_files) == 1294
                    and manifest['total_size_bytes'] == 10938128, 'locked source graph differs')
            selected = {source_root + '/' + row['source']: row for row in plan}
            compiles, outputs = {}, {}
            for record in records:
                if record['role'] != 'compile':
                    continue
                names = [receipt.absolute(word, record['cwd']) for word in record['requested_arguments']
                         if not word.startswith('-') and word.endswith(('.c', '.cpp'))]
                require(len(names) == 1 and names[0] in selected and names[0] not in compiles,
                        'actual compilation is repeated or outside selected source plan')
                name, unit = names[0], selected[names[0]]
                locked = source_files[unit['source']]
                observed = [item for item in record['inputs_before'] if item['path'] == name]
                require(len(observed) == 1 and observed[0]['sha256'] == locked['sha256']
                        and observed[0]['size_bytes'] == locked['size_bytes'], 'actual source lock differs')
                receipt._verify_compile_inputs(document, record, source_files)
                require(record['output_path'] not in outputs, 'compile output is repeated')
                if unit['component'] == 'softfloat':
                    directory = source_root + '/softfloat/build/Linux-x86_64-GCC'
                    expected = ['-c', '-Werror-implicit-function-declaration', '-DSOFTFLOAT_FAST_INT64',
                        *contract.SOFTFLOAT_OPTIONS, '-I' + directory, '-I' + source_root + '/softfloat/source/RISCV',
                        '-I' + source_root + '/softfloat/source/include', '-O2', '-o', record['output_path'], name]
                    require(record['tool_name'] == 'gcc' and record['cwd'] == directory
                            and receipt._normal_compile(record['requested_arguments'], directory) == expected
                            and record['output_path'] == directory + '/' + unit['archive_member'],
                            'SoftFloat specialization or recipe differs')
                compiles[name], outputs[record['output_path']] = record, record
            missing = sorted(set(selected) - set(compiles))
            require(missing == [source_root + '/ramulator/src/dram/impl/GDDR6.cpp'], 'partial source boundary differs')
            observed_components = dict(Counter(selected[name]['component'] for name in compiles))
            require(observed_components == {'softfloat': 309, 'ramulator': 60, 'yaml-cpp': 29, 'spdlog': 7},
                    'actual component population differs')
            archives = {}
            for name in ('softfloat', 'yaml-cpp', 'spdlog'):
                units = [row for row in plan if row['component'] == name]
                objects = [compiles[source_root + '/' + row['source']] for row in units]
                members = [{'name': unit['archive_member'], 'sha256': row['output']['sha256'],
                            'size_bytes': row['output']['size_bytes']} for unit, row in zip(units, objects)]
                path = (source_root + '/softfloat/build/Linux-x86_64-GCC/softfloat.a' if name == 'softfloat'
                        else build_root + '/ramulator/_deps/' + name + '-build/lib' + name + '.a')
                creates = [row for row in records if row['role'] == 'archive' and row['output_path'] == path]
                require(len(creates) == 1, 'archive creator is not unique')
                create = creates[0]
                require(create['requested_arguments'][0] == ('crs' if name == 'softfloat' else 'qc')
                        and [receipt.absolute(word, create['cwd']) for word in create['requested_arguments'][1:]]
                        == [path, *[row['output_path'] for row in objects]], 'archive recipe or member order differs')
                require(create['inputs_before'] == [row['output'] for row in objects]
                        and all(row['finished_ns'] <= create['started_ns'] for row in objects),
                        'archive object identities or chronology differ')
                binary.validate_archive(receipt.payload(create['output'], read), members)
                indexes = [row for row in records if row['role'] == 'index' and row['output_path'] == path]
                final = create
                if name == 'softfloat':
                    require(not indexes, 'SoftFloat invents an index operation')
                else:
                    require(len(indexes) == 1 and indexes[0]['output_before'] == create['output']
                            and create['finished_ns'] <= indexes[0]['started_ns'], 'archive indexing join differs')
                    final = indexes[0]
                parsed = binary.validate_archive(receipt.payload(final['output'], read), members)
                archives[name] = {'output': final['output'], 'finished_ns': final['finished_ns'],
                                  'members': len(parsed['members']), 'symbol_count': parsed['symbol_count']}

            receipt.fields(link, receipt.RECORD_FIELDS, 'failed actual link receipt')
            map_path = build_root + '/ramulator.map'
            reason = 'file is not regular or exceeds its byte bound: ' + map_path
            ramulator_objects = [compiles[source_root + '/' + row['source']] for row in plan
                                 if row['component'] == 'ramulator']
            expected_inputs = [row['output'] for row in ramulator_objects]
            expected_inputs += [archives[name]['output'] for name in ('yaml-cpp', 'spdlog')]
            require(link['state'] == 'finished' and link['outcome'] == 'fail' and link['reason'] == reason
                    and link['failures'] == [{'stage': 'execution', 'reason': reason}]
                    and link['process_started'] is True and type(link['exit_code']) is int and link['exit_code'] == 0,
                    'failed link termination differs')
            require(link['role'] == 'link' and link['tool_name'] == 'g++' and link['tool'] == config['tools']['g++']
                    and link['config_sha256'] == document['tool_config']['sha256']
                    and link['recorder'] == records[0]['recorder'], 'failed link selected tool/config differs')
            require(link['id'] == contract.digest({'role': 'link', 'output': link['output_path']})
                    and link['cwd'] == build_root + '/ramulator'
                    and link['output_path'] == source_root + '/ramulator/libramulator.so'
                    and link['output_absent_before'] is True and link['output_before'] is None
                    and link['output']['path'] == link['output_path'] == link['output']['resolved_path'],
                    'failed link identity or fresh output differs')
            expected_argv = ['-fPIC', '-O3', '-DNDEBUG', '-Wl,-Map,' + map_path, '-shared',
                '-Wl,-soname,libramulator.so', '-o', link['output_path'],
                *[str(PurePosixPath(row['output_path']).relative_to(PurePosixPath(link['cwd'])))
                  for row in ramulator_objects], '_deps/yaml-cpp-build/libyaml-cpp.a', '_deps/spdlog-build/libspdlog.a']
            require(link['arguments'] == link['requested_arguments'] == expected_argv,
                    'failed link observed recipe differs')
            require(link['inputs_before'] == expected_inputs and link['inputs_after'] == []
                    and link['link_map'] is None and link['dependency_file'] is None
                    and link['dependency_prepass_file'] is None, 'failed link evidence boundary differs')
            for item in [*expected_inputs, link['output']]:
                receipt.payload(item, read)
            require(all(row['finished_ns'] <= link['started_ns'] for row in ramulator_objects)
                    and all(archives[name]['finished_ns'] <= link['started_ns'] for name in ('yaml-cpp', 'spdlog')),
                    'failed link predates prerequisites')
            require(link['environment'] == records[0]['environment'] and len(link['children']) == 1,
                    'failed link child/environment differs')
            child = link['children'][0]
            receipt.fields(child, receipt.CHILD_FIELDS, 'failed link actual child')
            require(child['stage'] == 'tool' and child['process_started'] is True and child['exit_code'] == 0
                    and child['argv'] == [config['tools']['g++']['path'], *expected_argv]
                    and all(type(child[key]) is int and child[key] > 0 for key in
                            ('pid', 'process_group', 'started_ns', 'finished_ns'))
                    and 0 < link['started_ns'] <= child['started_ns'] <= child['finished_ns'] <= link['finished_ns'],
                    'failed link successful child observation differs')
            require(document['compile_database'] is None and document['generated_inputs'] == [],
                    'original unexpectedly claims generated CMake capture')
            rejected = {}
            for name, operation in (
                ('successful_record', lambda: receipt._validate_record(link, config, document['tool_config']['sha256'],
                                                                       read, link['recorder'])),
                ('full_compile_graph', lambda: receipt._verify_compile_graph(document, records, config, read)),
                ('generated_cmake', lambda: receipt._verify_generated_build(document, records, read)),
                ('full_outer_commands', lambda: receipt._verify_outer_commands(document, config, read)),
            ):
                try:
                    operation()
                except ValueError as error:
                    rejected[name] = str(error)
                else:
                    raise ValueError('incomplete evidence incorrectly accepted by ' + name)

            commands = document['commands']
            require([row['id'] for row in commands] == ['softfloat', 'ramulator-configure', 'ramulator-build'],
                    'actual outer operation population differs')
            for index, row in enumerate(commands):
                receipt.fields(row, receipt.COMMAND_FIELDS, 'actual outer command')
                require(row['process_started'] is True and row['cleanup_complete'] is True
                        and row['environment'] == document['environment']
                        and row['timeout_seconds'] == (120 if index == 1 else 1800)
                        and row['outcome'] == ('fail' if index == 2 else 'pass')
                        and row['exit_code'] == (2 if index == 2 else 0)
                        and row['reason'] == ('nonzero_exit' if index == 2 else None), 'actual outer outcome differs')
                require(math.isfinite(row['duration_seconds']) and 0 <= row['duration_seconds'] < row['timeout_seconds']
                        and 0 <= row['peak_rss_bytes'] <= contract.BUDGET['max_rss_bytes']
                        and 0 <= row['log_size_bytes'] <= contract.BUDGET['max_log_bytes']
                        and row['limitations'] == list(receipt.PROCESS_LIMITATIONS), 'actual outer limits differ')
                receipt.descriptor({'path': row['log'], 'sha256': row['log_sha256'],
                                    'size_bytes': row['log_size_bytes']}, read)
            compile_words = [*receipt._launcher(document, 'gcc', 'compile'), '-c', '-Werror-implicit-function-declaration',
                '-DSOFTFLOAT_FAST_INT64', *contract.SOFTFLOAT_OPTIONS, '-I.', '-I../../source/RISCV',
                '-I../../source/include', '-O2', '-o']
            softfloat_argv = [document['tools']['make']['path'], '--no-print-directory', '-j2', '--output-sync=target',
                'SPECIALIZE_TYPE=RISCV', 'SOFTFLOAT_OPTS=' + ' '.join(contract.SOFTFLOAT_OPTIONS),
                'COMPILE_C=' + shlex.join(compile_words) + ' $@',
                'MAKELIB=' + shlex.join([*receipt._launcher(document, 'ar', 'archive'), 'crs']) + ' $@', 'softfloat.a']
            require(commands[0]['argv'] == softfloat_argv
                    and commands[0]['cwd'] == source_root + '/softfloat/build/Linux-x86_64-GCC', 'SoftFloat outer recipe differs')
            options = document['cmake_configuration']
            require(all(options[key] == value for key, value in graph.CMAKE_OPTIONS.items()), 'fixed CMake options differ')
            for key, role in (('CMAKE_CXX_COMPILER_LAUNCHER', 'compile'), ('CMAKE_CXX_LINKER_LAUNCHER', 'link')):
                require(options[key] == ';'.join(receipt._launcher(document, 'g++', role, compiler_launcher=True)),
                        'CMake recorder selection differs')
            for name, role in (('ar', 'archive'), ('ranlib', 'index')):
                path = 'launchers/' + name + '.sh'
                require(options['CMAKE_' + name.upper()] == document['paths']['output'] + '/' + path
                        and read(path) == ('#!/bin/sh\nexec ' + shlex.join(receipt._launcher(document, name, role))
                                          + ' "$@"\n').encode(), 'archive launcher differs')
            require(options['CMAKE_CXX_COMPILER'] == document['tools']['g++']['path']
                    and options['CMAKE_MAKE_PROGRAM'] == document['tools']['make']['path']
                    and options['CMAKE_SHARED_LINKER_FLAGS'] == '-Wl,-Map,' + map_path
                    and all(options['FETCHCONTENT_SOURCE_DIR_' + key] == source_root + '/' + name
                            for key, name in (('YAML-CPP', 'yaml-cpp'), ('SPDLOG', 'spdlog'), ('ARGPARSE', 'argparse'))),
                    'CMake input selection differs')
            require(commands[1]['argv'] == [document['tools']['cmake']['path'], '-S', source_root + '/ramulator',
                '-B', build_root + '/ramulator', '-G', 'Unix Makefiles',
                *('-D' + name + '=' + value for name, value in sorted(options.items()))]
                and commands[1]['cwd'] == build_root, 'CMake configure recipe differs')
            require(commands[2]['argv'] == [document['tools']['cmake']['path'], '--build', build_root + '/ramulator',
                '--target', 'ramulator', '--parallel', '2', '--verbose'] and commands[2]['cwd'] == build_root,
                'CMake build recipe differs')
            generated = {}
            for row in sorted(records, key=lambda item: item['finished_ns']):
                for field in ('output', 'dependency_file', 'dependency_prepass_file', 'link_map'):
                    item = row[field]
                    if item is not None and PurePosixPath(item['path']).is_relative_to(PurePosixPath(source_root)):
                        name = str(PurePosixPath(item['path']).relative_to(PurePosixPath(source_root)))
                        generated[name] = {'path': name, 'sha256': item['sha256'], 'size_bytes': item['size_bytes']}
            generated_rows = [generated[name] for name in sorted(generated)]
            require(document['generated_sources'] == generated_rows and len(generated_rows) == 929,
                    'record-derived generated source inventory differs')
            labels = ['sources-frozen', 'before-softfloat', 'after-softfloat', 'before-ramulator-configure',
                      'after-ramulator-configure', 'before-ramulator-build']
            require([row['label'] for row in document['stability_checks']] == labels,
                    'actual partial stability boundary population differs')
            for index, row in enumerate(document['stability_checks']):
                current = [] if index < 2 else [item for item in generated_rows if item['path'].startswith('softfloat/')]
                require(set(row) == {'label', 'sources'} and row['sources'] == {
                    'contract_id': sources.CONTRACT_ID, 'manifest_sha256': contract.digest(manifest),
                    'source_files': 1294, 'source_bytes': 10938128, 'generated_files': len(current),
                    'generated_bytes': sum(item['size_bytes'] for item in current),
                    'generated_sha256': contract.digest(current)}, 'partial stability summary differs')
            require(report['reason'] == 'host diagnostic command failed: ramulator-build'
                    and report['failures'] == [
                        {'stage': 'execution-or-inert-check', 'reason': report['reason']},
                        {'stage': 'final-stability', 'reason': 'dependency source filesystem inventory is incomplete'}],
                    'original terminal failure list differs')
            log = read('logs/ramulator-build.log').decode()
            require('dependency recorder: ' + reason in log
                    and "Deleting file '" + link['output_path'] + "'" in log, 'outer log lacks failure/deletion chain')

            # Supplemental read-only observation, explicitly outside the retained original inventory.
            # It cannot supply the missing link receipt or turn the failed original into a pass.
            observed_map_path = WORKSPACE / 'dependency-build/ramulator.map'
            before = observed_map_path.lstat()
            raw_map = receipt.PacketReader(WORKSPACE / 'dependency-build')('ramulator.map')
            require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and len(raw_map) == 18084083
                    and digest(raw_map) == MAP_SHA256, 'post-terminal map observation differs')
            map_rejections = {}
            for name, operation in (
                ('recorder_bound', lambda: recorder._regular_bytes(observed_map_path, contract.MAX_RECEIPT_BYTES)),
                ('parser_bound', lambda: binary.parse_link_map(raw_map.decode('ascii'), cwd=link['cwd'])),
            ):
                try:
                    operation()
                except ValueError as error:
                    map_rejections[name] = str(error)
                else:
                    raise ValueError('oversized actual map unexpectedly accepted by ' + name)
            after = observed_map_path.lstat()
            require(all(getattr(before, field) == getattr(after, field) for field in
                    ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')), 'post-terminal map changed during review')
            output_absent = not (WORKSPACE / 'dependency-sources/ramulator/libramulator.so').exists()
            require(output_absent, 'make-deleted target unexpectedly exists')
            repeated = compiles[source_root + '/softfloat/source/s_shortShiftLeft128.c']
            depfile = receipt.payload(repeated['dependency_prepass_file'], read)
            words = depfile.decode().replace('\\\r\n', ' ').replace('\\\n', ' ').split(':', 1)[1].split()
            require(len(words) == 24 and len(repeated['inputs_before']) == 23,
                    'actual repeated-header regression population differs')
            for row in document['retained_files']:
                receipt.descriptor(row, packet)
            require(packet('host-diagnostic.json') == report_bytes, 'original report changed during semantic review')
            result.update(review_outcome='pass', original_bytes_stable_during_review=True,
                selected_tool_operations=411, passing_tool_operations=410,
                child_stages=dict(Counter(child['stage'] for row in records for child in row['children'])),
                source_files=1294, source_bytes=10938128, planned_translation_units=406,
                observed_translation_units=observed_components, absent_translation_units=missing,
                archives=archives, failed_link={'id': link['id'], 'record_sha256': next(row['sha256']
                    for row in document['record_identities'] if row['path'] == 'records/' + link['id'] + '.json'),
                    'reason': reason, 'input_count_before': 62, 'input_count_after': 0,
                    'child_exit_code': 0, 'output_payload': link['output'], 'map_retained': False},
                complete_validators_rejected=rejected, actual_stability_boundaries=labels,
                record_derived_source_outputs=929, final_source_stability_passed=False,
                actual_outer_commands=[{key: row[key] for key in ('id', 'outcome', 'exit_code',
                    'duration_seconds', 'peak_rss_bytes', 'log_size_bytes', 'cleanup_complete')} for row in commands],
                supplemental_map_observation={'scope': 'post-terminal-read-only-workspace-observation',
                    'in_original_retained_inventory': False, 'sha256': MAP_SHA256, 'size_bytes': len(raw_map),
                    'lines': raw_map.count(b'\n'), 'regular_file': True, 'stable_during_review': True,
                    'recorder_limit_bytes': contract.MAX_RECEIPT_BYTES,
                    'parser_limit_bytes': contract.BUDGET['max_log_bytes'], 'artifact_limit_bytes': contract.MAX_FILE_BYTES,
                    'rejections': map_rejections}, workspace_link_output_absent_after_make_cleanup=output_absent,
                repeated_header_regression={'record_id': repeated['id'], 'raw_dependency_tokens': 24,
                    'unique_stable_inputs': 23, 'prepass_sha256': digest(depfile), 'actual_compile_outcome': repeated['outcome']},
                unavailable_checks=['Complete 406-compile and two-link population',
                    'Generated CMake cache, flags, archive/link recipes and 97-row compile database were not retained',
                    'Retained map semantics and direct-input/member LOAD joins',
                    'Post-link input identity comparison and final source-filesystem stability',
                    'Extension compilation/link and final three-product completion',
                    'Formal preparation, cache restoration, measurement staging, managed builds and native/loader joins'])
    except (OSError, ValueError, RuntimeError, AssertionError, KeyError, TypeError) as error:
        result.update(reason=str(error), error_type=type(error).__name__)
    result['duration_seconds'] = round(time.monotonic() - start, 6)
    result['reviewer_sha256'] = digest(Path(__file__).read_bytes())
    with (ROOT / 'review-04-partial.json').open('x') as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write('\n')
    print(json.dumps({key: result[key] for key in ('review_outcome', 'original_outcome',
        'full_selected_graph_verified', 'native_execution', 'duration_seconds')}, sort_keys=True))
    if result.get('reason'):
        print(result['reason'])
    return 0 if result['review_outcome'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())
