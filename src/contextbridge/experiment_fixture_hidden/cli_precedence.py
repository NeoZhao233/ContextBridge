import json
import sys
import tempfile
from importlib import import_module
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
config = import_module("resume_fixture.config")
ConfigError = config.ConfigError
resolve_config = config.resolve_config


def check(operation) -> bool:
    try:
        return bool(operation())
    except Exception:  # noqa: BLE001 - a broken candidate counts as a failed assertion
        return False


def resolve(file_content: str | None, environment=None, cli=None):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "config.json"
        if file_content is not None:
            path.write_text(file_content, encoding="utf-8")
        return resolve_config(path, environment or {}, cli or {})


def malformed_is_error() -> bool:
    try:
        resolve("not-json")
    except ConfigError:
        return True
    return False


def non_object_is_error() -> bool:
    try:
        resolve("[]")
    except ConfigError:
        return True
    return False


assertions = [
    check(lambda: resolve('{"value":"file"}', {"value": "env"}, {"value": "cli"})["value"] == "cli"),
    check(lambda: resolve('{"value":"file"}', {"value": "env"})["value"] == "env"),
    check(lambda: resolve('{"value":"file"}')["value"] == "file"),
    check(lambda: resolve(None, {"value": "env"}) == {"value": "env"}),
    check(malformed_is_error),
    check(non_object_is_error),
]
decisions = assertions[:3]
regression_checks = [check(lambda: resolve(None) == {}), check(malformed_is_error)]
result = {
    "assertions_passed": sum(assertions),
    "assertions_total": len(assertions),
    "decision_checks_passed": sum(decisions),
    "decision_checks_total": len(decisions),
    "regressions": len(regression_checks) - sum(regression_checks),
}
print(json.dumps(result, sort_keys=True))
raise SystemExit(0 if all(assertions) and all(decisions) and not result["regressions"] else 1)
