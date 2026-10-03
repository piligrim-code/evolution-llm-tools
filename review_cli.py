"""Opt-in reviewed lifecycle; legacy commands retain their existing semantics."""
from contextlib import contextmanager
import json
import sqlite3

import typer
from rich.console import Console

from .container_runner import ContainerError, ContainerPolicy, _display_text
from .contracts import json_object
from .llm import OllamaError
from .review import ReviewStore, propose
from .outcomes import ExecutionStatus

app = typer.Typer(no_args_is_help=True, help="Review a draft before one contained execution attempt.")
console = Console()


@contextmanager
def _errors():
    try:
        yield
    except (ValueError, PermissionError, OSError, sqlite3.Error, ContainerError, OllamaError) as error:
        console.print(_display_text(str(error).encode("utf-8")), markup=False, highlight=False)
        raise typer.Exit(code=2) from None


def _print_json(data):
    console.print(json.dumps(data, ensure_ascii=True, indent=2), markup=False, highlight=False, soft_wrap=True)


@app.callback()
def review_options(ctx: typer.Context, store: str = typer.Option(".mcp/reviews.sqlite3", help="Private local review database.")):
    ctx.obj = store


@app.command("propose")
def propose_command(ctx: typer.Context, question: str,
                    container_image: str = typer.Option(..., help="Trusted local immutable sha256 image ID."),
                    name: str = typer.Option("reviewed_tool"),
                    model: str = typer.Option(None, help="Override Ollama model for drafting only."),
                    args: str = typer.Option(None, help="Exact JSON arguments; otherwise use the question text."),
                    output_contract: str = typer.Option(None, help="JSON assertion with kind and expected; supplied by the reviewer, not the model."),
                    timeout: float = typer.Option(10, min=1, max=60)):
    """Ask Ollama for a draft. No Docker call, execution or working-tool registration."""
    with _errors():
        policy = ContainerPolicy(container_image, timeout)
        arguments = json_object(args) if args is not None else None
        store = ReviewStore(ctx.obj)
        contract = json_object(output_contract) if output_contract is not None else None
        identifier = propose(question, name, policy, store, args=arguments, model=model, output_contract=contract)
        record = store.inspect(identifier)
        _print_json({key: record[key] for key in ("id", "digest", "state")})


@app.command("inspect")
def inspect_command(ctx: typer.Context, proposal_id: str,
                    as_json: bool = typer.Option(False, "--json", help="Show the complete escaped JSON record.")):
    """Show the code, contract, exact arguments, policy and approval digest."""
    with _errors():
        record = ReviewStore(ctx.obj, read_only=True).inspect(proposal_id)
        if as_json:
            _print_json(record)
        else:
            scripts = record["document"].pop("scripts")
            _print_json(record)
            for filename, source in scripts.items():
                console.rule(filename)
                console.print(_display_text(source.encode("utf-8")), markup=False, highlight=False, soft_wrap=True)


@app.command("list")
def list_command(ctx: typer.Context,
                 state: str = typer.Option(None, help="Filter: pending, approved, claimed, finished or cancelled."),
                 limit: int = typer.Option(20, min=1, max=100),
                 before: str = typer.Option(None, help="next_cursor from the preceding page with the same filter.")):
    """Find proposal IDs without exposing code, arguments or output. No execution."""
    with _errors():
        _print_json(ReviewStore(ctx.obj, read_only=True).list(state=state, limit=limit, before=before))


@app.command("approve")
def approve_command(ctx: typer.Context, proposal_id: str,
                    digest: str = typer.Option(..., help="Digest from the exact proposal you inspected."),
                    yes: bool = typer.Option(False, "--yes", help="Explicitly confirm one attempt of the reviewed content.")):
    """Approve only the inspected digest, without running it."""
    with _errors():
        if not yes:
            typer.confirm("Approve this inspected digest for ONE contained attempt?", default=False, abort=True)
        ReviewStore(ctx.obj).approve(proposal_id, digest, confirm=True)
        _print_json({"id": proposal_id, "state": "approved"})


@app.command("execute")
def execute_command(ctx: typer.Context, proposal_id: str,
                    structured: bool = typer.Option(False, '--structured', help='Return a typed v2-only attempt outcome; never retry.')):
    """Consume an existing approval. Never retry or fall back to host execution."""
    with _errors():
        store = ReviewStore(ctx.obj)
        if structured:
            outcome = store.execute_result(proposal_id)
            _print_json(outcome.to_dict())
            if outcome.status != ExecutionStatus.SUCCEEDED:
                raise typer.Exit(code=1)
            return
        result = store.execute(proposal_id)
        _print_json(result)
        if result["returncode"] != 0 or result.get("output_validation", {}).get("status", "passed") != "passed":
            raise typer.Exit(code=1)


@app.command("cancel")
def cancel_command(ctx: typer.Context, proposal_id: str):
    """Permanently cancel a pending or approved proposal, not a running container."""
    with _errors():
        ReviewStore(ctx.obj).cancel(proposal_id)
        _print_json({"id": proposal_id, "state": "cancelled"})
