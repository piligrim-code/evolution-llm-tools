import json
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from alita import cli, review, llm
from alita.container_runner import ContainerPolicy
from alita.demo_fixtures import get_demo, list_demos, prepare_demo

POLICY = ContainerPolicy('sha256:' + 'a' * 64)


@pytest.fixture(autouse=True)
def no_execution_or_model(monkeypatch):
    executor = Mock(side_effect=AssertionError('Preparing demos must not execute'))
    provider = Mock(side_effect=AssertionError('Demos must not contact a model'))
    monkeypatch.setattr(review.runner, 'ContainerExecutor', executor)
    monkeypatch.setattr(llm, 'OllamaClient', provider)
    yield
    executor.assert_not_called()
    provider.assert_not_called()


def test_three_named_fixtures_and_detached_nested_data():
    assert [row['name'] for row in list_demos()] == ['text-summary', 'table-totals', 'json-projection']
    one = get_demo('table-totals')
    one['args']['rows'][0]['amount'] = 99
    assert get_demo('table-totals')['args']['rows'][0]['amount'] == 3


@pytest.mark.parametrize('name', [row['name'] for row in list_demos()])
def test_prepare_only_creates_pending_v2_proposal(tmp_path, name):
    store = review.ReviewStore(tmp_path / 'reviews.sqlite3')
    prepared = prepare_demo(name, POLICY, store)
    proposal = store.inspect(prepared['id'])
    assert prepared['execution_authorized'] is False and prepared['state'] == 'pending'
    assert proposal['state'] == 'pending' and proposal['result'] is None
    assert proposal['document']['version'] == 2
    assert proposal['document']['output_contract'] == get_demo(name)['output_contract']
    with pytest.raises(PermissionError):
        store.execute(prepared['id'])


def test_cli_list_and_prepare_without_model_or_docker(tmp_path):
    runner = CliRunner()
    listed = runner.invoke(cli.app, ['demo', 'list'])
    assert listed.exit_code == 0 and len(json.loads(listed.output)['demos']) == 3
    path = tmp_path / 'reviews.sqlite3'
    draft = runner.invoke(cli.app, ['demo', 'prepare', 'text-summary', '--container-image', POLICY.image, '--store', str(path)])
    assert draft.exit_code == 0, draft.output
    identifier = json.loads(draft.output)['id']
    assert review.ReviewStore(path, read_only=True).inspect(identifier)['state'] == 'pending'


@pytest.mark.parametrize('name', ['unknown', '../bad', 'TEXT-SUMMARY'])
def test_unknown_demo_does_not_create_store(tmp_path, name):
    path = tmp_path / 'absent' / 'reviews.sqlite3'
    response = CliRunner().invoke(cli.app, ['demo', 'prepare', name, '--container-image', POLICY.image, '--store', str(path)])
    assert response.exit_code == 2 and not path.parent.exists()
