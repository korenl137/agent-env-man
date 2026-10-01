"""Explicit commands for the bound catalog, independent of its content."""

from types import SimpleNamespace

import click

from .. import catalog as delivery
from ..cli_runtime import pass_runtime, timeout_option, preview_option
from ..updates import TRIGGERS


@click.group()
def catalog():
    """Inspect, update, or publish the bound catalog."""


def run(runtime, action, **options):
    args = SimpleNamespace(catalog_command=action, **options)
    return runtime.run(lambda session: delivery.command(session.config, session.state, args))


@catalog.command()
@timeout_option
@pass_runtime
def status(runtime, timeout):
    """Inspect the catalog and its checkout offline."""
    return run(runtime, "status", timeout=timeout)


@catalog.command()
@timeout_option
@pass_runtime
def locate(runtime, timeout):
    """Locate the bound catalog entry offline."""
    return run(runtime, "locate", timeout=timeout)


@catalog.command()
@timeout_option
@pass_runtime
def update(runtime, timeout):
    """Validate and fast-forward the catalog without installing content."""
    return run(runtime, "update", timeout=timeout)


@catalog.command()
@click.option("-m", "--message", help="Commit all nonignored catalog checkout changes.")
@preview_option
@timeout_option
@pass_runtime
def publish(runtime, message, dry_run, timeout):
    """Publish the whole catalog repository."""
    return run(runtime, "publish", message=message, dry_run=dry_run, timeout=timeout)


@catalog.command()
@click.option("--trigger", required=True, type=click.Choice(TRIGGERS), help="External event to process.")
@preview_option
@pass_runtime
def auto(runtime, trigger, dry_run):
    """Run due catalog policy work for an external event."""
    return run(runtime, "auto", trigger=trigger, dry_run=dry_run)
