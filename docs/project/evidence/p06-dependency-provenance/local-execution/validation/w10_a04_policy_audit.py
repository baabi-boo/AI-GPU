#!/usr/bin/env python3
"""Independent read-only base-policy/protected-input audit; no native execution."""
from __future__ import annotations

import ast
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path('/workspace/ai-gpu-next')
OUT = Path('/workspace/scratch/279b6658611e/validation')
BASE = '849469e1111870fbcfe0346afd33b284a5a1edd8'
PREFIX = os.environ.get('W10_A04_PROFILE', 'w10_a04-policy-audit')
FALSE = ('qualified', 'ready_for_warm', 'warm_execution', 'full_warm_coverage',
         'acceptance_claimed', 'phase_acceptance', 'performance_acceptance')

def sha(body):
    return hashlib.sha256(body).hexdigest()

def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args])

def descriptor(path):
    body = path.read_bytes()
    return {'path': str(path), 'size_bytes': len(body), 'sha256': sha(body)}

def tree(revision):
    result = {}
    for row in git('ls-tree', '-r', '-z', revision).split(b'\0'):
        if not row:
            continue
        header, path = row.split(b'\t', 1)
        mode, kind, oid = header.decode().split()
        result[path.decode()] = {'mode': mode, 'kind': kind, 'git_object': oid}
    return result

def current_profile():
    head = git('rev-parse', 'HEAD').decode().strip()
    changed = set(git('diff', '--name-only', '-z', BASE).decode().split('\0'))
    untracked = set(git('ls-files', '--others', '--exclude-standard', '-z').decode().split('\0'))
    # All changed source plus tracked provisional docs; appended evidence is separately scoped.
    paths = sorted(p for p in changed | untracked if p and
                   (p.startswith('ci/') or (p in changed and p.startswith('docs/'))))
    rows = []
    for name in paths:
        path = ROOT / name
        row = {'path': name, 'tracked': name not in untracked}
        if path.is_file():
            row.update(size_bytes=path.stat().st_size, sha256=sha(path.read_bytes()))
        else:
            row['missing'] = True
        rows.append(row)
    return {'revision': head, 'tree': git('rev-parse', 'HEAD^{tree}').decode().strip(),
            'status_porcelain': git('status', '--porcelain=v1', '--untracked-files=normal').decode(),
            'files': rows, 'source_profile_sha256': sha(json.dumps(
                [r for r in rows if r['path'].startswith('ci/')], sort_keys=True).encode())}

def run(label, argv):
    started = datetime.now(timezone.utc).isoformat()
    proc = subprocess.run(argv, cwd=ROOT, capture_output=True, timeout=90)
    stdout = OUT / (PREFIX + '-' + label + '.stdout.log')
    stderr = OUT / (PREFIX + '-' + label + '.stderr.log')
    stdout.write_bytes(proc.stdout)
    stderr.write_bytes(proc.stderr)
    return {'argv': argv, 'cwd': str(ROOT), 'started_at': started,
            'finished_at': datetime.now(timezone.utc).isoformat(), 'exit_code': proc.returncode,
            'stdout': descriptor(stdout), 'stderr': descriptor(stderr)}, proc.stdout

def ast_value(body, name):
    module = ast.parse(body)
    for node in module.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.dump(node.value, include_attributes=False)
    raise AssertionError(name)

started = datetime.now(timezone.utc).isoformat()
before = current_profile()
base_tree, head_tree = tree(BASE), tree(before['revision'])
protected_prefixes = ('hw/', 'sim/', 'sw/', 'tests/', 'profiles/', 'third_party/',
    '.github/', 'ci/baselines/', 'ci/testcases/', 'ci/project/fixtures/',
    'docs/assets/', 'docs/review/', 'docs/project/evidence/',
    'ci/project/p06_warm_', 'ci/project/p06_native_lifetime_', 'ci/project/p06_managed_preflight_')
protected_exact = {'AGENTS.md', 'ROADMAP.md', 'README.md', 'LICENSE', 'LICENSE.md', 'VERSION',
    'VX_config.toml', 'VX_types.toml', 'configure', 'Makefile.in', 'config.mk.in',
    '.gitmodules', '.gitattributes', 'ci/change_impact.py', 'ci/gen_config.py',
    'ci/project/p01_toolchain.lock.json', 'ci/project/p06_contract.py',
    'docs/project/roadmap.json', 'docs/project/acceptance.md',
    'docs/project/phases/p06-performance.md', 'docs/project/p06-mpm-qualification-plan.md',
    'docs/designs/simx_counter_lifetime_v1.md', 'docs/designs/managed_counter_lifetime_v1.md',
    'docs/designs/warm_workspace_benchmark_v1.md'}
provisional_index = 'docs/project/evidence/p06-dependency-provenance/README.md'
protected = sorted(p for p in base_tree if p != provisional_index and (
    p in protected_exact or p.startswith(protected_prefixes) or
    (p.startswith('ci/') and '/' not in p[3:])))
index = {}
for raw in git('ls-files', '-s', '-z').split(b'\0'):
    if raw:
        header, path = raw.split(b'\t', 1)
        mode, oid, stage = header.decode().split()
        index.setdefault(path.decode(), []).append({'mode': mode, 'git_object': oid, 'stage': stage})
cat = subprocess.Popen(['git', '-C', str(ROOT), 'cat-file', '--batch'], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
rows, failures = [], []
for name in protected:
    old = base_tree[name]
    row = {'path': name, **old, 'head_identical': head_tree.get(name) == old,
           'index_identical': index.get(name) == [dict(mode=old['mode'], git_object=old['git_object'], stage='0')]}
    path = ROOT / name
    if old['kind'] == 'blob':
        cat.stdin.write((old['git_object'] + '\n').encode()); cat.stdin.flush()
        header = cat.stdout.readline().decode().strip().split()
        assert header[1] == 'blob', header
        body = cat.stdout.read(int(header[2])); assert cat.stdout.read(1) == b'\n'
        current = os.fsencode(os.readlink(path)) if path.is_symlink() else path.read_bytes()
        row.update(size_bytes=len(body), sha256=sha(body), worktree_sha256=sha(current),
                   worktree_identical=body == current)
        row['worktree_mode_identical'] = (path.is_symlink() if old['mode'] == '120000' else
            (not path.is_symlink() and bool(path.stat().st_mode & 0o111) == (old['mode'] == '100755')))
    else:
        row['worktree_identity_scope'] = 'Gitlink objects, not recursively hashed external repository content'
        if (path / '.git').exists():
            observed = subprocess.check_output(['git', '-C', str(path), 'rev-parse', 'HEAD']).decode().strip()
            row.update(initialized_gitlink_revision=observed, worktree_identical=observed == old['git_object'])
        else:
            row['worktree_identical'] = None
            row['initialized'] = False
    if (not row['head_identical'] or not row['index_identical'] or
            row.get('worktree_identical') is False or row.get('worktree_mode_identical') is False):
        failures.append(name)
    rows.append(row)
cat.stdin.close(); cat.wait(timeout=10)
protected_path = OUT / (PREFIX + '-protected.json')
protected_path.write_text(json.dumps({'base_revision': BASE, 'head_revision': before['revision'],
    'scope': {'prefixes': protected_prefixes, 'exact_paths': sorted(protected_exact),
              'provisional_index_excluded': provisional_index},
    'entries': rows, 'failures': failures}, sort_keys=True, separators=(',', ':')) + '\n')

classifier_root = OUT / 'w10_a04-base-classifier'
classifier_sources = []
for source, target in [('ci/change_impact.py', 'change_impact.py'),
                       ('docs/review/change-impact.yaml', 'change-impact.yaml')]:
    body = git('show', BASE + ':' + source)
    path = classifier_root / target
    assert path.read_bytes() == body
    classifier_sources.append({'source': source, 'base_git_object': base_tree[source]['git_object'], **descriptor(path)})
commands = {}
commands['base_classifier'], classifier_output = run('base-classifier', [sys.executable, '-I',
    str(classifier_root / 'change_impact.py'), '--repo', str(ROOT), '--policy',
    str(classifier_root / 'change-impact.yaml'), 'explain', '--base', BASE, '--head', before['revision']])
commands['check_project'], project_output = run('check-project', [sys.executable, '-B', 'ci/project/check_project.py'])
commands['governance_preflight'], preflight_output = run('preflight', [sys.executable, '-B',
    'ci/project/preflight.py', '--root', str(ROOT), '--tier', 'governance', '--json'])

sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'ci/project'))
import p06_contract as common_contract
import p06_dependency_contract as dependency_contract
import p06_managed_preflight_contract as managed_contract
import p06_native_lifetime_contract as lifetime_contract
import p06_warm_analyze as warm_analyze
import p06_warm_contract as warm_contract
budget_unchanged = ast_value(git('show', BASE + ':ci/project/p06_dependency_contract.py'), 'BUDGET') == ast_value(
    (ROOT / 'ci/project/p06_dependency_contract.py').read_bytes(), 'BUDGET')
false_claims_unchanged = ast_value(git('show', BASE + ':ci/project/p06_dependency_contract.py'), 'FALSE_CLAIMS') == ast_value(
    (ROOT / 'ci/project/p06_dependency_contract.py').read_bytes(), 'FALSE_CLAIMS')
manifest_path = ROOT / 'docs/project/evidence/p06-counter-diagnostics/lifetime-source-manifest.json'
manifest = json.loads(manifest_path.read_bytes())
selectors = manifest['selectors']
components = [component for row in selectors for component in row['components']]
selector_counts = dict(Counter(row['component_count'] for row in selectors))
premises = [row['id'] for row in manifest['premises']]
all_counter_shapes = {'_COUNTERS': type(common_contract._COUNTERS).__name__,
                      'count': len(common_contract._COUNTERS)}
reports = []
evidence = Path('/workspace/p06-local-native-run-04/evidence')
for relative in ('dependency-preparation.json', 'dependency-build/report.json', 'native-lifetime/report.json',
                 'pending-probe/report.json', 'dependency-substitution/report.json', 'local-execution.json'):
    path = evidence / relative
    if not path.exists():
        reports.append({'path': str(path), 'missing': True}); continue
    document = json.loads(path.read_bytes())
    flags = {key: document.get(key, 'absent') for key in FALSE}
    reports.append({**descriptor(path), 'contract_id': document.get('contract_id'),
                    'outcome': document.get('outcome'), 'false_claims': flags,
                    'all_seven_false': all(value is False for value in flags.values())})
after = current_profile()
source_stable = before['source_profile_sha256'] == after['source_profile_sha256']
preflight_document = json.loads(preflight_output)
output = {'schema_version': 1, 'reviewer': '/root/w10_a04', 'started_at': started,
    'finished_at': datetime.now(timezone.utc).isoformat(), 'base_revision': BASE,
    'before': before, 'after': after, 'source_profile_stable': source_stable,
    'base_classifier_sources': classifier_sources, 'classifier_summary': classifier_output.decode().splitlines()[:2],
    'commands': commands, 'check_project_summary': project_output.decode().strip(),
    'preflight': preflight_document,
    'protected': {'count': len(rows), 'blobs': sum(r['kind'] == 'blob' for r in rows),
                  'gitlinks': sum(r['kind'] == 'commit' for r in rows), 'failures': failures,
                  'manifest': descriptor(protected_path),
                  'svg': next(row for row in rows if row['path'] == 'docs/assets/img/vortex_framework_stack.svg')},
    'gates': {'dependency_budget_unchanged': budget_unchanged, 'dependency_budget': dependency_contract.BUDGET,
              'dependency_false_claims_unchanged': false_claims_unchanged,
              'dependency_false_claims': dependency_contract.FALSE_CLAIMS,
              'managed_false_claims': managed_contract.FALSE_CLAIMS,
              'lifetime_false_claims': lifetime_contract.FALSE_CLAIMS,
              'warm_v1': warm_analyze._full_hypothesis_qualification(),
              'unresolved_obligations': managed_contract.UNRESOLVED_OBLIGATIONS,
              'managed_counts': managed_contract.COMPLETE_COUNTS},
    'qualification_handoff': {'manifest': descriptor(manifest_path), 'available_selectors': len(selectors),
        'unavailable_selectors': len(manifest['unavailable_selectors']), 'components': len(components),
        'unique_components': len(set(components)), 'selector_component_histogram': selector_counts,
        'premises': premises, 'transient_exclusions': manifest['transient_and_unselected_exclusions'],
        'counter_source_inventory_shape': all_counter_shapes},
    'original_reports': reports,
    'limits': ['Base classifier covers committed HEAD, not uncommitted stats-reader or provisional docs.',
        'No full governance unit suite, native process, performance, RTL, vendor, synthesis or physical check run by this audit.',
        'Actual report flags are read-only observations; this audit does not replace full inert original replay.',
        'Historical source manifest remains historical; its inventory is reconciled, not relabelled as current qualification.',
        'Initialized gitlinks checked by HEAD identity; uninitialized gitlinks checked by superproject objects only.']}
target = OUT / (PREFIX + '.json')
target.write_text(json.dumps(output, sort_keys=True, indent=2) + '\n')
print(json.dumps({'report': descriptor(target), 'head': before['revision'], 'classifier': output['classifier_summary'],
    'command_exit_codes': {k:v['exit_code'] for k,v in commands.items()}, 'source_profile_stable': source_stable,
    'protected_count': len(rows), 'protected_failures': failures, 'budget_unchanged': budget_unchanged,
    'false_claims_unchanged': false_claims_unchanged, 'selectors': len(selectors), 'components': len(components),
    'premises': premises, 'original_report_flags': {Path(r['path']).parent.name:r.get('all_seven_false') for r in reports}}, indent=2))
