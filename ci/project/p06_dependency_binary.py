# SPDX-License-Identifier: Apache-2.0
"""Inspect selected GNU archive and linker-map bytes without executing them."""

from collections import Counter
import hashlib
from pathlib import PurePosixPath
import re

import p06_dependency_contract as contract


MAX_MEMBERS = contract.MAX_RECORDS
MAX_SYMBOLS = 65536
MAX_MAP_LINE_BYTES = 32768
MAX_MAP_LINES = 400000
ARCHIVE_HEADING = "Archive member included to satisfy reference by file (symbol)"
MAP_HEADING = "Linker script and memory map"
NEXT_HEADINGS = frozenset((
    "Merging program properties",
    "As-needed library included to satisfy reference by file (symbol)",
    "Allocating common symbols",
    "Discarded input sections",
    "Memory Configuration",
    MAP_HEADING,
))
_MEMBER = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.+-]{0,254}\Z")
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_PATH = re.compile(r"[A-Za-z0-9_./+-]+\Z")
_SELECTION = re.compile(r"([^\s()]+\.a)\(([^\s()]+)\)(?:[ \t]+(.*))?\Z")
_REFERENCE = re.compile(r"([^\s]+)[ \t]+\((.+)\)\Z")
_CONTRIBUTION = re.compile(
    r"[ \t]+(?:\S+[ \t]+)?0x[0-9a-f]+[ \t]+0x[0-9a-f]+[ \t]+"
    r"([^\s()]+\.a)\(([^\s()]+)\)(?:[ \t]+.*)?\Z")


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _member_name(name):
    _require(type(name) is str and _MEMBER.fullmatch(name) is not None,
             "archive member name is unsafe or unsupported")
    return name


def _number(field, label, *, octal=False, blank=False):
    value = field.rstrip(b" ")
    if blank and not value:
        return 0
    pattern = rb"(?:0|[1-7][0-7]*)" if octal else rb"(?:0|[1-9][0-9]*)"
    _require(re.fullmatch(pattern, value) is not None,
             "archive " + label + " is not a canonical unsigned number")
    return int(value, 8 if octal else 10)


def _long_names(body):
    names, used, position = {}, set(), 0
    while position < len(body):
        if body[position:] == b"\n" and position % 2 == 1:
            break
        end = body.find(b"/\n", position)
        _require(end >= position, "archive long-name table is malformed")
        try:
            name = _member_name(body[position:end].decode("ascii"))
        except UnicodeError as error:
            raise ValueError("archive long-name table is not ASCII") from error
        _require(name not in used, "archive long-name table contains duplicate names")
        _require(len(names) < MAX_MEMBERS, "archive long-name table exceeds its member bound")
        names[position] = name
        used.add(name)
        position = end + 2
    _require(names and len(body) % 2 == 0, "archive long-name table is empty or misaligned")
    return names


def _symbol_table(body, width, member_offsets):
    _require(len(body) >= width, "archive symbol table is truncated")
    count = int.from_bytes(body[:width], "big")
    _require(count <= MAX_SYMBOLS and width * (count + 1) <= len(body),
             "archive symbol table exceeds its count or byte bounds")
    for index in range(count):
        start = width * (index + 1)
        offset = int.from_bytes(body[start:start + width], "big")
        _require(offset in member_offsets, "archive symbol points outside an object member")
    names = body[width * (count + 1):]
    position = 0
    for _ in range(count):
        end = names.find(b"\0", position)
        _require(end > position, "archive symbol name is empty or unterminated")
        _require(all(32 <= value < 127 for value in names[position:end]),
                 "archive symbol name contains unsupported bytes")
        position = end + 1
    _require(names[position:] in (b"", b"\0"), "archive symbol table has trailing data")
    return count


def parse_archive(data):
    """Return ordered object identities from one bounded ordinary GNU archive."""
    _require(type(data) is bytes and 8 <= len(data) <= contract.MAX_FILE_BYTES,
             "archive must be bounded immutable bytes")
    _require(not data.startswith(b"!<thin>\n"), "thin archives are forbidden")
    _require(data.startswith(b"!<arch>\n"), "archive magic is invalid")
    position, header_count = 8, 0
    members, offsets, seen_names = [], set(), set()
    long_names, used_long_names, symbols = None, set(), None
    while position < len(data):
        header_count += 1
        _require(header_count <= MAX_MEMBERS + 2, "archive exceeds its member bound")
        _require(position + 60 <= len(data), "archive member header is truncated")
        header_offset = position
        header = data[position:position + 60]
        _require(header[58:60] == b"`\n", "archive member header terminator is invalid")
        try:
            name = header[:16].rstrip(b" ").decode("ascii")
        except UnicodeError as error:
            raise ValueError("archive member header is not ASCII") from error
        metadata = name in ("/", "/SYM64/", "//")
        for label, field, octal in (("timestamp", header[16:28], False),
                                    ("uid", header[28:34], False),
                                    ("gid", header[34:40], False),
                                    ("mode", header[40:48], True)):
            _number(field, label, octal=octal, blank=metadata)
        size = _number(header[48:58], "member size")
        position += 60
        _require(size <= contract.MAX_FILE_BYTES and position + size <= len(data),
                 "archive member body is truncated or exceeds its bound")
        body = data[position:position + size]
        position += size
        if size % 2:
            _require(position < len(data) and data[position:position + 1] == b"\n",
                     "archive member padding is invalid or missing")
            position += 1
        if name in ("/", "/SYM64/"):
            _require(symbols is None and not members and long_names is None,
                     "archive symbol table is duplicate or out of order")
            symbols = (body, 8 if name == "/SYM64/" else 4)
            continue
        if name == "//":
            _require(long_names is None and not members,
                     "archive long-name table is duplicate or out of order")
            long_names = _long_names(body)
            continue
        if name.startswith("/"):
            _require(re.fullmatch(r"/(?:0|[1-9][0-9]*)", name) is not None,
                     "archive long-name reference is unsupported")
            offset = int(name[1:])
            _require(long_names is not None and offset in long_names,
                     "archive long-name reference is not an entry boundary")
            used_long_names.add(offset)
            name = long_names[offset]
        else:
            _require(name.endswith("/") and not name.startswith("#1/"),
                     "archive member name format is unsupported")
            name = _member_name(name[:-1])
        _require(name not in seen_names, "archive contains duplicate object members")
        _require(size > 0 and len(members) < MAX_MEMBERS,
                 "archive object is empty or exceeds its member bound")
        seen_names.add(name)
        offsets.add(header_offset)
        members.append({"name": name, "sha256": hashlib.sha256(body).hexdigest(),
                        "size_bytes": size})
    _require(members, "archive has no object members")
    _require(long_names is None or set(long_names) == used_long_names,
             "archive contains unreferenced long-name entries")
    symbol_count = 0 if symbols is None else _symbol_table(*symbols, offsets)
    return {"format": "gnu-ar-v1", "sha256": hashlib.sha256(data).hexdigest(),
            "size_bytes": len(data), "members": members, "symbol_count": symbol_count,
            "has_long_names": long_names is not None}


def _expected_members(rows):
    _require(type(rows) is list and 0 < len(rows) <= MAX_MEMBERS,
             "expected archive members must be a bounded nonempty list")
    names = set()
    for row in rows:
        _require(type(row) is dict and set(row) == {"name", "sha256", "size_bytes"},
                 "expected archive member schema differs")
        _member_name(row["name"])
        _require(row["name"] not in names, "expected archive members contain duplicates")
        _require(type(row["sha256"]) is str and _HEX.fullmatch(row["sha256"]) is not None,
                 "expected archive member digest is invalid")
        _require(type(row["size_bytes"]) is int and 0 < row["size_bytes"] <= contract.MAX_FILE_BYTES,
                 "expected archive member size is invalid")
        names.add(row["name"])
    return {row["name"]: row for row in rows}


def validate_archive(data, expected_members):
    _expected_members(expected_members)
    result = parse_archive(data)
    _require(result["members"] == expected_members,
             "archive ordered object identities differ from observed compiler outputs")
    return result


def _absolute(value, label):
    _require(type(value) is str and 0 < len(value) <= 4096 and _PATH.fullmatch(value) is not None
             and value.startswith("/") and not value.startswith("//"),
             label + " must be a safe absolute path")
    _require(str(PurePosixPath(value)) == value
             and not {".", ".."} & set(value.split("/")), label + " must be canonical")
    return value


def _recorded_path(value, cwd):
    _require(type(value) is str and 0 < len(value) <= 4096
             and _PATH.fullmatch(value) is not None and not value.startswith("//"),
             "link map contains an unsafe input path")
    parts = [] if value.startswith("/") else list(PurePosixPath(cwd).parts[1:])
    for part in value.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            _require(parts, "link map input escapes the filesystem root")
            parts.pop()
        else:
            parts.append(part)
    _require(parts, "link map input cannot be the filesystem root")
    return "/" + "/".join(parts)


def _reference(text, cwd):
    match = _REFERENCE.fullmatch(text)
    _require(match is not None, "link map archive reference is malformed or unsupported")
    origin, symbol = match.groups()
    selected = _SELECTION.fullmatch(origin)
    if selected:
        archive, member, tail = selected.groups()
        _require(tail is None, "link map reference contains trailing fields")
        return {"reference_file": _recorded_path(archive, cwd),
                "reference_member": _member_name(member), "symbol": symbol}
    return {"reference_file": _recorded_path(origin, cwd),
            "reference_member": None, "symbol": symbol}


def parse_link_map(text, *, cwd):
    """Parse selected-member and LOAD records; all paths remain lexical data."""
    cwd = _absolute(cwd, "link working directory")
    _require(type(text) is str and 0 < len(text) <= contract.MAX_FILE_BYTES,
             "link map must be bounded text")
    try:
        data = text.encode("ascii")
    except UnicodeError as error:
        raise ValueError("link map must be ASCII") from error
    _require(text.endswith("\n") and all(value in (9, 10) or 32 <= value < 127 for value in data),
             "link map contains unsupported control bytes or lacks a final newline")
    lines = text.split("\n")
    _require(len(lines) <= MAX_MAP_LINES and all(len(line) <= MAX_MAP_LINE_BYTES for line in lines),
             "link map exceeds its line bounds")
    _require(lines.count(ARCHIVE_HEADING) <= 1 and lines.count(MAP_HEADING) == 1,
             "link map section inventory differs")
    map_start = lines.index(MAP_HEADING)
    selected_members, selection_lines = [], set()
    if ARCHIVE_HEADING in lines:
        _require(lines[0] == ARCHIVE_HEADING and map_start > 0,
                 "link map archive section is misplaced")
        position, seen = 1, set()
        while position < map_start:
            line = lines[position]
            position += 1
            if not line:
                continue
            if line in NEXT_HEADINGS:
                break
            match = _SELECTION.fullmatch(line)
            _require(match is not None, "link map selected-member row is malformed")
            selection_lines.add(position - 1)
            archive, member, reference = match.groups()
            archive, member = _recorded_path(archive, cwd), _member_name(member)
            _require((archive, member) not in seen, "link map repeats an archive member selection")
            _require(len(selected_members) < MAX_MEMBERS, "link map exceeds its selected-member bound")
            if reference is None or not reference.strip():
                _require(position < map_start and lines[position].startswith((" ", "\t")),
                         "link map archive reference is missing")
                reference = lines[position].strip(" \t")
                position += 1
            else:
                reference = reference.strip(" \t")
            selected_members.append({"archive": archive, "name": member,
                                     **_reference(reference, cwd)})
            seen.add((archive, member))
        _require(selected_members, "link map archive section contains no member selections")
    loads, section_members = [], set()
    for position, line in enumerate(lines):
        _require(position in selection_lines or _SELECTION.fullmatch(line) is None,
                 "link map selected-member row is outside its archive section")
        contribution = _CONTRIBUTION.fullmatch(line)
        if contribution:
            archive, member = contribution.groups()
            section_members.add((_recorded_path(archive, cwd), _member_name(member)))
            _require(len(section_members) <= MAX_MEMBERS, "link map exceeds its section-member bound")
        if line.startswith("LOAD"):
            _require(position > map_start and line.startswith("LOAD ")
                     and len(line) > 5 and " " not in line[5:] and "\t" not in line[5:],
                     "link map LOAD row is malformed or misplaced")
            loads.append(_recorded_path(line[5:], cwd))
    _require(loads, "link map has no LOAD records")
    _require(section_members == {(row["archive"], row["name"]) for row in selected_members},
             "link map archive selections differ from its input-section members")
    return {"format": "gnu-ld-map-v1", "sha256": hashlib.sha256(data).hexdigest(),
            "size_bytes": len(data), "selected_members": selected_members, "loads": loads,
            "section_members": [{"archive": archive, "name": member}
                                for archive, member in sorted(section_members)]}


def validate_link_map(text, *, cwd, archives, required_archives=None, required_loads=()):
    _require(type(archives) is dict and len(archives) <= MAX_MEMBERS,
             "link map expected archives must be a bounded mapping")
    known = {}
    for path, members in archives.items():
        path = _absolute(path, "expected archive path")
        _require(path.endswith(".a"), "expected archive path has an unsupported suffix")
        known[path] = _expected_members(members)
    required = list(known) if required_archives is None else required_archives
    _require(type(required) in (list, tuple) and all(type(item) is str for item in required)
             and len(required) == len(set(required)) and set(required) <= set(known),
             "required archive inventory differs")
    _require(type(required_loads) in (list, tuple) and len(required_loads) <= MAX_MEMBERS,
             "required LOAD inventory must be bounded")
    for path in required_loads:
        _absolute(path, "required LOAD path")
    _require(len(required_loads) == len(set(required_loads)), "required LOAD paths contain duplicates")
    result = parse_link_map(text, cwd=cwd)
    admitted = []
    for row in result["selected_members"]:
        archive, member = row["archive"], row["name"]
        _require(archive in known, "link map selects an unadmitted archive")
        _require(member in known[archive], "link map selects an unadmitted archive member")
        admitted.append({**row, "sha256": known[archive][member]["sha256"],
                         "size_bytes": known[archive][member]["size_bytes"]})
    selected_archives = {row["archive"] for row in admitted}
    _require(set(required) <= selected_archives, "link map lacks required archive-member evidence")
    loads = Counter(result["loads"])
    _require(all(loads[path] == 1 for path in set(required) | set(required_loads)),
             "link map lacks a unique required LOAD record")
    _require(all(loads[path] >= 1 for path in selected_archives),
             "link map selected archive lacks its LOAD record")
    return {**result, "selected_members": admitted,
            "required_archives": list(required), "required_loads": list(required_loads)}
