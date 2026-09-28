"""Built-in agent capabilities injected at the machine boundary.

Profiles own product syntax; the manager owns delivery and installation safety.
The registry is intentionally internal, not a user-loadable plugin mechanism.
"""
from dataclasses import dataclass
import os
from pathlib import Path

from . import hooks
from .model import Error


# Source-level choice for Codex startup briefings, independent of machine setup.
# systemMessage displays a UI warning; additionalContext informs the model.
# Neither mode asks the model to announce the update in its response.
STARTUP_BRIEFING_OUTPUT = "systemMessage"


@dataclass(frozen=True)
class Codex:
    name: str = 'codex'
    entry_name: str = 'AGENTS.md'
    hook_name: str = 'hooks.json'
    notice: str = hooks.TRUST_NOTICE

    def defaults(self):
        return {'root': str(Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex').expanduser().resolve()),
                'skills': str(Path.home() / '.agents/skills')}

    def definition(self, config, name, *, startup=False):
        identity = f'{self.name}:startup' if startup else f'{self.name}:{name}'
        args = ['startup', '--trigger', 'agent-start', '--agent', self.name] if startup else ['agent-hook', name, '--agent', self.name]
        marker = hooks.marker(config, identity, 'startup' if startup else 'instruction roots')
        return marker, {'matcher': '^(startup|resume|clear|compact)$', 'hooks': [
            {'type': 'command', 'command': hooks.command(config, args), 'timeout': 10,
             'statusMessage': marker, 'additionalContextLimit': 1000}]}

    def render(self, path, marker, group, old, **options):
        return hooks.render(path, marker, group, old, **options)

    def current(self, path, marker, group):
        return hooks.current(path, marker, group)

    def remove(self, path, record):
        return hooks.remove(path, record)

    def context(self, text):
        return {'hookSpecificOutput': {'hookEventName': 'SessionStart', 'additionalContext': text}}

    def failure(self, message):
        return {'continue': False, 'stopReason': message, 'systemMessage': message}

    def startup_result(self, briefing=""):
        if not briefing:
            return {}
        if STARTUP_BRIEFING_OUTPUT == "systemMessage":
            return {"systemMessage": briefing}
        if STARTUP_BRIEFING_OUTPUT == "additionalContext":
            return self.context(briefing)
        raise Error(f"Unsupported startup briefing output: {STARTUP_BRIEFING_OUTPUT}")


PROFILES = {'codex': Codex()}


def profile(name):
    try:
        return PROFILES[name]
    except KeyError:
        raise Error(f'Unsupported agent: {name}') from None


def bindings(document):
    values = document.get('agents', {})
    if not isinstance(values, dict):
        raise Error('Machine agents must be a table')
    result = {}
    for name, value in values.items():
        adapter = profile(name)
        if not isinstance(value, dict) or set(value) - {'root', 'skills'}:
            raise Error(f'Invalid agent binding: {name}')
        result[name] = {**adapter.defaults(), **value}
        for path in result[name].values():
            if not isinstance(path, str) or not Path(path).expanduser().is_absolute():
                raise Error(f'Agent {name} paths must be absolute')
    return result


def suffix(name):
    # Keep the default profile's item names concise.
    return '' if name == 'codex' else '@' + name
