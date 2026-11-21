#!/usr/bin/env python3
"""Independently verify the P05-A01 source-retention mapping; no execution claim."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def audit(root):
    base = "bdd3485243f820947df94f7962641d10f2169834"
    tested = "e1420fd550f716df33a2556057b7086a03032cbe"
    original_path = "docs/project/evidence/p05-python/acceptance-binding.json"
    successor_path = "docs/project/evidence/p05-torch/a01-retained-binding.json"
    mapping_path = "docs/project/evidence/p05-torch/a01-source-retention.json"
    git = lambda revision, name: subprocess.check_output(
        ["git", "show", revision + ":" + name], cwd=root)
    original_bytes = git(base, original_path)
    original = json.loads(original_bytes)
    successor = json.loads((root / successor_path).read_bytes())
    mapping = json.loads((root / mapping_path).read_bytes())
    assert (root / original_path).read_bytes() == original_bytes
    assert mapping["source_revision"] == original["source_revision"] == tested
    assert mapping["publication_base"] == base
    assert mapping["execution_claimed"] is False
    assert mapping["acceptance_scope_changed"] is False
    assert mapping["original_record"] == {
        "path": original_path, "sha256": hashlib.sha256(original_bytes).hexdigest()}
    expected = {"python/vortex_ai/_bundle.py", "MANIFEST.in",
                "ci/project/test_p05_packaging.py", "ci/project/test_p05_bundle.py"}
    assert len(mapping["mappings"]) == len(expected)
    assert {row["original_path"] for row in mapping["mappings"]} == expected
    for row in mapping["mappings"]:
        old, retained = row["original_path"], row["retained_path"]
        path = root / retained
        assert path.is_file() and not path.is_symlink()
        data = path.read_bytes()
        assert data == git(base, old) == git(tested, old)
        assert digest(path) == row["sha256"] and len(data) == row["bytes"]
        old_row = next(item for item in original["artifacts"] if item["path"] == old)
        new_row = next(item for item in successor["artifacts"] if item["path"] == retained)
        assert new_row == dict(old_row, path=retained)
    reverse = {row["retained_path"]: row["original_path"] for row in mapping["mappings"]}
    assert [dict(row, path=reverse.get(row["path"], row["path"]))
            for row in successor["artifacts"][:-1]] == original["artifacts"]
    assert successor["artifacts"][-1] == mapping["original_record"]
    allowed = {"artifacts", "record_id", "reviewer", "scope", "limitations"}
    assert set(original) == set(successor)
    assert {key for key in original if original[key] != successor[key]} == allowed
    assert successor["scope"].startswith(original["scope"])
    assert successor["limitations"][:-1] == original["limitations"]
    assert successor["acceptance_ids"] == original["acceptance_ids"] == ["P05-A01"]
    assert successor["outcome"] == original["outcome"] == "pass"
    assert successor["reviewer"] == "/root/w03_a3_history_package (historical source retention only)"
    artifacts = []
    for row in successor["artifacts"]:
        path = root / row["path"]
        assert path.is_file() and not path.is_symlink()
        assert digest(path) == row["sha256"], row["path"]
        artifacts.append(dict(row, size_bytes=path.stat().st_size))
    roadmap = json.loads((root / "docs/project/roadmap.json").read_bytes())
    phase = next(row for row in roadmap["phases"] if row["id"] == "P05")
    gate = next(row for row in phase["evidence"] if row["acceptance_id"] == "P05-A01")
    assert gate["record"] == successor_path
    return {"schema_version": 1, "outcome": "pass",
            "reviewer": "/root/w03_a3_history_package",
            "scope": "historical-source-retention-only",
            "tested_revision": tested, "publication_base": base,
            "original_record_unchanged": True,
            "successor_sha256": digest(root / successor_path),
            "mapping_sha256": digest(root / mapping_path),
            "mappings": mapping["mappings"], "artifacts": artifacts,
            "new_native_execution_claimed": False, "new_acceptance_claimed": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    result = audit(arguments.source_dir.resolve(strict=True))
    arguments.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"outcome": result["outcome"], "mappings": len(result["mappings"]),
                      "artifacts": len(result["artifacts"]),
                      "new_native_execution_claimed": False}))
