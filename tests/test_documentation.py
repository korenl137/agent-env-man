"""Local documentation lookup works independently of configured installations."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from click.testing import CliRunner

from agent_env_man.cli import cli
from agent_env_man.commands import documentation


class Documentation(unittest.TestCase):
    def test_lookup_without_configuration_or_working_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "invalid.toml"
            config.write_text("not valid TOML [", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                # Any accidental entry into ordinary execution would read
                # configuration and take locks, which docs must bypass.
                with patch("agent_env_man.cli_runtime.Runtime.run", side_effect=AssertionError("operation executed")):
                    for flags in ([], ["--json"]):
                        result = CliRunner().invoke(cli, ["--config", str(config), *flags, "docs"])
                        self.assertEqual(result.exit_code, 0, result.output)
                        entry = (json.loads(result.output)["entry"] if flags else result.output.strip())
                        self.assertTrue(Path(entry).is_absolute())
                        self.assertTrue(Path(entry).is_file())
                        self.assertTrue((Path(entry).parent / "docs" / "commands.md").is_file())
            finally:
                os.chdir(previous)
            self.assertEqual(list(root.iterdir()), [config])

    def test_installed_resources_take_precedence_and_missing_resources_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / "site-packages" / "agent_env_man"
            module = package / "commands" / "documentation.py"
            module.parent.mkdir(parents=True)
            root = package / "_documentation"
            root.mkdir()
            entry = root / "README.md"
            entry.write_text("local docs", encoding="utf-8")
            with patch.object(documentation, "__file__", str(module)):
                result = CliRunner().invoke(cli, ["--json", "docs"])
                self.assertEqual(result.exit_code, 0, result.output)
                self.assertEqual(json.loads(result.output), {"root": str(root), "entry": str(entry)})
                entry.unlink()
                result = CliRunner().invoke(cli, ["docs"])
                self.assertEqual(result.exit_code, 1)
                self.assertIn("documentation", result.output)
