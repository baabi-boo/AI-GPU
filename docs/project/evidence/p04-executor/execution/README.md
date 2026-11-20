# Retained native model execution packets

Each variant directory contains the original, unmodified GitHub artifact ZIP,
its downloaded artifact metadata, and the final completed hosted job record.
The [archive index](../archive-index.json) binds ZIP bytes, every retained member,
the final model report, configuration stamp, source revision and hosted job.
The qualification source is `c9d139cc9f84839b6a56b6228dd304460cbfe45c`, from
[native workflow run 44762622060](https://github.com/baabi-boo/AI-GPU/actions/runs/44762622060).
The index declares whether all four fresh variants have been archived; archive
integrity alone does not make a phase-acceptance decision.

## Replay the retained evidence

Run these commands from a repository checkout containing this packet and the
exact qualification commit's Git objects. Python 3 and Git are sufficient for
the retained-data audits; they do not compile or execute the native model.
The extraction directory and packet arguments must be canonical absolute paths.
Literal `..` and symlink aliases are rejected by the auditors.

The first command verifies each original ZIP and every member against the index,
then extracts the four fresh packets outside the checkout. It stops if the index
does not yet contain the complete fresh matrix.

```bash
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
```

Run all three independent auditors over the same four extracted packets. Each
output path must be fresh; an existing receipt is not overwritten.

```bash
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
```

The original ZIP and report hashes remain identical after relocation. Audit
receipts record local extraction paths, so their own bytes can differ across
machines. Compare the bound original hashes, exact observation counts and audit
outcomes instead of expecting a relocated receipt to have an identical digest.
For a deliberate selected-variant check, supply that one packet and the explicit
`--selected-scope` flag; that result does not cover the full matrix.

## Interpretation and limits

The original `job.json` records initial workflow identity, including
`native_execution: "not_run"`. The preparation receipt uses the same initial
execution boundary. Preserve those original bodies. Final execution is recorded
by the finished `model/report.json`, its bound raw command logs and the separate
successful `final-job.json`; the initial field is not the final job verdict.

The four earlier `f4c6a3` packets remain in
[failed-attempts](../failed-attempts/f4c6a3-simx-fp16/retention-failure.json), with
all original ZIPs indexed separately. They completed numerical execution but
omitted required `.config.stamp` bodies during artifact upload. Their originals
remain incomplete; no missing body has been reconstructed, and their runs are
excluded from the fresh qualification totals.

This packet retains raw command logs, selected source/helper bodies, generated
configuration and source/tool/dependency inventories. Native binaries, complete
external submodule bodies, the toolchain, system headers and dynamic libraries
are identified where recorded, but their complete bodies are not archived here.
Retained-data audit replay therefore differs from native re-execution. The latter
requires the exact source and pinned external prerequisites, the trusted runner
and its stated build/run resource bounds.

Native processor RTL bypasses the AFU; these packets do not establish vendor
`hw_emu`, physical FPGA, silicon or physical performance results. Event and host
timings use host steady clocks, and overlapping intervals must not be summed as
disjoint cost. P01-A03 and later hardware obligations remain separate.
