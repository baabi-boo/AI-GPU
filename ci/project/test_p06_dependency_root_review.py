# SPDX-License-Identifier: Apache-2.0
"""Project-root controls with explicitly synthetic admission and native inputs.

The live model boundary reads actual fixture bytes. Native/control observations
are invented consistency fixtures. No dependency compilation or native execution
is established, and the targeted map/control semantics are not replaced.
"""

from copy import deepcopy
import hashlib
from pathlib import Path, PurePosixPath
import tempfile
import unittest

import p06_dependency_admission as admission
import p06_dependency_control_replay as controls
import p06_dependency_native_replay as native
import p06_managed_preflight_execute as preflight
from test_p06_dependency_admission import LiveInputs
from test_p06_dependency_native_replay import descriptor, digest, json_bytes
from test_p06_dependency_control_replay import SyntheticNativeWithControlTools, SyntheticControls


class WorkspaceNativePacket(SyntheticNativeWithControlTools):
    def make_dependencies(self):
        super().make_dependencies()
        self.dependency_document["paths"]["workspace"] = str(PurePosixPath(self.report["paths"]["work"]).parent)
        self.dependency_body = json_bytes(self.dependency_document)
        self.receipt_pin = digest(self.dependency_body)
        self.admission, self.stability = native._admission_values(
            self.dependency_document, self.dependency_verification, self.receipt_pin)


class LiveWorkspaceRootTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="p06-live-workspace-roots-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        tool = self.root / "host-cxx"
        tool.write_bytes(b"synthetic host compiler identity")
        self.inputs = LiveInputs(self.source, {"g++": preflight.base._file_identity(tool)})
        self.workspace = self.root / "dependency-workspace"
        self.workspace.mkdir(exist_ok=True)
        self.inputs.document["paths"]["workspace"] = str(self.workspace)
        for item in self.inputs.document["products"].values():
            item["original_path"] = str(self.workspace / "dependency-build" / Path(item["original_path"]).name)
        self.inputs.write()
        self.build = self.root / "native-work" / "simx-fp16"
        self.build.mkdir(parents=True)
        self.records = self.inputs.model(self.build)

    def test_dependency_workspace_inputs_are_not_external_model_loads(self):
        selected = self.inputs.admit()
        self.assertIs(selected.validate_model(self.build, self.records)["source_to_model_link_verified"], True)
        path = self.build / admission.MODEL_MAP
        original = path.read_text()
        for relative in ("dependency-build/unplanned.so", "dependency-sources/unplanned.o",
                         "evidence/unplanned.so", "tools/unplanned.o"):
            path.write_text(original + "\nLOAD " + str(self.workspace / relative) + "\n")
            with self.subTest(relative=relative), self.assertRaisesRegex(ValueError, "unplanned source/work"):
                selected.validate_model(self.build, self.records)

    def test_already_admitted_compiler_archive_can_repeat_inside_workspace(self):
        # The complete receipt boundary is stubbed; this supplies only the
        # already-admitted support archive used by this model boundary.
        body = (self.source / admission.dependency_contract.PRODUCTS["softfloat"]).read_bytes()
        support = self.workspace / "tools/libgcc.a"
        support.parent.mkdir()
        support.write_bytes(body)
        self.inputs.document["external_archives"] = [{"original_path": str(support),
            "members": self.inputs.members,
            "descriptor": {"sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)}}]
        self.inputs.write()
        selected = self.inputs.admit()
        path = self.build / admission.MODEL_MAP
        path.write_text(path.read_text() + "\nLOAD " + str(support) + "\nLOAD " + str(support) + "\n")
        result = selected.validate_model(self.build, self.records)
        self.assertIs(result["source_to_model_link_verified"], True)
        self.assertEqual(result["verification"]["loads"].count(str(support)), 2)


class RetainedWorkspaceRootTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = WorkspaceNativePacket()
        cls.native = cls.original.reader()
        cls.native.run()
        cls.workspace = PurePosixPath(cls.native.dependency_document["paths"]["workspace"])

    def test_native_model_map_reconciles_dependency_workspace_loads(self):
        for relative in ("dependency-build/unplanned.so", "evidence/unplanned.o"):
            with self.subTest(relative=relative):
                packet = deepcopy(self.original)
                variant = packet.report["variants"][0]
                name = native.admission.MODEL_MAP
                payload = next(row for row in variant["retained_dependency_model_payloads"]
                               if row["path"].endswith("/" + name))
                body = packet.files[payload["path"]] + ("LOAD " + str(self.workspace / relative) + "\n").encode()
                packet.report["retained_payload_bytes"] += len(body) - payload["size_bytes"]
                payload.update(packet.put(payload["path"], body))
                for key in ("artifacts_before", "artifacts_after"):
                    row = next(row for row in variant[key] if row["path"] == name)
                    row.update(descriptor(name, body))
                model = variant["dependency_model_link"]
                model["map"] = descriptor(variant["build_dir"] + "/" + name, body)
                products = packet.dependency_document["products"]
                softfloat = products["softfloat"]["staged_path"]
                model["verification"] = native.binary.validate_link_map(body.decode(),
                    cwd=variant["build_dir"] + "/sim/simx", archives={softfloat: packet.members},
                    required_archives=[softfloat], required_loads=[products[key]["staged_path"]
                        for key in ("ramulator", "extension")])
                packet.finish()
                checked = packet.reader()
                checked.budget()
                checked.provenance()
                checked.paths_and_tools()
                checked.variant = checked.report["variants"][0]
                checked.fmt, checked.variant_id = "fp16", "simx-fp16"
                checked.build = checked.paths["work"] / checked.variant_id
                checked.generated()
                # Seven version observations precede the targeted model build.
                checked.command_index = 7
                with self.assertRaisesRegex(ValueError, "unplanned source/work"):
                    checked.compiler_commands()

    def test_substitution_map_reconciles_dependency_workspace_loads(self):
        self.assertEqual(SyntheticControls(self.original, self.native).substitution_check()["outcome"], "pass")
        for relative in ("dependency-build/unplanned.so", "dependency-sources/unplanned.o"):
            with self.subTest(relative=relative):
                packet = SyntheticControls(self.original, self.native)
                report, files = packet.substitution_report, packet.substitution_files
                linked = deepcopy(report["dependency_control"]["link"])
                previous = "payloads/" + linked["link_map"]["payload"]
                body = files["work/control.map"] + ("LOAD " + str(self.workspace / relative) + "\n").encode()
                linked["link_map"] = packet.payload(linked["link_map"]["path"], body)
                files["work/control.map"] = body
                del files[previous]
                report["dependency_control"]["map_verification"] = controls.substitution.binary.validate_link_map(
                    body.decode(), cwd=str(packet.work), archives={}, required_loads=[
                        self.native.dependency_document["products"]["ramulator"]["staged_path"],
                        report["dependency_control"]["compile"]["output_path"]])
                packet.replace_substitution_record("link", linked)
                with self.assertRaisesRegex(ValueError, "unplanned source/work"):
                    packet.substitution_check()

    def test_substitution_header_closure_covers_dependency_workspace(self):
        self.assertEqual(SyntheticControls(self.original, self.native).substitution_check()["outcome"], "pass")
        for resolved_only in (False, True):
            with self.subTest(resolved_only=resolved_only):
                packet = SyntheticControls(self.original, self.native)
                files = packet.substitution_files
                compiled = deepcopy(packet.substitution_report["dependency_control"]["compile"])
                project_path = self.workspace / "dependency-sources/unplanned.h"
                path = PurePosixPath("/synthetic-system/workspace-alias.h") if resolved_only else project_path
                extra = packet.payload(path, b"/* synthetic unreviewed header */\n")
                if resolved_only:
                    extra["resolved_path"] = str(project_path)
                compiled["inputs_before"].append(extra)
                compiled["inputs_after"] = deepcopy(compiled["inputs_before"])
                body = (compiled["output_path"] + ": " + " ".join(
                    row["path"] for row in compiled["inputs_before"]) + "\n").encode()
                previous = {"payloads/" + compiled[key]["payload"]
                            for key in ("dependency_file", "dependency_prepass_file")}
                for key, relative in (("dependency_file", "work/gddr6-control.o.d"),
                                      ("dependency_prepass_file", "work/gddr6-control.o.p06-before.d")):
                    compiled[key] = packet.payload(compiled[key]["path"], body)
                    files[relative] = body
                for name in previous:
                    del files[name]
                packet.replace_substitution_record("compile", compiled)
                with self.assertRaisesRegex(ValueError, "unreviewed .*file"):
                    packet.substitution_check()


if __name__ == "__main__":
    unittest.main()
