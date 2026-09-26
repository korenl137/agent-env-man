"""Command boundaries, source registration, and optional trigger throttling."""

import argparse
from dataclasses import replace
import json
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time

import tomlkit

from .git_source import Git, now
from .manager import Manager
from .model import Config, Error, absolute, default_config, identifier, overlaps, relative
from .storage import State, atomic_write, exists, lock


def bootstrap_legacy(config, state, args):
    state.ready()
    name = identifier(args.name)
    if name in config.sources:
        raise Error("Source is already registered; edit machine.toml to add items or change local settings")
    path = absolute(args.path)
    relative(args.manifest)
    document = tomlkit.parse(tomlkit.dumps(config.doc))
    roots = document.setdefault("roots", {})
    home = Path.home()
    defaults = {"home": home, "codex": Path(os.environ.get("CODEX_HOME", home / ".codex")),
                "skills": home / ".agents/skills", "rules": home / ".agent-rules",
                "config": Path(os.environ.get("APPDATA", home / "AppData/Roaming")) if os.name == "nt"
                else Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))}
    if os.name == "nt":
        defaults.update(appdata=defaults["config"], localappdata=Path(os.environ.get("LOCALAPPDATA", home / "AppData/Local")))
    explicit = {}
    for value in args.root:
        key, separator, location = value.partition("=")
        if not separator:
            raise Error("--root expects NAME=ABSOLUTE_PATH")
        identifier(key)
        resolved = str(absolute(location))
        if key in config.roots and config.roots[key] != Path(resolved):
            raise Error(f"Root {key} is already configured; bootstrap will not relocate existing items")
        explicit[key] = resolved
    for key, location in defaults.items():
        roots.setdefault(key, str(location))
    roots.update(explicit)
    registration = {"path": str(path), "manifest": args.manifest, "items": []}
    if args.git:
        registration.update(git=args.git, branch=args.branch or "main")
    elif args.attach:
        raise Error("--attach is only needed with --git")
    document.setdefault("sources", {})[name] = registration
    candidate_config = Config(config.path, document=document)
    source = candidate_config.sources[name]
    for old in state.data["items"].values():
        if not old.get("detached") and overlaps(path, Path(old["target"])):
            raise Error("New source overlaps an existing managed target")
    temporary = None
    try:
        if args.git:
            git = Git(args.timeout)
            if exists(path):
                if not args.attach:
                    raise Error("Checkout path already exists; use --attach to explicitly register it")
                git.clean(source)
            else:
                if args.attach:
                    raise Error("Cannot attach a missing checkout")
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = Path(tempfile.mkdtemp(prefix=".aem-clone-", dir=path.parent))
                git.run(None, "clone", "--single-branch", "--branch", source.branch, "--", source.git, str(temporary))
                git.clean(replace(source, path=temporary))
        elif not path.is_dir():
            raise Error("External source must already exist as a local directory")
        manifest_root = temporary or path
        manifest_text = (manifest_root / source.manifest).read_text(encoding="utf-8")
        items = candidate_config.manifest(source, manifest_text)
        available = {i.id for i in items}
        requested = set(args.item) if args.item else available
        if requested - available:
            raise Error("Requested IDs are missing from the active manifest: " + ", ".join(sorted(requested - available)))
        document["sources"][name]["items"] = sorted(requested)
        candidate_config = Config(config.path, document=document)
        Manager(candidate_config, state).check_destinations([i for i in items if i.id in requested])
        if temporary:
            if exists(path):
                raise Error("Checkout destination appeared while cloning; refusing replacement")
            os.rename(temporary, path)
            temporary = None
        atomic_write(config.path, tomlkit.dumps(document).encode("utf-8"))
        if args.git:
            record = state.data["sources"].setdefault(name, {})
            record.update(revision=git.run(path, "rev-parse", "HEAD").stdout)
            if not args.attach:
                record.update(last_fetch=now(), observed_revision=record["revision"])
            state.save()
        return {"source": name, "path": str(path), "registered_items": sorted(requested),
                "roots": {k: str(v) for k, v in candidate_config.roots.items()}, "next": "apply --dry-run"}
    finally:
        if temporary:
            shutil.rmtree(temporary)


def bootstrap_skills(config, state, args):
    state.ready()
    if args.path or args.git or args.branch or args.attach or args.manifest != "links.conf":
        raise Error("Declare each skill's Git repository and optional branch/subdir in the local catalog")
    document = tomlkit.parse(tomlkit.dumps(config.doc))
    if args.catalog is not None:
        document["catalog"] = str(args.catalog.expanduser().resolve())
    if "catalog" not in document:
        raise Error("Use bootstrap --catalog /path/to/skills.toml")
    if args.checkout_root is not None:
        document["checkout_root"] = str(args.checkout_root.expanduser().resolve())
    roots = document.setdefault("roots", {})
    for value in args.root:
        key, separator, location = value.partition("=")
        if not separator:
            raise Error("--root expects NAME=ABSOLUTE_PATH")
        identifier(key)
        resolved = str(absolute(location))
        if key in config.roots and config.roots[key] != Path(resolved):
            raise Error(f"Root {key} is already configured; detach before relocating installed skills")
        roots[key] = resolved
    roots.setdefault("skills", str(Path.home() / ".agents/skills"))
    candidate = Config(config.path, document=document)
    if set(args.item) - candidate.catalog().keys():
        raise Error("Unknown catalog skill selection")
    manager = Manager(candidate, state)
    # Validate all declarations/ownership before saving a machine binding or
    # contacting any repository. Failed downloads can then be retried in place.
    manager.selected(args.item)
    atomic_write(config.path, tomlkit.dumps(document).encode("utf-8"))
    report, failed = manager.prepare_skills(args.item, timeout=args.timeout)
    return {"skills": report, "config": str(config.path), "next": "apply --dry-run"}, failed


def parser():
    result = argparse.ArgumentParser(prog="aem", description="Install Git-managed skills from an independent inventory")
    result.add_argument("--config", type=Path, default=default_config(), help="machine-local TOML file")
    commands = result.add_subparsers(dest="command", required=True)
    boot = commands.add_parser("bootstrap", help="prepare Git skills from a local catalog; never install targets")
    boot.add_argument("name", nargs="?", help="legacy links.conf source name")
    boot.add_argument("--catalog", type=Path, help="local inventory of skill names, source types, and repositories")
    boot.add_argument("--checkout-root", type=Path, help="device-local storage for managed skill checkouts")
    boot.add_argument("--path", help="legacy source checkout path")
    boot.add_argument("--git")
    boot.add_argument("--branch", help="legacy source branch (default: main)")
    boot.add_argument("--manifest", default="links.conf")
    boot.add_argument("--root", action="append", default=[], metavar="NAME=PATH")
    boot.add_argument("--item", action="append", default=[], metavar="ID")
    boot.add_argument("--attach", action="store_true")
    boot.add_argument("--timeout", type=float, default=30)
    update = commands.add_parser("update", help="fetch and fast-forward Git sources; live links change immediately")
    update.add_argument("source", nargs="*")
    update.add_argument("--timeout", type=float, default=30)
    for name in ("apply", "sync"):
        command = commands.add_parser(name, help="install registered local items" if name == "apply" else "update, then apply only if all updates succeed")
        command.add_argument("--item", action="append", default=[], metavar="NAME")
        command.add_argument("--timeout", type=float, default=30)
        if name == "apply":
            choices = command.add_mutually_exclusive_group()
            choices.add_argument("--adopt", action="store_true", help="register matching existing targets/keys")
            choices.add_argument("--replace", action="store_true", help="back up and replace conflicts for explicit --item selections")
            command.add_argument("--reattach", action="store_true", help="allow explicitly selected detached items")
            command.add_argument("--dry-run", action="store_true")
        else:
            command.add_argument("--min-interval", type=float, default=0, help="minimum seconds between attempts, including failures")
    status = commands.add_parser("status", help="inspect local state; network is opt-in")
    status.add_argument("--refresh", action="store_true")
    status.add_argument("--timeout", type=float, default=30)
    detach = commands.add_parser("detach", help="preserve current contents and release ownership")
    detach.add_argument("item", nargs="+", metavar="NAME")
    detach.add_argument("--dry-run", action="store_true")
    commands.add_parser("recover", help="restore the previous target after an interrupted replacement")
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if hasattr(args, "timeout") and (not math.isfinite(args.timeout) or args.timeout <= 0):
            raise Error("--timeout must be positive and finite")
        config = Config(args.config, missing_ok=args.command == "bootstrap")
        with lock(config.state_dir):
            # Read again under the lock: another process may just have registered a source.
            config = Config(args.config, missing_ok=args.command == "bootstrap")
            state = State(config.state_dir)
            manager = Manager(config, state)
            failed = False
            if args.command == "bootstrap":
                if args.name:
                    if not args.path or args.catalog or args.checkout_root:
                        raise Error("Legacy bootstrap needs NAME --path PATH; catalog bootstrap does not take NAME")
                    report = bootstrap_legacy(config, state, args)
                else:
                    report, failed = bootstrap_skills(config, state, args)
            elif args.command == "update":
                report, failed = manager.update(args.source, timeout=args.timeout)
            elif args.command == "apply":
                report = manager.apply(args.item, adopt=args.adopt, replace=args.replace,
                                       reattach=args.reattach, dry_run=args.dry_run, timeout=args.timeout)
            elif args.command == "status":
                report = manager.status(refresh=args.refresh, timeout=args.timeout)
            elif args.command == "detach":
                report = manager.detach(args.item, dry_run=args.dry_run)
            elif args.command == "recover":
                manager.recover()
                report = {"status": "recovered"}
            else:
                state.ready()
                current = time.time()
                if not math.isfinite(args.min_interval) or args.min_interval < 0:
                    raise Error("--min-interval must be nonnegative and finite")
                if current - state.data.get("last_sync_attempt", 0) < args.min_interval:
                    report = {"status": "throttled"}
                else:
                    state.data["last_sync_attempt"] = current
                    state.save()
                    updates, failed = manager.update(timeout=args.timeout)
                    report = {"updates": updates, "apply": "skipped"}
                    if not failed:
                        report["apply"] = manager.apply(args.item, timeout=args.timeout)
            print(json.dumps(report, indent=2, ensure_ascii=True))
            return 1 if failed else 0
    except (Error, OSError, ValueError) as exc:
        print(f"aem: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
