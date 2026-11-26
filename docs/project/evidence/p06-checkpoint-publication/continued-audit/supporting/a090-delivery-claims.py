#!/usr/bin/env python3
"""Read inert retained records and Git objects; execute no project code."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess
from datetime import datetime, timezone
import zipfile

ROOT = Path('/tmp/ai-gpu-2bfab0261c05')
SOURCE = ROOT / 'published-source'
AUDIT = ROOT / 'audit'
PACKET = SOURCE / 'docs/project/evidence/p06-checkpoint-publication'
CONT = AUDIT / 'docs/project/evidence/p06-checkpoint-publication/continued-audit'
PUBLISHED = '30b2e8ca69fba47646392c0cf6650cbb75155843'
LOCAL = '9f369a579ca764800b22eedd15e09795f09615da'
CODE = 'd31e8879e7c248b1a72615128882533ccdd0b3b4'
BASE = '858090410a992756808256ace90d36b9b3b88dd3'
TREE = '548b85370e3d13119730b5a30d1ec388d3e141a9'
checks = []
started = datetime.now(timezone.utc).isoformat()

def digest(body):
    return hashlib.sha256(body).hexdigest()

def git(*args):
    return subprocess.check_output(['git', '-C', str(SOURCE), *args])

def check(name, condition, detail=None):
    checks.append({'name': name, 'passed': bool(condition), 'detail': detail})

docs = [CONT/'README.md', AUDIT/'docs/project/p06-qualified-warm-handoff.md',
        SOURCE/'docs/project/p06-checkpoint-publication-audit.md', PACKET/'README.md']
observed_docs = {str(p): p.read_bytes() for p in docs}
pub = json.loads((CONT/'publication/master-publication.json').read_text())
uploads = json.loads((CONT/'publication/uploads-089.json').read_text())
verified = json.loads((CONT/'publication/a068-publication-verified.json').read_text())
focused = json.loads((PACKET/'validation/final-focused.json').read_text())
discovery = json.loads((PACKET/'validation/final-discovery.json').read_text())
invariants = json.loads((PACKET/'validation/final-protected-inputs.json').read_text())
replay = json.loads((PACKET/'base-governance/replay/replay.json').read_text())
provider = json.loads((PACKET/'base-governance/provider-original.json').read_text())
head_before = git('rev-parse', 'HEAD').decode().strip()
status_before = git('status', '--porcelain=v1').decode()
check('published_source_checkout_exact_clean', head_before == PUBLISHED and not status_before)
check('published_and_local_complete_trees_equal', git('rev-parse', PUBLISHED+'^{tree}').decode().strip() == git('rev-parse', LOCAL+'^{tree}').decode().strip() == TREE)
check('published_and_local_full_file_diff_empty', git('diff', PUBLISHED, LOCAL) == b'')
check('five_publication_mappings', len(pub['commit_mapping']) == 5)
check('89_unique_verified_uploaded_blobs', len(uploads['verified_blobs']) == len({r['sha'] for r in uploads['verified_blobs']}) == 89 and all(r['verified'] for r in uploads['verified_blobs']))
check('nonforced_expected_base_publication_record', pub['force'] is False and pub['expected_base'] == pub['ref_before'] == BASE and pub['ref_after'] == pub['published_sha'] == PUBLISHED)
check('47_passing_independent_publication_assertions_retained', len(verified['checks']) == verified['check_count'] == 47 and all(x['passed'] for x in verified['checks']))
for n, row in enumerate(pub['commit_mapping'], 1):
    local = git('cat-file', 'commit', row['local_sha'])
    remote = git('cat-file', 'commit', row['published_sha'])
    raw = (CONT/'publication/raw'/row['raw_local_commit_file']).read_bytes()
    identity = hashlib.sha1(b'commit '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
    check(f'commit_mapping_{n}_parents_trees_raw_identity', raw == local and identity == row['local_sha'] and ('tree '+row['tree']+'\n').encode() in local and ('tree '+row['tree']+'\n').encode() in remote and ('parent '+row['local_parent']+'\n').encode() in local and ('parent '+row['published_parent']+'\n').encode() in remote)

r = focused['result']
selection = focused['selection']
check('focused_258_unique_methods_18_modules', len(set(r['started_ids'])) == len(r['started_ids']) == len(r['completed_ids']) == r['testsRun'] == selection['test_count'] == selection['unique_test_count'] == 258 and selection['module_count'] == 18)
check('focused_all_success_752_subtests', r['wasSuccessful'] and r['successful_test_events'] == 258 and r['subtest_counts'] == {'error':0,'failure':0,'skip':0,'success':752} and len(r['subtests']) == 752)
check('focused_zero_failures_errors_skips_other_outcomes', all(r[k] == 0 for k in ('errors_count','failures_count','skips_count','expected_failures_count','unexpected_successes_count')) and not r['duplicate_executed_test_ids'] and not r['selected_ids_not_started'] and not r['unselected_started_ids'])
check('focused_exact_recorded_code_source', focused['expected_head'] == focused['git_before']['head'] == focused['git_after']['head'] == CODE)
check('focused_122_stable_observed_source_hashes_bind_published_files', len(focused['source_hashes']) == 122 and all(d['before'] == d['after'] == digest((SOURCE/p).read_bytes()) for p,d in focused['source_hashes'].items()))
check('focused_932_inventory_hashes_stable_at_recorded_scope', len(focused['all_repository_python_sha256_before']) == len(focused['all_repository_python_sha256_after']) == 932 and focused['all_repository_python_sha256_before'] == focused['all_repository_python_sha256_after'] and not focused['all_repository_python_hash_mismatches'])
check('focused_recorded_git_process_state_stable', focused['git_before'] == focused['git_after'] and all(not focused[k] for k in ('hash_mismatches','import_state_delta','execution_state_delta','whole_process_state_delta','unbaselined_loaded_paths')))
check('focused_raw_unittest_duration_28_921', b'Ran 258 tests in 28.921s' in (PACKET/'validation/final-focused.log').read_bytes())
check('focused_documentation_scope_explicit', focused['scope'] == 'One selected-module host-side unittest invocation; no governance or native qualification.')

ids = discovery['test_ids']
check('discovery_5547_unique_ids_and_digest', len(ids) == len(set(ids)) == discovery['count'] == discovery['unique_count'] == 5547 and digest(('\n'.join(ids)+'\n').encode()) == discovery['test_ids_sha256_newline_ordered'] == '0e8dbaad34266093f76db937eba670ce8f628ceb500998cb9094cdd2f12071fa')
check('discovery_is_not_test_execution', discovery['test_execution'] == 'not_run' and discovery['scope'] == 'canonical-unittest-discovery-only')
check('discovery_no_loader_errors_duplicates_placeholders', not discovery['loader_errors'] and not discovery['duplicate_test_ids'] and not discovery['failed_test_placeholders'])
new_ids = set(discovery['base_delta']['added_test_ids'])
ast_ids = set()
for module in discovery['base_delta']['expected_modules']:
    tree = ast.parse((SOURCE/'ci/project'/f'{module}.py').read_text())
    for cls in tree.body:
        if isinstance(cls, ast.ClassDef):
            ast_ids.update(f'{module}.{cls.name}.{m.name}' for m in cls.body if isinstance(m, ast.FunctionDef) and m.name.startswith('test_'))
check('all_32_new_methods_in_focused_run_and_ast', new_ids == ast_ids and len(new_ids) == 32 and new_ids <= set(selection['test_ids']))
check('new_methods_are_24_checkpoint_and_8_launcher', sum('.test_' in x and x.startswith('test_p05_launcher_signals.') for x in new_ids) == 8 and len(new_ids)-8 == 24)
archive = PACKET/'base-governance/run-45762183368-attempt1.zip'
check('base_original_matches_provider_size_and_digest', archive.stat().st_size == provider['size_in_bytes'] == 1395652 and 'sha256:'+digest(archive.read_bytes()) == provider['digest'] == 'sha256:21c1c6bda5e8513d99642dd12d5db8c52d4b2bcae8726119b12236e7708fc74e')
with zipfile.ZipFile(archive) as z:
    manifest = json.loads(z.read('run/discovered.json'))
    original_summary = json.loads(z.read('run/summary.json'))
base_ids = manifest['test_ids']
check('base_5515_ids_preserved_order_32_additions_zero_removals', len(base_ids) == len(set(base_ids)) == 5515 and [x for x in ids if x in set(base_ids)] == base_ids and set(ids)-set(base_ids) == new_ids and not set(base_ids)-set(ids))
check('base_replay_exact_revision_counts_duration', replay['revision'] == provider['workflow_run']['head_sha'] == BASE and (replay['canonical_tests'],replay['successful_subtests'],replay['events'],replay['duration_seconds']) == (5515,38655,55200,3134.501976))
check('base_provider_run_artifact_identity', provider['workflow_run']['id'] == 45762183368 and provider['id'] == 15092372891 and provider['name'] == f'project-governance-{BASE}-run45762183368-attempt1')
check('base_replay_not_provider_auth_or_test_execution_or_acceptance', all(replay[k] is False for k in ('provider_authenticated','tests_executed_by_replay','retained_code_executed','native_acceptance','performance_acceptance','phase_acceptance')))

check('14_protected_input_assertions_retained_pass', invariants['all_pass'] and len(invariants['checks']) == 14 and all(invariants['checks'].values()) and invariants['head_before'] == invariants['head_after'] == CODE)
measurements = invariants['measurement_sources']['inventory']
check('69_measurement_files_exact_published_bytes', len(measurements) == 69 and sum(r['size_bytes'] for r in measurements) == 1303138 and all((SOURCE/r['path']).stat().st_size == r['expected_size_bytes'] and digest((SOURCE/r['path']).read_bytes()) == r['expected_sha256'] for r in measurements))
check('21_dependency_descriptors_not_fresh_byte_hashes', invariants['dependency_descriptors']['count'] == 21 and invariants['dependency_descriptors']['local_source_files_present'] == 0 and invariants['dependency_descriptors']['source_bytes_rehashed'] == 0)
check('25_goldens_39_numerical_fixtures', len(invariants['golden_baselines']) == 25 and len(invariants['numerical_fixtures']) == 39)
check('qualified_warm_declared_24_792_25344', tuple(invariants['complete_counts'][k] for k in ('processes','launches','checked_words')) == (24,792,25344))
check('frozen_disk_15gib_and_memory_4gib_source', invariants['warm_budget']['min_free_bytes'] == 15*1024**3 and 'REQUIRED_BYTES = 4 * 1024**3' in (SOURCE/'ci/project/p06_qualified_warm_capacity.py').read_text())
svg = SOURCE/'docs/assets/img/vortex_framework_stack.svg'
check('protected_svg_48225_bytes_and_exact_digest', svg.stat().st_size == 48225 and digest(svg.read_bytes()) == 'db123c71024f85f379c2504c7465c03ee9df8959a5d17fc3d3e94a94a1cd3aa4')
legacy = (SOURCE/'ci/project/p06_warm_analyze.py').read_text()
auto_workflow = (SOURCE/'.github/workflows/p06-warm-workspace.yml').read_text()
qualified_workflow = (SOURCE/'.github/workflows/p06-qualified-warm.yml').read_text()
check('legacy_automatic_route_explicitly_unqualified', 'branches: [master]' in auto_workflow and 'p06_warm_execute.py run' in auto_workflow and '"status": "blocked", "qualified": False' in legacy and '"counter_transport": "unqualified_low_32_bits"' in legacy)
check('qualified_route_manual_and_separate', '\n  workflow_dispatch:' in qualified_workflow and '\n  push:' not in qualified_workflow and 'p06_qualified_warm_hosted.py run' in qualified_workflow)

handoff_path = 'docs/project/p06-qualified-warm-handoff.md'
old_handoff = git('show', PUBLISHED+':'+handoff_path).decode()
new_handoff = observed_docs[str(AUDIT/handoff_path)].decode()
anchor = '**Closeout reliability fixes are implemented;'
check('entire_previous_handoff_body_preserved', new_handoff[new_handoff.index(anchor):] == old_handoff[old_handoff.index(anchor):])
check('superseded_closeout_section_explicitly_historical', '## Earlier closeout reliability continuation (historical)' in new_handoff and new_handoff.index('## Checkpoint publication and launcher continuation') < new_handoff.index('## Earlier closeout reliability continuation (historical)'))
readme = observed_docs[str(CONT/'README.md')].decode()
check('continuation_names_distinct_test_discovery_base_scopes', 'Discovery did not execute test bodies.' in readme and "applies only to that base" in readme and 'does not qualify the\nentire published revision.' in readme)
check('continuation_does_not_claim_100_completed_or_current_ci_pass', '100 distinct agents' in readme and '100 completed' not in readme and "strict governance result and independently reconciled original remain required" in readme)
check('continuation_preserves_native_input_and_resource_prerequisites', 'qualified-warm attempt remains unstarted' in readme and '15 GiB free disk / 4 GiB available memory' in readme and 'public age\nrecipient' in readme and 'control delivery' in readme)
check('reviewed_documents_stable_during_this_script', all(p.read_bytes() == observed_docs[str(p)] for p in docs))
check('published_checkout_head_and_status_unchanged', git('rev-parse','HEAD').decode().strip() == head_before and git('status','--porcelain=v1').decode() == status_before)

result = {
    'schema_version': 1, 'agent': '/root/a090_delivery_claim_review',
    'scope': 'Read-only consistency review of current delivery claims, inert retained records, and local Git objects; no project code imported or test bodies run.',
    'started_at': started, 'finished_at': datetime.now(timezone.utc).isoformat(),
    'published_source_revision': PUBLISHED, 'local_equivalent_revision': LOCAL,
    'focused_code_revision': CODE, 'base_governance_revision': BASE,
    'reviewed_documents': [{'path':str(p), 'bytes':len(observed_docs[str(p)]), 'sha256':digest(observed_docs[str(p)])} for p in docs],
    'check_count':len(checks), 'all_passed':all(c['passed'] for c in checks), 'checks':checks,
    'network_requests':False, 'project_tests_executed':False, 'native_execution':False,
    'source_mutations':False, 'current_provider_ci_status_queried':False,
    'limitations':[
        'Current provider run completion is outside this offline review; no current-source governance or native pass is inferred.',
        'Retained focused-run and invariant records establish their recorded observations; this review does not rerun the tests or reproduce their runtime state.',
        'The entire previous handoff body was preserved and explicitly separated; historical execution and resource observations are not requalified for this source.',
        'This snapshot does not assert that all 100 requested reports are complete; the ledger was still being populated.',
        'No private control, recipient, provider secret, dependency source-byte materialization, or native resource admission is established.'
    ]
}
(ROOT/'a090-delivery-claims.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
print(json.dumps({'checks':len(checks),'all_passed':result['all_passed'],'failed':[c['name'] for c in checks if not c['passed']]}))
