# Agent Environment Manager (AEM)

Install and update AI agent skills and personal instruction bundles from a user-owned TOML catalog, supplied as a local file or delivered through Git.
Skills stay in their own Git repositories; instructions can come from Git or an existing local folder.
Upstream repositories need no AEM manifest.

```text
catalog.toml + machine.toml
             |
         bootstrap: clone or validate sources
             |
           apply
             |
     installed links or explicit skill copies
```

Links point directly to source contents, so an update changes them immediately.
Copies change on apply.
Prepared sources remain usable offline.

- [TOML specification](docs/configuration.md): every field, default, constraint, and path rule.
- [Command reference](docs/commands.md): complete command and option list.
- [Instruction walkthrough](docs/instruction-bundles.md): external and Git bundles on Linux/WSL and Windows.
- [Removed interfaces](docs/removed-interfaces.md): breaking changes and existing-installation precautions.
- [Changelog](CHANGELOG.md): release history and upcoming changes.
- [Contributing](CONTRIBUTING.md): development and validation contracts.

## Versioning and compatibility

AEM uses one package version to communicate compatibility across its commands, catalog syntax, and existing installations.
From 1.0.0 onward, it follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html): incompatible changes require a major release, compatible features a minor release, and compatible fixes a patch release.
During 0.x development, minor releases may break compatibility; patch releases preserve it.
During 0.x only, compatible feature additions may also ship in a patch release; maintainers may choose a minor release based on their scope and significance.
Review migration instructions before upgrading across an incompatible release.

The catalog is the user-authored interface; its integer `version` identifies a format generation, not a separate release version.
In the default workflow, AEM writes machine settings through setup/bootstrap and manages saved state.
Documented manual settings and continued operation of generated configuration and hooks are also covered by the package's compatibility policy.
Users do not need to coordinate separate file-format releases or manually change version markers.
See the [compatibility policy](CONTRIBUTING.md#versioning-and-compatibility) and [existing-installation precautions](docs/removed-interfaces.md).

CLI commands show readable fields and indented lists by default.
For scripts, add the global `--json` option before the command, for example `aem --json status`.
Put global options (`--config`, `--json`) before the command and command-specific options after their command.
Installed startup and instruction callbacks continue to emit their required JSON automatically.

## Install and connect this machine

Requirements: Python 3.11 or later and Git.
Linux/WSL and native Windows are supported in the implementation.
Native Windows tests have covered non-symlink paths; link privileges and real shell/agent hook execution still require platform validation.
Configure Git credentials separately; AEM uses noninteractive authentication and SSH batch mode.

With [uv](https://docs.astral.sh/uv/) installed, run from this checkout:

```bash
python scripts/setup.py --shell bash --agent codex
```

On Windows:

```powershell
py -3 scripts/setup.py --shell powershell --agent codex
```

The installer uses `uv tool install --reinstall` and then `aem setup` to connect startup integrations and link the official `idk-aem` skill for selected agents.
On first interactive installation, select the device automation mode (`policies`, `full`, or `off`), then the AEM release range (`off`, `compatible`, or `breaking`) when automation is enabled.
For unattended installation, supply `--automation full --self-update compatible` to enable the full sequence.
Omission preserves existing settings; a new installation defaults to `policies` with tool updates off.
Reinstallation preserves a saved mode and release repository unless explicitly overridden.
It does not bind a catalog or install user catalog skills/instructions.
Open a new selected shell to use the updated PATH.
Bash, Zsh, PowerShell, and Codex are the built-in integrations.
Repeat `--shell` or `--agent` to add selections; omitted selections remain configured.
The official skill guides AEM operations, including locating and publishing sources; content authoring remains governed by your task and its applicable instructions.
If its link cannot be installed, setup completes the shell/agent connection and reports the skill failure separately; resolve the cause and repeat `aem setup --agent codex` to retry.
It ships with AEM and is linked from the agent skills directory to the installed package, independently of your catalog.
After upgrading AEM with an external package manager, run `aem setup --agent codex` to verify or refresh the link.
To change integrations without reinstalling:

```bash
aem setup --shell zsh
aem setup --remove-shell bash
aem setup --dry-run
```

Setup preserves unrelated profile content, hooks, newline style, and permissions.
It owns an identified block in `.bashrc`, `$ZDOTDIR/.zshrc` (or `~/.zshrc`), or PowerShell's `$PROFILE.CurrentUserAllHosts`.
PowerShell discovery prefers `pwsh`, then `powershell.exe`.
Agent hooks use absolute interpreter and machine paths.
Setup rejects locally edited blocks, duplicate markers, invalid hook JSON, and redirected profiles.
After a partial failure, fix the error and retry the same setup selections.

For a development installation without startup integrations:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/aem --help
```

On Windows use `py -3 -m venv .venv`, then `.\.venv\Scripts\python.exe` and `.\.venv\Scripts\aem.exe`.
Activate the environment or use the executable's full path for the following examples.

## Declare and install content

Save a catalog outside managed checkout storage:

```toml
version = 2

[sources.tools]
type = "git"
repository = "https://github.com/OWNER/TOOLS.git"

[skills.report]
source = "tools"
subdir = "skills/report"

[sources.documents]
type = "external"

[instructions.personal]
source = "documents"
entry = "AGENTS.md"

[instructions.personal.install.entry]
root = "agent"
```

Replace the repository with one containing the selected directory and its `SKILL.md`.
The external folder must contain `AGENTS.md` and any documents it references.
Skills and instructions are independent; omit either section if it is not needed.
Start from [skills](examples/skills.toml), [instructions](examples/instructions.toml), or the [combined catalog](examples/combined-catalog.toml).

```bash
aem bootstrap ~/ai-config/catalog.toml --external documents=~/Synced/agent-documents
aem apply --dry-run
aem apply
aem status
```

Bootstrap binds this catalog, saves device-local paths, and prepares sources.
It never installs targets, pulls existing checkouts, or modifies the catalog.
`apply` installs from prepared sources without fetching.
Adding a catalog declaration registers content; run bootstrap and apply for the new item.
Removing a declaration never deletes its installed target, hook, or checkout.

One machine file binds one catalog.
To use a separate configuration, put `--config /path/machine.toml` before each command.
Bootstrap accepts a positional catalog or `--catalog`, plus `--checkout-root`, repeated `--root NAME=PATH`, and repeated `--external NAME=PATH` bindings.
Omitted bindings are reused on later runs.
The [TOML reference](docs/configuration.md#machine-configuration) describes default locations and storage.

If the catalog lives in Git, supply its repository and relative file path instead of a local file:

```bash
aem bootstrap --catalog-repository git@github.com:OWNER/environment.git --catalog-path catalogs/personal.toml
aem apply --dry-run
aem apply
```

No hand-written machine file is needed.
AEM clones and validates the catalog, records its repository, file path, and branch in `machine.toml`, then prepares its declared content.
Use `--catalog-branch NAME` to select a branch; otherwise AEM records the remote default.
Include any required `--external` bindings just as with a local catalog.
Later `aem bootstrap` calls reuse these settings without pulling the catalog.

Explicit catalog maintenance:

```bash
aem catalog update               # Validate and fast-forward the catalog only.
aem bootstrap                    # Prepare newly declared sources.
aem apply --dry-run
aem apply
aem catalog locate               # Find the catalog checkout for editing.
aem catalog publish --dry-run
aem catalog publish -m "Update catalog"
```

`aem catalog status` inspects the catalog offline.
Publishing includes all nonignored changes in its repository, not just the TOML file.
Content `update`, `sync`, and skill automatic policies never refresh the catalog itself.
Catalog automatic updates are an independent device policy described below.
The catalog has a separate checkout even when it shares a remote repository with content.

Skill links default to `~/.agents/skills`; instruction entries default to the selected Codex home when using agent bindings, or the explicitly declared entry root.
The instruction bundle directory defaults to `<machine-file>.bundles/NAME`.
To copy a skill on one device, add to its machine file:

```toml
[modes]
report = "copy"
```

Copy is never a silent fallback when symlink creation fails.
Windows and WSL should use separate machine configurations, checkouts, and targets.

Instruction apply links the original entry and registers one SessionStart hook invoking `agent-hook NAME --agent codex`.
It preserves unrelated hook groups and reports the required Codex `/hooks` trust review.
AEM does not grant trust or modify Codex `config.toml`.
The callback supplies source-root and entry-path metadata, never document contents or applicability rules.
See the [walkthrough](docs/instruction-bundles.md) for trust, lookup failure, and detach behavior.

## Daily work

```bash
aem bootstrap                    # Prepare newly declared content.
aem update                       # Update sources; links change immediately.
aem apply                        # Install or refresh from local sources.
aem sync                         # Update all, then apply if all updates succeed.
aem status                       # Inspect without network access.
aem status --refresh             # Fetch observations without advancing checkouts.
aem locate personal              # Resolve installed instruction paths.
```

`bootstrap --item NAME` and `update NAME` select skill or instruction source names.
`apply --item report` selects a skill; `apply --item personal:entry` includes the entry's bundle and hook.
`sync --item` filters only installation, while its update phase still visits all sources.
See [Commands](docs/commands.md) for all arguments, previews, callbacks, and exit codes.

## Edit and publish

Find the prepared source with `locate --source`, edit it directly or through its installed link, then publish by catalog skill or instruction bundle name:

```bash
aem locate report --source                  # Find the prepared source to edit.
aem locate report --source --cd             # Enter it with the registered shell integration.
aem publish report --dry-run                # Review local changes and outgoing commits.
aem publish report -m "Clarify guidance"    # Commit checkout changes and push.
aem publish report                         # Push changes already committed.
```

Pass multiple names to publish several sources; shared checkouts are grouped and processed once, with all connected skills and instructions listed.
Selection covers the whole repository, including files outside declared skills.
The optional dry run is offline; publication fetches first and leaves behind/diverged histories for explicit reconciliation.
A failed push retains the local commit for retry.
For copy installations, edit the checkout and apply after committing; installed-copy edits are not collected automatically.
External-folder synchronization stays with its existing service.
See [publish](docs/commands.md#publish) for commit scope, Git settings, and failure behavior.

## Device automation modes

```bash
python scripts/setup.py --shell bash --agent codex --automation full --self-update compatible
aem setup --automation full --automation-trigger shell-start --automation-trigger agent-start \
  --automation-interval 3600 --automation-timeout 30
aem automation --trigger agent-start --dry-run
aem setup --automation policies
aem setup --automation off
```

`policies` is the backward-compatible default: tool, catalog, and skill policies run as before.
`off` disables startup and event-driven automatic work; explicit update, sync, catalog update, and self update commands remain available.
`full` queues one sequential run after the requesting process exits:

1. Update AEM within its saved release range, or skip this stage when tool updates are off.
1. Invoke the installed AEM afresh and validate/fast-forward the Git catalog; local or unbound catalogs skip delivery.
1. Prepare and update eligible skill/instruction sources, then apply after all selected delivery succeeds.

Full mode uses one shared trigger list and attempt interval, including failed attempts.
Its defaults are shell/agent startup, 3600 seconds between attempts, and 30 seconds per content/catalog Git phase.
It replaces individual automatic triggers, intervals, and check/sync actions for this run.
Skills without an explicit trigger policy participate; explicit `manual` exclusions resolve through catalog defaults, named policy, and skill fields.
Detached skills and detached instruction groups remain excluded.
Shared checkout updates can still change linked consumers excluded from installation, including manual skills; this is the existing shared-source contract.
It never adopts conflicts, replaces user edits, reattaches detached content, removes undeclared targets, or grants agent hook trust.
New valid catalog declarations can be prepared and installed in full mode.
A failed stage stops later stages; successful earlier work remains and normal per-target recovery rules apply.

The installer must register an external Python, uv, and the installation directories before full mode can be enabled, even when tool updates are off.
No OS scheduler or daemon is installed: use startup integrations or `aem automation --trigger interval` from an external scheduler.
`aem auto` and `aem catalog auto` require `policies` mode; use the unified automation command in full mode to avoid duplicate event paths.
Policy-only setup edits require no profile changes; omitted fields retain saved values and supplied trigger lists replace the saved list.
Inspect the eventual sequence and stage results under `automation` in `aem status`.
Queued work is not yet completed; changed mode/runtime settings cancel pending work.
Registered commands may report lock contention while the worker or continuation holds the installation/configuration locks.
Native Windows replacement and real uv reinstallation retain their existing validation limits.

## Update AEM itself

```bash
python scripts/setup.py --shell bash --agent codex --self-update compatible
aem setup --self-update off       # Change the saved automatic mode.
aem self status                  # Installed version, mode, and last attempt.
aem self update --dry-run         # Offline preview.
aem self update                  # Queue an explicit compatible release update.
aem self update --mode breaking  # Permit incompatible releases for this attempt.
```

`compatible` permits newer releases in the same major version; during `0.x`, it permits only patches in the same minor version.
`breaking` permits any newer final release, including incompatible changes; review migration instructions before enabling it.
Prereleases and untagged commits are excluded.
AEM reads `vX.Y.Z` tags from its upstream Git repository, verifies the matching package metadata, and installs the selected commit through uv.
Use the installer's `--update-repository URL` to select another release repository.
Development checkout edits are not published or installed by this path.

In `policies` mode with tool updates enabled, the existing startup callback queues at most one attempt per day across shell and agent events; failures are throttled too.
It works without a bound content catalog.
The worker waits for the requesting AEM process to exit, then uses the installer's external Python rather than the environment being replaced.
The saved external Python and uv executables must remain available; rerun the installer if they move.
A queued result means the attempt has been scheduled, not completed; use `aem self status` for the eventual result.
Explicit updates bypass the daily throttle and work even with automatic updates off.
Content updates, catalog delivery, instruction location callbacks, and `auto` do not update AEM itself.
No daemon or OS scheduler is installed.

Self-updates coordinate registered AEM commands sharing the same uv tools directory.
Commands can report lock contention during replacement; startup remains fail-open.
Other package-manager processes and external editors are not covered by these locks.
A failed uv replacement is reported without a rollback guarantee; rerun `scripts/setup.py` to repair the installation if AEM cannot start.
Native Windows worker/replacement and actual agent hook continuity require platform validation.

## Automatic catalog updates

Choose automatic catalog events during Git registration:

```bash
aem bootstrap --catalog-repository URL --catalog-path catalogs/personal.toml \
  --catalog-trigger shell-start --catalog-trigger agent-start
```

Change the saved policy later:

```bash
aem setup --catalog-trigger agent-start --catalog-interval 3600 --catalog-timeout 5
aem setup --catalog-trigger manual  # Disable automatic catalog updates.
aem setup --catalog-trigger interval --dry-run
```

These options write device-local settings; no manual `machine.toml` edit is required.
Repeated trigger options replace the complete event list; omitted options retain their saved values.
Policy-only setup needs no executable or startup selections and leaves existing profiles alone.
The underlying `catalog_update` table remains documented in [Configuration](docs/configuration.md#catalog-automatic-update-settings).

The default trigger is `manual`; automatic updates require a Git catalog binding.
In `policies` mode, setup's existing startup callback updates a due catalog first, then resolves skill policies from the validated new catalog.
If that catalog attempt fails, the callback skips skill updates for the event and still allows startup to continue.
External callers can use `aem catalog auto --trigger interval`; add `--dry-run` for an offline preview.
`aem auto` continues to operate on skills only.

Catalog automation shares one attempt clock across events, throttling failures too.
It uses the same validation and fast-forward guards as `aem catalog update`, preserving local edits and the previous catalog on validation failure.
The catalog update itself does not bootstrap or apply content; startup's subsequent skill policies retain their existing scope and require prepared sources.
Explicit catalog updates bypass the automatic interval.
See `aem catalog status` or `aem status` for the last automatic result.

## Automatic updates

In `policies` mode, automatic skill updates default to disabled (`trigger = []`).
Opt in through the catalog:

```toml
[updates.defaults]
trigger = ["shell-start", "agent-start"]
action = "sync"
min_interval = 600
timeout = 5

[skills.report.update]
trigger = []
```

Policies apply only to skills and do not install integrations.
Setup connects interactive shell and agent startup to a fail-open `startup` callback.
Without setup, external callers can invoke `aem auto --trigger shell-start`, `agent-start`, or `interval`.
For `interval`, arrange an OS scheduler; AEM does not run a daemon.
Preview due work with `aem auto --trigger agent-start --dry-run`.

Each skill has one attempt clock across events; failed attempts are throttled too.
Automatic sync handles skills independently and preserves conflicts and detached items.
Explicit `update`, `apply`, `sync`, and `status --refresh` ignore automatic policies.
Agent startup shows a brief message for completed updates or installations; full outcomes and failures remain in status.
Instruction location hooks installed by apply do not trigger updates.
See [policy fields and precedence](docs/configuration.md#update-policies).

## Conflicts, detach, and recovery

AEM refuses unmanaged targets and locally modified copies unless explicitly authorized:

```bash
aem apply --item report --adopt     # Record matching existing content.
aem apply --item report --replace   # Back up and replace a conflict.
aem detach report                  # Keep contents and release ownership.
aem detach personal:bundle personal:entry
```

Backups are retained as `<target>.aem-backup-<id>`.
A directory item owns its entire subtree; local additions count as modifications.
Detach materializes links, preserves copies, and records a tombstone to prevent automatic reinstall.
After moving the preserved target aside, explicitly reattach with `aem apply --item report --reattach`.
Detaching instructions retains hook configuration and locator records for the preserved copy; disable the retained hook in Codex if no longer wanted.

Apply preflights selected items and journals each replacement before renaming targets.
Transactions are per target: earlier successful items can remain installed if a later item fails.
After an interruption, inspect `status` and run `recover`.
Recovery refuses to overwrite later user edits; keep state and backups.
Never delete state to bypass ownership conflicts or unsupported state versions.
Even when old or unknown machine fields block installation, `detach`, `recover`, `locate`, and removal-only `setup --remove-*` use saved ownership independently.
Offline `status` falls back to saved IDs and target observations.
These maintenance paths support state versions 1 and 2, preserving the original version and unknown fields without automatic migration.

Git updates never stash, reset, rebase, commit, or push automatically.
They reject tracked changes, nonignored untracked files, unfinished operations, local-ahead/divergent history, wrong branches, and checkout identity changes.
Git-ignored regular files such as `__pycache__` may remain in managed checkouts; an incoming revision that would overwrite them is refused without deleting the local files.
Ignored files remain visible through directory links and are included in directory copies and detach, which preserve the complete payload except root Git metadata.
Changes made inside an installed copy, including newly generated caches, still count as local modifications and require explicit replacement before reinstallation.
Updates also guard active link sources and instruction entries against removal or unsupported type changes, even after declarations disappear.
Nested payload symlinks/junctions, special files, and submodules are unsupported.
Portable copy metadata is preserved; platform-specific ACLs, alternate streams, and power-loss atomicity are outside the guarantee.

To remove integrations, detach managed agent content first, then use `aem setup --remove-agent codex` and the appropriate `--remove-shell` options.
Agent removal also attempts to remove the unchanged official skill link; failures are reported separately, and changed links, edited official sources, or substituted copies are preserved with their paths reported.
Disable any retained detached instruction hooks before uninstalling AEM with `uv tool uninstall agent-env-man`.

## License

[MIT License](LICENSE.txt).

## AI disclosure

OpenAI Codex assisted with design, implementation, documentation, and automated tests.
