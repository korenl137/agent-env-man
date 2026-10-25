"""Settings deletions preserve unrelated values and their source tokens."""

import unittest

from agent_env_man.model import Error
from agent_env_man.settings_formats import TomlFormat


class TomlDeletionSafety(unittest.TestCase):
    def test_scalar_parent_preserved_when_nested_delete_is_noop_or_write_conflicts(self):
        for scalar in ('1_000', 'true', '"private"', '[1, 2]'):
            with self.subTest(scalar=scalar):
                original = '# user settings\r\nparent = ' + scalar + '\r\nlocal = "\\u0061"\n'
                document = TomlFormat.parse(original)
                TomlFormat.put(document, ('parent', 'child'), delete=True)
                self.assertEqual(TomlFormat.dump(document), original)
                with self.assertRaisesRegex(Error, 'Field structure conflict'):
                    TomlFormat.put(document, ('parent', 'child'), 2)
                self.assertEqual(TomlFormat.dump(document), original)

    def test_deleting_last_nested_child_retains_nonempty_parent_and_sibling_tokens(self):
        sibling = 'keep = "\\u0061" # user spelling\n'
        original = '[parent]\n' + sibling + '\n[parent.nested]\nvalue = 1\n'
        document = TomlFormat.parse(original)
        TomlFormat.put(document, ('parent', 'nested', 'value'), delete=True)
        self.assertEqual(document.unwrap(), {'parent': {'keep': 'a'}})
        result = TomlFormat.dump(document)
        self.assertIn('[parent]\n', result)
        self.assertIn(sibling, result)
        self.assertNotIn('[parent.nested]', result)
