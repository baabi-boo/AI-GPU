#!/usr/bin/env python3
"""Focused inert compiler/header probe; no public replay or native execution."""

from contextlib import ExitStack
import copy
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path('/workspace/scratch/101d52695253/AI-GPU')
sys.path.insert(0, str(ROOT / 'ci/project'))
import p05_replay_native as replay
from p06_replay import _archive_api

ARCHIVE = ROOT.parent / 'originals/p05-torch-fp16-c0b44ce6-original.zip'
ARCHIVE_SHA256 = '8c42f7e9f310972e2c0c67c56a03ce8f5460d706cb8dc3a5397435445ea6737c'
REVISION = 'c0b44ce64665fe11895f869eea8c38c9b820d6f7'
FILES = (
    'ci/project/p05_replay_native.py', 'ci/project/compiler_records.py',
    'ci/project/p02_matrix_records.py', 'ci/project/p03_execution_records.py',
    'ci/project/baseline_packet_contract.py', 'ci/project/p05_execute.py',
    'docs/project/evidence/p05-torch/reviews/archive_reader.py',
)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def row(name, raw):
    return {'path': name, 'sha256': digest(raw), 'size_bytes': len(raw)}


class MemoryView:
    def __init__(self, payloads):
        self.payloads = payloads

    def files(self):
        return tuple(sorted(self.payloads))

    def read(self, name, *, limit=replay.MAX_LOG_BYTES):
        raw = self.payloads[name]
        if len(raw) > limit:
            raise ValueError('probe member exceeds read bound')
        return raw

    def verified(self, descriptor, expected_path=None, *, limit=replay.MAX_LOG_BYTES):
        replay._descriptor(descriptor)
        name = descriptor['path']
        raw = self.read(name, limit=limit)
        if row(name, raw) != descriptor or (expected_path is not None and name != expected_path):
            raise ValueError('probe member descriptor mismatch')
        return raw


def capture(view, report, prefix, app):
    needed = {prefix + '/' + name for name in (
        'sw/runtime/simx_rt_config.stamp', 'sw/runtime/simx_config.stamp', app + '/config.stamp')}
    needed.update(name for name in view.files() if name.startswith('logs/'))
    return MemoryView({name: view.read(name) for name in sorted(needed)})


def replace_log(view, report, command_id, old, new):
    command = next(item for item in report['commands'] if item['id'] == command_id)
    name = command['log']
    before = view.payloads[name]
    if before.count(old) != 1:
        raise AssertionError('expected exactly one selected macro in the retained log')
    after = before.replace(old, new, 1)
    view.payloads[name] = after
    command.update(log_sha256=digest(after), log_size_bytes=len(after))
    return {'member': name, 'before_sha256': digest(before), 'after_sha256': digest(after),
            'size_bytes': len(after), 'log_receipt_rehashed': True}


def denied(call):
    try:
        call()
    except ValueError as error:
        return {'outcome': 'rejected', 'error': str(error)}
    raise AssertionError('negative control unexpectedly accepted')


def main():
    before = {name: digest((ROOT / name).read_bytes()) for name in FILES}
    api = _archive_api()
    with api.ArchiveReader(ARCHIVE, ARCHIVE_SHA256) as archive:
        outer = archive.view()
        nv, pv = outer.subview('native-model'), outer.subview('python')
        native, python = nv.json('report.json'), pv.json('report.json')
        variant = native['variants'][0]
        tools = nv.document(native['tools_before'], 'snapshots/tools-before.json')
        request = pv.document(python['installed_request'], 'snapshots/installed-request.json')
        nview = capture(nv, native, 'artifacts/simx-fp16', 'tests/regression/ai_mlp')
        pview = capture(pv, python, 'artifacts/native-matmul', 'tests/regression/ai_matmul')
    common = dict(source=native['paths']['source'], build=python['paths']['native_build'],
                  jobs=native['budget']['jobs'], fmt='fp16')
    na = {item['path']: item for item in variant['artifacts_before']}
    pa = {item['path']: item for item in python['matmul_artifacts_before']}
    models = [{'id': item} for item in native['case_ids']]
    matmuls = [{'id': item} for item in python['matmul_case_ids']]
    literal = replay._package_probe()
    findings = {}
    with ExitStack() as stack:
        stack.enter_context(patch.object(Path, 'open', side_effect=AssertionError('filesystem read')))
        stack.enter_context(patch.object(Path, 'resolve', side_effect=AssertionError('producer resolution')))
        stack.enter_context(patch('subprocess.Popen', side_effect=AssertionError('process launch')))
        stack.enter_context(patch.object(replay, '_package_probe', return_value=literal))
        mc = replay._build_records(nview, 'artifacts/simx-fp16', na,
                                   app='tests/regression/ai_mlp', **common)
        pc = replay._build_records(pview, 'artifacts/native-matmul', pa,
                                   app='tests/regression/ai_matmul', **common)
        replay._same(mc, variant['compiler_records'], 'native compiler records')
        replay._same(pc, python['matmul_compiler_records'], 'matmul compiler records')
        replay._same(mc[:2], pc[:2], 'shared runtime/backend compiler records')

        def native_commands(view, report):
            return replay._native_commands(view, report, tools, mc, variant['qualification_id'],
                                           models, REVISION, 'fp16')

        def python_commands(view, report):
            return replay._python_commands(view, report, tools, pc, python['matmul_qualification_id'],
                                           matmuls, request)

        ncommands = native_commands(nview, native)
        pcommands = python_commands(pview, python)
        for view, name, summary in (
            (nview, 'logs/simx-fp16-header.log', variant['header_macros']),
            (nview, 'logs/simx-fp16-effective-header.log', variant['backend_header_macros']),
            (pview, 'logs/native-matmul-effective-header.log', python['matmul_backend_header_macros']),
        ):
            replay._same(replay.validate_header_macros(replay._text(view, name)), summary, 'header summary')
        findings['valid_control'] = {
            'outcome': 'accepted', 'native_commands': len(ncommands), 'python_commands': len(pcommands),
            'independent_roles': [item['role'] for item in mc], 'header_logs_checked': 3,
            'native_compiler_records_sha256': digest(json.dumps(mc, sort_keys=True, separators=(',', ':')).encode()),
            'matmul_compiler_records_sha256': digest(json.dumps(pc, sort_keys=True, separators=(',', ':')).encode()),
        }

        for route, original_view, original_report, checker, command_id, summary in (
            ('native', nview, native, native_commands, 'simx-fp16-effective-header', variant['backend_header_macros']),
            ('python', pview, python, python_commands, 'native-matmul-effective-header', python['matmul_backend_header_macros']),
        ):
            view, report = copy.deepcopy((original_view, original_report))
            changed = replace_log(view, report, command_id, b'#define ITYPE fp16\n', b'#define ITYPE bf16\n')
            checker(view, report)
            parsed = replay.validate_header_macros(replay._text(view, changed['member']))
            replay._same(parsed, summary, 'header summary')
            findings[route + '_effective_header_itype_disagreement'] = {
                **changed, 'outcome': 'accepted', 'argv_and_stamps_itype': 'fp16', 'log_itype': 'bf16',
                'parsed_summary_retains_itype': 'ITYPE' in parsed,
                'scope': 'real command validator plus real effective-header parser and real summary join',
            }

        for route, view, original_report, checker, ids in (
            ('native', nview, native, native_commands, ('simx-fp16-runtime', 'simx-fp16-application')),
            ('python', pview, python, python_commands, ('native-matmul-build',)),
        ):
            report = copy.deepcopy(original_report)
            for command in report['commands']:
                if command['id'] in ids:
                    command['environment']['CONFIGS'] = '-DITYPE=bf16 -DOTYPE=fp32 -DKUNROLL=1'
            findings[route + '_configs_disagreement'] = denied(lambda: checker(view, report))

        view, artifacts = copy.deepcopy((nview, na))
        name = 'tests/regression/ai_mlp/config.stamp'
        member = 'artifacts/simx-fp16/' + name
        lines = view.payloads[member].decode().splitlines()
        if lines[1].count('-DITYPE=fp16') != 1:
            raise AssertionError('expected exactly one host ITYPE flag')
        lines[1] = lines[1].replace('-DITYPE=fp16', '-I -DITYPE=fp16', 1)
        view.payloads[member] = ('\n'.join(lines) + '\n').encode()
        artifacts[name] = row(name, view.payloads[member])
        findings['host_itype_consumed_as_include'] = {
            **denied(lambda: replay._build_records(view, 'artifacts/simx-fp16', artifacts,
                                                   app='tests/regression/ai_mlp', **common)),
            'stamp_sha256': digest(view.payloads[member]), 'stamp_descriptor_rehashed': True,
        }

        view, report = copy.deepcopy((nview, native))
        changed = replace_log(view, report, 'simx-fp16-effective-header',
                              b'#define VX_CFG_XLEN 64\n', b'#define VX_CFG_XLEN 32\n')
        native_commands(view, report)
        findings['effective_header_xlen_disagreement'] = {
            **changed, **denied(lambda: replay.validate_header_macros(replay._text(view, changed['member']))),
        }
    after = {name: digest((ROOT / name).read_bytes()) for name in FILES}
    if before != after:
        raise AssertionError('reviewed source changed during probe')
    result = {
        'scope': 'focused helper composition using selected original members as inert in-memory data',
        'archive': str(ARCHIVE), 'archive_sha256': ARCHIVE_SHA256, 'archive_close_rehash': 'pass',
        'execution_revision': REVISION, 'source_sha256': before, 'source_unchanged': True,
        'probe_sha256': digest(Path(__file__).read_bytes()), 'findings': findings,
        'limits': ['No native compiler/process execution or retained code execution/import/extraction.',
                   'No public driver, full original replay, broad suite, or BF16 original was run.',
                   'Compiler binary bytes are absent; tool receipts do not establish reproducible compilation.',
                   'The package probe literal was read from trusted current source before filesystem denial.',
                   'Mutation receipts are coherent at the helper boundary; no complete rewritten outer packet was made.'],
    }
    target = ROOT.parent / 'agent-notes/a47-probe.json'
    target.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
