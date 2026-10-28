"""Read-only comparison of two Claude Code profile roots.

A profile is compared as it exists on disk: settings fields, hook groups by
owner, skill links, output styles, the instruction entry and installed plugin
identifiers. Nothing is written, no network is used, and credentials, sessions
and plugin data are never opened. Values that contain a profile's own root are
normalized to ``{root}`` so profile-specific paths are not reported as drift.
Values are replaced by a short digest unless the caller asks to see them,
because settings can carry secrets.
"""

from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path

from .agents import PROFILES, bindings, product_name
from .hooks import HOOK_ID_ARGUMENT, without_marker
from .model import Error

# Claude Code's file names come from its profile; the rest of its layout is fixed here.
CLAUDE = PROFILES['claude']
AEM_HOOK_MARKER = HOOK_ID_ARGUMENT
ROOT = '{root}'
MISSING = object()


@dataclass(frozen=True)
class Profile:
    name: str
    root: Path
    skills: Path


def resolve(document, spec):
    """Return the profile named by a machine binding or an absolute root path."""
    if os.path.isabs(os.path.expanduser(spec)):
        root = Path(spec).expanduser()
        return Profile(spec, root, root / 'skills')
    if product_name(spec) != CLAUDE.name:
        raise Error(f'Profile {spec} is not a Claude Code profile; only Claude Code layouts are supported')
    registered = bindings(document)
    if spec not in registered:
        raise Error(f'Unknown profile {spec}; use a registered agent name or an absolute root path')
    binding = registered[spec]
    return Profile(spec, Path(binding['root']).expanduser(), Path(binding['skills']).expanduser())


def _normalize(value, root, replacement=ROOT):
    """Replace a profile's own root inside every string; a profile copy passes the new root."""
    if isinstance(value, str):
        return value.replace(str(root), str(replacement))
    if isinstance(value, list):
        return [_normalize(item, root, replacement) for item in value]
    if isinstance(value, dict):
        return {key: _normalize(item, root, replacement) for key, item in value.items()}
    return value


def _leaves(value, prefix=()):
    """Yield (dotted path, value) for scalar leaves; arrays and empty objects are atomic."""
    if isinstance(value, dict) and value:
        for key, item in value.items():
            yield from _leaves(item, prefix + (key,))
    else:
        yield '.'.join(prefix), value


def _canonical(value):
    """Numbers compare by exact value (1 equals 1.0) and stay apart from booleans."""
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, (int, float, Decimal)):
        return ('number', str(Decimal(str(value)).normalize()))
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    if isinstance(value, dict):
        return {key: _canonical(item) for key, item in value.items()}
    return value


def _same(left, right):
    if left is MISSING or right is MISSING:
        return left is right
    return _canonical(left) == _canonical(right)


def _digest(value):
    return hashlib.sha256(json.dumps(_canonical(value), sort_keys=True).encode()).hexdigest()[:8]


def _read_json(path, parse_float=Decimal):
    if not path.is_file():
        return None
    try:
        document = json.loads(path.read_text(encoding='utf-8'), parse_float=parse_float)
    except (OSError, ValueError) as exc:
        raise Error(f'Cannot read {path}: {exc}') from exc
    if not isinstance(document, dict):
        raise Error(f'{path} must contain a JSON object')
    return document


def _settings(profile):
    """Return (normalized hooks, {dotted path: normalized scalar}) of the profile's settings."""
    document = _read_json(profile.root / CLAUDE.hook_name)
    if document is None:
        return {}, {}
    hooks = document.pop('hooks', {})
    return _normalize(hooks, profile.root), {
        path: _normalize(value, profile.root) for path, value in _leaves(document)}


def _hook_groups(hooks):
    """Map (event, matcher, owner, identity) to a group's commands.

    AEM-owned groups name their own machine configuration, so only the
    presence of such a group is comparable; external groups compare by command.
    """
    groups = {}
    if not isinstance(hooks, dict):
        return groups
    for event, entries in hooks.items():
        for entry in entries if isinstance(entries, list) else []:
            commands = [hook.get('command', '') for hook in entry.get('hooks', []) if isinstance(hook, dict)]
            owner = 'aem' if any(AEM_HOOK_MARKER in command for command in commands) else 'external'
            # A personal hook carries a per-agent marker, so it compares by its command without the marker.
            identity = '' if owner == 'aem' else '\n'.join(without_marker(command) for command in commands)
            groups[(event, entry.get('matcher', ''), owner, identity)] = commands
    return groups


def _links(directory, root):
    """Map entry names to a normalized link target, 'directory' or 'file'; None if absent."""
    if not directory.is_dir():
        return None
    return {entry.name: (_normalize(os.readlink(entry), root) if entry.is_symlink()
                         else 'directory' if entry.is_dir() else 'file')
            for entry in sorted(directory.iterdir())}


def _plugins(profile):
    document = _read_json(profile.root / 'plugins' / 'installed_plugins.json')
    if document is None:
        return None
    return {name: ','.join(sorted({str(item.get('version', '')) for item in installs if isinstance(item, dict)}))
            for name, installs in document.get('plugins', {}).items()}


def _entry(profile):
    path = profile.root / CLAUDE.entry_name
    if path.is_symlink():
        return _normalize(os.readlink(path), profile.root)
    if path.is_file():
        return 'file:' + hashlib.sha256(path.read_bytes()).hexdigest()[:8]
    return MISSING


def _item(name, left, right, expected, show):
    if _same(left, right):
        return {'item': name, 'status': 'same'}
    item = {'item': name, 'status': 'expected' if name in expected else 'different'}
    if left is MISSING:
        item['only'] = 'right'
    elif right is MISSING:
        item['only'] = 'left'
    if show:
        item['left'] = None if left is MISSING else left
        item['right'] = None if right is MISSING else right
    elif left is not MISSING and right is not MISSING:
        item['left'], item['right'] = _digest(left), _digest(right)
    return item


def _section(left, right, expected, show, prefix=''):
    left, right = left or {}, right or {}
    return [_item(prefix + key, left.get(key, MISSING), right.get(key, MISSING), expected, show)
            for key in sorted(set(left) | set(right))]


def _hooks(left, right, show):
    left_groups, right_groups = _hook_groups(left), _hook_groups(right)
    items = []
    for key in sorted(set(left_groups) | set(right_groups)):
        event, matcher, owner, identity = key
        # External groups differ by command, so the label carries a digest to tell two apart.
        label = f'{event}[{matcher}] {owner}' + (f'#{_digest(identity)[:6]}' if identity else '')
        item = {'item': label, 'status': 'same'}
        if key not in left_groups or key not in right_groups:
            item['status'] = 'different'
            item['only'] = 'left' if key in left_groups else 'right'
            if show:
                item['commands'] = left_groups.get(key) or right_groups.get(key)
        items.append(item)
    return items


def compare(left, right, *, expect=(), show_values=False):
    """Compare two profiles and return a report; nothing on disk is changed.

    ``expect`` names items (as the report prints them) whose difference is
    intended; they are reported as ``expected`` instead of ``different``.
    """
    expected = set(expect)
    left_hooks, left_fields = _settings(left)
    right_hooks, right_fields = _settings(right)
    sections = {
        'settings': _section(left_fields, right_fields, expected, show_values),
        'hooks': _hooks(left_hooks, right_hooks, show_values),
        'skills': _section(_links(left.skills, left.root), _links(right.skills, right.root),
                           expected, show_values, 'skills/'),
        'output-styles': _section(_links(left.root / 'output-styles', left.root),
                                  _links(right.root / 'output-styles', right.root),
                                  expected, show_values, 'output-styles/'),
        'plugins': _section(_plugins(left), _plugins(right), expected, True, 'plugins/'),
        'entry': [_item(CLAUDE.entry_name, _entry(left), _entry(right), expected, True)],
    }
    totals = {'same': 0, 'expected': 0, 'different': 0}
    for items in sections.values():
        for item in items:
            totals[item['status']] += 1
    known = {item['item'] for items in sections.values() for item in items}
    return {'left': {'name': left.name, 'root': str(left.root)},
            'right': {'name': right.name, 'root': str(right.root)},
            'totals': totals, 'unmatched_expect': sorted(expected - known), 'sections': sections}


def render(report):
    """Return a compact text report listing only the items that are not the same."""
    totals = report['totals']
    lines = [f"{report['left']['name']} <-> {report['right']['name']}",
             f"same {totals['same']}, expected {totals['expected']}, different {totals['different']}"]
    for name, items in report['sections'].items():
        changed = [item for item in items if item['status'] != 'same']
        if changed:
            lines.append(f'{name}:')
        for item in changed:
            only = f" (only {item['only']})" if 'only' in item else ''
            detail = f" {item['left']} | {item['right']}" if 'left' in item else ''
            lines.append(f"  {item['status']:<9} {item['item']}{only}{detail}")
    if report['unmatched_expect']:
        lines.append('unmatched --expect: ' + ', '.join(report['unmatched_expect']))
    return '\n'.join(lines)
