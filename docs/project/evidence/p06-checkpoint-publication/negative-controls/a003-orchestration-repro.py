#!/usr/bin/env python3
"""Offline synthetic reproduction; no native execution or network access."""

import json
from pathlib import Path
import sys
from unittest import mock

sys.dont_write_bytecode = True
REPO = Path('/tmp/ai-gpu-2bfab0261c05/repo')
sys.path.insert(0, str(REPO / 'ci/project'))

import p06_qualified_warm_hosted as hosted
import p06_qualified_warm_run as runner
from test_p06_qualified_warm_run import QualifiedWarmRunTests


for interrupt_at in (None, 1, 3, 10):
    case = QualifiedWarmRunTests()
    case.setUp()
    # Give hosted's read-only observation its production relative layout.
    case.workspace = case.root / 'workspace'
    case.args.workspace_dir = case.workspace
    case.paths['workspace'] = str(case.workspace)
    def complete_command_inventory(name, document, argv):
        if name == 'dependency-build':
            document['commands'] = []
        return 0
    case.change = complete_command_inventory
    real_fsync = runner.base.os.fsync
    writes = []
    def fsync(fd):
        writes.append(fd)
        if len(writes) == interrupt_at:
            raise KeyboardInterrupt('one-shot checkpoint interrupt')
        return real_fsync(fd)
    try:
        with mock.patch.object(runner, 'run_bounded', side_effect=case.child), \
                mock.patch.object(runner.base.os, 'fsync', side_effect=fsync):
            try:
                result = runner.execute(case.args)
                raised = None
            except BaseException as error:
                result = None
                raised = type(error).__name__ + ': ' + str(error)
        receipt = case.workspace / 'evidence' / runner.RECEIPT_PATH
        temporary = receipt.with_name(receipt.name + '.tmp')
        committed = json.loads(receipt.read_text()) if receipt.exists() else None
        pending = json.loads(temporary.read_text()) if temporary.exists() else None
        actual_native = case.workspace / 'evidence/qualified-warm/report.json'
        stages = [{'id': 'native-supervisor', 'process_started': True,
                   'cleanup_complete': True}]
        observed = {
            'scope': 'synthetic orchestration fixture; no native execution',
            'interrupt_at_checkpoint': interrupt_at,
            'exception': raised,
            'synthetic_completed_child_ids': [row['id'] for row in case.observed],
            'committed_state': None if committed is None else committed['state'],
            'committed_native_execution': None if committed is None else committed['native_execution'],
            'committed_stages': [] if committed is None else [row['id'] for row in committed['stages']],
            'temporary_remains': temporary.exists(),
            'temporary_native_execution': None if pending is None else pending['native_execution'],
            'synthetic_native_report_finished': actual_native.exists() and json.loads(actual_native.read_text())['state'] == 'finished',
            'hosted_writers_finished': hosted.writers_finished(case.root, stages),
            'hosted_observed_native_execution': hosted.observed_native_execution(case.root, case.revision),
        }
        print(json.dumps(observed, sort_keys=True))
    finally:
        case.doCleanups()
