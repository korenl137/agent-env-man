"""The first config adapter: explicit JSON leaf paths into a TOML document."""

import json
import math
from collections.abc import Mapping

import tomlkit

from .model import Error


def valid_value(value):
    if type(value) in (str, bool, int):
        return True
    if type(value) is float:
        return math.isfinite(value)
    return isinstance(value, list) and all(valid_value(v) and not isinstance(v, list) for v in value)


def declarations(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("set"), list):
        raise Error("Codex input needs version = 1 and a set array")
    result = {}
    paths = []
    for entry in data["set"]:
        if not isinstance(entry, dict) or set(entry) != {"path", "value"}:
            raise Error("Each Codex set entry needs exactly path and value")
        parts, value = entry["path"], entry["value"]
        if not isinstance(parts, list) or not parts or any(not isinstance(p, str) or not p for p in parts):
            raise Error("Codex key paths must be nonempty arrays of nonempty strings")
        if not valid_value(value):
            raise Error("Codex values must be finite scalars or flat arrays of scalars")
        for previous in paths:
            if parts[:len(previous)] == previous or previous[:len(parts)] == parts:
                raise Error("Overlapping Codex key paths")
        paths.append(parts)
        result[json.dumps(parts, ensure_ascii=True)] = value
    return result


def read(path):
    if path.is_symlink():
        raise Error(f"Merge target is a symlink; materialize and release its previous owner first: {path}")
    try:
        return tomlkit.parse(path.read_text(encoding="utf-8")) if path.exists() else tomlkit.document()
    except (OSError, ValueError) as exc:
        raise Error(f"Cannot parse merge target {path}: {exc}") from exc


def get(document, encoded_path):
    current = document
    for part in json.loads(encoded_path):
        if not isinstance(current, Mapping):
            raise Error(f"A scalar blocks managed key path {encoded_path}")
        if part not in current:
            return False, None
        current = current[part]
    value = current.unwrap() if hasattr(current, "unwrap") else current
    return True, value


def equal(a, b):
    # bool and int compare equal in Python, but are different TOML settings.
    return type(a) is type(b) and (all(equal(x, y) for x, y in zip(a, b)) and len(a) == len(b)
                                  if isinstance(a, list) else a == b)


def render(document, desired):
    for encoded, value in desired.items():
        parts = json.loads(encoded)
        table = document
        for part in parts[:-1]:
            if part not in table:
                table[part] = tomlkit.table()
            table = table[part]
            if not isinstance(table, Mapping):
                raise Error(f"A scalar blocks managed key path {encoded}")
        existing, old = get(document, encoded)
        if existing and isinstance(old, dict):
            raise Error(f"Refusing to replace an entire TOML table: {encoded}")
        if not existing or not equal(old, value):
            table[parts[-1]] = value
    rendered = tomlkit.dumps(document)
    tomlkit.parse(rendered)
    return rendered.encode("utf-8")
