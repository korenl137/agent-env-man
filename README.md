# agent-env-man

Install and update Git-managed AI agent skills and personal instruction bundles from a local inventory.
The inventory lists what you want; skill contents stay in their own repositories.
You do not need to combine those repositories or add a manager manifest to them.

```text
local skills.toml: skills + optional shared repositories
                |
             bootstrap: Git clone
                v
       device-local checkouts <--- update: Git fetch + fast-forward
                |
              apply
                v
       installed skills: link or explicit copy
```

Links point directly to checkouts, without a snapshot layer.
An update immediately changes content visible through links; copies change on apply.
Once prepared, the local skills remain usable offline.

## Install the manager

Requirements: Python 3.11 or later and Git.
Linux/WSL and native Windows are supported in the implementation.
Native Windows tests have run for non-symlink paths; symlink behavior still needs validation on a host with link creation enabled.

On Linux/WSL, from this repository:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/aem --help
```

On Windows PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\aem.exe --help
```

Examples below use `aem`; activate the environment or use the full executable path.
Configure Git credentials separately; network commands cannot prompt for authentication.
SSH uses OpenSSH batch mode.

## Write a local skill inventory

Create a `skills.toml` outside managed checkout storage:

```toml
version = 1

[repositories.research-tools]
repository = "https://github.com/OWNER/RESEARCH-TOOLS.git"

[skills.report-helper]
repo = "research-tools"
subdir = "skills/report-helper"

[skills.second-helper]
repo = "research-tools"
subdir = "skills/second-helper"

[skills.standalone-skill]
type = "git"
repository = "git@github.com:OWNER/STANDALONE-SKILL.git"
```

Replace the example repository locations with repositories you choose.
The table key is the skill's registration name and installed directory name; it does not rewrite the name inside SKILL.md.

| Field | Meaning |
| --- | --- |
| `type` | Required for a skill-local repository; currently only `git`. A named repository defaults to `git`. |
| `repository` | Git URL or absolute path to a local Git repository, including a bare repository; required for skill-local and named repository declarations. |
| `repo` | Reference to a named entry in `repositories`, as an alternative to a skill-local `repository`. |
| `subdir` | Skill directory inside the repository; defaults to `.` for a root skill. |
| `branch` | Optional branch on a skill-local or named repository. Otherwise bootstrap discovers and records the remote's default branch. |
| `root` | Target root name; defaults to `skills`. Its actual path is machine-local. |
| `mode` | `link` by default, or explicit `copy`. |
| `update` | Optional per-skill automatic update policy; see below. |

Subdirectories use literal `/`-separated paths without traversal or shell expansion.
The selected directory must contain a regular SKILL.md tracked by Git.
The manager does not execute installation scripts or validate skill prose/frontmatter as part of installation.
Each `[repositories.NAME]` entry accepts `repository` and optional `branch` (and optional `type = "git"`).
Skills referencing the same name share one checkout and branch; each still has its own installation, mode, and update policy.
Skill-local `repository` declarations retain separate checkouts even when their URLs match.
To move an installed skill from a skill-local repository declaration to `repo`, detach it, move the preserved target aside, then bootstrap and explicitly reattach it from the new source path.

## Personal instruction bundles

Start with the [complete instruction-bundle walkthrough](docs/instruction-bundles.md): it shows original files, both configuration files, every field's resolved path, generated output, and detach behavior.
Use [examples/instructions.toml](examples/instructions.toml) with [examples/instructions-machine.toml](examples/instructions-machine.toml) for instructions only.
Git skills are optional; [examples/combined-catalog.toml](examples/combined-catalog.toml) demonstrates declaring both in one version 1 catalog.
A bundle can contain the user's global entry document, development/research/workspace guidance, and reference documents in any directory layout.
AEM preserves this tree and does not interpret, merge, or author the instructions.

```toml
# Shared inventory, alongside existing [skills.*] and [repositories.*].
[externals.personal-documents]

[instructions.personal]
external = "personal-documents"
subdir = "guidance"
entry = "start.md"
entry_root = "agent"
entry_destination = "AGENTS.md"
```

| Field | Contract |
| --- | --- |
| `repo` / `external` | Exactly one named `repositories` or `externals` declaration. Git bundles use the existing named-repository URL/branch settings. External declarations are empty tables. |
| `subdir` | Bundle root relative to the source; defaults to `.`. |
| `entry` | Required regular entry file relative to the bundle root. Its name need not be AGENTS.md. |
| `root`, `destination` | Optional bundle location overrides. With neither set, AEM links the bundle at `<machine-file>.bundles/<bundle-name>` beside the machine file; no `rules` root is needed. `root` selects a configured machine root, and `destination` defaults to the bundle name. |
| `entry_root`, `entry_destination` | Codex home root name and relative destination for the direct original-entry link. AEM also merges a SessionStart hook into `hooks.json` at that root. |

Names must be distinct from skill and legacy source names.
Relative paths use `/`, without traversal, shell expansion, or absolute paths.
Bundle trees must contain only regular files and directories; symlinks, junctions, and Git submodules are rejected.
Git bundles require the entry and tree to be tracked; root bundles exclude top-level `.git` from fingerprints and detach copies.
There is no bundle copy-mode override in this version; link capability is required.

Bind the external folder with an optional bootstrap argument; no hand-written machine file is required:

```bash
aem bootstrap ~/ai-config/inventory.toml --external personal-documents=~/Syncthing/agent-documents
aem apply --dry-run
aem apply
aem status
```

Repeat `--external NAME=PATH` for multiple external sources.
AEM expands `~` and resolves relative external paths against the current working directory, then saves absolute paths in its machine configuration.
On another device, pass its own folder, such as `--external personal-documents=D:/Synced/agent-documents`, with the same catalog.
Git-only catalogs need no `--external` argument.
After registration, `aem bootstrap` reuses the saved catalog and bindings.

The default `agent` root is `CODEX_HOME` when set, otherwise `~/.codex`; the default `skills` root is `~/.agents/skills`.
Defaults are saved on first registration and do not override existing roots.
Use `--root agent=/custom/codex` or another named root to override a destination on initial setup, and `--checkout-root /custom/checkouts` to override checkout storage.
`--config /path/to/machine.toml` remains available before the command for separate installations; continue using it for later commands for that installation.
`bootstrap --catalog PATH` remains an alias for `bootstrap PATH`.
Existing installation ownership checks still apply when changing a saved binding.

External roots must be disjoint from other source roots, managed checkout storage, the inventory, and AEM state/configuration.
Multiple bundles may explicitly reference the same external declaration or named Git repository.
AEM never configures or invokes Syncthing or another external synchronization service.

Bootstrap prepares Git checkouts and validates external bundles without installing targets or hooks.
`bootstrap --item personal` selects the catalog source.
`apply --item personal:entry` includes the bundle and its hook; plain `apply` installs all declared items.
AEM links the original entry directly at the global AGENTS.md destination, leaving its text unchanged.
It merges one SessionStart group into the configured Codex home's `hooks.json`, preserving unrelated hooks and metadata.
Each Codex home can have one AEM instruction bundle per machine configuration; overlapping hook-file ownership is rejected.
Existing global entries still require explicit `--adopt` or `--replace`, and automatic dependency selection never authorizes replacing an existing bundle directory.

The hook invokes AEM's `codex-hook personal` callback with an absolute interpreter and machine config path.
That callback uses the local locator to resolve saved installation records and emits only root/entry paths and relative-reference guidance as Codex `additionalContext`.
It does not inject personal instruction contents, interpret applicability, fetch sources, or load the catalog.
The entry text therefore contains no script execution instructions and no generated policy.
The example uses a global Codex home and creates no repository-local AGENTS.md.

Apply reports the registered hook and tells you to open `/hooks` in the next Codex session, review and trust it, then start a new session.
AEM never grants hook trust, changes Codex feature flags, or claims that a registered hook has run.
New or changed hooks need Codex trust review; existing approvals are owned by Codex.
The hook matches session startup, resume, clear, and compaction, with a 10-second timeout.
See the [official Codex hook documentation](https://learn.chatgpt.com/docs/hooks) for discovery, trust, and event behavior.
Keep the installation's Python environment, AEM package, machine file, and state available to the hook.
`aem --config <machine-file> locate personal` remains available for manual diagnostics.

External edits become visible through the bundle link immediately, without apply.
`status` reports `changed-live`; `update` reports `external-no-fetch` and only checks that the external root exists.
If an external root, entry, or helper disappears, AEM does not restore it: status reports an unavailable payload or broken link where applicable; neither link is removed.
If its process starts but root lookup fails, the callback returns a structured stop request and visible error instead of a guessed root.
Individual helper removal is a live content change, not an error if the bundle and entry still exist; AEM does not parse document references.
Git update guards active bundles against entry deletion, tree removal/type changes, and unsupported links even after a declaration disappears.
Other document edits and deletions are visible immediately after a successful update.
Automatic policies remain skill-only; updating a skill in a shared Git checkout also changes linked bundles in that checkout, subject to the same guard.

```bash
aem --config ~/ai-config/machine.toml detach personal:bundle personal:entry
```

Detach materializes the complete bundle and global entry as regular local copies, and automatically releases ownership of the associated hook group.
It preserves hook registration and other hooks; the callback now locates the detached bundle copy from saved state.
This preserves usable instructions rather than disabling them: disable the retained hook explicitly through Codex `/hooks` if you no longer want it to run.
The three items have separate ownership records and tombstones; ordinary apply skips detached items.
A missing/unreadable source cannot be safely materialized, so detach fails without discarding ownership; restore the source first.
Detach, locate, and installed-state inspection still work without the catalog.
Removing a declaration never deletes installed targets or hook registrations.
Path/mode changes require detach before reconfiguration, except that an unchanged AEM-generated guide from the earlier implementation can migrate to the original-entry link in place.
Locally edited guides and hook groups remain conflicts; explicit replacement backs up the current target.

Transactions and recovery remain per target, not atomic across the two links and hook file.
A hook write failure can leave installed links; fix the reported error and retry apply.
The registered hook runs on root-session events; this version does not register a separate SubagentStart hook.
Native Windows hook execution and a real model session with trust approval remain integration validation limits.
There is no snapshot, remote catalog delivery, synchronization-service management, instruction rules language, or additional config.toml management.

## Prepare and install

```bash
aem bootstrap ~/ai-config/skills.toml
aem apply --dry-run
aem apply
```

Bootstrap saves the local catalog binding, clones the listed repositories, and validates the skill directories.
It does not install targets or modify the inventory or upstream repositories.
Failed clones are removed from staging; the saved machine binding lets you fix the repository location or connectivity and rerun `aem bootstrap`.
Already prepared checkouts are validated but not pulled or reset by bootstrap.

The default skill installation root is `~/.agents/skills`.
Use `--root skills=/absolute/path` to choose another agent's skill location, and `--checkout-root /absolute/path` to choose checkout storage.
Neither option belongs in the portable inventory.

Machine configuration defaults to `$XDG_CONFIG_HOME/agent-env-man/machine.toml` or `~/.config/agent-env-man/machine.toml` on Linux/WSL, and `%LOCALAPPDATA%\agent-env-man\machine.toml` on Windows.
Select a different file with `aem --config /path/machine.toml COMMAND`.
Bootstrap writes a configuration like:

```toml
version = 1
catalog = "/home/me/ai-config/skills.toml"

[roots]
skills = "/home/me/.agents/skills"
agent = "/home/me/.codex"
```

Default checkout storage is the sibling `machine.toml.checkouts/`: skill-local repositories use one child per skill name, while named repositories use `.aem-repositories/NAME`.
State is in `machine.toml.state/`.
You can set a top-level `checkout_root` explicitly.
A relative `catalog` value is interpreted relative to the machine configuration file.
Other machine paths must be absolute or use `~/`.
Do not sync machine config, checkouts, or state between devices; distribute the inventory separately and bootstrap it on each device.
Inventory synchronization itself is not implemented in this iteration.

To use copy explicitly on one device, add:

```toml
[modes]
report-helper = "copy"
```

Copy is never a silent fallback for failed symlinks.
On Windows, enable Developer Mode/link privileges or explicitly select copy.
Windows and WSL should have separate machine configurations and checkout/target locations.

## Daily commands

| Command | Behavior |
| --- | --- |
| `bootstrap [--item NAME ...]` | Prepare missing checkouts using the saved catalog binding. |
| `update [NAME ...]` | Fetch and fast-forward listed checkouts; existing links change immediately. |
| `apply [--item NAME ...]` | Install from prepared local checkouts without network access. |
| `apply --dry-run` | Validate and show planned actions without writing targets or ownership records. |
| `sync` | Update, then apply only if all updates succeed. |
| `auto --trigger EVENT [--item NAME ...] [--dry-run]` | Run due catalog skill policies for an external event, or preview them offline. |
| `status` | Report checkout, remote-observation, and installation states without contacting remotes. |
| `status --refresh` | Also fetch remote references without moving checkout branches or applying. |
| `detach NAME ...` | Keep current usable contents and release management; materialize links into directories. |
| `recover` | Restore a target after an interrupted replacement when recorded contents still match. |

Outputs are JSON; operation errors exit 1 and command-line usage errors exit 2.
A successful status report exits 0 even if its observations include conflicts or unavailable sources.
Read-only commands and dry runs may create a lock directory/file.

Adding an entry to your local catalog explicitly registers that skill.
Run bootstrap to prepare its checkout, then apply to install it.
Updates to a skill repository cannot add entries to the separate inventory.
Deleting an entry does not delete its target or cached checkout; status reports orphaned ownership, and detach can release it.
Detach records a tombstone, so a listed skill is not immediately installed again.
After moving a detached target aside, explicitly reattach with `aem apply --item NAME --reattach`.

## Preservation and conflicts

Existing unmanaged targets and locally changed copies are not overwritten automatically.
For matching existing content use `aem apply --item NAME --adopt`.
To replace a conflict while retaining a sibling backup, use `aem apply --item NAME --replace`.
Backups are named `<target>.aem-backup-<id>` and retained for manual review.
Directory items own their selected subtree; local additions to a copied skill count as modifications.

Apply validates selected items before writing, stages replacements, and journals each target replacement.
An ordinary replacement error attempts to restore that target; after interruption, inspect status and run recover.
Recovery refuses to overwrite later user edits.
Transactions are per target, so earlier successful items may remain applied if a later one fails.
Do not delete state to resolve conflicts: it contains ownership and recovery records.

Git operations never stash, reset, rebase, commit, or push automatically.
Updates refuse dirty/untracked/ignored local files, wrong/detached branches, unfinished Git operations, local-ahead history, and divergence.
Apply also requires a clean, correctly identified checkout.
An incoming commit cannot remove or change the type of an active link source, or remove its SKILL.md, without first detaching the skill.
For a shared checkout, this guard covers active links for every skill referencing that repository, including when `update NAME` selects one skill.
Changing an inventory repository URL does not silently reuse or repoint an old checkout.
Ordinary fetch/authentication failures keep the existing installation usable; a timeout/interruption during checkout can require manual repair.

Detach preserves current contents, including edits, instead of restoring an old version.
Copies remain untouched, and links are replaced only after a verified local copy is ready.
Root skills link directly to the repository root, so its .git entry is visible through that link; fingerprinting, copy, and detach exclude this top-level Git administration entry.
Nested symlinks/junctions, special files, and submodules are not supported as payloads in this version.
Portable copy metadata, including executable bits, is preserved; platform-specific ACLs/alternate streams and power-loss atomicity are outside the current guarantee.

## Automatic update policies

Automatic updates are opt-in and default to `trigger = "manual"`.
Add policy tables to the skill inventory alongside its existing skill declarations:

```toml
[updates.defaults]
trigger = ["shell-start", "agent-start"]
action = "sync"
min_interval = 600
timeout = 5

[updates.policies.observe]
action = "check"

[skills.report-helper.update]
policy = "observe"
min_interval = 3600

[skills.standalone-skill.update]
trigger = "manual"
```

`updates.defaults` applies to every catalog skill, regardless of its installation mode.
Settings resolve in this order: built-in defaults, inventory defaults, the skill's named policy, then explicit skill settings.
Only specified fields override earlier values; trigger lists replace earlier lists.
Named policies do not inherit other named policies.
The current catalog loader reads a local file; policy composition does not depend on that transport or on checkout paths.

| Field | Values and built-in default |
| --- | --- |
| `trigger` | `"manual"` (default), or one or more of `"shell-start"`, `"agent-start"`, `"interval"`. Use a string for one event or an array for several. `manual` cannot be combined with events. |
| `action` | `"sync"` (default) updates the prepared checkout and applies it; `"check"` only checks for remote changes. |
| `min_interval` | Minimum seconds between automatic attempts for each skill; default `600`, nonnegative. All its events share the same clock. `0` permits every invocation. |
| `timeout` | Positive, finite seconds for each Git phase of that skill's operation; default `30`. It is not a total deadline across skills or filesystem copying. |
| `policy` | Optional named policy selection, allowed only in a skill's `update` table. |

With Git, `check` fetches the configured branch and reports its relation to HEAD without moving the checkout or changing installed content.
`sync` fetches and fast-forwards, then applies: links see the checkout change immediately, and copies are refreshed by apply.
When skills share a checkout, advancing it changes all their live links at once; applying copies still follows each skill's selection and policy.
The policy vocabulary describes these outcomes; it does not expose Git commands as general configuration or add new source types.
Unknown fields, policies, triggers, and unsupported values are errors before any update starts.

Preview effective policies and which skills are due:

```bash
aem auto --trigger shell-start --dry-run
aem auto --trigger agent-start --item report-helper --dry-run
```

Dry runs neither contact remotes nor record attempts; they may create the configuration lock file.
Normal output reports each skill as `not-triggered`, `detached`, `throttled`, `checked`, `synced`, or `failed`; dry runs use `planned` for due skills.
Automatic execution requires prepared checkouts: run bootstrap for newly declared skills first.
A due `sync` can install a prepared but not yet installed skill, or recreate a missing managed target.
Detached skills are skipped without fetching and are never automatically reattached.

Attempts are saved before contacting the remote, including attempts that fail or are interrupted.
`status` includes each source's `automation` record with its latest attempt and outcome.
Automatic execution processes skills independently: a failed skill does not prevent another due skill from updating and applying.
It exits 1 if any attempted skill fails, and 0 if all succeed or are skipped.
An unresolved recovery journal stops further work until recovered.
Existing protections for local edits, unmanaged targets, dirty/divergent Git history, live links, and backups still apply.
There is no automatic adoption, conflict replacement, or global rollback.

Explicit `update`, `apply`, `sync`, and `status --refresh` keep their existing behavior and do not consult automatic policies or their attempt clocks.
In particular, explicit `sync` still applies only after all its updates succeed.
Legacy sources remain managed through those explicit commands; `auto` selects catalog skills only.

## Connect triggers

A trigger is an event supplied by a caller, not a background service started by TOML.
Connect the event you configured to the corresponding command:

| Caller | Command |
| --- | --- |
| Interactive shell startup | `aem auto --trigger shell-start` |
| An agent's supported session-start hook | `aem auto --trigger agent-start` |
| An OS scheduler, such as Task Scheduler or a Linux timer | `aem auto --trigger interval` |

For example, an interactive Bash startup file can call:

```bash
if [[ $- == *i* ]] && command -v aem >/dev/null 2>&1; then
    aem auto --trigger shell-start || true
fi
```

Use the installed executable's absolute path and `--config` in hooks or scheduled tasks when their environment differs from your terminal.
For Windows PowerShell, the invocation can be `& 'C:\path\to\aem.exe' --config 'C:\path\to\machine.toml' auto --trigger shell-start`.
Configure an agent hook to call the `agent-start` command using that agent's supported mechanism and allow startup to continue if updating fails.
Automatic update policies do not write hook files, shell profiles, or scheduler registrations.
The instruction-root SessionStart hook installed by `apply` is separate and never triggers an update.
For periodic updates, set `trigger = "interval"`, choose `min_interval`, and arrange recurring invocations; the manager checks what is due on each invocation and does not wait or launch a daemon.
Calls are synchronous, and the configuration lock prevents concurrent manager operations against the same state.

The earlier `aem sync --timeout 5 --min-interval 600` invocation remains supported with its configuration-wide throttle.
Use `auto` when events and per-skill settings should come from TOML.

## Compatibility

The initial source-local links.conf and Codex partial-merge workflow remains available as [legacy compatibility](docs/legacy-links.md).
It is not required by the skill catalog workflow.
Syncthing administration, additional repository types, inventory delivery, generalized merge adapters, and revert are deferred.

## AI disclosure

OpenAI Codex assisted with design, implementation, documentation, and automated tests.
