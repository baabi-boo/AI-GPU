import importlib.util
from pathlib import Path
import sys
import unittest
root=Path('/workspace/scratch/55f1fb23ad42/AI-GPU')
work=root.parent/'p05-torch-work'
sys.path.insert(0,str(root/'ci/project'))
source=root/'ci/project/p05_torch_native_host_tests.py' if sys.argv[1]=='original' else work/'drafts/w04_a6/p05_torch_native_host_tests.py'
name='p05_torch_native_host_tests'
spec=importlib.util.spec_from_file_location(name,source)
module=importlib.util.module_from_spec(spec)
sys.modules[name]=module
spec.loader.exec_module(module)
testspec=importlib.util.spec_from_file_location('test_w04_a6_retention',work/'drafts/w04_a6/test_p05_torch_native_host_orchestration.py')
tests=importlib.util.module_from_spec(testspec)
testspec.loader.exec_module(tests)
suite=unittest.defaultTestLoader.loadTestsFromModule(tests)
result=unittest.TextTestRunner(verbosity=2).run(suite)
assert 'torch' not in sys.modules
raise SystemExit(not result.wasSuccessful())
