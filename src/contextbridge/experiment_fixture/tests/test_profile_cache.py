import unittest

from resume_fixture.profile_cache import CommitError, ProfileService, ProfileStore


class ProfileCacheTests(unittest.TestCase):
    def test_success_invalidates_cache_after_commit(self) -> None:
        store = ProfileStore()
        cache = {"user-1": "old"}
        ProfileService(store, cache).update("user-1", "new")
        self.assertNotIn("user-1", cache)
        self.assertEqual(store.values["user-1"], "new")

    def test_failed_commit_keeps_cached_value(self) -> None:
        store = ProfileStore()
        store.fail_next_commit = True
        cache = {"user-1": "old"}
        with self.assertRaises(CommitError):
            ProfileService(store, cache).update("user-1", "new")
        self.assertEqual(cache["user-1"], "old")


if __name__ == "__main__":
    unittest.main()
