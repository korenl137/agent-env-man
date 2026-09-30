"""Explicit, repeatable machine integration; catalog policy never edits profiles."""
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import tomlkit

from .agents import profile
from .manager import Plan
from .model import Config, Error, Item, absolute, overlaps
from .storage import exists, is_reparse, observation


def regular(path):
    """Do not follow even an intermediate profile redirect when writing hooks."""
    for part in (path, *path.parents):
        if exists(part) and (part.is_symlink() or is_reparse(part)):
            raise Error(f'Setup target must not redirect: {part}')
    if exists(path) and not path.is_file():
        raise Error(f'Setup target must be a regular file: {path}')


def shell_path(name):
    if name == 'bash':
        return Path.home() / '.bashrc'
    if name == 'zsh':
        return Path(os.environ.get('ZDOTDIR') or Path.home()).expanduser() / '.zshrc'
    executable = shutil.which('pwsh') or shutil.which('powershell.exe')
    if not executable:
        raise Error('PowerShell is not available; install it before selecting powershell')
    value = subprocess.run([executable, '-NoLogo', '-NoProfile', '-NonInteractive', '-Command',
                            '[Console]::Write($PROFILE.CurrentUserAllHosts)'],
                           capture_output=True, text=True, check=True, timeout=10).stdout.strip()
    if not value or not Path(value).is_absolute():
        raise Error('PowerShell returned an invalid profile path')
    return Path(value)


def shell_block(name, config, executable, bin_dir):
    identity = hashlib.sha256(str(config).encode()).hexdigest()[:20]
    start, end = f'# >>> AEM {identity} >>>', f'# <<< AEM {identity} <<<'
    if name == 'powershell':
        quote = lambda value: "'" + str(value).replace("'", "''") + "'"
        body = [f"if (($env:PATH -split [IO.Path]::PathSeparator) -notcontains {quote(bin_dir)}) {{",
                f"    $env:PATH = {quote(bin_dir)} + [IO.Path]::PathSeparator + $env:PATH", '}',
                "$aemBatch = [Environment]::GetCommandLineArgs() | Where-Object { $_ -match '^-(NonI.*|Command.*|EncodedCommand|File|c|f|ec)$' }",
                'if ([Environment]::UserInteractive -and -not $aemBatch) {',
                '    $aemPreviousExitCode = $global:LASTEXITCODE',
                '    try {',
                f"        & {quote(executable)} --config {quote(config)} startup --trigger shell-start | Out-Null",
                '    } catch { Write-Verbose $_ } finally { $global:LASTEXITCODE = $aemPreviousExitCode }', '}']
    else:
        command = shlex.join([str(executable), '--config', str(config), 'startup', '--trigger', 'shell-start'])
        directory = shlex.quote(str(bin_dir))
        body = ['case $- in', '  *i*)', f'    case ":$PATH:" in *:{directory}:*) ;; *) export PATH={directory}:"$PATH" ;; esac',
                f'    {command} >/dev/null 2>&1 || true', '    ;;', 'esac']
    return start, end, '\n'.join([start, *body, end]) + '\n'


def render_shell(path, start, end, desired, old):
    regular(path)
    raw = path.read_bytes() if exists(path) else b''
    # UTF-8 BOM and the existing newline style belong to the user's file.
    text = raw.decode('utf-8')
    newline = '\r\n' if '\r\n' in text else '\n'
    desired = desired.replace('\n', newline) if desired is not None else None
    lines = text.splitlines(keepends=True)
    begins = [i for i, line in enumerate(lines) if line.rstrip('\r\n') == start]
    ends = [i for i, line in enumerate(lines) if line.rstrip('\r\n') == end]
    if len(begins) != len(ends) or len(begins) > 1 or (begins and begins[0] >= ends[0]):
        raise Error(f'Damaged or duplicate AEM shell block: {path}')
    if begins:
        a, b = begins[0], ends[0] + 1
        actual = ''.join(lines[a:b])
        if not old or actual != old.get('block'):
            raise Error(f'Existing or locally modified AEM shell block: {path}')
        result = ''.join(lines[:a]) + (desired or '') + ''.join(lines[b:])
    else:
        if old:
            raise Error(f'Managed shell block disappeared: {path}')
        prefix = text + (newline if text and not text.endswith('\n') else '')
        result = prefix + (desired or '')
    return result.encode('utf-8'), desired


def machine_plan(config, document):
    """Use the existing setup journal for a lossless machine-document replacement."""
    content = tomlkit.dumps(document).encode('utf-8')
    regular(config.path)
    record = {'source_name': 'setup', 'id': 'machine', 'kind': 'setup', 'mode': 'setup-config',
              'source': str(config.path), 'target': str(config.path), 'relative': '.',
              'hash': hashlib.sha256(content).hexdigest(), 'detached': False, 'agents': [], 'agent': ''}
    return Plan(Item('setup', 'machine', '.', config.path, config.path, 'setup-config', 'setup'),
                observation(config.path), record, not exists(config.path) or content != config.path.read_bytes(), content)


def setup(manager, args):
    """Preflight all integrations, then use the existing per-target journal.

    Selections are saved last. Completed ownership records allow a retry after
    interruption without adopting unknown files or discarding previous steps.
    """
    manager.state.ready()
    config, state = manager.config, manager.state
    document = tomlkit.parse(tomlkit.dumps(config.doc))
    from .updates import set_catalog_policy
    catalog_changed = set_catalog_policy(document, args)
    update_fields = ("repository", "python", "uv", "tool_dir", "bin_dir")
    if args.self_update is not None or any(getattr(args, "update_" + f) for f in update_fields):
        settings = document.setdefault("self_update", {})
        settings.setdefault("mode", "off")
        if args.self_update is not None:
            settings["mode"] = args.self_update
        for field in update_fields:
            value = getattr(args, "update_" + field)
            if value is not None:
                settings[field] = value
    policy_only = (catalog_changed and not (args.shell or args.agent or args.remove_shell or args.remove_agent
                   or args.self_update is not None or args.executable
                   or any(getattr(args, 'update_' + f) for f in update_fields)))
    if policy_only:
        # Policy edits need no executable or profile rewrites, including on a
        # machine bootstrapped without startup integrations.
        candidate = Config(config.path, document=document)
        plan = machine_plan(config, document)
        if not args.dry_run:
            manager.install(plan)
        return {'integrations': [], 'agents': list(config.agents),
                'shells': list(config.doc.get('setup', {}).get('shells', {})),
                'catalog_update': candidate.catalog_update, 'notices': [],
                'next': 'Use catalog auto --trigger EVENT or configured startup integrations.'}
    selected = document.setdefault('setup', {})
    values = selected.get('shells', {})
    shells = dict(values)
    agents = document.setdefault('agents', {})
    if set(args.shell) & set(args.remove_shell) or set(args.agent) & set(args.remove_agent):
        raise Error('Cannot add and remove the same integration')
    if not (args.shell or args.agent or shells or agents or args.remove_shell or args.remove_agent):
        raise Error('Select at least one --shell or --agent for initial setup')
    location = args.executable or selected.get('executable') or str(Path(sys.executable).parent / ('aem.exe' if os.name == 'nt' else 'aem'))
    if not isinstance(location, str) or not Path(location).expanduser().is_absolute():
        raise Error('Setup executable must be an absolute path')
    executable = Path(location).expanduser().absolute()
    if not executable.is_file() and not args.dry_run:
        raise Error(f'AEM executable is missing: {executable}')
    for name in args.agent:
        adapter = profile(name)
        if name not in agents:
            values = adapter.defaults()
            if name == 'codex':
                # Explicit roots are user-owned machine bindings, not defaults
                # that setup may silently relocate.
                for field, root in (('root', 'agent'), ('skills', 'skills')):
                    if root in config.roots:
                        values[field] = str(config.roots[root])
            agents[name] = values
    for name in args.remove_agent:
        profile(name)
        active = [k for k, r in state.data['items'].items() if r.get('kind') != 'setup' and not r.get('detached')
                  and name in r.get('agents', [r.get('agent', 'codex')])]
        if active:
            raise Error(f'{name}: detach managed content before removing agent: {active}')
        agents.pop(name, None)
    for name in args.shell:
        if name not in shells:
            shells[name] = str(shell_path(name).absolute())
    for name in args.remove_shell:
        shells.pop(name, None)
    selected['shells'] = shells
    selected['executable'] = str(executable)
    candidate = Config(config.path, document=document)
    # Catalog validation is deliberately optional here: setup can repair its
    # integrations even when a previously bound catalog is unavailable.
    plans, report = [], []
    requested = [('shell', n) for n in shells] + [('agent', n) for n in agents]
    requested += [('shell', n) for n in args.remove_shell] + [('agent', n) for n in args.remove_agent]
    for kind, name in dict.fromkeys(requested):
        key = f'setup:{kind}-{name}'
        old = state.data['items'].get(key)
        removing = name in (args.remove_shell if kind == 'shell' else args.remove_agent)
        if removing and (not old or old.get('detached')):
            continue
        baseline = None if old and old.get('detached') else old
        if removing:
            path = Path(old['target'])
        elif kind == 'shell':
            path = Path(shells[name])
        else:
            path = Path(candidate.agents[name]['root']) / profile(name).hook_name
        regular(path)
        protected = [config.path, config.state_dir, config.checkout_root]
        protected.extend(absolute(p) for p in config.doc.get("external_paths", {}).values())
        if config.catalog_path:
            protected.append(config.catalog_source.path if config.catalog_source else config.catalog_path)
        if any(overlaps(path, p) for p in protected):
            raise Error(f'Setup target overlaps manager storage: {path}')
        if baseline and baseline['target'] != str(path):
            raise Error(f'{key}: remove the existing connection before relocating it')
        for other_key, record in state.data['items'].items():
            if other_key == key or record.get('detached') or not overlaps(path, Path(record['target'])):
                continue
            if not (kind == 'agent' and record.get('mode') == 'agent-hook'
                    and record.get('agent', 'codex') == name and record['target'] == str(path)):
                raise Error(f'Setup target overlaps {other_key}')
        record = {'source_name': 'setup', 'id': f'{kind}-{name}', 'target': str(path), 'source': str(config.path),
                  'kind': 'setup', 'relative': '.', 'mode': 'setup-shell' if kind == 'shell' else 'agent-hook',
                  'agent': name if kind == 'agent' else '', 'agents': [name] if kind == 'agent' else [],
                  'detached': removing}
        if kind == 'shell':
            start, end, desired = shell_block(name, config.path, executable, executable.parent)
            content, block = render_shell(path, start, end, None if removing else desired, baseline)
            record['block'] = block
        else:
            adapter = profile(name)
            marker, group = adapter.definition(config.path, '', startup=True)
            content = adapter.remove(path, baseline) if removing else adapter.render(path, marker, group, baseline)
            record.update(hook_marker=marker, hook_group=group)
        record['hash'] = hashlib.sha256(content).hexdigest()
        item = Item('setup', record['id'], '.', config.path, path, record['mode'], 'setup', agent=record['agent'])
        plan = Plan(item, observation(path), record, not exists(path) or content != path.read_bytes(), content)
        plans.append(plan)
        report.append({'integration': f'{kind}:{name}', 'target': str(path),
                       'action': 'remove' if removing else 'write' if plan.change else 'unchanged'})
    # Detect overlaps among new selections before any profile is changed.
    for i, plan in enumerate(plans):
        if any(overlaps(plan.item.target, p.item.target) for p in plans[:i]):
            raise Error('Selected integrations have overlapping target files')
    plans.append(machine_plan(config, document))
    if not args.dry_run:
        for plan in plans:
            manager.install(plan)
    return {'integrations': report, 'agents': list(agents), 'shells': list(shells),
            'self_update': document.get('self_update', {'mode': 'off'}),
            'catalog_update': candidate.catalog_update,
            'notices': [profile(n).notice for n in agents],
            'next': 'Run bootstrap CATALOG, then apply; restart selected shells and review agent hook trust.'}


def remove_integrations(manager, args):
    """Remove only requested saved integrations without rebuilding remaining ones.

    Saved blocks/groups establish ownership; current profiles, executable paths,
    and catalog syntax are irrelevant. Keep opaque document/state fields and the
    original state version, and save selection changes after target transactions.
    """
    from . import hooks
    from .storage import saved_path

    config, state = manager.config, manager.state
    state.ready()
    regular(config.path)
    before_config = observation(config.path)
    if config.path.read_bytes() != config.raw:
        raise Error('Machine configuration changed after reading; retry removal')
    document = tomlkit.parse(tomlkit.dumps(config.doc))
    records = state.data['items']
    requested = [('shell', n) for n in args.remove_shell] + [('agent', n) for n in args.remove_agent]
    plans, report, hook_targets = [], [], {}
    for kind, name in dict.fromkeys(requested):
        key = f'setup:{kind}-{name}'
        if kind == 'agent':
            active = [k for k, r in records.items() if r.get('kind') != 'setup' and not r.get('detached')
                      and name in r.get('agents', [r.get('agent', 'codex')])]
            if active:
                raise Error(f'{name}: detach managed content before removing agent: {active}')
            selections = document.get('agents', {})
        else:
            settings = document.get('setup', {})
            if not isinstance(settings, dict):
                raise Error('Cannot remove a shell selection from a non-table setup field')
            selections = settings.get('shells', {})
        if not isinstance(selections, dict):
            raise Error(f'Cannot remove {kind} selection from a non-table field')
        selections.pop(name, None)
        old = records.get(key)
        if not old or old.get('detached'):
            continue
        if old.get('kind') != 'setup':
            raise Error(f'{key}: not a saved setup integration')
        path = saved_path(old.get('target'))
        regular(path)
        if overlaps(path, config.path) or overlaps(path, config.state_dir):
            raise Error(f'{key}: integration overlaps machine configuration or state')
        record = dict(old, detached=True)
        before = observation(path)
        if kind == 'shell':
            block = old.get('block')
            if not isinstance(block, str) or len(block.splitlines()) < 2:
                raise Error(f'{key}: no usable saved shell block')
            lines = block.splitlines()
            content, _ = render_shell(path, lines[0], lines[-1], None, old)
            record['block'] = None
        else:
            marker, group = old.get('hook_marker'), old.get('hook_group')
            if not isinstance(marker, str) or not marker or not isinstance(group, dict):
                raise Error(f'{key}: no usable saved hook ownership')
            entry = hook_targets.setdefault(path, {'document': hooks.read(path), 'records': {}, 'before': before})
            indices = hooks.matching(entry['document'], marker)
            if len(indices) != 1 or entry['document']['hooks']['SessionStart'][indices[0]] != group:
                raise Error(f'{key}: managed hook changed or disappeared; reconcile before removal')
            del entry['document']['hooks']['SessionStart'][indices[0]]
            entry['records'][key] = record
        report.append({'integration': f'{kind}:{name}', 'target': str(path), 'action': 'remove'})
        if kind == 'shell':
            record['hash'] = hashlib.sha256(content).hexdigest()
            item = Item('setup', f'{kind}-{name}', '.', config.path, path, 'setup-shell', 'setup')
            plans.append(Plan(item, before, record, True, content))
    for path, group in hook_targets.items():
        content = (json.dumps(group['document'], indent=2, ensure_ascii=True) + '\n').encode('utf-8')
        for record in group['records'].values():
            record['hash'] = hashlib.sha256(content).hexdigest()
        key, record = next(iter(group['records'].items()))
        item = Item('setup', key.removeprefix('setup:'), '.', config.path, path, 'agent-hook', 'setup')
        plans.append(Plan(item, group['before'], record, True, content, records=group['records']))
    for index, plan in enumerate(plans):
        if observation(plan.item.target) != plan.before:
            raise Error(f'{plan.item.key}: removal target changed during preflight')
        if any(overlaps(plan.item.target, other.item.target) for other in plans[:index]):
            raise Error('Selected removals have overlapping targets')
        for key, old in records.items():
            if key == plan.item.key or key in plan.records or old.get('detached'):
                continue
            value = old.get('target')
            if not isinstance(value, str) or not overlaps(plan.item.target, Path(value)):
                continue
            # Hook files support group ownership; other active directory/file
            # ownership must never be modified by an integration removal.
            if (plan.item.target == Path(value) and plan.item.mode == 'agent-hook'
                    and isinstance(old.get('hook_marker'), str) and isinstance(old.get('hook_group'), dict)):
                continue
            raise Error(f'Removal target overlaps {key}')
    if observation(config.path) != before_config:
        raise Error('Machine configuration changed during removal preflight')
    content = tomlkit.dumps(document).encode('utf-8')
    record = dict(records.get('setup:machine', {}), source_name='setup', id='machine', kind='setup',
                  mode='setup-config', source=str(config.path), target=str(config.path), relative='.',
                  hash=hashlib.sha256(content).hexdigest(), detached=False, agents=[], agent='')
    plans.append(Plan(Item('setup', 'machine', '.', config.path, config.path, 'setup-config', 'setup'),
                      before_config, record, content != config.raw, content))
    if not args.dry_run:
        for plan in plans:
            manager.install(plan)
    return {'integrations': report, 'next': 'Requested integrations removed; other selections were preserved.'}
