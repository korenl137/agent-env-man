"""Integration tests use only disposable homes and local Git remotes."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import tomlkit

from agent_env_man.cli import main
from agent_env_man.git_source import Git
from agent_env_man.model import Config, Error
from agent_env_man.storage import State, fingerprint, lock, observation


class Workflow(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="aem-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.config = self.root / "machine.toml"
        self.source = self.root / "personal"
        self.source.mkdir()
        (self.source / "rules").mkdir()
        (self.source / "rules/AGENTS.md").write_text("Original instructions\n", encoding="utf-8")
        (self.source / "skills/demo").mkdir(parents=True)
        (self.source / "skills/demo/SKILL.md").write_text("Demo skill\n", encoding="utf-8")
        self.manifest = self.source / "links.conf"
        self.manifest.write_text("all|rules/AGENTS.md|codex|AGENTS.md|link|rules\n", encoding="utf-8")
        self.target = self.home / ".codex/AGENTS.md"
        self.skill = self.home / ".agents/skills/demo"
        self.environment = patch.dict(os.environ, {"HOME": str(self.home), "USERPROFILE": str(self.home),
                                                   "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def run_cli(self, *args, code=0):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = main(["--config", str(self.config), *map(str, args)])
        self.assertEqual(result, code, f"{args}\nstdout: {stdout.getvalue()}\nstderr: {stderr.getvalue()}")
        return json.loads(stdout.getvalue()) if stdout.getvalue() else stderr.getvalue()

    def roots(self):
        return ["--root", f"codex={self.home / '.codex'}", "--root", f"skills={self.home / '.agents/skills'}",
                "--root", f"rules={self.home / '.agent-rules'}", "--root", f"home={self.home}"]

    def bootstrap(self, *args):
        return self.run_cli("bootstrap", "personal", "--path", self.source, *self.roots(), *args)

    def use_copy(self):
        self.manifest.write_text("all|rules/AGENTS.md|codex|AGENTS.md|copy|rules\n", encoding="utf-8")

    def use_merge(self):
        self.manifest.write_text("all|codex.json|codex|config.toml|codex-merge|settings\n", encoding="utf-8")
        self.write_settings(True)
        return self.home / ".codex/config.toml"

    def write_settings(self, value):
        (self.source / "codex.json").write_text(json.dumps({"version": 1, "set": [
            {"path": ["features", "example"], "value": value}]}), encoding="utf-8")

    def git(self, path, *args):
        result = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def commit(self, path, message):
        self.git(path, "add", "-A")
        self.git(path, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", message)

    def git_fixture(self):
        self.git(self.source, "init", "-b", "main")
        self.commit(self.source, "initial")
        self.remote = self.root / "remote.git"
        self.git(self.root, "clone", "--bare", str(self.source), str(self.remote))
        self.git(self.source, "remote", "add", "origin", str(self.remote))
        self.checkout = self.root / "checkout"
        self.run_cli("bootstrap", "personal", "--path", self.checkout, "--git", self.remote, *self.roots())

    def publish(self):
        self.commit(self.source, "published change")
        self.git(self.source, "push", "origin", "main")

    def status(self, key="personal:rules"):
        return next(i for i in self.run_cli("status")["items"] if i["item"] == key)

    def require_links(self):
        probe = self.root / "probe-link"
        try:
            probe.symlink_to(self.manifest)
        except OSError:
            self.skipTest("Symbolic link capability unavailable")
        probe.unlink()

    def test_bootstrap_and_dry_run_do_not_install(self):
        self.bootstrap()
        self.assertFalse(self.target.exists())
        self.run_cli("apply", "--dry-run")
        self.assertFalse(self.target.exists())

    def test_link_live_update_and_preserving_detach(self):
        self.require_links()
        self.bootstrap()
        self.run_cli("apply")
        self.assertTrue(self.target.is_symlink())
        (self.source / "rules/AGENTS.md").write_text("Updated\n", encoding="utf-8")
        self.assertEqual(self.target.read_text(), "Updated\n")
        self.assertEqual(self.status()["note"], "changed-live")
        self.run_cli("detach", "personal:rules")
        self.assertFalse(self.target.is_symlink())
        shutil.rmtree(self.source)
        self.assertEqual(self.target.read_text(), "Updated\n")

    def test_detach_tombstone_prevents_reinstallation(self):
        self.require_links()
        self.bootstrap()
        self.run_cli("apply")
        self.run_cli("detach", "personal:rules")
        self.assertEqual(self.run_cli("apply"), [])
        self.run_cli("apply", "--item", "personal:rules", "--reattach", "--replace")
        self.assertTrue(self.target.is_symlink())

    def test_directory_detach_preserves_files_empty_dirs_and_modes(self):
        self.require_links()
        self.manifest.write_text("all|skills/demo|skills|demo|link|demo\n", encoding="utf-8")
        (self.source / "skills/demo/empty").mkdir()
        (self.source / "skills/demo/run.sh").write_text("#!/bin/sh\n", encoding="utf-8")
        (self.source / "skills/demo/run.sh").chmod(0o755)
        self.bootstrap()
        self.run_cli("apply")
        expected = fingerprint(self.source / "skills/demo")
        self.run_cli("detach", "personal:demo")
        shutil.rmtree(self.source)
        self.assertFalse(self.skill.is_symlink())
        self.assertEqual(fingerprint(self.skill), expected)

    def test_directory_internal_symlink_rejected(self):
        self.require_links()
        (self.source / "skills/demo/external").symlink_to(self.source / "rules/AGENTS.md")
        self.manifest.write_text("all|skills/demo|skills|demo|copy|demo\n", encoding="utf-8")
        self.bootstrap()
        self.run_cli("apply", code=1)
        self.assertFalse(self.skill.exists())

    def test_unmanaged_target_requires_explicit_replacement_and_backup(self):
        self.use_copy()
        self.target.parent.mkdir(parents=True)
        self.target.write_text("Keep me", encoding="utf-8")
        self.bootstrap()
        self.run_cli("apply", code=1)
        self.assertEqual(self.target.read_text(), "Keep me")
        self.run_cli("apply", "--replace", code=1)
        self.run_cli("apply", "--item", "personal:rules", "--replace")
        backups = list(self.target.parent.glob("AGENTS.md.aem-backup-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), "Keep me")

    def test_matching_existing_copy_can_be_adopted(self):
        self.use_copy()
        self.target.parent.mkdir(parents=True)
        shutil.copy2(self.source / "rules/AGENTS.md", self.target)
        self.bootstrap()
        self.run_cli("apply", code=1)
        self.run_cli("apply", "--item", "personal:rules", "--adopt")
        self.assertEqual(self.status()["status"], "current")
        self.assertFalse(list(self.target.parent.glob("*.aem-backup-*")))

    def test_copy_distinguishes_stale_modified_conflict_and_missing(self):
        self.use_copy()
        self.bootstrap()
        self.run_cli("apply")
        (self.source / "rules/AGENTS.md").write_text("New source", encoding="utf-8")
        self.assertEqual(self.status()["status"], "stale")
        self.run_cli("apply")
        self.target.write_text("Local edit", encoding="utf-8")
        self.assertEqual(self.status()["status"], "modified-locally")
        (self.source / "rules/AGENTS.md").write_text("Another source", encoding="utf-8")
        self.assertEqual(self.status()["status"], "conflict")
        self.run_cli("apply", code=1)
        self.assertEqual(self.target.read_text(), "Local edit")
        self.target.unlink()
        self.assertEqual(self.status()["status"], "missing")

    def test_copy_directory_local_addition_is_not_deleted(self):
        self.manifest.write_text("all|skills/demo|skills|demo|copy|demo\n", encoding="utf-8")
        self.bootstrap()
        self.run_cli("apply")
        (self.skill / "mine.txt").write_text("Mine", encoding="utf-8")
        self.run_cli("apply", code=1)
        self.assertEqual((self.skill / "mine.txt").read_text(), "Mine")

    def test_preflight_checks_all_items_before_writing(self):
        self.use_copy()
        with self.manifest.open("a") as f:
            f.write("all|missing.txt|codex|other.txt|copy|other\n")
        self.bootstrap()
        self.run_cli("apply", code=1)
        self.assertFalse(self.target.exists())

    def test_new_manifest_item_is_not_automatically_registered(self):
        self.use_copy()
        self.bootstrap()
        with self.manifest.open("a") as f:
            f.write("all|skills/demo|skills|demo|copy|demo\n")
        self.run_cli("apply")
        self.assertFalse(self.skill.exists())
        self.assertEqual(self.status("personal:demo")["status"], "unregistered")

    def test_overlapping_targets_are_rejected(self):
        self.manifest.write_text("all|skills/demo|skills|demo|copy|demo\nall|rules/AGENTS.md|skills|demo/file|copy|file\n", encoding="utf-8")
        self.bootstrap_args_failure()

    def bootstrap_args_failure(self):
        self.run_cli("bootstrap", "personal", "--path", self.source, *self.roots(), code=1)
        self.assertFalse(self.config.exists())

    def test_traversal_is_rejected_without_config_write(self):
        self.manifest.write_text("all|rules/AGENTS.md|codex|../escape|copy|rules\n", encoding="utf-8")
        self.bootstrap_args_failure()

    def test_legacy_four_field_manifest(self):
        self.require_links()
        self.manifest.write_text("all|rules/AGENTS.md|codex|AGENTS.md\n", encoding="utf-8")
        report = self.bootstrap()
        self.assertTrue(report["registered_items"][0].startswith("legacy-"))
        self.run_cli("apply")
        self.assertEqual(self.target.read_text(), "Original instructions\n")

    def test_link_capability_failure_preserves_existing_file(self):
        self.bootstrap()
        self.target.parent.mkdir(parents=True)
        self.target.write_text("Original target", encoding="utf-8")
        with patch.object(Path, "symlink_to", side_effect=OSError("No privilege")):
            self.run_cli("apply", "--item", "personal:rules", "--replace", code=1)
        self.assertEqual(self.target.read_text(), "Original target")
        self.assertFalse(list(self.target.parent.glob("*.aem-backup-*")))

    def test_merge_preserves_unmanaged_values_and_comments(self):
        target = self.use_merge()
        target.parent.mkdir(parents=True)
        target.write_text('# personal comment\nmodel = "keep-me"\n\n[features]\nother = false # retained\n', encoding="utf-8")
        self.bootstrap()
        self.run_cli("apply")
        text = target.read_text()
        self.assertIn('# personal comment\nmodel = "keep-me"', text)
        self.assertIn("other = false # retained", text)
        self.assertTrue(tomlkit.parse(text)["features"]["example"])
        self.write_settings(False)
        self.assertEqual(self.status("personal:settings")["status"], "stale")
        self.run_cli("apply")
        self.assertFalse(tomlkit.parse(target.read_text())["features"]["example"])

    def test_merge_local_changes_are_conflicts_but_unmanaged_changes_are_not(self):
        target = self.use_merge()
        self.bootstrap()
        self.run_cli("apply")
        target.write_text(target.read_text() + 'other = "local"\n', encoding="utf-8")
        self.assertEqual(self.status("personal:settings")["status"], "current")
        target.write_text(target.read_text().replace("example = true", "example = false"), encoding="utf-8")
        self.assertEqual(self.status("personal:settings")["status"], "modified-locally")
        self.run_cli("apply", code=1)
        before = target.read_bytes()
        self.run_cli("detach", "personal:settings")
        self.assertEqual(target.read_bytes(), before)

    def test_merge_removed_keys_are_preserved(self):
        target = self.use_merge()
        self.bootstrap()
        self.run_cli("apply")
        (self.source / "codex.json").write_text('{"version":1,"set":[]}', encoding="utf-8")
        self.run_cli("apply", code=1)
        self.assertTrue(tomlkit.parse(target.read_text())["features"]["example"])

    def test_merge_invalid_toml_and_symlink_are_not_replaced(self):
        target = self.use_merge()
        target.parent.mkdir(parents=True)
        target.write_text("[broken", encoding="utf-8")
        self.bootstrap()
        self.run_cli("apply", "--item", "personal:settings", "--replace", code=1)
        self.assertEqual(target.read_text(), "[broken")
        self.require_links()
        target.unlink()
        other = self.root / "other.toml"
        other.write_text("", encoding="utf-8")
        target.symlink_to(other)
        self.run_cli("apply", "--item", "personal:settings", "--replace", code=1)
        self.assertTrue(target.is_symlink())
        self.assertEqual(other.read_text(), "")

    def test_merge_never_replaces_an_unmanaged_table(self):
        target = self.use_merge()
        target.parent.mkdir(parents=True)
        target.write_text('[features.example]\nkeep = "mine"\n', encoding="utf-8")
        self.bootstrap()
        self.run_cli("apply", "--item", "personal:settings", "--replace", code=1)
        self.assertIn('keep = "mine"', target.read_text())

    def test_git_end_to_end_update_changes_link_without_apply(self):
        self.require_links()
        self.git_fixture()
        self.run_cli("apply")
        (self.source / "rules/AGENTS.md").write_text("From remote", encoding="utf-8")
        self.publish()
        self.run_cli("update")
        self.assertEqual(self.target.read_text(), "From remote")
        self.assertEqual(self.status()["note"], "changed-live")

    def test_git_sync_updates_copies(self):
        self.use_copy()
        self.git_fixture()
        self.run_cli("apply")
        (self.source / "rules/AGENTS.md").write_text("From remote", encoding="utf-8")
        self.publish()
        self.run_cli("update")
        self.assertEqual(self.target.read_text(), "Original instructions\n")
        self.run_cli("sync")
        self.assertEqual(self.target.read_text(), "From remote")
        self.assertEqual(self.run_cli("sync", "--min-interval", "600")["status"], "throttled")

    def test_git_dirty_checkout_and_network_failure_preserve_installation(self):
        self.use_copy()
        self.git_fixture()
        self.run_cli("apply")
        (self.checkout / "unfinished.md").write_text("unfinished", encoding="utf-8")
        self.run_cli("update", code=1)
        self.assertEqual((self.checkout / "unfinished.md").read_text(), "unfinished")
        self.run_cli("apply", code=1)
        (self.checkout / "unfinished.md").unlink()
        self.remote.rename(self.root / "unavailable-remote.git")
        report = self.run_cli("sync", code=1)
        self.assertEqual(report["apply"], "skipped")
        self.assertEqual(self.target.read_text(), "Original instructions\n")

    def test_git_divergence_is_not_reset(self):
        self.use_copy()
        self.git_fixture()
        (self.checkout / "local.txt").write_text("local", encoding="utf-8")
        self.commit(self.checkout, "local work")
        head = self.git(self.checkout, "rev-parse", "HEAD")
        (self.source / "remote.txt").write_text("remote", encoding="utf-8")
        self.publish()
        self.run_cli("update", code=1)
        self.assertEqual(self.git(self.checkout, "rev-parse", "HEAD"), head)

    def test_git_removal_of_live_link_is_blocked_even_if_manifest_row_removed(self):
        self.require_links()
        self.git_fixture()
        self.run_cli("apply")
        (self.source / "rules/AGENTS.md").unlink()
        self.manifest.write_text("# removed\n", encoding="utf-8")
        self.publish()
        self.run_cli("update", code=1)
        self.assertEqual(self.target.read_text(), "Original instructions\n")
        self.run_cli("detach", "personal:rules")
        self.run_cli("update")
        self.assertEqual(self.target.read_text(), "Original instructions\n")
        self.assertEqual(self.run_cli("apply"), [])

    def test_detach_orphaned_manifest_item_preserves_current_contents(self):
        self.require_links()
        self.bootstrap()
        self.run_cli("apply")
        self.manifest.write_text("# No longer declared\n", encoding="utf-8")
        self.assertEqual(self.status()["status"], "orphaned-or-source-unavailable")
        self.run_cli("detach", "personal:rules")
        self.assertEqual(self.target.read_text(), "Original instructions\n")
        self.assertEqual(self.run_cli("apply"), [])

    def test_git_detached_head_still_reports_installed_targets(self):
        self.use_copy()
        self.git_fixture()
        self.run_cli("apply")
        self.git(self.checkout, "checkout", "--detach")
        report = self.run_cli("status")
        self.assertIn("expected attached branch", report["sources"][0]["error"])
        self.assertEqual(report["items"][0]["status"], "current")

    def test_ignored_files_block_git_update(self):
        self.use_copy()
        (self.source / ".gitignore").write_text("private.txt\n", encoding="utf-8")
        self.git_fixture()
        (self.checkout / "private.txt").write_text("preserve", encoding="utf-8")
        self.run_cli("update", code=1)
        self.assertEqual((self.checkout / "private.txt").read_text(), "preserve")

    def test_machine_copy_override_is_explicit_and_recorded(self):
        self.bootstrap()
        document = tomlkit.parse(self.config.read_text())
        document["sources"]["personal"]["modes"] = {"rules": "copy"}
        self.config.write_text(tomlkit.dumps(document), encoding="utf-8")
        self.run_cli("apply")
        self.assertFalse(self.target.is_symlink())
        self.assertEqual(self.status()["mode"], "copy")

    def test_merge_boolean_is_not_confused_with_integer(self):
        target = self.use_merge()
        self.bootstrap()
        self.run_cli("apply")
        target.write_text(target.read_text().replace("example = true", "example = 1"), encoding="utf-8")
        self.assertEqual(self.status("personal:settings")["status"], "modified-locally")
        self.run_cli("apply", code=1)

    def test_update_refuses_a_symlink_inside_live_directory(self):
        self.require_links()
        self.manifest.write_text("all|skills/demo|skills|demo|link|demo\n", encoding="utf-8")
        self.git_fixture()
        self.run_cli("apply")
        (self.source / "skills/demo/link").symlink_to("SKILL.md")
        self.publish()
        self.run_cli("update", code=1)
        self.assertFalse((self.skill / "link").exists())

    def test_status_refresh_fetches_without_changing_checkout(self):
        self.use_copy()
        self.git_fixture()
        head = self.git(self.checkout, "rev-parse", "HEAD")
        (self.source / "rules/AGENTS.md").write_text("New", encoding="utf-8")
        self.publish()
        report = self.run_cli("status", "--refresh")
        self.assertEqual(report["sources"][0]["remote_relation"], "behind")
        self.assertEqual(self.git(self.checkout, "rev-parse", "HEAD"), head)

    def test_failed_clone_does_not_register_source(self):
        self.run_cli("bootstrap", "personal", "--path", self.root / "checkout", "--git", self.root / "missing.git", code=1)
        self.assertFalse(self.config.exists())
        self.assertFalse((self.root / "checkout").exists())

    def test_exception_during_replace_restores_old_target(self):
        self.use_copy()
        self.bootstrap()
        self.run_cli("apply")
        (self.source / "rules/AGENTS.md").write_text("new", encoding="utf-8")
        original = os.replace

        def fail_stage(src, dst):
            if Path(src).name.startswith(".aem-stage-"):
                raise OSError("injected failure")
            return original(src, dst)

        with patch("agent_env_man.manager.os.replace", side_effect=fail_stage):
            self.run_cli("apply", code=1)
        self.assertEqual(self.target.read_text(), "Original instructions\n")
        self.assertIsNone(State(Config(self.config).state_dir).data["pending"])

    def test_crash_journal_can_restore_a_target(self):
        self.use_copy()
        self.bootstrap()
        self.run_cli("apply")
        cfg = Config(self.config)
        state = State(cfg.state_dir)
        before = observation(self.target)
        backup, stage = self.target.with_name("backup"), self.target.with_name("stage")
        stage.write_text("new", encoding="utf-8")
        state.data["pending"] = {"key": "personal:rules", "target": str(self.target), "stage": str(stage),
                                 "backup": str(backup), "before": before, "after": observation(stage)}
        state.save()
        os.replace(self.target, backup)
        os.replace(stage, self.target)
        self.run_cli("apply", code=1)
        self.run_cli("recover")
        self.assertEqual(self.target.read_text(), "Original instructions\n")

    def test_recovery_does_not_overwrite_concurrent_user_edit(self):
        self.use_copy()
        self.bootstrap()
        self.run_cli("apply")
        cfg = Config(self.config)
        state = State(cfg.state_dir)
        before = observation(self.target)
        backup, stage = self.target.with_name("backup"), self.target.with_name("stage")
        stage.write_text("new", encoding="utf-8")
        state.data["pending"] = {"key": "personal:rules", "target": str(self.target), "stage": str(stage),
                                 "backup": str(backup), "before": before, "after": observation(stage)}
        state.save()
        os.replace(self.target, backup)
        self.target.write_text("user edit", encoding="utf-8")
        self.run_cli("recover", code=1)
        self.assertEqual(self.target.read_text(), "user edit")
        self.assertEqual(backup.read_text(), "Original instructions\n")

    def test_lock_contention_does_not_run_commands(self):
        self.use_copy()
        self.bootstrap()
        with lock(Config(self.config).state_dir):
            self.run_cli("apply", code=1)
        self.assertFalse(self.target.exists())

    def test_status_observes_copy_when_source_is_missing(self):
        self.use_copy()
        self.bootstrap()
        self.run_cli("apply")
        shutil.rmtree(self.source)
        self.assertEqual(self.status()["installation"], "matches-last-apply")
        self.run_cli("detach", "personal:rules")
        self.assertEqual(self.target.read_text(), "Original instructions\n")

    def test_timeout_terminates_a_stalled_subprocess(self):
        real_popen = subprocess.Popen
        processes = []

        def stalled(command, **kwargs):
            if command[0] != "git":
                return real_popen(command, **kwargs)
            process = real_popen([sys.executable, "-c", "import time; time.sleep(60)"], **kwargs)
            processes.append(process)
            return process

        start = time.monotonic()
        with patch("agent_env_man.git_source.subprocess.Popen", side_effect=stalled):
            with self.assertRaisesRegex(Error, "timed out"):
                Git(timeout=0.1).run(None, "--version")
        self.assertLess(time.monotonic() - start, 6)
        self.assertIsNotNone(processes[0].poll())


if __name__ == "__main__":
    unittest.main()
