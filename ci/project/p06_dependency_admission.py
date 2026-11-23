# SPDX-License-Identifier: Apache-2.0
"""Admit fresh dependency evidence before the managed lifetime build and run."""

from collections import Counter
import hashlib
import os
from pathlib import Path
import re
import stat

from baseline_inventory import _digest, hash_artifacts
import p02_matrix as base
from p02_matrix_records import require
import p06_dependency_binary as binary
import p06_dependency_contract as dependency_contract
import p06_dependency_receipt as receipt
import p06_managed_preflight_application_build as application
import p06_managed_preflight_build as model
import p06_native_lifetime_contract as lifetime


CONTRACT_ID = dependency_contract.MANAGED_CONTRACT_ID
SCOPE = "seed-free-managed-dependency-lifetime"
MODEL_MAP = "sw/runtime/dependency-model.map"
MODEL_MAKEFILE = "tests/regression/ai_counter_preflight/dependency_model.mk"
SOURCE_FILES = (
    ".github/workflows/p06-dependency-provenance.yml",
    "ci/project/p06_dependency_admission.py",
    "ci/project/p06_dependency_lifetime_execute.py",
    "ci/project/p06_dependency_build.py",
    "ci/project/p06_dependency_prepare.py",
    "docs/designs/dependency_provenance_v1.md",
    MODEL_MAKEFILE,
)
LIMITATIONS = [
    "The new outer admission binds the fixed dependency source/build/staging graph and complete application build to the unchanged lifetime-v1 witness.",
    "Dependency source-to-loaded-binary verification requires both formats, both allocation policies, the exact selected linker inputs and every final stability check.",
    "All seven qualification, warm-readiness, warm-execution and acceptance claims remain false; complete counter qualification is a separate obligation.",
    "System headers, compiler support files and loaded system libraries outside the explicitly recorded graph are not a complete host-toolchain provenance claim.",
    "A consistent receipt does not authenticate an untrusted producer or defeat malicious concurrent filesystem writers.",
]


def contract():
    return {
        "schema_version": 1, "contract_id": CONTRACT_ID, "scope": SCOPE,
        "dependency_contract": dependency_contract.contract(),
        "lifetime_contract": lifetime.contract(),
        "application_contract_id": application.CONTRACT_ID,
        "model_map": MODEL_MAP, "model_makefile": MODEL_MAKEFILE,
        "model_translation_units": len(model.MODEL_SOURCES),
        "complete_counts": dict(lifetime.COMPLETE_COUNTS),
        "source_files": list(SOURCE_FILES),
        "false_claims": list(dependency_contract.FALSE_CLAIMS),
        "limitations": list(LIMITATIONS),
    }


def contract_hash():
    return dependency_contract.digest(contract())


def _live_identity(path):
    path = Path(os.path.abspath(path))
    require(re.fullmatch(r"/[A-Za-z0-9_./+()\-]+", str(path))
            and path.resolve(strict=True) == path
            and all(not parent.is_symlink() for parent in (path, *path.parents)),
            "dependency data paths must be safe absolute literals without symlink traversal")
    status = path.stat()
    require(stat.S_ISREG(status.st_mode) and status.st_nlink == 1
            and 0 <= status.st_size <= dependency_contract.MAX_FILE_BYTES,
            "dependency input is not a bounded, unlinked regular file: " + str(path))
    digest, size = _digest(path)
    return {"path": str(path), "sha256": digest, "size_bytes": size}


class Admission:
    def __init__(self, path, expected_sha256, *, source, expected_revision):
        self.path = base._path(path, existing=True)
        self.source = base._path(source, existing=True)
        self.document, self.verification = receipt.load_receipt(
            self.path, expected_sha256, expected_revision)
        require(self.document["paths"]["source"] == str(self.source),
                "dependency receipt selects a different measurement source")
        self.receipt_identity = _live_identity(self.path)
        require(self.receipt_identity["sha256"] == expected_sha256,
                "dependency receipt changed after validation")
        require(self.document["fresh_dependency_build_passed"] is True
                and self.verification["fresh_dependency_build_passed"] is True,
                "dependency receipt did not establish a complete fresh build")
        require(all(self.document[name] is False for name in dependency_contract.FALSE_CLAIMS),
                "dependency receipt changes a non-acceptance claim")
        self.products = self.document["products"]
        require(set(self.products) == set(dependency_contract.PRODUCTS),
                "dependency receipt changes the selected product inventory")
        self.source_inputs = []
        staged = []
        for source_record in self.document["source_manifest"]["sources"]:
            name = source_record["name"]
            root = self.source / dependency_contract.PINS[name]["path"]
            for item in source_record["files"]:
                row = {"path": str(root / item["path"]), "sha256": item["sha256"],
                       "size_bytes": item["size_bytes"]}
                self.source_inputs.append(row)
                if name in ("yaml-cpp", "spdlog", "argparse"):
                    staged.append(row)
        for name, relative in dependency_contract.PRODUCTS.items():
            product = self.products[name]
            require(product["staged_path"] == str(self.source / relative),
                    "dependency product is not at its canonical measurement path")
            staged.append({"path": product["staged_path"], "sha256": product["sha256"],
                           "size_bytes": product["size_bytes"]})
        self.source_inputs.sort(key=lambda item: item["path"])
        staged.sort(key=lambda item: item["path"])
        require(staged == self.document["staged_files"]
                and len({item["path"] for item in staged}) == len(staged),
                "staged dependency inventory differs from the complete pinned inputs")
        self.staged_files = staged
        self.helpers = self.document["helper_sources"]
        require(type(self.helpers) is list and self.helpers
                and all(type(row) is dict and set(row) == {"path", "sha256", "size_bytes"}
                        and receipt.relative(row["path"]).startswith("ci/project/") for row in self.helpers)
                and len({row["path"] for row in self.helpers}) == len(self.helpers),
                "dependency helper source inventory is malformed or duplicated")
        self.summary = {
            "receipt_sha256": expected_sha256,
            "dependency_contract_sha256": dependency_contract.contract_hash(),
            "source_manifest_sha256": dependency_contract.digest(self.document["source_manifest"]),
            "staged_files_sha256": dependency_contract.digest(self.staged_files),
            "verification": self.verification,
        }
        self.verify_stable()

    def verify_stable(self, managed_tools=None):
        require(_live_identity(self.path) == self.receipt_identity,
                "dependency receipt changed after admission")
        for item in (*self.source_inputs, *self.staged_files):
            require(_live_identity(item["path"]) == item,
                    "pinned dependency source or staged bytes changed: " + item["path"])
        require(hash_artifacts(self.source, [item["path"] for item in self.helpers]) == self.helpers,
                "dependency build helper bytes changed after admission")
        selected_tools = self.document["tools"]
        for name, expected in selected_tools.items():
            require(base._file_identity(expected["path"]) == expected,
                    "dependency tool identity changed: " + name)
            if managed_tools is not None and name in managed_tools:
                require(managed_tools[name] == expected,
                        "managed and dependency selected tools differ: " + name)
        for row in self.document.get("external_archives", []):
            digest, size = _digest(Path(row["original_path"]).resolve(strict=True))
            require((digest, size) == (row["descriptor"]["sha256"], row["descriptor"]["size_bytes"]),
                    "recorded compiler support archive changed")
        return {"receipt_sha256": self.receipt_identity["sha256"],
                "source_inputs_sha256": dependency_contract.digest(self.source_inputs),
                "staged_files_sha256": self.summary["staged_files_sha256"],
                "tools_sha256": dependency_contract.digest(selected_tools),
                "helper_sources_sha256": dependency_contract.digest(self.helpers)}

    def verify_model_stable(self, record):
        for identity in (record["map"], record["model"], *record["objects"]):
            require(_live_identity(identity["path"]) == identity,
                    "admitted model object, binary or link map changed")

    def validate_application(self, text, stamp, *, build, tools_root, tools, fmt,
                             compiler_records, source_files):
        identities = {row["path"]: row for row in source_files}

        def source_body(name):
            require(name in identities, "application recipe is outside the frozen source inventory")
            require(hash_artifacts(self.source, [name])[0] == identities[name],
                    "application recipe changed after the source freeze")
            data = (self.source / name).read_bytes()
            require(hashlib.sha256(data).hexdigest() == identities[name]["sha256"]
                    and len(data) == identities[name]["size_bytes"],
                    "application recipe changed while being read")
            return data

        return application.validate_application_build(text, stamp, source=self.source,
            build=build, tools_root=tools_root, tools=tools, fmt=fmt,
            compiler_records=compiler_records, source_body=source_body)

    def validate_model(self, build, model_records):
        build = base._path(build, existing=True)
        self.verify_stable()
        softfloat = self.products["softfloat"]
        members = self.verification["archives"]["softfloat"]["members"]
        archive = binary.validate_archive(Path(softfloat["staged_path"]).read_bytes(), members)
        require((archive["sha256"], archive["size_bytes"])
                == (softfloat["sha256"], softfloat["size_bytes"]),
                "model SoftFloat archive differs from its fresh compiler outputs")
        path = build / MODEL_MAP
        identity = _live_identity(path)
        text = path.read_text(encoding="utf-8", errors="strict")
        require(hashlib.sha256(text.encode()).hexdigest() == identity["sha256"],
                "model link map changed while being read")
        archives = {softfloat["staged_path"]: members}
        for row in self.document.get("external_archives", []):
            checked = binary.validate_archive(Path(row["original_path"]).read_bytes(), row["members"])
            require((checked["sha256"], checked["size_bytes"])
                    == (row["descriptor"]["sha256"], row["descriptor"]["size_bytes"]),
                    "recorded compiler support archive changed")
            archives[row["original_path"]] = checked["members"]
        checked = binary.validate_link_map(text, cwd=str(build / "sim/simx"), archives=archives,
            required_archives=[softfloat["staged_path"]],
            required_loads=[self.products[name]["staged_path"] for name in ("ramulator", "extension")])
        objects = sorted(str(model.expected_object(name, build)) for name in model.MODEL_SOURCES)
        require(model_records["object_paths"] == objects
                and model_records["dependency_link_map"] == str(path),
                "model link map differs from its validated compiler graph")
        loads = Counter(checked["loads"])
        require(all(loads[name] == 1 for name in objects),
                "model link map lacks an exact production object load")
        project_roots = (self.source, build.parent, Path(self.document["paths"]["workspace"]))
        external = {row["original_path"] for row in self.document.get("external_archives", [])}
        project_loads = [name for name in checked["loads"] if name not in external
                         and any(Path(name).is_relative_to(root) for root in project_roots)]
        expected_loads = objects + [self.products[name]["staged_path"]
                                    for name in dependency_contract.PRODUCTS]
        require(sorted(project_loads) == sorted(expected_loads),
                "model map contains an unplanned source/work input")
        return {"dependency_receipt_sha256": self.receipt_identity["sha256"],
                "map": identity, "verification": checked,
                "model": _live_identity(build / "sw/runtime/libsimx.so"),
                "objects": [_live_identity(name) for name in objects],
                "products": self.products,
                "source_to_model_link_verified": True,
                **dict.fromkeys(dependency_contract.FALSE_CLAIMS, False)}
