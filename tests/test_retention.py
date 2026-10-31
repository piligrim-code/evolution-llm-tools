"""Explicit maintenance on synthetic stores only. Never execute fixture code."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
import json
import multiprocessing
import sqlite3
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from alita import cli, review
from alita.catalog import CatalogError, VersionCatalog
from alita.container_runner import ContainerPolicy
from alita.outcomes import ExecutionStatus

POLICY = ContainerPolicy('sha256:' + 'a' * 64)
CONTRACT = {'kind': 'stdout-equals', 'expected': 'synthetic\n'}


@pytest.fixture(autouse=True)
def no_execution(monkeypatch):
    executor = Mock(side_effect=AssertionError('Maintenance must never execute'))
    monkeypatch.setattr(review.runner, 'ContainerExecutor', executor)
    yield
    executor.assert_not_called()


@pytest.fixture
def stores(tmp_path):
    return review.ReviewStore(tmp_path / 'reviews.sqlite3'), VersionCatalog(tmp_path / 'versions.sqlite3')


def create(store, state='finished'):
    identifier = store.create({'name': 'fixture', 'args': [{'name': 'text', 'type': 'string'}]},
                              {'tool.py': "print('synthetic') # PRIVATE_SYNTHETIC_CODE\n"},
                              {'text': 'PRIVATE_SYNTHETIC_ARGUMENT'}, POLICY, output_contract=CONTRACT)
    digest = store.inspect(identifier)['digest']
    result = {'execution': 'container', 'outcome': 'exited', 'returncode': 0, 'stdout': 'synthetic\n',
              'stderr': 'PRIVATE_SYNTHETIC_STDERR', 'stdout_sha256': review._digest('synthetic\n'), 'stdout_bytes': 10}
    result['output_validation'] = review.validate_output(CONTRACT, result)
    # Fabricated receipt for persistence tests only, not evidence of real execution.
    with closing(sqlite3.connect(store.path)) as db, db:
        db.execute('UPDATE proposals SET state=?,approval=?,result=? WHERE id=?',
                   (state, digest if state in ('approved', 'claimed', 'finished') else None,
                    json.dumps(result) if state == 'finished' else None, identifier))
    return identifier, digest


def prune(store, identifiers):
    plan = store.prune(identifiers)
    return store.prune(identifiers, plan_digest=plan['plan_digest'], confirm=True)


def retire(catalog, version):
    plan = catalog.retire('fixture', version)
    return catalog.retire('fixture', version, plan_digest=plan['plan_digest'], confirm=True)


def test_preview_is_read_only_bounded_and_contains_no_payload(stores):
    store, _ = stores
    identifier, digest = create(store)
    before = store.path.read_bytes()
    plan = review.ReviewStore(store.path, read_only=True).prune([identifier])
    assert not plan['applied'] and plan['count'] == 1 and plan['payload_bytes'] > 0
    assert plan['proposals'][0]['digest'] == digest
    assert 'PRIVATE_SYNTHETIC' not in json.dumps(plan) and not plan['content_included']
    assert store.path.read_bytes() == before and store.inspect(identifier)['state'] == 'finished'


@pytest.mark.parametrize('state', ['finished', 'cancelled'])
def test_pruned_payloads_leave_permanent_non_executable_identity(stores, state):
    store, catalog = stores
    identifier, digest = create(store, state)
    assert prune(store, [identifier])['applied']
    saved = store.inspect(identifier)
    assert saved['state'] == 'pruned' and saved['digest'] == digest
    assert saved['document'] is None and saved['result'] is None
    assert saved['retention']['previous_state'] == state
    assert 'PRIVATE_SYNTHETIC' not in json.dumps(saved)
    assert store.list(state='pruned')['proposals'] == [{'id': identifier, 'state': 'pruned', 'has_result': False}]
    for attempt in (lambda: store.approve(identifier, digest, confirm=True),
                    lambda: store.cancel(identifier), lambda: store.execute(identifier),
                    lambda: catalog.promote(store, identifier, confirm=True)):
        with pytest.raises(PermissionError, match='payload_pruned'):
            attempt()
    result = store.execute_result(identifier)
    assert result.status is ExecutionStatus.REFUSED and result.approval_consumed is False
    with closing(sqlite3.connect(store.path)) as db:
        for sql in ("UPDATE proposals SET state='approved' WHERE id=?", 'DELETE FROM proposals WHERE id=?'):
            with pytest.raises(sqlite3.IntegrityError, match='terminal'):
                db.execute(sql, (identifier,))
            db.rollback()
    with pytest.raises(PermissionError):
        prune(store, [identifier])


@pytest.mark.parametrize('state', ['pending', 'approved', 'claimed'])
def test_nonterminal_records_refuse_entire_batch(stores, state):
    store, _ = stores
    first, _ = create(store)
    second, _ = create(store, state)
    before = store.path.read_bytes()
    with pytest.raises(PermissionError, match='only_finished_or_cancelled'):
        store.prune([first, second], plan_digest='a' * 64, confirm=True)
    assert store.path.read_bytes() == before


@pytest.mark.parametrize('ids', [[], ['a' * 32] * 101, ['a' * 32] * 2, ['../bad'], 'a' * 32, [True]])
def test_invalid_or_unbounded_selection_is_refused(stores, ids):
    with pytest.raises(review.ReviewError):
        stores[0].prune(ids)


@pytest.mark.parametrize('token', [None, '', 'a' * 63, True, 'b' * 64])
def test_prune_requires_exact_preview_digest(stores, token):
    store, _ = stores
    identifier, _ = create(store)
    with pytest.raises((PermissionError, review.ReviewError)):
        store.prune([identifier], plan_digest=token, confirm=True)
    assert store.inspect(identifier)['state'] == 'finished'


def test_stale_plan_wrong_store_and_changed_selection_are_refused(stores, tmp_path):
    store, _ = stores
    first, _ = create(store)
    second, _ = create(store)
    plan = store.prune([first])
    with pytest.raises(review.ReviewError, match='plan_changed'):
        store.prune([second], plan_digest=plan['plan_digest'], confirm=True)
    copy_path = tmp_path / 'copy.sqlite3'
    # Byte copy is test setup, never a maintenance implementation strategy.
    copy_path.write_bytes(store.path.read_bytes())
    with pytest.raises(review.ReviewError, match='plan_changed'):
        review.ReviewStore(copy_path).prune([first], plan_digest=plan['plan_digest'], confirm=True)
    with closing(sqlite3.connect(store.path)) as db, db:
        db.execute("UPDATE proposals SET result='{}' WHERE id=?", (first,))
    with pytest.raises(review.ReviewError, match='plan_changed'):
        store.prune([first], plan_digest=plan['plan_digest'], confirm=True)
    assert store.inspect(first)['state'] == 'finished'


def test_prune_batch_rollback_and_order_independence(stores, monkeypatch):
    store, _ = stores
    ids = [create(store)[0], create(store, 'cancelled')[0]]
    plan = store.prune(ids)
    assert plan == store.prune(list(reversed(ids)))
    original = store._transaction

    @contextmanager
    def fail_commit():
        with original() as db:
            yield db
            raise sqlite3.OperationalError('synthetic pre-commit failure')

    with monkeypatch.context() as patch:
        patch.setattr(store, '_transaction', fail_commit)
        with pytest.raises(sqlite3.OperationalError):
            store.prune(ids, plan_digest=plan['plan_digest'], confirm=True)
    assert [store.inspect(i)['state'] for i in ids] == ['finished', 'cancelled']
    assert store.prune(ids, plan_digest=plan['plan_digest'], confirm=True)['applied']


def _process_prune(args):
    path, identifier, digest = args
    try:
        return review.ReviewStore(path).prune([identifier], plan_digest=digest, confirm=True)['applied']
    except PermissionError:
        return False


def test_independent_processes_cannot_prune_twice(stores):
    store, _ = stores
    identifier, _ = create(store)
    args = (str(store.path), identifier, store.prune([identifier])['plan_digest'])
    with multiprocessing.get_context('spawn').Pool(3) as pool:
        results = pool.map(_process_prune, [args] * 3)
    assert sum(results) == 1 and store.inspect(identifier)['state'] == 'pruned'


def test_prune_preserves_promoted_copy_and_pagination(stores):
    store, catalog = stores
    first, version = create(store)
    second, _ = create(store)
    catalog.promote(store, first, confirm=True)
    saved = catalog.inspect('fixture', version)
    page = store.list(limit=1)
    prune(store, [first, second])
    assert store.list(before=page['next_cursor'])['proposals'][0]['id'] == first
    assert catalog.inspect('fixture', version) == saved
    assert catalog.prepare('fixture', version, store)['state'] == 'pending'


def test_retirement_keeps_proof_blocks_repromotion_and_new_preparation(stores):
    store, catalog = stores
    identifier, version = create(store)
    catalog.promote(store, identifier, confirm=True)
    saved = catalog.inspect('fixture', version)
    prepared = catalog.prepare('fixture', version, store)
    before = catalog.path.read_bytes()
    plan = VersionCatalog(catalog.path, read_only=True).retire('fixture', version)
    assert not plan['applied'] and 'PRIVATE_SYNTHETIC' not in json.dumps(plan)
    assert catalog.path.read_bytes() == before
    assert catalog.retire('fixture', version, plan_digest=plan['plan_digest'], confirm=True)['applied']
    assert catalog.inspect('fixture', version) == {**saved, 'retired': True}
    assert catalog.list()['versions'][0]['retired'] is True
    for operation in (lambda: catalog.prepare('fixture', version, store),
                      lambda: catalog.promote(store, identifier, confirm=True),
                      lambda: retire(catalog, version)):
        with pytest.raises(PermissionError, match='version_retired'):
            operation()
    # Retirement is not revocation of independent proposals already prepared.
    assert store.inspect(prepared['id'])['state'] == 'pending'
    with closing(sqlite3.connect(catalog.path)) as db:
        for sql in ('DELETE FROM retirements', 'UPDATE retirements SET record_digest=record_digest'):
            with pytest.raises(sqlite3.IntegrityError, match='permanent'):
                db.execute(sql)
            db.rollback()


def test_retirement_does_not_retire_different_version(stores):
    store, catalog = stores
    first, version = create(store)
    catalog.promote(store, first, confirm=True)
    new = catalog.prepare('fixture', version, store, args={'text': 'other'}, output_contract=CONTRACT)
    new_doc = store.inspect(new['id'])
    original_result = store.inspect(first)['result']
    with closing(sqlite3.connect(store.path)) as db, db:
        db.execute("UPDATE proposals SET state='finished',approval=digest,result=? WHERE id=?",
                   (json.dumps(original_result), new['id']))
    catalog.promote(store, new['id'], confirm=True)
    retire(catalog, version)
    assert catalog.prepare('fixture', new_doc['digest'], store)['state'] == 'pending'


def test_retire_confirmation_readonly_and_concurrent_winner(stores):
    store, catalog = stores
    identifier, version = create(store)
    catalog.promote(store, identifier, confirm=True)
    plan = catalog.retire('fixture', version)
    with pytest.raises(PermissionError):
        catalog.retire('fixture', version, confirm=True)
    with pytest.raises(CatalogError, match='plan_changed'):
        catalog.retire('fixture', version, plan_digest='0' * 64, confirm=True)
    with pytest.raises(PermissionError, match='read_only'):
        VersionCatalog(catalog.path, read_only=True).retire('fixture', version, plan_digest=plan['plan_digest'], confirm=True)

    def attempt(_):
        try:
            return VersionCatalog(catalog.path).retire('fixture', version, plan_digest=plan['plan_digest'], confirm=True)['applied']
        except PermissionError:
            return False

    with ThreadPoolExecutor(max_workers=3) as pool:
        assert sum(pool.map(attempt, range(3))) == 1


def test_retirement_commit_failure_preserves_active_version(stores, monkeypatch):
    store, catalog = stores
    identifier, version = create(store)
    catalog.promote(store, identifier, confirm=True)
    original = catalog._transaction

    @contextmanager
    def fail_commit():
        with original() as db:
            yield db
            raise sqlite3.OperationalError('synthetic pre-commit failure')

    with monkeypatch.context() as patch:
        patch.setattr(catalog, '_transaction', fail_commit)
        with pytest.raises(sqlite3.OperationalError):
            retire(catalog, version)
    assert catalog.inspect('fixture', version)['retired'] is False


@pytest.mark.parametrize('command', ['prune', 'retire'])
def test_cli_preview_confirmation_and_missing_database(stores, tmp_path, command):
    store, catalog = stores
    identifier, version = create(store)
    catalog.promote(store, identifier, confirm=True)
    path = store.path if command == 'prune' else catalog.path
    group = 'review' if command == 'prune' else 'catalog'
    arguments = [identifier] if command == 'prune' else ['fixture', version]
    base = [group, '--store', str(path), command, *arguments]
    runner = CliRunner()
    preview = runner.invoke(cli.app, base)
    assert preview.exit_code == 0, preview.output
    digest = json.loads(preview.output)['plan_digest']
    before = path.read_bytes()
    for options, answer in [(['--yes'], None), (['--apply', '--yes'], None),
                            (['--apply', '--plan-digest', digest], 'n\n')]:
        result = runner.invoke(cli.app, base + options, input=answer)
        assert result.exit_code != 0 and path.read_bytes() == before
    applied = runner.invoke(cli.app, base + ['--apply', '--plan-digest', digest, '--yes'])
    assert applied.exit_code == 0, applied.output
    assert json.loads(applied.output)['applied'] is True
    missing = tmp_path / 'absent' / 'store.sqlite3'
    result = runner.invoke(cli.app, [group, '--store', str(missing), command, *arguments])
    assert result.exit_code != 0 and not missing.parent.exists()


def test_old_schema_readonly_preview_and_atomic_upgrade(stores):
    store, catalog = stores
    identifier, version = create(store)
    catalog.promote(store, identifier, confirm=True)
    # Restore the previous table layout as a synthetic v1 fixture.
    for path, drops in [(store.path, ['TRIGGER proposals_pruned_no_update', 'TRIGGER proposals_pruned_no_delete']),
                        (catalog.path, ['TRIGGER retirements_no_update', 'TRIGGER retirements_no_delete', 'TABLE retirements'])]:
        with closing(sqlite3.connect(path)) as db, db:
            for obj in drops:
                db.execute('DROP ' + obj)
            db.execute('PRAGMA user_version=1')
    for path in (store.path, catalog.path):
        with closing(sqlite3.connect(path)) as db:
            assert db.execute('PRAGMA user_version').fetchone()[0] == 1
    rp = review.ReviewStore(store.path, read_only=True).prune([identifier])
    cp = VersionCatalog(catalog.path, read_only=True).retire('fixture', version)
    store = review.ReviewStore(store.path)
    catalog = VersionCatalog(catalog.path)
    assert store.prune([identifier]) == rp and catalog.retire('fixture', version) == cp
    for path in (store.path, catalog.path):
        with closing(sqlite3.connect(path)) as db:
            assert db.execute('PRAGMA user_version').fetchone()[0] == 2
    assert catalog.inspect('fixture', version)['record']['proposal_id'] == identifier


def test_readonly_apply_bool_validation_and_policy_drift(stores, monkeypatch):
    store, catalog = stores
    identifier, version = create(store)
    catalog.promote(store, identifier, confirm=True)
    plan = store.prune([identifier])
    with pytest.raises(PermissionError, match='read_only'):
        review.ReviewStore(store.path, read_only=True).prune([identifier], plan_digest=plan['plan_digest'], confirm=True)
    for value in (1, 'yes', None):
        with pytest.raises(review.ReviewError, match='boolean'):
            store.prune([identifier], confirm=value)
        with pytest.raises(CatalogError, match='boolean'):
            catalog.retire('fixture', version, confirm=value)
    monkeypatch.setattr(review.runner, 'MEMORY', review.runner.MEMORY + 1)
    assert prune(store, [identifier])['applied']
    assert retire(catalog, version)['applied']


@pytest.mark.parametrize('kind', ['review', 'catalog'])
def test_schema_upgrade_failure_is_atomic(stores, monkeypatch, kind):
    store, catalog = stores
    identifier, version = create(store)
    catalog.promote(store, identifier, confirm=True)
    target, cls = (store, review.ReviewStore) if kind == 'review' else (catalog, VersionCatalog)
    drops = (['TRIGGER proposals_pruned_no_update', 'TRIGGER proposals_pruned_no_delete'] if kind == 'review'
             else ['TRIGGER retirements_no_update', 'TRIGGER retirements_no_delete', 'TABLE retirements'])
    with closing(sqlite3.connect(target.path)) as db, db:
        for obj in drops:
            db.execute('DROP ' + obj)
        db.execute('PRAGMA user_version=1')
    before = target.path.read_bytes()
    original = cls._transaction

    @contextmanager
    def fail_upgrade(self):
        with original(self) as db:
            yield db
            raise sqlite3.OperationalError('synthetic upgrade commit failure')

    with monkeypatch.context() as patch:
        patch.setattr(cls, '_transaction', fail_upgrade)
        with pytest.raises(sqlite3.OperationalError):
            cls(target.path)
    assert target.path.read_bytes() == before
    with closing(sqlite3.connect(target.path)) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 1
    cls(target.path)


def test_missing_and_changed_documents_refuse_pruning(stores):
    store, _ = stores
    identifier, _ = create(store)
    with pytest.raises(review.ReviewError, match='not_found'):
        store.prune([identifier, '0' * 32])
    with closing(sqlite3.connect(store.path)) as db, db:
        db.execute("UPDATE proposals SET document='{}' WHERE id=?", (identifier,))
    with pytest.raises(review.ReviewError, match='content_changed'):
        store.prune([identifier])


@pytest.mark.parametrize('receipt', [None, {'error': 'cleanup_unconfirmed', 'resource': 'alita-box-' + 'a' * 32}])
def test_missing_receipt_or_unresolved_cleanup_cannot_be_pruned(stores, receipt):
    store, _ = stores
    identifier, _ = create(store)
    with closing(sqlite3.connect(store.path)) as db, db:
        db.execute('UPDATE proposals SET result=? WHERE id=?',
                   (json.dumps(receipt) if receipt is not None else None, identifier))
    before = store.path.read_bytes()
    with pytest.raises(PermissionError):
        prune(store, [identifier])
    assert store.path.read_bytes() == before


def test_large_result_plan_uses_bounded_metadata_not_payload(stores):
    store, _ = stores
    identifier, _ = create(store)
    with closing(sqlite3.connect(store.path)) as db, db:
        db.execute('UPDATE proposals SET result=? WHERE id=?',
                   (json.dumps({'stdout': '"' * 900_000}), identifier))
    plan = store.prune([identifier])
    assert plan['payload_bytes'] > 1_800_000 and len(json.dumps(plan)) < 1000
    assert store.prune([identifier], plan_digest=plan['plan_digest'], confirm=True)['applied']


@pytest.mark.parametrize('operation', ['prune', 'retire'])
def test_lost_commit_acknowledgement_does_not_reactivate_data(stores, monkeypatch, operation):
    store, catalog = stores
    identifier, version = create(store)
    catalog.promote(store, identifier, confirm=True)
    target = store if operation == 'prune' else catalog
    original = target._transaction

    @contextmanager
    def lost_ack():
        with original() as db:
            yield db
        raise sqlite3.OperationalError('synthetic lost acknowledgement after commit')

    with monkeypatch.context() as patch:
        patch.setattr(target, '_transaction', lost_ack)
        with pytest.raises(sqlite3.OperationalError):
            prune(store, [identifier]) if operation == 'prune' else retire(catalog, version)
    if operation == 'prune':
        assert store.inspect(identifier)['state'] == 'pruned'
        assert store.execute_result(identifier).status is ExecutionStatus.REFUSED
    else:
        assert catalog.inspect('fixture', version)['retired'] is True
        with pytest.raises(PermissionError, match='retired'):
            catalog.prepare('fixture', version, store)


def test_retirement_snapshot_does_not_revoke_inflight_preparation(stores, monkeypatch):
    store, catalog = stores
    identifier, version = create(store)
    catalog.promote(store, identifier, confirm=True)
    original = catalog.inspect

    def inspect_then_retire(name, selected):
        snapshot = original(name, selected)
        retire(catalog, selected)
        return snapshot

    with monkeypatch.context() as patch:
        patch.setattr(catalog, 'inspect', inspect_then_retire)
        prepared = catalog.prepare('fixture', version, store)
    assert store.inspect(prepared['id'])['state'] == 'pending'
    with pytest.raises(PermissionError, match='retired'):
        catalog.prepare('fixture', version, store)
