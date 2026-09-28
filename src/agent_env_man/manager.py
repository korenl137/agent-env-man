"""Explicit ownership and per-target transactions; delivery lives elsewhere."""

from dataclasses import dataclass, replace, field
import os
from pathlib import Path
import shutil
import json
import stat
import tempfile
import uuid

from .agents import profile, suffix
from .git_source import Git, now
from .model import MachineFile, Error, Item, identifier, overlaps, relative
from .storage import State, copy_payload, exists, fingerprint, is_reparse, observation, remove, saved_path


@dataclass
class Plan:
    item: Item
    before: dict
    record: dict
    change: bool
    content: bytes | None = None
    materialize: Path | None = None
    records: dict = field(default_factory=dict)
    peers: list = field(default_factory=list)


class Manager:
    def __init__(self, config: MachineFile, state: State):
        self.config, self.state = config, state

    def delivery_source(self, source):
        if source.git and source.branch is None:
            branch = self.state.data["sources"].get(source.name, {}).get("branch")
            if not branch:
                raise Error(f"{source.name}: run bootstrap to prepare the checkout and record its default branch")
            return replace(source, branch=branch)
        return source

    def prepare_skills(self, names=(), *, timeout=30):
        """Clone listed repositories, validating skills before publishing a checkout.

        Clone success does not install anything. Existing checkouts are checked
        in place and never reset or pulled by bootstrap.
        """
        self.state.ready()
        sources = self.config.sources
        if set(names) - sources.keys():
            raise Error("Unknown catalog source selection")
        self.check_destinations([i for s in sources.values() for i in self.config.declarations(s)])
        report, failed = [], False
        groups = {}
        for name, source in sources.items():
            groups.setdefault(source.path, []).append((name, source))
        for members in groups.values():
            selected = [(name, source) for name, source in members if not names or name in names]
            if not selected:
                continue
            name, source = members[0]
            temporary = None
            try:
                if not source.git:
                    for _, member in members:
                        for item in self.config.declarations(member):
                            self.payload(item)
                    report.extend({"source": n, "status": "external-ready", "path": str(source.path)} for n, _ in selected)
                    continue
                git = Git(timeout)
                created = not exists(source.path)
                source_state = self.state.data["sources"].setdefault(name, {})
                previous_branch = source_state.get("branch") if source_state.get("repository") == source.git else None
                branch = source.branch or previous_branch
                if created:
                    source.path.parent.mkdir(parents=True, exist_ok=True)
                    temporary = Path(tempfile.mkdtemp(prefix=".aem-clone-", dir=source.path.parent))
                    options = ("--branch", branch) if branch else ()
                    git.run(None, "clone", "--single-branch", *options, "--", source.git, str(temporary))
                local_path = temporary or source.path
                if branch is None:
                    branch = git.run(local_path, "symbolic-ref", "--quiet", "--short", "HEAD").stdout
                prepared = replace(source, path=local_path, branch=branch)
                git.clean(prepared)
                # A shared checkout is published only when every declared skill is valid.
                for skill_name, skill_source in members:
                    item = self.config.declarations(skill_source)[0]
                    if item.kind == "skill":
                        git.skill_descriptor(prepared, item.relative)
                    else:
                        git.instruction_descriptor(prepared, item.relative, item.entry)
                    payload = local_path / item.relative
                    if item.kind == "skill" and not (payload / "SKILL.md").is_file():
                        raise Error(f"{skill_name}: skill path must contain SKILL.md")
                    cursor = payload
                    while cursor != local_path:
                        if cursor.is_symlink() or is_reparse(cursor):
                            raise Error(f"Skill source contains a symlink/junction: {cursor}")
                        cursor = cursor.parent
                    fingerprint(payload, exclude_git=item.relative == ".")
                revision = git.run(local_path, "rev-parse", "HEAD").stdout
                if temporary:
                    if exists(source.path):
                        raise Error("Checkout destination appeared while cloning; refusing replacement")
                    os.rename(temporary, source.path)
                    temporary = None
                for skill_name, _ in members:
                    member_state = self.state.data["sources"].setdefault(skill_name, {})
                    member_state.update(repository=source.git, branch=branch, revision=revision, error=None)
                    if created:
                        member_state.update(last_fetch=now(), observed_revision=revision)
                for skill_name, _ in selected:
                    report.append({"skill": skill_name, "status": "cloned" if created else "already-prepared", "checkout": str(source.path)})
            except (Error, OSError, ValueError) as exc:
                failed = True
                for skill_name, _ in selected:
                    self.state.data["sources"].setdefault(skill_name, {})["error"] = str(exc)
                    report.append({"skill": skill_name, "status": "failed", "error": str(exc)})
            finally:
                if temporary:
                    # Git can mark object files read-only on Windows; a failed
                    # staged clone must still be removable before returning.
                    def writable_retry(operation, path, error):
                        os.chmod(path, stat.S_IWRITE)
                        operation(path)

                    shutil.rmtree(temporary, onerror=writable_retry)
            for skill_name, _ in selected:
                self.state.data["sources"].setdefault(skill_name, {})["last_attempt"] = now()
            self.state.save()
        return report, failed

    def items(self):
        self.config.catalog()
        result = []
        for source in self.config.sources.values():
            result.extend(self.config.declarations(source))
        return result

    @staticmethod
    def matches(item, requested):
        logical = item.source_name if item.kind == "skill" else f"{item.source_name}:{item.id.split('@')[0]}"
        return item.key in requested or logical in requested

    def selected(self, requested=(), *, reattach=False, agent=None):
        all_items = self.items()
        # Entry installation includes its directory and hook; selecting a hook
        # likewise needs a usable entry. Flags still require explicit selection.
        requested = set(requested)
        expanded = {i.key for i in all_items if self.matches(i, requested)}
        logical = {i.source_name if i.kind == "skill" else f"{i.source_name}:{i.id.split('@')[0]}" for i in all_items}
        requested = expanded | (requested - logical - {i.key for i in all_items})
        for item in all_items:
            if item.key in requested and item.kind in ("instruction-entry", "instruction-hook"):
                requested.update(f"{item.source_name}:{part}{suffix(item.agent)}" for part in ("bundle", "entry", "hook"))
        registered = {i.key for i in all_items}
        detached = {k for k, r in self.state.data["items"].items() if r.get("detached")}
        if requested - registered:
            raise Error("Unknown item selection: " + ", ".join(sorted(requested - registered)))
        if reattach and not requested:
            raise Error("--reattach requires explicit --item selections")
        items = [i for i in all_items if not requested or i.key in requested]
        items = [i for i in items if reattach or not self.state.data["items"].get(i.key, {}).get("detached")]
        self.check_destinations([i for i in all_items if i.key not in detached])
        if agent is not None:
            profile(agent)
            items = [i for i in items if agent in (i.agents or (i.agent,))]
        self.check_destinations(items)
        return items

    def check_destinations(self, items):
        # Include inactive/orphaned ownership, not only the current catalog.
        owners = {k: Path(r["target"]) for k, r in self.state.data["items"].items() if not r.get("detached")}
        for item in items:
            old = self.state.data["items"].get(item.key)
            if old and not old.get("detached") and (old["target"] != str(item.target) or old["mode"] != item.mode
                                                    or old["source"] != str(item.source)):
                raise Error(f"{item.key}: path or mode changed; detach before reconfiguration")
            for key, target in owners.items():
                if key != item.key and overlaps(item.target, target):
                    other = next((i for i in items if i.key == key), None)
                    old_other = self.state.data["items"].get(key, {})
                    if (item.target == target and item.mode == "agent-hook"
                            and ((other and other.mode == "agent-hook" and other.agent == item.agent)
                                 or (old_other.get("mode") == "agent-hook"
                                     and old_other.get("agent", "codex") == item.agent))):
                        continue
                    raise Error(f"Overlapping targets: {item.key} and {key}")
            owners[item.key] = item.target

    def payload(self, item):
        root = self.config.sources[item.source_name].path
        # Intermediate source symlinks would bypass directory-tree validation.
        cursor = item.source
        while cursor != root:
            if cursor.is_symlink() or is_reparse(cursor):
                raise Error(f"Source path contains a symlink/junction: {cursor}")
            cursor = cursor.parent
        if item.kind == "skill" and (not item.source.is_dir() or not (item.source / "SKILL.md").is_file()):
            raise Error(f"{item.key}: skill path must be a directory containing SKILL.md")
        if item.kind in ("instruction", "instruction-hook"):
            if not item.source.is_dir() or not (item.source / item.entry).is_file():
                raise Error(f"{item.key}: instruction bundle needs a regular entry document: {item.entry}")
        if item.kind == "instruction-entry" and not item.source.is_file():
            raise Error(f"{item.key}: instruction entry must be a regular file")
        return fingerprint(item.source, exclude_git=item.kind in ("skill", "instruction", "instruction-hook") and item.relative == ".")

    def locate(self, name, agent="codex"):
        """Resolve a saved installation without loading its catalog or fetching sources.

        Detached bundles resolve to their preserved directory; active bundles
        must still have the recorded link so an unrelated replacement is not read.
        """
        self.state.ready()
        key = f"{identifier(name)}:bundle{suffix(agent)}"
        record = self.state.data["items"].get(key)
        if not record or record.get("kind") != "instruction":
            raise Error(f"{name}: instruction bundle has not been installed")
        target = Path(record["target"])
        if record.get("detached"):
            if target.is_symlink() or is_reparse(target):
                raise Error(f"{name}: detached bundle directory was replaced by a link")
        elif not target.is_symlink() or os.readlink(target) != record["source"]:
            raise Error(f"{name}: installed bundle link was replaced; inspect status")
        root = target.resolve(strict=True)
        if not root.is_dir():
            raise Error(f"{name}: installed bundle root is not a directory")
        entry = root / relative(record["entry"])
        # Refuse redirected entry paths, including intermediate links/junctions.
        cursor = entry
        while cursor != root:
            if cursor.is_symlink() or is_reparse(cursor):
                raise Error(f"{name}: entry path contains a symlink/junction")
            cursor = cursor.parent
        if not entry.is_file():
            raise Error(f"{name}: original entry document is missing: {entry}")
        return {"root": str(root), "entry": str(entry), "installed_root": str(target),
                "detached": bool(record.get("detached"))}

    def hook_context(self, name, agent="codex"):
        """Return location metadata only; personal instruction text stays in AGENTS.md."""
        found = self.locate(name, agent)
        record = self.state.data["items"].get(f"{name}:entry{suffix(agent)}")
        if not record or record.get("kind") != "instruction-entry" or record["mode"] != "link":
            raise Error(f"{name}: original instruction entry link is not installed")
        target = Path(record["target"])
        if not target.is_file():
            raise Error(f"{name}: installed global entry is unavailable")
        if record.get("detached") and (target.is_symlink() or is_reparse(target)):
            raise Error(f"{name}: detached global entry was replaced by a link")
        if not record.get("detached") and observation(target) != {"kind": "link", "to": record["source"]}:
            raise Error(f"{name}: global entry link was replaced; inspect status")
        if found["detached"] and not record.get("detached"):
            # A directory can be detached independently while AGENTS.md still
            # links to the live original. Its references must use that original
            # tree until the entry is materialized too, not the frozen copy.
            source_entry = Path(record["source"])
            source_root = source_entry
            for _ in relative(record["entry"]).parts:
                source_root = source_root.parent
            cursor = source_entry
            while True:
                if cursor.is_symlink() or is_reparse(cursor):
                    raise Error(f"{name}: live entry source was redirected")
                if cursor == source_root:
                    break
                cursor = cursor.parent
            found.update(root=str(source_root.resolve(strict=True)), entry=str(source_entry.resolve(strict=True)))
        # Expose reading locations only: after partial detach, installed_root
        # can name a preserved copy that no longer matches the live entry.
        locations = {"root": found["root"], "entry": found["entry"], "global_entry": str(target)}
        context = ("AEM instruction document locations (not instruction contents):\n"
                   + json.dumps(locations, ensure_ascii=True)
                   + "\nFor relative document references in this global entry, use the original entry's "
                   "directory as the base unless the user documents specify another base. "
                   "Follow those documents for applicability and reading order.")
        return profile(agent).context(context)

    def plan(self, item, *, adopt=False, replace=False, reattach=False):
        payload_hash = self.payload(item)
        before = observation(item.target)
        old = self.state.data["items"].get(item.key)
        if old and old.get("detached"):
            if not reattach:
                raise Error(f"{item.key}: detached; use --reattach")
            if item.mode != "agent-hook":
                old = None
        record = {"source_name": item.source_name, "relative": item.relative, "source": str(item.source),
                  "id": item.id,
                  "target": str(item.target), "mode": item.mode, "hash": payload_hash,
                  "directory": item.source.is_dir(), "detached": False, "kind": item.kind,
                  "exclude_git": item.kind in ("skill", "instruction", "instruction-hook") and item.relative == ".",
                  "entry": item.entry, "agent": item.agent, "agents": list(item.agents or (item.agent,))}
        present = before["kind"] != "missing"
        if item.mode == "agent-hook":
            marker, group = profile(item.agent).definition(self.config.path, item.source_name)
            content = profile(item.agent).render(item.target, marker, group, old, adopt=adopt, replace=replace)
            record.update(hook_marker=marker, hook_group=group)
            changed = not present or item.target.read_bytes() != content
            return Plan(item, before, record, changed, content=content)
        if item.mode == "link":
            correct = before == {"kind": "link", "to": str(item.source)}
            if old:
                safe = correct or not present
            else:
                safe = not present or (adopt and correct)
            if not safe and not replace:
                raise Error(f"{item.key}: existing or modified target; use explicit --adopt or --replace")
            return Plan(item, before, record, not correct)
        if item.mode == "copy":
            regular = before["kind"] in ("file", "directory")
            desired = regular and before["hash"] == payload_hash
            if old:
                safe = not present or (regular and before["hash"] in (old["hash"], payload_hash))
            else:
                safe = not present or (adopt and desired)
            if not safe and not replace:
                raise Error(f"{item.key}: existing or locally modified copy; use explicit --adopt or --replace")
            return Plan(item, before, record, not desired)
        raise Error(f"Unsupported installation mode: {item.mode}")

    def install(self, plan):
        item = plan.item
        if item.target.parent.resolve() / item.target.name != item.target:
            raise Error(f"{item.key}: target ancestry changed after preflight")
        if observation(item.target) != plan.before:
            raise Error(f"{item.key}: target changed after preflight")
        if plan.materialize is None and item.kind != "setup" and self.payload(item) != plan.record["hash"]:
            raise Error(f"{item.key}: source changed after preflight")
        for peer in plan.peers:
            if self.payload(peer.item) != peer.record["hash"]:
                raise Error(f"{peer.item.key}: source changed after preflight")
        if not plan.change:
            self.state.data["items"].update({item.key: plan.record, **plan.records})
            self.state.save()
            return
        item.target.parent.mkdir(parents=True, exist_ok=True)
        suffix = uuid.uuid4().hex
        stage = item.target.with_name(".aem-stage-" + suffix)
        backup = item.target.with_name(item.target.name + ".aem-backup-" + suffix)
        try:
            if plan.materialize is not None:
                exclude_git = plan.record.get("exclude_git", False)
                copy_payload(plan.materialize, stage, exclude_git=exclude_git)
                if fingerprint(stage) != plan.record["hash"] or fingerprint(plan.materialize, exclude_git=exclude_git) != plan.record["hash"]:
                    raise Error(f"{item.key}: linked contents changed during detach")
            elif item.mode == "link":
                try:
                    stage.symlink_to(item.source, target_is_directory=item.source.is_dir())
                except OSError as exc:
                    raise Error("Cannot create a symbolic link; enable Windows Developer Mode/link privileges "
                                "or explicitly configure this item as copy") from exc
            elif item.mode == "copy":
                copy_payload(item.source, stage, exclude_git=plan.record.get("exclude_git", False))
                if fingerprint(stage) != plan.record["hash"] or self.payload(item) != plan.record["hash"]:
                    raise Error(f"{item.key}: source changed while copying")
            else:
                fd = os.open(stage, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as stream:
                    stream.write(plan.content)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.chmod(stage, stat.S_IMODE(item.target.stat().st_mode) if exists(item.target) else 0o600)
            if observation(item.target) != plan.before:
                raise Error(f"{item.key}: target changed during staging")
            after = observation(stage)
            # Persist recovery paths before moving the old target. No journal is
            # needed for pure ownership adoption, which only writes state once.
            self.state.data["pending"] = {"key": item.key, "target": str(item.target), "stage": str(stage),
                                          "backup": str(backup), "before": plan.before, "after": after}
            self.state.save()
            if exists(item.target):
                os.replace(item.target, backup)
            os.replace(stage, item.target)
            if observation(item.target) != after:
                raise Error(f"{item.key}: installed target changed before commit")
            old_records = dict(self.state.data["items"])
            self.state.data["items"].update({item.key: plan.record, **plan.records})
            self.state.data["pending"] = None
            try:
                self.state.save()
            except Exception:
                self.state.data["items"] = old_records
                # Reload the durable journal for recovery after a failed commit.
                self.state.data["pending"] = State(self.config.state_dir, maintenance=self.state.maintenance).data["pending"]
                raise
        except Exception:
            if self.state.data.get("pending"):
                self.recover()
            raise
        finally:
            if exists(stage) and not self.state.data.get("pending"):
                remove(stage)

    def recover(self):
        pending = self.state.data.get("pending")
        if pending is None:
            return
        if not all(k in pending for k in ("target", "backup", "stage", "before", "after")):
            raise Error("Incomplete recovery journal; cannot safely recover")
        target, backup, stage = (saved_path(pending[k]) for k in ("target", "backup", "stage"))
        if len({target, backup, stage}) != 3 or any(p.parent != target.parent for p in (backup, stage)):
            raise Error("Recovery paths must be distinct siblings")
        for field in ("before", "after"):
            value = pending[field]
            if (not isinstance(value, dict) or value.get("kind") not in ("missing", "link", "file", "directory")
                    or (value["kind"] == "link" and not isinstance(value.get("to"), str))
                    or (value["kind"] in ("file", "directory") and not isinstance(value.get("hash"), str))):
                raise Error("Invalid recovery observation; cannot safely recover")
        current = observation(target)
        before, after = pending["before"], pending["after"]
        if exists(backup):
            if observation(backup) != before or current not in (after, {"kind": "missing"}):
                raise Error("Recovery stopped: target or backup changed; preserve both and resolve manually")
            if exists(target):
                remove(target)
            os.replace(backup, target)
        elif current == before:
            pass  # Crash before the first rename, or recovery already restored it.
        elif before == {"kind": "missing"} and current == after:
            remove(target)
        else:
            raise Error("Recovery stopped: cannot safely restore the recorded target")
        if exists(stage):
            if observation(stage) != after:
                raise Error("Recovery stopped: staged content changed")
            remove(stage)
        self.state.data["pending"] = None
        self.state.save()

    def apply(self, requested=(), *, adopt=False, replace=False, reattach=False, dry_run=False, timeout=30, agent=None):
        self.state.ready()
        if (adopt or replace) and not requested:
            raise Error("--adopt and --replace require explicit --item selections")
        items = self.selected(requested, reattach=reattach, agent=agent)
        revisions = {}
        for name in {i.source_name for i in items}:
            source = self.config.sources[name]
            if source.git:
                git = Git(timeout)
                source = self.delivery_source(source)
                git.clean(source)
                revisions[name] = git.run(source.path, "rev-parse", "HEAD").stdout
                for item in [i for i in items if i.source_name == name]:
                    if item.kind == "skill":
                        git.skill_descriptor(source, item.relative)
                    elif item.kind in ("instruction", "instruction-hook"):
                        git.instruction_descriptor(source, item.relative, item.entry)
                    else:
                        git.tracked_payload(source, item.relative)
        def explicit(item):
            return self.matches(item, requested) or (item.kind == "instruction-hook" and
                (f"{item.source_name}:entry" in requested or f"{item.source_name}:entry{suffix(item.agent)}" in requested))
        plans = [self.plan(i, adopt=adopt and explicit(i), replace=replace and explicit(i), reattach=reattach)
                 for i in items]
        for plan in plans:
            plan.record["revision"] = revisions.get(plan.item.source_name)
        report = [{"item": p.item.key, "action": "install" if p.change else "record", "target": str(p.item.target)} for p in plans]
        for entry, plan in zip(report, plans):
            if plan.item.mode == "agent-hook":
                entry.update(hook="would-register" if dry_run and plan.change else "registered" if plan.change else "unchanged",
                             trust="not-managed-by-aem", notice=profile(plan.item.agent).notice,
                             hook_group=plan.record["hook_group"])
        grouped = self.group_hooks(plans)
        if not dry_run:
            for plan in grouped:
                self.install(plan)
        return report

    def group_hooks(self, plans):
        """Preflight each group, but commit one replacement per hook file."""
        grouped = {}
        result = []
        for plan in plans:
            if plan.item.mode != "agent-hook":
                result.append(plan)
                continue
            grouped.setdefault(plan.item.target, []).append(plan)
        for target, group in grouped.items():
            first = group[0]
            if len(group) > 1:
                with tempfile.TemporaryDirectory() as directory:
                    shadow = Path(directory) / "hooks.json"
                    if exists(target):
                        shadow.write_bytes(target.read_bytes())
                    for plan in group:
                        old = self.state.data["items"].get(plan.item.key)
                        shadow.write_bytes(profile(plan.item.agent).render(shadow, plan.record["hook_marker"],
                                           plan.record["hook_group"], old, adopt=True, replace=True))
                    first.content = shadow.read_bytes()
                first.change = not exists(target) or first.content != target.read_bytes()
                first.records = {p.item.key: p.record for p in group[1:]}
                first.peers = group[1:]
            result.append(first)
        return result

    def detach(self, keys, *, dry_run=False, agent=None):
        self.state.ready()
        requested = set(keys)
        records = self.state.data["items"]
        def logical(key, record):
            return record.get("source_name") if record.get("kind") == "skill" else key.split('@')[0]
        expanded = [k for k, r in records.items() if k in requested or logical(k, r) in requested]
        unknown = requested - records.keys() - {logical(k, r) for k, r in records.items()}
        if unknown:
            raise Error(f"Not a managed item: {sorted(unknown)}")
        keys = [k for k in expanded if agent is None or agent in records[k].get("agents", [records[k].get("agent", "codex")])]
        if agent:
            profile(agent)
            for key in keys:
                if len(records[key].get("agents", [])) > 1:
                    raise Error(f"{key}: shared target; detach without --agent to release all consumers")
        # Preserve the registered hook on detach, but release its ownership with
        # the entry. Saved bundle records let it locate materialized contents.
        for key in list(keys):
            old = self.state.data["items"].get(key, {})
            hook_key = f"{old.get('source_name')}:hook{suffix(old.get('agent', 'codex'))}"
            if old.get("kind") == "instruction-entry" and hook_key in self.state.data["items"] and hook_key not in keys:
                keys.append(hook_key)
        plans, untouched = [], []
        for key in keys:
            old = self.state.data["items"].get(key)
            if old is None:
                raise Error(f"Not a managed item: {key}")
            if old.get("detached"):
                continue
            target = saved_path(old.get("target"))
            if not exists(target):
                raise Error(f"{key}: target is missing; cannot preserve usable contents")
            record = dict(old, detached=True)
            if target.is_symlink():
                content = target.resolve(strict=True)
                exclude_git = old.get("exclude_git", False)
                if not isinstance(exclude_git, bool):
                    raise Error(f"{key}: invalid saved copy exclusion")
                record["hash"] = fingerprint(content, exclude_git=exclude_git)
                # Use the saved key as an opaque transaction identity. No old
                # source declaration or install-mode interpreter is needed.
                item = Item("", key, ".", content, target, "link", "skill")
                plans.append(Plan(item, observation(target), record, True, materialize=content))
            else:
                # Preserve regular contents for any recorded mode, including
                # opaque partial ownership. Never release unreadable payloads.
                fingerprint(target)
                untouched.append((key, record))
        if not dry_run:
            for plan in plans:
                self.install(plan)
            for key, record in untouched:
                self.state.data["items"][key] = record
            self.state.save()
        return [{"item": key, "action": "detach"} for key in keys]

    def update(self, names=(), *, timeout=30):
        self.state.ready()
        if set(names) - self.config.sources.keys():
            raise Error("Unknown source selection")
        results, failed = [], False
        groups = {}
        for name, source in self.config.sources.items():
            groups.setdefault(source.path, []).append((name, source))
        for members in groups.values():
            selected = [(name, source) for name, source in members if not names or name in names]
            if not selected:
                continue
            name, source = members[0]
            source_state = self.state.data["sources"].setdefault(name, {})
            try:
                if source.git:
                    Git(timeout).update(self.delivery_source(source), self.state.data["items"], source_state)
                    status = "updated"
                else:
                    if not source.path.is_dir():
                        raise Error(f"External source missing: {source.path}")
                    status = "external-no-fetch"
                    source_state["error"] = None
                for skill_name, _ in members:
                    if skill_name != name:
                        self.state.data["sources"].setdefault(skill_name, {}).update(
                            {key: source_state[key] for key in ("last_fetch", "observed_revision", "last_update", "revision", "error")
                             if key in source_state})
                results.extend({"source": skill_name, "status": status} for skill_name, _ in selected)
            except (Error, OSError) as exc:
                failed = True
                for skill_name, _ in selected:
                    self.state.data["sources"].setdefault(skill_name, {})["error"] = str(exc)
                    results.append({"source": skill_name, "status": "failed", "error": str(exc)})
            for skill_name, _ in selected:
                self.state.data["sources"].setdefault(skill_name, {})["last_attempt"] = now()
            self.state.save()
        return results, failed

    def item_status(self, item, old):
        if old and old.get("detached"):
            return "detached", None
        desired = self.payload(item)
        current = observation(item.target)
        if old is None:
            return "unmanaged-existing" if current["kind"] != "missing" else "not-installed", None
        if old["target"] != str(item.target) or old["mode"] != item.mode or old["source"] != str(item.source):
            return "configuration-changed", None
        if current["kind"] == "missing":
            return "missing", None
        if item.mode == "agent-hook":
            marker, group = profile(item.agent).definition(self.config.path, item.source_name)
            if profile(item.agent).current(item.target, marker, group):
                return "current", None
            return ("stale" if profile(item.agent).current(item.target, old["hook_marker"], old["hook_group"])
                    else "modified-locally"), None
        if item.mode == "link":
            good = current == {"kind": "link", "to": str(item.source)}
            return ("current" if good else "modified-locally"), ("changed-live" if desired != old["hash"] else None)
        if item.mode == "copy":
            if current["kind"] not in ("file", "directory"):
                return "modified-locally", None
            actual = current["hash"]
            if actual == desired:
                return "current", None
            if actual == old["hash"]:
                return "stale", None
            return ("conflict" if desired != old["hash"] else "modified-locally"), None
        raise Error(f"Unsupported installation mode: {item.mode}")

    def status(self, *, refresh=False, timeout=30, agent=None):
        report = {"sources": [], "items": [], "pending": self.state.data.get("pending")}
        if "startup" in self.state.data:
            report["startup"] = self.state.data["startup"]
        try:
            sources = self.config.sources
        except Error as exc:
            report["catalog_error"] = str(exc)
            sources = {}
        seen = set()
        for name, source in sources.items():
            entry = {"source": name, "path": str(source.path), "transport": "git" if source.git else "external",
                     **self.state.data["sources"].get(name, {})}
            entry["last_update_error"] = entry.pop("error", None)
            entry["availability"] = "present" if source.path.is_dir() else "missing"
            try:
                if source.git:
                    git = Git(timeout)
                    source = self.delivery_source(source)
                    if refresh:
                        revision = git.fetch(source)
                        stored = self.state.data["sources"].setdefault(name, {})
                        stored.update(last_fetch=now(), observed_revision=revision)
                        self.state.save()
                        entry.update({k: v for k, v in stored.items() if k != "error"})
                    git.validate(source)
                    entry["head"] = git.run(source.path, "rev-parse", "HEAD").stdout
                    branch = git.run(source.path, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
                    entry["branch"] = branch.stdout if branch.returncode == 0 else "detached"
                    entry["checkout"] = "dirty" if git.run(source.path, "status", "--porcelain", "--untracked-files=all", "--ignored").stdout else "clean"
                    entry["remote_relation"] = git.relation(source)
                else:
                    entry["remote_relation"] = "externally-managed-unknown"
            except (Error, OSError, ValueError) as exc:
                entry["error"] = str(exc)
            try:
                for item in self.config.declarations(source):
                    seen.add(item.key)
                    if agent and agent not in (item.agents or (item.agent,)):
                        continue
                    item_entry = {"item": item.key, "target": str(item.target), "mode": item.mode}
                    old = self.state.data["items"].get(item.key)
                    if old:
                        item_entry["installation"] = self.installed_status(old)
                    try:
                        status, note = self.item_status(item, old)
                        item_entry.update(status=status)
                        if note:
                            item_entry["note"] = note
                    except (Error, OSError, ValueError) as exc:
                        item_entry.update(status="unavailable", error=str(exc))
                    report["items"].append(item_entry)
            except (Error, OSError, ValueError) as exc:
                entry["error"] = str(exc)
            report["sources"].append(entry)
        for key, old in self.state.data["items"].items():
            if old.get("mode") == "setup-config":
                continue
            if key not in seen and (agent is None or agent in old.get("agents", [old.get("agent", "codex")])):
                report["items"].append({"item": key, "target": old["target"],
                                        "installation": self.installed_status(old),
                                        "status": "detached" if old.get("detached") else "setup" if old.get("kind") == "setup" else "orphaned-or-source-unavailable"})
        return report

    def saved_status(self, *, agent=None, error=None):
        """Inspect recorded targets without interpreting source declarations or modes."""
        report = {"sources": [], "items": [], "pending": self.state.data["pending"],
                  "state_version": self.state.data["version"], "saved_only": True}
        if error:
            report["configuration_error"] = str(error)
        for key, record in self.state.data["items"].items():
            if agent and agent not in record.get("agents", [record.get("agent", "codex")]):
                continue
            item = {"item": key, "target": record.get("target"), "mode": record.get("mode"),
                    "status": "detached" if record.get("detached") else "recorded"}
            try:
                target = saved_path(record.get("target"))
                item["observation"] = observation(target)
                if target.is_symlink():
                    item["link_available"] = target.exists()
            except (Error, OSError, ValueError) as exc:
                item["error"] = str(exc)
            report["items"].append(item)
        return report

    def installed_status(self, record):
        """Inspect the last installed target even when its source is unavailable."""
        try:
            target = Path(record["target"])
            actual = observation(target)
            if record.get("detached"):
                return "unmanaged"
            if actual["kind"] == "missing":
                return "missing"
            if record["mode"] == "link":
                if actual != {"kind": "link", "to": record["source"]}:
                    return "modified-locally"
                return "linked" if target.exists() else "broken-link"
            if record["mode"] == "agent-hook":
                matches = profile(record.get("agent", "codex")).current(target, record["hook_marker"], record["hook_group"])
            elif record.get("kind") == "setup":
                block = record.get("block")
                matches = bool(block) and target.read_bytes().decode("utf-8").count(block) == 1
            elif record["mode"] == "copy":
                matches = actual.get("hash") == record["hash"]
            else:
                raise Error(f"Unsupported installation mode: {record['mode']}")
            return "matches-last-apply" if matches else "modified-locally"
        except (Error, OSError, ValueError):
            return "unreadable"
