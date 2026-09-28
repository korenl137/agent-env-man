# Removed interfaces and existing installations

The catalog is now the only content declaration format.
This is a breaking cleanup for installation: there is no legacy source parser, command alias, or automatic conversion.
Saved ownership remains available for maintenance without restoring legacy installation semantics.

| Removed interface | Current approach |
| --- | --- |
| Source-local `links.conf` (four or six fields) and machine `[sources]` | Catalog `skills`, `instructions`, and named `repositories`/`externals`. |
| `bootstrap NAME --path`, `--git`, `--branch`, `--manifest`, `--attach` | `bootstrap CATALOG`; put Git declarations in the catalog and external bindings in machine configuration or `--external`. |
| `codex-merge` JSON declarations and leaf-key ownership | Manage application `config.toml` directly; AEM no longer installs partial application settings. |
| `codex-hook NAME` | `agent-hook NAME --agent codex`; new instruction hooks use this command. |
| `sync --min-interval` and the configuration-wide attempt clock | Per-skill catalog policies and `auto --trigger EVENT`. Explicit sync is unthrottled. |
| Generated instruction guides and their in-place upgrade | Direct links to original entry documents, plus location hooks. |
| Installing/updating through state version `1` | New installations require state version `2`; maintenance can release version-1 ownership without converting it. |

Catalog and machine TOML versions remain `1`; state versioning is separate.
Installation/update commands reject machine `[sources]` even when empty and reject unknown machine fields.
Maintenance ignores unrelated declarations and preserves them.
Explicit catalog roots, direct skill repository declarations, and `bootstrap --catalog` remain current supported interfaces.

## Before upgrading an existing installation

Use current AEM maintenance commands against the old machine file:

```bash
aem --config /path/old-machine.toml status
aem --config /path/old-machine.toml recover
aem --config /path/old-machine.toml detach ITEM_ID ...
aem --config /path/old-machine.toml setup --remove-shell bash --remove-agent codex
```

Inspect status for saved IDs and run recovery only when a replacement is pending.
Detach the relevant managed content before removing its agent integration.
Removal-only setup accepts saved integration names even if the current build no longer ships their profiles.
It does not refresh remaining integrations and does not require the old executable to exist.
Disable/remove retained old instruction hooks through the agent's hook controls.
Detach preserves contents; it does not disable retained instruction hooks.
Keep a backup of the old machine file and state together, along with source contents and target backups.

Prepare a new machine configuration and state location with the current catalog format.
Preserved old targets remain unmanaged conflicts: inspect them, move them aside, or explicitly adopt matching content/replace selected targets with backups.
Run bootstrap, preview apply, then apply and review new hook trust.
The new build does not clean old checkouts, delete preserved targets, or automatically adopt them.
Maintenance preserves the old state's version and unknown fields, so releasing everything does not convert it into a current installation state.
Only the known version-1/version-2 ownership envelope and per-target journal format are accepted; unknown versions and incomplete/unsafe journals still require the matching tool or manual reconciliation.

Do not edit the old state's version number or delete its ownership records to force acceptance.
If an old hook still invokes `codex-hook`, the removed command will return a CLI usage error until that registration is replaced.
This repository cleanup does not modify an installed AEM tool, live machine configuration, shell profile, or agent home.
