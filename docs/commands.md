# Command reference

```text
aem [--config PATH] [--json] COMMAND [ARGS]
```

`--config` and `--json` are global options and must precede the command.
Command-specific options follow their command, for example `aem --json catalog publish --dry-run`.
Options require their full spelling; abbreviated long options are rejected.
Every command accepts `-h` or `--help`.
Ordinary commands print human-readable fields and indented lists by default, including when stdout is redirected.
Use `--json` for the existing JSON report schema, for example `aem --json status` or `aem --json catalog status`.
Scripts that parse stdout must add `--json`; startup and agent-hook callbacks retain JSON automatically.
Ordinary operation errors use stderr and exit `1`, argument parsing errors exit `2`.
Invalid numeric CLI durations (non-finite values, nonpositive timeouts, or negative intervals) are argument errors and exit `2` before configuration reads or filesystem effects.
Help exits `0`; invoking a command group without a required subcommand shows usage/help and exits `2`.
Successful operations exit `0`; status also exits `0` when its report contains conflicts or unavailable sources.
Callbacks have the exceptions described below.
Documented commands, behavior, exit codes, and JSON fields are covered by the package's [compatibility policy](../CONTRIBUTING.md#versioning-and-compatibility).
JSON consumers must ignore unknown object fields; field additions may appear in compatible feature releases.
Enum values are closed unless their interface explicitly documents unknown-value handling.
JSON whitespace, object key order, and human-readable diagnostic wording are not stable interfaces.
Commands lock one configuration; installations registered for self-updates also share a lock for their uv tools directory.
External editors and other package-manager processes do not participate in these locks.
Read-only commands and dry runs may create the lock directory/file; `setup --dry-run`, `self update --dry-run`, and `automation --dry-run` do not.

| Command | Purpose | Network |
| --- | --- | --- |
| `setup` | Connect or remove machine startup integrations. | None. |
| `self` | Inspect or queue updates of AEM itself. | Status and dry run are offline; queued workers fetch releases and install through uv. |
| `bootstrap` | Bind a catalog and prepare sources. | Clone missing Git repositories. |
| `catalog` | Inspect, update, or publish the catalog itself. | Update/publish only; publication dry run is offline. |
| `update` | Fetch and fast-forward prepared sources. | Yes for Git. |
| `publish` | Commit local changes and push selected checkouts. | Fetch and push; none in dry run. |
| `apply` | Install from local prepared sources. | None. |
| `sync` | Update all sources, then apply if every update succeeds. | Yes for Git. |
| `auto` | Run due per-skill policies for an event. | Due skills only; none in dry run. |
| `status` | Inspect sources and saved installations. | Only with `--refresh`. |
| `detach` | Preserve contents and release ownership. | None. |
| `locate` | Find installed content or prepared editing sources. | None. |
| `recover` | Recover an interrupted target replacement. | None. |
| `automation` | Run or preview device automation. | According to selected mode; no network in dry run. |
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
          [--executable PATH] [--self-update MODE] [--dry-run]
          [--update-repository URL] [--update-python PATH] [--update-uv PATH]
          [--update-tool-dir PATH] [--update-bin-dir PATH]
          [--catalog-trigger TRIGGER ...] [--catalog-interval SECONDS]
          [--catalog-timeout SECONDS]
          [--automation off|policies|full] [--automation-trigger EVENT ...]
          [--automation-interval SECONDS] [--automation-timeout SECONDS]
```

Shell choices are `bash`, `zsh`, and `powershell`.
Selections accumulate; omitted selections remain saved, and repeated setup avoids duplicate blocks/groups.
Initial integration setup requires at least one shell or agent selection.
A call supplying only catalog/device automation policy options (and optionally `--dry-run`) can save policy without registering integrations or requiring an executable.
Adding and removing the same integration in one call is invalid.
`--executable` overrides the saved absolute executable path, otherwise it defaults beside the running Python interpreter.
Setup edits startup integrations and saves machine selections; it does not bootstrap or apply content.
`--self-update` saves `off`, `compatible`, or `breaking`; omission preserves the saved mode.
The `--update-*` options register the release source and external installer runtime described in [Configuration](configuration.md#aem-self-update-settings).
Enabling updates requires runtime registration; the repository installer supplies those paths.
Changing self-update settings does not immediately update the package.
`--catalog-trigger` sets `manual` or a supported event; repeat it to replace the complete saved trigger list.
`--catalog-interval` sets the finite nonnegative attempt interval, and `--catalog-timeout` sets the finite positive per-Git-phase timeout.
Omitted policy options preserve their saved fields; configuring events requires a bound Git catalog.
Policy-only edits validate machine settings and use the configuration journal without reading or rewriting profiles, even when those profiles contain local edits.
They do not fetch, run automatic updates, or register startup integrations; the result includes the effective `catalog_update` policy.
Removing an agent requires first detaching its managed content.
Dry run writes no files, including lock files.
When only `--remove-shell` / `--remove-agent` selections are supplied, setup uses saved ownership instead of validating installation declarations.
Removal accepts retired integration names and old state versions 1/2; unknown machine fields and unselected records are preserved.
It removes only the selected saved blocks/groups and corresponding selections, without rebuilding other integrations.
A supplied `--executable` is ignored on removal-only calls; no executable or current agent profile is needed.
Locally edited selected blocks/groups, redirected targets, malformed records, and pending recovery still stop removal.
Calls that also add a shell/agent or change self-update/catalog policy settings retain full installation validation.
Device automation options save the [mode and full-run schedule](configuration.md#device-automation-settings), preserving omitted fields and replacing supplied trigger lists.
Changing these settings alone does not execute a run or rewrite profiles.
Initial interactive installation offers the device mode before tool release permission; unattended omission defaults to the existing `policies` behavior.
The repository installer `python scripts/setup.py` installs AEM using uv and delegates integration to this command; it is not an additional AEM subcommand.

## self

```text
aem self status
aem self update [--mode compatible|breaking] [--dry-run]
```

`status` is offline and reports `version`, `mode`, `repository`, `runtime_registered`, and `last_attempt`.
It works without a catalog, including when content declarations are malformed.
`update` queues an external worker and exits `0` when queued; asynchronous failure is reported by subsequent status, not the launch command's exit code.
It uses the saved enabled mode, or `compatible` if automatic updates are off.
`--mode` overrides only this attempt; explicit updates ignore the automatic daily interval.
Dry run requires a registered runtime but performs no remote access, launches no worker, and writes no files.
Pending recovery blocks an update.

The worker waits for the requesting AEM process to exit, locks the registered installation and configuration, then rechecks its request token, saved settings, and recovery state.
A superseded request does no work; changed settings or pending recovery cancel it.
The actual uv-installed version is checked under the installation lock so another configuration's completed update cannot cause a downgrade.
Only newer final `vX.Y.Z` tags qualify; annotated tags resolve to their commits.
The selected commit must contain `project.name = "agent-env-man"` and the matching release version in `pyproject.toml`.
Installation pins that commit through `uv tool install --reinstall`; neither the development checkout nor managed content is changed.
Git authentication is noninteractive.
Each Git/uv subprocess and worker lock wait is bounded to 300 seconds.
Package-manager rollback and coordination with external installers are not guaranteed.
If an installation is damaged, rerun the repository installer.

A queued report contains `status`, `time` (Unix seconds), `token`, and `mode`.
Dry run returns `status = "planned"`, `mode`, and `network = false`.
The initially empty `last_attempt` subsequently contains those queued fields and can become `up-to-date`, `updated`, `failed`, or `cancelled`.
Completed results include `finished` (Unix seconds); an updated result also includes `version` and `revision`, failures include `error`, and cancellations include `reason`.
An interrupted worker can leave a queued result; explicit update queues a fresh attempt immediately.
During startup, disabled/throttled work is reported in the saved startup outcome as `disabled`/`throttled` and does not replace the last attempt.

## bootstrap

```text
aem bootstrap [CATALOG | --catalog PATH] [--checkout-root PATH]
              [--catalog-repository URL --catalog-path RELATIVE_PATH [--catalog-branch BRANCH]]
              [--root NAME=PATH ...] [--external NAME=PATH ...]
              [--item NAME ...] [--timeout TIMEOUT]
              [--catalog-trigger TRIGGER ...] [--catalog-interval SECONDS]
              [--catalog-timeout SECONDS]
```

Omit the catalog argument to reuse the saved binding.
A positional catalog and `--catalog` cannot both be supplied.
Bootstrap accepts the same catalog policy options as setup, allowing initial Git registration and automatic policy selection in one call.
Omitted options retain saved policy fields, and repeated triggers replace the saved list.
Policy validation precedes cloning or configuration writes; enabling events for a local catalog is rejected.
`--catalog-timeout` controls future automatic updates; `--timeout` controls the current bootstrap delivery.
Git catalog registration requires `--catalog-repository` and `--catalog-path` together, optionally with `--catalog-branch`; these cannot be combined with a local catalog argument.
`--catalog-path` is relative to the repository root, not the working directory, and must identify a tracked regular TOML file.
Repository syntax matches catalog repository declarations: a URL, SSH location, or absolute local repository path.
The default branch is discovered and written to the machine binding; repeating registration for the same repository without `--catalog-branch` retains the recorded branch.
Catalog, checkout-root, and external CLI paths resolve relative to the working directory and are saved as absolute paths.
Root paths must be absolute or begin with `~/`.
Repeated `--external` binds declared external names; duplicate names in one invocation are invalid, and omitted saved bindings remain.
`--item` selects catalog skill or instruction names for preparation, not ownership IDs or repository names.
No selection prepares all declared sources.
Missing repositories are cloned and validated; existing checkouts are validated without pulling or resetting.
A failed content download leaves the machine binding saved so bootstrap can be retried.
For a local catalog, declaration and ownership preflight failures do not save a new binding or contact repositories.
For a missing Git catalog, bootstrap must clone the catalog into a temporary directory before validating its declarations and current ownership.
It publishes that checkout and saves the binding only after preflight succeeds, then prepares content repositories.
Failed catalog download or validation preserves the previous binding and leaves no new catalog checkout; fix the input or remote and repeat the registration command.
An interrupted machine-file save may leave a validated checkout that the same registration can reuse.
Existing machine settings and omitted external/root bindings are preserved.

The JSON result retains `skills`, `config`, and `next`.
For Git bindings it also includes `catalog`, with `status` (`cloned` or `already-prepared`), absolute `checkout` and `entry` paths, `repository`, resolved `branch`, and `revision`.

## catalog

```text
aem catalog status [--timeout TIMEOUT]
aem catalog locate [--timeout TIMEOUT]
aem catalog update [--timeout TIMEOUT]
aem catalog auto --trigger EVENT [--dry-run]
aem catalog publish [-m MESSAGE | --message MESSAGE] [--dry-run] [--timeout TIMEOUT]
```

These commands select the bound catalog, independently of the skill/instruction namespace.
They never install content or run content automatic policies.
`status` and `locate` are offline and do not change saved state; their Git subprocesses still respect `--timeout`.
`status` reports the entry, checkout, repository, `status` (`ready`, `unavailable`, or `unbound`), and `automation` (the last automatic attempt, or an empty object).
For Git catalogs it also reports the branch, current revision, local changes, tracked diff, outgoing commits, and remote relation at the last fetch, using the same fields as publication inspection.
Catalog reading/inspection failures appear as `error` with status `unavailable` and exit 0; machine/state loading failures still exit 1.
`locate` returns absolute `entry`, `checkout`, and `repository`; the latter two are null for a local catalog.
Locate validates Git identity and the tracked file but does not parse its TOML or require cleanliness, so it can locate a malformed file for repair.

`update` requires a Git binding and a clean checkout on the recorded branch with the expected origin.
It fetches that branch, validates the incoming tracked UTF-8 TOML, declarations, machine bindings, target paths, and existing ownership, then fast-forwards only after all checks pass.
Dirty, local-ahead, diverged, misidentified, detached, or unfinished checkouts are refused without reset or merge reconciliation.
Validation failures leave the previous HEAD and working catalog intact, although fetched references and observations may change.
No newly declared content is cloned or installed by this command.
Use `bootstrap`, then `apply --dry-run` / `apply`, after adding declarations.
Removed declarations leave existing installations and ownership intact; path/mode changes for owned items require detach first.
New required external paths must be bound in the machine file before the catalog update can pass validation.

`publish` uses the [content publication rules](#publish), but selects the whole catalog repository.
The working catalog must pass declaration and ownership validation before publication.
Dry run reports the checkout, entry, repository, branch, changed files, tracked diff, outgoing commits, and last-fetched relation without fetching, staging, committing, pushing, or recording attempts.
With a message it commits all nonignored changes, including files outside the catalog path; without a message it pushes existing commits from a clean worktree.
Fetch precedes staging, behind/diverged histories are refused, and only the registered branch is pushed without force.
A failed push retains the local commit so publication can be retried without a message.
Publication never applies declarations or collects installed-copy edits.

Update and publish return one JSON object with `checkout`, `entry`, `repository`, `branch`, and `status` (`updated`, `planned` for dry run, `published`, or `failed`).
Operation failures include `error` and exit 1; binding/precondition errors may use stderr instead.
Update includes `previous_revision`, `observed_revision`, and `last_fetch` once fetched, and `revision` / `last_update` after success.
Publish uses the inspection/result fields described above and adds `created_commit` when it commits, and `revision`, `observed_revision`, `last_fetch`, and `last_publish` after successful publication.
Fetch/publication observations are saved separately from content ownership and automatic attempt clocks.
Local catalog bindings reject update and publish; manage their transport yourself or register a Git catalog.

`auto` runs the machine's [catalog policy](configuration.md#catalog-automatic-update-settings) for the supplied event.
It shares update's validation and fast-forward behavior and does not prepare or install content.
Its JSON object contains the effective `policy` and `status`: `not-triggered`, `throttled`, `planned` (dry run), `updated`, or `failed`.
An executed update includes its ordinary result as `outcome`; failures before that result exists include `error`.
Failed automatic operations exit 1; skipped, planned, and successful work exit 0.
Dry run does not fetch or record an attempt, although ordinary command locks may be created.
Pending recovery blocks due work.

`automation` contains `binding` (`repository`, `branch`, `entry`), `last_attempt` (Unix seconds), `trigger`, and `status` (`running`, `updated`, or `failed`).
Successful attempts also include `last_success`; failed attempts include `error`.
The same saved record appears as `catalog_automation` in ordinary status, separately from skill clocks and catalog delivery observations.

Content `update`, `sync`, `auto`, and `status --refresh` never fetch or advance the catalog repository.
Bootstrap validates an existing catalog checkout without pulling it.

## update

```text
aem update [NAME ...] [--timeout TIMEOUT]
```

Select skill or instruction source names, or omit names for all sources.
Shared checkouts advance once and guard every active link, including orphaned declarations.
Links change immediately; copies are refreshed by apply.
External sources only receive an existence check (`external-no-fetch`).
Dirty, divergent, local-ahead, detached, misidentified, or unsupported incoming checkouts are refused.

## publish

```text
aem publish NAME [NAME ...] [-m MESSAGE | --message MESSAGE]
            [--dry-run] [--timeout TIMEOUT]
```

Edit the prepared checkout directly, or edit through an installed link pointing to it.
Select catalog skill or instruction bundle names, not ownership IDs or repository aliases:

```bash
aem publish report personal --dry-run
aem publish report personal -m "Clarify report and instruction guidance"
```

The optional dry run is offline and shows checkout paths, every inventory member sharing each checkout, changed files, the tracked diff against HEAD, and outgoing commit IDs/subjects relative to the last fetched remote reference.
Untracked files appear in the changed-file listing; their contents are not included in the diff.
Review full existing commit patches with Git in the reported checkout when needed.
Dry run does not stage, commit, push, fetch, or update ownership/source records.
Its remote comparison can be stale; actual publication fetches before staging.

Selection chooses whole repositories, not file scopes.
Each shared checkout is processed once, even if several selected skills or bundles reference it.
With `-m`, all nonignored changes in that checkout are staged and committed, including deletions, untracked files, previously staged changes, and changes outside declared skill directories.
The same message is used for each selected checkout needing a commit.
AEM reports the repository scope but does not determine whether unrelated files belong in the commit or outgoing history.
Without `-m`, publish requires no uncommitted changes and pushes existing commits.
No interactive confirmation or editor is required; use the optional dry run for review and supply a message when committing.

Publication uses the configured Git identity and signing settings, the registered origin URL, and the inventory branch (or the default branch recorded at bootstrap).
As with other AEM Git operations, repository Git hooks are disabled and authentication cannot prompt.
Only the selected branch is pushed, without force, additional branches, or tags; a different origin push URL is rejected.
Behind/diverged histories, wrong branches, and unfinished Git operations must be reconciled explicitly with Git before retrying.
Ignored untracked files are left alone by publication; the existing update/apply cleanliness rules still apply afterward.

With `--json`, results are grouped by checkout, with independent success/failure outcomes; any failure exits 1.
Publication is not atomic across repositories or between commit and push.
A failed commit may leave staged changes, and a failed push retains the local commit; inspect the reported error and retry after resolving it.
Publication does not install content or update automatic-policy attempt clocks.
For copy installations, edit the checkout and run apply after committing; changes made only in an installed copy or detached copy are not collected into the source.
External sources are reported as unsupported for publication; their synchronization remains outside AEM.

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
aem locate NAME [--agent AGENT] [--source]
```

The agent defaults to `codex`; NAME is a catalog skill or instruction bundle name.
By default, returns `root`, `entry`, `installed_root`, and `detached` from the selected agent's saved installation when one exists.
For skills, `entry` is SKILL.md, and `location` distinguishes a linked source from a copy.
An installed copy or detached item resolves to its preserved local contents, not the publish source.
Saved lookup works without loading the catalog or validating installation fields, accepts state versions 1 and 2, and never changes ownership.
Missing or redirected entries and replaced active links are errors; a broken installation never silently falls back to its source.

If no saved installation exists for the selected agent, locate resolves the prepared source from the current catalog.
Use `--source` to request that source explicitly even when a copy, detached item, or broken installation exists.
Source lookup returns `location: "source"`, `root`, `entry`, `checkout` (null for external folders), `repository`, and all source names sharing the checkout in `members`.
It sets `installed_root` to null and `detached` to false because it describes the source, not an installation.
It requires a valid current machine/catalog configuration and existing source content; it does not clone or fetch.
Git source lookup validates the registered repository and branch but allows uncommitted edits.
Use the returned root/entry to edit, then `publish NAME` for Git content; external synchronization stays outside AEM.

```bash
aem locate report --source
# Edit the returned entry or other files under root.
aem publish report -m "Clarify guidance"
```

Instruction callbacks continue to use saved instruction installations only, without catalog fallback or source lookup.

## recover

```text
aem recover
```

Restores the previous target from a pending replacement journal when observations still match.
Refuses to overwrite later user edits; retain the target, backup, and state for manual reconciliation.
Transactions are per target, so recovery does not undo earlier successful targets.
Recovery accepts the common journal format in state versions 1 and 2, validates paths and observations, and preserves the original state version and unrelated fields.
An unknown version or incomplete journal is rejected rather than inferred.

## automation

```text
aem automation --trigger EVENT [--dry-run]
```

Runs the selected device mode.
`off` returns `mode = "off"`, `status = "disabled"`, empty `outcomes`, and `failed = false`.
`policies` returns the individual `self_update` / `catalog_update` outcomes, skill `outcomes`, and `failed`; catalog failures skip skill work.
`full` returns `not-triggered`, `throttled`, `planned` (preview), or `queued` and defers the whole sequence until requester termination.
Only full mode uses the shared device trigger list and interval; individual modes retain their existing clocks.
Dry run makes no remote requests or attempt records and creates no command lock files.
The full preview includes `policy` and `stages = ["tool", "catalog", "content"]`.
The full launch result includes `mode`, Unix `time`, `trigger`, `token`, and an opaque request `binding`.
A launch failure exits 1; a successfully queued run exits 0 and reports eventual failure through status.

`status` includes an `automation` object with effective `policy` and `last_attempt`.
Full attempt status can be `queued`, `continuing`, `completed`, `failed`, or `cancelled`.
Continuation results contain a `stages` object with the tool outcome and, when reached, catalog and content outcomes.
Terminal results include Unix `finished`, with `error` or `reason` on failure/cancellation.
The content result includes selected `sources`, `excluded` consumers/reasons, and preparation/update/application outcomes when reached.
The tool stage obeys the existing self-update release range; `off` skips it.
The fresh installed CLI then updates only a Git-bound catalog before resolving declarations, preparing eligible sources, updating them, and applying only after delivery succeeds.
Full runs can install new declarations, while preserving explicit manual exclusions, detached groups, conflict/recovery protections, and shared-link semantics.
They do not publish content or delete targets removed from the catalog.
The worker and fresh continuation release/reacquire installation-before-configuration locks; mode/runtime binding and one-use token checks prevent stale continuation.
The continuation has no total wall-clock timeout; individual Git phases and the tool subprocess remain bounded.

In `off` mode, `auto` returns no skill work and `catalog auto` reports `not-triggered`.
In `full` mode these individual event commands fail with guidance to use `automation`, avoiding duplicate policy execution.
Explicit `self update`, `catalog update`, content `update`, and `sync` retain their contracts in every mode.

## startup

```text
aem startup --trigger EVENT [--agent AGENT]
```

Callback registered by setup; runs the selected device automation mode and remains fail-open.
In the default `policies` mode it independently queues due AEM self-updates, runs the machine catalog policy, then runs the same skill policy engine as `auto`.
In `full` mode it queues the entire sequence for execution after the callback exits; in `off` mode it performs no automatic work.
A successful catalog update reloads declarations before resolving skill policies for that event.
A failed catalog attempt skips skill work for that event, preserving fail-open startup.
The saved startup report includes the catalog result as `catalog_update`.
No bound catalog means no skill update work; enabled self-updates still run.
Self-updates are throttled once per day across events, including failures, and start after the requesting process exits.
They do not delay startup for release discovery or package installation.
The saved startup report includes `self_update`; `status` also reports the latest worker result separately.
AEM self-update completion does not produce a skill-change briefing.
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
