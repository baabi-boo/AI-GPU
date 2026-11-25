# SPDX-License-Identifier: Apache-2.0
"""Offline provider-binding and bounded HTTPS governance acquisition checks."""

from copy import deepcopy
import errno
import hashlib
import http.client
import io
import json
import os
from pathlib import Path
import ssl
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlsplit

import p06_governance_artifact as artifact


REVISION = "f3123513bb5bc5fa1c409bf0e7366d2f47c2d85b"
RUN_ID = 45625012254
ATTEMPT = 1
ARTIFACT_ID = 15032214051
REPOSITORY_ID = 1457409699
TOKEN = "fixture_token_DO_NOT_PRINT"
BODY = b"Synthetic governance transport bytes; semantic replay is separate."
DIGEST = hashlib.sha256(BODY).hexdigest()
STORAGE = "https://productionresultssa100.blob.core.windows.net/results/original.zip?sig=DO-NOT-PRINT"


def metadata():
    endpoint = artifact.API_ORIGIN + artifact.API_PREFIX + "artifacts/" + str(ARTIFACT_ID)
    return {"id": ARTIFACT_ID,
            "name": f"project-governance-{REVISION}-run{RUN_ID}-attempt{ATTEMPT}",
            "size_in_bytes": len(BODY), "url": endpoint, "archive_download_url": endpoint + "/zip",
            "expired": False, "created_at": "2026-11-25T14:38:09Z",
            "updated_at": "2026-11-25T14:38:09Z", "expires_at": "2099-12-25T14:38:08Z",
            "digest": "sha256:" + DIGEST,
            "workflow_run": {"id": RUN_ID, "repository_id": REPOSITORY_ID,
                             "head_repository_id": REPOSITORY_ID, "head_branch": "master",
                             "head_sha": REVISION}}


def run_metadata():
    return {"id": RUN_ID, "run_attempt": ATTEMPT, "workflow_id": 314,
            "path": artifact.WORKFLOW, "head_sha": REVISION, "head_branch": "master",
            "event": "push", "status": "completed", "conclusion": "success",
            "repository": {"id": REPOSITORY_ID, "full_name": artifact.REPOSITORY},
            "head_repository": {"id": REPOSITORY_ID, "full_name": artifact.REPOSITORY}}


class ProviderArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.run = run_metadata()
        self.rows = [metadata()]
        self.detail = metadata()
        self.after_download = None
        self.overrides = {}
        self.calls = []
        self.sequence = 0
        self.output = None
        self.download_descriptor = None

    def api(self, path, token):
        self.calls.append((path, token))
        if path in self.overrides:
            return deepcopy(self.overrides[path])
        if path == artifact.API_PREFIX + "runs/" + str(RUN_ID):
            return deepcopy(self.run)
        if path == artifact.API_PREFIX + "artifacts/" + str(self.detail["id"]):
            return deepcopy(self.detail)
        if path.startswith(artifact.API_PREFIX + f"runs/{RUN_ID}/artifacts?"):
            query = parse_qs(urlsplit(path).query)
            self.assertEqual(query["per_page"], ["100"])
            page = int(query["page"][0])
            return {"total_count": len(self.rows), "artifacts": deepcopy(
                self.rows[(page - 1) * artifact.PAGE_SIZE:page * artifact.PAGE_SIZE])}
        self.fail("unexpected provider path")

    def write(self, artifact_id, token, descriptor, size, digest):
        self.assertEqual((artifact_id, token, size, digest), (ARTIFACT_ID, TOKEN, len(BODY), DIGEST))
        self.download_descriptor = descriptor
        os.write(descriptor, BODY)
        if self.after_download is not None:
            self.after_download()

    def download(self, *, api=None, writer=None, output=None, **changes):
        self.sequence += 1
        self.output = output if output is not None else self.root / ("out" + str(self.sequence))
        arguments = {"revision": REVISION, "run_id": RUN_ID, "run_attempt": ATTEMPT,
                     "token": TOKEN, "output_dir": self.output, "api": self.api if api is None else api}
        arguments.update(changes)
        with mock.patch.object(artifact, "_download_bytes", side_effect=self.write if writer is None else writer):
            return artifact.download_artifact(**arguments)

    def reject(self, **arguments):
        with self.assertRaises(artifact.GovernanceArtifactError) as failure:
            self.download(**arguments)
        self.assertRegex(str(failure.exception), r"^artifact_[a-z_]+$")
        self.assertNotIn(TOKEN, str(failure.exception))
        self.assertNotIn(STORAGE, str(failure.exception))
        if self.output is not None and self.output.is_dir():
            self.assertFalse((self.output / artifact._FINAL).exists())

    def test_exact_current_api_shape_downloads_and_retains_only_safe_identity(self):
        def anonymous_writer(*arguments):
            self.assertEqual(list(self.output.iterdir()), [])
            self.assertEqual(os.fstat(arguments[2]).st_nlink, 0)
            self.write(*arguments)

        result = self.download(writer=anonymous_writer)
        path = Path(result.pop("archive_path"))
        self.assertEqual(path.read_bytes(), BODY)
        self.assertEqual(path.stat().st_nlink, 1)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(list(self.output.iterdir()), [path])
        self.assertEqual(result["artifact_id"], ARTIFACT_ID)
        self.assertEqual(result["artifact_name"], metadata()["name"])
        self.assertEqual(result["sha256"], DIGEST)
        self.assertEqual(result["bytes"], len(BODY))
        self.assertEqual(result["repository"], artifact.REPOSITORY)
        self.assertEqual(result["repository_id"], REPOSITORY_ID)
        self.assertEqual(result["head_sha"], REVISION)
        self.assertEqual((result["run_id"], result["run_attempt"]), (RUN_ID, ATTEMPT))
        self.assertTrue(result["provider_observed_stable"])
        public = json.dumps(result)
        self.assertNotIn("https:", public)
        self.assertNotIn(TOKEN, public)
        self.assertNotIn("independent_packet_replay", result)
        self.assertEqual(len(self.calls), 8)
        self.assertTrue(all(token == TOKEN for _, token in self.calls))

    def test_arguments_reject_aliases_booleans_and_header_injection_before_api(self):
        changes = [("revision", value) for value in (None, "master", "a" * 39, "A" * 40, REVISION + "\n")]
        changes += [(key, value) for key in ("run_id", "run_attempt")
                    for value in (True, 0, -1, "1", 10**20)]
        changes += [("token", value) for value in (None, "", TOKEN + "\r\nInjected: secret", "a" * 257)]
        for key, value in changes:
            with self.subTest(key=key, value=value):
                api = mock.Mock()
                self.reject(api=api, **{key: value})
                api.assert_not_called()

    def test_run_must_be_successful_exact_source_workflow_and_current_attempt(self):
        changes = {"id": True, "run_attempt": 2, "workflow_id": True,
                   "path": ".github/workflows/lookalike.yml", "head_sha": "a" * 40,
                   "head_branch": "topic", "event": "pull_request", "status": "in_progress",
                   "conclusion": "failure", "repository": {"id": REPOSITORY_ID, "full_name": "fork/AI-GPU"},
                   "head_repository": {"id": REPOSITORY_ID + 1, "full_name": artifact.REPOSITORY}}
        for key, value in changes.items():
            with self.subTest(key=key):
                self.run = dict(run_metadata(), **{key: value})
                self.reject()
        self.run = run_metadata()
        self.run["repository"]["id"] = True
        self.reject()

    def test_full_exact_name_rejects_wrong_revision_run_attempt_and_prefix_aliases(self):
        names = (metadata()["name"] + "-copy", "copy-" + metadata()["name"],
                 metadata()["name"].replace(REVISION, "a" * 40),
                 metadata()["name"].replace("attempt1", "attempt2"),
                 metadata()["name"].replace(str(RUN_ID), str(RUN_ID + 1)))
        for name in names:
            with self.subTest(name=name):
                self.rows = [dict(metadata(), name=name)]
                self.reject()

    def test_duplicate_exact_candidates_or_artifact_ids_fail_closed(self):
        for extra in (dict(metadata(), id=ARTIFACT_ID + 1),
                      dict(metadata(), name="other"), metadata()):
            with self.subTest(extra=extra["name"]):
                self.rows = [metadata(), extra]
                self.reject()

    def test_expiry_digest_size_and_exact_api_endpoint_are_required(self):
        changes = [("expired", value) for value in (True, 0, None)]
        changes += [("digest", value) for value in (None, DIGEST, "sha256:" + "A" * 64,
                                                   "sha512:" + DIGEST, "sha256:" + "0" * 63)]
        changes += [("size_in_bytes", value) for value in (True, 0, -1, artifact.MAX_ARCHIVE_BYTES + 1)]
        changes += [("url", metadata()["url"] + "/"), ("archive_download_url", STORAGE),
                    ("archive_download_url", metadata()["archive_download_url"] + "?token=private"),
                    ("expires_at", "2000-01-01T00:00:00Z"), ("created_at", "2099-12-26T00:00:00Z"),
                    ("updated_at", "2026-13-25T14:38:09Z"), ("created_at", "2026-11-25T14:38:09+00:00")]
        for key, value in changes:
            with self.subTest(key=key, value=value):
                self.rows = [dict(metadata(), **{key: value})]
                self.reject()

    def test_workflow_run_joins_numeric_repository_and_head_source_identities(self):
        changes = {"id": RUN_ID + 1, "repository_id": REPOSITORY_ID + 1,
                   "head_repository_id": REPOSITORY_ID + 1, "head_branch": "topic",
                   "head_sha": "b" * 40, "run_attempt": 2}
        for key, value in changes.items():
            with self.subTest(key=key):
                row = metadata()
                row["workflow_run"][key] = value
                self.rows = [row]
                self.reject()
        for key in ("id", "repository_id", "head_repository_id", "run_attempt"):
            with self.subTest(boolean=key):
                row = metadata()
                row["workflow_run"][key] = True
                self.rows = [row]
                self.reject()

    def test_provider_attempt_field_if_present_must_match(self):
        self.rows[0]["workflow_run"]["run_attempt"] = ATTEMPT
        self.detail["workflow_run"]["run_attempt"] = ATTEMPT
        self.assertEqual(self.download()["run_attempt"], ATTEMPT)

    def test_detail_must_agree_with_listed_artifact_identity(self):
        for key, value in (("digest", "sha256:" + "0" * 64),
                           ("updated_at", "2026-11-25T14:38:10Z"), ("size_in_bytes", len(BODY) + 1)):
            with self.subTest(key=key):
                self.detail = dict(metadata(), **{key: value})
                self.reject()

    def test_successful_snapshot_must_remain_unchanged_after_download(self):
        def changed_run():
            self.run["updated_at"] = "2026-11-25T14:38:10Z"

        def changed_attempt():
            self.run["run_attempt"] = 2

        def changed_detail():
            self.detail["node_id"] = "changed-observation"

        def changed_population():
            self.rows.append({"id": ARTIFACT_ID + 1, "name": "other"})

        for change in (changed_run, changed_attempt, changed_detail, changed_population):
            with self.subTest(change=change.__name__):
                self.run, self.rows, self.detail = run_metadata(), [metadata()], metadata()
                self.after_download = change
                self.reject()

    def test_api_exception_text_and_large_or_non_json_metadata_are_sanitized(self):
        for error in (OSError(STORAGE + TOKEN), ValueError(STORAGE + TOKEN),
                      artifact.GovernanceArtifactError(STORAGE + TOKEN)):
            with self.subTest(error=type(error).__name__):
                self.reject(api=mock.Mock(side_effect=error))
        for result in ([], {"huge": "x" * artifact.MAX_API_BYTES}, {"nan": float("nan")}, {"bad": object()}):
            with self.subTest(type=type(result).__name__):
                self.reject(api=mock.Mock(return_value=result))

    def test_bounded_complete_pagination_can_find_candidate_on_second_page(self):
        self.rows = [{"id": index + 1, "name": "other-" + str(index)} for index in range(100)]
        self.rows.append(metadata())
        result = self.download()
        self.assertEqual(result["artifact_id"], ARTIFACT_ID)
        self.assertEqual(sum(path.endswith("page=3") for path, _ in self.calls), 2)

    def test_pagination_gaps_count_changes_and_unadvertised_tail_are_rejected(self):
        page = artifact.API_PREFIX + f"runs/{RUN_ID}/artifacts?per_page=100&page="
        cases = [(1, {"total_count": True, "artifacts": [metadata()]}),
                 (1, {"total_count": -1, "artifacts": []}),
                 (1, {"total_count": artifact.MAX_ARTIFACTS + 1, "artifacts": []}),
                 (1, {"total_count": 100, "artifacts": [metadata()]}),
                 (1, {"total_count": 1, "artifacts": {}}),
                 (2, {"total_count": 2, "artifacts": []}),
                 (2, {"total_count": 1, "artifacts": [{"id": 1, "name": "hidden"}]})]
        for number, document in cases:
            with self.subTest(number=number, document=document):
                self.overrides = {page + str(number): document}
                self.reject()

    def test_duplicate_ids_across_pages_cannot_hide_a_missing_artifact(self):
        self.rows = [{"id": index + 1, "name": "other-" + str(index)} for index in range(99)]
        self.rows += [metadata(), {"id": 1, "name": "duplicate"}]
        self.reject()

    def test_download_corruption_short_write_and_failures_leave_no_complete_file(self):
        def corrupt(_id, _token, descriptor, _size, _digest):
            os.write(descriptor, b"X" * len(BODY))

        def short(_id, _token, descriptor, _size, _digest):
            os.write(descriptor, BODY[:-1])

        def failed(_id, _token, descriptor, _size, _digest):
            os.write(descriptor, BODY)
            raise OSError(STORAGE + TOKEN)

        for writer in (corrupt, short, failed):
            with self.subTest(writer=writer.__name__):
                self.reject(writer=writer)
                self.assertEqual(list(self.output.iterdir()), [])

    def test_unsupported_anonymous_staging_fails_without_a_named_fallback(self):
        original_open = os.open

        def unsupported(path, flags, *args, **options):
            if flags & os.O_TMPFILE == os.O_TMPFILE:
                raise OSError(errno.EOPNOTSUPP, STORAGE + TOKEN)
            return original_open(path, flags, *args, **options)

        writer = mock.Mock()
        with mock.patch.object(artifact.os, "open", side_effect=unsupported):
            self.reject(writer=writer)
        writer.assert_not_called()
        self.assertEqual(list(self.output.iterdir()), [])

    def test_output_directory_must_be_fresh_and_have_no_symlink_ancestors(self):
        occupied = self.root / "occupied"
        occupied.mkdir()
        sentinel = occupied / "owned.txt"
        sentinel.write_text("preserve")
        api = mock.Mock()
        self.reject(output=occupied, api=api)
        api.assert_not_called()
        alias = self.root / "alias"
        alias.symlink_to(occupied, target_is_directory=True)
        self.reject(output=alias / "child", api=api)
        self.reject(output=alias, api=api)
        self.assertEqual(sentinel.read_text(), "preserve")
        self.assertFalse((occupied / "child").exists())

    def test_output_path_rejects_relative_traversal_and_url_forms(self):
        for value in ("relative", "/tmp/../output", "/tmp//output", "/tmp/output/", STORAGE,
                      "/tmp/new\noutput", "/tmp/" + "x" * 256, 1):
            with self.subTest(value=value):
                with self.assertRaises(artifact.GovernanceArtifactError):
                    artifact.download_artifact(REVISION, RUN_ID, ATTEMPT, TOKEN, value, api=self.api)
        self.assertEqual(self.calls, [])

    def test_existing_final_file_or_symlink_is_not_overwritten(self):
        sentinel = self.root / "sentinel"
        sentinel.write_bytes(b"preserve")
        for kind in ("file", "symlink"):
            def occupy():
                target = self.output / artifact._FINAL
                if kind == "file":
                    target.write_bytes(b"preserve")
                else:
                    target.symlink_to(sentinel)

            with self.subTest(kind=kind):
                self.after_download = occupy
                with self.assertRaises(artifact.GovernanceArtifactError):
                    self.download()
                self.assertEqual((self.output / artifact._FINAL).read_bytes(), b"preserve")
                self.assertEqual(list(self.output.iterdir()), [self.output / artifact._FINAL])
                self.assertEqual(sentinel.read_bytes(), b"preserve")

    def test_directory_replacement_is_detected_and_anonymous_staging_is_discarded(self):
        alternative = self.root / "alternative"
        alternative.mkdir()
        moved = self.root / "moved"

        def replace():
            self.output.rename(moved)
            self.output.symlink_to(alternative, target_is_directory=True)

        self.after_download = replace
        self.reject()
        self.assertEqual(list(moved.iterdir()), [])
        self.assertEqual(list(alternative.iterdir()), [])

    def test_unrelated_staging_name_never_reads_or_overwrites_its_symlink_target(self):
        sentinel = self.root / "sentinel"
        sentinel.write_bytes(b"preserve")

        def replace():
            (self.output / ".governance.partial").symlink_to(sentinel)

        self.after_download = replace
        result = self.download()
        self.assertEqual(Path(result["archive_path"]).read_bytes(), BODY)
        self.assertEqual(sentinel.read_bytes(), b"preserve")
        self.assertTrue((self.output / ".governance.partial").is_symlink())

    def test_hardlink_to_anonymous_staging_prevents_completion_and_is_preserved(self):
        def link():
            directory = os.open(self.root, artifact._DIRECTORY_FLAGS)
            try:
                os.link("/proc/self/fd/" + str(self.download_descriptor), "extra-link",
                        dst_dir_fd=directory, follow_symlinks=True)
            finally:
                os.close(directory)

        self.after_download = link
        self.reject()
        self.assertEqual((self.root / "extra-link").read_bytes(), BODY)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_mutation_during_provider_reobservation_prevents_completion(self):
        observed = 0

        def api(path, token):
            nonlocal observed
            if path == artifact.API_PREFIX + "runs/" + str(RUN_ID):
                observed += 1
                if observed == 2:
                    os.pwrite(self.download_descriptor, b"X" * len(BODY), 0)
            return self.api(path, token)

        self.reject(api=api)

    def test_unrelated_symlink_at_publication_cannot_substitute_anonymous_bytes(self):
        sentinel = self.root / "sentinel"
        sentinel.write_bytes(b"unverified replacement")
        original_link = os.link

        def replace(source, destination, **options):
            (self.output / ".governance.partial").symlink_to(sentinel)
            return original_link(source, destination, **options)

        with mock.patch.object(artifact.os, "link", side_effect=replace):
            result = self.download()
        self.assertEqual(Path(result["archive_path"]).read_bytes(), BODY)
        self.assertEqual(sentinel.read_bytes(), b"unverified replacement")
        self.assertTrue((self.output / ".governance.partial").is_symlink())

    def test_final_replacement_after_publication_is_preserved_and_rejected(self):
        replacement = self.root / "replacement"
        replacement.write_bytes(b"unverified replacement")
        original_link = os.link

        def replace(source, destination, **options):
            original_link(source, destination, **options)
            os.replace(replacement, destination, dst_dir_fd=options["dst_dir_fd"])

        with mock.patch.object(artifact.os, "link", side_effect=replace):
            with self.assertRaisesRegex(artifact.GovernanceArtifactError, "^artifact_output_changed$"):
                self.download()
        self.assertEqual((self.output / artifact._FINAL).read_bytes(), b"unverified replacement")

    def test_failed_directory_sync_cannot_delete_replacement_after_ownership_stat(self):
        replacement = self.root / "replacement"
        replacement.write_bytes(b"unrelated replacement")
        original_stat = os.stat
        original_fsync = os.fsync
        failed = False

        def fail_directory_sync(descriptor):
            nonlocal failed
            if stat.S_ISDIR(os.fstat(descriptor).st_mode):
                failed = True
                raise OSError(STORAGE + TOKEN)
            return original_fsync(descriptor)

        def substitute_after_stat(path, *args, **options):
            info = original_stat(path, *args, **options)
            if failed and path == artifact._FINAL and options.get("dir_fd") is not None:
                os.replace(replacement, path, dst_dir_fd=options["dir_fd"])
            return info

        with mock.patch.object(artifact.os, "fsync", side_effect=fail_directory_sync), \
                mock.patch.object(artifact.os, "stat", side_effect=substitute_after_stat):
            with self.assertRaisesRegex(artifact.GovernanceArtifactError, "^artifact_acquisition$"):
                self.download()
        self.assertTrue(failed)
        retained = [path.read_bytes() for path in (replacement, self.output / artifact._FINAL)
                    if path.exists()]
        self.assertIn(b"unrelated replacement", retained)


class ArtifactHttpsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.descriptor = os.open(self.temporary.name, os.O_RDWR | os.O_TMPFILE |
                                  os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        self.addCleanup(os.close, self.descriptor)
        self.path = Path("/proc/self/fd/" + str(self.descriptor))
        self.requests = []
        self.connections = []

    def exchange(self, api=None, storage=None):
        api = (b"HTTP/1.1 302 Found\r\nLocation: " + STORAGE.encode("ascii") +
               b"\r\nContent-Length: 0\r\n\r\n") if api is None else api
        storage = (b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(BODY)).encode("ascii") +
                   b"\r\n\r\n" + BODY) if storage is None else storage
        replies = [api, storage]
        owner = self

        class Socket:
            def __init__(self, reply):
                self.reply = reply

            def makefile(self, _mode):
                return io.BytesIO(self.reply)

            def sendall(self, body):
                owner.requests.append(body)

            def settimeout(self, timeout):
                owner.assertGreater(timeout, 0)
                owner.assertLessEqual(timeout, artifact.SOCKET_SECONDS)

            def close(self):
                pass

        def connect(connection):
            self.connections.append(connection)
            self.assertTrue(replies, "unexpected additional network hop")
            connection.sock = Socket(replies.pop(0))

        with mock.patch.object(http.client.HTTPSConnection, "connect", new=connect):
            artifact._network_to_fd(ARTIFACT_ID, TOKEN, self.descriptor, len(BODY), DIGEST)

    def test_real_http_parser_uses_exact_api_and_unauthenticated_storage_hop(self):
        self.exchange()
        self.assertEqual(self.path.read_bytes(), BODY)
        self.assertEqual(os.fstat(self.descriptor).st_nlink, 0)
        self.assertEqual(list(Path(self.temporary.name).iterdir()), [])
        self.assertEqual(len(self.connections), 2)
        self.assertEqual([value.host for value in self.connections],
                         ["api.github.com", "productionresultssa100.blob.core.windows.net"])
        self.assertIn(("GET " + artifact.API_PREFIX + f"artifacts/{ARTIFACT_ID}/zip HTTP/1.1").encode(),
                      self.requests[0])
        self.assertIn(("Authorization: Bearer " + TOKEN).encode(), self.requests[0])
        self.assertNotIn(b"Authorization", self.requests[1])
        self.assertNotIn(TOKEN.encode(), self.requests[1])
        self.assertNotIn(b"Cookie", self.requests[1])

    def test_worker_rejects_linked_download_descriptor_before_writing(self):
        directory = os.open(self.temporary.name, artifact._DIRECTORY_FLAGS)
        try:
            os.link(self.path, "unrelated", dst_dir_fd=directory, follow_symlinks=True)
        finally:
            os.close(directory)
        with self.assertRaisesRegex(artifact.GovernanceArtifactError, "^artifact_output_changed$"):
            self.exchange()
        self.assertEqual(self.path.read_bytes(), b"")

    def test_ambient_proxy_key_logging_and_http_debug_do_not_disclose_credentials(self):
        keylog = Path(self.temporary.name) / "keylog"
        with mock.patch.dict(os.environ, {"SSLKEYLOGFILE": str(keylog), "HTTPS_PROXY": STORAGE,
                                         "HTTP_PROXY": STORAGE, "ALL_PROXY": STORAGE}), \
                mock.patch.object(http.client.HTTPConnection, "debuglevel", 1), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as stdout, \
                mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            self.exchange()
            self.assertEqual(stdout.getvalue() + stderr.getvalue(), "")
        self.assertFalse(keylog.exists())
        for connection in self.connections:
            self.assertIsNone(connection._context.keylog_filename)
            self.assertEqual(connection._context.verify_mode, ssl.CERT_REQUIRED)
            self.assertTrue(connection._context.check_hostname)
            self.assertGreater(connection._context.cert_store_stats()["x509_ca"], 0)
            self.assertEqual(connection.debuglevel, 0)

    def test_api_must_return_exactly_one_302_location(self):
        replies = [f"HTTP/1.1 {status} Nope\r\nContent-Length: 0\r\n\r\n".encode()
                   for status in (200, 301, 303, 307, 308, 401, 404)]
        replies += [b"HTTP/1.1 302 Found\r\nContent-Length: 0\r\n\r\n",
                    b"HTTP/1.1 302 Found\r\nLocation: " + STORAGE.encode() + b"\r\nLocation: " +
                    STORAGE.encode() + b"\r\nContent-Length: 0\r\n\r\n"]
        for reply in replies:
            with self.subTest(reply=reply[:30]), self.assertRaises(artifact.GovernanceArtifactError):
                self.exchange(api=reply)
        self.assertEqual(self.path.read_bytes(), b"")

    def test_storage_cannot_redirect_return_partial_content_or_fail_status(self):
        for status in (201, 206, 301, 302, 307, 308, 401, 404):
            reply = (f"HTTP/1.1 {status} Nope\r\nLocation: {STORAGE}\r\n"
                     "Content-Length: 0\r\n\r\n").encode()
            with self.subTest(status=status), self.assertRaises(artifact.GovernanceArtifactError):
                self.exchange(storage=reply)
        self.assertEqual(self.path.read_bytes(), b"")

    def test_redirect_url_is_bounded_to_canonical_https_provider_storage(self):
        values = [None, "", STORAGE.replace("https://", "http://"), STORAGE + "#fragment",
                  STORAGE.replace("https://", "https://name:password@"),
                  STORAGE.replace(".net/", ".net:443/"), STORAGE.replace(".net/", ".net:8443/"),
                  STORAGE.replace("productionresultssa100", "otheraccount"),
                  STORAGE.replace("productionresultssa100", "productionresultssa10000"),
                  STORAGE.replace(".net/", ".net.evil.invalid/"),
                  STORAGE.replace("productionresultssa100", "PRODUCTIONRESULTSSA100"),
                  "https://127.0.0.1/a?sig=x", "https://[::1]/a?sig=x", "/relative?sig=x",
                  STORAGE.replace("/results/", "/../"), STORAGE.replace("/results/", "/%2e%2e/"),
                  STORAGE.replace("/results/", "/%00/"), STORAGE.replace("/results/", "/%5c/"),
                  STORAGE.replace("/results/", "//results/"), STORAGE.split("?")[0],
                  STORAGE + "\r\nInjected: secret", STORAGE + "\\escape", STORAGE + "x" * 8192]
        for value in values:
            with self.subTest(value=value), self.assertRaises(artifact.GovernanceArtifactError):
                artifact._storage_url(value)
        for number in (0, 30, 49, 100, 199):
            value = STORAGE.replace("productionresultssa100", "productionresultssa" + str(number))
            self.assertEqual(artifact._storage_url(value), value)

    def test_rejected_redirect_never_reaches_second_connection(self):
        reply = b"HTTP/1.1 302 Found\r\nLocation: https://private.invalid/token\r\nContent-Length: 0\r\n\r\n"
        with self.assertRaises(artifact.GovernanceArtifactError):
            self.exchange(api=reply)
        self.assertEqual(len(self.connections), 1)

    def test_storage_length_encoding_and_duplicate_header_checks_precede_writing(self):
        headers = [b"", b"Content-Length: 0\r\n", b"Content-Length: 01\r\n",
                   b"Content-Length: " + str(len(BODY) + 1).encode() + b"\r\n",
                   b"Content-Length: " + str(len(BODY) - 1).encode() + b"\r\n",
                   ("Content-Length: " + str(len(BODY)) + "\r\n").encode() * 2,
                   ("Content-Length: " + str(len(BODY)) + "\r\nContent-Encoding: gzip\r\n").encode(),
                   ("Content-Length: " + str(len(BODY)) + "\r\nTransfer-Encoding: chunked\r\n").encode()]
        for header in headers:
            with self.subTest(header=header), self.assertRaises(artifact.GovernanceArtifactError):
                self.exchange(storage=b"HTTP/1.1 200 OK\r\n" + header + b"\r\n" + BODY)
        self.assertEqual(self.path.read_bytes(), b"")

    def test_stream_hash_and_short_body_are_checked(self):
        for body in (b"X" * len(BODY), BODY[:-1]):
            with self.subTest(body=body):
                os.ftruncate(self.descriptor, 0)
                os.lseek(self.descriptor, 0, os.SEEK_SET)
                response = ("HTTP/1.1 200 OK\r\nContent-Length: " + str(len(BODY)) + "\r\n\r\n").encode() + body
                with self.assertRaises(artifact.GovernanceArtifactError):
                    self.exchange(storage=response)

    def test_stream_cannot_cross_deadline_even_when_reads_keep_returning_bytes(self):
        redirect = mock.Mock(status=302)
        redirect.getheaders.return_value = [("Location", STORAGE)]
        response = mock.Mock(status=200)
        response.getheaders.return_value = [("Content-Length", str(len(BODY)))]
        connection = mock.Mock(sock=None)
        with mock.patch.object(artifact.time, "monotonic", return_value=0) as clock:
            def read(_count):
                clock.return_value = artifact.DOWNLOAD_SECONDS + 1
                return b"x"

            response.read1.side_effect = read
            with mock.patch.object(artifact, "_request", side_effect=[(connection, redirect), (connection, response)]):
                with self.assertRaisesRegex(artifact.GovernanceArtifactError, "artifact_download_time"):
                    artifact._network_to_fd(ARTIFACT_ID, TOKEN, self.descriptor, len(BODY), DIGEST)
        self.assertEqual(self.path.read_bytes(), b"")

    def test_worker_subprocess_has_wall_deadline_secret_stdin_and_closed_environment(self):
        with mock.patch.dict(os.environ, {"SSLKEYLOGFILE": STORAGE, "HTTPS_PROXY": STORAGE,
                                         "PYTHONPATH": STORAGE, "GITHUB_TOKEN": TOKEN}), \
                mock.patch.object(artifact.subprocess, "run", return_value=mock.Mock(returncode=0)) as child:
            artifact._download_bytes(ARTIFACT_ID, TOKEN, self.descriptor, len(BODY), DIGEST)
        args, options = child.call_args.args[0], child.call_args.kwargs
        self.assertNotIn(TOKEN, " ".join(args))
        self.assertEqual(args[1:3], ["-I", "-B"])
        self.assertEqual(json.loads(options["input"])["token"], TOKEN)
        self.assertEqual(options["timeout"], artifact.DOWNLOAD_SECONDS)
        self.assertEqual(options["pass_fds"], (self.descriptor,))
        self.assertTrue(options["close_fds"])
        self.assertEqual(options["cwd"], "/")
        self.assertEqual(options["stdout"], subprocess.DEVNULL)
        self.assertEqual(options["stderr"], subprocess.DEVNULL)
        self.assertEqual(set(options["env"]), {"PATH", "LANG", "LC_ALL", "TZ"})

    def test_worker_timeout_and_child_errors_never_propagate_secret_exception_text(self):
        errors = [subprocess.TimeoutExpired(STORAGE, 1, output=TOKEN), OSError(STORAGE + TOKEN)]
        for error in errors:
            with self.subTest(error=type(error).__name__), mock.patch.object(
                    artifact.subprocess, "run", side_effect=error):
                with self.assertRaisesRegex(artifact.GovernanceArtifactError, "^artifact_download$"):
                    artifact._download_bytes(ARTIFACT_ID, TOKEN, self.descriptor, len(BODY), DIGEST)
        with mock.patch.object(artifact.subprocess, "run", return_value=mock.Mock(returncode=2)):
            with self.assertRaisesRegex(artifact.GovernanceArtifactError, "^artifact_download$"):
                artifact._download_bytes(ARTIFACT_ID, TOKEN, self.descriptor, len(BODY), DIGEST)

    def test_real_isolated_worker_rejects_invalid_input_without_network_or_output(self):
        result = subprocess.run([sys.executable, "-I", "-B", str(Path(artifact.__file__).resolve()),
                                 "--download-fd", str(self.descriptor)],
                                input=b'{"artifact_id":false}', stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=5, pass_fds=(self.descriptor,), check=False)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (2, b"", b""))
        self.assertEqual(self.path.read_bytes(), b"")


if __name__ == "__main__":
    unittest.main()
