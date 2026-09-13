import tempfile
import unittest
from pathlib import Path

from resume_fixture.config import ConfigError, resolve_config


class ConfigTests(unittest.TestCase):
    def test_cli_overrides_environment_and_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text('{"endpoint": "file", "timeout": "10"}', encoding="utf-8")
            resolved = resolve_config(
                path,
                {"endpoint": "environment", "timeout": "20"},
                {"endpoint": "cli"},
            )
        self.assertEqual(resolved, {"endpoint": "cli", "timeout": "20"})

    def test_missing_file_is_allowed_but_malformed_file_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(resolve_config(root / "missing.json", {}, {}), {})
            malformed = root / "config.json"
            malformed.write_text("not-json", encoding="utf-8")
            with self.assertRaises(ConfigError):
                resolve_config(malformed, {}, {})


if __name__ == "__main__":
    unittest.main()
