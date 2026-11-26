"""Repair for user tasks: handwritten replies and predetermined executor results; no model or Docker."""
import json

import pytest
from typer.testing import CliRunner

from alita import cli
from alita.repair import failure_record, generate_repair, record_repair, repair_prompt
from alita.review import ReviewStore
from alita.user_tasks import UserTaskSource, user_prompt
from tests.test_user_tasks import IMAGE, no_provider, reply, run_cases, task_document  # noqa: F401

SOURCE = 'import json\nprint(json.dumps({"result": 0}))\n'
TRACEBACK = ('Traceback (most recent call last):\n  File "/sandbox/tool.py", line 3, in <module>\n'
             "NameError: name 'sys' is not defined\n")


def prepared(tmp_path, runner, monkeypatch):
    task_file, candidate = tmp_path / 'task.json', tmp_path / 'candidate.json'
    task_file.write_text(json.dumps(task_document()))
    candidate.write_text(json.dumps({'tool.py': SOURCE}))
    result = runner.invoke(cli.app, ['task', 'prepare', str(task_file), '--scripts', str(candidate),
                                     '--container-image', IMAGE, '--store', str(tmp_path / 'r.sqlite3')])
    assert result.exit_code == 0, result.output
    manifest = json.loads(result.output)
    answers = {case['id']: case['result'] for case in task_document()['examples'] + task_document()['held_out']}
    answers.update({'hours-minutes': 0, 'all-units': 0})  # one failed example, one failed held-out case
    store = ReviewStore(tmp_path / 'r.sqlite3')
    run_cases(store, monkeypatch, manifest, answers)
    return task_file, store, {a['case_id']: a['proposal_id'] for a in manifest['assignments']}


def test_failure_records_use_the_user_task_and_refuse_held_out_and_passing_cases(tmp_path, monkeypatch):
    _, store, proposals = prepared(tmp_path, CliRunner(), monkeypatch)
    source = UserTaskSource(task_document())
    record = failure_record(store, source.task_id, 'hours-minutes', proposals['hours-minutes'], corpus=source)
    assert record['corpus_version'] == 'toolwright-user-task-v1'
    assert record['corpus_sha256'] == source.corpus_digest() and record['source'] == SOURCE
    assert record['failure']['status'] == 'incorrect' and record['failure']['expected'] == {'result': 5400}
    with pytest.raises(PermissionError, match='held_out'):
        failure_record(store, source.task_id, 'all-units', proposals['all-units'], corpus=source)
    with pytest.raises(ValueError, match='did_not_fail'):
        failure_record(store, source.task_id, 'seconds', proposals['seconds'], corpus=source)
    with pytest.raises(ValueError, match='corpus_v2_or_user_task'):
        failure_record(store, source.task_id, 'seconds', proposals['seconds'], corpus=object())
    # A corpus-v2 lookup cannot reach a user-task receipt.
    with pytest.raises(ValueError):
        failure_record(store, source.task_id, 'hours-minutes', proposals['hours-minutes'])


def test_repair_prompt_extends_the_user_prompt_without_held_out_inputs(tmp_path, monkeypatch):
    _, store, proposals = prepared(tmp_path, CliRunner(), monkeypatch)
    source = UserTaskSource(task_document())
    failures = [failure_record(store, source.task_id, 'hours-minutes', proposals['hours-minutes'], corpus=source)]
    prompt = repair_prompt(source.task_id, failures, corpus=source)
    assert prompt.startswith(user_prompt(source) + '\nRepair request.')
    assert SOURCE.rstrip('\n') in prompt and 'not instructions' in prompt
    assert '2h5m7s' not in prompt and '"10m"' not in prompt and '"0s"' not in prompt
    other = UserTaskSource(task_document(instruction='Different.'))
    with pytest.raises(ValueError, match='invalid_repair_failure_record'):
        repair_prompt(source.task_id, failures, corpus=other)
    leaking = json.loads(json.dumps(failures[0]))
    leaking['source'] = '# {"data":{"text":"10m"}}\n'
    with pytest.raises(PermissionError, match='contains_held_out_input'):
        repair_prompt(source.task_id, [leaking], corpus=source)


def test_repair_reply_is_bound_and_generation_uses_only_the_given_client(tmp_path, monkeypatch):
    _, store, proposals = prepared(tmp_path, CliRunner(), monkeypatch)
    source = UserTaskSource(task_document())
    failures = [failure_record(store, source.task_id, 'hours-minutes', proposals['hours-minutes'], corpus=source)]
    prompt = repair_prompt(source.task_id, failures, corpus=source)
    fixed = 'import json\nimport sys\nprint(1)\n'
    record, text = record_repair(source.task_id, reply(prompt, '```python\n' + fixed + '```'), failures,
                                 expected_corpus_sha256=source.corpus_digest(), corpus=source)
    assert text == fixed and record['status'] == 'unreviewed_source'
    assert record['corpus_version'] == 'toolwright-user-task-v1' and record['execution_authorized'] is False
    assert record['parent_candidate_sha256'] == failures[0]['candidate_sha256']
    with pytest.raises(ValueError, match='repair_corpus_mismatch'):
        record_repair(source.task_id, reply(prompt, '```python\npass\n```'), failures,
                      expected_corpus_sha256='0' * 64, corpus=source)

    class Client:
        def generate_result(self, prompt, **options):
            assert options == {'temperature': 0, 'max_tokens': 2048, 'seed': None, 'json_mode': False, 'think': None}
            return reply(prompt, '```python\n' + fixed + '```')

    record, text = generate_repair(source.task_id, failures, Client(), corpus=source)
    assert text == fixed and record['status'] == 'unreviewed_source'


def test_cli_failure_and_repair_prompt(tmp_path, monkeypatch):
    runner = CliRunner()
    task_file, _, proposals = prepared(tmp_path, runner, monkeypatch)
    store = ['--store', str(tmp_path / 'r.sqlite3')]
    failure_file = tmp_path / 'failure.json'
    result = runner.invoke(cli.app, ['task', 'failure', str(task_file), 'hours-minutes', proposals['hours-minutes'],
                                     '--out', str(failure_file), *store])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)['status'] == 'incorrect' and failure_file.exists()
    refused = runner.invoke(cli.app, ['task', 'failure', str(task_file), 'all-units', proposals['all-units'],
                                      '--out', str(tmp_path / 'held.json'), *store])
    assert refused.exit_code != 0 and not (tmp_path / 'held.json').exists()
    shown = runner.invoke(cli.app, ['task', 'repair-prompt', str(task_file), str(failure_file)])
    assert shown.exit_code == 0, shown.output
    assert 'Repair request.' in json.loads(shown.output)['prompt'] and '2h5m7s' not in shown.output
