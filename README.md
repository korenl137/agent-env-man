# agent-env-man

Install and update AI agent skills and personal instruction bundles from a user-owned local TOML catalog.
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
Review migration instructions before upgrading across an incompatible release.

The catalog is the user-authored interface; its integer `version` identifies a format generation, not a separate release version.
In the default workflow, AEM writes machine settings through setup/bootstrap and manages saved state.
Documented manual settings and continued operation of generated configuration and hooks are also covered by the package's compatibility policy.
Users do not need to coordinate separate file-format releases or manually change version markers.
See the [compatibility policy](CONTRIBUTING.md#versioning-and-compatibility) and [existing-installation precautions](docs/removed-interfaces.md).

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

The installer uses `uv tool install --reinstall` and then `aem setup` to connect startup integrations.
It does not bind a catalog or install skills/instructions.
Open a new selected shell to use the updated PATH.
Bash, Zsh, PowerShell, and Codex are the built-in integrations.
Repeat `--shell` or `--agent` to add selections; omitted selections remain configured.
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
version = 1

[repositories.tools]
repository = "https://github.com/OWNER/TOOLS.git"

[skills.report]
repo = "tools"
subdir = "skills/report"

[externals.documents]

[instructions.personal]
external = "documents"
entry = "AGENTS.md"
entry_root = "agent"
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

## Automatic updates

Automatic updates default to disabled (`trigger = "manual"`).
Opt in through the catalog:

```toml
[updates.defaults]
trigger = ["shell-start", "agent-start"]
action = "sync"
min_interval = 600
timeout = 5

[skills.report.update]
trigger = "manual"
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
They reject dirty/untracked/ignored content, unfinished operations, local-ahead/divergent history, wrong branches, and checkout identity changes.
Updates also guard active link sources and instruction entries against removal or unsupported type changes, even after declarations disappear.
Nested payload symlinks/junctions, special files, and submodules are unsupported.
Portable copy metadata is preserved; platform-specific ACLs, alternate streams, and power-loss atomicity are outside the guarantee.

To remove integrations, detach managed agent content first, then use `aem setup --remove-agent codex` and the appropriate `--remove-shell` options.
Disable any retained detached instruction hooks before uninstalling AEM with `uv tool uninstall agent-env-man`.

## License

[MIT License](LICENSE.txt).

## AI disclosure

OpenAI Codex assisted with design, implementation, documentation, and automated tests.
