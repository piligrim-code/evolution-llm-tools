"""Prepare-only packaged fixtures; never call a model or run a tool."""
import typer

from .container_runner import ContainerPolicy
from .demo_fixtures import get_demo, list_demos, prepare_demo
from .review import ReviewStore
from .review_cli import _errors, _print_json

app = typer.Typer(no_args_is_help=True, help='Hand-written synthetic examples, each requiring normal review and approval.')


@app.command('list')
def list_command():
    _print_json({'demos': list_demos()})


@app.command('prepare')
def prepare_command(name: str,
                    container_image: str = typer.Option(..., help='Trusted local immutable sha256 image ID.'),
                    store: str = typer.Option('.mcp/reviews.sqlite3', help='Private review journal for the pending draft.')):
    """Create one pending proposal with an independent expected output. No execution."""
    with _errors():
        get_demo(name)
        policy = ContainerPolicy(container_image)
        _print_json(prepare_demo(name, policy, ReviewStore(store)))
