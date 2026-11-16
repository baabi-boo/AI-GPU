# SPDX-License-Identifier: Apache-2.0
"""Read explicit vendor-emulation inputs without following links or executing them."""

import re

from baseline_packet_io import MAX_TOTAL_BYTES, PacketError, PacketReader


MAX_INPUT_FILES = 64
MAX_TEXT_BYTES = 1024 * 1024
MAX_JSON_BYTES = 256 * 1024


class InputError(ValueError):
    """A declared input is unsafe, malformed, mismatched, or unstable."""


def _integer(value, maximum, label, minimum=1):
    if type(value) is not int or not minimum <= value <= maximum:
        raise InputError(label + " is outside its integer limit")
    return value


def _relative(path):
    if (type(path) is not str or not re.fullmatch(r"/[A-Za-z0-9_./+-]+", path)
            or len(path) > 4096):
        raise InputError("input path must be an absolute safe canonical path")
    parts = path[1:].split("/")
    if (len(parts) > 128 or any(
            part in ("", ".", "..") or len(part) > 255 for part in parts)):
        raise InputError("input path must be an absolute safe canonical path")
    return path[1:]


def _label(label):
    if type(label) is not str or not re.fullmatch(r"[A-Za-z0-9_. -]{1,80}", label):
        raise InputError("input label is invalid")
    return label


class Inputs:
    """Inspect a bounded set of explicit absolute paths with shared byte accounting."""

    def __init__(self, max_total_bytes=MAX_TOTAL_BYTES, max_files=MAX_INPUT_FILES):
        _integer(max_total_bytes, MAX_TOTAL_BYTES, "total input byte budget")
        _integer(max_files, MAX_INPUT_FILES, "input file budget")
        try:
            self._reader = PacketReader("/", max_total_bytes=max_total_bytes,
                                        max_files=max_files)
        except PacketError as error:
            raise InputError("safe input access is unavailable") from error

    def __enter__(self):
        self._reader.__enter__()
        return self

    def __exit__(self, _kind, _value, _traceback):
        self.close()

    def close(self):
        self._reader.close()

    def check_file(self, identity, label="input"):
        label = _label(label)
        if type(identity) is not dict or set(identity) != {"path", "size_bytes", "sha256"}:
            raise InputError(label + " identity fields are invalid")
        relative = _relative(identity["path"])
        size = _integer(identity["size_bytes"], MAX_TOTAL_BYTES,
                        label + " size", minimum=0)
        digest = identity["sha256"]
        if type(digest) is not str or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise InputError(label + " digest is invalid")
        try:
            observed = self._reader.identity(relative, limit=size)
        except PacketError as error:
            raise InputError(label + " is missing, unsafe, oversized, or changed") from error
        observed["path"] = "/" + observed["path"]
        if observed != identity:
            raise InputError(label + " bytes do not match their declared identity")
        return observed

    def read_text(self, path, limit=MAX_TEXT_BYTES):
        relative = _relative(path)
        _integer(limit, MAX_TEXT_BYTES, "text byte limit")
        try:
            return self._reader.read_bytes(relative, limit=limit).decode("utf-8")
        except (PacketError, UnicodeError) as error:
            raise InputError("text input is missing, unsafe, oversized, changed, or invalid UTF-8") from error

    def read_json(self, path, limit=MAX_JSON_BYTES):
        relative = _relative(path)
        _integer(limit, MAX_JSON_BYTES, "JSON byte limit")
        try:
            return self._reader.read_json(relative, limit=limit)
        except PacketError as error:
            raise InputError("JSON input is missing, unsafe, oversized, changed, or malformed") from error

    def inventory(self):
        return [dict(item, path="/" + item["path"]) for item in self._reader.inventory()]

    def recheck(self):
        try:
            self._reader.recheck()
        except PacketError as error:
            raise InputError("input set changed during inspection") from error


def read_manifest(path):
    """Read one inert manifest within a separate 256-KiB budget."""
    with Inputs(max_total_bytes=MAX_JSON_BYTES, max_files=1) as inputs:
        result = inputs.read_json(path)
        inputs.recheck()
        return result
