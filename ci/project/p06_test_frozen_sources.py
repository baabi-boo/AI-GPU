# SPDX-License-Identifier: Apache-2.0
"""Read original P06 source bytes as test data, never as executable helpers.

The accepted ZIP's complete identity is pinned before opening it. Each requested
source member is then checked against its retained descriptor; all 46 execution
pins are checked before any bytes are returned. Only explicit paths are written
to caller-owned temporary fixtures. Production native execution does not use
this module or substitute these bytes for the source it builds.
"""

from functools import lru_cache
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
from types import MappingProxyType
import zipfile

import p06_contract


ROOT = Path(__file__).resolve().parents[2]
ARCHIVE_PATH = "docs/project/evidence/p06-baseline/archives/simx-fp16.zip"
ARCHIVE_SHA256 = "aaf54ff60b8f4f889264fb3efa4249cbdb02a7fad2b20124b4ad0ba9ae2f41dc"
ARCHIVE_SIZE = 3854925
SOURCE_REVISION = "84b6ca0ca75fba248ba330642bbf8764db3d459c"
SOURCE_TREE = "6e96c99cc5a26bfacf398cd263b71f1d6ec7aab2"


def _relative(path):
    if (type(path) is not str or not path or "\\" in path
            or PurePosixPath(path).is_absolute()
            or any(part in ("", ".", "..") for part in path.split("/"))):
        raise ValueError("invalid frozen test source path")
    return path


@lru_cache(maxsize=1)
def _sources():
    body = p06_contract._read_file(ROOT / ARCHIVE_PATH, ARCHIVE_SIZE)
    if len(body) != ARCHIVE_SIZE or hashlib.sha256(body).hexdigest() != ARCHIVE_SHA256:
        raise ValueError("accepted test archive differs from its original identity")
    sources = {}
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        snapshot = json.loads(archive.read("baseline/snapshots/source-before.json"))
        checkout = snapshot["checkout"]
        if (checkout["revision"] != SOURCE_REVISION or checkout["tree"] != SOURCE_TREE
                or checkout["dirty"] is not False):
            raise ValueError("accepted test archive source identity differs")
        for row in snapshot["files"]:
            path = _relative(row["path"])
            if path in sources:
                raise ValueError("duplicate frozen test source")
            member = archive.read("baseline/artifacts/source/" + path)
            if (len(member) != row["size_bytes"]
                    or hashlib.sha256(member).hexdigest() != row["sha256"]):
                raise ValueError("retained test source differs: " + path)
            sources[path] = member
    contract = p06_contract.expected_contract()
    for row in contract["source_inputs"]:
        if hashlib.sha256(sources[row["path"]]).hexdigest() != row["sha256"]:
            raise ValueError("frozen execution pin differs in test archive: " + row["path"])
    if p06_contract.decode_contract(sources[p06_contract.MANIFEST_PATH]) != contract:
        raise ValueError("original test manifest differs")
    return MappingProxyType(sources)


def frozen_source_paths():
    """Return the immutable original retained-source inventory."""
    return tuple(_sources())


def frozen_source_bytes(path):
    """Return one verified original source body as immutable data."""
    return _sources()[_relative(path)]


def stage_frozen_sources(destination, paths):
    """Write explicitly selected original data into a temporary test fixture."""
    destination = Path(destination)
    for path in sorted(set(paths)):
        path = _relative(path)
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(frozen_source_bytes(path))
