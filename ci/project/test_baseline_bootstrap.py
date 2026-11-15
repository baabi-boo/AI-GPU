# Licensed under the Apache License, Version 2.0.
"""Independent installer checks with local miniature archives and fake HTTP."""

from contextlib import redirect_stdout
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import baseline_bootstrap as bootstrap


def part_record(path, data):
    return {
        "path": path, "size_bytes": len(data),
        "git_blob_sha": hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest(),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def archive_bytes(members):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:bz2") as archive:
        for name, kind, data in members:
            item = tarfile.TarInfo(name)
            item.mode = 0o755 if kind in ("directory", "executable") else 0o644
            if kind == "directory":
                item.type = tarfile.DIRTYPE
            elif kind in ("symlink", "hardlink"):
                item.type = tarfile.SYMTYPE if kind == "symlink" else tarfile.LNKTYPE
                item.linkname = data
            elif kind == "fifo":
                item.type = tarfile.FIFOTYPE
            else:
                item.size = len(data)
            archive.addfile(item, io.BytesIO(data) if item.isfile() else None)
    return output.getvalue()


class FakeResponse(io.BytesIO):
    def __init__(self, data, url):
        super().__init__(data)
        self.url = url

    def geturl(self):
        return self.url


class BootstrapFixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.tools = self.base / "tools"
        self.cache = self.base / "cache"
        self.manifest_path = self.base / "manifest.json"
        self.manifest = bootstrap.load_manifest()
        self.part_data = {}
        files = {}
        for name, path in bootstrap.inventory.TOOL_BINARIES.items():
            files[path] = ("executable", ("#!/bin/sh\nprintf '%s\\n' 'fixture " + name + " 1.0'\n").encode())
        for path in bootstrap.inventory.LIBRARIES:
            files[path] = ("file", ("fixture library " + path).encode())
        records = []
        for component in bootstrap.COMPONENTS:
            members = [(component, "directory", None)]
            members.extend((path, kind, data) for path, (kind, data) in files.items()
                           if path.startswith(component + "/"))
            payload = archive_bytes(members)
            paths = sorted(part["path"] for part in self.manifest["parts"]
                           if part["path"].startswith(component + "/"))
            for index, path in enumerate(paths):
                chunk = payload[len(payload) * index // len(paths):len(payload) * (index + 1) // len(paths)]
                self.part_data[path] = chunk
                records.append(part_record(path, chunk))
        self.manifest["parts"] = records
        self.write_manifest()
        self.production_anchor = bootstrap.inventory.TOOLCHAIN_MANIFEST_SHA256
        self.enterContext(mock.patch.object(bootstrap.inventory, "TOOLCHAIN_MANIFEST_SHA256",
                                           bootstrap.manifest_digest(self.manifest)))
        self.http = self.enterContext(mock.patch.object(bootstrap, "_open_url", side_effect=self.response))

    def write_manifest(self, data=None):
        self.manifest_path.write_text(json.dumps(self.manifest if data is None else data), encoding="utf-8")

    def response(self, url, timeout):
        prefix = ("https://raw.githubusercontent.com/" + bootstrap.inventory.TOOLCHAIN_REPOSITORY
                  + "/" + bootstrap.inventory.TOOLCHAIN_COMMIT + "/")
        self.assertTrue(url.startswith(prefix), url)
        self.assertEqual(timeout, 30)
        return FakeResponse(self.part_data[url.removeprefix(prefix)], url)

    def install(self):
        return bootstrap.install(self.tools, self.cache, self.manifest_path, min_free_bytes=1)

    def archive(self, members):
        path = self.base / "fixture.tar.bz2"
        path.write_bytes(archive_bytes(members))
        return path

    def extraction_root(self, name="unpacked"):
        root = self.base / name
        root.mkdir()
        return root


class ManifestTests(BootstrapFixture):
    def test_checked_in_lock_has_complete_immutable_identity(self):
        with mock.patch.object(bootstrap.inventory, "TOOLCHAIN_MANIFEST_SHA256", self.production_anchor):
            lock = bootstrap.load_manifest()
            bundle = bootstrap.inventory._bundle_identity(bootstrap.DEFAULT_MANIFEST)
        self.assertEqual(lock["revision"], "e3db4bcdf819a17f618ad9fc2472f8f7dea3192b")
        self.assertEqual(lock["repository"], "vortexgpgpu/vortex-toolchain-prebuilt")
        self.assertEqual(len(lock["parts"]), 18)
        self.assertEqual(sum(item["size_bytes"] for item in lock["parts"]), 720873529)
        self.assertEqual(bootstrap.manifest_digest(lock), self.production_anchor)
        self.assertEqual(bundle["parts"], lock["parts"])
        self.http.assert_not_called()

    def test_production_lock_accepts_equivalent_formatting_and_order(self):
        with mock.patch.object(bootstrap.inventory, "TOOLCHAIN_MANIFEST_SHA256", self.production_anchor):
            lock = bootstrap.load_manifest()
            reordered = dict(reversed(list(lock.items())))
            reordered["parts"] = [dict(reversed(list(part.items()))) for part in reversed(lock["parts"])]
            self.manifest_path.write_text(json.dumps(reordered, indent=4) + "\n", encoding="utf-8")
            loaded = bootstrap.load_manifest(self.manifest_path)
            bundle = bootstrap.inventory._bundle_identity(self.manifest_path)
        self.assertEqual(bootstrap.manifest_digest(loaded), self.production_anchor)
        self.assertEqual(bundle["parts"], reordered["parts"])
        self.http.assert_not_called()

    def test_production_lock_rejects_changed_archive_identity_with_unchanged_pin(self):
        with mock.patch.object(bootstrap.inventory, "TOOLCHAIN_MANIFEST_SHA256", self.production_anchor):
            lock = bootstrap.load_manifest()
            for field, value in (("size_bytes", lock["parts"][0]["size_bytes"] + 1),
                                 ("git_blob_sha", "0" * 40), ("sha256", "0" * 64)):
                with self.subTest(field=field):
                    changed = copy.deepcopy(lock)
                    changed["parts"][0][field] = value
                    self.write_manifest(changed)
                    with self.assertRaisesRegex(ValueError, "reviewed immutable lock"):
                        bootstrap.load_manifest(self.manifest_path)
                    with self.assertRaisesRegex(ValueError, "reviewed immutable lock"):
                        bootstrap.inventory._bundle_identity(self.manifest_path)
        self.http.assert_not_called()

    def test_manifest_rejects_pin_schema_coverage_and_type_changes(self):
        changes = [
            lambda d: d.update(revision="0" * 40),
            lambda d: d.update(repository="elsewhere/tools"),
            lambda d: d.update(unexpected=True),
            lambda d: d["parts"].pop(),
            lambda d: d["parts"].__setitem__(0, copy.deepcopy(d["parts"][1])),
            lambda d: d["parts"][0].update(path="../../outside"),
            lambda d: d["parts"][0].update(size_bytes=True),
            lambda d: d["parts"][0].update(size_bytes=0),
            lambda d: d["parts"][0].update(size_bytes=65 * bootstrap.CHUNK),
            lambda d: d["parts"][0].update(sha256="invalid"),
            lambda d: d["parts"][0].update(git_blob_sha="invalid"),
        ]
        for index, change in enumerate(changes):
            with self.subTest(index=index):
                data = copy.deepcopy(self.manifest)
                change(data)
                self.write_manifest(data)
                with self.assertRaises(ValueError):
                    bootstrap.load_manifest(self.manifest_path)

    def test_manifest_duplicate_json_nonfinite_symlink_and_size_are_rejected(self):
        for data in ('{"tag":"v3.0.2","tag":"v3.0.2"}', '{"parts":NaN}', '[' * 10):
            self.manifest_path.write_text(data)
            with self.assertRaises(ValueError):
                bootstrap.load_manifest(self.manifest_path)
        self.write_manifest()
        link = self.base / "manifest-link.json"
        link.symlink_to(self.manifest_path)
        with self.assertRaises(ValueError):
            bootstrap.load_manifest(link)
        with mock.patch.object(bootstrap, "_read_json", wraps=bootstrap._read_json):
            with self.assertRaises(ValueError):
                bootstrap._read_json(self.manifest_path, maximum=8)

    def test_manifest_digest_is_canonical_and_sensitive_to_content(self):
        reordered = dict(reversed(list(self.manifest.items())))
        reordered["parts"] = list(reversed(self.manifest["parts"]))
        self.assertEqual(bootstrap.manifest_digest(self.manifest), bootstrap.manifest_digest(reordered))
        changed = copy.deepcopy(reordered)
        changed["parts"][0]["sha256"] = "f" * 64
        self.assertNotEqual(bootstrap.manifest_digest(self.manifest), bootstrap.manifest_digest(changed))


class DownloadTests(BootstrapFixture):
    def test_part_verification_requires_size_and_both_digests(self):
        data = b"small pinned artifact"
        part = part_record("libc64/libc64.tar.bz2", data)
        path = self.base / "part"
        path.write_bytes(data)
        bootstrap.verify_part(path, part)
        for field in ("sha256", "git_blob_sha", "size_bytes"):
            with self.subTest(field=field):
                bad = dict(part)
                bad[field] = part[field] + 1 if field == "size_bytes" else "0" * len(part[field])
                with self.assertRaises(ValueError):
                    bootstrap.verify_part(path, bad)
        path.write_bytes(b"X" + data[1:])
        with self.assertRaises(ValueError):
            bootstrap.verify_part(path, part)
        link = self.base / "part-link"
        link.symlink_to(path)
        with self.assertRaises(ValueError):
            bootstrap.verify_part(link, part)

    def test_download_uses_immutable_url_and_verified_cache_without_refetch(self):
        self.cache.mkdir()
        part = self.manifest["parts"][0]
        path = bootstrap.download_part(part, self.cache, 1)
        self.assertEqual(path.read_bytes(), self.part_data[part["path"]])
        self.assertEqual(self.http.call_count, 1)
        self.assertEqual(bootstrap.download_part(part, self.cache, 1), path)
        self.assertEqual(self.http.call_count, 1)
        self.assertFalse(list(self.cache.glob("*.partial.*")))
        path.write_bytes(b"corrupt")
        with self.assertRaises(ValueError):
            bootstrap.download_part(part, self.cache, 1)
        self.assertEqual(self.http.call_count, 1)

    def test_download_failures_preserve_partial_and_never_publish_destination(self):
        part = self.manifest["parts"][0]
        original = self.part_data[part["path"]]
        for index, damaged in enumerate((original[:-1], original + b"!", b"X" + original[1:])):
            with self.subTest(index=index):
                cache = self.extraction_root("cache" + str(index))
                self.part_data[part["path"]] = damaged
                with self.assertRaises(ValueError):
                    bootstrap.download_part(part, cache, 1)
                self.assertFalse((cache / Path(part["path"]).name).exists())
                self.assertEqual(len(list(cache.glob("*.partial.*"))), 1)

    def test_redirects_and_changed_response_url_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "redirect"):
            bootstrap._NoRedirect().redirect_request(None, None, 302, "found", {}, "https://elsewhere.invalid")
        self.cache.mkdir()
        self.http.side_effect = lambda url, timeout: FakeResponse(b"bytes", "https://elsewhere.invalid")
        with self.assertRaisesRegex(ValueError, "URL"):
            bootstrap.download_part(self.manifest["parts"][0], self.cache, 1)
        self.assertFalse((self.cache / Path(self.manifest["parts"][0]["path"]).name).exists())

    def test_download_reserve_is_checked_before_and_during_streaming(self):
        self.cache.mkdir()
        part = self.manifest["parts"][0]
        with mock.patch.object(bootstrap.shutil, "disk_usage", return_value=SimpleNamespace(free=0)):
            with self.assertRaisesRegex(ValueError, "reserve"):
                bootstrap.download_part(part, self.cache, 1)
        self.http.assert_not_called()
        with mock.patch.object(bootstrap.shutil, "disk_usage", side_effect=[SimpleNamespace(free=10**8), SimpleNamespace(free=0)]):
            with self.assertRaisesRegex(ValueError, "reserve"):
                bootstrap.download_part(part, self.cache, 1)
        self.assertEqual(len(list(self.cache.glob("*.partial.*"))), 1)
        self.assertFalse((self.cache / Path(part["path"]).name).exists())

    def test_network_failure_keeps_partial_without_publishing_a_valid_part(self):
        self.cache.mkdir()
        part = self.manifest["parts"][0]
        self.http.side_effect = TimeoutError("fixture network timeout")
        with self.assertRaises(TimeoutError):
            bootstrap.download_part(part, self.cache, 1)
        self.assertEqual(len(list(self.cache.glob("*.partial.*"))), 1)
        self.assertFalse((self.cache / Path(part["path"]).name).exists())


class ExtractionTests(BootstrapFixture):
    def test_safe_files_executable_symlinks_and_hardlinks_extract(self):
        root = self.extraction_root()
        archive = self.archive([
            ("llvm-vortex", "directory", None),
            ("llvm-vortex/bin/clang", "executable", b"compiler fixture"),
            ("llvm-vortex/bin/clang++", "symlink", "clang"),
            ("llvm-vortex/bin/alias", "hardlink", "llvm-vortex/bin/clang"),
        ])
        bootstrap.extract_component(archive, root, "llvm-vortex", 1)
        compiler = root / "llvm-vortex/bin/clang"
        self.assertEqual(compiler.read_bytes(), b"compiler fixture")
        self.assertTrue(os.access(compiler, os.X_OK))
        self.assertEqual((root / "llvm-vortex/bin/clang++").resolve(), compiler)
        self.assertEqual((root / "llvm-vortex/bin/alias").stat().st_ino, compiler.stat().st_ino)

    def test_archive_traversal_wrong_root_special_files_and_duplicates_are_rejected(self):
        cases = [
            [("../outside", "file", b"x")],
            [("/absolute", "file", b"x")],
            [("other/file", "file", b"x")],
            [("libc64/../outside", "file", b"x")],
            [("libc64/back\\slash", "file", b"x")],
            [("libc64/fifo", "fifo", None)],
            [("libc64", "file", b"x")],
            [("libc64/file", "file", b"x"), ("libc64/./file", "file", b"y")],
            [],
        ]
        for index, members in enumerate(cases):
            with self.subTest(index=index):
                root = self.extraction_root("bad" + str(index))
                with self.assertRaises(ValueError):
                    bootstrap.extract_component(self.archive(members), root, "libc64", 1)
                self.assertFalse(list(root.iterdir()))

    def test_escaping_links_and_member_through_symlink_are_rejected(self):
        cases = [
            [("libc64/link", "symlink", "../../outside")],
            [("libc64/link", "symlink", "/outside")],
            [("libc64/link", "hardlink", "other/file")],
            [("libc64/real", "directory", None), ("libc64/link", "symlink", "real"),
             ("libc64/link/file", "file", b"blocked")],
        ]
        for index, members in enumerate(cases):
            with self.subTest(index=index):
                root = self.extraction_root("links" + str(index))
                with self.assertRaises(ValueError):
                    bootstrap.extract_component(self.archive(members), root, "libc64", 1)
                self.assertFalse((root / "libc64/real/file").exists())
        self.assertFalse((self.base / "outside").exists())

    def test_hardlink_requires_a_previously_extracted_regular_target(self):
        root = self.extraction_root()
        archive = self.archive([("libc64/alias", "hardlink", "libc64/missing")])
        with self.assertRaisesRegex(ValueError, "hardlink"):
            bootstrap.extract_component(archive, root, "libc64", 1)
        self.assertFalse((root / "libc64/alias").exists())

    def test_archive_expansion_and_member_limits_stop_before_writes(self):
        archive = self.archive([("libc64/a", "file", b"12345"), ("libc64/b", "file", b"6")])
        for name, limits in (("size", {"MAX_EXPANDED_BYTES": 5}), ("count", {"MAX_MEMBERS": 1})):
            with self.subTest(name=name):
                root = self.extraction_root(name)
                with mock.patch.multiple(bootstrap, **limits), self.assertRaises(ValueError):
                    bootstrap.extract_component(archive, root, "libc64", 1)
                self.assertFalse(list(root.iterdir()))

    def test_extraction_disk_reserve_and_existing_component_protect_files(self):
        root = self.extraction_root()
        archive = self.archive([("libc64/a", "file", b"payload")])
        with mock.patch.object(bootstrap.shutil, "disk_usage", return_value=SimpleNamespace(free=7)):
            with self.assertRaisesRegex(ValueError, "reserve"):
                bootstrap.extract_component(archive, root, "libc64", 1)
        self.assertFalse(list(root.iterdir()))
        existing = root / "libc64"
        existing.mkdir()
        (existing / "a").write_bytes(b"keep")
        with self.assertRaisesRegex(ValueError, "overwrite"):
            bootstrap.extract_component(archive, root, "libc64", 1)
        self.assertEqual((existing / "a").read_bytes(), b"keep")

    def test_extraction_resource_breach_retains_only_the_written_prefix(self):
        root = self.extraction_root()
        archive = self.archive([("libc64/a", "file", b"12345678")])
        free = [SimpleNamespace(free=10**8)] * 3 + [SimpleNamespace(free=0)]
        with mock.patch.object(bootstrap, "CHUNK", 4), \
                mock.patch.object(bootstrap.shutil, "disk_usage", side_effect=free):
            with self.assertRaisesRegex(ValueError, "reserve"):
                bootstrap.extract_component(archive, root, "libc64", 1)
        self.assertEqual((root / "libc64/a").read_bytes(), b"1234")


class InstallationTests(BootstrapFixture):
    def test_production_anchor_rejects_consistent_fixture_cache_and_receipt(self):
        self.install()
        self.http.reset_mock()
        receipt_path = self.tools / bootstrap.RECEIPT
        marker_path = self.cache / bootstrap.CACHE_MARKER
        receipt = receipt_path.read_bytes()
        marker = marker_path.read_bytes()
        with mock.patch.object(bootstrap.inventory, "TOOLCHAIN_MANIFEST_SHA256", self.production_anchor):
            with self.assertRaisesRegex(ValueError, "reviewed immutable lock"):
                self.install()
            with self.assertRaisesRegex(ValueError, "reviewed immutable lock"):
                bootstrap.verify(self.tools, self.manifest_path)
        self.assertEqual(receipt_path.read_bytes(), receipt)
        self.assertEqual(marker_path.read_bytes(), marker)
        self.http.assert_not_called()

    def test_miniature_complete_install_and_verify_preserve_identity(self):
        result = self.install()
        self.assertEqual(result["outcome"], "pass")
        self.assertEqual(result["action"], "installed_pinned_components")
        self.assertEqual(self.http.call_count, 18)
        self.assertEqual(result["manifest_sha256"], bootstrap.manifest_digest(self.manifest))
        self.assertTrue(all((self.tools / component).is_dir() for component in bootstrap.COMPONENTS))
        self.assertEqual(bootstrap.verify(self.tools, self.manifest_path)["outcome"], "pass")
        self.assertFalse(list(self.cache.glob("*.assembled.*")))
        self.assertFalse(list(self.cache.glob("*.partial.*")))

    def test_reinstall_verifies_without_network_and_rejects_modified_tools(self):
        self.install()
        self.http.reset_mock()
        result = self.install()
        self.assertEqual(result["action"], "verified_existing_installation")
        self.http.assert_not_called()
        path = self.tools / next(iter(bootstrap.inventory.TOOL_BINARIES.values()))
        path.write_bytes(path.read_bytes() + b"# changed\n")
        with self.assertRaisesRegex(ValueError, "differ"):
            self.install()
        self.assertIn(b"# changed", path.read_bytes())
        self.http.assert_not_called()

    def test_receipt_pin_file_set_versions_and_permissions_are_verified(self):
        self.install()
        receipt_path = self.tools / bootstrap.RECEIPT
        original = json.loads(receipt_path.read_text())
        changes = [
            lambda r: r.update(schema_version=True),
            lambda r: r.update(toolchain_commit="0" * 40),
            lambda r: r.update(manifest_sha256="0" * 64),
            lambda r: r["files"].pop(),
            lambda r: r["tool_versions"].clear(),
            lambda r: r["files"][0].update(path="../../outside"),
        ]
        for index, change in enumerate(changes):
            with self.subTest(index=index):
                receipt = copy.deepcopy(original)
                change(receipt)
                receipt_path.write_text(json.dumps(receipt))
                with self.assertRaises(ValueError):
                    bootstrap.verify(self.tools, self.manifest_path)
        receipt_path.write_text(json.dumps(original))
        executable = self.tools / next(iter(bootstrap.inventory.TOOL_BINARIES.values()))
        executable.chmod(0o600)
        with self.assertRaisesRegex(ValueError, "executable"):
            bootstrap.verify(self.tools, self.manifest_path)
        self.http.assert_called()

    def test_partial_installation_and_unrelated_cache_are_preserved(self):
        self.tools.mkdir()
        sentinel = self.tools / "unrelated"
        sentinel.write_bytes(b"keep")
        with self.assertRaises(ValueError):
            self.install()
        self.assertEqual(sentinel.read_bytes(), b"keep")
        self.http.assert_not_called()
        sentinel.unlink()
        cache_file = self.cache / "unrelated"
        cache_file.write_bytes(b"cache")
        with self.assertRaisesRegex(ValueError, "cache"):
            self.install()
        self.assertEqual(cache_file.read_bytes(), b"cache")
        self.http.assert_not_called()

    def test_failed_extraction_retains_downloads_without_creating_receipt(self):
        with mock.patch.object(bootstrap, "extract_component", side_effect=ValueError("archive rejected")):
            with self.assertRaisesRegex(ValueError, "archive rejected"):
                self.install()
        self.assertFalse((self.tools / bootstrap.RECEIPT).exists())
        self.assertTrue(list(self.cache.glob("*.assembled.*")))
        self.assertEqual(self.http.call_count, 10)

    def test_foreign_cache_marker_blocks_before_download_without_replacing_it(self):
        self.cache.mkdir()
        marker = self.cache / bootstrap.CACHE_MARKER
        previous = json.dumps({"manifest_sha256": "0" * 64}).encode()
        marker.write_bytes(previous)
        with self.assertRaisesRegex(ValueError, "another manifest"):
            self.install()
        self.assertEqual(marker.read_bytes(), previous)
        self.assertFalse(list(self.tools.iterdir()))
        self.http.assert_not_called()

    def test_install_rejects_unsafe_overlapping_paths_and_invalid_reserves(self):
        for tools, cache in ((self.tools, self.tools), (self.tools, self.tools / "cache"),
                             (self.cache / "tools", self.cache), (Path("relative"), self.cache)):
            with self.subTest(tools=tools, cache=cache), self.assertRaises(ValueError):
                bootstrap.install(tools, cache, self.manifest_path, 1)
        real = self.base / "real"
        real.mkdir()
        alias = self.base / "alias"
        alias.symlink_to(real, target_is_directory=True)
        with self.assertRaises(ValueError):
            bootstrap.install(alias, self.cache, self.manifest_path, 1)
        for reserve in (True, 0, -1, 1.0):
            with self.subTest(reserve=reserve), self.assertRaises(ValueError):
                bootstrap.install(self.tools, self.cache, self.manifest_path, reserve)
        self.http.assert_not_called()

    def test_cli_requires_explicit_cache_and_verify_never_downloads(self):
        output = io.StringIO()
        with redirect_stdout(output):
            result = bootstrap.main(["install", "--tool-dir", str(self.tools),
                                     "--manifest", str(self.manifest_path)])
        self.assertEqual(result, 1)
        self.assertEqual(json.loads(output.getvalue())["outcome"], "fail")
        self.assertFalse(self.tools.exists())
        self.install()
        self.http.reset_mock()
        output = io.StringIO()
        with redirect_stdout(output):
            result = bootstrap.main(["verify", "--tool-dir", str(self.tools),
                                     "--manifest", str(self.manifest_path)])
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output.getvalue())["operation"], "verify")
        self.http.assert_not_called()


if __name__ == "__main__":
    unittest.main()
