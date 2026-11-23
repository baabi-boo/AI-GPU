# SPDX-License-Identifier: Apache-2.0
"""Old transcripts cannot acquire a new prelaunch qualification binding.

The packets are synthetic tooling inputs. Dependency and historical-prerequisite
reader boundaries are mocked; production transcript validation is exercised.
"""

from copy import deepcopy
import unittest
from unittest import mock

import p06_counter_qualification_replay as replay
from p06_counter_qualification_test_fixture import SyntheticQualificationPacket
from test_p06_dependency_native_replay import MemoryView, SyntheticNativePacket, descriptor


class HistoricalTranscriptCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old = SyntheticNativePacket()
        cls.qualified = SyntheticQualificationPacket()

    def test_old_raw_transcript_rejects_after_new_envelope_and_digest_repair(self):
        """A proof attached later cannot change a recorded process's identity."""
        old_processes = {row["id"]: row for row in self.old.report["processes"]}
        for selected in self.qualified.report["processes"]:
            with self.subTest(process=selected["id"]):
                packet = deepcopy(self.qualified)
                process = next(row for row in packet.report["processes"]
                               if row["id"] == selected["id"])
                original = old_processes[process["id"]]
                self.assertNotEqual(process["execution_binding_sha256"],
                                    original["execution_binding_sha256"])
                command = next(row for row in packet.report["commands"]
                               if row["id"] == process["command_id"])
                old_text = self.old.files[original["log"]].decode("utf-8")
                packet.log(command, old_text)
                process["observation"] = deepcopy(original["observation"])
                process["retained_observation"] = packet.put_json(
                    process["retained_observation"]["path"], process["observation"])
                packet.report["raw_logs"] = [descriptor(row["log"], packet.files[row["log"]])
                                             for row in packet.report["commands"]]
                packet.finish()
                checked = {"retained_dependency_verification": packet.dependency_verification}
                with mock.patch.object(replay.native.dependency_replay, "verify_view",
                                       return_value=checked), \
                     mock.patch.object(replay.prerequisites, "verify_prerequisites",
                                       return_value=packet.diagnostics), \
                     mock.patch.object(replay.prerequisites, "verify_control_prerequisite",
                                       return_value=packet.controls), \
                     self.assertRaisesRegex(ValueError, "managed witness.execution_binding_sha256"):
                    replay.verify_view(MemoryView(packet.files, packet.api),
                        MemoryView({"report.json": packet.dependency_body}, packet.api),
                        packet.api, **packet.arguments())


if __name__ == "__main__":
    unittest.main()
