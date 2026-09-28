# Command reference

```text
aem [--config PATH] COMMAND [ARGS]
```

`--config` is a global option and must precede the command.
Every command accepts `-h` or `--help`.
Outputs are JSON; ordinary operation errors use stderr and exit `1`, argument parsing errors exit `2`.
Successful operations exit `0`; status also exits `0` when its report contains conflicts or unavailable sources.
Callbacks have the exceptions described below.
Commands lock one configuration, not all AEM installations or external editors.
Read-only commands and dry runs may create the lock directory/file; `setup --dry-run` does not.

| Command | Purpose | Network |
| --- | --- | --- |
| `setup` | Connect or remove machine startup integrations. | None. |
| `bootstrap` | Bind a catalog and prepare sources. | Clone missing Git repositories. |
| `update` | Fetch and fast-forward prepared sources. | Yes for Git. |
| `apply` | Install from local prepared sources. | None. |
| `sync` | Update all sources, then apply if every update succeeds. | Yes for Git. |
| `auto` | Run due per-skill policies for an event. | Due skills only; none in dry run. |
| `status` | Inspect sources and saved installations. | Only with `--refresh`. |
| `detach` | Preserve contents and release ownership. | None. |
| `locate` | Resolve saved instruction paths. | None. |
| `recover` | Recover an interrupted target replacement. | None. |
| `startup` | Fail-open automatic-update callback. | According to due policies. |
| `agent-hook` | Emit instruction locations for the selected agent. | None. |

`TIMEOUT` below defaults to `30` seconds and must be positive and finite.
It bounds each Git phase, not the entire command or filesystem copying.
`AGENT` is currently `codex`.
`EVENT` is `shell-start`, `agent-start`, or `interval`.

## setup

```text
aem setup [--shell SHELL ...] [--agent AGENT ...]
          [--remove-shell NAME ...] [--remove-agent NAME ...]
          [--executable PATH] [--dry-run]
```

Shell choices are `bash`, `zsh`, and `powershell`.
Selections accumulate; omitted selections remain saved, and repeated setup avoids duplicate blocks/groups.
Initial setup requires at least one shell or agent selection.
Adding and removing the same integration in one call is invalid.
`--executable` overrides the saved absolute executable path, otherwise it defaults beside the running Python interpreter.
Setup edits startup integrations and saves machine selections; it does not bootstrap or apply content.
Removing an agent requires first detaching its managed content.
Dry run writes no files, including lock files.
When only `--remove-shell` / `--remove-agent` selections are supplied, setup uses saved ownership instead of validating installation declarations.
Removal accepts retired integration names and old state versions 1/2; unknown machine fields and unselected records are preserved.
It removes only the selected saved blocks/groups and corresponding selections, without rebuilding other integrations.
A supplied `--executable` is ignored on removal-only calls; no executable or current agent profile is needed.
Locally edited selected blocks/groups, redirected targets, malformed records, and pending recovery still stop removal.
Calls that also add a shell or agent retain full installation validation.
The repository installer `python scripts/setup.py` installs AEM using uv and delegates integration to this command; it is not an additional AEM subcommand.

## bootstrap

```text
aem bootstrap [CATALOG | --catalog PATH] [--checkout-root PATH]
              [--root NAME=PATH ...] [--external NAME=PATH ...]
              [--item NAME ...] [--timeout TIMEOUT]
```

Omit the catalog argument to reuse the saved binding.
A positional catalog and `--catalog` cannot both be supplied.
Catalog, checkout-root, and external CLI paths resolve relative to the working directory and are saved as absolute paths.
Root paths must be absolute or begin with `~/`.
Repeated `--external` binds declared external names; duplicate names in one invocation are invalid, and omitted saved bindings remain.
`--item` selects catalog skill or instruction names for preparation, not ownership IDs or repository names.
No selection prepares all declared sources.
Missing repositories are cloned and validated; existing checkouts are validated without pulling or resetting.
A failed download leaves the machine binding saved so bootstrap can be retried.
Declaration and ownership preflight failures do not save a new binding or contact repositories.

## update

```text
aem update [NAME ...] [--timeout TIMEOUT]
```

Select skill or instruction source names, or omit names for all sources.
Shared checkouts advance once and guard every active link, including orphaned declarations.
Links change immediately; copies are refreshed by apply.
External sources only receive an existence check (`external-no-fetch`).
Dirty, divergent, local-ahead, detached, misidentified, or unsupported incoming checkouts are refused.

## apply

```text
aem apply [--agent AGENT] [--item ID ...] [--timeout TIMEOUT]
          [--adopt | --replace] [--reattach] [--dry-run]
```

Omit items to install all declared, non-detached items.
Skill IDs are skill names; instruction IDs are `NAME:bundle`, `NAME:entry`, and `NAME:hook`.
Selecting an entry or hook also selects its bundle and the other instruction items.
Selecting only a bundle installs its directory link alone.
`--agent` filters installation destinations.

`--adopt` records matching existing content; `--replace` backs up and replaces a conflict.
Both require explicit `--item` selections, as does `--reattach` for detached items.
An implicitly selected bundle does not gain replacement permission.
Dry run validates and shows planned actions without changing targets or ownership.
Prepared checkouts must be clean even though this command does not fetch.

## sync

```text
aem sync [--agent AGENT] [--item ID ...] [--timeout TIMEOUT]
```

Updates all sources, then applies only if every update succeeds.
`--item` and `--agent` filter the apply phase only; they do not narrow the update phase.
This command has no throttle and ignores automatic policy clocks.
For throttled event-based work, configure policies and use `auto`.

## auto

```text
aem auto --trigger EVENT [--item NAME ...] [--dry-run]
```

Select catalog skills only; omitted names consider all skill policies.
Due skills require prepared checkouts and run independently.
One failure does not block another skill, but an unresolved recovery journal stops further work.
Attempts are persisted before network access and throttle failures as well as successes.
Dry run shows effective policies and due work without fetching or saving attempts.
Automatic execution never adopts conflicts, replaces local edits, or reattaches detached skills.
It exits `1` if any attempted skill fails, otherwise `0`.

## status

```text
aem status [--agent AGENT] [--refresh] [--timeout TIMEOUT]
```

Reports local checkout observations, last observed remote state, ownership, and startup outcomes.
`--refresh` fetches remote references without moving checkout branches or installing content.
`--agent` filters installation observations, not source fetching.
Saved installed targets are still inspected if the catalog or source is unavailable.
Deleting a declaration leaves its target and ownership intact, reported as orphaned.
If strict machine/state validation fails, offline status returns `saved_only: true`, `state_version`, the validation error, and saved item IDs with filesystem observations.
This fallback does not interpret obsolete modes or claim that saved items match current declarations.
It never fetches; `--refresh` does not use the fallback.

## detach

```text
aem detach ID [ID ...] [--agent AGENT] [--dry-run]
```

Materializes links as regular copies, preserves copy contents, and records detached tombstones.
Detaching an instruction entry also releases its hook ownership while retaining the hook configuration.
For independent instruction copies, detach both `NAME:bundle` and `NAME:entry`.
Detach does not restore pre-installation content or disable retained hooks.
It refuses missing or unreadable content that cannot be preserved.
`--agent` cannot detach only one consumer of a shared target; omit it to release all consumers.
Dry run leaves targets and ownership unchanged.
Detach does not require valid installation fields or source declarations; it accepts state versions 1 and 2 without changing the version.
It materializes an actual symbolic link regardless of an obsolete saved mode, and checks regular contents are readable before releasing ownership.
Unknown fields and unselected records are preserved; no legacy config-merge parser is needed.

## locate

```text
aem locate NAME [--agent AGENT]
```

The agent defaults to `codex`.
Returns `root`, `entry`, `installed_root`, and `detached` for an installed instruction bundle.
Uses saved state without validating installation fields, loading the catalog, fetching, or changing ownership.
Versions 1 and 2 are accepted, but the selected bundle still needs a usable saved locator record.
Missing or redirected entries and replaced active links are errors.
Detached bundles resolve to preserved local contents.

## recover

```text
aem recover
```

Restores the previous target from a pending replacement journal when observations still match.
Refuses to overwrite later user edits; retain the target, backup, and state for manual reconciliation.
Transactions are per target, so recovery does not undo earlier successful targets.
Recovery accepts the common journal format in state versions 1 and 2, validates paths and observations, and preserves the original state version and unrelated fields.
An unknown version or incomplete journal is rejected rather than inferred.

## startup

```text
aem startup --trigger EVENT [--agent AGENT]
```

Callback registered by setup; runs the same automatic policy engine as `auto`.
No bound catalog means no update work.
Operational failures are recorded in status when possible; failures before state access go to stderr.
It exits `0` on handled operational failures so startup can continue; CLI usage errors still exit `2`.
With an agent, completed changes can return an agent-specific briefing; shell callbacks return `{}`.
This command does not install integrations.

## agent-hook

```text
aem agent-hook NAME --agent AGENT
```

Callback registered by instruction apply; emits only instruction reading locations and relative-reference guidance.
It does not update sources or inject document contents.
Unrelated machine fields and obsolete unselected state modes do not block lookup; the selected saved entry and bundle must still pass locator checks.
It waits up to five seconds for the configuration lock within the installed ten-second hook timeout.
For Codex, handled lookup errors return a structured stop response with exit `0`; usage errors still exit `2`.
Trust remains an agent-side decision; AEM never grants it.

Old source registration, `codex-hook`, and throttled `sync` syntax are removed; see [Removed interfaces](removed-interfaces.md).
