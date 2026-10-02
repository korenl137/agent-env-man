"""Failed atomic writes preserve the destination and remove temporary files."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent_env_man.model import Error
from agent_env_man.storage import atomic_write, fingerprint


class StorageSafety(unittest.TestCase):
    def test_atomic_write_failure_preserves_target_and_cleans_temporary_file(self):
        with tempfile.TemporaryDirectory(prefix="aem-atomic-write-") as directory:
            target = Path(directory) / "state.json"
            target.write_bytes(b"original\n")
            for operation in ("fsync", "chmod", "replace"):
                with self.subTest(operation=operation), patch(
                        "agent_env_man.storage.os." + operation, side_effect=OSError("write failed")):
                    with self.assertRaisesRegex(OSError, "write failed"):
                        atomic_write(target, b"replacement\n")
                self.assertEqual(target.read_bytes(), b"original\n")
                self.assertEqual(list(target.parent.iterdir()), [target])
            atomic_write(target, b"replacement\n")
            self.assertEqual(target.read_bytes(), b"replacement\n")

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO payload fixture requires POSIX")
    def test_fingerprint_rejects_special_files_without_reading_them(self):
        with tempfile.TemporaryDirectory(prefix="aem-special-file-") as directory:
            root = Path(directory)
            fifo = root / "pipe"
            os.mkfifo(fifo)
            with self.assertRaisesRegex(Error, "Special files are unsupported"):
                fingerprint(root)
            self.assertTrue(fifo.exists())
