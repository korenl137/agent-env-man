#!/usr/bin/env python3
"""Install this checkout with uv and invoke its machine setup command."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--shell', action='append', default=[], choices=['bash', 'zsh', 'powershell'])
    parser.add_argument('--agent', action='append', default=[], choices=['codex'])
    parser.add_argument('--remove-shell', action='append', default=[], choices=['bash', 'zsh', 'powershell'])
    parser.add_argument('--remove-agent', action='append', default=[], choices=['codex'])
    parser.add_argument('--config', type=Path)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    try:
        if sys.version_info < (3, 11):
            raise RuntimeError('Python 3.11 or later is required')
        for tool in ('uv', 'git'):
            if not shutil.which(tool):
                raise RuntimeError(f'{tool} must be installed and available on PATH')
        uv = shutil.which('uv')
        repository = Path(__file__).resolve().parents[1]
        install = [uv, 'tool', 'install', '--reinstall', '--python', sys.executable, str(repository)]
        # uv reports its executable directory without changing shell profiles.
        bin_dir = Path(subprocess.run([uv, 'tool', 'dir', '--bin'], check=True, capture_output=True,
                                      text=True).stdout.strip()).expanduser().absolute()
        executable = bin_dir / ('aem.exe' if os.name == 'nt' else 'aem')
        command = [str(executable)]
        if args.config:
            command += ['--config', str(args.config.expanduser().absolute())]
        command += ['setup', '--executable', str(executable)]
        for flag, values in (('--shell', args.shell), ('--agent', args.agent),
                             ('--remove-shell', args.remove_shell), ('--remove-agent', args.remove_agent)):
            for value in values:
                command += [flag, value]
        if args.dry_run:
            print(json.dumps({'install': install, 'configure': command + ['--dry-run'],
                              'note': 'No installation or profile changes. Run the configure preview with an installed AEM.'}, indent=2))
            if executable.is_file():
                return subprocess.run(command + ['--dry-run'], check=False).returncode
            return 0
        subprocess.run(install, check=True)
        return subprocess.run(command, check=False).returncode
    except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
        print(f'AEM setup: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
