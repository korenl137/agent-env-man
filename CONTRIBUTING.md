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

The primary input is a user-owned skill and instruction catalog, independent of the repositories it lists.
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

Instruction bundles select a named Git repository or a logical external source without source-local manifests.
Keep external path bindings in machine configuration and shared source/root/entry selections in the catalog.
Bootstrap accepts a positional catalog and repeated optional --external NAME=PATH bindings, persists them in the selected/default machine file, and reuses omitted bindings.
Default agent and skills roots only when absent; validate declarations and existing ownership before saving bindings or contacting repositories.
Keep explicit --config, --catalog, root/storage overrides, and legacy NAME --path bootstrap compatible.
Do not parse document policy, applicability, or reading order.
A Codex instruction bundle owns a directory link, a direct original-entry link, and one SessionStart group in the entry root's hooks.json.
Bootstrap only prepares and validates sources; apply installs links and merges the hook without granting Codex trust or modifying config.toml.
Preserve unrelated JSON events, groups and metadata; malformed or redirected hook files must fail preflight.
Own the complete AEM group identified by its saved marker, not the whole hooks file, and aggregate selected groups into one replacement per target file to avoid competing transactions.
Entry selection includes bundle and hook installation, but never extends replacement permission to an implicitly selected bundle.
Report the required /hooks trust review after apply; preview must show the planned group without registering it.
Detach materializes both links and releases hook ownership while retaining its configuration, so saved locator records still support preserved documents.
Default bundle installation to `<machine-file>.bundles/<bundle-name>` without requiring a configured rules root; preserve explicit location overrides and relocation guards.
Resolve roots from saved installation records and actual filesystem links, not from prompt text or the current catalog.
The locator must remain offline, avoid updating ownership records, work for detached copies without a catalog, and reject missing or redirected entries and replaced active links.
Use an absolute interpreter for hook execution, quote POSIX arguments, and explicitly encode a PowerShell command on Windows without evaluating user paths.
The callback emits only path metadata as additionalContext, never document contents, and requests a structured stop on lookup failure.
Limit callback metadata to the effective root, entry, and global_entry reading locations; keep installed_root and detached in locator diagnostics so a preserved copy cannot be mistaken for the live entry's source tree.
Preserve original documents and use the existing per-target conflict/recovery machinery.
Guard the saved entry path of active Git bundles even when their catalog declarations disappear or a shared skill initiates update.
Instruction automatic policies are not supported; skill policies may still advance shared checkouts.

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

Only declared catalog skills/instruction bundles or explicitly registered legacy items may be installed; a content repository update cannot expand the local catalog.
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
Agent profiles are the internal extension boundary for paths, hook syntax, callback output, notices, and supported config merge operations.
Do not add a dynamic plugin loader or additional source providers without a demonstrated use case.

## Machine setup and agent integration

The repository installer uses uv to install this checkout as a user tool, then delegates integration to `aem setup`.
Keep the installer standard-library-only; configuration and ownership logic belong in the package.
Setup owns machine selection and startup registration, while bootstrap prepares content and apply installs it.
Catalog update policies must never register hooks implicitly.

Selections accumulate, and repeated setup must preserve unrelated content and avoid duplicate groups or blocks.
Preflight all profile edits before changing any of them, commit each target through the existing recovery journal, and save machine selection last.
A retry must recognize completed ownership records after a partial failure.
Setup removal must not delete user content or silently detach installed skills and instructions.
Do not grant agent hook trust or rewrite user execution policies.

Resolve product-specific defaults, hook serialization, callback output, and merge capabilities through internal agent profiles.
Codex remains the only shipped profile; use a fake profile to validate injection and multiple destinations without claiming support for another product.
Preserve legacy Codex item identities and command aliases.
Store per-target ownership and shared consumers independently from per-skill Git delivery and automatic attempt clocks.
A shared target has one owner, and cannot be materialized for just one of its consumers.
Explicit catalog roots retain their meaning; omitted destinations use selected agent defaults.

Test setup with temporary homes and fake installer subprocesses, never actual user profiles or live remote repositories.
Exercise repeat/add/remove, edited blocks, invalid hook files, redirected paths, grouped hook writes, partial failure/retry, offline previews, and fail-open startup.
Shell quoting and PowerShell serialization tests do not establish native shell or Windows readiness.
