# SPDX-License-Identifier: Apache-2.0
"""Independent controls for preparation origin and retained live identities."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

import p06_dependency_admission as admission
import p06_dependency_contract as contract
import p06_dependency_receipt as receipt
from test_p06_dependency_admission import LiveInputs, REVISION
from test_p06_dependency_local_prepare import synthetic_preparation


class LocalPreparationBoundaryReviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="p06-local-boundary-review-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        host = self.root / "host-cxx"
        host.write_bytes(b"synthetic host compiler")
        self.inputs = LiveInputs(self.source, {"g++": admission.base._file_identity(host)})

    def retain(self, document):
        self.inputs.preparation_path.write_bytes(contract.json_bytes(document) + b"\n")
        self.inputs.document["preparation"] = dict(
            admission._live_identity(self.inputs.preparation_path), path=self.inputs.preparation_path.name)
        self.inputs.write()

    def test_explicit_local_metadata_cannot_select_the_hosted_validator(self):
        hosted = {"contract_id": "p06-dependency-preparation-v1", "outcome": "pass", "reason": None,
                  "expected_revision": REVISION, "dependency_contract_sha256": contract.contract_hash(),
                  "dependency_cache_used": False}
        self.assertIsNone(receipt.validate_preparation(hosted, REVISION))
        local = synthetic_preparation(self.root, REVISION)
        local["resources_before"]["available_memory_bytes"] = 0
        local["toolchain_receipt"]["tools"]["clang"]["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            receipt.validate_preparation(local, REVISION)
        local["contract_id"] = hosted["contract_id"]
        for document in (local, dict(hosted, execution_origin="local"),
                         dict(hosted, toolchain_receipt=deepcopy(local["toolchain_receipt"]))):
            with self.subTest(fields=sorted(document)), self.assertRaises(ValueError):
                receipt.validate_preparation(document, REVISION)

    def test_relabeling_local_preparation_cannot_skip_live_native_tools(self):
        local = synthetic_preparation(self.root, REVISION)
        self.retain(local)
        with self.assertRaisesRegex(ValueError, "locally provisioned tool identity changed"):
            self.inputs.admit()
        local["contract_id"] = "p06-dependency-preparation-v1"
        self.retain(local)
        with self.assertRaises(ValueError):
            self.inputs.admit()

    def test_hardlinked_preparation_is_rejected_before_live_admission(self):
        alias = self.root / "preparation-alias.json"
        alias.hardlink_to(self.inputs.preparation_path)
        with self.assertRaisesRegex(ValueError, "unlinked regular file"):
            self.inputs.admit()

    def test_new_hardlink_cannot_preserve_a_previously_admitted_preparation(self):
        checked = self.inputs.admit()
        alias = self.root / "preparation-alias.json"
        alias.hardlink_to(self.inputs.preparation_path)
        with self.assertRaisesRegex(ValueError, "unlinked regular file"):
            checked.verify_stable()


if __name__ == "__main__":
    unittest.main()
