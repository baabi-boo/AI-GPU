import datetime
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess

ROOT = Path('/tmp/ai-gpu-native-lifetime-dfd857')
WORK = Path('/tmp/ai-gpu-native-lifetime-dfd857-work')
BASE = '6130a2f7424932a6f3b7377ef8ae4816da2b304f'
PARENT = 'b4127b19a004b5aebb8d52eab9ceda0da3ff4561'
TREE = 'e7d178ebdbd48ff65e861cd4747f1f0fc39a1435'
PACKET = 'docs/project/evidence/p06-native-lifetime/'
ZIP_PATH = PACKET + 'native/b4127b19-run45130300651-attempt1/original.zip'


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def tree_rows(ref):
    result = {}
    for row in git('ls-tree', '-rz', '--full-tree', ref).split(b'\0'):
        if not row:
            continue
        header, path = row.split(b'\t', 1)
        mode, kind, sha = header.decode().split()
        result[path.decode()] = {'mode': mode, 'type': kind, 'sha': sha}
    return result


def read_blobs(shas):
    shas = sorted(set(shas))
    assert all(re.fullmatch('[0-9a-f]{40}', s) for s in shas)
    result = subprocess.run(['git', 'cat-file', '--batch'], cwd=ROOT,
                            input=('\n'.join(shas) + '\n').encode(),
                            stdout=subprocess.PIPE, check=True).stdout
    blobs = {}
    offset = 0
    for expected in shas:
        end = result.index(b'\n', offset)
        sha, kind, length = result[offset:end].decode().split()
        assert sha == expected and kind == 'blob'
        size = int(length)
        start = end + 1
        blobs[sha] = result[start:start + size]
        assert result[start + size:start + size + 1] == b'\n'
        offset = start + size + 1
    assert offset == len(result)
    return blobs


before = tree_rows(PARENT)
after = tree_rows(TREE)
audit_base = tree_rows(BASE)
plan = json.loads((WORK / 'prepublication-review-tree.json').read_text())
changed = sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))
assert changed == plan['changed_paths']
assert len(changed) == 143
assert set(before) <= set(after)
current_documents = {
    'README.md', 'docs/index.md', 'docs/project/backlog.md',
    'docs/project/index.md', 'docs/project/p06-managed-preflight-handoff.md',
    'docs/project/p06-mpm-qualification-plan.md', 'docs/project/p06-workspace-handoff.md',
    'docs/project/phases/p06-performance.md', 'docs/project/status.md',
    'docs/project/p06-dependency-provenance-handoff.md',
}
assert all(p in current_documents or p.startswith(PACKET) for p in changed)
assert all(after[p]['mode'] == '100644' and after[p]['type'] == 'blob' for p in changed)
assert all(before[p]['mode'] == after[p]['mode'] for p in changed if p in before)
assert all(before[p]['type'] == after[p]['type'] for p in changed if p in before)
projection = json.loads((WORK / 'w09_a02-projection.json').read_text())
source_rows = projection['root_source_join']
assert len(source_rows) == 813
assert len({r['path'] for r in source_rows}) == 813
source_paths = {r['path'] for r in source_rows}
assert not source_paths.intersection(changed)
policy_paths = ['AGENTS.md', 'ci/change_impact.py',
                'docs/review/change-impact.yaml', 'docs/review/code-review-policy.md']
assert all(audit_base[p] == before[p] == after[p] for p in policy_paths)
assert '.gitattributes' not in audit_base and '.gitattributes' not in before and '.gitattributes' not in after
blobs = read_blobs([after[p]['sha'] for p in changed] +
                   [after[r['path']]['sha'] for r in source_rows] +
                   [after[p]['sha'] for p in policy_paths])
descriptors = []
for row in source_rows:
    path = row['path']
    assert not PurePosixPath(path).is_absolute() and '..' not in PurePosixPath(path).parts
    expected = {'mode': row['git_mode'], 'type': 'blob', 'sha': row['git_blob_sha']}
    assert before[path] == after[path] == expected, path
    data = blobs[after[path]['sha']]
    assert hashlib.sha256(data).hexdigest() == row['sha256'] and len(data) == row['size_bytes'], path
    current = ROOT / path
    assert current.is_file() and not current.is_symlink(), path
    assert current.read_bytes() == data, path
    current_mode = '100755' if current.stat().st_mode & 0o111 else '100644'
    assert current_mode == row['git_mode'], path
    descriptors.append({key: row[key] for key in projection['inventory_descriptor_fields']})
descriptors.sort(key=lambda r: r['path'])
source_hash = hashlib.sha256(json.dumps(descriptors, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()
assert source_hash == projection['root_source_inventory_sha256']
assert source_hash == 'd096aef75122b0640c0ef528fcf6797555ed96ce82815de18bd60c3915a6e595'
for row in projection['frozen_design_contracts']:
    assert before[row['path']] == after[row['path']]
    assert after[row['path']]['sha'] == row['git_blob_sha']
zip_bytes = blobs[after[ZIP_PATH]['sha']]
assert after[ZIP_PATH]['sha'] == '5a9dae6b08ca7b3ee789363666be4827eb553ab8'
assert len(zip_bytes) == 9086055
assert hashlib.sha256(zip_bytes).hexdigest() == '3d4879f73c197352689d65feb56e73f537701fc1411e55bf53c92b1b41e13db3'
assert zip_bytes == (ROOT / ZIP_PATH).read_bytes() == (WORK / 'native-original.zip').read_bytes()
assert git('check-attr', '--all', '--', ZIP_PATH) == b''
governance_path = PACKET + 'ci/b4127b19-full-governance-original.log'
governance = blobs[after[governance_path]['sha']]
assert len(governance) == 801092
assert hashlib.sha256(governance).hexdigest() == '244af36ef253e5edb2c27aa79a4ac3f925f81a05203b83201bb444b49e9621f9'
assert b'Ran 3813 tests in 2498.078s' in governance
assert b'2026-11-23T08:01:51.9626781Z OK' in governance
ledger = json.loads(blobs[after[PACKET + 'agent-execution.json']['sha']])
assert ledger['actual_distinct_assignments'] == 58 and ledger['completed_assignments'] == 56
assert len(ledger['assignments']) == 58
assert len({a['canonical_task_name'] for a in ledger['assignments']}) == 58
for row in ledger['assignments']:
    if row['status'] != 'completed':
        continue
    path = PACKET + row['report']
    data = git('cat-file', 'blob', after[path]['sha'])
    assert hashlib.sha256(data).hexdigest() == row['report_sha256']
    assert len(data) == row['report_bytes']
    assert data == (WORK / Path(row['report']).name).read_bytes()
manifest = []
binary_paths = []
for path in changed:
    data = blobs[after[path]['sha']]
    if path != ZIP_PATH:
        data.decode('utf-8')
        assert b'\0' not in data
    else:
        binary_paths.append(path)
    manifest.append({'path': path, 'status': 'M' if path in before else 'A',
                     **after[path], 'size_bytes': len(data),
                     'sha256': hashlib.sha256(data).hexdigest()})
assert binary_paths == [ZIP_PATH]
check = subprocess.run(['git', 'diff', '--check', PARENT, TREE], cwd=ROOT,
                       capture_output=True, text=True)
(WORK / 'w10_a05-full-diff-check.txt').write_text(check.stdout + check.stderr)
original_logs = {
    PACKET + 'ci/b4127b19-full-governance-original.log': 'full-governance-original.log',
    PACKET + 'development-history/w03_a02-tests-attempt1.log': 'w03_a02-tests-attempt1.log',
    PACKET + 'development-history/w03_a02-tests-attempt2.log': 'w03_a02-tests-attempt2.log',
    PACKET + 'host-controls/w06_a04-job-137544020957.log': 'w06_a04-job-137544020957.log',
    PACKET + 'host-controls/w06_a04-job-137544021412.log': 'w06_a04-job-137544021412.log',
    PACKET + 'native/b4127b19-run45130300651-attempt1/job-original.log': 'native-job-original.log',
}
diagnostics = re.findall(r'^([^\n]+):(\d+): (trailing whitespace\.)$', check.stdout, re.M)
assert check.returncode == 2 and check.stderr == ''
assert {row[0] for row in diagnostics} == set(original_logs)
assert sum(1 for line in check.stdout.splitlines() if not line.startswith('+')) == len(diagnostics)
for path, work_name in original_logs.items():
    assert blobs[after[path]['sha']] == (WORK / work_name).read_bytes(), path
authored_check = subprocess.run(['git', 'diff', '--check', PARENT, TREE, '--', '.',
                                *[':(exclude)' + p for p in sorted(original_logs)]],
                               cwd=ROOT, capture_output=True, text=True)
assert authored_check.returncode == 0, authored_check.stdout + authored_check.stderr
immutable_dir = WORK / 'w10_a01-immutable-base'
for path, filename in [('ci/change_impact.py', 'change_impact.py'),
                       ('docs/review/change-impact.yaml', 'change-impact.yaml')]:
    assert (immutable_dir / filename).read_bytes() == blobs[after[path]['sha']]
classifier = ['python3', '-I', str(immutable_dir / 'change_impact.py'),
              '--repo', str(ROOT), '--policy', str(immutable_dir / 'change-impact.yaml')]
implementation_class = subprocess.run(classifier + ['explain', '--base', BASE, '--head', PARENT],
                                      capture_output=True, text=True, check=True).stdout
paths_class = subprocess.run(classifier + ['explain', '--path', *changed],
                             capture_output=True, text=True, check=True).stdout
(WORK / 'w10_a05-implementation-classification.txt').write_text(implementation_class)
(WORK / 'w10_a05-prepared-path-classification.txt').write_text(paths_class)
assert implementation_class.startswith('R2 ')
path_lines = paths_class.splitlines()
assert path_lines[::2] == changed
assert all(line == '  path rule prose -> R0' for line in path_lines[1::2])
remote = json.loads((WORK / 'w10_a05-remote.json').read_text())
assert remote['ref']['ref'] == 'refs/heads/master'
assert remote['ref']['object']['sha'] == PARENT
assert remote['commit']['sha'] == PARENT
assert remote['commit']['tree']['sha'] == 'bd37fb53ab1c34dfebc2ac8805abff5877735fc4'
receipt = {
    'scope': 'Independent inert review of immutable prepared Git tree and publication plan; no final publication claim.',
    'observed_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'prepared_tree': TREE, 'expected_parent': PARENT,
    'parent_tree': remote['commit']['tree']['sha'], 'audit_base': BASE,
    'outcome': 'pass', 'findings': [], 'repository_mutated_by_reviewer': False,
    'retained_programs_executed': False, 'tests_or_builds_run': False,
    'remote_writes': False, 'changed_paths': len(changed),
    'added_paths': sum(row['status'] == 'A' for row in manifest),
    'modified_paths': sum(row['status'] == 'M' for row in manifest),
    'deleted_paths': 0, 'mode_or_type_changes': 0,
    'current_document_paths': sorted(current_documents),
    'evidence_packet_changed_paths': sum(p.startswith(PACKET) for p in changed),
    'binary_paths': binary_paths, 'all_changed_modes': ['100644'],
    'projected_source_count': len(source_rows), 'root_source_inventory_sha256': source_hash,
    'frozen_contract_count': len(projection['frozen_design_contracts']),
    'protected_policy_paths': policy_paths, 'root_gitattributes_absent': True,
    'archive_attributes': {}, 'archive': next(row for row in manifest if row['path'] == ZIP_PATH),
    'governance_original': next(row for row in manifest if row['path'] == governance_path),
    'prepared_ledger': {'actual_assignments': 58, 'completed_assignments': 56,
                        'all_completed_report_hashes_match': True,
                        'scope': 'Prepared snapshot only. No prospective 60-agent completion asserted.'},
    'classification': {'implementation_automatic': 'R2', 'manual_program_review': 'R3',
                       'prepared_path_rules': 'R0'},
    'whitespace_check': {
        'full_range_exit': check.returncode,
        'full_range_output': 'w10_a05-full-diff-check.txt',
        'trailing_whitespace_diagnostics': len(diagnostics),
        'original_log_paths': sorted(original_logs),
        'all_six_original_log_bytes_match': True,
        'authored_files_check_exit': authored_check.returncode,
        'scope': 'Full check reports only original trailing spaces in six exact retained logs; all other changed files pass. No bytes, Git attributes, classifier policy or configuration were changed to suppress the diagnostics.'
    },
    'reviewer_correction': 'The initial check incorrectly assumed the full diff whitespace check would pass. It exposed preserved trailing spaces in exact original logs. The corrected receipt retains the full nonzero result and separately checks all other changed files, without altering originals or enforcement. A subsequent review-only assertion was corrected to parse the classifier path-display format as its actual path/rule pairs; neither correction changed repository inputs or classification.',
    'remote_snapshot_file': 'w10_a05-remote.json',
    'remote_snapshot_sha256': hashlib.sha256((WORK / 'w10_a05-remote.json').read_bytes()).hexdigest(),
    'manifest': manifest,
    'remaining_conditions': [
        'Review the exact final delta from this prepared tree: only authorized remaining review notes/receipts, actual completed ledger, audit/current status and CI evidence; recheck source projection and archive blob.',
        'Finish all 60 actual delegated assignments; retain final reports, their exact hashes and six completed slots per wave, without counting root/followups.',
        'Run final cheap project metadata/baseline and diff checks; run immutable-base classifier on the final local commit; retain manual R3 scope.',
        'Re-read the remote head immediately before final publication. If changed, preserve and integrate concurrent work before reconstructing and reviewing the candidate.',
        'Construct the API tree from the verified parent tree and exact final Git blobs/modes, then require complete API tree SHA equality with final local commit tree.',
        'Create the API commit with the verified current remote head as parent; move only master using expected_sha and force=false. Do not retry a rejected lease without inspecting the new head.',
        'Read back final commit/ref and tree; fetch and reconcile local identity only after identical trees and preservation of any concurrent local edits.',
        'Report tested source b4127b19 separately from final documentation tree and preserve actual CI status; no qualification/warm/acceptance promotion.'
    ]
}
(WORK / 'w10_a05-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps({k: receipt[k] for k in ['outcome', 'prepared_tree', 'changed_paths', 'added_paths', 'modified_paths', 'projected_source_count', 'root_source_inventory_sha256']}))
