# TOML configuration reference

AEM reads two independent UTF-8 TOML documents, both with integer `version = 1`.
Filenames are arbitrary: the CLI selects a machine file, and its `catalog` field selects the catalog.
The catalog declares reusable content and update policies; the machine file binds them to this device.
Installation and update commands reject unknown fields in the catalog and machine configuration.
Maintenance commands can ignore unrelated fields; see [validation boundaries](#storage-and-validation-boundaries).
For the command interface, see [Commands](commands.md).

## Paths and identifiers

Names use ASCII letters, digits, `_`, `-`, and `.`, starting with a letter or digit.
Relative content paths use `/`, with no empty, `.` or `..` components, backslashes, drive prefixes, or leading slash.
Only `subdir` accepts `.` to select the source root.
Paths are literal: AEM does not expand environment variables, interpolate other fields, or evaluate shell expressions.
Machine paths must be absolute or begin with `~/`, except `catalog`, which may be relative to the machine file's directory.
On Windows, use forward slashes such as `C:/Users/me/.codex` in TOML strings.
CLI path arguments have their own resolution rules described in [Commands](commands.md#bootstrap).

## Catalog

The only top-level fields are `version`, `repositories`, `skills`, `externals`, `instructions`, and `updates`.
All tables are optional; an instruction-only catalog needs no skills table.
Skill and instruction names share a namespace.
A named repository or external is a source declaration, not an installable item by itself.

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

[updates.defaults]
trigger = "manual"
```

### `repositories.NAME`

| Field | Type | Requirement/default |
| --- | --- | --- |
| `type` | String | `"git"` only; defaults to `"git"`. |
| `repository` | String | Required Git URL, SSH repository location, or absolute local Git repository path. |
| `branch` | String | Optional nonempty branch name; bootstrap discovers and records the remote default when absent. |

Named repositories let multiple skills and instruction bundles share a checkout.
All consumers are validated before bootstrap publishes that checkout.
Direct skill declarations with equal URLs still get independent checkouts.

### `skills.NAME`

| Field | Type | Requirement/default |
| --- | --- | --- |
| `repo` | String | Name in `repositories`; mutually exclusive with `repository` and `branch`. |
| `type` | String | `"git"` only; required for a direct repository, optional with `repo`. |
| `repository` | String | Required when `repo` is absent; same syntax as named repositories. |
| `branch` | String | Optional for a direct repository; otherwise set it on the named repository. |
| `subdir` | String | Directory containing `SKILL.md`; defaults to `"."`. |
| `root` | String | Optional name in machine `roots`; the target is `ROOT/NAME`. |
| `mode` | String | `"link"` (default) or `"copy"`; machine `modes.NAME` overrides it. |
| `update` | Table | Optional policy selection and overrides; see below. |

With `root` omitted, selected agents supply their skill destinations.
Without selected agents, machine `roots.skills` is required; bootstrap supplies its default.
An explicit `root` overrides agent destinations; agents sharing a target share one ownership record.
Skill names identify installation ownership and directory names, independently of the name inside `SKILL.md`.
Root skills link directly to the repository root; copy and detach exclude only its top-level `.git` entry.

A direct repository declaration remains supported and is not a legacy format:

```toml
[skills.standalone]
type = "git"
repository = "git@github.com:OWNER/SKILL.git"
```

### `externals.NAME`

Declare an empty table.
Its device-local path belongs in machine `external_paths.NAME`.
External sources are supported for instruction bundles, not skills.
AEM neither fetches these folders nor administers the service that synchronizes them.

### `instructions.NAME`

| Field | Type | Requirement/default |
| --- | --- | --- |
| `repo` | String | Name in `repositories`; select exactly one of `repo` and `external`. |
| `external` | String | Name in `externals`, with a machine path binding. |
| `subdir` | String | Bundle directory under the source; defaults to `"."`. |
| `entry` | String | Required relative path to a regular entry document inside the bundle. |
| `root` | String | Optional machine root for bundle installation; otherwise uses `<machine-file>.bundles`. |
| `destination` | String | Relative bundle destination; defaults to the instruction name. |
| `entry_root` | String | Optional machine root for the global entry and hook file; otherwise uses selected agent roots. |
| `entry_destination` | String | Relative global entry destination; defaults to the agent's entry filename (`AGENTS.md` for Codex). |

An explicit `entry_root` selects one destination; without it at least one machine agent must be selected.
Bootstrap supplies `roots.agent`, but an instruction declaration must either refer to it or use an agent binding.
Codex is the only shipped agent profile.
An instruction creates `NAME:bundle`, `NAME:entry`, and `NAME:hook` ownership IDs.
The bundle and entry are links; the hook owns one group in `hooks.json` under the entry root.
Instruction copy modes and automatic policies are not supported.
Changing a managed source path, target path, or mode requires detach before reconfiguration.
AEM does not interpret document contents, reading order, or applicability.
See the [instruction walkthrough](instruction-bundles.md).

### Update policies

Policy tables are `updates.defaults`, `updates.policies.NAME`, and `skills.NAME.update`.
No other fields belong directly under `updates`.

| Field | Type | Built-in default and constraints |
| --- | --- | --- |
| `trigger` | String or string array | `"manual"`; otherwise one or more unique events: `"shell-start"`, `"agent-start"`, `"interval"`. Empty arrays and mixing `manual` with events are invalid. |
| `action` | String | `"sync"` or `"check"`; default `"sync"`. |
| `min_interval` | Integer or float | `600` seconds; finite and nonnegative. Boolean values are invalid. |
| `timeout` | Integer or float | `30` seconds per Git phase; finite and positive. Boolean values are invalid. |
| `policy` | String | Optional name in `updates.policies`; allowed only in `skills.NAME.update`. |

Resolution order is built-ins, catalog defaults, selected named policy, then skill-local fields.
Only supplied fields override earlier values; trigger arrays replace earlier arrays.
Named policies cannot inherit another policy.
All declarations, including unused named policies, are validated before network access.

```toml
[updates.defaults]
trigger = ["shell-start", "agent-start"]
min_interval = 600

[updates.policies.observe]
action = "check"

[skills.report.update]
policy = "observe"
timeout = 5
```

`check` fetches references without moving the checkout or installing targets.
`sync` fast-forwards and applies each successful skill independently.
Each skill records attempts before network access; failures and successes share its throttle across events.
A shared checkout update changes all live links immediately, including linked instructions; copy installation still follows selected skills.
Policies do not register hooks or launch a scheduler; use `setup` or arrange external `auto` calls.
Explicit commands ignore these policies and clocks.

## Machine configuration

| Field/table | Type | Meaning/default |
| --- | --- | --- |
| `version` | Integer | Required, exactly `1`. |
| `catalog` | String | Optional local catalog path; required for bootstrap/content preparation. One binding per machine file. |
| `checkout_root` | String | Managed Git storage; defaults to sibling `<machine-file>.checkouts`. |
| `roots` | Table of paths | User-named installation roots; bootstrap defaults missing `skills` and `agent`. |
| `agents` | Table | Agent selections and path bindings, normally written by setup. |
| `external_paths` | Table of paths | Logical external source bindings; every used external must be bound. |
| `modes` | Table of strings | Catalog skill names mapped to `"link"` or `"copy"`. Unknown skill names fail catalog validation. |
| `setup` | Table | Saved startup selections; normally written by setup. |

```toml
version = 1
catalog = "catalog.toml"

[roots]
skills = "/home/me/.agents/skills"
agent = "/home/me/.codex"

[agents.codex]
root = "/home/me/.codex"
skills = "/home/me/.agents/skills"

[external_paths]
documents = "/home/me/Synced/documents"

[modes]
report = "copy"
```

Machine selection defaults to `$XDG_CONFIG_HOME/agent-env-man/machine.toml` or `~/.config/agent-env-man/machine.toml` on Linux/WSL.
On Windows it uses `%LOCALAPPDATA%/agent-env-man/machine.toml`, falling back to `~/AppData/Local/agent-env-man/machine.toml`.
Pass `--config PATH` before the command to select another file.

### Roots and agents

`agents.codex` accepts only `root` and `skills` path strings.
Omitted fields default to `CODEX_HOME` (or `~/.codex`) and `~/.agents/skills`, respectively.
Setup persists resolved defaults; saved values take precedence over later environment changes.
Setup initially respects existing `roots.agent` and `roots.skills` when adding Codex.
Bootstrap root overrides for `agent` and `skills` also update an existing Codex binding.
Custom roots must be declared explicitly.
AEM derives `aem-agent-codex` and `aem-skills-codex` roots from the agent binding; conflicting manual definitions are rejected.

### Saved setup

`setup` accepts only `executable` and `shells`.
`executable` is an absolute path to the installed `aem` executable.
`setup.shells` maps `bash`, `zsh`, or `powershell` to absolute profile paths.
Manage these selections with `aem setup`; editing TOML does not itself install or remove profile blocks or hook groups.
Setup rejects an invalid executable path before writing profiles and requires an existing executable except during dry run.

### Storage and validation boundaries

Direct skill checkouts use `CHECKOUT_ROOT/SKILL`; named repositories use `CHECKOUT_ROOT/.aem-repositories/NAME`.
Ownership, attempt records, and recovery journals live in sibling `<machine-file>.state`; default bundle links live in `<machine-file>.bundles`.
Do not synchronize machine files, checkouts, or state between devices.
External roots must be disjoint from each other, managed checkout storage, the catalog, machine file, and state.
Targets may not overlap sources, manager storage, or another owned target tree.

The catalog is loaded lazily so status, detach, locate, recover, and setup can still operate when it is unavailable.
Status reports catalog errors alongside saved installation observations.
The machine file must still be parseable TOML.
`detach`, `recover`, `locate`, `agent-hook`, and removal-only `setup` use its location and saved ownership without interpreting installation fields or the machine schema version.
They preserve unknown fields; setup removal only edits requested saved selections.
Offline `status` falls back to saved target observations when strict machine or state validation fails.
`status --refresh` still requires valid installation configuration.
Automatic policy attempts and ownership are generated state, not user-editable TOML settings.
New installations use state version `2`.
Maintenance accepts the common ownership/journal structure of versions `1` and `2` and retains its version and opaque fields on save.
It validates only the records and operations needed for the requested cleanup; it does not restore legacy installation behavior.
Unknown state versions or malformed ownership/journal structures are still rejected.
Regular setup, bootstrap, apply, update, sync, automatic updates, and refreshed status continue to require current configuration and state.
See [Removed interfaces](removed-interfaces.md) before upgrading an existing installation.
