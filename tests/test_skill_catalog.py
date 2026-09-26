"""Local inventories deliver independent Git skill repositories end to end."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import tomlkit

from agent_env_man.cli import main
from agent_env_man.git_source import Git
from agent_env_man.storage import fingerprint


class SkillCatalog(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="aem-skills-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config = self.root / "machine.toml"
        self.catalog = self.root / "inventory/skills.toml"
        self.catalog.parent.mkdir()
        self.checkouts = self.root / "checkouts"
        self.destination = self.root / "installed-skills"
        self.environment = patch.dict(os.environ, {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.repo = self.repository("research-tools", "skills/report")
        self.skills = {"report": {"type": "git", "repository": str(self.repo), "subdir": "skills/report"}}
        self.save_catalog()

    def git(self, path, *args):
        result = subprocess.run(["git", "-C", str(path), *map(str, args)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def commit(self, path):
        self.git(path, "add", "-A")
        self.git(path, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "Test content")

    def repository(self, name, skill_path):
        repo = self.root / name
        folder = repo / skill_path
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text("---\nname: report\ndescription: Test skill\n---\n\nUse the test helper.\n", encoding="utf-8")
        (folder / "helper.py").write_text("print('test')\n", encoding="utf-8")
        self.git(repo, "init", "-b", "main")
        self.commit(repo)
        return repo

    def save_catalog(self):
        self.catalog.write_text(tomlkit.dumps({"version": 1, "skills": self.skills}), encoding="utf-8")

    def run_cli(self, *args, code=0, config=None):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            result = main(["--config", str(config or self.config), *map(str, args)])
        self.assertEqual(result, code, f"{args}\n{output.getvalue()}\n{errors.getvalue()}")
        return json.loads(output.getvalue()) if output.getvalue() else errors.getvalue()

    def bootstrap(self, **kwargs):
        return self.run_cli("bootstrap", "--catalog", self.catalog, "--checkout-root", self.checkouts,
                            "--root", f"skills={self.destination}", **kwargs)

    def require_links(self):
        probe = self.root / "link-probe"
        try:
            probe.symlink_to(self.catalog)
        except OSError:
            self.skipTest("Symbolic link capability unavailable")
        probe.unlink()

    def copy_mode(self):
        self.skills["report"]["mode"] = "copy"
        self.save_catalog()

    def test_catalog_clones_two_independent_repositories_without_manifests(self):
        self.require_links()
        standalone = self.repository("standalone", ".")
        self.skills["standalone"] = {"type": "git", "repository": str(standalone)}
        self.save_catalog()
        before = self.catalog.read_bytes()
        self.bootstrap()
        self.assertFalse(self.destination.exists())
        self.assertEqual(len(self.run_cli("apply", "--dry-run")), 2)
        self.run_cli("apply")
        self.assertEqual((self.destination / "report").resolve(), self.checkouts / "report/skills/report")
        self.assertEqual((self.destination / "standalone").resolve(), self.checkouts / "standalone")
        for name in ("report", "standalone"):
            self.assertTrue((self.checkouts / name / ".git").is_dir())
            self.assertFalse((self.checkouts / name / "links.conf").exists())
        self.assertEqual(self.catalog.read_bytes(), before)
        self.assertEqual(self.git(self.repo, "status", "--porcelain"), "")

    def test_after_bootstrap_local_use_does_not_fetch(self):
        self.copy_mode()
        self.bootstrap()
        original = Git.run

        def offline(git, path, *args, **kwargs):
            self.assertNotIn(args[0], ("fetch", "pull", "clone", "push", "merge"))
            return original(git, path, *args, **kwargs)

        with patch.object(Git, "run", offline):
            self.run_cli("apply")
            self.run_cli("status")
            self.run_cli("detach", "report")

    def test_same_local_catalog_bootstraps_another_device_without_per_repo_bindings(self):
        self.copy_mode()
        self.bootstrap()
        self.run_cli("apply")
        second_config = self.root / "other-machine.toml"
        second_target = self.root / "other-skills"
        self.run_cli("bootstrap", "--catalog", self.catalog, "--root", f"skills={second_target}", config=second_config)
        self.run_cli("apply", config=second_config)
        self.assertEqual((self.destination / "report/SKILL.md").read_bytes(), (second_target / "report/SKILL.md").read_bytes())
        self.assertNotIn("repositories", tomlkit.parse(second_config.read_text()))

    def test_update_delivers_git_change_and_apply_refreshes_copy(self):
        self.copy_mode()
        self.bootstrap()
        self.run_cli("apply")
        descriptor = self.repo / "skills/report/SKILL.md"
        descriptor.write_text(descriptor.read_text() + "Published change\n", encoding="utf-8")
        self.commit(self.repo)
        self.run_cli("update")
        self.assertNotIn("Published change", (self.destination / "report/SKILL.md").read_text())
        self.run_cli("apply")
        self.assertIn("Published change", (self.destination / "report/SKILL.md").read_text())

    def test_failed_update_preserves_installed_skill(self):
        self.copy_mode()
        self.bootstrap()
        self.run_cli("apply")
        shutil.rmtree(self.repo)
        self.run_cli("sync", code=1)
        self.assertTrue((self.destination / "report/SKILL.md").is_file())
        self.run_cli("apply")

    def test_root_skill_copy_excludes_git_metadata(self):
        standalone = self.repository("standalone", ".")
        self.skills = {"standalone": {"type": "git", "repository": str(standalone), "mode": "copy"}}
        self.save_catalog()
        self.bootstrap()
        self.run_cli("apply")
        target = self.destination / "standalone"
        self.assertFalse((target / ".git").exists())
        self.assertTrue((target / "SKILL.md").is_file())
        self.run_cli("detach", "standalone")
        self.assertTrue((self.checkouts / "standalone/.git").is_dir())

    def test_root_skill_link_detach_materializes_only_skill_contents(self):
        self.require_links()
        standalone = self.repository("standalone", ".")
        self.skills = {"standalone": {"type": "git", "repository": str(standalone)}}
        self.save_catalog()
        self.bootstrap()
        self.run_cli("apply")
        target = self.destination / "standalone"
        before = fingerprint(self.checkouts / "standalone", exclude_git=True)
        self.run_cli("detach", "standalone")
        shutil.rmtree(self.checkouts)
        self.assertFalse(target.is_symlink())
        self.assertFalse((target / ".git").exists())
        self.assertEqual(fingerprint(target), before)
        self.assertEqual(self.run_cli("apply"), [])

    def test_default_branch_is_discovered_and_retained(self):
        self.copy_mode()
        self.git(self.repo, "branch", "-m", "stable")
        self.bootstrap()
        self.run_cli("apply")
        self.assertEqual(self.run_cli("status")["sources"][0]["branch"], "stable")
        self.git(self.checkouts / "report", "checkout", "-b", "other")
        self.run_cli("update", code=1)

    def test_missing_skill_descriptor_fails_before_publishing_checkout(self):
        self.git(self.repo, "rm", "skills/report/SKILL.md")
        self.commit(self.repo)
        report = self.bootstrap(code=1)
        self.assertEqual(report["skills"][0]["status"], "failed")
        self.assertFalse((self.checkouts / "report").exists())
        self.assertFalse(self.destination.exists())
        self.assertFalse(list(self.checkouts.glob(".aem-clone-*")))

    def test_unsupported_source_type_is_rejected_before_network(self):
        self.skills["report"]["type"] = "syncthing"
        self.save_catalog()
        self.assertIn("only type = 'git'", self.bootstrap(code=1))
        self.assertFalse(self.config.exists())
        self.assertFalse(self.checkouts.exists())

    def test_clone_failure_can_be_retried_from_saved_catalog_binding(self):
        self.skills["report"]["repository"] = str(self.root / "missing.git")
        self.save_catalog()
        self.bootstrap(code=1)
        self.assertTrue(self.config.exists())
        self.assertFalse((self.checkouts / "report").exists())
        self.skills["report"]["repository"] = str(self.repo)
        self.save_catalog()
        self.assertEqual(self.run_cli("bootstrap")["skills"][0]["status"], "cloned")

    def test_inventory_cannot_live_in_managed_checkout_storage(self):
        self.run_cli("bootstrap", "--catalog", self.catalog, "--checkout-root", self.catalog.parent,
                     "--root", f"skills={self.destination}", code=1)
        self.assertFalse(self.config.exists())

    def test_missing_inventory_does_not_prevent_preserving_detach(self):
        self.require_links()
        self.bootstrap()
        self.run_cli("apply")
        self.catalog.unlink()
        report = self.run_cli("status")
        self.assertIn("catalog_error", report)
        self.assertEqual(report["items"][0]["installation"], "linked")
        self.run_cli("detach", "report")
        self.assertFalse((self.destination / "report").is_symlink())

    def test_removing_catalog_entry_keeps_target_until_detach(self):
        self.require_links()
        self.bootstrap()
        self.run_cli("apply")
        self.skills = {}
        self.save_catalog()
        self.assertEqual(self.run_cli("apply"), [])
        self.assertTrue((self.destination / "report").is_symlink())
        self.assertEqual(self.run_cli("status")["items"][0]["status"], "orphaned-or-source-unavailable")
        self.run_cli("detach", "report")

    def test_traversal_subdirectory_is_rejected(self):
        for subdir in (None, "../escape", "/absolute", "skills/../report"):
            with self.subTest(subdir=subdir):
                entry = dict(self.skills["report"], subdir=subdir)
                if subdir is None:
                    entry["subdir"] = 123
                self.catalog.write_text(tomlkit.dumps({"version": 1, "skills": {"report": entry}}), encoding="utf-8")
                self.bootstrap(code=1)
                self.assertFalse(self.checkouts.exists())

    def test_update_guards_skill_descriptor_removal_even_if_folder_remains(self):
        self.require_links()
        self.bootstrap()
        self.run_cli("apply")
        (self.repo / "skills/report/SKILL.md").unlink()
        self.commit(self.repo)
        self.run_cli("update", code=1)
        self.assertTrue((self.destination / "report/SKILL.md").is_file())

    def test_changed_catalog_repository_does_not_reuse_an_unrelated_checkout(self):
        self.copy_mode()
        self.bootstrap()
        self.run_cli("apply")
        replacement = self.repository("replacement", "skills/report")
        self.skills["report"]["repository"] = str(replacement)
        self.save_catalog()
        self.run_cli("apply", code=1)
        self.run_cli("bootstrap", code=1)
        self.assertEqual(self.git(self.checkouts / "report", "remote", "get-url", "origin"), str(self.repo))

    def test_root_git_administration_changes_are_not_skill_content_changes(self):
        self.require_links()
        standalone = self.repository("standalone", ".")
        self.skills = {"standalone": {"type": "git", "repository": str(standalone)}}
        self.save_catalog()
        self.bootstrap()
        self.run_cli("apply")
        self.git(self.checkouts / "standalone", "config", "aem.test", "metadata-only")
        item = self.run_cli("status")["items"][0]
        self.assertNotIn("note", item)
        self.assertEqual(item["status"], "current")

    def test_machine_can_explicitly_override_link_with_copy(self):
        self.bootstrap()
        config = tomlkit.parse(self.config.read_text())
        config["modes"] = {"report": "copy"}
        self.config.write_text(tomlkit.dumps(config), encoding="utf-8")
        self.run_cli("apply")
        self.assertFalse((self.destination / "report").is_symlink())
        self.assertEqual(self.run_cli("status")["items"][0]["mode"], "copy")

    def test_new_repository_does_not_inherit_the_previous_default_branch(self):
        self.copy_mode()
        self.git(self.repo, "branch", "-m", "old-default")
        self.bootstrap()
        self.run_cli("apply")
        self.run_cli("detach", "report")
        (self.checkouts / "report").rename(self.root / "saved-old-checkout")
        replacement = self.repository("replacement", "skills/report")
        self.skills["report"]["repository"] = str(replacement)
        self.save_catalog()
        self.run_cli("bootstrap")
        self.assertEqual(self.git(self.checkouts / "report", "symbolic-ref", "--short", "HEAD"), "main")

    def test_root_skill_link_receives_update_without_an_apply_step(self):
        self.require_links()
        standalone = self.repository("standalone", ".")
        self.skills = {"standalone": {"type": "git", "repository": str(standalone)}}
        self.save_catalog()
        self.bootstrap()
        self.run_cli("apply")
        (standalone / "helper.py").write_text("print('new revision')\n", encoding="utf-8")
        self.commit(standalone)
        self.run_cli("update")
        self.assertIn("new revision", (self.destination / "standalone/helper.py").read_text())

    def test_git_symlinks_are_rejected_even_when_checked_out_as_text(self):
        self.require_links()
        (self.repo / "skills/report/helper-link").symlink_to("helper.py")
        self.commit(self.repo)
        with patch.dict(os.environ, {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.symlinks", "GIT_CONFIG_VALUE_0": "false"}):
            report = self.bootstrap(code=1)
        self.assertIn("Git symlink", report["skills"][0]["error"])
        self.assertFalse((self.checkouts / "report").exists())


if __name__ == "__main__":
    unittest.main()
