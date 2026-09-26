"""Configuration and the deliberately small links.conf grammar."""

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import sys

import tomlkit


class Error(Exception):
    """An actionable configuration, ownership, or operation failure."""


def identifier(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value):
        raise Error(f"Invalid identifier: {value!r}")
    return value


def relative(value: str) -> Path:
    # No evaluation, Windows drive syntax, or platform-dependent separators.
    if (not isinstance(value, str) or not value or "\\" in value or ":" in value
            or value.startswith("/") or any(p in ("", ".", "..") for p in value.split("/"))):
        raise Error(f"Expected a literal relative path using /: {value!r}")
    return Path(*PurePosixPath(value).parts)


def absolute(value: str) -> Path:
    if not isinstance(value, str):
        raise Error("Machine paths must be strings")
    result = Path(value).expanduser()
    if not result.is_absolute():
        raise Error(f"Machine paths must be absolute or start with ~/: {value}")
    return result.resolve()


def overlaps(a: Path, b: Path) -> bool:
    return a == b or a in b.parents or b in a.parents


def default_config() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "agent-env-man/machine.toml"


@dataclass(frozen=True)
class Source:
    name: str
    path: Path
    manifest: str
    git: str | None
    branch: str | None
    items: tuple[str, ...]
    modes: dict[str, str]


@dataclass(frozen=True)
class Item:
    source_name: str
    id: str
    relative: str
    source: Path
    target: Path
    mode: str

    @property
    def key(self) -> str:
        return f"{self.source_name}:{self.id}"


class Config:
    def __init__(self, path: Path, *, missing_ok: bool = False, document=None):
        self.path = path.expanduser().resolve()
        self.state_dir = self.path.parent / (self.path.name + ".state")
        if document is not None:
            self.doc = document
        elif not self.path.exists() and missing_ok:
            self.doc = tomlkit.parse('version = 1\n\n[roots]\n\n[sources]\n')
        else:
            try:
                self.doc = tomlkit.parse(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise Error(f"Cannot read machine config {self.path}: {exc}") from exc
        if self.doc.get("version") != 1:
            raise Error("Unsupported machine config version")
        if not isinstance(self.doc.get("roots", {}), dict) or not isinstance(self.doc.get("sources", {}), dict):
            raise Error("roots and sources must be TOML tables")
        self.roots = {identifier(k): absolute(v) for k, v in self.doc.get("roots", {}).items()}
        self.sources = {}
        for name, data in self.doc.get("sources", {}).items():
            identifier(name)
            if not isinstance(data, dict) or "path" not in data:
                raise Error(f"Source {name} needs a path")
            manifest = data.get("manifest", "links.conf")
            relative(manifest)
            git = data.get("git")
            branch = data.get("branch")
            if git is not None and (not isinstance(git, str) or not git or not isinstance(branch, str) or not branch):
                raise Error(f"Git source {name} needs git and branch strings")
            if git is None and branch is not None:
                raise Error(f"Source {name}: branch requires a Git URL")
            ids = data.get("items", [])
            if not isinstance(ids, list) or any(not isinstance(x, str) for x in ids) or len(set(ids)) != len(ids):
                raise Error(f"Source {name}: items must be unique identifiers")
            for item_id in ids:
                identifier(item_id)
            if not isinstance(data.get("modes", {}), dict):
                raise Error(f"Source {name}: modes must be a TOML table")
            modes = dict(data.get("modes", {}))
            if any(k not in ids or v not in ("link", "copy") for k, v in modes.items()):
                raise Error(f"Source {name}: mode overrides must select registered link/copy items")
            self.sources[name] = Source(name, absolute(data["path"]), manifest, git, branch, tuple(ids), modes)
        paths = [s.path for s in self.sources.values()]
        for i, path in enumerate(paths):
            if overlaps(path, self.state_dir) or overlaps(path, self.path):
                raise Error("Source and machine config/state paths must be separate")
            if any(overlaps(path, other) for other in paths[:i]):
                raise Error("Source roots must not overlap")

    def manifest(self, source: Source, text: str | None = None) -> list[Item]:
        if text is None:
            text = (source.path / source.manifest).read_text(encoding="utf-8")
        platform = "windows" if os.name == "nt" else "linux" if sys.platform.startswith("linux") else "unsupported"
        if platform == "unsupported":
            raise Error("This version supports Linux/WSL and native Windows")
        result = []
        ids = set()
        for number, line in enumerate(text.splitlines(), 1):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            fields = line.split("|")
            if len(fields) not in (4, 6):
                raise Error(f"{source.name}/{source.manifest}:{number}: expected 4 or 6 fields")
            system, src, root, dst = fields[:4]
            if system not in ("all", "linux", "windows"):
                raise Error(f"Unknown platform on line {number}: {system}")
            if system not in ("all", platform):
                continue
            src_path, dst_path = relative(src), relative(dst)
            if root not in self.roots:
                raise Error(f"Missing machine root {root!r} for {source.name}:{number}")
            mode, item_id = fields[4:] if len(fields) == 6 else (
                "link", "legacy-" + hashlib.sha256(f"{root}\0{dst}".encode()).hexdigest()[:16])
            identifier(item_id)
            if item_id in ids:
                raise Error(f"Duplicate active item ID: {source.name}:{item_id}")
            ids.add(item_id)
            if mode not in ("link", "copy", "codex-merge"):
                raise Error(f"Unknown install mode: {mode}")
            if item_id in source.modes:
                if mode == "codex-merge":
                    raise Error("Cannot override codex-merge with a whole-file mode")
                mode = source.modes[item_id]
            src_abs = source.path / src_path
            target = self.roots[root] / dst_path
            # Resolve ancestors but never follow an existing target symlink.
            target = target.parent.resolve() / target.name
            if self.roots[root] not in target.parents:
                raise Error(f"Target escapes its root: {target}")
            if any(target == r for r in self.roots.values()):
                raise Error(f"Cannot own an entire configured target root: {target}")
            for protected in [s.path for s in self.sources.values()] + [self.state_dir, self.path]:
                if overlaps(target, protected):
                    raise Error(f"Target overlaps source or manager state: {target}")
            result.append(Item(source.name, item_id, src, src_abs, target, mode))
        return result
