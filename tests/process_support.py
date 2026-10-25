"""Launch test fixtures without displaying Windows console windows."""

import copy
import os
import subprocess


def _hidden_options(options):
    if os.name != 'nt':
        return options
    options = dict(options)
    flags = options.get('creationflags', 0)
    # Explicit console modes are part of native process regression fixtures.
    if not flags & (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_CONSOLE):
        flags |= subprocess.CREATE_NO_WINDOW
    options['creationflags'] = flags
    startup = options.get('startupinfo')
    startup = copy.copy(startup) if startup is not None else subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    options['startupinfo'] = startup
    return options


def run_hidden(*args, **kwargs):
    return subprocess.run(*args, **_hidden_options(kwargs))


def popen_hidden(*args, **kwargs):
    return subprocess.Popen(*args, **_hidden_options(kwargs))
