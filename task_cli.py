"""User tasks with your own example and held-out cases. Review remains mandatory."""
import json
from pathlib import Path

import typer

from .admission import AdmissionLedger, prepare_admission_case
from .catalog import VersionCatalog
from .container_runner import ContainerPolicy
from .contracts import json_object
from .llm import OllamaClient
from .review import ReviewStore
from .review_cli import _errors, _print_json
from .user_tasks import UserTaskSource, generate_user_candidate, user_prompt

app = typer.Typer(no_args_is_help=True,
                  help='Your own tasks: examples guide generation, held-out cases decide admission.')


def _source(path):
    with Path(path).open('rb') as stream:
        return UserTaskSource.from_text(stream.read(256 * 1024 + 1))


def _read(path):
    with Path(path).open('rb') as stream:
        return json_object(stream.read(256001), limit=256000)


@app.command('check')
def check_command(task_file: str):
    """Validate a task file; show counts and its hash, never its cases."""
    with _errors():
        _print_json(_source(task_file).summary())


@app.command('prompt')
def prompt_command(task_file: str):
    """Show the generation prompt (instruction and examples only)."""
    with _errors():
        source = _source(task_file)
        _print_json({'task_id': source.task_id, 'task_sha256': source.corpus_digest(), 'prompt': user_prompt(source)})


@app.command('generate')
def generate_command(task_file: str, out: str = typer.Option(..., help='Where to write the candidate scripts JSON.'),
                     model: str = typer.Option(None, help='Override the configured Ollama model.'),
                     seed: int = typer.Option(None), max_tokens: int = typer.Option(2048),
                     no_think: bool = typer.Option(False, '--no-think', help='Send think=false (thinking models).')):
    """Ask the model for one candidate. Writes unreviewed source; never approves or runs it."""
    with _errors():
        source = _source(task_file)
        record, text = generate_user_candidate(source, OllamaClient(model=model), max_tokens=max_tokens,
                                               seed=seed, think=False if no_think else None)
        if text is not None:
            target = Path(out)
            with target.open('x', encoding='utf-8') as stream:
                stream.write(json.dumps({'tool.py': text}))
            record['candidate_file'] = str(target)
        _print_json(record)


@app.command('prepare')
def prepare_command(task_file: str, scripts: str = typer.Option(..., help='Local JSON scripts object.'),
                    container_image: str = typer.Option(...), store: str = typer.Option('.mcp/reviews.sqlite3')):
    """Create one pending proposal per case and print the admission manifest. Never approves or runs."""
    with _errors():
        source = _source(task_file)
        candidate, policy, reviews = _read(scripts), ContainerPolicy(container_image), ReviewStore(store)
        assignments = [{'case_id': case['id'],
                        'proposal_id': prepare_admission_case(source.task_id, case['id'], candidate, policy,
                                                              reviews, corpus=source)['proposal_id']}
                       for case in source.list_cases()]
        _print_json({'task_sha256': source.corpus_digest(), 'task_id': source.task_id,
                     'assignments': assignments, 'state': 'pending', 'execution_authorized': False})


@app.command('admit')
def admit_command(task_file: str, manifest: str, store: str = typer.Option('.mcp/reviews.sqlite3'),
                  ledger: str = typer.Option('.mcp/admissions.sqlite3')):
    """Score finished receipts for every case and record the attempt (uses one candidate slot)."""
    with _errors():
        source, data = _source(task_file), _read(manifest)
        if set(data) - {'state', 'execution_authorized'} != {'task_sha256', 'task_id', 'assignments'}:
            raise ValueError('invalid_task_manifest')
        if data['task_id'] != source.task_id:
            raise ValueError('task_manifest_mismatch')
        _print_json(AdmissionLedger(ledger, corpus=source).evaluate(
            ReviewStore(store, read_only=True), source.task_id, data['assignments'],
            expected_corpus_sha256=data['task_sha256']))


@app.command('promote')
def promote_command(task_file: str, attempt: int, store: str = typer.Option('.mcp/reviews.sqlite3'),
                    ledger: str = typer.Option('.mcp/admissions.sqlite3'),
                    catalog: str = typer.Option('.mcp/versions.sqlite3'),
                    yes: bool = typer.Option(False, '--yes', help='Explicitly confirm promotion.')):
    """Promote an admitted candidate into the catalog via its first example receipt."""
    with _errors():
        source = _source(task_file)
        _print_json(AdmissionLedger(ledger, corpus=source).promote(
            VersionCatalog(catalog), ReviewStore(store, read_only=True), attempt, confirm=yes))
