"""Explicit version promotion and fresh reviewed reuse; no execution command."""
import typer

from .catalog import VersionCatalog
from .contracts import json_object
from .review import ReviewStore
from .review_cli import _errors, _print_json

app = typer.Typer(no_args_is_help=True, help='Immutable validated versions; reuse always requires a fresh review.')


@app.callback()
def options(ctx: typer.Context,
            store: str = typer.Option('.mcp/versions.sqlite3', help='Private version catalog, separate from legacy tools.'),
            review_store: str = typer.Option('.mcp/reviews.sqlite3', help='Review journal for promotion or new drafts.')):
    ctx.obj = {'store': store, 'reviews': review_store}


@app.command('promote')
def promote_command(ctx: typer.Context, proposal_id: str,
                    yes: bool = typer.Option(False, '--yes', help='Explicitly preserve this validated proposal as an immutable version.')):
    """Save a completed, output-validated proposal. Does not execute or approve reuse."""
    with _errors():
        if not yes:
            typer.confirm('Preserve this validated proposal as an immutable version?', default=False, abort=True)
        reviews = ReviewStore(ctx.obj['reviews'], read_only=True)
        catalog = VersionCatalog(ctx.obj['store'])
        _print_json(catalog.promote(reviews, proposal_id, confirm=True))


@app.command('list')
def list_command(ctx: typer.Context, name: str = typer.Option(None),
                 limit: int = typer.Option(20, min=1, max=100), before: int = typer.Option(None, min=1)):
    """List version identities only, newest first. No latest-version execution alias."""
    with _errors():
        _print_json(VersionCatalog(ctx.obj['store'], read_only=True).list(name=name, limit=limit, before=before))


@app.command('inspect')
def inspect_command(ctx: typer.Context, name: str, version: str):
    """Read a complete saved snapshot/provenance. Not execution authorization."""
    with _errors():
        _print_json(VersionCatalog(ctx.obj['store'], read_only=True).inspect(name, version))


@app.command('prepare')
def prepare_command(ctx: typer.Context, name: str, version: str,
                    args: str = typer.Option(None, help='New JSON arguments, only together with a new output contract.'),
                    output_contract: str = typer.Option(None, help='New independent expected output, only together with new arguments.')):
    """Create a new pending proposal from an explicit version; never execute it."""
    with _errors():
        arguments = json_object(args) if args is not None else None
        contract = json_object(output_contract) if output_contract is not None else None
        catalog = VersionCatalog(ctx.obj['store'], read_only=True)
        reviews = ReviewStore(ctx.obj['reviews'])
        _print_json(catalog.prepare(name, version, reviews, args=arguments, output_contract=contract))


@app.command('retire')
def retire_command(ctx: typer.Context, name: str, version: str,
                   apply: bool = typer.Option(False, '--apply', help='Apply the inspected retirement plan.'),
                   plan_digest: str = typer.Option(None, help='Exact digest returned by the preview.'),
                   yes: bool = typer.Option(False, '--yes', help='Confirm permanent retirement, retaining history.')):
    """Preview disabling future preparations. Existing proposals are unaffected."""
    with _errors():
        preview = VersionCatalog(ctx.obj['store'], read_only=True).retire(name, version)
        if not apply:
            if yes or plan_digest is not None:
                raise ValueError('apply_required_for_confirmation')
            _print_json(preview)
            return
        if plan_digest != preview['plan_digest']:
            raise ValueError('reviewed_retirement_plan_required')
        if not yes:
            typer.confirm('Permanently retire this version while retaining its history?', default=False, abort=True)
        _print_json(VersionCatalog(ctx.obj['store']).retire(name, version, plan_digest=plan_digest, confirm=True))
