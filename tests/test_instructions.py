"""Instruction bundles share delivery and ownership with independent Git skills."""

from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

import tomlkit

from agent_env_man.storage import State
import test_skill_catalog as skill_tests


class InstructionFixture(unittest.TestCase):
    setUp = skill_tests.SkillCatalog.setUp
    repository = skill_tests.SkillCatalog.repository
    git = skill_tests.SkillCatalog.git
    commit = skill_tests.SkillCatalog.commit
    save_catalog = skill_tests.SkillCatalog.save_catalog
    run_cli = skill_tests.SkillCatalog.run_cli
    require_links = skill_tests.SkillCatalog.require_links

    def configure(self, *, git=False, subdir="."):
        self.require_links()
        self.external = self.root / "synced folder"
        self.bundle = self.external / subdir
        (self.bundle / "development").mkdir(parents=True)
        (self.bundle / "start.md").write_text("Read development/rules.md\n", encoding="utf-8")
        (self.bundle / "development/rules.md").write_text("User-supplied guidance\n", encoding="utf-8")
        self.rules = self.root / "installed rules"
        self.agent = self.root / "agent-home"
        source = {"external": "personal"}
        catalog = {"version": 1, "skills": self.skills, "externals": {"personal": {}}}
        if git:
            self.git(self.external, "init", "-b", "main")
            self.commit(self.external)
            catalog["repositories"] = {"guidance": {"repository": str(self.external)}}
            source = {"repo": "guidance"}
        catalog["instructions"] = {"personal": {**source, "subdir": subdir, "entry": "start.md",
            "root": "rules", "destination": "personal", "entry_root": "agent", "entry_destination": "AGENTS.md"}}
        self.catalog.write_text(tomlkit.dumps(catalog), encoding="utf-8")
        self.config.write_text(tomlkit.dumps({"version": 1, "external_paths": {"personal": str(self.external)},
            "roots": {"rules": str(self.rules), "agent": str(self.agent)}}), encoding="utf-8")
        return self.run_cli("bootstrap", "--catalog", self.catalog, "--checkout-root", self.checkouts,
                            "--root", f"skills={self.destination}")


class Instructions(InstructionFixture):
    def test_combined_external_live_change_detach_and_missing_catalog(self):
        self.configure(subdir="custom/layout")
        self.run_cli("apply")
        installed = self.rules / "personal"
        entry = self.agent / "AGENTS.md"
        self.assertTrue((self.destination / "report").is_symlink())
        self.assertTrue(installed.is_symlink())
        self.assertTrue(entry.is_symlink())
        self.assertEqual(entry.resolve(), self.bundle / "start.md")
        self.assertEqual(self.run_cli("locate", "personal")["root"], str(self.bundle))
        self.assertEqual(entry.read_bytes(), (self.bundle / "start.md").read_bytes())
        (self.bundle / "development/rules.md").write_text("Changed live", encoding="utf-8")
        self.assertEqual((installed / "development/rules.md").read_text(), "Changed live")
        statuses = {r["item"]: r for r in self.run_cli("status")["items"]}
        self.assertEqual(statuses["personal:bundle"]["note"], "changed-live")
        self.catalog.unlink()
        self.run_cli("detach", "personal:bundle", "personal:entry")
        shutil.rmtree(self.external)
        self.assertFalse(installed.is_symlink())
        self.assertEqual((installed / "development/rules.md").read_text(), "Changed live")
        self.assertTrue(entry.is_file())

    def test_missing_external_preserves_ownership_and_broken_link(self):
        self.configure()
        self.run_cli("apply")
        shutil.rmtree(self.external)
        statuses = {r["item"]: r for r in self.run_cli("status")["items"]}
        self.assertEqual(statuses["personal:bundle"]["installation"], "broken-link")
        self.run_cli("detach", "personal:bundle", "personal:entry", code=1)
        self.run_cli("update", "personal", code=1)
        self.assertTrue((self.agent / "AGENTS.md").is_symlink())
        self.assertFalse((self.agent / "AGENTS.md").exists())
        self.assertFalse(State(Path(str(self.config) + ".state")).data["items"]["personal:entry"]["detached"])

    def test_entry_conflict_preserves_local_edits(self):
        self.configure()
        self.agent.mkdir()
        entry = self.agent / "AGENTS.md"
        entry.write_text("Existing user content", encoding="utf-8")
        self.run_cli("apply", code=1)
        self.assertFalse((self.rules / "personal").exists())
        self.run_cli("apply", "--item", "personal:entry", "--replace")
        self.assertEqual(next(self.agent.glob("AGENTS.md.aem-backup-*")).read_text(), "Existing user content")
        entry.unlink()
        entry.write_text("Local edit", encoding="utf-8")
        self.run_cli("apply", code=1)
        self.run_cli("detach", "personal:entry")
        self.assertEqual(entry.read_text(), "Local edit")

    def test_git_root_bundle_guard_and_detach_excludes_database(self):
        self.configure(git=True)
        self.run_cli("apply")
        (self.bundle / "development/rules.md").write_text("New revision", encoding="utf-8")
        self.commit(self.external)
        self.run_cli("update", "personal")
        self.assertEqual((self.rules / "personal/development/rules.md").read_text(), "New revision")
        (self.bundle / "start.md").unlink()
        self.commit(self.external)
        # Saved active ownership must guard the entry even after declaration removal.
        doc = tomlkit.parse(self.catalog.read_text())
        del doc["instructions"]
        doc["skills"]["other"] = {"repo": "guidance", "subdir": "."}
        self.catalog.write_text(tomlkit.dumps(doc), encoding="utf-8")
        self.run_cli("update", "other", code=1)
        self.assertTrue((self.rules / "personal/start.md").exists())
        self.run_cli("detach", "personal:bundle", "personal:entry")
        self.assertFalse((self.rules / "personal/.git").exists())

    def test_invalid_layout_and_source_overlap_rejected_before_clone(self):
        self.configure()
        doc = tomlkit.parse(self.catalog.read_text())
        doc["instructions"]["personal"]["entry"] = "../escape.md"
        self.catalog.write_text(tomlkit.dumps(doc), encoding="utf-8")
        self.run_cli("apply", code=1)
        doc["instructions"]["personal"]["entry"] = "start.md"
        doc["instructions"]["personal"]["entry_root"] = "rules"
        doc["instructions"]["personal"]["entry_destination"] = "personal/AGENTS.md"
        self.catalog.write_text(tomlkit.dumps(doc), encoding="utf-8")
        self.run_cli("apply", code=1)

    def test_external_binding_can_differ_between_machines(self):
        self.configure()
        other = self.root / "another-device"
        shutil.copytree(self.external, other)
        doc = tomlkit.parse(self.config.read_text())
        doc["external_paths"]["personal"] = str(other)
        self.config.write_text(tomlkit.dumps(doc), encoding="utf-8")
        self.run_cli("apply")
        self.assertEqual((self.rules / "personal").resolve(), other)

    def test_failure_during_entry_replacement_recovers_old_file(self):
        self.configure()
        self.agent.mkdir()
        entry = self.agent / "AGENTS.md"
        entry.write_text("User content", encoding="utf-8")
        import os
        original = os.replace

        def fail_stage(src, dst):
            if Path(src).name.startswith(".aem-stage-"):
                raise OSError("Injected entry install failure")
            return original(src, dst)

        with patch("agent_env_man.manager.os.replace", side_effect=fail_stage):
            self.run_cli("apply", "--item", "personal:entry", "--replace", code=1)
        self.assertEqual(entry.read_text(), "User content")
        self.assertIsNone(State(Path(str(self.config) + ".state")).data["pending"])

    def test_external_entry_loss_and_nested_symlink_are_reported(self):
        self.configure()
        (self.bundle / "start.md").unlink()
        self.run_cli("apply", code=1)
        (self.bundle / "start.md").write_text("Restored entry", encoding="utf-8")
        (self.bundle / "escape").symlink_to(self.catalog)
        self.run_cli("apply", code=1)
        self.assertFalse((self.agent / "AGENTS.md").exists())

    def test_removed_declaration_keeps_targets_and_blocks_path_change(self):
        self.configure()
        self.run_cli("apply")
        doc = tomlkit.parse(self.catalog.read_text())
        doc["instructions"]["personal"]["destination"] = "relocated"
        self.catalog.write_text(tomlkit.dumps(doc), encoding="utf-8")
        self.run_cli("apply", code=1)
        del doc["instructions"]
        self.catalog.write_text(tomlkit.dumps(doc), encoding="utf-8")
        self.run_cli("apply")
        self.assertTrue((self.rules / "personal").is_symlink())
        self.assertTrue((self.agent / "AGENTS.md").is_file())

    def test_git_skill_and_bundle_share_checkout_and_validate_before_publish(self):
        self.configure(git=True, subdir="guidance")
        (self.external / "SKILL.md").write_text("Example skill", encoding="utf-8")
        self.commit(self.external)
        self.run_cli("update", "personal")
        doc = tomlkit.parse(self.catalog.read_text())
        doc["skills"]["shared"] = {"repo": "guidance"}
        self.catalog.write_text(tomlkit.dumps(doc), encoding="utf-8")
        self.run_cli("bootstrap")
        self.run_cli("apply")
        self.assertEqual((self.destination / "shared").resolve(), (self.rules / "personal").resolve().parent)
        self.assertTrue((self.rules / "personal/development/rules.md").is_file())

    def test_external_root_cannot_be_nested_in_managed_checkouts(self):
        self.configure()
        doc = tomlkit.parse(self.config.read_text())
        doc["external_paths"]["personal"] = str(self.checkouts / "synced")
        self.config.write_text(tomlkit.dumps(doc), encoding="utf-8")
        message = self.run_cli("apply", code=1)
        self.assertIn("disjoint", message)

    def test_invalid_git_entry_is_not_published_by_bootstrap(self):
        self.configure(git=True)
        checkout = self.checkouts / ".aem-repositories/guidance"
        shutil.rmtree(checkout)
        (self.bundle / "start.md").unlink()
        self.commit(self.external)
        self.run_cli("bootstrap", code=1)
        self.assertFalse(checkout.exists())

    def use_default_destination(self):
        document = tomlkit.parse(self.catalog.read_text())
        document["instructions"]["personal"].pop("root")
        document["instructions"]["personal"].pop("destination")
        self.catalog.write_text(tomlkit.dumps(document), encoding="utf-8")
        machine = tomlkit.parse(self.config.read_text())
        machine["roots"].pop("rules")
        self.config.write_text(tomlkit.dumps(machine), encoding="utf-8")
        return self.config.with_name(self.config.name + ".bundles") / "personal"

    def test_default_root_locator_and_detach_without_catalog(self):
        self.configure(subdir="nested bundle")
        target = self.use_default_destination()
        self.run_cli("locate", "personal", code=1)
        self.run_cli("apply")
        self.assertEqual(target.resolve(), self.bundle)
        found = self.run_cli("locate", "personal")
        self.assertEqual(found["root"], str(self.bundle))
        self.assertEqual(found["entry"], str(self.bundle / "start.md"))
        self.assertEqual(found["installed_root"], str(target))
        state_path = Path(str(self.config) + ".state/state.json")
        before = state_path.read_bytes()
        self.catalog.unlink()
        self.assertEqual(self.run_cli("locate", "personal"), found)
        self.assertEqual(state_path.read_bytes(), before)
        self.run_cli("detach", "personal:bundle", "personal:entry")
        shutil.rmtree(self.external)
        found = self.run_cli("locate", "personal")
        self.assertTrue(found["detached"])
        self.assertEqual(found["root"], str(target))
        self.assertEqual(Path(found["entry"]).read_text(), "Read development/rules.md\n")

    def test_locator_rejects_missing_entry_and_replaced_link(self):
        self.configure()
        self.run_cli("apply")
        entry = self.bundle / "start.md"
        entry.unlink()
        self.run_cli("locate", "personal", code=1)
        entry.write_text("Restored", encoding="utf-8")
        installed = self.rules / "personal"
        installed.unlink()
        installed.symlink_to(self.repo, target_is_directory=True)
        self.assertIn("replaced", self.run_cli("locate", "personal", code=1))

    def test_git_default_root_and_nested_entry(self):
        self.configure(git=True, subdir="guidance")
        (self.bundle / "development/entry.md").write_text("Nested entry", encoding="utf-8")
        self.commit(self.external)
        self.run_cli("update", "personal")
        target = self.use_default_destination()
        doc = tomlkit.parse(self.catalog.read_text())
        doc["instructions"]["personal"]["entry"] = "development/entry.md"
        self.catalog.write_text(tomlkit.dumps(doc), encoding="utf-8")
        self.run_cli("apply")
        found = self.run_cli("locate", "personal")
        self.assertEqual(found["root"], str(target.resolve()))
        self.assertEqual(Path(found["entry"]).read_text(), "Nested entry")

    def test_existing_guide_upgrades_without_replacing_local_edits(self):
        self.configure()
        self.run_cli("apply", "--item", "personal:bundle")
        self.agent.mkdir()
        guide = self.agent / "AGENTS.md"
        guide.write_text("Previous guide\n", encoding="utf-8")
        state = State(Path(str(self.config) + ".state"))
        state.data["items"]["personal:entry"] = dict(state.data["items"]["personal:bundle"],
            id="entry", target=str(guide), mode="entry", kind="instruction-entry", content="Previous guide\n")
        state.save()
        guide.write_text("Local edit", encoding="utf-8")
        self.run_cli("apply", code=1)
        self.assertFalse((self.agent / "hooks.json").exists())
        self.assertEqual(guide.read_text(), "Local edit")
        guide.write_text("Previous guide\n", encoding="utf-8")
        self.run_cli("apply")
        self.assertTrue(guide.is_symlink())
        self.assertEqual(guide.read_text(), (self.bundle / "start.md").read_text())

    def test_locator_uses_saved_entry_despite_changed_catalog_and_refuses_pending(self):
        self.configure()
        self.run_cli("apply")
        doc = tomlkit.parse(self.catalog.read_text())
        doc["instructions"]["personal"]["entry"] = "not-installed.md"
        self.catalog.write_text(tomlkit.dumps(doc), encoding="utf-8")
        self.assertEqual(self.run_cli("locate", "personal")["entry"], str(self.bundle / "start.md"))
        state = State(Path(str(self.config) + ".state"))
        state.data["pending"] = {"test": "pending transaction"}
        state.save()
        self.assertIn("recover", self.run_cli("locate", "personal", code=1))

    def test_locator_rejects_redirected_entry(self):
        self.configure()
        self.run_cli("apply")
        entry = self.bundle / "start.md"
        entry.unlink()
        entry.symlink_to(self.catalog)
        self.assertIn("symlink", self.run_cli("locate", "personal", code=1))

    def test_generated_locator_command_handles_special_config_path(self):
        import os
        import shlex
        import subprocess
        import sys
        if os.name == "nt":
            self.skipTest("POSIX shell command execution test")
        self.configure()
        old = self.config
        self.config = self.root / "machine 'quoted' $name.toml"
        old.rename(self.config)
        self.run_cli("bootstrap")
        self.run_cli("apply")
        import json
        config = json.loads((self.agent / "hooks.json").read_text())
        command = config["hooks"]["SessionStart"][0]["hooks"][0]["command"]
        tokens = shlex.split(command)
        self.assertEqual(tokens, [sys.executable, "-m", "agent_env_man", "--config", str(self.config), "codex-hook", "personal"])
        result = subprocess.run(command, shell=True, cwd=self.external, input='{"hook_event_name":"SessionStart"}',
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn(str(self.bundle), context)
        self.assertNotIn("User-supplied guidance", context)
