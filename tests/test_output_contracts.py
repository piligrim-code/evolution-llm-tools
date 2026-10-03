from contextlib import closing
import hashlib
import io
import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from alita import cli, review
from alita.container_runner import ContainerExecutor, ContainerPolicy, ContainerError, OUTPUT_LIMIT, _display_text
from alita.output_contracts import normalize_output_contract, validate_output

POLICY = ContainerPolicy('sha256:' + 'a' * 64)
SPEC = {'name': 'fixture', 'args': [{'name': 'text', 'type': 'string'}]}
SCRIPTS = {'tool.py': "print('synthetic')\n"}
ARGS = {'text': 'synthetic'}
CONTRACT = {'kind': 'stdout-equals', 'expected': 'synthetic\n'}


def captured(raw, **changes):
    result = {'execution': 'container', 'returncode': 0, 'outcome': 'exited',
              'stdout': _display_text(raw), 'stderr': '',
              'stdout_sha256': hashlib.sha256(raw).hexdigest(), 'stdout_bytes': len(raw)}
    result.update(changes)
    return result


@pytest.fixture(autouse=True)
def executor(monkeypatch):
    factory = Mock(side_effect=AssertionError('Unexpected execution'))
    monkeypatch.setattr(review.runner, 'ContainerExecutor', factory)
    return factory


@pytest.fixture
def store(tmp_path):
    return review.ReviewStore(tmp_path / 'reviews.sqlite3')


def create(store, contract=CONTRACT):
    return store.create(SPEC, SCRIPTS, ARGS, POLICY, output_contract=contract)


def approve(store, identifier):
    store.approve(identifier, store.inspect(identifier)['digest'], confirm=True)


@pytest.mark.parametrize('value', [None, {}, [], {'kind': 'eval', 'expected': 'print(1)'},
    {'kind': 'stdout-equals', 'expected': 1}, {'kind': 'stdout-equals', 'expected': 'x', 'network': True},
    {'kind': 'json-object-equals', 'expected': []}, {'kind': 'json-object-equals', 'expected': {1: 'x'}},
    {'kind': 'json-object-equals', 'expected': {'x': (1, 2)}},
    {'kind': 'json-object-equals', 'expected': {'x': float('nan')}},
    {'kind': 'json-object-equals', 'expected': {'x': float('inf')}},
    {'kind': 'stdout-equals', 'expected': '\ud800'},
    {'kind': 'stdout-equals', 'expected': 'ok\x00'},
    {'kind': 'stdout-equals', 'expected': 'x' * (OUTPUT_LIMIT + 1)}])
def test_invalid_contracts_are_refused(value):
    with pytest.raises(ValueError):
        normalize_output_contract(value)


def test_contract_copy_does_not_share_nested_expected_value():
    contract = {'kind': 'json-object-equals', 'expected': {'x': [1]}}
    clean = normalize_output_contract(contract)
    contract['expected']['x'].append(2)
    assert clean['expected'] == {'x': [1]}


@pytest.mark.parametrize('raw,expected,passed', [(b'9\n', '9\n', True), (b'9\n', '9', False),
    (b'', '', True), (b'ok\x00', 'ok', False), (b'\xff', '\ufffd', False)])
def test_text_assertion_uses_exact_raw_bytes_not_display(raw, expected, passed):
    result = validate_output({'kind': 'stdout-equals', 'expected': expected}, captured(raw))
    assert result['status'] == ('passed' if passed else 'failed')


@pytest.mark.parametrize('raw,expected,passed', [
    (b'{"b":2, "a":1}\n', {'a': 1, 'b': 2}, True),
    (b'{"a":true}', {'a': 1}, False), (b'{"a":1.0}', {'a': 1}, False),
    (b'{"a":1}', {'a': 1.0}, False), (b'{"a":1,"extra":2}', {'a': 1}, False),
    (b'{"a":[2,1]}', {'a': [1, 2]}, False), (b'{"a":[1,2]}', {'a': [1, 2]}, True),
    (b'{"a":null}', {'a': None}, True),
])
def test_json_objects_compare_structure_without_type_coercion(raw, expected, passed):
    result = validate_output({'kind': 'json-object-equals', 'expected': expected}, captured(raw))
    assert result['status'] == ('passed' if passed else 'failed')


@pytest.mark.parametrize('raw', [b'{"a":1,"a":1}', b'{"a":NaN}', b'{"a":1e999}',
    b'[]', b'prefix {"a":1}', b'{"a":1} trailing', b'{"a":1}\x00', b'{"a":1}\xff', b'{\r\n"a":1}'])
def test_ambiguous_or_sanitized_json_cannot_pass(raw):
    result = validate_output({'kind': 'json-object-equals', 'expected': {'a': 1}}, captured(raw))
    assert result['status'] == 'failed'


@pytest.mark.parametrize('change', [{'stdout_sha256': None}, {'stdout_sha256': 'a'},
    {'stdout_bytes': True}, {'stdout_bytes': -1}, {'stdout_bytes': OUTPUT_LIMIT + 1}])
def test_missing_or_invalid_stdout_evidence_is_not_a_pass(change):
    result = validate_output(CONTRACT, captured(b'synthetic\n', **change))
    assert result == {'status': 'failed', 'reason': 'stdout_evidence_missing'}


@pytest.mark.parametrize('change', [{'returncode': 1}, {'returncode': 124, 'outcome': 'timeout'},
                                   {'outcome': 'output_limit'}, {'outcome': 'memory_limit'}])
def test_failed_or_limited_execution_is_not_validated_even_with_matching_stdout(change):
    result = validate_output(CONTRACT, captured(b'synthetic\n', **change))
    assert result == {'status': 'not_checked', 'reason': 'execution_not_successful'}


def test_contract_is_digest_bound_and_old_document_remains_v1(store):
    legacy = create(store, None)
    checked = create(store)
    legacy_doc, checked_doc = store.inspect(legacy), store.inspect(checked)
    assert legacy_doc['document']['version'] == 1 and 'output_contract' not in legacy_doc['document']
    assert checked_doc['document']['version'] == 2 and checked_doc['document']['output_contract'] == CONTRACT
    assert legacy_doc['digest'] != checked_doc['digest']
    approve(store, checked)
    with closing(sqlite3.connect(store.path)) as db, db:
        document = checked_doc['document']
        document['output_contract']['expected'] = 'changed'
        db.execute('UPDATE proposals SET document=? WHERE id=?', (json.dumps(document), checked))
    with pytest.raises(review.ReviewError, match='content_changed'):
        store.execute(checked)


@pytest.mark.parametrize('change', ['remove', 'downgrade', 'null', 'rehashed'])
def test_output_check_cannot_be_removed_from_approved_proposal(store, change):
    identifier = create(store)
    approve(store, identifier)
    document = store.inspect(identifier)['document']
    if change == 'remove':
        document.pop('output_contract')
    elif change == 'downgrade':
        document['version'] = 1
    elif change == 'null':
        document['output_contract'] = None
    else:
        document['output_contract']['expected'] = 'changed'
    encoded = review._json(document)
    with closing(sqlite3.connect(store.path)) as db, db:
        db.execute('UPDATE proposals SET document=? WHERE id=?', (encoded, identifier))
        if change == 'rehashed':
            db.execute('UPDATE proposals SET digest=? WHERE id=?', (review._digest(encoded), identifier))
    with pytest.raises((ValueError, PermissionError)):
        store.execute(identifier)


@pytest.mark.parametrize('raw,passed', [(b'synthetic\n', True), (b'wrong\n', False)])
def test_v2_result_is_persisted_and_receipt_consumed_even_on_mismatch(store, executor, raw, passed):
    identifier = create(store)
    approve(store, identifier)
    executor.side_effect = None
    executor.return_value.run.return_value = captured(raw)
    result = store.execute(identifier)
    assert result['output_validation']['status'] == ('passed' if passed else 'failed')
    assert store.inspect(identifier)['result'] == result
    assert store.inspect(identifier)['state'] == 'finished'
    with pytest.raises(PermissionError):
        store.execute(identifier)
    executor.return_value.run.assert_called_once()


def test_v1_success_is_not_silently_claimed_output_validated(store, executor):
    identifier = create(store, None)
    approve(store, identifier)
    executor.side_effect = None
    executor.return_value.run.return_value = captured(b'anything\n')
    result = store.execute(identifier)
    assert 'output_validation' not in result
    assert result['returncode'] == 0


def test_output_validator_failure_cannot_replay(store, executor, monkeypatch):
    identifier = create(store)
    approve(store, identifier)
    executor.side_effect = None
    executor.return_value.run.return_value = captured(b'synthetic\n')
    monkeypatch.setattr(review, 'validate_output', Mock(side_effect=RuntimeError('synthetic verifier failure')))
    with pytest.raises(RuntimeError):
        store.execute(identifier)
    assert store.inspect(identifier)['state'] == 'claimed'
    with pytest.raises(PermissionError):
        store.execute(identifier)


def test_v2_receipt_persistence_failure_keeps_attempt_claimed(store, executor, monkeypatch):
    identifier = create(store)
    approve(store, identifier)
    executor.side_effect = None
    executor.return_value.run.return_value = captured(b'synthetic\n')
    monkeypatch.setattr(store, '_finish', Mock(side_effect=sqlite3.OperationalError('synthetic disk full')))
    with pytest.raises(sqlite3.OperationalError):
        store.execute(identifier)
    assert store.inspect(identifier)['state'] == 'claimed'
    with pytest.raises(PermissionError):
        store.execute(identifier)


def test_cleanup_error_takes_precedence_over_output_assertion(store, executor, monkeypatch):
    identifier = create(store)
    approve(store, identifier)
    executor.side_effect = None
    executor.return_value.run.side_effect = ContainerError('cleanup_unconfirmed', 'owned-fixture')
    checker = Mock(side_effect=AssertionError('Cannot validate without confirmed cleanup'))
    monkeypatch.setattr(review, 'validate_output', checker)
    with pytest.raises(ContainerError):
        store.execute(identifier)
    checker.assert_not_called()
    assert store.inspect(identifier)['result']['error'] == 'cleanup_unconfirmed'


def test_cli_exit_zero_is_overridden_by_failed_output_check(store, executor):
    identifier = create(store)
    approve(store, identifier)
    executor.side_effect = None
    executor.return_value.run.return_value = captured(b'wrong\n')
    result = CliRunner().invoke(cli.app, ['review', '--store', str(store.path), 'execute', identifier])
    assert result.exit_code == 1, result.output
    assert json.loads(result.output)['returncode'] == 0
    assert json.loads(result.output)['output_validation']['status'] == 'failed'


def test_cli_contract_is_visible_but_not_sent_to_provider(store, monkeypatch):
    from alita import llm
    expected = 'EXPECTED_PRIVATE_SYNTHETIC_SENTINEL'
    provider = Mock()
    provider.generate.side_effect = [json.dumps(SPEC), SCRIPTS['tool.py'] + 'REQUIREMENTS: none']
    monkeypatch.setattr(llm, 'OllamaClient', Mock(return_value=provider))
    contract = {'kind': 'stdout-equals', 'expected': expected}
    result = CliRunner().invoke(cli.app, ['review', '--store', str(store.path), 'propose', 'synthetic',
        '--container-image', POLICY.image, '--output-contract', json.dumps(contract)])
    assert result.exit_code == 0, result.output
    identifier = json.loads(result.output)['id']
    assert store.inspect(identifier)['document']['output_contract'] == contract
    assert expected not in str(provider.generate.call_args_list)


def test_invalid_contract_refused_before_model_call(store, monkeypatch):
    from alita import llm
    provider = Mock(side_effect=AssertionError('Must not contact provider'))
    monkeypatch.setattr(llm, 'OllamaClient', provider)
    with pytest.raises(ValueError):
        review.propose('synthetic', 'fixture', POLICY, store, output_contract={'kind': 'eval', 'expected': 'x'})
    provider.assert_not_called()


def test_executor_hashes_original_stdout_before_terminal_sanitization(monkeypatch):
    raw = b'{"a":1}\x00\xff\n'
    instance = ContainerExecutor(POLICY)
    instance.endpoint, instance.container_id = 'unix:///unused.sock', 'b' * 64
    process = SimpleNamespace(stdin=io.BytesIO(), stdout=io.BytesIO(raw), stderr=io.BytesIO(),
                              poll=Mock(return_value=0))
    monkeypatch.setattr(review.runner.subprocess, 'Popen', Mock(return_value=process))
    monkeypatch.setattr(instance, '_owned', Mock(return_value={'State': {'Running': False, 'Status': 'exited', 'ExitCode': 0}}))
    result = instance._execute(b'{}')
    assert result['stdout_sha256'] == hashlib.sha256(raw).hexdigest()
    assert result['stdout_bytes'] == len(raw)
    assert result['stdout'] == _display_text(raw)
    assert process.stdin.closed and process.stdout.closed and process.stderr.closed
