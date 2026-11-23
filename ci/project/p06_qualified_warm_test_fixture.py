# SPDX-License-Identifier: Apache-2.0
"""Invented complete warm packets; no native or dependency execution evidence."""

from copy import deepcopy
import json

import p06_qualified_warm_replay as replay
from p06_counter_qualification_test_fixture import (
    CONTROL_PATH, DIAGNOSTIC_PATH, SyntheticQualificationPacket,
)
from test_p06_dependency_native_replay import MemoryView, descriptor, digest
from test_p06_qualified_warm_records import raw_records, render_log


class SyntheticQualifiedWarmPacket(SyntheticQualificationPacket):
    """Real complete native grammar with explicit synthetic prerequisite seams."""

    def __init__(self):
        super().__init__()
        self.original_proof = self.proof
        self.proof_body = (replay.ROOT / replay.contract.SOURCE_PROOF_PATH).read_bytes()
        self.proof = replay.contract.validate_proof(self.proof_body)
        required = (set(replay.RUNNER_HELPERS) | set(replay.ADMISSION_HELPERS)
            | set(replay.contract.SOURCE_FILES)
            | {row["path"] for row in self.proof["measurement_sources"]})
        names = set(self.sources) | required
        for name in required:
            self.put("artifacts/source/" + name, (replay.ROOT / name).read_bytes())
        self.source["files"] = [descriptor(name, self.files["artifacts/source/" + name])
                                for name in sorted(names)]
        self.sources = {row["path"]: row for row in self.source["files"]}
        self.report["retained_sources"] = [dict(row, path="artifacts/source/" + row["path"])
                                            for row in self.source["files"]]
        self.report["loaded_helpers"] = [self.sources[name] for name in replay.RUNNER_HELPERS]
        for which in ("before", "after"):
            self.report["source_" + which] = self.put_json("snapshots/source-" + which + ".json", self.source)
        self.source_pin = self.report["source_before"]["sha256"]
        source_projection = replay.contract.verify_source_projection(self.proof, self.source["files"])
        dependency_projection = replay.prerequisites.verify_dependency_projection(
            self.original_proof, self.dependency_document)
        self.counter_admission = replay.admission.admission_summary(self.proof, source_projection,
            dependency_projection, self.diagnostics, self.controls)
        self.counter_stability = replay.admission.stability_summary(self.proof,
            [self.sources[name] for name in replay.ADMISSION_HELPERS],
            replay.admission.prerequisite_input_rows(self.proof))
        self.plan = replay.contract.process_plan()
        self.report.update(contract_id=replay.admission.CONTRACT_ID, scope=replay.admission.SCOPE,
            contract_sha256=replay.admission.contract_hash(),
            counter_qualification_sha256=replay.contract.SOURCE_PROOF_SHA256,
            counter_qualification_admission=self.counter_admission,
            counter_qualification_admission_before=self.counter_stability,
            counter_qualification_admission_after=self.counter_stability,
            counter_qualification_passed=True, qualified_warm_passed=True,
            expected_counts=deepcopy(replay.contract.COMPLETE_COUNTS),
            completed_counts=deepcopy(replay.contract.COMPLETE_COUNTS),
            expected_processes=self.plan,
            limitations=[*replay.admission.LIMITATIONS, *replay.native.producer.base.PROCESS_LIMITATIONS])
        self.report["contract_snapshot"] = self.put_json("snapshots/contract.json", replay.admission.contract())
        self.report["retained_counter_qualification"] = self.put(replay.PROOF_MEMBER, self.proof_body)
        original_commands = deepcopy(self.report["commands"])
        original_processes = deepcopy(self.report["processes"])
        templates = {(row["format"], row["policy"]): row for row in original_processes}
        commands = {row["id"]: row for row in original_commands}
        for row in original_processes:
            for path in (row["binding"]["path"], row["retained_observation"]["path"], row["log"]):
                del self.files[path]
        self.report["processes"] = []
        self.report["commands"] = [row for row in original_commands if row["id"].startswith("version-")]
        for variant in self.report["variants"]:
            fmt = variant["format"]
            selected = [row for row in self.plan if row["format"] == fmt]
            variant["process_ids"] = [row["id"] for row in selected]
            binding = json.loads(self.files[variant["binding"]["path"]])
            binding.update(contract_id=replay.admission.CONTRACT_ID,
                contract_sha256=replay.admission.contract_hash(), source=self.source,
                loaded_helpers=self.report["loaded_helpers"],
                counter_qualification_sha256=replay.contract.SOURCE_PROOF_SHA256,
                counter_qualification_admission=self.counter_admission,
                warm_sampling=replay.contract.sampling_binding())
            build_id = replay.native.qualification_id(binding)
            variant["binding"] = self.put_json(variant["binding"]["path"], binding)
            variant["build_binding_sha256"] = build_id
            self.report["commands"].extend(row for row in original_commands
                if row["id"].startswith(variant["id"] + "-") and not row["native_process"])
            for planned in selected:
                template = templates[fmt, planned["policy"]]
                process_binding = {"contract_id": replay.admission.CONTRACT_ID,
                    "contract_sha256": replay.admission.contract_hash(), "build_binding_sha256": build_id,
                    "build": binding, "process": planned, "lifetime_contract": replay.native.lifetime.contract(),
                    "preflight_contract_sha256": replay.native.qualification_id(self.contract),
                    "dependency_receipt_sha256": self.receipt_pin,
                    "counter_qualification_sha256": replay.contract.SOURCE_PROOF_SHA256,
                    "warm_sampling": replay.contract.sampling_binding()}
                binding_id = replay.native.qualification_id(process_binding)
                raw = raw_records(fmt, planned["policy"], pair_index=planned["pair_index"],
                                  binding_id=binding_id, contract=self.contract)
                raw[3]["loaded_libraries"] = [{"name": name, "path": path}
                    for name, path in sorted(variant["expected_loaded_libraries"].items())]
                text = render_log(*raw[1:])
                observed = replay.records.verify_output(text, contract=self.contract, case=raw[0], fmt=fmt,
                    policy=planned["policy"], binding_id=binding_id, sample_id=planned["sample_id"],
                    process_id=planned["id"], expected_libraries=variant["expected_loaded_libraries"],
                    pair_index=planned["pair_index"], phase=planned["phase"])
                command = deepcopy(commands[template["command_id"]])
                command.update(id=planned["id"], log="logs/" + planned["id"] + ".log")
                command["argv"].insert(2, "--qualified-warm")
                for option, value in (("--qualification-id", binding_id),
                        ("--sample-id", planned["sample_id"]), ("--pair-index", str(planned["pair_index"])),
                        ("--phase", planned["phase"])):
                    command["argv"][command["argv"].index(option) + 1] = value
                self.log(command, text)
                self.report["commands"].append(command)
                self.report["processes"].append({**planned, "command_id": planned["id"], "log": command["log"],
                    "outcome": "pass", "execution_binding_sha256": binding_id, "build_binding_sha256": build_id,
                    "binding": self.put_json("snapshots/" + planned["id"] + "-binding.json", process_binding),
                    "observation": observed, "process_duration_seconds": command["duration_seconds"],
                    "retained_observation": self.put_json("snapshots/" + planned["id"] + "-observation.json", observed)})
        self.report["raw_logs"] = [descriptor(row["log"], self.files[row["log"]])
                                   for row in self.report["commands"]]
        last_by_format = {fmt: [row for row in self.plan if row["format"] == fmt][-1]["id"]
                          for fmt in replay.native.manifest.FORMATS}
        labels = []
        for command in self.report["commands"]:
            labels.extend(("before-command-" + command["id"], "after-command-" + command["id"]))
            if command["native_process"]:
                labels.append("after-process-" + command["id"])
                for fmt, last_id in last_by_format.items():
                    if command["id"] == last_id:
                        labels.append("after-variant-simx-" + fmt)
        dependency_identity = replay.native.qualification_id(json.loads(
            self.files[self.report["dependencies_before"]["path"]]))
        self.report["stability_checks"] = [{"at": self.report["started_at"], "label": label,
            "source_sha256": replay.native.qualification_id(self.source),
            "tools_sha256": replay.native.qualification_id(self.tools),
            "dependencies_sha256": dependency_identity, "dependency_admission": self.stability,
            "counter_qualification_admission": self.counter_stability} for label in labels]
        self.finish()

    def arguments(self):
        return {"expected_revision": self.revision, "expected_receipt_sha256": self.receipt_pin,
            "expected_native_report_sha256": digest(self.files["report.json"]),
            "expected_source_manifest_sha256": self.source_pin,
            "expected_qualification_sha256": replay.contract.SOURCE_PROOF_SHA256,
            "diagnostic_archive": DIAGNOSTIC_PATH,
            "diagnostic_sha256": self.original_proof["diagnostics"]["archive"]["sha256"],
            "control_archive": CONTROL_PATH,
            "control_sha256": self.original_proof["controls"]["archive"]["sha256"]}

    def reader(self):
        self.finish()
        args = self.arguments()
        return replay._QualifiedWarmReplay(MemoryView(self.files, self.api), self.api, self.revision,
            dependency_document=deepcopy(self.dependency_document),
            dependency_verification=deepcopy(self.dependency_verification), dependency_body=self.dependency_body,
            dependency_receipt_sha256=self.receipt_pin, source_manifest_sha256=self.source_pin,
            **{name: args[name] for name in ("expected_qualification_sha256", "diagnostic_archive",
                "diagnostic_sha256", "control_archive", "control_sha256")})

    def local_files(self, prefix=""):
        stem = prefix + "/" if prefix else ""
        files = {stem + "qualified-warm/" + name: body for name, body in self.files.items()}
        files.update({stem + "dependency-build/report.json": self.dependency_body,
            stem + "dependency-build/snapshots/preparation.json": self.preparation_body})
        return files

    def replace_log(self, process_index, text):
        process = self.report["processes"][process_index]
        command = next(row for row in self.report["commands"] if row["id"] == process["command_id"])
        self.log(command, text)
        self.report["raw_logs"] = [descriptor(row["log"], self.files[row["log"]])
                                   for row in self.report["commands"]]
        self.finish()
