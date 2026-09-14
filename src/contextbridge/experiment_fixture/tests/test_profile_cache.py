import unittest

from resume_fixture.profile_cache import ProfileService, ProfileStore


class ProfileCacheTests(unittest.TestCase):
    def test_success_commits_before_invalidating_target(self) -> None:
        events: list[str] = []

        class LoggingStore(ProfileStore):
            def commit(self, user_id: str, value: str) -> None:
                events.append("commit")
                super().commit(user_id, value)

        class LoggingCache(dict[str, str]):
            def pop(self, key: str, default: str | None = None) -> str | None:
                events.append("invalidate")
                return super().pop(key, default)

        store = LoggingStore()
        cache = LoggingCache({"user-1": "old", "user-2": "stable"})
        ProfileService(store, cache).update("user-1", "new")
        self.assertNotIn("user-1", cache)
        self.assertEqual(cache["user-2"], "stable")
        self.assertEqual(store.values["user-1"], "new")
        self.assertEqual(events, ["commit", "invalidate"])


if __name__ == "__main__":
    unittest.main()
