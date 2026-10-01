"""Link ownership compares Windows spelling without following substituted aliases."""

import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agent_env_man import link_paths
from agent_env_man.storage import link_matches, observation


class LinkPaths(unittest.TestCase):
    def test_windows_extended_drive_and_unc_spellings(self):
        pairs = [(r"C:\source\file", r"\\?\C:\source\file"),
                 (r"\\server\share\file", r"\\?\UNC\server\share\file")]
        with patch.object(link_paths, "os", SimpleNamespace(name="nt")):
            for plain, extended in pairs:
                with self.subTest(plain=plain):
                    for actual, expected in ((plain, extended), (extended, plain)):
                        raw = {"kind": "link", "to": actual}
                        self.assertTrue(link_matches(raw, expected))
                        self.assertEqual(raw["to"], actual)

    def test_no_alias_resolution_or_posix_normalization(self):
        pairs = [(r"C:\other", r"C:\source"),
                 (r"C:\SOURCE", r"C:\source"),
                 (r"source", r"C:\source"),
                 (r"C:\alias\..\source", r"C:\source"),
                 (r"\\?\Volume{abc}\file", r"Volume{abc}\file"),
                 (r"\\.\C:\source", r"C:\source")]
        with patch.object(link_paths, "os", SimpleNamespace(name="nt")):
            for actual, expected in pairs:
                self.assertFalse(link_paths.same_destination(actual, expected))
            self.assertFalse(link_matches({"kind": "file", "to": "same"}, "same"))
            self.assertFalse(link_paths.same_destination(None, "same"))
        with patch.object(link_paths, "os", SimpleNamespace(name="posix")):
            self.assertFalse(link_paths.same_destination(r"\\?\C:\source", r"C:\source"))
            self.assertTrue(link_paths.same_destination("/source", "/source"))

    @unittest.skipUnless(os.name == "nt", "Native Windows link identity")
    def test_native_link_observation_is_raw_and_retargeting_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="aem-native-link-") as folder:
            root = Path(folder)
            source = root / "source"
            source.mkdir()
            target = root / "installed"
            try:
                target.symlink_to(source, target_is_directory=True)
            except OSError as exc:
                self.skipTest(str(exc))
            raw = observation(target)
            self.assertEqual(raw["to"], os.readlink(target))
            self.assertTrue(link_matches(raw, str(source)))
            alias = root / "alias"
            alias.symlink_to(source, target_is_directory=True)
            target.unlink()
            target.symlink_to(alias, target_is_directory=True)
            self.assertTrue(target.samefile(source))
            self.assertFalse(link_matches(observation(target), str(source)))
