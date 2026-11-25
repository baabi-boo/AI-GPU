# SPDX-License-Identifier: Apache-2.0
"""Bind one bounded governance download to stable GitHub Actions observations."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import ssl
import stat
import subprocess
import sys
import time
from urllib.parse import unquote, urlsplit


REPOSITORY = "baabi-boo/AI-GPU"
WORKFLOW = ".github/workflows/project-governance.yml"
API_ORIGIN = "https://api.github.com"
API_PREFIX = "/repos/" + REPOSITORY + "/actions/"
MAX_ARCHIVE_BYTES = 256 * 1024**2
MAX_API_BYTES = 4 * 1024**2
MAX_ARTIFACTS = 1000
PAGE_SIZE = 100
DOWNLOAD_SECONDS = 120
SOCKET_SECONDS = 20
CHUNK_BYTES = 64 * 1024
MAX_LOCATION_BYTES = 8192
CONTRACT_ID = "p06-governance-artifact-v1"
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FINAL = "governance.zip"


class GovernanceArtifactError(ValueError):
    """A static, public-safe failure code for provider artifact acquisition."""


def _require(condition, code):
    if not condition:
        raise GovernanceArtifactError(code)


def _integer(value):
    return type(value) is int and 0 < value < 10**20


def _arguments(revision, run_id, run_attempt, token):
    _require(type(revision) is str and re.fullmatch(r"[0-9a-f]{40}", revision),
             "artifact_revision")
    _require(_integer(run_id) and _integer(run_attempt), "artifact_run_identity")
    _require(type(token) is str and re.fullmatch(r"[A-Za-z0-9_.-]{1,256}", token),
             "artifact_token")


def _document(api, path, token):
    try:
        value = api(path, token)
    except Exception:
        raise GovernanceArtifactError("artifact_api") from None
    _require(type(value) is dict, "artifact_api_shape")
    try:
        body = json.dumps(value, sort_keys=True, separators=(",", ":"),
                          allow_nan=False).encode("utf-8")
        _require(0 < len(body) <= MAX_API_BYTES, "artifact_api_bound")
        return json.loads(body), hashlib.sha256(body).hexdigest()
    except GovernanceArtifactError:
        raise
    except Exception:
        raise GovernanceArtifactError("artifact_api") from None


def _run(row, revision, run_id, run_attempt):
    _require(_integer(row.get("id")) and row["id"] == run_id
             and _integer(row.get("run_attempt")) and row["run_attempt"] == run_attempt
             and _integer(row.get("workflow_id")) and row.get("path") == WORKFLOW
             and row.get("head_sha") == revision and row.get("head_branch") == "master"
             and row.get("event") in ("push", "workflow_dispatch")
             and row.get("status") == "completed" and row.get("conclusion") == "success",
             "artifact_run")
    repositories = [row.get(key) for key in ("repository", "head_repository")]
    _require(all(type(value) is dict and value.get("full_name") == REPOSITORY
                 and _integer(value.get("id")) for value in repositories)
             and repositories[0]["id"] == repositories[1]["id"], "artifact_repository")
    return repositories[0]["id"]


def _timestamp(value):
    _require(type(value) is str and re.fullmatch(r"[0-9]{4}(?:-[0-9]{2}){2}T"
             r"[0-9]{2}(?::[0-9]{2}){2}Z", value), "artifact_timestamp")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        raise GovernanceArtifactError("artifact_timestamp") from None


def _artifact(row, revision, run_id, run_attempt, repository_id):
    _require(type(row) is dict and _integer(row.get("id")), "artifact_identity")
    name = f"project-governance-{revision}-run{run_id}-attempt{run_attempt}"
    _require(row.get("name") == name and row.get("expired") is False,
             "artifact_selection")
    size = row.get("size_in_bytes")
    _require(type(size) is int and 0 < size <= MAX_ARCHIVE_BYTES, "artifact_size")
    digest = row.get("digest")
    _require(type(digest) is str and re.fullmatch(r"sha256:[0-9a-f]{64}", digest),
             "artifact_digest")
    endpoint = API_ORIGIN + API_PREFIX + "artifacts/" + str(row["id"])
    _require(row.get("url") == endpoint and row.get("archive_download_url") == endpoint + "/zip",
             "artifact_endpoint")
    workflow = row.get("workflow_run")
    _require(type(workflow) is dict and _integer(workflow.get("id"))
             and workflow["id"] == run_id and _integer(workflow.get("repository_id"))
             and workflow["repository_id"] == repository_id
             and _integer(workflow.get("head_repository_id"))
             and workflow["head_repository_id"] == repository_id
             and workflow.get("head_branch") == "master" and workflow.get("head_sha") == revision,
             "artifact_source")
    # The current artifact API omits attempts; its exact name joins the current run observation.
    if "run_attempt" in workflow:
        _require(_integer(workflow["run_attempt"]) and workflow["run_attempt"] == run_attempt,
                 "artifact_attempt")
    created, updated, expires = (_timestamp(row.get(key)) for key in
                                 ("created_at", "updated_at", "expires_at"))
    _require(created <= updated < expires and expires > datetime.now(timezone.utc),
             "artifact_expired")
    return {"artifact_id": row["id"], "artifact_name": name, "sha256": digest[7:],
            "bytes": size, "repository": REPOSITORY, "head_sha": revision,
            "run_id": run_id, "run_attempt": run_attempt, "repository_id": repository_id,
            "created_at": row["created_at"], "updated_at": row["updated_at"],
            "expires_at": row["expires_at"]}


def _population(api, run_id, token):
    path = API_PREFIX + f"runs/{run_id}/artifacts?per_page={PAGE_SIZE}&page="
    rows, observations, seen, total = [], [], set(), None
    # The extra empty page closes the advertised pagination boundary.
    for page in range(1, MAX_ARTIFACTS // PAGE_SIZE + 2):
        document, observation = _document(api, path + str(page), token)
        count, entries = document.get("total_count"), document.get("artifacts")
        _require(type(count) is int and 0 <= count <= MAX_ARTIFACTS
                 and type(entries) is list, "artifact_pagination")
        if total is None:
            total = count
        _require(count == total, "artifact_pagination_changed")
        expected = min(PAGE_SIZE, max(0, total - len(rows)))
        _require(len(entries) == expected, "artifact_pagination_gap")
        observations.append(observation)
        for row in entries:
            _require(type(row) is dict and _integer(row.get("id"))
                     and row["id"] not in seen and type(row.get("name")) is str
                     and 0 < len(row["name"]) <= 256, "artifact_population")
            seen.add(row["id"])
            rows.append(row)
        if not entries:
            _require(len(rows) == total, "artifact_pagination_gap")
            return rows, observations
    raise GovernanceArtifactError("artifact_pagination_bound")


def _observe(api, revision, run_id, run_attempt, token):
    run, run_observation = _document(api, API_PREFIX + "runs/" + str(run_id), token)
    repository_id = _run(run, revision, run_id, run_attempt)
    population, page_observations = _population(api, run_id, token)
    name = f"project-governance-{revision}-run{run_id}-attempt{run_attempt}"
    selected = [row for row in population if row["name"] == name]
    _require(len(selected) == 1, "artifact_selection")
    identity = _artifact(selected[0], revision, run_id, run_attempt, repository_id)
    detail, detail_observation = _document(api, API_PREFIX + "artifacts/" +
                                         str(identity["artifact_id"]), token)
    _require(_artifact(detail, revision, run_id, run_attempt, repository_id) == identity,
             "artifact_metadata_changed")
    return identity, (run_observation, page_observations, detail_observation)


def _output_path(value):
    try:
        text = os.fspath(value)
    except TypeError:
        raise GovernanceArtifactError("artifact_output_path") from None
    _require(type(text) is str and text.startswith("/") and len(text) <= 4096
             and "\\" not in text and ":" not in text
             and not any(ord(char) < 32 or ord(char) == 127 for char in text),
             "artifact_output_path")
    parts = text.split("/")[1:]
    _require(0 < len(parts) <= 64 and all(part not in ("", ".", "..")
             and len(part.encode("utf-8")) <= 255 for part in parts), "artifact_output_path")
    return Path(text)


def _directory(path):
    descriptor = os.open("/", _DIRECTORY_FLAGS)
    info = os.fstat(descriptor)
    identities = [(info.st_dev, info.st_ino)]
    try:
        for part in path.parts[1:]:
            child = os.open(part, _DIRECTORY_FLAGS, dir_fd=descriptor)
            previous, descriptor = descriptor, child
            os.close(previous)
            info = os.fstat(descriptor)
            identities.append((info.st_dev, info.st_ino))
        return descriptor, identities
    except BaseException:
        os.close(descriptor)
        raise


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _check_directory(path, identities):
    descriptor, observed = _directory(path)
    try:
        _require(observed == identities, "artifact_output_changed")
    finally:
        os.close(descriptor)


def _file(descriptor, identity, *, directory=None):
    before = os.fstat(descriptor)
    _require(stat.S_ISREG(before.st_mode) and before.st_nlink == (0 if directory is None else 1)
             and before.st_size == identity["bytes"]
             and (directory is None or _stamp(os.stat(
                 _FINAL, dir_fd=directory, follow_symlinks=False)) == _stamp(before)),
             "artifact_output_changed")
    digest, count = hashlib.sha256(), 0
    os.lseek(descriptor, 0, os.SEEK_SET)
    while True:
        body = os.read(descriptor, min(CHUNK_BYTES, identity["bytes"] - count + 1))
        if not body:
            break
        count += len(body)
        _require(count <= identity["bytes"], "artifact_download_size")
        digest.update(body)
    _require(count == identity["bytes"] and digest.hexdigest() == identity["sha256"],
             "artifact_download_digest")
    _require(_stamp(os.fstat(descriptor)) == _stamp(before)
             and (directory is None or _stamp(os.stat(
                 _FINAL, dir_fd=directory, follow_symlinks=False)) == _stamp(before)),
             "artifact_output_changed")
    return _stamp(before)


def _download_bytes(artifact_id, token, descriptor, size, digest):
    request = json.dumps({"artifact_id": artifact_id, "token": token,
                          "bytes": size, "sha256": digest}).encode("ascii")
    # A process deadline also bounds DNS and slow response headers, unlike socket timeouts.
    try:
        result = subprocess.run(
            [sys.executable, "-I", "-B", str(Path(__file__).resolve()),
             "--download-fd", str(descriptor)], input=request,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True,
            pass_fds=(descriptor,), cwd="/", timeout=DOWNLOAD_SECONDS,
            env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C", "TZ": "UTC"},
            check=False)
        _require(result.returncode == 0, "artifact_download")
    except GovernanceArtifactError:
        raise
    except Exception:
        raise GovernanceArtifactError("artifact_download") from None


def download_artifact(revision, run_id, run_attempt, token, output_dir, *, api):
    """Download one exact named original into a new directory; never replay its contents."""
    parent = directory = descriptor = None
    try:
        _arguments(revision, run_id, run_attempt, token)
        _require(callable(api), "artifact_api")
        path = _output_path(output_dir)
        parent, identities = _directory(path.parent)
        os.mkdir(path.name, mode=0o700, dir_fd=parent)
        directory = os.open(path.name, _DIRECTORY_FLAGS, dir_fd=parent)
        info = os.fstat(directory)
        identities.append((info.st_dev, info.st_ino))
        _check_directory(path, identities)
        identity, before = _observe(api, revision, run_id, run_attempt, token)
        # An unnamed inode needs no race-prone pathname deletion on acquisition failure.
        descriptor = os.open(".", os.O_RDWR | os.O_TMPFILE |
                             os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=directory)
        _download_bytes(identity["artifact_id"], token, descriptor,
                        identity["bytes"], identity["sha256"])
        recorded = _file(descriptor, identity)
        after_identity, after = _observe(api, revision, run_id, run_attempt, token)
        _require(after_identity == identity and before == after, "artifact_provider_changed")
        _check_directory(path, identities)
        _require(_stamp(os.fstat(descriptor)) == recorded, "artifact_output_changed")
        os.fsync(descriptor)
        # The exclusive descriptor link pins the verified inode without replacing a pathname.
        os.link("/proc/self/fd/" + str(descriptor), _FINAL,
                dst_dir_fd=directory, follow_symlinks=True)
        _file(descriptor, identity, directory=directory)
        _check_directory(path, identities)
        os.fsync(directory)
        return {"archive_path": str(path / _FINAL), **identity, "provider_observed_stable": True}
    except GovernanceArtifactError:
        raise
    except Exception:
        raise GovernanceArtifactError("artifact_acquisition") from None
    finally:
        # A published name may already belong to another writer; never unlink it on failure.
        for handle in (descriptor, directory, parent):
            if handle is not None:
                os.close(handle)


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    _require(remaining > 0, "artifact_download_time")
    return min(SOCKET_SECONDS, remaining)


def _context():
    # The convenience factory reads SSLKEYLOGFILE; construct the verified context directly.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_default_certs(ssl.Purpose.SERVER_AUTH)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def _request(url, headers, deadline):
    parsed = urlsplit(url)
    connection = http.client.HTTPSConnection(parsed.hostname, port=443,
                                             timeout=_remaining(deadline), context=_context())
    connection.set_debuglevel(0)
    try:
        target = parsed.path + (("?" + parsed.query) if parsed.query else "")
        connection.request("GET", target, headers=headers)
        if connection.sock is not None:
            connection.sock.settimeout(_remaining(deadline))
        response = connection.getresponse()
        _remaining(deadline)
        return connection, response
    except BaseException:
        connection.close()
        raise


def _header(response, name, *, required=False):
    values = [value for key, value in response.getheaders() if key.lower() == name.lower()]
    _require(len(values) <= 1 and (not required or len(values) == 1), "artifact_http_headers")
    return values[0] if values else None


def _storage_url(value):
    _require(type(value) is str and 0 < len(value) <= MAX_LOCATION_BYTES
             and all(33 <= ord(char) <= 126 for char in value) and "\\" not in value,
             "artifact_redirect")
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        _require(value.startswith("https://") and parsed.scheme == "https"
                 and type(host) is str and re.fullmatch(
                     r"productionresultssa[0-9]{1,4}\.blob\.core\.windows\.net", host)
                 and parsed.netloc == host and parsed.path.startswith("/")
                 and not parsed.path.startswith("//") and parsed.query and not parsed.fragment,
                 "artifact_redirect")
        decoded = unquote(parsed.path, errors="strict")
        _require("\\" not in decoded and not any(ord(char) < 32 or ord(char) == 127 for char in decoded)
                 and all(part not in (".", "..") for part in decoded.split("/")),
                 "artifact_redirect")
    except GovernanceArtifactError:
        raise
    except Exception:
        raise GovernanceArtifactError("artifact_redirect") from None
    return value


def _network_to_fd(artifact_id, token, descriptor, size, digest):
    deadline = time.monotonic() + DOWNLOAD_SECONDS
    api_url = API_ORIGIN + API_PREFIX + "artifacts/" + str(artifact_id) + "/zip"
    connection, response = _request(api_url, {
        "Accept": "application/vnd.github+json", "Authorization": "Bearer " + token,
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": CONTRACT_ID}, deadline)
    try:
        _require(response.status == 302, "artifact_download_status")
        location = _storage_url(_header(response, "Location", required=True))
    finally:
        response.close()
        connection.close()
    # Only the authenticated API Location authorizes this hop; the host grammar is a bound.
    connection, response = _request(location, {"Accept": "application/octet-stream",
                                              "User-Agent": CONTRACT_ID}, deadline)
    try:
        _require(response.status == 200, "artifact_download_status")
        length = _header(response, "Content-Length", required=True)
        _require(type(length) is str and re.fullmatch(r"[1-9][0-9]{0,9}", length)
                 and int(length) == size and size <= MAX_ARCHIVE_BYTES, "artifact_download_size")
        _require(_header(response, "Transfer-Encoding") is None
                 and _header(response, "Content-Encoding") in (None, "identity"),
                 "artifact_http_encoding")
        initial = os.fstat(descriptor)
        _require(stat.S_ISREG(initial.st_mode) and initial.st_nlink == 0 and initial.st_size == 0,
                 "artifact_output_changed")
        count, observed = 0, hashlib.sha256()
        with os.fdopen(os.dup(descriptor), "wb") as stream:
            while True:
                if connection.sock is not None:
                    connection.sock.settimeout(_remaining(deadline))
                body = response.read1(min(CHUNK_BYTES, size - count + 1))
                _remaining(deadline)
                if not body:
                    break
                count += len(body)
                _require(count <= size, "artifact_download_size")
                observed.update(body)
                stream.write(body)
            _require(count == size and observed.hexdigest() == digest, "artifact_download_digest")
    finally:
        response.close()
        connection.close()


def _main():
    try:
        _require(len(sys.argv) == 3 and sys.argv[1] == "--download-fd"
                 and re.fullmatch(r"[0-9]{1,8}", sys.argv[2]), "artifact_worker")
        descriptor = int(sys.argv[2])
        _require(descriptor >= 3, "artifact_worker")
        body = sys.stdin.buffer.read(1025)
        _require(0 < len(body) <= 1024, "artifact_worker")
        value = json.loads(body)
        _require(type(value) is dict and set(value) == {"artifact_id", "token", "bytes", "sha256"}
                 and _integer(value["artifact_id"]) and type(value["bytes"]) is int
                 and 0 < value["bytes"] <= MAX_ARCHIVE_BYTES
                 and type(value["sha256"]) is str and re.fullmatch(r"[0-9a-f]{64}", value["sha256"]),
                 "artifact_worker")
        _arguments("0" * 40, value["artifact_id"], 1, value["token"])
        _network_to_fd(value["artifact_id"], value["token"], descriptor,
                       value["bytes"], value["sha256"])
        return 0
    except BaseException:
        return 2


if __name__ == "__main__":
    raise SystemExit(_main())
