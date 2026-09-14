import json
import sys
from importlib import import_module
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
profile_cache = import_module("resume_fixture.profile_cache")
CommitError = profile_cache.CommitError
ProfileService = profile_cache.ProfileService
ProfileStore = profile_cache.ProfileStore


def check(operation) -> bool:
    try:
        return bool(operation())
    except Exception:  # noqa: BLE001 - a broken candidate counts as a failed assertion
        return False


def success_state() -> tuple[dict[str, str], ProfileStore]:
    store = ProfileStore()
    cache = {"user": "old"}
    ProfileService(store, cache).update("user", "new")
    return cache, store


def failure_state() -> tuple[dict[str, str], ProfileStore, bool]:
    store = ProfileStore()
    store.values["user"] = "old"
    store.fail_next_commit = True
    cache = {"user": "old", "other": "stable"}
    raised = False
    try:
        ProfileService(store, cache).update("user", "new")
    except CommitError:
        raised = True
    return cache, store, raised


def original_error_is_propagated() -> bool:
    original = CommitError("sentinel")

    class FailingStore(ProfileStore):
        def commit(self, user_id: str, value: str) -> None:
            raise original

    cache = {"user": "old", "other": "stable"}
    try:
        ProfileService(FailingStore(), cache).update("user", "new")
    except CommitError as error:
        return error is original and cache == {"user": "old", "other": "stable"}
    return False


def commit_precedes_invalidation() -> bool:
    events: list[str] = []

    class LoggingStore(ProfileStore):
        def commit(self, user_id: str, value: str) -> None:
            events.append("commit")
            super().commit(user_id, value)

    class LoggingCache(dict):
        def pop(self, key, default=None):
            events.append("invalidate")
            return super().pop(key, default)

    ProfileService(LoggingStore(), LoggingCache(user="old")).update("user", "new")
    return events == ["commit", "invalidate"]


assertions = [
    check(lambda: success_state()[0] == {}),
    check(lambda: success_state()[1].values.get("user") == "new"),
    check(lambda: failure_state()[2]),
    check(lambda: failure_state()[0].get("user") == "old"),
    check(lambda: failure_state()[0].get("other") == "stable"),
    check(lambda: failure_state()[1].values.get("user") == "old"),
    check(lambda: ProfileService(ProfileStore(), {}).update("missing", "new") is None),
    check(original_error_is_propagated),
]
decisions = [
    check(commit_precedes_invalidation),
    check(lambda: failure_state()[0] == {"user": "old", "other": "stable"}),
    check(lambda: failure_state()[2]),
    check(original_error_is_propagated),
]
regression_checks = [
    check(lambda: success_state()[1].values.get("user") == "new"),
    check(lambda: success_state()[0] == {}),
]
result = {
    "assertions_passed": sum(assertions),
    "assertions_total": len(assertions),
    "decision_checks_passed": sum(decisions),
    "decision_checks_total": len(decisions),
    "regressions": len(regression_checks) - sum(regression_checks),
}
print(json.dumps(result, sort_keys=True))
raise SystemExit(0 if all(assertions) and all(decisions) and not result["regressions"] else 1)
