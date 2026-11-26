#!/usr/bin/env python3
"""Run synthetic checkpoint integration tests against the unchanged HEAD writer."""

import ast
from pathlib import Path
import subprocess
import sys
import unittest

sys.dont_write_bytecode = True
repository = Path("/tmp/ai-gpu-2bfab0261c05/repo")
sys.path.insert(0, str(repository / "ci/project"))
import p02_matrix as base

revision = "858090410a992756808256ace90d36b9b3b88dd3"
source = subprocess.check_output(
    ["git", "show", revision + ":ci/project/p02_matrix.py"], cwd=repository, text=True)
writer = next(node for node in ast.parse(source).body
              if isinstance(node, ast.FunctionDef) and node.name == "_write_json")
exec(compile(ast.Module(body=[writer], type_ignores=[]), revision + ":p02_matrix.py", "exec"),
     base.__dict__)
suite = unittest.defaultTestLoader.loadTestsFromName("test_p06_checkpoint_run_recovery")
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(not result.wasSuccessful())
