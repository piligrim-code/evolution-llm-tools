"""User tasks use handwritten replies and predetermined executor results; no model or Docker."""
import hashlib
import json
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from alita import cli
from alita.generation_results import GenerationResult, GenerationUsage, request_digest, text_digest
from alita.review import ReviewStore
from alita.user_tasks import (UserTaskError, UserTaskSource, generate_user_candidate,
                              record_user_generation, user_prompt)

IMAGE = 'sha256:' + 'b' * 64


def task_document(**changes):
    document = {
        'format': 'toolwright-user-task-v1', 'id': 'duration-seconds',
        'instruction': 'Convert a duration like "1h30m" (hours, minutes, seconds) to whole seconds.',
        'examples': [{'id': 'hours-minutes', 'data': {'text': '1h30m'}, 'result': 5400},
                     {'id': 'seconds', 'data': {'text': '45s'}, 'result': 45}],
        'held_out': [{'id': 'all-units', 'data': {'text': '2h5m7s'}, 'result': 7507},
                     {'id': 'minutes', 'data': {'text': '10m'}, 'result': 600},
                     {'id': 'zero', 'data': {'text': '0s'}, 'result': 0}],
    }
    document.update(changes)
    return document


@pytest.fixture(autouse=True)
def no_provider(monkeypatch):
    provider = Mock(side_effect=AssertionError('User-task tests must not call a provider'))
    monkeypatch.setattr('alita.llm.OllamaClient.generate_result', provider)
    yield
    provider.assert_not_called()


def reply(prompt, text, *, json_mode=False):
    payload = {'model': 'synthetic', 'prompt': prompt, 'stream': True,
               'options': {'temperature': 0, 'num_predict': 2048}}
    if json_mode:
        payload['format'] = 'json'
    return GenerationResult(text=text, requested_model='synthetic', provider_model=None, done_reason='stop',
                            prompt_sha256=text_digest(prompt), request_sha256=request_digest(payload),
                            endpoint_sha256=text_digest('synthetic'), response_sha256=text_digest(text),
                            temperature=0, max_tokens=2048, seed=None, json_mode=json_mode, timeout_seconds=300,
                            client_elapsed_seconds=0, provider_usage=GenerationUsage())


@pytest.mark.parametrize('changes,reason', [
    ({'held_out': task_document()['held_out'][:2]}, 'held_out_case_count'),
    ({'examples': []}, 'example_case_count'),
    ({'id': 'Bad Id'}, 'invalid_task_id'),
    ({'format': 'other'}, 'unsupported_task_format'),
    ({'held_out': task_document()['held_out'][:2] + [{'id': 'seconds', 'data': {'text': '9s'}, 'result': 9}]},
     'duplicate_case_id'),
    ({'held_out': task_document()['held_out'][:2] + [{'id': 'copy', 'data': {'text': '45s'}, 'result': 45}]},
     'distinct_and_unseen'),
    ({'examples': [{'id': 'x', 'data': ['1h'], 'result': 3600}]}, 'case_data_must_be_object'),
    ({'examples': [{'id': 'x', 'data': {}, 'result': 1, 'note': 'extra'}]}, 'exactly_id_data_result'),
])
def test_task_files_are_validated(changes, reason):
    with pytest.raises(UserTaskError, match=reason):
        UserTaskSource(task_document(**changes))
    with pytest.raises(UserTaskError, match='one_json_object'):
        UserTaskSource.from_text('[1]')


def test_summary_and_listing_hide_cases_and_digest_is_stable():
    source = UserTaskSource(task_document())
    assert source.summary() == {'format': 'toolwright-user-task-v1', 'task_id': 'duration-seconds',
                                'task_sha256': source.corpus_digest(), 'examples': 2, 'held_out': 3,
                                'content_included': False}
    assert source.corpus_digest() == UserTaskSource(task_document()).corpus_digest()
    assert source.corpus_digest() != UserTaskSource(task_document(instruction='Other.')).corpus_digest()
    assert all(set(case) == {'id', 'split'} for case in source.list_cases())
    assert source.task_spec(source.get_task('duration-seconds'))['name'] == 'task_duration_seconds'


def test_prompt_shows_examples_only_and_refuses_held_out_leaks():
    source = UserTaskSource(task_document())
    prompt = user_prompt(source)
    assert '{"data":{"text":"1h30m"}} -> {"result":5400}' in prompt
    assert '2h5m7s' not in prompt and '10m"' not in prompt and '"0s"' not in prompt
    assert 'sys.exit(...), never exit() or quit()' in prompt
    leaking = UserTaskSource(task_document(instruction='See {"data":{"text":"10m"}} for the format.'))
    with pytest.raises(PermissionError, match='held_out_input'):
        user_prompt(leaking)


def test_replies_are_bound_to_the_exact_prompt():
    source = UserTaskSource(task_document())
    prompt = user_prompt(source)
    record, text = record_user_generation(source, reply(prompt, '```python\nimport json\nimport sys\n```'))
    assert text == 'import json\nimport sys\n' and record['status'] == 'unreviewed_source'
    assert record['task_sha256'] == source.corpus_digest() and record['execution_authorized'] is False
    assert 'import sys' not in json.dumps(record)
    record, text = record_user_generation(source, reply(prompt, 'import sys\n'))
    assert text is None and record['source_check']['reason'] == 'expected_single_python_fence'
    other = user_prompt(UserTaskSource(task_document(instruction='Different.')))
    with pytest.raises(ValueError, match='binding_mismatch'):
        record_user_generation(source, reply(other, '```python\npass\n```'))
    with pytest.raises(ValueError, match='without_json_mode'):
        record_user_generation(source, reply(prompt, '{}', json_mode=True))


def test_generate_calls_only_the_given_client():
    source = UserTaskSource(task_document())

    class Client:
        def generate_result(self, prompt, **options):
            assert options == {'temperature': 0, 'max_tokens': 2048, 'seed': None, 'json_mode': False, 'think': None}
            return reply(prompt, '```python\nprint(1)\n```')

    record, text = generate_user_candidate(source, Client())
    assert text == 'print(1)\n' and record['status'] == 'unreviewed_source'


def run_cases(store, monkeypatch, manifest, answers):
    for assignment in manifest['assignments']:
        output = json.dumps({'result': answers[assignment['case_id']]})

        class Executor:
            def __init__(self, policy):
                self._attempted = self._cleanup_confirmed = False

            def run(self, scripts, args, output=output):
                self._attempted = self._cleanup_confirmed = True
                return {'returncode': 0, 'stdout': output,
                        'stdout_sha256': hashlib.sha256(output.encode()).hexdigest(),
                        'stdout_bytes': len(output), 'stderr': '', 'execution': 'container', 'outcome': 'exited'}

        monkeypatch.setattr('alita.review.runner.ContainerExecutor', Executor)
        identifier = assignment['proposal_id']
        store.approve(identifier, store.inspect(identifier)['digest'], confirm=True)
        store.execute_result(identifier)


@pytest.mark.parametrize('wrong_case,admitted', [(None, True), ('minutes', False)])
def test_cli_flow_admits_only_when_every_case_passes(tmp_path, monkeypatch, wrong_case, admitted):
    runner = CliRunner()
    task_file, scripts = tmp_path / 'task.json', tmp_path / 'candidate.json'
    task_file.write_text(json.dumps(task_document()))
    scripts.write_text(json.dumps({'tool.py': 'pass\n'}))
    paths = ['--store', str(tmp_path / 'r.sqlite3')]
    checked = runner.invoke(cli.app, ['task', 'check', str(task_file)])
    assert checked.exit_code == 0 and '2h5m7s' not in checked.output
    prepared = runner.invoke(cli.app, ['task', 'prepare', str(task_file), '--scripts', str(scripts),
                                       '--container-image', IMAGE, *paths])
    assert prepared.exit_code == 0, prepared.output
    manifest = json.loads(prepared.output)
    assert manifest['state'] == 'pending' and len(manifest['assignments']) == 5
    answers = {case['id']: case['result'] for case in task_document()['examples'] + task_document()['held_out']}
    if wrong_case:
        answers[wrong_case] = -1
    run_cases(ReviewStore(tmp_path / 'r.sqlite3'), monkeypatch, manifest, answers)
    manifest_file = tmp_path / 'manifest.json'
    manifest_file.write_text(json.dumps(manifest))
    ledger = ['--ledger', str(tmp_path / 'a.sqlite3')]
    result = runner.invoke(cli.app, ['task', 'admit', str(task_file), str(manifest_file), *paths, *ledger])
    assert result.exit_code == 0, result.output
    summary = json.loads(result.output)
    assert summary['admitted'] is admitted and summary['corpus_version'] == 'toolwright-user-task-v1'
    assert summary['held_out_passed'] == (3 if admitted else 2)
    assert '"minutes"' not in result.output
    promoted = runner.invoke(cli.app, ['task', 'promote', str(task_file), str(summary['attempt']), *paths, *ledger,
                                       '--catalog', str(tmp_path / 'v.sqlite3'), '--yes'])
    if admitted:
        assert promoted.exit_code == 0 and json.loads(promoted.output)['name'] == 'task_duration_seconds'
    else:
        assert promoted.exit_code != 0
