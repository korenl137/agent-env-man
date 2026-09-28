"""Preserve unrelated Codex hooks while owning one explicit SessionStart group."""

import base64
import hashlib
import json
import os
from pathlib import Path
import shlex
import sys

from .model import Error
from .storage import exists, is_reparse


TRUST_NOTICE = ("Codex hook trust must be reviewed separately: in the next Codex session, "
                "open /hooks, review and trust the AEM hook, then start a new session. "
                "AEM does not grant trust or enable disabled hooks.")


def definition(config_path: Path, name: str) -> tuple[str, dict]:
    """Use a stable marker for ownership and an absolute interpreter for runtime lookup."""
    identity = hashlib.sha256(f"{config_path}\0{name}".encode()).hexdigest()[:20]
    marker = f"AEM instruction roots [{identity}]"
    args = [sys.executable, "-m", "agent_env_man", "--config", str(config_path), "codex-hook", name]
    command = ("& " + " ".join("'" + arg.replace("'", "''") + "'" for arg in args)
               if os.name == "nt" else shlex.join(args))
    if os.name == "nt":
        # Explicit PowerShell invocation avoids relying on Codex's outer shell.
        encoded = base64.b64encode(command.encode("utf-16le")).decode("ascii")
        command = "powershell.exe -NoProfile -NonInteractive -EncodedCommand " + encoded
    return marker, {"matcher": "^(startup|resume|clear|compact)$", "hooks": [
        {"type": "command", "command": command, "timeout": 10,
         "statusMessage": marker, "additionalContextLimit": 1000}]}


def read(path: Path) -> dict:
    """Reject invalid/redirected hook files rather than losing unrelated configuration."""
    if not exists(path):
        return {}
    if path.is_symlink() or is_reparse(path) or not path.is_file():
        raise Error(f"Hook configuration must be a regular JSON file: {path}")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise Error(f"Duplicate JSON key in hook configuration: {key}")
            result[key] = value
        return result

    try:
        doc = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    except (OSError, ValueError) as exc:
        raise Error(f"Cannot read hook configuration {path}: {exc}") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("hooks", {}), dict):
        raise Error("Hook configuration and hooks must be JSON objects")
    groups = doc.get("hooks", {}).get("SessionStart", [])
    if (not isinstance(groups, list) or any(not isinstance(g, dict) or not isinstance(g.get("hooks"), list)
            or any(not isinstance(h, dict) for h in g["hooks"]) for g in groups)):
        raise Error("SessionStart must be an array of hook groups")
    return doc


def matching(doc: dict, marker: str) -> list[int]:
    return [i for i, group in enumerate(doc.get("hooks", {}).get("SessionStart", []))
            if any(h.get("statusMessage") == marker for h in group["hooks"])]


def current(path: Path, marker: str, group: dict) -> bool:
    doc = read(path)
    indices = matching(doc, marker)
    return len(indices) == 1 and doc["hooks"]["SessionStart"][indices[0]] == group


def render(path: Path, marker: str, desired: dict, old: dict | None, *, adopt=False, replace=False) -> bytes:
    """Merge only the saved group, preserving other events, groups and top-level fields."""
    doc = read(path)
    groups = doc.setdefault("hooks", {}).setdefault("SessionStart", [])
    indices = matching(doc, marker)
    if len(indices) > 1:
        raise Error("Duplicate AEM hook markers; reconcile hook configuration before applying")
    if indices:
        index = indices[0]
        actual = groups[index]
        safe = (old and actual in (old["hook_group"], desired)) or (adopt and actual == desired)
        if not safe and not replace:
            raise Error("Existing or locally modified AEM hook; select its entry with --adopt or --replace")
        groups[index] = desired
    else:
        if old and exists(path) and not replace:
            raise Error("Managed AEM hook was removed; select its entry with --replace to restore it")
        groups.append(desired)
    # Preserve formatting and bytes as well when no semantic update is needed.
    if exists(path) and read(path) == doc:
        return path.read_bytes()
    return (json.dumps(doc, indent=2, ensure_ascii=True) + "\n").encode("utf-8")
