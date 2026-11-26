"""Generalization groundwork: handwritten replies and predetermined executor results; no model or Docker."""
import json

import pytest

from alita.admission import AdmissionLedger, prepare_admission_case
from alita.catalog import VersionCatalog
from alita.container_runner import ContainerPolicy
from alita.evaluation_corpus_v2 import corpus_digest, get_task
from alita.generalization import (BoundMember, GeneralizationError, Member, checked_documentation,
                                  family_decision, find_families, generalization_prompt, generate_generalization,
                                  record_generalization)
from alita.review import ReviewStore
from alita.user_tasks import UserTaskSource
from tests.test_user_tasks import IMAGE, no_provider, reply, run_cases  # noqa: F401


def max_task(**changes):
    document = {
        'format': 'toolwright-user-task-v1', 'id': 'values-max',
        'instruction': 'Return the largest integer in values.',
        'examples': [{'id': 'two', 'data': {'values': [3, 9]}, 'result': 9}],
        'held_out': [{'id': 'one', 'data': {'values': [5]}, 'result': 5},
                     {'id': 'negative', 'data': {'values': [-4, -2]}, 'result': -2},
                     {'id': 'many', 'data': {'values': [1, 7, 7, 2]}, 'result': 7}],
    }
    document.update(changes)
    return document


def family(**changes):
    return [Member('sum', 'integer-sum'), Member('max', 'values-max', UserTaskSource(max_task(**changes)))]


DOC = {'name': 'reduce_values', 'description': 'Reduce integer values with the selected operation.',
       'options': [{'name': 'operation', 'type': 'string', 'description': '"sum" or "max"'}],
       'bindings': {'max': {'operation': 'max'}, 'sum': {'operation': 'sum'}}}
SOURCE = 'import json\nimport sys\nTOOLWRIGHT_DOC = ' + repr(DOC) + '\nprint(1)\n'


def generalized_reply(members, source=SOURCE):
    return reply(generalization_prompt(members), '```python\n' + source + '```')


def test_families_group_members_by_contract_signature():
    members = [*family(), Member('median', 'median'), Member('dot', 'dot-product')]
    found = find_families(members)
    assert [f['members'] for f in found['families']] == [['max', 'sum']]
    assert found['families'][0]['signature'] == 'data{values:array}->integer'
    assert found['families'][0]['similarity'][0]['members'] == ['max', 'sum']
    # median examples return both integers and numbers, so it has no single signature.
    assert [s['member'] for s in found['skipped']] == ['median']


def test_prompt_shows_examples_of_every_member_and_no_held_out_input():
    members = family()
    prompt = generalization_prompt(members)
    assert prompt.startswith('Toolwright generalization prompt general-v1.')
    assert 'Variant max: Return the largest integer in values.' in prompt and 'Variant sum:' in prompt
    assert '{"values":[3,9]} -> {"result":9}' in prompt and 'TOOLWRIGHT_DOC' in prompt
    for member in members:
        for held in member.held_out_inputs():
            assert held not in prompt
    assert generalization_prompt(list(reversed(members))) == prompt
    leaking = family(instruction='Return the largest integer in values, e.g. {"values":[42]}.')
    with pytest.raises(PermissionError, match='held_out_input'):
        generalization_prompt(leaking)


@pytest.mark.parametrize('members,reason', [
    (lambda: family()[:1], 'two_to_four'),
    (lambda: [Member('sum', 'integer-sum'), Member('sum', 'values-max', UserTaskSource(max_task()))], 'duplicate_member_key'),
    (lambda: [Member('a', 'integer-sum'), Member('b', 'integer-sum')], 'duplicate_member_task'),
    (lambda: [Member('sum', 'integer-sum'), Member('med', 'median')], 'different_contracts'),
])
def test_families_are_validated(members, reason):
    with pytest.raises(GeneralizationError, match=reason):
        generalization_prompt(members())


def test_reply_is_bound_and_documentation_is_read_without_execution():
    members = family()
    record, source = record_generalization(members, generalized_reply(members))
    assert source == SOURCE and record['status'] == 'unreviewed_source'
    assert record['documentation']['bindings'] == DOC['bindings'] and record['execution_authorized'] is False
    assert [m['key'] for m in record['members']] == ['max', 'sum']
    hostile = 'import json\nimport sys\nTOOLWRIGHT_DOC = __import__("os").system("exit 3")\n'
    record, source = record_generalization(members, generalized_reply(members, hostile))
    assert source is None and record['source_check']['reason'] == 'toolwright_doc_must_be_a_literal'
    record, source = record_generalization(members, generalized_reply(members, 'import json\nprint(1)\n'))
    assert source is None and record['source_check']['reason'] == 'expected_one_toolwright_doc'
    other = generalization_prompt([Member('sum', 'integer-sum'), Member('max', 'values-max',
                                                                        UserTaskSource(max_task(instruction='Other.')))])
    with pytest.raises(ValueError, match='binding_mismatch'):
        record_generalization(members, reply(other, '```python\n' + SOURCE + '```'))

    class Client:
        def generate_result(self, prompt, **options):
            assert options == {'temperature': 0, 'max_tokens': 4096, 'seed': None, 'json_mode': False, 'think': None}
            return reply(prompt, '```python\n' + SOURCE + '```')

    record, source = generate_generalization(members, Client())
    assert source == SOURCE and record['status'] == 'unreviewed_source'


@pytest.mark.parametrize('change,reason', [
    ({'bindings': {'sum': {'operation': 'sum'}}}, 'cover_exactly_the_members'),
    ({'bindings': {'max': {'operation': 'x'}, 'sum': {'operation': 'x'}}}, 'distinguish_members'),
    ({'options': [{'name': 'operation', 'type': 'integer', 'description': 'code'}],
      'bindings': {'max': {'operation': True}, 'sum': {'operation': 0}}}, 'wrong_type'),
    ({'bindings': {'max': {}, 'sum': {'operation': 'sum'}}}, 'every_option'),
    ({'options': []}, 'one_to_eight_options'),
    ({'name': 'Bad Name'}, 'invalid_doc_name'),
])
def test_documentation_is_checked(change, reason):
    with pytest.raises(GeneralizationError, match=reason):
        checked_documentation({**DOC, **change}, ['max', 'sum'])


def admit_member(bound, reviews, ledger_path, monkeypatch, *, wrong=None):
    task = bound.get_task(bound.task_id)
    policy = ContainerPolicy(IMAGE)
    manifest = {'assignments': [
        {'case_id': case['id'],
         'proposal_id': prepare_admission_case(bound.task_id, case['id'], {'tool.py': SOURCE}, policy, reviews,
                                               corpus=bound)['proposal_id']}
        for case in task['cases']]}
    answers = {case['id']: case['expected']['result'] for case in task['cases']}
    if wrong:
        answers[wrong] = -999
    run_cases(reviews, monkeypatch, manifest, answers)
    return AdmissionLedger(ledger_path, corpus=bound).evaluate(reviews, bound.task_id, manifest['assignments'],
                                                               expected_corpus_sha256=bound.corpus_digest())


@pytest.mark.parametrize('wrong', [None, 'negative'])
def test_family_admission_spends_member_budgets_and_needs_every_member(tmp_path, monkeypatch, wrong):
    members = family()
    record, _ = record_generalization(members, generalized_reply(members))
    reviews, ledger = ReviewStore(tmp_path / 'r.sqlite3'), tmp_path / 'a.sqlite3'
    bound = {m.key: BoundMember(m, record['documentation']) for m in members}
    case = bound['sum'].get_case('integer-sum', get_task('integer-sum')['cases'][0]['id'])[1]
    assert set(case['args']) == {'data', 'options'} and case['args']['options'] == {'operation': 'sum'}
    assert bound['sum'].corpus_digest() == corpus_digest()
    summaries = {'sum': admit_member(bound['sum'], reviews, ledger, monkeypatch),
                 'max': admit_member(bound['max'], reviews, ledger, monkeypatch, wrong=wrong)}
    decision = family_decision(summaries, members)
    assert decision['admitted'] is (wrong is None) and decision['execution_authorized'] is False
    assert decision['members']['max']['held_out_passed'] == (3 if wrong is None else 2)
    # The generalized attempts used one slot of each member's own budget.
    assert AdmissionLedger(ledger).budget('integer-sum')['candidates_used'] == 1
    assert AdmissionLedger(ledger, corpus=members[1].source).budget('values-max')['candidates_used'] == 1
    if wrong is None:
        promoted = AdmissionLedger(ledger, corpus=bound['sum']).promote(
            VersionCatalog(tmp_path / 'v.sqlite3'), reviews, summaries['sum']['attempt'], confirm=True)
        assert promoted['name'] == 'general_reduce_values'


def test_family_decision_refuses_mixed_or_missing_members():
    members = family()
    summary = {'admitted': True, 'attempt': 1, 'held_out_passed': 5, 'held_out_total': 5, 'candidate_sha256': 'a' * 64}
    with pytest.raises(GeneralizationError, match='every_member'):
        family_decision({'sum': summary}, members)
    with pytest.raises(GeneralizationError, match='one_candidate'):
        family_decision({'sum': summary, 'max': {**summary, 'candidate_sha256': 'b' * 64}}, members)
    with pytest.raises(GeneralizationError, match='no_binding'):
        BoundMember(Member('other', 'median'), DOC)
