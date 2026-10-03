"""Packaged prepare-only fixtures through real approved typed execution and reuse."""
import json
import os

import pytest
from typer.testing import CliRunner

from alita import review
from alita.catalog import VersionCatalog
from alita.cli import app
from alita.container_runner import ContainerExecutor, ContainerPolicy
from alita.outcomes import CleanupState, ExecutionStatus
from alita.review import ReviewStore

pytestmark = pytest.mark.skipif(os.environ.get('ALITA_CONTAINER_TESTS') != '1',
                               reason='requires explicit disposable Docker run')


@pytest.fixture
def owned(monkeypatch):
    instances = []

    def executor(policy):
        instance = ContainerExecutor(policy)
        instances.append(instance)
        return instance

    monkeypatch.setattr(review.runner, 'ContainerExecutor', executor)
    yield instances
    for instance in instances:
        assert instance._cleanup_confirmed is True
        assert not instance._docker('container', 'ls', '--all', '--quiet', '--filter',
                                     'label=io.alita.executor.owner=' + instance.owner).stdout.strip()


def call(runner, args, exit_code=0):
    result = runner.invoke(app, args)
    assert result.exit_code == exit_code, result.output
    return json.loads(result.output)


def approve(store, identifier):
    store.approve(identifier, store.inspect(identifier)['digest'], confirm=True)


@pytest.mark.parametrize('demo,args,expected', [
    ('text-summary', {'text': 'gamma gamma delta epsilon'}, {'words': 4, 'unique_words': 3}),
    ('table-totals', {'rows': [{'group': 'A', 'amount': -2}, {'group': 'B', 'amount': 5}, {'group': 'A', 'amount': 1}]},
     {'totals': {'A': -1, 'B': 5}, 'rows': 3, 'total': 4}),
    ('json-projection', {'data': {'name': 'Lin', 'active': False, 'scores': [], 'internal_note': 'not returned'}},
     {'name': 'Lin', 'active': False, 'score_total': 0}),
])
def test_packaged_demo_typed_cli_and_independently_checked_reuse(tmp_path, owned, demo, args, expected):
    store_path = tmp_path / 'reviews.sqlite3'
    runner = CliRunner()
    prepared = call(runner, ['demo', 'prepare', demo, '--store', str(store_path),
                             '--container-image', os.environ['ALITA_TEST_IMAGE']])
    store = ReviewStore(store_path)
    identifier = prepared['id']
    rp = ['review', '--store', str(store_path)]
    refused = call(runner, rp + ['execute', identifier, '--structured'], exit_code=1)
    assert refused['status'] == 'refused' and refused['approval_consumed'] is False and not owned
    approve(store, identifier)
    outcome = call(runner, rp + ['execute', identifier, '--structured'])
    assert outcome['status'] == 'succeeded' and outcome['cleanup'] == 'confirmed'
    assert outcome['receipt_saved'] is True and outcome['approval_consumed'] is True
    assert outcome['result']['output_validation']['status'] == 'passed'
    catalog = VersionCatalog(tmp_path / 'versions.sqlite3')
    version = catalog.promote(store, identifier, confirm=True)
    fresh = catalog.prepare(version['name'], version['version'], store, args=args,
                            output_contract={'kind': 'json-object-equals', 'expected': expected})
    assert store.execute_result(fresh['id']).status is ExecutionStatus.REFUSED
    approve(store, fresh['id'])
    reused = store.execute_result(fresh['id'])
    assert reused.status is ExecutionStatus.SUCCEEDED
    assert json.loads(reused.result['stdout']) == expected and len(owned) == 2
    assert store.execute_result(identifier).status is ExecutionStatus.REFUSED
    assert store.execute_result(fresh['id']).status is ExecutionStatus.REFUSED
    assert len(owned) == 2 and catalog.list()['count'] == 1


@pytest.mark.parametrize('source,status', [('import time\ntime.sleep(3)', ExecutionStatus.TIMEOUT),
                                         ('raise SystemExit(3)', ExecutionStatus.FAILED)])
def test_actual_non_success_typed_outcome_is_not_promotable(tmp_path, owned, source, status):
    store = ReviewStore(tmp_path / 'reviews.sqlite3')
    identifier = store.create({'name': 'failure_fixture'}, {'tool.py': source}, {},
                              ContainerPolicy(os.environ['ALITA_TEST_IMAGE'], timeout=1),
                              output_contract={'kind': 'stdout-equals', 'expected': ''})
    approve(store, identifier)
    outcome = store.execute_result(identifier)
    assert outcome.status is status and outcome.cleanup is CleanupState.CONFIRMED
    assert outcome.approval_consumed is True and outcome.receipt_saved is True
    assert outcome.result['output_validation']['status'] == 'not_checked'
    assert store.execute_result(identifier).status is ExecutionStatus.REFUSED
    with pytest.raises(PermissionError):
        VersionCatalog(tmp_path / 'versions.sqlite3').promote(store, identifier, confirm=True)
    assert len(owned) == 1
