"""Copy a Claude Code profile's reusable state into a new, independent root.

Only an allowlist is copied: settings fields, the instruction entry, output
styles, skill links and hook scripts. Credentials, sessions, history and
plugin data are never read, and installed plugins are listed but not copied.
Links are recreated against their own targets, so the copy never points back
into the source profile, and strings that name the source root are rewritten
to the new root. Hook groups AEM generated are skipped: they name the source's
agent, so the new profile gets its own once it is registered and applied.
"""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import tempfile

from .hooks import generated
from .model import Error, absolute, overlaps
from .profile_compare import CLAUDE, Profile, _normalize, _plugins, _read_json, compare


@dataclass
class Plan:
    source: Profile
    target: Path
    mode: int
    settings: dict | None
    links: dict  # relative path -> link target
    files: dict  # relative path -> (bytes, mode)
    skipped: list  # (item, reason)
    sets: list


def _aem_owned(group):
    commands = [hook.get('command', '') for hook in group.get('hooks', []) if isinstance(hook, dict)]
    return any(generated(command) for command in commands)


def _assign(document, spec):
    field, separator, raw = spec.partition('=')
    keys = field.split('.')
    if not separator or not all(keys) or keys[0] == 'hooks':
        raise Error(f'--set expects FIELD=VALUE outside hooks: {spec}')
    try:
        value = json.loads(raw)
    except ValueError:
        value = raw
    node = document
    for key in keys[:-1]:
        node = node.setdefault(key, {})
        if not isinstance(node, dict):
            raise Error(f'--set {field}: {key} is not an object')
    node[keys[-1]] = value
    return field


def _link(path, source, target):
    """Absolute link target with the source root replaced; relative links are resolved first."""
    return _normalize(os.path.normpath(os.path.join(path.parent, os.readlink(path))), source.root, target)


def _text(data, source, target):
    try:
        return _normalize(data.decode('utf-8'), source.root, target).encode('utf-8')
    except UnicodeDecodeError:
        return data


def _entries(directory, relative, source, target, links, skipped):
    for entry in sorted(directory.iterdir()):
        if entry.is_symlink():
            links[relative / entry.name] = _link(entry, source, target)
        else:
            skipped.append((str(relative / entry.name), 'not a link'))


def plan(source, target, sets=()):
    target = absolute(str(target))
    if overlaps(target, source.root.resolve()):
        raise Error(f'Target {target} overlaps the source profile; use an independent root')
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise Error(f'Target {target} already exists and is not empty')
    links, files, skipped = {}, {}, []

    settings, fields = _read_json(source.root / CLAUDE.hook_name, parse_float=float), []
    if settings is not None or sets:
        settings, owned, kept = settings or {}, 0, {}
        for event, groups in settings.pop('hooks', {}).items():
            mine = [group for group in groups if not _aem_owned(group)]
            owned += len(groups) - len(mine)
            if mine:
                kept[event] = mine
        if kept:
            settings['hooks'] = kept
        settings = _normalize(settings, source.root, target)
        if owned:
            skipped.append(('hooks', f'{owned} AEM-generated hook group(s); register the target and run aem apply to recreate them'))
        fields = [_assign(settings, spec) for spec in sets]

    if source.skills.is_dir():
        _entries(source.skills, Path('skills'), source, target, links, skipped)
    entry = source.root / CLAUDE.entry_name
    if entry.is_symlink():
        links[Path(CLAUDE.entry_name)] = _link(entry, source, target)
    elif entry.is_file():
        files[Path(CLAUDE.entry_name)] = (_text(entry.read_bytes(), source, target), entry.stat().st_mode & 0o777)
    styles = source.root / 'output-styles'
    if styles.is_symlink():
        links[Path('output-styles')] = _link(styles, source, target)
    elif styles.is_dir():
        _entries(styles, Path('output-styles'), source, target, links, skipped)
    hook_dir = source.root / 'hooks'
    if hook_dir.is_dir() and not hook_dir.is_symlink():
        for script in sorted(hook_dir.iterdir()):
            relative = Path('hooks') / script.name
            if script.is_symlink():
                links[relative] = _link(script, source, target)
            elif script.is_file():
                files[relative] = (_text(script.read_bytes(), source, target), script.stat().st_mode & 0o777)

    installed = _plugins(source)
    if installed:
        skipped.append(('plugins', f'{len(installed)} installed plugin(s) are not copied; install with the product CLI'))
    return Plan(source, target, source.root.stat().st_mode & 0o777, settings, links, files, skipped, fields)


def apply(plan):
    """Write the plan into a staging folder beside the target, then move it into place."""
    plan.target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.aem-copy-', dir=plan.target.parent))
    try:
        staging.chmod(plan.mode)
        if plan.settings is not None:
            (staging / CLAUDE.hook_name).write_text(json.dumps(plan.settings, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        for relative, (data, mode) in plan.files.items():
            (staging / relative).parent.mkdir(parents=True, exist_ok=True)
            (staging / relative).write_bytes(data)
            (staging / relative).chmod(mode)
        for relative, destination in plan.links.items():
            (staging / relative).parent.mkdir(parents=True, exist_ok=True)
            os.symlink(destination, staging / relative)
        if plan.target.exists():
            plan.target.rmdir()
        staging.rename(plan.target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def report(plan, applied):
    """Describe the plan; after writing, include a read-only comparison against the source."""
    result = {'source': {'name': plan.source.name, 'root': str(plan.source.root)},
              'target': str(plan.target), 'applied': applied,
              'settings': plan.settings is not None, 'set': plan.sets,
              'links': sorted(path.as_posix() for path in plan.links),
              'files': sorted(path.as_posix() for path in plan.files),
              'skipped': [{'item': item, 'reason': reason} for item, reason in plan.skipped]}
    if applied:
        comparison = compare(plan.source, Profile(plan.target.name, plan.target, plan.target / 'skills'), expect=plan.sets)
        different = [{'section': section, **item} for section, items in comparison['sections'].items()
                     for item in items if item['status'] == 'different']
        # Plugins and hook groups the copy leaves out show up as present only in the source.
        left_out = [item for item in different if item['section'] in ('plugins', 'hooks') and item.get('only') == 'left']
        result['verification'] = {'same': comparison['totals']['same'], 'expected': comparison['totals']['expected'],
                                  'not_copied': len(left_out),
                                  'unexpected': [item for item in different if item not in left_out]}
    return result


def render(result):
    lines = [f"{'Copied' if result['applied'] else 'Would copy'} {result['source']['name']} -> {result['target']}"]
    if result['settings']:
        lines.append(CLAUDE.hook_name + (f" (set {', '.join(result['set'])})" if result['set'] else ''))
    lines += [f'link  {path}' for path in result['links']] + [f'file  {path}' for path in result['files']]
    lines += [f"skip  {item['item']}: {item['reason']}" for item in result['skipped']]
    if result['applied']:
        check = result['verification']
        lines.append(f"verification: same {check['same']}, expected {check['expected']}, "
                     f"not copied {check['not_copied']}, unexpected {len(check['unexpected'])}")
        lines += [f"  different {item['item']}" for item in check['unexpected']]
    else:
        lines.append('Nothing was written; add --write to create the profile.')
    lines.append('Settings are an independent copy; to share fields later, see staged settings for named instances in the AEM docs.')
    return '\n'.join(lines)
