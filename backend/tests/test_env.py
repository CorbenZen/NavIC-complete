import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from navic_tcp.env import load_env_file


class EnvFileTests(unittest.TestCase):
    def test_loads_values_without_overriding_existing_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(
                "# comment\n"
                "NEW_SETTING=from-file\n"
                "QUOTED=\"value with spaces\"\n"
                "export EXPORTED=yes\n"
                "EXISTING=file-value\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"EXISTING": "shell-value"}, clear=False):
                os.environ.pop("NEW_SETTING", None)
                os.environ.pop("QUOTED", None)
                os.environ.pop("EXPORTED", None)
                self.assertTrue(load_env_file(path))
                self.assertEqual(os.environ["NEW_SETTING"], "from-file")
                self.assertEqual(os.environ["QUOTED"], "value with spaces")
                self.assertEqual(os.environ["EXPORTED"], "yes")
                self.assertEqual(os.environ["EXISTING"], "shell-value")

    def test_missing_file_is_a_noop(self):
        self.assertFalse(load_env_file("/nonexistent/navic/.env"))


if __name__ == "__main__":
    unittest.main()
