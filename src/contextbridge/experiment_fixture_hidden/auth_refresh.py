import json
import sys
from importlib import import_module
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
refresh_tokens = import_module("resume_fixture.refresh_tokens")


def check(operation) -> bool:
    try:
        return bool(operation())
    except Exception:  # noqa: BLE001 - a broken candidate counts as a failed assertion
        return False


def rotated_token_works() -> bool:
    store = refresh_tokens.RefreshTokenStore()
    store.issue("family", "one")
    store.exchange("family", "one", "two")
    store.exchange("family", "two", "three")
    return True


def replay_is_rejected() -> bool:
    store = refresh_tokens.RefreshTokenStore()
    store.issue("family", "one")
    store.exchange("family", "one", "two")
    try:
        store.exchange("family", "one", "three")
    except ValueError as error:
        return "reuse" in str(error)
    return False


def replay_revokes_family() -> bool:
    store = refresh_tokens.RefreshTokenStore()
    store.issue("family", "one")
    store.exchange("family", "one", "two")
    try:
        store.exchange("family", "one", "three")
    except ValueError:
        pass
    try:
        store.exchange("family", "two", "three")
    except ValueError as error:
        return "revoked" in str(error)
    return False


def other_family_survives() -> bool:
    store = refresh_tokens.RefreshTokenStore()
    store.issue("first", "one")
    store.issue("second", "alpha")
    store.exchange("first", "one", "two")
    try:
        store.exchange("first", "one", "three")
    except ValueError:
        pass
    store.exchange("second", "alpha", "beta")
    return True


def evidence_is_retained() -> bool:
    store = refresh_tokens.RefreshTokenStore()
    store.issue("family", "one")
    store.exchange("family", "one", "two")
    try:
        store.exchange("family", "one", "three")
    except ValueError:
        pass
    return store.replay_evidence("family") == ("one",)


def typed_errors_are_preserved() -> bool:
    return issubclass(refresh_tokens.RefreshTokenReuseError, ValueError) and issubclass(
        refresh_tokens.TokenFamilyRevokedError, ValueError
    )


assertions = [
    check(rotated_token_works),
    check(replay_is_rejected),
    check(replay_revokes_family),
    check(other_family_survives),
    check(evidence_is_retained),
    check(typed_errors_are_preserved),
]
decisions = [
    check(replay_revokes_family),
    check(other_family_survives),
    check(typed_errors_are_preserved),
]
regression_checks = [check(rotated_token_works), check(replay_is_rejected)]
result = {
    "assertions_passed": sum(assertions),
    "assertions_total": len(assertions),
    "decision_checks_passed": sum(decisions),
    "decision_checks_total": len(decisions),
    "regressions": len(regression_checks) - sum(regression_checks),
}
print(json.dumps(result, sort_keys=True))
raise SystemExit(0 if all(assertions) and all(decisions) and not result["regressions"] else 1)
