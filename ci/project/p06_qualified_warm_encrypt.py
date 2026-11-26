#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Encrypt an entire PRIVATE packaging directory with the established age CLI.

Only a successful, bounded age process may release its ciphertext into a fresh
public output directory. The sibling <output-dir>.PRIVATE retains bounded
stderr and incomplete ciphertext on failure, with owner-only permissions. No
plaintext tar is written to disk. The encrypted tar contains manifest.json
and the entire selected tree under private/, including hidden files and empty
directories. The manifest records exact relative names, sizes and SHA256.

Stop all writers before calling this helper. Repeated descriptor and named-path
identities and hashes detect observed changes; they do not exclude concurrent writers.
The explicitly selected age executable is trusted software, not retained input.
This wrapper does not authenticate that executable, authenticate a producer,
perform replay, grant acceptance, obtain credentials, or upload anything.
The retention-only storage guard reserves a conservative ciphertext bound plus
64 MiB. It never authorizes native work or changes its separate 15 GiB reserve.
Publication is recoverable while this process can run cleanup, not a multi-file
crash transaction. Once the public pair commits, a later interruption preserves
it; storage failure, abrupt termination and concurrent replacement can prevent
cleanup or durable delivery.
"""

from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import time
import unicodedata

sys.dont_write_bytecode = True

CONTRACT_ID = "p06-qualified-warm-encrypted-retention-v1"
CIPHERTEXT_NAME = "qualified-warm-retention.tar.age"
SUMMARY_NAME = "encryption-summary.json"
MANIFEST_NAME = "manifest.json"
PRIVATE_SUFFIX = ".PRIVATE"
STDERR_NAME = "age-stderr.PRIVATE.log"
DIAGNOSTIC_NAME = "encryption.PRIVATE.json"
INCOMPLETE_NAME = "incomplete-retention.PRIVATE.age"
PRIVATE_SUMMARY_NAME = "encryption-summary.PRIVATE.json"
# Retention bounds do not change native execution budgets. The input bound
# accommodates both 256 MiB packaging ZIPs and their 64 MiB receipts.
RETENTION_DISK_MARGIN_BYTES = 64 * 1024**2
MAX_INPUT_BYTES = 1024**3
MAX_FILE_BYTES = 256 * 1024**2
MAX_ENTRIES = 40000
MAX_MANIFEST_BYTES = 16 * 1024**2
MAX_STDERR_BYTES = 16 * 1024**2
MAX_RUNTIME_SECONDS = 180
MAX_PATH_BYTES = 4096
MAX_DEPTH = 128
CHUNK_BYTES = 64 * 1024
SAFE_ENV = {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"}
_RECIPIENT = re.compile(r"age1[qpzry9x8gf2tvdw0s3jn54khce6mua7l]{58}\Z")


class EncryptionError(ValueError):
    """An intentionally non-sensitive, fixed diagnostic code."""


def _require(condition, code):
    if not condition:
        raise EncryptionError(code)


def validate_recipient(recipient):
    """Parse one canonical X25519 Bech32 public address, without cryptography.

    The fixed HRP, 32-byte encoding and BIP-173 checksum are checked offline.
    Encryption and key agreement remain exclusively the trusted age CLI's job.
    See https://github.com/bitcoin/bips/blob/master/bip-0173.mediawiki and
    https://github.com/FiloSottile/age/blob/main/x25519.go .
    """
    _require(type(recipient) is str and _RECIPIENT.fullmatch(recipient), "invalid-recipient")
    alphabet = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
    data = [alphabet.index(char) for char in recipient[4:]]
    # 32 bytes occupy 52 base32 characters, whose final four bits are padding.
    _require(data[-7] & 15 == 0, "invalid-recipient")
    check = 1
    expanded = [ord(char) >> 5 for char in "age"] + [0] + [ord(char) & 31 for char in "age"]
    for value in expanded + data:
        top = check >> 25
        check = ((check & 0x1ffffff) << 5) ^ value
        for bit, generator in enumerate((0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3)):
            if top & (1 << bit):
                check ^= generator
    _require(check == 1, "invalid-recipient")
    return recipient


def _relative(name):
    _require(type(name) is str and name and len(name.encode("utf-8")) <= MAX_PATH_BYTES,
             "noncanonical-path")
    _require(unicodedata.normalize("NFC", name) == name
             and not any(ord(char) < 32 or ord(char) == 127 for char in name)
             and "\\" not in name and ":" not in name, "noncanonical-path")
    parts = name.split("/")
    _require(len(parts) <= MAX_DEPTH and all(part not in ("", ".", "..")
             and len(part.encode("utf-8")) <= 255 for part in parts), "noncanonical-path")
    return name


def _canonical(value):
    raw = os.fspath(value)
    _require(type(raw) is str and raw.startswith("/") and raw != "/", "noncanonical-path")
    _relative(raw[1:])
    return Path(raw)


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _directory(path):
    """Open all ancestors without following links; return fd and ancestor IDs."""
    if path != Path("/"):
        path = _canonical(path)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open("/", flags)
    identities = []
    try:
        info = os.fstat(fd)
        identities.append((info.st_dev, info.st_ino))
        for part in path.parts[1:]:
            child = os.open(part, flags, dir_fd=fd)
            parent, fd = fd, child
            os.close(parent)
            info = os.fstat(fd)
            identities.append((info.st_dev, info.st_ino))
        return fd, identities
    except BaseException:
        try:
            os.close(fd)
        except BaseException:
            pass
        raise


def _verify_directories(directories):
    for path, expected, code in directories:
        try:
            fd, identities = _directory(path)
        except OSError:
            raise EncryptionError(code) from None
        try:
            _require(identities == expected, code)
        finally:
            os.close(fd)


def _overlap(left, right):
    return left == right or left in right.parents or right in left.parents


def _check_time(deadline):
    _require(time.monotonic() < deadline, "runtime-limit")


def _free_bytes(fd):
    info = os.fstatvfs(fd)
    return info.f_bavail * info.f_frsize


def _reserve(fd, additional=0):
    _require(_free_bytes(fd) >= RETENTION_DISK_MARGIN_BYTES + additional, "disk-reserve")


def _exclusive(directory_fd, name):
    fd = os.open(name, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC,
                 0o600, dir_fd=directory_fd)
    try:
        os.fchmod(fd, 0o600)
        return os.fdopen(fd, "w+b", buffering=0)
    except BaseException:
        try:
            # A failed close can consume the fd; never retry its reused number.
            os.close(fd)
        except BaseException:
            pass
        raise


def _json_bytes(document):
    return (json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def _write_all(stream, body):
    remaining = memoryview(body)
    while remaining:
        count = stream.write(remaining)
        _require(type(count) is int and count > 0, "short-output-write")
        remaining = remaining[count:]


def _unlink_owned(directory_fd, name, identity):
    """Withdraw only our inode; report whether it is observably absent.

    A false result is conservative: failed withdrawal must not allow cleanup of
    a file that an owned success summary still names. Repeated interruption or
    a same-user replacement between stat and unlink cannot be excluded here.
    """
    try:
        info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if (info.st_dev, info.st_ino) != identity:
            return True
        os.unlink(name, dir_fd=directory_fd)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return True


def _owned(directory_fd, name, identity):
    try:
        info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        return (info.st_dev, info.st_ino) == identity
    except OSError:
        return False


def _write_json(directory_fd, name, document):
    raw = _json_bytes(document)
    _require(len(raw) <= MAX_MANIFEST_BYTES, "json-limit")
    with _exclusive(directory_fd, name) as stream:
        identity = _stamp(os.fstat(stream.fileno()))[:2]
        try:
            _reserve(directory_fd, len(raw))
            _write_all(stream, raw)
            os.fsync(stream.fileno())
        except BaseException:
            _unlink_owned(directory_fd, name, identity)
            raise
    return identity


@dataclass(frozen=True)
class _Entry:
    name: str
    directory: bool
    identity: tuple
    size: int = 0
    sha256: str | None = None


class _VerifiedReader:
    """Read exactly a stable, bounded single-link regular descriptor."""
    def __init__(self, root, entry, deadline):
        path = root / entry.name
        self.entry, self.deadline, self.count = entry, deadline, 0
        self.digest = hashlib.sha256()
        self.parent, _ = _directory(path.parent)
        self.name = path.name
        self.stream = None
        try:
            before = os.stat(self.name, dir_fd=self.parent, follow_symlinks=False)
            _require(_stamp(before) == entry.identity and stat.S_ISREG(before.st_mode)
                     and before.st_nlink == 1, "source-changed")
            fd = os.open(self.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                         dir_fd=self.parent)
            self.stream = os.fdopen(fd, "rb", buffering=0)
            _require(_stamp(os.fstat(fd)) == entry.identity, "source-changed")
        except BaseException:
            self.close()
            raise

    def read(self, size=-1):
        _check_time(self.deadline)
        size = min(CHUNK_BYTES, self.entry.size + 1 - self.count,
                   size if size >= 0 else CHUNK_BYTES)
        body = self.stream.read(size)
        self.count += len(body)
        _require(self.count <= self.entry.size, "source-changed")
        self.digest.update(body)
        return body

    def verify(self):
        # Tar consumes the advertised size, so explicitly probe for growth.
        _require(self.read(1) == b"" and self.count == self.entry.size, "source-changed")
        _require(_stamp(os.fstat(self.stream.fileno())) == self.entry.identity
                 and _stamp(os.stat(self.name, dir_fd=self.parent, follow_symlinks=False)) == self.entry.identity,
                 "source-changed")
        digest = self.digest.hexdigest()
        _require(self.entry.sha256 is None or digest == self.entry.sha256, "source-changed")
        return digest

    def close(self):
        if self.stream is not None:
            self.stream.close()
        os.close(self.parent)


def _inventory(root, deadline):
    entries, seen, folded = {}, set(), set()
    byte_count = 0

    def visit(path, name, info):
        nonlocal byte_count
        _check_time(deadline)
        if name:
            _relative(name)
        _require(len(entries) < MAX_ENTRIES, "entry-limit")
        identity = _stamp(info)
        inode = identity[:2]
        _require(inode not in seen and name.casefold() not in folded, "path-alias")
        seen.add(inode)
        folded.add(name.casefold())
        if stat.S_ISDIR(info.st_mode):
            entries[name] = _Entry(name, True, identity)
            fd, _ = _directory(path)
            try:
                _require(_stamp(os.fstat(fd)) == identity, "source-changed")
                children = []
                with os.scandir(fd) as scan:
                    for child in scan:
                        _require(len(children) + len(entries) < MAX_ENTRIES, "entry-limit")
                        children.append((child.name, child.stat(follow_symlinks=False)))
                for child, child_info in sorted(children):
                    visit(path / child, name + "/" + child if name else child, child_info)
                _require(_stamp(os.fstat(fd)) == identity and _stamp(path.lstat()) == identity,
                         "source-changed")
            finally:
                os.close(fd)
        else:
            _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "link-or-special-input")
            _require(0 <= info.st_size <= MAX_FILE_BYTES, "file-limit")
            byte_count += info.st_size
            _require(byte_count <= MAX_INPUT_BYTES, "input-byte-limit")
            entry = _Entry(name, False, identity, info.st_size)
            reader = _VerifiedReader(root, entry, deadline)
            try:
                while reader.read():
                    pass
                entries[name] = _Entry(name, False, identity, info.st_size, reader.verify())
            finally:
                reader.close()

    fd, _ = _directory(root)
    try:
        visit(root, "", os.fstat(fd))
    finally:
        os.close(fd)
    return entries


def _age_binary(value, input_dir, output_dir, private_dir):
    _require(type(value) is str or isinstance(value, Path), "invalid-age-binary")
    raw = os.fspath(value)
    if raw == "age":
        raw = shutil.which("age", path=os.defpath)
        _require(raw is not None, "age-unavailable")
    path = _canonical(raw)
    _require(all(not _overlap(path, root) for root in (input_dir, output_dir, private_dir)),
             "age-binary-overlap")
    parent, _ = _directory(path.parent)
    try:
        info = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_mode & 0o111,
                 "invalid-age-binary")
        return path, _stamp(info)
    finally:
        os.close(parent)


def _tar_info(name, *, size=0, directory=False):
    info = tarfile.TarInfo(name)
    info.type = tarfile.DIRTYPE if directory else tarfile.REGTYPE
    info.mode = 0o700 if directory else 0o600
    info.size = size
    info.mtime = 0
    return info


def _tar_members(entries, manifest):
    yield _tar_info(MANIFEST_NAME, size=len(manifest)), None
    for name, entry in sorted(entries.items()):
        yield _tar_info("private" + ("/" + name if name else ""),
                        size=entry.size, directory=entry.directory), entry


def _tar_size(entries, manifest):
    count = 1024
    for info, _ in _tar_members(entries, manifest):
        count += len(info.tobuf(format=tarfile.PAX_FORMAT, encoding="utf-8", errors="strict"))
        count += (info.size + 511) // 512 * 512
    return (count + tarfile.RECORDSIZE - 1) // tarfile.RECORDSIZE * tarfile.RECORDSIZE


def _cleanup(process):
    """Bounded process-group cleanup observation, not descendant containment."""
    if process is None:
        return True
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            continue
    try:
        os.killpg(process.pid, 0)
    except ProcessLookupError:
        return process.poll() is not None
    return False


class _Pump:
    """Drive all three nonblocking pipes while tarfile produces bounded chunks."""
    def __init__(self, process, cipher, stderr, directory_fd, tar_bytes, deadline):
        self.process, self.cipher, self.stderr = process, cipher, stderr
        self.directory_fd, self.deadline = directory_fd, deadline
        self.expected_input = tar_bytes
        self.input_bytes = self.output_bytes = self.stderr_bytes = 0
        self.output_limit = tar_bytes + ((tar_bytes + 65535) // 65536) * 16 + 4096
        self.digest, self.prefix = hashlib.sha256(), bytearray()
        self.selector = selectors.DefaultSelector()
        for stream in (process.stdin, process.stdout, process.stderr):
            os.set_blocking(stream.fileno(), False)
        self.selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        self.selector.register(process.stderr, selectors.EVENT_READ, "stderr")

    def _events(self):
        _check_time(self.deadline)
        _reserve(self.directory_fd)
        return self.selector.select(timeout=min(0.1, max(0, self.deadline - time.monotonic())))

    def _drain(self, key):
        body = os.read(key.fileobj.fileno(), CHUNK_BYTES)
        if not body:
            self.selector.unregister(key.fileobj)
            return
        if key.data == "stdout":
            self.output_bytes += len(body)
            _require(self.output_bytes <= self.output_limit, "ciphertext-byte-limit")
            self.digest.update(body)
            self.prefix.extend(body[:max(0, 512 - len(self.prefix))])
            target = self.cipher
        else:
            remaining = MAX_STDERR_BYTES - self.stderr_bytes
            if len(body) > remaining:
                if remaining:
                    _reserve(self.directory_fd, remaining)
                    _write_all(self.stderr, body[:remaining])
                self.stderr_bytes += len(body)
                raise EncryptionError("stderr-byte-limit")
            self.stderr_bytes += len(body)
            target = self.stderr
        _reserve(self.directory_fd, len(body))
        _write_all(target, body)

    def write(self, body):
        length = len(body)
        _require(self.input_bytes + length <= self.expected_input, "tar-byte-limit")
        pending = memoryview(body)
        self.selector.register(self.process.stdin, selectors.EVENT_WRITE, "stdin")
        try:
            while pending:
                for key, _ in self._events():
                    if key.data == "stdin":
                        count = os.write(key.fileobj.fileno(), pending[:CHUNK_BYTES])
                        pending = pending[count:]
                        self.input_bytes += count
                    else:
                        self._drain(key)
        finally:
            self.selector.unregister(self.process.stdin)
        return length

    def finish(self):
        self.process.stdin.close()
        while self.selector.get_map() or self.process.poll() is None:
            for key, _ in self._events():
                self._drain(key)
        _require(self.process.returncode == 0, "age-failed")
        _require(self.input_bytes == self.expected_input, "incomplete-tar")
        # Framing catches wrong executables and accidental plaintext. It is not
        # cryptographic verification of an otherwise untrusted executable.
        lines = bytes(self.prefix).split(b"\n", 4)
        _require(len(lines) == 5 and lines[0] == b"age-encryption.org/v1"
                 and lines[1].startswith(b"-> X25519 ") and lines[3].startswith(b"--- "),
                 "invalid-age-output")
        for value in (lines[1][len(b"-> X25519 "):], lines[2], lines[3][4:]):
            _require(re.fullmatch(rb"[A-Za-z0-9+/]{43}", value), "invalid-age-output")
            _require(len(base64.b64decode(value + b"=", validate=True)) == 32, "invalid-age-output")
        header_bytes = sum(len(line) + 1 for line in lines[:4])
        exact = header_bytes + 16 + self.expected_input + ((self.expected_input + 65535) // 65536) * 16
        _require(self.output_bytes == exact, "invalid-age-output")
        os.fsync(self.cipher.fileno())
        os.fsync(self.stderr.fileno())

    def close(self):
        self.selector.close()
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            if not stream.closed:
                stream.close()


def _verify_cipher(stream, directory_fd, count, expected_digest, deadline):
    before = _stamp(os.fstat(stream.fileno()))
    _require(before[3] == 1 and before[4] == count, "ciphertext-changed")
    _require(_stamp(os.stat(INCOMPLETE_NAME, dir_fd=directory_fd, follow_symlinks=False)) == before,
             "ciphertext-changed")
    stream.seek(0)
    size, digest = 0, hashlib.sha256()
    while True:
        _check_time(deadline)
        body = stream.read(CHUNK_BYTES)
        if not body:
            break
        size += len(body)
        _require(size <= count, "ciphertext-changed")
        digest.update(body)
    _require(size == count and digest.hexdigest() == expected_digest
             and _stamp(os.fstat(stream.fileno())) == before, "ciphertext-changed")
    return before


def _verify_public_file(directory_fd, name, identity, count, expected_digest, deadline):
    _require(_owned(directory_fd, name, identity), "public-output-changed")
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                 dir_fd=directory_fd)
    try:
        before = _stamp(os.fstat(fd))
        _require(before[:2] == identity and stat.S_ISREG(before[2]) and before[4] == count,
                 "public-output-changed")
        size, digest = 0, hashlib.sha256()
        while True:
            _check_time(deadline)
            body = os.read(fd, CHUNK_BYTES)
            if not body:
                break
            size += len(body)
            _require(size <= count, "public-output-changed")
            digest.update(body)
        _require(size == count and digest.hexdigest() == expected_digest
                 and _stamp(os.fstat(fd)) == before
                 and _stamp(os.stat(name, dir_fd=directory_fd, follow_symlinks=False)) == before,
                 "public-output-changed")
    finally:
        os.close(fd)


def _summary(revision, *, passed=False, entries=None, cipher_bytes=0, cipher_digest=None):
    files = [entry for entry in (entries or {}).values() if not entry.directory]
    return {"schema_version": 1, "contract_id": CONTRACT_ID, "expected_revision": revision,
            "outcome": "pass" if passed else "fail", "encryption_passed": passed,
            "file_count": len(files), "directory_count": sum(entry.directory for entry in (entries or {}).values()),
            "input_bytes": sum(entry.size for entry in files),
            "ciphertext_bytes": cipher_bytes, "ciphertext_sha256": cipher_digest}


def encrypt_private_directory(*, input_dir, output_dir, recipient, age_binary="age", expected_revision=None):
    """Release ciphertext and a sanitized summary only after all checks pass.

    Public success authorizes only these two newly produced files for transfer.
    The input and sibling PRIVATE directory always remain private. On failure,
    cleanup before commit attempts to revoke its own summary before ciphertext,
    preserving the last encrypted copy and unrelated files. A committed public
    pair survives interruption of private-link cleanup even if this call raises.
    Callers must never substitute plaintext or upload the parent directory after
    a failure. Filesystem errors and abrupt termination can prevent recovery;
    these ordered operations are not an atomic multi-file storage transaction.
    """
    deadline = time.monotonic() + MAX_RUNTIME_SECONDS
    recipient = validate_recipient(recipient)
    _require(expected_revision is None or type(expected_revision) is str
             and re.fullmatch(r"[0-9a-f]{40}", expected_revision), "invalid-revision")
    source, output = map(_canonical, (input_dir, output_dir))
    private = _canonical(str(output) + PRIVATE_SUFFIX)
    _require(all(not _overlap(left, right) for left, right in
                 ((source, output), (source, private), (output, private))), "path-overlap")
    binary, binary_stamp = _age_binary(age_binary, source, output, private)
    source_fd, source_chain = _directory(source)
    os.close(source_fd)
    parent_fd, parent_chain = _directory(output.parent)
    output_fd = private_fd = None
    process = pump = None
    committed = False
    cipher_identity = summary_identity = None
    entries = None
    stage = "admission"
    cleanup_complete = True
    try:
        _require(source_chain[-1] not in parent_chain, "path-alias")
        for path in (output, private):
            try:
                os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            raise EncryptionError("existing-output")
        _reserve(parent_fd)
        os.mkdir(private.name, 0o700, dir_fd=parent_fd)
        private_fd = os.open(private.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                             dir_fd=parent_fd)
        os.fchmod(private_fd, 0o700)
        os.mkdir(output.name, 0o700, dir_fd=parent_fd)
        output_fd = os.open(output.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                            dir_fd=parent_fd)
        os.fchmod(output_fd, 0o700)
        directories = ((source, source_chain, "source-changed"),
            (output, parent_chain + [_stamp(os.fstat(output_fd))[:2]], "public-output-changed"),
            (private, parent_chain + [_stamp(os.fstat(private_fd))[:2]], "private-output-changed"))
        stage = "inventory"
        entries = _inventory(source, deadline)
        _verify_directories(directories)
        _require(not any(entry.directory and entry.identity[:2] in parent_chain for entry in entries.values()),
                 "path-alias")
        manifest = _json_bytes({"schema_version": 1, "contract_id": CONTRACT_ID,
            "expected_revision": expected_revision,
            "directories": [name for name, entry in sorted(entries.items()) if entry.directory],
            "files": [{"path": name, "size_bytes": entry.size, "sha256": entry.sha256}
                      for name, entry in sorted(entries.items()) if not entry.directory]})
        _require(len(manifest) <= MAX_MANIFEST_BYTES, "manifest-byte-limit")
        tar_bytes = _tar_size(entries, manifest)
        _reserve(private_fd, tar_bytes + ((tar_bytes + 65535) // 65536) * 16 + 4096)
        stage = "encryption"
        with _exclusive(private_fd, INCOMPLETE_NAME) as cipher, _exclusive(private_fd, STDERR_NAME) as stderr:
            _check_time(deadline)
            _require(_stamp(binary.lstat()) == binary_stamp, "age-binary-changed")
            process = subprocess.Popen([str(binary), "--encrypt", "--recipient", recipient],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                cwd=private, env=dict(SAFE_ENV), close_fds=True, start_new_session=True, bufsize=0)
            pump = _Pump(process, cipher, stderr, private_fd, tar_bytes, deadline)
            with tarfile.open(fileobj=pump, mode="w|", format=tarfile.PAX_FORMAT,
                              encoding="utf-8", errors="strict") as archive:
                for info, entry in _tar_members(entries, manifest):
                    _check_time(deadline)
                    if entry is None:
                        archive.addfile(info, io.BytesIO(manifest))
                    elif entry.directory:
                        archive.addfile(info)
                    else:
                        reader = _VerifiedReader(source, entry, deadline)
                        try:
                            archive.addfile(info, reader)
                            reader.verify()
                        finally:
                            reader.close()
            pump.finish()
            cleanup_complete = _cleanup(process)
            _require(cleanup_complete, "cleanup-unresolved")
            _require(_stamp(binary.lstat()) == binary_stamp, "age-binary-changed")
            stage = "final-inventory"
            _require(_inventory(source, deadline) == entries, "source-changed")
            cipher_stamp = _verify_cipher(cipher, private_fd, pump.output_bytes, pump.digest.hexdigest(), deadline)
            summary = _summary(expected_revision, passed=True, entries=entries,
                               cipher_bytes=pump.output_bytes, cipher_digest=pump.digest.hexdigest())
        stage = "publication"
        # Stage the success summary privately. Its inode is known before any
        # public operation; interruption after _write_json completes cannot
        # strand a public pass receipt whose ownership was never registered.
        summary_identity = _write_json(private_fd, PRIVATE_SUMMARY_NAME, summary)
        _check_time(deadline)
        _verify_directories(directories)
        _require(_stamp(os.stat(INCOMPLETE_NAME, dir_fd=private_fd, follow_symlinks=False)) == cipher_stamp,
                 "ciphertext-changed")
        _require(os.listdir(output_fd) == [], "public-output-changed")
        _require(_owned(private_fd, PRIVATE_SUMMARY_NAME, summary_identity), "summary-changed")
        # Register ownership intent before either no-clobber link: the syscall
        # can succeed and then be interrupted before Python observes its return.
        # The private ciphertext link stays until the complete pair commits.
        cipher_identity = cipher_stamp[:2]
        os.link(INCOMPLETE_NAME, CIPHERTEXT_NAME, src_dir_fd=private_fd,
                dst_dir_fd=output_fd, follow_symlinks=False)
        os.link(PRIVATE_SUMMARY_NAME, SUMMARY_NAME, src_dir_fd=private_fd,
                dst_dir_fd=output_fd, follow_symlinks=False)
        os.fsync(output_fd)
        _verify_directories(directories)
        _require(_owned(output_fd, CIPHERTEXT_NAME, cipher_identity)
                 and _owned(output_fd, SUMMARY_NAME, summary_identity), "public-output-changed")
        committed = True
        # From this boundary onward, rollback cannot revoke the public pair.
        # In particular unlink may complete before raising KeyboardInterrupt;
        # the public ciphertext could then be the last valid encrypted copy.
        stage = "private-cleanup"
        _unlink_owned(private_fd, INCOMPLETE_NAME, cipher_identity)
        _unlink_owned(private_fd, PRIVATE_SUMMARY_NAME, summary_identity)
        _verify_directories(directories)
        _verify_public_file(output_fd, CIPHERTEXT_NAME, cipher_identity,
                            summary["ciphertext_bytes"], summary["ciphertext_sha256"], deadline)
        raw_summary = _json_bytes(summary)
        _verify_public_file(output_fd, SUMMARY_NAME, summary_identity, len(raw_summary),
                            hashlib.sha256(raw_summary).hexdigest(), deadline)
        _verify_directories(directories)
        return summary
    except BaseException as error:
        cleanup_complete = _cleanup(process)
        if output_fd is not None and not committed:
            summary_withdrawn = (summary_identity is None or
                _unlink_owned(output_fd, SUMMARY_NAME, summary_identity))
            # Never withdraw ciphertext while its owned pass summary remains,
            # or if the private inode is unavailable as a retained copy.
            if (summary_withdrawn and cipher_identity is not None and
                    _owned(private_fd, INCOMPLETE_NAME, cipher_identity)):
                _unlink_owned(output_fd, CIPHERTEXT_NAME, cipher_identity)
            try:
                _write_json(output_fd, SUMMARY_NAME, _summary(expected_revision))
            except (OSError, ValueError):
                pass
        if private_fd is not None:
            try:
                _write_json(private_fd, DIAGNOSTIC_NAME, {"schema_version": 1,
                    "contract_id": CONTRACT_ID, "outcome": "fail", "stage": stage,
                    "error_type": type(error).__name__, "cleanup_complete": cleanup_complete,
                    "encryption_passed": False, "publication_committed": committed,
                    "plaintext_publication_authorized": False})
            except (OSError, ValueError):
                pass
        raise
    finally:
        if pump is not None:
            pump.close()
        elif process is not None:
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
        for fd in (output_fd, private_fd, parent_fd):
            if fd is not None:
                os.close(fd)


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's normal error text repeats arbitrary user arguments.
        raise EncryptionError("invalid-arguments")


def argument_parser():
    parser = _Parser(description=__doc__)
    for name in ("input-dir", "output-dir", "recipient"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--age-binary", default="age")
    parser.add_argument("--expected-revision")
    return parser


def _main(argv=None):
    revision = None
    try:
        args = argument_parser().parse_args(argv)
        if args.expected_revision is not None and re.fullmatch(r"[0-9a-f]{40}", args.expected_revision):
            revision = args.expected_revision
        summary = encrypt_private_directory(input_dir=args.input_dir, output_dir=args.output_dir,
            recipient=args.recipient, age_binary=args.age_binary, expected_revision=args.expected_revision)
        print(_json_bytes(summary).decode("utf-8"), end="")
        return 0
    except (Exception, KeyboardInterrupt):
        print(_json_bytes(_summary(revision)).decode("utf-8"), end="")
        return 1


def main(argv=None):
    def interrupt(number, frame):
        raise KeyboardInterrupt

    previous = signal.getsignal(signal.SIGTERM)
    try:
        signal.signal(signal.SIGTERM, interrupt)
        return _main(argv)
    finally:
        signal.signal(signal.SIGTERM, previous)


if __name__ == "__main__":
    sys.exit(main())
