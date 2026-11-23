from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest import mock

ROOT = Path('/workspace/AI-GPU')
WORK = Path('/workspace/w10-a06-review')
REVISION = 'c44bb0df7091f27e58d125d70fab80fb13b58557'
sys.path.insert(0, str(ROOT / 'ci/project'))
import test_p06_dependency_spdlog_selection as regression


def old_module(name):
    original = subprocess.check_output(['git', 'show', REVISION + ':ci/project/' + name + '.py'], cwd=ROOT)
    path = WORK / 'old' / 'ci' / 'project' / (name + '.py')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(original)
    spec = importlib.util.spec_from_file_location('w10_old_' + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, {'path': 'ci/project/' + name + '.py', 'sha256': hashlib.sha256(original).hexdigest(), 'size_bytes': len(original)}


started = datetime.now(timezone.utc).isoformat()
old_build, old_build_identity = old_module('p06_dependency_build')
old_receipt, old_receipt_identity = old_module('p06_dependency_receipt')
test_type = regression.UnselectedArchiveTests
test_type.setUpClass()
observations = []
try:
    case = test_type('test_actual_producer_admits_only_the_observed_member_selection')
    case.setUp()
    document, payloads = case.scoped_receipt()
    case.verify_scoped(document, payloads)
    with mock.patch.object(regression, 'build', old_build):
        try:
            case.producer().verify_products()
        except ValueError as error:
            if str(error) != 'link map lacks required archive-member evidence':
                raise
            observations.append({'boundary': 'published old Builder.verify_products', 'outcome': 'expected_rejection', 'reason': str(error)})
        else:
            raise AssertionError('old producer unexpectedly accepted unused spdlog archive')
    with mock.patch.object(regression, 'receipt', old_receipt):
        try:
            case.verify_scoped(document, payloads)
        except ValueError as error:
            if str(error) != 'link map lacks required archive-member evidence':
                raise
            observations.append({'boundary': 'published old verify_document archive/link callsite', 'outcome': 'expected_rejection', 'reason': str(error)})
        else:
            raise AssertionError('old inert receipt unexpectedly accepted unused spdlog archive')
    case.verify_scoped(document, payloads)
finally:
    test_type.doClassCleanups()

report = {'schema_version': 1, 'scope': 'Two isolated published-old-callsite negative controls using the tiny actual host fixture and explicit upstream substitutions',
          'published_old_revision': REVISION, 'old_sources': [old_build_identity, old_receipt_identity],
          'other_imports': 'Current reviewed dependencies; only each named old callsite module is substituted in its individual control.',
          'started_at_utc': started, 'finished_at_utc': datetime.now(timezone.utc).isoformat(),
          'observations': observations, 'expected_rejections': 2,
          'current_callsite_positive_before_and_after': True,
          'complete_pinned_dependency_original': False, 'native_execution': 'not_run',
          'qualification_or_acceptance_claimed': False}
path = ROOT / 'docs/project/evidence/p06-dependency-provenance/validation/w10_a06-published-negative-01.json'
path.write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
