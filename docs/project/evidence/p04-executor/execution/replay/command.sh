set -euo pipefail
export P04_SOURCE="$(pwd -P)"
export P04_REPLAY="$(python3 -c 'from pathlib import Path; import tempfile; print(Path(tempfile.mkdtemp(prefix="p04-evidence-")).resolve())')"
python3 - <<'PY'
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import zipfile

source = Path(os.environ["P04_SOURCE"]).resolve(strict=True)
replay = Path(os.environ["P04_REPLAY"]).resolve(strict=True)
index = json.loads((source / "docs/project/evidence/p04-executor/archive-index.json").read_text())
assert index["fresh_matrix_archived"]
entries = [entry for entry in index["archives"]
           if entry["disposition"] == "fresh_complete_variant_retained"]
assert sorted(entry["variant"] for entry in entries) == sorted(index["expected_fresh_variants"])
for entry in entries:
    archive_path = source / entry["archive"]["path"]
    body = archive_path.read_bytes()
    assert len(body) == entry["archive"]["size_bytes"]
    assert hashlib.sha256(body).hexdigest() == entry["archive"]["sha256"]
    expected = {member["path"]: member for member in entry["members"]}
    destination = replay / entry["variant"]
    destination.mkdir()
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        assert len(infos) == len(expected) < 1000
        assert sum(info.file_size for info in infos) < 256 * 1024 * 1024
        assert len({info.filename for info in infos}) == len(infos)
        assert {info.filename for info in infos} == set(expected)
        for info in infos:
            path = PurePosixPath(info.filename)
            assert path.parts and not path.is_absolute()
            assert info.filename == path.as_posix()
            assert ".." not in path.parts and "\\" not in info.filename
            assert ":" not in path.parts[0]
            assert stat.S_IFMT(info.external_attr >> 16) in (0, stat.S_IFREG)
            assert info.file_size <= 16 * 1024 * 1024
            data = archive.read(info)
            member = expected[info.filename]
            assert len(data) == member["size_bytes"]
            assert hashlib.sha256(data).hexdigest() == member["sha256"]
            target = destination / info.filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
print(replay)
PY

P04_PACKET_ARGS=(
  --packet "$P04_REPLAY/simx-fp16/model"
  --packet "$P04_REPLAY/simx-bf16/model"
  --packet "$P04_REPLAY/rtlsim-fp16/model"
  --packet "$P04_REPLAY/rtlsim-bf16/model"
)
python3 "$P04_SOURCE/docs/project/evidence/p04-executor/reviews/audit_numerics.py" \
  --fixture "$P04_SOURCE/ci/project/fixtures/p04_tiny_mlp_v1.json" \
  "${P04_PACKET_ARGS[@]}" --output "$P04_REPLAY/numerics.json"
python3 "$P04_SOURCE/docs/project/evidence/p04-executor/reviews/audit_dispatch.py" \
  "${P04_PACKET_ARGS[@]}" --output "$P04_REPLAY/dispatch.json"
python3 "$P04_SOURCE/docs/project/evidence/p04-executor/reviews/audit_provenance.py" \
  --source-dir "$P04_SOURCE" \
  "${P04_PACKET_ARGS[@]}" --output "$P04_REPLAY/provenance.json"
python3 - <<'PY_REPLAY_PATH'
import os,pathlib
pathlib.Path('/workspace/scratch/6ae68c392555/w09a_replay_path.txt').write_text(os.environ['P04_REPLAY']+'\n')
PY_REPLAY_PATH
