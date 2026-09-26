# agent-env-man

Deliver user-owned AI agent instructions, skills, and selected settings to multiple devices, then install only the explicitly registered items.
The manager lives in this repository; personal content lives in a separate Git repository or an existing local folder.

```text
Git remote --bootstrap/update--> device-local checkout
                                         |
                              links.conf + apply
                                         |
                           link / copy / Codex merge
                                         |
                              application targets
```

Targets link directly to the checkout; there is no extra snapshot layer.
An update immediately changes the contents visible through existing links.
Copies and merged settings change only on `apply`.
Daily use, `apply`, `status`, and `detach` do not require a network connection.

## Install

Requirements: Python 3.11 or later and Git.
Linux, WSL, and native Windows are the intended environments.
Native Windows behavior needs validation on a Windows host; the initial implementation has been tested on Linux.

From this repository on Linux/WSL:

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

The examples below use `aem`; activate the virtual environment or substitute its executable path.
The TOML Kit dependency preserves unrelated TOML settings and comments when editing configuration.
No command changes your shell profile, enables Developer Mode, installs an agent, or uploads content.

## Prepare your content source

Put your own files and a `links.conf` in a separate repository:

```text
personal-agent-config/
  links.conf
  rules/AGENTS.md
  rules/research.md
  skills/my-skill/SKILL.md
  codex.json
```

An example manifest:

```text
# platform|source|target root|target path|mode|item ID
all|rules/AGENTS.md|codex|AGENTS.md|link|global-agents
all|rules/research.md|rules|research.md|link|research-rules
all|skills/my-skill|skills|my-skill|link|my-skill
all|codex.json|codex|config.toml|codex-merge|codex-settings
```

The supported platforms are `all`, `linux` (including WSL), and `windows`.
Paths are literal relative paths with `/` separators, without surrounding quotes, empty components, `.` or `..`.
Spaces and Unicode are supported; `|`, backslashes, and colons are reserved or rejected.
Paths are never evaluated as shell expressions.
The same ID can have separate Linux and Windows rows, but only one row per ID may be active on a device.

The original four-field `platform|source|root|destination` format also works: it defaults to `link` and receives a stable ID derived from root and destination.
Use explicit IDs for new manifests.
Old dotfiles bootstrap scripts cannot parse the six-field extension.

A directory item owns that specific subtree, including its children.
Register individual skill directories, not an application's whole configuration directory.
Payloads support regular files and directories, including empty directories and executable files; nested symlinks, junctions, special files, and Git submodules are excluded in this version.

## Bootstrap a device

Configure Git authentication in the device's environment first.
Git commands are noninteractive and use existing credentials; SSH uses OpenSSH batch mode.

```bash
aem bootstrap personal \
  --git git@github.com:YOUR-NAME/personal-agent-config.git \
  --branch main \
  --path ~/ai-config/personal
aem apply --dry-run
aem apply
```

Bootstrap clones and registers all active manifest items unless you select IDs with repeated `--item ID` arguments.
It prints the registered items and resolved roots without installing targets.
Specify custom roots using `--root NAME=ABSOLUTE_PATH`.
Add `--attach` to explicitly register an existing Git checkout instead of cloning.
An existing checkout must match the configured `origin` and branch.

For an existing local or externally synchronized folder:

```bash
aem bootstrap external --path ~/Drops/ai-rules --item my-skill
```

Without `--git`, the manager does not fetch, start Syncthing, or claim to know remote freshness.
Git and external source roots cannot overlap.
Keep machine configuration, state, and target paths separate from content sources.

The default machine configuration is `$XDG_CONFIG_HOME/agent-env-man/machine.toml`, or `~/.config/agent-env-man/machine.toml`, on Linux/WSL.
On Windows it is `%LOCALAPPDATA%\agent-env-man\machine.toml`.
Use `aem --config /absolute/path/machine.toml COMMAND` to select another configuration.
State and the process lock live in a sibling directory named `machine.toml.state`.
Do not sync either file or state directory between devices.

## Machine-local configuration

Bootstrap writes a TOML file like this:

```toml
version = 1

[roots]
codex = "/home/me/.codex"
skills = "/home/me/.agents/skills"
rules = "/home/me/.agent-rules"

[sources.personal]
path = "/home/me/ai-config/personal"
manifest = "links.conf"
git = "git@github.com:YOUR-NAME/personal-agent-config.git"
branch = "main"
items = ["global-agents", "research-rules", "my-skill", "codex-settings"]

# Optional, explicit device-specific choice; never an automatic fallback.
[sources.personal.modes]
my-skill = "copy"
```

Bootstrap supplies roots for `home`, `codex`, `skills`, `rules`, and `config`, plus `appdata` and `localappdata` on Windows.
`CODEX_HOME`, `XDG_CONFIG_HOME`, and Windows application-data environment values seed relevant defaults; explicit `--root` values take precedence.
Resolved roots are saved, so later environment changes do not silently relocate targets.
Machine paths must be absolute or start with `~/`; arbitrary environment interpolation is not supported.
Root substitution affects installation paths, not text inside instructions or settings.

New manifest items are not automatically enrolled: add their IDs to the device's `items` array before applying.
Source IDs and item IDs identify ownership; keep them stable.
Detach an installed item before changing its source path, target path, or installation mode.
Different Windows and WSL environments should have separate checkouts, config/state, and target roots.

## Commands and conflicts

| Command | Contract |
| --- | --- |
| `bootstrap` | Clone or register a source and write local configuration; never install targets. |
| `update [SOURCE ...]` | Fetch and fast-forward Git sources; existing links see changes immediately. External sources are checked for availability only. |
| `apply [--item SOURCE:ID ...]` | Validate selected registrations, then install from local sources without fetching. |
| `apply --dry-run` | Validate and show the planned actions without writing targets or ownership records. Link capability is checked during real staging. |
| `sync` | Update sources, then apply only if every selected update succeeds. |
| `status` | Print source and installation observations as JSON without network access. |
| `status --refresh` | Also fetch remote references without advancing checkouts or installing targets. |
| `detach SOURCE:ID ...` | Keep current contents, materialize links, release ownership, and suppress future automatic installation. |
| `recover` | Restore the previous target after an interrupted replacement, only if recorded contents still match. |

Output is JSON for inspection or scripting.
Errors are written to stderr with exit code 1; argparse usage errors use exit code 2.
`status` is an observation command: a successful report exits 0 even when it reports unavailable sources or conflicts.
Lock files/directories may be created by observational commands and dry runs.

Existing unmanaged targets are not overwritten by default.
For matching existing contents, explicitly adopt a selected item:

```bash
aem apply --item personal:global-agents --adopt
```

To replace a conflict while retaining a sibling backup:

```bash
aem apply --item personal:global-agents --replace
```

These options require explicit item selections.
Backups use `<target>.aem-backup-<id>` names and are retained for manual review and removal.
Even replacement cannot override an invalid payload, malformed TOML, overlapping ownership, or a merge target that is a symlink.

`copy` compares the desired payload, last applied fingerprint, and current target to distinguish `current`, `stale`, `modified-locally`, `conflict`, and `missing`.
Local additions to a copied directory count as modifications.
Link status checks the actual connection; `changed-live` means the linked source changed since the last apply and those changes are already visible.
The manager cannot distinguish an edit through a live link from an edit made directly in its source.
Edit canonical source files deliberately; there is no automatic commit, push, or reverse synchronization.

## Codex partial configuration

Use a `codex-merge` item to manage only explicit leaf keys in `config.toml`.
Its `codex.json` input has the following shape; the key below illustrates the format and is not a suggested Codex setting:

```json
{
  "version": 1,
  "set": [
    {"path": ["example_table", "example_key"], "value": true}
  ]
}
```

Choose real key paths appropriate to your installed Codex version.
The adapter validates JSON/TOML structure, not the evolving Codex settings schema.
Values can be strings, booleans, integers, finite floats, or flat arrays of these types.
Arrays are managed as whole values; tables are not owned wholesale.
Unrelated keys and comments are preserved.
An existing managed-path value requires explicit adoption or replacement before first ownership, even if it already matches.
Only one merge item may own a particular target file in this version.

Changes to managed keys conflict with the last applied values; changes to unrelated keys do not.
Removing a declared key does not delete it from the target: detach the merge item, change the declaration, then explicitly reattach it.
Merge detach leaves all current settings intact.
An old whole-file `config.toml` symlink must first be materialized and released from the previous installer before this adapter can use it.

## Failure preservation and detach

Git update refuses dirty checkouts, untracked or ignored local files, detached/wrong branches, unfinished Git operations, local-ahead history, and divergence.
Keep local-only data outside the content checkout.
There is no stash, reset, rebase, automatic commit, or push.
Updates also reject removal/type changes of active link sources, including when their manifest rows have disappeared.
This guard covers manager-driven Git updates; it cannot intercept manual source edits or external synchronization.
For an intentional removal, detach first, then update.

Apply validates the complete selected plan before writing targets, creates replacements before moving existing entries, and journals each replacement.
An ordinary replacement failure attempts to restore that target.
If the process stops mid-replacement, inspect `status` and run `recover`.
Recovery refuses to overwrite changes made after the interruption.
Do not delete the state directory to resolve a conflict: it is the ownership and recovery record.

Transactions are per target, not across all items: earlier items can remain successfully applied if a later operation fails.
Other applications do not participate in the manager's lock, and there is no guarantee of a consistent multi-file read during updates, an uninterrupted path during directory replacement, or complete rollback after a power failure.
Timeout/interruption during Git checkout can require manual source repair; ordinary fetch/authentication failures leave existing local payloads usable.

Detach copies the current linked file or directory to a temporary sibling, verifies it, replaces the link, and only then records release of ownership.
It preserves regular contents and portable copy metadata, including executable bits; special files and platform-specific ACL/alternate-stream preservation are outside this initial contract.
Broken links cannot be materialized and remain registered after failure.
If an editor already replaced a link with a regular local file/directory, detach keeps that current content.
Copies and merge targets remain untouched.
Removed manifest rows become orphaned ownership records, not implicit deletions.

To deliberately manage a detached item again, ensure its ID is registered and use:

```bash
aem apply --item personal:global-agents --reattach --replace
```

## Optional triggers

Manual `aem sync` is always supported.
No hook is required by the core.
A shell startup or an agent's supported session hook can invoke:

```bash
aem sync --timeout 5 --min-interval 600
```

All commands are noninteractive.
The interval throttles failed attempts too; the lock prevents overlapping commands for the same configuration.
The timeout bounds each source's Git operation, including subprocess cleanup; several sources take several such budgets.
An integration should retain stderr for diagnosis and allow shell/agent startup to continue when sync fails.
For example, after making `aem` available on `PATH`, an opt-in Bash line is:

```bash
aem sync --timeout 5 --min-interval 600 >/dev/null || true
```

In PowerShell, invoke `aem sync --timeout 5 --min-interval 600` without throwing on its nonzero exit code.
Automatic hook installation, Syncthing administration, general package/tool installation, generic merge adapters, and revert are deferred.

## AI disclosure

OpenAI Codex assisted with the initial design, implementation, documentation, and automated tests.
