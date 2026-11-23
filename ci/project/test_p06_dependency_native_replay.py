# SPDX-License-Identifier: Apache-2.0
"""Synthetic native-original replay controls, never fresh execution evidence.

The full native fixture deliberately invents new object payloads, dependency
metadata and raw lifetime observations. Immutable historical source/build/log
bytes supply realistic grammar inputs only. No original archive is upgraded or
admitted as the new route: the resulting fixture is a new synthetic document.
The dependency receipt's complete build semantics have their separate tests.
"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path, PurePosixPath
import tempfile
import unittest
from unittest import mock
import zipfile

import p06_dependency_native_replay as replay
import p06_native_lifetime_test_fixture as fixture
from test_p06_dependency_binary import map_text


ROOT = replay.ROOT
HISTORICAL = ROOT / "docs/project/evidence/p06-native-lifetime/native/b4127b19-run45130300651-attempt1/original.zip"
HISTORICAL_SHA256 = "3d4879f73c197352689d65feb56e73f537701fc1411e55bf53c92b1b41e13db3"


def digest(body):
    return hashlib.sha256(body).hexdigest()


def descriptor(path, body):
    return {"path": path, "sha256": digest(body), "size_bytes": len(body)}


def json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


class MemoryView:
    """A bounded inert byte store with the real archive descriptor grammar."""

    def __init__(self, files, api):
        self.contents = files
        self.api = api

    def files(self):
        return sorted(self.contents)

    def read(self, name, *, limit=None):
        self.api.relative_name(name)
        data = self.contents[name]
        if limit is not None and len(data) > limit:
            raise ValueError("fixture member exceeds its bound")
        return data

    def json(self, name):
        return self.api.strict_json(self.read(name))

    def identity(self, name, *, limit=None):
        return descriptor(name, self.read(name, limit=limit))

    def verified(self, row, expected=None):
        self.api.descriptor(row)
        if expected is not None and row["path"] != expected:
            raise ValueError("fixture expected path differs")
        replay._same(self.identity(row["path"]), row, "fixture retained identity")
        return self.read(row["path"])


class SyntheticNativePacket:
    """All 37 receipts and four transcripts pass actual native replay semantics."""

    def __deepcopy__(self, memo):
        copied = type(self).__new__(type(self))
        memo[id(self)] = copied
        memo[id(self.api)] = self.api
        copied.__dict__ = deepcopy(self.__dict__, memo)
        return copied

    def __init__(self):
        if digest(HISTORICAL.read_bytes()) != HISTORICAL_SHA256:
            raise AssertionError("immutable grammar fixture archive changed")
        with zipfile.ZipFile(HISTORICAL) as archive:
            self.files = {name[len("native-lifetime/"):]: archive.read(name)
                          for name in archive.namelist() if name.startswith("native-lifetime/")
                          and not name.endswith("/")}
        self.report = json.loads(self.files["report.json"])
        self.source = json.loads(self.files[self.report["source_before"]["path"]])
        self.tools = json.loads(self.files[self.report["tools_before"]["path"]])
        self.revision = self.report["expected_revision"]
        self.api = replay.dependency_replay._archive_api()
        self.contract = replay.manifest.load_contract(ROOT)
        self.cases = replay.manifest.select_cases(self.contract, ROOT)
        source_names = {row["path"] for row in self.source["files"]}
        required = (set(replay.source_inventory.REQUIRED_SOURCE_NAMES) | set(replay.producer.SOURCE_FILES)
            | set(replay.lifetime.SOURCE_FILES) | set(replay.admission.SOURCE_FILES) | set(replay.RUNNER_HELPERS))
        for name in required:
            if name not in source_names or name in replay.RUNNER_HELPERS or name in replay.admission.SOURCE_FILES:
                self.files["artifacts/source/" + name] = (ROOT / name).read_bytes()
            source_names.add(name)
        self.source["files"] = [descriptor(name, self.files["artifacts/source/" + name])
                                for name in sorted(source_names)]
        self.sources = {row["path"]: row for row in self.source["files"]}
        self.report["retained_sources"] = [dict(row, path="artifacts/source/" + row["path"])
                                            for row in self.source["files"]]
        self.report["loaded_helpers"] = [self.sources[name] for name in replay.RUNNER_HELPERS]
        for which in ("before", "after"):
            self.report["source_" + which] = self.put_json("snapshots/source-" + which + ".json", self.source)
        self.source_pin = self.report["source_before"]["sha256"]
        self.make_dependencies()
        self.report.update(contract_id=replay.admission.CONTRACT_ID, scope=replay.admission.SCOPE,
            contract_sha256=replay.admission.contract_hash(), dependency_receipt_sha256=self.receipt_pin,
            dependency_admission=self.admission, dependency_admission_before=self.stability,
            dependency_admission_after=self.stability, dependency_source_to_loaded_binary_verified=True,
            limitations=[*replay.admission.LIMITATIONS, *replay.producer.base.PROCESS_LIMITATIONS])
        self.report["contract_snapshot"] = self.put_json("snapshots/contract.json", replay.admission.contract())
        self.report["retained_dependency_receipt"] = self.put("artifacts/dependency-receipt/report.json", self.dependency_body)
        self.old_commands = {row["id"]: row for row in self.report["commands"]}
        self.commands = self.report["commands"][:7]
        self.report["processes"] = []
        for variant in self.report["variants"]:
            self.make_variant(variant)
        self.report["commands"] = self.commands
        self.report["raw_logs"] = [descriptor(row["log"], self.files[row["log"]]) for row in self.commands]
        labels = []
        for row in self.commands:
            labels.extend(("before-command-" + row["id"], "after-command-" + row["id"]))
            if row["native_process"]:
                labels.append("after-process-" + row["id"])
                if row["id"].endswith("reusable_single_tile"):
                    labels.append("after-variant-simx-" + ("bf16" if "bf16" in row["id"] else "fp16"))
        self.report["stability_checks"] = [{"at": self.report["started_at"], "label": label,
            "source_sha256": replay.qualification_id(self.source),
            "tools_sha256": replay.qualification_id(self.tools),
            "dependencies_sha256": replay.qualification_id(json.loads(self.files[self.report["dependencies_before"]["path"]])),
            "dependency_admission": self.stability} for label in labels]
        payloads = list(self.report["retained_dependency_payloads"])
        for variant in self.report["variants"]:
            payloads.extend(variant["retained_binary_payloads"])
            payloads.extend(variant["retained_dependency_model_payloads"])
        self.report["retained_payload_bytes"] = sum(row["size_bytes"] for row in payloads)
        self.finish()

    def put(self, name, data):
        self.files[name] = data
        return descriptor(name, data)

    def put_json(self, name, value):
        return self.put(name, json_bytes(value))

    def finish(self):
        self.report["retained_files"] = [descriptor(name, body) for name, body in sorted(self.files.items())
                                          if name != "report.json" and not name.startswith("logs/")]
        self.put_json("report.json", self.report)

    def make_dependencies(self):
        products = {}
        for name, relative in replay.dependency_contract.PRODUCTS.items():
            payload = self.files["artifacts/dependencies/" + relative]
            products[name] = {"original_path": "/synthetic-dependency-build/" + PurePosixPath(relative).name,
                "staged_path": str(PurePosixPath(self.report["paths"]["source"]) / relative),
                "sha256": digest(payload), "size_bytes": len(payload), "payload": "payloads/" + digest(payload) + ".bin"}
        components, staged = [], []
        for name, pin in replay.dependency_contract.PINS.items():
            prefix = pin["path"] + "/"
            rows = [dict(row, path=path[len(prefix):]) for path, row in self.sources.items() if path.startswith(prefix)]
            components.append({"name": name, "files": rows})
            if name in ("yaml-cpp", "spdlog", "argparse"):
                staged.extend(dict(row, path=str(PurePosixPath(self.report["paths"]["source"]) / prefix / row["path"]))
                              for row in rows)
        staged.extend({"path": row["staged_path"], "sha256": row["sha256"], "size_bytes": row["size_bytes"]}
                      for row in products.values())
        softfloat = self.files["artifacts/dependencies/" + replay.dependency_contract.PRODUCTS["softfloat"]]
        self.members = replay.binary.parse_archive(softfloat)["members"]
        self.preparation_body = json_bytes({"synthetic_preparation": True})
        self.dependency_document = {"paths": {"source": self.report["paths"]["source"],
                                              "workspace": "/synthetic-dependency-build"},
            "source_manifest": {"sources": components}, "staged_files": sorted(staged, key=lambda row: row["path"]),
            "helper_sources": [self.sources[name] for name in replay.RUNNER_HELPERS], "tools": self.tools,
            "products": products, "external_archives": [],
            "preparation": descriptor("snapshots/preparation.json", self.preparation_body)}
        self.dependency_verification = {"synthetic_dependency_metadata": True,
            "archives": {"softfloat": {"members": self.members}}, "fresh_dependency_build_passed": True,
            **dict.fromkeys(replay.manifest.FALSE_CLAIMS, False)}
        self.dependency_body = json_bytes(self.dependency_document)
        self.receipt_pin = digest(self.dependency_body)
        self.admission, self.stability = replay._admission_values(self.dependency_document,
            self.dependency_verification, self.receipt_pin)

    def log(self, row, text):
        data = text.encode()
        self.put(row["log"], data)
        row.update(log_sha256=digest(data), log_size_bytes=len(data))

    def make_variant(self, variant):
        fmt, variant_id = variant["format"], variant["id"]
        source, build = PurePosixPath(self.report["paths"]["source"]), PurePosixPath(variant["build_dir"])
        original_backend = deepcopy(self.old_commands[variant_id + "-backend"])
        original_lines = self.files[original_backend["log"]].decode().splitlines()
        if len(original_lines) != 46:
            raise AssertionError("historical model grammar population changed")
        model_lines = original_lines[1:-1]
        left, separator, right = model_lines[-1].rpartition(" -o ")
        model_lines[-1] = left + " -Wl,-Map," + str(build / replay.admission.MODEL_MAP) + separator + right
        model_text = "\n".join(model_lines) + "\n"
        backend_text = "\n".join((original_lines[0], original_lines[-1])) + "\n"
        model_command = deepcopy(original_backend)
        model_command.update(id=variant_id + "-dependency-model", log="logs/" + variant_id + "-dependency-model.log",
            cwd=str(build / "sim/simx"))
        model_command["argv"][-2:] = [str(build / replay.admission.MODEL_MAKEFILE), str(build / "sw/runtime/libsimx.so")]
        self.log(model_command, model_text)
        self.log(original_backend, backend_text)
        variant["dependency_model_build_command"] = model_command["id"]
        stages = {row["stage"]: row for row in variant["retained_builds"]}
        for label, stage in stages.items():
            name = "artifacts/" + variant_id + "/" + label + "/" + replay.admission.MODEL_MAKEFILE
            stage["files"].append(self.put(name, replay.MODEL_RECIPE))
            stage["files"].sort(key=lambda row: row["path"])
        frozen = {row["path"]: row for row in variant["artifacts_before"]}
        frozen[replay.admission.MODEL_MAKEFILE] = descriptor(replay.admission.MODEL_MAKEFILE, replay.MODEL_RECIPE)
        object_names = [replay.build_records.expected_object(name, str(build)).relative_to(build).as_posix()
                        for name in replay.build_records.MODEL_SOURCES]
        variant["retained_dependency_model_payloads"] = []
        for name in object_names:
            data = b"synthetic model object, never executed: " + name.encode()
            frozen[name] = descriptor(name, data)
            variant["retained_dependency_model_payloads"].append(self.put(
                "artifacts/" + variant_id + "/dependency-model/" + name, data))
        objects = sorted(str(build / name) for name in object_names)
        products = self.dependency_document["products"]
        softfloat = products["softfloat"]["staged_path"]
        text = map_text([softfloat + "(" + self.members[0]["name"] + ") " + objects[0] + " (synthetic_symbol)"],
            [*objects, softfloat, *(products[name]["staged_path"] for name in ("ramulator", "extension"))])
        frozen[replay.admission.MODEL_MAP] = descriptor(replay.admission.MODEL_MAP, text.encode())
        variant["retained_dependency_model_payloads"].append(self.put(
            "artifacts/" + variant_id + "/dependency-model/" + replay.admission.MODEL_MAP, text.encode()))
        variant["artifacts_before"] = [frozen[name] for name in sorted(frozen)]
        variant["artifacts_after"] = deepcopy(variant["artifacts_before"])
        body = lambda name: self.files["artifacts/" + variant_id + "/frozen/" + name]
        variant["model_build_records"] = replay.build_records.validate_build_commands(model_text + backend_text,
            body(replay.BACKEND_STAMPS[0]).decode(), body(replay.BACKEND_STAMPS[1]).decode(),
            body(replay.BACKEND_STAMPS[2]).decode(), source=str(source), build=str(build), fmt=fmt,
            compiler=self.tools["g++"]["path"], make=self.tools["make"]["path"], source_files=list(self.sources),
            dependency_map=str(build / replay.admission.MODEL_MAP))
        application_command = self.old_commands[variant_id + "-application"]
        variant["application_build_records"] = replay.application.validate_application_build(
            self.files[application_command["log"]].decode(), body(replay.APP + "/config.stamp").decode(),
            source=source, build=build, tools_root=PurePosixPath(self.report["paths"]["tools"]), tools=self.tools,
            fmt=fmt, compiler_records=variant["compiler_records"],
            source_body=lambda name: self.files["artifacts/source/" + name])
        checked_map = replay.binary.validate_link_map(text, cwd=str(build / "sim/simx"),
            archives={softfloat: self.members}, required_archives=[softfloat],
            required_loads=[products[name]["staged_path"] for name in ("ramulator", "extension")])
        identity = lambda name: dict(frozen[name], path=str(build / name))
        model_link = {"dependency_receipt_sha256": self.receipt_pin, "map": identity(replay.admission.MODEL_MAP),
            "verification": checked_map, "model": identity("sw/runtime/libsimx.so"),
            "objects": [identity(PurePosixPath(name).relative_to(build).as_posix()) for name in objects],
            "products": products, "source_to_model_link_verified": True,
            **dict.fromkeys(replay.manifest.FALSE_CLAIMS, False)}
        variant.update(dependency_receipt_sha256=self.receipt_pin, dependency_model_link=model_link)
        binding = json.loads(self.files[variant["binding"]["path"]])
        binding.update(contract_id=replay.admission.CONTRACT_ID, contract_sha256=replay.admission.contract_hash(),
            source=self.source, loaded_helpers=self.report["loaded_helpers"], artifacts=variant["artifacts_before"],
            dependency_receipt_sha256=self.receipt_pin, dependency_admission=self.admission,
            application_build_records=variant["application_build_records"], dependency_model_link=model_link,
            model_build_records=variant["model_build_records"])
        build_id = replay.qualification_id(binding)
        variant["binding"] = self.put_json(variant["binding"]["path"], binding)
        variant["build_binding_sha256"] = build_id
        prefix_commands = [deepcopy(row) for row in self.old_commands.values()
                           if row["id"].startswith(variant_id + "-") and not row["native_process"]]
        for row in prefix_commands:
            if row["id"] == original_backend["id"]:
                self.commands.extend((model_command, original_backend))
            else:
                self.commands.append(row)
        for planned in self.report["expected_processes"]:
            if planned["format"] != fmt:
                continue
            process_binding = {"contract_id": replay.admission.CONTRACT_ID,
                "contract_sha256": replay.admission.contract_hash(), "build_binding_sha256": build_id,
                "build": binding, "process": planned, "lifetime_contract": replay.lifetime.contract(),
                "preflight_contract_sha256": replay.qualification_id(self.contract), "dependency_receipt_sha256": self.receipt_pin}
            binding_id = replay.qualification_id(process_binding)
            raw = fixture.raw_records(fmt, planned["policy"], binding_id=binding_id)
            raw[3]["loaded_libraries"] = [{"name": name, "path": path}
                for name, path in sorted(variant["expected_loaded_libraries"].items())]
            text = fixture.render_log(*raw[1:])
            observed = replay.records.verify_output(text, contract=self.contract, case=raw[0], fmt=fmt,
                policy=planned["policy"], binding_id=binding_id, sample_id=planned["sample_id"],
                process_id=planned["id"], expected_libraries=variant["expected_loaded_libraries"])
            command = deepcopy(self.old_commands[planned["id"]])
            command["argv"][command["argv"].index("--qualification-id") + 1] = binding_id
            self.log(command, text)
            self.commands.append(command)
            self.report["processes"].append({**planned, "command_id": planned["id"], "log": command["log"],
                "outcome": "pass", "execution_binding_sha256": binding_id, "build_binding_sha256": build_id,
                "binding": self.put_json("snapshots/" + planned["id"] + "-binding.json", process_binding),
                "observation": observed, "process_duration_seconds": command["duration_seconds"],
                "retained_observation": self.put_json("snapshots/" + planned["id"] + "-observation.json", observed)})

    def reader(self):
        return replay._NativeReplay(MemoryView(self.files, self.api), self.api, self.revision,
            dependency_document=deepcopy(self.dependency_document),
            dependency_verification=deepcopy(self.dependency_verification), dependency_body=self.dependency_body,
            dependency_receipt_sha256=self.receipt_pin, source_manifest_sha256=self.source_pin)

    def hosted_files(self):
        """A new synthetic envelope; it does not assert an actual GitHub run."""
        workflow = self.files["artifacts/source/.github/workflows/p06-dependency-provenance.yml"]
        job = {"GITHUB_SHA": self.revision, "GITHUB_REPOSITORY": "baabi-boo/AI-GPU",
            "GITHUB_JOB": "dependency-provenance", "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GITHUB_RUN_ID": "1", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_REF": "refs/heads/synthetic-fixture",
            "schema_version": 1, "contract_id": replay.admission.CONTRACT_ID,
            "scope": "fresh-selected-dependency-lifetime", "record_stage": "job-initialization",
            "requested_xlen": 64, "requested_profile": "p02-tfr", "requested_perf": "on",
            "requested_formats": list(replay.manifest.FORMATS), "requested_policies": list(replay.manifest.POLICIES),
            "requested_processes": 4, "requested_launches": 132, "requested_checked_words": 4224,
            "requested_build_jobs": 2, "requested_simulation_workers": 1,
            "native_execution": "not_run", "native_preflight_passed": False, "native_lifetime_passed": False,
            "fresh_dependency_build_passed": False, "dependency_source_to_loaded_binary_verified": False,
            "workflow_sha256": digest(workflow), "free_disk_bytes_before_cache": 20 * 1024**3,
            "available_memory_bytes_before_cache": 8 * 1024**3,
            **dict.fromkeys(replay.manifest.FALSE_CLAIMS, False)}
        provision = {"python_version": [3, 12, 14], "implementation": "CPython", "platform": "linux",
            "executable": self.tools["executing_python"]["path"], "python3_on_path": self.tools["python3"]["path"]}
        terminal = {"outcome": "pass", "reason": None,
            "report": self.report["paths"]["output"] + "/report.json", "completed_counts": replay.COUNTS,
            "native_preflight_passed": True, "native_lifetime_passed": True,
            "dependency_source_to_loaded_binary_verified": True,
            **dict.fromkeys(replay.manifest.FALSE_CLAIMS, False)}
        files = {"native-lifetime/" + name: body for name, body in self.files.items()}
        files.update({"job.json": json_bytes(job), "workflow.yml": workflow,
            "python-provision.json": json_bytes(provision), "execution.log": json_bytes(terminal),
            "dependency-receipt.json": json_bytes({"path": "dependency-build/report.json", "sha256": self.receipt_pin,
                "size_bytes": len(self.dependency_body), "expected_revision": self.revision}),
            "dependency-preparation.json": self.preparation_body,
            "dependency-build/report.json": self.dependency_body,
            "dependency-build/snapshots/preparation.json": self.preparation_body})
        return files


class CompleteSyntheticNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = SyntheticNativePacket()

    def setUp(self):
        self.packet = deepcopy(self.original)

    def check(self):
        self.packet.finish()
        return self.packet.reader().run()

    def test_complete_native_semantics_are_reconstructed_without_execution(self):
        with mock.patch("subprocess.Popen", side_effect=AssertionError("retained process started")), \
             mock.patch("os.system", side_effect=AssertionError("retained shell executed")), \
             mock.patch("runpy.run_path", side_effect=AssertionError("retained Python executed")):
            result = self.check()
        self.assertEqual(result["counts"], replay.COUNTS)
        self.assertEqual(result["commands_checked"], 37)
        self.assertEqual(len(result["processes"]), 4)
        self.assertEqual(sum(row["lifetime_runs"] for row in result["processes"]), 132)
        self.assertEqual(sum(row["checked_words"] for row in result["processes"]), 4224)
        self.assertTrue(all(row["command_count"] == 30 for row in result["application_builds"].values()))
        self.assertTrue(all(len(row["objects"]) == 43 for row in result["dependency_model_links"].values()))
        self.assertEqual(result["native_execution"], "not_run")
        self.assertFalse(result["retained_code_executed"])
        for name in replay.manifest.FALSE_CLAIMS:
            self.assertIs(result[name], False)

    def test_reports_cannot_omit_failures_claims_or_late_stability(self):
        changes = [("native_execution", "not_run"), ("native_lifetime_passed", False),
            ("dependency_source_to_loaded_binary_verified", False), ("failures", [{"reason": "first failed attempt"}]),
            ("qualified", True), ("source_stable", False), ("dependencies_stable", False),
            ("retained_files_stable", False), ("completed_counts", {**replay.COUNTS, "launches": 131})]
        for name, value in changes:
            with self.subTest(name=name):
                self.packet = deepcopy(self.original)
                self.packet.report[name] = value
                with self.assertRaises(ValueError):
                    self.check()
        self.packet = deepcopy(self.original)
        self.packet.report["stability_checks"].pop()
        with self.assertRaisesRegex(ValueError, "stability"):
            self.check()

    def test_native_source_digest_is_external_even_if_internal_descriptors_are_repaired(self):
        name = "ci/project/p06_dependency_lifetime_execute.py"
        data = self.packet.files["artifacts/source/" + name] + b"# substituted retained helper\n"
        self.packet.put("artifacts/source/" + name, data)
        for row in self.packet.source["files"]:
            if row["path"] == name:
                row.update(descriptor(name, data))
        for which in ("before", "after"):
            self.packet.report["source_" + which] = self.packet.put_json(
                "snapshots/source-" + which + ".json", self.packet.source)
        with self.assertRaisesRegex(ValueError, "externally pinned native source"):
            self.check()

    def test_omitted_or_duplicate_processes_and_commands_reject(self):
        for key in ("processes", "commands", "variants"):
            for duplicate in (False, True):
                with self.subTest(key=key, duplicate=duplicate):
                    self.packet = deepcopy(self.original)
                    if duplicate:
                        self.packet.report[key][1] = deepcopy(self.packet.report[key][0])
                    else:
                        self.packet.report[key].pop()
                    with self.assertRaises(ValueError):
                        self.check()

    def test_original_application_lines_are_required_even_when_host_link_is_present(self):
        command = next(row for row in self.packet.report["commands"] if row["id"] == "simx-fp16-application")
        text = self.packet.files[command["log"]].decode()
        self.packet.log(command, text.splitlines()[-1] + "\n")
        with self.assertRaisesRegex(ValueError, "missing or extra"):
            self.check()

    def test_all_model_objects_map_and_binary_are_required(self):
        for name in ("retained_dependency_model_payloads", "dependency_model_link"):
            with self.subTest(name=name):
                self.packet = deepcopy(self.original)
                variant = self.packet.report["variants"][0]
                if name == "retained_dependency_model_payloads":
                    variant[name].pop(0)
                else:
                    variant[name]["objects"].pop(0)
                with self.assertRaises(ValueError):
                    self.check()
        self.packet = deepcopy(self.original)
        row = self.packet.report["variants"][0]["retained_dependency_model_payloads"][0]
        self.packet.files[row["path"]] += b"substitution"
        with self.assertRaises(ValueError):
            self.check()

    def test_substituted_model_map_and_duplicate_load_fail_after_rehash(self):
        for mutate in (lambda text: text.replace(".a(", ".a(unadmitted-", 1),
                       lambda text: text + next(line for line in text.splitlines() if line.startswith("LOAD ")) + "\n"):
            with self.subTest(mutate=mutate):
                self.packet = deepcopy(self.original)
                variant = self.packet.report["variants"][0]
                row = variant["retained_dependency_model_payloads"][-1]
                data = mutate(self.packet.files[row["path"]].decode()).encode()
                row.update(self.packet.put(row["path"], data))
                for key in ("artifacts_before", "artifacts_after"):
                    for item in variant[key]:
                        if item["path"] == replay.admission.MODEL_MAP:
                            item.update(descriptor(item["path"], data))
                with self.assertRaises(ValueError):
                    self.check()

    def test_rehashed_model_map_cannot_add_source_or_work_inputs(self):
        # Exercise the real native model boundary with repaired map identities
        # and map-result metadata. A final binding mismatch must not be the only
        # reason an unplanned project library/archive/object is rejected.
        paths = self.original.report["paths"]
        extra_loads = (
            paths["work"] + "/simx-fp16/sw/runtime/unplanned.so",
            paths["work"] + "/simx-fp16/sw/runtime/unplanned.a",
            paths["work"] + "/simx-bf16/sw/runtime/obj/unplanned.o",
            paths["source"] + "/third_party/unplanned.so",
        )
        for extra in extra_loads:
            with self.subTest(extra=extra):
                self.packet = deepcopy(self.original)
                variant = self.packet.report["variants"][0]
                relative = replay.admission.MODEL_MAP
                payload = next(row for row in variant["retained_dependency_model_payloads"]
                               if row["path"].endswith("/" + relative))
                data = self.packet.files[payload["path"]] + ("LOAD " + extra + "\n").encode()
                self.packet.report["retained_payload_bytes"] += len(data) - payload["size_bytes"]
                payload.update(self.packet.put(payload["path"], data))
                for name in ("artifacts_before", "artifacts_after"):
                    row = next(row for row in variant[name] if row["path"] == relative)
                    row.update(descriptor(relative, data))
                model = variant["dependency_model_link"]
                model["map"] = descriptor(variant["build_dir"] + "/" + relative, data)
                products = self.packet.dependency_document["products"]
                softfloat = products["softfloat"]["staged_path"]
                model["verification"] = replay.binary.validate_link_map(data.decode(),
                    cwd=variant["build_dir"] + "/sim/simx", archives={softfloat: self.packet.members},
                    required_archives=[softfloat],
                    required_loads=[products[name]["staged_path"] for name in ("ramulator", "extension")])
                self.packet.finish()
                checked = self.packet.reader()
                checked.budget()
                checked.provenance()
                checked.paths_and_tools()
                checked.variant = checked.report["variants"][0]
                checked.fmt, checked.variant_id = "fp16", "simx-fp16"
                checked.build = checked.paths["work"] / checked.variant_id
                checked.generated()
                checked.command_index = 7  # The seven independent tool-version receipts precede this build.
                with self.assertRaisesRegex(ValueError, "unplanned source/work input"):
                    checked.compiler_commands()

    def test_lifetime_replay_rejects_pending_reads_loader_substitution_and_missing_records(self):
        changes = (
            lambda rows: rows[4]["runs"][1]["after"].update(pending_reads=1),
            lambda rows: rows[3]["loaded_libraries"][0].update(path="/foreign/libramulator-vortex.so"),
            lambda rows: rows[4]["runs"].pop(),
        )
        for change in changes:
            with self.subTest(change=change):
                self.packet = deepcopy(self.original)
                process = self.packet.report["processes"][0]
                raw = fixture.raw_records(process["format"], process["policy"],
                    binding_id=process["execution_binding_sha256"])
                variant = self.packet.report["variants"][0]
                raw[3]["loaded_libraries"] = [{"name": name, "path": path}
                    for name, path in sorted(variant["expected_loaded_libraries"].items())]
                change(raw)
                command = next(row for row in self.packet.report["commands"] if row["id"] == process["id"])
                self.packet.log(command, fixture.render_log(*raw[1:]))
                with self.assertRaises(ValueError):
                    self.check()

    def test_unlisted_native_file_and_changed_dependency_admission_are_rejected(self):
        self.packet.put("artifacts/unbound.py", b"raise AssertionError('must never execute')\n")
        with self.assertRaisesRegex(ValueError, "retained inventory"):
            self.check()
        self.packet = deepcopy(self.original)
        self.packet.report["dependency_admission_after"]["source_inputs_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            self.check()

    def test_hosted_zip_bridge_replays_native_semantics_with_synthetic_dependency_boundary(self):
        # Only the independently tested fresh-dependency semantic boundary is
        # replaced. All native records, archive transport and hosted joins run.
        with tempfile.TemporaryDirectory(prefix="p06-native-hosted-") as directory:
            path = Path(directory) / "synthetic-original.zip"
            files = self.packet.hosted_files()
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for name, body in files.items():
                    archive.writestr(name, body)

            def dependency_boundary(view, *, expected_revision, expected_receipt_sha256):
                self.assertEqual(list(view.files()), ["report.json", "snapshots/preparation.json"])
                self.assertEqual(expected_revision, self.packet.revision)
                self.assertEqual(expected_receipt_sha256, digest(view.read("report.json")))
                return {"dependency_report": view.identity("report.json"),
                    "retained_dependency_verification": self.packet.dependency_verification,
                    "packet_files_checked": 2, "packet_bytes_checked": sum(len(view.read(name)) for name in view.files())}

            original_open, original_resolve = Path.open, Path.resolve

            def inert_open(path, *args, **kwargs):
                if str(path).startswith("/home/runner/"):
                    raise AssertionError("a producer path was opened")
                return original_open(path, *args, **kwargs)

            def inert_resolve(path, *args, **kwargs):
                if str(path).startswith("/home/runner/"):
                    raise AssertionError("a producer path was resolved")
                return original_resolve(path, *args, **kwargs)

            args = {"expected_revision": self.packet.revision, "expected_receipt_sha256": self.packet.receipt_pin,
                "expected_native_report_sha256": digest(self.packet.files["report.json"]),
                "expected_source_manifest_sha256": self.packet.source_pin}
            original_verify_view, contexts = replay.verify_view, []

            def capture_context(*args, **kwargs):
                result, context = original_verify_view(*args, **kwargs)
                contexts.append(context)
                return result, context

            with mock.patch.object(replay.dependency_replay, "verify_view", side_effect=dependency_boundary) as dependency, \
                 mock.patch.object(replay, "verify_view", side_effect=capture_context), \
                 mock.patch("subprocess.Popen", side_effect=AssertionError("retained process started")), \
                 mock.patch.object(zipfile.ZipFile, "extract", side_effect=AssertionError("archive extracted")), \
                 mock.patch.object(zipfile.ZipFile, "extractall", side_effect=AssertionError("archive extracted")), \
                 mock.patch.object(Path, "open", new=inert_open), mock.patch.object(Path, "resolve", new=inert_resolve):
                result = replay.replay_archive(path, digest(path.read_bytes()), **args)
            dependency.assert_called_once()
            self.assertEqual(len(contexts), 1)
            self.assertEqual(contexts[0].report, self.packet.report)
            self.assertEqual(contexts[0].tools, self.packet.tools)
            self.assertEqual(set(contexts[0].bindings), {"simx-fp16", "simx-bf16"})
            self.assertEqual(set(contexts[0].model_links), {"simx-fp16", "simx-bf16"})
            self.assertEqual(result["hosted_identity"]["validation"], "pass")
            self.assertFalse(result["hosted_identity"]["origin_authenticated"])
            self.assertTrue(result["dependency_verification"]["retained_dependency_verification"]["synthetic_dependency_metadata"])
            self.assertEqual(result["counts"], replay.COUNTS)
            self.assertEqual(result["native_execution"], "not_run")
            # Without the explicitly named synthetic boundary this fabricated
            # dependency document must fail the actual full receipt reader.
            with self.assertRaisesRegex(ValueError, "dependency retained inventory"):
                replay.replay_archive(path, digest(path.read_bytes()), **args)

    def test_hosted_envelope_joins_fail_on_wrong_workflow_interpreter_or_terminal_result(self):
        checked = self.packet.reader()
        checked.run()
        outer = self.packet.hosted_files()
        dep = MemoryView({"snapshots/preparation.json": self.packet.preparation_body}, self.packet.api)
        for name, changed in (("workflow.yml", b"different workflow\n"),
                ("python-provision.json", json_bytes({"python_version": [3, 12, 13], "implementation": "CPython",
                    "platform": "linux", "executable": self.packet.tools["executing_python"]["path"],
                    "python3_on_path": self.packet.tools["python3"]["path"]})),
                ("execution.log", b'{"outcome":"fail"}\n')):
            with self.subTest(name=name), self.assertRaises(ValueError):
                replay._hosted_identity(checked, MemoryView(dict(outer, **{name: changed}), self.packet.api), dep)


class NativeExternalIntakeTests(unittest.TestCase):
    def test_all_external_pins_are_required_before_opening_the_archive(self):
        args = {"sha256": "e" * 64, "expected_revision": "a" * 40, "expected_receipt_sha256": "b" * 64,
                "expected_native_report_sha256": "c" * 64, "expected_source_manifest_sha256": "d" * 64}
        for name in args:
            for invalid in (None, True, "master", "A" * 64):
                changed = dict(args, **{name: invalid})
                with self.subTest(name=name, invalid=invalid), \
                     mock.patch.object(replay.dependency_replay, "_archive_api") as api, self.assertRaises(ValueError):
                    replay.replay_archive("/never-open-original.zip", **changed)
                api.assert_not_called()

    def test_shared_view_api_requires_pins_before_reading_either_view(self):
        args = {"expected_revision": "a" * 40, "expected_receipt_sha256": "b" * 64,
                "expected_native_report_sha256": "c" * 64, "expected_source_manifest_sha256": "d" * 64}
        for name in args:
            native, dependency = mock.Mock(), mock.Mock()
            with self.subTest(name=name), self.assertRaises(ValueError):
                replay.verify_view(native, dependency, mock.Mock(), **dict(args, **{name: None}))
            native.read.assert_not_called()
            dependency.read.assert_not_called()

    def test_native_report_digest_rejects_before_dependency_semantics(self):
        with tempfile.TemporaryDirectory(prefix="p06-native-replay-intake-") as directory:
            path = Path(directory) / "synthetic.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("native-lifetime/report.json", b"{}\n")
                archive.writestr("dependency-build/report.json", b"{}\n")
            with mock.patch.object(replay.dependency_replay, "verify_view") as dependency, \
                 self.assertRaisesRegex(ValueError, "externally pinned native report"):
                replay.replay_archive(path, digest(path.read_bytes()), expected_revision="a" * 40,
                    expected_receipt_sha256="b" * 64, expected_native_report_sha256="c" * 64,
                    expected_source_manifest_sha256="d" * 64)
            dependency.assert_not_called()

    def test_new_native_contract_cannot_accept_the_historical_original(self):
        with zipfile.ZipFile(HISTORICAL) as archive:
            data = json.loads(archive.read("native-lifetime/report.json"))
        self.assertNotEqual(set(data), replay.REPORT_FIELDS)
        with self.assertRaisesRegex(ValueError, "missing or unknown fields"):
            replay._fields(data, replay.REPORT_FIELDS, "new native report")


if __name__ == "__main__":
    unittest.main()
