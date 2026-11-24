#!/usr/bin/env python3
"""Read selected c0 original members and check the repaired effective-header join."""

from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path('/workspace/scratch/101d52695253/AI-GPU')
sys.path.insert(0, str(ROOT / 'ci/project'))
import p05_replay_native as replay
from p06_replay import _archive_api
from test_p05_replay_native import MemoryView

ORIGINALS = {
    'fp16': '8c42f7e9f310972e2c0c67c56a03ce8f5460d706cb8dc3a5397435445ea6737c',
    'bf16': '787fd1b41a27da8c100277613c581ba734920fd45b13e0707ba0f9ea2e866330',
}
FILES = (
    'ci/project/p05_replay_native.py', 'ci/project/test_p05_replay_effective_headers.py',
    'ci/project/p02_matrix_records.py', 'ci/project/p03_execution_records.py',
    'ci/project/compiler_records.py', 'ci/project/baseline_packet_contract.py',
    'ci/project/test_p05_replay_native.py',
    'docs/project/evidence/p05-torch/reviews/archive_reader.py',
)


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    before = {name: sha256((ROOT / name).read_bytes()) for name in FILES}
    api, observations = _archive_api(), []
    for fmt, pin in ORIGINALS.items():
        path = ROOT.parent / ('originals/p05-torch-' + fmt + '-c0b44ce6-original.zip')
        selected = []
        with api.ArchiveReader(path, pin) as archive:
            outer = archive.view()
            native_view, python_view = outer.subview('native-model'), outer.subview('python')
            native, python = native_view.json('report.json'), python_view.json('report.json')
            common = dict(source=native['paths']['source'], build=python['paths']['native_build'],
                          jobs=native['budget']['jobs'], fmt=fmt)
            variant = native['variants'][0]
            for route, view, report, prefix, app, artifacts, compiler_summary, header_summary, log_name in (
                ('native', native_view, native, 'artifacts/simx-' + fmt, 'tests/regression/ai_mlp',
                 variant['artifacts_before'], variant['compiler_records'], variant['backend_header_macros'],
                 'logs/simx-' + fmt + '-effective-header.log'),
                ('python', python_view, python, 'artifacts/native-matmul', 'tests/regression/ai_matmul',
                 python['matmul_artifacts_before'], python['matmul_compiler_records'],
                 python['matmul_backend_header_macros'], 'logs/native-matmul-effective-header.log'),
            ):
                indexed = {row['path']: row for row in artifacts}
                members = {}
                for name in ('sw/runtime/simx_rt_config.stamp', 'sw/runtime/simx_config.stamp', app + '/config.stamp'):
                    member = prefix + '/' + name
                    members[member] = view.verified(dict(indexed[name], path=member))
                command = next(row for row in report['commands'] if row['log'] == log_name)
                raw = view.verified({'path': log_name, 'sha256': command['log_sha256'],
                                     'size_bytes': command['log_size_bytes']})
                selected.append((route, MemoryView(members), prefix, app, indexed,
                                 compiler_summary, header_summary, raw))
        for route, view, prefix, app, indexed, compiler_summary, header_summary, raw in selected:
            with ExitStack() as stack:
                stack.enter_context(patch.object(Path, 'open', side_effect=AssertionError('filesystem read')))
                stack.enter_context(patch.object(Path, 'resolve', side_effect=AssertionError('producer resolution')))
                stack.enter_context(patch('subprocess.Popen', side_effect=AssertionError('compiler launch')))
                records = replay._build_records(view, prefix, indexed, app=app, **common)
                replay._same(records, compiler_summary, route + ' compiler summary')
                if records[2]['role'] != 'kernel' or records[2]['configuration']['ITYPE'] != fmt:
                    raise AssertionError('actual compiler role/index/format differs')
                replay._same(replay._effective_header_macros(raw.decode('utf-8'), records[2]),
                             header_summary, route + ' effective-header summary')
                original_line = ('#define ITYPE ' + fmt + '\n').encode()
                if raw.count(original_line) != 1:
                    raise AssertionError('actual effective header lacks one selected format')
                other = 'bf16' if fmt == 'fp16' else 'fp16'
                changed = raw.replace(original_line, ('#define ITYPE ' + other + '\n').encode(), 1)
                try:
                    replay._effective_header_macros(changed.decode('utf-8'), records[2])
                except ValueError as error:
                    reason = str(error)
                    if reason != 'effective header ITYPE differs':
                        raise AssertionError('mutation failed outside the repaired join') from error
                else:
                    raise AssertionError('effective-header format mutation passed')
                observations.append({'format': fmt, 'route': route, 'archive_sha256': pin,
                    'archive_close_rehash': 'pass', 'control': 'accepted', 'mutation': 'rejected',
                    'reason': reason, 'kernel_record_role': records[2]['role'],
                    'kernel_record_sha256': records[2]['sha256'], 'header_sha256': sha256(raw),
                    'mutated_header_sha256': sha256(changed)})
    after = {name: sha256((ROOT / name).read_bytes()) for name in FILES}
    if before != after:
        raise AssertionError('source changed during the post-fix probe')
    result = {'command': 'python3 -B ../agent-notes/a47-postfix-probe.py',
        'scope': 'selected-member native/Python compiler plus effective-header helper joins, both c0 formats',
        'source_stable': True, 'source_before': before, 'source_after': after,
        'probe_sha256': sha256(Path(__file__).read_bytes()), 'observations': observations,
        'native_execution': 'not_run', 'retained_code_executed': False, 'public_replay_executed': False,
        'controls_accepted': 4, 'format_mutations_rejected': 4,
        'limitations': ['No full original replay or fully rewritten public candidate was executed.',
                       'Public reachability remains complete-caller static analysis.',
                       'Compiler binary bytes are absent; recorded tool receipts cannot prove reproducible compilation.']}
    target = ROOT.parent / 'agent-notes/a47-postfix-probe.json'
    target.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
