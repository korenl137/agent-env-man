# agent-env-man

Install and update Git-managed AI agent skills from a local inventory.
The inventory lists what you want; skill contents stay in their own repositories.
You do not need to combine those repositories or add a manager manifest to them.

```text
local skills.toml: name + type + repository location
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
Linux/WSL and native Windows are supported in the implementation; native Windows execution has not yet been validated.

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

[skills.report-helper]
type = "git"
repository = "https://github.com/OWNER/RESEARCH-TOOLS.git"
subdir = "skills/report-helper"

[skills.standalone-skill]
type = "git"
repository = "git@github.com:OWNER/STANDALONE-SKILL.git"
```

Replace the example repository locations with repositories you choose.
The table key is the skill's registration name and installed directory name; it does not rewrite the name inside SKILL.md.

| Field | Meaning |
| --- | --- |
| `type` | Required repository type; currently only `git`. |
| `repository` | Required Git URL or absolute path to a local Git repository, including a bare repository. |
| `subdir` | Skill directory inside the repository; defaults to `.` for a root skill. |
| `branch` | Optional branch. Otherwise bootstrap discovers and records the remote's default branch. |
| `root` | Target root name; defaults to `skills`. Its actual path is machine-local. |
| `mode` | `link` by default, or explicit `copy`. |
| `update` | Optional per-skill automatic update policy; see below. |

Subdirectories use literal `/`-separated paths without traversal or shell expansion.
The selected directory must contain a regular SKILL.md tracked by Git.
The manager does not execute installation scripts or validate skill prose/frontmatter as part of installation.
There is one checkout per listed skill, even if two entries refer to the same repository.

## Prepare and install

```bash
aem bootstrap --catalog ~/ai-config/skills.toml
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
```

Default checkout storage is the sibling `machine.toml.checkouts/`, with one child per skill name; state is in `machine.toml.state/`.
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
Explicitly reattach with `aem apply --item NAME --reattach --replace` when wanted.

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
No application-specific hook files, shell profiles, or scheduler registrations are written automatically.
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
