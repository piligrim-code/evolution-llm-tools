"""User tasks with your own example and held-out cases. Review remains mandatory."""
import json
from pathlib import Path

import typer

from .admission import AdmissionLedger, prepare_admission_case
from .catalog import VersionCatalog
from .container_runner import ContainerPolicy
from .contracts import json_object
from .llm import OllamaClient
from .repair import failure_record, generate_repair, repair_prompt
from .review import ReviewStore
from .review_cli import _errors, _print_json
from .skill_index import decide_for_task, reuse_candidate
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
        _print_json(_write_candidate(record, text, out))


def _write_candidate(record, text, out):
    if text is not None:
        target = Path(out)
        with target.open('x', encoding='utf-8') as stream:
            stream.write(json.dumps({'tool.py': text}))
        record['candidate_file'] = str(target)
    return record


@app.command('reuse')
def reuse_command(task_file: str, catalog: str = typer.Option('.mcp/versions.sqlite3')):
    """Decide reuse or generate from the instruction and examples; never runs or reuses anything."""
    with _errors():
        _print_json(decide_for_task(VersionCatalog(catalog, read_only=True), _source(task_file)))


@app.command('reuse-candidate')
def reuse_candidate_command(task_file: str, name: str, version: str,
                            out: str = typer.Option(..., help='Where to write the candidate scripts JSON.'),
                            catalog: str = typer.Option('.mcp/versions.sqlite3')):
    """Write a catalog version's scripts as an unreviewed candidate for this task's admission."""
    with _errors():
        source = _source(task_file)
        record, scripts = reuse_candidate(VersionCatalog(catalog, read_only=True), name, version)
        with Path(out).open('x', encoding='utf-8') as stream:
            stream.write(json.dumps(scripts))
        _print_json({**record, 'task_id': source.task_id, 'candidate_file': out})


@app.command('failure')
def failure_command(task_file: str, case_id: str, proposal_id: str,
                    out: str = typer.Option(..., help='Where to write the failure record JSON.'),
                    store: str = typer.Option('.mcp/reviews.sqlite3')):
    """Record one failed EXAMPLE case from its finished receipt. Held-out cases are refused."""
    with _errors():
        source = _source(task_file)
        record = failure_record(ReviewStore(store, read_only=True), source.task_id, case_id, proposal_id,
                                corpus=source)
        with Path(out).open('x', encoding='utf-8') as stream:
            stream.write(json.dumps(record))
        _print_json({'task_id': source.task_id, 'case_id': case_id, 'status': record['failure']['status'],
                     'candidate_sha256': record['candidate_sha256'], 'failure_file': out})


@app.command('repair-prompt')
def repair_prompt_command(task_file: str, failures: list[str]):
    """Show the repair prompt built from one to three failure records of one candidate."""
    with _errors():
        source = _source(task_file)
        records = [_read(path) for path in failures]
        _print_json({'task_id': source.task_id, 'task_sha256': source.corpus_digest(),
                     'prompt': repair_prompt(source.task_id, records, corpus=source)})


@app.command('repair')
def repair_command(task_file: str, failures: list[str],
                   out: str = typer.Option(..., help='Where to write the repaired candidate scripts JSON.'),
                   model: str = typer.Option(None, help='Override the configured Ollama model.'),
                   seed: int = typer.Option(None), max_tokens: int = typer.Option(2048),
                   no_think: bool = typer.Option(False, '--no-think', help='Send think=false (thinking models).')):
    """Ask the model for one repaired candidate. Writes unreviewed source; never approves or runs it."""
    with _errors():
        source = _source(task_file)
        records = [_read(path) for path in failures]
        record, text = generate_repair(source.task_id, records, OllamaClient(model=model), corpus=source,
                                       max_tokens=max_tokens, seed=seed, think=False if no_think else None)
        _print_json(_write_candidate(record, text, out))


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
