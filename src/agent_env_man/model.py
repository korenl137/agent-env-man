"""Independent skill inventory, machine bindings, and legacy links.conf input."""

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
    manifest: str | None
    git: str | None
    branch: str | None
    items: tuple[str, ...]
    modes: dict[str, str]
    repository: bool = False


@dataclass(frozen=True)
class Item:
    source_name: str
    id: str
    relative: str
    source: Path
    target: Path
    mode: str
    kind: str = "payload"

    @property
    def key(self) -> str:
        return self.id if self.kind == "skill" else f"{self.source_name}:{self.id}"


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
        self.catalog_path = None
        self._catalog = None
        self.checkout_root = absolute(self.doc["checkout_root"]) if "checkout_root" in self.doc else self.path.parent / (self.path.name + ".checkouts")
        if overlaps(self.checkout_root, self.path) or overlaps(self.checkout_root, self.state_dir):
            raise Error("Checkout storage must be separate from machine config and state")
        if "catalog" in self.doc:
            value = self.doc["catalog"]
            if not isinstance(value, str) or not value:
                raise Error("catalog must name an inventory file")
            location = Path(value).expanduser()
            self.catalog_path = (location if location.is_absolute() else self.path.parent / location).resolve()
            if overlaps(self.catalog_path, self.state_dir) or self.catalog_path == self.path:
                raise Error("Catalog must be separate from machine config and state")
            if overlaps(self.catalog_path, self.checkout_root):
                raise Error("Keep the local catalog outside managed checkouts")
        self.modes = self.doc.get("modes", {})
        if not isinstance(self.modes, dict) or any(v not in ("link", "copy") for v in self.modes.values()):
            raise Error("Machine modes must map skill names to link or copy")
        self._legacy_sources = {}
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
            self._legacy_sources[name] = Source(name, absolute(data["path"]), manifest, git, branch, tuple(ids), modes)
        paths = [s.path for s in self._legacy_sources.values()]
        for i, path in enumerate(paths):
            if overlaps(path, self.state_dir) or overlaps(path, self.path):
                raise Error("Source and machine config/state paths must be separate")
            if self.catalog_path is not None and overlaps(path, self.catalog_path):
                raise Error("Keep the inventory outside the skill repositories it lists")
            if self.catalog_path is not None and overlaps(path, self.checkout_root):
                raise Error("Legacy source and catalog checkout storage must not overlap")
            if any(overlaps(path, other) for other in paths[:i]):
                raise Error("Source roots must not overlap")

    def catalog(self) -> dict:
        """Load lazily so detach/recovery remain usable when inventory is missing."""
        if self._catalog is not None:
            return self._catalog
        if self.catalog_path is None:
            return {}
        try:
            document = tomlkit.parse(self.catalog_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise Error(f"Cannot read skill catalog {self.catalog_path}: {exc}") from exc
        if document.get("version") != 1 or set(document) - {"version", "skills"}:
            raise Error("Skill catalog needs version = 1 and a skills table")
        skills = document.get("skills", {})
        if not isinstance(skills, dict):
            raise Error("Catalog skills must be a TOML table")
        for name, data in skills.items():
            identifier(name)
            if not isinstance(data, dict) or set(data) - {"type", "repository", "subdir", "branch", "root", "mode"}:
                raise Error(f"Invalid skill declaration: {name}")
            if data.get("type") != "git":
                raise Error(f"Skill {name}: only type = 'git' is supported")
            repository = data.get("repository")
            if not isinstance(repository, str) or not repository or repository.startswith("-"):
                raise Error(f"Skill {name}: repository must be a Git URL or absolute local repository path")
            if not (Path(repository).expanduser().is_absolute() or ":" in repository):
                raise Error(f"Skill {name}: use an absolute path for a local Git repository")
            if "branch" in data and (not isinstance(data["branch"], str) or not data["branch"] or data["branch"].startswith("-")):
                raise Error(f"Skill {name}: branch must be a nonempty branch name")
            if name in self._legacy_sources:
                raise Error(f"Skill name collides with a legacy source: {name}")
            path = data.get("subdir", ".")
            if path != ".":
                relative(path)
            root = data.get("root", "skills")
            if not isinstance(root, str) or root not in self.roots:
                raise Error(f"Skill {name}: missing target root {root!r}")
            if data.get("mode", "link") not in ("link", "copy"):
                raise Error(f"Skill {name}: expected link or copy mode")
        if self.modes.keys() - skills.keys():
            raise Error("Machine mode override does not name a skill in the catalog")
        self._catalog = skills
        return skills

    @property
    def sources(self) -> dict[str, Source]:
        """Derive checkout paths; the inventory never needs device-local bindings."""
        result = dict(self._legacy_sources)
        for name, data in self.catalog().items():
            repository = data["repository"]
            if Path(repository).expanduser().is_absolute():
                repository = str(absolute(repository))
            path = self.checkout_root / name
            if path.resolve() != path:
                raise Error(f"Managed checkout path must not redirect through a symlink: {path}")
            result[name] = Source(name, path, None, repository, data.get("branch"), (), {}, True)
        return result

    def declarations(self, source: Source) -> list[Item]:
        if not source.repository:
            return self.manifest(source)
        data = self.catalog()[source.name]
        relative_path = data.get("subdir", ".")
        payload = source.path if relative_path == "." else source.path / relative(relative_path)
        target = self.target(data.get("root", "skills"), Path(source.name))
        mode = self.modes.get(source.name, data.get("mode", "link"))
        return [Item(source.name, source.name, relative_path, payload, target, mode, "skill")]

    def target(self, root: str, destination: Path) -> Path:
        target = self.roots[root] / destination
        # Resolve ancestors but never follow an existing target symlink.
        target = target.parent.resolve() / target.name
        if self.roots[root] not in target.parents:
            raise Error(f"Target escapes its root: {target}")
        if any(target == r for r in self.roots.values()):
            raise Error(f"Cannot own an entire configured target root: {target}")
        protected = [s.path for s in self.sources.values()] + [self.state_dir, self.path]
        if self.catalog_path:
            protected.extend([self.catalog_path, self.checkout_root])
        if any(overlaps(target, path) for path in protected):
            raise Error(f"Target overlaps source, inventory, or manager state: {target}")
        return target

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
            target = self.target(root, dst_path)
            result.append(Item(source.name, item_id, src, src_abs, target, mode))
        return result
