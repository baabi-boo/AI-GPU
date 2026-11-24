# SPDX-License-Identifier: Apache-2.0
"""Synthetic host-only retained checks; no native or framework code executes."""

from contextlib import ExitStack, contextmanager
import copy
from dataclasses import FrozenInstanceError, replace
import hashlib
import io
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import unittest
from unittest import mock

import p05_execution_records as base_records
import p05_installed_check as installed_check
import p05_torch_records as records
from p05_qualification_test_fixture import raw_log as base_raw_log
from p05_torch_qualification_test_fixture import raw_log, synthetic


def request_digest(request):
    return hashlib.sha256(records.canonical(request)).hexdigest()


def retained_identity(value, request):
    """Join synthetic fixture bytes before removing its temporary producer."""
    installation = value["base_observations"]["installation"]
    names = [installation[key] for key in ("executable", "package_file", "extension_file")]
    names.append(value["framework"]["adapter_file"])
    receipts = []
    for name in names:
        data = Path(name).read_bytes()
        receipts.append((name, hashlib.sha256(data).hexdigest(), len(data)))
    return base_records.RetainedIdentity(request_digest(request["base_request"]), tuple(receipts))


@contextmanager
def denied_live_access():
    """Fail on filesystem/process/network access and on live validator reuse."""
    import builtins

    forbidden = (
        (builtins, "open"), (io, "open"), (os, "open"), (os, "stat"), (os, "lstat"),
        (os, "listdir"), (os, "scandir"), (os, "readlink"), (os, "system"), (os, "execve"),
        (Path, "resolve"), (Path, "open"), (Path, "stat"), (Path, "is_file"), (Path, "is_dir"),
        (subprocess, "Popen"), (subprocess, "run"), (socket, "socket"), (socket, "create_connection"),
        (installed_check, "validate_request"), (installed_check, "inspect_installation"),
        (base_records, "_installation"), (base_records, "verify_observations"),
        (records, "validate_request"), (records, "_framework"), (records, "verify_observations"),
        (installed_check.importlib, "import_module"),
    )
    with ExitStack() as stack:
        for owner, name in forbidden:
            stack.enter_context(mock.patch.object(owner, name,
                side_effect=AssertionError("retained validation attempted live access: " + name)))
        yield


class RetainedObservationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="p05-retained-host-only-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.value, self.request, self.native = synthetic(self.root)
        self.identity = retained_identity(self.value, self.request)
        self.adapter_bytes = Path(self.value["framework"]["adapter_file"]).read_bytes()

    def verify(self, value=None, *, request=None, identity=None, adapter_bytes=None, native=None, raw=None):
        value = self.value if value is None else value
        return records.verify_retained_observations(value, self.request if request is None else request,
            retained_identity=self.identity if identity is None else identity,
            adapter_bytes=self.adapter_bytes if adapter_bytes is None else adapter_bytes,
            **(self.native if native is None else native), raw_log=raw_log(value) if raw is None else raw)

    def test_both_formats_match_live_counts_with_producer_absent_and_all_io_denied(self):
        for fmt in ("fp16", "bf16"):
            with self.subTest(format=fmt):
                producer = self.root / fmt
                value, request, native = synthetic(producer, fmt)
                identity = retained_identity(value, request)
                adapter = Path(value["framework"]["adapter_file"]).read_bytes()
                raw, base_raw = raw_log(value), base_raw_log(value["base_observations"])
                live = records.verify_observations(value, request, **native, raw_log=raw)
                live_base = base_records.verify_observations(value["base_observations"],
                    request["base_request"], **native, raw_log=base_raw)
                shutil.rmtree(producer)
                with denied_live_access():
                    retained = records.verify_retained_observations(value, request,
                        retained_identity=identity, adapter_bytes=adapter, **native, raw_log=raw)
                    retained_base = base_records.verify_retained_observations(value["base_observations"],
                        request["base_request"], retained_identity=identity, **native, raw_log=base_raw)
                self.assertEqual(retained, live)
                self.assertEqual(retained_base, live_base)
                self.assertEqual(retained["counts"]["total_launches"], 36)
                self.assertEqual(retained["operator_calls"], 16)
                self.assertEqual(retained["event_profile_pairs"], 180)
                self.assertEqual(retained["framework_result_bytes"], 4096)

    def test_live_entrypoints_still_require_existing_paths(self):
        shutil.rmtree(self.root)
        for validate in (
                lambda: installed_check.validate_request(self.request["base_request"]),
                lambda: records.validate_request(self.request),
                lambda: base_records.verify_observations(self.value["base_observations"],
                    self.request["base_request"], **self.native,
                    raw_log=base_raw_log(self.value["base_observations"])),
                lambda: records.verify_observations(self.value, self.request,
                    **self.native, raw_log=raw_log(self.value))):
            with self.subTest(validator=validate), self.assertRaises((OSError, ValueError, installed_check.CheckError)):
                validate()
        with denied_live_access():
            self.verify()

    def test_live_adapter_still_requires_the_installed_bytes(self):
        adapter = Path(self.value["framework"]["adapter_file"])
        adapter.write_bytes(self.adapter_bytes + b"# changed live adapter\n")
        with self.assertRaisesRegex(ValueError, "adapter bytes"):
            records.verify_observations(self.value, self.request, **self.native, raw_log=raw_log(self.value))
        with denied_live_access():
            self.verify()

    def test_identity_is_exact_and_immutable_with_strict_receipt_types(self):
        with self.assertRaises(FrozenInstanceError):
            self.identity.request_sha256 = "0" * 64
        name, digest, size = self.identity.installed_files[0]
        malformed = (
            ("bad", self.identity.installed_files),
            (self.identity.request_sha256, list(self.identity.installed_files)),
            (self.identity.request_sha256, ([name, digest, size],)),
            (self.identity.request_sha256, ((name, digest, True),)),
            (self.identity.request_sha256, ((name, digest, -1),)),
            (self.identity.request_sha256, ((name, "A" * 64, size),)),
            (self.identity.request_sha256, ((name, digest, size), (name, digest, size))),
        )
        for digest, receipts in malformed:
            with self.subTest(receipts=repr(receipts)[:80]), self.assertRaises(ValueError):
                base_records.RetainedIdentity(digest, receipts)
        with self.assertRaisesRegex(ValueError, "identity"):
            self.verify(identity={"request_sha256": self.identity.request_sha256,
                                  "installed_files": self.identity.installed_files})

    def test_noncanonical_producer_paths_are_rejected_without_io(self):
        _, digest, size = self.identity.installed_files[0]
        names = ("relative/python", "//producer/python", "/producer/../python", "/producer/./python",
                 "/producer//python", "/producer/python/", "/producer/py\x00thon", "/producer\\python")
        with denied_live_access():
            for name in names:
                with self.subTest(path=name), self.assertRaises(ValueError):
                    base_records.RetainedIdentity(self.identity.request_sha256, ((name, digest, size),))

    def test_all_required_installed_receipts_are_joined(self):
        with denied_live_access():
            for index in range(len(self.identity.installed_files)):
                identity = replace(self.identity,
                    installed_files=self.identity.installed_files[:index] + self.identity.installed_files[index + 1:])
                with self.subTest(missing=index), self.assertRaisesRegex(ValueError, "receipt"):
                    self.verify(identity=identity)

    def test_frozen_requests_are_checked_even_when_their_digest_is_recomputed(self):
        mutations = (
            lambda value: value["base_request"].update(schema_version=True),
            lambda value: value["base_request"].update(iterations=True),
            lambda value: value["base_request"].update(extra=0),
            lambda value: value["base_request"]["binding"].update(extra=0),
            lambda value: value["base_request"]["matmul_cases"][0]["a_words"].__setitem__(0, "00000000"),
            lambda value: value["base_request"]["matmul_cases"].reverse(),
            lambda value: value["base_request"]["model_cases"].reverse(),
            lambda value: value["base_request"]["model_cases"].pop(),
            lambda value: value.update(contract_id="foreign"),
            lambda value: value["framework"].update(version="unlocked"),
            lambda value: value["framework"].update(extra=0),
        )
        with denied_live_access():
            for index, mutate in enumerate(mutations):
                request = copy.deepcopy(self.request)
                mutate(request)
                identity = replace(self.identity, request_sha256=request_digest(request["base_request"]))
                with self.subTest(mutation=index), self.assertRaises(ValueError):
                    self.verify(request=request, identity=identity)

    def test_request_pins_cannot_be_laundered_by_matching_observations(self):
        with denied_live_access():
            for key in ("bundle_sha256", "source_sha256", "qualification_id", "source_revision", "bundle_root"):
                request, value = copy.deepcopy(self.request), copy.deepcopy(self.value)
                replacement = "/foreign/bundle" if key == "bundle_root" else "1" * len(request["base_request"]["binding"][key])
                request["base_request"]["binding"][key] = replacement
                value["base_observations"]["binding"][key] = replacement
                with self.subTest(pin=key), self.assertRaisesRegex(ValueError, "request identity"):
                    self.verify(value, request=request)
            request = copy.deepcopy(self.request)
            request["base_request"]["expected_prefix"] = "/foreign/venv"
            with self.assertRaisesRegex(ValueError, "request identity"):
                self.verify(request=request)

    def test_foreign_nested_and_traversing_installation_paths_fail(self):
        installation = self.value["base_observations"]["installation"]
        package = str(Path(installation["package_file"]).parent)
        mutations = (
            ("package_file", package + "/nested/__init__.py"),
            ("package_file", package + "/../vortex_ai/__init__.py"),
            ("extension_file", package + "/_native.foreign.so"),
            ("executable", installation["prefix"] + "/bin/../bin/python"),
            ("base_prefix", "/host/../host-mock-python"),
            ("prefix", "/foreign/venv"),
        )
        with denied_live_access():
            for key, path in mutations:
                value = copy.deepcopy(self.value)
                value["base_observations"]["installation"][key] = path
                with self.subTest(field=key, path=path), self.assertRaises(ValueError):
                    self.verify(value)
            value = copy.deepcopy(self.value)
            value["framework"]["adapter_file"] = package + "/../vortex_ai/torch_ops.py"
            with self.assertRaisesRegex(ValueError, "adapter"):
                self.verify(value)

    def test_adapter_bytes_and_installed_digest_and_size_are_independently_joined(self):
        with denied_live_access():
            for adapter in (b"", bytearray(self.adapter_bytes), self.adapter_bytes + b"# corruption\n"):
                with self.subTest(adapter=type(adapter).__name__), self.assertRaisesRegex(ValueError, "adapter bytes"):
                    self.verify(adapter_bytes=adapter)
            for digest, size in (("0" * 64, len(self.adapter_bytes)),
                                 (hashlib.sha256(self.adapter_bytes).hexdigest(), len(self.adapter_bytes) + 1)):
                receipts = self.identity.installed_files[:-1] + ((self.value["framework"]["adapter_file"], digest, size),)
                identity = replace(self.identity, installed_files=receipts)
                with self.subTest(receipt=(digest, size)), self.assertRaisesRegex(ValueError, "receipt"):
                    self.verify(identity=identity)
            value, request = copy.deepcopy(self.value), copy.deepcopy(self.request)
            changed = self.adapter_bytes + b"# mutually changed request and observation\n"
            digest = hashlib.sha256(changed).hexdigest()
            value["framework"]["adapter_sha256"] = request["framework"]["adapter_sha256"] = digest
            with self.assertRaisesRegex(ValueError, "receipt"):
                self.verify(value, request=request, adapter_bytes=changed)

    def test_unchanged_native_lifecycle_abi_counts_and_tensor_checks_reject_corruption(self):
        mutations = (
            lambda value: value["base_observations"]["matmuls"][0]["actual_bits"].__setitem__(0, "00000000"),
            lambda value: value["base_observations"]["matmuls"][0]["trace"].update(argument_bytes="00" * 56),
            lambda value: value["base_observations"]["matmuls"][0]["close_status"].update(cleanup=6),
            lambda value: value["base_observations"]["matmuls"][0]["trace"]["event_profiles"][0].update(end_ns=0),
            lambda value: value["base_observations"]["models"][0]["record"]["trace"].update(owner_closed=False),
            lambda value: value["base_observations"]["models"][0]["record"]["trace"]["native"][1].update(a_bytes="00" * 128),
            lambda value: value["base_observations"]["counts"].update(total_launches=35),
            lambda value: value["framework_matmuls"][0]["a"].update(shape=[1, 1]),
            lambda value: value["framework_matmuls"][0]["b"].update(strides=[4, 1]),
            lambda value: value["framework_matmuls"][0]["a"].update(device="cuda:0"),
            lambda value: value["framework_matmuls"][0]["result"].update(requires_grad=True),
            lambda value: value["framework_models"][0]["result"].update(bytes="00"),
        )
        with denied_live_access():
            for index, mutate in enumerate(mutations):
                value = copy.deepcopy(self.value)
                mutate(value)
                with self.subTest(mutation=index), self.assertRaises(ValueError):
                    self.verify(value)
            native = copy.deepcopy(self.native)
            native["native_matmuls"][self.request["base_request"]["matmul_cases"][0]["id"]][0]["actual_bits"][0] = "00000000"
            with self.assertRaisesRegex(ValueError, "unchanged native executable"):
                self.verify(native=native)

    def test_raw_rows_chronology_and_failure_markers_remain_strict(self):
        raw = raw_log(self.value)
        lines = raw.splitlines(keepends=True)
        malformed = ("".join(lines[1:]), "".join([lines[0], lines[2], lines[1], *lines[3:]]),
                     "P05_TORCH_FRAMEWORK {}\n" + raw, "ERROR\n" + raw, "\x00\n" + raw)
        with denied_live_access():
            for index, text in enumerate(malformed):
                with self.subTest(raw=index), self.assertRaises(ValueError):
                    self.verify(raw=text)
            value = copy.deepcopy(self.value)
            value["framework_models"][0]["result"]["bytes"] = "00"
            with self.assertRaisesRegex(ValueError, "raw log"):
                self.verify(value, raw=raw)


if __name__ == "__main__":
    unittest.main()
