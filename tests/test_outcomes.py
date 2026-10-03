from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
import json
import sqlite3
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from alita import cli, review
from alita.container_runner import ContainerError, ContainerPolicy
from alita.outcomes import CleanupState, ExecutionOutcome, ExecutionStatus

POLICY = ContainerPolicy('sha256:' + 'a' * 64)
CONTRACT = {'kind': 'stdout-equals', 'expected': 'ok\n'}
RESOURCE = 'alita-box-' + 'c' * 32


@pytest.fixture
def store(tmp_path):
    return review.ReviewStore(tmp_path / 'reviews.sqlite3')


@pytest.fixture(autouse=True)
def executor(monkeypatch):
    factory = Mock(side_effect=AssertionError('Unexpected execution'))
    factory.return_value.name = RESOURCE
    factory.return_value._attempted = False
    factory.return_value._cleanup_confirmed = False
    monkeypatch.setattr(review.runner, 'ContainerExecutor', factory)
    return factory


def proposal(store, *, approved=True, contract=CONTRACT):
    identifier = store.create({'name': 'fixture'}, {'tool.py': "print('ok')\n"}, {}, POLICY, output_contract=contract)
    if approved:
        store.approve(identifier, store.inspect(identifier)['digest'], confirm=True)
    return identifier


def result(raw=b'ok\n', **changes):
    value = {'execution': 'container', 'outcome': 'exited', 'returncode': 0,
             'stdout': raw.decode(), 'stderr': '', 'stdout_bytes': len(raw),
             'stdout_sha256': hashlib.sha256(raw).hexdigest()}
    return {**value, **changes}


def configure(executor, value):
    executor.side_effect = None
    executor.return_value.run.return_value = value


def test_success_requires_a_saved_validated_receipt(store, executor):
    identifier = proposal(store)
    configure(executor, result())
    outcome = store.execute_result(identifier)
    assert isinstance(outcome, ExecutionOutcome)
    assert outcome.status is ExecutionStatus.SUCCEEDED
    assert outcome.approval_consumed is True and outcome.receipt_saved is True
    assert outcome.cleanup is CleanupState.CONFIRMED
    assert outcome.result == store.inspect(identifier)['result']
    encoded = outcome.to_dict()
    assert encoded['status'] == 'succeeded' and encoded['schema_version'] == 1
    assert encoded['automatic_retry_allowed'] is False
    encoded['result']['stdout'] = 'changed'
    assert outcome.result['stdout'] == 'ok\n'
    assert store.inspect(identifier)['result']['stdout'] == 'ok\n'


@pytest.mark.parametrize('value,status', [
    (result(b'wrong\n'), ExecutionStatus.INVALID),
    (result(returncode=1), ExecutionStatus.FAILED),
    (result(returncode=124, outcome='timeout'), ExecutionStatus.TIMEOUT),
    (result(returncode=124, outcome='output_limit'), ExecutionStatus.FAILED),
    (result(returncode=124, outcome='memory_limit'), ExecutionStatus.FAILED),
    (result(returncode=124, outcome='io_failure'), ExecutionStatus.FAILED),
    (result(stdout_sha256=None), ExecutionStatus.INVALID),
])
def test_completed_categories_preserve_actual_process_result(store, executor, value, status):
    identifier = proposal(store)
    configure(executor, value)
    outcome = store.execute_result(identifier)
    assert outcome.status is status and outcome.receipt_saved is True
    assert outcome.result['returncode'] == value['returncode']
    assert outcome.cleanup is CleanupState.CONFIRMED and outcome.approval_consumed is True
    assert store.execute_result(identifier).status is ExecutionStatus.REFUSED
    executor.return_value.run.assert_called_once()


def test_pending_cannot_be_executed_and_refusal_does_not_claim(store, executor):
    identifier = proposal(store, approved=False)
    outcome = store.execute_result(identifier)
    assert outcome.status is ExecutionStatus.REFUSED
    assert outcome.approval_consumed is False and outcome.receipt_saved is False
    assert outcome.cleanup is CleanupState.NOT_STARTED
    assert store.inspect(identifier)['state'] == 'pending'
    executor.assert_not_called()


def test_typed_api_refuses_v1_before_consuming_approval(store, executor):
    identifier = proposal(store, contract=None)
    outcome = store.execute_result(identifier)
    assert outcome.status is ExecutionStatus.REFUSED and outcome.reason == 'output_contract_required'
    assert outcome.approval_consumed is False and store.inspect(identifier)['state'] == 'approved'
    executor.assert_not_called()
    configure(executor, result())
    assert 'output_validation' not in store.execute(identifier)  # Explicit legacy path retained.


@pytest.mark.parametrize('identifier', ['../PRIVATE_SYNTHETIC_SENTINEL', None, '0' * 32])
def test_invalid_or_missing_proposal_has_no_execution_or_error_text(store, executor, identifier):
    outcome = store.execute_result(identifier)
    assert outcome.status is ExecutionStatus.INVALID and outcome.approval_consumed is False
    assert 'PRIVATE_SYNTHETIC_SENTINEL' not in json.dumps(outcome.to_dict())
    if identifier != '0' * 32:
        assert outcome.proposal_id is None
    executor.assert_not_called()


def test_readonly_refusal_is_explicit(store, executor):
    identifier = proposal(store)
    outcome = review.ReviewStore(store.path, read_only=True).execute_result(identifier)
    assert outcome.status is ExecutionStatus.REFUSED and outcome.reason == 'read_only_review_store'
    assert outcome.approval_consumed is False
    executor.assert_not_called()


def test_preflight_failure_consumes_approval_but_did_not_start_container(store, executor):
    identifier = proposal(store)
    executor.side_effect = None
    executor.return_value.run.side_effect = ContainerError('control_unavailable')
    outcome = store.execute_result(identifier)
    assert outcome.status is ExecutionStatus.FAILED
    assert outcome.approval_consumed is True and outcome.receipt_saved is True
    assert outcome.cleanup is CleanupState.NOT_STARTED and outcome.resource is None
    assert store.execute_result(identifier).status is ExecutionStatus.REFUSED


def test_cleanup_unknown_overrides_apparent_result_and_preserves_owned_name(store, executor):
    identifier = proposal(store)
    executor.side_effect = None
    executor.return_value._attempted = True
    executor.return_value.run.side_effect = ContainerError('cleanup_unconfirmed', RESOURCE)
    outcome = store.execute_result(identifier)
    assert outcome.status is ExecutionStatus.CLEANUP_UNKNOWN
    assert outcome.cleanup is CleanupState.UNKNOWN and outcome.resource == RESOURCE
    assert outcome.approval_consumed is True and outcome.receipt_saved is True
    assert outcome.result is None


def test_known_container_failure_can_have_confirmed_removal(store, executor):
    identifier = proposal(store)
    executor.side_effect = None
    executor.return_value._attempted = True
    executor.return_value._cleanup_confirmed = True
    executor.return_value.run.side_effect = ContainerError('container_boundary_mismatch', RESOURCE)
    outcome = store.execute_result(identifier)
    assert outcome.status is ExecutionStatus.FAILED and outcome.cleanup is CleanupState.CONFIRMED
    assert outcome.receipt_saved is True


def test_cleanup_and_receipt_failure_never_claim_persistence(store, executor, monkeypatch):
    identifier = proposal(store)
    executor.side_effect = None
    executor.return_value._attempted = True
    executor.return_value.run.side_effect = ContainerError('cleanup_unconfirmed', RESOURCE)
    monkeypatch.setattr(store, '_finish', Mock(side_effect=sqlite3.OperationalError('PRIVATE_SYNTHETIC_SENTINEL')))
    outcome = store.execute_result(identifier)
    assert outcome.status is ExecutionStatus.CLEANUP_UNKNOWN and outcome.receipt_saved is None
    assert outcome.resource == RESOURCE and outcome.approval_consumed is True
    assert 'PRIVATE_SYNTHETIC_SENTINEL' not in json.dumps(outcome.to_dict())


def test_receipt_failure_after_success_is_indeterminate_not_success(store, executor, monkeypatch):
    identifier = proposal(store)
    configure(executor, result())
    monkeypatch.setattr(store, '_finish', Mock(side_effect=sqlite3.OperationalError('PRIVATE_SYNTHETIC_SENTINEL')))
    outcome = store.execute_result(identifier)
    assert outcome.status is ExecutionStatus.INDETERMINATE
    assert outcome.reason == 'receipt_persistence_unknown' and outcome.receipt_saved is None
    assert outcome.approval_consumed is True and outcome.cleanup is CleanupState.CONFIRMED
    assert outcome.result['output_validation']['status'] == 'passed'
    assert store.inspect(identifier)['state'] == 'claimed'
    assert store.execute_result(identifier).status is ExecutionStatus.REFUSED
    assert 'PRIVATE_SYNTHETIC_SENTINEL' not in json.dumps(outcome.to_dict())


def test_lost_receipt_ack_does_not_trigger_a_second_attempt(store, executor, monkeypatch):
    identifier = proposal(store)
    configure(executor, result())
    finish = store._finish

    def lost_ack(*args):
        finish(*args)
        raise OSError('PRIVATE_SYNTHETIC_SENTINEL')

    monkeypatch.setattr(store, '_finish', lost_ack)
    outcome = store.execute_result(identifier)
    assert outcome.status is ExecutionStatus.INDETERMINATE and outcome.receipt_saved is None
    assert store.inspect(identifier)['state'] == 'finished'
    assert store.execute_result(identifier).status is ExecutionStatus.REFUSED
    executor.return_value.run.assert_called_once()


def test_claim_commit_failure_is_unknown_consumption_without_execution(store, executor, monkeypatch):
    identifier = proposal(store)
    original = store._transaction

    @contextmanager
    def failed_commit():
        with original() as db:
            yield db
            raise sqlite3.OperationalError('PRIVATE_SYNTHETIC_SENTINEL')

    monkeypatch.setattr(store, '_transaction', failed_commit)
    outcome = store.execute_result(identifier)
    assert outcome.status is ExecutionStatus.INDETERMINATE and outcome.reason == 'approval_claim_unknown'
    assert outcome.approval_consumed is None and outcome.receipt_saved is False
    assert outcome.cleanup is CleanupState.NOT_STARTED
    executor.assert_not_called()


def test_unexpected_post_start_failure_is_not_reported_as_refusal(store, executor):
    identifier = proposal(store)
    executor.side_effect = None
    executor.return_value._attempted = True
    executor.return_value.run.side_effect = PermissionError('PRIVATE_SYNTHETIC_SENTINEL')
    outcome = store.execute_result(identifier)
    assert outcome.status is ExecutionStatus.INDETERMINATE and outcome.approval_consumed is True
    assert outcome.cleanup is CleanupState.UNKNOWN and outcome.receipt_saved is False
    assert 'PRIVATE_SYNTHETIC_SENTINEL' not in json.dumps(outcome.to_dict())


def test_unexpected_before_claim_error_is_a_nonconsuming_failure(store, executor, monkeypatch):
    identifier = proposal(store)
    monkeypatch.setattr(store, '_load', Mock(side_effect=RuntimeError('PRIVATE_SYNTHETIC_SENTINEL')))
    outcome = store.execute_result(identifier)
    assert outcome.status is ExecutionStatus.FAILED and outcome.reason == 'review_access_failed'
    assert outcome.approval_consumed is False and outcome.receipt_saved is False
    assert 'PRIVATE_SYNTHETIC_SENTINEL' not in json.dumps(outcome.to_dict())
    executor.assert_not_called()


def test_keyboard_interrupt_propagates_without_replay(store, executor):
    identifier = proposal(store)
    executor.side_effect = None
    executor.return_value.run.side_effect = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        store.execute_result(identifier)
    assert store.inspect(identifier)['state'] == 'claimed'
    assert store.execute_result(identifier).status is ExecutionStatus.REFUSED


def test_typed_concurrent_callers_do_not_confuse_another_calls_consumption(store, executor):
    identifier = proposal(store)
    configure(executor, result())

    def execute(_):
        return review.ReviewStore(store.path).execute_result(identifier)

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(execute, range(5)))
    assert sum(outcome.status is ExecutionStatus.SUCCEEDED for outcome in results) == 1
    assert sum(outcome.approval_consumed is True for outcome in results) == 1
    assert sum(outcome.status is ExecutionStatus.REFUSED for outcome in results) == 4
    executor.return_value.run.assert_called_once()


def test_cli_structured_outcome_has_json_refusal_not_traceback(store, executor):
    identifier = proposal(store, approved=False)
    response = CliRunner().invoke(cli.app, ['review', '--store', str(store.path), 'execute', identifier, '--structured'])
    assert response.exit_code == 1, response.output
    assert json.loads(response.output)['status'] == 'refused'
    assert json.loads(response.output)['automatic_retry_allowed'] is False
    executor.assert_not_called()


@pytest.mark.parametrize('raw,status,exit_code', [(b'ok\n', 'succeeded', 0), (b'wrong\n', 'invalid', 1)])
def test_cli_structured_success_and_mismatch(store, executor, raw, status, exit_code):
    identifier = proposal(store)
    configure(executor, result(raw))
    response = CliRunner().invoke(cli.app, ['review', '--store', str(store.path), 'execute', identifier, '--structured'])
    assert response.exit_code == exit_code, response.output
    data = json.loads(response.output)
    assert data['status'] == status and data['result']['returncode'] == 0
