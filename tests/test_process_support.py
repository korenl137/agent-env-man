"""Fixture launch options preserve process contracts while hiding windows."""

from contextlib import ExitStack
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import process_support


class HiddenProcesses(unittest.TestCase):
    def windows(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(process_support, 'os', SimpleNamespace(name='nt')))
        stack.enter_context(patch.multiple(
            subprocess, CREATE_NO_WINDOW=0x08000000, DETACHED_PROCESS=8,
            CREATE_NEW_CONSOLE=16, STARTF_USESHOWWINDOW=1, SW_HIDE=0,
            STARTUPINFO=lambda: SimpleNamespace(dwFlags=0, wShowWindow=1), create=True))

    def test_capture_adds_no_window_and_preserves_options_and_result(self):
        self.windows()
        expected = subprocess.CompletedProcess(['tool'], 7, 'output', 'failure')
        environment = {'FIXTURE': 'temporary'}
        with patch.object(subprocess, 'run', return_value=expected) as run:
            actual = process_support.run_hidden(
                ['tool'], capture_output=True, text=True, timeout=9,
                check=False, env=environment, cwd='fixture', creationflags=512)
        self.assertIs(actual, expected)
        self.assertEqual(run.call_args.args, (['tool'],))
        options = run.call_args.kwargs
        startup = options.pop('startupinfo')
        self.assertEqual(options, dict(capture_output=True, text=True, timeout=9,
                         check=False, env=environment, cwd='fixture',
                         creationflags=512 | 0x08000000))
        self.assertEqual(startup.dwFlags, 1)
        self.assertEqual(startup.wShowWindow, 0)

    def test_popen_hides_ordinary_launch_and_returns_original_process(self):
        self.windows()
        with patch.object(subprocess, 'Popen') as popen:
            actual = process_support.popen_hidden(['tool'], stdin=subprocess.PIPE)
        self.assertIs(actual, popen.return_value)
        self.assertEqual(popen.call_args.args, (['tool'],))
        self.assertEqual(popen.call_args.kwargs['creationflags'], 0x08000000)
        self.assertEqual(popen.call_args.kwargs['stdin'], subprocess.PIPE)

    def test_explicit_console_modes_are_preserved_and_hidden(self):
        self.windows()
        for flags in (8, 16, 8 | 512, 16 | 512):
            for wrapper, api in ((process_support.run_hidden, 'run'),
                                 (process_support.popen_hidden, 'Popen')):
                with self.subTest(flags=flags, api=api), patch.object(subprocess, api) as launch:
                    wrapper(['tool'], creationflags=flags)
                self.assertEqual(launch.call_args.kwargs['creationflags'], flags)
                self.assertEqual(launch.call_args.kwargs['startupinfo'].wShowWindow, 0)

    def test_caller_startup_settings_are_copied_without_changing_handles(self):
        self.windows()
        attributes = {'handle_list': [41, 42]}
        startup = SimpleNamespace(dwFlags=256, wShowWindow=3, hStdOutput=41,
                                  lpAttributeList=attributes)
        with patch.object(subprocess, 'Popen') as popen:
            process_support.popen_hidden(['tool'], startupinfo=startup)
        actual = popen.call_args.kwargs['startupinfo']
        self.assertIsNot(actual, startup)
        self.assertEqual((actual.dwFlags, actual.wShowWindow, actual.hStdOutput), (257, 0, 41))
        self.assertEqual((startup.dwFlags, startup.wShowWindow), (256, 3))
        self.assertIs(actual.lpAttributeList, attributes)

    def test_posix_passes_options_through_unchanged(self):
        options = dict(stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       text=True, cwd='fixture', start_new_session=True)
        with patch.object(process_support, 'os', SimpleNamespace(name='posix')):
            for wrapper, api in ((process_support.run_hidden, 'run'),
                                 (process_support.popen_hidden, 'Popen')):
                with self.subTest(api=api), patch.object(subprocess, api) as launch:
                    result = wrapper(['tool'], **options)
                launch.assert_called_once_with(['tool'], **options)
                self.assertIs(result, launch.return_value)

    def test_exit_timeout_and_launch_errors_are_not_intercepted(self):
        self.windows()
        failures = (subprocess.CalledProcessError(7, ['tool'], output='out', stderr='err'),
                    subprocess.TimeoutExpired(['tool'], 9), FileNotFoundError('tool'))
        for failure in failures:
            with self.subTest(error=type(failure).__name__), patch.object(
                    subprocess, 'run', side_effect=failure) as run:
                with self.assertRaises(type(failure)) as caught:
                    process_support.run_hidden(['tool'], check=True, timeout=9)
            self.assertIs(caught.exception, failure)
            self.assertTrue(run.call_args.kwargs['check'])
            self.assertEqual(run.call_args.kwargs['timeout'], 9)


@unittest.skipUnless(os.name == 'nt', 'Native Windows console visibility')
class NativeHiddenProcesses(unittest.TestCase):
    def test_virtualenv_children_have_no_console_under_ordinary_and_detached_parents(self):
        child = (
            'import ctypes,json; from ctypes import wintypes; '
            'kernel=ctypes.WinDLL("kernel32",use_last_error=True); '
            'user=ctypes.WinDLL("user32",use_last_error=True); '
            'kernel.GetConsoleWindow.restype=wintypes.HWND; '
            'user.IsWindowVisible.argtypes=[wintypes.HWND]; '
            'user.IsWindowVisible.restype=wintypes.BOOL; '
            'handle=kernel.GetConsoleWindow(); '
            'print(json.dumps({"handle":handle or 0,"visible":bool(user.IsWindowVisible(handle))}))')
        parent = (
            'import sys; sys.path.insert(0,sys.argv[1]); '
            'from process_support import run_hidden; '
            'result=run_hidden([sys.executable,"-c",sys.argv[2]],'
            'capture_output=True,text=True,timeout=10,check=True); '
            'print(result.stdout,end="")')
        for flags in (0, subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP):
            with self.subTest(parent_flags=flags):
                result = process_support.run_hidden(
                    [sys.executable, '-c', parent, str(Path(__file__).resolve().parent), child],
                    creationflags=flags, capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), {'handle': 0, 'visible': False})


if __name__ == '__main__':
    unittest.main()
