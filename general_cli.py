"""Generalization of a task family into one documented, parameterized tool. Review remains mandatory."""
import json
from pathlib import Path

import typer

from .admission import AdmissionLedger, prepare_admission_case
from .catalog import VersionCatalog
from .container_runner import ContainerPolicy
from .contracts import json_object, tool_spec
from .generalization import (BoundMember, GeneralizationError, Member, _doc_literal, checked_documentation,
                             family_decision, find_families, generalization_prompt, generate_generalization)
from .llm import OllamaClient
from .review import ReviewStore
from .review_cli import _errors, _print_json
from .user_tasks import UserTaskSource

app = typer.Typer(no_args_is_help=True,
                  help='One parameterized tool for a task family; admitted only if admitted on every member.')
MEMBER_HELP = 'KEY=corpus:TASK_ID or KEY=path/to/task.json; repeat for every member.'


def _read(path):
    with Path(path).open('rb') as stream:
        return json_object(stream.read(256001), limit=256000)


def _members(specs):
    members = []
    for spec in specs or []:
        key, separator, target = spec.partition('=')
        if not separator or not target:
            raise GeneralizationError('member_requires_key_and_task')
        if target.startswith('corpus:'):
            members.append(Member(key, target[len('corpus:'):]))
        else:
            with Path(target).open('rb') as stream:
                source = UserTaskSource.from_text(stream.read(256 * 1024 + 1))
            members.append(Member(key, source.task_id, source))
    return members


def reviews_spec(bound):
    """The stored (normalized) spec a proposal for this bound member must carry."""
    return tool_spec(bound.task_spec(bound.get_task(bound.task_id)))


def _bound(record_path, specs, key):
    """Members and documentation of a recorded generalization, rechecked against the given members."""
    record, members = _read(record_path), _members(specs)
    if record.get('format') != 'toolwright-generalization-v1' or record.get('status') != 'unreviewed_source':
        raise GeneralizationError('invalid_generalization_record')
    if record.get('members') != [m.identity() for m in sorted(members, key=lambda m: m.key)]:
        raise GeneralizationError('generalization_members_changed')
    documentation = checked_documentation(record.get('documentation'), [m.key for m in members])
    by_key = {m.key: m for m in members}
    if key is not None and key not in by_key:
        raise GeneralizationError('unknown_member_key')
    return members, documentation, (BoundMember(by_key[key], documentation) if key is not None else None)


@app.command('families')
def families_command(member: list[str] = typer.Option(..., help=MEMBER_HELP)):
    """Group member tasks by contract signature. A proposal for a human; nothing is generated."""
    with _errors():
        _print_json(find_families(_members(member)))


@app.command('prompt')
def prompt_command(member: list[str] = typer.Option(..., help=MEMBER_HELP)):
    """Show the generalization prompt (instructions and examples of every member only)."""
    with _errors():
        _print_json({'prompt': generalization_prompt(_members(member))})


@app.command('generate')
def generate_command(member: list[str] = typer.Option(..., help=MEMBER_HELP),
                     out: str = typer.Option(..., help='Where to write the candidate scripts JSON.'),
                     record: str = typer.Option(..., help='Where to write the generalization record JSON.'),
                     model: str = typer.Option(None, help='Override the configured Ollama model.'),
                     seed: int = typer.Option(None), max_tokens: int = typer.Option(4096),
                     no_think: bool = typer.Option(False, '--no-think', help='Send think=false (thinking models).')):
    """Ask the model for one generalized candidate. Writes unreviewed source; never approves or runs it."""
    with _errors():
        result, text = generate_generalization(_members(member), OllamaClient(model=model), max_tokens=max_tokens,
                                               seed=seed, think=False if no_think else None)
        with Path(record).open('x', encoding='utf-8') as stream:
            stream.write(json.dumps(result))
        if text is not None:
            with Path(out).open('x', encoding='utf-8') as stream:
                stream.write(json.dumps({'tool.py': text}))
            result['candidate_file'] = out
        _print_json({key: value for key, value in result.items() if key != 'generation'})


@app.command('prepare')
def prepare_command(record: str, key: str, member: list[str] = typer.Option(..., help=MEMBER_HELP),
                    scripts: str = typer.Option(..., help='Candidate scripts JSON written by generate.'),
                    container_image: str = typer.Option(...), store: str = typer.Option('.mcp/reviews.sqlite3')):
    """Pending proposals for every case of one member under its binding. Never approves or runs."""
    with _errors():
        _, documentation, bound = _bound(record, member, key)
        candidate = _read(scripts)
        if set(candidate) != {'tool.py'} or checked_documentation(
                _doc_literal(candidate['tool.py']), list(documentation['bindings'])) != documentation:
            raise GeneralizationError('candidate_documentation_differs_from_record')
        policy, reviews = ContainerPolicy(container_image), ReviewStore(store)
        assignments = [{'case_id': case['id'],
                        'proposal_id': prepare_admission_case(bound.task_id, case['id'], candidate, policy, reviews,
                                                              corpus=bound)['proposal_id']}
                       for case in bound.list_cases()]
        _print_json({'member': key, 'task_id': bound.task_id, 'corpus_sha256': bound.corpus_digest(),
                     'assignments': assignments, 'state': 'pending', 'execution_authorized': False})


@app.command('admit')
def admit_command(record: str, key: str, manifest: str, member: list[str] = typer.Option(..., help=MEMBER_HELP),
                  store: str = typer.Option('.mcp/reviews.sqlite3'), ledger: str = typer.Option('.mcp/admissions.sqlite3')):
    """Score one member's finished receipts; uses one slot of that member's own held-out budget."""
    with _errors():
        _, _, bound = _bound(record, member, key)
        data = _read(manifest)
        if data.get('member') != key or data.get('task_id') != bound.task_id:
            raise GeneralizationError('manifest_member_mismatch')
        _print_json(AdmissionLedger(ledger, corpus=bound).evaluate(
            ReviewStore(store, read_only=True), bound.task_id, data['assignments'],
            expected_corpus_sha256=data['corpus_sha256']))


def _decision(record, member, attempt, ledger, store):
    members, documentation, _ = _bound(record, member, None)
    reviews = ReviewStore(store, read_only=True)
    attempts = dict(item.partition('=')[::2] for item in attempt or [])
    summaries = {}
    for m in members:
        if not attempts.get(m.key, '').isdigit():
            raise GeneralizationError('decision_requires_attempt_for_every_member')
        bound = BoundMember(m, documentation)
        summary = AdmissionLedger(ledger, corpus=bound).inspect(int(attempts[m.key]))
        if summary['task_id'] != m.task_id or summary['corpus_version'] != bound.CORPUS_VERSION:
            raise GeneralizationError('attempt_is_not_for_this_member')
        # The attempt's candidate must be the tool this record documents, not another generalization.
        document = reviews.inspect(AdmissionLedger(ledger, corpus=bound).promotion_proposal(int(attempts[m.key])))['document']
        if (document is None or document['spec'] != reviews_spec(bound) or set(document['scripts']) != {'tool.py'}
                or checked_documentation(_doc_literal(document['scripts']['tool.py']),
                                         list(documentation['bindings'])) != documentation):
            raise GeneralizationError('attempt_candidate_is_not_this_generalization')
        summaries[m.key] = summary
    return members, documentation, attempts, family_decision(summaries, members)


@app.command('decide')
def decide_command(record: str, member: list[str] = typer.Option(..., help=MEMBER_HELP),
                   attempt: list[str] = typer.Option(..., help='KEY=ATTEMPT from admit, for every member.'),
                   store: str = typer.Option('.mcp/reviews.sqlite3'), ledger: str = typer.Option('.mcp/admissions.sqlite3')):
    """Family decision from the recorded admission attempts; held-out details are never shown."""
    with _errors():
        _print_json(_decision(record, member, attempt, ledger, store)[3])


@app.command('promote')
def promote_command(record: str, member: list[str] = typer.Option(..., help=MEMBER_HELP),
                    attempt: list[str] = typer.Option(..., help='KEY=ATTEMPT from admit, for every member.'),
                    store: str = typer.Option('.mcp/reviews.sqlite3'), ledger: str = typer.Option('.mcp/admissions.sqlite3'),
                    catalog: str = typer.Option('.mcp/versions.sqlite3'),
                    yes: bool = typer.Option(False, '--yes', help='Explicitly confirm promotion.')):
    """Promote a family-admitted tool as general_<name>, via the first member's example receipt."""
    with _errors():
        members, documentation, attempts, decision = _decision(record, member, attempt, ledger, store)
        if decision['admitted'] is not True:
            raise PermissionError('generalization_not_admitted_on_every_member')
        first = sorted(members, key=lambda m: m.key)[0]
        _print_json({**AdmissionLedger(ledger, corpus=BoundMember(first, documentation)).promote(
            VersionCatalog(catalog), ReviewStore(store, read_only=True), int(attempts[first.key]), confirm=yes),
            'family_decision': decision})
