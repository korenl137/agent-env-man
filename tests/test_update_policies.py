"""Policy composition is independent of catalog file paths and Git execution."""

import unittest

from agent_env_man.model import Error
from agent_env_man.updates import resolve_policies


class UpdatePolicies(unittest.TestCase):
    def test_global_named_and_skill_precedence(self):
        result = resolve_policies(
            {"defaults": {"trigger": ["shell-start", "interval"], "timeout": 10},
             "policies": {"observe": {"action": "check", "timeout": 20}}},
            {"first": {"type": "git", "update": {"policy": "observe", "timeout": 5}},
             "second": {"type": "git", "update": {"trigger": "manual"}},
             "third": {"type": "git"}})
        self.assertEqual(result["first"], {"trigger": ["shell-start", "interval"], "action": "check",
                                           "timeout": 5, "min_interval": 600})
        self.assertEqual(result["second"]["trigger"], ["manual"])
        self.assertEqual(result["third"]["action"], "sync")
        self.assertEqual(result["third"]["timeout"], 10)

    def test_invalid_fields_and_values_are_rejected_even_in_unused_policies(self):
        invalid = [None, [], "sync", {"unknown": 1}, {"trigger": []}, {"trigger": True},
                   {"trigger": ["manual", "shell-start"]}, {"trigger": ["interval", "interval"]},
                   {"trigger": [1]}, {"trigger": "startup"}, {"action": "fetch"}, {"action": []},
                   {"min_interval": -1}, {"min_interval": True}, {"timeout": False},
                   {"timeout": 0}, {"timeout": "5"}, {"timeout": float("inf")},
                   {"min_interval": float("nan")}, {"policy": "recursive"}]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(Error):
                resolve_policies({"policies": {"unused": value}}, {"skill": {"type": "git"}})

    def test_unknown_policies_shapes_and_unsupported_sources_are_rejected(self):
        cases = [(None, {}), ({"extra": {}}, {}), ({"policies": []}, {}),
                 ({}, {"skill": {"type": "git", "update": {"policy": "missing"}}}),
                 ({}, {"skill": {"type": "git", "update": {"policy": []}}}),
                 ({}, {"skill": {"type": "external"}})]
        for updates, skills in cases:
            with self.subTest(updates=updates, skills=skills), self.assertRaises(Error):
                resolve_policies(updates, skills)


if __name__ == "__main__":
    unittest.main()
