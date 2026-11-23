# SPDX-License-Identifier: Apache-2.0
"""Keep linker-map file limits distinct from JSON and command-log bounds."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import p06_dependency_binary as binary
import p06_dependency_contract as contract
import p06_dependency_receipt as receipts
import p06_dependency_record as recorder


def map_text():
    return binary.MAP_HEADING + "\n\nLOAD /build/input.o\n"


class DependencyMapLimitTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="p06-map-limits-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.roots = {name: self.root / name for name in recorder.ROOT_NAMES}
        for path in self.roots.values():
            path.mkdir()

    def test_map_above_json_and_log_limits_retains_and_parses(self):
        self.assertEqual(contract.MAX_FILE_BYTES, 64 * 1024**2)
        self.assertEqual(contract.MAX_RECEIPT_BYTES, 16 * 1024**2)
        self.assertEqual(contract.BUDGET["max_log_bytes"], 16 * 1024**2)
        text = map_text() + (" " * 4095 + "\n") * 4096
        body = text.encode("ascii")
        self.assertGreater(len(body), contract.MAX_RECEIPT_BYTES)
        self.assertGreater(len(body), contract.BUDGET["max_log_bytes"])
        self.assertLess(len(body), contract.MAX_FILE_BYTES)
        path = self.roots["build"] / "large.map"
        path.write_bytes(body)
        retained = recorder._retain(path, self.roots, maximum=contract.MAX_FILE_BYTES)
        observed = receipts.payload(retained, lambda name: (self.root / name).read_bytes())
        self.assertEqual(observed, body)
        parsed = binary.parse_link_map(observed.decode("ascii"), cwd="/build")
        self.assertEqual(parsed["loads"], ["/build/input.o"])
        self.assertEqual(parsed["size_bytes"], len(body))
        self.assertEqual(parsed["sha256"], hashlib.sha256(body).hexdigest())
        self.assertEqual(path.read_bytes(), body)
        with self.assertRaisesRegex(ValueError, "JSON exceeds its byte bound"):
            receipts.decode(b"{" + b" " * contract.MAX_RECEIPT_BYTES + b"}")

    def test_parser_includes_exact_file_limit_and_rejects_one_byte_more(self):
        text = map_text()
        with mock.patch.object(contract, "MAX_FILE_BYTES", len(text)):
            self.assertEqual(binary.parse_link_map(text, cwd="/build")["size_bytes"], len(text))
            with self.assertRaisesRegex(ValueError, "bounded text"):
                binary.parse_link_map(text + "\n", cwd="/build")

    def test_retention_includes_exact_file_limit_and_rejects_one_byte_more(self):
        body = map_text().encode("ascii")
        path = self.roots["build"] / "bounded.map"
        path.write_bytes(body)
        with mock.patch.object(contract, "MAX_FILE_BYTES", len(body)):
            retained = recorder._retain(path, self.roots, maximum=contract.MAX_FILE_BYTES)
            self.assertEqual(retained["size_bytes"], len(body))
            path.write_bytes(body + b"\n")
            with self.assertRaisesRegex(recorder.RecorderError, "exceeds its byte bound"):
                recorder._retain(path, self.roots, maximum=contract.MAX_FILE_BYTES)
        self.assertEqual((self.roots["payloads"] / retained["payload"]).read_bytes(), body)
        self.assertEqual(len(list(self.roots["payloads"].glob("*.bin"))), 1)

    def test_file_limit_does_not_remove_independent_map_line_bounds(self):
        text = map_text()
        lines = text.split("\n")
        self.assertLess(len(text), contract.MAX_FILE_BYTES)
        with mock.patch.object(binary, "MAX_MAP_LINES", len(lines)), \
                mock.patch.object(binary, "MAX_MAP_LINE_BYTES", max(map(len, lines))):
            binary.parse_link_map(text, cwd="/build")
        with mock.patch.object(binary, "MAX_MAP_LINES", len(lines) - 1), \
                self.assertRaisesRegex(ValueError, "line bounds"):
            binary.parse_link_map(text, cwd="/build")
        with mock.patch.object(binary, "MAX_MAP_LINE_BYTES", max(map(len, lines)) - 1), \
                self.assertRaisesRegex(ValueError, "line bounds"):
            binary.parse_link_map(text, cwd="/build")

    def test_file_payload_still_obeys_packet_and_symlink_bounds(self):
        body = map_text().encode("ascii")
        path = self.roots["build"] / "packet.map"
        path.write_bytes(body)
        with mock.patch.object(contract, "MAX_PACKET_BYTES", len(body) - 1), \
                self.assertRaisesRegex(recorder.RecorderError, "payload budget exceeded"):
            recorder._retain(path, self.roots, maximum=contract.MAX_FILE_BYTES)
        self.assertEqual(list(self.roots["payloads"].glob("*.bin")), [])
        alias = self.roots["build"] / "alias.map"
        alias.symlink_to(path)
        with self.assertRaisesRegex(recorder.RecorderError, "symlink"):
            recorder._retain(alias, self.roots, maximum=contract.MAX_FILE_BYTES)

    def test_json_writer_and_reader_keep_their_separate_byte_bound(self):
        document = {"value": "bounded receipt"}
        body = contract.json_bytes(document) + b"\n"
        exact = self.roots["receipts"] / "exact.json"
        excess = self.roots["receipts"] / "excess.json"
        with mock.patch.object(contract, "MAX_RECEIPT_BYTES", len(body)):
            recorder._write_record(exact, document, exclusive=True)
            self.assertEqual(exact.read_bytes(), body)
            self.assertEqual(receipts.decode(body), document)
            with self.assertRaisesRegex(recorder.RecorderError, "receipt exceeds its byte bound"):
                recorder._write_record(excess, {"value": document["value"] + "x"}, exclusive=True)
            with self.assertRaisesRegex(ValueError, "JSON exceeds its byte bound"):
                receipts.decode(body + b" ")
        self.assertFalse(excess.exists())

    def test_real_link_record_uses_file_limit_instead_of_json_limit(self):
        tools = {}
        for name in recorder.TOOLS:
            path = shutil.which(name)
            self.assertIsNotNone(path, name + " must be available for the actual-link test")
            tools[name] = recorder.file_identity(path)
        environment = {name: value for name, value in os.environ.items()
                       if name not in recorder.INJECTION_ENVIRONMENT}
        source = self.roots["sources"] / "sample.c"
        source.write_text("int sample(void) { return 37; }\n")
        obj = self.roots["build"] / "sample.o"
        subprocess.run([tools["gcc"]["path"], "-fPIC", "-c", str(source), "-o", str(obj)],
                       cwd=self.roots["build"], env=environment, check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        output = self.roots["build"] / "libsample.so"
        link_map = self.roots["build"] / "sample.map"
        config_path = self.root / "config.json"
        with mock.patch.object(contract, "MAX_RECEIPT_BYTES", 8192), \
                mock.patch.dict(os.environ, environment, clear=True):
            config = {"schema_version": 1, "contract_id": recorder.CONTRACT_ID,
                      "contract_sha256": contract.contract_hash(),
                      "roots": {name: str(path) for name, path in self.roots.items()},
                      "tools": tools}
            config_body = contract.json_bytes(config) + b"\n"
            config_path.write_bytes(config_body)
            result = recorder.run(config_path, hashlib.sha256(config_body).hexdigest(),
                                  "g++", "link", ["-shared", str(obj),
                                  "-Wl,-Map," + str(link_map), "-o", str(output)],
                                  cwd=self.roots["build"])
            self.assertEqual(result["outcome"], "pass", result["reason"])
            self.assertIs(result["process_started"], True)
            self.assertEqual(result["exit_code"], 0)
            self.assertEqual([row["stage"] for row in result["children"]], ["tool"])
            self.assertEqual(result["inputs_before"], result["inputs_after"])
            self.assertGreater(result["link_map"]["size_bytes"], contract.MAX_RECEIPT_BYTES)
            record_body = (self.roots["receipts"] / (result["id"] + ".json")).read_bytes()
            self.assertLessEqual(len(record_body), contract.MAX_RECEIPT_BYTES)
            self.assertEqual(json.loads(record_body), result)
            self.assertEqual(receipts.payload(result["link_map"],
                             lambda name: (self.root / name).read_bytes()), link_map.read_bytes())


if __name__ == "__main__":
    unittest.main()
