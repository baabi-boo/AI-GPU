"""Independent A54 replay of the five A51 YAML assertion regressions."""
import ast
import difflib
import hashlib
import json
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

ROOT = Path('/tmp/ai-gpu-850acdff3419/repo')
OUT = ROOT.parent / 'validation/A54'
sys.path.insert(0, str(ROOT / 'ci/project'))
import test_p06_qualified_warm_hosted as corrected

def identity(path):
    raw = path.read_bytes()
    return {'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

paths = {
    'original_yaml': ROOT.parent / 'validation/A37/test_p06_qualified_warm_hosted.before.py',
    'before_a51': ROOT.parent / 'validation/A51/tests-before-a51.py',
    'current': ROOT / 'ci/project/test_p06_qualified_warm_hosted.py',
}
before = {name: identity(path) for name, path in paths.items()}
assert before['before_a51']['git_blob'] == '626ca94406f0a45be300154d588bc39e8c693330'
assert before['current']['git_blob'] == '611357b71f0ef8218a1a8a7a6bdc415b4aaed071'
modules = {'current': corrected}
for name in ('original_yaml', 'before_a51'):
    mod = types.ModuleType('a54_' + name)
    mod.__file__ = str(paths[name])
    exec(compile(paths[name].read_text(), str(paths[name]), 'exec'), mod.__dict__)
    modules[name] = mod

workflow_path = ROOT / corrected.hosted.WORKFLOW
canonical = workflow_path.read_text()
action = '        uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2'
assert canonical.count(action) == 1
run_start = canonical.index('        run: |\n')
run_stop = canonical.index('      - name:', run_start)
cases = {
    'canonical': canonical,
    'action_continuation': canonical.replace(action, action.split(' #', 1)[0] + '\n          /unreviewed-continuation', 1),
    'checkout_id_continuation': canonical.replace('        id: checkout\n', '        id: checkout\n          _continuation\n', 1),
    'hosted_id_continuation': canonical.replace('        id: hosted\n', '        id: hosted\n          _continuation\n', 1),
    'upload_path_lower_indent': canonical.replace('            ${{ runner.temp }}/p06-qualified-warm-attempt/public/', '           *${{ runner.temp }}/p06-qualified-warm-attempt/public/'),
    'run_lower_indent': canonical[:run_start] + '        run: |\n         governance_run.py\n' + canonical[run_stop:],
}
real_text, real_bytes = Path.read_text, Path.read_bytes
observations = []
for label, source in cases.items():
    assert label == 'canonical' or source != canonical
    modules['original_yaml'].yaml.load(source, Loader=modules['original_yaml'].yaml.BaseLoader)
    def read_text(path, *args, **kwargs):
        return source if path == workflow_path else real_text(path, *args, **kwargs)
    def read_bytes(path, *args, **kwargs):
        return source.encode() if path == workflow_path else real_bytes(path, *args, **kwargs)
    for version in ('original_yaml', 'before_a51', 'current'):
        suite = unittest.TestLoader().loadTestsFromTestCase(modules[version].HostedWorkflowTests)
        result = unittest.TestResult()
        with mock.patch.object(Path, 'read_text', read_text), mock.patch.object(Path, 'read_bytes', read_bytes):
            suite.run(result)
        expected = label == 'canonical' or version == 'before_a51'
        row = {'case': label, 'version': version, 'yaml_valid': True,
               'accepted': result.wasSuccessful(), 'expected_accepted': expected,
               'tests_run': result.testsRun, 'failures': len(result.failures),
               'errors': len(result.errors), 'skips': len(result.skipped)}
        observations.append(row)
        print(json.dumps(row, sort_keys=True), flush=True)
        assert result.testsRun == 2 and result.wasSuccessful() == expected and not result.skipped, row

def methods(path):
    return {(cls.name, node.name): ast.dump(node, include_attributes=False)
            for cls in ast.parse(path.read_text()).body if isinstance(cls, ast.ClassDef)
            for node in cls.body if isinstance(node, ast.FunctionDef) and node.name.startswith('test_')}

old_methods, new_methods = methods(paths['before_a51']), methods(paths['current'])
assert list(old_methods) == list(new_methods) and len(new_methods) == 34
changed = [key for key in old_methods if old_methods[key] != new_methods[key]]
assert changed == [('HostedWorkflowTests', 'test_manual_trusted_exact_revision_read_only_workflow'),
                   ('HostedWorkflowTests', 'test_artifact_upload_has_only_ciphertext_and_sanitized_summary')]
after = {name: identity(path) for name, path in paths.items()}
assert before == after
summary = {'scope': 'independent five-case workflow assertion parity; no native work',
           'passed': True, 'python': sys.version, 'python_executable': sys.executable,
           'yaml_version': modules['original_yaml'].yaml.__version__,
           'observations': observations, 'source_identities': before,
           'source_stable': before == after,
           'all_34_method_names_and_order_preserved': True,
           'unchanged_method_asts': 32, 'changed_methods': changed,
           'review': 'The delta adds scalar continuation and literal-script indentation checks; exact upload tuple comparison retains complete lines. Original workflow trust, checkout, actions, timeout, cancellation, private configuration, native-preflight separation, and ciphertext-only upload assertions remain present.'}
(OUT / 'parser-parity.json').write_text(json.dumps(summary, indent=2, sort_keys=True) + '\n')
(OUT / 'a51-authored.diff').write_text(''.join(difflib.unified_diff(
    paths['before_a51'].read_text().splitlines(keepends=True),
    paths['current'].read_text().splitlines(keepends=True),
    fromfile='blob:626ca94406f0a45be300154d588bc39e8c693330',
    tofile='blob:611357b71f0ef8218a1a8a7a6bdc415b4aaed071')))
print('A54 independent parser parity: PASS; canonical accepted by all versions; all five mutations rejected by original and current.', flush=True)
