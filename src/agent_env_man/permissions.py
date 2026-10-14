"""Permission preservation is separate from payload equality and ownership."""

import errno
import hashlib
import json
import os
from pathlib import Path
import stat

from .model import Error


def validate(value, location="permissions"):
    if not isinstance(value, str) or value not in ("strict", "best-effort"):
        raise Error(f"{location}: expected strict or best-effort")
    return value


def mode(info):
    # Windows chmod exposes the read-only attribute, not POSIX access classes.
    return info.st_mode & stat.S_IWRITE if os.name == "nt" else stat.S_IMODE(info.st_mode)


def snapshot(path, **policy):
    """Observe native modes without following links or including exclusions."""
    result = {}
    if os.name != "nt":
        from .payload_links import scan
        scan(path, modes=result, modes_only=True, allow_symlinks=policy.get("preserve_symlinks", False),
             **{k: v for k, v in policy.items() if k != "preserve_symlinks"})
        return result
    from .payload_policy import excluded
    from .storage import is_reparse
    root = Path(path)
    def visit(current, relative):
        before = current.lstat()
        if stat.S_ISLNK(before.st_mode) or is_reparse(current):
            raise Error(f"Payload symlinks/junctions are unsupported: {current}")
        if not (stat.S_ISDIR(before.st_mode) or stat.S_ISREG(before.st_mode)):
            raise Error(f"Special files are unsupported: {current}")
        result[relative or "."] = mode(before)
        if stat.S_ISDIR(before.st_mode):
            for child in sorted(current.iterdir()):
                name = "/".join(p for p in (relative, child.name) if p)
                if not (policy.get("exclude_git") and not relative and child.name == ".git") and not excluded(name, policy.get("exclusions", ()), policy.get("exclude_prefix", "")):
                    visit(child, name)
        after = current.lstat()
        if (before.st_dev, before.st_ino, before.st_mode) != (after.st_dev, after.st_ino, after.st_mode):
            raise Error(f"Payload permissions changed during inspection: {current}")
    visit(root, "")
    return result


def digest(modes):
    return hashlib.sha256(json.dumps(modes, sort_keys=True).encode()).hexdigest()


def differences(requested, actual, failures=()):
    result = {path: {"path": path, "requested": wanted, "actual": actual.get(path)}
              for path, wanted in requested.items() if actual.get(path) != wanted}
    for failure in failures:
        path = failure["path"]
        result.setdefault(path, {"path": path, "requested": failure["requested"], "actual": actual.get(path)})["error"] = failure["error"]
    return [result[path] for path in sorted(result)]


def apply(target, wanted, *, path=".", failures=None):
    """Only unsupported/denied permission setters are optional, never I/O errors."""
    try:
        (os.fchmod if isinstance(target, int) else os.chmod)(target, wanted)
    except OSError as exc:
        if exc.errno not in {errno.EPERM, errno.EACCES, errno.ENOSYS, errno.ENOTSUP, errno.EOPNOTSUPP}:
            raise
        if failures is not None:
            failures.append({"path": path, "requested": wanted if os.name != "nt" else wanted & stat.S_IWRITE,
                             "error": str(exc)})
