"""Native v2 syntax and migration boundaries, without catalog conversion."""

from copy import deepcopy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import tomlkit

from agent_env_man.git_source import Git
from agent_env_man.model import Config, Error
import test_skill_catalog as skill_tests


class CatalogV2(unittest.TestCase):
    setUp = skill_tests.SkillCatalog.setUp
    git = skill_tests.SkillCatalog.git
    commit = skill_tests.SkillCatalog.commit
    repository = skill_tests.SkillCatalog.repository
    save_catalog = skill_tests.SkillCatalog.save_catalog
    run_cli = skill_tests.SkillCatalog.run_cli
    bootstrap = skill_tests.SkillCatalog.bootstrap
    require_links = skill_tests.SkillCatalog.require_links

    def document(self):
        return {'version': 2, 'sources': {'tools': {'type': 'git', 'repository': str(self.repo)}},
                'skills': {'report': {'source': 'tools', 'subdir': 'skills/report'}}}

    def write(self, document):
        self.catalog.write_text(tomlkit.dumps(document), encoding='utf-8')

    def load(self, document, **machine):
        return Config(self.config, document={'version': 1, 'catalog': str(self.catalog),
                      'checkout_root': str(self.checkouts), 'roots': {'skills': str(self.destination)}, **machine},
                      catalog_document=document)

    def test_defaults_and_nested_installation_do_not_change_input(self):
        document = self.document()
        before = deepcopy(document)
        config = self.load(document)
        source = config.sources['report']
        self.assertEqual(source.path, self.checkouts / '.aem-repositories/tools')
        self.assertIsNone(source.branch)
        item, = config.declarations(source)
        self.assertEqual((item.mode, item.target), ('link', self.destination / 'report'))
        self.assertEqual(config.update_policies()['report']['trigger'], ['manual'])
        self.assertEqual(config.full_update_policies()['report']['trigger'], ['shell-start', 'agent-start', 'interval'])
        document['skills']['report']['install'] = {'root': 'skills', 'mode': 'copy'}
        config = self.load(document)
        self.assertEqual(config.declarations(config.sources['report'])[0].mode, 'copy')
        document['skills']['report'].pop('install')
        self.assertEqual(document, before)

    def test_shared_names_and_equal_urls_have_distinct_checkout_identity(self):
        document = self.document()
        document['sources']['independent'] = dict(document['sources']['tools'])
        document['skills']['sibling'] = dict(document['skills']['report'])
        document['skills']['separate'] = {'source': 'independent', 'subdir': 'skills/report'}
        for entry in document['skills'].values():
            entry['install'] = {'mode': 'copy'}
        self.write(document)
        report = self.bootstrap()
        paths = {entry['skill']: entry['checkout'] for entry in report['skills']}
        self.assertEqual(paths['report'], paths['sibling'])
        self.assertNotEqual(paths['report'], paths['separate'])
        self.run_cli('apply')
        self.assertEqual(len(self.run_cli('update')), 3)

    def test_instruction_only_external_binding_and_install_defaults(self):
        external = self.root / 'external'
        (external / 'guidance').mkdir(parents=True)
        (external / 'guidance/start.md').write_text('Read rules', encoding='utf-8')
        document = {'version': 2, 'sources': {'documents': {'type': 'external'}},
                    'instructions': {'personal': {'source': 'documents', 'subdir': 'guidance', 'entry': 'start.md',
                                     'install': {'entry': {'root': 'agent'}}}}}
        config = self.load(document, external_paths={'documents': str(external)},
                           roots={'agent': str(self.root / 'agent')})
        self.assertEqual(config.external_names, {'documents'})
        source = config.sources['personal']
        bundle, entry, hook = config.declarations(source)
        self.assertEqual(bundle.target, self.root / 'machine.toml.bundles/personal')
        self.assertEqual(entry.source, external / 'guidance/start.md')
        self.assertEqual(entry.target, self.root / 'agent/AGENTS.md')
        self.assertEqual(hook.target, self.root / 'agent/hooks.json')
        document['instructions']['personal']['install']['bundle'] = {'root': 'custom', 'destination': 'guidance'}
        config = self.load(document, external_paths={'documents': str(external)},
                           roots={'agent': str(self.root / 'agent'), 'custom': str(self.root / 'custom')})
        self.assertEqual(config.declarations(config.sources['personal'])[0].target, self.root / 'custom/guidance')
        with self.assertRaisesRegex(Error, 'missing machine external_paths.documents'):
            self.load(document, roots={'agent': str(self.root / 'agent'), 'custom': str(self.root / 'custom')}).catalog()

    def test_strict_schema_rejects_legacy_fields_wrong_types_and_unknown_references(self):
        cases = []
        def changed(path, value):
            candidate = self.document()
            target = candidate
            for component in path[:-1]:
                target = target[component]
            target[path[-1]] = value
            cases.append(candidate)
        for version in (1, True, 2.0, '2', None):
            changed(('version',), version)
        for field in ('repositories', 'externals', 'unknown'):
            changed((field,), {})
        for field in ('repo', 'external', 'type', 'repository', 'branch', 'root', 'mode', 'entry', 'unknown'):
            changed(('skills', 'report', field), 'tools')
        for value in ('absent', None, 1, [], {}):
            changed(('skills', 'report', 'source'), value)
        for value in ({}, {'type': 'git'}, {'type': 'external', 'repository': str(self.repo)},
                      {'type': 'external', 'branch': 'main'}, {'type': 'git', 'path': '/tmp'},
                      {'type': 'unknown'}, [], {'type': 'git', 'repository': 1},
                      {'type': 'git', 'repository': str(self.repo), 'branch': 1}):
            changed(('sources', 'tools'), value)
        for value in ([], None, {'destination': 'report'}, {'mode': 'other'}, {'root': 1}):
            changed(('skills', 'report', 'install'), value)
        changed(('sources',), [])
        changed(('skills',), [])
        changed(('instructions',), [])
        changed(('updates',), {'unknown': {}})
        changed(('updates',), {'policies': []})
        changed(('sources', 'tools'), {'type': 'external'})
        for candidate in cases:
            with self.subTest(candidate=candidate), patch.object(Git, 'run', side_effect=AssertionError('Unexpected Git')):
                with self.assertRaises(Error):
                    self.load(candidate).catalog()

    def test_instruction_schema_rejects_flat_install_fields_and_skill_name_collision(self):
        document = self.document()
        document['instructions'] = {'personal': {'source': 'tools', 'entry': 'start.md',
                                  'install': {'entry': {'root': 'agent'}}}}
        invalid = []
        for field in ('repo', 'external', 'root', 'destination', 'entry_root', 'entry_destination', 'update'):
            value = deepcopy(document)
            value['instructions']['personal'][field] = 'agent'
            invalid.append(value)
        for install in ([], {'mode': 'copy'}, {'bundle': {'mode': 'copy'}}, {'entry': {'entry_root': 'agent'}},
                        {'bundle': []}, {'entry': {'destination': '../escape'}}):
            value = deepcopy(document)
            value['instructions']['personal']['install'] = install
            invalid.append(value)
        for entry in ('../escape', '/absolute', 'guidance/../start.md', None):
            value = deepcopy(document)
            value['instructions']['personal']['entry'] = entry
            invalid.append(value)
        value = deepcopy(document)
        value['instructions']['report'] = value['instructions'].pop('personal')
        invalid.append(value)
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(Error):
                self.load(value, roots={'skills': str(self.destination), 'agent': str(self.root / 'agent')}).catalog()

    def test_trigger_arrays_and_precedence_keep_json_and_full_exclusions(self):
        document = self.document()
        for field in ('defaults', 'named', 'skill'):
            for trigger in ('manual', 'agent-start', ['manual'], ['manual', 'agent-start'],
                            ['agent-start', 'agent-start'], [False], None, {}):
                value = deepcopy(document)
                policy = {'trigger': trigger}
                if field == 'defaults':
                    value['updates'] = {'defaults': policy}
                elif field == 'named':
                    value['updates'] = {'policies': {'unused': policy}}
                else:
                    value['skills']['report']['update'] = policy
                with self.subTest(field=field, trigger=trigger), self.assertRaisesRegex(Error, 'trigger must be an array'):
                    self.load(value).catalog()
        document['updates'] = {'defaults': {'trigger': [], 'timeout': 8, 'min_interval': 2},
                               'policies': {'observe': {'action': 'check', 'trigger': ['agent-start']}}}
        document['skills']['report']['update'] = {'policy': 'observe', 'timeout': 3}
        config = self.load(document)
        self.assertEqual(config.update_policies()['report'],
                         {'trigger': ['agent-start'], 'action': 'check', 'timeout': 3, 'min_interval': 2})
        document['skills']['report']['update']['trigger'] = []
        for policies in (self.load(document).update_policies(), self.load(document).full_update_policies()):
            self.assertEqual(policies['report']['trigger'], ['manual'])
        del document['skills']['report']['update']
        self.assertEqual(self.load(document).full_update_policies()['report']['trigger'], ['manual'])
        del document['updates']['defaults']['trigger']
        self.assertEqual(self.load(document).full_update_policies()['report']['trigger'],
                         ['shell-start', 'agent-start', 'interval'])
        self.assertEqual(document['updates']['policies']['observe']['trigger'], ['agent-start'])

    def test_toml_source_collision_is_rejected_without_network_or_machine_writes(self):
        self.catalog.write_text('version = 2\n[sources.documents]\ntype = "git"\n'
                                'repository = "https://example.test/tools.git"\n'
                                '[sources.documents]\ntype = "external"\n', encoding='utf-8')
        with patch.object(Git, 'run', side_effect=AssertionError('Unexpected Git')):
            self.bootstrap(code=1)
        self.assertFalse(self.config.exists())
        self.assertFalse(self.checkouts.exists())

    def test_old_catalog_rejected_but_saved_maintenance_and_hooks_remain_offline(self):
        self.require_links()
        document = self.document()
        document['instructions'] = {'personal': {'source': 'tools', 'entry': 'skills/report/SKILL.md',
                                  'install': {'entry': {'root': 'agent'}}}}
        self.write(document)
        self.run_cli('bootstrap', '--catalog', self.catalog, '--checkout-root', self.checkouts,
                     '--root', f'skills={self.destination}', '--root', f'agent={self.root / "agent"}')
        self.run_cli('apply')
        state_path = Path(str(self.config) + '.state/state.json')
        before = state_path.read_bytes()
        self.write({'version': 1, 'skills': {'report': {'type': 'git', 'repository': str(self.repo),
                                                      'subdir': 'skills/report'}}})
        with patch.object(Git, 'run', side_effect=AssertionError('Unexpected Git')):
            self.assertIn('version = 2', self.run_cli('apply', code=1))
            self.assertIn('Manually migrate', self.run_cli('update', code=1))
            self.run_cli('locate', 'report')
            self.run_cli('locate', 'personal')
            self.run_cli('agent-hook', 'personal', '--agent', 'codex')
            report = self.run_cli('status')
            self.assertIn('catalog_error', report)
            self.assertEqual(state_path.read_bytes(), before)
            self.run_cli('recover')
            self.run_cli('detach', 'report', 'personal:bundle', 'personal:entry')
            self.assertFalse((self.destination / 'report').is_symlink())
            self.run_cli('locate', 'personal')
        saved = json.loads(state_path.read_text())
        self.assertEqual(saved['version'], 2)
        self.assertTrue((self.checkouts / '.aem-repositories/tools/.git').is_dir())

    def test_named_v1_installation_keeps_paths_and_ownership_after_syntax_change(self):
        self.require_links()
        document = self.document()
        self.write(document)
        self.bootstrap()
        self.run_cli('apply')
        state_path = Path(str(self.config) + '.state/state.json')
        original = json.loads(state_path.read_text())
        target = self.destination / 'report'
        checkout = self.checkouts / '.aem-repositories/tools'
        # v1 named sources used the same private model and saved envelope.
        self.write({'version': 1, 'repositories': {'tools': {'repository': str(self.repo)}},
                    'skills': {'report': {'repo': 'tools', 'subdir': 'skills/report'}}})
        self.assertIn('version = 2', self.run_cli('apply', code=1))
        self.write(document)
        self.assertTrue(all(entry['action'] == 'record' for entry in self.run_cli('apply')))
        current = json.loads(state_path.read_text())
        self.assertEqual(current['items'], original['items'])
        self.assertEqual(target.resolve(), checkout / 'skills/report')

    def test_former_direct_installation_requires_detach_preserves_checkout_and_backup(self):
        self.require_links()
        self.write(self.document())
        self.bootstrap()
        self.run_cli('apply')
        state_path = Path(str(self.config) + '.state/state.json')
        state = json.loads(state_path.read_text())
        named = self.checkouts / '.aem-repositories/tools'
        direct = self.checkouts / 'report'
        named.rename(direct)
        # Recreate the released direct-declaration record and link; its state
        # model is unchanged, only the source checkout path differs.
        target = self.destination / 'report'
        target.unlink()
        target.symlink_to(direct / 'skills/report', target_is_directory=True)
        item = state['items']['report']
        item['source'] = str(direct / 'skills/report')
        state_path.write_text(json.dumps(state), encoding='utf-8')
        self.write({'version': 1, 'skills': {'report': {'type': 'git', 'repository': str(self.repo),
                                                      'subdir': 'skills/report'}}})
        self.run_cli('detach', 'report')
        (target / 'SKILL.md').write_text('Preserved local edit', encoding='utf-8')
        self.write(self.document())
        self.bootstrap()
        self.assertEqual(self.run_cli('apply'), [])
        self.run_cli('apply', '--item', 'report', '--reattach', code=1)
        self.run_cli('apply', '--item', 'report', '--reattach', '--replace')
        self.assertEqual(target.resolve(), named / 'skills/report')
        self.assertTrue((direct / '.git').is_dir())
        backups = list(self.destination.glob('report.aem-backup-*'))
        self.assertTrue(backups)
        self.assertIn('Preserved local edit', [(backup / 'SKILL.md').read_text() for backup in backups])
