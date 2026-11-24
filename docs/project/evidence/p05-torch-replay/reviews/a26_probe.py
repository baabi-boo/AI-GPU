#!/usr/bin/env python3
"""A26 bounded lexical-path audit; synthetic data, no original artifacts."""
import builtins
import copy
from contextlib import ExitStack
import dataclasses
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / "AI-GPU"
sys.path.insert(0, str(ROOT / "ci/project"))
import p05_execution_records as records
import p05_replay_installation as install
import p05_replay_native as native
import p05_torch_replay as driver
from test_p05_replay_installation import SyntheticInstallation, encoded
from test_p05_replay_native import MemoryView

SOURCES = (
    "ci/project/p05_execution_records.py", "ci/project/p05_replay_native.py",
    "ci/project/p05_torch_replay.py", "ci/project/p05_replay_installation.py",
    "docs/project/evidence/p05-torch/reviews/archive_reader.py",
)
def hashes():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCES}

before = hashes()
api = driver._archive_api()  # Load only the trusted, pinned local reader before denying I/O.
fixture = SyntheticInstallation()
absolute = {
    "native": lambda p: native._path(p, absolute=True), "driver": driver._absolute,
    "identity": lambda p: records.RetainedIdentity("a" * 64, ((p, "b" * 64, 1),)),
    "shared": api.recorded_absolute,
}
relative = {"native_relative": native._path, "shared_relative": api.relative_name}
distribution = {"distribution": lambda p: install._distribution_path(p, api)}
counts = {"validator_calls": 0, "accepted": 0, "rejected": 0, "io_attempts": 0}
boundaries, environment_results = {}, {}

def check(value, functions, expected=None):
    outcomes = {}
    for name, function in functions.items():
        counts["validator_calls"] += 1
        try:
            result = function(value)
        except (ValueError, TypeError) as error:
            counts["rejected"] += 1
            outcomes[name] = type(error).__name__
            if expected is not None:
                assert expected is False, (name, repr(value), error)
        else:
            counts["accepted"] += 1
            outcomes[name] = "accept"
            if expected is not None:
                assert expected is not False, (name, repr(value), result)
                if isinstance(expected, str):
                    assert str(result) == expected, (value, result, expected)
    return outcomes

def deny(*args, **kwargs):
    counts["io_attempts"] += 1
    raise AssertionError("filesystem/process access during lexical audit")

def environment(variant):
    files = copy.deepcopy(fixture.files)
    view = MemoryView(files).subview("torch")
    if variant != "baseline":
        key = "torch/logs/framework-environment-before.log"
        raw = json.loads(files[key].split(b" ", 1)[1])
        names = raw["distributions"]["torch"]["files"]
        if variant == "duplicate_alias":
            names.append("../../../bin/../bin/torchrun")
        else:
            names[names.index("../../../bin/torchrun")] = "../../../../bin/torchrun"
        names.sort()
        files[key] = b"P05_TORCH_ENVIRONMENT " + encoded(raw) + b"\n"
    observed = fixture.snapshot_value("torch", fixture.tr, "framework_before")
    inventory = {row["path"]: row for row in fixture.snapshot_value("torch", fixture.tr, "installed_before")}
    seed = {row["path"]: row for row in fixture.snapshot_value("torch", fixture.tr, "venv_seed")}
    versions = {name: item["version"] for name, item in observed["distributions"].items()}
    try:
        install._environments(view, fixture.tr, inventory, seed, versions,
                              PurePosixPath(observed["prefix"]), observed["base_prefix"], api)
    except ValueError as error:
        assert variant != "baseline", error
        expected = "aliases" if variant == "duplicate_alias" else "escapes"
        assert expected in str(error), error
        return str(error)
    assert variant == "baseline"
    return "accept"

with ExitStack() as guards:
    for owner, names in ((builtins, ("open",)), (io, ("open",)),
                         (Path, ("open", "resolve", "stat", "lstat", "readlink")),
                         (subprocess, ("Popen",)),
                         (os, ("open", "stat", "lstat", "scandir", "listdir", "system", "fork",
                               "forkpty", "posix_spawn", "posix_spawnp", "execve", "execv", "spawnv"))):
        for name in names:
            if hasattr(owner, name):
                guards.enter_context(patch.object(owner, name, deny))
    check("/producer/venv/bin/python", absolute, True)
    check("/producer/café/λ", absolute, True)
    for value in ("", ".", "..", "C:/x", "C:x", "C:\\x", "\\\\server\\share",
                  "//server/share", "/a//b", "/a/./b", "/a/../b", "/a/", "/a\\b"):
        check(value, absolute, False)
    for codepoint in (*range(32), *range(127, 160)):
        check("/a" + chr(codepoint) + "b", absolute, False)
        check("a" + chr(codepoint) + "b", {**relative, **distribution}, False)
    for label, value in {
        "root": "/", "utf8_4096": "/" + "é" * 2047 + "a",
        "utf8_4097": "/" + "é" * 2048, "utf8_4098": "/" + "é" * 2048 + "a",
        "components_63": "/" + "/".join(["a"] * 63),
        "components_64": "/" + "/".join(["a"] * 64),
        "components_65": "/" + "/".join(["a"] * 65),
        "surrogate": "/a\ud800", "drive_component": "/C:/file",
    }.items():
        boundaries[label] = check(value, absolute)
    for value in ("normal/path", "café/λ", "é" * 2048, "/".join(["a"] * 64)):
        check(value, relative, True)
    for value in ("./x", "x//y", "x/../y", "x/", "C:/x", "C:x", "\\\\s\\x",
                  "/absolute", "é" * 2048 + "a", "/".join(["a"] * 65)):
        check(value, relative, False)
    for name, result in {
        "../../../bin/torchrun": "bin/torchrun", "../../../bin/f2py": "bin/f2py",
        "../../../share/man/man1/isympy.1": "share/man/man1/isympy.1",
        "../../../bin/../bin/torchrun": "bin/torchrun",
        "torch/../torch/__init__.py": install.SITE + "torch/__init__.py",
        "../../python3.12/site-packages/torch/__init__.py": install.SITE + "torch/__init__.py",
    }.items():
        check(name, distribution, result)
    for value in ("../../../../bin/torchrun", "../../../bin/../../bin/torchrun", "../../..",
                  "../../../bin/..", "../../../bin/", "../../../bin//torchrun", "C:/x", "torch\\file"):
        check(value, distribution, False)
    tail = "a" * (4096 - len(install.SITE.encode()))
    for value, expected in ((tail, True), (tail + "a", False),
                            ("/".join(["a"] * 61), True), ("/".join(["a"] * 62), False),
                            ("/".join([".."] * 3 + ["a"] * 61), True),
                            ("/".join([".."] * 3 + ["a"] * 62), False)):
        check(value, distribution, expected)
    identity = records.RetainedIdentity("a" * 64, (("/producer/file", "b" * 64, 1),))
    for action in (lambda: setattr(identity, "request_sha256", "c" * 64),
                   lambda: identity.installed_files.__setitem__(0, ("/other", "b" * 64, 1))):
        try:
            action()
        except (dataclasses.FrozenInstanceError, AttributeError):
            pass
        else:
            raise AssertionError("retained identity unexpectedly mutable")
    for variant in ("baseline", "duplicate_alias", "fourth_parent"):
        environment_results[variant] = environment(variant)

after = hashes()
assert before == after, "source changed during probe"
assert counts["io_attempts"] == 0
print(json.dumps({"scope": "synthetic host-only lexical audit", "counts": counts,
                  "boundaries": boundaries, "environments": environment_results,
                  "immutable_checks": 2, "source_sha256": before,
                  "source_unchanged": before == after}, sort_keys=True, indent=2))
