#!/usr/bin/env bash
set -euo pipefail
set -C
umask 077
REPLAY_SOURCE=/tmp/ai-gpu-b4f42b8a9d4b/repo
REPLAY_REVISION=81d7a35c641f3a969c23c8e604f7468a4d88644a
REPLAY_TREE=9da606f541ecb85248ef00995e8288c1266eea88
REPLAY_PYTHON=/opt/codex/runtimes/codex-primary-runtime/dependencies/python/bin/python3.12
REPLAY_DIRECTORY=/tmp/ai-gpu-b4f42b8a9d4b/governance-current
REPLAY_ORIGINAL=$REPLAY_DIRECTORY/original.zip
REPLAY_DIGEST=5596e541ebf8eb272d813ee353b8e5eb998a641aef7b675f5b014cfd8e2ef045
REPLAY_LENGTH=1414721

resource_observation() {
  /usr/bin/env -i PATH=/usr/bin:/bin LANG=C LC_ALL=C TZ=UTC PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1 \
    "$REPLAY_PYTHON" -B -I -S - "$REPLAY_DIRECTORY" <<'PY'
import datetime, json, os, sys
from pathlib import Path
directory = Path(sys.argv[1])
space = os.statvfs(directory)
memory = {}
for row in Path('/proc/meminfo').read_text().splitlines():
    key, value = row.split(':', 1)
    if key in ('MemAvailable', 'SwapTotal', 'SwapFree'):
        memory[key + '_bytes'] = int(value.split()[0]) * 1024
free = space.f_bavail * space.f_frsize
required = 1073741824 + 33554432
print(json.dumps({
    'observed_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'filesystem': 'tmpfs', 'original_already_acquired': True,
    'reserve_bytes': 1073741824, 'metadata_allowance_bytes': 33554432,
    'required_free_bytes': required, 'free_bytes': free,
    'storage_gate_passed': free >= required,
    'memory_observation': memory,
    'effective_cgroup_memory_capacity_established': False,
    'native_admission_established': False,
}, sort_keys=True, indent=2))
if free < required:
    raise SystemExit(1)
PY
}

identity() {
  /usr/bin/env -i PATH=/usr/bin:/bin LANG=C LC_ALL=C TZ=UTC PYTHONUTF8=1 \
    PYTHONDONTWRITEBYTECODE=1 "$REPLAY_PYTHON" -B -I -S - \
    "$REPLAY_SOURCE" "$REPLAY_REVISION" "$REPLAY_ORIGINAL" <<'PY'
import hashlib, json, sys
from pathlib import Path
r, revision, original = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
sys.path.insert(0, str(r / 'ci/project'))
from governance_replay_source import source_binding
def digest(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()
st = original.lstat()
fields = ('st_dev','st_ino','st_mode','st_nlink','st_size','st_mtime_ns','st_ctime_ns')
readers = sorted((r / 'ci/project').glob('governance_replay*.py'))
readers += [r / 'ci/project/baseline_packet_io.py', Path(sys.executable), Path('/usr/bin/git')]
print(json.dumps({
    'source': source_binding(str(r), revision),
    'original': {'stat': {k:getattr(st,k) for k in fields}, 'sha256':digest(original)},
    'parents': [{'path':str(p),'device':p.lstat().st_dev,'inode':p.lstat().st_ino}
                for p in original.parents],
    'reader_runtime_sha256': {str(p):digest(p) for p in readers},
    'python_version':sys.version,
    'python_resolved_path':str(Path(sys.executable).resolve()),
    'git_resolved_path':str(Path('/usr/bin/git').resolve()),
}, sort_keys=True, indent=2))
PY
}

resource_observation > "$REPLAY_DIRECTORY/resource.before.json"
test "$(/usr/bin/git --no-optional-locks -C "$REPLAY_SOURCE" rev-parse HEAD)" = "$REPLAY_REVISION"
test "$(/usr/bin/git --no-optional-locks -C "$REPLAY_SOURCE" rev-parse 'HEAD^{tree}')" = "$REPLAY_TREE"
test -z "$(/usr/bin/git --no-optional-locks -C "$REPLAY_SOURCE" status --porcelain=v1 --untracked-files=all --ignored)"
test "$(stat -c %s "$REPLAY_ORIGINAL")" -eq "$REPLAY_LENGTH"
test "$(stat -c %a "$REPLAY_ORIGINAL")" = 400
printf '%s  %s\n' "$REPLAY_DIGEST" "$REPLAY_ORIGINAL" | sha256sum -c - > "$REPLAY_DIRECTORY/original.before.sha256.log"
test ! -e "$REPLAY_DIRECTORY/replay.json"
identity > "$REPLAY_DIRECTORY/identity.before.json" 2> "$REPLAY_DIRECTORY/identity.before.stderr.log"
date -u +%Y-%m-%dT%H:%M:%SZ > "$REPLAY_DIRECTORY/replay.start.txt"
cd "$REPLAY_SOURCE"
REPLAY_RC=0
timeout -k 5s 180s /usr/bin/env -i PATH=/usr/bin:/bin LANG=C LC_ALL=C TZ=UTC \
  PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1 "$REPLAY_PYTHON" -B \
  "$REPLAY_SOURCE/ci/project/governance_replay.py" --archive "$REPLAY_ORIGINAL" \
  --expected-revision "$REPLAY_REVISION" --source-dir "$REPLAY_SOURCE" \
  --expected-sha256 "$REPLAY_DIGEST" --output "$REPLAY_DIRECTORY/replay.json" \
  > "$REPLAY_DIRECTORY/replay.stdout.log" 2> "$REPLAY_DIRECTORY/replay.stderr.log" || REPLAY_RC=$?
printf '%s\n' "$REPLAY_RC" > "$REPLAY_DIRECTORY/replay.exit.txt"
date -u +%Y-%m-%dT%H:%M:%SZ > "$REPLAY_DIRECTORY/replay.end.txt"
identity > "$REPLAY_DIRECTORY/identity.after.json" 2> "$REPLAY_DIRECTORY/identity.after.stderr.log"
resource_observation > "$REPLAY_DIRECTORY/resource.after.json"
cmp "$REPLAY_DIRECTORY/identity.before.json" "$REPLAY_DIRECTORY/identity.after.json"
test "$(stat -c %s "$REPLAY_ORIGINAL")" -eq "$REPLAY_LENGTH"
printf '%s  %s\n' "$REPLAY_DIGEST" "$REPLAY_ORIGINAL" | sha256sum -c - > "$REPLAY_DIRECTORY/original.after.sha256.log"
test -z "$(/usr/bin/git --no-optional-locks -C "$REPLAY_SOURCE" status --porcelain=v1 --untracked-files=all --ignored)"
test "$REPLAY_RC" -eq 0
