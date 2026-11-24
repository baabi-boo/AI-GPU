#!/usr/bin/env python3
"""Read original P05 data and join repository sources to exact Git blobs."""
from __future__ import annotations

import base64
from collections import Counter, defaultdict
import csv
import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tarfile
import zipfile

sys.dont_write_bytecode = True
BASE = Path(__file__).resolve().parents[1]
ROOT = BASE / "AI-GPU"
READER = "docs/project/evidence/p05-torch/reviews/archive_reader.py"
READER_SHA = "4144becd4fe3c829380f7e66cdb66f7cf073b5e189c2620cd60c62940b9317d3"
REVIEWED_READER_REVISION = "d8abc24d2fd5dab5ceddbae3627e3d3eb9750358"
REVISIONS = ("c0b44ce64665fe11895f869eea8c38c9b820d6f7", "c6fb039e706e812b6b3f4d2a5db1828076fe50df")
SOURCE_ROOT = "/home/runner/work/AI-GPU/AI-GPU/"
SITE = "lib/python3.12/site-packages/"
HOST_TEST = "ci/project/p05_torch_native_host_tests.py"
HELPERS = {"p05_installed_check.py", "p05_torch_installed_check.py", "p05_torch_records.py", "p05_torch_contract.json"}
SCALARS = {
    "workflow_sha256": ".github/workflows/p05-torch.yml",
    "test_sha256": HOST_TEST,
    "adapter_sha256": "python/vortex_ai/torch_ops.py",
    "contract_sha256": "ci/project/p05_torch_contract.json",
    "fixture_sha256": "ci/project/fixtures/p04_tiny_mlp_v1.json",
    "profile_sha256": "profiles/p02-tfr.json",
}
MAX_NESTED = 64 * 1024**2
SHA = re.compile(r"[a-f0-9]{64}\Z")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def git(*args, data=None):
    return subprocess.run(["git", "--no-optional-locks", *args], cwd=ROOT, input=data,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout


def tree(revision):
    files, links = {}, {}
    for row in git("ls-tree", "-rz", revision).split(b"\0"):
        if row:
            header, path = row.split(b"\t", 1)
            mode, kind, oid = header.decode().split()
            (files if kind == "blob" else links)[path.decode()] = oid
    return files, links


GIT_BODIES = {}


def batch_blobs(oids):
    missing = sorted(set(oids) - set(GIT_BODIES))
    if not missing:
        return
    raw = git("cat-file", "--batch", data=("\n".join(missing) + "\n").encode())
    offset = 0
    for oid in missing:
        end = raw.index(b"\n", offset)
        header = raw[offset:end].decode().split()
        assert header[:2] == [oid, "blob"], header
        size = int(header[2])
        body = raw[end + 1:end + 1 + size]
        offset = end + 2 + size
        assert len(body) == size and raw[offset - 1:offset] == b"\n"
        assert hashlib.sha1(b"blob " + str(size).encode() + b"\0" + body).hexdigest() == oid
        GIT_BODIES[oid] = body
    assert offset == len(raw)


def package_source(name):
    if SITE in name:
        name = name.split(SITE, 1)[1]
    if name.startswith("vortex_ai/") and name.endswith(".py"):
        return "python/" + name
    if name == "vortex_ai-0.1.0.dist-info/licenses/LICENSE":
        return "LICENSE"
    return None


def outer_source(name):
    if "/artifacts/source/" in name:
        return name.split("/artifacts/source/", 1)[1], "artifacts_source"
    if name in ("workflow.yml", "p05_torch_contract.json", "p05_torch_requirements.lock"):
        return ({"workflow.yml": ".github/workflows/p05-torch.yml"}.get(name, "ci/project/" + name), "workflow_or_contract")
    if name == "torch-native-host/test.snapshot.py":
        return HOST_TEST, "supplementary_host_snapshot"
    if name.startswith("torch-native-host/runtime/python/") and name.endswith(".py"):
        return "python/" + name.removeprefix("torch-native-host/runtime/python/"), "supplementary_host_python"
    if name.startswith("torch/artifacts/checker/"):
        return "ci/project/" + name.rsplit("/", 1)[-1], "installed_checker"
    if "/artifacts/installed/" in name:
        source = package_source(name.split("/artifacts/installed/", 1)[1])
        if source:
            return source, "installed_python_source_or_license"
    match = re.fullmatch(r".+/artifacts/(?:simx-(?:fp16|bf16)|native-matmul)/(tests/regression/(?:ai_mlp|ai_matmul)/Makefile)", name)
    if match:
        return match[1], "copied_build_makefile"
    return None


def non_source_class(name):
    if name.endswith((".whl", ".tar.gz")):
        return "nested_package_container"
    if "/runtime/generated/" in name or "/children/" in name and name.endswith("launcher.py"):
        return "generated_host_source_or_configuration"
    if "/artifacts/sdist-pin/" in name or name.startswith("python/p05_build/"):
        return "generated_sdist_pins"
    if ".dist-info/" in name or ".egg-info/" in name or name.endswith("PKG-INFO"):
        return "generated_package_metadata"
    if name.endswith((".so", ".a", ".elf", ".vxbin")) or name.endswith(("/ai_mlp", "/ai_matmul")):
        return "compiled_or_binary_artifact"
    if "/artifacts/" in name and name.endswith((".h", ".vh", ".vlt", ".mk", ".stamp")):
        return "generated_build_configuration"
    if name.endswith(".json"):
        return "json_evidence_or_manifest"
    if name.endswith(".log"):
        return "execution_or_build_log"
    return "other_data"


def nested_members(name, raw, api):
    result = {}
    if name.endswith(".whl"):
        with zipfile.ZipFile(io.BytesIO(raw), "r") as archive:
            members = archive.infolist()
            assert len(members) <= 1024 and sum(x.file_size for x in members) <= MAX_NESTED
            for item in members:
                path = api.relative_name(item.filename)
                assert item.orig_filename == path and path not in result and not item.is_dir()
                assert stat.S_IFMT(item.external_attr >> 16) in (0, stat.S_IFREG)
                assert not item.flag_bits & 1 and item.file_size <= MAX_NESTED
                with archive.open(item, "r") as stream:
                    body = stream.read(item.file_size + 1)
                assert len(body) == item.file_size
                result[path] = body
    else:
        with gzip.GzipFile(fileobj=io.BytesIO(raw), mode="rb") as stream:
            unpacked = stream.read(MAX_NESTED + 1)
        assert len(unpacked) <= MAX_NESTED
        with tarfile.open(fileobj=io.BytesIO(unpacked), mode="r:") as archive:
            entries = archive.getmembers()
            assert len(entries) <= 1024
            seen = set()
            for item in entries:
                full = api.relative_name(item.name.rstrip("/"))
                assert full not in seen
                seen.add(full)
                assert full == "vortex_ai-0.1.0" or full.startswith("vortex_ai-0.1.0/")
                assert item.isdir() or item.isfile()
                if item.isfile():
                    path = full.split("/", 1)[1]
                    assert path not in result and item.size <= MAX_NESTED
                    body = unpacked[item.offset_data:item.offset_data + item.size]
                    assert len(body) == item.size
                    result[path] = body
    return result


def artifact_probe(path, expected_sha, revision, fmt, api, tree_files, links):
    byte_rows, receipt_rows, mismatches = [], [], []
    byte_raw = {}
    source_snapshots = []
    unknown_submodule_rows = []
    tool_rows = []
    aggregate_rows = []
    aggregate_references = []
    revision_references = []
    classes, nested_classes = Counter(), Counter()
    generated_names, nested_summary = [], []
    log_unparsed = []
    parsed_json_files = []
    json_rows = {}
    git_tree = git("rev-parse", revision + "^{tree}").decode().strip()

    def record_byte(source, body, locator, category):
        api.relative_name(source)
        byte_rows.append({"source": source, "locator": locator, "category": category,
                          "sha256": digest(body), "size_bytes": len(body)})
        byte_raw[locator] = body

    def source_path(value, locator):
        if not isinstance(value, str):
            return None
        candidate = None
        if value.startswith(SOURCE_ROOT):
            candidate = value[len(SOURCE_ROOT):]
        elif "artifacts/source/" in value:
            candidate = value.split("artifacts/source/", 1)[1]
        elif value in tree_files:
            candidate = value
        elif value.startswith(tuple(root + "/" for root in links)) and (
                re.search(r"snapshots/source-(before|after)\.json/files/", locator)
                or any(token in locator for token in ("/binding_sources/", "/source_files/"))):
            candidate = value
        elif (source := package_source(value)):
            candidate = source
        elif "/artifacts/installed/" in value:
            candidate = package_source(value.split("/artifacts/installed/", 1)[1])
        elif "/checker/" in value and value.rsplit("/", 1)[-1] in HELPERS:
            candidate = "ci/project/" + value.rsplit("/", 1)[-1]
        elif "installed-helpers" in locator and value in HELPERS:
            candidate = "ci/project/" + value
        if candidate:
            api.relative_name(candidate)
        return candidate

    def add_receipt(source, sha, size, locator, category):
        row = {"source": source, "sha256": sha, "size_bytes": size, "locator": locator, "category": category}
        if source in tree_files:
            receipt_rows.append(row)
        elif any(source.startswith(root + "/") for root in links):
            unknown_submodule_rows.append(row)
        else:
            mismatches.append({"kind": "source_receipt_has_no_commit_blob", **row})

    def walk(value, locator):
        if type(value) is dict:
            if type(value.get("path")) is str and type(value.get("sha256")) is str and SHA.fullmatch(value["sha256"]):
                source = source_path(value["path"], locator)
                size = value.get("size_bytes", value.get("size"))
                if source:
                    add_receipt(source, value["sha256"], size, locator, "json_path_receipt")
                elif "resolved_path" in value:
                    tool_rows.append({"path": value["path"], "sha256": value["sha256"], "size_bytes": size})
            for field, source in SCALARS.items():
                if field in value:
                    add_receipt(source, value[field], None, locator + "/" + field, "scalar_source_pin")
            for field in ("binding_source_sha256", "source_sha256"):
                if field in value:
                    aggregate_references.append({"locator": locator + "/" + field, "sha256": value[field],
                        "kind": "host" if locator.startswith("torch-native-host/") else "production"})
            for field, expected in (("source_revision", revision), ("source_tree", git_tree), ("GITHUB_SHA", revision)):
                if field in value:
                    revision_references.append({"locator": locator + "/" + field, "matches": value[field] == expected})
                    if value[field] != expected:
                        mismatches.append({"kind": "execution_revision_or_tree_mismatch", "locator": locator + "/" + field,
                                           "observed": value[field], "expected": expected})
            if "revision" in value and "tree" in value and "dirty" in value:
                matched = value["revision"] == revision and value["tree"] == git_tree
                revision_references.append({"locator": locator, "matches": matched})
                if not matched:
                    mismatches.append({"kind": "checkout_revision_or_tree_mismatch", "locator": locator})
            if type(value.get("binding_sources")) is list:
                field = "binding_source_sha256" if "binding_source_sha256" in value else "source_sha256"
                if field in value:
                    expected = digest(canonical(value["binding_sources"]) + b"\n")
                    aggregate_rows.append({"locator": locator + "/" + field, "sha256": value[field], "matches": expected == value[field],
                        "kind": "host" if locator.startswith("torch-native-host/") else "production"})
                    if expected != value[field]:
                        mismatches.append({"kind": "source_inventory_aggregate", "locator": locator})
            for key, child in value.items():
                walk(child, locator + "/" + key)
        elif type(value) is list:
            for index, child in enumerate(value):
                walk(child, locator + "/" + str(index))

    def record_csv(raw, locator):
        for index, row in enumerate(csv.reader(io.StringIO(raw.decode("utf-8"), newline=""))):
            assert len(row) == 3
            source = package_source(row[0])
            if source:
                assert row[1].startswith("sha256=")
                sha = base64.urlsafe_b64decode(row[1][7:] + "=" * (-len(row[1][7:]) % 4)).hex()
                add_receipt(source, sha, int(row[2]), locator + "/row/" + str(index), "package_record_csv")

    with api.ArchiveReader(path, expected_sha) as archive:
        for name in archive.files():
            mapped = outer_source(name)
            category = mapped[1] if mapped else non_source_class(name)
            classes[category] += 1
            if category.startswith("generated_"):
                generated_names.append(name)
            relevant = mapped or name.endswith((".json", ".whl", ".tar.gz", ".log", "/RECORD")) or category.startswith("generated_")
            if not relevant:
                continue
            raw = archive.read(name, limit=api.MEMBER_BYTES)
            if mapped:
                record_byte(mapped[0], raw, name, mapped[1])
            if name.endswith(".json"):
                value = api.strict_json(raw)
                parsed_json_files.append(name)
                walk(value, name)
                if name in ("torch/snapshots/installed-before.json", "torch/snapshots/installed-after.json", "torch/snapshots/framework-wheel-payload.json", "torch/snapshots/venv-seed.json", "p05_torch_contract.json"):
                    json_rows[name] = value
                if name.endswith(("snapshots/source-before.json", "snapshots/source-after.json")):
                    checkout = value["checkout"]
                    assert checkout["revision"] == revision and checkout["tree"] == git_tree
                    assert checkout["dirty"] is False and not checkout["changed_paths"] and not checkout["untracked_paths"]
                    module_index = {row["path"]: row["revision"] for row in checkout["submodules"]["entries"]}
                    assert all(module_index[root] == oid for root, oid in links.items())
                    paths = [row["path"] for row in value["files"]]
                    source_snapshots.append({"member": name, "rows": len(paths),
                        "first_party_commit_paths": sum(p in tree_files and not p.startswith("third_party/") for p in paths),
                        "tracked_third_party_commit_paths": sum(p in tree_files and p.startswith("third_party/") for p in paths),
                        "unavailable_submodule_paths": sum(p not in tree_files for p in paths),
                        "superrepo_gitlinks_matched": len(links),
                        "nested_gitlink_receipts_not_compared": sorted(set(module_index) - set(links))})
                if name == "job.json":
                    assert value["GITHUB_SHA"] == revision and value["P05_FORMAT"] == fmt
            if name.endswith("/RECORD"):
                record_csv(raw, name)
            if name.endswith(".log"):
                for number, line in enumerate(raw.decode("utf-8", errors="replace").splitlines(), 1):
                    if "sha256" not in line:
                        continue
                    start = line.find("{")
                    if start < 0:
                        log_unparsed.append({"member": name, "line": number, "text": line[:240]})
                        continue
                    try:
                        value = api.strict_json(line[start:].encode())
                    except api.ArchiveError:
                        log_unparsed.append({"member": name, "line": number, "text": line[:240]})
                        continue
                    walk(value, name + "/line/" + str(number))
            if name.endswith((".whl", ".tar.gz")):
                members = nested_members(name, raw, api)
                package_counts = Counter()
                for child, body in members.items():
                    source = package_source(child) if name.endswith(".whl") else child if child in tree_files else None
                    locator = name + "!" + child
                    kind = "wheel_first_party_source_or_license" if name.endswith(".whl") else "sdist_source"
                    if source:
                        record_byte(source, body, locator, kind)
                        package_counts[kind] += 1
                    else:
                        child_kind = non_source_class(child)
                        nested_classes[child_kind] += 1
                        package_counts[child_kind] += 1
                    if child.endswith(".json"):
                        walk(api.strict_json(body), locator)
                    if child.endswith("/RECORD"):
                        record_csv(body, locator)
                nested_summary.append({"container": name, "members": len(members), "categories": dict(package_counts)})
        read_receipt = archive.receipt()
    # Reaching this statement means ArchiveReader.__exit__ completed close-time rehash.
    source_paths = {row["source"] for row in byte_rows + receipt_rows}
    absent_git_paths = source_paths - set(tree_files)
    assert not absent_git_paths, sorted(absent_git_paths)
    batch_blobs(tree_files[p] for p in source_paths)
    for row in byte_rows + receipt_rows:
        body = GIT_BODIES[tree_files[row["source"]]]
        matches = row["sha256"] == digest(body) and (row["size_bytes"] is None or row["size_bytes"] == len(body))
        if row["locator"] in byte_raw:
            matches = matches and byte_raw[row["locator"]] == body
        if not matches:
            mismatches.append({"kind": "git_blob_mismatch", **row, "git_sha256": digest(body), "git_size_bytes": len(body)})
    for row in aggregate_references:
        expected = {a["sha256"] for a in aggregate_rows if a["kind"] == row["kind"]}
        assert len(expected) == 1
        if row["sha256"] not in expected:
            mismatches.append({"kind": "source_inventory_pin_reference_mismatch", **row})
    by_source = {}
    for source in sorted(source_paths):
        br = [row for row in byte_rows if row["source"] == source]
        rr = [row for row in receipt_rows if row["source"] == source]
        body = GIT_BODIES[tree_files[source]]
        by_source[source] = {"git_blob": tree_files[source], "sha256": digest(body), "size_bytes": len(body),
            "retained_byte_copies": len(br), "source_receipt_occurrences": len(rr),
            "retained_copy_categories": dict(Counter(row["category"] for row in br))}
    byte_set = {r["source"] for r in byte_rows}
    receipt_set = {r["source"] for r in receipt_rows}
    first_party = {p for p in source_paths if not p.startswith("third_party/")}
    source_member_set = {r["source"] for r in byte_rows if r["category"] == "artifacts_source"}
    installed = json_rows["torch/snapshots/installed-before.json"]
    payload = json_rows["torch/snapshots/framework-wheel-payload.json"]
    seed = json_rows["torch/snapshots/venv-seed.json"]
    absent_tools = {canonical(row) for row in tool_rows}
    report = {
        "archive": {"filename": path.name, "sha256": expected_sha, "size_bytes": path.stat().st_size},
        "execution_revision": revision, "execution_tree": git_tree, "format": fmt,
        "outcome": "pass" if not mismatches else "fail", "close_rehash_passed": True,
        "outer_member_count": len(archive._files), "outer_member_categories": dict(classes),
        "source_byte_checks": {"copy_occurrences": len(byte_rows), "unique_repository_paths": len(byte_set),
            "unique_first_party_paths": len(byte_set & first_party),
            "artifacts_source_copy_occurrences": classes["artifacts_source"],
            "artifacts_source_unique_paths": len(source_member_set),
            "artifacts_source_packet_copies": dict(Counter(r["locator"].split("/artifacts/source/", 1)[0] for r in byte_rows if r["category"] == "artifacts_source")),
            "categories": dict(Counter(r["category"] for r in byte_rows)),
            "transcript_sha256": digest(canonical(byte_rows))},
        "source_receipt_checks": {"occurrences": len(receipt_rows), "unique_repository_paths": len(receipt_set),
            "unique_first_party_paths": len(receipt_set & first_party),
            "unique_tracked_third_party_paths": len(receipt_set - first_party),
            "source_paths_with_receipt_but_no_retained_source_bytes": len(receipt_set - byte_set),
            "categories": dict(Counter(r["category"] for r in receipt_rows)),
            "transcript_sha256": digest(canonical(receipt_rows))},
        "all_source_union": {"unique_repository_paths": len(source_paths), "unique_first_party_paths": len(first_party),
            "unique_tracked_third_party_paths": len(source_paths - first_party)},
        "source_snapshots": source_snapshots, "source_inventory_aggregates_checked": len(aggregate_rows),
        "source_inventory_pin_references_checked": len(aggregate_references),
        "execution_revision_or_tree_references_checked": len(revision_references),
        "submodule_limits": {"uncompared_source_receipt_occurrences": len(unknown_submodule_rows),
            "unique_uncompared_paths": len({r["source"] for r in unknown_submodule_rows}),
            "paths_sha256": digest(canonical(sorted({r["source"] for r in unknown_submodule_rows})))},
        "absent_external_bytes": {"unique_observed_tool_identities": len(absent_tools),
            "tool_receipt_occurrences": len(tool_rows), "third_party_locked_wheels": len(json_rows["p05_torch_contract.json"]["wheels"]),
            "framework_installed_before_rows": len(installed), "framework_installed_after_rows": len(json_rows["torch/snapshots/installed-after.json"]),
            "framework_payload_rows": len(payload), "framework_seed_rows": len(seed),
            "framework_payload_rows_other_than_first_party_package": sum(not r["path"].startswith((SITE + "vortex_ai/", SITE + "vortex_ai-0.1.0.dist-info/")) for r in payload)},
        "nested_packages": nested_summary, "nested_non_source_categories": dict(nested_classes),
        "generated_outer_members": generated_names,
        "parsed_json_members": len(parsed_json_files), "unparsed_digest_bearing_log_lines": log_unparsed,
        "read_receipt": {k: v for k, v in read_receipt.items() if k != "read_files"},
        "read_members_receipt_sha256": digest(canonical(read_receipt["read_files"])),
        "mismatches": mismatches,
    }
    return report, by_source


def main():
    reader_before = (ROOT / READER).read_bytes()
    assert digest(reader_before) == READER_SHA
    assert git("cat-file", "blob", REVIEWED_READER_REVISION + ":" + READER) == reader_before
    spec = importlib.util.spec_from_file_location("a49_reviewed_archive_reader", ROOT / READER)
    api = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(api)
    intake0 = json.loads((ROOT / "docs/project/evidence/p05-torch-replay/intake.json").read_text())
    intake6 = json.loads((BASE / "validation/c6-intake.json").read_text())
    assert (intake0["execution_revision"], intake6["execution_revision"]) == REVISIONS
    manifests = {}
    results, details, archive_sources = [], {}, {}
    for intake in (intake0, intake6):
        revision = intake["execution_revision"]
        tree_files, links = tree(revision)
        for item in intake["artifacts"]:
            fmt = item.get("format") or ("fp16" if "-fp16-" in item["name"] else "bf16")
            filename = f"p05-torch-{fmt}-{revision[:8]}-original.zip"
            path = BASE / "originals" / filename
            assert path.stat().st_size == item["size_bytes"]
            report, sources = artifact_probe(path, item["sha256"], revision, fmt, api, tree_files, links)
            results.append(report)
            if revision in details:
                assert details[revision] == sources, "Format-specific source path joins differ"
            details[revision] = sources
            archive_sources[filename] = revision
            manifests[revision] = {"tree": report["execution_tree"], "source_blob_rows": len(tree_files), "gitlinks": links}
            print(json.dumps({"archive": filename, "outcome": report["outcome"],
                "bytes": report["source_byte_checks"], "receipts": report["source_receipt_checks"],
                "union": report["all_source_union"], "mismatches": report["mismatches"],
                "unparsed_log_lines": len(report["unparsed_digest_bearing_log_lines"])}), flush=True)
    assert (ROOT / READER).read_bytes() == reader_before
    changed_sources = [p for p in sorted(set(details[REVISIONS[0]]) | set(details[REVISIONS[1]]))
                       if details[REVISIONS[0]].get(p, {}).get("sha256") != details[REVISIONS[1]].get(p, {}).get("sha256")]
    output = {"scope": "independent-exact-Git-blob-first-party-source-joins", "agent": 49,
        "reader": {"path": READER, "sha256": READER_SHA, "reviewed_revision": REVIEWED_READER_REVISION,
                   "identity_scope": "Only the unchanged shared archive_reader.py; no current replay-core or installation-parser identity is claimed.",
                   "matches_reviewed_commit_blob": True, "unchanged_after_all_reads": True},
        "probe": {"path": str(Path(__file__)), "sha256": digest(Path(__file__).read_bytes()), "python": sys.version},
        "execution": {"native_execution": "not_run", "retained_code_executed": False,
                      "archive_members_written_to_filesystem": False, "producer_paths_opened": False,
                      "acceptance_claimed": False, "phase_acceptance": False},
        "method": "Pinned outer ArchiveReader; bounded in-memory ZIP/TAR reads; Git ls-tree and cat-file --batch; raw source byte equality plus SHA-256/size receipt comparisons; Git blob SHA-1 recomputed.",
        "counting": "Copy occurrences count every retained location; unique source paths deduplicate inside each original and are never summed across copies/formats/revisions. Git-tracked third_party paths are separately identified; gitlink source bytes are not compared.",
        "limitations": [
            "Matching a retained receipt to a Git blob verifies the receipt's recorded identity, not absent producer filesystem bytes or whether the producer used those bytes.",
            "Generated configuration/source and package metadata have no corresponding exact Git file; they are classified separately and are not counted as source-blob matches.",
            "Submodule source bytes, third-party framework wheel/payload bytes, interpreter/compiler/tool bytes are not supplied as Git blobs or retained source bytes; no byte qualification is inferred.",
            "Compiled extensions, simulators, libraries and kernels are outputs, not Git source blobs; this probe does not establish reproducible compilation or native behavior.",
            "Provider origin and reported host/native outcomes are separate evidence. This report grants no acceptance.",
        ], "git_revisions": manifests, "source_paths_changed_between_execution_revisions": changed_sources,
        "artifacts": results}
    target = BASE / "agent-notes/a49-git-source-joins.json"
    target.write_text(json.dumps(output, sort_keys=True, indent=2) + "\n")
    (BASE / "agent-notes/a49-git-source-join-paths.json").write_text(json.dumps(
        {"archives": archive_sources, "execution_revisions": details,
         "format_source_join_tables_equal": True}, sort_keys=True, separators=(",", ":")) + "\n")
    assert all(row["outcome"] == "pass" for row in results), "Source mismatch found; see JSON report"


if __name__ == "__main__":
    main()
