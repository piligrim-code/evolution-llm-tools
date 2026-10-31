"""Reuse-or-generate tests promote handwritten receipts; no Docker or model."""
import hashlib
import json
from unittest.mock import Mock

import pytest

from alita.admission import prepare_admission_case
from alita.catalog import CatalogError, VersionCatalog
from alita.container_runner import ContainerPolicy
from alita.evaluation_corpus_v2 import get_task
from alita.review import ReviewStore
from alita.skill_index import coarse_type, contract_signature, decide, find_reusable, prepare_reuse_check

IMAGE = 'sha256:' + 'a' * 64


@pytest.fixture(autouse=True)
def no_provider(monkeypatch):
    provider = Mock(side_effect=AssertionError('Index tests must not call a provider'))
    monkeypatch.setattr('alita.llm.OllamaClient.generate_result', provider)
    yield
    provider.assert_not_called()


def promote(catalog, reviews, monkeypatch, task_id):
    case = get_task(task_id)['cases'][0]
    prepared = prepare_admission_case(task_id, case['id'], {'tool.py': f'# {task_id}\n'}, ContainerPolicy(IMAGE), reviews)
    output = json.dumps(case['expected'], sort_keys=True, separators=(',', ':'))

    class Executor:
        def __init__(self, policy):
            self._attempted = self._cleanup_confirmed = False

        def run(self, scripts, args):
            self._attempted = self._cleanup_confirmed = True
            return {'returncode': 0, 'stdout': output, 'stdout_sha256': hashlib.sha256(output.encode()).hexdigest(),
                    'stdout_bytes': len(output), 'stderr': '', 'execution': 'container', 'outcome': 'exited'}

    monkeypatch.setattr('alita.review.runner.ContainerExecutor', Executor)
    reviews.approve(prepared['proposal_id'], reviews.inspect(prepared['proposal_id'])['digest'], confirm=True)
    reviews.execute_result(prepared['proposal_id'])
    return catalog.promote(reviews, prepared['proposal_id'], confirm=True)


@pytest.fixture
def stocked(tmp_path, monkeypatch):
    reviews, catalog = ReviewStore(tmp_path / 'r.sqlite3'), VersionCatalog(tmp_path / 'v.sqlite3')
    promoted = {task: promote(catalog, reviews, monkeypatch, task) for task in ('integer-sum', 'median', 'dot-product')}
    return catalog, promoted


def test_signature_keeps_coarse_json_types_and_ignores_data_dependent_detail():
    assert [coarse_type(v) for v in (True, 1, 1.0, 'a', [], {}, None)] == \
        ['boolean', 'integer', 'number', 'string', 'array', 'object', 'null']
    assert contract_signature({'data': {'values': [1]}}, {'result': 1}) == 'data{values:array}->integer'
    assert contract_signature({'data': {'values': [1]}}, {'result': 1}) != \
        contract_signature({'data': {'values': [1]}}, {'result': 1.0})
    # Word-count style results have data-dependent keys; the contract is the same.
    assert contract_signature({'data': {'text': 'Red red'}}, {'result': {'red': 2}}) == \
        contract_signature({'data': {'text': 'a b'}}, {'result': {'a': 1, 'b': 1}})
    with pytest.raises(CatalogError, match='contract_shape'):
        contract_signature({'values': [1]}, {'result': 1})


def test_paraphrased_request_with_same_contract_leads_to_verification(stocked):
    catalog, promoted = stocked
    decision = decide(catalog, args={'data': {'values': [4, 5]}}, expected={'result': 9},
                      description='Add up all the integers in values and return the total.')
    assert decision['action'] == 'verify_reuse' and decision['fallback'] == 'generate'
    assert decision['selected']['name'] == promoted['integer-sum']['name']
    assert decision['estimated_cost'] == {'model_requests': 0, 'executions': 1}
    assert decision['execution_authorized'] is False


def test_output_type_separates_tasks_with_identical_inputs(stocked):
    catalog, promoted = stocked
    matches = find_reusable(catalog, args={'data': {'values': [5, 1, 3]}}, expected={'result': 3.0},
                            description='Return the median of integer values.')
    assert [m['name'] for m in matches] == [promoted['median']['name']]


def test_unknown_contract_generates(stocked):
    catalog, _ = stocked
    unknown = decide(catalog, args={'data': {'text': 'x'}}, expected={'result': True},
                     description='Return whether parentheses are balanced.')
    assert unknown['action'] == 'generate' and 'no catalog version' in unknown['reason']
    assert unknown['selected'] is None and unknown['fallback'] is None
    assert unknown['estimated_cost'] == {'model_requests': 1, 'executions': 8}


def test_shared_contract_is_only_a_candidate_until_the_requesters_example_passes(tmp_path, monkeypatch):
    reviews, catalog = ReviewStore(tmp_path / 'r.sqlite3'), VersionCatalog(tmp_path / 'v.sqlite3')
    promote(catalog, reviews, monkeypatch, 'stable-unique')
    # run-length shares the contract data{values:array}->array with stable-unique.
    args, expected = {'data': {'values': [1, 1, 2]}}, {'result': [[1, 2], [2, 1]]}
    decision = decide(catalog, args=args, expected=expected, description='Return runs of equal values.')
    assert decision['action'] == 'verify_reuse' and decision['selected']['name'] == 'eval_stable_unique'
    check = prepare_reuse_check(catalog, reviews, decision, args=args, expected=expected)
    document = reviews.inspect(check['id'])['document']
    assert check['state'] == 'pending' and document['args'] == args
    assert document['output_contract'] == {'kind': 'json-object-equals', 'expected': expected}
    with pytest.raises(CatalogError, match='contract_changed'):
        prepare_reuse_check(catalog, reviews, decision, args={'data': {'text': 'x'}}, expected=expected)
    with pytest.raises(CatalogError, match='verify_decision'):
        prepare_reuse_check(catalog, reviews, {'action': 'generate'}, args=args, expected=expected)


def test_retired_versions_are_never_offered(stocked):
    catalog, promoted = stocked
    chosen = promoted['integer-sum']
    plan = catalog.retire(chosen['name'], chosen['version'])
    catalog.retire(chosen['name'], chosen['version'], plan_digest=plan['plan_digest'], confirm=True)
    decision = decide(catalog, args={'data': {'values': [4, 5]}}, expected={'result': 9},
                      description='Sum the integer values. Empty input has sum zero.')
    assert decision['action'] == 'generate'
