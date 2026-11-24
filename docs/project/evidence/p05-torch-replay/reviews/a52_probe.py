"""Bounded host-only inventory audit; trusted synthetic fixture, no originals."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path('/workspace/scratch/101d52695253/AI-GPU')
sys.path.insert(0, str(ROOT / 'ci/project'))
sys.dont_write_bytecode = True
tempfile.tempdir = '/tmp'
import p05_replay_installation as r
from p06_replay import _archive_api
from test_p05_replay_installation import SyntheticInstallation, encoded, record
from test_p05_replay_installation_identity import transfer_files

SOURCES = ('ci/project/p05_replay_installation.py', 'ci/project/p05_torch_replay.py',
           'ci/project/p05_torch_contract.json', 'ci/project/p05_torch_requirements.lock',
           'ci/project/test_p05_replay_installation.py',
           'ci/project/test_p05_replay_installation_identity.py',
           'docs/project/evidence/p05-torch/reviews/archive_reader.py')
def hashes():
    return {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in SOURCES}

before = hashes()
api = _archive_api()
results = []
def case(name, operation, error=None):
    try:
        operation()
    except ValueError as exc:
        ok = error is not None and error in str(exc)
        results.append({'id': name, 'expected': 'reject' if error else 'accept',
                        'pass': ok, 'message': str(exc)})
    else:
        results.append({'id': name, 'expected': 'reject' if error else 'accept',
                        'pass': error is None})
    if not results[-1]['pass']:
        print(json.dumps(results[-1]), flush=True)

def inv(rows, **kwargs):
    return r._inventory(rows, api, 'audit', **kwargs)

a = {'path': 'a', 'sha256': 'a' * 64, 'size_bytes': 0}
b = {**a, 'path': 'b'}
case('zero_byte_descriptor', lambda: inv([a]))
case('per_file_exact_2gib', lambda: inv([{**a, 'size_bytes': r.EXTERNAL_FILE_BYTES}]))
case('per_file_over_by_one', lambda: inv([{**a, 'size_bytes': r.EXTERNAL_FILE_BYTES + 1}]), 'file size')
case('total_exact_3gib', lambda: inv([{**a, 'size_bytes': 2 * 1024**3}, {**b, 'size_bytes': 1024**3}]))
case('total_over_by_one', lambda: inv([{**a, 'size_bytes': 2 * 1024**3}, {**b, 'size_bytes': 1024**3 + 1}]), 'total byte bound')
rows = [{**a, 'path': f'x/{i:05d}'} for i in range(50000)]
case('count_exact_50000', lambda: inv(rows))
case('count_50001', lambda: inv(rows + [{**a, 'path': 'x/50000'}]), 'inventory')
del rows
case('empty_inventory', lambda: inv([]), 'inventory')
for name, size in [('bool', True), ('negative', -1), ('float', 1.0)]:
    case('size_' + name, lambda size=size: inv([{**a, 'size_bytes': size}]), 'file size')
for name, digest in [('uppercase', 'A' * 64), ('short', 'a' * 63)]:
    case('digest_' + name, lambda digest=digest: inv([{**a, 'sha256': digest}]), 'digest')
case('duplicate_path', lambda: inv([a, a]), 'repeats a path')
case('file_directory_collision', lambda: inv([a, {**a, 'path': 'a/b'}]), 'file/directory collision')
case('reordered_inventory', lambda: inv([b, a]), 'reordered')
case('unordered_distribution_allowed', lambda: inv([b, a], ordered=False))
case('relative_dot_alias', lambda: inv([{**a, 'path': 'a/./b'}]), 'noncanonical')
case('extra_descriptor_field', lambda: inv([{**a, 'extra': None}]), 'fields')
case('absolute_descriptor', lambda: inv([{**a, 'path': '/producer/a'}], absolute=True))
case('absolute_rejected_in_relative', lambda: inv([{**a, 'path': '/producer/a'}]), 'noncanonical')
case('entrypoint_lexical_parent', lambda: r._same(r._distribution_path('../../../bin/torchrun', api), 'bin/torchrun', 'path'))
case('distribution_venv_escape', lambda: r._distribution_path('../../../../escape', api), 'escapes')

def snap(f, key, change, packet='torch'):
    report = f.tr if packet == 'torch' else f.pr
    value = f.snapshot_value(packet, report, key)
    change(value)
    f.snapshot(packet, report, key, value)

def pair(f, keys, change):
    for key in keys:
        snap(f, key, change)

def fixture_case(name, mutate, error):
    def run():
        f = SyntheticInstallation()
        mutate(f)
        return f.run()
    case(name, run, error)

case('complete_synthetic_installation', lambda: SyntheticInstallation().run())
fixture_case('contract_byte_pin', lambda f: f.tr.update(contract=f.put('torch', 'artifacts/source/' + r.CONTRACT, f.contract_raw + b'\n')), 'unsupported frozen')
fixture_case('lock_byte_pin', lambda f: f.tr.update(requirements=f.put('torch', 'artifacts/source/' + r.LOCK, f.lock_raw.replace(b'filelock==4.2.12', b'filelock==4.2.13'))), 'lock pin')
for field, value in [('path', 'other-1-py3-none-any.whl'), ('sha256', '0' * 64), ('size_bytes', 0)]:
    fixture_case('wheelhouse_' + field, lambda f, field=field, value=value: f.tr['wheelhouse']['files'][0].update({field: value}), 'wheelhouse lock')
fixture_case('wheelhouse_duplicate', lambda f: f.tr['wheelhouse']['files'].append(copy.deepcopy(f.tr['wheelhouse']['files'][0])), 'wheelhouse lock')
fixture_case('wheelhouse_after_drift', lambda f: snap(f, 'wheelhouse_after', lambda v: v[0].update(sha256='0' * 64)), 'wheelhouse stability')
fixture_case('installed_after_drift', lambda f: snap(f, 'installed_after', lambda v: v[0].update(sha256='0' * 64)), 'installation stability')
fixture_case('seed_identity_drift', lambda f: snap(f, 'venv_seed', lambda v: v[0].update(sha256='0' * 64)), 'seed stability')
fixture_case('seed_payload_overlap', lambda f: snap(f, 'venv_seed', lambda v: (v.append(copy.deepcopy(f.snapshot_value('torch', f.tr, 'framework_wheel_payload')[0])), v.sort(key=lambda row: row['path']))), 'seed overlaps')
fixture_case('missing_entrypoint', lambda f: pair(f, ('installed_before', 'installed_after'), lambda v: v.__setitem__(slice(None), [row for row in v if row['path'] != 'bin/torchrun'])), 'unexplained or missing')
fixture_case('entrypoint_order', lambda f: f.tr['framework_entry_points'].reverse(), 'recorded entry points')
root = r.SITE + 'filelock-4.2.12.dist-info/'
fixture_case('missing_metadata', lambda f: snap(f, 'framework_wheel_payload', lambda v: v.__setitem__(slice(None), [row for row in v if row['path'] != root + 'WHEEL'])), 'lacks distribution metadata')
fixture_case('missing_distribution_root', lambda f: snap(f, 'framework_wheel_payload', lambda v: v.__setitem__(slice(None), [row for row in v if row['path'] != root + 'RECORD'])), 'distribution roots')
fixture_case('payload_identity_drift', lambda f: snap(f, 'framework_wheel_payload', lambda v: next(row for row in v if row['path'] == f.large_path).update(sha256='0' * 64)), 'payload/installation')
env_keys = ('framework_before', 'framework_after')
fixture_case('distribution_version', lambda f: pair(f, env_keys, lambda v: v['distributions']['filelock'].update(version='4.2.13')), 'distribution version')
fixture_case('distribution_name_alias', lambda f: pair(f, env_keys, lambda v: v['distributions'].__setitem__('Jinja2', v['distributions'].pop('jinja2'))), 'distribution closure')
fixture_case('distribution_overlap', lambda f: pair(f, env_keys, lambda v: v['distributions']['filelock']['files'].append(copy.deepcopy(v['distributions']['torch']['files'][0]))), 'overlapping files')
fixture_case('distribution_coverage', lambda f: pair(f, env_keys, lambda v: v['distributions']['torch'].__setitem__('files', [row for row in v['distributions']['torch']['files'] if row['path'] != f.large_path])), 'omit installed wheel')
fixture_case('first_party_transfer', lambda f: transfer_files(f, 'vortex_ai', 'torch', {r.SITE + 'vortex_ai/torch_ops.py'}), 'first-party distribution membership')
fixture_case('first_party_absorb_seed', lambda f: transfer_files(f, 'pip', 'vortex_ai', {'bin/pip'}), 'first-party distribution membership')
fixture_case('environment_after_drift', lambda f: snap(f, 'framework_after', lambda v: v.update(gil=False)), 'environment stability')

def raw_mutation(f, change):
    path = 'torch/logs/framework-environment-before.log'
    raw = json.loads(f.files[path].split(b' ', 1)[1])
    change(raw)
    f.files[path] = b'P05_TORCH_ENVIRONMENT ' + encoded(raw) + b'\n'

fixture_case('raw_normalized_alias_duplicate', lambda f: raw_mutation(f, lambda v: (v['distributions']['torch']['files'].append('torch/../torch/__init__.py'), v['distributions']['torch']['files'].sort())), 'aliases or uninventoried')
fixture_case('raw_omission', lambda f: raw_mutation(f, lambda v: v['distributions']['torch']['files'].remove('torch/__init__.py')), 'raw framework environment')
fixture_case('raw_version_drift', lambda f: raw_mutation(f, lambda v: v['distributions']['torch'].update(version='2.14.0+cpu')), 'raw framework environment')

contract = json.loads((ROOT / r.CONTRACT).read_bytes())
lock = (ROOT / r.LOCK).read_text()
assert hashlib.sha256((ROOT / r.CONTRACT).read_bytes()).hexdigest() == r.CONTRACT_SHA256
assert hashlib.sha256(lock.encode()).hexdigest() == contract['requirements']['sha256']
assert [line for line in lock.splitlines() if line and not line.startswith('#')] == [w['name'] + '==' + w['version'] + ' --hash=sha256:' + w['sha256'] for w in contract['wheels']]
receipts = {}
for fmt in ('fp16', 'bf16'):
    path = ROOT.parent / 'validation' / ('c6-' + fmt + '-replay.json')
    raw = path.read_bytes()
    d = json.loads(raw)
    summary = d['installation']
    receipts[fmt] = {'sha256': hashlib.sha256(raw).hexdigest(), 'execution_revision': d['execution_revision'],
                     'outcome': d['outcome'], 'source_scope': 'prior receipt read only; no original rerun',
                     **{k: v for k, v in summary.items() if k.endswith('_receipts') or k.endswith('_rehashed')}}

after = hashes()
out = {'scope': 'helper composition synthetic controls; no public archive replay',
       'source_before': before, 'source_after': after, 'source_stable': before == after,
       'probe_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
       'bounds': {'per_file': r.EXTERNAL_FILE_BYTES, 'total': r.EXTERNAL_TOTAL_BYTES, 'count': r.EXTERNAL_FILES},
       'locked_wheels': [{k: w[k] for k in ('name', 'version', 'filename', 'sha256', 'size')} for w in contract['wheels']],
       'prior_c6_receipts': receipts, 'cases': results,
       'summary': {'cases': len(results), 'passed': sum(v['pass'] for v in results),
                   'expected_accept': sum(v['expected'] == 'accept' for v in results),
                   'expected_reject': sum(v['expected'] == 'reject' for v in results)}}
path = ROOT.parent / 'agent-notes/a52-probe.json'
path.write_text(json.dumps(out, sort_keys=True, indent=2) + '\n')
print(json.dumps({'summary': out['summary'], 'source_stable': out['source_stable'],
                  'evidence_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}))
raise SystemExit(0 if all(v['pass'] for v in results) and before == after else 1)
