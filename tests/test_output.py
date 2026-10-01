"""Presentation contracts and callback compatibility at the CLI boundary."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

from agent_env_man.cli import main, parser
from agent_env_man.output import format_report


class OutputTests(unittest.TestCase):
    def test_nested_reports_preserve_paths_failures_and_notices(self):
        report = {"items": [{"item": "한글-skill", "status": "conflict",
                             "target": "/path with spaces/SKILL.md",
                             "error": "first line\nsecond line"}],
                  "pending": None, "failed": True, "outcomes": [],
                  "notice": "Review /hooks"}
        text = format_report(report)
        self.assertIn("items:\n  - item: 한글-skill\n    status: conflict", text)
        self.assertIn("target: /path with spaces/SKILL.md", text)
        self.assertIn("error: first line\n           second line", text)
        self.assertIn("pending: none", text)
        self.assertIn("failed: yes", text)
        self.assertIn("outcomes: none", text)
        self.assertIn("notice: Review /hooks", text)

    def test_empty_and_scalar_lists(self):
        self.assertEqual(format_report([]), "none")
        self.assertEqual(format_report({}), "none")
        self.assertEqual(format_report({"names": ["one", "two"]}), "names:\n  - one\n  - two")

    def test_json_flag_at_each_parser_level(self):
        for args in (["--json", "status"], ["status", "--json"],
                     ["--json", "catalog", "status"], ["catalog", "--json", "status"],
                     ["catalog", "status", "--json"], ["self", "status", "--json"]):
            with self.subTest(args=args):
                self.assertTrue(parser().parse_args(args).json)

    def test_default_text_and_explicit_json_share_report(self):
        with tempfile.TemporaryDirectory() as directory:
            config = str(Path(directory) / "machine.toml")
            reports = []
            for flags in ([], ["--json"]):
                output = io.StringIO()
                with redirect_stdout(output):
                    code = main(["--config", config, "self", "status", *flags])
                self.assertEqual(code, 0)
                reports.append(output.getvalue())
            self.assertEqual(reports[0], format_report(json.loads(reports[1])) + "\n")

    def test_startup_retains_json_without_flag(self):
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--config", str(Path(directory) / "machine.toml"),
                             "startup", "--trigger", "shell-start"])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.getvalue()), {})
