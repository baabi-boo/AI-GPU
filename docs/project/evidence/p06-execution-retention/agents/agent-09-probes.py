"""Independent bounded packaging identity/recovery probes; synthetic bytes only."""

import errno
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import types
from unittest import mock

ROOT = Path('/tmp/ai-gpu-ae456f837c05/AI-GPU')
NOTES = ROOT.parent / 'notes'
sys.path.insert(0, str(ROOT / 'ci/project'))
import p06_qualified_warm_pack as candidate
import test_p06_qualified_warm_pack as fixtures

baseline_raw = subprocess.check_output(
    ['git', 'show', 'HEAD:ci/project/p06_qualified_warm_pack.py'], cwd=ROOT)
baseline = types.ModuleType('agent09_pack_baseline')
sys.modules[baseline.__name__] = baseline
exec(compile(baseline_raw, '<baseline-pack>', 'exec'), baseline.__dict__)


def fixture():
    case = fixtures.PrivatePackagingTests()
    case.setUp()
    return case


def identities(directory):
    return {p.name: {'sha256': hashlib.sha256(p.read_bytes()).hexdigest(),
                     'size_bytes': p.stat().st_size,
                     'links': p.stat().st_nlink}
            for p in directory.iterdir() if p.is_file()}


def fds():
    result = {}
    for path in Path('/proc/self/fd').iterdir():
        try:
            result[int(path.name)] = os.readlink(path)
        except FileNotFoundError:
            pass
    return result


def invoke(action, arguments):
    try:
        receipt = action(**arguments)
        return {'raised': None, 'packaging_passed': receipt['packaging_passed']}
    except BaseException as error:
        return {'raised': type(error).__name__, 'message': str(error)}


def initial_replacement(module):
    case = fixture()
    before = case.tree_bytes()
    saved = case.root / 'retained-output'
    inventory = module._inventory
    started = False

    def replace(selections):
        nonlocal started
        if not started:
            started = True
            case.output.rename(saved)
            case.output.mkdir(mode=0o755)
            (case.output / 'unrelated').write_bytes(b'unrelated\n')
        return inventory(selections)

    try:
        with mock.patch.object(module, '_inventory', side_effect=replace):
            result = invoke(module.package_partial, case.arguments())
        assert case.tree_bytes() == before
        result.update(retained_files=identities(saved), replacement_files=identities(case.output))
        return result
    finally:
        case.doCleanups()


def restored_leaf_below_new_parent():
    case = fixture()
    parent = case.root / 'private-parent'
    parent.mkdir(mode=0o700)
    case.output = parent / 'output'
    old_parent = parent.stat()
    saved = case.root / 'displaced-parent'
    inventory = candidate._inventory
    leaf_identity = None

    def replace(selections):
        nonlocal leaf_identity
        if leaf_identity is None:
            info = case.output.stat()
            leaf_identity = (info.st_dev, info.st_ino, info.st_mode)
            parent.rename(saved)
            parent.mkdir(mode=0o755)
            (saved / 'output').rename(case.output)
        return inventory(selections)

    try:
        with mock.patch.object(candidate, '_inventory', side_effect=replace):
            result = invoke(candidate.package_partial, case.arguments())
        info = case.output.stat()
        result.update(same_leaf=leaf_identity == (info.st_dev, info.st_ino, info.st_mode),
                      parent_changed=parent.stat().st_ino != old_parent.st_ino,
                      output_mode=oct(stat.S_IMODE(info.st_mode)))
        assert result['packaging_passed'] and result['same_leaf'] and result['parent_changed']
        return result
    finally:
        case.doCleanups()


def recovery(*, ancestor=False, before_unlink=False, receipt_link_fault=None):
    case = fixture()
    source_before = case.tree_bytes()
    if ancestor:
        parent = case.root / 'private-parent'
        parent.mkdir(mode=0o700)
        case.output = parent / 'output'
        saved_parent = case.root / 'displaced-parent'
        retained = saved_parent / 'output'
    else:
        retained = case.root / 'retained-output'
    publish, link = candidate._publish, os.link
    interrupted = False
    published_receipt = None
    replacement_bytes = {name: b'unrelated replacement\n' for name in
                         (candidate.ORIGINAL_NAME, candidate.RECEIPT_NAME, candidate.FAILURE_NAME)}

    def fault_link(source, target, *args, **kwargs):
        if source == candidate.RECEIPT_NAME and kwargs.get('src_dir_fd') is not None:
            if receipt_link_fault == 'after-link':
                link(source, target, *args, **kwargs)
            if receipt_link_fault is not None:
                raise OSError(errno.ENOSPC, 'injected receipt withdrawal link failure')
        return link(source, target, *args, **kwargs)

    def relocate():
        if ancestor:
            parent.rename(saved_parent)
            parent.mkdir(mode=0o755)
            case.output.mkdir(mode=0o755)
        else:
            case.output.rename(retained)
            case.output.mkdir(mode=0o755)
        for name, body in replacement_bytes.items():
            (case.output / name).write_bytes(body)

    def interrupt(source, target):
        nonlocal interrupted, published_receipt
        if before_unlink and target.name == candidate.PARTIAL_NAME:
            link(source, target, follow_symlinks=False)
            relocate()
            interrupted = True
            raise KeyboardInterrupt()
        publish(source, target)
        if target.name == candidate.RECEIPT_NAME:
            published_receipt = json.loads(target.read_bytes())
            relocate()
            interrupted = True
            raise KeyboardInterrupt()

    before_fds = fds()
    try:
        with mock.patch.object(candidate, '_publish', side_effect=interrupt), \
                mock.patch.object(candidate.os, 'link', side_effect=fault_link):
            action = candidate.package_partial if before_unlink else candidate.package_success
            result = invoke(action, case.arguments())
        assert interrupted and result['raised'] == 'KeyboardInterrupt'
        assert case.tree_bytes() == source_before
        assert {p.name: p.read_bytes() for p in case.output.iterdir()} == replacement_bytes
        assert fds() == before_fds
        failure = json.loads((retained / candidate.FAILURE_NAME).read_bytes())
        assert failure['packaging_passed'] is False
        assert failure['published_receipt_withdrawal_unresolved'] is (receipt_link_fault is not None)
        retained_rows = {row['filename']: row for row in failure['created_files']}
        observed = identities(retained)
        for name, row in retained_rows.items():
            assert row['sha256'] == observed[name]['sha256']
            assert row['size_bytes'] == observed[name]['size_bytes']
        if receipt_link_fault is None:
            assert candidate.RECEIPT_NAME not in observed
            assert all(name.startswith('incomplete-') for name in retained_rows)
            assert all(observed[name]['links'] == 1 for name in retained_rows)
        else:
            assert candidate.RECEIPT_NAME in observed
            for archive in published_receipt['archives']:
                assert observed[archive['filename']]['sha256'] == archive['sha256']
                assert observed[archive['filename']]['links'] == 1
        result.update(receipt_withdrawal_unresolved=failure['published_receipt_withdrawal_unresolved'],
                      source_unchanged=True, replacement_unchanged=True, descriptor_leak=False,
                      retained_files=observed, failure_files=retained_rows)
        return result
    finally:
        case.doCleanups()


def initial_fstat_interrupt():
    case = fixture()
    original = os.fstat
    caught_fd = None

    def interrupt(descriptor):
        nonlocal caught_fd
        if caught_fd is None and os.readlink('/proc/self/fd/' + str(descriptor)) == str(case.output):
            caught_fd = descriptor
            raise KeyboardInterrupt()
        return original(descriptor)

    before = fds()
    try:
        with mock.patch.object(candidate.os, 'fstat', side_effect=interrupt):
            result = invoke(candidate.package_partial, case.arguments())
        leaked = {fd: target for fd, target in fds().items() if fd not in before}
        result.update(leaked_descriptor_count=len(leaked),
                      leak_points_to_created_output=leaked.get(caught_fd) == str(case.output),
                      output_files=sorted(p.name for p in case.output.iterdir()))
        assert result['raised'] == 'KeyboardInterrupt' and len(leaked) == 1
        for descriptor in leaked:
            os.close(descriptor)
        assert fds() == before
        return result
    finally:
        case.doCleanups()


results = {
    'base_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
    'python': sys.version,
    'baseline_sha256': hashlib.sha256(baseline_raw).hexdigest(),
    'candidate_sha256': hashlib.sha256((ROOT / 'ci/project/p06_qualified_warm_pack.py').read_bytes()).hexdigest(),
    'baseline_initial_replacement': initial_replacement(baseline),
    'candidate_initial_replacement': initial_replacement(candidate),
    'ancestor_replaced_original_leaf_restored': restored_leaf_below_new_parent(),
    'ancestor_replacement_after_receipt_publication': recovery(ancestor=True),
    'replacement_after_archive_link_before_unlink': recovery(before_unlink=True),
    'replacement_receipt_withdrawal_link_failure': recovery(receipt_link_fault='before-link'),
    'replacement_receipt_withdrawal_failure_after_link': recovery(receipt_link_fault='after-link'),
    'initial_output_fstat_interrupt': initial_fstat_interrupt(),
}
assert results['baseline_initial_replacement']['packaging_passed'] is True
assert results['candidate_initial_replacement']['raised'] == 'ValueError'
assert len(results['candidate_initial_replacement']['replacement_files']) == 1
(NOTES / 'agent-09-probes.json').write_text(json.dumps(results, sort_keys=True, indent=2) + '\n')
print('Eight independent probes completed; all expected observations asserted.')
print('Known F2 reproduction fixed; early-fstat interrupt leaks one fd (narrow F1).')
