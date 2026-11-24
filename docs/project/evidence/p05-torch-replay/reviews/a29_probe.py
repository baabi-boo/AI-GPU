#!/usr/bin/env python3
"""Owned synthetic ZIP lifetime probes; public semantic joins are stubbed.

No retained original, retained code, native execution, extraction or producer
path is used. Source files are read only. Each fixture is independently owned.
"""
import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
import zipfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1] / "AI-GPU"
sys.path.insert(0, str(ROOT / "ci/project"))
import p05_torch_replay as replay
from test_p05_torch_replay_driver import API, OrchestrationTests, REVISION

NAME = "torch/report.json"
PAYLOAD = b"OWNED_LIFETIME_A29"
HELPER = OrchestrationTests()
RESULTS = []


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(root):
    path = Path(root) / "a29-owned.zip"
    entry = zipfile.ZipInfo(NAME, date_time=(2020, 1, 1, 0, 0, 0))
    entry.compress_type = zipfile.ZIP_STORED
    entry.external_attr = 0o100600 << 16
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(entry, PAYLOAD)
    return path, digest(path)


def mutate(path, *, append=False):
    before = path.stat()
    before_hash = digest(path)
    with path.open("r+b") as stream:
        stream.seek(0, os.SEEK_END) if append else stream.seek(30 + len(NAME))
        stream.write(b"X")
        stream.flush()
        os.fsync(stream.fileno())
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    after = path.stat()
    result = {"before_sha256": before_hash, "after_sha256": digest(path),
              "same_size": before.st_size == after.st_size,
              "restored_mtime": before.st_mtime_ns == after.st_mtime_ns,
              "ctime_changed": before.st_ctime_ns != after.st_ctime_ns}
    assert result["before_sha256"] != result["after_sha256"]
    assert result["restored_mtime"] and result["same_size"] == (not append)
    return result


def released(reader):
    return reader._closed and reader._stream.closed and reader._zip.fp is None


def reader_probe(mode):
    with tempfile.TemporaryDirectory(prefix="a29-reader-") as root:
        path, pin = fixture(root)
        reader = API.ArchiveReader(path, pin)
        errors, mutation = [], None
        assert reader.read(NAME) == PAYLOAD
        if mode != "valid":
            mutation = mutate(path, append=mode == "append")
        if mode == "same_size":
            try:
                reader.read(NAME)
            except API.ArchiveError as error:
                errors.append(str(error))
            else:
                raise AssertionError("mutated ZIP reread succeeded")
        try:
            reader.close()
        except API.ArchiveError as error:
            errors.append(str(error))
        else:
            assert mode == "valid", "mutated ZIP close succeeded"
        assert released(reader)
        assert len(errors) == {"valid": 0, "append": 1, "same_size": 2}[mode]
        assert all("original ZIP changed during its audit" in error for error in errors)
        RESULTS.append({"probe": "reader_" + mode, "expected_outcome_observed": True,
                        "errors": errors, "released": True, "mutation": mutation,
                        "archive_sha256": pin})


def public_probe(mode, cli):
    """Actual public API/main and ArchiveReader; semantic orchestration seams.

    Composition reuses the existing helper's stubs for report/native/package/
    observation/supplementary joins. The read, coverage loop, context exit,
    source recheck, exception propagation and JSON publication remain real.
    """
    with tempfile.TemporaryDirectory(prefix="a29-public-") as root:
        path, pin = fixture(root)
        events, mutation, readers = [], [], []
        real_close, real_sources = API.ArchiveReader.close, replay._reader_sources

        def close(reader):
            readers.append(reader)
            assert [r["path"] for r in reader.receipt()["read_files"]] == [NAME]
            events.append("close-enter-after-read")
            if mode == "mutation":
                mutation.append(mutate(path))
            try:
                real_close(reader)
            except API.ArchiveError:
                events.append("close-identity-rejected")
                raise
            events.append("close-identity-complete")
            assert released(reader)
            if mode == "close_fault":
                events.append("injected-close-failure")
                raise ValueError("a29 injected final close failure")

        source_calls = 0

        def sources():
            nonlocal source_calls
            source_calls += 1
            result = real_sources()
            if source_calls == 1:
                events.append("source-check-initial")
            else:
                assert len(readers) == 1 and released(readers[0])
                events.append("source-check-after-close")
                if mode == "source_fault":
                    result = copy.deepcopy(result)
                    result[-1]["sha256"] = "0" * 64
            return result

        stdout = io.StringIO()
        failure = None
        with HELPER.driver(path) as run, patch.object(API.ArchiveReader, "close", close), \
                patch.object(replay, "_reader_sources", sources), contextlib.redirect_stdout(stdout):
            if cli:
                status = replay.main(["--archive", str(path), "--sha256", pin,
                                      "--expected-revision", REVISION, "--format", "fp16"])
                value = json.loads(stdout.getvalue())
                events.append("cli-return")
                assert status == (0 if mode == "valid" else 1)
                assert value["outcome"] == ("pass" if mode == "valid" else "fail")
                assert value["native_execution"] == "not_run"
                assert all(value[key] is False for key in
                           ("retained_code_executed", "acceptance_claimed", "phase_acceptance"))
                failure = value.get("reason")
            else:
                try:
                    value = run()
                    events.append("api-return")
                except ValueError as error:
                    failure = str(error)
                    events.append("api-raised")
                assert bool(failure) == (mode != "valid")
                if mode == "valid":
                    assert value["outcome"] == "pass"
            assert len(readers) == 1 and released(readers[0])
        expected_checks = 1 if mode in ("mutation", "close_fault") else 2
        assert source_calls == expected_checks
        if mode == "valid":
            assert events[-2] == "source-check-after-close"
        if mode == "mutation":
            assert "original ZIP changed during its audit" in failure
        if mode == "close_fault":
            assert "injected final close failure" in failure
        if mode == "source_fault":
            assert "trusted reader sources during replay differs" in failure
        RESULTS.append({"probe": "public_" + mode + ("_cli" if cli else "_api"),
                        "scope": "orchestration-only-semantic-stubs",
                        "expected_outcome_observed": True, "events": events,
                        "failure": failure, "released": True, "mutation": mutation})


def main():
    reviewed = [ROOT / "docs/project/evidence/p05-torch/reviews/archive_reader.py",
                ROOT / "ci/project/p05_torch_replay.py",
                ROOT / "ci/project/p06_replay.py",
                ROOT / "ci/project/test_p05_torch_replay_driver.py"]
    before = {str(p.relative_to(ROOT)): digest(p) for p in reviewed}
    all_sources_before = replay._reader_sources()
    for mode in ("valid", "append", "same_size"):
        reader_probe(mode)
    for mode in ("valid", "mutation", "close_fault", "source_fault"):
        for cli in (False, True):
            public_probe(mode, cli)
    after = {str(p.relative_to(ROOT)): digest(p) for p in reviewed}
    assert before == after
    assert all_sources_before == replay._reader_sources()
    print(json.dumps({"scope": "host-only-owned-synthetic-lifetime-publication",
                      "probe_count": len(RESULTS), "all_expected_outcomes_observed": True,
                      "existing_source_unchanged": before == after,
                      "reader_source_count": len(all_sources_before),
                      "source_sha256": before, "probe_sha256": digest(Path(__file__)),
                      "results": RESULTS}, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
