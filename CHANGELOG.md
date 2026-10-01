<!-- markdownlint-disable MD024 -->

# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
During 0.x development, minor releases may break compatibility; patch releases preserve it.

## [Unreleased]

### Changed

- Expand CLI help with selection scope, settings stage locations and field choices, shell navigation requirements, and publication defaults without changing command behavior; define contributor guidance for concise, sufficient installed help.
- Move detailed automation, AEM self-update, and maintenance/recovery guidance into dedicated docs guides; retain core workflows and preservation reminders in the README, and clarify contributor guidance without changing its structure or contracts.
- Official skill contribution guidance prioritizes installed CLI help and authoritative local documentation; streamline `idk-aem` around important operation boundaries, publication scope, and preservation.

## [0.5.1] &mdash; 2026-10-01

### Fixed

- Allow first publication of the registered local branch to a verified empty Git remote, including catalog and settings publication; keep authentication/network failures and missing branches in populated remotes fatal.
- Keep catalog skill replacement and detach backups outside agent discovery roots to prevent duplicate skills, with verified copies and recovery across filesystems while preserving older recovery journals.

## [0.5.0] &mdash; 2026-10-01

### Added

- Staged application TOML settings with Git/external sources, explicit field collection, persistent deletion/release intent, source export, Git publication, conflict resolution, and grouped recovery.
- Settings-aware locate/status and bootstrap `--setting-target` bindings; settings stages and actual files remain outside automatic/full runs.
- `locate --cd` and `catalog locate --cd` enter the selected directory through the Bash, Zsh, or PowerShell setup integration; standalone use prints the directory path.

### Changed

- During 0.x, permit compatible feature additions in PATCH releases, with MINOR chosen at maintainer discretion according to scope and significance; incompatible changes and public deprecation still require MINOR.
- Contributor guidance requires reviewing and updating affected official skill guidance alongside user-facing changes; the `idk-aem` skill now covers directory navigation with `locate --cd`.

## [0.4.2] &mdash; 2026-10-01

### Fixed

- Instruction callbacks wait for installation-lock contention within the same five-second budget as configuration-lock contention, instead of stopping immediately when another AEM command holds the installation lock.

## [0.4.1] &mdash; 2026-10-01

This release preserves existing setup behavior and adds the official skill as an ancillary integration under the 0.x PATCH exception.
It is eligible for `compatible` self-updates from 0.4.0.

### Added

- Official `idk-aem` skill for AEM user operations, authored at `skills/idk-aem/SKILL.md` and included in wheel and source distributions.
Self-update validates owned skill links and local source edits before package replacement, then verifies or refreshes links through the fresh CLI with separate stage results.

### Changed

- Agent setup attempts the official skill link after completing core integrations and machine selection storage, reporting recoverable skill failures separately without failing setup.
Agent removal also removes unchanged owned official links; changed links, edited sources, and substituted copies are preserved and released from ownership.
User catalog installation and content editing remain independent of the official skill.
- Permit compatible supporting refinements to existing workflows in PATCH releases during 0.x only; new functionality otherwise remains MINOR, and compatibility, ownership, and recovery guarantees remain required.

## [0.4.0] &mdash; 2026-10-01

This release requires catalog v2 and changes CLI parsing and default report formatting.
Follow the [catalog transition instructions](docs/removed-interfaces.md#catalog-v2-transition) before upgrading existing installations.
During 0.x, `compatible` self-updates stay within the current minor series; upgrading from 0.3.x to 0.4.0 requires an explicit upgrade or `breaking` permission.

### Changed

- **Breaking:** Require catalog `version = 2`, named `sources` with explicit Git/external types, one `source` reference per item, and nested skill/instruction installation tables.
Catalog update triggers accept only event arrays; `[]` disables automatic execution, including inherited exclusions in full mode.
Machine format/policies, state version 2, policy JSON and callbacks retain their contracts; saved-state maintenance remains available with old catalogs.
Named checkout identities are retained; direct-declaration or relocated installations require manual detach and explicit reattachment/replacement, with old contents and backups preserved.
See [transition instructions](docs/removed-interfaces.md#catalog-v2-transition).
- **Breaking:** Ordinary CLI commands now print human-readable fields and indented lists by default, including redirected stdout.
Add the global `--json` option before the command to retain the existing JSON report schema; installed startup and instruction callbacks continue to emit JSON automatically.
- **Breaking:** Replace argparse with Click command groups and consistent option scope.
Place global `--config` and `--json` before the command, for example `aem --json status`.
Abbreviated long options are rejected, and invalid numeric CLI durations now exit `2` as usage errors before configuration reads or filesystem effects.
- Centralize CLI configuration/locking, report output, and operational error handling while keeping command callbacks and reusable core operations separate.
- Allow Git-ignored runtime files in prepared checkouts during bootstrap, apply, and content/catalog updates; ignored files alone no longer mark a content checkout dirty.
Fast-forwards preserve local ignored files by refusing incoming path collisions.
Directory links, copies, and detach retain ignored regular contents; installed-copy local edits and unsupported nested links/special files remain protected.

## [0.3.0] &mdash; 2026-09-30

Existing configurations retain policy-driven automation by default; full automation requires explicit opt-in.
During 0.x, `compatible` self-updates stay within the current minor series; upgrading from 0.2.x to 0.3.0 requires an explicit upgrade or `breaking` permission.

### Added

- Installer/setup-selected device automation modes (`off`, `policies`, `full`), a unified event/preview command, and sequential full runs through tool replacement, fresh-CLI catalog refresh, and eligible content preparation/update/application with shared throttling.
Full runs preserve explicit manual exclusions and detached installations, stop later stages on failure, and retain the existing live-link effects of shared checkouts.
- Opt-in machine-owned catalog automatic triggers configured through bootstrap/setup options, independent attempt throttling, `catalog auto`, and validated catalog refresh before startup skill policies.
- Installer-selected `off`, `compatible`, and `breaking` AEM self-update modes, release-tag updates queued after startup exits, and independent `self status` / `self update` commands.
Updates validate release metadata, use an external worker after the requesting process exits, and serialize replacement across configurations sharing an installation.
- Changelog with release history and contributor guidance for maintaining release notes.
- Git-delivered catalogs registered through bootstrap repository/path arguments, with automatic machine binding and separate checkouts.
- Explicit `catalog status`, `locate`, `update`, and `publish` commands, including validation before catalog updates and offline publication previews.

### Changed

- Automation settings can be changed through configuration-only `setup` calls without registering integrations or rewriting shell profiles.
- Require validation across connected command workflows, including the distinction between installed content and editable source checkouts.

## [0.2.0] &mdash; 2026-09-29

This release includes incompatible installation and CLI changes.
See [Removed interfaces and existing installations](docs/removed-interfaces.md) for replacements and migration precautions.

### Added

- Shared Git checkouts through named catalog repositories, with validation of all declared skills and protection of active links before updates.
- Composable automatic skill update policies, per-skill attempt throttling, and an `auto` command for externally supplied startup or interval events.
- Instruction bundles from Git repositories or external folders, with direct entry-document links and Codex hooks that report saved reading locations.
- Repeatable machine setup and a uv-based installer, with Bash, Zsh, PowerShell, and Codex startup integrations and brief startup update reports.
- `locate` for saved skill/instruction installations and catalog source paths, including explicit source lookup for editing.
- `publish` to commit and push selected catalog sources by shared repository, with offline preview and retryable push failures.
- MIT license and a package-level compatibility policy covering commands, catalogs, generated configuration, and existing integrations.

### Changed

- **Breaking:** Installation requires state version 2, without automatic conversion of version-1 installations.
Maintenance commands can still inspect, detach, recover, and remove saved integrations using known version-1/version-2 ownership records independently of current installation declarations.
- Bootstrap accepts a positional catalog and external-folder bindings; explicit catalog and machine path overrides remain supported.
- Separate the configuration specification and command reference from the README workflows.

### Removed

- **Breaking:** Source-local `links.conf`, machine `[sources]`, legacy source bootstrap options, and partial Codex configuration merging; the catalog is the only content declaration format.
- **Breaking:** The `codex-hook` alias and generated instruction-guide upgrade path; instruction callbacks use `agent-hook NAME --agent codex` and direct entry links.
- **Breaking:** `sync --min-interval` and configuration-wide throttling; explicit sync is unthrottled, while automatic updates use per-skill catalog policies.

## [0.1.0] &mdash; 2026-09-26

### Added

- Initial agent environment manager with a user-owned TOML skill catalog and Git delivery independent of upstream repository manifests.
- Bootstrap, update, apply, sync, status, detach, and recovery commands with JSON output and offline installation from prepared checkouts.
- Direct skill links and explicit copies, ownership tracking, conflict adoption/replacement, retained backups, and journaled per-target recovery.
- Conservative Git updates that reject local changes and divergent histories and protect active skill link sources.
- Linux/WSL and native Windows path handling, with Python 3.11 or later and Git required.
- Legacy source-local `links.conf` delivery and partial Codex configuration merging, retained alongside the initial catalog workflow.

[Unreleased]: https://github.com/mirinae3145/agent-env-man/compare/v0.5.1...HEAD
[0.5.1]: https://github.com/mirinae3145/agent-env-man/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/mirinae3145/agent-env-man/compare/v0.4.2...v0.5.0
[0.4.2]: https://github.com/mirinae3145/agent-env-man/compare/v0.4.1...v0.4.2
[0.4.1]: https://github.com/mirinae3145/agent-env-man/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/mirinae3145/agent-env-man/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/mirinae3145/agent-env-man/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/mirinae3145/agent-env-man/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/mirinae3145/agent-env-man/tree/v0.1.0
