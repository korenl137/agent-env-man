"""Locate version-matched local documentation without machine state or locks."""

from pathlib import Path

import click

from ..cli_runtime import pass_runtime


def location():
    """Return the installed documentation root, or canonical development tree.

    Source lookup is limited to this module's own src checkout, including an
    editable install; it never searches the working directory or user homes.
    """
    module = Path(__file__).resolve()
    root = module.parent.parent / "_documentation"
    if not (root / "README.md").is_file():
        checkout = module.parents[3]
        if (checkout / "src" / "agent_env_man" / "commands" / module.name == module
                and (checkout / "pyproject.toml").is_file()):
            root = checkout
    entry = root / "README.md"
    if not entry.is_file():
        raise click.ClickException("Local documentation is missing from the AEM installation")
    return {"root": str(root), "entry": str(entry)}


@click.command()
@pass_runtime
def docs(runtime):
    """Locate the installed README, detailed docs, examples, and license offline.

    Print the absolute README path; global --json returns root and entry paths.
    No machine configuration, catalog, or setup integration is required.
    """
    report = location()
    if runtime.json_output:
        runtime.emit(report)
    else:
        click.echo(report["entry"])
