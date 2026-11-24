"""A22 synthetic nested-archive probes; never extract or execute members.

Run from AI-GPU: python3 -B ../agent-notes/a22_probe.py
The main() check routes only the top-level replay seam to a real synthetic
installation verifier; it is an error-boundary check, not full CLI replay.
"""

import contextlib
import gzip
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
from unittest.mock import patch
import warnings
import zipfile

ROOT = Path(__file__).resolve().parents[1] / "AI-GPU"
sys.path.insert(0, str(ROOT / "ci/project"))
import p05_replay_installation as installation
import p05_torch_replay as driver
from p06_replay import _archive_api
from test_p05_replay_installation import SyntheticInstallation, record, source_archive, wheel_bytes


def sparse_archive(*, later=False):
    item = tarfile.TarInfo("vortex_ai-0.1.0/setup.py")
    item.type = tarfile.GNUTYPE_SPARSE
    header = bytearray(item.tobuf(format=tarfile.GNU_FORMAT))
    header[482] = 1  # An extension block is promised but absent.
    header[148:156] = b"        "
    header[148:156] = ("%06o\0 " % sum(header)).encode("ascii")
    prefix = b""
    if later:
        earlier = tarfile.TarInfo("vortex_ai-0.1.0/earlier.txt")
        earlier.size = 1
        prefix = earlier.tobuf(format=tarfile.GNU_FORMAT) + b"x" + b"\0" * 511
    return gzip.compress(prefix + bytes(header), mtime=0)


def fixture_with_sdist(raw):
    fixture = SyntheticInstallation()
    for index, row in enumerate(fixture.pr["packages"]):
        if row["path"].endswith(".tar.gz"):
            fixture.files["python/" + row["path"]] = raw
            fixture.pr["packages"][index] = record(row["path"], raw)
            return fixture
    raise AssertionError("synthetic sdist is missing")


def outcome(name, operation):
    try:
        value = operation()
        print(json.dumps({"case": name, "result": "accepted", "value": value}, sort_keys=True))
    except Exception as error:
        print(json.dumps({"case": name, "result": type(error).__name__, "reason": str(error)}, sort_keys=True))


def cli_boundary(fixture):
    output = io.StringIO()
    try:
        with patch.object(driver, "replay_archive", side_effect=lambda *args, **kwargs: fixture.run()), \
                contextlib.redirect_stdout(output):
            status = driver.main(["--archive", "/unused-synthetic.zip", "--sha256", "0" * 64,
                                  "--expected-revision", "a" * 40, "--format", "fp16"])
    except Exception as error:
        return {"escaped": type(error).__name__, "stdout_bytes": len(output.getvalue())}
    return {"status": status, "json": json.loads(output.getvalue())}


def main():
    for name in ("ci/project/p05_replay_installation.py", "ci/project/p05_torch_replay.py",
                 "docs/project/evidence/p05-torch/reviews/archive_reader.py"):
        print(json.dumps({"source": name, "sha256": hashlib.sha256((ROOT / name).read_bytes()).hexdigest()}))
    fixture, api = SyntheticInstallation(), _archive_api()
    valid_wheel = wheel_bytes(fixture.wheel_members)
    valid_sdist = source_archive({"setup.py": b"inert"})
    outcome("valid_wheel", lambda: len(installation._wheel_members(valid_wheel, fixture.manifest, api)[0]))
    outcome("valid_sdist", lambda: sorted(installation._sdist_members(valid_sdist, api)))
    outcome("valid_installation", lambda: fixture.run()["summary"]["scope"])
    for label, compression, duplicate in (("duplicate_wheel_name", zipfile.ZIP_DEFLATED, True),
                                           ("unsupported_bzip2_wheel", zipfile.ZIP_BZIP2, False)):
        stream = io.BytesIO()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(stream, "w", compression=compression) as archive:
                rows = list(fixture.wheel_members.items())
                for index, (name, raw) in enumerate(rows):
                    archive.writestr(rows[0][0] if duplicate and index == 1 else name, raw)
        outcome(label, lambda raw=stream.getvalue(): len(installation._wheel_members(raw, fixture.manifest, api)[0]))
    mismatched = bytearray(valid_wheel)
    mismatched[30] = ord("x")  # Local header name disagrees with central directory.
    outcome("wheel_local_central_name_mismatch",
            lambda: len(installation._wheel_members(bytes(mismatched), fixture.manifest, api)[0]))
    for label, raw in (("truncated_gzip", valid_sdist[:-8]), ("gzip_trailing_junk", valid_sdist + b"junk"),
                       ("concatenated_tar_streams", valid_sdist + source_archive({"hidden.txt": b"inert"})),
                       ("truncated_sparse_first", sparse_archive()), ("truncated_sparse_later", sparse_archive(later=True))):
        outcome(label, lambda raw=raw: sorted(installation._sdist_members(raw, api)))
    malformed = fixture_with_sdist(sparse_archive())
    outcome("real_installation_verifier_sparse", lambda: malformed.run()["summary"]["scope"])
    outcome("cli_error_boundary_sparse", lambda: cli_boundary(malformed))


if __name__ == "__main__":
    main()
