"""Failure and recovery boundaries for settings files and saved ownership."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent_env_man.model import Error
from agent_env_man.settings import Bundle, recover_group, transaction
from agent_env_man.storage import State, observation


class SettingsSafety(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="aem-settings-safety-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.state = State(self.root / "state")
        self.state.data["items"]["unselected"] = {"mode": "copy", "opaque": "keep"}
        self.state.save()
        self.target = self.root / "config.toml"
        self.target.write_bytes(b"count = 1\n")

    def writes(self):
        return [(self.target, b"count = 2\n", observation(self.target))]

    def test_duplicate_writes_rejected_without_mutation(self):
        before = self.state.path.read_bytes()
        with self.assertRaisesRegex(Error, "Duplicate grouped"):
            transaction(self.state, self.writes() * 2, {})
        self.assertEqual(self.target.read_bytes(), b"count = 1\n")
        self.assertEqual(self.state.path.read_bytes(), before)
        self.assertFalse(list(self.root.glob(".aem-*")))

    def test_stale_read_rejected_even_in_preview(self):
        writes = self.writes()
        self.target.write_bytes(b"user edit\n")
        before = self.state.path.read_bytes()
        for preview in (False, True):
            with self.subTest(preview=preview), self.assertRaisesRegex(Error, "changed after reading"):
                transaction(self.state, writes, {}, dry_run=preview)
        self.assertEqual(self.target.read_bytes(), b"user edit\n")
        self.assertEqual(self.state.path.read_bytes(), before)

    def test_preview_preserves_files_and_ownership(self):
        before = self.state.path.read_bytes()
        transaction(self.state, self.writes(), {"new": {"mode": "settings"}}, dry_run=True)
        self.assertEqual(self.target.read_bytes(), b"count = 1\n")
        self.assertEqual(self.state.path.read_bytes(), before)
        self.assertFalse(list(self.root.glob(".aem-*")))

    def test_failed_stage_creation_preserves_existing_target_and_state(self):
        before = self.state.path.read_bytes()
        with patch("agent_env_man.settings.atomic_write", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                transaction(self.state, self.writes(), {"new": {"mode": "settings"}})
        self.assertEqual(self.target.read_bytes(), b"count = 1\n")
        self.assertEqual(self.state.path.read_bytes(), before)
        self.assertFalse(list(self.root.glob(".aem-*")))

    def test_failed_journal_save_cleans_prepared_files(self):
        before = self.state.path.read_bytes()
        with patch.object(self.state, "save", side_effect=OSError("journal failed")):
            with self.assertRaisesRegex(OSError, "journal failed"):
                transaction(self.state, self.writes(), {})
        self.assertEqual(self.target.read_bytes(), b"count = 1\n")
        self.assertEqual(self.state.path.read_bytes(), before)
        self.assertFalse(list(self.root.glob(".aem-stage-*")))
        self.assertFalse(list(self.root.glob("*.aem-backup-*")))

    def test_failed_state_commit_restores_group_and_all_ownership(self):
        missing = self.root / "new.json"
        writes = self.writes() + [(missing, b"{}\n", observation(missing))]
        original_items = deepcopy(self.state.data["items"])
        save = self.state.save
        calls = 0

        def fail_commit_once():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("state commit failed")
            save()

        with patch.object(self.state, "save", side_effect=fail_commit_once):
            with self.assertRaisesRegex(OSError, "state commit failed"):
                transaction(self.state, writes, {"new": {"mode": "settings"}})
        self.assertEqual(self.target.read_bytes(), b"count = 1\n")
        self.assertFalse(missing.exists())
        durable = State(self.state.path.parent)
        self.assertEqual(durable.data["items"], original_items)
        self.assertIsNone(durable.data["pending"])
        self.assertFalse(list(self.root.glob(".aem-stage-*")))
        transaction(durable, self.writes(), {"new": {"mode": "settings"}})
        self.assertEqual(self.target.read_bytes(), b"count = 2\n")
        self.assertEqual(State(self.state.path.parent).data["items"]["unselected"], original_items["unselected"])

    def interrupted_entry(self, target=None):
        target = target or self.target
        before = observation(target)
        backup = target.with_name(target.name + ".aem-backup-test")
        if target.exists():
            target.rename(backup)
        target.write_bytes(b"new content\n")
        return {"target": str(target), "stage": str(target.with_name(".aem-stage-" + target.name)),
                "backup": str(backup), "before": before, "after": observation(target)}

    def journal(self, entries):
        self.state.data["pending"] = {"operation": "settings-group", "files": entries}
        self.state.save()

    def test_recovery_restores_existing_and_removes_new_file(self):
        entries = [self.interrupted_entry(), self.interrupted_entry(self.root / "new.json")]
        self.journal(entries)
        recover_group(self.state)
        self.assertEqual(self.target.read_bytes(), b"count = 1\n")
        self.assertFalse((self.root / "new.json").exists())
        self.assertIsNone(State(self.state.path.parent).data["pending"])
        self.assertEqual(self.state.data["items"]["unselected"]["opaque"], "keep")

    def test_invalid_later_journal_entry_prevents_all_rollback(self):
        mutations = [
            (None, "Incomplete"),
            ({"stage": str(self.root / "elsewhere/stage")}, "distinct siblings"),
            ({"stage": str(self.root / "second.json")}, "distinct siblings"),
            ({"stage": str(self.root / "wrong-name")}, "artifact paths"),
            ({"backup": str(self.root / "wrong-backup")}, "artifact paths"),
            ({"before": {"kind": "link", "to": "other"}}, "observation"),
            ({"after": {"kind": "file", "hash": 7}}, "observation"),
        ]
        entry = self.interrupted_entry()
        second = self.interrupted_entry(self.root / "second.json")
        for changes, message in mutations:
            with self.subTest(changes=changes):
                invalid = None if changes is None else dict(second, **changes)
                self.journal([entry, invalid])
                before = self.state.path.read_bytes()
                with self.assertRaisesRegex(Error, message):
                    recover_group(self.state)
                self.assertEqual(self.target.read_bytes(), b"new content\n")
                self.assertEqual(Path(entry["backup"]).read_bytes(), b"count = 1\n")
                self.assertEqual(self.state.path.read_bytes(), before)

    def test_overlapping_recovery_artifacts_preserved(self):
        entry = self.interrupted_entry()
        self.journal([entry, entry])
        with self.assertRaisesRegex(Error, "Overlapping settings recovery"):
            recover_group(self.state)
        self.assertEqual(self.target.read_bytes(), b"new content\n")
        self.assertTrue(Path(entry["backup"]).exists())

    def test_non_list_recovery_files_rejected(self):
        self.journal({})
        with self.assertRaisesRegex(Error, "Invalid grouped"):
            recover_group(self.state)
        self.assertEqual(self.target.read_bytes(), b"count = 1\n")

    def test_changed_stage_or_backup_blocks_entire_recovery(self):
        entry = self.interrupted_entry()
        backup = Path(entry["backup"])
        stage = Path(entry["stage"])
        for artifact in (stage, backup):
            with self.subTest(artifact=artifact):
                artifact.write_bytes(b"user edit\n")
                self.journal([entry])
                before = self.state.path.read_bytes()
                with self.assertRaisesRegex(Error, "preserve files and backups"):
                    recover_group(self.state)
                self.assertEqual(artifact.read_bytes(), b"user edit\n")
                self.assertEqual(self.target.read_bytes(), b"new content\n")
                self.assertEqual(self.state.path.read_bytes(), before)
                stage.unlink(missing_ok=True)
                backup.write_bytes(b"count = 1\n")


class SettingsMetadataSafety(unittest.TestCase):
    def test_invalid_saved_snapshots_and_formats_are_rejected(self):
        for snapshot in (None, {}, {"config": "", "management": "", "extra": ""}):
            with self.subTest(snapshot=snapshot), self.assertRaisesRegex(Error, "comparison base"):
                Bundle.from_snapshot(snapshot)
        for format in (None, [], "jsonc"):
            with self.subTest(format=format):
                with self.assertRaisesRegex(Error, "Unsupported settings format"):
                    Bundle.empty(format=format)
                with self.assertRaisesRegex(Error, "Unsupported settings format"):
                    Bundle.from_snapshot({"config": "", "management": ""}, format=format)

    def test_invalid_intent_metadata_rejected_before_use(self):
        cases = [
            ('version = true\n', "requires version"),
            ('version = 2\n', "requires version"),
            ('version = 1\nunknown = []\n', "requires version"),
            ('version = 1\ndeleted = "key"\n', "must be an array"),
            ('version = 1\nreleased = [[]]\n', "nonempty string arrays"),
            ('version = 1\ndeleted = [[1]]\n', "nonempty string arrays"),
            ('version = 1\ndeleted = [["key"], ["key"]]\n', "Duplicate metadata"),
            ('version = 1\ndeleted = [["key"]]\nreleased = [["key", "child"]]\n', "Overlapping"),
        ]
        for management, message in cases:
            with self.subTest(management=management), self.assertRaisesRegex(Error, message):
                Bundle.from_snapshot({"config": "", "management": management})

    def test_read_race_rejected_without_changing_source(self):
        with tempfile.TemporaryDirectory(prefix="aem-settings-read-") as directory:
            path = Path(directory) / "config.toml"
            path.write_bytes(b"count = 1\n")
            with patch("agent_env_man.settings.observation", side_effect=[observation(path), {"kind": "missing"}]):
                with self.assertRaisesRegex(Error, "changed while reading"):
                    Bundle.load(path)
            self.assertEqual(path.read_bytes(), b"count = 1\n")
