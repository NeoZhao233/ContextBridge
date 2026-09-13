import json
from pathlib import Path


class ConfigError(ValueError):
    pass


def resolve_config(
    path: Path,
    environment: dict[str, str],
    cli_values: dict[str, str],
) -> dict[str, str]:
    if not path.exists():
        file_values: dict[str, str] = {}
    else:
        try:
            file_values = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as error:
            raise ConfigError(f"invalid config file: {error}") from error
    # Intentional baseline bug: environment and CLI precedence are not implemented.
    return {str(key): str(value) for key, value in file_values.items()}
