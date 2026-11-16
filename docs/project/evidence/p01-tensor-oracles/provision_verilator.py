import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent / 'AI-GPU'
sys.path.insert(0, str(SOURCE / 'ci/project'))
from baseline_bootstrap import extract_component, load_manifest, verify_part

lock = load_manifest(SOURCE / 'ci/project/p01_toolchain.lock.json')
checkout = ROOT / 'toolchain-source'
revision = subprocess.check_output(['git', '-C', str(checkout), 'rev-parse', 'HEAD'], text=True).strip()
assert revision == lock['revision'], 'toolchain source does not match immutable lock'
parts = [p for p in lock['parts'] if p['path'].startswith('verilator/')]
assert len(parts) == 3
archive = ROOT / 'verilator.tar.bz2'
with archive.open('xb') as out:
    for part in parts:
        path = checkout / part['path']
        verify_part(path, part)
        with path.open('rb') as src:
            shutil.copyfileobj(src, out, 1024 * 1024)
extract_component(archive, ROOT / 'tools', 'verilator', 15 * 1024**3)
tool = ROOT / 'tools/verilator/bin/verilator'
version = subprocess.check_output([str(tool), '--version'], text=True).strip()
result = {'scope': 'Verilator-only provisioning; not a complete baseline toolchain receipt',
          'toolchain_revision': revision, 'parts': parts, 'version': version,
          'free_disk_bytes': shutil.disk_usage(ROOT).free}
(ROOT / 'reports/provision-verilator.json').write_text(json.dumps(result, indent=2)+'\n')
print(json.dumps(result, indent=2))
