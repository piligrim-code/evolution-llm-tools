"""Read-only discovery scenarios; execution deferred for this follow-up."""
from contextlib import closing
import json
import sqlite3
from unittest.mock import Mock, patch

import pytest
from typer.testing import CliRunner

from alita import cli, review
from alita.container_runner import ContainerPolicy

POLICY = ContainerPolicy('sha256:' + 'a' * 64)
SPEC = {'name': 'fixture', 'args': [{'name': 'text', 'type': 'string'}]}
SCRIPTS = {'tool.py': "print('PRIVATE_SYNTHETIC_CODE')\n"}
ARGS = {'text': 'PRIVATE_SYNTHETIC_ARGUMENT'}


@pytest.fixture
def store(tmp_path):
    return review.ReviewStore(tmp_path / 'reviews.sqlite3')


@pytest.fixture(autouse=True)
def no_execution(monkeypatch):
    executor = Mock(side_effect=AssertionError('Discovery must never execute'))
    monkeypatch.setattr(review.runner, 'ContainerExecutor', executor)
    yield
    executor.assert_not_called()


def create(store):
    return store.create(SPEC, SCRIPTS, ARGS, POLICY)


def test_empty_list_has_no_cursor(store):
    assert store.list() == {'proposals': [], 'count': 0, 'next_cursor': None,
                            'content_included': False, 'integrity_checked': False}


def test_discovery_excludes_source_args_result_and_approval_digest(store):
    identifier = create(store)
    digest = store.inspect(identifier)['digest']
    with closing(sqlite3.connect(store.path)) as db, db:
        db.execute("UPDATE proposals SET state='finished',result=? WHERE id=?",
                   (json.dumps({'stdout': 'PRIVATE_SYNTHETIC_RESULT'}), identifier))
    with patch.object(store, '_load', side_effect=AssertionError('Must not inspect source')):
        result = store.list()
    assert result['proposals'] == [{'id': identifier, 'state': 'finished', 'has_result': True}]
    assert 'PRIVATE_SYNTHETIC' not in json.dumps(result)
    assert digest not in json.dumps(result)
    assert result['integrity_checked'] is False


def test_pages_follow_insertion_order_without_duplicate_ids(store):
    ids = [create(store) for _ in range(5)]
    first = store.list(limit=2)
    second = store.list(limit=2, before=first['next_cursor'])
    last = store.list(limit=2, before=second['next_cursor'])
    assert [row['id'] for page in (first, second, last) for row in page['proposals']] == ids[::-1]
    assert last['next_cursor'] is None
    assert first['next_cursor'] == ids[3]


def test_new_insert_does_not_shift_older_pages(store):
    ids = [create(store) for _ in range(3)]
    first = store.list(limit=1)
    create(store)
    second = store.list(limit=2, before=first['next_cursor'])
    assert [row['id'] for row in second['proposals']] == ids[1::-1]
    assert second['next_cursor'] is None


def test_filter_pages_do_not_skip_matching_older_records(store):
    ids = [create(store) for _ in range(5)]
    store.cancel(ids[1])
    store.cancel(ids[3])
    first = store.list(state='cancelled', limit=1)
    second = store.list(state='cancelled', limit=1, before=first['next_cursor'])
    assert first['proposals'][0]['id'] == ids[3]
    assert second['proposals'][0]['id'] == ids[1]
    assert second['next_cursor'] is None


@pytest.mark.parametrize('state', review.PROPOSAL_STATES)
def test_all_lifecycle_states_are_discoverable(store, state):
    identifier = create(store)
    with closing(sqlite3.connect(store.path)) as db, db:
        db.execute('UPDATE proposals SET state=? WHERE id=?', (state, identifier))
    assert store.list(state=state)['proposals'] == [{'id': identifier, 'state': state, 'has_result': False}]


@pytest.mark.parametrize('limit', [0, -1, 101, True, '2', 1.5])
def test_invalid_limits_refused(store, limit):
    with pytest.raises(review.ReviewError, match='invalid_list_limit'):
        store.list(limit=limit)


@pytest.mark.parametrize('state', ['', 'running', 'PENDING', True, []])
def test_invalid_filters_refused(store, state):
    with pytest.raises(review.ReviewError, match='invalid_proposal_state'):
        store.list(state=state)


def test_invalid_or_unknown_cursor_never_restarts_first_page(store):
    create(store)
    with pytest.raises(review.ReviewError, match='invalid_proposal_id'):
        store.list(before='../bad')
    with pytest.raises(review.ReviewError, match='list_cursor_not_found'):
        store.list(before='0' * 32)


def test_read_only_discovery_does_not_change_rows_or_database_bytes(store):
    identifier = create(store)
    before = store.path.read_bytes()
    reader = review.ReviewStore(store.path, read_only=True)
    assert reader.list()['proposals'][0]['id'] == identifier
    assert reader.inspect(identifier)['state'] == 'pending'
    assert before == store.path.read_bytes()


def test_read_only_store_refuses_all_mutations(store):
    identifier = create(store)
    reader = review.ReviewStore(store.path, read_only=True)
    digest = reader.inspect(identifier)['digest']
    calls = [lambda: reader.create(SPEC, SCRIPTS, ARGS, POLICY),
             lambda: reader.approve(identifier, digest, confirm=True),
             lambda: reader.cancel(identifier), lambda: reader.execute(identifier)]
    for call in calls:
        with pytest.raises(PermissionError, match='read_only'):
            call()
    assert reader.inspect(identifier)['state'] == 'pending'


def test_missing_read_only_store_does_not_create_directory(tmp_path):
    path = tmp_path / 'absent' / 'reviews.sqlite3'
    with pytest.raises(review.ReviewError, match='review_store_not_found'):
        review.ReviewStore(path, read_only=True)
    assert not path.parent.exists()


def test_read_only_store_requires_existing_schema(tmp_path):
    path = tmp_path / 'empty.sqlite3'
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('PRAGMA user_version=1')
    before = path.read_bytes()
    with pytest.raises(review.ReviewError, match='invalid_review_store'):
        review.ReviewStore(path, read_only=True)
    assert before == path.read_bytes()


def test_read_only_option_is_not_coerced(store):
    with pytest.raises(review.ReviewError, match='read_only_must_be_boolean'):
        review.ReviewStore(store.path, read_only='false')


def test_read_only_inspection_refuses_future_version_without_migration(store):
    with closing(sqlite3.connect(store.path)) as db, db:
        db.execute('PRAGMA user_version=2')
    before = store.path.read_bytes()
    with pytest.raises(review.ReviewError, match='unsupported_review_store_version'):
        review.ReviewStore(store.path, read_only=True)
    assert before == store.path.read_bytes()


def test_corrupt_document_remains_discoverable_but_not_inspectable(store):
    identifier = create(store)
    with closing(sqlite3.connect(store.path)) as db, db:
        db.execute('UPDATE proposals SET document=? WHERE id=?', ('PRIVATE_SYNTHETIC_CORRUPTION', identifier))
    reader = review.ReviewStore(store.path, read_only=True)
    assert reader.list()['proposals'][0]['id'] == identifier
    with pytest.raises(ValueError):
        reader.inspect(identifier)


def test_cli_lists_claimed_attempts_without_retrying_or_marking_them(store):
    identifier = create(store)
    with closing(sqlite3.connect(store.path)) as db, db:
        db.execute("UPDATE proposals SET state='claimed' WHERE id=?", (identifier,))
    result = CliRunner().invoke(cli.app, ['review', '--store', str(store.path), 'list', '--state', 'claimed'])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)['proposals'] == [{'id': identifier, 'state': 'claimed', 'has_result': False}]
    assert store.inspect(identifier)['state'] == 'claimed'


@pytest.mark.parametrize('command', [['list'], ['inspect', '0' * 32]])
def test_cli_discovery_does_not_create_missing_store(tmp_path, command):
    path = tmp_path / 'absent' / 'reviews.sqlite3'
    result = CliRunner().invoke(cli.app, ['review', '--store', str(path), *command])
    assert result.exit_code == 2
    assert 'review_store_not_found' in result.output
    assert not path.parent.exists()
