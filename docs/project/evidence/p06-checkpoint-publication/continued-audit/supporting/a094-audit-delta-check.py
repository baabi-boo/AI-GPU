from pathlib import Path
import ast
import datetime
import hashlib
import json
import os
import stat
import subprocess
import time

ROOT = Path('/tmp/ai-gpu-2bfab0261c05/audit')
OUT = Path('/tmp/ai-gpu-2bfab0261c05/a094-audit-delta.json')
BASE = '30b2e8ca69fba47646392c0cf6650cbb75155843'
PACKET = 'docs/project/evidence/p06-checkpoint-publication/continued-audit/'
HANDOFF = 'docs/project/p06-qualified-warm-handoff.md'
started = datetime.datetime.now(datetime.timezone.utc).isoformat()
checks = []

def git(*args):
    return subprocess.check_output(['/usr/bin/git', '-C', str(ROOT), *args])

def check(name, result, detail=None):
    checks.append({'name': name, 'passed': bool(result), 'detail': detail})

def sha(data):
    return hashlib.sha256(data).hexdigest()

def inventory():
    paths = git('ls-files', '--others', '--exclude-standard', '-z').split(b'\0')
    result = []
    for path in paths:
        if not path:
            continue
        relative = os.fsdecode(path)
        node = ROOT / relative
        mode = node.lstat().st_mode
        content = os.fsencode(os.readlink(node)) if stat.S_ISLNK(mode) else node.read_bytes()
        result.append({'path': relative, 'size_bytes': len(content), 'sha256': sha(content),
                       'mode': oct(stat.S_IMODE(mode)), 'regular': stat.S_ISREG(mode),
                       'symlink': stat.S_ISLNK(mode)})
    return result

head_before = git('rev-parse', 'HEAD').decode().strip()
branch_before = git('branch', '--show-current').decode().strip()
index = Path(git('rev-parse', '--git-path', 'index').decode().strip())
if not index.is_absolute():
    index = ROOT / index
index_before = sha(index.read_bytes())
before = inventory()
check('untracked_snapshot_initially_stable', before == inventory())
tree = git('rev-parse', BASE + '^{tree}').decode().strip()
entries = []
for item in git('ls-tree', '-r', '-z', BASE).split(b'\0'):
    if not item:
        continue
    metadata, name = item.split(b'\t', 1)
    mode, kind, identity = metadata.decode().split()
    entries.append({'path': os.fsdecode(name), 'mode': mode, 'kind': kind, 'sha1': identity})
mismatches, mode_mismatches, missing, gitlinks = [], [], [], []
total_bytes = 0
for entry in entries:
    path = ROOT / entry['path']
    if entry['kind'] == 'commit':
        gitlinks.append(entry)
        continue
    try:
        info = path.lstat()
    except FileNotFoundError:
        missing.append(entry['path'])
        continue
    if entry['mode'] == '120000':
        data = os.fsencode(os.readlink(path)) if path.is_symlink() else path.read_bytes()
        body_hash = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        total_bytes += len(data)
        mode_ok = stat.S_ISLNK(info.st_mode)
    else:
        body_hash_state = hashlib.sha1(b'blob ' + str(info.st_size).encode() + b'\0')
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                body_hash_state.update(block)
                total_bytes += len(block)
        body_hash = body_hash_state.hexdigest()
        actual_executable = bool(info.st_mode & stat.S_IXUSR)
        mode_ok = stat.S_ISREG(info.st_mode) and actual_executable == (entry['mode'] == '100755')
    if body_hash != entry['sha1']:
        mismatches.append({'path': entry['path'], 'expected_blob': entry['sha1'], 'actual_blob': body_hash})
    if not mode_ok:
        mode_mismatches.append(entry['path'])

tracked_delta = git('diff', '--name-only', BASE, '--').decode().splitlines()
staged_delta = git('diff', '--cached', '--name-only', BASE, '--').decode().splitlines()
ignored = [os.fsdecode(p) for p in git('ls-files', '--others', '--ignored', '--exclude-standard', '-z').split(b'\0') if p]
hidden_index = [os.fsdecode(p) for p in git('ls-files', '-v', '-z').split(b'\0') if p and (p[0:1].islower() or p.startswith(b'S '))]
check('head_is_published_source', head_before == BASE, head_before)
check('branch_is_expected_audit_branch', branch_before == 'audit/checkpoint-publication-30b2e8c', branch_before)
check('only_tracked_delta_is_handoff', tracked_delta == [HANDOFF], tracked_delta)
check('index_unmodified_from_source', not staged_delta, staged_delta)
check('all_tracked_bytes_except_handoff_match_published_git_blobs', [x['path'] for x in mismatches] == [HANDOFF], mismatches)
check('all_tracked_modes_match', not mode_mismatches, mode_mismatches)
check('no_missing_tracked_materialization', not missing, missing)
check('no_hidden_index_flags', not hidden_index, hidden_index)
check('all_untracked_files_under_packet', all(x['path'].startswith(PACKET) for x in before))
check('all_untracked_files_regular_nonsymlink', all(x['regular'] and not x['symlink'] for x in before))
check('all_untracked_files_mode_0644', all(x['mode'] == '0o644' for x in before))
check('no_ignored_untracked_files', not ignored, ignored)
check('no_added_canonical_test_paths', not any(x['path'].startswith('ci/project/') for x in before))
new_python = [x for x in before if x['path'].endswith('.py')]
check('new_python_confined_to_historical_supporting', all(x['path'].startswith(PACKET + 'supporting/') for x in new_python))
check('new_python_not_test_or_import_hook_names', all(not Path(x['path']).name.startswith('test_') and Path(x['path']).name not in {'__init__.py', 'sitecustomize.py', 'usercustomize.py', 'conftest.py'} for x in new_python))
check('no_added_pycache_or_bytecode', not any('__pycache__' in Path(x['path']).parts or x['path'].endswith(('.pyc', '.pyo')) for x in before))
for entry in new_python:
    ast.parse((ROOT / entry['path']).read_text(), filename=entry['path'])
check('retained_python_syntax_parsed_without_execution', True, len(new_python))
readme = (ROOT / PACKET / 'README.md').read_text()
check('readme_labels_retained_historical_probe_source', 'retained historical probe source' in readme and 'separate from the canonical governance tests' in readme)
run_source = (ROOT / 'ci/project/governance_run.py').read_text()
collect_source = (ROOT / 'ci/project/governance_replay_collect.py').read_text()
check('strict_runner_discovery_remains_ci_project_test_pattern', 'DISCOVERY = {"start_directory": "ci/project", "pattern": "test_*.py"}' in run_source)
check('trusted_replay_discovery_remains_ci_project_test_pattern', 'loader.discover("ci/project", pattern="test_*.py")' in collect_source)
base_handoff = git('show', BASE + ':' + HANDOFF)
current_handoff = (ROOT / HANDOFF).read_bytes()
old_body = base_handoff.split(b'## Current closeout reliability continuation\n\n', 1)[1]
new_body = current_handoff.split(b'and then-existing temporary-file limitation.\n\n', 1)[1]
check('historical_handoff_body_unchanged', old_body == new_body)

groups = {
    'workflows': lambda p: p.startswith('.github/workflows/'),
    'governance_tooling': lambda p: p.startswith('ci/project/'),
    'existing_evidence': lambda p: p.startswith('docs/project/evidence/'),
    'production_and_tests': lambda p: p.startswith(('hw/', 'sim/', 'sw/', 'runtime/', 'python/', 'tests/')),
    'licenses_and_notices': lambda p: Path(p).name.upper().startswith(('LICENSE', 'COPYING', 'NOTICE')),
    'metadata_policy_and_status': lambda p: p in {'AGENTS.md','ROADMAP.md','docs/project/roadmap.json','docs/project/status.md','docs/project/backlog.md','docs/project/acceptance.md','docs/review/code-review-policy.md','docs/review/change-impact.yaml'},
    'frozen_svg_and_embedding_readme': lambda p: p in {'README.md','docs/assets/img/vortex_framework_stack.svg'},
}
group_results = {}
mismatch_paths = {x['path'] for x in mismatches} | set(mode_mismatches) | set(missing)
for name, matches in groups.items():
    paths = [x['path'] for x in entries if matches(x['path'])]
    failures = sorted(mismatch_paths.intersection(paths))
    group_results[name] = {'tracked_entries': len(paths), 'mismatches': failures}
    check(name + '_unchanged', not failures, len(paths))
roadmap_bytes = (ROOT / 'docs/project/roadmap.json').read_bytes()
roadmap = json.loads(roadmap_bytes)
references = []
for phase in roadmap['phases']:
    for entry in phase.get('evidence', []):
        if isinstance(entry, dict) and isinstance(entry.get('record'), str):
            references.append(entry['record'])
check('no_acceptance_reference_points_to_audit_packet', not any(p.startswith(PACKET) for p in references), len(references))
after = inventory()
before_map = {x['path']: x for x in before}
after_map = {x['path']: x for x in after}
changed_snapshot = [p for p in before_map.keys() & after_map.keys() if before_map[p] != after_map[p]]
removed_snapshot = sorted(before_map.keys() - after_map.keys())
added_snapshot = sorted(after_map.keys() - before_map.keys())
check('captured_untracked_bytes_stable', not changed_snapshot and not removed_snapshot, {'changed': changed_snapshot, 'removed': removed_snapshot})
check('head_unchanged_during_review', git('rev-parse', 'HEAD').decode().strip() == head_before)
check('index_bytes_unchanged_during_review', sha(index.read_bytes()) == index_before)
check('tracked_diff_unchanged_during_review', git('diff', '--name-only', BASE, '--').decode().splitlines() == tracked_delta)
check('handoff_bytes_unchanged_during_review', (ROOT / HANDOFF).read_bytes() == current_handoff)
result = {
    'schema_version': 1, 'reviewer': 'A094', 'scope': 'Read-only audit delta snapshot; no project test collection, test body execution, native work or qualification.',
    'started_at_utc': started, 'completed_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'source_root': str(ROOT), 'base_revision': BASE, 'base_tree': tree, 'branch': branch_before,
    'assertion_count': len(checks), 'failed_assertions': [x['name'] for x in checks if not x['passed']],
    'assertions': checks, 'tracked_entries': len(entries), 'tracked_materialized_bytes_hashed': total_bytes,
    'tracked_diff': tracked_delta, 'gitlinks': gitlinks, 'protected_groups': group_results,
    'untracked_snapshot': {'count': len(before), 'size_bytes': sum(x['size_bytes'] for x in before), 'files': before,
        'new_paths_added_during_review': added_snapshot, 'captured_bytes_stable': not changed_snapshot and not removed_snapshot},
    'new_python_paths': [x['path'] for x in new_python],
    'roadmap_sha256': sha(roadmap_bytes), 'acceptance_record_paths': references,
    'effects': {'canonical_test_registration_changed': False, 'existing_acceptance_bindings_changed': False,
       'future_committed_tree_source_inventory_will_change': True,
       'new_markdown_included_in_project_link_validation': True,
       'audit_branch_ci_cannot_qualify_master_revision': True},
}
OUT.write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({k: result[k] for k in ['assertion_count','failed_assertions','tracked_entries','tracked_materialized_bytes_hashed']} | {'untracked_count':len(before),'untracked_bytes':sum(x['size_bytes'] for x in before),'new_python':len(new_python),'added_during_review':len(added_snapshot)}))
