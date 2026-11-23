from pathlib import Path
import ast
import hashlib
import json
import os
import subprocess
import sys
import time
import zipfile

ROOT = Path('/tmp/ai-gpu-native-lifetime-dfd857')
OUT = Path('/tmp/ai-gpu-native-lifetime-dfd857-work/w03_a05-replay')
BASE = '6130a2f7424932a6f3b7377ef8ae4816da2b304f'
NATIVE = ROOT / 'docs/project/evidence/p06-managed-preflight/native'
CLAIMS = ('qualified', 'ready_for_warm', 'warm_execution', 'full_warm_coverage',
          'acceptance_claimed', 'phase_acceptance', 'performance_acceptance')
PINS = (
    ('success', 'run-45085300171-attempt1.zip',
     'cee5be4dba875494f6eafb83484933ab7693428e4773b932a26d5b91bd17969d',
     '57248e73dfce4ae2d21d2cbdb82c3953eef2e3db',
     'source-inventory-57248e73.json',
     '72ca7e9237060ca2831a275811d27ec6fdb3507dfd9a00b693aa177aa68382e8',
     'source-derivation-57248e73.json',
     '3b25d30eceeee2dc5cebd1cce8ed7ab90da0fec64857e82fc7cc7fc3ca38e171'),
    ('failure', 'run-45084009157-attempt1.zip',
     '4f1e177ba930c132f5e8cc7558b3087d39789c346763f00a9d1bdd2a6d17d00c',
     '8756f40029e59c87546fa22f4da33acd4e5d8e02',
     'source-inventory-8756f400-replay.json',
     '57a1290e4cadb7e357d109b49ff7e2ee85459c42b9a54d9522e1e178f3323c30',
     'source-derivation-8756f400-replay.json',
     '492b142b047e71a84a62425aebf5d46bb35f2ec022a173d42d6463e04fe834b8'),
)
PROTECTED = (
    '.github/workflows/p06-managed-preflight-replay.yml',
    'ci/project/p06_managed_preflight_replay.py',
    'ci/project/p06_managed_preflight_source_export.py',
    'ci/project/p06_managed_preflight_sources.py',
    'ci/project/p06_managed_preflight_derivation.py',
    'ci/project/p06_managed_preflight_records.py',
    'ci/project/p06_managed_preflight_contract.py',
)

def identity(path):
    body = path.read_bytes()
    return {'path': path.relative_to(ROOT).as_posix(),
            'sha256': hashlib.sha256(body).hexdigest(), 'size_bytes': len(body)}

def selected_sources():
    names = {Path(x) for x in PROTECTED}
    todo = [ROOT / 'ci/project/p06_managed_preflight_replay.py',
            ROOT / 'ci/project/p06_native_lifetime_records.py']
    seen = set()
    while todo:
        path = todo.pop()
        if path in seen:
            continue
        seen.add(path)
        names.add(path.relative_to(ROOT))
        for node in ast.walk(ast.parse(path.read_bytes())):
            modules = ([entry.name.split('.')[0] for entry in node.names]
                       if isinstance(node, ast.Import) else
                       [node.module.split('.')[0]] if isinstance(node, ast.ImportFrom)
                       and node.module and node.level == 0 else [])
            for module in modules:
                candidate = ROOT / 'ci/project' / (module + '.py')
                if candidate.is_file():
                    todo.append(candidate)
    names.update((Path('ci/gen_config.py'),
                  Path('docs/project/evidence/p05-torch/reviews/archive_reader.py')))
    return [identity(ROOT / name) for name in sorted(names)]

OUT.mkdir(exist_ok=False)
report = {'scope': 'historical-v1-replay-and-lifetime-version-separation',
          'base_revision': BASE, 'checkout_head': subprocess.check_output(
              ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
          'native_execution': 'not_run', 'retained_code_executed': False,
          'acceptance_claimed': False, 'commands': [], 'inputs': []}
report['sources_before'] = selected_sources()
for _, archive, archive_sha, revision, inventory, inventory_sha, derivation, derivation_sha in PINS:
    for name, expected in ((archive, archive_sha), (inventory, inventory_sha),
                           (derivation, derivation_sha)):
        row = identity(NATIVE / name)
        assert row['sha256'] == expected, (name, row)
        report['inputs'].append(dict(row, expected_sha256=expected, source_revision=revision))

for mode, archive, archive_sha, revision, inventory, inventory_sha, derivation, derivation_sha in PINS:
    command = [sys.executable, '-B', 'ci/project/p06_managed_preflight_replay.py',
               '--archive', str(NATIVE / archive), '--sha256', archive_sha,
               '--source-revision', revision,
               '--source-inventory', str(NATIVE / inventory),
               '--source-inventory-sha256', inventory_sha,
               '--source-derivation', str(NATIVE / derivation),
               '--source-derivation-sha256', derivation_sha]
    if mode == 'success':
        command += ['--output', str(OUT / 'successful-replay.json')]
    started = time.monotonic()
    result = subprocess.run(command, cwd=ROOT, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'),
                            text=True, capture_output=True, timeout=120)
    elapsed = time.monotonic() - started
    (OUT / (mode + '.stdout')).write_text(result.stdout)
    (OUT / (mode + '.stderr')).write_text(result.stderr)
    data = json.loads(result.stdout)
    assert not result.stderr, result.stderr
    assert data['native_execution'] == 'not_run' and data['retained_code_executed'] is False
    assert all(data[name] is False for name in CLAIMS)
    if mode == 'success':
        assert result.returncode == 0 and data['outcome'] == 'pass', data
        assert data['counts']['processes'] == 4 and data['counts']['launches'] == 132
        assert data['counts']['checked_words'] == 4224
    else:
        expected = {'contract_id': 'p06-managed-counter-preflight-replay-v1',
                    'outcome': 'fail', 'reason': 'report.outcome: value differs',
                    'native_execution': 'not_run', 'retained_code_executed': False,
                    'dependency_compilation_provenance_verified': False,
                    **dict.fromkeys(CLAIMS, False)}
        assert result.returncode == 1 and data == expected, data
    report['commands'].append({'argv': command, 'exit_code': result.returncode,
                               'duration_seconds': elapsed, 'result': data})
    print(mode, 'expected result verified', f'{elapsed:.3f}s', flush=True)

sys.path.insert(0, str(ROOT / 'ci/project'))
import p06_native_lifetime_records as lifetime
report['historical_log_rejections'] = []
with zipfile.ZipFile(NATIVE / PINS[0][1]) as archive:
    names = archive.namelist()
    assert len(names) == len(set(names))
    for fmt in ('fp16', 'bf16'):
        for policy in ('per_operation', 'reusable_single_tile'):
            name = f'managed-preflight/logs/preflight-simx-{fmt}-{policy}.log'
            member = archive.getinfo(name)
            assert not member.is_dir() and 0 < member.file_size <= 16 * 1024**2
            body = archive.read(name)
            assert len(body) == member.file_size
            try:
                lifetime._split_output(body.decode('utf-8', errors='strict'))
            except ValueError as error:
                reason = str(error)
                assert reason == 'native lifetime requires exactly one lifetime witness', reason
            else:
                raise AssertionError('historical v1 log satisfied absent lifetime witness')
            report['historical_log_rejections'].append({'member': name,
                'sha256': hashlib.sha256(body).hexdigest(), 'size_bytes': len(body),
                'outcome': 'expected_rejection', 'reason': reason})

diff = subprocess.run(['git', 'diff', '--exit-code', BASE, '--', *PROTECTED],
                      cwd=ROOT, text=True, capture_output=True, timeout=30)
assert diff.returncode == 0 and not diff.stdout and not diff.stderr
report['unchanged_protected_paths'] = list(PROTECTED)
report['sources_after'] = selected_sources()
assert report['sources_after'] == report['sources_before'], 'selected reader sources changed during replay'
report['sources_stable'] = True
report['outcome'] = 'pass'
report['verification_script'] = {'path': __file__,
    'sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
(OUT / 'compatibility-receipt.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
print('four historical logs rejected specifically for absent lifetime witness', flush=True)
print('protected v1 paths unchanged; selected current source hashes stable', flush=True)
