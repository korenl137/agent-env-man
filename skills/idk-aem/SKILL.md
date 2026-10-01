---
name: idk-aem
description: Use AEM (agent-env-man) to configure agent integrations, manage catalogs, install or update managed skills and instructions, locate or publish their sources, and inspect or recover installations. Applies to AEM user operations rather than development of AEM itself.
---

# Use AEM

Use the installed `aem` CLI for the requested operation and preserve the user's selected catalog, machine configuration, and automation settings.
This skill covers AEM operations; content editing follows the user's task and the content's applicable instructions.

## Discover the relevant interface

Start with `aem --help` and the relevant command's `--help` to learn the installed version's commands, selectors, options, and previews.
Use JSON reports when subsequent actions depend on command results; a queued update is not a completed update.

Read the relevant command's local help before choosing selectors or sequencing operations.
For behavior beyond help, use `aem docs` to locate the installed README and follow its local links to the relevant command, configuration, settings, or recovery documentation.
For staged settings, consult `aem settings --help` and the chosen subcommand's help before collection, deletion, release, or conflict resolution.

## Important operation boundaries

`setup` connects agents and shells; `bootstrap` prepares catalog content; `apply` installs from prepared local paths.
Agent setup includes this official skill but does not install user catalog content or grant hook trust.
Catalog updates, content updates, and AEM self-updates are separate operations.
`self publish` publishes an already prepared AEM checkout and release tag; it does not prepare a release or update the installation.
Content `update` changes linked installations immediately; copies need `apply`, and `sync` combines update and application.

Use `locate` to distinguish installed content from its editable source, and request `--source` when editing content for publication.
Installed copies and detached contents can differ from the source; publishing does not collect their edits.
Use returned paths as explicit working directories in tool calls rather than assuming shell navigation persists between subprocesses.

Settings use an editable stage between the shared source and actual application file.
Apply consumes the stage; collection of actual-file edits and export to the source are explicit.
Removing a managed field requests deletion; releasing it leaves the actual value in place.
Settings are excluded from automatic/full runs.

## Publication and preservation

Publication acts on the entire selected repository, including changes outside the selected content directory.
For content/catalog publication, supplying a commit message stages all nonignored changes; inspect the repository changes and publication preview to verify scope.
Self publication instead requires a clean committed release with its matching tag already prepared in Git; verify the reported checkout and destination before publishing.
A preview is offline and cannot confirm remote state; a remote failure does not establish an empty remote.
A request to locate or edit content does not itself authorize publication.
External-source synchronization remains the responsibility of its existing service.

Inspect reported targets and ownership before resolving conflicts; preserve local changes, state, and recovery backups.
Do not delete state, reset checkouts, or adopt/replace content merely to bypass a diagnostic.
Use explicit selections for intentional adoption or replacement.
After an interrupted replacement, inspect `status` and use `recover` before retrying.
`detach` preserves current contents and releases management; it does not restore pre-installation contents.

## Agent integrations

Codex and Claude share content commands but use their own saved paths and hook
formats. Preserve unrelated settings and hooks; AEM does not grant hook trust.
For full asynchronous startup, inspect status and start a fresh product session
after completion to discover updated skills. See the installed agent profile
guide through `aem docs`.
