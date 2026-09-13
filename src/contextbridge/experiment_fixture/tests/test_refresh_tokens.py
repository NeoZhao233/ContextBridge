import unittest

from resume_fixture.refresh_tokens import RefreshTokenStore


class RefreshTokenTests(unittest.TestCase):
    def test_replay_revokes_the_entire_family(self) -> None:
        store = RefreshTokenStore()
        store.issue("family-1", "token-1")
        store.exchange("family-1", "token-1", "token-2")

        with self.assertRaisesRegex(ValueError, "reuse"):
            store.exchange("family-1", "token-1", "token-3")
        with self.assertRaisesRegex(ValueError, "revoked"):
            store.exchange("family-1", "token-2", "token-3")


if __name__ == "__main__":
    unittest.main()
