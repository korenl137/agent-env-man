# Legacy links.conf compatibility

The initial implementation registered source repositories that carried both content and a links.conf manifest.
This remains available for existing configurations and Codex partial-merge items.
New Git skill installations use the independent local catalog described in the [README](../README.md).
The two paths share ownership, conflict handling, and detach behavior.

## Register an existing manifest source

```bash
aem bootstrap personal \
  --git git@github.com:YOUR-NAME/personal-agent-config.git \
  --branch main \
  --path ~/ai-config/personal
aem apply --dry-run
aem apply
```

Use `--attach` for an existing checkout, or omit `--git` for an already prepared external local folder.
Bootstrap registers active manifest items unless restricted with repeated `--item ID` options.
New upstream manifest rows are not automatically registered; add their IDs to the machine configuration explicitly.

```text
# platform|source|target root|target path|mode|item ID
all|rules/AGENTS.md|codex|AGENTS.md|link|global-agents
all|skills/my-skill|skills|my-skill|link|my-skill
all|codex.json|codex|config.toml|codex-merge|codex-settings
```

Platforms are `all`, `linux` (including WSL), and `windows`.
Source and target paths are literal relative paths with `/` separators, without traversal, quotes, or shell evaluation.
Four-field rows remain supported as links, with generated stable IDs based on the destination root and path.

The machine file stores legacy sources as follows:

```toml
version = 1

[roots]
codex = "/home/me/.codex"
skills = "/home/me/.agents/skills"

[sources.personal]
path = "/home/me/ai-config/personal"
manifest = "links.conf"
git = "git@github.com:YOUR-NAME/personal-agent-config.git"
branch = "main"
items = ["global-agents", "my-skill", "codex-settings"]
```

Unlike catalog skill names, legacy item selections use `SOURCE:ID`, for example `aem detach personal:my-skill`.
The optional `[sources.personal.modes]` table overrides registered link/copy modes explicitly.
Registered source roots must not overlap each other, catalog checkout storage, machine state, or targets.
Removing an item from the manifest leaves its ownership record and target intact until detach.

## Partial Codex configuration

A `codex-merge` item consumes this JSON shape; these example key names describe syntax, not recommended Codex settings:

```json
{
  "version": 1,
  "set": [
    {"path": ["example_table", "example_key"], "value": true}
  ]
}
```

Select real key paths appropriate to your installed Codex version.
The adapter validates JSON/TOML structure, not the evolving Codex settings schema.
It owns only explicit scalar/array values and preserves unrelated settings and comments.
Arrays are managed as whole values; tables are not owned wholesale.
Only one merge item may own a target file in this version.

An existing key requires explicit adoption or replacement before first ownership.
Changes to managed keys are compared to their last applied values; changes to other keys do not conflict.
Removing declared keys does not delete their target values: detach, edit the declaration, and explicitly reattach when needed.
Merge detach leaves all current settings intact.
A config.toml symlink managed by an older installer must be materialized and released from that installer before partial merge can use it.
