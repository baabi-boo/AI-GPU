"""Inspect original native raw records as data; do not run retained code."""

from pathlib import Path
import hashlib
import json
import zipfile

import p06_counter_public_records as records


ROOT = Path.cwd()
NATIVE = ROOT / "docs/project/evidence/p06-counter-diagnostics/native"
intake = json.loads((NATIVE / "public-runtime-pass.json").read_bytes())
assert set(intake) == {"archive", "sha256", "source_revision"}
path = NATIVE / intake["archive"]
data = path.read_bytes()
assert hashlib.sha256(data).hexdigest() == intake["sha256"] == "05f79eef4c9e30b97302e02fec9e2cca47e08fc10c4d5f8235b21f40f41d7276"
assert len(data) == 4228429
assert intake["source_revision"] == "e5f152464dda5e488d6d1a030c1fcdc49b5a9701"
rows = []
with zipfile.ZipFile(path) as archive:
    body = archive.read("public-counters/report.json")
    report_digest = hashlib.sha256(body).hexdigest()
    report = json.loads(body)
    for mode in records.MODES:
        command = next(row for row in report["commands"] if row["id"] == "public-" + mode)
        observed = records.verify_output(archive.read("public-counters/" + command["log"]).decode(), mode)
        row = {"mode": mode, "schema_version": observed["schema_version"], "checks": observed["checks"],
               "terminal_snapshots": len(observed["terminal_snapshots"]), "destructions": len(observed["destructions"]),
               "cp_after": [{key: item["cp_after"][key]
                             for key in ("head_writeback_raw", "runtime_tail", "tail_register_pair_raw", "retired", "expected")}
                            for item in observed["terminal_snapshots"]]}
        if observed["failure"]:
            row["dma"] = observed["failure"]["suppression"]["dma"]
        rows.append(row)
receipt = {"scope": "retained native raw-log parser inspection only; no new native execution",
           "archive": intake, "archive_size_bytes": len(data), "public_report_sha256": report_digest, "modes": rows}
(ROOT.parent / "w07-public-replay-genuine-raw-inspection.json").write_text(json.dumps(receipt, indent=2) + "\n")
with (ROOT.parent / "w07-public-replay-integration-tests.log").open("a") as stream:
    stream.write("\nRAW INSPECTION DEVELOPMENT FAILURE: first inline inspection attempted to re-read report bytes after its ZIP context had closed; ValueError: Attempt to use ZIP archive that was already closed. No repository/evidence bytes changed.\n")
    stream.write("CORRECTED GENUINE RAW INSPECTION " + json.dumps(receipt, sort_keys=True) + "\n")
print(json.dumps(receipt, indent=2))
