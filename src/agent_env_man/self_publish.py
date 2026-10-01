"""Publish a prepared AEM release independently of machine/catalog state."""

from importlib import metadata
import json
from pathlib import Path
import subprocess
import tomllib
from urllib.parse import urlsplit
from urllib.request import url2pathname

from .git_source import Git
from .model import Error, Source
from .self_update import release_version


def checkout_path(checkout=None):
    """Select an explicit root, recorded local installation source, or own src tree.

    Installation provenance is a candidate, not proof of Git identity. A stale
    recorded local path must fail validation instead of selecting another tree.
    Never infer a publication target from the working directory.
    """
    if checkout is not None:
        return Path(checkout).expanduser().resolve()
    try:
        recorded = metadata.distribution("agent-env-man").read_text("direct_url.json")
    except metadata.PackageNotFoundError:
        recorded = None
    if recorded is not None:
        try:
            value = json.loads(recorded)
            if not isinstance(value, dict) or not isinstance(value.get("url"), str):
                raise ValueError("invalid direct_url.json")
            url = urlsplit(value["url"])
            if url.scheme == "file" and "dir_info" in value:
                if (not isinstance(value["dir_info"], dict) or url.query or url.fragment
                        or url.netloc not in ("", "localhost")):
                    raise ValueError("unsupported local source URL")
                path = Path(url2pathname(url.path))
                if not path.is_absolute():
                    raise ValueError("local source path is not absolute")
                return path.resolve()
        except ValueError as exc:
            raise Error(f"Cannot read local installation source: {exc}; use --checkout PATH") from exc
    module = Path(__file__).resolve()
    root = module.parents[2]
    if (root / "src/agent_env_man/self_publish.py" == module
            and (root / "pyproject.toml").is_file()):
        return root
    raise Error("No local installation source or development checkout; use --checkout PATH")


def prepared(git, path):
    """Validate the entire checkout and pin the commit and original tag object."""
    try:
        git.validate_checkout(Source("self", path, None, None))
    except Error as exc:
        raise Error(f"{exc}; use --checkout PATH to select an AEM checkout root") from exc
    branch = git.run(path, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    if branch.returncode:
        raise Error("self: an attached branch is required; use Git to prepare the checkout")
    repositories = git.run(path, "remote", "get-url", "--all", "origin").stdout.splitlines()
    if len(repositories) != 1:
        raise Error("self: origin must have a single fetch destination; use Git for other combinations")
    repository = repositories[0]
    source = Source("self", path, repository, branch.stdout)
    report = {"checkout": str(path), "repository": repository, "branch": branch.stdout}
    git.clean(source)
    # Read the reviewed commit, not a working file that could change after the
    # cleanliness check. Require the same tracked regular metadata as self-update.
    revision = git.run(path, "rev-parse", "HEAD").stdout
    descriptor = git.run(path, "ls-tree", revision, "--", "pyproject.toml").stdout
    if not descriptor or descriptor.split(" ", 1)[0] not in ("100644", "100755"):
        raise Error("self: pyproject.toml must be a tracked regular file")
    project = tomllib.loads(git.run(path, "show", f"{revision}:pyproject.toml", strict_utf8=True).stdout).get("project")
    if not isinstance(project, dict) or project.get("name") != "agent-env-man":
        raise Error("self: checkout must contain project.name = 'agent-env-man'")
    version = project.get("version")
    if not isinstance(version, str) or release_version(version) is None:
        raise Error("self: project.version must be an X.Y.Z or X.Y.Z{a|b|rc}[N] release version")
    tag = "v" + version
    ref = "refs/tags/" + tag
    tagged = git.run(path, "rev-parse", "--verify", ref + "^{commit}", check=False)
    if tagged.returncode or tagged.stdout != revision:
        raise Error(f"self: prepare local tag {tag} pointing to HEAD using Git")
    tag_object = git.run(path, "rev-parse", "--verify", ref).stdout
    # Includes push-URL validation and rejects any unfinished Git operation.
    report.update(git.publication(source))
    report.update(version=version, tag=tag, revision=revision)
    return source, report, tag_object


def publish(checkout=None, *, dry_run=False, timeout=30):
    """Return (report, failed), publishing only existing branch/tag refs atomically.

    Preview is offline and does not mutate Git or AEM state. Actual publication
    fetches branch observations but never changes local commits, tags, or index.
    Failures retain the prepared release for retry; no sequential push fallback
    or history rewriting is permitted.
    """
    report = {"status": "planned", "network": not dry_run, "remote_verified": False}
    try:
        path = checkout_path(checkout)
        report["checkout"] = str(path)
        if not path.is_dir():
            raise Error("Local installation source is unavailable; use --checkout PATH")
        git = Git(timeout)
        source, details, tag_object = prepared(git, path)
        report.update(details)
        if dry_run:
            return report, False
        observed = git.publication_preflight(source)
        if observed is not None:
            relation = git.relation(source)
            report.update(remote_relation=relation, observed_revision=observed)
            if relation not in ("ahead", "equal-at-last-fetch"):
                raise Error(f"self: {relation}; reconcile Git history manually")
        else:
            report.update(initial_publish=True, remote_relation="unknown")
        ref = "refs/tags/" + report["tag"]
        listing = git.run(path, "ls-remote", "origin", ref, ref + "^{}").stdout
        refs = dict((fields[1], fields[0]) for line in listing.splitlines()
                    if len(fields := line.split()) == 2)
        remote_tag = refs.get(ref + "^{}", refs.get(ref))
        if listing and remote_tag is None:
            raise Error("self: cannot verify remote release tag")
        if remote_tag is not None and remote_tag != report["revision"]:
            raise Error(f"self: remote tag {report['tag']} points to a different commit; use Git to inspect it")
        report.update(remote_verified=True, tag_present=remote_tag is not None)
        # Revalidate after network inspection, then push pinned objects rather
        # than mutable HEAD/tag names. Existing equivalent remote tags retain
        # their annotation/signature even when the local tag object differs.
        final_source, final, final_tag = prepared(git, path)
        if (final_source != source or final["revision"] != report["revision"]
                or final_tag != tag_object):
            raise Error("self: checkout changed during publication; inspect and retry")
        refspecs = [f"{report['revision']}:refs/heads/{source.branch}"]
        if remote_tag is None:
            refspecs.append(f"{tag_object}:{ref}")
        git.run(path, "-c", "remote.origin.mirror=false", "push", "--porcelain", "--atomic",
                "--no-follow-tags", "origin", *refspecs)
        report["status"] = "published"
        return report, False
    except (Error, OSError, ValueError, subprocess.SubprocessError) as exc:
        report.update(status="failed", error=str(exc))
        return report, True
