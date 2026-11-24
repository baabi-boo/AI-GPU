"""Agent16 bounded data-only original native/installation validation."""
import hashlib
import json
from pathlib import Path
import time

import p05_replay_installation
import p05_replay_native
from p06_replay import _archive_api


root = Path(__file__).resolve().parents[1]
sources = (
    root / "AI-GPU/ci/project/p05_replay_installation.py",
    root / "AI-GPU/ci/project/p05_replay_native.py",
    root / "AI-GPU/docs/project/evidence/p05-torch/reviews/archive_reader.py",
)
before = {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
revision = "c0b44ce64665fe11895f869eea8c38c9b820d6f7"
results = []
for fmt, digest in (
    ("fp16", "8c42f7e9f310972e2c0c67c56a03ce8f5460d706cb8dc3a5397435445ea6737c"),
    ("bf16", "787fd1b41a27da8c100277613c581ba734920fd45b13e0707ba0f9ea2e866330"),
):
    started = time.monotonic()
    path = root / "originals" / ("p05-torch-" + fmt + "-c0b44ce6-original.zip")
    with _archive_api().ArchiveReader(path, digest) as archive:
        outer = archive.view()
        native = p05_replay_native.verify_native(outer, expected_revision=revision, expected_format=fmt)
        installed = p05_replay_installation.verify_installations(
            outer, outer.subview("torch").json("report.json"), native,
            expected_revision=revision, expected_format=fmt)
        archive_receipt = archive.receipt()
    baseline = json.loads((root / "validation" / (fmt + "-replay.json")).read_bytes())
    assert installed["summary"] == baseline["installation"], "original installation summary changed"
    results.append({"format": fmt, "outcome": "pass", "sha256": digest,
                    "archive_close_rehash": "pass", "original_installation_summary_unchanged": True,
                    "native_counts": native["counts"], "installation": installed["summary"],
                    "archive": archive_receipt["archive"], "seconds": round(time.monotonic() - started, 6)})
after = {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
assert after == before, "helper source changed during validation"
print(json.dumps({"scope": "native-and-installation-helper-only", "sources": before,
                  "sources_unchanged": True, "results": results}, indent=2, sort_keys=True))
