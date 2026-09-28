# Contributing

## Development and validation

Use Python 3.11 or later and Git.
Create a virtual environment and install the project with `python -m pip install -e .`.
TOML Kit is the only runtime dependency; tests use the standard library.

```bash
python -m unittest discover -s tests -v
python -m compileall -q src tests
git diff --check
```

Run these commands from the activated environment.
On native Windows the same test command works with `.\.venv\Scripts\python.exe`.
Tests create temporary sources, targets, config, state, and local Git remotes; do not use actual user homes, credentials, or network remotes in tests.
Successful symlink tests skip if the host cannot create links; the simulated capability-failure test must still run.
The initial validation was performed on Linux with Python 3.12.
Native Windows tests have run on Python 3.12, but link-dependent tests require a host with symlink creation enabled before claiming full Windows readiness.

Preserve Linux/WSL and native Windows path handling.
Use Python filesystem/subprocess APIs, explicit UTF-8, argument lists, and `/` in shared relative paths.
Do not depend on a POSIX shell from the core.
Windows-only code must not import POSIX locking or signal primitives at runtime.

## Architectural contracts

The manager owns reusable installation and delivery behavior.
Personal instructions, research guidance, skills, and settings remain user-supplied content outside this repository.
Do not introduce personal policies as built-in payloads.

Delivery prepares local source paths; installation consumes those paths without network access.
Git must remain an end-to-end supported delivery path, not an external setup prerequisite that bypasses the core.
External folders do not imply ownership of the service that synchronizes them.
Keep source roots disjoint, and never nest externally synchronized sources inside managed Git checkouts.

Targets directly link to local source content.
Do not add snapshot activation semantics silently: changing this contract requires an explicit design decision and updated user documentation.
`update` therefore can change live instruction contents without `apply`.
The incoming-revision guard protects active link source paths, even if the latest manifest no longer declares those items.

The primary input is a user-owned skill catalog, independent of the repositories it lists.
The current loader reads a local TOML file; policy composition must remain independent of this transport and any future auxiliary-file layout.
Each skill has a stable name and selects one Git repository and optional subdirectory.
Named repository declarations let related skills share one URL, branch, and checkout; direct per-skill repository declarations remain supported.
Do not require upstream skill repositories to add manager manifests or aggregate their content in this repository.
The catalog owns repository URLs, requested branches, and declarative automatic update policies; machine configuration owns its catalog binding, checkout storage, target roots, and explicit mode overrides.
Bootstrap clones missing repositories directly from the catalog, discovers and records their default branches when unspecified, and validates SKILL.md before publishing a checkout.
Application paths consume these prepared local checkouts without fetching.
Share a checkout only when skills explicitly reference the same named repository; equal URLs in direct declarations do not imply shared ownership.
Validate every skill in a shared checkout before publishing it, and guard all active links from that checkout before advancing it.
Keep installation ownership and automatic policies per skill, even when delivery is shared.
Do not introduce a provider framework without a demonstrated need.
Content rendering and arbitrary shell evaluation are not part of path substitution.
The previous source-local links.conf workflow is compatibility support, not the model for new skill registration.
Keep its existing four-field parser and saved ownership records functional when changing the primary workflow.

## Automatic update contracts

Resolve policies by explicit field override: built-in defaults, catalog-wide defaults, one named policy, then skill-local fields.
Trigger arrays replace earlier arrays; `manual` disables all automatic events for the skill.
Validate all policy declarations, including unused named policies, before network access.
Keep common trigger/action/interval settings separate from source-specific delivery options; reject unsupported capabilities rather than substituting another action.

External callers supply shell-start, agent-start, or interval events to `auto`.
Policy configuration does not install hooks, modify shell profiles, register OS tasks, or imply an in-process scheduler.
Do not make ordinary apply/status/bootstrap perform implicit automatic updates.
Explicit commands retain their existing contracts and ignore automatic policy throttles.

Under the existing configuration lock, persist each skill's attempt before network access and throttle failures as well as successes across all its events.
Preview must not fetch or record attempts.
Automatic sync applies each successfully updated skill independently; this intentionally differs from explicit sync's all-updates-before-apply gate.
Preserve existing per-target transactions, stop if recovery is pending, and never adopt, replace conflicts, or reattach detached skills automatically.
Automatic policies cover catalog skills; legacy sources remain available through explicit commands.

## Ownership and safety

Only declared catalog skills or explicitly registered legacy items may be installed; a content repository update cannot expand the local catalog.
Catalog skill names identify ownership independently of repository URLs and paths; legacy items retain `(source ID, item ID)` identities.
Do not infer ownership from an existing file or delete targets when declarations disappear.
Reject overlapping target trees and require detach before changing an existing item's path or mode.
A directory item owns its entire subtree, so extra local files are meaningful modifications.
Repository-root skills are valid and use direct links, not an extra content layer.
Exclude only their top-level .git administration entry from content fingerprints, copies, and materializing detach; never duplicate a repository database or worktree pointer into an unmanaged skill.
Git identity checks still validate the managed checkout's origin and expected branch before applying or updating.

Link, copy, and merge have different contracts.
Never silently fall back from link to copy.
Copy conflict detection uses the last applied content, desired content, and actual target; Git revision alone is insufficient.
Merge ownership is per explicit leaf key, never an entire application config tree.
Do not replace a table to install a scalar or drop undeclared keys/comments.
This version restricts one merge item to a target file; do not extend that without resolving cross-item key ownership.

Prepare and verify a replacement before moving the current target.
Write the recovery journal before the first rename and commit the ownership record only after installation succeeds.
Keep target backups; cleanup must never remove user changes discovered during recovery.
The process lock serializes commands for one configuration, not arbitrary editors or Git processes.
Retain the documented per-target transaction boundary instead of claiming global atomicity.

Detach preserves the current usable contents, then releases ownership and records a tombstone to prevent automatic reinstallation.
It does not restore a pre-install value or delete merge keys.
Do not discard state when a target is missing, unreadable, or cannot be safely materialized.

## Validation expectations

Changes to delivery must exercise clone, fast-forward, dirty/divergent histories, network/remote failures, and live-link removal guards using local Git fixtures.
Catalog tests must start with repositories lacking links.conf, exercise root and nested skills, and keep the inventory independent of both checkouts and installation roots.
Verify that missing inventory files do not prevent status from observing installed contents or detach from preserving them.
Changes to installation must exercise unmanaged targets, local edits, directory contents, partial config preservation, detach, and failure recovery.
Policy changes must cover precedence, manual opt-out, event selection, offline preview/check-only behavior, per-skill throttling including failures, independent outcomes, and preservation of local edits and detached skills.
Test meaningful user-visible behavior and preservation boundaries rather than mirroring private implementation functions.
Keep command contracts, examples, and platform limitations in the README aligned with behavior.
Do not add an application-specific adapter framework or additional source providers without a demonstrated use case.
