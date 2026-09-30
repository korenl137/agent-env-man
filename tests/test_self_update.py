"""Release updates use local Git fixtures and never change real uv installations."""
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import tomlkit

from agent_env_man import self_update
from agent_env_man.model import Config, Error
from agent_env_man.storage import State, lock
from test_setup import SetupFixture


class Releases(unittest.TestCase):
    def test_semver_boundaries_and_annotated_tags(self):
        refs = '\n'.join(f'{str(i) * 40}\trefs/tags/v{v}' for i, v in enumerate(
            ['0.2.0', '0.2.1', '0.2.10', '0.3.0', '1.0.0', '1.1.0', '1.2.0', '2.0.0', '3.0.0rc1']))
        refs += '\n' + 'a' * 40 + '\trefs/tags/v0.2.10^{}'
        self.assertEqual(self_update.select_release(refs, '0.2.0', 'compatible'),
                         {'version': '0.2.10', 'revision': 'a' * 40})
        self.assertEqual(self_update.select_release(refs, '1.0.0', 'compatible')['version'], '1.2.0')
        self.assertEqual(self_update.select_release(refs, '0.2.0', 'breaking')['version'], '2.0.0')
        self.assertIsNone(self_update.select_release(refs, '2.0.0', 'compatible'))
        self.assertIsNone(self_update.select_release(refs, '0.2.0', 'off'))
        with self.assertRaises(ValueError):
            self_update.select_release(refs, '0.2.0.dev1', 'compatible')

    def test_configuration_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'machine.toml'
            for settings in ({'mode': 'stable'}, {'mode': 'compatible'}, {'other': True},
                             {'python': 'relative'}, {'repository': '-remote'}, {'repository': 'git@host'}, {'mode': []},
                             {'python': str(Path(directory) / 'tools/python'), 'tool_dir': str(Path(directory) / 'tools')}):
                with self.subTest(settings=settings), self.assertRaises(Error):
                    Config(path, document={'version': 1, 'self_update': settings})
            Config(path, document={'version': 1, 'self_update': {'mode': 'off'}})


class SelfUpdate(SetupFixture):
    def register(self, mode='compatible'):
        self.tools = self.root / 'uv tools'
        self.bin = self.root / 'uv bin'
        self.uv = self.root / 'fake-uv'
        self.uv.write_text('fake')
        self.settings = {'mode': mode, 'repository': str(self.repo), 'python': sys.executable,
                         'uv': str(self.uv), 'tool_dir': str(self.tools), 'bin_dir': str(self.bin)}
        options = ['--self-update', mode]
        for field, value in self.settings.items():
            if field != 'mode':
                options += ['--update-' + field.replace('_', '-'), value]
        self.setup_cli('--shell', 'bash', *options)
        return Config(self.config)

    def finish_worker(self, config):
        # In-process tests close the lifetime pipe while their test runner
        # remains alive; model a terminated requester before releasing EOF.
        attempt = self_update.read_result(self_update.result_path(config))
        request_path = config.state_dir / 'self-update-worker' / attempt['token'] / 'request.json'
        request = json.loads(request_path.read_text())
        request['parent_pid'] = 0
        self_update.write_json(request_path, request)
        self_update.close_workers()

    def release(self, value, *, tag=None, name='agent-env-man'):
        (self.repo / 'pyproject.toml').write_text(f'[project]\nname = "{name}"\nversion = "{value}"\n')
        self.commit(self.repo)
        self.git(self.repo, 'tag', tag or 'v' + value)

    def test_settings_preserved_changed_and_preview_read_only(self):
        config = self.register()
        self.setup_cli('--shell', 'zsh')
        self.assertEqual(Config(self.config).doc['self_update'], self.settings)
        before = self.config.read_bytes()
        self.setup_cli('--self-update', 'breaking', '--dry-run')
        self.assertEqual(self.config.read_bytes(), before)
        self.setup_cli('--self-update', 'off')
        self.assertEqual(self.run_cli('self', 'status')['mode'], 'off')
        self.assertFalse(self_update.result_path(config).exists())
        with patch('agent_env_man.self_update.subprocess.Popen') as spawn:
            self.run_cli('self', 'update', '--dry-run')
            spawn.assert_not_called()
        self.assertFalse(self_update.result_path(config).exists())

    def test_startup_queue_throttle_and_explicit_retry(self):
        config = self.register()
        with patch('agent_env_man.self_update.subprocess.Popen') as spawn:
            self.run_cli('startup', '--trigger', 'shell-start')
            self.assertEqual(spawn.call_count, 1)
            self.assertEqual(self_update.read_result(self_update.result_path(config))['status'], 'queued')
            self.run_cli('startup', '--trigger', 'agent-start')
            self.assertEqual(spawn.call_count, 1)
            self.run_cli('self', 'update')
            self.assertEqual(spawn.call_count, 2)
        self_update.close_workers()
        self.catalog.write_text('broken TOML [')
        # Self commands remain independent of content declaration validity.
        self.assertEqual(self.run_cli('self', 'status')['mode'], 'compatible')

    def test_spawn_failure_is_recorded_and_throttled(self):
        config = self.register()
        with patch('agent_env_man.self_update.subprocess.Popen', side_effect=OSError('cannot launch')):
            self.run_cli('startup', '--trigger', 'agent-start')
        result = self_update.read_result(self_update.result_path(config))
        self.assertEqual(result['status'], 'failed')
        with patch('agent_env_man.self_update.subprocess.Popen') as spawn:
            self.run_cli('startup', '--trigger', 'shell-start')
            spawn.assert_not_called()

    def test_missing_external_runtime_failure_is_throttled(self):
        config = self.register()
        self.uv.unlink()
        self.run_cli('startup', '--trigger', 'agent-start')
        self.assertEqual(self_update.read_result(self_update.result_path(config))['status'], 'failed')
        self.run_cli('startup', '--trigger', 'shell-start')
        self.assertEqual(State(config.state_dir).data['startup']['self_update']['status'], 'throttled')

    def test_release_metadata_verified_and_commit_pinned(self):
        self.register()
        self.release('0.2.1')
        self.release('0.3.0')
        calls = []
        real_run = subprocess.run
        def run(command, **kwargs):
            if command[0] == str(self.uv):
                calls.append((command, kwargs))
                return subprocess.CompletedProcess(command, 0, stdout='agent-env-man v0.2.0\n - aem\n')
            return real_run(command, **kwargs)
        with patch('agent_env_man.self_update.subprocess.run', side_effect=run):
            outcome = self_update.perform({'settings': self.settings})
        self.assertEqual(outcome['version'], '0.2.1')
        install, options = calls[-1]
        self.assertIn('@' + outcome['revision'], install[-2])
        self.assertEqual(options['env']['UV_TOOL_DIR'], str(self.tools))
        self.assertEqual(options['env']['UV_TOOL_BIN_DIR'], str(self.bin))
        self.release('0.2.2', tag='v0.2.3')
        calls.clear()
        with patch('agent_env_man.self_update.subprocess.run', side_effect=run), self.assertRaises(ValueError):
            self_update.perform({'settings': self.settings})
        self.assertEqual(len(calls), 1)  # Metadata failure never reaches install.

    def test_actual_installed_version_prevents_cross_config_downgrade(self):
        self.register()
        self.release('0.2.1')
        self.release('0.3.0')
        real_run = subprocess.run
        def run(command, **kwargs):
            if command[0] == str(self.uv):
                self.assertEqual(command[-1], 'list')
                return subprocess.CompletedProcess(command, 0, stdout='agent-env-man v0.3.0\n')
            return real_run(command, **kwargs)
        with patch('agent_env_man.self_update.subprocess.run', side_effect=run):
            self.assertEqual(self_update.perform({'settings': self.settings, 'current': '0.2.0'}),
                             {'status': 'up-to-date'})

    @unittest.skipIf(os.name == 'nt', 'Fake executable integration requires a POSIX shebang')
    def test_worker_waits_for_parent_then_updates_with_local_git(self):
        config = self.register()
        self.release('0.2.1')
        calls = self.root / 'uv-calls.json'
        self.uv.write_text('#!' + sys.executable + '\nimport json, sys\nfrom pathlib import Path\n'
                           'if sys.argv[-1] == "list":\n print("agent-env-man v0.2.0\\n - aem")\n'
                           'else:\n Path(' + repr(str(calls)) + ').write_text(json.dumps(sys.argv[1:]))\n')
        self.uv.chmod(0o755)
        # Real lifetime pipe: worker must do no update until it receives EOF.
        with lock(config.state_dir):
            attempt = self_update.schedule(config)
        child = self_update._children[-1]
        time.sleep(0.15)
        self.assertFalse(calls.exists())
        self.assertIsNone(child.poll())
        self.finish_worker(config)
        self.assertEqual(child.wait(timeout=15), 0)
        result = self_update.read_result(self_update.result_path(config))
        self.assertEqual(result['token'], attempt['token'])
        self.assertEqual(result['status'], 'updated')
        self.assertEqual(result['version'], '0.2.1')
        self.assertIn('install', json.loads(calls.read_text()))

    def test_installation_lock_serializes_configs_and_startup_is_fail_open(self):
        config = self.register()
        with lock(self_update.installation_lock(self.settings)):
            self.assertEqual(self.run_cli('startup', '--trigger', 'agent-start'), {})
            self.run_cli('self', 'update', code=1)
        self.assertFalse(self_update.result_path(config).exists())

    def test_corrupt_attempt_clock_fails_open_without_launching(self):
        config = self.register()
        self_update.write_json(self_update.result_path(config), {'time': 'invalid'})
        with patch('agent_env_man.self_update.subprocess.Popen') as spawn:
            self.run_cli('startup', '--trigger', 'shell-start')
            spawn.assert_not_called()
        self.assertEqual(State(config.state_dir).data['startup']['self_update']['status'], 'failed')

    @unittest.skipIf(os.name == 'nt', 'Fake executable integration requires a POSIX shebang')
    def test_worker_failure_recorded_and_explicit_retry_succeeds(self):
        config = self.register()
        self.release('0.2.1')
        self.uv.write_text('#!' + sys.executable + '\nimport sys\n'
                           'if sys.argv[-1] == "list":\n print("agent-env-man v0.2.0")\n'
                           'else:\n sys.exit(1)\n')
        self.uv.chmod(0o755)
        self_update.schedule(config)
        child = self_update._children[-1]
        self.finish_worker(config)
        self.assertEqual(child.wait(timeout=15), 0)
        self.assertEqual(self_update.read_result(self_update.result_path(config))['status'], 'failed')
        self.uv.write_text(self.uv.read_text().replace('sys.exit(1)', 'sys.exit(0)'))
        # Exercise the real entrypoint: stdout must finish without waiting on
        # worker-owned handles, and the external child outlives the callback.
        response = subprocess.run([sys.executable, '-m', 'agent_env_man', '--config', str(self.config),
                                   'self', 'update'], capture_output=True, text=True, timeout=5)
        self.assertEqual(response.returncode, 0, response.stderr)
        self.assertEqual(json.loads(response.stdout)['status'], 'queued')
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            result = self_update.read_result(self_update.result_path(config))
            if result.get('status') != 'queued':
                break
            time.sleep(0.02)
        self.assertEqual(result['status'], 'updated')

    @unittest.skipIf(os.name == 'nt', 'Fake executable integration requires a POSIX shebang')
    def test_queued_worker_cancels_for_pending_recovery(self):
        config = self.register()
        self_update.schedule(config)
        child = self_update._children[-1]
        state = State(config.state_dir)
        state.data['pending'] = {}  # Even an empty journal blocks replacement.
        state.save()
        self.finish_worker(config)
        self.assertEqual(child.wait(timeout=15), 0)
        result = self_update.read_result(self_update.result_path(config))
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(result['reason'], 'Recovery is pending')

    @unittest.skipIf(os.name == 'nt', 'Fake executable integration requires a POSIX shebang')
    def test_queued_worker_cancels_when_policy_changes(self):
        config = self.register()
        with lock(config.state_dir):
            self_update.schedule(config)
        child = self_update._children[-1]
        self.setup_cli('--self-update', 'off')
        self.finish_worker(config)
        self.assertEqual(child.wait(timeout=15), 0)
        self.assertEqual(self_update.read_result(self_update.result_path(config))['status'], 'cancelled')


class InstallerChoices(SetupFixture):
    def module(self):
        spec = importlib.util.spec_from_file_location('installer', Path(__file__).parents[1] / 'scripts/setup.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_initial_prompt_and_repeat_preserves_selection(self):
        module = self.module()
        calls = []
        def run(command, **kwargs):
            calls.append(command)
            output = str(self.root / 'tools') if command[-1] == 'dir' else str(self.executable.parent)
            return subprocess.CompletedProcess(command, 0, stdout=output)
        with patch.object(module.shutil, 'which', side_effect=lambda n: '/fake/' + n), \
                patch.object(module.subprocess, 'run', side_effect=run), \
                patch.object(module.sys.stdin, 'isatty', return_value=True), \
                patch('builtins.input', side_effect=['invalid', 'compatible']) as prompt, redirect_stdout(io.StringIO()):
            self.assertEqual(module.main(['--shell', 'bash', '--config', str(self.config)]), 0)
            self.assertEqual(prompt.call_count, 2)
        self.assertIn('compatible', calls[-1])
        self.config.write_text('version = 1\n[self_update]\nmode = "breaking"\nrepository = "https://example.test/aem.git"\n')
        with patch.object(module.shutil, 'which', side_effect=lambda n: '/fake/' + n), \
                patch.object(module.subprocess, 'run', side_effect=run), patch('builtins.input') as prompt:
            self.assertEqual(module.main(['--shell', 'bash', '--config', str(self.config)]), 0)
            prompt.assert_not_called()
        self.assertNotIn('--self-update', calls[-1])
        self.assertNotIn('--update-repository', calls[-1])
