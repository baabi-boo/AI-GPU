#!/usr/bin/env python3
"""Inspect a new diagnostic preparation without running its retained code."""
import argparse
import ast
import datetime
import difflib
import hashlib
import importlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
REPO = Path('/workspace/AI-GPU')
PACKET = REPO / 'docs/project/evidence/p06-dependency-provenance/host-diagnostic'
WORKSPACE = Path('/workspace/p06-host-diagnostic-fixed-05')
OLD_REV = '5527cb062e10dfff3266022d138dd7cdf63f5e5c'
PROTECTED = {
    PACKET / 'driver.py': '743439b558db9ec39b12bb0bac5b838fd33aac72f9f996f3f8569090db33b91b',
    PACKET / 'driver-04.py': 'c2aeaf524fd134b4c7eca6544b9d03c51bbe374dabde5239fa0c4c4372c3ddd0',
    Path('/workspace/p06-host-diagnostic-5527-03/prepared.json'): '0083c760fc36ad58018c27d3ec0355fe91422d20ce4bfc58b07df52079b7e54c',
    Path('/workspace/p06-host-diagnostic-fixed-04/prepared.json'): '8a5d86be8362bcd1cdb3083f403d0ffb9600d1b2d34410aefb1894b434646a82',
    Path('/workspace/p06-host-diagnostic-5527-03/evidence/host-diagnostic.json'): '2d275a08f0a8547e720fa97bac99c23343fbcddfbfbd351d6d90bd2a437e2570',
    Path('/workspace/p06-host-diagnostic-fixed-04/evidence/host-diagnostic.json'): '8f1afcb69d5bd17dc9fa727411d0dd2bb67b5ae655fa484236cb9bed9bc36798',
}

def identity(path):
    assert path.is_file() and not path.is_symlink()
    raw = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'size_bytes': len(raw)}

def write_exclusive(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')

def git(helpers, *args):
    return subprocess.check_output(['git', '-C', str(helpers), *args])

def resources():
    lines = Path('/proc/meminfo').read_text().splitlines()
    available = next(int(line.split()[1]) * 1024 for line in lines if line.startswith('MemAvailable:'))
    free = shutil.disk_usage('/workspace').free
    assert available >= 6 * 1024**3, 'aggregate 2 GiB governance + 4 GiB diagnostic memory entry bound'
    assert free >= 15 * 1024**3, 'unchanged 15 GiB disk reserve'
    return {'available_memory_bytes': available, 'free_disk_bytes': free, 'aggregate_rss_ceiling_bytes': 6 * 1024**3}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['preflight', 'prepared'])
    parser.add_argument('--helpers', type=Path, required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--tree', required=True)
    args = parser.parse_args()
    helpers = args.helpers
    assert helpers.resolve(strict=True) == helpers
    assert git(helpers, 'rev-parse', 'HEAD').decode().strip() == args.revision
    assert git(helpers, 'rev-parse', 'HEAD^{tree}').decode().strip() == args.tree
    assert git(helpers, 'status', '--porcelain=v1') == b''
    protected = [identity(path) for path in PROTECTED]
    assert all(row['sha256'] == PROTECTED[Path(row['path'])] for row in protected)
    original = (PACKET / 'driver.py').read_text()
    replacement = original.replace('REVISION = "' + OLD_REV + '"', 'REVISION = "' + args.revision + '"')
    assert original.count('REVISION = "' + OLD_REV + '"') == 1
    old_map_policy = 'required = [archives[key]["path"] for key in ("yaml-cpp", "spdlog")]\n                required_loads = []'
    new_map_policy = 'required = [archives["yaml-cpp"]["path"]]\n                required_loads = [archives[key]["path"] for key in ("yaml-cpp", "spdlog")]'
    assert replacement.count(old_map_policy) == 1
    replacement = replacement.replace(old_map_policy, new_map_policy)
    assert replacement.count(new_map_policy) == 1
    restored_policy = replacement.replace(new_map_policy, old_map_policy)
    assert restored_policy.replace('REVISION = "' + args.revision + '"', 'REVISION = "' + OLD_REV + '"') == original
    tree_old, tree_new = ast.parse(original), ast.parse(restored_policy)
    for tree in (tree_old, tree_new):
        assignment = [node for node in tree.body if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id == 'REVISION']
        assert len(assignment) == 1 and isinstance(assignment[0].value, ast.Constant)
        assignment[0].value.value = '<reviewed-revision>'
    assert ast.dump(tree_old) == ast.dump(tree_new)
    driver = PACKET / 'driver-05.py'
    basic = {
        'schema_version': 1, 'checked_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'helper_revision': args.revision, 'helper_tree': args.tree, 'helper_checkout': str(helpers),
        'preparation_checker': identity(Path(__file__).resolve()),
        'helper_checkout_clean': True, 'workspace': str(WORKSPACE),
        'prior_attempt_protected_bytes_unchanged': True, 'prior_attempt_protected_identities': protected,
        'driver_difference': 'Exactly three reviewed changes from original driver03: REVISION literal; Ramulator required member archive becomes yaml-cpp only; Ramulator required LOADs become yaml-cpp and spdlog. Reversing the explicit map-policy text substitution and normalizing REVISION yields exact text and AST equality.',
        'driver_semantic_change_basis': 'agents/w10_a05-spdlog-selection.md and host-diagnostic/review-04-spdlog-selection.json; the parent approved this exact three-change transformation before preparation.',
        'driver_unified_diff': ''.join(difflib.unified_diff(original.splitlines(True), replacement.splitlines(True), fromfile='driver.py', tofile='driver-05.py')),
        **resources(),
    }
    if args.phase == 'preflight':
        assert not WORKSPACE.exists()
        with driver.open('x') as stream:
            stream.write(replacement)
        basic.update(scope='Attempt05 prerequisites and exact revision plus reviewed Ramulator map-policy substitutions; no preparation or build at this snapshot', driver=identity(driver), original_driver=identity(PACKET / 'driver.py'), preparation_started=False, execution_started=False)
        write_exclusive(PACKET / 'execution-05-preflight.json', basic)
        print(json.dumps(basic, indent=2))
        return
    assert driver.read_text() == replacement
    sys.path.insert(0, str(helpers / 'ci/project'))
    modules = {name: importlib.import_module(name) for name in ('p06_dependency_build', 'p06_dependency_receipt', 'p06_dependency_binary', 'p06_dependency_sources', 'p06_dependency_graph', 'p06_dependency_contract', 'p06_dependency_record', 'baseline_process', 'preflight')}
    assert all(Path(mod.__file__).resolve().is_relative_to(helpers / 'ci/project') for mod in modules.values())
    build = modules['p06_dependency_build']; sources = modules['p06_dependency_sources']; contract = modules['p06_dependency_contract']; recorder = modules['p06_dependency_record']
    prepared_path = WORKSPACE / 'prepared.json'
    prepared = json.loads(prepared_path.read_text())
    report = json.loads((WORKSPACE / 'evidence/host-diagnostic.json').read_text())
    previous = json.loads(Path('/workspace/p06-host-diagnostic-fixed-04/prepared.json').read_text())
    assert report['state'] == 'prepared' and report['outcome'] == 'not_run'
    assert report['observations'] == prepared
    assert report['prepared'] == identity(prepared_path)
    assert prepared['driver'] == identity(driver)
    assert prepared['helper_revision'] == args.revision
    assert prepared['helper_sources'] == build.helper_inventory()
    assert len(prepared['helper_sources']) == 18
    for row in prepared['helper_sources']:
        source_raw = git(helpers, 'show', args.revision + ':' + row['path'])
        retained = WORKSPACE / 'evidence/helpers' / row['path']
        assert source_raw == retained.read_bytes() == (helpers / row['path']).read_bytes()
        assert len(source_raw) == row['size_bytes']
        assert hashlib.sha256(source_raw).hexdigest() == row['sha256']
    assert len(prepared['tools']) == 7
    assert all(recorder.file_identity(row['path']) == row for row in prepared['tools'].values())
    assert prepared['budget'] == previous['budget'] == contract.BUDGET
    assert contract.MAX_FILE_BYTES == 64 * 1024**2
    assert contract.MAX_RECEIPT_BYTES == contract.BUDGET['max_log_bytes'] == 16 * 1024**2
    assert prepared['source_manifest'] == previous['source_manifest']
    assert prepared['source_plan'] == previous['source_plan']
    check = sources.verify_sources(prepared['source_manifest'], WORKSPACE / 'dependency-sources')
    for component in prepared['source_manifest']['sources']:
        for row in component['files']:
            retained = WORKSPACE / 'evidence/sources' / component['name'] / row['path']
            raw = retained.read_bytes()
            assert len(raw) == row['size_bytes'] and hashlib.sha256(raw).hexdigest() == row['sha256']
    assert prepared['commands'] == prepared['stability_checks'] == prepared['generated_inputs'] == []
    assert prepared['compile_database'] is None
    assert not list((WORKSPACE / 'evidence/records').glob('*'))
    assert not (WORKSPACE / 'execution-started').exists()
    old_helpers = {row['path']: row for row in previous['helper_sources']}
    changed = [{'path': row['path'], 'before': old_helpers[row['path']], 'after': row} for row in prepared['helper_sources'] if row != old_helpers[row['path']]]
    assert {row['path'] for row in changed} == {'ci/project/p06_dependency_binary.py', 'ci/project/p06_dependency_record.py', 'ci/project/p06_dependency_build.py', 'ci/project/p06_dependency_receipt.py'}
    basic.update(scope='Prepared fresh host-only diagnostic attempt05; zero compiler or native execution at this snapshot',
        driver=identity(driver), prepared=identity(prepared_path), tool_config=identity(WORKSPACE / 'evidence/tool-config.json'),
        helper_sources=prepared['helper_sources'], helper_sources_match_git_and_retained_bytes=True,
        changed_helper_files_from_attempt04=changed, tools=prepared['tools'], selected_tools_verified=True,
        resources_before_prepare=prepared['resources_before_prepare'], budget=prepared['budget'],
        source_manifest_sha256=contract.digest(prepared['source_manifest']), source_plan_sha256=contract.digest(prepared['source_plan']),
        source_files=prepared['source_manifest']['total_files'], source_bytes=prepared['source_manifest']['total_size_bytes'],
        planned_translation_units=len(prepared['source_plan']), source_verification=check, retained_sources_verified=True,
        actual_outer_commands=0, actual_tool_records=0, execution_marker_present=False,
        **{key: report[key] for key in ('state','outcome','native_execution','fresh_dependency_build_passed','host_diagnostic_passed','dependency_source_to_loaded_binary_verified','measurement_staging_executed','formal_preparation_executed','cache_restoration_claimed',*contract.FALSE_CLAIMS)})
    assert all(basic[key] is False for key in contract.FALSE_CLAIMS)
    write_exclusive(PACKET / 'preparation-05.json', basic)
    print(json.dumps({key: basic[key] for key in ('helper_revision','helper_tree','prepared','source_files','source_bytes','planned_translation_units','actual_outer_commands','actual_tool_records','state','outcome')}, indent=2))

if __name__ == '__main__':
    main()
