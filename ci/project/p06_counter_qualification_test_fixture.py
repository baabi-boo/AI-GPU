# SPDX-License-Identifier: Apache-2.0
"""Synthetic qualification grammar, never evidence of native execution."""

from copy import deepcopy
import json
from pathlib import Path

import p06_counter_qualification_replay as replay
import p06_native_lifetime_test_fixture as lifetime_fixture
from p06_counter_qualification_historical_fixture import source_body
from test_p06_dependency_native_replay import (
    MemoryView, SyntheticNativePacket, descriptor, digest, json_bytes,
)


DIAGNOSTIC_PATH = Path("/explicit-inputs/diagnostics.zip")
CONTROL_PATH = Path("/explicit-inputs/separate-controls.zip")


def prerequisite_summaries(proof):
    common = {"schema_version": 1, "contract_id": replay.prerequisites.CONTRACT_ID,
        "outcome": "pass", "native_execution": "not_run", "retained_code_executed": False,
        **dict.fromkeys(replay.contract.FALSE_CLAIMS, False)}
    diagnostics = {**common, "scope": "pinned-diagnostic-prerequisites-only",
        "diagnostic_prerequisites_consistent": True,
        "archive": deepcopy(proof["diagnostics"]["archive"]),
        "source_revision": proof["diagnostics"]["source_revision"],
        "public_source_inventory_sha256": proof["diagnostics"]["public_source_inventory"]["sha256"]}
    controls = {**common, "scope": "pinned-separate-control-prerequisites-only",
        "control_prerequisites_consistent": True,
        "archive": deepcopy(proof["controls"]["archive"]),
        "source_revision": proof["controls"]["source_revision"],
        "projected_measurement_sources": len(proof["measurement_sources"]),
        "measurement_projection_sha256": replay.contract.digest(proof["measurement_sources"]),
        "managed_population_included": False,
        "positive_pending_contexts": [{"gp": 7}, {"gp": -1}]}
    return diagnostics, controls


class SyntheticQualificationPacket(SyntheticNativePacket):
    """All native semantics are real; prerequisite/dependency API seams are synthetic."""

    def __init__(self):
        super().__init__()
        self.proof_body = (replay.ROOT / replay.contract.SOURCE_PROOF_PATH).read_bytes()
        self.proof = replay.contract.validate_proof(self.proof_body)
        required = (set(replay.RUNNER_HELPERS) | set(replay.ADMISSION_HELPERS)
            | set(replay.contract.SOURCE_FILES)
            | {row["path"] for row in self.proof["measurement_sources"]})
        names = set(self.sources) | required
        for name in required:
            self.put("artifacts/source/" + name, source_body(name))
        self.source["files"] = [descriptor(name, self.files["artifacts/source/" + name])
                                for name in sorted(names)]
        self.sources = {row["path"]: row for row in self.source["files"]}
        self.report["retained_sources"] = [dict(row, path="artifacts/source/" + row["path"])
                                            for row in self.source["files"]]
        self.report["loaded_helpers"] = [self.sources[name] for name in replay.RUNNER_HELPERS]
        for which in ("before", "after"):
            self.report["source_" + which] = self.put_json("snapshots/source-" + which + ".json", self.source)
        self.source_pin = self.report["source_before"]["sha256"]
        self.dependency_document["contract_id"] = replay.native.dependency_contract.CONTRACT_ID
        self.dependency_document["expected_revision"] = self.revision
        self.dependency_document["helper_sources"] = [self.sources[name] for name in replay.native.RUNNER_HELPERS]
        component = next(row for row in self.dependency_document["source_manifest"]["sources"]
                         if row["name"] == "ramulator")
        component.update(revision=self.proof["dependency_revision"],
                         tree=replay.native.dependency_contract.PINS["ramulator"]["tree"])
        frozen = {row["path"]: row for row in self.proof["dependency_sources"]}
        component_files = {row["path"]: row for row in component["files"]}
        for name, row in frozen.items():
            component_files[name] = {key: row[key] for key in ("path", "sha256", "size_bytes")}
            component_files[name]["oid"] = row["git_blob"]
        component["files"] = [component_files[name] for name in sorted(component_files)]
        self.dependency_body = json_bytes(self.dependency_document)
        self.receipt_pin = digest(self.dependency_body)
        self.admission, self.stability = replay.native._admission_values(
            self.dependency_document, self.dependency_verification, self.receipt_pin)
        self.diagnostics, self.controls = prerequisite_summaries(self.proof)
        source_projection = replay.contract.verify_source_projection(self.proof, self.source["files"])
        dependency_projection = replay.prerequisites.verify_dependency_projection(self.proof, self.dependency_document)
        self.counter_admission = replay.admission.admission_summary(self.proof, source_projection,
            dependency_projection, self.diagnostics, self.controls)
        self.counter_stability = replay.admission.stability_summary(self.proof,
            [self.sources[name] for name in replay.ADMISSION_HELPERS],
            [self.proof["diagnostics"]["public_source_inventory"]])
        self.report.update(contract_id=replay.admission.CONTRACT_ID, scope=replay.admission.SCOPE,
            contract_sha256=replay.admission.contract_hash(), dependency_receipt_sha256=self.receipt_pin,
            dependency_admission=self.admission, dependency_admission_before=self.stability,
            dependency_admission_after=self.stability,
            counter_qualification_sha256=replay.contract.SOURCE_PROOF_SHA256,
            counter_qualification_admission=self.counter_admission,
            counter_qualification_admission_before=self.counter_stability,
            counter_qualification_admission_after=self.counter_stability,
            counter_qualification_passed=True,
            limitations=[*replay.admission.LIMITATIONS, *replay.native.producer.base.PROCESS_LIMITATIONS])
        self.report["contract_snapshot"] = self.put_json("snapshots/contract.json", replay.admission.contract())
        self.report["retained_dependency_receipt"] = self.put("artifacts/dependency-receipt/report.json", self.dependency_body)
        self.report["retained_counter_qualification"] = self.put(replay.PROOF_MEMBER, self.proof_body)
        commands = {row["id"]: row for row in self.report["commands"]}
        for variant in self.report["variants"]:
            variant["dependency_receipt_sha256"] = self.receipt_pin
            variant["dependency_model_link"]["dependency_receipt_sha256"] = self.receipt_pin
            binding = json.loads(self.files[variant["binding"]["path"]])
            binding.update(contract_id=replay.admission.CONTRACT_ID,
                contract_sha256=replay.admission.contract_hash(), source=self.source,
                loaded_helpers=self.report["loaded_helpers"], dependency_receipt_sha256=self.receipt_pin,
                dependency_admission=self.admission, dependency_model_link=variant["dependency_model_link"],
                counter_qualification_sha256=replay.contract.SOURCE_PROOF_SHA256,
                counter_qualification_admission=self.counter_admission)
            build_id = replay.native.qualification_id(binding)
            variant["binding"] = self.put_json(variant["binding"]["path"], binding)
            variant["build_binding_sha256"] = build_id
            for row in self.report["processes"]:
                if row["format"] != variant["format"]:
                    continue
                process = json.loads(self.files[row["binding"]["path"]])
                process.update(contract_id=replay.admission.CONTRACT_ID,
                    contract_sha256=replay.admission.contract_hash(), build_binding_sha256=build_id,
                    build=binding, dependency_receipt_sha256=self.receipt_pin,
                    counter_qualification_sha256=replay.contract.SOURCE_PROOF_SHA256)
                binding_id = replay.native.qualification_id(process)
                row.update(execution_binding_sha256=binding_id, build_binding_sha256=build_id,
                    binding=self.put_json(row["binding"]["path"], process))
                raw = lifetime_fixture.raw_records(row["format"], row["policy"], binding_id=binding_id)
                raw[3]["loaded_libraries"] = [{"name": name, "path": path}
                    for name, path in sorted(variant["expected_loaded_libraries"].items())]
                text = lifetime_fixture.render_log(*raw[1:])
                observed = replay.native.records.verify_output(text, contract=self.contract, case=raw[0],
                    fmt=row["format"], policy=row["policy"], binding_id=binding_id,
                    sample_id=row["sample_id"], process_id=row["id"],
                    expected_libraries=variant["expected_loaded_libraries"])
                row["observation"] = observed
                row["retained_observation"] = self.put_json(row["retained_observation"]["path"], observed)
                command = commands[row["id"]]
                command["argv"][command["argv"].index("--qualification-id") + 1] = binding_id
                self.log(command, text)
        self.report["raw_logs"] = [descriptor(row["log"], self.files[row["log"]])
                                   for row in self.report["commands"]]
        for row in self.report["stability_checks"]:
            row.update(source_sha256=replay.native.qualification_id(self.source),
                dependency_admission=self.stability, counter_qualification_admission=self.counter_stability)
        self.finish()

    def arguments(self):
        return {"expected_revision": self.revision, "expected_receipt_sha256": self.receipt_pin,
            "expected_native_report_sha256": digest(self.files["report.json"]),
            "expected_source_manifest_sha256": self.source_pin,
            "expected_qualification_sha256": replay.contract.SOURCE_PROOF_SHA256,
            "diagnostic_archive": DIAGNOSTIC_PATH,
            "diagnostic_sha256": self.proof["diagnostics"]["archive"]["sha256"],
            "control_archive": CONTROL_PATH, "control_sha256": self.proof["controls"]["archive"]["sha256"]}

    def reader(self):
        self.finish()
        args = self.arguments()
        return replay._QualifiedReplay(MemoryView(self.files, self.api), self.api, self.revision,
            dependency_document=deepcopy(self.dependency_document),
            dependency_verification=deepcopy(self.dependency_verification), dependency_body=self.dependency_body,
            dependency_receipt_sha256=self.receipt_pin, source_manifest_sha256=self.source_pin,
            **{name: args[name] for name in ("expected_qualification_sha256", "diagnostic_archive",
                "diagnostic_sha256", "control_archive", "control_sha256")})

    def local_files(self, prefix=""):
        stem = prefix + "/" if prefix else ""
        files = {stem + "native-qualification/" + name: body for name, body in self.files.items()}
        files.update({stem + "dependency-build/report.json": self.dependency_body,
            stem + "dependency-build/snapshots/preparation.json": self.preparation_body})
        return files
