#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Safely relocate the two exact P05 archives for independent data-only replay.

This extracts evidence. It executes no packaged extension, binary or simulator.
Run the three sibling audit scripts against the extracted python directories.
"""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys
import zipfile

INDEX_SHA256 = "4295bc5eb96f34e0bf9dfbcea9752b6db493e0eb89669cc097ec0105e33646bd"
ARCHIVES = {
    "simx-fp16": (6417582, "467122e41bee4e67f9eef285e015b2dee3a52522f0bcb3f497e3cec87e6c7380"),
    "simx-bf16": (6417108, "e951f943ece1878f3767180c4ce2b859939722d2d639c1afb37b8a72c76006d8"),
}
REVISION = "e1420fd550f716df33a2556057b7086a03032cbe"
LIMIT = 16 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def plain(path, directory=False):
    require(path.is_absolute() and path.resolve(strict=True) == path,
            "path must be absolute, existing and free of symlinks: " + str(path))
    mode = path.stat().st_mode
    require(stat.S_ISDIR(mode) if directory else stat.S_ISREG(mode), "wrong file type: " + str(path))


def read(path):
    plain(path)
    require(path.stat().st_size <= LIMIT, "oversized input: " + str(path))
    with path.open("rb") as stream:
        body = stream.read(LIMIT + 1)
    require(len(body) <= LIMIT, "oversized input: " + str(path))
    return body


def verified_members(evidence):
    index_bytes = read(evidence / "archive-index.json")
    require(sha(index_bytes) == INDEX_SHA256, "retained archive index changed")
    index = json.loads(index_bytes)
    require(index["source_revision"] == REVISION, "archive source revision differs")
    by_variant = {row["variant"]: row for row in index["archives"]}
    require(set(by_variant) == set(ARCHIVES), "archive inventory differs")
    result = {}
    for variant, (size, digest) in ARCHIVES.items():
        archive = evidence / "archives" / (variant + ".zip")
        raw = read(archive)
        require(len(raw) == size and sha(raw) == digest, "original archive identity differs: " + variant)
        expected = {row["path"]: row for row in by_variant[variant]["members"]}
        members = {}
        with zipfile.ZipFile(io.BytesIO(raw)) as stream:
            infos = stream.infolist()
            require(len(infos) == len(expected) == 304, "archive member count differs")
            require(sum(info.file_size for info in infos) < 128 * 1024 * 1024, "archive expands beyond bound")
            for info in infos:
                name = info.filename
                relative = PurePosixPath(name)
                require(relative.parts and not relative.is_absolute() and str(relative) == name
                        and ".." not in relative.parts and "\\" not in name
                        and not any(ord(c) < 32 or 127 <= ord(c) < 160 for c in name),
                        "unsafe archive member")
                require(name not in members and name in expected, "extra or duplicate archive member")
                require(stat.S_IFMT(info.external_attr >> 16) in (0, stat.S_IFREG)
                        and not info.flag_bits & 1 and 0 <= info.file_size <= LIMIT,
                        "unsupported archive member type or size")
                body = stream.read(info)
                row = expected[name]
                require(len(body) == info.file_size == row["size_bytes"] and sha(body) == row["sha256"],
                        "archive member identity differs: " + name)
                members[name] = body
        require(set(members) == set(expected), "missing archive member")
        result[variant] = members
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    evidence = Path(__file__).resolve().parent.parent
    try:
        require(args.output.is_absolute() and args.output.name not in ("", ".", ".."), "invalid output directory")
        plain(args.output.parent, directory=True)
        require(not os.path.lexists(args.output), "output must be fresh")
        require(not args.output.is_relative_to(evidence), "output must be outside the retained evidence")
        retained = verified_members(evidence)
        args.output.mkdir()
        for variant, members in retained.items():
            for name, body in members.items():
                destination = args.output / variant / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open("xb") as stream:
                    stream.write(body)
        receipt = {"schema_version": 1, "scope": "archive integrity and relocation; no native execution or acceptance",
                   "source_revision": REVISION, "archive_index_sha256": INDEX_SHA256,
                   "archives": {name: {"size_bytes": value[0], "sha256": value[1], "members": len(retained[name])}
                                for name, value in ARCHIVES.items()}, "outcome": "pass"}
        with (args.output / "extraction.json").open("x", encoding="utf-8") as stream:
            json.dump(receipt, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
        print(json.dumps({"outcome": "pass", "receipt": str(args.output / "extraction.json")}, sort_keys=True))
        return 0
    except (ValueError, OSError, KeyError, zipfile.BadZipFile) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
