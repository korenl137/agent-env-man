"""Git inventories bootstrap and round-trip through local remotes only."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import tomlkit

from agent_env_man.cli import main
from agent_env_man.git_source import Git


class GitCatalog(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="aem-git-catalog-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        environment = patch.dict(os.environ, {
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.invalid"})
        environment.start()
        self.addCleanup(environment.stop)
        self.config = self.root / "machine.toml"
        self.remote = self.root / "remote.git"
        self.seed = self.root / "seed"
        self.checkout = self.root / "machine.toml.catalog"
        self.entry = self.checkout / "catalogs/personal.toml"
        self.content = self.root / "machine.toml.checkouts/tool"
        self.target = self.root / "installed/tool"
        self.git(self.root, "init", "--bare", "-b", "main", self.remote)
        self.git(self.root, "clone", self.remote, self.seed)
        (self.seed / "catalogs").mkdir()
        (self.seed / "skill").mkdir()
        (self.seed / "skill/SKILL.md").write_text("# Initial\n", encoding="utf-8")
        self.document = {"version": 1, "skills": {"tool": {
            "type": "git", "repository": str(self.remote), "subdir": "skill", "mode": "copy"}}}
        self.save_remote()

    def git(self, path, *args):
        result = subprocess.run(["git", "-C", str(path), *map(str, args)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def commit(self, path):
        self.git(path, "add", "--all")
        self.git(path, "commit", "-m", "Test change")

    def save_remote(self, text=None):
        (self.seed / "catalogs/personal.toml").write_text(
            tomlkit.dumps(self.document) if text is None else text, encoding="utf-8")
        self.commit(self.seed)
        self.git(self.seed, "push", "origin", "main")

    def cli(self, *args, code=0):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            result = main(["--config", str(self.config), *map(str, args)])
        self.assertEqual(result, code, f"{args}\n{output.getvalue()}\n{errors.getvalue()}")
        return json.loads(output.getvalue()) if output.getvalue() else errors.getvalue()

    def boot(self, *args, code=0):
        return self.cli("bootstrap", "--catalog-repository", self.remote,
                        "--catalog-path", "catalogs/personal.toml",
                        "--root", f"skills={self.root / 'installed'}",
                        "--root", f"agent={self.root / 'agent'}", *args, code=code)

    def state(self):
        return (self.root / "machine.toml.state/state.json").read_bytes()

    def test_first_registration_reuse_locate_apply_and_separate_checkouts(self):
        report = self.boot()
        self.assertEqual(report["catalog"]["status"], "cloned")
        document = tomlkit.parse(self.config.read_text(encoding="utf-8"))
        self.assertEqual(document["catalog"], {"type": "git", "repository": str(self.remote),
                                            "path": "catalogs/personal.toml", "branch": "main"})
        self.assertEqual(self.cli("catalog", "locate")["entry"], str(self.entry))
        self.assertEqual(self.cli("catalog", "status")["status"], "ready")
        self.cli("apply")
        self.assertEqual((self.target / "SKILL.md").read_text(), "# Initial\n")
        before = self.config.read_bytes()
        self.remote.rename(self.root / "offline.git")
        self.assertEqual(self.cli("bootstrap")["catalog"]["status"], "already-prepared")
        self.assertEqual(self.config.read_bytes(), before)
        self.assertTrue((self.content / ".git").is_dir())
        self.assertTrue((self.checkout / ".git").is_dir())

    def test_explicit_branch_and_existing_machine_fields_are_preserved(self):
        self.git(self.seed, "checkout", "-b", "custom")
        self.git(self.seed, "push", "origin", "custom")
        self.config.write_text('version = 1\n# Keep me\n[roots]\nextra = "' + self.root.as_posix() + '/extra"\n')
        self.boot("--catalog-branch", "custom")
        self.assertEqual(self.git(self.checkout, "branch", "--show-current"), "custom")
        self.assertIn("# Keep me", self.config.read_text())
        self.assertIn("extra", tomlkit.parse(self.config.read_text())["roots"])

    def test_update_then_bootstrap_and_apply_new_declarations(self):
        self.boot()
        self.cli("apply")
        self.document["skills"]["new"] = dict(self.document["skills"]["tool"])
        (self.seed / "skill/SKILL.md").write_text("# New\n")
        self.save_remote()
        content_head = self.git(self.content, "rev-parse", "HEAD")
        before = json.loads(self.state())["items"]
        self.assertEqual(self.cli("catalog", "update")["status"], "updated")
        self.assertEqual(self.git(self.content, "rev-parse", "HEAD"), content_head)
        self.assertEqual(json.loads(self.state())["items"], before)
        self.assertFalse((self.root / "installed/new").exists())
        report = self.cli("bootstrap")
        self.assertEqual([r["status"] for r in report["skills"]], ["already-prepared", "cloned"])
        self.cli("apply")
        self.assertEqual((self.root / "installed/new/SKILL.md").read_text(), "# New\n")
        self.assertEqual((self.target / "SKILL.md").read_text(), "# Initial\n")

    def test_content_update_sync_and_auto_do_not_refresh_catalog(self):
        self.boot()
        original = self.git(self.checkout, "rev-parse", "HEAD")
        self.document["skills"]["new"] = dict(self.document["skills"]["tool"])
        self.save_remote()
        self.cli("update")
        self.cli("sync")
        self.cli("auto", "--trigger", "shell-start")
        self.assertEqual(self.git(self.checkout, "rev-parse", "HEAD"), original)
        self.assertNotIn("new", tomlkit.parse(self.entry.read_text())["skills"])

    def test_invalid_incoming_preserves_head_file_and_ownership_then_repairs(self):
        self.boot()
        self.cli("apply")
        head, entry, items = self.git(self.checkout, "rev-parse", "HEAD"), self.entry.read_bytes(), json.loads(self.state())["items"]
        self.save_remote("version = 1\nmisspelled = true\n")
        result = self.cli("catalog", "update", code=1)
        self.assertIn("Catalog requires", result["error"])
        self.assertEqual(self.git(self.checkout, "rev-parse", "HEAD"), head)
        self.assertEqual(self.entry.read_bytes(), entry)
        self.assertEqual(json.loads(self.state())["items"], items)
        self.save_remote()
        self.assertEqual(self.cli("catalog", "update")["status"], "updated")

    def test_incoming_relocation_is_rejected_and_deletion_keeps_installed_item(self):
        self.boot()
        self.cli("apply")
        self.document["skills"]["tool"]["mode"] = "link"
        self.save_remote()
        self.assertIn("detach", self.cli("catalog", "update", code=1)["error"])
        self.document["skills"].clear()
        self.save_remote()
        self.cli("catalog", "update")
        self.assertTrue(self.target.exists())
        self.assertIn("tool", json.loads(self.state())["items"])
        self.cli("detach", "tool")
        self.assertEqual((self.target / "SKILL.md").read_text(), "# Initial\n")

    def test_missing_external_binding_refuses_incoming_catalog(self):
        self.boot()
        self.document["externals"] = {"documents": {}}
        self.document["instructions"] = {"personal": {"external": "documents", "entry": "AGENTS.md", "entry_root": "agent"}}
        self.save_remote()
        self.assertIn("external_paths", self.cli("catalog", "update", code=1)["error"])

    def test_initial_invalid_catalog_does_not_persist_or_clone_content(self):
        for text in ('version = [', 'version = 1\nunknown = 1', 'version = 1\n[skills.bad]\ntype = "git"'):
            with self.subTest(text=text):
                self.save_remote(text)
                self.boot(code=1)
                self.assertFalse(self.config.exists())
                self.assertFalse(self.checkout.exists())
                self.assertFalse(self.content.exists())
                self.assertEqual(list(self.root.glob(".aem-catalog-*")), [])

    def test_failed_download_can_be_retried_without_partial_binding(self):
        self.remote.rename(self.root / "offline.git")
        self.boot(code=1)
        self.assertFalse(self.config.exists())
        self.assertFalse(self.checkout.exists())
        (self.root / "offline.git").rename(self.remote)
        self.boot()

    def test_content_clone_failure_retains_valid_catalog_binding_for_retry(self):
        content_remote = self.root / "missing.git"
        self.document["skills"]["tool"]["repository"] = str(content_remote)
        self.save_remote()
        self.boot(code=1)
        self.assertTrue(self.config.exists())
        self.assertTrue(self.entry.exists())
        self.git(self.root, "clone", "--bare", self.remote, content_remote)
        self.cli("bootstrap")
        self.cli("apply")

    def test_invalid_arguments_fail_without_network(self):
        with patch.object(Git, "run", side_effect=AssertionError("Git invoked before input validation")):
            for args in (("--catalog-repository", str(self.remote)),
                         ("--catalog-path", "catalog.toml"),
                         ("--catalog-branch", "main"),
                         ("--catalog-repository", str(self.remote), "--catalog-path", "../catalog.toml"),
                         ("--catalog-repository", str(self.remote), "--catalog-path", "a\\b"),
                         ("--catalog-repository", str(self.remote), "--catalog-path", "/catalog.toml"),
                         ("--catalog", "local.toml", "--catalog-repository", str(self.remote), "--catalog-path", "catalog.toml")):
                with self.subTest(args=args):
                    self.cli("bootstrap", *args, code=1)
        self.assertFalse(self.config.exists())

    def test_invalid_selection_and_catalog_storage_overlap_leave_no_binding(self):
        self.boot("--item", "unknown", code=1)
        self.assertFalse(self.config.exists())
        self.assertFalse(self.checkout.exists())
        self.boot("--root", f"skills={self.checkout}", code=1)
        self.assertFalse(self.checkout.exists())
        with patch.object(Git, "run", side_effect=AssertionError("overlap contacted Git")):
            self.boot("--checkout-root", self.checkout, code=1)
            self.boot("--external", f"documents={self.checkout / 'docs'}", code=1)

    def test_dirty_ahead_diverged_and_missing_remote_preserve_work(self):
        self.boot()
        original = self.git(self.checkout, "rev-parse", "HEAD")
        self.entry.write_text(self.entry.read_text() + "\n# Local\n")
        self.assertIn("dirty", self.cli("catalog", "update", code=1)["error"])
        self.commit(self.checkout)
        ahead = self.git(self.checkout, "rev-parse", "HEAD")
        self.assertNotEqual(original, ahead)
        self.assertIn("ahead", self.cli("catalog", "update", code=1)["error"])
        self.save_remote(tomlkit.dumps(self.document) + "\n# Remote\n")
        self.assertIn("diverged", self.cli("catalog", "update", code=1)["error"])
        self.remote.rename(self.root / "offline.git")
        self.cli("catalog", "update", code=1)
        self.assertEqual(self.git(self.checkout, "rev-parse", "HEAD"), ahead)

    def test_missing_entry_and_invalid_utf8_do_not_advance(self):
        self.boot()
        original = self.git(self.checkout, "rev-parse", "HEAD")
        file = self.seed / "catalogs/personal.toml"
        file.unlink()
        self.commit(self.seed)
        self.git(self.seed, "push", "origin", "main")
        self.assertIn("tracked regular", self.cli("catalog", "update", code=1)["error"])
        file.write_bytes(b'version = 1\n# \xff\n')
        self.commit(self.seed)
        self.git(self.seed, "push", "origin", "main")
        self.cli("catalog", "update", code=1)
        self.assertEqual(self.git(self.checkout, "rev-parse", "HEAD"), original)

    def test_publish_preview_is_offline_and_round_trip_includes_whole_repository(self):
        self.boot()
        self.document["skills"]["new"] = dict(self.document["skills"]["tool"])
        self.entry.write_text(tomlkit.dumps(self.document))
        (self.checkout / "notes.txt").write_text("Included\n")
        index, state = (self.checkout / ".git/index").read_bytes(), self.state()
        with patch.object(Git, "fetch", side_effect=AssertionError("preview fetched")):
            result = self.cli("catalog", "publish", "--dry-run")
        self.assertIn("notes.txt", result["changes"])
        self.assertEqual((self.checkout / ".git/index").read_bytes(), index)
        self.assertEqual(self.state(), state)
        self.assertEqual(self.cli("catalog", "publish", "-m", "Share catalog")["status"], "published")
        self.assertEqual(self.git(self.remote, "show", "main:notes.txt"), "Included")
        self.cli("bootstrap")
        self.cli("apply")
        self.assertTrue((self.root / "installed/new/SKILL.md").exists())
        self.assertEqual(self.cli("catalog", "publish")["status"], "published")

    def test_publish_failure_retains_commit_and_retry_pushes_it(self):
        self.boot()
        self.entry.write_text(self.entry.read_text() + "\n# Published later\n")
        self.assertIn("--message", self.cli("catalog", "publish", code=1)["error"])
        self.cli("catalog", "publish", "-m", " ", code=1)
        self.git(self.remote, "config", "core.bare", "false")
        self.git(self.remote, "config", "receive.denyCurrentBranch", "refuse")
        result = self.cli("catalog", "publish", "-m", "Retain", code=1)
        self.assertEqual(result["created_commit"], self.git(self.checkout, "rev-parse", "HEAD"))
        self.git(self.remote, "config", "core.bare", "true")
        self.cli("catalog", "publish")
        self.assertEqual(self.git(self.remote, "rev-parse", "main"), result["created_commit"])

    def test_status_locate_and_detach_work_with_broken_catalog(self):
        self.boot()
        self.cli("apply")
        self.entry.write_text("broken [")
        self.assertEqual(self.cli("catalog", "status")["status"], "unavailable")
        self.assertEqual(self.cli("catalog", "locate")["entry"], str(self.entry))
        self.cli("catalog", "publish", "-m", "Invalid", code=1)
        self.entry.unlink()
        self.cli("status")
        self.cli("detach", "tool")
        self.cli("recover")
        self.assertTrue(self.target.exists())

    def test_changed_origin_or_branch_are_rejected_without_adoption(self):
        self.boot()
        self.git(self.checkout, "checkout", "-b", "other")
        self.assertIn("expected attached branch", self.cli("bootstrap", code=1))
        self.assertIn("expected attached branch", self.boot(code=1))
        self.cli("catalog", "locate", code=1)
        self.git(self.checkout, "checkout", "main")
        self.git(self.checkout, "remote", "set-url", "origin", self.seed)
        self.cli("bootstrap", code=1)
        self.cli("catalog", "update", code=1)
        self.cli("catalog", "publish", code=1)

    def test_local_catalog_commands_and_switch_back_preserve_git_checkout(self):
        self.boot()
        local = self.root / "local.toml"
        local.write_text(tomlkit.dumps(self.document))
        self.cli("bootstrap", local)
        self.assertEqual(self.cli("catalog", "locate")["entry"], str(local))
        self.assertEqual(self.cli("catalog", "status")["status"], "ready")
        self.cli("catalog", "update", code=1)
        self.cli("catalog", "publish", code=1)
        self.assertTrue(self.entry.exists())
        self.boot()

    def test_tracked_symlink_catalog_rejected_even_without_os_symlink_support(self):
        # Build a Git symlink entry directly so this also exercises Windows Git modes.
        blob = self.git(self.seed, "hash-object", "-w", "catalogs/personal.toml")
        self.git(self.seed, "update-index", "--cacheinfo", f"120000,{blob},catalogs/personal.toml")
        self.git(self.seed, "commit", "-m", "Unsupported catalog symlink")
        self.git(self.seed, "push", "origin", "main")
        self.boot(code=1)
        self.assertFalse(self.config.exists())
        self.assertFalse(self.checkout.exists())

    def test_git_and_external_instructions_survive_catalog_loss_and_detach(self):
        probe = self.root / "probe"
        try:
            probe.symlink_to(self.seed, target_is_directory=True)
        except OSError:
            self.skipTest("Symbolic link capability unavailable")
        probe.unlink()
        external = self.root / "external"
        external.mkdir()
        (external / "AGENTS.md").write_text("# External\n")
        (self.seed / "AGENTS.md").write_text("# Git instructions\n")
        self.document["skills"]["tool"]["mode"] = "link"
        self.document["repositories"] = {"personal": {"repository": str(self.remote)}}
        self.document["externals"] = {"documents": {}}
        self.document["instructions"] = {
            "personal": {"repo": "personal", "entry": "AGENTS.md", "entry_root": "agent"},
            "documents": {"external": "documents", "entry": "AGENTS.md", "entry_root": "agent",
                          "entry_destination": "EXTERNAL.md"}}
        self.save_remote()
        self.boot("--external", f"documents={external}")
        self.cli("apply")
        self.assertTrue(self.target.is_symlink())
        self.assertEqual((self.root / "agent/AGENTS.md").read_text(), "# Git instructions\n")
        self.assertEqual((self.root / "agent/EXTERNAL.md").read_text(), "# External\n")
        self.entry.unlink()
        self.cli("agent-hook", "personal", "--agent", "codex")
        self.cli("locate", "personal")
        self.cli("detach", "tool", "personal:entry", "personal:bundle")
        self.assertFalse(self.target.is_symlink())
        self.assertEqual((self.target / "SKILL.md").read_text(), "# Initial\n")
        self.assertFalse((self.root / "agent/AGENTS.md").is_symlink())
        self.cli("locate", "personal")

    def test_unknown_git_binding_fields_fail_offline(self):
        from agent_env_man.model import Config, Error
        binding = {"repository": str(self.remote), "path": "catalogs/personal.toml"}
        for extra in ({"typo": True}, {"type": "external"}, {"path": "."}, {"path": True},
                      {"repository": "relative"}, {"branch": False}, {"branch": ""}):
            with self.subTest(extra=extra), self.assertRaises(Error), \
                    patch.object(Git, "run", side_effect=AssertionError("configuration fetched")):
                Config(self.config, document={"version": 1, "catalog": {**binding, **extra}})

    def test_catalog_storage_cannot_overlap_orphaned_owned_targets(self):
        self.boot()
        self.cli("apply")
        path = self.root / "machine.toml.state/state.json"
        saved = json.loads(path.read_text())
        saved["items"]["tool"]["target"] = str(self.checkout / "unrelated")
        path.write_text(json.dumps(saved))
        with patch.object(Git, "run", side_effect=AssertionError("ownership preflight fetched")):
            self.assertIn("saved installation", self.cli("bootstrap", code=1))


if __name__ == "__main__":
    unittest.main()
