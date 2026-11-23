#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Inert population/lifetime review of the retained native original.

Only explicitly selected current repository helpers are imported. Retained
commands, Python sources, executables and libraries are never executed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import zipfile

sys.dont_write_bytecode = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path('/tmp/ai-gpu-native-lifetime-dfd857'))
    parser.add_argument('--original', type=Path, default=Path('/tmp/ai-gpu-native-lifetime-dfd857-work/native-original'))
    parser.add_argument('--revision', default='b4127b19a004b5aebb8d52eab9ceda0da3ff4561')
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--output', type=Path, default=Path('/tmp/ai-gpu-native-lifetime-dfd857-work/w08_a01-aggregate-receipt.json'))
    args = parser.parse_args()
    repo, original = args.repo.resolve(), args.original.resolve()
    managed, probe_root = original / 'native-lifetime', original / 'pending-probe'
    started = time.monotonic()
    checks = 0
    accessed = {}

    def require(value, message):
        nonlocal checks
        checks += 1
        if value is not True:
            raise AssertionError(message)

    def sha(body):
        return hashlib.sha256(body).hexdigest()

    def canonical(value):
        return sha(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode())

    def unique(pairs):
        value = {}
        for name, item in pairs:
            if name in value:
                raise ValueError('duplicate JSON key: ' + name)
            value[name] = item
        return value

    def read(path):
        body = path.read_bytes()
        accessed[str(path.relative_to(original))] = {'sha256': sha(body), 'size_bytes': len(body)}
        return body

    def parse(body):
        return json.loads(body, object_pairs_hook=unique,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))

    def descriptor(root, row):
        require(set(row) == {'path', 'sha256', 'size_bytes'}, 'descriptor fields')
        relative = Path(row['path'])
        require(not relative.is_absolute() and '..' not in relative.parts, 'descriptor containment')
        path = root / relative
        require(path.resolve().is_relative_to(root), 'resolved descriptor containment')
        body = read(path)
        require(sha(body) == row['sha256'] and len(body) == row['size_bytes'], 'descriptor bytes: ' + row['path'])
        return body

    sys.path.insert(0, str(repo / 'ci/project'))
    import p06_managed_preflight_contract as parent
    import p06_native_lifetime_contract as lifetime
    import p06_native_lifetime_records as records

    report = parse(read(managed / 'report.json'))
    probe = parse(read(probe_root / 'report.json'))
    contract = parent.load_contract(repo)
    plan = parent.process_plan(contract, repo)
    cases = {row['format']: row for row in parent.select_cases(contract, repo)}
    require(report['expected_revision'] == args.revision, 'selected native source')
    require(report['contract_id'] == lifetime.CONTRACT_ID, 'selected lifetime contract')
    require(report['contract_sha256'] == lifetime.contract_hash(), 'current lifetime digest')
    require(parse(descriptor(managed, report['contract_snapshot'])) == lifetime.contract(), 'retained lifetime descriptor')
    require(parse(descriptor(managed, report['preflight_contract_snapshot'])) == contract, 'retained parent descriptor')
    require(report['preflight_contract_sha256'] == canonical(contract), 'current parent digest')
    require(report['expected_processes'] == plan and len(plan) == 4, 'complete canonical process plan')
    require(report['state'] == 'finished' and report['outcome'] == 'pass' and report['reason'] is None, 'finished managed result')
    require(report['native_execution'] == 'run' and report['native_lifetime_passed'] is True
            and report['native_preflight_passed'] is True, 'managed execution result')
    require(report['failures'] == [], 'managed failures preserved empty')
    for document in (report, probe):
        for name in parent.FALSE_CLAIMS:
            require(document[name] is False, 'false claim: ' + name)
    require(report['unresolved_obligations'] == list(parent.UNRESOLVED_OBLIGATIONS), 'unresolved obligations')
    require(report['budget'] == parent.BUDGET, 'fixed managed budget')

    source = parse(descriptor(managed, report['source_before']))
    tools = parse(descriptor(managed, report['tools_before']))
    dependencies = parse(descriptor(managed, report['dependencies_before']))
    for name, before in (('source', source), ('tools', tools), ('dependencies', dependencies)):
        require(parse(descriptor(managed, report[name + '_after'])) == before, name + ' before/after bytes')
        require(report[name + '_stable'] is True, name + ' stable result')
    require(source['checkout']['revision'] == args.revision
            and source['checkout']['tree'] == 'bd37fb53ab1c34dfebc2ac8805abff5877735fc4'
            and source['checkout']['dirty'] is False and source['checkout']['blockers'] == []
            and source['checkout']['changed_paths'] == [] and source['checkout']['untracked_paths'] == [],
            'single clean source checkout')

    require(len(report['variants']) == 2 and [v['format'] for v in report['variants']] == ['fp16', 'bf16'], 'two format builds')
    builds = {}
    for variant in report['variants']:
        fmt = variant['format']
        binding = parse(descriptor(managed, variant['binding']))
        require(variant['id'] == 'simx-' + fmt and variant['outcome'] == 'pass', 'format variant identity')
        require(canonical(binding) == variant['build_binding_sha256'], 'canonical format build digest')
        require(binding['source'] == source and binding['tools'] == tools and binding['dependencies'] == dependencies,
                'shared source/tool/dependency binding')
        require(binding['case'] == cases[fmt] and binding['format'] == fmt and binding['backend'] == 'simx', 'canonical format case')
        require(binding['lifetime_contract'] == lifetime.contract() and binding['contract_sha256'] == report['contract_sha256'],
                'build selected lifetime descriptor')
        require(binding['artifacts'] == variant['artifacts_before'] == variant['artifacts_after'], 'format products stable')
        require(binding['loaded_helpers'] == report['loaded_helpers'], 'shared helper inventory')
        require(binding['simulation_workers'] == 1 and binding['performance_environment'] == {'PERF': '1'}, 'build worker/PERF route')
        require(variant['process_ids'] == [row['id'] for row in plan if row['format'] == fmt], 'no format process omission')
        for name in parent.FALSE_CLAIMS:
            require(binding[name] is False, 'build false claim')
        require(binding['unresolved_obligations'] == list(parent.UNRESOLVED_OBLIGATIONS), 'build unresolved obligations')
        builds[fmt] = (variant, binding)
    require(len({v['build_binding_sha256'] for v in report['variants']}) == 2, 'distinct format bindings')

    commands = report['commands']
    require(len(commands) == 35 and len({row['id'] for row in commands}) == 35, 'exact original command inventory')
    native_commands = [row for row in commands if row['native_process'] is True]
    require([row['id'] for row in native_commands] == [row['id'] for row in plan], 'no native retry or replacement')
    require(len(native_commands) == 4, 'four managed native processes only')
    require(set(p.name for p in (managed / 'logs').iterdir()) == {Path(c['log']).name for c in commands}, 'complete original log inventory')
    require({row['path'] for row in report['raw_logs']} == {row['log'] for row in commands}, 'retained command/log bijection')
    command_by_id = {row['id']: row for row in commands}
    expected_stability_labels = []
    for command in commands:
        require(command['outcome'] == 'pass' and command['exit_code'] == 0 and command['reason'] is None
                and command['process_started'] is True and command['cleanup_complete'] is True, 'successful command receipt')
        body = read(managed / command['log'])
        require(sha(body) == command['log_sha256'] and len(body) == command['log_size_bytes'], 'original command log bytes')
        require(0 <= command['peak_rss_bytes'] <= parent.BUDGET['max_rss_bytes'], 'observed process-group RSS')
        require(command['log_size_bytes'] <= parent.BUDGET['max_log_bytes'], 'command log budget')
        require(0 <= command['duration_seconds'] <= command['timeout_seconds'], 'command timeout observation')
        require(command['environment']['MAKEFLAGS'] == '-j2' and command['environment']['THREADS'] == '1'
                and command['environment']['CMAKE_BUILD_PARALLEL_LEVEL'] == '2', 'bounded command parallelism')
        expected_stability_labels += ['before-command-' + command['id'], 'after-command-' + command['id']]
        if command['native_process']:
            require(command['timeout_seconds'] == 180, 'native process timeout')
            expected_stability_labels.append('after-process-' + command['id'])
            if command['id'].endswith('-reusable_single_tile'):
                expected_stability_labels.append('after-variant-simx-' + command['id'].split('-')[2])
    require([row['label'] for row in report['stability_checks']] == expected_stability_labels, 'all required stability checkpoints')
    for row in report['stability_checks']:
        require(row['source_sha256'] == canonical(source) and row['tools_sha256'] == canonical(tools)
                and row['dependencies_sha256'] == canonical(dependencies), 'checkpoint identities agree')
    for name in ('resources_before', 'resources_after'):
        resource = report[name]
        require(resource['available_memory_bytes'] >= parent.BUDGET['max_rss_bytes'], 'available memory observation')
        require(set(resource['free_disk_bytes']) == {'output', 'source', 'tools', 'work'}
                and all(value >= parent.BUDGET['min_free_bytes'] for value in resource['free_disk_bytes'].values()),
                'free disk observations')
    require(report['retained_files_stable'] is True, 'retained file final stability')
    for row in report['retained_files']:
        descriptor(managed, row)

    totals = {name: 0 for name in parent.COMPLETE_COUNTS}
    aggregate_pending = 0
    rows = []
    require(len(report['processes']) == 4, 'four observed process rows')
    require(len({p['id'] for p in report['processes']}) == 4
            and len({p['sample_id'] for p in report['processes']}) == 4
            and len({p['execution_binding_sha256'] for p in report['processes']}) == 4, 'unique process/sample/execution identities')
    for planned, process in zip(plan, report['processes']):
        fmt, policy = planned['format'], planned['policy']
        variant, build_binding = builds[fmt]
        require({name: process[name] for name in parent.PROCESS_FIELDS} == planned, 'exact ordered process identity')
        require(process['outcome'] == 'pass' and process['command_id'] == planned['id'], 'process successful command join')
        binding = parse(descriptor(managed, process['binding']))
        expected_binding = {'build': build_binding, 'build_binding_sha256': variant['build_binding_sha256'],
            'contract_id': lifetime.CONTRACT_ID, 'contract_sha256': report['contract_sha256'],
            'lifetime_contract': lifetime.contract(), 'preflight_contract_sha256': report['preflight_contract_sha256'], 'process': planned}
        require(binding == expected_binding and canonical(binding) == process['execution_binding_sha256'], 'complete process binding')
        command = command_by_id[process['command_id']]
        app = Path(variant['build_dir']) / parent.APP
        expected_argv = [str(app / 'ai_counter_preflight'), '--lifetime', '--policy', policy, '--module',
            str(app / 'kernel.vxbin'), '--qualification-id', process['execution_binding_sha256'], '--sample-id',
            planned['sample_id'], '--pair-index', '0', '--phase', 'warmup']
        require(command['argv'] == expected_argv and command['cwd'] == str(app), 'exact native argv/cwd')
        require(command['log'] == process['log'] and command['duration_seconds'] == process['process_duration_seconds'], 'native receipt identity')
        text = read(managed / process['log']).decode('utf-8')
        observed = records.verify_output(text, contract=contract, case=cases[fmt], fmt=fmt, policy=policy,
            binding_id=process['execution_binding_sha256'], sample_id=planned['sample_id'], process_id=planned['id'],
            expected_libraries=variant['expected_loaded_libraries'])
        require(observed == process['observation'] == parse(descriptor(managed, process['retained_observation'])), 'raw original observation reproduced')
        warm, witness, life = observed['warm'], observed['witness'], observed['lifetime']
        operations, summary = warm['operations'], warm['summary']
        require(len(operations) == 33 and len(life['runs']) == 33 and summary['operations'] == 33, 'all operations and runs present')
        require(sum(op['checked'] for op in operations) == summary['checked'] == 1056
                and sum(op['mismatches'] for op in operations) == summary['mismatches'] == 0
                and all(op['passed'] is True for op in operations) and summary['passed'] is True, 'exact numerical population')
        require([op['operation_index'] for op in operations] == list(range(33)), 'no repeated or omitted operation')
        require(sum(op['dispatch']['launches'] for op in operations) == 33, 'all native launches')
        require(witness['observation']['run_entries'] == witness['observation']['run_completed'] == 33, 'real run entry/completion counts')
        require(witness['observation']['constructed'] == witness['observation']['destroyed'] == 1
                and witness['observation']['constructor_entries'] == witness['observation']['destructor_entries'] == 1
                and witness['observation']['live'] is False, 'one completed processor lifetime')
        for key in ('run_errors','dcr_read_errors','dcr_write_errors','overflow_errors','underflow_errors',
                    'negative_operand_errors','unexpected_errors','violations'):
            require(witness['observation'][key] == 0, 'zero lifecycle failure count')
        pending = []
        def collect_pending(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key in ('pending_reads', 'pending_before', 'pending_after'):
                        pending.append(item)
                    else:
                        collect_pending(item)
            elif isinstance(value, list):
                for item in value:
                    collect_pending(item)
        collect_pending(life)
        require(len(pending) == 670 and all(type(value) is int and value == 0 for value in pending), 'every pending boundary zero')
        aggregate_pending += len(pending)
        require([(r['before']['reset_generation'], r['after']['reset_generation']) for r in life['runs']]
                == [(j, j + 1) for j in range(1, 34)], 'all actual reset pairs')
        require([s['before']['reset_generation'] for s in life['snapshots']] == [1, 2, 34, 34], 'actual snapshot reset generations')
        sequences = [r['sequence'] for r in witness['reads']] + [r['sequence'] for r in witness['cache_flush_reads']]
        require(len(witness['reads']) == 264 and len(witness['cache_flush_reads']) == 33
                and sorted(sequences) == list(range(1, 298)), 'complete DCR event partition')
        terminal = witness['snapshots'][-1]
        require(terminal['device_refs'] == 1 and terminal['queues'] == terminal['buffers'] == 0, 'sole terminal runtime owner')
        for cp in (terminal['cp_before'], terminal['cp_after']):
            require(cp['control'] == cp['queue_control'] == 1 and cp['status'] == cp['error'] == 0
                    and cp['retired'] == cp['expected'], 'enabled and drained terminal command processor')
        require(terminal['cp_after']['retired'] - terminal['cp_before']['retired'] == 66, 'terminal query retirement')
        destruction = life['destruction']
        require(life['snapshots'][2]['after'] == life['snapshots'][3]['before']
                == life['snapshots'][3]['after'] == destruction['before'], 'terminal model unchanged until actual destructor')
        require(destruction['completed'] is True and destruction['idle_after'] is True
                and destruction['ticks_after'] == 0 and destruction['reset_after'] == 34, 'actual completed disposal observation')
        for document in (witness, life):
            for name in parent.FALSE_CLAIMS:
                require(document[name] is False, 'raw false claim')
            require(document['unresolved_obligations'] == list(parent.UNRESOLVED_OBLIGATIONS), 'raw unresolved obligations')
        require(summary['counts']['device_open_calls'] == summary['counts']['device_release_calls'] == 1
                and summary['counts']['live_buffers'] == summary['counts']['errors'] == summary['counts']['premature_releases'] == 0,
                'successful owner and buffer cleanup')
        totals['processes'] += 1
        totals['launches'] += sum(op['dispatch']['launches'] for op in operations)
        totals['checked_words'] += sum(op['checked'] for op in operations)
        totals['snapshots'] += len(life['snapshots'])
        totals['half_replies'] += len(witness['reads'])
        totals['cache_flush_reads'] += len(witness['cache_flush_reads'])
        totals['dcr_reads'] += len(sequences)
        counters = [c for s in summary['snapshots'].values() for c in s['counters']]
        totals['available_queries'] += sum(c['enabled'] is True for c in counters)
        totals['unavailable_rows'] += sum(c['enabled'] is False for c in counters)
        rows.append({'process_id': planned['id'], 'sample_id': planned['sample_id'], 'format': fmt, 'policy': policy,
            'build_binding_sha256': process['build_binding_sha256'], 'execution_binding_sha256': process['execution_binding_sha256'],
            'raw_log_sha256': command['log_sha256'], 'launches': 33, 'checked_words': 1056, 'mismatches': 0,
            'pending_fields': len(pending), 'reset_start': 1, 'reset_end': 34,
            'mpm_half_reads': 264, 'flushes': 33, 'snapshots': 4, 'dcr_reads': 297,
            'terminal_device_refs': 1, 'terminal_queues': 0, 'terminal_buffers': 0,
            'tensor_creates': summary['counts']['buffer_create_calls'], 'tensor_releases': summary['counts']['buffer_release_calls'],
            'terminal_core_cycles': destruction['before']['core_cycles'], 'terminal_instructions': destruction['before']['core_instructions'],
            'terminal_ticks': destruction['before']['ticks'], 'post_destruction_ticks': destruction['ticks_after'],
            'observed_peak_rss_bytes': command['peak_rss_bytes']})
    require(totals == parent.COMPLETE_COUNTS == report['expected_counts'] == report['completed_counts'], 'independent complete aggregate')
    require(aggregate_pending == 2680, 'complete pending observation aggregate')

    require(probe['contract_id'] == 'p06-pending-read-probe-v1' and probe['expected_revision'] == args.revision
            and probe['state'] == 'finished' and probe['outcome'] == 'pass' and probe['reason'] is None
            and probe['native_execution'] == 'run' and probe['native_probe_passed'] is True
            and probe['zero_mutation_rejected'] is True and probe['failures'] == [], 'separate probe report')
    require(probe['managed_build_binding_sha256'] == builds['fp16'][0]['build_binding_sha256'], 'probe selected managed model')
    require(probe['inputs_before'] == probe['inputs_after'], 'probe input stability')
    probe_ids = [c['id'] for c in probe['commands']]
    require(probe_ids == ['compiler-version', 'compile-native', 'run-native', 'compile-always-zero', 'run-always-zero'], 'separate probe command population')
    require(set(probe_ids).isdisjoint(command_by_id), 'probe excluded from managed command inventory')
    require([p['mode'] for p in probe['products']] == ['native', 'always-zero'], 'separate probe products')
    probe_native = next(c for c in probe['commands'] if c['id'] == 'run-native')
    probe_zero = next(c for c in probe['commands'] if c['id'] == 'run-always-zero')
    require(probe_native['outcome'] == 'pass' and probe_native['exit_code'] == 0
            and probe_zero['outcome'] == 'fail' and probe_zero['exit_code'] == 1
            and probe_zero['reason'] == 'nonzero_exit', 'positive and expected-negative probe receipts')
    contexts = probe['products'][0]['observation']['contexts']
    require(len(contexts) == 2 and [r['gp'] for r in contexts] == [7, -1], 'separate successful native probe contexts')
    require(all(r['steps'] == 135 and r['positive_samples'] == 23 and r['max_pending'] == 1
                and r['pending_final'] == 0 and r['stepped_reset_delta'] == r['checked_reset_delta'] == 1 for r in contexts),
                'probe observations kept outside matrix')

    trusted = {}
    for module in list(sys.modules.values()):
        path = getattr(module, '__file__', None)
        if not path:
            continue
        path = Path(path).resolve()
        if path.is_relative_to(repo / 'ci/project'):
            relative = path.relative_to(repo).as_posix()
            body = path.read_bytes()
            committed = subprocess.check_output(['git', 'show', args.revision + ':' + relative], cwd=repo)
            require(body == committed, 'trusted imported helper matches reviewed source: ' + relative)
            trusted[relative] = {'sha256': sha(body), 'size_bytes': len(body)}
    for relative, identity in list(accessed.items()):
        body = (original / relative).read_bytes()
        require({'sha256': sha(body), 'size_bytes': len(body)} == identity, 'review inputs unchanged: ' + relative)
    archive = args.archive.resolve() if args.archive else original.with_suffix('.zip')
    archive_bytes = archive.read_bytes()
    archive_sha = sha(archive_bytes)
    require(len(archive_bytes) == 9086055
            and archive_sha == '3d4879f73c197352689d65feb56e73f537701fc1411e55bf53c92b1b41e13db3',
            'original GitHub archive identity')
    with zipfile.ZipFile(archive) as container:
        require(len(container.namelist()) == len(set(container.namelist())) == 1264, 'original member population')
        for relative, identity in accessed.items():
            body = container.read(relative)
            require({'sha256': sha(body), 'size_bytes': len(body)} == identity, 'original ZIP bytes: ' + relative)
    receipt = {'schema_version': 1, 'scope': 'independent inert aggregate review of original hosted native lifetime data',
        'outcome': 'pass', 'reviewed_revision': args.revision, 'run_id': 45130300651, 'run_attempt': 1,
        'native_execution_by_review': 'not_run', 'retained_code_executed': False, 'retained_binaries_executed': False,
        'original_archive': {'sha256': archive_sha, 'size_bytes': len(archive_bytes), 'members': 1264},
        'managed_commands': len(commands), 'managed_native_processes': len(native_commands), 'format_builds': 2,
        'source_snapshots': 1, 'process_binding_count': 4, 'sample_id_count': 4, 'retry_or_replacement': False,
        'totals': totals, 'total_zero_pending_fields': aggregate_pending, 'processes': rows,
        'source_snapshot_sha256': report['source_before']['sha256'], 'canonical_source_binding_sha256': canonical(source),
        'stability_checkpoints': len(report['stability_checks']), 'failures': [],
        'resources': {'max_observed_command_rss_bytes': max(c['peak_rss_bytes'] for c in commands),
            'max_observed_native_rss_bytes': max(c['peak_rss_bytes'] for c in native_commands),
            'min_observed_free_disk_bytes': min(v for k in ('resources_before', 'resources_after') for v in report[k]['free_disk_bytes'].values()),
            'min_observed_available_memory_bytes': min(report[k]['available_memory_bytes'] for k in ('resources_before', 'resources_after')),
            'budget': report['budget'], 'limitations': commands[0]['limitations']},
        'separate_probe': {'commands': probe_ids, 'successful_contexts': 2, 'context_observations': contexts,
            'positive_exit': 0, 'expected_negative_exit': 1, 'included_in_managed_counts': False},
        'false_claims': {name: False for name in parent.FALSE_CLAIMS},
        'unresolved_obligations': list(parent.UNRESOLVED_OBLIGATIONS),
        'trusted_source_files': trusted, 'reviewed_original_files': accessed, 'assertions': checks,
        'seconds': round(time.monotonic() - started, 6), 'checker_sha256': sha(Path(__file__).read_bytes())}
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'outcome': 'pass', 'assertions': checks, 'seconds': receipt['seconds'],
        'totals': totals, 'pending_fields': aggregate_pending, 'trusted_sources': len(trusted),
        'original_files_rehashed': len(accessed)}))


if __name__ == '__main__':
    main()
