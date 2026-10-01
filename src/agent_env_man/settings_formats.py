"""Native file-format operations for staged application settings.

The registry is internal; supporting another format does not require changing
command selection or transport. AEM intent metadata remains TOML separately.
"""

from copy import deepcopy
import json
import math
from typing import Protocol

import tomlkit

from .model import Error


class SettingsFormat(Protocol):
    """Native document operations consumed by the format-independent workflow."""

    def parse(self, text: str) -> object: ...
    def fields(self, document: object) -> dict[tuple[str, ...], object]: ...
    def identity(self, value: object) -> object: ...
    def put(self, document: object, path: tuple[str, ...], value: object = None, *, delete: bool = False) -> None: ...
    def dump(self, document: object) -> str: ...


class TomlFormat:
    """TOML-specific parsing, field identity, equality, and preserving edits.

    Ordinary tables expose their leaves; arrays (including arrays of tables)
    and empty tables are indivisible values. No parser nodes escape this adapter
    into persisted ownership or CLI reports.
    """

    @staticmethod
    def parse(text):
        try:
            return tomlkit.parse(text)
        except (ValueError, TypeError) as exc:
            raise Error(f"Invalid TOML settings: {exc}") from exc

    @staticmethod
    def fields(document):
        result = {}

        def visit(node, path):
            if isinstance(node, dict) and node:
                for key, value in node.items():
                    visit(value, (*path, key))
            elif path:
                result[path] = node

        visit(document, ())
        return result

    @staticmethod
    def identity(value):
        value = value.unwrap() if hasattr(value, "unwrap") else value
        if isinstance(value, dict):
            return ("table", tuple(sorted((k, TomlFormat.identity(v)) for k, v in value.items())))
        if isinstance(value, list):
            return ("array", tuple(TomlFormat.identity(v) for v in value))
        if isinstance(value, float):
            return ("float", "nan" if math.isnan(value) else value.hex())
        return (type(value).__name__, value)

    @staticmethod
    def put(document, path, value=None, *, delete=False):
        node = document
        parents = []
        for key in path[:-1]:
            if key not in node:
                if delete:
                    return
                node[key] = tomlkit.table()
            if not isinstance(node[key], dict):
                if delete:
                    return
                raise Error(f"Field structure conflict at {json.dumps(list(path))}")
            parents.append((node, key))
            node = node[key]
        if delete:
            node.pop(path[-1], None)
            # Empty parent tables introduced by removing their last leaf are
            # containers, not retained empty-table ownership declarations.
            for parent, key in reversed(parents):
                if parent[key]:
                    break
                del parent[key]
        else:
            node[path[-1]] = deepcopy(value)

    @staticmethod
    def dump(document):
        return tomlkit.dumps(document)


FORMATS = {"toml": TomlFormat()}

