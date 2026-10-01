<!-- markdownlint-disable MD024 -->

# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
During 0.x development, minor releases may break compatibility; patch releases preserve it.

## [Unreleased]

### Changed

- **Breaking:** Ordinary CLI commands now print human-readable fields and indented lists by default, including redirected stdout.
Add the global `--json` option before the command to retain the existing JSON report schema; installed startup and instruction callbacks continue to emit JSON automatically.
- **Breaking:** Replace argparse with Click command groups and consistent option scope.
Place global `--config` and `--json` before the command, for example `aem --json status`.
Abbreviated long options are rejected, and invalid numeric CLI durations now exit `2` as usage errors before configuration reads or filesystem effects.
- Centralize CLI configuration/locking, report output, and operational error handling while keeping command callbacks and reusable core operations separate.

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

[Unreleased]: https://github.com/mirinae3145/agent-env-man/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/mirinae3145/agent-env-man/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/mirinae3145/agent-env-man/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/mirinae3145/agent-env-man/tree/v0.1.0
