# Contributing

## Versioning and compatibility

Follow the authoritative [compatibility policy](docs/compatibility.md) when changing public contracts or classifying releases.
It covers package versioning, supported interfaces, and machine/state format compatibility.

## Changelog and releases

Maintain [CHANGELOG.md](CHANGELOG.md) alongside notable user-visible changes and contributor workflow changes.
Release entries identify their `vVERSION` Git tag and the corresponding Python package version in `pyproject.toml`, using the supported tag conversion and compatibility policy above.

## Development and validation

Use Python 3.11 or later and Git.
Create a virtual environment and install the project with `python -m pip install -e ".[dev]"`.
Runtime dependencies are Click and TOML Kit.
Tests use the standard-library `unittest` runner and Click's `CliRunner` to check command behavior.
The development extra adds coverage.py for optional coverage measurement and setuptools for build-hook regression tests.

The following commands run the complete unittest suite and basic source checks:

```bash
python -m unittest discover -s tests -v
python -m compileall -q src tests
git diff --check
```

These examples assume an activated development environment.
Select checks according to the affected behavior and remaining uncertainty; a complete suite run is not required for every change.
Reuse passing results when subsequent changes cannot affect them.
On native Windows the same test command works with `.\.venv\Scripts\python.exe`.
Tests use temporary sources, targets, configuration, state, and local Git remotes.
Do not use actual user homes, credentials, or network remotes in tests.
Tests that require successful symlink creation skip when the host cannot create links.
The test that simulates unavailable symlink support must still run.
The initial validation was performed on Linux with Python 3.12.
Native Windows tests have run on Python 3.12, but link-dependent tests require a host with symlink creation enabled before claiming full Windows readiness.

Preserve Linux/WSL and native Windows path handling.
Use Python filesystem and subprocess APIs, explicit UTF-8 encoding, subprocess argument lists, and `/` in shared relative paths.
Do not depend on a POSIX shell from the core.
Windows-only code must not import POSIX locking or signal primitives at runtime.

### Writing for multiple execution environments

Consider supported environments while designing the change, even when only one is available for execution.
For affected behavior, identify relevant differences between native Windows and Linux/WSL, shell invocation, interactive terminals and redirected input, and editable versus installed or copied-worker execution.
Do not require every environment for every change; select the relevant dimensions and checks according to the affected contract.

- Treat filesystem paths and serialized representations as different values.
  Parse JSON before comparing path values, and decode encoded commands before checking their arguments.
  Assert exact bytes or quoting when serialization or byte preservation is the contract, with expectations appropriate to the platform.
- Account for drive and UNC paths, separators, case behavior, symlink/reparse capabilities, permissions, line endings, and non-ASCII or shell-sensitive characters where they affect the change.
  Do not normalize away distinctions that ownership, identity, or preservation checks rely on.
- Make test prerequisites explicit rather than inheriting the developer's machine state.
  Control home/configuration locations, relevant environment variables, executable discovery, working directory, TTY detection, and input responses when they influence the behavior under test.
  An unattended-flow test should fail if input is requested; interactive-flow tests should supply their expected responses.
- Use platform-appropriate fake executables and subprocess invocation.
  A POSIX shebang is not a portable executable fixture, and successful command serialization does not establish execution or exit-code propagation in the target shell.
  Keep portable policy and output checks runnable everywhere; isolate native process, shell, and filesystem checks behind explicit capability requirements.
- Exercise both success and failure behavior, especially preservation of user files, unrelated configuration, and saved ownership when an operation cannot proceed.
  A platform limitation should skip only checks requiring that capability, not portable validation of the corresponding error or refusal path.

When another relevant environment is unavailable, review its code paths and fixture assumptions and run the meaningful checks available locally.
Record the environments actually exercised, skipped capabilities, and remaining uncertainty with the change's validation results.
Mocks and static review support portability reasoning but do not establish native readiness; retain that distinction in compatibility claims.

### Installation and dependency boundaries

Base installation supports ordinary AEM use; the `dev` extra supports contribution work and the full test suite.
Both installations must have identical command behavior, configuration defaults, and automation policy.
Installing either package does not register shell or agent integrations; `aem setup` owns those explicit changes.
The repository installer combines package installation and requested setup as a user-facing workflow.

Runtime commands must not import development or build tools.
Build-system requirements provision isolated package builds independently of the `dev` extra; setuptools in `dev` supports source build-hook tests.
Keep the standalone installer and copied worker standard-library-only, and verify them with Python site packages disabled.

Source tests in an editable development environment and verification of an installed distribution are separate acceptance checks.
For packaging or dependency changes, also install a built wheel without extras into a fresh environment with neither coverage.py nor setuptools, and run the runtime verifier from the checkout:

```bash
python -m venv --without-pip /path/to/runtime-venv
python -m pip --python /path/to/runtime-venv install /path/to/agent_env_man-VERSION-py3-none-any.whl
python scripts/verify_runtime.py --python /path/to/runtime-venv/bin/python
```

Use a separate temporary environment; on Windows pass its `Scripts/python.exe` to the verifier.
The pip installation command uses the development environment's pip to install only the wheel and its runtime dependencies into the target environment.
Package acquisition may require network access; verification itself uses only temporary local Git repositories and never registers integrations.
The verifier rejects editable installations and environments containing development dependencies, disables Python source-path inheritance, and checks installed CLI help, local documentation, and bootstrap/apply/status/detach behavior.
It also exercises TOML and JSON settings reception, stage editing, application, export, local Git publication, conflict preservation, and detach through the installed CLI.
Verify both a direct wheel and a wheel rebuilt from the sdist as required by the installed-documentation contract below.

### Coverage measurement

Run coverage separately from ordinary tests, from the repository root in the activated development environment.
The configuration measures statements and branches in `src/` and `scripts/`, including the build hook and standalone installer.
Python subprocesses are also measured; combine their data before generating reports.

```bash
python -m coverage erase
python -m coverage run -m unittest discover -s tests -v
python -m coverage combine
python -m coverage report
python -m coverage html
python -m coverage json
```

Check the test command's exit status before treating a report as a successful baseline.
Reports from a failed run may help diagnosis but do not establish successful validation.
The terminal report shows missing lines and branch destinations; `htmlcov/index.html` provides file-level detail and `coverage.json` contains machine-readable results.
Coverage data and reports are ignored local artifacts.
There is no minimum coverage threshold or automatic CI or hook enforcement.
Keep coverage.py's default exclusions; do not exclude whole files to improve the percentage.

Review unmeasured failure, recovery, and platform paths for meaningful behavior tests before choosing a minimum threshold.
Record the source revision, environment, test outcomes and skips, statement and branch coverage, and combined percentage with validation results rather than embedding changing baselines in this guidance.
Linux/WSL measurement does not establish coverage of Windows-only behavior.
The same commands work with the native Windows environment's Python, but report its results separately.
Workers copied into temporary request directories are outside the configured source roots; subprocess measurement does not map those copies back to their originals.
Test the original worker's policy, failure, and continuation behavior separately from copied-worker lifetime integration.
Mocked Windows API tests check branching and resource handling; they do not establish native Windows lock or process behavior.

## Architectural contracts

Click owns CLI parsing, help, and command groups.
Command callbacks adapt inputs to core operations; shared execution owns configuration loading, locks, report output, and callback failure behavior.
Keep core installation, delivery, ownership, and policy operations independent of Click contexts so workers and non-CLI callers can reuse them.
Help and usage validation must complete before reading machine configuration or acquiring locks.
Global options belong before the command; repeated policy options must preserve the distinction between omission and an explicit replacement list.
Machine callbacks must emit the JSON required by their agent or worker contracts regardless of ordinary output mode.
The standalone installer and external update worker remain standard-library-only because they run outside the installed package environment.
Captured background processes on Windows must not open console windows, including Git, uv, PowerShell profile discovery, and fresh-CLI worker continuations.
Keep the worker lifetime pipe, process-group termination, captured output, and exit-code behavior intact when controlling console creation.

The manager owns reusable installation and delivery behavior.
Personal instructions, research guidance, skills, and settings remain user-supplied content outside this repository.
Do not introduce personal policies as built-in payloads.
The official `idk-aem` skill is the exception: it documents AEM user operations and ships with the package from `skills/idk-aem/SKILL.md`.
It must not prescribe how to author managed content or restrict user-requested edits.

Delivery prepares local source paths; installation consumes those paths without network access.
Git must remain an end-to-end supported delivery path, not an external setup prerequisite that bypasses the core.
AEM does not own the service that synchronizes an external folder.
Keep source roots disjoint, and never nest externally synchronized sources inside managed Git checkouts.

Targets directly link to local source content.
Compare Windows link destinations with equivalent extended drive/UNC prefixes normalized, without following aliases or changing raw transaction observations.
Do not add snapshot activation semantics silently: changing this contract requires an explicit design decision and updated user documentation.
An `update` can therefore change live instruction contents without `apply`.
The incoming-revision guard protects active link source paths, even if the latest catalog no longer declares those items.
Allow Git-ignored runtime files in checkouts while continuing to reject tracked changes and nonignored untracked files.
All content and catalog fast-forwards must refuse to overwrite ignored local files when mutating the Git checkout.
Never delete caches or weaken local-file preservation to make an update succeed.
Ignored regular files and directories remain part of directory payloads for hashing, copying, and detach.
Check the entire installed-copy tree for local modifications, and reject nested links and special files during payload validation.

The primary input is a user-owned skill, instruction, and settings catalog, independent of the repositories it lists.
The loader reads a local TOML file supplied directly or prepared through Git catalog delivery; policy composition must remain independent of this transport and any future auxiliary-file layout.
Each skill has a stable name and selects one Git repository and optional subdirectory.
Catalog v2 requires named sources with explicit Git or external types and one source reference per item.
Validate its surface syntax separately, then normalize to the existing runtime model; do not accept that private model as input.
Keep skill installation fields under `install`, instruction installation fields under `install.bundle`/`install.entry`, and skill entry files fixed to `SKILL.md`.
Catalog trigger arrays replace inherited values; `[]` disables automatic execution even in full mode, while omitted policies retain their full-mode participation.
Preserve machine policy syntax, effective policy JSON, per-skill attempt records and callback contracts when normalizing catalog policies.
Do not require upstream skill repositories to add manager manifests or aggregate their content in this repository.
The catalog owns repository URLs, requested branches, and declarative skill automatic update policies; machine configuration owns its catalog binding, checkout storage, target roots, and explicit mode overrides.
Bootstrap clones missing repositories directly from the catalog, discovers and records their default branches when unspecified, and validates SKILL.md before publishing a checkout.
Installation consumes these prepared local checkouts without fetching.
Share a checkout only when skills explicitly reference the same named repository; equal URLs under different source names do not imply shared ownership.
Preserve named-source checkout paths; do not migrate or remove old direct-declaration checkouts automatically.
Validate every skill in a shared checkout before publishing it, and guard all active links from that checkout before advancing it.
Keep installation ownership and automatic policies per skill, even when delivery is shared.
Do not introduce a provider framework without a demonstrated need.
Content rendering and arbitrary shell evaluation are not part of path substitution.
The catalog is the only content declaration format.
Do not restore source-local links.conf parsing, machine sources tables, legacy codex-merge declarations, or removed command aliases.
Staged application settings follow the independent contracts in [Settings management](docs/settings-management.md); they do not revive legacy installation semantics.
Installation requires state version 2; maintenance may read the shared ownership/journal envelope of versions 1 and 2 without conversion.
Keep detach, recover, saved-state lookup, offline status fallback, and removal-only setup independent of installation declarations.
These paths may ignore unknown machine fields and opaque modes, but must validate the specific saved paths, blocks, groups, and observations they consume.
Preserve unknown fields, unselected records, and the original state version when saving maintenance results.
Reject unknown state envelopes instead of guessing how to undo them.
Keep the breaking-change instructions in [Removed interfaces](docs/removed-interfaces.md) aligned with this boundary.

Instruction bundles select a named Git repository or a logical external source without source-local manifests.
Keep external path bindings in machine configuration and shared source/root/entry selections in the catalog.
Bootstrap accepts a positional catalog and optional repeated `--external NAME=PATH` bindings.
Persist them in the selected or default machine file, and reuse saved bindings when omitted.
Default agent and skills roots only when absent; validate declarations and existing ownership before saving bindings or contacting content repositories.
Support explicit `--config`, `--catalog`, and root and storage overrides.
Do not parse document policy, applicability, or reading order.
A Codex instruction bundle owns a directory link, a link directly to the original entry, and one `SessionStart` group in the entry root's `hooks.json`.
Bootstrap only prepares and validates sources.
Apply installs links and merges the hook without granting Codex trust or modifying `config.toml`.
Preserve unrelated JSON events, groups, and metadata; malformed or redirected hook files must fail preflight.
Own the complete AEM group identified by its saved marker, not the whole hooks file, and aggregate selected groups into one replacement per target file to avoid competing transactions.
Entry selection includes bundle and hook installation, but never extends replacement permission to an implicitly selected bundle.
Report the required `/hooks` trust review after apply; preview must show the planned group without registering it.
Detach materializes both links and releases hook ownership while retaining its configuration, so saved locator records still support preserved documents.
Default bundle installation to `<machine-file>.bundles/<bundle-name>` without requiring a configured rules root; preserve explicit location overrides and relocation guards.
Resolve roots from saved installation records and actual filesystem links, not from prompt text or the current catalog.
Saved location lookup must remain offline, avoid updating ownership records, work for detached copies without a catalog, and reject missing or redirected entries and replaced active links.
User-facing `locate` also supports saved skills and current catalog source lookup for uninstalled content or explicit `--source` requests.
Keep callbacks on saved instruction lookup only; never fall back from a broken saved installation to a different source.
Source lookup validates paths and Git identity without requiring a clean checkout, fetching, or installing content.
Keep copy/detached locations distinct from source editing paths so publication never implies collecting installed-copy edits.
Use an absolute interpreter for hook execution, quote POSIX arguments, and explicitly encode a PowerShell command on Windows without evaluating user paths.
Instruction callbacks emit only path metadata, never document contents. Codex uses
additionalContext and a structured stop; Claude uses plain stdout and stderr with
exit 2 on failure, which does not stop SessionStart.
Instruction callbacks wait at most 5 seconds total for the installation and configuration locks within their 10-second hook limit, then read configuration and state under the acquired lock; other commands retain immediate contention failure.
Limit callback metadata to the effective `root`, `entry`, and `global_entry` reading locations.
Explain their correspondence without assuming the entry's contents have already been loaded or requesting a redundant read when they have.
Resolve entry-relative references from its parent directory and supplemental references from the referring document's directory, unless the user documents explicitly specify another base.
Do not infer applicability or reading order from bundle placement or the entry filename.
Keep `installed_root` and `detached` in locator diagnostics so a preserved copy cannot be mistaken for the live entry's source tree.
Preserve original documents and use the existing per-target conflict/recovery machinery.
Guard the saved entry path of active Git bundles even when their catalog declarations disappear or a shared skill initiates update.
Instruction-specific automatic policies are not supported; skill policies may still advance shared checkouts.
Explicit full device automation may prepare/update/apply instruction bundles, excluding an agent group if any of its saved components is detached.

## Catalog delivery contracts

Preserve compatibility for local catalog path strings, and keep Git bindings in machine configuration.
Bootstrap accepts the catalog repository, relative entry path, and optional branch without requiring a hand-written machine file; persist the resolved branch for subsequent operations.
Catalog delivery precedes content delivery and must not depend on declarations inside the catalog itself.
Use a separate checkout even when catalog and content share a remote, so content updates cannot implicitly change the inventory or automatic policies.
Do not merge checkout identities by URL.

Preparing a missing Git catalog checkout is the explicit exception to declaration validation before network access.
Clone it to temporary storage, then validate its tracked regular UTF-8 entry, declarations, machine bindings, and existing ownership before publishing the checkout or saving the binding.
Content repositories must remain untouched until preflight succeeds.
Validate candidate revisions against final machine paths without temporarily changing the active binding or checkout.
Catalog updates fast-forward only after the candidate passes the same declaration and ownership checks.
Preserve the old catalog on validation failure, local edits on delivery failure, and installed ownership when declarations disappear.
Do not reset mismatching checkouts on rebind.

Explicit catalog update/publication and separately opted-in catalog automation may contact an existing catalog's remote.
Keep catalog automation policy in machine configuration, outside the file it updates.
Default to manual, and require a Git binding when automation is enabled.
Expose trigger/interval/timeout selection through bootstrap and setup, preserving omitted fields and replacing explicitly supplied trigger lists.
Validate supplied policies before network access or saving configuration.
Policy-only setup must use the machine configuration journal without requiring an executable, registering integrations, or rewriting profiles.
Use the same candidate validation and fast-forward safeguards as explicit catalog update, without bootstrapping or applying declarations.
Persist a separate attempt clock before remote access, throttle failed attempts across events, and reset the effective clock on a changed repository/branch/entry binding.
Explicit catalog operations ignore this clock, and automatic previews remain offline without recording attempts.
In `policies` mode, startup must run due catalog work before resolving skill policies and reload successfully updated declarations.
A failed catalog attempt must skip skill work for that event while allowing startup to continue.
Ordinary content update, sync, skill automatic policies, and refreshed content status must not fetch or advance the catalog.
Keep catalog inspection/location offline and usable for repairing malformed catalog contents, and retain catalog-independent maintenance paths.
Catalog publication selects the whole repository and follows the existing publication contracts; it never installs declarations or changes content attempt clocks.
Keep catalog delivery observations separate from item/source names and protect the whole catalog checkout from targets and external sources.
Verify registration, saved-binding reuse, update/bootstrap/apply and locate/edit/publish workflows, invalid incoming catalogs, ownership conflicts, offline maintenance, local edits, and remote failures with local Git fixtures.

## Publication contracts

Explicit `publish` selects catalog skill, instruction bundle, or setting names and groups them by existing checkout identity.
Report all catalog consumers of each selected checkout.
Do not infer per-skill file ownership for publication: commit and push operate on the whole repository, including changes outside catalog subdirectories.
A supplied message authorizes staging all nonignored changes; without it, require a clean worktree and publish existing commits only.
Keep preview offline and preserve the index, HEAD, installation records, and automatic-policy attempt clocks.
Verify all advertised remote refs before staging or settings export.
Only a successful empty listing permits initial publication without a remote branch; a populated remote must contain the registered branch and be fetched before staging.
Never reinterpret authentication, transport, listing, or fetch failures as an empty remote.
Refuse behind/diverged histories without rewriting or merging them.
Push only the registered branch to the registered origin, without force or implicit additional refs.
Preserve staged changes and commits after failures, report each repository's outcome independently, and never claim atomicity across repositories.
External synchronization, fork/PR workflows, and collecting installed-copy edits are outside this command's scope.
Exercise shared skill/instruction consumers, unrelated files, existing commits, offline preview, rejected histories, remote failure, and retry using local Git fixtures.

Self publication is a separate prepared-release contract: require a clean AEM checkout and an existing version tag resolving to HEAD, and never generate commits, tags, or version edits.
Resolve its default checkout from local installation provenance or the running module's own development tree, never by searching the current directory or user homes; invalid recorded paths require explicit correction.
Keep it independent of machine/catalog state and self-update scheduling.
Use the checkout's origin and current branch, validate remote history and existing tag targets, and atomically publish only the reviewed branch commit and missing release tag.
Preserve equivalent existing remote tag objects, local release contents, and ordinary content/catalog publication contracts; do not fall back to sequential push or force.

## Automatic update contracts

Resolve policies by explicit field override: built-in defaults, catalog-wide defaults, one named policy, then skill-local fields.
Catalog trigger arrays replace earlier arrays; `[]` disables all automatic events for the skill.
Keep the existing `["manual"]` sentinel in effective policy JSON and the existing machine policy syntax.
Validate all policy declarations, including unused named policies, before network access.
Keep common trigger/action/interval settings separate from source-specific delivery options; reject unsupported capabilities rather than substituting another action.

External callers supply `shell-start`, `agent-start`, or `interval` events to `auto`.
Policy configuration does not install hooks, modify shell profiles, register OS tasks, or imply an in-process scheduler.
Ordinary `apply`, `status`, and `bootstrap` must not perform implicit automatic updates.
Explicit commands retain their existing contracts and ignore automatic policy throttles.

Under the existing configuration lock, persist each skill's attempt before network access and throttle failures as well as successes across all its events.
Preview must not fetch or record attempts.
Automatic sync applies each successfully updated skill independently.
Explicit sync instead requires all updates to succeed before applying.
Preserve existing per-target transactions, stop if recovery is pending, and never adopt, replace conflicts, or reattach detached skills automatically.
Skill automatic policies cover catalog skills; settings schedules remain independent, and explicit sync is unthrottled.

## Device orchestration contracts

Default to `policies` so existing installations retain independent automatic behavior.
Expose `off`/`policies`/`full` and full trigger/interval/timeout options in installer/setup, preserving omitted fields and supporting configuration-only journaled edits.
`off` disables automatic events; explicit maintenance and update commands remain available.
Full mode owns one persisted attempt clock across events and failures; do not consult or modify individual automatic clocks during its stages.
Reject individual skill/catalog event entrypoints in full mode to avoid duplicating the unified schedule.
Queue full runs through the existing external standard-library worker after the requesting process exits, including when tool updates are off.
Apply the saved tool release permission first, then invoke the freshly installed CLI before catalog/content work; never import the replacing package into the external worker.
Release installation/configuration locks before invoking the fresh CLI, and validate mode/runtime binding and a one-use token under its locks.
Cancel queued work when automation settings change, and cancel queued individual tool updates when switching to `off` or `full`.
Validate and fast-forward the catalog before loading full content selection; skip transport for local/unbound catalogs.
Full mode opts in otherwise unconfigured skills but preserves explicit or inherited empty-trigger exclusions using the existing precedence.
Prepare/update eligible sources before applying selected items, with no adoption, replacement, reattachment, deletion, publication, or hook trust granting.
Keep shared-checkout validation and live-link side effects intact, including excluded consumers; document this boundary.
Stop later stages on failure without claiming cross-repository rollback; preserve ordinary per-target journals and recovery.
Test actual fresh-CLI continuation, stage ordering, new declarations, exclusions, throttling, cancellation, lock handoff, and failure gates using local fixtures and fake installers.

## Ownership and safety

Only declared catalog skills and instruction bundles, and the package-owned official integration skill, may be installed.
A content repository update cannot expand the local catalog.
Catalog skill names identify ownership independently of repository URLs and paths.
Instruction ownership uses the bundle name and bundle/entry/hook component.
Do not infer ownership from an existing file or delete targets when declarations disappear.
Reject overlapping target trees and require detach before changing an existing item's path or mode.
A directory item owns its entire subtree, so extra local files are meaningful modifications.
Repository-root skills are valid and use direct links, not an extra content layer.
Exclude only their top-level `.git` administration entry from content fingerprints, copies, and detach materialization.
Never duplicate a repository database or worktree pointer into an unmanaged skill.
Git identity checks still validate the managed checkout's origin and expected branch before applying or updating.

Link and copy have different contracts.
Never silently fall back from link to copy.
Copy conflict detection uses the last applied content, desired content, and actual target; Git revision alone is insufficient.

Prepare and verify a replacement before moving the current target.
Write the recovery journal before the first rename and commit the ownership record only after installation succeeds.
Keep target backups; cleanup must never remove user changes discovered during recovery.
The process lock serializes commands for one configuration, not arbitrary editors or Git processes.
Retain the documented per-target transaction boundary instead of claiming global atomicity.

Detach preserves the current usable contents, then releases ownership and records a tombstone to prevent automatic reinstallation.
It does not restore pre-installation contents.
Do not discard state when a target is missing, unreadable, or cannot be safely materialized.

## Validation expectations

Changes to delivery must exercise clone, fast-forward, dirty/divergent histories, network/remote failures, and live-link removal guards using local Git fixtures.
Catalog tests must start with repositories lacking links.conf, exercise root and nested skills, and keep the inventory independent of both checkouts and installation roots.
Verify that missing inventory files do not prevent status from observing installed contents or detach from preserving them.
Changes to installation must exercise unmanaged targets, local edits, directory contents, unrelated hook preservation, detach, and failure recovery.
Policy changes must cover precedence, empty-trigger opt-out, event selection, offline preview/check-only behavior, per-skill throttling including failures, independent outcomes, and preservation of local edits and detached skills.
Test meaningful user-visible behavior and preservation boundaries rather than mirroring private implementation functions.
When adding or changing a workflow that connects multiple commands, verify that each command's outputs and selected scope match the next command's inputs and actual operation targets.
Where source content and installed content can differ, cover link, copy, and detached states and verify which content an edit changes and which content the subsequent command consumes.
Keep [Configuration](docs/configuration.md) and [Commands](docs/commands.md) authoritative for TOML fields and CLI contracts.
Keep the README focused on user workflows and link to those references.
Installation and update paths must reject unknown fields and invalid types instead of silently accepting misspelled or removed settings.
Update examples and platform limitations with interface changes.
Agent profiles are the internal extension boundary for paths, hook syntax, callback output, and notices.
Do not add a dynamic plugin loader or additional source providers without a demonstrated use case.

## CLI help scope

CLI help is the installed, version-matched entry point for choosing and invoking commands.
Explain the target being read or changed, selection identifiers and scope, omitted-option behavior, and non-obvious prerequisites or option incompatibilities when these affect correct use.
For workflows spanning multiple commands, make clear which phase a selector filters and which content each command consumes, such as a source, editable stage, or actual application file.
Describe consequential defaults and preview limits concisely enough to choose the operation without reading a full guide.

Keep help focused on invocation decisions; retain full schemas, output contracts, detailed recovery procedures, and extended examples in the authoritative documentation.
Do not reproduce a manual in command help or compensate for missing help by copying syntax and procedures into the official skill.
When removing operational detail from the skill in favor of CLI discovery, verify that the relevant help actually supplies the information needed for the task.
A repository-local document is not necessarily available in an installed package; only advertise local documentation entry points that the installation provides.
Help must remain available without valid machine configuration, loading catalogs, acquiring locks, or running operations.
For help changes, inspect rendered command output and verify this boundary; avoid tests that lock down exact prose.

## Installed documentation

Ship `README.md`, `docs/`, `examples/`, and `LICENSE.txt` as version-matched local package resources, preserving their repository-relative directory structure.
`aem docs` identifies the local README and documentation root without reading machine configuration, acquiring locks, fetching, or requiring an agent/shell integration.
Package installation provides these resources; setup only connects integrations and does not download documentation.
Keep canonical sources at the repository root and copy them unchanged during builds; do not maintain a second authored copy or rewrite Markdown links at build time.
The documentation copy of LICENSE.txt and the packaging-standard metadata license must both come from the same source file; do not add installation-time symlinks.

Exclude CONTRIBUTING.md and CHANGELOG.md from installed documentation resources.
Links to contribution instructions and release history use repository web URLs as optional references, not required paths for ordinary tool use.
User-facing compatibility policy lives in [Compatibility](docs/compatibility.md); both contributor guidance and user documentation reference this single policy.
Use relative links among bundled documents and examples so they work in a checkout and an installation.
Build hooks must resolve from the configured source layout without relying on the caller's Python module search path.
Verify isolated wheel builds, wheel contents, wheel builds from the sdist, installed local lookup, and local link/anchor resolution when changing packaging or documentation structure.

## Official skill guidance

The packaged [idk-aem skill](skills/idk-aem/SKILL.md) should help agents choose and carry out AEM operations, with emphasis on important behavior, sequencing, and non-obvious consequences.
Organize the skill by the user's intended task, with enough basic commands and sequencing to carry out ordinary workflows directly.
Do not lead with command inventories or require interface discovery before every operation.
Keep exhaustive options, configuration schemas, and detailed procedures in installed CLI help and authoritative local documentation.
When a workflow leaves a decision unresolved, consult the relevant installed command help first, then the matching local documentation only if help is insufficient.
Give agents concrete local entry points, explain when to consult them, and reuse already verified guidance until the runtime changes or an incompatibility appears.
Use documentation paths only when they resolve in the installed environment; do not rely on repository-relative paths to unbundled files or web links that require fetching documentation.
Use the local help and documentation provided by the installation.
Treat missing or incomplete advertised materials as an installation or documentation issue; do not add fallback instructions to the skill.
Keep essential guidance inline when it prevents a material mistake, rather than making ordinary use depend on loading an entire manual.
Do not move duplicated manuals into skill references merely to shorten the entrypoint.

Retain distinctions that affect the requested outcome, such as preparation versus installation, source versus installed copy, live-link update effects, settings stages versus actual files, repository-wide publication, and preservation during recovery.
The skill must not impose content-authoring policies or infer publication authorization from an editing request.
When changing user-facing commands, options, configuration, or workflows, review the skill's guidance and documentation entry points in the same change.
Update the skill when its decision guidance or discovery route changes; a new option or documentation detail alone does not require copying it into the skill.
Verify that referenced documentation is available and retained guidance agrees with the actual command behavior.

## Machine setup and agent integration

The repository installer uses uv to install this checkout as a user tool, then delegates integration to `aem setup`.
Offer `off`, `compatible`, and `breaking` self-update modes on first interactive installation; unattended omission defaults to off, and omitted choices preserve saved settings.
Self-update policy and the external installer runtime belong to machine configuration, never the content catalog.
Release selection accepts newer final, Python `a`/`b`/`rc`, or SemVer-style `-alpha`/`-beta`/`-rc` prerelease tags with optional `.N` numbers.
Convert SemVer pre labels to Python package notation before ordering or metadata comparison; an omitted pre number is zero.
Prefer exact package tags during self publication and Python tags during update selection when equivalent aliases coexist; never bypass a mismatched exact tag with an alias.
Final compatible updates select final releases only, preserving same-major compatibility from 1.x.
Prerelease compatible updates require the same base version and pre label and increase only the numeric subversion; label/base changes and graduation to final require breaking permission.
Pre numbers may be omitted and mean zero; do not require earlier pre phases to exist.
Keep parsing and ordering standard-library-only for the copied worker; exclude development, post, and local versions.
Validate package identity and tag/version agreement before installation, and pin the selected commit.
Do not advance or publish the development checkout as a self-update side effect.
The standalone worker must remain standard-library-only, run on a Python outside the replaced tool environment, and wait for its requesting AEM process to exit.
Copy worker code into a distinct request directory before launching; never depend on package files surviving replacement.
Registered commands and workers must acquire the shared installation lock before their configuration lock.
This order also applies across machine files that share one uv tools directory.
Recheck saved policy, recovery state, request identity, and actual installed version before replacement.
Persist attempts before launch, throttle failures across startup events, keep previews offline and read-only, and distinguish queued work from completed updates.
Keep self commands independent of content declarations; ordinary content operations and instruction location callbacks must not schedule self-updates.
Keep removal-only setup independent of runtime registration and policy edits.
Exercise release boundaries, annotated tags, metadata mismatches, policy cancellation, contention, failure/retry, and worker lifetime with local repositories and fake uv processes.
Package-manager rollback and real Windows replacement require separate evidence before strengthening their documented guarantees.
Keep the installer standard-library-only; configuration and ownership logic belong in the package.
Setup owns machine selection, startup registration, and official skill links, while bootstrap prepares catalog content and apply installs it.
Agent integration includes the startup hook and an ancillary link to the packaged official skill at the selected skills root.
Complete and persist core setup integrations before attempting optional skill installation or removal.
Report skill outcomes separately in `official_skills`, preserving the core `integrations` results and successful exit status.
Preflight ancillary skills independently per agent, preserve conflicting targets, and permit explicit setup retries after resolving their cause.
Do not suppress unresolved recovery journals or shared-state errors; the worker's strict refresh and pre-replacement edit guard remain independent of best-effort setup.
Keep official skill ownership under setup, independently of catalog declarations and content policies.
The package resource mapping in `pyproject.toml` must include the root-level skill in both wheel and sdist; update explicit package registration when adding a Python package.
Self-update validates recorded links and source edits before replacement, then releases locks before invoking the fresh CLI to refresh official links.
Refresh only active owned official integrations; a failed or uninstalled ancillary integration must not become a prerequisite for existing update workflows.
The continuation must validate its request token and saved policy binding and run at most once.
Keep package replacement outcomes separate from official link refresh outcomes; full automation stops if link refresh fails.
Older saved source hashes may differ after another configuration or an external installer replaces the package; compare payloads only for the recorded package version.
Catalog update policies must never register hooks implicitly.

Selections accumulate, and repeated setup must preserve unrelated content and avoid duplicate groups or blocks.
Preflight all core profile edits before changing any of them, and commit each target through the existing recovery journal.
Save machine selection after core target transactions and before ancillary skill attempts.
A retry must recognize completed ownership records after a partial failure.
Setup removal must not delete user content or silently detach installed skills and instructions.
Official integration removal deletes only unchanged owned links, preserving their package sources and transaction backups.
Store official removal backups under the machine state directory's `setup-backups`, outside agent discovery roots; sibling link backups would remain discoverable skills.
Reject official skills roots containing machine state storage, and preserve link identity without requiring renames across filesystems during removal or restoration.
Recovery permits this backup location only for recorded official link removal with a missing post-transaction target, retaining sibling-path validation for ordinary replacements.
Changed official links, edited sources, and substituted copies are preserved and released from setup ownership, with their paths reported.
A setup invocation containing only removals must touch only requested saved integrations, without rebuilding remaining integrations or consulting current profile defaults.
Use saved shell blocks and hook groups, including retired integration names; ignore an executable override on removal-only calls.
Preflight selected removals and machine-document edits before writing, detect concurrent edits, group removals sharing a hook file, and retain the same journal/retry boundaries as setup installation.
Do not grant agent hook trust or rewrite user execution policies.

Resolve product-specific defaults, hook serialization, and callback output through internal agent profiles.
Codex and Claude Code are shipped profiles. Keep product syntax in internal profiles
and delivery/ownership in the shared manager. Validate future extension with fake
profiles without claiming third-product support. See [profile contracts](docs/agent-profiles.md).
Generate instruction callbacks through agent-hook NAME --agent AGENT and the internal profile.
Store per-target ownership and shared consumers independently from per-skill Git delivery and automatic attempt clocks.
A shared target has one owner and cannot be materialized for just one of its consumers.
Explicit catalog roots retain their meaning; omitted destinations use selected agent defaults.

During development, switch `STARTUP_BRIEFING_OUTPUT` in `src/agent_env_man/agents.py` between `"systemMessage"` (UI warning) and `"additionalContext"` (model context) to try both startup briefing behaviors.
For a regular uv tool installation, reinstall the updated checkout before testing the installed hook.

Test setup with temporary homes and fake installer subprocesses, never actual user profiles or live remote repositories.
Exercise repeat/add/remove, edited blocks, invalid hook files, redirected paths, grouped hook writes, partial failure/retry, offline previews, and fail-open startup.
Shell quoting and PowerShell serialization tests do not establish native shell or Windows readiness.

## Staged settings architecture

Keep settings transport, editable stages, and actual application files distinct.
Collection, export, and publication require explicit operations.
Settings have independent per-item automatic schedules; never inherit skill defaults or named policies.
Automatic settings work always receives shared changes and then applies the stage, stopping application on reception failure or conflicts.
Full device automation includes settings by default, preserving explicit empty-trigger exclusions and detached items, and uses the shared full-run clock.
A shared checkout update by another consumer may change the source but must not activate or rewrite an unselected settings stage.
Automatic settings application retains the ordinary field conflict checks and must never replace local edits or reattach detached items.

Keep format parsing, value identity, field enumeration, and preserving edits behind the format adapter.
Do not use TOML parser nodes as persisted ownership values or expose them in CLI reports.
Shared intent metadata is an AEM contract, independent of the supported application format.
Support TOML and strict JSON objects, treat arrays and empty tables/objects as atomic values, and permit one owner per target file.
JSON numbers compare by exact numeric value regardless of spelling, with booleans kept distinct; preserve numeric tokens without conversion through binary floats.
Keep JSON edits local to changed values and required punctuation, preserving untouched tokens and returning unchanged documents verbatim.
Reject duplicate JSON keys, comments, trailing commas, and nonstandard numeric constants.
Distinguish format-specific empty document construction from parsing an existing file; an existing empty JSON file is invalid.

Editable stages never replace trusted shared/apply comparison bases.
Deletion, ownership release, and local detach have distinct semantics; preserve intent records for newly connected and offline devices.
Preflight grouped settings/metadata writes before mutation and commit comparison records with their journal.
Recovery must validate the complete group before rollback and remain compatible with existing single-target journals.
Reuse existing whole-checkout publication and Git safety rules; field merging never reconciles Git history.
