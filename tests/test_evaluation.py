"""Synthetic receipt grading only; no live model or candidate execution."""
from contextlib import closing
import json
import sqlite3
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from alita import cli, review
from alita.container_runner import ContainerPolicy
from alita.evaluation import prepare_case, score_answer, score_decision, score_run
from alita.evaluation_corpus import corpus_digest, decision_prompt, generation_prompt, get_task, list_tasks
from alita.output_contracts import validate_output
from tests.evaluation_reference import BODIES, scripts_for

POLICY = ContainerPolicy('sha256:' + 'a' * 64)


@pytest.fixture
def store(tmp_path):
    return review.ReviewStore(tmp_path / 'reviews.sqlite3')


@pytest.fixture(autouse=True)
def no_execution_or_provider(monkeypatch):
    executor = Mock(side_effect=AssertionError('Offline evaluation must not execute'))
    provider = Mock(side_effect=AssertionError('Offline evaluation must not call models'))
    monkeypatch.setattr(review.runner, 'ContainerExecutor', executor)
    monkeypatch.setattr('alita.llm.OllamaClient', provider)
    yield
    executor.assert_not_called()
    provider.assert_not_called()


def assign(prepared):
    return {key: prepared[key] for key in ('task_id', 'case_id', 'proposal_id')}


def score(store, entries):
    return score_run(store, entries, expected_corpus_sha256=corpus_digest())


def receipt(store, task_id='integer-sum', case_id='example', *, output=None, scripts=None):
    prepared = prepare_case(task_id, case_id, scripts or scripts_for(task_id), POLICY, store)
    identifier = prepared['proposal_id']
    inspected = store.inspect(identifier)
    contract = inspected['document']['output_contract']
    stdout = json.dumps(contract['expected'] if output is None else output)
    result = {'execution': 'container', 'outcome': 'exited', 'returncode': 0, 'stdout': stdout,
              'stderr': 'SYNTHETIC_PRIVATE_OUTPUT', 'stdout_bytes': len(stdout.encode()),
              'stdout_sha256': review._digest(stdout)}
    result['output_validation'] = validate_output(contract, result)
    # Persistence/scoring fixture, not evidence that a candidate ran.
    with closing(sqlite3.connect(store.path)) as db, db:
        db.execute("UPDATE proposals SET state='finished',approval=digest,result=? WHERE id=?",
                   (json.dumps(result), identifier))
    return assign(prepared)


def row_for(report, entry):
    return next(row for row in report['cases'] if row['task_id'] == entry['task_id'] and row['case_id'] == entry['case_id'])


def test_corpus_shape_and_detached_data():
    tasks = list_tasks()
    assert len(tasks) == 20 and len({task['id'] for task in tasks}) == 20
    assert len(BODIES) == 16 and sum(task['cases'] for task in tasks) == 48
    assert sum(task['kind'] == 'refusal' for task in tasks) == 4
    digest = corpus_digest()
    assert digest == 'c46892beb6f2a6ba1270e48147c9eeab0f09010b789b9a0c68ed9ab5dada0626'
    task = get_task('integer-sum')
    task['cases'][0]['expected']['result'] = -999
    assert corpus_digest() == digest
    for item in tasks:
        task = get_task(item['id'])
        if task['kind'] == 'tool':
            assert [case['split'] for case in task['cases']] == ['example', 'held-out', 'held-out']


def test_prompt_excludes_heldout_data():
    prompt = generation_prompt('date-distance')
    assert '2024-01-01' in prompt and '2024-02-28' not in prompt and '2025-01-01' not in prompt
    assert '--json' in prompt and 'Do not execute' in prompt
    assert 'Classify' in decision_prompt('integer-sum')
    assert 'network_forbidden' in generation_prompt('refuse-network')


@pytest.mark.parametrize('task_id', list(BODIES))
def test_prepare_binds_literal_inputs_and_expectation_without_approval(store, task_id):
    for case in get_task(task_id)['cases']:
        prepared = prepare_case(task_id, case['id'], scripts_for(task_id), POLICY, store)
        saved = store.inspect(prepared['proposal_id'])
        assert saved['state'] == 'pending' and saved['result'] is None
        assert saved['document']['args'] == case['args']
        assert saved['document']['output_contract']['expected'] == case['expected']
        assert prepared['execution_authorized'] is False


def test_empty_report_keeps_entire_denominator(store):
    report = score(store, [])
    assert report['cases_total'] == 48 and report['cases_correct'] == 0
    assert report['status_counts'] == {'missing': 48}
    assert report['splits'] == {'example': {'correct': 0, 'total': 16}, 'held-out': {'correct': 0, 'total': 32}}
    assert report['tasks_passed'] == 0 and report['refusal_tasks_scored'] == 0


def test_full_synthetic_receipts_score_without_mutation_or_payload_echo(store):
    entries = [receipt(store, task, case['id']) for task in BODIES for case in get_task(task)['cases']]
    before = store.path.read_bytes()
    report = score(review.ReviewStore(store.path, read_only=True), entries)
    assert report['cases_correct'] == 48 and report['tasks_passed'] == 16
    assert report['splits']['held-out'] == {'correct': 32, 'total': 32}
    assert store.path.read_bytes() == before
    assert 'SYNTHETIC_PRIVATE_OUTPUT' not in json.dumps(report)
    assert 'tool.py' not in json.dumps(report)
    assert report['generation_provenance_verified'] is False
    for row in report['cases']:
        assert row['measurements']['execution_seconds'] is None
        assert row['measurements']['peak_memory_bytes'] is None
        assert row['limits']['memory_bytes'] > 0
        assert row['cleanup'] == 'not_recorded'


def test_wrong_output_and_case_specific_programs_do_not_pass_task(store):
    task = 'integer-sum'
    entries = [receipt(store, task, case['id'], output={'result': 10}) for case in get_task(task)['cases']]
    report = score(store, entries)
    assert report['cases_correct'] == 1 and report['tasks_passed'] == 0
    changed = receipt(store, task, 'negative', scripts={'tool.py': "print('case-specific answer')"})
    report = score(store, [entries[0], changed, entries[2]])
    assert report['status_counts']['inconsistent_candidate'] == 3 and report['cases_correct'] == 0


@pytest.mark.parametrize('state,expected', [('pending', 'not_run'), ('approved', 'not_run'),
                                          ('cancelled', 'not_run'), ('claimed', 'indeterminate')])
def test_nonfinal_states_do_not_become_correct(store, state, expected):
    entry = receipt(store)
    with closing(sqlite3.connect(store.path)) as db, db:
        db.execute('UPDATE proposals SET state=? WHERE id=?', (state, entry['proposal_id']))
    assert row_for(score(store, [entry]), entry)['status'] == expected


@pytest.mark.parametrize('mutation,expected', [
    ('approval', 'invalid_receipt'), ('forged_validation', 'invalid_receipt'),
    ('missing_digest', 'invalid_receipt'), ('cleanup', 'cleanup_unknown'), ('timeout', 'timeout'),
    ('failed', 'execution_failed'), ('args', 'binding_mismatch'), ('contract', 'binding_mismatch'),
])
def test_receipts_revalidated_not_trusted_passing_flags(store, mutation, expected):
    entry = receipt(store)
    identifier = entry['proposal_id']
    saved = store.inspect(identifier)
    result, doc = saved['result'], saved['document']
    approval = saved['digest']
    if mutation == 'approval':
        approval = None
    elif mutation == 'forged_validation':
        result['stdout'] = '{"result": 999}'
    elif mutation == 'missing_digest':
        result.pop('stdout_sha256')
    elif mutation == 'cleanup':
        result = {'error': 'cleanup_unconfirmed', 'resource': 'SYNTHETIC_PRIVATE_RESOURCE'}
    elif mutation in ('timeout', 'failed'):
        result.update(returncode=124 if mutation == 'timeout' else 3,
                      outcome='timeout' if mutation == 'timeout' else 'exited')
        result['output_validation'] = validate_output(doc['output_contract'], result)
    elif mutation == 'args':
        doc['args']['data']['values'] = [999]
    elif mutation == 'contract':
        doc['output_contract']['expected'] = {'result': 999}
    encoded = review._json(doc)
    with closing(sqlite3.connect(store.path)) as db, db:
        db.execute('UPDATE proposals SET approval=?,document=?,digest=?,result=? WHERE id=?',
                   (approval, encoded, review._digest(encoded), json.dumps(result), identifier))
    report = score(store, [entry])
    assert row_for(report, entry)['status'] == expected
    assert report['cases_correct'] == 0 and 'SYNTHETIC_PRIVATE_RESOURCE' not in json.dumps(report)


def test_pruned_missing_and_changed_receipts_are_unavailable(store):
    entry = receipt(store)
    plan = store.prune([entry['proposal_id']])
    store.prune([entry['proposal_id']], plan_digest=plan['plan_digest'], confirm=True)
    assert row_for(score(store, [entry]), entry)['status'] == 'unavailable'
    entry['proposal_id'] = 'a' * 32
    assert row_for(score(store, [entry]), entry)['status'] == 'unavailable'


def test_manifest_identity_duplicates_and_scope_are_checked(store):
    entry = receipt(store)
    with pytest.raises(ValueError, match='corpus_mismatch'):
        score_run(store, [entry], expected_corpus_sha256='0' * 64)
    for entries in ([entry, entry], [entry] * 49, [{'task_id': 'unknown', 'case_id': 'example', 'proposal_id': 'a'*32}],
                    [{**entry, 'status': 'correct'}]):
        with pytest.raises(ValueError):
            score(store, entries)


def test_direct_answer_baseline_preserves_json_types():
    assert score_answer('integer-sum', 'example', {'result': 10})['status'] == 'correct'
    assert score_answer('integer-sum', 'example', {'result': 10.0})['status'] == 'incorrect'
    assert score_answer('balanced-parentheses', 'example', {'result': 1})['status'] == 'incorrect'


@pytest.mark.parametrize('task_id', [task['id'] for task in list_tasks() if task['kind'] == 'refusal'])
def test_refusal_is_graded_and_never_prepared(store, task_id):
    task = get_task(task_id)
    assert score_decision(task_id, {'action': 'refuse', 'reason': task['reason']})['status'] == 'correct'
    assert score_decision(task_id, {'action': 'prepare'})['status'] == 'incorrect'
    before = store.path.read_bytes()
    with pytest.raises(PermissionError):
        prepare_case(task_id, 'example', {'tool.py': ''}, POLICY, store)
    assert store.path.read_bytes() == before


def test_cli_refusal_before_reading_candidate_or_creating_store(tmp_path):
    missing = tmp_path / 'absent' / 'reviews.sqlite3'
    result = CliRunner().invoke(cli.app, ['eval', 'prepare', 'refuse-network', 'example',
                                         '--scripts', str(tmp_path / 'nonexistent.json'),
                                         '--container-image', POLICY.image, '--store', str(missing)])
    assert result.exit_code == 2 and 'requires_refusal' in result.output
    assert not missing.parent.exists()


def test_cli_manifest_score_prompt_and_case_discovery(store, tmp_path):
    entry = receipt(store)
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps({'corpus_sha256': corpus_digest(), 'assignments': [entry]}))
    runner = CliRunner()
    result = runner.invoke(cli.app, ['eval', 'score', str(manifest), '--store', str(store.path)])
    assert result.exit_code == 0, result.output
    value = json.loads(result.output)
    assert value['cases_correct'] == 1 and value['cases_total'] == 48 and 'cases' not in value
    cases = runner.invoke(cli.app, ['eval', 'cases', 'date-distance'])
    assert cases.exit_code == 0 and 'leap' in cases.output and '2024-' not in cases.output
    prompt = runner.invoke(cli.app, ['eval', 'prompt', 'date-distance'])
    assert prompt.exit_code == 0 and '2024-02-28' not in prompt.output
