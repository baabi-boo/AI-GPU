#!/usr/bin/env python3
"""Publish completed local qualification evidence into fresh scratch staging.

Only retained text and named sidecars are read. Nothing is executed from a
packet, and no source, tool, dependency or build tree is traversed. The public
manifest maps original bytes to redacted bytes; embedded evidence hashes keep
their original meaning. This is separate from the historical P01 export schema.

Examples (run from the scratch workspace):
  python3 -B work-notes/blockers/export_local_packets.py export \
    --attempt failed953 --destination local-packets-staging
  python3 -B work-notes/blockers/export_local_packets.py export \
    --attempt all --destination local-packets.tar.gz --format tar.gz
  python3 -B work-notes/blockers/export_local_packets.py verify local-packets-staging
  python3 -B work-notes/blockers/export_local_packets.py verify local-packets-staging \
    --raw-workspace .
"""

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tarfile


MIB = 1024 * 1024
MAX_BYTES = 64 * MIB
MAX_FILE_BYTES = 16 * MIB
MAX_FILES = 2048
PROFILE = "literal-utf8-path-prefix-v1"
SCHEMA = "local-qualification-public-text-v1"
NOTES = "work-notes/blockers"
PRIVATE_MAPPING = NOTES + "/b05d-summary.json"
ATTEMPTS = {
    "failed953": {
        "packet": "local-qualification-run", "short": "9532327",
        "revision": "9532327e6006e0b6b09bae761745bc0d36a79b1e",
        "tree": "aeedbf4d7a042e86ec8d1326370a87dd73587494",
        "directory": "local-afu-9532327-failed", "launcher": "native-launch.json",
        "command": "native-command.json",
    },
    "retry7e4": {
        "packet": "local-qualification-run-2", "short": "7e4ac58",
        "revision": "7e4ac5851f1f71d292ed1802c3f92456d96faf8d",
        "tree": "89c28a445e0e269e53b36213a04e593f9e76b6d2",
        "directory": "local-afu-7e4ac58-retry", "launcher": "native-launch-7e4ac58.json",
        "command": "native-command-7e4ac58.json",
    },
}
ROOT_TOKENS = {
    "source": "$SOURCE", "tools": "$TOOLS", "dependencies": "$DEPENDENCIES",
    "headers": "$HEADERS", "build": "$BUILD", "output": "$OUTPUT",
}
PROTECTED_KEYS = {
    "outcome", "state", "exit_code", "phase_complete", "qualifies_P01_A03",
    "vendor_execution_performed", "supplemental", "execution_performed",
    "workload_command_started", "workload_execution_verified", "revision", "tree",
    "source_revision", "source_tree",
}
# Standard system paths (e.g. /usr/bin, /proc and /dev/null) remain meaningful.
# These classes are deployment/user roots and must be accounted for explicitly.
HOST_PATH = re.compile(
    r"(?<![A-Za-z0-9_.$}/)])(?:-(?:I|L|B|isystem|iquote|include))?"
    r"/(?:workspace|home|root|Users|opt|tmp|private|mnt|media|srv|run|var/tmp)"
    r"(?=/|[^A-Za-z0-9_.-]|$)|(?<![A-Za-z0-9_])~[/\\]|(?<![A-Za-z0-9_:/])[A-Za-z]:[\\/]"
)
TOKEN = re.compile(r"\$[A-Z][A-Z0-9_]{0,63}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class ExportError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ExportError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encode_json(value):
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False,
                       allow_nan=False) + "\n").encode("utf-8")


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def decode_json(data, label):
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=unique_keys,
                           parse_constant=lambda _: (_ for _ in ()).throw(
                               ExportError("nonfinite JSON constant")))
        require(isinstance(value, dict), label + ": JSON object required")
        return value
    except (UnicodeError, ValueError, RecursionError) as error:
        raise ExportError(label + ": invalid JSON: " + str(error)) from error


def relative_name(name):
    require(isinstance(name, str) and name and len(name.encode("utf-8")) <= 4096,
            "invalid relative member name")
    path = PurePosixPath(name)
    require(not path.is_absolute() and str(path) == name and "\\" not in name
            and all(p not in ("", ".", "..") for p in name.split("/"))
            and not any(ord(c) < 32 for c in name), "unsafe relative member name")
    return name


def file_state(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def real_directory(path):
    """Reject symbolic directory components rather than resolving through them."""
    path = Path(os.path.abspath(path))
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        require(stat.S_ISDIR(current.lstat().st_mode), "directory component is not real")
    return path


def read_stable(path, limit=MAX_FILE_BYTES):
    real_directory(path.parent)
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode), "input is not a regular file: " + path.name)
    require(0 <= before.st_size <= limit, "input exceeds file byte ceiling: " + path.name)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        initial = os.fstat(fd)
        require(file_state(before) == file_state(initial), "input changed while opening")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            data = stream.read(limit + 1)
        require(len(data) <= limit and len(data) == initial.st_size,
                "input changed size or exceeded byte ceiling")
        require(file_state(initial) == file_state(os.fstat(fd)) == file_state(path.lstat()),
                "input changed during reading")
        return data, file_state(initial)
    finally:
        os.close(fd)


def inventory(root):
    root = real_directory(root)
    result = []
    for directory, names, files in os.walk(root, followlinks=False):
        names.sort()
        files.sort()
        for name in names:
            require(stat.S_ISDIR((Path(directory) / name).lstat().st_mode),
                    "symbolic or special directory in packet")
        for name in files:
            path = Path(directory) / name
            require(stat.S_ISREG(path.lstat().st_mode), "symbolic or special file in packet")
            result.append(relative_name(path.relative_to(root).as_posix()))
            require(len(result) <= MAX_FILES, "file-count ceiling exceeded")
    return sorted(result)


class Capture:
    def __init__(self, workspace, maximum):
        self.workspace, self.maximum = real_directory(workspace), maximum
        self.files, self.states, self.trees = {}, {}, {}

    def read(self, name):
        name = relative_name(name)
        if name not in self.files:
            data, state = read_stable(self.workspace / name)
            require(sum(map(len, self.files.values())) + len(data) <= self.maximum,
                    "raw byte ceiling exceeded")
            require(len(self.files) < MAX_FILES, "raw file-count ceiling exceeded")
            self.files[name], self.states[name] = data, state
        return self.files[name]

    def tree(self, name):
        names = inventory(self.workspace / relative_name(name))
        self.trees[name] = names
        return {member: self.read(name + "/" + member) for member in names}

    def recheck(self):
        for name, expected in sorted(self.files.items()):
            observed, state = read_stable(self.workspace / name)
            require(observed == expected and state == self.states[name],
                    "raw input changed during export: " + name)
        for root, names in sorted(self.trees.items()):
            require(inventory(self.workspace / root) == names,
                    "raw packet inventory changed during export")


def assert_identity(data, record, label, sha_key="sha256", size_key="size_bytes"):
    require(record.get(sha_key) == digest(data) and record.get(size_key) == len(data),
            label + ": raw hash/size mismatch")


def check_report_evidence(report, members):
    referenced = {"report.json"}
    for command in report["commands"]:
        name = relative_name(command["log"])
        require(name in members, "missing recorded command log")
        assert_identity(members[name], command, name, "log_sha256", "log_size_bytes")
        require(command.get("cleanup_complete") is True, "command cleanup is incomplete")
        referenced.add(name)
    for snapshot in report["snapshots"]:
        retained = snapshot["retained"]
        name = relative_name(retained["path"])
        require(name in members, "missing recorded text snapshot")
        assert_identity(members[name], retained, name)
        assert_identity(members[name], snapshot["source"], name + " source-copy identity")
        referenced.add(name)
    return sorted(set(members) - referenced)


def protected_values(value, trail=()):
    result = {}
    if isinstance(value, dict):
        for key, child in value.items():
            location = trail + (key,)
            if key in PROTECTED_KEYS or "sha256" in key or key.endswith("_hash"):
                result[location] = child
            result.update(protected_values(child, location))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            result.update(protected_values(child, trail + (index,)))
    return result


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from strings(child)


def no_machine_paths(data, label, parsed=None):
    text = data.decode("utf-8", errors="strict")
    for item in [text, *(strings(parsed) if parsed is not None else [])]:
        require(HOST_PATH.search(item) is None,
                label + ": unaccounted deployment/home/temporary path remains")


def make_rules(report, suite, private):
    # Private input is explicit; do not infer broad workspace redaction to hide
    # an unknown path. The six run-specific roots override the first run's roots.
    by_token = {}
    for item in private["public_layout_proposal"]["prefix_mapping_private"]:
        prefix, token = item["raw_prefix"], item["token"]
        require(digest(prefix.encode("utf-8")) == item["raw_prefix_sha256_utf8"],
                "private prefix-map hash mismatch")
        by_token[token] = prefix
    for key, token in ROOT_TOKENS.items():
        by_token[token] = report["paths"][key]
    python_executable = suite["command"][0]
    require(isinstance(python_executable, str) and python_executable.startswith("/")
            and Path(python_executable).parent.name == "bin", "missing explicit Python prefix")
    by_token["$PYTHON_PREFIX"] = str(Path(python_executable).parent.parent)
    require(report["environment"].get("HOME") == by_token.get("$AGENT_HOME"),
            "home root needs an explicit private redaction rule")
    require(len(set(by_token.values())) == len(by_token), "duplicate redaction prefix")
    for token, prefix in by_token.items():
        require(TOKEN.fullmatch(token) and isinstance(prefix, str) and prefix.startswith("/")
                and prefix != "/" and not prefix.endswith("/")
                and not any(ord(c) < 32 for c in prefix), "invalid explicit redaction rule")
    return sorted([(prefix.encode("utf-8"), token.encode("ascii"))
                   for token, prefix in by_token.items()], key=lambda pair: (-len(pair[0]), pair[0]))


def transform(data, name, rules):
    require(b"\0" not in data, name + ": binary/NUL input is not publishable")
    data.decode("utf-8", errors="strict")
    published, counts = data, {}
    for prefix, token in rules:
        count = published.count(prefix)
        if count:
            counts[token.decode("ascii")] = count
            published = published.replace(prefix, token)
    raw_json = public_json = None
    protected_count = 0
    if name.endswith(".json"):
        raw_json = decode_json(data, name)
        public_json = decode_json(published, name)
        before, after = protected_values(raw_json), protected_values(public_json)
        require(before == after, name + ": protected outcome/hash field changed")
        protected_count = len(before)
    no_machine_paths(published, name, public_json)
    for prefix, _ in rules:
        require(prefix not in published, name + ": explicit raw prefix remains")
    return published, counts, protected_count


def attempt_readme(attempt_id, spec, report, launcher, suite, count):
    rows = "\n".join("| " + case["id"] + " | " + case["outcome"] + " |"
                     for case in report["cases"])
    suite_result = suite["result"]
    text = f"""# Local AFU attempt: {attempt_id}

Recorded native outcome: **{report['outcome']}**. Source revision
`{spec['revision']}`, tree `{spec['tree']}`.
Recorded interval: {report['started_at']} to {report['finished_at']}.
Outer launcher exit: **{launcher['exit_code']}**. Separate tooling-suite
outcome: **{suite.get('outcome', suite_result['outcome'])}**, process exit
**{suite_result['exit_code']}**. Individual command exits remain in the report.

| Selected case | Recorded outcome |
|---|---|
{rows}

`report.redacted.json` is derived from the complete raw report. Its original
`log_sha256`, snapshot hashes, sizes, outcomes and execution flags are preserved.
Those embedded hashes identify **raw bytes**. Root `manifest.json` records both
raw and public SHA-256/byte counts for each of the {count} retained evidence
files. Verify distributed bytes against **public** identities. Unchanged files
have equal raw and public identities. Reports and logs remain readable; source
snapshots are inert evidence and must not be run as an exported build tree.

Every raw packet file is retained, including every command log and text snapshot.
The matched suite JSON/log, native launcher, stdout/stderr, plan and command
sidecars are also retained. The plan's `pass` outcome describes preflight only.
The stdout report is a separately labeled, already partly redacted launcher copy;
the canonical raw-report relationship is the manifest's `report.redacted.json` row.

The aggregate execution flags can be true when only some cases verified; they
do not turn failed or not-run cases into passes. This is supplemental local
XRT-shim/model evidence. It does not establish vendor runtime, platform,
`hw_emu`, physical FPGA, cache-coherence or silicon qualification. The original
`qualifies_P01_A03` and `phase_complete` fields remain authoritative and false.
Binary executables, kernel images and simulator models referenced by identities
were never part of this text export and are not copied from the build tree.

`redaction-rules.json` lists inert display tokens, exact original-prefix hashes,
and replacement counts. Original prefixes remain in the private input mapping
and raw records. Replacement is literal UTF-8 bytes, longest prefix first;
nonmatching bytes and line endings are unchanged. The metadata is unsigned.
Public verification does not authenticate original execution. With the raw
workspace, the exporter can re-read all bytes and reproduce this transformation.
"""
    return text.encode("utf-8")


def build_bundle(workspace, chosen, maximum):
    require(0 < maximum <= MAX_BYTES, "byte ceiling must be within the hard 64 MiB limit")
    capture = Capture(workspace, maximum)
    private_bytes = capture.read(PRIVATE_MAPPING)
    private = decode_json(private_bytes, PRIVATE_MAPPING)
    output, artifacts, generated, summaries, forbidden = {}, [], [], [], []

    def generated_file(name, contents):
        require(name not in output, "duplicate generated public path")
        no_machine_paths(contents, name)
        output[name] = contents
        generated.append({"public_path": name, "public_sha256": digest(contents),
                          "public_size_bytes": len(contents), "origin": "export_metadata"})

    for attempt_id in chosen:
        spec = ATTEMPTS[attempt_id]
        raw_report_name = spec["packet"] + "/report.json"
        raw_report = capture.read(raw_report_name)
        report = decode_json(raw_report, raw_report_name)
        require(report.get("state") == "finished" and report.get("finished_at")
                and not report.get("active_command"), attempt_id + ": run is unfinished; export refused")
        require(report.get("mode") == "run" and report.get("outcome") in {"pass", "fail", "blocked"},
                attempt_id + ": invalid final run outcome")
        source = report["inputs_before"]["source"]
        require(source["revision"] == spec["revision"] and source["tree"] == spec["tree"],
                attempt_id + ": source revision/tree differs from the named attempt")
        require(report.get("supplemental") is True and report.get("qualifies_P01_A03") is False
                and report.get("phase_complete") is False
                and report.get("vendor_execution_performed") is False,
                "unexpected vendor/phase claim in local-only report")
        require(Path(report["paths"]["output"]) == capture.workspace / spec["packet"],
                "report output does not identify its retained packet")
        forbidden.extend(Path(value) for value in report["paths"].values() if value)
        sidecar_names = [spec["launcher"], spec["command"],
                         "full-suite-" + spec["short"] + ".json",
                         "full-suite-" + spec["short"] + ".log",
                         "native-run-" + spec["short"] + ".stdout.json",
                         "native-run-" + spec["short"] + ".stderr.log",
                         "native-plan-" + spec["short"] + ".json"]
        sidecars = {name: capture.read(NOTES + "/" + name) for name in sidecar_names}
        launcher = decode_json(sidecars[spec["launcher"]], "launcher")
        suite = decode_json(sidecars["full-suite-" + spec["short"] + ".json"], "suite")
        require(launcher.get("finished_at") and type(launcher.get("exit_code")) is int,
                attempt_id + ": launcher is unfinished; export refused")
        require(suite.get("finished_at") and suite.get("state", "finished") == "finished"
                and isinstance(suite.get("result"), dict)
                and suite["result"].get("cleanup_complete") is True,
                attempt_id + ": tooling suite is unfinished; export refused")
        require(launcher.get("source_revision") == suite.get("source_revision") == spec["revision"]
                and suite.get("source_tree") == spec["tree"], "sidecar source identity mismatch")
        assert_identity(sidecars["full-suite-" + spec["short"] + ".log"], suite["result"],
                        "tooling-suite log", "log_sha256", "log_size_bytes")
        stdout = decode_json(sidecars["native-run-" + spec["short"] + ".stdout.json"], "stdout")
        require(protected_values(stdout) == protected_values(report),
                "launcher stdout and canonical report differ in protected fields")
        members = capture.tree(spec["packet"])
        unreferenced = check_report_evidence(report, members)
        rules = make_rules(report, suite, private)
        totals = {token.decode("ascii"): 0 for _, token in rules}
        inputs = [(spec["packet"] + "/" + member,
                   "report.redacted.json" if member == "report.json" else member, data)
                  for member, data in sorted(members.items())]
        inputs.extend((NOTES + "/" + name, "tooling/" + name, data)
                      for name, data in sorted(sidecars.items()))
        protected_count = 0
        for raw_path, member, raw in inputs:
            public_path = spec["directory"] + "/" + member
            require(public_path not in output, "duplicate public path")
            public, counts, checked = transform(raw, member, rules)
            output[public_path] = public
            protected_count += checked
            for token, count in counts.items():
                totals[token] += count
            artifacts.append({"attempt": attempt_id, "raw_path": raw_path,
                              "public_path": public_path, "raw_sha256": digest(raw),
                              "public_sha256": digest(public), "raw_size_bytes": len(raw),
                              "public_size_bytes": len(public),
                              "transformation_id": PROFILE if counts else "byte-preserving-copy",
                              "replacement_counts": counts})
        rule_document = {
            "profile": PROFILE,
            "algorithm": "literal UTF-8 byte replacement; descending original-prefix byte length, then byte order",
            "nested_hash_policy": "All embedded raw evidence hashes and sizes remain unchanged.",
            "tokens_are_executable": False,
            "rules": [{"token": token.decode("ascii"), "raw_prefix_sha256_utf8": digest(prefix),
                       "raw_prefix_utf8_bytes": len(prefix), "replacements": totals[token.decode("ascii")]}
                      for prefix, token in rules],
        }
        generated_file(spec["directory"] + "/redaction-rules.json", encode_json(rule_document))
        generated_file(spec["directory"] + "/README.md",
                       attempt_readme(attempt_id, spec, report, launcher, suite, len(inputs)))
        summaries.append({"id": attempt_id, "directory": spec["directory"],
                          "source_revision": spec["revision"], "source_tree": spec["tree"],
                          "reported_outcome": report["outcome"], "raw_report_sha256": digest(raw_report),
                          "raw_packet_files": len(members), "retained_sidecar_files": len(sidecars),
                          "command_logs_verified": len(report["commands"]),
                          "text_snapshots_verified": len(report["snapshots"]),
                          "protected_json_fields_checked": protected_count,
                          "unreferenced_packet_files_retained": unreferenced,
                          "omitted_packet_files": []})

    generated_file("README.md", (
        "# Completed local qualification text packets\n\n"
        "Each attempt directory retains its exact recorded outcome and source identity.\n"
        "The root manifest distinguishes raw evidence from published, possibly redacted bytes.\n"
        "Every retained report, log and text snapshot is included; no binary model is copied.\n\n"
        "Verify with `python3 -B export_local_packets.py verify DESTINATION`. To also check\n"
        "the raw-to-public relationship, add `--raw-workspace RAW_WORKSPACE`. Public-only\n"
        "verification checks shipped bytes and their mapping, not original execution.\n"
        "The manifest inventories every shipped file except itself and is unsigned.\n"
        "The printed bundle digest includes the manifest and all member names and bytes.\n\n"
        "Directory and optional gzip/tar forms contain identical member bytes. Archive\n"
        "members have sorted paths, zero timestamps/ownership and mode 0644; the gzip\n"
        "header has no filename and timestamp zero. No wall-clock export time or output\n"
        "destination appears in generated content. Byte ceilings apply before writing.\n"
    ).encode("utf-8"))
    artifacts.sort(key=lambda row: row["public_path"])
    generated.sort(key=lambda row: row["public_path"])
    manifest = {
        "schema": SCHEMA, "schema_version": 1, "attempts": summaries,
        "limits": {"total_bytes": maximum, "per_file_bytes": MAX_FILE_BYTES, "files": MAX_FILES},
        "artifacts": artifacts, "generated_files": generated,
        "raw_retained_bytes": sum(row["raw_size_bytes"] for row in artifacts),
        "public_retained_bytes": sum(row["public_size_bytes"] for row in artifacts),
        "private_configuration": {"raw_path": PRIVATE_MAPPING, "raw_sha256": digest(private_bytes),
                                  "raw_size_bytes": len(private_bytes),
                                  "published": False, "reason": "contains private original-prefix mapping"},
        "hash_semantics": {"embedded_report_hashes": "raw bytes, unchanged",
                           "raw_sha256": "original input bytes before this exporter",
                           "public_sha256": "exact distributed member bytes after redaction",
                           "manifest_self_hash": "not embedded; printed bundle digest includes manifest"},
        "limitations": ["Unsigned provenance metadata does not authenticate execution.",
                        "No workload, suite, compiler or retained source is executed by this exporter.",
                        "Referenced external binary inputs and models are identified, not copied.",
                        "This supplemental local route does not qualify vendor or physical execution.",
                        "Machine-path scan covers deployment, home and temporary roots; standard system paths remain."],
    }
    output["manifest.json"] = encode_json(manifest)
    require(len(output) <= MAX_FILES and sum(map(len, output.values())) <= maximum,
            "public byte/file ceiling exceeded")
    require(all(len(data) <= MAX_FILE_BYTES for data in output.values()), "public file byte ceiling exceeded")
    for name, data in output.items():
        no_machine_paths(data, name, decode_json(data, name) if name.endswith(".json") else None)
    capture.recheck()
    return output, forbidden


def bundle_identity(members):
    records = [{"path": name, "sha256": digest(data), "size_bytes": len(data)}
               for name, data in sorted(members.items())]
    return digest(encode_json(records))


def archive_bytes(members):
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, filename="", mode="wb", compresslevel=9, mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT) as archive:
            for name, data in sorted(members.items()):
                info = tarfile.TarInfo(relative_name(name))
                info.size, info.mode, info.mtime = len(data), 0o644, 0
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def publish(workspace, destination, members, forbidden, output_format, maximum):
    workspace = real_directory(workspace)
    destination = Path(os.path.abspath(destination))
    require(destination != workspace and destination.is_relative_to(workspace),
            "destination must be fresh staging inside the scratch workspace")
    require(not os.path.lexists(destination), "destination already exists; nothing overwritten")
    real_directory(destination.parent)
    for root in [workspace / "AI-GPU", *forbidden]:
        require(not destination.is_relative_to(root), "destination overlaps a source/build/input tree")
    if output_format == "tar.gz":
        contents = archive_bytes(members)
        require(len(contents) <= maximum, "archive byte ceiling exceeded")
        with destination.open("xb") as stream:
            stream.write(contents)
        return {"archive_sha256": digest(contents), "archive_size_bytes": len(contents)}
    destination.mkdir(mode=0o700)
    for name, data in sorted(members.items()):
        path = destination / relative_name(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(data)
    return {}


def load_public(destination):
    destination = Path(destination)
    require(not destination.is_symlink(), "public destination is a symbolic link")
    members = {}
    if destination.is_dir():
        for name in inventory(destination):
            members[name] = read_stable(destination / name)[0]
            require(sum(map(len, members.values())) <= MAX_BYTES, "public byte ceiling exceeded")
    else:
        compressed = read_stable(destination, MAX_BYTES)[0]
        # Bound decompression before passing tar bytes to the parser.
        with gzip.GzipFile(fileobj=io.BytesIO(compressed), mode="rb") as stream:
            tar_bytes = stream.read(MAX_BYTES + MAX_FILES * 1024 + 10241)
        require(len(tar_bytes) <= MAX_BYTES + MAX_FILES * 1024 + 10240,
                "decompressed archive ceiling exceeded")
        with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as archive:
            for item in archive:
                name = relative_name(item.name)
                require(item.isfile() and name not in members and 0 <= item.size <= MAX_FILE_BYTES,
                        "archive contains a link, duplicate, special or oversized member")
                require(len(members) < MAX_FILES, "archive file-count ceiling exceeded")
                members[name] = archive.extractfile(item).read(MAX_FILE_BYTES + 1)
                require(len(members[name]) == item.size and sum(map(len, members.values())) <= MAX_BYTES,
                        "archive byte ceiling exceeded")
    return members


def verify(members, raw_workspace=None):
    require("manifest.json" in members, "public manifest is missing")
    manifest = decode_json(members["manifest.json"], "manifest")
    require(manifest.get("schema") == SCHEMA, "unsupported public schema")
    rows = manifest["artifacts"] + manifest["generated_files"]
    names = [relative_name(row["public_path"]) for row in rows]
    require(len(names) == len(set(names)) and set(names) | {"manifest.json"} == set(members),
            "manifest does not cover exactly the distributed files")
    for row in rows:
        assert_identity(members[row["public_path"]], row, row["public_path"],
                        "public_sha256", "public_size_bytes")
    for name, data in members.items():
        no_machine_paths(data, name, decode_json(data, name) if name.endswith(".json") else None)
    for attempt in manifest["attempts"]:
        prefix = attempt["directory"] + "/"
        mapping = {row["public_path"][len(prefix):]: row for row in manifest["artifacts"]
                   if row["attempt"] == attempt["id"]}
        report = decode_json(members[prefix + "report.redacted.json"], "public report")
        require(report["outcome"] == attempt["reported_outcome"]
                and mapping["report.redacted.json"]["raw_sha256"] == attempt["raw_report_sha256"],
                "report outcome/raw anchor differs from manifest")
        identities = [(c["log"], c["log_sha256"], c["log_size_bytes"]) for c in report["commands"]]
        identities.extend((s["retained"]["path"], s["retained"]["sha256"], s["retained"]["size_bytes"])
                          for s in report["snapshots"])
        for name, sha, size in identities:
            require(name in mapping and mapping[name]["raw_sha256"] == sha
                    and mapping[name]["raw_size_bytes"] == size,
                    "embedded raw identity differs from raw/public mapping")
    reproduced = False
    if raw_workspace is not None:
        expected, _ = build_bundle(raw_workspace, [a["id"] for a in manifest["attempts"]],
                                   manifest["limits"]["total_bytes"])
        require(expected == members, "published bytes differ from raw-input reproduction")
        reproduced = True
    return {"published_integrity": "verified", "raw_to_public_reproduced": reproduced,
            "original_execution_authenticated": False, "files": len(members),
            "bytes": sum(map(len, members.values())), "bundle_sha256": bundle_identity(members),
            "attempt_outcomes": {a["id"]: a["reported_outcome"] for a in manifest["attempts"]}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="action", required=True)
    export = commands.add_parser("export", help="export only completed attempts into a nonexistent destination")
    export.add_argument("--workspace", type=Path, default=Path(__file__).resolve().parents[2])
    export.add_argument("--attempt", choices=[*ATTEMPTS, "all"], required=True)
    export.add_argument("--destination", type=Path, required=True)
    export.add_argument("--format", choices=["directory", "tar.gz"], default="directory")
    export.add_argument("--max-bytes", type=int, default=MAX_BYTES)
    check = commands.add_parser("verify", help="check public identities, optionally reproduce from raw inputs")
    check.add_argument("destination", type=Path)
    check.add_argument("--raw-workspace", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.action == "export":
            require(not os.path.lexists(args.destination), "destination already exists; nothing overwritten")
            chosen = list(ATTEMPTS) if args.attempt == "all" else [args.attempt]
            members, forbidden = build_bundle(args.workspace, chosen, args.max_bytes)
            result = verify(members)
            result.update(publish(args.workspace, args.destination, members, forbidden, args.format, args.max_bytes))
            # Read-back is essential: the successful result describes written bytes.
            require(load_public(args.destination) == members, "written output differs from prepared bytes")
            result.update({"format": args.format, "raw_to_public_reproduced": True,
                           "raw_inputs_rechecked_unchanged": True})
        else:
            result = verify(load_public(args.destination), args.raw_workspace)
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0
    except (ExportError, OSError, UnicodeError, KeyError, TypeError, tarfile.TarError, EOFError) as error:
        print("export_local_packets: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
