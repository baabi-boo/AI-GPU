# SPDX-License-Identifier: Apache-2.0
"""Boundary controls for completed serial governance event populations."""

import unittest

import governance_replay_events as replay
import test_governance_replay_events as fixtures


class GovernanceReplayEventControlsTests(unittest.TestCase):
    def test_start_after_complete_population_is_rejected_before_manifest_indexing(self):
        discovered, records, execution = fixtures.GovernanceReplayEventsTests.produce()
        fixtures.GovernanceReplayEventsTests.resequence(records)
        execution["duration_seconds"] = 0
        self.assertEqual(replay.reconcile(discovered, fixtures._encode(records), execution), execution)

        for identity in (discovered["test_ids"][0], "test_fixture.Case.test_extra"):
            with self.subTest(identity=identity):
                trailing = {
                    "sequence": len(records) + 1, "event": "test_start",
                    "elapsed_seconds": 0, "test_id": identity,
                }
                claim = {**execution, "event_count": len(records) + 1}
                with self.assertRaisesRegex(replay.ReplayEventsError, "discovered test order"):
                    replay.reconcile(discovered, fixtures._encode([*records, trailing]), claim)


if __name__ == "__main__":
    unittest.main()
