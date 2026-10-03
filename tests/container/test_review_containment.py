"""Review receipts around real contained execution of a hand-written fixture."""
import os
import json

import pytest

from alita.container_runner import ContainerExecutor, ContainerPolicy
from alita.review import ReviewStore
from alita.cli import app
from typer.testing import CliRunner

pytestmark = pytest.mark.skipif(os.environ.get("ALITA_CONTAINER_TESTS") != "1",
                               reason="requires explicit disposable Docker run")


def test_reviewed_fixture_requires_approval_and_cannot_replay(tmp_path, monkeypatch):
    from alita import review

    instances = []

    def executor(policy):
        instance = ContainerExecutor(policy)
        instances.append(instance)
        return instance

    monkeypatch.setattr(review.runner, "ContainerExecutor", executor)
    store = ReviewStore(tmp_path / "reviews.sqlite3")
    identifier = store.create(
        {"name": "length", "args": [{"name": "text", "type": "string"}], "output": "Text length"},
        {"tool.py": "import json, sys\nprint(len(json.loads(sys.argv[2])['text']))\n"},
        {"text": "synthetic"}, ContainerPolicy(os.environ["ALITA_TEST_IMAGE"]))
    assert not instances
    with pytest.raises(PermissionError):
        store.execute(identifier)
    assert not instances
    store.approve(identifier, store.inspect(identifier)["digest"], confirm=True)
    assert not instances
    result = store.execute(identifier)
    assert result["returncode"] == 0 and result["stdout"].strip() == "9"
    assert store.inspect(identifier)["result"] == result
    with pytest.raises(PermissionError):
        ReviewStore(store.path).execute(identifier)
    assert len(instances) == 1
    controller = instances[0]
    remaining = controller._docker("container", "ls", "--all", "--quiet", "--filter",
                                   "label=io.alita.executor.owner=" + controller.owner)
    assert not remaining.stdout.strip(), "Owned container was not removed"


@pytest.mark.parametrize('source,contract,status', [
    ("print('synthetic')", {'kind': 'stdout-equals', 'expected': 'synthetic\n'}, 'passed'),
    ("print('wrong')", {'kind': 'stdout-equals', 'expected': 'synthetic\n'}, 'failed'),
    ("print('{\"b\":2,\"a\":1}')", {'kind': 'json-object-equals', 'expected': {'a': 1, 'b': 2}}, 'passed'),
    ("import sys\nsys.stdout.buffer.write(b'{\"a\":1}\\x00')", {'kind': 'json-object-equals', 'expected': {'a': 1}}, 'failed'),
])
def test_reviewed_cli_enforces_output_contract_with_actual_container(tmp_path, monkeypatch, source, contract, status):
    from alita import review
    instances = []

    def executor(policy):
        instance = ContainerExecutor(policy)
        instances.append(instance)
        return instance

    monkeypatch.setattr(review.runner, 'ContainerExecutor', executor)
    store = ReviewStore(tmp_path / 'reviews.sqlite3')
    identifier = store.create({'name': 'fixture'}, {'tool.py': source}, {},
                              ContainerPolicy(os.environ['ALITA_TEST_IMAGE']), output_contract=contract)
    runner = CliRunner()
    prefix = ['review', '--store', str(store.path)]
    assert runner.invoke(app, prefix + ['execute', identifier]).exit_code == 2
    inspected = runner.invoke(app, prefix + ['inspect', identifier, '--json'])
    assert inspected.exit_code == 0, inspected.output
    record = json.loads(inspected.output)
    assert record['document']['output_contract'] == contract
    approval = runner.invoke(app, prefix + ['approve', identifier, '--digest', record['digest'], '--yes'])
    assert approval.exit_code == 0, approval.output
    assert not instances
    result = runner.invoke(app, prefix + ['execute', identifier])
    assert result.exit_code == (0 if status == 'passed' else 1), result.output
    receipt = json.loads(result.output)
    assert receipt['returncode'] == 0 and receipt['output_validation']['status'] == status
    assert store.inspect(identifier)['result'] == receipt
    assert runner.invoke(app, prefix + ['execute', identifier]).exit_code == 2
    assert len(instances) == 1
    controller = instances[0]
    assert not controller._docker('container', 'ls', '--all', '--quiet', '--filter',
                                  'label=io.alita.executor.owner=' + controller.owner).stdout.strip()
