"""Offline editing lookup distinguishes sources from installed copies."""

import json
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

from agent_env_man.git_source import Git
import test_publish as publication_tests


class Locate(unittest.TestCase):
    setUp = publication_tests.Publication.setUp
    git = publication_tests.Publication.git
    commit = publication_tests.Publication.commit
    cli = publication_tests.Publication.cli
    edit = publication_tests.Publication.edit

    def require_links(self):
        probe = self.root / "probe"
        try:
            probe.symlink_to(self.catalog)
        except OSError:
            self.skipTest("Symbolic link capability unavailable")
        probe.unlink()

    def test_prepared_skill_and_instruction_lookup_is_offline_and_read_only(self):
        state = self.root / 'machine.toml.state/state.json'
        before = state.read_bytes()
        self.remote.rename(self.root / 'offline.git')
        with patch.object(Git, 'fetch', side_effect=AssertionError('Unexpected fetch')):
            skill = self.cli('locate', 'one')
            instruction = self.cli('locate', 'personal')
        self.assertEqual(skill['root'], str(self.checkout / 'skill'))
        self.assertEqual(skill['entry'], str(self.checkout / 'skill/SKILL.md'))
        self.assertEqual(skill['checkout'], str(self.checkout))
        self.assertEqual(skill['members'], ['one', 'personal', 'two'])
        self.assertIsNone(skill['installed_root'])
        self.assertEqual(instruction['entry'], str(self.checkout / 'AGENTS.md'))
        self.assertEqual(state.read_bytes(), before)
        self.assertIn('not been installed', self.cli('agent-hook', 'personal', '--agent', 'codex')[
            'stopReason'])

    def test_copy_lookup_and_explicit_source_remain_distinct_after_detach(self):
        self.cli('apply', '--item', 'one')
        installed = self.root / 'installed/one'
        self.assertEqual(self.cli('locate', 'one')['root'], str(installed))
        source = self.cli('locate', 'one', '--source')
        self.assertEqual(source['root'], str(self.checkout / 'skill'))
        Path(source['entry']).write_text('# Edited at source\n', encoding='utf-8')
        self.cli('publish', 'one', '-m', 'Edit located source')
        self.assertEqual(self.git(self.remote, 'show', 'main:skill/SKILL.md'), '# Edited at source')
        self.assertEqual((installed / 'SKILL.md').read_text(), '# Skill\n')
        self.cli('detach', 'one')
        self.assertTrue(self.cli('locate', 'one')['detached'])
        self.assertEqual(self.cli('locate', 'one', '--source')['root'], source['root'])
        self.catalog.unlink()
        shutil.rmtree(self.checkout)
        self.assertEqual(self.cli('locate', 'one')['root'], str(installed))
        self.cli('locate', 'one', '--source', code=1)

    def test_installed_link_and_replaced_copy_do_not_silently_fall_back(self):
        self.require_links()
        import tomlkit

        self.document['skills']['one'].setdefault('install', {})['mode'] = 'link'
        self.catalog.write_text(tomlkit.dumps(self.document), encoding='utf-8')
        self.cli('apply', '--item', 'one')
        target = self.root / 'installed/one'
        self.assertEqual(self.cli('locate', 'one')['root'], str(self.checkout / 'skill'))
        target.unlink()
        target.mkdir()
        self.assertIn('replaced', self.cli('locate', 'one', code=1))
        self.assertEqual(self.cli('locate', 'one', '--source')['root'], str(self.checkout / 'skill'))

    def test_source_requires_prepared_valid_entry_but_accepts_dirty_work(self):
        self.edit()
        self.cli('locate', 'one', '--source')
        (self.checkout / 'skill/SKILL.md').unlink()
        self.assertIn('missing', self.cli('locate', 'one', code=1))
        self.cli('locate', 'unknown', code=1)
        shutil.rmtree(self.checkout)
        self.assertIn('bootstrap', self.cli('locate', 'personal', code=1))

    def test_redirected_source_entry_is_rejected(self):
        self.require_links()
        entry = self.checkout / 'skill/SKILL.md'
        entry.unlink()
        entry.symlink_to(self.checkout / 'AGENTS.md')
        self.assertIn('symlink', self.cli('locate', 'one', code=1))

    def test_detached_instruction_lookup_can_explicitly_find_publish_source(self):
        self.require_links()
        self.cli('apply', '--item', 'personal:entry')
        self.cli('detach', 'personal:bundle', 'personal:entry')
        saved = self.cli('locate', 'personal')
        source = self.cli('locate', 'personal', '--source')
        self.assertTrue(saved['detached'])
        self.assertFalse(source['detached'])
        self.assertNotEqual(saved['root'], source['root'])
        self.assertEqual(source['checkout'], str(self.checkout))

    def test_saved_copy_survives_old_state_and_invalid_catalog_fields(self):
        self.cli('apply', '--item', 'one')
        state = self.root / 'machine.toml.state/state.json'
        data = json.loads(state.read_text())
        data['version'] = 1
        state.write_text(json.dumps(data))
        with self.config.open('a') as output:
            output.write('\n[obsolete]\nkeep = true\n')
        self.catalog.unlink()
        before = state.read_bytes()
        self.assertEqual(self.cli('locate', 'one')['root'], str(self.root / 'installed/one'))
        self.assertEqual(state.read_bytes(), before)
