set -euo pipefail
python3 - <<'PY' 2>&1 | tee "$P06_MANAGED_REPLAY_ROOT/evidence/tests.log"
import unittest
loader = unittest.TestLoader()
suite = unittest.TestSuite()
for pattern in (
    'test_p06_managed_preflight_replay*.py',
    'test_p06_managed_preflight_source_export.py',
    'test_p06_managed_preflight_application_build.py',
    'test_p06_managed_preflight_derivation.py',
    'test_p06_managed_preflight_generated.py',
):
    selected = loader.discover('ci/project', pattern=pattern)
    if selected.countTestCases() == 0:
        raise RuntimeError('Required replay test group is missing: ' + pattern)
    suite.addTests(selected)
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
PY
