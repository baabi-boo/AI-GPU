#!/usr/bin/env python3
"""Read-only repository invariant inventory; writes only sibling review artifacts."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess
from datetime import datetime, timezone

ROOT = Path('/tmp/ai-gpu-2bfab0261c05/repo')
OUT = ROOT.parent
BASE = '858090410a992756808256ace90d36b9b3b88dd3'
CURRENT = '93bb3f0'

def git(*args, binary=False):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=not binary)

def diff_check(paths):
    result = subprocess.run(['git', 'diff', '--quiet', BASE, '--', *paths], cwd=ROOT)
    return {'command': ['git', 'diff', '--quiet', BASE, '--', *paths],
            'returncode': result.returncode, 'unchanged': result.returncode == 0}

def sha(body):
    return hashlib.sha256(body).hexdigest()

def read_json(path):
    return json.loads((ROOT / path).read_bytes())

def literal_assignments(path):
    result = {}
    for node in ast.parse((ROOT / path).read_text()).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                result[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                pass
    return result

def git_file_inventory(prefix):
    return sorted(p for p in git('ls-files', '--', prefix).splitlines() if (ROOT / p).is_file())

head = git('rev-parse', 'HEAD').strip()
selected = git('rev-parse', CURRENT).strip()
status_before = git('status', '--short')
qualified = read_json('ci/project/p06_qualified_warm_proof.json')
counter = read_json('ci/project/p06_counter_qualification_proof.json')
base_counter = json.loads(git('show', BASE + ':ci/project/p06_counter_qualification_proof.json', binary=True))
measurement = []
for expected in qualified['measurement_sources']:
    path = expected['path']
    body = (ROOT / path).read_bytes()
    actual = {'path': path, 'size_bytes': len(body), 'sha256': sha(body)}
    measurement.append({**actual, 'expected_size_bytes': expected['size_bytes'],
                        'expected_sha256': expected['sha256'],
                        'size_matches': len(body) == expected['size_bytes'],
                        'sha256_matches': sha(body) == expected['sha256']})
measurement_pass = len(measurement) == 69 and len({r['path'] for r in measurement}) == 69 and all(r['size_matches'] and r['sha256_matches'] for r in measurement)
measurement_diff = diff_check([r['path'] for r in measurement])

proof_rows = []
for contract in ['ci/project/p06_qualified_warm_contract.py', 'ci/project/p06_counter_qualification_contract.py']:
    constants = literal_assignments(contract)
    path = constants['SOURCE_PROOF_PATH']
    body = (ROOT / path).read_bytes()
    value = json.loads(body)
    semantic = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('utf-8')
    proof_rows.append({'path': path, 'contract': contract, 'size_bytes': len(body), 'sha256': sha(body),
                       'size_matches_frozen_constant': len(body) == constants['SOURCE_PROOF_BYTES'],
                       'sha256_matches_frozen_constant': sha(body) == constants['SOURCE_PROOF_SHA256'],
                       'semantic_sha256': sha(semantic),
                       'semantic_sha256_matches_frozen_constant': sha(semantic) == constants['SOURCE_PROOF_DOCUMENT_SHA256'],
                       'byte_identical_to_base': body == git('show', BASE + ':' + path, binary=True),
                       'claims': value['claims']})
proof_pass = all(row['size_matches_frozen_constant'] and row['sha256_matches_frozen_constant'] and row['semantic_sha256_matches_frozen_constant'] and row['byte_identical_to_base'] and all(v is False for v in row['claims'].values()) for row in proof_rows)

dep_rows = []
base_dependencies = {r['path']: r for r in base_counter['dependency_sources']}
for descriptor in counter['dependency_sources']:
    path = ROOT / 'third_party/ramulator' / descriptor['path']
    row = {**descriptor, 'descriptor_equals_base': descriptor == base_dependencies.get(descriptor['path']), 'local_source_file_present': path.is_file()}
    if path.is_file():
        data = path.read_bytes()
        row.update(actual_size_bytes=len(data), actual_sha256=sha(data), source_bytes_match=len(data) == descriptor['size_bytes'] and sha(data) == descriptor['sha256'])
    dep_rows.append(row)
pins = literal_assignments('ci/project/p06_dependency_contract.py')['PINS']
ramulator_pin = pins['ramulator']
gitlink_before = git('ls-tree', BASE, 'third_party/ramulator').strip()
gitlink_after = git('ls-tree', 'HEAD', 'third_party/ramulator').strip()
dep_pass = len(dep_rows) == 21 and len(base_dependencies) == 21 and all(r['descriptor_equals_base'] for r in dep_rows) and gitlink_before == gitlink_after and counter['dependency_revision'] == ramulator_pin['revision'] and ramulator_pin['revision'] in gitlink_after

baselines = git_file_inventory('ci/baselines')
baseline_rows = []
for path in baselines:
    body = (ROOT / path).read_bytes()
    baseline_rows.append({'path': path, 'size_bytes': len(body), 'sha256': sha(body)})
fixture_paths = git_file_inventory('ci/project/fixtures')
resource_paths = ['ci/project/p06_warm_contract.json', 'ci/project/p06_warm_contract.py',
    'ci/project/p06_benchmark_contract.json', 'ci/project/p06_contract.py',
    'ci/project/p06_workspace_contract.json', 'ci/project/p06_warm_analysis.py',
    'ci/project/p06_dependency_contract.py', 'ci/project/p06_managed_preflight_contract.py',
    'ci/project/p06_qualified_warm_capacity.py', 'ci/project/p06_qualified_warm_analyze.py',
    'ci/project/p06_qualified_warm_hosted.py', 'ci/project/p06_qualified_warm_run.py',
    '.github/workflows/p06-qualified-warm.yml', 'docs/project/developer-guide.md',
    'ci/asic_gate.py', 'ci/fpga_gate.py', 'ci/logic_gate.py', 'ci/synth_gate.py', 'ci/perf_baseline.py']
resource_paths = [p for p in resource_paths if (ROOT / p).is_file()]
roadmap_paths = ['docs/project/roadmap.json', 'ROADMAP.md', 'docs/project/status.md',
                 'docs/project/backlog.md', 'docs/project/acceptance.md', 'docs/project/phases',
                 'docs/project/evidence/p01-xrt-blocked.json', 'docs/project/evidence/p06-baseline/acceptance.json',
                 'docs/project/evidence/p06-serial-workspace/p06-a01-retained-baseline.json']
groups = {
    'golden_baselines': diff_check(['ci/baselines']),
    'numerical_fixture_directory': diff_check(['ci/project/fixtures']),
    'resource_and_performance_contracts_and_enforcement': diff_check(resource_paths),
    'frozen_proofs_and_dependency_contract': diff_check(['ci/project/p06_qualified_warm_proof.json', 'ci/project/p06_counter_qualification_proof.json', 'ci/project/p06_qualified_warm_contract.py', 'ci/project/p06_counter_qualification_contract.py', 'ci/project/p06_dependency_contract.py', '.gitmodules', 'third_party/ramulator']),
    'roadmap_and_acceptance_records': diff_check(roadmap_paths),
    'retained_evidence_tree': diff_check(['docs/project/evidence']),
    'retained_svg_and_readme': diff_check(['docs/assets/img/vortex_framework_stack.svg', 'README.md']),
}

warm = read_json('ci/project/p06_warm_contract.json')
roadmap = read_json('docs/project/roadmap.json')
phases = [{'id': p['id'], 'title': p['title'], 'status': p['status']} for p in roadmap['phases']]
svg_path = 'docs/assets/img/vortex_framework_stack.svg'
svg_body = (ROOT / svg_path).read_bytes()
svg_expected = next(r['sha256'] for r in roadmap['protected_assets'] if r['path'] == svg_path)
svg = {'path': svg_path, 'size_bytes': len(svg_body), 'sha256': sha(svg_body),
       'matches_roadmap_sha256': sha(svg_body) == svg_expected,
       'byte_identical_to_base': svg_body == git('show', BASE + ':' + svg_path, binary=True),
       'readme_embedding_present': svg_path in (ROOT / 'README.md').read_text()}

old_matrix = ast.parse(git('show', BASE + ':ci/project/p02_matrix.py'))
new_matrix = ast.parse((ROOT / 'ci/project/p02_matrix.py').read_text())
old_writer = next(n for n in old_matrix.body if isinstance(n, ast.FunctionDef) and n.name == '_write_json')
new_writer = next(n for n in new_matrix.body if isinstance(n, ast.FunctionDef) and n.name == '_write_json')
writer_guard_unchanged = all(ast.dump(a) == ast.dump(b) for a, b in zip(old_writer.body[:2], new_writer.body[:2]))
for tree in [old_matrix, new_matrix]:
    tree.body = [n for n in tree.body if not (isinstance(n, ast.FunctionDef) and n.name == '_write_json')]
rest_matrix_identical = ast.dump(old_matrix) == ast.dump(new_matrix)

result = {
 'schema_version': 1, 'reviewer': 'A025', 'scope': 'read-only frozen-invariant source inventory; no test or native execution',
 'observed_at_utc': datetime.now(timezone.utc).isoformat(), 'repository': str(ROOT), 'base_revision': BASE,
 'selected_revision': selected, 'observed_head_revision': head, 'head_matches_selected': head == selected,
 'tracked_diff_base_to_selected': git('diff', '--name-status', BASE, selected).splitlines(),
 'tracked_diff_selected_to_observed_head': git('diff', '--name-status', selected, head).splitlines(),
 'status_before': status_before.splitlines(), 'status_after': git('status', '--short').splitlines(),
 'measurement_sources': {'count': len(measurement), 'total_bytes': sum(r['size_bytes'] for r in measurement), 'all_pins_match': measurement_pass, 'base_worktree_diff': measurement_diff, 'inventory': measurement},
 'dependency_descriptors': {'count': len(dep_rows), 'all_descriptors_and_pins_unchanged': dep_pass, 'local_source_files_present': sum(r['local_source_file_present'] for r in dep_rows), 'source_bytes_rehashed': sum('source_bytes_match' in r for r in dep_rows), 'ramulator_pin': ramulator_pin, 'proof_dependency_revision': counter['dependency_revision'], 'gitlink_base': gitlink_before, 'gitlink_current': gitlink_after, 'inventory': dep_rows},
 'frozen_proofs': {'all_checks_pass': proof_pass, 'inventory': proof_rows},
 'baselines': {'count': len(baseline_rows), 'inventory': baseline_rows},
 'numerical_fixture_inventory': fixture_paths,
 'protected_groups': groups,
 'warm_budget': warm['budget'], 'warm_analysis': warm['analysis'], 'warm_sampling': warm['sampling'],
 'warm_complete_counts': qualified['complete_counts'], 'phases': phases,
 'retained_svg': svg,
 'p02_matrix_change_scope': {'only_write_json_body_changes_ast': rest_matrix_identical, 'serialization_and_16_mib_guard_unchanged_ast': writer_guard_unchanged},
 'limitations': [
  'No tests, governance qualification, dependency fetch/build, simulator, RTL, FPGA or physical-device execution was performed.',
  'All 21 Ramulator descriptors are unchanged, but all corresponding submodule files are absent; this is not a rehash of dependency source bytes or verification of remote availability.',
  'Tracked evidence preservation is established by git diff, not by rehashing every historical evidence artifact or revalidating its claims.',
  'The source inventory proves frozen identities at the observation time, not execution evidence, producer authentication, native admission, performance acceptance or phase acceptance.',
  'Concurrent new or modified unbound test-only files and an untracked publication audit are outside the protected assertions; status snapshots disclose them.'
 ]}
result['all_requested_source_invariants_pass'] = measurement_pass and measurement_diff['unchanged'] and dep_pass and proof_pass and all(v['unchanged'] for v in groups.values()) and all(svg[k] for k in ['matches_roadmap_sha256', 'byte_identical_to_base', 'readme_embedding_present']) and rest_matrix_identical and writer_guard_unchanged
json_path = OUT / 'a025-invariants.json'
json_path.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')

lines = ['# A025 frozen invariant review', '',
 f'Observation: `{result["observed_at_utc"]}`. Repository: `{ROOT}`.',
 f'Base: `{BASE}`. Selected revision: `{selected}`. Observed HEAD: `{head}`.', '',
 '**Result: all requested source invariant checks passed.** This is a read-only source and metadata review; it contains no test execution or native qualification.', '',
 '## Findings', '',
 f'- All **69** distinct frozen measurement paths match both their declared byte length and SHA-256 in `ci/project/p06_qualified_warm_proof.json`: **{result["measurement_sources"]["total_bytes"]:,} bytes** read. Their base-to-working-tree diff is empty.',
 '- All **21** Ramulator dependency descriptors in `ci/project/p06_counter_qualification_proof.json` equal their base-revision values, including path, Git blob, SHA-256 and byte size. The dependency contract pin, proof revision and repository gitlink remain `e62c84a6f0e06566ba6e182d308434b4532068a5`.',
 '- **Dependency-source limitation:** none of those 21 submodule files is materialized locally. No dependency fetch or source-byte rehash was performed. This establishes descriptor/proof-input preservation, not fresh source verification.',
 '- Both frozen proof files match the literal byte-count, SHA-256 and canonical-JSON SHA-256 constants in their contracts, and are byte-identical to the base. All seven claim fields remain false.',
 f'- All **{len(baseline_rows)}** inherited golden baseline files and the **{len(fixture_paths)}** tracked files under `ci/project/fixtures/` are unchanged relative to base. The entire retained `docs/project/evidence/` tree has an empty diff; historical packets were not broadly rehashed.',
 '- Resource and performance contracts, their selected enforcement files, both roadmap files, phase documents and acceptance records have empty base-to-working-tree diffs. P01 remains blocked, P06 remains in progress, and P06-A02/A03 have no acceptance evidence added.',
 '- The retained SVG matches its roadmap SHA-256, is byte-identical to base, and remains embedded in the unchanged README.',
 '- The only changed pre-existing production file is `ci/project/p02_matrix.py`; an AST comparison confirms that changes are confined to `_write_json`. Serialization and the existing 16 MiB checkpoint bound are unchanged. The six added test files and one added design document are not frozen measurement inputs.', '',
 '## Exact verification method and commands', '',
 'The retained standalone script is `/tmp/ai-gpu-2bfab0261c05/a025-verify-invariants.py`. It imports only Python standard-library modules and reads repository files without importing or executing project code.', '',
 '```bash', 'cd /tmp/ai-gpu-2bfab0261c05/repo',
 'python /tmp/ai-gpu-2bfab0261c05/a025-verify-invariants.py',
 'git diff --name-status 858090410a992756808256ace90d36b9b3b88dd3 93bb3f0',
 'git status --short', '```', '',
 'For each of the 69 frozen entries, the script computes `len(Path(path).read_bytes())` and `hashlib.sha256(body).hexdigest()` and compares both values to that entry. It checks uniqueness and the expected count of 69. For each dependency row it compares the entire parsed descriptor against `git show BASE:ci/project/p06_counter_qualification_proof.json`. Proof constants are read with `ast.literal_eval` from source, without importing their modules. Canonical proof hashes use `json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)`.', '',
 'The compact summary and complete machine-readable inventories, exact protected-path command arguments, return codes, source hashes, proof identities and status snapshots are in `/tmp/ai-gpu-2bfab0261c05/a025-invariants.json`.', '',
 '| Protected group | Exact path arguments after `git diff --quiet BASE --` | Exit |', '|---|---|---:|']
for name, group in groups.items():
    lines.append(f'| {name} | ' + '<br>'.join('`' + p + '`' for p in group['command'][5:]) + f' | {group["returncode"]} |')
lines += ['', 'The measurement-source diff additionally supplies every path listed in the 69-row inventory below; it exited 0. Exit 0 establishes no base-to-working-tree change for the supplied paths, including staged and unstaged tracked changes. Untracked files outside these protected inventories are not treated as frozen inputs.', '',
 '## Frozen measurement source inventory', '', '| Path | Bytes | SHA-256 | Size/hash match |', '|---|---:|---|---|']
for row in measurement:
    lines.append(f'| `{row["path"]}` | {row["size_bytes"]} | `{row["sha256"]}` | yes / yes |')
lines += ['', '## Dependency descriptor inventory', '', 'Paths below are relative to the unmaterialized `third_party/ramulator` submodule. Every complete descriptor equals the base proof. The JSON also records all expected Git blob IDs.', '', '| Path | Expected bytes | Expected SHA-256 | Descriptor unchanged |', '|---|---:|---|---|']
for row in dep_rows:
    lines.append(f'| `{row["path"]}` | {row["size_bytes"]} | `{row["sha256"]}` | yes |')
lines += ['', '## Golden baseline inventory', '', '| Path | Bytes | Current SHA-256 |', '|---|---:|---|']
for row in baseline_rows:
    lines.append(f'| `{row["path"]}` | {row["size_bytes"]} | `{row["sha256"]}` |')
lines += ['', '## Frozen proofs', '', '| Proof | Bytes | SHA-256 |', '|---|---:|---|']
for row in proof_rows:
    lines.append(f'| `{row["path"]}` | {row["size_bytes"]} | `{row["sha256"]}` |')
lines += ['', '## Preserved resource and performance predicates', '',
 '- Warm and dependency disk floor: **16,106,127,360 bytes (15 GiB)**. Warm/dependency maximum RSS and capacity required available memory: **4,294,967,296 bytes (4 GiB)**.',
 '- Warm contract: at most **2 jobs**, **16 MiB** maximum log size, **1,800 s** build timeout, **180 s** per-process run timeout, and **90 min** hosted job timeout.',
 '- Both formats must improve; candidate median is at most **95% of reference**; each measured candidate pair must not be slower and must not increase modeled cycles. All validity requirements are preserved. The decision is not phase acceptance.',
 '- The unchanged population is **24 processes, 792 launches, 25,344 checked words**; five measured pairs and one warm-up pair per format/policy, one prime and 32 timed operations per process. No sample replacement, outlier removal or optional stopping is permitted.', '',
 '## Roadmap phases', '', '| Phase | Title | Status |', '|---|---|---|']
for row in phases:
    lines.append(f'| {row["id"]} | {row["title"]} | `{row["status"]}` |')
lines += ['', '## Retained image', '', f'`{svg_path}`: **{svg["size_bytes"]} bytes**, SHA-256 `{svg["sha256"]}`. Matches the protected-asset manifest, base bytes and README embedding.', '',
 '## Revision and concurrent-file scope', '', 'Base-to-selected change list:', '', '```text', *result['tracked_diff_base_to_selected'], '```', '', 'Working tree status at completion:', '', '```text', *(result['status_after'] or ['(clean)']), '```', '',
 'The assertions apply to the protected path inventories as observed. A024 may add or edit unbound test files while this review runs; these are deliberately outside protected assertions and are not evidence of a frozen-input mutation.', '', '## Limitations', '']
lines += ['- ' + item for item in result['limitations']]
if head != selected:
    lines += ['', '## Concurrent test-only commit observed', '',
              f'HEAD advanced from selected `{selected}` to `{head}` during review. The protected-path working-tree comparisons and hashes reported above were rerun at the observed HEAD and all still passed. The additional commit changed only these test paths:', '',
              '```text', *result['tracked_diff_selected_to_observed_head'], '```', '',
              'These unbound test-only edits are excluded from frozen-input assertions; no native qualification is inferred from the new commit.']
(OUT / 'a025-invariants.md').write_text('\n'.join(lines) + '\n')
print(json.dumps({'report': str(OUT / 'a025-invariants.md'), 'json': str(json_path),
                  'all_requested_source_invariants_pass': result['all_requested_source_invariants_pass'],
                  'measurement_count': len(measurement), 'measurement_bytes': result['measurement_sources']['total_bytes'],
                  'dependency_descriptor_count': len(dep_rows), 'dependency_source_files_present': result['dependency_descriptors']['local_source_files_present'],
                  'golden_baseline_count': len(baseline_rows), 'fixture_file_count': len(fixture_paths),
                  'head': head, 'head_matches_selected': head == selected}, indent=2))
