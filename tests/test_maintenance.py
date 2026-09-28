"""Teardown consumes saved ownership, not obsolete installation declarations."""

import json
import os
from pathlib import Path
from unittest.mock import patch

import tomlkit

from agent_env_man import hooks
from agent_env_man.git_source import Git
from agent_env_man.storage import observation
from test_setup import SetupFixture


class Maintenance(SetupFixture):
    def load_saved(self):
        return json.loads(Path(str(self.config) + '.state/state.json').read_text())

    def save_state(self, data):
        Path(str(self.config) + '.state/state.json').write_text(json.dumps(data), encoding='utf-8')

    def obsolete(self):
        doc = tomlkit.parse(self.config.read_text())
        doc['sources'] = {'retired': {'anything': ['opaque']}}
        doc['unknown'] = {'keep': 'untouched'}
        doc['catalog'] = str(self.root / 'missing-catalog.toml')
        doc['roots'] = 'unusable'
        doc.setdefault('setup', {})['executable'] = 'not an absolute path'
        self.config.write_text(tomlkit.dumps(doc), encoding='utf-8')
        state = self.load_saved()
        state['version'] = 1
        state['future'] = {'keep': ['opaque']}
        for record in state['items'].values():
            if record.get('mode') == 'agent-hook':
                record['mode'] = 'codex-hook'
        # Even an opaque unselected item's body must survive maintenance.
        state['items']['opaque'] = {'mode': 'retired', 'detached': True, 'unfamiliar': [1, 2]}
        self.save_state(state)
        return state

    def test_old_link_detach_and_locator_without_catalog_or_valid_fields(self):
        self.configure()
        self.run_cli('apply')
        original = self.obsolete()
        before_config = self.config.read_bytes()
        hook_file = self.agent / 'hooks.json'
        before_hooks = hook_file.read_bytes()
        with patch.object(Git, 'run', side_effect=AssertionError('No Git during maintenance')):
            self.assertIn('root', self.run_cli('locate', 'personal'))
            self.assertIn('hookSpecificOutput', self.run_cli('agent-hook', 'personal', '--agent', 'codex'))
            preview = self.run_cli('detach', 'personal:bundle', 'personal:entry', '--dry-run')
            self.assertEqual(len(preview), 3)
            self.assertEqual(self.load_saved(), original)
            self.run_cli('detach', 'personal:bundle', 'personal:entry')
            self.assertTrue(self.run_cli('locate', 'personal')['detached'])
        state = self.load_saved()
        self.assertEqual(state['version'], 1)
        self.assertEqual(state['future'], original['future'])
        self.assertEqual(state['items']['opaque'], original['items']['opaque'])
        self.assertTrue(state['items']['personal:hook']['detached'])
        self.assertFalse((self.agent / 'AGENTS.md').is_symlink())
        self.assertEqual(hook_file.read_bytes(), before_hooks)
        self.assertEqual(self.config.read_bytes(), before_config)

    def test_offline_status_reports_saved_ids_and_observations(self):
        self.setup_cli('--shell', 'bash')
        self.obsolete()
        before = Path(str(self.config) + '.state/state.json').read_bytes()
        with patch.object(Git, 'run', side_effect=AssertionError('No fetch')):
            result = self.run_cli('status')
        self.assertTrue(result['saved_only'])
        self.assertEqual(result['state_version'], 1)
        items = {i['item']: i for i in result['items']}
        self.assertEqual(items['setup:shell-bash']['observation']['kind'], 'file')
        self.assertIn('error', items['opaque'])
        self.assertIn('configuration_error', result)
        self.assertEqual(Path(str(self.config) + '.state/state.json').read_bytes(), before)
        self.run_cli('status', '--refresh', code=1)

    def test_remove_only_preserves_other_integrations_and_unknown_document(self):
        self.setup_cli('--shell', 'bash', '--shell', 'zsh', '--agent', 'codex')
        original = self.obsolete()
        zsh = self.home / '.zshrc'
        zsh.write_text(zsh.read_text() + '# unrelated local edit\n')
        before_zsh = zsh.read_bytes()
        before_hooks = (self.home / '.codex/hooks.json').read_bytes()
        self.executable.unlink()
        with patch.object(Git, 'run', side_effect=AssertionError('No Git')), \
                patch('agent_env_man.agents.Codex.definition', side_effect=AssertionError('No regeneration')):
            self.setup_cli('--remove-shell', 'bash', '--dry-run')
            self.assertEqual(self.load_saved(), original)
            result = self.setup_cli('--remove-shell', 'bash')
        self.assertEqual([i['integration'] for i in result['integrations']], ['shell:bash'])
        self.assertNotIn('AEM', (self.home / '.bashrc').read_text())
        self.assertEqual(zsh.read_bytes(), before_zsh)
        self.assertEqual((self.home / '.codex/hooks.json').read_bytes(), before_hooks)
        doc = tomlkit.parse(self.config.read_text())
        self.assertEqual(doc['unknown']['keep'], 'untouched')
        self.assertIn('sources', doc)
        self.assertEqual(doc['roots'], 'unusable')
        self.assertNotIn('bash', doc['setup']['shells'])
        state = self.load_saved()
        self.assertEqual(state['version'], 1)
        self.assertEqual(state['items']['setup:agent-codex'], original['items']['setup:agent-codex'])
        self.setup_cli('--remove-shell', 'bash')  # Repeated removal is harmless.

    def test_saved_old_hook_removed_without_profile_or_mode_interpretation(self):
        self.setup_cli('--agent', 'codex')
        path = self.home / '.codex/hooks.json'
        document = json.loads(path.read_text())
        unrelated = {'hooks': [{'type': 'command', 'command': 'echo user'}]}
        document['hooks']['SessionStart'].append(unrelated)
        document['extra'] = {'keep': True}
        path.write_text(json.dumps(document))
        self.obsolete()
        with patch('agent_env_man.agents.Codex.definition', side_effect=AssertionError('No profile synthesis')):
            self.run_cli('setup', '--remove-agent', 'codex')
        self.assertEqual(json.loads(path.read_text()), {'hooks': {'SessionStart': [unrelated]}, 'extra': {'keep': True}})
        self.assertTrue(self.load_saved()['items']['setup:agent-codex']['detached'])
        self.assertEqual(self.load_saved()['items']['setup:agent-codex']['mode'], 'codex-hook')

    def test_retired_agent_and_shell_names_can_be_removed(self):
        self.setup_cli('--shell', 'bash', '--agent', 'codex')
        state = self.obsolete()
        state['items']['setup:shell-retired-shell'] = state['items'].pop('setup:shell-bash')
        state['items']['setup:agent-retired-agent'] = state['items'].pop('setup:agent-codex')
        self.save_state(state)
        document = tomlkit.parse(self.config.read_text())
        document['setup']['shells']['retired-shell'] = document['setup']['shells'].pop('bash')
        document['agents']['retired-agent'] = document['agents'].pop('codex')
        self.config.write_text(tomlkit.dumps(document))
        self.run_cli('setup', '--remove-shell', 'retired-shell', '--remove-agent', 'retired-agent')
        self.assertNotIn('AEM', (self.home / '.bashrc').read_text())
        self.assertEqual(json.loads((self.home / '.codex/hooks.json').read_text())['hooks']['SessionStart'], [])
        self.assertTrue(self.load_saved()['items']['setup:agent-retired-agent']['detached'])

    def test_opaque_regular_item_detach_checks_readability_and_preserves_bytes(self):
        self.setup_cli('--shell', 'bash')
        state = self.obsolete()
        target = self.root / 'settings.toml'
        target.write_text('# unmanaged and managed values\nx = 1\n')
        record = {'mode': 'unknown-merge-mode', 'target': str(target), 'future': {'owned': ['x']}}
        state['items']['settings'] = record
        self.save_state(state)
        before = target.read_bytes()
        self.run_cli('detach', 'settings')
        self.assertEqual(target.read_bytes(), before)
        self.assertEqual(self.load_saved()['items']['settings'], {**record, 'detached': True})

    def test_missing_or_redirected_target_does_not_release_ownership(self):
        self.require_links()
        self.setup_cli('--shell', 'bash')
        state = self.obsolete()
        folder = self.root / 'real'
        folder.mkdir()
        target = folder / 'data'
        target.write_text('keep')
        redirect = self.root / 'redirect'
        redirect.symlink_to(folder, target_is_directory=True)
        for value in (str(self.root / 'missing'), str(redirect / 'data'), 'relative'):
            state['items']['selected'] = {'target': value, 'mode': 'opaque'}
            self.save_state(state)
            self.run_cli('detach', 'selected', code=1)
            self.assertEqual(self.load_saved(), state)
        self.assertEqual(target.read_text(), 'keep')

    def test_edited_selected_hook_blocks_all_removal_writes(self):
        self.setup_cli('--shell', 'bash', '--agent', 'codex')
        self.obsolete()
        path = self.home / '.codex/hooks.json'
        doc = json.loads(path.read_text())
        doc['hooks']['SessionStart'][0]['hooks'][0]['command'] = 'echo edited'
        path.write_text(json.dumps(doc))
        paths = [self.config, self.home / '.bashrc', path, Path(str(self.config) + '.state/state.json')]
        before = {p: p.read_bytes() for p in paths}
        self.run_cli('setup', '--remove-shell', 'bash', '--remove-agent', 'codex', code=1)
        for p in paths:
            self.assertEqual(p.read_bytes(), before[p])

    def test_remove_agent_still_requires_detaching_managed_content(self):
        self.configure()
        self.run_cli('apply')
        self.setup_cli('--agent', 'codex')
        self.obsolete()
        self.run_cli('setup', '--remove-agent', 'codex', code=1)
        self.assertFalse(self.load_saved()['items']['setup:agent-codex']['detached'])

    def test_old_journal_recovery_preserves_state_version_and_user_edits(self):
        self.setup_cli('--shell', 'bash')
        state = self.obsolete()
        target, backup, stage = (self.root / n for n in ('target', 'backup', 'stage'))
        target.write_text('old')
        stage.write_text('new')
        state['pending'] = {'key': 'opaque', 'target': str(target), 'backup': str(backup), 'stage': str(stage),
                            'before': observation(target), 'after': observation(stage), 'opaque': True}
        self.save_state(state)
        os.replace(target, backup)
        os.replace(stage, target)
        target.write_text('user edit')
        self.run_cli('recover', code=1)
        self.assertEqual(target.read_text(), 'user edit')
        self.assertEqual(backup.read_text(), 'old')
        target.write_text('new')
        self.run_cli('recover')
        self.assertEqual(target.read_text(), 'old')
        self.assertEqual(self.load_saved()['version'], 1)
        self.assertIsNone(self.load_saved()['pending'])
        self.assertEqual(self.load_saved()['future'], state['future'])

    def test_incomplete_or_future_state_fails_without_target_changes(self):
        self.setup_cli('--shell', 'bash')
        state = self.obsolete()
        state['pending'] = {'target': str(self.home / '.bashrc')}
        self.save_state(state)
        before = (self.home / '.bashrc').read_bytes()
        self.run_cli('recover', code=1)
        self.run_cli('detach', 'setup:shell-bash', code=1)
        state['pending'] = {}
        self.save_state(state)
        self.run_cli('recover', code=1)
        self.run_cli('setup', '--remove-shell', 'bash', code=1)
        state['version'] = 999
        self.save_state(state)
        self.run_cli('status', code=1)
        self.run_cli('setup', '--remove-shell', 'bash', code=1)
        self.assertEqual((self.home / '.bashrc').read_bytes(), before)
        self.assertEqual(self.load_saved(), state)

    def test_partial_removal_retries_without_recreating_other_integrations(self):
        self.setup_cli('--shell', 'bash', '--agent', 'codex')
        self.obsolete()
        replace = os.replace

        def fail_machine(src, dst):
            if Path(dst) == self.config and Path(src).name.startswith('.aem-stage-'):
                raise OSError('injected machine write failure')
            return replace(src, dst)

        with patch('agent_env_man.manager.os.replace', side_effect=fail_machine):
            self.run_cli('setup', '--remove-shell', 'bash', code=1)
        self.assertTrue(self.load_saved()['items']['setup:shell-bash']['detached'])
        self.assertIn('bash', tomlkit.parse(self.config.read_text())['setup']['shells'])
        self.run_cli('setup', '--remove-shell', 'bash')
        self.assertNotIn('bash', tomlkit.parse(self.config.read_text())['setup']['shells'])
        self.assertEqual(self.load_saved()['version'], 1)

    def test_grouped_retired_hook_removals_preserve_other_groups(self):
        self.setup_cli('--agent', 'codex')
        state = self.obsolete()
        first = state['items']['setup:agent-codex']
        second = json.loads(json.dumps(first))
        second['agent'] = 'retired'
        second['agents'] = ['retired']
        second['hook_marker'] = 'AEM retired startup'
        second['hook_group']['hooks'][0]['statusMessage'] = second['hook_marker']
        state['items']['setup:agent-retired'] = second
        self.save_state(state)
        path = self.home / '.codex/hooks.json'
        doc = json.loads(path.read_text())
        unrelated = {'hooks': [{'command': 'user', 'type': 'command'}]}
        doc['hooks']['SessionStart'].extend([second['hook_group'], unrelated])
        path.write_text(json.dumps(doc))
        self.run_cli('setup', '--remove-agent', 'codex', '--remove-agent', 'retired')
        self.assertEqual(json.loads(path.read_text())['hooks']['SessionStart'], [unrelated])
        state = self.load_saved()
        self.assertTrue(state['items']['setup:agent-codex']['detached'])
        self.assertTrue(state['items']['setup:agent-retired']['detached'])
        self.assertEqual(len(list(path.parent.glob('hooks.json.aem-backup-*'))), 1)

    def test_concurrent_hook_edit_is_not_overwritten(self):
        self.setup_cli('--agent', 'codex')
        self.obsolete()
        path = self.home / '.codex/hooks.json'
        before_state = self.load_saved()
        original = hooks.read

        def edit_after_read(target):
            doc = original(target)
            altered = json.loads(json.dumps(doc))
            altered['concurrent'] = 'keep'
            target.write_text(json.dumps(altered))
            return doc

        with patch('agent_env_man.hooks.read', side_effect=edit_after_read):
            self.run_cli('setup', '--remove-agent', 'codex', code=1)
        self.assertEqual(json.loads(path.read_text())['concurrent'], 'keep')
        self.assertEqual(self.load_saved(), before_state)

    def test_detach_commit_failure_recovers_using_the_old_state_envelope(self):
        from agent_env_man.storage import State
        self.configure()
        self.run_cli('apply')
        self.obsolete()
        before_state = self.load_saved()
        save = State.save
        failed = False

        def fail_committing(state):
            nonlocal failed
            if (not failed and state.data['pending'] is None
                    and state.data['items']['personal:bundle'].get('detached')):
                failed = True
                raise OSError('injected state commit failure')
            return save(state)

        with patch.object(State, 'save', fail_committing):
            self.run_cli('detach', 'personal:bundle', code=1)
        self.assertTrue(failed)
        self.assertTrue((self.rules / 'personal').is_symlink())
        self.assertEqual(self.load_saved(), before_state)

    def test_mixed_addition_still_requires_current_configuration(self):
        self.setup_cli('--shell', 'bash')
        self.obsolete()
        before = (self.home / '.bashrc').read_bytes()
        self.run_cli('setup', '--remove-shell', 'bash', '--agent', 'codex', code=1)
        self.assertEqual((self.home / '.bashrc').read_bytes(), before)
        self.assertFalse(self.load_saved()['items']['setup:shell-bash']['detached'])
