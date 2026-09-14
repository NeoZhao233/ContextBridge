import unittest

from resume_fixture.refresh_tokens import RefreshTokenReuseError, RefreshTokenStore


class RefreshTokenTests(unittest.TestCase):
    def test_rotation_and_typed_replay_error(self) -> None:
        store = RefreshTokenStore()
        store.issue("family-1", "token-1")
        store.exchange("family-1", "token-1", "token-2")

        with self.assertRaises(RefreshTokenReuseError):
            store.exchange("family-1", "token-1", "token-3")
        self.assertTrue(issubclass(RefreshTokenReuseError, ValueError))


if __name__ == "__main__":
    unittest.main()
