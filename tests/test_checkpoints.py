"""
Tests for First-Class Checkpoint Assertions.
Verifies assertion evaluations against surface state.
"""

import unittest
from core.artifact.schema import AssertionType, CheckpointAssertion
from core.surface.base import InteractiveControl, SurfaceState
from core.replay.engine import DeterministicReplayEngine


class MockSurfaceForCheckpoints:
    def __init__(self, url: str, page_text: str):
        self.state = SurfaceState(url=url, title="Test", controls=[], page_text=page_text)

    def get_state(self):
        return self.state


class TestCheckpoints(unittest.TestCase):

    def test_url_matches_checkpoint(self):
        mock_surf = MockSurfaceForCheckpoints(
            url="http://127.0.0.1:8080/member_detail?id=M-10928",
            page_text="Member profile"
        )
        engine = DeterministicReplayEngine(surface=mock_surf)

        chk_pass = CheckpointAssertion(
            assertion_type=AssertionType.URL_MATCHES,
            description="Verify detail URL",
            expected_value="member_detail"
        )
        passed, msg = engine._verify_checkpoint(chk_pass)
        self.assertTrue(passed)

        chk_fail = CheckpointAssertion(
            assertion_type=AssertionType.URL_MATCHES,
            description="Verify incorrect URL",
            expected_value="admin_console"
        )
        passed, msg = engine._verify_checkpoint(chk_fail)
        self.assertFalse(passed)

    def test_text_contains_checkpoint(self):
        mock_surf = MockSurfaceForCheckpoints(
            url="http://127.0.0.1:8080/member_detail",
            page_text="Account Summary & Ledger Balances for Johnathan Doe"
        )
        engine = DeterministicReplayEngine(surface=mock_surf)

        chk_pass = CheckpointAssertion(
            assertion_type=AssertionType.TEXT_CONTAINS,
            description="Verify ledger text",
            expected_value="Account Summary & Ledger Balances"
        )
        passed, msg = engine._verify_checkpoint(chk_pass)
        self.assertTrue(passed)

        chk_fail = CheckpointAssertion(
            assertion_type=AssertionType.TEXT_CONTAINS,
            description="Verify absent text",
            expected_value="Wire Transfer Confirmation"
        )
        passed, msg = engine._verify_checkpoint(chk_fail)
        self.assertFalse(passed)


if __name__ == "__main__":
    unittest.main()
