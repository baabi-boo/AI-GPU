# SPDX-License-Identifier: Apache-2.0
"""Distinguish exact archive inputs from the members a real linker selects.

The tiny fixture executes six host compiles, three archives, two indexes and two
links. Producer product checks and inert archive/link checks consume those real
bytes. The full-receipt entry fixture explicitly substitutes upstream source,
configuration, individual-record, fixed-population and stability validation; it
does not represent a complete pinned dependency build or a native original.
"""

from collections import Counter
from contextlib import ExitStack
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

import p06_dependency_binary as binary
import p06_dependency_build as build
import p06_dependency_contract as contract
import p06_dependency_receipt as receipt
import p06_dependency_record as recorder


class UnselectedArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="p06-unused-archive-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        cls.measurement = cls.root / "measurement"
        cls.workspace = cls.root / "workspace"
        cls.sources = cls.workspace / "dependency-sources"
        cls.build_root = cls.workspace / "dependency-build"
        cls.packet = cls.workspace / "evidence"
        for path in (cls.measurement, cls.sources, cls.build_root, cls.packet,
                     cls.build_root / "home", cls.build_root / "tmp", cls.build_root / "extension",
                     cls.packet / "records", cls.packet / "payloads"):
            path.mkdir(parents=True, exist_ok=True)
        cls.tools = {}
        for name in build.HOST_TOOLS:
            path = shutil.which(name)
            if path is None:
                raise AssertionError("required fixture tool absent: " + name)
            cls.tools[name] = recorder.file_identity(path)
        cls.config = {"schema_version": 1, "contract_id": recorder.CONTRACT_ID,
                      "contract_sha256": contract.contract_hash(), "roots": {
                          "sources": str(cls.sources), "build": str(cls.build_root),
                          "receipts": str(cls.packet / "records"),
                          "payloads": str(cls.packet / "payloads")},
                      "tools": {name: cls.tools[name] for name in recorder.TOOLS}}
        cls.config_path = cls.packet / "tool-config.json"
        cls.config_sha = build.write_json(cls.config_path, cls.config)["sha256"]
        cls.environment = build.clean_environment(cls.build_root)
        cls.plan, cls.actual_records, cls.compiles = [], [], {}

        def execute(tool, role, arguments, cwd):
            with mock.patch.dict(os.environ, cls.environment, clear=True):
                result = recorder.run(cls.config_path, cls.config_sha, tool, role,
                                      list(map(str, arguments)), cwd=cwd)
            if result["outcome"] != "pass":
                raise AssertionError(result["reason"])
            cls.actual_records.append(result)
            return result

        units = [
            ("softfloat", "softfloat/source/soft.c", "int soft(void) { return 5; }\n",
             cls.sources / "softfloat/build/Linux-x86_64-GCC/soft.o"),
            ("yaml-cpp", "yaml-cpp/selected.c", "int selected(void) { return 11; }\n",
             cls.build_root / "ramulator/_deps/yaml-cpp-build/selected.c.o"),
            ("spdlog", "spdlog/unused1.c", "int unused_one(void) { return 17; }\n",
             cls.build_root / "ramulator/_deps/spdlog-build/unused1.c.o"),
            ("spdlog", "spdlog/unused2.c", "int unused_two(void) { return 23; }\n",
             cls.build_root / "ramulator/_deps/spdlog-build/unused2.c.o"),
            ("ramulator", "ramulator/shared.c",
             "int selected(void); int ramulator(void) { return selected(); }\n",
             cls.build_root / "ramulator/ramulator.c.o"),
            ("extension", "ramulator/extension.c",
             "int ramulator(void); int extension(void) { return ramulator(); }\n",
             cls.build_root / "extension/gddr6.o"),
        ]
        for component, name, body, output in units:
            source = cls.sources / name
            source.parent.mkdir(parents=True, exist_ok=True)
            output.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(body)
            record = execute("gcc", "compile", ["-fPIC", "-c", source, "-o", output], output.parent)
            cls.compiles[str(source)] = record
            cls.plan.append({"component": component, "source": name, "archive_member": output.name})
        cls.archive_paths = {}
        for component in ("softfloat", "yaml-cpp", "spdlog"):
            objects = [cls.compiles[str(cls.sources / item["source"])]["output_path"]
                       for item in cls.plan if item["component"] == component]
            path = (cls.sources / "softfloat/build/Linux-x86_64-GCC/softfloat.a"
                    if component == "softfloat" else cls.build_root / "ramulator/_deps" /
                    (component + "-build") / ("lib" + component + ".a"))
            cls.archive_paths[component] = str(path)
            execute("ar", "archive", ["crs" if component == "softfloat" else "qc", path, *objects], path.parent)
            if component != "softfloat":
                execute("ranlib", "index", [path], path.parent)
        cls.maps = {name: cls.build_root / (name + ".map") for name in ("ramulator", "extension")}
        ramulator_output = cls.sources / "ramulator/libramulator.so"
        execute("g++", "link", ["-shared", cls.compiles[str(cls.sources / "ramulator/shared.c")]["output_path"],
                cls.archive_paths["yaml-cpp"], cls.archive_paths["spdlog"],
                "-Wl,-Map," + str(cls.maps["ramulator"]), "-o", ramulator_output], cls.build_root / "ramulator")
        execute("g++", "link", ["-shared", cls.compiles[str(cls.sources / "ramulator/extension.c")]["output_path"],
                "-L" + str(cls.sources / "ramulator"), "-lramulator",
                "-Wl,-Map," + str(cls.maps["extension"]), "-o",
                cls.build_root / "extension/libramulator-vortex.so"], cls.build_root / "extension")
        cls.original_maps = {name: path.read_bytes() for name, path in cls.maps.items()}
        cls.archive_members = {path: binary.parse_archive(Path(path).read_bytes())["members"]
                               for path in cls.archive_paths.values()}
        cls.ramulator_link = next(row for row in cls.actual_records if row["role"] == "link"
                                 and row["output_path"] == str(ramulator_output))
        actual_payloads = {"payloads/" + path.name: path.read_bytes()
                           for path in (cls.packet / "payloads").glob("*.bin")}
        for row in cls.actual_records:
            receipt._validate_record(row, cls.config, cls.config_sha,
                                     actual_payloads.__getitem__, recorder.file_identity(recorder.__file__))

    def setUp(self):
        for name, body in self.original_maps.items():
            self.maps[name].write_bytes(body)

    def producer(self):
        result = object.__new__(build.Builder)
        result.source, result.workspace = self.measurement, self.workspace
        result.source_root, result.build_root, result.output = self.sources, self.build_root, self.packet
        result.report = {"source_plan": deepcopy(self.plan), "tools": self.tools,
                         "archives": [], "external_archives": [], "maps": [], "products": {}}
        return result

    def parsed(self, text=None):
        return binary.parse_link_map(text or self.original_maps["ramulator"].decode(),
                                     cwd=self.ramulator_link["cwd"])

    def test_actual_map_selects_yaml_but_keeps_spdlog_as_an_exact_input(self):
        self.assertEqual(Counter(row["role"] for row in self.actual_records),
                         {"compile": 6, "archive": 3, "index": 2, "link": 2})
        parsed = self.parsed()
        self.assertEqual([row["archive"] for row in parsed["selected_members"]],
                         [self.archive_paths["yaml-cpp"]])
        for name in ("yaml-cpp", "spdlog"):
            self.assertEqual(parsed["loads"].count(self.archive_paths[name]), 1)
            self.assertIn(self.archive_paths[name], [row["path"] for row in self.ramulator_link["inputs_before"]])
        self.assertEqual(self.ramulator_link["inputs_before"], self.ramulator_link["inputs_after"])

    def test_generic_required_archive_default_still_rejects_zero_selection(self):
        with self.assertRaisesRegex(ValueError, "required archive-member evidence"):
            binary.validate_link_map(self.original_maps["ramulator"].decode(),
                cwd=self.ramulator_link["cwd"], archives=self.archive_members)

    def test_actual_producer_admits_only_the_observed_member_selection(self):
        producer = self.producer()
        producer.verify_products()
        self.assertEqual(set(producer.report["products"]), set(contract.PRODUCTS))
        mapping = next(row["verification"] for row in producer.report["maps"] if row["name"] == "ramulator")
        self.assertEqual(mapping["required_archives"], [self.archive_paths["yaml-cpp"]])
        self.assertEqual([row["archive"] for row in mapping["selected_members"]],
                         [self.archive_paths["yaml-cpp"]])
        self.assertEqual(len(next(row for row in producer.report["archives"] if row["name"] == "spdlog")["members"]), 2)

    def test_producer_rejects_missing_duplicated_or_substituted_spdlog_load(self):
        original = self.original_maps["ramulator"].decode()
        load = "LOAD " + self.archive_paths["spdlog"] + "\n"
        self.assertEqual(original.count(load), 1)
        for replacement in ("", load * 2, load.replace("libspdlog.a", "libsubstitute.a")):
            with self.subTest(replacement=replacement):
                self.maps["ramulator"].write_text(original.replace(load, replacement))
                with self.assertRaisesRegex(ValueError, "unique required LOAD"):
                    self.producer().verify_products()

    def test_yaml_selection_and_admitted_member_identity_remain_required(self):
        original = self.original_maps["ramulator"].decode()
        without_selection = binary.MAP_HEADING + "\n\n" + "".join(
            "LOAD " + name + "\n" for name in self.parsed()["loads"])
        mutations = (
            (without_selection, "required archive-member evidence"),
            (original.replace("selected.c.o)", "unadmitted.c.o)"), "unadmitted archive member"),
            (original.replace(self.archive_paths["yaml-cpp"], self.archive_paths["spdlog"]),
             "unadmitted archive member"),
            (original.replace(self.archive_paths["yaml-cpp"],
                              self.archive_paths["yaml-cpp"].replace("libyaml-cpp.a", "libunknown.a")),
             "unadmitted archive"),
        )
        for text, reason in mutations:
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                binary.validate_link_map(text, cwd=self.ramulator_link["cwd"], archives=self.archive_members,
                    required_archives=[self.archive_paths["yaml-cpp"]],
                    required_loads=[self.archive_paths[name] for name in ("yaml-cpp", "spdlog")])

    def scoped_receipt(self):
        """Real product joins behind explicit unrelated upstream substitutions."""
        producer = self.producer()
        producer.verify_products()
        payloads = {"payloads/" + path.name: path.read_bytes()
                    for path in (self.packet / "payloads").glob("*.bin")}

        def retain(name, body):
            payloads[name] = body
            return {"path": name, "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)}

        document = dict.fromkeys(receipt.REPORT_FIELDS)
        revision = "a" * 40
        document.update(schema_version=1, contract_id=contract.CONTRACT_ID,
            dependency_contract_sha256=contract.contract_hash(), expected_revision=revision,
            state="finished", outcome="pass", reason=None, failures=[], fresh_dependency_build_passed=True,
            budget=dict(contract.BUDGET), environment=self.environment, source_manifest={"sources": []},
            source_plan=deepcopy(self.plan), tools=self.tools, **dict.fromkeys(contract.FALSE_CLAIMS, False))
        document["paths"] = {"source": str(self.measurement), "workspace": str(self.workspace),
                             "sources": str(self.sources), "build": str(self.build_root), "output": str(self.packet)}
        document["tool_config"] = retain("tool-config.json", self.config_path.read_bytes())
        preparation = {"contract_id": "p06-dependency-preparation-v1", "outcome": "pass", "reason": None,
                       "dependency_cache_used": False, "expected_revision": revision,
                       "dependency_contract_sha256": contract.contract_hash()}
        document["preparation"] = retain("preparation.json", contract.json_bytes(preparation))
        checkout = {"revision": revision, "dirty": False, "blockers": []}
        document["source_checkout_before"] = retain("before.json", contract.json_bytes(checkout))
        document["source_checkout_after"] = retain("after.json", contract.json_bytes(checkout))
        helper_name = "ci/project/p06_dependency_record.py"
        helper = retain("helpers/" + helper_name, Path(recorder.__file__).read_bytes())
        document["helper_sources"] = [dict(helper, path=helper_name)]
        records = deepcopy(self.actual_records)
        # Only the six actual fixture compiles feed product checks. The inert
        # entry point's fixed count is satisfied by explicitly synthetic rows;
        # its full source/record/population premise is substituted below.
        for number in range(406 - len(self.compiles)):
            records.append({"role": "compile", "id": "synthetic-" + str(number).zfill(4),
                            "environment": self.environment})
        document["records"] = sorted([retain("records/" + row["id"] + ".json", contract.json_bytes(row))
                                      for row in records], key=lambda row: row["path"])
        for name in ("products", "archives", "external_archives", "maps"):
            document[name] = deepcopy(producer.report[name])
        document["staged_files"] = sorted([{"path": row["staged_path"], "sha256": row["sha256"],
                                            "size_bytes": row["size_bytes"]}
                                           for row in document["products"].values()], key=lambda row: row["path"])
        document["retained_files"] = sorted([{"path": name, "sha256": hashlib.sha256(body).hexdigest(),
                                              "size_bytes": len(body)} for name, body in payloads.items()],
                                             key=lambda row: row["path"])
        return document, payloads

    def verify_scoped(self, document, payloads):
        compiles = deepcopy(self.compiles)
        outputs = {row["output_path"]: row for row in compiles.values()}
        commands = dict.fromkeys(("softfloat", "ramulator-configure", "ramulator-build",
                                  "extension-compile", "extension-link"), {})
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(receipt, "_verify_outer_commands", return_value=commands))
            stack.enter_context(mock.patch.object(receipt, "_validate_record", side_effect=lambda row, *args: row))
            stack.enter_context(mock.patch.object(receipt, "_verify_compile_graph",
                                                  return_value=(self.plan, compiles, outputs)))
            stack.enter_context(mock.patch.object(receipt, "_verify_generated_build"))
            stack.enter_context(mock.patch.object(receipt, "_verify_source_stability"))
            stack.enter_context(mock.patch("subprocess.Popen", side_effect=AssertionError("inert reader executed code")))
            stack.enter_context(mock.patch.object(Path, "open", side_effect=AssertionError("inert reader opened producer path")))
            return receipt.verify_document(document, payloads.__getitem__, expected_revision="a" * 40)

    def replace_payload(self, document, payloads, path, body):
        payloads[path] = body
        for row in document["retained_files"]:
            if row["path"] == path:
                row.update(sha256=hashlib.sha256(body).hexdigest(), size_bytes=len(body))
        for row in document["records"]:
            if row["path"] == path:
                row.update(sha256=hashlib.sha256(body).hexdigest(), size_bytes=len(body))

    def test_inert_receipt_callsite_preserves_real_archive_and_link_joins(self):
        document, payloads = self.scoped_receipt()
        result = self.verify_scoped(document, payloads)
        mapping = result["links"]["ramulator"]["map"]
        self.assertEqual(mapping["required_archives"], [self.archive_paths["yaml-cpp"]])
        self.assertEqual([row["archive"] for row in mapping["selected_members"]],
                         [self.archive_paths["yaml-cpp"]])
        self.assertEqual(len(result["archives"]["spdlog"]["members"]), 2)
        self.assertTrue(all(result[name] is False for name in contract.FALSE_CLAIMS))

    def test_inert_receipt_rejects_reordered_or_substituted_unused_archive_inputs(self):
        for mutation in ("reordered", "substituted", "omitted"):
            document, payloads = self.scoped_receipt()
            row = next(item for item in self.actual_records if item["role"] == "archive"
                       and item["output_path"] == self.archive_paths["spdlog"])
            path = "records/" + row["id"] + ".json"
            changed = json.loads(payloads[path])
            if mutation == "reordered":
                changed["requested_arguments"][2:] = reversed(changed["requested_arguments"][2:])
                changed["inputs_before"].reverse()
                reason = "archive creation object order differs"
            elif mutation == "substituted":
                changed["inputs_before"][0] = deepcopy(self.compiles[str(self.sources / "yaml-cpp/selected.c")]["output"])
                reason = "archive does not consume its completed compiler outputs"
            else:
                changed["requested_arguments"].pop()
                changed["inputs_before"].pop()
                reason = "archive creation object order differs"
            self.replace_payload(document, payloads, path, contract.json_bytes(changed))
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, reason):
                self.verify_scoped(document, payloads)

    def test_inert_receipt_rejects_changed_unused_archive_bytes_at_link(self):
        document, payloads = self.scoped_receipt()
        path = "records/" + self.ramulator_link["id"] + ".json"
        changed = json.loads(payloads[path])
        item = next(row for row in changed["inputs_before"] if row["path"] == self.archive_paths["spdlog"])
        item["sha256"] = "0" * 64
        changed["inputs_after"] = deepcopy(changed["inputs_before"])
        self.replace_payload(document, payloads, path, contract.json_bytes(changed))
        with self.assertRaisesRegex(ValueError, "link consumes different dependency objects or archives"):
            self.verify_scoped(document, payloads)

    def test_inert_receipt_rejects_rehashed_missing_duplicate_and_alternate_spdlog_load(self):
        original = self.original_maps["ramulator"].decode()
        load = "LOAD " + self.archive_paths["spdlog"] + "\n"
        for replacement in ("", load * 2, load.replace("libspdlog.a", "libsubstitute.a")):
            document, payloads = self.scoped_receipt()
            record_path = "records/" + self.ramulator_link["id"] + ".json"
            changed = json.loads(payloads[record_path])
            body = original.replace(load, replacement).encode()
            digest = hashlib.sha256(body).hexdigest()
            changed["link_map"].update(sha256=digest, size_bytes=len(body), payload=digest + ".bin")
            payloads["payloads/" + digest + ".bin"] = body
            self.replace_payload(document, payloads, record_path, contract.json_bytes(changed))
            mapping = next(row for row in document["maps"] if row["name"] == "ramulator")
            mapping["descriptor"] = {"path": "payloads/" + digest + ".bin",
                                     "sha256": digest, "size_bytes": len(body)}
            document["retained_files"] = sorted([{"path": name, "sha256": hashlib.sha256(value).hexdigest(),
                                                  "size_bytes": len(value)} for name, value in payloads.items()],
                                                 key=lambda row: row["path"])
            with self.subTest(replacement=replacement), self.assertRaisesRegex(ValueError, "unique required LOAD"):
                self.verify_scoped(document, payloads)


if __name__ == "__main__":
    unittest.main()
