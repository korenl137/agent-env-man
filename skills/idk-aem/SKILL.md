---
name: idk-aem
description: Use AEM (agent-env-man) to configure agent integrations, manage catalogs, install or update managed skills and instructions, locate or publish their sources, and inspect or recover installations. Applies to AEM user operations rather than development of AEM itself.
---

# Use AEM

Use the installed `aem` CLI for the requested operation.
Consult `aem --help` and the relevant command's `--help` for the installed version rather than assuming options or reconstructing ownership from directory names.
Put global options before the command: `aem --config /absolute/machine.toml --json status`.
Use JSON reports when choosing subsequent commands; queued self-updates have not completed yet.

## Choose the operation

- `setup` connects agents and shells and configures machine automation. Agent integration includes this official skill. It does not install user catalog content or grant hook trust.
- `bootstrap` binds or prepares a catalog and its content sources; `apply` installs declared content from prepared local paths.
- `catalog` commands inspect, locate, update, or publish the catalog repository. Content `update` does not refresh the catalog.
- `update` advances selected content sources; linked installations change immediately. `sync` updates and applies; copy installations need application to receive changes.
- `settings prepare/collect/release/resolve` operate on editable settings stages; `export` reflects a stage in a Git/external source without publishing. Settings are excluded from automatic/full runs.
- `status` inspects installations and pending recovery. `self status` and `self update` concern AEM itself, independently of catalog content.
- `locate` identifies installed or source paths; `publish` publishes the selected source repository. Consult command help for selectors: preparation uses catalog names, while installation may use component ownership IDs.

## Locate and publish

Use `locate` to distinguish installed content from its editable source.
Linked installations expose the source; installed copies and detached content can differ from it.
Use `locate --source` when the task targets source content for publication.
This skill identifies paths and manages AEM operations; it does not prescribe how to author or edit the content at those paths.

For directory navigation, use `aem locate NAME --cd`, adding `--source` to enter the prepared source instead of an installed copy or detached content.
Use `aem catalog locate --cd` to enter the directory containing the catalog entry.
These commands change the calling shell's directory only through the Bash, Zsh, or PowerShell integration registered by `setup --shell`; existing registrations need setup run again and the profile reloaded to gain this function.
Without that integration, `--cd` prints only the absolute directory path; use it as a working directory for subsequent tool calls or with `cd -- "$(aem locate NAME --cd)"` in Bash/Zsh.
Do not combine `--cd` with `--json`, and do not assume a directory change in one tool subprocess persists in later calls.

For settings, default `locate NAME` identifies the editable stage, `--source` identifies the shared file, and `--target` identifies the actual application file.
Apply uses the stage; update receives shared changes; collection of actual edits is explicit.
New managed fields require `settings collect NAME --path '["section","key"]'` or stage editing.
Deletion and `settings release` have different effects; release leaves actual values in place.
Use `settings resolve` for shared conflicts and preserve stage edits on detach.
Git settings publication includes export; external sources support export and leave synchronization to their existing service.

Publication acts on the whole selected repository, including files outside the selected skill or instruction directory.
A supplied commit message stages all nonignored changes; without a message, publication requires a clean worktree and pushes existing commits.
Inspect the relevant changes and publication preview before publishing when the task calls for publication.
Do not infer authorization to publish from a request to locate or edit content.

## Conflicts and recovery

Inspect reported targets and ownership before resolving a conflict.
Do not delete state, reset a checkout, or use adoption/replacement merely to bypass a diagnostic.
Use explicit selections for intentional adoption or replacement and preserve the user's local changes.
When a replacement is interrupted, inspect `status` and use `recover` before retrying.
`detach` preserves contents and releases management; it does not restore the pre-installation contents.

Respect the user's chosen catalog, machine configuration, automation settings, and existing authorization.
Use available previews for consequential operations when they help verify scope.
Keep content editing governed by the user's task and the content's applicable instructions.
