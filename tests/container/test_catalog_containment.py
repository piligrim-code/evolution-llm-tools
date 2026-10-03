"""Actual reviewed execution, immutable promotion and fresh reviewed reuse."""
import json
import os

import pytest
from typer.testing import CliRunner

from alita import review
from alita.catalog import VersionCatalog
from alita.cli import app
from alita.container_runner import ContainerExecutor, ContainerPolicy
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
        assert not instance._docker('container', 'ls', '--all', '--quiet', '--filter',
                                     'label=io.alita.executor.owner=' + instance.owner).stdout.strip()


def create(reviews, expected='4\n'):
    return reviews.create(
        {'name': 'length', 'args': [{'name': 'text', 'type': 'string'}], 'output': 'Character count'},
        {'tool.py': "import json, sys\nprint(len(json.loads(sys.argv[2])['text']))\n"},
        {'text': 'four'}, ContainerPolicy(os.environ['ALITA_TEST_IMAGE']),
        output_contract={'kind': 'stdout-equals', 'expected': expected})


def call(runner, arguments, exit_code=0):
    result = runner.invoke(app, arguments)
    assert result.exit_code == exit_code, result.output
    return json.loads(result.output) if exit_code in (0, 1) else None


def approve(runner, prefix, identifier):
    proposal = call(runner, prefix + ['inspect', identifier, '--json'])
    call(runner, prefix + ['approve', identifier, '--digest', proposal['digest'], '--yes'])


def test_actual_cli_version_lifecycle_and_changed_arguments(tmp_path, owned):
    reviews = ReviewStore(tmp_path / 'reviews.sqlite3')
    catalog_path = tmp_path / 'versions.sqlite3'
    runner = CliRunner()
    rp = ['review', '--store', str(reviews.path)]
    cp = ['catalog', '--store', str(catalog_path), '--review-store', str(reviews.path)]
    identifier = create(reviews)
    approve(runner, rp, identifier)
    first = call(runner, rp + ['execute', identifier])
    assert first['output_validation']['status'] == 'passed' and len(owned) == 1
    version = call(runner, cp + ['promote', identifier, '--yes'])['version']
    saved = call(runner, cp + ['inspect', 'length', version])
    assert saved['record']['proposal_id'] == identifier
    assert call(runner, cp + ['list'])['count'] == 1
    clone = call(runner, cp + ['prepare', 'length', version])
    call(runner, rp + ['execute', clone['id']], exit_code=2)
    assert len(owned) == 1
    approve(runner, rp, clone['id'])
    assert call(runner, rp + ['execute', clone['id']])['output_validation']['status'] == 'passed'
    assert len(owned) == 2
    assert call(runner, cp + ['promote', clone['id'], '--yes'])['promoted'] is False
    changed = call(runner, cp + ['prepare', 'length', version, '--args', '{"text":"changed"}',
                                '--output-contract', '{"kind":"stdout-equals","expected":"7\\n"}'])
    call(runner, rp + ['execute', changed['id']], exit_code=2)
    approve(runner, rp, changed['id'])
    assert call(runner, rp + ['execute', changed['id']])['stdout'] == '7\n'
    assert len(owned) == 3
    for proposal_id in (identifier, clone['id'], changed['id']):
        call(runner, rp + ['execute', proposal_id], exit_code=2)
    assert len(owned) == 3
    assert call(runner, cp + ['inspect', 'length', version]) == saved
    assert call(runner, cp + ['list'])['count'] == 1  # Execution never promotes automatically.


def test_actual_incorrect_output_is_not_promotable(tmp_path, owned):
    reviews = ReviewStore(tmp_path / 'reviews.sqlite3')
    catalog = VersionCatalog(tmp_path / 'versions.sqlite3')
    runner = CliRunner()
    rp = ['review', '--store', str(reviews.path)]
    identifier = create(reviews, expected='5\n')
    approve(runner, rp, identifier)
    result = call(runner, rp + ['execute', identifier], exit_code=1)
    assert result['returncode'] == 0 and result['output_validation']['status'] == 'failed'
    cp = ['catalog', '--store', str(catalog.path), '--review-store', str(reviews.path)]
    call(runner, cp + ['promote', identifier, '--yes'], exit_code=2)
    assert catalog.list()['count'] == 0 and len(owned) == 1
