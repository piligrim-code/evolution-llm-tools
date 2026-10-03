from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
import hashlib
import json
import multiprocessing
import sqlite3
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from alita import cli, review
from alita.catalog import CatalogError, VersionCatalog
from alita.container_runner import ContainerPolicy

POLICY = ContainerPolicy('sha256:' + 'a' * 64)
SPEC = {'name': 'fixture', 'args': [{'name': 'text', 'type': 'string'}]}
SCRIPT = {'tool.py': "print('synthetic')\n"}
ARGS = {'text': 'PRIVATE_SYNTHETIC_ARGUMENT'}
CONTRACT = {'kind': 'stdout-equals', 'expected': 'synthetic\n'}


@pytest.fixture
def reviews(tmp_path):
    return review.ReviewStore(tmp_path / 'reviews.sqlite3')


@pytest.fixture
def catalog(tmp_path):
    return VersionCatalog(tmp_path / 'versions.sqlite3')


@pytest.fixture(autouse=True)
def no_execution(monkeypatch):
    executor = Mock(side_effect=AssertionError('Catalog operations must not execute'))
    monkeypatch.setattr(review.runner, 'ContainerExecutor', executor)
    yield
    executor.assert_not_called()


def record(reviews, *, validated=True, output='synthetic\n', script=SCRIPT, spec=SPEC):
    identifier = reviews.create(spec, script, ARGS, POLICY, output_contract=CONTRACT if validated else None)
    digest = reviews.inspect(identifier)['digest']
    reviews.approve(identifier, digest, confirm=True)
    raw = output.encode()
    result = {'execution': 'container', 'outcome': 'exited', 'returncode': 0, 'stdout': output, 'stderr': '',
              'stdout_sha256': hashlib.sha256(raw).hexdigest(), 'stdout_bytes': len(raw)}
    if validated:
        result['output_validation'] = review.validate_output(CONTRACT, result)
    # Synthetic fixture receipt only; actual execution is covered by Docker tests.
    with closing(sqlite3.connect(reviews.path)) as db, db:
        db.execute("UPDATE proposals SET state='finished',result=? WHERE id=?", (json.dumps(result), identifier))
    return identifier, digest


def test_promotion_requires_confirmation_and_validated_receipt(reviews, catalog):
    identifier, version = record(reviews)
    with pytest.raises(PermissionError, match='explicit_promotion'):
        catalog.promote(reviews, identifier)
    assert catalog.list()['count'] == 0
    result = catalog.promote(reviews, identifier, confirm=True)
    assert result['promoted'] and result['version'] == version
    saved = catalog.inspect('fixture', version)
    assert saved['record']['proposal_id'] == identifier
    assert saved['record']['document'] == reviews.inspect(identifier)['document']
    assert saved['execution_authorized'] is False and saved['integrity_checked'] is True


@pytest.mark.parametrize('state', ['pending', 'approved', 'claimed', 'cancelled'])
def test_unfinished_or_cancelled_proposals_cannot_be_promoted(reviews, catalog, state):
    identifier, _ = record(reviews)
    with closing(sqlite3.connect(reviews.path)) as db, db:
        db.execute('UPDATE proposals SET state=? WHERE id=?', (state, identifier))
    with pytest.raises(PermissionError, match='validated_completed'):
        catalog.promote(reviews, identifier, confirm=True)
    assert catalog.list()['count'] == 0


@pytest.mark.parametrize('kind', ['legacy', 'mismatch', 'forged_flag', 'missing_proof', 'cleanup', 'approval'])
def test_exit_zero_or_stored_pass_flag_is_not_sufficient(reviews, catalog, kind):
    identifier, _ = record(reviews, validated=kind != 'legacy', output='wrong\n' if kind in ('mismatch', 'forged_flag') else 'synthetic\n')
    result = reviews.inspect(identifier)['result']
    if kind == 'forged_flag':
        result['output_validation'] = {'status': 'passed', 'reason': 'expected_output_matched'}
    elif kind == 'missing_proof':
        result.pop('stdout_sha256')
    elif kind == 'cleanup':
        result['error'] = 'cleanup_unconfirmed'
    with closing(sqlite3.connect(reviews.path)) as db, db:
        db.execute('UPDATE proposals SET result=? WHERE id=?', (json.dumps(result), identifier))
        if kind == 'approval':
            db.execute('UPDATE proposals SET approval=NULL WHERE id=?', (identifier,))
    with pytest.raises(PermissionError):
        catalog.promote(reviews, identifier, confirm=True)
    assert catalog.list()['count'] == 0


def test_identical_content_is_idempotent_and_retains_first_provenance(reviews, catalog):
    first, version = record(reviews)
    second, same = record(reviews)
    assert same == version and first != second
    one = catalog.promote(reviews, first, confirm=True)
    two = catalog.promote(reviews, second, confirm=True)
    assert one['promoted'] and not two['promoted'] and one['sequence'] == two['sequence']
    assert catalog.list()['count'] == 1
    assert catalog.inspect('fixture', version)['record']['proposal_id'] == first


def test_changed_source_preserves_old_version(reviews, catalog):
    first, version1 = record(reviews)
    second, version2 = record(reviews, script={'tool.py': "print('synthetic') # revised\n"})
    catalog.promote(reviews, first, confirm=True)
    before = catalog.inspect('fixture', version1)
    catalog.promote(reviews, second, confirm=True)
    assert version1 != version2 and catalog.list(name='fixture')['count'] == 2
    assert before == catalog.inspect('fixture', version1)


def test_catalog_rows_cannot_be_updated_or_deleted(reviews, catalog):
    identifier, version = record(reviews)
    catalog.promote(reviews, identifier, confirm=True)
    with closing(sqlite3.connect(catalog.path)) as db:
        for statement in ('UPDATE versions SET record=record', 'DELETE FROM versions'):
            with pytest.raises(sqlite3.IntegrityError, match='immutable'):
                db.execute(statement)
            db.rollback()
    assert catalog.inspect('fixture', version)['record']['proposal_id'] == identifier


def test_promotion_commit_failure_is_atomic_and_retry_has_no_execution(reviews, catalog, monkeypatch):
    identifier, version = record(reviews)
    original = catalog._transaction

    @contextmanager
    def failed_commit():
        with original() as db:
            yield db
            raise sqlite3.OperationalError('synthetic commit failure')

    with monkeypatch.context() as patch:
        patch.setattr(catalog, '_transaction', failed_commit)
        with pytest.raises(sqlite3.OperationalError):
            catalog.promote(reviews, identifier, confirm=True)
    assert catalog.list()['count'] == 0
    assert reviews.inspect(identifier)['state'] == 'finished'
    assert catalog.promote(reviews, identifier, confirm=True)['version'] == version


def test_concurrent_promotion_has_one_immutable_winner(reviews, catalog):
    identifier, _ = record(reviews)

    def promote(_):
        return VersionCatalog(catalog.path).promote(review.ReviewStore(reviews.path, read_only=True), identifier, confirm=True)

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(promote, range(6)))
    assert sum(result['promoted'] for result in results) == 1
    assert catalog.list()['count'] == 1


def _process_promote(arguments):
    catalog_path, reviews_path, identifier = arguments
    review.runner.ContainerExecutor = Mock(side_effect=AssertionError('No execution in worker'))
    return VersionCatalog(catalog_path).promote(review.ReviewStore(reviews_path, read_only=True), identifier, confirm=True)


def test_independent_processes_cannot_duplicate_a_version(reviews, catalog):
    identifier, _ = record(reviews)
    with multiprocessing.get_context('spawn').Pool(3) as pool:
        results = pool.map(_process_promote, [(str(catalog.path), str(reviews.path), identifier)] * 3)
    assert sum(result['promoted'] for result in results) == 1
    assert catalog.list()['count'] == 1


def test_prepare_creates_new_pending_proposal_not_reused_approval(reviews, catalog):
    identifier, version = record(reviews)
    catalog.promote(reviews, identifier, confirm=True)
    prepared = catalog.prepare('fixture', version, reviews)
    assert prepared['id'] != identifier and prepared['state'] == 'pending'
    assert prepared['source_version'] == version
    fresh = reviews.inspect(prepared['id'])
    assert fresh['document'] == reviews.inspect(identifier)['document']
    assert fresh['digest'] == version and fresh['result'] is None
    with pytest.raises(PermissionError):
        reviews.execute(prepared['id'])
    assert reviews.inspect(identifier)['state'] == 'finished'


def test_new_args_require_new_expectation_and_fresh_approval(reviews, catalog):
    identifier, version = record(reviews)
    catalog.promote(reviews, identifier, confirm=True)
    with pytest.raises(CatalogError, match='new_arguments'):
        catalog.prepare('fixture', version, reviews, args={'text': 'changed'})
    with pytest.raises(CatalogError, match='new_arguments'):
        catalog.prepare('fixture', version, reviews, output_contract=CONTRACT)
    new = catalog.prepare('fixture', version, reviews, args={'text': 'changed'},
                          output_contract={'kind': 'stdout-equals', 'expected': 'different\n'})
    fresh = reviews.inspect(new['id'])
    assert fresh['digest'] != version and fresh['document']['args'] == {'text': 'changed'}
    assert fresh['state'] == 'pending' and fresh['result'] is None


@pytest.mark.parametrize('version', ['latest', 'a' * 8, 'A' * 64, 'sha256:' + 'a' * 64, '', None])
def test_version_selection_is_explicit(reviews, catalog, version):
    with pytest.raises(CatalogError, match='explicit_full_version'):
        catalog.inspect('fixture', version)
    with pytest.raises(CatalogError, match='explicit_full_version'):
        catalog.prepare('fixture', version, reviews)


def test_wrong_name_does_not_select_another_tool(reviews, catalog):
    identifier, version = record(reviews)
    catalog.promote(reviews, identifier, confirm=True)
    with pytest.raises(CatalogError, match='version_not_found'):
        catalog.inspect('other', version)


def test_policy_drift_preserves_audit_but_refuses_reuse(reviews, catalog, monkeypatch):
    identifier, version = record(reviews)
    catalog.promote(reviews, identifier, confirm=True)
    monkeypatch.setattr(review.runner, 'BOOTSTRAP', review.runner.BOOTSTRAP + '\n')
    assert catalog.inspect('fixture', version)['integrity_checked'] is True
    with pytest.raises(CatalogError, match='policy_or_contract_changed'):
        catalog.prepare('fixture', version, reviews)
    assert reviews.list()['count'] == 1


def test_history_can_prepare_after_original_journal_is_unavailable(reviews, catalog, tmp_path):
    identifier, version = record(reviews)
    catalog.promote(reviews, identifier, confirm=True)
    new_reviews = review.ReviewStore(tmp_path / 'new-reviews.sqlite3')
    new = catalog.prepare('fixture', version, new_reviews)
    assert new_reviews.inspect(new['id'])['state'] == 'pending'


def test_tampered_record_is_not_inspected_or_prepared(reviews, catalog):
    identifier, version = record(reviews)
    catalog.promote(reviews, identifier, confirm=True)
    with closing(sqlite3.connect(catalog.path)) as db, db:
        db.execute('DROP TRIGGER versions_no_update')
        db.execute("UPDATE versions SET record='{}'")
    with pytest.raises(CatalogError, match='record_changed'):
        catalog.inspect('fixture', version)
    with pytest.raises(CatalogError):
        catalog.prepare('fixture', version, reviews)


def test_catalog_and_review_journals_cannot_be_mistaken_for_each_other(reviews, catalog):
    before_catalog, before_reviews = catalog.path.read_bytes(), reviews.path.read_bytes()
    for read_only in (False, True):
        with pytest.raises(CatalogError):
            VersionCatalog(reviews.path, read_only=read_only)
        with pytest.raises(review.ReviewError, match='not_a_review_store'):
            review.ReviewStore(catalog.path, read_only=read_only)
    assert before_catalog == catalog.path.read_bytes()
    assert before_reviews == reviews.path.read_bytes()


def test_read_only_missing_catalog_does_not_create_directories(tmp_path):
    path = tmp_path / 'absent' / 'versions.sqlite3'
    with pytest.raises(CatalogError, match='catalog_not_found'):
        VersionCatalog(path, read_only=True)
    assert not path.parent.exists()


def test_read_only_catalog_can_read_and_prepare_but_not_promote(reviews, catalog):
    identifier, version = record(reviews)
    catalog.promote(reviews, identifier, confirm=True)
    before = catalog.path.read_bytes()
    reader = VersionCatalog(catalog.path, read_only=True)
    assert reader.list()['count'] == 1
    assert reader.inspect('fixture', version)['integrity_checked']
    assert reader.prepare('fixture', version, reviews)['state'] == 'pending'
    with pytest.raises(PermissionError, match='read_only'):
        reader.promote(reviews, identifier, confirm=True)
    assert before == catalog.path.read_bytes()


def test_metadata_listing_is_bounded_and_omits_proofs(reviews, catalog):
    versions = []
    for i in range(4):
        identifier, version = record(reviews, script={'tool.py': "print('synthetic') # " + str(i)})
        catalog.promote(reviews, identifier, confirm=True)
        versions.append(version)
    first = catalog.list(name='fixture', limit=2)
    second = catalog.list(name='fixture', limit=2, before=first['next_cursor'])
    assert [row['version'] for page in (first, second) for row in page['versions']] == versions[::-1]
    assert second['next_cursor'] is None
    assert 'PRIVATE_SYNTHETIC' not in json.dumps(first)
    assert first['integrity_checked'] is False and first['content_included'] is False


@pytest.mark.parametrize('kwargs', [{'limit': 0}, {'limit': True}, {'limit': 101}, {'before': 0},
                                   {'before': True}, {'before': '1'}, {'before': 2**63}])
def test_invalid_list_arguments_refused(catalog, kwargs):
    with pytest.raises(CatalogError):
        catalog.list(**kwargs)


def test_unknown_cursor_is_not_silently_ignored(catalog):
    with pytest.raises(CatalogError, match='cursor_not_found'):
        catalog.list(before=999)


def test_failed_initialization_rolls_back_schema_without_touching_reviews(reviews, tmp_path, monkeypatch):
    before = reviews.path.read_bytes()
    path = tmp_path / 'new-catalog.sqlite3'
    with monkeypatch.context() as patch:
        patch.setattr(VersionCatalog, '_check_schema', Mock(side_effect=RuntimeError('synthetic initialization interruption')))
        with pytest.raises(RuntimeError):
            VersionCatalog(path)
    with closing(sqlite3.connect(path)) as db:
        assert db.execute('SELECT name FROM sqlite_master').fetchall() == []
        assert db.execute('PRAGMA application_id').fetchone()[0] == 0
        assert db.execute('PRAGMA user_version').fetchone()[0] == 0
    assert before == reviews.path.read_bytes()
    assert VersionCatalog(path).list()['count'] == 0


def test_failed_prepare_leaves_catalog_and_review_journal_unchanged(reviews, catalog, monkeypatch):
    identifier, version = record(reviews)
    catalog.promote(reviews, identifier, confirm=True)
    before = catalog.path.read_bytes()
    with monkeypatch.context() as patch:
        patch.setattr(reviews, 'create', Mock(side_effect=sqlite3.OperationalError('synthetic disk full')))
        with pytest.raises(sqlite3.OperationalError):
            catalog.prepare('fixture', version, reviews)
    assert before == catalog.path.read_bytes() and reviews.list()['count'] == 1


def test_future_catalog_schema_is_not_reinitialized(catalog):
    with closing(sqlite3.connect(catalog.path)) as db, db:
        db.execute('PRAGMA user_version=99')
    before = catalog.path.read_bytes()
    for read_only in (True, False):
        with pytest.raises(CatalogError, match='supported_version_catalog'):
            VersionCatalog(catalog.path, read_only=read_only)
    assert before == catalog.path.read_bytes()


def test_cli_refused_confirmation_creates_no_catalog(reviews, tmp_path):
    identifier, _ = record(reviews)
    path = tmp_path / 'never' / 'versions.sqlite3'
    result = CliRunner().invoke(cli.app, ['catalog', '--store', str(path), '--review-store', str(reviews.path),
                                         'promote', identifier], input='n\n')
    assert result.exit_code != 0
    assert not path.parent.exists()


def test_cli_promote_inspect_and_prepare_never_execute(reviews, catalog):
    identifier, version = record(reviews)
    runner = CliRunner()
    prefix = ['catalog', '--store', str(catalog.path), '--review-store', str(reviews.path)]
    promoted = runner.invoke(cli.app, prefix + ['promote', identifier, '--yes'])
    assert promoted.exit_code == 0, promoted.output
    assert json.loads(promoted.output)['version'] == version
    inspected = runner.invoke(cli.app, prefix + ['inspect', 'fixture', version])
    assert inspected.exit_code == 0, inspected.output
    assert json.loads(inspected.output)['execution_authorized'] is False
    prepared = runner.invoke(cli.app, prefix + ['prepare', 'fixture', version])
    assert prepared.exit_code == 0, prepared.output
    assert reviews.inspect(json.loads(prepared.output)['id'])['state'] == 'pending'
