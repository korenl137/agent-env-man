"""Offline Codex hook installation preserves other hooks and never grants trust."""

import base64
from contextlib import ExitStack
import json
import os
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

from agent_env_man import hooks
from agent_env_man.agents import profile
from agent_env_man.manager import Manager
from agent_env_man.model import Config
from agent_env_man.storage import State, lock
from test_instructions import InstructionFixture


class HookInstallation(InstructionFixture):
    def hook_file(self):
        return self.agent / "hooks.json"

    def write_hooks(self, document):
        self.agent.mkdir(exist_ok=True)
        self.hook_file().write_text(json.dumps(document), encoding="utf-8")

    def existing_hooks(self):
        return {"description": "User configuration", "custom": {"keep": True}, "hooks": {
            "SessionStart": [{"matcher": "startup", "hooks": [{"type": "command", "command": "echo existing"}]}],
            "Stop": [{"hooks": [{"type": "command", "command": "echo stop"}]}]}}

    def test_bootstrap_and_preview_do_not_register_and_apply_reports_trust(self):
        self.configure()
        self.assertFalse(self.hook_file().exists())
        preview = self.run_cli("apply", "--item", "personal:entry", "--dry-run")
        self.assertEqual([r["item"] for r in preview], ["personal:bundle", "personal:entry", "personal:hook"])
        self.assertEqual(preview[-1]["hook"], "would-register")
        self.assertIn("/hooks", preview[-1]["notice"])
        self.assertFalse(self.hook_file().exists())
        self.assertFalse((self.agent / "AGENTS.md").exists())
        result = self.run_cli("apply", "--item", "personal:entry")
        self.assertEqual(result[-1]["hook"], "registered")
        self.assertEqual(result[-1]["trust"], "not-managed-by-aem")
        self.assertFalse((self.agent / "config.toml").exists())
        self.assertEqual((self.agent / "AGENTS.md").read_bytes(), (self.bundle / "start.md").read_bytes())

    def test_unrelated_hooks_and_metadata_survive_and_reapply_is_idempotent(self):
        self.configure()
        initial = self.existing_hooks()
        self.write_hooks(initial)
        self.run_cli("apply")
        after = json.loads(self.hook_file().read_text())
        self.assertEqual(after["description"], initial["description"])
        self.assertEqual(after["custom"], initial["custom"])
        self.assertEqual(after["hooks"]["Stop"], initial["hooks"]["Stop"])
        self.assertEqual(after["hooks"]["SessionStart"][:-1], initial["hooks"]["SessionStart"])
        before = self.hook_file().read_bytes()
        result = self.run_cli("apply")
        self.assertEqual(result[-1]["hook"], "unchanged")
        self.assertEqual(before, self.hook_file().read_bytes())
        # Changes outside the owned group must not be reported as local conflicts.
        after["hooks"]["Stop"][0]["hooks"][0]["command"] = "echo changed by user"
        self.write_hooks(after)
        statuses = {i["item"]: i for i in self.run_cli("status")["items"]}
        self.assertEqual(statuses["personal:hook"]["status"], "current")
        self.run_cli("apply")
        self.assertEqual(json.loads(self.hook_file().read_text()), after)

    def test_modified_owned_hook_is_preserved_until_explicit_replace(self):
        self.configure()
        self.write_hooks(self.existing_hooks())
        self.run_cli("apply")
        changed = json.loads(self.hook_file().read_text())
        changed["hooks"]["SessionStart"][-1]["hooks"][0]["command"] = "echo local override"
        self.write_hooks(changed)
        self.run_cli("apply", code=1)
        self.assertEqual(json.loads(self.hook_file().read_text()), changed)
        self.run_cli("apply", "--item", "personal:entry", "--replace")
        restored = json.loads(self.hook_file().read_text())
        self.assertEqual(restored["hooks"]["SessionStart"][0], changed["hooks"]["SessionStart"][0])
        self.assertNotEqual(restored["hooks"]["SessionStart"][-1], changed["hooks"]["SessionStart"][-1])

    def test_invalid_hook_file_prevents_any_installation(self):
        self.configure()
        self.agent.mkdir()
        for content in ('{broken', '{"hooks": []}', '{"hooks":{},"hooks":{}}', '{"hooks":{"SessionStart":{}}}'):
            with self.subTest(content=content):
                self.hook_file().write_text(content)
                self.run_cli("apply", code=1)
                self.assertEqual(self.hook_file().read_text(), content)
                self.assertFalse((self.rules / "personal").exists())
                self.assertFalse((self.agent / "AGENTS.md").exists())

    def test_hook_file_symlink_is_not_followed_or_replaced(self):
        self.configure()
        self.agent.mkdir()
        other = self.root / "other-hooks.json"
        other.write_text('{}')
        self.hook_file().symlink_to(other)
        self.run_cli("apply", "--item", "personal:entry", "--replace", code=1)
        self.assertTrue(self.hook_file().is_symlink())
        self.assertEqual(other.read_text(), '{}')

    def test_hook_callback_is_metadata_only_and_survives_detach(self):
        self.configure()
        self.run_cli("apply")
        state_path = Config(self.config).state_dir / "state.json"
        before = state_path.read_bytes()
        result = self.run_cli("agent-hook", "personal", "--agent", "codex")
        self.assertEqual(result["hookSpecificOutput"]["hookEventName"], "SessionStart")
        context = result["hookSpecificOutput"]["additionalContext"]
        self.assertIn(str(self.bundle), context)
        self.assertNotIn("Read development/rules.md", context)
        self.assertEqual(state_path.read_bytes(), before)
        registered = self.hook_file().read_bytes()
        self.catalog.unlink()
        self.run_cli("detach", "personal:bundle", "personal:entry")
        shutil.rmtree(self.external)
        self.assertEqual(self.hook_file().read_bytes(), registered)
        result = self.run_cli("agent-hook", "personal", "--agent", "codex")
        self.assertIn(str(self.rules / "personal"), result["hookSpecificOutput"]["additionalContext"])
        self.assertFalse((self.agent / "AGENTS.md").is_symlink())
        self.assertTrue(State(Config(self.config).state_dir).data["items"]["personal:hook"]["detached"])

    def test_missing_source_or_pending_recovery_produces_structured_stop(self):
        self.configure()
        self.run_cli("apply")
        shutil.rmtree(self.external)
        result = self.run_cli("agent-hook", "personal", "--agent", "codex")
        self.assertIs(result["continue"], False)
        self.assertIn("lookup failed", result["systemMessage"])
        state = State(Config(self.config).state_dir)
        state.data["pending"] = {"example": "pending transaction"}
        state.save()
        result = self.run_cli("agent-hook", "personal", "--agent", "codex")
        self.assertIs(result["continue"], False)
        self.assertIn("recover", result["stopReason"])

    def test_instruction_callbacks_retry_contention_and_read_state_after_acquiring(self):
        self.configure()
        self.run_cli("apply")
        directory = Config(self.config).state_dir
        for command in (("agent-hook", "--agent", "codex"),):
            for pending in (False, True):
                with self.subTest(command=command, pending=pending), ExitStack() as holder:
                    state = State(directory)
                    state.data["pending"] = None
                    state.save()
                    holder.enter_context(lock(directory))

                    def finish_writer(_delay):
                        if pending:
                            state.data["pending"] = {"example": "interrupted transaction"}
                            state.save()
                        holder.close()

                    with patch("agent_env_man.storage.time.sleep", side_effect=finish_writer) as retry:
                        result = self.run_cli(*command, "personal")
                    retry.assert_called_once()
                    if pending:
                        self.assertIs(result["continue"], False)
                        self.assertIn("recover", result["stopReason"])
                    else:
                        self.assertIn(str(self.bundle), result["hookSpecificOutput"]["additionalContext"])

    def test_instruction_callbacks_stop_when_contention_outlasts_wait_budget(self):
        self.configure()
        self.run_cli("apply")
        directory = Config(self.config).state_dir
        before = (directory / "state.json").read_bytes()
        for command in (("agent-hook", "--agent", "codex"),):
            with self.subTest(command=command), lock(directory):
                with patch("agent_env_man.storage.time.monotonic", side_effect=[0, 0, 5]), \
                        patch("agent_env_man.storage.time.sleep") as retry:
                    result = self.run_cli(*command, "personal")
                retry.assert_called_once()
                self.assertIs(result["continue"], False)
                self.assertIn("holds this config's lock", result["stopReason"])
        self.assertEqual((directory / "state.json").read_bytes(), before)

    def test_hook_transaction_failure_restores_existing_hooks_and_can_retry(self):
        self.configure()
        initial = self.existing_hooks()
        self.write_hooks(initial)
        original = os.replace

        def fail_hook(src, dst):
            if Path(src).name.startswith(".aem-stage-") and Path(dst) == self.hook_file():
                raise OSError("Injected hook installation failure")
            return original(src, dst)

        with patch("agent_env_man.manager.os.replace", side_effect=fail_hook):
            self.run_cli("apply", code=1)
        self.assertEqual(json.loads(self.hook_file().read_text()), initial)
        state = State(Config(self.config).state_dir)
        self.assertIsNone(state.data["pending"])
        self.assertNotIn("personal:hook", state.data["items"])
        self.assertTrue((self.agent / "AGENTS.md").is_symlink())
        self.run_cli("apply")
        self.assertEqual(len(json.loads(self.hook_file().read_text())["hooks"]["SessionStart"]), 2)

    def test_duplicate_marker_is_never_silently_removed(self):
        self.configure()
        self.run_cli("apply")
        doc = json.loads(self.hook_file().read_text())
        doc["hooks"]["SessionStart"].append(doc["hooks"]["SessionStart"][0])
        self.write_hooks(doc)
        self.run_cli("apply", "--item", "personal:entry", "--replace", code=1)
        self.assertEqual(json.loads(self.hook_file().read_text()), doc)

    def test_implicit_bundle_does_not_gain_replace_permission(self):
        self.configure()
        target = self.rules / "personal"
        target.mkdir(parents=True)
        (target / "local.txt").write_text("Keep")
        self.run_cli("apply", "--item", "personal:entry", "--replace", code=1)
        self.assertEqual((target / "local.txt").read_text(), "Keep")

    def test_other_bundle_shares_one_hook_file_transaction(self):
        self.configure()
        import tomlkit
        doc = tomlkit.parse(self.catalog.read_text())
        doc["instructions"]["other"] = dict(doc["instructions"]["personal"],
            destination="other", entry_destination="OTHER.md")
        self.catalog.write_text(tomlkit.dumps(doc))
        original = os.replace
        def fail_hook(src, dst):
            if Path(src).name.startswith(".aem-stage-") and Path(dst) == self.hook_file():
                raise OSError("Grouped hook failure")
            return original(src, dst)
        with patch("agent_env_man.manager.os.replace", side_effect=fail_hook):
            self.run_cli("apply", code=1)
        state = State(Config(self.config).state_dir).data
        self.assertIsNone(state["pending"])
        self.assertNotIn("personal:hook", state["items"])
        self.assertNotIn("other:hook", state["items"])
        self.assertFalse(self.hook_file().exists())
        self.run_cli("apply")
        before = self.hook_file().read_bytes()
        self.assertEqual(len(json.loads(before)["hooks"]["SessionStart"]), 2)
        self.run_cli("apply")
        self.assertEqual(self.hook_file().read_bytes(), before)

    def test_windows_command_encodes_literal_arguments(self):
        # Verify platform-independent encoding without claiming a Windows run.
        path = Path("C:/Users/space ' and $name/machine.toml")
        with patch.object(hooks.os, "name", "nt"):
            _, group = profile("codex").definition(path, "personal")
        command = group["hooks"][0]["command"]
        self.assertTrue(command.startswith("powershell.exe -NoProfile -NonInteractive -EncodedCommand "))
        decoded = base64.b64decode(command.split()[-1]).decode("utf-16le")
        self.assertIn("'" + str(path).replace("'", "''") + "'", decoded)
        self.assertIn("'agent-hook' 'personal' '--agent' 'codex'", decoded)

    def test_removed_hook_is_not_silently_reinstalled(self):
        self.configure()
        self.run_cli("apply")
        self.write_hooks(self.existing_hooks())
        before = self.hook_file().read_bytes()
        self.run_cli("apply", code=1)
        self.assertEqual(self.hook_file().read_bytes(), before)
        self.run_cli("apply", "--item", "personal:entry", "--replace")
        self.assertEqual(len(json.loads(self.hook_file().read_text())["hooks"]["SessionStart"]), 2)

    def test_hook_preflight_does_not_overwrite_concurrent_edit(self):
        self.configure()
        self.write_hooks(self.existing_hooks())
        config = Config(self.config)
        manager = Manager(config, State(config.state_dir))
        item = next(i for i in manager.items() if i.kind == "instruction-hook")
        plan = manager.plan(item)
        changed = self.existing_hooks()
        changed["description"] = "Edited after preflight"
        self.write_hooks(changed)
        from agent_env_man.model import Error
        with self.assertRaises(Error):
            manager.install(plan)
        self.assertEqual(json.loads(self.hook_file().read_text()), changed)

    def test_reattach_retained_hook_requires_no_duplicate_or_implicit_replacement(self):
        self.configure()
        self.run_cli("apply")
        self.run_cli("detach", "personal:bundle", "personal:entry")
        self.run_cli("apply", "--item", "personal:entry", "--reattach", "--replace", code=1)
        self.run_cli("apply", "--item", "personal:bundle", "--item", "personal:entry", "--reattach", "--replace")
        self.assertEqual(len(json.loads(self.hook_file().read_text())["hooks"]["SessionStart"]), 1)
        self.assertTrue((self.agent / "AGENTS.md").is_symlink())

    def test_active_entry_link_guard_survives_detached_bundle_and_removed_declaration(self):
        self.configure(git=True)
        self.run_cli("apply")
        self.run_cli("detach", "personal:bundle")
        (self.bundle / "start.md").unlink()
        self.commit(self.external)
        import tomlkit
        doc = tomlkit.parse(self.catalog.read_text())
        del doc["instructions"]
        doc["skills"]["other"] = {"repo": "guidance", "subdir": "."}
        self.catalog.write_text(tomlkit.dumps(doc))
        self.run_cli("update", "other", code=1)
        self.assertTrue((self.agent / "AGENTS.md").is_file())

    def test_partial_bundle_detach_keeps_hook_aligned_with_live_global_entry(self):
        self.configure()
        self.run_cli("apply")
        self.run_cli("detach", "personal:bundle")
        (self.bundle / "development/rules.md").write_text("Live source change")
        context = self.run_cli("agent-hook", "personal", "--agent", "codex")["hookSpecificOutput"]["additionalContext"]
        metadata = json.loads(context.split("\n")[1])
        self.assertEqual(metadata, {"root": str(self.bundle), "entry": str(self.bundle / "start.md"),
                                    "global_entry": str(self.agent / "AGENTS.md")})
        diagnostic = self.run_cli("locate", "personal")
        self.assertEqual(diagnostic["installed_root"], str(self.rules / "personal"))
        self.assertTrue(diagnostic["detached"])
        self.assertEqual(metadata["root"], str(self.bundle))
        self.assertEqual(Path(metadata["root"], "development/rules.md").read_text(), "Live source change")
        self.run_cli("detach", "personal:entry")
        context = self.run_cli("agent-hook", "personal", "--agent", "codex")["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(json.loads(context.split("\n")[1]), {
            "root": str(self.rules / "personal"), "entry": str(self.rules / "personal/start.md"),
            "global_entry": str(self.agent / "AGENTS.md")})
