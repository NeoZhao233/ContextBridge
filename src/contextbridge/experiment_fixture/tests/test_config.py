import tempfile
import unittest
from pathlib import Path

from resume_fixture.config import resolve_config


class ConfigTests(unittest.TestCase):
    def test_environment_overrides_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text('{"endpoint": "file", "timeout": "10"}', encoding="utf-8")
            resolved = resolve_config(
                path,
                {"endpoint": "environment", "timeout": "20"},
                {},
            )
        self.assertEqual(resolved, {"endpoint": "environment", "timeout": "20"})

    def test_missing_file_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(resolve_config(root / "missing.json", {}, {}), {})


if __name__ == "__main__":
    unittest.main()
