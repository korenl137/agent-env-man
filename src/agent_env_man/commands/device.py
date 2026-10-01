"""Machine setup, device automation, and installed callback commands."""

from types import SimpleNamespace

import click

from .. import automation as device_automation, self_update
from ..agents import profile
from ..cli_runtime import (pass_runtime, agent_option, preview_option, catalog_policy_options,
                           identifier_value, AGENT, SECONDS, INTERVAL, OPERATION_ERRORS)
from ..git_source import now
from ..setup import setup as configure, remove_integrations
from ..updates import TRIGGERS, startup_briefing


@click.command()
@click.option("--shell", multiple=True, type=click.Choice(("bash", "zsh", "powershell")), help="Connect a shell; repeat to select more.")
@click.option("--agent", multiple=True, type=AGENT, help="Connect an agent; repeat to select more.")
@click.option("--remove-shell", multiple=True, callback=identifier_value, metavar="NAME", help="Remove a saved shell integration, including retired names.")
@click.option("--remove-agent", multiple=True, callback=identifier_value, metavar="NAME", help="Remove a saved agent integration, including retired names.")
@click.option("--executable", help="Absolute installed AEM executable.")
@click.option("--self-update", type=click.Choice(("off", "compatible", "breaking")))
@click.option("--update-repository", help="AEM release repository.")
@click.option("--update-python", help="External Python used by the update worker.")
@click.option("--update-uv", help="External uv executable.")
@click.option("--update-tool-dir", help="uv tools directory.")
@click.option("--update-bin-dir", help="uv executable directory.")
@click.option("--automation", type=click.Choice(device_automation.MODES))
@click.option("--automation-trigger", multiple=True, type=click.Choice(("manual", *TRIGGERS)), help="Replace device triggers; repeat for multiple events.")
@click.option("--automation-interval", type=INTERVAL, help="Minimum seconds between device attempts.")
@click.option("--automation-timeout", type=SECONDS, help="Seconds per Git phase in device automation.")
@catalog_policy_options
@preview_option
@pass_runtime
def setup(runtime, **options):
    """Configure machine policies and integrations, including the official skill."""
    # Core setup accepts lists and distinguishes omitted policies from supplied
    # replacement lists. Click's empty multiple values must retain that distinction.
    for key in ("shell", "agent", "remove_shell", "remove_agent"):
        options[key] = list(options[key])
    for key in ("automation_trigger", "catalog_trigger"):
        options[key] = list(options[key]) or None
    args = SimpleNamespace(**options)
    remove_only = bool((args.remove_shell or args.remove_agent)
                       and not (args.shell or args.agent or args.self_update is not None
                                or args.catalog_trigger is not None or args.catalog_interval is not None or args.catalog_timeout is not None
                                or any(getattr(args, option) is not None for _, option in device_automation.FIELDS)
                                or any(getattr(args, "update_" + field) for field in ("repository", "python", "uv", "tool_dir", "bin_dir"))))
    def operation(session):
        report = remove_integrations(session.manager, args) if remove_only else configure(session.manager, args)
        return report, False
    return runtime.run(operation, maintenance=remove_only, missing_ok=True, preview=args.dry_run)


@click.group(name="self")
def self_group():
    """Inspect or queue release updates of AEM itself."""


@click.command(name='_self-skill-refresh', hidden=True)
@click.option('--token', required=True)
@click.option('--result-file', required=True, type=click.Choice(('self-update.json', 'automation.json')))
@pass_runtime
def self_skill_refresh(runtime, token, result_file):
    """Worker continuation: repair official links using the newly installed CLI."""
    from ..setup import refresh_official
    from ..model import Error
    def operation(session):
        result = session.config.state_dir / result_file
        saved = self_update.read_result(result)
        expected_status = 'continuing' if result_file == 'automation.json' else 'queued'
        if (saved.get('token') != token or saved.get('status') != expected_status
                or saved.get('skill_refreshed') or saved.get('skill_binding') != self_update.full_binding(session.config.doc)):
            raise Error('No matching official skill continuation')
        report = refresh_official(session.manager, replaced=saved.get('stages', {}).get('tool', {}).get('status') == 'updated')
        self_update.write_json(result, {**saved, 'skill_refreshed': True})
        return report, False
    return runtime.run(operation)


@self_group.command(name="status")
@pass_runtime
def self_status(runtime):
    """Inspect the installed version, update mode, and last attempt."""
    return runtime.run(lambda session: (self_update.status(session.config), False), maintenance=True, missing_ok=True)


@self_group.command(name="update")
@click.option("--mode", type=click.Choice(("compatible", "breaking")), help="Override the release range for this attempt.")
@preview_option
@pass_runtime
def self_update_command(runtime, mode, dry_run):
    """Queue a release update after this command exits."""
    def operation(session):
        self_update.validate(session.config.doc.get("self_update", {}))
        session.state.ready()
        selected_mode = mode or session.config.doc.get("self_update", {}).get("mode", "off")
        return self_update.schedule(session.config, mode="compatible" if selected_mode == "off" else selected_mode,
                                    dry_run=dry_run), False
    return runtime.run(operation, maintenance=True, missing_ok=True, preview=dry_run)


@click.command(name="automation")
@click.option("--trigger", required=True, type=click.Choice(TRIGGERS), help="External event to process.")
@preview_option
@pass_runtime
def automation_command(runtime, trigger, dry_run):
    """Run or preview the selected device automation mode."""
    def operation(session):
        report = device_automation.run(session.manager, trigger, dry_run=dry_run)
        return report, report.get("failed", False)
    return runtime.run(operation, missing_ok=True, preview=dry_run)


@click.command()
@click.option("--trigger", required=True, type=click.Choice(TRIGGERS), help="Startup event to process.")
@agent_option
@pass_runtime
def startup(runtime, trigger, agent):
    """Fail-open startup callback with machine-readable output."""
    def operation(session):
        try:
            result = device_automation.run(session.manager, trigger)
        except OPERATION_ERRORS as exc:
            result = {"status": "failed", "failed": True, "error": str(exc), "outcomes": []}
        session.state.data["startup"] = {"trigger": trigger, "time": now(), **result}
        session.state.save()
        report = profile(agent).startup_result(startup_briefing(result.get("outcomes", []))) if agent else {}
        return report, False
    return runtime.run(operation, missing_ok=True, callback="startup", agent=agent)


@click.command(name="agent-hook")
@click.argument("name")
@click.option("--agent", required=True, type=AGENT)
@pass_runtime
def agent_hook(runtime, name, agent):
    """Emit agent-specific saved instruction location context."""
    return runtime.run(lambda session: (session.manager.hook_context(name, agent), False),
                       maintenance=True, callback="agent-hook", agent=agent)


@click.command(name="_full-run", hidden=True)
@click.option("--token", required=True)
@pass_runtime
def full_run(runtime, token):
    """Continue a queued full run from a fresh installed CLI."""
    return runtime.run(lambda session: device_automation.complete(session.manager, token), callback="_full-run")
