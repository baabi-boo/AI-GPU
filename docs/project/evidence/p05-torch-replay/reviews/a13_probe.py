"""Independent agent13 host-only probes; retained archive members remain inert."""
from contextlib import ExitStack
import copy
import hashlib
import io
import json
import os
from pathlib import Path
from unittest.mock import patch

import p05_replay_native as replay
from p06_replay import _archive_api
from test_p05_replay_native import MemoryView, descriptor, encoded, synthetic_results, model_output

REVISION = "c0b44ce64665fe11895f869eea8c38c9b820d6f7"
ARCHIVE = Path("/workspace/scratch/101d52695253/originals/p05-torch-fp16-c0b44ce6-original.zip")
DIGEST = "8c42f7e9f310972e2c0c67c56a03ce8f5460d706cb8dc3a5397435445ea6737c"
api = _archive_api()


class StrictMemoryView(MemoryView):
    def subview(self, relative):
        return StrictMemoryView(self.payloads, self.name(relative))

    def json(self, relative, *, integers_only=False):
        return api.strict_json(self.read(relative), integers_only=integers_only)

    def document(self, row, expected_path=None, *, integers_only=False):
        return api.strict_json(self.verified(row, expected_path), integers_only=integers_only)


def propagate(files, native):
    files["native-model/report.json"] = encoded(native)
    for name in list(files):
        if name.startswith("python/native/") or name.startswith("torch/python/"):
            del files[name]
    for name, body in list(files.items()):
        if name.startswith("native-model/"):
            files["python/native/" + name.removeprefix("native-model/")] = body
    python = json.loads(files["python/report.json"])
    view = StrictMemoryView(files)
    python["native_report"] = descriptor("native/report.json", files["native-model/report.json"])
    python["native_input"]["files"] = view.subview("native-model").inventory()
    files["python/report.json"] = encoded(python)
    for name, body in list(files.items()):
        if name.startswith("python/"):
            files["torch/" + name] = body


def check(files):
    return replay.verify_native(StrictMemoryView(files), expected_revision=REVISION, expected_format="fp16")


def guarded(original, metadata=False):
    def wrapper(path, *args, **kwargs):
        if not isinstance(path, int):
            location = os.fsdecode(os.fspath(path))
            ancestor = metadata and location in {str(replay.ROOT), *(str(path) for path in replay.ROOT.parents)}
            if not location.startswith(str(replay.ROOT) + "/") and not ancestor:
                raise AssertionError("unexpected filesystem access: " + location)
        return original(path, *args, **kwargs)
    return wrapper


with api.ArchiveReader(ARCHIVE, DIGEST) as archive:
    original = {name: archive.read(name, limit=replay.MAX_MEMBER_BYTES) for name in archive.files()
                if name.startswith(("native-model/", "python/", "torch/python/"))}
print("original_reader_closed_after_rehash", True)
print("inert_original_members", len(original))

with ExitStack() as stack:
    for owner, method in ((Path, "open"), (Path, "resolve"), (Path, "stat"),
                          (Path, "is_file"), (Path, "is_symlink"), (io, "open"), (os, "open")):
        stack.enter_context(patch.object(owner, method, guarded(getattr(owner, method),
            metadata=owner is Path and method in {"resolve", "stat", "is_file", "is_symlink"})))
    stack.enter_context(patch("subprocess.Popen", side_effect=AssertionError("process launch")))
    result = check(original)
    assert result["counts"]["total_launches"] == 36
    print("baseline_full_native_with_io_guard", "PASS", result["counts"])

    for label in ("native_zero_elapsed", "python_zero_elapsed", "dropped_native_retained_source",
                  "source_after_mismatch", "compiler_summary_mismatch", "missing_native_command"):
        files = dict(original)
        native = json.loads(files["native-model/report.json"])
        if label == "native_zero_elapsed":
            native["finished_at"] = native["started_at"]
        elif label == "python_zero_elapsed":
            python = json.loads(files["python/report.json"])
            python["finished_at"] = python["started_at"]
            files["python/report.json"] = encoded(python)
        elif label == "dropped_native_retained_source":
            name = "artifacts/source/tests/regression/ai_mlp/main.cpp"
            assert name in {row["path"] for row in native["retained_sources"]}
            native["retained_sources"] = [row for row in native["retained_sources"] if row["path"] != name]
            del files["native-model/" + name]
        elif label == "source_after_mismatch":
            name = "snapshots/source-after.json"
            source = json.loads(files["native-model/" + name])
            source["checkout"]["tree"] = "0" * 40
            files["native-model/" + name] = encoded(source)
            native["source_after"] = descriptor(name, files["native-model/" + name])
        elif label == "compiler_summary_mismatch":
            native["variants"][0]["compiler_records"][0]["configuration"]["ITYPE"] = "bf16"
        elif label == "missing_native_command":
            native["commands"] = [row for row in native["commands"] if row["id"] != "version-make"]
            del files["native-model/logs/version-make.log"]
        propagate(files, native)
        try:
            counts = check(files)["counts"]
        except ValueError as error:
            print(label, "REJECTED", str(error))
        else:
            print(label, "ACCEPTED", counts)

    files = dict(original)
    files["torch/python/native/report.json"] += b" "
    try:
        check(files)
        raise AssertionError("asymmetric copied bytes accepted")
    except ValueError as error:
        print("asymmetric_copy", "REJECTED", str(error))

sample = synthetic_results()
stage = sample[1]["variants"][0]["cases"][0]["observations"][0]["trace"]["native"][1]
stage["a_bytes"] = "ff" + stage["a_bytes"][2:]
case = sample[1]["variants"][0]["cases"][0]
sample[0]["native/logs/simx-fp16-" + case["id"] + ".log"] = model_output(case["observations"]).encode()
try:
    replay._results(MemoryView(sample[0], "native"), MemoryView(sample[0], "python"),
                    *sample[1:], "2" * 64, "3" * 64, "1" * 40, "fp16")
    raise AssertionError("mutated output-stage A lineage accepted")
except ValueError as error:
    print("synthetic_output_stage_a_lineage", "REJECTED", str(error))
