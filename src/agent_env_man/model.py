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
    instruction: bool = False


@dataclass(frozen=True)
class Item:
    source_name: str
    id: str
    relative: str
    source: Path
    target: Path
    mode: str
    kind: str = "payload"
    entry: str | None = None
    agent: str = "codex"
    agents: tuple[str, ...] = ()

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
        from .agents import bindings
        self.agents = bindings(self.doc)
        for name, paths in self.agents.items():
            for category, field in (("agent", "root"), ("skills", "skills")):
                key, path = f"aem-{category}-{name}", absolute(paths[field])
                if key in self.roots and self.roots[key] != path:
                    raise Error(f"Root {key} conflicts with the agent binding")
                self.roots[key] = path
        self.catalog_path = None
        self._catalog = None
        self._repositories = {}
        self._instructions = {}
        self._update_policies = {}
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

    @property
    def external_names(self) -> set[str]:
        """Return the logical external sources declared by the bound catalog."""
        self.catalog()
        return set(getattr(self, "_external_names", ()))

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
        if document.get("version") != 1 or set(document) - {"version", "skills", "repositories", "updates", "instructions", "externals"}:
            raise Error("Skill catalog needs version = 1 and a skills table")
        skills = document.get("skills", {})
        if not isinstance(skills, dict):
            raise Error("Catalog skills must be a TOML table")
        repositories = document.get("repositories", {})
        if not isinstance(repositories, dict):
            raise Error("Catalog repositories must be a TOML table")
        for name, data in repositories.items():
            identifier(name)
            if not isinstance(data, dict) or set(data) - {"type", "repository", "branch"}:
                raise Error(f"Invalid repository declaration: {name}")
            if data.get("type", "git") != "git":
                raise Error(f"Repository {name}: only type = 'git' is supported")
            self._validate_repository(data, f"Repository {name}")
        for name, data in skills.items():
            identifier(name)
            if not isinstance(data, dict) or set(data) - {"type", "repository", "repo", "subdir", "branch", "root", "mode", "update"}:
                raise Error(f"Invalid skill declaration: {name}")
            if data.get("type", "git" if "repo" in data else None) != "git":
                raise Error(f"Skill {name}: only type = 'git' is supported")
            if "repo" in data:
                if ("repository" in data or "branch" in data or not isinstance(data["repo"], str)
                        or data["repo"] not in repositories):
                    raise Error(f"Skill {name}: repo must name a declared repository; set its branch there")
            else:
                if name == ".aem-repositories" and repositories:
                    raise Error("Skill name .aem-repositories is reserved for shared checkouts")
                self._validate_repository(data, f"Skill {name}")
            if name in self._legacy_sources:
                raise Error(f"Skill name collides with a legacy source: {name}")
            path = data.get("subdir", ".")
            if path != ".":
                relative(path)
            root = data.get("root", "skills")
            if not isinstance(root, str) or (root not in self.roots and not ("root" not in data and self.agents)):
                raise Error(f"Skill {name}: missing target root {root!r}")
            if data.get("mode", "link") not in ("link", "copy"):
                raise Error(f"Skill {name}: expected link or copy mode")
        externals = document.get("externals", {})
        instructions = document.get("instructions", {})
        bindings = self.doc.get("external_paths", {})
        if not all(isinstance(x, dict) for x in (externals, instructions, bindings)):
            raise Error("externals, instructions and external_paths must be tables")
        for name, data in externals.items():
            identifier(name)
            if not isinstance(data, dict) or data:
                raise Error(f"External {name}: declare an empty table; paths belong in machine external_paths")
        for name, data in instructions.items():
            identifier(name)
            if name in skills or name in self._legacy_sources:
                raise Error(f"Instruction name collides with another source: {name}")
            if not isinstance(data, dict) or set(data) - {"repo", "external", "subdir", "entry", "root", "destination", "entry_root", "entry_destination"}:
                raise Error(f"Invalid instruction declaration: {name}")
            if ("repo" in data) == ("external" in data):
                raise Error(f"Instruction {name}: select exactly one repo or external")
            field = "repo" if "repo" in data else "external"
            choices = repositories if field == "repo" else externals
            if not isinstance(data[field], str) or data[field] not in choices:
                raise Error(f"Instruction {name}: unknown {field}")
            if field == "external" and data[field] not in bindings:
                raise Error(f"Instruction {name}: missing machine external_paths.{data[field]}")
            if data.get("subdir", ".") != ".":
                relative(data["subdir"])
            relative(data.get("entry"))
            for field in (f for f in ("root", "entry_root") if f in data):
                if not isinstance(data.get(field), str) or data[field] not in self.roots:
                    raise Error(f"Instruction {name}: missing target root {field}")
            relative(data.get("destination", name))
            if "entry_destination" in data:
                relative(data["entry_destination"])
            if "entry_root" not in data and not self.agents:
                raise Error(f"Instruction {name}: missing target root entry_root")
        external_paths = {identifier(k): absolute(v) for k, v in bindings.items()}
        protected = [self.path, self.state_dir, self.checkout_root, *[s.path for s in self._legacy_sources.values()]]
        if self.catalog_path:
            protected.append(self.catalog_path)
        paths = list(external_paths.values())
        for i, path in enumerate(paths):
            if any(overlaps(path, other) for other in protected + paths[:i]):
                raise Error("External source roots must be disjoint from other sources, checkouts, inventory and state")
        self._external_paths = external_paths
        self._external_names = set(externals)
        self._instructions = instructions
        if self.modes.keys() - skills.keys():
            raise Error("Machine mode override does not name a skill in the catalog")
        from .updates import resolve_policies

        self._update_policies = resolve_policies(document.get("updates", {}), skills)
        self._repositories = repositories
        self._catalog = skills
        return skills

    @staticmethod
    def _validate_repository(data, label):
        repository = data.get("repository")
        if not isinstance(repository, str) or not repository or repository.startswith("-"):
            raise Error(f"{label}: repository must be a Git URL or absolute local repository path")
        if not (Path(repository).expanduser().is_absolute() or ":" in repository):
            raise Error(f"{label}: use an absolute path for a local Git repository")
        if "branch" in data and (not isinstance(data["branch"], str) or not data["branch"] or data["branch"].startswith("-")):
            raise Error(f"{label}: branch must be a nonempty branch name")

    def update_policies(self) -> dict:
        """Return validated effective policies from the currently bound catalog."""
        self.catalog()
        return self._update_policies

    @property
    def sources(self) -> dict[str, Source]:
        """Derive checkout paths; the inventory never needs device-local bindings."""
        result = dict(self._legacy_sources)
        declarations = {**self.catalog(), **self._instructions}
        for name, data in declarations.items():
            if "external" in data:
                result[name] = Source(name, self._external_paths[data["external"]], None, None, None, self.instruction_ids(data), {}, instruction=True)
                continue
            shared = data.get("repo")
            settings = self._repositories[shared] if shared else data
            repository = settings["repository"]
            if Path(repository).expanduser().is_absolute():
                repository = str(absolute(repository))
            path = self.checkout_root / ".aem-repositories" / shared if shared else self.checkout_root / name
            if path.resolve() != path:
                raise Error(f"Managed checkout path must not redirect through a symlink: {path}")
            result[name] = Source(name, path, None, repository, settings.get("branch"), self.instruction_ids(data) if name in self._instructions else (), {}, True, name in self._instructions)
        return result

    def instruction_agents(self, data):
        # Explicit legacy destinations remain single-target. Match their binding
        # when possible, rather than interpreting one path as several agents.
        if "entry_root" in data:
            root = self.roots[data["entry_root"]]
            matches = [n for n, p in self.agents.items() if absolute(p["root"]) == root]
            if len(matches) > 1:
                raise Error("Explicit entry_root matches multiple agents")
            if matches:
                return matches
            if len(self.agents) == 1:
                return list(self.agents)
            if not self.agents or "codex" in self.agents:
                return ["codex"]  # Preserve the explicit legacy destination.
            raise Error("Explicit entry_root must match one selected agent")
        return sorted(self.agents, key=lambda n: (n != "codex", n))

    def instruction_ids(self, data):
        from .agents import suffix
        return tuple(part + suffix(n) for n in self.instruction_agents(data) for part in ("bundle", "entry", "hook"))

    def declarations(self, source: Source) -> list[Item]:
        from .agents import profile, suffix
        self.catalog()
        if source.name in self._instructions:
            data = self._instructions[source.name]
            subdir = data.get("subdir", ".")
            payload = source.path / subdir
            entry_relative = data["entry"] if subdir == "." else subdir + "/" + data["entry"]
            result = []
            for agent in self.instruction_agents(data):
                adapter, tail = profile(agent), suffix(agent)
                destination = data.get("destination", source.name) + (tail if "entry_root" not in data else "")
                target = self.target(data.get("root"), relative(destination))
                root = data.get("entry_root", f"aem-agent-{agent}")
                entry_target = self.target(root, relative(data.get("entry_destination", adapter.entry_name)))
                hook_target = self.target(root, relative(adapter.hook_name))
                result.extend([
                    Item(source.name, "bundle" + tail, subdir, payload, target, "link", "instruction", data["entry"], agent),
                    Item(source.name, "entry" + tail, entry_relative, payload / data["entry"], entry_target,
                         "link", "instruction-entry", data["entry"], agent),
                    Item(source.name, "hook" + tail, subdir, payload, hook_target, "codex-hook" if agent == "codex" else "agent-hook",
                         "instruction-hook", data["entry"], agent)])
            return result
        if not source.repository:
            return self.manifest(source)
        data = self.catalog()[source.name]
        relative_path = data.get("subdir", ".")
        payload = source.path if relative_path == "." else source.path / relative(relative_path)
        mode = self.modes.get(source.name, data.get("mode", "link"))
        names = sorted(self.agents, key=lambda n: (n != "codex", n)) if self.agents else ["codex"]
        by_target = {}
        for agent in names:
            root = data.get("root", f"aem-skills-{agent}" if self.agents else "skills")
            target = self.target(root, Path(source.name))
            by_target.setdefault(target, []).append(agent)
        return [Item(source.name, source.name + suffix(names[0]), relative_path, payload, target, mode, "skill",
                     agent=names[0], agents=tuple(names)) for target, names in by_target.items()]

    def target(self, root: str | None, destination: Path) -> Path:
        # Instruction bundles default to per-configuration storage, like checkouts.
        base = self.roots[root] if root is not None else (self.path.parent / (self.path.name + ".bundles")).resolve()
        target = base / destination
        # Resolve ancestors but never follow an existing target symlink.
        target = target.parent.resolve() / target.name
        if base not in target.parents:
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
