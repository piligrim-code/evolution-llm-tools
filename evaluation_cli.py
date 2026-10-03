"""Offline corpus preparation and scoring. No provider calls or execution shortcut."""
from pathlib import Path

import typer

from .container_runner import ContainerPolicy
from .contracts import json_object
from .evaluation import prepare_case, score_answer, score_decision, score_run
from .evaluation_corpus import CORPUS_VERSION, corpus_digest, decision_prompt, generation_prompt, get_case, get_task, list_tasks
from .review import ReviewStore, _digest
from .review_cli import _errors, _print_json

app = typer.Typer(no_args_is_help=True, help='Fixed synthetic tasks and offline grading; review remains mandatory.')


def _read(path):
    with Path(path).open('rb') as stream:
        return json_object(stream.read(256001), limit=256000)


@app.command('list')
def list_command():
    _print_json({'version': CORPUS_VERSION, 'sha256': corpus_digest(), 'tasks': list_tasks()})


@app.command('prompt')
def prompt_command(task_id: str, decision: bool = typer.Option(False, '--decision')):
    """Show only the task and demonstration, never held-out inputs/answers."""
    with _errors():
        prompt = decision_prompt(task_id) if decision else generation_prompt(task_id)
        _print_json({'task_id': task_id, 'corpus_sha256': corpus_digest(),
                     'prompt_sha256': _digest(prompt), 'prompt': prompt})


@app.command('cases')
def cases_command(task_id: str):
    """List case identifiers/splits without their inputs or expected answers."""
    with _errors():
        task = get_task(task_id)
        _print_json({'task_id': task_id, 'kind': task['kind'],
                     'cases': [{'id': case['id'], 'split': case['split']} for case in task['cases']]})


@app.command('prepare')
def prepare_command(task_id: str, case_id: str, scripts: str = typer.Option(..., help='Local JSON scripts object.'),
                    container_image: str = typer.Option(...), store: str = typer.Option('.mcp/reviews.sqlite3')):
    """Prepare one pending case with a literal assertion. Never approve or run."""
    with _errors():
        get_case(task_id, case_id)
        candidate = _read(scripts)
        policy = ContainerPolicy(container_image)
        _print_json(prepare_case(task_id, case_id, candidate, policy, ReviewStore(store)))


@app.command('score')
def score_command(manifest: str, store: str = typer.Option('.mcp/reviews.sqlite3'),
                  details: bool = typer.Option(False, '--details')):
    """Grade existing receipts, counting every missing case as not correct."""
    with _errors():
        data = _read(manifest)
        if set(data) != {'corpus_sha256', 'assignments'}:
            raise ValueError('invalid_evaluation_manifest')
        result = score_run(ReviewStore(store, read_only=True), data['assignments'],
                           expected_corpus_sha256=data['corpus_sha256'])
        if not details:
            result.pop('cases')
        _print_json(result)


@app.command('answer')
def answer_command(task_id: str, case_id: str, answer: str = typer.Option(..., help='Supplied JSON object, not code.')):
    """Grade a direct answer without claiming it came from a model or execution."""
    with _errors():
        _print_json(score_answer(task_id, case_id, json_object(answer)))


@app.command('decision')
def decision_command(task_id: str, decision: str = typer.Option(..., help='Explicit action/reason JSON label.')):
    """Grade the supplied prepare/refuse label. Does not grant permission."""
    with _errors():
        _print_json(score_decision(task_id, json_object(decision)))
