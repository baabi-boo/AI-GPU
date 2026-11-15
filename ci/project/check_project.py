#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Validate project structure and evidence metadata, not hardware truth."""

import argparse
import hashlib
import html
import json
from pathlib import Path, PurePosixPath
import re
import string
import sys
from urllib.parse import unquote, urlsplit


LEVELS = ("source_present", "simulated", "rtl_verified", "fpga_measured", "silicon_measured")
STATUSES = ("not_started", "in_progress", "blocked", "complete")
OUTCOMES = ("pass", "fail", "not_run", "blocked")
KIND_LEVELS = {
    "governance": "source_present", "design_review": "source_present",
    "simulation": "simulated", "rtl": "rtl_verified",
    "fpga": "fpga_measured", "silicon": "silicon_measured",
}
IMAGE_PATH = "docs/assets/img/vortex_framework_stack.svg"
IMAGE_SHA256 = "db123c71024f85f379c2504c7465c03ee9df8959a5d17fc3d3e94a94a1cd3aa4"
ROOT_DOCUMENTS = ("README.md", "ROADMAP.md", "CONTRIBUTING.md", "AGENTS.md", "SECURITY.md")
MAX_TEXT_BYTES = 4 * 1024 * 1024
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
HEX40 = re.compile(r"[0-9a-fA-F]{40}\Z")
HEX64 = re.compile(r"[0-9a-fA-F]{64}\Z")
PHASE_ID = re.compile(r"P[0-9]{2}\Z")
ACCEPTANCE_ID = re.compile(r"P[0-9]{2}-A[0-9]{2}\Z")


def _object(value, keys, where, errors):
    if not isinstance(value, dict):
        errors.append(f"{where}: expected an object")
        return False
    missing = set(keys) - value.keys()
    extra = value.keys() - set(keys)
    if missing:
        errors.append(f"{where}: missing fields: {', '.join(sorted(missing))}")
    if extra:
        errors.append(f"{where}: unknown fields: {', '.join(sorted(map(str, extra)))}")
    return True


def _string(value, where, errors):
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{where}: expected a nonempty string")
        return False
    return True


def _strings(value, where, errors, nonempty=False):
    if not isinstance(value, list):
        errors.append(f"{where}: expected a list")
        return []
    if nonempty and not value:
        errors.append(f"{where}: must not be empty")
    result = []
    for index, item in enumerate(value):
        if _string(item, f"{where}[{index}]", errors):
            if item in result:
                errors.append(f"{where}: duplicate value {item!r}")
            else:
                result.append(item)
    return result


def _inside(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _repo_path(value, root, where, errors, kind="file"):
    if not _string(value, where, errors):
        return None
    if (PurePosixPath(value).is_absolute() or "\\" in value or ":" in value
            or any(part in ("", ".", "..") for part in value.split("/"))
            or any(char in value for char in ("\x00", "#", "?"))):
        errors.append(f"{where}: requires a canonical repository-relative path")
        return None
    try:
        path = (root / value).resolve()
        if not _inside(path, root):
            errors.append(f"{where}: path escapes repository")
            return None
        valid = path.is_file() if kind == "file" else path.exists()
        if not valid:
            errors.append(f"{where}: missing {kind}: {value}")
            return None
        return path
    except (OSError, RuntimeError, ValueError) as exc:
        errors.append(f"{where}: cannot resolve path ({type(exc).__name__})")
        return None


def _read_text(path, where, errors):
    try:
        if path.stat().st_size > MAX_TEXT_BYTES:
            errors.append(f"{where}: text exceeds {MAX_TEXT_BYTES} bytes")
            return None
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        errors.append(f"{where}: cannot read UTF-8 text ({type(exc).__name__})")
        return None


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(f"non-finite JSON number {value}")


def _load_json(path, where, errors):
    text = _read_text(path, where, errors)
    if text is None:
        return None
    try:
        data = json.loads(text, object_pairs_hook=_unique_object,
                          parse_constant=_reject_constant)
        if not isinstance(data, dict):
            errors.append(f"{where}: JSON root must be an object")
            return None
        return data
    except (ValueError, RecursionError) as exc:
        errors.append(f"{where}: invalid JSON ({exc})")
        return None


def _checksum(path, where, errors):
    try:
        if path.stat().st_size > MAX_ARTIFACT_BYTES:
            errors.append(f"{where}: artifact exceeds compact-evidence limit of {MAX_ARTIFACT_BYTES} bytes")
            return None
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError as exc:
        errors.append(f"{where}: cannot hash artifact ({type(exc).__name__})")
        return None


def _artifact(value, root, where, errors):
    if not _object(value, ("path", "sha256"), where, errors):
        return
    path = _repo_path(value.get("path"), root, where + ".path", errors)
    digest = value.get("sha256")
    if not isinstance(digest, str) or not HEX64.fullmatch(digest):
        errors.append(f"{where}.sha256: expected a 64-hex SHA-256")
    elif path is not None:
        actual = _checksum(path, where, errors)
        if actual is not None and actual != digest.lower():
            errors.append(f"{where}: SHA-256 mismatch for {value['path']}")


def _schema_version(data, where, errors):
    if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        errors.append(f"{where}.schema_version: expected integer 1")


def _revision(value, where, errors):
    if (not isinstance(value, str) or not HEX40.fullmatch(value)
            or value == "0" * 40):
        errors.append(f"{where}: expected a full nonzero 40-hex commit identifier")


def _validate_report(data, root, where, acceptance_ids, errors):
    keys = ("schema_version", "record_id", "kind", "outcome", "evidence_level",
            "scope", "source_revision", "configuration", "acceptance_ids",
            "commands", "artifacts", "limitations", "reviewer")
    if not _object(data, keys, where, errors):
        return
    _schema_version(data, where, errors)
    for key in ("record_id", "scope", "configuration", "reviewer"):
        _string(data.get(key), where + "." + key, errors)
    _revision(data.get("source_revision"), where + ".source_revision", errors)
    kind, level, outcome = data.get("kind"), data.get("evidence_level"), data.get("outcome")
    if not isinstance(kind, str) or kind not in (*KIND_LEVELS, "release"):
        errors.append(f"{where}.kind: unsupported report kind")
    elif kind in KIND_LEVELS and level != KIND_LEVELS[kind]:
        errors.append(f"{where}: kind {kind} requires evidence level {KIND_LEVELS[kind]}")
    if level not in LEVELS:
        errors.append(f"{where}.evidence_level: unsupported evidence level")
    if outcome not in OUTCOMES:
        errors.append(f"{where}.outcome: unsupported outcome")
    ids = _strings(data.get("acceptance_ids"), where + ".acceptance_ids", errors, nonempty=True)
    for criterion in ids:
        if criterion not in acceptance_ids:
            errors.append(f"{where}: unknown acceptance ID {criterion}")
    _strings(data.get("limitations"), where + ".limitations", errors)

    commands = data.get("commands")
    passing_commands = 0
    if not isinstance(commands, list):
        errors.append(f"{where}.commands: expected a list")
    else:
        for index, command in enumerate(commands):
            context = f"{where}.commands[{index}]"
            if not _object(command, ("command", "result", "exit_code"), context, errors):
                continue
            _string(command.get("command"), context + ".command", errors)
            result, code = command.get("result"), command.get("exit_code")
            if result not in OUTCOMES:
                errors.append(f"{context}.result: unsupported outcome")
            if code is not None and type(code) is not int:
                errors.append(f"{context}.exit_code: expected an integer or null")
            if result == "pass":
                if type(code) is not int or code != 0:
                    errors.append(f"{context}: passing command requires exit code 0")
                else:
                    passing_commands += 1
            elif result == "fail" and type(code) is not int:
                errors.append(f"{context}: failed command requires its observed integer exit code")
            elif result == "not_run" and code is not None:
                errors.append(f"{context}: unexecuted command requires null exit code")
            if outcome == "pass" and result != "pass":
                errors.append(f"{context}: passing report cannot contain a non-passing command")

    artifacts = data.get("artifacts")
    if not isinstance(artifacts, list):
        errors.append(f"{where}.artifacts: expected a list")
    else:
        seen = set()
        for index, artifact in enumerate(artifacts):
            _artifact(artifact, root, f"{where}.artifacts[{index}]", errors)
            if isinstance(artifact, dict) and isinstance(artifact.get("path"), str):
                if artifact["path"] in seen:
                    errors.append(f"{where}.artifacts: duplicate artifact path {artifact['path']}")
                seen.add(artifact["path"])
    if outcome == "pass":
        if not passing_commands:
            errors.append(f"{where}: passing report requires a passing command")
        if not isinstance(artifacts, list) or not artifacts:
            errors.append(f"{where}: passing report requires a hash-checked artifact")
        reviewer = data.get("reviewer")
        if (not isinstance(reviewer, str) or reviewer.strip().lower() in
                ("pending", "tbd", "unknown", "none", "n/a", "")
                or "replace_with" in reviewer.lower()):
            errors.append(f"{where}: passing report requires an actual non-pending reviewer")


def _without_fences(text):
    lines, fence, list_indents = [], None, []
    paragraph, html_block, quote_depth = False, False, 0
    text = re.sub(r"<!--.*?-->", lambda match: re.sub(r"[^\r\n]", " ", match[0]),
                  text, flags=re.DOTALL)
    for raw_line in text.splitlines(keepends=True):
        line = raw_line.expandtabs(4)
        if fence is not None:
            marker, depth, indent = fence
            content = line
            for _ in range(depth):
                quote = re.match(r"^ {0,3}> ?", content)
                if quote is None:
                    break
                content = content[quote.end():]
            else:
                if not content.strip() or len(content) - len(content.lstrip(" ")) >= indent:
                    match = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", content[indent:])
                    if (match and match[1][0] == marker[0] and len(match[1]) >= len(marker)
                            and not match[2].strip()):
                        fence = None
                    lines.append("\n")
                    continue
            fence = None
        depth = 0
        while (quote := re.match(r"^ {0,3}> ?", line)) is not None:
            line = line[quote.end():]
            depth += 1
        if depth != quote_depth:
            paragraph, html_block, list_indents = False, False, []
            quote_depth = depth
        if not line.strip():
            paragraph, html_block = False, False
            lines.append("\n")
            continue
        if html_block:
            lines.append(line)
            continue
        indent = len(line) - len(line.lstrip(" "))
        while list_indents and indent < list_indents[-1]:
            list_indents.pop()
        base = list_indents[-1] if list_indents else 0
        item = re.match(r"^ {0,3}(?:[-+*]|[0-9]{1,9}[.)])( {1,4})(?=\S)", line[base:])
        if item:
            base += item.end()
            list_indents.append(base)
            paragraph = False
        content = line[base:]
        # Indentation cannot interrupt a paragraph, and is relative to list content.
        if content.startswith("    ") and not paragraph:
            lines.append("\n")
            continue
        match = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", content)
        if match:
            fence = (match[1], depth, base)
            paragraph = False
            lines.append("\n")
            continue
        tag = re.match(r"^ {0,3}</?([a-z][a-z0-9-]*)(?:\s|/?>|$)", content, re.IGNORECASE)
        if tag and tag[1].lower() in {
                "address", "article", "aside", "base", "basefont", "blockquote", "body",
                "caption", "center", "col", "colgroup", "dd", "details", "dialog", "dir",
                "div", "dl", "dt", "fieldset", "figcaption", "figure", "footer", "form",
                "frame", "frameset", "h1", "h2", "h3", "h4", "h5", "h6", "head", "header",
                "hr", "html", "iframe", "legend", "li", "link", "main", "menu", "menuitem",
                "nav", "noframes", "ol", "optgroup", "option", "p", "param", "search",
                "section", "summary", "table", "tbody", "td", "tfoot", "th", "thead",
                "title", "tr", "track", "ul"}:
            html_block = True
        paragraph = not html_block and not re.match(
            r"^ {0,3}(?:#{1,6}(?:\s|$)|(?:=+|-+)\s*$|(?:\*\s*){3,}$|(?:_\s*){3,}$|\[[^\]\n]+\]:)",
            content)
        lines.append(content)
    return "".join(lines)


def _escaped(text, index):
    count = 0
    while index > 0 and text[index - 1] == "\\":
        count += 1
        index -= 1
    return count % 2 == 1


def _markdown_unescape(value):
    return re.sub(r"\\([" + re.escape(string.punctuation) + r"])", r"\1", value)


def _inline_destination(text, opening):
    index = opening + 1
    while index < len(text) and text[index].isspace():
        index += 1
    if index == len(text):
        return None
    if text[index] == "<":
        start = index + 1
        index = start
        while index < len(text):
            if text[index] in "\r\n" or (text[index] == "<" and not _escaped(text, index)):
                return None
            if text[index] == ">" and not _escaped(text, index):
                break
            index += 1
        if index == len(text):
            return None
        destination = text[start:index]
        index += 1
    else:
        start, depth = index, 0
        while index < len(text):
            char = text[index]
            if char == "\\" and index + 1 < len(text):
                index += 2
                continue
            if char == "(":
                depth += 1
            elif char == ")":
                if depth == 0:
                    return _markdown_unescape(text[start:index]), index + 1
                depth -= 1
            elif char.isspace():
                break
            elif char == "<":
                return None
            index += 1
        if depth:
            return None
        destination = text[start:index]

    before_space = index
    while index < len(text) and text[index].isspace():
        index += 1
    if index < len(text) and text[index] == ")":
        return _markdown_unescape(destination), index + 1
    if index == before_space or index == len(text) or text[index] not in "\"'(":
        return None
    delimiter = ")" if text[index] == "(" else text[index]
    index += 1
    while index < len(text):
        if text[index] == delimiter and not _escaped(text, index):
            break
        if delimiter == ")" and text[index] == "(" and not _escaped(text, index):
            return None
        index += 1
    if index == len(text):
        return None
    index += 1
    while index < len(text) and text[index].isspace():
        index += 1
    if index < len(text) and text[index] == ")":
        return _markdown_unescape(destination), index + 1
    return None


def _visible_markdown(text):
    return re.sub(r"(`+).*?\1", "", _without_fences(text), flags=re.DOTALL)


def _reference_name(label):
    return " ".join(label.casefold().split())


def _reference_definitions(text):
    definitions = {}
    for match in re.finditer(r"^ {0,3}\[((?:\\.|[^\]\\\n])+)\]:\s*<?([^\s>]+)>?", text, re.MULTILINE):
        definitions.setdefault(_reference_name(match[1]), _markdown_unescape(match[2]))
    return definitions


def _markdown_targets(text, definitions):
    labels, pairs = [], []
    for index, char in enumerate(text):
        if char not in "[]" or _escaped(text, index):
            continue
        if char == "[":
            labels.append(index)
        elif labels:
            pairs.append((labels.pop(), index))
    endings = dict(pairs)
    skip_start = skip_end = -1
    for opening, closing in pairs:
        if skip_start <= opening < skip_end:
            continue
        image = opening > 0 and text[opening - 1] == "!" and not _escaped(text, opening - 1)
        following = closing + 1
        if following < len(text) and text[following] == "(":
            inline = _inline_destination(text, following)
            if inline is not None:
                destination, skip_end = inline
                skip_start = following
                yield image, destination, None
                continue
        label = text[opening + 1:closing]
        if following in endings:
            reference = text[following + 1:endings[following]] or label
            skip_start, skip_end = following, endings[following] + 1
            yield image, definitions.get(_reference_name(reference)), reference
        elif _reference_name(label) in definitions:
            yield image, definitions[_reference_name(label)], label


def _html_tags(text):
    for match in re.finditer(r"<([A-Za-z][A-Za-z0-9:-]*)\b(?:[^<>\"']|\"[^\"]*\"|'[^']*')*>", text):
        if not _escaped(text, match.start()):
            yield match[1].lower(), match[0]


def _html_attributes(tag, names):
    return re.findall(r"\s(?:" + names + r")\s*=\s*[\"']([^\"']+)[\"']", tag, re.IGNORECASE)


def _links(text):
    text = _visible_markdown(text)
    definitions = _reference_definitions(text)
    links = [destination for _, destination, _ in _markdown_targets(text, definitions)
             if destination is not None]
    links.extend(definitions.values())
    for _, tag in _html_tags(text):
        links.extend(_html_attributes(tag, "href|src"))
    return links


def _anchors(text):
    text = _without_fences(text)
    anchors = set(re.findall(r"\b(?:id|name)\s*=\s*[\"']([^\"']+)[\"']", text))
    seen = {}
    headings = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = re.match(r"^ {0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
        if match:
            headings.append(match.group(1))
        elif index and re.fullmatch(r" {0,3}(?:=+|-+)\s*", line) and lines[index - 1].strip():
            headings.append(lines[index - 1].strip())
    for heading in headings:
        heading = re.sub(r"<[^>]*>", "", heading)
        heading = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", heading)
        slug = re.sub(r"[^\w\-\s]", "", html.unescape(heading).lower())
        slug = re.sub(r"\s", "-", slug)
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        anchors.add(slug + (f"-{count}" if count else ""))
    return anchors


def _image_embedded(text, image_path):
    text = _visible_markdown(text)
    for name, tag in _html_tags(text):
        if name == "img" and image_path in _html_attributes(tag, "src"):
            return True
    return any(image and destination == image_path for image, destination, _ in
               _markdown_targets(text, _reference_definitions(text)))


def validate_roadmap(data, root):
    """Return structural errors for a roadmap and its referenced local evidence."""
    errors = []
    try:
        root = Path(root).resolve()
        if not root.is_dir():
            return ["roadmap: project root is not a directory"]
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return [f"roadmap: invalid project root ({type(exc).__name__})"]
    keys = ("schema_version", "project", "repository", "default_branch", "baseline_commit",
            "evidence_levels", "status_values", "protected_assets", "required_documents", "phases")
    if not _object(data, keys, "roadmap", errors):
        return errors
    _schema_version(data, "roadmap", errors)
    for key in ("project", "repository", "default_branch"):
        _string(data.get(key), "roadmap." + key, errors)
    _revision(data.get("baseline_commit"), "roadmap.baseline_commit", errors)
    if data.get("evidence_levels") != list(LEVELS):
        errors.append("roadmap.evidence_levels: must match the canonical ordered vocabulary")
    if data.get("status_values") != list(STATUSES):
        errors.append("roadmap.status_values: must match the canonical vocabulary")
    for path in _strings(data.get("required_documents"), "roadmap.required_documents", errors, True):
        _repo_path(path, root, "roadmap.required_documents", errors)

    assets = data.get("protected_assets")
    if not isinstance(assets, list) or not assets:
        errors.append("roadmap.protected_assets: expected a nonempty list")
    else:
        seen_assets = set()
        readme_path = _repo_path("README.md", root, "README.md", errors)
        readme = _read_text(readme_path, "README.md", errors) if readme_path else None
        for index, asset in enumerate(assets):
            _artifact(asset, root, f"roadmap.protected_assets[{index}]", errors)
            if isinstance(asset, dict) and isinstance(asset.get("path"), str):
                path = asset["path"]
                if path in seen_assets:
                    errors.append(f"roadmap.protected_assets: duplicate asset {path}")
                seen_assets.add(path)
                if readme is not None and not _image_embedded(readme, path):
                    errors.append(f"README.md: protected image is not embedded: {path}")

    phases = data.get("phases")
    if not isinstance(phases, list) or not phases:
        errors.append("roadmap.phases: expected a nonempty list")
        return errors
    phase_map, criteria, dependencies = {}, {}, {}
    phase_keys = ("id", "title", "status", "depends_on", "accountable_role", "goal",
                  "document", "acceptance", "evidence")
    for index, phase in enumerate(phases):
        where = f"roadmap.phases[{index}]"
        if not _object(phase, phase_keys, where, errors):
            continue
        phase_id = phase.get("id")
        if not isinstance(phase_id, str) or not PHASE_ID.fullmatch(phase_id):
            errors.append(f"{where}.id: expected P followed by two digits")
            continue
        if phase_id in phase_map:
            errors.append(f"{where}: duplicate phase ID {phase_id}")
            continue
        phase_map[phase_id] = phase
        for key in ("title", "accountable_role", "goal"):
            _string(phase.get(key), phase_id + "." + key, errors)
        if phase.get("status") not in STATUSES:
            errors.append(f"{phase_id}.status: unsupported status")
        dependencies[phase_id] = _strings(phase.get("depends_on"), phase_id + ".depends_on", errors)
        _repo_path(phase.get("document"), root, phase_id + ".document", errors)
        acceptance = phase.get("acceptance")
        if not isinstance(acceptance, list) or not acceptance:
            errors.append(f"{phase_id}.acceptance: expected a nonempty list")
            continue
        for number, criterion in enumerate(acceptance):
            context = f"{phase_id}.acceptance[{number}]"
            if not _object(criterion, ("id", "criterion", "verification", "evidence_level"), context, errors):
                continue
            criterion_id = criterion.get("id")
            if (not isinstance(criterion_id, str) or not ACCEPTANCE_ID.fullmatch(criterion_id)
                    or not criterion_id.startswith(phase_id + "-")):
                errors.append(f"{context}.id: expected {phase_id}-A followed by two digits")
                continue
            if criterion_id in criteria:
                errors.append(f"{context}: duplicate acceptance ID {criterion_id}")
            else:
                criteria[criterion_id] = criterion
            for key in ("criterion", "verification"):
                _string(criterion.get(key), context + "." + key, errors)
            if criterion.get("evidence_level") not in LEVELS:
                errors.append(f"{context}.evidence_level: unsupported evidence level")

    for phase_id, deps in dependencies.items():
        for dependency in deps:
            if dependency not in phase_map:
                errors.append(f"{phase_id}: unknown dependency {dependency}")
            elif phase_map[phase_id].get("status") == "complete" and phase_map[dependency].get("status") != "complete":
                errors.append(f"{phase_id}: complete phase has incomplete dependency {dependency}")
    visited, active = set(), set()

    def visit(phase_id):
        if phase_id in active:
            errors.append(f"{phase_id}: dependency cycle detected")
            return
        if phase_id in visited:
            return
        active.add(phase_id)
        for dependency in dependencies.get(phase_id, []):
            if dependency in phase_map:
                visit(dependency)
        active.remove(phase_id)
        visited.add(phase_id)

    for phase_id in phase_map:
        visit(phase_id)

    reports, record_ids = {}, {}
    for phase_id, phase in phase_map.items():
        references = phase.get("evidence")
        if not isinstance(references, list):
            errors.append(f"{phase_id}.evidence: expected a list")
            references = []
        covered, seen_references = set(), set()
        for index, reference in enumerate(references):
            where = f"{phase_id}.evidence[{index}]"
            if not _object(reference, ("acceptance_id", "record"), where, errors):
                continue
            criterion_id = reference.get("acceptance_id")
            if (not isinstance(criterion_id, str) or criterion_id not in criteria
                    or not criterion_id.startswith(phase_id + "-")):
                errors.append(f"{where}: reference must name an acceptance ID in {phase_id}")
                continue
            path = _repo_path(reference.get("record"), root, where + ".record", errors)
            if path is None:
                continue
            if path.name.endswith(".example.json"):
                errors.append(f"{where}: an example template cannot be phase evidence")
                continue
            pair = (criterion_id, path)
            if pair in seen_references:
                errors.append(f"{where}: duplicate evidence reference")
            seen_references.add(pair)
            if path not in reports:
                before = len(errors)
                report = _load_json(path, reference["record"], errors)
                if report is not None:
                    _validate_report(report, root, reference["record"], criteria, errors)
                if isinstance(report, dict) and isinstance(report.get("record_id"), str):
                    record_id = report["record_id"]
                    if record_id in record_ids and record_ids[record_id] != path:
                        errors.append(f"{where}: duplicate record_id {record_id}")
                    record_ids[record_id] = path
                reports[path] = (report, len(errors) == before)
            report, valid = reports[path]
            if not isinstance(report, dict):
                continue
            report_ids = report.get("acceptance_ids")
            if not isinstance(report_ids, list) or criterion_id not in report_ids:
                errors.append(f"{where}: report does not cover {criterion_id}")
                continue
            required = criteria[criterion_id].get("evidence_level")
            supplied = report.get("evidence_level")
            compatible = required in LEVELS and supplied in LEVELS and LEVELS.index(supplied) >= LEVELS.index(required)
            if not compatible:
                errors.append(f"{where}: evidence level is insufficient for {criterion_id}")
            if valid and compatible and report.get("outcome") == "pass":
                covered.add(criterion_id)
        if phase.get("status") == "complete":
            for criterion_id in criteria:
                if criterion_id.startswith(phase_id + "-") and criterion_id not in covered:
                    errors.append(f"{phase_id}: complete phase lacks passing evidence for {criterion_id}")
    return errors


def _owned_markdown(root):
    paths = [root / name for name in ROOT_DOCUMENTS]
    paths.extend(sorted((root / "docs/project").rglob("*.md")))
    paths.append(root / "docs/index.md")
    return list(dict.fromkeys(paths))


def _validate_links(root, errors):
    anchor_cache = {}
    for source in _owned_markdown(root):
        relative = source.relative_to(root).as_posix()
        path = _repo_path(relative, root, relative, errors)
        if path is None:
            continue
        text = _read_text(path, relative, errors)
        if text is None:
            continue
        if relative == "AGENTS.md":
            text = text.split("## 1. Documentation Map", 1)[0]
        if relative != "docs/index.md":
            visible = _visible_markdown(text)
            definitions = _reference_definitions(visible)
            for _, destination, reference in _markdown_targets(visible, definitions):
                if reference is not None and destination is None:
                    errors.append(f"{relative}: undefined Markdown link reference: {reference}")
        for link in _links(text):
            try:
                parts = urlsplit(html.unescape(link))
                if parts.scheme or parts.netloc:
                    continue
                destination = unquote(parts.path)
                if "\\" in destination or "\x00" in destination or destination.startswith("/"):
                    errors.append(f"{relative}: unsafe local link {link!r}")
                    continue
                target = (source.parent / destination).resolve() if destination else path
                if not _inside(target, root):
                    errors.append(f"{relative}: local link escapes repository: {link}")
                    continue
                target_name = target.relative_to(root).as_posix()
                is_project = target_name.startswith("docs/project/") or target_name in ROOT_DOCUMENTS
                if relative == "docs/index.md" and not is_project:
                    continue
                if not target.exists():
                    errors.append(f"{relative}: broken local link: {link}")
                    continue
                if parts.fragment and is_project and target.suffix.lower() == ".md" and target.is_file():
                    if target not in anchor_cache:
                        target_text = _read_text(target, target_name, errors)
                        anchor_cache[target] = _anchors(target_text) if target_text is not None else set()
                    fragment = unquote(parts.fragment)
                    if fragment not in anchor_cache[target]:
                        errors.append(f"{relative}: broken Markdown anchor: {link}")
            except (OSError, RuntimeError, ValueError) as exc:
                errors.append(f"{relative}: invalid local link {link!r} ({type(exc).__name__})")


def validate_project(root):
    """Return errors for the complete checkout without changing or executing it."""
    errors = []
    try:
        root = Path(root).resolve()
        if not root.is_dir():
            return ["project root is not a directory"]
        path = _repo_path("docs/project/roadmap.json", root, "roadmap", errors)
        data = _load_json(path, "roadmap", errors) if path else None
        if data is not None:
            errors.extend(validate_roadmap(data, root))
        _artifact({"path": IMAGE_PATH, "sha256": IMAGE_SHA256}, root, "original README image", errors)
        if isinstance(data, dict):
            assets = data.get("protected_assets")
            if not isinstance(assets, list) or {"path": IMAGE_PATH, "sha256": IMAGE_SHA256} not in assets:
                errors.append("roadmap.protected_assets: original README image protection is missing or changed")
        _validate_links(root, errors)
    except (OSError, RuntimeError, ValueError, TypeError) as exc:
        errors.append(f"project validation could not complete ({type(exc).__name__}: {exc})")
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2],
                        help="repository source root (default: this script's checkout)")
    args = parser.parse_args(argv)
    errors = validate_project(args.root)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        print(f"Project governance validation failed: {len(errors)} error(s).", file=sys.stderr)
        return 1
    print("Project governance validation passed (structure and metadata only; no GPU execution certified).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
