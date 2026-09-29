"""Catalog preparation, explicit commands, and startup callback boundaries."""

import argparse
from contextlib import nullcontext
import json
import math
from pathlib import Path
import subprocess
import sys

import tomlkit

from .agents import PROFILES, profile
from .git_source import now
from .manager import Manager
from .model import Config, MachineFile, Error, absolute, default_config, identifier
from .storage import State, atomic_write, lock
from .updates import TRIGGERS, run_updates, startup_briefing


def argument_identifier(value):
    try:
        return identifier(value)
    except Error as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def bootstrap_skills(config, state, args):
    state.ready()
    document = tomlkit.parse(tomlkit.dumps(config.doc))
    if args.catalog_path is not None:
        if args.catalog is not None:
            raise Error("Specify the catalog either positionally or with --catalog, not both")
        args.catalog = Path(args.catalog_path)
    if args.catalog is not None:
        document["catalog"] = str(args.catalog.expanduser().resolve())
    if "catalog" not in document:
        raise Error("Use bootstrap /path/to/catalog.toml")
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
        if key in ("agent", "skills") and "codex" in document.get("agents", {}):
            document["agents"]["codex"]["root" if key == "agent" else "skills"] = resolved
    defaults = next(iter(config.agents.values())) if config.agents else profile("codex").defaults()
    roots.setdefault("skills", defaults["skills"])
    roots.setdefault("agent", defaults["root"])
    external_names = set()
    for value in args.external:
        key, separator, location = value.partition("=")
        if not separator or not location:
            raise Error("--external expects NAME=PATH")
        identifier(key)
        if key in external_names:
            raise Error(f"Duplicate --external binding: {key}")
        external_names.add(key)
        document.setdefault("external_paths", {})[key] = str(Path(location).expanduser().resolve())
    candidate = Config(config.path, document=document)
    if external_names - candidate.external_names:
        raise Error("--external must name an external declared in the catalog")
    if set(args.item) - candidate.sources.keys():
        raise Error("Unknown catalog source selection")
    manager = Manager(candidate, state)
    # Validate all declarations/ownership before saving a machine binding or
    # contacting any repository. Failed downloads can then be retried in place.
    manager.selected([i.key for name in args.item for i in candidate.declarations(candidate.sources[name])])
    atomic_write(config.path, tomlkit.dumps(document).encode("utf-8"))
    report, failed = manager.prepare_skills(args.item, timeout=args.timeout)
    return {"skills": report, "config": str(config.path), "next": "apply --dry-run"}, failed


def parser():
    result = argparse.ArgumentParser(prog="aem", description="Install skills and personal instruction bundles from an independent inventory")
    result.add_argument("--config", type=Path, default=default_config(), help="machine-local TOML file")
    commands = result.add_subparsers(dest="command", required=True)
    setup_parser = commands.add_parser("setup", help="connect selected shells and agents; never bootstrap or apply")
    for flag, choices in (("shell", ("bash", "zsh", "powershell")), ("agent", tuple(PROFILES))):
        setup_parser.add_argument("--" + flag, action="append", default=[], choices=choices)
        setup_parser.add_argument("--remove-" + flag, action="append", default=[], type=argument_identifier,
                                 metavar="NAME", help="remove a saved integration, including retired names")
    setup_parser.add_argument("--executable", help="absolute installed aem executable")
    setup_parser.add_argument("--dry-run", action="store_true")
    boot = commands.add_parser("bootstrap", help="prepare Git skills and Git/external instruction bundles; never install targets")
    boot.add_argument("catalog_path", nargs="?", metavar="CATALOG", help="local catalog path")
    boot.add_argument("--catalog", type=Path, help="local inventory of skills, instruction bundles, and sources")
    boot.add_argument("--checkout-root", type=Path, help="device-local storage for managed skill checkouts")
    boot.add_argument("--root", action="append", default=[], metavar="NAME=PATH")
    boot.add_argument("--external", action="append", default=[], metavar="NAME=PATH", help="bind a catalog external source to a device-local folder; repeat for multiple sources")
    boot.add_argument("--item", action="append", default=[], metavar="NAME", help="catalog skill or instruction name; repeat to select multiple sources")
    boot.add_argument("--timeout", type=float, default=30)
    update = commands.add_parser("update", help="fetch and fast-forward Git sources; live links change immediately")
    update.add_argument("source", nargs="*")
    update.add_argument("--timeout", type=float, default=30)
    publish = commands.add_parser("publish", help="commit and push whole checkouts selected by skill or instruction name")
    publish.add_argument("source", nargs="+", metavar="NAME")
    publish.add_argument("-m", "--message", help="commit all nonignored checkout changes with this message before pushing")
    publish.add_argument("--dry-run", action="store_true", help="review grouped changes and commits offline without staging, committing, or pushing")
    publish.add_argument("--timeout", type=float, default=30)
    for name in ("apply", "sync"):
        command = commands.add_parser(name, help="install registered local items" if name == "apply" else "update, then apply only if all updates succeed")
        command.add_argument("--agent", choices=tuple(PROFILES))
        command.add_argument("--item", action="append", default=[], metavar="NAME")
        command.add_argument("--timeout", type=float, default=30)
        if name == "apply":
            choices = command.add_mutually_exclusive_group()
            choices.add_argument("--adopt", action="store_true", help="register matching existing targets")
            choices.add_argument("--replace", action="store_true", help="back up and replace conflicts for explicit --item selections")
            command.add_argument("--reattach", action="store_true", help="allow explicitly selected detached items")
            command.add_argument("--dry-run", action="store_true")
    auto = commands.add_parser("auto", help="run due skill policies for an external trigger")
    auto.add_argument("--trigger", required=True, choices=TRIGGERS)
    auto.add_argument("--item", action="append", default=[], metavar="NAME")
    auto.add_argument("--dry-run", action="store_true", help="show effective policies and due skills without fetching")
    status = commands.add_parser("status", help="inspect local state; network is opt-in")
    status.add_argument("--agent", choices=tuple(PROFILES))
    status.add_argument("--refresh", action="store_true")
    status.add_argument("--timeout", type=float, default=30)
    detach = commands.add_parser("detach", help="preserve current contents and release ownership")
    detach.add_argument("--agent", choices=tuple(PROFILES))
    detach.add_argument("item", nargs="+", metavar="NAME")
    detach.add_argument("--dry-run", action="store_true")
    locate = commands.add_parser("locate", help="locate installed skill/instruction content or prepared source paths without fetching")
    locate.add_argument("--agent", default="codex", choices=tuple(PROFILES))
    locate.add_argument("name", help="catalog skill or instruction bundle name")
    locate.add_argument("--source", action="store_true", help="resolve the current catalog source for editing and publication")
    commands.add_parser("recover", help="restore the previous target after an interrupted replacement")
    startup = commands.add_parser("startup", help="fail-open startup callback; policies still select the work")
    startup.add_argument("--trigger", required=True, choices=TRIGGERS)
    startup.add_argument("--agent", choices=tuple(PROFILES))
    agent_hook = commands.add_parser("agent-hook", help="emit agent-specific instruction location context")
    agent_hook.add_argument("name")
    agent_hook.add_argument("--agent", required=True, choices=tuple(PROFILES))
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if hasattr(args, "timeout") and (not math.isfinite(args.timeout) or args.timeout <= 0):
            raise Error("--timeout must be positive and finite")
        remove_only = (args.command == "setup" and (args.remove_shell or args.remove_agent)
                       and not (args.shell or args.agent))
        maintenance = args.command in ("detach", "recover", "locate", "agent-hook") or remove_only
        missing_ok = args.command in ("bootstrap", "setup", "startup")
        # Find the lock without requiring installation declarations to be valid.
        config = MachineFile(args.config, missing_ok=missing_ok)
        # SessionStart callbacks can overlap each other or startup updates.
        # Leave time for lookup/output within the installed 10-second hook limit.
        lock_timeout = 5 if args.command == "agent-hook" else 0
        with (nullcontext() if args.command == "setup" and args.dry_run
              else lock(config.state_dir, timeout=lock_timeout)):
            # Read again under the lock: another process may just have registered a source.
            saved_error = None
            if maintenance:
                config = MachineFile(args.config, missing_ok=missing_ok)
                state = State(config.state_dir, maintenance=True)
            else:
                try:
                    config = Config(args.config, missing_ok=missing_ok)
                    state = State(config.state_dir)
                except Error as exc:
                    if args.command != "status" or args.refresh:
                        raise
                    # An offline status remains a way to discover IDs to release
                    # when installation declarations or old modes are unusable.
                    config = MachineFile(args.config)
                    state = State(config.state_dir, maintenance=True)
                    saved_error = exc
            manager = Manager(config, state)
            failed = False
            if args.command == "setup":
                from .setup import setup, remove_integrations
                report = remove_integrations(manager, args) if remove_only else setup(manager, args)
            elif args.command == "startup":
                outcomes = []
                try:
                    outcomes, failed = run_updates(manager, args.trigger)
                    state.data["startup"] = {"trigger": args.trigger, "time": now(), "failed": failed, "outcomes": outcomes}
                except (Error, OSError, ValueError) as exc:
                    state.data["startup"] = {"trigger": args.trigger, "time": now(), "failed": True, "error": str(exc)}
                state.save()
                report, failed = (profile(args.agent).startup_result(startup_briefing(outcomes)) if args.agent else {}), False
            elif args.command == "bootstrap":
                report, failed = bootstrap_skills(config, state, args)
            elif args.command == "update":
                report, failed = manager.update(args.source, timeout=args.timeout)
            elif args.command == "publish":
                report, failed = manager.publish(args.source, message=args.message, dry_run=args.dry_run, timeout=args.timeout)
            elif args.command == "apply":
                report = manager.apply(args.item, adopt=args.adopt, replace=args.replace,
                                       reattach=args.reattach, dry_run=args.dry_run, timeout=args.timeout, agent=args.agent)
            elif args.command == "auto":
                report, failed = run_updates(manager, args.trigger, args.item, dry_run=args.dry_run)
            elif args.command == "agent-hook":
                report = manager.hook_context(args.name, args.agent)
            elif args.command == "locate":
                report = manager.locate(args.name, args.agent, source=args.source)
            elif args.command == "status":
                report = (manager.saved_status(agent=args.agent, error=saved_error) if saved_error
                          else manager.status(refresh=args.refresh, timeout=args.timeout, agent=args.agent))
            elif args.command == "detach":
                report = manager.detach(args.item, dry_run=args.dry_run, agent=args.agent)
            elif args.command == "recover":
                manager.recover()
                report = {"status": "recovered"}
            elif args.command == "sync":
                state.ready()
                updates, failed = manager.update(timeout=args.timeout)
                report = {"updates": updates, "apply": "skipped"}
                if not failed:
                    report["apply"] = manager.apply(args.item, timeout=args.timeout, agent=args.agent)
            print(json.dumps(report, indent=2, ensure_ascii=True))
            return 1 if failed else 0
    except (Error, OSError, ValueError, subprocess.SubprocessError) as exc:
        if args.command == "agent-hook":
            # A hook failure must be visible instead of silently omitting root
            # context. Let the selected agent encode its structured stop request.
            message = f"AEM instruction root lookup failed: {exc}"
            print(json.dumps(profile(args.agent).failure(message)))
            return 0
        print(f"aem: {exc}", file=sys.stderr)
        if args.command == "startup":
            print(json.dumps(profile(args.agent).startup_result() if args.agent else {}))
            return 0
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
