import importlib.util
import json
from pathlib import Path
import sys
import unittest

root = Path(__file__).resolve().parents[1]
test_path = root / "repo/ci/project/test_p06_encrypt_reader_ownership.py"
spec = importlib.util.spec_from_file_location("test_p06_encrypt_reader_ownership", test_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.SOURCE = root / "reports/a034-encrypt-before.py"
suite = unittest.defaultTestLoader.loadTestsFromModule(module)

def identifiers(tests):
    for test in tests:
        if isinstance(test, unittest.TestSuite):
            yield from identifiers(test)
        else:
            yield test.id()

ids = list(identifiers(suite))
result = unittest.TextTestRunner(verbosity=2).run(suite)
summary = {"source": module.SOURCE.name, "test_ids": ids, "tests_run": result.testsRun,
           "failures": len(result.failures), "errors": len(result.errors),
           "skips": len(result.skipped), "successful": result.wasSuccessful()}
(root / "reports/a037-negative-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps({key: value for key, value in summary.items() if key != "test_ids"}))
raise SystemExit(not result.wasSuccessful())
