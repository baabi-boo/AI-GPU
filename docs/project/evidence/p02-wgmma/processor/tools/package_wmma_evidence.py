#!/usr/bin/env python3
"""Plan, package, or verify a bounded UTF-8 evidence export without editing inputs."""

import argparse
import fnmatch
import gzip
import hashlib
import html
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tempfile
from urllib.parse import unquote, urlsplit, parse_qsl


MIB = 1024 * 1024
LIMITS = {
    "member_bytes": 16 * MIB,
    "total_original_bytes": 64 * MIB,
    "total_published_bytes": 64 * MIB,
    "members": 4096,
    "expanded_bundle_bytes": 96 * MIB,
    "compressed_bundle_bytes": 4 * MIB,
}
DIGEST_POLICY = (
    "original_sha256 and original_size_bytes identify the exact retained input bytes. "
    "published_sha256 and published_size_bytes identify content.encode('utf-8') after "
    "literal path-prefix substitution only. Every pre-existing digest or size inside "
    "embedded records still describes ORIGINAL bytes and is never recomputed or "
    "rewritten. Verify published members with their published fields; verifying "
    "original fields requires the retained originals. An unchanged member has equal "
    "original and published bytes, sizes, and hashes."
)
SCOPE = (
    "Text evidence packaging only. Completed execution packets, historical failures, "
    "logs and reviews retain their individual scope. This export grants no acceptance "
    "and makes no execution, numerical, hardware, or phase-completion decision."
)
AUDIT_LIMITS = [
    "Original-byte checking covers every selected member, not excluded binaries, tools, "
    "build trees, third-party header bodies, or all dependencies named by records.",
    "Excluded directory entries are pruning roots; their descendants are not inventoried.",
    "Embedded binding checks cover recognized path/hash pairs that resolve to selected "
    "members; external and deliberately excluded references are counted separately. "
    "Explicit live_file_snapshot_only observations retain their historical digest and "
    "are listed separately instead of being asserted to identify the finished file.",
    "Private-key and signed-URL scans are bounded pattern checks, not a complete secret "
    "or redistribution-rights audit.",
    "A completed-report marker does not certify result correctness or acceptance.",
    "Digest consistency checks integrity against this inventory; no signature or origin "
    "authentication is established by the exporter.",
    "Planning is a point-in-time observation. Re-run after all execution and review "
    "writers stop; build re-reads every selected input before publication.",
    "Deterministic bytes require identical inputs, selection, helper and Python/zlib "
    "compression implementation; gzip timestamps and filenames are fixed.",
]
DEFAULT_SELECTION = {
    "schema_version": 1,
    "inputs": [
        {"path": "formal-matrix-packet", "required": True,
         "completed_report": "formal-matrix-packet/report.json"},
        {"path": "formal-api", "required": True,
         "completed_report": "formal-api/report.json"},
        {"path": "dev-matrix-packet", "required": True,
         "completed_report": "dev-matrix-packet/report.json"},
        {"path": "dev-matrix-v2-packet", "required": True,
         "completed_report": "dev-matrix-v2-packet/report.json"},
        {"path": "w03-simx-selector-evidence", "required": True},
        {"path": "reports", "required": True},
        {"path": "logs", "required": True},
        {"path": "reviews", "required": True},
        {"path": "bounded_command.py", "required": True},
        {"path": "package_wmma_evidence.py", "required": True},
        {"path": "test_package_wmma_evidence.py", "required": True},
        {"path": "wmma-evidence-selection.json", "required": False},
    ],
    "required_groups": {
        "offline_report": ["reports/*offline*.json", "reports/*governance*.json"],
        "host_test_report": ["reports/*adapter*.json", "reviews/*adapter*tests.json"],
        "catalog_execution_report": ["reports/*catalog*execution*.json",
                                     "reports/*catalog*rv32*.json",
                                     "reports/*catalog*rv64*.json"],
    },
    "guards": {
        "logs/formal-offline-suite*.log": "reports/formal-offline-suite.json",
    },
    "exclude": [],
}
TEXT_SUFFIXES = {
    ".json", ".log", ".txt", ".md", ".csv", ".tsv", ".yaml", ".yml",
    ".py", ".sh", ".h", ".hpp", ".c", ".cc", ".cpp", ".sv", ".v",
    ".vh", ".mk", ".in", ".toml", ".stamp", ".d", ".vlt", ".s",
    ".diff", ".patch", ".map", ".list", ".cfg", ".ini",
}
TEXT_NAMES = {"Makefile", "makefile", "configure", "VERSION", "LICENSE", "COPYING"}
SKIP_DIRS = {
    ".git", ".cache", "__pycache__", "CMakeFiles", "_deps", "tmp", "temp",
    "tools", "toolchains", "downloads", "host-packages", "host-bin", "cmake-python",
}
HASH = re.compile(r"[0-9a-f]{64}\Z")
PRIVATE_KEY = re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*(?:PRIVATE KEY|PGP PRIVATE KEY BLOCK)-----")
URL = re.compile(r'''https?://[^\s<>"']+''', re.IGNORECASE)
SIGNED_KEYS = {
    "sig", "signature", "x-amz-signature", "x-amz-credential", "x-goog-signature",
    "x-goog-credential", "googleaccessid", "awsaccesskeyid", "access_token",
    "id_token", "api_key", "token",
}


class InvalidEvidence(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise InvalidEvidence(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def relative_name(value):
    require(isinstance(value, str) and value and "\\" not in value,
            "member paths must be nonempty POSIX relative paths")
    path = PurePosixPath(value)
    require(not path.is_absolute() and all(p not in ("", ".", "..") for p in value.split("/")),
            "unsafe member path")
    require(not any(ord(c) < 32 for c in value), "control character in member path")
    return value


def checked_root(value):
    path = Path(os.path.abspath(value))
    for item in (path, *path.parents):
        require(not item.is_symlink(), "symlink in root path")
    require(path.is_dir(), "root directory is missing")
    return path


def read_member(root, name, cap=LIMITS["member_bytes"]):
    """Use no-follow directory descriptors, then reject concurrent byte changes."""
    parts = PurePosixPath(relative_name(name)).parts
    fds = []
    try:
        parent = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        fds.append(parent)
        for part in parts[:-1]:
            parent = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            fds.append(parent)
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        fds.append(fd)
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode), "non-regular member: " + name)
        require(before.st_size <= cap, "member exceeds byte limit: " + name)
        with os.fdopen(os.dup(fd), "rb") as stream:
            data = stream.read(cap + 1)
        after = os.fstat(fd)
        signature = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        require(signature(before) == signature(after) and len(data) == before.st_size,
                "member changed during read: " + name)
        require(len(data) <= cap, "member exceeds byte limit: " + name)
        return data
    finally:
        for fd in reversed(fds):
            os.close(fd)


def scan_text(text, name):
    require(not any(ord(c) < 32 and c not in "\b\t\n\f\r\x1b" for c in text),
            "binary/control-byte member: " + name)
    require(not PRIVATE_KEY.search(text), "private-key marker in member: " + name)
    for url in URL.findall(unquote(text.replace("\\/", "/"))):
        decoded = html.unescape(url.replace("\\u0026", "&"))
        for _ in range(2):
            decoded = unquote(decoded)
        keys = {key.lower() for key, _ in parse_qsl(urlsplit(decoded).query, keep_blank_values=True)}
        require(not keys.intersection(SIGNED_KEYS), "signed/credential URL in member: " + name)


def normalization_rules(work, source, tools):
    mapping = {str(work): "${WORK}", str(source): "${SOURCE}", str(tools): "${TOOLS}"}
    require(len(mapping) == 3, "work, source, and tools roots must be distinct")
    if source.parent == work.parent:
        mapping[str(work.parent)] = "${WORK}/.."
    return sorted(mapping.items(), key=lambda item: (-len(item[0]), item[0]))


def normalize(text, rules):
    counts = {}
    for prefix, label in rules:
        pattern = re.escape(prefix) + r"(?=$|[^A-Za-z0-9_.+\-])"
        text, count = re.subn(pattern, lambda _: label, text)
        if count:
            counts[label] = count
    require(not any(prefix in text for prefix, _ in rules), "unhandled current-workspace path prefix")
    return text, counts


def exclusion(name, directory, custom, retained_includes=()):
    parts = PurePosixPath(name).parts
    if any(fnmatch.fnmatchcase(name, pattern) for pattern in custom):
        return "explicit selection exclusion"
    if any(p in SKIP_DIRS or re.fullmatch(r"builds?(?:[-_].*)?|.*[-_]builds?", p) for p in parts):
        return "tool/build/cache/temporary tree"
    if any(parts[i:i + 2] == ("snapshots", "includes") for i in range(len(parts) - 1)):
        if name not in retained_includes and not (directory and any(n.startswith(name + "/") for n in retained_includes)):
            return "system/resource include bodies; authoritative paths and hashes retained"
    if (not directory and Path(name).suffix.lower() not in TEXT_SUFFIXES
            and Path(name).name not in TEXT_NAMES and not Path(name).name.endswith("-Makefile")
            and name not in retained_includes):
        return "non-allowlisted text type; binaries/archives/waveforms omitted"
    return None


def completed_report(data):
    report = json.loads(data.decode("utf-8"))
    require(isinstance(report, dict), "completion report must be a JSON object")
    if report.get("state") not in (None, "finished", "completed"):
        return False
    if report.get("outcome") in ("running", "pending", "not_run"):
        return False
    for start, end in (("started_at", "finished_at"), ("started_utc", "finished_utc")):
        if start in report and not report.get(end):
            return False
    if report.get("process_started") is True and report.get("exit_code") is None:
        return False
    return bool(report.get("finished_at") or report.get("finished_utc")
                or report.get("state") in ("finished", "completed")
                or (report.get("outcome") in ("pass", "fail", "blocked")
                    and isinstance(report.get("exit_code"), int)))


def validate_selection(selection):
    require(isinstance(selection, dict) and selection.get("schema_version") == 1,
            "selection schema_version must be 1")
    fields = {"schema_version", "inputs", "required_groups", "exclude"}
    require(fields <= set(selection) <= fields | {"guards"}, "unexpected or missing selection keys")
    require(isinstance(selection["inputs"], list) and selection["inputs"], "empty selection")
    require(len(selection["inputs"]) <= 256, "too many input selectors")
    for rule in selection["inputs"]:
        require(isinstance(rule, dict) and set(rule) <= {"path", "required", "completed_report"},
                "unknown input selector field")
        relative_name(rule["path"])
        require(type(rule.get("required", False)) is bool, "required must be boolean")
        if "completed_report" in rule:
            relative_name(rule["completed_report"])
    require(isinstance(selection["required_groups"], dict), "required_groups must be an object")
    for patterns in [selection["exclude"], *selection["required_groups"].values()]:
        require(isinstance(patterns, list) and len(patterns) <= 256, "invalid glob group")
        for pattern in patterns:
            relative_name(pattern)
    require(isinstance(selection.get("guards", {}), dict) and len(selection.get("guards", {})) <= 256,
            "invalid completion guard map")
    for pattern, report in selection.get("guards", {}).items():
        relative_name(pattern)
        relative_name(report)


def collect(work, selection, source=None, tools=None):
    names, missing, deferred, excluded = set(), [], [], {}
    retained_includes = set()
    source, tools = source or work.parent / "AI-GPU", tools or work / "tools"

    def ready(name, gate):
        if not (work / gate).exists() and not (work / gate).is_symlink():
            reason = "completion report missing"
        elif not completed_report(read_member(work, gate)):
            reason = "execution report unfinished"
        else:
            return True
        deferred.append({"path": name, "report": gate, "reason": reason})
        return False

    def walk(name):
        path = work / name
        info = path.lstat()
        require(not stat.S_ISLNK(info.st_mode), "symlink in selected tree: " + name)
        directory = stat.S_ISDIR(info.st_mode)
        why = exclusion(name, directory, selection["exclude"], retained_includes)
        if why:
            excluded[name] = why
        elif directory:
            for child in sorted(path.iterdir(), key=lambda p: p.name):
                walk(name + "/" + child.name)
        else:
            require(stat.S_ISREG(info.st_mode), "non-regular selected input: " + name)
            for pattern, gate in selection.get("guards", {}).items():
                if fnmatch.fnmatchcase(name, pattern) and not ready(name, gate):
                    return
            names.add(relative_name(name))
            require(len(names) <= LIMITS["members"], "member-count limit exceeded")

    for rule in selection["inputs"]:
        name = rule["path"]
        if not (work / name).exists() and not (work / name).is_symlink():
            if rule.get("required", False):
                missing.append(name)
            continue
        gate = rule.get("completed_report")
        if gate:
            if not ready(name, gate):
                continue
            report = json.loads(read_member(work, gate))
            for item in report.get("include_dependencies", {}).values():
                original, snapshot = Path(item["path"]), Path(item["snapshot"])
                if (not original.is_relative_to(tools)
                        and (original.is_relative_to(source) or original.is_relative_to(work))):
                    require(snapshot.is_relative_to(work), "include snapshot escaped evidence workspace")
                    retained_includes.add(relative_name(snapshot.relative_to(work).as_posix()))
        walk(name)
        if rule.get("required", False) and not any(n == name or n.startswith(name + "/") for n in names):
            missing.append("empty:" + name)
    for group, patterns in sorted(selection["required_groups"].items()):
        if not any(fnmatch.fnmatchcase(name, pattern) for name in names for pattern in patterns):
            missing.append("group:" + group)
    return (sorted(names), sorted(missing), deferred,
            [{"path": k, "reason": v} for k, v in sorted(excluded.items())], sorted(retained_includes))


def member_metadata(member):
    return {k: v for k, v in member.items() if k != "content"}


def binding_audit(originals, work, selection):
    verified, external = set(), set()
    historical = []
    pairs = (("log", "log_sha256", "log_size_bytes"),
             ("path", "sha256", "size_bytes"),
             ("snapshot", "sha256", "size_bytes"),
             ("source", "source_sha256", None),
             ("record", "record_sha256", None))

    def visit(node, owner):
        if isinstance(node, list):
            for value in node:
                visit(value, owner)
        elif isinstance(node, dict):
            for path_key, hash_key, size_key in pairs:
                value, digest = node.get(path_key), node.get(hash_key)
                if not isinstance(value, str) or not isinstance(digest, str) or not HASH.fullmatch(digest):
                    continue
                path = Path(value)
                candidates = [str(path)] if path.is_absolute() else [
                    str(Path(owner).parent / path), str(work / path)]
                candidates = [os.path.normpath(candidate) for candidate in candidates]
                targets = [candidate for candidate in candidates if candidate in originals]
                if path_key == "path" and node.get("live_file_snapshot_only") is True:
                    target = targets[0] if targets else None
                    historical.append({"record": Path(owner).relative_to(work).as_posix(),
                                       "target_member": Path(target).relative_to(work).as_posix() if target else None,
                                       "observed_sha256": digest,
                                       "selected_original_sha256": sha(originals[target]) if target else None,
                                       "meaning": "historical live-file observation; not a binding to current bytes"})
                    continue
                if not targets:
                    if path_key == "log":
                        expected = Path(candidates[0])
                        if expected.is_relative_to(work):
                            local_name = expected.relative_to(work).as_posix()
                            require(exclusion(local_name, False, selection["exclude"]) is not None,
                                    "referenced original log is not selected: " + local_name)
                    external.add((owner, path_key, value, digest))
                    continue
                require(len(set(targets)) == 1, "ambiguous embedded binding in " + owner)
                target = targets[0]
                raw = originals[target]
                require(sha(raw) == digest, "embedded original digest mismatch in " + owner)
                if size_key and size_key in node:
                    require(node[size_key] == len(raw), "embedded original size mismatch in " + owner)
                verified.add((owner, path_key, target, digest))
            for value in node.values():
                visit(value, owner)

    for name, raw in originals.items():
        if name.endswith(".json"):
            visit(json.loads(raw.decode("utf-8")), name)
    return {"recognized_original_bindings_verified": len(verified),
            "recognized_external_or_excluded_bindings_not_verified": len(external),
            "historical_live_file_observations": historical}


def make_bundle(work, source, tools, selection):
    validate_selection(selection)
    names, missing, deferred, excluded, retained_includes = collect(work, selection, source, tools)
    rules = normalization_rules(work, source, tools)
    members, originals = [], {}
    original_total = published_total = 0
    for name in names:
        raw = read_member(work, name)
        original_total += len(raw)
        require(original_total <= LIMITS["total_original_bytes"], "total original-byte limit exceeded")
        text = raw.decode("utf-8", errors="strict")
        scan_text(text, name)
        published, substitutions = normalize(text, rules)
        scan_text(published, name)
        body = published.encode("utf-8")
        published_total += len(body)
        require(len(body) <= LIMITS["member_bytes"], "published member limit exceeded: " + name)
        require(published_total <= LIMITS["total_published_bytes"], "total published-byte limit exceeded")
        members.append({"path": name, "encoding": "utf-8", "original_sha256": sha(raw),
                        "original_size_bytes": len(raw), "published_sha256": sha(body),
                        "published_size_bytes": len(body), "substitutions": substitutions,
                        "content": published})
        originals[str(work / name)] = raw
    bindings = binding_audit(originals, work, selection)
    source_identity = None
    identity_name = "formal-matrix-packet/snapshots/source-before.json"
    if str(work / identity_name) in originals:
        checkout = json.loads(originals[str(work / identity_name)])["checkout"]
        source_identity = {"revision": checkout.get("revision"), "tree": checkout.get("tree"),
                           "source": identity_name, "meaning": "identity recorded by matrix execution"}
    metadata = {
        "schema_version": 1, "format": "normalized-text-evidence-v2", "scope": SCOPE,
        "acceptance_claimed": False, "digest_policy": DIGEST_POLICY,
        "normalization_roles": {"${WORK}": "retained evidence workspace",
                                "${SOURCE}": "tested source checkout",
                                "${TOOLS}": "installed tools root",
                                "${WORK}/..": "workspace parent, when source and work are siblings"},
        "source_identity": source_identity, "limits": LIMITS, "selection": selection,
        "missing_required_inputs": missing, "deferred_inputs": deferred, "excluded_inputs": excluded,
        "retained_project_include_snapshots": retained_includes,
        "audit_limits": AUDIT_LIMITS, "binding_audit": bindings,
    }
    bundle = {**metadata, "files": members}
    expanded = json_bytes(bundle)
    require(len(expanded) <= LIMITS["expanded_bundle_bytes"], "expanded-bundle limit exceeded")
    target = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=target, compresslevel=9, mtime=0) as stream:
        stream.write(expanded)
    compressed = target.getvalue()
    require(len(compressed) <= LIMITS["compressed_bundle_bytes"], "compressed-bundle limit exceeded")
    inventory = {**metadata, "bundle_path": "evidence-bundle.json.gz", "files": [member_metadata(m) for m in members],
                 "file_count": len(members), "original_total_bytes": original_total,
                 "published_text_bytes": published_total, "bundle_sha256": sha(compressed),
                 "bundle_size_bytes": len(compressed), "uncompressed_bundle_sha256": sha(expanded),
                 "uncompressed_bundle_size_bytes": len(expanded)}
    verify_bytes(compressed, inventory, work, rules)
    require(collect(work, selection, source, tools) == (names, missing, deferred, excluded, retained_includes),
            "input membership or completion status changed during packaging")
    return compressed, inventory


def verify_bytes(compressed, inventory, work=None, rules=None):
    require(len(compressed) <= LIMITS["compressed_bundle_bytes"], "compressed-bundle limit exceeded")
    require(compressed[:4] == b"\x1f\x8b\x08\x00" and compressed[4:8] == b"\0" * 4,
            "gzip header must have no optional fields and mtime zero")
    require(len(compressed) == inventory["bundle_size_bytes"] and sha(compressed) == inventory["bundle_sha256"],
            "compressed bundle identity mismatch")
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
        expanded = stream.read(LIMITS["expanded_bundle_bytes"] + 1)
    require(len(expanded) <= LIMITS["expanded_bundle_bytes"], "expanded-bundle limit exceeded")
    require(len(expanded) == inventory["uncompressed_bundle_size_bytes"]
            and sha(expanded) == inventory["uncompressed_bundle_sha256"], "expanded bundle identity mismatch")
    bundle = json.loads(expanded.decode("utf-8"))
    require(bundle.get("schema_version") == 1 and bundle.get("format") == "normalized-text-evidence-v2"
            and bundle.get("acceptance_claimed") is False and bundle.get("limits") == LIMITS,
            "unsupported bundle contract")
    members = bundle["files"]
    names = [relative_name(m["path"]) for m in members]
    require(names == sorted(set(names)) and len(members) == inventory["file_count"] <= LIMITS["members"],
            "invalid member ordering, duplicates, or count")
    require([member_metadata(m) for m in members] == inventory["files"], "inventory/member metadata mismatch")
    for key, value in bundle.items():
        if key != "files":
            require(inventory.get(key) == value, "inventory/bundle metadata mismatch: " + key)
    original_total = published_total = originals_checked = 0
    for member in members:
        name = member["path"]
        require(exclusion(name, False, bundle["selection"]["exclude"],
                          bundle["retained_project_include_snapshots"]) is None,
                "excluded member in bundle: " + name)
        require(member["encoding"] == "utf-8", "unexpected member encoding")
        require(HASH.fullmatch(member["original_sha256"]) and HASH.fullmatch(member["published_sha256"]),
                "invalid member digest")
        for key in ("original_size_bytes", "published_size_bytes"):
            require(type(member[key]) is int and 0 <= member[key] <= LIMITS["member_bytes"], "member size limit exceeded")
        body = member["content"].encode("utf-8")
        scan_text(member["content"], name)
        require(len(body) == member["published_size_bytes"] and sha(body) == member["published_sha256"],
                "published member identity mismatch: " + name)
        if work is not None:
            raw = read_member(work, name)
            require(len(raw) == member["original_size_bytes"] and sha(raw) == member["original_sha256"],
                    "original member identity mismatch: " + name)
            scan_text(raw.decode("utf-8"), name)
            normalized, counts = normalize(raw.decode("utf-8"), rules)
            require(normalized.encode("utf-8") == body and counts == member["substitutions"],
                    "normalization reproduction mismatch: " + name)
            originals_checked += 1
        original_total += member["original_size_bytes"]
        published_total += len(body)
    require(original_total == inventory["original_total_bytes"] <= LIMITS["total_original_bytes"], "original total mismatch/limit")
    require(published_total == inventory["published_text_bytes"] <= LIMITS["total_published_bytes"], "published total mismatch/limit")
    return {"published_members_verified": len(members), "original_members_verified": originals_checked,
            "bundle_sha256": sha(compressed), "acceptance_claimed": False}


def write_new(path, data):
    for ancestor in (path.parent, *path.parent.parents):
        require(not ancestor.is_symlink(), "symlink in output path")
    path.parent.mkdir(parents=True, exist_ok=True)
    checked_root(path.parent)
    with path.open("xb") as stream:
        stream.write(data)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("selection", "plan", "build", "verify"))
    parser.add_argument("--work", type=Path, default=Path(__file__).absolute().parent)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--tools", type=Path)
    parser.add_argument("--selection", type=Path, help="JSON explicit input roots, completion reports, required globs, exclusions")
    parser.add_argument("--output", type=Path, required=True,
                        help="new file for selection/plan; new directory for build; existing directory for verify")
    parser.add_argument("--published-only", action="store_true", help="verify normalized bytes without retained originals")
    args = parser.parse_args(argv)
    require(not args.published_only or args.mode == "verify", "--published-only is only for verify")
    if args.mode == "verify" and args.published_only:
        output = checked_root(args.output)
        inventory = json.loads(read_member(output, "inventory.json"))
        require(inventory["bundle_path"] == "evidence-bundle.json.gz", "unexpected bundle name")
        compressed = read_member(output, inventory["bundle_path"], LIMITS["compressed_bundle_bytes"])
        print(json.dumps(verify_bytes(compressed, inventory), sort_keys=True))
        return 0
    work = checked_root(args.work)
    source = checked_root(args.source or work.parent / "AI-GPU")
    tools = checked_root(args.tools or work / "tools")
    output = Path(os.path.abspath(args.output))
    if args.mode != "verify":
        require(output.is_relative_to(work) and not output.is_relative_to(source),
                "new output must stay in the evidence workspace and outside source")
    if args.mode == "selection":
        write_new(args.output, json_bytes(DEFAULT_SELECTION))
        print(json.dumps({"selection_written": True, "acceptance_claimed": False}))
        return 0
    rules = normalization_rules(work, source, tools)
    if args.mode == "verify":
        output = checked_root(args.output)
        inventory = json.loads(read_member(output, "inventory.json"))
        require(inventory["bundle_path"] == "evidence-bundle.json.gz", "unexpected bundle name")
        compressed = read_member(output, inventory["bundle_path"], LIMITS["compressed_bundle_bytes"])
        result = verify_bytes(compressed, inventory, work, rules)
        print(json.dumps(result, sort_keys=True))
        return 0
    selection = DEFAULT_SELECTION
    if args.selection:
        selection_file = Path(os.path.abspath(args.selection))
        selection = json.loads(read_member(checked_root(selection_file.parent), selection_file.name))
    validate_selection(selection)
    require(not any((work / rule["path"]).is_dir() and output.is_relative_to(work / rule["path"])
                    for rule in selection["inputs"]), "output cannot be inside a selected input directory")
    compressed, inventory = make_bundle(work, source, tools, selection)
    if args.mode == "plan":
        plan = {**inventory, "mode": "plan", "bundle_written": False,
                "candidate_scope": "completed selected inputs observed now; unfinished packets deferred",
                "publication_ready": not inventory["missing_required_inputs"] and not inventory["deferred_inputs"]}
        write_new(args.output, json_bytes(plan))
    else:
        require(not inventory["missing_required_inputs"] and not inventory["deferred_inputs"],
                "cannot build: missing required inputs or unfinished execution reports; inspect plan")
        checked_root(output.parent)
        require(not output.exists() and not output.is_symlink(), "build output directory must be new")
        with tempfile.TemporaryDirectory(prefix=".wmma-evidence-", dir=output.parent) as temporary:
            stage = Path(temporary)
            write_new(stage / "evidence-bundle.json.gz", compressed)
            write_new(stage / "inventory.json", json_bytes(inventory))
            verify_bytes(read_member(stage, "evidence-bundle.json.gz", LIMITS["compressed_bundle_bytes"]),
                         json.loads(read_member(stage, "inventory.json")), work, rules)
            os.rename(stage, output)
    print(json.dumps({"mode": args.mode, "bundle_written": args.mode == "build",
                      "members_verified": inventory["file_count"], "candidate_gzip_bytes": len(compressed),
                      "missing_required_inputs": inventory["missing_required_inputs"],
                      "deferred_inputs": inventory["deferred_inputs"], "acceptance_claimed": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"error": str(error), "acceptance_claimed": False}), file=sys.stderr)
        raise SystemExit(1)
