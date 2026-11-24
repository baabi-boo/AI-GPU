#!/usr/bin/env python3
"""Agent 38: bounded inert BF16 original review, never a GPU execution."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import zipfile

BASE = Path('/workspace/scratch/101d52695253')
ROOT = BASE / 'AI-GPU'
ARCHIVE = BASE / 'originals/p05-torch-bf16-c0b44ce6-original.zip'
DIGEST = '787fd1b41a27da8c100277613c581ba734920fd45b13e0707ba0f9ea2e866330'
REVISION = 'c0b44ce64665fe11895f869eea8c38c9b820d6f7'
REVIEW_BASE = 'f01c9d03147343d274ee0a45b71b34f004709c0e'
sys.path.insert(0, str(ROOT / 'ci/project'))
import p05_torch_replay as replay


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def sha(body):
    return hashlib.sha256(body).hexdigest()


def file_sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def git(*args):
    result = subprocess.run(['git', *args], cwd=ROOT, capture_output=True, check=True)
    return result.stdout


def cli(fmt):
    command = [sys.executable, '-B', 'ci/project/p05_torch_replay.py',
               '--archive', str(ARCHIVE), '--sha256', DIGEST,
               '--expected-revision', REVISION, '--format', fmt]
    start = time.monotonic()
    proc = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=120,
                          env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
    value = json.loads(proc.stdout)
    return value, {'command': command, 'exit_code': proc.returncode,
                   'seconds': round(time.monotonic() - start, 6),
                   'stdout_sha256': sha(proc.stdout), 'stdout_bytes': len(proc.stdout),
                   'stderr_bytes': len(proc.stderr), 'stderr': proc.stderr.decode()}


before = replay._reader_sources()
head = git('rev-parse', 'HEAD').decode().strip()
status = git('status', '--short').decode()
dirty_installation_diff = git('diff', 'HEAD', '--', 'ci/project/p05_replay_installation.py')
start_digest = file_sha(ARCHIVE)
assert start_digest == DIGEST
result, invocation = cli('bf16')
assert invocation['exit_code'] == 0 and invocation['stderr_bytes'] == 0
assert result['outcome'] == 'pass' and result['format'] == 'bf16'
assert result['reader_sources'] == before == replay._reader_sources()
assert result['execution_revision'] == REVISION
assert result['native_execution'] == 'not_run'
assert all(result[key] is False for key in ('retained_code_executed', 'acceptance_claimed',
                                           'phase_acceptance', 'host_fault_semantics_revalidated'))
assert result['archive_read']['data_files'] == len(result['archive_read']['read_files']) == 663

# One negative public selection: identical original and revision, wrong format.
negative, negative_invocation = cli('fp16')
assert negative_invocation['exit_code'] == 1 and negative['outcome'] == 'fail'
assert negative['reason'] == 'framework report format differs'
assert negative['native_execution'] == 'not_run'

api = replay._archive_api()
with api.ArchiveReader(ARCHIVE, DIGEST) as reader:
    outer = reader.view()
    nv, pv, tv = (outer.subview(name) for name in ('native-model', 'python', 'torch'))
    nr, pr, tr = (view.json('report.json') for view in (nv, pv, tv))
    sources = [view.document(report['source_before'])
               for view, report in ((nv, nr), (pv, pr), (tv, tr))]
    checkout = sources[0]['checkout']
    assert all(source['checkout'] == checkout for source in sources)
    assert checkout['revision'] == REVISION and checkout['dirty'] is False
    for view, report, source in zip((nv, pv, tv), (nr, pr, tr), sources):
        assert view.document(report['source_after']) == source
    mb = nv.document(nr['variants'][0]['binding'])
    ab = pv.document(pr['matmul_binding'])
    model_id, matmul_id = sha(canonical(mb)), sha(canonical(ab))
    assert model_id == nr['variants'][0]['qualification_id'] == pr['native_qualification_id']
    assert matmul_id == pr['matmul_qualification_id']
    assert all(binding['format'] == 'bf16' and binding['backend'] == 'simx'
               and binding['source'] == checkout for binding in (mb, ab))
    compiler_rows = []
    for name, binding in (('model', mb), ('matmul', ab)):
        assert [row['role'] for row in binding['compiler_records']] == ['runtime', 'backend_cpp', 'kernel', 'host']
        for row in binding['compiler_records']:
            selected = {key: row['configuration'][key]
                        for key in ('ITYPE', 'OTYPE', 'KUNROLL', 'VX_CFG_TCU_TYPE', 'VX_CFG_XLEN')}
            assert selected == dict(ITYPE='bf16', OTYPE='fp32', KUNROLL='1', VX_CFG_TCU_TYPE='TFR', VX_CFG_XLEN='64')
            compiler_rows.append(dict(scope=name, role=row['role'], sha256=row['sha256'], configuration=selected))

    def raw_rows(view, path, marker):
        return [api.strict_json(line[len(marker) + 1:].encode(), integers_only=True)
                for line in view.read(path, limit=16*1024*1024).decode().splitlines()
                if line.startswith(marker + ' ')]

    nm = [row for case in pr['matmul_case_ids']
          for row in raw_rows(pv, 'logs/native-' + case + '.log', 'P03_RESULT')]
    nl = [row for case in nr['case_ids']
          for row in raw_rows(nv, 'logs/simx-bf16-' + case + '.log', 'P04_RESULT')]
    po = pv.document(pr['observations'], integers_only=True)
    to = tv.document(tr['observations'], integers_only=True)
    pm = raw_rows(pv, 'logs/installed-matrix.log', 'P05_MATMUL')
    pl = raw_rows(pv, 'logs/installed-matrix.log', 'P05_MODEL')
    fm = raw_rows(tv, 'logs/installed-framework-matrix.log', 'P05_MATMUL')
    fl = raw_rows(tv, 'logs/installed-framework-matrix.log', 'P05_MODEL')
    ftm = raw_rows(tv, 'logs/installed-framework-matrix.log', 'P05_TORCH_MATMUL')
    ftl = raw_rows(tv, 'logs/installed-framework-matrix.log', 'P05_TORCH_MODEL')
    assert pm == po['matmuls'] and pl == po['models']
    assert fm == to['base_observations']['matmuls'] and fl == to['base_observations']['models']
    assert ftm == to['framework_matmuls'] and ftl == to['framework_models']
    expected_matmul_ids = [(case, iteration) for case in pr['matmul_case_ids'] for iteration in (0, 1)]
    expected_model_ids = [(case, iteration) for case in nr['case_ids'] for iteration in (0, 1)]
    for rows in (nm, pm, fm, ftm):
        assert [(row['case_id'], row['iteration']) for row in rows] == expected_matmul_ids
    for rows in (pl, fl, ftl):
        assert [(row['case_id'], row['iteration']) for row in rows] == expected_model_ids
    assert [(row['trace']['case_id'], row['iteration']) for row in nl] == expected_model_ids
    assert all(row['format'] == 'bf16' and row['qualification_id'] == matmul_id for row in nm)
    assert all(row['trace']['input_dtype'] == 'bf16' and row['trace']['qualification_id'] == model_id
               for row in pm + fm)
    models = nl + [row['record'] for row in pl + fl]
    assert all(row['source_revision'] == REVISION and row['qualification_id'] == model_id
               and row['trace']['input_dtype'] == 'bf16' for row in models)
    assert all(row[key]['dtype'] == 'torch.bfloat16' for row in ftm for key in ('a', 'b'))
    assert all(row['result']['dtype'] == 'torch.float32' for row in ftm + ftl)
    assert all(a['actual_bits'] == b['actual_bits'] == c['actual_bits']
               for a, b, c in zip(nm, pm, fm))
    for n, p, f in zip(nl, pl, fl):
        for key in ('hidden_words', 'bridge_words', 'bridge_bytes', 'output_words'):
            assert n['trace'][key] == p['record']['trace'][key] == f['record']['trace'][key]
    native_launches = sum(row['dispatch']['launches'] for row in nm)
    native_launches += sum(stage['dispatch']['launches_enqueued'] for row in nl for stage in row['trace']['native'])
    def installed_counts(matmuls, models):
        traces = [row['trace'] for row in matmuls]
        traces += [stage['dispatch'] for row in models for stage in row['record']['trace']['native']]
        return sum(trace['launches_enqueued'] for trace in traces), sum(len(trace['event_profiles']) for trace in traces)
    python_launches, python_profiles = installed_counts(pm, pl)
    framework_launches, framework_profiles = installed_counts(fm, fl)
    assert (native_launches, python_launches, framework_launches, len(ftm)+len(ftl), framework_profiles) == (36, 36, 36, 16, 180)
    assert result['counts'] == dict(copied_packet_additional_launches=0, distinct_total_launches=108,
        framework_event_profile_pairs=180, framework_launches=36, framework_operator_calls=16,
        native_comparison_launches=36, plain_python_launches=36)
    manifest = pv.document(pr['bundle_manifest'], integers_only=True)
    assert manifest['format'] == 'bf16' and manifest['source_revision'] == REVISION
    assert manifest['native_binding'] == mb
    header = pv.read('artifacts/sdist-pin/p05_build_config.h')
    assert b'inline constexpr char format[] = "bf16";' in header
    assert REVISION.encode() in header and model_id.encode() in header
    wheel = tv.verified(tr['installed_wheel'])
    python_wheel = next(row for row in pr['packages'] if row['path'].endswith('.whl'))
    assert pv.verified(python_wheel) == wheel
    with zipfile.ZipFile(io.BytesIO(wheel)) as package:
        identities = []
        for name in ('vortex_ai/torch_ops.py', 'vortex_ai/_native.cpython-312-x86_64-linux-gnu.so'):
            body = package.read(name)
            assert body == pv.read('artifacts/installed/' + name)
            if name.endswith('torch_ops.py'):
                assert body == tv.read('artifacts/source/python/' + name)
                assert sha(body) == to['framework']['adapter_sha256']
            identities.append({'path': name, 'sha256': sha(body), 'size_bytes': len(body)})
    raw = dict(execution_revision=REVISION, execution_tree=checkout['tree'], format='bf16',
        source_before_after_equal=True, compiler_records=compiler_rows,
        model_qualification_id=model_id, matmul_qualification_id=matmul_id,
        matmul_ids=expected_matmul_ids, model_ids=expected_model_ids,
        raw_record_counts=dict(native_matmuls=len(nm), native_models=len(nl), python_matmuls=len(pm),
            python_models=len(pl), framework_native_matmuls=len(fm), framework_native_models=len(fl),
            framework_tensor_matmuls=len(ftm), framework_tensor_models=len(ftl)),
        derived_launches=[native_launches, python_launches, framework_launches],
        framework_operator_calls=len(ftm)+len(ftl), framework_event_profile_pairs=framework_profiles,
        native_python_framework_output_equality=True, bf16_operands_fp32_results=True,
        wheel=tr['installed_wheel'], bundle_manifest=tr['bundle_manifest'], adapter_and_extension=identities,
        declared_copy_launch_increment=0, generated_build_header_binds_bf16=True)
    raw_receipt = {key: value for key, value in reader.receipt().items() if key != 'read_files'}
# Reaching here is evidence that this independent read's close-time rehash returned.
final_digest = file_sha(ARCHIVE)
after = replay._reader_sources()
assert before == after and final_digest == start_digest == DIGEST
receipt = dict(agent=38, scope='actual-original-bf16-host-only-inert-review',
    review_base=REVIEW_BASE, reader_head=head, head_after=git('rev-parse', 'HEAD').decode().strip(),
    source_status_before=status, source_status_after=git('status', '--short').decode(),
    dirty_installation_diff_sha256=sha(dirty_installation_diff),
    original_sha256_before=start_digest, original_sha256_after=final_digest,
    public_replay={**invocation, **{key: result[key] for key in (
        'outcome','scope','execution_revision','format','provider_record','counts','native_execution',
        'retained_code_executed','acceptance_claimed','phase_acceptance','host_fault_semantics_revalidated',
        'installation','python_comparison','framework_comparison','limitations')}},
    public_archive_receipt={key:value for key,value in result['archive_read'].items() if key != 'read_files'},
    public_cli_success_after_close_rehash=True, reader_source_files_before_and_after=before,
    reader_sources_stable=True, negative_public_wrong_format={**negative_invocation,'result':negative},
    independent_raw_inspection=raw, independent_archive_receipt=raw_receipt,
    independent_archive_close_rehash_returned=True, current_source_native_execution='not_run',
    repository_source_modified_by_probe=False)
destination = BASE / 'agent-notes/a38-receipt.json'
destination.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
print(json.dumps({'receipt': str(destination), 'public_seconds': invocation['seconds'],
    'public_exit': invocation['exit_code'], 'negative_exit': negative_invocation['exit_code'],
    'reader_sources': len(before), 'counts': result['counts'], 'sha256': file_sha(destination)}, indent=2))
