# Removed interfaces and existing installations

The catalog is now the only content declaration format.
This is a breaking cleanup: there is no legacy parser, command alias, ownership adapter, or automatic conversion.

| Removed interface | Current approach |
| --- | --- |
| Source-local `links.conf` (four or six fields) and machine `[sources]` | Catalog `skills`, `instructions`, and named `repositories`/`externals`. |
| `bootstrap NAME --path`, `--git`, `--branch`, `--manifest`, `--attach` | `bootstrap CATALOG`; put Git declarations in the catalog and external bindings in machine configuration or `--external`. |
| `codex-merge` JSON declarations and leaf-key ownership | Manage application `config.toml` directly; AEM no longer installs partial application settings. |
| `codex-hook NAME` | `agent-hook NAME --agent codex`; new instruction hooks use this command. |
| `sync --min-interval` and the configuration-wide attempt clock | Per-skill catalog policies and `auto --trigger EVENT`. Explicit sync is unthrottled. |
| Generated instruction guides and their in-place upgrade | Direct links to original entry documents, plus location hooks. |
| State version `1`, including its old modes and ownership fallbacks | New installations use state version `2`; older state is rejected without rewriting it. |

Catalog and machine TOML versions remain `1`; state versioning is separate.
Machine `[sources]` is rejected even when empty, and unknown machine fields are errors.
Explicit catalog roots, direct skill repository declarations, and `bootstrap --catalog` remain current supported interfaces.

## Before upgrading an existing installation

Use the matching older AEM build to inspect the old configuration, finish pending recovery, and detach its managed content.
Remove old startup integrations with that build where available, and disable/remove retained old instruction hooks through the agent's hook controls.
Detach preserves contents; it does not disable retained instruction hooks.
Keep a backup of the old machine file and state together, along with source contents and target backups.

Prepare a new machine configuration and state location with the current catalog format.
Preserved old targets remain unmanaged conflicts: inspect them, move them aside, or explicitly adopt matching content/replace selected targets with backups.
Run bootstrap, preview apply, then apply and review new hook trust.
The new build does not clean old checkouts, delete old targets, reinterpret old recovery journals, or automatically adopt them.

Do not edit the old state's version number or delete its ownership records to force acceptance.
If an old hook still invokes `codex-hook`, the removed command will return a CLI usage error until that registration is replaced.
This repository cleanup does not modify an installed AEM tool, live machine configuration, shell profile, or agent home.
