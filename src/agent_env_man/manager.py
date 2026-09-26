"""Explicit ownership and per-target transactions; delivery lives elsewhere."""

from dataclasses import dataclass
import os
from pathlib import Path
import stat
import uuid

from . import codex
from .git_source import Git, now
from .model import Config, Error, Item, overlaps
from .storage import State, copy_payload, exists, fingerprint, is_reparse, observation, remove


@dataclass
class Plan:
    item: Item
    before: dict
    record: dict
    change: bool
    content: bytes | None = None
    materialize: Path | None = None


class Manager:
    def __init__(self, config: Config, state: State):
        self.config, self.state = config, state

    def items(self):
        result = []
        for source in self.config.sources.values():
            result.extend(self.config.manifest(source))
        return result

    def selected(self, requested=(), *, reattach=False):
        all_items = self.items()
        registered = {f"{s.name}:{i}" for s in self.config.sources.values() for i in s.items}
        available = {i.key for i in all_items}
        detached = {k for k, r in self.state.data["items"].items() if r.get("detached")}
        missing = registered - available - detached
        if missing:
            raise Error("Registered items disappeared from manifests; detach them or edit registration: " + ", ".join(sorted(missing)))
        if requested and set(requested) - registered:
            raise Error("Unknown or unregistered item: " + ", ".join(sorted(set(requested) - registered)))
        if requested and set(requested) - available:
            raise Error("Selected items are no longer declared in a manifest")
        if reattach and not requested:
            raise Error("--reattach requires explicit --item SOURCE:ID selections")
        items = [i for i in all_items if i.key in registered and (not requested or i.key in requested)]
        items = [i for i in items if reattach or not self.state.data["items"].get(i.key, {}).get("detached")]
        self.check_destinations([i for i in all_items if i.key in registered and i.key not in detached])
        self.check_destinations(items)
        return items

    def check_destinations(self, items):
        # Include inactive/orphaned ownership, not only the current manifest.
        owners = {k: Path(r["target"]) for k, r in self.state.data["items"].items() if not r.get("detached")}
        for item in items:
            old = self.state.data["items"].get(item.key)
            if old and not old.get("detached") and (old["target"] != str(item.target) or old["mode"] != item.mode
                                                    or old["source"] != str(item.source)):
                raise Error(f"{item.key}: path or mode changed; detach before reconfiguration")
            for key, target in owners.items():
                if key != item.key and overlaps(item.target, target):
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
        return fingerprint(item.source)

    def plan(self, item, *, adopt=False, replace=False, reattach=False):
        payload_hash = self.payload(item)
        before = observation(item.target)
        old = self.state.data["items"].get(item.key)
        if old and old.get("detached"):
            if not reattach:
                raise Error(f"{item.key}: detached; use --reattach")
            old = None
        record = {"source_name": item.source_name, "relative": item.relative, "source": str(item.source),
                  "target": str(item.target), "mode": item.mode, "hash": payload_hash,
                  "directory": item.source.is_dir(), "detached": False}
        present = before["kind"] != "missing"
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
        desired = codex.declarations(item.source)
        document = codex.read(item.target)
        baseline = old.get("values", {}) if old else {}
        if set(baseline) - set(desired):
            raise Error(f"{item.key}: managed keys were removed; detach before changing the owned key set")
        for path, value in desired.items():
            found, current = codex.get(document, path)
            if path in baseline:
                safe = found and (codex.equal(current, baseline[path]) or codex.equal(current, value))
                # A missing file can be re-created; a removed key in a present file is a local edit.
                safe = safe or not present
            else:
                safe = not found or (adopt and codex.equal(current, value))
            if not safe and not replace:
                raise Error(f"{item.key}: unmanaged or locally modified key {path}; use explicit --adopt or --replace")
        content = codex.render(document, desired)
        record["values"] = desired
        changed = not present or item.target.read_bytes() != content
        return Plan(item, before, record, changed, content=content)

    def install(self, plan):
        item = plan.item
        if item.target.parent.resolve() / item.target.name != item.target:
            raise Error(f"{item.key}: target ancestry changed after preflight")
        if observation(item.target) != plan.before:
            raise Error(f"{item.key}: target changed after preflight")
        if plan.materialize is None and self.payload(item) != plan.record["hash"]:
            raise Error(f"{item.key}: source changed after preflight")
        if not plan.change:
            self.state.data["items"][item.key] = plan.record
            self.state.save()
            return
        item.target.parent.mkdir(parents=True, exist_ok=True)
        suffix = uuid.uuid4().hex
        stage = item.target.with_name(".aem-stage-" + suffix)
        backup = item.target.with_name(item.target.name + ".aem-backup-" + suffix)
        try:
            if plan.materialize is not None:
                copy_payload(plan.materialize, stage)
                if fingerprint(stage) != plan.record["hash"] or fingerprint(plan.materialize) != plan.record["hash"]:
                    raise Error(f"{item.key}: linked contents changed during detach")
            elif item.mode == "link":
                try:
                    stage.symlink_to(item.source, target_is_directory=item.source.is_dir())
                except OSError as exc:
                    raise Error("Cannot create a symbolic link; enable Windows Developer Mode/link privileges "
                                "or explicitly configure this item as copy") from exc
            elif item.mode == "copy":
                copy_payload(item.source, stage)
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
            old_record = self.state.data["items"].get(item.key)
            self.state.data["items"][item.key] = plan.record
            self.state.data["pending"] = None
            try:
                self.state.save()
            except Exception:
                if old_record is None:
                    self.state.data["items"].pop(item.key, None)
                else:
                    self.state.data["items"][item.key] = old_record
                # Reload the durable journal for recovery after a failed commit.
                self.state.data["pending"] = State(self.config.state_dir).data["pending"]
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
        if not pending:
            return
        target, backup, stage = (Path(pending[k]) for k in ("target", "backup", "stage"))
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

    def apply(self, requested=(), *, adopt=False, replace=False, reattach=False, dry_run=False, timeout=30):
        self.state.ready()
        if (adopt or replace) and not requested:
            raise Error("--adopt and --replace require explicit --item SOURCE:ID selections")
        items = self.selected(requested, reattach=reattach)
        revisions = {}
        for name in {i.source_name for i in items}:
            source = self.config.sources[name]
            if source.git:
                git = Git(timeout)
                git.clean(source)
                revisions[name] = git.run(source.path, "rev-parse", "HEAD").stdout
                for item in [i for i in items if i.source_name == name]:
                    git.tracked_payload(source, item.relative)
        plans = [self.plan(i, adopt=adopt, replace=replace, reattach=reattach) for i in items]
        for plan in plans:
            plan.record["revision"] = revisions.get(plan.item.source_name)
        report = [{"item": p.item.key, "action": "install" if p.change else "record", "target": str(p.item.target)} for p in plans]
        if not dry_run:
            for plan in plans:
                self.install(plan)
        return report

    def detach(self, keys, *, dry_run=False):
        self.state.ready()
        plans, untouched = [], []
        for key in dict.fromkeys(keys):
            old = self.state.data["items"].get(key)
            if old is None:
                raise Error(f"Not a managed item: {key}")
            if old.get("detached"):
                continue
            target = Path(old["target"])
            if not exists(target):
                raise Error(f"{key}: target is missing; cannot preserve usable contents")
            record = dict(old, detached=True)
            if old["mode"] == "link":
                if target.is_symlink():
                    content = target.resolve(strict=True)
                    record["hash"] = fingerprint(content)
                    item = Item(old["source_name"], key.split(":", 1)[1], old["relative"], Path(old["source"]), target, "link")
                    plans.append(Plan(item, observation(target), record, True, materialize=content))
                else:
                    # An editor may already have replaced the link. Keep its
                    # current regular contents, not the old source or baseline.
                    fingerprint(target)
                    untouched.append((key, record))
            else:
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
        for name, source in self.config.sources.items():
            if names and name not in names:
                continue
            source_state = self.state.data["sources"].setdefault(name, {})
            try:
                if source.git:
                    Git(timeout).update(source, self.state.data["items"], source_state)
                    status = "updated"
                else:
                    if not source.path.is_dir():
                        raise Error(f"External source missing: {source.path}")
                    status = "external-no-fetch"
                    source_state["error"] = None
                results.append({"source": name, "status": status})
            except (Error, OSError) as exc:
                failed = True
                source_state["error"] = str(exc)
                results.append({"source": name, "status": "failed", "error": str(exc)})
            source_state["last_attempt"] = now()
            self.state.save()
        return results, failed

    def item_status(self, item, old):
        if old and old.get("detached"):
            return "detached", None
        if item.id not in self.config.sources[item.source_name].items:
            return "unregistered", None
        desired = self.payload(item)
        current = observation(item.target)
        if old is None:
            return "unmanaged-existing" if current["kind"] != "missing" else "not-installed", None
        if old["target"] != str(item.target) or old["mode"] != item.mode or old["source"] != str(item.source):
            return "configuration-changed", None
        if current["kind"] == "missing":
            return "missing", None
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
        values, baseline = codex.declarations(item.source), old["values"]
        if set(baseline) - set(values):
            return "ownership-change", None
        document = codex.read(item.target)
        statuses = []
        for path, value in values.items():
            found, actual = codex.get(document, path)
            if path not in baseline:
                statuses.append("conflict" if found else "stale")
            elif found and codex.equal(actual, value):
                statuses.append("current")
            elif found and codex.equal(actual, baseline[path]):
                statuses.append("stale")
            else:
                statuses.append("modified-locally" if codex.equal(value, baseline[path]) else "conflict")
        for status in ("conflict", "modified-locally", "stale"):
            if status in statuses:
                return status, None
        return "current", None

    def status(self, *, refresh=False, timeout=30):
        report = {"sources": [], "items": [], "pending": self.state.data.get("pending")}
        seen = set()
        for name, source in self.config.sources.items():
            entry = {"source": name, "path": str(source.path), "transport": "git" if source.git else "external",
                     **self.state.data["sources"].get(name, {})}
            entry["last_update_error"] = entry.pop("error", None)
            entry["availability"] = "present" if source.path.is_dir() else "missing"
            try:
                if source.git:
                    git = Git(timeout)
                    if refresh:
                        revision = git.fetch(source)
                        stored = self.state.data["sources"].setdefault(name, {})
                        stored.update(last_fetch=now(), observed_revision=revision)
                        self.state.save()
                        entry.update({k: v for k, v in stored.items() if k != "error"})
                    git.validate(source)
                    entry["checkout"] = "dirty" if git.run(source.path, "status", "--porcelain", "--untracked-files=all", "--ignored").stdout else "clean"
                    entry["remote_relation"] = git.relation(source)
                else:
                    entry["remote_relation"] = "externally-managed-unknown"
            except (Error, OSError, ValueError) as exc:
                entry["error"] = str(exc)
            try:
                for item in self.config.manifest(source):
                    seen.add(item.key)
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
            if key not in seen:
                report["items"].append({"item": key, "target": old["target"],
                                        "installation": self.installed_status(old),
                                        "status": "detached" if old.get("detached") else "orphaned-or-source-unavailable"})
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
            if record["mode"] == "copy":
                matches = actual.get("hash") == record["hash"]
            else:
                document = codex.read(target)
                matches = all(found and codex.equal(value, expected)
                              for key, expected in record["values"].items()
                              for found, value in [codex.get(document, key)])
            return "matches-last-apply" if matches else "modified-locally"
        except (Error, OSError, ValueError):
            return "unreadable"
