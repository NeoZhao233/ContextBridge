class CommitError(RuntimeError):
    pass


class ProfileStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.fail_next_commit = False

    def commit(self, user_id: str, value: str) -> None:
        if self.fail_next_commit:
            self.fail_next_commit = False
            raise CommitError("commit failed")
        self.values[user_id] = value


class ProfileService:
    def __init__(self, store: ProfileStore, cache: dict[str, str]) -> None:
        self.store = store
        self.cache = cache

    def update(self, user_id: str, value: str) -> None:
        # Intentional baseline bug: a failed commit must leave the cached value intact.
        self.cache.pop(user_id, None)
        self.store.commit(user_id, value)
