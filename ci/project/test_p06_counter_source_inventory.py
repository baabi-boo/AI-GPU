# SPDX-License-Identifier: Apache-2.0
"""Independent source expectations with original descriptors and synthetic mutations.

The two externally hash-pinned ZIPs supply inert original source bytes only.
Synthetic additions, revisions and filesystem races do not establish Git origin,
binary identity, native execution, warm qualification or phase acceptance.
"""

from contextlib import ExitStack
from copy import deepcopy
from functools import lru_cache
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

import p06_counter_source_inventory as inventory


ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / "docs/project/evidence/p06-counter-diagnostics/native"
CONTRACT = "simx-counter-source-inventory-v1"
CHECKED = "simx-checked-counters-native-v2"
PUBLIC = "simx-counter-public-native-v1"
MANIFEST_LIMIT = 8 * 1024 * 1024
SOURCE_LIMIT = 256 * 1024 * 1024
SOURCE_COUNT_LIMIT = 20000
SYNTHETIC_REVISION = "1234567890abcdef1234567890abcdef12345678"
HELPER = "ci/project/baseline_packet_io.py"
UNCOMPILED_HEADER = "sim/avedsim/vrt_c.h"
ORIGINALS = {
    CHECKED: {
        "archive": "run-45026112992-attempt1.zip",
        "sha256": "c4a7ae49259bbb72066d55f7c3e733ce5696f215175ce308f654e1cec9e9c13f",
        "prefix": "checked-counters",
        "revision": "407ab9fea5e4f793a2a5088f566a87f3e631aa84",
        "count": 270,
        "names_sha256": "d074477d6c6b9a0521c2a79e912b3113e9648bc73a3e6cc3dc0f3bc311106108",
    },
    PUBLIC: {
        "archive": "run-45029135146-attempt1.zip",
        "sha256": "d628813ec8815140830825adef22cd2ea9191707686931e49145d5a4e4247db5",
        "prefix": "public-counters",
        "revision": "81ed6871634fefbf5c78fb27cf10dce913bd4d9c",
        "count": 676,
        "names_sha256": "f38b606f70604edc6ff27400126e94d3fdcc5983950658dcf35588fb655d09da",
    },
}


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
            + "\n").encode("utf-8")


def descriptor(path, body):
    return {"path": path, "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)}


@lru_cache(maxsize=1)
def original_records():
    result = {}
    for producer, spec in ORIGINALS.items():
        contents = (NATIVE / spec["archive"]).read_bytes()
        if hashlib.sha256(contents).hexdigest() != spec["sha256"]:
            raise AssertionError("original source inventory archive identity differs")
        with zipfile.ZipFile(io.BytesIO(contents)) as archive:
            report = json.loads(archive.read(spec["prefix"] + "/report.json"))
            if report["contract_id"] != producer:
                raise AssertionError("original producer contract differs")
            if report["source_before"]["checkout"]["revision"] != spec["revision"]:
                raise AssertionError("original producer revision differs")
            rows = report["source_before"]["files"]
            if rows != report["source_after"]["files"]:
                raise AssertionError("original source snapshots differ")
            names = [row["path"] for row in rows]
            names_sha256 = hashlib.sha256("".join(name + "\n" for name in names).encode()).hexdigest()
            if len(rows) != spec["count"] or names_sha256 != spec["names_sha256"]:
                raise AssertionError("original complete source names differ")
            for row in rows:
                body = archive.read(spec["prefix"] + "/artifacts/source/" + row["path"])
                if row != descriptor(row["path"], body):
                    raise AssertionError("original retained source descriptor differs")
            result[producer] = {
                "rows": rows,
                "helper_body": archive.read(spec["prefix"] + "/artifacts/source/" + HELPER),
            }
    return result


class InventoryFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.originals = original_records()

    def manifest(self, producer=CHECKED):
        return {"schema_version": 1, "contract_id": CONTRACT,
                "producer_contract_id": producer,
                "source_revision": ORIGINALS[producer]["revision"],
                "sources": deepcopy(self.originals[producer]["rows"])}

    def expectations(self, producer=CHECKED, revision=None):
        return {"expected_revision": ORIGINALS[producer]["revision"] if revision is None else revision,
                "producer_contract_id": producer}

    def validate(self, manifest, producer=CHECKED, **kwargs):
        return inventory.validate_source_inventory(manifest, **(self.expectations(producer) | kwargs))

    def compare(self, rows, manifest, producer=CHECKED, **kwargs):
        return inventory.validate_archive_sources(rows, manifest,
                                                 **(self.expectations(producer) | kwargs))

    def decode(self, contents, producer=CHECKED, **kwargs):
        arguments = self.expectations(producer) | {"expected_sha256": hashlib.sha256(contents).hexdigest()}
        return inventory.decode_source_inventory(contents, **(arguments | kwargs))

    def add(self, manifest, path, body=b"synthetic source bytes\n"):
        manifest["sources"].append(descriptor(path, body))
        manifest["sources"].sort(key=lambda row: row["path"])


class OriginalSourceInventoryTests(InventoryFixture):
    def test_public_contract_id_is_versioned(self):
        self.assertEqual(inventory.CONTRACT_ID, CONTRACT)

    def test_required_names_match_both_complete_originals_and_fixed_digests(self):
        for producer, spec in ORIGINALS.items():
            with self.subTest(producer=producer):
                names = tuple(inventory.required_source_names(producer))
                original_names = tuple(row["path"] for row in self.originals[producer]["rows"])
                self.assertEqual(names, original_names)
                self.assertEqual(len(names), spec["count"])
                self.assertEqual(len(set(names)), spec["count"])
                self.assertEqual(names, tuple(sorted(names)))
                self.assertEqual(hashlib.sha256("".join(name + "\n" for name in names).encode()).hexdigest(),
                                 spec["names_sha256"])

    def test_original_descriptors_validate_decode_and_compare_exactly(self):
        for producer in ORIGINALS:
            with self.subTest(producer=producer):
                manifest = self.manifest(producer)
                self.assertEqual(self.validate(manifest, producer), manifest)
                self.assertEqual(self.decode(encoded(manifest), producer), manifest)
                self.assertEqual(self.compare(self.originals[producer]["rows"], manifest, producer),
                                 manifest["sources"])

    def test_synthetic_future_helper_body_requires_matching_archive_descriptor(self):
        body = b"raise AssertionError('synthetic source body must never execute')\n"
        for producer in ORIGINALS:
            with self.subTest(producer=producer):
                manifest = self.manifest(producer)
                manifest["source_revision"] = SYNTHETIC_REVISION
                self.add(manifest, "ci/project/synthetic_counter_helper.py", body)
                expected = {"expected_revision": SYNTHETIC_REVISION}
                self.assertEqual(self.validate(manifest, producer, **expected), manifest)
                pinned = self.decode(encoded(manifest), producer, **expected)
                self.assertEqual(self.compare(manifest["sources"], pinned, producer, **expected),
                                 manifest["sources"])
                with self.assertRaises(ValueError):
                    self.compare(self.originals[producer]["rows"], pinned, producer, **expected)

    def test_changed_original_helper_is_caller_expected_data_not_git_or_binary_proof(self):
        for producer in ORIGINALS:
            with self.subTest(producer=producer):
                manifest = self.manifest(producer)
                manifest["source_revision"] = SYNTHETIC_REVISION
                body = self.originals[producer]["helper_body"] + b"\n# synthetic later helper body\n"
                index = next(i for i, row in enumerate(manifest["sources"]) if row["path"] == HELPER)
                manifest["sources"][index] = descriptor(HELPER, body)
                expected = {"expected_revision": SYNTHETIC_REVISION}
                pinned = self.decode(encoded(manifest), producer, **expected)
                self.assertEqual(set(pinned), {"schema_version", "contract_id", "producer_contract_id",
                                              "source_revision", "sources"})
                with self.assertRaises(ValueError):
                    self.compare(self.originals[producer]["rows"], pinned, producer, **expected)
                self.assertEqual(self.compare(manifest["sources"], pinned, producer, **expected),
                                 manifest["sources"])

    def test_new_sources_are_allowed_in_each_reviewed_producer_root(self):
        shared = ("ci/project", "sim", "sw/common", "tests/unittest/checked_counters",
                  "third_party/ramulator_ext")
        roots = {CHECKED: shared, PUBLIC: (*shared, "sw/include", "sw/runtime", "sw/kernel/include",
                                         "tests/regression/ai_bench_common")}
        for producer, producer_roots in roots.items():
            for root in producer_roots:
                with self.subTest(producer=producer, root=root):
                    manifest = self.manifest(producer)
                    self.add(manifest, root + "/synthetic-added+source.h")
                    self.assertEqual(self.validate(manifest, producer), manifest)

    def test_omitted_uncompiled_header_or_original_helper_cannot_be_replaced_by_an_addition(self):
        for producer in ORIGINALS:
            for omitted in (UNCOMPILED_HEADER, HELPER):
                for replacement in (False, True):
                    with self.subTest(producer=producer, omitted=omitted, replacement=replacement):
                        manifest = self.manifest(producer)
                        manifest["sources"] = [row for row in manifest["sources"] if row["path"] != omitted]
                        if replacement:
                            self.add(manifest, "ci/project/synthetic_replacement.py")
                            self.assertEqual(len(manifest["sources"]), ORIGINALS[producer]["count"])
                        with self.assertRaises(ValueError):
                            self.validate(manifest, producer)

    def test_success_copies_descriptors_and_does_not_mutate_inputs(self):
        manifest = self.manifest()
        rows = deepcopy(manifest["sources"])
        before = encoded(manifest)
        validated = self.validate(manifest)
        compared = self.compare(rows, manifest)
        self.assertEqual(encoded(manifest), before)
        self.assertEqual(rows, manifest["sources"])
        validated["sources"][0]["sha256"] = "0" * 64
        compared[0]["size_bytes"] += 1
        self.assertEqual(encoded(manifest), before)
        self.assertEqual(rows, manifest["sources"])

    def test_pure_apis_do_not_open_resolve_or_discover_source_paths(self):
        manifest = self.manifest()
        self.add(manifest, "sim/synthetic_unavailable_source.cpp")
        with ExitStack() as stack:
            for target in ("builtins.open", "io.open", "os.open", "os.stat", "os.lstat",
                           "os.scandir", "os.listdir", "pathlib.Path.resolve"):
                stack.enter_context(mock.patch(target, side_effect=AssertionError("unexpected filesystem access")))
            self.assertEqual(self.validate(manifest), manifest)
            self.assertEqual(self.compare(manifest["sources"], manifest), manifest["sources"])
            self.assertEqual(len(inventory.required_source_names(CHECKED)), 270)
            self.assertEqual(self.decode(encoded(manifest)), manifest)


class SourceInventoryValidationTests(InventoryFixture):
    def test_manifest_must_be_a_plain_object(self):
        class DerivedDict(dict):
            pass

        for value in (None, [], (), True, 1, "{}", DerivedDict(self.manifest())):
            with self.subTest(value=type(value).__name__), self.assertRaises(ValueError):
                self.validate(value)

    def test_manifest_fields_are_exact(self):
        for missing in self.manifest():
            with self.subTest(missing=missing):
                manifest = self.manifest()
                del manifest[missing]
                with self.assertRaises(ValueError):
                    self.validate(manifest)
        for extra in ("sha256", "source_root", "qualified", "binary", "schemaVersion"):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.validate(self.manifest() | {extra: "synthetic"})

    def test_schema_version_is_exact_integer_one(self):
        class DerivedInt(int):
            pass

        for value in (False, True, 0, -1, 2, 1.0, "1", None, [], {}, DerivedInt(1)):
            with self.subTest(value=repr(value)), self.assertRaises(ValueError):
                self.validate(self.manifest() | {"schema_version": value})

    def test_manifest_contract_and_external_producer_are_exact(self):
        for field, values in (
            ("contract_id", (None, True, 1, {}, "", CONTRACT + "\n", "simx-counter-source-inventory-v2")),
            ("producer_contract_id", (None, True, 1, [], "", PUBLIC, CHECKED + "\n")),
        ):
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    self.validate(self.manifest() | {field: value})

    def test_unknown_and_legacy_producer_contracts_have_no_fallback(self):
        for producer in (None, True, 1, {}, [], "", "simx-checked-counters-native-v1",
                         "simx-counter-public-native-v0", "simx-counter-public-native-v2", CHECKED + "\n"):
            with self.subTest(producer=producer):
                with self.assertRaises(ValueError):
                    inventory.required_source_names(producer)
                with self.assertRaises(ValueError):
                    inventory.validate_source_inventory(self.manifest(), expected_revision=ORIGINALS[CHECKED]["revision"],
                                                        producer_contract_id=producer)

    def test_revision_is_external_exact_lowercase_40_hex(self):
        for value in (None, True, 1, [], b"a" * 40, "", "a" * 39, "a" * 41, "g" * 40,
                      "A" * 40, "a" * 40 + "\n", SYNTHETIC_REVISION):
            with self.subTest(revision=value):
                with self.assertRaises(ValueError):
                    self.validate(self.manifest(), expected_revision=value)
                with self.assertRaises(ValueError):
                    self.validate(self.manifest() | {"source_revision": value})

    def test_source_container_is_a_nonempty_plain_list(self):
        class DerivedList(list):
            pass

        rows = self.manifest()["sources"]
        for value in (None, False, 0, {}, "sources", (), tuple(rows), [], DerivedList(rows)):
            with self.subTest(value=type(value).__name__), self.assertRaises(ValueError):
                self.validate(self.manifest() | {"sources": value})

    def test_descriptors_are_plain_objects_with_exact_fields(self):
        class DerivedDict(dict):
            pass

        original = self.manifest()["sources"][0]
        invalid = [None, [], (), True, "source", DerivedDict(original)]
        invalid.extend({key: value for key, value in original.items() if key != missing}
                       for missing in original)
        invalid.extend(original | {extra: "synthetic"} for extra in ("body", "sha", "source_revision"))
        for row in invalid:
            with self.subTest(row=row):
                manifest = self.manifest()
                manifest["sources"][0] = row
                with self.assertRaises(ValueError):
                    self.validate(manifest)

    def test_descriptor_sha256_is_an_exact_lowercase_hex_string(self):
        class DerivedStr(str):
            pass

        for value in (None, True, 1, [], b"a" * 64, "", "a" * 63, "a" * 65,
                      "g" * 64, "A" * 64, "a" * 64 + "\n", DerivedStr("a" * 64)):
            with self.subTest(sha256=value):
                manifest = self.manifest()
                manifest["sources"][0]["sha256"] = value
                with self.assertRaises(ValueError):
                    self.validate(manifest)

    def test_sizes_accept_both_integer_bounds_without_reading_source_bodies(self):
        for value in (0, 1, SOURCE_LIMIT - 1, SOURCE_LIMIT):
            with self.subTest(size=value):
                manifest = self.manifest()
                manifest["sources"][0]["size_bytes"] = value
                self.assertEqual(self.validate(manifest), manifest)

    def test_sizes_reject_bool_nonintegers_negative_and_overflow(self):
        class DerivedInt(int):
            pass

        for value in (False, True, None, "0", 0.0, 1.0, [], {}, -1, SOURCE_LIMIT + 1,
                      2 ** 64 - 1, 2 ** 64, DerivedInt(0)):
            with self.subTest(size=repr(value)):
                manifest = self.manifest()
                manifest["sources"][0]["size_bytes"] = value
                with self.assertRaises(ValueError):
                    self.validate(manifest)

    def test_duplicate_or_unsorted_descriptors_are_rejected(self):
        for mode in ("duplicate", "reversed", "adjacent-swap"):
            with self.subTest(mode=mode):
                manifest = self.manifest()
                if mode == "duplicate":
                    manifest["sources"].insert(0, deepcopy(manifest["sources"][0]))
                elif mode == "reversed":
                    manifest["sources"].reverse()
                else:
                    manifest["sources"][0], manifest["sources"][1] = manifest["sources"][1], manifest["sources"][0]
                with self.assertRaises(ValueError):
                    self.validate(manifest)

    def test_unsafe_source_paths_are_rejected(self):
        paths = (None, False, 1, [], b"sim/a.h", "", "/sim/a.h", "C:/sim/a.h", "C:\\sim\\a.h",
                 "../sim/a.h", "sim/../a.h", "sim/./a.h", "sim//a.h", "sim/a.h/", "sim\\a.h",
                 "sim/.git/config", ".git/config", "sim/a\x00.h", "sim/a\n.h", "sim/a\r.h",
                 "sim/a\t.h", "sim/a\x7f.h", "sim/a\x85.h", "sim/café.h", "sim/a b.h",
                 "sim/a%2fb.h", "sim/a:b.h", "sim/" + "a" * 256,
                 "sim/" + "/".join("x" for _ in range(64)), "sim/" + "a" * 4096)
        for path in paths:
            with self.subTest(path=path):
                manifest = self.manifest()
                manifest["sources"].append({"path": path, "sha256": "a" * 64, "size_bytes": 0})
                with self.assertRaises(ValueError):
                    self.validate(manifest)

    def test_unknown_roots_and_root_prefix_lookalikes_are_rejected(self):
        for producer in ORIGINALS:
            for path in ("unknown/file.h", "ci/projector/file.py", "simx/file.h", "sw/common-extra/file.h",
                         "third_party/ramulator_extension/file.h", "ci/project", "sim",
                         ".github/workflows/synthetic.yml", "profiles/synthetic.json", "VERSION.extra"):
                with self.subTest(producer=producer, path=path):
                    manifest = self.manifest(producer)
                    self.add(manifest, path)
                    with self.assertRaises(ValueError):
                        self.validate(manifest, producer)
        for path in ("sw/runtime/synthetic.cpp", "sw/include/synthetic.h", "sw/kernel/include/synthetic.h",
                     "tests/regression/ai_bench_common/synthetic.h"):
            with self.subTest(checked_only=path):
                manifest = self.manifest()
                self.add(manifest, path)
                with self.assertRaises(ValueError):
                    self.validate(manifest)

    def test_source_count_accepts_20000_and_rejects_20001(self):
        for producer in ORIGINALS:
            with self.subTest(producer=producer):
                manifest = self.manifest(producer)
                for number in range(SOURCE_COUNT_LIMIT - len(manifest["sources"])):
                    manifest["sources"].append(descriptor(f"ci/project/synthetic_inventory_{number:05}.py", b""))
                manifest["sources"].sort(key=lambda row: row["path"])
                self.assertEqual(len(self.validate(manifest, producer)["sources"]), SOURCE_COUNT_LIMIT)
                self.add(manifest, "ci/project/synthetic_inventory_over_limit.py", b"")
                with self.assertRaises(ValueError):
                    self.validate(manifest, producer)

    def test_archive_comparison_rejects_each_descriptor_difference_and_missing_or_extra_rows(self):
        for change in ("sha256", "size_bytes", "missing", "extra"):
            with self.subTest(change=change):
                manifest = self.manifest()
                observed = deepcopy(manifest["sources"])
                if change == "sha256":
                    observed[0]["sha256"] = "0" * 64
                elif change == "size_bytes":
                    observed[0]["size_bytes"] += 1
                elif change == "missing":
                    observed.pop()
                else:
                    observed.append(descriptor("sim/synthetic_extra.cpp", b"synthetic"))
                    observed.sort(key=lambda row: row["path"])
                with self.assertRaises(ValueError):
                    self.compare(observed, manifest)

    def test_archive_comparison_validates_expected_and_observed_schema(self):
        for expected_bad in (False, True):
            with self.subTest(expected_bad=expected_bad):
                manifest = self.manifest()
                observed = deepcopy(manifest["sources"])
                if expected_bad:
                    manifest["sources"][0]["size_bytes"] = True
                else:
                    observed[0]["size_bytes"] = True
                with self.assertRaises(ValueError):
                    self.compare(observed, manifest)


class SourceInventoryDecodeTests(InventoryFixture):
    def test_digest_binds_exact_bytes_including_whitespace(self):
        manifest = self.manifest()
        compact = encoded(manifest)
        spaced = compact + b" \n\t"
        self.assertEqual(self.decode(compact), manifest)
        self.assertEqual(self.decode(spaced), manifest)
        with self.assertRaisesRegex(ValueError, "(?i)(sha.?256|digest|hash)"):
            self.decode(spaced, expected_sha256=hashlib.sha256(compact).hexdigest())

    def test_external_digest_is_mandatory_and_never_inferred(self):
        contents = encoded(self.manifest())
        for digest in (None, True, 1, [], {}, b"a" * 64, "", "a" * 63, "a" * 65,
                       "A" * 64, "g" * 64, "a" * 64 + "\n"):
            with self.subTest(digest=digest), self.assertRaises(ValueError):
                self.decode(contents, expected_sha256=digest)
        with self.assertRaises(TypeError):
            inventory.decode_source_inventory(contents, **self.expectations())

    def test_wrong_hash_is_rejected_before_invalid_encoding_or_json_is_parsed(self):
        for contents in (b"\xffnot-json", b'{"a":1,"a":2}', b"not-json", encoded(self.manifest())):
            with self.subTest(contents=contents[:24]), self.assertRaisesRegex(ValueError, "(?i)(sha.?256|digest|hash)"):
                self.decode(contents, expected_sha256="0" * 64)

    def test_duplicate_json_fields_at_top_level_or_descriptor_depth_are_rejected(self):
        contents = encoded(self.manifest())
        duplicates = (
            b'{"schema_version":1,' + contents[1:],
            b'{"\\u0073chema_version":1,' + contents[1:],
            contents.replace(b'"path":', b'"path":"sim/synthetic.h","path":', 1),
            contents.replace(b'"path":', b'"\\u0070ath":"sim/synthetic.h","path":', 1),
            contents.replace(b'"size_bytes":', b'"size_bytes":0,"size_bytes":', 1),
        )
        for number, data in enumerate(duplicates):
            with self.subTest(duplicate=number), self.assertRaisesRegex(ValueError, "duplicate"):
                self.decode(data)

    def test_bad_encoding_malformed_json_and_nonobject_json_are_rejected(self):
        contents = encoded(self.manifest())
        malformed = (b"\xff", b"\xc3", b"\xed\xa0\x80", b"\xef\xbb\xbf" + contents,
                     contents.decode().encode("utf-16"), b"", b"{}{}", b'{"x":}', b'{"x":1,}',
                     b"[]", b"null", b"true", b"1", b'"inventory"')
        for number, data in enumerate(malformed):
            with self.subTest(malformed=number), self.assertRaises(ValueError):
                self.decode(data)

    def test_nonfinite_or_float_size_tokens_cannot_act_as_integers(self):
        contents = encoded(self.manifest())
        first_size = str(self.manifest()["sources"][0]["size_bytes"]).encode()
        for token in (b"NaN", b"Infinity", b"-Infinity", b"1e400", b"0.0", b"true", b"false"):
            with self.subTest(token=token), self.assertRaises(ValueError):
                self.decode(contents.replace(b'"size_bytes":' + first_size,
                                             b'"size_bytes":' + token, 1))

    def test_decoder_requires_plain_bytes(self):
        contents = encoded(self.manifest())
        class DerivedBytes(bytes):
            pass

        for data in (None, True, 1, [], {}, contents.decode(), bytearray(contents), memoryview(contents),
                     DerivedBytes(contents)):
            with self.subTest(type=type(data).__name__), self.assertRaises(ValueError):
                inventory.decode_source_inventory(data, expected_sha256=hashlib.sha256(contents).hexdigest(),
                                                  **self.expectations())

    def test_manifest_byte_bound_accepts_8_mib_and_rejects_one_more(self):
        manifest = self.manifest()
        contents = encoded(manifest)
        at_limit = contents + b" " * (MANIFEST_LIMIT - len(contents))
        self.assertEqual(self.decode(at_limit), manifest)
        with self.assertRaises(ValueError):
            self.decode(at_limit + b" ")

    def test_external_revision_and_producer_mismatch_have_no_fallback(self):
        contents = encoded(self.manifest())
        for expected in ({"expected_revision": SYNTHETIC_REVISION}, {"producer_contract_id": PUBLIC},
                         {"producer_contract_id": "simx-checked-counters-native-v1"}):
            with self.subTest(expected=expected), self.assertRaises(ValueError):
                self.decode(contents, **expected)


@unittest.skipUnless(os.name == "posix" and hasattr(os, "O_NOFOLLOW"),
                     "source inventory filesystem checks require POSIX no-follow support")
class SourceInventoryFileTests(InventoryFixture):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="source-inventory-test-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.directory = self.base / "packet"
        self.directory.mkdir()
        self.path = self.directory / "inventory.json"
        self.document = self.manifest()
        self.contents = encoded(self.document)
        self.path.write_bytes(self.contents)
        self.digest = hashlib.sha256(self.contents).hexdigest()

    def load(self, path=None, **kwargs):
        arguments = self.expectations() | {"expected_sha256": self.digest}
        return inventory.load_source_inventory(self.path if path is None else path, **(arguments | kwargs))

    def test_loads_only_the_explicit_manifest_with_no_source_path_resolution(self):
        self.add(self.document, "ci/project/synthetic_unavailable_helper.py",
                 b"raise AssertionError('must remain inert')\n")
        self.contents = encoded(self.document)
        self.path.write_bytes(self.contents)
        self.digest = hashlib.sha256(self.contents).hexdigest()
        with ExitStack() as stack:
            for target in ("builtins.open", "io.open", "pathlib.Path.resolve", "os.scandir", "os.listdir"):
                stack.enter_context(mock.patch(target, side_effect=AssertionError("unexpected path access")))
            self.assertEqual(self.load(), self.document)
            self.assertEqual(self.load(str(self.path)), self.document)

    def test_external_digest_is_checked_before_any_filesystem_access(self):
        with mock.patch("os.open", side_effect=AssertionError("unexpected open")) as opened:
            with self.assertRaises(ValueError):
                self.load(expected_sha256=None)
            opened.assert_not_called()
        with self.assertRaises(TypeError):
            inventory.load_source_inventory(self.path, **self.expectations())

    def test_missing_and_directory_paths_cannot_fall_back(self):
        for path in (self.base / "missing.json", self.directory, self.base / "missing" / "inventory.json"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.load(path)

    def test_symlink_leaf_is_rejected_for_contained_outside_and_missing_targets(self):
        outside = self.base / "outside.json"
        outside.write_bytes(self.contents)
        for label, target in (("contained", self.path), ("outside", outside),
                              ("broken", self.base / "missing.json")):
            with self.subTest(target=label):
                alias = self.directory / (label + ".json")
                alias.symlink_to(target)
                with self.assertRaises(ValueError):
                    self.load(alias)
        self.assertEqual(outside.read_bytes(), self.contents)

    def test_symlink_parent_or_ancestor_is_rejected(self):
        nested = self.directory / "nested"
        nested.mkdir()
        (nested / "inventory.json").write_bytes(self.contents)
        alias = self.base / "alias"
        alias.symlink_to(self.directory, target_is_directory=True)
        for path in (alias / "inventory.json", alias / "nested" / "inventory.json"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.load(path)

    def test_fifo_and_regular_to_fifo_race_reject_without_blocking(self):
        os.mkfifo(self.directory / "pipe.json")
        (self.directory / "raced.json").write_bytes(self.contents)
        script = """
import os
from pathlib import Path
import sys
from unittest import mock
sys.path.insert(0, sys.argv[1])
import p06_counter_source_inventory as inventory
directory = Path(sys.argv[2])
arguments = dict(expected_sha256=sys.argv[3], expected_revision=sys.argv[4], producer_contract_id=sys.argv[5])
def reject(path):
    try:
        inventory.load_source_inventory(path, **arguments)
    except ValueError:
        return
    raise AssertionError('FIFO accepted')
reject(directory / 'pipe.json')
real_stat = os.stat
changed = False
def replace_with_fifo(path, *args, **kwargs):
    global changed
    info = real_stat(path, *args, **kwargs)
    if path == 'raced.json' and not changed:
        changed = True
        (directory / 'raced.json').unlink()
        os.mkfifo(directory / 'raced.json')
    return info
with mock.patch.object(os, 'stat', replace_with_fifo), \\
     mock.patch.object(os, 'supports_dir_fd', os.supports_dir_fd | {replace_with_fifo}), \\
     mock.patch.object(os, 'supports_follow_symlinks', os.supports_follow_symlinks | {replace_with_fifo}):
    reject(directory / 'raced.json')
assert changed, 'race injection was not reached'
"""
        result = subprocess.run([sys.executable, "-c", script, str(ROOT / "ci/project"),
                                 str(self.directory), self.digest, ORIGINALS[CHECKED]["revision"], CHECKED],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_oversized_file_is_rejected_before_reading_its_contents(self):
        with self.path.open("wb") as stream:
            stream.truncate(MANIFEST_LIMIT + 1)
        with mock.patch("os.read", side_effect=AssertionError("oversized file was read")) as read:
            with self.assertRaises(ValueError):
                self.load()
            read.assert_not_called()

    def test_manifest_at_exact_file_byte_limit_loads(self):
        contents = self.contents + b" " * (MANIFEST_LIMIT - len(self.contents))
        self.path.write_bytes(contents)
        self.assertEqual(self.load(expected_sha256=hashlib.sha256(contents).hexdigest()), self.document)

    def test_wrong_digest_or_malformed_explicit_file_never_falls_back(self):
        with self.assertRaisesRegex(ValueError, "(?i)(sha.?256|digest|hash)"):
            self.load(expected_sha256="0" * 64)
        for contents in (b"\xff", b"not-json", b'{"a":1,"a":2}',
                         encoded(self.document | {"source_revision": SYNTHETIC_REVISION}),
                         encoded(self.document | {"producer_contract_id": PUBLIC})):
            with self.subTest(contents=contents[:24]):
                self.path.write_bytes(contents)
                with self.assertRaises(ValueError):
                    self.load(expected_sha256=hashlib.sha256(contents).hexdigest())

    def test_same_size_content_drift_with_restored_mtime_during_read_is_rejected(self):
        original = self.path.stat()
        real_read = os.read
        changed = False

        def alter(descriptor_number, count):
            nonlocal changed
            chunk = real_read(descriptor_number, count)
            if not changed:
                changed = True
                self.path.write_bytes(self.contents[:-1] + b" ")
                os.utime(self.path, ns=(original.st_atime_ns, original.st_mtime_ns))
            return chunk

        with mock.patch("os.read", side_effect=alter), self.assertRaises(ValueError):
            self.load()
        self.assertTrue(changed)

    def test_identical_content_inode_replacement_during_read_is_rejected(self):
        original = self.path.stat()
        replacement = self.directory / "replacement.json"
        replacement.write_bytes(self.contents)
        os.utime(replacement, ns=(original.st_atime_ns, original.st_mtime_ns))
        real_read = os.read
        changed = False

        def alter(descriptor_number, count):
            nonlocal changed
            chunk = real_read(descriptor_number, count)
            if not changed:
                changed = True
                os.replace(replacement, self.path)
            return chunk

        with mock.patch("os.read", side_effect=alter), self.assertRaises(ValueError):
            self.load()
        self.assertTrue(changed)

    def test_growth_or_truncation_during_read_is_rejected(self):
        for body in (b"", self.contents + b"unexpected growth"):
            with self.subTest(size=len(body)):
                self.path.write_bytes(self.contents)
                real_read = os.read
                changed = False

                def alter(descriptor_number, count):
                    nonlocal changed
                    chunk = real_read(descriptor_number, count)
                    if not changed:
                        changed = True
                        self.path.write_bytes(body)
                    return chunk

                with mock.patch("os.read", side_effect=alter), self.assertRaises(ValueError):
                    self.load()
                self.assertTrue(changed)

    def test_parent_directory_replacement_during_read_is_rejected(self):
        real_read = os.read
        changed = False

        def alter(descriptor_number, count):
            nonlocal changed
            chunk = real_read(descriptor_number, count)
            if not changed:
                changed = True
                self.directory.rename(self.base / "retired")
                self.directory.mkdir()
                self.path.write_bytes(self.contents)
            return chunk

        with mock.patch("os.read", side_effect=alter), self.assertRaises(ValueError):
            self.load()
        self.assertTrue(changed)


if __name__ == "__main__":
    unittest.main()
