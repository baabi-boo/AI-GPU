import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / 'AI-GPU/ci/project'))
from baseline_process import run_bounded

spec = json.loads(Path(sys.argv[1]).read_text())
env = {**os.environ, 'OBJCACHE': '', 'CCACHE_DISABLE': '1', 'TMPDIR': str(ROOT / 'tmp')}
(ROOT / 'tmp').mkdir(exist_ok=True)
env.update(spec.get('env', {}))
log = ROOT / 'logs' / (spec['id'] + '.log')
result = run_bounded(spec['argv'], spec['cwd'], env, log,
    timeout_seconds=spec.get('timeout_seconds', 900), min_free_bytes=15*1024**3,
    max_log_bytes=16*1024**2, max_rss_bytes=6*1024**3,
    resource_paths=[ROOT, ROOT / 'tmp'])
record = {'id': spec['id'], 'argv': spec['argv'], 'cwd': spec['cwd'], 'environment_overrides': spec.get('env', {}),
          'log': str(log), 'limits': {'jobs': 2, 'min_free_gib': 15, 'max_rss_gib': 6, 'max_log_mib': 16}, **result}
(ROOT / 'reports' / (spec['id'] + '.json')).write_text(json.dumps(record, indent=2)+'\n')
print(json.dumps(record, indent=2))
sys.exit(0 if result['outcome'] == 'pass' else 1)
