# Licensed under the Apache License, Version 2.0.
"""Strict, inert input contracts for the bounded vendor XRT smoke."""

import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat


CONTRACT_ID = "p01-xrt-hw-emu-demo-v1"
CONFIGS = (
    "-DVX_CFG_NUM_CLUSTERS=1",
    "-DVX_CFG_NUM_CORES=1",
    "-DVX_CFG_NUM_WARPS=4",
    "-DVX_CFG_NUM_THREADS=4",
    "-DVX_CFG_ISSUE_WIDTH=1",
    "-DVX_CFG_FPU_TYPE_STD",
)
MAX_JSON_BYTES = 1024 * 1024
MAX_FILE_BYTES = 16 * 1024**3
MAX_TEXT_BYTES = 16 * 1024**2
VENDOR_ROLES = (
    "vpp", "vivado", "emconfigutil", "platforminfo", "xrt_header", "xrt_coreutil",
)
_PATH = re.compile(r"/[A-Za-z0-9_./+-]+\Z")
_LABEL = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:+-]{0,127}\Z")


def _object(value, keys, field):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError(field + " must contain exactly: " + ", ".join(sorted(keys)))
    return value


def _literal(value, expected, field):
    if type(value) is not type(expected) or value != expected:
        raise ValueError(field + " must be " + repr(expected))


def _hex(value, length, field):
    if type(value) is not str or not re.fullmatch(r"[0-9a-f]{" + str(length) + "}", value):
        raise ValueError(field + " must be a lowercase hexadecimal digest")


def safe_path(value):
    """Validate a path lexically without consulting or modifying the filesystem."""
    if isinstance(value, Path):
        value = str(value)
    if (type(value) is not str or len(value) > 4096 or not _PATH.fullmatch(value)
            or any(part in ("", ".", "..") for part in value.split("/")[1:])):
        raise ValueError("paths must be absolute, normalized and contain only safe characters")
    return Path(value)


def _label(value, field):
    if type(value) is not str or not _LABEL.fullmatch(value):
        raise ValueError(field + " must be a bounded safe label")


def _file(record, field, maximum=MAX_FILE_BYTES):
    _object(record, ("path", "sha256", "size_bytes"), field)
    if type(record["path"]) is not str:
        raise ValueError(field + ".path must be a string")
    safe_path(record["path"])
    _hex(record["sha256"], 64, field + ".sha256")
    size = record["size_bytes"]
    if type(size) is not int or not 0 < size <= maximum:
        raise ValueError(field + ".size_bytes must be a positive bounded integer")


def _source(value):
    _object(value, ("revision", "tree"), "source")
    for key in ("revision", "tree"):
        _hex(value[key], 40, "source." + key)


def _configuration(value):
    _object(value, ("xlen", "configs", "app", "args", "expected_points"), "configuration")
    for key, expected in (("xlen", 64), ("app", "demo"), ("expected_points", 16)):
        _literal(value[key], expected, "configuration." + key)
    for key, expected in (("configs", list(CONFIGS)), ("args", ["-n1"])):
        _literal(value[key], expected, "configuration." + key)


def _platform(value):
    _object(value, ("name", "file"), "platform")
    _label(value["name"], "platform.name")
    _file(value["file"], "platform.file")
    if Path(value["file"]["path"]).suffix != ".xpfm":
        raise ValueError("platform.file must identify an .xpfm descriptor")


def _vendor(value):
    _object(value, ("release", "vitis_root", "vivado_root", "xrt_root", "files"), "vendor")
    _label(value["release"], "vendor.release")
    for key in ("vitis_root", "vivado_root", "xrt_root"):
        if type(value[key]) is not str:
            raise ValueError("vendor." + key + " must be a string")
        safe_path(value[key])
    _object(value["files"], VENDOR_ROLES, "vendor.files")
    for role in VENDOR_ROLES:
        _file(value["files"][role], "vendor.files." + role)


def _artifacts(value):
    _object(value, ("xclbin", "emconfig"), "artifacts")
    _file(value["xclbin"], "artifacts.xclbin")
    _file(value["emconfig"], "artifacts.emconfig", MAX_JSON_BYTES)
    xclbin = Path(value["xclbin"]["path"])
    emconfig = Path(value["emconfig"]["path"])
    if (xclbin.name != "vortex_afu.xclbin" or emconfig.name != "emconfig.json"
            or xclbin.parent != emconfig.parent):
        raise ValueError("xclbin and emconfig must use the expected names in one artifact directory")


def _common(value):
    _literal(value["schema_version"], 1, "schema_version")
    _literal(value["driver"], "xrt", "driver")
    _literal(value["target"], "hw_emu", "target")
    _source(value["source"])
    _configuration(value["configuration"])
    _platform(value["platform"])
    _vendor(value["vendor"])
    _artifacts(value["artifacts"])


def validate_manifest(data):
    """Validate structure only; caller assertions are not vendor qualification."""
    _object(data, ("schema_version", "id", "driver", "target", "source", "configuration",
                   "platform", "vendor", "artifacts", "build_receipt", "qualification_review"),
            "manifest")
    _common(data)
    _literal(data["id"], CONTRACT_ID, "id")
    _file(data["build_receipt"], "build_receipt", MAX_JSON_BYTES)
    _file(data["qualification_review"], "qualification_review", MAX_JSON_BYTES)
    return data


def validate_receipt(data, manifest):
    """Bind inert successful build-command records to the declared inputs and outputs."""
    validate_manifest(manifest)
    _object(data, ("schema_version", "driver", "target", "source", "configuration",
                   "platform", "vendor", "artifacts", "commands"), "build receipt")
    _common(data)
    for key in ("driver", "target", "source", "configuration", "platform", "vendor", "artifacts"):
        if data[key] != manifest[key]:
            raise ValueError("build receipt disagrees with manifest: " + key)
    commands = data["commands"]
    if type(commands) is not list or not 1 <= len(commands) <= 32:
        raise ValueError("build receipt must retain between one and 32 commands")
    for index, command in enumerate(commands):
        field = "commands[" + str(index) + "]"
        _object(command, ("argv", "cwd", "exit_code", "log"), field)
        arguments = command["argv"]
        if (type(arguments) is not list or not 1 <= len(arguments) <= 128
                or any(type(arg) is not str or not arg or len(arg) > 4096
                       or any(ord(char) < 32 or ord(char) == 127 for char in arg)
                       for arg in arguments)
                or sum(len(arg) for arg in arguments) > 32768):
            raise ValueError(field + ".argv must be a bounded nonempty string array")
        if type(command["cwd"]) is not str:
            raise ValueError(field + ".cwd must be a string")
        safe_path(command["cwd"])
        _literal(command["exit_code"], 0, field + ".exit_code")
        _file(command["log"], field + ".log", MAX_TEXT_BYTES)
    return data


def _limit(value, maximum):
    if type(value) is not int or not 0 < value <= maximum:
        raise ValueError("file limit must be a positive bounded integer")
    return value


def _open_regular(path):
    path = safe_path(path)
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise ValueError("no-follow file inspection is unavailable on this platform")
    directory = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                            dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                             dir_fd=directory)
    finally:
        os.close(directory)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("input is not a regular file")
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _snapshot(metadata):
    return (metadata.st_dev, metadata.st_ino, metadata.st_size,
            metadata.st_mtime_ns, metadata.st_ctime_ns)


def _read(path, maximum, retain=False):
    descriptor = None
    try:
        descriptor = _open_regular(path)
        before = os.fstat(descriptor)
        if before.st_size > maximum:
            raise ValueError("input exceeds its file limit")
        digest = hashlib.sha256()
        size = 0
        chunks = []
        while True:
            block = os.read(descriptor, min(65536, maximum - size + 1))
            if not block:
                break
            size += len(block)
            if size > maximum:
                raise ValueError("input exceeds its file limit")
            digest.update(block)
            if retain:
                chunks.append(block)
        if size != before.st_size or _snapshot(os.fstat(descriptor)) != _snapshot(before):
            raise ValueError("input changed while being read")
        current = _open_regular(path)
        try:
            if _snapshot(os.fstat(current)) != _snapshot(before):
                raise ValueError("input path changed while being read")
        finally:
            os.close(current)
        return {"sha256": digest.hexdigest(), "size_bytes": size}, b"".join(chunks)
    except OSError as error:
        raise ValueError("input is unavailable or traverses a symlink") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def file_identity(path, max_bytes=None):
    """Stream a bounded regular file without following any path-component symlink."""
    maximum = MAX_FILE_BYTES if max_bytes is None else _limit(max_bytes, MAX_FILE_BYTES)
    return _read(path, maximum)[0]


def read_verified(record, max_bytes=None):
    """Read small retained content while checking its declared size and digest."""
    maximum = MAX_JSON_BYTES if max_bytes is None else _limit(max_bytes, MAX_TEXT_BYTES)
    _file(record, "file", maximum)
    identity, contents = _read(record["path"], maximum, retain=True)
    if identity != {key: record[key] for key in ("sha256", "size_bytes")}:
        raise ValueError("input differs from its declared identity")
    return contents


def _unique_fields(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON field: " + key)
        value[key] = item
    return value


def _reject_constant(value):
    raise ValueError("nonfinite JSON number: " + value)


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("nonfinite JSON number: " + value)
    return number


def decode_json(contents):
    if type(contents) is not bytes or len(contents) > MAX_JSON_BYTES:
        raise ValueError("JSON must be bounded UTF-8 bytes")
    try:
        data = json.loads(contents.decode("utf-8"), object_pairs_hook=_unique_fields,
                          parse_constant=_reject_constant, parse_float=_finite_float)
    except (UnicodeError, RecursionError, OverflowError) as error:
        raise ValueError("JSON is malformed or too deeply nested") from error
    if type(data) is not dict:
        raise ValueError("JSON root must be an object")
    return data


def load_json(path, max_bytes=MAX_JSON_BYTES):
    maximum = _limit(max_bytes, MAX_JSON_BYTES)
    return decode_json(_read(path, maximum, retain=True)[1])


def load_manifest(path):
    return validate_manifest(load_json(path))


def load_receipt(path, manifest):
    validate_manifest(manifest)
    if safe_path(path) != safe_path(manifest["build_receipt"]["path"]):
        raise ValueError("receipt path differs from the manifest")
    return validate_receipt(decode_json(read_verified(manifest["build_receipt"])), manifest)
