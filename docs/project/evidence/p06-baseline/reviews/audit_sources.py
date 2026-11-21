#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Compare the retained P06 baseline source bytes with locally available Git objects.

This offline reader never fetches dependencies or executes archive contents.
Supply the four reviewed dependency Git repositories beneath --vendor-root.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys


REVISION = "84b6ca0ca75fba248ba330642bbf8764db3d459c"
TREE = "6e96c99cc5a26bfacf398cd263b71f1d6ec7aab2"
INDEX_PATH = "docs/project/evidence/p06-baseline/archive-index.json"
READER_PATH = "docs/project/evidence/p05-torch/reviews/archive_reader.py"
READER_SHA256 = "4144becd4fe3c829380f7e66cdb66f7cf073b5e189c2620cd60c62940b9317d3"
ARCHIVES = {
    "fp16": ("aaf54ff60b8f4f889264fb3efa4249cbdb02a7fad2b20124b4ad0ba9ae2f41dc", 3854925),
    "bf16": ("f19f174879e2c1fb120a3328ec919d42b4d67f59ba056ceb6e0b6f5607f4996b", 3855324),
}
FETCHCONTENT = {
    "spdlog": {"tag": "v1.11.0", "revision": "ad0e89cbfb4d0c1ce4d097e134eb7be67baebb36"},
    "yaml-cpp": {"tag": "yaml-cpp-0.7.0", "revision": "0579ae3d976091d7d664aa9d2527e0d0cff25763"},
}
EXPECTED_COUNTS = {
    "main_repository": 786,
    "third_party/ramulator": 50,
    "third_party/softfloat": 7,
    "third_party/ramulator/ext/spdlog": 99,
    "third_party/ramulator/ext/yaml-cpp": 37,
}
LIMITATIONS = [
    "This is retained source-to-Git comparison, not native execution or phase acceptance.",
    "The reviewed archive digests and source revision are explicit inputs pinned in this auditor; GitHub origin is a separate review.",
    "Three nested CVFPU gitlinks are recorded but not independently checked; no retained source body falls under them.",
    "FetchContent tags were resolved during the original review; retained headers match those immutable commits, but historical tag immutability is not established.",
    "Dependency binary construction, toolchain origin and system support files are outside this source-byte comparison.",
    "Every retained body and its inventory is checked; this does not prove the producer retained every possible build input.",
]


class AuditError(ValueError):
    """A retained source identity does not match the reviewed Git provenance."""


def require(condition, message):
    if not condition:
        raise AuditError(message)


def sha256(body):
    return hashlib.sha256(body).hexdigest()


def git(repo, *arguments):
    environment = dict(os.environ, GIT_NO_REPLACE_OBJECTS="1", GIT_OPTIONAL_LOCKS="0")
    result = subprocess.run(["git", "-C", str(repo), *arguments], env=environment,
                            check=False, capture_output=True, timeout=30)
    require(result.returncode == 0, "required local Git object is unavailable: " + " ".join(arguments))
    return result.stdout


def tree(repo, revision, api):
    result = {}
    for item in git(repo, "ls-tree", "-r", "-z", "--full-tree", revision).split(b"\0"):
        if not item:
            continue
        descriptor, raw_name = item.split(b"\t", 1)
        mode, kind, oid = descriptor.decode("ascii").split()
        name = api.relative_name(raw_name.decode("utf-8"))
        require(name not in result, "duplicate Git tree path")
        result[name] = {"mode": mode, "kind": kind, "oid": oid}
    return result


def archive_api():
    root = Path(__file__).resolve().parents[5]
    path = root / READER_PATH
    require(sha256(path.read_bytes()) == READER_SHA256, "trusted archive reader differs from its reviewed pin")
    spec = importlib.util.spec_from_file_location("p06_source_archive_reader", path)
    require(spec is not None and spec.loader is not None, "trusted archive reader is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def audit(repo, vendor_root):
    repo, vendor_root = repo.resolve(strict=True), vendor_root.resolve(strict=True)
    api = archive_api()
    index_body = (repo / INDEX_PATH).read_bytes()
    index = api.strict_json(index_body)
    require(index["schema_version"] == 1 and index["repository"] == "baabi-boo/AI-GPU"
            and index["source_revision"] == REVISION and index["source_tree"] == TREE,
            "archive index differs from the reviewed source identity")
    rows = index["archives"]
    require(type(rows) is list and [row["format"] for row in rows] == list(ARCHIVES),
            "archive index must contain exactly FP16 then BF16")
    source_tree = tree(repo, REVISION, api)
    require(git(repo, "rev-parse", "--verify", REVISION + "^{tree}").decode().strip() == TREE,
            "source Git tree differs")
    gitlinks = {path: entry["oid"] for path, entry in source_tree.items() if entry["kind"] == "commit"}
    require(len(gitlinks) == 5, "unexpected top-level submodule inventory")
    vendor_trees = {}
    for name in ("ramulator", "softfloat"):
        prefix = "third_party/" + name
        vendor_trees[prefix] = tree(vendor_root / name, gitlinks[prefix], api)
    cmake = git(vendor_root / "ramulator", "show", gitlinks["third_party/ramulator"]
                + ":CMakeLists.txt").decode("utf-8")
    for name, identity in FETCHCONTENT.items():
        require(identity["tag"] in cmake, "FetchContent tag is absent from pinned Ramulator source")
        vendor_trees["third_party/ramulator/ext/" + name] = tree(vendor_root / name, identity["revision"], api)

    formats, shared_checks, shared_source, unchecked = {}, None, None, None
    for indexed in rows:
        fmt = indexed["format"]
        expected_digest, expected_size = ARCHIVES[fmt]
        relative_archive = "docs/project/evidence/p06-baseline/archives/simx-" + fmt + ".zip"
        require(indexed["path"] == relative_archive and indexed["sha256"] == expected_digest
                and type(indexed["size_bytes"]) is int and indexed["size_bytes"] == expected_size,
                fmt + ": archive index differs from independently reviewed identity")
        archive_path = repo / relative_archive
        with api.ArchiveReader(archive_path, expected_digest) as archive:
            require(archive.receipt()["archive"]["size_bytes"] == expected_size, fmt + ": ZIP size differs")
            view = archive.view("baseline")
            before = view.read("snapshots/source-before.json")
            require(before == view.read("snapshots/source-after.json"), fmt + ": source changed during execution")
            source = api.strict_json(before)
            checkout = source["checkout"]
            require(checkout["revision"] == REVISION and checkout["tree"] == TREE,
                    fmt + ": recorded source commit or tree differs")
            require(checkout["dirty"] is False and checkout["changed_paths"] == []
                    and checkout["untracked_paths"] == [] and checkout["blockers"] == []
                    and checkout["outcome"] == "pass", fmt + ": source is not clean and qualified")
            require(checkout["submodules"]["errors"] == [], fmt + ": submodule inventory contains errors")
            entries = {row["path"]: row for row in checkout["submodules"]["entries"]}
            require(len(entries) == len(checkout["submodules"]["entries"]), fmt + ": duplicate submodule path")
            for prefix, oid in gitlinks.items():
                require(entries.get(prefix) == {"path": prefix, "revision": oid, "status": "initialized"},
                        fmt + ": top-level gitlink differs: " + prefix)
            nested = {path: entry["revision"] for path, entry in entries.items() if path not in gitlinks}
            require(len(nested) == 3 and all(path.startswith("third_party/cvfpu/") for path in nested),
                    fmt + ": unexpected unverified nested submodule")
            inventory = source["files"]
            require(type(inventory) is list and len(inventory) == sum(EXPECTED_COUNTS.values()),
                    fmt + ": retained source count differs")
            paths = [row["path"] for row in inventory]
            require(paths == sorted(set(paths)), fmt + ": source inventory is not unique and sorted")
            retained = sorted(name[len("artifacts/source/"):] for name in view.files()
                              if name.startswith("artifacts/source/"))
            require(retained == paths, fmt + ": source inventory and retained bodies differ")
            checks, counts = [], dict.fromkeys(EXPECTED_COUNTS, 0)
            for row in inventory:
                api.descriptor(row)
                name = api.relative_name(row["path"])
                body = view.verified(dict(row, path="artifacts/source/" + name))
                if name in source_tree:
                    category, entry, location = "main_repository", source_tree[name], repo
                else:
                    prefixes = [prefix for prefix in vendor_trees if name.startswith(prefix + "/")]
                    require(bool(prefixes), "source is outside supported provenance: " + name)
                    category = max(prefixes, key=len)
                    relative = name[len(category) + 1:]
                    require(relative in vendor_trees[category], "source is missing from dependency Git tree: " + name)
                    entry, location = vendor_trees[category][relative], vendor_root / PurePosixPath(category).name
                require(entry["kind"] == "blob" and entry["mode"] in ("100644", "100755"),
                        "source is not a regular Git blob: " + name)
                original = git(location, "cat-file", "blob", entry["oid"])
                blob_oid = hashlib.sha1(b"blob " + str(len(original)).encode("ascii") + b"\0" + original).hexdigest()
                require(blob_oid == entry["oid"] and body == original, "source differs from immutable Git blob: " + name)
                counts[category] += 1
                checks.append(dict(row, git_blob=entry["oid"], category=category))
            require(counts == EXPECTED_COUNTS, fmt + ": source classification counts differ")
            require(not any(name.startswith(prefix + "/") for name in paths for prefix in nested),
                    fmt + ": retained source exists under an unchecked nested gitlink")
            if shared_checks is None:
                shared_checks, shared_source, unchecked = checks, source, nested
            else:
                require(checks == shared_checks and source == shared_source and nested == unchecked,
                        "format source inventories, identities or content differ")
            formats[fmt] = {"outcome": "pass", "archive_path": relative_archive,
                            "archive_sha256": expected_digest, "archive_size_bytes": expected_size,
                            "source_files_checked": len(checks), "counts": counts}

    return {"schema_version": 1, "scope": "retained-source-to-Git-byte-comparison", "outcome": "pass",
            "native_execution": "not_run", "acceptance_claimed": False, "source_revision": REVISION,
            "source_tree": TREE, "format_source_inventories_identical": True, "formats": formats,
            "source_checks": shared_checks, "top_level_gitlinks_checked": gitlinks,
            "fetchcontent_tag_resolutions": FETCHCONTENT,
            "nested_gitlinks_not_independently_checked": unchecked,
            "archive_index": {"path": INDEX_PATH, "sha256": sha256(index_body)},
            "trusted_archive_reader": {"path": READER_PATH, "sha256": READER_SHA256},
            "auditor": {"path": "docs/project/evidence/p06-baseline/reviews/audit_sources.py",
                        "sha256": sha256(Path(__file__).read_bytes())},
            "limitations": LIMITATIONS}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--vendor-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = audit(args.repo, args.vendor_root)
        with args.output.open("x", encoding="utf-8") as output:
            json.dump(result, output, indent=2, sort_keys=True, allow_nan=False)
            output.write("\n")
        print(json.dumps({"outcome": "pass", "source_revision": REVISION,
                          "formats": {fmt: value["counts"] for fmt, value in result["formats"].items()}}))
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(json.dumps({"outcome": "fail", "reason": str(error),
                          "native_execution": "not_run", "acceptance_claimed": False}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
