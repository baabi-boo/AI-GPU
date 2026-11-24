#!/usr/bin/env python3
"""Bounded synthetic exact-JSON/type probes; no native execution or originals."""

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1] / "AI-GPU"
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "ci/project"))
import p05_torch_replay as replay
from p02_wmma_fixtures import load_cases
from test_p05_torch_replay_driver import command_fixture, source_fixture, REVISION

API = replay._archive_api()
FILES = (
    "docs/project/evidence/p05-torch/reviews/archive_reader.py",
    "ci/project/p06_replay.py", "ci/project/p05_torch_replay.py",
    "ci/project/p05_replay_native.py", "ci/project/p05_replay_installation.py",
    "ci/project/p05_execution_records.py", "ci/project/p05_torch_records.py",
    "ci/project/p05_installed_check.py", "ci/project/test_p05_torch_replay_driver.py",
)
hashes = lambda: {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in FILES}
BEFORE = hashes()
RESULTS = []
STATS = {"archives": 0, "largest_zip_bytes": 0, "largest_payload_bytes": 0}


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def row(name, body):
    return {"path": name, "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)}


def check(name, operation, error=None):
    try:
        operation()
    except ValueError as exc:
        assert error is not None and error in str(exc), (name, type(exc).__name__, str(exc))
        RESULTS.append({"name": name, "outcome": "rejected", "reason": str(exc)})
    else:
        assert error is None, (name, "unexpected acceptance")
        RESULTS.append({"name": name, "outcome": "accepted"})


def packet(payloads, operation):
    with tempfile.TemporaryDirectory(prefix="a32-synthetic-") as directory:
        archive_path = Path(directory).resolve() / "tiny.zip"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED) as archive:
            for name, body in sorted(payloads.items()):
                info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
                archive.writestr(info, body)
        raw = archive_path.read_bytes()
        STATS["archives"] += 1
        STATS["largest_zip_bytes"] = max(STATS["largest_zip_bytes"], len(raw))
        STATS["largest_payload_bytes"] = max(STATS["largest_payload_bytes"], sum(map(len, payloads.values())))
        with API.ArchiveReader(archive_path, hashlib.sha256(raw).hexdigest()) as archive:
            return operation(archive.view())


def parsed(raw, operation=lambda value: None, **kwargs):
    return packet({"value.json": raw}, lambda view: operation(view.json("value.json", **kwargs)))


def exact_types(value):
    assert tuple(type(item).__name__ for item in value) == ("bool", "int", "float")


for name, raw, error in (
    ("escaped-duplicate", b'{"outer":{"n":1,"\\u006e":2}}', "duplicate JSON field"),
    ("malformed-utf8", b'{"x":"\xed\xa0\x80"}', "invalid bounded JSON"),
    ("nan", b'{"x":NaN}', "noninteger JSON observation number"),
    ("exponent-overflow", b'{"x":1e999}', "nonfinite JSON number"),
    ("depth65", b"[" * 65 + b"0" + b"]" * 65, "structure bound"),
    ("integer65digits", b"9" * 65, "oversized JSON integer"),
    ("integer64digits", b"9" * 64, None),
    ("depth64", b"[" * 64 + b"0" + b"]" * 64, None),
):
    check(name, lambda raw=raw: parsed(raw), error)
check("types-preserved", lambda: parsed(b"[true,1,1.0]", exact_types))
check("integer-only-float", lambda: parsed(b'{"count":1.0}', integers_only=True), "noninteger JSON")


def descriptor_probe(change):
    descriptor = {**row("one.bin", b"x"), **change}
    return packet({"one.bin": b"x", "descriptor.json": encode(descriptor)},
                  lambda view: view.verified(view.json("descriptor.json")))


for name, change, error in (
    ("descriptor-int", {}, None),
    ("descriptor-bool", {"size_bytes": True}, "byte count"),
    ("descriptor-float", {"size_bytes": 1.0}, "byte count"),
    ("descriptor-negative", {"size_bytes": -1}, "byte count"),
    ("descriptor-overbound", {"size_bytes": API.MEMBER_BYTES + 1}, "byte count"),
    ("descriptor-extra", {"extra": 0}, "descriptor fields"),
    ("descriptor-wrong-size", {"size_bytes": 0}, "hash or size differs"),
):
    check(name, lambda change=change: descriptor_probe(change), error)

view, report, request = command_fixture()
source_view, source_report, source = source_fixture()
view.payloads.update(source_view.payloads)
report = {**dict.fromkeys(replay.REPORT_FIELDS), **report, **source_report}
report.update(schema_version=1, contract_id="p05-installed-torch-execution-v1", backend="simx", format="fp16",
              state="finished", outcome="pass", reason=None, development=False, source_stable=True,
              acceptance_claimed=False, phase_complete=False, iterations=2, budget=dict(replay.BUDGET),
              limitations=list(replay.REPORT_LIMITATIONS), started_at="2026-11-24T00:00:00+00:00",
              finished_at="2026-11-24T00:00:10+00:00")
for key in ("resources_before", "resources_after"):
    report[key] = {"available_memory_bytes": 4 * 1024**3,
                   "free_disk_bytes": dict.fromkeys(("source", "output", "work"), 15 * 1024**3)}
base = request["base_request"]
base.update(schema_version=1, contract_id="p05-installed-request-v1", iterations=2,
            matmul_cases=replay.python_records.select_matmul_cases(load_cases(ROOT), "fp16"),
            model_cases=["fp16-" + family for family in replay.python_records.MODEL_FAMILIES])
base["binding"].update(backend="simx", format="fp16", bundle_sha256="a" * 64,
                       source_sha256="b" * 64, qualification_id="c" * 64, source_revision=REVISION)
request.update(schema_version=1, contract_id="p05-torch-request-v1",
               framework={"version": replay.torch_records.TORCH_VERSION,
                          "contract_sha256": "d" * 64, "adapter_sha256": "e" * 64})
report["installed_request"] = view.document_row("snapshots/installed-request.json", request)
report["observations"] = view.document_row("artifacts/installed-observations.json", {})


def report_probe(mutate=lambda value, source: None):
    value, source_value, payloads = copy.deepcopy((report, source, view.payloads))
    mutate(value, source_value)
    for key in ("source_before", "source_after"):
        name = "snapshots/" + key.replace("_", "-") + ".json"
        payloads[name] = encode(source_value)
        value[key] = row(name, payloads[name])
    payloads["report.json"] = encode(value)
    return packet(payloads, lambda packet_view: replay._report(packet_view, API, REVISION, "fp16"))


for name, mutation, error in (
    ("report-duration-float", lambda r, s: None, None),
    ("report-duration-int", lambda r, s: r["commands"][0].update(duration_seconds=1), None),
    ("report-schema-bool", lambda r, s: r.update(schema_version=True), "report schema_version"),
    ("report-count-float", lambda r, s: r.update(iterations=2.0), "report iterations"),
    ("report-extra", lambda r, s: r.update(extra=0), "report fields"),
    ("command-duration-bool", lambda r, s: r["commands"][0].update(duration_seconds=False), "command duration"),
    ("command-rss-float", lambda r, s: r["commands"][0].update(peak_rss_bytes=4096.0), "command sampled RSS"),
    ("command-log-size-float", lambda r, s: r["commands"][0].update(log_size_bytes=0.0), "command log length"),
    ("joined-source-count-float", lambda r, s: s["checkout"]["submodules"].update(declared_count=5.0), "declared submodule count"),
    ("joined-source-descriptor-float", lambda r, s: r["retained_sources"][0].update(size_bytes=float(r["retained_sources"][0]["size_bytes"])), "byte count"),
):
    check(name, lambda mutation=mutation: report_probe(mutation), error)

counts = {"copied_packet_additional_launches": 0, "distinct_total_launches": 108}
for name, changed, error in (
    ("count-join-int", {}, None),
    ("count-join-bool", {"copied_packet_additional_launches": False}, "counts differs"),
    ("count-join-float", {"distinct_total_launches": 108.0}, "counts differs"),
):
    check(name, lambda changed=changed: parsed(encode({**counts, **changed}),
          lambda value: replay.same(value, counts, "counts")), error)
for name, size, error in (("installation-size-int", 1, None), ("installation-size-bool", True, "file size"),
                          ("installation-size-float", 1.0, "file size")):
    check(name, lambda size=size: parsed(encode([{**row("one.bin", b"x"), "size_bytes": size}]),
          lambda value: replay.installation_replay._inventory(value, API, "synthetic")), error)

assert BEFORE == hashes(), "reviewed source changed during probe"
print(json.dumps({"scope": "synthetic host-only; no complete replay verdict", "checks": len(RESULTS),
                  "accepted_controls": sum(item["outcome"] == "accepted" for item in RESULTS),
                  "rejected_mutations": sum(item["outcome"] == "rejected" for item in RESULTS),
                  "source_hashes_stable": True, "source_sha256": BEFORE, "statistics": STATS,
                  "results": RESULTS}, indent=2, sort_keys=True))
