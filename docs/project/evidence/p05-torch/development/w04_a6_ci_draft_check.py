import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest
root=Path('/workspace/scratch/55f1fb23ad42/AI-GPU')
work=root.parent/'p05-torch-work'
sys.path.insert(0,str(root/'ci/project'))
spec=importlib.util.spec_from_file_location('w04_a6_ci_tests',work/'drafts/w04_a6/ci/project/test_p05_torch_ci.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
m.ROOT=root
m.WORKFLOW=work/'drafts/w04_a6/.github/workflows/p05-torch.yml'
m.PYTHON_WORKFLOW=root/'.github/workflows/p05-python.yml'
m.GOVERNANCE=root/'.github/workflows/project-governance.yml'
m.CONTRACT=root/'ci/project/p05_torch_contract.json'
m.LOCK=root/'ci/project/p05_torch_requirements.lock'
result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(m))
blocks=[m.script(step) for step in m.steps(m.children(m.children(m.workflow(m.WORKFLOW),'jobs',2),'qualification',4)) if 'run' in step]
for block in blocks:
 r=subprocess.run(['bash','-n'],input=block,text=True,capture_output=True)
 assert r.returncode==0,r.stderr
print(json.dumps({'shell_blocks':len(blocks),'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'scope':'host-only-workflow-contract'}))
raise SystemExit(not result.wasSuccessful())
