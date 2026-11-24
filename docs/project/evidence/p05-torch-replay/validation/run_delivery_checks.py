"""Bounded metadata and workflow checks on the actual final documentation candidate."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

root = Path.cwd().resolve()
out = Path('/workspace/scratch/101d52695253/validation')
commands = [
    ['python3', '-B', 'ci/project/check_project.py'],
    ['python3', '-B', 'ci/project/check_baseline_packets.py'],
    ['python3', '-B', '-m', 'unittest', 'discover', '-s', 'ci/project', '-p', 'test_p05_governance_integration.py', '-v'],
    ['python3', '-B', '-m', 'unittest', 'discover', '-s', 'ci/project', '-p', 'test_p05_torch_ci.py', '-v'],
]
tracked = ['.github/workflows/project-governance.yml', 'docs/project/roadmap.json',
           'ci/project/check_project.py', 'ci/project/check_baseline_packets.py',
           'ci/project/test_p05_governance_integration.py', 'ci/project/test_p05_torch_ci.py',
           'docs/project/evidence/p05-torch-replay/acceptance-torch.json',
           'docs/project/evidence/p05-torch-replay/acceptance-compatibility.json',
           'docs/project/p05-torch-compatibility.md', 'docs/assets/img/vortex_framework_stack.svg']
sha = lambda p: hashlib.sha256((root / p).read_bytes()).hexdigest()
before = {p: sha(p) for p in tracked}
rows = []
for i, command in enumerate(commands):
    output = out / ('delivery-check-%d.log' % i)
    start = time.monotonic()
    with output.open('w') as stream:
        result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT,
                                env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1',
                                     'TMPDIR': '/tmp/ai-gpu-p05-host-temp-101d52695253'}, timeout=180)
    rows.append({'command': command, 'exit_code': result.returncode,
                 'seconds': round(time.monotonic() - start, 6), 'log': output.name,
                 'log_sha256': hashlib.sha256(output.read_bytes()).hexdigest()})
after = {p: sha(p) for p in tracked}
changed = [p for p in tracked if before[p] != after[p]]
record = {'scope': 'Final candidate metadata/baseline consistency and affected workflow contracts; no full-suite/native claim',
          'cwd': str(root), 'git_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
          'working_tree_is_clean': False, 'source_sha256_before': before, 'source_sha256_after': after,
          'source_changed': changed, 'commands': rows,
          'outcome': 'pass' if all(x['exit_code'] == 0 for x in rows) and not changed else 'fail'}
(out / 'delivery-checks.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps({'outcome': record['outcome'], 'commands': rows, 'source_changed': changed}))
raise SystemExit(0 if record['outcome'] == 'pass' else 1)
